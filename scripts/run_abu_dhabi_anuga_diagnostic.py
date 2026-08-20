#!/usr/bin/env python3
"""Run the pinned synthetic ANUGA fixture and write its governed receipt."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

from data_agent.uwm.abu_dhabi_flood import (
    AnugaQualityPolicy,
    TraditionalSolverRunRequest,
    execute_anuga,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PYTHON = Path("external_models/anuga-venv/bin/python")
DEFAULT_SOURCE = Path("external_models/anuga-core")
DEFAULT_SCRIPT = DEFAULT_SOURCE / "examples/simple_examples/channel1.py"
DEFAULT_RECEIPT = Path(
    "docs/customer/abu_dhabi_liveability_site_validation/technical_validation/"
    "anuga_synthetic_execution_receipt.json"
)
ANUGA_COMMIT = "9a7ef669872540a215bbb58972d12262a0209668"
ANUGA_DIFF_SHA256 = "7a8572541f42082f2261017d2b42ed60ea02d90ddcbd162df87c700a8f153aed"
ANUGA_STATUS_SHA256 = "7e63b3d53a4f17d0dc49ea99fea2ef1e2b422a2e595d3b46fab13812294fa614"


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--python", type=Path, default=DEFAULT_PYTHON)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--script", type=Path, default=DEFAULT_SCRIPT)
    parser.add_argument("--output", type=Path, default=DEFAULT_RECEIPT)
    return parser.parse_args()


def _repository_path(path: Path) -> Path:
    return path if path.is_absolute() else REPOSITORY_ROOT / path


def main() -> None:
    args = _arguments()
    output = _repository_path(args.output)
    os.chdir(REPOSITORY_ROOT)
    request = TraditionalSolverRunRequest(
        run_id="abu-dhabi-anuga-channel1-synthetic-diagnostic",
        solver_id="anuga_2d",
        executable_path=args.python,
        model_input_path=args.script,
        expected_solver_version="0.0.0+g9a7ef66.dirty",
        evidence_class="synthetic_fixture",
        calibration_status="not_calibrated",
    )
    receipt = execute_anuga(
        request,
        source_root=args.source,
        expected_source_commit=ANUGA_COMMIT,
        expected_source_diff_sha256=ANUGA_DIFF_SHA256,
        expected_source_status_sha256=ANUGA_STATUS_SHA256,
        output_filename="channel1.sww",
        quality_policy=AnugaQualityPolicy(
            expected_cell_count=200,
            expected_step_count=201,
            expected_start_seconds=0.0,
            expected_end_seconds=40.0,
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
