#!/usr/bin/env python3
"""Audit provenance-backed SJNF/MSSM candidates for the frozen JQDLTB source.

The audit is read-only. It records what the standard defines, what the source
actually contains, and why candidate fields are rejected or left pending. It
never creates a derivation rule or writes canonical values.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROTOCOL = (
    REPO_ROOT
    / "benchmarks/standard_mapping_chongqing_v0_1/source_onboarding_protocol.json"
)
DEFAULT_DATASET_ROOT = (
    REPO_ROOT
    / ".tmp/twm_standard_1128/自然资源一张图数据库标准1128/"
    "规划院提供数据样例及Demo系统功能演示建议/01数据样例"
)
DEFAULT_STANDARD_DOC = (
    REPO_ROOT
    / ".tmp/twm_standard_1128/自然资源一张图数据库标准1128/"
    "自然资源“一张图”数据库体系结构（2）统一调查监测1126.docx"
)
DEFAULT_OUTPUT = (
    REPO_ROOT / "docs/reports/jqdltb_semantic_candidate_audit_2026-08-26.json"
)
SCHEMA = "gda.jqdltb_semantic_candidate_audit.v1"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_sha256(value: Any) -> str:
    from data_agent.platform_contracts import canonical_json_fingerprint

    return canonical_json_fingerprint(value)


def _display_path(path: Path) -> str:
    resolved = path.resolve()
    return str(resolved.relative_to(REPO_ROOT)) if resolved.is_relative_to(REPO_ROOT) else path.name


def _field_profile(frame: Any, field: str) -> dict[str, Any]:
    import pandas as pd

    series = frame[field]
    values = series.dropna()
    blank_count = int(series.fillna("").astype(str).str.strip().eq("").sum())
    return {
        "field": field,
        "dtype": str(series.dtype),
        "rows": int(len(series)),
        "null_count": int(series.isna().sum()),
        "blank_count": blank_count,
        "non_blank_count": int(len(series) - blank_count),
        "distinct_non_null": int(values.nunique()),
        "numeric_like_count": int(pd.to_numeric(values, errors="coerce").notna().sum()),
    }


def _extract_dltb_standard(doc_path: Path) -> dict[str, Any]:
    from docx import Document

    document = Document(doc_path)
    matches: list[tuple[int, Any]] = []
    for index, table in enumerate(document.tables):
        rows = [[" ".join(cell.text.split()) for cell in row.cells] for row in table.rows]
        codes = {row[2] for row in rows if len(row) >= 3}
        notes = " ".join(" ".join(row) for row in rows if row and row[0].startswith("注"))
        if {"SJNF", "MSSM"}.issubset(codes) and "数据年份为数据生产的年份" in notes:
            matches.append((index, table))
    if len(matches) != 1:
        raise ValueError(
            "expected exactly one DLTB table containing SJNF/MSSM and the "
            f"production-year note, found {len(matches)}"
        )
    table_index, table = matches[0]
    rows = [[" ".join(cell.text.split()) for cell in row.cells] for row in table.rows]
    header = rows[0]
    records: dict[str, list[str]] = {}
    notes = ""
    for row in rows[1:]:
        if row and row[0].startswith("注"):
            notes = " ".join(row)
            continue
        if len(row) >= 3 and row[2] in {"SJNF", "MSSM"}:
            records[row[2]] = row
    if set(records) != {"SJNF", "MSSM"}:
        raise ValueError(f"DLTB table {table_index} did not expose SJNF and MSSM rows")
    sjnf_note = "数据年份为数据生产的年份"
    if sjnf_note not in notes:
        raise ValueError("DLTB standard note for SJNF production year is missing")
    return {
        "document_table_index": table_index,
        "table_name": "地类图斑属性结构描述表（属性表名：DLTB）",
        "header": header,
        "fields": {
            "SJNF": {
                "name_zh": records["SJNF"][1],
                "code": records["SJNF"][2],
                "type": records["SJNF"][3],
                "length": records["SJNF"][4],
                "domain": records["SJNF"][6],
                "constraint": records["SJNF"][7],
                "remark": records["SJNF"][8],
                "definition": sjnf_note,
            },
            "MSSM": {
                "name_zh": records["MSSM"][1],
                "code": records["MSSM"][2],
                "type": records["MSSM"][3],
                "length": records["MSSM"][4],
                "domain": records["MSSM"][6],
                "constraint": records["MSSM"][7],
                "remark": records["MSSM"][8],
                "definition": None,
            },
        },
        "notes": {
            "sjnf_definition_present": sjnf_note in notes,
            "mssm_value_domain_present": bool(records["MSSM"][6]),
        },
    }


def _xml_evidence(xml_path: Path) -> dict[str, Any]:
    text = xml_path.read_text(encoding="utf-8", errors="replace")
    labels = {field: field in text for field in ("DLBZ", "PZWH", "SM")}
    root = ElementTree.fromstring(text)
    process_dates = sorted(
        {
            date
            for element in root.iter("Process")
            if (date := str(element.attrib.get("Date", "")).strip()).isdigit()
        }
    )
    creation_date = next(
        ((element.text or "").strip() for element in root.iter("CreaDate")), None
    )
    return {
        "path": _display_path(xml_path),
        "sha256": _sha256(xml_path),
        "field_labels_present": labels,
        "arcgis_metadata_creation_date": creation_date,
        "arcgis_process_date_min": process_dates[0] if process_dates else None,
        "arcgis_process_date_max": process_dates[-1] if process_dates else None,
        "arcgis_process_years": sorted({date[:4] for date in process_dates}),
        "semantic_definition_present": False,
        "production_year_value_present": False,
        "mssm_value_domain_present": False,
        "interpretation": (
            "ArcGIS lineage and field-label evidence only; no authoritative "
            "SJNF/MSSM semantics."
        ),
    }


def audit(protocol_path: Path, dataset_root: Path, standard_doc: Path) -> dict[str, Any]:
    import geopandas as gpd

    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    source_path = (
        dataset_root / Path(protocol["source"]["relative_path"])
    ).resolve(strict=True)
    if not source_path.is_relative_to(dataset_root):
        raise ValueError("source path escapes dataset root")
    frame = gpd.read_file(source_path)
    from data_agent.standards_platform.application.acceptance import bundle_identity

    identity = bundle_identity(source_path)
    if identity["bundle_sha256"] != protocol["source"]["bundle_sha256"]:
        raise ValueError("source bundle identity does not match sealed protocol")
    xml_path = source_path.with_suffix(".shp.xml")
    standard = _extract_dltb_standard(standard_doc)

    source_fields = ["PZWH", "SM", "DLBZ", "JQDLMC"]
    profiles = {
        field: _field_profile(frame, field)
        for field in source_fields
        if field in frame.columns
    }
    candidates = {
        "SJNF": [
            {
                "field": "PZWH",
                "status": "rejected",
                "reason": (
                    "PZWH 字段没有权威定义可证明数据生产年份；且本源仅 10 条非空，"
                    "无法覆盖 DLTB 必填字段。"
                ),
                "evidence": profiles.get("PZWH"),
            },
            {
                "field": "SM",
                "status": "rejected",
                "reason": "源字段全为空，不能提供数据生产年份。",
                "evidence": profiles.get("SM"),
            },
            {
                "field": "JQDLMC",
                "status": "rejected",
                "reason": "地类名称不是数据生产年份；把类别名称转换为年份没有来源依据。",
                "evidence": profiles.get("JQDLMC"),
            },
            {
                "field": "metadata_processing_history",
                "status": "rejected",
                "reason": (
                    "JQDLTB.shp.xml 的 ArcGIS 处理时间是编辑/处理痕迹，不等于"
                    "标准定义的数据生产年份。"
                ),
                "evidence": {
                    "source": "JQDLTB.shp.xml",
                    "semantic_definition_present": False,
                },
            },
        ],
        "MSSM": [
            {
                "field": "DLBZ",
                "status": "rejected",
                "reason": (
                    "字段在源 XML 中仅有标签且本源全为空；没有 DLTB MSSM "
                    "Char(2) 的值域或填写规则证据。"
                ),
                "evidence": profiles.get("DLBZ"),
            },
            {
                "field": "SM",
                "status": "rejected",
                "reason": "源字段全为空，且标准正文没有把 SM 定义为 DLTB MSSM 来源。",
                "evidence": profiles.get("SM"),
            },
            {
                "field": "PZWH",
                "status": "rejected",
                "reason": (
                    "PZWH 没有被标准材料绑定为 DLTB 描述说明来源；字段覆盖、长度"
                    "和值域也不能满足目标语义。"
                ),
                "evidence": profiles.get("PZWH"),
            },
            {
                "field": "JQDLMC",
                "status": "rejected",
                "reason": (
                    "地类名称不是 Char(2) 描述说明值；把名称截断或编码会制造"
                    "未批准语义。"
                ),
                "evidence": profiles.get("JQDLMC"),
            },
        ],
    }
    for target in candidates:
        candidates[target].append(
            {
                "field": "no_authoritative_candidate",
                "status": "pending_business_evidence",
                "reason": (
                    "需要业务方提供与本 ProductVersion 绑定的生产年份依据。"
                    if target == "SJNF"
                    else "需要业务方提供 DLTB MSSM Char(2) 的正式值域、逐行规则或确认继续隔离。"
                ),
            }
        )

    report: dict[str, Any] = {
        "schema": SCHEMA,
        "audit_mode": "read_only_provenance_backed_candidate_audit",
        "protocol_id": protocol["protocol_id"],
        "identities": {
            "archive_sha256": protocol["source"]["archive_sha256"],
            "bundle_sha256": identity["bundle_sha256"],
            "feature_count": int(len(frame)),
            "source_crs": frame.crs.to_string() if frame.crs else None,
            "standard_doc_code": protocol["standardization"]["standard_doc_code"],
            "standard_version_label": protocol["standardization"][
                "standard_version_label"
            ],
        },
        "standard_evidence": {
            "document_path": _display_path(standard_doc),
            "document_sha256": _sha256(standard_doc),
            "source_reference": (
                "自然资源‘一张图’数据库体系结构（2）统一调查监测1126.docx，"
                "表5-13 DLTB"
            ),
            "definition": standard,
        },
        "source_evidence": {
            "relative_path": protocol["source"]["relative_path"],
            "metadata_xml": _xml_evidence(xml_path),
            "candidate_field_profiles": profiles,
            "target_fields_present": {
                field: field in frame.columns for field in ("SJNF", "MSSM")
            },
            "target_values_written": False,
        },
        "candidates": candidates,
        "decisions": {
            "SJNF": "blocked_no_authoritative_derivation",
            "MSSM": "blocked_no_authoritative_derivation",
        },
        "business_input_minimum": [
            {
                "target": "SJNF",
                "request": (
                    "提供能证明该 JQDLTB 产品数据生产年份的版本化业务材料/字段，"
                    "并确认按年份填入全量记录。"
                ),
                "accepted_shape": (
                    "source field or business artifact + SHA-256 + deterministic "
                    "extraction method"
                ),
            },
            {
                "target": "MSSM",
                "request": (
                    "提供 DLTB MSSM Char(2) 的正式值域和逐行规则；若没有，"
                    "确认该字段继续隔离而不写默认值。"
                ),
                "accepted_shape": (
                    "standard/code-list artifact + SHA-256 + deterministic mapping "
                    "or explicit quarantine policy"
                ),
            },
        ],
        "governance": {
            "derivation_rule_created": False,
            "strategy_created": False,
            "approval_case_created": False,
            "data_product_version_created": False,
        },
    }
    report["report_sha256"] = _canonical_sha256(report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--dataset-root", type=Path, default=DEFAULT_DATASET_ROOT)
    parser.add_argument("--standard-doc", type=Path, default=DEFAULT_STANDARD_DOC)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    protocol = args.protocol if args.protocol.is_absolute() else REPO_ROOT / args.protocol
    dataset_root = (
        args.dataset_root
        if args.dataset_root.is_absolute()
        else REPO_ROOT / args.dataset_root
    )
    standard_doc = (
        args.standard_doc
        if args.standard_doc.is_absolute()
        else REPO_ROOT / args.standard_doc
    )
    report = audit(
        protocol.resolve(strict=True),
        dataset_root.resolve(strict=True),
        standard_doc.resolve(strict=True),
    )
    output = args.output if args.output.is_absolute() else REPO_ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "schema": report["schema"],
                "output": str(output),
                "report_sha256": report["report_sha256"],
                "decisions": report["decisions"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
