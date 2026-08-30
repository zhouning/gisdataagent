"""Verify the live PostgreSQL privilege contract used by platform gateways.

Migration checksums prove that reviewed SQL was applied once. They cannot prove
that roles and ACLs still match that SQL. This module observes the current
catalog through the application login and emits redacted, deterministic
evidence. It never changes roles, grants, or database objects.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from .db_engine import get_engine

REPORT_SCHEMA = "gda.runtime_privilege_contract.v1"
DEFAULT_GATEWAY_ROLE = "gda_control_gateway"
DEFAULT_RUNTIME_ROLE = "agent_user"
VALID_PROFILES = frozenset({"development", "test", "staging", "production"})
PROFILE_ALIASES = {
    "dev": "development",
    "ci": "test",
    "stage": "staging",
    "prod": "production",
}
ROLE_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]{0,62}$")


@dataclass(frozen=True)
class PrivilegeRequirement:
    kind: Literal["schema", "table", "function"]
    schema: str
    name: str
    expected_privileges: tuple[str, ...]
    source_migration: str
    authority_surface: str
    identity_arguments: str | None = None

    @property
    def object_id(self) -> str:
        suffix = f"({self.identity_arguments})" if self.kind == "function" else ""
        return f"{self.kind}:{self.schema}.{self.name}{suffix}"


PRIVILEGE_REQUIREMENTS = (
    PrivilegeRequirement(
        kind="schema",
        schema="gda_control",
        name="gda_control",
        expected_privileges=("USAGE",),
        source_migration="094_platform_control_gateway",
        authority_surface="platform_gateway",
    ),
    PrivilegeRequirement(
        kind="table",
        schema="gda_control",
        name="data_product",
        expected_privileges=("INSERT", "SELECT", "UPDATE"),
        source_migration="100_data_product_registry",
        authority_surface="data_product_registry",
    ),
    PrivilegeRequirement(
        kind="table",
        schema="gda_control",
        name="data_product_version",
        expected_privileges=("INSERT", "SELECT"),
        source_migration="100_data_product_registry",
        authority_surface="data_product_registry",
    ),
    PrivilegeRequirement(
        kind="table",
        schema="gda_control",
        name="data_product_event",
        expected_privileges=("INSERT", "SELECT"),
        source_migration="100_data_product_registry",
        authority_surface="data_product_registry",
    ),
    PrivilegeRequirement(
        kind="table",
        schema="gda_control",
        name="data_incident",
        expected_privileges=("INSERT", "SELECT"),
        source_migration="098_platform_data_incident",
        authority_surface="platform_gateway_incident",
    ),
    PrivilegeRequirement(
        kind="table",
        schema="gda_control",
        name="data_incident_event",
        expected_privileges=("SELECT",),
        source_migration="098_platform_data_incident",
        authority_surface="platform_gateway_incident",
    ),
    PrivilegeRequirement(
        kind="function",
        schema="gda_control",
        name="transition_data_incident",
        identity_arguments="text, uuid, integer, text, text, text, jsonb",
        expected_privileges=("EXECUTE",),
        source_migration="098_platform_data_incident",
        authority_surface="platform_gateway_incident",
    ),
)

ROLE_QUERY = """
/* runtime_privilege_contract:roles */
WITH runtime_role AS (
    SELECT oid, rolname
      FROM pg_catalog.pg_roles
     WHERE rolname = :runtime_role
), gateway_role AS (
    SELECT oid, rolname, rolcanlogin, rolsuper, rolcreatedb, rolcreaterole,
           rolinherit, rolbypassrls
      FROM pg_catalog.pg_roles
     WHERE rolname = :gateway_role
)
SELECT current_user = :runtime_role AS observer_is_runtime_role,
       EXISTS (SELECT 1 FROM runtime_role) AS runtime_role_exists,
       EXISTS (SELECT 1 FROM gateway_role) AS gateway_role_exists,
       COALESCE((
           SELECT pg_catalog.pg_has_role(runtime_role.oid, gateway_role.oid, 'MEMBER')
             FROM runtime_role CROSS JOIN gateway_role
       ), FALSE) AS runtime_is_gateway_member,
       COALESCE((SELECT rolcanlogin FROM gateway_role), TRUE) AS gateway_can_login,
       COALESCE((SELECT rolsuper FROM gateway_role), TRUE) AS gateway_is_superuser,
       COALESCE((SELECT rolcreatedb FROM gateway_role), TRUE) AS gateway_can_create_db,
       COALESCE((SELECT rolcreaterole FROM gateway_role), TRUE) AS gateway_can_create_role,
       COALESCE((SELECT rolinherit FROM gateway_role), TRUE) AS gateway_inherits,
       COALESCE((SELECT rolbypassrls FROM gateway_role), TRUE) AS gateway_bypasses_rls
