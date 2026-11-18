import re

import graph_store
import removal


def test_patron_de_fichero_es_exacto():
    p = removal.file_pattern("PDFs/FAQS (1).pdf")
    assert re.search(p, "file:PDFs/FAQS (1).pdf")
    assert not re.search(p, "file:PDFs/FAQS (1).pdf.bak") and not re.search(p, "github:PDFs/FAQS (1).pdf")


def test_patron_de_repo_no_confunde_nombres_parecidos():
    p = removal.repo_pattern("acme/api")
    assert re.search(p, "github:acme/api") and re.search(p, "github:acme/api/docs/x.md")
    assert not re.search(p, "github:acme/api-v2") and not re.search(p, "github:acme/apix/README.md")
    assert not re.search(p, "file:acme/api")


def test_drop_targets_mantiene_las_listas_alineadas():
    rel = {"target_ids": ["a", "b", "c"], "types": ["X", "Y", "Z"], "attributes": [{"v": 1}, {}, {"v": 3}]}
    new, n = graph_store._drop_targets(rel, {"b"})
    assert n == 1 and new == {"target_ids": ["a", "c"], "types": ["X", "Z"], "attributes": [{"v": 1}, {"v": 3}]}
    # listas desalineadas (pasa con entidades del LLM): no debe lanzar
    new, n = graph_store._drop_targets({"target_ids": ["a", "b"], "types": ["X"]}, {"a"})
    assert n == 1 and new["target_ids"] == ["b"]
    assert graph_store._drop_targets({}, {"a"}) == ({"target_ids": [], "types": [], "attributes": []}, 0)


def test_delete_items_valida_la_entrada():
    out = removal.delete_items([{"kind": "otro", "source": "x"}, {"kind": "file", "source": " "}], "u")
    assert all("error" in r for r in out)
