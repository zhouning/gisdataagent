from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping


SCHEMA = "uwm.traditional_livability.s1_fpp_assessment.v1"


def _compare(value: float, comparator: str, threshold: float) -> bool:
    return {
        ">=": value >= threshold,
        "<=": value <= threshold,
        ">": value > threshold,
        "<": value < threshold,
        "==": value == threshold,
    }[comparator]


def _unresolved(metric, blockers, warnings=None):
    return {
        "schema": SCHEMA,
        "dimension": "FPP",
        "status": "unresolved",
        "observed_value": None,
        "unit": metric.get("unit") if isinstance(metric, Mapping) else None,
        "threshold": metric.get("threshold") if isinstance(metric, Mapping) else None,
        "comparator": metric.get("comparator") if isinstance(metric, Mapping) else None,
        "metric": metric.get("metric") if isinstance(metric, Mapping) else None,
        "evidence": {},
        "blockers": list(dict.fromkeys(blockers)),
        "completeness_warnings": list(dict.fromkeys(warnings or [])),
        "max_claim_level": "unresolved",
    }


def _population(population_units, admin_code):
    matches = [row for row in population_units if row.get("admin_code") == admin_code]
    if len(matches) != 1:
        return None, ["population_unit_missing_or_ambiguous"]
    value = matches[0].get("population")
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
        return None, ["population_must_be_positive"]
    return float(value), []


def evaluate_fpp(
    *,
    facilities: list[Mapping[str, Any]],
    population_units: list[Mapping[str, Any]],
    profile: Mapping[str, Any],
    admin_code: str,
    complete_facility_inventory: bool = True,
) -> dict[str, Any]:
    profile_copy = deepcopy(dict(profile))
    facility_rows = deepcopy(list(facilities))
    population_rows = deepcopy(list(population_units))
    metric = next(
        (deepcopy(dict(row)) for row in profile_copy.get("metrics", []) if isinstance(row, Mapping) and row.get("dimension") == "FPP"),
        None,
    )
    if profile_copy.get("status") != "valid" or metric is None:
        return _unresolved(metric, ["valid_fpp_profile_required"])
    selected = [
        row
        for row in facility_rows
        if row.get("admin_code") == admin_code
        and row.get("canonical_class") == profile_copy.get("standard_class_id")
    ]
    metric_name = metric.get("metric")
    blockers = []
    population = None
    if metric_name in {"facilities_per_10000_residents", "capacity_per_10000_residents"}:
        population, blockers = _population(population_rows, admin_code)
    if blockers:
        return _unresolved(metric, blockers)

    if metric_name == "facility_count":
        value = float(len(selected))
        numerator = value
        denominator = None
    elif metric_name == "facilities_per_10000_residents":
        numerator = float(len(selected))
        denominator = population
        value = numerator / population * 10000.0
    elif metric_name == "total_facility_area":
        missing = [row.get("facility_id") for row in selected if not isinstance(row.get("facility_area_m2"), (int, float)) or isinstance(row.get("facility_area_m2"), bool)]
        if missing:
            return _unresolved(metric, [f"facility_area_missing:{facility_id}" for facility_id in missing])
        numerator = sum(float(row["facility_area_m2"]) for row in selected)
        denominator = None
        value = numerator
    elif metric_name == "capacity_per_10000_residents":
        missing = [row.get("facility_id") for row in selected if not isinstance(row.get("capacity"), (int, float)) or isinstance(row.get("capacity"), bool)]
        if missing:
            return _unresolved(metric, [f"facility_capacity_missing:{facility_id}" for facility_id in missing])
        numerator = sum(float(row["capacity"]) for row in selected)
        denominator = population
        value = numerator / population * 10000.0
    else:
        return _unresolved(metric, ["fpp_metric_not_implemented"])

    value = round(value, 6)
    threshold = float(metric["threshold"])
    status = "meets" if _compare(value, metric["comparator"], threshold) else "does_not_meet"
    warnings = [] if complete_facility_inventory else ["facility_inventory_incomplete"]
    return {
        "schema": SCHEMA,
        "dimension": "FPP",
        "profile_id": profile_copy.get("profile_id"),
        "standard_class_id": profile_copy.get("standard_class_id"),
        "metric": metric_name,
        "status": status,
        "observed_value": value,
        "unit": metric.get("unit"),
        "threshold": threshold,
        "comparator": metric.get("comparator"),
        "gap_to_threshold": round(value - threshold, 6),
        "evidence": {
            "facility_ids": [row.get("facility_id") for row in selected],
            "facility_count": len(selected),
            "numerator": numerator,
            "denominator": denominator,
            "population": int(population) if population is not None and population.is_integer() else population,
        },
        "blockers": [],
        "completeness_warnings": warnings,
        "max_claim_level": "authoritative_static_assessment" if complete_facility_inventory else "bounded_sample_diagnostic",
    }
