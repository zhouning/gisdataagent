"""Single-use execution guard for formal state-prior transition evaluation."""

from __future__ import annotations

import copy
import fcntl
import hashlib
import json
import math
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from .state_prior_context_adapter import DAMGKStatePriorContextBinding
from .state_prior_transition_evaluation import (
    build_dam_gk_state_prior_transition_evaluation,
    validate_dam_gk_state_prior_transition_evaluation,
)
from .state_prior_transition_protocol import (
    TRANSITION_EVALUATION_METHODS,
    validate_dam_gk_state_prior_transition_protocol,
)
from .state_prior_transition_receipts import (
    validate_state_prior_transition_holdout_opening,
    validate_state_prior_transition_protocol_registration,
)

DAM_GK_STATE_PRIOR_SINGLE_USE_RESERVATION_SCHEMA = (
    "gwm.geospatial_kernel.state_prior_transition_single_use_reservation.v1"
)
DAM_GK_STATE_PRIOR_SINGLE_USE_FINALIZATION_SCHEMA = (
    "gwm.geospatial_kernel.state_prior_transition_single_use_finalization.v1"
)
DAM_GK_STATE_PRIOR_SINGLE_USE_EXECUTION_SCHEMA = (
    "gwm.geospatial_kernel.state_prior_transition_single_use_execution.v1"
)

_EVALUATOR_PATH = Path(__file__).with_name("state_prior_transition_evaluation.py")
_ARTIFACT_FIELDS = {
    "uri",
    "created_at",
    "protocol_sha256",
    "protocol_registration_receipt_sha256",
    "holdout_opening_receipt_sha256",
    "holdout_manifest_sha256",
    "paired_input_sha256",
    "predictions_sha256",
    "model_sha256",
    "context_values_sha256",
}
_NO_INDEPENDENT_CLAIM = {
    "single_use_execution_receipt_only": True,
    "scientific_result_claim": False,
    "transition_skill_improvement_claim": False,
    "policy_causal_effect_claim": False,
    "general_geospatial_world_model_validation_claim": False,
}


class StatePriorTransitionSingleUseRegistry(Protocol):
    """Registry contract required by the formal single-use execution path."""

    def reserve(self, receipt: Mapping[str, Any]) -> Mapping[str, Any]:
        """Reserve the receipt's globally unique single-use key."""

    def record_finalization(self, receipt: Mapping[str, Any]) -> Mapping[str, Any]:
        """Append the completed or failed terminal receipt."""


@dataclass(frozen=True)
class StatePriorTransitionSingleUseReservation:
    """An atomically persisted reservation that can be consumed exactly once."""

    path: Path
    receipt: Mapping[str, Any]

    def finalize(
        self,
        *,
        evaluation: Mapping[str, Any],
        consumed_at: str,
        protocol: Mapping[str, Any],
        registration_receipt: Mapping[str, Any],
        opening_receipt: Mapping[str, Any],
        prediction_artifacts: Mapping[str, Mapping[str, Any]],
    ) -> dict[str, Any]:
        """Consume the reservation with one validated evaluation artifact."""

        evaluation_payload = copy.deepcopy(dict(evaluation))
        evaluation_validation = validate_dam_gk_state_prior_transition_evaluation(
            evaluation_payload
        )
        if not evaluation_validation["valid"]:
            raise ValueError(
                "single_use_evaluation_invalid:" + ";".join(evaluation_validation["errors"])
            )
        return self._consume(
            status="completed",
            consumed_at=consumed_at,
            evaluation=evaluation_payload,
            failure_code=None,
            protocol=protocol,
            registration_receipt=registration_receipt,
            opening_receipt=opening_receipt,
            prediction_artifacts=prediction_artifacts,
        )

    def fail(
        self,
        *,
        failure_code: str,
        consumed_at: str,
        protocol: Mapping[str, Any],
        registration_receipt: Mapping[str, Any],
        opening_receipt: Mapping[str, Any],
        prediction_artifacts: Mapping[str, Mapping[str, Any]],
    ) -> dict[str, Any]:
        """Consume a failed attempt so malformed or adverse runs cannot be retried."""

        if not _nonempty_string(failure_code):
            raise ValueError("single_use_failure_code_required")
        return self._consume(
            status="failed",
            consumed_at=consumed_at,
            evaluation=None,
            failure_code=str(failure_code),
            protocol=protocol,
            registration_receipt=registration_receipt,
            opening_receipt=opening_receipt,
            prediction_artifacts=prediction_artifacts,
        )

    def _consume(
        self,
        *,
        status: str,
        consumed_at: str,
        evaluation: Mapping[str, Any] | None,
        failure_code: str | None,
        protocol: Mapping[str, Any],
        registration_receipt: Mapping[str, Any],
        opening_receipt: Mapping[str, Any],
        prediction_artifacts: Mapping[str, Mapping[str, Any]],
    ) -> dict[str, Any]:
        reservation_validation = validate_state_prior_transition_single_use_reservation(
            self.receipt,
            protocol=protocol,
            registration_receipt=registration_receipt,
            opening_receipt=opening_receipt,
            prediction_artifacts=prediction_artifacts,
        )
        if not reservation_validation["valid"]:
            raise ValueError(
                "single_use_reservation_invalid:" + ";".join(reservation_validation["errors"])
            )
        consumed = _require_aware_timestamp(consumed_at, "single_use_consumed_at")
        reserved = _parse_aware_timestamp(self.receipt.get("reserved_at"))
        if reserved is None or consumed < reserved:
            raise ValueError("single_use_consumed_before_reservation")
        final_receipt = _build_finalization_receipt(
            reservation=self.receipt,
            status=status,
            consumed_at=str(consumed_at),
            evaluation=evaluation,
            failure_code=failure_code,
        )
        validation = validate_state_prior_transition_single_use_finalization(
            final_receipt,
            protocol=protocol,
            registration_receipt=registration_receipt,
            opening_receipt=opening_receipt,
            prediction_artifacts=prediction_artifacts,
            evaluation=evaluation,
        )
        if not validation["valid"]:
            raise ValueError("single_use_finalization_invalid:" + ";".join(validation["errors"]))
        _replace_reserved_receipt_once(
            self.path,
            expected=dict(self.receipt),
            finalized=final_receipt,
        )
        return final_receipt


