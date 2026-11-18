import pytest
import github_ingest as g


def test_requirements():
    t = "# c\nfastapi==0.1\nuvicorn[standard]>=0.2\n-r other.txt\nrequests ; python_version<'3'\n"
    assert g.parse_requirements(t) == [("fastapi", "0.1"), ("uvicorn", "0.2"), ("requests", "")]


def test_pyproject():
    assert g.parse_pyproject('[project]\ndependencies=["pymongo>=4"]') == [("pymongo", "4")]
    p = '[tool.poetry.dependencies]\npython="^3.11"\nflask="^2.0"'
    assert g.parse_pyproject(p) == [("flask", "2.0")]


def test_other_manifests():
    assert g.parse_package_json('{"dependencies":{"express":"^4.1"}}') == [("express", "4.1")]
    assert g.parse_go_mod("require (\n\tgithub.com/a/b v1.2.3\n)\nrequire x/y v0.1") == [
        ("github.com/a/b", "v1.2.3"), ("x/y", "v0.1")]
    pom = "<dependency><groupId>org.x</groupId><artifactId>y</artifactId><version>1</version></dependency>"
    assert g.parse_pom(pom) == [("org.x:y", "1")]
    assert g.parse_codeowners("* @acme/a @bob # c\n/x @acme/a") == ["@acme/a", "@bob"]


def test_repo_url():
    assert g.parse_repo_url("https://github.com/Foo/Bar.git") == ("foo", "bar")
    assert g.parse_repo_url("https://github.com/foo/bar/tree/main") == ("foo", "bar")
    with pytest.raises(ValueError):
        g.parse_repo_url("https://gitlab.com/a/b")


def test_endpoints():
    assert g.find_endpoints("a.py", '@app.get("/u")\n@bp.route("/x")') == ["GET /u", "ANY /x"]
    assert g.find_endpoints("a.js", "router.post('/p', h)") == ["POST /p"]
    assert g.find_endpoints("A.java", '@GetMapping("/j")') == ["GET /j"]


def test_python_symbols():
    code = "import os\nfrom fastapi import X\nclass A:\n  def m(self): helper()\ndef helper(): pass\n"
    s = g.python_symbols("a.py", code)
    assert s["classes"] == ["A"] and "A.m" in s["functions"]
    assert s["imports"] == ["os", "fastapi"] and s["calls"]["A.m"] == ["helper"]
    assert g.python_symbols("a.py", "def (") == {"classes": [], "functions": [], "imports": [], "calls": {}}
