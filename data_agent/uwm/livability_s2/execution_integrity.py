"""Executed dependency receipts and stale-downstream mutation probes for S2."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any, Mapping

from .dependency_dag import REQUIRED_MUTATION_EDGES, VERSION, build_dependency_dag


SCHEMA = "uwm.livability_s2.execution_dependency_receipt.v1"
VALIDATION_SCHEMA = "uwm.livability_s2.execution_dependency_validation.v1"
MUTATION_SCHEMA = "uwm.livability_s2.executed_dependency_mutations.v1"


def build_execution_dependency_receipt(run: Mapping[str, Any]) -> dict[str, Any]:
    """Bind each applicable dependency edge to the completed module outputs."""

    action_type = _action_type(run)
    projections = _module_output_projections(run)
    module_output_digests = {
        module_id: _digest(payload) for module_id, payload in projections.items()
    }
    applicable_edges = [
        edge
        for edge in build_dependency_dag()["edges"]
        if action_type in set(edge.get("action_types") or [])
    ]
    bindings = [
        {
            "source_module_id": edge["source_module_id"],
            "target_module_id": edge["target_module_id"],
            "source_output_digest": module_output_digests[edge["source_module_id"]],
            "target_output_digest": module_output_digests[edge["target_module_id"]],
            "conditional": bool(edge["conditional"]),
        }
        for edge in applicable_edges
    ]
    payload = {
        "schema": SCHEMA,
        "dag_version": VERSION,
        "action_type": action_type,
        "module_output_digests": module_output_digests,
        "edge_bindings": bindings,
        "claim_boundary": (
            "The receipt binds implementation outputs and detects stale or "
            "unattributed downstream artifacts. It does not validate an urban outcome."
        ),
    }
    payload["receipt_digest"] = _digest(payload)
    return payload


def validate_execution_dependency_receipt(run: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a stored receipt against the current run artifacts."""

    receipt = run.get("execution_dependency_receipt")
    if not isinstance(receipt, Mapping):
        return {
            "schema": VALIDATION_SCHEMA,
            "valid": False,
            "errors": ["execution_dependency_receipt_missing"],
            "edge_findings": [],
        }
    receipt_payload = {
        key: deepcopy(value) for key, value in receipt.items() if key != "receipt_digest"
    }
    errors: list[str] = []
    if receipt.get("schema") != SCHEMA:
        errors.append("execution_dependency_receipt_schema_mismatch")
    if receipt.get("dag_version") != VERSION:
        errors.append("execution_dependency_receipt_dag_version_mismatch")
    if receipt.get("receipt_digest") != _digest(receipt_payload):
        errors.append("execution_dependency_receipt_digest_mismatch")
    if receipt.get("action_type") != _action_type(run):
        errors.append("execution_dependency_receipt_action_type_mismatch")

    current_digests = {
        module_id: _digest(payload)
        for module_id, payload in _module_output_projections(run).items()
    }
    findings = []
    for binding in receipt.get("edge_bindings") or []:
        source = str(binding.get("source_module_id") or "")
        target = str(binding.get("target_module_id") or "")
        expected_source = str(binding.get("source_output_digest") or "")
        expected_target = str(binding.get("target_output_digest") or "")
        source_changed = current_digests.get(source) != expected_source
        target_changed = current_digests.get(target) != expected_target
        if source_changed and not target_changed:
            status = "stale_target_output"
        elif source_changed and target_changed:
            status = "propagated_change"
        elif not source_changed and target_changed:
            status = "unattributed_target_change"
        else:
            status = "consistent"
        findings.append(
            {
                "source_module_id": source,
                "target_module_id": target,
                "status": status,
                "source_output_changed": source_changed,
                "target_output_changed": target_changed,
                "detected": status in {
                    "stale_target_output",
                    "unattributed_target_change",
                },
            }
        )
    return {
        "schema": VALIDATION_SCHEMA,
        "valid": not errors
        and all(row["status"] == "consistent" for row in findings),
        "errors": errors,
        "edge_findings": findings,
        "stale_target_count": sum(
            row["status"] == "stale_target_output" for row in findings
        ),
        "unattributed_target_change_count": sum(
            row["status"] == "unattributed_target_change" for row in findings
        ),
    }


def execute_dependency_mutation_cases(run: Mapping[str, Any]) -> dict[str, Any]:
    """Mutate an executed upstream artifact while retaining its stale target."""

    healthy = deepcopy(dict(run))
    if "execution_dependency_receipt" not in healthy:
        healthy["execution_dependency_receipt"] = build_execution_dependency_receipt(
            healthy
        )
    healthy_validation = validate_execution_dependency_receipt(healthy)
    if not healthy_validation["valid"]:
        raise ValueError("healthy_execution_dependency_receipt_invalid")

    available = {
        (str(row["source_module_id"]), str(row["target_module_id"]))
        for row in healthy["execution_dependency_receipt"]["edge_bindings"]
    }
    cases = []
    for source, target in REQUIRED_MUTATION_EDGES:
        if (source, target) not in available:
            continue
        mutated = deepcopy(healthy)
        mutation = _mutate_source_artifact(mutated, source=source, target=target)
        validation = validate_execution_dependency_receipt(mutated)
        finding = next(
            row
            for row in validation["edge_findings"]
            if row["source_module_id"] == source
            and row["target_module_id"] == target
        )
        cases.append(
            {
                "mutation_id": f"EXEC-{len(cases) + 1:02d}",
                "mutation": f"executed:{source}->{target}",
                "source_module_id": source,
                "target_module_id": target,
                "mutation_operation": mutation,
                "observed_status": finding["status"],
                "source_output_changed": finding["source_output_changed"],
                "target_output_changed": finding["target_output_changed"],
                "detected": finding["status"] == "stale_target_output",
                "structural_only": False,
                "failure_mode": "executed_upstream_change_with_stale_downstream_output",
            }
        )
    return {
        "schema": MUTATION_SCHEMA,
        "dag_version": VERSION,
        "case_count": len(cases),
        "detected_count": sum(bool(case["detected"]) for case in cases),
        "stale_escape_count": sum(not bool(case["detected"]) for case in cases),
        "all_detected": bool(cases) and all(bool(case["detected"]) for case in cases),
        "cases": cases,
        "claim_boundary": (
            "Controlled mutations alter an executed upstream artifact while retaining "
            "the prior downstream artifact. This tests dependency-receipt detection, "
            "not every possible execution omission or real-world failure."
        ),
    }


