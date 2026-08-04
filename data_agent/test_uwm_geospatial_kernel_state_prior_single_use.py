import copy
import json
import math
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from data_agent.test_uwm_geospatial_kernel_state_prior_transition_evaluation import (
    _bindings,
    _holdout_records,
    _leakage_audit,
    _prediction_artifacts,
    _protocol,
    _receipt_chain,
)
from data_agent.uwm.dam_geospatial_kernel.state_prior_transition_execution import (
    DAM_GK_STATE_PRIOR_SINGLE_USE_EXECUTION_SCHEMA,
    DAM_GK_STATE_PRIOR_SINGLE_USE_FINALIZATION_SCHEMA,
    compute_state_prior_transition_single_use_finalization_sha256,
    execute_single_use_state_prior_transition_evaluation,
    reserve_state_prior_transition_evaluation,
    validate_state_prior_transition_single_use_execution,
    validate_state_prior_transition_single_use_finalization,
)
from data_agent.uwm.dam_geospatial_kernel.state_prior_transition_registry import (
    DAM_GK_STATE_PRIOR_SINGLE_USE_REGISTRY_RECORD_SCHEMA,
    SQLiteStatePriorTransitionSingleUseRegistry,
    compute_state_prior_transition_single_use_registry_record_sha256,
    validate_state_prior_transition_single_use_registry_record,
)


def test_formal_transition_evaluation_is_reserved_and_finalized_once(tmp_path):
    inputs = _single_use_inputs()
    receipt_path = tmp_path / "state-prior-transition-single-use.json"

    execution = _execute(receipt_path, inputs)

    assert execution["schema"] == DAM_GK_STATE_PRIOR_SINGLE_USE_EXECUTION_SCHEMA
    assert execution["evaluation"]["state_prior_transition_evaluation_ready"] is True
    final_receipt = execution["single_use_receipt"]
    assert final_receipt["schema"] == DAM_GK_STATE_PRIOR_SINGLE_USE_FINALIZATION_SCHEMA
    assert final_receipt["status"] == "completed"
    assert final_receipt["rerun_permitted"] is False
    assert final_receipt["evaluation_sha256"]
    assert final_receipt["evaluation_ready"] is True
    assert len(final_receipt["reservation"]["single_use_key_sha256"]) == 64
    assert json.loads(receipt_path.read_text(encoding="utf-8")) == final_receipt
    assert validate_state_prior_transition_single_use_execution(
        execution,
        protocol=inputs["protocol"],
        registration_receipt=inputs["registration"],
        opening_receipt=inputs["opening"],
        prediction_artifacts=inputs["artifacts"],
    ) == {"valid": True, "errors": []}


def test_completed_reservation_blocks_repeated_evaluation(tmp_path):
    inputs = _single_use_inputs()
    receipt_path = tmp_path / "state-prior-transition-repeat.json"
    _execute(receipt_path, inputs)

    with pytest.raises(RuntimeError, match="single_use_reservation_already_exists"):
        _execute(receipt_path, inputs)


def test_failed_evaluation_consumes_reservation_and_blocks_retry(tmp_path):
    inputs = _single_use_inputs()
    receipt_path = tmp_path / "state-prior-transition-failed.json"
    inputs["rows"][0]["forcing_sha256"] = "invalid"

    with pytest.raises(ValueError, match="forcing_sha256_invalid"):
        _execute(receipt_path, inputs)

    failed_receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert failed_receipt["status"] == "failed"
    assert failed_receipt["rerun_permitted"] is False
    assert failed_receipt["failure_code"] == "evaluation_failed:ValueError"
    assert failed_receipt["evaluation_sha256"] is None
    assert validate_state_prior_transition_single_use_finalization(
        failed_receipt,
        protocol=inputs["protocol"],
        registration_receipt=inputs["registration"],
        opening_receipt=inputs["opening"],
        prediction_artifacts=inputs["artifacts"],
        evaluation=None,
    ) == {"valid": True, "errors": []}
    with pytest.raises(RuntimeError, match="single_use_reservation_already_exists"):
        _execute(receipt_path, inputs)


