"""Unit tests for run_cq_eval.compare_results numeric-in-prose extraction (L2).

The L2 layer was added to handle a specific gemini-3.5-flash failure mode where
the model wraps a scalar SQL result in a string template:

    SELECT 'The count is ' || COUNT(*) AS result FROM cq_buildings_2021 WHERE ...

The SQL executes correctly and returns the right numeric answer, only the
string framing differs. The evaluator should extract the numeric literal and
match with float tolerance — but only when there's exactly ONE numeric token
in the string side, to avoid false merges.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "nl2sql_bench_cq"))

from run_cq_eval import compare_results


def _ok(rows):
    return {"status": "ok", "rows": rows}


def test_pred_string_wraps_gold_int_passes():
    gold = _ok([(30096,)])
    pred = _ok([("The count is 30096",)])
    ok, reason = compare_results(gold, pred)
    assert ok, f"expected pass, got reason={reason}"
    assert "numeric-in-prose" in reason


def test_pred_string_wraps_gold_float_passes():
    gold = _ok([(2.8791,)])
    pred = _ok([("Total area is 2.8791",)])
    ok, reason = compare_results(gold, pred)
    assert ok, f"expected pass, got reason={reason}"


def test_pred_string_wraps_gold_within_tolerance():
    gold = _ok([(30096,)])
    pred = _ok([("Result: 30095.5",)])  # 1.7e-5 relative diff, within 1e-3
    ok, reason = compare_results(gold, pred)
    assert ok, f"expected pass within tolerance, got reason={reason}"


def test_pred_string_outside_tolerance_fails():
    gold = _ok([(30096,)])
    pred = _ok([("Approximately 30000",)])  # 0.32% diff, outside 1e-3
    ok, reason = compare_results(gold, pred)
    assert not ok


def test_multiple_numbers_in_prose_does_not_extract():
    """If the prose has multiple numbers, can't unambiguously extract — fail."""
    gold = _ok([(30096,)])
    pred = _ok([("In 2024, the count is 30096",)])  # 2 numbers: 2024 and 30096
    ok, reason = compare_results(gold, pred)
    assert not ok, "should NOT extract when prose has multiple numbers (ambiguous)"


def test_gold_string_wraps_pred_int_passes():
    """Symmetric direction: if gold is the string-wrapped one and pred is plain numeric."""
    gold = _ok([("Result: 30096",)])
    pred = _ok([(30096,)])
    ok, reason = compare_results(gold, pred)
    assert ok, f"expected pass, got reason={reason}"


def test_pure_string_mismatch_still_fails():
    """Original string-vs-string strict equality is preserved."""
    gold = _ok([("ST_Polygon",)])
    pred = _ok([("面",)])
    ok, reason = compare_results(gold, pred)
    assert not ok
    assert "value:" in reason


def test_pure_numeric_match_still_passes():
    """Existing numeric float-tol path still works."""
    gold = _ok([(2.8791,)])
    pred = _ok([(2.8791001,)])
    ok, reason = compare_results(gold, pred)
    assert ok
    assert "float" in reason


def test_multi_row_unaffected():
    """L2 only applies to len==1 case; multi-row should be unchanged."""
    gold = _ok([(1,), (2,), (3,)])
    pred = _ok([("Total: 1",), ("Total: 2",), ("Total: 3",)])
    ok, reason = compare_results(gold, pred)
    # Multi-row pred-strings won't match numeric gold (and shouldn't — the
    # extraction is restricted to single-value cells)
    assert not ok


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
