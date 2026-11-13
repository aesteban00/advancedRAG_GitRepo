# ============================================================
#  config.py
#  ------------------------------------------------------------------
#  Ajustes de la Demo, en dos grupos:
#
#  1) CREDENCIALES (secretos): se leen del .env, que NO se sube a git.
#       MONGODB_URI, VOYAGE_API_KEY, DEEPSEEK_API_KEY y AGENTIC_MEMORY_*
#     (el LLM tambien se puede cambiar en caliente desde el panel derecho).
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

# ------------------------- Atlas Agent Engine Memory -------------------------
# Servicio alojado: project_id + client id/secret del service account.
# Para desarrollo local se puede usar AGENTIC_MEMORY_BASE_URL y dejar lo demas vacio.
AGENTIC_MEMORY_PROJECT_ID = os.getenv("AGENTIC_MEMORY_PROJECT_ID")
AGENTIC_MEMORY_CLIENT_ID = os.getenv("AGENTIC_MEMORY_CLIENT_ID")
AGENTIC_MEMORY_CLIENT_SECRET = os.getenv("AGENTIC_MEMORY_CLIENT_SECRET")
AGENTIC_MEMORY_BASE_URL = os.getenv("AGENTIC_MEMORY_BASE_URL")

# ======================= 2) AJUSTES FIJOS (no editables) =======================

# ------------------------- Modelos de Voyage -------------------------
# Texto: "contextualized chunk embeddings" (PDFs sin imagenes).
VOYAGE_MODEL_TEXT = "voyage-context-4"
# Multimodal: texto + imagen juntos (PDFs con imagenes).
VOYAGE_MODEL_MULTIMODAL = "voyage-multimodal-3.5"

# ------------------------- Base de datos y colecciones -------------------------
MONGODB_DB = "pdf_chat"
COLL_TEXT = "documents_text"              # chunks de PDFs sin imagenes
COLL_MULTIMODAL = "documents_multimodal"  # chunks de PDFs con imagenes
COLL_FLOWS = "request_flows"              # flujo de cada peticion (flow_store.py)

# ------------------------- Indices de Atlas Vector Search -------------------------
# Se crean solos al arrancar (ver setup_indexes.py).
VECTOR_INDEX_TEXT_MANUAL = "idx_vector_text"
VECTOR_INDEX_MULTIMODAL = "idx_vector_multimodal"

# ------------------------- Re-ranking con $rerank -------------------------
# Reordena los resultados de la busqueda vectorial con un modelo de Voyage.
# Requisitos: cluster MongoDB 9.0+ y "Native Reranking" activado en Atlas.
RERANK_ENABLED = True
RERANK_MODEL = "rerank-3"
RERANK_NUM_DOCS = 50  # documentos que se envian al modelo para reordenar
