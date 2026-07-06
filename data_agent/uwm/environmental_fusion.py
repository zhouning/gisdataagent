"""Multi-source environmental evidence fusion for UWM scene construction."""

from __future__ import annotations

from statistics import mean
from typing import Any


UWM_ENVIRONMENTAL_EVIDENCE_BUNDLE_SCHEMA = "uwm.environmental_evidence_bundle.v1"


def build_environmental_evidence_bundle(
    *,
    openmeteo_proxy: dict[str, Any],
    gee_proxy: dict[str, Any],
    openaq_proxy: dict[str, Any],
    scene_time_range: dict[str, Any],
    bundle_id: str,
    created_at: str,
) -> dict[str, Any]:
    """Fuse Open-Meteo, GEE ERA5/CAMS and OpenAQ evidence without upgrading claims."""

    openmeteo_aligned = _time_range_matches(openmeteo_proxy.get("time_range") or {}, scene_time_range)
    gee_aligned = _time_range_matches(gee_proxy.get("time_range") or {}, scene_time_range)
    openaq_holdout_ready = bool(openaq_proxy.get("scene_holdout_ready"))
    scene_source_ids = []
    if openmeteo_aligned:
        scene_source_ids.extend(_dataset_ids(openmeteo_proxy))
    if gee_aligned:
        scene_source_ids.extend(_dataset_ids(gee_proxy))
    observed_holdout_sources = _dataset_ids(openaq_proxy) if openaq_holdout_ready else []

    meteorology_fusion = _meteorology_fusion(openmeteo_proxy if openmeteo_aligned else {}, gee_proxy if gee_aligned else {})
    air_pollution_fusion = _air_pollution_fusion(
        openmeteo_proxy if openmeteo_aligned else {},
        gee_proxy if gee_aligned else {},
        openaq_proxy,
    )
    disagreement = _source_disagreement(openmeteo_proxy if openmeteo_aligned else {}, gee_proxy if gee_aligned else {})
    flags = _evidence_flags(disagreement, observed_holdout_sources, openaq_proxy)
    limitations = sorted(
        {
            limitation
            for proxy in [openmeteo_proxy, gee_proxy, openaq_proxy]
            for limitation in (proxy.get("limitations") or [])
            if isinstance(limitation, str)
        }
        | set(flags)
        | {
            "multi_source_environmental_fusion_uses_public_proxies",
            "environmental_evidence_bundle_not_policy_effect_holdout",
        }
    )
    return {
        "schema": UWM_ENVIRONMENTAL_EVIDENCE_BUNDLE_SCHEMA,
        "version": "0.1",
        "bundle_id": bundle_id,
        "created_at": created_at,
        "scene_time_range": {
            "start_date": str(scene_time_range.get("start_date") or ""),
            "end_date": str(scene_time_range.get("end_date") or ""),
        },
        "source_dataset_ids": _unique(_dataset_ids(openmeteo_proxy) + _dataset_ids(gee_proxy) + _dataset_ids(openaq_proxy)),
        "scene_aligned_sources": _unique(scene_source_ids),
        "observed_holdout_sources": observed_holdout_sources,
        "observed_holdout_ready": bool(observed_holdout_sources),
        "source_record_counts": {
            "openmeteo": openmeteo_proxy.get("record_counts") or {},
            "gee": gee_proxy.get("record_counts") or {},
            "openaq": openaq_proxy.get("record_counts") or {},
        },
        "meteorology_fusion": meteorology_fusion,
        "air_pollution_fusion": air_pollution_fusion,
        "source_disagreement": disagreement,
        "evidence_flags": flags,
        "claim_boundary": {
            "max_claim_level": _claim_level([openmeteo_proxy, gee_proxy, openaq_proxy]),
            "reason": "multi-source environmental evidence is bounded proxy support until observed holdout is ready",
        },
        "limitations": limitations,
        "empirical_superiority_claim": False,
    }


