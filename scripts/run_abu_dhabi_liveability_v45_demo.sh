#!/usr/bin/env bash
# Preflight and start the Abu Dhabi Liveability v45 manual-acceptance session.
# Uses the registered virtual source and metadata-only discovery. It does not
# accept a PostgreSQL DSN, export source rows, or expose credentials.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

SOURCE_ID="${GDA_ABU_DHABI_LIVEABILITY_SOURCE_ID:-12}"
SOURCE_OWNER="${GDA_ABU_DHABI_SOURCE_OWNER:-abu-dhabi-site-operator}"
EXPECTED_SOURCE_PORT="${GDA_ABU_DHABI_SOURCE_PORT:-5443}"
HOST="${GDA_DEMO_HOST:-127.0.0.1}"
PORT="${GDA_DEMO_PORT:-8000}"
START_APP=true
USE_DOCKER_CONTROL_PLANE=false
ENV_FILE="${GDA_OPERATOR_ENV_FILE:-${REPO_ROOT}/data_agent/.env}"
SOURCE_SECRET_ENV_FILE="${REPO_ROOT}/data_agent/.vsource-secret.env"
CUSTOMER_SOURCE_SECRET_ENV_FILE="${GDA_CUSTOMER_SOURCE_SECRET_ENV_FILE:-${REPO_ROOT}/data_agent/.abu-dhabi-vsource-secret.env}"
RUNTIME_ENV_FILE="${GDA_DEMO_RUNTIME_ENV_FILE:-${REPO_ROOT}/data_agent/.demo-runtime.env}"

usage() {
  cat <<'EOF'
Usage: scripts/run_abu_dhabi_liveability_v45_demo.sh [options]

Options:
  --check-only          Run v45 preflight and do not start Chainlit.
  --docker-control-plane
                        Read control-plane database mapping from Docker Compose.
  --no-llm-proxy       Clear HTTP(S)/ALL proxy variables for this process.
  --host HOST          Bind address (default: 127.0.0.1).
  --port PORT          Bind port (default: 8000).
  --help               Show this help.

Environment overrides:
  GDA_ABU_DHABI_LIVEABILITY_SOURCE_ID (default: 12)
  GDA_ABU_DHABI_SOURCE_OWNER          (default: abu-dhabi-site-operator)
  GDA_ABU_DHABI_SOURCE_PORT           (default: 5443)
  GDA_OPERATOR_ENV_FILE               control-plane environment file
  GDA_CUSTOMER_SOURCE_SECRET_ENV_FILE registered-source secret file
  GDA_DEMO_RUNTIME_ENV_FILE           local Chainlit secret file
EOF
}

die() { printf '[v45-demo][error] %s\n' "$*" >&2; exit 1; }
ok() { printf '[v45-demo][ok] %s\n' "$*"; }
note() { printf '[v45-demo] %s\n' "$*"; }

while (( $# > 0 )); do
  case "$1" in
    --check-only) START_APP=false ;;
    --docker-control-plane) USE_DOCKER_CONTROL_PLANE=true ;;
    --no-llm-proxy)
      export GDA_DISABLE_LLM_PROXY=1
      unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy
      ;;
    --host) shift; HOST="${1:-}"; [[ -n "$HOST" ]] || die '--host requires a value' ;;
    --host=*) HOST="${1#*=}" ;;
    --port) shift; PORT="${1:-}"; [[ -n "$PORT" ]] || die '--port requires a value' ;;
    --port=*) PORT="${1#*=}" ;;
    --help|-h) usage; exit 0 ;;
    *) die "unknown option: $1" ;;
  esac
  shift
done

[[ "$SOURCE_ID" =~ ^[0-9]+$ ]] || die 'source id must be numeric'
[[ "$EXPECTED_SOURCE_PORT" =~ ^[0-9]+$ ]] || die 'source port must be numeric'
[[ "$PORT" =~ ^[0-9]+$ ]] || die 'application port must be numeric'

if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi
if [[ -f "$SOURCE_SECRET_ENV_FILE" ]]; then
  export GDA_VSOURCE_SECRET_FILE="${GDA_VSOURCE_SECRET_FILE:-$SOURCE_SECRET_ENV_FILE}"
  set -a
  # shellcheck disable=SC1090
  source "$SOURCE_SECRET_ENV_FILE"
  set +a