"""

SCHEMA_QUERY = """
/* runtime_privilege_contract:schema */
WITH target AS (
    SELECT n.oid, n.nspacl, n.nspowner
      FROM pg_catalog.pg_namespace AS n
     WHERE n.nspname = :schema_name
), grantee AS (
    SELECT oid FROM pg_catalog.pg_roles WHERE rolname = :gateway_role
)
SELECT EXISTS (SELECT 1 FROM target) AS object_exists,
       COALESCE((
           SELECT array_agg(privilege ORDER BY privilege)
             FROM (
                 SELECT DISTINCT upper(acl.privilege_type) AS privilege
                   FROM target
                   CROSS JOIN LATERAL pg_catalog.aclexplode(
                       COALESCE(target.nspacl, pg_catalog.acldefault('n', target.nspowner))
                   ) AS acl
                   JOIN grantee ON acl.grantee = grantee.oid
             ) AS direct_grants
       ), ARRAY[]::text[]) AS role_privileges,
       COALESCE((
           SELECT array_agg(privilege ORDER BY privilege)
             FROM (
                 SELECT DISTINCT upper(acl.privilege_type) AS privilege
                   FROM target
                   CROSS JOIN LATERAL pg_catalog.aclexplode(
                       COALESCE(target.nspacl, pg_catalog.acldefault('n', target.nspowner))
                   ) AS acl
                  WHERE acl.grantee = 0
             ) AS public_grants
       ), ARRAY[]::text[]) AS public_privileges
"""

TABLE_QUERY = """
/* runtime_privilege_contract:table */
WITH target AS (
    SELECT c.oid, c.relacl, c.relowner
      FROM pg_catalog.pg_class AS c
      JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace
     WHERE n.nspname = :schema_name
       AND c.relname = :object_name
       AND c.relkind IN ('r', 'p', 'v', 'm', 'f')
), grantee AS (
    SELECT oid FROM pg_catalog.pg_roles WHERE rolname = :gateway_role
)
SELECT EXISTS (SELECT 1 FROM target) AS object_exists,
       COALESCE((
           SELECT array_agg(privilege ORDER BY privilege)
             FROM (
                 SELECT DISTINCT upper(acl.privilege_type) AS privilege
                   FROM target
                   CROSS JOIN LATERAL pg_catalog.aclexplode(
                       COALESCE(target.relacl, pg_catalog.acldefault('r', target.relowner))
                   ) AS acl
                   JOIN grantee ON acl.grantee = grantee.oid
             ) AS direct_grants
       ), ARRAY[]::text[]) AS role_privileges,
       COALESCE((
           SELECT array_agg(privilege ORDER BY privilege)
             FROM (
                 SELECT DISTINCT upper(acl.privilege_type) AS privilege
                   FROM target
                   CROSS JOIN LATERAL pg_catalog.aclexplode(
                       COALESCE(target.relacl, pg_catalog.acldefault('r', target.relowner))
                   ) AS acl
                  WHERE acl.grantee = 0
             ) AS public_grants
       ), ARRAY[]::text[]) AS public_privileges
"""

FUNCTION_QUERY = """
/* runtime_privilege_contract:function */
WITH target AS (
    SELECT p.oid, p.proacl, p.proowner
      FROM pg_catalog.pg_proc AS p
      JOIN pg_catalog.pg_namespace AS n ON n.oid = p.pronamespace
     WHERE n.nspname = :schema_name
       AND p.proname = :object_name
       AND pg_catalog.oidvectortypes(p.proargtypes) = :identity_arguments
), grantee AS (
    SELECT oid FROM pg_catalog.pg_roles WHERE rolname = :gateway_role
)
SELECT EXISTS (SELECT 1 FROM target) AS object_exists,
       COALESCE((
           SELECT array_agg(privilege ORDER BY privilege)
             FROM (
                 SELECT DISTINCT upper(acl.privilege_type) AS privilege
                   FROM target
                   CROSS JOIN LATERAL pg_catalog.aclexplode(
                       COALESCE(target.proacl, pg_catalog.acldefault('f', target.proowner))
                   ) AS acl
                   JOIN grantee ON acl.grantee = grantee.oid
             ) AS direct_grants
       ), ARRAY[]::text[]) AS role_privileges,
       COALESCE((
           SELECT array_agg(privilege ORDER BY privilege)
             FROM (
                 SELECT DISTINCT upper(acl.privilege_type) AS privilege
                   FROM target
                   CROSS JOIN LATERAL pg_catalog.aclexplode(
                       COALESCE(target.proacl, pg_catalog.acldefault('f', target.proowner))
                   ) AS acl
                  WHERE acl.grantee = 0
             ) AS public_grants
       ), ARRAY[]::text[]) AS public_privileges
