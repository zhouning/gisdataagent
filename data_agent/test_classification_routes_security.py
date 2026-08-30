import asyncio
import json
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

from starlette.requests import Request
from starlette.responses import JSONResponse

from data_agent.api import classification_routes as routes
from data_agent.platform_gateway import GatewayConflictError
from data_agent.security_event_ledger import SecurityEventLedgerUnavailableError
from data_agent.security_event_reconciliation import (
    SecurityEventReconciliationResult,
)


def _request(
    method: str = "GET",
    payload: object | None = None,
    query_string: str = "",
) -> Request:
    body = json.dumps(payload or {}).encode("utf-8")

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(
        {
            "type": "http",
            "method": method,
            "path": "/",
            "headers": [(b"content-type", b"application/json")],
            "query_string": query_string.encode("ascii"),
        },
        receive,
    )


def _authenticate(
    monkeypatch,
    *,
    username: str = "alice",
    role: str = "analyst",
    tenant_id: str = "tenant-a",
):
    user = SimpleNamespace(
        identifier=username,
        metadata={"role": role, "tenant_id": tenant_id},
    )
    monkeypatch.setattr(routes, "_get_user_from_request", lambda request: user)

    def set_context(value):
        routes.current_tenant_id.set(tenant_id)
        return username, role

    monkeypatch.setattr(routes, "_set_user_context", set_context)
    monkeypatch.setattr(
        routes,
        "_append_security_event",
        lambda **kwargs: SimpleNamespace(event_id=uuid4()),
    )
    return user


def _capture_security_events(monkeypatch) -> list[dict]:
    events: list[dict] = []

    def append(**kwargs):
        events.append(kwargs)
        return SimpleNamespace(event_id=uuid4())

    monkeypatch.setattr(routes, "_append_security_event", append)
    return events


def _capture_audit(monkeypatch) -> list[dict]:
    events: list[dict] = []

    def record(username, action, status="success", ip_address=None, details=None):
        events.append(
            {
                "username": username,
                "action": action,
                "status": status,
                "ip_address": ip_address,
                "details": details or {},
            }
        )

    monkeypatch.setattr(routes, "record_audit", record)
    return events


def _admin(monkeypatch, *, tenant_id: str = "tenant-a"):
    routes.current_tenant_id.set(tenant_id)
    user = SimpleNamespace(identifier="admin", metadata={"role": "admin"})
    monkeypatch.setattr(
        routes,
        "_require_admin",
        lambda request: (user, "admin", "admin", None),
    )
    return user


def _asset(asset_id: int, table_name: str) -> dict:
    return {
        "id": asset_id,
        "name": table_name,
        "owner": "alice",
        "shared": False,
        "postgis_table": table_name,
    }


def test_summary_requires_authentication(monkeypatch):
    monkeypatch.setattr(routes, "_get_user_from_request", lambda request: None)

    response = asyncio.run(routes._api_classification_summary(_request()))

    assert response.status_code == 401


def test_summary_applies_explicit_asset_visibility_and_database_context(monkeypatch):
    _authenticate(monkeypatch)
    injected = []
    monkeypatch.setattr(routes, "_inject_user_context", lambda conn: injected.append(conn))

    result = MagicMock()
    result.fetchall.return_value = [
        (
            7,
            "roads",
            "internal",
            "vector",
            "Road network",
            "10",
            "EPSG:4326",
            None,
            None,
            "roads",
            "alice",
            False,
        )
    ]
    conn = MagicMock()
    conn.execute.return_value = result
    engine = MagicMock()
    engine.connect.return_value.__enter__.return_value = conn
    monkeypatch.setattr(routes, "_engine", lambda: engine)

    response = asyncio.run(routes._api_classification_summary(_request()))
    payload = json.loads(response.body)

    assert response.status_code == 200
    assert payload["total"] == 1
    assert payload["assets"][0]["postgis_table"] == "roads"
    assert injected == [conn]
    statement, parameters = conn.execute.call_args.args
    rendered = str(statement)
    assert "owner_username = :username OR is_shared = TRUE" in rendered
    assert "asset_name LIKE 'cq_%'" not in rendered
    assert parameters == {"username": "alice", "is_admin": False}


