"""Authenticated HTTP boundary for the governed semantic query capability."""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from ..capability_registry import (
    CAPABILITY_FINGERPRINT_HEADER,
    GOVERNED_SEMANTIC_QUERY,
    CapabilityFingerprintMismatchError,
    CapabilityInputError,
    CapabilityOutputError,
)
from ..governed_query import (
    GovernedQueryRequest,
    QueryExecutionStatus,
    QueryPolicyDeniedError,
    execute_governed_query,
)
from ..governed_query_security import (
    GovernedQuerySecurityError,
    resolve_governed_query_security_ports,
)
from ..nl2sql_source_authority import (
    NL2SQLSourceAuthority,
    NL2SQLSourceAuthorityError,
    NL2SQLSourceAuthorityUnavailableError,
    NL2SQLSourceBinding,
)
from ..platform_contracts import SubjectContext, SubjectType
from ..platform_gateway import PlatformGateway, PlatformGatewayError
from ..user_context import current_tenant_id
from .helpers import _get_user_from_request, _set_user_context


class NL2SQLSourceBindingActivationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    semantic_source_name: str = Field(
        min_length=1,
        max_length=255,
        pattern=r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?$",
    )
    execution_engine: Literal["postgis", "lake"]
    physical_locator: str = Field(min_length=1, max_length=2_048)
    resource_version_id: UUID


def _metadata(user: Any) -> dict[str, Any]:
    value = getattr(user, "metadata", None)
    return value if isinstance(value, dict) else {}


def _roles(user: Any, default_role: str) -> tuple[str, ...]:
    configured = _metadata(user).get("roles", ())
    if isinstance(configured, str):
        configured = (configured,)
    if not isinstance(configured, (list, tuple, set)):
        configured = ()
    roles = {
        str(role).strip()
        for role in (*configured, default_role)
        if str(role).strip()
    }
    return tuple(sorted(roles))


def _contract_guard(request: Request) -> JSONResponse | None:
    fingerprint = request.headers.get(CAPABILITY_FINGERPRINT_HEADER)
    if fingerprint is None:
        fingerprint = request.headers.get(CAPABILITY_FINGERPRINT_HEADER.lower())
    try:
        GOVERNED_SEMANTIC_QUERY.assert_invocation_fingerprint(fingerprint)
    except CapabilityFingerprintMismatchError:
        return JSONResponse(
            {
                "error": "CapabilitySpec fingerprint does not match the serving contract",
                "code": "capability_contract_mismatch",
                "capability_id": GOVERNED_SEMANTIC_QUERY.capability_id,
                "version": GOVERNED_SEMANTIC_QUERY.version,
                "fingerprint": GOVERNED_SEMANTIC_QUERY.fingerprint,
            },
            status_code=409,
        )
    return None


async def governed_query_execute(request: Request) -> JSONResponse:
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, role = _set_user_context(user)
    tenant_id = current_tenant_id.get().strip()
    if not tenant_id:
        return JSONResponse(
            {
                "error": "Authenticated identity has no tenant binding",
                "code": "tenant_context_required",
            },
            status_code=403,
        )
    if mismatch := _contract_guard(request):
        return mismatch

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)
    if not isinstance(body, dict):
        return JSONResponse({"error": "JSON body must be an object"}, status_code=400)

    try:
        GOVERNED_SEMANTIC_QUERY.validate_input(body)
        query = GovernedQueryRequest.model_validate(body)
        subject = SubjectContext(
            tenant_id=tenant_id,
            subject_id=username,
            subject_type=SubjectType.HUMAN,
            roles=_roles(user, role),
            purpose=query.purpose,
            trace_id=query.request_id,
        )
        security_ports = resolve_governed_query_security_ports(tenant_id)
        security_kwargs = (
            {}
            if security_ports is None
            else {
                "security_reader": security_ports[0],
                "security_audit_port": security_ports[1],
            }
        )
        result = execute_governed_query(query, subject, **security_kwargs)
        payload = result.model_dump(mode="json", by_alias=True)
        GOVERNED_SEMANTIC_QUERY.validate_output(payload)
        status_code = (
            202
            if result.status is QueryExecutionStatus.RUN_ADMITTED
            else 200
        )
        return JSONResponse(payload, status_code=status_code)
    except QueryPolicyDeniedError as exc:
        return JSONResponse(
            {"error": str(exc), "code": "query_policy_denied"},
            status_code=403,
        )
    except GovernedQuerySecurityError as exc:
        return JSONResponse(
            {"error": str(exc), "code": "query_security_unavailable"},
            status_code=503,
        )
    except CapabilityOutputError:
        return JSONResponse(
            {
                "error": "Governed query implementation violated its output contract",
                "code": "query_output_contract_invalid",
            },
            status_code=500,
        )
    except (CapabilityInputError, ValidationError, ValueError, TypeError) as exc:
        return JSONResponse(
            {"error": str(exc), "code": "query_contract_invalid"},
            status_code=400,
        )


