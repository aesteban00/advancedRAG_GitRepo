# ============================================================
#  loaders.py
#  Lee documentos (.pdf, .md, .txt) y los trocea (chunking).
#
#  Por que chunking? Los modelos de embedding tienen limite de tokens y un
#  vector por documento entero seria impreciso: troceando, cada vector
#  representa una idea concreta y la busqueda recupera pasajes relevantes.
# ============================================================

from __future__ import annotations

import io

from PIL import Image
from pypdf import PdfReader

import config

SUPPORTED_EXTENSIONS = (".pdf", ".md", ".txt")


def load_pages(filename: str, data: bytes) -> list[dict]:
    """-> [{"page", "text", "images"}]. md/txt: una unica 'pagina'."""
    ext = "." + filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    if ext not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"Formato no soportado: {ext} (usa .pdf, .md o .txt)")
    if not data:
        raise ValueError("El archivo esta vacio.")
    if ext == ".pdf":
        pages = []
        for i, page in enumerate(PdfReader(io.BytesIO(data)).pages, start=1):
            images = []
            try:
                for img in (page.images or []):
                    images.append(Image.open(io.BytesIO(img.data)))
            except Exception:
                pass  # imagen ilegible: se ignora
            pages.append({"page": i, "text": page.extract_text() or "", "images": images})
    else:
        pages = [{"page": 1, "text": data.decode("utf-8", errors="replace"), "images": []}]
    if not any(p["text"].strip() or p["images"] for p in pages):
        raise ValueError("No se pudo extraer contenido del documento.")
    return pages


def split_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    """Trozos de ~chunk_size caracteres. El solape repite el final del trozo
    anterior para no perder frases que caen justo en el borde."""
    if not 0 <= overlap < chunk_size:
        raise ValueError("El solape debe ser >= 0 y menor que el tamano de chunk.")
    text = text.strip()
    chunks, start = [], 0
    while text and start < len(text):
        end = start + chunk_size
        if end < len(text):
            # No cortar a mitad de palabra: retrocede al ultimo espacio cercano.
            cut = max(text.rfind(" ", start, end), text.rfind("\n", start, end))
            if cut > end - 100 and cut > start + overlap:
                end = cut
        piece = text[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= len(text):
            break
        start = end - overlap
    return chunks


def make_chunks(pages: list[dict], strategy: str, chunk_size: int, overlap: int) -> list[dict]:
    """-> [{"text", "page", "images"}] segun la estrategia."""
    if strategy not in config.STRATEGIES:
        raise ValueError(f"Estrategia desconocida: {strategy}")
    if strategy == "auto_embed":
        size, ov = chunk_size, overlap  # unica estrategia con chunking elegible
    else:
        # voyage-context embebe cada chunk con el contexto del documento entero,
        # asi que no necesita afinar tamanos.
        size, ov = config.FIXED_CHUNK_SIZE, config.FIXED_CHUNK_OVERLAP
    out = []
    for p in pages:
        if strategy == "voyage_multimodal" and p["images"]:
            out.append({"text": p["text"], "page": p["page"], "images": p["images"]})  # pagina = chunk
            continue
        for t in split_text(p["text"], size, ov):
            out.append({"text": t, "page": p["page"], "images": []})
    return out
