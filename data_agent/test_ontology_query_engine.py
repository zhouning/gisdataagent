import json

import pytest
from pydantic import ValidationError

from data_agent.ontology.query_contracts import OntologyQueryPlan
from data_agent.ontology.service import OntologyService
from data_agent.ontology.sparql_adapter import SparqlProjectionUnavailable, SparqlReadAdapter
from data_agent.pipeline_helpers import extract_workspace_update_from_tool_response
from data_agent.toolsets.ontology_tools import (
    query_ontology,
    run_ontology_application_scenario,
)


@pytest.fixture(scope="module")
def service() -> OntologyService:
    return OntologyService()


def test_query_contract_rejects_raw_sparql():
    with pytest.raises(ValidationError):
        OntologyQueryPlan.model_validate(
            {
                "query_type": "hierarchy",
                "subject": "土地",
                "sparql": "DELETE WHERE { ?s ?p ?o }",
            }
        )


def test_sparql_adapter_rejects_unregistered_template_and_external_uri():
    adapter = SparqlReadAdapter("http://127.0.0.1:1/ontology/query")
    with pytest.raises(ValueError, match="outside the governed ontology namespace"):
        adapter.select("concept_summary", concept_uri="https://example.com/other")
    with pytest.raises(ValueError, match="not allowlisted"):
        adapter.select(
            "arbitrary",
            concept_uri="https://ontology.gis-data-agent.local/natural-resource/one-map/class/Land",
        )


def test_sparql_probe_distinguishes_ready_mismatch_and_unavailable(monkeypatch):
    adapter = SparqlReadAdapter("http://ontology-rdf:3030/ontology/query")
    monkeypatch.setattr(
        adapter,
        "_execute_select",
        lambda _query: {
            "results": {"bindings": [{"triples": {"value": "528252"}}]},
        },
    )

    assert adapter.probe(expected_triples=528252)["status"] == "ready"
    assert adapter.probe(expected_triples=1)["status"] == "mismatch"

    def unavailable(_query):
        raise SparqlProjectionUnavailable("offline")

    monkeypatch.setattr(adapter, "_execute_select", unavailable)
    assert adapter.probe(expected_triples=528252)["status"] == "unavailable"


def test_land_hierarchy_uses_curated_domain_classes(service, monkeypatch):
    monkeypatch.delenv("ONTOLOGY_SPARQL_ENDPOINT", raising=False)
    result = service.execute_query(
        {
            "query_type": "hierarchy",
            "subject": "土地",
            "depth": 2,
            "limit": 60,
        }
    )

    assert result["status"] == "ok"
    assert result["workspace_update"]["concept_id"] == "gda:nr:class:Land"
    node_ids = {node["id"] for node in result["result"]["hierarchy"]["nodes"]}
    assert {
        "gda:nr:class:AgriculturalLand",
        "gda:nr:class:ConstructionLand",
        "gda:nr:class:UnusedLand",
        "gda:nr:class:CultivatedLand",
    }.issubset(node_ids)
    assert result["okf_reference"] == {
        "okf_version": "0.2",
        "compatibility": "0.2+",
        "bundle_id": "natural-resource-ontology-knowledge-v2",
        "concept_id": "assets/natural-resource-ontology",
        "role": "knowledge_concept",
        "resource": "/api/ontology/okf?path=assets/natural-resource-ontology.md",
        "bundle_index": "/api/ontology/okf?path=index.md",
    }
    assert "attestation" not in result
    assert "okf_context" not in result


def test_transition_rules_include_states_and_inherited_evidence_requirements(service, monkeypatch):
    monkeypatch.delenv("ONTOLOGY_SPARQL_ENDPOINT", raising=False)
    adjustment = service.execute_query(
        {
            "query_type": "transition_rules",
            "subject": "农业结构调整",
            "depth": 3,
        }
    )["result"]
    occupation = service.execute_query(
        {
            "query_type": "transition_rules",
            "subject": "建设占用",
            "depth": 3,
        }
    )["result"]

    assert {item["concept_id"] for item in adjustment["allowed_source_states"]} == {
        "gda:nr:class:CultivatedLandUseState",
        "gda:nr:class:NonCultivatedAgriculturalLandUseState",
    }
    assert {item["concept_id"] for item in adjustment["allowed_target_states"]} == {
        "gda:nr:class:CultivatedLandUseState",
        "gda:nr:class:NonCultivatedAgriculturalLandUseState",
    }
    requirements = {item["property"] for item in occupation["semantic_requirements"]}
    assert {
        "hasSourceState",
        "hasTargetState",
        "affectsParcel",
        "authorizedBy",
        "supportedBy",
    }.issubset(requirements)


