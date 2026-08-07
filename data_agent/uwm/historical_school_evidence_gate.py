"""Claim-bounded evidence gate for historical school-status observations."""

from __future__ import annotations

from typing import Any


UWM_HISTORICAL_SCHOOL_EVIDENCE_GATE_SCHEMA = "uwm.historical_school_evidence_gate.v1"
UWM_HISTORICAL_SCHOOL_QUERY_RECEIPT_SCHEMA = "uwm.historical_school_query_receipt.v1"


def build_uwm_historical_school_evidence_gate(
    *,
    nces_status_probe: dict[str, Any],
    support_probe: dict[str, Any],
    gate_id: str,
    source_refs: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build a fail-closed gate from an NCES observation and support audit."""

    record = nces_status_probe.get("bounded_record") or {}
    support_school = support_probe.get("school_status_evidence") or {}
    support_readiness = support_probe.get("readiness") or {}
    census = support_probe.get("census_support_evidence") or {}

    historical_ready = all(
        [
            nces_status_probe.get("decision")
            == "historical_open_status_confirmed_but_current_gate_remains_blocked",
            record.get("feature_count") == 1,
            bool(record.get("explicit_status_text_observed")),
            record.get("historical_status_observation") == "passed",
            bool(support_school.get("school_state_microcase_ready")),
            bool(support_school.get("historical_only")),
            bool(record.get("ncessch")),
            bool(record.get("school_year")),
            bool(record.get("status_description")),
        ]
    )
    official_identifier_bridge = bool(record.get("official_beds_to_ncessch_crosswalk_found"))
    current_temporal_alignment = (
        (nces_status_probe.get("gate_assessment") or {}).get("current_temporal_alignment")
        == "passed"
    )
    population_ready = bool(support_readiness.get("population_accessibility_case_ready"))

    source_access = {
        "acs_2024_acs5_metadata": _source_access_state(
            (census.get("acs_2024_acs5_dataset") or {}).get("access_status")
        ),
        "acs_b01001_metadata": _source_access_state(
            (census.get("acs_b01001_group") or {}).get("access_status")
        ),
        "tiger_2024_block_group_candidate": _source_access_state(
            census.get("tiger_candidate_access")
        ),
        "tigerweb_acs2024_metadata": _source_access_state(
            (census.get("tigerweb_acs2024") or {}).get("access_status")
        ),
    }

    gate = {
        "schema": UWM_HISTORICAL_SCHOOL_EVIDENCE_GATE_SCHEMA,
        "gate_id": gate_id,
        "source_refs": dict(sorted((source_refs or {}).items())),
        "entity": {
            "entity_type": "public_school",
            "name": record.get("attributes", {}).get("SCH_NAME")
            or record.get("school_name")
            or record.get("captured_name"),
            "ncessch": record.get("ncessch"),
            "captured_dbn": record.get("dbn"),
            "captured_beds_code": record.get("beds_code"),
            "captured_institution_id": record.get("institution_id"),
        },
        "observation": {
            "school_year": record.get("school_year"),
            "status_code": record.get("status_code"),
            "status_description": record.get("status_description"),
            "observation_role": record.get("observation_role"),
            "historical_only": True,
        },
        "identity_gate": {
            "ncessch_query_authorized": historical_ready,
            "official_beds_ncessch_crosswalk_found": official_identifier_bridge,
            "beds_ncessch_merge_authorized": official_identifier_bridge,
            "identity_corroboration": record.get("identity_corroboration"),
        },
        "temporal_gate": {
            "historical_school_year_query_authorized": historical_ready,
            "authorized_school_year": record.get("school_year") if historical_ready else None,
            "current_status_query_authorized": current_temporal_alignment,
            "current_temporal_alignment": (nces_status_probe.get("gate_assessment") or {}).get(
                "current_temporal_alignment"
            ),
        },
        "population_gate": {
            "population_accessibility_query_authorized": population_ready,
            "acs_attribute_rows_available": bool(
                support_probe.get("census_attribute_rows_downloaded")
            ),
            "tiger_geometry_available": bool(support_probe.get("tiger_geometry_downloaded")),
        },
        "source_access": source_access,
        "claim_boundary": {
            "historical_school_status_claim_authorized": historical_ready,
            "current_school_status_claim_authorized": current_temporal_alignment,
            "beds_ncessch_identity_claim_authorized": official_identifier_bridge,
            "population_claim_authorized": bool(
                support_readiness.get("population_claim_authorized")
            ),
            "capacity_claim_authorized": bool(
                support_readiness.get("capacity_claim_authorized")
            ),
            "equity_claim_authorized": bool(support_readiness.get("equity_claim_authorized")),
            "policy_effect_claim_authorized": bool(
                support_readiness.get("policy_effect_claim_authorized")
            ),
        },
        "admission_effect": "no_gate_change",
        "real_city_admission_status": support_probe.get("real_city_admission_status"),
        "preadmission_status": support_probe.get("preadmission_status"),
        "submission_ready": False,
        "fabricated_value_count": 0,
    }
    validation = validate_uwm_historical_school_evidence_gate(gate)
    if validation["status"] != "passed":
        raise ValueError("invalid historical school evidence gate: " + "; ".join(validation["errors"]))
    return gate


def evaluate_uwm_historical_school_query(
    gate: dict[str, Any],
    query: dict[str, Any],
) -> dict[str, Any]:
    """Evaluate one bounded query and return an auditable disposition receipt."""

    validation = validate_uwm_historical_school_evidence_gate(gate)
    if validation["status"] != "passed":
        raise ValueError("invalid historical school evidence gate")

    query_id = str(query.get("query_id") or "unknown_query")
    query_type = str(query.get("query_type") or "unknown")
    base = {
        "schema": UWM_HISTORICAL_SCHOOL_QUERY_RECEIPT_SCHEMA,
        "query_id": query_id,
        "query_type": query_type,
        "gate_id": gate["gate_id"],
        "claim_authorized": False,
        "answer": None,
        "blockers": [],
        "evidence_refs": list(gate["source_refs"].values()),
        "fabricated_value_count": 0,
    }

    if query_type == "school_operational_status":
        return _evaluate_status_query(gate, query, base)
    if query_type == "source_data_availability":
        return _evaluate_source_availability_query(gate, query, base)
    if query_type == "population_accessibility":
        blockers = []
        population_gate = gate["population_gate"]
        if not population_gate["acs_attribute_rows_available"]:
            blockers.append("acs_attribute_rows_missing")
        if not population_gate["tiger_geometry_available"]:
            blockers.append("tiger_geometry_missing")
        if not blockers:
            blockers.append("population_accessibility_claim_not_authorized")
        return {
            **base,
            "disposition": "rejected_fail_closed",
            "blockers": blockers,
            "claim_boundary": "no_population_accessibility_result",
        }
    return {
        **base,
        "disposition": "rejected_fail_closed",
        "blockers": ["unsupported_query_type"],
        "claim_boundary": "no_result",
    }


def validate_uwm_historical_school_evidence_gate(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate gate structure and the mandatory fail-closed claim boundary."""

    errors: list[str] = []
    if payload.get("schema") != UWM_HISTORICAL_SCHOOL_EVIDENCE_GATE_SCHEMA:
        errors.append("schema_mismatch")
    entity = payload.get("entity") or {}
    observation = payload.get("observation") or {}
    identity = payload.get("identity_gate") or {}
    temporal = payload.get("temporal_gate") or {}
    population = payload.get("population_gate") or {}
    claims = payload.get("claim_boundary") or {}
    if not entity.get("ncessch"):
        errors.append("ncessch_missing")
    if not observation.get("school_year") or not observation.get("status_description"):
        errors.append("historical_observation_incomplete")
    if observation.get("historical_only") is not True:
        errors.append("historical_only_boundary_missing")
    if not temporal.get("historical_school_year_query_authorized"):
        errors.append("historical_query_not_authorized")
    if temporal.get("authorized_school_year") != observation.get("school_year"):
        errors.append("authorized_school_year_mismatch")
    if temporal.get("current_status_query_authorized"):
        errors.append("current_status_improperly_authorized")
    if identity.get("beds_ncessch_merge_authorized"):
        errors.append("beds_ncessch_merge_improperly_authorized")
    if population.get("population_accessibility_query_authorized"):
        errors.append("population_accessibility_improperly_authorized")
    if claims.get("historical_school_status_claim_authorized") is not True:
        errors.append("historical_claim_boundary_missing")
    forbidden_claims = [
        "current_school_status_claim_authorized",
        "beds_ncessch_identity_claim_authorized",
        "population_claim_authorized",
        "capacity_claim_authorized",
        "equity_claim_authorized",
        "policy_effect_claim_authorized",
    ]
    for key in forbidden_claims:
        if claims.get(key) is not False:
            errors.append(f"forbidden_claim_not_false:{key}")
    for source_id, row in (payload.get("source_access") or {}).items():
        if row.get("availability") == "unknown" and row.get("data_absent") is not False:
            errors.append(f"unknown_source_interpreted_as_absent:{source_id}")
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
        "historical_query_authorized": bool(
            temporal.get("historical_school_year_query_authorized")
        ),
        "forbidden_claim_count": sum(bool(claims.get(key)) for key in forbidden_claims),
    }


