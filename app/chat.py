# ============================================================
#  chat.py
#  ------------------------------------------------------------------
#  Orquesta el pipeline del chat:
#
#   1. Recuperar contexto de MEMORIA  (conversaciones anteriores)
#   2. Recuperar contexto de DOCUMENTOS (Atlas Vector Search) y del GRAFO ($graphLookup)
#   3. Construir el prompt del sistema con ambos contextos
#   4. Llamar al modelo de chat para generar la respuesta
#   5. Registrar el turno en la memoria
#
#  El modelo de chat es cualquiera compatible con la API de OpenAI, asi que usamos el
#  paquete "openai" apuntando a su base_url.
# ============================================================

from __future__ import annotations

import time

from openai import OpenAI

import config
import graph_store
import graph_view
import memory
import settings
import vector_search


def _llm(role: str = "chat") -> OpenAI:
    """Cliente del LLM (compatible con OpenAI) segun la pestana Configuracion."""
    cfg = settings.llm(role)
    if not cfg["api_key"]:
        raise RuntimeError(f"Falta la API key del LLM de {role} (.env o Configuracion)")
    if not cfg["model"]:
        raise RuntimeError("Falta el modelo de chat (CHAT_LLM_MODEL en .env o Configuracion)")
    return OpenAI(api_key=cfg["api_key"], base_url=cfg["base_url"],
                  timeout=config.LLM_TIMEOUT_S, max_retries=config.LLM_MAX_RETRIES)


def _usage(response) -> dict:
    """Tokens consumidos en una llamada al LLM."""
    u = getattr(response, "usage", None)
    return {
        "prompt": getattr(u, "prompt_tokens", 0) or 0,
        "completion": getattr(u, "completion_tokens", 0) or 0,
        "total": getattr(u, "total_tokens", 0) or 0,
    }


def _format_entity(e: dict) -> str:
    """Una linea por entidad: id (tipo) attrs | relaciones | fuentes."""
    attrs = e.get("attributes") or {}
    sources = ", ".join(attrs.get("sources", []))
    shown = "; ".join(f"{k}={','.join(map(str, v))}"[:200] for k, v in attrs.items() if k != "sources" and v)
    rel = e.get("relationships") or {}
    targets, types = rel.get("target_ids", []), rel.get("types", [])
    rels = " ; ".join(f"-> {types[i] if i < len(types) else '?'} {t}" for i, t in enumerate(targets))
    return f"- {e.get('_id')} ({e.get('type', '?')}) attrs: {shown} | {rels} | fuentes: {sources}"


def _build_system_prompt(memory_ctx: str, docs_ctx: list[dict], entities: list[dict]) -> str:
    partes = [
        "Eres un asistente que responde sobre la documentacion y los repositorios de codigo indexados. "
        "Usa SOLO el contexto proporcionado. Cita la fuente entre corchetes tras cada afirmacion "
        "([fuente - pag. N] o [grafo: _id]). Si el contexto no cubre la pregunta, dilo claramente: no inventes."
    ]
    if memory_ctx:
        partes.append("## Recuerdos de conversaciones anteriores\n" + memory_ctx)
    if docs_ctx:
        bloques = [f"[{d.get('metadata', {}).get('source', 'desconocido')} - pag. "
                   f"{d.get('metadata', {}).get('page', '?')}]\n{d.get('text', '')}" for d in docs_ctx]
        partes.append("## Fragmentos de los documentos\n" + "\n\n".join(bloques))
    if entities:
        partes.append("## Grafo de conocimiento (entidades y relaciones)\n"
                      + "\n".join(_format_entity(e) for e in entities[:60]))
    return "\n\n".join(partes)


# Palabra clave que el LLM devuelve cuando la memoria NO basta para responder.
NEED_DOCS = "NECESITO_DOCUMENTOS"


