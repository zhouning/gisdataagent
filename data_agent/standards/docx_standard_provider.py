"""Docx Standard Provider — surfaces 国标 field dictionaries to NL2SQL prompts.

Reads from data_agent/standards/compiled_docx/*.yaml (built by docx_extractor.py).
Two entry points:

1. get_field_dict_for_tables(table_codes)
   Format the full field table for explicit table codes (e.g. ['DLTB']).
   Use when the caller already knows which physical/standard table is relevant.

2. recall_field_dicts(query, max_tables=3)
   Cheap keyword recall — extract Chinese tokens (≥2 chars) and table-name
   matches from query; return top-K field dictionaries.

Output is a prompt-ready string segment that can be appended verbatim to the
NL2SQL prompt. No LLM calls, no embedding — pure index lookup.
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Iterable

import yaml

_COMPILED_DIR = Path(__file__).resolve().parent / "compiled_docx"

# Token: contiguous Chinese characters (≥2) OR uppercase ASCII codes (≥2)
_TOKEN_RE = re.compile(r"[一-鿿]{2,}|[A-Z][A-Z0-9_]{1,}")


@lru_cache(maxsize=1)
def _load_all_field_tables() -> list[dict]:
    """Load every field_table from every module yaml. Returns flat list."""
    out: list[dict] = []
    if not _COMPILED_DIR.is_dir():
        return out
    for yp in sorted(_COMPILED_DIR.glob("*.yaml")):
        if yp.name.startswith("_"):
            continue
        try:
            doc = yaml.safe_load(yp.read_text(encoding="utf-8")) or {}
        except Exception:
            continue
        module = doc.get("module") or yp.stem
        for ft in doc.get("field_tables", []):
            out.append({
                "module": module,
                "table_code": (ft.get("table_code") or "").strip().upper(),
                "table_name_cn": ft.get("table_name_cn") or "",
                "caption_raw": ft.get("caption_raw") or "",
                "section_path": ft.get("section_path") or [],
                "fields": ft.get("fields") or [],
                "notes": ft.get("notes") or [],
            })
    return out


@lru_cache(maxsize=1)
def _build_index() -> dict:
    """Build lookup indexes."""
    all_tables = _load_all_field_tables()
    by_code: dict[str, list[dict]] = {}
    by_name_token: dict[str, list[int]] = {}     # 2-char token from table_name_cn -> table indexes
    by_field_cn: dict[str, list[int]] = {}       # field中文名 -> table indexes
    by_field_code: dict[str, list[int]] = {}     # field code -> table indexes
    for i, t in enumerate(all_tables):
        if t["table_code"]:
            by_code.setdefault(t["table_code"], []).append(t)
        name = t["table_name_cn"] or ""
        for tok in _TOKEN_RE.findall(name):
            by_name_token.setdefault(tok, []).append(i)
        for f in t["fields"]:
            cn = (f.get("name_cn") or "").strip()
            if cn:
                by_field_cn.setdefault(cn, []).append(i)
            code = (f.get("code") or "").strip().upper()
            if code:
                by_field_code.setdefault(code, []).append(i)
    return {
        "tables": all_tables,
        "by_code": by_code,
        "by_name_token": by_name_token,
        "by_field_cn": by_field_cn,
        "by_field_code": by_field_code,
    }


# --------------------------------------------------------------------------- #
# Formatting
# --------------------------------------------------------------------------- #

def _format_field_row(f: dict) -> str:
    parts = []
    parts.append(f"{f.get('name_cn','')}({f.get('code','')})")
    dtype = (f.get("dtype") or "").strip()
    length = (f.get("length") or "").strip()
    if dtype:
        if length:
            parts.append(f"{dtype}({length})")
        else:
            parts.append(dtype)
    domain = (f.get("domain") or "").strip()
    if domain:
        parts.append(f"值域={domain}")
    constraint = (f.get("constraint") or "").strip()
    if constraint:
        parts.append(f"{constraint}")
    note = (f.get("note") or "").strip()
    if note:
        parts.append(f"备注={note}")
    return "  - " + " | ".join(parts)


def _format_table(t: dict, max_fields: int | None = None) -> str:
    out = []
    out.append(f"### {t['table_name_cn'] or t['table_code']} (国标表名: {t['table_code'] or '-'}, 模块: {t['module']})")
    fields = t["fields"]
    if max_fields and len(fields) > max_fields:
        fields = fields[:max_fields]
        truncated = True
    else:
        truncated = False
    for f in fields:
        out.append(_format_field_row(f))
    if truncated:
        out.append(f"  (字段共 {len(t['fields'])} 个，已截断显示前 {max_fields} 个)")
    return "\n".join(out)


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #

def get_field_dict_for_tables(table_codes: Iterable[str],
                              max_fields_per_table: int | None = None) -> str:
    """Return a formatted standard-field-dictionary block for the given codes."""
    idx = _build_index()
    by_code = idx["by_code"]
    parts: list[str] = []
    for code in table_codes:
        code = (code or "").strip().upper()
        if not code:
            continue
        candidates = by_code.get(code, [])
        if not candidates:
            continue
        # Prefer non-"全域数据模型" entry (de-dup the umbrella copy)
        candidates_sorted = sorted(candidates, key=lambda c: "全域" in c["module"])
        t = candidates_sorted[0]
        parts.append(_format_table(t, max_fields_per_table))
    if not parts:
        return ""
    return ("## 自然资源数据库国标字段字典 (节选)\n"
            "下表给出与本问题相关的国标表字段定义。\n"
            "格式: 中文名(国标字段编码) | 类型(长度) | 值域 | 约束(M=必填 C=条件 O=可选) | 备注。\n"
            "实际 PG 表的列名通常是国标编码的小写形式 (e.g. 地类名称 → 列名 `dlmc`)。\n\n"
            + "\n\n".join(parts))


def recall_field_dicts(query: str, max_tables: int = 3,
                       max_fields_per_table: int | None = None) -> str:
    """Cheap keyword recall — Chinese 2-char tokens + field中文名 + field code matches."""
    idx = _build_index()
    tables = idx["tables"]
    tokens = set(_TOKEN_RE.findall(query))
    if not tokens:
        return ""

    scores: dict[int, float] = {}

    # (a) Field中文名 exact match — strongest signal (+3 each)
    for tok in tokens:
        for ti in idx["by_field_cn"].get(tok, []):
            scores[ti] = scores.get(ti, 0.0) + 3.0
    # (b) Field code exact match (+5)
    for tok in tokens:
        for ti in idx["by_field_code"].get(tok.upper(), []):
            scores[ti] = scores.get(ti, 0.0) + 5.0
    # (c) Table name token (+2)
    for tok in tokens:
        for ti in idx["by_name_token"].get(tok, []):
            scores[ti] = scores.get(ti, 0.0) + 2.0

    if not scores:
        return ""

    # Sort, dedup by table_code preferring non-"全域数据模型"
    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], "全域" in tables[kv[0]]["module"]))
    chosen: list[dict] = []
    seen_codes: set[str] = set()
    for ti, _score in ranked:
        t = tables[ti]
        code = t["table_code"] or t["table_name_cn"]
        if code in seen_codes:
            continue
        seen_codes.add(code)
        chosen.append(t)
        if len(chosen) >= max_tables:
            break

    parts = [_format_table(t, max_fields_per_table) for t in chosen]
    return ("## 自然资源数据库国标字段字典 (按问题召回)\n"
            "下面是与本问题用语最相关的国标表字段定义 (按关键词匹配召回)。\n"
            "格式: 中文名(国标字段编码) | 类型(长度) | 值域 | 约束(M=必填 C=条件 O=可选) | 备注。\n"
            "实际 PG 表的列名通常是国标编码的小写形式 (e.g. 地类名称 → 列名 `dlmc`)。\n\n"
            + "\n\n".join(parts))


if __name__ == "__main__":
    # Smoke test
    print("=== DLTB explicit lookup ===")
    print(get_field_dict_for_tables(["DLTB"]))
    print()
    print("=== Recall on a real Q ===")
    q = "找出土地利用现状图斑中，地类名称为'水田'且图斑面积大于 50000 平方米的图斑标识码。"
    out = recall_field_dicts(q, max_tables=2, max_fields_per_table=15)
    print(out)
