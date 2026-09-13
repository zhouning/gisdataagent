from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path
from typing import Any


SPATIAL_STATE_SCHEMA = "territory_world_model.spatial_rollout_state.v2"
SIMULATOR_TRACE_SCHEMA = "territory_world_model.spatial_simulator_trace.v1"
SIMULATOR_BACKEND = "deterministic_gis_rule_state_transition"

OBJECTIVE_WEIGHTS = {
    "planning_compatibility": 0.30,
    "farmland_protection": 0.22,
    "ecological_protection": 0.18,
    "urban_alignment": 0.12,
    "review_readiness": 0.10,
    "compactness_score": 0.08,
}


def _stable_sha256(value: Any) -> str:
    material = json.dumps(value, ensure_ascii=False, default=str, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(material.encode("utf-8")).hexdigest()


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return default if math.isnan(number) else number


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _read_csv(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _compactness(geometry: Any) -> float:
    if geometry.is_empty or geometry.area <= 0 or geometry.length <= 0:
        return 0.0
    return max(0.0, min(1.0, (4.0 * math.pi * float(geometry.area)) / (float(geometry.length) ** 2)))


def _union(items: list[Any], unary_union: Any, empty_geometry: Any) -> Any:
    return unary_union(items) if items else empty_geometry


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def load_optimization_spatial_runtime(root: Path) -> dict[str, Any]:
    """Load the spatial inputs used by the online recursive simulator.

    The returned object is an in-memory runtime input, not an API payload. It
    retains Shapely geometries so each transition can materialize its next
    spatial state from the previously written-back action set.
    """

    action_path = root / "action_space.geojson"
    membership_path = root / "scenario_project_membership.csv"
    constraint_path = root / "constraint_masks.geojson"
    paths = {
        "action_space": action_path,
        "membership": membership_path,
        "constraint_masks": constraint_path,
    }
    missing_paths = [str(path) for path in paths.values() if not path.exists()]
    if missing_paths:
        return {
            "available": False,
            "errors": ["missing_spatial_source", *missing_paths],
            "source_files": {key: str(path) for key, path in paths.items()},
        }

    try:
        from shapely.geometry import GeometryCollection, shape as shapely_shape
        from shapely.ops import unary_union

        action_payload = _read_json(action_path)
        constraint_payload = _read_json(constraint_path)
        memberships = _read_csv(membership_path)
        action_records: dict[str, dict[str, Any]] = {}
        duplicate_action_ids: list[str] = []
        for feature in action_payload.get("features") or []:
            properties = dict(feature.get("properties") or {})
            action_id = str(properties.get("action_id") or "")
            geometry = shapely_shape(feature.get("geometry")) if feature.get("geometry") else None
            if not action_id or geometry is None or geometry.is_empty:
                continue
            if action_id in action_records:
                duplicate_action_ids.append(action_id)
                continue
            action_records[action_id] = {
                "geometry": geometry if geometry.is_valid else geometry.buffer(0),
                "properties": properties,
            }

        required_objectives = {"pbf_overlap_m2", "eco_overlap_m2", "urban_outside_m2", "planning_conflict_m2"}
        available_objectives = {
            str((feature.get("properties") or {}).get("objective_id") or "")
            for feature in constraint_payload.get("features") or []
        }
        missing_objectives = sorted(required_objectives - available_objectives)
        crs = str((((action_payload.get("crs") or {}).get("properties") or {}).get("name")) or "")
        errors: list[str] = []
        if duplicate_action_ids:
            errors.extend(["duplicate_action_id", *sorted(set(duplicate_action_ids))])
        if not action_records:
            errors.append("no_valid_action_geometry")
        if not crs:
            errors.append("missing_action_crs")
        if missing_objectives:
            errors.extend(["missing_constraint_objective", *missing_objectives])

        membership_by_scenario: dict[str, list[dict[str, Any]]] = {}
        for row in memberships:
            membership_by_scenario.setdefault(str(row.get("scenario_id") or ""), []).append(row)
        for rows in membership_by_scenario.values():
            rows.sort(key=lambda row: _safe_int(row.get("selection_order")))

        return {
            "available": not errors,
            "errors": errors,
            "root": str(root),
            "crs": crs,
            "action_records": action_records,
            "membership_by_scenario": membership_by_scenario,
            "unary_union": unary_union,
            "empty_geometry": GeometryCollection(),
            "source_files": {key: str(path) for key, path in paths.items()},
            "source_sha256": {key: _file_sha256(path) for key, path in paths.items()},
            "relation_edge_source": "action_space_properties_compiled_from_source_geometry_intersections",
        }
    except (ImportError, OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        return {
            "available": False,
            "errors": [f"spatial_runtime_load_error:{type(exc).__name__}"],
            "source_files": {key: str(path) for key, path in paths.items()},
        }


def compile_optimization_spatial_profiles(
    root: Path,
    *,
    scenario_specs: dict[str, dict[str, Any]],
    horizon: int,
    hard_constraint_tolerance_m2: float,
) -> dict[str, dict[str, Any]]:
    """Materialize each candidate as recursive GIS states.

    This is the TWM renderer/simulator boundary for the optimization fixture:
    source geometries and action memberships are applied period by period, and
    every derived relation, objective and hard constraint is recalculated from
    the materialized state.
    """

    action_path = root / "action_space.geojson"
    membership_path = root / "scenario_project_membership.csv"
    constraint_path = root / "constraint_masks.geojson"
    source_paths = {
        "action_space": str(action_path),
        "membership": str(membership_path),
        "constraint_masks": str(constraint_path),
    }
    profiles = {
        scenario_id: {
            "available": False,
            "no_action_baseline": "baseline" in str(spec.get("scenario_type") or scenario_id).lower(),
            "periods": [],
            "action_ids": [],
            "transition_evaluation_count": 0,
            "errors": [],
            "provenance": source_paths,
        }
        for scenario_id, spec in scenario_specs.items()
        if scenario_id
    }
    missing_paths = [str(path) for path in (action_path, membership_path, constraint_path) if not path.exists()]
    if missing_paths:
        for profile in profiles.values():
            profile["errors"] = ["missing_spatial_source"] + missing_paths
        return profiles

    try:
        from shapely.geometry import GeometryCollection, shape as shapely_shape
        from shapely.ops import unary_union

        action_payload = _read_json(action_path)
        constraint_payload = _read_json(constraint_path)
        memberships = _read_csv(membership_path)
        empty_geometry = GeometryCollection()

        action_records: dict[str, dict[str, Any]] = {}
        for feature in action_payload.get("features") or []:
            properties = dict(feature.get("properties") or {})
            action_id = str(properties.get("action_id") or "")
            geometry = shapely_shape(feature.get("geometry")) if feature.get("geometry") else None
            if action_id and geometry is not None and not geometry.is_empty:
                action_records[action_id] = {
                    "geometry": geometry if geometry.is_valid else geometry.buffer(0),
                    "properties": properties,
                }

        required_objectives = {"pbf_overlap_m2", "eco_overlap_m2", "urban_outside_m2", "planning_conflict_m2"}
        available_objectives: set[str] = set()
        for feature in constraint_payload.get("features") or []:
            properties = dict(feature.get("properties") or {})
            objective_id = str(properties.get("objective_id") or "")
            if objective_id:
                available_objectives.add(objective_id)
        missing_objectives = sorted(required_objectives - available_objectives)
        if missing_objectives:
            for profile in profiles.values():
                profile["errors"] = ["missing_constraint_objective", *missing_objectives]
            return profiles
        membership_by_scenario: dict[str, list[dict[str, Any]]] = {}
        for row in memberships:
            membership_by_scenario.setdefault(str(row.get("scenario_id") or ""), []).append(row)
        crs = str((((action_payload.get("crs") or {}).get("properties") or {}).get("name")) or "")

        for scenario_id, profile in profiles.items():
            members = sorted(
                membership_by_scenario.get(scenario_id) or [],
                key=lambda row: _safe_int(row.get("selection_order")),
            )
            missing_action_ids = [
                str(row.get("action_id") or "")
                for row in members
                if str(row.get("action_id") or "") not in action_records
            ]
            if missing_action_ids:
                profile["errors"] = ["missing_action_geometry", *missing_action_ids]
                continue
            if not members and not profile.get("no_action_baseline"):
                profile["errors"] = ["missing_scenario_action_membership"]
                continue

            periods = []
            for period in range(1, horizon + 1):
                end = int(math.ceil(len(members) * period / horizon)) if members else 0
                periods.append(
                    _spatial_period_snapshot(
                        scenario_id=scenario_id,
                        period=period,
                        horizon=horizon,
                        members=members[:end],
                        total_action_count=len(members),
                        action_records=action_records,
                        hard_constraint_tolerance_m2=hard_constraint_tolerance_m2,
                        crs=crs,
                        unary_union=unary_union,
                        empty_geometry=empty_geometry,
                    )
                )
            profile.update(
                {
                    "available": True,
                    "periods": periods,
                    "crs": crs,
                    "action_ids": [str(row.get("action_id") or "") for row in members],
                    "transition_evaluation_count": len(periods),
                }
            )
            final = periods[-1]
            profile.update(
                {
                    "final_bbox": final.get("bbox"),
                    "final_geometry_sha256": final.get("geometry_sha256"),
                    "final_state_sha256": final.get("state_sha256"),
                    "final_constraint_recheck": final.get("constraint_recheck"),
                }
            )
    except (ImportError, OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        for profile in profiles.values():
            if not profile.get("available"):
                profile["errors"] = list(profile.get("errors") or []) + [f"spatial_compilation_error:{type(exc).__name__}"]
    return profiles


def _spatial_period_snapshot(
    *,
    scenario_id: str,
    period: int,
    horizon: int,
    members: list[dict[str, Any]],
    total_action_count: int,
    action_records: dict[str, dict[str, Any]],
    hard_constraint_tolerance_m2: float,
    crs: str,
    unary_union: Any,
    empty_geometry: Any,
    parent_state_sha256: str | None = None,
    action_delta_ids: list[str] | None = None,
) -> dict[str, Any]:
    action_ids = [str(row.get("action_id") or "") for row in members if str(row.get("action_id") or "")]
    records = [action_records[action_id] for action_id in action_ids]
    geometries = [record["geometry"] for record in records]
    geometry = _union(geometries, unary_union, empty_geometry)
    area_m2 = float(geometry.area) if not geometry.is_empty else 0.0

    pbf_overlap = sum(_safe_float(record["properties"].get("pbf_overlap_m2")) for record in records)
    eco_overlap = sum(_safe_float(record["properties"].get("eco_overlap_m2")) for record in records)
    urban_inside = sum(_safe_float(record["properties"].get("urban_inside_m2")) for record in records)
    planning_conflict_m2 = sum(_safe_float(record["properties"].get("planning_conflict_m2")) for record in records)
    planning_relation_count = sum(
        int(_safe_float(record["properties"].get("action_area_m2")) > 0)
        for record in records
    )
    pbf_relation_count = sum(
        int(_safe_float(record["properties"].get("pbf_overlap_m2")) > hard_constraint_tolerance_m2)
        for record in records
    )
    eco_relation_count = sum(
        int(_safe_float(record["properties"].get("eco_overlap_m2")) > hard_constraint_tolerance_m2)
        for record in records
    )
    urban_relation_count = sum(
        int(_safe_float(record["properties"].get("urban_inside_m2")) > 0)
        for record in records
    )
    planning_conflict_action_count = sum(
        int(_safe_float(record["properties"].get("planning_conflict_m2")) > hard_constraint_tolerance_m2)
        for record in records
    )
    farmland_loss_m2 = sum(_safe_float(record["properties"].get("ZYGDMJ")) for record in records)
    ecological_special_area_m2 = sum(_safe_float(record["properties"].get("SJSTHXMJ")) for record in records)
    review_load_count = sum(_safe_int(record["properties"].get("review_hit_count")) for record in records)
    compactness_score = _compactness(geometry)

    failed_constraints = []
    if pbf_overlap > hard_constraint_tolerance_m2:
        failed_constraints.append("CONSTRAINT-PBF")
    if eco_overlap > hard_constraint_tolerance_m2:
        failed_constraints.append("CONSTRAINT-ECO")
    hard_violation = pbf_overlap + eco_overlap
    planning_compatibility = 1.0 - min(1.0, planning_conflict_m2 / max(area_m2, 1.0)) if area_m2 else 1.0
    farmland_protection = 1.0 - min(1.0, farmland_loss_m2 / max(area_m2, 1.0)) if area_m2 else 1.0
    ecological_protection = 1.0 - min(1.0, ecological_special_area_m2 / max(area_m2, 1.0)) if area_m2 else 1.0
    urban_alignment = min(1.0, urban_inside / max(area_m2, 1.0)) if area_m2 else 0.0
    review_readiness = 1.0 - min(1.0, review_load_count / max(len(action_ids) * 4.0, 1.0)) if action_ids else 1.0
    development_capacity = 1.0 - math.exp(-area_m2 / 100_000.0) if area_m2 else 0.0
    quality_score = (
        OBJECTIVE_WEIGHTS["planning_compatibility"] * planning_compatibility
        + OBJECTIVE_WEIGHTS["farmland_protection"] * farmland_protection
        + OBJECTIVE_WEIGHTS["ecological_protection"] * ecological_protection
        + OBJECTIVE_WEIGHTS["urban_alignment"] * urban_alignment
        + OBJECTIVE_WEIGHTS["review_readiness"] * review_readiness
        + OBJECTIVE_WEIGHTS["compactness_score"] * compactness_score
    )
    spatial_objective_score = development_capacity * quality_score if not failed_constraints else 0.0

    geometry_sha256 = "sha256:" + hashlib.sha256(bytes(geometry.wkb)).hexdigest()
    relation_counts = {
        "scenario_contains_action": len(action_ids),
        "action_overlaps_planning_zone": planning_relation_count,
        "action_overlaps_urban_boundary": urban_relation_count,
        "action_overlaps_permanent_basic_farmland": pbf_relation_count,
        "action_overlaps_ecological_redline": eco_relation_count,
        "action_has_planning_conflict": planning_conflict_action_count,
    }
    state_identity = {
        "scenario_id": scenario_id,
        "period": period,
        "parent_state_sha256": parent_state_sha256,
        "action_delta_ids": list(action_delta_ids or []),
        "action_ids": action_ids,
        "geometry_sha256": geometry_sha256,
        "relation_counts": relation_counts,
        "constraint": {
            "pbf_overlap_m2": round(pbf_overlap, 6),
            "eco_overlap_m2": round(eco_overlap, 6),
        },
        "outcome": {
            "planning_conflict_m2": round(planning_conflict_m2, 6),
            "farmland_loss_m2": round(farmland_loss_m2, 6),
            "ecological_special_area_m2": round(ecological_special_area_m2, 6),
            "spatial_objective_score": round(spatial_objective_score, 6),
        },
    }
    return {
        "schema": SPATIAL_STATE_SCHEMA,
        "scenario_id": scenario_id,
        "period": period,
        "horizon": horizon,
        "parent_state_sha256": parent_state_sha256,
        "applied_action_delta_ids": list(action_delta_ids or []),
        "completion_ratio": round(len(action_ids) / max(total_action_count, 1), 6) if total_action_count else 0.0,
        "action_count": len(action_ids),
        "action_ids": action_ids,
        "project_ids": [str(row.get("project_id") or "") for row in members if str(row.get("project_id") or "")],
        "crs": crs,
        "bbox": [round(float(value), 6) for value in geometry.bounds] if not geometry.is_empty else None,
        "area_m2": round(area_m2, 6),
        "geometry_component_count": 0 if geometry.is_empty else len(getattr(geometry, "geoms", [geometry])),
        "geometry_sha256": geometry_sha256,
        "state_sha256": _stable_sha256(state_identity),
        "relation_counts_by_type": relation_counts,
        "constraint_recheck": {
            "passed": not failed_constraints,
            "hard_constraint_tolerance_m2": round(hard_constraint_tolerance_m2, 6),
            "pbf_overlap_m2": round(pbf_overlap, 6),
            "eco_overlap_m2": round(eco_overlap, 6),
            "hard_constraint_violation_m2": round(hard_violation, 6),
            "failed_constraints": failed_constraints,
            "method": "reaggregate_active_action_to_constraint_spatial_relation_edges",
        },
        "outcome_metrics": {
            "planning_conflict_m2": round(planning_conflict_m2, 6),
            "urban_inside_m2": round(urban_inside, 6),
            "farmland_loss_m2": round(farmland_loss_m2, 6),
            "ecological_special_area_m2": round(ecological_special_area_m2, 6),
            "review_load_count": review_load_count,
            "compactness_score": round(compactness_score, 6),
            "development_capacity": round(development_capacity, 6),
            "planning_compatibility": round(planning_compatibility, 6),
            "farmland_protection": round(farmland_protection, 6),
            "ecological_protection": round(ecological_protection, 6),
            "urban_alignment": round(urban_alignment, 6),
            "review_readiness": round(review_readiness, 6),
            "spatial_objective_score": round(spatial_objective_score, 6),
        },
        "objective_contract": {
            "formula": "development_capacity * weighted_spatial_quality",
            "weights": OBJECTIVE_WEIGHTS,
            "source": "current_period_geometry_and_reaggregated_action_to_constraint_relation_edges",
            "production_effect_claim": "not_supported",
        },
        "transition_source": SIMULATOR_BACKEND,
    }


def build_spatial_simulator_trace(
    *,
    candidate_id: str,
    scenario_name: str,
    initial_state_ref: str,
    periods: list[dict[str, Any]],
    evidence_coverage: float,
    synthetic: bool,
    not_for_production: bool,
) -> dict[str, Any]:
    """Convert states created in one simulator execution into an auditable trace."""

    transitions = []
    previous_state_sha = initial_state_ref
    previous_geometry_sha = None
    previous_action_ids: list[str] = []
    previous_objective = 0.0
    previous_relations: dict[str, int] = {}
    for period_state in periods:
        action_ids = list(period_state.get("action_ids") or [])
        action_delta = [action_id for action_id in action_ids if action_id not in previous_action_ids]
        objective = _safe_float((period_state.get("outcome_metrics") or {}).get("spatial_objective_score"))
        relation_counts = {
            str(key): _safe_int(value)
            for key, value in (period_state.get("relation_counts_by_type") or {}).items()
        }
        relation_delta = {
            key: value - previous_relations.get(key, 0)
            for key, value in relation_counts.items()
            if value - previous_relations.get(key, 0)
        }
        constraint = dict(period_state.get("constraint_recheck") or {})
        area_m2 = _safe_float(period_state.get("area_m2"))
        hard_violation = _safe_float(constraint.get("hard_constraint_violation_m2"))
        risk = min(1.0, hard_violation / max(area_m2, 1.0))
        confidence = max(0.0, min(1.0, evidence_coverage, 0.72) - (len(transitions) * 0.02))
        transition_core = {
            "candidate_id": candidate_id,
            "period": period_state.get("period"),
            "input_state_sha256": previous_state_sha,
            "action_delta_ids": action_delta,
            "output_state_sha256": period_state.get("state_sha256"),
        }
        parent_link_verified = period_state.get("parent_state_sha256") == previous_state_sha
        transition = {
            "schema": "territory_world_model.spatial_state_transition.v1",
            **transition_core,
            "transition_sha256": _stable_sha256(transition_core),
            "action": {
                "type": "apply_candidate_spatial_actions" if action_delta else "maintain_current_state",
                "new_action_ids": action_delta,
                "cumulative_action_ids": action_ids,
            },
            "next_state": period_state,
            "state_delta": {
                "geometry_changed": previous_geometry_sha != period_state.get("geometry_sha256"),
                "new_action_count": len(action_delta),
                "cumulative_action_count": len(action_ids),
                "relation_count_delta": relation_delta,
            },
            "outcome": {
                "spatial_objective_score": round(objective, 6),
                "spatial_objective_delta": round(objective - previous_objective, 6),
                "constraint_violation_probability": round(risk, 6),
                "confidence": round(confidence, 6),
            },
            "state_writeback": {
                "applied": parent_link_verified,
                "from_state_sha256": previous_state_sha,
                "to_state_sha256": period_state.get("state_sha256"),
                "parent_link_verified": parent_link_verified,
                "geometry_changed": previous_geometry_sha != period_state.get("geometry_sha256"),
                "relations_recomputed": True,
                "hard_constraints_recomputed": bool(constraint.get("method")),
                "objectives_recomputed": "spatial_objective_score" in (period_state.get("outcome_metrics") or {}),
            },
        }
        transitions.append(transition)
        previous_state_sha = str(period_state.get("state_sha256") or previous_state_sha)
        previous_geometry_sha = period_state.get("geometry_sha256")
        previous_action_ids = action_ids
        previous_objective = objective
        previous_relations = relation_counts

    missing = []
    if synthetic:
        missing.append("authoritative_production_state")
    if not_for_production:
        missing.append("real_observed_transition_holdout")
    trace_core = {
        "candidate_id": candidate_id,
        "initial_state_ref": initial_state_ref,
        "transition_sha256s": [item["transition_sha256"] for item in transitions],
    }
    return {
        "schema": SIMULATOR_TRACE_SCHEMA,
        "status": "completed" if transitions and all(
            bool((item.get("state_writeback") or {}).get("applied")) for item in transitions
        ) else "blocked",
        "simulator_trace_sha256": _stable_sha256(trace_core),
        "candidate_id": candidate_id,
        "scenario_name": scenario_name,
        "backend": {
            "type": SIMULATOR_BACKEND,
            "version": "1.0",
            "execution_mode": "online_recursive_transition_loop",
            "precomputed_period_states_consumed": False,
            "action_conditioned": True,
            "recursive_state_writeback": True,
            "stochastic": False,
            "learned_dynamics": False,
        },
        "initial_state_ref": initial_state_ref,
        "transitions": transitions,
        "transition_evaluation_count": len(transitions),
        "evidence_gate": {
            "passed": not missing,
            "status": "pass" if not missing else "review",
            "coverage": round(max(0.0, min(1.0, evidence_coverage)), 6),
            "missing": missing,
        },
        "claim_boundary": {
            "supported": "deterministic_GIS_rule_mechanism_rollout_on_supplied_candidate_actions",
            "not_supported": "learned_real_world_dynamics_or_production_policy_effect_prediction",
        },
    }


def simulate_optimization_spatial_candidate(
    *,
    runtime: dict[str, Any],
    candidate_id: str,
    scenario_name: str,
    initial_state_ref: str,
    horizon: int,
    hard_constraint_tolerance_m2: float,
    evidence_coverage: float,
    synthetic: bool,
    not_for_production: bool,
    no_action_baseline: bool,
) -> dict[str, Any]:
    """Run one candidate through recursive action-conditioned GIS transitions."""

    runtime_errors = list(runtime.get("errors") or [])
    if not runtime.get("available"):
        return _blocked_spatial_simulator_trace(
            candidate_id=candidate_id,
            scenario_name=scenario_name,
            initial_state_ref=initial_state_ref,
            evidence_coverage=evidence_coverage,
            errors=runtime_errors or ["spatial_runtime_unavailable"],
        )

    members = list((runtime.get("membership_by_scenario") or {}).get(candidate_id) or [])
    action_records = dict(runtime.get("action_records") or {})
    missing_action_ids = [
        str(row.get("action_id") or "")
        for row in members
        if str(row.get("action_id") or "") not in action_records
    ]
    if missing_action_ids:
        return _blocked_spatial_simulator_trace(
            candidate_id=candidate_id,
            scenario_name=scenario_name,
            initial_state_ref=initial_state_ref,
            evidence_coverage=evidence_coverage,
            errors=["missing_action_geometry", *missing_action_ids],
        )
    if not members and not no_action_baseline:
        return _blocked_spatial_simulator_trace(
            candidate_id=candidate_id,
            scenario_name=scenario_name,
            initial_state_ref=initial_state_ref,
            evidence_coverage=evidence_coverage,
            errors=["missing_scenario_action_membership"],
        )

    period_states: list[dict[str, Any]] = []
    active_members: list[dict[str, Any]] = []
    parent_state_sha256 = initial_state_ref
    for period in range(1, horizon + 1):
        scheduled_end = int(math.ceil(len(members) * period / horizon)) if members else 0
        action_delta_members = members[len(active_members):scheduled_end]
        active_members = [*active_members, *action_delta_members]
        action_delta_ids = [
            str(row.get("action_id") or "")
            for row in action_delta_members
            if str(row.get("action_id") or "")
        ]
        next_state = _spatial_period_snapshot(
            scenario_id=candidate_id,
            period=period,
            horizon=horizon,
            members=active_members,
            total_action_count=len(members),
            action_records=action_records,
            hard_constraint_tolerance_m2=hard_constraint_tolerance_m2,
            crs=str(runtime.get("crs") or ""),
            unary_union=runtime["unary_union"],
            empty_geometry=runtime["empty_geometry"],
            parent_state_sha256=parent_state_sha256,
            action_delta_ids=action_delta_ids,
        )
        period_states.append(next_state)
        parent_state_sha256 = str(next_state.get("state_sha256") or parent_state_sha256)

    trace = build_spatial_simulator_trace(
        candidate_id=candidate_id,
        scenario_name=scenario_name,
        initial_state_ref=initial_state_ref,
        periods=period_states,
        evidence_coverage=evidence_coverage,
        synthetic=synthetic,
        not_for_production=not_for_production,
    )
    trace["execution_contract"] = {
        "renderer_input": "candidate_action_membership_and_spatial_source_fingerprints",
        "transition": "previous_written_back_state_plus_current_action_delta_to_next_spatial_state",
        "recomputation_each_period": ["cumulative_geometry", "spatial_relations", "hard_constraints", "spatial_objectives"],
        "planner_consumption": "trace_only",
        "fail_closed": True,
    }
    trace["runtime_input_audit"] = {
        "source_files": dict(runtime.get("source_files") or {}),
        "source_sha256": dict(runtime.get("source_sha256") or {}),
        "relation_edge_source": runtime.get("relation_edge_source"),
        "candidate_action_count": len(members),
        "horizon": horizon,
    }
    return trace


def _blocked_spatial_simulator_trace(
    *,
    candidate_id: str,
    scenario_name: str,
    initial_state_ref: str,
    evidence_coverage: float,
    errors: list[str],
) -> dict[str, Any]:
    return {
        "schema": SIMULATOR_TRACE_SCHEMA,
        "status": "blocked",
        "simulator_trace_sha256": _stable_sha256(
            {"candidate_id": candidate_id, "initial_state_ref": initial_state_ref, "errors": errors}
        ),
        "candidate_id": candidate_id,
        "scenario_name": scenario_name,
        "backend": {
            "type": SIMULATOR_BACKEND,
            "version": "1.0",
            "execution_mode": "online_recursive_transition_loop",
            "precomputed_period_states_consumed": False,
            "action_conditioned": True,
            "recursive_state_writeback": True,
            "stochastic": False,
            "learned_dynamics": False,
        },
        "initial_state_ref": initial_state_ref,
        "transitions": [],
        "transition_evaluation_count": 0,
        "errors": errors,
        "evidence_gate": {
            "passed": False,
            "status": "blocked",
            "coverage": round(max(0.0, min(1.0, evidence_coverage)), 6),
            "missing": errors,
        },
        "claim_boundary": {
            "supported": "fail_closed_spatial_simulator_input_validation",
            "not_supported": "candidate_selection_without_complete_spatial_trace",
        },
    }


__all__ = [
    "SIMULATOR_BACKEND",
    "SIMULATOR_TRACE_SCHEMA",
    "SPATIAL_STATE_SCHEMA",
    "build_spatial_simulator_trace",
    "compile_optimization_spatial_profiles",
    "load_optimization_spatial_runtime",
    "simulate_optimization_spatial_candidate",
]
