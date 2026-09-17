"""Formal-gate tests for ontology-driven physical-lake query contracts."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import pytest

from data_agent.ontology.semantic_execution import (
    SemanticExecutionContractError,
    audit_physical_lake_semantic_execution_ontology,
    audit_virtual_ontology_semantic_execution,
    build_physical_lake_semantic_execution_contract,
    scope_virtual_semantic_layer_to_ontology,
    validate_physical_lake_semantic_execution_contract,
    validate_virtual_ontology_semantic_gate,
)
from data_agent.platform_contracts import canonical_json_fingerprint


def _ods_contract() -> dict:
    return {
        "model_contract_id": "11111111-1111-1111-1111-111111111111",
        "model_contract_sha256": "a" * 64,
        "tables": [
            {
                "source_id": 13,
                "source_table": "public.busshelter",
                "ods_table": "lakehouse.gis_ods.busshelter",
                "columns": [
                    {"ods_column": "shelter_no"},
                    {"ods_column": "location"},
                    {"ods_column": "shape"},
                ],
            }
        ],
    }


def _reseal(contract: dict) -> None:
    payload = {
        key: value
        for key, value in contract.items()
        if key not in {"semantic_contract_sha256", "semantic_contract_id"}
    }
    fingerprint = canonical_json_fingerprint(payload)
    contract["semantic_contract_sha256"] = fingerprint
    contract["semantic_contract_id"] = str(
        uuid5(NAMESPACE_URL, f"gda://abu-dhabi/ontology-semantic-execution/{fingerprint}")
    )


def test_contract_keeps_classes_and_physical_representations_separate() -> None:
    contract = build_physical_lake_semantic_execution_contract(_ods_contract())

    assert contract["execution_policy"]["physical_table_is_ontology_class"] is False
    assert all("source_table" not in item for item in contract["classes"])
    representation = contract["source_representations"][0]
    assert representation["source_binding"] == {
        "source_id": 13,
        "source_table": "public.busshelter",
        "ods_table": "lakehouse.gis_ods.busshelter",
        "source_role": "candidate_reference",
    }
    assert representation["concept_iri"].endswith("class/mobility/transit-location")
    assert all(
        property_["domain_iri"] == representation["concept_iri"]
        for property_ in contract["data_properties"]
    )


def test_contract_rejects_a_table_promoted_to_a_class_even_if_resealed() -> None:
    contract = deepcopy(build_physical_lake_semantic_execution_contract(_ods_contract()))
    contract["classes"][-1]["source_table"] = "public.busshelter"
    _reseal(contract)

    with pytest.raises(SemanticExecutionContractError, match="table_promoted_to_class"):
        validate_physical_lake_semantic_execution_contract(contract)


def test_contract_rejects_property_without_a_formal_range_even_if_resealed() -> None:
    contract = deepcopy(build_physical_lake_semantic_execution_contract(_ods_contract()))
    contract["data_properties"][0]["range"] = ""
    _reseal(contract)

    with pytest.raises(SemanticExecutionContractError, match="data_property_invalid"):
        validate_physical_lake_semantic_execution_contract(contract)


def test_contract_rejects_a_tampered_logical_axiom_even_if_resealed() -> None:
    contract = deepcopy(build_physical_lake_semantic_execution_contract(_ods_contract()))
    contract["axioms"]["data_property_constraints"][0]["max_count"] = 2
    _reseal(contract)

    with pytest.raises(SemanticExecutionContractError, match="data_property_axiom_invalid"):
        validate_physical_lake_semantic_execution_contract(contract)


def test_physical_contract_has_an_owl_and_shacl_projection() -> None:
    contract = build_physical_lake_semantic_execution_contract(_ods_contract())

    audit = audit_physical_lake_semantic_execution_ontology(contract)

    assert audit["ontology_language"] == "OWL 2 RL"
    assert audit["constraint_language"] == "SHACL"
    assert audit["shacl_conforms"] is True
    assert audit["owl_triple_count"] > 0
    assert audit["logical_axiom_count"] > 0


def _virtual_semantic_layer(overlay_path: Path) -> dict:
    return {
        "schema": "gda.multilingual-virtual-semantic-layer.v1",
        "activation_gate": {"active_for_free_form_nl2sql": True},
        "ontology_overlay": str(overlay_path),
        "source_binding": {"source_id": 12},
        "table_bindings": [
            {
                "physical_table": "public.facility_inventory",
                "execution_eligible": True,
                "fields": [
                    {
                        "semantic_field": "facility_identifier",
                        "physical_field": "facility_id",
                        "business_role": "identifier",
                        "labels": {"zh": "设施标识", "en": "facility identifier", "ar": "معرف المرفق"},
                        "description": "设施在来源版本中的唯一标识。",
                        "semantic_status": "reviewed_business_semantics",
                        "inference": {"runtime_authority": True},
                        "technical_metadata": {"data_type": "UUID"},
                    },
                    {
                        "semantic_field": "unreviewed_tracking_value",
                        "physical_field": "tracking_value",
                        "business_role": "attribute",
                        "labels": {"zh": "追踪值", "en": "tracking value", "ar": "قيمة التتبع"},
                        "description": "尚未审核的追踪字段。",
                        "semantic_status": "inferred_candidate",
                        "inference": {"runtime_authority": False},
                        "technical_metadata": {"data_type": "TEXT"},
                    },
                ],
            }
        ],
        "semantic_assets": [
            {
                "asset_id": "city.facility",
                "physical_tables": ["public.facility_inventory"],
                "labels": {"zh": "设施", "en": "facility", "ar": "مرفق"},
                "description": "A public facility represented in one source version.",
                "grain": "one row per facility in one source version",
                "fields": [
                    {
                        "semantic_field": "facility_identifier",
                        "physical_field": "facility_id",
                        "business_role": "identifier",
                        "labels": {"zh": "设施标识", "en": "facility identifier", "ar": "معرف المرفق"},
                        "description": "设施在来源版本中的唯一标识。",
                    }
                ],
            }
        ],
        "metric_contracts": [],
    }


def _virtual_overlay() -> dict:
    return {
        "schema": "gda.ontology-runtime-overlay.v1",
        "overlay_id": "city-source-overlay-v1",
        "base_ontology": "city-domain-ontology-v1",
        "source_evidence": {"source_id": 12},
        "concepts": [
            {
                "concept_id": "city_source.facility_inventory",
                "physical_binding": "public.facility_inventory",
                "business_asset_id": "city.facility",
                "labels": {"zh": "设施", "en": "facility", "ar": "مرفق"},
                "description": "A public facility represented in one source version.",
                "grain": "one row per facility in one source version",
                "fields": [
                    {
                        "semantic_field": "facility_identifier",
                        "physical_field": "facility_id",
                        "business_role": "identifier",
                        "labels": {"zh": "设施标识", "en": "facility identifier", "ar": "معرف المرفق"},
                        "description": "设施在来源版本中的唯一标识。",
                        "semantic_status": "reviewed_business_semantics",
                        "inference": {"runtime_authority": True},
                        "technical_metadata": {"data_type": "UUID"},
                    },
                    {
                        "semantic_field": "unreviewed_tracking_value",
                        "physical_field": "tracking_value",
                        "business_role": "attribute",
                        "labels": {"zh": "追踪值", "en": "tracking value", "ar": "قيمة التتبع"},
                        "description": "尚未审核的追踪字段。",
                        "semantic_status": "inferred_candidate",
                        "inference": {"runtime_authority": False},
                        "technical_metadata": {"data_type": "TEXT"},
                    },
                ],
            }
        ],
    }


def test_virtual_execution_scope_removes_unmapped_same_table_fields(tmp_path: Path) -> None:
    overlay_path = tmp_path / "overlay.json"
    overlay_path.write_text(json.dumps(_virtual_overlay()), encoding="utf-8")
    layer = _virtual_semantic_layer(overlay_path)

    gate = validate_virtual_ontology_semantic_gate(layer, tmp_path / "semantic.json")
    scoped = scope_virtual_semantic_layer_to_ontology(layer, gate)

    binding = scoped["table_bindings"][0]
    assert [field["physical_field"] for field in binding["fields"]] == ["facility_id"]
    assert gate["formal_contract"]["physical_table_is_ontology_class"] is False
    assert gate["formal_contract"]["business_class_count"] == 1
    audit = audit_virtual_ontology_semantic_execution(layer, gate)
    assert audit["shacl_conforms"] is True
    assert audit["logical_axiom_count"] > 0


def test_virtual_execution_scope_removes_technical_only_tables_from_row_policies(
    tmp_path: Path,
) -> None:
    overlay_path = tmp_path / "overlay.json"
    overlay_path.write_text(json.dumps(_virtual_overlay()), encoding="utf-8")
    layer = _virtual_semantic_layer(overlay_path)
    layer["table_bindings"].append(
        {
            "physical_table": "public.raw_tracking_inventory",
            "execution_eligible": True,
            "fields": [
                {
                    "semantic_field": "tracking_value",
                    "physical_field": "tracking_value",
                    "business_role": "attribute",
                    "labels": {"zh": "追踪值", "en": "tracking value", "ar": "قيمة التتبع"},
                    "description": "技术追踪值。",
                    "semantic_status": "inferred_candidate",
                    "inference": {"runtime_authority": False},
                    "technical_metadata": {"data_type": "TEXT"},
                }
            ],
        }
    )
    overlay = _virtual_overlay()
    overlay["concepts"].append(
        {
            "concept_id": "city_source.raw_tracking_inventory",
            "physical_binding": "public.raw_tracking_inventory",
            "labels": {"zh": "追踪清单", "en": "tracking inventory", "ar": "قائمة التتبع"},
            "description": "仅用于来源目录检查的技术表示。",
            "fields": [
                {
                    "semantic_field": "tracking_value",
                    "physical_field": "tracking_value",
                    "business_role": "attribute",
                    "labels": {"zh": "追踪值", "en": "tracking value", "ar": "قيمة التتبع"},
                }
            ],
        }
    )
    overlay_path.write_text(json.dumps(overlay), encoding="utf-8")
    layer["row_scope_policies"] = [
        {
            "policy_id": "CITY_ACTIVE_FACILITY_V1",
            "review_status": "reviewed",
            "applies_to_tables": [
                "public.facility_inventory",
                "public.raw_tracking_inventory",
            ],
            "required_predicate": {
                "table": "public.facility_inventory",
                "field": "facility_id",
                "operator": "is_true",
            },
            "explicit_override_terms": {},
        }
    ]

    gate = validate_virtual_ontology_semantic_gate(layer, tmp_path / "semantic.json")
    scoped = scope_virtual_semantic_layer_to_ontology(layer, gate)

    assert scoped["row_scope_policies"][0]["applies_to_tables"] == [
        "public.facility_inventory"
    ]
    raw_binding = next(
        item
        for item in scoped["table_bindings"]
        if item["physical_table"] == "public.raw_tracking_inventory"
    )
    assert raw_binding["execution_eligible"] is False


def test_virtual_execution_scope_keeps_non_class_row_scope_source_compiler_only(
    tmp_path: Path,
) -> None:
    overlay_path = tmp_path / "overlay.json"
    overlay_path.write_text(json.dumps(_virtual_overlay()), encoding="utf-8")
    layer = _virtual_semantic_layer(overlay_path)
    layer["table_bindings"][0]["semantic_entity"] = "city.facility"
    layer["table_bindings"][0]["fields"].append(
        {
            "semantic_field": "version_id",
            "physical_field": "version_id",
            "business_role": "join_key",
            "labels": {"zh": "版本标识", "en": "version id", "ar": "معرف الإصدار"},
            "description": "来源版本连接键。",
            "semantic_status": "inferred_candidate",
            "inference": {"runtime_authority": False},
            "technical_metadata": {"data_type": "BIGINT"},
        }
    )
    layer["table_bindings"].append(
        {
            "physical_table": "public.version_control",
            "semantic_entity": "technical.version_control",
            "execution_eligible": True,
            "fields": [
                {
                    "semantic_field": "version_id",
                    "physical_field": "version_id",
                    "business_role": "identifier",
                    "labels": {"zh": "版本标识", "en": "version id", "ar": "معرف الإصدار"},
                    "description": "技术版本标识。",
                    "semantic_status": "inferred_candidate",
                    "inference": {"runtime_authority": False},
                    "technical_metadata": {"data_type": "BIGINT"},
                },
                {
                    "semantic_field": "current_flag",
                    "physical_field": "current_flag",
                    "business_role": "attribute",
                    "labels": {"zh": "当前标志", "en": "current flag", "ar": "علامة الحالية"},
                    "description": "当前批准版本标志。",
                    "semantic_status": "inferred_candidate",
                    "inference": {"runtime_authority": False},
                    "technical_metadata": {"data_type": "BOOLEAN"},
                },
            ],
        }
    )
    overlay = _virtual_overlay()
    overlay["concepts"].append(
        {
            "concept_id": "technical.version_control",
            "physical_binding": "public.version_control",
            "labels": {"zh": "版本控制表示", "en": "version control representation", "ar": "تمثيل التحكم في الإصدار"},
            "description": "仅作为来源治理控制的技术表示。",
            "fields": deepcopy(layer["table_bindings"][1]["fields"]),
        }
    )
    overlay_path.write_text(json.dumps(overlay), encoding="utf-8")
    layer["relationships"] = [
        {
            "left": "public.facility_inventory.version_id",
            "right": "public.version_control.version_id",
            "kind": "equality",
            "operator": "=",
            "review_status": "reviewed",
        }
    ]
    layer["row_scope_policies"] = [
        {
            "policy_id": "CITY_CURRENT_VERSION_V1",
            "review_status": "reviewed",
            "applies_to_tables": ["public.facility_inventory"],
            "required_join": {
                "fact_field": "version_id",
                "dimension_table": "public.version_control",
                "dimension_field": "version_id",
            },
            "required_predicate": {
                "table": "public.version_control",
                "field": "current_flag",
                "operator": "is_true",
            },
            "explicit_override_terms": {},
        }
    ]

    gate = validate_virtual_ontology_semantic_gate(layer, tmp_path / "semantic.json")
    scoped = scope_virtual_semantic_layer_to_ontology(layer, gate)

    assert gate["formal_contract"]["business_class_count"] == 1
    assert scoped["row_scope_policies"][0]["policy_id"] == "CITY_CURRENT_VERSION_V1"
    support = next(
        item
        for item in scoped["table_bindings"]
        if item["physical_table"] == "public.version_control"
    )
    assert support["execution_eligible"] is False
    assert support["compiler_governance_support"] is True
    assert {field["physical_field"] for field in support["fields"]} == {
        "current_flag",
        "version_id",
    }
    facility = scoped["table_bindings"][0]
    version_field = next(
        field for field in facility["fields"] if field["physical_field"] == "version_id"
    )
    assert version_field["compiler_governance_support"] is True
    assert scoped["ontology_semantic_execution"][
        "compiler_governance_support_tables"
    ] == ("public.version_control",)


def test_virtual_gate_rejects_a_candidate_field_added_as_a_business_property(tmp_path: Path) -> None:
    overlay_path = tmp_path / "overlay.json"
    overlay_path.write_text(json.dumps(_virtual_overlay()), encoding="utf-8")
    layer = _virtual_semantic_layer(overlay_path)
    candidate = deepcopy(layer["table_bindings"][0]["fields"][1])
    layer["semantic_assets"][0]["fields"].append(candidate)

    with pytest.raises(
        SemanticExecutionContractError,
        match="business_property_mapping_invalid",
    ):
        validate_virtual_ontology_semantic_gate(layer, tmp_path / "semantic.json")


def test_virtual_gate_rejects_a_physical_table_used_as_the_business_class(tmp_path: Path) -> None:
    overlay_path = tmp_path / "overlay.json"
    overlay = _virtual_overlay()
    overlay["concepts"][0]["business_asset_id"] = "public.facility_inventory"
    overlay_path.write_text(json.dumps(overlay), encoding="utf-8")
    layer = _virtual_semantic_layer(overlay_path)
    layer["semantic_assets"][0]["asset_id"] = "public.facility_inventory"

    with pytest.raises(
        SemanticExecutionContractError,
        match="table_promoted_to_business_class",
    ):
        validate_virtual_ontology_semantic_gate(layer, tmp_path / "semantic.json")


def test_virtual_execution_gate_rejects_business_definition_drift(tmp_path: Path) -> None:
    overlay_path = tmp_path / "overlay.json"
    overlay = _virtual_overlay()
    overlay["concepts"][0]["grain"] = "one row per facility without a source version"
    overlay_path.write_text(json.dumps(overlay), encoding="utf-8")

    with pytest.raises(
        SemanticExecutionContractError,
        match="business_asset_definition_mismatch",
    ):
        validate_virtual_ontology_semantic_gate(
            _virtual_semantic_layer(overlay_path),
            tmp_path / "semantic.json",
        )
