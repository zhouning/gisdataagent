from __future__ import annotations

import json
from pathlib import Path

import pytest

from data_agent.semantic_query_ir import (
    AdHocSemanticQueryIR,
    CategoricalScopeValueResolutionEvidence,
    FederatedMergeStrategy,
    JoinKind,
    SemanticAggregate,
    SpatialIntent,
    SemanticIRCompilationError,
    SemanticQueryRoute,
    build_compiled_ad_hoc_semantic_plan,
    build_certified_metric_contract_plan,
    build_federated_semantic_plan_evidence,
    build_shadow_semantic_plan_evidence,
    infer_spatial_intent,
    _reviewed_domain_alias_variants,
)
from data_agent.governed_virtual_nl2sql import validate_semantic_sql
from data_agent.connectors.database import validate_database_read_query
from data_agent.ontology.semantic_execution import (
    scope_virtual_semantic_layer_to_ontology,
    validate_virtual_ontology_semantic_gate,
)

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
LIVEABILITY_V38_SEMANTIC_PATH = (
    Path(__file__).resolve().parents[1]
    / "docs/customer/abu_dhabi_liveability_site_validation"
    / "liveability_data_20260730_semantic_layer_v38_ontology_semantic_evolution_20260909.json"
)
LIVEABILITY_V41_SEMANTIC_PATH = (
    Path(__file__).resolve().parents[1]
    / "docs/customer/abu_dhabi_liveability_site_validation"
    / "liveability_data_20260730_semantic_layer_v41_detail_grain_contracts_20260911.json"
)
LIVEABILITY_V62_SEMANTIC_PATH = (
    Path(__file__).resolve().parents[1]
    / "docs/customer/abu_dhabi_liveability_site_validation"
    / "liveability_data_20260730_semantic_layer_v62_ontology_authority_alignment_20260917.json"
)
MAKANI_V15_SEMANTIC_PATH = (
    Path(__file__).resolve().parents[1]
    / "docs/customer/abu_dhabi_liveability_site_validation"
    / "makani_sync_full_semantic_layer_v15_masterplan_district_spatial_relation_20260910.json"
)
MAKANI_V16_SEMANTIC_PATH = (
    Path(__file__).resolve().parents[1]
    / "docs/customer/abu_dhabi_liveability_site_validation"
    / "makani_sync_full_semantic_layer_v16_district_label_comparison_20260910.json"
)


def _makani_semantic_layer() -> dict:
    return json.loads(MAKANI_SEMANTIC_PATH.read_text(encoding="utf-8"))


def _liveability_semantic_layer() -> dict:
    return json.loads(LIVEABILITY_SEMANTIC_PATH.read_text(encoding="utf-8"))


def _liveability_published_json_semantic_layer() -> dict:
    return json.loads(LIVEABILITY_PUBLISHED_JSON_SEMANTIC_PATH.read_text(encoding="utf-8"))


def _liveability_v24_semantic_layer() -> dict:
    return json.loads(LIVEABILITY_V24_SEMANTIC_PATH.read_text(encoding="utf-8"))


def _liveability_v38_semantic_layer() -> dict:
    return json.loads(LIVEABILITY_V38_SEMANTIC_PATH.read_text(encoding="utf-8"))


def _liveability_v41_semantic_layer() -> dict:
    return json.loads(LIVEABILITY_V41_SEMANTIC_PATH.read_text(encoding="utf-8"))


def _liveability_v62_scoped_semantic_layer() -> dict:
    semantic_layer = json.loads(
        LIVEABILITY_V62_SEMANTIC_PATH.read_text(encoding="utf-8")
    )
    gate = validate_virtual_ontology_semantic_gate(
        semantic_layer,
        LIVEABILITY_V62_SEMANTIC_PATH,
    )
    return scope_virtual_semantic_layer_to_ontology(semantic_layer, gate)


def _liveability_grouped_measure_filter_policy(semantic_layer: dict) -> None:
    binding = next(
        item
        for item in semantic_layer["table_bindings"]
        if item.get("semantic_entity") == "dmt_liveability.fact_facility_provision"
    )
    field = next(
        item for item in binding["fields"] if item.get("semantic_field") == "demand_current"
    )
    field["grouped_measure_filter_policy"] = {
        "schema": "gda.semantic-grouped-measure-filter-policy.v1",
        "policy_id": "liveability.facility_provision.demand_current.grouped-sum.v1",
        "review_status": "reviewed_runtime_validated",
        "execution_authorized": True,
        "aggregate": "sum",
        "allowed_operators": ["gt", "gte", "lt", "lte", "eq", "neq"],
        "requires_grouped_result": True,
        "source_evidence": {
            "path": "docs/source/fact-facility-provision-card.md",
            "sha256": "a" * 64,
            "benchmark_questions_used": False,
            "gold_sql_used": False,
            "gold_results_used": False,
            "model_outputs_used": False,
        },
        "source_rows_persisted": False,
    }


def _makani_v15_semantic_layer() -> dict:
    return json.loads(MAKANI_V15_SEMANTIC_PATH.read_text(encoding="utf-8"))


