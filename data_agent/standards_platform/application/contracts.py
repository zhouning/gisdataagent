"""Pure contracts and scoring for standard-version-bound field mapping."""
from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from difflib import SequenceMatcher

EmbeddingProvider = Callable[[list[str]], list[list[float]]]


@dataclass(frozen=True)
class SourceFieldProfile:
    name: str
    dtype: str = ""
    samples: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class DatasetColumnProfile:
    name: str
    dtype: str
    row_count: int
    null_count: int = 0
    invalid_geometry_count: int = 0


@dataclass(frozen=True)
class StandardDataElement:
    id: str
    document_version_id: str
    code: str
    name_zh: str
    name_en: str = ""
    definition: str = ""
    representation_class: str = ""
    datatype: str = ""
    unit: str = ""
    obligation: str = "optional"
    bound_table: str = ""
    bound_column: str = ""
    aliases: tuple[str, ...] = field(default_factory=tuple)
    embedding: tuple[float, ...] = field(default_factory=tuple, repr=False)

    @property
    def target_field(self) -> str:
        return (self.bound_column or self.code).strip()

    @property
    def labels(self) -> tuple[str, ...]:
        return tuple(
            value for value in (
                self.code,
                self.name_zh,
                self.name_en,
                self.bound_column,
                *self.aliases,
            ) if value and value.strip()
        )

    @property
    def semantic_text(self) -> str:
        return " ".join(value for value in (
            self.code,
            self.name_zh,
            self.name_en,
            self.definition,
            self.datatype,
            self.unit,
            *self.aliases,
        ) if value and value.strip())


@dataclass(frozen=True)
class MappingCandidate:
    target_data_element_id: str
    target_field: str
    code: str
    name_zh: str
    confidence: float
    lexical_score: float
    semantic_score: float | None
    type_score: float
    matched_on: str
    method: str

    def to_dict(self) -> dict:
        return {
            "target_data_element_id": self.target_data_element_id,
            "target_field": self.target_field,
            "code": self.code,
            "name_zh": self.name_zh,
            "confidence": self.confidence,
            "evidence": {
                "lexical_score": self.lexical_score,
                "semantic_score": self.semantic_score,
                "type_score": self.type_score,
                "matched_on": self.matched_on,
            },
            "match_method": self.method,
        }


