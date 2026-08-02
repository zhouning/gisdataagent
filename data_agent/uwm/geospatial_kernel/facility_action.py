"""Typed, server-authorized facility actions for bounded scenario branches."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


FACILITY_ACTION_SCHEMA = "uwm.geospatial_kernel.facility_action.v1"
FACILITY_ACTION_TYPES = {"add_facility", "remove_facility", "no_facility_change"}
RADIUS_EVIDENCE_SOURCES = {"authoritative_profile", "user_scenario_assumption"}


def scenario_facility_id(*, parcel_id: str, facility_class: str) -> str:
    return f"scenario_facility:{parcel_id}:{facility_class}"


def build_facility_action(
    *,
    action_type: str,
    parcel_id: str,
    planning_area_id: str,
    facility_class: str,
    facility_id: str | None,
    service_radius_m: float,
    radius_evidence_source: str,
    placement_geometry_wgs84: dict[str, Any],
    distance_crs: str,
    rationale: str,
    snapshot_digest: str,
    requested_at: str,
) -> dict[str, Any]:
    """Build an untrusted facility request awaiting server authorization."""

    resolved_facility_id = str(facility_id or "")
    if action_type == "add_facility" and not resolved_facility_id:
        resolved_facility_id = scenario_facility_id(
            parcel_id=parcel_id, facility_class=facility_class
        )
    return {
        "schema": FACILITY_ACTION_SCHEMA,
        "action_type": str(action_type),
        "parcel_id": str(parcel_id),
        "planning_area_id": str(planning_area_id),
        "facility_class": str(facility_class),
        "facility_id": resolved_facility_id,
        "service_radius_m": float(service_radius_m),
        "radius_evidence_source": str(radius_evidence_source),
        "placement_geometry_wgs84": deepcopy(placement_geometry_wgs84),
        "placement_method": "target_parcel_representative_point",
        "distance_crs": str(distance_crs),
        "rationale": str(rationale),
        "snapshot_digest": str(snapshot_digest),
        "requested_at": str(requested_at),
        "actor_id": None,
        "actor_binding": "unbound",
        "permission_binding": "unbound",
        "authorized_planning_area_ids": [],
        "evidence_refs": [
            f"source_snapshot:{snapshot_digest}",
            f"radius_evidence:{radius_evidence_source}",
        ],
        "approval_claim": False,
    }


def bind_server_facility_actor(
    action: dict[str, Any],
    *,
    actor_id: str,
    authorized_planning_area_ids: list[str],
) -> dict[str, Any]:
    """Bind authenticated identity and server-resolved area permissions."""

    bound = deepcopy(action)
    bound["actor_id"] = str(actor_id)
    bound["actor_binding"] = "server_authenticated_identity"
    bound["permission_binding"] = "server_authorized_planning_area_scope"
    bound["authorized_planning_area_ids"] = sorted(
        {str(value) for value in authorized_planning_area_ids if str(value)}
    )
    return bound


def build_no_facility_change_action(
    intervention_action: dict[str, Any]
) -> dict[str, Any]:
    """Create the internal baseline contract paired with a facility action."""

    baseline = deepcopy(intervention_action)
    baseline["action_type"] = "no_facility_change"
    baseline["rationale"] = "counterfactual_no_facility_change_baseline"
    return baseline


def validate_facility_action(
    action: dict[str, Any], *, graph: dict[str, Any]
) -> dict[str, Any]:
    """Validate snapshot, target area, evidence, identity and permissions."""

    errors: list[str] = []
    if action.get("schema") != FACILITY_ACTION_SCHEMA:
        errors.append("schema_mismatch")
    action_type = str(action.get("action_type") or "")
    if action_type not in FACILITY_ACTION_TYPES:
        errors.append("invalid_action_type")

    nodes = {str(node.get("node_id")): node for node in graph.get("nodes") or []}
    parcel_id = str(action.get("parcel_id") or "")
    parcel = nodes.get(parcel_id)
    if parcel is None or parcel.get("node_type") != "parcel":
        errors.append("target_parcel_missing")
        parcel = {}
    planning_area_id = str(action.get("planning_area_id") or "")
    if not planning_area_id:
        errors.append("planning_area_id_missing")
    elif str(parcel.get("planning_area_id") or "") != planning_area_id:
        errors.append("target_parcel_planning_area_mismatch")

    if action.get("snapshot_digest") != graph.get("snapshot_digest"):
        errors.append("snapshot_digest_mismatch")
    if action.get("actor_binding") != "server_authenticated_identity" or not action.get(
        "actor_id"
    ):
        errors.append("actor_not_server_bound")
    if action.get("permission_binding") != "server_authorized_planning_area_scope":
        errors.append("permission_not_server_bound")
    authorized = {
        str(value) for value in action.get("authorized_planning_area_ids") or []
    }
    if planning_area_id and planning_area_id not in authorized:
        errors.append("planning_area_permission_denied")
    if not str(action.get("rationale") or "").strip():
        errors.append("rationale_missing")
    if not str(action.get("requested_at") or "").strip():
        errors.append("requested_at_missing")
    if not str(action.get("facility_class") or "").strip():
        errors.append("facility_class_required")
    if not str(action.get("facility_id") or "").strip():
        errors.append("facility_id_required")
    radius = action.get("service_radius_m")
    if (
        not isinstance(radius, (int, float))
        or isinstance(radius, bool)
        or float(radius) <= 0.0
    ):
        errors.append("positive_service_radius_required")
    if action.get("radius_evidence_source") not in RADIUS_EVIDENCE_SOURCES:
        errors.append("radius_evidence_source_required")
    if not str(action.get("distance_crs") or "").strip():
        errors.append("distance_crs_missing")
    geometry = action.get("placement_geometry_wgs84")
    if not isinstance(geometry, dict) or geometry.get("type") != "Point":
        errors.append("placement_point_missing")
    evidence_refs = action.get("evidence_refs")
    if not isinstance(evidence_refs, list) or not evidence_refs:
        errors.append("action_evidence_refs_missing")

    facility_id = str(action.get("facility_id") or "")
    facility = nodes.get(facility_id)
    if action_type == "add_facility" and facility is not None:
        errors.append("duplicate_facility_id")
    if action_type == "remove_facility":
        if facility is None or facility.get("node_type") != "facility":
            errors.append("facility_not_found")
        elif str(facility.get("planning_area_id") or "") != planning_area_id:
            errors.append("facility_planning_area_mismatch")
        if facility is not None:
            node_class = str(facility.get("canonical_class") or "")
            if node_class and node_class != str(action.get("facility_class") or ""):
                errors.append("facility_class_mismatch")

    transition = {
        "status": "allowed" if not errors else "unresolved",
        "human_review_required": True,
        "authority_refs": list(evidence_refs or []),
        "approval_claim": False,
    }
    return {
        "valid": not errors,
        "errors": errors,
        "transition": transition,
        "review_required": True,
        "approval_claim": False,
    }
