# ============================================================
#  config.py
#  ------------------------------------------------------------------
#  Ajustes de la Demo, en dos grupos:
#
#  1) CREDENCIALES (secretos): se leen del .env, que NO se sube a git.
#       MONGODB_URI, VOYAGE_API_KEY, DEEPSEEK_API_KEY y AGENTIC_MEMORY_*
#     (los LLM tambien se pueden cambiar en caliente desde la pestana Configuracion).
#
#  2) AJUSTES FIJOS: modelos de Voyage, base de datos, colecciones,
#     indices y re-ranking. Van AQUI, en el codigo, y NO se pueden
#     cambiar desde el .env: asi todas las instalaciones de la Demo se
#     comportan igual y nadie rompe la configuracion por accidente.
#
#  Regla de seguridad: ningun API key ni URI va en el codigo.
# ============================================================

import os

from dotenv import load_dotenv

# Carga las variables definidas en el archivo .env al entorno.
# Si no existe el archivo, no falla: simplemente usa los defaults.
load_dotenv()

# ======================= 1) CREDENCIALES (.env) =======================

# ------------------------- LLM (compatible con OpenAI) -------------------------
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash-0731")

# ------------------------- VoyageAI -------------------------
VOYAGE_API_KEY = os.getenv("VOYAGE_API_KEY")

# ------------------------- MongoDB Atlas -------------------------
MONGODB_URI = os.getenv("MONGODB_URI")

# ------------------------- GitHub (opcional) -------------------------
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

# ------------------------- Atlas Agent Engine Memory -------------------------
# Servicio alojado: project_id + client id/secret del service account.
# Para desarrollo local se puede usar AGENTIC_MEMORY_BASE_URL y dejar lo demas vacio.
AGENTIC_MEMORY_PROJECT_ID = os.getenv("AGENTIC_MEMORY_PROJECT_ID")
AGENTIC_MEMORY_CLIENT_ID = os.getenv("AGENTIC_MEMORY_CLIENT_ID")
AGENTIC_MEMORY_CLIENT_SECRET = os.getenv("AGENTIC_MEMORY_CLIENT_SECRET")
AGENTIC_MEMORY_BASE_URL = os.getenv("AGENTIC_MEMORY_BASE_URL")

# ======================= 2) AJUSTES FIJOS (no editables por .env) =======================
# Lo que SI se elige desde la UI (estrategia, modelos, chunking...) vive en settings.py.

MONGODB_DB = "graphrag_demo"

# Ventaja MongoDB: chunks, vectores, grafo, flujos y ajustes en el MISMO cluster.
COLL_AUTO = "chunks_auto"              # chunking manual + autoEmbed (Atlas genera los vectores)
COLL_CONTEXT = "chunks_context"        # voyage-context (vectores generados por la app)
COLL_MULTIMODAL = "chunks_multimodal"  # voyage-multimodal (texto + imagen)
COLL_GRAPH = "knowledge_graph"         # entidades + relaciones (MongoDBGraphStore)
COLL_FLOWS = "request_flows"
COLL_SETTINGS = "app_settings"

VECTOR_INDEX_CONTEXT = "idx_vector_context"
VECTOR_INDEX_MULTIMODAL = "idx_vector_multimodal"
AUTO_INDEX_PREFIX = "idx_auto_"        # + nombre del modelo, p.ej. idx_auto_voyage-4
VECTOR_DIMENSIONS = 1024

STRATEGIES = ("auto_embed", "voyage_context", "voyage_multimodal")
EMBEDDING_MODELS = {
    "auto_embed": ["voyage-4", "voyage-4-lite", "voyage-4-large"],
    "voyage_context": ["voyage-context-4", "voyage-context-3"],
    "voyage_multimodal": ["voyage-multimodal-3.5", "voyage-multimodal-3"],
}
# Chunking fijo para las estrategias manuales (solo autoEmbed lo deja elegir en la UI).
FIXED_CHUNK_SIZE = 1000
FIXED_CHUNK_OVERLAP = 200
CHUNK_SIZE_RANGE = (200, 4000)      # limites de los sliders
# Para el grafo se usan trozos mas grandes: 1 llamada al LLM por trozo (coste).
GRAPH_CHUNK_SIZE = 4000

GRAPH_ENTITY_TYPES = [
    "Repository", "Library", "Database", "Service", "Endpoint", "Team",
    "File", "Class", "Function", "Document", "Concept", "Person", "Organization",
]
GRAPH_RELATIONSHIP_TYPES = [
    "DEPENDS_ON", "USES_DATABASE", "USES_SERVICE", "EXPOSES_ENDPOINT", "CALLS_ENDPOINT",
    "OWNED_BY", "CONTAINS", "DEFINES", "CALLS", "IMPORTS", "DOCUMENTS", "RELATED_TO",
]

GITHUB_API = "https://api.github.com"
GITHUB_RAW = "https://raw.githubusercontent.com"
GITHUB_MAX_FILES = 150          # ficheros de codigo analizados por repo
GITHUB_MAX_FILE_BYTES = 100_000
GITHUB_MAX_DOCS = 10            # README/docs .md que pasan por el LLM (coste)

# Re-ranking con $rerank (cluster 9.0+ y Native Reranking activado).
RERANK_ENABLED = True
RERANK_MODEL = "rerank-3"
RERANK_NUM_DOCS = 50
