from data_agent.uwm.traditional_housing_community import build_housing_community_product


def fixtures():
    morphology=[{"admin_unit_id":"A|T|1","county":"A","township":"T","building_count":10,"floor_count_sum":50,"average_floor":5,"max_floor":9,"assignment_rule":"bbox","bbox_area_degrees2":1.2,"service_point_count":2,"essential_service_count":1,"ghsl_population_proxy_sum":100,"ghsl_built_surface_proxy_sum":200}]
    proxy=[{"admin_unit_id":"A|T|1","admin_code":"500001","county":"A","township":"T","district_resident_population":1000,"downscaled_population":120,"allocation_weight":.12,"allocation_basis":"ghsl_population_proxy_sum","synthetic_status":"fitted_proxy"},{"admin_unit_id":"B|X|2","admin_code":"500002","county":"B","township":"X","district_resident_population":2000,"downscaled_population":220,"allocation_weight":.11,"allocation_basis":"built_surface","synthetic_status":"fitted_proxy"}]
    districts=[{"admin_code":"500001","district_name":"A","year":2021,"registered_households_10k":1,"registered_population_10k":3,"registered_urban_population_10k":2,"registered_rural_population_10k":1,"resident_population_10k":2.8,"resident_urban_population_10k":2,"urbanization_rate_percent":71}]
    return morphology,proxy,districts


def test_contract_and_exact_joins():
    m,p,d=fixtures(); product=build_housing_community_product(morphology_rows=m,population_proxy_rows=p,district_rows=d,source_artifacts=["m","p","d"])
    assert product["schema"]=="traditional_livability.housing_community_evidence.v1"
    assert set(product["views"])=={"building_morphology_context","population_context","housing_evidence_readiness"}
    assert product["fabricated_value_count"]==0
    row=next(x for x in product["admin_units"] if x["admin_unit_id"]=="A|T|1")
    assert row["building_morphology_context"]["join_status"]=="exact_supported"
    assert row["population_proxy_context"]["join_status"]=="exact_supported"
    assert row["district_population_context"]["join_status"]=="aggregate_supported"
    assert row["limitations"]["building_count_not_housing_unit_count"] is True
    assert product["channel_readiness"]["affordability"]["status"]=="unavailable"
    assert product["channel_readiness"]["affordability"]["value"] is None
    forbidden={"housing_unit_count","residential_floor_area","housing_supply","housing_shortage","affordability_score","crowding_score","family_suitability_score","mixed_use_balance_score"}
    assert forbidden.isdisjoint(row)


def test_unmatched_stays_null_and_rank_is_evidence_only():
    m,p,d=fixtures(); product=build_housing_community_product(morphology_rows=m,population_proxy_rows=p,district_rows=d,source_artifacts=[])
    row=next(x for x in product["admin_units"] if x["admin_unit_id"]=="B|X|2")
    assert row["building_morphology_context"]["join_status"]=="incompatible"
    assert row["building_morphology_context"]["building_count"] is None
    assert row["district_population_context"]["join_status"]=="reference_only"
    assert row["district_population_context"]["resident_population_10k"] is None
    assert row["relative_housing_community_evidence_gap_rank"] < next(x for x in product["admin_units"] if x["admin_unit_id"]=="A|T|1")["relative_housing_community_evidence_gap_rank"]
    assert "relative_housing_community_evidence_gap_rank" in row
    assert "housing_shortage_score" not in row
