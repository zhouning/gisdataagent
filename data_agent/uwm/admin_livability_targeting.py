"""Composite admin livability target panel from exposure, population and service proxies."""

from __future__ import annotations

from statistics import mean
from typing import Any


UWM_ADMIN_LIVABILITY_TARGET_PANEL_SCHEMA = "uwm.admin_livability_target_panel.v1"


def build_admin_livability_target_panel(
    *,
    exposure_equity_panel: dict[str, Any],
    admin_service_panel: dict[str, Any],
    panel_id: str,
    created_at: str,
    experiment_scope: str = "full_admin_graph",
) -> dict[str, Any]:
    """Join exposure-equity and service sample panels into composite planner targets."""

    full_service_surface = _is_full_service_surface(admin_service_panel)
    exposure_rows = [
        row
        for row in exposure_equity_panel.get("admin_exposure_equity_rows") or []
        if row.get("admin_unit_id")
    ]
    service_by_id = {
        str(row.get("admin_unit_id")): row
        for row in admin_service_panel.get("admin_service_rows") or []
        if row.get("admin_unit_id")
    }
    joined = []
    for exposure_row in exposure_rows:
        admin_unit_id = str(exposure_row.get("admin_unit_id") or "")
        service_row = service_by_id.get(admin_unit_id) or _missing_service_row(exposure_row)
        joined.append(_joined_row(exposure_row, service_row))
    scored = _score_rows(joined)
    scored.sort(key=lambda row: row["livability_need_score"], reverse=True)
    target_units = [_target_unit(row) for row in scored[:50]]
    service_missing_count = len(
        [
            row
            for row in scored
            if row.get("service_coverage_status") == "missing_service_proxy"
        ]
    )
    limitations = {
        limitation
        for source in [exposure_equity_panel, admin_service_panel]
        for limitation in (source.get("limitations") or [])
        if isinstance(limitation, str)
    } | {
        "composite_target_score_is_proxy_not_observed_livability",
        "planner_targets_require_human_review",
    }
    if service_missing_count > 0 or not full_service_surface:
        limitations |= {
            "partial_service_panel_retained_as_missing_not_dropped",
            "service_sample_gap_not_true_absence",
        }
    if full_service_surface:
        limitations.add("service_accessibility_surface_is_proxy_not_observed_travel_time")
    limitations = sorted(
        limitations
    )
    source_dataset_ids = [
        "admin_exposure_equity_panel_2024_07",
        _service_source_dataset_id(admin_service_panel),
    ]
    return {
        "schema": UWM_ADMIN_LIVABILITY_TARGET_PANEL_SCHEMA,
        "version": "0.1",
        "panel_id": panel_id,
        "created_at": created_at,
        "experiment_scope": experiment_scope,
        "source_dataset_ids": source_dataset_ids,
        "source_admin_count": len(exposure_rows),
        "joined_admin_count": len(scored),
        "service_matched_admin_count": len(scored) - service_missing_count,
        "service_missing_admin_count": service_missing_count,
        "target_candidate_count": len([row for row in scored if row["target_candidate"]]),
        "summary": {
            "livability_need_score_mean": _rounded_mean(row["livability_need_score"] for row in scored),
            "target_candidate_count": len([row for row in scored if row["target_candidate"]]),
            "service_sample_gap_count": len([row for row in scored if row["sample_gap_flag"]]),
            "service_missing_admin_count": service_missing_count,
            "service_surface_type": (
                "full_admin_local_poi_road_accessibility_surface"
                if full_service_surface
                else "partial_admin_service_accessibility_panel"
            ),
            "service_accessibility_score_available_count": len(
                [row for row in scored if "service_accessibility_score" in row]
            ),
        },
        "admin_livability_target_rows": scored,
        "target_units": target_units,
        "claim_boundary": {
            "max_claim_level": _claim_level(exposure_equity_panel, admin_service_panel),
            "reason": "Composite livability targets combine public proxies for bounded planner benchmarking only.",
        },
        "limitations": limitations,
        "empirical_superiority_claim": False,
    }


