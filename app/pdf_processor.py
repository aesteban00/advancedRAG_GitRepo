# ============================================================
#  pdf_processor.py
#  ------------------------------------------------------------------
#  Se encarga de "leer" un PDF y convertirlo en CHUNKS (fragmentos
#  de texto) listos para indexar. Tambien DETECTA si el PDF contiene
#  imagenes, porque eso decide que modelo de embedding usaremos:
#    * PDF de texto solO  -> modelo de texto (voyage-context-4)
#    * PDF CON imagenes   -> modelo multimodal (voyage-multimodal)
#
#  Por que "chunking"?
#  Los modelos de embedding tienen un limite de tokens por llamada.
#  Si mandamos el PDF entero, nos cortamos el contexto y la busqueda
#  es imprecisa. Troceando en partes pequenas, cada chunk se convierte
#  en un vector que recupera "trozos" concretos y relevantes.
# ============================================================

from __future__ import annotations

import io

from PIL import Image
from pypdf import PdfReader


# Ajustes de chunking (faciles de cambiar).
CHUNK_SIZE = 1000     # caracteres por fragmento
CHUNK_OVERLAP = 200   # solapamiento entre fragmentos para no perder contexto


def split_text(text: str) -> list[str]:
    """Divide un texto largo en trozos de ~CHUNK_SIZE caracteres.

    El 'overlap' (solapamiento) hace que el inicio de cada trozo repita
    el final del anterior: asi frases que quedaban justo en el borde no
    se pierden y la busqueda sigue encontrandolas.
    """
    text = text.strip()
    if not text:
        return []

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = start + CHUNK_SIZE
        chunk = text[start:end]
        if chunk:
            chunks.append(chunk)
        # Avanzamos dejando un poco de "colchon" al final.
        if end >= len(text):
            break
        start = end - CHUNK_OVERLAP
    return chunks


def has_images(pdf_bytes: bytes) -> bool:
    """Devuelve True si el PDF contiene al menos una imagen incrustada.

    pypdf expone la propiedad .images de cada pagina. Si hay alguna,
    consideramos que es un PDF "multimodal".
    """
    reader = PdfReader(io.BytesIO(pdf_bytes))
    for page in reader.pages:
        try:
            if len(page.images or []) > 0:
                return True
        except Exception:
            # Si una pagina no se puede inspeccionar, la ignoramos.
            continue
    return False


def extract_pages(pdf_bytes: bytes) -> list[dict]:
    """Extrae texto e imagenes de cada pagina.

    Devuelve una lista de paginas, cada una con:
      - "page":    numero de pagina (1-based)
      - "text":    texto extraido de esa pagina
      - "images":  lista de imagenes PIL de esa pagina (puede estar vacia)
    """
    reader = PdfReader(io.BytesIO(pdf_bytes))
    pages = []
    for i, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        # Convertimos las imagenes de pypdf a objetos PIL para poder
        # pasarselas luego a voyage-multimodal.
        images = []
        try:
            for img in (page.images or []):
                images.append(Image.open(io.BytesIO(img.data)))
        except Exception:
            pass
        pages.append({"page": i, "text": text, "images": images})
    return pages


def process_pdf(pdf_bytes: bytes) -> dict:
    """Punto de entrada: procesa un PDF y decide el camino de embedding.

    Devuelve:
      {
        "has_images": True/False,
        "text_chunks": [ {"text": ..., "page": n}, ... ],   # para PDFs de texto
        "multimodal_chunks": [ {"text": ..., "images": [PIL], "page": n}, ... ]
      }
    Solo se rellena la lista que corresponda segun tenga imagenes o no.
    """
    has_img = has_images(pdf_bytes)
    pages = extract_pages(pdf_bytes)

    if not has_img:
        # PDF de TEXTO SOLO: troceamos cada pagina.
        text_chunks = []
        for p in pages:
            for chunk in split_text(p["text"]):
                text_chunks.append({"text": chunk, "page": p["page"]})
        return {"has_images": False, "text_chunks": text_chunks, "multimodal_chunks": []}

    # PDF CON IMAGENES: agrupamos texto + imagenes de cada pagina en un
    # solo "input" multimodal (el modelo entiende texto e imagen juntos).
    multimodal_chunks = []
    for p in pages:
        if not p["text"] and not p["images"]:
            continue  # pagina vacia: la saltamos
        # Por simplicidad, una "chunk" = una pagina completa con sus imagenes.
        multimodal_chunks.append({
            "text": p["text"],
            "images": p["images"],
            "page": p["page"],
        })
    return {"has_images": True, "text_chunks": [], "multimodal_chunks": multimodal_chunks}