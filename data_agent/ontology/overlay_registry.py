"""Read-only registry for source overlays attached to a domain ontology.

Overlays are generated evidence artifacts, not ontology packages.  This
module deliberately exposes a bounded read model so the ontology workbench
can inspect source coverage without treating technical table names as
published business concepts or mutating the immutable base package.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ARTIFACT_ROOT = REPOSITORY_ROOT / "docs/customer/abu_dhabi_liveability_site_validation"
MAX_PAGE_LIMIT = 200


@dataclass(frozen=True, slots=True)
class OntologyOverlayDescriptor:
    overlay_id: str
    ontology_key: str
    source_key: str
    label: str
    overlay_path: Path
    semantic_path: Path | None
    catalog_path: Path | None


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"overlay artifact must be an object: {path.name}")
    return value


def _source_key(path: Path) -> str:
    marker = "_ontology_"
    if marker not in path.stem:
        return path.stem
    return path.stem.split(marker, 1)[0]


def _ontology_key(payload: dict[str, Any]) -> str | None:
    base = str(payload.get("base_ontology") or "").casefold()
    if "dmt" in base or str(payload.get("overlay_id") or "").startswith("abu-dhabi-"):
        return "abu-dhabi-dmt-gis"
    explicit = str(payload.get("ontology_key") or "").strip()
    return explicit or None


def _active_package_version(ontology_key: str) -> str | None:
    pointer = REPOSITORY_ROOT / "data_agent/ontology/packages/abu_dhabi_dmt_gis/active.json"
    if ontology_key != "abu-dhabi-dmt-gis" or not pointer.is_file():
        return None
    try:
        value = json.loads(pointer.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    version = str(value.get("semantic_version") or "").strip()
    return version or None


def _descriptor_payload(descriptor: OntologyOverlayDescriptor) -> dict[str, Any]:
    overlay = _load(descriptor.overlay_path)
    semantic = _load(descriptor.semantic_path) if descriptor.semantic_path and descriptor.semantic_path.is_file() else {}
    source = overlay.get("source_evidence") or semantic.get("source_binding") or {}
    coverage = overlay.get("coverage") or {}
    catalog = _load(descriptor.catalog_path) if descriptor.catalog_path and descriptor.catalog_path.is_file() else {}
    catalog_coverage = catalog.get("coverage") or {}
    execution_mode = str(source.get("execution_mode") or "")
    ingestion_mode = str(source.get("ingestion_mode") or "").strip() or (
        "virtual_source" if "virtual" in execution_mode.casefold() else None
    )
    persisted = source.get("source_rows_persisted")
    if not isinstance(persisted, bool) and ingestion_mode:
        persisted = ingestion_mode != "virtual_source"
    return {
        "overlay_id": descriptor.overlay_id,
        "ontology_key": descriptor.ontology_key,
        "source_key": descriptor.source_key,
        "label": descriptor.label,
        "status": overlay.get("status"),
        "version": overlay.get("ontology_enrichment_version"),
        "base_ontology": overlay.get("base_ontology"),
        "source": {
            "source_id": source.get("source_id"),
            "database_name": source.get("database_name"),
            "allowed_schemas": list(source.get("allowed_schemas") or []),
            "ingestion_mode": ingestion_mode,
            "execution_mode": source.get("execution_mode"),
            "source_rows_persisted": persisted,
            "discovery_fingerprint": source.get("discovery_fingerprint"),
            "profile_fingerprint": source.get("profile_fingerprint"),
        },
        "binding": {
            "metadata_fingerprint": source.get("discovery_fingerprint"),
            "profile_fingerprint": source.get("profile_fingerprint"),
            "semantic_version": semantic.get("semantic_version"),
            "base_ontology_version": overlay.get("base_ontology_version") or _active_package_version(descriptor.ontology_key),
            "catalog_id": catalog.get("catalog_id"),
            "drift_status": "bound" if source.get("discovery_fingerprint") else "unbound",
        },
        "coverage": coverage,
        "catalog_coverage": catalog_coverage,
        "runtime_role": overlay.get("runtime_role") or {},
        "claim_boundary": {
            "business_semantics_complete": coverage.get("business_semantic_coverage_complete") is True,
            "technical_metadata_complete": coverage.get("technical_semantic_coverage_complete") is True,
            "unreviewed_assets_executable": False,
        },
    }


def _candidate_descriptors(artifact_root: Path) -> list[OntologyOverlayDescriptor]:
    descriptors: list[OntologyOverlayDescriptor] = []
    for path in sorted(artifact_root.glob("*_ontology_*coverage*.json")):
        try:
            payload = _load(path)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        ontology_key = _ontology_key(payload)
        overlay_id = str(payload.get("overlay_id") or "").strip()
        if not ontology_key or not overlay_id or not isinstance(payload.get("concepts"), list):
            continue
        source_key = _source_key(path)
        semantic_path = path.with_name(f"{source_key}_semantic_layer_v4_full_coverage.json")
        catalog_path = path.with_name(f"{source_key}_technical_semantic_catalog_v3.json")
        source = payload.get("source_evidence") or {}
        database_name = str(source.get("database_name") or source_key)
        descriptors.append(
            OntologyOverlayDescriptor(
                overlay_id=overlay_id,
                ontology_key=ontology_key,
                source_key=source_key,
                label=database_name,
                overlay_path=path,
                semantic_path=semantic_path if semantic_path.is_file() else None,
                catalog_path=catalog_path if catalog_path.is_file() else None,
            )
        )
    return descriptors


def list_overlay_descriptors(
    ontology_key: str,
    *,
    artifact_root: Path | None = None,
) -> list[OntologyOverlayDescriptor]:
    return [
        item
        for item in _candidate_descriptors(artifact_root or DEFAULT_ARTIFACT_ROOT)
        if item.ontology_key == ontology_key
    ]


def get_overlay_descriptor(
    ontology_key: str,
    overlay_id: str,
    *,
    artifact_root: Path | None = None,
) -> OntologyOverlayDescriptor:
    for descriptor in list_overlay_descriptors(ontology_key, artifact_root=artifact_root):
        if descriptor.overlay_id == overlay_id:
            return descriptor
    raise KeyError(f"ontology overlay is not registered: {overlay_id}")


def overlay_summary(ontology_key: str, *, artifact_root: Path | None = None) -> list[dict[str, Any]]:
    return [
        _descriptor_payload(item)
        for item in list_overlay_descriptors(ontology_key, artifact_root=artifact_root)
    ]


def _concept_summary(concept: dict[str, Any], *, include_fields: bool = False) -> dict[str, Any]:
    fields = []
    for field in concept.get("fields") or []:
        if not isinstance(field, dict):
            continue
        fields.append(
            {
                "semantic_field": field.get("semantic_field"),
                "physical_field": field.get("physical_field"),
                "labels": field.get("labels") or {},
                "business_role": field.get("business_role"),
                "definition_status": field.get("definition_status"),
                "semantic_status": field.get("semantic_status"),
                "description": field.get("description"),
                "technical_metadata": field.get("technical_metadata") or {},
            }
        )
    result = {
        "concept_id": concept.get("concept_id"),
        "physical_binding": concept.get("physical_binding"),
        "business_asset_id": concept.get("business_asset_id"),
        "labels": concept.get("labels") or {},
        "aliases": list(concept.get("aliases") or []),
        "description": concept.get("description"),
        "grain": concept.get("grain"),
        "roles": list(concept.get("roles") or []),
        "capabilities": list(concept.get("capabilities") or []),
        "runtime_status": concept.get("runtime_status"),
        "review_status": concept.get("review_status"),
        "binding_status": concept.get("binding_status"),
        "semantic_coverage_status": concept.get("semantic_coverage_status"),
        "retrieval_eligible": concept.get("retrieval_eligible") is True,
        "field_count": len(fields),
    }
    if include_fields:
        result["fields"] = fields
    return result


def overlay_concepts(
    ontology_key: str,
    overlay_id: str,
    *,
    query: str = "",
    status: str = "",
    offset: int = 0,
    limit: int = 50,
    artifact_root: Path | None = None,
) -> dict[str, Any]:
    descriptor = get_overlay_descriptor(ontology_key, overlay_id, artifact_root=artifact_root)
    payload = _load(descriptor.overlay_path)
    needle = query.strip().casefold()
    status_needle = status.strip().casefold()
    matched: list[dict[str, Any]] = []
    for concept in payload.get("concepts") or []:
        if not isinstance(concept, dict):
            continue
        row = _concept_summary(concept, include_fields=False)
        searchable = " ".join(
            [
                str(row.get("concept_id") or ""),
                str(row.get("physical_binding") or ""),
                str(row.get("business_asset_id") or ""),
                *[str(value) for value in (row.get("labels") or {}).values()],
                *[str(value) for value in row.get("aliases") or []],
            ]
        ).casefold()
        if needle and needle not in searchable:
            continue
        state = str(row.get("semantic_coverage_status") or row.get("binding_status") or "").casefold()
        if status_needle and status_needle not in state:
            continue
        matched.append(row)
    matched.sort(key=lambda item: (str(item.get("physical_binding") or ""), str(item.get("concept_id") or "")))
    bounded_offset = max(0, int(offset))
    bounded_limit = min(max(int(limit), 1), MAX_PAGE_LIMIT)
    return {
        "overlay": _descriptor_payload(descriptor),
        "items": matched[bounded_offset : bounded_offset + bounded_limit],
        "total": len(matched),
        "offset": bounded_offset,
        "limit": bounded_limit,
    }


def overlay_concept(
    ontology_key: str,
    overlay_id: str,
    concept_id: str,
    *,
    artifact_root: Path | None = None,
) -> dict[str, Any] | None:
    descriptor = get_overlay_descriptor(ontology_key, overlay_id, artifact_root=artifact_root)
    payload = _load(descriptor.overlay_path)
    for concept in payload.get("concepts") or []:
        if isinstance(concept, dict) and str(concept.get("concept_id") or "") == concept_id:
            return {"overlay": _descriptor_payload(descriptor), "concept": _concept_summary(concept, include_fields=True)}
    return None
