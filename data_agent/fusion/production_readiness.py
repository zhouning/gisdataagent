"""Production-readiness metadata contracts for MMFE source datasets."""

from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any


PRODUCTION_READINESS_SCHEMA = "mmfe.production_readiness.v1"
PRODUCTION_READINESS_VERSION = "0.1"

REQUIRED_PRODUCTION_FIELDS = (
    "source_id",
    "role",
    "source_path",
    "authority",
    "authority_level",
    "license",
    "access_rights",
    "update_date",
    "lineage",
    "crs",
    "scale_or_resolution",
    "official_standard_version",
    "security_classification",
)

VALID_AUTHORITY_LEVELS = {
    "national",
    "provincial",
    "municipal",
    "county",
    "department",
    "official_platform",
}
VALID_ACCESS_RIGHTS = {"open", "authorized", "restricted"}
VALID_SECURITY_CLASSIFICATIONS = {"public", "internal", "confidential", "restricted", "secret"}


def build_production_readiness_contract(
    manifest: dict,
    *,
    sources: list[dict] | None = None,
    timestamp: str | None = None,
) -> dict:
    """Build a compact production-readiness contract from source metadata."""
    if not isinstance(manifest, dict):
        raise ValueError("semantic product manifest must be a JSON object")

    source_inputs = _metadata_sources_from_manifest(manifest) if sources is None else sources
    source_items = [
        _normalise_source_metadata(item, index)
        for index, item in enumerate(list(source_inputs or []))
        if isinstance(item, dict)
    ]
    findings = [_evaluate_source(item) for item in source_items]
    blocking_findings = [item for item in findings if item["status"] != "pass"]

    return {
        "schema": PRODUCTION_READINESS_SCHEMA,
        "version": PRODUCTION_READINESS_VERSION,
        "created_at": timestamp or datetime.now(timezone.utc).isoformat(),
        "product_id": manifest.get("product_id"),
        "source_count": len(source_items),
        "summary": {
            "production_metadata_ready": bool(source_items) and not blocking_findings,
            "source_count": len(source_items),
            "ready_source_count": sum(1 for item in findings if item["status"] == "pass"),
            "blocked_source_count": len(blocking_findings),
            "missing_field_count": sum(len(item.get("missing_fields") or []) for item in findings),
            "invalid_field_count": sum(len(item.get("invalid_fields") or []) for item in findings),
            "synthetic_source_count": sum(1 for item in source_items if item.get("synthetic")),
            "not_for_production_source_count": sum(1 for item in source_items if item.get("not_for_production")),
        },
        "sources": source_items,
        "findings": findings,
    }


def validate_production_readiness_contract(payload: dict) -> dict:
    """Validate the production-readiness contract surface."""
    errors: list[str] = []
    if not isinstance(payload, dict):
        return {"valid": False, "errors": ["payload must be a JSON object"]}
    if payload.get("schema") != PRODUCTION_READINESS_SCHEMA:
        errors.append(f"schema must be {PRODUCTION_READINESS_SCHEMA}")
    if not payload.get("product_id"):
        errors.append("product_id is required")
    if not isinstance(payload.get("sources"), list):
        errors.append("sources must be a list")
    if not isinstance(payload.get("findings"), list):
        errors.append("findings must be a list")
    summary = payload.get("summary") or {}
    if not isinstance(summary.get("production_metadata_ready"), bool):
        errors.append("summary.production_metadata_ready must be boolean")
    return {"valid": not errors, "errors": errors}


def production_readiness_from_manifest(manifest: dict) -> dict:
    """Return embedded production-readiness metadata, or build it from source metadata."""
    if not isinstance(manifest, dict):
        return {}
    bundle = manifest.get("mmfe_bundle") if isinstance(manifest.get("mmfe_bundle"), dict) else {}
    embedded = bundle.get("production_readiness")
    if isinstance(embedded, dict):
        return embedded
    source_metadata = _metadata_sources_from_manifest(manifest)
    if source_metadata:
        return build_production_readiness_contract(manifest, sources=source_metadata)
    return {}


def standard_source_production_metadata_from_registry(registry: dict) -> list[dict]:
    """Map enriched standard-source registry entries to production metadata rows."""
    if not isinstance(registry, dict):
        raise ValueError("standard source registry must be a JSON object")
    rows = []
    for index, entry in enumerate(registry.get("entries") or []):
        if not isinstance(entry, dict):
            continue
        rows.append(_standard_source_metadata_row(entry, index))
    return rows


