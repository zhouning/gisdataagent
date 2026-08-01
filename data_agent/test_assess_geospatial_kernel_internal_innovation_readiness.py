from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts import assess_geospatial_kernel_internal_innovation_readiness as assess


def test_current_four_combinations_fail_closed_without_internal_artifacts() -> None:
    report = assess.assess()

    assert report["assessment_integrity_passed"] is True
    assert report["status"] == ("blocked_missing_or_invalid_internal_state_and_flux_artifacts")
    assert len(report["combinations"]) == 4
    assert report["gates"]["aggregate_conservation_available_and_passed"] is True
    assert report["gates"]["sealed_prediction_identities_match"] is True
    assert report["gates"]["required_internal_artifacts_hash_bound"] is False
    assert report["gates"]["internal_artifact_semantics_validated"] is False
    assert report["decision"] == {
        "aggregate_conservation_evidence_available": True,
        "internal_innovation_fit_ready": False,
        "fit_executed": False,
        "prediction_reexecution_performed": False,
        "prediction_values_parsed": False,
        "outcome_values_loaded": False,
        "candidate_promoted": False,
        "runtime_enabled": False,
    }
    for combination in report["combinations"].values():
        assert combination["missing_or_invalid_internal_artifacts"] == list(
            assess.REQUIRED_INTERNAL_ARTIFACTS
        )
        assert combination["internal_innovation_fit_ready"] is False
        assert combination["execution_boundary"]["outcome_values_loaded"] is False


def test_declared_but_missing_internal_artifacts_do_not_pass(tmp_path: Path) -> None:
    prediction = tmp_path / "prediction.csv"
    prediction.write_text(
        "time,prediction\n2024-01-01T00:00:00Z,1.0\n",
        encoding="utf-8",
    )
    prediction_descriptor = _descriptor(tmp_path, prediction, "prediction.v1")
    missing_descriptors = {
        name: {
            "path": f"missing/{name}.json",
            "sha256": "a" * 64,
            "size_bytes": 1,
            "schema": schema,
        }
        for name, schema in assess.REQUIRED_INTERNAL_ARTIFACTS.items()
    }
    payload = _rollout_payload(
        prediction_descriptor,
        internal_artifacts={
            **missing_descriptors,
            "alignment_assertions": {name: True for name in assess.REQUIRED_ALIGNMENT_ASSERTIONS},
        },
    )
    source = tmp_path / "rollout.json"
    _write_json(source, payload)

    report = assess.assess(tmp_path, _spec(source, tmp_path))

    combination = report["combinations"]["test:test_system"]
    assert report["assessment_integrity_passed"] is True
    assert combination["all_alignment_assertions_passed"] is True
    assert combination["missing_or_invalid_internal_artifacts"] == list(
        assess.REQUIRED_INTERNAL_ARTIFACTS
    )
    assert report["decision"]["internal_innovation_fit_ready"] is False


def test_hash_bound_but_semantically_empty_instrumentation_does_not_pass(
    tmp_path: Path,
) -> None:
    prediction = tmp_path / "prediction.csv"
    prediction.write_text(
        "time,prediction\n2024-01-01T00:00:00Z,1.0\n",
        encoding="utf-8",
    )
    internal_artifacts: dict[str, object] = {}
    for name, schema in assess.REQUIRED_INTERNAL_ARTIFACTS.items():
        artifact = tmp_path / f"{name}.json"
        artifact.write_text('{"fixture":true}\n', encoding="utf-8")
        internal_artifacts[name] = _descriptor(tmp_path, artifact, schema)
    internal_artifacts["alignment_assertions"] = {
        name: True for name in assess.REQUIRED_ALIGNMENT_ASSERTIONS
    }
    payload = _rollout_payload(
        _descriptor(tmp_path, prediction, "prediction.v1"),
        internal_artifacts=internal_artifacts,
    )
    source = tmp_path / "rollout.json"
    _write_json(source, payload)

    report = assess.assess(tmp_path, _spec(source, tmp_path))

    assert report["assessment_integrity_passed"] is True
    assert report["status"] == ("blocked_missing_or_invalid_internal_state_and_flux_artifacts")
    assert report["gates"]["required_internal_artifacts_hash_bound"] is True
    assert report["gates"]["internal_artifact_semantics_validated"] is False
    assert report["decision"]["internal_innovation_fit_ready"] is False
    assert report["decision"]["fit_executed"] is False


def test_descriptor_without_size_fails_closed(tmp_path: Path) -> None:
    artifact = tmp_path / "artifact.json"
    artifact.write_text("{}\n", encoding="utf-8")
    descriptor = _descriptor(tmp_path, artifact, "fixture.v1")
    descriptor.pop("size_bytes")

    identity = assess._descriptor_identity(tmp_path, descriptor)

    assert identity["exists"] is True
    assert identity["descriptor_complete"] is False
    assert identity["identity_matches"] is False


def _rollout_payload(
    prediction_descriptor: dict[str, object],
    *,
    internal_artifacts: dict[str, object],
) -> dict[str, object]:
    return {
        "schema": "test.rollout.v1",
        "status": "joint_outcome_free_predictions_sealed",
        "data_isolation": {
            "outcome_columns_accepted_by_executor": False,
            "outcome_manifest_accepted_by_executor": False,
            "outcome_path_accepted_by_executor": False,
            "outcome_urls_requested": False,
            "outcome_values_loaded": False,
            "usgs_observations_loaded": False,
        },
        "systems": {
            "test_system": {
                "system_id": "test_system",
                "prediction_artifact": prediction_descriptor,
                "registered_execution": {"operator": "FixtureOperator"},
                "invariants": {"actual_conservation_passed": True},
                "internal_innovation_artifacts": internal_artifacts,
            }
        },
    }


def _descriptor(root: Path, path: Path, schema: str) -> dict[str, object]:
    body = path.read_bytes()
    return {
        "path": path.relative_to(root).as_posix(),
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
        "schema": schema,
    }


def _spec(source: Path, root: Path) -> dict[str, dict[str, object]]:
    body = source.read_bytes()
    return {
        "test": {
            "path": source.relative_to(root).as_posix(),
            "sha256": hashlib.sha256(body).hexdigest(),
            "schema": "test.rollout.v1",
            "system_ids": ("test_system",),
        }
    }


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
