import json
from pathlib import Path

import pytest

from data_agent.uwm.planning_version_registry_service import PlanningVersionRegistryService


FILES = ("overview", "version_assets", "version_channels", "data_contracts", "temporal_gate", "map")


def test_service_loads_consistent_closed_bundle(tmp_path):
    for name in FILES:
        payload = {"bundle_id": "version-test"}
        if name == "version_assets": payload["version_assets"] = [{"asset_id": "a", "approval_status": "unverified"}]
        if name == "temporal_gate": payload["temporal_gate"] = {"status": "closed"}
        (tmp_path / f"{name}.json").write_text(json.dumps(payload))
    service = PlanningVersionRegistryService(tmp_path)
    assert service.version_assets()["version_assets"][0]["approval_status"] == "unverified"
    assert service.temporal_gate()["temporal_gate"]["status"] == "closed"


def test_service_rejects_mixed_bundles(tmp_path):
    for index, name in enumerate(FILES): (tmp_path / f"{name}.json").write_text(json.dumps({"bundle_id": str(index)}))
    with pytest.raises(ValueError, match="planning_version_bundle_mismatch"):
        PlanningVersionRegistryService(tmp_path)


def test_real_service_has_four_assets_and_no_current_version():
    service = PlanningVersionRegistryService(Path("data/uwm_public_proxy/chongqing_central/planning_version_registry_chongqing"))
    assert service.overview()["summary"]["version_asset_count"] == 4
    assert service.overview()["summary"]["authoritative_current_version_count"] == 0
    assert all(asset["approval_status"] == "unverified" for asset in service.version_assets()["version_assets"])
    assert service.temporal_gate()["temporal_gate"]["uwm_temporal_baseline_status"] == "closed"
