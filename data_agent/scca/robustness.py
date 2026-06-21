from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
import statsmodels.api as sm

from .specs import StudySpec


ROBUSTNESS_FILES = {
    "context_ablation": "context_ablation.csv",
    "placebo_tests": "placebo_tests.csv",
    "bootstrap_robustness": "bootstrap_robustness.csv",
    "bootstrap_summary": "bootstrap_summary.json",
    "erf_stability": "erf_stability.json",
    "robustness_report": "robustness_report.md",
    "robustness_manifest": "robustness_manifest.json",
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


def _complete_numeric_frame(frame: pd.DataFrame) -> pd.DataFrame:
    numeric = frame.apply(pd.to_numeric, errors="coerce")
    return numeric.replace([np.inf, -np.inf], np.nan).dropna()


def fit_ols_effect(
    frame: pd.DataFrame,
    outcome: str,
    exposure: str,
    columns: Iterable[str],
) -> dict[str, object]:
    original_n = len(frame)
    model_columns = list(dict.fromkeys([col for col in columns if col in frame.columns]))
    if exposure not in model_columns:
        model_columns.insert(0, exposure)
    required = [outcome, *model_columns]
    missing = [col for col in required if col not in frame.columns]
    if missing:
        return {
            "status": "skipped",
            "coef": np.nan,
            "se": np.nan,
            "p_value": np.nan,
            "ci_lower": np.nan,
            "ci_upper": np.nan,
            "r_squared": np.nan,
            "n": 0,
            "dropped_n": original_n,
            "warnings": [f"Missing columns: {', '.join(missing)}"],
        }

    numeric = _complete_numeric_frame(frame[required])
    dropped_n = original_n - len(numeric)
    if len(numeric) < 3 or numeric[exposure].nunique() < 2:
        return {
            "status": "skipped",
            "coef": np.nan,
            "se": np.nan,
            "p_value": np.nan,
            "ci_lower": np.nan,
            "ci_upper": np.nan,
            "r_squared": np.nan,
            "n": int(len(numeric)),
            "dropped_n": int(dropped_n),
            "warnings": ["Too few complete rows or no exposure variation."],
        }

    x = sm.add_constant(numeric[model_columns], has_constant="add").astype(float)
    y = numeric[outcome].astype(float)
    warnings_: list[str] = []
    status = "ok"
    try:
        rank = int(np.linalg.matrix_rank(x.to_numpy(dtype=float)))
        if rank < x.shape[1]:
            warnings_.append("Design matrix rank is lower than number of columns.")
            status = "unstable"
        model = sm.OLS(y, x, missing="drop").fit()
        conf_int = model.conf_int()
    except Exception as exc:
        return {
            "status": "unstable",
            "coef": np.nan,
            "se": np.nan,
            "p_value": np.nan,
            "ci_lower": np.nan,
            "ci_upper": np.nan,
            "r_squared": np.nan,
            "n": int(len(numeric)),
            "dropped_n": int(dropped_n),
            "warnings": [*warnings_, f"OLS fit failed: {exc}"],
        }

    def finite(value: object) -> float:
        try:
            numeric_value = float(value)
        except (TypeError, ValueError):
            return np.nan
        return numeric_value if np.isfinite(numeric_value) else np.nan

    coef = finite(model.params.get(exposure, np.nan))
    se = finite(model.bse.get(exposure, np.nan))
    p_value = finite(model.pvalues.get(exposure, np.nan))
    ci_lower = finite(conf_int.loc[exposure, 0]) if exposure in conf_int.index else np.nan
    ci_upper = finite(conf_int.loc[exposure, 1]) if exposure in conf_int.index else np.nan
    r_squared = finite(model.rsquared)
    if not np.isfinite(coef):
        status = "unstable"
        warnings_.append("Exposure coefficient is non-finite.")
    return {
        "status": status,
        "coef": coef,
        "se": se,
        "p_value": p_value,
        "ci_lower": ci_lower,
        "ci_upper": ci_upper,
        "r_squared": r_squared,
        "n": int(model.nobs),
        "dropped_n": int(dropped_n),
        "warnings": warnings_,
    }


def _available(features: pd.DataFrame, columns: Iterable[str]) -> list[str]:
    return [col for col in columns if col in features.columns]


def run_context_ablation(features: pd.DataFrame, spec: StudySpec, case_name: str) -> pd.DataFrame:
    confounders = _available(features, spec.confounders)
    context = _available(features, spec.context_columns)
    specs = {
        "exposure_only": [],
        "confounders_only": confounders,
        "context_only": context,
        "confounders_plus_context": list(dict.fromkeys([*confounders, *context])),
    }
    rows: list[dict[str, object]] = []
    for name, covariates in specs.items():
        included = [spec.exposure, *covariates]
        result = fit_ols_effect(features, spec.outcome, spec.exposure, included)
        rows.append(
            {
                "case": case_name,
                "specification": name,
                "estimator": "baseline_adjusted_ols",
                "coef": result["coef"],
                "se": result["se"],
                "p_value": result["p_value"],
                "ci_lower": result["ci_lower"],
                "ci_upper": result["ci_upper"],
                "r_squared": result["r_squared"],
                "n": result["n"],
                "included_columns": ",".join(included),
                "status": result["status"],
            }
        )
    return pd.DataFrame(rows)


def run_placebo_tests(
    features: pd.DataFrame,
    spec: StudySpec,
    case_name: str,
    tests: Iterable[dict[str, str]],
) -> pd.DataFrame:
    covariates = list(dict.fromkeys(_available(features, [*spec.confounders, *spec.context_columns])))
    rows: list[dict[str, object]] = []
    for test in tests:
        exposure = test["exposure"]
        result = fit_ols_effect(features, spec.outcome, exposure, [exposure, *covariates])
        coef = result["coef"]
        interpretation = "not_estimable"
        if result["status"] == "ok" and np.isfinite(float(coef)):
            interpretation = "estimated"
        rows.append(
            {
                "case": case_name,
                "test_name": test.get("test_name", exposure),
                "exposure": exposure,
                "role": test.get("role", "placebo"),
                "expected_relation": test.get("expected_relation", "weaker_than_main"),
                "estimator": "baseline_adjusted_ols",
                "coef": coef,
                "se": result["se"],
                "p_value": result["p_value"],
                "ci_lower": result["ci_lower"],
                "ci_upper": result["ci_upper"],
                "n": result["n"],
                "status": result["status"],
                "interpretation": interpretation,
            }
        )
    return pd.DataFrame(rows)


def make_quantile_grid_groups(features: pd.DataFrame, x_col: str, y_col: str, bins: int = 4) -> pd.Series:
    x_bins = pd.qcut(pd.to_numeric(features[x_col], errors="coerce"), q=bins, duplicates="drop")
    y_bins = pd.qcut(pd.to_numeric(features[y_col], errors="coerce"), q=bins, duplicates="drop")
    return x_bins.astype(str) + "|" + y_bins.astype(str)


def run_group_bootstrap(
    features: pd.DataFrame,
    spec: StudySpec,
    case_name: str,
    group_column: str,
    n_replicates: int = 200,
    random_state: int = 0,
) -> tuple[pd.DataFrame, dict[str, object]]:
    rng = np.random.default_rng(random_state)
    groups = pd.Series(features[group_column]).dropna().astype(str).unique()
    covariates = list(dict.fromkeys(_available(features, [*spec.confounders, *spec.context_columns])))
    rows: list[dict[str, object]] = []
    if len(groups) == 0:
        bootstrap_rows = pd.DataFrame(
            columns=["case", "bootstrap_type", "replicate", "coef", "n", "status"]
        )
        return bootstrap_rows, summarize_bootstrap(bootstrap_rows, case_name, group_column, n_replicates)

    for replicate in range(n_replicates):
        sampled = rng.choice(groups, size=len(groups), replace=True)
        parts = [features.loc[features[group_column].astype(str) == group] for group in sampled]
        sample = pd.concat(parts, ignore_index=True) if parts else features.iloc[0:0].copy()
        result = fit_ols_effect(sample, spec.outcome, spec.exposure, [spec.exposure, *covariates])
        rows.append(
            {
                "case": case_name,
                "bootstrap_type": group_column,
                "replicate": replicate,
                "coef": result["coef"],
                "n": result["n"],
                "status": result["status"],
            }
        )
    bootstrap_rows = pd.DataFrame(rows)
    return bootstrap_rows, summarize_bootstrap(bootstrap_rows, case_name, group_column, n_replicates)


def summarize_bootstrap(
    rows: pd.DataFrame,
    case_name: str,
    bootstrap_type: str,
    n_replicates_requested: int,
) -> dict[str, object]:
    if rows.empty:
        finite = pd.Series(dtype=float)
        failure_count = int(n_replicates_requested)
    else:
        coefs = pd.to_numeric(rows["coef"], errors="coerce")
        finite = coefs[np.isfinite(coefs)]
        failure_count = int(n_replicates_requested - len(finite))
    if finite.empty:
        return {
            "case": case_name,
            "bootstrap_type": bootstrap_type,
            "n_replicates_requested": int(n_replicates_requested),
            "n_replicates_valid": 0,
            "coef_mean": None,
            "coef_median": None,
            "coef_std": None,
            "ci_lower_2_5": None,
            "ci_upper_97_5": None,
            "sign_stability": 0.0,
            "failure_count": failure_count,
        }
    signs = np.sign(finite)
    nonzero = signs[signs != 0]
    if nonzero.empty:
        sign_stability = 1.0
    else:
        sign_stability = float((nonzero == nonzero.mode().iloc[0]).mean())
    return {
        "case": case_name,
        "bootstrap_type": bootstrap_type,
        "n_replicates_requested": int(n_replicates_requested),
        "n_replicates_valid": int(len(finite)),
        "coef_mean": float(finite.mean()),
        "coef_median": float(finite.median()),
        "coef_std": float(finite.std(ddof=1)) if len(finite) > 1 else 0.0,
        "ci_lower_2_5": float(finite.quantile(0.025)),
        "ci_upper_97_5": float(finite.quantile(0.975)),
        "sign_stability": sign_stability,
        "failure_count": failure_count,
    }


def summarize_erf_stability(erf_curve: pd.DataFrame, case_name: str) -> dict[str, object]:
    curve = erf_curve[["exposure", "response"]].apply(pd.to_numeric, errors="coerce").dropna()
    if curve.empty:
        return {
            "case": case_name,
            "n_grid": 0,
            "response_at_min_exposure": None,
            "response_at_median_exposure": None,
            "response_at_max_exposure": None,
            "range_effect": None,
            "median_split_effect": None,
            "monotonic_direction": "not_estimable",
            "monotonic_fraction": 0.0,
            "max_adjacent_response_jump": None,
            "interpretation": "ERF curve is not estimable.",
        }
    curve = curve.sort_values("exposure").reset_index(drop=True)
    responses = curve["response"]
    diffs = responses.diff().dropna()
    positive = int((diffs > 0).sum())
    negative = int((diffs < 0).sum())
    total = int(len(diffs))
    if total == 0:
        direction = "flat"
        fraction = 1.0
    elif positive >= negative and positive > 0:
        direction = "increasing"
        fraction = positive / total
    elif negative > positive:
        direction = "decreasing"
        fraction = negative / total
    else:
        direction = "flat"
        fraction = 1.0
    mid = len(curve) // 2
    range_effect = float(responses.iloc[-1] - responses.iloc[0])
    median_split_effect = float(responses.iloc[-1] - responses.iloc[mid])
    jump = float(diffs.abs().max()) if total else 0.0
    interpretation = f"ERF is mostly {direction} with monotonic fraction {fraction:.3f}."
    return {
        "case": case_name,
        "n_grid": int(len(curve)),
        "response_at_min_exposure": float(responses.iloc[0]),
        "response_at_median_exposure": float(responses.iloc[mid]),
        "response_at_max_exposure": float(responses.iloc[-1]),
        "range_effect": range_effect,
        "median_split_effect": median_split_effect,
        "monotonic_direction": direction,
        "monotonic_fraction": float(fraction),
        "max_adjacent_response_jump": jump,
        "interpretation": interpretation,
    }


def _direction_stable(ablation: pd.DataFrame) -> bool:
    coefs = pd.to_numeric(ablation.loc[ablation["status"] == "ok", "coef"], errors="coerce")
    coefs = coefs[np.isfinite(coefs)]
    signs = np.sign(coefs)
    signs = signs[signs != 0]
    return bool(not signs.empty and signs.nunique() == 1)


def _placebo_weaker(ablation: pd.DataFrame, placebo: pd.DataFrame) -> bool:
    main = ablation.loc[ablation["specification"] == "confounders_plus_context", "coef"]
    if main.empty:
        return False
    main_abs = abs(float(main.iloc[0]))
    placebo_coefs = pd.to_numeric(placebo.get("coef", pd.Series(dtype=float)), errors="coerce")
    placebo_abs = placebo_coefs[np.isfinite(placebo_coefs)].abs()
    if placebo_abs.empty:
        return True
    return bool(placebo_abs.max() < main_abs)


def classify_robustness(
    original_decision: str,
    ablation: pd.DataFrame,
    placebo: pd.DataFrame,
    bootstrap_summary: dict[str, object],
    erf_summary: dict[str, object],
    main_limitation: str,
) -> dict[str, object]:
    ablation_stable = _direction_stable(ablation)
    placebo_weaker = _placebo_weaker(ablation, placebo)
    sign_stability = float(bootstrap_summary.get("sign_stability") or 0.0)
    monotonic_fraction = float(erf_summary.get("monotonic_fraction") or 0.0)
    erf_direction = str(erf_summary.get("monotonic_direction") or "not_estimable")

    if not placebo_weaker or sign_stability < 0.8:
        interpretation = "fragile_support"
    elif original_decision == "strong_support" and ablation_stable and monotonic_fraction >= 0.8:
        interpretation = "robust_support"
    else:
        interpretation = "bounded_support"
    reasons = []
    if not ablation_stable:
        reasons.append("Ablation specifications are not directionally stable.")
    if not placebo_weaker:
        reasons.append("At least one placebo or competing exposure is not weaker than the main estimate.")
    if sign_stability < 0.8:
        reasons.append(f"Bootstrap sign stability is below threshold ({sign_stability:.3f}).")
    if monotonic_fraction < 0.8:
        reasons.append(f"ERF monotonic fraction is below threshold ({monotonic_fraction:.3f}).")
    if not reasons:
        reasons.append("Ablation, placebo, bootstrap, and ERF checks support the current interpretation.")
    return {
        "robustness_interpretation": interpretation,
        "ablation_direction_stable": ablation_stable,
        "placebo_weaker_than_main": placebo_weaker,
        "bootstrap_sign_stability": sign_stability,
        "erf_monotonic_direction": erf_direction,
        "main_limitation": main_limitation,
        "reasons": reasons,
    }


def write_robustness_outputs(
    output_dir: str | Path,
    case_name: str,
    original_decision: str,
    main_coef: float,
    main_limitation: str,
    ablation: pd.DataFrame,
    placebo: pd.DataFrame,
    bootstrap_rows: pd.DataFrame,
    bootstrap_summary: dict[str, object],
    erf_summary: dict[str, object],
) -> dict[str, object]:
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    ablation.to_csv(target / ROBUSTNESS_FILES["context_ablation"], index=False)
    placebo.to_csv(target / ROBUSTNESS_FILES["placebo_tests"], index=False)
    bootstrap_rows.to_csv(target / ROBUSTNESS_FILES["bootstrap_robustness"], index=False)
    (target / ROBUSTNESS_FILES["bootstrap_summary"]).write_text(
        json.dumps(_json_ready(bootstrap_summary), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (target / ROBUSTNESS_FILES["erf_stability"]).write_text(
        json.dumps(_json_ready(erf_summary), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    classification = classify_robustness(
        original_decision,
        ablation,
        placebo,
        bootstrap_summary,
        erf_summary,
        main_limitation,
    )
    report = f"""# SCCA Robustness Report

## Case

`{case_name}`

## Interpretation

`{classification["robustness_interpretation"]}`

## Main Result

- Original decision: `{original_decision}`
- Main coefficient: `{main_coef}`
- Main limitation: {main_limitation}

## Robustness Checks

- Ablation direction stable: `{classification["ablation_direction_stable"]}`
- Placebo weaker than main: `{classification["placebo_weaker_than_main"]}`
- Bootstrap sign stability: `{classification["bootstrap_sign_stability"]}`
- ERF monotonic direction: `{classification["erf_monotonic_direction"]}`

## Reasons

{chr(10).join(f"- {reason}" for reason in classification["reasons"])}
"""
    (target / ROBUSTNESS_FILES["robustness_report"]).write_text(report, encoding="utf-8")
    manifest = {
        "case": case_name,
        "original_decision": original_decision,
        "main_coef": main_coef,
        **classification,
        "files": ROBUSTNESS_FILES,
    }
    (target / ROBUSTNESS_FILES["robustness_manifest"]).write_text(
        json.dumps(_json_ready(manifest), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return manifest


def write_cross_case_summary(case_manifests: Iterable[dict[str, object]], output_dir: str | Path) -> dict[str, object]:
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    rows = []
    for manifest in case_manifests:
        rows.append(
            {
                "case": manifest.get("case"),
                "original_decision": manifest.get("original_decision"),
                "robustness_interpretation": manifest.get("robustness_interpretation"),
                "main_coef": manifest.get("main_coef"),
                "ablation_direction_stable": manifest.get("ablation_direction_stable"),
                "placebo_weaker_than_main": manifest.get("placebo_weaker_than_main"),
                "bootstrap_sign_stability": manifest.get("bootstrap_sign_stability"),
                "erf_monotonic_direction": manifest.get("erf_monotonic_direction"),
                "main_limitation": manifest.get("main_limitation"),
            }
        )
    summary = pd.DataFrame(rows)
    csv_name = "case_robustness_summary.csv"
    report_name = "case_robustness_report.md"
    summary.to_csv(target / csv_name, index=False)
    report_lines = ["# SCCA Cross-Case Robustness Summary", ""]
    for row in rows:
        report_lines.append(
            f"- `{row['case']}`: `{row['robustness_interpretation']}` "
            f"(original `{row['original_decision']}`, bootstrap sign stability "
            f"`{row['bootstrap_sign_stability']}`)."
        )
    (target / report_name).write_text("\n".join(report_lines) + "\n", encoding="utf-8")
    manifest = {
        "cases": [row["case"] for row in rows],
        "files": {
            "case_robustness_summary": csv_name,
            "case_robustness_report": report_name,
        },
    }
    (target / "manifest.json").write_text(
        json.dumps(_json_ready(manifest), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return manifest
