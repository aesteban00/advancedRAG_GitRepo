# ============================================================
#  flow_store.py
#  ------------------------------------------------------------------
#  Guarda en una coleccion APARTE ("request_flows") el "Flujo de la
#  peticion" de cada pregunta del chat: los pasos (memoria, BBDD, LLM...),
#  sus tiempos y el origen del contexto.
#
#  Asi, al pinchar una pregunta en el chat, la UI puede volver a
#  mostrar su flujo en el panel derecho (GET /flows/{id}).
# ============================================================

from __future__ import annotations

from datetime import datetime, timezone

from bson import ObjectId
import config
import db

def _coll():
    return db.coll(config.COLL_FLOWS)


def save_flow(user_id: str, thread_id: str, question: str,
              steps: list[dict], result: dict) -> str:
    """Guarda el flujo de una peticion y devuelve su id (string)."""
    doc = {
        "user_id": user_id,
        "thread_id": thread_id,
        "question": question,
        "reply": result.get("reply", ""),  # respuesta, para reconstruir el historial
        "steps": steps,  # [{id, label, status, detail, ms}, ...]
        "memory": result.get("memory", {}),
        "documents": result.get("documents", 0),
        "tokens": result.get("tokens", {}),
        "graph": result.get("graph"),
        "created_at": datetime.now(timezone.utc),
    }
    return str(_coll().insert_one(doc).inserted_id)


def get_flow(flow_id: str, user_id: str) -> dict | None:
    """Recupera un flujo por id. Solo lo ve el usuario que lo genero."""
    try:
        oid = ObjectId(flow_id)
    except Exception:
        return None
    doc = _coll().find_one({"_id": oid, "user_id": user_id})
    if not doc:
        return None
    doc["id"] = str(doc.pop("_id"))
    doc["created_at"] = doc["created_at"].isoformat()
    return doc


def list_threads(user_id: str, limit: int = 30) -> list[dict]:
    """Sesiones (hilos) del usuario, la mas reciente primero.

    El titulo de cada sesion es su primera pregunta, como en ChatGPT.
    """
    pipeline = [
        {"$match": {"user_id": user_id}},
        {"$sort": {"created_at": 1}},
        {"$group": {
            "_id": "$thread_id",
            "title": {"$first": "$question"},
            "first": {"$first": "$created_at"},
            "last": {"$last": "$created_at"},
            "count": {"$sum": 1},
        }},
        {"$sort": {"last": -1}},
        {"$limit": limit},
    ]
    return [
        {"thread_id": r["_id"], "title": r["title"], "count": r["count"],
         "first": r["first"].isoformat() + "Z", "last": r["last"].isoformat() + "Z"}
        for r in _coll().aggregate(pipeline)
    ]


def get_thread(user_id: str, thread_id: str) -> list[dict]:
    """Todas las preguntas/respuestas de un hilo, en orden cronologico."""
    cursor = _coll().find({"user_id": user_id, "thread_id": thread_id}).sort("created_at", 1)
    return [
        {
            "id": str(d["_id"]),
            "question": d["question"],
            "reply": d.get("reply", ""),
            "memory": d.get("memory", {}),
            "documents": d.get("documents", 0),
        }
        for d in cursor
    ]
