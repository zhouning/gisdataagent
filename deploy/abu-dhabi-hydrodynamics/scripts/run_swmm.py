#!/usr/bin/env python3
"""Run an arbitrary SWMM input through the pinned portable executable."""

from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path, help="SWMM .inp file")
    parser.add_argument("--output", type=Path, default=None, help="run output directory")
    parser.add_argument("--timeout-seconds", type=int, default=2700)
    args = parser.parse_args()
    executable = Path(os.environ.get("ABU_DHABI_SWMM_EXECUTABLE", "/opt/swmm/bin/runswmm"))
    input_path = args.input.expanduser().resolve()
    if not input_path.is_file():
        raise SystemExit(f"input_missing:{input_path}")
    output = (args.output or Path(os.environ.get("ABU_DHABI_HYDRO_RUN_ROOT", "/data/runs")) / input_path.stem).resolve()
    output.mkdir(parents=True, exist_ok=True)
    report = output / f"{input_path.stem}.rpt"
    binary = output / f"{input_path.stem}.out"
    result = subprocess.run(
        [str(executable), str(input_path), str(report), str(binary)],
        capture_output=True,
        text=True,
        timeout=args.timeout_seconds,
        check=False,
    )
    (output / "stdout.log").write_text(result.stdout, encoding="utf-8")
    (output / "stderr.log").write_text(result.stderr, encoding="utf-8")
    if result.returncode != 0:
        raise SystemExit(f"swmm_failed:{result.returncode};see {output / 'stderr.log'}")
    print(f"completed output={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