def validate_admin_livability_target_panel(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate composite admin livability target panel."""

    errors: list[str] = []
    if not isinstance(payload, dict):
        return {"valid": False, "errors": ["payload must be a JSON object"]}
    if payload.get("schema") != UWM_ADMIN_LIVABILITY_TARGET_PANEL_SCHEMA:
        errors.append(f"schema must be {UWM_ADMIN_LIVABILITY_TARGET_PANEL_SCHEMA}")
    for key in [
        "panel_id",
        "source_dataset_ids",
        "joined_admin_count",
        "experiment_scope",
        "source_admin_count",
        "service_matched_admin_count",
        "service_missing_admin_count",
        "admin_livability_target_rows",
        "target_units",
        "claim_boundary",
        "limitations",
    ]:
        if key not in payload:
            errors.append(f"{key} is required")
    if payload.get("empirical_superiority_claim") is not False:
        errors.append("empirical_superiority_claim must be false for composite proxy targets")
    claim = payload.get("claim_boundary") or {}
    if not isinstance(claim, dict) or not claim.get("max_claim_level"):
        errors.append("claim_boundary.max_claim_level is required")
    return {"valid": not errors, "errors": errors}


def _joined_row(exposure_row: dict[str, Any], service_row: dict[str, Any]) -> dict[str, Any]:
    joined = {
        "admin_unit_id": str(exposure_row.get("admin_unit_id") or ""),
        "county": str(exposure_row.get("county") or service_row.get("county") or ""),
        "township": str(exposure_row.get("township") or service_row.get("township") or ""),
        "exposure_priority_score": _float(exposure_row.get("priority_score")),
        "exposure_priority_flags": list(exposure_row.get("priority_flags") or []),
        "service_point_count": _float(service_row.get("service_point_count")),
        "essential_service_count": _float(service_row.get("essential_service_count")),
        "sample_gap_flag": str(service_row.get("sample_gap_flag") or ""),
        "interpretable_as_true_service_absence": bool(service_row.get("interpretable_as_true_service_absence")),
        "service_coverage_status": str(
            service_row.get("service_coverage_status") or "matched_service_proxy"
        ),
    }
    for key in [
        "service_accessibility_score",
        "service_gap_score",
        "nearest_essential_service_distance_m",
        "estimated_nearest_essential_travel_time_min",
        "road_segment_count",
        "road_length_km",
        "mean_road_speed_kmh",
        "healthcare_count",
        "education_count",
        "food_retail_count",
        "finance_count",
        "mobility_transport_count",
        "civic_public_count",
        "recreation_count",
        "lodging_count",
        "other_service_count",
        "service_capacity_proxy",
        "service_void_flag",
    ]:
        if key in service_row:
            joined[key] = service_row.get(key)
    return joined


def _score_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    exposure_norm = _minmax([row["exposure_priority_score"] for row in rows])
    matched_indices = [
        index
        for index, row in enumerate(rows)
        if row.get("service_coverage_status") != "missing_service_proxy"
    ]
    matched_service_gap = _inverse_minmax(
        [rows[index]["service_point_count"] for index in matched_indices]
    )
    matched_essential_gap = _inverse_minmax(
        [rows[index]["essential_service_count"] for index in matched_indices]
    )
    service_gap_norm = [0.5 for _ in rows]
    essential_gap_norm = [0.5 for _ in rows]
    for offset, index in enumerate(matched_indices):
        if "service_gap_score" in rows[index]:
            service_gap_norm[index] = _clamp01(_float(rows[index].get("service_gap_score")))
        else:
            service_gap_norm[index] = matched_service_gap[offset]
        essential_gap_norm[index] = matched_essential_gap[offset]
    scored = []
    for index, row in enumerate(rows):
        score = 0.50 * exposure_norm[index] + 0.30 * service_gap_norm[index] + 0.20 * essential_gap_norm[index]
        flags = []
        if exposure_norm[index] >= 0.75:
            flags.append("high_exposure_priority")
        if row["sample_gap_flag"]:
            flags.append("service_sample_gap")
        if row.get("service_coverage_status") == "missing_service_proxy":
            flags.append("service_proxy_missing")
        if essential_gap_norm[index] >= 0.75:
            flags.append("low_essential_service_sample")
        target_candidate = "high_exposure_priority" in flags and (
            "service_sample_gap" in flags or "low_essential_service_sample" in flags
        )
        if target_candidate:
            flags.append("composite_livability_target")
        scored.append(
            {
                **row,
                "livability_need_score": round(score, 6),
                "target_flags": flags,
                "target_candidate": target_candidate,
                "score_components": {
                    "exposure_norm": round(exposure_norm[index], 6),
                    "service_gap_norm": round(service_gap_norm[index], 6),
                    "essential_gap_norm": round(essential_gap_norm[index], 6),
                },
            }
        )
    return scored


def _missing_service_row(exposure_row: dict[str, Any]) -> dict[str, Any]:
    return {
        "admin_unit_id": exposure_row.get("admin_unit_id"),
        "county": exposure_row.get("county"),
        "township": exposure_row.get("township"),
        "service_point_count": 0,
        "essential_service_count": 0,
        "sample_gap_flag": "service_data_missing_for_admin_unit",
        "interpretable_as_true_service_absence": False,
        "service_coverage_status": "missing_service_proxy",
    }


def _target_unit(row: dict[str, Any]) -> dict[str, Any]:
    flags = list(row.get("target_flags") or [])
    if not row.get("target_candidate") and "top_composite_proxy_unit" not in flags:
        flags.append("top_composite_proxy_unit")
    return {
        "admin_unit_id": row["admin_unit_id"],
        "county": row["county"],
        "township": row["township"],
        "priority_score": row["livability_need_score"],
        "livability_need_score": row["livability_need_score"],
        "priority_flags": flags,
        "target_flags": flags,
        "target_candidate": bool(row.get("target_candidate")),
    }


def _minmax(values: list[float]) -> list[float]:
    if not values:
        return []
    low = min(values)
    high = max(values)
    if high == low:
        return [0.0 for _ in values]
    return [(value - low) / (high - low) for value in values]


def _inverse_minmax(values: list[float]) -> list[float]:
    return [1.0 - value for value in _minmax(values)]


def _claim_level(*sources: dict[str, Any]) -> str:
    levels = [
        str((source.get("claim_boundary") or {}).get("max_claim_level") or "not_for_claim")
        for source in sources
    ]
    order = ["not_for_claim", "exploratory_only", "fragile", "bounded_support", "core_support"]
    return min(levels, key=lambda level: order.index(level) if level in order else 0)


def _is_full_service_surface(panel: dict[str, Any]) -> bool:
    return panel.get("schema") == "uwm.full_admin_service_accessibility_surface.v1"


def _service_source_dataset_id(panel: dict[str, Any]) -> str:
    if _is_full_service_surface(panel):
        return "full_admin_service_accessibility_surface_2026_07_08"
    return "admin_service_accessibility_panel_2026_07_05"


def _rounded_mean(values: Any) -> float | None:
    numbers = [_float(value) for value in values]
    return round(mean(numbers), 3) if numbers else None


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))
