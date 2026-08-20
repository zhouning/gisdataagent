#!/usr/bin/env python3
"""Run the pinned synthetic SWMM fixture and write its governed receipt."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

from data_agent.uwm.abu_dhabi_flood import TraditionalSolverRunRequest, execute_swmm

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EXECUTABLE = Path("external_models/swmm-5.2.4/build-local/bin/runswmm")
DEFAULT_INPUT = Path(
    "external_models/swmm-5.2.4/validation/abu_dhabi_synthetic_storm.inp"
)
DEFAULT_RECEIPT = Path(
    "docs/customer/abu_dhabi_liveability_site_validation/technical_validation/"
    "swmm_synthetic_execution_receipt.json"
)


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--executable", type=Path, default=DEFAULT_EXECUTABLE)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_RECEIPT)
    return parser.parse_args()


def _repository_path(path: Path) -> Path:
    return path if path.is_absolute() else REPOSITORY_ROOT / path


def main() -> None:
    args = _arguments()
    output = _repository_path(args.output)
    os.chdir(REPOSITORY_ROOT)
    request = TraditionalSolverRunRequest(
        run_id="abu-dhabi-swmm-5.2.4-synthetic-diagnostic",
        solver_id="epa_swmm",
        executable_path=args.executable,
        model_input_path=args.input,
        expected_solver_version="5.2.4",
        evidence_class="synthetic_fixture",
        calibration_status="not_calibrated",
    )
    receipt = execute_swmm(request)
    output.parent.mkdir(parents=True, exist_ok=True)
    encoded = (
        json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False)
        + "\n"
    ).encode("ascii")
    with tempfile.NamedTemporaryFile(dir=output.parent, delete=False) as handle:
        handle.write(encoded)
        temporary = Path(handle.name)
    os.replace(temporary, output)
    print(json.dumps({"output": str(output), "receipt_sha256": receipt["receipt_sha256"]}))


if __name__ == "__main__":
    main()
