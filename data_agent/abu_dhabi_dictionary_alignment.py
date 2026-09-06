"""Align Abu Dhabi source discovery metadata with supplied data dictionaries.

The alignment is intentionally evidence-oriented.  An exact table-name match
does not turn an older dictionary page into runtime truth; it records how much
of the current discovered schema is supported by documentation so semantic
review can promote assets without guessing from physical identifiers.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

_MARKDOWN_TABLE_ROW_RE = re.compile(r"^\|(?P<cells>.*)\|\s*$")
_MARKDOWN_DIVIDER_CELL_RE = re.compile(r"^:?-{3,}:?$")
_LIVEABILITY_TITLE_RE = re.compile(r"^#\s+(?P<table>[^\n]+?)\s+-\s+", re.MULTILINE)
_MAKANI_TITLE_RE = re.compile(r"^#\s+`?(?P<table>[A-Za-z0-9_]+)`?\s*[—-]\s*(?P<label>[^\n]+)", re.MULTILINE)
_LIVEABILITY_DESCRIPTION_RE = re.compile(
    r"^##\s+这张表是什么\s*$\s*(?P<description>.+?)(?:\n\s*\n|\n##\s)",
    re.MULTILINE | re.DOTALL,
)
_MAKANI_DESCRIPTION_RE = re.compile(
    r"\*\*是什么\*\*(?:\s*[（(][^）)\n]+[）)])?\s*：\s*"
    r"(?P<description>.+?)(?:\n\s*\n|\n\*\*)",
    re.DOTALL,
)
_MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]*\)")
# Underscores are valid and common physical-field characters.  Removing them
# here turns e.g. ``district_id`` into a different field name.
_MARKDOWN_EMPHASIS_RE = re.compile(r"[*`]")


def _normalise_table_name(value: str) -> str:
    return str(value or "").strip().rsplit(".", 1)[-1].casefold()


def _clean_markdown(value: str) -> str:
    value = _MARKDOWN_LINK_RE.sub(r"\1", value)
    value = _MARKDOWN_EMPHASIS_RE.sub("", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def _markdown_rows(text: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for line in text.splitlines():
        match = _MARKDOWN_TABLE_ROW_RE.match(line.strip())
        if not match:
            continue
        cells = [_clean_markdown(cell) for cell in match.group("cells").split("|")]
        if not cells or all(not cell for cell in cells):
            continue
        if all(_MARKDOWN_DIVIDER_CELL_RE.fullmatch(cell.replace(" ", "")) for cell in cells):
            continue
        rows.append(cells)
    return rows


def _field_definitions(text: str) -> dict[str, str]:
    """Extract field descriptions from both supplied dictionary Markdown styles."""

    fields: dict[str, str] = {}
    for row in _markdown_rows(text):
        if len(row) < 3:
            continue
        first = row[0].strip()
        if not first or first.casefold() in {"字段", "字段名", "field", "关联表", "子表"}:
            continue
        # Some source pages collapse multiple all-null fields with slash syntax.
        names = [part.strip().strip("`") for part in re.split(r"\s*/\s*", first)]
        if not all(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name or "") for name in names):
            continue
        description = row[-1]
        for name in names:
            fields[name.casefold()] = description
    return fields


def _document_table_and_label(path: Path, text: str, source_kind: str) -> tuple[str, str]:
    if source_kind == "liveability":
        match = _LIVEABILITY_TITLE_RE.search(text)
        table = match.group("table").strip() if match else path.name.split(" - ", 1)[0]
        return table, table.replace("_", " ")
    match = _MAKANI_TITLE_RE.search(text)
    if match:
        return match.group("table").strip(), _clean_markdown(match.group("label"))
    return path.stem, path.stem.replace("_", " ")


def _description(text: str, source_kind: str) -> str:
    pattern = _LIVEABILITY_DESCRIPTION_RE if source_kind == "liveability" else _MAKANI_DESCRIPTION_RE
    match = pattern.search(text)
    return _clean_markdown(match.group("description")) if match else ""


def read_dictionary_documents(root: Path, *, source_kind: str) -> dict[str, list[dict[str, Any]]]:
    """Return all pages indexed by documented physical table name.

    Duplicate pages are preserved rather than silently overwritten.  Their
    presence is itself useful review evidence for a source with historical and
    planning variants of the same asset.
    """

    documents: dict[str, list[dict[str, Any]]] = {}
    for path in sorted(root.rglob("*.md")):
        if path.name.startswith("00_"):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        table, label = _document_table_and_label(path, text, source_kind)
        key = _normalise_table_name(table)
        if not key or key in {"readme", "relationships", "index"}:
            continue
        documents.setdefault(key, []).append(
            {
                "document_table": table,
                "document_label": label,
                "path": str(path),
                "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "description": _description(text, source_kind),
                "fields": _field_definitions(text),
            }
        )
    return documents


def _select_document(
    candidates: list[dict[str, Any]],
    discovered_fields: set[str],
) -> tuple[dict[str, Any] | None, int]:
    if not candidates:
        return None, 0
    ranked = sorted(
        (
            len(discovered_fields & set(candidate["fields"])),
            len(candidate["fields"]),
            str(candidate["path"]),
            candidate,
        )
        for candidate in candidates
    )
    best = ranked[-1]
    return best[-1], int(best[0])


def build_dictionary_alignment(
    *,
    catalog_path: Path,
    dictionary_root: Path,
    source_kind: str,
) -> dict[str, Any]:
    """Compare a frozen metadata-only technical catalog to dictionary pages."""

    if source_kind not in {"liveability", "makani"}:
        raise ValueError("source_kind must be liveability or makani")
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    if catalog.get("schema") != "gda.technical-semantic-catalog.v1":
        raise ValueError("technical catalog schema is unsupported")
    documents = read_dictionary_documents(dictionary_root, source_kind=source_kind)
    resources: list[dict[str, Any]] = []
    status_counts: Counter[str] = Counter()
    for resource in catalog.get("resources") or []:
        physical_table = str(resource.get("physical_table") or "")
        discovered_fields = {
            str(field.get("physical_field") or "").casefold()
            for field in resource.get("fields") or []
            if str(field.get("physical_field") or "").strip()
        }
        candidate_docs = documents.get(_normalise_table_name(physical_table), [])
        document, field_match_count = _select_document(candidate_docs, discovered_fields)
        field_coverage = (
            round(field_match_count / len(discovered_fields), 6) if discovered_fields else None
        )
        if document is None:
            status = "no_exact_dictionary_page"
        elif field_match_count == len(discovered_fields):
            status = "exact_table_and_field_alignment"
        elif field_match_count:
            status = "exact_table_partial_field_alignment"
        else:
            status = "exact_table_without_field_alignment"
        status_counts[status] += 1
        resources.append(
            {
                "physical_table": physical_table,
                "catalog_semantic_status": resource.get("semantic_status"),
                "field_count": len(discovered_fields),
                "dictionary_alignment_status": status,
                "dictionary_candidate_count": len(candidate_docs),
                "matched_field_count": field_match_count,
                "matched_field_coverage": field_coverage,
                "dictionary_document": (
                    {
                        "table": document["document_table"],
                        "label": document["document_label"],
                        "path": document["path"],
                        "sha256": document["sha256"],
                        "description": document["description"],
                        "field_descriptions": {
                            field: description
                            for field, description in document["fields"].items()
                            if field in discovered_fields
                        },
                    }
                    if document
                    else None
                ),
            }
        )
    source_evidence = catalog.get("source_evidence") or {}
    return {
        "schema": "gda.abu-dhabi-dictionary-alignment.v1",
        "source_kind": source_kind,
        "source_evidence": {
            "source_id": source_evidence.get("source_id"),
            "database_name": source_evidence.get("database_name"),
            "discovery_fingerprint": source_evidence.get("discovery_fingerprint"),
            "catalog_path": str(catalog_path),
            "catalog_sha256": hashlib.sha256(catalog_path.read_bytes()).hexdigest(),
        },
        "dictionary_evidence": {
            "root": str(dictionary_root),
            "document_count": sum(len(items) for items in documents.values()),
            "unique_documented_table_count": len(documents),
            "dictionary_is_runtime_authority": False,
            "runtime_metadata_is_authoritative": True,
        },
        "coverage": {
            "resource_count": len(resources),
            "dictionary_alignment_status_counts": dict(sorted(status_counts.items())),
            "exact_table_match_count": len(resources) - status_counts["no_exact_dictionary_page"],
            "full_field_alignment_count": status_counts["exact_table_and_field_alignment"],
            "partial_field_alignment_count": status_counts[
                "exact_table_partial_field_alignment"
            ],
        },
        "claim_boundary": {
            "all_resources_assessed": True,
            "dictionary_alignment_is_not_business_semantic_approval": True,
            "business_asset_promotion_requires_review": True,
            "source_rows_persisted": False,
        },
        "resources": resources,
    }


def write_alignment(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
