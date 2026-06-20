from __future__ import annotations

import math
from typing import Any

from .spatial_causal_estimator import build_neighbor_edges, estimate_spatial_treatment_effect
from .utils import safe_float, truthy


CAUSAL_CALIBRATION_BACKEND_SCHEMA = "territory_world_model.causal_calibration_backend.v1"


def estimate_observational_treatment_effect(records: list[dict[str, Any]], *, thresholds: dict[str, Any]) -> dict[str, Any]:
    """Estimate a local observational treatment effect with audit diagnostics.

    The backend reports three transparent estimators and uses augmented IPW as
    the primary effect only when treatment/control support and overlap exist.
    It is still observational calibration, not a randomized causal proof.
    """
    usable = _usable_records(records, thresholds)
    treated = [row for row in usable if row["treatment"] == 1]
    control = [row for row in usable if row["treatment"] == 0]
    naive_effect = _weighted_mean([row["outcome"] for row in treated], [row["evidence_weight"] for row in treated]) - _weighted_mean(
        [row["outcome"] for row in control],
        [row["evidence_weight"] for row in control],
    ) if treated and control else 0.0

    propensity = _assign_propensity_scores(usable, thresholds)
    strata, stratified_effect, stratified_se = _stratified_effect(usable, treated)
    ipw_effect, ipw_se, ess = _ipw_ate(usable)
    aipw_effect, aipw_se, influence = _augmented_ipw_ate(usable)
    balance = _covariate_balance(usable)
    overlap = _overlap_diagnostics(usable, thresholds)
    neighbor_edges = build_neighbor_edges(usable, thresholds)
    spatial = _spatial_interference_diagnostics(usable, influence, thresholds, neighbor_edges=neighbor_edges)
    spatial_estimator = estimate_spatial_treatment_effect(
        usable,
        thresholds=thresholds,
        neighbor_edges=neighbor_edges,
        observational_effect=aipw_effect,
        observational_standard_error=aipw_se,
    )

    primary_name, primary_effect, primary_se = _primary_estimator(
        naive_effect=naive_effect,
        stratified_effect=stratified_effect,
        stratified_se=stratified_se,
        ipw_effect=ipw_effect,
        ipw_se=ipw_se,
        aipw_effect=aipw_effect,
        aipw_se=aipw_se,
        usable_count=len(usable),
        treated_count=len(treated),
        control_count=len(control),
        thresholds=thresholds,
        overlap=overlap,
        spatial_estimator=spatial_estimator,
    )
    model_effects = [safe_float(row.get("model_effect"), None) for row in usable]
    model_effects = [float(item) for item in model_effects if item is not None]
    return {
        "backend": {
            "schema": CAUSAL_CALIBRATION_BACKEND_SCHEMA,
            "name": "local_augmented_ipw_calibration",
            "version": "v1",
            "claim": "observational_calibration_only",
        },
        "att": round(primary_effect, 6),
        "ate": round(primary_effect, 6),
        "naive_effect": round(naive_effect, 6),
        "standard_error": round(primary_se, 6),
        "treated_count": len(treated),
        "control_count": len(control),
        "usable_record_count": len(usable),
        "raw_record_count": len(records),
        "strata": strata,
        "mean_model_effect_from_records": round(_mean(model_effects), 6) if model_effects else None,
        "identification": "observational_augmented_ipw_with_stratified_sensitivity",
        "estimator": {
            "primary": primary_name,
            "primary_effect": round(primary_effect, 6),
            "primary_standard_error": round(primary_se, 6),
        },
        "estimators": {
            "naive_difference": {"effect": round(naive_effect, 6)},
            "stratified_att": {"effect": round(stratified_effect, 6), "standard_error": round(stratified_se, 6)},
            "ipw_ate": {"effect": round(ipw_effect, 6), "standard_error": round(ipw_se, 6), "effective_sample_size": ess},
            "augmented_ipw_ate": {
                "effect": round(aipw_effect, 6),
                "standard_error": round(aipw_se, 6),
                "influence_count": len(influence),
            },
        },
        "propensity": propensity,
        "overlap": overlap,
        "balance": balance,
        "spatial": spatial,
        "spatial_estimator": spatial_estimator,
    }