def test_transition_rules_accept_land_class_and_find_governed_processes(service, monkeypatch):
    monkeypatch.delenv("ONTOLOGY_SPARQL_ENDPOINT", raising=False)
    result = service.execute_query(
        {
            "query_type": "transition_rules",
            "subject": "农用地",
            "depth": 3,
        }
    )

    assert result["status"] == "ok"
    payload = result["result"]
    assert payload["interpreted_state"]["concept_id"] == ("gda:nr:class:AgriculturalLandUseState")
    assert payload["interpretation"]["method"] == "domain_code_to_state_class"
    processes = {item["process"]["concept_id"]: item for item in payload["processes"]}
    assert set(processes) == {
        "gda:nr:class:AgriculturalStructureAdjustment",
        "gda:nr:class:ConstructionOccupation",
    }
    occupation = processes["gda:nr:class:ConstructionOccupation"]
    assert {item["concept_id"] for item in occupation["allowed_source_states"]} == {
        "gda:nr:class:AgriculturalLandUseState"
    }
    assert {item["concept_id"] for item in occupation["allowed_target_states"]} == {
        "gda:nr:class:ConstructionLandUseState"
    }


def test_transition_rules_filter_by_explicit_target_state(service, monkeypatch):
    monkeypatch.delenv("ONTOLOGY_SPARQL_ENDPOINT", raising=False)
    result = service.execute_query(
        {
            "query_type": "transition_rules",
            "subject": "农用地",
            "target": "建设用地",
            "depth": 3,
        }
    )["result"]

    assert result["interpreted_state"]["concept_id"] == ("gda:nr:class:AgriculturalLandUseState")
    assert result["interpreted_target_state"]["concept_id"] == (
        "gda:nr:class:ConstructionLandUseState"
    )
    assert [item["process"]["concept_id"] for item in result["processes"]] == [
        "gda:nr:class:ConstructionOccupation"
    ]
    assert {item["rule"] for item in result["processes"][0]["matched_state_rules"]} == {
        "allowedSource"
    }


def test_transition_rules_inherit_parent_state_rules_for_specific_land_class(service, monkeypatch):
    monkeypatch.delenv("ONTOLOGY_SPARQL_ENDPOINT", raising=False)
    result = service.execute_query(
        {
            "query_type": "transition_rules",
            "subject": "耕地",
            "depth": 3,
        }
    )["result"]

    assert result["interpreted_state"]["concept_id"] == "gda:nr:class:CultivatedLandUseState"
    assert {item["process"]["concept_id"] for item in result["processes"]} == {
        "gda:nr:class:AgriculturalStructureAdjustment",
        "gda:nr:class:ConstructionOccupation",
    }


def test_relation_path_is_bounded_and_explainable(service, monkeypatch):
    monkeypatch.delenv("ONTOLOGY_SPARQL_ENDPOINT", raising=False)
    result = service.execute_query(
        {
            "query_type": "relation_path",
            "subject": "耕地",
            "target": "土地",
            "depth": 3,
        }
    )

    assert result["status"] == "ok"
    assert [step["relation_type"] for step in result["result"]["path"]] == [
        "subClassOf",
        "subClassOf",
    ]
    assert result["result"]["visited_count"] <= 120


def test_high_level_tools_emit_workspace_map_and_attested_okf_contract(monkeypatch):
    monkeypatch.setenv("ONTOLOGY_RUNTIME_BACKEND", "package")
    monkeypatch.delenv("ONTOLOGY_SPARQL_ENDPOINT", raising=False)
    hierarchy = json.loads(query_ontology("hierarchy", subject="农用地"))
    scenario = json.loads(run_ontology_application_scenario("heping_review"))

    assert hierarchy["workspace_update"] == {
        "tab": "ontology",
        "concept_id": "gda:nr:class:AgriculturalLand",
    }
    assert scenario["workspace_update"]["tab"] == "ontology_demo"
    assert scenario["workspace_update"]["auto_run"] is True
    assert "map_update" not in scenario["result"]
    assert scenario["result"]["map_update_summary"]["layer_count"] == 3
    assert scenario["result"]["map_update_summary"]["layer_names"] == [
        "和平村 · 规划变化地块",
        "和平村 · 空间约束",
        "和平村 · 建设用地管制区",
    ]
    assert scenario["okf_reference"]["okf_version"] == "0.2"
    assert scenario["okf_reference"]["concept_id"] == (
        "computations/heping-land-conversion-precheck"
    )
    assert scenario["okf_reference"]["role"] == "attested_computation_contract"
    assert scenario["attestation"]["passed"] is True
    assert scenario["attestation"]["gate"] == "display"
    scenario_run = scenario["result"]["scenario_result"]
    receipt = scenario_run["execution_receipt"]
    assert receipt["schema"] == "gda.okf.attested-computation-receipt.v1"
    assert receipt["parameters"] == {"scenario_id": "heping_review"}
    assert receipt["executed_computation"]["resource"] == (
        "/references/computations/version-locked-ontology-demo.json"
    )
    assert all(item["sha256"] == item["manifest_sha256"] for item in receipt["input_artifacts"])


def test_workspace_extractor_handles_serialized_tool_response():
    value = json.dumps(
        {
            "result": json.dumps(
                {
                    "workspace_update": {
                        "tab": "ontology",
                        "concept_id": "gda:nr:class:Land",
                        "unexpected": "removed",
                    }
                }
            )
        }
    )
    assert extract_workspace_update_from_tool_response(value) == {
        "tab": "ontology",
        "concept_id": "gda:nr:class:Land",
    }
