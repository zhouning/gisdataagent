#!/bin/bash
# =============================================================================
# GIS Data Agent — Database Backup Script
# Usage: bash scripts/backup-db.sh [--dry-run]
# =============================================================================
set -euo pipefail

# ---- Configuration (from env or defaults) ------------------------------------

POSTGRES_HOST="${POSTGRES_HOST:-localhost}"
POSTGRES_PORT="${POSTGRES_PORT:-5433}"
POSTGRES_USER="${POSTGRES_ADMIN_USER:-postgres}"
POSTGRES_DATABASE="${POSTGRES_DATABASE:-gis_agent}"
BACKUP_DIR="${BACKUP_DIR:-./backups}"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-7}"
DRY_RUN=false

if [ "${1:-}" = "--dry-run" ]; then
    DRY_RUN=true
    echo "[DRY-RUN] No actual backup will be created."
fi

# ---- Prerequisite check -----------------------------------------------------

if ! command -v pg_dump &> /dev/null; then
    echo "[ERROR] pg_dump not found. Install postgresql-client."
    exit 1
fi

# ---- Prepare backup directory ------------------------------------------------

mkdir -p "$BACKUP_DIR"

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
FILENAME="${BACKUP_DIR}/gis_agent_${TIMESTAMP}.sql.gz"

echo "========================================="
echo " GIS Data Agent — Database Backup"
echo "========================================="
echo "Host:      $POSTGRES_HOST:$POSTGRES_PORT"
echo "Database:  $POSTGRES_DATABASE"
echo "Output:    $FILENAME"
echo "Retention: $RETENTION_DAYS days"
echo ""

# ---- Create backup -----------------------------------------------------------

if [ "$DRY_RUN" = true ]; then
    echo "[DRY-RUN] Would run: pg_dump -h $POSTGRES_HOST -p $POSTGRES_PORT -U $POSTGRES_USER -Fc $POSTGRES_DATABASE | gzip > $FILENAME"
else
    export PGPASSWORD="${POSTGRES_ADMIN_PASSWORD:-postgres}"

    echo "[Backup] Dumping database..."
    pg_dump -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -Fc "$POSTGRES_DATABASE" | gzip > "$FILENAME"

    unset PGPASSWORD

    SIZE=$(du -h "$FILENAME" | cut -f1)
    echo "[Backup] Created: $FILENAME ($SIZE)"
fi

# ---- Cleanup old backups -----------------------------------------------------

echo "[Cleanup] Removing backups older than $RETENTION_DAYS days..."
if [ "$DRY_RUN" = true ]; then
    find "$BACKUP_DIR" -name "gis_agent_*.sql.gz" -mtime +"$RETENTION_DAYS" -print 2>/dev/null || true
else
    REMOVED=$(find "$BACKUP_DIR" -name "gis_agent_*.sql.gz" -mtime +"$RETENTION_DAYS" -delete -print 2>/dev/null | wc -l)
    echo "[Cleanup] Removed $REMOVED old backup(s)."
fi

echo "[Done]"