def _usable_records(records: list[dict[str, Any]], thresholds: dict[str, Any]) -> list[dict[str, Any]]:
    usable = []
    for row in records:
        treatment = _binary_treatment(row.get("treatment"))
        outcome = safe_float(row.get("outcome"), None)
        if treatment is None or outcome is None:
            continue
        if truthy(row.get("synthetic")) and not thresholds.get("allow_synthetic"):
            continue
        if truthy(row.get("not_for_production")) and not thresholds.get("allow_not_for_production"):
            continue
        usable.append(
            {
                **row,
                "treatment": treatment,
                "outcome": float(outcome),
                "stratum": str(row.get("stratum") or "global"),
                "covariates": _numeric_covariates(row),
                "evidence_weight": max(0.0, float(safe_float(row.get("evidence_weight"), safe_float(row.get("weight"), 1.0)) or 1.0)),
                "spatial": _spatial_attributes(row),
            }
        )
    return usable


def _assign_propensity_scores(usable: list[dict[str, Any]], thresholds: dict[str, Any]) -> dict[str, Any]:
    if not usable:
        return {"method": "none", "propensity_count": 0}
    min_p = max(0.001, min(0.49, float(thresholds.get("min_propensity", 0.05) or 0.05)))
    global_rate = _clamp_probability(_mean([row["treatment"] for row in usable]), min_p)
    by_stratum: dict[str, list[dict[str, Any]]] = {}
    for row in usable:
        by_stratum.setdefault(row["stratum"], []).append(row)
    stratum_rates = {
        stratum: _clamp_probability((sum(item["treatment"] for item in rows) + 1.0) / (len(rows) + 2.0), min_p)
        for stratum, rows in by_stratum.items()
    }
    payload_score_count = 0
    for row in usable:
        payload_score = safe_float(row.get("propensity_score"), None)
        if payload_score is not None and 0.0 < float(payload_score) < 1.0:
            raw_propensity = float(payload_score)
            propensity = _clamp_probability(raw_propensity, min_p)
            row["raw_propensity_score"] = raw_propensity
            row["propensity_clipped"] = raw_propensity != propensity
            payload_score_count += 1
        else:
            propensity = stratum_rates.get(row["stratum"], global_rate)
            row["raw_propensity_score"] = propensity
            row["propensity_clipped"] = False
        row["propensity_score"] = propensity
    return {
        "method": "payload_score_or_laplace_stratum_rate",
        "propensity_count": len(usable),
        "payload_score_count": payload_score_count,
        "stratum_rates": {key: round(value, 6) for key, value in stratum_rates.items()},
    }


def _stratified_effect(usable: list[dict[str, Any]], treated: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], float, float]:
    stratum_effects: list[dict[str, Any]] = []
    strata = sorted({row["stratum"] for row in usable})
    treated_count = max(1, len(treated))
    for stratum in strata:
        rows = [row for row in usable if row["stratum"] == stratum]
        s_treated = [row for row in rows if row["treatment"] == 1]
        s_control = [row for row in rows if row["treatment"] == 0]
        if not s_treated or not s_control:
            continue
        effect = _weighted_mean([row["outcome"] for row in s_treated], [row["evidence_weight"] for row in s_treated]) - _weighted_mean(
            [row["outcome"] for row in s_control],
            [row["evidence_weight"] for row in s_control],
        )
        weight = len(s_treated) / treated_count
        stratum_effects.append(
            {
                "stratum": stratum,
                "effect": round(effect, 6),
                "treated_count": len(s_treated),
                "control_count": len(s_control),
                "weight": round(weight, 6),
            }
        )
    if not stratum_effects:
        return [], 0.0, 1.0
    effect = sum(float(item["effect"]) * float(item["weight"]) for item in stratum_effects)
    if len(stratum_effects) == 1:
        return stratum_effects, effect, 0.0
    mean_effect = _mean([float(item["effect"]) for item in stratum_effects])
    variance = sum((float(item["effect"]) - mean_effect) ** 2 for item in stratum_effects) / max(1, len(stratum_effects) - 1)
    return stratum_effects, effect, math.sqrt(variance) / math.sqrt(len(stratum_effects))


