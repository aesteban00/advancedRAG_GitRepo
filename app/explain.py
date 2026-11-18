# ============================================================
#  explain.py
#  Catalogo DINAMICO de la aplicacion para la pestaña Explicacion.
#  Cada paso muestra la llamada real a MongoDB que hace la app, construida con los
#  MISMOS constructores que usa el chat (vector_search.build_pipeline, graph_store.related_pipeline,
#  setup_indexes.*_definition, graph_store.make_entity...), con la configuracion ACTUAL
#  (estrategia, modelos, modo de busqueda, profundidad, usuario y pregunta).
#  Asi, lo que se copia a MongoDB Compass es exactamente lo que ejecuta la aplicacion.
# ============================================================

from __future__ import annotations

from datetime import datetime, timezone

import config
import db
import embeddings
import graph_store
import loaders
import settings
import setup_indexes
import vector_search

COLL_BY_STRATEGY = {"auto_embed": config.COLL_AUTO, "voyage_context": config.COLL_CONTEXT,
                    "voyage_multimodal": config.COLL_MULTIMODAL}
INDEX_BY_STRATEGY = {"auto_embed": None, "voyage_context": config.VECTOR_INDEX_CONTEXT,
                     "voyage_multimodal": config.VECTOR_INDEX_MULTIMODAL}


def _step(id, lane, title, summary, kind, collection=None, code=None, note="", runnable=False):
    return {"id": id, "lane": lane, "title": title, "summary": summary, "kind": kind,
            "db": config.MONGODB_DB, "collection": collection, "code": code, "note": note, "runnable": runnable}


def _status(user_id: str) -> dict:
    s = settings.get()
    counts, idx = {}, []
    try:
        counts = vector_search.counts() | {"entidades": graph_store.count()}
        idx = setup_indexes.index_status()
    except Exception as exc:
        counts = {"error": str(exc)}
    return {"db": config.MONGODB_DB, "strategy": s["ingest"]["strategy"],
            "embedding": s["embedding"][s["ingest"]["strategy"]], "chunk": [s["ingest"]["chunk_size"], s["ingest"]["chunk_overlap"]],
            "retrieval": s["retrieval"]["mode"], "search_mode": s["retrieval"]["search_mode"],
            "top_k": s["retrieval"]["top_k"], "graph_depth": s["retrieval"]["graph_depth"],
            "chat_model": settings.llm("chat")["model"], "user": user_id, "counts": counts, "indexes": idx}


def _sample_chunk(strategy: str, model: str, user_id: str) -> dict:
    doc = {"text": "Plan de Pensiones de Empleo ... (fragmento de ejemplo)",
           "metadata": {"source": "documento.pdf", "source_type": "file", "page": 1, "chunk_index": 0,
                        "model": model, "strategy": strategy, "owner": user_id, "visibility": "public"}}
    if strategy != "auto_embed":
        doc = {**doc, "embedding": "[ vector de 1024 números ]"}   # lo genera la app con Voyage
    return doc


def _example_entity(user_id: str) -> dict | None:
    """Una entidad REAL de tu grafo (la mas conectada), para que los ejemplos sean reales."""
    rows = graph_store.overview(None)
    return rows[0] if rows else None


