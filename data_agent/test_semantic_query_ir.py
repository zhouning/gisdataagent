from __future__ import annotations

import json
from pathlib import Path

import pytest

from data_agent.semantic_query_ir import (
    AdHocSemanticQueryIR,
    FederatedMergeStrategy,
    JoinKind,
    SpatialIntent,
    SemanticIRCompilationError,
    SemanticQueryRoute,
    build_compiled_ad_hoc_semantic_plan,
    build_certified_metric_contract_plan,
    build_federated_semantic_plan_evidence,
    build_shadow_semantic_plan_evidence,
    infer_spatial_intent,
)
from data_agent.governed_virtual_nl2sql import validate_semantic_sql
from data_agent.connectors.database import validate_database_read_query

SOURCE = {
    "source_id": 12,
    "source_name": "abu-dhabi-liveability-dev",
    "database_name": "liveability_data_20260730",
    "authorized_schemas": ["public"],
    "discovery_fingerprint": "a" * 64,
}

MAKANI_SEMANTIC_PATH = (
    Path(__file__).resolve().parents[1]
    / "docs/customer/abu_dhabi_liveability_site_validation"
    / "makani_sync_full_semantic_layer_v3.json"
)
LIVEABILITY_SEMANTIC_PATH = (
    Path(__file__).resolve().parents[1]
    / "docs/customer/abu_dhabi_liveability_site_validation"
    / "liveability_data_20260730_semantic_layer_v3.json"
)
LIVEABILITY_PUBLISHED_JSON_SEMANTIC_PATH = (
    Path(__file__).resolve().parents[1]
    / "docs/customer/abu_dhabi_liveability_site_validation"
    / "liveability_data_20260730_semantic_layer_v8_published_table_cards_json_contract_20260901.json"
)
LIVEABILITY_V24_SEMANTIC_PATH = (
    Path(__file__).resolve().parents[1]
    / "docs/customer/abu_dhabi_liveability_site_validation"
    / "liveability_data_20260730_semantic_layer_v24_display_disambiguation_20260902.json"
)


def _makani_semantic_layer() -> dict:
    return json.loads(MAKANI_SEMANTIC_PATH.read_text(encoding="utf-8"))


def _liveability_semantic_layer() -> dict:
    return json.loads(LIVEABILITY_SEMANTIC_PATH.read_text(encoding="utf-8"))


def _liveability_published_json_semantic_layer() -> dict:
    return json.loads(LIVEABILITY_PUBLISHED_JSON_SEMANTIC_PATH.read_text(encoding="utf-8"))


def _liveability_v24_semantic_layer() -> dict:
    return json.loads(LIVEABILITY_V24_SEMANTIC_PATH.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("Show facilities inside each district.", SpatialIntent.WITHIN),
        ("统计区域范围内的设施。", SpatialIntent.WITHIN),
        ("Find facilities within 500 metres of a road.", SpatialIntent.DISTANCE),
        ("Count overlapping parcels.", SpatialIntent.INTERSECTS),
        ("Count facilities by district association.", SpatialIntent.NONE),
    ],
)
def test_spatial_intent_inference_distinguishes_geometry_from_equality(
    question: str, expected: SpatialIntent
) -> None:
    assert infer_spatial_intent(question) is expected


def _makani_building_inside_district_ir() -> AdHocSemanticQueryIR:
    return AdHocSemanticQueryIR.model_validate(
        {
            "language": "en",
            "status": "query",
            "semantic_entity": "dmt_utility.udm_building",
            "spatial_intent": "within",
            "projections": [
                {
                    "output_name": "district_name",
                    "role": "dimension",
                    "field_ref": {
                        "semantic_entity": "dmt_utility.udm_district",
                        "semantic_field": "nameenglish",
                    },
                },
                {
                    "output_name": "building_count",
                    "role": "metric",
                    "aggregate": "count",
                },
            ],
            "joins": [
                {
                    "left_field_ref": {
                        "semantic_entity": "dmt_utility.udm_building",
                        "semantic_field": "shape",
                    },
                    "right_field_ref": {
                        "semantic_entity": "dmt_utility.udm_district",
                        "semantic_field": "shape",
                    },
                    "kind": "spatial",
                    "operator": "st_intersects",
                }
            ],
        }
    )


def test_ad_hoc_semantic_compiler_accepts_reviewed_contains_intersects_for_within() -> None:
    semantic_layer = _makani_semantic_layer()
    plan = build_compiled_ad_hoc_semantic_plan(
        semantic_ir=_makani_building_inside_district_ir(),
        source={"source_id": 13, "database_name": "makani_sync_full"},
        semantic_version=semantic_layer["semantic_version"],
        semantic_layer=semantic_layer,
        max_rows=1000,
        expected_spatial_intent=SpatialIntent.WITHIN,
    )

    assert "ST_Intersects(gda_source.\"shape\", gda_join_001.\"shape\")" in plan.compiled_statement
    assert plan.physical_plan.spatial_operators == ("st_intersects",)


def test_ad_hoc_semantic_ir_accepts_single_entity_count_without_field_reference() -> None:
    semantic_layer = _makani_semantic_layer()
    semantic_ir = AdHocSemanticQueryIR.model_validate(
        {
            "language": "en",
            "status": "query",
            "semantic_entity": "dmt_utility.udm_building",
            "projections": [
                {
                    "output_name": "building_count",
                    "role": "metric",
                    "aggregate": "count",
                }
            ],
        }
    )
    plan = build_compiled_ad_hoc_semantic_plan(
        semantic_ir=semantic_ir,
        source={"source_id": 13, "database_name": "makani_sync_full"},
        semantic_version=semantic_layer["semantic_version"],
        semantic_layer=semantic_layer,
        max_rows=1000,
    )
    assert 'SELECT COUNT(*) AS "building_count"' in plan.compiled_statement


def test_ad_hoc_semantic_compiler_adds_reviewed_display_companion() -> None:
    semantic_layer = _liveability_v24_semantic_layer()
    semantic_ir = AdHocSemanticQueryIR.model_validate(
        {
            "language": "en",
            "status": "query",
            "semantic_entity": "dmt_liveability.fact_facility_provision",
            "projections": [
                {
                    "output_name": "district_name",
                    "role": "dimension",
                    "field_ref": {
                        "semantic_entity": "dmt_liveability.dim_districts",
                        "semantic_field": "name_en",
                    },
                },
                {
                    "output_name": "facility_count",
                    "role": "metric",
                    "aggregate": "count",
                },
            ],
            "joins": [
                {
                    "left_field_ref": {
                        "semantic_entity": "dmt_liveability.fact_facility_provision",
                        "semantic_field": "district_id",
                    },
                    "right_field_ref": {
                        "semantic_entity": "dmt_liveability.dim_districts",
                        "semantic_field": "district_id",
                    },
                    "kind": "equality",
                    "operator": "eq",
                }
            ],
        }
    )

    plan = build_compiled_ad_hoc_semantic_plan(
        semantic_ir=semantic_ir,
        source=SOURCE,
        semantic_version=semantic_layer["semantic_version"],
        semantic_layer=semantic_layer,
        max_rows=1000,
    )

    assert plan.compiler_added_output_names == ("municipality",)
    assert [item.output_name for item in plan.semantic_ir.projections] == [
        "district_name",
        "municipality",
        "facility_count",
    ]
    assert 'gda_join_001."municipality" AS "municipality"' in plan.compiled_statement


def test_ad_hoc_semantic_compiler_compiles_independent_grouped_extrema() -> None:
    semantic_layer = _makani_semantic_layer()
    semantic_ir = AdHocSemanticQueryIR.model_validate(
        {
            "language": "en",
            "status": "query",
            "semantic_entity": "dmt_utility.udm_building",
            "projections": [
                {
                    "output_name": "municipality_name",
                    "role": "dimension",
                    "field_ref": {
                        "semantic_entity": "dmt_utility.udm_building",
                        "semantic_field": "municipalityname",
                    },
                },
                {
                    "output_name": "building_count",
                    "role": "metric",
                    "aggregate": "count",
                },
            ],
            "extreme_order_by": [
                {"output_name": "building_count", "direction": "desc"},
                {"output_name": "building_count", "direction": "asc"},
            ],
        }
    )
    plan = build_compiled_ad_hoc_semantic_plan(
        semantic_ir=semantic_ir,
        source={"source_id": 13, "database_name": "makani_sync_full"},
        semantic_version=semantic_layer["semantic_version"],
        semantic_layer=semantic_layer,
        max_rows=1000,
    )

    assert plan.compiled_statement.count("FETCH FIRST 1 ROW WITH TIES") == 2
    assert "UNION ALL" in plan.compiled_statement
    # Each ordered FETCH branch must be parenthesized for PostgreSQL.  Run
    # the same governed SQL validator used by the runtime so this regression
    # catches parser failures before a live benchmark consumes a model call.
    evidence = validate_semantic_sql(
        plan.compiled_statement,
        list(plan.physical_plan.tables),
        semantic_layer,
    )
    assert evidence["tables"] == list(plan.physical_plan.tables)
    bounded = validate_database_read_query(
        plan.compiled_statement,
        {"allowed_schemas": ["public"], "max_rows": 1000},
        limit=2,
    )
    assert bounded.startswith("SELECT * FROM (WITH ")
    assert bounded.endswith("LIMIT 2")
    assert 'ORDER BY "building_count" DESC' in plan.compiled_statement
    assert 'ORDER BY "building_count" ASC' in plan.compiled_statement
    set_nodes = [node for node in plan.logical_plan.nodes if node.operator == "set_operation"]
    assert len(set_nodes) == 1
    assert set_nodes[0].attributes["branch_count"] == 2


def test_ad_hoc_semantic_compiler_places_aggregate_condition_in_having() -> None:
    semantic_layer = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "docs/customer/abu_dhabi_liveability_site_validation"
            / "liveability_data_20260730_semantic_layer_v21_answerability_data_quality_20260902.json"
        ).read_text(encoding="utf-8")
    )
    semantic_ir = AdHocSemanticQueryIR.model_validate(
        {
            "language": "en",
            "status": "query",
            "semantic_entity": "dmt_liveability.fact_facility_provision",
            "projections": [
                {
                    "output_name": "facility_type",
                    "role": "dimension",
                    "field_ref": {
                        "semantic_entity": "dmt_liveability.fact_facility_provision",
                        "semantic_field": "subcategory_name",
                    },
                },
                {
                    "output_name": "existing_facility_count",
                    "role": "metric",
                    "aggregate": "sum",
                    "field_ref": {
                        "semantic_entity": "dmt_liveability.fact_facility_provision",
                        "semantic_field": "existing_count",
                    },
                },
            ],
            "having_filters": [
                {
                    "field_ref": {
                        "semantic_entity": "dmt_liveability.fact_facility_provision",
                        "semantic_field": "demand_current",
                    },
                    "aggregate": "sum",
                    "operator": "gt",
                    "values": [0],
                }
            ],
        }
    )
    plan = build_compiled_ad_hoc_semantic_plan(
        semantic_ir=semantic_ir,
        source={"source_id": 12, "database_name": "liveability_data_20260730"},
        semantic_version=semantic_layer["semantic_version"],
        semantic_layer=semantic_layer,
        max_rows=1000,
    )

    assert 'HAVING SUM(gda_source."demand_current") > :gda_p_001' in plan.compiled_statement
    assert 'WHERE gda_source."demand_current"' not in plan.compiled_statement
    having_nodes = [
        node for node in plan.logical_plan.nodes
        if node.operator == "filter" and node.attributes.get("predicate_stage") == "post_aggregate"
    ]
    assert len(having_nodes) == 1


