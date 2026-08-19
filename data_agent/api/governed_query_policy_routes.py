"""Authenticated write boundary for governed query policy records."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from ..governed_query_policy_authority import (
    GovernedQueryPolicyAuthorityConfigurationError,
    GovernedQueryPolicyAuthorityConflictError,
    GovernedQueryPolicyAuthorityError,
    GovernedQueryPolicyAuthorityForbiddenError,
    GovernedQueryPolicyAuthorityUnavailableError,
    GovernedQueryPolicyAuthorityValidationError,
    PostgresGovernedQueryPolicyAuthority,
    build_policy_revocation,
    build_policy_version,
    build_purpose_registration,
)
from ..platform_contracts import NonEmptyText, ShortName, SubjectType
from ..user_context import current_tenant_id
from .helpers import _get_user_from_request, _set_user_context

RequestModel = TypeVar("RequestModel", bound=BaseModel)


class PurposeRegistrationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    purpose_code: ShortName
    description: NonEmptyText


class PolicyVersionPublicationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    policy_ref: NonEmptyText
    policy_version: ShortName
    purpose_code: ShortName
    effect: Literal["allow", "deny"] = "allow"
    priority: int = Field(default=0, ge=0, le=10_000)
    subject_types: tuple[SubjectType, ...] = Field(
        default=(
            SubjectType.HUMAN,
            SubjectType.WORKLOAD,
            SubjectType.AGENT,
        ),
        min_length=1,
        max_length=3,
    )
    subject_ids: tuple[ShortName, ...] = Field(default=(), max_length=100)
    required_roles: tuple[ShortName, ...] = Field(default=(), max_length=32)
    channels: tuple[ShortName, ...] = Field(
        default=("ontology",), min_length=1, max_length=16
    )
    adapter_ids: tuple[ShortName, ...] = Field(
        default=("gda.ontology.query",), min_length=1, max_length=32
    )
    resource_prefixes: tuple[NonEmptyText, ...] = Field(default=(), max_length=100)
    obligations: tuple[NonEmptyText, ...] = Field(default=(), max_length=32)
    valid_from: datetime
    expires_at: datetime


class PolicyRevocationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    policy_ref: NonEmptyText
    policy_version: ShortName
    reason: NonEmptyText


def _metadata(user: Any) -> dict[str, Any]:
    value = getattr(user, "metadata", None)
    return value if isinstance(value, dict) else {}


def _roles(user: Any, default_role: str) -> tuple[str, ...]:
    configured = _metadata(user).get("roles", ())
    if isinstance(configured, str):
        configured = (configured,)
    if not isinstance(configured, (list, tuple, set)):
        configured = ()
    return tuple(
        sorted(
            {
                str(role).strip()
                for role in (*configured, default_role)
                if str(role).strip()
            }
        )
    )


def _operator_context(
    request: Request,
) -> tuple[str, str, JSONResponse | None]:
    user = _get_user_from_request(request)
    if not user:
        return "", "", JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, default_role = _set_user_context(user)
    tenant_id = current_tenant_id.get().strip()
    if not tenant_id:
        return (
            "",
            "",
            JSONResponse(
                {
                    "error": "Authenticated identity has no tenant binding",
                    "code": "tenant_context_required",
                },
                status_code=403,
            ),
        )
    if not set(_roles(user, str(default_role))) & {"admin", "platform_operator"}:
        return (
            "",
            "",
            JSONResponse(
                {
                    "error": "admin or platform_operator role required",
                    "code": "governed_query_policy_operator_required",
                },
                status_code=403,
            ),
        )
    return tenant_id, f"human:{str(username).strip()}", None


def _utc_now() -> datetime:
    return datetime.now(UTC)


async def _parse_request(
    request: Request, model_type: type[RequestModel]
) -> RequestModel:
    try:
        payload = await request.json()
    except Exception as exc:
        raise ValueError("Invalid JSON body") from exc
    return model_type.model_validate(payload)


def _error_response(exc: Exception) -> JSONResponse:
    if isinstance(
        exc,
        (
            GovernedQueryPolicyAuthorityValidationError,
            ValidationError,
            ValueError,
            TypeError,
        ),
    ):
        status_code = 400
        code = "governed_query_policy_contract_invalid"
    elif isinstance(exc, GovernedQueryPolicyAuthorityForbiddenError):
        status_code = 403
        code = "governed_query_policy_forbidden"
    elif isinstance(exc, GovernedQueryPolicyAuthorityConflictError):
        status_code = 409
        code = "governed_query_policy_conflict"
    elif isinstance(
        exc,
        (
            GovernedQueryPolicyAuthorityConfigurationError,
            GovernedQueryPolicyAuthorityUnavailableError,
            GovernedQueryPolicyAuthorityError,
        ),
    ):
        status_code = 503
        code = "governed_query_policy_authority_unavailable"
    else:
        status_code = 503
        code = "governed_query_policy_authority_unavailable"
    return JSONResponse({"error": str(exc), "code": code}, status_code=status_code)


async def register_governed_query_purpose(request: Request) -> JSONResponse:
    tenant_id, actor, error = _operator_context(request)
    if error is not None:
        return error
    try:
        body = await _parse_request(request, PurposeRegistrationRequest)
        registration = build_purpose_registration(
            tenant_id=tenant_id,
            purpose_code=body.purpose_code,
            description=body.description,
            registered_by=actor,
            registered_at=_utc_now(),
        )
        stored = PostgresGovernedQueryPolicyAuthority(tenant_id).register_purpose(
            registration
        )
        return JSONResponse(stored.model_dump(mode="json"), status_code=201)
    except (
        GovernedQueryPolicyAuthorityError,
        ValidationError,
        ValueError,
        TypeError,
    ) as exc:
        return _error_response(exc)


async def publish_governed_query_policy_version(request: Request) -> JSONResponse:
    tenant_id, actor, error = _operator_context(request)
    if error is not None:
        return error
    try:
        body = await _parse_request(request, PolicyVersionPublicationRequest)
        policy = build_policy_version(
            tenant_id=tenant_id,
            policy_ref=body.policy_ref,
            policy_version=body.policy_version,
            purpose_code=body.purpose_code,
            effect=body.effect,
            priority=body.priority,
            subject_types=body.subject_types,
            subject_ids=body.subject_ids,
            required_roles=body.required_roles,
            channels=body.channels,
            adapter_ids=body.adapter_ids,
            resource_prefixes=body.resource_prefixes,
            obligations=body.obligations,
            valid_from=body.valid_from,
            expires_at=body.expires_at,
            published_at=_utc_now(),
            published_by=actor,
        )
        stored = PostgresGovernedQueryPolicyAuthority(tenant_id).register_policy(policy)
        return JSONResponse(stored.model_dump(mode="json"), status_code=201)
    except (
        GovernedQueryPolicyAuthorityError,
        ValidationError,
        ValueError,
        TypeError,
    ) as exc:
        return _error_response(exc)


async def revoke_governed_query_policy_version(request: Request) -> JSONResponse:
    tenant_id, actor, error = _operator_context(request)
    if error is not None:
        return error
    try:
        body = await _parse_request(request, PolicyRevocationRequest)
        revocation = build_policy_revocation(
            tenant_id=tenant_id,
            policy_ref=body.policy_ref,
            policy_version=body.policy_version,
            revoked_at=_utc_now(),
            revoked_by=actor,
            reason=body.reason,
        )
        stored = PostgresGovernedQueryPolicyAuthority(tenant_id).revoke_policy(
            revocation
        )
        return JSONResponse(stored.model_dump(mode="json"), status_code=201)
    except (
        GovernedQueryPolicyAuthorityError,
        ValidationError,
        ValueError,
        TypeError,
    ) as exc:
        return _error_response(exc)


def get_governed_query_policy_routes() -> list[Route]:
    return [
        Route(
            "/api/governed-query-policy/purposes",
            endpoint=register_governed_query_purpose,
            methods=["POST"],
        ),
        Route(
            "/api/governed-query-policy/versions",
            endpoint=publish_governed_query_policy_version,
            methods=["POST"],
        ),
        Route(
            "/api/governed-query-policy/revocations",
            endpoint=revoke_governed_query_policy_version,
            methods=["POST"],
        ),
    ]
