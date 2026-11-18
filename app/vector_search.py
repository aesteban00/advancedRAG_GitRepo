# ============================================================
#  vector_search.py
#  $vectorSearch (+ $rerank) sobre las 3 colecciones de chunks.
#  Ventaja MongoDB: con autoEmbed ni siquiera generamos el vector de la
#  pregunta; Atlas lo hace con el mismo modelo del indice.
# ============================================================

from __future__ import annotations

import re

from pymongo.errors import OperationFailure

import config
import db
import embeddings
import settings
from setup_indexes import auto_index_name


def _rerank_stage(query: str) -> list[dict]:
    if not config.RERANK_ENABLED:
        return []
    return [{"$rerank": {"model": config.RERANK_MODEL, "query": {"text": query},
                         "numDocsToRerank": config.RERANK_NUM_DOCS, "path": "text"}},
            {"$addFields": {"rerankScore": {"$meta": "score"}}}]


def _project_stage(coll_name: str) -> dict:
    score = "$rerankScore" if config.RERANK_ENABLED else {"$meta": "vectorSearchScore"}
    return {"$project": {"text": 1, "metadata": 1, "score": score, "collection": {"$literal": coll_name}}}


def _visibility_filter(user_id: str) -> dict:
    return {"$or": [{"metadata.visibility": "public"}, {"metadata.owner": user_id}]}


def _filter(user_id: str, model: str) -> dict:
    return {"$and": [_visibility_filter(user_id), {"metadata.model": model}]}


def _run(coll_name: str, stage: dict, query: str) -> list[dict]:
    pipeline = [{"$vectorSearch": stage}, *_rerank_stage(query), _project_stage(coll_name)]
    return list(db.coll(coll_name).aggregate(pipeline))


def _search_auto(query: str, user_id: str, top_k: int) -> list[dict]:
    model = settings.get()["embedding"]["auto_embed"]
    stage = {"index": auto_index_name(model), "path": "text", "query": {"text": query},
             "numCandidates": top_k * 20, "limit": top_k, "filter": _filter(user_id, model)}
    try:
        return _run(config.COLL_AUTO, stage, query)
    except OperationFailure as exc:
        if "query" not in str(exc).lower():
            raise
        # Versiones preview de autoEmbed usaban "query" como string.
        return _run(config.COLL_AUTO, {**stage, "query": query}, query)


def _search_context(query: str, user_id: str, top_k: int) -> list[dict]:
    model = settings.get()["embedding"]["voyage_context"]
    stage = {"index": config.VECTOR_INDEX_CONTEXT, "path": "embedding",
             "queryVector": embeddings.embed_context([query], model, "query")[0],
             "numCandidates": top_k * 20, "limit": top_k, "filter": _filter(user_id, model)}
    return _run(config.COLL_CONTEXT, stage, query)


def _search_multimodal(query: str, user_id: str, top_k: int) -> list[dict]:
    model = settings.get()["embedding"]["voyage_multimodal"]
    stage = {"index": config.VECTOR_INDEX_MULTIMODAL, "path": "embedding",
             "queryVector": embeddings.embed_multimodal([query], model, "query"),
             "numCandidates": top_k * 20, "limit": top_k, "filter": _filter(user_id, model)}
    return _run(config.COLL_MULTIMODAL, stage, query)


def search(query: str, user_id: str, top_k: int) -> list[dict]:
    """Busca en las 3 colecciones (salta las vacias) y concatena: son espacios
    vectoriales distintos, asi que no se ordenan entre si (simplificacion didactica)."""
    results = []
    for name, fn in ((config.COLL_AUTO, _search_auto), (config.COLL_CONTEXT, _search_context),
                     (config.COLL_MULTIMODAL, _search_multimodal)):
        try:
            if db.coll(name).estimated_document_count() == 0:
                continue
            results += fn(query, user_id, top_k)
        except Exception as exc:
            print(f"[aviso] busqueda en {name}: {exc}")
    return results


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
