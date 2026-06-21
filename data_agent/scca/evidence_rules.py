from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np


RULE_VERSION = "scca-evidence-grade-rules-2026-06-20"

GRADE_RULE_FILES = {
    "rules_json": "scca_evidence_grade_rules.json",
    "rules_md": "scca_evidence_grade_rules.md",
}

THRESHOLDS = {
    "max_balance_corr_moderate": 0.50,
    "overlap_boundary_mass_moderate": 0.25,
    "bootstrap_sign_stability_min": 0.80,
    "erf_monotonic_fraction_min": 0.80,
    "material_residual_moran_abs": 0.20,
    "spatial_p_value_max": 0.05,
    "spatial_adjustment_relative_change_max": 0.25,
}

GRADE_RULES = [
    {
        "rule_id": "strong_nonspatial_and_robust",
        "scope": "core_support gate",
        "condition": (
            "credibility_decision == strong_support and "
            "robustness_interpretation == robust_support"
        ),
        "effect": "Required, but not sufficient, for core_support.",
    },
    {
        "rule_id": "moderate_credibility",
        "scope": "credibility",
        "condition": "credibility_decision == moderate_support",
        "effect": "Downgrade final manuscript evidence to bounded_support.",
    },
    {
        "rule_id": "weak_credibility",
        "scope": "credibility",
        "condition": "credibility_decision == weak_or_failed_support",
        "effect": "Downgrade final manuscript evidence to bounded_support.",
    },
    {
        "rule_id": "high_exposure_balance_correlation",
        "scope": "credibility",
        "condition": "max absolute exposure-balance correlation > 0.50",
        "effect": "Downgrade credibility to moderate_support and final evidence to bounded_support.",
    },
    {
        "rule_id": "high_overlap_boundary_mass",
        "scope": "credibility",
        "condition": "exposure boundary mass > 0.25",
        "effect": "Downgrade credibility to moderate_support and final evidence to bounded_support.",
    },
    {
        "rule_id": "bounded_robustness",
        "scope": "robustness",
        "condition": "robustness_interpretation == bounded_support",
        "effect": "Downgrade final manuscript evidence to bounded_support.",
    },
    {
        "rule_id": "fragile_robustness",
        "scope": "robustness",
        "condition": "robustness_interpretation == fragile_support",
        "effect": "Downgrade final manuscript evidence to bounded_support.",
    },
    {
        "rule_id": "material_residual_moran",
        "scope": "spatial diagnostics",
        "condition": (
            "|residual Moran's I| >= 0.20 and permutation p <= 0.05"
        ),
        "effect": "Downgrade final manuscript evidence to bounded_support.",
    },
    {
        "rule_id": "significant_neighbor_exposure",
        "scope": "spatial diagnostics",
        "condition": "neighbor-exposure p <= 0.05 after adjustment",
        "effect": "Downgrade final manuscript evidence to bounded_support.",
    },
    {
        "rule_id": "material_spatial_adjustment_shift",
        "scope": "spatial diagnostics",
        "condition": "max relative main-effect change across spatial adjustments >= 0.25",
        "effect": "Downgrade final manuscript evidence to bounded_support.",
    },
    {
        "rule_id": "graph_sign_unstable",
        "scope": "spatial diagnostics",
        "condition": "graph-sensitivity sign stability is false",
        "effect": "Downgrade final manuscript evidence to bounded_support.",
    },
]


