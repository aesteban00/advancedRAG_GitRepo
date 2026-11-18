import pytest
import chat
import settings


def test_deep_merge():
    a = {"x": {"y": 1, "z": 2}}
    assert settings._deep_merge(a, {"x": {"y": 9}}) == {"x": {"y": 9, "z": 2}}
    assert a["x"]["y"] == 1


def test_validate():
    ok = settings._deep_merge(settings.DEFAULTS, {})
    settings._validate(ok)
    for patch in ({"ingest": {"strategy": "x"}}, {"ingest": {"chunk_overlap": 900}},
                  {"embedding": {"auto_embed": "gpt"}}, {"retrieval": {"top_k": 99}}):
        with pytest.raises(ValueError):
            settings._validate(settings._deep_merge(ok, patch))
    assert settings._has_api_key({"llm": {"chat": {"api_key": "x"}}})


def test_format_entity():
    e = {"_id": "a/b", "type": "Repository", "attributes": {"sources": ["github:a/b"], "language": ["Python"]},
         "relationships": {"target_ids": ["fastapi"], "types": ["DEPENDS_ON"]}}
    line = chat._format_entity(e)
    assert "a/b (Repository)" in line and "DEPENDS_ON fastapi" in line and "github:a/b" in line
