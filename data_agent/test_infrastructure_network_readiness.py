import pytest

from data_agent.uwm.infrastructure_network_readiness import build_infrastructure_network_readiness_product


def test_infrastructure_product_separates_visible_assets_from_utilities():
    product = build_infrastructure_network_readiness_product(assets=[{"asset_id": "roads", "asset_role": "visible_road_inventory", "source_path": "audit.json", "feature_count": 10}], source_artifacts=["audit.json"])
    assert product["schema"] == "uwm.infrastructure_network_readiness.v1"
    assert all(channel["status"] == "unavailable" and channel["value"] is None for channel in product["utility_channels"].values())
    assert all(value == "closed" for value in product["kernel_gate"]["mechanisms"].values())
    assert product["claim_boundary"]["road_line_not_utility_pipe_or_cable"] is True
    assert product["fabricated_value_count"] == 0


def test_commuting_proxy_cannot_be_telecom_network():
    with pytest.raises(ValueError, match="commuting_proxy_not_telecom_network"):
        build_infrastructure_network_readiness_product(assets=[{"asset_id": "od", "asset_role": "telecom_network_observation", "source_path": "audit.json", "source_kind": "commuting_od_proxy"}], source_artifacts=["audit.json"])
