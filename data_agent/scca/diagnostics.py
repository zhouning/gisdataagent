from __future__ import annotations

import json

import numpy as np
import pandas as pd
import statsmodels.api as sm

from .evidence_rules import assess_scca_evidence_grade
from .specs import SCCAPaths, StudySpec


DECISIONS = ("weak_or_failed_support", "moderate_support", "strong_support")
CORE_ESTIMATORS = {
    "baseline_adjusted_ols",
    "difference_outcome_ols",
    "generalized_propensity_erf",
}


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


def _corr_abs(a: pd.Series, b: pd.Series) -> float:
    a_num = pd.to_numeric(a, errors="coerce")
    b_num = pd.to_numeric(b, errors="coerce")
    valid = a_num.notna() & b_num.notna()
    if valid.sum() < 3 or a_num[valid].nunique() < 2 or b_num[valid].nunique() < 2:
        return 0.0
    value = np.corrcoef(a_num[valid], b_num[valid])[0, 1]
    return float(abs(value)) if np.isfinite(value) else 0.0


def _available_balance_columns(features: pd.DataFrame, spec: StudySpec) -> list[str]:
    candidates = list(dict.fromkeys([*spec.confounders, *spec.context_columns]))
    return [col for col in candidates if col in features.columns]


def _write_balance_summary(features: pd.DataFrame, spec: StudySpec, paths: SCCAPaths) -> float:
    rows = []
    exposure = features.get(spec.exposure)
    for col in _available_balance_columns(features, spec):
        corr = _corr_abs(exposure, features[col]) if exposure is not None else 0.0
        rows.append({"variable": col, "abs_corr_with_exposure": corr})
    balance = pd.DataFrame(rows, columns=["variable", "abs_corr_with_exposure"])
    balance.to_csv(paths.balance_summary, index=False)
    if balance.empty:
        return 0.0
    max_corr = pd.to_numeric(balance["abs_corr_with_exposure"], errors="coerce").max()
    return float(max_corr) if np.isfinite(max_corr) else 0.0


