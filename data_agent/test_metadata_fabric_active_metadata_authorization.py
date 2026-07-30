import json
from copy import deepcopy

from data_agent import metadata_fabric_active_metadata_authorization as authorization


def test_static_contract_requires_atomic_evidence_bound_dispatch():
    report = authorization.build_contract_report()

    assert report["status"] == "valid"
    assert report["errors"] == []
    assert report["approval_required"] is True
    assert report["promotion_boundary"] == (
        "authorization_and_dispatch_same_transaction"
    )
    assert report["real_data_role"] == (
        "acceptance_input_and_resource_version_fingerprint"
    )
    assert report["provider_apply_authorized"] is False
    assert report["production_scheduler_submission_verified"] is False
    assert report["production_ready"] is False
    assert all(
        not item["path"].startswith("/") for item in report["files"].values()
    )


def test_checked_real_data_evidence_is_current_path_free_and_fail_closed():
    evidence = json.loads(
        authorization.DEFAULT_EVIDENCE_PATH.read_text(encoding="utf-8")
    )

    assert authorization.validate_rehearsal_evidence(evidence) == []
    assert evidence["real_dataset_inspected"] is True
    assert evidence["dataset_bundle"]["spatial_inventory"] == {
        "bounds": [
            106.37987914500007,
            29.558008447000077,
            106.59532712300008,
            29.877271985000025,
        ],
        "crs": {
            "authority": "EPSG",
            "code": 4490,
            "name": "China Geodetic Coordinate System 2000",
        },
        "driver": "ESRI Shapefile",
        "feature_count": 20,
        "field_count": 33,
        "geometry_type": "PolygonZ",
    }
    assert evidence["resource_version_content_sha256"] == (
        evidence["dataset_bundle"]["content_sha256"]
    )
    assert evidence["dataset_source_committed"] is False
    assert evidence["dataset_absolute_path_committed"] is False
    assert evidence["dataset_required_in_ci"] is False
    assert "/Users/" not in json.dumps(evidence)
    assert evidence["authorization_count"] == 1
    assert evidence["dispatch_command_count"] == 1
    assert evidence["dispatch_command_status"] == "pending"
    assert evidence["provider_apply_authorized"] is False
    assert evidence["production_scheduler_submission_verified"] is False
    assert evidence["production_ready"] is False


def test_evidence_validation_rejects_tampering_and_production_overclaim():
    evidence = json.loads(
        authorization.DEFAULT_EVIDENCE_PATH.read_text(encoding="utf-8")
    )
    tampered = deepcopy(evidence)
    tampered["dispatch_command_count"] = 2
    tampered["production_ready"] = True

    errors = authorization.validate_rehearsal_evidence(tampered)

    assert "Active Metadata authorization evidence SHA-256 does not match" in errors
    assert "local authorization evidence may not claim production_ready" in errors
    assert "authorization evidence must contain one dispatch command" in errors
