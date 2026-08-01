#!/usr/bin/env python3
"""Compare the frozen Geospatial Kernel with a classical causal ARX baseline."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from data_agent.uwm.geospatial_kernel_v2.action_innovation_transition import (
    action_innovation_transition_parameters_from_dict,
)
from data_agent.uwm.geospatial_kernel_v2.classical_arx_baseline import (
    CLASSICAL_ARX_SCHEMA,
    ClassicalCausalARXParameters,
    classical_causal_arx_parameters_from_dict,
    fit_classical_causal_arx,
)

if __package__:
    from scripts import evaluate_geospatial_kernel_action_innovation_candidate as candidate
    from scripts import evaluate_geospatial_kernel_action_innovation_cross_system as cross
else:
    import evaluate_geospatial_kernel_action_innovation_candidate as candidate
    import evaluate_geospatial_kernel_action_innovation_cross_system as cross


REPO_ROOT = Path(__file__).resolve().parents[1]
EVALUATOR_PATH = Path(__file__).resolve()
CORE_OPERATOR_PATH = REPO_ROOT / (
    "data_agent/uwm/geospatial_kernel_v2/classical_arx_baseline.py"
)
DEFAULT_FREEZE = cross.DEFAULT_FREEZE
DEFAULT_PRIMARY_INPUT_REPORT = cross.DEFAULT_INPUT_REPORT
DEFAULT_PRIMARY_OUTCOME_REPORT = cross.DEFAULT_OUTCOME_REPORT
DEFAULT_REPLICATION_INPUT_REPORT = cross.DEFAULT_REPLICATION_INPUT_REPORT
DEFAULT_REPLICATION_OUTCOME_REPORT = cross.DEFAULT_REPLICATION_OUTCOME_REPORT
DEFAULT_OUTPUT_ROOT = REPO_ROOT / (
    "data/geotransport_v0_1/kernel_innovation_traditional_arx_posthoc"
)
DEFAULT_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "geospatial_kernel_traditional_arx_posthoc_report.json"
)

SCHEMA = "gwm.geotransport.geospatial_kernel_traditional_arx_posthoc.v1"
FIT_HOURS = 168
HORIZONS = cross.HORIZONS


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--freeze", type=Path, default=DEFAULT_FREEZE)
    parser.add_argument(
        "--primary-input-report", type=Path, default=DEFAULT_PRIMARY_INPUT_REPORT
    )
    parser.add_argument(
        "--primary-outcome-report", type=Path, default=DEFAULT_PRIMARY_OUTCOME_REPORT
    )
    parser.add_argument(
        "--replication-input-report",
        type=Path,
        default=DEFAULT_REPLICATION_INPUT_REPORT,
    )
    parser.add_argument(
        "--replication-outcome-report",
        type=Path,
        default=DEFAULT_REPLICATION_OUTCOME_REPORT,
    )
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def compile_traditional_arx_posthoc(
    *,
    freeze_path: Path = DEFAULT_FREEZE,
    primary_input_report_path: Path = DEFAULT_PRIMARY_INPUT_REPORT,
    primary_outcome_report_path: Path = DEFAULT_PRIMARY_OUTCOME_REPORT,
    replication_input_report_path: Path = DEFAULT_REPLICATION_INPUT_REPORT,
    replication_outcome_report_path: Path = DEFAULT_REPLICATION_OUTCOME_REPORT,
    parameter_path: Path | None = None,
    primary_prediction_path: Path | None = None,
    replication_prediction_path: Path | None = None,
) -> tuple[dict[str, bytes], dict[str, Any]]:
    parameter_path = parameter_path or DEFAULT_OUTPUT_ROOT / "parameters.json"
    primary_prediction_path = primary_prediction_path or (
        DEFAULT_OUTPUT_ROOT / "j_percy_priest_primary_predictions.csv"
    )
    replication_prediction_path = replication_prediction_path or (
        DEFAULT_OUTPUT_ROOT / "j_percy_priest_replication_predictions.csv"
    )

    freeze_body, freeze = cross._load_json(freeze_path)
    cross._validate_freeze(freeze)
    source_parameter_descriptor = freeze["candidate_artifacts"]["parameters"]
    source_parameter_body = cross._read_verified(source_parameter_descriptor)
    source_parameters = action_innovation_transition_parameters_from_dict(
        json.loads(source_parameter_body)
    )
    source_parameter_sha256 = hashlib.sha256(source_parameter_body).hexdigest()
    candidate_report_body = cross._read_verified(
        freeze["candidate_artifacts"]["candidate_report"]
    )
    candidate_report = json.loads(candidate_report_body)
    source_panel_descriptor = candidate_report["source_artifacts"]["development_panel"]
    source_panel_body = cross._read_verified(source_panel_descriptor)
    training = _parse_training_panel(source_panel_body)
    fitted = fit_classical_causal_arx(
        valid_times=tuple(row["valid_time"] for row in training),
        observed_discharge_m3s=tuple(row["outcome"] for row in training),
        action_release_m3s=tuple(row["action"] for row in training),
        lateral_forcing_m3s=tuple(row["forcing"] for row in training),
        lag_hours=source_parameters.support.lag_hours,
        lag_weights=source_parameters.support.lag_weights,
        supported_forecast_horizons_hours=(1, 3, 6, 12),
        maximum_discharge_m3s=source_parameters.maximum_discharge_m3s,
        source_artifact_sha256=source_panel_descriptor["sha256"],
        provenance_id=(
            "classical-arx1:center-hill:first-168-hours:"
            "fixed-action-lag-support=5,6,7"
        ),
    )
    parameter_body = _json_body(fitted.as_dict())
    parameters = classical_causal_arx_parameters_from_dict(json.loads(parameter_body))
    parameter_sha256 = hashlib.sha256(parameter_body).hexdigest()

    # Both target input reports are outcome-free and can be inspected after fit lock.
    (
        primary_input_body,
        primary_input,
        primary_protocol_body,
        primary_protocol,
        primary_inputs,
    ) = _load_outcome_free_input(
        primary_input_report_path, input_schema=cross.INPUT_SCHEMA
    )
    (
        replication_input_body,
        replication_input,
        replication_protocol_body,
        replication_protocol,
        replication_inputs,
    ) = _load_outcome_free_input(
        replication_input_report_path,
        input_schema=cross.REPLICATION_INPUT_SCHEMA,
    )
    if cross._descriptor_identity(primary_inputs["topology_report"]) != (
        cross._descriptor_identity(replication_inputs["topology_report"])
    ):
        raise ValueError("traditional_arx_target_topology_identity_invalid")

    topology_body = cross._read_verified(primary_inputs["topology_report"])
    topology_report = json.loads(topology_body)
    network_body = cross._read_verified(
        topology_report["artifacts"]["full_subnetwork"]
    )
    target_support = cross._transfer_support(
        source=source_parameters.support,
        network_payload=json.loads(network_body),
        target_lock=primary_protocol["systems"][cross.SYSTEM_ID],
        source_parameter_sha256=source_parameter_sha256,
        topology_sha256=hashlib.sha256(topology_body).hexdigest(),
    )
    transferred_wwm_parameters = cross._transfer_parameters(
        source=source_parameters,
        support=target_support,
        source_parameter_sha256=source_parameter_sha256,
    )
    transferred_wwm_body = _json_body(transferred_wwm_parameters.as_dict())
    transferred_wwm_sha256 = hashlib.sha256(transferred_wwm_body).hexdigest()

    # Outcome-bearing reports are loaded only after the ARX parameter body is locked.
    primary_outcome_body, primary_outcome = cross._load_json(
        primary_outcome_report_path
    )
    (
        verified_primary_protocol_body,
        verified_primary_protocol,
        verified_primary_inputs,
        primary_outcomes,
    ) = cross._validate_source_reports(
        input_report=primary_input,
        outcome_report=primary_outcome,
    )
    replication_outcome_body, replication_outcome = cross._load_json(
        replication_outcome_report_path
    )
    (
        verified_replication_protocol_body,
        verified_replication_protocol,
        verified_replication_inputs,
        replication_outcomes,
    ) = cross._validate_source_reports(
        input_report=replication_input,
        outcome_report=replication_outcome,
        input_schema=cross.REPLICATION_INPUT_SCHEMA,
        outcome_schema=cross.REPLICATION_OUTCOME_SCHEMA,
    )
    if (
        verified_primary_protocol_body != primary_protocol_body
        or verified_replication_protocol_body != replication_protocol_body
        or verified_primary_protocol != primary_protocol
        or verified_replication_protocol != replication_protocol
    ):
        raise ValueError("traditional_arx_protocol_reverification_invalid")

    primary_prediction_body, primary_result = _compile_window(
        target_inputs=verified_primary_inputs,
        target_outcomes=primary_outcomes,
        target_lock=primary_protocol["systems"][cross.SYSTEM_ID],
        target_support=target_support,
        arx_parameters=parameters,
        arx_parameter_sha256=parameter_sha256,
        wwm_parameters=transferred_wwm_parameters,
        wwm_parameter_sha256=transferred_wwm_sha256,
    )
    replication_prediction_body, replication_result = _compile_window(
        target_inputs=verified_replication_inputs,
        target_outcomes=replication_outcomes,
        target_lock=replication_protocol["systems"][cross.SYSTEM_ID],
        target_support=target_support,
        arx_parameters=parameters,
        arx_parameter_sha256=parameter_sha256,
        wwm_parameters=transferred_wwm_parameters,
        wwm_parameter_sha256=transferred_wwm_sha256,
    )

    outputs = {
        "parameters": parameter_body,
        "primary_predictions": primary_prediction_body,
        "replication_predictions": replication_prediction_body,
    }
    arx_beats_wwm_both = all(
        result["comparison"]["arx_beats_wwm_all_horizons"]
        for result in (primary_result, replication_result)
    )
    arx_beats_persistence_both = all(
        result["comparison"]["arx_beats_persistence_all_horizons"]
        for result in (primary_result, replication_result)
    )
    report = {
        "schema": SCHEMA,
        "status": "traditional_arx_zero_refit_posthoc_benchmark_complete",
        "generated_at": datetime.now(UTC).isoformat(),
        "implementation_artifacts": {
            "classical_arx_operator": _artifact(
                CORE_OPERATOR_PATH, CORE_OPERATOR_PATH.read_bytes()
            ),
            "evaluator": _artifact(EVALUATOR_PATH, EVALUATOR_PATH.read_bytes()),
        },
        "source_artifacts": {
            "source_candidate_freeze": _artifact(freeze_path, freeze_body),
            "source_candidate_report": freeze["candidate_artifacts"][
                "candidate_report"
            ],
            "source_wwm_parameters": source_parameter_descriptor,
            "source_development_panel": source_panel_descriptor,
            "primary_input_report": _artifact(
                primary_input_report_path, primary_input_body
            ),
            "primary_outcome_report": _artifact(
                primary_outcome_report_path, primary_outcome_body
            ),
            "primary_protocol": cross._artifact_from_descriptor(
                primary_input["protocol"], primary_protocol_body
            ),
            "replication_input_report": _artifact(
                replication_input_report_path, replication_input_body
            ),
            "replication_outcome_report": _artifact(
                replication_outcome_report_path, replication_outcome_body
            ),
            "replication_protocol": cross._artifact_from_descriptor(
                replication_input["protocol"], replication_protocol_body
            ),
            "target_topology_report": primary_inputs["topology_report"],
            "target_route_network": topology_report["artifacts"]["full_subnetwork"],
        },
        "outputs": {
            "parameters": _artifact(parameter_path, parameter_body),
            "primary_predictions": _artifact(
                primary_prediction_path, primary_prediction_body
            ),
            "replication_predictions": _artifact(
                replication_prediction_path, replication_prediction_body
            ),
        },
        "baseline_contract": {
            "model_family": "classical_ARX_1_transfer_function",
            "formula": fitted.as_dict()["formula"],
            "free_parameter_count": 4,
            "source_fit_hour_count": FIT_HOURS,
            "effective_fit_sample_count": parameters.training_sample_count,
            "same_source_fit_window_as_wwm": True,
            "same_action_lag_hours_as_wwm": True,
            "same_action_lag_weights_as_wwm": True,
            "same_target_rows_as_wwm": True,
            "per_target_window_refit_performed": False,
            "target_outcomes_used_for_fit": False,
        },
        "parameter_lock": {
            "schema": CLASSICAL_ARX_SCHEMA,
            "parameter_sha256": parameter_sha256,
            "parameter_body_compiled_before_target_outcome_document_load": True,
            "all_windows_use_deserialized_parameter_artifact": True,
        },
        "primary_window": primary_result,
        "replication_window": replication_result,
        "diagnostic_interpretation": {
            "arx_beats_wwm_all_horizons_in_both_windows": arx_beats_wwm_both,
            "arx_beats_persistence_all_horizons_in_both_windows": (
                arx_beats_persistence_both
            ),
            "benchmark_role": (
                "test whether the current WWM exceeds a classical linear dynamic "
                "model under a near-matched information and calibration budget"
            ),
            "result_may_trigger_refit_on_these_windows": False,
            "t_route_mc_physical_baseline_still_required": True,
        },
        "information_boundary": {
            "historical_realized_action_used": True,
            "retrospective_nwm_forcing_used": True,
            "latest_outlet_observation_used_as_issue_state": True,
            "future_outlet_observations_used_inside_rollout": False,
            "operational_issue_time_vintages_verified": False,
            "evaluation_counts_as_fresh_validation": False,
            "fresh_prospective_window_consumed": False,
        },
        "claim_boundary": {
            "traditional_arx_posthoc_benchmark_executed": True,
            "traditional_physical_router_benchmark_executed": False,
            "arx_parameters_admitted": False,
            "wwm_candidate_admitted": False,
            "geospatial_kernel_validated": False,
            "multi_system_generalization_validated": False,
            "operational_forecast_validated": False,
            "runtime_default_enabled": False,
        },
    }
    return outputs, report


def _parse_training_panel(body: bytes) -> list[dict[str, Any]]:
    reader = csv.DictReader(io.StringIO(body.decode("utf-8")))
    required = {
        "support_end_utc",
        "action_release_m3s",
        "nwm_q_lateral_active_reach_sum_m3s",
        "outcome_discharge_interval_sample_mean_m3s",
        "outcome_available",
    }
    if reader.fieldnames is None or not required.issubset(reader.fieldnames):
        raise ValueError("traditional_arx_training_panel_columns_invalid")
    source = list(reader)[:FIT_HOURS]
    rows = [
        {
            "valid_time": cross._parse_time(row["support_end_utc"]),
            "action": float(row["action_release_m3s"]),
            "forcing": float(row["nwm_q_lateral_active_reach_sum_m3s"]),
            "outcome": float(row["outcome_discharge_interval_sample_mean_m3s"]),
        }
        for row in source
    ]
    if (
        len(rows) != FIT_HOURS
        or any(row["outcome_available"].lower() != "true" for row in source)
    ):
        raise ValueError("traditional_arx_training_panel_support_invalid")
    return rows


def _load_outcome_free_input(
    path: Path, *, input_schema: str
) -> tuple[
    bytes,
    Mapping[str, Any],
    bytes,
    Mapping[str, Any],
    Mapping[str, Any],
]:
    body, report = cross._load_json(path)
    if (
        report.get("schema") != input_schema
        or report.get("status") != "pass_outcome_free_two_system_inputs_acquired"
        or (report.get("data_isolation") or {}).get("outcome_values_loaded")
        is not False
        or cross.SYSTEM_ID not in report.get("systems", {})
    ):
        raise ValueError("traditional_arx_outcome_free_input_report_invalid")
    protocol_body = cross._read_verified(report["protocol"])
    protocol = json.loads(protocol_body)
    inputs = report["systems"][cross.SYSTEM_ID]
    lock = protocol["systems"][cross.SYSTEM_ID]
    if cross._descriptor_identity(inputs["topology_report"]) != (
        cross._descriptor_identity(lock["topology_report"])
    ):
        raise ValueError("traditional_arx_input_topology_identity_invalid")
    return body, report, protocol_body, protocol, inputs


def _compile_window(
    *,
    target_inputs: Mapping[str, Any],
    target_outcomes: Mapping[str, Any],
    target_lock: Mapping[str, Any],
    target_support: Any,
    arx_parameters: ClassicalCausalARXParameters,
    arx_parameter_sha256: str,
    wwm_parameters: Any,
    wwm_parameter_sha256: str,
) -> tuple[bytes, dict[str, Any]]:
    wwm_body, wwm_result = cross._compile_diagnostic_window(
        target_inputs=target_inputs,
        target_outcomes=target_outcomes,
        target_lock=target_lock,
        target_support=target_support,
        parameters=wwm_parameters,
        parameter_sha256=wwm_parameter_sha256,
    )
    window = cross._load_window(
        target_inputs=target_inputs,
        target_outcomes=target_outcomes,
        target_lock=target_lock,
        target_support=target_support,
    )
    valid_times = tuple(window["valid_times"])
    time_index = {value: index for index, value in enumerate(valid_times)}
    rows: list[dict[str, object]] = []
    clipped_step_count = 0
    for source in csv.DictReader(io.StringIO(wwm_body.decode("utf-8"))):
        issue_time = cross._parse_time(source["issue_time_utc"])
        target_time = cross._parse_time(source["target_support_end_utc"])
        issue_index = time_index[issue_time]
        target_index = time_index[target_time]
        prediction, clipped = arx_parameters.forecast(
            initial_discharge_m3s=float(source["causal_persistence_m3s"]),
            issue_index=issue_index,
            target_indices=(target_index,),
            action_release_m3s=tuple(window["action_values"]),
            lateral_forcing_m3s=tuple(window["forcing_values"]),
        )
        clipped_step_count += clipped
        rows.append(
            {
                "system_id": source["system_id"],
                "issue_time_utc": source["issue_time_utc"],
                "target_support_end_utc": source["target_support_end_utc"],
                "horizon_hours": int(source["horizon_hours"]),
                "observed_discharge_m3s": source["observed_discharge_m3s"],
                "classical_arx_m3s": prediction[0],
                "action_innovation_wwm_m3s": source[
                    "action_innovation_candidate_m3s"
                ],
                "causal_persistence_m3s": source["causal_persistence_m3s"],
                "latest_observation_valid_at_utc": source[
                    "latest_observation_valid_at_utc"
                ],
                "latest_observation_available_at_utc": source[
                    "latest_observation_available_at_utc"
                ],
                "future_outcome_observation_used": False,
                "operational_vintages_verified": False,
                "arx_parameter_sha256": arx_parameter_sha256,
                "wwm_parameter_sha256": wwm_parameter_sha256,
            }
        )
    columns = {
        "classical_arx": "classical_arx_m3s",
        "action_innovation_wwm": "action_innovation_wwm_m3s",
        "causal_persistence": "causal_persistence_m3s",
    }
    metrics, scoring = candidate._score(rows, columns)
    for horizon in HORIZONS:
        if metrics[str(horizon)]["action_innovation_wwm"] != (
            wwm_result["metrics_by_horizon"][str(horizon)]["candidate"]
        ):
            raise ValueError("traditional_arx_wwm_metric_replay_mismatch")
    comparison = {
        "per_horizon": {
            str(horizon): {
                "arx_minus_wwm_rmse_m3s": (
                    metrics[str(horizon)]["classical_arx"]["rmse_m3s"]
                    - metrics[str(horizon)]["action_innovation_wwm"]["rmse_m3s"]
                ),
                "arx_minus_persistence_rmse_m3s": (
                    metrics[str(horizon)]["classical_arx"]["rmse_m3s"]
                    - metrics[str(horizon)]["causal_persistence"]["rmse_m3s"]
                ),
            }
            for horizon in HORIZONS
        }
    }
    comparison["arx_beats_wwm_all_horizons"] = all(
        value["arx_minus_wwm_rmse_m3s"] < 0.0
        for value in comparison["per_horizon"].values()
    )
    comparison["arx_beats_persistence_all_horizons"] = all(
        value["arx_minus_persistence_rmse_m3s"] < 0.0
        for value in comparison["per_horizon"].values()
    )
    return cross._encode_rows(rows), {
        "window": wwm_result["window"],
        "metrics_by_horizon": metrics,
        "comparison": comparison,
        "scoring": scoring,
        "execution": {
            "prediction_row_count": len(rows),
            "arx_clipped_recursive_step_count": clipped_step_count,
            "future_outcome_observation_used": False,
        },
    }


def _artifact(path: Path, body: bytes) -> dict[str, Any]:
    return {
        "path": cross._display(path),
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }


def _json_body(value: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def main() -> None:
    args = parse_args()
    paths = {
        "parameters": args.output_root / "parameters.json",
        "primary_predictions": (
            args.output_root / "j_percy_priest_primary_predictions.csv"
        ),
        "replication_predictions": (
            args.output_root / "j_percy_priest_replication_predictions.csv"
        ),
    }
    bodies, report = compile_traditional_arx_posthoc(
        freeze_path=args.freeze,
        primary_input_report_path=args.primary_input_report,
        primary_outcome_report_path=args.primary_outcome_report,
        replication_input_report_path=args.replication_input_report,
        replication_outcome_report_path=args.replication_outcome_report,
        parameter_path=paths["parameters"],
        primary_prediction_path=paths["primary_predictions"],
        replication_prediction_path=paths["replication_predictions"],
    )
    args.output_root.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    for name, body in bodies.items():
        paths[name].write_bytes(body)
    args.report.write_bytes(_json_body(report))
    print(f"status={report['status']}")
    for window_name in ("primary_window", "replication_window"):
        for horizon in HORIZONS:
            comparison = report[window_name]["comparison"]["per_horizon"][
                str(horizon)
            ]
            print(
                f"window={window_name} horizon={horizon}h "
                f"arx_minus_wwm_rmse="
                f"{comparison['arx_minus_wwm_rmse_m3s']:.6f} "
                f"arx_minus_persistence_rmse="
                f"{comparison['arx_minus_persistence_rmse_m3s']:.6f}"
            )


if __name__ == "__main__":
    main()
