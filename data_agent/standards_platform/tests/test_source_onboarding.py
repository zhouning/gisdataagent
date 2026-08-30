"""Contracts for deterministic full-dataset source onboarding."""
from __future__ import annotations

import json
from types import SimpleNamespace

import geopandas as gpd
from shapely.geometry import Polygon

from data_agent.standards_platform.application.acceptance import bundle_identity
from data_agent.standards_platform.application.source_onboarding import (
    evaluate_vector_source_onboarding,
    register_source_onboarding_evidence,
    source_onboarding_public_summary,
)


def _write_source(path):
    frame = gpd.GeoDataFrame(
        {
            "BSM": [1, 1, 1],
            "YSDM": ["2001010100"] * 3,
            "TBBH": ["secret-a", "secret-b", "secret-c"],
            "DLDM": ["111"] * 3,
            "DLMC": ["land"] * 3,
            "QSXZ": ["30"] * 3,
            "QSDWDM": ["500227001"] * 3,
            "QSDWMC": ["unit"] * 3,
            "ZLDWDM": ["500227001001"] * 3,
            "ZLDWMC": ["village"] * 3,
            "TBMJ": [100.0, 0.0, 80.0],
            "TBDLMJ": [100.0, 0.0, 80.0],
        },
        geometry=[
            Polygon([(0, 0), (10, 0), (10, 10), (0, 10)]),
            Polygon([(20, 0), (30, 0), (30, 10), (20, 10)]),
            Polygon([(40, 0), (50, 0), (50, 10), (40, 10)]),
        ],
        crs="EPSG:4523",
    )
    frame.to_file(path, encoding="utf-8")


def _protocol(path) -> dict:
    return {
        "schema": "gis-data-agent.vector-source-onboarding.v1",
        "protocol_id": "test-source-v1",
        "onboarding_at": "2026-07-31T14:00:00+00:00",
        "source": {
            "archive_sha256": "a" * 64,
            "relative_path": path.name,
            "bundle_sha256": bundle_identity(path)["bundle_sha256"],
            "required_members": [".shp", ".shx", ".dbf", ".prj", ".cpg"],
        },
        "resource": {
            "tenant_id": "test-tenant",
            "resource_urn": "gda://test-tenant/dataset/source-parcels",
            "governance_policy_ref": "governance://test-tenant/source/parcels",
        },
        "quality_rules": {
            "rule_version": "test.source-quality.v1",
            "expected_crs": "EPSG:4523",
            "allowed_geometry_types": ["Polygon", "MultiPolygon"],
            "required_source_fields": [
                "BSM", "YSDM", "TBBH", "DLDM", "DLMC", "QSXZ",
                "QSDWDM", "QSDWMC", "ZLDWDM", "ZLDWMC", "TBMJ", "TBDLMJ",
            ],
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
            "target_table": "parcel_current",
            "required_target_fields": ["BSM", "DLBM", "SJNF", "MSSM"],
            "source_to_target": {"BSM": "BSM", "DLBM": "DLDM"},
            "derivations": {
                "SJNF": {"status": "pending"},
                "MSSM": {"status": "pending"},
            },
        },
        "governance": {
            "platform_owner": "team:data-platform",
            "business_steward": "pending_assignment",
            "classification": "internal",
            "license_status": "pending_internal_evaluation_only",
        },
        "runtime": {
            "dolphinscheduler_configured": False,
            "authoritative_quality_result_recorded": False,
            "data_product_version_created": False,
        },
    }


def test_full_dataset_onboarding_separates_source_failures_and_derivation_gaps(
    tmp_path,
):
    source = tmp_path / "parcels.shp"
    _write_source(source)

    report = evaluate_vector_source_onboarding(
        protocol=_protocol(source),
        dataset_root=tmp_path,
    )

    assert report["evaluation_policy"] == {
        "mode": "full_dataset_read_only",
        "records_scanned": 3,
        "full_dataset_validated": True,
        "samples_persisted": False,
        "source_values_persisted": False,
        "authoritative_quality_result": False,
        "data_product_version_created": False,
    }
    assert report["quality"]["source_quality_verdict"] == "failed"
    checks = {item["id"]: item for item in report["quality"]["checks"]}
    assert checks["geometries_valid"]["status"] == "passed"
    assert checks["primary_key_unique"]["metrics"]["duplicate_rows"] == 3
    assert checks["numeric_constraints_satisfied"]["status"] == "failed"
    assert checks["declared_area_consistent"]["metrics"]["outside_tolerance_count"] == 1
    assert report["standardization"]["missing_target_fields"] == ["MSSM", "SJNF"]
    assert "standardization_derived_fields_missing" in report["promotion"]["blockers"]
    assert "authoritative_quality_result_not_recorded" in report["promotion"]["blockers"]
    encoded = json.dumps(report, ensure_ascii=False)
    assert "secret-a" not in encoded
    assert str(tmp_path) not in encoded


def test_public_summary_exposes_aggregates_but_no_control_ids_or_paths(tmp_path):
    source = tmp_path / "parcels.shp"
    _write_source(source)
    report = evaluate_vector_source_onboarding(
        protocol=_protocol(source),
        dataset_root=tmp_path,
    )

    summary = source_onboarding_public_summary(
        report,
        source_registered=True,
        evidence_registered=True,
    )

    assert summary["source"]["feature_count"] == 3
    assert summary["control_plane"]["source_registered"] is True
    assert summary["quality"]["findings"]["primary_key_duplicate_rows"] == 3
    encoded = json.dumps(summary, ensure_ascii=False)
    assert "resource_version_id" not in encoded
    assert "relative_path" not in encoded
    assert "secret-a" not in encoded


def test_registration_writes_source_version_and_evidence_but_not_quality_result(
    tmp_path,
):
    source = tmp_path / "parcels.shp"
    _write_source(source)
    report = evaluate_vector_source_onboarding(
        protocol=_protocol(source),
        dataset_root=tmp_path,
    )
    evidence = tmp_path / "report.json"
    evidence.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    class FakeGateway:
        def __init__(self):
            self.resource = None
            self.version = None
            self.artifact = None

        def register_resource(self, value):
            self.resource = value
            return SimpleNamespace(created=True)

        def register_resource_version(self, value):
            self.version = value
            return SimpleNamespace(created=True)

        def record_artifact(self, value):
            self.artifact = value
            return SimpleNamespace(created=True)

    gateway = FakeGateway()
    receipt = register_source_onboarding_evidence(
        report=report,
        evidence_path=evidence,
        gateway=gateway,
    )

    assert gateway.version.content_sha256 == report["source"]["bundle"]["bundle_sha256"]
    assert gateway.artifact.resource_version_id == gateway.version.resource_version_id
    assert gateway.artifact.manifest["authoritative_quality_result"] is False
    assert receipt["quality_result_recorded"] is False
    assert receipt["platform_run_created"] is False
    assert receipt["data_product_version_created"] is False


def test_registration_rejects_tampered_evidence(tmp_path):
    source = tmp_path / "parcels.shp"
    _write_source(source)
    report = evaluate_vector_source_onboarding(
        protocol=_protocol(source),
        dataset_root=tmp_path,
    )
    report["promotion"]["ready"] = True
    evidence = tmp_path / "tampered.json"
    evidence.write_text(json.dumps(report), encoding="utf-8")

    try:
        register_source_onboarding_evidence(
            report=report,
            evidence_path=evidence,
            gateway=SimpleNamespace(),
        )
    except ValueError as exc:
        assert "evidence hash" in str(exc)
    else:
        raise AssertionError("tampered onboarding evidence was accepted")