fi
if [[ -f "$CUSTOMER_SOURCE_SECRET_ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$CUSTOMER_SOURCE_SECRET_ENV_FILE"
  set +a
fi
if [[ -f "$RUNTIME_ENV_FILE" && -z "${CHAINLIT_AUTH_SECRET:-}" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$RUNTIME_ENV_FILE"
  set +a
fi

if command -v uv >/dev/null 2>&1; then
  PYTHON=(uv run --no-sync python)
  CHAINLIT=(uv run --no-sync chainlit)
elif [[ -x "$REPO_ROOT/.venv/bin/python" ]]; then
  PYTHON=("$REPO_ROOT/.venv/bin/python")
  CHAINLIT=("$REPO_ROOT/.venv/bin/chainlit")
elif command -v python3 >/dev/null 2>&1 && command -v chainlit >/dev/null 2>&1; then
  PYTHON=(python3)
  CHAINLIT=(chainlit)
else
  die '需要 uv，或仓库 .venv，或同时可用的 python3 与 chainlit'
fi

json_field() {
  local payload="$1" path="$2"
  printf '%s' "$payload" | "${PYTHON[@]}" -c '
import json, sys
value = json.load(sys.stdin)
for part in sys.argv[1].split("."):
    if not isinstance(value, dict):
        raise SystemExit(2)
    value = value.get(part)
if isinstance(value, (dict, list)):
    print(json.dumps(value, ensure_ascii=False, separators=(",", ":")))
elif value is None:
    print("")
else:
    print(value)
' "$path"
}

run_capture() {
  local output status
  set +e
  output="$("$@" 2>&1)"
  status=$?
  set -e
  if (( status != 0 )); then
    printf '%s\n' "$output" >&2
    return "$status"
  fi
  printf '%s' "$output"
}

if [[ "$USE_DOCKER_CONTROL_PLANE" == true ]]; then
  command -v docker >/dev/null 2>&1 || die '--docker-control-plane requires Docker Compose'
  COMPOSE_CONFIG="$(run_capture docker compose config --format json)" \
    || die 'cannot resolve Docker Compose configuration'
  DB_PORT_OUTPUT="$(run_capture docker compose port db 5432)" \
    || die 'Docker Compose database service is not running'
  DB_PORT="${DB_PORT_OUTPUT##*:}"
  [[ "$DB_PORT" =~ ^[0-9]+$ ]] || die 'cannot resolve Docker Compose database port'
  export POSTGRES_HOST=127.0.0.1 POSTGRES_PORT="$DB_PORT"
  export POSTGRES_DATABASE="$(json_field "$COMPOSE_CONFIG" services.app.environment.POSTGRES_DATABASE)"
  export POSTGRES_USER="$(json_field "$COMPOSE_CONFIG" services.app.environment.POSTGRES_USER)"
  export POSTGRES_PASSWORD="$(json_field "$COMPOSE_CONFIG" services.app.environment.POSTGRES_PASSWORD)"
  [[ -n "$POSTGRES_DATABASE" && -n "$POSTGRES_USER" && -n "$POSTGRES_PASSWORD" ]] \
    || die 'Docker Compose app database configuration is incomplete'
  ok 'using the running Docker Compose control-plane database'
  if [[ "$START_APP" == true && -z "${CHAINLIT_AUTH_SECRET:-}" ]]; then
    command -v openssl >/dev/null 2>&1 || die 'OpenSSL is required for local Chainlit auth'
    umask 077
    CHAINLIT_AUTH_SECRET="$(openssl rand -hex 32)"
    printf 'CHAINLIT_AUTH_SECRET=%s\n' "$CHAINLIT_AUTH_SECRET" > "$RUNTIME_ENV_FILE"
    chmod 600 "$RUNTIME_ENV_FILE"
    export CHAINLIT_AUTH_SECRET
    ok 'initialized the local Chainlit auth secret'
  fi
fi

note "repository: $REPO_ROOT"
note "source: id=$SOURCE_ID, owner=$SOURCE_OWNER, expected database port=$EXPECTED_SOURCE_PORT"
note 'scope: liveability_data_20260730/public, governed virtual read-only'

PREFLIGHT="$(run_capture "${PYTHON[@]}" scripts/abu_dhabi_v45_preflight.py \
  --source-id "$SOURCE_ID" --owner "$SOURCE_OWNER" --expected-port "$EXPECTED_SOURCE_PORT")" \
  || die 'source, migration, discovery, or v45 artifact preflight failed'
[[ "$(json_field "$PREFLIGHT" status)" == 'ok' ]] || die 'v45 preflight did not pass'
ok "source $SOURCE_ID is healthy and endpoint port is $(json_field "$PREFLIGHT" endpoint_port)"
ok "migration status: $(json_field "$PREFLIGHT" migration_status)"
ok 'metadata-only discovery and repeat fingerprint stability passed'
ok "v45 semantic bundle verified: $(json_field "$PREFLIGHT" semantic_version)"
note "ontology overlay: $(json_field "$PREFLIGHT" ontology_version)"
note "metrics=$(json_field "$PREFLIGHT" metric_contract_count), bindings=$(json_field "$PREFLIGHT" table_binding_count), reviewed_assets=$(json_field "$PREFLIGHT" reviewed_asset_count), relationships=$(json_field "$PREFLIGHT" relationship_count)"
ok 'runtime boundary verified: no Gold SQL/results and no source-row persistence'

if [[ "$START_APP" == false ]]; then
  note 'check-only requested; Chainlit was not started'
  exit 0
fi
[[ -n "${CHAINLIT_AUTH_SECRET:-}" ]] || die 'CHAINLIT_AUTH_SECRET is required outside Docker demo mode'
if command -v lsof >/dev/null 2>&1 && lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  die "port $PORT is already in use; choose --port=<free-port>"
fi
note 'starting Chainlit; stop with Ctrl-C'
note "login URL: http://${HOST}:${PORT}"
note 'manual acceptance script: docs/customer/abu_dhabi_liveability_site_validation/liveability_v45_manual_acceptance_script.md'
exec "${CHAINLIT[@]}" run data_agent/app.py --host "$HOST" --port "$PORT" -w
