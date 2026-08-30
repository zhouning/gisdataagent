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

if [ "$DRY_RUN" = false ] && ! command -v pg_dump &> /dev/null; then
    echo "[ERROR] pg_dump not found. Install postgresql-client."
    exit 1
fi

# ---- Prepare backup directory ------------------------------------------------

if [ "$DRY_RUN" = false ]; then
    mkdir -p "$BACKUP_DIR"
fi

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
FILENAME="${BACKUP_DIR}/gis_agent_${TIMESTAMP}.dump"

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
    echo "[DRY-RUN] Would create a custom-format dump at $FILENAME"
else
    if [ -n "${POSTGRES_ADMIN_PASSWORD:-}" ]; then
        export PGPASSWORD="$POSTGRES_ADMIN_PASSWORD"
    fi
    PARTIAL="${FILENAME}.partial"
    cleanup_partial() {
        rm -f "$PARTIAL"
    }
    trap cleanup_partial EXIT

    echo "[Backup] Dumping database..."
    pg_dump \
        -h "$POSTGRES_HOST" \
        -p "$POSTGRES_PORT" \
        -U "$POSTGRES_USER" \
        --format=custom \
        --no-owner \
        --no-acl \
        --file "$PARTIAL" \
        "$POSTGRES_DATABASE"
    mv "$PARTIAL" "$FILENAME"
    trap - EXIT

    unset PGPASSWORD || true

    SIZE=$(du -h "$FILENAME" | cut -f1)
    echo "[Backup] Created: $FILENAME ($SIZE)"
fi

# ---- Cleanup old backups -----------------------------------------------------

echo "[Cleanup] Removing backups older than $RETENTION_DAYS days..."
if [ "$DRY_RUN" = true ]; then
    find "$BACKUP_DIR" -name "gis_agent_*.dump" -mtime +"$RETENTION_DAYS" -print 2>/dev/null || true
else
    REMOVED=$(find "$BACKUP_DIR" -name "gis_agent_*.dump" -mtime +"$RETENTION_DAYS" -delete -print 2>/dev/null | wc -l)
    echo "[Cleanup] Removed $REMOVED old backup(s)."
fi

echo "[Notice] A dump is not recovery evidence; run the isolated recovery rehearsal."
echo "[Done]"
