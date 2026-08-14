from __future__ import annotations

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from data_agent.api import ontology_draft_routes, ontology_routes
from data_agent.ontology.contracts import ONTOLOGY_KEY
from data_agent.ontology.drafting import (
    OntologyDraftValidationError,
    apply_draft_change,
    empty_model_state,
    validate_model_state,
)
from data_agent.ontology.package_reader import OntologyPackageReader
from data_agent.ontology.registry import (
    DMT_PROFILE,
    IRRIGATION_PROFILE,
    get_ontology_profile,
)
from data_agent.ontology.service import OntologyService

DMT_KEY = "abu-dhabi-dmt-gis"
IRRIGATION_KEY = "irrigation-district-water"


def _dmt_state() -> dict:
    state = empty_model_state()
    for code, label in (("Building", "建筑"), ("Plot", "地块")):
        apply_draft_change(
            state,
            {
                "operation": "upsert_concept",
                "entity_type": "concept",
                "entity_id": "",
                "payload": {
                    "code": code,
                    "pref_label": label,
                    "domain_id": "dmt_built" if code == "Building" else "dmt_land",
                    "kind": "DomainClass",
                },
            },
            profile=DMT_KEY,
        )
    return state


def test_registered_industry_ontologies_have_isolated_identity_spaces():
    natural_resource = get_ontology_profile()
    dmt = get_ontology_profile(DMT_KEY)
    irrigation = get_ontology_profile(IRRIGATION_KEY)

    assert natural_resource.ontology_key == ONTOLOGY_KEY
    assert dmt is DMT_PROFILE
    assert irrigation is IRRIGATION_PROFILE
    assert natural_resource.package_root != dmt.package_root
    assert natural_resource.namespace_uri != dmt.namespace_uri
    assert natural_resource.stable_id_prefix == "gda:nr"
    assert dmt.stable_id_prefix == "gda:dmt"
    assert irrigation.stable_id_prefix == "gda:irr"
    assert "dmt_built" in dmt.domain_labels
    assert "02" not in dmt.domain_labels
    assert "irr_network" in irrigation.domain_labels


def test_real_packages_are_resolved_by_profile_and_cross_loading_is_rejected():
    natural_resource = OntologyPackageReader(ontology_key=ONTOLOGY_KEY)
    dmt = OntologyPackageReader(ontology_key=DMT_KEY)
    irrigation = OntologyPackageReader(ontology_key=IRRIGATION_KEY)

    assert natural_resource.manifest.ontology_key == ONTOLOGY_KEY
    assert natural_resource.manifest.semantic_version == "2.3.0"
    assert dmt.manifest.ontology_key == DMT_KEY
    assert dmt.manifest.semantic_version == "0.1.1"
    assert irrigation.manifest.ontology_key == IRRIGATION_KEY
    assert irrigation.manifest.semantic_version == "0.1.0"

    with pytest.raises(ValueError, match="ontology package key mismatch"):
        OntologyPackageReader(dmt.package_dir, ontology_key=ONTOLOGY_KEY)


def test_dmt_same_named_properties_are_scoped_by_owner():
    state = _dmt_state()
    property_ids = []
    for owner in ("gda:dmt:class:Building", "gda:dmt:class:Plot"):
        result = apply_draft_change(
            state,
            {
                "operation": "upsert_property",
                "entity_type": "property",
                "entity_id": "",
                "payload": {
                    "code": "status",
                    "pref_label": "状态",
                    "owner_concept_id": owner,
                    "datatype": "xsd:string",
                },
            },
            profile=DMT_KEY,
        )
        property_ids.append(result["entity_id"])

    assert property_ids == [
        "gda:dmt:property:Building:status",
        "gda:dmt:property:Plot:status",
    ]
    assert len({state["property"][item]["uri"] for item in property_ids}) == 2
    assert validate_model_state(state, profile=DMT_KEY)["conforms"] is True


