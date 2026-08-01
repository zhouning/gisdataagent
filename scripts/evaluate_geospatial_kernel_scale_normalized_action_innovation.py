#!/usr/bin/env python3
"""Build and diagnose a scale-normalized cross-system successor candidate."""

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

from data_agent.uwm.geospatial_kernel_v2.action_innovation_scale_normalization import (
    SCALE_NORMALIZED_FORMULA,
    ScaleNormalizedActionInnovationParameters,
    derive_system_action_scale,
    scale_normalized_action_innovation_parameters_from_dict,
)
from data_agent.uwm.geospatial_kernel_v2.action_innovation_transition import (
    action_innovation_transition_parameters_from_dict,
)

if __package__:
    from scripts import evaluate_geospatial_kernel_action_innovation_cross_system as cross
else:
    import evaluate_geospatial_kernel_action_innovation_cross_system as cross


REPO_ROOT = Path(__file__).resolve().parents[1]
EVALUATOR_PATH = Path(__file__).resolve()
CORE_OPERATOR_PATH = REPO_ROOT / (
    "data_agent/uwm/geospatial_kernel_v2/"
    "action_innovation_scale_normalization.py"
)
DEFAULT_FREEZE = cross.DEFAULT_FREEZE
DEFAULT_SCALE_INPUT_REPORT = cross.DEFAULT_INPUT_REPORT
DEFAULT_EVALUATION_INPUT_REPORT = cross.DEFAULT_REPLICATION_INPUT_REPORT
DEFAULT_EVALUATION_OUTCOME_REPORT = cross.DEFAULT_REPLICATION_OUTCOME_REPORT
DEFAULT_OUTPUT_ROOT = REPO_ROOT / (
    "data/geotransport_v0_1/kernel_innovation_scale_normalized_candidate"
)
DEFAULT_IDENTITY = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "geospatial_kernel_scale_normalized_action_innovation_candidate_identity.json"
)
DEFAULT_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "geospatial_kernel_scale_normalized_action_innovation_report.json"
)

