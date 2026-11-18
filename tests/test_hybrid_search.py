import pytest
import config
import settings
import setup_indexes
import vector_search as vs


def test_lexical_stage_filtra_como_el_vectorial():
    st = vs._lexical_stage("rdl 19/2022", "ana", "voyage-4")["$search"]
    assert st["index"] == config.TEXT_INDEX
    must = st["compound"]["must"][0]["text"]
    assert must["query"] == "rdl 19/2022" and {"value": "text", "multi": "es"} in must["path"]
    flt = st["compound"]["filter"]
    assert {"equals": {"path": "metadata.model", "value": "voyage-4"}} in flt
    owners = [c["equals"]["value"] for c in flt[0]["compound"]["should"]]
    assert owners == ["public", "ana"]


def test_pipeline_segun_modo():
    vec, lex = {"index": "i", "path": "text"}, {"$search": {}}
    assert vs._pipeline(vec, None, "vector", 12) == [{"$vectorSearch": vec}]
    assert vs._pipeline(None, lex, "bm25", 12) == [lex, {"$limit": 12}]
    hyb = vs._pipeline(vec, lex, "hybrid", 12)
    fusion = hyb[0]["$rankFusion"]
    assert set(fusion["input"]["pipelines"]) == {"vector", "bm25"}
    assert fusion["combination"]["weights"] == config.RRF_WEIGHTS and fusion["scoreDetails"] is True
    assert hyb[1] == {"$addFields": {"_sd": {"$meta": "scoreDetails"}}}


def test_annotate_ignora_rank_na_y_modos_simples():
    d = {"_sd": {"details": [{"inputPipelineName": "bm25", "rank": "NA"}, {"inputPipelineName": "vector", "rank": 2}]}}
    out = vs._annotate(d, "hybrid")
    assert out["found_by"] == ["vector"] and out["ranks"] == {"vector": 2} and "_sd" not in out
    both = vs._annotate({"_sd": {"details": [{"inputPipelineName": "bm25", "rank": 1},
                                             {"inputPipelineName": "vector", "rank": 3}]}}, "hybrid")
    assert both["found_by"] == ["bm25", "vector"]
    assert vs._annotate({}, "bm25")["found_by"] == ["bm25"]
    assert vs._annotate({}, "vector")["found_by"] == ["vector"]


def test_indice_de_texto_y_ajustes():
    d = setup_indexes.text_definition()
    fields = d["mappings"]["fields"]
    assert fields["text"]["multi"]["es"]["analyzer"] == "lucene.spanish"
    assert {"visibility", "owner", "model"} <= set(fields["metadata"]["fields"])
    assert all(v["type"] == "token" for v in fields["metadata"]["fields"].values())
    cfg = settings._deep_merge(settings.DEFAULTS, {})
    assert cfg["retrieval"]["search_mode"] == "hybrid"
    settings._validate(cfg)
    with pytest.raises(ValueError):
        settings._validate(settings._deep_merge(cfg, {"retrieval": {"search_mode": "fuzzy"}}))
