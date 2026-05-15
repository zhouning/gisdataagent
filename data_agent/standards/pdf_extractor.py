"""Extract structured field / layer tables from GB/T PDF standards.

Strategy:
1. Try pymupdf native text extraction (fast, works for well-encoded PDFs).
2. Detect garbled text (CID font encoding issues common in old GB/T PDFs).
3. Fall back to OCR via RapidOCR (ONNX-based, no external binary needed).
4. Apply column-classification heuristics from docx_extractor.
"""
from __future__ import annotations

import re
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np
import fitz  # pymupdf

from .docx_extractor import (
    FieldDef, FieldTable, LayerRow, LayerTable,
    _NAME_ALIASES, _CODE_ALIASES, _TYPE_ALIASES, _LEN_ALIASES,
    _DOMAIN_ALIASES, _CONSTRAINT_ALIASES, _NOTE_ALIASES, _DEC_ALIASES,
    _LAYER_NAME_KEYS, _LAYER_CODE_KEYS, _LAYER_GEOM_KEYS,
)
from ..observability import get_logger

logger = get_logger("standards.pdf_extractor")

_ocr_engine = None


def _get_ocr():
    global _ocr_engine
    if _ocr_engine is None:
        from rapidocr_onnxruntime import RapidOCR
        _ocr_engine = RapidOCR()
    return _ocr_engine


def _clean(cell: str | None) -> str:
    if cell is None:
        return ""
    return re.sub(r"\s+", " ", cell).strip()


def _is_garbled(text: str) -> bool:
    """Detect if extracted text is garbled (CID encoding failure).

    Chinese standard PDFs with broken CID fonts produce Latin-1 garbage
    (e.g. 'ÇÞ', '©)', '|\x8c-') instead of actual CJK characters.
    We check: if a text that should be Chinese has very few CJK chars, it's garbled.
    """
    if not text or len(text) < 5:
        return True
    # Count actual CJK characters (common Chinese range)
    cjk_count = sum(1 for c in text if '一' <= c <= '鿿'
                    or '㐀' <= c <= '䶿'
                    or '豈' <= c <= '﫿')
    # Count ASCII letters/digits (legitimate in codes like "DLTB", "01")
    ascii_alnum = sum(1 for c in text if c.isascii() and c.isalnum())
    # For a Chinese standard, we expect significant CJK presence.
    # If there are almost no CJK chars but plenty of non-space chars, it's garbled.
    non_space = sum(1 for c in text if not c.isspace())
    if non_space == 0:
        return True
    cjk_ratio = cjk_count / non_space
    # A Chinese standard table header should have at least some CJK
    return cjk_ratio < 0.1


# --- PLACEHOLDER_CLASSIFY ---


def _classify_header(cells: list[str]) -> str:
    """Classify a header row as 'field', 'layer', or 'unknown'."""
    texts = {c.replace(" ", "") for c in cells if c}
    has_name = bool(texts & _NAME_ALIASES)
    has_code = bool(texts & _CODE_ALIASES)
    has_type = bool(texts & _TYPE_ALIASES)
    if has_name and has_code and has_type:
        return "field"
    has_layer_name = bool(texts & _LAYER_NAME_KEYS)
    has_layer_code = bool(texts & _LAYER_CODE_KEYS)
    has_layer_geom = bool(texts & _LAYER_GEOM_KEYS)
    if has_layer_name and (has_layer_code or has_layer_geom):
        return "layer"
    return "unknown"


def _map_field_columns(header: list[str]) -> dict[str, int]:
    mapping: dict[str, int] = {}
    for i, h in enumerate(header):
        h_clean = h.replace(" ", "")
        if h_clean in {"序号", "编号"}:
            mapping.setdefault("seq", i)
        elif h_clean in _NAME_ALIASES:
            mapping.setdefault("name", i)
        elif h_clean in _CODE_ALIASES:
            mapping.setdefault("code", i)
        elif h_clean in _TYPE_ALIASES:
            mapping.setdefault("type", i)
        elif h_clean in _LEN_ALIASES:
            mapping.setdefault("length", i)
        elif h_clean in _DEC_ALIASES:
            mapping.setdefault("decimal", i)
        elif h_clean in _DOMAIN_ALIASES:
            mapping.setdefault("domain", i)
        elif h_clean in _CONSTRAINT_ALIASES:
            mapping.setdefault("constraint", i)
        elif h_clean in _NOTE_ALIASES:
            mapping.setdefault("note", i)
    return mapping


