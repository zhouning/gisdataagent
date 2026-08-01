#!/usr/bin/env python3
"""Fit and evaluate the frozen Smith Fork boundary hydrograph transition."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
import math
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from data_agent.uwm.geospatial_kernel_v2 import (
    AutoregressiveLogBoundaryParameters,
    CausalAutoregressiveLogBoundaryHydrograph,
    CausalDischargeObservation,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROTOCOL = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/smith_fork_boundary_transition_protocol.json"
)
DEFAULT_OUTPUT = REPO_ROOT / (
    "data/geotransport_v0_1/smith_fork_boundary_transition"
)
DEFAULT_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/smith_fork_boundary_transition_report.json"
)
PROTOCOL_SCHEMA = "gwm.geotransport.smith_fork_boundary_transition_protocol.v1"
REPORT_SCHEMA = "gwm.geotransport.smith_fork_boundary_transition_report.v1"
FEATURE_ID = 18_421_273
FIT_END = datetime(2021, 9, 1, 0, tzinfo=timezone.utc)
HOLDOUT_START = datetime(2021, 9, 1, 1, tzinfo=timezone.utc)
HOLDOUT_END = datetime(2021, 12, 9, 1, tzinfo=timezone.utc)
HORIZONS = (1, 3, 6, 12, 24)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def fit_and_evaluate(
    *, protocol_path: Path, output_root: Path
) -> tuple[bytes, bytes, dict[str, Any]]:
    protocol_body = protocol_path.read_bytes()
    protocol = json.loads(protocol_body)
    _validate_protocol(protocol)
    hourly_body = _read_verified(protocol["source_artifacts"]["hourly_observations"])
    values = _parse_hourly(hourly_body)

    fit_rows: list[tuple[list[float], float]] = []
    for target in sorted(values):
        lag1 = target - timedelta(hours=1)
        lag2 = target - timedelta(hours=2)
        if target <= FIT_END and lag1 in values and lag2 in values:
            fit_rows.append(
                (
                    [
                        1.0,
                        math.log1p(values[lag1]),
                        math.log1p(values[lag2]),
                    ],
                    math.log1p(values[target]),
                )
            )
    design = np.asarray([row[0] for row in fit_rows], dtype=float)
    target = np.asarray([row[1] for row in fit_rows], dtype=float)
    coefficients, residuals, rank, singular = np.linalg.lstsq(
        design, target, rcond=None
    )
    if rank != 3 or len(fit_rows) < 5_000:
        raise ValueError("boundary_transition_fit_design_invalid")
    parameters = AutoregressiveLogBoundaryParameters(
        feature_id=FEATURE_ID,
        intercept=float(coefficients[0]),
        lag1_coefficient=float(coefficients[1]),
        lag2_coefficient=float(coefficients[2]),
        timestep_seconds=3600,
        maximum_discharge_m3s=float(protocol["fit_lock"]["maximum_discharge_m3s"]),
        training_data_start=_parse_utc(
            protocol["site_and_axis_lock"]["fit_data_start_utc"]
        ),
        training_data_end=FIT_END,
        provenance_id=(
            "usgs:03424730:boundary-only-ols:"
            f"{protocol['source_artifacts']['hourly_observations']['sha256']}"
        ),
        evidence_level="candidate",
        admitted=False,
        outlet_target_calibrated=False,
    )
    predictor = CausalAutoregressiveLogBoundaryHydrograph(parameters)
    observations = tuple(
        CausalDischargeObservation(
            feature_id=FEATURE_ID,
            discharge_m3s=value,
            valid_at=valid_at,
            available_at=valid_at + timedelta(hours=1),
            quality_status="approved",
            provenance_id=f"usgs:03424730:archive:{_iso(valid_at)}",
            evidence_level="candidate",
        )
        for valid_at, value in sorted(values.items())
    )

    rows: list[dict[str, object]] = []
    for issue_time in _hour_axis(HOLDOUT_START, HOLDOUT_END):
        available = tuple(
            value for value in observations if value.available_at <= issue_time
        )
        if len(available) < 2:
            continue
        latest = available[-1]
        for horizon in HORIZONS:
            target_time = issue_time + timedelta(hours=horizon)
            if target_time not in values:
                continue
            targets = tuple(
                issue_time + timedelta(hours=offset)
                for offset in range(1, horizon + 1)
            )
            try:
                forecast = predictor.forecast(
                    available,
                    issue_time=issue_time,
                    target_valid_times=targets,
                )
            except ValueError as exc:
                if str(exc) == "boundary_hydrograph_latest_history_must_be_consecutive":
                    continue
                raise
            rows.append(
                {
                    "issue_time_utc": _iso(issue_time),
                    "target_valid_at_utc": _iso(target_time),
                    "horizon_hours": horizon,
                    "observed_discharge_m3s": values[target_time],
                    "autoregressive_log_boundary_m3s": forecast.discharge_m3s[-1],
                    "causal_persistence_m3s": latest.discharge_m3s,
                    "latest_observation_valid_at_utc": _iso(latest.valid_at),
                    "future_observations_used": False,
                }
            )
    metrics = _score(rows)
    per_horizon = {
        str(horizon): {
            "candidate_beats_causal_persistence_rmse": (
                metrics[str(horizon)]["autoregressive_log_boundary"]["rmse_m3s"]
                < metrics[str(horizon)]["causal_persistence"]["rmse_m3s"]
            )
        }
        for horizon in HORIZONS
    }
    holdout_passed = all(
        value["candidate_beats_causal_persistence_rmse"]
        for value in per_horizon.values()
    )
    parameter_body = _json_body(parameters.as_dict())
    prediction_body = _encode_rows(rows)
    parameter_path = output_root / "parameters.json"
    prediction_path = output_root / "holdout_predictions.csv"
    roots = parameters.characteristic_roots
    return parameter_body, prediction_body, {
        "schema": REPORT_SCHEMA,
        "status": "boundary_transition_fit_and_holdout_complete",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "protocol": _artifact(protocol_path, protocol_body),
        "source_artifacts": protocol["source_artifacts"],
        "outputs": {
            "parameters": _artifact(parameter_path, parameter_body),
            "holdout_predictions": _artifact(prediction_path, prediction_body),
        },
        "fit": {
            "fit_target_count": len(fit_rows),
            "design_rank": int(rank),
            "design_singular_values": [float(value) for value in singular],
            "least_squares_residual_sum": (
                None if not residuals.size else float(residuals[0])
            ),
            "intercept": parameters.intercept,
            "lag1_coefficient": parameters.lag1_coefficient,
            "lag2_coefficient": parameters.lag2_coefficient,
            "characteristic_root_magnitudes": [abs(value) for value in roots],
            "stationary": all(abs(value) < 1.0 for value in roots),
            "outlet_target_fitted_parameter_count": 0,
        },
        "metrics_by_horizon": metrics,
        "registered_gates": {
            "per_horizon": per_horizon,
            "stationarity_gate_passed": all(abs(value) < 1.0 for value in roots),
            "all_horizons_holdout_gate_passed": holdout_passed,
            "boundary_transition_development_gate_passed": holdout_passed,
        },
        "information_boundary": {
            "publication_lag_seconds": 3600,
            "future_observations_used": False,
            "operational_observation_vintage_verified": False,
            "operational_forecast_claim_permitted": False,
        },
        "data_isolation": {
            "fit_uses_only_smith_fork_pre_holdout_history": True,
            "center_hill_outlet_target_used": False,
            "downstream_development_window_used_for_fit": False,
            "d3_or_two_system_blind_outcomes_used": False,
            "missing_values_imputed": False,
        },
        "claim_boundary": {
            "boundary_transition_fitted": True,
            "upstream_temporal_holdout_evaluated": True,
            "upstream_temporal_holdout_passed": holdout_passed,
            "downstream_improvement_validated": False,
            "operational_forecast_evaluated": False,
            "geospatial_kernel_validated": False,
        },
    }


def _validate_protocol(protocol: Mapping[str, Any]) -> None:
    if (
        protocol.get("schema") != PROTOCOL_SCHEMA
        or protocol.get("status") != "frozen_before_boundary_transition_fit"
        or protocol.get("site_and_axis_lock", {}).get("horizons_hours")
        != list(HORIZONS)
        or protocol.get("fit_lock", {}).get("model")
        != "stationary_ar2_on_log1p_hourly_discharge"
    ):
        raise ValueError("boundary_transition_protocol_invalid")
    for descriptor in protocol["source_artifacts"].values():
        _read_verified(descriptor)


def _read_verified(descriptor: Mapping[str, Any]) -> bytes:
    path = (REPO_ROOT / str(descriptor["path"])).resolve()
    body = path.read_bytes()
    if (
        hashlib.sha256(body).hexdigest() != descriptor.get("sha256")
        or len(body) != descriptor.get("size_bytes")
    ):
        raise ValueError("boundary_transition_artifact_identity_mismatch")
    return body


def _parse_hourly(body: bytes) -> dict[datetime, float]:
    rows = csv.DictReader(io.StringIO(body.decode("utf-8")))
    values: dict[datetime, float] = {}
    for row in rows:
        raw = row["usgs_03424730_discharge_m3s"]
        if not raw:
            continue
        valid_at = _parse_utc(row["support_end_utc"])
        if row["native_sample_count"] != "2" or row["qualifier"] != "A":
            raise ValueError("boundary_transition_hourly_semantics_invalid")
        values[valid_at] = float(raw)
    return values


def _score(rows: list[dict[str, object]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for horizon in HORIZONS:
        selected = [row for row in rows if row["horizon_hours"] == horizon]
        observed = np.asarray(
            [float(row["observed_discharge_m3s"]) for row in selected], dtype=float
        )
        result[str(horizon)] = {
            name: _metrics(
                observed,
                np.asarray([float(row[f"{name}_m3s"]) for row in selected]),
            )
            for name in ("autoregressive_log_boundary", "causal_persistence")
        }
    return result


def _metrics(observed: np.ndarray, predicted: np.ndarray) -> dict[str, float]:
    error = predicted - observed
    denominator = float(np.sum((observed - observed.mean()) ** 2))
    return {
        "sample_count": int(observed.size),
        "rmse_m3s": float(np.sqrt(np.mean(error**2))),
        "mae_m3s": float(np.mean(np.abs(error))),
        "bias_m3s": float(np.mean(error)),
        "nse": float(1.0 - np.sum(error**2) / denominator),
    }


def _encode_rows(rows: list[dict[str, object]]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def _hour_axis(start: datetime, end: datetime) -> tuple[datetime, ...]:
    count = int((end - start).total_seconds() // 3600)
    return tuple(start + timedelta(hours=value) for value in range(count))


def _artifact(path: Path, body: bytes) -> dict[str, Any]:
    return {
        "path": path.resolve().relative_to(REPO_ROOT).as_posix(),
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("boundary_transition_timezone_required")
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _json_body(payload: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def main() -> int:
    args = parse_args()
    parameter_path = args.output / "parameters.json"
    prediction_path = args.output / "holdout_predictions.csv"
    if args.output.exists() or args.report.exists():
        raise ValueError("boundary_transition_fit_refuses_overwrite")
    parameter_body, prediction_body, report = fit_and_evaluate(
        protocol_path=args.protocol, output_root=args.output
    )
    args.output.mkdir(parents=True, exist_ok=False)
    parameter_path.write_bytes(parameter_body)
    prediction_path.write_bytes(prediction_body)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_bytes(_json_body(report))
    print(args.report)
    print(
        "coefficients="
        f"{report['fit']['intercept']:.12g},"
        f"{report['fit']['lag1_coefficient']:.12g},"
        f"{report['fit']['lag2_coefficient']:.12g}"
    )
    for horizon in HORIZONS:
        metrics = report["metrics_by_horizon"][str(horizon)]
        print(
            f"h={horizon}:ar2={metrics['autoregressive_log_boundary']['rmse_m3s']:.6f}:"
            f"persistence={metrics['causal_persistence']['rmse_m3s']:.6f}"
        )
    print(
        "holdout_gate_passed="
        f"{report['registered_gates']['all_horizons_holdout_gate_passed']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
