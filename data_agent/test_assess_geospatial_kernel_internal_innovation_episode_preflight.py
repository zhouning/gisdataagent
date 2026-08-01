from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from scripts import assess_geospatial_kernel_internal_innovation_episode_preflight as preflight
from scripts import (
    freeze_geospatial_kernel_internal_innovation_manning_execution_addendum as freeze_addendum,
)

ISSUE = datetime(2026, 8, 1, tzinfo=UTC)
START = ISSUE + timedelta(hours=1)
EPISODE_ID = "center-hill-2026-08-01t00z"
SYSTEM_ID = "center_hill"


def test_empty_queue_waits_without_network_or_outcome_access() -> None:
    report = preflight.assess_queue()

    assert report["assessment_integrity_passed"] is True
    assert report["status"] == "awaiting_prospective_episode_manifests"
    assert report["submitted_episode_count"] == 0
    assert report["all_submitted_episodes_ready"] is False
    assert report["execution_boundary"] == {
        "network_requests_performed": False,
        "outcome_artifacts_opened": False,
        "physical_rollout_executed": False,
        "candidate_fit_executed": False,
        "runtime_enabled": False,
    }


def test_complete_causal_episode_manifest_passes_preflight(tmp_path: Path) -> None:
    manifest, protocol = _episode_fixture(tmp_path)

    report = preflight.assess_manifest(
        manifest,
        repo_root=tmp_path,
        protocol_path=protocol,
    )

    assert report["episode_execution_ready"] is True
    assert report["decision"] == "ready_for_outcome_free_physical_rollout"
    assert all(report["gates"].values())
    assert report["semantic_validation"]["all_checks_passed"] is True
    assert report["execution_boundary"]["outcome_values_loaded"] is False


