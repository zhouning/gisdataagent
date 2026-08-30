#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
COMPOSE_FILE="${REPO_ROOT}/docker-compose.dolphinscheduler-sandbox.yml"
RUNTIME_DIR="${GDA_DOLPHINSCHEDULER_SANDBOX_DIR:-${REPO_ROOT}/.tmp/dolphinscheduler-sandbox}"
ENV_FILE="${RUNTIME_DIR}/sandbox.env"
EXECUTOR_TOKEN_FILE="${RUNTIME_DIR}/executor-token"

mkdir -p "${RUNTIME_DIR}"
chmod 700 "${RUNTIME_DIR}"

if [[ ! -f "${ENV_FILE}" ]]; then
  umask 077
  DB_PASSWORD="$(openssl rand -hex 32)"
  {
    printf 'DOLPHINSCHEDULER_DB_PASSWORD=%s\n' "${DB_PASSWORD}"
    printf 'DOLPHINSCHEDULER_API_PORT=%s\n' "${DOLPHINSCHEDULER_API_PORT:-12345}"
  } >"${ENV_FILE}"
fi

chmod 600 "${ENV_FILE}"

if [[ ! -f "${EXECUTOR_TOKEN_FILE}" ]]; then
  openssl rand -hex 32 -out "${EXECUTOR_TOKEN_FILE}"
fi
chmod 600 "${EXECUTOR_TOKEN_FILE}"
export GDA_DATAOPS_EXECUTOR_TOKEN_FILE="${EXECUTOR_TOKEN_FILE}"

docker compose \
  --env-file "${ENV_FILE}" \
  -f "${COMPOSE_FILE}" \
  up -d

API_PORT="$(sed -n 's/^DOLPHINSCHEDULER_API_PORT=//p' "${ENV_FILE}")"
API_PORT="${API_PORT:-12345}"
BASE_URL="http://127.0.0.1:${API_PORT}/dolphinscheduler"

for _attempt in $(seq 1 60); do
  if curl -fsS "${BASE_URL}/actuator/health" >/dev/null; then
    break
  fi
  sleep 2
done

curl -fsS "${BASE_URL}/actuator/health" >/dev/null
python3 "${SCRIPT_DIR}/bootstrap_dolphinscheduler_api.py" \
  --base-url "${BASE_URL}" \
  --runtime-dir "${RUNTIME_DIR}"

printf 'DolphinScheduler sandbox ready at %s/\n' "${BASE_URL}"
printf 'Runtime credentials are stored with mode 0600 under %s\n' "${RUNTIME_DIR}"
