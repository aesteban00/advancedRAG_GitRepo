import graph_store
import graph_view


def test_make_entity():
    e = graph_store.make_entity("a/b", "Repository", "github:a/b", {"language": "Python"},
                                [("fastapi", "DEPENDS_ON", {"version": "1"})])
    assert e["attributes"] == {"language": ["Python"], "sources": ["github:a/b"]}
    assert e["relationships"] == {"target_ids": ["fastapi"], "types": ["DEPENDS_ON"],
                                  "attributes": [{"version": ["1"]}]}


def test_layout():
    assert graph_view.subgraph_layout([]) == {"nodes": [], "edges": []}
    ents = [graph_store.make_entity("a/b", "Repository", "s", None, [("lib", "DEPENDS_ON", {})]),
            {"_id": "x", "type": "File", "relationships": {"target_ids": ["a/b", "z"], "types": ["CONTAINS"]}}]
    g = graph_view.subgraph_layout(ents, highlight=["a/b"])
    assert {n["id"] for n in g["nodes"]} == {"a/b", "lib", "x", "z"}
    assert all(0 <= n["x"] <= 1 and 0 <= n["y"] <= 1 for n in g["nodes"])
    assert next(n for n in g["nodes"] if n["id"] == "a/b")["highlight"]


def test_bfs_camino_mas_corto():
    adj = {"a": ["b", "c"], "b": ["d"], "c": ["d", "e"], "d": [], "e": ["f"]}
    assert graph_store._bfs(adj, "a", "d") in (["a", "b", "d"], ["a", "c", "d"])
    assert graph_store._bfs(adj, "a", "f") == ["a", "c", "e", "f"]
    assert graph_store._bfs(adj, "a", "a") == ["a"]
    assert graph_store._bfs(adj, "d", "a") is None   # el grafo es dirigido