def _action_type(run: Mapping[str, Any]) -> str:
    rollout = _mapping(run.get("rollout"))
    intervention = _mapping(rollout.get("intervention"))
    action = _mapping(intervention.get("action"))
    action_type = str(action.get("action_type") or "")
    if not action_type:
        raise ValueError("execution_dependency_action_type_missing")
    return action_type


def _module_output_projections(run: Mapping[str, Any]) -> dict[str, Any]:
    rollout = _mapping(run.get("rollout"))
    intervention = _mapping(rollout.get("intervention"))
    t1 = _mapping(intervention.get("t1"))
    t2 = _mapping(intervention.get("t2"))
    delta = _mapping(t1.get("direct_state_delta"))
    direct_delta = {
        key: deepcopy(value)
        for key, value in delta.items()
        if key not in {"changed_edge_ids", "relation_deltas"}
    }
    assessment = _mapping(run.get("business_assessment"))
    return {
        "action_admission": {
            "action": deepcopy(intervention.get("action")),
            "action_validation": deepcopy(intervention.get("action_validation")),
        },
        "direct_transition": {
            "direct_state_delta": direct_delta,
            "future_snapshot_digest": _mapping(t1.get("state_graph")).get(
                "snapshot_digest"
            ),
        },
        "relation_update": {
            "changed_edge_ids": deepcopy(delta.get("changed_edge_ids") or []),
            "relation_deltas": deepcopy(delta.get("relation_deltas") or []),
        },
        "spatial_propagation": {
            "message_digest": t2.get("message_digest"),
            "messages": deepcopy(t2.get("messages") or []),
        },
        "facility_coverage": {
            "baseline": deepcopy(assessment.get("baseline")),
            "intervention": deepcopy(assessment.get("intervention")),
            "coverage_delta_percentage_points": assessment.get(
                "coverage_delta_percentage_points"
            ),
            "newly_covered_parcel_ids": deepcopy(
                assessment.get("newly_covered_parcel_ids") or []
            ),
            "newly_uncovered_parcel_ids": deepcopy(
                assessment.get("newly_uncovered_parcel_ids") or []
            ),
        },
        "business_assessment": {
            "recommendation": assessment.get("recommendation"),
            "triggered_rules": deepcopy(assessment.get("triggered_rules") or []),
            "blockers": deepcopy(assessment.get("blockers") or []),
            "completeness_warnings": deepcopy(
                assessment.get("completeness_warnings") or []
            ),
            "evidence_level": assessment.get("evidence_level"),
            "business_rule_version": assessment.get("business_rule_version"),
            "claim_boundary": assessment.get("claim_boundary"),
        },
        "map_evidence": deepcopy(run.get("map_evidence")),
        "technical_audit": deepcopy(run.get("technical_audit")),
    }


def _mutate_source_artifact(
    run: dict[str, Any], *, source: str, target: str
) -> str:
    intervention = run["rollout"]["intervention"]
    if source == "action_admission":
        validation = intervention["action_validation"]
        validation["review_required"] = not bool(validation.get("review_required"))
        return "toggle_action_review_required_after_execution"
    if source == "direct_transition":
        if target == "facility_coverage":
            graph = intervention["t1"]["state_graph"]
            graph["snapshot_digest"] = str(graph.get("snapshot_digest")) + ":mutated"
            return "replace_future_snapshot_identity_without_coverage_recompute"
        delta = intervention["t1"]["direct_state_delta"]
        delta["facility_id"] = str(delta.get("facility_id") or "") + ":mutated"
        return "replace_direct_transition_target_without_downstream_recompute"
    if source == "relation_update":
        delta = intervention["t1"]["direct_state_delta"]
        changed = list(delta.get("changed_edge_ids") or [])
        changed.append("edge:executed-mutation-probe")
        delta["changed_edge_ids"] = changed
        return "append_changed_relation_without_downstream_recompute"
    if source == "spatial_propagation":
        intervention["t2"].setdefault("messages", []).append(
            {
                "message_id": "message:executed-mutation-probe",
                "source_node_id": "mutation-source",
                "target_node_id": "mutation-target",
                "relation_type": "executed_mutation_probe",
            }
        )
        return "append_spatial_message_without_downstream_recompute"
    if source == "facility_coverage":
        assessment = run["business_assessment"]
        value = assessment.get("coverage_delta_percentage_points")
        assessment["coverage_delta_percentage_points"] = (
            1.0 if value is None else float(value) + 1.0
        )
        return "change_coverage_delta_without_business_or_audit_recompute"
    if source == "business_assessment":
        run["business_assessment"]["recommendation"] = "mutation_requires_recompute"
        return "change_business_recommendation_without_downstream_recompute"
    if source == "map_evidence":
        run["map_evidence"]["mutation_probe"] = "map_changed_after_audit"
        return "change_map_evidence_without_audit_recompute"
    raise ValueError(f"unsupported_execution_mutation_source:{source}")


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _digest(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()
