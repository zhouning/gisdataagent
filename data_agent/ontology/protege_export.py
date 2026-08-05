"""Generate a review-oriented Protege bundle from a verified package."""

from __future__ import annotations

import gzip
import json
import shutil
from pathlib import Path

from rdflib import Graph, URIRef

from .compiler import CompiledOntology, build_rdf
from .contracts import (
    BASE_URI,
    ConceptRecord,
    MappingRecord,
    PropertyRecord,
    RelationRecord,
    SourceRecord,
)
from .package_reader import OntologyPackageReader

DOMAIN_CLASS_KINDS = {
    "DomainClass",
    "ProcessClass",
    "StateClass",
    "RoleClass",
    "InformationClass",
    "ObservationClass",
}

METAMODEL_SUPPORT_CLASSES = {
    URIRef(f"{BASE_URI}{name}")
    for name in (
        "CRSReference",
        "ModelPackage",
        "SchemaArtifact",
        "SchemaField",
        "SourceDocument",
        "SubjectArea",
    )
}


def _strip_metamodel_support_classes(graph: Graph) -> None:
    """Keep technical metamodel classes out of the domain-only Protege view."""
    for support_class in METAMODEL_SUPPORT_CLASSES:
        graph.remove((support_class, None, None))
        graph.remove((None, None, support_class))


def _load_records(package_dir: Path, name: str, model_type: type):
    with gzip.open(package_dir / name, "rt", encoding="utf-8") as stream:
        return [model_type.model_validate_json(line) for line in stream if line.strip()]


def export_protege_bundle(
    package_dir: str | Path,
    output_dir: str | Path,
) -> dict[str, object]:
    reader = OntologyPackageReader(package_dir, verify=True)
    package = reader.package_dir
    version = reader.manifest.semantic_version
    output = Path(output_dir).expanduser().resolve()
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"Protege export directory is not empty: {output}")
    output.mkdir(parents=True, exist_ok=True)

    concepts = _load_records(package, "concepts.jsonl.gz", ConceptRecord)
    properties = _load_records(package, "properties.jsonl.gz", PropertyRecord)
    relations = _load_records(package, "relations.jsonl.gz", RelationRecord)
    sources = _load_records(package, "sources.jsonl.gz", SourceRecord)
    mappings = _load_records(package, "mappings.jsonl.gz", MappingRecord)

    core_ids = {record.concept_id for record in concepts if record.kind in DOMAIN_CLASS_KINDS}
    core_concepts = [record for record in concepts if record.concept_id in core_ids]
    core_properties = [record for record in properties if record.owner_concept_id in core_ids]
    core_relations = [
        record
        for record in relations
        if record.source_concept_id in core_ids and record.target_concept_id in core_ids
    ]
    core_source_ids = {
        *(record.source_id for record in core_concepts),
        *(record.source_id for record in core_properties),
        *(record.source_id for record in core_relations),
    }
    core = CompiledOntology(
        sources=[record for record in sources if record.source_id in core_source_ids],
        concepts=core_concepts,
        properties=core_properties,
        relations=core_relations,
        mappings=[],
        issues=[],
    )
    core_graph, core_shapes = build_rdf(core)
    _strip_metamodel_support_classes(core_graph)
    core_path = output / f"natural-resource-domain-core-{version}.ttl"
    core_graph.serialize(destination=str(core_path), format="turtle")
    core_shapes.serialize(
        destination=str(output / f"natural-resource-domain-core-shapes-{version}.ttl"),
        format="turtle",
    )

    complete_path = output / f"natural-resource-one-map-complete-{version}.ttl"
    with gzip.open(reader.artifact_path("rdf"), "rb") as source_stream:
        with complete_path.open("wb") as target_stream:
            shutil.copyfileobj(source_stream, target_stream)
    shutil.copy2(
        reader.artifact_path("shacl"),
        output / f"natural-resource-one-map-shapes-{version}.ttl",
    )
    shutil.copy2(package / "manifest.json", output / f"manifest-{version}.json")

    summary = {
        "semantic_version": reader.manifest.semantic_version,
        "package_id": reader.manifest.package_id,
        "content_sha256": reader.manifest.content_sha256,
        "domain_class_count": len(core_ids),
        "schema_artifact_count": sum(record.kind == "SchemaArtifact" for record in concepts),
        "reference_concept_count": sum(record.kind == "ReferenceConcept" for record in concepts),
        "mapping_count": len(mappings),
        "core_rdf_triple_count": len(core_graph),
        "complete_rdf_triple_count": reader.manifest.stats.get("rdf_triple_count", 0),
    }
    (output / "export-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    readme = (
        f"# 自然资源“一张图”本体 Protege 审查包 v{version}\n\n"
        "## 建议打开顺序\n\n"
        f"1. `natural-resource-domain-core-{version}.ttl`：严格只含 96 个经策划的"
        "实体、状态、过程、角色、权利、规则和观测类。优先用它审查类层次和对象关系。\n"
        f"2. `natural-resource-one-map-complete-{version}.ttl`：完整模型，增加标准代码、"
        "标准表、EA 数据结构、字段、关联和映射。数据表与字段是个体，不会进入领域类层次。\n"
        f"3. `natural-resource-one-map-shapes-{version}.ttl`：完整 SHACL 规则；核心转换"
        f"规则也单独保存在 `natural-resource-domain-core-shapes-{version}.ttl`。\n\n"
        "## 重点检查\n\n"
        "- `土地 > 农用地 > 耕地/非耕农用地` 和 `土地 > 建设用地/未利用地` 的"
        "层次与互斥公理。\n"
        "- `土地利用状态`与`土地利用转换`是独立语义轴，不把历史状态永久写成"
        "地块身份。\n"
        "- `农业结构调整`允许耕地和非耕农用地状态双向转换。\n"
        "- `建设占用`要求农用地源状态、建设用地目标状态、法律依据和审批文件。\n"
        "- EA package、数据库表、标准表、智能问数等应用功能不属于自然资源 OWL 类。\n\n"
        "## Protege\n\n"
        "在 Protege 中选择 File > Open，打开上述 TTL 文件。使用 Entities > Classes "
        "查看领域层次，使用 Object properties 查看关系，使用 Individuals 查看完整模型"
        "中的数据结构与代码项。\n"
    )
    (output / "README.md").write_text(
        readme,
        encoding="utf-8",
    )
    return summary
