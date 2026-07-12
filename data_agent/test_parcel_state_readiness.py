import pytest

from data_agent.uwm.parcel_state_readiness import build_parcel_state_readiness_product


def test_parcel_state_readiness_keeps_observations_and_transitions_closed():
    product = build_parcel_state_readiness_product(source_assets=[{"asset_id": "dltb", "source_path": "audit.json", "feature_count": 101657, "fields": ["BSM", "DLBM", "DLMC", "TBMJ"], "version_status": "unresolved"}], source_artifacts=["audit.json"])
    assert product["schema"] == "uwm.parcel_land_use_state_readiness.v1"
    assert all(channel["status"] == "unavailable" and channel["value"] is None for channel in product["state_channels"].values())
    assert all(value == "closed" for value in product["state_gate"]["mechanisms"].values())
    assert product["claim_boundary"]["audited_feature_count_not_current_land_use_distribution"] is True
    assert product["fabricated_value_count"] == 0


def test_unresolved_version_cannot_be_observed_t0():
    with pytest.raises(ValueError, match="unresolved_version_cannot_be_observed_state"):
        build_parcel_state_readiness_product(source_assets=[{"asset_id": "bad", "source_path": "audit.json", "version_status": "unresolved", "state_status": "observed_t0"}], source_artifacts=["audit.json"])
