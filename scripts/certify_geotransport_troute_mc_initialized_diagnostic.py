#!/usr/bin/env python3
"""Certify the explicitly initialized derived t-route MC diagnostic runtime."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

from data_agent.uwm.geospatial_kernel_v2 import (
    CtypesInitializedDiagnosticTrouteMuskingumCungeKernel,
)

if __package__:
    from scripts import build_geotransport_troute_mc_baseline as baseline
    from scripts import certify_geotransport_troute_mc_response_matrix as matrix
    from scripts import diagnose_geotransport_troute_mc_reach_response as reach
else:
    import build_geotransport_troute_mc_baseline as baseline
    import certify_geotransport_troute_mc_response_matrix as matrix
    import diagnose_geotransport_troute_mc_reach_response as reach


REPO_ROOT = baseline.REPO_ROOT
DEFAULT_BUILD_MANIFEST = (
    REPO_ROOT
    / "data/geotransport_v0_1/t_route_mc_initialized_diagnostic_runtime/"
    "build_manifest.json"
)
DEFAULT_REPORT = (
    REPO_ROOT
    / "benchmarks/geotransport_v0_1/"
    "t_route_mc_initialized_diagnostic_response_matrix.json"
)
SCHEMA = "gwm.geotransport.t_route_mc_initialized_diagnostic_matrix.v1"
BUILD_SCHEMA = "gwm.geotransport.t_route_mc_initialized_diagnostic_runtime.v1"
TRACE_TIMESTEP_SECONDS = 300.0
TRACE_BACKGROUND_FLOW_M3S = 2.0
TRACE_PULSE_RATE_M3S = 10.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--route-link-manifest", type=Path, default=matrix.DEFAULT_ROUTE_LINK_MANIFEST
    )
    parser.add_argument("--source-manifest", type=Path, default=matrix.DEFAULT_SOURCE_MANIFEST)
    parser.add_argument("--build-manifest", type=Path, default=DEFAULT_BUILD_MANIFEST)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument(
        "--worker-trace",
        choices=("mc_only", "manning_interleaved"),
        help=argparse.SUPPRESS,
    )
    return parser.parse_args()


def compile_certification(
    *,
    route_link_manifest_path: Path = matrix.DEFAULT_ROUTE_LINK_MANIFEST,
    source_manifest_path: Path = matrix.DEFAULT_SOURCE_MANIFEST,
    build_manifest_path: Path = DEFAULT_BUILD_MANIFEST,
) -> dict[str, Any]:
    rows, artifacts = _load_inputs(
        route_link_manifest_path=route_link_manifest_path,
        source_manifest_path=source_manifest_path,
        build_manifest_path=build_manifest_path,
    )
    kernel = CtypesInitializedDiagnosticTrouteMuskingumCungeKernel(
        build_manifest_path
    )
    cases: list[dict[str, Any]] = []
    warmups: list[dict[str, Any]] = []
    for timestep in matrix.TIMESTEPS_SECONDS:
        for background in matrix.BACKGROUND_FLOWS_M3S:
            adapter, state, warmup = reach._warm_adapter(
                rows,
                kernel,
                timestep_seconds=timestep,
                background_flow_m3s=background,
                assume_short_timestep=False,
            )
            warmups.append(warmup)
            for pulse in matrix.PULSE_RATES_M3S:
                cases.append(
                    reach._run_case(
                        rows,
                        adapter,
                        state,
                        timestep_seconds=timestep,
                        background_flow_m3s=background,
                        pulse_rate_m3s=pulse,
                    )
                )
    summary = reach._summarize_mode(cases, False)
    trace_a = _isolated_trace(
        "mc_only",
        route_link_manifest_path=route_link_manifest_path,
        source_manifest_path=source_manifest_path,
        build_manifest_path=build_manifest_path,
    )
    trace_b = _isolated_trace(
        "manning_interleaved",
        route_link_manifest_path=route_link_manifest_path,
        source_manifest_path=source_manifest_path,
        build_manifest_path=build_manifest_path,
    )
    trace_differences = _metric_differences(
        trace_a["response"], trace_b["response"]
    )
    trace_tolerance = 1e-9
    trace_invariant = all(
        value is not None and abs(value) <= trace_tolerance
        for value in trace_differences.values()
    )
    gates = {
        "all_warmup_states_nonnegative_finite": all(
            item["states_nonnegative_finite"] for item in warmups
        ),
        "all_outlet_negative_lobes_within_tolerance": all(
            item["outlet_response"]["negative_lobe_within_tolerance"]
            for item in cases
        ),
        "timestep_stability": summary["timestep_stability"][
            "all_comparisons_passed"
        ],
        "cold_process_trace_invariance": trace_invariant,
        "outcome_isolation": True,
    }
    gates["all_diagnostic_gates_passed"] = all(gates.values())
    return {
        "schema": SCHEMA,
        "status": "derived_initialized_runtime_diagnostic_complete",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_artifacts": artifacts,
        "runtime_identity": {
            "source_commit": json.loads(
                build_manifest_path.read_bytes()
            )["source_commit"],
            "patch_id": json.loads(build_manifest_path.read_bytes())["patch_id"],
            "official_source_unmodified": False,
            "derived_diagnostic_only": True,
        },
        "protocol": {
            "background_flows_m3s": list(matrix.BACKGROUND_FLOWS_M3S),
            "pulse_rates_m3s": list(matrix.PULSE_RATES_M3S),
            "pulse_duration_seconds": matrix.PULSE_DURATION_SECONDS,
            "timesteps_seconds": list(matrix.TIMESTEPS_SECONDS),
            "warmup_hours": matrix.WARMUP_HOURS,
            "rollout_hours": matrix.ROLLOUT_HOURS,
            "case_count": len(cases),
            "assume_short_timestep": False,
        },
        "warmup_states": warmups,
        "cases": cases,
        "matrix_summary": summary,
        "cold_process_trace_invariance": {
            "trace_a": "MC calls only",
            "trace_b": "same MC calls with independent Manning work interleaved",
            "shared_operator_state": False,
            "absolute_tolerance": trace_tolerance,
            "metric_differences_mc_only_minus_interleaved": trace_differences,
            "passed": trace_invariant,
            "mc_only_warmup": trace_a["warmup"],
            "manning_interleaved_warmup": trace_b["warmup"],
        },
        "gates": gates,
        "data_isolation": {
            "observed_discharge_loaded": False,
            "observed_action_loaded": False,
            "observed_forcing_loaded": False,
            "target_fitted_parameters": 0,
            "synthetic_boundary_only": True,
        },
        "scientific_limitations": {
            "derived_runtime_is_official": False,
            "initialization_patch_is_upstream_admitted": False,
            "official_mc_internal_storage_exposed": False,
            "real_world_transfer_validated": False,
        },
        "claim_boundary": {
            "initialization_defect_removed_for_diagnostic": True,
            "derived_matrix_executed": True,
            "official_runtime_replaced": False,
            "professional_baseline_eligible": False,
            "professional_transfer_operator_certified": False,
            "geospatial_kernel_validated": False,
        },
    }


def _load_inputs(
    *,
    route_link_manifest_path: Path,
    source_manifest_path: Path,
    build_manifest_path: Path,
) -> tuple[list[dict[str, float | int]], dict[str, Any]]:
    route_body = route_link_manifest_path.read_bytes()
    source_body = source_manifest_path.read_bytes()
    build_body = build_manifest_path.read_bytes()
    route_manifest = json.loads(route_body)
    source_manifest = json.loads(source_body)
    build_manifest = json.loads(build_body)
    if (
        build_manifest.get("schema") != BUILD_SCHEMA
        or build_manifest.get("official_source_unmodified") is not False
        or build_manifest.get("derived_diagnostic_only") is not True
    ):
        raise ValueError("t_route_mc_initialized_matrix_build_manifest_invalid")
    route_descriptor = baseline._validate_manifests(
        route_manifest,
        source_manifest,
        {
            "schema": baseline.BUILD_SCHEMA,
            "source_commit": build_manifest["source_commit"],
            "official_source_unmodified": True,
        },
    )
    route_path, route_bytes = baseline._read_verified(route_descriptor)
    by_feature = baseline._route_link_rows(route_path)
    rows = [by_feature[feature_id] for feature_id in baseline.FEATURE_PATH]
    for upstream, downstream in zip(rows[:-1], rows[1:], strict=True):
        if int(upstream["to"]) != int(downstream["link"]):
            raise ValueError("t_route_mc_initialized_matrix_topology_mismatch")
    return rows, {
        "route_link_manifest": _artifact(route_link_manifest_path, route_body),
        "route_link_fixture": _artifact(route_path, route_bytes),
        "t_route_source_manifest": _artifact(source_manifest_path, source_body),
        "derived_build_manifest": _artifact(build_manifest_path, build_body),
        "derived_core_source": build_manifest["derived_core_source"],
        "source_patch": build_manifest["source_patch"],
        "derived_shared_library": build_manifest["library_artifact"],
    }


def _isolated_trace(
    trace: str,
    *,
    route_link_manifest_path: Path,
    source_manifest_path: Path,
    build_manifest_path: Path,
) -> dict[str, Any]:
    completed = subprocess.run(
        [
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
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def _compile_worker_trace(
    trace: str,
    *,
    route_link_manifest_path: Path,
    source_manifest_path: Path,
    build_manifest_path: Path,
) -> dict[str, Any]:
    rows, _ = _load_inputs(
        route_link_manifest_path=route_link_manifest_path,
        source_manifest_path=source_manifest_path,
        build_manifest_path=build_manifest_path,
    )
    kernel = CtypesInitializedDiagnosticTrouteMuskingumCungeKernel(
        build_manifest_path
    )
    if trace == "mc_only":
        adapter, state, warmup = reach._warm_adapter(
            rows,
            kernel,
            timestep_seconds=TRACE_TIMESTEP_SECONDS,
            background_flow_m3s=TRACE_BACKGROUND_FLOW_M3S,
            assume_short_timestep=False,
        )
        selected = None
        for pulse in matrix.PULSE_RATES_M3S:
            case = reach._run_case(
                rows,
                adapter,
                state,
                timestep_seconds=TRACE_TIMESTEP_SECONDS,
                background_flow_m3s=TRACE_BACKGROUND_FLOW_M3S,
                pulse_rate_m3s=pulse,
            )
            if pulse == TRACE_PULSE_RATE_M3S:
                selected = case["outlet_response"]
    else:
        context, warmup = matrix._warm_operators(
            rows,
            kernel,
            timestep_seconds=TRACE_TIMESTEP_SECONDS,
            background_flow_m3s=TRACE_BACKGROUND_FLOW_M3S,
        )
        selected = None
        for pulse in matrix.PULSE_RATES_M3S:
            case = matrix._run_response_case(
                rows,
                context,
                timestep_seconds=TRACE_TIMESTEP_SECONDS,
                background_flow_m3s=TRACE_BACKGROUND_FLOW_M3S,
                pulse_rate_m3s=pulse,
            )
            if pulse == TRACE_PULSE_RATE_M3S:
                selected = case["t_route_mc"]
    if selected is None:
        raise RuntimeError("t_route_mc_initialized_trace_case_missing")
    return {"trace": trace, "warmup": warmup, "response": selected}


def _metric_differences(
    a: dict[str, Any], b: dict[str, Any]
) -> dict[str, float | None]:
    output = {
        key: float(a[key]) - float(b[key])
        for key in (
            "net_outlet_volume_m3",
            "negative_outlet_volume_m3",
            "minimum_response_m3s",
        )
    }
    for quantile in ("t05", "t50", "t95"):
        a_value = a["input_recovery_quantile_seconds"][quantile]
        b_value = b["input_recovery_quantile_seconds"][quantile]
        if a_value is None or b_value is None:
            output[f"{quantile}_seconds"] = None
        else:
            output[f"{quantile}_seconds"] = float(a_value) - float(b_value)
    return output


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
        raise ValueError("t_route_mc_initialized_matrix_refuses_overwrite")
    report = compile_certification(
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
    print(
        "outlet_negative="
        f"{report['matrix_summary']['outlet_negative_lobe_case_count']}/"
        f"{report['matrix_summary']['case_count']}"
    )
    print(
        "timestep_passed="
        f"{report['matrix_summary']['timestep_stability']['passed_count']}/"
        f"{report['matrix_summary']['timestep_stability']['comparison_count']}"
    )
    print(
        "cold_process_trace_invariance="
        f"{report['cold_process_trace_invariance']['passed']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
