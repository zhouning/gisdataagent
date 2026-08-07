"""Data classification and spatial anonymization API routes."""

from __future__ import annotations

import asyncio
import os
import re
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from ..audit_logger import (
    ACTION_ANONYMIZATION_VERIFY,
    ACTION_DATA_ANONYMIZE,
    ACTION_SECURITY_EVENT_RECONCILE,
    record_audit,
)
from ..database_tools import _inject_user_context
from ..platform_gateway import (
    GatewayConfigurationError,
    GatewayConflictError,
    GatewayUnavailableError,
    GatewayValidationError,
    PlatformGateway,
)
from ..security_event_ledger import SecurityEventLedger, SecurityEventLedgerError
from ..security_event_reconciliation import (
    SecurityEventReconciliationError,
    reconcile_security_event_outcomes,
)
from ..spatial_anonymization_run import (
    SpatialAnonymizationRequest,
    SpatialAnonymizationRunSpec,
)
from ..user_context import current_tenant_id
from .helpers import _get_user_from_request, _require_admin, _set_user_context

_IDENTIFIER_RE = re.compile(r"^[^\W\d]\w*$", re.UNICODE)
_TENANT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_ANONYMIZATION_ROLES = frozenset({"admin", "analyst"})
_LEVELS = frozenset({"L1", "L2", "L3", "L4"})
_DATA_TYPES = frozenset({"point", "polygon"})
_AGG_STRATEGIES = frozenset({"mode", "area_weighted", "topk"})


class _RequestValidationError(ValueError):
    pass


class _DatabaseUnavailable(RuntimeError):
    pass


