import json

import pytest

from data_agent.uwm.asset_lifecycle_readiness_service import AssetLifecycleReadinessService


FILES = ("overview", "source_products", "lifecycle_channels", "data_contracts", "lifecycle_gate", "map")


def test_service_loads_consistent_closed_bundle(tmp_path):
    for name in FILES:
        payload = {"bundle_id": "asset-test"}
        if name == "lifecycle_gate": payload["lifecycle_gate"] = {"status": "closed"}
        (tmp_path / f"{name}.json").write_text(json.dumps(payload))
    assert AssetLifecycleReadinessService(tmp_path).lifecycle_gate()["lifecycle_gate"]["status"] == "closed"


def test_service_rejects_mixed_bundles(tmp_path):
    for index, name in enumerate(FILES):
        (tmp_path / f"{name}.json").write_text(json.dumps({"bundle_id": str(index)}))
    with pytest.raises(ValueError, match="asset_lifecycle_bundle_mismatch"):
        AssetLifecycleReadinessService(tmp_path)