def test_ad_hoc_semantic_compiler_hides_condition_only_metric_projection() -> None:
    semantic_layer = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "docs/customer/abu_dhabi_liveability_site_validation"
            / "liveability_data_20260730_semantic_layer_v32_facility_type_semantics_20260904.json"
        ).read_text(encoding="utf-8")
    )
    semantic_ir = AdHocSemanticQueryIR.model_validate(
        {
            "language": "en",
            "status": "query",
            "semantic_entity": "dmt_liveability.fact_facility_provision",
            "projections": [
                {
                    "output_name": "facility_type",
                    "role": "dimension",
                    "field_ref": {
                        "semantic_entity": "dmt_liveability.fact_facility_provision",
                        "semantic_field": "subcategory_name",
                    },
                },
                {
                    "output_name": "min_fpp_score",
                    "role": "metric",
                    "aggregate": "min",
                    "field_ref": {
                        "semantic_entity": "dmt_liveability.fact_facility_provision",
                        "semantic_field": "kpi_existing",
                    },
                },
            ],
            "having_filters": [
                {
                    "field_ref": {
                        "semantic_entity": "dmt_liveability.fact_facility_provision",
                        "semantic_field": "kpi_existing",
                    },
                    "aggregate": "min",
                    "operator": "gte",
                    "values": [100],
                }
            ],
        }
    )
    plan = build_compiled_ad_hoc_semantic_plan(
        semantic_ir=semantic_ir,
        source={"source_id": 12, "database_name": "liveability_data_20260730"},
        semantic_version=semantic_layer["semantic_version"],
        semantic_layer=semantic_layer,
        max_rows=1000,
        question="Which facility types have an FPP score of 100% in every assessed district?",
    )

    assert 'SELECT gda_source."subcategory_name" AS "facility_type"' in plan.compiled_statement
    assert 'AS "min_fpp_score"' not in plan.compiled_statement
    assert plan.compiler_hidden_output_names == ("min_fpp_score",)
    assert 'HAVING MIN(gda_source."kpi_existing") >= :gda_p_001' in plan.compiled_statement


def test_ad_hoc_semantic_compiler_resolves_source_value_and_value_set_aliases() -> None:
    semantic_layer = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "docs/customer/abu_dhabi_liveability_site_validation"
            / "liveability_data_20260730_semantic_layer_v21_answerability_data_quality_20260902.json"
        ).read_text(encoding="utf-8")
    )
    binding = next(
        item for item in semantic_layer["table_bindings"]
        if item.get("physical_table") == "public.fact_facility_provision"
    )
    field = next(
        item for item in binding["fields"]
        if item.get("physical_field") == "subcategory_name"
    )
    field["value_semantics"] = {
        "Healthcare_Medical_Centre": [
            "Healthcare_Medical_Centre", "clinic", "clinics", "medical centre"
        ],
    }
    field["value_domain"] = ["Healthcare_Medical_Centre", "Neighbourhood_Majlis"]
    field["value_set_semantics"] = [{
        "source_values": ["Park_Local", "Park_District"],
        "aliases": ["parks"],
    }]
    semantic_ir = AdHocSemanticQueryIR.model_validate(
        {
            "language": "en",
            "status": "query",
            "semantic_entity": "dmt_liveability.fact_facility_provision",
            "projections": [{
                "output_name": "facility_count",
                "role": "metric",
                "aggregate": "count",
            }],
            "filters": [{
                "field_ref": {
                    "semantic_entity": "dmt_liveability.fact_facility_provision",
                    "semantic_field": "subcategory_name",
                },
                "operator": "eq",
                "values": ["parks"],
            }],
        }
    )
    plan = build_compiled_ad_hoc_semantic_plan(
        semantic_ir=semantic_ir,
        source={"source_id": 12, "database_name": "liveability_data_20260730"},
        semantic_version=semantic_layer["semantic_version"],
        semantic_layer=semantic_layer,
        max_rows=1000,
    )
    assert 'IN (:gda_p_001, :gda_p_002)' in plan.compiled_statement
    assert plan.parameter_bindings["gda_p_001"] == "Park_Local"
    assert plan.parameter_bindings["gda_p_002"] == "Park_District"

    clinic_ir = semantic_ir.model_copy(
        update={
            "filters": (
                semantic_ir.filters[0].model_copy(update={"values": ("Clinic",)}),
            )
        }
    )
    clinic_plan = build_compiled_ad_hoc_semantic_plan(
        semantic_ir=clinic_ir,
        source={"source_id": 12, "database_name": "liveability_data_20260730"},
        semantic_version=semantic_layer["semantic_version"],
        semantic_layer=semantic_layer,
        max_rows=1000,
    )
    assert clinic_plan.parameter_bindings["gda_p_001"] == "Healthcare_Medical_Centre"


def test_ad_hoc_semantic_compiler_prefers_observed_case_for_colliding_enum_keys() -> None:
    semantic_layer = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "docs/customer/abu_dhabi_liveability_site_validation"
            / "liveability_data_20260730_semantic_layer_v34_enum_domains_20260904.json"
        ).read_text(encoding="utf-8")
    )
    semantic_ir = AdHocSemanticQueryIR.model_validate(
        {
            "language": "en",
            "status": "query",
            "semantic_entity": "dmt_liveability.fact_district_scores",
            "projections": [
                {
                    "output_name": "score",
                    "role": "metric",
                    "aggregate": "max",
                    "field_ref": {
                        "semantic_entity": "dmt_liveability.fact_district_scores",
                        "semantic_field": "overall_score",
                    },
                }
            ],
            "filters": [
                {
                    "field_ref": {
                        "semantic_entity": "dmt_liveability.fact_district_scores",
                        "semantic_field": "stage",
                    },
                    "operator": "eq",
                    "values": ["Target stage"],
                }
            ],
        }
    )
    plan = build_compiled_ad_hoc_semantic_plan(
        semantic_ir=semantic_ir,
        source={"source_id": 12, "database_name": "liveability_data_20260730"},
        semantic_version=semantic_layer["semantic_version"],
        semantic_layer=semantic_layer,
        max_rows=1000,
    )
    assert plan.parameter_bindings["gda_p_001"] == "AP50"


def test_ad_hoc_semantic_ir_rejects_conflicting_global_and_extreme_ordering() -> None:
    with pytest.raises(ValueError, match="cannot combine global and extreme ordering"):
        AdHocSemanticQueryIR.model_validate(
            {
                "language": "en",
                "status": "query",
                "semantic_entity": "dmt_utility.udm_building",
                "projections": [
                    {
                        "output_name": "municipality_name",
                        "role": "dimension",
                        "field_ref": {
                            "semantic_entity": "dmt_utility.udm_building",
                            "semantic_field": "municipalityname",
                        },
                    },
                    {
                        "output_name": "building_count",
                        "role": "metric",
                        "aggregate": "count",
                    },
                ],
                "order_by": [
                    {"output_name": "building_count", "direction": "desc"}
                ],
                "extreme_order_by": [
                    {"output_name": "building_count", "direction": "asc"}
                ],
            }
        )


def test_ad_hoc_semantic_compiler_rejects_generic_intersection_as_within() -> None:
    semantic_layer = _makani_semantic_layer()
    for relation in semantic_layer["relationships"]:
        if (
            relation.get("left") == "public.udm_district.shape"
            and relation.get("right") == "public.udm_building.shape"
        ):
            relation["cardinality"] = "many_to_many_spatial"
            break
    with pytest.raises(
        SemanticIRCompilationError,
        match="semantic_ir_spatial_intent_not_supported_by_reviewed_relation",
    ):
        build_compiled_ad_hoc_semantic_plan(
            semantic_ir=_makani_building_inside_district_ir(),
            source={"source_id": 13, "database_name": "makani_sync_full"},
            semantic_version=semantic_layer["semantic_version"],
            semantic_layer=semantic_layer,
            max_rows=1000,
            expected_spatial_intent=SpatialIntent.WITHIN,
        )


def _building_average_ir(*, field: str = "buildingnumberoffloors") -> AdHocSemanticQueryIR:
    return AdHocSemanticQueryIR.model_validate(
        {
            "language": "en",
            "status": "query",
            "semantic_entity": "dmt_utility.udm_building",
            "projections": [
                {
                    "output_name": "municipality_name",
                    "role": "dimension",
                    "field_ref": {
                        "semantic_entity": "dmt_utility.udm_building",
                        "semantic_field": "municipalityname",
                    },
                },
                {
                    "output_name": "average_floor_count",
                    "role": "metric",
                    "aggregate": "avg",
                    "field_ref": {
                        "semantic_entity": "dmt_utility.udm_building",
                        "semantic_field": field,
                    },
                },
            ],
            "filters": [
                {
                    "field_ref": {
                        "semantic_entity": "dmt_utility.udm_building",
                        "semantic_field": "municipalityname",
                    },
                    "operator": "contains",
                    "values": ["Abu Dhabi"],
                }
            ],
            "order_by": [
                {"output_name": "average_floor_count", "direction": "desc"}
            ],
            "limit": 25,
        }
    )


def test_ad_hoc_semantic_compiler_uses_only_logical_identifiers_and_bind_parameters() -> None:
    semantic_layer = _makani_semantic_layer()
    source = {
        "source_id": int(semantic_layer["source_binding"]["source_id"]),
        "database_name": "makani_sync_full",
    }
    semantic_ir = _building_average_ir()

    first = build_compiled_ad_hoc_semantic_plan(
        semantic_ir=semantic_ir,
        source=source,
        semantic_version=semantic_layer["semantic_version"],
        semantic_layer=semantic_layer,
        max_rows=1000,
    )
    second = build_compiled_ad_hoc_semantic_plan(
        semantic_ir=semantic_ir,
        source=source,
        semantic_version=semantic_layer["semantic_version"],
        semantic_layer=semantic_layer,
        max_rows=1000,
    )

    assert "public.udm_building" not in semantic_ir.model_dump_json()
    assert first.execution_authority is True
    assert first.authority == "validated_semantic_ir_postgis_compiler_experimental"
    assert first.physical_plan.tables == ("public.udm_building",)
    assert "FROM public.udm_building AS gda_source" in first.compiled_statement
    assert 'AVG(gda_source."buildingnumberoffloors")' in first.compiled_statement
    assert ":gda_p_001" in first.compiled_statement
    assert "Abu Dhabi" not in first.compiled_statement
    assert first.parameter_bindings == {"gda_p_001": "%ADM%"}
    assert first.fingerprints == second.fingerprints


