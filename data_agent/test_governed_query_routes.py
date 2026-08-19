from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from starlette.requests import Request

from data_agent.api import governed_query_routes as routes
from data_agent.capability_registry import GOVERNED_SEMANTIC_QUERY
from data_agent.governed_query_security import (
    GovernedQuerySecurityDecision,
    InMemoryGovernedQuerySecurityAudit,
    _fingerprint,
    configure_governed_query_security_port_resolver,
)
from data_agent.metric_query import (
    MetricQueryPlanner,
    MetricQueryRequest,
    MetricQuerySecurityContext,
)
from data_agent.metric_query_execution import MetricQueryExecutionAuthority
from data_agent.platform_contracts import ResourceVersion
from data_agent.test_metric_query_execution import RUN_ID, _record
from data_agent.test_metric_query_planning import (
    NOW,
    TENANT,
    _active_projection,
    _metric,
)


def _request(payload: object, headers: list[tuple[bytes, bytes]] | None = None) -> Request:
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
            "path": "/api/governed-query",
            "headers": headers or [],
            "query_string": b"",
        },
        receive=receive,
    )


def _path_request(
    method: str,
    path: str,
    *,
    payload: object | None = None,
    path_params: dict | None = None,
) -> Request:
    body = json.dumps(payload).encode() if payload is not None else b""
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
            "method": method,
            "path": path,
            "headers": [],
            "query_string": b"",
            "path_params": path_params or {},
        },
        receive=receive,
    )


def _payload() -> dict:
    return {
        "request_id": "api-query-001",
        "question": "土地是什么？",
        "purpose": "authenticated ontology query",
        "channel": "ontology",
        "ontology_plan": {
            "query_type": "concept_explanation",
            "subject": "土地",
        },
    }


def _authenticate(monkeypatch, *, tenant_id: str = "tenant-a") -> None:
    user = SimpleNamespace(
        identifier="analyst-a",
        metadata={"tenant_id": tenant_id, "role": "analyst"},
    )
    monkeypatch.setattr(routes, "_get_user_from_request", lambda request: user)


@pytest.fixture(autouse=True)
def _reset_query_security(monkeypatch):
    monkeypatch.delenv("GDA_GOVERNED_QUERY_SECURITY_REQUIRED", raising=False)
    configure_governed_query_security_port_resolver(None)
    yield
    configure_governed_query_security_port_resolver(None)


def _security_decision(request, *, effect: str = "allow"):
    now = datetime.now(UTC)
    values = {
        "request": request,
        "effect": effect,
        "policy_ref": "policy:semantic-query",
        "policy_version": "v1",
        "evaluator_subject": "workload:policy-engine",
        "obligations": (),
        "decided_at": now,
        "expires_at": now + timedelta(minutes=5),
        "authority_live_read_performed": True,
        "provider_access_performed": False,
    }
    return GovernedQuerySecurityDecision(
        **values,
        decision_sha256=_fingerprint(
            GovernedQuerySecurityDecision.schema_id,
            values,
            "decision_sha256",
        ),
    )


class _SecurityResolver:
    def __init__(self, *, effect: str = "allow"):
        self.effect = effect
        self.audit = InMemoryGovernedQuerySecurityAudit("tenant-a")
        self.reader_calls = 0

    def resolve(self, tenant_id: str):
        resolver = self

        class Reader:
            tenant_id = "tenant-a"

            def governed_query_security_decision_current(self, request):
                resolver.reader_calls += 1
                return _security_decision(request, effect=resolver.effect)

        return Reader(), self.audit


@pytest.mark.asyncio
async def test_route_requires_authentication(monkeypatch) -> None:
    monkeypatch.setattr(routes, "_get_user_from_request", lambda request: None)
    response = await routes.governed_query_execute(_request(_payload()))
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_route_requires_server_bound_tenant(monkeypatch) -> None:
    _authenticate(monkeypatch, tenant_id="")
    response = await routes.governed_query_execute(_request(_payload()))
    assert response.status_code == 403
    assert json.loads(response.body)["code"] == "tenant_context_required"


@pytest.mark.asyncio
async def test_route_rejects_client_owned_identity(monkeypatch) -> None:
    _authenticate(monkeypatch)
    response = await routes.governed_query_execute(
        _request({**_payload(), "tenant_id": "spoofed"})
    )
    assert response.status_code == 400
    assert json.loads(response.body)["code"] == "query_contract_invalid"


@pytest.mark.asyncio
async def test_route_rejects_capability_contract_drift(monkeypatch) -> None:
    _authenticate(monkeypatch)
    response = await routes.governed_query_execute(
        _request(
            _payload(),
            [(b"x-gda-capability-fingerprint", b"f" * 64)],
        )
    )
    payload = json.loads(response.body)
    assert response.status_code == 409
    assert payload["code"] == "capability_contract_mismatch"
    assert payload["fingerprint"] == GOVERNED_SEMANTIC_QUERY.fingerprint


