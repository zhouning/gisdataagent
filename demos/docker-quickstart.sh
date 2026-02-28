#!/bin/bash
# =============================================================================
# GIS Data Agent — Docker Quick Start
# =============================================================================
# One-command setup: starts PostgreSQL + PostGIS + Chainlit app
# Then runs a demo scenario to verify everything works.
#
# Usage:
#   chmod +x demos/docker-quickstart.sh
#   ./demos/docker-quickstart.sh
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "=========================================="
echo " GIS Data Agent — Docker Quick Start"
echo "=========================================="

# Step 1: Start services
echo "[1/4] Starting Docker containers..."
cd "$PROJECT_DIR"
docker-compose up -d

# Step 2: Wait for health check
echo "[2/4] Waiting for services to be ready..."
MAX_WAIT=60
WAITED=0
until docker-compose exec -T db pg_isready -U postgres > /dev/null 2>&1; do
    sleep 2
    WAITED=$((WAITED + 2))
    if [ $WAITED -ge $MAX_WAIT ]; then
        echo "ERROR: Database did not become ready within ${MAX_WAIT}s"
        docker-compose logs db
        exit 1
    fi
done
echo "  Database ready (${WAITED}s)"

# Wait for app to be ready
sleep 5
echo "  Application starting..."

# Step 3: Check app health
echo "[3/4] Verifying application..."
APP_URL="http://localhost:8000"
if curl -s -o /dev/null -w "%{http_code}" "$APP_URL" | grep -q "200\|302"; then
    echo "  Application is running at $APP_URL"
else
    echo "  WARNING: Application may still be starting up"
fi

# Step 4: Print access info
echo ""
echo "=========================================="
echo " Access Information"
echo "=========================================="
echo "  Web UI:  $APP_URL"
echo "  Login:   admin / admin123"
echo ""
echo "  To run a demo:"
echo "    python demos/demo_retail_site_selection.py"
echo "    python demos/demo_land_governance.py"
echo "    python demos/demo_population_analysis.py"
echo ""
echo "  To stop:"
echo "    docker-compose down"
echo "=========================================="