def propose_standard_mapping(
    *,
    source_fields: Sequence[SourceFieldProfile],
    standard_version_id: str,
    elements: Sequence[StandardDataElement],
    target_table: str | None = None,
    embedding_provider: EmbeddingProvider | None = None,
    recommendation_threshold: float = 0.80,
    review_threshold: float = 0.58,
    ambiguity_margin: float = 0.08,
    max_candidates: int = 3,
) -> dict:
    """Return an auditable proposal without modifying source or target data.

    Only unambiguous high-confidence candidates enter ``mapping``. Everything
    else remains an explicit review item. A caller may use an embedding
    provider, but deterministic lexical/type evidence is always retained.
    """
    if not standard_version_id:
        raise ValueError("standard_version_id is required")
    if not 0 <= review_threshold <= recommendation_threshold <= 1:
        raise ValueError("mapping thresholds must satisfy 0 <= review <= recommendation <= 1")
    if not 0 <= ambiguity_margin <= 1:
        raise ValueError("ambiguity_margin must be between 0 and 1")
    if max_candidates < 1:
        raise ValueError("max_candidates must be positive")

    source_fields = tuple(source_fields)
    elements = tuple(e for e in elements if e.target_field)
    normalized_target_table = (target_table or "").strip()
    if target_table is not None and not normalized_target_table:
        raise ValueError("target_table must not be blank")
    if normalized_target_table:
        elements = tuple(
            element
            for element in elements
            if element.bound_table.casefold() == normalized_target_table.casefold()
        )
        if not elements:
            raise ValueError(
                f"target_table {normalized_target_table!r} has no standard elements"
            )
    semantic_scores = _semantic_score_matrix(
        source_fields, elements, embedding_provider,
    )

    proposals: list[dict] = []
    for source_index, source in enumerate(source_fields):
        ranked: list[MappingCandidate] = []
        for element_index, element in enumerate(elements):
            lexical, matched_on = _lexical_score(source.name, element.labels)
            semantic = (
                semantic_scores[source_index][element_index]
                if semantic_scores is not None else None
            )
            type_score = _type_compatibility(source.dtype, element)
            if semantic is None:
                confidence = 0.80 * lexical + 0.20 * type_score
                method = "lexical_type"
            else:
                confidence = (
                    0.70 * lexical + 0.20 * max(0.0, semantic)
                    + 0.10 * type_score
                )
                method = "hybrid_embedding"
            ranked.append(MappingCandidate(
                target_data_element_id=element.id,
                target_field=element.target_field,
                code=element.code,
                name_zh=element.name_zh,
                confidence=round(min(max(confidence, 0.0), 1.0), 6),
                lexical_score=round(lexical, 6),
                semantic_score=round(semantic, 6) if semantic is not None else None,
                type_score=round(type_score, 6),
                matched_on=matched_on,
                method=method,
            ))
        ranked.sort(key=lambda item: (
            -item.confidence,
            item.code.casefold(),
            item.target_data_element_id,
        ))
        top = ranked[:max_candidates]
        best = top[0] if top else None
        runner_up = top[1] if len(top) > 1 else None
        margin = (
            best.confidence - runner_up.confidence
            if best is not None and runner_up is not None else 1.0
        )
        if best is None or best.confidence < review_threshold:
            disposition = "unmatched"
        elif (
            best.confidence >= recommendation_threshold
            and margin >= ambiguity_margin
        ):
            disposition = "recommended"
        else:
            disposition = "review_required"
        proposals.append({
            "source_field": source.name,
            "source_dtype": source.dtype,
            "samples": list(source.samples),
            "disposition": disposition,
            "confidence_margin": round(margin, 6),
            "candidates": [candidate.to_dict() for candidate in top],
        })

    _mark_target_conflicts(proposals)
    mapping = {
        proposal["source_field"]: proposal["candidates"][0]["target_field"]
        for proposal in proposals
        if proposal["disposition"] == "recommended"
        and proposal["candidates"]
    }
    return {
        "schema": "gis-data-agent.standard-mapping-proposal.v1",
        "standard_version_id": standard_version_id,
        "target_scope": {
            "bound_table": normalized_target_table or None,
            "candidate_elements": len(elements),
        },
        "source_profile_hash": _source_profile_hash(source_fields),
        "mapping": mapping,
        "proposals": proposals,
        "summary": {
            "source_fields": len(source_fields),
            "standard_elements": len(elements),
            "recommended": sum(p["disposition"] == "recommended" for p in proposals),
            "review_required": sum(p["disposition"] == "review_required" for p in proposals),
            "unmatched": sum(p["disposition"] == "unmatched" for p in proposals),
            "conflicts": sum(p["disposition"] == "conflict" for p in proposals),
        },
        "thresholds": {
            "recommendation": recommendation_threshold,
            "review": review_threshold,
            "ambiguity_margin": ambiguity_margin,
        },
        "execution_policy": {
            "mode": "proposal_only",
            "automatic_authoritative_write": False,
            "supported_transform": "rename",
            "requires_human_confirmation": True,
        },
        "review_state": {
            "status": "awaiting_human_review",
            "pending": len(source_fields),
            "approved": 0,
            "rejected": 0,
        },
        "publication": {
            "status": "not_published",
            "ready": False,
            "blockers": [
                "human_review_required",
                "standard_mapping_quality_gate_not_passed",
                "dataset_quality_validation_not_run",
                "data_product_version_not_created",
            ],
        },
    }


