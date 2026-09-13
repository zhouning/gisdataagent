import json
from pathlib import Path

import pytest

from data_agent.uwm.parcel_state_readiness_service import ParcelStateReadinessService


FILES = ("overview", "source_assets", "state_channels", "data_contracts", "state_gate", "map")


def test_service_loads_consistent_closed_bundle(tmp_path):
    for name in FILES:
        payload = {"bundle_id": "parcel-test"}
        if name == "state_channels": payload["state_channels"] = {"current_land_use_code": {"status": "unavailable", "value": None}}
        if name == "state_gate": payload["state_gate"] = {"status": "closed"}
        (tmp_path / f"{name}.json").write_text(json.dumps(payload))
    service = ParcelStateReadinessService(tmp_path)
    assert service.state_channels()["state_channels"]["current_land_use_code"]["value"] is None
    assert service.state_gate()["state_gate"]["status"] == "closed"


def test_service_rejects_mixed_bundles(tmp_path):
    for index, name in enumerate(FILES): (tmp_path / f"{name}.json").write_text(json.dumps({"bundle_id": str(index)}))
    with pytest.raises(ValueError, match="parcel_state_bundle_mismatch"):
        ParcelStateReadinessService(tmp_path)


def test_real_service_exposes_schema_audit_without_state_nodes():
    service = ParcelStateReadinessService(Path("data/uwm_public_proxy/chongqing_central/parcel_state_readiness_chongqing"))
    assert service.overview()["summary"]["audited_feature_count"] == 101657
    assert service.overview()["summary"]["materialized_state_node_count"] == 0
    assert service.overview()["summary"]["observed_transition_count"] == 0
    assert service.state_gate()["state_gate"]["uwm_transition_status"] == "closed"
