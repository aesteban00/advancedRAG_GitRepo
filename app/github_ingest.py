# ============================================================
#  github_ingest.py
#  Repos de GitHub -> grafo DETERMINISTA en MongoDB (sin LLM) + docs.
#  Se extrae: descripcion, librerias+versiones, BBDD/servicios, endpoints,
#  propietario, ficheros/clases/funciones Python y relaciones entre repos.
#  Ventaja MongoDB: cada nodo es un documento; se recorre con $graphLookup
#  en la BD en vez de cargar un JSON enorme por repo en memoria.
# ============================================================

from __future__ import annotations

import ast
import json
import re
import tomllib

import httpx

import config
import db
import graph_store
import ingest

make_entity = graph_store.make_entity
SKIP = ("node_modules/", "vendor/", "/test", "tests/", "test/", ".min.")
CODE_EXT = (".py", ".js", ".ts", ".java", ".go")
MANIFESTS = ("pyproject.toml", "package.json", "go.mod", "pom.xml")

TECH_MAP = {
    "pymongo": ("Database", "MongoDB"), "motor": ("Database", "MongoDB"), "mongoose": ("Database", "MongoDB"),
    "mongodb": ("Database", "MongoDB"), "org.mongodb": ("Database", "MongoDB"),
    "go.mongodb.org": ("Database", "MongoDB"), "psycopg": ("Database", "PostgreSQL"),
    "pg": ("Database", "PostgreSQL"), "org.postgresql": ("Database", "PostgreSQL"),
    "mysql": ("Database", "MySQL"), "redis": ("Database", "Redis"), "ioredis": ("Database", "Redis"),
    "elasticsearch": ("Database", "Elasticsearch"), "sqlalchemy": ("Database", "SQL (SQLAlchemy)"),
    "kafka": ("Service", "Kafka"), "confluent-kafka": ("Service", "Kafka"), "pika": ("Service", "RabbitMQ"),
    "boto3": ("Service", "AWS"), "@aws-sdk": ("Service", "AWS"), "openai": ("Service", "OpenAI API"),
    "voyageai": ("Service", "Voyage AI"), "databricks": ("Service", "Databricks"),
}


# ---------------------------- HTTP ----------------------------
def _gh(path: str):
    headers = {"Accept": "application/vnd.github+json"}
    if config.GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {config.GITHUB_TOKEN}"
    r = httpx.get(config.GITHUB_API + path, headers=headers, timeout=20)
    if r.status_code == 404:
        raise ValueError(f"Repo no encontrado o privado: {path}")
    if r.status_code == 403:
        raise RuntimeError("Limite de la API de GitHub alcanzado: anade GITHUB_TOKEN al .env")
    r.raise_for_status()
    return r.json()


def _raw(owner: str, repo: str, branch: str, path: str) -> str | None:
    try:
        r = httpx.get(f"{config.GITHUB_RAW}/{owner}/{repo}/{branch}/{path}", timeout=20)
    except httpx.HTTPError:
        return None
    if r.status_code != 200 or len(r.content) > config.GITHUB_MAX_FILE_BYTES:
        return None
    return r.text


def parse_repo_url(url: str) -> tuple[str, str]:
    m = re.match(r"^https?://(www\.)?github\.com/([\w.-]+)/([\w.-]+?)(\.git)?(/.*)?$", url.strip())
    if not m:
        raise ValueError("Solo se admiten URLs de github.com (https://github.com/owner/repo)")
    return m.group(2).lower(), m.group(3).lower()


# ---------------------------- parsers puros ----------------------------
def _req_line(line: str) -> tuple[str, str] | None:
    line = line.split("#")[0].split(";")[0].strip()
    if not line or line.startswith(("-", "git+", "http")):
        return None
    m = re.match(r"^([A-Za-z0-9_.\-]+)(?:\[[^\]]*\])?\s*(?:(==|>=|<=|~=|!=|>|<)\s*([\w.*]+))?", line)
    return (m.group(1).lower(), m.group(3) or "") if m else None


def parse_requirements(text: str) -> list[tuple[str, str]]:
    return [r for r in map(_req_line, text.splitlines()) if r]


def parse_pyproject(text: str) -> list[tuple[str, str]]:
    data = tomllib.loads(text)
    out = [r for r in map(_req_line, data.get("project", {}).get("dependencies", [])) if r]
    for name, v in data.get("tool", {}).get("poetry", {}).get("dependencies", {}).items():
        if name.lower() != "python":
            ver = v if isinstance(v, str) else (v.get("version", "") if isinstance(v, dict) else "")
            out.append((name.lower(), ver.lstrip("^~=")))
    return out


