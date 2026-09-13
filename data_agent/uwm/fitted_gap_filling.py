"""Fitted UWM gap-filling layers built from audited real/proxy inputs."""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


POPULATION_DOWNSCALING_SCHEMA = "uwm.population_downscaling_fitted_proxy.v1"
POPULATION_DOWNSCALING_DATASET_ID = "uwm_fitted_admin_population_downscaling_2021"
UNICOM_LATENT_MOBILITY_SCHEMA = "uwm.unicom_latent_mobility_graph.v1"
UNICOM_LATENT_MOBILITY_DATASET_ID = "uwm_unicom_latent_mobility_graph_2023"
FITTED_SNAPSHOT_SCHEMA = "uwm.fitted_gap_filling_snapshot_manifest.v1"


def build_population_downscaling_proxy(
    *,
    ghsl_rows: list[dict[str, Any]],
    district_rows: list[dict[str, Any]],
    source_ref: str,
    created_at: str,
) -> dict[str, Any]:
    """Downscale district resident population to admin rows with audited weights."""

    districts_by_name = {
        _norm_key(row.get("district_name")): row
        for row in district_rows
        if _norm_key(row.get("district_name"))
    }
    ghsl_by_county: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in ghsl_rows:
        county_key = _norm_key(row.get("county"))
        if county_key:
            ghsl_by_county[county_key].append(row)

    admin_rows: list[dict[str, Any]] = []
    district_summaries: list[dict[str, Any]] = []
    unmatched_districts: list[str] = []
    unmatched_admin_counties = sorted(
        {
            str(row.get("county") or "").strip()
            for key, rows in ghsl_by_county.items()
            if key not in districts_by_name
            for row in rows[:1]
        }
    )

    for district_key, district in sorted(districts_by_name.items()):
        source_admin_rows = ghsl_by_county.get(district_key, [])
        district_name = str(district.get("district_name") or "").strip()
        district_total = round(_float(district.get("resident_population_10k")) * 10000.0, 6)
        if not source_admin_rows:
            unmatched_districts.append(district_name)
            admin_rows.append(
                {
                    "admin_unit_id": _fallback_admin_unit_id(district),
                    "admin_code": str(district.get("admin_code") or "").strip(),
                    "district_name": district_name,
                    "county": district_name,
                    "township": "",
                    "feature_index": 0,
                    "population_proxy_sum": 0.0,
                    "built_surface_proxy_sum": 0.0,
                    "allocation_weight": 1.0,
                    "allocation_basis": "district_total_no_ghsl_admin_rows_fallback",
                    "geometry_level": "district_without_township_geometry",
                    "district_resident_population": district_total,
                    "downscaled_population": district_total,
                    "synthetic_status": "fitted_proxy",
                }
            )
            district_summaries.append(
                {
                    "district_name": district_name,
                    "admin_code": str(district.get("admin_code") or "").strip(),
                    "admin_unit_count": 1,
                    "resident_population_input": district_total,
                    "downscaled_population_sum": district_total,
                    "absolute_error": 0.0,
                    "allocation_basis": "district_total_no_ghsl_admin_rows_fallback",
                }
            )
            continue

        allocation_basis, weights = _allocation_weights(source_admin_rows)
        allocations = _allocate_total(district_total, weights)
        for source_row, weight, allocation in zip(source_admin_rows, weights, allocations):
            admin_rows.append(
                {
                    "admin_unit_id": str(source_row.get("admin_unit_id") or "").strip(),
                    "admin_code": str(district.get("admin_code") or "").strip(),
                    "district_name": district_name,
                    "county": str(source_row.get("county") or "").strip(),
                    "township": str(source_row.get("township") or "").strip(),
                    "feature_index": _int(source_row.get("feature_index")),
                    "population_proxy_sum": _float(source_row.get("population_proxy_sum")),
                    "built_surface_proxy_sum": _float(source_row.get("built_surface_proxy_sum")),
                    "allocation_weight": round(weight, 12),
                    "allocation_basis": allocation_basis,
                    "geometry_level": "township_admin_geometry",
                    "district_resident_population": district_total,
                    "downscaled_population": allocation,
                    "synthetic_status": "fitted_proxy",
                }
            )
        downscaled_sum = round(sum(allocations), 6)
        district_summaries.append(
            {
                "district_name": district_name,
                "admin_code": str(district.get("admin_code") or "").strip(),
                "admin_unit_count": len(source_admin_rows),
                "resident_population_input": district_total,
                "downscaled_population_sum": downscaled_sum,
                "absolute_error": round(abs(district_total - downscaled_sum), 6),
                "allocation_basis": allocation_basis,
            }
        )

    input_sum = round(
        sum(_float(row.get("resident_population_10k")) * 10000.0 for row in district_rows),
        6,
    )
    output_sum = round(sum(row["downscaled_population"] for row in admin_rows), 6)
    return {
        "schema": POPULATION_DOWNSCALING_SCHEMA,
        "dataset_id": POPULATION_DOWNSCALING_DATASET_ID,
        "source": "fitted proxy from local 2021 district population totals and GHSL admin zonal proxy weights",
        "source_ref": source_ref,
        "created_at": created_at,
        "temporal_extent": "2021_population_total_with_2020_GHSL_weight_proxy",
        "record_counts": {
            "district_rows": len(district_rows),
            "matched_districts": sum(
                1
                for row in district_summaries
                if row["allocation_basis"] != "district_total_no_ghsl_admin_rows_fallback"
            ),
            "unmatched_districts": len(unmatched_districts),
            "admin_rows": len(admin_rows),
            "unmatched_admin_counties": len(unmatched_admin_counties),
        },
        "summary": {
            "district_resident_population_input_sum": input_sum,
            "admin_downscaled_population_sum": output_sum,
            "district_total_absolute_error": round(
                sum(row["absolute_error"] for row in district_summaries),
                6,
            ),
            "allocation_basis_counts": _count_values(row["allocation_basis"] for row in admin_rows),
        },
        "district_summaries": district_summaries,
        "admin_rows": admin_rows,
        "unmatched_districts": unmatched_districts,
        "unmatched_admin_counties": unmatched_admin_counties,
        "mmfe_target_roles": [
            "population_vulnerability",
            "equity_evaluation",
            "simulator_context",
            "planner_targeting",
            "mmfe_alignment",
        ],
        "synthetic_flags": [{"dataset_id": POPULATION_DOWNSCALING_DATASET_ID, "status": "fitted_proxy"}],
        "claim_boundary": {
            "max_claim_level": "exploratory_only",
            "reason": (
                "The layer preserves audited district totals but distributes them with GHSL proxy weights. "
                "It is useful for simulator stress tests and planner targeting, not as census microdata."
            ),
        },
        "limitations": [
            "fitted_proxy_not_census_microdata",
            "district_total_preserving_but_township_distribution_modelled",
            "ghsl_2020_weight_proxy_with_2021_population_totals",
            "does_not_replace_authoritative_grid_population_or_township_census",
            "not_observed_policy_outcome",
            "unmatched_district_kept_as_district_level_fallback",
        ],
        "empirical_superiority_claim": False,
    }


