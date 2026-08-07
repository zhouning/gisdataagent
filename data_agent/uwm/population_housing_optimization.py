"""Auditable aggregate population and housing allocation with SciPy/HiGHS.

The model assigns household groups to housing options. It deliberately avoids
person-level decisions and keeps proxy inputs, assumptions, and hard-constraint
checks visible in the returned artifact.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict
from collections.abc import Iterable
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

import numpy as np
import scipy
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import coo_matrix

POPULATION_HOUSING_INPUT_SCHEMA = "uwm.population_housing_optimization.input.v1"
POPULATION_HOUSING_RESULT_SCHEMA = "uwm.population_housing_optimization.result.v1"
POPULATION_HOUSING_PORTFOLIO_SCHEMA = "uwm.population_housing_optimization.portfolio.v1"

DEFAULT_OBJECTIVE_WEIGHTS = {
    "public_cost": 1.0,
    "resident_housing_cost": 0.15,
    "commute_cost": 0.5,
    "relocation_cost": 1.0,
    "unmet_penalty": 1.0,
}

DEFAULT_PORTFOLIO_PROFILES = {
    "balanced": DEFAULT_OBJECTIVE_WEIGHTS,
    "fiscal_priority": {
        "public_cost": 1.0,
        "resident_housing_cost": 0.05,
        "commute_cost": 0.1,
        "relocation_cost": 0.25,
        "unmet_penalty": 1.0,
    },
    "commute_priority": {
        "public_cost": 0.35,
        "resident_housing_cost": 0.1,
        "commute_cost": 3.0,
        "relocation_cost": 1.5,
        "unmet_penalty": 1.0,
    },
}


@dataclass(frozen=True)
class _Variable:
    name: str
    kind: str
    key: str
    lower: float
    upper: float
    integral: bool
    objective: float


@dataclass(frozen=True)
class _ConstraintRow:
    constraint_id: str
    category: str
    coefficients: dict[int, float]
    lower: float
    upper: float


def validate_population_housing_input(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate the input contract without mutating the caller's payload."""

    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(payload, dict):
        return {"valid": False, "errors": ["payload_must_be_object"], "warnings": []}
    if payload.get("schema") != POPULATION_HOUSING_INPUT_SCHEMA:
        errors.append(f"schema_must_equal::{POPULATION_HOUSING_INPUT_SCHEMA}")

    zones = _object_list(payload, "zones", errors)
    groups = _object_list(payload, "population_groups", errors)
    housing = _object_list(payload, "housing_options", errors)
    candidates = _object_list(payload, "candidate_assignments", errors)
    parameters = payload.get("parameters")
    if not isinstance(parameters, dict):
        errors.append("parameters_must_be_object")
        parameters = {}

    zone_ids = _unique_ids(zones, "zone_id", "zone", errors)
    group_ids = _unique_ids(groups, "group_id", "population_group", errors)
    housing_ids = _unique_ids(housing, "housing_option_id", "housing_option", errors)

    for zone in zones:
        zone_id = str(zone.get("zone_id") or "")
        for field in (
            "existing_service_capacity",
            "max_service_expansion",
            "service_expansion_unit_public_cost",
        ):
            _nonnegative_number(zone.get(field), f"zone::{zone_id}::{field}", errors)

    group_map: dict[str, dict[str, Any]] = {}
    for group in groups:
        group_id = str(group.get("group_id") or "")
        group_map[group_id] = group
        if str(group.get("origin_zone_id") or "") not in zone_ids:
            errors.append(f"group::{group_id}::unknown_origin_zone")
        _nonnegative_integer(group.get("households"), f"group::{group_id}::households", errors)
        _positive_number(
            group.get("persons_per_household"),
            f"group::{group_id}::persons_per_household",
            errors,
        )
        _nonnegative_number(
            group.get("service_demand_per_household"),
            f"group::{group_id}::service_demand_per_household",
            errors,
        )
        _positive_number(
            group.get("max_commute_minutes"),
            f"group::{group_id}::max_commute_minutes",
            errors,
        )
        relocation_share = group.get("max_relocation_share", 1.0)
        if not _is_finite_number(relocation_share) or not 0 <= float(relocation_share) <= 1:
            errors.append(f"group::{group_id}::max_relocation_share_must_be_0_to_1")
        eligible_types = group.get("eligible_housing_types")
        if not isinstance(eligible_types, list) or not eligible_types:
            errors.append(f"group::{group_id}::eligible_housing_types_must_be_nonempty_list")

    housing_map: dict[str, dict[str, Any]] = {}
    for option in housing:
        option_id = str(option.get("housing_option_id") or "")
        housing_map[option_id] = option
        if str(option.get("zone_id") or "") not in zone_ids:
            errors.append(f"housing::{option_id}::unknown_zone")
        if not str(option.get("housing_type") or ""):
            errors.append(f"housing::{option_id}::housing_type_required")
        for field in ("existing_units", "max_new_units"):
            _nonnegative_integer(option.get(field), f"housing::{option_id}::{field}", errors)
        for field in ("new_unit_public_cost", "activation_public_cost"):
            _nonnegative_number(option.get(field), f"housing::{option_id}::{field}", errors)

    candidate_pairs: set[tuple[str, str]] = set()
    for index, candidate in enumerate(candidates):
        group_id = str(candidate.get("group_id") or "")
        option_id = str(candidate.get("housing_option_id") or "")
        prefix = f"candidate::{index}"
        if group_id not in group_ids:
            errors.append(f"{prefix}::unknown_group")
        if option_id not in housing_ids:
            errors.append(f"{prefix}::unknown_housing_option")
        pair = (group_id, option_id)
        if pair in candidate_pairs:
            errors.append(f"candidate_pair_duplicate::{group_id}::{option_id}")
        candidate_pairs.add(pair)
        for field in (
            "commute_minutes",
            "commute_generalized_cost",
            "resident_housing_cost",
            "public_cost",
            "relocation_cost",
        ):
            _nonnegative_number(candidate.get(field), f"{prefix}::{field}", errors)

    _positive_number(
        parameters.get("total_public_budget"),
        "parameters::total_public_budget",
        errors,
    )
    global_relocation = parameters.get("max_relocated_households_share", 1.0)
    if not _is_finite_number(global_relocation) or not 0 <= float(global_relocation) <= 1:
        errors.append("parameters::max_relocated_households_share_must_be_0_to_1")
    allow_unmet = parameters.get("allow_unmet_households", False)
    if not isinstance(allow_unmet, bool):
        errors.append("parameters::allow_unmet_households_must_be_boolean")
    if allow_unmet:
        _positive_number(
            parameters.get("unmet_household_penalty"),
            "parameters::unmet_household_penalty",
            errors,
        )

    _positive_number(
        parameters.get("solver_time_limit_seconds", 120.0),
        "parameters::solver_time_limit_seconds",
        errors,
    )
    mip_relative_gap = parameters.get("solver_mip_relative_gap", 0.001)
    if (
        not _is_finite_number(mip_relative_gap)
        or not 0 <= float(mip_relative_gap) <= 1
    ):
        errors.append("parameters::solver_mip_relative_gap_must_be_0_to_1")
    if not isinstance(parameters.get("solver_log", False), bool):
        errors.append("parameters::solver_log_must_be_boolean")

    weights = parameters.get("objective_weights", {})
    if not isinstance(weights, dict):
        errors.append("parameters::objective_weights_must_be_object")
    else:
        unknown_weights = sorted(set(weights) - set(DEFAULT_OBJECTIVE_WEIGHTS))
        if unknown_weights:
            errors.append(f"parameters::unknown_objective_weights::{','.join(unknown_weights)}")
        for name, value in weights.items():
            _nonnegative_number(value, f"parameters::objective_weights::{name}", errors)
        merged_weights = dict(DEFAULT_OBJECTIVE_WEIGHTS)
        merged_weights.update(weights)
        if all(_is_finite_number(value) for value in merged_weights.values()) and all(
            float(value) == 0 for value in merged_weights.values()
        ):
            errors.append("parameters::objective_weights_must_include_positive_weight")

    if not errors:
        screened = _screen_candidates(groups, housing_map, candidates)
        valid_groups = Counter(row["group_id"] for row in screened["eligible"])
        for group_id in group_ids:
            if valid_groups[group_id] == 0:
                errors.append(f"group::{group_id}::no_eligible_candidate_after_screening")
        if screened["excluded"]:
            warnings.append(
                f"candidate_assignments_excluded::{len(screened['excluded'])}"
            )

    claim_boundary = payload.get("claim_boundary")
    if not isinstance(claim_boundary, dict):
        warnings.append("claim_boundary_missing_or_not_object")
    if payload.get("empirical_policy_optimality_claim") is not False:
        errors.append("empirical_policy_optimality_claim_must_be_false_for_poc")

    return {
        "schema": "uwm.population_housing_optimization.input_validation.v1",
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "counts": {
            "zones": len(zones),
            "population_groups": len(groups),
            "housing_options": len(housing),
            "candidate_assignments": len(candidates),
        },
    }


