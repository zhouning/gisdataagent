import copy
import json
from pathlib import Path

import pytest

from data_agent.uwm.geospatial_kernel.state_prior_predictor_preflight import (
    build_state_prior_predictor_preflight,
    compute_state_prior_predictor_preflight_sha256,
    validate_state_prior_predictor_preflight,
)

ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "data/uwm_public_proxy/chongqing_central"
PROTOCOL = (
    DATA_ROOT
    / "geospatial_state_prior_next_p1_protocol_2024_07_02_07"
    / "uwm_geospatial_state_prior_p1_prospective_protocol.json"
)
PLAN = (
    DATA_ROOT
    / "openaq_multi_station_acquisition_plan_2024_07_02_07"
    / "uwm_openaq_multi_station_acquisition_plan.json"
)
REFERENCE_AUDIT = (
    DATA_ROOT
    / "openaq_station_observations_multi_station_2018_10_17_23"
    / "openaq_acquisition_audit.json"
)
ATTEMPT_MANIFEST = DATA_ROOT / "openaq_station_observations_2024_07_attempt/snapshot_manifest.json"
CROSSWALK = (
    DATA_ROOT
    / "geospatial_station_admin_crosswalk_2024_07_attempt_locations"
    / "uwm_geospatial_station_admin_crosswalk.json"
)
ADMIN_UNITS = DATA_ROOT / "admin_units/chongqing_township_admin_units.geojson"
ADMIN_MANIFEST = DATA_ROOT / "admin_units/snapshot_manifest.json"
ADMIN_GRAPH = DATA_ROOT / "admin_spatial_graph_2026_07_05/uwm_admin_spatial_adjacency_graph.json"
ADMIN_METADATA_XML = Path("/Users/zhouning/Downloads/shp/xiangzhen.shp.xml")
TAP_DOWNLOADED = (
    Path("/Users/zhouning/Downloads/tap_uwm") / "chongqing_pm25_2024_07_01_07" / "downloaded"
)
PREFLIGHT = (
    DATA_ROOT
    / "geospatial_state_prior_2024_predictor_preflight"
    / "uwm_geospatial_state_prior_predictor_preflight.json"
)


def test_checked_in_predictor_preflight_is_ready_but_cannot_execute_p1():
    artifact = _read_json(PREFLIGHT)

    assert validate_state_prior_predictor_preflight(artifact) == {
        "valid": True,
        "errors": [],
    }
    assert artifact["preflight_sha256"] == (
        "65c47235e37278494adf9a7909f6dd1b2b610d9de41e6b39dd11143308e23dc7"
    )
    assert artifact["pre_acquisition_predictor_inputs_ready"] is True
    assert artifact["tap_support_summary"]["required_station_day_count"] == 90
    assert artifact["tap_support_summary"]["available_station_day_count"] == 90
    assert artifact["binding_summary"]["planned_station_count"] == 15
    assert artifact["binding_summary"]["bindings_match_prior_audited_catalog"] is True
    assert artifact["admin_provenance_audit"]["metadata_created_date"] == "20210622"
    assert artifact["admin_provenance_audit"]["source_license_verified"] is False
    assert artifact["p1_execution_permitted"] is False
    assert artifact["p2_admission_permitted"] is False


@pytest.mark.skipif(
    not ADMIN_UNITS.is_file() or not ADMIN_METADATA_XML.is_file() or not TAP_DOWNLOADED.is_dir(),
    reason="requires restricted admin provenance and local TAP integration files",
)
def test_predictor_preflight_rebuild_is_deterministic():
    rebuilt = _build()
    checked_in = _read_json(PREFLIGHT)

    assert rebuilt == checked_in


def test_predictor_preflight_cannot_promote_itself_after_digest_recomputation():
    forged = copy.deepcopy(_read_json(PREFLIGHT))
    forged["p1_execution_permitted"] = True
    forged["p2_admission_permitted"] = True
    forged["claim_boundary"]["max_claim_level"] = "bounded_support"
    forged["preflight_sha256"] = compute_state_prior_predictor_preflight_sha256(forged)

    validation = validate_state_prior_predictor_preflight(forged)

    assert not validation["valid"]
    assert "predictor_preflight_cannot_permit_p1_execution" in validation["errors"]
    assert "predictor_preflight_cannot_permit_p2_admission" in validation["errors"]
    assert "predictor_preflight_claim_boundary_invalid" in validation["errors"]
    assert "predictor_preflight_sha256_mismatch" not in validation["errors"]


def _build() -> dict:
    evidence_paths = [
        PROTOCOL,
        PLAN,
        REFERENCE_AUDIT,
        ATTEMPT_MANIFEST,
        CROSSWALK,
        ADMIN_UNITS,
        ADMIN_MANIFEST,
        ADMIN_GRAPH,
        ADMIN_METADATA_XML,
    ]
    return build_state_prior_predictor_preflight(
        assessment_id="chongqing-observed-station-p1-2024-predictor-preflight",
        created_at="2026-08-04T21:50:00Z",
        protocol=_read_json(PROTOCOL),
        acquisition_plan=_read_json(PLAN),
        reference_acquisition_audit=_read_json(REFERENCE_AUDIT),
        prior_attempt_manifest=_read_json(ATTEMPT_MANIFEST),
        station_admin_crosswalk=_read_json(CROSSWALK),
        admin_feature_collection=_read_json(ADMIN_UNITS),
        admin_snapshot_manifest=_read_json(ADMIN_MANIFEST),
        admin_spatial_graph=_read_json(ADMIN_GRAPH),
        admin_source_metadata_xml=ADMIN_METADATA_XML,
        tap_downloaded_dir=TAP_DOWNLOADED,
        evidence_refs=[_relative_or_absolute(path) for path in evidence_paths]
        + [str(TAP_DOWNLOADED.resolve())],
    )


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _relative_or_absolute(path: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(ROOT))
    except ValueError:
        return str(resolved)