def validate_environmental_evidence_bundle(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate UWM environmental evidence bundle contract."""

    errors: list[str] = []
    if not isinstance(payload, dict):
        return {"valid": False, "errors": ["payload must be a JSON object"]}
    if payload.get("schema") != UWM_ENVIRONMENTAL_EVIDENCE_BUNDLE_SCHEMA:
        errors.append(f"schema must be {UWM_ENVIRONMENTAL_EVIDENCE_BUNDLE_SCHEMA}")
    for key in [
        "bundle_id",
        "scene_time_range",
        "source_dataset_ids",
        "scene_aligned_sources",
        "observed_holdout_sources",
        "meteorology_fusion",
        "air_pollution_fusion",
        "source_disagreement",
        "evidence_flags",
        "claim_boundary",
        "limitations",
    ]:
        if key not in payload:
            errors.append(f"{key} is required")
    if payload.get("empirical_superiority_claim") is not False:
        errors.append("empirical_superiority_claim must remain false unless an observed holdout gate passes")
    if not isinstance(payload.get("observed_holdout_ready"), bool):
        errors.append("observed_holdout_ready must be boolean")
    claim = payload.get("claim_boundary") or {}
    if not isinstance(claim, dict) or not claim.get("max_claim_level"):
        errors.append("claim_boundary.max_claim_level is required")
    return {"valid": not errors, "errors": errors}


def _meteorology_fusion(openmeteo_proxy: dict[str, Any], gee_proxy: dict[str, Any]) -> dict[str, float | None]:
    openmeteo = openmeteo_proxy.get("meteorology_summary") or {}
    gee = gee_proxy.get("meteorology_summary") or {}
    return {
        "temperature_2m_mean_c": _rounded_mean(
            [
                openmeteo.get("temperature_2m_mean_avg_c"),
                gee.get("temperature_2m_mean_avg_c"),
            ]
        ),
        "precipitation_total_mm": _rounded_mean(
            [
                openmeteo.get("precipitation_sum_total_mm"),
                gee.get("precipitation_total_mm"),
            ]
        ),
        "surface_pressure_avg_hpa": _rounded_mean(
            [
                openmeteo.get("surface_pressure_avg_hpa"),
                gee.get("surface_pressure_avg_hpa"),
            ]
        ),
    }


def _air_pollution_fusion(
    openmeteo_proxy: dict[str, Any],
    gee_proxy: dict[str, Any],
    openaq_proxy: dict[str, Any],
) -> dict[str, float | None]:
    openmeteo = openmeteo_proxy.get("air_pollution_summary") or {}
    gee = gee_proxy.get("air_pollution_summary") or {}
    openaq = openaq_proxy.get("air_pollution_summary") or {}
    return {
        "pm25_scene_proxy_ugm3": _rounded_mean(
            [
                openmeteo.get("pm25_avg_ugm3"),
                gee.get("cams_pm25_avg_ugm3"),
            ]
        ),
        "no2_scene_proxy_ugm3": _rounded_mean([openmeteo.get("no2_avg_ugm3")]),
        "pm25_observed_reference_ugm3": _safe_float(openaq.get("pm25_avg_ugm3")),
        "pm10_observed_reference_ugm3": _safe_float(openaq.get("pm10_avg_ugm3")),
    }


def _source_disagreement(openmeteo_proxy: dict[str, Any], gee_proxy: dict[str, Any]) -> dict[str, float | None]:
    openmeteo_met = openmeteo_proxy.get("meteorology_summary") or {}
    gee_met = gee_proxy.get("meteorology_summary") or {}
    openmeteo_air = openmeteo_proxy.get("air_pollution_summary") or {}
    gee_air = gee_proxy.get("air_pollution_summary") or {}
    return {
        "temperature_scene_proxy_range_c": _rounded_range(
            [
                openmeteo_met.get("temperature_2m_mean_avg_c"),
                gee_met.get("temperature_2m_mean_avg_c"),
            ]
        ),
        "pm25_scene_proxy_range_ugm3": _rounded_range(
            [
                openmeteo_air.get("pm25_avg_ugm3"),
                gee_air.get("cams_pm25_avg_ugm3"),
            ]
        ),
    }


def _evidence_flags(
    disagreement: dict[str, float | None],
    observed_holdout_sources: list[str],
    openaq_proxy: dict[str, Any],
) -> list[str]:
    flags = []
    if _safe_float(disagreement.get("pm25_scene_proxy_range_ugm3")) is not None:
        if _safe_float(disagreement.get("pm25_scene_proxy_range_ugm3")) >= 10.0:
            flags.append("high_pm25_source_disagreement")
    if _safe_float(disagreement.get("temperature_scene_proxy_range_c")) is not None:
        if _safe_float(disagreement.get("temperature_scene_proxy_range_c")) >= 2.0:
            flags.append("high_temperature_source_disagreement")
    if not observed_holdout_sources:
        flags.append("observed_holdout_not_ready")
    if openaq_proxy and not bool(openaq_proxy.get("scene_holdout_ready")):
        flags.append("openaq_not_scene_aligned")
    return flags


def _time_range_matches(proxy_range: dict[str, Any], scene_range: dict[str, Any]) -> bool:
    return (
        str(proxy_range.get("start_date") or "") == str(scene_range.get("start_date") or "")
        and str(proxy_range.get("end_date") or "") == str(scene_range.get("end_date") or "")
    )


def _dataset_ids(proxy: dict[str, Any]) -> list[str]:
    ids = proxy.get("source_dataset_ids") or []
    return [str(dataset_id) for dataset_id in ids if dataset_id]


def _claim_level(proxies: list[dict[str, Any]]) -> str:
    levels = [
        str((proxy.get("claim_boundary") or {}).get("max_claim_level") or "not_for_claim")
        for proxy in proxies
        if proxy
    ]
    order = ["not_for_claim", "exploratory_only", "fragile", "bounded_support", "core_support"]
    return min(levels, key=lambda level: order.index(level) if level in order else 0) if levels else "not_for_claim"


def _unique(values: list[str]) -> list[str]:
    unique_values = []
    seen = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        unique_values.append(value)
    return unique_values


def _rounded_mean(values: list[Any]) -> float | None:
    numbers = [number for number in (_safe_float(value) for value in values) if number is not None]
    return round(mean(numbers), 3) if numbers else None


def _rounded_range(values: list[Any]) -> float | None:
    numbers = [number for number in (_safe_float(value) for value in values) if number is not None]
    return round(max(numbers) - min(numbers), 3) if len(numbers) >= 2 else None


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