def test_anonymize_rejects_viewer_and_audits_denial(monkeypatch):
    _authenticate(monkeypatch, role="viewer")
    events = _capture_audit(monkeypatch)
    security_events = _capture_security_events(monkeypatch)

    response = asyncio.run(
        routes._api_classification_anonymize(
            _request(
                "POST",
                {"source_table": "roads", "output_table": "roads_grid"},
            )
        )
    )

    assert response.status_code == 403
    assert events[0]["status"] == "denied"
    assert events[0]["details"]["reason"] == "role_not_allowed"
    assert security_events[0]["phase"] == "denied"
    assert security_events[0]["reason"] == "role_not_allowed"


def test_anonymize_denial_survives_unexpected_ledger_error(monkeypatch):
    _authenticate(monkeypatch, role="viewer")
    monkeypatch.setattr(
        routes,
        "_append_security_event",
        MagicMock(side_effect=RuntimeError("unexpected ledger failure")),
    )

    response = asyncio.run(
        routes._api_classification_anonymize(
            _request("POST", {"source_table": "roads", "output_table": "roads_grid"})
        )
    )

    assert response.status_code == 403


def test_anonymize_requires_tenant_context(monkeypatch):
    _authenticate(monkeypatch, tenant_id="")
    events = _capture_audit(monkeypatch)

    response = asyncio.run(
        routes._api_classification_anonymize(
            _request("POST", {"source_table": "roads", "output_table": "roads_grid"})
        )
    )

    assert response.status_code == 403
    assert events[0]["details"]["reason"] == "tenant_context_required"


def test_anonymize_rejects_identifier_injection_before_catalog_lookup(monkeypatch):
    _authenticate(monkeypatch)
    events = _capture_audit(monkeypatch)
    lookup = MagicMock()
    monkeypatch.setattr(routes, "_lookup_accessible_postgis_asset", lookup)

    response = asyncio.run(
        routes._api_classification_anonymize(
            _request(
                "POST",
                {
                    "source_table": 'roads"; DROP TABLE agent_data_assets; --',
                    "output_table": "roads_grid",
                },
            )
        )
    )

    assert response.status_code == 400
    lookup.assert_not_called()
    assert events[0]["status"] == "denied"
    assert events[0]["details"]["reason"] == "invalid_request"


def test_anonymize_rejects_inaccessible_source_asset(monkeypatch):
    _authenticate(monkeypatch)
    events = _capture_audit(monkeypatch)
    monkeypatch.setattr(
        routes,
        "_lookup_accessible_postgis_asset",
        lambda schema, table, username, role: None,
    )

    response = asyncio.run(
        routes._api_classification_anonymize(
            _request(
                "POST",
                {"source_table": "bob_private", "output_table": "private_grid"},
            )
        )
    )

    assert response.status_code == 403
    assert events[0]["details"]["reason"] == "source_asset_not_accessible"


def test_anonymize_never_overwrites_existing_output(monkeypatch):
    _authenticate(monkeypatch)
    events = _capture_audit(monkeypatch)
    monkeypatch.setattr(
        routes,
        "_lookup_accessible_postgis_asset",
        lambda schema, table, username, role: _asset(1, table),
    )
    monkeypatch.setattr(routes, "_physical_table_exists", lambda schema, table: True)

    response = asyncio.run(
        routes._api_classification_anonymize(
            _request(
                "POST",
                {"source_table": "roads", "output_table": "protected_table"},
            )
        )
    )

    assert response.status_code == 409
    assert events[0]["details"]["reason"] == "output_table_exists"


