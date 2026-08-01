"""Shared outcome-time metrics for online expert comparisons."""

from __future__ import annotations


def external_regret_to_best_fixed_constituent(
    *,
    algorithm_errors: list[float],
    v4_errors: list[float],
    wwm_errors: list[float],
) -> dict[str, float | None]:
    """Return squared-loss external regret along the issue-time prefix axis."""

    if not algorithm_errors:
        return {
            "final_cumulative_m6s2": None,
            "final_average_per_case_m6s2": None,
            "maximum_prefix_cumulative_m6s2": None,
            "minimum_prefix_cumulative_m6s2": None,
        }
    algorithm_loss = 0.0
    v4_loss = 0.0
    wwm_loss = 0.0
    prefix_regrets = []
    for algorithm_error, v4_error, wwm_error in zip(
        algorithm_errors,
        v4_errors,
        wwm_errors,
        strict=True,
    ):
        algorithm_loss += algorithm_error**2
        v4_loss += v4_error**2
        wwm_loss += wwm_error**2
        prefix_regrets.append(algorithm_loss - min(v4_loss, wwm_loss))
    final = prefix_regrets[-1]
    return {
        "final_cumulative_m6s2": final,
        "final_average_per_case_m6s2": final / len(prefix_regrets),
        "maximum_prefix_cumulative_m6s2": max(prefix_regrets),
        "minimum_prefix_cumulative_m6s2": min(prefix_regrets),
    }
