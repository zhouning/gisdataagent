"""Evidence gates for unsupported geospatial prediction heads."""

from __future__ import annotations

from typing import Any


UNAVAILABLE_EFFECTS = sorted(
    [
        "population_migration",
        "land_price",
        "facility_capacity",
        "traffic_and_walkability",
        "construction_schedule",
        "approval_probability",
        "livability_score",
        "validated_policy_effect",
    ]
)


def build_rollout_evidence_gate() -> dict[str, Any]:
    """Return the fixed first-version claim and prediction boundary."""

    return {
        "unavailable_effects": list(UNAVAILABLE_EFFECTS),
        "unsupported_prediction_heads_ready": False,
        "enabled_support_levels": [
            "deterministic_geometry",
            "authoritative_rule",
            "bounded_proxy",
        ],
        "learned_calibrated_effect_ready": False,
        "claim_boundary": {
            "max_claim_level": "bounded_action_conditioned_spatial_scenario"
        },
        "empirical_policy_effect_claim": False,
    }

