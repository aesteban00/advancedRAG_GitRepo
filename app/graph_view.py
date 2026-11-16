# ============================================================
#  graph_view.py
#  NetworkX calcula en Python el layout (posiciones) del subgrafo; el
#  navegador solo dibuja circulos y lineas en SVG (sin librerias JS).
# ============================================================

from __future__ import annotations

import networkx as nx


def _label(node_id: str, type_: str) -> str:
    if type_ in ("Repository", "Endpoint"):
        return node_id
    return node_id.split("::")[-1].split("/")[-1]


def subgraph_layout(entities: list[dict], highlight: list[str] | None = None, max_nodes: int = 80) -> dict:
    highlight = highlight or []
    G = nx.DiGraph()
    for e in entities[:max_nodes]:
        G.add_node(e["_id"], type=e.get("type", ""))
    for e in entities:
        if e["_id"] not in G:
            continue
        rel = e.get("relationships") or {}
        types = rel.get("types", [])
        for i, t in enumerate(rel.get("target_ids", [])):
            if t not in G:
                if len(G) >= max_nodes:
                    continue
                G.add_node(t, type="?")
            G.add_edge(e["_id"], t, type=types[i] if i < len(types) else "")
    if len(G) == 0:
        return {"nodes": [], "edges": []}
    pos = nx.spring_layout(G, seed=42, k=1.5 / max(1, len(G)) ** 0.5)
    xs, ys = [p[0] for p in pos.values()], [p[1] for p in pos.values()]

    def norm(v, lo, hi):
        return 0.5 if hi == lo else (v - lo) / (hi - lo)

    nodes = [{"id": n, "type": d["type"], "label": _label(n, d["type"]),
              "x": round(float(norm(pos[n][0], min(xs), max(xs))), 4),
              "y": round(float(norm(pos[n][1], min(ys), max(ys))), 4),
              "highlight": n in highlight} for n, d in G.nodes(data=True)]
    edges = [{"source": a, "target": b, "type": d["type"]} for a, b, d in G.edges(data=True)]
    return {"nodes": nodes, "edges": edges}