def test_anonymize_authorized_asset_succeeds_and_is_audited(monkeypatch):
    _authenticate(monkeypatch)
    events = _capture_audit(monkeypatch)
    security_events = _capture_security_events(monkeypatch)
    monkeypatch.setattr(
        routes,
        "_lookup_accessible_postgis_asset",
        lambda schema, table, username, role: _asset(11, table),
    )
    monkeypatch.setattr(routes, "_physical_table_exists", lambda schema, table: False)

    from data_agent import grid_anonymize

    anonymize = MagicMock(
        return_value={
            "status": "ok",
            "output_table": "public.roads_grid",
            "output_row_count": 12,
            "level": "L3",
        }
    )
    monkeypatch.setattr(grid_anonymize, "grid_anonymize_pg", anonymize)

    response = asyncio.run(
        routes._api_classification_anonymize(
            _request(
                "POST",
                {
                    "source_table": "geo.roads",
                    "output_table": "roads_grid",
                    "keep_attrs": ["road_type"],
                },
            )
        )
    )

    assert response.status_code == 200
    assert anonymize.call_args.kwargs["source_schema"] == "geo"
    assert anonymize.call_args.kwargs["output_schema"] == "public"
    assert anonymize.call_args.kwargs["security_tenant_id"] == "tenant-a"
    assert (
        anonymize.call_args.kwargs["security_attempt_id"]
        == str(security_events[0]["attempt_id"])
    )
    assert events[0]["status"] == "success"
    assert events[0]["details"]["source_asset_id"] == 11
    assert [event["phase"] for event in security_events] == ["admitted", "outcome"]
    assert security_events[1]["outcome"] == "success"
    assert security_events[0]["attempt_id"] == security_events[1]["attempt_id"]


def test_anonymize_does_not_run_when_admission_event_fails(monkeypatch):
    _authenticate(monkeypatch)
    monkeypatch.setattr(
        routes,
        "_lookup_accessible_postgis_asset",
        lambda schema, table, username, role: _asset(11, table),
    )
    monkeypatch.setattr(routes, "_physical_table_exists", lambda schema, table: False)
    monkeypatch.setattr(
        routes,
        "_append_security_event",
        MagicMock(side_effect=SecurityEventLedgerUnavailableError("offline")),
    )

    from data_agent import grid_anonymize

    anonymize = MagicMock(return_value={"status": "ok"})
    monkeypatch.setattr(grid_anonymize, "grid_anonymize_pg", anonymize)

    response = asyncio.run(
        routes._api_classification_anonymize(
            _request("POST", {"source_table": "roads", "output_table": "roads_grid"})
        )
    )
    payload = json.loads(response.body)

    assert response.status_code == 503
    assert payload["code"] == "security_ledger_unavailable"
    anonymize.assert_not_called()


def test_anonymize_reports_incomplete_evidence_when_outcome_event_fails(monkeypatch):
    _authenticate(monkeypatch)
    monkeypatch.setattr(
        routes,
        "_lookup_accessible_postgis_asset",
        lambda schema, table, username, role: _asset(11, table),
    )
    monkeypatch.setattr(routes, "_physical_table_exists", lambda schema, table: False)
    append = MagicMock(
        side_effect=[
            SimpleNamespace(event_id=uuid4()),
            SecurityEventLedgerUnavailableError("offline"),
        ]
    )
    monkeypatch.setattr(routes, "_append_security_event", append)

    from data_agent import grid_anonymize

    anonymize = MagicMock(return_value={"status": "ok", "output_row_count": 3})
    monkeypatch.setattr(grid_anonymize, "grid_anonymize_pg", anonymize)

    response = asyncio.run(
        routes._api_classification_anonymize(
            _request("POST", {"source_table": "roads", "output_table": "roads_grid"})
        )
    )
    payload = json.loads(response.body)

    assert response.status_code == 503
    assert payload["code"] == "security_evidence_incomplete"
    anonymize.assert_called_once()


