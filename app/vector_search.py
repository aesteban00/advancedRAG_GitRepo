# ============================================================
#  vector_search.py
#  Busqueda en las 3 colecciones de chunks. Tres modos (Configuracion):
#    vector  -> $vectorSearch (significado)
#    bm25    -> $search       (palabras exactas, BM25)
#    hybrid  -> $rankFusion(vectorSearch + search): la BASE DE DATOS fusiona
#               ambos rankings con Reciprocal Rank Fusion (RRF)
#  y despues $rerank. Por que hibrida: la vectorial entiende el significado
#  pero falla con siglas, codigos o nombres propios; BM25 acierta con esos
#  terminos exactos pero no entiende sinonimos. Juntas se compensan.
#  Ventaja MongoDB: mismo documento, indice vectorial + indice de texto +
#  fusion + rerank en UNA sola agregacion. Con autoEmbed ni siquiera se
#  genera el vector de la pregunta: lo hace Atlas con el modelo del indice.
# ============================================================

from __future__ import annotations

import re

from pymongo.errors import OperationFailure

import config
import db
import embeddings
import settings
from setup_indexes import auto_index_name

POOL = 3  # candidatos por pipeline = top_k * POOL: se fusionan y rerankean, y luego se recortan a top_k


def _rerank_stage(query: str) -> list[dict]:
    if not config.RERANK_ENABLED:
        return []
    return [{"$rerank": {"model": config.RERANK_MODEL, "query": {"text": query},
                         "numDocsToRerank": config.RERANK_NUM_DOCS, "path": "text"}},
            {"$addFields": {"rerankScore": {"$meta": "score"}}}]


def _project_stage(coll_name: str) -> dict:
    score = "$rerankScore" if config.RERANK_ENABLED else {"$meta": "score"}
    return {"$project": {"text": 1, "metadata": 1, "score": score, "_sd": 1,
                         "collection": {"$literal": coll_name}}}


def _visibility_filter(user_id: str) -> dict:
    return {"$or": [{"metadata.visibility": "public"}, {"metadata.owner": user_id}]}


def _filter(user_id: str, model: str) -> dict:
    return {"$and": [_visibility_filter(user_id), {"metadata.model": model}]}


def _lexical_stage(query: str, user_id: str, model: str) -> dict:
    """$search (BM25). `text` se busca con el analizador estandar (terminos exactos) y con el de
    espanol (stemming). Los filtros usan campos `token` del indice, igual que el pre-filtro vectorial."""
    eq = lambda path, value: {"equals": {"path": path, "value": value}}
    return {"$search": {"index": config.TEXT_INDEX, "compound": {
        "must": [{"text": {"query": query, "path": ["text", {"value": "text", "multi": "es"}]}}],
        "filter": [{"compound": {"should": [eq("metadata.visibility", "public"), eq("metadata.owner", user_id)],
                                 "minimumShouldMatch": 1}},
                   eq("metadata.model", model)]}}}


def _pipeline(vec: dict | None, lex: dict | None, mode: str, pool: int) -> list[dict]:
    """Etapas de recuperacion segun el modo (antes del rerank)."""
    if mode == "vector":
        return [{"$vectorSearch": vec}]
    if mode == "bm25":
        return [lex, {"$limit": pool}]
    fusion = {"$rankFusion": {
        "input": {"pipelines": {"vector": [{"$vectorSearch": vec}], "bm25": [lex, {"$limit": pool}]}},
        "combination": {"weights": config.RRF_WEIGHTS},
        "scoreDetails": True}}   # scoreDetails: rango de cada resultado en cada pipeline
    return [fusion, {"$addFields": {"_sd": {"$meta": "scoreDetails"}}}]


def _annotate(doc: dict, mode: str) -> dict:
    """Anade de donde sale el fragmento: found_by (['vector','bm25']) y ranks ({'vector': 2, 'bm25': 1})."""
    sd = doc.pop("_sd", None) or {}
    if mode == "hybrid":
        # Si el fragmento no estaba en un pipeline, $rankFusion devuelve rank "NA": no cuenta como hallazgo.
        ranks = {d["inputPipelineName"]: d["rank"] for d in sd.get("details", [])
                 if "inputPipelineName" in d and isinstance(d.get("rank"), int)}
        doc["found_by"], doc["ranks"] = sorted(ranks), ranks
    else:
        doc["found_by"], doc["ranks"] = ["vector" if mode == "vector" else "bm25"], {}
    doc["mode"] = mode
    return doc


def _targets(query: str) -> list[tuple[str, str, callable]]:
    """(coleccion, modelo, funcion que construye la etapa $vectorSearch). Es perezosa: el embedding
    de la pregunta solo se pide si se va a usar (en modo bm25 no se llama a Voyage)."""
    m = settings.get()["embedding"]
    return [
        (config.COLL_AUTO, m["auto_embed"],
         lambda md: {"index": auto_index_name(md), "path": "text", "query": {"text": query}}),
        (config.COLL_CONTEXT, m["voyage_context"],
         lambda md: {"index": config.VECTOR_INDEX_CONTEXT, "path": "embedding",
                     "queryVector": embeddings.embed_context([query], md, "query")[0]}),
        (config.COLL_MULTIMODAL, m["voyage_multimodal"],
         lambda md: {"index": config.VECTOR_INDEX_MULTIMODAL, "path": "embedding",
                     "queryVector": embeddings.embed_multimodal([query], md, "query")}),
    ]


