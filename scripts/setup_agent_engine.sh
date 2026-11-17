#!/usr/bin/env bash
# ============================================================
#  scripts/setup_agent_engine.sh
#  Crea y despliega en Atlas Agent Engine el servicio de MEMORIA
#  usando solo los valores de tu .env. Es opcional: sin memoria el
#  chat funciona igual.
#
#  Uso:   ./scripts/setup_agent_engine.sh            (de verdad)
#         DRY_RUN=1 ./scripts/setup_agent_engine.sh  (solo muestra los pasos)
#
#  Antes:  agentengine auth login   (el login abre el navegador)
#  Nota:   crear un workspace exige una organizacion de Agent Engine
#          "Atlas-backed" (vinculada a un proyecto de Atlas).
# ============================================================
set -euo pipefail
cd "$(dirname "$0")/.."

[ -f .env ] || { echo "Falta el fichero .env (copia .env.example)"; exit 1; }
set -a; source .env; set +a
command -v agentengine >/dev/null || { echo "Instala la CLI 'agentengine' primero."; exit 1; }

# --- valores del .env (los de CHAT_LLM_* son los mismos que usa la app) ---
CTX="${AGENTENGINE_CONTEXT:-graphrag}"
DB="${MONGODB_DATABASE:-graphrag_demo}"
LLM_KEY="${LLM_API_KEY:-${CHAT_LLM_API_KEY:-}}"
AUTH_HEADER="${CHAT_LLM_AUTH_HEADER:-authorization}"
for v in MONGODB_URI VOYAGE_API_KEY CHAT_LLM_BASE_URL CHAT_LLM_MODEL AGENTIC_MEMORY_PROJECT_ID; do
  [ -n "${!v:-}" ] || { echo "Falta $v en el .env"; exit 1; }
done
[ -n "$LLM_KEY" ] || { echo "Falta LLM_API_KEY (o CHAT_LLM_API_KEY) en el .env"; exit 1; }

run() { echo "+ $*"; [ -n "${DRY_RUN:-}" ] || "$@"; }
secret() {  # sube un secret de proyecto leyendo el valor por stdin (no queda en el historial)
  echo "+ agentengine secret set $1 --stdin --project-scope --context $CTX"
  [ -n "${DRY_RUN:-}" ] || printf %s "$2" | agentengine secret set "$1" --stdin --project-scope --context "$CTX"
}

echo "== 1/5 Context (organizacion + proyecto de Agent Engine)"
if agentengine context list 2>/dev/null | awk '{print $1}' | grep -qx "$CTX"; then
  echo "El context '$CTX' ya existe."
else
  ORG=(); [ -n "${AGENTENGINE_ORG_ID:-}" ] && ORG=(--org-id "$AGENTENGINE_ORG_ID")
  run agentengine context create "$CTX" "${ORG[@]}" --project-id "$AGENTIC_MEMORY_PROJECT_ID" \
      --base-url https://agentengine.mongodb.com
fi

echo "== 2/5 Agente con memoria (genera project-config.yaml con tu LLM)"
if [ ! -d agent-engine ]; then
  LLM_API_KEY="$LLM_KEY" VOYAGE_API_KEY="$VOYAGE_API_KEY" run agentengine create --name graphrag-memory --memory \
    --llm openai-compatible --llm-base-url "$CHAT_LLM_BASE_URL" --llm-model "$CHAT_LLM_MODEL" \
    --llm-auth-header "$AUTH_HEADER" --dir agent-engine --yes
else
  echo "La carpeta agent-engine/ ya existe: se reutiliza."
fi

echo "== 3/5 Secrets de proyecto (la memoria corre en Agent Engine y no ve tu .env)"
secret MONGODB_URI "$MONGODB_URI"
secret MONGODB_DATABASE "$DB"
secret VOYAGE_API_KEY "$VOYAGE_API_KEY"
secret LLM_API_KEY "$LLM_KEY"

echo "== 4/5 Aplicar la configuracion de memoria"
( cd agent-engine 2>/dev/null || true
  run agentengine memory configure --context "$CTX"
  run agentengine memory apply --wait --context "$CTX" )

echo "== 5/5 Registrar y desplegar el workspace"
( cd agent-engine/agents/graphrag-memory 2>/dev/null || true
  run agentengine init --context "$CTX" --yes
  run agentengine deploy --context "$CTX" )

cat <<MSG

Listo. Falta un ultimo paso manual (el secret se muestra UNA sola vez):
  agentengine service-account create memory-service --context $CTX --role PROJECT_OWNER
y copia client id y secret a tu .env:
  AGENTIC_MEMORY_CLIENT_ID=...   AGENTIC_MEMORY_CLIENT_SECRET=...
MSG