def _makani_v16_semantic_layer() -> dict:
    return json.loads(MAKANI_V16_SEMANTIC_PATH.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("Show facilities inside each district.", SpatialIntent.WITHIN),
        ("统计区域范围内的设施。", SpatialIntent.WITHIN),
        ("Find facilities within 500 metres of a road.", SpatialIntent.DISTANCE),
        ("Count overlapping parcels.", SpatialIntent.INTERSECTS),
        ("Count facilities by district association.", SpatialIntent.NONE),
        ("Rank districts by their within-municipality share.", SpatialIntent.NONE),
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
    assert ":gda_scope_001" in plan.compiled_statement
    assert plan.parameter_bindings["gda_p_001"] == 0
    assert plan.parameter_bindings["gda_scope_001"] is True
    having_nodes = [
        node for node in plan.logical_plan.nodes
        if node.operator == "filter" and node.attributes.get("predicate_stage") == "post_aggregate"
    ]
    assert len(having_nodes) == 1


def test_ad_hoc_semantic_compiler_promotes_reviewed_grouped_measure_filter() -> None:
    semantic_layer = _liveability_v38_semantic_layer()
    _liveability_grouped_measure_filter_policy(semantic_layer)
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
                    "output_name": "existing_count_sum",
                    "role": "metric",
                    "aggregate": "sum",
                    "field_ref": {
                        "semantic_entity": "dmt_liveability.fact_facility_provision",
                        "semantic_field": "existing_count",
                    },
                },
            ],
            "filters": [
                {
                    "field_ref": {
                        "semantic_entity": "dmt_liveability.fact_facility_provision",
                        "semantic_field": "demand_current",
                    },
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

    assert all(
        item.field_ref.semantic_field != "demand_current"
        for item in plan.semantic_ir.filters
    )
    assert len(plan.semantic_ir.having_filters) == 1
    assert plan.semantic_ir.having_filters[0].aggregate is SemanticAggregate.SUM
    assert 'HAVING SUM(gda_source."demand_current") > :gda_p_001' in plan.compiled_statement
    assert 'WHERE gda_source."demand_current"' not in plan.compiled_statement
    assert (
        "semantic_ir_promoted_grouped_measure_filter:"
        "dmt_liveability.fact_facility_provision.demand_current"
    ) in plan.compiler_semantic_filter_corrections


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
    assert plan.parameter_bindings["gda_p_001"] == 100
    assert plan.parameter_bindings["gda_scope_001"] is True


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
        "semantic_ir_applied_row_scope:LIVEABILITY_ACTIVE_ASSESSED_DISTRICTS_V1",
    )
    assert {"urban", "rural"}.issubset(plan.parameter_bindings.values())
    assert True in plan.parameter_bindings.values()
    assert 'gda_source."classification" IN (' in plan.compiled_statement


def test_ad_hoc_semantic_compiler_binds_single_explicit_reviewed_enum_to_in_filter() -> None:
    semantic_layer = _liveability_v38_semantic_layer()
    semantic_ir = AdHocSemanticQueryIR.model_validate(
        {
            "language": "en",
            "status": "query",
            "semantic_entity": "dmt_liveability.fact_district_scores",
            "projections": [
                {
                    "output_name": "overall_score",
                    "role": "dimension",
                    "field_ref": {
                        "semantic_entity": "dmt_liveability.fact_district_scores",
                        "semantic_field": "overall_score",
                    },
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
        question="List all district domain scores for the existing lifecycle stage.",
    )

    assert (
        "semantic_ir_added_explicit_domain_filter:dmt_liveability.fact_district_scores.stage"
        in plan.compiler_semantic_filter_corrections
    )
    assert "Existing" in plan.parameter_bindings.values()
    assert 'gda_source."stage" IN (' in plan.compiled_statement


def test_reviewed_domain_alias_variants_cover_regular_and_irregular_plurals():
    assert "community hubs" in _reviewed_domain_alias_variants("Community_Hub")
    assert "wedding halls" in _reviewed_domain_alias_variants("Wedding_Hall")
    assert "libraries" in _reviewed_domain_alias_variants("Library")
    assert "pharmacies" in _reviewed_domain_alias_variants("Pharmacy")
    assert "mosques" in _reviewed_domain_alias_variants("Mosque")


def test_reviewed_domain_alias_variants_skip_non_english_or_numeric_values():
    assert _reviewed_domain_alias_variants("阶段_1") == ()
    assert _reviewed_domain_alias_variants("مرحلة") == ()


def test_ad_hoc_semantic_compiler_normalizes_existing_reviewed_enum_alias() -> None:
    semantic_layer = _liveability_v38_semantic_layer()
    semantic_ir = AdHocSemanticQueryIR.model_validate(
        {
            "language": "en",
            "status": "query",
            "semantic_entity": "dmt_liveability.fact_district_scores",
            "projections": [
                {
                    "output_name": "overall_score",
                    "role": "dimension",
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
                    "values": ["current"],
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
        question="List district scores for the existing lifecycle stage.",
    )

    assert (
        "semantic_ir_normalized_explicit_domain_filter:"
        "dmt_liveability.fact_district_scores.stage"
        in plan.compiler_semantic_filter_corrections
    )
    assert "Existing" in plan.parameter_bindings.values()
    assert "current" not in plan.parameter_bindings.values()
    assert 'gda_source."stage" IN (' in plan.compiled_statement


def test_ad_hoc_semantic_compiler_does_not_bind_ambiguous_single_domain_value() -> None:
    semantic_layer = _liveability_v38_semantic_layer()
    binding = next(
        item
        for item in semantic_layer["table_bindings"]
        if item["semantic_entity"] == "dmt_liveability.fact_district_scores"
    )
    transport_score = next(
        item for item in binding["fields"] if item["semantic_field"] == "transport_score"
    )
    transport_score["source_value_domain_observed"] = ["Existing", "Future"]
    transport_score["value_semantics"] = {
        "Existing": ["existing"],
        "Future": ["future"],
    }
    semantic_ir = AdHocSemanticQueryIR.model_validate(
        {
            "language": "en",
            "status": "query",
            "semantic_entity": "dmt_liveability.fact_district_scores",
            "projections": [
                {
                    "output_name": "overall_score",
                    "role": "dimension",
                    "field_ref": {
                        "semantic_entity": "dmt_liveability.fact_district_scores",
                        "semantic_field": "overall_score",
                    },
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
        question="List district scores for the existing lifecycle stage.",
    )

    assert not any(
        correction.startswith("semantic_ir_added_explicit_domain_filter:")
        for correction in plan.compiler_semantic_filter_corrections
    )
    assert 'gda_source."stage" IN (' not in plan.compiled_statement
    assert 'gda_source."transport_score" IN (' not in plan.compiled_statement


def test_ad_hoc_semantic_compiler_rejects_conflicting_single_explicit_domain_value() -> None:
    semantic_layer = _liveability_v38_semantic_layer()
    semantic_ir = AdHocSemanticQueryIR.model_validate(
        {
            "language": "en",
            "status": "query",
            "semantic_entity": "dmt_liveability.fact_district_scores",
            "projections": [
                {
                    "output_name": "overall_score",
                    "role": "dimension",
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
                    "values": ["Pipeline"],
                }
            ],
        }
    )

    with pytest.raises(
        SemanticIRCompilationError,
        match="semantic_ir_explicit_domain_filter_conflict",
    ):
        build_compiled_ad_hoc_semantic_plan(
            semantic_ir=semantic_ir,
            source=SOURCE,
            semantic_version=semantic_layer["semantic_version"],
            semantic_layer=semantic_layer,
            max_rows=1000,
            question="List district scores for the existing lifecycle stage.",
        )


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
    assert plan.compiler_semantic_filter_corrections == (
        "semantic_ir_applied_row_scope:LIVEABILITY_ACTIVE_ASSESSED_DISTRICTS_V1",
    )
    assert '"classification"' in plan.compiled_statement
    assert '"is_activated"' in plan.compiled_statement


def test_ad_hoc_semantic_compiler_applies_spatial_crs_by_relation_endpoint() -> None:
    semantic_layer = _makani_v16_semantic_layer()
    semantic_ir = AdHocSemanticQueryIR.model_validate(
        {
            "language": "en",
            "status": "query",
            "semantic_entity": "dmt_utility.ud_masterplan_boundary",
            "spatial_intent": "intersects",
            "projections": [
                {
                    "output_name": "project_name",
                    "role": "attribute",
                    "field_ref": {
                        "semantic_entity": "dmt_utility.ud_masterplan_boundary",
                        "semantic_field": "project_name",
                    },
                },
                {
                    "output_name": "approval_year",
                    "role": "attribute",
                    "field_ref": {
                        "semantic_entity": "dmt_utility.ud_masterplan_boundary",
                        "semantic_field": "approvalyear",
                    },
                },
                {
                    "output_name": "developer_name",
                    "role": "attribute",
                    "field_ref": {
                        "semantic_entity": "dmt_utility.ud_masterplan_boundary",
                        "semantic_field": "developer_name",
                    },
                },
            ],
            "filters": [
                {
                    "field_ref": {
                        "semantic_entity": "dmt_utility.udm_district",
                        "semantic_field": "nameenglish",
                    },
                    "operator": "eq",
                    "values": ["a named district"],
                }
            ],
            "joins": [
                {
                    "left_field_ref": {
                        "semantic_entity": "dmt_utility.ud_masterplan_boundary",
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

    plan = build_compiled_ad_hoc_semantic_plan(
        semantic_ir=semantic_ir,
        source={"source_id": 13, "database_name": "makani_sync_full"},
        semantic_version=semantic_layer["semantic_version"],
        semantic_layer=semantic_layer,
        max_rows=1000,
        expected_spatial_intent=SpatialIntent.INTERSECTS,
        question="Which master-plan projects overlap a named district?",
    )

    assert "FROM public.ud_masterplan_boundary AS gda_source" in plan.compiled_statement
    assert "JOIN public.udm_district AS gda_join_001" in plan.compiled_statement
    assert (
        'ST_Intersects(gda_source."shape", '
        'ST_Transform(gda_join_001."shape", 32640))'
    ) in plan.compiled_statement
    assert 'UPPER(BTRIM(gda_join_001."nameenglish")) = :gda_p_001' in plan.compiled_statement
    assert "A NAMED DISTRICT" in plan.parameter_bindings.values()
    assert plan.compiler_text_comparison_policy_ids == (
        "makani.udm_district.nameenglish.trim-uppercase-comparison.v1",
    )


def test_ad_hoc_semantic_compiler_normalizes_field_identifier_aliases() -> None:
    semantic_layer = _makani_v16_semantic_layer()
    semantic_ir = AdHocSemanticQueryIR.model_validate(
        {
            "language": "en",
            "status": "query",
            "semantic_entity": "dmt_utility.ud_masterplan_boundary",
            "projections": [
                {
                    "output_name": "project_name",
                    "role": "attribute",
                    "field_ref": {
                        "semantic_entity": "dmt_utility.ud_masterplan_boundary",
                        "semantic_field": "projectname",
                    },
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
        question="List recorded master plan project names.",
    )

    assert 'gda_source."project_name" AS "project_name"' in plan.compiled_statement


def test_ad_hoc_semantic_compiler_applies_v38_reviewed_row_scopes() -> None:
    semantic_layer = _liveability_v38_semantic_layer()
    semantic_ir = AdHocSemanticQueryIR.model_validate(
        {
            "language": "en",
            "status": "query",
            "semantic_entity": "dmt_liveability.fact_district_scores",
            "projections": [
                {
                    "output_name": "overall_score",
                    "role": "dimension",
                    "field_ref": {
                        "semantic_entity": "dmt_liveability.fact_district_scores",
                        "semantic_field": "overall_score",
                    },
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
        question="List district overall scores.",
    )

    assert plan.physical_plan.tables == (
        "public.dim_calc_versions",
        "public.dim_districts",
        "public.fact_district_scores",
    )
    assert "JOIN public.dim_districts AS" in plan.compiled_statement
    assert "JOIN public.dim_calc_versions AS" in plan.compiled_statement
    assert '"is_activated"' in plan.compiled_statement
    assert '"current_flag"' in plan.compiled_statement
    assert set(plan.parameter_bindings.values()) == {True}
    assert plan.compiler_semantic_filter_corrections == (
        "semantic_ir_applied_row_scope:LIVEABILITY_ACTIVE_ASSESSED_DISTRICTS_V1",
        "semantic_ir_applied_row_scope:LIVEABILITY_CURRENT_APPROVED_CALC_VERSION_V1",
    )


def test_v62_ontology_scope_enforces_current_version_without_promoting_control_table() -> None:
    semantic_layer = _liveability_v62_scoped_semantic_layer()
    semantic_ir = AdHocSemanticQueryIR.model_validate(
        {
            "language": "en",
            "status": "query",
            "semantic_entity": "dmt_liveability.fact_district_scores",
            "projections": [
                {
                    "output_name": "overall_score",
                    "role": "attribute",
                    "field_ref": {
                        "semantic_entity": "dmt_liveability.fact_district_scores",
                        "semantic_field": "overall_score",
                    },
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
        question="List district overall scores.",
    )

    support_binding = next(
        binding
        for binding in semantic_layer["table_bindings"]
        if binding["physical_table"] == "public.dim_calc_versions"
    )
    assert support_binding["execution_eligible"] is False
    assert support_binding["compiler_governance_support"] is True
    assert plan.physical_plan.tables == (
        "public.dim_calc_versions",
        "public.dim_districts",
        "public.fact_district_scores",
    )
    assert 'JOIN public.dim_calc_versions AS' in plan.compiled_statement
    assert '"current_flag" = :gda_scope_' in plan.compiled_statement
    assert plan.compiler_semantic_filter_corrections == (
        "semantic_ir_applied_row_scope:LIVEABILITY_ACTIVE_ASSESSED_DISTRICTS_V1",
        "semantic_ir_applied_row_scope:LIVEABILITY_CURRENT_APPROVED_CALC_VERSION_V1",
    )
    evidence = validate_semantic_sql(
        plan.compiled_statement,
        list(plan.physical_plan.tables),
        semantic_layer,
        sql_params=plan.parameter_bindings,
        question="List district overall scores.",
    )
    assert evidence["row_scope_policies"]["applied"] == [
        "LIVEABILITY_ACTIVE_ASSESSED_DISTRICTS_V1",
        "LIVEABILITY_CURRENT_APPROVED_CALC_VERSION_V1",
    ]


def test_v62_compiler_governance_support_is_not_model_queryable() -> None:
    semantic_layer = _liveability_v62_scoped_semantic_layer()
    control_table_ir = AdHocSemanticQueryIR.model_validate(
        {
            "language": "en",
            "status": "query",
            "semantic_entity": "dmt_liveability.dim_calc_versions",
            "projections": [
                {
                    "output_name": "current_flag",
                    "role": "attribute",
                    "field_ref": {
                        "semantic_entity": "dmt_liveability.dim_calc_versions",
                        "semantic_field": "current_flag",
                    },
                }
            ],
        }
    )
    hidden_join_key_ir = AdHocSemanticQueryIR.model_validate(
        {
            "language": "en",
            "status": "query",
            "semantic_entity": "dmt_liveability.fact_district_scores",
            "projections": [
                {
                    "output_name": "calc_version_id",
                    "role": "attribute",
                    "field_ref": {
                        "semantic_entity": "dmt_liveability.fact_district_scores",
                        "semantic_field": "calc_version_id",
                    },
                }
            ],
        }
    )

    with pytest.raises(
        SemanticIRCompilationError,
        match="semantic_entity_not_active_or_ambiguous",
    ):
        build_compiled_ad_hoc_semantic_plan(
            semantic_ir=control_table_ir,
            source=SOURCE,
            semantic_version=semantic_layer["semantic_version"],
            semantic_layer=semantic_layer,
            max_rows=1000,
            question="List calculation-version control flags.",
        )
    with pytest.raises(
        SemanticIRCompilationError,
        match="semantic_field_not_active_or_ambiguous",
    ):
        build_compiled_ad_hoc_semantic_plan(
            semantic_ir=hidden_join_key_ir,
            source=SOURCE,
            semantic_version=semantic_layer["semantic_version"],
            semantic_layer=semantic_layer,
            max_rows=1000,
            question="List score calculation version identifiers.",
        )


def test_ad_hoc_semantic_compiler_normalizes_matching_reviewed_row_scope_filter() -> None:
    semantic_layer = _liveability_v38_semantic_layer()
    semantic_ir = AdHocSemanticQueryIR.model_validate(
        {
            "language": "en",
            "status": "query",
            "semantic_entity": "dmt_liveability.fact_district_scores",
            "projections": [
                {
                    "output_name": "overall_score",
                    "role": "dimension",
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
                        "semantic_entity": "dmt_liveability.dim_districts",
                        "semantic_field": "is_activated",
                    },
                    "operator": "eq",
                    "values": [True],
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
        question="List district overall scores.",
    )

    assert plan.compiled_statement.count('"is_activated"') == 1
    assert plan.compiler_semantic_filter_corrections == (
        "semantic_ir_normalized_row_scope_filter:LIVEABILITY_ACTIVE_ASSESSED_DISTRICTS_V1",
        "semantic_ir_applied_row_scope:LIVEABILITY_ACTIVE_ASSESSED_DISTRICTS_V1",
        "semantic_ir_applied_row_scope:LIVEABILITY_CURRENT_APPROVED_CALC_VERSION_V1",
    )


def test_ad_hoc_semantic_compiler_enforces_reviewed_row_scope_over_conflicting_model_filter() -> None:
    semantic_layer = _liveability_v38_semantic_layer()
    semantic_ir = AdHocSemanticQueryIR.model_validate(
        {
            "language": "en",
            "status": "query",
            "semantic_entity": "dmt_liveability.fact_district_scores",
            "projections": [
                {
                    "output_name": "overall_score",
                    "role": "dimension",
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
                        "semantic_entity": "dmt_liveability.dim_districts",
                        "semantic_field": "is_activated",
                    },
                    "operator": "eq",
                    "values": [False],
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
        question="List district overall scores.",
    )

    assert plan.compiled_statement.count('"is_activated"') == 1
    assert set(plan.parameter_bindings.values()) == {True}
    assert plan.compiler_semantic_filter_corrections == (
        "semantic_ir_removed_conflicting_row_scope_filter:LIVEABILITY_ACTIVE_ASSESSED_DISTRICTS_V1",
        "semantic_ir_applied_row_scope:LIVEABILITY_ACTIVE_ASSESSED_DISTRICTS_V1",
        "semantic_ir_applied_row_scope:LIVEABILITY_CURRENT_APPROVED_CALC_VERSION_V1",
    )


def test_ad_hoc_semantic_compiler_keeps_scope_filter_after_explicit_override() -> None:
    semantic_layer = _liveability_v38_semantic_layer()
    semantic_ir = AdHocSemanticQueryIR.model_validate(
        {
            "language": "en",
            "status": "query",
            "semantic_entity": "dmt_liveability.fact_district_scores",
            "projections": [
                {
                    "output_name": "overall_score",
                    "role": "dimension",
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
                        "semantic_entity": "dmt_liveability.dim_districts",
                        "semantic_field": "is_activated",
                    },
                    "operator": "is_null",
                    "values": [],
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
        question="List scores and include inactive districts.",
    )

    assert 'gda_join_001."is_activated" IS NULL' in plan.compiled_statement
    assert not any(
        "LIVEABILITY_ACTIVE_ASSESSED_DISTRICTS_V1" in correction
        for correction in plan.compiler_semantic_filter_corrections
    )


def test_ad_hoc_semantic_compiler_respects_v38_row_scope_overrides() -> None:
    semantic_layer = _liveability_v38_semantic_layer()
    semantic_ir = AdHocSemanticQueryIR.model_validate(
        {
            "language": "en",
            "status": "query",
            "semantic_entity": "dmt_liveability.fact_district_scores",
            "projections": [
                {
                    "output_name": "overall_score",
                    "role": "dimension",
                    "field_ref": {
                        "semantic_entity": "dmt_liveability.fact_district_scores",
                        "semantic_field": "overall_score",
                    },
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
        question="List scores for all raw districts and compare versions.",
    )

    assert plan.physical_plan.tables == ("public.fact_district_scores",)
    assert plan.compiler_semantic_filter_corrections == ()


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


def _makani_categorical_spatial_scope() -> dict:
    return {
        "scope_id": "makani.planning_project_recorded_precinct.v1",
        "scope_kind": "source_recorded_categorical_scope",
        "review_status": "reviewed",
        "semantic_entity": "dmt_utility.masterplan_ud_masterplan_boundary",
        "semantic_field": "precinctid",
        "supported_spatial_intents": ["intersects"],
        "allowed_filter_operators": ["eq", "in"],
        "required_scope_term_groups": {
            "en": [["planned", "planning", "master plan", "masterplan"], ["overlap", "intersect"]],
            "zh": [["规划", "总体规划", "主计划"], ["重叠", "相交", "交叠"]],
            "ar": [["مخطط", "تخطيط", "رئيسي"], ["تداخل", "يتقاطع"]],
        },
        "source_evidence": {
            "path": "docs/source/masterplan-card.md",
            "sha256": "a" * 64,
            "benchmark_questions_used": False,
            "gold_sql_used": False,
            "gold_results_used": False,
            "model_outputs_used": False,
        },
        "description": (
            "This source-recorded planning precinct classification is not a "
            "geometric intersection or a substitute for a PostGIS predicate."
        ),
        "source_rows_persisted": False,
    }


def _makani_recorded_scope_ir(*, spatial_intent: str = "intersects", operator: str = "eq") -> AdHocSemanticQueryIR:
    return AdHocSemanticQueryIR.model_validate(
        {
            "language": "en",
            "status": "query",
            "semantic_entity": "dmt_utility.masterplan_ud_masterplan_boundary",
            "spatial_intent": spatial_intent,
            "projections": [
                {
                    "output_name": "project_name",
                    "role": "attribute",
                    "field_ref": {
                        "semantic_entity": "dmt_utility.masterplan_ud_masterplan_boundary",
                        "semantic_field": "project_name",
                    },
                }
            ],
            "filters": [
                {
                    "field_ref": {
                        "semantic_entity": "dmt_utility.masterplan_ud_masterplan_boundary",
                        "semantic_field": "precinctid",
                    },
                    "operator": operator,
                    "values": ["Example planning precinct"],
                }
            ],
        }
    )


def test_ad_hoc_semantic_compiler_accepts_reviewed_source_recorded_categorical_spatial_scope() -> None:
    semantic_layer = _makani_semantic_layer()
    semantic_layer["categorical_spatial_scopes"] = [_makani_categorical_spatial_scope()]

    plan = build_compiled_ad_hoc_semantic_plan(
        semantic_ir=_makani_recorded_scope_ir(),
        source={"source_id": 13, "database_name": "makani_sync_full"},
        semantic_version=semantic_layer["semantic_version"],
        semantic_layer=semantic_layer,
        max_rows=1000,
        expected_spatial_intent=SpatialIntent.INTERSECTS,
        question="List planned projects that overlap the recorded planning scope.",
    )

    assert 'gda_source."precinctid" = :gda_p_001' in plan.compiled_statement
    assert "ST_Intersects" not in plan.compiled_statement
    assert plan.compiler_categorical_spatial_scope_ids == (
        "makani.planning_project_recorded_precinct.v1",
    )
    assert any(
        item.check_id == "reviewed_categorical_spatial_scope" and item.passed
        for item in plan.validation.checks
    )
    assert plan.logical_plan.nodes[0].attributes["categorical_spatial_scope_ids"] == [
        "makani.planning_project_recorded_precinct.v1"
    ]


def test_ad_hoc_semantic_compiler_records_row_free_scope_value_resolution() -> None:
    semantic_layer = _makani_semantic_layer()
    semantic_layer["categorical_spatial_scopes"] = [_makani_categorical_spatial_scope()]
    resolution = CategoricalScopeValueResolutionEvidence(
        scope_id="makani.planning_project_recorded_precinct.v1",
        semantic_entity="dmt_utility.masterplan_ud_masterplan_boundary",
        semantic_field="precinctid",
        strategy="unique_suffix_source_value",
        candidate_sha256="a" * 64,
        resolved_value_sha256="b" * 64,
        source_candidate_count=1,
    )

    plan = build_compiled_ad_hoc_semantic_plan(
        semantic_ir=_makani_recorded_scope_ir(),
        source={"source_id": 13, "database_name": "makani_sync_full"},
        semantic_version=semantic_layer["semantic_version"],
        semantic_layer=semantic_layer,
        max_rows=1000,
        expected_spatial_intent=SpatialIntent.INTERSECTS,
        question="List planned projects that overlap the recorded planning scope.",
        categorical_scope_value_resolutions=(resolution,),
    )

    assert plan.compiler_categorical_scope_value_resolutions == (resolution,)
    assert plan.compiler_categorical_scope_value_resolutions[0].source_rows_persisted is False


@pytest.mark.parametrize(
    ("semantic_ir", "question", "expected_intent"),
    [
        (
            _makani_recorded_scope_ir(),
            "List planned projects in the recorded planning scope.",
            SpatialIntent.INTERSECTS,
        ),
        (
            _makani_recorded_scope_ir(operator="contains"),
            "List planned projects that overlap the recorded planning scope.",
            SpatialIntent.INTERSECTS,
        ),
        (
            _makani_recorded_scope_ir(spatial_intent="within"),
            "List planned projects that overlap the recorded planning scope.",
            SpatialIntent.INTERSECTS,
        ),
    ],
)
def test_ad_hoc_semantic_compiler_rejects_unadmitted_categorical_spatial_scope(
    semantic_ir: AdHocSemanticQueryIR,
    question: str,
    expected_intent: SpatialIntent,
) -> None:
    semantic_layer = _makani_semantic_layer()
    semantic_layer["categorical_spatial_scopes"] = [_makani_categorical_spatial_scope()]

    with pytest.raises(
        SemanticIRCompilationError,
        match="semantic_ir_spatial_intent_(requires_spatial_join|mismatch)",
    ):
        build_compiled_ad_hoc_semantic_plan(
            semantic_ir=semantic_ir,
            source={"source_id": 13, "database_name": "makani_sync_full"},
            semantic_version=semantic_layer["semantic_version"],
            semantic_layer=semantic_layer,
            max_rows=1000,
            expected_spatial_intent=expected_intent,
            question=question,
        )


def test_ad_hoc_semantic_compiler_requires_scope_or_join_for_spatial_intent() -> None:
    semantic_layer = _makani_semantic_layer()

    with pytest.raises(
        SemanticIRCompilationError,
        match="semantic_ir_spatial_intent_requires_spatial_join",
    ):
        build_compiled_ad_hoc_semantic_plan(
            semantic_ir=_makani_recorded_scope_ir(),
            source={"source_id": 13, "database_name": "makani_sync_full"},
            semantic_version=semantic_layer["semantic_version"],
            semantic_layer=semantic_layer,
            max_rows=1000,
            expected_spatial_intent=SpatialIntent.INTERSECTS,
            question="List planned projects that overlap the recorded planning scope.",
        )


def test_ad_hoc_semantic_compiler_cannot_bypass_question_spatial_intent_gate() -> None:
    semantic_layer = _makani_semantic_layer()
    semantic_layer["categorical_spatial_scopes"] = [_makani_categorical_spatial_scope()]

    with pytest.raises(
        SemanticIRCompilationError,
        match="semantic_ir_spatial_intent_requires_spatial_join",
    ):
        build_compiled_ad_hoc_semantic_plan(
            semantic_ir=_makani_recorded_scope_ir(),
            source={"source_id": 13, "database_name": "makani_sync_full"},
            semantic_version=semantic_layer["semantic_version"],
            semantic_layer=semantic_layer,
            max_rows=1000,
            question="List planned projects that overlap the recorded planning scope.",
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
                "member_disambiguation_field_refs": [
                    {
                        "semantic_entity": "dmt_liveability.dim_districts",
                        "semantic_field": "municipality",
                    }
                ],
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
    assert plan.parameter_bindings["gda_p_001"] == "Existing"
    assert plan.parameter_bindings["gda_scope_001"] is True
    assert plan.parameter_bindings["gda_band_lower_001_002"] == 75.0
    assert plan.semantic_ir.band_summary is not None
    assert plan.logical_plan.nodes[-1].attributes["row_limit"] == 3


def test_compiler_promotes_lossless_explicit_numeric_band_projections() -> None:
    semantic_layer = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "docs/customer/abu_dhabi_liveability_site_validation"
            / "liveability_data_20260730_semantic_layer_v42_metric_execution_20260912.json"
        ).read_text(encoding="utf-8")
    )
    semantic_ir = AdHocSemanticQueryIR.model_validate(
        {
            "language": "en",
            "status": "query",
            "semantic_entity": "dmt_liveability.fact_district_scores",
            "projections": [
                {
                    "output_name": "score_band",
                    "role": "dimension",
                    "field_ref": {
                        "semantic_entity": "dmt_liveability.fact_district_scores",
                        "semantic_field": "overall_score",
                    },
                },
                {
                    "output_name": "district_count",
                    "role": "metric",
                    "aggregate": "count_distinct",
                    "field_ref": {
                        "semantic_entity": "dmt_liveability.fact_district_scores",
                        "semantic_field": "district_id",
                    },
                },
                {
                    "output_name": "low_band_districts",
                    "role": "dimension",
                    "field_ref": {
                        "semantic_entity": "dmt_liveability.dim_districts",
                        "semantic_field": "name_en",
                    },
                },
            ],
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
            "include_result_count": True,
            "result_count_alias": "total_assessed_districts",
        }
    )
    question = (
        "Divide all assessed districts into high above 75%, medium from 50% "
        "to 75%, and low below 50% bands based on their Existing quantitative "
        "scores. How many districts are in each band, and which districts are "
        "in the low band?"
    )

    plan = build_compiled_ad_hoc_semantic_plan(
        semantic_ir=semantic_ir,
        source=SOURCE,
        semantic_version=semantic_layer["semantic_version"],
        semantic_layer=semantic_layer,
        max_rows=1000,
        question=question,
    )

    assert plan.semantic_ir.band_summary is not None
    assert not plan.semantic_ir.projections
    assert "CASE WHEN" in plan.compiled_statement
    assert "STRING_AGG" in plan.compiled_statement
    assert "semantic_ir_promoted_explicit_numeric_band_summary" in (
        plan.compiler_semantic_filter_corrections
    )


def test_compiler_promotes_numeric_band_with_reviewed_label_and_threshold_or_group() -> None:
    semantic_layer = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "docs/customer/abu_dhabi_liveability_site_validation"
            / "liveability_data_20260730_semantic_layer_v42_metric_execution_20260912.json"
        ).read_text(encoding="utf-8")
    )
    score_ref = {
        "semantic_entity": "dmt_liveability.fact_district_scores",
        "semantic_field": "overall_score",
    }
    semantic_ir = AdHocSemanticQueryIR.model_validate(
        {
            "language": "en",
            "status": "query",
            "semantic_entity": "dmt_liveability.dim_districts",
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
                    "output_name": "municipality",
                    "role": "dimension",
                    "field_ref": {
                        "semantic_entity": "dmt_liveability.dim_districts",
                        "semantic_field": "municipality",
                    },
                },
                {"output_name": "score", "role": "dimension", "field_ref": score_ref},
                {"output_name": "score_band", "role": "dimension", "field_ref": score_ref},
                {"output_name": "district_count", "role": "metric", "aggregate": "count"},
            ],
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
            "any_filter_groups": [
                {
                    "filters": [
                        {"field_ref": score_ref, "operator": "gt", "values": [80]},
                        {"field_ref": score_ref, "operator": "gte", "values": [40]},
                        {"field_ref": score_ref, "operator": "lt", "values": [40]},
                    ]
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
    question = (
        "Put districts into red above 80%, amber from 40% to 80%, and green "
        "below 40% bands. How many districts are in each band, and which "
        "districts are in the green band?"
    )

    plan = build_compiled_ad_hoc_semantic_plan(
        semantic_ir=semantic_ir,
        source=SOURCE,
        semantic_version=semantic_layer["semantic_version"],
        semantic_layer=semantic_layer,
        max_rows=1000,
        question=question,
    )

    assert plan.semantic_ir.band_summary is not None
    assert plan.semantic_ir.band_summary.member_field_ref.semantic_field == "name_en"
    assert tuple(
        field.semantic_field
        for field in plan.semantic_ir.band_summary.member_disambiguation_field_refs
    ) == ("municipality",)
    assert not plan.semantic_ir.any_filter_groups
    assert not plan.semantic_ir.projections
    assert plan.parameter_bindings["gda_band_lower_001_002"] == 80.0
    assert "gda_band_member_context_001" in plan.compiled_statement
    assert "COUNT(*) OVER (PARTITION BY \"score_band\", gda_band_member)" in plan.compiled_statement
    assert "gda_band_member_display" in plan.compiled_statement
    assert 'SELECT "score_band", gda_band_member, CASE WHEN COUNT(*) OVER' in (
        plan.compiled_statement
    )


def test_band_summary_rejects_repeated_display_and_disambiguation_field() -> None:
    with pytest.raises(ValueError, match="member display and disambiguation fields"):
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
                    "member_disambiguation_field_refs": [
                        {
                            "semantic_entity": "dmt_liveability.dim_districts",
                            "semantic_field": "name_en",
                        }
                    ],
                    "bands": [
                        {"key": "low", "upper": 50, "upper_inclusive": True},
                        {"key": "high", "lower": 50, "lower_inclusive": False},
                    ],
                    "member_band": "low",
                },
            }
        )


def test_detail_projection_repair_demotes_safe_having_filter_for_entity_list() -> None:
    from data_agent.semantic_query_ir import _repair_reviewed_detail_projection_aggregates

    semantic_ir = AdHocSemanticQueryIR.model_validate(
        {
            "language": "en",
            "status": "query",
            "semantic_entity": "catalog.district_score",
            "projections": [
                {
                    "output_name": "district_name",
                    "role": "dimension",
                    "field_ref": {
                        "semantic_entity": "catalog.district_score",
                        "semantic_field": "name",
                    },
                },
                {
                    "output_name": "environment_score",
                    "role": "metric",
                    "aggregate": "avg",
                    "field_ref": {
                        "semantic_entity": "catalog.district_score",
                        "semantic_field": "environment_score",
                    },
                },
            ],
            "having_filters": [
                {
                    "field_ref": {
                        "semantic_entity": "catalog.district_score",
                        "semantic_field": "environment_score",
                    },
                    "aggregate": "avg",
                    "operator": "gt",
                    "values": [0],
                }
            ],
        }
    )
    semantic_layer = {
        "table_bindings": [
            {
                "semantic_entity": "catalog.district_score",
                "fields": [
                    {
                        "semantic_field": "environment_score",
                        "detail_projection_safe": True,
                    }
                ],
            }
        ],
        "display_projection_policies": [
            {
                "review_status": "reviewed",
                "semantic_entity": "catalog.district_score",
                "primary_label_field": "name",
            }
        ],
    }

    repaired = _repair_reviewed_detail_projection_aggregates(
        semantic_ir,
        semantic_layer,
        "Which districts have the lowest Environment scores?",
    )

    assert not repaired.having_filters
    assert repaired.filters[0].operator == "gt"
    assert repaired.projections[1].role.value == "attribute"
    assert repaired.projections[1].aggregate is None


def test_detail_filter_explanation_adds_reviewed_threshold_measure_to_entity_list() -> None:
    from data_agent.semantic_query_ir import (
        _add_reviewed_detail_filter_explanation_projections,
    )

    semantic_ir = AdHocSemanticQueryIR.model_validate(
        {
            "language": "en",
            "status": "query",
            "semantic_entity": "catalog.district_score",
            "projections": [
                {
                    "output_name": "district_name",
                    "role": "attribute",
                    "field_ref": {
                        "semantic_entity": "catalog.district_score",
                        "semantic_field": "name",
                    },
                }
            ],
            "filters": [
                {
                    "field_ref": {
                        "semantic_entity": "catalog.district_score",
                        "semantic_field": "overall_score",
                    },
                    "operator": "gt",
                    "values": [90],
                }
            ],
            "include_result_count": True,
        }
    )
    semantic_layer = {
        "table_bindings": [
            {
                "semantic_entity": "catalog.district_score",
                "fields": [
                    {"semantic_field": "name"},
                    {
                        "semantic_field": "overall_score",
                        "business_role": "measure",
                        "detail_projection_safe": True,
                        "detail_filter_explanation_policy": {
                            "review_status": "reviewed",
                            "application": ["entity_list_direct_numeric_filter"],
                        },
                    }
                ],
            },
        ],
        "display_projection_policies": [
            {
                "review_status": "reviewed",
                "semantic_entity": "catalog.district_score",
                "primary_label_field": "name",
            }
        ],
    }

    explained, added = _add_reviewed_detail_filter_explanation_projections(
        semantic_ir,
        semantic_layer,
        question="Which districts have an overall score above 90, and how many are there?",
    )
    count_only, count_only_added = _add_reviewed_detail_filter_explanation_projections(
        semantic_ir,
        semantic_layer,
        question="How many districts have an overall score above 90?",
    )

    assert added == ("overall_score",)
    assert [item.output_name for item in explained.projections] == [
        "district_name",
        "overall_score",
    ]
    assert count_only_added == ()
    assert count_only == semantic_ir


def test_context_dimension_policy_removes_parent_only_when_not_requested() -> None:
    from data_agent.semantic_query_ir import _apply_reviewed_context_dimension_policies

    semantic_ir = AdHocSemanticQueryIR.model_validate(
        {
            "language": "en",
            "status": "query",
            "semantic_entity": "catalog.facility",
            "projections": [
                {
                    "output_name": "facility_category",
                    "role": "dimension",
                    "field_ref": {
                        "semantic_entity": "catalog.facility",
                        "semantic_field": "category",
                    },
                },
                {
                    "output_name": "facility_type",
                    "role": "dimension",
                    "field_ref": {
                        "semantic_entity": "catalog.facility",
                        "semantic_field": "type",
                    },
                },
            ],
        }
    )
    semantic_layer = {
        "table_bindings": [
            {
                "semantic_entity": "catalog.facility",
                "fields": [
                    {
                        "semantic_field": "category",
                        "dimension_context_policy": {
                            "review_status": "reviewed",
                            "omit_when_child_projected": "type",
                            "retain_when_question_mentions": {
                                "en": ["facility category", "category"]
                            },
                        },
                    },
                    {"semantic_field": "type"},
                ],
            }
        ]
    }

    reduced, removed = _apply_reviewed_context_dimension_policies(
        semantic_ir,
        semantic_layer,
        question="Which facility type has the highest count?",
    )
    retained, retained_removed = _apply_reviewed_context_dimension_policies(
        semantic_ir,
        semantic_layer,
        question="Which facility category and type have the highest count?",
    )

    assert removed == ("facility_category",)
    assert [item.output_name for item in reduced.projections] == ["facility_type"]
    assert retained_removed == ()
    assert [item.output_name for item in retained.projections] == [
        "facility_category",
        "facility_type",
    ]


def test_compiler_removes_redundant_measure_dimension_and_projects_filtered_label() -> None:
    semantic_layer = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "docs/customer/abu_dhabi_liveability_site_validation"
            / "liveability_data_20260730_semantic_layer_v43_remaining_metric_policies_20260912.json"
        ).read_text(encoding="utf-8")
    )
    semantic_ir = AdHocSemanticQueryIR.model_validate(
        {
            "language": "en",
            "status": "query",
            "semantic_entity": "dmt_liveability.fact_ic_scores",
            "projections": [
                {
                    "output_name": "stage",
                    "role": "dimension",
                    "field_ref": {
                        "semantic_entity": "dmt_liveability.fact_ic_scores",
                        "semantic_field": "streetlight_perc_existing",
                    },
                },
                {
                    "output_name": "existing_completion",
                    "role": "metric",
                    "aggregate": "avg",
                    "field_ref": {
                        "semantic_entity": "dmt_liveability.fact_ic_scores",
                        "semantic_field": "streetlight_perc_existing",
                    },
                },
                {
                    "output_name": "post_pipeline_completion",
                    "role": "metric",
                    "aggregate": "avg",
                    "field_ref": {
                        "semantic_entity": "dmt_liveability.fact_ic_scores",
                        "semantic_field": "streetlight_perc_pipeline",
                    },
                },
            ],
            "filters": [
                {
                    "field_ref": {
                        "semantic_entity": "dmt_liveability.dim_districts",
                        "semantic_field": "name_en",
                    },
                    "operator": "eq",
                    "values": ["EXAMPLE DISTRICT"],
                }
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
        }
    )

    plan = build_compiled_ad_hoc_semantic_plan(
        semantic_ir=semantic_ir,
        source=SOURCE,
        semantic_version=semantic_layer["semantic_version"],
        semantic_layer=semantic_layer,
        max_rows=1000,
        question="Compare existing and post-pipeline streetlight completion for EXAMPLE DISTRICT.",
    )

    output_names = [item.output_name for item in plan.semantic_ir.projections]
    assert output_names == [
        "name_en",
        "municipality",
        "existing_completion",
        "post_pipeline_completion",
    ]
    assert "stage" in plan.compiler_removed_output_names
    assert "name_en" in plan.compiler_added_output_names
    assert "municipality" in plan.compiler_added_output_names
    assert "semantic_ir_removed_redundant_measure_dimension:stage" in (
        plan.compiler_semantic_filter_corrections
    )
    assert "GROUP BY gda_source" not in plan.compiled_statement


def test_compiler_preserves_reviewed_fixed_identity_for_aggregate_metric() -> None:
    """A named aggregate keeps its reviewed identity even when the model omits it."""

    semantic_layer = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "docs/customer/abu_dhabi_liveability_site_validation"
            / "liveability_data_20260730_semantic_layer_v57_multilingual_score_lexicon_20260915.json"
        ).read_text(encoding="utf-8")
    )
    semantic_layer["aggregate_identity_projection_policies"] = [
        {
            "policy_id": "liveability.district.fixed_aggregate_identity_v1",
            "review_status": "reviewed",
            "operation": "project_fixed_filtered_identity",
            "semantic_entity": "dmt_liveability.dim_districts",
            "physical_table": "public.dim_districts",
            "primary_label_field": "name_en",
            "output_name": "district_name",
            "requires_aggregate_metric": True,
            "allowed_filter_operators": ["eq", "in"],
            "max_filter_values": 1,
            "source_evidence": {
                "statement_sha256": "a" * 64,
                "benchmark_questions_used": False,
                "gold_sql_used": False,
                "gold_results_used": False,
                "model_outputs_used": False,
                "source_rows_persisted": False,
            },
        }
    ]
    semantic_ir = AdHocSemanticQueryIR.model_validate(
        {
            "language": "en",
            "status": "query",
            "semantic_entity": "dmt_liveability.fact_ic_scores",
            "projections": [
                {
                    "output_name": "existing_streetlight_completion",
                    "role": "metric",
                    "aggregate": "avg",
                    "field_ref": {
                        "semantic_entity": "dmt_liveability.fact_ic_scores",
                        "semantic_field": "streetlight_perc_existing",
                    },
                },
                {
                    "output_name": "post_pipeline_streetlight_completion",
                    "role": "metric",
                    "aggregate": "avg",
                    "field_ref": {
                        "semantic_entity": "dmt_liveability.fact_ic_scores",
                        "semantic_field": "streetlight_perc_pipeline",
                    },
                },
            ],
            "filters": [
                {
                    "field_ref": {
                        "semantic_entity": "dmt_liveability.dim_districts",
                        "semantic_field": "name_en",
                    },
                    "operator": "eq",
                    "values": ["EXAMPLE DISTRICT"],
                }
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
        }
    )

    plan = build_compiled_ad_hoc_semantic_plan(
        semantic_ir=semantic_ir,
        source=SOURCE,
        semantic_version=semantic_layer["semantic_version"],
        semantic_layer=semantic_layer,
        max_rows=1000,
        question=(
            "Compare existing and post-pipeline streetlight completion for "
            "EXAMPLE DISTRICT."
        ),
    )

    assert [item.output_name for item in plan.semantic_ir.projections] == [
        "district_name",
        "municipality",
        "existing_streetlight_completion",
        "post_pipeline_streetlight_completion",
    ]
    assert plan.compiler_added_output_names == ("district_name", "municipality")
    assert plan.compiler_projection_policy_applications == (
        "liveability.ic.streetlight_post_pipeline_cumulative_v1",
        "liveability.district.fixed_aggregate_identity_v1",
    )
    assert 'GROUP BY gda_join_001."name_en", gda_join_001."district_id", gda_join_001."municipality"' in plan.compiled_statement


def test_compiler_requires_field_identity_for_unprojected_single_enum_value() -> None:
    semantic_layer = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "docs/customer/abu_dhabi_liveability_site_validation"
            / "liveability_data_20260730_semantic_layer_v42_metric_execution_20260912.json"
        ).read_text(encoding="utf-8")
    )
    semantic_ir = AdHocSemanticQueryIR.model_validate(
        {
            "language": "en",
            "status": "query",
            "semantic_entity": "dmt_liveability.fact_ic_scores",
            "projections": [
                {
                    "output_name": "pipeline_completion",
                    "role": "metric",
                    "aggregate": "avg",
                    "field_ref": {
                        "semantic_entity": "dmt_liveability.fact_ic_scores",
                        "semantic_field": "streetlight_perc_pipeline",
                    },
                }
            ],
            "joins": [
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
        question="Show current post-pipeline streetlight completion.",
    )

    assert "current" not in plan.parameter_bindings.values()
    assert 'gda_join_001."status"' not in plan.compiled_statement
    assert not any(
        value.endswith("dim_calc_versions.status")
        for value in plan.compiler_semantic_filter_corrections
    )


def test_compiler_applies_reviewed_derived_projection_policy() -> None:
    semantic_layer = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "docs/customer/abu_dhabi_liveability_site_validation"
            / "liveability_data_20260730_semantic_layer_v42_metric_execution_20260912.json"
        ).read_text(encoding="utf-8")
    )
    semantic_layer["derived_projection_policies"] = [
        {
            "policy_id": "liveability.ic.streetlight_post_pipeline_cumulative_v1",
            "review_status": "reviewed",
            "operation": "replace_direct_projection_with_derived_expression",
            "match": {
                "required_term_groups": {
                    "en": [["streetlight"], ["existing"], ["post-pipeline", "after pipeline"]],
                    "zh": [["路灯"], ["现有"], ["在建完成后"]],
                    "ar": [["إنارة الشوارع"], ["القائم"], ["بعد التنفيذ"]],
                },
                "forbidden_terms": {"en": [], "zh": [], "ar": []},
            },
            "target_field_ref": {
                "semantic_entity": "dmt_liveability.fact_ic_scores",
                "semantic_field": "streetlight_perc_pipeline",
            },
            "operator": "add",
            "operand_field_refs": [
                {
                    "semantic_entity": "dmt_liveability.fact_ic_scores",
                    "semantic_field": "streetlight_perc_existing",
                },
                {
                    "semantic_entity": "dmt_liveability.fact_ic_scores",
                    "semantic_field": "streetlight_perc_pipeline",
                },
            ],
        }
    ]
    semantic_ir = AdHocSemanticQueryIR.model_validate(
        {
            "language": "en",
            "status": "query",
            "semantic_entity": "dmt_liveability.fact_ic_scores",
            "projections": [
                {
                    "output_name": "existing_completion",
                    "role": "metric",
                    "aggregate": "avg",
                    "field_ref": {
                        "semantic_entity": "dmt_liveability.fact_ic_scores",
                        "semantic_field": "streetlight_perc_existing",
                    },
                },
                {
                    "output_name": "post_pipeline_completion",
                    "role": "metric",
                    "aggregate": "avg",
                    "field_ref": {
                        "semantic_entity": "dmt_liveability.fact_ic_scores",
                        "semantic_field": "streetlight_perc_pipeline",
                    },
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
        question="Compare existing and post-pipeline streetlight completion.",
    )

    assert '(gda_source."streetlight_perc_existing" + gda_source."streetlight_perc_pipeline")' in plan.compiled_statement
    assert plan.semantic_ir.projections[1].derived_expression is not None
    assert plan.compiler_projection_policy_applications == (
        "liveability.ic.streetlight_post_pipeline_cumulative_v1",
    )


def test_compiler_exact_projection_policy_removes_unrequested_entity_fields() -> None:
    semantic_layer = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "docs/customer/abu_dhabi_liveability_site_validation"
            / "liveability_data_20260730_semantic_layer_v42_metric_execution_20260912.json"
        ).read_text(encoding="utf-8")
    )
    policy = next(
        item
        for item in semantic_layer["projection_completeness_policies"]
        if item["policy_id"] == "liveability.facility_provision.target_gap_detail_v1"
    )
    policy["projection_mode"] = "exact_on_selected_entity"
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
                    "output_name": "current_gap",
                    "role": "attribute",
                    "field_ref": {
                        "semantic_entity": "dmt_liveability.fact_facility_provision",
                        "semantic_field": "needed_current",
                    },
                },
                {
                    "output_name": "demand_current",
                    "role": "dimension",
                    "field_ref": {
                        "semantic_entity": "dmt_liveability.fact_facility_provision",
                        "semantic_field": "demand_current",
                    },
                },
            ],
            "filters": [
                {
                    "field_ref": {
                        "semantic_entity": "dmt_liveability.fact_facility_provision",
                        "semantic_field": "subcategory_name",
                    },
                    "operator": "eq",
                    "values": ["Library"],
                },
                {
                    "field_ref": {
                        "semantic_entity": "dmt_liveability.fact_facility_provision",
                        "semantic_field": "needed_ap50",
                    },
                    "operator": "gt",
                    "values": [0],
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
        question="Which districts still need libraries to reach the 50% target (needed>0)?",
    )

    output_names = [item.output_name for item in plan.semantic_ir.projections]
    assert output_names == [
        "district_name",
        "municipality",
        "existing_count",
        "pipeline_count",
        "target_50pct",
        "needed_ap50",
    ]
    assert set(plan.compiler_removed_output_names) == {"current_gap", "demand_current"}
    assert plan.compiler_projection_policy_applications == (
        "liveability.facility_provision.target_gap_detail_v1",
    )


def test_compiler_retains_reviewed_identity_for_exact_detail_filter() -> None:
    """A fixed entity detail result stays identifiable without prompt-specific repair."""

    semantic_layer = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "docs/customer/abu_dhabi_liveability_site_validation"
            / "liveability_data_20260730_semantic_layer_v59_cross_stage_comparison_20260915.json"
        ).read_text(encoding="utf-8")
    )
    semantic_layer["detail_identity_projection_policies"] = [
        {
            "policy_id": "test.district.exact_detail_identity_v1",
            "review_status": "reviewed",
            "operation": "project_exact_filtered_detail_identity",
            "requires_non_aggregate_detail": True,
            "semantic_entity": "dmt_liveability.dim_districts",
            "physical_table": "public.dim_districts",
            "primary_label_field": "name_en",
            "allowed_filter_operators": ["eq", "in"],
            "max_filter_values": 1,
            "required_fields": [
                {
                    "semantic_field": "name_en",
                    "output_name": "district_name",
                    "role": "dimension",
                },
                {
                    "semantic_field": "municipality",
                    "output_name": "municipality",
                    "role": "dimension",
                },
            ],
            "source_evidence": {
                "statement_sha256": "a" * 64,
                "benchmark_questions_used": False,
                "gold_sql_used": False,
                "gold_results_used": False,
                "model_outputs_used": False,
                "source_rows_persisted": False,
            },
        }
    ]
    semantic_ir = AdHocSemanticQueryIR.model_validate(
        {
            "language": "en",
            "status": "query",
            "semantic_entity": "dmt_liveability.fact_district_scores",
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
                    "output_name": "social_score",
                    "role": "attribute",
                    "field_ref": {
                        "semantic_entity": "dmt_liveability.fact_district_scores",
                        "semantic_field": "social_score",
                    },
                }
            ],
            "filters": [
                {
                    "field_ref": {
                        "semantic_entity": "dmt_liveability.dim_districts",
                        "semantic_field": "name_en",
                    },
                    "operator": "eq",
                    "values": ["A SELECTED DISTRICT"],
                },
                {
                    "field_ref": {
                        "semantic_entity": "dmt_liveability.fact_district_scores",
                        "semantic_field": "stage",
                    },
                    "operator": "eq",
                    "values": ["Existing"],
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
        source=SOURCE,
        semantic_version=semantic_layer["semantic_version"],
        semantic_layer=semantic_layer,
        max_rows=1000,
        question="List all domain scores for a selected district in the existing stage.",
    )

    output_names = [item.output_name for item in plan.semantic_ir.projections]
    assert output_names[:2] == ["district_name", "municipality"]
    assert plan.compiler_added_output_names == (
        "environment_score",
        "built_environment_score",
        "safety_security_score",
        "culture_literature_score",
        "education_score",
        "health_wellbeing_score",
        "infrastructure_score",
        "leisure_entertainment_score",
        "social_infrastructure_score",
        "sports_recreation_score",
        "transport_score",
        "municipality",
    )
    assert set(
        [
            "social_score",
            "environment_score",
            "built_environment_score",
            "safety_security_score",
            "culture_literature_score",
            "education_score",
            "health_wellbeing_score",
            "infrastructure_score",
            "leisure_entertainment_score",
            "social_infrastructure_score",
            "sports_recreation_score",
            "transport_score",
        ]
    ) <= set(output_names)
    assert plan.compiler_projection_policy_applications == (
        "test.district.exact_detail_identity_v1",
        "liveability.domain_scores.complete_v1",
    )
    assert 'gda_join_001."name_en" AS "district_name"' in plan.compiled_statement
    assert 'gda_join_001."municipality" AS "municipality"' in plan.compiled_statement

    unfixed_ir = semantic_ir.model_copy(
        update={
            "projections": (semantic_ir.projections[1],),
            "filters": (
                semantic_ir.filters[0].model_copy(
                    update={
                        "operator": "in",
                        "values": ("FIRST DISTRICT", "SECOND DISTRICT"),
                    }
                ),
                semantic_ir.filters[1],
            )
        }
    )
    unfixed_plan = build_compiled_ad_hoc_semantic_plan(
        semantic_ir=unfixed_ir,
        source=SOURCE,
        semantic_version=semantic_layer["semantic_version"],
        semantic_layer=semantic_layer,
        max_rows=1000,
        question="Show the social score for two selected districts in the existing stage.",
    )
    assert "district_name" not in [
        item.output_name for item in unfixed_plan.semantic_ir.projections
    ]
    assert "test.district.exact_detail_identity_v1" not in (
        unfixed_plan.compiler_projection_policy_applications
    )


def test_compiler_repairs_aggregate_role_before_complete_detail_collection() -> None:
    semantic_layer = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "docs/customer/abu_dhabi_liveability_site_validation"
            / "liveability_data_20260730_semantic_layer_v59_cross_stage_comparison_20260915.json"
        ).read_text(encoding="utf-8")
    )
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
                    "output_name": "social_score",
                    "role": "metric",
                    "field_ref": {
                        "semantic_entity": "dmt_liveability.fact_district_scores",
                        "semantic_field": "social_score",
                    },
                    "aggregate": "avg",
                },
            ],
            "filters": [
                {
                    "field_ref": {
                        "semantic_entity": "dmt_liveability.dim_districts",
                        "semantic_field": "name_en",
                    },
                    "operator": "eq",
                    "values": ["A SELECTED DISTRICT"],
                },
                {
                    "field_ref": {
                        "semantic_entity": "dmt_liveability.fact_district_scores",
                        "semantic_field": "stage",
                    },
                    "operator": "eq",
                    "values": ["Existing"],
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
        source=SOURCE,
        semantic_version=semantic_layer["semantic_version"],
        semantic_layer=semantic_layer,
        max_rows=1000,
        question="List all domain scores for a selected district in the existing stage.",
    )

    projections = {item.output_name: item for item in plan.semantic_ir.projections}
    assert projections["social_score"].aggregate is None
    assert projections["social_score"].role.value == "attribute"
    assert "environment_score" in projections
    assert "transport_score" in projections
    assert "AVG(" not in plan.compiled_statement
    assert "liveability.domain_scores.complete_v1" in (
        plan.compiler_projection_policy_applications
    )


def test_compiler_promotes_unambiguous_per_group_top_n_to_partitioned_ranking() -> None:
    semantic_layer = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "docs/customer/abu_dhabi_liveability_site_validation"
            / "liveability_data_20260730_semantic_layer_v41_detail_grain_contracts_20260911.json"
        ).read_text(encoding="utf-8")
    )
    semantic_ir = AdHocSemanticQueryIR.model_validate(
        {
            "language": "en",
            "status": "query",
            "semantic_entity": "dmt_liveability.fact_district_scores",
            "projections": [
                {
                    "output_name": "settlement_context",
                    "role": "dimension",
                    "field_ref": {
                        "semantic_entity": "dmt_liveability.dim_districts",
                        "semantic_field": "classification",
                    },
                },
                {
                    "output_name": "district_name",
                    "role": "dimension",
                    "field_ref": {
                        "semantic_entity": "dmt_liveability.dim_districts",
                        "semantic_field": "name_en",
                    },
                },
                {
                    "output_name": "score",
                    "role": "metric",
                    "aggregate": "avg",
                    "field_ref": {
                        "semantic_entity": "dmt_liveability.fact_district_scores",
                        "semantic_field": "overall_score",
                    },
                },
            ],
            "filters": [
                {
                    "field_ref": {
                        "semantic_entity": "dmt_liveability.fact_district_scores",
                        "semantic_field": "stage",
                    },
                    "operator": "eq",
                    "values": ["Existing"],
                },
                {
                    "field_ref": {
                        "semantic_entity": "dmt_liveability.dim_districts",
                        "semantic_field": "classification",
                    },
                    "operator": "in",
                    "values": ["urban", "suburban", "rural"],
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
            "order_by": [{"output_name": "score", "direction": "desc"}],
            "limit": 3,
        }
    )

    plan = build_compiled_ad_hoc_semantic_plan(
        semantic_ir=semantic_ir,
        source=SOURCE,
        semantic_version=semantic_layer["semantic_version"],
        semantic_layer=semantic_layer,
        max_rows=1000,
        question=(
            "For each Urban, Suburban, and Rural settlement context, which three "
            "districts have the highest Existing-stage scores?"
        ),
    )

    assert plan.semantic_ir.partition_by == ("settlement_context",)
    assert plan.semantic_ir.partition_limit == 3
    assert plan.semantic_ir.limit is None
    assert "ROW_NUMBER() OVER" in plan.compiled_statement
    assert "PARTITION BY \"settlement_context\"" in plan.compiled_statement
    assert "semantic_ir_promoted_unambiguous_partitioned_ranking" in (
        plan.compiler_semantic_filter_corrections
    )


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


def test_numeric_target_alias_rebinds_sibling_measure_without_changing_dimension_filter() -> None:
    """A reviewed 50% alias selects the target-gap measure, not current gap."""

    semantic_layer = _liveability_v41_semantic_layer()
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
                    "output_name": "gap",
                    "role": "metric",
                    "aggregate": "sum",
                    "field_ref": {
                        "semantic_entity": "dmt_liveability.fact_facility_provision",
                        "semantic_field": "needed_current",
                    },
                },
            ],
            "filters": [
                {
                    "field_ref": {
                        "semantic_entity": "dmt_liveability.fact_facility_provision",
                        "semantic_field": "subcategory_name",
                    },
                    "operator": "eq",
                    "values": ["Library"],
                },
                {
                    "field_ref": {
                        "semantic_entity": "dmt_liveability.fact_facility_provision",
                        "semantic_field": "needed_current",
                    },
                    "operator": "gt",
                    "values": [0],
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
        question="Which districts still need libraries to reach the 50% target (needed>0)?",
    )
    assert '"needed_ap50"' in plan.compiled_statement
    assert '"subcategory_name"' in plan.compiled_statement
    assert 0 in plan.parameter_bindings.values()


def test_compound_measure_filters_keep_existing_and_target_need_distinct() -> None:
    """Clause-local reviewed labels prevent one numeric alias from swallowing another."""

    semantic_layer = _liveability_v41_semantic_layer()
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
                    "output_name": "target_need",
                    "role": "attribute",
                    "field_ref": {
                        "semantic_entity": "dmt_liveability.fact_facility_provision",
                        "semantic_field": "needed_ap50",
                    },
                },
            ],
            "filters": [
                {
                    "field_ref": {
                        "semantic_entity": "dmt_liveability.fact_facility_provision",
                        "semantic_field": "subcategory_name",
                    },
                    "operator": "eq",
                    "values": ["Neighbourhood_Majlis"],
                },
                {
                    "field_ref": {
                        "semantic_entity": "dmt_liveability.fact_facility_provision",
                        "semantic_field": "needed_ap50",
                    },
                    "operator": "eq",
                    "values": [0],
                },
                {
                    "field_ref": {
                        "semantic_entity": "dmt_liveability.fact_facility_provision",
                        "semantic_field": "needed_ap50",
                    },
                    "operator": "gt",
                    "values": [0],
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
        question="Which districts have zero existing neighbourhood majlis but a positive 50% target need?",
    )
    # The first numeric predicate is the reviewed existing-count measure; the
    # second remains the reviewed AP50 target-gap measure.
    assert '"existing_count" = :gda_p_002' in plan.compiled_statement
    assert '"needed_ap50" > :gda_p_003' in plan.compiled_statement


def test_universal_upper_bound_drops_redundant_average_having() -> None:
    semantic_layer = _liveability_v41_semantic_layer()
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
                    "output_name": "score",
                    "role": "metric",
                    "aggregate": "avg",
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
                    "aggregate": "avg",
                    "operator": "eq",
                    "values": [100],
                }
            ],
            "universal_conditions": [
                {
                    "policy_id": "liveability.fpp.assessed_district_universal_v1",
                    "field_ref": {
                        "semantic_entity": "dmt_liveability.fact_facility_provision",
                        "semantic_field": "kpi_existing",
                    },
                    "operator": "gte",
                    "values": [100],
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
        question="Which Main Category facility types have an FPP score of 100% in every assessed district?",
    )
    assert "semantic_universal_query_grouping_control_conflict" not in plan.compiled_statement
    assert "gda_universal_target_001" in plan.compiled_statement


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


def _liveability_two_value_comparison_semantic_layer() -> dict:
    root = Path(__file__).resolve().parents[1]
    semantic = json.loads(
        (
            root
            / "docs/customer/abu_dhabi_liveability_site_validation"
            / "liveability_data_20260730_semantic_layer_v58_aggregate_identity_projection_20260915.json"
        ).read_text(encoding="utf-8")
    )
    fact = "dmt_liveability.fact_district_scores"
    districts = "dmt_liveability.dim_districts"
    semantic["two_value_comparison_policies"] = [
        {
            "policy_id": "liveability.district_score.cross_stage_delta.v1",
            "review_status": "reviewed",
            "operation": "same_entity_two_value_subtract",
            "aggregate": "max",
            "semantic_entity": fact,
            "physical_table": "public.fact_district_scores",
            "scope_field_ref": {"semantic_entity": fact, "semantic_field": "stage"},
            "measure_field_ref": {"semantic_entity": fact, "semantic_field": "overall_score"},
            "pairing_field_ref": {"semantic_entity": fact, "semantic_field": "district_id"},
            "allowed_scope_values": ["Existing", "Pipeline", "AP50"],
            "required_join": {
                "left_field_ref": {"semantic_entity": fact, "semantic_field": "district_id"},
                "right_field_ref": {"semantic_entity": districts, "semantic_field": "district_id"},
                "kind": "equality",
                "operator": "eq",
            },
            "required_dimension_field_refs": [
                {"semantic_entity": districts, "semantic_field": "name_en"},
                {"semantic_entity": districts, "semantic_field": "municipality"},
            ],
            "map_binding": {
                "semantic_entity": districts,
                "geometry_field_ref": {"semantic_entity": districts, "semantic_field": "geom"},
                "key_field_refs": [
                    {"semantic_entity": districts, "semantic_field": "name_en"},
                    {"semantic_entity": districts, "semantic_field": "municipality"},
                ],
                "metric_labels": {"en": "liveability score improvement"},
            },
            "source_evidence": {
                "statement_sha256": "a" * 64,
                "benchmark_questions_used": False,
                "gold_sql_used": False,
                "gold_results_used": False,
                "model_outputs_used": False,
                "source_rows_persisted": False,
            },
        }
    ]
    return semantic


def _two_value_comparison_ir(
    *,
    baseline: str = "Existing",
    include_municipality: bool = True,
    district_label: bool = True,
) -> AdHocSemanticQueryIR:
    fact = "dmt_liveability.fact_district_scores"
    districts = "dmt_liveability.dim_districts"
    projections = [
        {
            "output_name": "district_name" if district_label else "district_classification",
            "role": "dimension",
            "field_ref": {
                "semantic_entity": districts,
                "semantic_field": "name_en" if district_label else "classification",
            },
        }
    ]
    if include_municipality:
        projections.append(
            {
                "output_name": "municipality",
                "role": "dimension",
                "field_ref": {"semantic_entity": districts, "semantic_field": "municipality"},
            }
        )
    return AdHocSemanticQueryIR.model_validate(
        {
            "language": "en",
            "status": "query",
            "semantic_entity": fact,
            "projections": projections,
            "joins": [
                {
                    "left_field_ref": {"semantic_entity": fact, "semantic_field": "district_id"},
                    "right_field_ref": {"semantic_entity": districts, "semantic_field": "district_id"},
                    "kind": "equality",
                    "operator": "eq",
                }
            ],
            "two_value_comparison": {
                "policy_id": "liveability.district_score.cross_stage_delta.v1",
                "scope_field_ref": {"semantic_entity": fact, "semantic_field": "stage"},
                "measure_field_ref": {"semantic_entity": fact, "semantic_field": "overall_score"},
                "baseline_value": baseline,
                "comparison_value": "AP50",
                "baseline_output_name": "existing_score",
                "comparison_output_name": "ap50_score",
                "difference_output_name": "improvement_points",
            },
            "order_by": [{"output_name": "improvement_points", "direction": "desc"}],
            "limit": 15,
        }
    )


def test_two_value_comparison_compiles_governed_conditional_aggregate() -> None:
    semantic = _liveability_two_value_comparison_semantic_layer()
    plan = build_compiled_ad_hoc_semantic_plan(
        semantic_ir=_two_value_comparison_ir(),
        source=SOURCE,
        semantic_version=semantic["semantic_version"],
        semantic_layer=semantic,
        max_rows=1000,
        question="Show the 15 districts with the greatest AP50 minus Existing overall liveability score improvement.",
    )
    sql = plan.compiled_statement
    assert "MAX(gda_source.\"overall_score\") FILTER (WHERE gda_source.\"stage\" = :gda_two_value_baseline_001)" in sql
    assert "MAX(gda_source.\"overall_score\") FILTER (WHERE gda_source.\"stage\" = :gda_two_value_comparison_001)" in sql
    assert "AS \"improvement_points\"" in sql
    assert "SELF JOIN" not in sql.upper()
    assert plan.parameter_bindings["gda_two_value_baseline_001"] == "Existing"
    assert plan.parameter_bindings["gda_two_value_comparison_001"] == "AP50"
    assert "public.fact_district_scores.overall_score" in plan.physical_plan.columns
    aggregate_node = next(node for node in plan.logical_plan.nodes if node.operator == "aggregate")
    assert aggregate_node.attributes["two_value_comparison"]["policy_id"] == (
        "liveability.district_score.cross_stage_delta.v1"
    )


def test_two_value_comparison_supports_group_average_filter_and_partition_rank() -> None:
    semantic = _liveability_two_value_comparison_semantic_layer()
    base = _two_value_comparison_ir()
    semantic_ir = AdHocSemanticQueryIR.model_validate(
        {
            **base.model_dump(mode="python"),
            "group_average_filter": {
                "value_output_name": "ap50_score",
                "partition_by": ["municipality"],
                "operator": "gt",
                "average_output_name": "municipality_ap50_average",
            },
            "partition_by": ["municipality"],
            "partition_limit": 3,
            "partition_rank_output_name": "municipality_rank",
            "limit": None,
        }
    )

    plan = build_compiled_ad_hoc_semantic_plan(
        semantic_ir=semantic_ir,
        source=SOURCE,
        semantic_version=semantic["semantic_version"],
        semantic_layer=semantic,
        max_rows=1000,
        question=(
            "For each municipality, show the top 3 districts whose AP50 score is "
            "above the municipality AP50 average, ranked by AP50 minus Existing."
        ),
    )

    sql = plan.compiled_statement
    assert 'AVG("ap50_score") OVER (PARTITION BY "municipality")' in sql
    assert 'WHERE "ap50_score" > "municipality_ap50_average"' in sql
    assert (
        'ROW_NUMBER() OVER (PARTITION BY "municipality" ORDER BY '
        '"improvement_points" DESC NULLS LAST, "district_name" ASC NULLS LAST)'
        in sql
    )
    assert 'gda_partition_rank AS "municipality_rank"' in sql
    assert "WHERE gda_partition_rank <= 3" in sql
    assert [
        item
        for item in plan.logical_plan.nodes
        if item.operator == "window"
    ][0].attributes["operation"] == "partition_average_filter"
    project_node = next(
        item for item in plan.logical_plan.nodes if item.operator == "project"
    )
    assert project_node.attributes["outputs"][-2:] == [
        "municipality_ap50_average",
        "municipality_rank",
    ]


def test_two_value_comparison_supports_safe_rate_multiple_group_averages_and_partition_rank() -> None:
    semantic = _liveability_two_value_comparison_semantic_layer()
    base = _two_value_comparison_ir()
    semantic_ir = AdHocSemanticQueryIR.model_validate(
        {
            **base.model_dump(mode="python"),
            "result_expressions": [
                {
                    "output_name": "improvement_rate_pct",
                    "operator": "divide",
                    "operands": ["improvement_points", "existing_score"],
                    "scale": 100,
                }
            ],
            "group_average_filters": [
                {
                    "value_output_name": "improvement_rate_pct",
                    "partition_by": ["municipality"],
                    "operator": "gt",
                    "average_output_name": "municipality_improvement_rate_average",
                },
                {
                    "value_output_name": "ap50_score",
                    "partition_by": ["municipality"],
                    "operator": "gt",
                    "average_output_name": "municipality_ap50_average",
                },
            ],
            "order_by": [
                {"output_name": "improvement_rate_pct", "direction": "desc"}
            ],
            "partition_by": ["municipality"],
            "partition_limit": 2,
            "partition_rank_output_name": "municipality_rank",
            "limit": None,
        }
    )

    plan = build_compiled_ad_hoc_semantic_plan(
        semantic_ir=semantic_ir,
        source=SOURCE,
        semantic_version=semantic["semantic_version"],
        semantic_layer=semantic,
        max_rows=1000,
        question=(
            "For each municipality, show the top 2 districts whose AP50 score is above "
            "the municipality AP50 average and whose percentage improvement, defined as "
            "(AP50 minus Existing) divided by Existing times 100, is above the municipality average."
        ),
    )

    sql = plan.compiled_statement
    assert (
        '("improvement_points"::double precision / '
        'NULLIF("existing_score"::double precision, 0.0)) * 100'
    ) in sql
    assert 'AS "improvement_rate_pct"' in sql
    assert (
        'AVG("improvement_rate_pct") OVER (PARTITION BY "municipality") '
        'AS "municipality_improvement_rate_average"'
    ) in sql
    assert (
        'AVG("ap50_score") OVER (PARTITION BY "municipality") '
        'AS "municipality_ap50_average"'
    ) in sql
    assert (
        'WHERE "improvement_rate_pct" > "municipality_improvement_rate_average" '
        'AND "ap50_score" > "municipality_ap50_average"'
    ) in sql
    assert (
        'ROW_NUMBER() OVER (PARTITION BY "municipality" ORDER BY '
        '"improvement_rate_pct" DESC NULLS LAST, "district_name" ASC NULLS LAST)'
    ) in sql
    assert 'WHERE gda_partition_rank <= 2' in sql
    expression_node = next(
        item for item in plan.logical_plan.nodes if item.node_id == "result_expression_001"
    )
    assert expression_node.attributes["expressions"][0]["zero_division"] == "null"
    average_node = next(
        item for item in plan.logical_plan.nodes if item.node_id == "window_average_001"
    )
    assert len(average_node.attributes["filters"]) == 2


def test_two_value_comparison_supports_partition_contribution_and_cumulative_threshold() -> None:
    semantic = _liveability_two_value_comparison_semantic_layer()
    base = _two_value_comparison_ir()
    semantic_ir = AdHocSemanticQueryIR.model_validate(
        {
            **base.model_dump(mode="python"),
            "result_expressions": [
                {
                    "output_name": "improvement_rate_pct",
                    "operator": "divide",
                    "operands": ["improvement_points", "existing_score"],
                    "scale": 100,
                }
            ],
            "partition_statistics": [
                {
                    "value_output_name": "improvement_points",
                    "partition_by": ["municipality"],
                    "aggregate": "sum",
                    "output_name": "municipality_positive_improvement_total",
                    "value_filter_operator": "gt",
                    "value_filter_value": 0,
                },
                {
                    "value_output_name": "ap50_score",
                    "partition_by": ["municipality"],
                    "aggregate": "average",
                    "output_name": "municipality_ap50_average",
                },
            ],
            "post_statistic_expressions": [
                {
                    "output_name": "contribution_rate_pct",
                    "operator": "divide",
                    "operands": [
                        "improvement_points",
                        "municipality_positive_improvement_total",
                    ],
                    "scale": 100,
                }
            ],
            "result_filters": [
                {
                    "left_output_name": "improvement_points",
                    "operator": "gt",
                    "values": [0],
                },
                {
                    "left_output_name": "ap50_score",
                    "operator": "gt",
                    "right_output_name": "municipality_ap50_average",
                },
            ],
            "order_by": [
                {"output_name": "contribution_rate_pct", "direction": "desc"}
            ],
            "partition_by": ["municipality"],
            "partition_limit": None,
            "partition_rank_output_name": "municipality_rank",
            "cumulative_windows": [
                {
                    "value_output_name": "contribution_rate_pct",
                    "partition_by": ["municipality"],
                    "order_by": [
                        {"output_name": "contribution_rate_pct", "direction": "desc"}
                    ],
                    "output_name": "cumulative_contribution_rate_pct",
                }
            ],
            "post_window_filters": [
                {
                    "left_output_name": "cumulative_contribution_rate_pct",
                    "operator": "lte",
                    "values": [60],
                }
            ],
            "limit": None,
        }
    )

    plan = build_compiled_ad_hoc_semantic_plan(
        semantic_ir=semantic_ir,
        source=SOURCE,
        semantic_version=semantic["semantic_version"],
        semantic_layer=semantic,
        max_rows=1000,
        question=(
            "Within each municipality, show districts with positive Existing-to-AP50 "
            "improvement and AP50 above the municipality average. Calculate each "
            "district's percentage improvement and contribution to the municipality's "
            "positive improvement total, rank by contribution, and keep cumulative "
            "contribution at or below 60%."
        ),
    )

    sql = plan.compiled_statement
    assert (
        'SUM("improvement_points") FILTER (WHERE "improvement_points" > '
        ':gda_partition_stat_001) OVER (PARTITION BY "municipality") AS '
        '"municipality_positive_improvement_total"'
    ) in sql
    assert (
        'AVG("ap50_score") OVER (PARTITION BY "municipality") AS '
        '"municipality_ap50_average"'
    ) in sql
    assert (
        '("improvement_points"::double precision / NULLIF('
        '"municipality_positive_improvement_total"::double precision, 0.0)) * 100'
    ) in sql
    assert (
        'WHERE "improvement_points" > :gda_result_filter_001 '
        'AND "ap50_score" > "municipality_ap50_average"'
    ) in sql
    assert sql.index('AS "municipality_positive_improvement_total"') < sql.index(
        'WHERE "improvement_points" > :gda_result_filter_001'
    )
    assert (
        'ROW_NUMBER() OVER (PARTITION BY "municipality" ORDER BY '
        '"contribution_rate_pct" DESC NULLS LAST, "district_name" ASC NULLS LAST)'
    ) in sql
    assert (
        'SUM("contribution_rate_pct") OVER (PARTITION BY "municipality" ORDER BY '
        '"contribution_rate_pct" DESC NULLS LAST, "district_name" ASC NULLS LAST '
        'ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS '
        '"cumulative_contribution_rate_pct"'
    ) in sql
    assert (
        'WHERE "cumulative_contribution_rate_pct" <= '
        ':gda_post_window_filter_001'
    ) in sql
    assert "gda_partition_rank <=" not in sql
    assert plan.parameter_bindings["gda_partition_stat_001"] == 0
    assert plan.parameter_bindings["gda_result_filter_001"] == 0
    assert plan.parameter_bindings["gda_post_window_filter_001"] == 60
    statistic_node = next(
        item for item in plan.logical_plan.nodes if item.node_id == "window_statistic_001"
    )
    assert statistic_node.attributes["operation"] == "partition_statistics"
    cumulative_node = next(
        item for item in plan.logical_plan.nodes if item.node_id == "window_001"
    )
    assert cumulative_node.attributes["partition_limit"] is None
    assert cumulative_node.attributes["cumulative_windows"][0]["frame"] == (
        "rows_unbounded_preceding_to_current_row"
    )


def test_categorical_pivot_supports_three_stage_acceleration_percentile_and_pareto() -> None:
    semantic = _liveability_two_value_comparison_semantic_layer()
    base = _two_value_comparison_ir().model_dump(mode="python")
    base.pop("two_value_comparison")
    semantic_ir = AdHocSemanticQueryIR.model_validate(
        {
            **base,
            "order_by": [{"output_name": "ap50_score", "direction": "desc"}],
            "categorical_pivot": {
                "policy_id": "liveability.district_score.cross_stage_delta.v1",
                "scope_field_ref": {
                    "semantic_entity": "dmt_liveability.fact_district_scores",
                    "semantic_field": "stage",
                },
                "measure_field_ref": {
                    "semantic_entity": "dmt_liveability.fact_district_scores",
                    "semantic_field": "overall_score",
                },
                "values": [
                    {"value": "Existing", "output_name": "existing_score"},
                    {"value": "Pipeline", "output_name": "pipeline_score"},
                    {"value": "AP50", "output_name": "ap50_score"},
                ],
            },
            "result_expressions": [
                {
                    "output_name": "existing_to_pipeline_gain",
                    "operator": "subtract",
                    "operands": ["pipeline_score", "existing_score"],
                },
                {
                    "output_name": "pipeline_to_ap50_gain",
                    "operator": "subtract",
                    "operands": ["ap50_score", "pipeline_score"],
                },
                {
                    "output_name": "improvement_acceleration",
                    "operator": "subtract",
                    "operands": [
                        "pipeline_to_ap50_gain",
                        "existing_to_pipeline_gain",
                    ],
                },
            ],
            "partition_statistics": [
                {
                    "value_output_name": "ap50_score",
                    "partition_by": ["municipality"],
                    "aggregate": "percentile",
                    "percentile": 0.75,
                    "output_name": "municipality_ap50_p75",
                },
                {
                    "value_output_name": "improvement_acceleration",
                    "partition_by": ["municipality"],
                    "aggregate": "average",
                    "output_name": "municipality_average_acceleration",
                },
                {
                    "value_output_name": "improvement_acceleration",
                    "partition_by": ["municipality"],
                    "aggregate": "sum",
                    "output_name": "municipality_positive_acceleration_total",
                    "value_filter_operator": "gt",
                    "value_filter_value": 0,
                },
            ],
            "post_statistic_expressions": [
                {
                    "output_name": "acceleration_contribution_rate",
                    "operator": "divide",
                    "operands": [
                        "improvement_acceleration",
                        "municipality_positive_acceleration_total",
                    ],
                    "scale": 100,
                }
            ],
            "result_filters": [
                {
                    "left_output_name": "existing_to_pipeline_gain",
                    "operator": "gt",
                    "values": [0],
                },
                {
                    "left_output_name": "pipeline_to_ap50_gain",
                    "operator": "gt",
                    "values": [0],
                },
                {
                    "left_output_name": "ap50_score",
                    "operator": "gt",
                    "right_output_name": "municipality_ap50_p75",
                },
                {
                    "left_output_name": "improvement_acceleration",
                    "operator": "gt",
                    "values": [0],
                },
                {
                    "left_output_name": "improvement_acceleration",
                    "operator": "gt",
                    "right_output_name": "municipality_average_acceleration",
                },
            ],
            "order_by": [
                {"output_name": "acceleration_contribution_rate", "direction": "desc"}
            ],
            "partition_by": ["municipality"],
            "partition_limit": None,
            "partition_rank_output_name": "municipality_rank",
            "cumulative_windows": [
                {
                    "value_output_name": "acceleration_contribution_rate",
                    "partition_by": ["municipality"],
                    "order_by": [
                        {
                            "output_name": "acceleration_contribution_rate",
                            "direction": "desc",
                        }
                    ],
                    "output_name": "cumulative_contribution_rate",
                }
            ],
            "post_window_filters": [
                {
                    "left_output_name": "cumulative_contribution_rate",
                    "operator": "lte",
                    "values": [70],
                }
            ],
            "map_value_output_name": "improvement_acceleration",
            "limit": None,
        }
    )

    plan = build_compiled_ad_hoc_semantic_plan(
        semantic_ir=semantic_ir,
        source=SOURCE,
        semantic_version=semantic["semantic_version"],
        semantic_layer=semantic,
        max_rows=1000,
        question=(
            "Show districts with positive gains across Existing, Pipeline, and AP50, "
            "AP50 above the municipality 75th percentile, and positive acceleration "
            "above the municipality average; rank contribution and keep cumulative 70%."
        ),
    )

    sql = plan.compiled_statement
    assert sql.count("MAX(gda_source.\"overall_score\") FILTER") == 3
    assert 'AS "existing_score"' in sql
    assert 'AS "pipeline_score"' in sql
    assert 'AS "ap50_score"' in sql
    assert '("pipeline_score" - "existing_score") AS "existing_to_pipeline_gain"' in sql
    assert '("ap50_score" - "pipeline_score") AS "pipeline_to_ap50_gain"' in sql
    assert (
        '("pipeline_to_ap50_gain" - "existing_to_pipeline_gain") '
        'AS "improvement_acceleration"'
    ) in sql
    assert "PERCENTILE_CONT(:gda_partition_percentile_001) WITHIN GROUP" in sql
    assert 'SUM("improvement_acceleration") FILTER' in sql
    assert 'ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW' in sql
    assert plan.parameter_bindings["gda_categorical_pivot_001"] == "Existing"
    assert plan.parameter_bindings["gda_categorical_pivot_002"] == "Pipeline"
    assert plan.parameter_bindings["gda_categorical_pivot_003"] == "AP50"
    assert plan.parameter_bindings["gda_partition_percentile_001"] == 0.75
    assert plan.parameter_bindings["gda_post_window_filter_001"] == 70


def test_categorical_pivot_rejects_unpublished_scope_value() -> None:
    semantic = _liveability_two_value_comparison_semantic_layer()
    base = _two_value_comparison_ir().model_dump(mode="python")
    base.pop("two_value_comparison")
    semantic_ir = AdHocSemanticQueryIR.model_validate(
        {
            **base,
            "order_by": [{"output_name": "ap50_score", "direction": "desc"}],
            "categorical_pivot": {
                "policy_id": "liveability.district_score.cross_stage_delta.v1",
                "scope_field_ref": {
                    "semantic_entity": "dmt_liveability.fact_district_scores",
                    "semantic_field": "stage",
                },
                "measure_field_ref": {
                    "semantic_entity": "dmt_liveability.fact_district_scores",
                    "semantic_field": "overall_score",
                },
                "values": [
                    {"value": "Existing", "output_name": "existing_score"},
                    {"value": "AP25", "output_name": "ap25_score"},
                    {"value": "AP50", "output_name": "ap50_score"},
                ],
            },
        }
    )

    with pytest.raises(
        SemanticIRCompilationError,
        match="semantic_categorical_pivot_scope_value_unsupported",
    ):
        build_compiled_ad_hoc_semantic_plan(
            semantic_ir=semantic_ir,
            source=SOURCE,
            semantic_version=semantic["semantic_version"],
            semantic_layer=semantic,
            max_rows=1000,
            question="Compare Existing, AP25, and AP50 scores.",
        )


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        (
            {
                "partition_statistics": [
                    {
                        "value_output_name": "district_name",
                        "partition_by": ["municipality"],
                        "aggregate": "sum",
                        "output_name": "bad_total",
                    }
                ]
            },
            "partition statistic requires a projected metric output",
        ),
        (
            {
                "result_filters": [
                    {
                        "left_output_name": "missing_metric",
                        "operator": "gt",
                        "values": [0],
                    }
                ]
            },
            "result filter left alias must reference a numeric output",
        ),
        (
            {
                "cumulative_windows": [
                    {
                        "value_output_name": "improvement_points",
                        "partition_by": ["municipality"],
                        "order_by": [
                            {"output_name": "missing_order", "direction": "desc"}
                        ],
                        "output_name": "running_total",
                    }
                ]
            },
            "cumulative window requires projected numeric and order outputs",
        ),
    ],
)
def test_partition_result_controls_reject_ungoverned_aliases(overrides, reason) -> None:
    base = _two_value_comparison_ir()
    with pytest.raises(ValueError, match=reason):
        AdHocSemanticQueryIR.model_validate(
            {**base.model_dump(mode="python"), **overrides}
        )


@pytest.mark.parametrize(
    ("group_average_filter", "reason"),
    [
        (
            {
                "value_output_name": "district_name",
                "partition_by": ["municipality"],
                "operator": "gt",
                "average_output_name": "municipality_average",
            },
            "group average filter requires a projected metric output",
        ),
        (
            {
                "value_output_name": "ap50_score",
                "partition_by": ["district_name"],
                "operator": "gt",
                "average_output_name": "municipality",
            },
            "group average output alias conflicts with projections",
        ),
    ],
)
def test_group_average_filter_rejects_unsafe_alias_shapes(
    group_average_filter: dict,
    reason: str,
) -> None:
    payload = _two_value_comparison_ir().model_dump(mode="python")
    payload["group_average_filter"] = group_average_filter

    with pytest.raises(ValueError, match=reason):
        AdHocSemanticQueryIR.model_validate(payload)


@pytest.mark.parametrize(
    ("semantic_ir", "reason"),
    [
        (_two_value_comparison_ir(baseline="Ultimate"), "semantic_two_value_comparison_scope_value_unsupported"),
        (
            _two_value_comparison_ir(
                include_municipality=False,
                district_label=False,
            ),
            "semantic_two_value_comparison_required_dimensions_missing",
        ),
    ],
)
def test_two_value_comparison_rejects_unaudited_values_or_incomplete_pairing_grain(
    semantic_ir: AdHocSemanticQueryIR,
    reason: str,
) -> None:
    semantic = _liveability_two_value_comparison_semantic_layer()
    with pytest.raises(SemanticIRCompilationError, match=reason):
        build_compiled_ad_hoc_semantic_plan(
            semantic_ir=semantic_ir,
            source=SOURCE,
            semantic_version=semantic["semantic_version"],
            semantic_layer=semantic,
            max_rows=1000,
            question="Compare reviewed district score stages.",
        )