SCHEMA = "gwm.geotransport.scale_normalized_action_innovation_evaluation.v1"
IDENTITY_SCHEMA = (
    "gwm.geotransport.scale_normalized_action_innovation_candidate_identity.v1"
)
SCALE_QUANTILE = 0.9
MINIMUM_SCALE_M3S = 1.0
SOURCE_SCALE_HOURS = 168


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--freeze", type=Path, default=DEFAULT_FREEZE)
    parser.add_argument(
        "--scale-input-report", type=Path, default=DEFAULT_SCALE_INPUT_REPORT
    )
    parser.add_argument(
        "--evaluation-input-report",
        type=Path,
        default=DEFAULT_EVALUATION_INPUT_REPORT,
    )
    parser.add_argument(
        "--evaluation-outcome-report",
        type=Path,
        default=DEFAULT_EVALUATION_OUTCOME_REPORT,
    )
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--identity", type=Path, default=DEFAULT_IDENTITY)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def compile_scale_normalized_successor(
    *,
    freeze_path: Path = DEFAULT_FREEZE,
    scale_input_report_path: Path = DEFAULT_SCALE_INPUT_REPORT,
    evaluation_input_report_path: Path = DEFAULT_EVALUATION_INPUT_REPORT,
    evaluation_outcome_report_path: Path = DEFAULT_EVALUATION_OUTCOME_REPORT,
    parameter_path: Path | None = None,
    candidate_identity_path: Path | None = None,
    prediction_path: Path | None = None,
) -> tuple[dict[str, bytes], dict[str, Any]]:
    parameter_path = parameter_path or DEFAULT_OUTPUT_ROOT / "parameters.json"
    candidate_identity_path = candidate_identity_path or DEFAULT_IDENTITY
    prediction_path = prediction_path or DEFAULT_OUTPUT_ROOT / "predictions.csv"

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
    source_scale_times, source_scale_values = _parse_source_scale_panel(
        source_panel_body
    )
    source_scale = derive_system_action_scale(
        network_id=source_parameters.support.network_id,
        valid_times=source_scale_times,
        action_release_m3s=source_scale_values,
        quantile=SCALE_QUANTILE,
        minimum_scale_m3s=MINIMUM_SCALE_M3S,
        source_artifact_sha256=source_panel_descriptor["sha256"],
        provenance_id=(
            "center-hill:first-168-development-hours:action-release-p90"
        ),
        evidence_level="candidate",
        operational_vintage_verified=False,
    )

    (
        scale_input_body,
        scale_input_report,
        scale_protocol_body,
        scale_protocol,
        target_inputs,
    ) = _load_outcome_free_target_scale_inputs(scale_input_report_path)
    target_lock = scale_protocol["systems"][cross.SYSTEM_ID]
    topology_body = cross._read_verified(target_inputs["topology_report"])
    topology_report = json.loads(topology_body)
    network_body = cross._read_verified(
        topology_report["artifacts"]["full_subnetwork"]
    )
    target_support = cross._transfer_support(
        source=source_parameters.support,
        network_payload=json.loads(network_body),
        target_lock=target_lock,
        source_parameter_sha256=source_parameter_sha256,
        topology_sha256=hashlib.sha256(topology_body).hexdigest(),
    )
    target_action_body = cross._read_verified(target_inputs["action_values"])
    _, target_scale_times, target_scale_values = cross._parse_actions(
        target_action_body
    )
    target_scale = derive_system_action_scale(
        network_id=target_support.network_id,
        valid_times=target_scale_times,
        action_release_m3s=target_scale_values,
        quantile=SCALE_QUANTILE,
        minimum_scale_m3s=MINIMUM_SCALE_M3S,
        source_artifact_sha256=target_inputs["action_values"]["sha256"],
        provenance_id=(
            "j-percy-priest:2022-03-outcome-free-action-input:release-p90"
        ),
        evidence_level="candidate",
        operational_vintage_verified=False,
    )
    base_target_parameters = cross._transfer_parameters(
        source=source_parameters,
        support=target_support,
        source_parameter_sha256=source_parameter_sha256,
    )
    scale_parameters = ScaleNormalizedActionInnovationParameters(
        base_target_parameters=base_target_parameters,
        source_action_scale=source_scale,
        target_action_scale=target_scale,
        source_parameter_sha256=source_parameter_sha256,
        provenance_id=(
            "scale-normalized-successor:source=center-hill:target=j-percy-priest:"
            "scale=p90-action:drift-only"
        ),
        admitted=False,
    )
    parameter_body = _json_body(scale_parameters.as_dict())
    replay_scale_parameters = scale_normalized_action_innovation_parameters_from_dict(
        json.loads(parameter_body)
    )
    runtime_parameters = replay_scale_parameters.runtime_parameters()
    runtime_parameter_body = _json_body(runtime_parameters.as_dict())
    runtime_parameter_sha256 = hashlib.sha256(runtime_parameter_body).hexdigest()

    identity = {
        "schema": IDENTITY_SCHEMA,
        "status": "frozen_posthoc_scale_normalized_successor_not_admitted",
        "scientific_role": (
            "lock a drift-scale successor identity for future fresh evaluation; "
            "not blind validation and not admission"
        ),
        "candidate_artifacts": {
            "core_operator": _artifact(CORE_OPERATOR_PATH, CORE_OPERATOR_PATH.read_bytes()),
            "evaluator": _artifact(EVALUATOR_PATH, EVALUATOR_PATH.read_bytes()),
            "parameters": _artifact(parameter_path, parameter_body),
            "source_candidate_freeze": _artifact(freeze_path, freeze_body),
            "source_parameters": source_parameter_descriptor,
            "source_scale_panel": source_panel_descriptor,
            "target_scale_input_report": _artifact(
                scale_input_report_path, scale_input_body
            ),
            "target_scale_action": target_inputs["action_values"],
            "target_topology_report": target_inputs["topology_report"],
        },
        "operator_lock": {
            "formula": SCALE_NORMALIZED_FORMULA,
            "scale_quantile": SCALE_QUANTILE,
            "minimum_scale_m3s": MINIMUM_SCALE_M3S,
            "source_action_scale_m3s": source_scale.scale_m3s,
            "target_action_scale_m3s": target_scale.scale_m3s,
            "scale_ratio": replay_scale_parameters.scale_ratio,
            "source_baseline_drift_m3s_per_hour": (
                source_parameters.baseline_drift_m3s_per_hour
            ),
            "scaled_baseline_drift_m3s_per_hour": (
                runtime_parameters.baseline_drift_m3s_per_hour
            ),
            "action_change_coefficient_unchanged": True,
            "forcing_coefficient_unchanged": True,
            "lag_support_unchanged": True,
            "target_outcomes_used_for_scale_or_parameters": False,
            "per_window_refit_permitted": False,
        },
        "admission_contract": {
            "fresh_prospective_window_required": True,
            "independent_system_required": True,
            "operational_issue_time_vintages_required": True,
            "automatic_admission_from_posthoc_results": False,
            "candidate_admitted": False,
            "runtime_default_enabled": False,
        },
        "claim_boundary": {
            "posthoc_design_motivated_by_exposed_cross_system_failures": True,
            "candidate_identity_frozen_for_future_evaluation": True,
            "candidate_admitted": False,
            "geospatial_kernel_validated": False,
            "multi_system_generalization_validated": False,
            "operational_forecast_validated": False,
            "runtime_default_enabled": False,
        },
    }
    candidate_identity_body = _json_body(identity)
    candidate_identity_sha256 = hashlib.sha256(candidate_identity_body).hexdigest()

    # Outcome-bearing documents are intentionally loaded only after identity compilation.
    evaluation_input_body, evaluation_input = cross._load_json(
        evaluation_input_report_path
    )
    evaluation_outcome_body, evaluation_outcome = cross._load_json(
        evaluation_outcome_report_path
    )
    (
        evaluation_protocol_body,
        evaluation_protocol,
        evaluation_inputs,
        evaluation_outcomes,
    ) = cross._validate_source_reports(
        input_report=evaluation_input,
        outcome_report=evaluation_outcome,
        input_schema=cross.REPLICATION_INPUT_SCHEMA,
        outcome_schema=cross.REPLICATION_OUTCOME_SCHEMA,
    )
    if cross._descriptor_identity(evaluation_inputs["topology_report"]) != (
        cross._descriptor_identity(target_inputs["topology_report"])
    ):
        raise ValueError("scale_normalized_evaluation_topology_identity_invalid")

    prediction_body, scaled_result = cross._compile_diagnostic_window(
        target_inputs=evaluation_inputs,
        target_outcomes=evaluation_outcomes,
        target_lock=evaluation_protocol["systems"][cross.SYSTEM_ID],
        target_support=target_support,
        parameters=runtime_parameters,
        parameter_sha256=runtime_parameter_sha256,
    )
    _, unscaled_result = cross._compile_diagnostic_window(
        target_inputs=evaluation_inputs,
        target_outcomes=evaluation_outcomes,
        target_lock=evaluation_protocol["systems"][cross.SYSTEM_ID],
        target_support=target_support,
        parameters=base_target_parameters,
        parameter_sha256=source_parameter_sha256,
    )
    gate_passed = scaled_result["diagnostic_gate"][
        "cross_system_diagnostic_gate_passed"
    ]
    comparison = _compare_results(scaled_result, unscaled_result)
    scale_normalization_supported = (
        gate_passed and comparison["all_horizons_improved"]
    )
    outputs = {
        "parameters": parameter_body,
        "candidate_identity": candidate_identity_body,
        "predictions": prediction_body,
    }
    report = {
        "schema": SCHEMA,
        "status": (
            "scale_normalized_successor_posthoc_gate_passed_not_validated"
            if gate_passed
            else "scale_normalized_successor_posthoc_gate_failed"
        ),
        "generated_at": datetime.now(UTC).isoformat(),
        "candidate_identity_sha256": candidate_identity_sha256,
        "implementation_artifacts": {
            "core_operator": _artifact(CORE_OPERATOR_PATH, CORE_OPERATOR_PATH.read_bytes()),
            "evaluator": _artifact(EVALUATOR_PATH, EVALUATOR_PATH.read_bytes()),
        },
        "source_artifacts": {
            "source_candidate_freeze": _artifact(freeze_path, freeze_body),
            "source_candidate_report": freeze["candidate_artifacts"][
                "candidate_report"
            ],
            "source_parameters": source_parameter_descriptor,
            "source_scale_panel": source_panel_descriptor,
            "target_scale_input_report": _artifact(
                scale_input_report_path, scale_input_body
            ),
            "target_scale_protocol": _artifact_from_descriptor(
                scale_input_report["protocol"], scale_protocol_body
            ),
            "target_scale_action": target_inputs["action_values"],
            "evaluation_input_report": _artifact(
                evaluation_input_report_path, evaluation_input_body
            ),
            "evaluation_outcome_report": _artifact(
                evaluation_outcome_report_path, evaluation_outcome_body
            ),
            "evaluation_protocol": _artifact_from_descriptor(
                evaluation_input["protocol"], evaluation_protocol_body
            ),
            "evaluation_outcomes": evaluation_outcomes["outcome_values"],
        },
        "outputs": {
            "parameters": _artifact(parameter_path, parameter_body),
            "candidate_identity": _artifact(
                candidate_identity_path, candidate_identity_body
            ),
            "predictions": _artifact(prediction_path, prediction_body),
        },
        "scale_contract": {
            "source_action_scale": source_scale.as_dict(),
            "target_action_scale": target_scale.as_dict(),
            "scale_ratio": replay_scale_parameters.scale_ratio,
            "source_baseline_drift_m3s_per_hour": (
                source_parameters.baseline_drift_m3s_per_hour
            ),
            "scaled_baseline_drift_m3s_per_hour": (
                runtime_parameters.baseline_drift_m3s_per_hour
            ),
            "action_change_coefficient_unchanged": True,
            "forcing_coefficient_unchanged": True,
            "lag_support_unchanged": True,
        },
        "evaluation": scaled_result,
        "comparison_to_unscaled_candidate": comparison,
        "diagnostic_interpretation": {
            "hypothesis": (
                "scaling only the source baseline drift by the outcome-free "
                "target-to-source action P90 ratio improves cross-system transfer"
            ),
            "posthoc_scale_normalization_supported": (
                scale_normalization_supported
            ),
            "all_horizons_improved_against_unscaled_candidate": comparison[
                "all_horizons_improved"
            ],
            "clipping_reduced": comparison["clipped_step_count_reduction"] > 0,
            "result_may_trigger_refit_on_this_window": False,
            "next_modeling_boundary": (
                "do not tune this scalar rule on the exposed window; a future "
                "successor must normalize state, action, and forcing jointly and "
                "must be locked before fresh-system outcomes are accessed"
            ),
        },
        "selection_boundary": {
            "scale_formula_and_quantile_locked_before_outcome_document_load": True,
            "candidate_identity_compiled_before_outcome_document_load": True,
            "target_outcomes_used_for_scale_or_parameter_selection": False,
            "developer_had_seen_target_outcome_results_before_this_design": True,
            "evaluation_counts_as_fresh_validation": False,
            "result_may_trigger_refit_on_this_window": False,
            "fresh_prospective_window_consumed": False,
        },
        "claim_boundary": {
            "posthoc_diagnostic_gate_passed": gate_passed,
            "posthoc_scale_normalization_supported": (
                scale_normalization_supported
            ),
            "scale_normalized_candidate_admitted": False,
            "geospatial_kernel_validated": False,
            "multi_system_generalization_validated": False,
            "operational_forecast_validated": False,
            "runtime_default_enabled": False,
        },
    }
    return outputs, report


