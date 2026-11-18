# ============================================================
#  setup_indexes.py
#  Crea colecciones e indices EN CODIGO (reproducible, sin tocar la UI de Atlas).
#   * idx_vector_context / idx_vector_multimodal: tipo "vector" (vectores de la app)
#   * idx_auto_<modelo>: tipo "autoEmbed" (Atlas genera los vectores)
#   * indices normales sobre el grafo (knowledge_graph)
# ============================================================

from __future__ import annotations

import config
import db
import settings

FILTER_FIELDS = [
    {"type": "filter", "path": "metadata.visibility"},
    {"type": "filter", "path": "metadata.owner"},
    {"type": "filter", "path": "metadata.model"},  # no mezclar vectores de modelos distintos
]


def vector_definition() -> dict:
    return {"fields": [{"type": "vector", "path": "embedding",
                        "numDimensions": config.VECTOR_DIMENSIONS, "similarity": "cosine"}, *FILTER_FIELDS]}


def auto_embed_definition(model: str) -> dict:
    # Ventaja MongoDB: no hay campo "embedding"; Atlas lee "text", llama a Voyage
    # y guarda/sincroniza los vectores el solo.
    return {"fields": [{"type": "autoEmbed", "modality": "text", "path": "text", "model": model},
                       *FILTER_FIELDS]}


def text_definition() -> dict:
    """Indice BM25 (Atlas Search) sobre el texto del chunk.
    Ventaja MongoDB: el MISMO documento tiene indice vectorial e indice de texto, sin copiar datos
    a un buscador aparte. `text` se indexa con el analizador estandar (terminos exactos: nombres,
    siglas, codigos) y con uno de espanol (`multi: es`: stemming y stopwords)."""
    return {"mappings": {"dynamic": False, "fields": {
        "text": {"type": "string", "analyzer": "lucene.standard",
                 "multi": {"es": {"type": "string", "analyzer": "lucene.spanish"}}},
        "metadata": {"type": "document", "fields": {
            "visibility": {"type": "token"}, "owner": {"type": "token"}, "model": {"type": "token"}}}}}}


def auto_index_name(model: str) -> str:
    return config.AUTO_INDEX_PREFIX + model


def _create_if_missing(coll, name: str, definition: dict, editable: bool = True, index_type: str = "vectorSearch") -> None:
    """Idempotente. Los indices autoEmbed no se pueden editar (editable=False)."""
    existing = {i.get("name"): i for i in coll.list_search_indexes()}
    if name in existing:
        if existing[name].get("latestDefinition") != definition:
            if editable:
                coll.update_search_index(name, definition)
                print(f"[setup] indice '{name}' actualizado.")
            else:
                print(f"[setup] AVISO '{name}' existe con otra definicion (autoEmbed no es editable).")
        else:
            print(f"[setup] indice '{name}' ya existe.")
        return
    coll.create_search_index({"name": name, "type": index_type, "definition": definition})
    print(f"[setup] indice '{name}' creado.")


def _ensure_collection(database, name: str) -> None:
    if name not in database.list_collection_names():
        database.create_collection(name)
        print(f"[setup] coleccion '{name}' creada.")


def ensure_auto_index(model: str) -> str:
    """Un indice autoEmbed por modelo: cambiar de modelo = indice nuevo (Atlas re-embebe solo)."""
    name = auto_index_name(model)
    _create_if_missing(db.coll(config.COLL_AUTO), name, auto_embed_definition(model), editable=False)
    return name


def ensure_indexes() -> None:
    database = db.get_db()
    for n in (config.COLL_AUTO, config.COLL_CONTEXT, config.COLL_MULTIMODAL,
              config.COLL_GRAPH, config.COLL_FLOWS, config.COLL_SETTINGS):
        _ensure_collection(database, n)

    for coll_name, idx in ((config.COLL_CONTEXT, config.VECTOR_INDEX_CONTEXT),
                           (config.COLL_MULTIMODAL, config.VECTOR_INDEX_MULTIMODAL)):
        try:
            _create_if_missing(db.coll(coll_name), idx, vector_definition())
        except Exception as exc:
            print(f"[setup] AVISO {idx}: {exc}")
    # Indices BM25 ($search) en las tres colecciones de chunks.
    for coll_name in (config.COLL_AUTO, config.COLL_CONTEXT, config.COLL_MULTIMODAL):
        try:
            _create_if_missing(db.coll(coll_name), config.TEXT_INDEX, text_definition(), index_type="search")
        except Exception as exc:
            print(f"[setup] AVISO {config.TEXT_INDEX} en {coll_name}: {exc}")
    try:
        ensure_auto_index(settings.get()["embedding"]["auto_embed"])
    except Exception as exc:
        print(f"[setup] AVISO autoEmbed: {exc}")

    # Indices normales del grafo. $graphLookup conecta por _id (ya indexado);
    # el multikey sobre target_ids resuelve las aristas ENTRANTES ("quien usa X?").
    g = db.coll(config.COLL_GRAPH)
    g.create_index("type")
    g.create_index("relationships.target_ids")


def index_status() -> list[dict]:
    out = []
    for n in (config.COLL_AUTO, config.COLL_CONTEXT, config.COLL_MULTIMODAL):
        for i in db.coll(n).list_search_indexes():
            out.append({"collection": n, "name": i.get("name"), "type": i.get("type"),
                        "status": i.get("status"), "queryable": i.get("queryable")})
    return out
