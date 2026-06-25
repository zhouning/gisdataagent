"""Deployment punch-list helpers for TWM readiness reports."""

from __future__ import annotations

from typing import Any


def build_deployment_punch_list(
    *,
    schema: str,
    status: str,
    readiness_gate: dict[str, Any],
) -> dict[str, Any]:
    checks = {str(check.get("gate") or ""): check for check in readiness_gate.get("checks") or []}
    missing_gates = [str(gate) for gate in readiness_gate.get("missing") or []]
    actions: list[dict[str, Any]] = []
    for gate in missing_gates:
        check = checks.get(gate) or {}
        phase, resolution = deployment_punch_list_remedy(gate)
        actions.append(
            {
                "gate": gate,
                "phase": phase,
                "status": "blocked" if status == "blocked" else "review",
                "observed_status": check.get("status"),
                "observed": check.get("observed"),
                "requirement": check.get("requirement"),
                "resolution": resolution,
                "blocks_current_run": status == "blocked",
            }
        )
    return {
        "schema": schema,
        "status": status if actions else "pass",
        "required": bool(readiness_gate.get("required")),
        "open_action_count": len(actions),
        "blocking_action_count": sum(1 for action in actions if action["blocks_current_run"]),
        "actions": actions,
        "claim_boundary": "derived from production_readiness_gate; it organizes deployment gaps without changing validation or production-readiness claims",
    }


def deployment_punch_list_remedy(gate: str) -> tuple[str, str]:
    mapping = {
        "selected_plan_bundle_pass": (
            "selected_plan",
            "Run the selected-plan evaluation bundle until planner, evidence and selected-candidate checks pass.",
        ),
        "validation_report_pass": (
            "validation_ladder",
            "Resolve validation ladder review/blocking stages before promoting the bundle.",
        ),
        "claim_ladder_deployable": (
            "claim_ladder",
            "Promote the claim ladder to L4 only after deployable GIS support evidence is available.",
        ),
        "production_observed_history_preflight_pass": (
            "observed_history",
            "Provide real non-synthetic observed history that passes schema, policy-history, temporal and alignment gates.",
        ),
        "production_scale_readiness_pass": (
            "production_scale",
            "Provide a sanitized production scale profile that passes storage, partitioning, spatial-index and compute-readiness checks.",
        ),
        "human_review_and_audit_pass": (
            "human_review",
            "Complete human review, audit and GIS deployability checks.",
        ),
        "scca_causal_evidence_pass": (
            "spatial_causal",
            "Provide SCCA spatial causal evidence and pass the causal evidence gate.",
        ),
        "production_observed_history_schema_pass": (
            "observed_history",
            "Fix the production observed-history schema until the preflight schema gate passes.",
        ),
        "production_policy_alignment_pass": (
            "observed_history",
            "Fix the production policy-history alignment until the preflight alignment gate passes.",
        ),
    }
    return mapping.get(
        gate,
        (
            "deployment",
            f"Resolve the {gate} readiness gap before promoting production readiness.",
        ),
    )
