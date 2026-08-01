#!/usr/bin/env python3
"""Emit frozen v5 and Follow-the-Leader predictions without loading outcomes."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from data_agent.uwm.geospatial_kernel_v2.physical_online_expert_blend import (
    PhysicalOnlineExpertBlendConfig,
)
from data_agent.uwm.geospatial_kernel_v2.prospective_online_expert_pair import (
    PRIMARY_CANDIDATE_ID,
    PROSPECTIVE_ONLINE_EXPERT_PAIR_PREDICTION_SCHEMA,
    TRADITIONAL_BASELINE_ID,
    ProspectiveOnlineExpertPairRunner,
    ProspectiveOnlineExpertPairState,
    algorithm_contract,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = Path(__file__).resolve()
CORE_PATH = REPO_ROOT / ("data_agent/uwm/geospatial_kernel_v2/prospective_online_expert_pair.py")
ISSUE_SCHEMA = "gwm.geospatial_kernel.online_expert_pair_issue.v1"
OUTPUT_SCHEMA = "gwm.geospatial_kernel.online_expert_pair_predictions.v1"
REPORT_SCHEMA = "gwm.geospatial_kernel.online_expert_pair_outcome_free_run.v1"
HORIZONS = (1, 3, 6, 12)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--issue", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    return parser.parse_args()


def compile_outcome_free_online_expert_pair(
    *,
    issue_path: Path,
    state_path: Path,
    output_path: Path,
    executed_at: datetime | None = None,
) -> tuple[bytes, dict[str, Any]]:
    """Compile both predictions from pre-issue state and expert forecasts."""

    issue_body, issue = _load_json(issue_path)
    state_body, state_payload = _load_json(state_path)
    state = ProspectiveOnlineExpertPairState.from_dict(state_payload)
    if state.config != PhysicalOnlineExpertBlendConfig():
        raise ValueError("online_expert_pair_algorithm_config_not_frozen")
    issue_time, forecasts = _validate_issue(issue, state)
    runner = ProspectiveOnlineExpertPairRunner(state)
    predictions = []
    for forecast in forecasts:
        step = runner.predict(
            forecast_horizon_hours=forecast["horizon_hours"],
            baseline_prediction_m3s=forecast["baseline_prediction_m3s"],
            alternative_prediction_m3s=forecast["alternative_prediction_m3s"],
            issue_time=issue_time,
        )
        encoded = step.as_dict()
        if encoded["schema"] != PROSPECTIVE_ONLINE_EXPERT_PAIR_PREDICTION_SCHEMA:
            raise ValueError("online_expert_pair_prediction_schema_invalid")
        predictions.append(
            {
                "forecast_id": forecast["forecast_id"],
                "target_support_end_utc": _iso(forecast["target_support_end"]),
                **encoded,
            }
        )
    output_payload = {
        "schema": OUTPUT_SCHEMA,
        "system_id": state.system_id,
        "issue_time_utc": _iso(issue_time),
        "state_as_of_utc": _iso(state.state_as_of),
        "primary_candidate": PRIMARY_CANDIDATE_ID,
        "traditional_baseline": TRADITIONAL_BASELINE_ID,
        "predictions": predictions,
        "prediction_count": len(predictions),
        "raw_observations_included": False,
        "scores_included": False,
    }
    output_body = _json_body(output_payload)
    recorded_at = executed_at if executed_at is not None else datetime.now(UTC)
    if (
        not _aware(recorded_at)
        or recorded_at < issue_time
        or recorded_at >= min(value["target_support_end"] for value in forecasts)
    ):
        raise ValueError("online_expert_pair_executed_at_invalid")
    report = {
        "schema": REPORT_SCHEMA,
        "status": "outcome_free_candidate_and_baseline_predictions_complete",
        "executed_at": recorded_at.astimezone(UTC).isoformat(),
        "system_id": state.system_id,
        "issue_time_utc": _iso(issue_time),
        "state_as_of_utc": _iso(state.state_as_of),
        "algorithm_lock": algorithm_contract(state.config),
        "input_artifacts": {
            "issue": _artifact(issue_path, issue_body),
            "matured_state": _artifact(state_path, state_body),
        },
        "implementation_artifacts": {
            "prospective_pair_core": _artifact(CORE_PATH, CORE_PATH.read_bytes()),
            "outcome_free_runner": _artifact(RUNNER_PATH, RUNNER_PATH.read_bytes()),
        },
        "prediction_artifact": _artifact(output_path, output_body),
        "execution": {
            "forecast_horizons_hours": list(HORIZONS),
            "prediction_count": len(predictions),
            "matured_sample_count_by_horizon": {
                str(key): value for key, value in state.sample_count_by_horizon().items()
            },
            "both_candidate_and_baseline_emitted_before_scoring": True,
            "candidate_selected_from_current_window_score": False,
            "baseline_selected_from_current_window_score": False,
        },
        "data_isolation": {
            "outcome_path_accepted_by_executor": False,
            "raw_observation_field_accepted_in_issue_input": False,
            "raw_observation_value_loaded": False,
            "score_or_loss_field_accepted_in_issue_input": False,
            "current_or_future_target_used": False,
            "matured_outcome_derived_state_loaded": any(state.sample_count_by_horizon().values()),
        },
        "claim_boundary": {
            "outcome_free_dual_prediction_software_executed": True,
            "fresh_outcome_scored": False,
            "v5_superiority_over_traditional_selector_validated": False,
            "geospatial_kernel_validated": False,
            "runtime_default_enabled": False,
        },
    }
    return output_body, report


def _validate_issue(
    payload: Mapping[str, object],
    state: ProspectiveOnlineExpertPairState,
) -> tuple[datetime, list[dict[str, Any]]]:
    if set(payload) != {"schema", "system_id", "issue_time_utc", "forecasts"}:
        raise ValueError("online_expert_pair_issue_invalid")
    if (
        payload.get("schema") != ISSUE_SCHEMA
        or payload.get("system_id") != state.system_id
        or not isinstance(payload.get("forecasts"), list)
    ):
        raise ValueError("online_expert_pair_issue_invalid")
    issue_time = _parse_datetime(payload["issue_time_utc"])
    if state.state_as_of > issue_time:
        raise ValueError("online_expert_pair_state_after_issue")
    rows: list[dict[str, Any]] = []
    ids: set[str] = set()
    horizons: set[int] = set()
    for value in payload["forecasts"]:
        if not isinstance(value, Mapping) or set(value) != {
            "forecast_id",
            "horizon_hours",
            "target_support_end_utc",
            "physical_online_residual_adaptation_v4_m3s",
            "action_innovation_wwm_m3s",
        }:
            raise ValueError("online_expert_pair_issue_forecast_invalid")
        forecast_id = value["forecast_id"]
        horizon = value["horizon_hours"]
        if (
            not isinstance(forecast_id, str)
            or not forecast_id.strip()
            or forecast_id in ids
            or not isinstance(horizon, int)
            or isinstance(horizon, bool)
            or horizon not in HORIZONS
            or horizon in horizons
        ):
            raise ValueError("online_expert_pair_issue_forecast_invalid")
        try:
            baseline = float(value["physical_online_residual_adaptation_v4_m3s"])
            alternative = float(value["action_innovation_wwm_m3s"])
        except (TypeError, ValueError) as exc:
            raise ValueError("online_expert_pair_issue_forecast_invalid") from exc
        target_support_end = _parse_datetime(value["target_support_end_utc"])
        if (
            not math.isfinite(baseline)
            or not math.isfinite(alternative)
            or isinstance(value["physical_online_residual_adaptation_v4_m3s"], bool)
            or isinstance(value["action_innovation_wwm_m3s"], bool)
            or baseline < 0.0
            or alternative < 0.0
            or target_support_end != issue_time + timedelta(hours=horizon)
        ):
            raise ValueError("online_expert_pair_issue_forecast_invalid")
        ids.add(forecast_id)
        horizons.add(horizon)
        rows.append(
            {
                "forecast_id": forecast_id,
                "horizon_hours": horizon,
                "target_support_end": target_support_end,
                "baseline_prediction_m3s": baseline,
                "alternative_prediction_m3s": alternative,
            }
        )
    if horizons != set(HORIZONS):
        raise ValueError("online_expert_pair_issue_horizon_axis_invalid")
    return issue_time, sorted(rows, key=lambda row: row["horizon_hours"])


def _load_json(path: Path) -> tuple[bytes, Mapping[str, object]]:
    body = path.read_bytes()

    def pairs(values: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in values:
            if key in result:
                raise ValueError("online_expert_pair_json_duplicate_key")
            result[key] = value
        return result

    def reject_constant(value: str) -> None:
        raise ValueError(f"online_expert_pair_json_nonfinite:{value}")

    try:
        payload = json.loads(
            body,
            object_pairs_hook=pairs,
            parse_constant=reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("online_expert_pair_json_invalid") from exc
    if not isinstance(payload, Mapping):
        raise ValueError("online_expert_pair_json_invalid")
    return body, payload


def _artifact(path: Path, body: bytes) -> dict[str, object]:
    try:
        display = path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        display = str(path.resolve())
    return {
        "path": display,
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }


def _parse_datetime(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("online_expert_pair_datetime_invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("online_expert_pair_datetime_invalid") from exc
    if not _aware(parsed):
        raise ValueError("online_expert_pair_datetime_invalid")
    return parsed.astimezone(UTC)


def _aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _json_body(payload: Mapping[str, object]) -> bytes:
    return (json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n").encode("utf-8")


def main() -> None:
    args = parse_args()
    output_body, report = compile_outcome_free_online_expert_pair(
        issue_path=args.issue,
        state_path=args.state,
        output_path=args.output,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(output_body)
    args.report.write_bytes(_json_body(report))
    print(f"status={report['status']}")
    print(f"system_id={report['system_id']}")
    print(f"issue_time_utc={report['issue_time_utc']}")
    print(f"prediction_count={report['execution']['prediction_count']}")


if __name__ == "__main__":
    main()
