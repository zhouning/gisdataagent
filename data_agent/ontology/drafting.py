"""Governed ontology drafting over an immutable published baseline.

The browser sends small canonical changes. This module validates and appends
them to PostgreSQL, materializes an in-memory domain-model view for review, and
never mutates the active ontology version or package.
"""

from __future__ import annotations

import copy
import json
import re
import threading
import uuid
from collections import Counter
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any
from urllib.parse import quote

from sqlalchemy import bindparam, text

from ..db_engine import get_engine
from .contracts import ONTOLOGY_KEY, sha256_json, stable_token
from .registry import OntologyProfile, get_ontology_profile

DOMAIN_MODEL_KINDS = {
    "DomainClass",
    "ProcessClass",
    "StateClass",
    "RoleClass",
    "InformationClass",
    "ObservationClass",
}
EDITABLE_STATUSES = {"candidate", "curated", "active", "deprecated"}
GEOMETRY_TYPES = {
    "Point",
    "MultiPoint",
    "LineString",
    "MultiLineString",
    "Polygon",
    "MultiPolygon",
    "Geometry",
}
DATATYPES = {
    "xsd:string",
    "xsd:boolean",
    "xsd:date",
    "xsd:dateTime",
    "xsd:decimal",
    "xsd:double",
    "xsd:integer",
    "xsd:long",
    "xsd:anyURI",
    "geo:wktLiteral",
}
UPSERT_OPERATION = {
    "concept": "upsert_concept",
    "property": "upsert_property",
    "relation": "upsert_relation",
}
CODE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{1,127}$")
RELATION_TYPE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{1,127}$")
MAX_CHANGE_PAYLOAD_BYTES = 64 * 1024
MAX_DRAFT_CHANGES = 2_000


def _profile(value: OntologyProfile | str | None = None) -> OntologyProfile:
    if isinstance(value, OntologyProfile):
        return value
    return get_ontology_profile(value)

_PAYLOAD_FIELDS = {
    "concept": frozenset(
        {
            "code",
            "uri",
            "pref_label",
            "alt_labels",
            "definition",
            "kind",
            "domain_id",
            "geometry_type",
            "lifecycle_status",
        }
    ),
    "property": frozenset(
        {
            "code",
            "uri",
            "pref_label",
            "owner_concept_id",
            "datatype",
            "length",
            "precision_value",
            "scale_value",
            "min_count",
            "max_count",
            "ordinal",
            "value_domain",
            "default_value",
            "lifecycle_status",
        }
    ),
    "relation": frozenset(
        {
            "relation_type",
            "source_concept_id",
            "target_concept_id",
            "pref_label",
            "direction",
            "transitive",
            "is_transitive",
            "symmetric",
            "is_symmetric",
            "lifecycle_status",
        }
    ),
}


class OntologyDraftError(RuntimeError):
    """Base error for draft operations."""


class OntologyDraftNotFound(OntologyDraftError):
    pass


class OntologyDraftForbidden(OntologyDraftError):
    pass


class OntologyDraftConflict(OntologyDraftError):
    def __init__(self, message: str, *, current_revision: int | None = None):
        super().__init__(message)
        self.current_revision = current_revision


class OntologyDraftValidationError(OntologyDraftError):
    pass


def _json_ready(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def _row_dict(row: Any) -> dict[str, Any]:
    mapping = getattr(row, "_mapping", row)
    return _json_ready(dict(mapping))


def _clean_text(value: Any, field: str, *, maximum: int, required: bool = False) -> str:
    normalized = " ".join(str(value or "").split())
    if required and not normalized:
        raise OntologyDraftValidationError(f"{field} is required")
    if len(normalized) > maximum:
        raise OntologyDraftValidationError(f"{field} exceeds {maximum} characters")
    return normalized


def _string_list(value: Any, field: str, *, maximum: int = 50) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise OntologyDraftValidationError(f"{field} must be an array")
    output: list[str] = []
    for item in value:
        normalized = _clean_text(item, field, maximum=200)
        if normalized and normalized not in output:
            output.append(normalized)
    if len(output) > maximum:
        raise OntologyDraftValidationError(f"{field} contains too many values")
    return output


def _optional_integer(
    value: Any,
    field: str,
    *,
    maximum: int | None = None,
) -> int | None:
    """Normalize integer schema facets without silently truncating floats."""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise OntologyDraftValidationError(f"{field} must be an integer")
    try:
        decimal_value = Decimal(str(value))
    except Exception as exc:
        raise OntologyDraftValidationError(f"{field} must be an integer") from exc
    if not decimal_value.is_finite() or decimal_value != decimal_value.to_integral_value():
        raise OntologyDraftValidationError(f"{field} must be an integer")
    normalized = int(decimal_value)
    if normalized < 0:
        raise OntologyDraftValidationError(f"{field} must be non-negative")
    if maximum is not None and normalized > maximum:
        raise OntologyDraftValidationError(f"{field} exceeds {maximum}")
    return normalized


def _optional_value_domain(value: Any) -> dict[str, Any] | list[Any] | str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, (dict, list, str)):
        raise OntologyDraftValidationError("value_domain must be an object, array or string")
    if isinstance(value, str):
        return _clean_text(value, "value_domain", maximum=512)
    try:
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise OntologyDraftValidationError("value_domain must be JSON serializable") from exc
    if len(encoded.encode("utf-8")) > 32 * 1024:
        raise OntologyDraftValidationError("value_domain exceeds 32 KiB")
    return copy.deepcopy(value)


def _optional_default(value: Any) -> str | None:
    if value is None or value == "":
        return None
    return _clean_text(value, "default_value", maximum=1_024)


def _reject_unknown_fields(entity_type: str, payload: dict[str, Any]) -> None:
    unknown = sorted(set(payload) - _PAYLOAD_FIELDS[entity_type])
    if unknown:
        raise OntologyDraftValidationError(
            f"unsupported {entity_type} payload field(s): {', '.join(unknown)}"
        )


def empty_model_state() -> dict[str, dict[str, dict[str, Any]]]:
    return {"concept": {}, "property": {}, "relation": {}}


def _require_code(value: Any) -> str:
    code = _clean_text(value, "code", maximum=128, required=True)
    if not CODE_RE.fullmatch(code):
        raise OntologyDraftValidationError(
            "code must start with an ASCII letter and contain only letters, digits, _, . or -"
        )
    return code


def _stable_uri(
    entity_type: str,
    code: str,
    *,
    profile: OntologyProfile | str | None = None,
    owner_concept_id: str = "",
) -> str:
    ontology = _profile(profile)
    segment = "class" if entity_type == "concept" else "property"
    owner_segment = ""
    if entity_type == "property" and ontology.property_ids_scoped_by_owner and owner_concept_id:
        owner_segment = f"{quote(owner_concept_id.rsplit(':', 1)[-1], safe='-._~')}/"
    return f"{ontology.namespace_uri}{segment}/{owner_segment}{quote(code, safe='-._~')}"