def test_reservation_file_tampering_is_detected_before_consumption(tmp_path):
    inputs = _single_use_inputs()
    receipt_path = tmp_path / "state-prior-transition-tampered.json"
    reservation = reserve_state_prior_transition_evaluation(
        receipt_path,
        reservation_id="tampered-state-prior-transition-reservation",
        reserved_at="2026-08-04T15:58:00Z",
        evaluation_id="tampered-state-prior-transition-evaluation",
        protocol=inputs["protocol"],
        registration_receipt=inputs["registration"],
        opening_receipt=inputs["opening"],
        prediction_artifacts=inputs["artifacts"],
        evaluator_sha256="9" * 64,
    )
    forged = json.loads(receipt_path.read_text(encoding="utf-8"))
    forged["prediction_artifact_bundle_sha256"] = "0" * 64
    receipt_path.write_text(json.dumps(forged), encoding="utf-8")

    with pytest.raises(RuntimeError, match="reservation_changed_or_already_consumed"):
        reservation.fail(
            failure_code="fixture_failure",
            consumed_at="2026-08-04T16:00:00Z",
            protocol=inputs["protocol"],
            registration_receipt=inputs["registration"],
            opening_receipt=inputs["opening"],
            prediction_artifacts=inputs["artifacts"],
        )


def test_prediction_created_before_holdout_opening_cannot_be_reserved(tmp_path):
    inputs = _single_use_inputs()
    receipt_path = tmp_path / "state-prior-transition-early-prediction.json"
    inputs["artifacts"]["full_state_prior"]["created_at"] = "2026-08-04T15:54:00Z"

    with pytest.raises(ValueError, match="created_before_holdout_opening"):
        reserve_state_prior_transition_evaluation(
            receipt_path,
            reservation_id="early-prediction-reservation",
            reserved_at="2026-08-04T15:58:00Z",
            evaluation_id="early-prediction-evaluation",
            protocol=inputs["protocol"],
            registration_receipt=inputs["registration"],
            opening_receipt=inputs["opening"],
            prediction_artifacts=inputs["artifacts"],
            evaluator_sha256="9" * 64,
        )

    assert not receipt_path.exists()


def test_final_receipt_claim_escalation_is_rejected_after_rehash(tmp_path):
    inputs = _single_use_inputs()
    execution = _execute(
        tmp_path / "state-prior-transition-claim-escalation.json",
        inputs,
    )
    forged = copy.deepcopy(execution["single_use_receipt"])
    forged["claim_boundary"]["scientific_result_claim"] = True
    forged["finalization_receipt_sha256"] = (
        compute_state_prior_transition_single_use_finalization_sha256(forged)
    )

    validation = validate_state_prior_transition_single_use_finalization(
        forged,
        protocol=inputs["protocol"],
        registration_receipt=inputs["registration"],
        opening_receipt=inputs["opening"],
        prediction_artifacts=inputs["artifacts"],
        evaluation=execution["evaluation"],
    )

    assert not validation["valid"]
    assert "single_use_finalization_claim_boundary_invalid" in validation["errors"]
    assert "single_use_finalization_receipt_sha256_mismatch" not in validation["errors"]


def test_nonready_missing_split_result_still_gets_canonical_final_receipt(tmp_path):
    inputs = _single_use_inputs()
    inputs["rows"] = [row for row in inputs["rows"] if row["split"] != "future_action_conditioned"]
    inputs["artifacts"], inputs["evidence_refs"] = _prediction_artifacts(
        inputs["rows"],
        inputs["full"],
        inputs["zero"],
        inputs["shuffled"],
        inputs["protocol"],
        inputs["registration"],
        inputs["opening"],
    )

    execution = _execute(
        tmp_path / "state-prior-transition-missing-split.json",
        inputs,
    )

    assert execution["evaluation"]["state_prior_transition_evaluation_ready"] is False
    assert math.isinf(
        execution["evaluation"]["split_metrics"]["future_action_conditioned"][
            "traditional_baseline"
        ]["mae"]
    )
    assert execution["single_use_receipt"]["status"] == "completed"
    assert execution["single_use_receipt"]["evaluation_sha256"]


def test_registered_execution_binds_append_only_registry_record(tmp_path):
    inputs = _single_use_inputs()
    registry = SQLiteStatePriorTransitionSingleUseRegistry(
        tmp_path / "state-prior-transition-registry.sqlite3"
    )

    execution = _execute(
        tmp_path / "registered-state-prior-transition.json",
        inputs,
        registry=registry,
    )

    record = execution["single_use_registry_record"]
    assert record["schema"] == DAM_GK_STATE_PRIOR_SINGLE_USE_REGISTRY_RECORD_SCHEMA
    assert record["status"] == "completed"
    assert [event["event_type"] for event in record["events"]] == [
        "reserved",
        "completed",
    ]
    assert record["rerun_permitted"] is False
    assert record["finalization_receipt"] == execution["single_use_receipt"]
    stored = registry.get_record(record["single_use_key_sha256"])
    assert stored == record
    assert validate_state_prior_transition_single_use_execution(
        execution,
        protocol=inputs["protocol"],
        registration_receipt=inputs["registration"],
        opening_receipt=inputs["opening"],
        prediction_artifacts=inputs["artifacts"],
    ) == {"valid": True, "errors": []}