def catalog(user_id: str, question: str) -> dict:
    s = settings.get()
    strategy = s["ingest"]["strategy"]
    model = s["embedding"][strategy]
    coll = COLL_BY_STRATEGY[strategy]
    mode = s["retrieval"]["search_mode"]
    depth = s["retrieval"]["graph_depth"]
    top_k = s["retrieval"]["top_k"]
    question = (question or "").strip() or "límites de aportaciones"
    ingest: list[dict] = []
    query: list[dict] = []

    # ---------------- INGESTA (mitad superior) ----------------
    size, ov = (s["ingest"]["chunk_size"], s["ingest"]["chunk_overlap"]) if strategy == "auto_embed" \
        else (config.FIXED_CHUNK_SIZE, config.FIXED_CHUNK_OVERLAP)
    ingest.append(_step("ingest-load", "ingest", "1 · Leer y trocear",
        f"PDF/MD/TXT → páginas → trozos de {size} caracteres con solape de {ov}. Sin llamadas a MongoDB.",
        "local", note="loaders.py: pypdf extrae texto e imágenes por página; el troceo no corta palabras."))
    ingest.append(_step("ingest-store", "ingest", f"2 · Guardar en {coll}",
        "Cada trozo se guarda como un documento con su texto y sus metadatos (fuente, página, propietario, visibilidad, modelo).",
        "insert", coll, code=_sample_chunk(strategy, model, user_id),
        note="Se inserta desde la app (insertMany). En Compass: Insert Document para ver la forma del documento."))
    if strategy == "auto_embed":
        ingest.append(_step("ingest-embed", "ingest", "3 · Vectores automáticos (Atlas)",
            f"Atlas genera el vector con {model} (Voyage) y lo guarda en __mdb_internal. La app NO llama a ningún modelo.",
            "atlas", coll, note="Ventaja MongoDB: autoEmbed. Cambiar de modelo = crear otro índice; Atlas re-embebe solo."))
    else:
        ingest.append(_step("ingest-embed", "ingest", "3 · Vectores con Voyage",
            f"La app llama a {model} (Voyage AI) y guarda el vector en el campo embedding del mismo documento.",
            "local", coll, note="voyage-context: los trozos del documento se embeben juntos para tener contexto global."))

    defs = [{"collection": coll, "name": setup_indexes.auto_index_name(model) if strategy == "auto_embed" else INDEX_BY_STRATEGY[strategy],
             "type": "vectorSearch",
             "definition": setup_indexes.auto_embed_definition(model) if strategy == "auto_embed" else setup_indexes.vector_definition()},
            {"collection": coll, "name": config.TEXT_INDEX, "type": "search", "definition": setup_indexes.text_definition()}]
    ingest.append(_step("ingest-index", "ingest", "4 · Índices de búsqueda",
        "Dos índices por colección: el vectorial (o autoEmbed) y el de texto BM25 (Atlas Search). Se crean solos al arrancar.",
        "createSearchIndex", coll, code=defs,
        note="Compass: Indexes → Search Indexes → Create (JSON). Los índices autoEmbed no se editan: se crea uno nuevo."))
    ent = _example_entity(user_id)
    ingest.append(_step("ingest-graph-llm", "ingest", "5 · Grafo desde documentos (LLM)",
        "El LLM de grafo extrae entidades y relaciones de cada trozo. Cada entidad guarda la fuente de la que sale.",
        "update", config.COLL_GRAPH,
        code={"filter": {"_id": ent["_id"] if ent else "<entidad>"}, "upsert": True,
              "update": {"$setOnInsert": {"type": ent.get("type", "?") if ent else "<tipo>"},
                         "$addToSet": {"attributes.sources": "file:documento.pdf"},
                         "$push": {"relationships.target_ids": {"$each": ["<destino>"]},
                                   "relationships.types": {"$each": ["<TIPO_RELACION>"]}}}},
        note="Upsert sin duplicar: $addToSet para atributos y fuentes, $push para relaciones (listas paralelas)."))
    repo = db.coll(config.COLL_GRAPH).find_one({"type": "Repository", "attributes.sources": {"$regex": "^github:"}},
                                               {"relationships": 0})
    ingest.append(_step("ingest-github", "ingest", "6 · Repos de GitHub (determinista)",
        "Sin LLM: librerías, endpoints, funciones y CODEOWNERS se convierten en nodos y relaciones. Así es un repo ya ingerido (sin relaciones, para acortar).",
        "update", config.COLL_GRAPH, code=repo or None,
        note="Ejemplo real de un nodo Repository de tu grafo."))

    # ---------------- CONSULTA Y RECUPERACION (mitad inferior) ----------------
    query.append(_step("query-memory", "query", "1 · Memoria (Agent Engine)",
        "Antes de responder se recuperan recuerdos de conversaciones anteriores (corta, episódica y semántica).",
        "agent", note="Lo gestiona el servicio de memoria de Agent Engine, que usa colecciones de tu mismo cluster. No es una llamada directa de la app."))

    vec_base = None
    if mode != "bm25":
        if strategy == "auto_embed":
            vec_base = {"index": setup_indexes.auto_index_name(model), "path": "text", "query": {"text": question}}
        else:
            qmodel = s["embedding"][strategy]
            qvec = (embeddings.embed_context([question], qmodel, "query")[0] if strategy == "voyage_context"
                    else embeddings.embed_multimodal([question], qmodel, "query"))
            vec_base = {"index": INDEX_BY_STRATEGY[strategy], "path": "embedding", "queryVector": qvec}
    pipeline = vector_search.build_pipeline(coll, question, user_id, top_k, mode, model, vec_base)
    title = {"hybrid": "2 · Búsqueda híbrida ($rankFusion)", "vector": "2 · Búsqueda vectorial", "bm25": "2 · Búsqueda BM25 ($search)"}[mode]
    query.append(_step("query-search", "query", title,
        f"Pregunta: «{question}». Modo {mode}; después $rerank y los {top_k} mejores. Filtro: tu usuario y el modelo {model}.",
        "aggregate", coll, code=pipeline, runnable=True,
        note="Compass: Aggregations → elige la colección → pega este array de etapas. Requiere los índices READY."))

    ent_name = ent["_id"] if ent else "<nombre de entidad>"
    query.append(_step("query-graph-entities", "query", "3 · Entidades de la pregunta (LLM)",
        "El LLM de grafo extrae nombres de entidad de la pregunta y los resuelve contra _id en MongoDB.",
        "find", config.COLL_GRAPH,
        code={"_id": {"$regex": f"^{ent_name}$", "$options": "i"}},
        note="Filtro de Find en Compass. Primero coincidencia exacta y, si no, parcial (ver graph_store._resolve)."))
    start = [ent["_id"]] if ent else ["<id de entidad>"]
    query.append(_step("query-graph-traverse", "query", f"4 · Recorrido del grafo ($graphLookup, {depth} saltos)",
        "Desde las entidades encontradas, MongoDB recorre todo lo alcanzable hasta la profundidad configurada, en una sola consulta.",
        "aggregate", config.COLL_GRAPH, code=graph_store.related_pipeline(start, depth), runnable=bool(ent),
        note=f"Ejemplo con la entidad «{ent_name}». En la app el punto de partida sale del paso 3. «Profundidad del grafo» = maxDepth."))
    query.append(_step("query-graph-incoming", "query", "5 · Relaciones entrantes",
        "Quién apunta a la entidad (\"¿quién usa X?\"). Lo resuelve el índice multikey sobre relationships.target_ids.",
        "find", config.COLL_GRAPH, code={"relationships.target_ids": {"$in": start}},
        note="Filtro de Find en Compass; limitado a 50 resultados en la app."))
    query.append(_step("query-answer", "query", "6 · Respuesta del LLM de chat",
        "Se envían memoria, fragmentos (con su fuente) y entidades al LLM de chat, que responde citando fuentes.",
        "llm", note=f"Modelo: {settings.llm('chat')['model']}. Sin llamadas a MongoDB."))
    query.append(_step("query-record", "query", "7 · Guardar el flujo",
        "Cada turno se guarda con sus pasos, tokens y los fragmentos recuperados, para reabrirlo después.",
        "insert", config.COLL_FLOWS,
        code={"user_id": user_id, "thread_id": "hilo-…", "question": question, "reply": "…",
              "steps": ["…"], "chunks": ["…"], "tokens": {"prompt": 0, "completion": 0, "total": 0},
              "created_at": datetime.now(timezone.utc).isoformat()},
        note="Insert desde la app. Sirve también para ver el historial en Compass."))

    return {"status": _status(user_id), "question": question, "ingest": ingest, "query": query}