def test_ad_hoc_semantic_compiler_resolves_reviewed_value_aliases() -> None:
    semantic_layer = _makani_semantic_layer()
    semantic_ir = AdHocSemanticQueryIR.model_validate(
        {
            "language": "en",
            "status": "query",
            "semantic_entity": "dmt_utility.udm_traffichump",
            "projections": [
                {
                    "output_name": "traffic_hump_count",
                    "role": "metric",
                    "aggregate": "count",
                }
            ],
            "filters": [
                {
                    "field_ref": {
                        "semantic_entity": "dmt_utility.udm_traffichump",
                        "semantic_field": "municipalityname",
                    },
                    "operator": "eq",
                    "values": ["Abu Dhabi City"],
                }
            ],
        }
    )

    plan = build_compiled_ad_hoc_semantic_plan(
        semantic_ir=semantic_ir,
        source={"source_id": 13},
        semantic_version=semantic_layer["semantic_version"],
        semantic_layer=semantic_layer,
        max_rows=1000,
    )

    assert plan.parameter_bindings == {"gda_p_001": "ADM"}


def test_ad_hoc_semantic_compiler_compiles_or_groups_and_distinct_rows() -> None:
    semantic_layer = _makani_semantic_layer()
    semantic_ir = AdHocSemanticQueryIR.model_validate(
        {
            "language": "en",
            "status": "query",
            "semantic_entity": "dmt_utility.udm_building",
            "projections": [
                {
                    "output_name": "building_name",
                    "role": "attribute",
                    "field_ref": {
                        "semantic_entity": "dmt_utility.udm_building",
                        "semantic_field": "nameenglish",
                    },
                }
            ],
            "any_filter_groups": [
                {
                    "filters": [
                        {
                            "field_ref": {
                                "semantic_entity": "dmt_utility.udm_building",
                                "semantic_field": "nameenglish",
                            },
                            "operator": "contains",
                            "values": ["City Centre"],
                        },
                        {
                            "field_ref": {
                                "semantic_entity": "dmt_utility.udm_building",
                                "semantic_field": "namepopularenglish",
                            },
                            "operator": "contains",
                            "values": ["City Centre"],
                        },
                    ]
                }
            ],
            "distinct_rows": True,
        }
    )

    plan = build_compiled_ad_hoc_semantic_plan(
        semantic_ir=semantic_ir,
        source={"source_id": 13},
        semantic_version=semantic_layer["semantic_version"],
        semantic_layer=semantic_layer,
        max_rows=1000,
    )

    assert plan.compiled_statement.startswith("SELECT DISTINCT ")
    assert " OR " in plan.compiled_statement
    assert plan.parameter_bindings == {
        "gda_p_001": "%City Centre%",
        "gda_p_002": "%City Centre%",
    }


def test_ad_hoc_semantic_compiler_compiles_entity_count_without_field() -> None:
    semantic_layer = _makani_semantic_layer()
    semantic_ir = AdHocSemanticQueryIR.model_validate(
        {
            "language": "ar",
            "status": "query",
            "semantic_entity": "dmt_utility.udm_building",
            "projections": [
                {
                    "output_name": "primary_land_use",
                    "role": "dimension",
                    "field_ref": {
                        "semantic_entity": "dmt_utility.udm_building",
                        "semantic_field": "primaryuseengdesc",
                    },
                },
                {
                    "output_name": "building_count",
                    "role": "metric",
                    "aggregate": "count",
                },
            ],
            "order_by": [{"output_name": "building_count", "direction": "desc"}],
        }
    )

    plan = build_compiled_ad_hoc_semantic_plan(
        semantic_ir=semantic_ir,
        source={"source_id": 13},
        semantic_version=semantic_layer["semantic_version"],
        semantic_layer=semantic_layer,
        max_rows=1000,
    )

    assert 'COUNT(*) AS "building_count"' in plan.compiled_statement
    assert "gisid" not in plan.compiled_statement


def test_ad_hoc_semantic_compiler_stabilizes_bounded_grouped_results() -> None:
    semantic_layer = _makani_semantic_layer()
    semantic_ir = AdHocSemanticQueryIR.model_validate(
        {
            "language": "en",
            "status": "query",
            "semantic_entity": "dmt_utility.udm_building",
            "projections": [
                {
                    "output_name": "primary_land_use",
                    "role": "dimension",
                    "field_ref": {
                        "semantic_entity": "dmt_utility.udm_building",
                        "semantic_field": "primaryuseengdesc",
                    },
                },
                {
                    "output_name": "building_count",
                    "role": "metric",
                    "aggregate": "count",
                },
            ],
        }
    )

    plan = build_compiled_ad_hoc_semantic_plan(
        semantic_ir=semantic_ir,
        source={"source_id": 13},
        semantic_version=semantic_layer["semantic_version"],
        semantic_layer=semantic_layer,
        max_rows=1000,
    )

    assert plan.compiler_default_ordering is True
    assert 'ORDER BY "primary_land_use" ASC' in plan.compiled_statement
    sort_node = next(
        node for node in plan.logical_plan.nodes if node.node_id == "sort_001"
    )
    assert sort_node.attributes["ordering_source"] == "compiler_default_bounded_aggregate"


def test_ad_hoc_semantic_compiler_rejects_join_key_for_entity_count() -> None:
    semantic_layer = _makani_semantic_layer()
    semantic_ir = AdHocSemanticQueryIR.model_validate(
        {
            "language": "en",
            "status": "query",
            "semantic_entity": "dmt_utility.udm_building",
            "projections": [
                {
                    "output_name": "building_count",
                    "role": "metric",
                    "aggregate": "count",
                    "field_ref": {
                        "semantic_entity": "dmt_utility.udm_building",
                        "semantic_field": "gisid",
                    },
                }
            ],
        }
    )

    with pytest.raises(
        SemanticIRCompilationError,
        match="semantic_ir_count_join_key_requires_row_count",
    ):
        build_compiled_ad_hoc_semantic_plan(
            semantic_ir=semantic_ir,
            source={"source_id": 13},
            semantic_version=semantic_layer["semantic_version"],
            semantic_layer=semantic_layer,
            max_rows=1000,
        )


def _pedestrian_crash_json_array_ir(*, value_key: str = "Nb_of_Accidents") -> AdHocSemanticQueryIR:
    return AdHocSemanticQueryIR.model_validate(
        {
            "language": "en",
            "status": "query",
            "semantic_entity": "dmt_liveability.fact_oi_indicators",
            "projections": [
                {
                    "output_name": "district_name",
                    "role": "dimension",
                    "field_ref": {
                        "semantic_entity": "dmt_liveability.dim_districts",
                        "semantic_field": "name_en",
                    },
                },
                {
                    "output_name": "pedestrian_crashes",
                    "role": "metric",
                    "aggregate": "sum",
                    "field_ref": None,
                    "derived_measure": None,
                    "json_array": {
                        "field_ref": {
                            "semantic_entity": "dmt_liveability.fact_oi_indicators",
                            "semantic_field": "data",
                        },
                        "value_key": value_key,
                    },
                },
            ],
            "filters": [
                {
                    "field_ref": {
                        "semantic_entity": "dmt_liveability.fact_oi_indicators",
                        "semantic_field": "indicator_type",
                    },
                    "operator": "eq",
                    "values": ["crash_pedestrian"],
                }
            ],
            "joins": [
                {
                    "left_field_ref": {
                        "semantic_entity": "dmt_liveability.fact_oi_indicators",
                        "semantic_field": "district_id",
                    },
                    "right_field_ref": {
                        "semantic_entity": "dmt_liveability.dim_districts",
                        "semantic_field": "district_id",
                    },
                    "kind": "equality",
                    "operator": "eq",
                }
            ],
            "order_by": [{"output_name": "pedestrian_crashes", "direction": "desc"}],
            "limit": 10,
        }
    )


def test_ad_hoc_semantic_compiler_compiles_governed_json_array_metric() -> None:
    semantic_layer = _liveability_published_json_semantic_layer()
    plan = build_compiled_ad_hoc_semantic_plan(
        semantic_ir=_pedestrian_crash_json_array_ir(),
        source={"source_id": 12, "database_name": "liveability_data_20260730"},
        semantic_version=semantic_layer["semantic_version"],
        semantic_layer=semantic_layer,
        max_rows=1000,
    )
    assert "jsonb_array_elements" in plan.compiled_statement
    assert "Nb_of_Accidents" in plan.compiled_statement
    # Each source row may contain multiple JSON objects.  The compiler must
    # aggregate those elements inside the correlated subquery before applying
    # the outer source-row aggregate; a scalar subquery would fail at runtime
    # with PostgreSQL's "more than one row returned" error.
    assert "COALESCE(SUM((gda_json_item_001 ->> 'Nb_of_Accidents')::double precision), 0)" in plan.compiled_statement
    assert "crash_pedestrian" not in plan.compiled_statement
    assert plan.parameter_bindings["gda_p_001"] == "crash_pedestrian"
    aggregate_node = next(node for node in plan.logical_plan.nodes if node.operator == "aggregate")
    assert aggregate_node.attributes["json_array_metrics"][0]["value_key"] == "Nb_of_Accidents"


def test_ad_hoc_semantic_compiler_rejects_whole_json_array_numeric_aggregate() -> None:
    semantic_layer = _liveability_published_json_semantic_layer()
    semantic_ir = AdHocSemanticQueryIR.model_validate(
        {
            "language": "en",
            "status": "query",
            "semantic_entity": "dmt_liveability.fact_oi_indicators",
            "projections": [
                {
                    "output_name": "pedestrian_crashes",
                    "role": "metric",
                    "aggregate": "sum",
                    "field_ref": {
                        "semantic_entity": "dmt_liveability.fact_oi_indicators",
                        "semantic_field": "data",
                    },
                }
            ],
            "filters": [
                {
                    "field_ref": {
                        "semantic_entity": "dmt_liveability.fact_oi_indicators",
                        "semantic_field": "indicator_type",
                    },
                    "operator": "eq",
                    "values": ["crash_pedestrian"],
                }
            ],
        }
    )

    with pytest.raises(
        SemanticIRCompilationError,
        match="semantic_json_array_projection_required",
    ):
        build_compiled_ad_hoc_semantic_plan(
            semantic_ir=semantic_ir,
            source={"source_id": 12, "database_name": "liveability_data_20260730"},
            semantic_version=semantic_layer["semantic_version"],
            semantic_layer=semantic_layer,
            max_rows=1000,
        )


def test_ad_hoc_semantic_compiler_rejects_undeclared_json_key() -> None:
    semantic_layer = _liveability_published_json_semantic_layer()
    with pytest.raises(SemanticIRCompilationError, match="semantic_json_array_contract_not_found_or_ambiguous"):
        build_compiled_ad_hoc_semantic_plan(
            semantic_ir=_pedestrian_crash_json_array_ir(value_key="not_a_real_key"),
            source={"source_id": 12, "database_name": "liveability_data_20260730"},
            semantic_version=semantic_layer["semantic_version"],
            semantic_layer=semantic_layer,
            max_rows=1000,
        )


def test_ad_hoc_semantic_compiler_requires_json_indicator_filter() -> None:
    semantic_layer = _liveability_published_json_semantic_layer()
    ir = _pedestrian_crash_json_array_ir()
    ir = ir.model_copy(update={"filters": ()})
    with pytest.raises(SemanticIRCompilationError, match="semantic_json_array_indicator_filter_required"):
        build_compiled_ad_hoc_semantic_plan(
            semantic_ir=ir,
            source={"source_id": 12, "database_name": "liveability_data_20260730"},
            semantic_version=semantic_layer["semantic_version"],
            semantic_layer=semantic_layer,
            max_rows=1000,
        )


