"""Build source-bound, field-level evidence from the customer dictionaries.

The alignment artifacts are the durable copy of the supplied dictionary
evidence.  This module deliberately does not read source rows or the original
Downloads directory.  It only rebinds that evidence to the current frozen
technical catalog after checking that table and field identities are
schema-compatible.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from pathlib import Path
from typing import Any


DICTIONARY_EVIDENCE_SCHEMA = "gda.abu-dhabi-dictionary-evidence-index.v1"
TABLE_SUPPORT_STATUSES = {
    "exact_table_and_field_alignment": "dictionary_exact_supported",
    "exact_table_partial_field_alignment": "dictionary_partial_supported",
    "exact_table_without_field_alignment": "dictionary_unmatched",
    "no_exact_dictionary_page": "no_dictionary_evidence",
}
FIELD_SUPPORT_STATUSES = {
    "exact": "dictionary_exact_supported",
    "table_partial": "dictionary_partial_supported",
    "unmatched": "dictionary_unmatched",
    "none": "no_dictionary_evidence",
}


class DictionaryEvidenceError(ValueError):
    """Raised when dictionary evidence cannot be safely rebound."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _table_fields(catalog: dict[str, Any]) -> dict[str, set[str]]:
    return {
        str(resource.get("physical_table")): {
            str(field.get("physical_field")).casefold()
            for field in resource.get("fields") or []
            if str(field.get("physical_field") or "").strip()
        }
        for resource in catalog.get("resources") or []
        if str(resource.get("physical_table") or "").strip()
    }


def _source_compatibility(
    catalog: dict[str, Any], alignment: dict[str, Any]
) -> tuple[str, dict[str, Any]]:
    catalog_source = catalog.get("source_evidence") or {}
    alignment_source = alignment.get("source_evidence") or {}
    catalog_tables = _table_fields(catalog)
    alignment_tables = {
        str(item.get("physical_table")): {
            str(field).casefold()
            for field in ((item.get("dictionary_document") or {}).get("field_descriptions") or {})
        }
        for item in alignment.get("resources") or []
        if str(item.get("physical_table") or "").strip()
    }
    alignment_table_names = {
        str(item.get("physical_table"))
        for item in alignment.get("resources") or []
        if str(item.get("physical_table") or "").strip()
    }
    if catalog_source.get("discovery_fingerprint") == alignment_source.get(
        "discovery_fingerprint"
    ):
        return "exact_fingerprint", {
            "table_set_equal": catalog_tables.keys() == alignment_table_names,
            "field_sets_checked": False,
        }
    if set(catalog_tables) != alignment_table_names:
        raise DictionaryEvidenceError("dictionary_alignment_catalog_table_set_mismatch")
    # The alignment only stores matched field names, so compare those names
    # against the current catalog as a conservative compatibility check. A
    # table with a partial dictionary page is allowed to have fewer matches.
    for resource in alignment.get("resources") or []:
        table = str(resource.get("physical_table") or "")
        current_fields = catalog_tables[table]
        document = resource.get("dictionary_document") or {}
        documented = {
            str(field).casefold() for field in (document.get("field_descriptions") or {})
        }
        if not documented <= current_fields:
            raise DictionaryEvidenceError(
                f"dictionary_alignment_catalog_field_set_mismatch:{table}"
            )
    return "schema_equivalent_rebind", {
        "table_set_equal": True,
        "field_sets_checked": True,
        "alignment_discovery_fingerprint": alignment_source.get("discovery_fingerprint"),
        "catalog_discovery_fingerprint": catalog_source.get("discovery_fingerprint"),
    }


