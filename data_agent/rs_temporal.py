"""
Remote Sensing Phase 2 — Spatiotemporal Analysis (v22.0).

Change detection, time series analysis, and evidence sufficiency assessment
for multi-temporal remote sensing data analysis.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from .observability import get_logger

logger = get_logger("rs_temporal")


# ---------------------------------------------------------------------------
# Change Detection Engine
# ---------------------------------------------------------------------------


@dataclass
class ChangeDetectionResult:
    """Result of a change detection analysis."""
    method: str
    changed_area_pct: float
    total_pixels: int
    changed_pixels: int
    change_map: Optional[np.ndarray] = None
    statistics: dict = field(default_factory=dict)
    description: str = ""

    def to_dict(self) -> dict:
        return {
            "method": self.method,
            "changed_area_pct": round(self.changed_area_pct, 2),
            "total_pixels": self.total_pixels,
            "changed_pixels": self.changed_pixels,
            "statistics": self.statistics,
            "description": self.description,
        }


def detect_change_difference(before: np.ndarray, after: np.ndarray,
                              threshold: float = 0.15) -> ChangeDetectionResult:
    """Bi-temporal difference change detection.

    Computes pixel-wise absolute difference and thresholds to identify change.
    Works with single-band (e.g., NDVI) or multi-band imagery.
    """
    if before.shape != after.shape:
        raise ValueError(f"Shape mismatch: {before.shape} vs {after.shape}")

    diff = np.abs(after.astype(np.float64) - before.astype(np.float64))
    if diff.ndim == 3:
        diff = np.mean(diff, axis=2)  # average across bands

    change_mask = diff > threshold
    total = change_mask.size
    changed = int(np.sum(change_mask))

    return ChangeDetectionResult(
        method="bi_temporal_difference",
        changed_area_pct=changed / total * 100 if total > 0 else 0,
        total_pixels=total,
        changed_pixels=changed,
        change_map=change_mask,
        statistics={
            "mean_diff": float(np.mean(diff)),
            "max_diff": float(np.max(diff)),
            "std_diff": float(np.std(diff)),
            "threshold": threshold,
        },
        description=f"双时相差异检测: {changed}/{total} 像素变化 ({changed/total*100:.1f}%)",
    )


def detect_change_index(before_index: np.ndarray, after_index: np.ndarray,
                         threshold: float = 0.1) -> ChangeDetectionResult:
    """Index-based change detection (e.g., NDVI difference).

    Computes the difference of spectral indices between two dates.
    Positive = increase, negative = decrease.
    """
    diff = after_index.astype(np.float64) - before_index.astype(np.float64)
    change_mask = np.abs(diff) > threshold
    total = change_mask.size
    changed = int(np.sum(change_mask))

    increase = int(np.sum(diff > threshold))
    decrease = int(np.sum(diff < -threshold))

    return ChangeDetectionResult(
        method="index_difference",
        changed_area_pct=changed / total * 100 if total > 0 else 0,
        total_pixels=total,
        changed_pixels=changed,
        change_map=change_mask,
        statistics={
            "mean_change": float(np.mean(diff)),
            "increase_pixels": increase,
            "decrease_pixels": decrease,
            "threshold": threshold,
        },
        description=f"指数差异检测: 增加 {increase}, 减少 {decrease}, 总变化 {changed} 像素",
    )


def detect_change_classification(before_classes: np.ndarray,
                                  after_classes: np.ndarray) -> ChangeDetectionResult:
    """Post-classification comparison change detection.

    Compares classified land cover maps from two dates.
    """
    if before_classes.shape != after_classes.shape:
        raise ValueError("Shape mismatch")

    change_mask = before_classes != after_classes
    total = change_mask.size
    changed = int(np.sum(change_mask))

    # Compute transition matrix
    unique_classes = np.unique(np.concatenate([before_classes.ravel(), after_classes.ravel()]))
    transitions = {}
    for from_cls in unique_classes:
        for to_cls in unique_classes:
            if from_cls == to_cls:
                continue
            count = int(np.sum((before_classes == from_cls) & (after_classes == to_cls)))
            if count > 0:
                transitions[f"{int(from_cls)}→{int(to_cls)}"] = count

    return ChangeDetectionResult(
        method="post_classification",
        changed_area_pct=changed / total * 100 if total > 0 else 0,
        total_pixels=total,
        changed_pixels=changed,
        change_map=change_mask,
        statistics={
            "num_classes": len(unique_classes),
            "transitions": transitions,
        },
        description=f"分类后比较: {len(transitions)} 种转换类型, {changed} 像素变化",
    )


# ---------------------------------------------------------------------------
# Time Series Analysis
# ---------------------------------------------------------------------------


@dataclass
class TimeSeriesResult:
    """Result of a time series analysis."""
    method: str
    trend: str  # increasing / decreasing / stable / no_trend
    statistic: float
    p_value: float
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "method": self.method,
            "trend": self.trend,
            "statistic": round(self.statistic, 4),
            "p_value": round(self.p_value, 6),
            "details": self.details,
        }


def mann_kendall_trend(values: list[float], alpha: float = 0.05) -> TimeSeriesResult:
    """Mann-Kendall trend test for monotonic trend detection.

    Non-parametric test suitable for environmental time series.
    """
    n = len(values)
    if n < 4:
        return TimeSeriesResult(
            method="mann_kendall", trend="insufficient_data",
            statistic=0.0, p_value=1.0,
            details={"n": n, "error": "需要至少 4 个数据点"},
        )

    # Compute S statistic
    s = 0
    for i in range(n - 1):
        for j in range(i + 1, n):
            diff = values[j] - values[i]
            if diff > 0:
                s += 1
            elif diff < 0:
                s -= 1

    # Variance of S
    var_s = n * (n - 1) * (2 * n + 5) / 18.0

    # Z statistic
    if s > 0:
        z = (s - 1) / (var_s ** 0.5) if var_s > 0 else 0
    elif s < 0:
        z = (s + 1) / (var_s ** 0.5) if var_s > 0 else 0
    else:
        z = 0

    # Two-tailed p-value (normal approximation)
    from math import erfc
    p_value = erfc(abs(z) / (2 ** 0.5))

    if p_value <= alpha:
        trend = "increasing" if s > 0 else "decreasing"
    else:
        trend = "no_trend"

    # Sen's slope estimate
    slopes = []
    for i in range(n - 1):
        for j in range(i + 1, n):
            if j != i:
                slopes.append((values[j] - values[i]) / (j - i))
    sen_slope = float(np.median(slopes)) if slopes else 0.0

    return TimeSeriesResult(
        method="mann_kendall",
        trend=trend,
        statistic=z,
        p_value=p_value,
        details={
            "s_statistic": s,
            "z_statistic": round(z, 4),
            "sen_slope": round(sen_slope, 6),
            "n": n,
            "alpha": alpha,
        },
    )


def detect_breakpoints(values: list[float], min_segment: int = 3) -> list[int]:
    """Simple breakpoint detection using cumulative sum (CUSUM).

    Returns indices where significant shifts occur.
    """
    if len(values) < min_segment * 2:
        return []

    arr = np.array(values, dtype=np.float64)
    mean_val = np.mean(arr)
    cusum = np.cumsum(arr - mean_val)

    # Find points where CUSUM deviates most from linear trend
    breakpoints = []
    threshold = np.std(cusum) * 1.5

    for i in range(min_segment, len(cusum) - min_segment):
        local_range = cusum[max(0, i-min_segment):min(len(cusum), i+min_segment)]
        if abs(cusum[i] - np.mean(local_range)) > threshold:
            # Check it's a local extremum
            if i > 0 and i < len(cusum) - 1:
                if (cusum[i] > cusum[i-1] and cusum[i] > cusum[i+1]) or \
                   (cusum[i] < cusum[i-1] and cusum[i] < cusum[i+1]):
                    breakpoints.append(i)

    return breakpoints


# ---------------------------------------------------------------------------
# Evidence Sufficiency Assessment
# ---------------------------------------------------------------------------


@dataclass
class EvidenceAssessment:
    """Assessment of evidence sufficiency for a conclusion."""
    overall_score: float  # 0-1
    data_coverage: float  # 0-1
    method_diversity: float  # 0-1
    conclusion_strength: float  # 0-1
    verdict: str  # sufficient / marginal / insufficient
    recommendations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "overall_score": round(self.overall_score, 3),
            "data_coverage": round(self.data_coverage, 3),
            "method_diversity": round(self.method_diversity, 3),
            "conclusion_strength": round(self.conclusion_strength, 3),
            "verdict": self.verdict,
            "recommendations": self.recommendations,
        }


def assess_evidence(
    num_dates: int,
    num_methods: int,
    spatial_coverage_pct: float,
    agreement_rate: float,
    has_ground_truth: bool = False,
) -> EvidenceAssessment:
    """Assess whether evidence is sufficient to support a conclusion.

    Args:
        num_dates: Number of temporal observations
        num_methods: Number of analysis methods applied
        spatial_coverage_pct: % of study area covered (0-100)
        agreement_rate: % agreement between methods (0-100)
        has_ground_truth: Whether ground truth validation exists
    """
    # Data coverage: temporal × spatial
    temporal_score = min(1.0, num_dates / 5.0)  # 5+ dates = full score
    spatial_score = spatial_coverage_pct / 100.0
    data_coverage = temporal_score * 0.5 + spatial_score * 0.5

    # Method diversity
    method_diversity = min(1.0, num_methods / 3.0)  # 3+ methods = full score

    # Conclusion strength: agreement + ground truth bonus
    conclusion_strength = agreement_rate / 100.0
    if has_ground_truth:
        conclusion_strength = min(1.0, conclusion_strength * 1.2)

    # Overall = weighted combination
    overall = data_coverage * 0.3 + method_diversity * 0.3 + conclusion_strength * 0.4

    # Verdict
    if overall >= 0.7:
        verdict = "sufficient"
    elif overall >= 0.4:
        verdict = "marginal"
    else:
        verdict = "insufficient"

    # Recommendations
    recs = []
    if num_dates < 3:
        recs.append("增加时间序列观测点 (建议 ≥3 期)")
    if num_methods < 2:
        recs.append("使用多种分析方法交叉验证")
    if spatial_coverage_pct < 80:
        recs.append(f"提高空间覆盖率 (当前 {spatial_coverage_pct:.0f}%, 建议 ≥80%)")
    if agreement_rate < 70:
        recs.append("方法间一致性较低，检查数据质量或方法适用性")
    if not has_ground_truth:
        recs.append("建议引入地面真值数据进行验证")

    return EvidenceAssessment(
        overall_score=overall,
        data_coverage=data_coverage,
        method_diversity=method_diversity,
        conclusion_strength=conclusion_strength,
        verdict=verdict,
        recommendations=recs,
    )
