import json
from pathlib import Path

import pytest

from data_agent.uwm.spatial_scope_registry_service import SpatialScopeRegistryService


FILES = ("overview", "spatial_units", "scope_registry", "diagnostics", "data_contracts", "map")


def test_service_loads_consistent_bundle(tmp_path):
    for name in FILES:
        payload = {"bundle_id": "scope-test"}
        if name == "spatial_units": payload["spatial_units"] = [{"unit_id": "u1", "evidence_status": "fragile"}]
        (tmp_path / f"{name}.json").write_text(json.dumps(payload))
    assert SpatialScopeRegistryService(tmp_path).spatial_units()["spatial_units"][0]["evidence_status"] == "fragile"


def test_service_rejects_mixed_bundles(tmp_path):
    for index, name in enumerate(FILES): (tmp_path / f"{name}.json").write_text(json.dumps({"bundle_id": str(index)}))
    with pytest.raises(ValueError, match="spatial_scope_bundle_mismatch"):
        SpatialScopeRegistryService(tmp_path)


def test_real_service_exposes_fragile_1017_unit_registry():
    service = SpatialScopeRegistryService(Path("data/uwm_public_proxy/chongqing_central/spatial_scope_registry_chongqing"))
    assert service.overview()["summary"]["spatial_unit_count"] == 1017
    assert service.overview()["summary"]["county_name_count"] == 38
    assert service.diagnostics()["diagnostics"]["topology_validated"] is False
    assert len(service.map_payload()["feature_bindings"]) == 1017
    assert service.map_payload()["geometry_embedded"] is False