@pytest.mark.asyncio
async def test_route_builds_subject_from_authentication_context(monkeypatch) -> None:
    _authenticate(monkeypatch)
    response = await routes.governed_query_execute(_request(_payload()))
    payload = json.loads(response.body)

    assert response.status_code == 200
    assert payload["status"] == "completed"
    assert payload["subject_context"]["tenant_id"] == "tenant-a"
    assert payload["subject_context"]["subject_id"] == "analyst-a"
    assert payload["subject_context"]["roles"] == ["analyst"]
    assert payload["evidence_bundle"]["verification"]["valid"] is True


@pytest.mark.asyncio
async def test_route_required_security_without_resolver_fails_closed(
    monkeypatch,
) -> None:
    _authenticate(monkeypatch)
    monkeypatch.setenv("GDA_GOVERNED_QUERY_SECURITY_REQUIRED", "1")

    response = await routes.governed_query_execute(_request(_payload()))
    payload = json.loads(response.body)

    assert response.status_code == 503
    assert payload["code"] == "query_security_unavailable"
    assert "no port resolver" in payload["error"]


@pytest.mark.asyncio
async def test_route_required_security_resolves_live_ports_and_audits(
    monkeypatch,
) -> None:
    _authenticate(monkeypatch)
    monkeypatch.setenv("GDA_GOVERNED_QUERY_SECURITY_REQUIRED", "1")
    resolver = _SecurityResolver()
    configure_governed_query_security_port_resolver(resolver)

    response = await routes.governed_query_execute(_request(_payload()))
    payload = json.loads(response.body)

    assert response.status_code == 200
    assert payload["status"] == "completed"
    assert resolver.reader_calls == 1
    assert len(resolver.audit.admissions) == 1
    assert len(resolver.audit.outcomes) == 1
    assert resolver.audit.outcomes[0].outcome == "success"