async def activate_nl2sql_source_binding(request: Request) -> JSONResponse:
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, role = _set_user_context(user)
    tenant_id = current_tenant_id.get().strip()
    roles = _roles(user, role)
    if not tenant_id:
        return JSONResponse(
            {"error": "Authenticated identity has no tenant binding"},
            status_code=403,
        )
    if not set(roles) & {"admin", "platform_operator"}:
        return JSONResponse(
            {"error": "admin or platform_operator role required"},
            status_code=403,
        )
    try:
        body = NL2SQLSourceBindingActivationRequest.model_validate(
            await request.json()
        )
        version = PlatformGateway().get_resource_version(
            tenant_id,
            body.resource_version_id,
        )
        source_mode = (
            "immutable_snapshot"
            if (
                version.authority_version_ref.get("immutable_snapshot") is True
                or version.authority_version_ref.get("source_mode")
                == "immutable_snapshot"
            )
            else "mutable_view"
        )
        if source_mode != "immutable_snapshot":
            raise ValueError(
                "ResourceVersion does not attest an immutable physical snapshot"
            )
        binding = NL2SQLSourceBinding.create(
            tenant_id=tenant_id,
            semantic_source_name=body.semantic_source_name,
            execution_engine=body.execution_engine,
            physical_locator=body.physical_locator,
            source_mode=source_mode,
            resource_version=version,
        )
        subject = SubjectContext(
            tenant_id=tenant_id,
            subject_id=username,
            subject_type=SubjectType.HUMAN,
            roles=roles,
            purpose="activate governed NL2SQL source binding",
            trace_id=f"nl2sql-bind-{binding.binding_id.hex[:12]}",
        )
        activated = NL2SQLSourceAuthority().activate(binding, subject)
        return JSONResponse(
            activated.model_dump(mode="json", by_alias=True),
            status_code=200,
        )
    except (NL2SQLSourceAuthorityUnavailableError, PlatformGatewayError) as exc:
        return JSONResponse(
            {"error": str(exc), "code": "nl2sql_source_binding_unavailable"},
            status_code=503,
        )
    except (NL2SQLSourceAuthorityError, ValidationError, ValueError, TypeError) as exc:
        return JSONResponse(
            {"error": str(exc), "code": "nl2sql_source_binding_invalid"},
            status_code=400,
        )


async def get_nl2sql_source_binding(request: Request) -> JSONResponse:
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    tenant_id = current_tenant_id.get().strip()
    if not tenant_id:
        return JSONResponse(
            {"error": "Authenticated identity has no tenant binding"},
            status_code=403,
        )
    try:
        engine = str(request.path_params["execution_engine"])
        if engine not in {"postgis", "lake"}:
            raise ValueError("execution_engine must be postgis or lake")
        source_name = str(request.path_params["semantic_source_name"])
        binding = NL2SQLSourceAuthority().resolve(
            tenant_id,
            source_name,
            engine,
        )
        return JSONResponse(binding.model_dump(mode="json", by_alias=True))
    except NL2SQLSourceAuthorityUnavailableError as exc:
        return JSONResponse(
            {"error": str(exc), "code": "nl2sql_source_binding_unavailable"},
            status_code=503,
        )
    except (NL2SQLSourceAuthorityError, ValueError) as exc:
        return JSONResponse(
            {"error": str(exc), "code": "nl2sql_source_binding_not_found"},
            status_code=404,
        )


def get_governed_query_routes() -> list[Route]:
    return [
        Route(
            "/api/governed-query",
            endpoint=governed_query_execute,
            methods=["POST"],
        ),
        Route(
            "/api/governed-query/nl2sql-source-bindings/activate",
            endpoint=activate_nl2sql_source_binding,
            methods=["POST"],
        ),
        Route(
            "/api/governed-query/nl2sql-source-bindings/"
            "{execution_engine}/{semantic_source_name}",
            endpoint=get_nl2sql_source_binding,
            methods=["GET"],
        ),
    ]