def test_validate_semantic_sql_accepts_compiler_owned_json_array_sql() -> None:
    semantic_layer = _liveability_published_json_semantic_layer()
    plan = build_compiled_ad_hoc_semantic_plan(
        semantic_ir=_pedestrian_crash_json_array_ir(value_key="Total_Injuries"),
        source={"source_id": 12, "database_name": "liveability_data_20260730"},
        semantic_version=semantic_layer["semantic_version"],
        semantic_layer=semantic_layer,
        max_rows=1000,
    )
    evidence = validate_semantic_sql(
        plan.compiled_statement,
        list(plan.physical_plan.tables),
        semantic_layer,
        sql_params=plan.parameter_bindings,
    )
    assert "public.fact_oi_indicators.data" in evidence["columns"]


def test_validate_semantic_sql_rejects_json_array_without_type_filter() -> None:
    semantic_layer = _liveability_published_json_semantic_layer()
    sql = """SELECT (SELECT SUM((x ->> 'Nb_of_Accidents')::double precision)
FROM jsonb_array_elements(CASE WHEN jsonb_typeof(o.data)='array' THEN o.data ELSE '[]'::jsonb END) AS x)
FROM public.fact_oi_indicators AS o"""
    with pytest.raises(Exception, match="json_array_indicator_filter_rejected"):
        validate_semantic_sql(sql, ["public.fact_oi_indicators"], semantic_layer)


def test_validate_semantic_sql_rejects_undeclared_json_key() -> None:
    semantic_layer = _liveability_published_json_semantic_layer()
    sql = """SELECT (SELECT SUM((x ->> 'Secret_Key')::double precision)
FROM jsonb_array_elements(CASE WHEN jsonb_typeof(o.data)='array' THEN o.data ELSE '[]'::jsonb END) AS x)
FROM public.fact_oi_indicators AS o WHERE o.indicator_type = 'crash_pedestrian'"""
    with pytest.raises(Exception, match="json_accessor_key_rejected"):
        validate_semantic_sql(sql, ["public.fact_oi_indicators"], semantic_layer)


def test_ad_hoc_semantic_compiler_resolves_reviewed_asset_and_field_aliases() -> None:
    semantic_layer = _makani_semantic_layer()
    semantic_ir = AdHocSemanticQueryIR.model_validate(
        {
            "language": "en",
            "status": "query",
            "semantic_entity": "makani.dictionary.aa_hotels_cleanup_poly",
            "projections": [
                {
                    "output_name": "record_count",
                    "role": "metric",
                    "aggregate": "count",
                },
            ],
        }
    )

    plan = build_compiled_ad_hoc_semantic_plan(
        semantic_ir=semantic_ir,
        source={"source_id": 13},
        semantic_version=semantic_layer["semantic_version"],
        semantic_layer=semantic_layer,
        max_rows=1000,
    )

    assert 'FROM public.aa_hotels_cleanup_poly AS gda_source' in plan.compiled_statement


def test_numeric_question_literal_is_satisfied_by_unambiguous_reviewed_field_alias() -> None:
    """A reviewed AP50 alias carries the 50% meaning without a raw 50 predicate."""

    semantic_layer = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "docs/customer/abu_dhabi_liveability_site_validation"
            / "liveability_data_20260730_semantic_layer_v31_ap50_semantic_aliases_20260903.json"
        ).read_text(encoding="utf-8")
    )
    # Exercise the same logical alias path used by a provider while keeping
    # the source-published canonical field as the compiler authority.
    facility_binding = next(
        item
        for item in semantic_layer["table_bindings"]
        if item.get("physical_table") == "public.fact_facility_provision"
    )
    needed = next(
        item for item in facility_binding["fields"] if item.get("semantic_field") == "needed_ap50"
    )
    needed["aliases"] = [*(needed.get("aliases") or []), "target_need"]
    ir = AdHocSemanticQueryIR.model_validate(
        {
            "language": "en",
            "status": "query",
            "semantic_entity": facility_binding["semantic_entity"],
            "projections": [
                {
                    "output_name": "district_name",
                    "role": "dimension",
                    "field_ref": {
                        "semantic_entity": "dmt_liveability.dim_districts",
                        "semantic_field": "name_en",
                    },
                },
                {
                    "output_name": "needed",
                    "role": "attribute",
                    "field_ref": {
                        "semantic_entity": facility_binding["semantic_entity"],
                        "semantic_field": "target_need",
                    },
                },
            ],
            "filters": [
                {
                    "field_ref": {
                        "semantic_entity": facility_binding["semantic_entity"],
                        "semantic_field": "subcategory_name",
                    },
                    "operator": "eq",
                    "values": ["Library"],
                },
                {
                    "field_ref": {
                        "semantic_entity": facility_binding["semantic_entity"],
                        "semantic_field": "target_need",
                    },
                    "operator": "gt",
                    "values": [0],
                },
            ],
            "joins": [
                {
                    "left_field_ref": {
                        "semantic_entity": facility_binding["semantic_entity"],
                        "semantic_field": "district_id",
                    },
                    "right_field_ref": {
                        "semantic_entity": "dmt_liveability.dim_districts",
                        "semantic_field": "district_id",
                    },
                    "kind": "equality",
                    "operator": "eq",
                }
            ],
        }
    )
    plan = build_compiled_ad_hoc_semantic_plan(
        semantic_ir=ir,
        source={"source_id": 12, "database_name": "liveability_data_20260730"},
        semantic_version=semantic_layer["semantic_version"],
        semantic_layer=semantic_layer,
        max_rows=1000,
        question="Which districts still need libraries to reach the 50% target (needed>0)?",
    )
    assert '"needed_ap50"' in plan.compiled_statement


def test_ad_hoc_semantic_compiler_rejects_explicitly_inactive_binding() -> None:
    semantic_layer = _makani_semantic_layer()
    target = next(
        item
        for item in semantic_layer["table_bindings"]
        if item.get("physical_table") == "public.aa_hotels_cleanup_poly"
    )
    target["execution_eligible"] = False
    semantic_ir = AdHocSemanticQueryIR.model_validate(
        {
            "language": "en",
            "status": "query",
            "semantic_entity": "dmt_utility.aa_hotels_cleanup_poly",
            "projections": [
                {"output_name": "record_count", "role": "metric", "aggregate": "count"}
            ],
        }
    )

    with pytest.raises(
        SemanticIRCompilationError,
        match="semantic_entity_not_active_or_ambiguous",
    ):
        build_compiled_ad_hoc_semantic_plan(
            semantic_ir=semantic_ir,
            source={"source_id": 13},
            semantic_version=semantic_layer["semantic_version"],
            semantic_layer=semantic_layer,
            max_rows=1000,
        )


@pytest.mark.parametrize(
    ("semantic_entity", "field", "error"),
    [
        (
            "dmt_utility.unknown_building",
            "buildingnumberoffloors",
            "semantic_entity_not_active_or_ambiguous",
        ),
        (
            "dmt_utility.udm_building",
            "not_a_reviewed_field",
            "semantic_field_not_active_or_ambiguous",
        ),
        (
            "dmt_utility.udm_building",
            "shape",
            "semantic_geometry_projection_rejected",
        ),
    ],
)
def test_ad_hoc_semantic_compiler_rejects_unreviewed_and_geometry_bindings(
    semantic_entity: str,
    field: str,
    error: str,
) -> None:
    semantic_layer = _makani_semantic_layer()
    semantic_ir = _building_average_ir(field=field).model_copy(
        update={"semantic_entity": semantic_entity}
    )
    if semantic_entity != "dmt_utility.udm_building":
        semantic_ir = AdHocSemanticQueryIR.model_validate(
            {
                **semantic_ir.model_dump(mode="json"),
                "projections": [
                    {
                        **item,
                        "field_ref": {
                            **item["field_ref"],
                            "semantic_entity": semantic_entity,
                        },
                    }
                    for item in semantic_ir.model_dump(mode="json")["projections"]
                ],
                "filters": [
                    {
                        **item,
                        "field_ref": {
                            **item["field_ref"],
                            "semantic_entity": semantic_entity,
                        },
                    }
                    for item in semantic_ir.model_dump(mode="json")["filters"]
                ],
            }
        )

    with pytest.raises(SemanticIRCompilationError, match=error):
        build_compiled_ad_hoc_semantic_plan(
            semantic_ir=semantic_ir,
            source={"source_id": 13},
            semantic_version=semantic_layer["semantic_version"],
            semantic_layer=semantic_layer,
            max_rows=1000,
        )


def test_ad_hoc_semantic_ir_rejects_multiple_entities_before_compilation() -> None:
    payload = _building_average_ir().model_dump(mode="json")
    payload["filters"][0]["field_ref"]["semantic_entity"] = "dmt_utility.udm_district"

    with pytest.raises(ValueError, match="multiple entities require reviewed joins"):
        AdHocSemanticQueryIR.model_validate(payload)


def _parking_distance_ir(distance_metres: float) -> AdHocSemanticQueryIR:
    return AdHocSemanticQueryIR.model_validate(
        {
            "language": "en",
            "status": "query",
            "semantic_entity": "dmt_utility.udm_parkingmachine",
            "projections": [
                {
                    "output_name": "parking_meter_count",
                    "role": "metric",
                    "aggregate": "count",
                }
            ],
            "filters": [
                {
                    "field_ref": {
                        "semantic_entity": "dmt_utility.udm_district",
                        "semantic_field": "nameenglish",
                    },
                    "operator": "contains",
                    "values": ["Al Danah"],
                }
            ],
            "joins": [
                {
                    "left_field_ref": {
                        "semantic_entity": "dmt_utility.udm_parkingmachine",
                        "semantic_field": "shape",
                    },
                    "right_field_ref": {
                        "semantic_entity": "dmt_utility.udm_district",
                        "semantic_field": "shape",
                    },
                    "kind": "spatial",
                    "operator": "st_dwithin",
                    "distance_metres": distance_metres,
                }
            ],
        }
    )


def _makani_with_distance_relationship() -> dict:
    semantic_layer = _makani_semantic_layer()
    semantic_layer["relationships"].append(
        {
            "left": "public.udm_parkingmachine.shape",
            "right": "public.udm_district.shape",
            "kind": "spatial",
            "operator": "ST_DWithin",
            "cardinality": "many_to_many_distance_match",
            "review_status": "reviewed_runtime_validated",
            "max_distance_metres": 5000,
            "metric_srid": 32640,
        }
    )
    return semantic_layer


def test_ad_hoc_semantic_compiler_parameterizes_reviewed_spatial_distance() -> None:
    semantic_layer = _makani_with_distance_relationship()
    plan = build_compiled_ad_hoc_semantic_plan(
        semantic_ir=_parking_distance_ir(200),
        source={"source_id": 13, "database_name": "makani_sync_full"},
        semantic_version=semantic_layer["semantic_version"],
        semantic_layer=semantic_layer,
        max_rows=1000,
    )

    assert "ST_DWithin" in plan.compiled_statement
    assert "ST_Transform" in plan.compiled_statement
    assert ":gda_join_distance_001" in plan.compiled_statement
    assert "200" not in plan.compiled_statement
    assert plan.parameter_bindings["gda_join_distance_001"] == 200.0
    assert plan.parameter_bindings["gda_p_001"] == "%Al Danah%"


