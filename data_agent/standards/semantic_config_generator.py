"""Derive semantic-layer column configs from docx 国标 field tables.

For a given (PG table, docx table code) pair, produce a `register_cq_semantic`
style dict per column, so the human editor can focus on patching the PostGIS
special rules / foreign synonyms rather than rewriting from scratch.

Data model matches scripts/nl2sql_bench_cq/register_cq_semantic.py COLUMN_META:
  {
    "domain":  "AREA" | "ID" | "NAME" | "LAND_USE" | ... | None,
    "aliases": [str, ...],
    "unit":    "m²" | "层" | "度" | "",
    "desc":    "业务中文描述",
  }

Heuristics we use (all cheap, no LLM):
  - aliases = [field.name_cn, field.code.upper()]  (auto)
  - unit    = parsed from field.note ("面积单位：㎡" → "m²"); else normalised
  - desc    = "{name_cn}. 国标字段代码 {code}. {domain_note}. {note}"
  - domain  = rule-based mapping on field.code suffix / name_cn keywords
  - is_geometry = dtype mentions '几何' or 'Geometry' or 'Polygon'/'Point'/'Line'

Output: a dict matching register_cq_semantic schema + a per-column provenance
tag so the diff tool can report what came from docx vs what is missing.
"""
from __future__ import annotations

import re
import yaml
from pathlib import Path
from typing import Any

_COMPILED = Path(__file__).resolve().parent / "compiled_docx"


# --------------------------------------------------------------------------- #
# Unit parsing
# --------------------------------------------------------------------------- #

_UNIT_PATTERNS = [
    (re.compile(r"面积单位[:：]\s*㎡|面积.*m²|平方米"), "m²"),
    (re.compile(r"面积单位[:：]\s*hm²|公顷"), "hm²"),
    (re.compile(r"长度单位[:：]\s*m\b|长度.*米"), "m"),
    (re.compile(r"高程.*[:：]\s*m\b"), "m"),
    (re.compile(r"单位[:：]\s*度|经度|纬度"), "度"),
    (re.compile(r"单位[:：]\s*%"), "%"),
    (re.compile(r"坐标.*m\b"), "m"),
]


def _parse_unit(note: str, domain_hint: str) -> str:
    """Extract unit from a field.note / field.domain string."""
    text = f"{note} {domain_hint}"
    for rx, u in _UNIT_PATTERNS:
        if rx.search(text):
            return u
    return ""


# --------------------------------------------------------------------------- #
# Semantic domain inference (rule-based)
# --------------------------------------------------------------------------- #

# Mapping: (code suffix tokens or name keywords) → semantic_domain
_DOMAIN_RULES: list[tuple[str, str, str]] = [
    # (pattern_type: "code" or "name", regex, domain)
    ("code", r"^BSM$", "ID"),
    ("code", r"^YSDM$", "FEATURE_CODE"),
    ("code", r"MJ$", "AREA"),           # 面积 suffix
    ("code", r"KD$", "LENGTH"),          # 宽度 suffix
    ("code", r"CD$", "LENGTH"),          # 长度 suffix
    ("code", r"MC$", "NAME"),            # 名称 suffix
    ("code", r"DM$", "CODE"),            # 代码 suffix
    ("code", r"BM$", "CODE"),            # 编码 suffix
    ("code", r"BH$", "ID"),              # 编号 suffix
    ("code", r"RQ$", "DATE"),            # 日期
    ("code", r"SJ$", "DATETIME"),        # 时间
    ("code", r"NF$", "YEAR"),
    ("code", r"^DLBM$|^DLMC$|^DLLX$", "LAND_USE"),
    ("code", r"^QS|^ZL", "OWNERSHIP"),   # 权属 / 坐落
    ("code", r"^XZQ", "ADMIN_CODE"),     # 行政区
    ("name", r"地类", "LAND_USE"),
    ("name", r"权属|坐落", "OWNERSHIP"),
    ("name", r"面积", "AREA"),
    ("name", r"长度|周长|宽度", "LENGTH"),
    ("name", r"名称", "NAME"),
    ("name", r"代码|编码", "CODE"),
    ("name", r"编号", "ID"),
    ("name", r"几何|Polygon|Point|LineString", None),  # geometry, no domain tag
    ("name", r"日期", "DATE"),
    ("name", r"年份", "YEAR"),
    ("name", r"行政区", "ADMIN_CODE"),
    ("name", r"备注|描述", None),
]


def _infer_domain(code: str, name_cn: str) -> str | None:
    for ptype, rx, dom in _DOMAIN_RULES:
        target = code if ptype == "code" else name_cn
        if re.search(rx, target or "", re.IGNORECASE):
            return dom
    return None


def _is_geometry_field(dtype: str, name_cn: str) -> bool:
    t = f"{dtype} {name_cn}"
    return bool(re.search(r"几何|Geometry|Polygon|LineString|Point", t, re.IGNORECASE))


# --------------------------------------------------------------------------- #
# Description assembly
# --------------------------------------------------------------------------- #

