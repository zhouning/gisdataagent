"""Extract structured field / layer tables from 一张图 docx standards.

Strategy:
- Iterate body XML in order so Caption paragraphs can be bound to their table.
- Identify 2 canonical shapes:
  * FIELD table (9 cols): [序号, 字段名称, 字段代码, 字段类型, 字段长度, 小数位数, 值域, 约束条件, 备注]
  * LAYER table: contains '层名' + '属性表名' + '几何特征' (or close variants)
- Strip trailing "注1..." merged rows (all cells identical).
- Associate table to the nearest preceding Caption / Heading paragraph.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Iterable

import yaml
from docx import Document
from docx.document import Document as DocumentCls
from docx.oxml.ns import qn
from docx.table import Table as DocxTable
from docx.text.paragraph import Paragraph


# --------------------------------------------------------------------------- #
# Data model
# --------------------------------------------------------------------------- #

@dataclass
class FieldDef:
    seq: str
    name_cn: str
    code: str
    dtype: str
    length: str
    decimal: str
    domain: str
    constraint: str
    note: str


@dataclass
class FieldTable:
    module: str
    table_name_cn: str      # "地类图斑属性结构描述表"
    table_code: str         # "DLTB"
    caption_raw: str        # "表5-13地类图斑属性结构描述表(属性表名：DLTB)"
    section_path: list[str] # ["5 国土调查数据库结构定义", "地类图斑属性结构"]
    fields: list[FieldDef]
    notes: list[str] = field(default_factory=list)  # trailing "注1..." narrative


@dataclass
class LayerRow:
    seq: str
    layer_name: str         # "城区监测范围"
    feature: str            # "城区监测范围面层"
    geometry: str           # "Polygon"
    table_code: str         # "CQJCFWA"
    constraint: str         # "M" / "C" / "O"
    note: str


@dataclass
class LayerTable:
    module: str
    caption_raw: str
    section_path: list[str]
    rows: list[LayerRow]


# --------------------------------------------------------------------------- #
# Body iteration (preserves paragraph/table order)
# --------------------------------------------------------------------------- #

def _iter_block_items(doc: DocumentCls) -> Iterable[Paragraph | DocxTable]:
    body = doc.element.body
    for child in body.iterchildren():
        if child.tag == qn("w:p"):
            yield Paragraph(child, doc)
        elif child.tag == qn("w:tbl"):
            yield DocxTable(child, doc)


# --------------------------------------------------------------------------- #
# Header / shape classification
# --------------------------------------------------------------------------- #

# Header column aliases — different modules use slightly different vocabulary.
_NAME_ALIASES = {"字段名称", "中文名称", "属性中文名", "中文释义"}
_CODE_ALIASES = {"字段代码", "属性项", "属性名", "字段名"}
_TYPE_ALIASES = {"字段类型", "数据类型", "类型"}
_LEN_ALIASES  = {"字段长度", "长度"}
_DOMAIN_ALIASES = {"值域", "值域或示例", "值域范围", "取值范围"}
_CONSTRAINT_ALIASES = {"约束条件", "是否必填", "必填"}
_NOTE_ALIASES = {"备注", "说明"}
_DEC_ALIASES = {"小数位数", "小数"}

_LAYER_NAME_KEYS = {"层名", "图层", "数据集"}
_LAYER_CODE_KEYS = {"属性表名", "图层（属性表）名", "图层名", "图层编码", "属性表中文名称"}
_LAYER_GEOM_KEYS = {"几何特征", "几何类型"}

def _row_texts(row) -> list[str]:
    return [(c.text or "").strip() for c in row.cells]

def _classify_table(t: DocxTable) -> str:
    rows = t.rows
    if not rows:
        return "unknown"
    header = set(_row_texts(rows[0]))
    has_name = bool(header & _NAME_ALIASES)
    has_code = bool(header & _CODE_ALIASES)
    has_type = bool(header & _TYPE_ALIASES)
    if has_name and has_code and has_type:
        return "field"
    # Layer table: needs a code column AND (geom OR layer-name keyword)
    has_layer_code = bool(header & _LAYER_CODE_KEYS)
    has_layer_geom = bool(header & _LAYER_GEOM_KEYS)
    has_layer_name = bool(header & _LAYER_NAME_KEYS)
    if has_layer_code and (has_layer_geom or has_layer_name):
        return "layer"
    return "unknown"

def _is_note_row(row, n_cols: int) -> bool:
    texts = _row_texts(row)
    if len(texts) != n_cols:
        return False
    first = texts[0]
    if not first:
        return False
    # All cells identical AND starts with 注 / Note / explanation pattern
    if all(c == first for c in texts):
        if first.startswith("注") or first.startswith("Note") or re.match(r"^[0-9]+[\.、]", first):
            return True
        # Sometimes notes don't start with 注 but are clearly narrative (length >>)
        if len(first) > 40:
            return True
    return False


# --------------------------------------------------------------------------- #
# Caption parsing
# --------------------------------------------------------------------------- #

_CAPTION_RE = re.compile(
    r"^表\s*[\d\-\.]+\s*(?P<cn>.*?)(?:[(（]\s*属性表名\s*[:：]\s*(?P<code>[A-Za-z0-9_一-鿿]+)\s*[)）])?\s*$"
)

def _parse_caption(raw: str) -> tuple[str, str]:
    """Return (table_name_cn, table_code). Either may be ''."""
    m = _CAPTION_RE.match(raw.strip())
    if not m:
        return "", ""
    cn = (m.group("cn") or "").strip()
    code = (m.group("code") or "").strip()
    # Drop trailing punctuation from cn
    cn = re.sub(r"[。\s]+$", "", cn)
    return cn, code


def _looks_like_caption(p: Paragraph) -> bool:
    t = (p.text or "").strip()
    if not t:
        return False
    style = (p.style.name if p.style and p.style.name else "").lower()
    if "caption" in style:
        return True
    # Some docs use plain style but text starts with "表 x-y"
    if re.match(r"^表\s*[\d\-\.]+", t):
        return True
    return False


# --------------------------------------------------------------------------- #
# Heading stack
# --------------------------------------------------------------------------- #

def _heading_level(style_name: str) -> int | None:
    m = re.match(r"^Heading\s+(\d+)", style_name or "")
    return int(m.group(1)) if m else None


class _SectionStack:
    def __init__(self):
        self._stack: list[tuple[int, str]] = []

    def push(self, level: int, text: str):
        # Pop any same-or-deeper-level
        while self._stack and self._stack[-1][0] >= level:
            self._stack.pop()
        self._stack.append((level, text))

    def path(self) -> list[str]:
        return [t for _, t in self._stack]


# --------------------------------------------------------------------------- #
# Extractor
# --------------------------------------------------------------------------- #

def extract(docx_path: str | Path, module_name: str) -> dict[str, list]:
    doc = Document(str(docx_path))
    stack = _SectionStack()
    last_caption: tuple[str, str, str] | None = None   # (raw, cn, code)
    recent_plain_paragraphs: list[str] = []            # fallback if no caption

    field_tables: list[FieldTable] = []
    layer_tables: list[LayerTable] = []

    for block in _iter_block_items(doc):
        if isinstance(block, Paragraph):
            style = block.style.name if block.style else ""
            text = (block.text or "").strip()
            if not text:
                continue
            # Heading
            lvl = _heading_level(style)
            if lvl is not None:
                stack.push(lvl, text)
                last_caption = None
                recent_plain_paragraphs.clear()
                continue
            # Caption
            if _looks_like_caption(block):
                cn, code = _parse_caption(text)
                last_caption = (text, cn, code)
                continue
            # Other
            recent_plain_paragraphs.append(text)
            if len(recent_plain_paragraphs) > 3:
                recent_plain_paragraphs.pop(0)

        elif isinstance(block, DocxTable):
            kind = _classify_table(block)
            if kind == "unknown":
                last_caption = None
                continue

            raw_caption = last_caption[0] if last_caption else ""
            cn = last_caption[1] if last_caption else ""
            code = last_caption[2] if last_caption else ""

            if kind == "field":
                ft = _parse_field_table(block, module_name, raw_caption, cn, code, stack.path())
                if ft and ft.fields:
                    field_tables.append(ft)
            elif kind == "layer":
                lt = _parse_layer_table(block, module_name, raw_caption, stack.path())
                if lt and lt.rows:
                    layer_tables.append(lt)

            last_caption = None  # caption consumed

    return {
        "field_tables": [asdict(ft) for ft in field_tables],
        "layer_tables": [asdict(lt) for lt in layer_tables],
    }


def _resolve_col(header_idx: dict[str, int], aliases: set[str]) -> int:
    for k, i in header_idx.items():
        if k in aliases:
            return i
    return -1


def _parse_field_table(t: DocxTable, module: str, raw_caption: str,
                       cn: str, code: str, section_path: list[str]) -> FieldTable | None:
    rows = t.rows
    header = _row_texts(rows[0])
    idx = {h: i for i, h in enumerate(header)}

    col_name = _resolve_col(idx, _NAME_ALIASES)
    col_code = _resolve_col(idx, _CODE_ALIASES)
    col_type = _resolve_col(idx, _TYPE_ALIASES)
    if col_name < 0 or col_code < 0 or col_type < 0:
        return None

    col_seq = idx.get("序号", -1)
    col_len = _resolve_col(idx, _LEN_ALIASES)
    col_dec = _resolve_col(idx, _DEC_ALIASES)
    col_dom = _resolve_col(idx, _DOMAIN_ALIASES)
    col_con = _resolve_col(idx, _CONSTRAINT_ALIASES)
    col_note = _resolve_col(idx, _NOTE_ALIASES)

    fields: list[FieldDef] = []
    notes: list[str] = []
    n_cols = len(header)

    def gc(cells: list[str], i: int) -> str:
        return cells[i] if 0 <= i < len(cells) else ""

    for row in rows[1:]:
        if _is_note_row(row, n_cols):
            note_text = _row_texts(row)[0].strip()
            if note_text:
                notes.append(note_text)
            continue
        cells = _row_texts(row)
        if len(cells) < n_cols:
            continue
        # In 是否必填-style tables, normalise to M/O
        raw_constraint = gc(cells, col_con)
        constraint = raw_constraint
        if raw_constraint in ("是",): constraint = "M"
        elif raw_constraint in ("否",): constraint = "O"

        fd = FieldDef(
            seq=gc(cells, col_seq),
            name_cn=gc(cells, col_name),
            code=gc(cells, col_code),
            dtype=gc(cells, col_type),
            length=gc(cells, col_len),
            decimal=gc(cells, col_dec),
            domain=gc(cells, col_dom),
            constraint=constraint,
            note=gc(cells, col_note),
        )
        if not (fd.name_cn or fd.code):
            continue
        fields.append(fd)

    return FieldTable(
        module=module,
        table_name_cn=cn,
        table_code=code,
        caption_raw=raw_caption,
        section_path=section_path.copy(),
        fields=fields,
        notes=notes,
    )


def _parse_layer_table(t: DocxTable, module: str, raw_caption: str,
                       section_path: list[str]) -> LayerTable | None:
    rows = t.rows
    header = _row_texts(rows[0])
    idx = {h: i for i, h in enumerate(header)}

    col_code = _resolve_col(idx, _LAYER_CODE_KEYS)
    if col_code < 0:
        return None

    col_seq = idx.get("序号", -1)
    col_layer = _resolve_col(idx, _LAYER_NAME_KEYS)
    col_feature = -1
    for k in ("层要素", "图层", "数据内容", "属性表分类"):
        if k in idx:
            col_feature = idx[k]; break
    col_geom = _resolve_col(idx, _LAYER_GEOM_KEYS)
    col_con  = _resolve_col(idx, _CONSTRAINT_ALIASES)
    col_note = _resolve_col(idx, _NOTE_ALIASES)

    n_cols = len(header)
    out_rows: list[LayerRow] = []
    def gc(cells: list[str], i: int) -> str:
        return cells[i] if 0 <= i < len(cells) else ""

    for row in rows[1:]:
        if _is_note_row(row, n_cols):
            continue
        cells = _row_texts(row)
        if len(cells) < n_cols:
            continue
        lr = LayerRow(
            seq=gc(cells, col_seq),
            layer_name=gc(cells, col_layer),
            feature=gc(cells, col_feature),
            geometry=gc(cells, col_geom),
            table_code=gc(cells, col_code),
            constraint=gc(cells, col_con),
            note=gc(cells, col_note),
        )
        if not lr.table_code:
            continue
        out_rows.append(lr)
    return LayerTable(
        module=module,
        caption_raw=raw_caption,
        section_path=section_path.copy(),
        rows=out_rows,
    )


# --------------------------------------------------------------------------- #
# Batch driver
# --------------------------------------------------------------------------- #

_DOCX_ROOT_DEFAULT = Path(r"D:\adk\数据标准\自然资源一张图数据库标准1128")
_OUT_ROOT_DEFAULT  = Path(r"D:\adk\data_agent\standards\compiled_docx")

_MODULE_ID_RE = re.compile(r"（(\d+)）(.+?)(?:\d{4})?\.docx?$")

def _module_id_from_filename(name: str) -> str:
    # "自然资源"一张图"数据库体系结构（2）统一调查监测1126.docx" → "02_统一调查监测"
    m = _MODULE_ID_RE.search(name)
    if m:
        num = m.group(1).zfill(2)
        return f"{num}_{m.group(2)}"
    return Path(name).stem


def compile_docx_corpus(source_dir: Path = _DOCX_ROOT_DEFAULT,
                        out_dir: Path = _OUT_ROOT_DEFAULT) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    files = sorted(source_dir.glob("*.doc*"))

    summary: list[dict] = []
    all_codes: dict[str, list[str]] = {}  # field_code -> list of tables using it

    for fp in files:
        module = _module_id_from_filename(fp.name)
        try:
            result = extract(fp, module)
        except Exception as e:
            summary.append({"module": module, "file": fp.name, "error": str(e)})
            continue

        mod_out = out_dir / f"{module}.yaml"
        with mod_out.open("w", encoding="utf-8") as f:
            yaml.safe_dump({
                "module": module,
                "source_file": fp.name,
                **result,
            }, f, allow_unicode=True, sort_keys=False)

        fcount = sum(len(ft["fields"]) for ft in result["field_tables"])
        lcount = sum(len(lt["rows"]) for lt in result["layer_tables"])
        summary.append({
            "module": module,
            "file": fp.name,
            "field_tables": len(result["field_tables"]),
            "fields_total": fcount,
            "layer_tables": len(result["layer_tables"]),
            "layers_total": lcount,
        })

        # Build field code cross-index
        for ft in result["field_tables"]:
            for fd in ft["fields"]:
                code = fd["code"].strip().upper()
                if code:
                    all_codes.setdefault(code, []).append(f"{module}::{ft['table_code'] or ft['table_name_cn']}")

    # Write summary + cross-index
    with (out_dir / "_summary.yaml").open("w", encoding="utf-8") as f:
        yaml.safe_dump({"modules": summary}, f, allow_unicode=True, sort_keys=False)

    # Cross-index: field_code -> unique tables
    code_index = {c: sorted(set(tbls)) for c, tbls in all_codes.items()}
    with (out_dir / "_field_code_index.yaml").open("w", encoding="utf-8") as f:
        yaml.safe_dump(code_index, f, allow_unicode=True, sort_keys=True)

    return {
        "modules_processed": len(summary),
        "total_field_tables": sum(m.get("field_tables", 0) for m in summary),
        "total_fields": sum(m.get("fields_total", 0) for m in summary),
        "total_layer_tables": sum(m.get("layer_tables", 0) for m in summary),
        "total_layers": sum(m.get("layers_total", 0) for m in summary),
        "unique_field_codes": len(code_index),
    }


if __name__ == "__main__":
    import json
    r = compile_docx_corpus()
    print(json.dumps(r, ensure_ascii=False, indent=2))
