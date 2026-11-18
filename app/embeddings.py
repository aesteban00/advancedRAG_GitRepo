# ============================================================
#  embeddings.py
#  Embeddings MANUALES con Voyage AI (las estrategias voyage_context y
#  voyage_multimodal). Con autoEmbed no se usa: Atlas genera los vectores.
# ============================================================

from __future__ import annotations

import voyageai

import config


def _voyage() -> voyageai.Client:
    if not config.VOYAGE_API_KEY:
        raise RuntimeError("Falta VOYAGE_API_KEY en el .env")
    return voyageai.Client(api_key=config.VOYAGE_API_KEY)


def embed_context(texts: list[str], model: str, input_type: str = "document") -> list[list[float]]:
    """voyage-context: 'contextualized chunk embeddings'. Recibe los chunks del
    MISMO documento juntos y los embebe teniendo en cuenta el documento entero.
    Para queries cada 'documento' es la propia pregunta."""
    inputs = [texts] if input_type == "document" else [[texts[0]]]
    resp = _voyage().contextualized_embed(inputs=inputs, model=model, input_type=input_type)
    return [list(e) for e in resp.results[0].embeddings]


def embed_multimodal(content: list, model: str, input_type: str = "document") -> list[float]:
    """voyage-multimodal: una lista mezcla texto e imagenes PIL en UN vector."""
    resp = _voyage().multimodal_embed(inputs=[content], model=model, input_type=input_type)
    return list(resp.embeddings[0])