def _map_layer_columns(header: list[str]) -> dict[str, int]:
    mapping: dict[str, int] = {}
    for i, h in enumerate(header):
        h_clean = h.replace(" ", "")
        if h_clean in {"序号", "编号"}:
            mapping.setdefault("seq", i)
        elif h_clean in _LAYER_NAME_KEYS:
            mapping.setdefault("layer_name", i)
        elif h_clean in _LAYER_CODE_KEYS:
            mapping.setdefault("table_code", i)
        elif h_clean in _LAYER_GEOM_KEYS:
            mapping.setdefault("geometry", i)
        elif h_clean in _CONSTRAINT_ALIASES:
            mapping.setdefault("constraint", i)
        elif h_clean in _NOTE_ALIASES:
            mapping.setdefault("note", i)
    return mapping


def _get_cell(row: list[str], idx: int | None) -> str:
    if idx is None or idx >= len(row):
        return ""
    return _clean(row[idx])


# --- PLACEHOLDER_OCR ---


def _ocr_page_tables(page: fitz.Page) -> list[list[list[str]]]:
    """Render page to image, OCR once, then assign text to table cells by bbox.

    Returns list of tables, each table is list of rows, each row is list of cells.
    """
    ocr = _get_ocr()
    pix = page.get_pixmap(dpi=200)
    img_array = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
        pix.height, pix.width, pix.n)
    if pix.n == 4:
        img_array = img_array[:, :, :3]

    tables_finder = page.find_tables()
    if not tables_finder.tables:
        return []

    # Single OCR call for the whole page
    ocr_result, _ = ocr(img_array)
    if not ocr_result:
        return []

    # ocr_result: list of [box(4 points), text, confidence]
    # box = [[x0,y0],[x1,y0],[x1,y1],[x0,y1]] in image coords
    text_boxes = []
    for item in ocr_result:
        box, text, _conf = item
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        text_boxes.append({
            "x0": min(xs), "y0": min(ys),
            "x1": max(xs), "y1": max(ys),
            "cx": (min(xs) + max(xs)) / 2,
            "cy": (min(ys) + max(ys)) / 2,
            "text": text,
        })

    scale = 200.0 / 72.0
    results = []

    for tab in tables_finder.tables:
        row_count = tab.row_count
        col_count = tab.col_count
        cells = tab.cells
        grid: list[list[list[str]]] = [
            [[] for _ in range(col_count)] for _ in range(row_count)
        ]

        for row_idx in range(row_count):
            for col_idx in range(col_count):
                cell_idx = row_idx * col_count + col_idx
                if cell_idx >= len(cells):
                    continue
                cell_rect = cells[cell_idx]
                if cell_rect is None:
                    continue
                cx0 = cell_rect[0] * scale
                cy0 = cell_rect[1] * scale
                cx1 = cell_rect[2] * scale
                cy1 = cell_rect[3] * scale
                # Assign text boxes whose center falls inside this cell
                for tb in text_boxes:
                    if cx0 <= tb["cx"] <= cx1 and cy0 <= tb["cy"] <= cy1:
                        grid[row_idx][col_idx].append((tb["cy"], tb["cx"], tb["text"]))

        # Sort tokens within cell top-to-bottom, left-to-right; join with space
        flat_grid: list[list[str]] = []
        for row in grid:
            new_row = []
            for cell_tokens in row:
                cell_tokens.sort(key=lambda x: (x[0], x[1]))
                new_row.append(_clean(" ".join(t[2] for t in cell_tokens)))
            flat_grid.append(new_row)

        if any(any(c for c in row) for row in flat_grid):
            results.append(flat_grid)

    return results


