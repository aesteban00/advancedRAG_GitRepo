# ============================================================
#  removal.py
#  Borrado de documentos (ficheros) y repos de GitHub. Lo que se elimina:
#    * sus chunks en las 3 colecciones (con autoEmbed, Atlas retira solo los vectores)
#    * lo que solo ellos aportaron al grafo (ver graph_store.remove_source)
#  Solo puede borrar el PROPIETARIO; el ADMINISTRADOR (contrasena en el servidor) tambien lo PUBLICO de cualquiera.
#  No se puede deshacer: para recuperarlo hay que volver a ingerirlo.
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


def _chunk_scope(user_id: str, is_admin: bool) -> dict:
    """Que chunks puede borrar quien llama: los suyos; y el admin, ademas, los PUBLICOS de cualquiera
    (nunca los privados de otros)."""
    own = {"metadata.owner": user_id}
    return {"$or": [own, {"metadata.visibility": "public"}]} if is_admin else own


def delete_file(source: str, user_id: str, is_admin: bool = False) -> dict:
    # Los chunks de README/docs de un repo (source_type github) se borran con su repo, no sueltos.
    base = {"metadata.source": source, "metadata.source_type": {"$ne": "github"}}
    chunks = _delete_chunks({**base, **_chunk_scope(user_id, is_admin)})
    if chunks == 0:
        raise ValueError("No encontrado, o sin permiso (solo su propietario; el administrador, solo lo publico).")
    # Si otro usuario conserva un fichero con el mismo nombre, el grafo sigue necesitando esa fuente.
    if any(db.coll(n).count_documents(base, limit=1) for n in CHUNK_COLLECTIONS):
        return {"chunks_deleted": chunks, "entities_updated": 0, "entities_deleted": 0, "edges_removed": 0, "graph_kept": True}
    return {"chunks_deleted": chunks, **graph_store.remove_source(file_pattern(source))}


def delete_repo(rid: str, user_id: str, is_admin: bool = False) -> dict:
    if rid.count("/") != 1:
        raise ValueError("Identificador de repo no valido (owner/repo).")
    repo = db.coll(config.COLL_GRAPH).find_one({"_id": rid, "type": "Repository"}, {"attributes": 1})
    if not repo:
        raise ValueError("Repo no encontrado.")
    attrs = repo.get("attributes", {})
    owners, vis = attrs.get("owner_user") or [], attrs.get("visibility") or []
    is_public = bool(vis) and all(v == "public" for v in vis)   # si consta tambien como privado, no es publico
    if owners and user_id not in owners and not (is_admin and is_public):
        raise ValueError("Solo se pueden eliminar repos publicos." if is_admin else "Solo su propietario puede eliminarlo.")
    chunks = _delete_chunks({"metadata.source": {"$regex": f"^{re.escape(rid)}/"}, "metadata.source_type": "github"})
    return {"chunks_deleted": chunks, **graph_store.remove_source(repo_pattern(rid))}


def delete_items(items: list[dict], user_id: str, is_admin: bool = False) -> list[dict]:
    """items: [{"kind": "file"|"repo", "source": "..."}]. Un fallo en uno no detiene a los demas."""
    out = []
    for it in items:
        kind, source = it.get("kind"), (it.get("source") or "").strip()
        try:
            if not source or kind not in ("file", "repo"):
                raise ValueError("Elemento no valido.")
            res = (delete_repo if kind == "repo" else delete_file)(source, user_id, is_admin)
            out.append({"kind": kind, "source": source, **res})
        except Exception as exc:
            out.append({"kind": kind, "source": source, "error": str(exc)})
    return out