def test_anonymize_submit_creates_governed_run_without_execution_event(monkeypatch):
    _authenticate(monkeypatch)
    security_events = _capture_security_events(monkeypatch)
    audits = _capture_audit(monkeypatch)
    monkeypatch.setattr(
        routes,
        "_lookup_accessible_postgis_asset",
        lambda schema, table, username, role: _asset(17, table),
    )
    monkeypatch.setattr(routes, "_physical_table_exists", lambda schema, table: False)
    captured = {}
    run_spec = object()

    def build_spec(operation_request):
        captured["request"] = operation_request
        return run_spec

    monkeypatch.setattr(routes, "_spatial_anonymization_run_spec", build_spec)
    result = SimpleNamespace(
        request_sha256="a" * 64,
        request_version=SimpleNamespace(resource_version_id=uuid4()),
        run=SimpleNamespace(run_id=uuid4(), status=SimpleNamespace(value="accepted")),
        command=SimpleNamespace(command_id=uuid4()),
        created=True,
    )
    gateway = MagicMock()
    gateway.submit_spatial_anonymization_run.return_value = result
    monkeypatch.setattr(routes, "_platform_gateway", lambda: gateway)

    response = asyncio.run(
        routes._api_classification_anonymize_submit(
            _request(
                "POST",
                {
                    "client_request_id": "spatial-mask-20260803-001",
                    "source_table": "geo.restricted_parcels",
                    "output_table": "restricted_parcels_l3",
                    "keep_attrs": ["tbmj", "dlmc"],
                    "dp_epsilon": 1.0,
                    "dp_numeric_fields": ["tbmj"],
                },
            )
        )
    )
    payload = json.loads(response.body)

    assert response.status_code == 202
    assert payload["run_id"] == str(result.run.run_id)
    assert payload["status"] == "accepted"
    assert security_events == []
    assert audits[0]["status"] == "accepted"
    operation_request = captured["request"]
    assert operation_request.tenant_id == "tenant-a"
    assert operation_request.requester_subject == "human:alice"
    assert operation_request.source_asset_ref == "agent_data_assets:17"
    assert operation_request.keep_attrs == ("dlmc", "tbmj")
    gateway.submit_spatial_anonymization_run.assert_called_once_with(run_spec)


def test_anonymize_submit_returns_conflict_for_client_request_payload_drift(monkeypatch):
    _authenticate(monkeypatch)
    monkeypatch.setattr(
        routes,
        "_lookup_accessible_postgis_asset",
        lambda schema, table, username, role: _asset(17, table),
    )
    monkeypatch.setattr(routes, "_physical_table_exists", lambda schema, table: False)
    monkeypatch.setattr(routes, "_spatial_anonymization_run_spec", lambda request: object())
    gateway = MagicMock()
    gateway.submit_spatial_anonymization_run.side_effect = GatewayConflictError(
        "spatial anonymization request identity already has a different immutable binding"
    )
    monkeypatch.setattr(routes, "_platform_gateway", lambda: gateway)

    response = asyncio.run(
        routes._api_classification_anonymize_submit(
            _request(
                "POST",
                {
                    "client_request_id": "spatial-mask-20260803-001",
                    "source_table": "restricted_parcels",
                    "output_table": "restricted_parcels_l3",
                },
            )
        )
    )

    assert response.status_code == 409
    assert json.loads(response.body)["code"] == "platform_conflict"


def test_verify_requires_access_to_source_and_output(monkeypatch):
    _authenticate(monkeypatch)
    events = _capture_audit(monkeypatch)
    security_events = _capture_security_events(monkeypatch)

    def lookup(schema, table, username, role):
        return _asset(1, table) if table == "roads" else None

    monkeypatch.setattr(routes, "_lookup_accessible_postgis_asset", lookup)

    response = asyncio.run(
        routes._api_classification_verify(
            _request(
                "POST",
                {"source_table": "roads", "output_table": "bob_private_grid"},
            )
        )
    )

    assert response.status_code == 403
    assert events[0]["status"] == "denied"
    assert events[0]["details"]["reason"] == "asset_not_accessible"
    assert security_events[0]["phase"] == "denied"
    assert security_events[0]["reason"] == "asset_not_accessible"


