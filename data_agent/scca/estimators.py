from __future__ import annotations

import json
import warnings

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy.stats import gaussian_kde
from sklearn.ensemble import GradientBoostingRegressor

from .specs import SCCAPaths, StudySpec


def _available_columns(features: pd.DataFrame, columns: tuple[str, ...]) -> list[str]:
    return [col for col in columns if col in features.columns]


def _model_covariates(features: pd.DataFrame, spec: StudySpec) -> tuple[list[str], list[str]]:
    covariates = _available_columns(features, spec.confounders)
    context_columns = _available_columns(features, spec.context_columns)
    ordered = list(dict.fromkeys(covariates + context_columns))
    return ordered, context_columns


def _complete_numeric_frame(frame: pd.DataFrame) -> pd.DataFrame:
    numeric = frame.apply(pd.to_numeric, errors="coerce")
    return numeric.replace([np.inf, -np.inf], np.nan).dropna()


def _nan_effect(
    *,
    status: str,
    n: int,
    complete_n: int,
    dropped_n: int,
    warnings_: list[str],
) -> dict[str, object]:
    return {
        "status": status,
        "coef": np.nan,
        "se": np.nan,
        "p_value": np.nan,
        "ci_lower": np.nan,
        "ci_upper": np.nan,
        "r_squared": np.nan,
        "n": int(n),
        "complete_n": int(complete_n),
        "dropped_n": int(dropped_n),
        "warnings": warnings_,
    }


def _finite_or_nan(value: object) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return np.nan
    return numeric if np.isfinite(numeric) else np.nan


def _range_effect_inference(
    model: sm.regression.linear_model.RegressionResultsWrapper,
    exposure_name: str,
    exposure_min: float,
    exposure_max: float,
) -> tuple[float, float, float]:
    params = getattr(model, "params", pd.Series(dtype=float))
    if exposure_name not in params.index:
        return np.nan, np.nan, np.nan
    try:
        contrast = np.zeros(len(params), dtype=float)
        contrast[list(params.index).index(exposure_name)] = exposure_max - exposure_min
        test = model.t_test(contrast)
        se = _finite_or_nan(np.ravel(test.sd)[0])
        ci = np.asarray(test.conf_int(alpha=0.05), dtype=float).reshape(-1, 2)
        ci_lower = _finite_or_nan(ci[0, 0])
        ci_upper = _finite_or_nan(ci[0, 1])
    except Exception:
        return np.nan, np.nan, np.nan
    return se, ci_lower, ci_upper


def _ols_effect(
    features: pd.DataFrame,
    outcome_name: str,
    design_columns: list[str],
    exposure_name: str,
) -> dict[str, object]:
    original_n = len(features)
    messages: list[str] = []
    if exposure_name not in features.columns:
        return _nan_effect(
            status="skipped",
            n=0,
            complete_n=0,
            dropped_n=original_n,
            warnings_=[f"Exposure column '{exposure_name}' is missing."],
        )
    if outcome_name not in features.columns:
        return _nan_effect(
            status="skipped",
            n=0,
            complete_n=0,
            dropped_n=original_n,
            warnings_=[f"Outcome column '{outcome_name}' is missing."],
        )

    columns = list(dict.fromkeys([col for col in design_columns if col in features.columns]))
    if exposure_name not in columns:
        columns.insert(0, exposure_name)
    frame = _complete_numeric_frame(pd.concat([features[outcome_name].rename("__y__"), features[columns]], axis=1))
    complete_n = len(frame)
    dropped_n = original_n - complete_n
    if complete_n < 2:
        return _nan_effect(
            status="skipped",
            n=complete_n,
            complete_n=complete_n,
            dropped_n=dropped_n,
            warnings_=["Fewer than 2 complete rows for OLS effect estimation."],
        )

    x_const = sm.add_constant(frame.drop(columns=["__y__"]), has_constant="add").astype(float)
    y = frame["__y__"].astype(float)
    rank = int(np.linalg.matrix_rank(x_const.to_numpy(dtype=float)))
    if rank < x_const.shape[1]:
        messages.append("Design matrix rank is lower than the number of columns.")

    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", RuntimeWarning)
            model = sm.OLS(y, x_const, missing="drop").fit()
            conf_int = model.conf_int()
        for warning in caught:
            messages.append(str(warning.message))
    except Exception as exc:
        return _nan_effect(
            status="unstable",
            n=complete_n,
            complete_n=complete_n,
            dropped_n=dropped_n,
            warnings_=[*messages, f"OLS fit failed: {exc}"],
        )

    coef = _finite_or_nan(model.params.get(exposure_name, np.nan))
    se = _finite_or_nan(model.bse.get(exposure_name, np.nan))
    p_value = _finite_or_nan(model.pvalues.get(exposure_name, np.nan))
    ci_lower = _finite_or_nan(conf_int.loc[exposure_name, 0]) if exposure_name in conf_int.index else np.nan
    ci_upper = _finite_or_nan(conf_int.loc[exposure_name, 1]) if exposure_name in conf_int.index else np.nan
    r_squared = _finite_or_nan(model.rsquared)

    if model.df_resid <= 0:
        messages.append("Residual degrees of freedom are non-positive.")
    if not all(np.isfinite(value) for value in [se, p_value, ci_lower, ci_upper]):
        messages.append("One or more OLS inference statistics are non-finite.")
    status = "unstable" if messages else "ok"
    return {
        "status": status,
        "coef": coef,
        "se": se,
        "p_value": p_value,
        "ci_lower": ci_lower,
        "ci_upper": ci_upper,
        "r_squared": r_squared,
        "n": int(model.nobs),
        "complete_n": complete_n,
        "dropped_n": dropped_n,
        "warnings": messages,
    }