def _validate_identifier(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise _RequestValidationError(f"{field} must be a string")
    identifier = value.strip()
    if (
        not identifier
        or len(identifier.encode("utf-8")) > 63
        or not _IDENTIFIER_RE.fullmatch(identifier)
    ):
        raise _RequestValidationError(f"invalid {field}")
    return identifier


def _parse_table_reference(value: Any, field: str) -> tuple[str, str]:
    if not isinstance(value, str):
        raise _RequestValidationError(f"{field} must be a string")
    parts = [part.strip() for part in value.split(".")]
    if len(parts) == 1:
        return "public", _validate_identifier(parts[0], field)
    if len(parts) == 2:
        return (
            _validate_identifier(parts[0], f"{field} schema"),
            _validate_identifier(parts[1], field),
        )
    raise _RequestValidationError(f"invalid {field}")


def _validate_identifier_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or len(value) > 100:
        raise _RequestValidationError(f"{field} must be a list of at most 100 columns")
    return [_validate_identifier(item, field) for item in value]


def _bounded_integer(
    value: Any,
    field: str,
    *,
    minimum: int,
    maximum: int,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise _RequestValidationError(f"{field} must be an integer")
    if not minimum <= value <= maximum:
        raise _RequestValidationError(
            f"{field} must be between {minimum} and {maximum}"
        )
    return value


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _audit(
    request: Request,
    username: str,
    action: str,
    status: str,
    **details: Any,
) -> None:
    record_audit(
        username,
        action,
        status=status,
        ip_address=_client_ip(request),
        details=details,
    )


def _append_security_event(
    *,
    tenant_id: str,
    attempt_id: UUID,
    phase: str,
    action: str,
    outcome: str,
    username: str,
    resource_ref: str,
    reason: str,
    details: dict[str, Any] | None = None,
):
    return SecurityEventLedger().append(
        tenant_id=tenant_id,
        attempt_id=attempt_id,
        phase=phase,
        action=action,
        outcome=outcome,
        actor_subject=f"human:{username}",
        resource_ref=resource_ref,
        reason=reason,
        details=details or {},
    )


def _record_security_denial(
    *,
    tenant_id: str,
    attempt_id: UUID,
    action: str,
    username: str,
    resource_ref: str,
    reason: str,
    details: dict[str, Any] | None = None,
) -> bool:
    if not tenant_id:
        return False
    try:
        _append_security_event(
            tenant_id=tenant_id,
            attempt_id=attempt_id,
            phase="denied",
            action=action,
            outcome="denied",
            username=username,
            resource_ref=resource_ref,
            reason=reason,
            details=details,
        )
        return True
    except Exception:
        return False


def _security_resource_ref(
    source_schema: str,
    source_table: str,
    output_schema: str | None = None,
    output_table: str | None = None,
) -> str:
    source = f"postgis://{source_schema}/{source_table}"
    if output_schema and output_table:
        return f"{source}->postgis://{output_schema}/{output_table}"
    return source


def _query_integer(
    request: Request,
    name: str,
    default: int,
    *,
    minimum: int,
    maximum: int,
) -> int:
    raw = request.query_params.get(name)
    try:
        value = default if raw is None else int(raw)
    except (TypeError, ValueError) as error:
        raise _RequestValidationError(f"{name} must be an integer") from error
    return _bounded_integer(value, name, minimum=minimum, maximum=maximum)


def _attempt_id(value: Any, *, required: bool = False) -> UUID | None:
    if value in (None, "") and not required:
        return None
    try:
        return UUID(str(value))
    except (TypeError, ValueError, AttributeError) as error:
        raise _RequestValidationError("attempt_id must be a UUID") from error


def _reconciliation_payload(results) -> dict[str, Any]:
    items = [result.as_dict() for result in results]
    return {
        "items": items,
        "summary": dict(Counter(item["status"] for item in items)),
        "total": len(items),
    }


def _engine():
    from ..db_engine import get_engine

    engine = get_engine()
    if not engine:
        raise _DatabaseUnavailable("database unavailable")
    return engine


def _lookup_accessible_postgis_asset(
    schema: str,
    table_name: str,
    username: str,
    role: str,
) -> dict[str, Any] | None:
    """Resolve a physical PostGIS table through the governed asset catalog."""
    qualified_name = f"{schema}.{table_name}"
    with _engine().connect() as conn:
        _inject_user_context(conn)
        row = conn.execute(
            text("""
                SELECT id, asset_name, owner_username, is_shared,
                       technical_metadata->'storage'->>'postgis_table' AS postgis_table
                FROM agent_data_assets
                WHERE technical_metadata->'storage'->>'backend' = 'postgis'
                  AND (
                    technical_metadata->'storage'->>'postgis_table' IN (:qualified, :table_name)
                    OR asset_name IN (:qualified, :table_name)
                  )
                  AND (
                    :is_admin
                    OR owner_username = :username
                    OR is_shared = TRUE
                  )
                ORDER BY
                  CASE WHEN technical_metadata->'storage'->>'postgis_table' = :qualified
                       THEN 0 ELSE 1 END,
                  updated_at DESC,
                  id DESC
                LIMIT 1
            """),
            {
                "qualified": qualified_name,
                "table_name": table_name,
                "username": username,
                "is_admin": role == "admin",
            },
        ).fetchone()
    if not row:
        return None
    return {
        "id": row[0],
        "name": row[1],
        "owner": row[2],
        "shared": bool(row[3]),
        "postgis_table": row[4],
    }


def _physical_table_exists(schema: str, table_name: str) -> bool:
    with _engine().connect() as conn:
        _inject_user_context(conn)
        return bool(
            conn.execute(
                text("SELECT to_regclass(:qualified_name)"),
                {"qualified_name": f"{schema}.{table_name}"},
            ).scalar()
        )


def _platform_gateway() -> PlatformGateway:
    return PlatformGateway()


def _required_uuid_environment(name: str) -> UUID:
    raw = os.environ.get(name)
    if not raw:
        raise GatewayConfigurationError(
            "spatial anonymization admission profile is incomplete"
        )
    try:
        return UUID(raw)
    except ValueError as exc:
        raise GatewayConfigurationError(
            "spatial anonymization admission profile is invalid"
        ) from exc


def _spatial_anonymization_run_spec(
    operation_request: SpatialAnonymizationRequest,
) -> SpatialAnonymizationRunSpec:
    workload_subject = os.environ.get("GDA_SPATIAL_ANONYMIZATION_WORKLOAD_SUBJECT") or (
        os.environ.get("GDA_DATAOPS_MANUAL_WORKLOAD_SUBJECT")
    )
    policy_version_ref = os.environ.get(
        "GDA_SPATIAL_ANONYMIZATION_POLICY_VERSION_REF"
    ) or os.environ.get("GDA_DATAOPS_MANUAL_POLICY_VERSION_REF")
    policy_evaluator = os.environ.get(
        "GDA_SPATIAL_ANONYMIZATION_POLICY_EVALUATOR_SUBJECT"
    ) or os.environ.get("GDA_DATAOPS_MANUAL_POLICY_EVALUATOR_SUBJECT")
    if not workload_subject or not policy_version_ref or not policy_evaluator:
        raise GatewayConfigurationError(
            "spatial anonymization admission profile is incomplete"
        )
    raw_roles = os.environ.get(
        "GDA_SPATIAL_ANONYMIZATION_WORKLOAD_ROLES"
    ) or os.environ.get("GDA_DATAOPS_MANUAL_WORKLOAD_ROLES", "platform_operator")
    config_fingerprint = os.environ.get(
        "GDA_SPATIAL_ANONYMIZATION_CONFIG_FINGERPRINT"
    )
    try:
        return SpatialAnonymizationRunSpec(
            request=operation_request,
            definition_version_id=_required_uuid_environment(
                "GDA_SPATIAL_ANONYMIZATION_DEFINITION_VERSION_ID"
            ),
            execution_plan_artifact_id=_required_uuid_environment(
                "GDA_SPATIAL_ANONYMIZATION_EXECUTION_PLAN_ARTIFACT_ID"
            ),
            workload_subject_id=workload_subject.removeprefix("workload:"),
            workload_roles=tuple(
                role.strip() for role in raw_roles.split(",") if role.strip()
            ),
            purpose=os.environ.get(
                "GDA_SPATIAL_ANONYMIZATION_PURPOSE",
                "produce a governed anonymized spatial output",
            ),
            policy_version_ref=policy_version_ref,
            policy_evaluator_subject=policy_evaluator,
            policy_ttl_seconds=int(
                os.environ.get(
                    "GDA_SPATIAL_ANONYMIZATION_POLICY_TTL_SECONDS",
                    os.environ.get("GDA_DATAOPS_MANUAL_POLICY_TTL_SECONDS", "86400"),
                )
            ),
            config_fingerprint=config_fingerprint,
            invocation_owner_ref=os.environ.get(
                "GDA_SPATIAL_ANONYMIZATION_INVOCATION_OWNER_REF",
                os.environ.get(
                    "GDA_DATAOPS_MANUAL_INVOCATION_OWNER_REF", "team:data-platform"
                ),
            ),
            request_owner_ref=os.environ.get(
                "GDA_SPATIAL_ANONYMIZATION_REQUEST_OWNER_REF",
                "team:data-governance",
            ),
        )
    except (TypeError, ValueError) as exc:
        raise GatewayConfigurationError(
            "spatial anonymization admission profile is invalid"
        ) from exc


def _normalized_anonymization_parameters(body: dict[str, Any]) -> dict[str, Any]:
    source_schema, source_table = _parse_table_reference(
        body.get("source_table", ""), "source_table"
    )
    output_schema, output_table = _parse_table_reference(
        body.get("output_table", ""), "output_table"
    )
    if output_schema != "public":
        raise _RequestValidationError("output_table schema must be public")
    level = body.get("level", "L3")
    data_type = body.get("data_type", "polygon")
    if level not in _LEVELS:
        raise _RequestValidationError("level must be one of L1, L2, L3, L4")
    if data_type not in _DATA_TYPES:
        raise _RequestValidationError("data_type must be point or polygon")
    values: dict[str, Any] = {
        "source_schema": source_schema,
        "source_table": source_table,
        "output_schema": output_schema,
        "output_table": output_table,
        "level": level,
        "data_type": data_type,
        "k_anonymity": _bounded_integer(
            body.get("k_anonymity", 5),
            "k_anonymity",
            minimum=2,
            maximum=1000,
        ),
    }
    if data_type == "point":
        values.update(
            {
                "category_column": _validate_identifier(
                    body.get("category_column", "类型"), "category_column"
                ),
                "top_k_categories": _bounded_integer(
                    body.get("top_k_categories", 5),
                    "top_k_categories",
                    minimum=1,
                    maximum=100,
                ),
            }
        )
        return values

    keep_attrs = _validate_identifier_list(
        body.get("keep_attrs", ["dlmc", "tbmj"]), "keep_attrs"
    )
    dp_numeric_fields = body.get("dp_numeric_fields")
    if dp_numeric_fields is not None:
        dp_numeric_fields = _validate_identifier_list(
            dp_numeric_fields, "dp_numeric_fields"
        )
    else:
        dp_numeric_fields = []
    agg_strategy = body.get("agg_strategy", "area_weighted")
    if agg_strategy not in _AGG_STRATEGIES:
        raise _RequestValidationError(
            "agg_strategy must be mode, area_weighted, or topk"
        )
    dp_epsilon = body.get("dp_epsilon")
    if dp_epsilon is not None:
        if isinstance(dp_epsilon, bool) or not isinstance(dp_epsilon, (int, float)):
            raise _RequestValidationError("dp_epsilon must be a number")
        dp_epsilon = float(dp_epsilon)
        if not 0.01 <= dp_epsilon <= 10.0:
            raise _RequestValidationError("dp_epsilon must be between 0.01 and 10")
    if (dp_epsilon is None) != (not dp_numeric_fields):
        raise _RequestValidationError(
            "dp_epsilon and dp_numeric_fields must be provided together"
        )
    values.update(
        {
            "keep_attrs": keep_attrs,
            "agg_strategy": agg_strategy,
            "dp_epsilon": dp_epsilon,
            "dp_numeric_fields": dp_numeric_fields,
        }
    )
    return values


async def _api_classification_summary(request: Request):
    """List sensitivity labels for assets visible to the current user."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    username, role = _set_user_context(user)
    try:
        with _engine().connect() as conn:
            _inject_user_context(conn)
            rows = conn.execute(text("""
                SELECT id, asset_name,
                       business_metadata->'classification'->>'sensitivity' AS sensitivity,
                       business_metadata->'classification'->>'category' AS category,
                       business_metadata->'semantic'->>'description' AS description,
                       technical_metadata->'structure'->>'feature_count' AS feature_count,
                       technical_metadata->'spatial'->>'crs' AS crs,
                       lineage_metadata->'upstream'->>'transform_tool' AS transform_tool,
                       lineage_metadata->'upstream'->'source_tables' AS source_tables,
                       technical_metadata->'storage'->>'postgis_table' AS postgis_table,
                       owner_username, is_shared
                FROM agent_data_assets
                WHERE :is_admin OR owner_username = :username OR is_shared = TRUE
                ORDER BY
                  CASE business_metadata->'classification'->>'sensitivity'
                    WHEN 'secret' THEN 1 WHEN 'restricted' THEN 2
                    WHEN 'confidential' THEN 3 WHEN 'internal' THEN 4
                    WHEN 'public' THEN 5 ELSE 6
                  END, asset_name
            """), {
                "username": username,
                "is_admin": role == "admin",
            }).fetchall()
            assets = []
            for r in rows:
                assets.append({
                    "id": r[0], "name": r[1],
                    "sensitivity": r[2] or "unclassified",
                    "category": r[3] or "",
                    "description": r[4] or "",
                    "feature_count": r[5],
                    "crs": r[6],
                    "derived_from": r[7],
                    "source_tables": r[8],
                    "postgis_table": r[9],
                    "owner": r[10],
                    "shared": bool(r[11]),
                })
            level_counts = Counter(a["sensitivity"] for a in assets)
            return JSONResponse({
                "assets": assets,
                "summary": dict(level_counts),
                "total": len(assets),
            })
    except _DatabaseUnavailable:
        return JSONResponse({"error": "database unavailable"}, status_code=503)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def _api_classification_anonymize(request: Request):
    """Run grid anonymization for a governed, accessible PostGIS asset."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    username, role = _set_user_context(user)
    tenant_id = current_tenant_id.get().strip()
    attempt_id = uuid4()
    resource_ref = "api://classification/anonymize"
    if role not in _ANONYMIZATION_ROLES:
        security_recorded = _record_security_denial(
            tenant_id=tenant_id,
            attempt_id=attempt_id,
            action=ACTION_DATA_ANONYMIZE,
            username=username,
            resource_ref=resource_ref,
            reason="role_not_allowed",
            details={"role": role},
        )
        _audit(
            request,
            username,
            ACTION_DATA_ANONYMIZE,
            "denied",
            reason="role_not_allowed",
            role=role,
            attempt_id=str(attempt_id),
            security_event_recorded=security_recorded,
        )
        return JSONResponse({"error": "admin or analyst role required"}, status_code=403)
    if not _TENANT_ID_RE.fullmatch(tenant_id):
        _audit(
            request,
            username,
            ACTION_DATA_ANONYMIZE,
            "denied",
            reason="tenant_context_required",
            attempt_id=str(attempt_id),
        )
        return JSONResponse(
            {"error": "valid tenant context required"},
            status_code=403,
        )

    try:
        try:
            body = await request.json()
        except (UnicodeDecodeError, ValueError) as error:
            raise _RequestValidationError("invalid JSON") from error
        if not isinstance(body, dict):
            raise _RequestValidationError("JSON object required")

        source_schema, source_table = _parse_table_reference(
            body.get("source_table", ""), "source_table"
        )
        output_schema, output_table = _parse_table_reference(
            body.get("output_table", ""), "output_table"
        )
        if output_schema != "public":
            raise _RequestValidationError("output_table schema must be public")

        level = body.get("level", "L3")
        data_type = body.get("data_type", "polygon")
        if level not in _LEVELS:
            raise _RequestValidationError("level must be one of L1, L2, L3, L4")
        if data_type not in _DATA_TYPES:
            raise _RequestValidationError("data_type must be point or polygon")
        k_anonymity = _bounded_integer(
            body.get("k_anonymity", 5),
            "k_anonymity",
            minimum=2,
            maximum=1000,
        )

        operation = None
        operation_kwargs: dict[str, Any]
        if data_type == "point":
            from ..grid_anonymize import poi_grid_aggregate_pg

            category_column = _validate_identifier(
                body.get("category_column", "类型"), "category_column"
            )
            top_k_categories = _bounded_integer(
                body.get("top_k_categories", 5),
                "top_k_categories",
                minimum=1,
                maximum=100,
            )
            operation = poi_grid_aggregate_pg
            operation_kwargs = {
                "source_table": source_table,
                "output_table": output_table,
                "source_schema": source_schema,
                "output_schema": output_schema,
                "category_column": category_column,
                "level": level,
                "k_anonymity": k_anonymity,
                "top_k_categories": top_k_categories,
                "register_lineage": True,
                "security_tenant_id": tenant_id,
                "security_attempt_id": str(attempt_id),
            }
        else:
            from ..grid_anonymize import grid_anonymize_pg

            keep_attrs = _validate_identifier_list(
                body.get("keep_attrs", ["dlmc", "tbmj"]), "keep_attrs"
            )
            dp_numeric_fields = body.get("dp_numeric_fields")
            if dp_numeric_fields is not None:
                dp_numeric_fields = _validate_identifier_list(
                    dp_numeric_fields, "dp_numeric_fields"
                )
            agg_strategy = body.get("agg_strategy", "area_weighted")
            if agg_strategy not in _AGG_STRATEGIES:
                raise _RequestValidationError(
                    "agg_strategy must be mode, area_weighted, or topk"
                )
            dp_epsilon = body.get("dp_epsilon")
            if dp_epsilon is not None:
                if isinstance(dp_epsilon, bool) or not isinstance(
                    dp_epsilon, (int, float)
                ):
                    raise _RequestValidationError("dp_epsilon must be a number")
                dp_epsilon = float(dp_epsilon)
                if not 0.01 <= dp_epsilon <= 10.0:
                    raise _RequestValidationError(
                        "dp_epsilon must be between 0.01 and 10"
                    )
            operation = grid_anonymize_pg
            operation_kwargs = {
                "source_table": source_table,
                "output_table": output_table,
                "source_schema": source_schema,
                "output_schema": output_schema,
                "level": level,
                "keep_attrs": keep_attrs,
                "agg_strategy": agg_strategy,
                "k_anonymity": k_anonymity,
                "dp_epsilon": dp_epsilon,
                "dp_numeric_fields": dp_numeric_fields,
                "random_offset": True,
                "register_lineage": True,
                "security_tenant_id": tenant_id,
                "security_attempt_id": str(attempt_id),
            }

        resource_ref = _security_resource_ref(
            source_schema,
            source_table,
            output_schema,
            output_table,
        )

        source_asset = _lookup_accessible_postgis_asset(
            source_schema, source_table, username, role
        )
        if source_asset is None:
            security_recorded = _record_security_denial(
                tenant_id=tenant_id,
                attempt_id=attempt_id,
                action=ACTION_DATA_ANONYMIZE,
                username=username,
                resource_ref=resource_ref,
                reason="source_asset_not_accessible",
                details={
                    "source_table": f"{source_schema}.{source_table}",
                    "output_table": f"{output_schema}.{output_table}",
                },
            )
            _audit(
                request,
                username,
                ACTION_DATA_ANONYMIZE,
                "denied",
                reason="source_asset_not_accessible",
                source_table=f"{source_schema}.{source_table}",
                output_table=f"{output_schema}.{output_table}",
                attempt_id=str(attempt_id),
                security_event_recorded=security_recorded,
            )
            return JSONResponse(
                {"error": "source asset not found or access denied"},
                status_code=403,
            )

        if _physical_table_exists(output_schema, output_table):
            security_recorded = _record_security_denial(
                tenant_id=tenant_id,
                attempt_id=attempt_id,
                action=ACTION_DATA_ANONYMIZE,
                username=username,
                resource_ref=resource_ref,
                reason="output_table_exists",
                details={"source_asset_id": source_asset["id"]},
            )
            _audit(
                request,
                username,
                ACTION_DATA_ANONYMIZE,
                "denied",
                reason="output_table_exists",
                source_asset_id=source_asset["id"],
                output_table=f"{output_schema}.{output_table}",
                attempt_id=str(attempt_id),
                security_event_recorded=security_recorded,
            )
            return JSONResponse(
                {"error": "output table already exists; choose a new name"},
                status_code=409,
            )

        try:
            admission_event = _append_security_event(
                tenant_id=tenant_id,
                attempt_id=attempt_id,
                phase="admitted",
                action=ACTION_DATA_ANONYMIZE,
                outcome="admitted",
                username=username,
                resource_ref=resource_ref,
                reason="authorized_anonymization_request",
                details={
                    "source_asset_id": source_asset["id"],
                    "source_table": f"{source_schema}.{source_table}",
                    "output_table": f"{output_schema}.{output_table}",
                    "level": level,
                    "data_type": data_type,
                },
            )
        except SecurityEventLedgerError as error:
            _audit(
                request,
                username,
                ACTION_DATA_ANONYMIZE,
                "failure",
                reason="security_ledger_admission_failed",
                attempt_id=str(attempt_id),
                security_error_code=error.code,
            )
            return JSONResponse(
                {
                    "error": "security evidence unavailable; operation not started",
                    "code": "security_ledger_unavailable",
                    "attempt_id": str(attempt_id),
                },
                status_code=503,
            )

        try:
            result = operation(**operation_kwargs)
            if not isinstance(result, dict):
                raise TypeError("anonymization result must be an object")
            succeeded = result.get("status") == "ok"
        except Exception as error:
            try:
                failure_event = _append_security_event(
                    tenant_id=tenant_id,
                    attempt_id=attempt_id,
                    phase="outcome",
                    action=ACTION_DATA_ANONYMIZE,
                    outcome="failure",
                    username=username,
                    resource_ref=resource_ref,
                    reason="anonymization_raised_exception",
                    details={"error_type": type(error).__name__},
                )
            except SecurityEventLedgerError as ledger_error:
                _audit(
                    request,
                    username,
                    ACTION_DATA_ANONYMIZE,
                    "failure",
                    reason="security_ledger_outcome_failed",
                    error_type=type(error).__name__,
                    attempt_id=str(attempt_id),
                    admission_event_id=str(admission_event.event_id),
                    security_error_code=ledger_error.code,
                )
                return JSONResponse(
                    {
                        "error": "security outcome evidence is incomplete",
                        "code": "security_evidence_incomplete",
                        "attempt_id": str(attempt_id),
                    },
                    status_code=503,
                )
            _audit(
                request,
                username,
                ACTION_DATA_ANONYMIZE,
                "failure",
                reason="anonymization_raised_exception",
                error_type=type(error).__name__,
                tenant_id=tenant_id,
                attempt_id=str(attempt_id),
                admission_event_id=str(admission_event.event_id),
                outcome_event_id=str(failure_event.event_id),
            )
            return JSONResponse({"error": "anonymization failed"}, status_code=500)

        try:
            outcome_event = _append_security_event(
                tenant_id=tenant_id,
                attempt_id=attempt_id,
                phase="outcome",
                action=ACTION_DATA_ANONYMIZE,
                outcome="success" if succeeded else "failure",
                username=username,
                resource_ref=resource_ref,
                reason=(
                    "anonymization_succeeded"
                    if succeeded
                    else "anonymization_failed"
                ),
                details={
                    "source_asset_id": source_asset["id"],
                    "result_status": result.get("status", "unknown"),
                    "output_row_count": result.get("output_row_count"),
                },
            )
        except SecurityEventLedgerError as error:
            _audit(
                request,
                username,
                ACTION_DATA_ANONYMIZE,
                "failure",
                reason="security_ledger_outcome_failed",
                attempt_id=str(attempt_id),
                admission_event_id=str(admission_event.event_id),
                security_error_code=error.code,
            )
            return JSONResponse(
                {
                    "error": "security outcome evidence is incomplete",
                    "code": "security_evidence_incomplete",
                    "attempt_id": str(attempt_id),
                },
                status_code=503,
            )
        _audit(
            request,
            username,
            ACTION_DATA_ANONYMIZE,
            "success" if succeeded else "failure",
            source_asset_id=source_asset["id"],
            source_table=f"{source_schema}.{source_table}",
            output_table=f"{output_schema}.{output_table}",
            level=level,
            data_type=data_type,
            result_status=result.get("status", "unknown"),
            tenant_id=tenant_id,
            attempt_id=str(attempt_id),
            admission_event_id=str(admission_event.event_id),
            outcome_event_id=str(outcome_event.event_id),
        )
        status_code = 200 if succeeded else 500
        return JSONResponse(result, status_code=status_code)
    except _RequestValidationError as e:
        security_recorded = _record_security_denial(
            tenant_id=tenant_id,
            attempt_id=attempt_id,
            action=ACTION_DATA_ANONYMIZE,
            username=username,
            resource_ref=resource_ref,
            reason="invalid_request",
            details={"validation_error": str(e)},
        )
        _audit(
            request,
            username,
            ACTION_DATA_ANONYMIZE,
            "denied",
            reason="invalid_request",
            validation_error=str(e),
            attempt_id=str(attempt_id),
            security_event_recorded=security_recorded,
        )
        return JSONResponse({"error": str(e)}, status_code=400)
    except _DatabaseUnavailable:
        _audit(
            request,
            username,
            ACTION_DATA_ANONYMIZE,
            "failure",
            reason="database_unavailable",
            attempt_id=str(attempt_id),
        )
        return JSONResponse({"error": "database unavailable"}, status_code=503)
    except Exception as e:
        _audit(
            request,
            username,
            ACTION_DATA_ANONYMIZE,
            "failure",
            reason="unexpected_error",
            error_type=type(e).__name__,
            attempt_id=str(attempt_id),
        )
        return JSONResponse({"error": "anonymization failed"}, status_code=500)


async def _api_classification_anonymize_submit(request: Request):
    """Admit spatial anonymization as an asynchronous governed DataOps Run."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    username, role = _set_user_context(user)
    tenant_id = current_tenant_id.get().strip()
    denial_attempt_id = uuid4()
    resource_ref = "api://classification/anonymize/submit"
    if role not in _ANONYMIZATION_ROLES:
        security_recorded = _record_security_denial(
            tenant_id=tenant_id,
            attempt_id=denial_attempt_id,
            action=ACTION_DATA_ANONYMIZE,
            username=username,
            resource_ref=resource_ref,
            reason="role_not_allowed",
            details={"role": role, "admission_only": True},
        )
        _audit(
            request,
            username,
            ACTION_DATA_ANONYMIZE,
            "denied",
            reason="role_not_allowed",
            role=role,
            admission_only=True,
            security_event_recorded=security_recorded,
        )
        return JSONResponse({"error": "admin or analyst role required"}, status_code=403)
    if not _TENANT_ID_RE.fullmatch(tenant_id):
        _audit(
            request,
            username,
            ACTION_DATA_ANONYMIZE,
            "denied",
            reason="tenant_context_required",
            admission_only=True,
        )
        return JSONResponse({"error": "valid tenant context required"}, status_code=403)

    try:
        try:
            body = await request.json()
        except (UnicodeDecodeError, ValueError) as error:
            raise _RequestValidationError("invalid JSON") from error
        if not isinstance(body, dict):
            raise _RequestValidationError("JSON object required")
        allowed_fields = {
            "client_request_id",
            "source_table",
            "output_table",
            "level",
            "data_type",
            "k_anonymity",
            "category_column",
            "top_k_categories",
            "keep_attrs",
            "agg_strategy",
            "dp_epsilon",
            "dp_numeric_fields",
        }
        unexpected = sorted(set(body) - allowed_fields)
        if unexpected:
            raise _RequestValidationError(
                f"unsupported request fields: {', '.join(unexpected)}"
            )
        client_request_id = body.get("client_request_id")
        if not isinstance(client_request_id, str):
            raise _RequestValidationError("client_request_id must be a string")
        parameters = _normalized_anonymization_parameters(body)
        resource_ref = _security_resource_ref(
            parameters["source_schema"],
            parameters["source_table"],
            parameters["output_schema"],
            parameters["output_table"],
        )
        source_asset = _lookup_accessible_postgis_asset(
            parameters["source_schema"],
            parameters["source_table"],
            username,
            role,
        )
        if source_asset is None:
            security_recorded = _record_security_denial(
                tenant_id=tenant_id,
                attempt_id=denial_attempt_id,
                action=ACTION_DATA_ANONYMIZE,
                username=username,
                resource_ref=resource_ref,
                reason="source_asset_not_accessible",
                details={"admission_only": True},
            )
            _audit(
                request,
                username,
                ACTION_DATA_ANONYMIZE,
                "denied",
                reason="source_asset_not_accessible",
                admission_only=True,
                security_event_recorded=security_recorded,
            )
            return JSONResponse(
                {"error": "source asset not found or access denied"},
                status_code=403,
            )
        if _physical_table_exists(
            parameters["output_schema"], parameters["output_table"]
        ):
            security_recorded = _record_security_denial(
                tenant_id=tenant_id,
                attempt_id=denial_attempt_id,
                action=ACTION_DATA_ANONYMIZE,
                username=username,
                resource_ref=resource_ref,
                reason="output_table_exists",
                details={"source_asset_id": source_asset["id"], "admission_only": True},
            )
            _audit(
                request,
                username,
                ACTION_DATA_ANONYMIZE,
                "denied",
                reason="output_table_exists",
                source_asset_id=source_asset["id"],
                admission_only=True,
                security_event_recorded=security_recorded,
            )
            return JSONResponse(
                {"error": "output table already exists; choose a new name"},
                status_code=409,
            )

        operation_request = SpatialAnonymizationRequest(
            tenant_id=tenant_id,
            client_request_id=client_request_id,
            requester_subject=f"human:{username}",
            source_asset_ref=f"agent_data_assets:{source_asset['id']}",
            **parameters,
        )
        spec = _spatial_anonymization_run_spec(operation_request)
        result = await asyncio.to_thread(
            _platform_gateway().submit_spatial_anonymization_run,
            spec,
        )
        _audit(
            request,
            username,
            ACTION_DATA_ANONYMIZE,
            "accepted",
            admission_only=True,
            client_request_id=client_request_id,
            request_sha256=result.request_sha256,
            source_asset_id=source_asset["id"],
            run_id=str(result.run.run_id),
            command_id=str(result.command.command_id),
            created=result.created,
        )
        return JSONResponse(
            {
                "request_sha256": result.request_sha256,
                "request_version_id": str(result.request_version.resource_version_id),
                "run_id": str(result.run.run_id),
                "command_id": str(result.command.command_id),
                "status": result.run.status.value,
                "created": result.created,
            },
            status_code=202 if result.created else 200,
        )
    except _RequestValidationError as error:
        security_recorded = _record_security_denial(
            tenant_id=tenant_id,
            attempt_id=denial_attempt_id,
            action=ACTION_DATA_ANONYMIZE,
            username=username,
            resource_ref=resource_ref,
            reason="invalid_request",
            details={"validation_error": str(error), "admission_only": True},
        )
        _audit(
            request,
            username,
            ACTION_DATA_ANONYMIZE,
            "denied",
            reason="invalid_request",
            validation_error=str(error),
            admission_only=True,
            security_event_recorded=security_recorded,
        )
        return JSONResponse({"error": str(error)}, status_code=400)
    except GatewayConflictError as error:
        _audit(
            request,
            username,
            ACTION_DATA_ANONYMIZE,
            "conflict",
            reason=error.code,
            admission_only=True,
        )
        return JSONResponse(
            {"error": str(error), "code": error.code},
            status_code=409,
        )
    except GatewayValidationError as error:
        return JSONResponse(
            {"error": str(error), "code": error.code},
            status_code=422,
        )
    except (GatewayConfigurationError, GatewayUnavailableError) as error:
        _audit(
            request,
            username,
            ACTION_DATA_ANONYMIZE,
            "failure",
            reason=error.code,
            admission_only=True,
        )
        return JSONResponse(
            {"error": "spatial anonymization admission unavailable", "code": error.code},
            status_code=503,
        )
    except ValueError as error:
        security_recorded = _record_security_denial(
            tenant_id=tenant_id,
            attempt_id=denial_attempt_id,
            action=ACTION_DATA_ANONYMIZE,
            username=username,
            resource_ref=resource_ref,
            reason="invalid_request",
            details={"validation_error": str(error), "admission_only": True},
        )
        return JSONResponse(
            {
                "error": "request does not satisfy the anonymization contract",
                "code": "contract_validation_failed",
                "security_event_recorded": security_recorded,
            },
            status_code=422,
        )


async def _api_classification_verify(request: Request):
    """Run re-identification checks on two governed PostGIS assets."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    username, role = _set_user_context(user)
    tenant_id = current_tenant_id.get().strip()
    attempt_id = uuid4()
    resource_ref = "api://classification/verify"
    if role not in _ANONYMIZATION_ROLES:
        security_recorded = _record_security_denial(
            tenant_id=tenant_id,
            attempt_id=attempt_id,
            action=ACTION_ANONYMIZATION_VERIFY,
            username=username,
            resource_ref=resource_ref,
            reason="role_not_allowed",
            details={"role": role},
        )
        _audit(
            request,
            username,
            ACTION_ANONYMIZATION_VERIFY,
            "denied",
            reason="role_not_allowed",
            role=role,
            attempt_id=str(attempt_id),
            security_event_recorded=security_recorded,
        )
        return JSONResponse({"error": "admin or analyst role required"}, status_code=403)
    if not _TENANT_ID_RE.fullmatch(tenant_id):
        _audit(
            request,
            username,
            ACTION_ANONYMIZATION_VERIFY,
            "denied",
            reason="tenant_context_required",
            attempt_id=str(attempt_id),
        )
        return JSONResponse(
            {"error": "valid tenant context required"},
            status_code=403,
        )

    try:
        try:
            body = await request.json()
        except (UnicodeDecodeError, ValueError) as error:
            raise _RequestValidationError("invalid JSON") from error
        if not isinstance(body, dict):
            raise _RequestValidationError("JSON object required")
        source_schema, source_table = _parse_table_reference(
            body.get("source_table", ""), "source_table"
        )
        output_schema, output_table = _parse_table_reference(
            body.get("output_table", ""), "output_table"
        )
        sample_size = _bounded_integer(
            body.get("sample_size", 30),
            "sample_size",
            minimum=1,
            maximum=1000,
        )
        resource_ref = _security_resource_ref(
            source_schema,
            source_table,
            output_schema,
            output_table,
        )

        source_asset = _lookup_accessible_postgis_asset(
            source_schema, source_table, username, role
        )
        output_asset = _lookup_accessible_postgis_asset(
            output_schema, output_table, username, role
        )
        if source_asset is None or output_asset is None:
            security_recorded = _record_security_denial(
                tenant_id=tenant_id,
                attempt_id=attempt_id,
                action=ACTION_ANONYMIZATION_VERIFY,
                username=username,
                resource_ref=resource_ref,
                reason="asset_not_accessible",
                details={
                    "source_asset_found": source_asset is not None,
                    "output_asset_found": output_asset is not None,
                },
            )
            _audit(
                request,
                username,
                ACTION_ANONYMIZATION_VERIFY,
                "denied",
                reason="asset_not_accessible",
                source_table=f"{source_schema}.{source_table}",
                output_table=f"{output_schema}.{output_table}",
                attempt_id=str(attempt_id),
                security_event_recorded=security_recorded,
            )
            return JSONResponse(
                {"error": "source or output asset not found or access denied"},
                status_code=403,
            )

        try:
            admission_event = _append_security_event(
                tenant_id=tenant_id,
                attempt_id=attempt_id,
                phase="admitted",
                action=ACTION_ANONYMIZATION_VERIFY,
                outcome="admitted",
                username=username,
                resource_ref=resource_ref,
                reason="authorized_anonymization_verification",
                details={
                    "source_asset_id": source_asset["id"],
                    "output_asset_id": output_asset["id"],
                    "sample_size": sample_size,
                },
            )
        except SecurityEventLedgerError as error:
            _audit(
                request,
                username,
                ACTION_ANONYMIZATION_VERIFY,
                "failure",
                reason="security_ledger_admission_failed",
                attempt_id=str(attempt_id),
                security_error_code=error.code,
            )
            return JSONResponse(
                {
                    "error": "security evidence unavailable; operation not started",
                    "code": "security_ledger_unavailable",
                    "attempt_id": str(attempt_id),
                },
                status_code=503,
            )

        from ..grid_anonymize import verify_anonymization

        try:
            result = verify_anonymization(
                source_table=source_table,
                output_table=output_table,
                source_schema=source_schema,
                output_schema=output_schema,
                sample_size=sample_size,
            )
            if not isinstance(result, dict):
                raise TypeError("verification result must be an object")
            succeeded = result.get("status") == "ok"
        except Exception as error:
            try:
                failure_event = _append_security_event(
                    tenant_id=tenant_id,
                    attempt_id=attempt_id,
                    phase="outcome",
                    action=ACTION_ANONYMIZATION_VERIFY,
                    outcome="failure",
                    username=username,
                    resource_ref=resource_ref,
                    reason="anonymization_verification_raised_exception",
                    details={"error_type": type(error).__name__},
                )
            except SecurityEventLedgerError as ledger_error:
                _audit(
                    request,
                    username,
                    ACTION_ANONYMIZATION_VERIFY,
                    "failure",
                    reason="security_ledger_outcome_failed",
                    error_type=type(error).__name__,
                    attempt_id=str(attempt_id),
                    admission_event_id=str(admission_event.event_id),
                    security_error_code=ledger_error.code,
                )
                return JSONResponse(
                    {
                        "error": "security outcome evidence is incomplete",
                        "code": "security_evidence_incomplete",
                        "attempt_id": str(attempt_id),
                    },
                    status_code=503,
                )
            _audit(
                request,
                username,
                ACTION_ANONYMIZATION_VERIFY,
                "failure",
                reason="anonymization_verification_raised_exception",
                error_type=type(error).__name__,
                tenant_id=tenant_id,
                attempt_id=str(attempt_id),
                admission_event_id=str(admission_event.event_id),
                outcome_event_id=str(failure_event.event_id),
            )
            return JSONResponse(
                {"error": "anonymization verification failed"},
                status_code=500,
            )

        try:
            outcome_event = _append_security_event(
                tenant_id=tenant_id,
                attempt_id=attempt_id,
                phase="outcome",
                action=ACTION_ANONYMIZATION_VERIFY,
                outcome="success" if succeeded else "failure",
                username=username,
                resource_ref=resource_ref,
                reason=(
                    "anonymization_verification_succeeded"
                    if succeeded
                    else "anonymization_verification_failed"
                ),
                details={
                    "source_asset_id": source_asset["id"],
                    "output_asset_id": output_asset["id"],
                    "result_status": result.get("status", "unknown"),
                    "risk_score": result.get("overall_risk_score"),
                },
            )
        except SecurityEventLedgerError as error:
            _audit(
                request,
                username,
                ACTION_ANONYMIZATION_VERIFY,
                "failure",
                reason="security_ledger_outcome_failed",
                attempt_id=str(attempt_id),
                admission_event_id=str(admission_event.event_id),
                security_error_code=error.code,
            )
            return JSONResponse(
                {
                    "error": "security outcome evidence is incomplete",
                    "code": "security_evidence_incomplete",
                    "attempt_id": str(attempt_id),
                },
                status_code=503,
            )
        _audit(
            request,
            username,
            ACTION_ANONYMIZATION_VERIFY,
            "success" if succeeded else "failure",
            source_asset_id=source_asset["id"],
            output_asset_id=output_asset["id"],
            source_table=f"{source_schema}.{source_table}",
            output_table=f"{output_schema}.{output_table}",
            result_status=result.get("status", "unknown"),
            risk_score=result.get("overall_risk_score"),
            tenant_id=tenant_id,
            attempt_id=str(attempt_id),
            admission_event_id=str(admission_event.event_id),
            outcome_event_id=str(outcome_event.event_id),
        )
        return JSONResponse(result, status_code=200 if succeeded else 500)
    except _RequestValidationError as e:
        security_recorded = _record_security_denial(
            tenant_id=tenant_id,
            attempt_id=attempt_id,
            action=ACTION_ANONYMIZATION_VERIFY,
            username=username,
            resource_ref=resource_ref,
            reason="invalid_request",
            details={"validation_error": str(e)},
        )
        _audit(
            request,
            username,
            ACTION_ANONYMIZATION_VERIFY,
            "denied",
            reason="invalid_request",
            validation_error=str(e),
            attempt_id=str(attempt_id),
            security_event_recorded=security_recorded,
        )
        return JSONResponse({"error": str(e)}, status_code=400)
    except _DatabaseUnavailable:
        _audit(
            request,
            username,
            ACTION_ANONYMIZATION_VERIFY,
            "failure",
            reason="database_unavailable",
            attempt_id=str(attempt_id),
        )
        return JSONResponse({"error": "database unavailable"}, status_code=503)
    except Exception as e:
        _audit(
            request,
            username,
            ACTION_ANONYMIZATION_VERIFY,
            "failure",
            reason="unexpected_error",
            error_type=type(e).__name__,
            attempt_id=str(attempt_id),
        )
        return JSONResponse({"error": "anonymization verification failed"}, status_code=500)


async def _api_security_reconciliation_list(request: Request):
    """Preview incomplete security outcomes without mutating the ledger."""
    _user, _username, _role, error_response = _require_admin(request)
    if error_response:
        return error_response
    tenant_id = current_tenant_id.get().strip()
    if not _TENANT_ID_RE.fullmatch(tenant_id):
        return JSONResponse({"error": "valid tenant context required"}, status_code=403)
    try:
        minimum_age_seconds = _query_integer(
            request,
            "minimum_age_seconds",
            60,
            minimum=0,
            maximum=604800,
        )
        limit = _query_integer(request, "limit", 100, minimum=1, maximum=1000)
        attempt_id = _attempt_id(request.query_params.get("attempt_id"))
        results = reconcile_security_event_outcomes(
            tenant_id,
            older_than=datetime.now(UTC) - timedelta(seconds=minimum_age_seconds),
            attempt_id=attempt_id,
            limit=limit,
            apply=False,
        )
        return JSONResponse(_reconciliation_payload(results))
    except _RequestValidationError as error:
        return JSONResponse({"error": str(error)}, status_code=400)
    except (SecurityEventLedgerError, SecurityEventReconciliationError) as error:
        return JSONResponse(
            {
                "error": "security reconciliation unavailable",
                "code": error.code,
            },
            status_code=503,
        )


async def _api_security_reconciliation_apply(request: Request):
    """Append an outcome only when durable output evidence matches admission."""
    _user, username, _role, error_response = _require_admin(request)
    if error_response:
        return error_response
    tenant_id = current_tenant_id.get().strip()
    if not _TENANT_ID_RE.fullmatch(tenant_id):
        return JSONResponse({"error": "valid tenant context required"}, status_code=403)
    try:
        try:
            body = await request.json()
        except (UnicodeDecodeError, ValueError) as error:
            raise _RequestValidationError("invalid JSON") from error
        if not isinstance(body, dict):
            raise _RequestValidationError("JSON object required")
        attempt_id = _attempt_id(body.get("attempt_id"), required=True)
        minimum_age_seconds = _bounded_integer(
            body.get("minimum_age_seconds", 60),
            "minimum_age_seconds",
            minimum=0,
            maximum=604800,
        )
        results = reconcile_security_event_outcomes(
            tenant_id,
            older_than=datetime.now(UTC) - timedelta(seconds=minimum_age_seconds),
            attempt_id=attempt_id,
            limit=1,
            apply=True,
            actor_subject=f"human:{username}",
        )
        payload = _reconciliation_payload(results)
        if not results:
            status_code = 404
            status = "not_found"
        elif results[0].status == "manual_review":
            status_code = 409
            status = "manual_review"
        else:
            status_code = 200
            status = results[0].status
        _audit(
            request,
            username,
            ACTION_SECURITY_EVENT_RECONCILE,
            "success" if status_code == 200 else "failure",
            tenant_id=tenant_id,
            attempt_id=str(attempt_id),
            reconciliation_status=status,
        )
        return JSONResponse(payload, status_code=status_code)
    except _RequestValidationError as error:
        return JSONResponse({"error": str(error)}, status_code=400)
    except (SecurityEventLedgerError, SecurityEventReconciliationError) as error:
        _audit(
            request,
            username,
            ACTION_SECURITY_EVENT_RECONCILE,
            "failure",
            tenant_id=tenant_id,
            reason="reconciliation_unavailable",
            error_code=error.code,
        )
        return JSONResponse(
            {
                "error": "security reconciliation unavailable",
                "code": error.code,
            },
            status_code=503,
        )


def get_classification_routes() -> list[Route]:
    return [
        Route("/api/classification/summary", _api_classification_summary, methods=["GET"]),
        Route("/api/classification/anonymize", _api_classification_anonymize, methods=["POST"]),
        Route(
            "/api/classification/anonymize/submit",
            _api_classification_anonymize_submit,
            methods=["POST"],
        ),
        Route("/api/classification/verify", _api_classification_verify, methods=["POST"]),
        Route(
            "/api/classification/security/incomplete",
            _api_security_reconciliation_list,
            methods=["GET"],
        ),
        Route(
            "/api/classification/security/reconcile",
            _api_security_reconciliation_apply,
            methods=["POST"],
        ),
    ]
