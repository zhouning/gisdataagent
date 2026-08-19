from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest
from pydantic import ValidationError

from data_agent.chongqing_customer_data_quality import (
    ChongqingCustomerDataQualityError,
    ChongqingCustomerDataQualityReport,
    build_chongqing_customer_data_quality_report,
)
from data_agent.chongqing_entity_link_baseline import CUSTOMER_BUNDLE_DIR


def _profile(report: ChongqingCustomerDataQualityReport, name: str):
    return next(item for item in report.artifact_profiles if item.artifact_name == name)


def _rewrite_artifact_and_manifest(
    bundle_dir: Path,
    artifact_name: str,
    document: dict,
) -> None:
    artifact_path = bundle_dir / artifact_name
    artifact_path.write_text(
        json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    digest = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
    manifest_path = bundle_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_entry = next(item for item in manifest["files"] if item["name"] == artifact_name)
    manifest_entry["size"] = artifact_path.stat().st_size
    manifest_entry["sha256"] = digest
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def test_default_chongqing_customer_quality_report_is_deterministic_and_aggregate():
    first = build_chongqing_customer_data_quality_report()
    second = build_chongqing_customer_data_quality_report()

    assert first == second
    assert first.report_sha256 == second.report_sha256
    assert first.ontology_package_id == "natural-resource-one-map:2.3.0:587915868b1221af"
    assert (
        first.parcel_record_count,
        first.parcel_identity_count,
        first.constraint_feature_count,
        first.entity_count,
        first.link_identity_count,
        first.exact_intersection_observation_count,
        first.customer_link_evidence_observation_count,
        first.excluded_precision_sliver_count,
    ) == (445, 439, 16, 455, 486, 492, 472, 1)
    assert first.ontology_review_status == "technical_baseline_unreviewed"
    assert first.usage_status == "assisted_precheck_not_for_production_decision"
    assert first.quality_state == "passed_with_documented_precision_exclusion"
    assert first.authority_write_performed is False
    assert first.customer_approval_present is False
    assert [gate.status for gate in first.quality_gates].count("passed") == 5
    assert [gate.status for gate in first.quality_gates].count("warning") == 1

    source_document = json.loads(
        (CUSTOMER_BUNDLE_DIR / "heping_changed_parcels.geojson").read_text(encoding="utf-8")
    )
    source_parcel_id = source_document["features"][0]["properties"]["parcel_id"]
    serialized = first.model_dump_json()
    assert source_parcel_id not in serialized
    assert '"features"' not in serialized
    assert '"geometry"' not in serialized


def test_artifact_profiles_cover_fields_codes_geometry_crs_and_identity_policy():
    report = build_chongqing_customer_data_quality_report()
    parcels = _profile(report, "heping_changed_parcels.geojson")
    constraints = _profile(report, "heping_constraints.geojson")

    assert parcels.crs_state == constraints.crs_state == "rfc7946_default_wgs84"
    assert {item.geometry_type: item.count for item in parcels.geometry_type_counts} == {
        "MultiPolygon": 1,
        "Polygon": 444,
    }
    assert {item.geometry_type: item.count for item in constraints.geometry_type_counts} == {
        "MultiPolygon": 3,
        "Polygon": 13,
    }
    for profile in (parcels, constraints):
        assert profile.empty_geometry_count == 0
        assert profile.invalid_geometry_count == 0
        assert profile.non_area_geometry_count == 0
        assert all(field.missing_count == 0 for field in profile.field_profiles)

    assert parcels.primary_key_fields == ("parcel_id",)
    assert parcels.primary_key_duplicate_policy == "allowed_identity_aggregation"
    assert parcels.primary_key_duplicate_group_count == 2
    assert parcels.primary_key_duplicate_row_count == 6
    assert parcels.primary_key_distinct_count == parcels.identity_count == 439
    assert constraints.primary_key_fields == ("layer", "BSM")
    assert constraints.primary_key_duplicate_policy == "must_be_unique"
    assert constraints.primary_key_duplicate_group_count == 0
    assert constraints.primary_key_duplicate_row_count == 0
    assert constraints.primary_key_distinct_count == constraints.identity_count == 16

    expected_code_fields = {
        "JQDLDM",
        "JQDLMC",
        "GHDLDM",
        "GHDLMC",
        "review_status",
        "layer",
        "constraint_type",
        "severity",
        "ontology_class",
    }
    code_profiles = {
        field.field_name: field
        for profile in (parcels, constraints)
        for field in profile.field_profiles
        if field.value_counts
    }
    assert set(code_profiles) == expected_code_fields
    for field in code_profiles.values():
        assert sum(item.count for item in field.value_counts) == field.record_count
        assert len(field.value_counts) == field.distinct_value_count


def test_quality_report_rejects_tampered_sealed_counters():
    report = build_chongqing_customer_data_quality_report()
    payload = report.model_dump(mode="json")
    payload["entity_count"] += 1

    with pytest.raises(ValidationError, match="entity count"):
        ChongqingCustomerDataQualityReport.model_validate(payload)


def test_customer_artifact_hash_mismatch_fails_closed(tmp_path: Path):
    bundle_dir = tmp_path / "customer-bundle"
    shutil.copytree(CUSTOMER_BUNDLE_DIR, bundle_dir)
    parcel_path = bundle_dir / "heping_changed_parcels.geojson"
    parcel_path.write_text(parcel_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    with pytest.raises(ChongqingCustomerDataQualityError, match="sealed baseline"):
        build_chongqing_customer_data_quality_report(bundle_dir=bundle_dir)


def test_missing_required_field_cannot_be_reported_as_passed(tmp_path: Path):
    bundle_dir = tmp_path / "customer-bundle"
    shutil.copytree(CUSTOMER_BUNDLE_DIR, bundle_dir)
    artifact_name = "heping_changed_parcels.geojson"
    document = json.loads((bundle_dir / artifact_name).read_text(encoding="utf-8"))
    document["features"][0]["properties"].pop("JQDLDM")
    _rewrite_artifact_and_manifest(bundle_dir, artifact_name, document)

    with pytest.raises(ChongqingCustomerDataQualityError, match="aggregate quality"):
        build_chongqing_customer_data_quality_report(bundle_dir=bundle_dir)


def test_empty_required_object_cannot_be_reported_as_present(tmp_path: Path):
    bundle_dir = tmp_path / "customer-bundle"
    shutil.copytree(CUSTOMER_BUNDLE_DIR, bundle_dir)
    artifact_name = "heping_changed_parcels.geojson"
    document = json.loads((bundle_dir / artifact_name).read_text(encoding="utf-8"))
    document["features"][0]["properties"]["evidence"] = {}
    _rewrite_artifact_and_manifest(bundle_dir, artifact_name, document)

    with pytest.raises(ChongqingCustomerDataQualityError, match="sealed baseline"):
        build_chongqing_customer_data_quality_report(bundle_dir=bundle_dir)


def test_explicit_legacy_geojson_crs_cannot_be_labeled_rfc7946_default(
    tmp_path: Path,
):
    bundle_dir = tmp_path / "customer-bundle"
    shutil.copytree(CUSTOMER_BUNDLE_DIR, bundle_dir)
    artifact_name = "heping_constraints.geojson"
    document = json.loads((bundle_dir / artifact_name).read_text(encoding="utf-8"))
    document["crs"] = {
        "type": "name",
        "properties": {"name": "urn:ogc:def:crs:EPSG::4326"},
    }
    _rewrite_artifact_and_manifest(bundle_dir, artifact_name, document)

    with pytest.raises(ChongqingCustomerDataQualityError, match="non-RFC-7946 CRS"):
        build_chongqing_customer_data_quality_report(bundle_dir=bundle_dir)
