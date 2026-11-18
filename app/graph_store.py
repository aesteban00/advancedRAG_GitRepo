# ============================================================
#  graph_store.py  -  GraphRAG con MongoDB (guia oficial MongoDB + LangChain)
#
#  Cada ENTIDAD es UN documento de la coleccion knowledge_graph; las ARISTAS
#  viven dentro del documento origen (relationships.target_ids/types/attributes).
#  La consulta recorre el grafo DENTRO de la base de datos con $graphLookup:
#  no hay que cargar el grafo entero en memoria ni mantener una base de grafos
#  aparte. Ventaja MongoDB: documentos + vectores + grafo en el mismo cluster.
#
#  Convencion de _id (para que el grafo determinista y el del LLM coincidan):
#    Repository  owner/repo (minusculas)        Library   nombre del paquete
#    Database/Service  MongoDB, Redis, Kafka... Endpoint  "GET /users @ owner/repo"
#    Team  @org/equipo                          File      owner/repo/ruta
#    Class/Function  owner/repo/ruta::Nombre    Document  nombre del fichero
# ============================================================

from __future__ import annotations

import re

from pymongo import UpdateOne

import config
import db
import loaders
import settings

ID_RULES = ("Repository: owner/repo en minusculas. Library: nombre del paquete en minusculas. "
            "Database/Service: nombre canonico (MongoDB, Redis, Kafka). "
            "Endpoint: 'GET /ruta @ owner/repo'. Document: nombre del fichero.")

_store = None
_store_key = None


def get_store():
    """MongoDBGraphStore (LangChain) cacheado; se reconstruye si cambia el LLM de grafo."""
    global _store, _store_key
    from langchain_mongodb.graphrag.graph import MongoDBGraphStore
    from langchain_openai import ChatOpenAI

    cfg = settings.llm("graph")
    key = (cfg["base_url"], cfg["model"], cfg["api_key"])
    if _store is None or key != _store_key:
        if not cfg["api_key"]:
            raise RuntimeError("Falta la API key del LLM de grafo (.env o Configuracion)")
        # timeout: una llamada que no responde no puede bloquear la ingesta para siempre.
        model = ChatOpenAI(model=cfg["model"], api_key=cfg["api_key"], base_url=cfg["base_url"], temperature=0,
                           timeout=config.LLM_TIMEOUT_S, max_retries=config.LLM_MAX_RETRIES)
        _store = MongoDBGraphStore(
            collection=db.coll(config.COLL_GRAPH),
            entity_extraction_model=model,
            max_depth=3,
            allowed_entity_types=config.GRAPH_ENTITY_TYPES,
            allowed_relationship_types=config.GRAPH_RELATIONSHIP_TYPES,
            entity_name_examples=ID_RULES,
        )
        _store_key = key
    return _store


def reset_store() -> None:
    global _store
    _store = None


def _as_list(v) -> list:
    return list(v) if isinstance(v, (list, tuple)) else [v]


def _norm_attrs(attrs: dict | None) -> dict:
    return {k: _as_list(v) for k, v in (attrs or {}).items()}


def make_entity(_id: str, type: str, source: str, attributes: dict | None = None,
                relationships: list[tuple[str, str, dict]] | None = None) -> dict:
    """Entidad en el formato de MongoDBGraphStore. relationships: [(destino, tipo, attrs)]."""
    rels = relationships or []
    return {
        "_id": _id, "type": type,
        "attributes": {**_norm_attrs(attributes), "sources": [source]},
        "relationships": {"target_ids": [r[0] for r in rels], "types": [r[1] for r in rels],
                          "attributes": [_norm_attrs(r[2] if len(r) > 2 else {}) for r in rels]},
    }