def _answer_from_memory(question: str, memory_ctx: str) -> tuple[str | None, dict]:
    """Intenta responder SOLO con la memoria. Devuelve (texto|None, tokens).

    Se hace una llamada corta al LLM con unicamente los recuerdos. Si
    contienen la respuesta la da; si no, el LLM contesta NECESITO_DOCUMENTOS
    y entonces habra que buscar en la BBDD.
    """
    system = (
        "Responde a la pregunta usando UNICAMENTE los recuerdos de la "
        "conversacion que se indican abajo. Si contienen la respuesta, "
        "respondela directamente. Si NO la contienen o no estas seguro, "
        f"responde exactamente: {NEED_DOCS}\n\n"
        "## Recuerdos\n" + memory_ctx
    )
    response = _llm().chat.completions.create(
        model=settings.llm("chat")["model"],
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": question},
        ],
    )
    text = (response.choices[0].message.content or "").strip()
    return (None if NEED_DOCS in text or not text else text), _usage(response)


def _step(id: str, label: str, status: str, detail: str = "", t0: float | None = None,
          tokens: dict | None = None) -> dict:
    """Evento de progreso que la UI pinta en el panel de flujo.

    status: running | done | skipped | error
    """
    ev = {"type": "step", "id": id, "label": label, "status": status, "detail": detail}
    if tokens:
        ev["tokens"] = tokens
    if t0 is not None:
        ev["ms"] = int((time.time() - t0) * 1000)
    return ev