def test_ad_hoc_semantic_compiler_rejects_distance_above_relationship_maximum() -> None:
    semantic_layer = _makani_with_distance_relationship()
    with pytest.raises(
        SemanticIRCompilationError,
        match="semantic_ir_spatial_distance_exceeds_reviewed_maximum",
    ):
        build_compiled_ad_hoc_semantic_plan(
            semantic_ir=_parking_distance_ir(5001),
            source={"source_id": 13},
            semantic_version=semantic_layer["semantic_version"],
            semantic_layer=semantic_layer,
            max_rows=1000,
        )


def test_ad_hoc_semantic_compiler_applies_reviewed_topology_geometry_policy() -> None:
    semantic_layer = _makani_semantic_layer()
    semantic_ir = AdHocSemanticQueryIR.model_validate(
        {
            "language": "en",
            "status": "query",
            "semantic_entity": "dmt_utility.ud_masterplan_boundary",
            "projections": [
                {
                    "output_name": "majlis_count",
                    "role": "metric",
                    "aggregate": "count",
                    "field_ref": {
                        "semantic_entity": "dmt_utility.ud_masterplan_boundary",
                        "semantic_field": "objectid",
                    },
                }
            ],
            "joins": [
                {
                    "left_field_ref": {
                            "semantic_entity": "dmt_utility.ud_masterplan_boundary",
                            "semantic_field": "shape",
                        },
                        "right_field_ref": {
                            "semantic_entity": "dmt_utility.udm_majlis",
                            "semantic_field": "shape",
                    },
                    "kind": "spatial",
                    "operator": "st_covers",
                }
            ],
        }
    )

    plan = build_compiled_ad_hoc_semantic_plan(
        semantic_ir=semantic_ir,
        source={"source_id": 13, "database_name": "makani_sync_full"},
        semantic_version=semantic_layer["semantic_version"],
        semantic_layer=semantic_layer,
        max_rows=1000,
    )

    assert (
        "ST_Covers(gda_source.\"shape\", "
        "ST_Transform(ST_PointOnSurface(gda_join_001.\"shape\"), 32640))"
    ) in plan.compiled_statement


def _compile_liveability_ir(payload: dict, *, question: str | None = None):
    semantic_layer = _liveability_semantic_layer()
    return build_compiled_ad_hoc_semantic_plan(
        semantic_ir=AdHocSemanticQueryIR.model_validate(payload),
        source={"source_id": 12, "database_name": "liveability_data_20260730"},
        semantic_version=semantic_layer["semantic_version"],
        semantic_layer=semantic_layer,
        max_rows=1000,
        question=question,
    )


def test_ad_hoc_semantic_compiler_binds_explicit_reviewed_enum_list_to_in_filter() -> None:
    semantic_layer = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "docs/customer/abu_dhabi_liveability_site_validation"
            / "liveability_data_20260730_semantic_layer_v34_enum_domains_20260904.json"
        ).read_text(encoding="utf-8")
    )
    semantic_ir = AdHocSemanticQueryIR.model_validate(
        {
            "language": "en",
            "status": "query",
            "semantic_entity": "dmt_liveability.dim_districts",
            "projections": [
                {
                    "output_name": "classification",
                    "role": "dimension",
                    "field_ref": {
                        "semantic_entity": "dmt_liveability.dim_districts",
                        "semantic_field": "classification",
                    },
                },
                {"output_name": "district_count", "role": "metric", "aggregate": "count"},
            ],
        }
    )
    plan = build_compiled_ad_hoc_semantic_plan(
        semantic_ir=semantic_ir,
        source={"source_id": 12, "database_name": "liveability_data_20260730"},
        semantic_version=semantic_layer["semantic_version"],
        semantic_layer=semantic_layer,
        max_rows=1000,
        question="Show Urban and Rural districts.",
    )
    assert plan.compiler_semantic_filter_corrections == (
        "semantic_ir_added_explicit_domain_filter:dmt_liveability.dim_districts.classification",
    )
    assert set(plan.parameter_bindings.values()) == {"urban", "rural"}
    assert 'gda_source."classification" IN (' in plan.compiled_statement


def test_ad_hoc_semantic_compiler_does_not_add_enum_filter_for_single_category_reference() -> None:
    semantic_layer = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "docs/customer/abu_dhabi_liveability_site_validation"
            / "liveability_data_20260730_semantic_layer_v34_enum_domains_20260904.json"
        ).read_text(encoding="utf-8")
    )
    semantic_ir = AdHocSemanticQueryIR.model_validate(
        {
            "language": "en",
            "status": "query",
            "semantic_entity": "dmt_liveability.dim_districts",
            "projections": [
                {
                    "output_name": "classification",
                    "role": "dimension",
                    "field_ref": {
                        "semantic_entity": "dmt_liveability.dim_districts",
                        "semantic_field": "classification",
                    },
                },
                {"output_name": "district_count", "role": "metric", "aggregate": "count"},
            ],
        }
    )
    plan = build_compiled_ad_hoc_semantic_plan(
        semantic_ir=semantic_ir,
        source={"source_id": 12, "database_name": "liveability_data_20260730"},
        semantic_version=semantic_layer["semantic_version"],
        semantic_layer=semantic_layer,
        max_rows=1000,
        question="Show the district classification distribution.",
    )
    assert plan.compiler_semantic_filter_corrections == ()
    assert " WHERE " not in plan.compiled_statement


def test_ad_hoc_semantic_compiler_compiles_reviewed_district_score_join() -> None:
    plan = _compile_liveability_ir(
        {
            "language": "ar",
            "status": "query",
            "semantic_entity": "dmt_liveability.fact_district_scores",
            "projections": [
                {
                    "output_name": "district_name",
                    "role": "dimension",
                    "field_ref": {
                        "semantic_entity": "dmt_liveability.dim_districts",
                        "semantic_field": "name_en",
                    },
                },
                {
                    "output_name": "average_overall_score",
                    "role": "metric",
                    "aggregate": "avg",
                    "field_ref": {
                        "semantic_entity": "dmt_liveability.fact_district_scores",
                        "semantic_field": "overall_score",
                    },
                },
            ],
            "joins": [
                {
                    "left_field_ref": {
                        "semantic_entity": "dmt_liveability.fact_district_scores",
                        "semantic_field": "district_id",
                    },
                    "right_field_ref": {
                        "semantic_entity": "dmt_liveability.dim_districts",
                        "semantic_field": "district_id",
                    },
                    "kind": "equality",
                    "operator": "eq",
                }
            ],
            "order_by": [
                {"output_name": "average_overall_score", "direction": "desc"}
            ],
        }
    )

    assert "FROM public.fact_district_scores AS gda_source" in plan.compiled_statement
    assert "JOIN public.dim_districts AS gda_join_001 ON" in plan.compiled_statement
    assert 'gda_source."district_id" = gda_join_001."district_id"' in plan.compiled_statement
    assert 'AVG(gda_source."overall_score") AS "average_overall_score"' in plan.compiled_statement
    assert plan.physical_plan.tables == (
        "public.dim_districts",
        "public.fact_district_scores",
    )
    assert "join" in [node.operator for node in plan.logical_plan.nodes]


def test_ad_hoc_semantic_compiler_compiles_reviewed_facility_district_count() -> None:
    plan = _compile_liveability_ir(
        {
            "language": "en",
            "status": "query",
            "semantic_entity": "dmt_liveability.dim_facilities",
            "projections": [
                {
                    "output_name": "district_name",
                    "role": "dimension",
                    "field_ref": {
                        "semantic_entity": "dmt_liveability.dim_districts",
                        "semantic_field": "name_en",
                    },
                },
                {
                    "output_name": "facility_type",
                    "role": "dimension",
                    "field_ref": {
                        "semantic_entity": "dmt_liveability.dim_facilities",
                        "semantic_field": "facility_type",
                    },
                },
                {
                    "output_name": "facility_count",
                    "role": "metric",
                    "aggregate": "count",
                },
            ],
            "joins": [
                {
                    "left_field_ref": {
                        "semantic_entity": "dmt_liveability.dim_facilities",
                        "semantic_field": "district_id",
                    },
                    "right_field_ref": {
                        "semantic_entity": "dmt_liveability.dim_districts",
                        "semantic_field": "district_id",
                    },
                    "kind": "equality",
                    "operator": "eq",
                }
            ],
            "order_by": [
                {"output_name": "facility_count", "direction": "desc"}
            ],
        }
    )

    assert 'COUNT(*) AS "facility_count"' in plan.compiled_statement
    assert 'GROUP BY gda_join_001."name_en", gda_source."facility_type"' in plan.compiled_statement


def test_ad_hoc_semantic_compiler_preserves_detail_rows_with_requested_total_count() -> None:
    """A list-plus-count request must not collapse into a count-only group."""

    plan = _compile_liveability_ir(
        {
            "language": "en",
            "status": "query",
            "semantic_entity": "dmt_liveability.fact_district_scores",
            "projections": [
                {
                    "output_name": "district_name",
                    "role": "dimension",
                    "field_ref": {
                        "semantic_entity": "dmt_liveability.dim_districts",
                        "semantic_field": "name_en",
                    },
                },
                {
                    "output_name": "overall_score",
                    "role": "attribute",
                    "field_ref": {
                        "semantic_entity": "dmt_liveability.fact_district_scores",
                        "semantic_field": "overall_score",
                    },
                },
            ],
            "include_result_count": True,
            "result_count_alias": "district_count",
            "joins": [
                {
                    "left_field_ref": {
                        "semantic_entity": "dmt_liveability.fact_district_scores",
                        "semantic_field": "district_id",
                    },
                    "right_field_ref": {
                        "semantic_entity": "dmt_liveability.dim_districts",
                        "semantic_field": "district_id",
                    },
                    "kind": "equality",
                    "operator": "eq",
                }
            ],
            "filters": [
                {
                    "field_ref": {
                        "semantic_entity": "dmt_liveability.fact_district_scores",
                        "semantic_field": "overall_score",
                    },
                    "operator": "gt",
                    "values": [90],
                }
            ],
        },
        question=(
            "Which districts have a quantitative liveability score above 90% "
            "and how many are there?"
        ),
    )

    assert 'gda_source."overall_score" AS "overall_score"' in plan.compiled_statement
    assert 'COUNT(*) OVER () AS "district_count"' in plan.compiled_statement
    assert "GROUP BY" not in plan.compiled_statement


