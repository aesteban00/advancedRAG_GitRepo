# GraphRAG avanzado sobre documentos y repos de GitHub (MongoDB Atlas)

Proyecto **educacional** en Python: sube documentos (`.pdf`, `.md`, `.txt`) o analiza repositorios de GitHub y pregunta sobre ellos en un chat que combina **búsqueda vectorial** y **GraphRAG**, todo sobre **una sola plataforma: MongoDB Atlas**. Cada respuesta cita sus fuentes y muestra el subgrafo usado (NetworkX).

## Por qué MongoDB

| Ventaja | Dónde se ve |
|---|---|
| **Una sola base de conocimiento**: chunks, vectores, grafo, memoria, flujos y ajustes en el mismo cluster | BD `graphrag_demo` |
| **Grafo nativo con `$graphLookup`**: un documento por entidad, recorrido dentro de la BD (sin cargar el grafo en memoria ni una base de grafos aparte) | `graph_store.py` |
| **Automated Embedding (`autoEmbed`)**: Atlas genera y sincroniza los vectores con Voyage AI; la app solo inserta texto | estrategia `auto_embed` |
| **Voyage AI y `$rerank` integrados** | estrategias manuales + `$rerank` |
| **Esquema flexible**: repos, librerías, endpoints, funciones, documentos… en la misma colección | `knowledge_graph` |
| **Respuestas con fuente**: cada chunk y cada entidad guardan su origen | prompt y citas |

## Arquitectura

```
 ficheros / carpeta ─► loaders ─► chunking ─► ingest ─┬─► chunks_auto | chunks_context | chunks_multimodal
 URLs GitHub ─► github_ingest ─┬─ grafo determinista ─┼─► knowledge_graph  (+ LLM de grafo: MongoDBGraphStore)
                               └─ README/docs ────────┘
 Chat ─► memoria (Agent Engine) ─► $vectorSearch + $rerank ─┐
                               └─► entidades (LLM) + $graphLookup ─► LLM de chat ─► respuesta + subgrafo (NetworkX → SVG)
```

## Estrategias de ingesta (pestaña Configuración)

| Estrategia | Vectores | Chunking | Colección | Índice |
|---|---|---|---|---|
| `auto_embed` | Atlas (`autoEmbed`) | **tamaño y solape elegibles** | `chunks_auto` | `idx_auto_<modelo>` |
| `voyage_context` | app → `voyage-context-4` | fijo (1000/200) | `chunks_context` | `idx_vector_context` |
| `voyage_multimodal` | app → `voyage-multimodal-3.5` | página = chunk | `chunks_multimodal` | `idx_vector_multimodal` |

Se puede elegir un modelo de **embedding**, un **LLM para construir el grafo** y otro **para el chat** (por defecto el mismo, el del `.env`).

## GraphRAG

