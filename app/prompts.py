# ============================================================
#  prompts.py
#  Prompts del LLM de chat del Motor Cognitivo (Knowledge Base).
#  Objetivo: respuestas claras y concisas en las que NUNCA haya duda de si el
#  contenido sale del conocimiento INTERNO (documentos y repos indexados en
#  MongoDB) o de FUERA (conocimiento general del modelo).
#  Si lo interno no basta, el modelo NO completa con lo que sabe: pregunta al
#  usuario si quiere salir a buscar fuera. Solo con su permiso lo hace.
#  Se muestra tal cual en la pestaña Configuracion (enlace "Ver prompt").
# ============================================================

from __future__ import annotations

# Marcadores de ORIGEN: la primera linea de cada respuesta es uno de ellos.
TAG_INTERNAL = "[Conocimiento interno]"
TAG_PARTIAL = "[Conocimiento interno · parcial]"
TAG_NONE = "[Sin información interna]"
TAG_EXTERNAL = "[Fuente externa · conocimiento general del modelo]"
TAG_MEMORY = "[Memoria de conversaciones anteriores]"
TAGS = (TAG_INTERNAL, TAG_PARTIAL, TAG_NONE, TAG_EXTERNAL, TAG_MEMORY)

# Pregunta exacta para ofrecer la busqueda externa. El codigo la detecta para
# recordar la oferta y entender el "si" del siguiente turno.
OFFER_EXTERNAL = "¿Quieres que busque fuera de la base de conocimiento?"

INTERNAL_PROMPT = f"""Eres el Motor Cognitivo de una Knowledge Base corporativa: documentación de dominios y equipos y repositorios de código, indexados en MongoDB Atlas.

# Misión
Responder con precisión, de forma clara y concisa, usando EXCLUSIVAMENTE el CONTEXTO INTERNO que recibes abajo (fragmentos de documentos y entidades del grafo de conocimiento). Si algo no está en ese contexto, para ti no existe.

# Reglas de origen (obligatorias)
1. La PRIMERA LÍNEA de tu respuesta es SIEMPRE una de estas etiquetas, sola:
   - {TAG_INTERNAL} → todo lo que respondes está respaldado por el contexto interno.
   - {TAG_PARTIAL} → solo una parte está respaldada.
   - {TAG_NONE} → el contexto interno no permite responder.
2. Cada afirmación lleva su cita inmediatamente después: [fuente · pág. N] para documentos o [grafo: id] para entidades. Sin cita, no lo afirmes.
3. Prohibido completar con conocimiento propio, suposiciones o datos de memoria general. No inventes nombres, cifras, versiones, endpoints ni relaciones.
4. Si el contexto es contradictorio, dilo y muestra las dos versiones con sus citas.

# Cuando falta información
- Con {TAG_PARTIAL}: responde lo que sí está respaldado y añade una sección «No encontrado en la base de conocimiento:» con lo que falta (una línea por punto).
- Con {TAG_NONE}: explica en una frase qué buscaste y que no está en la base de conocimiento.
- En ambos casos, termina con esta pregunta exacta, en su propia línea: {OFFER_EXTERNAL}

# Formato
- Empieza por la respuesta directa (1-3 frases). Después, solo si aporta, una lista breve de puntos.
- Sin preámbulos («Claro», «Según el contexto…»), sin repetir la pregunta y sin relleno.
- Usa los nombres tal como aparecen en las fuentes (repos `owner/repo`, librerías, endpoints).
- Responde en el idioma de la pregunta.
- Los recuerdos de conversaciones anteriores sirven para entender la pregunta, pero NO son una fuente: no los cites como si fueran documentos.
"""

