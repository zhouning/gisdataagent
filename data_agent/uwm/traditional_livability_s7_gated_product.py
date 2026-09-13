from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping

from data_agent.uwm.traditional_livability_facility_dictionary import compute_canonical_content_digest
from data_agent.uwm.traditional_livability_s1_s7_crosswalk import SCHEMA as CROSSWALK_SCHEMA, validate_s1_s7_crosswalk


GATE_FILENAME = "uwm_traditional_livability_s7_demand_gate.json"
SITING_FILENAME = "uwm_traditional_livability_s7_gated.json"
CROSSWALK_FILENAME = "uwm_traditional_livability_s1_s7_crosswalk.json"
MANIFEST_FILENAME = "uwm_traditional_livability_s7_gated_manifest.json"


def _digest(payload: Mapping[str, Any]) -> str:
    return compute_canonical_content_digest(payload)


def _write(path: Path, payload: Mapping[str, Any]):
    path.write_text(json.dumps(payload, ensure_ascii=False, allow_nan=False, indent=2), encoding="utf-8")


def _crosswalk(area_ids):
    payload = {
        "schema": CROSSWALK_SCHEMA,
        "crosswalk_id": "bishan-fulu-planning-v1",
        "source_metadata": {
            "issuing_organisation": "Local planning source packages",
            "source_reference": "Heping and Banzhu village planning datasets",
            "effective_date": "2026-07-11",
            "version": "v1",
        },
        "rows": [
            {
                "s1_geography_id": "500120",
                "s1_geography_name": "璧山区",
                "s7_planning_area_id": area_id,
                "s7_planning_area_name": area_id,
                "relationship_type": "planning_area_within_admin",
                "source_reference": "Fulu village planning package",
            }
            for area_id in area_ids
        ],
    }
    payload["content_digest"] = _digest(payload)
    return payload


def build_gated_s7_product(
    *,
    s7_snapshot: Mapping[str, Any],
    s1_snapshot: Mapping[str, Any],
    facility_product: Mapping[str, Any],
    output_dir: Path,
) -> dict[str, Any]:
    s7 = deepcopy(dict(s7_snapshot))
    s1 = deepcopy(dict(s1_snapshot))
    facility = deepcopy(dict(facility_product))
    if s7.get("schema") != "uwm.traditional_livability.s7_siting.v1":
        return {"ready": False, "blockers": ["s7_snapshot_invalid"]}
    if s1.get("schema") != "uwm.traditional_livability.s1_assessment.v1":
        return {"ready": False, "blockers": ["s1_snapshot_invalid"]}
    if facility.get("schema") != "uwm.traditional_livability.facility_product.v1":
        return {"ready": False, "blockers": ["facility_product_invalid"]}
    area_ids = list(s7.get("planning_area_ids") or [])
    crosswalk = _crosswalk(area_ids)
    validation = validate_s1_s7_crosswalk(
        crosswalk, s1_geography_id="500120", requested_s7_area_ids=area_ids
    )
    identity = {
        "s7_siting_id": s7.get("siting_id"),
        "s7_created_at": s7.get("created_at"),
        "s1_assessment_id": s1.get("assessment_id"),
        "facility_product_id": facility.get("product_id"),
        "crosswalk_digest": crosswalk.get("content_digest"),
    }
    encoded = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    bundle_id = f"traditional-livability-s7-gated-{sha256(encoded).hexdigest()[:20]}"
    blockers = list(dict.fromkeys([
        "authoritative_s1_metric_profile_missing",
        "authoritative_synthesis_matrix_missing",
        "fulu_village_population_or_demand_missing",
        "school_capacity_and_operating_status_missing",
        "facility_inventory_incomplete",
        *(s1.get("production_blockers") or []),
        *(s7.get("production_blockers") or []),
        *(validation.get("blockers") or []),
    ]))
    gate = {
        "schema": "uwm.traditional_livability.s7_demand_gate.v1",
        "bundle_id": bundle_id,
        "gate_id": f"gate-{bundle_id}",
        "state": "need_unresolved",
        "standard_class_id": "education.primary_school",
        "s1_geography_id": "500120",
        "s7_planning_area_ids": area_ids,
        "s1_assessment_id": s1.get("assessment_id"),
        "facility_product_id": facility.get("product_id"),
        "crosswalk_id": crosswalk.get("crosswalk_id"),
        "required_site_count": None,
        "gap": {"gap_type": None, "gap_value": None, "unit": None},
        "gap_closure_assessed": False,
        "blockers": blockers,
        "claim_boundary": {"authoritative_recommendation_allowed": False, "uwm_rollout": False},
    }
    ranked = [{**deepcopy(row), "not_a_site_recommendation": True} for row in s7.get("ranked_candidates") or []]
    selected = [{**deepcopy(row), "not_a_site_recommendation": True} for row in s7.get("selected_sites") or []]
    gated = {
        **s7,
        "schema": "uwm.traditional_livability.s7_gated_siting.v1",
        "bundle_id": bundle_id,
        "mode": "conditional",
        "recommendation_status": "conditional_candidate_ranking_available" if ranked else "conditional_ranking_unavailable",
        "demand_gate": deepcopy(gate),
        "ranked_candidates": ranked,
        "selected_sites": selected,
        "not_a_site_recommendation": True,
        "gap_closure_assessed": False,
        "remaining_gap": None,
        "production_blockers": blockers,
        "claim_boundary": {
            **deepcopy(s7.get("claim_boundary") or {}),
            "max_claim_level": "conditional_static_candidate_ranking",
            "uwm_rollout": False,
            "future_demand_modelled": False,
        },
    }
    crosswalk["bundle_id"] = bundle_id
    manifest = {
        "schema": "uwm.traditional_livability.s7_gated_manifest.v1",
        "bundle_id": bundle_id,
        "workflow_ready": True,
        "authoritative_recommendation_available": False,
        "conditional_ranking_available": bool(ranked),
        "planning_area_count": len(area_ids),
        "ranked_candidate_count": len(ranked),
        "selected_conditional_count": len(selected),
        "blockers": blockers,
        "fabricated_values": [],
        "claim_boundary": {"not_a_site_recommendation": True, "uwm_rollout": False},
    }
    for payload in [crosswalk, gate, gated, manifest]:
        payload["content_digest"] = _digest(payload)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    for filename, payload in {
        CROSSWALK_FILENAME: crosswalk,
        GATE_FILENAME: gate,
        SITING_FILENAME: gated,
        MANIFEST_FILENAME: manifest,
    }.items():
        _write(output / filename, payload)
    return {"ready": True, "bundle_id": bundle_id, "output_dir": str(output), "blockers": blockers}