def solve_population_housing_allocation(payload: dict[str, Any]) -> dict[str, Any]:
    """Solve one weighted aggregate allocation scenario with HiGHS MILP."""

    validation = validate_population_housing_input(payload)
    if not validation["valid"]:
        raise ValueError("invalid population-housing input: " + "; ".join(validation["errors"]))

    zones = payload["zones"]
    groups = payload["population_groups"]
    housing = payload["housing_options"]
    parameters = payload["parameters"]
    zone_map = {str(row["zone_id"]): row for row in zones}
    group_map = {str(row["group_id"]): row for row in groups}
    housing_map = {str(row["housing_option_id"]): row for row in housing}
    weights = dict(DEFAULT_OBJECTIVE_WEIGHTS)
    weights.update(parameters.get("objective_weights") or {})

    screened = _screen_candidates(groups, housing_map, payload["candidate_assignments"])
    eligible_candidates = screened["eligible"]
    variables: list[_Variable] = []
    assignment_indices: dict[tuple[str, str], int] = {}
    new_unit_indices: dict[str, int] = {}
    activation_indices: dict[str, int] = {}
    service_indices: dict[str, int] = {}
    unmet_indices: dict[str, int] = {}

    for candidate in eligible_candidates:
        group_id = str(candidate["group_id"])
        option_id = str(candidate["housing_option_id"])
        group = group_map[group_id]
        objective = (
            weights["public_cost"] * float(candidate["public_cost"])
            + weights["resident_housing_cost"]
            * float(candidate["resident_housing_cost"])
            + weights["commute_cost"]
            * float(candidate["commute_generalized_cost"])
            + weights["relocation_cost"] * float(candidate["relocation_cost"])
        )
        assignment_indices[(group_id, option_id)] = len(variables)
        variables.append(
            _Variable(
                name=f"assign::{group_id}::{option_id}",
                kind="assignment",
                key=f"{group_id}::{option_id}",
                lower=0.0,
                upper=float(group["households"]),
                integral=True,
                objective=objective,
            )
        )

    for option in housing:
        option_id = str(option["housing_option_id"])
        max_new = int(option["max_new_units"])
        new_unit_indices[option_id] = len(variables)
        variables.append(
            _Variable(
                name=f"new_units::{option_id}",
                kind="new_units",
                key=option_id,
                lower=0.0,
                upper=float(max_new),
                integral=True,
                objective=weights["public_cost"] * float(option["new_unit_public_cost"]),
            )
        )
        activation_indices[option_id] = len(variables)
        variables.append(
            _Variable(
                name=f"activate::{option_id}",
                kind="activation",
                key=option_id,
                lower=0.0,
                upper=1.0 if max_new > 0 else 0.0,
                integral=True,
                objective=weights["public_cost"] * float(option["activation_public_cost"]),
            )
        )

    for zone in zones:
        zone_id = str(zone["zone_id"])
        service_indices[zone_id] = len(variables)
        variables.append(
            _Variable(
                name=f"service_expansion::{zone_id}",
                kind="service_expansion",
                key=zone_id,
                lower=0.0,
                upper=float(zone["max_service_expansion"]),
                integral=False,
                objective=(
                    weights["public_cost"]
                    * float(zone["service_expansion_unit_public_cost"])
                ),
            )
        )

    if parameters.get("allow_unmet_households", False):
        unmet_cost = (
            weights["unmet_penalty"] * float(parameters["unmet_household_penalty"])
        )
        for group in groups:
            group_id = str(group["group_id"])
            unmet_indices[group_id] = len(variables)
            variables.append(
                _Variable(
                    name=f"unmet::{group_id}",
                    kind="unmet",
                    key=group_id,
                    lower=0.0,
                    upper=float(group["households"]),
                    integral=True,
                    objective=unmet_cost,
                )
            )

    constraints: list[_ConstraintRow] = []
    by_group: dict[str, list[tuple[dict[str, Any], int]]] = defaultdict(list)
    by_option: dict[str, list[tuple[dict[str, Any], int]]] = defaultdict(list)
    by_zone: dict[str, list[tuple[dict[str, Any], int]]] = defaultdict(list)
    for candidate in eligible_candidates:
        group_id = str(candidate["group_id"])
        option_id = str(candidate["housing_option_id"])
        index = assignment_indices[(group_id, option_id)]
        by_group[group_id].append((candidate, index))
        by_option[option_id].append((candidate, index))
        by_zone[str(housing_map[option_id]["zone_id"])].append((candidate, index))

    for group in groups:
        group_id = str(group["group_id"])
        coefficients = {index: 1.0 for _, index in by_group[group_id]}
        if group_id in unmet_indices:
            coefficients[unmet_indices[group_id]] = 1.0
        households = float(group["households"])
        constraints.append(
            _ConstraintRow(
                constraint_id=f"group_balance::{group_id}",
                category="population_conservation",
                coefficients=coefficients,
                lower=households,
                upper=households,
            )
        )

    for option in housing:
        option_id = str(option["housing_option_id"])
        capacity_coefficients = {index: 1.0 for _, index in by_option[option_id]}
        capacity_coefficients[new_unit_indices[option_id]] = -1.0
        constraints.append(
            _ConstraintRow(
                constraint_id=f"housing_capacity::{option_id}",
                category="housing_capacity",
                coefficients=capacity_coefficients,
                lower=-math.inf,
                upper=float(option["existing_units"]),
            )
        )
        constraints.append(
            _ConstraintRow(
                constraint_id=f"housing_activation::{option_id}",
                category="housing_activation",
                coefficients={
                    new_unit_indices[option_id]: 1.0,
                    activation_indices[option_id]: -float(option["max_new_units"]),
                },
                lower=-math.inf,
                upper=0.0,
            )
        )
        if int(option["max_new_units"]) > 0:
            constraints.append(
                _ConstraintRow(
                    constraint_id=f"housing_activation_lower::{option_id}",
                    category="housing_activation",
                    coefficients={
                        activation_indices[option_id]: 1.0,
                        new_unit_indices[option_id]: -1.0,
                    },
                    lower=-math.inf,
                    upper=0.0,
                )
            )

    for zone in zones:
        zone_id = str(zone["zone_id"])
        coefficients: dict[int, float] = {}
        for candidate, index in by_zone[zone_id]:
            group = group_map[str(candidate["group_id"])]
            coefficients[index] = float(group["service_demand_per_household"])
        coefficients[service_indices[zone_id]] = -1.0
        constraints.append(
            _ConstraintRow(
                constraint_id=f"service_capacity::{zone_id}",
                category="public_service_capacity",
                coefficients=coefficients,
                lower=-math.inf,
                upper=float(zone["existing_service_capacity"]),
            )
        )

    budget_coefficients: dict[int, float] = {}
    for candidate in eligible_candidates:
        assignment_key = (
            str(candidate["group_id"]),
            str(candidate["housing_option_id"]),
        )
        index = assignment_indices[assignment_key]
        budget_coefficients[index] = float(candidate["public_cost"]) + float(
            candidate["relocation_cost"]
        )
    for option in housing:
        option_id = str(option["housing_option_id"])
        budget_coefficients[new_unit_indices[option_id]] = float(
            option["new_unit_public_cost"]
        )
        budget_coefficients[activation_indices[option_id]] = float(
            option["activation_public_cost"]
        )
    for zone in zones:
        zone_id = str(zone["zone_id"])
        budget_coefficients[service_indices[zone_id]] = float(
            zone["service_expansion_unit_public_cost"]
        )
    constraints.append(
        _ConstraintRow(
            constraint_id="public_budget",
            category="fiscal",
            coefficients=budget_coefficients,
            lower=-math.inf,
            upper=float(parameters["total_public_budget"]),
        )
    )

    total_households = sum(int(group["households"]) for group in groups)
    global_relocation_coefficients: dict[int, float] = {}
    for candidate in eligible_candidates:
        group = group_map[str(candidate["group_id"])]
        option = housing_map[str(candidate["housing_option_id"])]
        if str(group["origin_zone_id"]) != str(option["zone_id"]):
            assignment_key = (
                str(candidate["group_id"]),
                str(candidate["housing_option_id"]),
            )
            global_relocation_coefficients[assignment_indices[assignment_key]] = 1.0
    constraints.append(
        _ConstraintRow(
            constraint_id="global_relocation_cap",
            category="relocation",
            coefficients=global_relocation_coefficients,
            lower=-math.inf,
            upper=float(
                math.floor(
                    total_households
                    * float(parameters.get("max_relocated_households_share", 1.0))
                )
            ),
        )
    )
    for group in groups:
        group_id = str(group["group_id"])
        coefficients: dict[int, float] = {}
        for candidate, index in by_group[group_id]:
            destination = housing_map[str(candidate["housing_option_id"])]["zone_id"]
            if str(destination) != str(group["origin_zone_id"]):
                coefficients[index] = 1.0
        constraints.append(
            _ConstraintRow(
                constraint_id=f"group_relocation_cap::{group_id}",
                category="relocation",
                coefficients=coefficients,
                lower=-math.inf,
                upper=float(
                    math.floor(
                        int(group["households"])
                        * float(group.get("max_relocation_share", 1.0))
                    )
                ),
            )
        )

    matrix = _constraint_matrix(constraints, len(variables))
    scipy_constraints = LinearConstraint(
        matrix,
        np.array([row.lower for row in constraints], dtype=float),
        np.array([row.upper for row in constraints], dtype=float),
    )
    options = {
        "disp": bool(parameters.get("solver_log", False)),
        "presolve": True,
        "time_limit": float(parameters.get("solver_time_limit_seconds", 120.0)),
        "mip_rel_gap": float(parameters.get("solver_mip_relative_gap", 0.001)),
    }
    result = milp(
        c=np.array([variable.objective for variable in variables], dtype=float),
        integrality=np.array([1 if variable.integral else 0 for variable in variables], dtype=int),
        bounds=Bounds(
            np.array([variable.lower for variable in variables], dtype=float),
            np.array([variable.upper for variable in variables], dtype=float),
        ),
        constraints=scipy_constraints,
        options=options,
    )

    status = _solver_status(int(result.status), result.x is not None)
    solution = (
        np.asarray(result.x, dtype=float)
        if result.x is not None
        else np.zeros(len(variables), dtype=float)
    )
    artifact = _build_result_artifact(
        payload=payload,
        status=status,
        solver_result=result,
        solution=solution,
        variables=variables,
        constraints=constraints,
        matrix=matrix,
        screened=screened,
        eligible_candidates=eligible_candidates,
        assignment_indices=assignment_indices,
        new_unit_indices=new_unit_indices,
        activation_indices=activation_indices,
        service_indices=service_indices,
        unmet_indices=unmet_indices,
        zone_map=zone_map,
        group_map=group_map,
        housing_map=housing_map,
        weights=weights,
        validation=validation,
    )
    return artifact