def _stable_entity_id(
    entity_type: str,
    *,
    code: str = "",
    source_id: str = "",
    target_id: str = "",
    relation_type: str = "",
    profile: OntologyProfile | str | None = None,
) -> str:
    ontology = _profile(profile)
    prefix = ontology.stable_id_prefix
    if entity_type == "concept":
        return f"{prefix}:class:{code}"
    if entity_type == "property":
        owner = ""
        if ontology.property_ids_scoped_by_owner and source_id:
            owner = f"{source_id.rsplit(':', 1)[-1]}:"
        return f"{prefix}:property:{owner}{code}"
    if relation_type == "subClassOf":
        source = source_id.rsplit(":", 1)[-1]
        target = target_id.rsplit(":", 1)[-1]
        return f"{prefix}:subclass:{source}:{target}"
    token = stable_token(prefix, relation_type, source_id, target_id, length=24)
    return f"{prefix}:relation:{token}"


def _normalize_concept(
    entity_id: str,
    payload: dict[str, Any],
    existing: dict[str, Any] | None,
    *,
    profile: OntologyProfile | str | None = None,
) -> tuple[str, dict[str, Any]]:
    ontology = _profile(profile)
    code = _require_code(
        payload.get("code") if "code" in payload else (existing or {}).get("code")
    )
    concept_id = entity_id or _stable_entity_id("concept", code=code, profile=ontology)
    if existing and concept_id != existing["concept_id"]:
        raise OntologyDraftValidationError("concept_id is immutable")
    if not existing and concept_id != _stable_entity_id("concept", code=code, profile=ontology):
        raise OntologyDraftValidationError(
            f"new concept_id must use the governed {ontology.stable_id_prefix}:class namespace"
        )

    uri = str(
        payload.get("uri")
        or (existing or {}).get("uri")
        or _stable_uri("concept", code, profile=ontology)
    )
    if existing and uri != existing.get("uri"):
        raise OntologyDraftValidationError("uri is immutable for an existing concept")
    if uri != _stable_uri("concept", code, profile=ontology):
        raise OntologyDraftValidationError("concept URI must be the stable URI derived from code")

    kind = str(payload.get("kind") or (existing or {}).get("kind") or "DomainClass")
    if kind not in DOMAIN_MODEL_KINDS:
        raise OntologyDraftValidationError("only curated domain-model kinds can be edited")
    domain_id = str(payload.get("domain_id") or (existing or {}).get("domain_id") or "")
    if domain_id not in ontology.domain_labels:
        raise OntologyDraftValidationError("domain_id is not registered for this ontology")
    geometry_type = payload.get("geometry_type", (existing or {}).get("geometry_type"))
    if geometry_type in {"", None}:
        geometry_type = None
    elif str(geometry_type) not in GEOMETRY_TYPES:
        raise OntologyDraftValidationError("unsupported geometry_type")
    lifecycle = str(
        payload.get("lifecycle_status") or (existing or {}).get("lifecycle_status") or "candidate"
    )
    if lifecycle not in EDITABLE_STATUSES:
        raise OntologyDraftValidationError("unsupported lifecycle_status")

    value = dict(existing or {})
    value.update(
        {
            "concept_id": concept_id,
            "uri": uri,
            "kind": kind,
            "code": code,
            "pref_label": _clean_text(
                payload.get("pref_label") if "pref_label" in payload else value.get("pref_label"),
                "pref_label",
                maximum=300,
                required=True,
            ),
            "alt_labels": _string_list(
                payload.get("alt_labels")
                if "alt_labels" in payload
                else value.get("alt_labels", []),
                "alt_labels",
            ),
            "definition": _clean_text(
                payload.get("definition")
                if "definition" in payload
                else value.get("definition", ""),
                "definition",
                maximum=4_000,
            ),
            "domain_id": domain_id,
            "geometry_type": geometry_type,
            "lifecycle_status": lifecycle,
            "source_system": value.get("source_system") or "curated_domain",
            "source_id": value.get("source_id") or ontology.curated_source_id,
        }
    )
    provenance = dict(value.get("provenance") or {})
    provenance.update(
        {
            "modeling_role": provenance.get("modeling_role") or kind,
            "draft_managed": True,
            "review_status": "domain_owner_review_required",
        }
    )
    value["provenance"] = provenance
    return concept_id, value


def _normalize_property(
    entity_id: str,
    payload: dict[str, Any],
    existing: dict[str, Any] | None,
    state: dict[str, dict[str, dict[str, Any]]],
    *,
    profile: OntologyProfile | str | None = None,
) -> tuple[str, dict[str, Any]]:
    ontology = _profile(profile)
    code = _require_code(
        payload.get("code") if "code" in payload else (existing or {}).get("code")
    )
    owner_for_id = str(
        payload.get("owner_concept_id")
        or (existing or {}).get("owner_concept_id")
        or ""
    )
    property_id = entity_id or _stable_entity_id(
        "property", code=code, source_id=owner_for_id, profile=ontology
    )
    if existing and property_id != existing["property_id"]:
        raise OntologyDraftValidationError("property_id is immutable")
    if not existing and property_id != _stable_entity_id(
        "property", code=code, source_id=owner_for_id, profile=ontology
    ):
        raise OntologyDraftValidationError(
            f"new property_id must use the governed {ontology.stable_id_prefix}:property namespace"
        )
    uri = str(
        payload.get("uri")
        or (existing or {}).get("uri")
        or _stable_uri("property", code, profile=ontology, owner_concept_id=owner_for_id)
    )
    if existing and uri != existing.get("uri"):
        raise OntologyDraftValidationError("uri is immutable for an existing property")
    if uri != _stable_uri(
        "property", code, profile=ontology, owner_concept_id=owner_for_id
    ):
        raise OntologyDraftValidationError("property URI must be the stable URI derived from code")

    owner_id = str(
        payload.get("owner_concept_id") or (existing or {}).get("owner_concept_id") or ""
    )
    if owner_id not in state["concept"]:
        raise OntologyDraftValidationError(
            "owner_concept_id is not present in the draft domain model"
        )
    datatype = str(payload.get("datatype") or (existing or {}).get("datatype") or "xsd:string")
    if datatype not in DATATYPES:
        raise OntologyDraftValidationError("unsupported datatype")
    min_count = _optional_integer(
        payload.get("min_count", (existing or {}).get("min_count", 0)),
        "min_count",
        maximum=1_000_000,
    )
    min_count = 0 if min_count is None else min_count
    max_count = _optional_integer(
        payload.get("max_count", (existing or {}).get("max_count", 1)),
        "max_count",
        maximum=1_000_000,
    )
    if max_count is not None and max_count < min_count:
        raise OntologyDraftValidationError(
            "property cardinality must satisfy 0 <= min_count <= max_count"
        )
    ordinal = _optional_integer(
        payload.get("ordinal", (existing or {}).get("ordinal", 0)),
        "ordinal",
        maximum=1_000_000,
    )
    ordinal = 0 if ordinal is None else ordinal
    length = _optional_integer(
        payload.get("length", (existing or {}).get("length")),
        "length",
        maximum=1_000_000,
    )
    precision = _optional_integer(
        payload.get("precision_value", (existing or {}).get("precision_value")),
        "precision_value",
        maximum=1_000,
    )
    scale = _optional_integer(
        payload.get("scale_value", (existing or {}).get("scale_value")),
        "scale_value",
        maximum=1_000,
    )
    if precision is not None and scale is not None and scale > precision:
        raise OntologyDraftValidationError("scale_value cannot exceed precision_value")

    value = dict(existing or {})
    value.update(
        {
            "property_id": property_id,
            "owner_concept_id": owner_id,
            "uri": uri,
            "code": code,
            "pref_label": _clean_text(
                payload.get("pref_label") if "pref_label" in payload else value.get("pref_label"),
                "pref_label",
                maximum=300,
                required=True,
            ),
            "datatype": datatype,
            "length": length,
            "precision_value": precision,
            "scale_value": scale,
            "min_count": min_count,
            "max_count": max_count,
            "ordinal": ordinal,
            "value_domain": _optional_value_domain(
                payload.get("value_domain", value.get("value_domain"))
            ),
            "default_value": _optional_default(
                payload.get("default_value", value.get("default_value"))
            ),
            "lifecycle_status": str(
                payload.get("lifecycle_status") or value.get("lifecycle_status") or "candidate"
            ),
            "source_id": value.get("source_id") or ontology.curated_source_id,
        }
    )
    if value["lifecycle_status"] not in EDITABLE_STATUSES:
        raise OntologyDraftValidationError("unsupported lifecycle_status")
    provenance = dict(value.get("provenance") or {})
    provenance.update(
        {
            "modeling_role": "curated_domain_data_property",
            "draft_managed": True,
            "review_status": "domain_owner_review_required",
        }
    )
    value["provenance"] = provenance
    return property_id, value