def _build_desc(fd: dict) -> str:
    parts = []
    name_cn = (fd.get("name_cn") or "").strip()
    code = (fd.get("code") or "").strip().upper()
    dtype = (fd.get("dtype") or "").strip()
    length = (fd.get("length") or "").strip()
    decimal = (fd.get("decimal") or "").strip()
    domain = (fd.get("domain") or "").strip()
    note = (fd.get("note") or "").strip()
    constraint = (fd.get("constraint") or "").strip()

    if name_cn and code:
        parts.append(f"{name_cn} (国标字段代码 {code})")
    elif name_cn:
        parts.append(name_cn)
    elif code:
        parts.append(f"国标字段 {code}")

    if dtype:
        type_str = dtype
        if length:
            type_str += f"({length}"
            if decimal:
                type_str += f",{decimal}"
            type_str += ")"
        parts.append(f"类型 {type_str}")

    if domain:
        parts.append(f"值域 {domain}")

    if constraint:
        constraint_map = {"M": "必填", "C": "条件必填", "O": "可选", "是": "必填", "否": "可选"}
        c_cn = constraint_map.get(constraint, constraint)
        parts.append(c_cn)

    if note:
        parts.append(note)

    return "。".join(parts) + "。"


# --------------------------------------------------------------------------- #
# Per-column derivation
# --------------------------------------------------------------------------- #

def derive_column_meta(fd: dict) -> dict:
    """Convert one docx field to register_cq_semantic column dict."""
    code = (fd.get("code") or "").strip().upper()
    name_cn = (fd.get("name_cn") or "").strip()
    aliases = []
    if name_cn:
        aliases.append(name_cn)
    if code:
        aliases.append(code)

    domain = _infer_domain(code, name_cn)
    unit = _parse_unit(fd.get("note") or "", fd.get("domain") or "")
    desc = _build_desc(fd)
    is_geom = _is_geometry_field(fd.get("dtype") or "", name_cn)

    return {
        "domain": None if is_geom else domain,
        "aliases": aliases,
        "unit": unit,
        "desc": desc,
        "is_geometry": is_geom,
        # Provenance metadata — not part of register schema; used by diff tool
        "_docx_code": code,
        "_docx_constraint": fd.get("constraint", ""),
        "_docx_length": fd.get("length", ""),
    }


# --------------------------------------------------------------------------- #
# Public: generate full table config
# --------------------------------------------------------------------------- #

def _load_docx_table(module_yaml: str, table_code: str) -> dict | None:
    path = _COMPILED / module_yaml
    if not path.is_file():
        return None
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    for ft in doc.get("field_tables", []):
        if (ft.get("table_code") or "").strip().upper() == table_code.upper():
            return ft
    return None


def generate_semantic_config(
    module_yaml: str,
    docx_table_code: str,
    pg_column_names: list[str] | None = None,
) -> dict[str, Any]:
    """
    Generate semantic-layer config for one table from docx.

    Args:
        module_yaml:   filename under compiled_docx/ (e.g. '02_统一调查监测.yaml')
        docx_table_code: e.g. 'DLTB'
        pg_column_names: if provided, only generate entries for columns that
                         exist in the real PG table (case-insensitive). The
                         extra (docx-only) fields are returned in the report
                         as "governance gap".

    Returns:
        {
          "pg_table_code": ...,
          "derived": {column_name: {domain/aliases/unit/desc/...}, ...},
          "docx_only": [ ... ],     # in docx but not in PG table
          "pg_only": [ ... ],       # in PG but not in docx
          "source_caption": ...,
        }
    """
    ft = _load_docx_table(module_yaml, docx_table_code)
    if ft is None:
        return {"error": f"Table {docx_table_code} not found in {module_yaml}"}

    docx_fields = {f["code"].strip().upper(): f for f in ft["fields"] if f.get("code")}
    pg_set_upper = None
    if pg_column_names is not None:
        pg_set_upper = {c.upper() for c in pg_column_names}

    derived: dict[str, dict] = {}
    docx_only: list[str] = []
    for code, fd in docx_fields.items():
        meta = derive_column_meta(fd)
        if pg_set_upper is not None and code not in pg_set_upper:
            docx_only.append(code)
            continue
        # Key by PG physical column name (preserve original case from caller)
        if pg_column_names:
            for pg_col in pg_column_names:
                if pg_col.upper() == code:
                    derived[pg_col] = meta
                    break
        else:
            derived[code] = meta

    pg_only: list[str] = []
    if pg_column_names is not None:
        for c in pg_column_names:
            if c.upper() not in docx_fields:
                pg_only.append(c)

    return {
        "pg_table_code": docx_table_code,
        "source_caption": ft.get("caption_raw", ""),
        "derived": derived,
        "docx_only": docx_only,
        "pg_only": pg_only,
        "docx_field_count": len(docx_fields),
    }


if __name__ == "__main__":
    # Smoke: DLTB vs real cq_land_use_dltb schema
    real_cols = ["objectid", "BSM", "YSDM", "DLBM", "DLMC",
                 "QSDWDM", "QSDWMC", "ZLDWDM", "ZLDWMC", "TBMJ", "shape",
                 # ArcGIS-derived
                 "SHAPE_Length", "SHAPE_Area"]
    r = generate_semantic_config("02_统一调查监测.yaml", "DLTB", real_cols)
    import json
    print(json.dumps({
        "docx_field_count": r["docx_field_count"],
        "derived_count": len(r["derived"]),
        "docx_only": r["docx_only"],
        "pg_only": r["pg_only"],
    }, ensure_ascii=False, indent=2))
    print("\n=== derived example (TBMJ) ===")
    if "TBMJ" in r["derived"]:
        print(json.dumps(r["derived"]["TBMJ"], ensure_ascii=False, indent=2))