Cada entidad es un documento `{_id, type, attributes, relationships:{target_ids, types, attributes}}` (formato de `MongoDBGraphStore`, [guía oficial](https://www.mongodb.com/docs/atlas/ai-integrations/langchain/graph-rag/)). La consulta extrae entidades de la pregunta con el LLM, recorre salientes con `$graphLookup` y entrantes con un índice multikey sobre `relationships.target_ids` ("¿quién usa X?").

De cada repo de GitHub se extrae, sin LLM: descripción, librerías y versiones (requirements, pyproject, package.json, go.mod, pom.xml), BBDD/servicios, endpoints (FastAPI/Flask/Express/Spring), propietario (CODEOWNERS), ficheros/clases/funciones Python con sus llamadas, y relaciones entre repos (librería interna o endpoint consumido). README y `docs/*.md` pasan por la ingesta normal.

## Requisitos previos
1. Python 3.11 o superior (lo exige el SDK de Agent Engine Memory).
2. Cluster **MongoDB Atlas** con Vector Search y Automated Embedding (M10+ recomendado). `$rerank` requiere **MongoDB 9.0+**, **Native Reranking** activado en Project Settings y, para `rerank-3`, M10+. Si tu cluster no lo cumple, pon `RERANK_ENABLED = False` en `app/config.py`.
3. API key de **Voyage AI** (solo para las estrategias manuales `voyage_context` y `voyage_multimodal`).
4. API key de un **LLM compatible con OpenAI** (por defecto DeepSeek).
5. Opcional: `GITHUB_TOKEN` (sube el límite de la API de GitHub de 60 a 5000 peticiones/h) y acceso a **Agent Engine Memory** (ver más abajo).

## Instalación y ejecución
```bash
git clone <repo-url> && cd advancedRAG_GitRepo
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # rellena las credenciales
uvicorn app.main:app --reload --port 8090
```
Abre http://localhost:8090. Al arrancar se crean **en código** las colecciones y los índices (logs `[setup]`).

| Índice | Colección | Tipo |
|---|---|---|
| `idx_auto_<modelo>` (p. ej. `idx_auto_voyage-4`) | `chunks_auto` | `autoEmbed` sobre `text` |
| `idx_vector_context` | `chunks_context` | `vector`, 1024 dims, cosine |
| `idx_vector_multimodal` | `chunks_multimodal` | `vector`, 1024 dims, cosine |
| `type` y `relationships.target_ids` | `knowledge_graph` | índices normales (el segundo, multikey, resuelve aristas entrantes) |

Todos los de búsqueda llevan además campos `filter` (`metadata.visibility`, `metadata.owner`, `metadata.model`). Un índice `autoEmbed` no se puede editar: al cambiar de modelo se crea uno nuevo.

## Variables de entorno (`.env`)
Solo **credenciales**. Colecciones, índices y re-ranking están fijos en `app/config.py`; estrategia, modelos y LLMs se eligen en la pestaña Configuración.

| Variable | Descripción |
|---|---|
| `DEEPSEEK_API_KEY` | API key del LLM (editable en caliente desde Configuración, solo en memoria) |
| `DEEPSEEK_BASE_URL` / `DEEPSEEK_MODEL` | (opcionales) URL base y modelo del LLM por defecto |
| `VOYAGE_API_KEY` | API key de Voyage AI (estrategias manuales) |
| `MONGODB_URI` | Cadena de conexión a Atlas |
| `GITHUB_TOKEN` | (opcional) token de solo lectura para la API de GitHub |
| `AGENTIC_MEMORY_PROJECT_ID` | Project id de Agent Engine Memory |
| `AGENTIC_MEMORY_CLIENT_ID` / `AGENTIC_MEMORY_CLIENT_SECRET` | Credenciales del service account de memoria |
| `AGENTIC_MEMORY_BASE_URL` | (opcional) backend local de memoria |

## Memoria (Atlas Agent Engine Memory)
La memoria de las conversaciones la gestiona **Agent Engine Memory** y se guarda en el **mismo cluster** que los documentos. Es opcional: sin ella (o si falla, p. ej. `AGENT_NOT_DEPLOYED`) el chat sigue funcionando y el paso de memoria aparece en rojo en el panel de flujo. Requiere una organización Atlas-backed.

```bash
# 0) CLI instalado y autenticado
agentengine auth login

# 1) Proyecto de memoria (genera project-config.yaml con el bloque memory:)
agentengine create --memory-only --name "Mi Proyecto"

# 2) Context apuntando al proyecto Atlas-backed
agentengine context create mi-memoria \
  --org-id <org-id> --project-id <project-id> \
  --base-url https://agentengine.mongodb.com

# 3) Secrets de proyecto (Consola > Secrets > Add Secrets, o por CLI)
#    MONGODB_URI = mismo cluster que los documentos; MONGODB_DATABASE = graphrag_demo
agentengine secret set MONGODB_URI --project-scope
agentengine secret set VOYAGE_API_KEY --project-scope
agentengine secret set LLM_API_KEY --project-scope
agentengine secret set MONGODB_DATABASE --project-scope

# 4) Aplicar la configuración de memoria (desde la carpeta de project-config.yaml)
agentengine memory configure --context mi-memoria
agentengine memory apply --wait --context mi-memoria

# 5) Permitir las IPs del data plane en el cluster
agentengine atlas profile save --context mi-memoria
agentengine atlas setup-ip-access --context mi-memoria

# 6) Crear y desplegar el workspace (sin esto: AGENT_NOT_DEPLOYED / NO_WORKSPACE_ENDPOINT)
agentengine init && agentengine deploy

# 7) Service account (devuelve client id y secret)
agentengine service-account create memory-service --context mi-memoria --role PROJECT_OWNER
```
Y en el `.env`: `AGENTIC_MEMORY_PROJECT_ID`, `AGENTIC_MEMORY_CLIENT_ID`, `AGENTIC_MEMORY_CLIENT_SECRET`.

> - El service account con rol `PROJECT_OWNER`/`PROJECT_READ_ONLY` exige el *Atlas service account pairing* en el proyecto.
> - Los cambios en Secrets se aplican en el siguiente despliegue o al forzar una sincronización.
> - La app canjea el client id/secret por un token y lo renueva sola; la organización nunca va en el `.env`.
> - Si la sesión de la CLI caduca (`session expired`), repite `agentengine auth login`.

## Estructura del proyecto
```
app/
├── main.py            # FastAPI: chat, ajustes, ingesta, estado y grafo
├── config.py          # credenciales (.env) y constantes fijas
├── settings.py        # ajustes editables desde la UI (se guardan en MongoDB, sin secretos)
├── db.py              # MongoClient compartido
├── setup_indexes.py   # colecciones e índices en código
├── loaders.py         # pdf/md/txt -> páginas -> chunks
├── embeddings.py      # Voyage manual (context / multimodal)
├── ingest.py          # ingesta de un documento según la estrategia + grafo
├── github_ingest.py   # repos de GitHub -> grafo determinista + docs
├── graph_store.py     # GraphRAG: MongoDBGraphStore + $graphLookup
├── graph_view.py      # NetworkX -> JSON para el visor
├── vector_search.py   # $vectorSearch + $rerank
├── memory.py          # Agent Engine Memory
├── chat.py            # memoria + vector + grafo + LLM
├── flow_store.py      # flujo de cada petición e historial
└── static/            # UI (index.html, app.js, graph.js, style.css)
tests/                 # pytest sin red
```

## Notas
- **Seguridad:** ninguna credencial está en el código; todo vive en `.env` (ignorado por git) y solo se versiona `.env.example`. Las API keys introducidas en la UI viven solo en la memoria del proceso.
- **Memoria persistente:** el navegador guarda un `thread_id` en `localStorage`, que se usa como `session_id` en Agent Engine Memory.

## Limitaciones (a propósito)
Sin MCP ni Databricks, sin autenticación/roles, sin actualización automática de repos, AST solo para Python (otros lenguajes: endpoints por regex), ingesta síncrona, sin streaming de tokens.

## Pruebas
`pytest -q` (sin red). Checklist manual:
1. Arrancar → pestaña Configuración → Estado muestra índices.
2. `auto_embed` con chunk 600/100 sobre `PDFs/FAQS.pdf` → más chunks que con 1000/200; en `chunks_auto` no hay campo `embedding`.
3. Cambiar modelo autoEmbed → aparece un índice `idx_auto_<modelo>` (BUILDING → READY).
4. `voyage_context` → sliders deshabilitados; subir un `.md`.
5. Seleccionar la carpeta `PDFs/` → se indexan los 4 PDFs.
6. Analizar 2 repos relacionados → nodos Repository/Library/Endpoint/Function y `DEPENDS_ON` entre ellos.
7. Preguntar en modo `vector`, `graph` e `hybrid` y comparar el panel de flujo; clic en un nodo del grafo lo expande.
8. Reiniciar → los ajustes persisten; las API keys de la UI no.