def _bulk_upsert(entities: list[dict]) -> int:
    """Escritura determinista (sin LLM): upsert + $addToSet de atributos + relaciones sin duplicar."""
    coll = db.coll(config.COLL_GRAPH)
    ops = []
    for e in entities:
        rel = e.get("relationships") or {}
        t_ids, types, attrs = rel.get("target_ids", []), rel.get("types", []), rel.get("attributes", [])
        existing = coll.find_one({"_id": e["_id"]}, {"relationships": 1}) or {}
        have = set(zip(existing.get("relationships", {}).get("target_ids", []),
                       existing.get("relationships", {}).get("types", [])))
        new = []
        for i, (t, ty) in enumerate(zip(t_ids, types)):
            if (t, ty) not in have:
                have.add((t, ty))
                new.append((t, ty, attrs[i] if i < len(attrs) else {}))
        update = {"$setOnInsert": {"_id": e["_id"], "type": e["type"]}}
        adds = {f"attributes.{k}": {"$each": _as_list(v)} for k, v in (e.get("attributes") or {}).items()}
        if adds:
            update["$addToSet"] = adds
        if new:
            update["$push"] = {"relationships.target_ids": {"$each": [n[0] for n in new]},
                               "relationships.types": {"$each": [n[1] for n in new]},
                               "relationships.attributes": {"$each": [n[2] for n in new]}}
        # $setOnInsert no puede coexistir con _id en el filtro si repetimos _id: lo quitamos.
        update["$setOnInsert"].pop("_id")
        ops.append(UpdateOne({"_id": e["_id"]}, update, upsert=True))
    if ops:
        coll.bulk_write(ops)
    return len(ops)


def upsert_entities(entities: list[dict]) -> int:
    return _bulk_upsert(entities)


def add_text(text: str, source: str) -> int:
    """El LLM extrae entidades/relaciones de cada trozo; se guardan con su fuente."""
    total = 0
    for i, piece in enumerate(loaders.split_text(text, config.GRAPH_CHUNK_SIZE, 200)):
        try:
            entities = get_store().extract_entities(piece)
        except Exception as exc:
            print(f"[grafo] AVISO trozo {i}: {exc}")
            continue
        for e in entities:
            e["attributes"] = {**_norm_attrs(e.get("attributes")), "sources": [source]}
        total += _bulk_upsert(entities)
    return total


def _resolve(names: list[str]) -> list[str]:
    coll, ids = db.coll(config.COLL_GRAPH), []
    for n in names:
        found = coll.find_one({"_id": n}, {"_id": 1})
        if not found:
            found = coll.find_one({"_id": {"$regex": f"^{re.escape(n)}$", "$options": "i"}}, {"_id": 1})
        if found:
            ids.append(found["_id"])
        else:
            ids += [d["_id"] for d in coll.find({"_id": {"$regex": re.escape(n), "$options": "i"}}, {"_id": 1}).limit(3)]
    return list(dict.fromkeys(ids))


def neighborhood(entity_id: str, depth: int) -> list[dict]:
    return _expand([entity_id], depth)


def _expand(start: list[str], depth: int) -> list[dict]:
    if not start:
        return []
    # Salientes: $graphLookup (recorrido recursivo dentro de MongoDB).
    out = get_store().related_entities(start, max_depth=depth)
    # Entrantes (1 salto): "quien usa X?" -> indice multikey sobre relationships.target_ids.
    incoming = list(db.coll(config.COLL_GRAPH).find({"relationships.target_ids": {"$in": start}}).limit(50))
    merged = {e["_id"]: e for e in out + incoming}
    return list(merged.values())[:60]


def retrieve(question: str, depth: int) -> dict:
    try:
        names = get_store().extract_entity_names(question)
    except Exception as exc:
        print(f"[grafo] AVISO extrayendo entidades de la pregunta: {exc}")
        names = []
    start = _resolve([n for n in names if isinstance(n, str)])
    return {"start": start, "entities": _expand(start, depth)}


CODE_TYPES = ["File", "Class", "Function"]  # ruido de codigo: se ocultan en el resumen