def test_verify_requires_tenant_context(monkeypatch):
    _authenticate(monkeypatch, tenant_id="")
    events = _capture_audit(monkeypatch)

    response = asyncio.run(
        routes._api_classification_verify(
            _request("POST", {"source_table": "roads", "output_table": "roads_grid"})
        )
    )

    assert response.status_code == 403
    assert events[0]["details"]["reason"] == "tenant_context_required"


def test_verify_success_is_audited_with_risk_score(monkeypatch):
    _authenticate(monkeypatch)
    events = _capture_audit(monkeypatch)
    security_events = _capture_security_events(monkeypatch)

    def lookup(schema, table, username, role):
        return _asset(1 if table == "roads" else 2, table)

    monkeypatch.setattr(routes, "_lookup_accessible_postgis_asset", lookup)

    from data_agent import grid_anonymize

    verify = MagicMock(
        return_value={"status": "ok", "overall_risk_score": 8, "verdict": "safe"}
    )
    monkeypatch.setattr(grid_anonymize, "verify_anonymization", verify)

    response = asyncio.run(
        routes._api_classification_verify(
            _request(
                "POST",
                {"source_table": "roads", "output_table": "roads_grid"},
            )
        )
    )

    assert response.status_code == 200
    assert events[0]["status"] == "success"
    assert events[0]["details"]["risk_score"] == 8
    assert [event["phase"] for event in security_events] == ["admitted", "outcome"]
    assert security_events[1]["outcome"] == "success"


def test_verify_does_not_run_when_admission_event_fails(monkeypatch):
    _authenticate(monkeypatch)
    monkeypatch.setattr(
        routes,
        "_lookup_accessible_postgis_asset",
        lambda schema, table, username, role: _asset(1, table),
    )
    monkeypatch.setattr(
        routes,
        "_append_security_event",
        MagicMock(side_effect=SecurityEventLedgerUnavailableError("offline")),
    )

    from data_agent import grid_anonymize

    verify = MagicMock(return_value={"status": "ok"})
    monkeypatch.setattr(grid_anonymize, "verify_anonymization", verify)

    response = asyncio.run(
        routes._api_classification_verify(
            _request("POST", {"source_table": "roads", "output_table": "roads_grid"})
        )
    )
    payload = json.loads(response.body)

    assert response.status_code == 503
    assert payload["code"] == "security_ledger_unavailable"
    verify.assert_not_called()


def test_verify_reports_incomplete_evidence_when_outcome_event_fails(monkeypatch):
    _authenticate(monkeypatch)
    monkeypatch.setattr(
        routes,
        "_lookup_accessible_postgis_asset",
        lambda schema, table, username, role: _asset(1, table),
    )
    append = MagicMock(
        side_effect=[
            SimpleNamespace(event_id=uuid4()),
            SecurityEventLedgerUnavailableError("offline"),
        ]
    )
    monkeypatch.setattr(routes, "_append_security_event", append)

    from data_agent import grid_anonymize

    verify = MagicMock(return_value={"status": "ok", "overall_risk_score": 7})
    monkeypatch.setattr(grid_anonymize, "verify_anonymization", verify)

    response = asyncio.run(
        routes._api_classification_verify(
            _request("POST", {"source_table": "roads", "output_table": "roads_grid"})
        )
    )
    payload = json.loads(response.body)

    assert response.status_code == 503
    assert payload["code"] == "security_evidence_incomplete"
    verify.assert_called_once()