def _gps_weights(features: pd.DataFrame, spec: StudySpec, covariates: list[str]) -> tuple[pd.Series, dict[str, object]]:
    weights = pd.Series(1.0, index=features.index, dtype=float)
    diagnostics: dict[str, object] = {"gps_fit_n": 0, "gps_fallback_reason": None}
    if spec.exposure not in features.columns:
        diagnostics["gps_fallback_reason"] = f"Exposure column '{spec.exposure}' is missing."
        return weights, diagnostics
    if len(features) < 3:
        diagnostics["gps_fallback_reason"] = "Fewer than 3 rows available for GPS fitting."
        return weights, diagnostics
    if not covariates:
        diagnostics["gps_fallback_reason"] = "No covariates available for GPS fitting."
        return weights, diagnostics

    frame = _complete_numeric_frame(features[[spec.exposure, *covariates]])
    diagnostics["gps_fit_n"] = int(len(frame))
    if len(frame) < 3:
        diagnostics["gps_fallback_reason"] = "Fewer than 3 complete rows available for GPS fitting."
        return weights, diagnostics
    if frame[spec.exposure].nunique() < 2:
        diagnostics["gps_fallback_reason"] = "Exposure has no variation for GPS fitting."
        return weights, diagnostics

    try:
        model = GradientBoostingRegressor(random_state=0)
        x = frame[covariates].astype(float)
        exposure = frame[spec.exposure].astype(float)
        model.fit(x, exposure)
        residuals = exposure - model.predict(x)
        residual_sd = float(np.std(residuals, ddof=1))
        if not np.isfinite(residual_sd) or residual_sd <= 0:
            diagnostics["gps_fallback_reason"] = "GPS residual standard deviation is non-positive."
            return weights, diagnostics

        density = gaussian_kde(residuals)(residuals)
        conditional = np.maximum(density, np.finfo(float).eps)
        raw = 1.0 / conditional
        raw = np.where(np.isfinite(raw), raw, np.nan)
        mean = np.nanmean(raw)
        if not np.isfinite(mean) or mean <= 0:
            diagnostics["gps_fallback_reason"] = "GPS raw weights have no finite positive mean."
            return weights, diagnostics

        weights.loc[frame.index] = raw / mean
        weights = weights.replace([np.inf, -np.inf], np.nan).fillna(1.0)
        overall_mean = float(weights.mean())
        if np.isfinite(overall_mean) and overall_mean > 0:
            weights = weights / overall_mean
    except Exception as exc:
        diagnostics["gps_fallback_reason"] = f"GPS fitting failed: {exc}"
        return pd.Series(1.0, index=features.index, dtype=float), diagnostics
    return weights.astype(float), diagnostics


