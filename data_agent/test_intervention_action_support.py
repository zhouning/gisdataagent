import numpy as np
import pytest

from data_agent.uwm.intervention_action_support import analyze_action_support


def test_componentwise_support_does_not_imply_row_span_support():
    development = np.array([[0.0, 0.0], [2.0, 2.0]])
    target = np.array([1.5, 0.5])

    result = analyze_action_support(development, target, ["a", "b"])

    assert result["componentwise_support_pass"] is True
    assert result["rank"] == 1
    assert result["row_span"]["pass"] is False
    assert result["null_space_witness"]["available"] is True
    assert result["null_space_witness"]["max_abs_observed_action_dot"] < 1e-8
    assert result["null_space_witness"]["target_action_dot"] > 0


def test_row_span_support_does_not_imply_convex_support():
    development = np.array([[1.0, 0.0], [0.0, 1.0]])
    target = np.array([2.0, -1.0])

    result = analyze_action_support(development, target, ["a", "b"])

    assert result["row_span"]["pass"] is True
    assert result["affine_hull"]["pass"] is True
    assert result["convex_hull"]["pass"] is False
    assert result["null_space_witness"]["available"] is False


def test_convex_combination_passes_all_geometric_support_levels():
    development = np.array([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]])
    target = np.array([0.25, 0.50])

    result = analyze_action_support(development, target, ["a", "b"])

    assert result["full_column_rank"] is True
    assert result["row_span"]["pass"] is True
    assert result["affine_hull"]["pass"] is True
    assert result["convex_hull"]["pass"] is True


def test_invalid_designs_are_rejected():
    with pytest.raises(ValueError, match="feature dimensions"):
        analyze_action_support(np.ones((2, 2)), np.ones(3), ["a", "b"])

    with pytest.raises(ValueError, match="unique"):
        analyze_action_support(np.ones((2, 2)), np.ones(2), ["a", "a"])

    with pytest.raises(ValueError, match="positive"):
        analyze_action_support(
            np.ones((2, 2)), np.ones(2), ["a", "b"], tolerance=0
        )
