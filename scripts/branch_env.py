#!/usr/bin/env python3
# ============================================================
#  scripts/branch_env.py
#  Ajusta el .env a la RAMA activa. Para cada rama:
#    * app:      MONGODB_DATABASE         = <rama>            (BBDD de la aplicacion)
#    * memoria:  MEMORY_MONGODB_DATABASE  = <rama>_memory     (BBDD que usa el agente de memoria)
#    * context:  AGENTENGINE_CONTEXT      = <rama>            (proyecto de Agent Engine de la rama)
#  Los datos que no se pueden deducir del nombre (organizacion, proyecto
#  de memoria y credenciales) salen de envs/<rama>.env, que es privado.
#  Solo reescribe un bloque marcado dentro de .env; el resto no se toca.
#  Lo ejecuta el hook post-checkout (.githooks) y scripts/new_branch.sh.
# ============================================================
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ENV = os.path.join(ROOT, ".env")
BEGIN = "# >>> branch-env (generado por scripts/branch_env.py; no editar a mano) >>>"
END = "# <<< branch-env <<<"
KEYS = ["MONGODB_DATABASE", "MEMORY_MONGODB_DATABASE", "AGENTENGINE_CONTEXT", "AGENTENGINE_ORG_ID",
        "AGENTIC_MEMORY_PROJECT_ID", "AGENTIC_MEMORY_CLIENT_ID", "AGENTIC_MEMORY_CLIENT_SECRET"]
# Excepcion: main conserva sus datos (graphrag_demo). Cualquier otra rama sigue la regla de nombres.
MAIN_DB = "graphrag_demo"


def slug(branch: str) -> str:
    """Nombre valido para BBDD de Mongo: solo minusculas, digitos y '_', maximo 55 caracteres."""
    s = re.sub(r"[^a-z0-9]+", "_", branch.lower()).strip("_")
    return s[:55] or "rama"


def read_profile(name: str) -> dict:
    path = os.path.join(ROOT, "envs", f"{name}.env")
    out = {}
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            m = re.match(r"^([A-Z_]+)=(.*)$", line.strip())
            if m:
                out[m.group(1)] = m.group(2)
    return out


def desired(branch: str) -> tuple[dict, list[str]]:
    warnings = []
    if branch == "main":
        base = {"MONGODB_DATABASE": MAIN_DB, "MEMORY_MONGODB_DATABASE": MAIN_DB, "AGENTENGINE_CONTEXT": "graphrag"}
        profile = read_profile("main")
    else:
        s = slug(branch)
        base = {"MONGODB_DATABASE": s, "MEMORY_MONGODB_DATABASE": s + "_memory", "AGENTENGINE_CONTEXT": s}
        profile = read_profile(s)
        if not profile:
            warnings.append(f"Falta envs/{s}.env: la memoria queda desactivada hasta completar el perfil.")
    values = {k: base.get(k, profile.get(k, "")) for k in KEYS}
    for k in ("AGENTENGINE_ORG_ID", "AGENTIC_MEMORY_PROJECT_ID", "AGENTIC_MEMORY_CLIENT_ID", "AGENTIC_MEMORY_CLIENT_SECRET"):
        if k in profile:
            values[k] = profile[k]
    return values, warnings


def apply(branch: str) -> list[str]:
    values, warnings = desired(branch)
    block = [BEGIN] + [f"{k}={values[k]}" for k in KEYS] + [END]
    text = open(ENV, encoding="utf-8").read() if os.path.exists(ENV) else ""
    if BEGIN in text and END in text:
        pre, rest = text.split(BEGIN, 1)
        post = rest.split(END, 1)[1]
        text = pre + "\n".join(block) + post
    else:
        text = text.rstrip("\n") + "\n\n" + "\n".join(block) + "\n"
    # Evita claves duplicadas fuera del bloque (dotenv podria leer una antigua).
    out = []
    inside = False
    for line in text.splitlines():
        if line == BEGIN:
            inside = True
        elif line == END:
            inside = False
        if not inside and re.match(r"^(%s)=" % "|".join(KEYS), line):
            continue
        out.append(line)
    tmp = ENV + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("\n".join(out).rstrip("\n") + "\n")
    os.replace(tmp, ENV)
    os.chmod(ENV, 0o600)
    return warnings


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("uso: branch_env.py <rama>")
    for w in apply(sys.argv[1]):
        print("AVISO:", w)
    v, _ = desired(sys.argv[1])
    print(f"Rama '{sys.argv[1]}': BBDD app={v['MONGODB_DATABASE']} · BBDD memoria={v['MEMORY_MONGODB_DATABASE']} · context={v['AGENTENGINE_CONTEXT']}")
