"""Admin-level exposure and vulnerability proxy panel for UWM planning targets."""

from __future__ import annotations

from statistics import mean
from typing import Any


UWM_ADMIN_EXPOSURE_EQUITY_PANEL_SCHEMA = "uwm.admin_exposure_equity_panel.v1"


def build_admin_exposure_equity_panel(
    *,
    ghsl_zonal_rows: list[dict[str, Any]],
    admin_environment_proxy: dict[str, Any],
    panel_id: str,
    created_at: str,
) -> dict[str, Any]:
    """Join GHSL admin population/built proxy with GEE admin environmental proxy."""

    env_by_admin_id = {
        str(row.get("admin_id")): row
        for row in admin_environment_proxy.get("admin_environment_rows") or []
        if row.get("admin_id")
    }
    joined_rows = []
    for row in ghsl_zonal_rows:
        feature_index = _safe_int(row.get("feature_index"), default=-1)
        admin_id = f"cq-admin-{feature_index:04d}"
        env = env_by_admin_id.get(admin_id)
        if not env:
            continue
        joined_rows.append(_joined_row(row, env, admin_id))
    scored_rows = _score_rows(joined_rows)
    scored_rows.sort(key=lambda item: item["priority_score"], reverse=True)
    strict_target_units = [row for row in scored_rows if row["target_candidate"]]
    target_units = [_target_unit(row) for row in scored_rows[:50]]
    limitations = sorted(
        {
            limitation
            for limitation in (admin_environment_proxy.get("limitations") or [])
            if isinstance(limitation, str)
        }
        | {
            "ghsl_population_proxy_not_local_census",
            "priority_score_is_proxy_targeting_not_policy_effect",
            "not_observed_health_or_livability_outcome",
        }
    )
    return {
        "schema": UWM_ADMIN_EXPOSURE_EQUITY_PANEL_SCHEMA,
        "version": "0.1",
        "panel_id": panel_id,
        "created_at": created_at,
        "source_dataset_ids": [
            "ghsl_admin_zonal_proxy_alignment",
            "gee_admin_environment_chongqing_proxy",
        ],
        "time_range": admin_environment_proxy.get("time_range"),
        "joined_admin_count": len(scored_rows),
        "summary": {
            "target_candidate_count": len(strict_target_units),
            "priority_score_mean": _rounded_mean(row["priority_score"] for row in scored_rows),
            "pm25_proxy_mean": _rounded_mean(row["cams_pm25_ugm3"] for row in scored_rows),
            "temperature_proxy_mean": _rounded_mean(row["temperature_2m_mean_c"] for row in scored_rows),
        },
        "admin_exposure_equity_rows": scored_rows,
        "target_units": target_units[:50],
        "claim_boundary": {
            "max_claim_level": "bounded_support",
            "reason": (
                "Admin exposure-equity panel supports bounded targeting hypotheses only; "
                "it combines public proxies and does not estimate observed policy effects."
            ),
        },
        "limitations": limitations,
        "empirical_superiority_claim": False,
    }


def validate_admin_exposure_equity_panel(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate admin exposure-equity panel contract."""

    errors: list[str] = []
    if not isinstance(payload, dict):
        return {"valid": False, "errors": ["payload must be a JSON object"]}
    if payload.get("schema") != UWM_ADMIN_EXPOSURE_EQUITY_PANEL_SCHEMA:
        errors.append(f"schema must be {UWM_ADMIN_EXPOSURE_EQUITY_PANEL_SCHEMA}")
    for key in [
        "panel_id",
        "source_dataset_ids",
        "joined_admin_count",
        "summary",
        "admin_exposure_equity_rows",
        "target_units",
        "claim_boundary",
        "limitations",
    ]:
        if key not in payload:
            errors.append(f"{key} is required")
    if payload.get("empirical_superiority_claim") is not False:
        errors.append("empirical_superiority_claim must be false for proxy targeting panel")
    claim = payload.get("claim_boundary") or {}
    if not isinstance(claim, dict) or not claim.get("max_claim_level"):
        errors.append("claim_boundary.max_claim_level is required")
    return {"valid": not errors, "errors": errors}


def _joined_row(row: dict[str, Any], env: dict[str, Any], admin_id: str) -> dict[str, Any]:
    population = _safe_float(row.get("population_proxy_sum"), default=0.0)
    built = _safe_float(row.get("built_surface_proxy_sum"), default=0.0)
    return {
        "admin_unit_id": str(row.get("admin_unit_id") or ""),
        "admin_id": admin_id,
        "county": str(row.get("county") or env.get("county") or ""),
        "township": str(row.get("township") or env.get("township") or ""),
        "population_proxy_sum": round(population, 3),
        "built_surface_proxy_sum": round(built, 3),
        "temperature_2m_mean_c": _safe_float(env.get("temperature_2m_mean_c"), default=0.0),
        "cams_pm25_ugm3": _safe_float(env.get("cams_pm25_ugm3"), default=0.0),
    }


def _target_unit(row: dict[str, Any]) -> dict[str, Any]:
    flags = list(row.get("priority_flags") or [])
    if not row.get("target_candidate") and "top_priority_proxy_unit" not in flags:
        flags.append("top_priority_proxy_unit")
    return {
        "admin_unit_id": row["admin_unit_id"],
        "county": row["county"],
        "township": row["township"],
        "priority_score": row["priority_score"],
        "priority_flags": flags,
        "target_candidate": bool(row.get("target_candidate")),
    }


def _score_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    population_norm = _minmax([row["population_proxy_sum"] for row in rows])
    built_norm = _minmax([row["built_surface_proxy_sum"] for row in rows])
    temperature_norm = _minmax([row["temperature_2m_mean_c"] for row in rows])
    pm25_norm = _minmax([row["cams_pm25_ugm3"] for row in rows])
    scored = []
    for index, row in enumerate(rows):
        score = (
            0.30 * population_norm[index]
            + 0.15 * built_norm[index]
            + 0.25 * temperature_norm[index]
            + 0.30 * pm25_norm[index]
        )
        flags = []
        if population_norm[index] >= 0.75:
            flags.append("high_population_proxy")
        if temperature_norm[index] >= 0.75:
            flags.append("high_heat_proxy")
        if pm25_norm[index] >= 0.75:
            flags.append("high_pm25_proxy")
        target_candidate = {
            "high_population_proxy",
            "high_heat_proxy",
            "high_pm25_proxy",
        }.issubset(set(flags))
        if target_candidate:
            flags.append("target_candidate")
        scored.append(
            {
                **row,
                "priority_score": round(score, 6),
                "priority_components": {
                    "population_norm": round(population_norm[index], 6),
                    "built_surface_norm": round(built_norm[index], 6),
                    "heat_norm": round(temperature_norm[index], 6),
                    "pm25_norm": round(pm25_norm[index], 6),
                },
                "priority_flags": flags,
                "target_candidate": target_candidate,
            }
        )
    return scored


def _minmax(values: list[float]) -> list[float]:
    if not values:
        return []
    low = min(values)
    high = max(values)
    if high == low:
        return [0.0 for _ in values]
    return [(value - low) / (high - low) for value in values]


def _rounded_mean(values: Any) -> float | None:
    numbers = [number for number in (_safe_float(value, default=None) for value in values) if number is not None]
    return round(mean(numbers), 3) if numbers else None


def _safe_float(value: Any, *, default: float | None) -> float | None:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, *, default: int) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default
