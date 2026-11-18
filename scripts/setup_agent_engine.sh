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

# --- valores del .env (la memoria usa su PROPIO LLM, MEMORY_LLM_*, independiente del de chat CHAT_LLM_*) ---
CTX="${AGENTENGINE_CONTEXT:-graphrag}"
DB="${MONGODB_DATABASE:-graphrag_demo}"
LLM_KEY="${MEMORY_LLM_API_KEY:-}"
AUTH_HEADER="${MEMORY_LLM_AUTH_HEADER:-authorization}"
for v in MONGODB_URI VOYAGE_API_KEY MEMORY_LLM_BASE_URL MEMORY_LLM_MODEL AGENTIC_MEMORY_PROJECT_ID AGENTENGINE_ORG_ID; do
  [ -n "${!v:-}" ] || { echo "Falta $v en el .env"; exit 1; }
done
case "$MEMORY_LLM_BASE_URL" in
  *ai-gateway.corp.mongodb.com*)
    echo "ERROR: ai-gateway.corp.mongodb.com NO es alcanzable desde Agent Engine (restriccion de red conocida,"
    echo "       afecta tambien a la memoria). Usa el gateway Grove publico, con una clave Grove NUEVA:"
    echo "         MEMORY_LLM_BASE_URL=https://grove-gateway-prod.azure-api.net/grove-foundry-prod/openai/v1"
    echo "         MEMORY_LLM_AUTH_HEADER=api-key"
    echo "       (o la API publica de un proveedor: https://api.openai.com/v1 con MEMORY_LLM_AUTH_HEADER=authorization)."
    exit 1 ;;
esac
[ -n "$LLM_KEY" ] || { echo "Falta MEMORY_LLM_API_KEY en el .env"; exit 1; }

run() { echo "+ $*"; [ -n "${DRY_RUN:-}" ] || "$@"; }
secret() {  # sube un secret de proyecto leyendo el valor por stdin (no queda en el historial)
  echo "+ agentengine secret set $1 --stdin --project-scope --context $CTX"
  [ -n "${DRY_RUN:-}" ] && return 0
  printf %s "$2" | agentengine secret set "$1" --stdin --project-scope --context "$CTX" || {
    echo "AVISO: no se pudo subir $1 (¿tu usuario no es PROJECT_OWNER?). Si ya lo creaste en la consola"
    echo "       (Secrets > Add Secrets) puedes ignorarlo; si no, crealo alli o pide el rol PROJECT_OWNER."
  }
}

echo "== 1/5 Context (organizacion + proyecto de Agent Engine)"
create_ctx() {
  run agentengine context create "$CTX" --org-id "$AGENTENGINE_ORG_ID" \
      --project-id "$AGENTIC_MEMORY_PROJECT_ID" --base-url https://agentengine.mongodb.com
}
if row=$(agentengine context list 2>/dev/null | awk -v c="$CTX" '$1==c'); [ -n "$row" ]; then
  read -r _ _ ctx_org ctx_proj <<<"$row"
  if [ "$ctx_org" != "$AGENTENGINE_ORG_ID" ] || [ "$ctx_proj" != "$AGENTIC_MEMORY_PROJECT_ID" ]; then
    # Un context no se puede reapuntar: hay que borrarlo y recrearlo (solo afecta a esta maquina).
    echo "ADVERTENCIA: el context '$CTX' apunta a org=$ctx_org proyecto=$ctx_proj,"
    echo "             pero tu .env dice org=$AGENTENGINE_ORG_ID proyecto=$AGENTIC_MEMORY_PROJECT_ID."
    echo "Para continuar se va a:"
    echo "  - borrar el context local '$CTX' (agentengine context delete; no toca nada en Agent Engine)"
    echo "  - borrar la carpeta local agent-engine/ (agente generado, pin y registro del workspace)"
    echo "  - recrear ambos con los valores de tu .env"
    read -r -p "¿Continuar? [y/N] " ans
    [ "$ans" = "y" ] || { echo "Cancelado. Corrige el .env o usa otro AGENTENGINE_CONTEXT."; exit 1; }
    run agentengine context delete "$CTX" --yes
    run rm -rf agent-engine
    create_ctx
  else
    echo "El context '$CTX' ya existe y coincide con el .env."
  fi
else
  create_ctx
fi

echo "== 2/5 Agente con memoria (carpeta agent-engine/, se crea aqui)"
TARGET="$AGENTENGINE_ORG_ID $AGENTIC_MEMORY_PROJECT_ID"
if [ -d agent-engine ] && [ "$(cat agent-engine/.target 2>/dev/null)" != "$TARGET" ]; then
  # La carpeta se genero para otra org/proyecto (o con una version antigua del script): hay que recrearla.
  echo "ADVERTENCIA: agent-engine/ no corresponde a la org/proyecto de tu .env."
  read -r -p "¿Borrar agent-engine/ y recrearla? [y/N] " ans
  [ "$ans" = "y" ] || { echo "Cancelado."; exit 1; }
  run rm -rf agent-engine
fi
if [ ! -d agent-engine ] || [ -n "${DRY_RUN:-}" ]; then
  LLM_API_KEY="$LLM_KEY" VOYAGE_API_KEY="$VOYAGE_API_KEY" run agentengine create --name graphrag-memory --memory \
    --llm openai-compatible --llm-base-url "$MEMORY_LLM_BASE_URL" --llm-model "$MEMORY_LLM_MODEL" \
    --llm-auth-header "$AUTH_HEADER" --dir agent-engine --yes
  [ -n "${DRY_RUN:-}" ] || echo "$TARGET" > agent-engine/.target
else
  echo "La carpeta agent-engine/ ya existe: se reutiliza."
fi

# project-config.yaml (raiz) es la fuente de verdad: se copia al agente rellenando los marcadores con el .env
if [ -z "${DRY_RUN:-}" ]; then
  sed -e "s|__MEMORY_LLM_BASE_URL__|$MEMORY_LLM_BASE_URL|" -e "s|__MEMORY_LLM_MODEL__|$MEMORY_LLM_MODEL|" \
      -e "s|__MEMORY_LLM_AUTH_HEADER__|$AUTH_HEADER|" project-config.yaml > agent-engine/project-config.yaml
fi
echo "+ project-config.yaml (raiz) -> agent-engine/project-config.yaml"

echo "== 3/5 Secrets de proyecto (la memoria corre en Agent Engine y no ve tu .env)"
secret MONGODB_URI "$MONGODB_URI"
secret MONGODB_DATABASE "$DB"
secret VOYAGE_API_KEY "$VOYAGE_API_KEY"
secret LLM_API_KEY "$LLM_KEY"

echo "== 4/5 Aplicar la configuracion de memoria"
( cd agent-engine 2>/dev/null || true
  run agentengine memory configure --context "$CTX"
  run agentengine memory apply --wait --context "$CTX" ) || {
  echo; echo "La memoria no arranco. Estado e indicacion de la plataforma:"
  agentengine memory status --context "$CTX" || true
  exit 1
}

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