def _normalize_relation(
    entity_id: str,
    payload: dict[str, Any],
    existing: dict[str, Any] | None,
    state: dict[str, dict[str, dict[str, Any]]],
    *,
    profile: OntologyProfile | str | None = None,
) -> tuple[str, dict[str, Any]]:
    ontology = _profile(profile)
    relation_type = _clean_text(
        payload.get("relation_type")
        if "relation_type" in payload
        else (existing or {}).get("relation_type"),
        "relation_type",
        maximum=128,
        required=True,
    )
    if not RELATION_TYPE_RE.fullmatch(relation_type):
        raise OntologyDraftValidationError("unsupported relation_type")
    source_id = str(
        payload.get("source_concept_id") or (existing or {}).get("source_concept_id") or ""
    )
    target_id = str(
        payload.get("target_concept_id") or (existing or {}).get("target_concept_id") or ""
    )
    if source_id not in state["concept"] or target_id not in state["concept"]:
        raise OntologyDraftValidationError(
            "relation endpoints must exist in the draft domain model"
        )
    if source_id == target_id:
        raise OntologyDraftValidationError("self-referential relations are not allowed")
    expected_id = _stable_entity_id(
        "relation",
        source_id=source_id,
        target_id=target_id,
        relation_type=relation_type,
        profile=ontology,
    )
    relation_id = entity_id or expected_id
    if existing and relation_id != existing["relation_id"]:
        raise OntologyDraftValidationError("relation_id is immutable")
    if existing and (
        relation_type != existing.get("relation_type")
        or source_id != existing.get("source_concept_id")
        or target_id != existing.get("target_concept_id")
    ):
        raise OntologyDraftValidationError(
            "relation technical identity is immutable; create a new relation instead"
        )
    if not existing and relation_id != expected_id:
        raise OntologyDraftValidationError(
            "new relation_id must use the governed stable identifier"
        )

    direction = str(payload.get("direction") or (existing or {}).get("direction") or "directed")
    if direction not in {"directed", "bidirectional"}:
        raise OntologyDraftValidationError("direction must be directed or bidirectional")
    transitive = bool(
        payload.get(
            "transitive", payload.get("is_transitive", (existing or {}).get("transitive", False))
        )
    )
    symmetric = bool(
        payload.get(
            "symmetric", payload.get("is_symmetric", (existing or {}).get("symmetric", False))
        )
    )
    if relation_type == "subClassOf":
        direction = "directed"
        transitive = True
        symmetric = False

    value = dict(existing or {})
    value.update(
        {
            "relation_id": relation_id,
            "relation_type": relation_type,
            "source_concept_id": source_id,
            "target_concept_id": target_id,
            "pref_label": _clean_text(
                payload.get("pref_label")
                if "pref_label" in payload
                else value.get("pref_label", ""),
                "pref_label",
                maximum=300,
            ),
            "direction": direction,
            "transitive": transitive,
            "symmetric": symmetric,
            "lifecycle_status": str(
                payload.get("lifecycle_status") or value.get("lifecycle_status") or "candidate"
            ),
            "source_id": value.get("source_id") or ontology.curated_source_id,
        }
    )
    if value["lifecycle_status"] not in EDITABLE_STATUSES:
        raise OntologyDraftValidationError("unsupported lifecycle_status")
    provenance = dict(value.get("provenance") or {})
    provenance.update(
        {
            "axiom_type": "rdfs:subClassOf"
            if relation_type == "subClassOf"
            else "owl:ObjectProperty",
            "draft_managed": True,
            "review_status": "domain_owner_review_required",
        }
    )
    value["provenance"] = provenance
    return relation_id, value


def apply_draft_change(
    state: dict[str, dict[str, dict[str, Any]]],
    change: dict[str, Any],
    *,
    profile: OntologyProfile | str | None = None,
) -> dict[str, Any]:
    """Validate and apply one canonical change to a mutable model state."""
    operation = str(change.get("operation") or "")
    entity_type = str(change.get("entity_type") or "")
    entity_id = str(change.get("entity_id") or "").strip()
    payload = change.get("payload", {})
    if entity_type not in UPSERT_OPERATION:
        raise OntologyDraftValidationError("entity_type must be concept, property or relation")
    if not isinstance(payload, dict):
        raise OntologyDraftValidationError("payload must be an object")
    _reject_unknown_fields(entity_type, payload)
    if len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) > MAX_CHANGE_PAYLOAD_BYTES:
        raise OntologyDraftValidationError("change payload exceeds 64 KiB")
    if operation not in {*UPSERT_OPERATION.values(), "deprecate_entity"}:
        raise OntologyDraftValidationError("unsupported draft operation")
    if operation != "deprecate_entity" and operation != UPSERT_OPERATION[entity_type]:
        raise OntologyDraftValidationError("operation does not match entity_type")

    existing = state[entity_type].get(entity_id) if entity_id else None
    before = copy.deepcopy(existing)
    if operation == "deprecate_entity":
        if not entity_id or existing is None:
            raise OntologyDraftValidationError("the entity to deprecate does not exist")
        after = dict(existing)
        after["lifecycle_status"] = "deprecated"
        state[entity_type][entity_id] = after
        return {"entity_id": entity_id, "before": before, "after": copy.deepcopy(after)}

    if entity_type == "concept":
        normalized_id, after = _normalize_concept(entity_id, payload, existing, profile=profile)
    elif entity_type == "property":
        normalized_id, after = _normalize_property(
            entity_id, payload, existing, state, profile=profile
        )
    else:
        normalized_id, after = _normalize_relation(
            entity_id, payload, existing, state, profile=profile
        )
    state[entity_type][normalized_id] = after
    return {"entity_id": normalized_id, "before": before, "after": copy.deepcopy(after)}


def materialize_model_state(
    base_state: dict[str, dict[str, dict[str, Any]]],
    changes: list[dict[str, Any]],
    *,
    profile: OntologyProfile | str | None = None,
) -> dict[str, dict[str, dict[str, Any]]]:
    state = copy.deepcopy(base_state)
    for change in changes:
        apply_draft_change(state, change, profile=profile)
    return state


