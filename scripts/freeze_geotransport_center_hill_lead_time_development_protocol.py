#!/usr/bin/env python3
"""Freeze the Center Hill lead-time development diagnostic before execution."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GRAPH_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "center_hill_graph_multigauge_development_report.json"
)
DEFAULT_OUTPUT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "center_hill_lead_time_development_protocol.json"
)
SCHEMA = "gwm.geotransport.center_hill_lead_time_development_protocol.v1"
START = datetime(2021, 12, 9, 1, tzinfo=timezone.utc)
END = datetime(2022, 1, 6, 1, tzinfo=timezone.utc)
ACTIVATION_INDEX = 169
DIAGNOSTIC_HORIZONS = (1,)
CORE_HORIZONS = (3, 6, 12, 24)
HORIZONS = DIAGNOSTIC_HORIZONS + CORE_HORIZONS
SCENARIOS = ("graph_multi_gauge", "local_multi_gauge", "outlet_only")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graph-report", type=Path, default=DEFAULT_GRAPH_REPORT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def compile_protocol(
    *, graph_report_path: Path = DEFAULT_GRAPH_REPORT
) -> dict[str, Any]:
    graph_body, graph = _load_json(graph_report_path)
    _validate_graph_parent(graph)
    parameters = graph["outputs"]["graph_parameters"]
    predictions = graph["outputs"]["predictions"]
    _read_verified(parameters)
    _read_verified(predictions)
    maximum_horizon = max(HORIZONS)
    issue_start = START + timedelta(hours=ACTIVATION_INDEX)
    issue_end = END - timedelta(hours=maximum_horizon)
    issue_count = int((issue_end - issue_start).total_seconds() // 3600) + 1
    return {
        "schema": SCHEMA,
        "status": "frozen_before_lead_time_development_execution",
        "frozen_at": datetime.now(timezone.utc).isoformat(),
        "scientific_role": (
            "post-outcome development re-analysis of one already exposed window; "
            "not prospective validation"
        ),
        "parent_evidence": {
            "graph_multigauge_report": _artifact(graph_report_path, graph_body),
            "graph_parameters": parameters,
            "one_step_predictions": predictions,
        },
        "outcome_access_at_freeze": {
            "window_outcomes_previously_accessed": True,
            "reason": "same window was already scored by the one-step diagnostic",
            "parameter_or_gain_tuning_after_access": False,
            "prospective_or_blind_claim_permitted": False,
        },
        "window": {
            "input_start_inclusive": _iso(START),
            "input_end_exclusive": _iso(END),
            "first_issue_time": _iso(issue_start),
            "last_issue_time": _iso(issue_end),
            "issue_count": issue_count,
            "maximum_horizon_hours": maximum_horizon,
            "all_issues_have_all_registered_horizons": True,
            "role": "public_development_only_not_validation",
        },
        "horizon_lock": {
            "diagnostic_horizons_hours": list(DIAGNOSTIC_HORIZONS),
            "core_horizons_hours": list(CORE_HORIZONS),
            "all_horizons_hours": list(HORIZONS),
            "target_definition": (
                "outlet mean discharge over the final hourly interval ending "
                "issue_time_plus_horizon"
            ),
            "horizon_selection_from_target_errors": False,
        },
        "forecast_cycle_lock": {
            "scenarios": list(SCENARIOS),
            "cycling_state": (
                "each scenario advances one hour between issue times using only its "
                "registered issue-time observations"
            ),
            "branch_rollout": (
                "clone each scenario analysis at issue time and execute one continuous "
                "24-hour rollout, recording registered intermediate horizons"
            ),
            "observations_after_issue_time": "forbidden",
            "horizon_rollout_mutates_cycling_state": False,
            "graph_gain_artifact_mutation": False,
            "graph_gain_search_on_this_window": False,
            "topology_geometry_and_solver": "unchanged_from_parent_graph_diagnostic",
        },
        "information_tracks": {
            "retrospective_oracle_forcing": {
                "executable": True,
                "action": "realized CWMS hourly release for every future interval",
                "forcing": "NWM v3 retrospective q_lateral for every future interval",
                "future_outlet_target_used_as_model_input": False,
                "operational_forecast_claim_permitted": False,
                "reason": (
                    "future action and forcing are realized retrospective values, not "
                    "issue-time forecast vintages"
                ),
            },
            "operational_forecast": {
                "executable": False,
                "required_missing_inputs": [
                    "historical issue-time NWM forcing forecast vintages",
                    "historical issue-time reservoir release plan vintages",
                    "verified historical USGS observation publication vintages",
                ],
                "fabricated_substitution_forbidden": True,
                "metrics_must_be_null": True,
            },
        },
        "observation_lock": {
            "assumed_publication_lag_seconds": 3600,
            "maximum_age_seconds": 7200,
            "archive_values_are_revised": True,
            "operational_vintage_verified": False,
            "missing_observation_imputation": False,
        },
        "baseline_lock": {
            "causal_latency_matched_persistence": (
                "latest outlet observation available under the registered one-hour "
                "publication-lag assumption, held constant to each horizon"
            ),
            "zero_latency_archive_persistence": (
                "outlet archive observation whose support ends at issue time, held "
                "constant; diagnostic only and unavailable under the lag assumption"
            ),
            "separate_baseline_at_every_horizon": True,
            "baseline_parameters_fitted": False,
        },
        "scoring_and_gate_lock": {
            "primary_metric": "rmse_m3s",
            "secondary_metrics": ["mae_m3s", "bias_m3s", "nse"],
            "common_complete_case_mask_per_horizon": True,
            "missing_target_or_baseline_imputation": False,
            "per_core_horizon_gate": (
                "graph RMSE strictly below local multi-gauge, outlet-only, and "
                "causal latency-matched persistence RMSE"
            ),
            "development_gate": "all four core horizons pass without compensation",
            "one_hour_can_change_development_gate": False,
            "mass_gate": "every executed scenario step within numeric tolerance",
            "operational_gate": "unassessable until all required forecast vintages exist",
        },
        "forbidden_after_freeze": [
            "change_horizons_or_issue_times",
            "change_graph_gain_or_support",
            "fit_lag_from_target_errors",
            "assimilate observations after issue time within a horizon rollout",
            "replace unavailable operational inputs with realized future values",
            "drop finite rows based on error",
            "change_metric_baseline_mask_or_gate",
        ],
        "claim_boundary_before_execution": {
            "lead_time_protocol_preregistered": True,
            "lead_time_diagnostic_executed": False,
            "operational_forecast_executed": False,
            "lagged_graph_kernel_fitted": False,
            "forecast_closure_validated": False,
            "geospatial_kernel_validated": False,
            "untouched_window_consumed": False,
        },
    }


def _validate_graph_parent(graph: Mapping[str, Any]) -> None:
    if (
        graph.get("schema")
        != "gwm.geotransport.center_hill_graph_multigauge_development.v1"
        or graph.get("status")
        != "public_development_graph_multigauge_diagnostic_complete"
        or (graph.get("diagnostics") or {}).get("development_gate_passed")
        is not False
        or (graph.get("data_isolation") or {}).get("graph_gain_uses_usgs_values")
        is not False
        or (graph.get("claim_boundary") or {}).get(
            "untouched_multi_system_window_consumed"
        )
        is not False
    ):
        raise ValueError("lead_time_parent_graph_report_invalid")


def _read_verified(descriptor: Mapping[str, Any]) -> bytes:
    path = (REPO_ROOT / str(descriptor["path"])).resolve()
    try:
        path.relative_to(REPO_ROOT)
    except ValueError as exc:
        raise ValueError("lead_time_parent_artifact_outside_repository") from exc
    body = path.read_bytes()
    if (
        hashlib.sha256(body).hexdigest() != descriptor.get("sha256")
        or len(body) != descriptor.get("size_bytes")
    ):
        raise ValueError("lead_time_parent_artifact_identity_mismatch")
    return body


def _load_json(path: Path) -> tuple[bytes, dict[str, Any]]:
    body = path.read_bytes()
    return body, json.loads(body)


def _artifact(path: Path, body: bytes) -> dict[str, Any]:
    return {
        "path": _display(path),
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }


def _display(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return resolved.as_posix()


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    args = parse_args()
    if args.output.exists():
        raise ValueError("lead_time_protocol_refuses_overwrite")
    protocol = compile_protocol(graph_report_path=args.graph_report)
    _write(args.output, protocol)
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
