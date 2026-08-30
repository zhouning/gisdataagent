#!/bin/bash
# GIS Data Agent strict SQL migration entrypoint.
set -euo pipefail

export POSTGRES_HOST="${POSTGRES_HOST:-localhost}"
export POSTGRES_PORT="${POSTGRES_PORT:-5433}"
export POSTGRES_DATABASE="${POSTGRES_DATABASE:-gis_agent}"
export MIGRATION_RUNTIME_DB_ROLE="${MIGRATION_RUNTIME_DB_ROLE:-agent_user}"
export POSTGRES_USER="${POSTGRES_ADMIN_USER:-${POSTGRES_USER:-postgres}}"
export POSTGRES_PASSWORD="${POSTGRES_ADMIN_PASSWORD:-${POSTGRES_PASSWORD:-postgres}}"
unset DATABASE_URL

echo "========================================="
echo " GIS Data Agent - SQL Migrations"
echo "========================================="
echo "Host:     $POSTGRES_HOST:$POSTGRES_PORT"
echo "Database: $POSTGRES_DATABASE"
echo ""

# The Python runner validates stable IDs and checksums, owns the advisory lock,
# and exits non-zero on catalog drift or the first SQL failure.
python -m data_agent.migration_runner migrate "$@"
bash "$(dirname "$0")/grant-platform-gateway-role.sh"
