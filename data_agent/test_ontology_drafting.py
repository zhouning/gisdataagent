from __future__ import annotations

import copy
from pathlib import Path

import pytest

from data_agent.ontology.contracts import BASE_URI
from data_agent.ontology.drafting import (
    OntologyDraftValidationError,
    OntologyDraftService,
    apply_draft_change,
    compute_model_diff,
    empty_model_state,
    materialize_model_state,
    validate_model_state,
)


def test_draft_row_lock_does_not_require_update_on_immutable_baseline():
    assert OntologyDraftService._draft_access_clause(for_update=True) == " FOR UPDATE OF d"
    assert OntologyDraftService._draft_access_clause(for_update=False) == ""


def _concept(code: str, label: str, domain: str = "02") -> dict:
    return {
        "concept_id": f"gda:nr:class:{code}",
        "uri": f"{BASE_URI}class/{code}",
        "kind": "DomainClass",
        "code": code,
        "pref_label": label,
        "alt_labels": [],
        "definition": "",
        "domain_id": domain,
        "source_system": "curated_domain",
        "source_id": "natural-resource-domain-model-v2",
        "geometry_type": None,
        "lifecycle_status": "curated",
        "provenance": {},
    }


def _base_state() -> dict:
    state = empty_model_state()
    state["concept"]["gda:nr:class:Land"] = _concept("Land", "土地")
    state["concept"]["gda:nr:class:Parcel"] = _concept("Parcel", "地块")
    return state


def test_modeling_can_add_concept_property_and_relation_with_stable_ids():
    state = _base_state()
    concept = apply_draft_change(
        state,
        {
            "operation": "upsert_concept",
            "entity_type": "concept",
            "entity_id": "",
            "payload": {
                "code": "AgriculturalParcel",
                "pref_label": "农业地块",
                "definition": "具有农业利用状态的空间地块",
                "domain_id": "02",
                "kind": "DomainClass",
            },
        },
    )
    new_id = concept["entity_id"]
    assert new_id == "gda:nr:class:AgriculturalParcel"
    assert state["concept"][new_id]["uri"] == f"{BASE_URI}class/AgriculturalParcel"

    prop = apply_draft_change(
        state,
        {
            "operation": "upsert_property",
            "entity_type": "property",
            "entity_id": "",
            "payload": {
                "code": "cultivatedArea",
                "pref_label": "耕地面积",
                "owner_concept_id": new_id,
                "datatype": "xsd:double",
                "min_count": 1,
                "max_count": 1,
            },
        },
    )
    assert prop["entity_id"] == "gda:nr:property:cultivatedArea"

    relation = apply_draft_change(
        state,
        {
            "operation": "upsert_relation",
            "entity_type": "relation",
            "entity_id": "",
            "payload": {
                "relation_type": "subClassOf",
                "source_concept_id": new_id,
                "target_concept_id": "gda:nr:class:Parcel",
                "pref_label": "属于",
            },
        },
    )
    assert relation["entity_id"].startswith("gda:nr:subclass:AgriculturalParcel:Parcel")
    assert validate_model_state(state)["conforms"] is True


def test_existing_identity_and_uri_cannot_be_changed():
    state = _base_state()
    with pytest.raises(OntologyDraftValidationError, match="uri"):
        apply_draft_change(
            state,
            {
                "operation": "upsert_concept",
                "entity_type": "concept",
                "entity_id": "gda:nr:class:Land",
                "payload": {
                    "code": "Land",
                    "pref_label": "土地",
                    "domain_id": "02",
                    "uri": "https://evil.test/Land",
                },
            },
        )
    with pytest.raises(OntologyDraftValidationError, match="property_id"):
        state["property"]["gda:nr:property:area"] = {
            "property_id": "gda:nr:property:area",
            "owner_concept_id": "gda:nr:class:Land",
            "uri": f"{BASE_URI}property/area",
            "code": "area",
            "pref_label": "面积",
            "datatype": "xsd:double",
            "min_count": 0,
            "max_count": 1,
            "lifecycle_status": "active",
        }
        apply_draft_change(
            state,
            {
                "operation": "upsert_property",
                "entity_type": "property",
                "entity_id": "gda:nr:property:other",
                "payload": {
                    "code": "area",
                    "pref_label": "面积",
                    "owner_concept_id": "gda:nr:class:Land",
                },
            },
        )


def test_cardinality_and_relation_cycle_are_rejected():
    state = _base_state()
    with pytest.raises(OntologyDraftValidationError, match="cardinality"):
        apply_draft_change(
            state,
            {
                "operation": "upsert_property",
                "entity_type": "property",
                "entity_id": "",
                "payload": {
                    "code": "badCount",
                    "pref_label": "错误",
                    "owner_concept_id": "gda:nr:class:Land",
                    "min_count": 2,
                    "max_count": 1,
                },
            },
        )

    apply_draft_change(
        state,
        {
            "operation": "upsert_relation",
            "entity_type": "relation",
            "entity_id": "",
            "payload": {
                "relation_type": "subClassOf",
                "source_concept_id": "gda:nr:class:Land",
                "target_concept_id": "gda:nr:class:Parcel",
            },
        },
    )
    apply_draft_change(
        state,
        {
            "operation": "upsert_relation",
            "entity_type": "relation",
            "entity_id": "",
            "payload": {
                "relation_type": "subClassOf",
                "source_concept_id": "gda:nr:class:Parcel",
                "target_concept_id": "gda:nr:class:Land",
            },
        },
    )
    report = validate_model_state(state)
    assert report["conforms"] is False
    assert any(issue["code"] == "subclass_cycle" for issue in report["issues"])


