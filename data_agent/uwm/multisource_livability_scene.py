"""Multisource renderer for UWM urban livability analysis.

The renderer aligns real prepared artifacts onto one administrative-unit scene.
It keeps predictive validation heads source-gated so broad livability analysis
does not turn into circular scoring.
"""

from __future__ import annotations

import ast
from typing import Any

import numpy as np


UWM_MULTISOURCE_LIVABILITY_SCENE_SCHEMA = "uwm.multisource_livability_scene.v1"


def build_uwm_multisource_livability_scene(
    *,
    scene_id: str,
    created_at: str,
    admin_livability_rows: list[dict[str, Any]],
    admin_exposure_equity_rows: list[dict[str, Any]],
    service_accessibility_rows: list[dict[str, Any]],
    ghsl_admin_rows: list[dict[str, Any]],
    gee_admin_environment: dict[str, Any],
    scene_aligned_gridded_air_quality_holdout: dict[str, Any],
    admin_spatial_graph: dict[str, Any],
    unicom_latent_mobility_graph: dict[str, Any],
    osm_mobility_network: dict[str, Any],
    osm_admin_mobility_crosswalk: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Render all currently aligned UWM livability sources into one scene."""

    osm_admin_mobility_crosswalk = osm_admin_mobility_crosswalk or {}
    exposure_by_key = _rows_by_county_township(admin_exposure_equity_rows)
    service_by_key = _rows_by_county_township(service_accessibility_rows)
    ghsl_by_key = _rows_by_county_township(ghsl_admin_rows)
    gee_rows = gee_admin_environment.get("admin_environment_rows") or []
    gee_by_key = _rows_by_county_township(gee_rows)
    pm25_rows = scene_aligned_gridded_air_quality_holdout.get("series_results") or []
    pm25_by_key = _rows_by_county_township(pm25_rows)
    graph_nodes = admin_spatial_graph.get("nodes") or []
    graph_by_key = _rows_by_county_township(graph_nodes)
    osm_crosswalk_rows = osm_admin_mobility_crosswalk.get("admin_mobility_rows") or []
    osm_crosswalk_by_key = _rows_by_county_township(osm_crosswalk_rows)

    rendered_rows = []
    for row in admin_livability_rows:
        key = _county_township_key(row)
        exposure = exposure_by_key[key]
        service = service_by_key[key]
        ghsl = ghsl_by_key[key]
        gee = gee_by_key[key]
        pm25 = pm25_by_key[key]
        graph_node = graph_by_key[key]
        osm_crosswalk = osm_crosswalk_by_key.get(key, {})
        score_components = _literal_dict(row.get("score_components"))
        scene_pm25_mean = _mean(
            [_float(record.get("pm25_ugm3")) for record in pm25.get("daily_pm25") or []]
        )
        service_gap_norm = _float(score_components.get("service_gap_norm"))
        state_vector = {
            "livability_need_score": _float(row.get("livability_need_score")),
            "exposure_priority_score": _float(row.get("exposure_priority_score")),
            "heat_exposure_norm": _float(score_components.get("exposure_norm")),
            "service_gap_norm": service_gap_norm,
            "essential_service_gap_norm": _float(
                score_components.get("essential_gap_norm")
            ),
            "essential_service_count": _float(service.get("essential_service_count")),
            "service_point_count": _float(service.get("service_point_count")),
            "gee_temperature_2m_mean_c": _float(gee.get("temperature_2m_mean_c")),
            "gee_cams_pm25_ugm3": _float(gee.get("cams_pm25_ugm3")),
            "chap_pm25_ugm3": _float(pm25.get("chap_pm25_ugm3")),
            "tap_scene_pm25_mean_ugm3": scene_pm25_mean,
            "ghsl_population_proxy_sum": _float(ghsl.get("population_proxy_sum")),
            "ghsl_built_surface_proxy_sum": _float(
                ghsl.get("built_surface_proxy_sum")
            ),
            "admin_graph_degree": _float(graph_node.get("degree")),
            "osm_road_segment_count": _float(osm_crosswalk.get("road_segment_count")),
            "osm_road_length_degrees_proxy": _float(
                osm_crosswalk.get("road_length_degrees_proxy")
            ),
            "osm_bbox_area_degrees2": _float(
                osm_crosswalk.get("bbox_area_degrees2")
            ),
        }
        matched_sources = [
            "admin_exposure_equity",
            "admin_service_accessibility_complete_bbox",
            "ghsl_admin_alignment",
            "gee_admin_environment",
            "scene_aligned_gridded_air_quality_holdout",
            "admin_spatial_adjacency_graph",
        ]
        if key in osm_crosswalk_by_key:
            matched_sources.append("osm_admin_mobility_crosswalk")
        rendered_rows.append(
            {
                "admin_unit_id": row.get("admin_unit_id"),
                "county": row.get("county"),
                "township": row.get("township"),
                "state_vector": state_vector,
                "target_candidate": str(row.get("target_candidate")) == "True",
                "source_join_trace": {
                    "join_key": "county_township",
                    "matched_sources": matched_sources,
                    "osm_assignment_rule": osm_crosswalk.get("assignment_rule"),
                },
            }
        )

    air_quality_eval = _air_quality_leave_one_admin_out(rendered_rows)
    data_sources_used = [
        "admin_livability_target_complete_bbox",
        "admin_exposure_equity",
        "admin_service_accessibility_complete_bbox",
        "ghsl_admin_alignment",
        "gee_admin_environment",
        "scene_aligned_gridded_air_quality_holdout",
        "admin_spatial_adjacency_graph",
        "unicom_latent_mobility_graph",
        "osm_mobility_network_proxy",
    ]
    if osm_crosswalk_by_key:
        data_sources_used.append("osm_admin_mobility_crosswalk")
    osm_crosswalk_coverage = _coverage(admin_livability_rows, osm_crosswalk_by_key)
    osm_crosswalk_projected = (
        osm_crosswalk_coverage["matched_admin_units"] == len(admin_livability_rows)
        and bool(osm_crosswalk_by_key)
    )
    supported_claim = (
        "multisource_livability_scene_air_quality_head_beats_single_source_baselines"
        if air_quality_eval["beats_all_single_source_baselines"]
        else "no_multisource_livability_scene_superiority_claim_supported"
    )
    return {
        "schema": UWM_MULTISOURCE_LIVABILITY_SCENE_SCHEMA,
        "scene_id": scene_id,
        "created_at": created_at,
        "admin_unit_count": len(rendered_rows),
        "data_sources_used": data_sources_used,
        "source_coverage": {
            "admin_exposure_equity": _coverage(admin_livability_rows, exposure_by_key),
            "service_accessibility": _coverage(admin_livability_rows, service_by_key),
            "ghsl_admin_alignment": _coverage(admin_livability_rows, ghsl_by_key),
            "gee_admin_environment": _coverage(admin_livability_rows, gee_by_key),
            "scene_aligned_gridded_pm25": _coverage(admin_livability_rows, pm25_by_key),
            "admin_spatial_graph": {
                **_coverage(admin_livability_rows, graph_by_key),
                "source_node_count": _int(
                    (admin_spatial_graph.get("summary") or {}).get("node_count")
                ),
                "source_edge_count": _int(
                    (admin_spatial_graph.get("summary") or {}).get("edge_count")
                ),
            },
            "unicom_latent_mobility_graph": {
                "node_count": len(unicom_latent_mobility_graph.get("nodes") or []),
                "edge_count": len(unicom_latent_mobility_graph.get("edges") or []),
                "unit_projection": "not_projected_without_grid_to_admin_crosswalk",
            },
            "osm_mobility_network": {
                "node_count": _int(
                    (osm_mobility_network.get("graph_summary") or {}).get("node_count")
                ),
                "edge_count": _int(
                    (osm_mobility_network.get("graph_summary") or {}).get("edge_count")
                ),
                "unit_projection": (
                    "projected_via_osm_admin_mobility_crosswalk"
                    if osm_crosswalk_projected
                    else "not_projected_without_road_to_admin_overlay"
                ),
            },
            "osm_admin_mobility_crosswalk": {
                **osm_crosswalk_coverage,
                "assigned_road_segment_count": _int(
                    osm_admin_mobility_crosswalk.get("assigned_road_segment_count")
                ),
                "unassigned_road_segment_count": _int(
                    osm_admin_mobility_crosswalk.get("unassigned_road_segment_count")
                ),
                "assignment_rule": osm_admin_mobility_crosswalk.get(
                    "assignment_rule"
                ),
                "unit_projection": (
                    "admin_unit_state_vector"
                    if osm_crosswalk_projected
                    else "not_projected_without_osm_admin_mobility_crosswalk"
                ),
            },
        },
        "admin_unit_states": rendered_rows,
        "holdout_evaluation": {
            "air_quality_multisource_leave_one_admin_out": air_quality_eval,
        },
        "supported_claim": supported_claim,
        "claim_boundary": {
            "max_claim_level": (
                "bounded_support"
                if supported_claim
                == "multisource_livability_scene_air_quality_head_beats_single_source_baselines"
                else "not_for_claim"
            ),
            "reason": (
                "multisource scene uses real aligned admin-unit sources; superiority is limited to "
                "leave-one-admin-out TAP scene PM2.5 prediction over single-source baselines"
            ),
        },
        "remaining_gates": [
            "observed_policy_outcome_required",
            "scene_aligned_station_calibrated_air_quality_holdout_required",
            "osm_true_polygon_overlay_required_for_high_precision_mobility_score",
        ],
        "observed_policy_outcome_superiority_claim": False,
        "empirical_superiority_claim": False,
    }


def _air_quality_leave_one_admin_out(rows: list[dict[str, Any]]) -> dict[str, Any]:
    records = [
        {
            "target": _float(row["state_vector"].get("tap_scene_pm25_mean_ugm3")),
            "chap": _float(row["state_vector"].get("chap_pm25_ugm3")),
            "cams": _float(row["state_vector"].get("gee_cams_pm25_ugm3")),
        }
        for row in rows
    ]
    multisource_errors = _loo_abs_errors(records, ["chap", "cams"])
    chap_errors = _loo_abs_errors(records, ["chap"])
    cams_errors = _loo_abs_errors(records, ["cams"])
    city_mean_errors = _loo_city_mean_errors(records)
    multisource_mae = _mean(multisource_errors)
    baseline_maes = {
        "chap_monthly_anchor_ridge": round(_mean(chap_errors), 6),
        "gee_cams_pm25_ridge": round(_mean(cams_errors), 6),
        "city_mean": round(_mean(city_mean_errors), 6),
    }
    best_single_source_mae = min(baseline_maes.values())
    paired_win_count = sum(
        multi < chap for multi, chap in zip(multisource_errors, chap_errors)
    )
    paired_loss_count = sum(
        multi > chap for multi, chap in zip(multisource_errors, chap_errors)
    )
    return {
        "target": "tap_scene_pm25_mean_ugm3",
        "model": "chap_cams_standardized_ridge",
        "ridge": 0.1,
        "holdout_admin_unit_count": len(records),
        "multisource_mae": round(multisource_mae, 6),
        "single_source_baselines": baseline_maes,
        "best_single_source_mae": round(best_single_source_mae, 6),
        "mae_reduction_vs_best_single_source": round(
            best_single_source_mae - multisource_mae,
            6,
        ),
        "paired_win_count_vs_chap": paired_win_count,
        "paired_loss_count_vs_chap": paired_loss_count,
        "beats_all_single_source_baselines": multisource_mae < best_single_source_mae,
        "spatial_interaction_negative_control_passed": False,
        "negative_control_note": (
            "reversed CAMS ordering did not degrade CHAP+CAMS LOO MAE, so this head "
            "supports only multisource prediction advantage, not spatial interaction attribution"
        ),
    }


def _loo_abs_errors(records: list[dict[str, float]], columns: list[str]) -> list[float]:
    errors = []
    for index, test in enumerate(records):
        train = [record for item, record in enumerate(records) if item != index]
        prediction = _standardized_ridge_predict(train, test, columns)
        errors.append(abs(prediction - test["target"]))
    return errors


def _loo_city_mean_errors(records: list[dict[str, float]]) -> list[float]:
    errors = []
    for index, test in enumerate(records):
        train = [record for item, record in enumerate(records) if item != index]
        prediction = _mean([record["target"] for record in train])
        errors.append(abs(prediction - test["target"]))
    return errors


def _standardized_ridge_predict(
    train: list[dict[str, float]],
    test: dict[str, float],
    columns: list[str],
    *,
    ridge: float = 0.1,
) -> float:
    x_train = np.array([[record[column] for column in columns] for record in train])
    y_train = np.array([record["target"] for record in train])
    x_test = np.array([test[column] for column in columns])
    mean = x_train.mean(axis=0)
    scale = x_train.std(axis=0)
    scale[scale == 0.0] = 1.0
    design = np.column_stack([np.ones(len(train)), (x_train - mean) / scale])
    penalty = ridge * np.eye(design.shape[1])
    coefficients = np.linalg.solve(design.T @ design + penalty, design.T @ y_train)
    return float(np.r_[1.0, (x_test - mean) / scale] @ coefficients)


def _coverage(
    admin_livability_rows: list[dict[str, Any]],
    source_by_key: dict[tuple[str, str], dict[str, Any]],
) -> dict[str, Any]:
    matched = [
        row
        for row in admin_livability_rows
        if _county_township_key(row) in source_by_key
    ]
    return {
        "matched_admin_units": len(matched),
        "requested_admin_units": len(admin_livability_rows),
        "join_key": "county_township",
    }


def _rows_by_county_township(
    rows: list[dict[str, Any]],
) -> dict[tuple[str, str], dict[str, Any]]:
    return {_county_township_key(row): row for row in rows}


def _county_township_key(row: dict[str, Any]) -> tuple[str, str]:
    return (str(row.get("county") or ""), str(row.get("township") or ""))


def _literal_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        parsed = ast.literal_eval(str(value))
    except (SyntaxError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _float(value: Any, default: float = 0.0) -> float:
    if value in {None, ""}:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
