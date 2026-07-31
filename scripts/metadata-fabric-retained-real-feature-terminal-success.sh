#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
common_git_dir="$(git -C "$repo_root" rev-parse --path-format=absolute --git-common-dir 2>/dev/null || true)"
shared_root=""
if [ -n "$common_git_dir" ]; then
    shared_root="$(cd "$common_git_dir/.." && pwd)"
fi

if [ -n "${PYTHON:-}" ]; then
    :
elif [ -x "$repo_root/.venv/bin/python" ]; then
    PYTHON="$repo_root/.venv/bin/python"
elif [ -n "$shared_root" ] && [ -x "$shared_root/.venv/bin/python" ]; then
    PYTHON="$shared_root/.venv/bin/python"
else
    PYTHON="python"
fi

cd "$repo_root"
exec "$PYTHON" -m data_agent.metadata_fabric_retained_real_feature_terminal_success "$@"
