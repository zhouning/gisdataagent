"""Claim-bounded gate for school accountability evidence updates."""

from __future__ import annotations

from typing import Any


UWM_ACCOUNTABILITY_EVIDENCE_UPDATE_GATE_SCHEMA = (
    "uwm.accountability_evidence_update_gate.v1"
)
UWM_ACCOUNTABILITY_EVIDENCE_UPDATE_RECEIPT_SCHEMA = (
    "uwm.accountability_evidence_update_receipt.v1"
)


def build_uwm_accountability_evidence_update_gate(
    *,
    update_probe: dict[str, Any],
    gate_id: str,
    source_refs: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build a fail-closed gate from one official accountability record update."""

    record = update_probe.get("bounded_record") or {}
    semantics = update_probe.get("source_semantics") or {}
    record_ready = all(
        [
            update_probe.get("decision")
            == "2025_26_accountability_record_confirmed_without_operational_status",
            record.get("record_count") == 1,
            record.get("school_year") == "2025-26",
            bool(record.get("institution_id")),
            bool(record.get("beds_code")),
            bool(record.get("school_name")),
            bool(record.get("accountability_support_model_code")),
            record.get("accountability_record_observation") == "passed",
            semantics.get("accountability_status_not_operational_status") is True,
        ]
    )
    official_crosswalk = bool(record.get("official_beds_ncessch_crosswalk_found"))
    explicit_operational_status = bool(record.get("explicit_operational_status_found"))

    gate = {
        "schema": UWM_ACCOUNTABILITY_EVIDENCE_UPDATE_GATE_SCHEMA,
        "gate_id": gate_id,
        "source_refs": dict(sorted((source_refs or {}).items())),
        "entity": {
            "entity_type": "public_school",
            "name": record.get("school_name"),
            "institution_id": record.get("institution_id"),
            "beds_code": record.get("beds_code"),
            "ncessch": record.get("ncessch"),
        },
        "observation": {
            "school_year": record.get("school_year"),
            "accountability_support_model_code": record.get(
                "accountability_support_model_code"
            ),
            "accountability_support_model_text": record.get(
                "accountability_support_model_text"
            ),
            "observation_role": record.get("observation_role"),
            "explicit_operational_status_observed": explicit_operational_status,
        },
        "identity_gate": {
            "state_identity_record_authorized": record_ready,
            "official_beds_ncessch_crosswalk_found": official_crosswalk,
            "beds_ncessch_merge_authorized": official_crosswalk,
        },
        "claim_boundary": {
            "accountability_support_model_claim_authorized": record_ready,
            "state_school_identity_record_claim_authorized": record_ready,
            "current_school_status_claim_authorized": explicit_operational_status,
            "beds_ncessch_identity_claim_authorized": official_crosswalk,
            "population_claim_authorized": False,
            "capacity_claim_authorized": False,
            "accessibility_claim_authorized": False,
            "equity_claim_authorized": False,
            "policy_effect_claim_authorized": False,
        },
        "selective_rerun": {
            "event_detected": record_ready,
            "triggered_modules": [12, 13] if record_ready else [],
            "withheld_analytical_modules": list(range(1, 12)) + list(range(14, 18)),
            "analytical_outputs_changed": False,
            "reason": (
                "accountability_record_updates_event_and_traceability_only;"
                "operational_status_and_downstream_inputs_not_authorized"
            ),
        },
        "source_semantics": {
            "accountability_status_not_operational_status": bool(
                semantics.get("accountability_status_not_operational_status")
            ),
            "capacity_not_published": bool(semantics.get("capacity_not_published")),
            "ncessch_not_published": bool(semantics.get("ncessch_not_published")),
        },
        "admission_effect": "no_gate_change",
        "real_city_admission_status": "blocked",
        "preadmission_status": "blocked_preadmission_failure",
        "submission_ready": False,
        "fabricated_value_count": 0,
    }
    validation = validate_uwm_accountability_evidence_update_gate(gate)
    if validation["status"] != "passed":
        raise ValueError(
            "invalid accountability evidence update gate: "
            + "; ".join(validation["errors"])
        )
    return gate


def evaluate_uwm_accountability_evidence_update_query(
    gate: dict[str, Any],
    query: dict[str, Any],
) -> dict[str, Any]:
    """Evaluate one bounded update query and return an auditable receipt."""

    validation = validate_uwm_accountability_evidence_update_gate(gate)
    if validation["status"] != "passed":
        raise ValueError("invalid accountability evidence update gate")

    query_id = str(query.get("query_id") or "unknown_query")
    query_type = str(query.get("query_type") or "unknown")
    base = {
        "schema": UWM_ACCOUNTABILITY_EVIDENCE_UPDATE_RECEIPT_SCHEMA,
        "query_id": query_id,
        "query_type": query_type,
        "gate_id": gate["gate_id"],
        "claim_authorized": False,
        "answer": None,
        "blockers": [],
        "evidence_refs": list(gate["source_refs"].values()),
        "fabricated_value_count": 0,
    }

    if query_type == "accountability_support_model":
        blockers = _state_identity_blockers(gate, query)
        if query.get("school_year") != gate["observation"]["school_year"]:
            blockers.append("requested_school_year_not_observed")
        if blockers:
            return _rejected(base, blockers, "no_accountability_support_model_result")
        return {
            **base,
            "disposition": "answered_supported",
            "claim_authorized": True,
            "answer": {
                "institution_id": gate["entity"]["institution_id"],
                "beds_code": gate["entity"]["beds_code"],
                "school_name": gate["entity"]["name"],
                "school_year": gate["observation"]["school_year"],
                "accountability_support_model_code": gate["observation"][
                    "accountability_support_model_code"
                ],
                "accountability_support_model_text": gate["observation"][
                    "accountability_support_model_text"
                ],
            },
            "claim_boundary": "accountability_support_model_only",
        }

    if query_type == "school_operational_status":
        return _rejected(
            base,
            ["accountability_status_is_not_operational_status"],
            "no_operational_status_result",
        )

    if query_type == "identifier_crosswalk":
        return _rejected(
            base,
            ["official_beds_ncessch_crosswalk_missing"],
            "no_beds_ncessch_merge",
        )

    if query_type == "facility_capacity":
        return _rejected(
            base,
            ["capacity_not_published_by_accountability_source"],
            "no_capacity_result",
        )

    if query_type == "module_rerun_plan":
        rerun = gate["selective_rerun"]
        return {
            **base,
            "disposition": "answered_supported",
            "claim_authorized": True,
            "answer": {
                "event_detected": rerun["event_detected"],
                "triggered_modules": rerun["triggered_modules"],
                "withheld_analytical_modules": rerun["withheld_analytical_modules"],
                "analytical_outputs_changed": rerun["analytical_outputs_changed"],
                "reason": rerun["reason"],
            },
            "claim_boundary": "uwm_selective_rerun_plan_only",
        }

    return _rejected(base, ["unsupported_query_type"], "no_result")


def validate_uwm_accountability_evidence_update_gate(
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Validate update structure and prevent semantic or admission widening."""

    errors: list[str] = []
    if payload.get("schema") != UWM_ACCOUNTABILITY_EVIDENCE_UPDATE_GATE_SCHEMA:
        errors.append("schema_mismatch")
    entity = payload.get("entity") or {}
    observation = payload.get("observation") or {}
    identity = payload.get("identity_gate") or {}
    claims = payload.get("claim_boundary") or {}
    rerun = payload.get("selective_rerun") or {}
    semantics = payload.get("source_semantics") or {}

    if not all(entity.get(key) for key in ["name", "institution_id", "beds_code"]):
        errors.append("state_identity_incomplete")
    if entity.get("ncessch") is not None:
        errors.append("ncessch_improperly_populated")
    if observation.get("school_year") != "2025-26":
        errors.append("school_year_mismatch")
    if not observation.get("accountability_support_model_code"):
        errors.append("accountability_model_missing")
    if observation.get("explicit_operational_status_observed") is not False:
        errors.append("operational_status_improperly_observed")
    if identity.get("state_identity_record_authorized") is not True:
        errors.append("state_identity_record_not_authorized")
    if identity.get("beds_ncessch_merge_authorized") is not False:
        errors.append("beds_ncessch_merge_improperly_authorized")
    if semantics.get("accountability_status_not_operational_status") is not True:
        errors.append("accountability_semantics_missing")
    if semantics.get("capacity_not_published") is not True:
        errors.append("capacity_semantics_missing")
    if semantics.get("ncessch_not_published") is not True:
        errors.append("ncessch_semantics_missing")

    allowed_claims = [
        "accountability_support_model_claim_authorized",
        "state_school_identity_record_claim_authorized",
    ]
    for key in allowed_claims:
        if claims.get(key) is not True:
            errors.append(f"allowed_claim_not_true:{key}")
    forbidden_claims = [
        "current_school_status_claim_authorized",
        "beds_ncessch_identity_claim_authorized",
        "population_claim_authorized",
        "capacity_claim_authorized",
        "accessibility_claim_authorized",
        "equity_claim_authorized",
        "policy_effect_claim_authorized",
    ]
    for key in forbidden_claims:
        if claims.get(key) is not False:
            errors.append(f"forbidden_claim_not_false:{key}")

    expected_withheld = list(range(1, 12)) + list(range(14, 18))
    if rerun.get("event_detected") is not True:
        errors.append("event_not_detected")
    if rerun.get("triggered_modules") != [12, 13]:
        errors.append("triggered_module_scope_widened")
    if rerun.get("withheld_analytical_modules") != expected_withheld:
        errors.append("withheld_module_scope_changed")
    if rerun.get("analytical_outputs_changed") is not False:
        errors.append("analytical_outputs_improperly_changed")
    if payload.get("admission_effect") != "no_gate_change":
        errors.append("admission_effect_widened")
    if payload.get("real_city_admission_status") != "blocked":
        errors.append("real_city_admission_widened")
    if payload.get("preadmission_status") != "blocked_preadmission_failure":
        errors.append("preadmission_failure_hidden")
    if payload.get("submission_ready") is not False:
        errors.append("submission_readiness_widened")
    if payload.get("fabricated_value_count") != 0:
        errors.append("fabricated_values_present")
    return {
        "status": "passed" if not errors else "failed",
        "errors": errors,
        "supported_claim_count": sum(bool(claims.get(key)) for key in allowed_claims),
        "forbidden_claim_count": sum(bool(claims.get(key)) for key in forbidden_claims),
        "triggered_modules": list(rerun.get("triggered_modules") or []),
    }


def _state_identity_blockers(
    gate: dict[str, Any], query: dict[str, Any]
) -> list[str]:
    identifier = query.get("identifier") or {}
    identifier_type = str(identifier.get("type") or "")
    identifier_value = str(identifier.get("value") or "")
    if identifier_type == "beds":
        return [] if identifier_value == str(gate["entity"]["beds_code"]) else ["beds_not_observed"]
    if identifier_type == "institution_id":
        return (
            []
            if identifier_value == str(gate["entity"]["institution_id"])
            else ["institution_id_not_observed"]
        )
    if identifier_type == "ncessch":
        return ["ncessch_not_published_by_accountability_source"]
    return ["unsupported_or_missing_identifier"]


def _rejected(
    base: dict[str, Any], blockers: list[str], claim_boundary: str
) -> dict[str, Any]:
    return {
        **base,
        "disposition": "rejected_fail_closed",
        "blockers": blockers,
        "claim_boundary": claim_boundary,
    }