def _finite_float(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if np.isfinite(numeric) else None


def _truthy_false(value: Any) -> bool:
    if isinstance(value, bool):
        return value is False
    if isinstance(value, str):
        return value.strip().lower() in {"false", "0", "no"}
    return False


def _json_ready(value: object) -> object:
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        numeric = float(value)
        return numeric if np.isfinite(numeric) else None
    return value


def assess_scca_evidence_grade(
    *,
    credibility_decision: str | None,
    robustness_interpretation: str | None,
    spatial_summary: dict[str, Any] | None = None,
    max_balance_corr: float | None = None,
    overlap_boundary_mass: float | None = None,
    forced_grade: str | None = None,
) -> dict[str, Any]:
    """Map SCCA diagnostics to a reproducible manuscript evidence grade."""

    if forced_grade in {"negative_ablation", "auxiliary_only"}:
        return {
            "rule_version": RULE_VERSION,
            "evidence_grade": forced_grade,
            "material_spatial_caution": False,
            "triggered_rules": [forced_grade],
            "reasons": [f"Grade is fixed by evidence role: {forced_grade}."],
            "thresholds": THRESHOLDS,
        }

    triggered: list[str] = []
    reasons: list[str] = []
    credibility = str(credibility_decision or "unknown")
    robustness = str(robustness_interpretation or "unknown")
    spatial = spatial_summary or {}
    balance_corr = _finite_float(max_balance_corr)
    boundary_mass = _finite_float(overlap_boundary_mass)

    if credibility == "moderate_support":
        triggered.append("moderate_credibility")
        reasons.append("Credibility diagnostics only support a moderate claim.")
    elif credibility == "weak_or_failed_support":
        triggered.append("weak_credibility")
        reasons.append("Credibility diagnostics indicate weak or failed support.")
    elif credibility != "strong_support":
        triggered.append("unknown_credibility")
        reasons.append(f"Credibility decision is not strong_support ({credibility}).")

    if balance_corr is not None and balance_corr > THRESHOLDS["max_balance_corr_moderate"]:
        triggered.append("high_exposure_balance_correlation")
        reasons.append(
            "Maximum exposure-balance correlation exceeds the threshold "
            f"({balance_corr:.3f} > {THRESHOLDS['max_balance_corr_moderate']:.2f})."
        )

    if boundary_mass is not None and boundary_mass > THRESHOLDS["overlap_boundary_mass_moderate"]:
        triggered.append("high_overlap_boundary_mass")
        reasons.append(
            "Exposure boundary mass exceeds the threshold "
            f"({boundary_mass:.3f} > {THRESHOLDS['overlap_boundary_mass_moderate']:.2f})."
        )

    if robustness == "bounded_support":
        triggered.append("bounded_robustness")
        reasons.append("Robustness checks support only a bounded interpretation.")
    elif robustness == "fragile_support":
        triggered.append("fragile_robustness")
        reasons.append("Robustness checks indicate fragile support.")
    elif robustness != "robust_support":
        triggered.append("unknown_robustness")
        reasons.append(f"Robustness interpretation is not robust_support ({robustness}).")

    residual_moran = _finite_float(spatial.get("residual_moran_i"))
    residual_p = _finite_float(spatial.get("residual_moran_p_value"))
    if (
        residual_moran is not None
        and residual_p is not None
        and abs(residual_moran) >= THRESHOLDS["material_residual_moran_abs"]
        and residual_p <= THRESHOLDS["spatial_p_value_max"]
    ):
        triggered.append("material_residual_moran")
        reasons.append(
            "Residual spatial autocorrelation is both statistically significant "
            f"and materially large (Moran's I={residual_moran:.3f}, p={residual_p:.3f})."
        )

    neighbor_p = _finite_float(spatial.get("neighbor_exposure_p_value"))
    if neighbor_p is not None and neighbor_p <= THRESHOLDS["spatial_p_value_max"]:
        triggered.append("significant_neighbor_exposure")
        reasons.append(
            "Neighboring exposure remains associated with the outcome after adjustment "
            f"(p={neighbor_p:.3f})."
        )

    relative_changes = [
        _finite_float(spatial.get("neighbor_adjusted_relative_change")),
        _finite_float(spatial.get("spatial_lag_relative_change")),
        _finite_float(spatial.get("neighbor_adjusted_relative_change_max")),
        _finite_float(spatial.get("spatial_lag_relative_change_max")),
    ]
    finite_changes = [value for value in relative_changes if value is not None]
    if finite_changes and max(finite_changes) >= THRESHOLDS["spatial_adjustment_relative_change_max"]:
        triggered.append("material_spatial_adjustment_shift")
        reasons.append(
            "Spatial adjustment changes the main effect by at least "
            f"{THRESHOLDS['spatial_adjustment_relative_change_max']:.2f} "
            f"(max relative change={max(finite_changes):.3f})."
        )

    if _truthy_false(spatial.get("neighbor_adjusted_sign_stability")) or _truthy_false(
        spatial.get("spatial_lag_sign_stability")
    ):
        triggered.append("graph_sign_unstable")
        reasons.append("Graph-sensitivity checks do not preserve the effect sign.")

    material_spatial = any(
        rule in triggered
        for rule in (
            "material_residual_moran",
            "significant_neighbor_exposure",
            "material_spatial_adjustment_shift",
            "graph_sign_unstable",
        )
    )
    evidence_grade = "bounded_support" if triggered else "core_support"
    return {
        "rule_version": RULE_VERSION,
        "evidence_grade": evidence_grade,
        "material_spatial_caution": material_spatial,
        "triggered_rules": triggered,
        "reasons": reasons,
        "thresholds": THRESHOLDS,
    }


def evidence_rule_payload() -> dict[str, Any]:
    return {
        "rule_version": RULE_VERSION,
        "grade_meanings": {
            "core_support": (
                "Strong credibility, robust support, and no material spatial caution "
                "under the declared thresholds."
            ),
            "bounded_support": (
                "Useful SCCA evidence with explicit credibility, robustness, support, "
                "or spatial-diagnostic limits."
            ),
            "negative_ablation": (
                "A candidate context source was tested and did not improve the "
                "diagnostic design."
            ),
            "auxiliary_only": (
                "An output may support interpretation or software development but is "
                "not causal evidence for SCCA."
            ),
        },
        "thresholds": THRESHOLDS,
        "rules": GRADE_RULES,
    }


def render_evidence_rule_markdown(payload: dict[str, Any] | None = None) -> str:
    payload = payload or evidence_rule_payload()
    lines = [
        "# SCCA Evidence Grade Rules",
        "",
        f"- Rule version: `{payload['rule_version']}`",
        "",
        "## Grade Meanings",
        "",
    ]
    for grade, meaning in payload["grade_meanings"].items():
        lines.append(f"- `{grade}`: {meaning}")
    lines.extend(["", "## Thresholds", ""])
    for key, value in payload["thresholds"].items():
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Downgrade Rules", ""])
    for rule in payload["rules"]:
        lines.extend(
            [
                f"### `{rule['rule_id']}`",
                "",
                f"- Scope: {rule['scope']}",
                f"- Condition: {rule['condition']}",
                f"- Effect: {rule['effect']}",
                "",
            ]
        )
    return "\n".join(lines)


def write_evidence_rule_outputs(output_dir: str | Path) -> dict[str, str]:
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    payload = evidence_rule_payload()
    json_path = target / GRADE_RULE_FILES["rules_json"]
    md_path = target / GRADE_RULE_FILES["rules_md"]
    json_path.write_text(
        json.dumps(_json_ready(payload), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    md_path.write_text(render_evidence_rule_markdown(payload), encoding="utf-8")
    return {
        "rules_json": str(json_path),
        "rules_md": str(md_path),
        "rule_version": RULE_VERSION,
    }
