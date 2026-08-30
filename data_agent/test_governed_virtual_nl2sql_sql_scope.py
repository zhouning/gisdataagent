import json
from pathlib import Path

import pytest

from data_agent.governed_virtual_nl2sql import (
    GovernedVirtualNL2SQLError,
    apply_metric_projection_contract,
    validate_semantic_sql,
)


def _layer():
    tables = {
        "public.dim_districts": ["district_id", "name_en"],
        "public.dim_facilities": ["district_id", "facility_uuid"],
        "public.fact_population": ["district_id", "total_population"],
    }
    return {
        "table_bindings": [
            {
                "physical_table": name,
                "fields": [{"physical_field": field} for field in fields],
            }
            for name, fields in tables.items()
        ],
        "relationships": [
            {
                "left": "public.dim_districts.district_id",
                "right": "public.dim_facilities.district_id",
                "kind": "equality",
            },
            {
                "left": "public.dim_districts.district_id",
                "right": "public.fact_population.district_id",
                "kind": "equality",
            },
        ],
        "metric_contracts": [
            {
                "contract_id": "TEST_FACILITIES_PER_10000",
                "review_status": "reviewed_candidate",
                "operation": "grouped_summary",
                "match": {
                    "required_term_groups": {
                        "ar": [["مرافق"], ["السكان", "نسمة"]],
                        "en": [["facilities"], ["population"]],
                        "zh": [["设施"], ["人口"]],
                    }
                },
                "tables": list(tables),
                "dimensions": [
                    {
                        "table": "public.dim_districts",
                        "field": "name_en",
                        "alias": "district_name",
                    }
                ],
                "metrics": [
                    {
                        "aggregate": "count_distinct",
                        "table": "public.dim_facilities",
                        "field": "facility_uuid",
                        "alias": "facility_count",
                    },
                    {
                        "aggregate": "sum",
                        "table": "public.fact_population",
                        "field": "total_population",
                        "alias": "total_population",
                    },
                ],
                "order_by": ["district_name"],
                "canonical_sql_template": (
                    "WITH facility_counts AS ("
                    " SELECT district_id, COUNT(DISTINCT facility_uuid) AS facility_count"
                    " FROM public.dim_facilities GROUP BY district_id),"
                    " population_totals AS ("
                    " SELECT district_id, SUM(total_population) AS total_population"
                    " FROM public.fact_population GROUP BY district_id)"
                    " SELECT d.name_en AS district_name, f.facility_count,"
                    " p.total_population, f.facility_count * 10000.0 /"
                    " NULLIF(p.total_population, 0) AS facilities_per_10000"
                    " FROM public.dim_districts AS d"
                    " JOIN facility_counts AS f ON f.district_id = d.district_id"
                    " JOIN population_totals AS p ON p.district_id = d.district_id"
                    " ORDER BY district_name LIMIT 1000"
                ),
            }
        ],
    }


def test_cte_aliases_and_canonical_template_are_governed():
    layer = _layer()
    sql, evidence = apply_metric_projection_contract(
        question="كم عدد المرافق لكل عشرة آلاف نسمة في كل منطقة؟",
        language="ar",
        sql=(
            "SELECT d.name_en, f.facility_count, p.total_population "
            "FROM public.dim_districts d "
            "JOIN public.dim_facilities f ON f.district_id = d.district_id "
            "JOIN public.fact_population p ON p.district_id = d.district_id"
        ),
        proposal_tables=list(
            ["public.dim_districts", "public.dim_facilities", "public.fact_population"]
        ),
        semantic_layer=layer,
    )
    assert evidence["contract_id"] == "TEST_FACILITIES_PER_10000"
    validated = validate_semantic_sql(
        sql,
        ["public.dim_districts", "public.dim_facilities", "public.fact_population"],
        layer,
    )
    assert validated["tables"] == [
        "public.dim_districts",
        "public.dim_facilities",
        "public.fact_population",
    ]


def test_derived_subquery_alias_is_resolved_without_physical_access_bypass():
    layer = _layer()
    sql = (
        "SELECT f.district_id, f.facility_count "
        "FROM (SELECT district_id, COUNT(*) AS facility_count "
        "FROM public.dim_facilities GROUP BY district_id) AS f"
    )
    validated = validate_semantic_sql(sql, ["public.dim_facilities"], layer)
    assert validated["tables"] == ["public.dim_facilities"]


def test_unknown_derived_column_is_rejected():
    layer = _layer()
    sql = (
        "SELECT f.not_governed FROM (SELECT district_id "
        "FROM public.dim_facilities) AS f"
    )
    with pytest.raises(GovernedVirtualNL2SQLError, match="derived_field_rejected:f.not_governed"):
        validate_semantic_sql(sql, ["public.dim_facilities"], layer)


def test_reviewed_business_contracts_canonicalize_spatial_and_population_queries():
    root = Path(__file__).resolve().parents[1]
    makani = json.loads(
        (root / "docs/customer/abu_dhabi_liveability_site_validation/makani_sync_full_semantic_layer_v3.json")
        .read_text(encoding="utf-8")
    )
    liveability = json.loads(
        (root / "docs/customer/abu_dhabi_liveability_site_validation/liveability_data_20260730_semantic_layer_v3.json")
        .read_text(encoding="utf-8")
    )

    area_sql, area_evidence = apply_metric_projection_contract(
        question="What is the mapped land area of the districts in each municipality, in square kilometres?",
        language="en",
        sql="SELECT municipalityname, SUM(ST_Area(shape::geography)) FROM public.udm_district GROUP BY municipalityname",
        proposal_tables=["public.udm_district"],
        semantic_layer=makani,
    )
    assert area_evidence["contract_id"] == "MAKANI_DISTRICT_AREA_BY_MUNICIPALITY_V4"
    assert "SUM(ST_Area(shape::geography)) / 1000000.0" in area_sql

    population_sql, population_evidence = apply_metric_projection_contract(
        question="ما إجمالي السكان في كل منطقة؟",
        language="ar",
        sql="SELECT district_name_en, SUM(total_population) FROM public.fact_population GROUP BY district_name_en",
        proposal_tables=["public.fact_population"],
        semantic_layer=liveability,
    )
    assert population_evidence["contract_id"] == "LIVEABILITY_POPULATION_BY_REGION_V4"
    assert "GROUP BY region" in population_sql


def test_reviewed_plot_status_contract_prefers_business_field_over_generic_status():
    root = Path(__file__).resolve().parents[1]
    makani = json.loads(
        (
            root
            / "docs/customer/abu_dhabi_liveability_site_validation/"
            "makani_sync_full_semantic_layer_v3.json"
        ).read_text(encoding="utf-8")
    )

    rewritten, evidence = apply_metric_projection_contract(
        question="Show the number of land plots in each construction status.",
        language="en",
        sql=(
            "SELECT status, COUNT(*) AS row_count "
            "FROM public.udm_plot GROUP BY status ORDER BY status"
        ),
        proposal_tables=["public.udm_plot"],
        semantic_layer=makani,
    )

    assert evidence is not None
    assert evidence["contract_id"] == "MAKANI_PLOT_COUNT_BY_CONSTRUCTION_STATUS_V4"
    assert "SELECT construction_status" in rewritten
    assert "GROUP BY construction_status" in rewritten
    admitted = validate_semantic_sql(rewritten, ["public.udm_plot"], makani)
    assert admitted["columns"] == ["public.udm_plot.construction_status"]