"""


def _canonical_sha256(value: object) -> str:
    rendered = json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(rendered).hexdigest()


def _normalize_profile(profile: str | None) -> str:
    normalized = (profile or "development").strip().lower()
    return PROFILE_ALIASES.get(normalized, normalized)


def _row(connection: Any, query: str, parameters: Mapping[str, Any]) -> dict[str, Any]:
    return dict(connection.execute(text(query), dict(parameters)).mappings().one())


def _privilege_values(value: Any) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return sorted({str(item).upper() for item in value})


def _contract_definition(
    requirements: Sequence[PrivilegeRequirement],
    *,
    runtime_role: str,
    gateway_role: str,
) -> dict[str, Any]:
    return {
        "runtime_role": runtime_role,
        "gateway_role": gateway_role,
        "gateway_role_attributes": {
            "can_login": False,
            "is_superuser": False,
            "can_create_db": False,
            "can_create_role": False,
            "inherits": False,
            "bypasses_rls": False,
        },
        "requirements": [
            {
                **asdict(requirement),
                "object_id": requirement.object_id,
                "expected_privileges": list(requirement.expected_privileges),
                "public_privileges": [],
            }
            for requirement in requirements
        ],
    }


def inspect_runtime_privilege_contract(
    connection: Any,
    *,
    profile: str = "development",
    runtime_role: str = DEFAULT_RUNTIME_ROLE,
    gateway_role: str = DEFAULT_GATEWAY_ROLE,
    requirements: Sequence[PrivilegeRequirement] = PRIVILEGE_REQUIREMENTS,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Return exact live role and ACL evidence from a read-only connection."""
    normalized_profile = _normalize_profile(profile)
    if normalized_profile not in VALID_PROFILES:
        raise ValueError("unsupported deployment profile")
    for role_name in (runtime_role, gateway_role):
        if not ROLE_NAME_PATTERN.fullmatch(role_name):
            raise ValueError("database role name is invalid")

    contract = _contract_definition(
        requirements,
        runtime_role=runtime_role,
        gateway_role=gateway_role,
    )
    contract_fingerprint = _canonical_sha256(contract)
    role_row = _row(
        connection,
        ROLE_QUERY,
        {"runtime_role": runtime_role, "gateway_role": gateway_role},
    )
    expected_role_values = contract["gateway_role_attributes"]
    actual_role_values = {
        "can_login": bool(role_row.get("gateway_can_login")),
        "is_superuser": bool(role_row.get("gateway_is_superuser")),
        "can_create_db": bool(role_row.get("gateway_can_create_db")),
        "can_create_role": bool(role_row.get("gateway_can_create_role")),
        "inherits": bool(role_row.get("gateway_inherits")),
        "bypasses_rls": bool(role_row.get("gateway_bypasses_rls")),
    }
    role_violations: list[str] = []
    if not role_row.get("observer_is_runtime_role"):
        role_violations.append("observer_role_mismatch")
    if not role_row.get("runtime_role_exists"):
        role_violations.append("missing_runtime_role")
    if not role_row.get("gateway_role_exists"):
        role_violations.append("missing_gateway_role")
    if not role_row.get("runtime_is_gateway_member"):
        role_violations.append("missing_gateway_membership")
    if actual_role_values != expected_role_values:
        role_violations.append("gateway_role_attribute_drift")

    observations: list[dict[str, Any]] = []
    drift: list[dict[str, Any]] = []
    for requirement in requirements:
        parameters = {
            "schema_name": requirement.schema,
            "object_name": requirement.name,
            "identity_arguments": requirement.identity_arguments,
            "gateway_role": gateway_role,
        }
        if requirement.kind == "schema":
            observed = _row(connection, SCHEMA_QUERY, parameters)
        elif requirement.kind == "table":
            observed = _row(connection, TABLE_QUERY, parameters)
        else:
            observed = _row(connection, FUNCTION_QUERY, parameters)

        actual = _privilege_values(observed.get("role_privileges"))
        public = _privilege_values(observed.get("public_privileges"))
        expected = sorted(requirement.expected_privileges)
        missing = sorted(set(expected) - set(actual))
        unexpected = sorted(set(actual) - set(expected))
        violations: list[str] = []
        if not observed.get("object_exists"):
            violations.append("missing_object")
        if missing:
            violations.append("missing_privilege")
        if unexpected:
            violations.append("excess_privilege")
        if public:
            violations.append("public_exposure")
        observation = {
            "object_id": requirement.object_id,
            "kind": requirement.kind,
            "object_exists": bool(observed.get("object_exists")),
            "expected_privileges": expected,
            "actual_privileges": actual,
            "missing_privileges": missing,
            "unexpected_privileges": unexpected,
            "public_privileges": public,
            "source_migration": requirement.source_migration,
            "authority_surface": requirement.authority_surface,
            "status": "in_sync" if not violations else "drifted",
            "violations": violations,
        }
        observations.append(observation)
        if violations:
            drift.append(
                {
                    "object_id": requirement.object_id,
                    "violations": violations,
                    "missing_privileges": missing,
                    "unexpected_privileges": unexpected,
                    "public_privileges": public,
                }
            )

    if role_violations:
        drift.insert(
            0,
            {
                "object_id": f"role:{runtime_role}->{gateway_role}",
                "violations": role_violations,
                "missing_privileges": [],
                "unexpected_privileges": [],
                "public_privileges": [],
            },
        )
    admitted = not drift
    stable = {
        "schema": REPORT_SCHEMA,
        "profile": normalized_profile,
        "contract_fingerprint": contract_fingerprint,
        "runtime_role": runtime_role,
        "gateway_role": gateway_role,
        "role_observation": {
            "observer_is_runtime_role": bool(role_row.get("observer_is_runtime_role")),
            "runtime_role_exists": bool(role_row.get("runtime_role_exists")),
            "gateway_role_exists": bool(role_row.get("gateway_role_exists")),
            "runtime_is_gateway_member": bool(role_row.get("runtime_is_gateway_member")),
            "expected_gateway_attributes": expected_role_values,
            "actual_gateway_attributes": actual_role_values,
            "status": "in_sync" if not role_violations else "drifted",
            "violations": role_violations,
        },
        "observations": observations,
        "drift": drift,
        "admission_allowed": admitted,
    }
    observed_at = generated_at or datetime.now(UTC)
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("generated_at must be timezone-aware")
    return {
        **stable,
        "generated_at": observed_at.isoformat(),
        "status": "in_sync" if admitted else "blocked",
        "read_only": True,
        "self_healed": False,
        "evidence_fingerprint": _canonical_sha256(stable),
    }


