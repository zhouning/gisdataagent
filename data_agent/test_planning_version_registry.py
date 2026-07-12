import pytest

from data_agent.uwm.planning_version_registry import build_planning_version_registry


def test_planning_version_registry_keeps_temporal_baseline_closed():
    product = build_planning_version_registry(assets=[{"asset_id": "dltb", "asset_class": "land_use_parcel_layer", "source_path": "audit.json", "feature_count": 10, "approval_status": "unverified"}], source_artifacts=["audit.json"])
    assert product["schema"] == "uwm.planning_parcel_version_registry.v1"
    assert all(channel["status"] == "unavailable" and channel["value"] is None for channel in product["version_channels"].values())
    assert all(value == "closed" for value in product["temporal_gate"]["mechanisms"].values())
    assert product["claim_boundary"]["audit_creation_time_not_plan_effective_date"] is True
    assert product["fabricated_value_count"] == 0


def test_unverified_asset_cannot_be_declared_current():
    with pytest.raises(ValueError, match="unverified_asset_cannot_be_current"):
        build_planning_version_registry(assets=[{"asset_id": "bad", "asset_class": "land_use_parcel_layer", "source_path": "audit.json", "approval_status": "unverified", "version_status": "current"}], source_artifacts=["audit.json"])
