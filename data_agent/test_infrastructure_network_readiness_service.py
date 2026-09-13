import json
from pathlib import Path

import pytest

from data_agent.uwm.infrastructure_network_readiness_service import InfrastructureNetworkReadinessService


FILES = ("overview", "infrastructure_assets", "utility_channels", "data_contracts", "kernel_gate", "map")


def test_service_loads_consistent_closed_bundle(tmp_path):
    for name in FILES:
        payload = {"bundle_id": "infra-test"}
        if name == "utility_channels": payload["utility_channels"] = {"water_supply_network": {"status": "unavailable", "value": None}}
        if name == "kernel_gate": payload["kernel_gate"] = {"status": "closed"}
        (tmp_path / f"{name}.json").write_text(json.dumps(payload))
    service = InfrastructureNetworkReadinessService(tmp_path)
    assert service.utility_channels()["utility_channels"]["water_supply_network"]["value"] is None
    assert service.kernel_gate()["kernel_gate"]["status"] == "closed"


def test_service_rejects_mixed_bundles(tmp_path):
    for index, name in enumerate(FILES): (tmp_path / f"{name}.json").write_text(json.dumps({"bundle_id": str(index)}))
    with pytest.raises(ValueError, match="infrastructure_network_bundle_mismatch"):
        InfrastructureNetworkReadinessService(tmp_path)


def test_real_service_has_visible_assets_but_no_utility_states():
    service = InfrastructureNetworkReadinessService(Path("data/uwm_public_proxy/chongqing_central/infrastructure_network_readiness_chongqing"))
    assert service.overview()["summary"]["visible_road_feature_count"] == 50366
    assert service.overview()["summary"]["visible_building_feature_count"] == 107452
    assert service.overview()["summary"]["materialized_utility_state_count"] == 0
    assert service.kernel_gate()["kernel_gate"]["uwm_cascade_kernel_status"] == "closed"
