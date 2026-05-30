"""Exact two-sided binomial bootstrap CI for EX accuracy.

Given a list of 0/1 outcomes (EX correct/incorrect), produce a 95% CI on
the mean (== execution accuracy).

Methods:
- Wilson score CI (analytic, no resampling) — fast, accurate for small n
- Percentile bootstrap (B=10_000) — for cross-check; makes no normality assumption
"""
from __future__ import annotations

import math
import random


def wilson_ci(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson score interval. z=1.96 → 95%."""
    if n == 0:
        return (0.0, 1.0)
    p = successes / n
    denom = 1 + z**2 / n
    centre = p + z**2 / (2 * n)
    half = z * math.sqrt((p * (1 - p) + z**2 / (4 * n)) / n)
    return (max(0.0, (centre - half) / denom), min(1.0, (centre + half) / denom))


def bootstrap_ci(outcomes: list[int], B: int = 10_000, seed: int = 42) -> tuple[float, float]:
    """Percentile bootstrap 95% CI on the mean."""
    if not outcomes:
        return (0.0, 1.0)
    rng = random.Random(seed)
    n = len(outcomes)
    means = []
    for _ in range(B):
        sample = [outcomes[rng.randrange(n)] for _ in range(n)]
        means.append(sum(sample) / n)
    means.sort()
    lo = means[int(0.025 * B)]
    hi = means[int(0.975 * B)]
    return (lo, hi)


def format_with_ci(successes: int, n: int) -> str:
    """Produce 'EX 0.XXX [low, high]' string using Wilson CI."""
    if n == 0:
        return "n/a"
    p = successes / n
    lo, hi = wilson_ci(successes, n)
    return f"{p:.3f} [{lo:.3f}, {hi:.3f}]"
