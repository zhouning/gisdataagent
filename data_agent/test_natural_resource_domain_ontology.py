from __future__ import annotations

import gzip
import json
from datetime import UTC, datetime
from functools import cache
from pathlib import Path

from pyshacl import validate as shacl_validate
from rdflib import RDF, RDFS, Graph, Literal, Namespace, URIRef
from rdflib.namespace import OWL, PROV, XSD

from data_agent.ontology.compiler import CompiledOntology, build_rdf, write_package
from data_agent.ontology.contracts import (
    BASE_URI,
    ConceptRecord,
    PropertyRecord,
    SourceRecord,
)
from data_agent.ontology.domain_model import (
    CURATED_MODEL_VERSION,
    CURATED_SOURCE_ID,
    DATA_PROPERTIES,
    class_id,
    class_uri,
    compile_curated_domain_ontology,
    property_uri,
)
from data_agent.ontology.protege_export import (
    METAMODEL_SUPPORT_CLASSES,
    _strip_metamodel_support_classes,
)
from scripts.analyze_natural_resource_ontology_evidence_expansion import analyze

REPO_ROOT = Path(__file__).resolve().parents[1]

EA_SOURCE = SourceRecord(
    source_id="ea-repository",
    source_kind="ea_repository",
    title="EA fixture",
    locator="test:ea",
    sha256="a" * 64,
)
STANDARD_SOURCE = SourceRecord(
    source_id="std-doc-01",
    source_kind="standard_document",
    title="Standard fixture",
    locator="test:standard",
    source_version="2025-draft",
    sha256="b" * 64,
)


def _flat_fixture() -> CompiledOntology:
    return CompiledOntology(
        sources=[EA_SOURCE, STANDARD_SOURCE],
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
                concept_id="test:standard:feature:cultivated-land",
                uri="https://example.test/standard/cultivated-land",
                kind="FeatureType",
                code="GD",
                pref_label="耕地",
                source_system="standard",
                source_id="std-doc-01",
                source_object_id="GD",
                provenance={
                    "heading": "5.1空间要素分层",
                    "occurrences": [{"heading": "5.1空间要素分层"}],
                },
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
            ConceptRecord(
                concept_id="test:ea:table:land-use-right",
                uri="https://example.test/ea/table/land-use-right",
                kind="DatasetSchema",
                code="建设用地使用权\\\\宅基地使用权 JSYDSYQ表",
                pref_label="JSYDSYQ表",
                source_system="enterprise_architect",
                source_id="ea-repository",
                package_path=(
                    "Model / 自然资源数据模型 / 03统一产权底板 / 0302不动产登记 / "
                    "030202国有建设用地使用权 / 逻辑模型"
                ),
            ),
        ],
        properties=[
            PropertyRecord(
                property_id="test:ea:field:parcel-area",
                owner_concept_id="test:ea:table:parcel",
                uri="https://example.test/ea/field/parcel-area",
                code="TBMJ",
                pref_label="图斑面积",
                datatype="xsd:double",
                source_id="ea-repository",
            ),
            PropertyRecord(
                property_id="test:ea:field:shape",
                owner_concept_id="test:ea:table:parcel",
                uri="https://example.test/ea/field/shape",
                code="SHAPE",
                pref_label="空间几何",
                datatype="geo:wktLiteral",
                source_id="ea-repository",
            ),
            PropertyRecord(
                property_id="test:ea:field:real-estate-unit",
                owner_concept_id="test:ea:table:land-use-right",
                uri="https://example.test/ea/field/real-estate-unit",
                code="不动产单元号",
                pref_label="不动产单元号",
                source_id="ea-repository",
            ),
        ],
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
    assert source.source_version == CURATED_MODEL_VERSION
    assert source.metadata["authority"] == "ADR-140;ADR-162;ADR-163"


def test_curated_compilation_is_idempotent_and_has_unique_record_ids():
    first = compile_curated_domain_ontology(_flat_fixture())
    second = compile_curated_domain_ontology(first)

    for first_records, second_records, id_field in (
        (first.concepts, second.concepts, "concept_id"),
        (first.properties, second.properties, "property_id"),
        (first.relations, second.relations, "relation_id"),
        (first.mappings, second.mappings, "mapping_id"),
    ):
        first_ids = [getattr(record, id_field) for record in first_records]
        second_ids = [getattr(record, id_field) for record in second_records]
        assert len(first_ids) == len(set(first_ids))
        assert len(second_ids) == len(set(second_ids))
        assert set(second_ids) == set(first_ids)


def test_land_parcel_is_a_spatial_unit_and_land_has_three_direct_categories():
    compiled = compile_curated_domain_ontology(_flat_fixture())
    graph, _ = build_rdf(compiled)
    land = URIRef(class_uri("Land"))
    parcel = URIRef(class_uri("LandParcel"))
    spatial_unit = URIRef(class_uri("SpatialUnit"))
    expected_children = {
        URIRef(class_uri("AgriculturalLand")),
        URIRef(class_uri("ConstructionLand")),
        URIRef(class_uri("UnusedLand")),
    }
    named_children = {
        child
        for child in graph.subjects(RDFS.subClassOf, land)
        if (child, RDF.type, OWL.Class) in graph
    }

    assert named_children == expected_children
    assert (parcel, RDFS.subClassOf, spatial_unit) in graph
    assert (parcel, RDFS.subClassOf, land) not in graph
    assert (land, OWL.disjointWith, spatial_unit) in graph