def build_unicom_latent_mobility_graph(
    *,
    records: list[dict[str, Any]],
    source_ref: str,
    created_at: str,
) -> dict[str, Any]:
    """Aggregate local Unicom OD rows into a directed latent graph without coordinates."""

    edge_accumulator: dict[tuple[str, str], dict[str, Any]] = {}
    node_accumulator: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"grid_id": "", "in_weight": 0.0, "out_weight": 0.0, "self_loop_weight": 0.0}
    )
    total_weight = 0.0
    self_loop_weight = 0.0
    unknown_work_weight = 0.0
    for record in records:
        home_grid_id = _grid_id(record.get("home_grid_id"))
        work_grid_id = _grid_id(record.get("work_grid_id"))
        weight = _float(record.get("expanded_population"))
        if not home_grid_id:
            continue
        if not work_grid_id:
            work_grid_id = "0"
        pair = (home_grid_id, work_grid_id)
        edge = edge_accumulator.setdefault(
            pair,
            {
                "home_grid_id": home_grid_id,
                "work_grid_id": work_grid_id,
                "expanded_population": 0.0,
                "raw_population": 0.0,
                "raw_row_count": 0,
                "same_home_work_row_count": 0,
                "is_self_loop": home_grid_id == work_grid_id,
                "is_unknown_or_external_work_grid": work_grid_id == "0",
            },
        )
        edge["expanded_population"] = round(edge["expanded_population"] + weight, 6)
        edge["raw_population"] = round(edge["raw_population"] + _float(record.get("raw_population")), 6)
        edge["raw_row_count"] += 1
        if _int(record.get("home_work_same")) == 1 or home_grid_id == work_grid_id:
            edge["same_home_work_row_count"] += 1

        home_node = node_accumulator[home_grid_id]
        home_node["grid_id"] = home_grid_id
        home_node["out_weight"] = round(home_node["out_weight"] + weight, 6)
        work_node = node_accumulator[work_grid_id]
        work_node["grid_id"] = work_grid_id
        work_node["in_weight"] = round(work_node["in_weight"] + weight, 6)
        if home_grid_id == work_grid_id:
            home_node["self_loop_weight"] = round(home_node["self_loop_weight"] + weight, 6)
            self_loop_weight = round(self_loop_weight + weight, 6)
        if work_grid_id == "0":
            unknown_work_weight = round(unknown_work_weight + weight, 6)
        total_weight = round(total_weight + weight, 6)

    edges = sorted(
        edge_accumulator.values(),
        key=lambda row: (-row["expanded_population"], row["home_grid_id"], row["work_grid_id"]),
    )
    nodes = []
    for node in node_accumulator.values():
        total_activity = round(node["in_weight"] + node["out_weight"], 6)
        nodes.append(
            {
                "grid_id": node["grid_id"],
                "in_weight": node["in_weight"],
                "out_weight": node["out_weight"],
                "total_activity_weight": total_activity,
                "self_loop_weight": node["self_loop_weight"],
                "is_unknown_or_external_work_grid": node["grid_id"] == "0",
            }
        )
    nodes.sort(key=lambda row: (-row["total_activity_weight"], row["grid_id"]))
    return {
        "schema": UNICOM_LATENT_MOBILITY_SCHEMA,
        "dataset_id": UNICOM_LATENT_MOBILITY_DATASET_ID,
        "source": "fitted directed graph aggregated from local China Unicom OD rows; no grid geometry dictionary in supplied zip",
        "source_ref": source_ref,
        "created_at": created_at,
        "temporal_extent": "2023-05",
        "record_counts": {
            "raw_rows": len(records),
            "directed_edges": len(edges),
            "nodes": len(nodes),
            "home_nodes": len({edge["home_grid_id"] for edge in edges}),
            "work_nodes": len({edge["work_grid_id"] for edge in edges}),
        },
        "summary": {
            "total_expanded_population": total_weight,
            "self_loop_expanded_population": self_loop_weight,
            "unknown_or_external_work_grid_expanded_population": unknown_work_weight,
            "top_edges": edges[:10],
            "top_nodes": nodes[:10],
        },
        "edges": edges,
        "nodes": nodes,
        "mmfe_target_roles": [
            "mobility_activity",
            "commuting_od",
            "simulator_context",
            "planner_targeting",
            "mmfe_alignment",
        ],
        "synthetic_flags": [{"dataset_id": UNICOM_LATENT_MOBILITY_DATASET_ID, "status": "fitted_proxy"}],
        "claim_boundary": {
            "max_claim_level": "exploratory_only",
            "reason": (
                "The OD weights are from real local rows, but this graph has no coordinates because "
                "the supplied package does not include the grid geometry dictionary."
            ),
        },
        "limitations": [
            "grid_geometry_dictionary_missing",
            "latent_graph_over_grid_ids_not_spatial_od_geometry",
            "work_grid_zero_meaning_unverified_unknown_or_external",
            "not_travel_time_or_traffic_flow",
            "not_observed_policy_outcome",
        ],
        "empirical_superiority_claim": False,
    }


