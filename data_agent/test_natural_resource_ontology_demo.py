import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from data_agent.api import ontology_demo_routes, ontology_routes
from data_agent.natural_resource_ontology_demo import NaturalResourceOntologyDemo
from data_agent.ontology.okf_attestation import (
    attest_scenario_receipt,
    build_scenario_receipt,
)
from data_agent.ontology.okf_bundle import validate_ontology_okf_bundle


@pytest.fixture(scope="module")
def demo() -> NaturalResourceOntologyDemo:
    return NaturalResourceOntologyDemo()


def test_bundle_is_bound_to_active_ontology_2_0_1(demo):
    overview = demo.overview()

    assert overview["ontology"]["version"] == "2.0.1"
    assert (
        overview["ontology"]["sha256"]
        == "953dac97c1be4d9683247da42dea022128471b15b9c677215d913fa209bd1200"
    )
    assert overview["ontology"]["stats"] == {
        "domain_classes": 96,
        "schema_artifacts": 3932,
        "skos_concepts": 1066,
        "mappings": 422,
        "rdf_triples": 528252,
    }
    assert overview["okf"]["okf_version"] == "0.2"
    assert overview["okf"]["validation"]["valid"] is True


def test_official_okf_bundle_and_computation_contract_are_valid():
    validation = validate_ontology_okf_bundle()

    assert validation == {
        "okf_version": "0.2",
        "bundle_id": "natural-resource-ontology-knowledge-v2",
        "valid": True,
        "concept_count": 8,
        "errors": [],
    }


def test_heping_results_are_computed_from_spatial_features(demo):
    scenario = next(item for item in demo.scenarios() if item["id"] == "heping_review")
    payload = demo.map_payload("heping_review")

    assert scenario["parcel_count"] == 902
    assert scenario["changed_count"] == 445
    assert scenario["review_status_counts"] == {
        "条件复核": 312,
        "材料待补": 108,
        "空间冲突": 25,
    }
    assert len(payload["layers"][0]["geojsonData"]["features"]) == scenario["changed_count"]
    assert len(payload["layers"][1]["geojsonData"]["features"]) == 16
    assert 29.5 < payload["center"][0] < 30.0
    assert 106.0 < payload["center"][1] < 106.5


def test_banzhu_structure_adjustment_retains_source_workbook_values(demo):
    scenario = next(item for item in demo.scenarios() if item["id"] == "banzhu_adjustment")
    rows = {row["name"]: row for row in scenario["structure_rows"]}

    assert scenario["parcel_count"] == 1555
    assert scenario["changed_count"] == 559
    assert rows["农用地合计"]["delta_ha"] == 9.06
    assert rows["旱地"]["delta_ha"] == 16.21
    assert rows["宅基地（村居住用地）"]["delta_ha"] == -12.2


def test_parcel_evidence_exposes_entity_state_process_and_constraints(demo):
    evidence = demo.evidence("和平村-62362")
    trace = evidence["semantic_trace"]
    properties = evidence["parcel"]["properties"]

    assert trace["entity"]["class"] == "gda:nr:class:LandParcel"
    assert trace["transition"]["class"] == "gda:nr:class:ConstructionOccupation"
    assert trace["source_state"]["label"] == "非耕农用地利用状态"
    assert trace["target_state"]["label"] == "建设用地利用状态"
    assert properties["evidence"]["approval_evidence"] == "missing"
    assert any(hit["layer"] == "STBHHX" for hit in properties["evidence"]["constraint_hits"])


def test_governance_does_not_fabricate_project_geometry(demo):
    governance = demo.governance()
    project_check = next(
        item for item in governance["quality"]["checks"] if item["id"] == "project_link"
    )

    assert project_check["status"] == "warning"
    assert project_check["value"] == "0/16"
    assert all(
        project["spatial_link_status"] == "unresolved"
        for project in governance["projects"]["和平村"]
    )


def test_scenario_receipt_is_attested_and_tampering_is_rejected(demo):
    raw_result = demo._run_computation("heping_review")
    receipt = build_scenario_receipt(
        demo,
        "heping_review",
        raw_result,
        executed_at="2026-08-05T00:00:00Z",
    )

    accepted = attest_scenario_receipt(
        demo,
        "heping_review",
        receipt,
        checked_at="2026-08-05T00:00:01Z",
    )
    assert accepted["passed"] is True
    assert accepted["gate"] == "display"

    receipt["result"]["changed_count"] = 444
    rejected = attest_scenario_receipt(
        demo,
        "heping_review",
        receipt,
        checked_at="2026-08-05T00:00:02Z",
    )
    assert rejected["passed"] is False
    assert rejected["gate"] == "refuse_display"
    assert {"result_digest", "authoritative_result"}.issubset(rejected["errors"])


def test_demo_routes_require_authentication(monkeypatch):
    monkeypatch.setattr(ontology_demo_routes, "_get_user_from_request", lambda request: None)
    app = Starlette(routes=ontology_demo_routes.get_ontology_demo_routes())

    with TestClient(app) as client:
        response = client.get("/api/ontology/demo/overview")

    assert response.status_code == 401


def test_demo_routes_return_bounded_scenario(monkeypatch):
    class User:
        identifier = "demo-user"
        metadata = {"role": "analyst"}

    monkeypatch.setattr(ontology_demo_routes, "_get_user_from_request", lambda request: User())
    app = Starlette(routes=ontology_demo_routes.get_ontology_demo_routes())

    with TestClient(app) as client:
        response = client.post("/api/ontology/demo/run", json={"scenario_id": "heping_review"})
        missing = client.get("/api/ontology/demo/map?scenario_id=unknown")

    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert len(response.json()["steps"]) == 6
    assert response.json()["attestation"]["passed"] is True
    assert response.json()["okf_reference"]["okf_version"] == "0.2"
    assert missing.status_code == 404


def test_ontology_okf_route_serves_bundle_and_blocks_path_traversal(monkeypatch):
    class User:
        identifier = "demo-user"
        metadata = {"role": "analyst"}

    monkeypatch.setattr(ontology_routes, "_get_user_from_request", lambda request: User())
    app = Starlette(routes=ontology_routes.get_ontology_routes())

    with TestClient(app) as client:
        index = client.get("/api/ontology/okf?path=index.md")
        validation = client.get("/api/ontology/okf?validate=1")
        traversal = client.get("/api/ontology/okf?path=../../pyproject.toml")

    assert index.status_code == 200
    assert 'okf_version: "0.2"' in index.text
    assert validation.status_code == 200
    assert validation.json()["valid"] is True
    assert traversal.status_code == 400