def test_attachment_scope_has_explicit_built_water_admin_and_indicator_layers():
    compiled = compile_curated_domain_ontology(_flat_fixture())
    graph, _ = build_rdf(compiled, semantic_version=CURATED_MODEL_VERSION)
    expected_subclasses = {
        "Building": "BuiltStructure",
        "EducationalFacility": "PublicFacility",
        "Canal": "SurfaceWaterBody",
        "Pond": "SurfaceWaterBody",
        "Village": "AdministrativeUnit",
        "VillageCommitteeSite": "AdministrativePlace",
        "UrbanBlueLine": "UrbanFourLine",
        "UrbanFormAssessment": "QualityAssessment",
        "AccessibilityIndicator": "BuiltEnvironmentIndicator",
        "ServiceCoverageObservation": "NaturalResourceObservation",
    }

    for child, parent in expected_subclasses.items():
        assert (
            URIRef(class_uri(child)),
            RDFS.subClassOf,
            URIRef(class_uri(parent)),
        ) in graph

    property_ns = Namespace(f"{BASE_URI}property/")
    assert (
        property_ns.representsAdministrativeUnit,
        RDFS.domain,
        URIRef(class_uri("AdministrativePlace")),
    ) in graph
    assert (
        property_ns.hasMeasurement,
        RDFS.range,
        URIRef(class_uri("Measurement")),
    ) in graph


def test_attachment_fields_map_to_stable_curated_data_properties():
    compiled = compile_curated_domain_ontology(_flat_fixture())
    curated_properties = {
        record.code: record
        for record in compiled.properties
        if record.source_id == CURATED_SOURCE_ID
    }
    expected = {
        "buildingHeight": ("Building", "JZGD"),
        "floorAreaRatio": ("UrbanFormAssessment", "JRJL"),
        "fireRescue5MinuteCoverageRate": ("ServiceCoverageObservation", None),
        "meanWaterDepth": ("SurfaceWaterBody", None),
        "artificialChannelFlag": ("SurfaceWaterBody", None),
        "landSeaUseClassificationName": ("PlannedLandUseArea", "YDYHFLMC"),
    }

    assert len(curated_properties) == len(DATA_PROPERTIES)
    for property_name, (owner, source_code) in expected.items():
        record = curated_properties[property_name]
        assert record.owner_concept_id == class_id(owner)
        assert record.provenance["modeling_role"] == "curated_domain_data_property"
        if source_code:
            assert source_code in record.provenance["source_field_codes"]


def test_schema_fields_have_explicit_rdf_semantic_dispositions():
    compiled = compile_curated_domain_ontology(_flat_fixture())
    graph, _ = build_rdf(compiled, semantic_version=CURATED_MODEL_VERSION)
    gda = Namespace(BASE_URI)
    property_ns = Namespace(f"{BASE_URI}property/")
    parcel_area = URIRef("https://example.test/ea/field/parcel-area")
    shape = URIRef("https://example.test/ea/field/shape")
    registration_unit = URIRef("https://example.test/ea/field/real-estate-unit")

    assert (parcel_area, RDF.type, gda.SchemaField) in graph
    assert (parcel_area, RDF.type, OWL.DatatypeProperty) not in graph
    assert (parcel_area, gda.mapsToProperty, URIRef(property_uri("parcelArea"))) in graph
    assert (
        parcel_area,
        gda.semanticDisposition,
        Literal("mapped_domain_property"),
    ) in graph
    assert (
        shape,
        gda.semanticDisposition,
        Literal("schema_implementation_only"),
    ) in graph
    assert (
        registration_unit,
        gda.mapsToRelation,
        property_ns.hasRegistrationUnit,
    ) in graph


@cache
def _evidence_audit() -> dict[str, object]:
    return analyze(
        REPO_ROOT / "docs/analysis/natural-resource-ontology-attachment-coverage-0804.json",
        REPO_ROOT / "data_agent/ontology/packages/natural_resource_one_map/2.2.0",
    )


def test_dltb_full_standard_schema_has_no_unresolved_semantic_fields():
    payload = _evidence_audit()
    fields = [row for row in payload["expanded_fields"] if row["schema_code"] == "DLTB"]

    assert len(fields) == 30
    assert all(
        row["semantic_status"]
        not in {
            "unresolved_domain_field",
            "ambiguous_property_mapping",
        }
        for row in fields
    )