def evaluate_mapping_quality_gate(
    *,
    source_fields: Sequence[str],
    field_bindings: Sequence[dict],
    review_decisions: Sequence[dict],
    mandatory_elements: Sequence[StandardDataElement],
    source_profile_hash: str | None,
    target_table: str | None,
) -> dict:
    """Evaluate the human-reviewed mapping without claiming product release.

    Every profiled source field must have an explicit approve/reject decision.
    Mandatory coverage is evaluated only inside the selected target table so a
    multi-domain standard cannot accidentally require unrelated data elements.
    """
    normalized_sources = [str(value).strip() for value in source_fields]
    if any(not value for value in normalized_sources):
        raise ValueError("source_fields must contain non-empty strings")
    if len(set(normalized_sources)) != len(normalized_sources):
        raise ValueError("source_fields must be unique")

    decision_by_source: dict[str, dict] = {}
    allowed_reasons = {
        "recommendation_accepted",
        "manual_match",
        "not_applicable",
        "no_suitable_standard_element",
    }
    for raw in review_decisions:
        if not isinstance(raw, dict):
            raise ValueError("each review decision must be an object")
        source_field = str(raw.get("source_field") or "").strip()
        decision = str(raw.get("decision") or "").strip()
        reason = str(raw.get("reason") or "").strip()
        if not source_field:
            raise ValueError("review decision source_field is required")
        if source_field in decision_by_source:
            raise ValueError(f"duplicate review decision: {source_field}")
        if decision not in {"approved", "rejected"}:
            raise ValueError("review decision must be approved or rejected")
        if reason and reason not in allowed_reasons:
            raise ValueError(f"unsupported review decision reason: {reason}")
        decision_by_source[source_field] = {
            "source_field": source_field,
            "decision": decision,
            "reason": reason or (
                "manual_match" if decision == "approved"
                else "no_suitable_standard_element"
            ),
        }

    source_set = set(normalized_sources)
    unexpected = set(decision_by_source) - source_set
    if unexpected:
        raise ValueError(
            "review decisions contain unknown source fields: "
            + ", ".join(sorted(unexpected))
        )
    approved_sources = {
        source for source, item in decision_by_source.items()
        if item["decision"] == "approved"
    }
    binding_sources = {
        str(item.get("source_field") or "").strip()
        for item in field_bindings
    }
    if approved_sources != binding_sources:
        raise ValueError("approved review decisions must match field bindings")

    mapped_target_ids = {
        str(item.get("target_data_element_id") or "").strip()
        for item in field_bindings
    }
    missing_mandatory = sorted(
        (
            {
                "target_data_element_id": element.id,
                "code": element.code,
                "name_zh": element.name_zh,
                "target_field": element.target_field,
            }
            for element in mandatory_elements
            if element.id not in mapped_target_ids
        ),
        key=lambda item: (item["code"], item["target_data_element_id"]),
    )
    pending_sources = sorted(source_set - set(decision_by_source))
    approved_count = len(approved_sources)
    rejected_count = sum(
        item["decision"] == "rejected" for item in decision_by_source.values()
    )
    mandatory_total = len(mandatory_elements)
    mandatory_mapped = mandatory_total - len(missing_mandatory)
    checks = [
        {
            "id": "source_profile_bound",
            "status": "passed" if source_profile_hash else "blocked",
        },
        {
            "id": "target_scope_bound",
            "status": "passed" if target_table else "blocked",
        },
        {
            "id": "human_review_complete",
            "status": "passed" if not pending_sources else "blocked",
        },
        {
            "id": "mapping_present",
            "status": "passed" if approved_count else "blocked",
        },
        {
            "id": "mandatory_elements_covered",
            "status": "passed" if not missing_mandatory else "blocked",
        },
    ]
    status = (
        "passed" if all(item["status"] == "passed" for item in checks)
        else "blocked"
    )
    return {
        "schema": "gis-data-agent.standard-mapping-quality-gate.v1",
        "status": status,
        "checks": checks,
        "summary": {
            "source_fields": len(normalized_sources),
            "approved": approved_count,
            "rejected": rejected_count,
            "pending": len(pending_sources),
            "mandatory_elements": mandatory_total,
            "mandatory_mapped": mandatory_mapped,
        },
        "pending_source_fields": pending_sources,
        "missing_mandatory_elements": missing_mandatory,
        "review_decisions": [
            decision_by_source[key] for key in sorted(decision_by_source)
        ],
        "target_table": target_table,
    }