def solve_population_housing_portfolio(
    payload: dict[str, Any],
    profiles: dict[str, dict[str, float]] | None = None,
) -> dict[str, Any]:
    """Solve several transparent weighting profiles against the same constraints."""

    selected_profiles = profiles or DEFAULT_PORTFOLIO_PROFILES
    if not selected_profiles:
        raise ValueError("at least one objective profile is required")
    results: list[dict[str, Any]] = []
    for profile_id, weights in selected_profiles.items():
        scenario = deepcopy(payload)
        scenario.setdefault("parameters", {})["objective_weights"] = dict(weights)
        scenario["scenario_id"] = f"{payload.get('scenario_id', 'scenario')}::{profile_id}"
        result = solve_population_housing_allocation(scenario)
        result["profile_id"] = profile_id
        results.append(result)

    comparison = []
    for result in results:
        metrics = result["metrics"]
        comparison.append(
            {
                "profile_id": result["profile_id"],
                "status": result["status"],
                "objective_value": result["objective_value"],
                "assigned_households": metrics["assigned_households"],
                "unmet_households": metrics["unmet_households"],
                "relocated_households": metrics["relocated_households"],
                "relocation_share": metrics["relocation_share"],
                "new_units": metrics["new_units"],
                "public_cost": metrics["costs"]["public_cost"],
                "resident_housing_cost": metrics["costs"]["resident_housing_cost"],
                "commute_generalized_cost": metrics["costs"]["commute_generalized_cost"],
                "relocation_cost": metrics["costs"]["relocation_cost"],
                "all_constraints_pass": result["constraint_summary"]["all_pass"],
            }
        )
    portfolio = {
        "schema": POPULATION_HOUSING_PORTFOLIO_SCHEMA,
        "portfolio_id": f"{payload.get('scenario_id', 'scenario')}::portfolio",
        "input_digest": _input_digest(payload),
        "reference_profile_id": (
            "balanced" if "balanced" in selected_profiles else next(iter(selected_profiles))
        ),
        "profile_count": len(results),
        "comparison": comparison,
        "results": results,
        "claim_boundary": {
            "max_claim_level": "aggregate_proxy_scenario_optimization_poc",
            "not_person_level_assignment": True,
            "not_policy_recommendation": True,
            "weighted_profiles_not_complete_pareto_frontier": True,
        },
        "empirical_policy_optimality_claim": False,
    }
    return add_population_housing_reference_comparison(portfolio)