def build_runtime_privilege_report(
    *,
    profile: str,
    runtime_role: str,
    gateway_role: str = DEFAULT_GATEWAY_ROLE,
    engine: Any | None = None,
) -> dict[str, Any]:
    """Observe the configured PostgreSQL engine without changing live state."""
    active_engine = engine or get_engine()
    if active_engine is None:
        raise RuntimeError("database engine is not configured")
    if active_engine.dialect.name != "postgresql":
        raise RuntimeError("runtime privilege contract requires PostgreSQL")
    with active_engine.connect() as connection:
        connection.exec_driver_sql("SET TRANSACTION READ ONLY")
        return inspect_runtime_privilege_contract(
            connection,
            profile=profile,
            runtime_role=runtime_role,
            gateway_role=gateway_role,
        )


def _write_report(report: Mapping[str, Any], output: Path | None) -> None:
    rendered = json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True)
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


def _error_report(*, profile: str, error: BaseException) -> dict[str, Any]:
    stable = {
        "schema": REPORT_SCHEMA,
        "profile": _normalize_profile(profile),
        "status": "error",
        "admission_allowed": False,
        "read_only": True,
        "self_healed": False,
        "error_code": f"observation_failed:{type(error).__name__}",
    }
    return {
        **stable,
        "generated_at": datetime.now(UTC).isoformat(),
        "evidence_fingerprint": _canonical_sha256(stable),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--profile",
        default=os.environ.get("GDA_DEPLOYMENT_PROFILE", "development"),
    )
    parser.add_argument(
        "--runtime-role",
        default=(
            os.environ.get("MIGRATION_RUNTIME_DB_ROLE")
            or os.environ.get("POSTGRES_USER")
            or DEFAULT_RUNTIME_ROLE
        ),
    )
    parser.add_argument("--gateway-role", default=DEFAULT_GATEWAY_ROLE)
    parser.add_argument(
        "--observe-only",
        action="store_true",
        help="emit blocked evidence without failing the observation transport",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        report = build_runtime_privilege_report(
            profile=args.profile,
            runtime_role=args.runtime_role,
            gateway_role=args.gateway_role,
        )
    except (RuntimeError, ValueError, SQLAlchemyError) as exc:
        report = _error_report(profile=args.profile, error=exc)
    _write_report(report, args.output)
    return (
        0
        if args.observe_only or report.get("admission_allowed") is True
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