def test_ad_hoc_semantic_compiler_rejects_list_count_without_count_companion() -> None:
    semantic_ir = AdHocSemanticQueryIR.model_validate(
        {
            "language": "en",
            "status": "query",
            "semantic_entity": "dmt_liveability.fact_district_scores",
            "projections": [
                {
                    "output_name": "district_name",
                    "role": "dimension",
                    "field_ref": {
                        "semantic_entity": "dmt_liveability.dim_districts",
                        "semantic_field": "name_en",
                    },
                },
                {
                    "output_name": "overall_score",
                    "role": "attribute",
                    "field_ref": {
                        "semantic_entity": "dmt_liveability.fact_district_scores",
                        "semantic_field": "overall_score",
                    },
                },
            ],
            "joins": [
                {
                    "left_field_ref": {
                        "semantic_entity": "dmt_liveability.fact_district_scores",
                        "semantic_field": "district_id",
                    },
                    "right_field_ref": {
                        "semantic_entity": "dmt_liveability.dim_districts",
                        "semantic_field": "district_id",
                    },
                    "kind": "equality",
                    "operator": "eq",
                }
            ],
        }
    )
    with pytest.raises(SemanticIRCompilationError, match="semantic_ir_result_count_required"):
        build_compiled_ad_hoc_semantic_plan(
            semantic_ir=semantic_ir,
            source={"source_id": 12, "database_name": "liveability_data_20260730"},
            semantic_version="test",
            semantic_layer=_liveability_semantic_layer(),
            max_rows=1000,
            question="Which districts are listed and how many are there?",
        )


def test_ad_hoc_semantic_compiler_does_not_treat_metric_count_as_total_count_request():
    """A phrase such as 'highest citywide count' names a metric, not a row total."""

    semantic_ir = AdHocSemanticQueryIR.model_validate(
        {
            "language": "en",
            "status": "query",
            "semantic_entity": "dmt_liveability.fact_facility_provision",
            "projections": [
                {
                    "output_name": "facility_type",
                    "role": "dimension",
                    "field_ref": {
                        "semantic_entity": "dmt_liveability.fact_facility_provision",
                        "semantic_field": "category_name",
                    },
                },
                {
                    "output_name": "facility_count",
                    "role": "metric",
                    "aggregate": "count",
                },
            ],
        }
    )
    plan = build_compiled_ad_hoc_semantic_plan(
        semantic_ir=semantic_ir,
        source={"source_id": 12, "database_name": "liveability_data_20260730"},
        semantic_version=_liveability_semantic_layer()["semantic_version"],
        semantic_layer=_liveability_semantic_layer(),
        max_rows=1000,
        question=(
            "Which facility type has the highest citywide count and which has "
            "the lowest count among facility types with non-zero demand?"
        ),
    )
    assert 'COUNT(*) AS "facility_count"' in plan.compiled_statement


def test_ad_hoc_semantic_compiler_appends_dimension_tiebreakers_to_metric_order() -> None:
    """A bounded Top-N grouped metric must be deterministic under ties."""

    semantic_layer = _liveability_v24_semantic_layer()
    plan = build_compiled_ad_hoc_semantic_plan(
        semantic_ir=AdHocSemanticQueryIR.model_validate({
            "language": "en",
            "status": "query",
            "semantic_entity": "dmt_liveability.fact_facility_provision",
            "projections": [
                {
                    "output_name": "district_name",
                    "role": "dimension",
                    "field_ref": {
                        "semantic_entity": "dmt_liveability.dim_districts",
                        "semantic_field": "name_en",
                    },
                },
                {
                    "output_name": "existing_count",
                    "role": "metric",
                    "aggregate": "sum",
                    "field_ref": {
                        "semantic_entity": "dmt_liveability.fact_facility_provision",
                        "semantic_field": "existing_count",
                    },
                },
            ],
            "joins": [
                {
                    "left_field_ref": {
                        "semantic_entity": "dmt_liveability.fact_facility_provision",
                        "semantic_field": "district_id",
                    },
                    "right_field_ref": {
                        "semantic_entity": "dmt_liveability.dim_districts",
                        "semantic_field": "district_id",
                    },
                    "kind": "equality",
                    "operator": "eq",
                }
            ],
            "order_by": [
                {"output_name": "existing_count", "direction": "desc"}
            ],
            "limit": 10,
        }),
        source={"source_id": 12, "database_name": "liveability_data_20260730"},
        semantic_version=semantic_layer["semantic_version"],
        semantic_layer=semantic_layer,
        max_rows=1000,
    )

    assert plan.compiler_added_ordering_tiebreakers == (
        "dmt_liveability.dim_districts.district_id",
    )
    assert (
        'ORDER BY "existing_count" DESC NULLS LAST, gda_join_001."district_id" ASC'
        in plan.compiled_statement
    )
    sort_node = next(
        node for node in plan.logical_plan.nodes if node.node_id == "sort_001"
    )
    assert sort_node.attributes["ordering_source"] == (
        "semantic_ir_with_dimension_tiebreakers"
    )


def test_ad_hoc_semantic_compiler_stabilizes_detail_top_n_with_projected_entity_key() -> None:
    """A detail Top-N must not pick an arbitrary subset when values tie."""

    semantic_layer = _liveability_v24_semantic_layer()
    plan = build_compiled_ad_hoc_semantic_plan(
        semantic_ir=AdHocSemanticQueryIR.model_validate({
            "language": "en",
            "status": "query",
            "semantic_entity": "dmt_liveability.fact_ic_scores",
            "projections": [
                {
                    "output_name": "district_name",
                    "role": "attribute",
                    "field_ref": {
                        "semantic_entity": "dmt_liveability.dim_districts",
                        "semantic_field": "name_en",
                    },
                },
                {
                    "output_name": "municipality",
                    "role": "attribute",
                    "field_ref": {
                        "semantic_entity": "dmt_liveability.dim_districts",
                        "semantic_field": "municipality",
                    },
                },
                {
                    "output_name": "existing_cycle_ic_completion_rate",
                    "role": "attribute",
                    "field_ref": {
                        "semantic_entity": "dmt_liveability.fact_ic_scores",
                        "semantic_field": "cycle_perc_existing",
                    },
                },
            ],
            "filters": [
                {
                    "field_ref": {
                        "semantic_entity": "dmt_liveability.dim_districts",
                        "semantic_field": "is_activated",
                    },
                    "operator": "eq",
                    "values": [True],
                },
                {
                    "field_ref": {
                        "semantic_entity": "dmt_liveability.dim_calc_versions",
                        "semantic_field": "current_flag",
                    },
                    "operator": "eq",
                    "values": [True],
                },
            ],
            "joins": [
                {
                    "left_field_ref": {
                        "semantic_entity": "dmt_liveability.fact_ic_scores",
                        "semantic_field": "district_id",
                    },
                    "right_field_ref": {
                        "semantic_entity": "dmt_liveability.dim_districts",
                        "semantic_field": "district_id",
                    },
                    "kind": "equality",
                    "operator": "eq",
                },
                {
                    "left_field_ref": {
                        "semantic_entity": "dmt_liveability.fact_ic_scores",
                        "semantic_field": "calc_version_id",
                    },
                    "right_field_ref": {
                        "semantic_entity": "dmt_liveability.dim_calc_versions",
                        "semantic_field": "calc_version_id",
                    },
                    "kind": "equality",
                    "operator": "eq",
                },
            ],
            "order_by": [
                {
                    "output_name": "existing_cycle_ic_completion_rate",
                    "direction": "asc",
                }
            ],
            "limit": 10,
        }),
        source={"source_id": 12, "database_name": "liveability_data_20260730"},
        semantic_version=semantic_layer["semantic_version"],
        semantic_layer=semantic_layer,
        max_rows=1000,
    )

    assert plan.compiler_added_ordering_tiebreakers == (
        "dmt_liveability.dim_districts.district_id",
    )
    assert (
        'ORDER BY "existing_cycle_ic_completion_rate" ASC, '
        'gda_join_001."district_id" ASC'
        in plan.compiled_statement
    )
    assert "public.dim_districts.district_id" in plan.physical_plan.columns
    sort_node = next(
        node for node in plan.logical_plan.nodes if node.node_id == "sort_001"
    )
    assert sort_node.attributes["ordering_source"] == (
        "semantic_ir_with_detail_tiebreakers"
    )


def test_ad_hoc_semantic_compiler_preserves_primary_key_grain_for_label_grouping() -> None:
    semantic_layer = _liveability_semantic_layer()
    district_binding = next(
        item
        for item in semantic_layer["table_bindings"]
        if item["semantic_entity"] == "dmt_liveability.dim_districts"
    )
    district_binding["primary_key"] = ["district_id"]
    semantic_ir = AdHocSemanticQueryIR.model_validate(
        {
            "language": "en",
            "status": "query",
            "semantic_entity": "dmt_liveability.fact_district_scores",
            "projections": [
                {
                    "output_name": "district_name",
                    "role": "dimension",
                    "field_ref": {
                        "semantic_entity": "dmt_liveability.dim_districts",
                        "semantic_field": "name_en",
                    },
                },
                {
                    "output_name": "average_score",
                    "role": "metric",
                    "aggregate": "avg",
                    "field_ref": {
                        "semantic_entity": "dmt_liveability.fact_district_scores",
                        "semantic_field": "overall_score",
                    },
                },
            ],
            "joins": [
                {
                    "left_field_ref": {
                        "semantic_entity": "dmt_liveability.fact_district_scores",
                        "semantic_field": "district_id",
                    },
                    "right_field_ref": {
                        "semantic_entity": "dmt_liveability.dim_districts",
                        "semantic_field": "district_id",
                    },
                    "kind": "equality",
                    "operator": "eq",
                }
            ],
        }
    )

    plan = build_compiled_ad_hoc_semantic_plan(
        semantic_ir=semantic_ir,
        source={"source_id": 12, "database_name": "liveability_data_20260730"},
        semantic_version=semantic_layer["semantic_version"],
        semantic_layer=semantic_layer,
        max_rows=1000,
    )

    assert (
        'GROUP BY gda_join_001."name_en", gda_join_001."district_id"'
        in plan.compiled_statement
    )


def test_ad_hoc_semantic_compiler_compiles_median_as_ordered_set_aggregate() -> None:
    plan = _compile_liveability_ir(
        {
            "language": "en",
            "status": "query",
            "semantic_entity": "dmt_liveability.fact_district_scores",
            "projections": [
                {
                    "output_name": "median_score",
                    "role": "metric",
                    "aggregate": "median",
                    "field_ref": {
                        "semantic_entity": "dmt_liveability.fact_district_scores",
                        "semantic_field": "overall_score",
                    },
                }
            ],
        }
    )
    assert (
        'PERCENTILE_CONT(0.5) WITHIN GROUP '
        '(ORDER BY gda_source."overall_score") AS "median_score"'
    ) in plan.compiled_statement