def source_production_metadata_from_records(
    records: list[dict],
    *,
    defaults: dict | None = None,
) -> list[dict]:
    """Map authoritative source metadata records to production metadata rows."""
    if not isinstance(records, list):
        raise ValueError("source metadata records must be a list")
    base_defaults = dict(defaults or {})
    rows = []
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            continue
        rows.append(_source_metadata_row_from_record(record, index, base_defaults))
    return rows


def _metadata_sources_from_manifest(manifest: dict) -> list[dict]:
    bundle = manifest.get("mmfe_bundle") if isinstance(manifest.get("mmfe_bundle"), dict) else {}
    sources = []
    for item in list(bundle.get("source_production_metadata") or []):
        if isinstance(item, dict):
            sources.append(item)
    for item in list(manifest.get("source_production_metadata") or []):
        if isinstance(item, dict):
            sources.append(item)
    for records in (
        bundle.get("source_metadata_records"),
        bundle.get("authoritative_source_records"),
        manifest.get("source_metadata_records"),
        manifest.get("authoritative_source_records"),
    ):
        if isinstance(records, list):
            sources.extend(source_production_metadata_from_records(records))
    for registry in (
        bundle.get("standard_source_registry"),
        manifest.get("standard_source_registry"),
    ):
        if isinstance(registry, dict):
            sources.extend(standard_source_production_metadata_from_registry(registry))

    deduped = _dedupe_source_metadata(sources)
    if deduped:
        return deduped

    legacy_sources = []
    for index, item in enumerate(list(manifest.get("sources") or [])):
        if not isinstance(item, dict):
            continue
        source = dict(item)
        source.setdefault("source_id", item.get("source_id") or item.get("id") or f"source-{index + 1}")
        source.setdefault("source_path", item.get("path") or item.get("source_path") or "")
        source.setdefault("role", item.get("role") or item.get("data_type") or "")
        legacy_sources.append(source)
    return legacy_sources


def _source_metadata_row_from_record(record: dict, index: int, defaults: dict) -> dict:
    source_id = _first_present(
        record,
        ("source_id", "resource_id", "data_id", "layer_name", "data_name"),
        default=f"source-{index + 1}",
    )
    role = _first_present(record, ("role", "twm_role", "layer_role", "layer_name", "data_type"), default=source_id)
    authority = _first_present(record, ("authority", "pro_unit_name", "producer", "check_unit_name"), defaults)
    update_date = _normalise_contract_date(
        _first_present(record, ("update_date", "release_date", "product_date", "import_time"), defaults)
    )
    synthetic = _to_bool(_first_present(record, ("synthetic", "is_synthetic"), defaults, default=False))
    not_for_production = _to_bool(
        _first_present(record, ("not_for_production", "not_for_production_gap"), defaults, default=False)
    )
    return {
        "source_id": str(source_id),
        "role": str(role),
        "source_path": _first_present(record, ("source_path", "path", "uri", "url", "data_path"), defaults),
        "authority": authority,
        "authority_level": _authority_level_for_record(record, defaults),
        "license": _first_present(
            record,
            ("license", "license_name", "usage_license", "authorization"),
            defaults,
            default="authorized_government_use" if authority else "",
        ),
        "access_rights": _access_rights_for_record(record, defaults),
        "update_date": update_date,
        "lineage": _lineage_for_record(record, defaults),
        "crs": _crs_for_record(record, defaults),
        "scale_or_resolution": _first_present(
            record,
            ("scale_or_resolution", "scale", "resolution", "spatial_resolution", "coordinate_unit"),
            defaults,
        ),
        "official_standard_version": _first_present(
            record,
            ("official_standard_version", "standard_version", "source_standard_version", "standard_identifier"),
            defaults,
        ),
        "security_classification": _security_classification_for_record(record, defaults),
        "synthetic": synthetic,
        "not_for_production": not_for_production or synthetic,
        "source_type": _first_present(record, ("source_type", "data_type", "data_format"), defaults),
        "raw_metadata_id": str(_first_present(record, ("data_id", "resource_id", "metadata_id"), default="")),
    }


