from __future__ import annotations

from datetime import UTC, datetime

from pyshacl import validate as shacl_validate
from rdflib import RDF, RDFS, Graph, Literal, Namespace, URIRef
from rdflib.namespace import OWL, PROV, XSD

from data_agent.ontology.compiler import CompiledOntology, build_rdf
from data_agent.ontology.contracts import ConceptRecord, SourceRecord
from data_agent.ontology.domain_model import (
    CURATED_SOURCE_ID,
    class_id,
    class_uri,
    compile_curated_domain_ontology,
)
from data_agent.ontology.protege_export import (
    METAMODEL_SUPPORT_CLASSES,
    _strip_metamodel_support_classes,
)

EA_SOURCE = SourceRecord(
    source_id="ea-repository",
    source_kind="ea_repository",
    title="EA fixture",
    locator="test:ea",
    sha256="a" * 64,
)


def _flat_fixture() -> CompiledOntology:
    return CompiledOntology(
        sources=[EA_SOURCE],
        concepts=[
            ConceptRecord(
                concept_id="test:ea:package:smart-query",
                uri="https://example.test/ea/package/smart-query",
                kind="Package",
                code="11",
                pref_label="智能问数",
                source_system="enterprise_architect",
                source_id="ea-repository",
            ),
            ConceptRecord(
                concept_id="test:ea:table:parcel",
                uri="https://example.test/ea/table/parcel",
                kind="DatasetSchema",
                code="DLTB",
                pref_label="地类图斑",
                source_system="enterprise_architect",
                source_id="ea-repository",
            ),
        ],
        properties=[],
        relations=[],
        mappings=[],
        issues=[],
    )


def test_land_taxonomy_and_source_artifacts_have_distinct_modeling_roles():
    compiled = compile_curated_domain_ontology(_flat_fixture())
    concepts = {record.concept_id: record for record in compiled.concepts}

    assert class_id("Land") in concepts
    assert concepts[class_id("AgriculturalLand")].kind == "DomainClass"
    assert concepts[class_id("ConstructionOccupation")].kind == "ProcessClass"
    assert concepts[class_id("AgriculturalLandUseState")].kind == "StateClass"
    assert not any(record.pref_label == "智能问数" for record in compiled.concepts)
    assert concepts["test:ea:table:parcel"].kind == "SchemaArtifact"

    graph, _ = build_rdf(compiled)
    land = URIRef(class_uri("Land"))
    agricultural = URIRef(class_uri("AgriculturalLand"))
    construction = URIRef(class_uri("ConstructionLand"))
    cultivated = URIRef(class_uri("CultivatedLand"))
    non_cultivated = URIRef(class_uri("NonCultivatedAgriculturalLand"))
    schema = URIRef("https://example.test/ea/table/parcel")
    gda = Namespace("https://ontology.gis-data-agent.local/natural-resource/one-map/")

    assert (agricultural, RDFS.subClassOf, land) in graph
    assert (cultivated, RDFS.subClassOf, agricultural) in graph
    assert (non_cultivated, RDFS.subClassOf, agricultural) in graph
    assert (agricultural, OWL.disjointWith, construction) in graph
    assert (cultivated, OWL.disjointWith, non_cultivated) in graph
    assert (schema, RDF.type, gda.SchemaArtifact) in graph
    assert (schema, RDF.type, OWL.Class) not in graph


def _transition_graph(event_class: str, source_class: str, target_class: str) -> Graph:
    data = Graph()
    base = Namespace("https://example.test/resource/")
    prop = Namespace("https://ontology.gis-data-agent.local/natural-resource/one-map/property/")
    event = base.event
    parcel = base.parcel
    source = base.source_state
    target = base.target_state
    basis = base.legal_basis
    evidence = base.source_evidence
    data.add((event, RDF.type, URIRef(class_uri(event_class))))
    data.add((parcel, RDF.type, URIRef(class_uri("LandParcel"))))
    data.add((source, RDF.type, URIRef(class_uri(source_class))))
    data.add((target, RDF.type, URIRef(class_uri(target_class))))
    data.add((basis, RDF.type, URIRef(class_uri("LegalBasis"))))
    data.add((event, prop.affectsParcel, parcel))
    data.add((event, prop.hasSourceState, source))
    data.add((event, prop.hasTargetState, target))
    data.add(
        (
            event,
            prop.occurredAt,
            Literal(datetime(2026, 8, 4, tzinfo=UTC), datatype=XSD.dateTime),
        )
    )
    data.add((event, prop.supportedBy, basis))
    data.add((event, PROV.wasDerivedFrom, evidence))
    return data


def _validate_transition(data: Graph) -> tuple[bool, str]:
    compiled = compile_curated_domain_ontology(_flat_fixture())
    ontology, shapes = build_rdf(compiled)
    validation_graph = Graph()
    validation_graph += ontology
    validation_graph += data
    conforms, _, report = shacl_validate(
        validation_graph,
        shacl_graph=shapes,
        inference="rdfs",
        advanced=True,
    )
    return bool(conforms), str(report)


def test_agricultural_structure_adjustment_requires_opposite_agricultural_states():
    valid = _transition_graph(
        "AgriculturalStructureAdjustment",
        "CultivatedLandUseState",
        "NonCultivatedAgriculturalLandUseState",
    )
    invalid = _transition_graph(
        "AgriculturalStructureAdjustment",
        "CultivatedLandUseState",
        "CultivatedLandUseState",
    )

    assert _validate_transition(valid)[0] is True
    conforms, report = _validate_transition(invalid)
    assert conforms is False
    assert "农业结构调整" in report


def test_construction_occupation_requires_approval_basis_and_target_state():
    prop = Namespace("https://ontology.gis-data-agent.local/natural-resource/one-map/property/")
    valid = _transition_graph(
        "ConstructionOccupation",
        "AgriculturalLandUseState",
        "ConstructionLandUseState",
    )
    event = URIRef("https://example.test/resource/event")
    basis = URIRef("https://example.test/resource/legal-basis")
    approval = URIRef("https://example.test/resource/approval")
    valid.add((basis, RDF.type, URIRef(class_uri("LegalBasis"))))
    valid.add((approval, RDF.type, URIRef(class_uri("ApprovalDocument"))))
    valid.add((event, prop.supportedBy, basis))
    valid.add((event, prop.authorizedBy, approval))

    assert _validate_transition(valid)[0] is True

    invalid = _transition_graph(
        "ConstructionOccupation",
        "AgriculturalLandUseState",
        "UnusedLandUseState",
    )
    conforms, report = _validate_transition(invalid)
    assert conforms is False
    assert "ConstructionLandUseState" in report


def test_curated_source_is_versioned_and_present():
    compiled = compile_curated_domain_ontology(_flat_fixture())
    source = next(item for item in compiled.sources if item.source_id == CURATED_SOURCE_ID)
    assert source.source_version == "2.0.0"
    assert source.metadata["authority"] == "ADR-140"


def test_protege_domain_core_excludes_technical_metamodel_classes():
    graph = Graph()
    domain_class = URIRef(class_uri("Land"))
    for support_class in METAMODEL_SUPPORT_CLASSES:
        graph.add((support_class, RDF.type, OWL.Class))
    graph.add((domain_class, RDF.type, OWL.Class))

    _strip_metamodel_support_classes(graph)

    assert set(graph.subjects(RDF.type, OWL.Class)) == {domain_class}