def _load_outcome_free_target_scale_inputs(
    path: Path,
) -> tuple[
    bytes,
    Mapping[str, Any],
    bytes,
    Mapping[str, Any],
    Mapping[str, Any],
]:
    body, report = cross._load_json(path)
    if (
        report.get("schema") != cross.INPUT_SCHEMA
        or report.get("status") != "pass_outcome_free_two_system_inputs_acquired"
        or (report.get("data_isolation") or {}).get("outcome_values_loaded")
        is not False
        or cross.SYSTEM_ID not in report.get("systems", {})
    ):
        raise ValueError("scale_normalized_target_scale_input_report_invalid")
    protocol_body = cross._read_verified(report["protocol"])
    protocol = json.loads(protocol_body)
    target_inputs = report["systems"][cross.SYSTEM_ID]
    target_lock = protocol["systems"][cross.SYSTEM_ID]
    if cross._descriptor_identity(target_inputs["topology_report"]) != (
        cross._descriptor_identity(target_lock["topology_report"])
    ):
        raise ValueError("scale_normalized_target_scale_topology_identity_invalid")
    return body, report, protocol_body, protocol, target_inputs


def _parse_source_scale_panel(
    body: bytes,
) -> tuple[tuple[datetime, ...], tuple[float, ...]]:
    reader = csv.DictReader(io.StringIO(body.decode("utf-8")))
    required = {"support_end_utc", "action_release_m3s"}
    if reader.fieldnames is None or not required.issubset(reader.fieldnames):
        raise ValueError("scale_normalized_source_panel_columns_invalid")
    rows = list(reader)[:SOURCE_SCALE_HOURS]
    times = tuple(cross._parse_time(row["support_end_utc"]) for row in rows)
    values = tuple(float(row["action_release_m3s"]) for row in rows)
    if len(rows) != SOURCE_SCALE_HOURS:
        raise ValueError("scale_normalized_source_scale_support_invalid")
    return times, values