def add_population_housing_reference_comparison(
    portfolio: dict[str, Any],
) -> dict[str, Any]:
    """Add raw-metric deltas without pretending a missing status quo is observed."""

    enriched = deepcopy(portfolio)
    comparison = enriched.get("comparison")
    if not isinstance(comparison, list) or not comparison:
        raise ValueError("portfolio comparison must be a non-empty list")
    reference_profile_id = str(enriched.get("reference_profile_id") or "")
    reference = next(
        (
            row
            for row in comparison
            if isinstance(row, dict)
            and str(row.get("profile_id") or "") == reference_profile_id
        ),
        None,
    )
    if reference is None:
        raise ValueError("portfolio reference profile is missing from comparison")

    delta_fields = (
        "unmet_households",
        "relocated_households",
        "relocation_share",
        "new_units",
        "public_cost",
        "resident_housing_cost",
        "commute_generalized_cost",
        "relocation_cost",
    )
    for row in comparison:
        if not isinstance(row, dict):
            raise ValueError("portfolio comparison rows must be objects")
        row["delta_vs_reference"] = {
            field: round(float(row[field]) - float(reference[field]), 8)
            for field in delta_fields
        }

    enriched["comparison_context"] = {
        "reference_profile_id": reference_profile_id,
        "delta_definition": "profile_metric_minus_reference_profile_metric",
        "lower_is_better_for_reported_cost_and_adverse_outcome_deltas": True,
        "objective_values_comparable_across_profiles": False,
        "status_quo_baseline_available": False,
        "status_quo_baseline_blocker": (
            "observed_current_group_to_housing_occupancy_is_not_available"
        ),
        "not_a_complete_pareto_frontier": True,
    }
    return enriched