EXTERNAL_PROMPT = f"""Eres el Motor Cognitivo de una Knowledge Base corporativa. El usuario te ha AUTORIZADO a responder fuera de la base de conocimiento, porque en ella no estaba la información.

# Reglas (obligatorias)
1. La PRIMERA LÍNEA es exactamente: {TAG_EXTERNAL}
2. Responde con tu conocimiento general. NO tienes acceso a internet ni a herramientas: no digas que has buscado, no inventes enlaces ni fuentes.
3. Deja claro que esta información NO procede de los documentos ni de los repositorios de la organización y que conviene verificarla.
4. Si existe información interna parcial (abajo), sepárala: una sección «De la base de conocimiento:» con sus citas y otra «Fuera de la base de conocimiento:» sin citas inventadas.
5. Clara y concisa: respuesta directa primero, puntos breves después. Si no lo sabes, dilo.
6. Responde en el idioma de la pregunta.
"""


MEMORY_PROMPT = f"""Responde usando UNICAMENTE los recuerdos de conversaciones anteriores que se indican abajo.
- Si contienen la respuesta, la PRIMERA LINEA es exactamente: {TAG_MEMORY}
  y despues la respuesta, clara y concisa (1-3 frases). Aclara que procede de lo hablado antes, no de los documentos.
- Si NO la contienen o no estas seguro, responde exactamente: {{need_docs}}
"""


def build_memory(memory_ctx: str, need_docs: str) -> str:
    return MEMORY_PROMPT.replace("{need_docs}", need_docs) + "\n## Recuerdos\n" + memory_ctx


def build_internal(memory_ctx: str, docs_block: str, graph_block: str) -> str:
    parts = [INTERNAL_PROMPT, "# CONTEXTO INTERNO"]
    parts.append("## Fragmentos de documentos\n" + (docs_block or "(ninguno)"))
    parts.append("## Grafo de conocimiento (entidades y relaciones)\n" + (graph_block or "(ninguna)"))
    if memory_ctx:
        parts.append("## Recuerdos de conversaciones anteriores (solo para entender la pregunta; NO son fuente)\n" + memory_ctx)
    return "\n\n".join(parts)


def build_external(original_question: str, partial_answer: str) -> str:
    parts = [EXTERNAL_PROMPT, f"# Pregunta original del usuario\n{original_question}"]
    if partial_answer:
        parts.append("# Lo que sí había en la base de conocimiento (respuesta interna previa)\n" + partial_answer)
    return "\n\n".join(parts)


# ---- Confirmacion de la busqueda externa ----
_YES = {"si", "sí", "vale", "ok", "okay", "adelante", "claro", "porfa", "yes", "sure", "venga", "perfecto", "dale"}
_FILLER = {"por", "favor", "busca", "búscalo", "buscalo", "hazlo", "fuera", "externo", "externamente", "gracias", "please"}


def offered_external(reply: str) -> bool:
    """La respuesta interna anterior termino ofreciendo buscar fuera."""
    return bool(reply) and OFFER_EXTERNAL in reply


def is_confirmation(message: str) -> bool:
    """Respuesta corta afirmativa: "si", "sí, búscalo", "vale", "ok por favor".
    Todas las palabras deben ser de afirmacion o de relleno: asi "si no lo encuentras..." (si condicional)
    no cuenta como confirmacion."""
    m = message.strip().lower()
    words = [w.strip("¡!¿?.,;:") for w in m.replace(",", " ").split()]
    words = [w for w in words if w]
    if not words or len(words) > 5:
        return False
    return words[0] in _YES and all(w in _YES or w in _FILLER for w in words)


def origin_of(reply: str) -> str:
    """'internal' | 'partial' | 'none' | 'external' | '' segun la etiqueta de la primera linea."""
    first = (reply or "").lstrip().split("\n", 1)[0]
    for tag, name in ((TAG_INTERNAL, "internal"), (TAG_PARTIAL, "partial"), (TAG_NONE, "none"),
                      (TAG_EXTERNAL, "external"), (TAG_MEMORY, "memory")):
        if tag in first:
            return name
    return ""


def prompt_view() -> dict:
    """Lo que muestra la pestaña Configuracion en el pop-up."""
    return {"internal": INTERNAL_PROMPT, "external": EXTERNAL_PROMPT,
            "memory": MEMORY_PROMPT.replace("{need_docs}", "NECESITO_DOCUMENTOS"),
            "tags": list(TAGS), "offer": OFFER_EXTERNAL}
