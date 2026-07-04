#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data_agent.benchmarks.twm_runtime_v1.runner import run_twm_runtime_benchmark


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the TWM Runtime Benchmark v1 gate report.")
    parser.add_argument("--suite", default="twm_runtime_v1", help="Benchmark suite id.")
    parser.add_argument("--output", default=str(REPO_ROOT / "docs/reports/twm_runtime_benchmark_v1.json"))
    parser.add_argument("--markdown-output", default=str(REPO_ROOT / "docs/reports/twm_runtime_benchmark_v1.md"))
    parser.add_argument("--fail-on-failed", action="store_true")
    args = parser.parse_args()

    report = run_twm_runtime_benchmark(
        suite=args.suite,
        output_path=Path(args.output).expanduser(),
        markdown_output_path=Path(args.markdown_output).expanduser(),
        fail_on_failed=False,
    )
    print(f"wrote {Path(args.output).expanduser()}")
    print(f"wrote {Path(args.markdown_output).expanduser()}")
    print(f"status={report['status']}")
    if args.fail_on_failed and report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
