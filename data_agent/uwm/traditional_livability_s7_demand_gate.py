from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from hashlib import sha256
import json
import math
from typing import Any, Mapping


SCHEMA = "uwm.traditional_livability.s7_demand_gate.v1"


def _text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _parse_time(value: Any):
    text = _text(value)
    if text is None:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def build_s7_demand_gate(
    *,
    s1_assessment: Mapping[str, Any],
    s7_product: Mapping[str, Any],
    crosswalk_validation: Mapping[str, Any],
    created_at: str,
) -> dict[str, Any]:
    s1 = deepcopy(dict(s1_assessment))
    s7 = deepcopy(dict(s7_product))
    crosswalk = deepcopy(dict(crosswalk_validation))
    blockers = []
    profile = s1.get("profile") if isinstance(s1.get("profile"), Mapping) else {}
    if profile.get("status") != "valid" or profile.get("authority_level") != "authoritative":
        blockers.append("authoritative_s1_metric_profile_missing")
    if crosswalk.get("status") != "valid":
        blockers.append("geography_crosswalk_invalid")
        blockers.extend(crosswalk.get("blockers") or [])
    if s1.get("standard_class_id") != s7.get("facility_class_id"):
        blockers.append("facility_class_mismatch")
    if s1.get("facility_bundle_id") != s7.get("bundle_id"):
        blockers.append("facility_bundle_mismatch")
    if s1.get("admin_code") != crosswalk.get("s1_geography_id"):
        blockers.append("s1_geography_mismatch")
    if set(s7.get("planning_area_ids") or []) != set(crosswalk.get("requested_s7_area_ids") or []):
        blockers.append("s7_planning_areas_mismatch")
    assessment_time = _parse_time(s1.get("created_at"))
    snapshot_time = _parse_time(s7.get("snapshot_at"))
    if assessment_time is None or snapshot_time is None:
        blockers.append("assessment_or_snapshot_time_invalid")
    elif assessment_time < snapshot_time:
        blockers.append("s1_assessment_older_than_s7_snapshot")
    if s1.get("complete_inventory") is not True:
        blockers.append("facility_inventory_incomplete")
    applicable = s1.get("applicable_result") if isinstance(s1.get("applicable_result"), Mapping) else {}
    gap_type = applicable.get("gap_type")
    gap_value = applicable.get("gap_value")
    if gap_type not in {"facility_count_gap", "facility_area_gap_m2", "facility_capacity_gap"}:
        blockers.append("authoritative_gap_type_missing")
    if not isinstance(gap_value, (int, float)) or isinstance(gap_value, bool):
        blockers.append("authoritative_gap_value_missing")
        numeric_gap = None
    else:
        numeric_gap = float(gap_value)

    if blockers:
        state = "need_unresolved"
    elif applicable.get("status") == "does_not_meet" and numeric_gap is not None and numeric_gap > 0:
        state = "authoritative_need_confirmed"
    elif applicable.get("status") == "meets" or (numeric_gap is not None and numeric_gap <= 0):
        state = "authoritative_need_not_confirmed"
    else:
        state = "need_unresolved"
        blockers.append("authoritative_need_status_unresolved")

    required_site_count = None
    gap_closure_assessed = False
    if state == "authoritative_need_not_confirmed":
        required_site_count = 0
        gap_closure_assessed = True
    elif state == "authoritative_need_confirmed" and gap_type == "facility_count_gap":
        required_site_count = int(math.ceil(numeric_gap))
        gap_closure_assessed = True
    identity = {
        "s1_digest": s1.get("content_digest"),
        "s7_digest": s7.get("content_digest"),
        "crosswalk_digest": crosswalk.get("content_digest"),
        "created_at": created_at,
        "state": state,
        "gap_type": gap_type,
        "gap_value": numeric_gap,
    }
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return deepcopy({
        "schema": SCHEMA,
        "gate_id": f"s7-gate-{sha256(encoded).hexdigest()[:20]}",
        "created_at": created_at,
        "state": state,
        "standard_class_id": s1.get("standard_class_id"),
        "s1_geography_id": s1.get("admin_code"),
        "s7_planning_area_ids": deepcopy(s7.get("planning_area_ids") or []),
        "s1_assessment_id": s1.get("assessment_id"),
        "s1_assessment_digest": s1.get("content_digest"),
        "facility_product_id": s1.get("facility_product_id"),
        "facility_bundle_id": s1.get("facility_bundle_id"),
        "s7_product_id": s7.get("product_id"),
        "s7_product_digest": s7.get("content_digest"),
        "crosswalk_id": crosswalk.get("crosswalk_id"),
        "profile": deepcopy(profile),
        "synthesis_matrix": deepcopy(s1.get("synthesis_matrix")),
        "applicable_status": applicable.get("status"),
        "gap": {
            "gap_type": gap_type,
            "gap_value": numeric_gap,
            "unit": applicable.get("unit"),
            "observed_value": applicable.get("observed_value"),
            "threshold": applicable.get("threshold"),
            "comparator": applicable.get("comparator"),
        },
        "required_site_count": required_site_count,
        "gap_closure_assessed": gap_closure_assessed,
        "complete_inventory": s1.get("complete_inventory") is True,
        "uncertainty": s1.get("uncertainty"),
        "blockers": list(dict.fromkeys(blockers)),
        "claim_boundary": {
            "temporal_demand_modelled": False,
            "uwm_rollout": False,
            "authoritative_recommendation_allowed": state == "authoritative_need_confirmed",
        },
    })
