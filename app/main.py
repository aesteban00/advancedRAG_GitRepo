# ============================================================
#  main.py
#  ------------------------------------------------------------------
#  Aplicacion FastAPI. Es el "punto de entrada" del servidor local.
#  Se lanza con:  uvicorn app.main:app --reload
#
#  Rutas:
#    GET  /            -> sirve la interfaz web (static/index.html)
#    POST /upload      -> recibe un PDF, lo procesa y lo indexa
#    POST /chat        -> recibe {message, thread_id} y responde
# ============================================================

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import Body, FastAPI, Header, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import json
import traceback

import chat
import config
import flow_store
import hmac
import time
from datetime import datetime, timezone

import db
import jobs
import removal
import github_ingest
import graph_store
import graph_view
import ingest
import loaders
import memory
import settings
import setup_indexes
import vector_search


def _http_error(exc: Exception) -> HTTPException:
    """ValueError -> 400 (entrada invalida); el resto -> 500."""
    return HTTPException(400 if isinstance(exc, ValueError) else 500, str(exc))


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Al arrancar, aseguramos que existan los indices de Atlas Vector Search.
    try:
        setup_indexes.ensure_indexes()
    except Exception as exc:  # la app debe arrancar aunque Atlas falle
        print(f"[setup] ERROR creando indices: {exc}")
    yield


app = FastAPI(title="GraphRAG sobre documentos y repos (MongoDB Atlas)", lifespan=lifespan)

# Sirve los archivos estaticos (HTML/CSS/JS) en /static.
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Ruta raiz: devuelve la pagina web.
@app.get("/")
def index():
    return FileResponse("app/static/index.html")


# Ruta de configuracion: le dice a la UI que funciones estan disponibles.
def _actor(user_id: str, token: str | None) -> bool:
    """Devuelve si quien llama actua como administrador. El nombre "admin" esta RESERVADO: sin la
    contrasena correcta (cabecera X-Admin-Token) se rechaza, para que nadie se haga pasar por el."""
    if user_id != config.ADMIN_USER:
        return False
    if not config.ADMIN_TOKEN:
        raise HTTPException(403, "El modo administrador esta desactivado (falta ADMIN_TOKEN en el .env).")
    if not token or not hmac.compare_digest(token, config.ADMIN_TOKEN):
        time.sleep(0.5)   # frena los intentos por fuerza bruta
        raise HTTPException(403, "Contrasena de administrador incorrecta.")
    return True


class AdminLogin(BaseModel):
    token: str


@app.post("/admin/login")
def admin_login(req: AdminLogin):
    """Comprueba la contrasena de administrador (sin efectos). La UI la guarda solo en la sesion del navegador."""
    _actor(config.ADMIN_USER, req.token)
    return {"ok": True}


@app.get("/config")
def config_endpoint():
    return {"memory_available": memory.is_configured(), "admin_enabled": bool(config.ADMIN_TOKEN),
            "admin_user": config.ADMIN_USER}


# Esquema de la peticion del chat.
class ChatRequest(BaseModel):
    message: str
    thread_id: str = "default-thread"
    user_id: str = "demo-user"
    # Si la UI tiene la memoria desactivada, se envia use_memory=false.
    use_memory: bool = True


@app.get("/users")
def users():
    """Usuarios conocidos (con datos) para el selector de la interfaz."""
    try:
        return vector_search.list_users()
    except Exception as exc:
        raise _http_error(exc)


@app.get("/explain")
def explain_catalog(user_id: str = "demo-user", question: str = ""):
    """Catalogo dinamico para la pestaña Explicacion: pasos de ingesta y consulta con su llamada real a MongoDB."""
    try:
        import explain
        return explain.catalog(user_id, question)
    except Exception as exc:
        raise _http_error(exc)


@app.get("/documents")
def list_documents(user_id: str = "demo-user"):
    """PDFs publicos + privados del usuario indicado."""
    return vector_search.list_documents(user_id)


def _check_visibility(v: str) -> None:
    if v not in ("public", "private"):
        raise HTTPException(400, "visibility debe ser public o private.")