def test_catalog_lookup_injects_context_and_fails_closed(monkeypatch):
    _authenticate(monkeypatch)
    injected = []
    monkeypatch.setattr(routes, "_inject_user_context", lambda conn: injected.append(conn))

    result = MagicMock()
    result.fetchone.return_value = None
    conn = MagicMock()
    conn.execute.return_value = result
    engine = MagicMock()
    engine.connect.return_value.__enter__.return_value = conn
    monkeypatch.setattr(routes, "_engine", lambda: engine)

    asset = routes._lookup_accessible_postgis_asset(
        "public", "bob_private", "alice", "analyst"
    )

    assert asset is None
    assert injected == [conn]
    statement, parameters = conn.execute.call_args.args
    assert ":is_admin" in str(statement)
    assert "owner_username = :username" in str(statement)
    assert parameters["is_admin"] is False


def _reconciliation_result(status: str):
    return SecurityEventReconciliationResult(
        tenant_id="tenant-a",
        attempt_id=uuid4(),
        admission_event_id=uuid4(),
        action="data_anonymize",
        status=status,
        reason="test",
        resource_ref="postgis://geo/roads->postgis://public/roads_grid",
        receipt_sha256="a" * 64 if status != "manual_review" else None,
        outcome_event_id=uuid4() if status == "reconciled" else None,
    )


def test_security_reconciliation_preview_is_admin_only_and_read_only(monkeypatch):
    _admin(monkeypatch)
    reconcile = MagicMock(return_value=[_reconciliation_result("ready")])
    monkeypatch.setattr(routes, "reconcile_security_event_outcomes", reconcile)

    response = asyncio.run(
        routes._api_security_reconciliation_list(
            _request(query_string="minimum_age_seconds=0&limit=5")
        )
    )
    payload = json.loads(response.body)

    assert response.status_code == 200
    assert payload["summary"] == {"ready": 1}
    assert reconcile.call_args.kwargs["apply"] is False
    assert reconcile.call_args.kwargs["limit"] == 5


def test_security_reconciliation_apply_requires_exact_attempt(monkeypatch):
    _admin(monkeypatch)
    events = _capture_audit(monkeypatch)
    result = _reconciliation_result("reconciled")
    reconcile = MagicMock(return_value=[result])
    monkeypatch.setattr(routes, "reconcile_security_event_outcomes", reconcile)

    response = asyncio.run(
        routes._api_security_reconciliation_apply(
            _request(
                "POST",
                {
                    "attempt_id": str(result.attempt_id),
                    "minimum_age_seconds": 0,
                },
            )
        )
    )

    assert response.status_code == 200
    assert reconcile.call_args.kwargs["attempt_id"] == result.attempt_id
    assert reconcile.call_args.kwargs["apply"] is True
    assert reconcile.call_args.kwargs["actor_subject"] == "human:admin"
    assert events[0]["action"] == "security_event_reconcile"
    assert events[0]["status"] == "success"


def test_security_reconciliation_refuses_manual_review_candidate(monkeypatch):
    _admin(monkeypatch)
    _capture_audit(monkeypatch)
    result = _reconciliation_result("manual_review")
    monkeypatch.setattr(
        routes,
        "reconcile_security_event_outcomes",
        lambda *args, **kwargs: [result],
    )

    response = asyncio.run(
        routes._api_security_reconciliation_apply(
            _request("POST", {"attempt_id": str(result.attempt_id)})
        )
    )

    assert response.status_code == 409


def test_security_reconciliation_rejects_missing_attempt_id(monkeypatch):
    _admin(monkeypatch)

    response = asyncio.run(
        routes._api_security_reconciliation_apply(_request("POST", {}))
    )

    assert response.status_code == 400


def test_security_reconciliation_routes_reject_non_admin(monkeypatch):
    monkeypatch.setattr(
        routes,
        "_require_admin",
        lambda request: (
            None,
            None,
            None,
            JSONResponse({"error": "Admin required"}, status_code=403),
        ),
    )

    response = asyncio.run(routes._api_security_reconciliation_list(_request()))

    assert response.status_code == 403


def test_security_reconciliation_routes_are_mounted():
    paths = {route.path for route in routes.get_classification_routes()}

    assert "/api/classification/security/incomplete" in paths
    assert "/api/classification/security/reconcile" in paths
    assert "/api/classification/anonymize/submit" in paths
