"""Traditional static livability baseline for UWM demonstrations."""

from __future__ import annotations

from typing import Any


UWM_TRADITIONAL_LIVABILITY_BASELINE_SCHEMA = (
    "uwm.traditional_livability_baseline.v1"
)


def build_traditional_livability_baseline(
    *,
    baseline_id: str,
    created_at: str,
    multisource_livability_scene: dict[str, Any],
    top_n: int = 2,
) -> dict[str, Any]:
    """Build a static indicator-ranking baseline from the same UWM scene data."""

    ranked_units = _rank_static_units(
        multisource_livability_scene.get("admin_unit_states") or []
    )
    top_priority_units = [
        str(row.get("admin_unit_id")) for row in ranked_units[:top_n]
    ]
    return {
        "schema": UWM_TRADITIONAL_LIVABILITY_BASELINE_SCHEMA,
        "baseline_id": baseline_id,
        "created_at": created_at,
        "data_scene_id": multisource_livability_scene.get("scene_id"),
        "admin_unit_count": len(ranked_units),
        "baseline_method": "static_indicator_weighted_ranking_without_world_model",
        "final_output_type": "static_problem_ranking",
        "capabilities": [
            "current_state_indicator_summary",
            "static_problem_ranking",
            "static_priority_units",
        ],
        "simulator_used": False,
        "planner_used": False,
        "counterfactual_output_available": False,
        "top_priority_units": top_priority_units,
        "ranked_admin_units": ranked_units,
        "static_action_recommendation": {
            "method": "top_n_static_livability_need_score",
            "action_count": len(top_priority_units),
            "target_units": top_priority_units,
            "actions": [
                {
                    "action_id": f"traditional-static-priority-{unit_id}",
                    "action_type": "static_priority_attention",
                    "target_units": [unit_id],
                    "basis": "current_livability_need_score_ranking",
                }
                for unit_id in top_priority_units
            ],
        },
        "claim_boundary": {
            "max_claim_level": "baseline_reference",
            "reason": (
                "traditional baseline uses the same rendered scene but only outputs "
                "current-state ranking; it does not simulate action-conditioned futures"
            ),
        },
        "observed_policy_outcome_superiority_claim": False,
        "empirical_superiority_claim": False,
    }


def _rank_static_units(scene_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for row in scene_rows:
        state = row.get("state_vector") or {}
        rows.append(
            {
                "admin_unit_id": row.get("admin_unit_id"),
                "county": row.get("county"),
                "township": row.get("township"),
                "static_livability_need_score": _float(
                    state.get("livability_need_score")
                ),
                "exposure_priority_score": _float(
                    state.get("exposure_priority_score")
                ),
                "service_gap_norm": _float(state.get("service_gap_norm")),
                "essential_service_gap_norm": _float(
                    state.get("essential_service_gap_norm")
                ),
                "service_point_count": _float(state.get("service_point_count")),
                "essential_service_count": _float(
                    state.get("essential_service_count")
                ),
            }
        )
    rows.sort(
        key=lambda item: (
            -item["static_livability_need_score"],
            str(item["admin_unit_id"]),
        )
    )
    for rank, row in enumerate(rows, start=1):
        row["static_rank"] = rank
    return rows


def _float(value: Any, default: float = 0.0) -> float:
    if value in {None, ""}:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
