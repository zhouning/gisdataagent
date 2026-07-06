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
) -> dict[str, Any]:
    """Join exposure-equity and service sample panels into composite planner targets."""

    exposure_by_id = {
        str(row.get("admin_unit_id")): row
        for row in exposure_equity_panel.get("admin_exposure_equity_rows") or []
        if row.get("admin_unit_id")
    }
    joined = []
    for service_row in admin_service_panel.get("admin_service_rows") or []:
        admin_unit_id = str(service_row.get("admin_unit_id") or "")
        exposure_row = exposure_by_id.get(admin_unit_id)
        if not exposure_row:
            continue
        joined.append(_joined_row(exposure_row, service_row))
    scored = _score_rows(joined)
    scored.sort(key=lambda row: row["livability_need_score"], reverse=True)
    target_units = [_target_unit(row) for row in scored[:50]]
    limitations = sorted(
        {
            limitation
            for source in [exposure_equity_panel, admin_service_panel]
            for limitation in (source.get("limitations") or [])
            if isinstance(limitation, str)
        }
        | {
            "composite_target_score_is_proxy_not_observed_livability",
            "service_sample_gap_not_true_absence",
            "planner_targets_require_human_review",
        }
    )
    return {
        "schema": UWM_ADMIN_LIVABILITY_TARGET_PANEL_SCHEMA,
        "version": "0.1",
        "panel_id": panel_id,
        "created_at": created_at,
        "source_dataset_ids": [
            "admin_exposure_equity_panel_2024_07",
            "admin_service_accessibility_panel_2026_07_05",
        ],
        "joined_admin_count": len(scored),
        "target_candidate_count": len([row for row in scored if row["target_candidate"]]),
        "summary": {
            "livability_need_score_mean": _rounded_mean(row["livability_need_score"] for row in scored),
            "target_candidate_count": len([row for row in scored if row["target_candidate"]]),
            "service_sample_gap_count": len([row for row in scored if row["sample_gap_flag"]]),
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
    return {
        "admin_unit_id": str(exposure_row.get("admin_unit_id") or ""),
        "county": str(exposure_row.get("county") or service_row.get("county") or ""),
        "township": str(exposure_row.get("township") or service_row.get("township") or ""),
        "exposure_priority_score": _float(exposure_row.get("priority_score")),
        "exposure_priority_flags": list(exposure_row.get("priority_flags") or []),
        "service_point_count": _float(service_row.get("service_point_count")),
        "essential_service_count": _float(service_row.get("essential_service_count")),
        "sample_gap_flag": str(service_row.get("sample_gap_flag") or ""),
        "interpretable_as_true_service_absence": bool(service_row.get("interpretable_as_true_service_absence")),
    }


def _score_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    exposure_norm = _minmax([row["exposure_priority_score"] for row in rows])
    service_gap_norm = _inverse_minmax([row["service_point_count"] for row in rows])
    essential_gap_norm = _inverse_minmax([row["essential_service_count"] for row in rows])
    scored = []
    for index, row in enumerate(rows):
        score = 0.50 * exposure_norm[index] + 0.30 * service_gap_norm[index] + 0.20 * essential_gap_norm[index]
        flags = []
        if exposure_norm[index] >= 0.75:
            flags.append("high_exposure_priority")
        if row["sample_gap_flag"]:
            flags.append("service_sample_gap")
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


def _rounded_mean(values: Any) -> float | None:
    numbers = [_float(value) for value in values]
    return round(mean(numbers), 3) if numbers else None


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
