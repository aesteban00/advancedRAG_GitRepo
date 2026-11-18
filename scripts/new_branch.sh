#!/usr/bin/env bash
# ============================================================
#  scripts/new_branch.sh <nombre-de-rama>
#  Crea una rama desde main y deja preparados sus nombres:
#    BBDD de la app ........ <rama>
#    BBDD de la memoria .... <rama>_memory
#    context de Agent Engine <rama>   (proyecto de memoria con el mismo nombre)
#  Crea envs/<rama>.env con las claves que hay que rellenar a mano.
#  Crear el proyecto de Agent Engine NO se puede automatizar con esta CLI.
# ============================================================
set -euo pipefail
cd "$(dirname "$0")/.."

[ $# -eq 1 ] || { echo "uso: scripts/new_branch.sh <nombre-de-rama>"; exit 1; }
NAME="$1"
[[ "$NAME" =~ ^[A-Za-z0-9][A-Za-z0-9._/-]*$ ]] || { echo "Nombre de rama no valido: $NAME"; exit 1; }
[ "$NAME" != "main" ] || { echo "main ya existe."; exit 1; }
git show-ref --verify --quiet "refs/heads/$NAME" && { echo "La rama $NAME ya existe."; exit 1; }
[ -z "$(git status --porcelain --untracked-files=no)" ] || { echo "Tienes cambios sin commitear: confirma o guarda (stash) antes."; exit 1; }

SLUG=$(echo "$NAME" | tr 'A-Z' 'a-z' | sed -E 's/[^a-z0-9]+/_/g; s/^_+|_+$//g' | cut -c1-55)
echo "== Rama $NAME desde main"
git checkout -q main && git pull -q --ff-only origin main
git checkout -q -b "$NAME"

echo "== Perfil envs/$SLUG.env"
if [ ! -f "envs/$SLUG.env" ]; then
  cat > "envs/$SLUG.env" <<PROFILE
# Perfil privado de la rama $NAME (ignorado por git). Rellena los valores del proyecto de memoria.
AGENTENGINE_ORG_ID=
AGENTIC_MEMORY_PROJECT_ID=
AGENTIC_MEMORY_CLIENT_ID=
AGENTIC_MEMORY_CLIENT_SECRET=
PROFILE
  chmod 600 "envs/$SLUG.env"
fi

echo "== Ajustando .env a la rama"
python3 scripts/branch_env.py "$NAME"

cat <<MSG

Siguientes pasos (una sola vez por rama):
  1. En Agent Engine (consola), crea un PROYECTO llamado "$SLUG" dentro de una
     organizacion Atlas-backed. La CLI de esta version no puede crearlo.
  2. Copia su ID y las credenciales de un service account de ese proyecto en envs/$SLUG.env.
  3. Ejecuta de nuevo: python3 scripts/branch_env.py $NAME
  4. Memoria: ./scripts/setup_agent_engine.sh  (usa MEMORY_MONGODB_DATABASE=${SLUG}_memory).
  5. Arranca la app: uvicorn app.main:app --reload --port 8090
Mientras no completes el perfil, la app arranca con la memoria desactivada.
MSG