def _search_collection(name: str, model: str, vec_fn, query: str, user_id: str, top_k: int, mode: str) -> list[dict]:
    pool = top_k * POOL
    vec = None if mode == "bm25" else {**vec_fn(model), "numCandidates": pool * 20, "limit": pool,
                                       "filter": _filter(user_id, model)}
    lex = None if mode == "vector" else _lexical_stage(query, user_id, model)

    def run(v):
        pipe = _pipeline(v, lex, mode, pool) + _rerank_stage(query) + [{"$limit": top_k}, _project_stage(name)]
        return list(db.coll(name).aggregate(pipe))

    try:
        docs = run(vec)
    except OperationFailure as exc:
        if name != config.COLL_AUTO or vec is None or "query" not in str(exc).lower():
            raise
        docs = run({**vec, "query": query})   # versiones preview de autoEmbed: "query" como string
    return [_annotate(d, mode) for d in docs]


def search(query: str, user_id: str, top_k: int, mode: str | None = None) -> tuple[list[dict], list[str]]:
    """Busca en las 3 colecciones (salta las vacias) y concatena: son espacios vectoriales distintos,
    asi que no se ordenan entre si. Devuelve (resultados, avisos). Si $search/$rankFusion no estan
    disponibles (indice sin crear, cluster antiguo...) se recurre a la busqueda vectorial y se avisa."""
    mode = mode or settings.get()["retrieval"]["search_mode"]
    results, warnings = [], []
    for name, model, vec_fn in _targets(query):
        try:
            if db.coll(name).estimated_document_count() == 0:
                continue
            results += _search_collection(name, model, vec_fn, query, user_id, top_k, mode)
        except Exception as exc:
            print(f"[aviso] busqueda {mode} en {name}: {exc}")
            if mode == "vector":
                continue
            warnings.append(f"{name}: {mode} no disponible, se uso solo la busqueda vectorial")
            try:
                results += _search_collection(name, model, vec_fn, query, user_id, top_k, "vector")
            except Exception as exc2:
                print(f"[aviso] busqueda vector en {name}: {exc2}")
    return results, warnings


def _repo_items(user_id: str) -> list[dict]:
    """Repos de GitHub visibles para el usuario (nodos Repository del grafo) con sus chunks de documentacion."""
    vis = {"$or": [{"attributes.visibility": "public"}, {"attributes.owner_user": user_id}]}
    coll = db.coll(config.COLL_GRAPH)
    out = []
    for r in coll.find({"type": "Repository", "attributes.sources": {"$regex": "^github:"}, **vis}):
        rid = r["_id"]
        if rid.count("/") != 1:
            continue
        attrs = r.get("attributes", {})
        chunks = sum(db.coll(n).count_documents({"metadata.source": {"$regex": f"^{re.escape(rid)}/"}})
                     for n in (config.COLL_AUTO, config.COLL_CONTEXT, config.COLL_MULTIMODAL))
        out.append({"source": rid, "kind": "repo", "owner": (attrs.get("owner_user") or ["?"])[0],
                    "visibility": (attrs.get("visibility") or ["public"])[0],
                    "strategy": "github", "chunks": chunks,
                    "language": (attrs.get("language") or [""])[0], "url": (attrs.get("url") or [""])[0]})
    return out


def list_documents(user_id: str) -> dict:
    # Los chunks de README/docs de repos se listan dentro de su repo, no como documentos sueltos.
    pipeline = [
        {"$match": {**_visibility_filter(user_id), "metadata.source_type": {"$ne": "github"}}},
        {"$group": {"_id": {"source": "$metadata.source", "owner": "$metadata.owner",
                            "visibility": "$metadata.visibility", "strategy": "$metadata.strategy"},
                    "chunks": {"$sum": 1}}},
    ]
    docs = []
    for n in (config.COLL_AUTO, config.COLL_CONTEXT, config.COLL_MULTIMODAL):
        docs += [{**r["_id"], "chunks": r["chunks"]} for r in db.coll(n).aggregate(pipeline)]
    for d in docs:
        d.setdefault("kind", "file")
    docs += _repo_items(user_id)
    docs.sort(key=lambda d: d["source"] or "")
    return {"public": [d for d in docs if d["visibility"] == "public"],
            "private": [d for d in docs if d["visibility"] == "private" and d["owner"] == user_id]}


def counts() -> dict:
    return {n: db.coll(n).estimated_document_count()
            for n in (config.COLL_AUTO, config.COLL_CONTEXT, config.COLL_MULTIMODAL)}
