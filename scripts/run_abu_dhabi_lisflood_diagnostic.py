#!/usr/bin/env python3
"""Run the pinned synthetic LISFLOOD-FP fixture and write its governed receipt."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

from data_agent.uwm.abu_dhabi_flood import (
    LisfloodQualityPolicy,
    TraditionalSolverRunRequest,
    execute_lisflood,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = Path("external_models/lisflood-fp-bmi-5.9")
DEFAULT_RUNTIME = DEFAULT_SOURCE / "lisflood-fp-bmi-v5.9"
DEFAULT_EXECUTABLE = DEFAULT_RUNTIME / "lisflood"
DEFAULT_LIBRARY = DEFAULT_RUNTIME / "liblisflood.so"
DEFAULT_PARAMETER = DEFAULT_RUNTIME / "validation/lisflood_synthetic.par"
DEFAULT_RECEIPT = Path(
    "docs/customer/abu_dhabi_liveability_site_validation/technical_validation/"
    "lisflood_synthetic_execution_receipt.json"
)
LISFLOOD_COMMIT = "11f2a9214f80e1194bfaea23bc52a8247b9924ad"
LISFLOOD_DIFF_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
LISFLOOD_STATUS_SHA256 = (
    "e6b8c54555408eb9c914ab77ab93b43bad36bee9c8a53680ba76cc0f8bf0cba5"
)


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--executable", type=Path, default=DEFAULT_EXECUTABLE)
    parser.add_argument("--library", type=Path, default=DEFAULT_LIBRARY)
    parser.add_argument("--parameter", type=Path, default=DEFAULT_PARAMETER)
    parser.add_argument("--output", type=Path, default=DEFAULT_RECEIPT)
    return parser.parse_args()


def _repository_path(path: Path) -> Path:
    return path if path.is_absolute() else REPOSITORY_ROOT / path


def main() -> None:
    args = _arguments()
    output = _repository_path(args.output)
    os.chdir(REPOSITORY_ROOT)
    request = TraditionalSolverRunRequest(
        run_id="abu-dhabi-lisflood-synthetic-diagnostic",
        solver_id="lisflood_fp_2d",
        executable_path=args.executable,
        model_input_path=args.parameter,
        expected_solver_version="5.99.0",
        evidence_class="synthetic_fixture",
        calibration_status="not_calibrated",
    )
    receipt = execute_lisflood(
        request,
        runtime_library_path=args.library,
        source_root=args.source,
        expected_source_commit=LISFLOOD_COMMIT,
        expected_source_diff_sha256=LISFLOOD_DIFF_SHA256,
        expected_source_status_sha256=LISFLOOD_STATUS_SHA256,
        quality_policy=LisfloodQualityPolicy(
            expected_ncols=5,
            expected_nrows=5,
            expected_final_time_seconds=60.0,
            expected_final_volume_m3=5.0,
        ),
    )
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
