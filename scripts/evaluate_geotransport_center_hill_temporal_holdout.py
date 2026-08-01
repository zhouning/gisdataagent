#!/usr/bin/env python3
"""Score the frozen Center Hill temporal holdout exactly once as registered."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
import math
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from data_agent.uwm.geospatial_kernel_v2 import (
    ActionBoundaryFlux,
    ForcingFlux,
    LinearReferencedPath,
    ReachHydraulicState,
    ReachTransportConfig,
    StateDependentReachTransportOperator,
    StockState,
)

if __package__:
    from scripts.build_geotransport_center_hill_672h_reach_transport_rollout import (
        compile_rollout as compile_development_rollout,
    )
    from scripts.build_geotransport_center_hill_reach_transport_smoke import (
        _linear_path,
        _read_reach_values,
    )
else:
    from build_geotransport_center_hill_672h_reach_transport_rollout import (
        compile_rollout as compile_development_rollout,
    )
    from build_geotransport_center_hill_reach_transport_smoke import (
        _linear_path,
        _read_reach_values,
    )


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROTOCOL = (
    REPO_ROOT
    / "benchmarks/geotransport_v0_1/center_hill_temporal_holdout_protocol_v1.json"
)
DEFAULT_PANEL_REPORT = (
    REPO_ROOT
    / "benchmarks/geotransport_v0_1/center_hill_temporal_holdout_panel_report.json"
)
DEFAULT_NWM_MANIFEST = (
    REPO_ROOT
    / "data/geotransport_v0_1/center_hill_evaluation/nwm/acquisition_manifest.json"
)
DEFAULT_TRAVEL_REPORT = (
    REPO_ROOT
    / "benchmarks/geotransport_v0_1/center_hill_travel_time_prior_report.json"
)
DEFAULT_DEVELOPMENT_ROLLOUT_REPORT = (
    REPO_ROOT
    / "benchmarks/geotransport_v0_1/center_hill_672h_reach_transport_rollout_report.json"
)
DEFAULT_DEVELOPMENT_PANEL_REPORT = (
    REPO_ROOT
    / "benchmarks/geotransport_v0_1/center_hill_672h_development_panel_report.json"
)
DEFAULT_DEVELOPMENT_Q_MANIFEST = (
    REPO_ROOT
    / "data/geotransport_v0_1/nwm_q_lateral_672h/extraction_manifest.json"
)
DEFAULT_OUTPUT = (
    REPO_ROOT
    / "data/geotransport_v0_1/center_hill_evaluation/evaluation/center_hill_temporal_holdout_predictions.csv"
)
DEFAULT_REPORT = (
    REPO_ROOT
    / "benchmarks/geotransport_v0_1/center_hill_temporal_holdout_evaluation_report.json"
)
SCHEMA = "gwm.geotransport.center_hill_temporal_holdout_evaluation.v1"
HOUR_COUNT = 672
WARMUP_HOURS = 168
SCENARIOS = ("candidate", "zero_action", "no_forcing", "reversed_topology")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--panel-report", type=Path, default=DEFAULT_PANEL_REPORT)
    parser.add_argument("--nwm-manifest", type=Path, default=DEFAULT_NWM_MANIFEST)
    parser.add_argument("--travel-report", type=Path, default=DEFAULT_TRAVEL_REPORT)
    parser.add_argument(
        "--development-rollout-report",
        type=Path,
        default=DEFAULT_DEVELOPMENT_ROLLOUT_REPORT,
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def compile_evaluation(
    *,
    protocol_path: Path = DEFAULT_PROTOCOL,
    panel_report_path: Path = DEFAULT_PANEL_REPORT,
    nwm_manifest_path: Path = DEFAULT_NWM_MANIFEST,
    travel_report_path: Path = DEFAULT_TRAVEL_REPORT,
    development_rollout_report_path: Path = DEFAULT_DEVELOPMENT_ROLLOUT_REPORT,
    output_path: Path = DEFAULT_OUTPUT,
) -> tuple[bytes, dict[str, Any]]:
    protocol_body, protocol = _load_json(protocol_path)
    panel_report_body, panel_report = _load_json(panel_report_path)
    nwm_body, nwm = _load_json(nwm_manifest_path)
    travel_body, travel = _load_json(travel_report_path)
    development_report_body, frozen_development_report = _load_json(
        development_rollout_report_path
    )
    _validate_sources(
        protocol=protocol,
        protocol_body=protocol_body,
        protocol_path=protocol_path,
        panel=panel_report,
        nwm=nwm,
        travel=travel,
        frozen_development_report=frozen_development_report,
        frozen_development_report_body=development_report_body,
        frozen_development_report_path=development_rollout_report_path,
    )

    development = compile_development_rollout()
    for key, value in development.report.items():
        if frozen_development_report.get(key) != value:
            raise ValueError("evaluation_development_state_recompute_mismatch")

    panel_descriptor = panel_report["panel_artifact"]
    panel_body = _read_verified_artifact(panel_descriptor)
    panel_rows = list(csv.DictReader(io.StringIO(panel_body.decode("utf-8"))))
    _validate_panel_rows(panel_rows)
    q_descriptor = nwm["value_artifacts"]["q_lateral"]
    velocity_descriptor = nwm["value_artifacts"]["velocity"]
    q_body = _read_verified_artifact(q_descriptor)
    velocity_body = _read_verified_artifact(velocity_descriptor)
    q_values = _read_reach_values(
        q_body,
        value_column="q_lateral_m3s",
        role_column="source_role",
        expected_role="modeled_forcing",
    )
    velocity_values = _read_reach_values(
        velocity_body,
        value_column="velocity_ms",
        role_column="source_role",
        expected_role="modeled_state_context",
    )

    path = _linear_path(travel["linear_referenced_path"])
    config = ReachTransportConfig(
        timestep_seconds=3600.0,
        allow_unadmitted_components_for_diagnostics=True,
    )
    forward_operator = StateDependentReachTransportOperator(path, config)
    reverse_path = _reverse_active_path(forward_operator)
    reverse_operator = StateDependentReachTransportOperator(reverse_path, config)
    if len(development.final_stock_values_m3) != len(forward_operator.active_feature_ids):
        raise ValueError("evaluation_development_final_stock_axis_mismatch")
    (
        ablation_development_states,
        scenario_failures,
    ) = _recompute_ablation_development_states(
        forward_operator=forward_operator,
        reverse_operator=reverse_operator,
        travel=travel,
        protocol=protocol,
    )
    states: dict[str, StockState] = {
        "candidate": StockState(
            development.final_stock_values_m3,
            "m3",
            "center_hill:frozen_development_final_state",
        ),
    }
    states.update(ablation_development_states)
    operators = {
        "candidate": forward_operator,
        "zero_action": forward_operator,
        "no_forcing": forward_operator,
        "reversed_topology": reverse_operator,
    }
    initial_storage = {
        name: float(sum(states[name].values)) if name in states else None
        for name in SCENARIOS
    }
    predictions: dict[str, list[float]] = {name: [] for name in SCENARIOS}
    residuals: dict[str, list[float]] = {name: [] for name in SCENARIOS}
    numeric_tolerances: dict[str, list[float]] = {
        name: [] for name in SCENARIOS
    }
    inputs = {name: 0.0 for name in SCENARIOS}
    outlets = {name: 0.0 for name in SCENARIOS}

    for row in panel_rows:
        support_start = row["support_start_utc"]
        support_end = row["support_end_utc"]
        q_by_id = q_values.get(support_start)
        velocity_by_id = velocity_values.get(support_start)
        if q_by_id is None or velocity_by_id is None:
            raise ValueError("evaluation_hourly_reach_values_missing")
        action_rate = float(row["action_release_m3s"])
        for scenario in SCENARIOS:
            if scenario in scenario_failures:
                predictions[scenario].append(float("nan"))
                continue
            operator = operators[scenario]
            active_ids = operator.active_feature_ids
            q_active = tuple(q_by_id[feature_id] for feature_id in active_ids)
            velocity_active = tuple(
                velocity_by_id[feature_id] for feature_id in active_ids
            )
            action = None
            if scenario != "zero_action":
                action = ActionBoundaryFlux(
                    (action_rate,) + (0.0,) * (len(active_ids) - 1),
                    "m3 s-1",
                    f"cwms:eop:{support_end}:{scenario}",
                )
            forcing = None
            if scenario != "no_forcing":
                forcing = ForcingFlux(
                    q_active,
                    "m3 s-1",
                    f"nwm:q_lateral:{support_start}:{scenario}",
                    modeled=True,
                )
            try:
                result = operator.step(
                    states[scenario],
                    ReachHydraulicState(
                        active_ids,
                        velocity_active,
                        "river_velocity_proxy",
                        f"nwm:velocity:{support_start}:{scenario}",
                        "candidate",
                        False,
                    ),
                    action=action,
                    forcing=forcing,
                )
            except RuntimeError as exc:
                scenario_failures[scenario] = {
                    "phase": "evaluation",
                    "support_start_utc": support_start,
                    "error": str(exc),
                }
                predictions[scenario].append(float("nan"))
                continue
            numeric_scale = max(
                1.0,
                float(sum(states[scenario].values)),
                result.input_volume_m3,
            )
            tolerance = (
                config.absolute_mass_tolerance_m3
                + np.finfo(float).eps * 1_000.0 * numeric_scale
            )
            predictions[scenario].append(result.outlet_mean_flow_m3s)
            residuals[scenario].append(result.global_mass_balance_residual_m3)
            numeric_tolerances[scenario].append(tolerance)
            inputs[scenario] += result.input_volume_m3
            outlets[scenario] += result.outlet_volume_m3
            states[scenario] = result.next_stock

    scenario_conservation: dict[str, dict[str, Any]] = {}
    for name in SCENARIOS:
        if name in scenario_failures:
            scenario_conservation[name] = {
                "gate_status": "fail",
                "reason": "operator_step_failed_before_complete_series",
                "failure": scenario_failures[name],
            }
        else:
            scenario_conservation[name] = _conservation_summary(
                initial_storage=float(initial_storage[name]),
                final_storage=float(sum(states[name].values)),
                input_volume=inputs[name],
                outlet_volume=outlets[name],
                residuals=residuals[name],
                numeric_tolerances=numeric_tolerances[name],
            )

    scored_rows: list[dict[str, Any]] = []
    for index in range(WARMUP_HOURS, HOUR_COUNT):
        row = panel_rows[index]
        previous = panel_rows[index - 1]
        observed = _optional_float(
            row["outcome_discharge_interval_sample_mean_m3s"]
        )
        persistence = _optional_float(
            previous["outcome_discharge_interval_sample_mean_m3s"]
        )
        scored_rows.append(
            {
                "support_start_utc": row["support_start_utc"],
                "support_end_utc": row["support_end_utc"],
                "observed_m3s": observed,
                "candidate_m3s": predictions["candidate"][index],
                "persistence_m3s": persistence,
                "direct_release_m3s": float(row["action_release_m3s"]),
                "zero_action_m3s": _finite_or_none(
                    predictions["zero_action"][index]
                ),
                "no_forcing_m3s": _finite_or_none(
                    predictions["no_forcing"][index]
                ),
                "reversed_topology_m3s": _finite_or_none(
                    predictions["reversed_topology"][index]
                ),
                "candidate_step_mass_balance_residual_m3": residuals[
                    "candidate"
                ][index],
            }
        )
    primary_columns = (
        "observed_m3s",
        "candidate_m3s",
        "persistence_m3s",
        "direct_release_m3s",
    )
    primary_complete_rows = [
        row
        for row in scored_rows
        if all(
            row[column] is not None and math.isfinite(float(row[column]))
            for column in primary_columns
        )
    ]
    if not primary_complete_rows:
        raise ValueError("evaluation_no_common_complete_scored_rows")
    metrics = {
        name: _metrics(
            [float(row["observed_m3s"]) for row in primary_complete_rows],
            [float(row[column]) for row in primary_complete_rows],
        )
        for name, column in (
            ("candidate", "candidate_m3s"),
            ("persistence", "persistence_m3s"),
            ("direct_release", "direct_release_m3s"),
        )
    }
    candidate_predictions = np.asarray(
        [float(row["candidate_m3s"]) for row in primary_complete_rows]
    )
    gates = {
        "accuracy_better_than_persistence": (
            "pass"
            if metrics["candidate"]["rmse_m3s"]
            < metrics["persistence"]["rmse_m3s"]
            else "fail"
        ),
        "accuracy_better_than_direct_release": (
            "pass"
            if metrics["candidate"]["rmse_m3s"]
            < metrics["direct_release"]["rmse_m3s"]
            else "fail"
        ),
    }
    ablation_diagnostics: dict[str, dict[str, Any]] = {}
    for name, column in (
        ("zero_action", "zero_action_m3s"),
        ("no_forcing", "no_forcing_m3s"),
        ("reversed_topology", "reversed_topology_m3s"),
    ):
        ablation_rows = [
            row
            for row in primary_complete_rows
            if row[column] is not None and math.isfinite(float(row[column]))
        ]
        if len(ablation_rows) != len(primary_complete_rows):
            gates[f"{name}_degrades_accuracy_and_changes_prediction"] = "fail"
            ablation_diagnostics[name] = {
                "gate_status": "fail",
                "reason": "registered_ablation_series_unavailable",
                "available_scored_hours": len(ablation_rows),
                "failure": scenario_failures.get(name),
            }
            metrics[name] = None
            continue
        alternative = np.asarray([float(row[column]) for row in ablation_rows])
        observed = [float(row["observed_m3s"]) for row in ablation_rows]
        metrics[name] = _metrics(observed, list(alternative))
        change = float(np.mean(np.abs(candidate_predictions - alternative)))
        status = (
            "pass"
            if metrics[name]["rmse_m3s"] > metrics["candidate"]["rmse_m3s"]
            and change > 0.0
            else "fail"
        )
        gates[f"{name}_degrades_accuracy_and_changes_prediction"] = status
        ablation_diagnostics[name] = {
            "gate_status": status,
            "rmse_degradation_m3s": (
                metrics[name]["rmse_m3s"] - metrics["candidate"]["rmse_m3s"]
            ),
            "mean_absolute_prediction_change_m3s": change,
        }
    gates["all_scenarios_conservative"] = (
        "pass"
        if all(
            row["gate_status"] == "pass"
            for row in scenario_conservation.values()
        )
        else "fail"
    )
    overall = "pass" if set(gates.values()) == {"pass"} else "fail"
    csv_body = _encode_csv(scored_rows)
    report = {
        "schema": SCHEMA,
        "status": f"registered_single_system_temporal_holdout_{overall}",
        "evaluation_role": "external_temporal_holdout",
        "source_artifacts": {
            "evaluation_protocol": _artifact(protocol_path, protocol_body),
            "evaluation_panel_report": _artifact(
                panel_report_path, panel_report_body
            ),
            "evaluation_panel": _artifact_from_descriptor(panel_descriptor),
            "evaluation_nwm_manifest": _artifact(nwm_manifest_path, nwm_body),
            "q_lateral_values": _artifact_from_descriptor(q_descriptor),
            "velocity_values": _artifact_from_descriptor(velocity_descriptor),
            "travel_time_prior_report": _artifact(travel_report_path, travel_body),
            "development_rollout_report": _artifact(
                development_rollout_report_path, development_report_body
            ),
        },
        "protocol_compliance": {
            "dates_unchanged": True,
            "warmup_length_unchanged": True,
            "operator_unchanged": True,
            "parameter_fitting_on_evaluation_outcome": False,
            "missing_outcome_imputation": False,
            "common_complete_case_mask_used": True,
            "all_registered_ablation_series_produced": not scenario_failures,
            "metric_and_gate_thresholds_unchanged": True,
            "score_run_count": 1,
        },
        "window": {
            "acquisition_start_inclusive": panel_report["window"]["start_inclusive"],
            "scored_start_inclusive": panel_report["window"][
                "scored_start_inclusive"
            ],
            "end_exclusive": panel_report["window"]["end_exclusive"],
            "evaluation_warmup_hours": WARMUP_HOURS,
            "maximum_scored_hours": HOUR_COUNT - WARMUP_HOURS,
            "primary_common_complete_scored_hours": len(primary_complete_rows),
            "excluded_primary_scored_hours": (
                len(scored_rows) - len(primary_complete_rows)
            ),
        },
        "initial_state": {
            "source": (
                "recomputed_frozen_development_final_per_reach_state_per_scenario"
            ),
            "reach_count": len(development.final_stock_values_m3),
            "total_storage_m3_by_scenario": initial_storage,
            "state_reset_at_evaluation_boundary": False,
            "outcome_used": False,
        },
        "metrics": metrics,
        "scenario_failures": scenario_failures,
        "ablation_diagnostics": ablation_diagnostics,
        "conservation": scenario_conservation,
        "gate_statuses": gates,
        "overall_gate_status": overall,
        "aggregation": "non_compensatory_all_registered_gates_must_pass",
        "output_artifact": {
            "path": _display(output_path),
            "sha256": hashlib.sha256(csv_body).hexdigest(),
            "size_bytes": len(csv_body),
        },
        "claim_boundary": {
            "evaluation_values_acquired": True,
            "evaluation_scored": True,
            "registered_single_system_temporal_holdout_passed": overall == "pass",
            "empirical_support_for_candidate_operator": overall == "pass",
            "identified_causal_action_effect": False,
            "river_velocity_admitted_as_flood_wave_celerity": False,
            "flood_wave_transport_admitted": False,
            "hydrodynamically_validated": False,
            "benchmark_validated": False,
            "multi_system_generalization_validated": False,
            "geospatial_kernel_validated": False,
        },
    }
    return csv_body, report


def _recompute_ablation_development_states(
    *,
    forward_operator: StateDependentReachTransportOperator,
    reverse_operator: StateDependentReachTransportOperator,
    travel: Mapping[str, Any],
    protocol: Mapping[str, Any],
) -> tuple[dict[str, StockState], dict[str, dict[str, str]]]:
    panel_report_body, panel_report = _load_json(DEFAULT_DEVELOPMENT_PANEL_REPORT)
    q_manifest_body, q_manifest = _load_json(DEFAULT_DEVELOPMENT_Q_MANIFEST)
    if (
        panel_report.get("schema")
        != "gwm.geotransport.center_hill_672h_development_panel.v1"
        or q_manifest.get("schema")
        != "gwm.geotransport.nwm_q_lateral_extract.v1"
    ):
        raise ValueError("evaluation_ablation_development_sources_invalid")
    parent = protocol.get("parent_development_evidence") or {}
    if parent.get("panel_report") != _artifact(
        DEFAULT_DEVELOPMENT_PANEL_REPORT, panel_report_body
    ) or (panel_report.get("source_manifests") or {}).get(
        "nwm_q_lateral_672h"
    ) != _artifact(DEFAULT_DEVELOPMENT_Q_MANIFEST, q_manifest_body):
        raise ValueError("evaluation_ablation_development_lineage_mismatch")
    panel_body = _read_verified_artifact(panel_report["panel_artifact"])
    rows = list(csv.DictReader(io.StringIO(panel_body.decode("utf-8"))))
    if len(rows) != HOUR_COUNT:
        raise ValueError("evaluation_ablation_development_requires_672_rows")
    q_descriptor = (q_manifest.get("value_artifacts") or [None])[0]
    if not isinstance(q_descriptor, Mapping):
        raise ValueError("evaluation_ablation_development_q_artifact_missing")
    q_values = _read_reach_values(
        _read_verified_artifact(q_descriptor),
        value_column="q_lateral_m3s",
        role_column="source_role",
        expected_role="modeled_forcing",
    )
    velocity_descriptor = travel["source_artifacts"]["selected_velocity"]
    velocity_values = _read_reach_values(
        _read_verified_artifact(velocity_descriptor),
        value_column="velocity_ms",
        role_column="source_role",
        expected_role="modeled_state_context",
        target_start=rows[0]["support_start_utc"],
        target_end=rows[-1]["support_end_utc"],
    )
    operators = {
        "zero_action": forward_operator,
        "no_forcing": forward_operator,
        "reversed_topology": reverse_operator,
    }
    states = {
        name: operator.zero_state(
            provenance_id=f"center_hill:development_zero_state:{name}"
        )
        for name, operator in operators.items()
    }
    failures: dict[str, dict[str, str]] = {}
    for row in rows:
        support_start = row["support_start_utc"]
        support_end = row["support_end_utc"]
        q_by_id = q_values[support_start]
        velocity_by_id = velocity_values[support_start]
        action_rate = float(row["action_release_m3s"])
        for name, operator in operators.items():
            if name in failures:
                continue
            active_ids = operator.active_feature_ids
            action = None
            if name != "zero_action":
                action = ActionBoundaryFlux(
                    (action_rate,) + (0.0,) * (len(active_ids) - 1),
                    "m3 s-1",
                    f"cwms:development:{support_end}:{name}",
                )
            forcing = None
            if name != "no_forcing":
                forcing = ForcingFlux(
                    tuple(q_by_id[feature_id] for feature_id in active_ids),
                    "m3 s-1",
                    f"nwm:development:q_lateral:{support_start}:{name}",
                    modeled=True,
                )
            try:
                result = operator.step(
                    states[name],
                    ReachHydraulicState(
                        active_ids,
                        tuple(
                            velocity_by_id[feature_id] for feature_id in active_ids
                        ),
                        "river_velocity_proxy",
                        f"nwm:development:velocity:{support_start}:{name}",
                        "candidate",
                        False,
                    ),
                    action=action,
                    forcing=forcing,
                )
            except RuntimeError as exc:
                failures[name] = {
                    "phase": "development_recompute",
                    "support_start_utc": support_start,
                    "error": str(exc),
                }
                continue
            states[name] = result.next_stock
    return (
        {name: state for name, state in states.items() if name not in failures},
        failures,
    )


def _validate_sources(
    *,
    protocol: Mapping[str, Any],
    protocol_body: bytes,
    protocol_path: Path,
    panel: Mapping[str, Any],
    nwm: Mapping[str, Any],
    travel: Mapping[str, Any],
    frozen_development_report: Mapping[str, Any],
    frozen_development_report_body: bytes,
    frozen_development_report_path: Path,
) -> None:
    protocol_artifact = _artifact(protocol_path, protocol_body)
    if (
        protocol.get("schema")
        != "gwm.geotransport.center_hill_temporal_holdout_protocol.v1"
        or protocol.get("status")
        != "frozen_before_evaluation_outcome_acquisition"
        or (protocol.get("metric_and_gate_lock") or {}).get(
            "score_once_without_post_label_operator_revision"
        )
        is not True
    ):
        raise ValueError("evaluation_frozen_protocol_invalid")
    if (
        panel.get("schema")
        != "gwm.geotransport.center_hill_temporal_holdout_panel.v1"
        or (panel.get("source_manifests") or {}).get("evaluation_protocol")
        != protocol_artifact
        or (panel.get("quality_summary") or {}).get(
            "operator_input_missing_value_count"
        )
        != 0
        or (panel.get("claim_boundary") or {}).get("evaluation_scored") is not False
    ):
        raise ValueError("evaluation_panel_contract_invalid")
    if (
        nwm.get("schema") != "gwm.geotransport.center_hill_evaluation_nwm.v1"
        or nwm.get("evaluation_protocol") != protocol_artifact
        or (nwm.get("claim_boundary") or {}).get("evaluation_scored") is not False
    ):
        raise ValueError("evaluation_nwm_contract_invalid")
    if (
        travel.get("schema")
        != "gwm.geotransport.center_hill_travel_time_prior.v1"
        or (travel.get("claim_boundary") or {}).get(
            "flood_wave_travel_time_admitted"
        )
        is not False
    ):
        raise ValueError("evaluation_travel_prior_contract_invalid")
    expected_development = (protocol.get("parent_development_evidence") or {}).get(
        "rollout_report"
    )
    if not isinstance(expected_development, Mapping):
        raise ValueError("evaluation_development_lineage_missing")
    if expected_development != _artifact(
        frozen_development_report_path, frozen_development_report_body
    ):
        raise ValueError("evaluation_development_lineage_mismatch")
    if (
        frozen_development_report.get("schema")
        != "gwm.geotransport.center_hill_672h_reach_transport_rollout.v1"
        or (frozen_development_report.get("checks") or {}).get(
            "outcome_values_scored"
        )
        is not False
    ):
        raise ValueError("evaluation_development_report_contract_invalid")


def _validate_panel_rows(rows: list[dict[str, str]]) -> None:
    if len(rows) != HOUR_COUNT:
        raise ValueError("evaluation_panel_requires_672_rows")
    if any(
        row["split_role"]
        != ("evaluation_warmup" if index < WARMUP_HOURS else "evaluation")
        for index, row in enumerate(rows)
    ):
        raise ValueError("evaluation_panel_split_mismatch")
    for row in rows:
        for field in (
            "action_release_m3s",
            "nwm_q_lateral_active_reach_sum_m3s",
            "nwm_velocity_proxy_residence_time_seconds",
        ):
            if row[field] == "":
                raise ValueError("evaluation_operator_input_missing")


def _reverse_active_path(
    forward: StateDependentReachTransportOperator,
) -> LinearReferencedPath:
    lengths = tuple(reversed(forward.effective_lengths_m))
    feature_ids = tuple(reversed(forward.active_feature_ids))
    return LinearReferencedPath(
        path_id=f"{forward.path.path_id}:negative-control-reversed-active-path",
        feature_ids=feature_ids,
        full_lengths_m=lengths,
        entry_offsets_m=(0.0,) * len(lengths),
        exit_offsets_m=lengths,
        provenance_id=f"negative-control:{forward.path.provenance_id}",
        evidence_level="candidate",
    )


def _conservation_summary(
    *,
    initial_storage: float,
    final_storage: float,
    input_volume: float,
    outlet_volume: float,
    residuals: list[float],
    numeric_tolerances: list[float],
) -> dict[str, Any]:
    horizon_residual = final_storage + outlet_volume - initial_storage - input_volume
    all_steps = all(
        abs(residual) <= tolerance
        for residual, tolerance in zip(residuals, numeric_tolerances, strict=True)
    )
    horizon_tolerance = float(sum(numeric_tolerances))
    passed = all_steps and abs(horizon_residual) <= horizon_tolerance
    return {
        "gate_status": "pass" if passed else "fail",
        "initial_storage_m3": initial_storage,
        "input_volume_m3": input_volume,
        "outlet_volume_m3": outlet_volume,
        "final_storage_m3": final_storage,
        "maximum_absolute_step_residual_m3": max(abs(value) for value in residuals),
        "horizon_residual_m3": horizon_residual,
        "cumulative_numeric_tolerance_m3": horizon_tolerance,
    }


def _metrics(observed_values: list[float], predicted_values: list[float]) -> dict[str, Any]:
    observed = np.asarray(observed_values, dtype=float)
    predicted = np.asarray(predicted_values, dtype=float)
    error = predicted - observed
    denominator = float(np.sum((observed - observed.mean()) ** 2))
    return {
        "sample_count": int(observed.size),
        "mae_m3s": float(np.mean(np.abs(error))),
        "rmse_m3s": float(np.sqrt(np.mean(error**2))),
        "bias_m3s": float(np.mean(error)),
        "nse": (
            None
            if denominator <= 0.0
            else 1.0 - float(np.sum(error**2)) / denominator
        ),
    }


def _optional_float(value: str) -> float | None:
    return None if value == "" else float(value)


def _finite_or_none(value: float) -> float | None:
    return float(value) if math.isfinite(value) else None


def _read_verified_artifact(descriptor: Mapping[str, Any]) -> bytes:
    path = (REPO_ROOT / str(descriptor.get("path"))).resolve()
    try:
        path.relative_to(REPO_ROOT)
    except ValueError as exc:
        raise ValueError("evaluation_artifact_outside_repository") from exc
    body = path.read_bytes()
    if (
        hashlib.sha256(body).hexdigest() != descriptor.get("sha256")
        or len(body) != descriptor.get("size_bytes")
    ):
        raise ValueError(f"evaluation_artifact_identity_mismatch:{path}")
    return body


def _artifact_from_descriptor(descriptor: Mapping[str, Any]) -> dict[str, Any]:
    body = _read_verified_artifact(descriptor)
    return {
        "path": str(descriptor["path"]),
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }


def _encode_csv(rows: list[dict[str, Any]]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=list(rows[0]), lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow(
            {
                key: (
                    ""
                    if value is None
                    else format(value, ".12g")
                    if isinstance(value, float)
                    else value
                )
                for key, value in row.items()
            }
        )
    return output.getvalue().encode("utf-8")


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


def main() -> int:
    args = parse_args()
    csv_body, report = compile_evaluation(
        protocol_path=args.protocol,
        panel_report_path=args.panel_report,
        nwm_manifest_path=args.nwm_manifest,
        travel_report_path=args.travel_report,
        development_rollout_report_path=args.development_rollout_report,
        output_path=args.output,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(csv_body)
    output_report = dict(report)
    output_report["generated_at"] = datetime.now(timezone.utc).isoformat()
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(output_report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(args.report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
