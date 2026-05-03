"""Exact McNemar test for paired binary outcomes.

`base` and `full` are aligned per-question 0/1 EX outcomes. The exact
binomial test is used so the result is valid for small samples (e.g. our
20-question GIS pilot).
"""
from __future__ import annotations

from math import comb


def mcnemar_paired(base: list[int], full: list[int]) -> dict:
    if len(base) != len(full):
        raise ValueError("paired sequences must have equal length")
    b = sum(1 for x, y in zip(base, full) if x == 1 and y == 0)
    c = sum(1 for x, y in zip(base, full) if x == 0 and y == 1)
    n = b + c
    if n == 0:
        return {"b": 0, "c": 0, "p_value": 1.0}
    k = min(b, c)
    # two-sided exact binomial probability
    p = sum(comb(n, i) for i in range(k + 1)) / (2 ** n) * 2
    return {"b": b, "c": c, "p_value": min(1.0, p)}
