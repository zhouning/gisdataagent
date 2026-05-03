def test_mcnemar_returns_p_value_for_paired_results():
    from scripts.nl2sql_bench_common.mcnemar import mcnemar_paired
    base = [1, 0, 1, 0, 1, 0]
    full = [1, 1, 0, 1, 1, 0]
    out = mcnemar_paired(base, full)
    assert "b" in out and "c" in out and "p_value" in out
    assert out["b"] + out["c"] >= 1
    assert 0.0 <= out["p_value"] <= 1.0


def test_mcnemar_identical_results_gives_p_one():
    from scripts.nl2sql_bench_common.mcnemar import mcnemar_paired
    same = [1, 0, 1, 0]
    out = mcnemar_paired(same, same)
    assert out["b"] == 0 and out["c"] == 0
    assert out["p_value"] == 1.0


def test_mcnemar_raises_on_length_mismatch():
    import pytest
    from scripts.nl2sql_bench_common.mcnemar import mcnemar_paired
    with pytest.raises(ValueError):
        mcnemar_paired([1, 0], [1])