def test_kinematic_episode_accepts_hash_bound_cell_volume_initial_state(
    tmp_path: Path,
) -> None:
    manifest_path, protocol = _episode_fixture(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["operator_schema"] = "gwm.geospatial_kernel.branching_finite_volume_kinematic_wave.v1"
    initial_path = tmp_path / manifest["artifacts"]["initial_state"]["path"]
    initial = json.loads(initial_path.read_text(encoding="utf-8"))
    initial.pop("feature_ids")
    initial.pop("stock_m3")
    initial.update(
        {
            "representation": "cell_volume",
            "cell_feature_ids": [30, 30, 10, 20],
            "cell_index_within_reach": [0, 1, 0, 0],
            "cell_volume_m3": [4000.0, 4000.0, 5000.0, 6000.0],
        }
    )
    _write_json(initial_path, initial)
    _refresh_descriptor_and_receipt(
        tmp_path,
        manifest,
        artifact_name="initial_state",
    )
    _write_json(manifest_path, manifest)

    report = preflight.assess_manifest(
        manifest_path,
        repo_root=tmp_path,
        protocol_path=protocol,
    )

    assert report["episode_execution_ready"] is True
    assert (
        report["semantic_validation"]["checks"]["geometry_and_initial_state_match_feature_axis"]
        is True
    )


def test_operator_specific_initial_state_and_cell_axis_fail_closed(tmp_path: Path) -> None:
    manifest_path, protocol = _episode_fixture(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["operator_schema"] = "gwm.geospatial_kernel.branching_finite_volume_kinematic_wave.v1"
    _write_json(manifest_path, manifest)

    mismatched = preflight.assess_manifest(
        manifest_path,
        repo_root=tmp_path,
        protocol_path=protocol,
    )

    assert mismatched["episode_execution_ready"] is False
    assert (
        mismatched["semantic_validation"]["checks"]["geometry_and_initial_state_match_feature_axis"]
        is False
    )

    initial_path = tmp_path / manifest["artifacts"]["initial_state"]["path"]
    initial = json.loads(initial_path.read_text(encoding="utf-8"))
    initial.pop("feature_ids")
    initial.pop("stock_m3")
    initial.update(
        {
            "representation": "cell_volume",
            "cell_feature_ids": [[30], 10, 20],
            "cell_index_within_reach": [0, 0, 0],
            "cell_volume_m3": [8000.0, 5000.0, 6000.0],
        }
    )
    _write_json(initial_path, initial)
    _refresh_descriptor_and_receipt(
        tmp_path,
        manifest,
        artifact_name="initial_state",
    )
    _write_json(manifest_path, manifest)

    malformed = preflight.assess_manifest(
        manifest_path,
        repo_root=tmp_path,
        protocol_path=protocol,
    )

    assert malformed["episode_execution_ready"] is False
    assert (
        malformed["semantic_validation"]["checks"]["geometry_and_initial_state_match_feature_axis"]
        is False
    )


def test_forbidden_outcome_content_inside_hash_bound_input_fails(tmp_path: Path) -> None:
    manifest_path, protocol = _episode_fixture(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    forcing_path = tmp_path / manifest["artifacts"]["distributed_forcing_forecast"]["path"]
    forcing = json.loads(forcing_path.read_text(encoding="utf-8"))
    forcing["outcome_values"] = [123.0]
    _write_json(forcing_path, forcing)
    _refresh_descriptor_and_receipt(
        tmp_path,
        manifest,
        artifact_name="distributed_forcing_forecast",
    )
    _write_json(manifest_path, manifest)

    report = preflight.assess_manifest(
        manifest_path,
        repo_root=tmp_path,
        protocol_path=protocol,
    )

    assert report["episode_execution_ready"] is False
    assert report["gates"]["no_forbidden_outcome_content"] is False
    assert (
        "$.artifacts.distributed_forcing_forecast.outcome_values"
        in report["forbidden_content_locations"]
    )


def test_outcome_injection_and_late_input_fail_before_execution(tmp_path: Path) -> None:
    manifest_path, protocol = _episode_fixture(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["outcome_values"] = [1.0]
    manifest["artifacts"]["distributed_forcing_forecast"]["available_at"] = (
        ISSUE + timedelta(seconds=1)
    ).isoformat()
    _write_json(manifest_path, manifest)

    report = preflight.assess_manifest(
        manifest_path,
        repo_root=tmp_path,
        protocol_path=protocol,
    )

    assert report["episode_execution_ready"] is False
    assert report["gates"]["no_forbidden_outcome_content"] is False
    assert report["gates"]["all_input_descriptors_available_at_issue"] is False
    assert "$.outcome_values" in report["forbidden_content_locations"]
    assert report["execution_boundary"]["physical_rollout_executed"] is False


def test_artifact_substitution_and_internal_schema_lie_fail_closed(
    tmp_path: Path,
) -> None:
    manifest_path, protocol = _episode_fixture(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    action_path = tmp_path / manifest["artifacts"]["reservoir_action_schedule"]["path"]
    action = json.loads(action_path.read_text(encoding="utf-8"))
    action["schema"] = "forged.schema.v1"
    _write_json(action_path, action)
    body = action_path.read_bytes()
    manifest["artifacts"]["reservoir_action_schedule"]["sha256"] = hashlib.sha256(body).hexdigest()
    manifest["artifacts"]["reservoir_action_schedule"]["size_bytes"] = len(body)
    receipts_path = tmp_path / manifest["artifacts"]["input_availability_receipts"]["path"]
    receipts = json.loads(receipts_path.read_text(encoding="utf-8"))
    for receipt in receipts["receipts"]:
        if receipt["artifact_name"] == "reservoir_action_schedule":
            receipt["artifact_sha256"] = hashlib.sha256(body).hexdigest()
    _write_json(receipts_path, receipts)
    receipt_body = receipts_path.read_bytes()
    manifest["artifacts"]["input_availability_receipts"]["sha256"] = hashlib.sha256(
        receipt_body
    ).hexdigest()
    manifest["artifacts"]["input_availability_receipts"]["size_bytes"] = len(receipt_body)
    _write_json(manifest_path, manifest)

    report = preflight.assess_manifest(
        manifest_path,
        repo_root=tmp_path,
        protocol_path=protocol,
    )

    assert report["artifacts"]["reservoir_action_schedule"]["identity_matches"] is True
    assert report["episode_execution_ready"] is False
    assert report["semantic_validation"]["checks"]["all_payloads_are_typed_json_objects"] is False


def test_manifest_without_execution_addendum_is_blocked(tmp_path: Path) -> None:
    manifest_path, protocol = _episode_fixture(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.pop("execution_addendum")
    _write_json(manifest_path, manifest)

    report = preflight.assess_manifest(
        manifest_path,
        repo_root=tmp_path,
        protocol_path=protocol,
    )

    assert report["episode_execution_ready"] is False
    assert (
        report["gates"][
            "frozen_manning_execution_addendum_identity_and_binding_valid"
        ]
        is False
    )


def test_resealed_addendum_with_forged_code_identity_is_blocked(tmp_path: Path) -> None:
    manifest_path, protocol = _episode_fixture(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    descriptor = manifest["execution_addendum"]
    addendum_path = tmp_path / descriptor["path"]
    addendum = json.loads(addendum_path.read_text(encoding="utf-8"))
    code_path = preflight.ADDENDUM_CODE_PATHS[0]
    addendum["frozen_code"][code_path]["sha256"] = "0" * 64
    addendum.pop("addendum_seal")
    canonical = json.dumps(
        addendum,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    addendum["addendum_seal"] = {
        "algorithm": "sha256_canonical_json_without_addendum_seal",
        "sha256": hashlib.sha256(canonical).hexdigest(),
    }
    _write_json(addendum_path, addendum)
    body = addendum_path.read_bytes()
    descriptor["sha256"] = hashlib.sha256(body).hexdigest()
    descriptor["size_bytes"] = len(body)
    descriptor["addendum_seal_sha256"] = addendum["addendum_seal"]["sha256"]
    _write_json(manifest_path, manifest)

    report = preflight.assess_manifest(
        manifest_path,
        repo_root=tmp_path,
        protocol_path=protocol,
    )

    assert report["episode_execution_ready"] is False
    assert report["execution_addendum"]["seal_recomputed"] is True
    assert (
        report["execution_addendum"]["all_frozen_code_identities_recomputed"]
        is False
    )


def _episode_fixture(tmp_path: Path) -> tuple[Path, Path]:
    protocol = tmp_path / "protocol.json"
    protocol.write_bytes(preflight.PROTOCOL_PATH.read_bytes())
    addendum_path = tmp_path / "manning_execution_addendum.json"
    _write_json(addendum_path, freeze_addendum.compile_addendum())
    addendum_body = addendum_path.read_bytes()
    addendum_payload = json.loads(addendum_body)
    common = {"episode_id": EPISODE_ID, "system_id": SYSTEM_ID}
    feature_ids = [30, 10, 20]
    payloads: dict[str, dict[str, object]] = {
        "feature_axis": {
            **common,
            "schema": preflight.REQUIRED_INPUT_ARTIFACTS["feature_axis"],
            "feature_count": 3,
            "features": [
                {"feature_index": 0, "feature_id": 30},
                {"feature_index": 1, "feature_id": 10},
                {"feature_index": 2, "feature_id": 20},
            ],
        },
        "edge_axis": {
            **common,
            "schema": preflight.REQUIRED_INPUT_ARTIFACTS["edge_axis"],
            "edge_count": 2,
            "edges": [
                {
                    "edge_index": 0,
                    "edge_key": "reach:10->reach:30",
                    "source_feature_id": 10,
                    "target_feature_id": 30,
                    "direction_role": "authoritative_network_direction",
                    "edge_admitted": True,
                },
                {
                    "edge_index": 1,
                    "edge_key": "reach:20->reach:30",
                    "source_feature_id": 20,
                    "target_feature_id": 30,
                    "direction_role": "authoritative_network_direction",
                    "edge_admitted": True,
                },
            ],
        },
        "hydraulic_geometry": {
            **common,
            "schema": preflight.REQUIRED_INPUT_ARTIFACTS["hydraulic_geometry"],
            "feature_ids": feature_ids,
            "bottom_width_m": [10.0, 8.0, 9.0],
            "side_slope_horizontal_per_vertical": [2.0, 2.0, 2.0],
            "bed_slope": [0.001, 0.0015, 0.0012],
            "manning_n": [0.04, 0.045, 0.042],
            "admitted_as_hydraulic_geometry": True,
        },
        "initial_state": {
            **common,
            "schema": preflight.REQUIRED_INPUT_ARTIFACTS["initial_state"],
            "representation": "reach_stock",
            "feature_ids": feature_ids,
            "stock_m3": [8000.0, 5000.0, 6000.0],
            "unit": "m3",
            "ground_truth": False,
            "possible_nudging": True,
        },
        "reservoir_action_schedule": {
            **common,
            "schema": preflight.REQUIRED_INPUT_ARTIFACTS["reservoir_action_schedule"],
            "feature_ids": feature_ids,
            "step_count": 24,
            "known_at_issue": True,
            "rows": _dynamic_rows("action_m3s", [0.0, 1.0, 2.0]),
        },
        "distributed_forcing_forecast": {
            **common,
            "schema": preflight.REQUIRED_INPUT_ARTIFACTS["distributed_forcing_forecast"],
            "feature_ids": feature_ids,
            "step_count": 24,
            "modeled": True,
            "ground_truth": False,
            "rows": _dynamic_rows("forcing_m3s", [0.1, 0.2, 0.3]),
        },
    }
    descriptors: dict[str, dict[str, object]] = {}
    available_at = (ISSUE - timedelta(minutes=5)).isoformat()
    for artifact_name, payload in payloads.items():
        path = tmp_path / f"{artifact_name}.json"
        _write_json(path, payload)
        descriptors[artifact_name] = _descriptor(
            tmp_path,
            path,
            schema=preflight.REQUIRED_INPUT_ARTIFACTS[artifact_name],
            available_at=available_at,
        )
    receipts_payload = {
        **common,
        "schema": preflight.REQUIRED_INPUT_ARTIFACTS["input_availability_receipts"],
        "receipts": [
            {
                "artifact_name": artifact_name,
                "artifact_sha256": descriptor["sha256"],
                "available_at": descriptor["available_at"],
                "source_id": f"fixture:{artifact_name}",
            }
            for artifact_name, descriptor in descriptors.items()
        ],
    }
    receipts_path = tmp_path / "input_availability_receipts.json"
    _write_json(receipts_path, receipts_payload)
    descriptors["input_availability_receipts"] = _descriptor(
        tmp_path,
        receipts_path,
        schema=preflight.REQUIRED_INPUT_ARTIFACTS["input_availability_receipts"],
        available_at=available_at,
    )
    manifest = {
        "schema": preflight.MANIFEST_SCHEMA,
        "episode_id": EPISODE_ID,
        "system_id": SYSTEM_ID,
        "operator_schema": ("gwm.geospatial_kernel.branching_manning_network_storage.v1"),
        "forecast_issue_time": ISSUE.isoformat(),
        "support": {
            "start_inclusive": START.isoformat(),
            "end_exclusive": (START + timedelta(hours=24)).isoformat(),
            "time_step_seconds": 3600,
            "step_count": 24,
        },
        "protocol": {
            "path": protocol.relative_to(tmp_path).as_posix(),
            "sha256": preflight.EXPECTED_PROTOCOL_FILE_SHA256,
            "protocol_seal_sha256": preflight.EXPECTED_PROTOCOL_SEAL_SHA256,
        },
        "execution_addendum": {
            "path": addendum_path.relative_to(tmp_path).as_posix(),
            "sha256": hashlib.sha256(addendum_body).hexdigest(),
            "size_bytes": len(addendum_body),
            "schema": preflight.ADDENDUM_SCHEMA,
            "addendum_seal_sha256": addendum_payload["addendum_seal"]["sha256"],
        },
        "artifacts": descriptors,
        "claim_boundary": {
            "outcomes_included": False,
            "retrospective_replay": False,
            "inputs_frozen_before_execution": True,
        },
    }
    manifest_path = tmp_path / "episode_manifest.json"
    _write_json(manifest_path, manifest)
    return manifest_path, protocol


def _dynamic_rows(field: str, values: list[float]) -> list[dict[str, object]]:
    return [
        {
            "step_index": index,
            "support_start_utc": (START + timedelta(hours=index)).isoformat(),
            "support_end_utc": (START + timedelta(hours=index + 1)).isoformat(),
            field: values,
        }
        for index in range(24)
    ]


def _refresh_descriptor_and_receipt(
    root: Path,
    manifest: dict[str, object],
    *,
    artifact_name: str,
) -> None:
    artifacts = manifest["artifacts"]
    descriptor = artifacts[artifact_name]
    artifact_path = root / descriptor["path"]
    body = artifact_path.read_bytes()
    descriptor["sha256"] = hashlib.sha256(body).hexdigest()
    descriptor["size_bytes"] = len(body)
    receipt_descriptor = artifacts["input_availability_receipts"]
    receipt_path = root / receipt_descriptor["path"]
    receipt_payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    for receipt in receipt_payload["receipts"]:
        if receipt["artifact_name"] == artifact_name:
            receipt["artifact_sha256"] = descriptor["sha256"]
    _write_json(receipt_path, receipt_payload)
    receipt_body = receipt_path.read_bytes()
    receipt_descriptor["sha256"] = hashlib.sha256(receipt_body).hexdigest()
    receipt_descriptor["size_bytes"] = len(receipt_body)


def _descriptor(
    root: Path,
    path: Path,
    *,
    schema: str,
    available_at: str,
) -> dict[str, object]:
    body = path.read_bytes()
    return {
        "path": path.relative_to(root).as_posix(),
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
        "schema": schema,
        "available_at": available_at,
        "provenance_id": f"fixture:{path.stem}",
    }


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