def test_attachment_is_a_minimum_baseline_and_evidence_gaps_are_explicit():
    payload = _evidence_audit()
    summary = payload["summary"]
    unmatched = {
        (row["source_layer"], row["source_layer_code"])
        for row in payload["layers"]
        if row["status"] != "matched"
    }

    assert summary["attachment_row_count"] == 269
    assert summary["expanded_field_count"] == 390
    assert summary["unresolved_or_ambiguous_field_count"] == 0
    assert unmatched == {
        ("城市房屋建筑", "FWJZ"),
        ("规划地块评估", "GHDKPG"),
        ("社区村评估", "SQCPG"),
        ("", "PLAPT"),
        ("殡葬设施面", ""),
    }


def test_inverse_functional_and_qualified_cardinality_axioms_are_materialized():
    compiled = compile_curated_domain_ontology(_flat_fixture())
    graph, _ = build_rdf(compiled, semantic_version=CURATED_MODEL_VERSION)
    property_ns = Namespace(f"{BASE_URI}property/")
    parcel = URIRef(class_uri("LandParcel"))
    land = URIRef(class_uri("Land"))
    ontology_uri = URIRef(BASE_URI.rstrip("/"))

    assert (property_ns.spatiallyRepresents, RDF.type, OWL.FunctionalProperty) in graph
    assert (
        property_ns.spatiallyRepresents,
        OWL.inverseOf,
        property_ns.representedBySpatialUnit,
    ) in graph
    assert (
        ontology_uri,
        OWL.versionIRI,
        URIRef(f"{BASE_URI}version/{CURATED_MODEL_VERSION}"),
    ) in graph
    restrictions = list(graph.objects(parcel, RDFS.subClassOf))
    assert any(
        (restriction, OWL.onProperty, property_ns.spatiallyRepresents) in graph
        and (restriction, OWL.onClass, land) in graph
        and (
            restriction,
            OWL.qualifiedCardinality,
            Literal(1, datatype=XSD.nonNegativeInteger),
        )
        in graph
        for restriction in restrictions
    )


def test_curated_classes_have_source_evidence_or_an_explicit_gap_and_dispositions():
    flat = _flat_fixture()
    compiled = compile_curated_domain_ontology(flat)
    concepts = {record.concept_id: record for record in compiled.concepts}
    cultivated = concepts[class_id("CultivatedLand")]
    land = concepts[class_id("Land")]

    assert cultivated.provenance["evidence_status"] == "source_matches_found"
    assert cultivated.provenance["source_evidence"][0]["source_id"] == "std-doc-01"
    assert land.provenance["evidence_status"] == "explicit_evidence_gap"
    assert all(
        record.provenance.get("evidence_status")
        in {
            "source_matches_found",
            "explicit_evidence_gap",
        }
        for record in concepts.values()
        if record.source_system == "curated_domain"
    )
    dispositions = {record["candidate_id"]: record for record in compiled.review_dispositions}
    assert dispositions[class_id("CultivatedLand")]["disposition"] == "accepted"
    assert dispositions["test:standard:feature:cultivated-land"]["disposition"] == "mapped"
    assert dispositions["test:ea:package:smart-query"]["disposition"] == "rejected"


def test_package_contains_executable_semantic_quality_artifacts(tmp_path):
    compiled = compile_curated_domain_ontology(_flat_fixture())
    package_dir = tmp_path / CURATED_MODEL_VERSION
    manifest = write_package(
        compiled,
        package_dir,
        semantic_version=CURATED_MODEL_VERSION,
        generated_at=datetime(2026, 8, 5, tzinfo=UTC),
    )

    assert manifest.validation_summary["conforms"] is True
    assert manifest.stats["competency_question_count"] >= 8
    assert (
        manifest.stats["competency_question_count"]
        == manifest.stats["competency_question_passed_count"]
    )
    assert manifest.stats["unsatisfiable_named_class_count"] == 0
    for artifact_name in (
        "review_dispositions",
        "competency_report",
        "semantic_quality_report",
        "completeness_report",
    ):
        assert artifact_name in manifest.artifacts

    competency = json.loads((package_dir / "competency-report.json").read_text(encoding="utf-8"))
    semantic_quality = json.loads(
        (package_dir / "semantic-quality-report.json").read_text(encoding="utf-8")
    )
    completeness = json.loads(
        (package_dir / "completeness-report.json").read_text(encoding="utf-8")
    )
    with gzip.open(package_dir / "review-dispositions.jsonl.gz", "rt", encoding="utf-8") as stream:
        dispositions = [json.loads(line) for line in stream if line.strip()]

    assert competency["conforms"] is True
    assert semantic_quality["unsatisfiable_named_class_count"] == 0
    assert completeness["status"] == "open_pending_expert_review"
    assert completeness["expert_review"]["closure_allowed"] is False
    assert len(dispositions) == len(compiled.review_dispositions)


def test_protege_domain_core_excludes_technical_metamodel_classes():
    graph = Graph()
    domain_class = URIRef(class_uri("Land"))
    for support_class in METAMODEL_SUPPORT_CLASSES:
        graph.add((support_class, RDF.type, OWL.Class))
    graph.add((domain_class, RDF.type, OWL.Class))

    _strip_metamodel_support_classes(graph)

    assert set(graph.subjects(RDF.type, OWL.Class)) == {domain_class}
