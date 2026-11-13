# ============================================================
#  embeddings.py
#  ------------------------------------------------------------------
#  Genera los vectores (embeddings) de cada chunk y los guarda en
#  MongoDB Atlas. Hay DOS estrategias, segun el contenido del PDF:
#
#   1) TEXTO SOLO      -> llamamos a VoyageAI con "voyage-context-4"
#       (contextualized chunk embeddings) y guardamos el vector.
#
#   2) CON IMAGENES    -> llamamos a VoyageAI con "voyage-multimodal"
#       pasando texto + imagenes juntas y guardamos el vector.
#
#  Al final, cada documento en Atlas tiene la forma:
#      { "text": "...", "embedding": [ ... ], "metadata": {...} }
# ============================================================

from __future__ import annotations

import voyageai
from pymongo import MongoClient

import config


def _client() -> MongoClient:
    """Crea (y cachea en la variable global de modulo) un cliente PyMongo."""
    if not config.MONGODB_URI:
        raise RuntimeError("Falta MONGODB_URI en el .env")
    return MongoClient(config.MONGODB_URI)


def _voyage() -> voyageai.Client:
    """Crea un cliente de VoyageAI usando la API key del .env."""
    if not config.VOYAGE_API_KEY:
        raise RuntimeError("Falta VOYAGE_API_KEY en el .env")
    return voyageai.Client(api_key=config.VOYAGE_API_KEY)


# ------------------------------------------------------------------
#  Embeber texto con voyage-context-4 (camino manual de texto)
# ------------------------------------------------------------------
def embed_text_manual(texts: list[str]) -> list[list[float]]:
    """Genera vectores de una lista de chunks usando voyage-context-4.

    voyage-context-4 es un modelo de 'contextualized chunk embeddings':
    recibe UNA lista de chunks del MISMO documento y los embebe teniendo
    en cuenta el contexto global del documento. Por eso pasamos todos
    los chunks de un mismo PDF juntos, en una sola llamada, ordenados.
    """
    vo = _voyage()
    # contextualized_embed espera una lista de "documentos"; cada documento
    # es una lista de chunks. Aqui hay UN documento con N chunks.
    resp = vo.contextualized_embed(
        inputs=[texts],
        model=config.VOYAGE_MODEL_TEXT,
        input_type="document",
    )
    # resp.results[0].embeddings es la lista de embeddings (uno por chunk).
    return [list(e) for e in resp.results[0].embeddings]


def embed_query_text_manual(query: str) -> list[float]:
    """Genera el vector de una PREGUNTA con voyage-context-4.

    Para queries, cada "documento" tiene UN solo elemento (la propia
    query), tal y como exige la API.
    """
    vo = _voyage()
    resp = vo.contextualized_embed(
        inputs=[[query]],
        model=config.VOYAGE_MODEL_TEXT,
        input_type="query",
    )
    return list(resp.results[0].embeddings[0])


# ------------------------------------------------------------------
#  Embeber contenido multimodal (PDFs con imagenes)
# ------------------------------------------------------------------
def embed_multimodal_manual(chunk: dict) -> list[float]:
    """Genera el vector de una pagina (texto + imagenes) con voyage-multimodal.

    Cada chunk es un "input" que mezcla texto e imagenes PIL en una lista.
    El modelo procesa ambas modalidades a la vez en un mismo vector.
    """
    vo = _voyage()
    content: list = [chunk["text"]] if chunk["text"] else []
    content.extend(chunk["images"])  # objetos PIL
    resp = vo.multimodal_embed(
        inputs=[content],
        model=config.VOYAGE_MODEL_MULTIMODAL,
        input_type="document",
    )
    return list(resp.embeddings[0])


def embed_query_multimodal_manual(query: str) -> list[float]:
    """Genera el vector de una PREGUNTA (solo texto) con voyage-multimodal."""
    vo = _voyage()
    resp = vo.multimodal_embed(
        inputs=[[query]],
        model=config.VOYAGE_MODEL_MULTIMODAL,
        input_type="query",
    )
    return list(resp.embeddings[0])


# ------------------------------------------------------------------
#  Guardar en MongoDB
# ------------------------------------------------------------------
def index_text_document(chunks: list[dict], filename: str, owner: str = "demo-user", visibility: str = "public") -> int:
    """Indexa los chunks de texto de un PDF usando voyage-context-4.

    Generamos el vector de todos los chunks en UNA sola llamada (el modelo
    de 'contextualized chunk embeddings' recibe los chunks del mismo documento
    juntos para darles contexto global) y guardamos cada vector en su doc.
    """
    db = _client()[config.MONGODB_DB]
    coll = db[config.COLL_TEXT]

    texts = [c["text"] for c in chunks]
    vectors = embed_text_manual(texts)

    docs = [
        {
            "text": chunk["text"],
            "embedding": vector,
            "metadata": {
                "filename": filename,
                "page": chunk["page"],
                "owner": owner,            # quien subio el PDF
                "visibility": visibility,  # "public" o "private"
            },
        }
        for chunk, vector in zip(chunks, vectors)
    ]

    coll.insert_many(docs)
    return len(docs)


def index_multimodal_documents(chunks: list[dict], filename: str, owner: str = "demo-user", visibility: str = "public") -> int:
    """Indexa los chunks de un PDF CON imagenes usando voyage-multimodal.

    Generamos un vector por pagina (texto + imagenes) y lo guardamos
    junto a su texto.
    """
    db = _client()[config.MONGODB_DB]
    coll = db[config.COLL_MULTIMODAL]

    docs = []
    for chunk in chunks:
        vector = embed_multimodal_manual(chunk)
        docs.append({
            "text": chunk["text"],
            "metadata": {
                "filename": filename,
                "page": chunk["page"],
                "owner": owner,            # quien subio el PDF
                "visibility": visibility,  # "public" o "private"
            },
            "embedding": vector,
        })

    coll.insert_many(docs)
    return len(docs)