def mapping_publication_status(quality_gate: dict) -> dict:
    """Describe publication truth after mapping review.

    A passed mapping gate is necessary but cannot substitute for dataset-level
    quality validation or creation of a governed DataProductVersion.
    """
    blockers = []
    if quality_gate.get("status") != "passed":
        blockers.append("standard_mapping_quality_gate_not_passed")
    blockers.extend([
        "dataset_quality_validation_not_run",
        "data_product_version_not_created",
    ])
    return {
        "status": "not_published",
        "ready": False,
        "blockers": blockers,
        "next_stage": "dataset_quality_validation",
    }


def evaluate_dataset_quality_preflight(
    *,
    mapping_contract_id: str,
    mapping_hash: str,
    source_snapshot_hash: str | None,
    sample_fingerprint: str,
    requested_limit: int,
    observed_records: int,
    columns: Sequence[DatasetColumnProfile],
    field_bindings: Sequence[dict],
) -> dict:
    """Evaluate a read-only sample without claiming full-dataset assurance."""
    if not mapping_contract_id:
        raise ValueError("mapping_contract_id is required")
    for name, digest in (
        ("mapping_hash", mapping_hash),
        ("sample_fingerprint", sample_fingerprint),
    ):
        if not re.fullmatch(r"[0-9a-f]{64}", digest or ""):
            raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    if source_snapshot_hash is not None and not re.fullmatch(
        r"[0-9a-f]{64}", source_snapshot_hash,
    ):
        raise ValueError(
            "source_snapshot_hash must be a lowercase SHA-256 digest",
        )
    if requested_limit < 1 or requested_limit > 1000:
        raise ValueError("requested_limit must be between 1 and 1000")
    if observed_records < 0 or observed_records > requested_limit:
        raise ValueError("observed_records must be within the requested limit")

    column_by_name: dict[str, DatasetColumnProfile] = {}
    for profile in columns:
        if not profile.name or profile.name in column_by_name:
            raise ValueError("column profile names must be non-empty and unique")
        if (
            profile.row_count != observed_records
            or profile.null_count < 0
            or profile.null_count > observed_records
            or profile.invalid_geometry_count < 0
            or profile.invalid_geometry_count > observed_records
        ):
            raise ValueError("column profile counts are inconsistent")
        column_by_name[profile.name] = profile

    normalized_bindings = []
    seen_sources: set[str] = set()
    for raw in field_bindings:
        if not isinstance(raw, dict):
            raise ValueError("each field binding must be an object")
        source_field = str(raw.get("source_field") or "").strip()
        target_field = str(raw.get("target_field") or "").strip()
        if not source_field or not target_field:
            raise ValueError("field binding source and target are required")
        if source_field in seen_sources:
            raise ValueError(f"duplicate source field: {source_field}")
        seen_sources.add(source_field)
        normalized_bindings.append({
            "source_field": source_field,
            "target_field": target_field,
            "target_data_element_id": str(
                raw.get("target_data_element_id") or "",
            ),
            "datatype": str(raw.get("datatype") or ""),
            "representation_class": str(
                raw.get("representation_class") or "",
            ),
            "obligation": str(raw.get("obligation") or "optional"),
        })

    missing_sources = sorted(
        source for source in seen_sources if source not in column_by_name
    )
    mandatory_nulls = sorted(
        (
            {
                "source_field": binding["source_field"],
                "target_field": binding["target_field"],
                "null_count": column_by_name[binding["source_field"]].null_count,
            }
            for binding in normalized_bindings
            if binding["obligation"] == "mandatory"
            and binding["source_field"] in column_by_name
            and column_by_name[binding["source_field"]].null_count > 0
        ),
        key=lambda item: item["source_field"],
    )
    type_mismatches = []
    for binding in normalized_bindings:
        profile = column_by_name.get(binding["source_field"])
        if profile is None:
            continue
        target = StandardDataElement(
            id=binding["target_data_element_id"],
            document_version_id="preflight",
            code=binding["target_field"],
            name_zh=binding["target_field"],
            datatype=binding["datatype"],
            representation_class=binding["representation_class"],
        )
        compatibility = _type_compatibility(profile.dtype, target)
        if compatibility == 0:
            type_mismatches.append({
                "source_field": binding["source_field"],
                "target_field": binding["target_field"],
                "source_dtype": profile.dtype,
                "target_datatype": binding["datatype"],
            })
    type_mismatches.sort(key=lambda item: item["source_field"])

    geometry_profiles = sorted(
        (
            profile for profile in columns
            if _source_type(profile.dtype) == "geometry"
        ),
        key=lambda item: item.name,
    )
    invalid_geometries = [
        {
            "source_field": profile.name,
            "invalid_count": profile.invalid_geometry_count,
        }
        for profile in geometry_profiles
        if profile.invalid_geometry_count > 0
    ]
    checks = [
        {
            "id": "sample_available",
            "status": "passed" if observed_records else "blocked",
            "severity": "critical",
            "metrics": {"observed_records": observed_records},
        },
        {
            "id": "mapped_source_fields_present",
            "status": "passed" if not missing_sources else "failed",
            "severity": "critical",
            "metrics": {
                "mapped_fields": len(normalized_bindings),
                "missing_source_fields": missing_sources,
            },
        },
        {
            "id": "mandatory_sample_values_complete",
            "status": "passed" if not mandatory_nulls else "failed",
            "severity": "critical",
            "metrics": {"fields_with_nulls": mandatory_nulls},
        },
        {
            "id": "mapped_datatypes_compatible",
            "status": "passed" if not type_mismatches else "failed",
            "severity": "high",
            "metrics": {"mismatches": type_mismatches},
        },
        {
            "id": "sample_geometries_valid",
            "status": (
                "not_applicable" if not geometry_profiles
                else "passed" if not invalid_geometries else "failed"
            ),
            "severity": "critical",
            "metrics": {
                "geometry_fields": len(geometry_profiles),
                "invalid_geometries": invalid_geometries,
            },
        },
    ]
    if not observed_records:
        verdict = "blocked"
    elif any(check["status"] == "failed" for check in checks):
        verdict = "failed"
    else:
        verdict = "passed"

    release_blockers = []
    if verdict != "passed":
        release_blockers.append("dataset_sample_preflight_not_passed")
    release_blockers.extend([
        "full_dataset_quality_assessment_not_recorded",
        "data_product_version_not_created",
    ])
    result = {
        "schema": "gis-data-agent.dataset-quality-preflight.v1",
        "verdict": verdict,
        "mapping_contract_id": mapping_contract_id,
        "mapping_hash": mapping_hash,
        "source_snapshot_hash": source_snapshot_hash,
        "scope": {
            "mode": "sample",
            "requested_limit": requested_limit,
            "observed_records": observed_records,
            "full_dataset_validated": False,
            "authoritative_quality_assessment": False,
        },
        "sample_fingerprint": sample_fingerprint,
        "checks": checks,
        "summary": {
            "passed": sum(check["status"] == "passed" for check in checks),
            "failed": sum(check["status"] == "failed" for check in checks),
            "blocked": sum(check["status"] == "blocked" for check in checks),
            "not_applicable": sum(
                check["status"] == "not_applicable" for check in checks
            ),
        },
        "release_candidate": {
            "status": "blocked",
            "data_product_version_created": False,
            "blockers": release_blockers,
        },
    }
    result["preflight_sha256"] = hashlib.sha256(json.dumps(
        result, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()
    return result


def _mark_target_conflicts(proposals: list[dict]) -> None:
    by_target: dict[str, list[dict]] = {}
    for proposal in proposals:
        if proposal["disposition"] != "recommended" or not proposal["candidates"]:
            continue
        target_field = proposal["candidates"][0]["target_field"].casefold()
        by_target.setdefault(target_field, []).append(proposal)
    for target_proposals in by_target.values():
        if len(target_proposals) < 2:
            continue
        source_fields = sorted(p["source_field"] for p in target_proposals)
        for proposal in target_proposals:
            proposal["disposition"] = "conflict"
            proposal["conflict"] = {
                "reason": "multiple_source_fields_target_same_target_field",
                "source_fields": source_fields,
            }


def _normalize(value: str) -> str:
    return "".join(ch for ch in value.casefold() if ch.isalnum())


def _tokens(value: str) -> set[str]:
    return {
        token for token in re.split(r"[^\w\u4e00-\u9fff]+", value.casefold())
        if token
    }


def _lexical_score(source_name: str, labels: Iterable[str]) -> tuple[float, str]:
    source_normalized = _normalize(source_name)
    source_tokens = _tokens(source_name)
    best_score = 0.0
    best_label = ""
    for label in labels:
        label_normalized = _normalize(label)
        if not source_normalized or not label_normalized:
            continue
        if source_normalized == label_normalized:
            score = 1.0
        else:
            sequence = SequenceMatcher(
                None, source_normalized, label_normalized,
            ).ratio()
            label_tokens = _tokens(label)
            union = source_tokens | label_tokens
            token_score = (
                len(source_tokens & label_tokens) / len(union) if union else 0.0
            )
            containment = 0.0
            shorter = min(len(source_normalized), len(label_normalized))
            if shorter >= 3 and (
                source_normalized in label_normalized
                or label_normalized in source_normalized
            ):
                containment = shorter / max(
                    len(source_normalized), len(label_normalized),
                )
            score = max(sequence, token_score, containment)
        if score > best_score:
            best_score = score
            best_label = label
    return best_score, best_label


def _source_type(dtype: str) -> str:
    value = dtype.casefold()
    if any(token in value for token in ("geometry", "point", "polygon", "linestring")):
        return "geometry"
    if "datetime" in value or "timestamp" in value or value.startswith("date"):
        return "datetime"
    if "bool" in value:
        return "boolean"
    if any(token in value for token in ("float", "double", "decimal", "numeric")):
        return "decimal"
    if any(token in value for token in ("int", "long")):
        return "integer"
    if any(token in value for token in ("str", "string", "object", "char", "text")):
        return "text"
    return "unknown"


def _target_type(element: StandardDataElement) -> str:
    value = f"{element.representation_class} {element.datatype}".casefold()
    if "geometry" in value:
        return "geometry"
    if "datetime" in value or "timestamp" in value or "date" in value:
        return "datetime"
    if "bool" in value:
        return "boolean"
    if any(token in value for token in ("decimal", "numeric", "float", "double", "real")):
        return "decimal"
    if any(token in value for token in ("integer", "int", "long")):
        return "integer"
    if any(token in value for token in ("code", "text", "string", "char", "varchar")):
        return "text"
    return "unknown"


def _type_compatibility(dtype: str, element: StandardDataElement) -> float:
    source = _source_type(dtype)
    target = _target_type(element)
    if source == "unknown" or target == "unknown":
        return 0.5
    if source == target:
        return 1.0
    if {source, target} <= {"integer", "decimal"}:
        return 0.75
    return 0.0


def _semantic_score_matrix(
    source_fields: Sequence[SourceFieldProfile],
    elements: Sequence[StandardDataElement],
    provider: EmbeddingProvider | None,
) -> list[list[float]] | None:
    if provider is None or not source_fields or not elements:
        return None
    source_texts = [f"{field.name} {field.dtype}".strip() for field in source_fields]
    try:
        if all(element.embedding for element in elements):
            source_embeddings = provider(source_texts)
            if len(source_embeddings) != len(source_texts):
                return None
            target_embeddings = [element.embedding for element in elements]
        else:
            target_texts = [element.semantic_text for element in elements]
            embeddings = provider(source_texts + target_texts)
            if len(embeddings) != len(source_texts) + len(target_texts):
                return None
            source_embeddings = embeddings[:len(source_texts)]
            target_embeddings = embeddings[len(source_texts):]
    except Exception:
        return None
    return [
        [_cosine(source, target) for target in target_embeddings]
        for source in source_embeddings
    ]


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


def _source_profile_hash(source_fields: Sequence[SourceFieldProfile]) -> str:
    payload = [
        {
            "name": field.name,
            "dtype": field.dtype,
            "samples": list(field.samples),
        }
        for field in source_fields
    ]
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
