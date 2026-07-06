"""UWM scene-state fusion between renderer observations and simulator rollouts."""

from __future__ import annotations

from statistics import mean
from typing import Any


UWM_SCENE_STATE_SCHEMA = "uwm.scene_state.v1"


def build_scene_state_from_proxy_artifacts(
    *,
    observations: list[dict[str, Any]],
    ghsl_alignment: dict[str, Any],
    ghsl_zonal_rows: list[dict[str, Any]],
    openmeteo_proxy: dict[str, Any],
    environmental_evidence_bundle: dict[str, Any] | None = None,
    scene_id: str,
    created_at: str,
) -> dict[str, Any]:
    """Fuse current UWM proxy observations into simulator-ready scene controls."""

    population_context = _population_context(ghsl_alignment, ghsl_zonal_rows)
    environmental_context = (
        _environmental_context_from_bundle(environmental_evidence_bundle)
        if environmental_evidence_bundle
        else _environmental_context(openmeteo_proxy)
    )
    scenario_controls = _scenario_controls(population_context, environmental_context)
    claim_level = _claim_level(observations, openmeteo_proxy, environmental_evidence_bundle)
    limitations = sorted(
        {
            limitation
            for limitation in (openmeteo_proxy.get("limitations") or [])
            if isinstance(limitation, str)
        }
        | {
            limitation
            for limitation in ((environmental_evidence_bundle or {}).get("limitations") or [])
            if isinstance(limitation, str)
        }
        | {
            flag
            for flag in ((environmental_evidence_bundle or {}).get("evidence_flags") or [])
            if isinstance(flag, str)
        }
        | {
            "proxy_scene_state_not_observed_holdout",
            "scene_controls_are_mechanistic_scalars_not_fitted_policy_effects",
        }
    )
    return {
        "schema": UWM_SCENE_STATE_SCHEMA,
        "version": "0.1",
        "scene_id": scene_id,
        "created_at": created_at,
        "source_observation_ids": [
            str(observation.get("observation_id"))
            for observation in observations
            if observation.get("observation_id")
        ],
        "source_dataset_ids": _source_dataset_ids(observations),
        "population_context": population_context,
        "environmental_context": environmental_context,
        "scenario_controls": scenario_controls,
        "claim_boundary": {
            "max_claim_level": claim_level,
            "reason": "scene state is fused from bounded public proxies and must pass simulator/evidence gates",
        },
        "limitations": limitations,
        "empirical_superiority_claim": False,
        "scene_trace": [
            {
                "step": "fuse_renderer_observations",
                "observation_count": len(observations),
            },
            {
                "step": "derive_population_and_built_context",
                "admin_unit_count": population_context["admin_unit_count"],
            },
            {
                "step": "derive_environmental_context",
                "time_range": environmental_context.get("time_range"),
                "source_schema": environmental_context.get("source_schema"),
            },
            {
                "step": "derive_simulator_controls",
                "scenario_controls": scenario_controls,
            },
        ],
    }


