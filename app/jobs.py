# ============================================================
#  jobs.py
#  Ingestas en SEGUNDO PLANO. La peticion HTTP solo crea el trabajo y
#  devuelve un job_id al instante; el navegador consulta GET /jobs/{id}
#  para ver el progreso. Asi una ingesta larga (LLM, muchos ficheros) ya
#  no depende de una conexion abierta: no hay "Failed to fetch".
#  Limite didactico: los trabajos viven en memoria del proceso; si el
#  servidor se reinicia, se pierden (lo ya escrito en MongoDB se conserva).
# ============================================================

from __future__ import annotations

import threading
import time
import traceback
import uuid

import github_ingest
import ingest

_jobs: dict[str, dict] = {}
_lock = threading.Lock()
MAX_LOG = 300


def _stamp() -> str:
    return time.strftime("%H:%M:%S")


def _append(jid: str, msg: str) -> None:
    with _lock:
        lg = _jobs[jid]["log"]
        lg.append(f"{_stamp()}  {msg}")
        del lg[:-MAX_LOG]


def start(kind: str, fn, *args) -> str:
    """Lanza fn(*args, log=...) en un hilo y devuelve su id de trabajo."""
    jid = uuid.uuid4().hex[:12]
    with _lock:
        _jobs[jid] = {"id": jid, "kind": kind, "status": "running", "log": [],
                      "result": None, "error": None, "started": _stamp()}
    _append(jid, "Trabajo iniciado")

    def run():
        try:
            result = fn(*args, log=lambda m: _append(jid, m))
            with _lock:
                _jobs[jid].update(status="done", result=result)
            _append(jid, "Terminado")
        except Exception as exc:  # cualquier fallo queda registrado, no se pierde en la consola
            traceback.print_exc()
            with _lock:
                _jobs[jid].update(status="error", error=str(exc))
            _append(jid, f"ERROR: {exc}")

    threading.Thread(target=run, daemon=True, name=f"job-{jid}").start()
    return jid


def get(jid: str) -> dict | None:
    with _lock:
        j = _jobs.get(jid)
        return {**j, "log": list(j["log"])} if j else None


# ---- Trabajos concretos ----
def run_files(items: list[tuple[str, bytes]], user_id: str, visibility: str, log=None) -> dict:
    log = log or (lambda m: None)
    results, errors = [], []
    for i, (name, data) in enumerate(items, 1):
        log(f"Fichero {i}/{len(items)}: {name}")
        try:
            r = ingest.ingest_file(name, data, user_id, visibility, log=log)
            results.append(r)
            log(f"  ✓ {r['chunks']} chunks · {r['entities']} entidades" + (f" · avisos: {len(r['warnings'])}" if r["warnings"] else ""))
        except Exception as exc:
            errors.append({"file": name, "error": str(exc)})
            log(f"  ✗ {exc}")
    return {"results": results, "skipped": [], "errors": errors}


def run_github(urls: list[str], user_id: str, visibility: str, log=None) -> dict:
    log = log or (lambda m: None)
    results, errors = [], []
    for i, url in enumerate(urls, 1):
        log(f"Repo {i}/{len(urls)}: {url}")
        try:
            r = github_ingest.ingest_repo(url, user_id, visibility, log=log)
            results.append(r)
        except Exception as exc:
            errors.append({"file": url, "error": str(exc)})
            log(f"  ✗ {exc}")
    return {"results": results, "skipped": [], "errors": errors}
