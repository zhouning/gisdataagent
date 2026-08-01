#!/usr/bin/env python3
"""Generate the fail-closed GWM Geospatial Kernel K0 assessment."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from data_agent.uwm.gwm_geospatial_kernel_readiness import (
    assess_gwm_geospatial_kernel_k0,
    load_json,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONTRACT = (
    REPO_ROOT
    / "docs/research/GWM_GEOSPATIAL_KERNEL_K0_READINESS_CONTRACT_2026-07-20.json"
)
DEFAULT_OUTPUT = (
    REPO_ROOT
    / "data/benchmarks/gwm_geospatial_kernel_k0_2026-07-20/readiness_report.json"
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--require-k0", action="store_true")
    args = parser.parse_args()

    report = assess_gwm_geospatial_kernel_k0(
        root=REPO_ROOT,
        contract=load_json(args.contract.resolve()),
    )
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(output),
                "status": report["decision"]["status"],
                "uwm_k1_admitted": report["decision"]["uwm_k1_admitted"],
                "public_release_ready": report["decision"]["public_release_ready"],
                "first_gap": report["first_legitimately_closable_gap"]["id"],
            },
            indent=2,
        )
    )
    if args.require_k0 and not report["decision"]["k0_scientific_readiness_pass"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
