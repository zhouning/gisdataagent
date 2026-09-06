"""Loss-aware standards interchange for GDA runtime semantic assets.

The Abu Dhabi assets intentionally have a richer contract than OWL, SKOS or
SHACL alone can express (execution gates, source fingerprints, metric
contracts and provenance).  The exporter therefore emits a standards
projection *and* a GDA extension payload.  The latter is not a workaround: it
is the documented lossless bridge between the runtime contract and standards
vocabularies.  Imports are explicit about whether the caller wants a lossless
runtime reconstruction or a projection-only business ontology.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable, Mapping

import yaml


ONTOLOGY_SCHEMA = "gda.ontology-runtime-overlay.v1"
SEMANTIC_SCHEMA = "gda.multilingual-virtual-semantic-layer.v1"
INTEROP_FORMAT = "gda-semantic-interop-v1"
OSSIE_VERSION = "0.2.0.dev0"
DEFAULT_BASE_URI = "https://ontology.gis-data-agent.local/abu-dhabi/"
GDA_NS = DEFAULT_BASE_URI + "vocab/"


class InteropError(ValueError):
    """Raised when a standards asset cannot satisfy the selected import mode."""


def _rdflib():
    try:
        from rdflib import BNode, Graph, Literal, Namespace, RDF, RDFS, URIRef, XSD
    except ImportError as exc:  # pragma: no cover - exercised only in lite installs
        raise InteropError(
            "RDF/OWL/JSON-LD interchange requires the optional 'full' dependencies "
            "(rdflib and pyshacl); install the full profile first"
        ) from exc
    return BNode, Graph, Literal, Namespace, RDF, RDFS, URIRef, XSD


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _read_payload(source: str | Path | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(source, Mapping):
        return dict(source)
    path = Path(source).expanduser()
    return json.loads(path.read_text(encoding="utf-8"))


def _write_text(destination: str | Path | None, content: str) -> str:
    if destination is None:
        return content
    path = Path(destination).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return str(path)


def _write_bytes(destination: str | Path | None, content: bytes) -> str:
    if destination is None:
        return content.decode("utf-8")
    path = Path(destination).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return str(path)


def _safe_token(value: Any) -> str:
    token = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "").strip())
    return token.strip("_") or "anonymous"


def _uri(base: str, kind: str, value: Any) -> str:
    return f"{base.rstrip('/')}/{kind}/{_safe_token(value)}"


def _literal(value: Any, Literal, XSD):
    if value is None:
        return Literal("")
    if isinstance(value, bool):
        return Literal(value, datatype=XSD.boolean)
    if isinstance(value, int):
        return Literal(value, datatype=XSD.integer)
    if isinstance(value, float):
        return Literal(value, datatype=XSD.double)
    if isinstance(value, (dict, list)):
        return Literal(_canonical_json(value), datatype=XSD.string)
    return Literal(str(value))


def _put_json_literal(graph, subject, predicate, value, Literal, XSD) -> None:
    if value is not None:
        graph.add((subject, predicate, _literal(value, Literal, XSD)))


def _payload_identity(payload: Mapping[str, Any]) -> tuple[str, str, str]:
    schema = str(payload.get("schema") or "")
    version = str(payload.get("semantic_version") or payload.get("ontology_enrichment_version") or "")
    digest = _sha256_json(payload)
    return schema, version, digest


def _document_kind(payload: Mapping[str, Any]) -> str:
    schema = payload.get("schema")
    if schema == ONTOLOGY_SCHEMA:
        return "ontology"
    if schema == SEMANTIC_SCHEMA:
        return "semantic_layer"
    raise InteropError(f"unsupported runtime schema: {schema!r}")


def _jsonld_context(base: str) -> dict[str, Any]:
    return {
        "gda": GDA_NS,
        "owl": "http://www.w3.org/2002/07/owl#",
        "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
        "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
        "skos": "http://www.w3.org/2004/02/skos/core#",
        "sh": "http://www.w3.org/ns/shacl#",
        "dcterms": "http://purl.org/dc/terms/",
        "xsd": "http://www.w3.org/2001/XMLSchema#",
        "gdaDocument": {"@id": "gda:document", "@type": "@id"},
        "gdaPayload": "gda:originalJson",
        "gdaPayloadSha256": "gda:payloadSha256",
        "gdaSemanticVersion": "gda:semanticVersion",
        "gdaSourceId": "gda:sourceId",
        "gdaPhysicalBinding": "gda:physicalBinding",
        "gdaBusinessRole": "gda:businessRole",
        "gdaValueDomain": {"@id": "gda:valueDomain", "@container": "@set"},
        "gdaMetricContract": {"@id": "gda:metricContract", "@container": "@set"},
        "gdaRelationshipBinding": "gda:relationshipBinding",
        "@base": base,
    }


def _add_document_metadata(graph, payload, kind, base, *, BNode, Literal, Namespace, RDF, URIRef, XSD):
    gda = Namespace(GDA_NS)
    owl = Namespace("http://www.w3.org/2002/07/owl#")
    dcterms = Namespace("http://purl.org/dc/terms/")
    doc = URIRef(_uri(base, "document", f"{kind}-{payload.get('semantic_version') or payload.get('ontology_enrichment_version') or 'unversioned'}"))
    graph.add((doc, RDF.type, owl.Ontology))
    graph.add((doc, gda["format"], Literal(INTEROP_FORMAT)))
    graph.add((doc, gda["runtimeSchema"], Literal(payload.get("schema"))))
    schema, version, digest = _payload_identity(payload)
    graph.add((doc, gda["payloadSha256"], Literal(digest)))
    graph.add((doc, gda["payloadSchema"], Literal(schema)))
    if version:
        graph.add((doc, gda["semanticVersion"], Literal(version)))
    source_binding = payload.get("source_binding") or payload.get("source_evidence") or {}
    if source_binding.get("source_id") is not None:
        graph.add((doc, gda["sourceId"], _literal(source_binding["source_id"], Literal, XSD)))
    if source_binding.get("database_name"):
        graph.add((doc, dcterms.source, Literal(source_binding["database_name"])))
    # The original document is deliberately retained as an extension literal.
    # It makes round-trip losslessness testable and prevents silent field loss.
    graph.add((doc, gda["originalJson"], Literal(_canonical_json(payload), datatype=XSD.string)))
    return doc, gda


def _add_labels(graph, subject, labels, *, SKOS, Literal):
    if isinstance(labels, Mapping):
        for language, label in labels.items():
            if label:
                graph.add((subject, SKOS.prefLabel, Literal(str(label), lang=str(language))))
    elif labels:
        graph.add((subject, SKOS.prefLabel, Literal(str(labels))))


def _add_aliases(graph, subject, aliases, *, SKOS, Literal):
    for alias in aliases or []:
        if alias:
            graph.add((subject, SKOS.altLabel, Literal(str(alias))))


def _field_uri(base: str, entity_id: str, field: str) -> str:
    return _uri(base, "property", f"{entity_id}--{field}")


def _entity_id(item: Mapping[str, Any]) -> str:
    return str(item.get("concept_id") or item.get("asset_id") or item.get("semantic_entity") or item.get("physical_binding") or "anonymous")


def _iter_ontology_entities(payload: Mapping[str, Any]) -> Iterable[Mapping[str, Any]]:
    for item in payload.get("concepts") or []:
        if isinstance(item, Mapping):
            yield item


def _iter_semantic_entities(payload: Mapping[str, Any]) -> Iterable[Mapping[str, Any]]:
    seen: set[str] = set()
    for item in payload.get("semantic_assets") or []:
        if isinstance(item, Mapping):
            key = str(item.get("asset_id") or item.get("semantic_entity") or item.get("physical_tables"))
            seen.add(key)
            yield item
    # Technical bindings without a business asset must remain visible in the
    # standard projection; they are deliberately marked technical-only.
    for item in payload.get("table_bindings") or []:
        if not isinstance(item, Mapping):
            continue
        key = str(item.get("semantic_entity") or item.get("physical_table"))
        if key not in seen:
            yield item


def _entity_physical_binding(entity: Mapping[str, Any]) -> str | None:
    direct = entity.get("physical_binding") or entity.get("physical_table")
    if direct:
        return str(direct)
    tables = entity.get("physical_tables") or []
    return str(tables[0]) if tables else None


def _add_entity(graph, entity, *, kind, base, doc, gda, BNode, Literal, Namespace, URIRef, OWL, RDF, RDFS, SKOS, XSD):
    entity_id = _entity_id(entity)
    subject = URIRef(_uri(base, "concept", entity_id))
    graph.add((subject, RDF.type, OWL.Class))
    _add_labels(graph, subject, entity.get("labels"), SKOS=SKOS, Literal=Literal)
    _add_aliases(graph, subject, entity.get("aliases"), SKOS=SKOS, Literal=Literal)
    description = entity.get("description") or entity.get("business_description")
    if description:
        graph.add((subject, RDFS.comment, Literal(str(description))))
    graph.add((subject, gda["document"], doc))
    graph.add((subject, gda["runtimeKind"], Literal(kind)))
    physical = _entity_physical_binding(entity)
    if physical:
        graph.add((subject, gda["physicalBinding"], Literal(physical)))
    for prop, key in ((gda["reviewStatus"], "review_status"), (gda["bindingStatus"], "binding_status"), (gda["semanticCoverageStatus"], "semantic_coverage_status")):
        if entity.get(key) is not None:
            graph.add((subject, prop, Literal(str(entity[key]))))
    for field in entity.get("fields") or []:
        if not isinstance(field, Mapping):
            continue
        field_name = str(field.get("semantic_field") or field.get("physical_field") or "field")
        prop_subject = URIRef(_field_uri(base, entity_id, field_name))
        graph.add((prop_subject, RDF.type, OWL.DatatypeProperty))
        graph.add((prop_subject, RDFS.domain, subject))
        labels = field.get("labels") or {"en": field_name}
        _add_labels(graph, prop_subject, labels, SKOS=SKOS, Literal=Literal)
        _add_aliases(graph, prop_subject, field.get("aliases"), SKOS=SKOS, Literal=Literal)
        if field.get("description") or field.get("definition"):
            graph.add((prop_subject, RDFS.comment, Literal(str(field.get("description") or field.get("definition")))))
        graph.add((prop_subject, gda["physicalBinding"], Literal(str(field.get("physical_field") or field_name))))
        graph.add((prop_subject, gda["semanticField"], Literal(field_name)))
        graph.add((prop_subject, gda["businessRole"], Literal(str(field.get("business_role") or "attribute"))))
        if field.get("definition_status"):
            graph.add((prop_subject, gda["definitionStatus"], Literal(str(field["definition_status"]))))
        technical = field.get("technical_metadata") or {}
        if technical.get("data_type"):
            graph.add((prop_subject, gda["dataType"], Literal(str(technical["data_type"]))))
        if technical.get("nullable") is not None:
            graph.add((prop_subject, gda["nullable"], _literal(technical["nullable"], Literal, XSD)))
        domain = field.get("value_domain")
        for value in (domain if isinstance(domain, list) else []):
            graph.add((prop_subject, gda["valueDomain"], Literal(str(value))))
        graph.add((prop_subject, gda["document"], doc))
        graph.add((subject, gda["hasField"], prop_subject))
    return subject


def _add_relationships(graph, payload, *, base, doc, gda, Literal, RDF, OWL, XSD):
    URIRef = __import__("rdflib", fromlist=["URIRef"]).URIRef
    relationships = list(payload.get("relationships") or []) + list(payload.get("relations") or [])
    for index, relation in enumerate(relationships):
        if not isinstance(relation, Mapping):
            continue
        left = relation.get("left") or relation.get("source") or relation.get("source_concept")
        right = relation.get("right") or relation.get("target") or relation.get("target_concept")
        rid = relation.get("relationship_id") or relation.get("relation_id") or f"{left}-{right}-{index}"
        subject = URIRef(_uri(base, "relationship", hashlib.sha1(str(rid).encode()).hexdigest()[:20]))
        graph.add((subject, RDF.type, OWL.ObjectProperty))
        graph.add((subject, gda["relationshipBinding"], Literal(f"{left or ''} -> {right or ''}")))
        graph.add((subject, gda["relationshipId"], Literal(str(rid))))
        if left is not None:
            graph.add((subject, gda["relationshipSource"], Literal(str(left))))
        if right is not None:
            graph.add((subject, gda["relationshipTarget"], Literal(str(right))))
        for key in ("kind", "operator", "cardinality", "review_status", "notes"):
            if relation.get(key) is not None:
                graph.add((subject, gda[_safe_token(key)], Literal(str(relation[key]))))
        graph.add((subject, gda["document"], doc))


def _add_metric_contracts(graph, payload, *, base, doc, gda, Literal, RDF, OWL, XSD):
    URIRef = __import__("rdflib", fromlist=["URIRef"]).URIRef
    for metric in payload.get("metric_contracts") or []:
        if not isinstance(metric, Mapping):
            continue
        contract_id = metric.get("contract_id") or metric.get("id") or "metric"
        subject = URIRef(_uri(base, "metric", contract_id))
        graph.add((subject, RDF.type, gda["MetricContract"]))
        graph.add((subject, gda["document"], doc))
        graph.add((subject, gda["contractId"], Literal(str(contract_id))))
        for key in ("operation", "review_status", "priority", "canonical_sql_template"):
            if metric.get(key) is not None:
                graph.add((subject, gda[_safe_token(key)], _literal(metric[key], Literal, XSD)))
        for table in metric.get("tables") or []:
            graph.add((subject, gda["physicalBinding"], Literal(str(table))) )


def _add_value_domains(graph, payload, *, base, doc, gda, Literal, RDF, SKOS):
    URIRef = __import__("rdflib", fromlist=["URIRef"]).URIRef
    domains: dict[str, list[Any]] = {}
    for entity in list(_iter_ontology_entities(payload)) + list(_iter_semantic_entities(payload)):
        for field in entity.get("fields") or []:
            values = field.get("value_domain")
            if isinstance(values, list) and values:
                domain_id = f"{_entity_id(entity)}--{field.get('semantic_field') or field.get('physical_field')}"
                domains[domain_id] = values
    for domain_id, values in domains.items():
        scheme = URIRef(_uri(base, "value-domain", domain_id))
        graph.add((scheme, RDF.type, SKOS.ConceptScheme))
        graph.add((scheme, gda["document"], doc))
        for value in values:
            concept = URIRef(_uri(base, "value", f"{domain_id}--{value}"))
            graph.add((concept, RDF.type, SKOS.Concept))
            graph.add((concept, SKOS.inScheme, scheme))
            graph.add((concept, SKOS.prefLabel, Literal(str(value))))


def _add_shapes(graph, payload, *, base, gda, BNode, Literal, Namespace, RDF, SH, XSD):
    """Emit basic SHACL shapes without claiming metric contracts are SHACL."""
    URIRef = __import__("rdflib", fromlist=["URIRef"]).URIRef
    for entity in _iter_ontology_entities(payload) if _document_kind(payload) == "ontology" else _iter_semantic_entities(payload):
        entity_id = _entity_id(entity)
        shape = URIRef(_uri(base, "shape", entity_id))
        target = URIRef(_uri(base, "concept", entity_id))
        graph.add((shape, RDF.type, SH.NodeShape))
        graph.add((shape, SH.targetClass, target))
        for field in entity.get("fields") or []:
            field_name = str(field.get("semantic_field") or field.get("physical_field") or "field")
            prop = URIRef(_field_uri(base, entity_id, field_name))
            pshape = BNode()
            graph.add((shape, SH.property, pshape))
            graph.add((pshape, SH.path, prop))
            technical = field.get("technical_metadata") or {}
            if technical.get("nullable") is False:
                graph.add((pshape, SH.minCount, Literal(1, datatype=XSD.integer)))
            if isinstance(field.get("value_domain"), list) and field["value_domain"]:
                members = BNode()
                graph.add((pshape, SH["in"], members))
                values = [Literal(str(value)) for value in field["value_domain"]]
                collection = graph.collection(members)
                collection += values


def _build_graph(payload: Mapping[str, Any], *, include_shapes: bool = True, base: str = DEFAULT_BASE_URI):
    BNode, Graph, Literal, Namespace, RDF, RDFS, URIRef, XSD = _rdflib()
    OWL = Namespace("http://www.w3.org/2002/07/owl#")
    SKOS = Namespace("http://www.w3.org/2004/02/skos/core#")
    SH = Namespace("http://www.w3.org/ns/shacl#")
    kind = _document_kind(payload)
    graph = Graph()
    doc, gda = _add_document_metadata(
        graph, payload, kind, base, BNode=BNode, Literal=Literal, Namespace=Namespace,
        RDF=RDF, URIRef=URIRef, XSD=XSD,
    )
    if kind == "ontology":
        entities = _iter_ontology_entities(payload)
    else:
        entities = _iter_semantic_entities(payload)
    for entity in entities:
        _add_entity(
            graph, entity, kind=kind, base=base, doc=doc, gda=gda, BNode=BNode,
            Literal=Literal, Namespace=Namespace, OWL=OWL, RDF=RDF, RDFS=RDFS,
            URIRef=URIRef, SKOS=SKOS, XSD=XSD,
        )
    _add_relationships(graph, payload, base=base, doc=doc, gda=gda, Literal=Literal, RDF=RDF, OWL=OWL, XSD=XSD)
    _add_metric_contracts(graph, payload, base=base, doc=doc, gda=gda, Literal=Literal, RDF=RDF, OWL=OWL, XSD=XSD)
    _add_value_domains(graph, payload, base=base, doc=doc, gda=gda, Literal=Literal, RDF=RDF, SKOS=SKOS)
    if include_shapes:
        _add_shapes(graph, payload, base=base, gda=gda, BNode=BNode, Literal=Literal, Namespace=Namespace, RDF=RDF, SH=SH, XSD=XSD)
    graph.bind("gda", gda)
    graph.bind("owl", OWL)
    graph.bind("skos", SKOS)
    graph.bind("sh", SH)
    graph.bind("rdfs", RDFS)
    return graph


def _serialize(payload: Mapping[str, Any], fmt: str, *, include_shapes: bool = True, base: str = DEFAULT_BASE_URI) -> str:
    graph = _build_graph(payload, include_shapes=include_shapes, base=base)
    rendered = graph.serialize(format=fmt)
    return rendered.decode("utf-8") if isinstance(rendered, bytes) else str(rendered)


def export_ontology_to_turtle(source, destination=None, *, include_shapes=True, base=DEFAULT_BASE_URI):
    payload = _read_payload(source)
    if _document_kind(payload) != "ontology":
        raise InteropError("export_ontology_to_turtle expects the ontology runtime schema")
    return _write_text(destination, _serialize(payload, "turtle", include_shapes=include_shapes, base=base))


def export_semantic_layer_to_turtle(source, destination=None, *, include_shapes=True, base=DEFAULT_BASE_URI):
    payload = _read_payload(source)
    if _document_kind(payload) != "semantic_layer":
        raise InteropError("export_semantic_layer_to_turtle expects the semantic-layer runtime schema")
    return _write_text(destination, _serialize(payload, "turtle", include_shapes=include_shapes, base=base))


def _serialize_jsonld(payload, *, include_shapes=True, base=DEFAULT_BASE_URI):
    graph = _build_graph(payload, include_shapes=include_shapes, base=base)
    rendered = graph.serialize(format="json-ld", auto_compact=True, context=_jsonld_context(base), indent=2)
    return rendered.decode("utf-8") if isinstance(rendered, bytes) else str(rendered)


def export_ontology_to_jsonld(source, destination=None, *, include_shapes=True, base=DEFAULT_BASE_URI):
    payload = _read_payload(source)
    if _document_kind(payload) != "ontology":
        raise InteropError("export_ontology_to_jsonld expects the ontology runtime schema")
    return _write_text(destination, _serialize_jsonld(payload, include_shapes=include_shapes, base=base))


def export_semantic_layer_to_jsonld(source, destination=None, *, include_shapes=True, base=DEFAULT_BASE_URI):
    payload = _read_payload(source)
    if _document_kind(payload) != "semantic_layer":
        raise InteropError("export_semantic_layer_to_jsonld expects the semantic-layer runtime schema")
    return _write_text(destination, _serialize_jsonld(payload, include_shapes=include_shapes, base=base))


def export_semantic_layer_to_yaml(source, destination=None):
    payload = _read_payload(source)
    if _document_kind(payload) != "semantic_layer":
        raise InteropError("export_semantic_layer_to_yaml expects the semantic-layer runtime schema")
    content = yaml.safe_dump(payload, allow_unicode=True, sort_keys=False)
    return _write_text(destination, content)


# ---------------------------------------------------------------------------
# Apache Ossie Core Metadata Specification (0.2.0.dev0) projection
# ---------------------------------------------------------------------------

_OSSIE_TYPES = {
    "string": "String",
    "text": "String",
    "varchar": "String",
    "character varying": "String",
    "integer": "Integer",
    "bigint": "Integer",
    "smallint": "Integer",
    "numeric": "Decimal",
    "decimal": "Decimal",
    "real": "Float",
    "double precision": "Float",
    "double": "Float",
    "float": "Float",
    "boolean": "Boolean",
    "date": "Date",
    "time": "Time",
    "timestamp": "DateTime",
    "timestamp without time zone": "DateTime",
    "timestamp with time zone": "DateTimeTz",
    "timestamptz": "DateTimeTz",
}


def _ossie_type(field: Mapping[str, Any]) -> str | None:
    technical = field.get("technical_metadata") or {}
    raw = str(technical.get("data_type") or technical.get("datatype") or "").strip().lower()
    if not raw:
        return None
    for source, target in _OSSIE_TYPES.items():
        if raw == source or raw.startswith(source + "("):
            return target
    return "Opaque"


def _ossie_ai_context(entity: Mapping[str, Any], *, instructions: str | None = None) -> dict[str, Any]:
    context: dict[str, Any] = {}
    aliases = [str(value) for value in entity.get("aliases") or [] if value]
    if aliases:
        context["synonyms"] = aliases
    if instructions:
        context["instructions"] = instructions
    return context


def _ossie_extension(vendor_name: str, data: Mapping[str, Any]) -> dict[str, str]:
    return {"vendor_name": vendor_name, "data": _canonical_json(dict(data))}


def _ossie_dataset_name(entity: Mapping[str, Any], used: set[str]) -> str:
    candidate = str(entity.get("asset_id") or entity.get("semantic_entity") or entity.get("physical_table") or "dataset")
    if candidate not in used:
        used.add(candidate)
        return candidate
    index = 2
    while f"{candidate}__{index}" in used:
        index += 1
    result = f"{candidate}__{index}"
    used.add(result)
    return result


def _ossie_field(field: Mapping[str, Any]) -> dict[str, Any]:
    field_name = str(field.get("semantic_field") or field.get("physical_field") or "field")
    physical = str(field.get("physical_field") or field_name)
    labels = field.get("labels") or {}
    label = labels.get("en") if isinstance(labels, Mapping) else None
    if not label and isinstance(labels, Mapping):
        label = next((str(value) for value in labels.values() if value), None)
    role = str(field.get("business_role") or "attribute")
    item: dict[str, Any] = {
        "name": field_name,
        "expression": {"dialects": [{"dialect": "ANSI_SQL", "expression": physical}]},
        "label": label or field_name,
        "description": str(field.get("description") or field.get("definition") or ""),
    }
    datatype = _ossie_type(field)
    if datatype:
        item["datatype"] = datatype
    item["dimension"] = {"is_time": role == "temporal_dimension"}
    aliases = []
    if isinstance(labels, Mapping):
        aliases.extend(str(value) for key, value in labels.items() if key != "en" and value)
    aliases.extend(str(value) for value in field.get("aliases") or [] if value)
    if aliases:
        item["ai_context"] = {"synonyms": list(dict.fromkeys(aliases))}
    extension_data = {
        "physical_field": physical,
        "business_role": role,
        "definition_status": field.get("definition_status"),
        "semantic_status": field.get("semantic_status"),
        "technical_metadata": field.get("technical_metadata") or {},
        "value_domain": field.get("value_domain"),
    }
    item["custom_extensions"] = [_ossie_extension("GDA", extension_data)]
    return item


def _ossie_entities(payload: Mapping[str, Any]) -> tuple[list[Mapping[str, Any]], dict[str, str], dict[str, str]]:
    entities = list(_iter_semantic_entities(payload))
    used: set[str] = set()
    datasets: list[dict[str, Any]] = []
    logical_by_table: dict[str, str] = {}
    logical_by_entity: dict[str, str] = {}
    for entity in entities:
        logical_name = _ossie_dataset_name(entity, used)
        entity_id = _entity_id(entity)
        logical_by_entity[entity_id] = logical_name
        physical_tables = [str(value) for value in entity.get("physical_tables") or [] if value]
        physical = _entity_physical_binding(entity)
        if physical and physical not in physical_tables:
            physical_tables.insert(0, physical)
        source = physical_tables[0] if physical_tables else str(entity.get("physical_table") or entity_id)
        for table in physical_tables:
            logical_by_table[table] = logical_name
        fields = list(entity.get("fields") or [])
        primary_key = [str(field.get("physical_field") or field.get("semantic_field")) for field in fields if field.get("business_role") == "identifier"]
        labels = entity.get("labels") or {}
        description = str(entity.get("description") or entity.get("business_description") or "")
        instructions = "; ".join(filter(None, [
            f"GDA review status: {entity.get('review_status') or entity.get('binding_status') or 'unspecified'}",
            f"GDA semantic coverage: {entity.get('semantic_coverage_status') or 'unspecified'}",
            f"Physical binding: {', '.join(physical_tables)}" if physical_tables else None,
        ]))
        extension_data = {
            "gda_runtime_schema": payload.get("schema"),
            "gda_entity_id": entity_id,
            "gda_entity": entity,
            "physical_tables": physical_tables,
            "retrieval_eligible": entity.get("retrieval_eligible"),
            "execution_eligible": entity.get("execution_eligible"),
        }
        dataset: dict[str, Any] = {
            "name": logical_name,
            "source": source,
            "description": description,
            "fields": [_ossie_field(field) for field in fields if isinstance(field, Mapping)],
            "ai_context": _ossie_ai_context(entity, instructions=instructions),
            "custom_extensions": [_ossie_extension("GDA", extension_data)],
        }
        if primary_key:
            dataset["primary_key"] = list(dict.fromkeys(primary_key))
        datasets.append(dataset)
    return datasets, logical_by_table, logical_by_entity


def _split_physical_binding(value: Any) -> tuple[str | None, str | None]:
    raw = str(value or "")
    if "." not in raw:
        return None, None
    table, field = raw.rsplit(".", 1)
    return table, field


def _ossie_relationships(payload: Mapping[str, Any], logical_by_table: Mapping[str, str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    relationships: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    for index, relation in enumerate(list(payload.get("relationships") or []) + list(payload.get("relations") or [])):
        if not isinstance(relation, Mapping):
            continue
        left_table, left_field = _split_physical_binding(relation.get("left") or relation.get("source"))
        right_table, right_field = _split_physical_binding(relation.get("right") or relation.get("target"))
        left_dataset = logical_by_table.get(left_table or "")
        right_dataset = logical_by_table.get(right_table or "")
        if not (left_dataset and right_dataset and left_field and right_field):
            unresolved.append(dict(relation))
            continue
        relationship = {
            "name": str(relation.get("name") or relation.get("relationship_id") or relation.get("relation_id") or f"gda_relationship_{index + 1}"),
            "from": left_dataset,
            "to": right_dataset,
            "from_columns": [left_field],
            "to_columns": [right_field],
            "custom_extensions": [_ossie_extension("GDA", {
                "kind": relation.get("kind"),
                "operator": relation.get("operator"),
                "cardinality": relation.get("cardinality"),
                "review_status": relation.get("review_status"),
                "notes": relation.get("notes"),
            })],
        }
        relationships.append(relationship)
    return relationships, unresolved


def _ossie_metric_expression(metric: Mapping[str, Any]) -> str | None:
    if metric.get("canonical_sql_template"):
        return str(metric["canonical_sql_template"])
    pieces: list[str] = []
    for item in metric.get("metrics") or []:
        if not isinstance(item, Mapping):
            continue
        aggregate = str(item.get("aggregate") or "").upper()
        field = str(item.get("field") or "*")
        table = str(item.get("table") or "")
        reference = f"{table}.{field}" if table and field != "*" else (table + ".*" if table else field)
        if aggregate in {"COUNT", "SUM", "AVG", "MIN", "MAX", "COUNT_DISTINCT"}:
            if aggregate == "COUNT_DISTINCT":
                pieces.append(f"COUNT(DISTINCT {reference})")
            else:
                pieces.append(f"{aggregate}({reference})")
    if len(pieces) == 1:
        return pieces[0]
    if pieces:
        return " + ".join(pieces)
    return None


def export_semantic_layer_to_ossie_yaml(source, destination=None, *, include_runtime_extension=True):
    """Export a GDA semantic layer to Apache Ossie Core Metadata YAML.

    Ossie is currently a draft semantic-model exchange format.  The output is
    intentionally a *projection*: executable GDA gates, source fingerprints,
    answerability contracts and non-FK spatial relationships remain in the GDA
    extension payload.  A consumer must not treat an Ossie document alone as
    an activated NL2SQL semantic layer.
    """
    payload = _read_payload(source)
    if _document_kind(payload) != "semantic_layer":
        raise InteropError("export_semantic_layer_to_ossie_yaml expects the semantic-layer runtime schema")
    datasets, logical_by_table, _ = _ossie_entities(payload)
    relationships, unresolved = _ossie_relationships(payload, logical_by_table)
    metrics: list[dict[str, Any]] = []
    for metric in payload.get("metric_contracts") or []:
        if not isinstance(metric, Mapping):
            continue
        expression = _ossie_metric_expression(metric)
        if not expression:
            continue
        metrics.append({
            "name": str(metric.get("contract_id") or metric.get("name") or "metric"),
            "expression": {"dialects": [{"dialect": "ANSI_SQL", "expression": expression}]},
            "description": str(metric.get("description") or metric.get("operation") or ""),
            "datatype": "Decimal",
            "ai_context": {"synonyms": [str(metric.get("contract_id"))]} if metric.get("contract_id") else {},
            "custom_extensions": [_ossie_extension("GDA", {
                "metric_contract": metric,
                "projection_status": "derived_expression",
            })],
        })
    gda_extension = {
        "runtime_schema": payload.get("schema"),
        "semantic_version": payload.get("semantic_version"),
        "source_binding": payload.get("source_binding"),
        "activation_gate": payload.get("activation_gate"),
        "query_policy": payload.get("query_policy"),
        "relationships_unresolved_in_ossie_core": unresolved,
        "metric_contracts_not_projected": [
            metric for metric in payload.get("metric_contracts") or []
            if isinstance(metric, Mapping) and not _ossie_metric_expression(metric)
        ],
    }
    model: dict[str, Any] = {
        "name": str(payload.get("semantic_version") or payload.get("source_binding", {}).get("database_name") or "gda_semantic_model"),
        "description": f"GDA standards projection of {payload.get('semantic_version') or 'unversioned runtime semantic layer'}",
        "ai_context": {
            "instructions": "This is a standards projection. Rebind source, verify governance, and pass GDA activation gates before execution.",
        },
        "datasets": datasets,
        "relationships": relationships,
        "metrics": metrics,
        "custom_extensions": [],
    }
    document: dict[str, Any] = {"version": OSSIE_VERSION, "semantic_model": [model]}
    if include_runtime_extension:
        gda_extension["ossie_projection_sha256"] = _sha256_json(_ossie_projection_core(document))
        model["custom_extensions"] = [
            _ossie_extension("GDA", gda_extension),
            _ossie_extension("GDA", {"runtime_payload": payload}),
        ]
    return _write_text(destination, yaml.safe_dump(document, allow_unicode=True, sort_keys=False))


def _ossie_extensions(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, Any]] = []
    for extension in value:
        if not isinstance(extension, Mapping):
            continue
        vendor = str(extension.get("vendor_name") or "")
        raw = extension.get("data")
        try:
            data = json.loads(raw) if isinstance(raw, str) else raw
        except (TypeError, ValueError):
            data = raw
        result.append({"vendor_name": vendor, "data": data})
    return result


def _ossie_payload_extension(document: Mapping[str, Any]) -> dict[str, Any] | None:
    for extension in _ossie_extensions(document.get("custom_extensions")):
        data = extension.get("data")
        if extension.get("vendor_name", "").upper() == "GDA" and isinstance(data, Mapping):
            payload = data.get("runtime_payload")
            if isinstance(payload, Mapping):
                return dict(payload)
    models = document.get("semantic_model") or []
    if isinstance(models, list):
        for model in models:
            if not isinstance(model, Mapping):
                continue
            for extension in _ossie_extensions(model.get("custom_extensions")):
                data = extension.get("data")
                if extension.get("vendor_name", "").upper() == "GDA" and isinstance(data, Mapping):
                    payload = data.get("runtime_payload")
                    if isinstance(payload, Mapping):
                        return dict(payload)
    return None


def _ossie_runtime_extension(document: Mapping[str, Any]) -> dict[str, Any] | None:
    """Return the GDA extension carrying runtime integrity metadata."""
    candidates: list[Mapping[str, Any]] = [document]
    models = document.get("semantic_model")
    if isinstance(models, list):
        candidates.extend(item for item in models if isinstance(item, Mapping))
    for candidate in candidates:
        for extension in _ossie_extensions(candidate.get("custom_extensions")):
            data = extension.get("data")
            if extension.get("vendor_name", "").upper() == "GDA" and isinstance(data, Mapping):
                if (
                    "runtime_payload" in data
                    or "runtime_payload_sha256" in data
                    or "ossie_projection_sha256" in data
                ):
                    return dict(data)
    return None


def _ossie_projection_core(document: Mapping[str, Any]) -> dict[str, Any]:
    """Canonical Ossie core projection, excluding vendor extensions.

    This deliberately hashes the interoperable datasets/fields/relationships/
    metrics rather than the GDA payload extension, so editing a standard field
    cannot be silently ignored during a strict round-trip import.
    """
    models = document.get("semantic_model")
    if not isinstance(models, list):
        return {"version": document.get("version"), "semantic_model": []}

    def strip_extensions(value: Any) -> Any:
        if isinstance(value, Mapping):
            return {
                str(key): strip_extensions(item)
                for key, item in value.items()
                if key != "custom_extensions"
            }
        if isinstance(value, list):
            return [strip_extensions(item) for item in value]
        return value

    return {
        "version": document.get("version"),
        "semantic_model": [strip_extensions(model) for model in models if isinstance(model, Mapping)],
    }


def import_semantic_layer_from_ossie_yaml(source, *, mode="strict") -> dict[str, Any]:
    if mode not in {"strict", "lossless-extension", "projection-only"}:
        raise InteropError(f"unsupported import mode: {mode}")
    path: Path | None = None
    if isinstance(source, Path):
        path = source.expanduser()
    elif isinstance(source, str) and len(source) < 4096:
        try:
            candidate = Path(source).expanduser()
            if candidate.is_file():
                path = candidate
        except OSError:
            path = None
    raw = yaml.safe_load(path.read_text(encoding="utf-8") if path else str(source))
    if not isinstance(raw, Mapping):
        raise InteropError("OSSIE document must be a mapping")
    if raw.get("version") != OSSIE_VERSION:
        raise InteropError(
            f"unsupported OSSIE version: {raw.get('version')!r}; expected {OSSIE_VERSION}"
        )
    unsupported_top_level = set(raw) - {"version", "semantic_model"}
    if unsupported_top_level:
        raise InteropError(
            "OSSIE document contains unsupported top-level properties: "
            + ", ".join(sorted(str(key) for key in unsupported_top_level))
        )
    models = raw.get("semantic_model")
    if not isinstance(models, list) or not models or not all(isinstance(model, Mapping) for model in models):
        raise InteropError("OSSIE document requires a non-empty semantic_model list")
    payload = _ossie_payload_extension(raw)
    if payload is not None:
        if payload.get("schema") != SEMANTIC_SCHEMA:
            raise InteropError(f"embedded runtime schema is {payload.get('schema')!r}, expected {SEMANTIC_SCHEMA!r}")
        runtime_extension = _ossie_runtime_extension(raw) or {}
        declared_projection = runtime_extension.get("ossie_projection_sha256")
        actual_projection = _sha256_json(_ossie_projection_core(raw))
        if not declared_projection:
            if mode in {"strict", "lossless-extension"}:
                raise InteropError(
                    "strict OSSIE import requires an ossie_projection_sha256 integrity extension"
                )
        elif str(declared_projection) != actual_projection:
            raise InteropError(
                "OSSIE core projection hash mismatch; refusing a modified datasets, relationships or metrics projection"
            )
        return payload
    if mode == "strict":
        raise InteropError("strict OSSIE import requires a GDA runtime extension to preserve bindings and execution governance")
    assets: list[dict[str, Any]] = []
    relationships: list[dict[str, Any]] = []
    metric_contracts: list[dict[str, Any]] = []
    used_asset_ids: set[str] = set()
    for model_index, model in enumerate(models):
        datasets = model.get("datasets") or []
        if not isinstance(datasets, list) or not datasets:
            raise InteropError(f"OSSIE semantic_model[{model_index}] requires datasets")
        model_dataset_ids: dict[str, str] = {}
        for dataset in datasets:
            if not isinstance(dataset, Mapping):
                continue
            extensions = _ossie_extensions(dataset.get("custom_extensions"))
            entity_ext = next((e.get("data") for e in extensions if e.get("vendor_name", "").upper() == "GDA" and isinstance(e.get("data"), Mapping)), {})
            entity_id = entity_ext.get("gda_entity_id") if isinstance(entity_ext, Mapping) else None
            base_id = str(entity_id or dataset.get("name") or dataset.get("source") or "dataset")
            asset_id = base_id
            suffix = 2
            while asset_id in used_asset_ids:
                asset_id = f"{base_id}__{suffix}"
                suffix += 1
            used_asset_ids.add(asset_id)
            source_table = str(dataset.get("source") or "")
            declared_name = str(dataset.get("name") or source_table or base_id)
            model_dataset_ids[declared_name] = asset_id
            if source_table:
                model_dataset_ids[source_table] = asset_id
            fields: list[dict[str, Any]] = []
            for field in dataset.get("fields") or []:
                if not isinstance(field, Mapping):
                    continue
                exprs = ((field.get("expression") or {}).get("dialects") or [])
                physical = str(exprs[0].get("expression") if exprs and isinstance(exprs[0], Mapping) else field.get("name") or "")
                field_exts = _ossie_extensions(field.get("custom_extensions"))
                field_ext = next((e.get("data") for e in field_exts if e.get("vendor_name", "").upper() == "GDA" and isinstance(e.get("data"), Mapping)), {})
                labels = {"en": str(field.get("label") or field.get("name") or "")}
                fields.append({
                    "semantic_field": str(field.get("name") or physical),
                    "physical_field": str(field_ext.get("physical_field") or physical) if isinstance(field_ext, Mapping) else physical,
                    "labels": labels,
                    "business_role": "temporal_dimension" if ((field.get("dimension") or {}).get("is_time") is True) else "attribute",
                    "description": str(field.get("description") or ""),
                    "technical_metadata": {"data_type": field.get("datatype")} if field.get("datatype") else {},
                    "value_domain": field_ext.get("value_domain") if isinstance(field_ext, Mapping) else None,
                })
            assets.append({
                "asset_id": asset_id,
                "labels": {"en": str(dataset.get("name") or source_table)},
                "aliases": list((dataset.get("ai_context") or {}).get("synonyms") or []) if isinstance(dataset.get("ai_context"), Mapping) else [],
                "description": str(dataset.get("description") or ""),
                "physical_tables": [source_table] if source_table else [],
                "fields": fields,
                "review_status": "imported_projection",
                "binding_status": "imported_projection",
                "retrieval_eligible": False,
                "execution_eligible": False,
            })
        for relation in model.get("relationships") or []:
            if not isinstance(relation, Mapping):
                continue
            from_columns = relation.get("from_columns") or []
            to_columns = relation.get("to_columns") or []
            relation_from = model_dataset_ids.get(
                str(relation.get("from") or ""), str(relation.get("from") or "")
            )
            relation_to = model_dataset_ids.get(
                str(relation.get("to") or ""), str(relation.get("to") or "")
            )
            relationships.append({
                "relationship_id": str(relation.get("name") or f"ossie_relationship_{model_index + 1}_{len(relationships) + 1}"),
                "source": f"{relation_from}.{from_columns[0]}" if from_columns else relation_from,
                "target": f"{relation_to}.{to_columns[0]}" if to_columns else relation_to,
                "kind": "foreign_key",
                "review_status": "imported_projection",
            })
        for metric in model.get("metrics") or []:
            if not isinstance(metric, Mapping):
                continue
            expressions = ((metric.get("expression") or {}).get("dialects") or [])
            expression = expressions[0].get("expression") if expressions and isinstance(expressions[0], Mapping) else None
            metric_contracts.append({
                "contract_id": str(metric.get("name") or f"ossie_metric_{model_index + 1}_{len(metric_contracts) + 1}"),
                "description": str(metric.get("description") or ""),
                "canonical_sql_template": str(expression) if expression else None,
                "review_status": "imported_projection",
            })
    return {
        "schema": SEMANTIC_SCHEMA,
        "semantic_version": "imported-ossie-projection",
        "status": "projection_only_import_requires_review",
        "source_binding": {},
        "semantic_assets": assets,
        "table_bindings": [],
        "relationships": relationships,
        "metric_contracts": metric_contracts,
        "runtime_role": {"execution_authority": False},
        "provenance": {
            "source_format": "apache-ossie-core-metadata",
            "import_mode": mode,
            "semantic_model_count": len(models),
        },
    }


def _find_original_payload(graph) -> dict[str, Any] | None:
    from rdflib import Namespace

    gda = Namespace(GDA_NS)
    for _, _, literal in graph.triples((None, gda["originalJson"], None)):
        try:
            value = json.loads(str(literal))
        except (TypeError, ValueError):
            continue
        if isinstance(value, dict):
            return value
    return None


def _runtime_import_from_graph(graph, *, expected_schema: str, mode: str) -> dict[str, Any]:
    if mode not in {"strict", "lossless-extension", "projection-only"}:
        raise InteropError(f"unsupported import mode: {mode}")
    payload = _find_original_payload(graph)
    if payload is not None:
        if payload.get("schema") != expected_schema:
            raise InteropError(
                f"embedded runtime schema is {payload.get('schema')!r}, expected {expected_schema!r}"
            )
        from rdflib import Namespace

        gda = Namespace(GDA_NS)
        declared = next((str(value) for _, _, value in graph.triples((None, gda["payloadSha256"], None))), None)
        actual = _sha256_json(payload)
        if declared and declared != actual:
            raise InteropError(
                "GDA extension payload hash mismatch; refusing a corrupted or partially edited import"
            )
        return payload
    if mode == "strict":
        raise InteropError(
            "strict import requires a GDA extension payload so source bindings, versions and "
            "execution metadata cannot be silently lost"
        )
    # Projection-only reconstruction from ordinary OWL/RDF.  It is explicitly
    # inactive for execution and must be reviewed before entering the runtime.
    from rdflib import Namespace, RDF, RDFS

    owl = Namespace("http://www.w3.org/2002/07/owl#")
    skos = Namespace("http://www.w3.org/2004/02/skos/core#")
    gda = Namespace(GDA_NS)
    concepts: list[dict[str, Any]] = []

    def labels_for(subject: Any) -> dict[str, str]:
        labels: dict[str, str] = {}
        for label in graph.objects(subject, skos.prefLabel):
            labels[str(label.language or "und")] = str(label)
        return labels

    def fields_for(subject: Any) -> list[dict[str, Any]]:
        fields: list[dict[str, Any]] = []
        field_subjects = list(graph.objects(subject, gda["hasField"]))
        for field_subject in field_subjects:
            field_labels = labels_for(field_subject)
            physical = next((str(value) for value in graph.objects(field_subject, gda["physicalBinding"])), None)
            semantic_field = next((str(value) for value in graph.objects(field_subject, gda["semanticField"])), None)
            semantic_field = semantic_field or next(iter(field_labels.values()), None) or str(field_subject).rsplit("/", 1)[-1]
            field: dict[str, Any] = {
                "semantic_field": semantic_field,
                "physical_field": physical or semantic_field,
                "labels": field_labels,
                "aliases": [str(value) for value in graph.objects(field_subject, skos.altLabel)],
                "business_role": next((str(value) for value in graph.objects(field_subject, gda["businessRole"])), "attribute"),
                "definition_status": next((str(value) for value in graph.objects(field_subject, gda["definitionStatus"])), None),
                "description": next((str(value) for value in graph.objects(field_subject, RDFS.comment)), ""),
                "technical_metadata": {},
                "value_domain": [str(value) for value in graph.objects(field_subject, gda["valueDomain"])],
            }
            data_type = next((str(value) for value in graph.objects(field_subject, gda["dataType"])), None)
            nullable = next((value for value in graph.objects(field_subject, gda["nullable"])), None)
            if data_type:
                field["technical_metadata"]["data_type"] = data_type
            if nullable is not None:
                field["technical_metadata"]["nullable"] = str(nullable).lower() == "true"
            fields.append(field)
        return fields

    for subject in graph.subjects(RDF.type, owl.Class):
        labels = labels_for(subject)
        aliases = [str(value) for value in graph.objects(subject, skos.altLabel)]
        binding = next((str(value) for value in graph.objects(subject, gda["physicalBinding"])), None)
        concepts.append({
            "concept_id": str(subject).rsplit("/concept/", 1)[-1],
            "labels": labels,
            "aliases": aliases,
            "description": next((str(value) for value in graph.objects(subject, RDFS.comment)), ""),
            "physical_binding": binding,
            "fields": fields_for(subject),
            "binding_status": "imported_projection",
            "semantic_coverage_status": "projection_only",
            "retrieval_eligible": False,
            "execution_eligible": False,
        })
    relationships: list[dict[str, Any]] = []
    for subject in graph.subjects(RDF.type, owl.ObjectProperty):
        source = next((str(value) for value in graph.objects(subject, gda["relationshipSource"])), None)
        target = next((str(value) for value in graph.objects(subject, gda["relationshipTarget"])), None)
        binding = next((str(value) for value in graph.objects(subject, gda["relationshipBinding"])), None)
        if not (source or target or binding):
            continue
        relationships.append({
            "relationship_id": next((str(value) for value in graph.objects(subject, gda["relationshipId"])), str(subject).rsplit("/", 1)[-1]),
            "source": source or binding or "",
            "target": target or "",
            "kind": next((str(value) for value in graph.objects(subject, gda["kind"])), "relationship"),
            "review_status": next((str(value) for value in graph.objects(subject, gda["reviewStatus"])), "imported_projection"),
        })
    metric_contracts: list[dict[str, Any]] = []
    for subject in graph.subjects(RDF.type, gda["MetricContract"]):
        metric_contracts.append({
            "contract_id": next((str(value) for value in graph.objects(subject, gda["contractId"])), str(subject).rsplit("/", 1)[-1]),
            "operation": next((str(value) for value in graph.objects(subject, gda["operation"])), None),
            "canonical_sql_template": next((str(value) for value in graph.objects(subject, gda["canonical_sql_template"])), None),
            "review_status": next((str(value) for value in graph.objects(subject, gda["reviewStatus"])), "imported_projection"),
        })
    reconstructed = {
        "schema": expected_schema,
        "status": "projection_only_import_requires_review",
        "runtime_role": {"execution_authority": False},
        "concepts": concepts,
        "relationships": relationships,
        "metric_contracts": metric_contracts,
        "provenance": {"import_mode": mode, "source_format": "rdf"},
    }
    if expected_schema == SEMANTIC_SCHEMA:
        reconstructed["semantic_version"] = "imported-projection"
        reconstructed["source_binding"] = {}
        reconstructed["semantic_assets"] = concepts
        reconstructed["table_bindings"] = []
        reconstructed["metric_contracts"] = metric_contracts
    return reconstructed


def _parse_graph(source, fmt: str):
    _, Graph, _, _, _, _, _, _ = _rdflib()
    graph = Graph()
    if isinstance(source, Path):
        graph.parse(str(source.expanduser()), format=fmt)
    elif isinstance(source, str):
        # A serialized document can be much longer than a filesystem path;
        # test it as a path only when it is plausibly a path and tolerate the
        # platform's ENAMETOOLONG response.
        try:
            candidate = Path(source).expanduser()
            if len(source) < 4096 and candidate.is_file():
                graph.parse(str(candidate), format=fmt)
            else:
                graph.parse(data=source, format=fmt)
        except (OSError, ValueError):
            graph.parse(data=source, format=fmt)
    else:
        graph.parse(data=str(source), format=fmt)
    return graph


def import_ontology_from_turtle(source, *, mode="strict"):
    return _runtime_import_from_graph(_parse_graph(source, "turtle"), expected_schema=ONTOLOGY_SCHEMA, mode=mode)


def import_semantic_layer_from_turtle(source, *, mode="strict"):
    return _runtime_import_from_graph(_parse_graph(source, "turtle"), expected_schema=SEMANTIC_SCHEMA, mode=mode)


def import_ontology_from_jsonld(source, *, mode="strict"):
    return _runtime_import_from_graph(_parse_graph(source, "json-ld"), expected_schema=ONTOLOGY_SCHEMA, mode=mode)


def import_semantic_layer_from_jsonld(source, *, mode="strict"):
    return _runtime_import_from_graph(_parse_graph(source, "json-ld"), expected_schema=SEMANTIC_SCHEMA, mode=mode)


def validate_roundtrip(source, *, kind: str | None = None, formats=("turtle", "json-ld")) -> dict[str, Any]:
    """Export and re-import a runtime asset, reporting exact hash preservation."""
    payload = _read_payload(source)
    detected = _document_kind(payload)
    if kind and kind != detected:
        raise InteropError(f"kind={kind!r} does not match {detected!r}")
    expected_schema = ONTOLOGY_SCHEMA if detected == "ontology" else SEMANTIC_SCHEMA
    result: dict[str, Any] = {
        "interop_format": INTEROP_FORMAT,
        "source_schema": expected_schema,
        "source_sha256": _sha256_json(payload),
        "formats": {},
        "lossless": True,
    }
    for fmt in formats:
        content = _serialize_jsonld(payload) if fmt == "json-ld" else _serialize(payload, fmt)
        imported = _runtime_import_from_graph(_parse_graph(content, fmt), expected_schema=expected_schema, mode="strict")
        digest = _sha256_json(imported)
        result["formats"][fmt] = {
            "bytes": len(content.encode("utf-8")),
            "imported_sha256": digest,
            "lossless": digest == result["source_sha256"],
        }
        result["lossless"] = result["lossless"] and digest == result["source_sha256"]
    return result


__all__ = [
    "InteropError",
    "export_ontology_to_turtle",
    "export_ontology_to_jsonld",
    "export_semantic_layer_to_turtle",
    "export_semantic_layer_to_jsonld",
    "export_semantic_layer_to_ossie_yaml",
    "export_semantic_layer_to_yaml",
    "import_ontology_from_turtle",
    "import_ontology_from_jsonld",
    "import_semantic_layer_from_turtle",
    "import_semantic_layer_from_jsonld",
    "import_semantic_layer_from_ossie_yaml",
    "validate_roundtrip",
]