def _subclass_cycle(state: dict[str, dict[str, dict[str, Any]]]) -> list[str] | None:
    adjacency: dict[str, list[str]] = {}
    for relation in state["relation"].values():
        if (
            relation.get("relation_type") != "subClassOf"
            or relation.get("lifecycle_status") == "deprecated"
        ):
            continue
        adjacency.setdefault(str(relation["source_concept_id"]), []).append(
            str(relation["target_concept_id"])
        )
    visiting: set[str] = set()
    visited: set[str] = set()
    path: list[str] = []

    def visit(node: str) -> list[str] | None:
        if node in visiting:
            start = path.index(node)
            return [*path[start:], node]
        if node in visited:
            return None
        visiting.add(node)
        path.append(node)
        for target in adjacency.get(node, []):
            cycle = visit(target)
            if cycle:
                return cycle
        path.pop()
        visiting.remove(node)
        visited.add(node)
        return None

    for node in sorted(adjacency):
        cycle = visit(node)
        if cycle:
            return cycle
    return None


def validate_model_state(
    state: dict[str, dict[str, dict[str, Any]]],
    *,
    base_is_active: bool = True,
    profile: OntologyProfile | str | None = None,
) -> dict[str, Any]:
    """Run bounded structural gates over a materialized curated-domain draft."""
    issues: list[dict[str, Any]] = []
    if not base_is_active:
        issues.append(
            {
                "code": "stale_baseline",
                "severity": "error",
                "path": "draft.base_content_sha256",
                "message": "活动本体已变化，请基于最新活动版本重新建立草稿",
            }
        )

    uri_owners: dict[str, tuple[str, str]] = {}
    for entity_type in ("concept", "property"):
        for entity_id, entity in state[entity_type].items():
            if entity.get("lifecycle_status") == "deprecated":
                continue
            code = str(entity.get("code") or "")
            expected_id = _stable_entity_id(
                entity_type,
                code=code,
                source_id=entity.get("owner_concept_id", ""),
                profile=profile,
            ) if code else ""
            actual_id = (
                entity.get("concept_id") if entity_type == "concept" else entity.get("property_id")
            )
            if not code:
                issues.append(
                    {
                        "code": "missing_code",
                        "severity": "error",
                        "path": f"{entity_type}.{entity_id}.code",
                        "entity_type": entity_type,
                        "entity_id": entity_id,
                        "message": "领域对象必须有稳定技术代码",
                    }
                )
            elif actual_id != expected_id or entity_id != expected_id:
                issues.append(
                    {
                        "code": "unstable_entity_id",
                        "severity": "error",
                        "path": f"{entity_type}.{entity_id}",
                        "entity_type": entity_type,
                        "entity_id": entity_id,
                        "message": "实体 ID 必须由稳定代码推导",
                    }
                )
            uri = str(entity.get("uri") or "")
            if uri != _stable_uri(
                entity_type,
                code,
                profile=profile,
                owner_concept_id=entity.get("owner_concept_id", ""),
            ):
                issues.append(
                    {
                        "code": "unstable_uri",
                        "severity": "error",
                        "path": f"{entity_type}.{entity_id}.uri",
                        "entity_type": entity_type,
                        "entity_id": entity_id,
                        "message": "URI 不属于 GIS Data Agent 稳定命名空间",
                    }
                )
            if uri in uri_owners:
                issues.append(
                    {
                        "code": "duplicate_uri",
                        "severity": "error",
                        "path": f"{entity_type}.{entity_id}.uri",
                        "entity_type": entity_type,
                        "entity_id": entity_id,
                        "message": f"URI 已由 {uri_owners[uri][1]} 使用",
                    }
                )
            else:
                uri_owners[uri] = (entity_type, entity_id)

    for property_id, prop in state["property"].items():
        if prop.get("owner_concept_id") not in state["concept"]:
            issues.append(
                {
                    "code": "missing_property_owner",
                    "severity": "error",
                    "path": f"property.{property_id}.owner_concept_id",
                    "entity_type": "property",
                    "entity_id": property_id,
                    "message": "属性所属类不存在",
                }
            )
        elif state["concept"][prop["owner_concept_id"]].get("lifecycle_status") == "deprecated":
            issues.append(
                {
                    "code": "deprecated_property_owner",
                    "severity": "error",
                    "path": f"property.{property_id}.owner_concept_id",
                    "entity_type": "property",
                    "entity_id": property_id,
                    "message": "属性不能挂在已弃用的领域类上",
                }
            )
        min_count = prop.get("min_count")
        max_count = prop.get("max_count")
        cardinality_valid = (
            isinstance(min_count, int)
            and not isinstance(min_count, bool)
            and min_count >= 0
            and (
                max_count is None
                or (
                    isinstance(max_count, int)
                    and not isinstance(max_count, bool)
                    and max_count >= min_count
                )
            )
        )
        if not cardinality_valid:
            issues.append(
                {
                    "code": "invalid_cardinality",
                    "severity": "error",
                    "path": f"property.{property_id}.cardinality",
                    "entity_type": "property",
                    "entity_id": property_id,
                    "message": "属性基数无效",
                }
            )
        for field, maximum in (
            ("length", 1_000_000),
            ("precision_value", 1_000),
            ("scale_value", 1_000),
        ):
            value = prop.get(field)
            if value is not None and (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < 0
                or value > maximum
            ):
                issues.append(
                    {
                        "code": "invalid_property_facet",
                        "severity": "error",
                        "path": f"property.{property_id}.{field}",
                        "entity_type": "property",
                        "entity_id": property_id,
                        "message": f"{field} 必须是合法非负整数",
                    }
                )
        if (
            isinstance(prop.get("precision_value"), int)
            and isinstance(prop.get("scale_value"), int)
            and prop["scale_value"] > prop["precision_value"]
        ):
            issues.append(
                {
                    "code": "invalid_property_facet",
                    "severity": "error",
                    "path": f"property.{property_id}.scale_value",
                    "entity_type": "property",
                    "entity_id": property_id,
                    "message": "scale_value 不能大于 precision_value",
                }
            )
        if prop.get("datatype") not in DATATYPES:
            issues.append(
                {
                    "code": "unsupported_datatype",
                    "severity": "error",
                    "path": f"property.{property_id}.datatype",
                    "entity_type": "property",
                    "entity_id": property_id,
                    "message": "属性数据类型不在受治理的数据类型集合中",
                }
            )

    relation_identities: dict[tuple[str, ...], str] = {}
    for relation_id, relation in state["relation"].items():
        if relation.get("lifecycle_status") == "deprecated":
            continue
        relation_type = str(relation.get("relation_type") or "")
        source_id = str(relation.get("source_concept_id") or "")
        target_id = str(relation.get("target_concept_id") or "")
        if relation.get("relation_id") != relation_id:
            issues.append(
                {
                    "code": "unstable_relation_id",
                    "severity": "error",
                    "path": f"relation.{relation_id}",
                    "entity_type": "relation",
                    "entity_id": relation_id,
                    "message": "关系记录的技术 ID 与模型索引不一致",
                }
            )
        provenance = relation.get("provenance") or {}
        identity_parts = [relation_type, source_id, target_id]
        if relation_type == "objectProperty":
            identity_parts.append(str(provenance.get("property_name") or ""))
        elif relation_type == "classRestriction":
            identity_parts.extend(
                [
                    str(provenance.get("property_name") or ""),
                    str(provenance.get("cardinality") or ""),
                    str(provenance.get("count") or ""),
                ]
            )
        ontology = _profile(profile)
        if ontology.property_ids_scoped_by_owner:
            # DMT keeps repeated relationship patterns when they originate
            # from distinct source fields.  The source relation ordinal is
            # part of that candidate's review identity.
            identity_parts.append(
                str(
                    provenance.get("relation_index")
                    or relation.get("source_object_id")
                    or ""
                )
            )
        identity = tuple(identity_parts)
        if identity in relation_identities and relation_identities[identity] != relation_id:
            issues.append(
                {
                    "code": "duplicate_relation_identity",
                    "severity": "error",
                    "path": f"relation.{relation_id}",
                    "entity_type": "relation",
                    "entity_id": relation_id,
                    "message": f"关系技术身份与 {relation_identities[identity]} 重复",
                }
            )
        else:
            relation_identities[identity] = relation_id
        for field in ("source_concept_id", "target_concept_id"):
            if relation.get(field) not in state["concept"]:
                issues.append(
                    {
                        "code": "missing_relation_endpoint",
                        "severity": "error",
                        "path": f"relation.{relation_id}.{field}",
                        "entity_type": "relation",
                        "entity_id": relation_id,
                        "message": "关系端点不存在",
                    }
                )
            elif state["concept"][relation[field]].get("lifecycle_status") == "deprecated":
                issues.append(
                    {
                        "code": "deprecated_relation_endpoint",
                        "severity": "error",
                        "path": f"relation.{relation_id}.{field}",
                        "entity_type": "relation",
                        "entity_id": relation_id,
                        "message": "活动关系不能指向已弃用的领域类",
                    }
                )
        if not relation_type or not RELATION_TYPE_RE.fullmatch(relation_type):
            issues.append(
                {
                    "code": "unsupported_relation_type",
                    "severity": "error",
                    "path": f"relation.{relation_id}.relation_type",
                    "entity_type": "relation",
                    "entity_id": relation_id,
                    "message": "关系类型不符合受治理命名规则",
                }
            )

    for entity_type in ("concept", "property"):
        seen_codes: dict[str, str] = {}
        for entity_id, entity in state[entity_type].items():
            if entity.get("lifecycle_status") == "deprecated":
                continue
            code = str(entity.get("code") or "").casefold()
            if entity_type == "property" and _profile(profile).property_ids_scoped_by_owner:
                code = f"{entity.get('owner_concept_id', '')}:{code}"
            if not code:
                continue
            if code in seen_codes and seen_codes[code] != entity_id:
                issues.append(
                    {
                        "code": "duplicate_code",
                        "severity": "error",
                        "path": f"{entity_type}.{entity_id}.code",
                        "entity_type": entity_type,
                        "entity_id": entity_id,
                        "message": f"技术代码与 {seen_codes[code]} 重复",
                    }
                )
            else:
                seen_codes[code] = entity_id

    cycle = _subclass_cycle(state)
    if cycle:
        issues.append(
            {
                "code": "subclass_cycle",
                "severity": "error",
                "path": "relation.subClassOf",
                "entity_type": "relation",
                "entity_id": " -> ".join(cycle),
                "message": "继承关系形成环",
            }
        )

    severities = Counter(str(issue["severity"]) for issue in issues)
    return {
        "conforms": not any(issue["severity"] == "error" for issue in issues),
        "issue_count": len(issues),
        "severity_counts": dict(severities),
        "issues": issues,
        "checks": [
            "stable_entity_id",
            "stable_uri",
            "unique_uri",
            "property_owner",
            "cardinality",
            "property_facets",
            "relation_endpoint",
            "relation_identity",
            "subclass_acyclic",
            "active_baseline",
        ],
    }


