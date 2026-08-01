#!/usr/bin/env python3
"""Replay causal residual intervals around v5 and its traditional comparator."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
from collections import defaultdict
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from statistics import median
from typing import Any

from data_agent.uwm.geospatial_kernel_v2.online_residual_envelope import (
    ExpandingOnlineResidualEnvelope,
    OnlineResidualEnvelopeConfig,
    interval_score,
)

if __package__:
    from scripts import evaluate_geospatial_kernel_action_innovation_cross_system as cross
    from scripts import evaluate_geospatial_kernel_online_expert_traditional_baselines as source
else:
    import evaluate_geospatial_kernel_action_innovation_cross_system as cross
    import evaluate_geospatial_kernel_online_expert_traditional_baselines as source

REPO_ROOT = Path(__file__).resolve().parents[1]
EVALUATOR_PATH = Path(__file__).resolve()
CORE_PATH = REPO_ROOT / ("data_agent/uwm/geospatial_kernel_v2/online_residual_envelope.py")
DEFAULT_SOURCE_REPORT = source.DEFAULT_REPORT
DEFAULT_OUTPUT_ROOT = REPO_ROOT / (
    "data/geotransport_v0_1/geospatial_kernel_online_expert_uncertainty_posthoc"
)
DEFAULT_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/geospatial_kernel_online_expert_uncertainty_posthoc_report.json"
)
SCHEMA = "gwm.geotransport.online_expert_uncertainty_posthoc.v1"
STATUS = "online_expert_uncertainty_posthoc_complete"
WINDOW_NAMES = source.WINDOW_NAMES
HORIZONS = source.HORIZONS
MODEL_COLUMNS = {
    "v5": "physical_online_expert_blend_m3s",
    "traditional_selector": "evidence_gated_follow_the_leader_m3s",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-report", type=Path, default=DEFAULT_SOURCE_REPORT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def compile_online_expert_uncertainty_posthoc(
    *,
    source_report_path: Path = DEFAULT_SOURCE_REPORT,
    prediction_paths: Mapping[str, Path] | None = None,
    generated_at: datetime | None = None,
) -> tuple[dict[str, bytes], dict[str, Any]]:
    """Evaluate fixed online intervals without changing either point predictor."""

    prediction_paths = dict(prediction_paths or _default_prediction_paths())
    if set(prediction_paths) != set(WINDOW_NAMES):
        raise ValueError("online_expert_uncertainty_output_paths_invalid")
    source_body, source_report = _load_source_report(source_report_path)
    descriptors = source_report["outputs"]
    config = OnlineResidualEnvelopeConfig()
    outputs: dict[str, bytes] = {}
    windows: dict[str, Any] = {}
    for name in WINDOW_NAMES:
        input_body = cross._read_verified(descriptors[name])
        output_body, window = _compile_window(input_body=input_body, config=config)
        outputs[name] = output_body
        windows[name] = window

    comparisons = _comparison_counts(windows)
    return outputs, {
        "schema": SCHEMA,
        "status": STATUS,
        "generated_at": _aware_datetime(
            generated_at if generated_at is not None else datetime.now(UTC)
        ).isoformat(),
        "implementation_artifacts": {
            "online_residual_envelope": _artifact(CORE_PATH, CORE_PATH.read_bytes()),
            "evaluator": _artifact(EVALUATOR_PATH, EVALUATOR_PATH.read_bytes()),
        },
        "source_artifacts": {
            "traditional_online_expert_report": _artifact(
                source_report_path,
                source_body,
            ),
            "point_predictions_by_window": {name: dict(descriptors[name]) for name in WINDOW_NAMES},
        },
        "outputs": {
            name: _artifact(prediction_paths[name], outputs[name]) for name in WINDOW_NAMES
        },
        "fixed_uncertainty_contract": {
            **config.as_dict(),
            "models": MODEL_COLUMNS,
            "one_independent_calibration_state_per_window_model_and_horizon": True,
            "only_errors_matured_by_issue_time_enter_interval": True,
            "raw_observations_retained_by_interval_state": False,
            "signed_observation_interval_lower_bound_allowed": True,
            "negative_lower_bound_implies_reverse_flow_dynamics": False,
            "point_predictions_modified": False,
        },
        "windows": windows,
        "diagnostic_interpretation": {
            **comparisons,
            "target_marginal_coverage": config.target_marginal_coverage,
            "all_four_windows_have_evaluable_intervals": all(
                window["execution"]["both_models_interval_prediction_count"] > 0
                for window in windows.values()
            ),
            "result_may_trigger_point_model_refit_on_these_windows": False,
            "new_point_model_version_created": False,
            "prospective_primary_point_candidate_changed": False,
        },
        "information_boundary": {
            "all_target_windows_exposed_before_interval_design": True,
            "future_target_observation_used_at_interval_inference": False,
            "only_matured_historical_errors_used_at_interval_inference": True,
            "evaluation_counts_as_fresh_validation": False,
            "fresh_prospective_window_consumed": False,
            "time_series_exchangeability_claimed": False,
            "operational_issue_time_vintages_verified": False,
        },
        "claim_boundary": {
            "online_uncertainty_operator_implemented": True,
            "empirical_historical_coverage_audited": True,
            "finite_sample_coverage_guarantee_claimed": False,
            "conditional_coverage_guarantee_claimed": False,
            "uncertainty_candidate_admitted": False,
            "v5_or_selector_superiority_validated": False,
            "geospatial_kernel_validated": False,
            "runtime_default_enabled": False,
        },
    }


def _compile_window(
    *,
    input_body: bytes,
    config: OnlineResidualEnvelopeConfig,
) -> tuple[bytes, dict[str, Any]]:
    rows = _source_rows(input_body)
    rows_by_issue: dict[datetime, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        rows_by_issue[cross._parse_time(row["issue_time_utc"])].append(row)
    first_issue = min(rows_by_issue)
    envelopes = {
        name: ExpandingOnlineResidualEnvelope(state_as_of=first_issue, config=config)
        for name in MODEL_COLUMNS
    }
    pending: list[dict[str, Any]] = []
    outputs: list[dict[str, object]] = []
    matured_update_count = 0
    for issue_time in sorted(rows_by_issue):
        still_pending = []
        for sample in pending:
            if sample["available_at"] <= issue_time:
                for model_name, absolute_error in sample["absolute_errors"].items():
                    envelopes[model_name].update(
                        sample_id=sample["sample_id"],
                        forecast_horizon_hours=sample["horizon"],
                        absolute_error_m3s=absolute_error,
                        matured_at=sample["available_at"],
                        update_time=issue_time,
                    )
                matured_update_count += 1
            else:
                still_pending.append(sample)
        pending = still_pending
        for row in sorted(
            rows_by_issue[issue_time],
            key=lambda value: int(value["horizon_hours"]),
        ):
            horizon = int(row["horizon_hours"])
            observed_raw = row["observed_discharge_m3s"]
            observed = None if observed_raw == "" else float(observed_raw)
            encoded: dict[str, object] = {
                "system_id": row["system_id"],
                "issue_time_utc": row["issue_time_utc"],
                "target_support_end_utc": row["target_support_end_utc"],
                "horizon_hours": horizon,
                "observed_discharge_m3s": observed_raw,
                "target_observation_available_at_utc": row["target_observation_available_at_utc"],
            }
            point_values = {}
            for model_name, column in MODEL_COLUMNS.items():
                point = float(row[column])
                point_values[model_name] = point
                interval = envelopes[model_name].interval(
                    forecast_horizon_hours=horizon,
                    point_prediction_m3s=point,
                    issue_time=issue_time,
                )
                prefix = model_name
                encoded[f"{prefix}_point_m3s"] = point
                encoded[f"{prefix}_matured_sample_count"] = interval.matured_sample_count
                encoded[f"{prefix}_quantile_rank"] = (
                    "" if interval.quantile_rank is None else interval.quantile_rank
                )
                encoded[f"{prefix}_radius_m3s"] = (
                    "" if interval.radius_m3s is None else interval.radius_m3s
                )
                encoded[f"{prefix}_lower_m3s"] = (
                    "" if interval.lower_discharge_m3s is None else interval.lower_discharge_m3s
                )
                encoded[f"{prefix}_upper_m3s"] = (
                    "" if interval.upper_discharge_m3s is None else interval.upper_discharge_m3s
                )
                encoded[f"{prefix}_interval_available"] = interval.interval_available
                covered: bool | str = ""
                score: float | str = ""
                if observed is not None and interval.interval_available:
                    lower = float(interval.lower_discharge_m3s)
                    upper = float(interval.upper_discharge_m3s)
                    covered = lower <= observed <= upper
                    score = interval_score(
                        lower=lower,
                        upper=upper,
                        observed=observed,
                        target_coverage=config.target_marginal_coverage,
                    )
                encoded[f"{prefix}_observed_inside_interval"] = covered
                encoded[f"{prefix}_interval_score_m3s"] = score
            encoded["future_target_observation_used_at_interval_inference"] = False
            encoded["point_predictions_modified"] = False
            outputs.append(encoded)
            if observed is not None:
                pending.append(
                    {
                        "sample_id": _sample_id(row),
                        "horizon": horizon,
                        "available_at": cross._parse_time(
                            row["target_observation_available_at_utc"]
                        ),
                        "absolute_errors": {
                            name: abs(observed - value) for name, value in point_values.items()
                        },
                    }
                )
    metrics = {
        str(horizon): {
            model_name: _metrics(outputs, horizon=horizon, model_name=model_name)
            for model_name in MODEL_COLUMNS
        }
        for horizon in HORIZONS
    }
    comparison = {str(horizon): _compare_metrics(metrics[str(horizon)]) for horizon in HORIZONS}
    return _encode_rows(outputs), {
        "system_id": rows[0]["system_id"],
        "execution": {
            "source_prediction_count": len(rows),
            "interval_output_count": len(outputs),
            "matured_target_update_count": matured_update_count,
            "both_models_interval_prediction_count": sum(
                row["v5_interval_available"] and row["traditional_selector_interval_available"]
                for row in outputs
            ),
            "future_target_observation_used_at_interval_inference": False,
            "point_predictions_modified": False,
        },
        "metrics_by_horizon": metrics,
        "comparison_by_horizon": comparison,
    }


def _metrics(
    rows: list[dict[str, object]],
    *,
    horizon: int,
    model_name: str,
) -> dict[str, int | float]:
    selected = [
        row
        for row in rows
        if row["horizon_hours"] == horizon
        and row[f"{model_name}_interval_available"]
        and row["observed_discharge_m3s"] != ""
    ]
    if not selected:
        raise ValueError("online_expert_uncertainty_no_evaluable_intervals")
    covered = [bool(row[f"{model_name}_observed_inside_interval"]) for row in selected]
    widths = [
        float(row[f"{model_name}_upper_m3s"]) - float(row[f"{model_name}_lower_m3s"])
        for row in selected
    ]
    scores = [float(row[f"{model_name}_interval_score_m3s"]) for row in selected]
    negative_rows = [row for row in selected if float(row["observed_discharge_m3s"]) < 0.0]
    return {
        "evaluable_interval_count": len(selected),
        "empirical_marginal_coverage": sum(covered) / len(covered),
        "coverage_minus_target": sum(covered) / len(covered) - 0.9,
        "mean_interval_width_m3s": sum(widths) / len(widths),
        "median_interval_width_m3s": median(widths),
        "mean_interval_score_m3s": sum(scores) / len(scores),
        "negative_observation_count": len(negative_rows),
        "negative_observation_covered_count": sum(
            bool(row[f"{model_name}_observed_inside_interval"]) for row in negative_rows
        ),
    }


def _compare_metrics(metrics: Mapping[str, Mapping[str, int | float]]) -> dict[str, Any]:
    v5 = metrics["v5"]
    selector = metrics["traditional_selector"]
    v5_score = float(v5["mean_interval_score_m3s"])
    selector_score = float(selector["mean_interval_score_m3s"])
    return {
        "v5_minus_selector_mean_interval_score_m3s": v5_score - selector_score,
        "v5_lower_mean_interval_score": v5_score < selector_score,
        "selector_lower_mean_interval_score": selector_score < v5_score,
        "equal_mean_interval_score": math.isclose(
            v5_score,
            selector_score,
            abs_tol=1e-12,
        ),
        "comparison_is_posthoc": True,
    }


def _comparison_counts(
    windows: Mapping[str, Mapping[str, Any]],
) -> dict[str, int | float]:
    comparisons = [
        comparison
        for window in windows.values()
        for comparison in window["comparison_by_horizon"].values()
    ]
    metrics = {
        model_name: [
            window["metrics_by_horizon"][str(horizon)][model_name]
            for window in windows.values()
            for horizon in HORIZONS
        ]
        for model_name in MODEL_COLUMNS
    }
    negative_observation_count = sum(
        int(value["negative_observation_count"]) for value in metrics["v5"]
    )
    return {
        "window_horizon_comparison_count": len(comparisons),
        "v5_lower_mean_interval_score_count": sum(
            value["v5_lower_mean_interval_score"] for value in comparisons
        ),
        "selector_lower_mean_interval_score_count": sum(
            value["selector_lower_mean_interval_score"] for value in comparisons
        ),
        "equal_mean_interval_score_count": sum(
            value["equal_mean_interval_score"] for value in comparisons
        ),
        "v5_coverage_at_or_above_target_count": sum(
            float(value["coverage_minus_target"]) >= 0.0 for value in metrics["v5"]
        ),
        "selector_coverage_at_or_above_target_count": sum(
            float(value["coverage_minus_target"]) >= 0.0
            for value in metrics["traditional_selector"]
        ),
        "v5_minimum_coverage_minus_target": min(
            float(value["coverage_minus_target"]) for value in metrics["v5"]
        ),
        "selector_minimum_coverage_minus_target": min(
            float(value["coverage_minus_target"]) for value in metrics["traditional_selector"]
        ),
        "signed_negative_observation_count": negative_observation_count,
        "v5_signed_negative_observation_covered_count": sum(
            int(value["negative_observation_covered_count"]) for value in metrics["v5"]
        ),
        "selector_signed_negative_observation_covered_count": sum(
            int(value["negative_observation_covered_count"])
            for value in metrics["traditional_selector"]
        ),
    }


def _source_rows(body: bytes) -> list[dict[str, str]]:
    reader = csv.DictReader(io.StringIO(body.decode("utf-8")))
    required = {
        "system_id",
        "issue_time_utc",
        "target_support_end_utc",
        "horizon_hours",
        "observed_discharge_m3s",
        "target_observation_available_at_utc",
        *MODEL_COLUMNS.values(),
        "future_target_observation_used_for_selector",
        "operational_vintages_verified",
    }
    rows = list(reader)
    if (
        reader.fieldnames is None
        or not rows
        or not required.issubset(reader.fieldnames)
        or any(
            row["future_target_observation_used_for_selector"] != "False"
            or row["operational_vintages_verified"] != "False"
            or int(row["horizon_hours"]) not in HORIZONS
            for row in rows
        )
    ):
        raise ValueError("online_expert_uncertainty_source_rows_invalid")
    return rows


def _sample_id(row: Mapping[str, str]) -> str:
    return ":".join(
        (
            row["system_id"],
            row["issue_time_utc"],
            row["target_support_end_utc"],
            row["horizon_hours"],
        )
    )


def _load_source_report(path: Path) -> tuple[bytes, Mapping[str, Any]]:
    body, report = cross._load_json(path)
    information = report.get("information_boundary") or {}
    claims = report.get("claim_boundary") or {}
    if (
        report.get("schema") != source.SCHEMA
        or report.get("status") != "online_expert_traditional_baselines_posthoc_complete"
        or set(report.get("outputs", {})) != set(WINDOW_NAMES)
        or information.get("evaluation_counts_as_fresh_validation") is not False
        or claims.get("geospatial_kernel_validated") is not False
    ):
        raise ValueError("online_expert_uncertainty_source_report_invalid")
    return body, report


def _encode_rows(rows: list[dict[str, object]]) -> bytes:
    if not rows:
        raise ValueError("online_expert_uncertainty_rows_required")
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def _default_prediction_paths() -> dict[str, Path]:
    return {name: DEFAULT_OUTPUT_ROOT / f"{name}_intervals.csv" for name in WINDOW_NAMES}


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


def _aware_datetime(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("online_expert_uncertainty_generated_at_invalid")
    return value.astimezone(UTC)


def _json_body(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True) + "\n").encode("utf-8")


def main() -> None:
    args = parse_args()
    paths = {name: args.output_root / f"{name}_intervals.csv" for name in WINDOW_NAMES}
    outputs, report = compile_online_expert_uncertainty_posthoc(
        source_report_path=args.source_report,
        prediction_paths=paths,
    )
    args.output_root.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    for name, body in outputs.items():
        paths[name].write_bytes(body)
    args.report.write_bytes(_json_body(report))
    print(f"status={report['status']}")
    interpretation = report["diagnostic_interpretation"]
    print(
        "interval_score_counts="
        f"v5:{interpretation['v5_lower_mean_interval_score_count']},"
        f"selector:{interpretation['selector_lower_mean_interval_score_count']},"
        f"equal:{interpretation['equal_mean_interval_score_count']}"
    )


if __name__ == "__main__":
    main()
