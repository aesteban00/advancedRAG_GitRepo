# ============================================================
#  vector_search.py
#  ------------------------------------------------------------------
#  Busca en MongoDB Atlas los chunks mas relevantes para una pregunta
#  usando Atlas Vector Search ($vectorSearch) + re-ranking ($rerank).
#
#  Buscamos en DOS colecciones (porque hay dos estrategias):
#    * documents_text      -> chunks de texto (voyage-context-4)
#    * documents_multimodal-> chunks con imagenes (voyage-multimodal)
#  Y unimos los resultados como contexto para el LLM.
#
#  El $rerank usa un modelo de Voyage AI para REORDENAR los resultados
#  de la busqueda vectorial segun su relevancia real a la pregunta,
#  mejorando la precision de la respuesta final.
# ============================================================

from __future__ import annotations

from pymongo import MongoClient

import config
import embeddings

TOP_K = 4  # cuantos chunks recuperamos por coleccion


def _client() -> MongoClient:
    if not config.MONGODB_URI:
        raise RuntimeError("Falta MONGODB_URI en el .env")
    return MongoClient(config.MONGODB_URI)


def _rerank_stage(query: str) -> list[dict]:
    """Devuelve los stages de re-ranking ($rerank + extraccion del score).

    Si RERANK_ENABLED es false, devolvemos una lista vacia (sin rerank).
    $rerank reordena los documentos usando el texto de la pregunta y el
    campo "text" de cada documento. El nuevo score se guarda en
    "rerankScore" con $addFields.
    """
    if not config.RERANK_ENABLED:
        return []

    return [
        {
            "$rerank": {
                "model": config.RERANK_MODEL,
                "query": {"text": query},
                "numDocsToRerank": config.RERANK_NUM_DOCS,
                "path": "text",
            }
        },
        {"$addFields": {"rerankScore": {"$meta": "score"}}},
    ]


def _project_stage() -> dict:
    """Proyecta los campos que nos interesan y el score final.

    Si hay rerank, el score relevante es rerankScore; si no, usamos el
    score de la busqueda vectorial.
    """
    if config.RERANK_ENABLED:
        return {"$project": {"text": 1, "metadata": 1, "score": "$rerankScore"}}
    return {"$project": {"text": 1, "metadata": 1, "score": {"$meta": "vectorSearchScore"}}}


def _visibility_filter(user_id: str) -> dict:
    """Un usuario ve los documentos publicos y los privados que subio el."""
    return {"$or": [
        {"metadata.visibility": "public"},
        {"metadata.owner": user_id},
    ]}


def _search_text(query: str, user_id: str) -> list[dict]:
    """Ejecuta $vectorSearch (+ $rerank) sobre la coleccion de texto."""
    coll = _client()[config.MONGODB_DB][config.COLL_TEXT]
    vector = embeddings.embed_query_text_manual(query)

    pipeline = [
        {
            "$vectorSearch": {
                "index": config.VECTOR_INDEX_TEXT_MANUAL,
                "path": "embedding",
                "queryVector": vector,
                "numCandidates": TOP_K * 10,
                "limit": TOP_K,
                "filter": _visibility_filter(user_id),
            }
        },
        *_rerank_stage(query),
        _project_stage(),
    ]
    return list(coll.aggregate(pipeline))


def _search_multimodal(query: str, user_id: str) -> list[dict]:
    """Ejecuta $vectorSearch (+ $rerank) sobre la coleccion multimodal."""
    coll = _client()[config.MONGODB_DB][config.COLL_MULTIMODAL]
    vector = embeddings.embed_query_multimodal_manual(query)

    pipeline = [
        {
            "$vectorSearch": {
                "index": config.VECTOR_INDEX_MULTIMODAL,
                "path": "embedding",
                "queryVector": vector,
                "numCandidates": TOP_K * 10,
                "limit": TOP_K,
                "filter": _visibility_filter(user_id),
            }
        },
        *_rerank_stage(query),
        _project_stage(),
    ]
    return list(coll.aggregate(pipeline))


def list_documents(user_id: str) -> dict:
    """Lista los PDFs visibles: todos los publicos + los privados de user_id."""
    db = _client()[config.MONGODB_DB]
    pipeline = [
        {"$match": {"$or": [
            {"metadata.visibility": "public"},
            {"metadata.owner": user_id},
        ]}},
        {"$group": {
            "_id": {
                "filename": "$metadata.filename",
                "owner": "$metadata.owner",
                "visibility": "$metadata.visibility",
            },
            "chunks": {"$sum": 1},
        }},
    ]
    docs = []
    for name in (config.COLL_TEXT, config.COLL_MULTIMODAL):
        for r in db[name].aggregate(pipeline):
            docs.append({**r["_id"], "chunks": r["chunks"]})
    docs.sort(key=lambda d: d["filename"] or "")
    return {
        "public": [d for d in docs if d["visibility"] == "public"],
        "private": [d for d in docs if d["visibility"] == "private" and d["owner"] == user_id],
    }


def search(query: str, user_id: str = "demo-user") -> list[dict]:
    """Busca en ambas colecciones y devuelve los chunks mas relevantes.

    Nota educativa: los resultados vienen de dos espacios vectoriales
    distintos, asi que en vez de ordenarlos entre si simplemente los
    concatenamos como contexto (simplificacion a proposito para el
    proposito educativo de este proyecto).
    """
    results = _search_text(query, user_id)
    results += _search_multimodal(query, user_id)
    return results