def compute_model_diff(
    base_state: dict[str, dict[str, dict[str, Any]]],
    draft_state: dict[str, dict[str, dict[str, Any]]],
) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    for entity_type in ("concept", "property", "relation"):
        base_entities = base_state[entity_type]
        draft_entities = draft_state[entity_type]
        for entity_id in sorted(set(base_entities) | set(draft_entities)):
            before = base_entities.get(entity_id)
            after = draft_entities.get(entity_id)
            if before == after:
                continue
            if before is None:
                change_kind = "added"
            elif after is None:
                change_kind = "removed"
            elif (
                before.get("lifecycle_status") != "deprecated"
                and after.get("lifecycle_status") == "deprecated"
            ):
                change_kind = "deprecated"
            else:
                change_kind = "modified"
            counts[change_kind] += 1
            items.append(
                {
                    "entity_type": entity_type,
                    "entity_id": entity_id,
                    "change_kind": change_kind,
                    "before": before,
                    "after": after,
                }
            )
    changed_concepts = {
        item["entity_id"]
        for item in items
        if item["entity_type"] == "concept"
    }
    changed_properties = {
        item["entity_id"]
        for item in items
        if item["entity_type"] == "property"
    }
    changed_relations = {
        item["entity_id"]
        for item in items
        if item["entity_type"] == "relation"
    }
    impacted_concepts = set(changed_concepts)
    impacted_properties = set(changed_properties)
    impacted_relations = set(changed_relations)
    for item in items:
        before = item.get("before") or {}
        after = item.get("after") or {}
        if item["entity_type"] == "property":
            owner_id = after.get("owner_concept_id") or before.get("owner_concept_id")
            if owner_id:
                impacted_concepts.add(owner_id)
        elif item["entity_type"] == "relation":
            impacted_concepts.update(
                endpoint
                for endpoint in (
                    after.get("source_concept_id") or before.get("source_concept_id"),
                    after.get("target_concept_id") or before.get("target_concept_id"),
                )
                if endpoint
            )
    for entity_id, prop in draft_state["property"].items():
        if prop.get("owner_concept_id") in changed_concepts:
            impacted_properties.add(entity_id)
    for entity_id, relation in draft_state["relation"].items():
        if (
            relation.get("source_concept_id") in changed_concepts
            or relation.get("target_concept_id") in changed_concepts
        ):
            impacted_relations.add(entity_id)
            impacted_concepts.update(
                endpoint
                for endpoint in (
                    relation.get("source_concept_id"),
                    relation.get("target_concept_id"),
                )
                if endpoint
            )
    return {
        "items": items,
        "summary": {
            "total": len(items),
            "added": counts["added"],
            "modified": counts["modified"],
            "deprecated": counts["deprecated"],
            "removed": counts["removed"],
        },
        "impact": {
            "changed_concept_count": len(changed_concepts),
            "changed_property_count": len(changed_properties),
            "changed_relation_count": len(changed_relations),
            "impacted_concept_count": len(impacted_concepts),
            "impacted_property_count": len(impacted_properties),
            "impacted_relation_count": len(impacted_relations),
            "concept_ids": sorted(impacted_concepts)[:100],
        },
    }


