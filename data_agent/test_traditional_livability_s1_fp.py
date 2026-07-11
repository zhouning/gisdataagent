from copy import deepcopy

from shapely.geometry import Point, box, mapping

from data_agent.uwm.traditional_livability_s1_fp import evaluate_fp


def _facilities():
    return [
        {
            "facility_id": "market-1",
            "canonical_class": "facility.market",
            "admin_code": "area-1",
            "metric_geometry": mapping(Point(0, 0)),
            "metric_crs": "EPSG:3857",
        }
    ]


def _demand_units():
    return [
        {
            "demand_unit_id": "demand-near",
            "admin_code": "area-1",
            "population": 100,
            "metric_geometry": mapping(box(-100, -100, 100, 100)),
            "metric_crs": "EPSG:3857",
        },
        {
            "demand_unit_id": "demand-far",
            "admin_code": "area-1",
            "population": 300,
            "metric_geometry": mapping(box(900, -100, 1100, 100)),
            "metric_crs": "EPSG:3857",
        },
    ]


def _profile(radius=800.0):
    return {
        "profile_id": "market-fp-v1",
        "standard_class_id": "facility.market",
        "status": "valid",
        "authority_level": "authoritative",
        "metrics": [
            {
                "dimension": "FP",
                "metric": "population_weighted_demand_geometry_coverage_rate",
                "unit": "percent",
                "comparator": ">=",
                "threshold": 50.0,
                "spatial_method": "euclidean_service_radius",
                "distance_crs": "EPSG:3857",
                "service_radius_m": radius,
                "required_source_fields": ["population", "metric_geometry"],
            }
        ],
    }


def test_fp_uses_profile_radius_not_s6_screening_radius():
    result = evaluate_fp(
        facilities=_facilities(),
        demand_units=_demand_units(),
        profile=_profile(radius=800.0),
        admin_code="area-1",
    )
    assert result["method_parameters"]["service_radius_m"] == 800.0
    assert result["method_parameters"]["service_radius_m"] != 150.0
    assert result["observed_value"] == 25.0
    assert result["status"] == "does_not_meet"
    assert result["evidence"]["covered_population"] == 100
    assert result["evidence"]["total_population"] == 400


def test_larger_authoritative_radius_changes_covered_demand():
    result = evaluate_fp(
        facilities=_facilities(),
        demand_units=_demand_units(),
        profile=_profile(radius=1200.0),
        admin_code="area-1",
    )
    assert result["observed_value"] == 100.0
    assert result["status"] == "meets"
    assert len(result["geojson"]["service_areas"]["features"]) == 1
    assert len(result["geojson"]["covered_demand_units"]["features"]) == 2


def test_network_fp_without_authoritative_network_is_unresolved():
    profile = _profile()
    profile["metrics"][0]["spatial_method"] = "network_service_area"
    profile["metrics"][0].pop("service_radius_m")
    result = evaluate_fp(
        facilities=_facilities(), demand_units=_demand_units(), profile=profile, admin_code="area-1"
    )
    assert result["status"] == "unresolved"
    assert "authoritative_network_missing" in result["blockers"]


def test_incomplete_inventory_caps_claim_and_inputs_are_detached():
    facilities = _facilities()
    demand = _demand_units()
    before_facilities = deepcopy(facilities)
    before_demand = deepcopy(demand)
    result = evaluate_fp(
        facilities=facilities,
        demand_units=demand,
        profile=_profile(),
        admin_code="area-1",
        complete_facility_inventory=False,
    )
    assert result["max_claim_level"] == "bounded_sample_diagnostic"
    assert "facility_inventory_incomplete" in result["completeness_warnings"]
    result["geojson"]["service_areas"]["features"].clear()
    assert facilities == before_facilities
    assert demand == before_demand