def _build_result_artifact(
    *,
    payload: dict[str, Any],
    status: str,
    solver_result: Any,
    solution: np.ndarray,
    variables: list[_Variable],
    constraints: list[_ConstraintRow],
    matrix: Any,
    screened: dict[str, list[dict[str, Any]]],
    eligible_candidates: list[dict[str, Any]],
    assignment_indices: dict[tuple[str, str], int],
    new_unit_indices: dict[str, int],
    activation_indices: dict[str, int],
    service_indices: dict[str, int],
    unmet_indices: dict[str, int],
    zone_map: dict[str, dict[str, Any]],
    group_map: dict[str, dict[str, Any]],
    housing_map: dict[str, dict[str, Any]],
    weights: dict[str, float],
    validation: dict[str, Any],
) -> dict[str, Any]:
    has_solution = solver_result.x is not None
    assignments: list[dict[str, Any]] = []
    assignment_lookup = {
        (str(row["group_id"]), str(row["housing_option_id"])): row
        for row in eligible_candidates
    }
    public_assignment_cost = 0.0
    resident_housing_cost = 0.0
    commute_cost = 0.0
    relocation_cost = 0.0
    relocated_households = 0.0
    assigned_households = 0.0
    modeled_people = 0.0
    service_demand_by_zone: dict[str, float] = defaultdict(float)
    occupied_by_option: dict[str, float] = defaultdict(float)

    if has_solution:
        for (group_id, option_id), index in assignment_indices.items():
            households = _clean_integer(solution[index])
            if households <= 0:
                continue
            candidate = assignment_lookup[(group_id, option_id)]
            group = group_map[group_id]
            option = housing_map[option_id]
            destination_zone_id = str(option["zone_id"])
            relocated = str(group["origin_zone_id"]) != destination_zone_id
            people = households * float(group["persons_per_household"])
            row_public_cost = households * float(candidate["public_cost"])
            row_resident_cost = households * float(candidate["resident_housing_cost"])
            row_commute_cost = households * float(candidate["commute_generalized_cost"])
            row_relocation_cost = households * float(candidate["relocation_cost"])
            assignments.append(
                {
                    "group_id": group_id,
                    "group_name": group.get("group_name"),
                    "origin_zone_id": group["origin_zone_id"],
                    "destination_zone_id": destination_zone_id,
                    "destination_zone_name": zone_map[destination_zone_id].get("zone_name"),
                    "housing_option_id": option_id,
                    "housing_type": option["housing_type"],
                    "households": households,
                    "people": round(people, 3),
                    "relocated": relocated,
                    "commute_minutes": float(candidate["commute_minutes"]),
                    "costs": {
                        "public_cost": round(row_public_cost, 6),
                        "resident_housing_cost": round(row_resident_cost, 6),
                        "commute_generalized_cost": round(row_commute_cost, 6),
                        "relocation_cost": round(row_relocation_cost, 6),
                    },
                    "evidence_status": candidate.get("evidence_status"),
                }
            )
            public_assignment_cost += row_public_cost
            resident_housing_cost += row_resident_cost
            commute_cost += row_commute_cost
            relocation_cost += row_relocation_cost
            assigned_households += households
            modeled_people += people
            occupied_by_option[option_id] += households
            service_demand_by_zone[destination_zone_id] += households * float(
                group["service_demand_per_household"]
            )
            if relocated:
                relocated_households += households

    housing_actions: list[dict[str, Any]] = []
    housing_public_cost = 0.0
    if has_solution:
        for option_id, option in housing_map.items():
            new_units = _clean_integer(solution[new_unit_indices[option_id]])
            activated = bool(solution[activation_indices[option_id]] >= 0.5)
            action_cost = (
                new_units * float(option["new_unit_public_cost"])
                + (float(option["activation_public_cost"]) if activated else 0.0)
            )
            housing_public_cost += action_cost
            housing_actions.append(
                {
                    "housing_option_id": option_id,
                    "zone_id": option["zone_id"],
                    "housing_type": option["housing_type"],
                    "existing_units": int(option["existing_units"]),
                    "new_units": new_units,
                    "activated": activated,
                    "occupied_units": _clean_integer(occupied_by_option[option_id]),
                    "available_units_after_action": int(option["existing_units"]) + new_units,
                    "public_cost": round(action_cost, 6),
                    "evidence_status": option.get("evidence_status"),
                }
            )

    service_actions: list[dict[str, Any]] = []
    service_public_cost = 0.0
    if has_solution:
        for zone_id, zone in zone_map.items():
            expansion = max(0.0, float(solution[service_indices[zone_id]]))
            action_cost = expansion * float(zone["service_expansion_unit_public_cost"])
            service_public_cost += action_cost
            service_actions.append(
                {
                    "zone_id": zone_id,
                    "zone_name": zone.get("zone_name"),
                    "existing_service_capacity": float(zone["existing_service_capacity"]),
                    "service_expansion": round(expansion, 6),
                    "assigned_service_demand": round(service_demand_by_zone[zone_id], 6),
                    "public_cost": round(action_cost, 6),
                    "evidence_status": zone.get("service_capacity_evidence_status"),
                }
            )

    unmet_households = (
        sum(_clean_integer(solution[index]) for index in unmet_indices.values())
        if has_solution
        else 0
    )
    total_households = sum(int(group["households"]) for group in group_map.values())
    public_cost = (
        public_assignment_cost + relocation_cost + housing_public_cost + service_public_cost
    )
    audit = _constraint_audit(constraints, matrix, solution) if has_solution else []
    excluded_reasons = Counter(row["exclusion_reason"] for row in screened["excluded"])
    solver_metadata = {
        "backend": "scipy.optimize.milp",
        "engine": "HiGHS",
        "scipy_version": scipy.__version__,
        "status_code": int(solver_result.status),
        "message": str(solver_result.message),
        "success": bool(solver_result.success),
        "mip_gap": _optional_float(getattr(solver_result, "mip_gap", None)),
        "mip_node_count": _optional_int(getattr(solver_result, "mip_node_count", None)),
        "dual_bound": _optional_float(getattr(solver_result, "mip_dual_bound", None)),
        "variable_count": len(variables),
        "integer_variable_count": sum(variable.integral for variable in variables),
        "constraint_count": len(constraints),
    }
    return {
        "schema": POPULATION_HOUSING_RESULT_SCHEMA,
        "scenario_id": payload.get("scenario_id"),
        "input_digest": _input_digest(payload),
        "status": status,
        "objective_value": (
            round(float(solver_result.fun), 6) if solver_result.fun is not None else None
        ),
        "objective_weights": weights,
        "cost_unit": payload.get("cost_unit"),
        "solver": solver_metadata,
        "input_validation": validation,
        "candidate_screening": {
            "input_count": len(payload["candidate_assignments"]),
            "eligible_count": len(screened["eligible"]),
            "excluded_count": len(screened["excluded"]),
            "excluded_reason_counts": dict(sorted(excluded_reasons.items())),
        },
        "metrics": {
            "source_households": total_households,
            "assigned_households": _clean_integer(assigned_households),
            "unmet_households": _clean_integer(unmet_households),
            "modeled_people": round(modeled_people, 3),
            "relocated_households": _clean_integer(relocated_households),
            "relocation_share": round(
                relocated_households / total_households if total_households else 0.0,
                8,
            ),
            "new_units": sum(row["new_units"] for row in housing_actions),
            "service_expansion": round(
                sum(row["service_expansion"] for row in service_actions), 6
            ),
            "costs": {
                "public_cost": round(public_cost, 6),
                "public_assignment_cost": round(public_assignment_cost, 6),
                "housing_action_public_cost": round(housing_public_cost, 6),
                "service_action_public_cost": round(service_public_cost, 6),
                "resident_housing_cost": round(resident_housing_cost, 6),
                "commute_generalized_cost": round(commute_cost, 6),
                "relocation_cost": round(relocation_cost, 6),
            },
        },
        "assignments": sorted(
            assignments,
            key=lambda row: (
                str(row["group_id"]),
                str(row["destination_zone_id"]),
                str(row["housing_option_id"]),
            ),
        ),
        "housing_actions": housing_actions,
        "service_actions": service_actions,
        "constraint_summary": {
            "all_pass": bool(audit) and all(row["pass"] for row in audit),
            "passed": sum(row["pass"] for row in audit),
            "failed": sum(not row["pass"] for row in audit),
            "constraint_count": len(audit),
        },
        "constraint_audit": audit,
        "claim_boundary": {
            **deepcopy(payload.get("claim_boundary") or {}),
            "max_claim_level": "aggregate_proxy_scenario_optimization_poc",
            "not_person_level_assignment": True,
            "not_observed_policy_outcome": True,
            "not_policy_recommendation": True,
        },
        "limitations": list(payload.get("limitations") or []),
        "empirical_policy_optimality_claim": False,
    }


