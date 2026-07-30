#!/usr/bin/env python3
"""Run deterministic Paper9 behavior contracts and write a JSON report."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from data_agent.paper9_agent_evaluation import evaluate_paper9_tool_trajectory

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASES = ROOT / "data_agent" / "evals" / "paper9_finals" / "behavior_contract_cases.json"
DEFAULT_OUTPUT = (
    ROOT
    / "data_agent"
    / "demo_evidence"
    / "paper9"
    / "finals_20260730"
    / "behavior_contract_report.json"
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    payload = json.loads(args.cases.read_text(encoding="utf-8"))
    results = []
    for case in payload.get("cases", []):
        actual = evaluate_paper9_tool_trajectory(case.get("events", []))
        matched = actual["passed"] is bool(case.get("expected_pass"))
        results.append(
            {
                "id": case.get("id"),
                "expected_pass": bool(case.get("expected_pass")),
                "matched_expectation": matched,
                "evaluation": actual,
            }
        )

    passed = sum(1 for result in results if result["matched_expectation"])
    report = {
        "schema_version": "paper9.behavior_contract_report.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "scope": "deterministic_offline_behavior_contracts",
        "limitations": [
            "This report validates control-flow invariants, not stochastic Gemma 4 "
            "tool-selection reliability.",
            "Live model reliability must be measured separately with repeated ADK runs.",
        ],
        "summary": {
            "total": len(results),
            "matched": passed,
            "pass_rate": passed / len(results) if results else 0.0,
        },
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report["summary"], ensure_ascii=False))
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