def test_registry_blocks_same_key_at_a_different_local_receipt_path(tmp_path):
    inputs = _single_use_inputs()
    registry = SQLiteStatePriorTransitionSingleUseRegistry(tmp_path / "cross-path-registry.sqlite3")
    _execute(tmp_path / "first-local-receipt.json", inputs, registry=registry)
    second_path = tmp_path / "second-local-receipt.json"

    with pytest.raises(RuntimeError, match="single_use_registry_key_already_reserved"):
        _execute(second_path, inputs, registry=registry)

    blocked_receipt = json.loads(second_path.read_text(encoding="utf-8"))
    assert blocked_receipt["status"] == "reserved"
    assert blocked_receipt["rerun_permitted"] is False


def test_registry_records_failed_evaluation_and_blocks_cross_path_retry(tmp_path):
    inputs = _single_use_inputs()
    inputs["rows"][0]["forcing_sha256"] = "invalid"
    registry = SQLiteStatePriorTransitionSingleUseRegistry(
        tmp_path / "failed-evaluation-registry.sqlite3"
    )
    failed_path = tmp_path / "failed-registered-evaluation.json"

    with pytest.raises(ValueError, match="forcing_sha256_invalid"):
        _execute(failed_path, inputs, registry=registry)

    failed_receipt = json.loads(failed_path.read_text(encoding="utf-8"))
    key = failed_receipt["reservation"]["single_use_key_sha256"]
    record = registry.get_record(key)
    assert record["status"] == "failed"
    assert [event["event_type"] for event in record["events"]] == [
        "reserved",
        "failed",
    ]
    with pytest.raises(RuntimeError, match="single_use_registry_key_already_reserved"):
        _execute(tmp_path / "failed-cross-path-retry.json", inputs, registry=registry)


def test_registry_rejects_duplicate_finalization(tmp_path):
    inputs = _single_use_inputs()
    registry = SQLiteStatePriorTransitionSingleUseRegistry(
        tmp_path / "duplicate-finalization-registry.sqlite3"
    )
    execution = _execute(
        tmp_path / "duplicate-finalization.json",
        inputs,
        registry=registry,
    )

    with pytest.raises(RuntimeError, match="single_use_registry_already_finalized"):
        registry.record_finalization(execution["single_use_receipt"])


def test_registry_finalization_failure_still_blocks_rerun(tmp_path):
    inputs = _single_use_inputs()
    backend = SQLiteStatePriorTransitionSingleUseRegistry(
        tmp_path / "finalization-failure-registry.sqlite3"
    )

    class FailingFinalizationRegistry:
        def reserve(self, receipt):
            return backend.reserve(receipt)

        def record_finalization(self, receipt):
            raise RuntimeError("forced_registry_finalization_failure")

    receipt_path = tmp_path / "finalization-failure.json"
    with pytest.raises(RuntimeError, match="forced_registry_finalization_failure"):
        _execute(
            receipt_path,
            inputs,
            registry=FailingFinalizationRegistry(),
        )

    local_receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert local_receipt["status"] == "completed"
    key = local_receipt["reservation"]["single_use_key_sha256"]
    assert backend.get_record(key)["status"] == "reserved"
    with pytest.raises(RuntimeError, match="single_use_registry_key_already_reserved"):
        _execute(tmp_path / "finalization-failure-retry.json", inputs, registry=backend)


def test_concurrent_registry_reservation_allows_exactly_one_writer(tmp_path):
    inputs = _single_use_inputs()
    reservation = reserve_state_prior_transition_evaluation(
        tmp_path / "concurrent-local-reservation.json",
        reservation_id="concurrent-state-prior-transition-reservation",
        reserved_at="2026-08-04T15:58:00Z",
        evaluation_id="concurrent-state-prior-transition-evaluation",
        protocol=inputs["protocol"],
        registration_receipt=inputs["registration"],
        opening_receipt=inputs["opening"],
        prediction_artifacts=inputs["artifacts"],
        evaluator_sha256="9" * 64,
    )
    registry = SQLiteStatePriorTransitionSingleUseRegistry(tmp_path / "concurrent-registry.sqlite3")

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(registry.reserve, reservation.receipt) for _ in range(2)]
    outcomes = []
    for future in futures:
        try:
            outcomes.append(future.result()["status"])
        except RuntimeError as exc:
            outcomes.append(str(exc))

    assert outcomes.count("reserved") == 1
    assert outcomes.count("single_use_registry_key_already_reserved") == 1


