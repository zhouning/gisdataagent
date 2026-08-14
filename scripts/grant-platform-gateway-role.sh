#!/usr/bin/env bash
# Bind the application login to the NOLOGIN gateway role without inheritance.
set -euo pipefail

: "${MIGRATION_RUNTIME_DB_ROLE:?MIGRATION_RUNTIME_DB_ROLE is required}"
: "${POSTGRES_USER:?POSTGRES_USER is required}"
: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is required}"

export PGPASSWORD="$POSTGRES_PASSWORD"
trap 'unset PGPASSWORD' EXIT

psql \
  --no-psqlrc \
  --host "${POSTGRES_HOST:-localhost}" \
  --port "${POSTGRES_PORT:-5432}" \
  --username "$POSTGRES_USER" \
  --dbname "${POSTGRES_DATABASE:-gis_agent}" \
  --set ON_ERROR_STOP=1 \
  --set runtime_role="$MIGRATION_RUNTIME_DB_ROLE" <<'SQL'
SELECT
  count(*) = 1
  AND bool_and(rolcanlogin)
  AND bool_and(NOT rolsuper)
  AND bool_and(NOT rolcreatedb)
  AND bool_and(NOT rolcreaterole)
  AND bool_and(NOT rolbypassrls) AS runtime_role_is_safe
FROM pg_roles
WHERE rolname = :'runtime_role'
\gset

SELECT
  count(*) = 1
  AND bool_and(NOT rolcanlogin)
  AND bool_and(NOT rolsuper)
  AND bool_and(NOT rolcreatedb)
  AND bool_and(NOT rolcreaterole)
  AND bool_and(NOT rolinherit)
  AND bool_and(NOT rolbypassrls) AS gateway_role_is_safe
FROM pg_roles
WHERE rolname = 'gda_control_gateway'
\gset

\if :runtime_role_is_safe
\else
  \echo 'runtime database role is missing or privileged'
  \quit 3
\endif

\if :gateway_role_is_safe
\else
  \echo 'platform gateway role is missing or privileged'
  \quit 4
\endif

GRANT gda_control_gateway TO :"runtime_role"
  WITH INHERIT FALSE, SET TRUE;

SELECT
  count(*) = 1
  AND bool_and(NOT membership.inherit_option)
  AND bool_and(membership.set_option) AS gateway_membership_is_safe
FROM pg_auth_members AS membership
JOIN pg_roles AS granted_role
  ON granted_role.oid = membership.roleid
JOIN pg_roles AS member_role
  ON member_role.oid = membership.member
WHERE granted_role.rolname = 'gda_control_gateway'
  AND member_role.rolname = :'runtime_role'
\gset

\if :gateway_membership_is_safe
  \echo 'platform gateway membership verified'
\else
  \echo 'platform gateway membership verification failed'
  \quit 5
\endif
SQL