def _source_access_state(access_status: Any) -> dict[str, Any]:
    status = str(access_status or "unknown")
    if status == "passed":
        return {"observed_access_status": status, "availability": "available", "data_absent": False}
    return {"observed_access_status": status, "availability": "unknown", "data_absent": False}


def _evaluate_status_query(
    gate: dict[str, Any],
    query: dict[str, Any],
    base: dict[str, Any],
) -> dict[str, Any]:
    identifier = query.get("identifier") or {}
    identifier_type = str(identifier.get("type") or "")
    identifier_value = str(identifier.get("value") or "")
    entity = gate["entity"]
    identity_gate = gate["identity_gate"]
    temporal_gate = gate["temporal_gate"]
    blockers = []

    if identifier_type == "ncessch":
        if identifier_value != str(entity["ncessch"]):
            blockers.append("ncessch_not_observed")
    elif identifier_type == "beds":
        if not identity_gate["beds_ncessch_merge_authorized"]:
            blockers.append("official_beds_ncessch_crosswalk_missing")
        elif identifier_value != str(entity["captured_beds_code"]):
            blockers.append("beds_not_observed")
    else:
        blockers.append("unsupported_or_missing_identifier")

    requested_school_year = query.get("school_year")
    if query.get("current") is True or query.get("as_of_date") is not None:
        if not temporal_gate["current_status_query_authorized"]:
            blockers.append("current_temporal_alignment_missing")
    elif requested_school_year != temporal_gate["authorized_school_year"]:
        blockers.append("requested_school_year_not_observed")

    if blockers:
        return {
            **base,
            "disposition": "rejected_fail_closed",
            "blockers": blockers,
            "claim_boundary": "no_operational_status_result",
        }
    observation = gate["observation"]
    return {
        **base,
        "disposition": "answered_supported",
        "claim_authorized": True,
        "answer": {
            "ncessch": entity["ncessch"],
            "school_year": observation["school_year"],
            "status_code": observation["status_code"],
            "status_description": observation["status_description"],
            "historical_only": True,
        },
        "claim_boundary": "historical_school_year_status_only",
    }


def _evaluate_source_availability_query(
    gate: dict[str, Any],
    query: dict[str, Any],
    base: dict[str, Any],
) -> dict[str, Any]:
    source_id = str(query.get("source_id") or "")
    source = gate["source_access"].get(source_id)
    if source is None:
        return {
            **base,
            "disposition": "rejected_fail_closed",
            "blockers": ["source_not_registered"],
            "claim_boundary": "no_source_availability_result",
        }
    if source["availability"] == "unknown":
        return {
            **base,
            "disposition": "withheld_unknown",
            "answer": {"availability": "unknown", "data_absent": False},
            "blockers": ["source_access_not_observed"],
            "claim_boundary": "access_failure_is_not_data_absence",
        }
    return {
        **base,
        "disposition": "answered_supported",
        "claim_authorized": True,
        "answer": {"availability": "available", "data_absent": False},
        "claim_boundary": "source_access_only_not_data_content",
    }
