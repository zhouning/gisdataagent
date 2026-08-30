#!/bin/bash
# Bind the deployment login to the NOLOGIN/NOINHERIT platform gateway role.
set -euo pipefail

runtime_role="${MIGRATION_RUNTIME_DB_ROLE:-agent_user}"
if [[ ! "$runtime_role" =~ ^[A-Za-z_][A-Za-z0-9_$]*$ ]]; then
  echo "Invalid MIGRATION_RUNTIME_DB_ROLE identifier" >&2
  exit 2
fi

python -m data_agent.platform_gateway_role --login-role "$runtime_role"