def parse_package_json(text: str) -> list[tuple[str, str]]:
    d = json.loads(text)
    return [(k.lower(), str(v).lstrip("^~"))
            for sec in ("dependencies", "devDependencies") for k, v in d.get(sec, {}).items()]


def parse_go_mod(text: str) -> list[tuple[str, str]]:
    out, in_block = [], False
    for line in text.splitlines():
        line = line.split("//")[0].strip()
        if line.startswith("require ("):
            in_block = True
        elif in_block and line == ")":
            in_block = False
        else:
            body = line[len("require "):] if line.startswith("require ") else (line if in_block else "")
            parts = body.split()
            if len(parts) >= 2:
                out.append((parts[0].lower(), parts[1]))
    return out


def parse_pom(text: str) -> list[tuple[str, str]]:
    out = []
    for block in re.findall(r"<dependency>(.*?)</dependency>", text, re.S):
        g = re.search(r"<groupId>(.*?)</groupId>", block)
        a = re.search(r"<artifactId>(.*?)</artifactId>", block)
        v = re.search(r"<version>(.*?)</version>", block)
        if g and a:
            out.append((f"{g.group(1)}:{a.group(1)}".lower(), v.group(1) if v else ""))
    return out


def parse_codeowners(text: str) -> list[str]:
    seen = []
    for line in text.splitlines():
        for tok in line.split("#")[0].split():
            if tok.startswith("@") and tok not in seen:
                seen.append(tok)
    return seen


def find_endpoints(path: str, text: str) -> list[str]:
    found = []
    for m, p in re.findall(r"@\w+\.(get|post|put|delete|patch)\(\s*[\"']([^\"']+)", text):
        found.append(f"{m.upper()} {p}")
    for p in re.findall(r"@\w+\.route\(\s*[\"']([^\"']+)", text):
        found.append(f"ANY {p}")
    for m, p in re.findall(r"\b(?:app|router)\.(get|post|put|delete|patch)\(\s*[\"'`]([^\"'`]+)", text):
        found.append(f"{m.upper()} {p}")
    for m, p in re.findall(r"@(Get|Post|Put|Delete|Patch)Mapping\(\s*(?:value\s*=\s*)?\"([^\"]+)\"", text):
        found.append(f"{m.upper()} {p}")
    return list(dict.fromkeys(found))


def python_symbols(path: str, text: str) -> dict:
    out = {"classes": [], "functions": [], "imports": [], "calls": {}}
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return out

    def calls_of(fn) -> list[str]:
        names = []
        for n in ast.walk(fn):
            if isinstance(n, ast.Call):
                f = n.func
                names.append(f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else "")
        return list(dict.fromkeys(n for n in names if n))

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out["functions"].append(node.name)
            out["calls"][node.name] = calls_of(node)
        elif isinstance(node, ast.ClassDef):
            out["classes"].append(node.name)
            for m in node.body:
                if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    out["functions"].append(f"{node.name}.{m.name}")
                    out["calls"][f"{node.name}.{m.name}"] = calls_of(m)
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            out["imports"] += [a.name.split(".")[0] for a in n.names]
        elif isinstance(n, ast.ImportFrom) and n.module and not n.level:
            out["imports"].append(n.module.split(".")[0])
    out["imports"] = list(dict.fromkeys(out["imports"]))
    return out


# ---------------------------- ingesta ----------------------------
def _parse_manifest(path: str, text: str) -> list[tuple[str, str]]:
    name = path.rsplit("/", 1)[-1]
    try:
        if name.startswith("requirements") and name.endswith(".txt"):
            return parse_requirements(text)
        return {"pyproject.toml": parse_pyproject, "package.json": parse_package_json,
                "go.mod": parse_go_mod, "pom.xml": parse_pom}[name](text)
    except Exception:
        return []


def _tech(lib: str):
    for k, v in TECH_MAP.items():
        if lib == k or lib.startswith(k):
            return v
    return None