def build_fitted_gap_filling_mmfe_state_input(
    *,
    population_proxy: dict[str, Any],
    mobility_graph: dict[str, Any],
    timestamp: str | None = None,
) -> dict[str, Any]:
    """Convert fitted gap-filling artifacts into an MMFE UWM state input."""

    from .mmfe_state_input import build_uwm_state_input_from_semantic_product

    admin_rows = population_proxy.get("admin_rows") or []
    edges = mobility_graph.get("edges") or []
    payload = build_uwm_state_input_from_semantic_product(
        {
            "product_id": "mmfe-uwm-fitted-gap-filling-2026-07-05",
            "product_type": "semantic_fusion_product",
            "version": "0.1",
            "quality": {"score": 0.46},
        },
        semantic_relations=[
            {
                "semantic_relation_type": "admin_unit_has_fitted_population",
                "uwm_usage": "population_vulnerability",
                "relation_count": len(admin_rows),
            },
            {
                "semantic_relation_type": "unicom_grid_has_latent_commuting_edge",
                "uwm_usage": "mobility_activity",
                "relation_count": len(edges),
            },
        ],
        input_contract={
            "spatial_unit": {
                "unit_type": "township_admin_unit_and_unicom_grid_id_graph",
                "crs": "mixed_epsg4326_admin_plus_unicom_grid_ids_without_geometry",
                "feature_count": len(admin_rows),
            },
            "role_bindings": [
                {
                    "role": "district_population_total_preserving_downscale",
                    "uwm_role": "population_vulnerability",
                    "object_type": "admin_unit_numeric_attribute",
                    "source_dataset_id": str(population_proxy.get("dataset_id")),
                    "synthetic_status": "fitted_proxy",
                },
                {
                    "role": "unicom_latent_commuting_edge_weight",
                    "uwm_role": "mobility_activity",
                    "object_type": "directed_graph_edge_without_geometry",
                    "source_dataset_id": str(mobility_graph.get("dataset_id")),
                    "synthetic_status": "fitted_proxy",
                },
            ],
        },
        timestamp=timestamp,
    )
    payload["source_fitted_gap_filling"] = {
        "population_dataset_id": population_proxy.get("dataset_id"),
        "mobility_dataset_id": mobility_graph.get("dataset_id"),
        "population_summary": population_proxy.get("summary"),
        "mobility_summary": mobility_graph.get("summary"),
        "empirical_superiority_claim": False,
    }
    payload["warnings"].append(
        "fitted proxies cannot support empirical superiority claims without observed holdout or authoritative source replacement"
    )
    return payload