def test_materialization_is_deterministic_and_diff_classifies_changes():
    base = _base_state()
    changes = [
        {
            "operation": "upsert_concept",
            "entity_type": "concept",
            "entity_id": "gda:nr:class:Land",
            "payload": {"code": "Land", "pref_label": "土地资源", "domain_id": "02"},
        },
        {
            "operation": "upsert_concept",
            "entity_type": "concept",
            "entity_id": "",
            "payload": {"code": "Wetland", "pref_label": "湿地", "domain_id": "02"},
        },
    ]
    first = materialize_model_state(base, changes)
    second = materialize_model_state(base, copy.deepcopy(changes))
    assert first == second
    diff = compute_model_diff(base, first)
    assert diff["summary"] == {"total": 2, "added": 1, "modified": 1, "deprecated": 0, "removed": 0}
    assert {item["change_kind"] for item in diff["items"]} == {"added", "modified"}
    assert diff["impact"] == {
        "changed_concept_count": 2,
        "changed_property_count": 0,
        "changed_relation_count": 0,
        "impacted_concept_count": 2,
        "impacted_property_count": 0,
        "impacted_relation_count": 0,
        "concept_ids": ["gda:nr:class:Land", "gda:nr:class:Wetland"],
    }


def test_unknown_payload_fields_are_rejected_instead_of_silently_discarded():
    state = _base_state()
    with pytest.raises(OntologyDraftValidationError, match="unsupported concept payload field"):
        apply_draft_change(
            state,
            {
                "operation": "upsert_concept",
                "entity_type": "concept",
                "entity_id": "gda:nr:class:Land",
                "payload": {
                    "code": "Land",
                    "pref_label": "土地",
                    "domain_id": "02",
                    "owl_equivalent_class": "external:Land",
                },
            },
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("length", -1, "length must be non-negative"),
        ("precision_value", 4.5, "precision_value must be an integer"),
        ("scale_value", 5, "scale_value cannot exceed precision_value"),
        ("value_domain", 42, "value_domain must be an object"),
    ],
)
def test_property_schema_facets_are_bounded(field, value, message):
    state = _base_state()
    payload = {
        "code": "area",
        "pref_label": "面积",
        "owner_concept_id": "gda:nr:class:Land",
        "datatype": "xsd:decimal",
        "precision_value": 4,
        "scale_value": 2,
        field: value,
    }
    with pytest.raises(OntologyDraftValidationError, match=message):
        apply_draft_change(
            state,
            {
                "operation": "upsert_property",
                "entity_type": "property",
                "entity_id": "",
                "payload": payload,
            },
        )


def test_deprecated_concepts_cannot_remain_active_relation_endpoints():
    state = _base_state()
    apply_draft_change(
        state,
        {
            "operation": "upsert_relation",
            "entity_type": "relation",
            "entity_id": "",
            "payload": {
                "relation_type": "contains",
                "source_concept_id": "gda:nr:class:Land",
                "target_concept_id": "gda:nr:class:Parcel",
            },
        },
    )
    apply_draft_change(
        state,
        {
            "operation": "deprecate_entity",
            "entity_type": "concept",
            "entity_id": "gda:nr:class:Parcel",
            "payload": {},
        },
    )

    report = validate_model_state(state)
    assert report["conforms"] is False
    assert any(issue["code"] == "deprecated_relation_endpoint" for issue in report["issues"])


def test_duplicate_relation_identity_is_reported():
    state = _base_state()
    first_id = "gda:nr:subclass:Land:Parcel"
    relation = {
        "relation_id": first_id,
        "relation_type": "subClassOf",
        "source_concept_id": "gda:nr:class:Land",
        "target_concept_id": "gda:nr:class:Parcel",
        "pref_label": "属于",
        "direction": "directed",
        "transitive": True,
        "symmetric": False,
        "lifecycle_status": "active",
    }
    state["relation"][first_id] = relation
    duplicate_id = "gda:nr:duplicate:Land:Parcel"
    state["relation"][duplicate_id] = {**relation, "relation_id": duplicate_id}

    report = validate_model_state(state)
    assert report["conforms"] is False
    assert any(issue["code"] == "duplicate_relation_identity" for issue in report["issues"])


def test_draft_migration_enforces_baseline_identity_and_append_only_history():
    sql = (Path(__file__).parent / "migrations/156_ontology_model_drafting.sql").read_text(
        encoding="utf-8"
    )

    assert "validate_ontology_draft_baseline" in sql
    assert "base_key <> NEW.ontology_key" in sql
    assert "base_hash <> NEW.base_content_sha256" in sql
    assert "ontology draft baseline identity is immutable" in sql
    assert "reject_ontology_draft_change_mutation" in sql
    assert "BEFORE UPDATE OR DELETE ON gda_ontology.ontology_draft_change" in sql
    assert "REFERENCES gda_ontology.ontology_draft(draft_id) ON DELETE RESTRICT" in sql


def test_draft_migration_grants_only_bounded_runtime_table_permissions():
    sql = (Path(__file__).parent / "migrations/156_ontology_model_drafting.sql").read_text(
        encoding="utf-8"
    )
    upper = sql.upper()

    assert "ALTER DEFAULT PRIVILEGES" not in upper
    assert "GRANT ALL" not in upper
    assert "GRANT SELECT, INSERT, UPDATE ON gda_ontology.ontology_draft TO %I" in sql
    assert "GRANT SELECT, INSERT ON gda_ontology.ontology_draft_change TO %I" in sql
    assert "UPDATE ON gda_ontology.ontology_draft_change" not in sql
