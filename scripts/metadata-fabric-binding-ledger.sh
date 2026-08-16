#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMMON_GIT_DIR="$(git -C "${REPO_ROOT}" rev-parse --path-format=absolute --git-common-dir 2>/dev/null || true)"
SHARED_ROOT=""
if [ -n "${COMMON_GIT_DIR}" ]; then
  SHARED_ROOT="$(cd "${COMMON_GIT_DIR}/.." && pwd)"
fi
if [ -n "${PYTHON:-}" ]; then
  PYTHON_BIN="${PYTHON}"
elif [ -x "${REPO_ROOT}/.venv/bin/python" ]; then
  PYTHON_BIN="${REPO_ROOT}/.venv/bin/python"
elif [ -n "${SHARED_ROOT}" ] && [ -x "${SHARED_ROOT}/.venv/bin/python" ]; then
  PYTHON_BIN="${SHARED_ROOT}/.venv/bin/python"
else
  PYTHON_BIN="python"
fi
EVIDENCE_OUT="${GDA_BINDING_LEDGER_EVIDENCE_OUT:-${REPO_ROOT}/docs/evidence/metadata-fabric-binding-ledger-2026-07-28.json}"
CONTAINER_NAME="gda-metadata-binding-${$}-${RANDOM}"
DATABASE_NAME="gda_binding"
DATABASE_PASSWORD="$(openssl rand -hex 24)"

cleanup() {
  docker rm -f "${CONTAINER_NAME}" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

docker run --detach --rm \
  --name "${CONTAINER_NAME}" \
  --env "POSTGRES_PASSWORD=${DATABASE_PASSWORD}" \
  --env "POSTGRES_DB=${DATABASE_NAME}" \
  --publish 127.0.0.1::5432 \
  postgres:16-alpine >/dev/null

for _attempt in $(seq 1 60); do
  if docker exec "${CONTAINER_NAME}" pg_isready \
    --username postgres --dbname "${DATABASE_NAME}" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
docker exec "${CONTAINER_NAME}" pg_isready \
  --username postgres --dbname "${DATABASE_NAME}" >/dev/null

HOST_PORT="$(docker port "${CONTAINER_NAME}" 5432/tcp | sed -E 's/.*:([0-9]+)$/\1/')"
DATABASE_URL="postgresql+psycopg2://postgres:${DATABASE_PASSWORD}@127.0.0.1:${HOST_PORT}/${DATABASE_NAME}"

cd "${REPO_ROOT}"
"${PYTHON_BIN}" -m data_agent.metadata_fabric_binding_ledger rehearse \
  --database-url "${DATABASE_URL}" \
  --evidence-out "${EVIDENCE_OUT}"
