import argparse
from unittest.mock import patch

import pandas as pd
import pytest

from data_agent.migration_runner import MigrationStateError
from data_agent.virtual_source_operator import (
    _export_discovery,
    _onboard_database,
    _query_database,
    _rediscover_source,
)


@pytest.mark.asyncio
async def test_onboard_database_fails_before_reading_credentials_when_control_plane_is_not_ready():
    args = argparse.Namespace()
    error = MigrationStateError("control plane is not ready")

    with (
        patch("data_agent.migration_runner.verify_schema_state", side_effect=error),
        patch("data_agent.virtual_source_operator._required_secret") as required_secret,
    ):
        result = await _onboard_database(args)

    assert result == {
        "status": "error",
        "stage": "control_plane_schema",
        "message": "control plane is not ready",
    }
    required_secret.assert_not_called()


@pytest.mark.asyncio
async def test_onboard_database_updates_exact_source_id_without_renaming():
    args = argparse.Namespace(
        source_id=12,
        name=None,
        owner="abu-dhabi-site-operator",
        endpoint="postgresql://approved-host:5444/liveability_data",
        schema=["public"],
        username="postgres",
        discovery_limit=5000,
        statement_timeout_ms=15_000,
        lock_timeout_ms=2000,
        max_rows=1000,
    )
    existing = {
        "id": 12,
        "source_name": "abu-dhabi-liveability-dev",
        "source_type": "database",
        "enabled": False,
    }
    discovery = {
        "status": "ok",
        "discovery_status": "succeeded",
        "discovery_fingerprint": "discovery-sha",
        "profile_fingerprint": "profile-sha",
        "snapshot": {"contains_source_rows": False},
        "profile": {"metadata_only": True},
    }

    with (
        patch("data_agent.migration_runner.verify_schema_state"),
        patch("data_agent.virtual_sources.list_virtual_sources", return_value=[existing]),
        patch(
            "data_agent.virtual_sources.update_virtual_source",
            return_value={"status": "ok"},
        ) as update,
        patch("data_agent.virtual_sources.create_virtual_source") as create,
        patch(
            "data_agent.virtual_sources.check_source_health",
            return_value={"health": "healthy"},
        ),
        patch(
            "data_agent.virtual_sources.discover_virtual_source",
            return_value=discovery,
        ),
        patch(
            "data_agent.virtual_source_operator._required_secret",
            return_value="runtime-secret",
        ),
        patch.dict("os.environ", {"CHAINLIT_AUTH_SECRET": "control-secret"}),
    ):
        result = await _onboard_database(args)

    assert result["status"] == "ok"
    assert result["source_id"] == 12
    assert result["source_name"] == "abu-dhabi-liveability-dev"
    assert result["registration"] == "updated"
    assert update.call_args.args[:2] == (12, "abu-dhabi-site-operator")
    assert update.call_args.kwargs["query_config"]["allowed_schemas"] == ["public"]
    create.assert_not_called()


def test_export_discovery_returns_only_persisted_metadata():
    args = argparse.Namespace(source_id=13, owner="abu-dhabi-site-operator")
    discovery = {
        "source_id": 13,
        "source_name": "abu-dhabi-makani-dev",
        "discovery_snapshot": {
            "resource_count": 138,
            "contains_source_rows": False,
        },
        "discovery_fingerprint": "discovery-sha",
        "profile_snapshot": {"metadata_only": True},
        "profile_fingerprint": "profile-sha",
    }

    with (
        patch("data_agent.migration_runner.verify_schema_state"),
        patch(
            "data_agent.virtual_sources.get_virtual_source_discovery",
            return_value=discovery,
        ),
    ):
        result = _export_discovery(args)

    assert result == {"status": "ok", **discovery}
    assert "auth_config" not in result


@pytest.mark.asyncio
async def test_rediscover_source_verifies_expected_fingerprints():
    args = argparse.Namespace(
        source_id=14,
        owner="abu-dhabi-site-operator",
        expected_discovery_fingerprint="discovery-sha",
        expected_profile_fingerprint="profile-sha",
    )
    source = {"source_type": "database", "enabled": True}
    discovery = {
        "status": "ok",
        "discovery_status": "succeeded",
        "discovery_fingerprint": "discovery-sha",
        "profile_fingerprint": "profile-sha",
        "snapshot": {"contains_source_rows": False},
        "profile": {"metadata_only": True},
    }

    with (
        patch("data_agent.migration_runner.verify_schema_state"),
        patch("data_agent.virtual_sources.get_virtual_source", return_value=source),
        patch(
            "data_agent.virtual_sources.discover_virtual_source",
            return_value=discovery,
        ),
    ):
        result = await _rediscover_source(args)

    assert result["status"] == "ok"
    assert result["fingerprint_stable"] is True
    assert result["snapshot"]["contains_source_rows"] is False


@pytest.mark.asyncio
async def test_rediscover_source_fails_closed_on_discovery_drift():
    args = argparse.Namespace(
        source_id=14,
        owner="abu-dhabi-site-operator",
        expected_discovery_fingerprint="previous-sha",
        expected_profile_fingerprint=None,
    )
    discovery = {
        "status": "ok",
        "discovery_status": "succeeded",
        "discovery_fingerprint": "new-sha",
        "profile_fingerprint": "profile-sha",
        "snapshot": {"contains_source_rows": False},
        "profile": {"metadata_only": True},
    }

    with (
        patch("data_agent.migration_runner.verify_schema_state"),
        patch(
            "data_agent.virtual_sources.get_virtual_source",
            return_value={"source_type": "database", "enabled": True},
        ),
        patch(
            "data_agent.virtual_sources.discover_virtual_source",
            return_value=discovery,
        ),
    ):
        result = await _rediscover_source(args)

    assert result["status"] == "error"
    assert result["stage"] == "discovery_stability"
    assert result["fingerprint_stable"] is False
    assert result["fingerprint_mismatches"]["discovery_fingerprint"] == {
        "expected": "previous-sha",
        "actual": "new-sha",
    }


@pytest.mark.asyncio
async def test_query_database_returns_fingerprint_without_rows_by_default(tmp_path):
    sql_file = tmp_path / "gold.sql"
    sql_file.write_text(
        "SELECT status, COUNT(*) AS asset_count FROM layer.st_pipeline GROUP BY status",
        encoding="utf-8",
    )
    args = argparse.Namespace(
        source_id=13,
        owner="abu-dhabi-site-operator",
        sql_file=sql_file,
        geom_column="",
        limit=100,
        include_rows=False,
    )
    source = {
        "source_type": "database",
        "enabled": True,
        "query_config": {"allowed_schemas": ["layer"]},
    }
    frame = pd.DataFrame([{"status": "ACTIVE", "asset_count": 3}])

    with (
        patch("data_agent.migration_runner.verify_schema_state"),
        patch("data_agent.virtual_sources.get_virtual_source", return_value=source),
        patch(
            "data_agent.virtual_sources.query_virtual_source",
            return_value=frame,
        ) as query,
    ):
        result = await _query_database(args)

    assert result["status"] == "ok"
    assert result["row_count"] == 1
    assert len(result["result_fingerprint"]) == 64
    assert "rows" not in result
    assert query.call_args.kwargs["extra_params"]["sql"].startswith("SELECT status")
