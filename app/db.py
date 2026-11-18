# ============================================================
#  db.py
#  Un UNICO MongoClient compartido (con su pool de conexiones) en
#  lugar de crear uno nuevo en cada modulo/llamada como en la v1.
# ============================================================

from __future__ import annotations

from pymongo import MongoClient

import config

_client: MongoClient | None = None


def get_db():
    """Base de datos de la demo (el cliente se crea la primera vez)."""
    global _client
    if _client is None:
        if not config.MONGODB_URI:
            raise RuntimeError("Falta MONGODB_URI en el .env")
        _client = MongoClient(config.MONGODB_URI)
    return _client[config.MONGODB_DB]


def coll(name: str):
    """Atajo: coleccion por nombre."""
    return get_db()[name]
