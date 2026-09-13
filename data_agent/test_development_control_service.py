import json
from pathlib import Path

import pytest

from data_agent.uwm.development_control_service import DevelopmentControlService


FILES = ("overview", "rule_assets", "dcr_channels", "data_contracts", "execution_gate", "map")


def test_development_control_service_loads_one_fail_closed_bundle(tmp_path):
    for name in FILES:
        payload = {"bundle_id": "development-control-test"}
        if name == "overview":
            payload["summary"] = {"available_dcr_channel_count": 0}
        if name == "dcr_channels":
            payload["dcr_channels"] = {"floor_area_ratio": {"status": "unavailable", "value": None}}
        if name == "execution_gate":
            payload["execution_gate"] = {"status": "closed", "mechanisms": {"project_compliance_decision": "closed"}}
        (tmp_path / f"{name}.json").write_text(json.dumps(payload))

    service = DevelopmentControlService(tmp_path)

    assert service.overview()["summary"]["available_dcr_channel_count"] == 0
    assert service.dcr_channels()["dcr_channels"]["floor_area_ratio"]["value"] is None
    assert service.execution_gate()["execution_gate"]["status"] == "closed"


def test_development_control_service_rejects_mixed_bundles(tmp_path):
    for index, name in enumerate(FILES):
        (tmp_path / f"{name}.json").write_text(json.dumps({"bundle_id": f"bundle-{index}"}))
    with pytest.raises(ValueError, match="development_control_bundle_mismatch"):
        DevelopmentControlService(tmp_path)


def test_real_development_control_service_is_fail_closed():
    service = DevelopmentControlService(Path("data/uwm_public_proxy/chongqing_central/development_control_chongqing"))
    assert service.overview()["summary"]["rule_asset_count"] == 9
    assert service.overview()["summary"]["executable_site_rule_count"] == 0
    assert all(channel["value"] is None for channel in service.dcr_channels()["dcr_channels"].values())
    assert service.execution_gate()["execution_gate"]["status"] == "closed"
