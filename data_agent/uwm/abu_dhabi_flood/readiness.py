"""Readiness and hybrid-model contract for the Abu Dhabi flood candidate."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .smartmakani_acquisition import TARGET_CRS, canonical_json_bytes

READINESS_SCHEMA = "gwm.abu_dhabi_flood.hybrid_readiness.v1"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(canonical_json_bytes(payload))
    temporary.replace(path)


def _path_label(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _count_and_percent(mask: Any, denominator: int) -> dict[str, float | int]:
    count = int(mask.sum())
    return {
        "count": count,
        "percent": round(count / denominator * 100.0 if denominator else 0.0, 6),
    }


def _finite_summary(values: Any) -> dict[str, float | int | None]:
    import numpy as np

    array = np.asarray(values, dtype="float64")
    array = array[np.isfinite(array)]
    if not len(array):
        return {
            "count": 0,
            "minimum": None,
            "median": None,
            "p95": None,
            "maximum": None,
        }
    return {
        "count": int(len(array)),
        "minimum": float(array.min()),
        "median": float(np.median(array)),
        "p95": float(np.quantile(array, 0.95)),
        "maximum": float(array.max()),
    }


def audit_registered_engineering_fields(pipelines: Any) -> dict[str, Any]:
    """Audit candidate engineering fields without assigning unverified units."""

    import numpy as np
    import pandas as pd

    required = {
        "pipe_length",
        "pipe_diameter",
        "invert_level_upstream",
        "invert_level_downstream",
        "gradient",
        "recomputed_length_m",
        "geometry_z_both_zero",
    }
    missing = sorted(required.difference(pipelines.columns))
    if missing:
        raise ValueError(f"registered_engineering_audit_missing_columns:{','.join(missing)}")

    row_count = len(pipelines)
    pipe_length = pd.to_numeric(pipelines["pipe_length"], errors="coerce")
    geometry_length = pd.to_numeric(pipelines["recomputed_length_m"], errors="coerce")
    comparable_length = (
        pipe_length.notna()
        & geometry_length.notna()
        & pipe_length.gt(0)
        & geometry_length.gt(0)
    )
    relative_length_delta = (
        (pipe_length - geometry_length).abs()
        / np.maximum(pipe_length, geometry_length)
    )

    diameter = pd.to_numeric(pipelines["pipe_diameter"], errors="coerce")
    invert_up = pd.to_numeric(pipelines["invert_level_upstream"], errors="coerce")
    invert_down = pd.to_numeric(pipelines["invert_level_downstream"], errors="coerce")
    gradient = pd.to_numeric(pipelines["gradient"], errors="coerce")
    sentinel_values = (-999.0, -99.0, 999.0, 9999.0)

    def sentinel_counts(values: Any) -> dict[str, int]:
        return {
            str(value): int(np.isclose(values.to_numpy(dtype="float64"), value).sum())
            for value in sentinel_values
        }

    plausible_up = invert_up.between(-100.0, 200.0, inclusive="both")
    plausible_down = invert_down.between(-100.0, 200.0, inclusive="both")
    return {
        "row_count": row_count,
        "pipe_length": {
            "numeric": _count_and_percent(pipe_length.notna(), row_count),
            "nonpositive": _count_and_percent(pipe_length.le(0), row_count),
            "geometry_comparable": _count_and_percent(comparable_length, row_count),
            "within_1_percent_if_source_unit_is_m": _count_and_percent(
                comparable_length & relative_length_delta.le(0.01),
                row_count,
            ),
            "relative_delta": _finite_summary(relative_length_delta[comparable_length]),
            "source_unit_verified": False,
        },
        "pipe_diameter": {
            "numeric": _count_and_percent(diameter.notna(), row_count),
            "positive": _count_and_percent(diameter.gt(0), row_count),
            "value_summary": _finite_summary(diameter),
            "source_unit_verified": False,
        },
        "invert_level": {
            "upstream_numeric": _count_and_percent(invert_up.notna(), row_count),
            "downstream_numeric": _count_and_percent(invert_down.notna(), row_count),
            "upstream_sentinel_value_counts": sentinel_counts(invert_up),
            "downstream_sentinel_value_counts": sentinel_counts(invert_down),
            "upstream_absolute_ge_900": _count_and_percent(
                invert_up.abs().ge(900), row_count
            ),
            "downstream_absolute_ge_900": _count_and_percent(
                invert_down.abs().ge(900), row_count
            ),
            "both_plausible_candidate": _count_and_percent(
                plausible_up & plausible_down,
                row_count,
            ),
            "upstream_summary": _finite_summary(invert_up),
            "downstream_summary": _finite_summary(invert_down),
            "vertical_datum_verified": False,
            "source_unit_verified": False,
        },
        "gradient": {
            "numeric": _count_and_percent(gradient.notna(), row_count),
            "negative": _count_and_percent(gradient.lt(0), row_count),
            "absolute_ge_1_candidate_outlier": _count_and_percent(
                gradient.abs().ge(1), row_count
            ),
            "value_summary": _finite_summary(gradient),
            "source_unit_verified": False,
        },
        "geometry_z": {
            "both_zero": _count_and_percent(
                pipelines["geometry_z_both_zero"].fillna(False), row_count
            ),
            "z_source_unit_or_datum_verified": False,
        },
    }


def _architecture_contract() -> dict[str, Any]:
    return {
        "traditional_model": {
            "role": [
                "physics_baseline",
                "mass_and_boundary_constraint",
                "calibration_reference",
                "high_risk_validation",
                "fallback_runtime",
            ],
            "required_inputs": [
                "surface_patch_geometry_and_elevation",
                "authoritative_drainage_links_and_units",
                "event_rainfall_time_series",
                "pump_gate_operations",
                "coastal_outfall_boundary_time_series",
            ],
            "current_status": "blocked_missing_engineering_and_event_inputs",
        },
        "gwm": {
            "role": [
                "action_conditioned_state_representation",
                "fast_scenario_rollout",
                "uncertainty_and_distribution_shift_detection",
                "planner_candidate_screening",
            ],
            "training_sources": [
                "admitted_observed_event_windows",
                "admitted_traditional_model_rollouts",
                "operator_action_history",
            ],
            "current_status": "blocked_no_observed_event_or_admitted_physics_training_panel",
            "must_not_be_used_as": [
                "sole_physics_authority",
                "unconstrained_city_scale_extrapolator",
                "replacement_for_event_calibration",
            ],
        },
        "coupling": {
            "forward_path": "gwm_screens_candidates_then_traditional_model_validates_shortlist",
            "residual_form": (
                "optional_gwm_residual_correction_on_top_of_traditional_state_transition"
            ),
            "shadow_validation": "required_for_high_risk_and_out_of_distribution_scenarios",
            "fallback": "traditional_model_or_no_claim_when_uncertainty_gate_fails",
            "hard_constraints": [
                "mass_balance",
                "nonnegative_storage",
                "admitted_boundary_conditions",
                "asset_action_bounds",
            ],
            "replacement_boundary": (
                "gwm_may_replace_expensive_inner_loop_search_only_after_blind_validation"
            ),
        },
        "state_channels": [
            {
                "channel": "surface_water_depth_m",
                "traditional_owner": "surface_solver",
                "gwm_role": "latent_state_and_fast_forecast",
                "current_status": "blocked_surface_patch_crosswalk_missing",
            },
            {
                "channel": "drainage_link_storage_m3",
                "traditional_owner": "network_solver",
                "gwm_role": "graph_dynamics_embedding",
                "current_status": "blocked_network_units_and_direction_unverified",
            },
            {
                "channel": "rainfall_and_tide_forcing",
                "traditional_owner": "boundary_forcing",
                "gwm_role": "forcing_encoder_and_shift_detector",
                "current_status": "blocked_event_time_series_missing",
            },
            {
                "channel": "pump_gate_action",
                "traditional_owner": "operational_constraint",
                "gwm_role": "counterfactual_action_conditioning",
                "current_status": "blocked_operation_history_missing",
            },
        ],
    }


def build_hybrid_readiness(dataset_root: Path) -> dict[str, Any]:
    """Build a deterministic readiness audit from frozen Abu Dhabi artifacts."""

    import geopandas as gpd

    root = dataset_root.resolve()
    inventory_path = root / "manifest.json"
    network_manifest_path = (
        root
        / "derived/makani_registered/registered_network_candidate_manifest.json"
    )
    network_audit_path = root / "derived/makani_registered/registered_network_candidate_audit.json"
    surface_audit_path = (
        root / "derived/smartmakani/supporting_surface_candidate_audit.json"
    )
    surface_clip_manifest_path = (
        root
        / "derived/smartmakani/surface_clip_candidate/"
        "surface_clip_candidate_manifest.json"
    )
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    network_manifest = json.loads(network_manifest_path.read_text(encoding="utf-8"))
    network_audit = json.loads(network_audit_path.read_text(encoding="utf-8"))
    surface_audit = (
        json.loads(surface_audit_path.read_text(encoding="utf-8"))
        if surface_audit_path.exists()
        else None
    )
    surface_clip = (
        json.loads(surface_clip_manifest_path.read_text(encoding="utf-8"))
        if surface_clip_manifest_path.exists()
        else None
    )
    if surface_audit is not None:
        if surface_audit.get("admission", {}).get("k0_opened") is not False:
            raise ValueError("hybrid_readiness_surface_audit_opened_k0")
        if (
            surface_audit.get("admission", {}).get(
                "surface_patch_contract_compiled"
            )
            is not False
        ):
            raise ValueError("hybrid_readiness_surface_patch_compiled")
    if surface_clip is not None:
        if surface_clip.get("schema") != "gwm.abu_dhabi_flood.surface_clip_bundle.v1":
            raise ValueError("hybrid_readiness_surface_clip_schema_changed")
        if surface_clip.get("admission", {}).get("k0_opened") is not False:
            raise ValueError("hybrid_readiness_surface_clip_opened_k0")
        if (
            surface_clip.get("admission", {}).get(
                "surface_patch_contract_compiled"
            )
            is not False
        ):
            raise ValueError("hybrid_readiness_surface_clip_compiled_surface_patch")
        for dataset in surface_clip["datasets"]:
            child_path = root / dataset["manifest_path"]
            if _sha256_file(child_path) != dataset["manifest_sha256"]:
                raise ValueError(
                    f"hybrid_readiness_surface_clip_hash_mismatch:"
                    f"{dataset['dataset_key']}"
                )
    pipeline_metadata = network_manifest["outputs"]["pipelines_geoparquet"]
    pipeline_path = root / pipeline_metadata["path"]
    if _sha256_file(pipeline_path) != pipeline_metadata["sha256"]:
        raise ValueError("hybrid_readiness_pipeline_checksum_mismatch")
    pipelines = gpd.read_parquet(pipeline_path)
    engineering = audit_registered_engineering_fields(pipelines)
    facilities = network_audit["facility_semantics"]
    topology = network_audit["topology"]

    blockers = [
        {
            "blocker_id": "engineering_units_and_vertical_datum",
            "status": "blocked",
            "evidence": (
                "pipe diameter, pipe length, invert and Z units/datum are not authoritative"
            ),
        },
        {
            "blocker_id": "surface_patch_crosswalk",
            "status": "blocked",
            "evidence": (
                "public contours and buildings are static candidates only; registered network "
                "target clipping and two invalid-building repairs are complete, but registered "
                "network nodes_are_surface_patches=false and no hydrologically conditioned "
                "surface-to-network crosswalk has been compiled"
            ),
        },
        {
            "blocker_id": "residual_network_endpoint_relations",
            "status": "blocked",
            "evidence": (
                f"{facilities['residual_unmatched_pipeline_endpoint_count']} supported "
                "endpoints lack a 1 m facility candidate"
            ),
        },
        {
            "blocker_id": "event_forcing_and_observations",
            "status": "blocked",
            "evidence": (
                "no admitted gauge/radar, tide, operation or timed inundation panel is present"
            ),
        },
        {
            "blocker_id": "independent_calibration_and_blind_holdout",
            "status": "blocked",
            "evidence": "no event-aligned calibrated traditional baseline exists",
        },
    ]
    gates = [
        {
            "gate_id": "candidate_data_foundation",
            "status": "candidate_ready",
            "passed": True,
            "claim_allowed": "diagnostic_only",
        },
        {
            "gate_id": "traditional_hydraulic_baseline",
            "status": "blocked",
            "passed": False,
            "claim_allowed": "none",
        },
        {
            "gate_id": "gwm_training_panel",
            "status": "blocked",
            "passed": False,
            "claim_allowed": "none",
        },
        {
            "gate_id": "hybrid_planner_contract",
            "status": "contract_ready_not_executable",
            "passed": False,
            "claim_allowed": "architecture_only",
        },
        {
            "gate_id": "operational_city_scale_prediction",
            "status": "blocked",
            "passed": False,
            "claim_allowed": "none",
        },
    ]
    return {
        "schema": READINESS_SCHEMA,
        "dataset_id": inventory["dataset_id"],
        "target_crs": TARGET_CRS,
        "registered_snapshot_id": network_manifest["registered_snapshot_id"],
        "input_artifacts": {
            "inventory": {
                "path": _path_label(inventory_path, root),
            },
            "network_manifest": {
                "path": _path_label(network_manifest_path, root),
                "sha256": _sha256_file(network_manifest_path),
            },
            "network_audit": {
                "path": _path_label(network_audit_path, root),
                "sha256": _sha256_file(network_audit_path),
            },
            "registered_pipelines": pipeline_metadata,
            "surface_support_audit": (
                {
                    "available": True,
                    "path": _path_label(surface_audit_path, root),
                    "sha256": _sha256_file(surface_audit_path),
                }
                if surface_audit is not None
                else {"available": False}
            ),
            "target_clipped_surface_candidate": (
                {
                    "available": True,
                    "path": _path_label(surface_clip_manifest_path, root),
                    "sha256": _sha256_file(surface_clip_manifest_path),
                }
                if surface_clip is not None
                else {"available": False}
            ),
        },
        "engineering_field_audit": engineering,
        "network_candidate_summary": {
            "pipeline_count": network_manifest["pipeline_count"],
            "node_count": network_manifest["node_count"],
            "connected_component_count": topology["topology"][
                "connected_component_count"
            ],
            "node_facility_candidate_count": facilities[
                "node_facility_candidate_count"
            ],
            "mapped_pipeline_endpoint_percent": facilities[
                "mapped_pipeline_endpoint_percent"
            ],
            "residual_unmatched_pipeline_endpoint_count": facilities[
                "residual_unmatched_pipeline_endpoint_count"
            ],
            "nodes_are_surface_patches": facilities["nodes_are_surface_patches"],
            "outfall_or_pump_connectivity_authoritative": facilities[
                "outfall_or_pump_connectivity_authoritative"
            ],
        },
        "surface_candidate_summary": (
            surface_audit["surface_candidate_summary"]
            if surface_audit is not None
            else {
                "available": False,
                "surface_patch_contract_compiled": False,
            }
        ),
        "target_clipped_surface_candidate_summary": (
            surface_clip["summary"]
            if surface_clip is not None
            else {
                "available": False,
                "surface_patch_contract_compiled": False,
            }
        ),
        "blockers": blockers,
        "gates": gates,
        "architecture_contract": _architecture_contract(),
        "admission": {
            "k0_status": inventory["k0_data_gate"]["status"],
            "k0_passed": inventory["k0_data_gate"]["passed"],
            "traditional_model_admitted": False,
            "gwm_training_admitted": False,
            "hybrid_planner_admitted": False,
            "city_scale_prediction_claim_allowed": False,
        },
        "claim_boundary": [
            "this_is_a_readiness_and_architecture_audit_not_a_hydraulic_simulation",
            "the_conservative_candidate_simulator_remains_fixture_or_contract_only",
            "traditional_physics_model_remains_the_future_validation_and_fallback_authority",
            "gwm_cannot_be_trained_or_admitted_without_event_observations_and_blind_holdouts",
        ],
    }


def write_hybrid_readiness(
    dataset_root: Path,
    *,
    output_path: Path | None = None,
) -> dict[str, Any]:
    root = dataset_root.resolve()
    destination = output_path or (
        root / "derived/makani_registered/hybrid_readiness_audit.json"
    )
    payload = build_hybrid_readiness(root)
    _atomic_write_json(destination, payload)
    output = {
        "path": _path_label(destination.resolve(), root),
        "sha256": _sha256_file(destination),
        "size_bytes": destination.stat().st_size,
    }
    payload["output"] = output
    return payload