def _screen_candidates(
    groups: list[dict[str, Any]],
    housing_map: dict[str, dict[str, Any]],
    candidates: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    group_map = {str(row["group_id"]): row for row in groups}
    eligible: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for candidate in candidates:
        row = deepcopy(candidate)
        group = group_map.get(str(row.get("group_id")))
        option = housing_map.get(str(row.get("housing_option_id")))
        reason = None
        if not bool(row.get("allowed", True)):
            reason = "candidate_marked_not_allowed"
        elif group is not None and option is not None:
            eligible_types = {str(value) for value in group["eligible_housing_types"]}
            if str(option["housing_type"]) not in eligible_types:
                reason = "housing_type_ineligible"
            elif float(row["commute_minutes"]) > float(group["max_commute_minutes"]):
                reason = "max_commute_exceeded"
        if reason:
            row["exclusion_reason"] = reason
            excluded.append(row)
        else:
            eligible.append(row)
    return {"eligible": eligible, "excluded": excluded}


def _constraint_matrix(rows: list[_ConstraintRow], variable_count: int) -> Any:
    row_indices: list[int] = []
    column_indices: list[int] = []
    values: list[float] = []
    for row_index, row in enumerate(rows):
        for column_index, value in row.coefficients.items():
            if value == 0:
                continue
            row_indices.append(row_index)
            column_indices.append(column_index)
            values.append(float(value))
    return coo_matrix(
        (values, (row_indices, column_indices)),
        shape=(len(rows), variable_count),
        dtype=float,
    ).tocsr()


def _constraint_audit(
    rows: list[_ConstraintRow],
    matrix: Any,
    solution: np.ndarray,
    tolerance: float = 1e-5,
) -> list[dict[str, Any]]:
    lhs_values = np.asarray(matrix @ solution, dtype=float)
    audit: list[dict[str, Any]] = []
    for row, lhs in zip(rows, lhs_values, strict=True):
        lower_pass = math.isinf(row.lower) or lhs >= row.lower - tolerance
        upper_pass = math.isinf(row.upper) or lhs <= row.upper + tolerance
        audit.append(
            {
                "constraint_id": row.constraint_id,
                "category": row.category,
                "lhs": round(float(lhs), 6),
                "lower": None if math.isinf(row.lower) else round(row.lower, 6),
                "upper": None if math.isinf(row.upper) else round(row.upper, 6),
                "lower_slack": (
                    None if math.isinf(row.lower) else round(float(lhs - row.lower), 6)
                ),
                "upper_slack": (
                    None if math.isinf(row.upper) else round(float(row.upper - lhs), 6)
                ),
                "pass": bool(lower_pass and upper_pass),
            }
        )
    return audit


def _solver_status(status_code: int, has_solution: bool) -> str:
    if status_code == 0:
        return "optimal"
    if status_code == 1 and has_solution:
        return "feasible_limit_reached"
    return {
        1: "limit_reached_without_solution",
        2: "infeasible",
        3: "unbounded",
        4: "solver_error",
    }.get(status_code, "unknown")


def _object_list(payload: dict[str, Any], field: str, errors: list[str]) -> list[dict[str, Any]]:
    value = payload.get(field)
    if not isinstance(value, list) or not value:
        errors.append(f"{field}_must_be_nonempty_list")
        return []
    if any(not isinstance(row, dict) for row in value):
        errors.append(f"{field}_rows_must_be_objects")
        return [row for row in value if isinstance(row, dict)]
    return value


def _unique_ids(
    rows: Iterable[dict[str, Any]], field: str, label: str, errors: list[str]
) -> set[str]:
    values: list[str] = []
    for index, row in enumerate(rows):
        value = str(row.get(field) or "").strip()
        if not value:
            errors.append(f"{label}::{index}::{field}_required")
        values.append(value)
    duplicates = sorted(value for value, count in Counter(values).items() if value and count > 1)
    for value in duplicates:
        errors.append(f"{label}::{field}_duplicate::{value}")
    return {value for value in values if value}


def _is_finite_number(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _nonnegative_number(value: Any, field: str, errors: list[str]) -> None:
    if not _is_finite_number(value) or float(value) < 0:
        errors.append(f"{field}_must_be_nonnegative_number")


def _positive_number(value: Any, field: str, errors: list[str]) -> None:
    if not _is_finite_number(value) or float(value) <= 0:
        errors.append(f"{field}_must_be_positive_number")


def _nonnegative_integer(value: Any, field: str, errors: list[str]) -> None:
    if isinstance(value, bool):
        errors.append(f"{field}_must_be_nonnegative_integer")
        return
    try:
        number = float(value)
    except (TypeError, ValueError):
        errors.append(f"{field}_must_be_nonnegative_integer")
        return
    if not math.isfinite(number) or number < 0 or not number.is_integer():
        errors.append(f"{field}_must_be_nonnegative_integer")


def _clean_integer(value: float, tolerance: float = 1e-5) -> int | float:
    rounded = round(float(value))
    if abs(float(value) - rounded) <= tolerance:
        return int(rounded)
    return round(float(value), 6)


def _optional_float(value: Any) -> float | None:
    return float(value) if _is_finite_number(value) else None


def _optional_int(value: Any) -> int | None:
    return int(value) if _is_finite_number(value) else None


def _input_digest(payload: dict[str, Any]) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


__all__ = [
    "DEFAULT_OBJECTIVE_WEIGHTS",
    "DEFAULT_PORTFOLIO_PROFILES",
    "POPULATION_HOUSING_INPUT_SCHEMA",
    "POPULATION_HOUSING_PORTFOLIO_SCHEMA",
    "POPULATION_HOUSING_RESULT_SCHEMA",
    "add_population_housing_reference_comparison",
    "solve_population_housing_allocation",
    "solve_population_housing_portfolio",
    "validate_population_housing_input",
]