def test_dmt_drafting_rejects_domains_from_another_industry():
    with pytest.raises(OntologyDraftValidationError, match="domain_id"):
        apply_draft_change(
            empty_model_state(),
            {
                "operation": "upsert_concept",
                "entity_type": "concept",
                "entity_id": "",
                "payload": {
                    "code": "CrossIndustryObject",
                    "pref_label": "跨行业对象",
                    "domain_id": "02",
                },
            },
            profile=DMT_KEY,
        )


def test_package_runtime_keeps_both_active_profiles_independent(monkeypatch):
    monkeypatch.setenv("ONTOLOGY_RUNTIME_BACKEND", "package")

    natural_resource = OntologyService(ontology_key=ONTOLOGY_KEY).status()
    dmt = OntologyService(ontology_key=DMT_KEY).status()
    irrigation = OntologyService(ontology_key=IRRIGATION_KEY).status()

    assert (natural_resource["ontology_key"], natural_resource["semantic_version"]) == (
        ONTOLOGY_KEY,
        "2.3.0",
    )
    assert (dmt["ontology_key"], dmt["semantic_version"]) == (DMT_KEY, "0.1.1")
    assert natural_resource["stats"]["domain_class_count"] == 246
    assert dmt["stats"]["domain_class_count"] == 79
    assert (irrigation["ontology_key"], irrigation["semantic_version"]) == (
        IRRIGATION_KEY,
        "0.1.0",
    )
    assert irrigation["stats"]["domain_class_count"] >= 30


class _FakeRuntimeService:
    def __init__(self, ontology_key: str):
        self.ontology_key = ontology_key

    def status(self):
        return {"available": True, "ontology_key": self.ontology_key}


class _FakeDraftService:
    def __init__(self, ontology_key: str):
        self.ontology_key = ontology_key

    def list_drafts(self, **_kwargs):
        return [{"ontology_key": self.ontology_key}]


def _authenticate_routes(monkeypatch, module) -> None:
    monkeypatch.setattr(module, "_get_user_from_request", lambda _request: object())
    monkeypatch.setattr(
        module,
        "_set_user_context",
        lambda _user: ("ontology-tester", "admin"),
    )


def test_scoped_runtime_routes_select_profile_and_legacy_route_stays_natural_resource(
    monkeypatch,
):
    calls: list[str] = []

    def service_factory(ontology_key: str = ONTOLOGY_KEY):
        calls.append(ontology_key)
        return _FakeRuntimeService(ontology_key)

    _authenticate_routes(monkeypatch, ontology_routes)
    monkeypatch.setattr(ontology_routes, "get_ontology_service", service_factory)
    client = TestClient(Starlette(routes=ontology_routes.get_ontology_routes()))

    profiles = client.get("/api/ontologies")
    scoped = client.get(f"/api/ontologies/{DMT_KEY}/status")
    legacy = client.get("/api/ontology/status")

    assert profiles.status_code == 200
    assert {item["ontology_key"] for item in profiles.json()["items"]} == {
        ONTOLOGY_KEY,
        DMT_KEY,
        IRRIGATION_KEY,
    }
    assert scoped.json()["ontology_key"] == DMT_KEY
    assert legacy.json()["ontology_key"] == ONTOLOGY_KEY
    assert calls == [DMT_KEY, ONTOLOGY_KEY]


def test_scoped_draft_routes_select_the_dmt_draft_authority(monkeypatch):
    calls: list[str] = []

    def service_factory(ontology_key: str = ONTOLOGY_KEY):
        calls.append(ontology_key)
        return _FakeDraftService(ontology_key)

    _authenticate_routes(monkeypatch, ontology_draft_routes)
    monkeypatch.setattr(
        ontology_draft_routes,
        "get_ontology_draft_service",
        service_factory,
    )
    client = TestClient(Starlette(routes=ontology_draft_routes.get_ontology_draft_routes()))

    response = client.get(f"/api/ontologies/{DMT_KEY}/drafts")

    assert response.status_code == 200
    assert response.json()["items"] == [{"ontology_key": DMT_KEY}]
    assert calls == [DMT_KEY]
