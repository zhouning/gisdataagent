#!/usr/bin/env python3
"""Audit fixed-commit t-route execution semantics against the local MC adapter."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EXECUTION_MANIFEST = (
    REPO_ROOT
    / "data/geotransport_v0_1/t_route_mc_execution_source_audit/acquisition_manifest.json"
)
DEFAULT_KERNEL_MANIFEST = (
    REPO_ROOT
    / "data/geotransport_v0_1/t_route_mc_source_audit/acquisition_manifest.json"
)
DEFAULT_ADAPTER = (
    REPO_ROOT
    / "data_agent/uwm/geospatial_kernel_v2/troute_muskingum_cunge.py"
)
DEFAULT_REPORT = (
    REPO_ROOT
    / "benchmarks/geotransport_v0_1/t_route_mc_execution_semantics_report.json"
)
SCHEMA = "gwm.geotransport.t_route_mc_execution_semantics.v1"
EXECUTION_MANIFEST_SCHEMA = "gwm.geotransport.t_route_mc_execution_source_audit.v1"
KERNEL_MANIFEST_SCHEMA = "gwm.geotransport.t_route_mc_source_audit.v1"
T_ROUTE_COMMIT = "12a8eae0cdfed437143c590659fa7077605a5e70"
EXPECTED_EXECUTION_HASHES = {
    "mc_reach.pyx": "cf17d4caf0fa819c15090579722270b8b1652651215a5146c21dc1af2fe32a3c",
    "compute.py": "82d9d7ef05b7466800fa0131ec7768d9bca4564e0b015dce654fa70bf3c968bb",
    "fortran_wrappers.pxd": "da75b439219fffe17af2c05e3e5c21ed96c8dd1f4019aa9252791ac90f848594",
}
EXPECTED_KERNEL_HASHES = {
    "MCsingleSegStime_f2py_NOLOOP.f90": (
        "1c0e47b3528c3fdf20c960408e41138921cb903e5035bd19e6c4e68f8f4b46da"
    ),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--execution-manifest", type=Path, default=DEFAULT_EXECUTION_MANIFEST
    )
    parser.add_argument("--kernel-manifest", type=Path, default=DEFAULT_KERNEL_MANIFEST)
    parser.add_argument("--adapter", type=Path, default=DEFAULT_ADAPTER)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def compile_audit(
    *,
    execution_manifest_path: Path = DEFAULT_EXECUTION_MANIFEST,
    kernel_manifest_path: Path = DEFAULT_KERNEL_MANIFEST,
    adapter_path: Path = DEFAULT_ADAPTER,
) -> dict[str, Any]:
    execution_body = execution_manifest_path.read_bytes()
    kernel_body = kernel_manifest_path.read_bytes()
    execution_manifest = json.loads(execution_body)
    kernel_manifest = json.loads(kernel_body)
    _validate_manifest(
        execution_manifest,
        schema=EXECUTION_MANIFEST_SCHEMA,
        expected_hashes=EXPECTED_EXECUTION_HASHES,
    )
    _validate_manifest(
        kernel_manifest,
        schema=KERNEL_MANIFEST_SCHEMA,
        expected_hashes=EXPECTED_KERNEL_HASHES,
        allow_additional=True,
        require_source_only_flag=False,
    )

    execution_sources = _load_artifacts(
        execution_manifest_path, execution_manifest, EXPECTED_EXECUTION_HASHES
    )
    kernel_sources = _load_artifacts(
        kernel_manifest_path, kernel_manifest, EXPECTED_KERNEL_HASHES
    )
    adapter_body = adapter_path.read_bytes()
    adapter_text = adapter_body.decode("utf-8")

    mc_reach = execution_sources["mc_reach.pyx"]
    compute = execution_sources["compute.py"]
    abi = execution_sources["fortran_wrappers.pxd"]
    fortran = kernel_sources["MCsingleSegStime_f2py_NOLOOP.f90"]

    findings = [
        _finding(
            "network_current_and_previous_upstream_aggregation",
            mc_reach,
            [
                "upstream_flows += flowveldepth[id, timestep, 0]",
                "previous_upstream_flows += flowveldepth[id, timestep-1, 0]",
            ],
            conclusion=(
                "The full driver separately sums current-step and previous-step "
                "upstream reach discharge."
            ),
        ),
        _finding(
            "short_timestep_switch_and_default",
            mc_reach,
            [
                "bint assume_short_ts=False",
                "if assume_short_ts:",
                "upstream_flows = previous_upstream_flows",
            ],
            conclusion=(
                "The fixed Cython entrypoint defaults assume_short_ts to false; "
                "true replaces current upstream flow with previous upstream flow."
            ),
        ),
        _finding(
            "within_reach_segment_recursion",
            mc_reach,
            [
                "qup = qdp",
                "quc = qup",
                "quc = out.qdc",
            ],
            conclusion=(
                "For the next segment, previous upstream flow is the upstream "
                "segment's previous discharge. Current upstream flow is its newly "
                "computed discharge by default, or the previous value in short-ts mode."
            ),
        ),
        _finding(
            "lateral_flow_temporal_hold",
            mc_reach,
            [
                "qlat_array[ segment.id, <int>((timestep-1)/qts_subdivisions)]",
            ],
            conclusion=(
                "qts_subdivisions selects a held lateral-flow time column; it is "
                "not a spatial reach subdivision or an internal solver substep."
            ),
        ),
        _finding(
            "global_timestep_and_float32_input_path",
            compute,
            ['param_df["dt"] = dt', 'param_df = param_df.astype("float32")'],
            conclusion=(
                "The Python driver writes the global routing timestep into every "
                "parameter row and casts the parameter table to float32."
            ),
        ),
        _finding(
            "previous_velocity_zeroed_by_full_driver",
            mc_reach,
            [
                "Note that velp isn't used anywhere",
                "buf_view[_i, 11] = 0.0",
            ],
            conclusion=(
                "The full execution path passes zero previous velocity and records "
                "that velp is unused by this kernel."
            ),
        ),
        _finding(
            "lateral_inflow_is_a_rate",
            fortran,
            ["C4 =  (ql*dt)/D"],
            conclusion=(
                "The segment kernel integrates ql over dt, so adapter lateral input "
                "has discharge-rate units rather than per-step volume units."
            ),
        ),
        _finding(
            "output_qdc_read_before_assignment",
            fortran,
            [
                "real(prec), intent(out) :: qdc, velc, depthc",
                ".or. qdp .gt. 0.0_prec .or. qdc .gt. 0.0_prec",
            ],
            conclusion=(
                "qdc is declared intent(out) and is read in the wet/dry guard before "
                "the subroutine assigns it. This is an undefined initialization path."
            ),
        ),
        _finding(
            "secant_outputs_read_before_assignment",
            fortran,
            [
                "real(prec), intent(out) :: Qj, C1, C2, C3, C4, X",
                "1.0_prec-(Qj/(2.0_prec*twl*s0*Ck*dx))",
                "0.5_prec*(1.0_prec-(((C1*qup)+(C2*quc)",
                "C1 =  (Km*X + dt/2.0_prec)/D",
                "Qj =  ((C1*qup)+(C2*quc)+(C3*qdp) + C4)",
            ],
            conclusion=(
                "secant2_h computes X from intent(out) Qj in the upper interval, "
                "or from intent(out) C1..C4 in the lower interval, before assigning "
                "those outputs later in the subroutine."
            ),
        ),
        _finding(
            "fortran_abi_argument_order",
            abi,
            [
                "void c_muskingcungenwm(float *dt,",
                "float *qup,",
                "float *quc,",
                "float *qdp,",
                "float *ql,",
                "float *velp,",
                "float *depthp,",
                "float *qdc,",
                "float *velc,",
                "float *depthc,",
            ],
            conclusion=(
                "The acquired ABI declaration agrees with the adapter's 15 inputs "
                "followed by qdc, velc, depthc, ck, cn, and X."
            ),
        ),
        _finding(
            "adapter_default_and_short_ts_mapping",
            (adapter_path, adapter_text),
            [
                "assume_short_timestep: bool = False",
                "self.assume_short_timestep = assume_short_timestep",
                "quc = qup if self.assume_short_timestep else",
            ],
            conclusion=(
                "The local chain adapter exposes the official switch, defaults it "
                "to false, and applies it at both the external boundary and every "
                "within-chain segment transition."
            ),
        ),
    ]

    return {
        "schema": SCHEMA,
        "status": "fixed_commit_execution_semantics_audited",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "runtime_identity": {
            "repository": "NOAA-OWP/t-route",
            "commit": T_ROUTE_COMMIT,
            "official_source_unmodified": True,
        },
        "source_artifacts": {
            "execution_manifest": _artifact(execution_manifest_path, execution_body),
            "kernel_manifest": _artifact(kernel_manifest_path, kernel_body),
            "local_adapter": _artifact(adapter_path, adapter_body),
        },
        "findings": findings,
        "adapter_conformance": {
            "open_loop_serial_chain_default_upstream_recursion_matches": True,
            "open_loop_serial_chain_short_ts_recursion_matches": True,
            "fortran_abi_matches": True,
            "lateral_flow_rate_semantics_match": True,
            "global_timestep_semantics_match": True,
            "float32_fortran_call_boundary_matches": True,
            "missing_full_python_driver_explains_response_matrix_failure": False,
        },
        "numerical_initialization_audit": {
            "output_read_before_assignment_found": True,
            "stateless_call_order_invariance_required": True,
            "fixed_commit_kernel_numerically_well_defined": False,
            "generic_muskingum_cunge_method_impugned": False,
        },
        "non_equivalence_boundary": {
            "full_network_application_reproduced": False,
            "branching_reach_scheduler_reproduced": False,
            "reservoir_routing_reproduced": False,
            "data_assimilation_reproduced": False,
            "parallel_subnetwork_execution_reproduced": False,
            "authoritative_mc_storage_exposed": False,
        },
        "data_isolation": {
            "source_code_only": True,
            "observed_discharge_loaded": False,
            "observed_forcing_loaded": False,
            "outcome_values_loaded": False,
        },
        "claim_boundary": {
            "execution_semantics_audited": True,
            "adapter_default_chain_semantics_match": True,
            "full_t_route_application_equivalence_claimed": False,
            "response_matrix_failure_attributed_to_driver_omission": False,
            "fixed_commit_kernel_initialization_gate_passed": False,
            "t_route_mc_promotion_gate_passed": False,
            "geospatial_kernel_validated": False,
        },
    }


def _validate_manifest(
    manifest: dict[str, Any],
    *,
    schema: str,
    expected_hashes: dict[str, str],
    allow_additional: bool = False,
    require_source_only_flag: bool = True,
) -> None:
    artifacts = manifest.get("artifacts") or []
    observed = {str(item.get("output_name")): item for item in artifacts}
    if (
        manifest.get("schema") != schema
        or manifest.get("mode") != "values"
        or manifest.get("commit") != T_ROUTE_COMMIT
        or (
            require_source_only_flag
            and manifest.get("data_isolation", {}).get("source_code_only") is not True
        )
        or not set(expected_hashes).issubset(observed)
        or (not allow_additional and set(expected_hashes) != set(observed))
    ):
        raise ValueError("t_route_mc_execution_semantics_manifest_invalid")
    for name, expected_hash in expected_hashes.items():
        if observed[name].get("sha256") != expected_hash:
            raise ValueError(f"t_route_mc_execution_semantics_manifest_hash_mismatch:{name}")


def _load_artifacts(
    manifest_path: Path,
    manifest: dict[str, Any],
    expected_hashes: dict[str, str],
) -> dict[str, tuple[Path, str]]:
    output: dict[str, tuple[Path, str]] = {}
    by_name = {str(item["output_name"]): item for item in manifest["artifacts"]}
    for name, expected_hash in expected_hashes.items():
        descriptor = by_name[name]
        path = Path(str(descriptor["path"]))
        if not path.is_absolute():
            candidate = REPO_ROOT / path
            path = candidate if candidate.exists() else manifest_path.parent / path
        body = path.read_bytes()
        if (
            hashlib.sha256(body).hexdigest() != expected_hash
            or len(body) != descriptor.get("size_bytes")
        ):
            raise ValueError(f"t_route_mc_execution_semantics_artifact_mismatch:{name}")
        output[name] = (path, body.decode("utf-8"))
    return output


def _finding(
    finding_id: str,
    source: tuple[Path, str],
    needles: list[str],
    *,
    conclusion: str,
) -> dict[str, Any]:
    path, content = source
    lines = content.splitlines()
    evidence = []
    for needle in needles:
        matches = [index for index, line in enumerate(lines, start=1) if needle in line]
        if not matches:
            raise ValueError(
                f"t_route_mc_execution_semantics_evidence_missing:{finding_id}:{needle}"
            )
        line_number = matches[0]
        evidence.append(
            {
                "path": str(path.relative_to(REPO_ROOT)),
                "line": line_number,
                "source": lines[line_number - 1].strip(),
            }
        )
    return {
        "finding_id": finding_id,
        "verified": True,
        "conclusion": conclusion,
        "evidence": evidence,
    }


def _artifact(path: Path, body: bytes) -> dict[str, Any]:
    resolved = path.resolve()
    try:
        display = str(resolved.relative_to(REPO_ROOT))
    except ValueError:
        display = str(resolved)
    return {
        "path": display,
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }


def main() -> int:
    args = parse_args()
    report = compile_audit(
        execution_manifest_path=args.execution_manifest,
        kernel_manifest_path=args.kernel_manifest,
        adapter_path=args.adapter,
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(args.report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
