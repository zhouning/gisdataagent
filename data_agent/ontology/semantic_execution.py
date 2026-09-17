"""Formal ontology gates for natural-language data execution.

The semantic layer is a binding from a published ontology to a physical
representation.  A database table is evidence for a representation; it is
never promoted to an ontology class simply because it is queryable.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from ..platform_contracts import canonical_json_fingerprint

PHYSICAL_LAKE_SEMANTIC_SCHEMA = "gda.ontology-semantic-execution-contract.v1"
PHYSICAL_LAKE_SEMANTIC_REVISION = "v1"
PHYSICAL_LAKE_ONTOLOGY_IRI = (
    "https://ontology.gis-data-agent.local/abu-dhabi/lake-semantic-core/1.0.0"
)
PHYSICAL_LAKE_NAMESPACE = "https://ontology.gis-data-agent.local/abu-dhabi/lake-semantic/"
VIRTUAL_SEMANTIC_NAMESPACE = "https://ontology.gis-data-agent.local/abu-dhabi/virtual-semantic/"

_PASCAL_NAME_RE = re.compile(r"^[A-Z][A-Za-z0-9]*$")
_CAMEL_NAME_RE = re.compile(r"^[a-z][A-Za-z0-9]*$")
_XSD_NAMESPACE = "http://www.w3.org/2001/XMLSchema#"
_RDF_JSON = "http://www.w3.org/1999/02/22-rdf-syntax-ns#JSON"


def _name_parts(value: str) -> list[str]:
    """Turn a stable semantic identifier into non-empty ASCII name parts."""

    return [part for part in re.split(r"[^A-Za-z0-9]+", value) if part]


def _pascal_name(value: str) -> str:
    parts = _name_parts(value)
    if not parts:
        return "Unnamed"
    name = "".join(part[:1].upper() + part[1:] for part in parts)
    return "Class" + name if name[:1].isdigit() else name


def _camel_name(value: str) -> str:
    pascal = _pascal_name(value)
    return pascal[:1].lower() + pascal[1:]


def _labels(value: str) -> dict[str, str]:
    """Keep the display label separate from its formal class/property name."""

    return {"zh": value}


def _xsd_range(source_type: Any) -> str | None:
    """Map attested source types to a formal literal range.

    A source representation may use a different physical type from another
    representation of the same business property.  The mapping is therefore
    attached to the representation field, while the business property keeps
    ``rdfs:Literal`` until a governed Silver conversion contract is approved.
    """

    value = re.sub(r"\s+", " ", str(source_type or "").strip().upper())
    if not value:
        return None
    if value in {"BOOLEAN", "BOOL"}:
        return _XSD_NAMESPACE + "boolean"
    if value in {"SMALLINT", "SMALLSERIAL", "INT2", "INTEGER", "SERIAL", "INT", "INT4", "BIGINT", "BIGSERIAL", "INT8"}:
        return _XSD_NAMESPACE + "integer"
    if value in {"REAL", "FLOAT4", "DOUBLE PRECISION", "FLOAT8"} or value.startswith("FLOAT"):
        return _XSD_NAMESPACE + "double"
    if value.startswith(("NUMERIC", "DECIMAL")):
        return _XSD_NAMESPACE + "decimal"
    if value == "DATE":
        return _XSD_NAMESPACE + "date"
    if value.startswith("TIMESTAMP"):
        return _XSD_NAMESPACE + "dateTime"
    if value.startswith("TIME"):
        return _XSD_NAMESPACE + "time"
    if value.startswith("GEOMETRY"):
        return PHYSICAL_LAKE_NAMESPACE + "datatype/encoded-geometry"
    if value in {"BYTEA", "BINARY", "VARBINARY"}:
        return _XSD_NAMESPACE + "base64Binary"
    if value in {"JSON", "JSONB"} or value.endswith("[]"):
        return _RDF_JSON
    # UUID is deliberately represented as text. It is a source identity, not
    # an ontology individual IRI unless an identity-resolution contract says so.
    return _XSD_NAMESPACE + "string"


class SemanticExecutionContractError(ValueError):
    """A semantic execution contract is missing or violates formal rules."""


# These labels identify a source representation only.  They are deliberately
# separate from ontology classes, which are supplied by the governed model.
_REPRESENTATION_VOCABULARY: dict[tuple[int, str], tuple[str, tuple[str, ...]]] = {
    (12, "public.dim_calc_versions"): ("宜居性计算版本", ("calculation version", "计算版本")),
    (12, "public.dim_districts"): ("宜居性行政区", ("district", "行政区")),
    (12, "public.dim_facilities"): ("宜居性设施清单", ("facility", "设施")),
    (12, "public.dim_facility_types"): ("宜居性设施类型", ("facility type", "设施类型")),
    (12, "public.dim_projects"): ("宜居性项目", ("liveability project", "宜居项目")),
    (12, "public.dim_stages"): ("宜居性评估阶段", ("assessment stage", "评估阶段")),
    (12, "public.dim_udm_plots"): ("宜居性城市模型地块", ("urban model plot", "城市模型地块")),
    (12, "public.fact_district_scores"): ("行政区宜居性评分", ("district score", "行政区评分")),
    (12, "public.fact_facility_provision"): ("行政区设施供给测度", ("facility provision", "设施供给")),
    (12, "public.fact_parks_demand"): ("公园需求测度", ("park demand", "公园需求")),
    (12, "public.fact_population"): ("宜居性行政区人口观测", ("population observation", "人口")),
    (12, "public.fact_qualitative_2025"): ("2025 定性巡查", ("qualitative inspection", "定性巡查")),
    (12, "public.fact_residential_plots"): ("居住地块观测", ("residential plot observation", "居住地块")),
    (12, "public.fact_school_fc"): ("学校容量测度", ("school capacity", "学校容量")),
    (13, "public.bus_line"): ("公交线路", ("bus line", "公交线路")),
    (13, "public.bus_route"): ("公交路线", ("bus route", "公交路线")),
    (13, "public.bus_stop"): ("公交站点", ("bus stop", "公交站")),
    (13, "public.busdepots"): ("公交车场", ("bus depot", "公交车场")),
    (13, "public.busshelter"): ("公交候车亭", ("bus shelter", "公交候车亭", "候车亭")),
    (13, "public.busstation"): ("公交枢纽", ("bus station", "公交枢纽", "公交总站")),
    (13, "public.lrt_brt_facility"): ("轻轨与快速公交设施", ("lrt brt facility", "轻轨快速公交设施")),
    (13, "public.masterplan_ud_plot"): ("总体规划地块", ("masterplan plot", "总体规划地块", "规划地块")),
    (13, "public.metro_facilities"): ("地铁设施", ("metro facility", "地铁设施")),
    (13, "public.parks_details"): ("公园清单", ("park", "parks", "公园")),
    (13, "public.poi_adek_schools_locations"): ("学校位置", ("school", "schools", "学校")),
    (13, "public.poi_doh_facilities"): ("卫生设施", ("health facility", "医疗设施", "卫生设施")),
    (13, "public.scad_districts_populationestimate_2024"): ("2024 行政区人口估算", ("district population estimate", "行政区人口估算")),
    (13, "public.ud_masterplan_boundary"): ("总体规划边界", ("masterplan boundary", "总体规划边界")),
    (13, "public.udm_building"): ("城市模型建筑物", ("building", "buildings", "建筑物")),
    (13, "public.udm_district"): ("城市模型行政区", ("udm district", "城市模型行政区")),
    (13, "public.udm_park"): ("城市模型公园", ("udm park", "城市模型公园")),
    (13, "public.udm_plot"): ("城市模型地块", ("udm plot", "城市模型地块", "地块")),
    (13, "public.udm_roadcentreline"): ("道路中心线", ("road centreline", "道路中心线")),
}


def _iri(kind: str, value: str) -> str:
    normalized = value.replace(".", "/").replace("_", "-")
    return f"{PHYSICAL_LAKE_NAMESPACE}{kind}/{normalized}"


def _virtual_iri(kind: str, value: str) -> str:
    normalized = value.replace(".", "/").replace("_", "-")
    return f"{VIRTUAL_SEMANTIC_NAMESPACE}{kind}/{normalized}"


def _parent_for_entity(entity_id: str, entity_kind: str) -> str:
    if entity_kind == "fact" or entity_id.startswith(("liveability.", "population.")):
        return "MeasurementObservation"
    if entity_id.startswith("reference."):
        return "ReferenceEntity"
    return "SpatialBusinessEntity"


def _formal_classes(entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    classes = [
        {
            "iri": PHYSICAL_LAKE_NAMESPACE + "SourceRepresentation",
            "name": "SourceRepresentation",
            "label": "来源表示",
            "labels": _labels("来源表示"),
            "definition": "受控来源中用于承载业务概念的物理表或视图表示；它不是业务本体类。",
            "abstract": True,
        },
        {
            "iri": _iri("class", "BusinessEntity"),
            "name": "BusinessEntity",
            "label": "业务实体",
            "labels": _labels("业务实体"),
            "definition": "在领域中具有稳定业务含义、可由一个或多个来源表示的对象或事实。",
            "abstract": True,
        },
        {
            "iri": _iri("class", "ReferenceEntity"),
            "name": "ReferenceEntity",
            "label": "参考实体",
            "labels": _labels("参考实体"),
            "definition": "定义、分类或版本等用于解释其他业务实体的参考对象。",
            "parent_iri": _iri("class", "BusinessEntity"),
            "abstract": True,
        },
        {
            "iri": _iri("class", "SpatialBusinessEntity"),
            "name": "SpatialBusinessEntity",
            "label": "空间业务实体",
            "labels": _labels("空间业务实体"),
            "definition": "在指定来源版本中可具有空间表示的现实业务对象。",
            "parent_iri": _iri("class", "BusinessEntity"),
            "abstract": True,
        },
        {
            "iri": _iri("class", "MeasurementObservation"),
            "name": "MeasurementObservation",
            "label": "测度与观测",
            "labels": _labels("测度与观测"),
            "definition": "在明确对象、时间、版本或方法下形成的事实、评分、估算或观测。",
            "parent_iri": _iri("class", "BusinessEntity"),
            "abstract": True,
        },
    ]
    for entity in entities:
        entity_id = str(entity["entity_id"])
        parent = _parent_for_entity(entity_id, str(entity.get("entity_kind") or ""))
        classes.append(
            {
                "iri": _iri("class", entity_id),
                "name": _pascal_name(entity_id),
                "label": str(entity["label"]),
                "labels": _labels(str(entity["label"])),
                "definition": f"{entity['grain']} {entity['key_policy']}",
                "parent_iri": _iri("class", parent),
                "abstract": False,
            }
        )
    return classes


def build_physical_lake_semantic_execution_contract(
    ods_contract: Mapping[str, Any],
) -> dict[str, Any]:
    """Compile a query semantic layer from curated business entities.

    The input ODS contract contributes only source representations and field
    bindings.  The ontology classes, definitions, relationships and semantic
    property names come from ``abu_dhabi_governed_model``.
    """

    from ..abu_dhabi_governed_model import build_governed_lake_model_contract

    governed = build_governed_lake_model_contract(dict(ods_contract))
    entities = list(governed.get("entities") or [])
    entity_by_id = {str(entity["entity_id"]): entity for entity in entities}
    ods_targets = {
        (int(table.get("source_id") or 0), str(table.get("source_table") or "")): str(
            table.get("ods_table") or ""
        )
        for table in ods_contract.get("tables") or []
        if isinstance(table, Mapping)
    }
    strict_source_type_evidence = bool(ods_contract.get("require_source_type_evidence"))
    source_types_by_binding: dict[tuple[int, str], dict[str, str]] = {}
    for table in ods_contract.get("tables") or []:
        if not isinstance(table, Mapping):
            continue
        key = (int(table.get("source_id") or 0), str(table.get("source_table") or ""))
        if key[0] <= 0 or not key[1]:
            continue
        fields = table.get("source_schema_evidence") or []
        if strict_source_type_evidence and not fields:
            raise SemanticExecutionContractError(
                f"semantic_execution_source_type_evidence_missing:{key[0]}:{key[1]}"
            )
        values: dict[str, str] = {}
        for field in fields:
            if not isinstance(field, Mapping):
                raise SemanticExecutionContractError("semantic_execution_source_type_evidence_invalid")
            name = str(field.get("name") or "").strip()
            source_type = str(field.get("source_type") or "").strip()
            if not name or not source_type or name in values:
                raise SemanticExecutionContractError("semantic_execution_source_type_evidence_invalid")
            values[name] = source_type
        source_types_by_binding[key] = values
    classes = _formal_classes(entities)
    properties: list[dict[str, Any]] = []
    property_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    representations: list[dict[str, Any]] = []

    for entity in entities:
        entity_id = str(entity["entity_id"])
        class_iri = _iri("class", entity_id)
        for mapping in entity.get("source_mappings") or []:
            source_id = int(mapping["source_id"])
            source_table = str(mapping["source_table"])
            ods_table = ods_targets.get((source_id, source_table))
            if not ods_table:
                continue
            vocabulary = _REPRESENTATION_VOCABULARY.get((source_id, source_table))
            if vocabulary is None:
                raise SemanticExecutionContractError(
                    f"semantic_execution_representation_vocabulary_missing:{source_id}:{source_table}"
                )
            label, aliases = vocabulary
            fields: list[dict[str, Any]] = []
            for semantic_property, physical_field in sorted(
                (mapping.get("field_mappings") or {}).items()
            ):
                source_type = source_types_by_binding.get((source_id, source_table), {}).get(
                    str(physical_field)
                )
                source_range = _xsd_range(source_type)
                if strict_source_type_evidence and source_range is None:
                    raise SemanticExecutionContractError(
                        "semantic_execution_source_property_type_missing:"
                        f"{source_id}:{source_table}.{physical_field}"
                    )
                property_key = (entity_id, str(semantic_property))
                property_record = property_by_key.get(property_key)
                if property_record is None:
                    property_record = {
                        "iri": _iri("property", f"{entity_id}.{semantic_property}"),
                        "name": _camel_name(f"{entity_id}.{semantic_property}"),
                        "label": str(semantic_property).replace("_", " "),
                        "labels": _labels(str(semantic_property).replace("_", " ")),
                        "definition": (
                            f"{entity['label']} 的 {semantic_property} 业务属性；"
                            "其物理表示由受控来源绑定给出。"
                        ),
                        "property_type": "data_property",
                        "owl_type": "owl:DatatypeProperty",
                        "domain_iri": class_iri,
                        "range": "rdfs:Literal",
                        "min_count": 0,
                        "max_count": 1,
                        "functional": True,
                        "source_ranges": set(),
                    }
                    property_by_key[property_key] = property_record
                    properties.append(property_record)
                if source_range:
                    property_record["source_ranges"].add(source_range)
                field = {
                    "property_iri": property_record["iri"],
                    "physical_field": str(physical_field),
                    "semantic_role": str(semantic_property),
                }
                if source_type:
                    field["source_type"] = source_type
                    field["source_range"] = source_range
                fields.append(field)
            representations.append(
                {
                    "representation_id": f"source:{source_id}:{source_table}",
                    "concept_iri": class_iri,
                    "label": label,
                    "aliases": list(dict.fromkeys((label, *aliases))),
                    "definition": (
                        f"{label} 是 {entity['label']} 在来源 {source_id} 中的受限物理表示；"
                        "它不是本体类，也不等同于其他来源中的同名或相近记录。"
                    ),
                    "source_binding": {
                        "source_id": source_id,
                        "source_table": source_table,
                        "ods_table": ods_table,
                        "source_role": str(mapping.get("source_role") or "source_scoped_representation"),
                    },
                    "fields": fields,
                    "execution_scope": "source_scoped_ods_read_only",
                    "data_governance_status": "ods_not_promoted_to_silver_or_gold",
                }
            )

    relationships = []
    for relation in governed.get("relationships") or []:
        source = entity_by_id.get(str(relation["from_entity"]))
        target = entity_by_id.get(str(relation["to_entity"]))
        if source is None or target is None:
            raise SemanticExecutionContractError("semantic_execution_relationship_entity_missing")
        relationships.append(
            {
                "iri": _iri("relation", str(relation["relationship_id"])),
                "name": _camel_name(str(relation["relationship_id"])),
                "label": str(relation["relationship"]),
                "labels": _labels(str(relation["relationship"])),
                "definition": str(relation["evidence_requirement"]),
                "property_type": "object_property",
                "owl_type": "owl:ObjectProperty",
                "domain_iri": _iri("class", str(source["entity_id"])),
                "range_iri": _iri("class", str(target["entity_id"])),
                "direction": "directed",
                "execution": str(relation["execution"]),
                "review_status": str(relation["status"]),
            }
        )

    for property_record in properties:
        ranges = sorted(property_record.pop("source_ranges"))
        property_record["source_ranges"] = ranges
        if len(ranges) == 1:
            property_record["range"] = ranges[0]
            property_record["range_resolution"] = "consistent_across_active_source_representations"
        else:
            property_record["range_resolution"] = (
                "source_representation_dependent_until_governed_type_conversion"
            )
    children_by_parent: dict[str, list[str]] = {}
    properties_by_domain: dict[str, list[str]] = {}
    for item in classes:
        parent_iri = str(item.get("parent_iri") or "")
        if parent_iri:
            children_by_parent.setdefault(parent_iri, []).append(str(item["iri"]))
    for item in properties:
        properties_by_domain.setdefault(str(item["domain_iri"]), []).append(str(item["iri"]))
    for item in classes:
        item["subclass_iris"] = sorted(children_by_parent.get(str(item["iri"]), []))
        item["property_iris"] = sorted(properties_by_domain.get(str(item["iri"]), []))

    data_property_constraints = [
        {
            "property_iri": str(item["iri"]),
            "domain_iri": str(item["domain_iri"]),
            "range": str(item["range"]),
            "min_count": int(item["min_count"]),
            "max_count": int(item["max_count"]),
            "functional": bool(item["functional"]),
        }
        for item in properties
    ]
    object_property_constraints = [
        {
            "property_iri": str(item["iri"]),
            "domain_iri": str(item["domain_iri"]),
            "range_iri": str(item["range_iri"]),
            "directed": True,
            "execution_authorized": item.get("execution") == "executable_reviewed",
        }
        for item in relationships
    ]

    payload: dict[str, Any] = {
        "schema": PHYSICAL_LAKE_SEMANTIC_SCHEMA,
        "semantic_revision": PHYSICAL_LAKE_SEMANTIC_REVISION,
        "ontology": {
            "ontology_iri": PHYSICAL_LAKE_ONTOLOGY_IRI,
            "namespace": PHYSICAL_LAKE_NAMESPACE,
            "profile": "owl2-rl-source-scoped-execution",
            "ontology_language": "OWL 2 RL",
            "constraint_language": "SHACL",
            "metadata_profile": "GB/T 48000.3-2026 Annex A",
            "modeling_boundary": "business_classes_and_properties_only; physical tables_are_source_representations",
        },
        "source_model": {
            "ods_model_contract_id": str(ods_contract.get("model_contract_id") or ""),
            "ods_model_contract_sha256": str(ods_contract.get("model_contract_sha256") or ""),
            "governed_model_contract_id": str(governed.get("model_contract_id") or ""),
            "governed_model_contract_sha256": str(governed.get("model_contract_sha256") or ""),
        },
        "classes": classes,
        "data_properties": properties,
        "object_properties": relationships,
        "axioms": {
            "disjoint_class_sets": [
                [
                    _iri("class", "ReferenceEntity"),
                    _iri("class", "SpatialBusinessEntity"),
                    _iri("class", "MeasurementObservation"),
                ]
            ],
            "data_property_constraints": data_property_constraints,
            "object_property_constraints": object_property_constraints,
            "source_representation_identity": {
                "class_iri": PHYSICAL_LAKE_NAMESPACE + "SourceRepresentation",
                "key_fields": ["source_id", "source_table"],
                "source_scoped": True,
                "cross_source_identity_resolution": "requires_approved_authority_contract",
            },
        },
        "source_representations": sorted(
            representations,
            key=lambda item: (int(item["source_binding"]["source_id"]), item["source_binding"]["source_table"]),
        ),
        "execution_policy": {
            "physical_table_is_ontology_class": False,
            "unmapped_physical_field": "not_queryable",
            "cross_representation_join": "prohibited_without_executable_reviewed_object_property",
            "data_governance_independence": "ontology_binding_required_even_for_ods_not_promoted_to_silver_or_gold",
        },
    }
    payload["semantic_contract_sha256"] = canonical_json_fingerprint(payload)
    payload["semantic_contract_id"] = str(
        uuid5(
            NAMESPACE_URL,
            "gda://abu-dhabi/ontology-semantic-execution/"
            f"{payload['semantic_contract_sha256']}",
        )
    )
    return validate_physical_lake_semantic_execution_contract(payload)


def validate_physical_lake_semantic_execution_contract(
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate the formal ontology and physical-binding separation."""

    value = dict(contract)
    if value.get("schema") != PHYSICAL_LAKE_SEMANTIC_SCHEMA:
        raise SemanticExecutionContractError("semantic_execution_schema_invalid")
    payload = {
        key: item
        for key, item in value.items()
        if key not in {"semantic_contract_sha256", "semantic_contract_id"}
    }
    fingerprint = str(value.get("semantic_contract_sha256") or "")
    if fingerprint != canonical_json_fingerprint(payload):
        raise SemanticExecutionContractError("semantic_execution_fingerprint_invalid")
    expected_id = str(
        uuid5(NAMESPACE_URL, f"gda://abu-dhabi/ontology-semantic-execution/{fingerprint}")
    )
    if str(value.get("semantic_contract_id") or "") != expected_id:
        raise SemanticExecutionContractError("semantic_execution_id_invalid")

    classes = value.get("classes") or []
    class_by_iri = {
        str(item.get("iri") or ""): item for item in classes if isinstance(item, Mapping)
    }
    if len(class_by_iri) != len(classes) or not class_by_iri:
        raise SemanticExecutionContractError("semantic_execution_class_identity_invalid")
    for iri, item in class_by_iri.items():
        labels = item.get("labels") or {}
        if (
            not iri.startswith(PHYSICAL_LAKE_NAMESPACE)
            or not _PASCAL_NAME_RE.fullmatch(str(item.get("name") or ""))
            or not isinstance(labels, Mapping)
            or not str(labels.get("zh") or "").strip()
            or not str(item.get("definition") or "").strip()
            or not isinstance(item.get("property_iris"), list)
            or not isinstance(item.get("subclass_iris"), list)
        ):
            raise SemanticExecutionContractError("semantic_execution_class_definition_invalid")
        if "source_table" in item or "physical_table" in item:
            raise SemanticExecutionContractError("semantic_execution_table_promoted_to_class")
        parent = item.get("parent_iri")
        if parent and str(parent) not in class_by_iri:
            raise SemanticExecutionContractError("semantic_execution_class_parent_missing")
    for iri, class_item in class_by_iri.items():
        seen: set[str] = set()
        cursor = iri
        while class_by_iri[cursor].get("parent_iri"):
            if cursor in seen:
                raise SemanticExecutionContractError("semantic_execution_class_hierarchy_cycle")
            seen.add(cursor)
            cursor = str(class_by_iri[cursor]["parent_iri"])
        for child in class_item.get("subclass_iris") or []:
            child_record = class_by_iri.get(str(child))
            if child_record is None or child_record.get("parent_iri") != iri:
                raise SemanticExecutionContractError("semantic_execution_class_hierarchy_invalid")

    properties = value.get("data_properties") or []
    property_by_iri = {
        str(item.get("iri") or ""): item for item in properties if isinstance(item, Mapping)
    }
    if len(property_by_iri) != len(properties) or not property_by_iri:
        raise SemanticExecutionContractError("semantic_execution_property_identity_invalid")
    for item in property_by_iri.values():
        labels = item.get("labels") or {}
        if (
            item.get("property_type") != "data_property"
            or item.get("owl_type") != "owl:DatatypeProperty"
            or not _CAMEL_NAME_RE.fullmatch(str(item.get("name") or ""))
            or not isinstance(labels, Mapping)
            or not str(labels.get("zh") or "").strip()
            or str(item.get("domain_iri") or "") not in class_by_iri
            or not str(item.get("range") or "").strip()
            or int(item.get("min_count") or 0) < 0
            or int(item.get("max_count") or 0) < int(item.get("min_count") or 0)
        ):
            raise SemanticExecutionContractError("semantic_execution_data_property_invalid")

        domain_properties = class_by_iri[str(item["domain_iri"])].get("property_iris") or []
        if str(item.get("iri") or "") not in domain_properties:
            raise SemanticExecutionContractError("semantic_execution_class_property_set_invalid")

    for item in value.get("object_properties") or []:
        labels = item.get("labels") if isinstance(item, Mapping) else None
        if not isinstance(item, Mapping) or (
            item.get("property_type") != "object_property"
            or item.get("owl_type") != "owl:ObjectProperty"
            or not _CAMEL_NAME_RE.fullmatch(str(item.get("name") or ""))
            or not isinstance(labels, Mapping)
            or not str(labels.get("zh") or "").strip()
            or str(item.get("domain_iri") or "") not in class_by_iri
            or str(item.get("range_iri") or "") not in class_by_iri
            or item.get("direction") != "directed"
        ):
            raise SemanticExecutionContractError("semantic_execution_object_property_invalid")

    axioms = value.get("axioms")
    if not isinstance(axioms, Mapping):
        raise SemanticExecutionContractError("semantic_execution_axioms_invalid")
    disjoint_sets = axioms.get("disjoint_class_sets")
    if not isinstance(disjoint_sets, list) or not disjoint_sets:
        raise SemanticExecutionContractError("semantic_execution_disjointness_axiom_invalid")
    for disjoint_set in disjoint_sets:
        members = [str(member) for member in disjoint_set] if isinstance(disjoint_set, list) else []
        if len(members) < 2 or len(set(members)) != len(members) or any(
            member not in class_by_iri for member in members
        ):
            raise SemanticExecutionContractError("semantic_execution_disjointness_axiom_invalid")

    data_axioms = axioms.get("data_property_constraints")
    if not isinstance(data_axioms, list) or len(data_axioms) != len(property_by_iri):
        raise SemanticExecutionContractError("semantic_execution_data_property_axiom_invalid")
    data_axioms_by_iri = {
        str(item.get("property_iri") or ""): item
        for item in data_axioms
        if isinstance(item, Mapping)
    }
    if set(data_axioms_by_iri) != set(property_by_iri):
        raise SemanticExecutionContractError("semantic_execution_data_property_axiom_invalid")
    for iri, property_item in property_by_iri.items():
        axiom = data_axioms_by_iri[iri]
        if (
            str(axiom.get("domain_iri") or "") != str(property_item.get("domain_iri") or "")
            or str(axiom.get("range") or "") != str(property_item.get("range") or "")
            or int(axiom.get("min_count") or 0) != int(property_item.get("min_count") or 0)
            or int(axiom.get("max_count") or -1) != int(property_item.get("max_count") or -1)
            or bool(axiom.get("functional")) is not bool(property_item.get("functional"))
        ):
            raise SemanticExecutionContractError("semantic_execution_data_property_axiom_invalid")

    object_by_iri = {
        str(item.get("iri") or ""): item
        for item in value.get("object_properties") or []
        if isinstance(item, Mapping)
    }
    object_axioms = axioms.get("object_property_constraints")
    if not isinstance(object_axioms, list) or len(object_axioms) != len(object_by_iri):
        raise SemanticExecutionContractError("semantic_execution_object_property_axiom_invalid")
    object_axioms_by_iri = {
        str(item.get("property_iri") or ""): item
        for item in object_axioms
        if isinstance(item, Mapping)
    }
    if set(object_axioms_by_iri) != set(object_by_iri):
        raise SemanticExecutionContractError("semantic_execution_object_property_axiom_invalid")
    for iri, property_item in object_by_iri.items():
        axiom = object_axioms_by_iri[iri]
        if (
            str(axiom.get("domain_iri") or "") != str(property_item.get("domain_iri") or "")
            or str(axiom.get("range_iri") or "") != str(property_item.get("range_iri") or "")
            or axiom.get("directed") is not True
            or bool(axiom.get("execution_authorized"))
            is not (property_item.get("execution") == "executable_reviewed")
        ):
            raise SemanticExecutionContractError("semantic_execution_object_property_axiom_invalid")

    representation_identity = axioms.get("source_representation_identity")
    if not isinstance(representation_identity, Mapping) or (
        representation_identity.get("class_iri") != PHYSICAL_LAKE_NAMESPACE + "SourceRepresentation"
        or representation_identity.get("key_fields") != ["source_id", "source_table"]
        or representation_identity.get("source_scoped") is not True
        or representation_identity.get("cross_source_identity_resolution")
        != "requires_approved_authority_contract"
    ):
        raise SemanticExecutionContractError("semantic_execution_representation_identity_axiom_invalid")

    physical_keys: set[tuple[int, str]] = set()
    for item in value.get("source_representations") or []:
        if not isinstance(item, Mapping):
            raise SemanticExecutionContractError("semantic_execution_representation_invalid")
        binding = item.get("source_binding") or {}
        key = (int(binding.get("source_id") or 0), str(binding.get("source_table") or ""))
        if key[0] <= 0 or not key[1] or not str(binding.get("ods_table") or "") or key in physical_keys:
            raise SemanticExecutionContractError("semantic_execution_representation_binding_invalid")
        physical_keys.add(key)
        if (
            str(item.get("concept_iri") or "") not in class_by_iri
            or not str(item.get("definition") or "").strip()
            or not item.get("aliases")
            or item.get("execution_scope") != "source_scoped_ods_read_only"
        ):
            raise SemanticExecutionContractError("semantic_execution_representation_semantics_invalid")
        for field in item.get("fields") or []:
            if (
                not isinstance(field, Mapping)
                or str(field.get("property_iri") or "") not in property_by_iri
                or not str(field.get("physical_field") or "").strip()
                or property_by_iri[str(field["property_iri"])].get("domain_iri")
                != item.get("concept_iri")
            ):
                raise SemanticExecutionContractError("semantic_execution_field_binding_invalid")
            source_type = field.get("source_type")
            source_range = field.get("source_range")
            if source_type is not None and _xsd_range(source_type) != source_range:
                raise SemanticExecutionContractError("semantic_execution_field_type_invalid")
    if not physical_keys:
        raise SemanticExecutionContractError("semantic_execution_representation_empty")
    return value