def _erf_curve(features: pd.DataFrame, spec: StudySpec, weights: pd.Series) -> tuple[pd.DataFrame, dict[str, object]]:
    if spec.exposure not in features.columns or spec.outcome not in features.columns:
        return (
            pd.DataFrame({"exposure": [np.nan], "response": [np.nan], "ci_lower": [np.nan], "ci_upper": [np.nan]}),
            {
                "status": "skipped",
                "erf_n": 0,
                "dropped_n": len(features),
                "range_effect": np.nan,
                "range_effect_se": np.nan,
                "range_effect_ci_lower": np.nan,
                "range_effect_ci_upper": np.nan,
                "response_min_exposure": np.nan,
                "response_max_exposure": np.nan,
                "warnings": ["Exposure or outcome column is missing for ERF estimation."],
            },
        )

    frame = _complete_numeric_frame(features[[spec.exposure, spec.outcome]])
    dropped_n = len(features) - len(frame)
    if frame.empty:
        return (
            pd.DataFrame({"exposure": [np.nan], "response": [np.nan], "ci_lower": [np.nan], "ci_upper": [np.nan]}),
            {
                "status": "skipped",
                "erf_n": 0,
                "dropped_n": dropped_n,
                "range_effect": np.nan,
                "range_effect_se": np.nan,
                "range_effect_ci_lower": np.nan,
                "range_effect_ci_upper": np.nan,
                "response_min_exposure": np.nan,
                "response_max_exposure": np.nan,
                "warnings": ["No complete exposure/outcome rows for ERF estimation."],
            },
        )

    exposure = frame[spec.exposure].astype(float)
    grid = np.linspace(float(exposure.min()), float(exposure.max()), 50)
    status = "ok"
    messages: list[str] = []
    if len(frame) < 2 or exposure.nunique() < 2:
        response = np.repeat(float(frame[spec.outcome].mean()), len(grid))
        ci_lower_curve = np.repeat(np.nan, len(grid))
        ci_upper_curve = np.repeat(np.nan, len(grid))
        range_se = range_ci_lower = range_ci_upper = np.nan
        status = "unstable"
        messages.append("ERF used mean response fallback due to sparse rows or no exposure variation.")
    else:
        try:
            aligned_weights = weights.reindex(frame.index).astype(float)
            aligned_weights = aligned_weights.replace([np.inf, -np.inf], np.nan).fillna(1.0)
            x_const = sm.add_constant(exposure.rename(spec.exposure), has_constant="add")
            grid_const = sm.add_constant(pd.Series(grid, name=spec.exposure), has_constant="add")
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always", RuntimeWarning)
                model = sm.WLS(frame[spec.outcome].astype(float), x_const.astype(float), weights=aligned_weights).fit()
                prediction = model.get_prediction(grid_const.astype(float))
                prediction_frame = prediction.summary_frame(alpha=0.05)
                response = prediction_frame["mean"].to_numpy(dtype=float)
                ci_lower_curve = prediction_frame["mean_ci_lower"].to_numpy(dtype=float)
                ci_upper_curve = prediction_frame["mean_ci_upper"].to_numpy(dtype=float)
                range_se, range_ci_lower, range_ci_upper = _range_effect_inference(
                    model,
                    spec.exposure,
                    float(grid[0]),
                    float(grid[-1]),
                )
            for warning in caught:
                messages.append(str(warning.message))
        except Exception as exc:
            response = np.repeat(np.nan, len(grid))
            ci_lower_curve = np.repeat(np.nan, len(grid))
            ci_upper_curve = np.repeat(np.nan, len(grid))
            range_se = range_ci_lower = range_ci_upper = np.nan
            status = "unstable"
            messages.append(f"ERF fit failed: {exc}")

    response_array = np.asarray(response, dtype=float)
    response_min = _finite_or_nan(response_array[0]) if len(response_array) else np.nan
    response_max = _finite_or_nan(response_array[-1]) if len(response_array) else np.nan
    range_effect = _finite_or_nan(response_max - response_min)
    return (
        pd.DataFrame(
            {
                "exposure": grid,
                "response": response_array,
                "ci_lower": np.asarray(ci_lower_curve, dtype=float),
                "ci_upper": np.asarray(ci_upper_curve, dtype=float),
            }
        ),
        {
            "status": status,
            "erf_n": int(len(frame)),
            "dropped_n": int(dropped_n),
            "range_effect": range_effect,
            "range_effect_se": range_se,
            "range_effect_ci_lower": range_ci_lower,
            "range_effect_ci_upper": range_ci_upper,
            "response_min_exposure": response_min,
            "response_max_exposure": response_max,
            "warnings": messages,
        },
    )


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