def overview(entity_type: str | None = None) -> list[dict]:
    """Resumen del grafo. Sin tipo: las entidades MAS conectadas de cualquier clase
    (repos, equipos, conceptos, documentos...), sin distinguir el origen."""
    coll = db.coll(config.COLL_GRAPH)
    if entity_type:
        base = list(coll.find({"type": entity_type}).limit(200))
    else:
        base = list(coll.aggregate([
            {"$match": {"type": {"$nin": CODE_TYPES}}},
            {"$addFields": {"n": {"$size": {"$ifNull": ["$relationships.target_ids", []]}}}},
            {"$sort": {"n": -1}}, {"$limit": 40}]))
    targets = {t for e in base for t in e.get("relationships", {}).get("target_ids", [])}
    extra = list(coll.find({"_id": {"$in": list(targets)}, "type": {"$nin": CODE_TYPES}}))
    return list({e["_id"]: e for e in base + extra}.values())


def direct_neighbors(entity_id: str) -> list[dict]:
    """La entidad y sus vecinos a UN salto (salientes y entrantes): para expandir un nodo."""
    coll = db.coll(config.COLL_GRAPH)
    root = coll.find_one({"_id": entity_id})
    if not root:
        return []
    tids = root.get("relationships", {}).get("target_ids", [])
    out = list(coll.find({"_id": {"$in": tids}}))
    inc = list(coll.find({"relationships.target_ids": entity_id}).limit(50))
    return list({e["_id"]: e for e in [root] + out + inc}.values())[:60]


def search(q: str, limit: int = 10) -> list[dict]:
    """Autocompletado por nombre (indice sobre _id)."""
    if not q.strip():
        return []
    cur = db.coll(config.COLL_GRAPH).find(
        {"_id": {"$regex": re.escape(q.strip()), "$options": "i"}}, {"type": 1}).limit(limit)
    return [{"id": d["_id"], "type": d.get("type", "?")} for d in cur]


def entity_detail(entity_id: str) -> dict:
    """Ficha de una entidad: atributos, fuentes y relaciones salientes y entrantes."""
    coll = db.coll(config.COLL_GRAPH)
    doc = coll.find_one({"_id": entity_id})
    if not doc:
        raise ValueError(f"Entidad no encontrada: {entity_id}")
    rel = doc.get("relationships") or {}
    tids, types = rel.get("target_ids", []), rel.get("types", [])
    tmap = {d["_id"]: d.get("type", "?") for d in coll.find({"_id": {"$in": tids}}, {"type": 1})}
    outgoing = [{"id": t, "type": tmap.get(t, "?"), "rel": types[i] if i < len(types) else ""}
                for i, t in enumerate(tids)]
    incoming = []
    for d in coll.find({"relationships.target_ids": entity_id}, {"type": 1, "relationships": 1}).limit(100):
        r = d.get("relationships") or {}
        rt = r.get("types", [])
        incoming += [{"id": d["_id"], "type": d.get("type", "?"), "rel": rt[i] if i < len(rt) else ""}
                     for i, t in enumerate(r.get("target_ids", [])) if t == entity_id]
    attrs = dict(doc.get("attributes") or {})
    return {"id": doc["_id"], "type": doc.get("type", "?"), "sources": attrs.pop("sources", []),
            "attributes": attrs, "outgoing": outgoing, "incoming": incoming}


def _bfs(adj: dict[str, list[str]], a: str, b: str) -> list[str] | None:
    """Camino mas corto de a a b en un grafo dirigido (funcion pura, testeable)."""
    prev, queue = {a: None}, [a]
    for node in queue:
        if node == b:
            path = []
            while node is not None:
                path.append(node)
                node = prev[node]
            return path[::-1]
        for nxt in adj.get(node, []):
            if nxt not in prev:
                prev[nxt] = node
                queue.append(nxt)
    return None


