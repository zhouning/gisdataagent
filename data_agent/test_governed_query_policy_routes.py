from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from starlette.requests import Request

from data_agent.api import governed_query_policy_routes as routes
from data_agent.governed_query_policy_authority import (
    GovernedQueryPolicyAuthorityConfigurationError,
    GovernedQueryPolicyAuthorityConflictError,
    GovernedQueryPolicyAuthorityForbiddenError,
    GovernedQueryPolicyAuthorityUnavailableError,
    GovernedQueryPolicyAuthorityValidationError,
    GovernedQueryPolicyRevocation,
    GovernedQueryPolicyVersion,
    GovernedQueryPurposeRegistration,
)

NOW = datetime(2026, 8, 19, 9, 30, tzinfo=UTC)


def _request(path: str, payload: object) -> Request:
    body = json.dumps(payload).encode()
    delivered = False

    async def receive():
        nonlocal delivered
        if delivered:
            return {"type": "http.disconnect"}
        delivered = True
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": path,
            "headers": [],
            "query_string": b"",
        },
        receive=receive,
    )


def _authenticate(
    monkeypatch,
    *,
    tenant_id: str = "tenant-a",
    role: str = "admin",
    roles: tuple[str, ...] = (),
) -> None:
    user = SimpleNamespace(
        identifier="operator-a",
        metadata={"tenant_id": tenant_id, "role": role, "roles": roles},
    )
    monkeypatch.setattr(routes, "_get_user_from_request", lambda request: user)


class _CapturingAuthority:
    calls: list[tuple[str, str, object]] = []
    error: Exception | None = None

    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id

    @classmethod
    def reset(cls) -> None:
        cls.calls = []
        cls.error = None

    def _record(self, operation: str, value: object):
        if self.error is not None:
            raise self.error
        self.calls.append((operation, self.tenant_id, value))
        return value

    def register_purpose(self, value):
        return self._record("purpose", value)

    def register_policy(self, value):
        return self._record("policy", value)

    def revoke_policy(self, value):
        return self._record("revocation", value)


@pytest.fixture(autouse=True)
def _authority(monkeypatch):
    _CapturingAuthority.reset()
    monkeypatch.setattr(routes, "PostgresGovernedQueryPolicyAuthority", _CapturingAuthority)
    monkeypatch.setattr(routes, "_utc_now", lambda: NOW)


@pytest.mark.asyncio
async def test_purpose_registration_seals_server_identity_and_tenant(monkeypatch) -> None:
    _authenticate(monkeypatch)

    response = await routes.register_governed_query_purpose(
        _request(
            "/api/governed-query-policy/purposes",
            {
                "purpose_code": "semantic_query",
                "description": "Governed semantic query execution",
            },
        )
    )
    payload = json.loads(response.body)
    sealed = GovernedQueryPurposeRegistration.model_validate(payload)

    assert response.status_code == 201
    assert _CapturingAuthority.calls == [("purpose", "tenant-a", sealed)]
    assert sealed.tenant_id == "tenant-a"
    assert sealed.registered_by == "human:operator-a"
    assert sealed.registered_at == NOW


@pytest.mark.asyncio
async def test_policy_publication_seals_scopes_and_server_metadata(monkeypatch) -> None:
    _authenticate(monkeypatch, role="analyst", roles=("platform_operator",))
    request_payload = {
        "policy_ref": "policy:semantic-query",
        "policy_version": "v2",
        "purpose_code": "semantic_query",
        "effect": "allow",
        "priority": 50,
        "subject_types": ["human"],
        "subject_ids": ["analyst-a"],
        "required_roles": ["analyst"],
        "channels": ["ontology", "metric"],
        "adapter_ids": ["gda.ontology.query", "gda.metric.query"],
        "resource_prefixes": ["gda://tenant-a/dataset/"],
        "obligations": ["mask_sensitive_fields"],
        "valid_from": NOW.isoformat(),
        "expires_at": (NOW + timedelta(days=30)).isoformat(),
    }

    response = await routes.publish_governed_query_policy_version(
        _request("/api/governed-query-policy/versions", request_payload)
    )
    payload = json.loads(response.body)
    sealed = GovernedQueryPolicyVersion.model_validate(payload)

    assert response.status_code == 201
    assert _CapturingAuthority.calls == [("policy", "tenant-a", sealed)]
    assert sealed.tenant_id == "tenant-a"
    assert sealed.published_by == "human:operator-a"
    assert sealed.published_at == NOW
    assert sealed.required_roles == ("analyst",)
    assert sealed.resource_prefixes == ("gda://tenant-a/dataset/",)


