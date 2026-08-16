#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
COMMON_GIT_DIR="$(git -C "$ROOT" rev-parse --path-format=absolute --git-common-dir 2>/dev/null || true)"
SHARED_ROOT=""
if [ -n "$COMMON_GIT_DIR" ]; then
    SHARED_ROOT="$(cd "$COMMON_GIT_DIR/.." && pwd)"
fi

if [ -n "${PYTHON:-}" ]; then
    :
elif [ -x "$ROOT/.venv/bin/python" ]; then
    PYTHON="$ROOT/.venv/bin/python"
elif [ -n "$SHARED_ROOT" ] && [ -x "$SHARED_ROOT/.venv/bin/python" ]; then
    PYTHON="$SHARED_ROOT/.venv/bin/python"
else
    PYTHON="python"
fi

cd "$ROOT"
exec "$PYTHON" -m data_agent.metadata_fabric_otel_metrics "$@"
