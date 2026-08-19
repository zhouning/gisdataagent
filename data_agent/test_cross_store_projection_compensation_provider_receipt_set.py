from __future__ import annotations

from datetime import UTC, datetime

import pytest

from data_agent.cross_store_projection_compensation_federated_run import (
    FederatedCompensationProviderOutcome,
    FederatedCompensationProviderOutcomeStatus,
    FederatedCompensationRunProviderFailureError,
    build_federated_compensation_run_bindings,
    execute_federated_compensation_run,
)
from data_agent.cross_store_projection_compensation_provider_adapter import (
    resolve_federated_compensation_provider_adapter,
)
from data_agent.cross_store_projection_compensation_provider_materialization import (
    FederatedProjectionCompensationProviderMaterializationInput,
    build_federated_compensation_provider_materialization_set,
)
from data_agent.cross_store_projection_compensation_provider_plan import (
    build_federated_compensation_provider_plan_set,
)
from data_agent.cross_store_projection_compensation_provider_receipt import (
    build_federated_compensation_provider_receipt_candidate,
    validate_federated_compensation_provider_receipt_candidate,
)
from data_agent.cross_store_projection_compensation_provider_receipt_set import (
    FederatedProjectionCompensationProviderReceiptSetError,
    build_federated_compensation_provider_receipt_validation_set,
    build_federated_compensation_provider_receipt_validation_set_from_run,
)
from data_agent.cross_store_projection_consistency import ProjectionEngine
from data_agent.platform_contracts import canonical_json_fingerprint
from data_agent.test_cross_store_projection_compensation_provider_adapter import (
    _inputs,
)
from data_agent.test_cross_store_projection_compensation_provider_receipt import (
    _postgis_receipt_document,
    _receipt_document,
)


def _receipt_set_inputs():
    intent, _, registry, request = _inputs()
    resolution = resolve_federated_compensation_provider_adapter(
        intent,
        request,
        registry,
    )
    plan_set = build_federated_compensation_provider_plan_set(intent, resolution)
    materialization_inputs = tuple(
        FederatedProjectionCompensationProviderMaterializationInput(
            position=binding.position,
            projection_id=f"customer-projection-{binding.position}",
            payload_sha256=f"{binding.position + 17:064x}",
            expected_target_exists=True,
            expected_target_content_sha256="c" * 64,
            expected_target_row_count=3,
        )
        for binding in plan_set.plan_bindings
    )
    materialization = build_federated_compensation_provider_materialization_set(
        plan_set,
        materialization_inputs,
        materialized_by="workload:chongqing-compensation-materializer",
    )
    validations = tuple(
        validate_federated_compensation_provider_receipt_candidate(
            materialization,
            build_federated_compensation_provider_receipt_candidate(
                materialization,
                binding,
                _receipt_document(binding),
            ),
        )
        for binding in materialization.bindings
    )
    return intent, plan_set, materialization, validations


def _run_result_for_receipt_set(
    intent,
    plan_set,
    materialization,
    validations,
    *,
    receipt_sha256_override: str | None = None,
    fail_at_position: int | None = None,
):
    bindings = build_federated_compensation_run_bindings(plan_set, materialization)
    validation_by_binding = {
        validation.materialization_binding_sha256: validation
        for validation in validations
    }

    def invoke(binding):
        if binding.position == fail_at_position:
            raise FederatedCompensationRunProviderFailureError("provider_rejected")
        validation = validation_by_binding[binding.materialization_binding_sha256]
        values = {
            "tenant_id": intent.tenant_id,
            "run_id": intent.run_id,
            "position": binding.position,
            "source_plan_sha256": binding.source_plan_sha256,
            "provider_plan_sha256": binding.provider_plan_sha256,
            "provider_idempotency_key": binding.provider_idempotency_key,
            "status": (
                FederatedCompensationProviderOutcomeStatus.REPLAYED
                if binding.position == 1
                else FederatedCompensationProviderOutcomeStatus.COMMITTED
            ),
            "provider_receipt_sha256": (
                receipt_sha256_override
                if receipt_sha256_override is not None and binding.position == 1
                else validation.provider_receipt_sha256
            ),
            "error_code": None,
        }
        return FederatedCompensationProviderOutcome(
            **values,
            outcome_sha256=canonical_json_fingerprint(
                {
                    "schema": FederatedCompensationProviderOutcome.schema_id,
                    "data": values,
                }
            ),
        )

    return execute_federated_compensation_run(bindings, invoke)


def test_complete_receipt_set_rebinds_chain_without_authority_write() -> None:
    intent, plan_set, materialization, validations = _receipt_set_inputs()

    receipt_set = build_federated_compensation_provider_receipt_validation_set(
        intent,
        plan_set,
        materialization,
        validations,
    )
    replay = build_federated_compensation_provider_receipt_validation_set(
        intent,
        plan_set,
        materialization,
        validations,
    )

    assert receipt_set.validation_set_sha256 == replay.validation_set_sha256
    assert receipt_set.receipt_count == len(materialization.bindings) == 3
    assert receipt_set.receipt_set_state == (
        "complete_provider_receipts_pending_authority_admission"
    )
    assert receipt_set.provider_receipts_complete is True
    assert receipt_set.authority_admission_performed is False
    assert receipt_set.authority_write_allowed is False
    assert receipt_set.checkpoint_write_allowed is False
    assert receipt_set.compensation_completion_allowed is False
    assert receipt_set.provider_invocation_performed_by_aggregator is False
    assert receipt_set.execution_approval_case_ref == (intent.execution_approval_case_ref)
    assert receipt_set.review_state == "technical_baseline_unreviewed"
    assert receipt_set.intended_use == ("assisted_precheck_not_for_production_decision")
    document = receipt_set.model_dump(mode="json")
    assert "receipt_document" not in str(document)
    assert "provider_commit_ref" not in str(document)


