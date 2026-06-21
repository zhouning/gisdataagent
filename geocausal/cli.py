from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .config import load_config
from .errors import GeoCausalError
from .pipeline import diagnose_config, rebuild_report, run_analysis


SCCA_TEMPLATE = """case_name: example_case
input:
  path: data.csv
  x: x
  y: y
variables:
  unit_id: unit_id
  exposure: exposure
  outcome: outcome
  baseline_outcome: baseline_outcome
  confounders:
    - confounder_1
context:
  columns:
    - context_1
robustness:
  placebo_exposures:
    - name: placebo_check
      column: placebo_exposure
      role: negative_control
      expected_relation: weaker_than_main
  bootstrap:
    group_column: group
    n_replicates: 200
output:
  directory: results/example_case
"""


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="geocausal")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="write an analysis template")
    init_parser.add_argument("--template", choices=["scca"], default="scca")
    init_parser.add_argument("--output", default="analysis.yaml")

    diagnose_parser = subparsers.add_parser("diagnose", help="diagnose an analysis config")
    diagnose_parser.add_argument("config")

    run_parser = subparsers.add_parser("run", help="run an analysis config")
    run_parser.add_argument("config")

    report_parser = subparsers.add_parser("report", help="rebuild a markdown report")
    report_parser.add_argument("output_dir")

    return parser


def _print_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def _write_template(output: str) -> dict[str, str]:
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(SCCA_TEMPLATE, encoding="utf-8")
    return {"template": "scca", "path": str(output_path)}


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "init":
            _print_json(_write_template(args.output))
        elif args.command == "diagnose":
            _print_json(diagnose_config(load_config(args.config)))
        elif args.command == "run":
            _print_json(run_analysis(load_config(args.config)))
        elif args.command == "report":
            _print_json(rebuild_report(args.output_dir))
        else:
            parser.error(f"unknown command: {args.command}")
        return 0
    except GeoCausalError as exc:
        print(f"GeoCausal error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
