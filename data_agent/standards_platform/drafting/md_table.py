"""Parse a markdown table embedded in clause body_md → list of data_element dicts."""
from __future__ import annotations

import re
from typing import Any

# Column header keywords (Chinese). Order doesn't matter; we map by header text.
_COL_KEYWORDS = {
    "code": {"字段代码", "代码", "字段名"},
    "name": {"字段名称", "名称", "中文名称"},
    "type": {"类型", "字段类型", "数据类型"},
    "length": {"长度", "字段长度"},
    "domain": {"值域", "值域范围", "取值范围"},
    "obligation": {"必选", "约束", "约束条件"},
    "note": {"备注", "说明"},
}


def _classify_header(cell: str) -> str | None:
    cleaned = cell.strip().replace(" ", "")
    for key, kws in _COL_KEYWORDS.items():
        if cleaned in kws:
            return key
    return None


def _split_row(line: str) -> list[str]:
    """Split a markdown table row by `|`. Strip leading/trailing | and whitespace."""
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def _is_divider(line: str) -> bool:
    s = line.strip()
    if not s.startswith("|"):
        return False
    # divider rows are e.g. |---|---|---| or |:---|:---:|---:|
    return bool(re.match(r"^\|[\s:|-]+\|?$", s))


def _coerce_cell(v: str) -> str:
    """Empty-marker cells (-, blank, whitespace) → ''."""
    s = (v or "").strip()
    if s in {"-", "—", "–", ""}:
        return ""
    return s


def _build_datatype(dtype: str, length: str) -> str:
    dtype = _coerce_cell(dtype)
    length = _coerce_cell(length)
    if not dtype:
        return ""
    if not length:
        return dtype
    return f"{dtype}({length})"


_OBLIGATION_MAP = {
    "M": "mandatory", "MANDATORY": "mandatory", "必填": "mandatory",
    "C": "conditional", "CONDITIONAL": "conditional", "条件": "conditional",
    "O": "optional", "OPTIONAL": "optional", "可选": "optional",
}


def _map_obligation(raw: str) -> str:
    return _OBLIGATION_MAP.get(_coerce_cell(raw).upper(), "optional")


def parse_md_table(body_md: str) -> list[dict[str, Any]]:
    """Parse the first markdown table in body_md → list of data_element dicts.

    Returns [] if no recognized table is present. Raises ValueError if a table
    is detected but cannot be unambiguously mapped (e.g., missing required
    code column).
    """
    if not body_md:
        return []
    lines = body_md.splitlines()
    # Find first header row + divider pair
    for i in range(len(lines) - 1):
        line = lines[i].strip()
        nxt = lines[i + 1].strip() if i + 1 < len(lines) else ""
        if line.startswith("|") and _is_divider(nxt):
            header_row = _split_row(line)
            data_start = i + 2
            break
    else:
        return []

    col_map: dict[str, int] = {}
    for idx, h in enumerate(header_row):
        key = _classify_header(h)
        if key and key not in col_map:
            col_map[key] = idx
    if "code" not in col_map:
        raise ValueError("markdown table missing 字段代码 / 代码 column")
    if "name" not in col_map:
        raise ValueError("markdown table missing 字段名称 / 名称 column")

    out: list[dict[str, Any]] = []
    for j in range(data_start, len(lines)):
        line = lines[j].strip()
        if not line.startswith("|"):
            break  # table ended
        if _is_divider(line):
            continue
        cells = _split_row(line)
        if len(cells) < len(header_row):
            cells = cells + [""] * (len(header_row) - len(cells))
        code = _coerce_cell(cells[col_map["code"]])
        if not code:
            continue  # skip blank rows
        out.append({
            "code": code,
            "name_zh": _coerce_cell(cells[col_map["name"]]),
            "datatype": _build_datatype(
                cells[col_map["type"]] if "type" in col_map else "",
                cells[col_map["length"]] if "length" in col_map else "",
            ),
            "definition": _coerce_cell(cells[col_map["note"]])
                if "note" in col_map else "",
            "obligation": _map_obligation(cells[col_map["obligation"]])
                if "obligation" in col_map else "optional",
        })
    return out
