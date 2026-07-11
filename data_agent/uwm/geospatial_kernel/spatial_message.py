"""Traceable spatial messages emitted by the geospatial kernel."""

from __future__ import annotations

import hashlib
import json
from typing import Any


MAX_CLAIM_LEVEL = "bounded_action_conditioned_spatial_scenario"


def build_spatial_message(
    *,
    source_node_id: str,
    target_node_id: str,
    relation_type: str,
    effect_type: str,
    direction: str,
    raw_evidence: dict[str, Any],
    normalization_basis: dict[str, Any],
    propagation_stage: int,
    support_level: str,
    uncertainty: str,
    review_priority: str,
    kernel_version: str,
) -> dict[str, Any]:
    """Build a deterministic evidence message without a synthetic impact score."""

    identity = {
        "source_node_id": source_node_id,
        "target_node_id": target_node_id,
        "relation_type": relation_type,
        "effect_type": effect_type,
        "propagation_stage": int(propagation_stage),
        "kernel_version": kernel_version,
    }
    encoded = json.dumps(
        identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return {
        "message_id": "spatial_message_" + hashlib.sha256(encoded).hexdigest()[:20],
        **identity,
        "direction": direction,
        "raw_evidence": raw_evidence,
        "normalization_basis": normalization_basis,
        "support_level": support_level,
        "uncertainty": uncertainty,
        "review_priority": review_priority,
        "claim_level": MAX_CLAIM_LEVEL,
    }


def spatial_message_digest(messages: list[dict[str, Any]]) -> str:
    """Hash canonical messages for reproducible rollout auditing."""

    encoded = json.dumps(
        messages, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()