def ingest_repo(url: str, user_id: str, visibility: str, log=None) -> dict:
    log = log or (lambda m: None)   # progreso visible en la interfaz (ver jobs.py)
    owner, repo = parse_repo_url(url)
    log(f"Consultando la API de GitHub: {owner}/{repo}")
    rid, src, warnings = f"{owner}/{repo}", f"github:{owner}/{repo}", []
    meta = _gh(f"/repos/{owner}/{repo}")
    branch = meta.get("default_branch", "main")
    tree = _gh(f"/repos/{owner}/{repo}/git/trees/{branch}?recursive=1")
    if tree.get("truncated"):
        warnings.append("El arbol del repo esta truncado: analisis parcial.")
    paths = [t["path"] for t in tree["tree"] if t["type"] == "blob"]
    log(f"Árbol descargado: {len(paths)} ficheros")
    ok = lambda p: not any(s in p.lower() for s in SKIP)

    ents: dict[str, dict] = {}

    def add(e: dict):
        """Fusiona entidades del mismo _id dentro de la ingesta."""
        cur = ents.get(e["_id"])
        if not cur:
            ents[e["_id"]] = e
            return
        cur["relationships"]["target_ids"] += e["relationships"]["target_ids"]
        cur["relationships"]["types"] += e["relationships"]["types"]
        cur["relationships"]["attributes"] += e["relationships"]["attributes"]

    rels: list[tuple[str, str, dict]] = []  # relaciones del repo

    # Propietario
    owners = []
    for p in ("CODEOWNERS", ".github/CODEOWNERS", "docs/CODEOWNERS"):
        if p in paths and (t := _raw(owner, repo, branch, p)):
            owners = parse_codeowners(t)
            break
    for o in owners[:5] or [None]:
        if o:
            add(make_entity(o, "Team", src))
            rels.append((o, "OWNED_BY", {}))
        else:
            add(make_entity(owner, "Organization", src))
            rels.append((owner, "OWNED_BY", {}))

    # Librerias, BBDD y servicios
    for p in filter(ok, paths):
        base = p.rsplit("/", 1)[-1]
        if base in MANIFESTS or (base.startswith("requirements") and base.endswith(".txt")):
            text = _raw(owner, repo, branch, p)
            for lib, ver in _parse_manifest(p, text or ""):
                add(make_entity(lib, "Library", src))
                rels.append((lib, "DEPENDS_ON", {"version": [ver] if ver else [], "manifest": [p]}))
                if (t := _tech(lib)):
                    add(make_entity(t[1], t[0], src))
                    rels.append((t[1], "USES_DATABASE" if t[0] == "Database" else "USES_SERVICE", {"via": [lib]}))
    libs = {r[0] for r in rels if r[1] == "DEPENDS_ON"}

    # Codigo: ficheros, endpoints, simbolos Python
    code = sorted((p for p in paths if p.endswith(CODE_EXT) and ok(p)), key=lambda p: p.count("/"))
    code = code[:config.GITHUB_MAX_FILES]
    log(f"Analizando {len(code)} ficheros de código (sin LLM)")
    func_ids: dict[str, list[str]] = {}
    file_calls: list[tuple[str, str, list[str]]] = []
    literals: list[str] = []
    for i, p in enumerate(code, 1):
        if i % 25 == 0:
            log(f"Código: {i}/{len(code)} ficheros")
        text = _raw(owner, repo, branch, p)
        if text is None:
            continue
        fid = f"{rid}/{p}"
        frels = []
        rels.append((fid, "CONTAINS", {}))
        for ep in find_endpoints(p, text):
            eid = f"{ep} @ {rid}"
            add(make_entity(eid, "Endpoint", src, {"path": ep.split(" ", 1)[1]}))
            rels.append((eid, "EXPOSES_ENDPOINT", {}))
            frels.append((eid, "DEFINES", {}))
        literals += re.findall(r"[\"'`](/[A-Za-z0-9_\-/{}:]+)[\"'`]", text)
        if p.endswith(".py"):
            sym = python_symbols(p, text)
            for c in sym["classes"] + sym["functions"]:
                cid = f"{fid}::{c}"
                add(make_entity(cid, "Class" if c in sym["classes"] else "Function", src))
                frels.append((cid, "DEFINES", {}))
                func_ids.setdefault(c.split(".")[-1], []).append(cid)
            for fn, called in sym["calls"].items():
                file_calls.append((f"{fid}::{fn}", fid, called))
            for imp in sym["imports"]:
                if imp.lower() in libs:
                    frels.append((imp.lower(), "IMPORTS", {}))
        add(make_entity(fid, "File", src, {"language": [p.rsplit(".", 1)[-1]]}, frels))
    for caller, _, called in file_calls:
        targets = [(func_ids[n][0], "CALLS", {}) for n in called if len(func_ids.get(n, [])) == 1 and func_ids[n][0] != caller]
        if targets and caller in ents:
            ents[caller]["relationships"]["target_ids"] += [t[0] for t in targets]
            ents[caller]["relationships"]["types"] += [t[1] for t in targets]
            ents[caller]["relationships"]["attributes"] += [{} for _ in targets]

    # Re-declarar relaciones de entidades ya creadas con make_entity (listas paralelas)
    uniq_lit = [l for l in dict.fromkeys(literals) if l.count("/") >= 2][:500]
    ends = [e for e in ents.values() if e["type"] == "Endpoint"]
    add(make_entity(rid, "Repository", src, {
        "description": meta.get("description") or "", "language": meta.get("language") or "",
        "topics": meta.get("topics") or [], "url": meta.get("html_url", ""),
        "stars": meta.get("stargazers_count", 0), "url_literals": uniq_lit,
        "endpoint_paths": [e["attributes"]["path"][0] for e in ends]}, rels))
    log(f"Escribiendo {len(ents)} entidades en el grafo")
    graph_store.upsert_entities(list(ents.values()))

    # Documentacion: README + docs/*.md por la ingesta normal (chunks + grafo LLM)
    docs = [p for p in paths if re.match(r"^readme(\.\w+)?$", p.lower())]
    docs += [p for p in paths if p.startswith("docs/") and p.endswith(".md")]
    n_docs = n_chunks = 0
    selected = docs[:config.GITHUB_MAX_DOCS]
    for i, p in enumerate(selected, 1):
        log(f"Documentación {i}/{len(selected)}: {p} (LLM: puede tardar, máx. {config.LLM_TIMEOUT_S}s por llamada)")
        text = _raw(owner, repo, branch, p)
        if not text:
            continue
        try:
            r = ingest.ingest_file(p.rsplit("/", 1)[-1] if p.endswith(".md") or "." in p else p + ".md",
                                   text.encode(), user_id, visibility, "github", f"{rid}/{p}")
            graph_store.upsert_entities([make_entity(f"{rid}/{p}", "Document", src, {}, [(rid, "DOCUMENTS", {})])])
            n_docs += 1
            n_chunks += r["chunks"]
            warnings += r["warnings"]
        except Exception as exc:
            warnings.append(f"{p}: {exc}")

    log("Relaciones entre repos…")
    link_repos()
    log("Repo terminado")
    return {"repo": rid, "entities": len(ents), "docs": n_docs, "chunks": n_chunks, "warnings": warnings}


