# Chat sobre PDFs con RAG + Memoria (MongoDB Atlas)

Proyecto **educacional** en Python: subes PDFs, se indexan automáticamente
con embeddings de **VoyageAI** vía **MongoDB Atlas**, y luego chateas sobre
ellos con **DeepSeek**. El chat **recuerda conversaciones anteriores**
gracias a **MongoDB Atlas Agent Engine Memory**.

Máxima prioridad: **sencillez y código comentado**.

## Arquitectura

```
PDF ──> pdf_processor (detecta imagenes) ──> embeddings (VoyageAI) ──> MongoDB Atlas
                                                                         │
Chat <── DeepSeek <── chat.py <── vector_search (Atlas Vector Search) ──┘
   │                 (memoria: agent-engine-sdk-memory)
   └───────────────────────────────────────────────────────────────────> recordar
```

### Estrategia de embedding (según el PDF)

Solo hay **dos** opciones, elegidas automáticamente según el contenido del PDF:

| Contenido del PDF      | Modelo                           | Qué se indexa        |
|------------------------|----------------------------------|----------------------|
| Solo texto             | `voyage-context-4`               | chunks de texto      |
| Con texto y/o imágenes | `voyage-multimodal-3.5`          | texto + imágenes     |

> **Detección automática:** al subir un PDF, `pdf_processor` detecta si
> contiene imágenes. Si las tiene → `voyage-multimodal-3.5`; si es solo
> texto → `voyage-context-4`. No hay que elegir nada a mano.

### Re-ranking con `$rerank`

Al consultar, los resultados del `$vectorSearch` se **reordenan** con el
stage `$rerank` de MongoDB (usa un modelo de re-ranking de Voyage AI) para
devolver los chunks más relevantes a la pregunta. Esto mejora la precisión
de las respuestas. Está activado y fijo en `app/config.py`
(`RERANK_ENABLED`, `RERANK_MODEL = "rerank-3"`, `RERANK_NUM_DOCS = 50`).

> **Requisitos de `$rerank`:** cluster MongoDB **9.0 o superior**, la
> opción **Native Reranking** habilitada en Project Settings de Atlas, y
> para `rerank-3` un **cluster dedicado (M10 o superior)**.

### Memoria (Atlas Agent Engine Memory)

La memoria de las conversaciones la gestiona **MongoDB Atlas Agent Engine
Memory** y se almacena en el **mismo cluster** que los documentos. Requiere
una **organización Atlas-backed** (vinculada a un proyecto de Atlas).

```bash
# 0) Prerrequisitos
#  - Org de Atlas Agent Engine Atlas-backed (con un cluster de Atlas)
#  - CLI instalado y autenticado:  agentengine auth login
#  - Credenciales de service-account de Atlas (para el setup de IPs)

# 1) Crear un proyecto de memoria (project-config.yaml con el bloque memory:)
agentengine create --memory-only --name "Mi Proyecto"

# 2) Crear un context apuntando al proyecto Atlas-backed
agentengine context create mi-memoria \
  --org-id <org-id-atlas-backed> \
  --project-id <project-id-atlas> \
  --base-url https://agentengine.mongodb.com

# 3) Subir secretos (MONGODB_URI = mismo cluster que documentos)
agentengine secret set MONGODB_URI --project-scope
agentengine secret set VOYAGE_API_KEY --project-scope
agentengine secret set LLM_API_KEY --project-scope
agentengine secret set MONGODB_DATABASE --project-scope

# 4) Aplicar la configuracion de memoria
agentengine memory configure --context mi-memoria
agentengine memory apply --wait --context mi-memoria

# 5) Añadir las IPs del data plane de Agent Engine al cluster
#    (requiere perfil Atlas valido y el proyecto ligado)
agentengine atlas profile save --context mi-memoria
agentengine atlas setup-ip-access --context mi-memoria

# 6) Crear un service-account (devuelve client id y client secret)
agentengine service-account create memory-service --context mi-memoria --role PROJECT_OWNER
```

En el `.env` de la app se necesitan:
```
AGENTIC_MEMORY_PROJECT_ID=<project-id>
AGENTIC_MEMORY_CLIENT_ID=<client-id>
AGENTIC_MEMORY_CLIENT_SECRET=<client-secret>
```

> **Notas:**
> - El **service-account** con rol `PROJECT_OWNER`/`PROJECT_READ_ONLY` exige
>   el **"Atlas service account pairing"** habilitado en el proyecto.
> - La app canjea el client id/secret por un token de acceso y lo renueva sola.
> - El **IP access list** del cluster debe permitir el tráfico del data plane
>   de Agent Engine (se añade con `atlas setup-ip-access`).

