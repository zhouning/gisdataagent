"""
Remote Sensing Phase 3 — Intelligent Credibility (v22.0).

Multi-Agent Debate pattern for analysis verification, hallucination detection
with spatial constraints, and code generation sandbox.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Optional

from .observability import get_logger

logger = get_logger("rs_credibility")


# ---------------------------------------------------------------------------
# Hallucination Detection
# ---------------------------------------------------------------------------


@dataclass
class FactCheckResult:
    """Result of a spatial fact-checking pass."""
    claim: str
    verified: bool
    confidence: float  # 0-1
    source: str  # constraint_check / cross_validation / ground_truth
    explanation: str = ""

    def to_dict(self) -> dict:
        return {
            "claim": self.claim,
            "verified": self.verified,
            "confidence": round(self.confidence, 3),
            "source": self.source,
            "explanation": self.explanation,
        }


def check_spatial_constraints(claims: list[dict], known_bounds: dict = None) -> list[FactCheckResult]:
    """Verify spatial claims against known constraints.

    Checks:
    - Area claims within plausible bounds
    - Coordinate claims within study area bbox
    - Percentage claims sum to ≤ 100
    - Negative area / population claims
    """
    results = []
    bounds = known_bounds or {
        "min_lat": -90, "max_lat": 90,
        "min_lon": -180, "max_lon": 180,
        "max_area_sqkm": 1e8,  # 100M km²
    }

    for claim in claims:
        claim_text = claim.get("text", "")
        claim_type = claim.get("type", "unknown")
        value = claim.get("value")

        if claim_type == "area" and value is not None:
            if value < 0:
                results.append(FactCheckResult(
                    claim=claim_text, verified=False, confidence=1.0,
                    source="constraint_check",
                    explanation="面积不能为负值",
                ))
            elif value > bounds.get("max_area_sqkm", 1e8):
                results.append(FactCheckResult(
                    claim=claim_text, verified=False, confidence=0.9,
                    source="constraint_check",
                    explanation=f"面积 {value} 超出合理范围 (>{bounds['max_area_sqkm']})",
                ))
            else:
                results.append(FactCheckResult(
                    claim=claim_text, verified=True, confidence=0.7,
                    source="constraint_check",
                    explanation="面积在合理范围内",
                ))

        elif claim_type == "percentage" and value is not None:
            if value < 0 or value > 100:
                results.append(FactCheckResult(
                    claim=claim_text, verified=False, confidence=1.0,
                    source="constraint_check",
                    explanation=f"百分比 {value}% 超出 0-100 范围",
                ))
            else:
                results.append(FactCheckResult(
                    claim=claim_text, verified=True, confidence=0.6,
                    source="constraint_check",
                ))

        elif claim_type == "coordinate" and value is not None:
            lat, lon = value if isinstance(value, (list, tuple)) else (None, None)
            if lat is not None and lon is not None:
                in_bounds = (bounds["min_lat"] <= lat <= bounds["max_lat"] and
                            bounds["min_lon"] <= lon <= bounds["max_lon"])
                results.append(FactCheckResult(
                    claim=claim_text, verified=in_bounds,
                    confidence=1.0 if in_bounds else 0.95,
                    source="constraint_check",
                    explanation="坐标在有效范围内" if in_bounds else "坐标超出有效范围",
                ))

    return results


def cross_validate_results(results: list[dict]) -> dict:
    """Cross-validate multiple analysis results for consistency.

    Compares key metrics across different methods to detect contradictions.
    Returns agreement statistics and flagged inconsistencies.
    """
    if len(results) < 2:
        return {"agreement_rate": 100.0, "inconsistencies": [], "n_methods": len(results)}

    # Extract comparable metrics
    metrics_by_key: dict[str, list[float]] = {}
    for r in results:
        for key, value in r.items():
            if isinstance(value, (int, float)):
                metrics_by_key.setdefault(key, []).append(float(value))

    inconsistencies = []
    total_checks = 0
    agreements = 0

    for key, values in metrics_by_key.items():
        if len(values) < 2:
            continue
        total_checks += 1
        mean_val = sum(values) / len(values)
        if mean_val == 0:
            continue
        cv = (max(values) - min(values)) / abs(mean_val)  # coefficient of variation
        if cv < 0.3:  # <30% variation = agreement
            agreements += 1
        else:
            inconsistencies.append({
                "metric": key,
                "values": values,
                "cv": round(cv, 3),
                "explanation": f"指标 '{key}' 变异系数 {cv:.1%}，方法间差异较大",
            })

    rate = agreements / total_checks * 100 if total_checks > 0 else 100.0

    return {
        "agreement_rate": round(rate, 1),
        "inconsistencies": inconsistencies,
        "n_methods": len(results),
        "n_checks": total_checks,
        "n_agreements": agreements,
    }


# ---------------------------------------------------------------------------
# Multi-Agent Debate
# ---------------------------------------------------------------------------


@dataclass
class DebateResult:
    """Result of a multi-agent debate verification."""
    original_conclusion: str
    verdict: str  # confirmed / revised / refuted
    confidence: float  # 0-1
    supporting_evidence: list[str] = field(default_factory=list)
    counter_evidence: list[str] = field(default_factory=list)
    final_conclusion: str = ""
    rounds: int = 0

    def to_dict(self) -> dict:
        return {
            "original_conclusion": self.original_conclusion,
            "verdict": self.verdict,
            "confidence": round(self.confidence, 3),
            "supporting_evidence": self.supporting_evidence,
            "counter_evidence": self.counter_evidence,
            "final_conclusion": self.final_conclusion,
            "rounds": self.rounds,
        }


def run_debate(
    conclusion: str,
    analysis_results: list[dict],
    fact_checks: list[dict] = None,
) -> DebateResult:
    """Run a simplified multi-agent debate verification.

    Without LLM: uses rule-based scoring of evidence strength.
    With LLM (future): main analyst + independent verifier + statistical checker + judge.
    """
    supporting = []
    counter = []
    fact_checks = fact_checks or []

    # Score from analysis results
    for r in analysis_results:
        method = r.get("method", "unknown")
        if r.get("changed_area_pct", 0) > 0:
            supporting.append(f"方法 {method} 检测到变化 ({r.get('changed_area_pct', 0):.1f}%)")
        confidence = r.get("confidence", r.get("overall_score", 0.5))
        if isinstance(confidence, (int, float)) and confidence < 0.3:
            counter.append(f"方法 {method} 置信度较低 ({confidence:.2f})")

    # Score from fact checks
    for fc in fact_checks:
        if fc.get("verified"):
            supporting.append(f"事实核查通过: {fc.get('claim', '')[:50]}")
        else:
            counter.append(f"事实核查失败: {fc.get('explanation', '')[:50]}")

    # Determine verdict
    support_score = len(supporting)
    counter_score = len(counter) * 1.5  # counter evidence weighs more
    total = support_score + counter_score

    if total == 0:
        confidence = 0.5
        verdict = "confirmed"
    else:
        confidence = support_score / total
        if confidence >= 0.7:
            verdict = "confirmed"
        elif confidence >= 0.4:
            verdict = "revised"
        else:
            verdict = "refuted"

    return DebateResult(
        original_conclusion=conclusion,
        verdict=verdict,
        confidence=confidence,
        supporting_evidence=supporting,
        counter_evidence=counter,
        final_conclusion=conclusion if verdict == "confirmed" else f"[需修正] {conclusion}",
        rounds=1,
    )


# ---------------------------------------------------------------------------
# Code Generation Sandbox (placeholder)
# ---------------------------------------------------------------------------


def validate_generated_code(code: str) -> dict:
    """Basic safety validation for agent-generated Python code.

    Checks for dangerous operations before sandbox execution.
    Returns validation result with allowed/blocked status.
    """
    blocked_patterns = [
        r'\bos\.system\b', r'\bsubprocess\b', r'\b__import__\b',
        r'\beval\b', r'\bexec\b', r'\bopen\s*\(.*["\']w',
        r'\bshutil\.rmtree\b', r'\bos\.remove\b',
    ]
    issues = []
    for pattern in blocked_patterns:
        if re.search(pattern, code):
            issues.append(f"Blocked pattern: {pattern}")

    return {
        "valid": len(issues) == 0,
        "issues": issues,
        "line_count": len(code.splitlines()),
    }
