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

## Requisitos
- Python 3.11+
- Cluster Atlas con Vector Search y Automated Embedding; `$rerank` requiere MongoDB 9.0+ y M10+ con Native Reranking (si no, `RERANK_ENABLED = False` en `app/config.py`)
- Claves: LLM compatible OpenAI, Voyage AI, `MONGODB_URI`; opcional `GITHUB_TOKEN` (60 → 5000 peticiones/h) y Agent Engine Memory

## Ejecución
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # rellena credenciales
uvicorn app.main:app --reload
```
Abre http://127.0.0.1:8000. Los índices se crean en código al arrancar (logs `[setup]`).

Preguntas de ejemplo: "¿Qué librerías y versiones usa owner/repo?", "¿Qué repos usan MongoDB?", "¿Qué endpoints expone X?", "¿Qué se ve afectado si cambia Y?".

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