def _standard_source_metadata_row(entry: dict, index: int) -> dict:
    identifier = str(entry.get("standard_identifier") or f"standard-source-{index + 1}")
    return {
        "source_id": f"standard-source:{identifier}",
        "role": "standard_source",
        "source_type": "standard_source",
        "source_path": entry.get("archive_uri") or entry.get("local_path") or entry.get("official_url") or "",
        "authority": entry.get("authority") or entry.get("publisher") or "",
        "authority_level": _standard_source_authority_level(entry),
        "license": entry.get("license") or _standard_source_license(entry),
        "access_rights": entry.get("access_rights") or _standard_source_access_rights(entry),
        "update_date": entry.get("implementation_date") or entry.get("publication_date") or "",
        "lineage": _standard_source_lineage(entry),
        "crs": entry.get("crs") or "not_applicable",
        "scale_or_resolution": entry.get("scale_or_resolution") or "not_applicable",
        "official_standard_version": identifier,
        "security_classification": entry.get("security_classification") or "public",
        "synthetic": False,
        "not_for_production": _standard_source_not_for_production(entry),
        "standard_identifier": identifier,
        "archive_uri": entry.get("archive_uri") or "",
        "checksum_sha256": entry.get("checksum_sha256") or "",
        "extraction_status": entry.get("extraction_status") or "",
        "citation_anchor_count": entry.get("citation_anchor_count") or entry.get("clause_anchor_count") or 0,
    }


def _dedupe_source_metadata(items: list[dict]) -> list[dict]:
    deduped = []
    seen = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        source = dict(item)
        key = str(source.get("source_id") or source.get("standard_identifier") or source.get("source_path") or "")
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        deduped.append(source)
    return deduped


def _normalise_source_metadata(item: dict, index: int) -> dict:
    source = dict(item)
    source.setdefault("source_id", source.get("id") or f"source-{index + 1}")
    source.setdefault("source_path", source.get("path") or source.get("source_path") or "")
    source.setdefault("role", source.get("role") or source.get("data_type") or "")
    source["synthetic"] = _to_bool(source.get("synthetic"))
    source["not_for_production"] = _to_bool(source.get("not_for_production"))
    return source


def _standard_source_authority_level(entry: dict) -> str:
    retrieval_status = str(entry.get("retrieval_status") or "")
    platform = str(entry.get("official_platform") or "")
    if retrieval_status.startswith("official_") or platform:
        return "official_platform"
    return ""


def _standard_source_license(entry: dict) -> str:
    if entry.get("license"):
        return str(entry["license"])
    if entry.get("official_url"):
        return "official_standard_public_access_or_authorized_use"
    return ""


def _standard_source_access_rights(entry: dict) -> str:
    access_mode = str(entry.get("access_mode") or "")
    if access_mode in {"online_preview_and_download", "archived_fulltext"}:
        return "open"
    if entry.get("archive_uri") or entry.get("official_url"):
        return "authorized"
    return ""


def _standard_source_lineage(entry: dict) -> str:
    parts = [
        entry.get("official_platform"),
        entry.get("official_url"),
        entry.get("archive_uri"),
        entry.get("checksum_sha256"),
        entry.get("extraction_status"),
    ]
    text = " | ".join(str(part) for part in parts if part)
    return text or str(entry.get("evidence_note_zh") or "")


def _standard_source_not_for_production(entry: dict) -> bool:
    if _to_bool(entry.get("not_for_production_gap")):
        return True
    return not (
        entry.get("official_url")
        and entry.get("archive_uri")
        and entry.get("checksum_sha256")
        and entry.get("extraction_status") == "extracted"
    )


def _first_present(
    record: dict,
    keys: tuple[str, ...],
    defaults: dict | None = None,
    default: Any = "",
) -> Any:
    for key in keys:
        value = record.get(key)
        if not _blank(value):
            return value
    for key in keys:
        value = (defaults or {}).get(key)
        if not _blank(value):
            return value
    return default


def _authority_level_for_record(record: dict, defaults: dict) -> str:
    explicit = _first_present(record, ("authority_level", "authority_rank"), defaults)
    if explicit:
        return str(explicit)
    authority_text = str(_first_present(record, ("authority", "pro_unit_name", "producer", "check_unit_name"), defaults))
    source_type = str(_first_present(record, ("source_type", "source_currency"), defaults))
    text = f"{authority_text} {source_type}"
    if any(token in text for token in ("国家", "国务院", "自然资源部", "国家标准")):
        return "national"
    if "省" in text:
        return "provincial"
    if any(token in text for token in ("市", "区县", "县", "自然资源主管部门", "主管部门")):
        return "department"
    return ""