def reserve_state_prior_transition_evaluation(
    path: Path,
    *,
    reservation_id: str,
    reserved_at: str,
    evaluation_id: str,
    protocol: Mapping[str, Any],
    registration_receipt: Mapping[str, Any],
    opening_receipt: Mapping[str, Any],
    prediction_artifacts: Mapping[str, Mapping[str, Any]],
    evaluator_sha256: str,
) -> StatePriorTransitionSingleUseReservation:
    """Atomically reserve one formal evaluation attempt with ``O_EXCL``."""

    if not isinstance(path, Path):
        raise TypeError("single_use_reservation_path_must_be_path")
    if not path.parent.is_dir():
        raise ValueError("single_use_reservation_parent_must_exist")
    if not _nonempty_string(reservation_id):
        raise ValueError("single_use_reservation_id_required")
    if not _nonempty_string(evaluation_id):
        raise ValueError("single_use_evaluation_id_required")
    reserved = _require_aware_timestamp(reserved_at, "single_use_reserved_at")
    protocol_payload, registration_payload, opening_payload = _validate_receipt_chain(
        protocol,
        registration_receipt,
        opening_receipt,
    )
    normalized_artifacts = _validate_prediction_artifact_chain(
        prediction_artifacts,
        protocol=protocol_payload,
        registration_receipt=registration_payload,
        opening_receipt=opening_payload,
        latest_created_at=reserved,
    )
    opened = _parse_aware_timestamp(opening_payload["opened_at"])
    if opened is None or reserved < opened:
        raise ValueError("single_use_reserved_before_holdout_opening")
    if not _valid_sha256(evaluator_sha256):
        raise ValueError("single_use_evaluator_sha256_invalid")
    prediction_bundle_sha256 = compute_state_prior_transition_prediction_bundle_sha256(
        normalized_artifacts
    )
    single_use_key_sha256 = compute_state_prior_transition_single_use_key_sha256(
        evaluation_id=evaluation_id,
        protocol_sha256=protocol_payload["protocol_sha256"],
        registration_receipt_sha256=registration_payload["registration_receipt_sha256"],
        opening_receipt_sha256=opening_payload["holdout_opening_receipt_sha256"],
        holdout_manifest_sha256=opening_payload["holdout_manifest_sha256"],
        prediction_artifact_bundle_sha256=prediction_bundle_sha256,
    )

    receipt = {
        "schema": DAM_GK_STATE_PRIOR_SINGLE_USE_RESERVATION_SCHEMA,
        "version": "0.1",
        "status": "reserved",
        "reservation_id": str(reservation_id),
        "reserved_at": str(reserved_at),
        "evaluation_id": str(evaluation_id),
        "protocol_id": protocol_payload["protocol_id"],
        "protocol_sha256": protocol_payload["protocol_sha256"],
        "protocol_registration_receipt_sha256": registration_payload["registration_receipt_sha256"],
        "holdout_opening_receipt_sha256": opening_payload["holdout_opening_receipt_sha256"],
        "holdout_manifest_sha256": opening_payload["holdout_manifest_sha256"],
        "prediction_artifact_bundle_sha256": prediction_bundle_sha256,
        "single_use_key_sha256": single_use_key_sha256,
        "evaluator_sha256": evaluator_sha256,
        "attempt_number": 1,
        "rerun_permitted": False,
        "claim_boundary": copy.deepcopy(_NO_INDEPENDENT_CLAIM),
    }
    receipt["reservation_receipt_sha256"] = (
        compute_state_prior_transition_single_use_reservation_sha256(receipt)
    )
    validation = validate_state_prior_transition_single_use_reservation(
        receipt,
        protocol=protocol_payload,
        registration_receipt=registration_payload,
        opening_receipt=opening_payload,
        prediction_artifacts=normalized_artifacts,
    )
    if not validation["valid"]:
        raise ValueError(
            "invalid_state_prior_transition_single_use_reservation:"
            + ";".join(validation["errors"])
        )
    _write_new_receipt(path, receipt)
    return StatePriorTransitionSingleUseReservation(
        path=path,
        receipt=copy.deepcopy(receipt),
    )