@pytest.mark.asyncio
async def test_revocation_seals_server_identity_and_time(monkeypatch) -> None:
    _authenticate(monkeypatch)

    response = await routes.revoke_governed_query_policy_version(
        _request(
            "/api/governed-query-policy/revocations",
            {
                "policy_ref": "policy:semantic-query",
                "policy_version": "v2",
                "reason": "Superseded by v3",
            },
        )
    )
    payload = json.loads(response.body)
    sealed = GovernedQueryPolicyRevocation.model_validate(payload)

    assert response.status_code == 201
    assert _CapturingAuthority.calls == [("revocation", "tenant-a", sealed)]
    assert sealed.revoked_by == "human:operator-a"
    assert sealed.revoked_at == NOW


@pytest.mark.asyncio
async def test_policy_routes_require_authentication(monkeypatch) -> None:
    monkeypatch.setattr(routes, "_get_user_from_request", lambda request: None)

    response = await routes.register_governed_query_purpose(
        _request(
            "/api/governed-query-policy/purposes",
            {"purpose_code": "semantic_query", "description": "Semantic query"},
        )
    )

    assert response.status_code == 401
    assert _CapturingAuthority.calls == []


@pytest.mark.asyncio
async def test_policy_routes_require_server_tenant(monkeypatch) -> None:
    _authenticate(monkeypatch, tenant_id="")

    response = await routes.register_governed_query_purpose(
        _request(
            "/api/governed-query-policy/purposes",
            {"purpose_code": "semantic_query", "description": "Semantic query"},
        )
    )

    assert response.status_code == 403
    assert json.loads(response.body)["code"] == "tenant_context_required"
    assert _CapturingAuthority.calls == []


@pytest.mark.asyncio
async def test_policy_routes_require_operator_role(monkeypatch) -> None:
    _authenticate(monkeypatch, role="analyst")

    response = await routes.register_governed_query_purpose(
        _request(
            "/api/governed-query-policy/purposes",
            {"purpose_code": "semantic_query", "description": "Semantic query"},
        )
    )

    assert response.status_code == 403
    assert json.loads(response.body)["code"] == (
        "governed_query_policy_operator_required"
    )
    assert _CapturingAuthority.calls == []


@pytest.mark.asyncio
async def test_policy_route_rejects_client_owned_authority_fields(monkeypatch) -> None:
    _authenticate(monkeypatch)
    payload = {
        "policy_ref": "policy:semantic-query",
        "policy_version": "v2",
        "purpose_code": "semantic_query",
        "valid_from": NOW.isoformat(),
        "expires_at": (NOW + timedelta(days=30)).isoformat(),
        "tenant_id": "spoofed-tenant",
        "published_by": "human:spoofed",
        "published_at": NOW.isoformat(),
        "content_sha256": "f" * 64,
        "record_sha256": "f" * 64,
    }

    response = await routes.publish_governed_query_policy_version(
        _request("/api/governed-query-policy/versions", payload)
    )

    assert response.status_code == 400
    assert json.loads(response.body)["code"] == (
        "governed_query_policy_contract_invalid"
    )
    assert _CapturingAuthority.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "status_code", "code"),
    [
        (
            GovernedQueryPolicyAuthorityValidationError("invalid record"),
            400,
            "governed_query_policy_contract_invalid",
        ),
        (
            GovernedQueryPolicyAuthorityForbiddenError("tenant denied"),
            403,
            "governed_query_policy_forbidden",
        ),
        (
            GovernedQueryPolicyAuthorityConflictError("immutable conflict"),
            409,
            "governed_query_policy_conflict",
        ),
        (
            GovernedQueryPolicyAuthorityConfigurationError("not configured"),
            503,
            "governed_query_policy_authority_unavailable",
        ),
        (
            GovernedQueryPolicyAuthorityUnavailableError("database unavailable"),
            503,
            "governed_query_policy_authority_unavailable",
        ),
    ],
)
async def test_policy_route_maps_authority_errors(
    monkeypatch, error, status_code: int, code: str
) -> None:
    _authenticate(monkeypatch)
    _CapturingAuthority.error = error

    response = await routes.register_governed_query_purpose(
        _request(
            "/api/governed-query-policy/purposes",
            {"purpose_code": "semantic_query", "description": "Semantic query"},
        )
    )

    assert response.status_code == status_code
    assert json.loads(response.body)["code"] == code


def test_governed_query_policy_routes_are_mounted() -> None:
    from data_agent.frontend_api import get_frontend_api_routes

    expected = {
        "/api/governed-query-policy/purposes",
        "/api/governed-query-policy/versions",
        "/api/governed-query-policy/revocations",
    }

    assert expected <= {route.path for route in routes.get_governed_query_policy_routes()}
    assert expected <= {route.path for route in get_frontend_api_routes()}