def _compare_results(
    scaled: Mapping[str, Any], unscaled: Mapping[str, Any]
) -> dict[str, Any]:
    metrics = {
        str(horizon): {
            "scaled_candidate_rmse_m3s": scaled["metrics_by_horizon"][str(horizon)][
                "candidate"
            ]["rmse_m3s"],
            "unscaled_candidate_rmse_m3s": unscaled["metrics_by_horizon"][
                str(horizon)
            ]["candidate"]["rmse_m3s"],
            "scaled_minus_unscaled_rmse_m3s": (
                scaled["metrics_by_horizon"][str(horizon)]["candidate"]["rmse_m3s"]
                - unscaled["metrics_by_horizon"][str(horizon)]["candidate"][
                    "rmse_m3s"
                ]
            ),
        }
        for horizon in cross.HORIZONS
    }
    return {
        "metrics_by_horizon": metrics,
        "all_horizons_improved": all(
            value["scaled_minus_unscaled_rmse_m3s"] < 0.0
            for value in metrics.values()
        ),
        "unscaled_clipped_step_count": unscaled["execution"][
            "clipped_candidate_step_count"
        ],
        "scaled_clipped_step_count": scaled["execution"][
            "clipped_candidate_step_count"
        ],
        "clipped_step_count_reduction": (
            unscaled["execution"]["clipped_candidate_step_count"]
            - scaled["execution"]["clipped_candidate_step_count"]
        ),
    }