def test_registry_record_event_tampering_is_detected_after_rehash(tmp_path):
    inputs = _single_use_inputs()
    registry = SQLiteStatePriorTransitionSingleUseRegistry(
        tmp_path / "tampered-registry-record.sqlite3"
    )
    execution = _execute(
        tmp_path / "tampered-registry-record.json",
        inputs,
        registry=registry,
    )
    forged = copy.deepcopy(execution["single_use_registry_record"])
    forged["events"][1]["receipt_sha256"] = "0" * 64
    forged["registry_record_sha256"] = (
        compute_state_prior_transition_single_use_registry_record_sha256(forged)
    )

    validation = validate_state_prior_transition_single_use_registry_record(
        forged,
        reservation=execution["single_use_receipt"]["reservation"],
        finalization=execution["single_use_receipt"],
    )

    assert not validation["valid"]
    assert "single_use_registry_record_event_receipt_sha256_mismatch" in validation["errors"]
    assert "single_use_registry_record_sha256_mismatch" not in validation["errors"]


def test_registry_record_claim_escalation_is_rejected_after_rehash(tmp_path):
    inputs = _single_use_inputs()
    registry = SQLiteStatePriorTransitionSingleUseRegistry(
        tmp_path / "registry-claim-escalation.sqlite3"
    )
    execution = _execute(
        tmp_path / "registry-claim-escalation.json",
        inputs,
        registry=registry,
    )
    forged = copy.deepcopy(execution["single_use_registry_record"])
    forged["claim_boundary"]["scientific_result_claim"] = True
    forged["registry_record_sha256"] = (
        compute_state_prior_transition_single_use_registry_record_sha256(forged)
    )

    validation = validate_state_prior_transition_single_use_registry_record(
        forged,
        reservation=execution["single_use_receipt"]["reservation"],
        finalization=execution["single_use_receipt"],
    )

    assert not validation["valid"]
    assert "single_use_registry_record_claim_boundary_invalid" in validation["errors"]
    assert "single_use_registry_record_sha256_mismatch" not in validation["errors"]


def test_registry_storage_rejects_update_and_delete(tmp_path):
    inputs = _single_use_inputs()
    database_path = tmp_path / "append-only-registry.sqlite3"
    registry = SQLiteStatePriorTransitionSingleUseRegistry(database_path)
    execution = _execute(
        tmp_path / "append-only-registry.json",
        inputs,
        registry=registry,
    )
    key = execution["single_use_receipt"]["reservation"]["single_use_key_sha256"]

    with sqlite3.connect(database_path) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="append_only"):
            connection.execute(
                "UPDATE single_use_attempts SET reservation_json = '{}' "
                "WHERE single_use_key_sha256 = ?",
                (key,),
            )
        with pytest.raises(sqlite3.IntegrityError, match="append_only"):
            connection.execute(
                "DELETE FROM single_use_events WHERE single_use_key_sha256 = ?",
                (key,),
            )


def _single_use_inputs():
    full, zero, shuffled = _bindings()
    rows = _holdout_records()
    protocol = _protocol(full, zero, shuffled)
    registration, opening = _receipt_chain(protocol)
    artifacts, evidence_refs = _prediction_artifacts(
        rows,
        full,
        zero,
        shuffled,
        protocol,
        registration,
        opening,
    )
    return {
        "full": full,
        "zero": zero,
        "shuffled": shuffled,
        "rows": rows,
        "protocol": protocol,
        "registration": registration,
        "opening": opening,
        "artifacts": artifacts,
        "evidence_refs": evidence_refs,
    }


def _execute(receipt_path, inputs, *, registry=None):
    return execute_single_use_state_prior_transition_evaluation(
        receipt_path,
        reservation_id="formal-state-prior-transition-reservation",
        reserved_at="2026-08-04T15:58:00Z",
        evaluation_id="formal-state-prior-transition-evaluation",
        created_at="2026-08-04T16:00:00Z",
        protocol=inputs["protocol"],
        protocol_registration_receipt=inputs["registration"],
        holdout_opening_receipt=inputs["opening"],
        full_binding=inputs["full"],
        zero_binding=inputs["zero"],
        shuffled_binding=inputs["shuffled"],
        holdout_records=inputs["rows"],
        prediction_artifacts=inputs["artifacts"],
        evidence_refs=inputs["evidence_refs"],
        leakage_audit=_leakage_audit(),
        registry=registry,
    )
