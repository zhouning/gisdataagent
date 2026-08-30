from __future__ import annotations

from unittest.mock import MagicMock, patch

from starlette.applications import Starlette
from starlette.testclient import TestClient

from data_agent.api.virtual_routes import get_virtual_source_routes


class _User:
    identifier = "alice"
    metadata = {"role": "analyst", "tenant_id": "tenant-a"}


def _client() -> TestClient:
    return TestClient(Starlette(routes=get_virtual_source_routes()))


def _auth_patches():
    return (
        patch(
            "data_agent.api.virtual_routes._get_user_from_request",
            return_value=_User(),
        ),
        patch(
            "data_agent.api.virtual_routes._set_user_context",
            return_value=("alice", "analyst"),
        ),
    )


def _source() -> dict:
    return {
        "id": 7,
        "source_name": "DMT Buildings",
        "source_type": "arcgis_rest",
        "refresh_policy": "on_demand",
    }


def test_create_ingestion_definition_enqueues_durable_run():
    repository = MagicMock()
    repository.create_definition.return_value = {
        "id": 9,
        "source_id": 7,
        "owner_username": "alice",
        "tenant_id": "tenant-a",
    }
    repository.enqueue_run.return_value = {
        "run_id": "a28d81b4-2235-4ed1-99c2-769ae5972cc3",
        "status": "queued",
    }
    auth, context = _auth_patches()
    with (
        auth,
        context,
        patch("data_agent.virtual_sources.get_virtual_source", return_value=_source()),
        patch("data_agent.data_ingestion.IngestionRepository", return_value=repository),
        patch("data_agent.data_ingestion.start_embedded_ingestion_worker") as start,
    ):
        response = _client().post(
            "/api/virtual-sources/7/ingestions",
            json={
                "target_name": "DMT Buildings ODS",
                "target_mode": "lakehouse_postgis",
                "schedule_policy": "interval:30m",
                "max_records": 500000,
                "page_size": 2000,
                "run_now": True,
            },
        )

    assert response.status_code == 201
    spec = repository.create_definition.call_args.args[3]
    assert spec.target_table == "dmt_buildings_ods"
    assert spec.schedule_policy == "interval:30m"
    assert repository.create_definition.call_args.args[:3] == (7, "alice", "tenant-a")
    repository.enqueue_run.assert_called_once()
    start.assert_called_once()


def test_list_ingestions_returns_definitions_and_runs():
    repository = MagicMock()
    repository.list_definitions.return_value = [{"id": 9, "target_name": "ODS"}]
    repository.list_runs.return_value = [{"run_id": "run-1", "status": "succeeded"}]
    auth, context = _auth_patches()
    with (
        auth,
        context,
        patch("data_agent.virtual_sources.get_virtual_source", return_value=_source()),
        patch("data_agent.data_ingestion.IngestionRepository", return_value=repository),
    ):
        response = _client().get("/api/virtual-sources/7/ingestions")

    assert response.status_code == 200
    assert response.json()["definitions"][0]["target_name"] == "ODS"
    assert response.json()["runs"][0]["status"] == "succeeded"


def test_ingestion_rejects_non_arcgis_source():
    source = {**_source(), "source_type": "wfs"}
    auth, context = _auth_patches()
    with (
        auth,
        context,
        patch("data_agent.virtual_sources.get_virtual_source", return_value=source),
    ):
        response = _client().post(
            "/api/virtual-sources/7/ingestions",
            json={"target_name": "WFS ODS"},
        )
    assert response.status_code == 400
    assert "ArcGIS REST" in response.json()["error"]


def test_cancel_ingestion_run_is_owner_scoped():
    repository = MagicMock()
    repository.request_cancel.return_value = {
        "run_id": "a28d81b4-2235-4ed1-99c2-769ae5972cc3",
        "status": "cancelling",
    }
    auth, context = _auth_patches()
    with (
        auth,
        context,
        patch("data_agent.data_ingestion.IngestionRepository", return_value=repository),
    ):
        response = _client().post(
            "/api/ingestions/runs/a28d81b4-2235-4ed1-99c2-769ae5972cc3/cancel"
        )
    assert response.status_code == 200
    repository.request_cancel.assert_called_once_with(
        "a28d81b4-2235-4ed1-99c2-769ae5972cc3", "alice"
    )


def test_cancel_ingestion_rejects_committing_or_terminal_run():
    repository = MagicMock()
    repository.request_cancel.return_value = None
    auth, context = _auth_patches()
    with (
        auth,
        context,
        patch("data_agent.data_ingestion.IngestionRepository", return_value=repository),
    ):
        response = _client().post(
            "/api/ingestions/runs/a28d81b4-2235-4ed1-99c2-769ae5972cc3/cancel"
        )

    assert response.status_code == 409
    assert "提交阶段" in response.json()["error"]
