"""Acceptance contracts for real vector-source standard mapping."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import geopandas as gpd

from data_agent.api.virtual_routes import _sample_frame_fingerprint
from data_agent.standards_platform.application.acceptance import (
    acceptance_public_summary,
    bundle_identity,
    profile_vector_dataset,
    run_acceptance_protocol,
)
from data_agent.standards_platform.application.contracts import (
    DatasetColumnProfile,
    StandardDataElement,
    evaluate_dataset_quality_preflight,
)

REPO_ROOT = Path(__file__).resolve().parents[3]


def _geojson(path):
    path.write_text(json.dumps({
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {"BSM": 7, "UNMAPPED": "private sample"},
            "geometry": {
                "type": "Point",
                "coordinates": [106.5, 29.5],
            },
        }],
    }), encoding="utf-8")


def _protocol() -> dict:
    return {
        "schema": "gis-data-agent.standard-mapping-acceptance.v1",
        "benchmark_id": "test-real-vector",
        "standard": {
            "doc_code": "STD",
            "version_label": "v1",
            "elements_sha256": None,
        },
        "source": {"archive_sha256": None},
        "governance": {
            "platform_owner": "data-platform",
            "business_steward": "pending_assignment",
            "classification": "internal",
            "license_status": "approved_internal",
        },
        "cases": [{
            "case_id": "parcel-golden",
            "split": "golden",
            "relative_path": "parcel.geojson",
            "target_table": "parcel_current",
            "bundle_sha256": None,
            "expected_mapping": {"BSM": "BSM"},
            "gates": {
                "min_precision": 1.0,
                "min_recall": 1.0,
                "max_unexpected_recommendations": 0,
            },
        }],
    }


def _elements() -> list[StandardDataElement]:
    return [StandardDataElement(
        id="element-bsm",
        document_version_id="version-1",
        code="parcel_current.BSM",
        name_zh="identifier",
        datatype="string",
        bound_table="parcel_current",
        bound_column="BSM",
    )]


def test_shapefile_bundle_identity_covers_sidecars(tmp_path):
    shp = tmp_path / "roads.shp"
    dbf = tmp_path / "roads.dbf"
    shp.write_bytes(b"shape")
    dbf.write_bytes(b"attributes-v1")

    before = bundle_identity(shp)
    dbf.write_bytes(b"attributes-v2")
    after = bundle_identity(shp)

    assert {member["name"] for member in before["members"]} == {
        "roads.shp",
        "roads.dbf",
    }
    assert before["bundle_sha256"] != after["bundle_sha256"]


def test_vector_profile_persists_schema_but_not_source_values(tmp_path):
    source = tmp_path / "parcel.geojson"
    _geojson(source)

    profile, fields = profile_vector_dataset(source)

    assert profile["feature_count"] == 1
    assert profile["geometry_type"] == "Point"
    assert [field.name for field in fields] == ["BSM", "UNMAPPED"]
    assert profile["samples_persisted"] is False
    assert "private sample" not in json.dumps(profile)


def test_acceptance_observes_then_verifies_a_sealed_protocol(tmp_path):
    source = tmp_path / "parcel.geojson"
    archive = tmp_path / "source.zip"
    _geojson(source)
    archive.write_bytes(b"frozen archive")
    protocol = _protocol()

    observed = run_acceptance_protocol(
        protocol=protocol,
        dataset_root=tmp_path,
        archive_path=archive,
        standard_version_id="version-1",
        standard_elements=_elements(),
        allow_unsealed=True,
    )

    assert observed["status"] == "observed_unsealed"
    sealed = copy.deepcopy(protocol)
    sealed["source"]["archive_sha256"] = observed["observed_seal"][
        "archive_sha256"
    ]
    sealed["standard"]["elements_sha256"] = observed["observed_seal"][
        "elements_sha256"
    ]
    sealed["cases"][0]["bundle_sha256"] = observed["observed_seal"][
        "case_bundle_sha256"
    ]["parcel-golden"]
    verified = run_acceptance_protocol(
        protocol=sealed,
        dataset_root=tmp_path,
        archive_path=archive,
        standard_version_id="version-1",
        standard_elements=_elements(),
    )

    assert verified["status"] == "passed"
    assert verified["technical_pass"] is True
    assert verified["promotion_ready"] is False
    assert verified["governance"]["promotion_blockers"] == [
        "business_steward"
    ]
    assert verified["metrics"]["micro_precision"] == 1.0
    assert verified["metrics"]["micro_recall"] == 1.0
    case = verified["cases"][0]
    assert case["acceptance_gates"]["min_precision"]["passed"] is True
    assert case["acceptance_gates"]["min_recall"]["passed"] is True
    assert case["proposal_evidence"][0]["source_field"] == "BSM"
    assert case["proposal_evidence"][0]["candidates"][0]["lexical_score"] == 1.0
    assert "samples" not in json.dumps(case["proposal_evidence"])
    assert "private sample" not in json.dumps(verified)


def test_acceptance_uses_precision_recall_gates_instead_of_exact_mapping(tmp_path):
    source = tmp_path / "parcel.geojson"
    archive = tmp_path / "source.zip"
    _geojson(source)
    archive.write_bytes(b"frozen archive")
    protocol = _protocol()
    protocol["cases"][0]["expected_mapping"]["REVIEW_ONLY"] = "REVIEW_ONLY"
    protocol["cases"][0]["gates"]["min_recall"] = 0.5

    observed = run_acceptance_protocol(
        protocol=protocol,
        dataset_root=tmp_path,
        archive_path=archive,
        standard_version_id="version-1",
        standard_elements=_elements(),
        allow_unsealed=True,
    )
    sealed = copy.deepcopy(protocol)
    sealed["source"]["archive_sha256"] = observed["observed_seal"][
        "archive_sha256"
    ]
    sealed["standard"]["elements_sha256"] = observed["observed_seal"][
        "elements_sha256"
    ]
    sealed["cases"][0]["bundle_sha256"] = observed["observed_seal"][
        "case_bundle_sha256"
    ]["parcel-golden"]

    verified = run_acceptance_protocol(
        protocol=sealed,
        dataset_root=tmp_path,
        archive_path=archive,
        standard_version_id="version-1",
        standard_elements=_elements(),
    )

    assert verified["status"] == "passed"
    assert verified["cases"][0]["missing_or_incorrect"] == {
        "REVIEW_ONLY": "REVIEW_ONLY"
    }
    assert verified["cases"][0]["metrics"]["recall"] == 0.5
    assert verified["cases"][0]["acceptance_gates"]["min_recall"] == {
        "required": 0.5,
        "observed": 0.5,
        "passed": True,
    }


def test_acceptance_fails_when_recall_is_below_the_sealed_gate(tmp_path):
    source = tmp_path / "parcel.geojson"
    archive = tmp_path / "source.zip"
    _geojson(source)
    archive.write_bytes(b"frozen archive")
    protocol = _protocol()
    protocol["cases"][0]["expected_mapping"]["REVIEW_ONLY"] = "REVIEW_ONLY"
    protocol["cases"][0]["gates"]["min_recall"] = 0.6

    observed = run_acceptance_protocol(
        protocol=protocol,
        dataset_root=tmp_path,
        archive_path=archive,
        standard_version_id="version-1",
        standard_elements=_elements(),
        allow_unsealed=True,
    )
    protocol["source"]["archive_sha256"] = observed["observed_seal"][
        "archive_sha256"
    ]
    protocol["standard"]["elements_sha256"] = observed["observed_seal"][
        "elements_sha256"
    ]
    protocol["cases"][0]["bundle_sha256"] = observed["observed_seal"][
        "case_bundle_sha256"
    ]["parcel-golden"]

    failed = run_acceptance_protocol(
        protocol=protocol,
        dataset_root=tmp_path,
        archive_path=archive,
        standard_version_id="version-1",
        standard_elements=_elements(),
    )

    assert failed["status"] == "failed"
    assert failed["technical_pass"] is False
    assert failed["cases"][0]["acceptance_gates"]["min_recall"] == {
        "required": 0.6,
        "observed": 0.5,
        "passed": False,
    }


def test_public_summary_excludes_paths_hashes_and_proposal_samples():
    report = {
        "benchmark_id": "cq-real-v1",
        "technical_pass": True,
        "promotion_ready": False,
        "standard": {
            "doc_code": "STD",
            "version_label": "v1",
            "elements_sha256": "sensitive-hash",
        },
        "governance": {"promotion_blockers": ["business_steward"]},
        "metrics": {"micro_precision": 1.0},
        "cases": [{
            "case_id": "bizhu-jqdltb-parcel-current-golden",
            "split": "golden",
            "relative_path": "private/source.shp",
            "target_table": "parcel_current",
            "profile": {
                "feature_count": 1555,
                "geometry_type": "Polygon",
                "samples": ["private-value"],
            },
            "metrics": {"precision": 1.0, "recall": 0.6},
            "acceptance_gates": {
                "precision": {"passed": True},
                "recall": {"passed": True},
            },
        }],
    }

    summary = acceptance_public_summary(report)

    assert summary["technical_status"] == "passed"
    assert summary["promotion_ready"] is False
    assert summary["cases"][0]["label"] == "璧山 JQDLTB 标准落标"
    encoded = json.dumps(summary, ensure_ascii=False)
    assert "private/source.shp" not in encoded
    assert "private-value" not in encoded
    assert "sensitive-hash" not in encoded


def test_chongqing_derived_parcel_product_passes_sample_quality_preflight():
    source = (
        REPO_ROOT
        / "data_agent/test_data/twm_one_map_village_standard_sample/"
        "parcel_current.geojson"
    )
    frame = gpd.read_file(source, rows=200)
    mandatory = {
        "BSM": ("string", "text"),
        "DLBM": ("string", "text"),
        "DLMC": ("string", "text"),
        "MSSM": ("string", "text"),
        "QSDWDM": ("string", "text"),
        "QSDWMC": ("string", "text"),
        "QSXZ": ("string", "text"),
        "SJNF": ("string", "text"),
        "TBBH": ("string", "text"),
        "TBDLMJ": ("numeric", "decimal"),
        "TBMJ": ("numeric", "decimal"),
        "YSDM": ("string", "text"),
        "ZLDWDM": ("string", "text"),
        "ZLDWMC": ("string", "text"),
    }
    profiles = [
        DatasetColumnProfile(
            name=column,
            dtype=str(frame[column].dtype),
            row_count=len(frame),
            null_count=int(frame[column].isna().sum()),
            invalid_geometry_count=(
                int(((~frame.geometry.is_valid) | frame.geometry.is_empty).sum())
                if column == frame.geometry.name else 0
            ),
        )
        for column in (*mandatory, frame.geometry.name)
    ]
    bindings = [
        {
            "source_field": field,
            "target_field": field,
            "target_data_element_id": f"parcel-current-{field.casefold()}",
            "datatype": datatype,
            "representation_class": representation,
            "obligation": "mandatory",
        }
        for field, (datatype, representation) in mandatory.items()
    ]
    mapping_hash = hashlib.sha256(json.dumps(
        sorted(mandatory), separators=(",", ":"),
    ).encode("utf-8")).hexdigest()

    result = evaluate_dataset_quality_preflight(
        mapping_contract_id="chongqing-derived-parcel-regression",
        mapping_hash=mapping_hash,
        source_snapshot_hash=None,
        sample_fingerprint=_sample_frame_fingerprint(frame),
        requested_limit=200,
        observed_records=len(frame),
        columns=profiles,
        field_bindings=bindings,
    )

    assert result["verdict"] == "passed"
    assert result["scope"]["observed_records"] == 200
    assert result["scope"]["full_dataset_validated"] is False
    assert result["release_candidate"]["data_product_version_created"] is False
