# ============================================================
#  ingest.py
#  Ingesta de UN documento segun la estrategia elegida en Configuracion:
#   auto_embed        -> guardamos solo texto; Atlas genera los vectores (autoEmbed)
#   voyage_context    -> la app genera vectores con voyage-context
#   voyage_multimodal -> la app genera vectores texto+imagen
#  y, opcionalmente, construye el grafo con el LLM.
#  (Sincrono por simplicidad; en produccion iria a una cola/worker.)
# ============================================================

from __future__ import annotations

import config
import db
import embeddings
import graph_store
import loaders
import settings
import setup_indexes

BATCH = 50  # chunks por llamada a voyage-context (cada lote = un "documento")


def ingest_file(filename: str, data: bytes, user_id: str, visibility: str,
                source_type: str = "file", source: str | None = None) -> dict:
    s = settings.get()
    strategy = s["ingest"]["strategy"]
    model = s["embedding"][strategy]
    source = source or filename
    warnings: list[str] = []

    pages = loaders.load_pages(filename, data)
    if strategy == "voyage_multimodal" and not any(p["images"] for p in pages):
        warnings.append("El documento no tiene imagenes: se embebe solo el texto con el modelo multimodal.")
    chunks = loaders.make_chunks(pages, strategy, s["ingest"]["chunk_size"], s["ingest"]["chunk_overlap"])
    if not chunks:
        raise ValueError("No se generaron fragmentos (documento sin texto?).")

    # Idempotencia: si el mismo origen ya estaba indexado, sustituimos sus chunks
    # (antes se duplicaban al volver a analizarlo).
    for name in (config.COLL_AUTO, config.COLL_CONTEXT, config.COLL_MULTIMODAL):
        db.coll(name).delete_many({"metadata.source": source})

    docs = [{"text": c["text"], "metadata": {
        "source": source, "source_type": source_type, "page": c["page"], "chunk_index": i,
        "model": model, "strategy": strategy, "owner": user_id, "visibility": visibility}}
        for i, c in enumerate(chunks)]

    if strategy == "auto_embed":
        setup_indexes.ensure_auto_index(model)
        # Ventaja MongoDB: sin campo embedding. Atlas detecta el insert y genera el vector.
        db.coll(config.COLL_AUTO).insert_many(docs)
        warnings.append("autoEmbed: los vectores se generan en Atlas de forma asincrona; espera unos segundos.")
    elif strategy == "voyage_context":
        for i in range(0, len(docs), BATCH):
            lote = docs[i:i + BATCH]
            vecs = embeddings.embed_context([d["text"] for d in lote], model)
            for d, v in zip(lote, vecs):
                d["embedding"] = v
        db.coll(config.COLL_CONTEXT).insert_many(docs)
    else:
        for d, c in zip(docs, chunks):
            content = ([c["text"]] if c["text"] else []) + c["images"]
            d["embedding"] = embeddings.embed_multimodal(content, model)
        db.coll(config.COLL_MULTIMODAL).insert_many(docs)

    entities = 0
    if s["ingest"]["build_graph"]:
        try:
            text = "\n".join(p["text"] for p in pages)
            entities = graph_store.add_text(text, source=f"{source_type}:{source}")
            graph_store.upsert_entities([graph_store.make_entity(
                source, "Document", f"{source_type}:{source}", {"strategy": strategy, "pages": len(pages)})])
        except Exception as exc:
            warnings.append(f"Grafo no construido: {exc}")

    return {"source": source, "strategy": strategy, "model": model,
            "chunks": len(docs), "entities": entities, "warnings": warnings}
