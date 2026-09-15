#!/usr/bin/env bash
# Run the v51 Liveability source/artifact gate, then optionally start Chainlit.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

SOURCE_ID="${GDA_ABU_DHABI_LIVEABILITY_SOURCE_ID:-12}"
SOURCE_OWNER="${GDA_ABU_DHABI_SOURCE_OWNER:-abu-dhabi-site-operator}"
EXPECTED_SOURCE_PORT="${GDA_ABU_DHABI_SOURCE_PORT:-5443}"
HOST="${GDA_DEMO_HOST:-127.0.0.1}"
PORT="${GDA_DEMO_PORT:-8000}"
CHECK_ONLY=false

while (( $# > 0 )); do
  case "$1" in
    --check-only) CHECK_ONLY=true ;;
    --no-llm-proxy)
      export GDA_DISABLE_LLM_PROXY=1
      unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy
      ;;
    --host) shift; HOST="${1:-}" ;;
    --host=*) HOST="${1#*=}" ;;
    --port) shift; PORT="${1:-}" ;;
    --port=*) PORT="${1#*=}" ;;
    --help|-h)
      printf '%s\n' 'Usage: scripts/run_abu_dhabi_liveability_v51_demo.sh [--check-only] [--no-llm-proxy] [--host HOST] [--port PORT]'
      exit 0 ;;
    *) printf '[v51-demo][error] unknown option: %s\n' "$1" >&2; exit 1 ;;
  esac
  shift
done

[[ "$SOURCE_ID" =~ ^[0-9]+$ && "$EXPECTED_SOURCE_PORT" =~ ^[0-9]+$ && "$PORT" =~ ^[0-9]+$ ]] || {
  printf '[v51-demo][error] source id and ports must be numeric\n' >&2; exit 1;
}

for file in "${GDA_OPERATOR_ENV_FILE:-${REPO_ROOT}/data_agent/.env}" "${REPO_ROOT}/data_agent/.vsource-secret.env" "${GDA_CUSTOMER_SOURCE_SECRET_ENV_FILE:-${REPO_ROOT}/data_agent/.abu-dhabi-vsource-secret.env}"; do
  if [[ -f "$file" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$file"
    set +a
  fi
done
[[ -f "${REPO_ROOT}/data_agent/.vsource-secret.env" ]] && export GDA_VSOURCE_SECRET_FILE="${GDA_VSOURCE_SECRET_FILE:-${REPO_ROOT}/data_agent/.vsource-secret.env}"

[[ -x "${REPO_ROOT}/.venv/bin/python" ]] || { printf '[v51-demo][error] repository .venv is required\n' >&2; exit 1; }
PYTHON=("${REPO_ROOT}/.venv/bin/python")
PREFLIGHT="$("${PYTHON[@]}" scripts/abu_dhabi_v50_preflight.py --source-id "$SOURCE_ID" --owner "$SOURCE_OWNER" --expected-port "$EXPECTED_SOURCE_PORT" --semantic-revision 51 --ontology-revision 50 --require-technical-schema-drift)" || {
  printf '[v51-demo][error] v51 preflight failed\n' >&2; exit 1;
}
printf '[v51-demo][ok] %s\n' "$(printf '%s' "$PREFLIGHT" | "${PYTHON[@]}" -c 'import json,sys; p=json.load(sys.stdin); print(p["semantic_version"])')"
printf '[v51-demo][ok] source %s is healthy on port %s; metadata-only discovery and runtime boundary passed\n' "$SOURCE_ID" "$EXPECTED_SOURCE_PORT"

if [[ "$CHECK_ONLY" == true ]]; then
  printf '[v51-demo] check-only requested; Chainlit was not started\n'
  exit 0
fi
[[ -n "${CHAINLIT_AUTH_SECRET:-}" ]] || { printf '[v51-demo][error] CHAINLIT_AUTH_SECRET is required\n' >&2; exit 1; }
[[ -x "${REPO_ROOT}/.venv/bin/chainlit" ]] || { printf '[v51-demo][error] Chainlit is unavailable in .venv\n' >&2; exit 1; }
if command -v lsof >/dev/null 2>&1 && lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  printf '[v51-demo][error] port %s is already in use\n' "$PORT" >&2; exit 1
fi
printf '[v51-demo] login URL: http://%s:%s\n' "$HOST" "$PORT"
printf '[v51-demo] manual acceptance: docs/customer/abu_dhabi_liveability_site_validation/liveability_v51_manual_acceptance_script.md\n'
exec "${REPO_ROOT}/.venv/bin/chainlit" run data_agent/app.py --host "$HOST" --port "$PORT" -w
