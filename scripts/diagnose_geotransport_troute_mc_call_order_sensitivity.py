#!/usr/bin/env python3
"""Test whether unrelated Manning work changes fixed t-route MC response output."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

from data_agent.uwm.geospatial_kernel_v2 import CtypesTrouteMuskingumCungeKernel

if __package__:
    from scripts import audit_geotransport_troute_mc_execution_semantics as semantics
    from scripts import build_geotransport_troute_mc_baseline as baseline
    from scripts import certify_geotransport_troute_mc_response_matrix as matrix
    from scripts import diagnose_geotransport_troute_mc_reach_response as reach
else:
    import audit_geotransport_troute_mc_execution_semantics as semantics
    import build_geotransport_troute_mc_baseline as baseline
    import certify_geotransport_troute_mc_response_matrix as matrix
    import diagnose_geotransport_troute_mc_reach_response as reach


REPO_ROOT = baseline.REPO_ROOT
DEFAULT_REPORT = (
    REPO_ROOT
    / "benchmarks/geotransport_v0_1/t_route_mc_call_order_sensitivity_report.json"
)
SCHEMA = "gwm.geotransport.t_route_mc_call_order_sensitivity.v1"
TIMESTEP_SECONDS = 300.0
BACKGROUND_FLOW_M3S = 2.0
PULSE_RATE_M3S = 10.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--route-link-manifest", type=Path, default=matrix.DEFAULT_ROUTE_LINK_MANIFEST
    )
    parser.add_argument("--source-manifest", type=Path, default=matrix.DEFAULT_SOURCE_MANIFEST)
    parser.add_argument("--build-manifest", type=Path, default=matrix.DEFAULT_BUILD_MANIFEST)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument(
        "--worker-trace",
        choices=("mc_only", "manning_interleaved"),
        help=argparse.SUPPRESS,
    )
    return parser.parse_args()


def compile_diagnostic(
    *,
    route_link_manifest_path: Path = matrix.DEFAULT_ROUTE_LINK_MANIFEST,
    source_manifest_path: Path = matrix.DEFAULT_SOURCE_MANIFEST,
    build_manifest_path: Path = matrix.DEFAULT_BUILD_MANIFEST,
) -> dict[str, Any]:
    route_body = route_link_manifest_path.read_bytes()
    source_body = source_manifest_path.read_bytes()
    build_body = build_manifest_path.read_bytes()
    route_manifest = json.loads(route_body)
    source_manifest = json.loads(source_body)
    build_manifest = json.loads(build_body)
    route_descriptor = baseline._validate_manifests(
        route_manifest, source_manifest, build_manifest
    )
    route_path, route_bytes = baseline._read_verified(route_descriptor)
    pure_trace = _isolated_trace(
        "mc_only",
        route_link_manifest_path=route_link_manifest_path,
        source_manifest_path=source_manifest_path,
        build_manifest_path=build_manifest_path,
    )
    interleaved_trace = _isolated_trace(
        "manning_interleaved",
        route_link_manifest_path=route_link_manifest_path,
        source_manifest_path=source_manifest_path,
        build_manifest_path=build_manifest_path,
    )
    pure_metrics = pure_trace["response"]
    interleaved_metrics = interleaved_trace["response"]
    metric_differences = {
        "net_outlet_volume_m3": (
            pure_metrics["net_outlet_volume_m3"]
            - interleaved_metrics["net_outlet_volume_m3"]
        ),
        "negative_outlet_volume_m3": (
            pure_metrics["negative_outlet_volume_m3"]
            - interleaved_metrics["negative_outlet_volume_m3"]
        ),
        "minimum_response_m3s": (
            pure_metrics["minimum_response_m3s"]
            - interleaved_metrics["minimum_response_m3s"]
        ),
        "t05_seconds": (
            pure_metrics["input_recovery_quantile_seconds"]["t05"]
            - interleaved_metrics["input_recovery_quantile_seconds"]["t05"]
        ),
        "t50_seconds": (
            pure_metrics["input_recovery_quantile_seconds"]["t50"]
            - interleaved_metrics["input_recovery_quantile_seconds"]["t50"]
        ),
        "t95_seconds": (
            pure_metrics["input_recovery_quantile_seconds"]["t95"]
            - interleaved_metrics["input_recovery_quantile_seconds"]["t95"]
        ),
    }
    invariance_tolerance = 1e-9
    invariant = all(abs(value) <= invariance_tolerance for value in metric_differences.values())
    kernel_source = (
        REPO_ROOT
        / "data/geotransport_v0_1/t_route_mc_source_audit/raw/"
        "MCsingleSegStime_f2py_NOLOOP.f90"
    )
    kernel_source_body = kernel_source.read_bytes()
    return {
        "schema": SCHEMA,
        "status": (
            "fixed_commit_cold_process_trace_invariance_passed"
            if invariant
            else "fixed_commit_cold_process_trace_sensitivity_detected"
        ),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_artifacts": {
            "route_link_manifest": _artifact(route_link_manifest_path, route_body),
            "route_link_fixture": _artifact(route_path, route_bytes),
            "t_route_source_manifest": _artifact(source_manifest_path, source_body),
            "t_route_build_manifest": _artifact(build_manifest_path, build_body),
            "fortran_kernel_source": _artifact(kernel_source, kernel_source_body),
            "t_route_shared_library": build_manifest["library_artifact"],
        },
        "protocol": {
            "timestep_seconds": TIMESTEP_SECONDS,
            "background_flow_m3s": BACKGROUND_FLOW_M3S,
            "pulse_rate_m3s": PULSE_RATE_M3S,
            "pulse_duration_seconds": matrix.PULSE_DURATION_SECONDS,
            "warmup_hours": matrix.WARMUP_HOURS,
            "rollout_hours": matrix.ROLLOUT_HOURS,
            "assume_short_timestep": False,
            "trace_a": "MC calls only",
            "trace_b": (
                "identical MC calls with an independent conservative Manning "
                "operator advanced after each MC base/pulse step"
            ),
            "trace_process_isolation": True,
            "pulse_scenario_order": list(matrix.PULSE_RATES_M3S),
            "reported_pulse_rate_m3s": PULSE_RATE_M3S,
            "shared_state_between_operators": False,
            "invariance_absolute_tolerance": invariance_tolerance,
        },
        "warmup": {
            "mc_only": pure_trace["warmup"],
            "manning_interleaved": interleaved_trace["warmup"],
        },
        "responses": {
            "mc_only": pure_metrics,
            "manning_interleaved": interleaved_metrics,
        },
        "metric_differences_mc_only_minus_interleaved": metric_differences,
        "call_order_invariance": {
            "passed": invariant,
            "expected_for_stateless_segment_kernel": True,
            "cold_process_execution_trace_changes_mc_result": not invariant,
        },
        "static_source_evidence": {
            "qdc_intent_out_read_before_assignment": semantics._finding(
                "qdc_intent_out_read_before_assignment",
                (kernel_source, kernel_source_body.decode("utf-8")),
                [
                    "real(prec), intent(out) :: qdc, velc, depthc",
                    ".or. qdp .gt. 0.0_prec .or. qdc .gt. 0.0_prec",
                ],
                conclusion="qdc is read in a guard before assignment.",
            ),
            "secant_outputs_read_before_assignment": semantics._finding(
                "secant_outputs_read_before_assignment",
                (kernel_source, kernel_source_body.decode("utf-8")),
                [
                    "real(prec), intent(out) :: Qj, C1, C2, C3, C4, X",
                    "1.0_prec-(Qj/(2.0_prec*twl*s0*Ck*dx))",
                    "C1 =  (Km*X + dt/2.0_prec)/D",
                    "Qj =  ((C1*qup)+(C2*quc)+(C3*qdp) + C4)",
                ],
                conclusion=(
                    "Qj or C1..C4 feed X before those intent(out) values are assigned."
                ),
            ),
        },
        "data_isolation": {
            "observed_discharge_loaded": False,
            "observed_forcing_loaded": False,
            "outcome_values_loaded": False,
            "synthetic_boundary_only": True,
        },
        "claim_boundary": {
            "call_order_invariance_passed": invariant,
            "undefined_initialization_path_found": True,
            "all_negative_lobes_explained_by_initialization_defect": False,
            "generic_muskingum_cunge_method_rejected": False,
            "fixed_commit_kernel_promotion_gate_passed": False,
            "professional_transfer_operator_certified": False,
            "geospatial_kernel_validated": False,
        },
    }


def _isolated_trace(
    trace: str,
    *,
    route_link_manifest_path: Path,
    source_manifest_path: Path,
    build_manifest_path: Path,
) -> dict[str, Any]:
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--worker-trace",
        trace,
        "--route-link-manifest",
        str(route_link_manifest_path.resolve()),
        "--source-manifest",
        str(source_manifest_path.resolve()),
        "--build-manifest",
        str(build_manifest_path.resolve()),
    ]
    completed = subprocess.run(command, check=True, capture_output=True, text=True)
    return json.loads(completed.stdout)


def _compile_worker_trace(
    trace: str,
    *,
    route_link_manifest_path: Path,
    source_manifest_path: Path,
    build_manifest_path: Path,
) -> dict[str, Any]:
    route_manifest = json.loads(route_link_manifest_path.read_bytes())
    source_manifest = json.loads(source_manifest_path.read_bytes())
    build_manifest = json.loads(build_manifest_path.read_bytes())
    descriptor = baseline._validate_manifests(
        route_manifest, source_manifest, build_manifest
    )
    route_path, _ = baseline._read_verified(descriptor)
    by_feature = baseline._route_link_rows(route_path)
    rows = [by_feature[feature_id] for feature_id in baseline.FEATURE_PATH]
    kernel = CtypesTrouteMuskingumCungeKernel(build_manifest_path)

    if trace == "mc_only":
        adapter, state, warmup = reach._warm_adapter(
            rows,
            kernel,
            timestep_seconds=TIMESTEP_SECONDS,
            background_flow_m3s=BACKGROUND_FLOW_M3S,
            assume_short_timestep=False,
        )
        selected = None
        for pulse_rate in matrix.PULSE_RATES_M3S:
            case = reach._run_case(
                rows,
                adapter,
                state,
                timestep_seconds=TIMESTEP_SECONDS,
                background_flow_m3s=BACKGROUND_FLOW_M3S,
                pulse_rate_m3s=pulse_rate,
            )
            if pulse_rate == PULSE_RATE_M3S:
                selected = case["outlet_response"]
    else:
        context, warmup = matrix._warm_operators(
            rows,
            kernel,
            timestep_seconds=TIMESTEP_SECONDS,
            background_flow_m3s=BACKGROUND_FLOW_M3S,
        )
        selected = None
        for pulse_rate in matrix.PULSE_RATES_M3S:
            case = matrix._run_response_case(
                rows,
                context,
                timestep_seconds=TIMESTEP_SECONDS,
                background_flow_m3s=BACKGROUND_FLOW_M3S,
                pulse_rate_m3s=pulse_rate,
            )
            if pulse_rate == PULSE_RATE_M3S:
                selected = case["t_route_mc"]
    if selected is None:
        raise RuntimeError("t_route_mc_call_order_worker_case_missing")
    return {"trace": trace, "warmup": warmup, "response": selected}


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
    if args.worker_trace:
        print(
            json.dumps(
                _compile_worker_trace(
                    args.worker_trace,
                    route_link_manifest_path=args.route_link_manifest,
                    source_manifest_path=args.source_manifest,
                    build_manifest_path=args.build_manifest,
                ),
                sort_keys=True,
            )
        )
        return 0
    if args.report.exists():
        raise ValueError("t_route_mc_call_order_sensitivity_refuses_overwrite")
    report = compile_diagnostic(
        route_link_manifest_path=args.route_link_manifest,
        source_manifest_path=args.source_manifest,
        build_manifest_path=args.build_manifest,
    )
    body = (
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_bytes(body)
    print(args.report)
    print(hashlib.sha256(body).hexdigest())
    print(f"call_order_invariance_passed={report['call_order_invariance']['passed']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
