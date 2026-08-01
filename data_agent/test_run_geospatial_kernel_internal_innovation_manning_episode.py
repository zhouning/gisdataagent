from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from data_agent.test_assess_geospatial_kernel_internal_innovation_episode_preflight import (
    _episode_fixture,
    _refresh_descriptor_and_receipt,
    _write_json,
)
from scripts import assess_geospatial_kernel_internal_innovation_episode_preflight as preflight
from scripts import run_geospatial_kernel_internal_innovation_manning_episode as execute


def test_preflighted_episode_seals_prediction_and_internal_telemetry(
    tmp_path: Path,
) -> None:
    manifest, protocol = _executable_episode_fixture(tmp_path)
    output = tmp_path / "sealed/episode-001"

    report = execute.execute_manning_episode(
        manifest_path=manifest,
        output_directory=output,
        repo_root=tmp_path,
        protocol_path=protocol,
    )

    assert report["status"] == (
        "outcome_free_physical_prediction_and_internal_telemetry_sealed"
    )
    assert report["invariants"] == {
        "step_count": 24,
        "actual_conservation_passed": True,
        "state_transition_continuity_verified": True,
        "all_source_steps_admitted": True,
    }
    assert report["data_isolation"]["outcome_values_loaded"] is False
    assert report["claim_boundary"]["innovation_fitted"] is False
    assert report["schema"] == execute.EXECUTION_SCHEMA
    assert report["schema"].endswith(".v2")
    assert report["execution_addendum"]["identity_matches"] is True
    prediction = _read_bound_artifact(tmp_path, report["prediction_artifact"])
    assert prediction["schema"] == execute.PREDICTION_SCHEMA
    assert prediction["step_count"] == 24
    assert len(prediction["rows"]) == 24
    for name in (
        "feature_axis_artifact",
        "edge_axis_artifact",
        "reach_state_artifact",
        "edge_flux_artifact",
        "step_mass_ledger_artifact",
    ):
        payload = _read_bound_artifact(
            tmp_path,
            report["internal_innovation_artifacts"][name],
        )
        assert not _contains_key(payload, "outcome_values")
    stored_report = json.loads(
        (output / execute.REPORT_FILENAME).read_text(encoding="utf-8")
    )
    assert stored_report == report


def test_missing_execution_lengths_fail_before_rollout_output(tmp_path: Path) -> None:
    manifest, protocol = _episode_fixture(tmp_path)
    assert preflight.assess_manifest(
        manifest,
        repo_root=tmp_path,
        protocol_path=protocol,
    )["episode_execution_ready"] is True
    output = tmp_path / "sealed/missing-lengths"

    with pytest.raises(ValueError, match="full_lengths_m_invalid"):
        execute.execute_manning_episode(
            manifest_path=manifest,
            output_directory=output,
            repo_root=tmp_path,
            protocol_path=protocol,
        )
    assert not output.exists()


def test_action_outside_registered_entry_fails_before_output(tmp_path: Path) -> None:
    manifest_path, protocol = _executable_episode_fixture(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    action_path = tmp_path / manifest["artifacts"]["reservoir_action_schedule"]["path"]
    action = json.loads(action_path.read_text(encoding="utf-8"))
    action["action_entry_feature_ids"] = [10]
    _write_json(action_path, action)
    _refresh_descriptor_and_receipt(
        tmp_path,
        manifest,
        artifact_name="reservoir_action_schedule",
    )
    _write_json(manifest_path, manifest)
    output = tmp_path / "sealed/bad-action-entry"

    with pytest.raises(ValueError, match="action_outside_registered_entry"):
        execute.execute_manning_episode(
            manifest_path=manifest_path,
            output_directory=output,
            repo_root=tmp_path,
            protocol_path=protocol,
        )
    assert not output.exists()


def test_output_conflict_and_repository_escape_fail_closed(tmp_path: Path) -> None:
    manifest, protocol = _executable_episode_fixture(tmp_path)
    existing = tmp_path / "sealed/existing"
    existing.mkdir(parents=True)

    with pytest.raises(FileExistsError, match="output_conflict"):
        execute.execute_manning_episode(
            manifest_path=manifest,
            output_directory=existing,
            repo_root=tmp_path,
            protocol_path=protocol,
        )
    with pytest.raises(ValueError, match="outside_repository"):
        execute.execute_manning_episode(
            manifest_path=manifest,
            output_directory=tmp_path.parent / "outside",
            repo_root=tmp_path,
            protocol_path=protocol,
        )


def _executable_episode_fixture(root: Path) -> tuple[Path, Path]:
    manifest_path, protocol = _episode_fixture(root)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    geometry_path = root / manifest["artifacts"]["hydraulic_geometry"]["path"]
    geometry = json.loads(geometry_path.read_text(encoding="utf-8"))
    geometry["full_lengths_m"] = [1000.0, 800.0, 900.0]
    geometry["effective_lengths_m"] = [1000.0, 800.0, 900.0]
    _write_json(geometry_path, geometry)
    _refresh_descriptor_and_receipt(
        root,
        manifest,
        artifact_name="hydraulic_geometry",
    )
    action_path = root / manifest["artifacts"]["reservoir_action_schedule"]["path"]
    action = json.loads(action_path.read_text(encoding="utf-8"))
    action["action_entry_feature_ids"] = [10, 20]
    _write_json(action_path, action)
    _refresh_descriptor_and_receipt(
        root,
        manifest,
        artifact_name="reservoir_action_schedule",
    )
    _write_json(manifest_path, manifest)
    return manifest_path, protocol


def _read_bound_artifact(
    root: Path, descriptor: dict[str, object]
) -> dict[str, object]:
    path = root / str(descriptor["path"])
    body = path.read_bytes()
    assert hashlib.sha256(body).hexdigest() == descriptor["sha256"]
    assert len(body) == descriptor["size_bytes"]
    return json.loads(body)


def _contains_key(value: object, target: str) -> bool:
    if isinstance(value, dict):
        return target in value or any(
            _contains_key(child, target) for child in value.values()
        )
    if isinstance(value, list):
        return any(_contains_key(child, target) for child in value)
    return False
