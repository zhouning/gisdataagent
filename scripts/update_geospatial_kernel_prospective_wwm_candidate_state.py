#!/usr/bin/env python3
"""Advance the integrated WWM candidate from matured authoritative outcomes."""

from __future__ import annotations

import argparse
import hashlib
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from data_agent.uwm.geospatial_kernel_v2.prospective_wwm_candidate import (
    ProspectiveWwmCandidatePrediction,
    ProspectiveWwmCandidateState,
    ProspectiveWwmMaturedFeedback,
    advance_prospective_wwm_candidate_state,
)
from scripts import update_geospatial_kernel_online_expert_pair_matured_state as pair_updater
from scripts.run_geospatial_kernel_prospective_wwm_candidate_outcome_free import (
    OUTPUT_SCHEMA,
    _artifact,
    _compile_predictions,
    _iso,
    _json_body,
    _load_json,
    _parse_datetime,
    compile_outcome_free_prospective_wwm_candidate,
)
from scripts.run_geospatial_kernel_prospective_wwm_candidate_outcome_free import (
    REPORT_SCHEMA as PREDICTION_RUN_REPORT_SCHEMA,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
UPDATER_PATH = Path(__file__).resolve()
CORE_PATH = REPO_ROOT / (
    "data_agent/uwm/geospatial_kernel_v2/prospective_wwm_candidate.py"
)
REPORT_SCHEMA = "gwm.geospatial_kernel.prospective_wwm_candidate_state_update.v1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prediction-run-report", type=Path, required=True)
    parser.add_argument("--prior-state", type=Path, required=True)
    parser.add_argument("--observations", type=Path, required=True)
    parser.add_argument("--output-state", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--update-time", type=str)
    return parser.parse_args()


def compile_prospective_wwm_candidate_state_update(
    *,
    prediction_run_report_path: Path,
    prior_state_path: Path,
    observations_path: Path,
    output_state_path: Path,
    update_time: datetime,
) -> tuple[bytes, dict[str, Any]]:
    """Verify a sealed run and update v4 plus v5 from the same feedback."""

    if update_time.tzinfo is None or update_time.utcoffset() is None:
        raise ValueError("prospective_wwm_candidate_state_update_time_invalid")
    prior_body, prior_payload = _load_json(prior_state_path)
    prior_state = ProspectiveWwmCandidateState.from_dict(prior_payload)
    (
        run_report_body,
        run_report,
        prediction_state,
        predictions,
        output_rows,
    ) = _recompute_prediction_run(prediction_run_report_path)
    if not _state_extends(prior_state, prediction_state):
        raise ValueError("prospective_wwm_candidate_prior_state_not_extension")
    observation_body, observation_payload = _load_json(observations_path)
    observations, retrieved_at, source_id = pair_updater._validate_observations(
        observation_payload,
        expected_system_id=prior_state.system_id,
        update_time=update_time,
    )
    executed_at = _parse_datetime(run_report["executed_at_utc"])
    if executed_at > min(value["observation_available_at"] for value in observations):
        raise ValueError("prospective_wwm_candidate_prediction_not_sealed")
    predictions_by_target = {
        value.target_support_end: value for value in predictions
    }
    feedbacks = []
    for observation in observations:
        prediction = predictions_by_target.get(observation["target_support_end"])
        if prediction is None:
            raise ValueError("prospective_wwm_candidate_observation_unmatched")
        feedbacks.append(
            ProspectiveWwmMaturedFeedback(
                prediction=prediction,
                observed_discharge_m3s=observation["observed_discharge_m3s"],
                observation_available_at=observation["observation_available_at"],
            )
        )
    updated_state = advance_prospective_wwm_candidate_state(
        prior_state,
        tuple(feedbacks),
        update_time=update_time,
    )
    output_body = _json_body(updated_state.as_dict())
    return output_body, {
        "schema": REPORT_SCHEMA,
        "status": "prospective_wwm_candidate_state_update_complete",
        "updated_at_utc": _iso(update_time),
        "system_id": prior_state.system_id,
        "observation_source_id": source_id,
        "observation_batch_retrieved_at_utc": _iso(retrieved_at),
        "input_artifacts": {
            "prior_state": _artifact(prior_state_path, prior_body),
            "sealed_prediction_run_report": _artifact(
                prediction_run_report_path,
                run_report_body,
            ),
            "sealed_predictions": dict(run_report["prediction_artifact"]),
            "authoritative_observations": _artifact(
                observations_path,
                observation_body,
            ),
        },
        "implementation_artifacts": {
            "prospective_wwm_core": _artifact(CORE_PATH, CORE_PATH.read_bytes()),
            "matured_state_updater": _artifact(
                UPDATER_PATH,
                UPDATER_PATH.read_bytes(),
            ),
        },
        "output_state_artifact": _artifact(output_state_path, output_body),
        "execution": {
            "sealed_prediction_run_recomputed_exactly": True,
            "prediction_row_count": len(output_rows),
            "matured_feedback_update_count": len(feedbacks),
            "v4_prior_sample_count_by_horizon": {
                str(key): value
                for key, value in (
                    prior_state.physical_residual_state.sample_count_by_horizon().items()
                )
            },
            "v4_updated_sample_count_by_horizon": {
                str(key): value
                for key, value in (
                    updated_state.physical_residual_state.sample_count_by_horizon().items()
                )
            },
            "v5_prior_sample_count_by_horizon": {
                str(key): value
                for key, value in (
                    prior_state.expert_pair_state.sample_count_by_horizon().items()
                )
            },
            "v5_updated_sample_count_by_horizon": {
                str(key): value
                for key, value in (
                    updated_state.expert_pair_state.sample_count_by_horizon().items()
                )
            },
        },
        "causal_boundary": {
            "prediction_created_before_feedback_update": True,
            "all_feedback_available_by_update_time": True,
            "raw_observation_retained_in_output_state": False,
            "v4_and_v5_updated_from_same_feedback": True,
            "prediction_code_or_input_refit_during_update": False,
        },
        "claim_boundary": {
            "integrated_online_state_update_executed": True,
            "prediction_accuracy_scored": False,
            "candidate_admitted": False,
            "geospatial_kernel_validated": False,
            "runtime_default_enabled": False,
        },
    }


def _recompute_prediction_run(
    report_path: Path,
) -> tuple[
    bytes,
    Mapping[str, Any],
    ProspectiveWwmCandidateState,
    tuple[ProspectiveWwmCandidatePrediction, ...],
    tuple[Mapping[str, Any], ...],
]:
    report_body, report = _load_json(report_path)
    if (
        report.get("schema") != PREDICTION_RUN_REPORT_SCHEMA
        or report.get("status")
        != "outcome_free_integrated_wwm_predictions_complete"
        or not isinstance(report.get("input_artifacts"), Mapping)
        or not isinstance(report.get("prediction_artifact"), Mapping)
    ):
        raise ValueError("prospective_wwm_candidate_run_report_invalid")
    inputs = report["input_artifacts"]
    if set(inputs) != {"issue", "matured_state"}:
        raise ValueError("prospective_wwm_candidate_run_report_invalid")
    issue_path, issue_body = _read_verified_descriptor(inputs["issue"])
    state_path, state_body = _read_verified_descriptor(inputs["matured_state"])
    output_path, output_body = _read_verified_descriptor(
        report["prediction_artifact"]
    )
    recomputed_body, recomputed_report = (
        compile_outcome_free_prospective_wwm_candidate(
            issue_path=issue_path,
            state_path=state_path,
            output_path=output_path,
            executed_at=_parse_datetime(report["executed_at_utc"]),
        )
    )
    if recomputed_body != output_body or recomputed_report != report:
        raise ValueError("prospective_wwm_candidate_run_recomputation_failed")
    _, output = _load_json(output_path)
    if output.get("schema") != OUTPUT_SCHEMA:
        raise ValueError("prospective_wwm_candidate_prediction_output_invalid")
    _, issue = _load_json(issue_path)
    _, state_payload = _load_json(state_path)
    state = ProspectiveWwmCandidateState.from_dict(state_payload)
    _, predictions, _, _, _ = _compile_predictions(issue, state)
    if _json_body(output) != output_body:
        raise ValueError("prospective_wwm_candidate_prediction_output_invalid")
    raw_rows = output.get("predictions")
    if (
        not isinstance(raw_rows, list)
        or len(raw_rows) != len(predictions)
        or any(not isinstance(row, Mapping) for row in raw_rows)
    ):
        raise ValueError("prospective_wwm_candidate_prediction_output_invalid")
    return report_body, report, state, predictions, tuple(raw_rows)


def _state_extends(
    current: ProspectiveWwmCandidateState,
    prediction_state: ProspectiveWwmCandidateState,
) -> bool:
    if (
        current.system_id != prediction_state.system_id
        or current.state_as_of < prediction_state.state_as_of
        or current.physical_residual_state.config
        != prediction_state.physical_residual_state.config
        or current.expert_pair_state.config != prediction_state.expert_pair_state.config
    ):
        return False
    residual_extends = all(
        set(prediction_samples).issubset(
            current.physical_residual_state.samples_by_horizon[index]
        )
        for index, prediction_samples in enumerate(
            prediction_state.physical_residual_state.samples_by_horizon
        )
    )
    pair_extends = all(
        set(prediction_samples).issubset(
            current.expert_pair_state.samples_by_horizon[index]
        )
        for index, prediction_samples in enumerate(
            prediction_state.expert_pair_state.samples_by_horizon
        )
    )
    return residual_extends and pair_extends


def _read_verified_descriptor(
    descriptor: object,
) -> tuple[Path, bytes]:
    if not isinstance(descriptor, Mapping) or set(descriptor) != {
        "path",
        "sha256",
        "size_bytes",
    }:
        raise ValueError("prospective_wwm_candidate_artifact_descriptor_invalid")
    raw_path = descriptor["path"]
    if not isinstance(raw_path, str) or not raw_path:
        raise ValueError("prospective_wwm_candidate_artifact_descriptor_invalid")
    path = Path(raw_path)
    if not path.is_absolute():
        path = REPO_ROOT / path
    body = path.read_bytes()
    if (
        hashlib.sha256(body).hexdigest() != descriptor["sha256"]
        or len(body) != descriptor["size_bytes"]
    ):
        raise ValueError("prospective_wwm_candidate_artifact_verification_failed")
    return path, body


def main() -> None:
    args = parse_args()
    update_time = (
        datetime.now(UTC)
        if args.update_time is None
        else _parse_datetime(args.update_time)
    )
    if (
        args.output_state.resolve() == args.prior_state.resolve()
        or args.output_state.exists()
        or args.report.exists()
    ):
        raise ValueError("prospective_wwm_candidate_state_overwrite_forbidden")
    output_body, report = compile_prospective_wwm_candidate_state_update(
        prediction_run_report_path=args.prediction_run_report,
        prior_state_path=args.prior_state,
        observations_path=args.observations,
        output_state_path=args.output_state,
        update_time=update_time,
    )
    args.output_state.parent.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.output_state.write_bytes(output_body)
    args.report.write_bytes(_json_body(report))
    print(f"status={report['status']}")
    print(f"system_id={report['system_id']}")
    print(
        "matured_feedback_update_count="
        f"{report['execution']['matured_feedback_update_count']}"
    )


if __name__ == "__main__":
    main()