def _artifact_from_descriptor(
    descriptor: Mapping[str, Any], body: bytes
) -> dict[str, Any]:
    if (
        not isinstance(descriptor, Mapping)
        or hashlib.sha256(body).hexdigest() != descriptor.get("sha256")
        or len(body) != descriptor.get("size_bytes")
    ):
        raise ValueError("scale_normalized_artifact_body_mismatch")
    return {
        "path": str(descriptor["path"]),
        "sha256": str(descriptor["sha256"]),
        "size_bytes": int(descriptor["size_bytes"]),
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
        "candidate_identity": args.identity,
        "predictions": args.output_root / "predictions.csv",
    }
    bodies, report = compile_scale_normalized_successor(
        freeze_path=args.freeze,
        scale_input_report_path=args.scale_input_report,
        evaluation_input_report_path=args.evaluation_input_report,
        evaluation_outcome_report_path=args.evaluation_outcome_report,
        parameter_path=paths["parameters"],
        candidate_identity_path=paths["candidate_identity"],
        prediction_path=paths["predictions"],
    )
    args.output_root.mkdir(parents=True, exist_ok=True)
    args.identity.parent.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    for name, body in bodies.items():
        paths[name].write_bytes(body)
    args.report.write_bytes(_json_body(report))
    print(f"status={report['status']}")
    print(f"scale_ratio={report['scale_contract']['scale_ratio']:.9f}")
    print(
        "clipped_step_count_reduction="
        f"{report['comparison_to_unscaled_candidate']['clipped_step_count_reduction']}"
    )
    for horizon in cross.HORIZONS:
        comparison = report["comparison_to_unscaled_candidate"][
            "metrics_by_horizon"
        ][str(horizon)]
        print(
            f"horizon={horizon}h "
            f"scaled_minus_unscaled_rmse="
            f"{comparison['scaled_minus_unscaled_rmse_m3s']:.6f}"
        )


if __name__ == "__main__":
    main()
