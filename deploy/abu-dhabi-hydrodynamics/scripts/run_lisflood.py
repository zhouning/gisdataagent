#!/usr/bin/env python3
"""Run an LISFLOOD-FP parameter file in the optional GPL runtime image."""

from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("parameter", type=Path)
    parser.add_argument("--timeout-seconds", type=int, default=2700)
    args = parser.parse_args()
    executable = Path(os.environ.get("LISFLOOD_EXECUTABLE", "/opt/lisflood/bin/lisflood"))
    parameter = args.parameter.expanduser().resolve()
    if not parameter.is_file():
        raise SystemExit(f"parameter_missing:{parameter}")
    result = subprocess.run(
        [str(executable), "-v", str(parameter)],
        cwd=parameter.parent,
        timeout=args.timeout_seconds,
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(f"lisflood_failed:{result.returncode}")
    print(f"completed parameter={parameter}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