def answer_stream(question: str, thread_id: str, use_memory: bool = True,
                  user_id: str = memory.DEFAULT_USER_ID):
    """Genera la respuesta emitiendo EVENTOS de cada paso del flujo.

    Es un generador: va devolviendo dicts (pasos) a medida que ocurren y,
    al final, un evento {"type": "result", ...} con la respuesta y el
    ORIGEN del contexto:
      memory    -> recuerdos por tipo {stm, episodic, semantic}
      documents -> cuantos fragmentos de la BBDD (Atlas) se usaron
    La UI usa estos eventos para el panel "Flujo de la peticion".
    """
    # Paso 1: memoria (leer).
    memory_ctx = ""
    memory_counts = {"stm": 0, "episodic": 0, "semantic": 0}
    if use_memory:
        yield _step("memory_read", "Memoria · leer contexto", "running")
        t0 = time.time()
        try:
            memory_ctx, memory_counts = memory.get_memory_context(question, thread_id, user_id)
            detail = (f"corta {memory_counts['stm']} · episódica {memory_counts['episodic']}"
                      f" · semántica {memory_counts['semantic']}")
            yield _step("memory_read", "Memoria · leer contexto", "done", detail, t0)
        except Exception as exc:  # la memoria no debe romper el chat
            print(f"[aviso] No se pudo recuperar memoria: {exc}")
            yield _step("memory_read", "Memoria · leer contexto", "error", str(exc)[:120], t0)
    else:
        yield _step("memory_read", "Memoria · leer contexto", "skipped", "memoria desactivada")

    # Paso 2: si hay recuerdos, intentamos responder SOLO con la memoria.
    # Si la memoria ya tiene la respuesta NO hace falta ir a la BBDD.
    answer_text = None
    docs_ctx: list[dict] = []
    usage_total = {"prompt": 0, "completion": 0, "total": 0}

    def add(u: dict):
        for k in usage_total:
            usage_total[k] += u[k]
    if memory_ctx:
        label = "LLM · ¿responde la memoria?"
        yield _step("memory_answer", label, "running")
        t0 = time.time()
        try:
            answer_text, mu = _answer_from_memory(question, memory_ctx)
            add(mu)
        except Exception as exc:
            mu = None
            print(f"[aviso] Fallo al responder desde memoria: {exc}")
        if answer_text:
            yield _step("memory_answer", label, "done", "sí: respondido solo con la memoria", t0, mu)
            yield _step("db_search", "BBDD · $vectorSearch", "skipped", "no hace falta: la memoria ya tenía la respuesta")
        else:
            yield _step("memory_answer", label, "done", "no basta → buscar en la BBDD", t0, mu)

    # Paso 3: si la memoria no basto, recuperacion (vector y/o grafo) y LLM.
    graph_entities: list[dict] = []
    graph_start: list[str] = []
    if answer_text is None:
        r = settings.get()["retrieval"]
        mode = r["mode"]
        rerank = " + $rerank" if config.RERANK_ENABLED else ""
        label = "BBDD · $vectorSearch" + rerank
        if mode in ("hybrid", "vector"):
            yield _step("db_search", label, "running")
            t0 = time.time()
            try:
                docs_ctx = vector_search.search(question, user_id, r["top_k"])
                files = sorted({d.get("metadata", {}).get("source", "?") for d in docs_ctx})
                yield _step("db_search", label, "done",
                            f"{len(docs_ctx)} fragmentos · " + (", ".join(files) if files else "sin resultados"), t0)
            except Exception as exc:
                print(f"[aviso] No se pudo buscar en documentos: {exc}")
                yield _step("db_search", label, "error", str(exc)[:120], t0)
        else:
            yield _step("db_search", label, "skipped", "modo grafo")

        glabel = "Grafo · LLM entidades + $graphLookup"
        if mode in ("hybrid", "graph"):
            yield _step("graph_search", glabel, "running")
            t0 = time.time()
            try:
                g = graph_store.retrieve(question, r["graph_depth"])
                graph_entities, graph_start = g["entities"], g["start"]
                detail = (f"inicio: {', '.join(graph_start)} · {len(graph_entities)} entidades" if graph_start
                          else "no se reconocieron entidades del grafo")
                yield _step("graph_search", glabel, "done", detail, t0)
            except Exception as exc:
                print(f"[aviso] No se pudo consultar el grafo: {exc}")
                yield _step("graph_search", glabel, "error", str(exc)[:120], t0)
        else:
            yield _step("graph_search", glabel, "skipped", "modo vector")

        model = settings.llm("chat")["model"]
        yield _step("llm", f"LLM · {model}", "running")
        t0 = time.time()
        system = _build_system_prompt(memory_ctx, docs_ctx, graph_entities)
        response = _llm().chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": question}],
        )
        answer_text = response.choices[0].message.content
        lu = _usage(response)
        add(lu)
        yield _step("llm", f"LLM · {model}", "done", "respuesta generada", t0, lu)
    else:
        yield _step("graph_search", "Grafo · LLM entidades + $graphLookup", "skipped", "la memoria ya tenia la respuesta")

    # Paso 4: memoria (guardar el turno).
    if use_memory:
        yield _step("memory_write", "Memoria · guardar turno", "running")
        t0 = time.time()
        try:
            memory.record_turn(thread_id, "user", question, user_id)
            memory.record_turn(thread_id, "assistant", answer_text, user_id)
            yield _step("memory_write", "Memoria · guardar turno", "done", "", t0)
        except Exception as exc:
            print(f"[aviso] No se pudo guardar memoria: {exc}")
            yield _step("memory_write", "Memoria · guardar turno", "error", str(exc)[:120], t0)
    else:
        yield _step("memory_write", "Memoria · guardar turno", "skipped", "memoria desactivada")

    yield {
        "type": "result",
        "reply": answer_text,
        "memory": memory_counts,
        "documents": len(docs_ctx),
        "tokens": usage_total,
        "graph": graph_view.subgraph_layout(graph_entities, highlight=graph_start),
        "sources": sorted({d.get("metadata", {}).get("source", "?") for d in docs_ctx}),
    }


def answer(question: str, thread_id: str, use_memory: bool = True,
           user_id: str = memory.DEFAULT_USER_ID) -> tuple[str, dict]:
    """Version sin streaming: devuelve (respuesta, memory)."""
    for ev in answer_stream(question, thread_id, use_memory, user_id):
        if ev["type"] == "result":
            return ev["reply"], ev["memory"]
