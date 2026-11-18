#!/usr/bin/env bash
# ============================================================
#  scripts/worktree.sh <rama> <puerto>
#  Crea una carpeta de trabajo PROPIA para una rama (git worktree) y deja
#  listo su servidor en el puerto indicado. Permite tener varias ramas
#  arrancadas a la vez, cada una con su BBDD, su memoria y su .env.
#    ../advancedRAG_<slug>  ->  uvicorn --port <puerto>
#  Notas:
#    * La rama debe existir (crala con scripts/new_branch.sh).
#    * main no puede estar en dos carpetas: para main usa la carpeta original.
#    * El .env se COPIA (no se enlaza): el hook de cada carpeta lo reescribe.
#    * .venv se enlaza (solo lectura de dependencias).
# ============================================================
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

[ $# -eq 2 ] || { echo "uso: scripts/worktree.sh <rama> <puerto>"; exit 1; }
BR="$1"; PORT="$2"
[[ "$PORT" =~ ^[0-9]+$ ]] || { echo "Puerto no valido: $PORT"; exit 1; }
[ "$BR" != "main" ] || { echo "main ya esta en la carpeta original ($ROOT). Usa otra rama."; exit 1; }
git show-ref --verify --quiet "refs/heads/$BR" || { echo "La rama $BR no existe. Crala con scripts/new_branch.sh $BR"; exit 1; }
[ -f .env ] || { echo "Falta .env en $ROOT"; exit 1; }

SLUG=$(echo "$BR" | tr 'A-Z' 'a-z' | sed -E 's/[^a-z0-9]+/_/g; s/^_+|_+$//g' | cut -c1-55)
DIR="$(dirname "$ROOT")/advancedRAG_$SLUG"

if [ -d "$DIR" ]; then
  echo "La carpeta $DIR ya existe: se reutiliza."
else
  echo "== git worktree add $DIR $BR"
  git worktree add "$DIR" "$BR"
fi

cd "$DIR"
echo "== Copiando configuracion privada (.env y envs/)"
cp "$ROOT/.env" .env && chmod 600 .env
rm -rf envs && cp -R "$ROOT/envs" envs
[ -e .venv ] || ln -s "$ROOT/.venv" .venv
echo "== Ajustando .env a la rama $BR"
python3 scripts/branch_env.py "$BR"

echo
echo "Listo. Arranca con:"
echo "  cd $DIR && source .venv/bin/activate && uvicorn app.main:app --reload --port $PORT"
echo "Limpiar la carpeta cuando ya no la necesites: git worktree remove $DIR"
