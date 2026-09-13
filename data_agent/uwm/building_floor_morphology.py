"""2.5D building-floor morphology renderer for UWM."""

from __future__ import annotations

import struct
from pathlib import Path
from typing import Any

import numpy as np


UWM_BUILDING_FLOOR_MORPHOLOGY_SCHEMA = "uwm.building_floor_morphology.v1"


def build_uwm_building_floor_morphology(
    *,
    morphology_id: str,
    created_at: str,
    building_shp_path: str | Path,
    admin_livability_rows: list[dict[str, Any]],
    service_accessibility_rows: list[dict[str, Any]],
    ghsl_admin_rows: list[dict[str, Any]],
    admin_spatial_graph: dict[str, Any],
) -> dict[str, Any]:
    """Project real building floor records onto UWM admin units."""

    building_shp_path = Path(building_shp_path)
    floors = _read_dbf_floor_values(building_shp_path.with_suffix(".dbf"))
    graph_nodes = _candidate_admin_nodes(admin_livability_rows, admin_spatial_graph)
    stats = {
        node["key"]: {
            "building_count": 0,
            "floor_count_sum": 0.0,
            "max_floor": 0.0,
        }
        for node in graph_nodes
    }
    parsed_building_count = 0
    assigned_building_count = 0
    for index, center in enumerate(_iter_shapefile_bbox_centers(building_shp_path)):
        parsed_building_count += 1
        match = _smallest_bbox_match(graph_nodes, center)
        if match is None:
            continue
        floor = floors[index] if index < len(floors) else 0.0
        unit_stats = stats[match["key"]]
        unit_stats["building_count"] += 1
        unit_stats["floor_count_sum"] += floor
        unit_stats["max_floor"] = max(unit_stats["max_floor"], floor)
        assigned_building_count += 1

    service_by_key = _rows_by_key(service_accessibility_rows)
    ghsl_by_key = _rows_by_key(ghsl_admin_rows)
    graph_by_key = {node["key"]: node for node in graph_nodes}
    rows = []
    for row in admin_livability_rows:
        key = _county_township_key(row)
        unit_stats = stats[key]
        service = service_by_key[key]
        ghsl = ghsl_by_key[key]
        graph_node = graph_by_key[key]
        building_count = int(unit_stats["building_count"])
        floor_sum = unit_stats["floor_count_sum"]
        rows.append(
            {
                "admin_unit_id": row.get("admin_unit_id"),
                "county": row.get("county"),
                "township": row.get("township"),
                "assignment_rule": "building_bbox_center_inside_admin_bbox_choose_smallest_bbox_area",
                "building_count": building_count,
                "floor_count_sum": int(floor_sum),
                "average_floor": round(
                    floor_sum / building_count if building_count else 0.0,
                    6,
                ),
                "max_floor": int(unit_stats["max_floor"]),
                "bbox_area_degrees2": round(graph_node["bbox_area_degrees2"], 12),
                "service_point_count": _float(service.get("service_point_count")),
                "essential_service_count": _float(
                    service.get("essential_service_count")
                ),
                "ghsl_population_proxy_sum": _float(
                    ghsl.get("population_proxy_sum")
                ),
                "ghsl_built_surface_proxy_sum": _float(
                    ghsl.get("built_surface_proxy_sum")
                ),
            }
        )

    evaluations = _morphology_endpoint_evaluations(rows)
    ready = all(item["beats_2d_baselines"] for item in evaluations)
    supported_claim = (
        "building_floor_25d_morphology_service_endpoint_head_beats_2d_baselines"
        if ready
        else "no_building_floor_25d_morphology_endpoint_claim_supported"
    )
    return {
        "schema": UWM_BUILDING_FLOOR_MORPHOLOGY_SCHEMA,
        "morphology_id": morphology_id,
        "created_at": created_at,
        "source_building_shp_path": str(building_shp_path),
        "source_building_record_count": len(floors),
        "parsed_building_geometry_count": parsed_building_count,
        "assigned_building_count": assigned_building_count,
        "unassigned_building_count": max(
            0,
            parsed_building_count - assigned_building_count,
        ),
        "admin_unit_count": len(rows),
        "source_coverage": {
            "matched_admin_units": sum(1 for row in rows if row["building_count"] > 0),
            "requested_admin_units": len(rows),
            "join_key": "building_bbox_center_to_admin_bbox",
        },
        "total_floor_count": int(sum(row["floor_count_sum"] for row in rows)),
        "max_floor": max(row["max_floor"] for row in rows) if rows else 0,
        "admin_morphology_rows": rows,
        "holdout_evaluation": {
            "morphology_endpoint_leave_one_admin_out": evaluations,
        },
        "supported_claim": supported_claim,
        "claim_boundary": {
            "max_claim_level": "bounded_support" if ready else "not_for_claim",
            "reason": (
                "building floor records are real 2.5D morphology attributes; "
                "this is not a full 3D mesh/BIM/point-cloud city model"
            ),
        },
        "true_3d_claim": False,
        "observed_policy_outcome_superiority_claim": False,
        "empirical_superiority_claim": False,
    }