def _ipw_ate(usable: list[dict[str, Any]]) -> tuple[float, float, dict[str, float]]:
    if not usable:
        return 0.0, 1.0, {"treated": 0.0, "control": 0.0}
    treated_terms = []
    control_terms = []
    treated_weights = []
    control_weights = []
    pseudo = []
    for row in usable:
        t = float(row["treatment"])
        y = float(row["outcome"])
        p = float(row.get("propensity_score") or 0.5)
        weight = float(row.get("evidence_weight") or 1.0)
        if t == 1.0:
            w = weight / p
            treated_terms.append(y)
            treated_weights.append(w)
        else:
            w = weight / (1.0 - p)
            control_terms.append(y)
            control_weights.append(w)
        pseudo.append((t * y / p) - ((1.0 - t) * y / (1.0 - p)))
    effect = _weighted_mean(treated_terms, treated_weights) - _weighted_mean(control_terms, control_weights) if treated_terms and control_terms else 0.0
    return effect, _standard_error(pseudo), {"treated": round(_effective_sample_size(treated_weights), 6), "control": round(_effective_sample_size(control_weights), 6)}


def _augmented_ipw_ate(usable: list[dict[str, Any]]) -> tuple[float, float, list[float]]:
    if not usable:
        return 0.0, 1.0, []
    global_mu1 = _mean([row["outcome"] for row in usable if row["treatment"] == 1])
    global_mu0 = _mean([row["outcome"] for row in usable if row["treatment"] == 0])
    outcome_by_stratum: dict[str, dict[int, float]] = {}
    for stratum in sorted({row["stratum"] for row in usable}):
        rows = [row for row in usable if row["stratum"] == stratum]
        treated = [row["outcome"] for row in rows if row["treatment"] == 1]
        control = [row["outcome"] for row in rows if row["treatment"] == 0]
        outcome_by_stratum[stratum] = {
            1: _mean(treated) if treated else global_mu1,
            0: _mean(control) if control else global_mu0,
        }
    influence = []
    weights = []
    for row in usable:
        t = float(row["treatment"])
        y = float(row["outcome"])
        p = float(row.get("propensity_score") or 0.5)
        mu1 = outcome_by_stratum.get(row["stratum"], {}).get(1, global_mu1)
        mu0 = outcome_by_stratum.get(row["stratum"], {}).get(0, global_mu0)
        psi = (mu1 - mu0) + (t * (y - mu1) / p) - ((1.0 - t) * (y - mu0) / (1.0 - p))
        influence.append(psi)
        weights.append(float(row.get("evidence_weight") or 1.0))
    return _weighted_mean(influence, weights), _standard_error(influence), influence


def _primary_estimator(
    *,
    naive_effect: float,
    stratified_effect: float,
    stratified_se: float,
    ipw_effect: float,
    ipw_se: float,
    aipw_effect: float,
    aipw_se: float,
    usable_count: int,
    treated_count: int,
    control_count: int,
    thresholds: dict[str, Any],
    overlap: dict[str, Any],
    spatial_estimator: dict[str, Any] | None = None,
) -> tuple[str, float, float]:
    if (
        spatial_estimator
        and spatial_estimator.get("status") == "pass"
        and usable_count >= int(thresholds.get("min_records", 8))
        and treated_count >= int(thresholds.get("min_treated", 3))
        and control_count >= int(thresholds.get("min_control", 3))
        and overlap.get("status") == "pass"
    ):
        return (
            "spatial_fixed_effect_neighbor_adapter",
            float(spatial_estimator.get("effect") or 0.0),
            float(spatial_estimator.get("standard_error") or 0.0),
        )
    if (
        usable_count >= int(thresholds.get("min_records", 8))
        and treated_count >= int(thresholds.get("min_treated", 3))
        and control_count >= int(thresholds.get("min_control", 3))
        and overlap.get("status") == "pass"
    ):
        return "augmented_ipw_ate", aipw_effect, aipw_se
    if stratified_se < 1.0:
        return "stratified_att", stratified_effect, stratified_se
    if ipw_se < 1.0:
        return "ipw_ate", ipw_effect, ipw_se
    return "naive_difference", naive_effect, 1.0


