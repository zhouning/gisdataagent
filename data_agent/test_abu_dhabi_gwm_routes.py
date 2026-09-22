"""HTTP contract tests for the Abu Dhabi flood world-model v1 routes."""

from __future__ import annotations

from types import SimpleNamespace

from starlette.applications import Starlette
from starlette.testclient import TestClient

import data_agent.api.abu_dhabi_flood_routes as flood_routes


def _app(monkeypatch) -> Starlette:
    monkeypatch.setattr(
        flood_routes,
        "_get_user_from_request",
        lambda request: SimpleNamespace(
            identifier="test-analyst",
            metadata={"role": "analyst"},
        ),
    )
    monkeypatch.setattr(
        flood_routes,
        "_set_user_context",
        lambda user: (user.identifier, "analyst"),
    )
    return Starlette(routes=flood_routes.get_abu_dhabi_flood_routes())


def test_public_citywide_2d_route_preserves_result_selection(monkeypatch) -> None:
    import data_agent.abu_dhabi_flood_scenario_service as scenario_service

    received: dict[str, object] = {}

    def fake_bootstrap(return_period_years, result_source):
        received.update(
            return_period_years=return_period_years,
            result_source=result_source,
        )
        return {
            "schema": "gwm.abu_dhabi_flood.public_citywide_2d.v1",
            "metadata": {
                "return_period_years": return_period_years,
                "result_source": result_source,
            },
        }

    monkeypatch.setattr(
        scenario_service,
        "public_citywide_2d_bootstrap_payload",
        fake_bootstrap,
    )

    with TestClient(_app(monkeypatch)) as client:
        response = client.get(
            "/api/abu-dhabi/flood/public-citywide-2d/bootstrap",
            params={
                "return_period_years": "100",
                "result_source": "bidirectional_validation",
            },
        )

    assert response.status_code == 200
    assert received == {
        "return_period_years": 100,
        "result_source": "bidirectional_validation",
    }
    assert response.json()["metadata"] == received


def test_frozen_trained_gwm_routes_serve_realtime_inference_without_training(monkeypatch) -> None:
    import data_agent.abu_dhabi_trained_gwm_service as trained_service

    received: dict[str, object] = {}

    monkeypatch.setattr(
        trained_service,
        "available_events",
        lambda: {
            "schema": "gwm.abu_dhabi_flood.trained_events.v1",
            "events": [{"event_id": "admitted-event"}],
        },
    )

    def fake_rollout(payload):
        received.update(payload)
        return {
            "run_id": "trained-gwm-fixture",
            "status": "completed",
            "metadata": {"model_mode": "trained_event_rollout"},
        }

    monkeypatch.setattr(trained_service, "start_rollout", fake_rollout)
    monkeypatch.setattr(
        trained_service,
        "public_run",
        lambda run_id: {"run_id": run_id, "status": "completed"},
    )
    monkeypatch.setattr(
        trained_service,
        "map_bootstrap",
        lambda run_id: {"run_id": run_id, "maximum_depth": {"features": []}},
    )
    monkeypatch.setattr(
        trained_service,
        "map_timeseries",
        lambda run_id, time_index: {
            "run_id": run_id,
            "metadata": {"time_index": time_index},
            "features": [],
        },
    )

    app = _app(monkeypatch)
    route_paths = {route.path for route in app.routes}
    assert "/api/abu-dhabi/flood/gwm/train" not in route_paths
    assert "/api/abu-dhabi/flood/gwm/trained/rainfall-scenarios" not in route_paths

    with TestClient(app) as client:
        events = client.get("/api/abu-dhabi/flood/gwm/trained/events")
        rollout = client.post(
            "/api/abu-dhabi/flood/gwm/trained/rollout",
            json={"eventId": "admitted-event"},
        )
        run_id = rollout.json()["run_id"]
        run = client.get(f"/api/abu-dhabi/flood/gwm/trained/runs/{run_id}")
        map_response = client.get(
            f"/api/abu-dhabi/flood/gwm/trained/runs/{run_id}/map"
        )
        frame = client.get(
            f"/api/abu-dhabi/flood/gwm/trained/runs/{run_id}/map/timeseries",
            params={"time_index": "2"},
        )

    assert events.status_code == 200
    assert events.json()["events"][0]["event_id"] == "admitted-event"
    assert rollout.status_code == 202
    assert received == {"eventId": "admitted-event"}
    assert run.status_code == 200
    assert map_response.status_code == 200
    assert frame.status_code == 200
    assert frame.json()["metadata"]["time_index"] == 2


def test_customer_hotspots_and_historical_replay_are_read_only(monkeypatch) -> None:
    import data_agent.abu_dhabi_customer_hotspots_service as hotspot_service
    import data_agent.abu_dhabi_flood_validation_service as validation_service

    monkeypatch.setattr(
        hotspot_service,
        "customer_hotspots_bootstrap_payload",
        lambda: {
            "schema": "gwm.abu_dhabi_flood.customer_hotspots.v1",
            "metadata": {"feature_count": 506},
            "features": [],
        },
    )
    monkeypatch.setattr(
        validation_service,
        "historical_replay_bootstrap_payload",
        lambda: {
            "schema": "gwm.abu_dhabi_flood.historical_replay.v1",
            "metadata": {"status": "completed"},
        },
    )
    monkeypatch.setattr(
        validation_service,
        "historical_replay_timeseries_payload",
        lambda time_index: {
            "metadata": {"time_index": time_index},
            "features": [],
        },
    )
    monkeypatch.setattr(
        validation_service,
        "historical_replay_report_html",
        lambda language: f"<html lang='{language}'>validated</html>",
    )

    app = _app(monkeypatch)
    methods_by_path = {
        route.path: route.methods
        for route in app.routes
        if getattr(route, "path", None)
    }
    assert methods_by_path[
        "/api/abu-dhabi/flood/customer-hotspots/bootstrap"
    ] == {"GET", "HEAD"}
    assert methods_by_path[
        "/api/abu-dhabi/flood/validation/historical-replay/bootstrap"
    ] == {"GET", "HEAD"}

    with TestClient(app) as client:
        hotspots = client.get("/api/abu-dhabi/flood/customer-hotspots/bootstrap")
        bootstrap = client.get(
            "/api/abu-dhabi/flood/validation/historical-replay/bootstrap"
        )
        frame = client.get(
            "/api/abu-dhabi/flood/validation/historical-replay/timeseries",
            params={"time_index": "3"},
        )
        report = client.get(
            "/api/abu-dhabi/flood/validation/historical-replay/report"
        )

    assert hotspots.status_code == 200
    assert hotspots.json()["metadata"]["feature_count"] == 506
    assert bootstrap.status_code == 200
    assert frame.status_code == 200
    assert frame.json()["metadata"]["time_index"] == 3
    assert report.status_code == 200
    assert "validated" in report.text