def _reach(a: str, b: str, max_hops: int) -> list[str] | None:
    # Ventaja MongoDB: $graphLookup trae TODO lo alcanzable desde a (hasta max_hops) en una sola consulta.
    pipe = [{"$match": {"_id": a}},
            {"$graphLookup": {"from": config.COLL_GRAPH, "startWith": "$relationships.target_ids",
                              "connectFromField": "relationships.target_ids", "connectToField": "_id",
                              "as": "conn", "maxDepth": max_hops - 1}}]
    res = list(db.coll(config.COLL_GRAPH).aggregate(pipe))
    if not res:
        return None
    docs = [res[0]] + res[0]["conn"]
    adj = {d["_id"]: d.get("relationships", {}).get("target_ids", []) for d in docs}
    return _bfs(adj, a, b)


def find_path(source: str, target: str, max_hops: int = 6) -> dict:
    """Camino entre dos entidades (en cualquier sentido). -> {"path": [ids], "direction": ...}"""
    for a, b, direction in ((source, target, "forward"), (target, source, "reverse")):
        path = _reach(a, b, max_hops)
        if path:
            return {"path": path, "direction": direction}
    return {"path": [], "direction": None}


def path_entities(path: list[str]) -> list[dict]:
    """Entidades del camino, con solo las relaciones que unen nodos del camino."""
    keep = set(path)
    ents = list(db.coll(config.COLL_GRAPH).find({"_id": {"$in": path}}))
    for e in ents:
        r = e.get("relationships") or {}
        idx = [i for i, t in enumerate(r.get("target_ids", [])) if t in keep]
        e["relationships"] = {k: [r.get(k, [])[i] for i in idx if i < len(r.get(k, []))]
                              for k in ("target_ids", "types", "attributes")}
    return ents


def _drop_targets(rel: dict, gone: set) -> tuple[dict, int]:
    """Quita de una entidad las relaciones cuyo destino ya no existe. Las tres listas de
    `relationships` van en paralelo (por posicion), asi que se filtran por indice. -> (nuevo, n_quitadas)."""
    ids = rel.get("target_ids", [])
    keep = [i for i, t in enumerate(ids) if t not in gone]
    new = {k: [rel.get(k, [])[i] for i in keep if i < len(rel.get(k, []))]
           for k in ("target_ids", "types", "attributes")}
    return new, len(ids) - len(keep)


def remove_source(pattern: str) -> dict:
    """Borra del grafo lo que aporto una fuente (regex sobre attributes.sources).
    1) Se QUITA la fuente de cada entidad. Una entidad puede venir de varias fuentes
       (p. ej. "Banco Sabadell" en varios documentos): mientras le quede alguna, se conserva.
    2) Las entidades que se quedan SIN fuentes se eliminan.
    3) Se limpian las relaciones que apuntaban a las eliminadas.
    Limite: los atributos y relaciones salientes de una entidad que se conserva no se atribuyen
    a una fuente concreta, asi que permanecen."""
    coll = db.coll(config.COLL_GRAPH)
    q = {"attributes.sources": {"$regex": pattern}}
    touched = [d["_id"] for d in coll.find(q, {"_id": 1})]
    if not touched:
        return {"entities_updated": 0, "entities_deleted": 0, "edges_removed": 0}
    coll.update_many(q, {"$pull": {"attributes.sources": {"$regex": pattern}}})
    orphans = [d["_id"] for d in coll.find({"_id": {"$in": touched}, "attributes.sources": {"$size": 0}}, {"_id": 1})]
    removed = 0
    if orphans:
        coll.delete_many({"_id": {"$in": orphans}})
        gone, ops = set(orphans), []
        for d in coll.find({"relationships.target_ids": {"$in": orphans}}, {"relationships": 1}):
            new, n = _drop_targets(d["relationships"], gone)
            removed += n
            ops.append(UpdateOne({"_id": d["_id"]}, {"$set": {"relationships": new}}))
        if ops:
            coll.bulk_write(ops)
    return {"entities_updated": len(touched) - len(orphans), "entities_deleted": len(orphans), "edges_removed": removed}


def count() -> int:
    return db.coll(config.COLL_GRAPH).estimated_document_count()
