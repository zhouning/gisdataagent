from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def load_payload(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _format_diff_table(baseline: dict, full: dict) -> str:
    diffs = sorted(set(baseline["summary"]["by_difficulty"]) | set(full["summary"]["by_difficulty"]))
    lines = ["| Difficulty | Baseline EX | Full EX | Delta |", "|---|---:|---:|---:|"]
    for diff in diffs:
        b = baseline["summary"]["by_difficulty"].get(diff, 0.0)
        f = full["summary"]["by_difficulty"].get(diff, 0.0)
        lines.append(f"| {diff} | {b:.4f} | {f:.4f} | {f - b:+.4f} |")
    return "\n".join(lines)


def write_report(run_dir: Path, baseline: dict, full: dict) -> Path:
    b = baseline["summary"]["execution_accuracy"]
    f = full["summary"]["execution_accuracy"]
    markdown = f"""# BIRD PostgreSQL Evaluation Report

## Summary

- baseline EX={b:.4f}
- full EX={f:.4f}
- delta={f - b:+.4f}
- baseline valid={baseline['summary']['execution_valid_rate']:.4f}
- full valid={full['summary']['execution_valid_rate']:.4f}

## By Difficulty

{_format_diff_table(baseline, full)}
"""
    out = run_dir / "comparison_report.md"
    out.write_text(markdown, encoding="utf-8")
    return out


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Generate BIRD PG evaluation comparison report")
    p.add_argument("--run-dir", required=True, help="Directory containing baseline_results.json and full_results.json")
    return p


def main() -> int:
    args = build_arg_parser().parse_args()
    run_dir = Path(args.run_dir)
    baseline_path = run_dir / "baseline_results.json"
    full_path = run_dir / "full_results.json"
    if not baseline_path.exists():
        print(f"ERROR: {baseline_path} not found", file=sys.stderr)
        return 2
    if not full_path.exists():
        print(f"ERROR: {full_path} not found", file=sys.stderr)
        return 2
    baseline = load_payload(baseline_path)
    full = load_payload(full_path)
    out = write_report(run_dir, baseline, full)
    print(f"[bird-pg-report] Wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
