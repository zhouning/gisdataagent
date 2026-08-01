#!/usr/bin/env python3
"""Localize t-route MC transfer-response negative lobes by reach and mode."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np

from data_agent.uwm.geospatial_kernel_v2 import (
    CtypesTrouteMuskingumCungeKernel,
    TrouteMuskingumCungeAdapter,
    analyze_dynamic_transfer_response,
)

if __package__:
    from scripts import build_geotransport_troute_mc_baseline as baseline
    from scripts import certify_geotransport_troute_mc_response_matrix as matrix
else:
    import build_geotransport_troute_mc_baseline as baseline
    import certify_geotransport_troute_mc_response_matrix as matrix


REPO_ROOT = baseline.REPO_ROOT
DEFAULT_REPORT = (
    REPO_ROOT
    / "benchmarks/geotransport_v0_1/t_route_mc_reach_response_diagnostic.json"
)
SCHEMA = "gwm.geotransport.t_route_mc_reach_response_diagnostic.v1"
MODES = (False, True)
RESPONSE_THRESHOLD_M3S = 1e-6
NEGATIVE_ABSOLUTE_TOLERANCE_M3 = 1e-5
NEGATIVE_RELATIVE_TOLERANCE = 1e-9


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--route-link-manifest", type=Path, default=matrix.DEFAULT_ROUTE_LINK_MANIFEST
    )
    parser.add_argument("--source-manifest", type=Path, default=matrix.DEFAULT_SOURCE_MANIFEST)
    parser.add_argument("--build-manifest", type=Path, default=matrix.DEFAULT_BUILD_MANIFEST)
    parser.add_argument("--semantics-report", type=Path, default=(
        REPO_ROOT
        / "benchmarks/geotransport_v0_1/t_route_mc_execution_semantics_report.json"
    ))
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def compile_diagnostic(
    *,
    route_link_manifest_path: Path = matrix.DEFAULT_ROUTE_LINK_MANIFEST,
    source_manifest_path: Path = matrix.DEFAULT_SOURCE_MANIFEST,
    build_manifest_path: Path = matrix.DEFAULT_BUILD_MANIFEST,
    semantics_report_path: Path,
) -> dict[str, Any]:
    route_body = route_link_manifest_path.read_bytes()
    source_body = source_manifest_path.read_bytes()
    build_body = build_manifest_path.read_bytes()
    semantics_body = semantics_report_path.read_bytes()
    route_manifest = json.loads(route_body)
    source_manifest = json.loads(source_body)
    build_manifest = json.loads(build_body)
    semantics = json.loads(semantics_body)
    if (
        semantics.get("schema")
        != "gwm.geotransport.t_route_mc_execution_semantics.v1"
        or semantics.get("claim_boundary", {}).get(
            "adapter_default_chain_semantics_match"
        )
        is not True
    ):
        raise ValueError("t_route_mc_reach_response_semantics_audit_invalid")

    route_descriptor = baseline._validate_manifests(
        route_manifest, source_manifest, build_manifest
    )
    route_path, route_bytes = baseline._read_verified(route_descriptor)
    by_feature = baseline._route_link_rows(route_path)
    rows = [by_feature[feature_id] for feature_id in baseline.FEATURE_PATH]
    for upstream, downstream in zip(rows[:-1], rows[1:], strict=True):
        if int(upstream["to"]) != int(downstream["link"]):
            raise ValueError("t_route_mc_reach_response_topology_mismatch")

    kernel = CtypesTrouteMuskingumCungeKernel(build_manifest_path)
    cases: list[dict[str, Any]] = []
    warmups: list[dict[str, Any]] = []
    for assume_short_timestep in MODES:
        for timestep in matrix.TIMESTEPS_SECONDS:
            for background in matrix.BACKGROUND_FLOWS_M3S:
                adapter, warmed_state, warmup = _warm_adapter(
                    rows,
                    kernel,
                    timestep_seconds=timestep,
                    background_flow_m3s=background,
                    assume_short_timestep=assume_short_timestep,
                )
                warmups.append(warmup)
                for pulse in matrix.PULSE_RATES_M3S:
                    cases.append(
                        _run_case(
                            rows,
                            adapter,
                            warmed_state,
                            timestep_seconds=timestep,
                            background_flow_m3s=background,
                            pulse_rate_m3s=pulse,
                        )
                    )

    mode_summaries = {
        _mode_name(mode): _summarize_mode(cases, mode) for mode in MODES
    }
    return {
        "schema": SCHEMA,
        "status": "outcome_free_reach_response_localization_complete",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_artifacts": {
            "route_link_manifest": _artifact(route_link_manifest_path, route_body),
            "route_link_fixture": _artifact(route_path, route_bytes),
            "t_route_source_manifest": _artifact(source_manifest_path, source_body),
            "t_route_build_manifest": _artifact(build_manifest_path, build_body),
            "execution_semantics_report": _artifact(
                semantics_report_path, semantics_body
            ),
            "t_route_shared_library": build_manifest["library_artifact"],
        },
        "runtime_identity": semantics["runtime_identity"],
        "fixture": {
            "source_id": baseline.SOURCE_ID,
            "feature_ids": list(baseline.FEATURE_PATH),
            "feature_count": len(rows),
            "full_reaches_only": True,
            "observed_outcomes_used": False,
        },
        "protocol": {
            "assume_short_timestep_modes": list(MODES),
            "official_default_assume_short_timestep": False,
            "background_flows_m3s": list(matrix.BACKGROUND_FLOWS_M3S),
            "pulse_rates_m3s": list(matrix.PULSE_RATES_M3S),
            "pulse_duration_seconds": matrix.PULSE_DURATION_SECONDS,
            "timesteps_seconds": list(matrix.TIMESTEPS_SECONDS),
            "warmup_hours": matrix.WARMUP_HOURS,
            "rollout_hours": matrix.ROLLOUT_HOURS,
            "case_count": len(cases),
            "response_threshold_m3s": RESPONSE_THRESHOLD_M3S,
            "negative_lobe_absolute_tolerance_m3": (
                NEGATIVE_ABSOLUTE_TOLERANCE_M3
            ),
            "negative_lobe_relative_tolerance": NEGATIVE_RELATIVE_TOLERANCE,
            "branch_initialization": (
                "base and pulse branches fork from the same mode-specific warmed state"
            ),
        },
        "warmup_states": warmups,
        "cases": cases,
        "mode_summaries": mode_summaries,
        "mode_comparison": {
            "official_default_mode": "default_current_upstream",
            "short_timestep_mode_is_posthoc_diagnostic": True,
            "short_timestep_mode_pre_registered_for_promotion": False,
            "promotion_may_follow_relative_mode_performance": False,
            "default_outlet_negative_case_count": mode_summaries[
                "default_current_upstream"
            ]["outlet_negative_lobe_case_count"],
            "short_ts_outlet_negative_case_count": mode_summaries[
                "short_previous_upstream"
            ]["outlet_negative_lobe_case_count"],
        },
        "data_isolation": {
            "observed_discharge_loaded": False,
            "observed_action_loaded": False,
            "observed_forcing_loaded": False,
            "target_fitted_parameters": 0,
            "inputs": [
                "official_route_link_parameters",
                "synthetic_constant_background_flow",
                "synthetic_boundary_pulse",
            ],
        },
        "scientific_limitations": {
            "float32_ulp_diagnostic_establishes_causation": False,
            "official_mc_internal_storage_exposed": False,
            "per_reach_mass_conservation_claimed": False,
            "full_t_route_application_reproduced": False,
            "real_world_transfer_validated": False,
        },
        "claim_boundary": {
            "negative_response_localized_by_reach": True,
            "official_default_mode_retested": True,
            "short_timestep_diagnostic_executed": True,
            "short_timestep_mode_promoted": False,
            "professional_transfer_operator_certified": False,
            "geospatial_kernel_validated": False,
        },
    }


def _warm_adapter(
    rows: list[dict[str, float | int]],
    kernel: CtypesTrouteMuskingumCungeKernel,
    *,
    timestep_seconds: float,
    background_flow_m3s: float,
    assume_short_timestep: bool,
) -> tuple[TrouteMuskingumCungeAdapter, Any, dict[str, Any]]:
    adapter = TrouteMuskingumCungeAdapter(
        baseline._mc_parameters(rows, reverse=False),
        kernel,
        timestep_seconds=timestep_seconds,
        assume_short_timestep=assume_short_timestep,
    )
    state = adapter.zero_state(provenance_id="reach-response:warmup-zero")
    steps = int(matrix.WARMUP_HOURS * 3600.0 / timestep_seconds)
    for step in range(steps):
        state = adapter.step(
            state,
            boundary_previous_m3s=background_flow_m3s,
            boundary_current_m3s=background_flow_m3s,
            provenance_id=f"reach-response:warmup:{step + 1}",
        ).next_state
    values = np.asarray(
        [state.discharge_m3s, state.velocity_mps, state.depth_m], dtype=float
    )
    return adapter, state, {
        "mode": _mode_name(assume_short_timestep),
        "assume_short_timestep": assume_short_timestep,
        "timestep_seconds": timestep_seconds,
        "background_flow_m3s": background_flow_m3s,
        "warmup_step_count": steps,
        "outlet_flow_m3s": state.discharge_m3s[-1],
        "outlet_relative_steady_error": abs(
            state.discharge_m3s[-1] - background_flow_m3s
        )
        / background_flow_m3s,
        "states_nonnegative_finite": bool(
            np.isfinite(values).all() and (values >= 0.0).all()
        ),
    }


def _run_case(
    rows: list[dict[str, float | int]],
    adapter: TrouteMuskingumCungeAdapter,
    warmed_state: Any,
    *,
    timestep_seconds: float,
    background_flow_m3s: float,
    pulse_rate_m3s: float,
) -> dict[str, Any]:
    base_state = warmed_state
    pulse_state = warmed_state
    response_by_reach: list[list[float]] = [[] for _ in rows]
    input_volume = 0.0
    steps = int(matrix.ROLLOUT_HOURS * 3600.0 / timestep_seconds)
    for step in range(steps):
        previous_seconds = step * timestep_seconds
        current_seconds = (step + 1) * timestep_seconds
        previous_pulse = matrix._pulse_component(previous_seconds, pulse_rate_m3s)
        current_pulse = matrix._pulse_component(current_seconds, pulse_rate_m3s)
        effective_mean_pulse = (
            previous_pulse
            if adapter.assume_short_timestep
            else 0.5 * (previous_pulse + current_pulse)
        )
        input_volume += effective_mean_pulse * timestep_seconds

        base_result = adapter.step(
            base_state,
            boundary_previous_m3s=background_flow_m3s,
            boundary_current_m3s=background_flow_m3s,
            provenance_id=f"reach-response:base:{step + 1}",
        )
        pulse_result = adapter.step(
            pulse_state,
            boundary_previous_m3s=background_flow_m3s + previous_pulse,
            boundary_current_m3s=background_flow_m3s + current_pulse,
            provenance_id=f"reach-response:pulse:{step + 1}",
        )
        for index in range(len(rows)):
            base_mean = 0.5 * (
                base_state.discharge_m3s[index]
                + base_result.next_state.discharge_m3s[index]
            )
            pulse_mean = 0.5 * (
                pulse_state.discharge_m3s[index]
                + pulse_result.next_state.discharge_m3s[index]
            )
            response_by_reach[index].append(pulse_mean - base_mean)
        base_state = base_result.next_state
        pulse_state = pulse_result.next_state

    expected_volume = pulse_rate_m3s * matrix.PULSE_DURATION_SECONDS
    if not np.isclose(input_volume, expected_volume, rtol=0.0, atol=1e-9):
        raise RuntimeError("t_route_mc_reach_response_pulse_volume_invalid")
    storage_difference = baseline._official_physical_storage(
        pulse_state.depth_m, rows
    ) - baseline._official_physical_storage(base_state.depth_m, rows)
    outlet_metrics = analyze_dynamic_transfer_response(
        response_by_reach[-1],
        timestep_seconds=timestep_seconds,
        input_volume_m3=input_volume,
        final_incremental_storage_m3=storage_difference,
    ).as_dict()
    reach_summaries = [
        _summarize_reach_response(
            response,
            feature_id=int(rows[index]["link"]),
            reach_index=index,
            warmed_flow_m3s=float(warmed_state.discharge_m3s[index]),
            timestep_seconds=timestep_seconds,
            input_volume_m3=input_volume,
        )
        for index, response in enumerate(response_by_reach)
    ]
    first_any = next(
        (
            item
            for item in reach_summaries
            if item["negative_sample_below_threshold_count"] > 0
        ),
        None,
    )
    first_volume = next(
        (item for item in reach_summaries if item["negative_lobe_above_tolerance"]),
        None,
    )
    return {
        "case_id": (
            f"{_mode_name(adapter.assume_short_timestep)}:q{background_flow_m3s:g}:"
            f"pulse{pulse_rate_m3s:g}:dt{timestep_seconds:g}"
        ),
        "mode": _mode_name(adapter.assume_short_timestep),
        "assume_short_timestep": adapter.assume_short_timestep,
        "background_flow_m3s": background_flow_m3s,
        "pulse_rate_m3s": pulse_rate_m3s,
        "pulse_input_volume_m3": input_volume,
        "timestep_seconds": timestep_seconds,
        "outlet_response": outlet_metrics,
        "reaches": reach_summaries,
        "first_reach_with_negative_sample_below_threshold": (
            None if first_any is None else _reach_identity(first_any)
        ),
        "first_reach_with_negative_lobe_above_tolerance": (
            None if first_volume is None else _reach_identity(first_volume)
        ),
        "all_negative_reaches_are_sub_float32_ulp": all(
            item["minimum_response_m3s"] >= 0.0
            or item["absolute_minimum_response_to_reference_float32_ulp"] <= 1.0
            for item in reach_summaries
        ),
    }


def _summarize_reach_response(
    response: list[float] | np.ndarray,
    *,
    feature_id: int,
    reach_index: int,
    warmed_flow_m3s: float,
    timestep_seconds: float,
    input_volume_m3: float,
) -> dict[str, Any]:
    values = np.asarray(response, dtype=float)
    if values.ndim != 1 or values.size == 0 or not np.isfinite(values).all():
        raise ValueError("t_route_mc_reach_response_vector_invalid")
    negative = np.maximum(-values, 0.0)
    positive = np.maximum(values, 0.0)
    below = np.flatnonzero(values < -RESPONSE_THRESHOLD_M3S)
    negative_volume = float(negative.sum() * timestep_seconds)
    tolerance = (
        NEGATIVE_ABSOLUTE_TOLERANCE_M3
        + NEGATIVE_RELATIVE_TOLERANCE * input_volume_m3
    )
    reference = np.float32(max(warmed_flow_m3s, np.finfo(np.float32).tiny))
    reference_ulp = float(np.spacing(reference))
    minimum = float(values.min())
    return {
        "feature_id": feature_id,
        "reach_index": reach_index,
        "warmed_flow_m3s": warmed_flow_m3s,
        "reference_float32_ulp_m3s": reference_ulp,
        "minimum_response_m3s": minimum,
        "absolute_minimum_response_to_reference_float32_ulp": (
            abs(minimum) / reference_ulp
        ),
        "peak_positive_response_m3s": float(positive.max()),
        "positive_response_volume_m3": float(positive.sum() * timestep_seconds),
        "negative_response_volume_m3": negative_volume,
        "negative_lobe_tolerance_m3": tolerance,
        "negative_lobe_above_tolerance": negative_volume > tolerance,
        "negative_sample_below_threshold_count": int(below.size),
        "first_negative_sample_interval_end_seconds": (
            None if below.size == 0 else float((int(below[0]) + 1) * timestep_seconds)
        ),
    }


def _summarize_mode(cases: list[dict[str, Any]], mode: bool) -> dict[str, Any]:
    selected = [item for item in cases if item["assume_short_timestep"] is mode]
    first_reach_counts: dict[str, int] = {}
    for case in selected:
        first = case["first_reach_with_negative_lobe_above_tolerance"]
        key = "none" if first is None else str(first["feature_id"])
        first_reach_counts[key] = first_reach_counts.get(key, 0) + 1
    stability = _mode_timestep_stability(selected)
    return {
        "mode": _mode_name(mode),
        "case_count": len(selected),
        "outlet_negative_lobe_case_count": sum(
            not item["outlet_response"]["negative_lobe_within_tolerance"]
            for item in selected
        ),
        "any_reach_negative_lobe_case_count": sum(
            item["first_reach_with_negative_lobe_above_tolerance"] is not None
            for item in selected
        ),
        "all_negative_reaches_sub_float32_ulp_case_count": sum(
            item["all_negative_reaches_are_sub_float32_ulp"] for item in selected
        ),
        "first_negative_lobe_feature_counts": dict(sorted(first_reach_counts.items())),
        "timestep_stability": stability,
    }


def _mode_timestep_stability(cases: list[dict[str, Any]]) -> dict[str, Any]:
    comparisons = []
    for background in matrix.BACKGROUND_FLOWS_M3S:
        for pulse in matrix.PULSE_RATES_M3S:
            group = {
                float(item["timestep_seconds"]): item["outlet_response"]
                for item in cases
                if item["background_flow_m3s"] == background
                and item["pulse_rate_m3s"] == pulse
            }
            reference = group[matrix.TIMESTEPS_SECONDS[0]][
                "input_recovery_quantile_seconds"
            ]
            for timestep in matrix.TIMESTEPS_SECONDS[1:]:
                candidate = group[timestep]["input_recovery_quantile_seconds"]
                for quantile in ("t05", "t50", "t95"):
                    reference_time = reference[quantile]
                    candidate_time = candidate[quantile]
                    tolerance = (
                        None
                        if reference_time is None
                        else max(
                            matrix.STABILITY_ABSOLUTE_TOLERANCE_SECONDS,
                            matrix.STABILITY_RELATIVE_TOLERANCE * reference_time,
                        )
                    )
                    difference = (
                        None
                        if reference_time is None or candidate_time is None
                        else abs(candidate_time - reference_time)
                    )
                    comparisons.append(
                        {
                            "background_flow_m3s": background,
                            "pulse_rate_m3s": pulse,
                            "candidate_timestep_seconds": timestep,
                            "quantile": quantile,
                            "absolute_difference_seconds": difference,
                            "tolerance_seconds": tolerance,
                            "passed": (
                                difference is not None
                                and tolerance is not None
                                and difference <= tolerance
                            ),
                        }
                    )
    return {
        "comparison_count": len(comparisons),
        "passed_count": sum(item["passed"] for item in comparisons),
        "all_comparisons_passed": all(item["passed"] for item in comparisons),
        "comparisons": comparisons,
    }


def _reach_identity(summary: dict[str, Any]) -> dict[str, int]:
    return {
        "feature_id": int(summary["feature_id"]),
        "reach_index": int(summary["reach_index"]),
    }


def _mode_name(assume_short_timestep: bool) -> str:
    return (
        "short_previous_upstream"
        if assume_short_timestep
        else "default_current_upstream"
    )


def _artifact(path: Path, body: bytes) -> dict[str, Any]:
    resolved = path.resolve()
    try:
        display = resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        display = resolved.as_posix()
    return {
        "path": display,
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }


def main() -> int:
    args = parse_args()
    if args.report.exists():
        raise ValueError("t_route_mc_reach_response_refuses_overwrite")
    report = compile_diagnostic(
        route_link_manifest_path=args.route_link_manifest,
        source_manifest_path=args.source_manifest,
        build_manifest_path=args.build_manifest,
        semantics_report_path=args.semantics_report,
    )
    body = (
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_bytes(body)
    print(args.report)
    print(hashlib.sha256(body).hexdigest())
    for name, summary in report["mode_summaries"].items():
        print(
            f"{name}: outlet_negative={summary['outlet_negative_lobe_case_count']}/"
            f"{summary['case_count']}, timestep_passed="
            f"{summary['timestep_stability']['passed_count']}/"
            f"{summary['timestep_stability']['comparison_count']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