@pytest.mark.asyncio
async def test_route_required_security_deny_never_executes_adapter(
    monkeypatch,
) -> None:
    _authenticate(monkeypatch)
    monkeypatch.setenv("GDA_GOVERNED_QUERY_SECURITY_REQUIRED", "1")
    resolver = _SecurityResolver(effect="deny")
    configure_governed_query_security_port_resolver(resolver)
    calls = 0

    def unexpected(*args, **kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("query adapter must not be called")

    monkeypatch.setattr(
        "data_agent.governed_query.OntologyQueryAdapter.execute", unexpected
    )
    response = await routes.governed_query_execute(_request(_payload()))
    payload = json.loads(response.body)

    assert response.status_code == 200
    assert payload["status"] == "not_admitted"
    assert calls == 0
    assert resolver.audit.admissions == []


@pytest.mark.asyncio
async def test_route_invalid_security_required_flag_fails_closed(
    monkeypatch,
) -> None:
    _authenticate(monkeypatch)
    monkeypatch.setenv("GDA_GOVERNED_QUERY_SECURITY_REQUIRED", "maybe")

    response = await routes.governed_query_execute(_request(_payload()))
    payload = json.loads(response.body)

    assert response.status_code == 503
    assert payload["code"] == "query_security_unavailable"
    assert "must be a boolean" in payload["error"]


@pytest.mark.asyncio
async def test_route_security_resolver_failure_fails_closed(
    monkeypatch,
) -> None:
    _authenticate(monkeypatch)
    monkeypatch.setenv("GDA_GOVERNED_QUERY_SECURITY_REQUIRED", "1")

    class BrokenResolver:
        def resolve(self, tenant_id):
            raise RuntimeError("policy control plane unavailable")

    configure_governed_query_security_port_resolver(BrokenResolver())
    response = await routes.governed_query_execute(_request(_payload()))
    payload = json.loads(response.body)

    assert response.status_code == 503
    assert payload["code"] == "query_security_unavailable"
    assert "resolution failed" in payload["error"]


@pytest.mark.asyncio
async def test_route_returns_202_for_new_metric_run_admission(monkeypatch) -> None:
    _authenticate(monkeypatch, tenant_id=TENANT)
    expected_plan = MetricQueryPlanner().plan_from(
        MetricQueryRequest(metric_name="land_area"),
        MetricQuerySecurityContext(
            tenant_id=TENANT,
            subject_ref="human:analyst-a",
            roles=("analyst",),
            purpose="natural_resource_reporting",
        ),
        _metric(),
        (_active_projection(),),
        now=NOW,
    )
    base = _record()
    record = base.model_copy(update={
        "admission": base.admission.model_copy(update={
            "plan": expected_plan,
            "cache_key": expected_plan.cache_key,
            "client_request_id": "metric-api-run-001",
        }),
        "run": base.run.model_copy(update={
            "run_id": RUN_ID,
            "config_fingerprint": expected_plan.cache_key,
        }),
    })
    monkeypatch.setattr(
        MetricQueryPlanner,
        "plan",
        lambda self, request, security, now=None: expected_plan,
    )
    monkeypatch.setattr(
        MetricQueryExecutionAuthority,
        "admit",
        lambda self, plan, security, client_request_id: record,
    )
    metric_payload = {
        "request_id": "metric-api-run-001",
        "question": "提交指标运行",
        "purpose": "metric run admission",
        "purpose_code": "natural_resource_reporting",
        "channel": "metric",
        "metric_request": {"metric_name": "land_area"},
        "metric_execution_mode": "admit_run",
    }

    response = await routes.governed_query_execute(_request(metric_payload))
    payload = json.loads(response.body)

    assert response.status_code == 202
    assert payload["status"] == "run_admitted"
    assert payload["run_ref"]["run_id"] == str(RUN_ID)
    assert payload["run_ref"]["client_request_id"] == "metric-api-run-001"
    assert payload["evidence_bundle"]["evidence"][-1]["source_kind"] == "execution_plan"


def test_governed_query_route_is_mounted() -> None:
    from data_agent.frontend_api import get_frontend_api_routes

    mounted = {route.path for route in get_frontend_api_routes()}
    assert "/api/governed-query" in mounted
    assert (
        "/api/governed-query/nl2sql-source-bindings/activate" in mounted
    )


@pytest.mark.asyncio
async def test_activate_nl2sql_binding_requires_operator_role(monkeypatch) -> None:
    _authenticate(monkeypatch)
    response = await routes.activate_nl2sql_source_binding(
        _path_request(
            "POST",
            "/api/governed-query/nl2sql-source-bindings/activate",
            payload={
                "semantic_source_name": "land_parcels_snapshot",
                "execution_engine": "postgis",
                "physical_locator": "land_parcels_snapshot",
                "resource_version_id": "00000000-0000-4000-8000-000000000601",
            },
        )
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_activate_nl2sql_binding_uses_server_tenant_and_resource_version(
    monkeypatch,
) -> None:
    version = ResourceVersion(
        tenant_id="tenant-a",
        resource_urn="gda://tenant-a/dataset/land-parcels",
        resource_version_id="00000000-0000-4000-8000-000000000601",
        version_key="sha256-aaaaaaaaaaaa",
        content_sha256="a" * 64,
        authority_version_ref={
            "postgis_table": "land_parcels_snapshot",
            "source_mode": "immutable_snapshot",
        },
        created_by="workload:ingestion-provider",
        created_at=NOW,
    )
    user = SimpleNamespace(
        identifier="operator-a",
        metadata={"tenant_id": "tenant-a", "role": "platform_operator"},
    )
    monkeypatch.setattr(routes, "_get_user_from_request", lambda request: user)
    captured = {}
    monkeypatch.setattr(
        routes.PlatformGateway,
        "get_resource_version",
        lambda self, tenant_id, resource_version_id: (
            captured.update({"tenant_id": tenant_id}) or version
        ),
    )

    def activate(self, binding, subject):
        captured["binding"] = binding
        captured["subject"] = subject
        return binding

    monkeypatch.setattr(routes.NL2SQLSourceAuthority, "activate", activate)
    response = await routes.activate_nl2sql_source_binding(
        _path_request(
            "POST",
            "/api/governed-query/nl2sql-source-bindings/activate",
            payload={
                "semantic_source_name": "land_parcels_snapshot",
                "execution_engine": "postgis",
                "physical_locator": "land_parcels_snapshot",
                "resource_version_id": str(version.resource_version_id),
            },
        )
    )

    assert response.status_code == 200
    assert captured["tenant_id"] == "tenant-a"
    assert captured["binding"].content_sha256 == "a" * 64
    assert captured["subject"].roles == ("platform_operator",)


@pytest.mark.asyncio
async def test_get_nl2sql_binding_distinguishes_missing_from_unavailable(
    monkeypatch,
) -> None:
    _authenticate(monkeypatch)

    def missing(self, tenant_id, semantic_source_name, execution_engine):
        raise routes.NL2SQLSourceAuthorityError("no active source binding")

    monkeypatch.setattr(routes.NL2SQLSourceAuthority, "resolve", missing)
    request = _path_request(
        "GET",
        "/api/governed-query/nl2sql-source-bindings/postgis/land_parcels_snapshot",
        path_params={
            "execution_engine": "postgis",
            "semantic_source_name": "land_parcels_snapshot",
        },
    )
    response = await routes.get_nl2sql_source_binding(request)
    assert response.status_code == 404
    assert json.loads(response.body)["code"] == "nl2sql_source_binding_not_found"

    def unavailable(self, tenant_id, semantic_source_name, execution_engine):
        raise routes.NL2SQLSourceAuthorityUnavailableError(
            "source binding authority unavailable"
        )

    monkeypatch.setattr(routes.NL2SQLSourceAuthority, "resolve", unavailable)
    response = await routes.get_nl2sql_source_binding(request)
    assert response.status_code == 503
    assert json.loads(response.body)["code"] == "nl2sql_source_binding_unavailable"