def _process_tables(tables: list[list[list[str]]], module_name: str,
                    page_num: int, page: fitz.Page | None = None,
                    tables_finder: Any = None) -> tuple[list[FieldTable], list[LayerTable], list[dict]]:
    """Classify and parse tables into field_tables / layer_tables / raw_tables."""
    field_tables: list[FieldTable] = []
    layer_tables: list[LayerTable] = []
    raw_tables: list[dict] = []

    for t_idx, rows in enumerate(tables):
        if len(rows) < 2:
            continue
        header = rows[0]
        kind = _classify_header(header)

        caption = ""
        caption_cn = ""
        caption_code = ""
        if page and tables_finder and t_idx < len(tables_finder.tables):
            bbox = tables_finder.tables[t_idx].bbox
            caption = _find_heading_above(page, bbox)
            m = re.search(r"[（(].*?[：:]?\s*([A-Z_][A-Z0-9_]*)", caption)
            if m:
                caption_code = m.group(1)
            m2 = re.search(r"表\s*[\d\-.]+\s*(.+?)(?:[（(]|$)", caption)
            if m2:
                caption_cn = m2.group(1).strip()

        if kind == "unknown":
            raw_tables.append({
                "page": page_num + 1,
                "caption": caption,
                "header": header,
                "rows": rows[1:],
            })
            continue

        if kind == "field":
            col_map = _map_field_columns(header)
            fields = []
            for row in rows[1:]:
                if all(c == "" for c in row):
                    continue
                fields.append(FieldDef(
                    seq=_get_cell(row, col_map.get("seq")),
                    name_cn=_get_cell(row, col_map.get("name")),
                    code=_get_cell(row, col_map.get("code")),
                    dtype=_get_cell(row, col_map.get("type")),
                    length=_get_cell(row, col_map.get("length")),
                    decimal=_get_cell(row, col_map.get("decimal")),
                    domain=_get_cell(row, col_map.get("domain")),
                    constraint=_get_cell(row, col_map.get("constraint")),
                    note=_get_cell(row, col_map.get("note")),
                ))
            if fields:
                field_tables.append(FieldTable(
                    module=module_name,
                    table_name_cn=caption_cn or f"page{page_num+1}_table",
                    table_code=caption_code,
                    caption_raw=caption,
                    section_path=[f"Page {page_num+1}"],
                    fields=fields,
                ))
        elif kind == "layer":
            col_map = _map_layer_columns(header)
            layer_rows = []
            for row in rows[1:]:
                if all(c == "" for c in row):
                    continue
                layer_rows.append(LayerRow(
                    seq=_get_cell(row, col_map.get("seq")),
                    layer_name=_get_cell(row, col_map.get("layer_name")),
                    feature=_get_cell(row, col_map.get("layer_name")),
                    geometry=_get_cell(row, col_map.get("geometry")),
                    table_code=_get_cell(row, col_map.get("table_code")),
                    constraint=_get_cell(row, col_map.get("constraint")),
                    note=_get_cell(row, col_map.get("note")),
                ))
            if layer_rows:
                layer_tables.append(LayerTable(
                    module=module_name,
                    caption_raw=caption,
                    section_path=[f"Page {page_num+1}"],
                    rows=layer_rows,
                ))

    return field_tables, layer_tables, raw_tables


def _find_heading_above(page: fitz.Page, table_bbox) -> str:
    """Try to find a heading/caption text above the table bounding box."""
    blocks = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)["blocks"]
    candidates = []
    table_top = table_bbox[1]
    for b in blocks:
        if b["type"] != 0:
            continue
        for line in b.get("lines", []):
            y = line["bbox"][3]
            if y < table_top and (table_top - y) < 80:
                text = "".join(span["text"] for span in line["spans"]).strip()
                if text and ("表" in text or "Table" in text):
                    candidates.append((y, text))
    if candidates:
        candidates.sort(key=lambda x: -x[0])
        return candidates[0][1]
    return ""


# --- PLACEHOLDER_EXTRACT ---


def extract(pdf_path: str | Path, module_name: str) -> dict[str, list]:
    """Extract field_tables and layer_tables from a PDF standard document.

    Tries native text extraction first; falls back to OCR for garbled PDFs.
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    doc = fitz.open(str(pdf_path))
    all_field_tables: list[FieldTable] = []
    all_layer_tables: list[LayerTable] = []
    all_raw_tables: list[dict] = []

    # Detect if PDF text is garbled by sampling first few pages with tables
    use_ocr = False
    for page_num in range(min(len(doc), 15)):
        page = doc[page_num]
        tables_finder = page.find_tables()
        if tables_finder.tables:
            sample_rows = tables_finder.tables[0].extract()
            sample_text = " ".join(
                c for row in sample_rows[:3] for c in row if c)
            if _is_garbled(sample_text):
                use_ocr = True
                logger.info("Garbled text detected on page %d, switching to OCR",
                            page_num + 1)
            break

    for page_num in range(len(doc)):
        page = doc[page_num]
        tables_finder = page.find_tables()
        if not tables_finder.tables:
            continue

        if use_ocr:
            tables = _ocr_page_tables(page)
        else:
            tables = []
            for tab in tables_finder.tables:
                rows = [[_clean(c) for c in row] for row in tab.extract()]
                if rows:
                    tables.append(rows)

        ft, lt, raw = _process_tables(
            tables, module_name, page_num,
            page=page, tables_finder=tables_finder)
        all_field_tables.extend(ft)
        all_layer_tables.extend(lt)
        all_raw_tables.extend(raw)

    doc.close()
    logger.info("PDF extracted: %d field_tables, %d layer_tables, %d raw_tables from %s (ocr=%s)",
                len(all_field_tables), len(all_layer_tables), len(all_raw_tables),
                pdf_path.name, use_ocr)
    return {
        "field_tables": [asdict(ft) for ft in all_field_tables],
        "layer_tables": [asdict(lt) for lt in all_layer_tables],
        "raw_tables": all_raw_tables,
    }
