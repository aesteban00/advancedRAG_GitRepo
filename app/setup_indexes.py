# ============================================================
#  setup_indexes.py
#  ------------------------------------------------------------------
#  Crea los indices de Atlas Vector Search EN CODIGO, no en la UI de
#  Atlas. Asi el proyecto es reproducible con un solo comando.
#
#  Se ejecuta automaticamente al arrancar la app (ver main.py).
#
#  Indices que se crean (si no existen ya):
#   * idx_vector_text      (coleccion texto)        -> vector, 1024d (voyage-context-4)
#   * idx_vector_multimodal(coleccion multimodal)   -> vector, 1024d (voyage-multimodal)
#
#  pymongo usa create_search_index() con un "modelo" que describe
#  la definicion JSON del indice, igual que en la consola de Atlas.
# ============================================================

from __future__ import annotations

from pymongo import MongoClient

import config

DIMENSIONS = 1024  # dimension por defecto de voyage-context-4 y voyage-multimodal-3.5


# Campos del indice: el vector + dos campos de FILTRO para controlar
# la visibilidad (publico/privado) y el propietario del documento.
VECTOR_FIELDS = [
    {
        "type": "vector",
        "path": "embedding",
        "numDimensions": DIMENSIONS,
        "similarity": "cosine",
    },
    {"type": "filter", "path": "metadata.visibility"},
    {"type": "filter", "path": "metadata.owner"},
]


def _client() -> MongoClient:
    if not config.MONGODB_URI:
        raise RuntimeError("Falta MONGODB_URI en el .env")
    return MongoClient(config.MONGODB_URI)


def _create_if_missing(coll, index_name: str, definition: dict) -> None:
    """Crea un indice de busqueda si aun no existe.

    Si el indice ya existe no hacemos nada (idempotente), para poder
    llamar a esta funcion en cada arranque sin errores.
    """
    existing = {i.get("name"): i for i in coll.list_search_indexes()}
    if index_name in existing:
        # Si el indice existe pero con otra definicion (p.ej. le faltan los
        # campos de filtro de visibilidad), lo actualizamos.
        if existing[index_name].get("latestDefinition") != definition:
            coll.update_search_index(index_name, definition)
            print(f"[setup] indice '{index_name}' actualizado.")
        else:
            print(f"[setup] indice '{index_name}' ya existe.")
        return

    coll.create_search_index(
        {
            "name": index_name,
            "type": "vectorSearch",
            "definition": definition,
        }
    )
    print(f"[setup] indice '{index_name}' creado.")


def _ensure_collection(db, name: str):
    """Crea la coleccion si no existe.

    En Atlas, para crear un indice de Vector Search (autoEmbed/vector) la
    coleccion debe existir previamente. Este helper la crea si falta.
    """
    if name not in db.list_collection_names():
        db.create_collection(name)
        print(f"[setup] coleccion '{name}' creada.")


def ensure_indexes() -> None:
    """Crea todos los indices necesarios segun la configuracion."""
    db = _client()[config.MONGODB_DB]
    _ensure_collection(db, config.COLL_TEXT)
    _ensure_collection(db, config.COLL_MULTIMODAL)
    coll_text = db[config.COLL_TEXT]
    coll_multimodal = db[config.COLL_MULTIMODAL]

    # Documentos antiguos (subidos antes de existir la visibilidad) se
    # consideran publicos.
    for c in (coll_text, coll_multimodal):
        c.update_many(
            {"metadata.visibility": {"$exists": False}},
            {"$set": {"metadata.visibility": "public", "metadata.owner": "demo-user"}},
        )

    # Indice de TEXTO: la app guarda vectores de voyage-context-4 en "embedding".
    _create_if_missing(
        coll_text,
        config.VECTOR_INDEX_TEXT_MANUAL,
        {
            "fields": VECTOR_FIELDS
        },
    )

    # Indice de MULTIMODAL: vectores de voyage-multimodal en "embedding".
    _create_if_missing(
        coll_multimodal,
        config.VECTOR_INDEX_MULTIMODAL,
        {
            "fields": VECTOR_FIELDS
        },
    )