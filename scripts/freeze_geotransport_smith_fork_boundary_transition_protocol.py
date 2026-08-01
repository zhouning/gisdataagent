#!/usr/bin/env python3
"""Freeze the Smith Fork causal boundary-transition fit and holdout protocol."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_HISTORY_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/smith_fork_boundary_history_report.json"
)
DEFAULT_PROTOCOL = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "smith_fork_boundary_transition_protocol.json"
)
CORE_PATH = "data_agent/uwm/geospatial_kernel_v2/boundary_hydrograph.py"
SCHEMA = "gwm.geotransport.smith_fork_boundary_transition_protocol.v1"
HISTORY_SCHEMA = "gwm.geotransport.smith_fork_boundary_history.v1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--history-report", type=Path, default=DEFAULT_HISTORY_REPORT
    )
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    return parser.parse_args()


def compile_protocol(*, history_report_path: Path) -> dict[str, Any]:
    history_body = history_report_path.read_bytes()
    history = json.loads(history_body)
    if (
        history.get("schema") != HISTORY_SCHEMA
        or history.get("status") != "pass_public_boundary_history_acquired"
        or history.get("summary", {}).get("complete_fit_hour_count", 0) < 5_000
        or history.get("summary", {}).get("complete_holdout_hour_count", 0) < 2_000
    ):
        raise ValueError("boundary_transition_history_report_invalid")
    hourly = history["hourly_observations"]
    hourly_body = _read_verified(hourly)
    core_path = REPO_ROOT / CORE_PATH
    core_body = core_path.read_bytes()
    return {
        "schema": SCHEMA,
        "status": "frozen_before_boundary_transition_fit",
        "frozen_at": datetime.now(timezone.utc).isoformat(),
        "source_artifacts": {
            "history_report": _artifact(history_report_path, history_body),
            "hourly_observations": _artifact(
                REPO_ROOT / hourly["path"], hourly_body
            ),
            "core_operator": _artifact(core_path, core_body),
        },
        "site_and_axis_lock": {
            "site_id": "03424730",
            "feature_id": 18_421_273,
            "timestep_seconds": 3600,
            "fit_data_start_utc": "2021-01-01T00:00:00Z",
            "fit_target_end_inclusive_utc": "2021-09-01T00:00:00Z",
            "first_holdout_issue_time_utc": "2021-09-01T01:00:00Z",
            "holdout_end_exclusive_utc": "2021-12-09T01:00:00Z",
            "horizons_hours": [1, 3, 6, 12, 24],
        },
        "fit_lock": {
            "model": "stationary_ar2_on_log1p_hourly_discharge",
            "design_columns": ["intercept", "log_q_lag_1", "log_q_lag_2"],
            "estimator": "unweighted_ordinary_least_squares",
            "regularization": "none",
            "missing_rows": "drop_incomplete_consecutive_triplets_without_imputation",
            "coefficient_or_hyperparameter_search": False,
            "maximum_discharge_m3s": 10_000.0,
            "maximum_discharge_role": "numerical_safety_bound_not_fitted",
            "stationarity_required": True,
            "outlet_target_calibration_forbidden": True,
        },
        "holdout_lock": {
            "publication_lag_seconds": 3600,
            "latest_observation_rule": "issue_time_minus_one_hour",
            "forecast_alignment": (
                "recursively fill every hourly boundary support from latest "
                "observation through issue_time_plus_horizon"
            ),
            "baseline": "latest_issue_time_available_observation_persistence",
            "primary_metric": "rmse_m3s",
            "secondary_metrics": ["mae_m3s", "bias_m3s", "nse"],
            "common_complete_case_mask_per_horizon": True,
            "gate": (
                "candidate RMSE strictly below persistence at every registered "
                "horizon plus stationary parameters"
            ),
            "noncompensatory": True,
        },
        "forbidden_after_freeze": [
            "change_fit_or_holdout_time_axis",
            "add_lags_or_regularization after reading holdout metrics",
            "fit coefficients from Center Hill outlet targets",
            "select a horizon-specific coefficient",
            "impute missing observations",
            "claim operational observation vintage is verified",
        ],
        "data_isolation": {
            "user_supplied_data_used": False,
            "center_hill_outlet_targets_used": False,
            "current_downstream_development_window_used_for_fit": False,
            "d3_or_two_system_blind_outcomes_used": False,
        },
        "claim_boundary_before_execution": {
            "boundary_transition_fitted": False,
            "upstream_temporal_holdout_evaluated": False,
            "downstream_improvement_validated": False,
            "operational_forecast_evaluated": False,
            "geospatial_kernel_validated": False,
        },
    }


def _read_verified(descriptor: Mapping[str, Any]) -> bytes:
    path = (REPO_ROOT / str(descriptor["path"])).resolve()
    body = path.read_bytes()
    if (
        hashlib.sha256(body).hexdigest() != descriptor.get("sha256")
        or len(body) != descriptor.get("size_bytes")
    ):
        raise ValueError("boundary_transition_source_identity_mismatch")
    return body


def _artifact(path: Path, body: bytes) -> dict[str, Any]:
    return {
        "path": path.resolve().relative_to(REPO_ROOT).as_posix(),
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }


def _json_body(payload: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def main() -> int:
    args = parse_args()
    if args.protocol.exists():
        raise ValueError("boundary_transition_protocol_refuses_overwrite")
    protocol = compile_protocol(history_report_path=args.history_report)
    body = _json_body(protocol)
    args.protocol.parent.mkdir(parents=True, exist_ok=True)
    args.protocol.write_bytes(body)
    print(args.protocol)
    print(hashlib.sha256(body).hexdigest())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