def validate_virtual_ontology_semantic_gate(
    semantic_layer: Mapping[str, Any],
    semantic_layer_path: Path,
) -> dict[str, Any]:
    """Require an ontology overlay and reviewed business assets for virtual SQL.

    This gate treats overlay concepts as physical bindings and semantic assets as
    business meanings, preventing a technical table name from becoming a class.
    Legacy test fixtures without an activation gate retain compatibility; every
    activated production layer must pass this gate.
    """

    if "activation_gate" not in semantic_layer:
        return {"status": "legacy_fixture_without_activation_gate"}
    activation_gate = semantic_layer.get("activation_gate")
    if not isinstance(activation_gate, Mapping) or (
        activation_gate.get("active_for_free_form_nl2sql") is not True
    ):
        raise SemanticExecutionContractError("virtual_ontology_execution_not_activated")
    overlay_ref = str(semantic_layer.get("ontology_overlay") or "").strip()
    if not overlay_ref:
        raise SemanticExecutionContractError("virtual_ontology_overlay_missing")
    candidate = Path(overlay_ref)
    if not candidate.is_absolute():
        repository_root = Path(__file__).resolve().parents[2]
        candidate = repository_root / candidate
    try:
        overlay = json.loads(candidate.resolve(strict=True).read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise SemanticExecutionContractError("virtual_ontology_overlay_unavailable") from exc
    if not isinstance(overlay, dict) or overlay.get("schema") != "gda.ontology-runtime-overlay.v1":
        raise SemanticExecutionContractError("virtual_ontology_overlay_schema_invalid")
    if not str(overlay.get("overlay_id") or "").strip() or not str(
        overlay.get("base_ontology") or ""
    ).strip():
        raise SemanticExecutionContractError("virtual_ontology_identity_missing")

    overlay_by_table: dict[str, Mapping[str, Any]] = {}
    overlay_fields_by_table: dict[str, dict[str, Mapping[str, Any]]] = {}
    for concept in overlay.get("concepts") or []:
        if not isinstance(concept, Mapping):
            raise SemanticExecutionContractError("virtual_ontology_concept_invalid")
        table = str(concept.get("physical_binding") or "").strip()
        if not table:
            raise SemanticExecutionContractError("virtual_ontology_representation_binding_missing")
        if table in overlay_by_table:
            raise SemanticExecutionContractError("virtual_ontology_representation_binding_ambiguous")
        overlay_by_table[table] = concept
        fields_by_physical: dict[str, Mapping[str, Any]] = {}
        for field in concept.get("fields") or []:
            if not isinstance(field, Mapping):
                raise SemanticExecutionContractError("virtual_ontology_field_invalid")
            physical_field = str(field.get("physical_field") or "").strip()
            semantic_field = str(field.get("semantic_field") or "").strip()
            if not physical_field or not semantic_field or physical_field in fields_by_physical:
                raise SemanticExecutionContractError("virtual_ontology_field_identity_invalid")
            fields_by_physical[physical_field] = field
        overlay_fields_by_table[table] = fields_by_physical

    assets_by_table: dict[str, list[Mapping[str, Any]]] = {}
    assets_by_id: dict[str, Mapping[str, Any]] = {}
    for asset in semantic_layer.get("semantic_assets") or []:
        if not isinstance(asset, Mapping):
            raise SemanticExecutionContractError("virtual_ontology_business_asset_invalid")
        asset_id = str(asset.get("asset_id") or "").strip()
        if not asset_id or asset_id in assets_by_id:
            raise SemanticExecutionContractError("virtual_ontology_business_asset_identity_invalid")
        assets_by_id[asset_id] = asset
        for table in asset.get("physical_tables") or []:
            assets_by_table.setdefault(str(table), []).append(asset)

    source_binding = semantic_layer.get("source_binding") or {}
    overlay_source = overlay.get("source_evidence") or {}
    if (
        source_binding
        and overlay_source
        and int(source_binding.get("source_id") or 0)
        != int(overlay_source.get("source_id") or 0)
    ):
        raise SemanticExecutionContractError("virtual_ontology_source_binding_mismatch")

    checked = 0
    source_representations = 0
    source_property_count = 0
    business_property_count = 0
    source_property_datatype_count = 0
    object_property_count = 0
    business_fields_by_table: dict[str, tuple[str, ...]] = {}
    downgraded_execution_tables: list[str] = []
    seen_binding_tables: set[str] = set()
    for binding in semantic_layer.get("table_bindings") or []:
        if not isinstance(binding, Mapping):
            raise SemanticExecutionContractError("virtual_ontology_binding_invalid")
        table = str(binding.get("physical_table") or "")
        if not table or table in seen_binding_tables:
            raise SemanticExecutionContractError("virtual_ontology_binding_identity_invalid")
        seen_binding_tables.add(table)
        concept = overlay_by_table.get(table)
        if concept is None:
            raise SemanticExecutionContractError("virtual_ontology_representation_missing")
        binding_fields: dict[str, Mapping[str, Any]] = {}
        for field in binding.get("fields") or []:
            if not isinstance(field, Mapping):
                raise SemanticExecutionContractError("virtual_ontology_binding_field_invalid")
            physical_field = str(field.get("physical_field") or "").strip()
            semantic_field = str(field.get("semantic_field") or "").strip()
            if not physical_field or not semantic_field or physical_field in binding_fields:
                raise SemanticExecutionContractError("virtual_ontology_binding_field_identity_invalid")
            # Full discovery can expose a technical source field before the
            # overlay publishes a business-property mapping. It remains a
            # source-representation property only. The stricter check below
            # requires every executable business property to appear in both
            # the overlay and the reviewed business asset.
            binding_fields[physical_field] = field
        source_representations += 1
        source_property_count += len(binding_fields)

        if binding.get("execution_eligible") is not True:
            continue
        assets = assets_by_table.get(table, [])
        # A table can be discoverable and even have an inferred semantic-card
        # candidate while no reviewed business ontology asset exists. It stays
        # queryable only through the explicitly technical source-representation
        # route; it cannot retain business-NL2SQL authority.
        if not str(concept.get("business_asset_id") or "").strip():
            downgraded_execution_tables.append(table)
            continue
        if len(assets) != 1:
            raise SemanticExecutionContractError("virtual_ontology_business_asset_binding_invalid")
        asset = assets[0]
        asset_id = str(asset.get("asset_id") or "")
        if str(concept.get("business_asset_id") or "") != asset_id:
            raise SemanticExecutionContractError("virtual_ontology_business_asset_identity_mismatch")
        # A business asset is the class-level abstraction. The source table is
        # represented only by ``physical_binding`` in the overlay, never by a
        # class identity. This rejects the shortcut that turns a table name
        # into an ontology class.
        if asset_id.casefold() in {table.casefold(), table.rsplit(".", 1)[-1].casefold()}:
            raise SemanticExecutionContractError("virtual_ontology_table_promoted_to_business_class")
        if not str(asset.get("description") or "").strip() or not str(asset.get("grain") or "").strip():
            raise SemanticExecutionContractError("virtual_ontology_business_asset_definition_missing")
        asset_labels = asset.get("labels") or {}
        concept_labels = concept.get("labels") or {}
        if not isinstance(asset_labels, Mapping) or not all(
            str(asset_labels.get(language) or "").strip()
            and str(concept_labels.get(language) or "").strip()
            and str(asset_labels.get(language)) == str(concept_labels.get(language))
            for language in ("zh", "en", "ar")
        ):
            raise SemanticExecutionContractError("virtual_ontology_business_asset_labels_invalid")
        if (
            str(concept.get("description") or "").strip() != str(asset.get("description") or "").strip()
            or str(concept.get("grain") or "").strip() != str(asset.get("grain") or "").strip()
        ):
            raise SemanticExecutionContractError("virtual_ontology_business_asset_definition_mismatch")

        approved_fields: list[str] = []
        seen_asset_fields: set[str] = set()
        for field in asset.get("fields") or []:
            if not isinstance(field, Mapping):
                raise SemanticExecutionContractError("virtual_ontology_business_property_invalid")
            physical_field = str(field.get("physical_field") or "").strip()
            semantic_field = str(field.get("semantic_field") or "").strip()
            role = str(field.get("business_role") or "").strip()
            labels = field.get("labels") or {}
            binding_field = binding_fields.get(physical_field)
            overlay_field = overlay_fields_by_table[table].get(physical_field)
            if (
                not physical_field
                or not semantic_field
                or not role
                or physical_field in seen_asset_fields
                or binding_field is None
                or overlay_field is None
                or not isinstance(labels, Mapping)
                or not all(str(labels.get(language) or "").strip() for language in ("zh", "en", "ar"))
                or not str(field.get("description") or field.get("definition") or "").strip()
            ):
                raise SemanticExecutionContractError("virtual_ontology_business_property_invalid")
            binding_labels = binding_field.get("labels") or {}
            overlay_labels = overlay_field.get("labels") or {}
            source_type = str(
                ((binding_field.get("technical_metadata") or {}).get("data_type"))
                or ""
            ).strip()
            source_range = _xsd_range(source_type)
            if (
                str(binding_field.get("semantic_field") or "") != semantic_field
                or str(overlay_field.get("semantic_field") or "") != semantic_field
                or str(binding_field.get("business_role") or "") != role
                or str(overlay_field.get("business_role") or "") != role
                or any(
                    str(binding_labels.get(language) or "") != str(labels.get(language) or "")
                    or str(overlay_labels.get(language) or "") != str(labels.get(language) or "")
                    for language in ("zh", "en", "ar")
                )
                or binding_field.get("semantic_status") != "reviewed_business_semantics"
                or (binding_field.get("inference") or {}).get("runtime_authority") is not True
                or source_range is None
            ):
                raise SemanticExecutionContractError("virtual_ontology_business_property_mapping_invalid")
            seen_asset_fields.add(physical_field)
            approved_fields.append(physical_field)
            source_property_datatype_count += 1
        if not approved_fields:
            raise SemanticExecutionContractError("virtual_ontology_business_property_empty")
        business_fields_by_table[table] = tuple(approved_fields)
        business_property_count += len(approved_fields)
        checked += 1
    if not checked:
        raise SemanticExecutionContractError("virtual_ontology_execution_scope_empty")
    for relation in semantic_layer.get("relationships") or []:
        if not isinstance(relation, Mapping):
            raise SemanticExecutionContractError("virtual_ontology_object_property_invalid")
        if relation.get("execution_authorized") is not True:
            continue
        left = str(relation.get("left") or "")
        right = str(relation.get("right") or "")
        if not left or not right or left == right:
            raise SemanticExecutionContractError("virtual_ontology_object_property_invalid")
        object_property_count += 1
    return {
        "status": "ontology_bound",
        "overlay_id": overlay.get("overlay_id"),
        "base_ontology": overlay.get("base_ontology"),
        "checked_execution_binding_count": checked,
        "formal_contract": {
            "schema": "gda.ontology-semantic-execution-contract.v1",
            "profile": "owl2-rl-source-scoped-execution",
            "ontology_language": "OWL 2 RL",
            "constraint_language": "SHACL",
            "metadata_profile": "GB/T 48000.3-2026 Annex A",
            "ontology_iri": VIRTUAL_SEMANTIC_NAMESPACE + str(overlay["overlay_id"]),
            "business_class_count": len({
                str(assets_by_table[table][0]["asset_id"])
                for table in business_fields_by_table
            }),
            "business_data_property_count": business_property_count,
            "source_property_datatype_count": source_property_datatype_count,
            "object_property_count": object_property_count,
            "source_representation_count": source_representations,
            "source_property_count": source_property_count,
            "physical_table_is_ontology_class": False,
            "unmapped_business_field": "not_queryable",
            "technical_data_scope": "source_scoped_representation_only",
            "cross_representation_inference": "requires_reviewed_object_property",
            "business_class_identity": "semantic_asset_id; never physical_table",
            "business_property_rule": "reviewed asset, overlay and binding definitions must agree",
        },
        "downgraded_execution_tables": tuple(sorted(downgraded_execution_tables)),
        # These are execution constraints, not an ontology payload.  They are
        # intentionally retained only in memory and used to remove unmapped
        # columns from the model prompt and SQL whitelist.
        "approved_business_fields_by_table": business_fields_by_table,
    }


def scope_virtual_semantic_layer_to_ontology(
    semantic_layer: Mapping[str, Any],
    gate: Mapping[str, Any],
) -> dict[str, Any]:
    """Return a runtime copy limited to formally mapped business properties.

    Technical-only bindings remain as source representations so an explicitly
    technical inventory check can still use its declared source properties.
    A reviewed business table is different: its unmapped columns are removed
    before prompting, SQL generation and validation.
    """

    value = json.loads(json.dumps(dict(semantic_layer)))
    approved = gate.get("approved_business_fields_by_table") or {}
    if not isinstance(approved, Mapping):
        raise SemanticExecutionContractError("virtual_ontology_execution_scope_invalid")
    downgraded = {
        str(table)
        for table in gate.get("downgraded_execution_tables") or []
        if str(table).strip()
    }
    original_fields_by_table = {
        str(binding.get("physical_table") or ""): [
            dict(field)
            for field in binding.get("fields") or []
            if isinstance(field, dict)
        ]
        for binding in value.get("table_bindings") or []
        if isinstance(binding, dict) and str(binding.get("physical_table") or "")
    }
    asset_by_table = {
        str(table): asset
        for asset in value.get("semantic_assets") or []
        if isinstance(asset, dict)
        for table in asset.get("physical_tables") or []
    }
    for binding in value.get("table_bindings") or []:
        if not isinstance(binding, dict) or binding.get("execution_eligible") is not True:
            continue
        table = str(binding.get("physical_table") or "")
        if table in downgraded:
            binding["execution_eligible"] = False
            continue
        fields = approved.get(table)
        if not isinstance(fields, (list, tuple, set)) or not fields:
            raise SemanticExecutionContractError("virtual_ontology_execution_binding_scope_missing")
        allowed = {str(field) for field in fields}
        asset = asset_by_table.get(table)
        asset_id = str((asset or {}).get("asset_id") or "")
        if not asset_id:
            raise SemanticExecutionContractError("virtual_ontology_execution_asset_missing")
        class_iri = _virtual_iri("class", asset_id)
        binding["fields"] = [
            {
                **field,
                "ontology_property_iri": _virtual_iri(
                    "property",
                    f"{asset_id}.{str(field.get('semantic_field') or '')}",
                ),
                "ontology_class_iri": class_iri,
            }
            for field in binding.get("fields") or []
            if isinstance(field, dict) and str(field.get("physical_field") or "") in allowed
        ]

    # A metric bundle is executable only when every referenced field is a
    # property of an execution-authorized business class. Inventory contracts
    # over technical-only representations are preserved separately and may be
    # reintroduced only by the explicit technical route below. Keeping them in
    # ``metric_contracts`` would let direct-metric resolution reach a table
    # that is outside the business ontology scope.
    def business_contract_is_property_bound(contract: Any) -> bool:
        if not isinstance(contract, dict):
            return False
        tables = [str(table) for table in contract.get("tables") or []]
        if not tables or not all(table in approved and table not in downgraded for table in tables):
            return False
        for section in ("dimensions", "metrics", "filters"):
            for item in contract.get(section) or []:
                if not isinstance(item, Mapping):
                    return False
                field = str(item.get("field") or "")
                if field == "*":
                    continue
                table = str(item.get("table") or "")
                if table not in approved or field not in set(approved[table]):
                    return False
        return True

    original_metric_contracts = list(value.get("metric_contracts") or [])
    value["metric_contracts"] = [
        contract for contract in original_metric_contracts if business_contract_is_property_bound(contract)
    ]
    value["technical_metric_contracts"] = [
        contract
        for contract in original_metric_contracts
        if isinstance(contract, dict)
        and contract not in value["metric_contracts"]
        and bool(contract.get("tables"))
        and all(
            str(table) not in approved or str(table) in downgraded
            for table in contract.get("tables") or []
        )
    ]

    # Governance policies are authored against the wider reviewed catalogue.
    # Once the ontology gate narrows execution to published business classes,
    # a policy must not fail merely because its historical ``applies_to`` list
    # also names a technical-only representation that can no longer execute.
    #
    # A mandatory predicate may itself live on a source representation that is
    # not a business ontology class (for example, a calculation-version
    # control table).  Dropping that policy would silently widen the answer to
    # historical rows.  Promoting the control table to a business class would
    # be equally wrong.  Preserve the minimum reviewed source fields as
    # compiler-only governance support instead: they remain non-queryable to
    # the model, but the deterministic compiler can still enforce the policy.
    execution_tables = {str(table) for table in approved if str(table) not in downgraded}
    bindings_by_table = {
        str(binding.get("physical_table") or ""): binding
        for binding in value.get("table_bindings") or []
        if isinstance(binding, dict) and str(binding.get("physical_table") or "")
    }
    governance_support_fields: dict[str, set[str]] = {}
    governance_support_policy_ids: dict[str, set[str]] = {}
    governance_field_roles: dict[tuple[str, str], list[dict[str, str]]] = {}

    def add_governance_field_role(
        table: str,
        field: str,
        *,
        policy_id: str,
        role: str,
    ) -> None:
        entry = {"policy_id": policy_id, "role": role}
        roles = governance_field_roles.setdefault((table, field), [])
        if entry not in roles:
            roles.append(entry)

    def reviewed_equality_relation_exists(
        *,
        target_table: str,
        target_field: str,
        support_table: str,
        support_field: str,
    ) -> bool:
        expected = frozenset(
            (
                f"{target_table}.{target_field}".casefold(),
                f"{support_table}.{support_field}".casefold(),
            )
        )
        return any(
            isinstance(relation, dict)
            and str(relation.get("review_status") or "").casefold().startswith(
                "reviewed"
            )
            and str(relation.get("kind") or "").casefold() == "equality"
            and str(relation.get("operator") or "").casefold() in {"=", "eq"}
            and frozenset(
                (
                    str(relation.get("left") or "").casefold(),
                    str(relation.get("right") or "").casefold(),
                )
            )
            == expected
            for relation in value.get("relationships") or []
        )

    scoped_row_policies: list[dict[str, Any]] = []
    for policy in value.get("row_scope_policies") or []:
        if not isinstance(policy, dict):
            continue
        predicate_table = str((policy.get("required_predicate") or {}).get("table") or "")
        applies_to = [
            str(table)
            for table in policy.get("applies_to_tables") or []
            if str(table) in execution_tables
        ]
        if not applies_to:
            continue
        predicate = policy.get("required_predicate") or {}
        predicate_field = str(predicate.get("field") or "")
        if not predicate_table or not predicate_field:
            raise SemanticExecutionContractError(
                "virtual_ontology_row_scope_predicate_invalid"
            )
        if predicate_table not in execution_tables:
            policy_id = str(policy.get("policy_id") or "unknown")
            required_join = policy.get("required_join") or {}
            support_table = str(required_join.get("dimension_table") or "")
            support_field = str(required_join.get("dimension_field") or "")
            target_field = str(required_join.get("fact_field") or "")
            support_binding = bindings_by_table.get(predicate_table)
            if (
                support_table != predicate_table
                or not support_field
                or not target_field
                or not isinstance(support_binding, dict)
            ):
                raise SemanticExecutionContractError(
                    "virtual_ontology_row_scope_governance_support_invalid"
                )
            available_support_fields = {
                str(field.get("physical_field") or "")
                for field in support_binding.get("fields") or []
                if isinstance(field, dict)
            }
            if not {predicate_field, support_field} <= available_support_fields:
                raise SemanticExecutionContractError(
                    "virtual_ontology_row_scope_governance_support_field_missing"
                )
            for target_table in applies_to:
                target_binding = bindings_by_table.get(target_table)
                available_target_fields = {
                    str(field.get("physical_field") or "")
                    for field in original_fields_by_table.get(target_table, [])
                    if isinstance(field, dict)
                }
                if target_field not in available_target_fields or not (
                    reviewed_equality_relation_exists(
                        target_table=target_table,
                        target_field=target_field,
                        support_table=predicate_table,
                        support_field=support_field,
                    )
                ):
                    raise SemanticExecutionContractError(
                        "virtual_ontology_row_scope_governance_join_missing"
                    )
                scoped_target_fields = {
                    str(field.get("physical_field") or "")
                    for field in (target_binding or {}).get("fields") or []
                    if isinstance(field, dict)
                }
                if target_field not in scoped_target_fields:
                    add_governance_field_role(
                        target_table,
                        target_field,
                        policy_id=policy_id,
                        role="target_join",
                    )
            governance_support_fields.setdefault(predicate_table, set()).update(
                (predicate_field, support_field)
            )
            governance_support_policy_ids.setdefault(predicate_table, set()).add(
                policy_id
            )
            add_governance_field_role(
                predicate_table,
                predicate_field,
                policy_id=policy_id,
                role="required_predicate",
            )
            add_governance_field_role(
                predicate_table,
                support_field,
                policy_id=policy_id,
                role="support_join",
            )
        policy["applies_to_tables"] = applies_to
        scoped_row_policies.append(policy)
    value["row_scope_policies"] = scoped_row_policies

    for table, required_fields in governance_support_fields.items():
        binding = bindings_by_table[table]
        binding["execution_eligible"] = False
        binding["compiler_governance_support"] = True
        binding["governance_support_policy_ids"] = sorted(
            governance_support_policy_ids.get(table, set())
        )
        binding["fields"] = [
            {
                **field,
                "compiler_governance_support": True,
                "governance_support_roles": governance_field_roles.get(
                    (table, str(field.get("physical_field") or "")),
                    [],
                ),
            }
            for field in binding.get("fields") or []
            if isinstance(field, dict)
            and str(field.get("physical_field") or "") in required_fields
        ]

    for (table, field_name), roles in governance_field_roles.items():
        if table in governance_support_fields:
            continue
        binding = bindings_by_table[table]
        if any(
            str(field.get("physical_field") or "") == field_name
            for field in binding.get("fields") or []
            if isinstance(field, dict)
        ):
            continue
        original_field = next(
            (
                field
                for field in original_fields_by_table.get(table, [])
                if str(field.get("physical_field") or "") == field_name
            ),
            None,
        )
        if original_field is None:
            raise SemanticExecutionContractError(
                "virtual_ontology_row_scope_governance_support_field_missing"
            )
        binding.setdefault("fields", []).append(
            {
                **original_field,
                "compiler_governance_support": True,
                "governance_support_roles": roles,
            }
        )

    value["ontology_semantic_execution"] = {
        **{
            key: item
            for key, item in gate.items()
            if key != "approved_business_fields_by_table"
        },
        "compiler_governance_support_tables": tuple(
            sorted(governance_support_fields)
        ),
        "compiler_governance_support_policy_ids": tuple(
            sorted(
                policy_id
                for policy_ids in governance_support_policy_ids.values()
                for policy_id in policy_ids
            )
        ),
    }
    return value


def _formal_ontology_validation(
    *,
    classes: list[Mapping[str, Any]],
    data_properties: list[Mapping[str, Any]],
    object_properties: list[Mapping[str, Any]],
    source_representations: list[Mapping[str, Any]],
    axioms: Mapping[str, Any] | None = None,
    include_turtle: bool = False,
) -> dict[str, Any]:
    """Validate the execution model as RDF/OWL with SHACL shapes.

    The JSON contract remains the execution envelope, while this function
    supplies its normative OWL/SHACL projection. It is intentionally used by
    release audits rather than per-question execution, where the lightweight
    deterministic checks above fail closed first.
    """

    try:
        from pyshacl import validate as shacl_validate
        from rdflib import OWL, RDF, RDFS, BNode, Graph, Literal, Namespace, URIRef
        from rdflib.collection import Collection
    except ImportError as exc:  # pragma: no cover - deployment dependency guard
        raise SemanticExecutionContractError("semantic_execution_owl_shacl_unavailable") from exc

    SH = Namespace("http://www.w3.org/ns/shacl#")
    GDA = Namespace(PHYSICAL_LAKE_NAMESPACE)
    graph = Graph()
    graph.bind("owl", OWL)
    graph.bind("rdfs", RDFS)
    graph.bind("gda", GDA)
    axioms = dict(axioms or {})

    def uri(value: Any) -> URIRef:
        raw = str(value or "").strip()
        if raw == "rdfs:Literal":
            return RDFS.Literal
        if raw.startswith("http://") or raw.startswith("https://"):
            return URIRef(raw)
        raise SemanticExecutionContractError("semantic_execution_ontology_iri_invalid")

    for item in classes:
        class_iri = uri(item.get("iri"))
        graph.add((class_iri, RDF.type, OWL.Class))
        graph.add((class_iri, GDA.ontologyName, Literal(str(item.get("name") or ""))))
        for label in (item.get("labels") or {}).values():
            if str(label or "").strip():
                graph.add((class_iri, RDFS.label, Literal(str(label))))
        graph.add((class_iri, RDFS.comment, Literal(str(item.get("definition") or ""))))
        if item.get("parent_iri"):
            graph.add((class_iri, RDFS.subClassOf, uri(item.get("parent_iri"))))

    for item in data_properties:
        property_iri = uri(item.get("iri"))
        graph.add((property_iri, RDF.type, OWL.DatatypeProperty))
        if item.get("functional"):
            graph.add((property_iri, RDF.type, OWL.FunctionalProperty))
        graph.add((property_iri, GDA.ontologyName, Literal(str(item.get("name") or ""))))
        for label in (item.get("labels") or {}).values():
            if str(label or "").strip():
                graph.add((property_iri, RDFS.label, Literal(str(label))))
        graph.add((property_iri, RDFS.comment, Literal(str(item.get("definition") or ""))))
        graph.add((property_iri, RDFS.domain, uri(item.get("domain_iri"))))
        graph.add((property_iri, RDFS.range, uri(item.get("range"))))

    for item in object_properties:
        property_iri = uri(item.get("iri"))
        graph.add((property_iri, RDF.type, OWL.ObjectProperty))
        graph.add((property_iri, GDA.ontologyName, Literal(str(item.get("name") or ""))))
        for label in (item.get("labels") or {}).values():
            if str(label or "").strip():
                graph.add((property_iri, RDFS.label, Literal(str(label))))
        graph.add((property_iri, RDFS.comment, Literal(str(item.get("definition") or ""))))
        graph.add((property_iri, RDFS.domain, uri(item.get("domain_iri"))))
        graph.add((property_iri, RDFS.range, uri(item.get("range_iri"))))

    for disjoint_set in axioms.get("disjoint_class_sets") or []:
        members = [uri(value) for value in disjoint_set]
        for index, left in enumerate(members):
            for right in members[index + 1 :]:
                graph.add((left, OWL.disjointWith, right))

    data_constraints = {
        str(item.get("property_iri") or ""): item
        for item in axioms.get("data_property_constraints") or []
        if isinstance(item, Mapping)
    }
    for item in data_properties:
        constraint = data_constraints.get(str(item.get("iri") or ""))
        if constraint is None:
            continue
        restriction = BNode()
        graph.add((uri(item.get("domain_iri")), RDFS.subClassOf, restriction))
        graph.add((restriction, RDF.type, OWL.Restriction))
        graph.add((restriction, OWL.onProperty, uri(item.get("iri"))))
        graph.add((restriction, OWL.minCardinality, Literal(int(constraint["min_count"]))))
        graph.add((restriction, OWL.maxCardinality, Literal(int(constraint["max_count"]))))

    object_constraints = {
        str(item.get("property_iri") or ""): item
        for item in axioms.get("object_property_constraints") or []
        if isinstance(item, Mapping)
    }

    physical_tables: set[str] = set()
    representation_identity = axioms.get("source_representation_identity") or {}
    if representation_identity:
        representation_class = uri(representation_identity.get("class_iri"))
        key_list = BNode()
        Collection(graph, key_list, [GDA.sourceId, GDA.sourceTable])
        graph.add((representation_class, OWL.hasKey, key_list))
    for item in source_representations:
        representation = BNode()
        binding = item.get("source_binding") or {}
        source_table = str(binding.get("source_table") or "")
        physical_tables.add(source_table)
        graph.add((representation, RDF.type, GDA.SourceRepresentation))
        if binding.get("source_id") is not None:
            graph.add((representation, GDA.sourceId, Literal(int(binding["source_id"]))))
        graph.add((representation, GDA.representsConcept, uri(item.get("concept_iri"))))
        graph.add((representation, GDA.sourceTable, Literal(source_table)))
        graph.add((representation, GDA.odsTable, Literal(str(binding.get("ods_table") or ""))))
        for field in item.get("fields") or []:
            field_map = BNode()
            graph.add((representation, GDA.hasFieldMapping, field_map))
            graph.add((field_map, GDA.mapsProperty, uri(field.get("property_iri"))))
            graph.add((field_map, GDA.physicalField, Literal(str(field.get("physical_field") or ""))))

    if any((URIRef(table), RDF.type, OWL.Class) in graph for table in physical_tables if table.startswith("http")):
        raise SemanticExecutionContractError("semantic_execution_table_promoted_to_class")

    shapes = Graph()
    shapes.bind("sh", SH)
    shapes.bind("owl", OWL)
    shapes.bind("rdfs", RDFS)
    shapes.bind("gda", GDA)

    def required_property(shape: BNode, path: URIRef, *, class_: URIRef | None = None) -> None:
        property_shape = BNode()
        shapes.add((shape, SH.property, property_shape))
        shapes.add((property_shape, SH.path, path))
        shapes.add((property_shape, SH.minCount, Literal(1)))
        if class_ is not None:
            shapes.add((property_shape, SH["class"], class_))

    class_shape = BNode()
    shapes.add((class_shape, RDF.type, SH.NodeShape))
    shapes.add((class_shape, SH.targetClass, OWL.Class))
    required_property(class_shape, GDA.ontologyName)
    required_property(class_shape, RDFS.label)
    required_property(class_shape, RDFS.comment)

    for target_class in (OWL.DatatypeProperty, OWL.ObjectProperty):
        property_shape = BNode()
        shapes.add((property_shape, RDF.type, SH.NodeShape))
        shapes.add((property_shape, SH.targetClass, target_class))
        for path in (GDA.ontologyName, RDFS.label, RDFS.comment, RDFS.domain, RDFS.range):
            required_property(property_shape, path)

    for item in data_properties:
        constraint = data_constraints.get(str(item.get("iri") or ""))
        if constraint is None:
            continue
        value_shape = BNode()
        shapes.add((value_shape, RDF.type, SH.NodeShape))
        shapes.add((value_shape, SH.targetClass, uri(item.get("domain_iri"))))
        property_shape = BNode()
        shapes.add((value_shape, SH.property, property_shape))
        shapes.add((property_shape, SH.path, uri(item.get("iri"))))
        shapes.add((property_shape, SH.minCount, Literal(int(constraint["min_count"]))))
        shapes.add((property_shape, SH.maxCount, Literal(int(constraint["max_count"]))))
        range_iri = str(constraint.get("range") or "")
        if range_iri.startswith(_XSD_NAMESPACE):
            shapes.add((property_shape, SH.datatype, uri(range_iri)))

    representation_shape = BNode()
    shapes.add((representation_shape, RDF.type, SH.NodeShape))
    shapes.add((representation_shape, SH.targetClass, GDA.SourceRepresentation))
    required_property(representation_shape, GDA.representsConcept, class_=OWL.Class)
    if representation_identity:
        required_property(representation_shape, GDA.sourceId)
    required_property(representation_shape, GDA.sourceTable)
    required_property(representation_shape, GDA.odsTable)
    required_property(representation_shape, GDA.hasFieldMapping)
    not_a_class = BNode()
    shapes.add((not_a_class, SH["class"], OWL.Class))
    shapes.add((representation_shape, SH["not"], not_a_class))

    conforms, _, _ = shacl_validate(
        data_graph=graph,
        shacl_graph=shapes,
        inference="none",
        abort_on_first=False,
        meta_shacl=False,
        advanced=False,
    )
    if not conforms:
        raise SemanticExecutionContractError("semantic_execution_shacl_validation_failed")
    result = {
        "ontology_language": "OWL 2 RL",
        "constraint_language": "SHACL",
        "shacl_conforms": True,
        "owl_triple_count": len(graph),
        "logical_axiom_count": (
            sum(len(item) * (len(item) - 1) // 2 for item in axioms.get("disjoint_class_sets") or [])
            + len(data_constraints)
            + len(object_constraints)
            + (1 if representation_identity else 0)
        ),
    }
    if include_turtle:
        turtle = graph.serialize(format="turtle")
        result["owl_turtle"] = str(turtle)
    return result


def audit_physical_lake_semantic_execution_ontology(
    contract: Mapping[str, Any],
    *,
    include_turtle: bool = False,
) -> dict[str, Any]:
    """Run the RDF/OWL and SHACL audit for a validated physical-lake contract."""

    value = validate_physical_lake_semantic_execution_contract(contract)
    return _formal_ontology_validation(
        classes=[item for item in value.get("classes") or [] if isinstance(item, Mapping)],
        data_properties=[
            item for item in value.get("data_properties") or [] if isinstance(item, Mapping)
        ],
        object_properties=[
            item for item in value.get("object_properties") or [] if isinstance(item, Mapping)
        ],
        source_representations=[
            item
            for item in value.get("source_representations") or []
            if isinstance(item, Mapping)
        ],
        axioms=value.get("axioms"),
        include_turtle=include_turtle,
    )


def audit_virtual_ontology_semantic_execution(
    semantic_layer: Mapping[str, Any],
    gate: Mapping[str, Any],
    *,
    include_turtle: bool = False,
) -> dict[str, Any]:
    """Run the RDF/OWL and SHACL audit for executable virtual business scope."""

    approved = gate.get("approved_business_fields_by_table") or {}
    if not isinstance(approved, Mapping):
        raise SemanticExecutionContractError("virtual_ontology_execution_scope_invalid")
    assets_by_table = {
        str(table): asset
        for asset in semantic_layer.get("semantic_assets") or []
        if isinstance(asset, Mapping)
        for table in asset.get("physical_tables") or []
    }
    bindings_by_table = {
        str(binding.get("physical_table") or ""): binding
        for binding in semantic_layer.get("table_bindings") or []
        if isinstance(binding, Mapping)
    }
    classes: list[dict[str, Any]] = []
    data_properties: list[dict[str, Any]] = []
    representations: list[dict[str, Any]] = []
    class_iri_by_table: dict[str, str] = {}
    source_id = int((semantic_layer.get("source_binding") or {}).get("source_id") or 0)
    if source_id <= 0:
        raise SemanticExecutionContractError("virtual_ontology_source_binding_missing")
    classes.append(
        {
            "iri": PHYSICAL_LAKE_NAMESPACE + "SourceRepresentation",
            "name": "SourceRepresentation",
            "labels": _labels("来源表示"),
            "definition": "受控来源中用于承载业务概念的物理表或视图表示；它不是业务本体类。",
        }
    )
    for table, fields in approved.items():
        asset = assets_by_table.get(str(table))
        binding = bindings_by_table.get(str(table))
        if not isinstance(asset, Mapping) or not isinstance(binding, Mapping):
            raise SemanticExecutionContractError("virtual_ontology_execution_asset_missing")
        asset_id = str(asset.get("asset_id") or "")
        class_iri = _virtual_iri("class", asset_id)
        class_iri_by_table[str(table)] = class_iri
        classes.append(
            {
                "iri": class_iri,
                "name": _pascal_name(asset_id),
                "labels": dict(asset.get("labels") or {}),
                "definition": str(asset.get("description") or ""),
            }
        )
        binding_fields = {
            str(field.get("physical_field") or ""): field
            for field in binding.get("fields") or []
            if isinstance(field, Mapping)
        }
        representation_fields: list[dict[str, Any]] = []
        for physical_field in fields:
            field = binding_fields.get(str(physical_field))
            if not isinstance(field, Mapping):
                raise SemanticExecutionContractError("virtual_ontology_business_property_mapping_invalid")
            property_iri = _virtual_iri(
                "property", f"{asset_id}.{str(field.get('semantic_field') or '')}"
            )
            data_properties.append(
                {
                    "iri": property_iri,
                    "name": _camel_name(f"{asset_id}.{str(field.get('semantic_field') or '')}"),
                    "labels": dict(field.get("labels") or {}),
                    "definition": str(field.get("description") or field.get("definition") or ""),
                    "domain_iri": class_iri,
                    "range": _xsd_range(
                        (field.get("technical_metadata") or {}).get("data_type")
                    ),
                    "functional": True,
                }
            )
            representation_fields.append(
                {
                    "property_iri": property_iri,
                    "physical_field": str(physical_field),
                }
            )
        representations.append(
            {
                "concept_iri": class_iri,
                "source_binding": {
                    "source_id": source_id,
                    "source_table": str(table),
                    "ods_table": str(table),
                },
                "fields": representation_fields,
            }
        )

    object_properties: list[dict[str, Any]] = []
    for index, relation in enumerate(semantic_layer.get("relationships") or []):
        if not isinstance(relation, Mapping) or relation.get("execution_authorized") is not True:
            continue
        left_table = str(relation.get("left") or "").rsplit(".", 1)[0]
        right_table = str(relation.get("right") or "").rsplit(".", 1)[0]
        left_class = class_iri_by_table.get(left_table)
        right_class = class_iri_by_table.get(right_table)
        if not left_class or not right_class:
            continue
        relation_id = str(relation.get("relation_id") or f"relation-{index}")
        object_properties.append(
            {
                "iri": _virtual_iri("relation", relation_id),
                "name": _camel_name(relation_id),
                "labels": _labels(str(relation.get("kind") or "relationship")),
                "definition": str(relation.get("notes") or relation.get("operator") or ""),
                "domain_iri": left_class,
                "range_iri": right_class,
            }
        )
    axioms = {
        # The virtual source artifacts do not declare mutually exclusive
        # business classes, so this intentionally remains empty rather than
        # inventing disjointness from table layout. Property and identity
        # constraints are still formalized below.
        "disjoint_class_sets": [],
        "data_property_constraints": [
            {
                "property_iri": str(item["iri"]),
                "domain_iri": str(item["domain_iri"]),
                "range": str(item["range"]),
                "min_count": 0,
                "max_count": 1,
                "functional": True,
            }
            for item in data_properties
        ],
        "object_property_constraints": [
            {
                "property_iri": str(item["iri"]),
                "domain_iri": str(item["domain_iri"]),
                "range_iri": str(item["range_iri"]),
                "directed": True,
                "execution_authorized": True,
            }
            for item in object_properties
        ],
        "source_representation_identity": {
            "class_iri": PHYSICAL_LAKE_NAMESPACE + "SourceRepresentation",
            "key_fields": ["source_id", "source_table"],
            "source_scoped": True,
            "cross_source_identity_resolution": "requires_approved_authority_contract",
        },
    }
    return _formal_ontology_validation(
        classes=classes,
        data_properties=data_properties,
        object_properties=object_properties,
        source_representations=representations,
        axioms=axioms,
        include_turtle=include_turtle,
    )


__all__ = [
    "PHYSICAL_LAKE_SEMANTIC_SCHEMA",
    "SemanticExecutionContractError",
    "build_physical_lake_semantic_execution_contract",
    "validate_physical_lake_semantic_execution_contract",
    "validate_virtual_ontology_semantic_gate",
    "scope_virtual_semantic_layer_to_ontology",
    "audit_physical_lake_semantic_execution_ontology",
    "audit_virtual_ontology_semantic_execution",
]
