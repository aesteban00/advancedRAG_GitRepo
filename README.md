# GraphRAG sobre documentos y repos de GitHub con MongoDB Atlas

Proyecto **educacional**: sube documentos o apunta a repositorios de GitHub y pregúntales en un chat. Todo vive en **una sola base de datos, MongoDB Atlas**.

---

# Parte 1 · Qué es y cómo funciona

## La idea en 30 segundos
Un RAG normal busca fragmentos de texto parecidos a tu pregunta. **GraphRAG** añade un segundo camino: un **grafo** de entidades (repositorios, librerías, endpoints, bases de datos, personas…) y de sus relaciones. Así puede responder cosas como *"¿qué repos usan MongoDB?"* o *"¿qué se ve afectado si cambia esta librería?"*, que la búsqueda por texto no resuelve bien.

```
Documentos / carpeta ─► troceado ─► vectores ─┐
Repos de GitHub ─► grafo (librerías, endpoints, código) ─┼─► MongoDB Atlas ─► Chat con fuentes + grafo
                                              (vectores + grafo + memoria + ajustes en el mismo cluster)
```

## Por qué MongoDB (el mensaje de la demo)
| Ventaja | Dónde se ve |
|---|---|
| **Una sola plataforma**: chunks, vectores, grafo, memoria y ajustes en el mismo cluster | BD `graphrag_demo` |
| **Grafo nativo**: un documento por entidad y recorrido con `$graphLookup` dentro de la BD, sin base de grafos aparte | `app/graph_store.py` |
| **Automated Embedding (`autoEmbed`)**: Atlas genera y sincroniza los vectores; la app solo guarda texto | estrategia `auto_embed` |
| **Voyage AI y `$rerank` integrados** | estrategias manuales y búsqueda |
| **Esquema flexible**: repos, librerías, endpoints, funciones… en la misma colección | `knowledge_graph` |

## Qué puedes elegir (pestaña Configuración)
| Estrategia | Quién genera los vectores | Chunking |
|---|---|---|
| `auto_embed` | Atlas (`autoEmbed`) | **tú eliges tamaño y solape** |
| `voyage_context` | la app con `voyage-context-4` | fijo |
| `voyage_multimodal` | la app con `voyage-multimodal-3.5` (texto + imagen) | una página = un chunk |

Además: un modelo de **embedding**, un **LLM para construir el grafo** y otro **para el chat** (por defecto, el mismo), tres modos de recuperación (`hybrid`, `vector`, `graph`) y tres fuentes: ficheros, carpeta o URLs de GitHub.

## Qué verás en pantalla
- **Chat**: la respuesta cita sus fuentes y el panel derecho muestra el flujo (memoria, `$vectorSearch`, grafo, LLM, tokens).
- **Grafo**: visor navegable (NetworkX calcula el layout; se dibuja en SVG). Zoom y arrastre; **filtros** por tipo de nodo y de relación (el código —ficheros, clases, funciones— va oculto por defecto); **clic** = ficha de la entidad (atributos, fuentes, relaciones salientes y entrantes clicables); **doble clic** = expandir o colapsar su vecindario sin perder lo que ya ves; búsqueda con autocompletado y **camino más corto entre dos entidades** (`$graphLookup`), sin distinguir si vienen de repos o de documentos.
- **Configuración**: modelos, ingesta, recuperación, fuentes y estado de los índices de Atlas.

## De un repo de GitHub se extrae (sin LLM)
Descripción, librerías y versiones, bases de datos y servicios, endpoints, propietario (CODEOWNERS), clases/funciones Python con sus llamadas y relaciones entre repos. El README y `docs/*.md` pasan por la ingesta normal.

## Limitaciones a propósito
Sin MCP, sin autenticación/roles, sin actualización automática de repos, AST solo para Python, ingesta síncrona.

---

# Parte 2 · Puesta en marcha

## Requisitos
- Python 3.11+
- Cluster **MongoDB Atlas** con Vector Search y Automated Embedding (M10+ recomendado)
- API key de **Voyage AI** y de un **LLM compatible con la API de OpenAI**
- Opcional: `GITHUB_TOKEN` (más peticiones a la API de GitHub) y la CLI `agentengine` (memoria)
- `$rerank` necesita MongoDB 9.0+ y M10+; si tu cluster no lo cumple, pon `RERANK_ENABLED = False` en `app/config.py`

## 1. Instalar
```bash
git clone <repo-url> && cd advancedRAG_GitRepo
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env     # y rellénalo (ver tabla)
```

