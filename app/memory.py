# ============================================================
#  memory.py
#  ------------------------------------------------------------------
#  Integra MongoDB Atlas Agent Engine Memory (SDK agent-engine-sdk-memory).
#
#  Que hace la memoria aqui?
#  * record_turn(...)   -> guarda cada turno de la conversacion.
#  * build_context(...) -> antes de responder, recupera de conversaciones
#                          ANTERIORES el contexto relevante para la pregunta.
#
#  Asi el chat "recuerda" cosas habladas en sesiones previas (memoria
#  de largo plazo), no solo lo dicho en la conversacion actual.
#
#  IMPORTANTE: para "recordar entre sesiones" usamos un session_id
#  ESTABLE por conversacion. El navegador guarda ese id (thread_id) y
#  lo reutiliza en futuras preguntas.
# ============================================================

from __future__ import annotations

import time

import httpx
from agent_engine_sdk_memory import Memory, MemoryRequestContext

import config

# Identidad del usuario. En un proyecto educacional de un solo usuario
# basta un valor fijo; en produccion vendria de la autenticacion.
DEFAULT_USER_ID = "demo-user"


# Cache del token de acceso (se canjea con client id/secret y caduca a la hora).
_token = {"value": None, "exp": 0.0}
TOKEN_URL = "https://agentengine.mongodb.com/api/v1/oauth/token"


def _service_token() -> str | None:
    """Canjea CLIENT_ID/CLIENT_SECRET por un token de acceso.

    Se reutiliza ~50 min y se renueva solo antes de caducar.
    """
    if not (config.AGENTIC_MEMORY_CLIENT_ID and config.AGENTIC_MEMORY_CLIENT_SECRET):
        return None
    if not _token["value"] or time.time() > _token["exp"]:
        r = httpx.post(
            TOKEN_URL,
            auth=(config.AGENTIC_MEMORY_CLIENT_ID, config.AGENTIC_MEMORY_CLIENT_SECRET),
            data={"grant_type": "client_credentials"},
            timeout=15,
        )
        r.raise_for_status()
        _token["value"] = r.json()["access_token"]
        _token["exp"] = time.time() + 50 * 60
    return _token["value"]


def is_configured() -> bool:
    """Indica si la memoria de Agent Engine esta configurada en el .env.

    Devuelve True si hay credenciales validas (alojado o local). Si no
    hay credenciales, la app funciona igual, simplemente sin memoria.
    """
    has_credentials = config.AGENTIC_MEMORY_CLIENT_ID and config.AGENTIC_MEMORY_CLIENT_SECRET
    if has_credentials and config.AGENTIC_MEMORY_PROJECT_ID:
        return True
    if config.AGENTIC_MEMORY_BASE_URL:
        return True
    return False


def _build_memory() -> Memory:
    """Construye el objeto Memory segun la configuracion del .env.

    Dos formas de conectarse (ver docs del SDK):
      * Servicio alojado: client id/secret + project_id.
      * Local:            base_url apuntando a tu backend local.
    """
    token = _service_token()
    if token and config.AGENTIC_MEMORY_PROJECT_ID:
        return Memory(
            service_account_token=token,
            project_id=config.AGENTIC_MEMORY_PROJECT_ID,
        )
    if config.AGENTIC_MEMORY_BASE_URL:
        return Memory(base_url=config.AGENTIC_MEMORY_BASE_URL)
    # Si no hay credenciales, lanzamos un error claro.
    raise RuntimeError(
        "Faltan credenciales de Agent Engine Memory en el .env "
        "(AGENTIC_MEMORY_CLIENT_ID/SECRET + AGENTIC_MEMORY_PROJECT_ID "
        "o AGENTIC_MEMORY_BASE_URL)."
    )


def get_memory_context(query: str, thread_id: str, user_id: str = DEFAULT_USER_ID) -> tuple[str, dict]:
    """Recupera el contexto relevante de memoria.

    Devuelve (texto, counts):
      - texto:  contexto listo para pegar en el prompt.
      - counts: cuantos recuerdos aporto cada tipo de memoria, p.ej.
                {"stm": 2, "episodic": 1, "semantic": 0}.
                stm = lo dicho en ESTA conversacion; episodic/semantic =
                recuerdos consolidados de conversaciones pasadas.

    user_id identifica a la persona (memoria episodica/semantica) y thread_id
    la conversacion (memoria corta).
    Hacemos un bind() con el usuario y la conversacion (thread) para que
    la memoria se lea SOLO de esa conversacion y de ese usuario.
    """
    memory = _build_memory()
    session = memory.bind(
        MemoryRequestContext(user_id=user_id, session_id=thread_id)
    )
    # enabled_sources: stm (lo recien dicho), episodic (resumen de episodios
    # pasados) y semantic (hechos aprendidos). max_tokens limita el presupuesto.
    ctx = session.build_context(
        query=query,
        enabled_sources={"stm", "episodic", "semantic"},
        max_tokens=1024,
    )
    # metadata.memory_counts indica cuantos recuerdos vienen de cada fuente.
    raw = ctx.metadata.memory_counts or {}
    counts = {k: int(raw.get(k, 0)) for k in ("stm", "episodic", "semantic")}

    # .formatted_context puede ser texto o una lista de mensajes
    # {role, content}; lo normalizamos siempre a un unico string.
    fc = ctx.formatted_context or ""
    if isinstance(fc, str):
        return fc, counts
    partes = []
    for b in fc:
        if isinstance(b, dict):
            partes.append(f"{b.get('role', 'memoria')}: {b.get('content') or b.get('text') or b}")
        else:
            partes.append(str(b))
    return "\n".join(partes), counts


def record_turn(thread_id: str, role: str, content: str, user_id: str = DEFAULT_USER_ID) -> None:
    """Guarda un turno (user o assistant) en la memoria.

    Hay que llamarlo DESPUES de responder, para que la conversacion
    quede registrada y pueda ser recordada en el futuro.
    """
    memory = _build_memory()
    session = memory.bind(
        MemoryRequestContext(user_id=user_id, session_id=thread_id)
    )
    session.record_turn(role=role, content=content)