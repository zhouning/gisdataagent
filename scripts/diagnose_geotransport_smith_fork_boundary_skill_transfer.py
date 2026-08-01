#!/usr/bin/env python3
"""Diagnose whether upstream boundary skill transfers to the downstream outlet."""

from __future__ import annotations

import argparse
import csv
from datetime import timedelta
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np

if __package__:
    from scripts import run_geotransport_center_hill_dynamic_internal_boundary as dynamic
    from scripts import (
        run_geotransport_center_hill_internal_boundary_development as parent,
    )
else:
    import run_geotransport_center_hill_dynamic_internal_boundary as dynamic
    import run_geotransport_center_hill_internal_boundary_development as parent


REPO_ROOT = dynamic.REPO_ROOT
DEFAULT_TRANSITION_REPORT = dynamic.DEFAULT_TRANSITION_REPORT
DEFAULT_DYNAMIC_REPORT = dynamic.DEFAULT_REPORT
DEFAULT_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "smith_fork_boundary_skill_transfer_diagnostic_report.json"
)
SCHEMA = "gwm.geotransport.smith_fork_boundary_skill_transfer_diagnostic.v1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--transition-report", type=Path, default=DEFAULT_TRANSITION_REPORT
    )
    parser.add_argument("--dynamic-report", type=Path, default=DEFAULT_DYNAMIC_REPORT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def compile_diagnostic(
    *, transition_report_path: Path, dynamic_report_path: Path
) -> dict[str, Any]:
    transition_body, transition = dynamic._load(transition_report_path)
    downstream_body, downstream = dynamic._load(dynamic_report_path)
    if (
        transition.get("schema") != dynamic.TRANSITION_REPORT_SCHEMA
        or transition.get("registered_gates", {}).get(
            "all_horizons_holdout_gate_passed"
        )
        is not True
        or downstream.get("schema") != dynamic.SCHEMA
        or downstream.get("status")
        != "dynamic_internal_boundary_development_diagnostic_complete"
    ):
        raise ValueError("boundary_skill_transfer_parent_report_invalid")
    parameter_body = dynamic._read_verified(transition["outputs"]["parameters"])
    parameters = dynamic._parameters(json.loads(parameter_body))
    predictor = dynamic.CausalAutoregressiveLogBoundaryHydrograph(parameters)
    prediction_body = dynamic._read_verified(downstream["outputs"]["predictions"])
    prediction_rows = list(csv.DictReader(prediction_body.decode("utf-8").splitlines()))
    issue_times = tuple(
        sorted(
            {
                dynamic._parse_utc(row["issue_time_utc"])
                for row in prediction_rows
            }
        )
    )
    multigauge = dynamic._load_descriptor_json(
        downstream["source_artifacts"]["multigauge_input_report"]
    )
    observation_body = dynamic._read_verified(multigauge["hourly_observations"])
    observation_values = parent._parse_multigauge_hourly(observation_body)
    actual = {
        valid_at: float(value)
        for valid_at, value in observation_values["03424730"]
        if value is not None
    }

    metrics: dict[str, Any] = {}
    for horizon in dynamic.HORIZONS:
        observed: list[float] = []
        candidate: list[float] = []
        persistence: list[float] = []
        for issue_time in issue_times:
            target_time = issue_time + timedelta(hours=horizon)
            if target_time not in actual:
                continue
            history = dynamic._boundary_history(observation_values, issue_time)
            targets = tuple(
                issue_time + timedelta(hours=value)
                for value in range(1, horizon + 1)
            )
            try:
                forecast = predictor.forecast(
                    history,
                    issue_time=issue_time,
                    target_valid_times=targets,
                )
            except ValueError as exc:
                if str(exc) in {
                    "boundary_hydrograph_two_available_observations_required",
                    "boundary_hydrograph_latest_history_must_be_consecutive",
                }:
                    continue
                raise
            observed.append(actual[target_time])
            candidate.append(forecast.discharge_m3s[-1])
            persistence.append(history[-1].discharge_m3s)
        observed_array = np.asarray(observed, dtype=float)
        metrics[str(horizon)] = {
            "autoregressive_log_boundary": parent._metrics(
                observed_array, np.asarray(candidate, dtype=float)
            ),
            "causal_persistence": parent._metrics(
                observed_array, np.asarray(persistence, dtype=float)
            ),
        }
        metrics[str(horizon)]["candidate_beats_persistence_rmse"] = (
            metrics[str(horizon)]["autoregressive_log_boundary"]["rmse_m3s"]
            < metrics[str(horizon)]["causal_persistence"]["rmse_m3s"]
        )

    upstream_all = all(
        metrics[str(horizon)]["candidate_beats_persistence_rmse"]
        for horizon in dynamic.HORIZONS
    )
    downstream_vs_held = {
        str(horizon): downstream["registered_gates"]["per_horizon"][str(horizon)][
            "candidate_beats_held_boundary_rmse"
        ]
        for horizon in dynamic.HORIZONS
    }
    downstream_all = all(
        downstream_vs_held[str(horizon)] for horizon in dynamic.CORE_HORIZONS
    )
    return {
        "schema": SCHEMA,
        "status": "boundary_skill_transfer_diagnostic_complete",
        "source_artifacts": {
            "boundary_transition_report": _artifact(
                transition_report_path, transition_body
            ),
            "boundary_transition_parameters": transition["outputs"]["parameters"],
            "dynamic_internal_boundary_report": _artifact(
                dynamic_report_path, downstream_body
            ),
            "dynamic_internal_boundary_predictions": downstream["outputs"][
                "predictions"
            ],
            "multigauge_observations": multigauge["hourly_observations"],
        },
        "current_window_boundary_metrics_by_horizon": metrics,
        "downstream_candidate_beats_held_boundary_by_horizon": downstream_vs_held,
        "diagnosis": {
            "boundary_forecast_beats_persistence_all_horizons": upstream_all,
            "downstream_beats_held_boundary_all_core_horizons": downstream_all,
            "boundary_skill_transfer_gate_passed": upstream_all and downstream_all,
            "failure_location": (
                "spatial_support_or_downstream_dynamic_transfer"
                if upstream_all and not downstream_all
                else "not_isolated"
            ),
        },
        "information_boundary": {
            "future_smith_fork_observations_used_by_forecast": False,
            "future_smith_fork_observations_used_only_for_posthoc_scoring": True,
            "center_hill_outlet_target_used": False,
            "operational_observation_vintage_verified": False,
        },
        "claim_boundary": {
            "post_outcome_error_attribution_only": True,
            "boundary_transition_validated": False,
            "spatial_transfer_validated": False,
            "forecast_closure_validated": False,
            "geospatial_kernel_validated": False,
        },
    }


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
    if args.report.exists():
        raise ValueError("boundary_skill_transfer_diagnostic_refuses_overwrite")
    report = compile_diagnostic(
        transition_report_path=args.transition_report,
        dynamic_report_path=args.dynamic_report,
    )
    body = _json_body(report)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_bytes(body)
    print(args.report)
    print(hashlib.sha256(body).hexdigest())
    print(
        "boundary_skill_transfer_gate_passed="
        f"{report['diagnosis']['boundary_skill_transfer_gate_passed']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