@app.post("/ingest/files")
async def ingest_files(files: list[UploadFile] = File(...), user_id: str = Form("demo-user"),
                       visibility: str = Form("public"), x_admin_token: str | None = Header(None)):
    """Crea un trabajo en segundo plano y devuelve su job_id (progreso en GET /jobs/{id})."""
    _actor(user_id, x_admin_token)
    _check_visibility(visibility)
    if len(files) > 50:
        raise HTTPException(400, "Maximo 50 ficheros por peticion.")
    items, skipped = [], []
    for f in files:
        name = f.filename or ""
        if not name.lower().endswith(loaders.SUPPORTED_EXTENSIONS):
            if len(files) == 1:
                raise HTTPException(400, "Formato no soportado (usa .pdf, .md o .txt).")
            skipped.append(name)
            continue
        items.append((name, await f.read()))
    jid = jobs.start("files", jobs.run_files, items, user_id, visibility)
    return {"job_id": jid, "skipped": skipped}


class GithubRequest(BaseModel):
    urls: list[str]
    user_id: str = "demo-user"
    visibility: str = "public"


@app.post("/ingest/github")
def ingest_github(req: GithubRequest, x_admin_token: str | None = Header(None)):
    _actor(req.user_id, x_admin_token)
    _check_visibility(req.visibility)
    if not req.urls or len(req.urls) > 10:
        raise HTTPException(400, "Indica entre 1 y 10 URLs.")
    for url in req.urls:  # valida el formato antes de lanzar nada
        try:
            github_ingest.parse_repo_url(url)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
    jid = jobs.start("github", jobs.run_github, req.urls, req.user_id, req.visibility)
    return {"job_id": jid, "skipped": []}


class DeleteItem(BaseModel):
    kind: str          # "file" | "repo"
    source: str


class DeleteRequest(BaseModel):
    items: list[DeleteItem]
    user_id: str = "demo-user"


@app.post("/documents/delete")
def delete_documents(req: DeleteRequest, x_admin_token: str | None = Header(None)):
    """Elimina ficheros y repos (chunks + lo que solo ellos aportaron al grafo). Solo el propietario;
    el administrador (X-Admin-Token) tambien lo PUBLICO de cualquier usuario."""
    is_admin = _actor(req.user_id, x_admin_token)
    if not 1 <= len(req.items) <= 100:
        raise HTTPException(400, "Indica entre 1 y 100 elementos.")
    results = removal.delete_items([i.model_dump() for i in req.items], req.user_id, is_admin)
    try:  # auditoria en MongoDB: quien elimino que y cuando
        db.coll(config.COLL_AUDIT).insert_one({"at": datetime.now(timezone.utc), "actor": req.user_id, "admin": is_admin,
                                               "results": results})
    except Exception as exc:  # la auditoria no debe romper el borrado
        print(f"[aviso] no se pudo registrar la auditoria: {exc}")
    return {"results": results}


@app.get("/jobs/{job_id}")
def get_job(job_id: str):
    j = jobs.get(job_id)
    if not j:
        raise HTTPException(404, "Trabajo no encontrado (quiza el servidor se reinicio).")
    return j


def _settings_response() -> dict:
    return {**settings.public_view(), "options": {
        "strategies": config.STRATEGIES, "embedding_models": config.EMBEDDING_MODELS,
        "chunk_size_range": config.CHUNK_SIZE_RANGE,
        "fixed_chunk": [config.FIXED_CHUNK_SIZE, config.FIXED_CHUNK_OVERLAP]}}


@app.get("/settings")
def get_settings():
    return _settings_response()


@app.post("/settings")
def post_settings(patch: dict = Body(...)):
    """Guarda ajustes. llm_keys (API keys) solo se guardan en memoria del proceso."""
    keys = patch.pop("llm_keys", None) or {}
    before = settings.get()
    try:
        for role, k in keys.items():
            settings.set_api_key(role, k)
        new = settings.update(patch) if patch else before
        if new["embedding"]["auto_embed"] != before["embedding"]["auto_embed"]:
            setup_indexes.ensure_auto_index(new["embedding"]["auto_embed"])
    except Exception as exc:
        raise _http_error(exc)
    if "llm" in patch or keys:
        graph_store.reset_store()
    return _settings_response()