def _covariate_balance(usable: list[dict[str, Any]]) -> dict[str, Any]:
    keys = sorted({key for row in usable for key in (row.get("covariates") or {})})
    diagnostics = []
    max_abs = 0.0
    for key in keys:
        treated = [float((row.get("covariates") or {}).get(key)) for row in usable if row["treatment"] == 1 and key in (row.get("covariates") or {})]
        control = [float((row.get("covariates") or {}).get(key)) for row in usable if row["treatment"] == 0 and key in (row.get("covariates") or {})]
        if not treated or not control:
            continue
        treated_mean = _mean(treated)
        control_mean = _mean(control)
        pooled = math.sqrt((_variance(treated) + _variance(control)) / 2.0) or 1.0
        smd = (treated_mean - control_mean) / pooled
        max_abs = max(max_abs, abs(smd))
        diagnostics.append(
            {
                "covariate": key,
                "treated_mean": round(treated_mean, 6),
                "control_mean": round(control_mean, 6),
                "standardized_mean_difference": round(smd, 6),
            }
        )
    return {
        "status": "not_applicable" if not diagnostics else "pass",
        "covariate_count": len(diagnostics),
        "max_abs_standardized_mean_difference": round(max_abs, 6),
        "diagnostics": diagnostics,
    }


def _overlap_diagnostics(usable: list[dict[str, Any]], thresholds: dict[str, Any]) -> dict[str, Any]:
    if not usable:
        return {"status": "review", "support_ratio": 0.0, "min_propensity": None, "max_propensity": None}
    min_p = max(0.001, min(0.49, float(thresholds.get("min_propensity", 0.05) or 0.05)))
    propensities = [float(row.get("raw_propensity_score", row.get("propensity_score") or 0.5)) for row in usable]
    support = [item for item in propensities if min_p <= item <= 1.0 - min_p]
    ratio = len(support) / max(1, len(propensities))
    clipped_count = sum(1 for row in usable if row.get("propensity_clipped"))
    return {
        "status": "pass" if ratio >= float(thresholds.get("min_overlap_ratio", 0.8) or 0.8) else "review",
        "support_ratio": round(ratio, 6),
        "min_propensity": round(min(propensities), 6),
        "max_propensity": round(max(propensities), 6),
        "clipped_propensity_count": clipped_count,
        "threshold": min_p,
    }


