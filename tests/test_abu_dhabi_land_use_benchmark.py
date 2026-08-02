from __future__ import annotations

import numpy as np

from benchmarks.abu_dhabi_land_use_v1.contract import (
    canonicalize_dynamic_world,
    load_protocol,
    observed_demand_counts,
    validate_prediction,
)
from benchmarks.abu_dhabi_land_use_v1.planning import (
    pareto_frontier,
    planning_metrics,
)
from benchmarks.abu_dhabi_land_use_v1.prepare_grid import aligned_bounds
from benchmarks.abu_dhabi_land_use_v1.shared import (
    evaluate_prediction,
    feasible_target_counts,
)


def test_protocol_freezes_three_candidates_and_city_scope() -> None:
    protocol = load_protocol()
    assert protocol["spatial_world"]["boundary_osm_relation_id"] == 4479763
    assert protocol["spatial_world"]["canonical_crs"] == "EPSG:32640"
    assert {row["id"] for row in protocol["models"]} == {
        "geosos_flus",
        "gwm_geospatial_kernel",
        "paper58",
    }


def test_dynamic_world_crosswalk_is_complete_and_excludes_snow() -> None:
    mapped = canonicalize_dynamic_world(np.arange(9, dtype=np.uint8))
    assert mapped.tolist() == [1, 2, 3, 4, 3, 3, 5, 6, 0]


def test_observed_demand_is_explicitly_oracle_only() -> None:
    start = np.array([[5, 6], [1, 3]], dtype=np.uint8)
    target = np.array([[5, 5], [1, 3]], dtype=np.uint8)
    action = observed_demand_counts(start, target, valid_mask=np.ones_like(start, dtype=bool))
    assert action["source"] == "observed_allocation"
    assert action["start_counts"]["6"] == 1
    assert action["target_counts"]["5"] == 2


def test_prediction_contract_rejects_exclusion_change_and_outside_values() -> None:
    origin = np.array([[5, 6], [0, 4]], dtype=np.uint8)
    prediction = np.array([[5, 5], [6, 4]], dtype=np.uint8)
    valid = np.array([[1, 1], [0, 1]], dtype=bool)
    excluded = np.array([[0, 1], [0, 1]], dtype=bool)
    report = validate_prediction(
        prediction,
        origin_state=origin,
        valid_mask=valid,
        hard_exclusion_mask=excluded,
    )
    assert report["valid"] is False
    assert report["changed_hard_exclusion_pixels"] == 1
    assert report["nonzero_outside_world_pixels"] == 1


def test_grid_bounds_are_anchored_to_resolution() -> None:
    assert aligned_bounds((31.1, 99.9, 231.2, 301.0), 100) == (0, 0, 300, 400)


def test_feasible_demand_preserves_immutable_class_counts() -> None:
    origin = np.array([[1, 6, 6], [4, 6, 5]], dtype=np.uint8)
    valid = np.ones_like(origin, dtype=bool)
    hard = np.array([[1, 0, 0], [1, 0, 0]], dtype=bool)
    result = feasible_target_counts(
        {1: 0, 2: 0, 3: 0, 4: 0, 5: 5, 6: 1},
        origin_state=origin,
        valid_mask=valid,
        hard_exclusion_mask=hard,
    )
    assert sum(result.values()) == 6
    assert result[1] >= 1
    assert result[4] >= 1


def test_shared_evaluator_reports_change_and_constraint_failures() -> None:
    origin = np.array([[1, 6], [6, 5]], dtype=np.uint8)
    target = np.array([[1, 5], [6, 5]], dtype=np.uint8)
    prediction = np.array([[5, 5], [6, 5]], dtype=np.uint8)
    valid = np.ones_like(origin, dtype=bool)
    hard = np.array([[1, 0], [0, 0]], dtype=bool)
    report = evaluate_prediction(
        prediction,
        origin_state=origin,
        observed_target=target,
        valid_mask=valid,
        hard_exclusion_mask=hard,
        requested_counts={1: 1, 2: 0, 3: 0, 4: 0, 5: 2, 6: 1},
    )
    assert report["change_figure_of_merit"] == 0.5
    assert report["constraint_violation_pixels"] == 1


def test_planning_metrics_report_spatial_costs_and_demand() -> None:
    origin = np.array([[5, 6, 6], [3, 6, 5]], dtype=np.uint8)
    state = np.array([[5, 5, 6], [3, 6, 5]], dtype=np.uint8)
    valid = np.ones_like(origin, dtype=bool)
    report = planning_metrics(
        state,
        origin_state=origin,
        valid_mask=valid,
        hard_exclusion_mask=np.zeros_like(valid),
        target_counts={1: 0, 2: 0, 3: 1, 4: 0, 5: 3, 6: 2},
        road_distance_m=np.array(
            [[0, 100, 200], [300, 400, 500]], dtype=np.float32
        ),
        major_road_distance_m=np.array(
            [[0, 700, 800], [900, 1000, 1100]], dtype=np.float32
        ),
        pixel_size_m=100,
    )
    assert report["demand_total_variation"] == 0
    assert report["built_gain_pixels"] == 1
    assert report["new_built_mean_road_distance_m"] == 100
    assert report["new_built_mean_major_road_distance_m"] == 700
    assert report["new_built_mean_prior_built_distance_m"] == 100


def test_pareto_frontier_respects_min_and_max_directions() -> None:
    candidates = [
        {"candidate_id": "a", "cost": 1.0, "benefit": 2.0},
        {"candidate_id": "b", "cost": 2.0, "benefit": 1.0},
        {"candidate_id": "c", "cost": 0.5, "benefit": 1.0},
    ]
    assert pareto_frontier(
        candidates, objectives={"cost": "min", "benefit": "max"}
    ) == ["a", "c"]
