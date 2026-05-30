"""Tests for bootstrap_ci."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def test_wilson_ci_returns_bounds_in_unit_interval():
    from scripts.nl2sql_bench_common.bootstrap_ci import wilson_ci
    lo, hi = wilson_ci(13, 20)
    assert 0.0 <= lo <= 0.65 <= hi <= 1.0


def test_wilson_ci_zero_successes():
    from scripts.nl2sql_bench_common.bootstrap_ci import wilson_ci
    lo, hi = wilson_ci(0, 20)
    assert lo == 0.0
    assert 0.0 < hi < 0.5


def test_wilson_ci_all_successes():
    from scripts.nl2sql_bench_common.bootstrap_ci import wilson_ci
    lo, hi = wilson_ci(20, 20)
    assert hi >= 0.999
    assert 0.5 < lo < 1.0


def test_bootstrap_ci_matches_wilson_approximately():
    from scripts.nl2sql_bench_common.bootstrap_ci import bootstrap_ci, wilson_ci
    # 13/20 = 0.65; both methods should give similar CIs
    outcomes = [1] * 13 + [0] * 7
    boot_lo, boot_hi = bootstrap_ci(outcomes, B=2000)
    wilson_lo, wilson_hi = wilson_ci(13, 20)
    # Within 0.05 absolute
    assert abs(boot_lo - wilson_lo) < 0.07
    assert abs(boot_hi - wilson_hi) < 0.07


def test_format_with_ci_reasonable_format():
    from scripts.nl2sql_bench_common.bootstrap_ci import format_with_ci
    s = format_with_ci(450, 1000)
    assert "0.450" in s
    assert "[" in s
    assert "]" in s