def _access_rights_for_record(record: dict, defaults: dict) -> str:
    explicit = _first_present(record, ("access_rights", "access_mode"), defaults)
    if explicit in VALID_ACCESS_RIGHTS:
        return str(explicit)
    text = str(
        _first_present(
            record,
            ("share_type", "is_shareable", "is_opentosociety", "security_order"),
            defaults,
        )
    ).lower()
    if any(token in text for token in ("open", "public", "公开", "是", "true")):
        return "open"
    if any(token in text for token in ("restricted", "confidential", "secret", "内部", "否", "false")):
        return "restricted"
    return str(_first_present(record, ("access_rights",), defaults, default="authorized"))


def _lineage_for_record(record: dict, defaults: dict) -> str:
    explicit = _first_present(record, ("lineage", "source_lineage", "lineage_note"), defaults)
    if explicit:
        return str(explicit)
    parts = [
        _first_present(record, ("producer", "authority", "pro_unit_name"), defaults),
        _first_present(record, ("source_type", "source_currency"), defaults),
        _first_present(record, ("receive_mode", "receive_batch"), defaults),
        _first_present(record, ("quality_des", "data_des"), defaults),
    ]
    return " | ".join(str(part) for part in parts if not _blank(part))


def _crs_for_record(record: dict, defaults: dict) -> str:
    crs = _first_present(record, ("crs", "projection", "wkid", "epsg"), defaults)
    if _blank(crs):
        return ""
    text = str(crs)
    if text.isdigit():
        return f"EPSG:{text}"
    return text


def _security_classification_for_record(record: dict, defaults: dict) -> str:
    explicit = _first_present(record, ("security_classification",), defaults)
    if explicit in VALID_SECURITY_CLASSIFICATIONS:
        return str(explicit)
    text = str(_first_present(record, ("security_order", "classification", "security_level"), defaults)).strip()
    if not text:
        return str(defaults.get("security_classification") or "internal")
    if text in {"公开", "public"}:
        return "public"
    if text in {"内部", "internal"}:
        return "internal"
    if "机密" in text or "secret" in text.lower():
        return "secret"
    if "秘密" in text or "restricted" in text.lower():
        return "restricted"
    if "confidential" in text.lower() or "保密" in text:
        return "confidential"
    return str(defaults.get("security_classification") or "internal")


def _normalise_contract_date(value: Any) -> str:
    text = str(value or "").strip()
    if re.match(r"^\d{8}$", text):
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    return text


def _evaluate_source(source: dict) -> dict:
    missing_fields = [
        field
        for field in REQUIRED_PRODUCTION_FIELDS
        if _blank(source.get(field))
    ]
    invalid_fields = []
    if source.get("authority_level") and source.get("authority_level") not in VALID_AUTHORITY_LEVELS:
        invalid_fields.append("authority_level")
    if source.get("access_rights") and source.get("access_rights") not in VALID_ACCESS_RIGHTS:
        invalid_fields.append("access_rights")
    if (
        source.get("security_classification")
        and source.get("security_classification") not in VALID_SECURITY_CLASSIFICATIONS
    ):
        invalid_fields.append("security_classification")
    if source.get("update_date") and not _looks_like_date(source.get("update_date")):
        invalid_fields.append("update_date")
    if source.get("synthetic"):
        invalid_fields.append("synthetic")
    if source.get("not_for_production"):
        invalid_fields.append("not_for_production")

    status = "pass" if not missing_fields and not invalid_fields else "fail"
    return {
        "source_id": source.get("source_id"),
        "role": source.get("role"),
        "source_path": source.get("source_path"),
        "status": status,
        "missing_fields": missing_fields,
        "invalid_fields": invalid_fields,
    }


def _blank(value: Any) -> bool:
    return value is None or str(value).strip() == ""


def _looks_like_date(value: Any) -> bool:
    text = str(value or "").strip()
    if len(text) < 10:
        return False
    try:
        datetime.fromisoformat(text[:10])
    except ValueError:
        return False
    return True


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "y", "是"}
