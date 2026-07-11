"""Closed-world contracts for the parcel-scale geospatial kernel."""

from __future__ import annotations

from typing import Any


GEOSPATIAL_KERNEL_SCHEMA = "uwm.geospatial_kernel.contract.v1"
MAX_CLAIM_LEVEL = "bounded_action_conditioned_spatial_scenario"

NODE_TYPES = sorted(
    ["parcel", "planning_resource", "facility", "village_context", "admin_context"]
)
RELATION_TYPES = sorted(
    [
        "parcel_adjacent_parcel",
        "parcel_near_parcel",
        "parcel_contains_resource",
        "parcel_near_facility",
        "parcel_within_village",
        "village_within_admin",
        "functional_compatibility",
        "cross_scale_context",
    ]
)
STATE_TIMES = ["t0_current", "t1_post_change", "t2_neighborhood_adaptation"]
SUPPORT_LEVELS = sorted(
    [
        "deterministic_geometry",
        "authoritative_rule",
        "bounded_proxy",
        "learned_calibrated",
        "unavailable",
    ]
)
EFFECT_LEVELS = sorted(
    [
        "observed_state_change",
        "rule_supported_effect",
        "geometry_supported_signal",
        "unresolved_effect",
        "unavailable_prediction",
    ]
)
PARCEL_LAND_USE_FIELDS = sorted(
    [
        "current_land_use_class",
        "planned_land_use_class",
        "candidate_land_use_class",
        "source_land_use_code",
    ]
)
DEFAULT_ENABLED_SUPPORT_LEVELS = [
    "deterministic_geometry",
    "authoritative_rule",
    "bounded_proxy",
]


def build_geospatial_kernel_contract(
    *, kernel_version: str, evidence_refs: list[str]
) -> dict[str, Any]:
    """Return the immutable semantic boundary used by kernel components."""

    return {
        "schema": GEOSPATIAL_KERNEL_SCHEMA,
        "kernel_version": str(kernel_version),
        "node_types": list(NODE_TYPES),
        "relation_types": list(RELATION_TYPES),
        "state_times": list(STATE_TIMES),
        "support_levels": list(SUPPORT_LEVELS),
        "enabled_support_levels": list(DEFAULT_ENABLED_SUPPORT_LEVELS),
        "effect_levels": list(EFFECT_LEVELS),
        "parcel_land_use_fields": list(PARCEL_LAND_USE_FIELDS),
        "evidence_refs": [str(value) for value in evidence_refs if str(value).strip()],
        "calibration_evidence_refs": [],
        "trusted_actor_source": "server_authenticated_identity",
        "claim_boundary": {"max_claim_level": MAX_CLAIM_LEVEL},
        "empirical_policy_effect_claim": False,
    }

