#!/bin/bash
# GIS Data Agent strict SQL migration entrypoint.
set -euo pipefail

export POSTGRES_HOST="${POSTGRES_HOST:-localhost}"
export POSTGRES_PORT="${POSTGRES_PORT:-5433}"
export POSTGRES_DATABASE="${POSTGRES_DATABASE:-gis_agent}"
export POSTGRES_USER="${POSTGRES_ADMIN_USER:-${POSTGRES_USER:-postgres}}"
export POSTGRES_PASSWORD="${POSTGRES_ADMIN_PASSWORD:-${POSTGRES_PASSWORD:-postgres}}"
# Migrations intentionally use the admin components above. DATABASE_URL is
# the application-role authority everywhere else and therefore must not win.
unset DATABASE_URL

echo "========================================="
echo " GIS Data Agent - SQL Migrations"
echo "========================================="
echo "Host:     $POSTGRES_HOST:$POSTGRES_PORT"
echo "Database: $POSTGRES_DATABASE"
echo ""

# The Python runner is the only migration authority.  It validates stable IDs,
# checks applied-file hashes, takes an advisory lock, and exits non-zero on any
# catalog drift or SQL failure.
python -m data_agent.migration_runner migrate "$@"