def _read_dbf_floor_values(dbf_path: Path) -> list[float]:
    data = dbf_path.read_bytes()
    record_count = struct.unpack("<I", data[4:8])[0]
    header_length = struct.unpack("<H", data[8:10])[0]
    record_length = struct.unpack("<H", data[10:12])[0]
    fields = []
    position = 32
    while data[position] != 0x0D:
        raw = data[position : position + 32]
        name = raw[:11].split(b"\x00", 1)[0].decode("gbk", "ignore")
        fields.append((name, raw[16]))
        position += 32
    floors = []
    for index in range(record_count):
        record = data[
            header_length + index * record_length : header_length
            + (index + 1) * record_length
        ]
        offset = 1
        values = {}
        for name, length in fields:
            values[name] = record[offset : offset + length].decode(
                "gbk",
                "ignore",
            ).strip()
            offset += length
        floors.append(_float(values.get("Floor")))
    return floors


def _iter_shapefile_bbox_centers(shp_path: Path):
    with shp_path.open("rb") as handle:
        handle.read(100)
        while True:
            record_header = handle.read(8)
            if len(record_header) < 8:
                break
            _, content_words = struct.unpack(">2i", record_header)
            content = handle.read(content_words * 2)
            if len(content) < 36:
                continue
            shape_type = struct.unpack("<i", content[:4])[0]
            if shape_type not in {5, 15, 25}:
                continue
            xmin, ymin, xmax, ymax = struct.unpack("<4d", content[4:36])
            yield ((xmin + xmax) / 2.0, (ymin + ymax) / 2.0)


def _candidate_admin_nodes(
    admin_livability_rows: list[dict[str, Any]],
    admin_spatial_graph: dict[str, Any],
) -> list[dict[str, Any]]:
    candidate_keys = {_county_township_key(row) for row in admin_livability_rows}
    nodes = []
    for node in admin_spatial_graph.get("nodes") or []:
        key = _county_township_key(node)
        if key not in candidate_keys:
            continue
        bbox = node.get("bbox") or []
        if len(bbox) != 4:
            continue
        xmin, ymin, xmax, ymax = [_float(value) for value in bbox]
        nodes.append(
            {
                "key": key,
                "unit_id": node.get("unit_id"),
                "bbox": (xmin, ymin, xmax, ymax),
                "bbox_area_degrees2": max(0.0, (xmax - xmin) * (ymax - ymin)),
            }
        )
    return nodes


def _smallest_bbox_match(
    graph_nodes: list[dict[str, Any]],
    point: tuple[float, float],
) -> dict[str, Any] | None:
    lon, lat = point
    matches = []
    for node in graph_nodes:
        xmin, ymin, xmax, ymax = node["bbox"]
        if xmin <= lon <= xmax and ymin <= lat <= ymax:
            matches.append((node["bbox_area_degrees2"], node))
    if not matches:
        return None
    return min(matches, key=lambda item: item[0])[1]


def _morphology_endpoint_evaluations(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        _evaluate_endpoint(
            rows,
            endpoint_id="service_point_accessibility",
            target="service_point_count",
        ),
        _evaluate_endpoint(
            rows,
            endpoint_id="essential_service_accessibility",
            target="essential_service_count",
        ),
    ]


def _evaluate_endpoint(
    rows: list[dict[str, Any]],
    *,
    endpoint_id: str,
    target: str,
) -> dict[str, Any]:
    morphology_errors = _loo_ridge_abs_errors(rows, target, ["max_floor"])
    baseline_errors = {
        "city_mean": _loo_city_mean_abs_errors(rows, target),
        "ghsl_population_proxy": _loo_ridge_abs_errors(
            rows,
            target,
            ["ghsl_population_proxy_sum"],
        ),
        "ghsl_built_surface_proxy": _loo_ridge_abs_errors(
            rows,
            target,
            ["ghsl_built_surface_proxy_sum"],
        ),
    }
    baseline_maes = {
        key: round(_mean(value), 6) for key, value in baseline_errors.items()
    }
    best_baseline = min(baseline_maes, key=baseline_maes.get)
    morphology_mae = round(_mean(morphology_errors), 6)
    reduction = round(baseline_maes[best_baseline] - morphology_mae, 6)
    return {
        "endpoint_id": endpoint_id,
        "target": target,
        "morphology_model": "building_max_floor_standardized_ridge",
        "ridge": 1.0,
        "holdout_admin_unit_count": len(rows),
        "morphology_mae": morphology_mae,
        "two_d_baseline_maes": baseline_maes,
        "best_2d_baseline": best_baseline,
        "best_2d_baseline_mae": baseline_maes[best_baseline],
        "mae_reduction_vs_best_2d_baseline": reduction,
        "relative_mae_reduction_vs_best_2d_baseline": round(
            reduction / baseline_maes[best_baseline]
            if baseline_maes[best_baseline]
            else 0.0,
            6,
        ),
        "beats_2d_baselines": morphology_mae < baseline_maes[best_baseline],
        "policy_outcome_claim": False,
    }


def _loo_ridge_abs_errors(
    rows: list[dict[str, Any]],
    target: str,
    columns: list[str],
    *,
    ridge: float = 1.0,
) -> list[float]:
    errors = []
    for index, test in enumerate(rows):
        train = [row for item, row in enumerate(rows) if item != index]
        prediction = _standardized_ridge_predict(
            train,
            test,
            target=target,
            columns=columns,
            ridge=ridge,
        )
        errors.append(abs(prediction - _float(test.get(target))))
    return errors


def _loo_city_mean_abs_errors(rows: list[dict[str, Any]], target: str) -> list[float]:
    errors = []
    for index, test in enumerate(rows):
        train = [row for item, row in enumerate(rows) if item != index]
        prediction = _mean([_float(row.get(target)) for row in train])
        errors.append(abs(prediction - _float(test.get(target))))
    return errors


def _standardized_ridge_predict(
    train: list[dict[str, Any]],
    test: dict[str, Any],
    *,
    target: str,
    columns: list[str],
    ridge: float,
) -> float:
    x_train = np.array(
        [[_float(record.get(column)) for column in columns] for record in train]
    )
    y_train = np.array([_float(record.get(target)) for record in train])
    x_test = np.array([_float(test.get(column)) for column in columns])
    mean = x_train.mean(axis=0)
    scale = x_train.std(axis=0)
    scale[scale == 0.0] = 1.0
    design = np.column_stack([np.ones(len(train)), (x_train - mean) / scale])
    penalty = ridge * np.eye(design.shape[1])
    coefficients = np.linalg.solve(design.T @ design + penalty, design.T @ y_train)
    return max(0.0, float(np.r_[1.0, (x_test - mean) / scale] @ coefficients))


def _rows_by_key(rows: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    return {_county_township_key(row): row for row in rows}


def _county_township_key(row: dict[str, Any]) -> tuple[str, str]:
    return (str(row.get("county") or ""), str(row.get("township") or ""))


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _float(value: Any, default: float = 0.0) -> float:
    if value in {None, ""}:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