def link_repos() -> int:
    """Relaciones entre repos: libreria interna o endpoint consumido."""
    coll = db.coll(config.COLL_GRAPH)
    # Solo repos con id "owner/repo". El grafo tambien tiene "Repository" extraidos por el LLM
    # (p. ej. "Banco Sabadell") que no tienen barra: antes provocaban "list index out of range".
    repos = [r for r in coll.find({"type": "Repository"}) if r["_id"].count("/") == 1]
    new = 0
    for a in repos:
        out, seen = [], set(zip(a["relationships"]["target_ids"], a["relationships"]["types"]))
        deps = set(a["relationships"]["target_ids"])
        lits = set(a.get("attributes", {}).get("url_literals", []))
        for b in repos:
            if b["_id"] == a["_id"]:
                continue
            via = None
            if b["_id"] in deps or b["_id"].split("/", 1)[1] in deps:
                via = "library"
            else:
                for p in b.get("attributes", {}).get("endpoint_paths", []):
                    if p.count("/") >= 2 and p in lits:
                        via = "endpoint"
                        ep = next((e for e in b["relationships"]["target_ids"] if e.split(" ")[1:2] == [p]), None)
                        if ep and (ep, "CALLS_ENDPOINT") not in seen:
                            out.append((ep, "CALLS_ENDPOINT", {}))
                        break
            if via and (b["_id"], "DEPENDS_ON") not in seen:
                out.append((b["_id"], "DEPENDS_ON", {"via": [via]}))
        if out:
            graph_store.upsert_entities([{"_id": a["_id"], "type": "Repository", "attributes": {}, "relationships": {
                "target_ids": [o[0] for o in out], "types": [o[1] for o in out], "attributes": [o[2] for o in out]}}])
            new += len(out)
    return new