def write_fitted_gap_filling_snapshot(
    *,
    output_dir: str | Path,
    ghsl_rows: list[dict[str, Any]],
    district_rows: list[dict[str, Any]],
    unicom_records: list[dict[str, Any]],
    source_ref: str,
    created_at: str,
) -> dict[str, Any]:
    """Persist fitted gap-filling artifacts and a snapshot manifest."""

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    population_proxy = build_population_downscaling_proxy(
        ghsl_rows=ghsl_rows,
        district_rows=district_rows,
        source_ref=source_ref,
        created_at=created_at,
    )
    mobility_graph = build_unicom_latent_mobility_graph(
        records=unicom_records,
        source_ref=source_ref,
        created_at=created_at,
    )
    state_input = build_fitted_gap_filling_mmfe_state_input(
        population_proxy=population_proxy,
        mobility_graph=mobility_graph,
        timestamp=created_at,
    )
    _write_json(output_path / "population_downscaling_proxy.json", population_proxy)
    _write_rows_csv(output_path / "population_downscaling_admin_rows.csv", population_proxy["admin_rows"])
    _write_json(output_path / "unicom_latent_mobility_graph.json", mobility_graph)
    _write_rows_csv(output_path / "unicom_latent_mobility_edges.csv", mobility_graph["edges"])
    _write_rows_csv(output_path / "unicom_latent_mobility_nodes.csv", mobility_graph["nodes"])
    _write_json(output_path / "mmfe_uwm_state_input_fitted_gap_filling.json", state_input)
    manifest = {
        "schema": FITTED_SNAPSHOT_SCHEMA,
        "dataset_id": "uwm_fitted_gap_filling_2026_07_05",
        "source_dataset_ids": [
            "ghsl_admin_zonal_proxy_alignment",
            "chongqing_district_population_stats_2021_local",
            "chongqing_unicom_commuting_2023_local",
        ],
        "created_at": created_at,
        "source_ref": source_ref,
        "files": {
            "population_downscaling_proxy": "population_downscaling_proxy.json",
            "population_downscaling_admin_rows": "population_downscaling_admin_rows.csv",
            "unicom_latent_mobility_graph": "unicom_latent_mobility_graph.json",
            "unicom_latent_mobility_edges": "unicom_latent_mobility_edges.csv",
            "unicom_latent_mobility_nodes": "unicom_latent_mobility_nodes.csv",
            "mmfe_state_input": "mmfe_uwm_state_input_fitted_gap_filling.json",
        },
        "record_counts": {
            "population_admin_rows": population_proxy["record_counts"]["admin_rows"],
            "mobility_edges": mobility_graph["record_counts"]["directed_edges"],
            "mobility_nodes": mobility_graph["record_counts"]["nodes"],
        },
        "summary": {
            "population": population_proxy["summary"],
            "mobility": {
                key: value
                for key, value in mobility_graph["summary"].items()
                if key not in {"top_edges", "top_nodes"}
            },
        },
        "synthetic_flags": [
            {"dataset_id": POPULATION_DOWNSCALING_DATASET_ID, "status": "fitted_proxy"},
            {"dataset_id": UNICOM_LATENT_MOBILITY_DATASET_ID, "status": "fitted_proxy"},
        ],
        "claim_boundary": {
            "max_claim_level": "exploratory_only",
            "reason": "Fitted gap-filling improves simulator completeness but cannot replace observed or authoritative data.",
        },
        "limitations": sorted(
            set(population_proxy["limitations"] + mobility_graph["limitations"])
        ),
        "empirical_superiority_claim": False,
    }
    _write_json(output_path / "snapshot_manifest.json", manifest)
    return manifest


