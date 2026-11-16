import pytest
import loaders


def test_split_text():
    assert loaders.split_text("   ", 100, 10) == []
    chunks = loaders.split_text("a" * 250, 100, 20)
    assert all(len(c) <= 100 for c in chunks) and len(chunks) == 3
    with pytest.raises(ValueError):
        loaders.split_text("hola", 10, 10)


def test_load_pages():
    assert loaders.load_pages("a.md", b"# hola")[0]["text"] == "# hola"
    with pytest.raises(ValueError):
        loaders.load_pages("a.docx", b"x")
    with pytest.raises(ValueError):
        loaders.load_pages("a.md", b"")


def test_make_chunks_fixed_for_context():
    pages = [{"page": 1, "text": "palabra " * 600, "images": []}]
    fixed = loaders.make_chunks(pages, "voyage_context", 200, 10)
    assert max(len(c["text"]) for c in fixed) <= 1000
    small = loaders.make_chunks(pages, "auto_embed", 200, 10)
    assert len(small) > len(fixed)
