#!/bin/bash
# =============================================================================
# GIS Data Agent — SQL Migration Runner
# Usage: bash scripts/migrate.sh
# =============================================================================
set -euo pipefail

# ---- Configuration -----------------------------------------------------------

POSTGRES_HOST="${POSTGRES_HOST:-localhost}"
POSTGRES_PORT="${POSTGRES_PORT:-5433}"
POSTGRES_USER="${POSTGRES_ADMIN_USER:-postgres}"
POSTGRES_DATABASE="${POSTGRES_DATABASE:-gis_agent}"
MIGRATION_DIR="${MIGRATION_DIR:-data_agent/migrations}"

echo "========================================="
echo " GIS Data Agent — SQL Migrations"
echo "========================================="
echo "Host:       $POSTGRES_HOST:$POSTGRES_PORT"
echo "Database:   $POSTGRES_DATABASE"
echo "Migrations: $MIGRATION_DIR"
echo ""

# ---- Prerequisite check -----------------------------------------------------

if ! command -v psql &> /dev/null; then
    echo "[ERROR] psql not found. Install postgresql-client."
    exit 1
fi

if [ ! -d "$MIGRATION_DIR" ]; then
    echo "[ERROR] Migration directory not found: $MIGRATION_DIR"
    exit 1
fi

# ---- Run migrations ----------------------------------------------------------

export PGPASSWORD="${POSTGRES_ADMIN_PASSWORD:-postgres}"

APPLIED=0
FAILED=0

for sql_file in "$MIGRATION_DIR"/*.sql; do
    if [ ! -f "$sql_file" ]; then
        continue
    fi

    BASENAME=$(basename "$sql_file")
    echo -n "  -> $BASENAME ... "

    if psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" \
            -U "$POSTGRES_USER" -d "$POSTGRES_DATABASE" \
            -f "$sql_file" \
            --set ON_ERROR_STOP=0 \
            -q 2>/dev/null; then
        echo "OK"
        APPLIED=$((APPLIED + 1))
    else
        echo "WARN (may already exist)"
        FAILED=$((FAILED + 1))
    fi
done

unset PGPASSWORD

echo ""
echo "[Done] Applied: $APPLIED, Warnings: $FAILED"
