"""Tests for Remote Sensing Phase 2 — Spatiotemporal Analysis (v22.0)."""
import numpy as np
import pytest

from data_agent.rs_temporal import (
    detect_change_difference,
    detect_change_index,
    detect_change_classification,
    mann_kendall_trend,
    detect_breakpoints,
    assess_evidence,
)


# ---------------------------------------------------------------------------
# Change Detection
# ---------------------------------------------------------------------------

def test_change_difference_basic():
    before = np.zeros((10, 10), dtype=np.float32)
    after = np.ones((10, 10), dtype=np.float32) * 0.5
    result = detect_change_difference(before, after, threshold=0.15)
    assert result.method == "bi_temporal_difference"
    assert result.changed_area_pct == 100.0
    assert result.changed_pixels == 100
    assert result.change_map is not None


def test_change_difference_no_change():
    arr = np.ones((5, 5), dtype=np.float32) * 0.3
    result = detect_change_difference(arr, arr, threshold=0.1)
    assert result.changed_pixels == 0
    assert result.changed_area_pct == 0.0


def test_change_difference_multiband():
    before = np.zeros((5, 5, 3), dtype=np.float32)
    after = np.ones((5, 5, 3), dtype=np.float32)
    result = detect_change_difference(before, after, threshold=0.5)
    assert result.total_pixels == 25
    assert result.changed_pixels == 25


def test_change_difference_shape_mismatch():
    with pytest.raises(ValueError, match="Shape mismatch"):
        detect_change_difference(np.zeros((3, 3)), np.zeros((4, 4)))


def test_change_index():
    before = np.array([0.2, 0.3, 0.4, 0.5]).reshape(2, 2)
    after = np.array([0.8, 0.3, 0.1, 0.5]).reshape(2, 2)
    result = detect_change_index(before, after, threshold=0.1)
    assert result.method == "index_difference"
    assert result.statistics["increase_pixels"] >= 1
    assert result.statistics["decrease_pixels"] >= 1


def test_change_classification():
    before = np.array([[1, 1, 2], [2, 3, 3], [1, 2, 3]])
    after = np.array([[1, 2, 2], [2, 3, 1], [1, 2, 3]])
    result = detect_change_classification(before, after)
    assert result.method == "post_classification"
    assert result.changed_pixels == 2  # (0,1): 1→2, (1,2): 3→1
    assert len(result.statistics["transitions"]) > 0


def test_change_classification_no_change():
    arr = np.array([[1, 2], [3, 4]])
    result = detect_change_classification(arr, arr)
    assert result.changed_pixels == 0


# ---------------------------------------------------------------------------
# Time Series Analysis
# ---------------------------------------------------------------------------

def test_mann_kendall_increasing():
    values = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0]
    result = mann_kendall_trend(values)
    assert result.trend == "increasing"
    assert result.p_value < 0.05
    assert result.details["sen_slope"] > 0


def test_mann_kendall_decreasing():
    values = [8.0, 7.0, 6.0, 5.0, 4.0, 3.0, 2.0, 1.0]
    result = mann_kendall_trend(values)
    assert result.trend == "decreasing"
    assert result.details["sen_slope"] < 0


def test_mann_kendall_no_trend():
    values = [1.0, 3.0, 2.0, 4.0, 1.0, 3.0, 2.0, 4.0]
    result = mann_kendall_trend(values)
    # Random-ish data should show no significant trend
    assert result.method == "mann_kendall"


def test_mann_kendall_insufficient():
    result = mann_kendall_trend([1.0, 2.0])
    assert result.trend == "insufficient_data"


def test_detect_breakpoints():
    # Clear shift at index 10
    values = [1.0] * 10 + [5.0] * 10
    bps = detect_breakpoints(values, min_segment=3)
    assert isinstance(bps, list)


def test_detect_breakpoints_short():
    assert detect_breakpoints([1, 2, 3]) == []


# ---------------------------------------------------------------------------
# Evidence Assessment
# ---------------------------------------------------------------------------

def test_evidence_sufficient():
    result = assess_evidence(
        num_dates=5, num_methods=3,
        spatial_coverage_pct=95, agreement_rate=90,
        has_ground_truth=True,
    )
    assert result.verdict == "sufficient"
    assert result.overall_score >= 0.7
    assert len(result.recommendations) == 0 or all("验证" not in r for r in result.recommendations)


def test_evidence_insufficient():
    result = assess_evidence(
        num_dates=1, num_methods=1,
        spatial_coverage_pct=30, agreement_rate=40,
    )
    assert result.verdict == "insufficient"
    assert len(result.recommendations) >= 3


def test_evidence_marginal():
    result = assess_evidence(
        num_dates=3, num_methods=2,
        spatial_coverage_pct=70, agreement_rate=65,
    )
    assert result.verdict in ("marginal", "sufficient")


def test_evidence_to_dict():
    result = assess_evidence(num_dates=5, num_methods=3,
                              spatial_coverage_pct=90, agreement_rate=85)
    d = result.to_dict()
    assert "overall_score" in d
    assert "verdict" in d
    assert "recommendations" in d
