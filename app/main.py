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

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import json
import traceback

import chat
import embeddings
import flow_store
import memory
import pdf_processor
import setup_indexes
import vector_search


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Al arrancar, aseguramos que existan los indices de Atlas Vector Search.
    setup_indexes.ensure_indexes()
    yield


app = FastAPI(title="PDF Chat + Memoria (RAG)", lifespan=lifespan)

# Sirve los archivos estaticos (HTML/CSS/JS) en /static.
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Ruta raiz: devuelve la pagina web.
@app.get("/")
def index():
    return FileResponse("app/static/index.html")


# Ruta de configuracion: le dice a la UI que funciones estan disponibles.
@app.get("/config")
def config_endpoint():
    return {"memory_available": memory.is_configured()}


# Esquema de la peticion del chat.
class ChatRequest(BaseModel):
    message: str
    thread_id: str = "default-thread"
    user_id: str = "demo-user"
    # Si la UI tiene la memoria desactivada, se envia use_memory=false.
    use_memory: bool = True


@app.get("/documents")
def list_documents(user_id: str = "demo-user"):
    """PDFs publicos + privados del usuario indicado."""
    return vector_search.list_documents(user_id)


@app.post("/upload")
async def upload_pdf(
    file: UploadFile = File(...),
    user_id: str = Form("demo-user"),
    visibility: str = Form("public"),  # "public" o "private"
):
    """Recibe un PDF, detecta si tiene imagenes y lo indexa.

    El procesamiento es sincrono por simplicidad (educacional).
    """
    if visibility not in ("public", "private"):
        raise HTTPException(400, "visibility debe ser public o private.")
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Solo se admiten archivos PDF.")

    # Leemos el contenido binario del PDF.
    pdf_bytes = await file.read()
    if not pdf_bytes:
        raise HTTPException(400, "El archivo esta vacio.")

    try:
        resultado = pdf_processor.process_pdf(pdf_bytes)
    except Exception as exc:
        raise HTTPException(400, f"No se pudo leer el PDF: {exc}")

    # Indexamos segun si tiene imagenes o no.
    if resultado["has_images"]:
        n = embeddings.index_multimodal_documents(
            resultado["multimodal_chunks"], file.filename, user_id, visibility
        )
        modelo = "voyage-multimodal"
    else:
        n = embeddings.index_text_document(
            resultado["text_chunks"], file.filename, user_id, visibility
        )
        modelo = "voyage-context-4"

    return {
        "message": f"PDF '{file.filename}' indexado correctamente.",
        "chunks": n,
        "mode": modelo,
        "has_images": resultado["has_images"],
    }


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


# ---- Ajustes del LLM desde la UI (solo en memoria del proceso) ----
class LLMConfig(BaseModel):
    base_url: str = ""
    api_key: str = ""
    model: str = ""


@app.get("/llm-config")
def get_llm_config():
    """Valores en uso. La API key NUNCA se devuelve, solo si existe."""
    cfg = chat.llm_settings()
    return {"base_url": cfg["base_url"], "model": cfg["model"], "has_key": bool(cfg["api_key"])}


@app.post("/llm-config")
def set_llm_config(cfg: LLMConfig):
    """Guarda los valores SOLO en memoria (se pierden al parar el servidor).
    Los campos vacios vuelven al valor del .env."""
    chat.set_llm_override(cfg.base_url, cfg.api_key, cfg.model)
    return get_llm_config()