@app.get("/status")
def status():
    out: dict = {"indexes": [], "counts": {}}
    try:
        out["indexes"] = setup_indexes.index_status()
        out["counts"] = {**vector_search.counts(), "entities": graph_store.count()}
    except Exception as exc:
        out["error"] = str(exc)
    return out


@app.get("/graph")
def graph(entity: str = "", depth: int = 2, type: str = ""):
    """Sin entity: resumen (entidades mas conectadas, o de un tipo). depth=0: solo vecinos directos."""
    try:
        if entity:
            ents = graph_store.direct_neighbors(entity) if depth <= 0 else graph_store.neighborhood(entity, depth)
            return graph_view.subgraph_layout(ents, [entity])
        return graph_view.subgraph_layout(graph_store.overview(type or None))
    except Exception as exc:
        raise _http_error(exc)


@app.get("/graph/search")
def graph_search(q: str = ""):
    try:
        return graph_store.search(q)
    except Exception as exc:
        raise _http_error(exc)


@app.get("/graph/entity")
def graph_entity(id: str):
    try:
        return graph_store.entity_detail(id)
    except Exception as exc:
        raise _http_error(exc)


@app.get("/graph/path")
def graph_path(source: str, target: str):
    """Camino entre dos entidades, calculado con $graphLookup."""
    try:
        res = graph_store.find_path(source, target)
        if not res["path"]:
            return {"found": False, "path": [], "graph": {"nodes": [], "edges": []}}
        g = graph_view.subgraph_layout(graph_store.path_entities(res["path"]), res["path"], max_nodes=len(res["path"]) + 1)
        return {"found": True, **res, "graph": g}
    except Exception as exc:
        raise _http_error(exc)


@app.post("/chat")
def chat_endpoint(req: ChatRequest):
    """Recibe una pregunta y devuelve la respuesta del asistente."""
    try:
        respuesta, memory = chat.answer(req.message, req.thread_id, use_memory=req.use_memory, user_id=req.user_id)
    except Exception as exc:
        traceback.print_exc()  # muestra el error completo en la consola
        raise HTTPException(500, f"Error generando la respuesta: {exc}")
    return {"reply": respuesta, "memory": memory}


@app.post("/chat/stream")
def chat_stream(req: ChatRequest):
    """Igual que /chat pero emite el flujo paso a paso (NDJSON, una linea por evento).

    Al terminar guarda el flujo en la coleccion aparte (flow_store) y envia
    su id en el evento final, para poder consultarlo despues.
    """
    def events():
        steps: dict[str, dict] = {}  # ultimo estado de cada paso
        try:
            for ev in chat.answer_stream(req.message, req.thread_id, req.use_memory, req.user_id):
                if ev["type"] == "step":
                    steps[ev["id"]] = ev
                elif ev["type"] == "result":
                    try:
                        ev["flow_id"] = flow_store.save_flow(
                            req.user_id, req.thread_id, req.message, list(steps.values()), ev
                        )
                    except Exception as exc:  # guardar el flujo no debe romper el chat
                        print(f"[aviso] No se pudo guardar el flujo: {exc}")
                yield json.dumps(ev, ensure_ascii=False) + "\n"
        except Exception as exc:
            traceback.print_exc()
            yield json.dumps({"type": "error", "message": str(exc)}, ensure_ascii=False) + "\n"

    return StreamingResponse(events(), media_type="application/x-ndjson")


@app.get("/flows/{flow_id}")
def get_flow(flow_id: str, user_id: str = "demo-user"):
    """Devuelve el flujo guardado de una pregunta (solo para su usuario)."""
    flow = flow_store.get_flow(flow_id, user_id)
    if not flow:
        raise HTTPException(404, "Flujo no encontrado.")
    return flow


@app.get("/threads")
def list_threads(user_id: str = "demo-user"):
    """Sesiones (hilos) del usuario para el historial del panel izquierdo."""
    return flow_store.list_threads(user_id)


@app.get("/threads/{thread_id}")
def get_thread(thread_id: str, user_id: str = "demo-user"):
    """Mensajes de una sesion (pregunta, respuesta y su flujo)."""
    return flow_store.get_thread(user_id, thread_id)