def execute_single_use_state_prior_transition_evaluation(
    reservation_path: Path,
    *,
    reservation_id: str,
    reserved_at: str,
    evaluation_id: str,
    created_at: str,
    protocol: Mapping[str, Any],
    protocol_registration_receipt: Mapping[str, Any],
    holdout_opening_receipt: Mapping[str, Any],
    full_binding: DAMGKStatePriorContextBinding,
    zero_binding: DAMGKStatePriorContextBinding,
    shuffled_binding: DAMGKStatePriorContextBinding,
    holdout_records: Sequence[Mapping[str, Any]],
    prediction_artifacts: Mapping[str, Mapping[str, Any]],
    evidence_refs: Sequence[str],
    leakage_audit: Mapping[str, Any],
    registry: StatePriorTransitionSingleUseRegistry | None = None,
) -> dict[str, Any]:
    """Reserve, evaluate and consume exactly one formal transition evaluation."""

    evaluation_created = _require_aware_timestamp(created_at, "single_use_evaluation_created_at")
    reserved = _require_aware_timestamp(reserved_at, "single_use_reserved_at")
    if evaluation_created < reserved:
        raise ValueError("single_use_evaluation_created_before_reservation")
    evaluator_sha256 = _sha256_path(_EVALUATOR_PATH)
    reservation = reserve_state_prior_transition_evaluation(
        reservation_path,
        reservation_id=reservation_id,
        reserved_at=reserved_at,
        evaluation_id=evaluation_id,
        protocol=protocol,
        registration_receipt=protocol_registration_receipt,
        opening_receipt=holdout_opening_receipt,
        prediction_artifacts=prediction_artifacts,
        evaluator_sha256=evaluator_sha256,
    )
    registry_record: dict[str, Any] | None = None
    if registry is not None:
        registry_record = copy.deepcopy(dict(registry.reserve(reservation.receipt)))
        _require_valid_registry_record(
            registry_record,
            reservation=reservation.receipt,
            finalization=None,
        )
    try:
        evaluation = build_dam_gk_state_prior_transition_evaluation(
            evaluation_id=evaluation_id,
            created_at=created_at,
            protocol=protocol,
            protocol_registration_receipt=protocol_registration_receipt,
            holdout_opening_receipt=holdout_opening_receipt,
            full_binding=full_binding,
            zero_binding=zero_binding,
            shuffled_binding=shuffled_binding,
            holdout_records=holdout_records,
            prediction_artifacts=prediction_artifacts,
            evidence_refs=evidence_refs,
            leakage_audit=leakage_audit,
        )
    except Exception as exc:
        failed_receipt = reservation.fail(
            failure_code=f"evaluation_failed:{type(exc).__name__}",
            consumed_at=created_at,
            protocol=protocol,
            registration_receipt=protocol_registration_receipt,
            opening_receipt=holdout_opening_receipt,
            prediction_artifacts=prediction_artifacts,
        )
        if registry is not None:
            try:
                registry_record = copy.deepcopy(dict(registry.record_finalization(failed_receipt)))
                _require_valid_registry_record(
                    registry_record,
                    reservation=reservation.receipt,
                    finalization=failed_receipt,
                )
            except Exception as registry_exc:
                raise RuntimeError(
                    "single_use_registry_failure_finalization_failed"
                ) from registry_exc
        raise
    final_receipt = reservation.finalize(
        evaluation=evaluation,
        consumed_at=created_at,
        protocol=protocol,
        registration_receipt=protocol_registration_receipt,
        opening_receipt=holdout_opening_receipt,
        prediction_artifacts=prediction_artifacts,
    )
    if registry is not None:
        registry_record = copy.deepcopy(dict(registry.record_finalization(final_receipt)))
        _require_valid_registry_record(
            registry_record,
            reservation=reservation.receipt,
            finalization=final_receipt,
        )
    result = {
        "schema": DAM_GK_STATE_PRIOR_SINGLE_USE_EXECUTION_SCHEMA,
        "version": "0.1",
        "evaluation": evaluation,
        "single_use_receipt": final_receipt,
    }
    if registry_record is not None:
        result["single_use_registry_record"] = registry_record
    result["execution_bundle_sha256"] = compute_state_prior_transition_single_use_execution_sha256(
        result
    )
    validation = validate_state_prior_transition_single_use_execution(
        result,
        protocol=protocol,
        registration_receipt=protocol_registration_receipt,
        opening_receipt=holdout_opening_receipt,
        prediction_artifacts=prediction_artifacts,
    )
    if not validation["valid"]:
        raise ValueError("single_use_execution_bundle_invalid:" + ";".join(validation["errors"]))
    return result


