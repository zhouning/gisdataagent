from copy import deepcopy

from data_agent.uwm.traditional_livability_s1_fpp import evaluate_fpp


def _facilities():
    return [
        {
            "facility_id": "market-1",
            "canonical_class": "facility.market",
            "admin_code": "area-1",
            "facility_area_m2": 400.0,
            "capacity": 80.0,
        },
        {
            "facility_id": "other-1",
            "canonical_class": "facility.school",
            "admin_code": "area-1",
            "facility_area_m2": 1000.0,
            "capacity": 500.0,
        },
    ]


def _population():
    return [{"admin_code": "area-1", "population": 20000}]


def _profile(metric, threshold, unit, required_fields):
    return {
        "profile_id": f"market-{metric}",
        "standard_class_id": "facility.market",
        "status": "valid",
        "metrics": [
            {
                "dimension": "FPP",
                "metric": metric,
                "unit": unit,
                "comparator": ">=",
                "threshold": threshold,
                "required_source_fields": required_fields,
            }
        ],
    }


def test_facilities_per_population_uses_matching_class_and_admin_only():
    result = evaluate_fpp(
        facilities=_facilities(),
        population_units=_population(),
        profile=_profile(
            "facilities_per_10000_residents",
            1.0,
            "facilities_per_10000_residents",
            ["population"],
        ),
        admin_code="area-1",
    )
    assert result["observed_value"] == 0.5
    assert result["status"] == "does_not_meet"
    assert result["evidence"]["facility_ids"] == ["market-1"]
    assert result["evidence"]["population"] == 20000


def test_total_area_metric_uses_real_area_fields():
    facilities = _facilities()
    facilities.append(
        {
            "facility_id": "market-2",
            "canonical_class": "facility.market",
            "admin_code": "area-1",
            "facility_area_m2": 700.0,
            "capacity": 100.0,
        }
    )
    result = evaluate_fpp(
        facilities=facilities,
        population_units=_population(),
        profile=_profile("total_facility_area", 1000.0, "m2", ["facility_area_m2"]),
        admin_code="area-1",
    )
    assert result["observed_value"] == 1100.0
    assert result["status"] == "meets"


def test_proposal_without_capacity_keeps_capacity_metric_unresolved():
    facilities = _facilities()
    facilities.append(
        {
            "facility_id": "proposal-1",
            "canonical_class": "facility.market",
            "admin_code": "area-1",
            "record_status": "proposed",
            "capacity": None,
        }
    )
    result = evaluate_fpp(
        facilities=facilities,
        population_units=_population(),
        profile=_profile(
            "capacity_per_10000_residents",
            50.0,
            "capacity_per_10000_residents",
            ["capacity", "population"],
        ),
        admin_code="area-1",
    )
    assert result["status"] == "unresolved"
    assert "facility_capacity_missing:proposal-1" in result["blockers"]


def test_incomplete_inventory_caps_claim_and_inputs_are_not_mutated():
    facilities = _facilities()
    population = _population()
    before_facilities = deepcopy(facilities)
    before_population = deepcopy(population)
    result = evaluate_fpp(
        facilities=facilities,
        population_units=population,
        profile=_profile("facility_count", 1.0, "count", []),
        admin_code="area-1",
        complete_facility_inventory=False,
    )
    assert result["status"] == "meets"
    assert result["max_claim_level"] == "bounded_sample_diagnostic"
    assert "facility_inventory_incomplete" in result["completeness_warnings"]
    assert facilities == before_facilities
    assert population == before_population
