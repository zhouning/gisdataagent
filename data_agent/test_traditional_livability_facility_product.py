from data_agent.uwm.traditional_livability_facility_product import (
    build_facility_data_product,
)


def _build_product(*, poi_rows=None, aoi_rows=None, population_rows=None):
    return build_facility_data_product(
        product_id="chongqing-facility-product-2026-07-10",
        created_at="2026-07-10T12:00:00+08:00",
        poi_rows=poi_rows or [],
        aoi_rows=aoi_rows or [],
        population_rows=population_rows or [],
        source_manifest={
            "manifest_id": "planning-sample-audit-v1",
            "sources": ["gaode_poi", "baidu_aoi", "admin_population_2021"],
        },
    )


def test_builds_versioned_chongqing_facility_product_and_maps_primary_school():
    product = _build_product(
        poi_rows=[
            {
                "source_record_id": "poi-001",
                "source_dataset_id": "gaode_poi",
                "raw_primary_class": "科教文化服务",
                "raw_secondary_class": "学校",
                "raw_tertiary_class": "小学",
                "admin_code": "500103",
                "longitude": 106.57,
                "latitude": 29.56,
                "geometry_type": "Point",
            }
        ]
    )

    assert product["schema"] == "uwm.traditional_livability.facility_product.v1"
    assert product["product_id"] == "chongqing-facility-product-2026-07-10"
    assert product["created_at"] == "2026-07-10T12:00:00+08:00"
    assert product["geography"]["executed_area"] == "重庆市"
    assert product["mapping_version"] == "traditional_livability_facility_mapping.v1"
    facility = product["facilities"][0]
    assert facility["canonical_class"] == "education_primary_school"
    assert facility["mapping_status"] == "mapped"
    assert facility["source_record_id"] == "poi-001"
    assert facility["source_dataset_id"] == "gaode_poi"
    assert facility["raw_primary_class"] == "科教文化服务"
    assert facility["raw_secondary_class"] == "学校"
    assert facility["raw_tertiary_class"] == "小学"
    assert facility["admin_code"] == "500103"
    assert facility["longitude"] == 106.57
    assert facility["latitude"] == 29.56
    assert facility["geometry_type"] == "Point"


def test_unknown_class_is_preserved_and_never_guessed():
    product = _build_product(
        aoi_rows=[
            {
                "source_record_id": "aoi-unknown",
                "source_dataset_id": "baidu_aoi",
                "raw_primary_class": "未来设施",
                "raw_secondary_class": "未定义服务",
                "raw_tertiary_class": "量子驿站",
                "admin_code": "500105",
                "longitude": 106.55,
                "latitude": 29.61,
                "geometry_type": "Polygon",
            }
        ]
    )

    facility = product["facilities"][0]
    assert facility["canonical_class"] == "unmapped"
    assert facility["mapping_status"] == "unmapped"
    assert facility["raw_primary_class"] == "未来设施"
    assert facility["raw_secondary_class"] == "未定义服务"
    assert facility["raw_tertiary_class"] == "量子驿站"


def test_normalizes_population_with_fixed_resident_population_basis():
    product = _build_product(
        population_rows=[
            {
                "source_record_id": "pop-500103",
                "source_dataset_id": "admin_population_2021",
                "admin_code": "500103",
                "admin_name": "渝中区",
                "population": "588717",
            }
        ]
    )

    assert product["population_units"] == [
        {
            "source_record_id": "pop-500103",
            "source_dataset_id": "admin_population_2021",
            "admin_code": "500103",
            "admin_name": "渝中区",
            "population": 588717,
            "population_basis": "resident_population_2021",
        }
    ]


def test_declares_non_authoritative_claim_boundary_and_production_blockers():
    product = _build_product()

    boundary = product["claim_boundary"]
    assert boundary["authoritative_fp_fpp_available"] is False
    assert "authoritative_43_class_facility_dictionary_missing" in boundary["production_blockers"]
    assert "authoritative_fp_fpp_thresholds_missing" in boundary["production_blockers"]
    assert "facility_capacity_and_operating_status_missing" in boundary["production_blockers"]


def test_deduplicates_only_by_source_dataset_and_source_record_id():
    shared = {
        "source_record_id": "same-id",
        "raw_primary_class": "交通设施服务",
        "raw_secondary_class": "公共交通",
        "raw_tertiary_class": "公交车站",
        "admin_code": "500103",
        "longitude": 106.57,
        "latitude": 29.56,
        "geometry_type": "Point",
    }
    product = _build_product(
        poi_rows=[
            {**shared, "source_dataset_id": "gaode_poi"},
            {**shared, "source_dataset_id": "gaode_poi"},
        ],
        aoi_rows=[
            {
                **shared,
                "source_dataset_id": "baidu_aoi",
                "geometry_type": "Polygon",
            }
        ],
    )

    assert len(product["facilities"]) == 2
    assert {
        (row["source_dataset_id"], row["source_record_id"])
        for row in product["facilities"]
    } == {("gaode_poi", "same-id"), ("baidu_aoi", "same-id")}


def test_mapping_contract_explicitly_covers_required_facility_domains():
    product = _build_product()

    assert set(product["mapping_contract"]["covered_domains"]) >= {
        "education",
        "healthcare",
        "green_space_park",
        "culture",
        "sports",
        "public_safety",
        "government_community",
        "transport",
    }