def validate_scene_state(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate UWM scene-state contract."""

    errors: list[str] = []
    if not isinstance(payload, dict):
        return {"valid": False, "errors": ["payload must be a JSON object"]}
    if payload.get("schema") != UWM_SCENE_STATE_SCHEMA:
        errors.append(f"schema must be {UWM_SCENE_STATE_SCHEMA}")
    for key in [
        "scene_id",
        "source_observation_ids",
        "population_context",
        "environmental_context",
        "scenario_controls",
        "claim_boundary",
        "limitations",
        "scene_trace",
    ]:
        if key not in payload:
            errors.append(f"{key} is required")
    if payload.get("empirical_superiority_claim") is not False:
        errors.append("empirical_superiority_claim must remain false for proxy scene state")
    controls = payload.get("scenario_controls") or {}
    for key in ["heat_stress_multiplier", "air_pollution_stress_multiplier", "vulnerability_multiplier"]:
        if _safe_float(controls.get(key), default=0.0) <= 0:
            errors.append(f"scenario_controls.{key} must be positive")
    claim = payload.get("claim_boundary") or {}
    if not isinstance(claim, dict) or not claim.get("max_claim_level"):
        errors.append("claim_boundary.max_claim_level is required")
    return {"valid": not errors, "errors": errors}


def derive_simulator_scenario_from_scene_state(
    scene_state: dict[str, Any],
    *,
    scenario_id: str,
) -> dict[str, Any]:
    """Derive simulator scenario controls from a validated scene state."""

    validation = validate_scene_state(scene_state)
    if not validation["valid"]:
        raise ValueError(f"invalid scene state: {validation['errors']}")
    controls = scene_state.get("scenario_controls") or {}
    return {
        "scenario_id": scenario_id,
        "source_scene_state_id": scene_state.get("scene_id"),
        "heat_stress_multiplier": _safe_float(controls.get("heat_stress_multiplier"), default=1.0),
        "air_pollution_stress_multiplier": _safe_float(
            controls.get("air_pollution_stress_multiplier"),
            default=1.0,
        ),
        "vulnerability_multiplier": _safe_float(controls.get("vulnerability_multiplier"), default=1.0),
        "claim_boundary": scene_state.get("claim_boundary"),
        "empirical_superiority_claim": False,
    }


def _population_context(
    ghsl_alignment: dict[str, Any],
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    populations = [_safe_float(row.get("population_proxy_sum"), default=0.0) for row in rows]
    built = [_safe_float(row.get("built_surface_proxy_sum"), default=0.0) for row in rows]
    positive_populations = [value for value in populations if value > 0]
    admin_count = int(ghsl_alignment.get("admin_feature_count") or len(rows))
    avg_population = mean(positive_populations) if positive_populations else 0.0
    high_population_threshold = avg_population * 1.5 if avg_population else 0.0
    return {
        "source_dataset_id": str(ghsl_alignment.get("dataset_id") or "ghsl_admin_zonal_proxy_alignment"),
        "admin_unit_count": admin_count,
        "nonzero_population_unit_count": len(positive_populations),
        "population_proxy_total": round(sum(populations), 3),
        "built_surface_proxy_total": round(sum(built), 3),
        "population_proxy_mean_nonzero": round(avg_population, 3),
        "high_population_proxy_unit_count": len(
            [value for value in positive_populations if high_population_threshold and value >= high_population_threshold]
        ),
    }


def _environmental_context(openmeteo_proxy: dict[str, Any]) -> dict[str, Any]:
    meteorology = openmeteo_proxy.get("meteorology_summary") or {}
    air = openmeteo_proxy.get("air_pollution_summary") or {}
    return {
        "source_schema": openmeteo_proxy.get("schema"),
        "time_range": openmeteo_proxy.get("time_range"),
        "temperature_2m_mean_avg_c": _safe_float(meteorology.get("temperature_2m_mean_avg_c"), default=0.0),
        "precipitation_sum_total_mm": _safe_float(meteorology.get("precipitation_sum_total_mm"), default=0.0),
        "pm25_avg_ugm3": _safe_float(air.get("pm25_avg_ugm3"), default=0.0),
        "no2_avg_ugm3": _safe_float(air.get("no2_avg_ugm3"), default=0.0),
    }


def _environmental_context_from_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    meteorology = bundle.get("meteorology_fusion") or {}
    air = bundle.get("air_pollution_fusion") or {}
    return {
        "source_schema": bundle.get("schema"),
        "time_range": bundle.get("scene_time_range"),
        "temperature_2m_mean_avg_c": _safe_float(meteorology.get("temperature_2m_mean_c"), default=0.0),
        "precipitation_sum_total_mm": _safe_float(meteorology.get("precipitation_total_mm"), default=0.0),
        "pm25_avg_ugm3": _safe_float(air.get("pm25_scene_proxy_ugm3"), default=0.0),
        "no2_avg_ugm3": _safe_float(air.get("no2_scene_proxy_ugm3"), default=0.0),
        "observed_holdout_ready": bool(bundle.get("observed_holdout_ready")),
        "evidence_flags": list(bundle.get("evidence_flags") or []),
    }


def _scenario_controls(
    population_context: dict[str, Any],
    environmental_context: dict[str, Any],
) -> dict[str, float]:
    temperature = environmental_context["temperature_2m_mean_avg_c"]
    pm25 = environmental_context["pm25_avg_ugm3"]
    no2 = environmental_context["no2_avg_ugm3"]
    admin_count = max(1, int(population_context["admin_unit_count"]))
    high_population_share = population_context["high_population_proxy_unit_count"] / admin_count
    return {
        "heat_stress_multiplier": _clamp(1.0 + max(0.0, temperature - 26.0) / 20.0, 0.8, 1.6),
        "air_pollution_stress_multiplier": _clamp(1.0 + max(0.0, pm25 - 25.0) / 100.0 + max(0.0, no2 - 30.0) / 200.0, 0.8, 1.8),
        "vulnerability_multiplier": _clamp(1.0 + high_population_share * 0.5, 1.0, 1.5),
    }


def _claim_level(
    observations: list[dict[str, Any]],
    openmeteo_proxy: dict[str, Any],
    environmental_evidence_bundle: dict[str, Any] | None = None,
) -> str:
    levels = [
        str((observation.get("claim_boundary") or {}).get("max_claim_level") or "not_for_claim")
        for observation in observations
    ]
    proxy_level = str((openmeteo_proxy.get("claim_boundary") or {}).get("max_claim_level") or "not_for_claim")
    levels.append(proxy_level)
    if environmental_evidence_bundle:
        bundle_level = str(
            (environmental_evidence_bundle.get("claim_boundary") or {}).get("max_claim_level") or "not_for_claim"
        )
        levels.append(bundle_level)
    order = ["not_for_claim", "exploratory_only", "fragile", "bounded_support", "core_support"]
    return min(levels, key=lambda level: order.index(level) if level in order else 0)


def _source_dataset_ids(observations: list[dict[str, Any]]) -> list[str]:
    ids = []
    seen = set()
    for observation in observations:
        for flag in observation.get("synthetic_flags") or []:
            dataset_id = str(flag.get("dataset_id") or "")
            if dataset_id and dataset_id not in seen:
                seen.add(dataset_id)
                ids.append(dataset_id)
    return ids


def _clamp(value: float, low: float, high: float) -> float:
    return round(max(low, min(high, value)), 6)


def _safe_float(value: Any, *, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
