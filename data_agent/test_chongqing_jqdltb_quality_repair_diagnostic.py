from __future__ import annotations

import geopandas as gpd
from shapely.geometry import Polygon

from data_agent.platform_contracts import canonical_json_fingerprint
from scripts.diagnose_chongqing_jqdltb_quality_repairs import build_quality_repair_diagnostic


def _protocol() -> dict:
    return {
        "protocol_id": "test-jqdltb-repair-v1",
        "source": {"relative_path": "JQDLTB.shp"},
        "quality_rules": {
            "primary_key": "BSM",
            "numeric_constraints": [
                {"field": "TBMJ", "min_exclusive": 0},
                {"field": "TBDLMJ", "min_exclusive": 0},
            ],
            "area_consistency": {
                "declared_area_field": "TBMJ",
                "max_relative_error": 0.01,
            },
        },
        "standardization": {
            "derivations": {
                "SJNF": {"status": "pending"},
                "MSSM": {"status": "pending"},
            }
        },
        "governance": {
            "business_steward": "pending_assignment",
            "license_status": "pending_internal_evaluation_only",
        },
    }


def test_quality_repair_diagnostic_is_aggregate_only_and_approval_gated() -> None:
    frame = gpd.GeoDataFrame(
        {
            "BSM": [1, 1, 1],
            "TBBH": ["a", "b", "c"],
            "TBMJ": [100.0, 0.0, 80.0],
            "TBDLMJ": [100.0, 0.0, 80.0],
            "SM": [None, None, None],
        },
        geometry=[
            Polygon([(0, 0), (10, 0), (10, 10), (0, 10)]),
            Polygon([(20, 0), (30, 0), (30, 10), (20, 10)]),
            Polygon([(40, 0), (50, 0), (50, 10), (40, 10)]),
        ],
        crs="EPSG:4523",
    )

    report = build_quality_repair_diagnostic(
        frame=frame,
        protocol=_protocol(),
        archive_sha256="a" * 64,
        bundle_sha256="b" * 64,
    )

    assert report["diagnostic_policy"]["source_values_persisted"] is False
    assert report["diagnostic_policy"]["source_bytes_modified"] is False
    assert report["diagnostic_policy"]["promotion_ready"] is False
    assert report["primary_key"]["configured_profile"]["unique_complete"] is False
    assert [item["field"] for item in report["primary_key"]["candidate_fields"]] == ["TBBH"]
    assert report["numeric_constraints"][0]["nonpositive_count"] == 1
    assert report["area_consistency"]["outside_tolerance_count"] == 1
    assert all(item["status"] == "pending_approval" for item in report["standard_derivations"])
    assert all(action["status"] == "approval_required" for action in report["proposed_actions"])
    fingerprint = report.pop("diagnostic_sha256")
    assert fingerprint == canonical_json_fingerprint(report)
