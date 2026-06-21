from __future__ import annotations

import json

import pandas as pd

from .specs import SCCAPaths, StudySpec


def select_design(df: pd.DataFrame, spec: StudySpec, paths: SCCAPaths) -> dict[str, object]:
    """Select the first SCCA design from explicit study metadata."""

    paths.ensure()
    exposure = pd.to_numeric(df[spec.exposure], errors="coerce")
    unique_exposure = int(exposure.nunique(dropna=True))
    baseline_available = bool(spec.baseline_outcome and spec.baseline_outcome in df.columns)
    warnings: list[str] = []

    if len(df) < 50:
        warnings.append(
            f"Small sample: n={len(df)}. Keep models low-dimensional and interpret uncertainty cautiously."
        )
    if unique_exposure <= 2:
        design = "binary_exposure_adjusted_regression"
        estimators = ["baseline_adjusted_ols"]
    else:
        design = "continuous_exposure_baseline_adjusted"
        estimators = ["baseline_adjusted_ols", "generalized_propensity_erf"]

    if baseline_available:
        estimators.append("difference_outcome_ols")

    if spec.baseline_outcome is None:
        warnings.append("No baseline outcome configured; difference-outcome checks will be skipped.")
    elif not baseline_available:
        warnings.append(
            f"Baseline outcome column '{spec.baseline_outcome}' is missing; difference-outcome checks will be skipped."
        )
    if spec.subgroup_column is None:
        warnings.append("No subgroup column configured; leave-one-group-out robustness will be skipped.")

    plan = {
        "study": spec.name,
        "design": design,
        "n_rows": int(len(df)),
        "unique_exposure_values": unique_exposure,
        "exposure": spec.exposure,
        "outcome": spec.outcome,
        "baseline_outcome": spec.baseline_outcome,
        "estimators": estimators,
        "warnings": warnings,
    }
    paths.design_plan.write_text(
        json.dumps(plan, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return plan
