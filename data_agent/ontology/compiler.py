"""Deterministic EA + natural-resource standard ontology compiler.

The compiler reads Enterprise Architect in a read-only transaction, keeps the
standard documents and EA models as separate provenance authorities, and emits
an immutable runtime package plus RDF/SHACL projections.
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import re
import shutil
import subprocess
import tempfile
import uuid
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable, Iterator
from urllib.parse import quote

from .contracts import (
    BASE_URI,
    ONTOLOGY_KEY,
    ArtifactRecord,
    ConceptRecord,
    MappingRecord,
    MappingStatus,
    PackageManifest,
    PropertyRecord,
    RelationRecord,
    SourceRecord,
    canonical_json,
    sha256_json,
    stable_token,
)


DOMAIN_LABELS = {
    "01": "统一地理底图",
    "02": "统一调查监测",
    "03": "统一产权底板",
    "04": "统一规划",
    "05": "底线安全",
    "06": "用途管制",
    "07": "开发利用",
    "08": "执法督察",
    "09": "社会经济人口",
    "10": "元数据",
}

CORE_META_CLASSES = [
    ("Standard", "标准"),
    ("Clause", "标准条款"),
    ("Term", "术语"),
    ("DataElement", "数据元"),
    ("ValueDomain", "值域"),
    ("ValueDomainMember", "值域成员"),
    ("Dataset", "数据集"),
    ("Layer", "图层"),
    ("FeatureType", "要素类型"),
    ("Field", "字段"),
    ("CRS", "坐标参考系"),
    ("QualityRule", "质量规则"),
    ("SpatialPolicy", "空间政策规则"),
    ("Capability", "能力"),
    ("Tool", "工具"),
    ("Artifact", "产物"),
    ("Package", "模型包"),
    ("DatasetSchema", "数据集结构"),
    ("ObjectType", "对象类型"),
    ("ActionType", "行动类型"),
    ("FunctionType", "函数类型"),
    ("InterfaceType", "接口类型"),
]

OPERATIONAL_TYPES = [
    ("ObjectType", "DatasetVersion", "数据集版本"),
    ("ObjectType", "StandardVersion", "标准版本"),
    ("ObjectType", "FieldMapping", "字段映射"),
    ("ObjectType", "QualityIssue", "质量问题"),
    ("ObjectType", "RemediationPlan", "整改方案"),
    ("ObjectType", "ApprovalTask", "审批任务"),
    ("ObjectType", "GovernedDataset", "受治理数据集"),
    ("ActionType", "CompileOntology", "编译本体"),
    ("ActionType", "ValidateOntology", "校验本体"),
    ("ActionType", "PublishOntology", "发布本体"),
    ("ActionType", "AlignSchema", "对齐数据结构"),
    ("ActionType", "ValidateDataset", "校验数据集"),
    ("FunctionType", "DiscoverConcepts", "发现概念"),
    ("FunctionType", "TraverseRelations", "遍历关系"),
    ("FunctionType", "ResolveFieldMapping", "解析字段映射"),
    ("InterfaceType", "SemanticQueryGateway", "语义查询网关"),
    ("InterfaceType", "OntologyToolset", "本体智能体工具集"),
]

STANDARD_DOC_RE = re.compile(r"数据库体系结构（\s*(\d{1,2})\s*）")
CAPTION_CODE_RE = re.compile(
    r"(?:属性表名|数据表名|统计表代码|图层[（(]属性表[）)]名|图层编码|图层名|表名)"
    r"\s*[：:]\s*[（(]?\s*"
    r"([A-Za-z][A-Za-z0-9_]{1,80})",
    re.IGNORECASE,
)
DOMAIN_PATH_RE = re.compile(r"(?:^|\s/\s)(0[1-9]|10)[^/]*")
GUID_RE = re.compile(r"[{}]", re.ASCII)
STANDARD_FIELD_CODE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_ ]{0,127}$")
VALUE_MEMBER_CODE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-/]{0,63}$")


@dataclass
class EAInput:
    packages: list[dict[str, Any]]
    tables: list[dict[str, Any]]
    attributes: list[dict[str, Any]]
    connectors: list[dict[str, Any]]
    source_sha256: str
    source_metadata: dict[str, Any]


@dataclass
class StandardField:
    code: str
    label: str
    datatype: str | None
    length: int | None
    precision: int | None
    scale: int | None
    required: bool
    value_domain: str | None
    ordinal: int
    heading: str
    raw: dict[str, Any]


@dataclass
class StandardEntry:
    domain_id: str
    source_id: str
    code: str
    label: str
    geometry_type: str | None = None
    constraint: str | None = None
    heading: str = ""
    fields: list[StandardField] = field(default_factory=list)
    provenance: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class StandardValueMember:
    code: str
    label: str
    ordinal: int
    raw: dict[str, Any]


@dataclass
class StandardValueDomain:
    domain_id: str
    source_id: str
    code: str
    label: str
    heading: str
    members: list[StandardValueMember]
    provenance: dict[str, Any]


@dataclass
class StandardInput:
    sources: list[SourceRecord]
    entries: list[StandardEntry]
    value_domains: list[StandardValueDomain]
    issues: list[dict[str, Any]]


@dataclass
class CompiledOntology:
    sources: list[SourceRecord]
    concepts: list[ConceptRecord]
    properties: list[PropertyRecord]
    relations: list[RelationRecord]
    mappings: list[MappingRecord]
    issues: list[dict[str, Any]]


def _clean(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def _int_or_none(value: Any) -> int | None:
    text = _clean(value)
    if not text:
        return None
    try:
        return int(float(text))
    except (TypeError, ValueError):
        return None


def _guid_token(value: Any, fallback: str) -> str:
    token = GUID_RE.sub("", _clean(value)).lower()
    return token or fallback


def _uri(*parts: str) -> str:
    return BASE_URI + "/".join(quote(str(part).strip(), safe="-._~") for part in parts)


def _domain_from_path(path: str) -> str | None:
    match = DOMAIN_PATH_RE.search(path or "")
    return match.group(1) if match else None


def _domain_concept_id(domain_id: str) -> str:
    return f"gda:nr:domain:{domain_id}"


def _normalize_datatype(value: Any) -> tuple[str | None, list[str]]:
    raw = _clean(value)
    lowered = raw.casefold()
    flags: list[str] = []
    if not lowered:
        return None, ["missing_datatype"]
    if lowered in {"varchar2", "nvarchar2", "number"}:
        flags.append("oracle_datatype_in_postgresql_model")
    if "geometry" in lowered or lowered in {"shape", "wkt"}:
        return "geo:wktLiteral", flags
    if any(token in lowered for token in ("char", "text", "string", "clob", "uuid")):
        return "xsd:string", flags
    if any(token in lowered for token in ("timestamp", "datetime")):
        return "xsd:dateTime", flags
    if lowered == "date" or lowered.startswith("date("):
        return "xsd:date", flags
    if any(token in lowered for token in ("bool", "bit")):
        return "xsd:boolean", flags
    if any(token in lowered for token in ("double", "float", "real")):
        return "xsd:double", flags
    if any(token in lowered for token in ("decimal", "numeric", "number", "money")):
        return "xsd:decimal", flags
    if any(token in lowered for token in ("bigint", "long")):
        return "xsd:long", flags
    if any(token in lowered for token in ("int", "smallint", "short")):
        return "xsd:integer", flags
    if any(token in lowered for token in ("bytea", "blob", "binary")):
        return "xsd:base64Binary", flags
    flags.append("unmapped_datatype")
    return "xsd:string", flags


def _fingerprint_rows(*collections: Iterable[dict[str, Any]]) -> str:
    def normalize(value: Any) -> Any:
        if isinstance(value, dict):
            return {str(key): normalize(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [normalize(item) for item in value]
        if isinstance(value, (datetime, date, time)):
            return value.isoformat()
        if isinstance(value, Decimal):
            return str(value)
        if isinstance(value, bytes):
            return value.hex()
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        return str(value)

    digest = hashlib.sha256()
    for collection in collections:
        for row in collection:
            digest.update(canonical_json(normalize(row)))
            digest.update(b"\n")
    return digest.hexdigest()


def read_ea_repository(database_url: str) -> EAInput:
    """Read EA using an explicitly read-only PostgreSQL transaction."""
    from sqlalchemy import create_engine, text

    engine = create_engine(database_url, pool_size=1, max_overflow=0, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                connection.execute(text("SET TRANSACTION READ ONLY"))
                version = str(connection.execute(text("SELECT version()")) .scalar() or "")
                packages = [dict(row._mapping) for row in connection.execute(text(
                    "SELECT package_id, parent_id, name, ea_guid, notes, createddate, modifieddate "
                    "FROM t_package ORDER BY package_id"
                ))]
                tables = [dict(row._mapping) for row in connection.execute(text(
                    "SELECT object_id, package_id, name, alias, note, author, version, gentype, "
                    "status, stereotype, ea_guid, createddate, modifieddate "
                    "FROM t_object WHERE lower(coalesce(stereotype, '')) = 'table' "
                    "ORDER BY object_id"
                ))]
                attributes = [dict(row._mapping) for row in connection.execute(text(
                    "SELECT a.object_id, a.id AS attribute_id, a.name AS attribute_name, "
                    "a.type AS attribute_type, a.length, a.precision, a.scale, "
                    "a.\"Default\" AS default_value, "
                    "a.stereotype, a.notes, a.style, a.pos, a.ea_guid, "
                    "o.name AS table_name, o.alias AS table_alias "
                    "FROM t_attribute a JOIN t_object o ON o.object_id = a.object_id "
                    "WHERE lower(coalesce(o.stereotype, '')) = 'table' "
                    "ORDER BY a.object_id, a.pos, a.id"
                ))]
                connectors = [dict(row._mapping) for row in connection.execute(text(
                    "SELECT connector_id, start_object_id, end_object_id, connector_type, "
                    "name, stereotype, direction, sourcecard, destcard, ea_guid, notes "
                    "FROM t_connector ORDER BY connector_id"
                ))]
                transaction.rollback()
            except Exception:
                transaction.rollback()
                raise
        source_sha = _fingerprint_rows(packages, tables, attributes, connectors)
        return EAInput(
            packages=packages,
            tables=tables,
            attributes=attributes,
            connectors=connectors,
            source_sha256=source_sha,
            source_metadata={
                "database_product": "PostgreSQL",
                "server_version": version.splitlines()[0][:300],
                "read_mode": "transaction_read_only",
                "package_count": len(packages),
                "table_model_count": len(tables),
                "attribute_count": len(attributes),
                "connector_count": len(connectors),
            },
        )
    finally:
        engine.dispose()


def read_ea_csv_exports(export_dir: str | Path) -> EAInput:
    """Read a controlled EA export when direct repository access is unavailable."""
    base = Path(export_dir)

    def rows(name: str) -> list[dict[str, Any]]:
        path = base / name
        if not path.is_file():
            return []
        with path.open(encoding="utf-8-sig", newline="") as stream:
            return list(csv.DictReader(stream))

    raw_packages = rows("packages.csv")
    raw_tables = rows("table_models.csv")
    raw_attributes = rows("table_attributes.csv")
    packages = [{
        **row,
        "package_id": _int_or_none(row.get("package_id")),
        "parent_id": _int_or_none(row.get("parent_id")),
    } for row in raw_packages]
    path_to_package = {row.get("package_path"): row.get("package_id") for row in packages}
    tables = [{
        **row,
        "object_id": _int_or_none(row.get("object_id")),
        "package_id": path_to_package.get(row.get("package_path")),
        "ea_guid": None,
    } for row in raw_tables]
    attributes = [{
        **row,
        "attribute_id": _int_or_none(row.get("attribute_id")),
        "attribute_name": row.get("attribute_name"),
        "attribute_type": row.get("attribute_type"),
        "pos": _int_or_none(row.get("attribute_position")),
        "ea_guid": None,
    } for row in raw_attributes]
    return EAInput(
        packages=packages,
        tables=tables,
        attributes=attributes,
        connectors=[],
        source_sha256=_fingerprint_rows(packages, tables, attributes),
        source_metadata={
            "read_mode": "controlled_csv_export",
            "export_dir": str(base),
            "package_count": len(packages),
            "table_model_count": len(tables),
            "attribute_count": len(attributes),
            "connector_count": 0,
            "limitations": ["ea_guid_unavailable", "connectors_unavailable"],
        },
    )


def _iter_doc_blocks(document: Any) -> Iterator[tuple[str, Any]]:
    from docx.table import Table
    from docx.text.paragraph import Paragraph
    from docx.oxml.table import CT_Tbl
    from docx.oxml.text.paragraph import CT_P

    for child in document.element.body.iterchildren():
        if isinstance(child, CT_P):
            yield "paragraph", Paragraph(child, document)
        elif isinstance(child, CT_Tbl):
            yield "table", Table(child, document)


def _table_dicts(table: Any) -> tuple[list[str], list[dict[str, str]]]:
    if not table.rows:
        return [], []
    matrix = [[_clean(cell.text) for cell in row.cells] for row in table.rows]
    header_index = 0
    for index, values in enumerate(matrix[:4]):
        joined = "|".join(values)
        if any(token in joined for token in ("字段代码", "属性表名", "数据表名", "统计表", "图层名", "表名")):
            header_index = index
            break
    headers: list[str] = []
    seen: Counter[str] = Counter()
    for index, value in enumerate(matrix[header_index]):
        header = value or f"column_{index + 1}"
        seen[header] += 1
        if seen[header] > 1:
            header = f"{header}_{seen[header]}"
        headers.append(header)
    rows = []
    for values in matrix[header_index + 1:]:
        if not any(values):
            continue
        rows.append({header: values[index] if index < len(values) else "" for index, header in enumerate(headers)})
    return headers, rows


def _first_column(headers: list[str], candidates: tuple[str, ...]) -> str | None:
    normalized = {re.sub(r"\s+", "", header): header for header in headers}
    for candidate in candidates:
        if candidate in normalized:
            return normalized[candidate]
    for compact, original in normalized.items():
        if any(candidate in compact for candidate in candidates):
            return original
    return None


def _exact_column(headers: list[str], candidates: tuple[str, ...]) -> str | None:
    """Return only an explicitly named column, ignoring whitespace differences."""
    normalized = {re.sub(r"\s+", "", header): header for header in headers}
    for candidate in candidates:
        original = normalized.get(re.sub(r"\s+", "", candidate))
        if original:
            return original
    return None


def _extract_code(text: str) -> str | None:
    match = CAPTION_CODE_RE.search(text)
    return match.group(1).strip() if match else None


def _parse_standard_document(
    data: bytes,
    filename: str,
    domain_id: str,
) -> tuple[list[StandardEntry], list[StandardValueDomain], list[dict[str, Any]]]:
    from docx import Document

    document = Document(io.BytesIO(data))
    entries: dict[str, StandardEntry] = {}
    value_domains: dict[str, StandardValueDomain] = {}
    issues: list[dict[str, Any]] = []
    context: list[str] = []
    heading = ""
    last_target_code: str | None = None

    def ensure_entry(code: str, label: str = "", **values: Any) -> StandardEntry:
        key = code.casefold()
        existing = entries.get(key)
        if existing is None:
            existing = StandardEntry(
                domain_id=domain_id,
                source_id=f"std-doc-{domain_id}",
                code=code,
                label=label or code,
                geometry_type=values.get("geometry_type"),
                constraint=values.get("constraint"),
                heading=heading,
            )
            entries[key] = existing
        else:
            if label and existing.label == existing.code:
                existing.label = label
            if values.get("geometry_type") and not existing.geometry_type:
                existing.geometry_type = values["geometry_type"]
            if values.get("constraint") and not existing.constraint:
                existing.constraint = values["constraint"]
        existing.provenance.append({"filename": filename, "heading": heading})
        return existing

    for block_kind, block in _iter_doc_blocks(document):
        if block_kind == "paragraph":
            text = _clean(block.text)
            if not text:
                continue
            style_name = _clean(getattr(block.style, "name", ""))
            if style_name.casefold().startswith("heading") or re.match(r"^\d+(?:\.\d+)*\s+", text):
                heading = text
            context.append(text)
            context = context[-8:]
            caption_code = _extract_code(text)
            if caption_code:
                last_target_code = caption_code
                label = re.sub(r"^表\s*[\d.\-—]*\s*", "", text)
                label = re.split(r"[（(](?:属性表名|数据表名|统计表名|图层名|表名)", label)[0].strip()
                ensure_entry(caption_code, label)
            continue

        headers, rows = _table_dicts(block)
        if not headers or not rows:
            continue
        field_code_col = _first_column(headers, ("字段代码", "属性代码", "字段名", "属性项"))
        field_label_col = _first_column(headers, ("字段名称", "属性名称", "中文名称"))
        if field_code_col and field_label_col:
            context_code = next((_extract_code(text) for text in reversed(context) if _extract_code(text)), None)
            target_code = context_code or last_target_code
            if not target_code:
                issues.append({
                    "severity": "warning",
                    "code": "standard_field_table_without_owner",
                    "source": filename,
                    "heading": heading,
                    "headers": headers,
                })
                continue
            entry = ensure_entry(target_code)
            datatype_col = _first_column(headers, ("字段类型", "数据类型", "类型"))
            length_col = _first_column(headers, ("字段长度", "长度"))
            scale_col = _first_column(headers, ("小数位数", "小数位"))
            domain_col = _first_column(headers, ("值域", "取值范围"))
            constraint_col = _first_column(headers, ("约束条件", "约束"))
            ordinal_col = _first_column(headers, ("序号",))
            existing_signatures = {(item.code.casefold(), item.ordinal) for item in entry.fields}
            for row_index, row in enumerate(rows, 1):
                code = _clean(row.get(field_code_col))
                label = _clean(row.get(field_label_col))
                if not code or code in {"-", "/"}:
                    continue
                if not STANDARD_FIELD_CODE_RE.fullmatch(code):
                    issues.append({
                        "severity": "warning",
                        "code": "invalid_standard_field_code_row_excluded",
                        "source": filename,
                        "heading": heading,
                        "owner_code": target_code,
                        "raw_code": code[:500],
                    })
                    continue
                ordinal = _int_or_none(row.get(ordinal_col)) if ordinal_col else row_index
                ordinal = ordinal or row_index
                signature = (code.casefold(), ordinal)
                if signature in existing_signatures:
                    continue
                existing_signatures.add(signature)
                raw_datatype = _clean(row.get(datatype_col)) if datatype_col else ""
                normalized_datatype, _ = _normalize_datatype(raw_datatype)
                constraint = _clean(row.get(constraint_col)).upper() if constraint_col else ""
                entry.fields.append(StandardField(
                    code=code,
                    label=label or code,
                    datatype=normalized_datatype,
                    length=_int_or_none(row.get(length_col)) if length_col else None,
                    precision=None,
                    scale=_int_or_none(row.get(scale_col)) if scale_col else None,
                    required=constraint in {"M", "必选", "必填", "是", "Y"},
                    value_domain=_clean(row.get(domain_col)) or None if domain_col else None,
                    ordinal=ordinal,
                    heading=heading,
                    raw=row,
                ))
            continue

        code_col = _exact_column(headers, (
            "属性表名", "数据表名", "统计表代码", "图层（属性表）名",
            "图层(属性表)名", "图层编码", "图层名", "表名",
        ))
        generic_code_col = _exact_column(headers, ("代码", "编码"))
        classification_context = " ".join([heading, *context[-4:]])
        if not code_col and generic_code_col and "分类" in classification_context:
            member_label_col = _first_column(headers, (
                "数据内容", "分类名称", "类别名称", "要素名称", "名称", "类别", "图层", "要素",
            ))
            members: list[StandardValueMember] = []
            members_by_code: dict[str, list[StandardValueMember]] = defaultdict(list)
            for row_index, row in enumerate(rows, 1):
                member_code = _clean(row.get(generic_code_col))
                if not member_code or member_code in {"-", "/"}:
                    continue
                if not VALUE_MEMBER_CODE_RE.fullmatch(member_code):
                    issues.append({
                        "severity": "warning",
                        "code": "value_domain_annotation_row_excluded",
                        "source": filename,
                        "heading": heading,
                        "raw_code": member_code[:500],
                    })
                    continue
                member_label = _clean(row.get(member_label_col)) if member_label_col else ""
                if not member_label:
                    member_label = next(
                        (_clean(row.get(header)) for header in reversed(headers)
                         if header != generic_code_col and _clean(row.get(header))),
                        member_code,
                    )
                code_key = member_code.casefold()
                previous = members_by_code.get(code_key, [])[-1] if members_by_code.get(code_key) else None
                same_source_ordinal = bool(
                    previous
                    and _clean(previous.raw.get("序号"))
                    and _clean(previous.raw.get("序号")) == _clean(row.get("序号"))
                    and previous.ordinal == row_index - 1
                )
                if previous and same_source_ordinal:
                    previous.label = f"{previous.label}{member_label}"
                    if member_label_col:
                        previous.raw[member_label_col] = previous.label
                    continue
                member = StandardValueMember(
                    code=member_code,
                    label=member_label,
                    ordinal=row_index,
                    raw=row,
                )
                if previous:
                    issues.append({
                        "severity": "warning",
                        "code": "duplicate_value_domain_member_code",
                        "source": filename,
                        "heading": heading,
                        "member_code": member_code,
                        "labels": [previous.label, member.label],
                    })
                members.append(member)
                members_by_code[code_key].append(member)
            if members:
                caption = next(
                    (text for text in reversed(context)
                     if text.startswith("表") or "代码表" in text or "字典表" in text),
                    heading,
                )
                label = re.sub(
                    r"^(?:(?:代码表|表)\s*)?[A-Za-z]?[.．]?\s*\d+(?:[.\-—]\d+)*\s*",
                    "",
                    caption,
                ).strip()
                label = re.sub(r"^表\s*", "", label).strip()
                if not label or label == heading:
                    label_header = next(
                        (header for header in headers if header != generic_code_col),
                        "分类",
                    )
                    label = f"{label_header}代码表"
                member_signature = [
                    (member.code.casefold(), member.label)
                    for member in members
                ]
                domain_token = stable_token(
                    domain_id,
                    label.casefold(),
                    member_signature,
                    length=12,
                )
                occurrence = {
                    "filename": filename,
                    "heading": heading,
                    "caption": caption,
                    "headers": headers,
                }
                existing_value_domain = value_domains.get(domain_token)
                if existing_value_domain:
                    existing_value_domain.provenance.setdefault("occurrences", []).append(occurrence)
                    continue
                value_domains[domain_token] = StandardValueDomain(
                    domain_id=domain_id,
                    source_id=f"std-doc-{domain_id}",
                    code=f"VD-{domain_id}-{domain_token.upper()}",
                    label=label,
                    heading=heading,
                    members=members,
                    provenance={
                        "occurrences": [occurrence],
                    },
                )
                continue
        if not code_col:
            continue
        label_col = _first_column(headers, (
            "层要素", "属性表中文名称", "数据表中文名称", "统计表名称", "表中文名称",
            "数据内容", "要素名称", "中文名称", "图层", "名称",
        ))
        geometry_col = _first_column(headers, ("几何特征", "几何类型", "空间类型"))
        constraint_col = _first_column(headers, ("约束条件", "约束"))
        for row in rows:
            raw_code = _clean(row.get(code_col))
            candidates = re.findall(r"[A-Za-z][A-Za-z0-9_]{1,80}", raw_code)
            if not candidates:
                continue
            label = _clean(row.get(label_col)) if label_col else ""
            for code in candidates:
                ensure_entry(
                    code,
                    label,
                    geometry_type=_clean(row.get(geometry_col)) or None if geometry_col else None,
                    constraint=_clean(row.get(constraint_col)) or None if constraint_col else None,
                )
                last_target_code = code

    for entry in entries.values():
        entry.fields.sort(key=lambda item: (item.ordinal, item.code.casefold()))
    return (
        sorted(entries.values(), key=lambda item: item.code.casefold()),
        sorted(value_domains.values(), key=lambda item: item.code),
        issues,
    )


def _convert_legacy_doc(data: bytes, filename: str) -> bytes:
    """Convert a legacy Word binary with an isolated LibreOffice profile."""
    import os

    converter = (
        os.environ.get("LIBREOFFICE_BIN")
        or shutil.which("soffice")
        or shutil.which("libreoffice")
    )
    if not converter:
        raise RuntimeError(
            f"legacy standard document requires LibreOffice conversion: {filename}"
        )
    with tempfile.TemporaryDirectory(prefix="gda-ontology-doc-") as temp_dir:
        base = Path(temp_dir)
        input_path = base / Path(filename).name
        input_path.write_bytes(data)
        profile_uri = (base / "lo-profile").resolve().as_uri()
        result = subprocess.run(
            [
                converter,
                "--headless",
                f"-env:UserInstallation={profile_uri}",
                "--convert-to",
                "docx",
                "--outdir",
                str(base),
                str(input_path),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=180,
        )
        output_path = base / f"{input_path.stem}.docx"
        if result.returncode != 0 or not output_path.is_file():
            detail = (result.stderr or result.stdout or "conversion produced no DOCX")[:1000]
            raise RuntimeError(f"LibreOffice conversion failed for {filename}: {detail}")
        return output_path.read_bytes()


def read_standard_zip(
    zip_path: str | Path,
    *,
    legacy_docx_dir: str | Path | None = None,
) -> StandardInput:
    path = Path(zip_path)
    sources: list[SourceRecord] = []
    entries: list[StandardEntry] = []
    value_domains: list[StandardValueDomain] = []
    issues: list[dict[str, Any]] = []
    selected: dict[str, tuple[str, bytes, bytes, str | None]] = {}
    legacy: dict[str, tuple[str, bytes]] = {}
    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            normalized_name = info.filename.replace("\\", "/")
            basename = Path(normalized_name).name
            match = STANDARD_DOC_RE.search(basename)
            if not match or basename.startswith("~$"):
                continue
            domain_number = int(match.group(1))
            if not 0 <= domain_number <= 10:
                continue
            domain_id = f"{domain_number:02d}"
            lowered = basename.casefold()
            if lowered.endswith(".docx"):
                data = archive.read(info)
                current = selected.get(domain_id)
                if current is None or len(data) > len(current[1]):
                    selected[domain_id] = (normalized_name, data, data, None)
            elif lowered.endswith(".doc"):
                legacy[domain_id] = (normalized_name, archive.read(info))

    for domain_id, (filename, source_data) in legacy.items():
        if domain_id in selected:
            continue
        converted: bytes | None = None
        if legacy_docx_dir:
            supplement_dir = Path(legacy_docx_dir)
            expected_name = f"{Path(filename).stem}.docx"
            supplement = supplement_dir / expected_name
            if supplement.is_file():
                converted = supplement.read_bytes()
        if converted is None:
            converted = _convert_legacy_doc(source_data, filename)
        selected[domain_id] = (filename, converted, source_data, "libreoffice-doc-to-docx")

    container_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    for domain_id in sorted(selected):
        filename, parse_data, source_data, conversion = selected[domain_id]
        source_id = f"std-doc-{domain_id}"
        title = Path(filename).stem
        sources.append(SourceRecord(
            source_id=source_id,
            source_kind="standard_document",
            title=title,
            locator=f"zip:{path.name}!/{filename}",
            source_version="2025-draft",
            sha256=hashlib.sha256(source_data).hexdigest(),
            metadata={
                "volume": int(domain_id),
                "domain_label": DOMAIN_LABELS.get(domain_id, "绪论" if domain_id == "00" else ""),
                "container_sha256": container_sha256,
                "publication_status": "draft_or_unconfirmed",
                "parse_derivation": conversion,
                "parse_derivation_sha256": (
                    hashlib.sha256(parse_data).hexdigest() if conversion else None
                ),
            },
        ))
        parsed, parsed_value_domains, parsed_issues = _parse_standard_document(
            parse_data, filename, domain_id
        )
        entries.extend(parsed)
        value_domains.extend(parsed_value_domains)
        issues.extend(parsed_issues)

    missing = [f"{number:02d}" for number in range(0, 11) if f"{number:02d}" not in selected]
    if missing:
        issues.append({"severity": "error", "code": "missing_standard_volumes", "volumes": missing})
    return StandardInput(
        sources=sources,
        entries=entries,
        value_domains=value_domains,
        issues=issues,
    )


def _package_paths(packages: list[dict[str, Any]]) -> dict[int, str]:
    by_id = {int(row["package_id"]): row for row in packages if row.get("package_id") is not None}
    cache: dict[int, str] = {}

    def resolve(package_id: int, stack: set[int] | None = None) -> str:
        if package_id in cache:
            return cache[package_id]
        stack = set(stack or ())
        if package_id in stack:
            return _clean(by_id.get(package_id, {}).get("name"))
        stack.add(package_id)
        row = by_id.get(package_id) or {}
        name = _clean(row.get("name")) or str(package_id)
        parent_id = _int_or_none(row.get("parent_id")) or 0
        if parent_id and parent_id in by_id:
            path = f"{resolve(parent_id, stack)} / {name}"
        else:
            path = name
        cache[package_id] = path
        return path

    for package_id in by_id:
        resolve(package_id)
    return cache


def compile_ontology(ea: EAInput, standards: StandardInput) -> CompiledOntology:
    sources = list(standards.sources)
    sources.append(SourceRecord(
        source_id="ea-repository",
        source_kind="ea_repository",
        title="Enterprise Architect PostgreSQL Repository",
        locator="controlled:ea-repository",
        source_version=None,
        sha256=ea.source_sha256,
        metadata=ea.source_metadata,
    ))
    core_source_sha = sha256_json({"meta": CORE_META_CLASSES, "operational": OPERATIONAL_TYPES})
    sources.append(SourceRecord(
        source_id="gda-core-vocabulary",
        source_kind="controlled_vocabulary",
        title="GIS Data Agent Ontology Core Vocabulary",
        locator="package:data_agent.ontology.compiler",
        source_version="1.0.0",
        sha256=core_source_sha,
        metadata={"authority": "ADR-139", "review_status": "accepted"},
    ))

    concepts: list[ConceptRecord] = []
    properties: list[PropertyRecord] = []
    relations: list[RelationRecord] = []
    mappings: list[MappingRecord] = []
    issues = list(standards.issues)
    concept_ids: set[str] = set()
    concept_uris: dict[str, str] = {}
    property_ids: set[str] = set()
    property_uris: dict[str, str] = {}
    relation_ids: set[str] = set()

    def add_concept(record: ConceptRecord) -> None:
        if record.concept_id in concept_ids:
            issues.append({"severity": "error", "code": "duplicate_concept_id", "concept_id": record.concept_id})
            return
        if record.uri in concept_uris:
            issues.append({
                "severity": "error",
                "code": "duplicate_concept_uri",
                "uri": record.uri,
                "concept_ids": [concept_uris[record.uri], record.concept_id],
            })
            return
        if len(record.uri.encode("utf-8")) > 2000:
            issues.append({
                "severity": "error",
                "code": "concept_uri_exceeds_authority_limit",
                "concept_id": record.concept_id,
                "uri_bytes": len(record.uri.encode("utf-8")),
            })
            return
        concept_ids.add(record.concept_id)
        concept_uris[record.uri] = record.concept_id
        concepts.append(record)

    def add_property(record: PropertyRecord) -> None:
        if record.property_id in property_ids:
            issues.append({"severity": "error", "code": "duplicate_property_id", "property_id": record.property_id})
            return
        if record.uri in property_uris:
            issues.append({
                "severity": "error",
                "code": "duplicate_property_uri",
                "uri": record.uri,
                "property_ids": [property_uris[record.uri], record.property_id],
            })
            return
        if len(record.uri.encode("utf-8")) > 2000:
            issues.append({
                "severity": "error",
                "code": "property_uri_exceeds_authority_limit",
                "property_id": record.property_id,
                "uri_bytes": len(record.uri.encode("utf-8")),
            })
            return
        property_ids.add(record.property_id)
        property_uris[record.uri] = record.property_id
        properties.append(record)

    def add_relation(record: RelationRecord) -> None:
        if record.relation_id in relation_ids:
            return
        relation_ids.add(record.relation_id)
        relations.append(record)

    for code, label in CORE_META_CLASSES:
        concept_id = f"gda:nr:meta:{code}"
        add_concept(ConceptRecord(
            concept_id=concept_id,
            uri=_uri("meta", code),
            kind="MetaClass",
            code=code,
            pref_label=label,
            alt_labels=[code],
            definition=f"GIS Data Agent 受治理本体元类：{label}",
            source_system="gda_core",
            source_id="gda-core-vocabulary",
            provenance={"decision": "ADR-139"},
        ))

    for domain_id, label in DOMAIN_LABELS.items():
        add_concept(ConceptRecord(
            concept_id=_domain_concept_id(domain_id),
            uri=_uri("domain", domain_id),
            kind="Domain",
            code=domain_id,
            pref_label=label,
            alt_labels=[],
            definition=f"自然资源“一张图”第 {int(domain_id)} 分册领域",
            domain_id=domain_id,
            source_system="standard",
            source_id=f"std-doc-{domain_id}" if any(source.source_id == f"std-doc-{domain_id}" for source in sources) else "gda-core-vocabulary",
            provenance={"domain_number": int(domain_id)},
        ))

    crs_id = "gda:nr:crs:cgcs2000"
    add_concept(ConceptRecord(
        concept_id=crs_id,
        uri="http://www.opengis.net/def/crs/EPSG/0/4490",
        kind="CRS",
        code="EPSG:4490",
        pref_label="2000国家大地坐标系",
        alt_labels=["CGCS2000"],
        definition="自然资源“一张图”标准规定的平面坐标系统；具体投影分带需由数据产品合同声明。",
        source_system="standard",
        source_id="std-doc-00" if any(source.source_id == "std-doc-00" for source in sources) else "gda-core-vocabulary",
        provenance={"scope": "horizontal_crs", "projection_zone": "must_be_declared_by_dataset"},
    ))
    for domain_id in DOMAIN_LABELS:
        add_relation(RelationRecord(
            relation_id=f"gda:nr:relation:domain-crs:{domain_id}",
            relation_type="usesCRS",
            source_concept_id=_domain_concept_id(domain_id),
            target_concept_id=crs_id,
            pref_label="采用坐标参考系",
            source_id="gda-core-vocabulary",
            provenance={"constraint_scope": "standard_default"},
        ))

    for kind, code, label in OPERATIONAL_TYPES:
        concept_id = f"gda:nr:operational:{kind.casefold()}:{code}"
        add_concept(ConceptRecord(
            concept_id=concept_id,
            uri=_uri("operational", kind, code),
            kind=kind,
            code=code,
            pref_label=label,
            alt_labels=[code],
            definition=f"Cognitive Runtime Operational Ontology {kind}: {label}",
            source_system="gda_core",
            source_id="gda-core-vocabulary",
            provenance={"decision": "ADR-139", "runtime_contract": True},
        ))

    source_by_domain = {source.source_id.removeprefix("std-doc-"): source for source in standards.sources}
    for domain_id, source in sorted(source_by_domain.items()):
        if domain_id == "00":
            continue
        concept_id = f"gda:nr:standard-document:{domain_id}"
        add_concept(ConceptRecord(
            concept_id=concept_id,
            uri=_uri("standard", "document", domain_id),
            kind="StandardDocument",
            code=f"NR-ONE-MAP-{domain_id}",
            pref_label=source.title,
            alt_labels=[DOMAIN_LABELS.get(domain_id, "")],
            definition="自然资源“一张图”数据库体系结构来源分册",
            domain_id=domain_id if domain_id in DOMAIN_LABELS else None,
            source_system="standard",
            source_id=source.source_id,
            lifecycle_status="candidate",
            provenance={"source_sha256": source.sha256, "publication_status": "draft_or_unconfirmed"},
        ))
        if domain_id in DOMAIN_LABELS:
            add_relation(RelationRecord(
                relation_id=f"gda:nr:relation:domain-document:{domain_id}",
                relation_type="governedBy",
                source_concept_id=_domain_concept_id(domain_id),
                target_concept_id=concept_id,
                pref_label="由分册定义",
                source_id=source.source_id,
            ))

    package_paths = _package_paths(ea.packages)
    package_concept_by_id: dict[int, str] = {}
    for row in ea.packages:
        package_id = _int_or_none(row.get("package_id"))
        if package_id is None:
            continue
        guid = _guid_token(row.get("ea_guid"), f"object-{package_id}")
        concept_id = f"gda:nr:ea:package:{guid}"
        package_concept_by_id[package_id] = concept_id
        path = package_paths.get(package_id, _clean(row.get("package_path")))
        add_concept(ConceptRecord(
            concept_id=concept_id,
            uri=_uri("ea", "package", guid),
            kind="Package",
            code=str(package_id),
            pref_label=_clean(row.get("name")) or f"Package {package_id}",
            definition=_clean(row.get("notes")),
            domain_id=_domain_from_path(path),
            source_system="enterprise_architect",
            source_id="ea-repository",
            source_object_id=str(package_id),
            ea_guid=_clean(row.get("ea_guid")) or None,
            package_path=path,
            provenance={"ea_object_type": "Package"},
        ))
    for row in ea.packages:
        package_id = _int_or_none(row.get("package_id"))
        parent_id = _int_or_none(row.get("parent_id"))
        if package_id in package_concept_by_id and parent_id in package_concept_by_id:
            add_relation(RelationRecord(
                relation_id=f"gda:nr:ea:relation:package-parent:{package_id}",
                relation_type="broaderThan",
                source_concept_id=package_concept_by_id[parent_id],
                target_concept_id=package_concept_by_id[package_id],
                pref_label="包含子包",
                transitive=True,
                source_id="ea-repository",
                source_object_id=str(package_id),
            ))

    attributes_by_object: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in ea.attributes:
        object_id = _int_or_none(row.get("object_id"))
        if object_id is not None:
            attributes_by_object[object_id].append(row)

    ea_concept_by_object: dict[int, str] = {}
    ea_rows_by_code: dict[str, list[tuple[dict[str, Any], str]]] = defaultdict(list)
    ea_rows_by_alias: dict[str, list[tuple[dict[str, Any], str]]] = defaultdict(list)
    for row in ea.tables:
        object_id = _int_or_none(row.get("object_id"))
        if object_id is None:
            continue
        guid = _guid_token(row.get("ea_guid"), f"object-{object_id}")
        concept_id = f"gda:nr:ea:table:{guid}"
        ea_concept_by_object[object_id] = concept_id
        package_id = _int_or_none(row.get("package_id"))
        path = package_paths.get(package_id or -1, _clean(row.get("package_path")))
        attrs = attributes_by_object.get(object_id, [])
        geometry_attr = next((attr for attr in attrs if "geometry" in _clean(attr.get("attribute_type")).casefold()), None)
        name = _clean(row.get("name")) or f"EA_Table_{object_id}"
        alias = _clean(row.get("alias"))
        add_concept(ConceptRecord(
            concept_id=concept_id,
            uri=_uri("ea", "table", guid),
            kind="DatasetSchema",
            code=name,
            pref_label=alias or name,
            alt_labels=[value for value in [name, alias] if value and value != (alias or name)],
            definition=_clean(row.get("note")),
            domain_id=_domain_from_path(path),
            source_system="enterprise_architect",
            source_id="ea-repository",
            source_object_id=str(object_id),
            ea_guid=_clean(row.get("ea_guid")) or None,
            package_path=path,
            geometry_type="Geometry" if geometry_attr else None,
            lifecycle_status="candidate" if _clean(row.get("status")).casefold() == "proposed" else "active",
            provenance={
                "ea_object_type": "Class",
                "ea_stereotype": "table",
                "author": _clean(row.get("author")) or None,
                "model_version": _clean(row.get("version")) or None,
                "generation_target": _clean(row.get("gentype")) or None,
                "created_at": _clean(row.get("createddate")) or None,
                "modified_at": _clean(row.get("modifieddate")) or None,
            },
        ))
        ea_rows_by_code[name.casefold()].append((row, concept_id))
        if alias:
            ea_rows_by_alias[alias].append((row, concept_id))
        if package_id in package_concept_by_id:
            add_relation(RelationRecord(
                relation_id=f"gda:nr:ea:relation:package-table:{object_id}",
                relation_type="contains",
                source_concept_id=package_concept_by_id[package_id],
                target_concept_id=concept_id,
                pref_label="包含数据结构",
                source_id="ea-repository",
                source_object_id=str(object_id),
            ))
        for attr_index, attr in enumerate(attrs):
            attribute_id = _int_or_none(attr.get("attribute_id")) or attr_index + 1
            attr_guid = _guid_token(attr.get("ea_guid"), f"attribute-{object_id}-{attribute_id}")
            raw_type = _clean(attr.get("attribute_type"))
            datatype, flags = _normalize_datatype(raw_type)
            for flag in flags:
                issues.append({
                    "severity": "warning",
                    "code": flag,
                    "ea_object_id": object_id,
                    "ea_attribute_id": attribute_id,
                    "table": name,
                    "field": _clean(attr.get("attribute_name")),
                    "raw_datatype": raw_type,
                })
            add_property(PropertyRecord(
                property_id=f"gda:nr:ea:property:{attr_guid}",
                owner_concept_id=concept_id,
                uri=_uri("ea", "property", attr_guid),
                code=_clean(attr.get("attribute_name")) or f"field_{attribute_id}",
                pref_label=_clean(attr.get("attribute_alias")) or _clean(attr.get("attribute_name")) or f"Field {attribute_id}",
                datatype=datatype,
                length=_int_or_none(attr.get("length")),
                precision_value=_int_or_none(attr.get("precision")),
                scale_value=_int_or_none(attr.get("scale")),
                ordinal=_int_or_none(attr.get("pos")) or _int_or_none(attr.get("attribute_position")) or attr_index,
                default_value=_clean(attr.get("default")) or _clean(attr.get("default_value")) or None,
                source_id="ea-repository",
                source_object_id=str(attribute_id),
                ea_guid=_clean(attr.get("ea_guid")) or None,
                provenance={
                    "ea_object_id": object_id,
                    "raw_datatype": raw_type or None,
                    "stereotype": _clean(attr.get("stereotype")) or None,
                    "notes": _clean(attr.get("notes")) or None,
                    "quality_flags": flags,
                },
            ))

    connector_type_map = {
        "foreignkey": "foreignKeyTo",
        "association": "associatedWith",
        "generalization": "subClassOf",
        "aggregation": "aggregates",
        "dependency": "dependsOn",
        "realisation": "implements",
        "realization": "implements",
    }
    broken_connectors = 0
    for row in ea.connectors:
        start_id = _int_or_none(row.get("start_object_id"))
        end_id = _int_or_none(row.get("end_object_id"))
        if start_id not in ea_concept_by_object or end_id not in ea_concept_by_object:
            if not start_id or not end_id:
                broken_connectors += 1
            continue
        connector_id = _int_or_none(row.get("connector_id")) or 0
        connector_type = _clean(row.get("connector_type"))
        relation_type = connector_type_map.get(connector_type.casefold(), "relatedTo")
        add_relation(RelationRecord(
            relation_id=f"gda:nr:ea:relation:connector:{connector_id}",
            relation_type=relation_type,
            source_concept_id=ea_concept_by_object[start_id],
            target_concept_id=ea_concept_by_object[end_id],
            pref_label=_clean(row.get("name")) or connector_type,
            direction="bidirectional" if _clean(row.get("direction")).casefold() == "bi-directional" else "directed",
            symmetric=relation_type in {"associatedWith", "relatedTo"},
            source_id="ea-repository",
            source_object_id=str(connector_id),
            ea_guid=_clean(row.get("ea_guid")) or None,
            provenance={
                "ea_connector_type": connector_type,
                "stereotype": _clean(row.get("stereotype")) or None,
                "source_cardinality": _clean(row.get("sourcecard")) or None,
                "target_cardinality": _clean(row.get("destcard")) or None,
                "notes": _clean(row.get("notes")) or None,
            },
        ))
    if broken_connectors:
        issues.append({"severity": "warning", "code": "broken_ea_connector_endpoints", "count": broken_connectors})

    standard_concept_by_key: dict[tuple[str, str], str] = {}
    standard_document_ids = {domain_id: f"gda:nr:standard-document:{domain_id}" for domain_id in DOMAIN_LABELS}
    for value_domain in standards.value_domains:
        if value_domain.domain_id == "00":
            continue
        value_domain_token = stable_token(
            value_domain.domain_id,
            value_domain.code.casefold(),
        )
        value_domain_id = (
            f"gda:nr:standard:value-domain:{value_domain.domain_id}:{value_domain_token}"
        )
        add_concept(ConceptRecord(
            concept_id=value_domain_id,
            uri=_uri(
                "standard", value_domain.domain_id, "value-domain", value_domain.code
            ),
            kind="ValueDomain",
            code=value_domain.code,
            pref_label=value_domain.label,
            alt_labels=[],
            definition=f"{value_domain.heading}中定义的标准分类代码集。",
            domain_id=value_domain.domain_id,
            source_system="standard",
            source_id=value_domain.source_id,
            source_object_id=value_domain.code,
            lifecycle_status="candidate",
            provenance={
                **value_domain.provenance,
                "member_count": len(value_domain.members),
                "publication_status": "draft_or_unconfirmed",
            },
        ))
        add_relation(RelationRecord(
            relation_id=f"gda:nr:standard:relation:domain-value-domain:{value_domain_token}",
            relation_type="contains",
            source_concept_id=_domain_concept_id(value_domain.domain_id),
            target_concept_id=value_domain_id,
            pref_label="包含标准值域",
            source_id=value_domain.source_id,
            source_object_id=value_domain.code,
        ))
        document_id = standard_document_ids.get(value_domain.domain_id)
        if document_id and document_id in concept_ids:
            add_relation(RelationRecord(
                relation_id=f"gda:nr:standard:relation:document-value-domain:{value_domain_token}",
                relation_type="defines",
                source_concept_id=document_id,
                target_concept_id=value_domain_id,
                pref_label="定义值域",
                source_id=value_domain.source_id,
                source_object_id=value_domain.code,
            ))
        for member in value_domain.members:
            member_token = stable_token(
                value_domain.domain_id,
                value_domain.code.casefold(),
                member.code.casefold(),
                member.label,
                canonical_json(member.raw),
            )
            member_id = (
                f"gda:nr:standard:value-member:{value_domain.domain_id}:{member_token}"
            )
            hierarchy_labels = [
                _clean(value)
                for key, value in member.raw.items()
                if key not in {"代码", "编码", "序号"}
                and _clean(value)
                and _clean(value) != member.label
            ]
            add_concept(ConceptRecord(
                concept_id=member_id,
                uri=_uri(
                    "standard", value_domain.domain_id, "value-domain",
                    value_domain.code, "member", f"{member.code}-{member_token[:12]}",
                ),
                kind="ValueDomainMember",
                code=member.code,
                pref_label=member.label,
                alt_labels=list(dict.fromkeys(hierarchy_labels)),
                definition=" / ".join(dict.fromkeys([*hierarchy_labels, member.label])),
                domain_id=value_domain.domain_id,
                source_system="standard",
                source_id=value_domain.source_id,
                source_object_id=f"{value_domain.code}.{member.code}",
                lifecycle_status="candidate",
                provenance={
                    "value_domain_id": value_domain_id,
                    "ordinal": member.ordinal,
                    "raw_definition": member.raw,
                    "publication_status": "draft_or_unconfirmed",
                },
            ))
            add_relation(RelationRecord(
                relation_id=f"gda:nr:standard:relation:value-domain-member:{member_token}",
                relation_type="hasMember",
                source_concept_id=value_domain_id,
                target_concept_id=member_id,
                pref_label="包含值域成员",
                source_id=value_domain.source_id,
                source_object_id=f"{value_domain.code}.{member.code}",
            ))

    for entry in standards.entries:
        if entry.domain_id == "00":
            continue
        token = stable_token(entry.domain_id, entry.code.casefold())
        concept_id = f"gda:nr:standard:feature:{entry.domain_id}:{token}"
        standard_concept_by_key[(entry.domain_id, entry.code.casefold())] = concept_id
        add_concept(ConceptRecord(
            concept_id=concept_id,
            uri=_uri("standard", entry.domain_id, "feature", entry.code),
            kind="FeatureType",
            code=entry.code,
            pref_label=entry.label or entry.code,
            alt_labels=[entry.code] if entry.label and entry.label != entry.code else [],
            definition=f"自然资源“一张图”{DOMAIN_LABELS.get(entry.domain_id, entry.domain_id)}标准表/图层。",
            domain_id=entry.domain_id,
            source_system="standard",
            source_id=entry.source_id,
            source_object_id=entry.code,
            geometry_type=entry.geometry_type,
            lifecycle_status="candidate",
            provenance={
                "heading": entry.heading,
                "constraint": entry.constraint,
                "occurrences": entry.provenance,
                "publication_status": "draft_or_unconfirmed",
            },
        ))
        if entry.domain_id in standard_document_ids and standard_document_ids[entry.domain_id] in concept_ids:
            add_relation(RelationRecord(
                relation_id=f"gda:nr:standard:relation:document-feature:{token}",
                relation_type="defines",
                source_concept_id=standard_document_ids[entry.domain_id],
                target_concept_id=concept_id,
                pref_label="定义表或图层",
                source_id=entry.source_id,
                source_object_id=entry.code,
            ))
        add_relation(RelationRecord(
            relation_id=f"gda:nr:standard:relation:domain-feature:{token}",
            relation_type="contains",
            source_concept_id=_domain_concept_id(entry.domain_id),
            target_concept_id=concept_id,
            pref_label="包含标准要素类型",
            source_id=entry.source_id,
            source_object_id=entry.code,
        ))
        for field_index, standard_field in enumerate(entry.fields):
            field_token = stable_token(entry.domain_id, entry.code.casefold(), standard_field.code.casefold(), standard_field.ordinal)
            add_property(PropertyRecord(
                property_id=f"gda:nr:standard:property:{field_token}",
                owner_concept_id=concept_id,
                uri=_uri("standard", entry.domain_id, "feature", entry.code, "property", standard_field.code, str(standard_field.ordinal)),
                code=standard_field.code,
                pref_label=standard_field.label,
                datatype=standard_field.datatype,
                length=standard_field.length,
                precision_value=standard_field.precision,
                scale_value=standard_field.scale,
                min_count=1 if standard_field.required else 0,
                ordinal=standard_field.ordinal or field_index,
                value_domain=standard_field.value_domain,
                lifecycle_status="candidate",
                source_id=entry.source_id,
                source_object_id=f"{entry.code}.{standard_field.code}",
                provenance={
                    "heading": standard_field.heading,
                    "raw_definition": standard_field.raw,
                    "publication_status": "draft_or_unconfirmed",
                },
            ))

        code_matches = ea_rows_by_code.get(entry.code.casefold(), [])
        alias_matches = ea_rows_by_alias.get(entry.label, []) if entry.label else []
        candidate_map: dict[str, tuple[str, list[str]]] = {}
        for _, target_id in code_matches:
            candidate_map.setdefault(target_id, ("exact_code", []))[1].append("code")
        for _, target_id in alias_matches:
            candidate_map.setdefault(target_id, ("exact_label", []))[1].append("label")
        status = MappingStatus.CONFIRMED if len(candidate_map) == 1 else MappingStatus.CONFLICT
        for target_id, (match_basis, evidence_basis) in candidate_map.items():
            mapping_token = stable_token(concept_id, target_id)
            mappings.append(MappingRecord(
                mapping_id=f"gda:nr:mapping:{mapping_token}",
                source_concept_id=concept_id,
                target_concept_id=target_id,
                mapping_type="exact_match",
                mapping_status=status,
                confidence=1.0 if match_basis == "exact_code" else 0.98,
                evidence={
                    "policy": "strict-code-or-chinese-alias-v1",
                    "match_basis": sorted(set(evidence_basis)),
                    "standard_code": entry.code,
                    "standard_label": entry.label,
                    "candidate_count": len(candidate_map),
                    "requires_domain_review": status != MappingStatus.CONFIRMED,
                },
                reviewed_by="deterministic-strict-match-policy-v1" if status == MappingStatus.CONFIRMED else None,
                reviewed_at=datetime(2026, 8, 4, tzinfo=UTC) if status == MappingStatus.CONFIRMED else None,
            ))

    concept_id_set = {record.concept_id for record in concepts}
    valid_relations: list[RelationRecord] = []
    for relation in relations:
        if relation.source_concept_id not in concept_id_set or relation.target_concept_id not in concept_id_set:
            issues.append({
                "severity": "error",
                "code": "dangling_relation",
                "relation_id": relation.relation_id,
                "source": relation.source_concept_id,
                "target": relation.target_concept_id,
            })
        else:
            valid_relations.append(relation)

    concepts.sort(key=lambda record: record.concept_id)
    properties.sort(key=lambda record: (record.owner_concept_id, record.ordinal, record.property_id))
    valid_relations.sort(key=lambda record: record.relation_id)
    mappings.sort(key=lambda record: record.mapping_id)
    sources.sort(key=lambda record: record.source_id)
    issues.sort(key=lambda issue: (issue.get("severity", ""), issue.get("code", ""), canonical_json(issue)))
    return CompiledOntology(
        sources=sources,
        concepts=concepts,
        properties=properties,
        relations=valid_relations,
        mappings=mappings,
        issues=issues,
    )


def compile_domain_ontology(ea: EAInput, standards: StandardInput) -> CompiledOntology:
    """Build the curated domain model and retain source structures as metadata."""
    from .domain_model import compile_curated_domain_ontology

    return compile_curated_domain_ontology(compile_ontology(ea, standards))


def _write_jsonl_gzip(path: Path, records: Iterable[Any]) -> int:
    count = 0
    with path.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0, compresslevel=9) as compressed:
            for record in records:
                compressed.write(canonical_json(record))
                compressed.write(b"\n")
                count += 1
    return count


def _datatype_uri(datatype: str | None) -> Any:
    from rdflib import URIRef
    from rdflib.namespace import XSD

    mapping = {
        "xsd:string": XSD.string,
        "xsd:date": XSD.date,
        "xsd:dateTime": XSD.dateTime,
        "xsd:boolean": XSD.boolean,
        "xsd:double": XSD.double,
        "xsd:decimal": XSD.decimal,
        "xsd:integer": XSD.integer,
        "xsd:long": XSD.long,
        "xsd:base64Binary": XSD.base64Binary,
        "geo:wktLiteral": URIRef("http://www.opengis.net/ont/geosparql#wktLiteral"),
    }
    return mapping.get(datatype or "", XSD.string)


def build_rdf(compiled: CompiledOntology) -> tuple[Any, Any]:
    from rdflib import BNode, Graph, Literal, Namespace, RDF, RDFS, URIRef
    from rdflib.namespace import DCTERMS, OWL, PROV, SH, SKOS, XSD

    GDA = Namespace(BASE_URI)
    GEO = Namespace("http://www.opengis.net/ont/geosparql#")
    graph = Graph()
    shapes = Graph()
    for target in (graph, shapes):
        target.bind("gda", GDA)
        target.bind("geo", GEO)
        target.bind("owl", OWL)
        target.bind("skos", SKOS)
        target.bind("prov", PROV)
        target.bind("sh", SH)
        target.bind("dcterms", DCTERMS)

    ontology_uri = URIRef(BASE_URI.rstrip("/"))
    graph.add((ontology_uri, RDF.type, OWL.Ontology))
    graph.add((ontology_uri, DCTERMS.title, Literal("自然资源“一张图”领域本体", lang="zh")))
    graph.add((ontology_uri, OWL.versionInfo, Literal("compiled-package")))

    source_uri_by_id: dict[str, URIRef] = {}
    for source in compiled.sources:
        source_uri = URIRef(_uri("source", source.source_id))
        source_uri_by_id[source.source_id] = source_uri
        graph.add((source_uri, RDF.type, PROV.Entity))
        graph.add((source_uri, DCTERMS.title, Literal(source.title)))
        graph.add((source_uri, GDA.sha256, Literal(source.sha256)))
        graph.add((source_uri, DCTERMS.identifier, Literal(source.source_id)))

    class_kinds = {
        "DomainClass", "ProcessClass", "StateClass", "RoleClass",
        "InformationClass", "ObservationClass",
        # Compatibility for packages created with the v1 record contract.
        "MetaClass", "FeatureType", "ObjectType", "ActionType", "FunctionType",
        "InterfaceType", "QualityRule", "SpatialPolicy",
    }
    metadata_kind_types = {
        "Domain": GDA.SubjectArea,
        "SchemaArtifact": GDA.SchemaArtifact,
        "DatasetSchema": GDA.SchemaArtifact,
        "Package": GDA.ModelPackage,
        "StandardDocument": GDA.SourceDocument,
        "CRS": GDA.CRSReference,
        "CRSReference": GDA.CRSReference,
    }
    meta_labels = {
        GDA.SubjectArea: "数据主题域",
        GDA.SchemaArtifact: "数据结构制品",
        GDA.ModelPackage: "模型包",
        GDA.SourceDocument: "来源文档",
        GDA.CRSReference: "坐标参考系引用",
        GDA.SchemaField: "结构字段",
    }
    provenance_source = next(iter(source_uri_by_id.values()), ontology_uri)
    for meta_class, label in meta_labels.items():
        graph.add((meta_class, RDF.type, OWL.Class))
        graph.add((meta_class, SKOS.prefLabel, Literal(label, lang="zh")))
        graph.add((meta_class, DCTERMS.identifier, Literal(str(meta_class))))
        graph.add((meta_class, PROV.wasDerivedFrom, provenance_source))

    concept_uri_by_id = {record.concept_id: URIRef(record.uri) for record in compiled.concepts}
    concept_kind_by_id = {record.concept_id: record.kind for record in compiled.concepts}
    for record in compiled.concepts:
        subject = concept_uri_by_id[record.concept_id]
        if record.kind in {"ValueDomain", "ReferenceScheme"}:
            graph.add((subject, RDF.type, SKOS.ConceptScheme))
        elif record.kind in {"ValueDomainMember", "ReferenceConcept"}:
            graph.add((subject, RDF.type, SKOS.Concept))
            value_domain_id = record.provenance.get("value_domain_id")
            if value_domain_id in concept_uri_by_id:
                graph.add((subject, SKOS.inScheme, concept_uri_by_id[value_domain_id]))
        elif record.kind in class_kinds:
            graph.add((subject, RDF.type, OWL.Class))
        else:
            graph.add((subject, RDF.type, metadata_kind_types.get(record.kind, GDA.MetadataArtifact)))
        graph.add((subject, GDA.modelingRole, Literal(record.kind)))
        graph.add((subject, SKOS.prefLabel, Literal(record.pref_label, lang="zh")))
        graph.add((subject, DCTERMS.identifier, Literal(record.concept_id)))
        graph.add((subject, PROV.wasDerivedFrom, source_uri_by_id[record.source_id]))
        if record.code:
            graph.add((subject, GDA.code, Literal(record.code)))
        if record.definition:
            graph.add((subject, SKOS.definition, Literal(record.definition, lang="zh")))
        for label in record.alt_labels:
            graph.add((subject, SKOS.altLabel, Literal(label)))
        if record.domain_id:
            graph.add((subject, GDA.domain, URIRef(_uri("domain", record.domain_id))))
        if record.geometry_type and record.kind in class_kinds:
            graph.add((subject, RDFS.subClassOf, GEO.Feature))
            graph.add((subject, GDA.geometryType, Literal(record.geometry_type)))
        elif record.geometry_type:
            graph.add((subject, GDA.geometryType, Literal(record.geometry_type)))
        if record.ea_guid:
            graph.add((subject, GDA.eaGuid, Literal(record.ea_guid)))

    property_records_by_owner: dict[str, list[PropertyRecord]] = defaultdict(list)
    for record in compiled.properties:
        subject = URIRef(record.uri)
        owner = concept_uri_by_id[record.owner_concept_id]
        owner_kind = concept_kind_by_id[record.owner_concept_id]
        property_records_by_owner[record.owner_concept_id].append(record)
        if owner_kind in class_kinds:
            graph.add((subject, RDF.type, OWL.DatatypeProperty))
            graph.add((subject, RDFS.domain, owner))
            graph.add((subject, RDFS.range, _datatype_uri(record.datatype)))
        else:
            graph.add((subject, RDF.type, GDA.SchemaField))
            graph.add((subject, GDA.fieldOf, owner))
            graph.add((subject, GDA.datatype, _datatype_uri(record.datatype)))
        graph.add((subject, SKOS.prefLabel, Literal(record.pref_label, lang="zh")))
        graph.add((subject, GDA.code, Literal(record.code)))
        graph.add((subject, DCTERMS.identifier, Literal(record.property_id)))
        graph.add((subject, PROV.wasDerivedFrom, source_uri_by_id[record.source_id]))
        if record.ea_guid:
            graph.add((subject, GDA.eaGuid, Literal(record.ea_guid)))

    relation_predicates: dict[str, Any] = {
        "subClassOf": RDFS.subClassOf,
        "disjointWith": OWL.disjointWith,
        "broaderThan": SKOS.narrower,
        "hasMember": SKOS.member,
    }
    declared_predicates: set[Any] = set()
    for record in compiled.relations:
        source = concept_uri_by_id[record.source_concept_id]
        target = concept_uri_by_id[record.target_concept_id]
        if record.relation_type == "objectProperty":
            property_name = str(record.provenance.get("property_name") or record.relation_id)
            predicate = URIRef(_uri("property", property_name))
            graph.add((predicate, RDF.type, OWL.ObjectProperty))
            graph.add((predicate, RDFS.label, Literal(record.pref_label, lang="zh")))
            graph.add((predicate, RDFS.domain, source))
            graph.add((predicate, RDFS.range, target))
            if record.provenance.get("restriction") == "some":
                restriction = BNode()
                graph.add((restriction, RDF.type, OWL.Restriction))
                graph.add((restriction, OWL.onProperty, predicate))
                graph.add((restriction, OWL.someValuesFrom, target))
                graph.add((source, RDFS.subClassOf, restriction))
            continue
        if record.relation_type in {"allowedSource", "allowedTarget"}:
            predicate = URIRef(_uri("annotation", record.relation_type))
            graph.add((predicate, RDF.type, OWL.AnnotationProperty))
        else:
            predicate = relation_predicates.get(
                record.relation_type,
                URIRef(_uri("relation", record.relation_type)),
            )
        if predicate not in declared_predicates and predicate not in {
            RDFS.subClassOf, OWL.disjointWith, SKOS.narrower, SKOS.member,
        }:
            declared_predicates.add(predicate)
            if record.relation_type not in {"allowedSource", "allowedTarget"}:
                graph.add((predicate, RDF.type, OWL.ObjectProperty))
            graph.add((predicate, RDFS.label, Literal(record.relation_type)))
        graph.add((source, predicate, target))
        statement = URIRef(_uri("statement", stable_token(record.relation_id)))
        graph.add((statement, RDF.type, RDF.Statement))
        graph.add((statement, RDF.subject, source))
        graph.add((statement, RDF.predicate, predicate))
        graph.add((statement, RDF.object, target))
        graph.add((statement, PROV.wasDerivedFrom, source_uri_by_id[record.source_id]))
        graph.add((statement, DCTERMS.identifier, Literal(record.relation_id)))
        if record.ea_guid:
            graph.add((statement, GDA.eaGuid, Literal(record.ea_guid)))

    mapping_predicates = {
        "exact_match": SKOS.exactMatch,
        "close_match": SKOS.closeMatch,
        "broad_match": SKOS.broadMatch,
        "narrow_match": SKOS.narrowMatch,
        "related_match": SKOS.relatedMatch,
        "denotes_class": GDA.denotesClass,
        "describes": GDA.describes,
        "schema_correspondence": GDA.schemaCorrespondence,
    }
    for record in compiled.mappings:
        source = concept_uri_by_id[record.source_concept_id]
        target = concept_uri_by_id[record.target_concept_id]
        predicate = mapping_predicates.get(
            record.mapping_type,
            URIRef(_uri("mapping-property", record.mapping_type)),
        )
        if predicate not in {SKOS.exactMatch, SKOS.closeMatch, SKOS.broadMatch, SKOS.narrowMatch, SKOS.relatedMatch}:
            graph.add((predicate, RDF.type, OWL.ObjectProperty))
        graph.add((source, predicate, target))
        mapping_uri = URIRef(_uri("mapping", stable_token(record.mapping_id)))
        graph.add((mapping_uri, RDF.type, GDA.OntologyMapping))
        graph.add((mapping_uri, RDF.subject, source))
        graph.add((mapping_uri, RDF.predicate, predicate))
        graph.add((mapping_uri, RDF.object, target))
        graph.add((mapping_uri, GDA.mappingStatus, Literal(record.mapping_status.value)))
        graph.add((mapping_uri, DCTERMS.identifier, Literal(record.mapping_id)))

    for shape_name, target_class in (
        ("ClassConceptShape", OWL.Class),
        ("ValueMemberShape", SKOS.Concept),
        ("ValueDomainShape", SKOS.ConceptScheme),
    ):
        concept_shape = URIRef(str(GDA) + shape_name)
        shapes.add((concept_shape, RDF.type, SH.NodeShape))
        shapes.add((concept_shape, SH.targetClass, target_class))
        for path, min_count, node_kind in (
            (SKOS.prefLabel, 1, SH.Literal),
            (DCTERMS.identifier, 1, SH.Literal),
            (PROV.wasDerivedFrom, 1, SH.IRI),
        ):
            prop_shape = BNode()
            shapes.add((concept_shape, SH.property, prop_shape))
            shapes.add((prop_shape, SH.path, path))
            shapes.add((prop_shape, SH.minCount, Literal(min_count)))
            shapes.add((prop_shape, SH.nodeKind, node_kind))

    for owner_id, records in property_records_by_owner.items():
        if concept_kind_by_id.get(owner_id) not in class_kinds:
            continue
        if not any(record.source_id.startswith("std-doc-") for record in records):
            continue
        owner_uri = concept_uri_by_id[owner_id]
        shape_uri = URIRef(str(owner_uri) + "/shape")
        shapes.add((shape_uri, RDF.type, SH.NodeShape))
        shapes.add((shape_uri, SH.targetClass, owner_uri))
        for record in records:
            prop_shape = BNode()
            shapes.add((shape_uri, SH.property, prop_shape))
            shapes.add((prop_shape, SH.path, URIRef(record.uri)))
            shapes.add((prop_shape, SH.minCount, Literal(record.min_count)))
            if record.max_count is not None:
                shapes.add((prop_shape, SH.maxCount, Literal(record.max_count)))
            shapes.add((prop_shape, SH.datatype, _datatype_uri(record.datatype)))
            if record.length and record.datatype == "xsd:string":
                shapes.add((prop_shape, SH.maxLength, Literal(record.length)))

    property_ns = Namespace(_uri("property") + "/")
    for name, domain_name, range_uri in (
        ("occurredAt", "NaturalResourceActivity", XSD.dateTime),
        ("validFrom", "NaturalResourceState", XSD.dateTime),
        ("validTo", "NaturalResourceState", XSD.dateTime),
    ):
        domain_id = f"gda:nr:class:{domain_name}"
        if domain_id not in concept_uri_by_id:
            continue
        predicate = property_ns[name]
        graph.add((predicate, RDF.type, OWL.DatatypeProperty))
        graph.add((predicate, RDFS.domain, concept_uri_by_id[domain_id]))
        graph.add((predicate, RDFS.range, range_uri))

    def add_property_shape(
        node_shape: Any,
        path: Any,
        *,
        min_count: int | None = None,
        max_count: int | None = None,
        class_uri_value: Any | None = None,
        datatype: Any | None = None,
    ) -> None:
        prop_shape = BNode()
        shapes.add((node_shape, SH.property, prop_shape))
        shapes.add((prop_shape, SH.path, path))
        if min_count is not None:
            shapes.add((prop_shape, SH.minCount, Literal(min_count)))
        if max_count is not None:
            shapes.add((prop_shape, SH.maxCount, Literal(max_count)))
        if class_uri_value is not None:
            shapes.add((prop_shape, SH["class"], class_uri_value))
        if datatype is not None:
            shapes.add((prop_shape, SH.datatype, datatype))

    land_transition_id = "gda:nr:class:LandUseTransition"
    if land_transition_id in concept_uri_by_id:
        transition_shape = GDA.LandUseTransitionShape
        shapes.add((transition_shape, RDF.type, SH.NodeShape))
        shapes.add((transition_shape, SH.targetClass, concept_uri_by_id[land_transition_id]))
        add_property_shape(
            transition_shape, property_ns.affectsParcel, min_count=1, max_count=1,
            class_uri_value=concept_uri_by_id["gda:nr:class:LandParcel"],
        )
        add_property_shape(
            transition_shape, property_ns.hasSourceState, min_count=1, max_count=1,
            class_uri_value=concept_uri_by_id["gda:nr:class:LandUseState"],
        )
        add_property_shape(
            transition_shape, property_ns.hasTargetState, min_count=1, max_count=1,
            class_uri_value=concept_uri_by_id["gda:nr:class:LandUseState"],
        )
        add_property_shape(
            transition_shape, property_ns.occurredAt, min_count=1, max_count=1,
            datatype=XSD.dateTime,
        )
        add_property_shape(
            transition_shape, property_ns.supportedBy, min_count=1,
            class_uri_value=concept_uri_by_id["gda:nr:class:LegalBasis"],
        )
        add_property_shape(
            transition_shape, PROV.wasDerivedFrom, min_count=1,
        )

    construction_id = "gda:nr:class:ConstructionOccupation"
    if construction_id in concept_uri_by_id:
        construction_shape = GDA.ConstructionOccupationShape
        shapes.add((construction_shape, RDF.type, SH.NodeShape))
        shapes.add((construction_shape, SH.targetClass, concept_uri_by_id[construction_id]))
        add_property_shape(
            construction_shape, property_ns.hasSourceState, min_count=1, max_count=1,
            class_uri_value=concept_uri_by_id["gda:nr:class:AgriculturalLandUseState"],
        )
        add_property_shape(
            construction_shape, property_ns.hasTargetState, min_count=1, max_count=1,
            class_uri_value=concept_uri_by_id["gda:nr:class:ConstructionLandUseState"],
        )
        add_property_shape(construction_shape, property_ns.authorizedBy, min_count=1)

    adjustment_id = "gda:nr:class:AgriculturalStructureAdjustment"
    if adjustment_id in concept_uri_by_id:
        adjustment_shape = GDA.AgriculturalStructureAdjustmentShape
        shapes.add((adjustment_shape, RDF.type, SH.NodeShape))
        shapes.add((adjustment_shape, SH.targetClass, concept_uri_by_id[adjustment_id]))
        constraint = BNode()
        shapes.add((adjustment_shape, SH.sparql, constraint))
        shapes.add((constraint, SH.message, Literal(
            "农业结构调整必须在耕地与非耕农用地状态之间双向转换。", lang="zh"
        )))
        shapes.add((constraint, SH.select, Literal(f"""
            SELECT $this WHERE {{
              $this <{property_ns.hasSourceState}> ?source ;
                    <{property_ns.hasTargetState}> ?target .
              FILTER (
                (EXISTS {{ ?source a <{concept_uri_by_id['gda:nr:class:CultivatedLandUseState']}> }} &&
                 NOT EXISTS {{ ?target a <{concept_uri_by_id['gda:nr:class:NonCultivatedAgriculturalLandUseState']}> }}) ||
                (EXISTS {{ ?source a <{concept_uri_by_id['gda:nr:class:NonCultivatedAgriculturalLandUseState']}> }} &&
                 NOT EXISTS {{ ?target a <{concept_uri_by_id['gda:nr:class:CultivatedLandUseState']}> }}) ||
                (NOT EXISTS {{ ?source a <{concept_uri_by_id['gda:nr:class:CultivatedLandUseState']}> }} &&
                 NOT EXISTS {{ ?source a <{concept_uri_by_id['gda:nr:class:NonCultivatedAgriculturalLandUseState']}> }})
              )
            }}
        """)))
    return graph, shapes


def _serialize_gzip(graph: Any, path: Path) -> None:
    turtle = graph.serialize(format="turtle")
    payload = turtle.encode("utf-8") if isinstance(turtle, str) else turtle
    with path.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0, compresslevel=9) as compressed:
            compressed.write(payload)


def _artifact(path: Path, base: Path, media_type: str, record_count: int | None = None) -> ArtifactRecord:
    return ArtifactRecord(
        path=str(path.relative_to(base)),
        media_type=media_type,
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        record_count=record_count,
        bytes=path.stat().st_size,
    )


def write_package(
    compiled: CompiledOntology,
    output_dir: str | Path,
    *,
    semantic_version: str,
    generated_at: datetime | None = None,
) -> PackageManifest:
    """Write and atomically promote a deterministic immutable package."""
    from pyshacl import validate as shacl_validate

    target = Path(output_dir).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{target.name}.", dir=target.parent))
    try:
        source_count = _write_jsonl_gzip(staging / "sources.jsonl.gz", compiled.sources)
        concept_count = _write_jsonl_gzip(staging / "concepts.jsonl.gz", compiled.concepts)
        property_count = _write_jsonl_gzip(staging / "properties.jsonl.gz", compiled.properties)
        relation_count = _write_jsonl_gzip(staging / "relations.jsonl.gz", compiled.relations)
        mapping_count = _write_jsonl_gzip(staging / "mappings.jsonl.gz", compiled.mappings)

        graph, shapes = build_rdf(compiled)
        rdf_path = staging / "ontology.ttl.gz"
        shapes_path = staging / "shapes.ttl"
        _serialize_gzip(graph, rdf_path)
        shapes.serialize(destination=str(shapes_path), format="turtle")

        conforms, _, validation_text = shacl_validate(
            graph,
            shacl_graph=shapes,
            inference="rdfs",
            abort_on_first=False,
            meta_shacl=True,
            advanced=True,
        )
        severity_counts = Counter(issue.get("severity", "warning") for issue in compiled.issues)
        structural_error_count = severity_counts.get("error", 0)
        validation_report = {
            "conforms": bool(conforms) and structural_error_count == 0,
            "shacl_conforms": bool(conforms),
            "structural_error_count": structural_error_count,
            "issue_count": len(compiled.issues),
            "severity_counts": dict(severity_counts),
            "issues": compiled.issues,
            "shacl_report_text": str(validation_text),
            "validators": [
                "stable-id-and-reference-validator-v2",
                "modeling-role-boundary-validator-v2",
                "curated-domain-competency-validator-v2",
                "land-transition-shacl-validator-v2",
                "source-quality-observation-validator-v2",
                "pyshacl-meta-and-ontology-validator",
            ],
        }
        validation_path = staging / "validation-report.json"
        validation_path.write_bytes(canonical_json(validation_report))

        context = {
            "@context": {
                "gda": BASE_URI,
                "skos": "http://www.w3.org/2004/02/skos/core#",
                "prov": "http://www.w3.org/ns/prov#",
                "geo": "http://www.opengis.net/ont/geosparql#",
                "owl": "http://www.w3.org/2002/07/owl#",
                "sh": "http://www.w3.org/ns/shacl#",
                "id": "@id",
                "type": "@type",
                "prefLabel": "skos:prefLabel",
                "altLabel": "skos:altLabel",
                "definition": "skos:definition",
                "source": {"@id": "prov:wasDerivedFrom", "@type": "@id"},
                "geometryType": "gda:geometryType",
                "eaGuid": "gda:eaGuid",
            }
        }
        context_path = staging / "context.jsonld"
        context_path.write_bytes(canonical_json(context))

        artifacts = {
            "sources": _artifact(staging / "sources.jsonl.gz", staging, "application/x-ndjson+gzip", source_count),
            "concepts": _artifact(staging / "concepts.jsonl.gz", staging, "application/x-ndjson+gzip", concept_count),
            "properties": _artifact(staging / "properties.jsonl.gz", staging, "application/x-ndjson+gzip", property_count),
            "relations": _artifact(staging / "relations.jsonl.gz", staging, "application/x-ndjson+gzip", relation_count),
            "mappings": _artifact(staging / "mappings.jsonl.gz", staging, "application/x-ndjson+gzip", mapping_count),
            "rdf": _artifact(rdf_path, staging, "application/gzip"),
            "shacl": _artifact(shapes_path, staging, "text/turtle"),
            "jsonld_context": _artifact(context_path, staging, "application/ld+json"),
            "validation": _artifact(validation_path, staging, "application/json"),
        }
        source_fingerprint = sha256_json([source.model_dump(mode="json") for source in compiled.sources])
        content_sha256 = sha256_json({key: value.sha256 for key, value in sorted(artifacts.items())})
        ontology_version_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{ONTOLOGY_KEY}:{semantic_version}:{content_sha256}"))
        package_id = f"{ONTOLOGY_KEY}:{semantic_version}:{content_sha256[:16]}"

        concept_counts = Counter(record.kind for record in compiled.concepts)
        property_counts_by_owner = Counter(record.owner_concept_id for record in compiled.properties)
        concepts_by_id = {record.concept_id: record for record in compiled.concepts}
        mapping_count_by_domain = Counter()
        confirmed_mapping_count_by_domain = Counter()
        for mapping in compiled.mappings:
            source = concepts_by_id.get(mapping.source_concept_id)
            if source and source.domain_id:
                mapping_count_by_domain[source.domain_id] += 1
                if mapping.mapping_status == MappingStatus.CONFIRMED:
                    confirmed_mapping_count_by_domain[source.domain_id] += 1
        domain_stats = []
        curated_model = any(
            record.kind in {"DomainClass", "ProcessClass", "StateClass"}
            for record in compiled.concepts
        )
        for domain_id, label in DOMAIN_LABELS.items():
            domain_concepts = [record for record in compiled.concepts if record.domain_id == domain_id]
            feature_count = sum(
                record.kind in {"FeatureType", "SchemaArtifact"}
                and record.source_system == "standard"
                for record in domain_concepts
            )
            ea_schema_count = sum(
                record.kind in {"DatasetSchema", "SchemaArtifact"}
                and record.source_system == "enterprise_architect"
                for record in domain_concepts
            )
            value_domain_count = sum(
                record.kind in {"ValueDomain", "ReferenceScheme"}
                for record in domain_concepts
            )
            value_member_count = sum(
                record.kind in {"ValueDomainMember", "ReferenceConcept"}
                for record in domain_concepts
            )
            domain_class_count = sum(
                record.kind in {
                    "DomainClass", "ProcessClass", "StateClass", "RoleClass",
                    "InformationClass", "ObservationClass",
                }
                for record in domain_concepts
            )
            domain_property_count = sum(property_counts_by_owner.get(record.concept_id, 0) for record in domain_concepts)
            confirmed = confirmed_mapping_count_by_domain[domain_id]
            domain_stats.append({
                "domain_id": domain_id,
                "label": label,
                "concept_count": len(domain_concepts),
                "domain_class_count": domain_class_count,
                "standard_feature_count": feature_count,
                "ea_schema_count": ea_schema_count,
                "value_domain_count": value_domain_count,
                "value_member_count": value_member_count,
                "property_count": domain_property_count,
                "mapping_count": mapping_count_by_domain[domain_id],
                "confirmed_mapping_count": confirmed,
                "strict_coverage": round(confirmed / feature_count, 4) if feature_count else 0.0,
            })
        manifest = PackageManifest(
            package_id=package_id,
            ontology_version_id=ontology_version_id,
            semantic_version=semantic_version,
            title=(
                "自然资源“一张图”领域本体"
                if curated_model else "自然资源“一张图”来源结构本体"
            ),
            description=(
                "经领域策划的自然资源实体、状态、过程、权利与规则本体；标准和 EA 结构仅作为独立的数据映射与溯源模块。"
                if curated_model
                else "由自然资源“一张图”标准和 EA PostgreSQL 仓库编译的来源结构包。"
            ),
            generated_at=generated_at or datetime.now(UTC),
            source_fingerprint=source_fingerprint,
            content_sha256=content_sha256,
            stats={
                "source_count": source_count,
                "concept_count": concept_count,
                "property_count": property_count,
                "relation_count": relation_count,
                "mapping_count": mapping_count,
                "confirmed_mapping_count": sum(record.mapping_status == MappingStatus.CONFIRMED for record in compiled.mappings),
                "candidate_mapping_count": sum(record.mapping_status == MappingStatus.CANDIDATE for record in compiled.mappings),
                "conflict_mapping_count": sum(record.mapping_status == MappingStatus.CONFLICT for record in compiled.mappings),
                "rdf_triple_count": len(graph),
                "shacl_triple_count": len(shapes),
                "validation_issue_count": len(compiled.issues),
                "domain_class_count": sum(
                    record.kind in {
                        "DomainClass", "ProcessClass", "StateClass", "RoleClass",
                        "InformationClass", "ObservationClass",
                    }
                    for record in compiled.concepts
                ),
                "schema_artifact_count": sum(
                    record.kind == "SchemaArtifact" for record in compiled.concepts
                ),
                **{f"kind_{key}": value for key, value in sorted(concept_counts.items())},
            },
            domain_stats=domain_stats,
            artifacts=artifacts,
            vocabularies=[
                "RDF 1.1", "RDFS", "OWL 2 RL bounded profile", "SKOS", "SHACL",
                "PROV-O", "GeoSPARQL 1.1 vocabulary", "OWL-Time",
            ],
            validation_summary={
                "conforms": validation_report["conforms"],
                "shacl_conforms": validation_report["shacl_conforms"],
                "issue_count": validation_report["issue_count"],
                "severity_counts": validation_report["severity_counts"],
            },
            compatibility={
                "minimum_runtime_contract": "gda-ontology-package-v1",
                "semantic_architecture": "curated-domain-plus-mapping-modules-v2" if curated_model else "legacy-flat-v1",
                "authority_store": "PostgreSQL gda_ontology schema",
                "rdf_projection": "Apache Jena Fuseki/TDB2",
                "fallback": "hash-verified immutable package",
            },
        )
        (staging / "manifest.json").write_text(
            json.dumps(manifest.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        if not validation_report["conforms"]:
            raise ValueError(
                f"ontology package failed validation: SHACL={conforms}, structural_errors={structural_error_count}"
            )
        if target.exists():
            existing_manifest = target / "manifest.json"
            if existing_manifest.is_file():
                existing = PackageManifest.model_validate_json(existing_manifest.read_text(encoding="utf-8"))
                if existing.content_sha256 == manifest.content_sha256:
                    shutil.rmtree(staging)
                    return existing
            raise FileExistsError(f"immutable ontology package already exists: {target}")
        staging.replace(target)
        return manifest
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise
