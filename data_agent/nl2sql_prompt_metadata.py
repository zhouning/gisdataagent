"""Render registered field annotations without repeating identical facts."""
from __future__ import annotations


def prompt_business_metadata(value):
    """Omit audit envelopes, preserving all business keys and their values.

    Provenance paths, hashes and superseded annotations remain in the registry.
    A fresh structure is returned so rendering cannot alter a governed record.
    """
    audit_keys = {"provenance", "dictionary_provenance", "public_definition_provenance", "reference_range_provenance",
                  "superseded_annotations"}
    if isinstance(value, dict):
        return {key: prompt_business_metadata(item) for key, item in value.items()
                if key not in audit_keys}
    if isinstance(value, list):
        return [prompt_business_metadata(item) for item in value]
    return value


def field_prompt_description(column: dict) -> str:
    """Remove exact repeated import segments, never approximate definitions."""
    raw = str(column.get("description") or "").strip()
    # The import uses this exact separator between dictionary components.
    parts = [part.strip() for part in raw.split(" | ")]
    return " | ".join(dict.fromkeys(part for part in parts if part))


def field_prompt_annotations(column: dict) -> tuple[list[str], dict]:
    """Preserve business meaning while removing exact presentation duplicates.

    The caller still renders the description, SQL identifier and physical type.
    Provenance remains in the registry for audits; it is not an instruction to
    the model. This function does not select or remove tables or columns.
    """
    name = str(column.get("column_name") or "")
    description = str(column.get("description") or "").strip()
    aliases = list(dict.fromkeys(str(alias) for alias in column.get("aliases") or []
                                if alias and str(alias) not in {name, description}))
    semantics = {key: value for key, value in (column.get("value_semantics") or {}).items()
                 if key not in {"dictionary_provenance", "public_definition_provenance",
                                "superseded_annotations"} and value}
    value_description = semantics.get("value_description")
    if (isinstance(value_description, str) and
            (description == value_description or description.endswith(" | " + value_description))):
        semantics.pop("value_description")
    declared_type = semantics.get("source_declared_format")
    if isinstance(declared_type, str) and declared_type.strip().casefold() == str(column.get("pg_type") or "").strip().casefold():
        semantics.pop("source_declared_format")
    semantics = prompt_business_metadata(semantics)
    return aliases, semantics
