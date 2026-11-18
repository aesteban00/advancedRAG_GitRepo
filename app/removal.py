# ============================================================
#  removal.py
#  Borrado de documentos (ficheros) y repos de GitHub. Lo que se elimina:
#    * sus chunks en las 3 colecciones (con autoEmbed, Atlas retira solo los vectores)
#    * lo que solo ellos aportaron al grafo (ver graph_store.remove_source)
#  Solo puede borrar el PROPIETARIO. No se puede deshacer: para recuperarlo hay que volver a ingerirlo.
# ============================================================

from __future__ import annotations

import re

import config
import db
import graph_store

CHUNK_COLLECTIONS = (config.COLL_AUTO, config.COLL_CONTEXT, config.COLL_MULTIMODAL)


def file_pattern(source: str) -> str:
    """Fuente de grafo de un fichero: `file:<nombre>` (coincidencia exacta)."""
    return f"^file:{re.escape(source)}$"


def repo_pattern(rid: str) -> str:
    """Fuentes de grafo de un repo: `github:owner/repo` y `github:owner/repo/<ruta>` (pero no `owner/repo-otro`)."""
    return f"^github:{re.escape(rid)}(/|$)"


def _delete_chunks(query: dict) -> int:
    return sum(db.coll(n).delete_many(query).deleted_count for n in CHUNK_COLLECTIONS)


def delete_file(source: str, user_id: str) -> dict:
    # Los chunks de README/docs de un repo (source_type github) se borran con su repo, no sueltos.
    chunks = _delete_chunks({"metadata.source": source, "metadata.owner": user_id,
                             "metadata.source_type": {"$ne": "github"}})
    if chunks == 0:
        raise ValueError("No encontrado, o solo su propietario puede eliminarlo.")
    return {"chunks_deleted": chunks, **graph_store.remove_source(file_pattern(source))}


def delete_repo(rid: str, user_id: str) -> dict:
    if rid.count("/") != 1:
        raise ValueError("Identificador de repo no valido (owner/repo).")
    repo = db.coll(config.COLL_GRAPH).find_one({"_id": rid, "type": "Repository"}, {"attributes": 1})
    if not repo:
        raise ValueError("Repo no encontrado.")
    owners = repo.get("attributes", {}).get("owner_user") or []
    if owners and user_id not in owners:
        raise ValueError("Solo su propietario puede eliminarlo.")
    chunks = _delete_chunks({"metadata.source": {"$regex": f"^{re.escape(rid)}/"}, "metadata.source_type": "github"})
    return {"chunks_deleted": chunks, **graph_store.remove_source(repo_pattern(rid))}


def delete_items(items: list[dict], user_id: str) -> list[dict]:
    """items: [{"kind": "file"|"repo", "source": "..."}]. Un fallo en uno no detiene a los demas."""
    out = []
    for it in items:
        kind, source = it.get("kind"), (it.get("source") or "").strip()
        try:
            if not source or kind not in ("file", "repo"):
                raise ValueError("Elemento no valido.")
            res = (delete_repo if kind == "repo" else delete_file)(source, user_id)
            out.append({"kind": kind, "source": source, **res})
        except Exception as exc:
            out.append({"kind": kind, "source": source, "error": str(exc)})
    return out
