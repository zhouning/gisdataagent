from __future__ import annotations

from copy import deepcopy
from typing import Any, Iterable, Mapping


SCHEMA = "uwm.traditional_livability.facility_product.v1"
MAPPING_VERSION = "traditional_livability_facility_mapping.v1"
POPULATION_BASIS = "resident_population_2021"

_RAW_CLASS_FIELDS = (
    "raw_primary_class",
    "raw_secondary_class",
    "raw_tertiary_class",
)

_FACILITY_CLASS_MAPPING = (
    {
        "domain": "education",
        "canonical_class": "education.primary_school",
        "raw_classes": frozenset({"小学", "小学校"}),
    },
    {
        "domain": "education",
        "canonical_class": "education.school",
        "raw_classes": frozenset({"学校", "中学", "幼儿园", "高等院校"}),
    },
    {
        "domain": "healthcare",
        "canonical_class": "healthcare.facility",
        "raw_classes": frozenset(
            {"医疗保健服务", "医院", "综合医院", "专科医院", "社区卫生服务中心", "诊所"}
        ),
    },
    {
        "domain": "green_space_park",
        "canonical_class": "green_space.park",
        "raw_classes": frozenset({"公园广场", "公园", "城市公园", "社区公园", "广场"}),
    },
    {
        "domain": "culture",
        "canonical_class": "culture.facility",
        "raw_classes": frozenset({"文化场馆", "图书馆", "博物馆", "文化馆", "科技馆"}),
    },
    {
        "domain": "sports",
        "canonical_class": "sports.facility",
        "raw_classes": frozenset({"体育休闲服务", "体育场馆", "体育馆", "运动场", "健身中心"}),
    },
    {
        "domain": "public_safety",
        "canonical_class": "public_safety.facility",
        "raw_classes": frozenset({"公共安全", "公安机关", "派出所", "消防站", "消防机关"}),
    },
    {
        "domain": "government_community",
        "canonical_class": "government_community.facility",
        "raw_classes": frozenset(
            {"政府机构及社会团体", "政府机关", "街道办事处", "社区服务中心", "居民委员会"}
        ),
    },
    {
        "domain": "transport",
        "canonical_class": "transport.facility",
        "raw_classes": frozenset(
            {"交通设施服务", "公共交通", "公交车站", "地铁站", "长途汽车站", "火车站"}
        ),
    },
)

_COVERED_DOMAINS = tuple(dict.fromkeys(rule["domain"] for rule in _FACILITY_CLASS_MAPPING))

_PRODUCTION_BLOCKERS = (
    "authoritative_43_class_facility_dictionary_missing",
    "authoritative_fp_fpp_thresholds_missing",
    "facility_capacity_and_operating_status_missing",
)


def _map_facility_class(row: Mapping[str, Any]) -> tuple[str, str]:
    raw_classes = {
        str(row.get(field)).strip()
        for field in _RAW_CLASS_FIELDS
        if row.get(field) is not None and str(row.get(field)).strip()
    }
    for rule in _FACILITY_CLASS_MAPPING:
        if raw_classes.intersection(rule["raw_classes"]):
            return str(rule["canonical_class"]), "mapped_internal_taxonomy"
    return "unmapped", "unmapped"


def _normalize_facility(row: Mapping[str, Any]) -> dict[str, Any]:
    canonical_class, mapping_status = _map_facility_class(row)
    return {
        "name": row.get("name"),
        "source_record_id": row.get("source_record_id"),
        "source_dataset_id": row.get("source_dataset_id"),
        "raw_primary_class": row.get("raw_primary_class"),
        "raw_secondary_class": row.get("raw_secondary_class"),
        "raw_tertiary_class": row.get("raw_tertiary_class"),
        "canonical_class": canonical_class,
        "mapping_status": mapping_status,
        "admin_code": row.get("admin_code"),
        "longitude": row.get("longitude"),
        "latitude": row.get("latitude"),
        "geometry_type": row.get("geometry_type"),
    }


def _deduplicated_facilities(
    poi_rows: Iterable[Mapping[str, Any]],
    aoi_rows: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    facilities = []
    seen_keys = set()
    for row in (*poi_rows, *aoi_rows):
        key = (row.get("source_dataset_id"), row.get("source_record_id"))
        if key in seen_keys:
            continue
        seen_keys.add(key)
        facilities.append(_normalize_facility(row))
    return facilities


def _normalize_population(row: Mapping[str, Any]) -> dict[str, Any]:
    population = row.get("population")
    if population is not None:
        population = int(population)
    return {
        "source_record_id": row.get("source_record_id"),
        "source_dataset_id": row.get("source_dataset_id"),
        "admin_code": row.get("admin_code"),
        "admin_name": row.get("admin_name"),
        "population": population,
        "population_basis": POPULATION_BASIS,
    }


def build_facility_data_product(
    *,
    product_id: str,
    created_at: str,
    poi_rows: Iterable[Mapping[str, Any]],
    aoi_rows: Iterable[Mapping[str, Any]],
    population_rows: Iterable[Mapping[str, Any]],
    source_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    poi_rows = list(poi_rows)
    aoi_rows = list(aoi_rows)
    population_rows = list(population_rows)
    facilities = _deduplicated_facilities(poi_rows, aoi_rows)
    population_units = [_normalize_population(row) for row in population_rows]
    production_blockers = list(_PRODUCTION_BLOCKERS)
    return {
        "schema": SCHEMA,
        "product_id": product_id,
        "created_at": created_at,
        "mapping_version": MAPPING_VERSION,
        "geography": {"executed_area": "重庆市"},
        "source_manifest": deepcopy(dict(source_manifest)),
        "mapping_contract": {
            "version": MAPPING_VERSION,
            "covered_domains": list(_COVERED_DOMAINS),
            "unknown_class_policy": "preserve_raw_and_mark_unmapped",
        },
        "facilities": facilities,
        "population_units": population_units,
        "quality_summary": {
            "input_poi_rows": len(poi_rows),
            "input_aoi_rows": len(aoi_rows),
            "input_population_rows": len(population_rows),
            "facility_rows_after_deduplication": len(facilities),
            "duplicate_facility_rows_removed": (
                len(poi_rows) + len(aoi_rows) - len(facilities)
            ),
            "mapped_facility_rows": sum(
                facility["mapping_status"] == "mapped_internal_taxonomy"
                for facility in facilities
            ),
            "unmapped_facility_rows": sum(
                facility["mapping_status"] == "unmapped" for facility in facilities
            ),
            "population_unit_rows": len(population_units),
        },
        "production_blockers": production_blockers,
        "claim_boundary": {
            "authoritative_fp_fpp_available": False,
            "production_blockers": list(production_blockers),
        },
    }
