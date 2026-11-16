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
        model = ChatOpenAI(model=cfg["model"], api_key=cfg["api_key"], base_url=cfg["base_url"], temperature=0)
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


def overview(entity_type: str = "Repository") -> list[dict]:
    coll = db.coll(config.COLL_GRAPH)
    base = list(coll.find({"type": entity_type}).limit(200))
    targets = {t for e in base for t in e.get("relationships", {}).get("target_ids", [])}
    extra = list(coll.find({"_id": {"$in": list(targets)},
                            "type": {"$in": ["Repository", "Library", "Database", "Service"]}}))
    return list({e["_id"]: e for e in base + extra}.values())


def count() -> int:
    return db.coll(config.COLL_GRAPH).estimated_document_count()
