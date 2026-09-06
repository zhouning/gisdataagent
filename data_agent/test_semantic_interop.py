"""Contract tests for Abu Dhabi ontology/semantic standards interchange."""

from __future__ import annotations

import pytest

rdflib = pytest.importorskip("rdflib")

from data_agent.semantic_interop import (  # noqa: E402
    InteropError,
    export_ontology_to_jsonld,
    export_ontology_to_turtle,
    export_semantic_layer_to_jsonld,
    export_semantic_layer_to_ossie_yaml,
    export_semantic_layer_to_turtle,
    import_ontology_from_jsonld,
    import_ontology_from_turtle,
    import_semantic_layer_from_jsonld,
    import_semantic_layer_from_ossie_yaml,
    import_semantic_layer_from_turtle,
    validate_roundtrip,
)


@pytest.fixture
def ontology_payload() -> dict:
    return {
        "schema": "gda.ontology-runtime-overlay.v1",
        "ontology_enrichment_version": "abu-test-1",
        "status": "active",
        "source_evidence": {"source_id": 12, "database_name": "liveability_data_20260730"},
        "concepts": [
            {
                "concept_id": "dmt_liveability.facility",
                "labels": {"zh": "设施", "en": "facility", "ar": "مرفق"},
                "aliases": ["facility point"],
                "description": "one facility per row",
                "physical_binding": "public.dim_facilities",
                "review_status": "reviewed",
                "fields": [
                    {
                        "semantic_field": "facility_id",
                        "physical_field": "facility_id",
                        "labels": {"en": "facility id"},
                        "business_role": "identifier",
                        "technical_metadata": {"data_type": "UUID", "nullable": False},
                    },
                    {
                        "semantic_field": "facility_type",
                        "physical_field": "facility_type",
                        "labels": {"en": "facility type"},
                        "business_role": "dimension",
                        "technical_metadata": {"data_type": "TEXT", "nullable": True},
                        "value_domain": ["park", "school"],
                    },
                ],
            }
        ],
        "relations": [],
    }


@pytest.fixture
def semantic_payload() -> dict:
    return {
        "schema": "gda.multilingual-virtual-semantic-layer.v1",
        "semantic_version": "abu-test-semantic-1",
        "status": "active",
        "source_binding": {
            "source_id": 13,
            "database_name": "makani_sync_full",
            "discovery_fingerprint": "a" * 64,
            "profile_fingerprint": "b" * 64,
        },
        "semantic_assets": [
            {
                "asset_id": "makani.facilities",
                "labels": {"en": "facilities"},
                "physical_tables": ["public.facilities"],
                "review_status": "reviewed",
                "fields": [
                    {
                        "semantic_field": "objectid",
                        "physical_field": "objectid",
                        "labels": {"en": "object id"},
                        "business_role": "identifier",
                        "technical_metadata": {"data_type": "INTEGER", "nullable": False},
                    }
                ],
            }
        ],
        "table_bindings": [],
        "relationships": [],
        "metric_contracts": [
            {
                "contract_id": "FACILITY_COUNT",
                "review_status": "reviewed",
                "operation": "count",
                "tables": ["public.facilities"],
                "metrics": [{"aggregate": "count", "field": "*"}],
            }
        ],
    }


def test_ontology_turtle_jsonld_roundtrip_and_standard_terms(ontology_payload):
    turtle = export_ontology_to_turtle(ontology_payload)
    jsonld = export_ontology_to_jsonld(ontology_payload)
    turtle_graph = rdflib.Graph().parse(data=turtle, format="turtle")
    jsonld_graph = rdflib.Graph().parse(data=jsonld, format="json-ld")
    owl = rdflib.Namespace("http://www.w3.org/2002/07/owl#")
    sh = rdflib.Namespace("http://www.w3.org/ns/shacl#")
    skos = rdflib.Namespace("http://www.w3.org/2004/02/skos/core#")
    assert list(turtle_graph.subjects(rdflib.RDF.type, owl.Class))
    assert list(turtle_graph.subjects(rdflib.RDF.type, sh.NodeShape))
    assert list(turtle_graph.objects(None, skos.prefLabel))
    assert import_ontology_from_turtle(turtle) == ontology_payload
    assert import_ontology_from_jsonld(jsonld) == ontology_payload


def test_semantic_layer_preserves_source_metric_and_standard_projection(semantic_payload):
    turtle = export_semantic_layer_to_turtle(semantic_payload)
    jsonld = export_semantic_layer_to_jsonld(semantic_payload)
    graph = rdflib.Graph().parse(data=turtle, format="turtle")
    owl = rdflib.Namespace("http://www.w3.org/2002/07/owl#")
    gda = rdflib.Namespace("https://ontology.gis-data-agent.local/abu-dhabi/vocab/")
    assert len(list(graph.subjects(rdflib.RDF.type, owl.Class))) == 1
    assert len(list(graph.subjects(rdflib.RDF.type, gda.MetricContract))) == 1
    assert "makani_sync_full" in turtle
    assert import_semantic_layer_from_turtle(turtle) == semantic_payload
    assert import_semantic_layer_from_jsonld(jsonld) == semantic_payload


def test_strict_import_rejects_plain_rdf_without_lossless_extension():
    graph = rdflib.Graph()
    owl = rdflib.Namespace("http://www.w3.org/2002/07/owl#")
    graph.add((rdflib.URIRef("https://example.test/Facility"), rdflib.RDF.type, owl.Class))
    turtle = graph.serialize(format="turtle")
    with pytest.raises(InteropError, match="strict import requires"):
        import_ontology_from_turtle(turtle, mode="strict")
    projection = import_ontology_from_turtle(turtle, mode="projection-only")
    assert projection["runtime_role"]["execution_authority"] is False


