#!/usr/bin/env python3
"""Acquire fixed-commit t-route MC network-execution source evidence."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

if __package__:
    from scripts import acquire_geotransport_troute_mc_source as source
else:
    import acquire_geotransport_troute_mc_source as source


REPO_ROOT = source.REPO_ROOT
DEFAULT_OUTPUT = (
    REPO_ROOT / "data/geotransport_v0_1/t_route_mc_execution_source_audit"
)
SCHEMA = "gwm.geotransport.t_route_mc_execution_source_audit.v1"
MAXIMUM_TOTAL_BYTES = 180_000
REQUESTS = (
    (
        "network_execution_kernel",
        "src/troute-routing/troute/routing/fast_reach/mc_reach.pyx",
        "mc_reach.pyx",
        60_000,
        "official_network_timestep_reach_execution",
    ),
    (
        "python_execution_driver",
        "src/troute-routing/troute/routing/compute.py",
        "compute.py",
        110_000,
        "official_network_input_and_qts_subdivision_driver",
    ),
    (
        "fortran_wrapper_declarations",
        "src/troute-routing/troute/routing/fast_reach/fortran_wrappers.pxd",
        "fortran_wrappers.pxd",
        10_000,
        "official_cython_fortran_abi_declarations",
    ),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--proxy", default="http://127.0.0.1:7897")
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    parser.add_argument("--retries", type=int, default=3)
    return parser.parse_args()


def compile_plan(*, values_mode: bool = False) -> dict[str, Any]:
    requests = [source._request(*values) for values in REQUESTS]
    planned = sum(int(item["maximum_bytes"]) for item in requests)
    if len(requests) != len(REQUESTS) or planned > MAXIMUM_TOTAL_BYTES:
        raise ValueError("t_route_mc_execution_source_request_boundary_exceeded")
    return {
        "schema": SCHEMA,
        "mode": "values" if values_mode else "plan",
        "purpose": (
            "audit the fixed-commit full network execution contract around the "
            "already acquired official single-segment MC kernel"
        ),
        "repository": source.T_ROUTE_REPOSITORY,
        "commit": source.T_ROUTE_COMMIT,
        "request_boundary": {
            "allowed_host": source.ALLOWED_HOST,
            "maximum_object_count": len(REQUESTS),
            "maximum_total_bytes": MAXIMUM_TOTAL_BYTES,
            "planned_maximum_bytes": planned,
        },
        "requests": requests,
        "data_isolation": {
            "source_code_only": True,
            "observed_discharge_requested": False,
            "observed_forcing_requested": False,
            "outcome_values_requested": False,
        },
        "claim_boundary": {
            "execution_source_acquired": values_mode,
            "execution_semantics_audited": False,
            "t_route_mc_promotion_gate_passed": False,
            "geospatial_kernel_validated": False,
        },
    }


def main() -> int:
    args = parse_args()
    if args.timeout_seconds <= 0.0 or args.retries <= 0:
        raise ValueError("t_route_mc_execution_source_positive_limits_required")
    manifest = compile_plan(values_mode=not args.plan_only)
    args.output.mkdir(parents=True, exist_ok=True)
    if args.plan_only:
        source._write_json(args.output / "acquisition_plan.json", manifest)
        print(args.output / "acquisition_plan.json")
        return 0

    raw_root = args.output / "raw"
    raw_root.mkdir(parents=True, exist_ok=True)
    opener = source._opener(args.proxy)
    total_bytes = 0
    artifacts = []
    for request in manifest["requests"]:
        body, retrieval = source._fetch(
            str(request["url"]),
            opener=opener,
            timeout_seconds=args.timeout_seconds,
            retries=args.retries,
            maximum_bytes=int(request["maximum_bytes"]),
        )
        total_bytes += len(body)
        if total_bytes > MAXIMUM_TOTAL_BYTES:
            raise ValueError("t_route_mc_execution_source_total_boundary_exceeded")
        path = raw_root / str(request["output_name"])
        path.write_bytes(body)
        artifacts.append({**request, **retrieval, **source._artifact(path, body)})

    manifest.update(
        {
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "artifacts": artifacts,
            "artifact_count": len(artifacts),
            "total_downloaded_bytes": total_bytes,
        }
    )
    output = args.output / "acquisition_manifest.json"
    output.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
