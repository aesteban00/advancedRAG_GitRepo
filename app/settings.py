# ============================================================
#  settings.py
#  Ajustes editables desde la pestana Configuracion.
#   * Se guardan en MongoDB (coleccion app_settings): otra ventaja de
#     tener todo en el mismo cluster. NUNCA incluyen secretos.
#   * Las API keys introducidas en la UI viven SOLO en memoria.
# ============================================================

from __future__ import annotations

import copy

import config
import db

DEFAULTS = {
    "ingest": {"strategy": "auto_embed", "chunk_size": 1000, "chunk_overlap": 200, "build_graph": True},
    "embedding": {"auto_embed": "voyage-4", "voyage_context": "voyage-context-4",
                  "voyage_multimodal": "voyage-multimodal-3.5"},
    "llm": {"same_for_all": True,
            "graph": {"base_url": "", "model": ""},
            "chat": {"base_url": "", "model": ""}},
    "retrieval": {"mode": "hybrid", "top_k": 4, "graph_depth": 2},
}
_keys = {"graph": "", "chat": ""}  # API keys SOLO en memoria


def _deep_merge(a: dict, b: dict) -> dict:
    """Mezcla recursiva sin mutar las entradas."""
    out = copy.deepcopy(a)
    for k, v in b.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def _has_api_key(d) -> bool:
    if isinstance(d, dict):
        return any(k == "api_key" or _has_api_key(v) for k, v in d.items())
    return False


def _validate(cfg: dict) -> None:
    ing, emb, ret = cfg["ingest"], cfg["embedding"], cfg["retrieval"]
    if ing["strategy"] not in config.STRATEGIES:
        raise ValueError(f"Estrategia no valida: {ing['strategy']}")
    lo, hi = config.CHUNK_SIZE_RANGE
    if not lo <= ing["chunk_size"] <= hi:
        raise ValueError(f"chunk_size debe estar entre {lo} y {hi}")
    if not 0 <= ing["chunk_overlap"] < ing["chunk_size"] // 2:
        raise ValueError("chunk_overlap debe ser >= 0 y menor que la mitad del tamano de chunk")
    for s, models in config.EMBEDDING_MODELS.items():
        if emb.get(s) not in models:
            raise ValueError(f"Modelo no permitido para {s}: {emb.get(s)}")
    if ret["mode"] not in ("hybrid", "vector", "graph"):
        raise ValueError("retrieval.mode debe ser hybrid, vector o graph")
    if not 1 <= ret["top_k"] <= 20:
        raise ValueError("top_k debe estar entre 1 y 20")
    if not 1 <= ret["graph_depth"] <= 5:
        raise ValueError("graph_depth debe estar entre 1 y 5")


def get() -> dict:
    try:
        doc = db.coll(config.COLL_SETTINGS).find_one({"_id": "global"}) or {}
        doc.pop("_id", None)
    except Exception as exc:
        print(f"[aviso] No se pudieron leer los ajustes: {exc}")
        doc = {}
    return _deep_merge(DEFAULTS, doc)


def update(patch: dict) -> dict:
    if _has_api_key(patch):
        raise ValueError("Las API keys no se guardan en ajustes (usa llm_keys).")
    new = _deep_merge(get(), patch)
    _validate(new)
    db.coll(config.COLL_SETTINGS).replace_one({"_id": "global"}, {"_id": "global", **new}, upsert=True)
    return get()


def set_api_key(role: str, api_key: str) -> None:
    if role not in _keys:
        raise ValueError("role debe ser graph o chat")
    if api_key and api_key.strip():
        _keys[role] = api_key.strip()


def llm(role: str) -> dict:
    """LLM efectivo (UI -> .env). Con same_for_all, ambos roles usan el bloque chat."""
    cfg = get()["llm"]
    src = "chat" if cfg["same_for_all"] else role
    return {
        "base_url": cfg[src]["base_url"] or config.DEEPSEEK_BASE_URL,
        "model": cfg[src]["model"] or config.DEEPSEEK_MODEL,
        "api_key": _keys[src] or config.DEEPSEEK_API_KEY,
    }


def public_view() -> dict:
    out = get()
    out["llm"] = {**out["llm"], **{
        r: {"base_url": (v := llm(r))["base_url"], "model": v["model"], "has_key": bool(v["api_key"])}
        for r in ("graph", "chat")}}
    return out