def _spatial_interference_diagnostics(
    usable: list[dict[str, Any]],
    influence: list[float],
    thresholds: dict[str, Any],
    *,
    neighbor_edges: list[tuple[int, int, float]] | None = None,
) -> dict[str, Any]:
    spatial_rows = [row for row in usable if row.get("spatial")]
    if not spatial_rows:
        return {
            "status": "not_applicable",
            "spatial_record_count": 0,
            "neighbor_edge_count": 0,
            "spatial_cluster_count": 0,
            "note": "no spatial coordinates, cluster ids or neighbor links supplied",
        }

    neighbor_edges = list(neighbor_edges or [])
    cluster_summary = _spatial_cluster_summary(usable)
    exposure = _neighborhood_exposure(usable, neighbor_edges)
    moran = _moran_like_residual_correlation(usable, influence, neighbor_edges)
    max_exposure_gap = float(exposure.get("max_abs_exposure_gap") or 0.0)
    max_cluster_imbalance = float(cluster_summary.get("max_abs_treatment_share_gap") or 0.0)
    moran_abs = abs(float(moran.get("moran_like_i") or 0.0)) if moran.get("status") != "not_applicable" else 0.0
    status = "pass"
    if max_exposure_gap > float(thresholds.get("max_neighbor_exposure_gap", 0.35) or 0.35):
        status = "review"
    if max_cluster_imbalance > float(thresholds.get("max_spatial_cluster_treatment_gap", 0.45) or 0.45):
        status = "review"
    if moran_abs > float(thresholds.get("max_spatial_residual_moran", 0.35) or 0.35):
        status = "review"
    return {
        "status": status,
        "spatial_record_count": len(spatial_rows),
        "neighbor_edge_count": len(neighbor_edges),
        "spatial_cluster_count": cluster_summary["spatial_cluster_count"],
        "neighborhood_exposure": exposure,
        "cluster_balance": cluster_summary,
        "residual_spatial_autocorrelation": moran,
        "thresholds": {
            "max_neighbor_exposure_gap": float(thresholds.get("max_neighbor_exposure_gap", 0.35) or 0.35),
            "max_spatial_cluster_treatment_gap": float(thresholds.get("max_spatial_cluster_treatment_gap", 0.45) or 0.45),
            "max_spatial_residual_moran": float(thresholds.get("max_spatial_residual_moran", 0.35) or 0.35),
        },
    }


def _spatial_attributes(row: dict[str, Any]) -> dict[str, Any]:
    spatial: dict[str, Any] = {}
    x = None
    y = None
    if any(key in row for key in ("x", "lon", "longitude")) and any(key in row for key in ("y", "lat", "latitude")):
        x = safe_float(row.get("x"), safe_float(row.get("lon"), safe_float(row.get("longitude"), None)))
        y = safe_float(row.get("y"), safe_float(row.get("lat"), safe_float(row.get("latitude"), None)))
    if x is not None and y is not None:
        spatial["x"] = float(x)
        spatial["y"] = float(y)
    cluster = row.get("spatial_cluster") or row.get("cluster") or row.get("block_id") or row.get("township_id")
    if cluster is not None:
        spatial["cluster"] = str(cluster)
    neighbors = _neighbor_ids(row.get("neighbors") or row.get("neighbor_unit_ids") or [])
    if neighbors:
        spatial["neighbors"] = neighbors
    return spatial


def _neighbor_ids(value: Any) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [item.strip() for item in value.replace(";", ",").split(",") if item.strip()]
    return []


def _spatial_cluster_summary(usable: list[dict[str, Any]]) -> dict[str, Any]:
    clusters: dict[str, list[dict[str, Any]]] = {}
    global_treatment_share = _mean([row["treatment"] for row in usable])
    for row in usable:
        cluster = dict(row.get("spatial") or {}).get("cluster")
        if cluster is not None:
            clusters.setdefault(str(cluster), []).append(row)
    diagnostics = []
    max_gap = 0.0
    for cluster, rows in sorted(clusters.items()):
        treatment_share = _mean([row["treatment"] for row in rows])
        gap = treatment_share - global_treatment_share
        max_gap = max(max_gap, abs(gap))
        diagnostics.append(
            {
                "cluster": cluster,
                "record_count": len(rows),
                "treatment_share": round(treatment_share, 6),
                "global_treatment_share_gap": round(gap, 6),
            }
        )
    return {
        "status": "not_applicable" if not diagnostics else "pass",
        "spatial_cluster_count": len(diagnostics),
        "max_abs_treatment_share_gap": round(max_gap, 6),
        "diagnostics": diagnostics,
    }