def test_ad_hoc_semantic_compiler_compiles_reviewed_numeric_addition_expression() -> None:
    # Use the current reviewed layer for this arithmetic contract.  The
    # historical v3 fixture intentionally contains metadata-only bindings for
    # some tables (including fact_ic_scores), so it is not an execution fixture.
    semantic_layer = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "docs/customer/abu_dhabi_liveability_site_validation"
            / "liveability_data_20260730_semantic_layer_v21_answerability_data_quality_20260902.json"
        ).read_text(encoding="utf-8")
    )
    plan = build_compiled_ad_hoc_semantic_plan(
        semantic_ir=AdHocSemanticQueryIR.model_validate(
            {
            "language": "en",
            "status": "query",
            "semantic_entity": "dmt_liveability.fact_ic_scores",
            "projections": [
                {
                    "output_name": "existing_completion",
                    "role": "attribute",
                    "field_ref": {
                        "semantic_entity": "dmt_liveability.fact_ic_scores",
                        "semantic_field": "streetlight_perc_existing",
                    },
                },
                {
                    "output_name": "post_pipeline_completion",
                    "role": "attribute",
                    "derived_expression": {
                        "operator": "add",
                        "operands": [
                            {
                                "semantic_entity": "dmt_liveability.fact_ic_scores",
                                "semantic_field": "streetlight_perc_existing",
                            },
                            {
                                "semantic_entity": "dmt_liveability.fact_ic_scores",
                                "semantic_field": "streetlight_perc_pipeline",
                            },
                        ],
                    },
                },
            ],
            }
        ),
        source={"source_id": 12, "database_name": "liveability_data_20260730"},
        semantic_version=semantic_layer["semantic_version"],
        semantic_layer=semantic_layer,
        max_rows=1000,
    )
    assert (
        '(gda_source."streetlight_perc_existing" + '
        'gda_source."streetlight_perc_pipeline") AS "post_pipeline_completion"'
    ) in plan.compiled_statement


def test_ad_hoc_semantic_compiler_rejects_spatial_question_without_spatial_join() -> None:
    semantic_layer = _liveability_semantic_layer()
    semantic_ir = AdHocSemanticQueryIR.model_validate(
        {
            "language": "en",
            "status": "query",
            "semantic_entity": "dmt_liveability.dim_facilities",
            "projections": [
                {
                    "output_name": "facility_type",
                    "role": "dimension",
                    "field_ref": {
                        "semantic_entity": "dmt_liveability.dim_facilities",
                        "semantic_field": "facility_type",
                    },
                },
                {
                    "output_name": "facility_count",
                    "role": "metric",
                    "aggregate": "count",
                }
            ],
        }
    )
    with pytest.raises(
        SemanticIRCompilationError,
        match="semantic_ir_spatial_intent_requires_spatial_join",
    ):
        build_compiled_ad_hoc_semantic_plan(
            semantic_ir=semantic_ir,
            source={"source_id": 12, "database_name": "liveability_data_20260730"},
            semantic_version=semantic_layer["semantic_version"],
            semantic_layer=semantic_layer,
            max_rows=1000,
            expected_spatial_intent=SpatialIntent.WITHIN,
        )


def test_ad_hoc_semantic_compiler_derives_area_in_square_kilometres() -> None:
    plan = _compile_liveability_ir(
        {
            "language": "zh",
            "status": "query",
            "semantic_entity": "dmt_liveability.fact_isochrones",
            "projections": [
                {
                    "output_name": "facility_type",
                    "role": "dimension",
                    "field_ref": {
                        "semantic_entity": "dmt_liveability.fact_isochrones",
                        "semantic_field": "facility_type",
                    },
                },
                {
                    "output_name": "travel_mode",
                    "role": "dimension",
                    "field_ref": {
                        "semantic_entity": "dmt_liveability.fact_isochrones",
                        "semantic_field": "mode",
                    },
                },
                {
                    "output_name": "average_area_km2",
                    "role": "metric",
                    "aggregate": "avg",
                    "derived_measure": "area_square_kilometres",
                    "field_ref": {
                        "semantic_entity": "dmt_liveability.fact_isochrones",
                        "semantic_field": "geom",
                    },
                },
            ],
        }
    )

    assert (
        'AVG(ST_Area(gda_source."geom"::geography)::numeric / 1000000.0) '
        'AS "average_area_km2"'
    ) in plan.compiled_statement
    assert "public.fact_isochrones.geom" in plan.physical_plan.columns


def test_ad_hoc_semantic_compiler_rejects_unreviewed_logical_join() -> None:
    payload = {
        "language": "en",
        "status": "query",
        "semantic_entity": "dmt_liveability.fact_district_scores",
        "projections": [
            {
                "output_name": "average_overall_score",
                "role": "metric",
                "aggregate": "avg",
                "field_ref": {
                    "semantic_entity": "dmt_liveability.fact_district_scores",
                    "semantic_field": "overall_score",
                },
            }
        ],
        "joins": [
            {
                "left_field_ref": {
                    "semantic_entity": "dmt_liveability.fact_district_scores",
                    "semantic_field": "overall_score",
                },
                "right_field_ref": {
                    "semantic_entity": "dmt_liveability.dim_districts",
                    "semantic_field": "district_id",
                },
                "kind": "equality",
                "operator": "eq",
            }
        ],
    }

    with pytest.raises(SemanticIRCompilationError, match="semantic_ir_join_not_reviewed"):
        _compile_liveability_ir(payload)


def _plan(
    sql: str,
    *,
    tables: list[str],
    columns: list[str],
    contract: dict | None = None,
):
    return build_shadow_semantic_plan_evidence(
        question="Count facilities by the requested business dimensions.",
        language="en",
        sql=sql,
        source=SOURCE,
        semantic_version="abu-dhabi-liveability-v3",
        metric_contract_version="abu-dhabi-metric-contract-v4",
        semantic_evidence={"tables": tables, "columns": columns},
        metric_contract_evidence=contract,
        max_rows=1000,
    )


def test_governed_aggregate_builds_deterministic_non_authoritative_plan() -> None:
    sql = (
        "SELECT f.facility_type, COUNT(*) AS facility_count "
        "FROM public.dim_facilities AS f "
        "GROUP BY f.facility_type "
        "ORDER BY facility_count DESC LIMIT 10"
    )
    kwargs = {
        "tables": ["public.dim_facilities"],
        "columns": ["public.dim_facilities.facility_type"],
    }

    first = _plan(sql, **kwargs)
    second = _plan(sql, **kwargs)

    assert first.status == "planned"
    assert first.execution_authority is False
    assert first.semantic_ir is not None
    assert first.semantic_ir.route is SemanticQueryRoute.GOVERNED_SQL_AST
    assert first.semantic_ir.operation == "aggregate"
    assert first.semantic_ir.result_limit == 10
    assert first.semantic_ir.limit_enforcement == "sql"
    assert first.validation is not None and first.validation.valid is True
    assert first.logical_plan is not None
    assert [node.operator for node in first.logical_plan.nodes] == [
        "scan",
        "aggregate",
        "project",
        "sort",
        "limit",
    ]
    assert first.fingerprints == second.fingerprints
    assert "Count facilities" not in first.model_dump_json()


def test_reviewed_spatial_contract_records_postgis_join() -> None:
    plan = _plan(
        "SELECT d.district_name, COUNT(*) AS building_count "
        "FROM public.udm_district AS d "
        "JOIN public.udm_building AS b ON ST_Covers(d.geom, b.geom) "
        "GROUP BY d.district_name",
        tables=["public.udm_building", "public.udm_district"],
        columns=[
            "public.udm_building.geom",
            "public.udm_district.district_name",
            "public.udm_district.geom",
        ],
        contract={"contract_id": "MAKANI_BUILDING_COUNT_BY_DISTRICT_SPATIAL_V4"},
    )

    assert plan.status == "planned"
    assert plan.semantic_ir is not None
    assert plan.semantic_ir.route is SemanticQueryRoute.REVIEWED_METRIC_CONTRACT
    assert plan.semantic_ir.metric_contract_id == (
        "MAKANI_BUILDING_COUNT_BY_DISTRICT_SPATIAL_V4"
    )
    assert len(plan.semantic_ir.joins) == 1
    assert plan.semantic_ir.joins[0].kind is JoinKind.SPATIAL
    assert plan.semantic_ir.joins[0].operator == "st_covers"
    assert plan.physical_plan is not None
    assert plan.physical_plan.spatial_operators == ("st_covers",)
    assert plan.physical_plan.compilation_mode == "reviewed_contract_shadow"


def test_reviewed_metric_contract_builds_authoritative_compiler_plan() -> None:
    sql = (
        "SELECT f.facility_type, COUNT(*) AS facility_count "
        "FROM public.dim_facilities AS f "
        "GROUP BY f.facility_type ORDER BY facility_count DESC LIMIT 10"
    )
    plan = build_certified_metric_contract_plan(
        question="Count facilities by facility type.",
        language="en",
        canonical_sql=sql,
        source=SOURCE,
        semantic_version="abu-dhabi-liveability-v4-reviewed-assets",
        metric_contract_version="abu-dhabi-liveability-metric-v4",
        semantic_evidence={
            "tables": ["public.dim_facilities"],
            "columns": ["public.dim_facilities.facility_type"],
        },
        metric_contract_evidence={
            "contract_id": "LIVEABILITY_FACILITY_COUNT_BY_TYPE_V4"
        },
        max_rows=1000,
    )

    assert plan.status == "planned"
    assert plan.execution_authority is True
    assert plan.authority == "reviewed_metric_contract_template_compiler"
    assert plan.semantic_ir.route is SemanticQueryRoute.REVIEWED_METRIC_CONTRACT
    assert plan.validation.valid is True
    assert plan.physical_plan.compilation_mode == "reviewed_contract_compiler"
    assert plan.compiled_statement == sql
    assert plan.fingerprints["compiled_statement_sha256"] == plan.physical_plan.statement_sha256


def test_unresolved_join_lineage_falls_back_without_affecting_execution() -> None:
    plan = _plan(
        "SELECT COUNT(*) FROM public.left_table AS l "
        "JOIN public.right_table AS r ON l.unknown_key = r.unknown_key",
        tables=["public.left_table", "public.right_table"],
        columns=[],
    )

    assert plan.status == "legacy_fallback"
    assert plan.execution_authority is False
    assert plan.semantic_ir is None
    assert plan.fallback_reason == (
        "shadow_plan_unavailable:shadow_ir_join_fields_unresolved"
    )


def test_source_executor_limit_is_explicit_when_sql_has_no_limit() -> None:
    plan = _plan(
        "SELECT f.stage FROM public.dim_facilities AS f",
        tables=["public.dim_facilities"],
        columns=["public.dim_facilities.stage"],
    )

    assert plan.status == "planned"
    assert plan.semantic_ir is not None
    assert plan.semantic_ir.result_limit == 1000
    assert plan.semantic_ir.limit_enforcement == "source_executor"
    assert plan.logical_plan is not None
    assert plan.logical_plan.nodes[-1].attributes == {
        "row_limit": 1000,
        "enforcement": "source_executor",
    }


def test_cte_output_lineage_supports_ratio_of_two_aggregates() -> None:
    plan = _plan(
        "WITH left_totals AS ("
        "SELECT area_id, COUNT(DISTINCT item_id) AS item_count "
        "FROM public.items GROUP BY area_id"
        "), right_totals AS ("
        "SELECT area_id, SUM(resident_count) AS resident_count "
        "FROM public.residents GROUP BY area_id"
        ") "
        "SELECT a.area_name, l.item_count, r.resident_count, "
        "l.item_count * 10000.0 / NULLIF(r.resident_count, 0) AS items_per_10000 "
        "FROM public.areas AS a "
        "JOIN left_totals AS l ON l.area_id = a.area_id "
        "JOIN right_totals AS r ON r.area_id = a.area_id "
        "ORDER BY a.area_name LIMIT 1000",
        tables=["public.areas", "public.items", "public.residents"],
        columns=[
            "public.areas.area_id",
            "public.areas.area_name",
            "public.items.area_id",
            "public.items.item_id",
            "public.residents.area_id",
            "public.residents.resident_count",
        ],
    )

    assert plan.status == "planned"
    assert plan.semantic_ir is not None
    assert len(plan.semantic_ir.joins) == 2
    assert all(join.kind is JoinKind.EQUALITY for join in plan.semantic_ir.joins)
    ratio = next(
        item for item in plan.semantic_ir.projections if item.output_name == "items_per_10000"
    )
    assert {(field.table, field.field) for field in ratio.source_fields} == {
        ("public.items", "item_id"),
        ("public.residents", "resident_count"),
    }


