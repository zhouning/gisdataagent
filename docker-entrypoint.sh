#!/bin/bash
set -e

echo "========================================="
echo " GIS Data Agent — Container Entrypoint"
echo "========================================="

# -----------------------------------------------------------------------
# 1. Wait for PostgreSQL
# -----------------------------------------------------------------------
MAX_RETRIES=30
RETRY_INTERVAL=2
for i in $(seq 1 $MAX_RETRIES); do
    if pg_isready -h "${POSTGRES_HOST:-db}" -p "${POSTGRES_PORT:-5432}" -q; then
        echo "[OK] PostgreSQL is ready."
        break
    fi
    echo "[WAIT] PostgreSQL not ready (attempt $i/$MAX_RETRIES)..."
    sleep $RETRY_INTERVAL
done

if ! pg_isready -h "${POSTGRES_HOST:-db}" -p "${POSTGRES_PORT:-5432}" -q; then
    echo "[ERROR] PostgreSQL did not become ready in time. Starting anyway..."
fi

# -----------------------------------------------------------------------
# 2. Run database migrations (if admin credentials provided)
# -----------------------------------------------------------------------
if [ -n "$POSTGRES_ADMIN_USER" ] && [ -n "$POSTGRES_ADMIN_PASSWORD" ]; then
    echo "[MIGRATE] Running SQL migrations..."
    export PGPASSWORD="$POSTGRES_ADMIN_PASSWORD"
    MIGRATION_DIR="/app/data_agent/migrations"
    if [ -d "$MIGRATION_DIR" ]; then
        for sql_file in "$MIGRATION_DIR"/*.sql; do
            if [ -f "$sql_file" ]; then
                echo "  -> $(basename "$sql_file")"
                psql -h "${POSTGRES_HOST:-db}" -p "${POSTGRES_PORT:-5432}" \
                     -U "$POSTGRES_ADMIN_USER" -d "${POSTGRES_DATABASE:-gis_agent}" \
                     -f "$sql_file" \
                     --set ON_ERROR_STOP=0 \
                     -q 2>/dev/null || true
            fi
        done
        echo "[MIGRATE] Done."
    fi
    unset PGPASSWORD
else
    echo "[MIGRATE] Skipped (POSTGRES_ADMIN_USER not set)."
fi

# -----------------------------------------------------------------------
# 3. Generate data_agent/.env if it does not exist
# -----------------------------------------------------------------------
ENV_FILE="/app/data_agent/.env"
if [ ! -f "$ENV_FILE" ]; then
    echo "[ENV] Generating $ENV_FILE from environment variables..."
    cat > "$ENV_FILE" <<ENVEOF
export POSTGRES_HOST="${POSTGRES_HOST:-db}"
export POSTGRES_PORT="${POSTGRES_PORT:-5432}"
export POSTGRES_DATABASE="${POSTGRES_DATABASE:-gis_agent}"
export POSTGRES_USER="${POSTGRES_USER:-agent_user}"
export POSTGRES_PASSWORD="${POSTGRES_PASSWORD}"
GOOGLE_GENAI_USE_VERTEXAI=${GOOGLE_GENAI_USE_VERTEXAI:-}
GOOGLE_CLOUD_PROJECT=${GOOGLE_CLOUD_PROJECT:-}
GOOGLE_CLOUD_LOCATION=${GOOGLE_CLOUD_LOCATION:-global}
GOOGLE_API_KEY=${GOOGLE_API_KEY:-}
export GAODE_API_KEY=${GAODE_API_KEY:-}
CHAINLIT_AUTH_SECRET="${CHAINLIT_AUTH_SECRET}"
export DYNAMIC_PLANNER=${DYNAMIC_PLANNER:-true}
ENVEOF

    # Optional: Huawei OBS
    if [ -n "$HUAWEI_OBS_AK" ]; then
        cat >> "$ENV_FILE" <<OBSEOF
export HUAWEI_OBS_AK="${HUAWEI_OBS_AK}"
export HUAWEI_OBS_SK="${HUAWEI_OBS_SK}"
export HUAWEI_OBS_SERVER="${HUAWEI_OBS_SERVER}"
export HUAWEI_OBS_BUCKET="${HUAWEI_OBS_BUCKET}"
OBSEOF
    fi

    # Optional: OAuth
    if [ -n "$OAUTH_GOOGLE_CLIENT_ID" ]; then
        cat >> "$ENV_FILE" <<OAEOF
OAUTH_GOOGLE_CLIENT_ID=${OAUTH_GOOGLE_CLIENT_ID}
OAUTH_GOOGLE_CLIENT_SECRET=${OAUTH_GOOGLE_CLIENT_SECRET}
OAEOF
    fi

    # Optional: Tianditu
    if [ -n "$TIANDITU_TOKEN" ]; then
        echo "TIANDITU_TOKEN=${TIANDITU_TOKEN}" >> "$ENV_FILE"
    fi

    # Optional: Usage limits
    [ -n "$DAILY_ANALYSIS_LIMIT" ] && echo "DAILY_ANALYSIS_LIMIT=${DAILY_ANALYSIS_LIMIT}" >> "$ENV_FILE"
    [ -n "$MONTHLY_TOKEN_LIMIT" ] && echo "MONTHLY_TOKEN_LIMIT=${MONTHLY_TOKEN_LIMIT}" >> "$ENV_FILE"
    [ -n "$AUDIT_LOG_RETENTION_DAYS" ] && echo "AUDIT_LOG_RETENTION_DAYS=${AUDIT_LOG_RETENTION_DAYS}" >> "$ENV_FILE"

    echo "[ENV] Generated."
else
    echo "[ENV] $ENV_FILE already exists, skipping generation."
fi

# -----------------------------------------------------------------------
# 4. Start Chainlit
# -----------------------------------------------------------------------
echo "[START] Launching Chainlit on 0.0.0.0:${PORT:-8080}..."
export PYTHONPATH="/app:${PYTHONPATH}"
exec /app/.venv/bin/chainlit run /app/data_agent/app.py --host 0.0.0.0 --port ${PORT:-8080}
