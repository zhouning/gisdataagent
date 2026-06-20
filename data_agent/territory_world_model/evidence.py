from __future__ import annotations

import hashlib
import json
from typing import Any

from .models import TwmEvidenceItem, TwmRuleHit, jsonable, now_utc_iso


def _canonical_json(payload: Any) -> str:
    return json.dumps(jsonable(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def evidence_checksum(payload: Any) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def build_evidence_chain(
    *,
    rule_hit: TwmRuleHit,
    source_feature: dict[str, Any] | None,
    rule_clause: dict[str, Any] | None,
    spatial_calc: dict[str, Any] | None,
    semantic_mapping: dict[str, Any] | None,
    model_output: dict[str, Any] | None = None,
    reviewer_note: dict[str, Any] | None = None,
    source_system: str = "twm",
) -> list[TwmEvidenceItem]:
    items: list[TwmEvidenceItem] = []
    base = {
        "rule_hit_id": rule_hit.id,
        "state_version_id": rule_hit.state_version_id,
        "rule_id": rule_hit.rule_id,
        "subject_object_id": rule_hit.subject_object_id,
        "target_object_id": rule_hit.target_object_id,
    }

    def add_item(evidence_type: str, source_ref: str, payload: dict[str, Any]) -> None:
        merged = {**base, **payload, "evidence_type": evidence_type, "source_ref": source_ref, "created_at": now_utc_iso()}
        items.append(
            TwmEvidenceItem(
                rule_hit_id=rule_hit.id,
                evidence_type=evidence_type,
                source_system=source_system,
                source_ref=source_ref,
                payload=merged,
                checksum=evidence_checksum(merged),
            )
        )

    if source_feature is not None:
        add_item("source_feature", "source_feature", {"source_feature": source_feature})
    if rule_clause is not None:
        add_item("rule_clause", "rule_clause", {"rule_clause": rule_clause})
    if spatial_calc is not None:
        add_item("spatial_calc", "spatial_calc", {"spatial_calc": spatial_calc})
    if semantic_mapping is not None:
        add_item("semantic_mapping", "semantic_mapping", {"semantic_mapping": semantic_mapping})
    if model_output is not None:
        add_item("model_output", "model_output", {"model_output": model_output})
    if reviewer_note is not None:
        add_item("reviewer_note", "reviewer_note", {"reviewer_note": reviewer_note})
    return items
