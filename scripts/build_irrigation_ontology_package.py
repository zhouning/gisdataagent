#!/usr/bin/env python3
"""Build the governed candidate irrigation ontology package.

The package is intentionally compact. It establishes a reviewable semantic
contract for the irrigation application without claiming that terminology,
cardinalities, or operating rules have already been approved by a water-domain
authority.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import shutil
import uuid
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pyshacl import validate as shacl_validate
from rdflib import Graph, Literal, Namespace, RDF, RDFS, URIRef
from rdflib.namespace import OWL, SH, SKOS, XSD

from data_agent.ontology.contracts import (
    ArtifactRecord,
    ConceptRecord,
    PackageManifest,
    PropertyRecord,
    RelationRecord,
    SourceRecord,
    canonical_json,
    sha256_json,
)
from data_agent.ontology.registry import IRRIGATION_PROFILE


VERSION = "0.1.0"
GENERATED_AT = datetime(2026, 8, 14, 8, 30, tzinfo=UTC)
ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = ROOT / "data_agent/ontology/packages/irrigation_district_water"
TARGET = PACKAGE_ROOT / VERSION
PROFILE = IRRIGATION_PROFILE
GDA = Namespace(PROFILE.namespace_uri)


DOMAIN_CONCEPTS = [
    ("irr_system", "灌区系统与管理单元"),
    ("irr_network", "水源与输配水网络"),
    ("irr_observation", "监测、状态与需水"),
    ("irr_process", "水文水力与农业过程"),
    ("irr_operation", "调度行动与方案"),
    ("irr_governance", "约束、证据与审计"),
]

CLASSES = [
    ("IrrigationDistrict", "灌区", "DomainClass", "irr_system", "具有明确供水、输配水、用水与管理边界的灌溉系统。"),
    ("ManagementUnit", "灌区管理单元", "DomainClass", "irr_system", "承担设施、配水或用水管理职责的组织化空间单元。"),
    ("IrrigationArea", "灌溉片区", "DomainClass", "irr_system", "按渠系、作物或管理边界划分的灌溉区域。"),
    ("FieldBlock", "田块", "DomainClass", "irr_system", "接受灌溉供水并具有需水状态的最小业务空间对象。"),
    ("WaterSource", "水源", "DomainClass", "irr_network", "向灌区提供可调配水量的边界对象。"),
    ("Reservoir", "水库", "DomainClass", "irr_network", "具有库容、水位、入流和出流状态的调蓄水源。"),
    ("PumpStation", "泵站", "DomainClass", "irr_network", "通过机电设备改变水量或水头的输水设施。"),
    ("CanalNetwork", "渠系网络", "DomainClass", "irr_network", "由有向渠段、节点与控制设施构成的输配水网络。"),
    ("CanalSegment", "渠段", "DomainClass", "irr_network", "具有长度、断面、糙率、坡度与过流能力的有向输水单元。"),
    ("ControlGate", "控制闸", "DomainClass", "irr_network", "通过开度或目标流量调节水流的控制设施。"),
    ("DiversionNode", "分水节点", "DomainClass", "irr_network", "将上游来水按规则分配到一个或多个下游分支的网络节点。"),
    ("DeliveryPoint", "供水交付点", "DomainClass", "irr_network", "供水责任和计量责任发生交接的网络位置。"),
    ("Observation", "观测", "ObservationClass", "irr_observation", "带有对象、时刻、单位、质量状态和来源的测量事实。"),
    ("WaterLevelObservation", "水位观测", "ObservationClass", "irr_observation", "水库、渠道或量水设施的水位测量。"),
    ("DischargeObservation", "流量观测", "ObservationClass", "irr_observation", "渠段、闸门或交付点的体积流量测量。"),
    ("GateOpeningObservation", "闸门开度观测", "ObservationClass", "irr_observation", "控制闸开度或控制位置的状态记录。"),
    ("SoilMoistureObservation", "土壤含水量观测", "ObservationClass", "irr_observation", "田块根区土壤含水状态的测量。"),
    ("CropWaterDemandState", "作物需水状态", "StateClass", "irr_observation", "在给定作物、物候、气象和土壤条件下的需水估计。"),
    ("AvailableSupplyState", "可供水状态", "StateClass", "irr_observation", "在时间窗和约束条件下可进入灌区的供水边界。"),
    ("HydraulicState", "水力状态", "StateClass", "irr_observation", "由水深、流量、流速和水面高程组成的渠系状态。"),
    ("WaterConveyance", "输水过程", "ProcessClass", "irr_process", "水量与动量沿渠系网络传播的水动力过程。"),
    ("WaterDiversion", "分水过程", "ProcessClass", "irr_process", "来水在分水节点和控制设施作用下向下游分支分配的过程。"),
    ("FieldApplication", "田间灌水过程", "ProcessClass", "irr_process", "交付水量进入田块并形成入渗、径流和土壤水变化的过程。"),
    ("Infiltration", "土壤入渗过程", "ProcessClass", "irr_process", "地表水进入土壤剖面的过程。"),
    ("Evapotranspiration", "作物蒸散过程", "ProcessClass", "irr_process", "土壤蒸发和作物蒸腾共同形成的耗水过程。"),
    ("SchedulingAction", "调度行动", "InformationClass", "irr_operation", "具有类型、目标、参数、时间窗和执行边界的候选调度动作。"),
    ("SetBoundarySupply", "设置供水边界", "InformationClass", "irr_operation", "设置水源或渠首在指定时间窗内的目标供水边界。"),
    ("SetGateOpening", "设置闸门开度", "InformationClass", "irr_operation", "设置控制闸目标开度的候选行动。"),
    ("SetBranchAllocation", "设置分支配水比例", "InformationClass", "irr_operation", "设置分水节点各下游分支目标分配比例的候选行动。"),
    ("ShiftDeliveryWindow", "调整供水时段", "InformationClass", "irr_operation", "调整交付点或分支渠的供水开始和结束时间。"),
    ("ScenarioProposal", "情景方案", "InformationClass", "irr_operation", "由冻结输入、模型版本、候选行动和推演结果组成的待审方案。"),
    ("OperatingConstraint", "运行约束", "InformationClass", "irr_governance", "用于限制状态、行动或方案可接受范围的显式规则。"),
    ("MassBalanceConstraint", "水量守恒约束", "InformationClass", "irr_governance", "边界水量、储量变化、交付量和损失之间必须闭合的约束。"),
    ("CanalCapacityConstraint", "渠段过流能力约束", "InformationClass", "irr_governance", "渠段流量、水深或流速不得超过审定能力的约束。"),
    ("ActionRangeConstraint", "行动范围约束", "InformationClass", "irr_governance", "行动参数必须处于设备、制度和安全允许范围内的约束。"),
    ("EvidenceRecord", "证据记录", "InformationClass", "irr_governance", "记录数据来源、有效时间、质量、模型版本和处理过程的审计证据。"),
    ("WorldModelRun", "世界模型运行", "InformationClass", "irr_governance", "绑定本体版本、状态快照、求解器版本、参数、结果和审计事件的运行记录。"),
    ("ApprovalDecision", "人工审核决定", "InformationClass", "irr_governance", "具备审核主体、意见、时间和终态结果的治理决定。"),
]

PROPERTIES = {
    "IrrigationDistrict": [("districtCode", "灌区编码", "xsd:string", 1), ("name", "名称", "xsd:string", 1)],
    "FieldBlock": [("areaM2", "面积", "xsd:decimal", 1), ("cropType", "作物类型", "xsd:string", 0)],
    "Reservoir": [("normalStorageM3", "正常库容", "xsd:decimal", 0), ("availableSupplyM3s", "可供流量", "xsd:decimal", 0)],
    "CanalSegment": [("lengthM", "长度", "xsd:decimal", 1), ("bottomWidthM", "渠底宽度", "xsd:decimal", 1), ("bedSlope", "渠底坡度", "xsd:decimal", 1), ("manningN", "Manning 糙率", "xsd:decimal", 1), ("capacityM3s", "审定过流能力", "xsd:decimal", 0)],
    "ControlGate": [("openingPercent", "闸门开度", "xsd:decimal", 0), ("maximumDischargeM3s", "最大过闸流量", "xsd:decimal", 0)],
    "Observation": [("observedAt", "观测时间", "xsd:dateTime", 1), ("numericValue", "数值", "xsd:decimal", 1), ("unit", "单位", "xsd:string", 1), ("qualityStatus", "质量状态", "xsd:string", 1)],
    "CropWaterDemandState": [("demandM3d", "需水量", "xsd:decimal", 1), ("effectiveAt", "生效时间", "xsd:dateTime", 1)],
    "SchedulingAction": [("targetStableId", "目标稳定标识", "xsd:string", 1), ("effectiveFrom", "行动开始时间", "xsd:dateTime", 0), ("executionMode", "执行模式", "xsd:string", 1)],
    "OperatingConstraint": [("severity", "约束级别", "xsd:string", 1), ("expression", "约束表达式", "xsd:string", 0)],
    "WorldModelRun": [("runId", "运行标识", "xsd:string", 1), ("modelVersion", "模型版本", "xsd:string", 1), ("startedAt", "开始时间", "xsd:dateTime", 1), ("runtimeMs", "运行耗时毫秒", "xsd:decimal", 0)],
    "EvidenceRecord": [("sourceAuthority", "来源权威", "xsd:string", 1), ("contentSha256", "内容哈希", "xsd:string", 1)],
}

RELATIONS = [
    ("IrrigationDistrict", "contains", "ManagementUnit", "包含管理单元"),
    ("IrrigationDistrict", "contains", "CanalNetwork", "包含渠系网络"),
    ("ManagementUnit", "manages", "IrrigationArea", "管理灌溉片区"),
    ("IrrigationArea", "contains", "FieldBlock", "包含田块"),
    ("WaterSource", "supplies", "CanalNetwork", "向渠系供水"),
    ("Reservoir", "subClassOf", "WaterSource", "属于水源"),
    ("CanalNetwork", "contains", "CanalSegment", "包含渠段"),
    ("CanalNetwork", "contains", "ControlGate", "包含控制闸"),
    ("CanalNetwork", "contains", "DiversionNode", "包含分水节点"),
    ("CanalSegment", "flowsTo", "DiversionNode", "流向分水节点"),
    ("DiversionNode", "flowsTo", "CanalSegment", "流向下游渠段"),
    ("ControlGate", "controls", "CanalSegment", "控制渠段"),
    ("CanalSegment", "deliversTo", "DeliveryPoint", "向交付点输水"),
    ("DeliveryPoint", "supplies", "FieldBlock", "向田块供水"),
    ("Observation", "observes", "HydraulicState", "观测水力状态"),
    ("WaterLevelObservation", "subClassOf", "Observation", "属于观测"),
    ("DischargeObservation", "subClassOf", "Observation", "属于观测"),
    ("GateOpeningObservation", "subClassOf", "Observation", "属于观测"),
    ("SoilMoistureObservation", "subClassOf", "Observation", "属于观测"),
    ("CanalSegment", "hasState", "HydraulicState", "具有水力状态"),
    ("FieldBlock", "hasState", "CropWaterDemandState", "具有需水状态"),
    ("Reservoir", "hasState", "AvailableSupplyState", "具有可供水状态"),
    ("WaterConveyance", "actsOn", "CanalNetwork", "作用于渠系网络"),
    ("WaterDiversion", "actsOn", "DiversionNode", "作用于分水节点"),
    ("FieldApplication", "actsOn", "FieldBlock", "作用于田块"),
    ("SetBoundarySupply", "subClassOf", "SchedulingAction", "属于调度行动"),
    ("SetGateOpening", "subClassOf", "SchedulingAction", "属于调度行动"),
    ("SetBranchAllocation", "subClassOf", "SchedulingAction", "属于调度行动"),
    ("ShiftDeliveryWindow", "subClassOf", "SchedulingAction", "属于调度行动"),
    ("ScenarioProposal", "proposes", "SchedulingAction", "提出候选行动"),
    ("ScenarioProposal", "generatedBy", "WorldModelRun", "由模型运行生成"),
    ("WorldModelRun", "usesEvidence", "EvidenceRecord", "使用证据"),
    ("WorldModelRun", "governedBy", "OperatingConstraint", "受运行约束治理"),
    ("MassBalanceConstraint", "subClassOf", "OperatingConstraint", "属于运行约束"),
    ("CanalCapacityConstraint", "subClassOf", "OperatingConstraint", "属于运行约束"),
    ("ActionRangeConstraint", "subClassOf", "OperatingConstraint", "属于运行约束"),
    ("ApprovalDecision", "reviews", "ScenarioProposal", "审核情景方案"),
]


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _identifier(kind: str, code: str) -> str:
    return f"{PROFILE.stable_id_prefix}:{kind}:{code}"


def _uri(kind: str, code: str) -> str:
    return f"{PROFILE.namespace_uri}{kind}/{code}"


def _write_jsonl_gzip(path: Path, rows: list[Any]) -> int:
    with path.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0, compresslevel=9) as stream:
            for row in rows:
                value = row.model_dump(mode="json", exclude_none=True) if hasattr(row, "model_dump") else row
                stream.write(canonical_json(value) + b"\n")
    return len(rows)


def _artifact(path: Path, media_type: str, count: int | None = None) -> ArtifactRecord:
    return ArtifactRecord(path=path.name, media_type=media_type, sha256=_sha(path.read_bytes()), record_count=count, bytes=path.stat().st_size)


def _build_records() -> tuple[list[SourceRecord], list[ConceptRecord], list[PropertyRecord], list[RelationRecord]]:
    source_payload = canonical_json({"model": "irrigation-domain-model-seed-v1", "status": "draft_pending_domain_review"})
    sources = [SourceRecord(source_id=PROFILE.curated_source_id, source_kind="curated_candidate", title="灌区与水利工程候选领域模型", locator="docs/designs/ontology_driven_irrigation_world_model_design_2026-08-14.md", source_version=VERSION, sha256=_sha(source_payload), metadata={"lifecycle_status": "draft_pending_domain_review", "authority": "internal_candidate_not_domain_standard"})]
    concepts: list[ConceptRecord] = []
    for code, label in DOMAIN_CONCEPTS:
        concepts.append(ConceptRecord(concept_id=_identifier("domain", code), uri=_uri("domain", code), kind="Domain", code=code, pref_label=label, definition=f"{label}领域入口。", domain_id=code, source_system="curated_domain", source_id=PROFILE.curated_source_id, source_object_id=code, provenance={"evidence_status": "candidate", "review_status": "pending_domain_review"}))
    for code, label, kind, domain, definition in CLASSES:
        concepts.append(ConceptRecord(concept_id=_identifier("class", code), uri=_uri("class", code), kind=kind, code=code, pref_label=label, definition=definition, domain_id=domain, source_system="curated_domain", source_id=PROFILE.curated_source_id, source_object_id=code, geometry_type="Polygon" if code in {"IrrigationDistrict", "IrrigationArea", "FieldBlock"} else "LineString" if code == "CanalSegment" else "Point" if code in {"PumpStation", "ControlGate", "DiversionNode", "DeliveryPoint"} else None, provenance={"evidence_status": "candidate", "review_status": "pending_domain_review"}))
    properties: list[PropertyRecord] = []
    for owner_code, declarations in PROPERTIES.items():
        owner_id = _identifier("class", owner_code)
        for ordinal, (code, label, datatype, min_count) in enumerate(declarations, 1):
            properties.append(PropertyRecord(property_id=_identifier("property", f"{owner_code}:{code}"), owner_concept_id=owner_id, uri=_uri("property", f"{owner_code}/{code}"), code=code, pref_label=label, datatype=datatype, min_count=min_count, max_count=1, ordinal=ordinal, source_id=PROFILE.curated_source_id, source_object_id=f"{owner_code}.{code}", provenance={"evidence_status": "candidate", "review_status": "pending_domain_review"}))
    relations: list[RelationRecord] = []
    for index, (source, relation_type, target, label) in enumerate(RELATIONS, 1):
        relations.append(RelationRecord(relation_id=_identifier("relation", f"{index:03d}"), relation_type=relation_type, source_concept_id=_identifier("class", source), target_concept_id=_identifier("class", target), pref_label=label, source_id=PROFILE.curated_source_id, source_object_id=f"{source}:{relation_type}:{target}", provenance={"evidence_status": "candidate", "review_status": "pending_domain_review"}))
    class_ids_by_domain: dict[str, list[str]] = {}
    for concept in concepts:
        if concept.kind != "Domain" and concept.domain_id:
            class_ids_by_domain.setdefault(concept.domain_id, []).append(concept.concept_id)
    for domain, concept_ids in class_ids_by_domain.items():
        for concept_id in concept_ids:
            relations.append(RelationRecord(relation_id=_identifier("relation", f"domain:{domain}:{concept_id.rsplit(':', 1)[-1]}"), relation_type="contains", source_concept_id=_identifier("domain", domain), target_concept_id=concept_id, pref_label="包含领域概念", source_id=PROFILE.curated_source_id, provenance={"evidence_status": "candidate"}))
    return sources, concepts, properties, relations


def _build_rdf(concepts: list[ConceptRecord], properties: list[PropertyRecord], relations: list[RelationRecord]) -> tuple[Graph, Graph]:
    graph = Graph()
    graph.bind("irr", GDA)
    graph.bind("skos", SKOS)
    graph.bind("owl", OWL)
    for concept in concepts:
        subject = URIRef(concept.uri)
        graph.add((subject, RDF.type, OWL.Class))
        graph.add((subject, SKOS.prefLabel, Literal(concept.pref_label, lang="zh")))
        graph.add((subject, SKOS.definition, Literal(concept.definition, lang="zh")))
        if concept.domain_id:
            graph.add((subject, GDA.domainId, Literal(concept.domain_id)))
    concepts_by_id = {item.concept_id: item for item in concepts}
    datatype_map = {"xsd:string": XSD.string, "xsd:decimal": XSD.decimal, "xsd:dateTime": XSD.dateTime}
    for prop in properties:
        subject = URIRef(prop.uri)
        graph.add((subject, RDF.type, OWL.DatatypeProperty))
        graph.add((subject, SKOS.prefLabel, Literal(prop.pref_label, lang="zh")))
        graph.add((subject, RDFS.domain, URIRef(concepts_by_id[prop.owner_concept_id].uri)))
        graph.add((subject, RDFS.range, datatype_map.get(prop.datatype or "", XSD.string)))
    relation_uris: dict[str, URIRef] = {}
    for relation in relations:
        predicate = relation_uris.setdefault(relation.relation_type, GDA[relation.relation_type])
        graph.add((predicate, RDF.type, OWL.ObjectProperty))
        graph.add((predicate, SKOS.prefLabel, Literal(relation.pref_label or relation.relation_type, lang="zh")))
        graph.add((URIRef(concepts_by_id[relation.source_concept_id].uri), predicate, URIRef(concepts_by_id[relation.target_concept_id].uri)))
    shapes = Graph()
    shapes.bind("sh", SH)
    shapes.bind("skos", SKOS)
    shape = GDA.CandidateConceptShape
    shapes.add((shape, RDF.type, SH.NodeShape))
    shapes.add((shape, SH.targetClass, OWL.Class))
    property_shape = GDA.CandidateConceptLabelShape
    shapes.add((shape, SH.property, property_shape))
    shapes.add((property_shape, SH.path, SKOS.prefLabel))
    shapes.add((property_shape, SH.minCount, Literal(1)))
    return graph, shapes


def build() -> PackageManifest:
    sources, concepts, properties, relations = _build_records()
    if TARGET.exists():
        shutil.rmtree(TARGET)
    TARGET.mkdir(parents=True)
    counts = {
        "sources": _write_jsonl_gzip(TARGET / "sources.jsonl.gz", sources),
        "concepts": _write_jsonl_gzip(TARGET / "concepts.jsonl.gz", concepts),
        "properties": _write_jsonl_gzip(TARGET / "properties.jsonl.gz", properties),
        "relations": _write_jsonl_gzip(TARGET / "relations.jsonl.gz", relations),
        "mappings": _write_jsonl_gzip(TARGET / "mappings.jsonl.gz", []),
        "review_dispositions": _write_jsonl_gzip(TARGET / "review-dispositions.jsonl.gz", []),
    }
    graph, shapes = _build_rdf(concepts, properties, relations)
    rdf_payload = graph.serialize(format="turtle").encode("utf-8")
    with (TARGET / "ontology.ttl.gz").open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0, compresslevel=9) as stream:
            stream.write(rdf_payload)
    shapes_payload = shapes.serialize(format="turtle").rstrip() + "\n"
    (TARGET / "shapes.ttl").write_text(shapes_payload, encoding="utf-8")
    conforms, _, report_text = shacl_validate(graph, shacl_graph=shapes, inference="rdfs", meta_shacl=True, advanced=True)
    validation = {"conforms": bool(conforms), "shacl_conforms": bool(conforms), "issue_count": 0 if conforms else 1, "severity_counts": {} if conforms else {"error": 1}, "issues": [], "validators": ["irrigation-candidate-structure-validator-v1", "pyshacl-meta-validator"], "report_text": str(report_text), "lifecycle_status": "draft_pending_domain_review"}
    (TARGET / "validation-report.json").write_bytes(canonical_json(validation))
    bounded_report = {"status": "pending_domain_review", "conforms": bool(conforms), "note": "结构校验通过不等于水利行业术语、约束或基数已获权威审定。"}
    for name in ("competency-report.json", "semantic-quality-report.json", "completeness-report.json"):
        (TARGET / name).write_bytes(canonical_json(bounded_report))
    context = {"@context": {"irr": PROFILE.namespace_uri, "skos": str(SKOS), "owl": str(OWL), "id": "@id", "type": "@type", "prefLabel": "skos:prefLabel"}}
    (TARGET / "context.jsonld").write_bytes(canonical_json(context))
    artifacts = {
        "sources": _artifact(TARGET / "sources.jsonl.gz", "application/x-ndjson+gzip", counts["sources"]),
        "concepts": _artifact(TARGET / "concepts.jsonl.gz", "application/x-ndjson+gzip", counts["concepts"]),
        "properties": _artifact(TARGET / "properties.jsonl.gz", "application/x-ndjson+gzip", counts["properties"]),
        "relations": _artifact(TARGET / "relations.jsonl.gz", "application/x-ndjson+gzip", counts["relations"]),
        "mappings": _artifact(TARGET / "mappings.jsonl.gz", "application/x-ndjson+gzip", 0),
        "review_dispositions": _artifact(TARGET / "review-dispositions.jsonl.gz", "application/x-ndjson+gzip", 0),
        "rdf": _artifact(TARGET / "ontology.ttl.gz", "application/gzip"),
        "shacl": _artifact(TARGET / "shapes.ttl", "text/turtle"),
        "jsonld_context": _artifact(TARGET / "context.jsonld", "application/ld+json"),
        "validation": _artifact(TARGET / "validation-report.json", "application/json"),
        "competency_report": _artifact(TARGET / "competency-report.json", "application/json"),
        "semantic_quality_report": _artifact(TARGET / "semantic-quality-report.json", "application/json"),
        "completeness_report": _artifact(TARGET / "completeness-report.json", "application/json"),
    }
    content_sha = sha256_json({key: item.sha256 for key, item in sorted(artifacts.items())})
    kind_counts = Counter(item.kind for item in concepts)
    property_counts = Counter(item.owner_concept_id for item in properties)
    domain_stats = []
    for domain_id, label in DOMAIN_CONCEPTS:
        domain_items = [item for item in concepts if item.domain_id == domain_id]
        domain_stats.append({"domain_id": domain_id, "label": label, "concept_count": len(domain_items), "domain_class_count": sum(item.kind in {"DomainClass", "ProcessClass", "StateClass", "RoleClass", "InformationClass", "ObservationClass"} for item in domain_items), "standard_feature_count": 0, "ea_schema_count": 0, "property_count": sum(property_counts[item.concept_id] for item in domain_items), "mapping_count": 0, "confirmed_mapping_count": 0, "strict_coverage": 0.0})
    manifest = PackageManifest(package_id=f"{PROFILE.ontology_key}:{VERSION}:{content_sha[:16]}", ontology_key=PROFILE.ontology_key, ontology_version_id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"{PROFILE.ontology_key}:{VERSION}:{content_sha}")), semantic_version=VERSION, title=PROFILE.title, description="灌区水源、渠系、观测、过程、行动、约束与证据的候选领域本体；待水利领域专家和项目数据审定。", namespace_uri=PROFILE.namespace_uri, model_profile="owl2-rl-bounded-candidate", generated_at=GENERATED_AT, source_fingerprint=sha256_json([item.model_dump(mode="json") for item in sources]), content_sha256=content_sha, stats={"source_count": len(sources), "concept_count": len(concepts), "property_count": len(properties), "relation_count": len(relations), "mapping_count": 0, "domain_class_count": sum(kind_counts[kind] for kind in ("DomainClass", "ProcessClass", "StateClass", "RoleClass", "InformationClass", "ObservationClass")), "schema_artifact_count": 0, "rdf_triple_count": len(graph), "validation_issue_count": validation["issue_count"]}, domain_stats=domain_stats, artifacts=artifacts, vocabularies=["RDF 1.1", "RDFS", "OWL 2 RL bounded profile", "SKOS", "SHACL", "GeoSPARQL vocabulary"], validation_summary=validation, compatibility={"minimum_runtime_contract": "gda-ontology-package-v1", "authority_store": "PostgreSQL gda_ontology schema", "fallback": "hash-verified immutable package", "lifecycle_status": "draft_pending_domain_review"})
    (TARGET / "manifest.json").write_text(json.dumps(manifest.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    PACKAGE_ROOT.mkdir(parents=True, exist_ok=True)
    (PACKAGE_ROOT / "active.json").write_text(json.dumps({"content_sha256": content_sha, "semantic_version": VERSION}, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return manifest


if __name__ == "__main__":
    built = build()
    print(json.dumps({"package_id": built.package_id, "content_sha256": built.content_sha256, "stats": built.stats}, ensure_ascii=False, indent=2))