## 2. (Opcional) Crear la memoria en Agent Engine
La memoria permite que el chat recuerde conversaciones anteriores. Sin ella todo lo demás funciona.
```bash
agentengine auth login                  # abre el navegador
./scripts/setup_agent_engine.sh         # crea contexto, agente y secrets desde tu .env y lo despliega
```
Al terminar, crea el service account (el secret se muestra una sola vez) y copia sus valores al `.env`:
```bash
agentengine service-account create memory-service --context graphrag --role PROJECT_OWNER
```
El script crea la carpeta `agent-engine/` (local, ignorada por git) y le copia el `project-config.yaml` de la raíz, rellenando el LLM de extracción con tu `.env`. Ese fichero define la configuración de la memoria (modelo de embeddings, LLM de extracción, cuándo y qué extraer) y trae alternativas comentadas: edítalo antes de ejecutar el script. `DRY_RUN=1 ./scripts/setup_agent_engine.sh` solo muestra los pasos sin ejecutarlos. Si el context `graphrag` ya existe con otra organización o proyecto, el script lo advierte y, con solo contestar `y`, borra el context local y la carpeta `agent-engine/` y los recrea con los valores de tu `.env` (no se toca nada en Agent Engine). Si falla con `session expired`, repite `agentengine auth login`. **LLM de extracción (`MEMORY_LLM_*`, separado del de chat `CHAT_LLM_*`):** debe ser alcanzable desde Agent Engine (corre en AWS). `ai-gateway.corp.mongodb.com` no lo es (restricción de red conocida; el script lo detecta y aborta). Usa el gateway Grove público (`https://grove-gateway-prod.azure-api.net/grove-foundry-prod/openai/v1`, `MEMORY_LLM_AUTH_HEADER=api-key`, clave Grove nueva) o la API pública de un proveedor (`https://api.openai.com/v1`, `authorization`). Crear un workspace exige una organización de Agent Engine **Atlas-backed**.

## 3. Arrancar
```bash
uvicorn app.main:app --reload --port 8090
```
Abre http://localhost:8090. Al arrancar se crean **en código** colecciones e índices (logs `[setup]`).

## 4. Probar
1. **Configuración** → elige estrategia y modelos → *Guardar configuración*.
2. **Fuentes** → sube un `.pdf/.md/.txt`, una carpeta (p. ej. `PDFs/`) o pega URLs de GitHub.
3. **Chat** → pregunta, p. ej. *"¿Qué librerías usa owner/repo?"*, *"¿Qué repos usan MongoDB?"*, *"¿Qué se ve afectado si cambia X?"*. Cambia el modo (`vector`, `graph`, `hybrid`) y compara el panel de flujo.
4. **Grafo** → explora las relaciones con zoom.

## Variables del `.env`
| Variable | Para qué sirve |
|---|---|
| `CHAT_LLM_API_KEY` / `CHAT_LLM_BASE_URL` / `CHAT_LLM_MODEL` | Modelo de chat por defecto (cualquier proveedor compatible con OpenAI). Editable en la pestaña Configuración |
| `VOYAGE_API_KEY` | Embeddings de las estrategias manuales y de la memoria |
| `MONGODB_URI` | Conexión a Atlas (la app y la memoria usan el mismo cluster) |
| `GITHUB_TOKEN` | (Opcional) sube el límite de GitHub de 60 a 5000 peticiones/h |
| `AGENTIC_MEMORY_PROJECT_ID` | Proyecto de Agent Engine donde vive la memoria |
| `AGENTIC_MEMORY_CLIENT_ID` / `AGENTIC_MEMORY_CLIENT_SECRET` | Service account que la app usa para hablar con la memoria |
| `MEMORY_LLM_BASE_URL` / `MEMORY_LLM_MODEL` / `MEMORY_LLM_AUTH_HEADER` / `MEMORY_LLM_API_KEY` | Solo para el script: **LLM de extracción de la memoria**, independiente del modelo de chat. Debe ser alcanzable desde Agent Engine (ver arriba). La clave se sube como secret `LLM_API_KEY` |
| `MONGODB_DATABASE` | Solo para el script: base de datos de la memoria (`graphrag_demo`) |
| `AGENTENGINE_ORG_ID` | Solo para el script, **obligatorio**: id de tu organización de Agent Engine. Con `AGENTIC_MEMORY_PROJECT_ID` fija dónde se despliega; el script aborta si el context existente apunta a otra org/proyecto |
| `AGENTENGINE_CONTEXT` | Solo para el script: nombre del context de la CLI (por defecto `graphrag`) |

## Estructura
```
app/       main, config, settings, db, setup_indexes, loaders, embeddings, ingest,
           github_ingest, graph_store, graph_view, vector_search, memory, chat, flow_store, static/
project-config.yaml        # configuración de la memoria (con alternativas comentadas)
scripts/   setup_agent_engine.sh   # memoria en Agent Engine desde el .env
tests/     pytest sin red
```

## Pruebas
`pytest -q` (sin red). Comprobación manual: ingerir `PDFs/FAQS.pdf` con `auto_embed` a 600/100 y ver que genera más chunks que a 1000/200 (en `chunks_auto` no hay campo `embedding`); analizar 2 repos relacionados y ver la relación `DEPENDS_ON` en la pestaña Grafo.

> **Seguridad:** ninguna credencial está en el código; todo va en `.env` (ignorado por git). Las API keys escritas en la UI viven solo en la memoria del servidor.