def _federated_source_report(
    *,
    source_id: int,
    source_name: str,
    database_name: str,
    semantic_version: str,
    metric_contract_id: str,
) -> dict:
    return {
        "status": "ok",
        "semantic_version": semantic_version,
        "metric_contract_version": "abu-dhabi-metric-contract-v4",
        "source": {
            "source_id": source_id,
            "source_name": source_name,
            "database_name": database_name,
        },
        "query": {
            "semantic_plan": {
                "status": "planned",
                "semantic_ir": {
                    "route": "reviewed_metric_contract",
                    "metric_contract_id": metric_contract_id,
                },
                "fingerprints": {"semantic_ir_sha256": f"{source_id:064x}"},
            }
        },
    }


def test_federated_plan_references_contracts_without_cross_source_sql() -> None:
    subplans = [
        {
            "source": "liveability",
            "metric_contract_id": "LIVEABILITY_FACILITY_COUNT_BY_STAGE_TYPE_V4",
            "report": _federated_source_report(
                source_id=12,
                source_name="abu-dhabi-liveability-dev-v3",
                database_name="liveability_data_20260730",
                semantic_version="abu-dhabi-liveability-v3",
                metric_contract_id="LIVEABILITY_FACILITY_COUNT_BY_STAGE_TYPE_V4",
            ),
        },
        {
            "source": "makani",
            "metric_contract_id": "MAKANI_SUBSTATION_COUNT_BY_STATUS_TYPE_V4",
            "report": _federated_source_report(
                source_id=13,
                source_name="abu-dhabi-makani-dev-v3",
                database_name="makani_sync_full",
                semantic_version="abu-dhabi-makani-v3",
                metric_contract_id="MAKANI_SUBSTATION_COUNT_BY_STATUS_TYPE_V4",
            ),
        },
    ]

    first = build_federated_semantic_plan_evidence(
        question="Compare the two governed business summaries.",
        language="en",
        semantic_version="abu-dhabi-liveability-makani-federated-v4",
        federated_contract_id="facilities_and_substations_v4",
        subplans=subplans,
    )
    second = build_federated_semantic_plan_evidence(
        question="Compare the two governed business summaries.",
        language="en",
        semantic_version="abu-dhabi-liveability-makani-federated-v4",
        federated_contract_id="facilities_and_substations_v4",
        subplans=subplans,
    )

    assert first.status == "planned"
    assert first.execution_authority is False
    assert first.validation is not None and first.validation.valid is True
    assert first.semantic_ir is not None
    assert first.semantic_ir.merge_strategy is FederatedMergeStrategy.INDEPENDENT_SECTIONS
    assert first.semantic_ir.cross_database_sql is False
    assert first.semantic_ir.cross_source_join is False
    assert [item.source_id for item in first.semantic_ir.subplans] == [12, 13]
    assert first.logical_plan is not None
    assert [node.operator for node in first.logical_plan.nodes] == [
        "metric_contract_subplan",
        "metric_contract_subplan",
        "independent_sections_merge",
    ]
    assert first.fingerprints == second.fingerprints
    assert "Compare the two" not in first.model_dump_json()


def test_federated_plan_falls_back_on_contract_drift() -> None:
    report = _federated_source_report(
        source_id=12,
        source_name="liveability",
        database_name="liveability_data_20260730",
        semantic_version="abu-dhabi-liveability-v3",
        metric_contract_id="ACTUAL_CONTRACT",
    )

    plan = build_federated_semantic_plan_evidence(
        question="A governed summary",
        language="en",
        semantic_version="federated-v4",
        federated_contract_id="bundle-v4",
        subplans=[
            {
                "source": "liveability",
                "metric_contract_id": "DIFFERENT_CONTRACT",
                "report": report,
            },
            {
                "source": "makani",
                "metric_contract_id": "ACTUAL_CONTRACT",
                "report": report,
            },
        ],
    )

    assert plan.status == "legacy_fallback"
    assert plan.fallback_reason == (
        "federated_plan_unavailable:federated_source_metric_contract_drift"
    )


def test_band_summary_compiler_is_restricted_and_parameterized() -> None:
    semantic_layer = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "docs/customer/abu_dhabi_liveability_site_validation"
            / "liveability_data_20260730_semantic_layer_v34_enum_domains_20260904.json"
        ).read_text(encoding="utf-8")
    )
    semantic_ir = AdHocSemanticQueryIR.model_validate(
        {
            "language": "en",
            "status": "query",
            "semantic_entity": "dmt_liveability.fact_district_scores",
            "band_summary": {
                "score_field_ref": {
                    "semantic_entity": "dmt_liveability.fact_district_scores",
                    "semantic_field": "overall_score",
                },
                "member_field_ref": {
                    "semantic_entity": "dmt_liveability.dim_districts",
                    "semantic_field": "name_en",
                },
                "bands": [
                    {"key": "high", "lower": 75, "lower_inclusive": False},
                    {
                        "key": "medium",
                        "lower": 50,
                        "lower_inclusive": True,
                        "upper": 75,
                        "upper_inclusive": True,
                    },
                    {"key": "low", "upper": 50, "upper_inclusive": False},
                ],
                "member_band": "low",
                "count_output_name": "district_count",
                "member_output_name": "low_band_districts",
            },
            "filters": [
                {
                    "field_ref": {
                        "semantic_entity": "dmt_liveability.fact_district_scores",
                        "semantic_field": "stage",
                    },
                    "operator": "eq",
                    "values": ["Existing"],
                }
            ],
            "joins": [
                {
                    "left_field_ref": {
                        "semantic_entity": "dmt_liveability.fact_district_scores",
                        "semantic_field": "district_id",
                    },
                    "right_field_ref": {
                        "semantic_entity": "dmt_liveability.dim_districts",
                        "semantic_field": "district_id",
                    },
                    "kind": "equality",
                    "operator": "eq",
                },
                {
                    "left_field_ref": {
                        "semantic_entity": "dmt_liveability.fact_district_scores",
                        "semantic_field": "calc_version_id",
                    },
                    "right_field_ref": {
                        "semantic_entity": "dmt_liveability.dim_calc_versions",
                        "semantic_field": "calc_version_id",
                    },
                    "kind": "equality",
                    "operator": "eq",
                },
            ],
        }
    )
    plan = build_compiled_ad_hoc_semantic_plan(
        semantic_ir=semantic_ir,
        source=SOURCE,
        semantic_version=semantic_layer["semantic_version"],
        semantic_layer=semantic_layer,
        max_rows=1000,
        question=(
            "Divide all assessed districts into high above 75%, medium from 50% "
            "to 75%, and low below 50% bands based on their Existing quantitative "
            "scores. How many districts are in each band, and which districts are "
            "in the low band?"
        ),
    )
    assert "CASE WHEN" in plan.compiled_statement
    assert "STRING_AGG" in plan.compiled_statement
    assert "75.0" not in plan.compiled_statement
    assert plan.parameter_bindings["gda_band_lower_001_002"] == 75.0
    assert plan.semantic_ir.band_summary is not None
    assert plan.logical_plan.nodes[-1].attributes["row_limit"] == 3


def test_band_summary_rejects_invalid_band_bounds() -> None:
    with pytest.raises(ValueError, match="lower bound"):
        AdHocSemanticQueryIR.model_validate(
            {
                "language": "en",
                "status": "query",
                "semantic_entity": "dmt_liveability.fact_district_scores",
                "band_summary": {
                    "score_field_ref": {
                        "semantic_entity": "dmt_liveability.fact_district_scores",
                        "semantic_field": "overall_score",
                    },
                    "member_field_ref": {
                        "semantic_entity": "dmt_liveability.dim_districts",
                        "semantic_field": "name_en",
                    },
                    "bands": [
                        {"key": "low", "upper": 50, "upper_inclusive": False},
                        {
                            "key": "high",
                            "lower": 75,
                            "lower_inclusive": False,
                            "upper": 70,
                        },
                    ],
                    "member_band": "low",
                },
            }
        )


def test_universal_quantification_compiles_from_reviewed_sentinel_policy() -> None:
    """Every-assessed-district semantics are compiler-owned, not SQL text."""

    root = Path(__file__).resolve().parents[1]
    semantic = json.loads(
        (
            root
            / "docs/customer/abu_dhabi_liveability_site_validation"
            / "liveability_data_20260730_semantic_layer_v35_fpp_sentinel_four_stage_20260904.json"
        ).read_text(encoding="utf-8")
    )
    entity = "dmt_liveability.fact_facility_provision"
    district = "dmt_liveability.dim_districts"
    ir = AdHocSemanticQueryIR.model_validate(
        {
            "language": "en",
            "status": "query",
            "semantic_entity": entity,
            "projections": [
                {
                    "output_name": "facility_type",
                    "role": "dimension",
                    "field_ref": {
                        "semantic_entity": entity,
                        "semantic_field": "subcategory_name",
                    },
                }
            ],
            "filters": [
                {
                    "field_ref": {
                        "semantic_entity": district,
                        "semantic_field": "is_activated",
                    },
                    "operator": "eq",
                    "values": [True],
                }
            ],
            "joins": [
                {
                    "left_field_ref": {
                        "semantic_entity": entity,
                        "semantic_field": "district_id",
                    },
                    "right_field_ref": {
                        "semantic_entity": district,
                        "semantic_field": "district_id",
                    },
                    "kind": "equality",
                    "operator": "eq",
                }
            ],
            "universal_conditions": [
                {
                    "policy_id": "liveability.fpp.assessed_district_universal_v1",
                    "field_ref": {
                        "semantic_entity": entity,
                        "semantic_field": "kpi_existing",
                    },
                    "operator": "eq",
                    "values": [100],
                }
            ],
        }
    )
    plan = build_compiled_ad_hoc_semantic_plan(
        semantic_ir=ir,
        source={"source_id": 12, "database_name": "liveability_data_20260730"},
        semantic_version=semantic["semantic_version"],
        semantic_layer=semantic,
        max_rows=1000,
        question="Which facility types have an FPP score of 100% in every assessed district?",
    )
    sql = plan.compiled_statement
    assert "gda_universal_base" in sql
    assert "COUNT(DISTINCT gda_universal_scope)" in sql
    assert '"kpi_existing" > :gda_universal_valid_001' in sql
    assert '"kpi_existing" <= :gda_universal_valid_002' in sql
    assert plan.parameter_bindings["gda_universal_target_001"] == 100
    aggregate_node = next(
        node for node in plan.logical_plan.nodes if node.operator == "aggregate"
    )
    assert aggregate_node.attributes["universal_quantification"]["policy_id"] == (
        "liveability.fpp.assessed_district_universal_v1"
    )