def _write_overlap_summary(features: pd.DataFrame, spec: StudySpec, paths: SCCAPaths) -> dict[str, object]:
    exposure = pd.to_numeric(features.get(spec.exposure, pd.Series(dtype=float)), errors="coerce").dropna()
    n = int(len(exposure))
    if n == 0:
        summary: dict[str, object] = {
            "n": 0,
            "exposure_min": None,
            "exposure_max": None,
            "exposure_unique": 0,
            "exposure_analyzable": False,
            "share_at_min": None,
            "share_at_max": None,
            "boundary_mass": None,
        }
    else:
        exposure_min = float(exposure.min())
        exposure_max = float(exposure.max())
        share_at_min = float((exposure == exposure_min).mean())
        share_at_max = float((exposure == exposure_max).mean())
        summary = {
            "n": n,
            "exposure_min": exposure_min,
            "exposure_max": exposure_max,
            "exposure_unique": int(exposure.nunique()),
            "exposure_analyzable": bool(n >= 2 and exposure.nunique() >= 2),
            "share_at_min": share_at_min,
            "share_at_max": share_at_max,
            "boundary_mass": float(max(share_at_min, share_at_max)),
        }
    paths.overlap_summary.write_text(
        json.dumps(_json_ready(summary), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return summary


def _model_columns(features: pd.DataFrame, spec: StudySpec) -> list[str]:
    candidates = list(dict.fromkeys([spec.exposure, *spec.confounders, *spec.context_columns]))
    return [col for col in candidates if col in features.columns]


def _fit_leave_group_coef(frame: pd.DataFrame, spec: StudySpec, columns: list[str]) -> float:
    if spec.exposure not in columns or spec.outcome not in frame.columns:
        return np.nan
    numeric = frame[[spec.outcome, *columns]].apply(pd.to_numeric, errors="coerce")
    numeric = numeric.replace([np.inf, -np.inf], np.nan).dropna()
    if len(numeric) < 3 or numeric[spec.exposure].nunique() < 2:
        return np.nan

    x = sm.add_constant(numeric[columns], has_constant="add").astype(float)
    y = numeric[spec.outcome].astype(float)
    if x.shape[1] > len(numeric):
        return np.nan
    try:
        rank = int(np.linalg.matrix_rank(x.to_numpy(dtype=float)))
    except Exception:
        return np.nan
    if rank < x.shape[1]:
        return np.nan

    try:
        model = sm.OLS(y, x, missing="drop").fit()
    except Exception:
        return np.nan
    coef = model.params.get(spec.exposure, np.nan)
    return float(coef) if np.isfinite(coef) else np.nan


def _write_spatial_robustness(features: pd.DataFrame, spec: StudySpec, paths: SCCAPaths) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    columns = _model_columns(features, spec)
    if spec.subgroup_column and spec.subgroup_column in features.columns:
        groups = features[spec.subgroup_column].dropna().astype(str).unique()
        for group in sorted(groups):
            kept = features.loc[features[spec.subgroup_column].astype(str) != group]
            rows.append(
                {
                    "group": group,
                    "coef": _fit_leave_group_coef(kept, spec, columns),
                    "n": int(len(kept)),
                }
            )
    robustness = pd.DataFrame(rows, columns=["group", "coef", "n"])
    robustness.to_csv(paths.spatial_robustness, index=False)
    return robustness


def _load_estimator_statuses(paths: SCCAPaths) -> dict[str, str]:
    if not paths.model_diagnostics.exists():
        return {}
    try:
        diagnostics = json.loads(paths.model_diagnostics.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    estimators = diagnostics.get("estimators", {})
    if not isinstance(estimators, dict):
        return {}
    statuses: dict[str, str] = {}
    for name, details in estimators.items():
        if not isinstance(details, dict):
            continue
        status = details.get("status")
        if isinstance(status, str) and name in CORE_ESTIMATORS:
            statuses[name] = status
    return statuses


def _load_spatial_diagnostics(paths: SCCAPaths) -> dict[str, object]:
    if not paths.spatial_diagnostics.exists():
        return {}
    try:
        diagnostics = json.loads(paths.spatial_diagnostics.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return diagnostics if isinstance(diagnostics, dict) else {}


def _stable_leave_group_signs(robustness: pd.DataFrame) -> bool | None:
    if robustness.empty or "coef" not in robustness.columns:
        return None
    coefs = pd.to_numeric(robustness["coef"], errors="coerce")
    finite = coefs[np.isfinite(coefs)]
    if finite.empty:
        return None
    signs = np.sign(finite)
    signs = signs[signs != 0]
    if signs.empty:
        return True
    return bool(signs.nunique() <= 1)


def _downgrade(current: str, target: str) -> str:
    return DECISIONS[min(DECISIONS.index(current), DECISIONS.index(target))]


def audit_effects(
    features: pd.DataFrame,
    spec: StudySpec,
    paths: SCCAPaths,
) -> dict[str, object]:
    paths.ensure()
    max_balance_corr = _write_balance_summary(features, spec, paths)
    overlap = _write_overlap_summary(features, spec, paths)
    robustness = _write_spatial_robustness(features, spec, paths)
    statuses = _load_estimator_statuses(paths)
    spatial_diagnostics = _load_spatial_diagnostics(paths)

    decision = "strong_support"
    reasons: list[str] = []
    exposure_n = overlap.get("n")
    exposure_unique = overlap.get("exposure_unique")
    exposure_analyzable = bool(
        isinstance(exposure_n, (int, float))
        and isinstance(exposure_unique, (int, float))
        and exposure_n >= 2
        and exposure_unique >= 2
    )
    if not exposure_analyzable:
        decision = _downgrade(decision, "weak_or_failed_support")
        reasons.append("No analyzable exposure support is available for credibility auditing.")

    boundary_mass = overlap.get("boundary_mass")
    if isinstance(boundary_mass, (int, float)) and np.isfinite(boundary_mass) and boundary_mass > 0.25:
        decision = _downgrade(decision, "moderate_support")
        reasons.append(f"Exposure boundary mass is high ({boundary_mass:.3f}).")
    if max_balance_corr > 0.5:
        decision = _downgrade(decision, "moderate_support")
        reasons.append(f"Maximum exposure-balance correlation is high ({max_balance_corr:.3f}).")

    sign_stable = _stable_leave_group_signs(robustness)
    if sign_stable is False:
        decision = _downgrade(decision, "weak_or_failed_support")
        reasons.append("Leave-one-subgroup-out coefficients do not have stable signs.")
    if (
        spec.subgroup_column
        and spec.subgroup_column in features.columns
        and not robustness.empty
        and "coef" in robustness.columns
    ):
        coefs = pd.to_numeric(robustness["coef"], errors="coerce")
        finite_count = int(np.isfinite(coefs).sum())
        nan_count = int(coefs.isna().sum())
        if nan_count > 0 and finite_count == 0:
            decision = _downgrade(decision, "weak_or_failed_support")
            reasons.append("Leave-one-subgroup-out spatial robustness is not estimable.")
        elif nan_count > 0:
            decision = _downgrade(decision, "moderate_support")
            reasons.append(
                "Leave-one-subgroup-out spatial robustness is incomplete because some folds are not estimable."
            )

    unstable = sorted(name for name, status in statuses.items() if status == "unstable")
    if unstable:
        decision = _downgrade(decision, "moderate_support")
        reasons.append(f"Core estimator status is unstable: {', '.join(unstable)}.")

    skipped = sorted(name for name, status in statuses.items() if status == "skipped")
    if skipped:
        decision = _downgrade(decision, "weak_or_failed_support")
        reasons.append(f"Core estimator status is skipped: {', '.join(skipped)}.")

    spatial_flags = spatial_diagnostics.get("flags")
    if isinstance(spatial_flags, list):
        for flag in spatial_flags:
            if isinstance(flag, str) and flag.strip():
                decision = _downgrade(decision, "moderate_support")
                reasons.append(flag)

    if not reasons:
        reasons.append("No credibility downgrade warnings were triggered.")

    graph_sensitivity: dict[str, object] = {}
    if paths.spatial_graph_sensitivity_summary.exists():
        try:
            loaded = json.loads(paths.spatial_graph_sensitivity_summary.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                graph_sensitivity = loaded
        except (OSError, json.JSONDecodeError):
            graph_sensitivity = {}
    residual = spatial_diagnostics.get("residual_moran", {})
    neighbor = spatial_diagnostics.get("neighbor_exposure_model", {})
    lag = spatial_diagnostics.get("spatial_lag_model", {})
    evidence_assessment = assess_scca_evidence_grade(
        credibility_decision=decision,
        robustness_interpretation="robust_support",
        max_balance_corr=max_balance_corr,
        overlap_boundary_mass=boundary_mass if isinstance(boundary_mass, (int, float)) else None,
        spatial_summary={
            "residual_moran_i": residual.get("moran_i") if isinstance(residual, dict) else None,
            "residual_moran_p_value": residual.get("permutation_p_value") if isinstance(residual, dict) else None,
            "neighbor_exposure_p_value": neighbor.get("p_value") if isinstance(neighbor, dict) else None,
            "neighbor_adjusted_relative_change": (
                neighbor.get("spatial_adjustment_sensitivity", {}).get("relative_change")
                if isinstance(neighbor, dict)
                and isinstance(neighbor.get("spatial_adjustment_sensitivity"), dict)
                else None
            ),
            "spatial_lag_relative_change": (
                lag.get("spatial_adjustment_sensitivity", {}).get("relative_change")
                if isinstance(lag, dict)
                and isinstance(lag.get("spatial_adjustment_sensitivity"), dict)
                else None
            ),
            "neighbor_adjusted_relative_change_max": graph_sensitivity.get(
                "neighbor_adjusted_relative_change_max"
            ),
            "spatial_lag_relative_change_max": graph_sensitivity.get("spatial_lag_relative_change_max"),
            "neighbor_adjusted_sign_stability": graph_sensitivity.get(
                "neighbor_adjusted_sign_stability"
            ),
            "spatial_lag_sign_stability": graph_sensitivity.get("spatial_lag_sign_stability"),
        },
    )
    report: dict[str, object] = {
        "decision": decision,
        "reasons": reasons,
        "evidence_grade": evidence_assessment["evidence_grade"],
        "evidence_grade_rule_ids": evidence_assessment["triggered_rules"],
        "evidence_grade_reasons": evidence_assessment["reasons"],
        "rule_version": evidence_assessment["rule_version"],
        "max_balance_corr": max_balance_corr,
        "overlap_boundary_mass": boundary_mass,
        "leave_group_sign_stable": sign_stable,
        "estimator_statuses": statuses,
        "spatial_diagnostics": spatial_diagnostics,
    }
    paths.credibility_report.write_text(
        json.dumps(_json_ready(report), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return report