## Requisitos previos

1. Python 3.11 o superior (requerido por el SDK de Agent Engine Memory).
2. Un cluster **MongoDB Atlas** (M10+ recomendado para Vector Search).
3. Una API key de **VoyageAI**.
4. Una API key de **DeepSeek**.
5. Acceso a **Agent Engine Memory** (client id/secret de service-account + project id,
   o un backend local).

## Instalación y ejecución

```bash
# 1) Clonar y entrar
git clone <repo-url>
cd advancedRAG_memory

# 2) Crear entorno virtual e instalar dependencias
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 3) Configurar credenciales
cp .env.example .env
# ... editar .env con tus credenciales reales ...

# 4) Arrancar la UI (los indices se crean solos en el arranque)
uvicorn app.main:app --reload --port 8090
```

Abre http://localhost:8090 en el navegador.

## Crear los índices (automático)

Los índices de Atlas Vector Search **se crean en código**, no en la UI de
Atlas. Al arrancar la app (`app/setup_indexes.py`) se aseguran estos dos
índices si no existen ya:

| Índice | Colección | Tipo | Campo |
|---|---|---|---|
| `idx_vector_text` | `documents_text` | `vector` | `embedding` / 1024 dims |
| `idx_vector_multimodal` | `documents_multimodal` | `vector` | `embedding` / 1024 dims |

Si prefieres crearlos a mano, las definiciones JSON equivalentes son:

### 1) `documents_text` — índice vector texto (`voyage-context-4`)
```json
{
  "name": "idx_vector_text",
  "type": "vectorSearch",
  "fields": [
    { "type": "vector", "path": "embedding", "numDimensions": 1024, "similarity": "cosine" }
  ]
}
```

### 2) `documents_multimodal` — índice vector multimodal (`voyage-multimodal`)
```json
{
  "name": "idx_vector_multimodal",
  "type": "vectorSearch",
  "fields": [
    { "type": "vector", "path": "embedding", "numDimensions": 1024, "similarity": "cosine" }
  ]
}
```

## Variables de entorno (`.env`)

El `.env` contiene solo las **credenciales**. Modelos de Voyage, base de datos,
colecciones, índices y re-ranking están fijos en `app/config.py`.

| Variable | Descripción |
|---|---|
| `DEEPSEEK_API_KEY` | API key del LLM (también editable en caliente desde la UI) |
| `DEEPSEEK_BASE_URL` / `DEEPSEEK_MODEL` | (opcionales) URL base y modelo del LLM |
| `VOYAGE_API_KEY` | API key de VoyageAI |
| `MONGODB_URI` | Cadena de conexión a Atlas |
| `AGENTIC_MEMORY_PROJECT_ID` | Project id de Agent Engine Memory |
| `AGENTIC_MEMORY_CLIENT_ID` / `AGENTIC_MEMORY_CLIENT_SECRET` | Credenciales del service account de Agent Engine Memory |
| `AGENTIC_MEMORY_BASE_URL` | (opcional) backend local de memoria |

## Estructura del proyecto

```
app/
├── main.py           # FastAPI + rutas (/ , /upload, /chat)
├── config.py         # credenciales (.env) y ajustes fijos
├── setup_indexes.py  # crea los indices de Atlas Vector Search (en codigo)
├── pdf_processor.py  # extrae texto/imagenes, detecta imagenes y trocea
├── embeddings.py     # genera vectores (auto / text / multimodal)
├── vector_search.py  # $vectorSearch en Atlas
├── memory.py         # Agent Engine Memory (recordar conversaciones)
├── chat.py           # orquesta el pipeline y llama a DeepSeek
└── static/           # UI (HTML/CSS/JS)
```

## Notas sobre el código

- **Seguridad:** ninguna credencial está en el código. Todo vive en `.env`
  (ignorado por git); se versiona únicamente `.env.example`.
- **Memoria persistente:** el navegador guarda un `thread_id` en
  `localStorage`. Ese id se usa como `session_id` en Agent Engine Memory,
  de modo que al volver, el chat recupera el contexto de sesiones previas
  mediante `build_context`.
- **Dos modelos de embedding:** los PDFs de solo texto se indexan con
  `voyage-context-4`; los PDFs con imágenes con `voyage-multimodal-3.5`.
  La app detecta automáticamente cuál usar al subir cada documento.