def validate_state_prior_transition_single_use_reservation(
    payload: Any,
    *,
    protocol: Mapping[str, Any],
    registration_receipt: Mapping[str, Any],
    opening_receipt: Mapping[str, Any],
    prediction_artifacts: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Validate a pending reservation against the complete frozen input chain."""

    if not isinstance(payload, dict):
        return {"valid": False, "errors": ["single_use_reservation_must_be_dictionary"]}
    errors: list[str] = []
    try:
        protocol_values, registration_values, opening_values = _validate_receipt_chain(
            protocol,
            registration_receipt,
            opening_receipt,
        )
        normalized_artifacts = _validate_prediction_artifact_chain(
            prediction_artifacts,
            protocol=protocol_values,
            registration_receipt=registration_values,
            opening_receipt=opening_values,
            latest_created_at=_parse_aware_timestamp(payload.get("reserved_at")),
        )
    except (TypeError, ValueError) as exc:
        errors.append(f"single_use_reservation_input_chain_invalid:{exc}")
        protocol_values = {}
        registration_values = {}
        opening_values = {}
        normalized_artifacts = {}
    expected_fields = {
        "schema",
        "version",
        "status",
        "reservation_id",
        "reserved_at",
        "evaluation_id",
        "protocol_id",
        "protocol_sha256",
        "protocol_registration_receipt_sha256",
        "holdout_opening_receipt_sha256",
        "holdout_manifest_sha256",
        "prediction_artifact_bundle_sha256",
        "single_use_key_sha256",
        "evaluator_sha256",
        "attempt_number",
        "rerun_permitted",
        "claim_boundary",
        "reservation_receipt_sha256",
    }
    if set(payload) != expected_fields:
        errors.append("single_use_reservation_field_set_mismatch")
    if payload.get("schema") != DAM_GK_STATE_PRIOR_SINGLE_USE_RESERVATION_SCHEMA:
        errors.append("single_use_reservation_schema_mismatch")
    if payload.get("version") != "0.1" or payload.get("status") != "reserved":
        errors.append("single_use_reservation_status_or_version_invalid")
    for field in ("reservation_id", "evaluation_id"):
        if not _nonempty_string(payload.get(field)):
            errors.append(f"single_use_reservation_{field}_required")
    reserved = _parse_aware_timestamp(payload.get("reserved_at"))
    opened = _parse_aware_timestamp(opening_values.get("opened_at"))
    if reserved is None:
        errors.append("single_use_reservation_reserved_at_invalid")
    elif opened is not None and reserved < opened:
        errors.append("single_use_reservation_before_holdout_opening")
    expected_links = {
        "protocol_id": protocol_values.get("protocol_id"),
        "protocol_sha256": protocol_values.get("protocol_sha256"),
        "protocol_registration_receipt_sha256": registration_values.get(
            "registration_receipt_sha256"
        ),
        "holdout_opening_receipt_sha256": opening_values.get("holdout_opening_receipt_sha256"),
        "holdout_manifest_sha256": opening_values.get("holdout_manifest_sha256"),
    }
    for field, expected in expected_links.items():
        if payload.get(field) != expected:
            errors.append(f"single_use_reservation_{field}_mismatch")
    if normalized_artifacts:
        expected_bundle = compute_state_prior_transition_prediction_bundle_sha256(
            normalized_artifacts
        )
        if payload.get("prediction_artifact_bundle_sha256") != expected_bundle:
            errors.append("single_use_reservation_prediction_bundle_sha256_mismatch")
        expected_key = compute_state_prior_transition_single_use_key_sha256(
            evaluation_id=str(payload.get("evaluation_id") or ""),
            protocol_sha256=str(protocol_values.get("protocol_sha256") or ""),
            registration_receipt_sha256=str(
                registration_values.get("registration_receipt_sha256") or ""
            ),
            opening_receipt_sha256=str(opening_values.get("holdout_opening_receipt_sha256") or ""),
            holdout_manifest_sha256=str(opening_values.get("holdout_manifest_sha256") or ""),
            prediction_artifact_bundle_sha256=expected_bundle,
        )
        if payload.get("single_use_key_sha256") != expected_key:
            errors.append("single_use_reservation_key_sha256_mismatch")
    if not _valid_sha256(payload.get("evaluator_sha256")):
        errors.append("single_use_reservation_evaluator_sha256_invalid")
    if payload.get("attempt_number") != 1:
        errors.append("single_use_reservation_attempt_number_must_be_one")
    if payload.get("rerun_permitted") is not False:
        errors.append("single_use_reservation_rerun_must_be_false")
    if payload.get("claim_boundary") != _NO_INDEPENDENT_CLAIM:
        errors.append("single_use_reservation_claim_boundary_invalid")
    receipt_sha256 = payload.get("reservation_receipt_sha256")
    if not _valid_sha256(receipt_sha256):
        errors.append("single_use_reservation_receipt_sha256_invalid")
    elif receipt_sha256 != compute_state_prior_transition_single_use_reservation_sha256(payload):
        errors.append("single_use_reservation_receipt_sha256_mismatch")
    return {"valid": not errors, "errors": errors}


def validate_state_prior_transition_single_use_finalization(
    payload: Any,
    *,
    protocol: Mapping[str, Any],
    registration_receipt: Mapping[str, Any],
    opening_receipt: Mapping[str, Any],
    prediction_artifacts: Mapping[str, Mapping[str, Any]],
    evaluation: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Validate a completed or failed receipt; both permanently consume the attempt."""

    if not isinstance(payload, dict):
        return {"valid": False, "errors": ["single_use_finalization_must_be_dictionary"]}
    errors: list[str] = []
    expected_fields = {
        "schema",
        "version",
        "status",
        "consumed_at",
        "reservation",
        "evaluation_sha256",
        "evaluation_ready",
        "supported_claim",
        "failure_code",
        "rerun_permitted",
        "claim_boundary",
        "finalization_receipt_sha256",
    }
    if set(payload) != expected_fields:
        errors.append("single_use_finalization_field_set_mismatch")
    if payload.get("schema") != DAM_GK_STATE_PRIOR_SINGLE_USE_FINALIZATION_SCHEMA:
        errors.append("single_use_finalization_schema_mismatch")
    if payload.get("version") != "0.1" or payload.get("status") not in {
        "completed",
        "failed",
    }:
        errors.append("single_use_finalization_status_or_version_invalid")
    reservation = payload.get("reservation")
    reservation_validation = validate_state_prior_transition_single_use_reservation(
        reservation,
        protocol=protocol,
        registration_receipt=registration_receipt,
        opening_receipt=opening_receipt,
        prediction_artifacts=prediction_artifacts,
    )
    errors.extend(f"single_use_finalization_{error}" for error in reservation_validation["errors"])
    consumed = _parse_aware_timestamp(payload.get("consumed_at"))
    reserved = (
        _parse_aware_timestamp(reservation.get("reserved_at"))
        if isinstance(reservation, Mapping)
        else None
    )
    if consumed is None:
        errors.append("single_use_finalization_consumed_at_invalid")
    elif reserved is not None and consumed < reserved:
        errors.append("single_use_finalization_before_reservation")

    if payload.get("status") == "completed":
        evaluation_validation = validate_dam_gk_state_prior_transition_evaluation(evaluation)
        errors.extend(
            f"single_use_finalization_evaluation_{error}"
            for error in evaluation_validation["errors"]
        )
        evaluation_values = dict(evaluation) if isinstance(evaluation, Mapping) else {}
        expected_evaluation_sha256 = (
            compute_state_prior_transition_evaluation_artifact_sha256(evaluation_values)
            if evaluation_values
            else None
        )
        if payload.get("evaluation_sha256") != expected_evaluation_sha256:
            errors.append("single_use_finalization_evaluation_sha256_mismatch")
        if isinstance(reservation, Mapping) and evaluation_values.get(
            "evaluation_id"
        ) != reservation.get("evaluation_id"):
            errors.append("single_use_finalization_evaluation_id_mismatch")
        if payload.get("evaluation_ready") is not (
            evaluation_values.get("state_prior_transition_evaluation_ready") is True
        ):
            errors.append("single_use_finalization_evaluation_ready_mismatch")
        if payload.get("supported_claim") != evaluation_values.get("supported_claim"):
            errors.append("single_use_finalization_supported_claim_mismatch")
        if payload.get("failure_code") is not None:
            errors.append("single_use_finalization_completed_failure_code_must_be_null")
    elif payload.get("status") == "failed":
        if evaluation is not None:
            errors.append("single_use_finalization_failed_evaluation_must_be_null")
        if payload.get("evaluation_sha256") is not None:
            errors.append("single_use_finalization_failed_evaluation_sha256_must_be_null")
        if payload.get("evaluation_ready") is not False:
            errors.append("single_use_finalization_failed_evaluation_ready_must_be_false")
        if payload.get("supported_claim") is not None:
            errors.append("single_use_finalization_failed_supported_claim_must_be_null")
        if not _nonempty_string(payload.get("failure_code")):
            errors.append("single_use_finalization_failure_code_required")
    if payload.get("rerun_permitted") is not False:
        errors.append("single_use_finalization_rerun_must_be_false")
    if payload.get("claim_boundary") != _NO_INDEPENDENT_CLAIM:
        errors.append("single_use_finalization_claim_boundary_invalid")
    finalization_sha256 = payload.get("finalization_receipt_sha256")
    if not _valid_sha256(finalization_sha256):
        errors.append("single_use_finalization_receipt_sha256_invalid")
    elif finalization_sha256 != compute_state_prior_transition_single_use_finalization_sha256(
        payload
    ):
        errors.append("single_use_finalization_receipt_sha256_mismatch")
    return {"valid": not errors, "errors": errors}


def validate_state_prior_transition_single_use_execution(
    payload: Any,
    *,
    protocol: Mapping[str, Any],
    registration_receipt: Mapping[str, Any],
    opening_receipt: Mapping[str, Any],
    prediction_artifacts: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Validate the returned evaluation/final-receipt bundle."""

    if not isinstance(payload, dict):
        return {"valid": False, "errors": ["single_use_execution_must_be_dictionary"]}
    errors: list[str] = []
    base_fields = {
        "schema",
        "version",
        "evaluation",
        "single_use_receipt",
        "execution_bundle_sha256",
    }
    allowed_field_sets = {
        frozenset(base_fields),
        frozenset(base_fields | {"single_use_registry_record"}),
    }
    if set(payload) not in allowed_field_sets:
        errors.append("single_use_execution_field_set_mismatch")
    if payload.get("schema") != DAM_GK_STATE_PRIOR_SINGLE_USE_EXECUTION_SCHEMA:
        errors.append("single_use_execution_schema_mismatch")
    if payload.get("version") != "0.1":
        errors.append("single_use_execution_version_mismatch")
    evaluation = payload.get("evaluation")
    finalization_validation = validate_state_prior_transition_single_use_finalization(
        payload.get("single_use_receipt"),
        protocol=protocol,
        registration_receipt=registration_receipt,
        opening_receipt=opening_receipt,
        prediction_artifacts=prediction_artifacts,
        evaluation=evaluation,
    )
    errors.extend(f"single_use_execution_{error}" for error in finalization_validation["errors"])
    if "single_use_registry_record" in payload:
        finalization = payload.get("single_use_receipt")
        reservation = finalization.get("reservation") if isinstance(finalization, Mapping) else {}
        try:
            registry_validation = _validate_registry_record(
                payload.get("single_use_registry_record"),
                reservation=reservation,
                finalization=finalization if isinstance(finalization, Mapping) else None,
            )
        except (TypeError, ValueError) as exc:
            errors.append(f"single_use_execution_registry_record_invalid:{exc}")
        else:
            errors.extend(
                f"single_use_execution_{error}" for error in registry_validation["errors"]
            )
    execution_sha256 = payload.get("execution_bundle_sha256")
    if not _valid_sha256(execution_sha256):
        errors.append("single_use_execution_bundle_sha256_invalid")
    elif execution_sha256 != compute_state_prior_transition_single_use_execution_sha256(payload):
        errors.append("single_use_execution_bundle_sha256_mismatch")
    return {"valid": not errors, "errors": errors}


def compute_state_prior_transition_prediction_bundle_sha256(
    prediction_artifacts: Mapping[str, Mapping[str, Any]],
) -> str:
    """Hash all four prediction artifact declarations in a stable method order."""

    payload = {
        method: dict(prediction_artifacts[method]) for method in TRANSITION_EVALUATION_METHODS
    }
    return _canonical_sha256(payload)


def compute_state_prior_transition_single_use_key_sha256(
    *,
    evaluation_id: str,
    protocol_sha256: str,
    registration_receipt_sha256: str,
    opening_receipt_sha256: str,
    holdout_manifest_sha256: str,
    prediction_artifact_bundle_sha256: str,
) -> str:
    """Derive the cross-path uniqueness key for one frozen evaluation attempt."""

    return _canonical_sha256(
        {
            "evaluation_id": evaluation_id,
            "protocol_sha256": protocol_sha256,
            "registration_receipt_sha256": registration_receipt_sha256,
            "opening_receipt_sha256": opening_receipt_sha256,
            "holdout_manifest_sha256": holdout_manifest_sha256,
            "prediction_artifact_bundle_sha256": prediction_artifact_bundle_sha256,
        }
    )


def compute_state_prior_transition_evaluation_artifact_sha256(
    evaluation: Mapping[str, Any],
) -> str:
    """Hash the complete evaluation artifact for final-receipt binding."""

    return _canonical_sha256(dict(evaluation))


def compute_state_prior_transition_single_use_reservation_sha256(
    payload: Mapping[str, Any],
) -> str:
    """Compute the canonical pending-reservation digest."""

    return _canonical_sha256(payload, excluded_key="reservation_receipt_sha256")


def compute_state_prior_transition_single_use_finalization_sha256(
    payload: Mapping[str, Any],
) -> str:
    """Compute the canonical completed/failed receipt digest."""

    return _canonical_sha256(payload, excluded_key="finalization_receipt_sha256")


def compute_state_prior_transition_single_use_execution_sha256(
    payload: Mapping[str, Any],
) -> str:
    """Compute the canonical successful single-use bundle digest."""

    return _canonical_sha256(payload, excluded_key="execution_bundle_sha256")


def _validate_registry_record(
    payload: Any,
    *,
    reservation: Mapping[str, Any],
    finalization: Mapping[str, Any] | None,
) -> dict[str, Any]:
    from .state_prior_transition_registry import (
        validate_state_prior_transition_single_use_registry_record,
    )

    return validate_state_prior_transition_single_use_registry_record(
        payload,
        reservation=reservation,
        finalization=finalization,
    )


def _require_valid_registry_record(
    payload: Any,
    *,
    reservation: Mapping[str, Any],
    finalization: Mapping[str, Any] | None,
) -> None:
    validation = _validate_registry_record(
        payload,
        reservation=reservation,
        finalization=finalization,
    )
    if not validation["valid"]:
        raise ValueError("single_use_registry_record_invalid:" + ";".join(validation["errors"]))


def _validate_receipt_chain(
    protocol: Mapping[str, Any],
    registration_receipt: Mapping[str, Any],
    opening_receipt: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    if not all(
        isinstance(value, Mapping) for value in (protocol, registration_receipt, opening_receipt)
    ):
        raise TypeError("single_use_protocol_and_receipts_must_be_mappings")
    protocol_payload = copy.deepcopy(dict(protocol))
    registration_payload = copy.deepcopy(dict(registration_receipt))
    opening_payload = copy.deepcopy(dict(opening_receipt))
    protocol_validation = validate_dam_gk_state_prior_transition_protocol(protocol_payload)
    if not protocol_validation["valid"]:
        raise ValueError("single_use_protocol_invalid:" + ";".join(protocol_validation["errors"]))
    registration_validation = validate_state_prior_transition_protocol_registration(
        registration_payload,
        protocol=protocol_payload,
    )
    if not registration_validation["valid"]:
        raise ValueError(
            "single_use_registration_invalid:" + ";".join(registration_validation["errors"])
        )
    opening_validation = validate_state_prior_transition_holdout_opening(
        opening_payload,
        protocol=protocol_payload,
        registration_receipt=registration_payload,
    )
    if not opening_validation["valid"]:
        raise ValueError("single_use_opening_invalid:" + ";".join(opening_validation["errors"]))
    return protocol_payload, registration_payload, opening_payload


def _validate_prediction_artifact_chain(
    prediction_artifacts: Mapping[str, Mapping[str, Any]],
    *,
    protocol: Mapping[str, Any],
    registration_receipt: Mapping[str, Any],
    opening_receipt: Mapping[str, Any],
    latest_created_at: datetime | None,
) -> dict[str, dict[str, Any]]:
    if not isinstance(prediction_artifacts, Mapping) or set(prediction_artifacts) != set(
        TRANSITION_EVALUATION_METHODS
    ):
        raise ValueError("single_use_prediction_artifact_set_mismatch")
    opened = _parse_aware_timestamp(opening_receipt.get("opened_at"))
    if latest_created_at is None:
        raise ValueError("single_use_prediction_latest_created_at_invalid")
    normalized: dict[str, dict[str, Any]] = {}
    for method in TRANSITION_EVALUATION_METHODS:
        artifact = prediction_artifacts[method]
        if not isinstance(artifact, Mapping) or set(artifact) != _ARTIFACT_FIELDS:
            raise ValueError(f"single_use_{method}_artifact_contract_invalid")
        value = copy.deepcopy(dict(artifact))
        for field in (
            "protocol_sha256",
            "protocol_registration_receipt_sha256",
            "holdout_opening_receipt_sha256",
            "holdout_manifest_sha256",
            "paired_input_sha256",
            "predictions_sha256",
            "model_sha256",
        ):
            if not _valid_sha256(value.get(field)):
                raise ValueError(f"single_use_{method}_{field}_invalid")
        expected_links = {
            "protocol_sha256": protocol["protocol_sha256"],
            "protocol_registration_receipt_sha256": registration_receipt[
                "registration_receipt_sha256"
            ],
            "holdout_opening_receipt_sha256": opening_receipt["holdout_opening_receipt_sha256"],
            "holdout_manifest_sha256": opening_receipt["holdout_manifest_sha256"],
        }
        if any(value.get(field) != expected for field, expected in expected_links.items()):
            raise ValueError(f"single_use_{method}_receipt_chain_mismatch")
        artifact_created = _parse_aware_timestamp(value.get("created_at"))
        if artifact_created is None:
            raise ValueError(f"single_use_{method}_created_at_invalid")
        if opened is None or artifact_created < opened:
            raise ValueError(f"single_use_{method}_created_before_holdout_opening")
        if artifact_created > latest_created_at:
            raise ValueError(f"single_use_{method}_created_after_reservation")
        if not _nonempty_string(value.get("uri")):
            raise ValueError(f"single_use_{method}_uri_required")
        if method == "traditional_baseline":
            if value.get("context_values_sha256") is not None:
                raise ValueError("single_use_baseline_context_sha256_must_be_null")
        elif not _valid_sha256(value.get("context_values_sha256")):
            raise ValueError(f"single_use_{method}_context_values_sha256_invalid")
        normalized[method] = value
    return normalized


def _build_finalization_receipt(
    *,
    reservation: Mapping[str, Any],
    status: str,
    consumed_at: str,
    evaluation: Mapping[str, Any] | None,
    failure_code: str | None,
) -> dict[str, Any]:
    completed = status == "completed"
    receipt = {
        "schema": DAM_GK_STATE_PRIOR_SINGLE_USE_FINALIZATION_SCHEMA,
        "version": "0.1",
        "status": status,
        "consumed_at": str(consumed_at),
        "reservation": copy.deepcopy(dict(reservation)),
        "evaluation_sha256": (
            compute_state_prior_transition_evaluation_artifact_sha256(evaluation)
            if completed and evaluation is not None
            else None
        ),
        "evaluation_ready": (
            evaluation.get("state_prior_transition_evaluation_ready") is True
            if completed and evaluation is not None
            else False
        ),
        "supported_claim": (
            evaluation.get("supported_claim") if completed and evaluation is not None else None
        ),
        "failure_code": failure_code,
        "rerun_permitted": False,
        "claim_boundary": copy.deepcopy(_NO_INDEPENDENT_CLAIM),
    }
    receipt["finalization_receipt_sha256"] = (
        compute_state_prior_transition_single_use_finalization_sha256(receipt)
    )
    return receipt


def _write_new_receipt(path: Path, receipt: Mapping[str, Any]) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        descriptor = os.open(path, flags, 0o600)
    except FileExistsError as exc:
        raise RuntimeError(f"single_use_reservation_already_exists:{path}") from exc
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(receipt, handle, ensure_ascii=True, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        raise


def _replace_reserved_receipt_once(
    path: Path,
    *,
    expected: Mapping[str, Any],
    finalized: Mapping[str, Any],
) -> None:
    try:
        with path.open("r+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            current = json.load(handle)
            if current != dict(expected) or current.get("status") != "reserved":
                raise RuntimeError("single_use_reservation_changed_or_already_consumed")
            handle.seek(0)
            json.dump(finalized, handle, ensure_ascii=True, indent=2, sort_keys=True)
            handle.write("\n")
            handle.truncate()
            handle.flush()
            os.fsync(handle.fileno())
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except FileNotFoundError as exc:
        raise RuntimeError("single_use_reservation_missing") from exc


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_sha256(
    payload: Mapping[str, Any],
    *,
    excluded_key: str | None = None,
) -> str:
    content = {
        key: value
        for key, value in dict(payload).items()
        if excluded_key is None or key != excluded_key
    }
    encoded = json.dumps(
        _normalize_nonfinite_numbers(content),
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _normalize_nonfinite_numbers(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        if math.isnan(value):
            return "__nonfinite__:nan"
        return "__nonfinite__:positive_infinity" if value > 0 else "__nonfinite__:negative_infinity"
    if isinstance(value, Mapping):
        return {key: _normalize_nonfinite_numbers(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalize_nonfinite_numbers(item) for item in value]
    return value


def _require_aware_timestamp(value: Any, field: str) -> datetime:
    parsed = _parse_aware_timestamp(value)
    if parsed is None:
        raise ValueError(f"{field}_invalid")
    return parsed


def _parse_aware_timestamp(value: Any) -> datetime | None:
    if not _nonempty_string(value):
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _valid_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )
