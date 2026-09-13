from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from hashlib import sha256
import json
from typing import Any, Mapping

from data_agent.uwm.traditional_livability_facility_dictionary import (
    compute_canonical_content_digest,
)


SCHEMA = "uwm.traditional_livability.s6_s1_handoff.v1"
_INPUT_FIELDS = ("facility_name", "raw_facility_type", "use_description")


def canonical_payload_digest(payload: Mapping[str, Any]) -> str:
    return compute_canonical_content_digest(_json_canonical_value(payload))


def _json_canonical_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_canonical_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_canonical_value(item) for item in value]
    return value


def _text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _confirmation(analysis: Mapping[str, Any]) -> dict[str, Any]:
    value = analysis.get("human_confirmation_validation")
    if isinstance(value, Mapping):
        return deepcopy(dict(value))
    request = analysis.get("normalized_request")
    if isinstance(request, Mapping) and isinstance(request.get("human_confirmation"), Mapping):
        return deepcopy(dict(request["human_confirmation"]))
    return {}


def _proposal(analysis: Mapping[str, Any]) -> dict[str, Any]:
    request = analysis.get("normalized_request")
    request = request if isinstance(request, Mapping) else {}
    geojson = analysis.get("geojson")
    geojson = geojson if isinstance(geojson, Mapping) else {}
    return {
        "analysis_area_id": _text(request.get("analysis_area_id")),
        "input_mode": _text(request.get("input_mode")),
        "longitude": request.get("longitude"),
        "latitude": request.get("latitude"),
        "parcel_id": _text(request.get("parcel_id")),
        "facility_name": _text(request.get("facility_name")),
        "raw_facility_type": _text(request.get("raw_facility_type")),
        "use_description": _text(request.get("use_description")),
        "proposed_geometry": deepcopy(geojson.get("proposed_geometry")),
    }


def _confirmation_matches_proposal(
    confirmation: Mapping[str, Any], proposal: Mapping[str, Any]
) -> bool:
    original_input = confirmation.get("original_input")
    if not isinstance(original_input, Mapping):
        return False
    current_input = {field: proposal.get(field) for field in _INPUT_FIELDS}
    expected_digest = compute_canonical_content_digest(current_input)
    supplied_digest = _text(confirmation.get("original_input_digest"))
    return supplied_digest == expected_digest and all(
        original_input.get(field) == current_input[field] for field in _INPUT_FIELDS
    )


def _applicable_profiles(
    metric_profiles: Mapping[str, Any], class_id: str | None
) -> list[dict[str, Any]]:
    profiles = metric_profiles.get("profiles")
    if not isinstance(profiles, list) or class_id is None:
        return []
    return [
        deepcopy(dict(profile))
        for profile in profiles
        if isinstance(profile, Mapping)
        and profile.get("status") == "valid"
        and _text(profile.get("standard_class_id")) == class_id
    ]


def build_s6_s1_handoff(
    *,
    s6_analysis: Mapping[str, Any],
    metric_profiles: Mapping[str, Any],
    actor_id: str,
    created_at: str,
) -> dict[str, Any]:
    analysis = deepcopy(dict(s6_analysis))
    profiles = deepcopy(dict(metric_profiles))
    proposal = _proposal(analysis)
    confirmation = _confirmation(analysis)
    actor = _text(actor_id)
    confirmed_class_id = _text(confirmation.get("selected_standard_class_id"))
    if confirmed_class_id is None:
        handoff = analysis.get("s1_handoff")
        if isinstance(handoff, Mapping):
            confirmed_class_id = _text(handoff.get("confirmed_standard_class_id"))
    applicable = _applicable_profiles(profiles, confirmed_class_id)

    blockers = []
    if actor is None:
        blockers.append("actor_id_required")
    if _text(created_at) is None:
        blockers.append("created_at_required")
    else:
        try:
            datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        except ValueError:
            blockers.append("created_at_invalid")
    if analysis.get("s1_handoff", {}).get("ready") is not True:
        blockers.append("source_s6_handoff_not_ready")
    if confirmation.get("valid") is not True or confirmed_class_id is None:
        blockers.append("confirmed_standard_class_required")
    if not _confirmation_matches_proposal(confirmation, proposal):
        blockers.append("stale_or_mismatched_human_confirmation")
    if proposal["analysis_area_id"] is None:
        blockers.append("analysis_area_required")
    if not applicable:
        blockers.append("authoritative_s1_metric_profile_missing")

    confirmation["actor_id"] = actor
    source_digest = canonical_payload_digest(analysis)
    identity_payload = {
        "source_s6_analysis_digest": source_digest,
        "actor_id": actor,
        "created_at": created_at,
        "profile_bundle_id": profiles.get("bundle_id"),
    }
    encoded = json.dumps(
        identity_payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    handoff_id = f"s6-s1-{sha256(encoded).hexdigest()[:20]}"
    source_bundle = analysis.get("source_bundle")
    return deepcopy(
        {
            "schema": SCHEMA,
            "handoff_id": handoff_id,
            "created_at": created_at,
            "actor_id": actor,
            "source_s6_analysis_id": analysis.get("analysis_id"),
            "source_s6_analysis_digest": source_digest,
            "proposal": proposal,
            "confirmed_standard_class_id": confirmed_class_id,
            "confirmation": confirmation,
            "semantic_resolution": deepcopy(analysis.get("semantic_resolution")),
            "dictionary_version": confirmation.get("dictionary_version"),
            "dictionary_content_digest": confirmation.get("dictionary_content_digest"),
            "source_resource_bundle": deepcopy(source_bundle),
            "source_s6_status": analysis.get("status"),
            "source_s6_max_claim_level": analysis.get("max_claim_level"),
            "source_s6_applied_rule_ids": deepcopy(analysis.get("applied_rule_ids") or []),
            "metric_profile_bundle_id": profiles.get("bundle_id"),
            "applicable_metric_profiles": applicable,
            "completeness_warnings": deepcopy(analysis.get("completeness_warnings") or []),
            "validation_blockers": list(dict.fromkeys(blockers)),
            "ready_for_s1": not blockers,
            "claim_boundary": {
                "method": "traditional_static_analysis",
                "uwm_rollout": False,
                "future_adaptation_assessed": False,
            },
        }
    )