def test_rdf_projection_only_reconstructs_fields_relationships_and_metrics(semantic_payload):
    semantic_payload = dict(semantic_payload)
    semantic_payload["semantic_assets"] = list(semantic_payload["semantic_assets"])
    semantic_payload["semantic_assets"][0] = dict(semantic_payload["semantic_assets"][0])
    semantic_payload["semantic_assets"].append({
        "asset_id": "makani.districts",
        "labels": {"en": "districts"},
        "physical_tables": ["public.districts"],
        "fields": [],
    })
    semantic_payload["relationships"] = [{
        "relationship_id": "facility_district",
        "source": "public.facilities.district_id",
        "target": "public.districts.id",
        "kind": "foreign_key",
    }]
    turtle = export_semantic_layer_to_turtle(semantic_payload)
    graph = rdflib.Graph().parse(data=turtle, format="turtle")
    gda = rdflib.Namespace("https://ontology.gis-data-agent.local/abu-dhabi/vocab/")
    for triple in list(graph.triples((None, gda["originalJson"], None))):
        graph.remove(triple)
    projection = import_semantic_layer_from_turtle(graph.serialize(format="turtle"), mode="projection-only")

    assert projection["runtime_role"]["execution_authority"] is False
    facilities = next(item for item in projection["semantic_assets"] if item.get("physical_binding") == "public.facilities")
    assert facilities["fields"][0]["semantic_field"] == "objectid"
    assert projection["relationships"][0]["relationship_id"] == "facility_district"
    assert projection["metric_contracts"]


def test_payload_hash_tampering_is_rejected(ontology_payload):
    turtle = export_ontology_to_turtle(ontology_payload)
    digest = validate_roundtrip(ontology_payload, formats=("turtle",))["source_sha256"]
    tampered = turtle.replace(digest, "0" * 64, 1)
    with pytest.raises(InteropError, match="payload hash mismatch"):
        import_ontology_from_turtle(tampered)


def test_validate_roundtrip_reports_both_formats(ontology_payload, semantic_payload):
    for payload in (ontology_payload, semantic_payload):
        result = validate_roundtrip(payload)
        assert result["lossless"] is True
        assert result["formats"]["turtle"]["lossless"] is True
        assert result["formats"]["json-ld"]["lossless"] is True


def test_ossie_projection_roundtrip_and_projection_only_import(semantic_payload):
    document = export_semantic_layer_to_ossie_yaml(semantic_payload)
    parsed = __import__("yaml").safe_load(document)
    assert parsed["version"] == "0.2.0.dev0"
    model = parsed["semantic_model"][0]
    assert model["datasets"][0]["source"] == "public.facilities"
    assert model["datasets"][0]["fields"][0]["expression"]["dialects"][0]["dialect"] == "ANSI_SQL"
    assert import_semantic_layer_from_ossie_yaml(document) == semantic_payload

    tampered = document.replace("public.facilities", "public.evil")
    with pytest.raises(InteropError, match="projection hash mismatch"):
        import_semantic_layer_from_ossie_yaml(tampered)

    plain = {"version": "0.2.0.dev0", "semantic_model": [{"name": "plain", "datasets": [{"name": "t", "source": "public.t", "fields": []}]}]}
    plain_text = __import__("yaml").safe_dump(plain, allow_unicode=True, sort_keys=False)
    with pytest.raises(InteropError, match="strict OSSIE import"):
        import_semantic_layer_from_ossie_yaml(plain_text)
    projection = import_semantic_layer_from_ossie_yaml(plain_text, mode="projection-only")
    assert projection["runtime_role"]["execution_authority"] is False
    assert projection["semantic_assets"][0]["execution_eligible"] is False


def test_ossie_projection_preserves_multi_model_relationships_and_metrics():
    plain = {
        "version": "0.2.0.dev0",
        "semantic_model": [
            {
                "name": "first",
                "datasets": [
                    {"name": "shared", "source": "public.shared", "fields": []},
                    {"name": "dim", "source": "public.dim", "fields": []},
                ],
                "relationships": [{
                    "name": "shared_dim",
                    "from": "shared",
                    "to": "dim",
                    "from_columns": ["id"],
                    "to_columns": ["id"],
                }],
                "metrics": [{
                    "name": "shared_count",
                    "description": "count shared rows",
                    "expression": {"dialects": [{"dialect": "ANSI_SQL", "expression": "COUNT(shared.id)"}]},
                }],
            },
            {
                "name": "second",
                "datasets": [{"name": "shared", "source": "public.shared_2", "fields": []}],
                "relationships": [{
                    "name": "shared_self",
                    "from": "shared",
                    "to": "shared",
                    "from_columns": ["id"],
                    "to_columns": ["parent_id"],
                }],
                "metrics": [{
                    "name": "shared_2_count",
                    "expression": {"dialects": [{"dialect": "ANSI_SQL", "expression": "COUNT(shared.id)"}]},
                }],
            },
        ],
    }
    projection = import_semantic_layer_from_ossie_yaml(
        __import__("yaml").safe_dump(plain, sort_keys=False), mode="projection-only"
    )

    assert [item["asset_id"] for item in projection["semantic_assets"]] == ["shared", "dim", "shared__2"]
    assert projection["relationships"] == [
        {
            "relationship_id": "shared_dim",
            "source": "shared.id",
            "target": "dim.id",
            "kind": "foreign_key",
            "review_status": "imported_projection",
        },
        {
            "relationship_id": "shared_self",
            "source": "shared__2.id",
            "target": "shared__2.parent_id",
            "kind": "foreign_key",
            "review_status": "imported_projection",
        },
    ]
    assert [item["contract_id"] for item in projection["metric_contracts"]] == ["shared_count", "shared_2_count"]