class OntologyDraftService:
    """PostgreSQL application service for ontology draft aggregates."""

    def __init__(
        self,
        engine: Any | None = None,
        *,
        ontology_key: str = ONTOLOGY_KEY,
    ):
        self.profile = get_ontology_profile(ontology_key)
        self.engine = engine if engine is not None else get_engine()
        if self.engine is None:
            raise RuntimeError("GIS Data Agent PostgreSQL is not configured")

    @staticmethod
    def _draft_access_clause(*, for_update: bool = False) -> str:
        # Lock only the mutable draft aggregate.  The joined ontology_version
        # row is an immutable published baseline and intentionally remains
        # read-only for the runtime role; a bare ``FOR UPDATE`` would ask
        # PostgreSQL for UPDATE privilege on that baseline as well.
        return " FOR UPDATE OF d" if for_update else ""

    def _draft_row(
        self,
        connection: Any,
        draft_id: str,
        *,
        actor: str,
        is_admin: bool,
        for_update: bool = False,
        require_owner: bool = False,
    ) -> dict[str, Any]:
        row = connection.execute(
            text(
                "SELECT d.draft_id::text AS draft_id, d.ontology_key, "
                "d.base_version_id::text AS base_version_id, d.base_content_sha256, "
                "v.semantic_version AS base_semantic_version, d.title, d.description, "
                "d.status, d.revision, d.created_by, d.updated_by, d.created_at, "
                "d.updated_at, d.submitted_at, d.submitted_by "
                "FROM gda_ontology.ontology_draft d "
                "JOIN gda_ontology.ontology_version v ON v.ontology_version_id = d.base_version_id "
                "WHERE d.draft_id = CAST(:draft_id AS uuid) AND d.ontology_key = :ontology_key"
                + self._draft_access_clause(for_update=for_update)
            ),
            {"draft_id": draft_id, "ontology_key": self.profile.ontology_key},
        ).first()
        if row is None:
            raise OntologyDraftNotFound("ontology draft not found")
        result = _row_dict(row)
        if not is_admin:
            can_read = result["created_by"] == actor
            if not can_read:
                raise OntologyDraftForbidden("ontology draft is not visible to this user")
            if require_owner and result["created_by"] != actor:
                raise OntologyDraftForbidden("only the draft owner can edit this draft")
        return result

    def _active_baseline(self, connection: Any) -> dict[str, Any]:
        row = connection.execute(
            text(
                "SELECT v.ontology_version_id::text AS ontology_version_id, "
                "v.semantic_version, v.content_sha256 "
                "FROM gda_ontology.active_package a "
                "JOIN gda_ontology.ontology_version v "
                "ON v.ontology_version_id = a.ontology_version_id "
                "WHERE a.ontology_key = :ontology_key AND v.status = 'published'"
            ),
            {"ontology_key": self.profile.ontology_key},
        ).first()
        if row is None:
            raise RuntimeError("no active published PostgreSQL ontology is available")
        return _row_dict(row)

    @staticmethod
    def _changes(connection: Any, draft_id: str) -> list[dict[str, Any]]:
        rows = connection.execute(
            text(
                "SELECT change_id::text AS change_id, sequence_no, operation, entity_type, "
                "entity_id, payload, actor, created_at "
                "FROM gda_ontology.ontology_draft_change "
                "WHERE draft_id = CAST(:draft_id AS uuid) ORDER BY sequence_no"
            ),
            {"draft_id": draft_id},
        ).fetchall()
        return [_row_dict(row) for row in rows]

    @staticmethod
    def _base_state(connection: Any, version_id: str) -> dict[str, dict[str, dict[str, Any]]]:
        state = empty_model_state()
        concept_sql = text(
            "SELECT concept_id, uri, kind, code, pref_label, alt_labels, definition, "
            "domain_id, source_system, source_id, geometry_type, lifecycle_status, provenance "
            "FROM gda_ontology.concept WHERE ontology_version_id = CAST(:version_id AS uuid) "
            "AND kind IN :kinds ORDER BY concept_id"
        ).bindparams(bindparam("kinds", expanding=True))
        concept_rows = connection.execute(
            concept_sql,
            {"version_id": version_id, "kinds": sorted(DOMAIN_MODEL_KINDS)},
        ).fetchall()
        for row in concept_rows:
            value = _row_dict(row)
            state["concept"][value["concept_id"]] = value

        property_sql = text(
            "SELECT p.property_id, p.owner_concept_id, p.uri, p.code, p.pref_label, "
            "p.datatype, p.length, p.precision_value, p.scale_value, p.min_count, "
            "p.max_count, p.ordinal, p.value_domain, p.default_value, p.lifecycle_status, "
            "p.source_id, p.provenance FROM gda_ontology.property p "
            "JOIN gda_ontology.concept c ON c.ontology_version_id = p.ontology_version_id "
            "AND c.concept_id = p.owner_concept_id "
            "WHERE p.ontology_version_id = CAST(:version_id AS uuid) AND c.kind IN :kinds "
            "ORDER BY p.property_id"
        ).bindparams(bindparam("kinds", expanding=True))
        property_rows = connection.execute(
            property_sql,
            {"version_id": version_id, "kinds": sorted(DOMAIN_MODEL_KINDS)},
        ).fetchall()
        for row in property_rows:
            value = _row_dict(row)
            state["property"][value["property_id"]] = value

        relation_sql = text(
            "SELECT r.relation_id, r.relation_type, r.source_concept_id, r.target_concept_id, "
            "r.pref_label, r.direction, r.is_transitive AS transitive, "
            "r.is_symmetric AS symmetric, r.source_id, r.lifecycle_status, r.provenance "
            "FROM gda_ontology.relation r "
            "WHERE r.ontology_version_id = CAST(:version_id AS uuid) "
            "AND r.source_concept_id IN :concept_ids AND r.target_concept_id IN :target_ids "
            "ORDER BY r.relation_id"
        ).bindparams(
            bindparam("concept_ids", expanding=True),
            bindparam("target_ids", expanding=True),
        )
        concept_ids = sorted(state["concept"])
        if concept_ids:
            relation_rows = connection.execute(
                relation_sql,
                {
                    "version_id": version_id,
                    "concept_ids": concept_ids,
                    "target_ids": concept_ids,
                },
            ).fetchall()
            for row in relation_rows:
                value = _row_dict(row)
                state["relation"][value["relation_id"]] = value
        return state

    @staticmethod
    def _model_payload(
        state: dict[str, dict[str, dict[str, Any]]],
        *,
        concept_id: str | None = None,
    ) -> dict[str, Any]:
        concepts = list(state["concept"].values())
        properties = list(state["property"].values())
        relations = list(state["relation"].values())
        if concept_id:
            concepts = [item for item in concepts if item["concept_id"] == concept_id]
            properties = [item for item in properties if item["owner_concept_id"] == concept_id]
            relations = [
                item
                for item in relations
                if concept_id in {item["source_concept_id"], item["target_concept_id"]}
            ]
        payload = {
            "concepts": sorted(
                concepts, key=lambda item: (item.get("pref_label", ""), item["concept_id"])
            ),
            "properties": sorted(
                properties, key=lambda item: (item.get("ordinal", 0), item["property_id"])
            ),
            "relations": sorted(relations, key=lambda item: item["relation_id"]),
            "summary": {
                "concept_count": len(state["concept"]),
                "property_count": len(state["property"]),
                "relation_count": len(state["relation"]),
            },
        }
        payload["model_sha256"] = sha256_json(payload)
        return payload

    def list_drafts(self, *, actor: str, is_admin: bool = False) -> list[dict[str, Any]]:
        visibility = "" if is_admin else "AND d.created_by = :actor"
        with self.engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT d.draft_id::text AS draft_id, "
                    "d.base_version_id::text AS base_version_id, "
                    "v.semantic_version AS base_semantic_version, d.base_content_sha256, d.title, "
                    "d.description, d.status, d.revision, d.created_by, d.updated_by, "
                    "d.created_at, d.updated_at, d.submitted_at, d.submitted_by "
                    "FROM gda_ontology.ontology_draft d "
                    "JOIN gda_ontology.ontology_version v "
                    "ON v.ontology_version_id = d.base_version_id "
                    "WHERE d.ontology_key = :ontology_key "
                    + visibility
                    + " ORDER BY d.updated_at DESC LIMIT 100"
                ),
                {"ontology_key": self.profile.ontology_key, "actor": actor},
            ).fetchall()
        return [_row_dict(row) for row in rows]

    def create_draft(self, *, actor: str, title: str, description: str = "") -> dict[str, Any]:
        normalized_title = _clean_text(title, "title", maximum=200, required=True)
        normalized_description = _clean_text(description, "description", maximum=4_000)
        draft_id = str(uuid.uuid4())
        with self.engine.begin() as connection:
            baseline = self._active_baseline(connection)
            row = connection.execute(
                text(
                    "INSERT INTO gda_ontology.ontology_draft ("
                    "draft_id, ontology_key, base_version_id, base_content_sha256, title, "
                    "description, created_by, updated_by) VALUES ("
                    "CAST(:draft_id AS uuid), :ontology_key, CAST(:base_version_id AS uuid), "
                    ":base_hash, :title, :description, :actor, :actor) "
                    "RETURNING draft_id::text AS draft_id, status, revision, created_at, updated_at"
                ),
                {
                    "draft_id": draft_id,
                    "ontology_key": self.profile.ontology_key,
                    "base_version_id": baseline["ontology_version_id"],
                    "base_hash": baseline["content_sha256"],
                    "title": normalized_title,
                    "description": normalized_description,
                    "actor": actor,
                },
            ).first()
        return {
            **_row_dict(row),
            "ontology_key": self.profile.ontology_key,
            "base_version_id": baseline["ontology_version_id"],
            "base_semantic_version": baseline["semantic_version"],
            "base_content_sha256": baseline["content_sha256"],
            "title": normalized_title,
            "description": normalized_description,
            "created_by": actor,
            "updated_by": actor,
        }

    def get_draft(self, draft_id: str, *, actor: str, is_admin: bool = False) -> dict[str, Any]:
        with self.engine.connect() as connection:
            draft = self._draft_row(connection, draft_id, actor=actor, is_admin=is_admin)
            changes = self._changes(connection, draft_id)
            active = self._active_baseline(connection)
        return {
            **draft,
            "changes": changes,
            "change_count": len(changes),
            "base_is_active": draft["base_content_sha256"] == active["content_sha256"],
            "active_semantic_version": active["semantic_version"],
            "active_content_sha256": active["content_sha256"],
        }

    def get_model(
        self,
        draft_id: str,
        *,
        actor: str,
        is_admin: bool = False,
        concept_id: str | None = None,
    ) -> dict[str, Any]:
        with self.engine.connect() as connection:
            draft = self._draft_row(connection, draft_id, actor=actor, is_admin=is_admin)
            changes = self._changes(connection, draft_id)
            state = materialize_model_state(
                self._base_state(connection, draft["base_version_id"]),
                changes,
                profile=self.profile,
            )
        return {
            "draft_id": draft_id,
            "revision": draft["revision"],
            "base_content_sha256": draft["base_content_sha256"],
            **self._model_payload(state, concept_id=concept_id),
        }

    def append_change(
        self,
        draft_id: str,
        *,
        actor: str,
        is_admin: bool,
        expected_revision: int,
        idempotency_key: str | None,
        operation: str,
        entity_type: str,
        entity_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        with self.engine.begin() as connection:
            draft = self._draft_row(
                connection,
                draft_id,
                actor=actor,
                is_admin=is_admin,
                for_update=True,
                require_owner=True,
            )
            if draft["status"] != "draft":
                raise OntologyDraftConflict(
                    "only draft status can be edited", current_revision=draft["revision"]
                )
            normalized_idempotency_key = _clean_text(
                idempotency_key or str(uuid.uuid4()),
                "idempotency_key",
                maximum=128,
                required=True,
            )
            if len(normalized_idempotency_key) < 8:
                raise OntologyDraftValidationError(
                    "idempotency_key must contain at least 8 characters"
                )
            replay = connection.execute(
                text(
                    "SELECT change_id::text AS change_id, sequence_no, operation, entity_type, "
                    "entity_id, payload, actor, created_at FROM gda_ontology.ontology_draft_change "
                    "WHERE draft_id = CAST(:draft_id AS uuid) AND idempotency_key = :key"
                ),
                {"draft_id": draft_id, "key": normalized_idempotency_key},
            ).first()
            if replay is not None:
                result = _row_dict(replay)
                stored_payload = result.get("payload") or {}
                if (
                    result.get("operation") != operation
                    or result.get("entity_type") != entity_type
                    or (entity_id and result.get("entity_id") != entity_id)
                    or sha256_json(stored_payload) != sha256_json(payload)
                ):
                    raise OntologyDraftValidationError(
                        "idempotency_key was already used for another change"
                    )
                history = self._changes(connection, draft_id)
                prior_changes = [
                    item
                    for item in history
                    if int(item["sequence_no"]) < int(result["sequence_no"])
                ]
                replay_state = materialize_model_state(
                    self._base_state(connection, draft["base_version_id"]),
                    prior_changes,
                    profile=self.profile,
                )
                normalized = apply_draft_change(
                    replay_state,
                    {
                        "operation": result["operation"],
                        "entity_type": result["entity_type"],
                        "entity_id": result["entity_id"],
                        "payload": stored_payload,
                    },
                    profile=self.profile,
                )
                result.update(
                    {
                        "draft_id": draft_id,
                        "revision": int(draft["revision"]),
                        "change_revision": int(result["sequence_no"]),
                        "before": normalized["before"],
                        "after": normalized["after"],
                        "replayed": True,
                    }
                )
                return result
            if int(draft["revision"]) != int(expected_revision):
                raise OntologyDraftConflict(
                    "draft revision is stale", current_revision=int(draft["revision"])
                )
            if int(draft["revision"]) >= MAX_DRAFT_CHANGES:
                raise OntologyDraftValidationError("draft change limit exceeded")

            changes = self._changes(connection, draft_id)
            state = materialize_model_state(
                self._base_state(connection, draft["base_version_id"]),
                changes,
                profile=self.profile,
            )
            normalized = apply_draft_change(
                state,
                {
                    "operation": operation,
                    "entity_type": entity_type,
                    "entity_id": entity_id,
                    "payload": payload,
                },
                profile=self.profile,
            )
            normalized_entity_id = normalized["entity_id"]
            change_id = str(uuid.uuid4())
            revision = int(draft["revision"]) + 1
            connection.execute(
                text(
                    "INSERT INTO gda_ontology.ontology_draft_change ("
                    "change_id, draft_id, sequence_no, idempotency_key, operation, entity_type, "
                    "entity_id, payload, actor"
                    ") VALUES (CAST(:change_id AS uuid), CAST(:draft_id AS uuid), :sequence_no, "
                    ":idempotency_key, :operation, :entity_type, :entity_id, "
                    "CAST(:payload AS jsonb), :actor)"
                ),
                {
                    "change_id": change_id,
                    "draft_id": draft_id,
                    "sequence_no": revision,
                    "idempotency_key": normalized_idempotency_key,
                    "operation": operation,
                    "entity_type": entity_type,
                    "entity_id": normalized_entity_id,
                    "payload": json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                    "actor": actor,
                },
            )
            connection.execute(
                text(
                    "UPDATE gda_ontology.ontology_draft "
                    "SET revision = :revision, updated_by = :actor "
                    "WHERE draft_id = CAST(:draft_id AS uuid)"
                ),
                {"revision": revision, "actor": actor, "draft_id": draft_id},
            )
            # Validate the materialized post-change state so the response is
            # useful to the editor immediately after a command is accepted.
            validation = validate_model_state(state, profile=self.profile)
        return {
            "draft_id": draft_id,
            "change_id": change_id,
            "revision": revision,
            "change_revision": revision,
            "operation": operation,
            "entity_type": entity_type,
            "entity_id": normalized_entity_id,
            "before": normalized["before"],
            "after": normalized["after"],
            "validation": {
                "conforms": validation["conforms"],
                "issue_count": validation["issue_count"],
                "severity_counts": validation["severity_counts"],
            },
        }

    def validate_draft(
        self, draft_id: str, *, actor: str, is_admin: bool = False
    ) -> dict[str, Any]:
        with self.engine.connect() as connection:
            draft = self._draft_row(connection, draft_id, actor=actor, is_admin=is_admin)
            active = self._active_baseline(connection)
            state = materialize_model_state(
                self._base_state(connection, draft["base_version_id"]),
                self._changes(connection, draft_id),
                profile=self.profile,
            )
        report = validate_model_state(
            state,
            base_is_active=draft["base_content_sha256"] == active["content_sha256"],
            profile=self.profile,
        )
        report.update(
            {
                "draft_id": draft_id,
                "revision": draft["revision"],
                "base_content_sha256": draft["base_content_sha256"],
                "active_content_sha256": active["content_sha256"],
                "model_sha256": self._model_payload(state)["model_sha256"],
                "validation_scope": "draft_structural_review",
                "quality_gates": {
                    "shacl": "pending_release_validation",
                    "competency_questions": "pending_release_validation",
                    "owlrl": "pending_release_validation",
                    "provenance": "pending_release_validation",
                },
                "quality_gates_pending": ["shacl", "competency_questions", "owlrl", "provenance"],
                "structural_review_submission_allowed": report["conforms"],
                "submission_allowed": report["conforms"],
                "publication_allowed": False,
            }
        )
        return report

    def diff(self, draft_id: str, *, actor: str, is_admin: bool = False) -> dict[str, Any]:
        with self.engine.connect() as connection:
            draft = self._draft_row(connection, draft_id, actor=actor, is_admin=is_admin)
            base_state = self._base_state(connection, draft["base_version_id"])
            draft_state = materialize_model_state(
                base_state,
                self._changes(connection, draft_id),
                profile=self.profile,
            )
        return {
            "draft_id": draft_id,
            "revision": draft["revision"],
            "base_semantic_version": draft["base_semantic_version"],
            **compute_model_diff(base_state, draft_state),
        }

    def submit(
        self,
        draft_id: str,
        *,
        actor: str,
        is_admin: bool,
        expected_revision: int,
    ) -> dict[str, Any]:
        report = self.validate_draft(draft_id, actor=actor, is_admin=is_admin)
        if not report["conforms"]:
            raise OntologyDraftValidationError(
                "draft must pass structural validation before review"
            )
        with self.engine.begin() as connection:
            draft = self._draft_row(
                connection,
                draft_id,
                actor=actor,
                is_admin=is_admin,
                for_update=True,
                require_owner=True,
            )
            if draft["status"] != "draft":
                raise OntologyDraftConflict(
                    "only a draft can be submitted", current_revision=draft["revision"]
                )
            active = self._active_baseline(connection)
            if draft["base_content_sha256"] != active["content_sha256"]:
                raise OntologyDraftConflict("draft baseline is no longer the active ontology hash")
            if int(draft["revision"]) != int(expected_revision):
                raise OntologyDraftConflict(
                    "draft revision is stale", current_revision=int(draft["revision"])
                )
            if int(draft["revision"]) == 0:
                raise OntologyDraftValidationError("an unchanged draft cannot be submitted")
            connection.execute(
                text(
                    "UPDATE gda_ontology.ontology_draft SET status = 'in_review', "
                    "submitted_at = now(), submitted_by = :actor, updated_by = :actor "
                    "WHERE draft_id = CAST(:draft_id AS uuid)"
                ),
                {"actor": actor, "draft_id": draft_id},
            )
        return {
            "draft_id": draft_id,
            "status": "in_review",
            "revision": int(draft["revision"]),
            "submitted_by": actor,
            "validation_scope": "draft_structural_review",
            "publication_allowed": False,
            "quality_gates_pending": ["shacl", "competency_questions", "owlrl", "provenance"],
            "next_gate": "human_review_and_full_release_validation",
        }

    def abandon(
        self,
        draft_id: str,
        *,
        actor: str,
        is_admin: bool,
        expected_revision: int,
    ) -> dict[str, Any]:
        """Close an editable draft without mutating or deleting its history."""
        with self.engine.begin() as connection:
            draft = self._draft_row(
                connection,
                draft_id,
                actor=actor,
                is_admin=is_admin,
                for_update=True,
                require_owner=True,
            )
            if draft["status"] != "draft":
                raise OntologyDraftConflict(
                    "only an editable draft can be abandoned",
                    current_revision=int(draft["revision"]),
                )
            if int(draft["revision"]) != int(expected_revision):
                raise OntologyDraftConflict(
                    "draft revision is stale", current_revision=int(draft["revision"])
                )
            connection.execute(
                text(
                    "UPDATE gda_ontology.ontology_draft SET status = 'abandoned', "
                    "updated_by = :actor WHERE draft_id = CAST(:draft_id AS uuid)"
                ),
                {"actor": actor, "draft_id": draft_id},
            )
        return {
            "draft_id": draft_id,
            "status": "abandoned",
            "revision": int(draft["revision"]),
            "updated_by": actor,
        }


_draft_services: dict[str, OntologyDraftService] = {}
_draft_service_lock = threading.Lock()


def get_ontology_draft_service(
    ontology_key: str = ONTOLOGY_KEY,
    *,
    refresh: bool = False,
) -> OntologyDraftService:
    profile = get_ontology_profile(ontology_key)
    key = profile.ontology_key
    if key not in _draft_services or refresh:
        with _draft_service_lock:
            if key not in _draft_services or refresh:
                _draft_services[key] = OntologyDraftService(ontology_key=key)
    return _draft_services[key]
