"""NL2SQLScenario — eval scenario for FloodSQL-Bench.

Metrics per question:
  - execution_valid: pred SQL ran without error
  - execution_accuracy (EX): pred result set == gold result set (multiset, float-tol)
  - exact_match: normalized SQL string equality (weak, informational)

Aggregate metrics computed across question lists by `aggregate()`.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from data_agent.eval_scenario import EvalScenario  # noqa: E402

from sql_executor import (  # noqa: E402  (sibling module)
    ExecResult,
    compare_result_sets,
    execute_sql,
    has_order_by,
)


def _normalize_sql(sql: str) -> str:
    s = re.sub(r"\s+", " ", sql or "").strip().rstrip(";").strip()
    return s.lower()


class NL2SQLScenario(EvalScenario):
    """Per-question scoring."""

    scenario = "nl2sql_floodsql"

    def evaluate(self, actual_output: dict, expected_output: dict) -> dict:
        """
        actual_output:   {"sql": str, "exec": ExecResult|None}
        expected_output: {"sql": str, "exec": ExecResult|None}
        """
        pred_sql = actual_output.get("sql", "") or ""
        gold_sql = expected_output.get("sql", "") or ""

        pred_exec: ExecResult | None = actual_output.get("exec")
        gold_exec: ExecResult | None = expected_output.get("exec")

        # Lazy execute if caller didn't pre-run
        if pred_exec is None and pred_sql:
            pred_exec = execute_sql(pred_sql)
        if gold_exec is None and gold_sql:
            gold_exec = execute_sql(gold_sql)

        valid = bool(pred_exec and pred_exec.status == "ok")

        if pred_exec is None or gold_exec is None:
            ex_match, reason = False, "missing exec result"
        else:
            order = has_order_by(gold_sql)
            ex_match, reason = compare_result_sets(gold_exec, pred_exec, order_sensitive=order)

        em = _normalize_sql(pred_sql) == _normalize_sql(gold_sql)

        return {
            "execution_valid": 1.0 if valid else 0.0,
            "execution_accuracy": 1.0 if ex_match else 0.0,
            "exact_match": 1.0 if em else 0.0,
            "compare_reason": reason,
            "pred_status": (pred_exec.status if pred_exec else "none"),
            "gold_status": (gold_exec.status if gold_exec else "none"),
        }


def aggregate(records: list[dict]) -> dict:
    """Aggregate per-question metric dicts. Records have keys:
    metrics: {execution_valid, execution_accuracy, exact_match, ...}
    difficulty: 'L0'..'L5'
    """
    if not records:
        return {"n": 0}

    n = len(records)
    valid = sum(r["metrics"]["execution_valid"] for r in records) / n
    ex = sum(r["metrics"]["execution_accuracy"] for r in records) / n
    em = sum(r["metrics"]["exact_match"] for r in records) / n

    by_diff: dict[str, list[float]] = {}
    for r in records:
        d = r.get("difficulty", "?")
        by_diff.setdefault(d, []).append(r["metrics"]["execution_accuracy"])
    diff_breakdown = {d: round(sum(v) / len(v), 3) for d, v in sorted(by_diff.items())}

    err_types: dict[str, int] = {}
    for r in records:
        m = r["metrics"]
        if m["execution_accuracy"] == 1.0:
            continue
        if m["pred_status"] != "ok":
            err_types[f"exec_{m['pred_status']}"] = err_types.get(f"exec_{m['pred_status']}", 0) + 1
        else:
            err_types["result_mismatch"] = err_types.get("result_mismatch", 0) + 1

    return {
        "n": n,
        "execution_valid_rate": round(valid, 4),
        "execution_accuracy": round(ex, 4),
        "exact_match_rate": round(em, 4),
        "by_difficulty": diff_breakdown,
        "error_types": dict(sorted(err_types.items(), key=lambda x: -x[1])),
    }
