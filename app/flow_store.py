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
        "chunks": result.get("chunks", []),
        "origin": result.get("origin", ""),
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


def similar_past_answer(user_id: str, question: str, min_sim: float = 0.6, scan: int = 300) -> dict | None:
    """Respuesta anterior del MISMO usuario a una pregunta parecida (Jaccard sobre palabras clave).
    Es el atajo de memoria: no depende de la extraccion asincrona de Agent Engine (que tarda hasta
    ~1 minuto en convertir turnos en recuerdos). Solo se reutilizan respuestas con origen (no las 'sin informacion')."""
    import graph_store
    from prompts import origin_of
    target = set(graph_store._keywords(question))
    if not target:
        return None
    best, best_sim = None, 0.0
    for d in _coll().find({"user_id": user_id, "reply": {"$exists": True, "$ne": ""}},
                          {"question": 1, "reply": 1, "created_at": 1}).sort("created_at", -1).limit(scan):
        if origin_of(d.get("reply", "")) in ("none", ""):
            continue
        words = set(graph_store._keywords(d.get("question", "")))
        if not words:
            continue
        sim = len(target & words) / len(target | words)
        if sim > best_sim:
            best, best_sim = d, sim
    if best is None or best_sim < min_sim:
        return None
    return {"question": best["question"], "reply": best["reply"], "sim": round(best_sim, 2),
            "when": best["created_at"].isoformat() if best.get("created_at") else ""}


def last_turn(user_id: str, thread_id: str) -> dict | None:
    """Ultima pregunta/respuesta del hilo (para saber si se ofrecio buscar fuera)."""
    return _coll().find_one({"user_id": user_id, "thread_id": thread_id},
                            {"question": 1, "reply": 1, "origin": 1}, sort=[("created_at", -1)])


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
            "origin": d.get("origin", ""),
        }
        for d in cursor
    ]