def _allocation_weights(rows: list[dict[str, Any]]) -> tuple[str, list[float]]:
    population_weights = [_float(row.get("population_proxy_sum")) for row in rows]
    if sum(population_weights) > 0:
        return "ghsl_population_proxy_sum", population_weights
    built_weights = [_float(row.get("built_surface_proxy_sum")) for row in rows]
    if sum(built_weights) > 0:
        return "ghsl_built_surface_proxy_sum_fallback", built_weights
    return "equal_weight_fallback", [1.0 for _ in rows]


def _fallback_admin_unit_id(district: dict[str, Any]) -> str:
    admin_code = str(district.get("admin_code") or "").strip() or "unknown_admin_code"
    district_name = str(district.get("district_name") or "").strip() or "unknown_district"
    return f"{admin_code}|{district_name}|district_fallback"


def _allocate_total(total: float, weights: list[float]) -> list[float]:
    if not weights:
        return []
    weight_sum = sum(weights)
    if weight_sum <= 0:
        weights = [1.0 for _ in weights]
        weight_sum = float(len(weights))
    allocations = [round(total * weight / weight_sum, 6) for weight in weights]
    residual = round(total - sum(allocations), 6)
    if allocations and residual:
        target_index = max(range(len(weights)), key=lambda index: weights[index])
        allocations[target_index] = round(allocations[target_index] + residual, 6)
    return allocations


def _count_values(values: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        key = str(value or "unknown")
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _norm_key(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "")


def _grid_id(value: Any) -> str:
    try:
        return str(int(float(value)))
    except (TypeError, ValueError):
        return str(value or "").strip()


def _int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _float(value: Any) -> float:
    try:
        return round(float(value), 6)
    except (TypeError, ValueError):
        return 0.0


def _write_rows_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