def build_dictionary_evidence_index(
    *,
    catalog: dict[str, Any],
    alignment: dict[str, Any],
    catalog_path: Path,
    alignment_path: Path,
    source_kind: str,
) -> dict[str, Any]:
    """Create a field-level evidence index bound to the supplied catalog."""

    if catalog.get("schema") != "gda.technical-semantic-catalog.v1":
        raise DictionaryEvidenceError("technical_catalog_schema_unsupported")
    if alignment.get("schema") != "gda.abu-dhabi-dictionary-alignment.v1":
        raise DictionaryEvidenceError("dictionary_alignment_schema_unsupported")
    if alignment.get("source_kind") != source_kind:
        raise DictionaryEvidenceError("dictionary_alignment_source_kind_mismatch")
    compatibility, compatibility_details = _source_compatibility(catalog, alignment)
    alignment_by_table = {
        str(item.get("physical_table")): item
        for item in alignment.get("resources") or []
        if str(item.get("physical_table") or "").strip()
    }
    table_counts: Counter[str] = Counter()
    field_counts: Counter[str] = Counter()
    tables: list[dict[str, Any]] = []
    for resource in sorted(
        catalog.get("resources") or [], key=lambda item: str(item.get("physical_table") or "").casefold()
    ):
        table = str(resource.get("physical_table") or "")
        alignment_item = alignment_by_table.get(table)
        alignment_status = str(
            (alignment_item or {}).get("dictionary_alignment_status") or "no_exact_dictionary_page"
        )
        table_status = TABLE_SUPPORT_STATUSES.get(alignment_status, "no_dictionary_evidence")
        table_counts[table_status] += 1
        document = (alignment_item or {}).get("dictionary_document") or {}
        field_descriptions = {
            str(name).casefold(): str(description or "")
            for name, description in (document.get("field_descriptions") or {}).items()
        }
        fields: list[dict[str, Any]] = []
        for field in sorted(
            resource.get("fields") or [],
            key=lambda item: str(item.get("physical_field") or "").casefold(),
        ):
            physical = str(field.get("physical_field") or "")
            key = physical.casefold()
            if not alignment_item:
                support_status = FIELD_SUPPORT_STATUSES["none"]
            elif key in field_descriptions and alignment_status == "exact_table_and_field_alignment":
                support_status = FIELD_SUPPORT_STATUSES["exact"]
            elif key in field_descriptions and alignment_status == "exact_table_partial_field_alignment":
                support_status = FIELD_SUPPORT_STATUSES["table_partial"]
            elif alignment_status == "no_exact_dictionary_page":
                support_status = FIELD_SUPPORT_STATUSES["none"]
            else:
                support_status = FIELD_SUPPORT_STATUSES["unmatched"]
            field_counts[support_status] += 1
            fields.append(
                {
                    "physical_field": physical,
                    "support_status": support_status,
                    "dictionary_description": field_descriptions.get(key),
                    "documented_field": key in field_descriptions,
                }
            )
        tables.append(
            {
                "physical_table": table,
                "support_status": table_status,
                "alignment_status": alignment_status,
                "matched_field_count": alignment_item.get("matched_field_count") if alignment_item else 0,
                "field_count": len(fields),
                "matched_field_coverage": alignment_item.get("matched_field_coverage") if alignment_item else None,
                "dictionary_document": (
                    {
                        "table": document.get("table"),
                        "label": document.get("label"),
                        "description": document.get("description"),
                        "path": document.get("path"),
                        "sha256": document.get("sha256"),
                    }
                    if document
                    else None
                ),
                "fields": fields,
            }
        )
    source = catalog.get("source_evidence") or {}
    return {
        "schema": DICTIONARY_EVIDENCE_SCHEMA,
        "source_kind": source_kind,
        "generated_from": {
            "catalog_path": str(catalog_path),
            "catalog_sha256": _sha256(catalog_path),
            "alignment_path": str(alignment_path),
            "alignment_sha256": _sha256(alignment_path),
        },
        "source_evidence": {
            "source_id": source.get("source_id"),
            "database_name": source.get("database_name"),
            "discovery_fingerprint": source.get("discovery_fingerprint"),
            "profile_fingerprint": source.get("profile_fingerprint"),
        },
        "compatibility": {
            "mode": compatibility,
            **compatibility_details,
        },
        "claim_boundary": {
            "dictionary_is_evidence_not_runtime_authority": True,
            "does_not_confirm_metric_additivity": True,
            "does_not_confirm_relationships": True,
            "does_not_confirm_time_or_spatial_semantics": True,
            "does_not_confirm_sensitivity_or_execution_eligibility": True,
            "source_rows_persisted": False,
        },
        "coverage": {
            "table_count": len(tables),
            "field_count": sum(item["field_count"] for item in tables),
            "table_support_status_counts": dict(sorted(table_counts.items())),
            "field_support_status_counts": dict(sorted(field_counts.items())),
            "dictionary_exact_supported_field_count": field_counts["dictionary_exact_supported"],
            "dictionary_partial_supported_field_count": field_counts["dictionary_partial_supported"],
            "dictionary_unmatched_field_count": field_counts["dictionary_unmatched"],
            "no_dictionary_evidence_field_count": field_counts["no_dictionary_evidence"],
        },
        "tables": tables,
    }


__all__ = [
    "DICTIONARY_EVIDENCE_SCHEMA",
    "DictionaryEvidenceError",
    "build_dictionary_evidence_index",
]
