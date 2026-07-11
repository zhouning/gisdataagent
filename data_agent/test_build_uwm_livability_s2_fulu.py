import hashlib
import importlib.util
import json
from pathlib import Path

from data_agent.test_traditional_livability_s6_fulu_adapter import (
    _facility_product,
    _planning_fixture_root,
    _specs,
)
from data_agent.uwm import traditional_livability_s6_fulu_adapter as s6_adapter


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "build_uwm_livability_s2_fulu.py"
SPEC = importlib.util.spec_from_file_location("build_uwm_livability_s2_fulu", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


EXPECTED_FILES = {
    "uwm_livability_s2_parcels.geojson",
    "uwm_livability_s2_planning_resources.geojson",
    "uwm_livability_s2_facilities.geojson",
    "uwm_livability_s2_graph_nodes.json",
    "uwm_livability_s2_graph_edges.json",
    "uwm_livability_s2_land_use_dictionary.json",
    "uwm_livability_s2_transition_matrix.json",
    "uwm_livability_s2_evidence_manifest.json",
    "uwm_livability_s2_build_report.json",
}


def _digest(payload: dict) -> str:
    content = {key: value for key, value in payload.items() if key != "content_digest"}
    encoded = json.dumps(
        content, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def test_builder_writes_complete_versioned_product_without_private_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(s6_adapter, "ASSET_SPECS", _specs())
    monkeypatch.setattr(MODULE.s6_adapter, "ASSET_SPECS", _specs())
    source_root = _planning_fixture_root(tmp_path / "sources")
    output = tmp_path / "out"

    result = MODULE.build_s2_fulu(
        source_root=source_root,
        facility_product=_facility_product(),
        output_dir=output,
        kernel_version="0.1.0",
    )

    assert result["ready"] is True
    assert result["exit_code"] == 0
    assert {path.name for path in output.iterdir()} == EXPECTED_FILES
    payloads = {
        path.name: json.loads(path.read_text(encoding="utf-8")) for path in output.iterdir()
    }
    serialized = json.dumps(payloads, ensure_ascii=False)
    assert str(source_root) not in serialized
    for payload in payloads.values():
        assert payload["content_digest"] == _digest(payload)

    manifest = payloads["uwm_livability_s2_evidence_manifest.json"]
    report = payloads["uwm_livability_s2_build_report.json"]
    assert manifest["source_content_digest"].startswith("sha256:")
    assert manifest["state_graph_snapshot_digest"]
    assert manifest["facility_inventory_complete"] is False
    assert manifest["synthetic_parcels_created"] is False
    assert report["parcel_count"] == 4
    assert report["planning_area_count"] == 2
    assert report["node_count"] > report["parcel_count"]
    assert report["edge_count"] > 0
    assert set(report["distance_crs_by_area"]) == {"fulu_heping", "fulu_banzhu"}


def test_builder_is_deterministic_for_same_real_vector_inputs(tmp_path, monkeypatch):
    monkeypatch.setattr(s6_adapter, "ASSET_SPECS", _specs())
    monkeypatch.setattr(MODULE.s6_adapter, "ASSET_SPECS", _specs())
    source_root = _planning_fixture_root(tmp_path / "sources")
    first = tmp_path / "first"
    second = tmp_path / "second"

    MODULE.build_s2_fulu(
        source_root=source_root,
        facility_product=_facility_product(),
        output_dir=first,
        kernel_version="0.1.0",
    )
    MODULE.build_s2_fulu(
        source_root=source_root,
        facility_product=_facility_product(),
        output_dir=second,
        kernel_version="0.1.0",
    )

    assert {
        path.name: json.loads(path.read_text(encoding="utf-8"))["content_digest"]
        for path in first.iterdir()
    } == {
        path.name: json.loads(path.read_text(encoding="utf-8"))["content_digest"]
        for path in second.iterdir()
    }


def test_builder_fails_closed_when_sources_or_facility_product_are_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(s6_adapter, "ASSET_SPECS", _specs())
    monkeypatch.setattr(MODULE.s6_adapter, "ASSET_SPECS", _specs())

    missing_product = MODULE.build_s2_fulu(
        source_root=tmp_path / "sources",
        facility_product=None,
        output_dir=tmp_path / "out-product",
        kernel_version="0.1.0",
    )
    assert missing_product == {
        "ready": False,
        "exit_code": 2,
        "blockers": ["facility_product_missing"],
    }

    missing_sources = MODULE.build_s2_fulu(
        source_root=tmp_path / "missing",
        facility_product=_facility_product(),
        output_dir=tmp_path / "out-sources",
        kernel_version="0.1.0",
    )
    assert missing_sources["ready"] is False
    assert missing_sources["exit_code"] == 2
    assert missing_sources["blockers"]
    assert not (tmp_path / "out-sources").exists()