def _neighborhood_exposure(usable: list[dict[str, Any]], neighbor_edges: list[tuple[int, int, float]]) -> dict[str, Any]:
    if not neighbor_edges:
        return {"status": "not_applicable", "max_abs_exposure_gap": 0.0, "diagnostics": []}
    neighbors: dict[int, list[int]] = {idx: [] for idx in range(len(usable))}
    for left, right, _weight in neighbor_edges:
        neighbors[left].append(right)
        neighbors[right].append(left)
    diagnostics = []
    gaps = []
    for idx, row in enumerate(usable):
        ids = neighbors.get(idx) or []
        if not ids:
            continue
        neighbor_treatment_share = _mean([usable[other]["treatment"] for other in ids])
        gap = neighbor_treatment_share - float(row["treatment"])
        gaps.append(abs(gap))
        diagnostics.append(
            {
                "unit_id": str(row.get("unit_id") or idx),
                "treatment": int(row["treatment"]),
                "neighbor_count": len(ids),
                "neighbor_treatment_share": round(neighbor_treatment_share, 6),
                "own_neighbor_exposure_gap": round(gap, 6),
            }
        )
    max_gap = max(gaps) if gaps else 0.0
    return {
        "status": "pass",
        "max_abs_exposure_gap": round(max_gap, 6),
        "diagnostics": diagnostics,
    }


def _moran_like_residual_correlation(usable: list[dict[str, Any]], influence: list[float], neighbor_edges: list[tuple[int, int, float]]) -> dict[str, Any]:
    if not neighbor_edges or len(influence) != len(usable) or len(influence) < 2:
        return {"status": "not_applicable", "moran_like_i": 0.0, "edge_count": len(neighbor_edges)}
    mean_residual = _mean(influence)
    centered = [value - mean_residual for value in influence]
    denominator = sum(value * value for value in centered)
    weight_sum = sum(weight for _left, _right, weight in neighbor_edges)
    if denominator <= 0 or weight_sum <= 0:
        return {"status": "not_applicable", "moran_like_i": 0.0, "edge_count": len(neighbor_edges)}
    numerator = sum(weight * centered[left] * centered[right] for left, right, weight in neighbor_edges)
    moran = (len(usable) / weight_sum) * (numerator / denominator)
    return {
        "status": "pass",
        "moran_like_i": round(moran, 6),
        "edge_count": len(neighbor_edges),
    }


def _numeric_covariates(row: dict[str, Any]) -> dict[str, float]:
    covariates: dict[str, float] = {}
    raw = row.get("covariates")
    if isinstance(raw, dict):
        for key, value in raw.items():
            numeric = safe_float(value, None)
            if numeric is not None:
                covariates[str(key)] = float(numeric)
    for key in ("area", "area_m2", "quality_score", "baseline_outcome", "risk_score", "evidence_coverage"):
        numeric = safe_float(row.get(key), None)
        if numeric is not None:
            covariates[key] = float(numeric)
    return covariates


def _binary_treatment(value: Any) -> int | None:
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, (int, float)):
        return 1 if float(value) >= 0.5 else 0
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "treated", "treatment", "yes", "protect", "intervention", "causal_calibrated"}:
            return 1
        if normalized in {"0", "false", "control", "untreated", "no", "baseline"}:
            return 0
    return None


def _weighted_mean(values: list[float], weights: list[float]) -> float:
    if not values:
        return 0.0
    if not weights or len(weights) != len(values):
        return _mean(values)
    total_weight = sum(max(0.0, weight) for weight in weights)
    if total_weight <= 0:
        return _mean(values)
    return sum(value * max(0.0, weight) for value, weight in zip(values, weights)) / total_weight


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _variance(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = _mean(values)
    return sum((item - mean) ** 2 for item in values) / (len(values) - 1)


def _standard_error(values: list[float]) -> float:
    if len(values) < 2:
        return 1.0 if not values else 0.0
    return math.sqrt(_variance(values)) / math.sqrt(len(values))


def _effective_sample_size(weights: list[float]) -> float:
    if not weights:
        return 0.0
    total = sum(weights)
    squared = sum(weight**2 for weight in weights)
    return (total * total / squared) if squared else 0.0


def _clamp_probability(value: float, min_p: float) -> float:
    return max(min_p, min(1.0 - min_p, float(value)))