def test_complete_federated_run_must_match_each_validated_receipt() -> None:
    intent, plan_set, materialization, validations = _receipt_set_inputs()
    run_result = _run_result_for_receipt_set(
        intent,
        plan_set,
        materialization,
        validations,
    )

    receipt_set = build_federated_compensation_provider_receipt_validation_set_from_run(
        intent,
        plan_set,
        materialization,
        run_result,
        validations,
    )

    assert receipt_set.provider_receipts_complete is True
    assert receipt_set.receipt_count == len(run_result.steps)
    assert receipt_set.authority_admission_performed is False


def test_federated_receipt_set_rejects_outcome_receipt_fingerprint_drift() -> None:
    intent, plan_set, materialization, validations = _receipt_set_inputs()
    run_result = _run_result_for_receipt_set(
        intent,
        plan_set,
        materialization,
        validations,
        receipt_sha256_override="f" * 64,
    )

    with pytest.raises(
        FederatedProjectionCompensationProviderReceiptSetError,
        match="differs from federated run outcome",
    ):
        build_federated_compensation_provider_receipt_validation_set_from_run(
            intent,
            plan_set,
            materialization,
            run_result,
            validations,
        )


def test_federated_receipt_set_rejects_incomplete_run_before_authority_admission() -> None:
    intent, plan_set, materialization, validations = _receipt_set_inputs()
    run_result = _run_result_for_receipt_set(
        intent,
        plan_set,
        materialization,
        validations,
        fail_at_position=1,
    )

    with pytest.raises(
        FederatedProjectionCompensationProviderReceiptSetError,
        match="not complete for receipt-set admission",
    ):
        build_federated_compensation_provider_receipt_validation_set_from_run(
            intent,
            plan_set,
            materialization,
            run_result,
            validations,
        )


@pytest.mark.parametrize("mode", ["missing", "duplicate"])
def test_receipt_set_requires_every_materialization_exactly_once(mode: str) -> None:
    intent, plan_set, materialization, validations = _receipt_set_inputs()
    invalid = validations[:-1] if mode == "missing" else (*validations, validations[0])

    with pytest.raises(
        FederatedProjectionCompensationProviderReceiptSetError,
        match="every materialization exactly once",
    ):
        build_federated_compensation_provider_receipt_validation_set(
            intent,
            plan_set,
            materialization,
            invalid,
        )


def test_receipt_set_rejects_receipts_from_another_materialization() -> None:
    intent, plan_set, materialization, validations = _receipt_set_inputs()
    different_inputs = tuple(
        FederatedProjectionCompensationProviderMaterializationInput(
            position=binding.position,
            projection_id=binding.projection_id,
            payload_sha256=f"{binding.position + 29:064x}",
            expected_target_exists=binding.expected_target_exists,
            expected_target_content_sha256=(binding.expected_target_content_sha256),
            expected_target_row_count=binding.expected_target_row_count,
        )
        for binding in materialization.bindings
    )
    different_materialization = build_federated_compensation_provider_materialization_set(
        plan_set,
        different_inputs,
        materialized_by="workload:chongqing-compensation-materializer",
    )

    with pytest.raises(
        FederatedProjectionCompensationProviderReceiptSetError,
        match="every materialization exactly once",
    ):
        build_federated_compensation_provider_receipt_validation_set(
            intent,
            plan_set,
            different_materialization,
            validations,
        )


def test_receipt_set_rejects_observation_before_authorization_consumption() -> None:
    intent, plan_set, materialization, validations = _receipt_set_inputs()
    position = next(
        index
        for index, binding in enumerate(materialization.bindings)
        if binding.target_engine is ProjectionEngine.POSTGIS
    )
    binding = materialization.bindings[position]
    early_candidate = build_federated_compensation_provider_receipt_candidate(
        materialization,
        binding,
        _postgis_receipt_document(
            binding,
            observed_at=datetime(2026, 8, 15, 10, tzinfo=UTC),
        ),
    )
    early_validation = validate_federated_compensation_provider_receipt_candidate(
        materialization,
        early_candidate,
    )
    early_validations = tuple(
        early_validation if index == position else validation
        for index, validation in enumerate(validations)
    )

    with pytest.raises(
        FederatedProjectionCompensationProviderReceiptSetError,
        match="predates authorization consumption",
    ):
        build_federated_compensation_provider_receipt_validation_set(
            intent,
            plan_set,
            materialization,
            early_validations,
        )


def test_receipt_set_rejects_unsealed_dispatch_or_plan_drift() -> None:
    intent, plan_set, materialization, validations = _receipt_set_inputs()
    drifted = plan_set.model_copy(update={"dispatch_intent_sha256": "f" * 64})

    with pytest.raises(
        FederatedProjectionCompensationProviderReceiptSetError,
        match="input violates its sealed contract",
    ):
        build_federated_compensation_provider_receipt_validation_set(
            intent,
            drifted,
            materialization,
            validations,
        )
