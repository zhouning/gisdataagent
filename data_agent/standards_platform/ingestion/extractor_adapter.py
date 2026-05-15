"""Adapter: convert extractor output (field_tables/layer_tables/raw_tables)
into the structurer input shape ({FieldTable: [clause...]}).

Each parsed table becomes a clause:
- FieldTable -> clause with data_elements (one per FieldDef row)
- LayerTable -> clause with data_elements (one per LayerRow)
- raw_tables  -> clause with body_md containing original cells (PDF OCR fallback)
"""
from __future__ import annotations

from typing import Any


def _section_path_to_str(section_path: list[str]) -> str:
    return " / ".join(section_path) if section_path else ""


def _make_clause_no(prefix: str, idx: int, sub_idx: int | None = None) -> str:
    if sub_idx is None:
        return f"{prefix}.{idx}"
    return f"{prefix}.{idx}.{sub_idx}"


def adapt_extractor_output(extracted: dict) -> dict:
    """Transform extractor output to structurer input format.

    Input shapes accepted:
    - docx/pdf: {field_tables: [...], layer_tables: [...], raw_tables?: [...]}
    - xmi:      {modules: [...], classes: [...], associations: [...]}

    Output: {FieldTable: [clause, ...], LayerTable: []}
    where each clause has: clause_no, heading, kind, body_md, page,
    char_span, data_elements, terms.
    """
    clauses: list[dict] = []

    field_tables = extracted.get("field_tables") or []
    for ti, ft in enumerate(field_tables, start=1):
        section = _section_path_to_str(ft.get("section_path") or [])
        heading = ft.get("table_name_cn") or ft.get("caption_raw") or f"FieldTable {ti}"
        table_code = ft.get("table_code") or ""
        clause_no = f"FT.{ti}"

        data_elements = []
        for fd in ft.get("fields") or []:
            code = fd.get("code") or fd.get("name_cn") or ""
            if not code:
                continue
            de = {
                "code": code.strip(),
                "name_zh": fd.get("name_cn", "").strip(),
                "name_en": "",
                "definition": (fd.get("note") or "").strip(),
                "datatype": _build_datatype(fd),
                "obligation": _map_obligation(fd.get("constraint", "")),
            }
            data_elements.append(de)

        body_lines = [f"模块: {ft.get('module', '')}",
                      f"章节: {section}",
                      f"表代码: {table_code}",
                      f"字段数: {len(ft.get('fields') or [])}"]

        clauses.append({
            "clause_no": clause_no,
            "heading": heading,
            "kind": "table",
            "body_md": "\n".join(body_lines),
            "page": None,
            "char_span": None,
            "data_elements": data_elements,
            "terms": [],
        })

    layer_tables = extracted.get("layer_tables") or []
    for ti, lt in enumerate(layer_tables, start=1):
        heading = lt.get("caption_raw") or f"LayerTable {ti}"
        clause_no = f"LT.{ti}"

        data_elements = []
        for row in lt.get("rows") or []:
            code = (row.get("table_code") or "").strip()
            if not code:
                continue
            data_elements.append({
                "code": code,
                "name_zh": (row.get("layer_name") or "").strip(),
                "name_en": "",
                "definition": (row.get("note") or "").strip(),
                "datatype": (row.get("geometry") or "").strip(),
                "obligation": _map_obligation(row.get("constraint", "")),
            })

        clauses.append({
            "clause_no": clause_no,
            "heading": heading,
            "kind": "table",
            "body_md": f"模块: {lt.get('module', '')}\n图层数: {len(lt.get('rows') or [])}",
            "page": None,
            "char_span": None,
            "data_elements": data_elements,
            "terms": [],
        })

    raw_tables = extracted.get("raw_tables") or []
    for ti, rt in enumerate(raw_tables, start=1):
        heading = rt.get("caption") or f"RawTable page{rt.get('page', '?')}"
        clause_no = f"RT.{ti}"
        header = rt.get("header") or []
        rows = rt.get("rows") or []
        body_lines = [f"页码: {rt.get('page', '?')}",
                      f"表头: {' | '.join(str(c) for c in header)}",
                      f"行数: {len(rows)}"]
        for row in rows[:30]:
            body_lines.append(" | ".join(str(c) for c in row))

        clauses.append({
            "clause_no": clause_no,
            "heading": heading,
            "kind": "table",
            "body_md": "\n".join(body_lines),
            "page": rt.get("page"),
            "char_span": None,
            "data_elements": [],
            "terms": [],
        })

    if extracted.get("modules") or extracted.get("classes"):
        for ci, cls in enumerate(extracted.get("classes") or [], start=1):
            data_elements = []
            for attr in cls.get("attributes") or []:
                code = (attr.get("name") or "").strip()
                if not code:
                    continue
                data_elements.append({
                    "code": code,
                    "name_zh": code,
                    "name_en": "",
                    "definition": (attr.get("description") or "").strip(),
                    "datatype": (attr.get("type") or "").strip(),
                    "obligation": "mandatory" if attr.get("mandatory") else "optional",
                })
            clauses.append({
                "clause_no": f"XC.{ci}",
                "heading": cls.get("name", f"Class {ci}"),
                "kind": "definition",
                "body_md": cls.get("description") or "",
                "page": None,
                "char_span": None,
                "data_elements": data_elements,
                "terms": [],
            })

    return {"FieldTable": clauses, "LayerTable": []}


def _build_datatype(fd: dict) -> str:
    dtype = (fd.get("dtype") or "").strip()
    length = (fd.get("length") or "").strip()
    decimal = (fd.get("decimal") or "").strip()
    if length and decimal and decimal not in ("0", ""):
        return f"{dtype}({length},{decimal})"
    if length:
        return f"{dtype}({length})"
    return dtype


def _map_obligation(constraint: str) -> str:
    c = (constraint or "").strip().upper()
    if c in {"M", "必填", "MANDATORY"}:
        return "mandatory"
    if c in {"O", "可选", "OPTIONAL"}:
        return "optional"
    if c in {"C", "条件", "CONDITIONAL"}:
        return "conditional"
    return "optional"