def estimate_effects(
    features: pd.DataFrame,
    spec: StudySpec,
    paths: SCCAPaths,
) -> dict[str, object]:
    paths.ensure()
    covariates, context_columns = _model_covariates(features, spec)
    results: dict[str, object] = {}
    estimates: list[dict[str, object]] = []

    baseline_columns = [spec.exposure, *covariates]
    baseline = _ols_effect(features, spec.outcome, baseline_columns, spec.exposure)
    results["baseline_adjusted_ols"] = baseline
    estimates.append({"estimator": "baseline_adjusted_ols", **baseline})

    if "outcome_change" in features.columns:
        difference = _ols_effect(features, "outcome_change", baseline_columns, spec.exposure)
        results["difference_outcome_ols"] = difference
        estimates.append({"estimator": "difference_outcome_ols", **difference})

    weights, gps_diagnostics = _gps_weights(features, spec, covariates)
    erf, erf_result = _erf_curve(features, spec, weights)
    gps_result = {
        "status": erf_result["status"],
        "coef": erf_result["range_effect"],
        "se": erf_result["range_effect_se"],
        "p_value": np.nan,
        "ci_lower": erf_result["range_effect_ci_lower"],
        "ci_upper": erf_result["range_effect_ci_upper"],
        "r_squared": np.nan,
        "n": int(erf_result["erf_n"]),
        "n_grid": int(len(erf)),
        "complete_n": int(erf_result["erf_n"]),
        "dropped_n": int(erf_result["dropped_n"]),
        "warnings": erf_result["warnings"],
        "weight_min": float(weights.min()),
        "weight_max": float(weights.max()),
        "weight_mean": float(weights.mean()),
        "range_effect": erf_result["range_effect"],
        "response_min_exposure": erf_result["response_min_exposure"],
        "response_max_exposure": erf_result["response_max_exposure"],
        **gps_diagnostics,
    }
    results["generalized_propensity_erf"] = gps_result
    estimates.append(
        {
            "estimator": "generalized_propensity_erf",
            **{
                key: gps_result[key]
                for key in [
                    "status",
                    "coef",
                    "se",
                    "p_value",
                    "ci_lower",
                    "ci_upper",
                    "r_squared",
                    "n",
                    "dropped_n",
                ]
            },
        }
    )

    pd.DataFrame(estimates).to_csv(paths.effect_estimates, index=False)
    erf.to_csv(paths.erf_curve, index=False)
    diagnostics = {
        "original_n": int(len(features)),
        "covariates": covariates,
        "context_columns": context_columns,
        "gps_weight_min": gps_result["weight_min"],
        "gps_weight_max": gps_result["weight_max"],
        "gps_weight_mean": gps_result["weight_mean"],
        "gps_fit_n": gps_result["gps_fit_n"],
        "gps_fallback_reason": gps_result["gps_fallback_reason"],
        "erf_n": gps_result["n"],
        "erf_grid_n": gps_result["n_grid"],
        "estimators": {
            name: {
                "status": value["status"],
                "n": int(value["n"]),
                "complete_n": int(value.get("complete_n", value["n"])),
                "dropped_n": int(value.get("dropped_n", 0)),
                "warnings": value.get("warnings", []),
            }
            for name, value in results.items()
            if isinstance(value, dict) and "n" in value and "status" in value
        },
    }
    paths.model_diagnostics.write_text(
        json.dumps(_json_ready(diagnostics), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return results
