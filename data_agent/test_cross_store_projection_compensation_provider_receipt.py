from __future__ import annotations

from datetime import UTC, datetime

import pytest

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
    FederatedProjectionCompensationProviderReceiptCandidate,
    FederatedProjectionCompensationProviderReceiptValidationError,
    build_federated_compensation_provider_receipt_candidate,
    validate_federated_compensation_provider_receipt_candidate,
)
from data_agent.cross_store_projection_consistency import ProjectionEngine
from data_agent.lakehouse_projection_executor import (
    lakehouse_projection_receipt_fingerprint,
)
from data_agent.platform_contracts import canonical_json_fingerprint
from data_agent.postgis_projection_executor import (
    postgis_projection_receipt_fingerprint,
)
from data_agent.rdf_projection_executor import rdf_projection_receipt_fingerprint
from data_agent.test_cross_store_projection_compensation_provider_adapter import (
    _inputs,
)


def _materialization(*, expected_target_content_sha256="c" * 64):
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
            expected_target_content_sha256=expected_target_content_sha256,
            expected_target_row_count=3,
        )
        for binding in plan_set.plan_bindings
    )
    materialization = build_federated_compensation_provider_materialization_set(
        plan_set,
        materialization_inputs,
        materialized_by="workload:chongqing-compensation-materializer",
    )
    binding = next(
        item for item in materialization.bindings if item.target_engine is ProjectionEngine.POSTGIS
    )
    return materialization, binding


def _postgis_receipt_document(binding, **changes):
    values = {
        "status": "completed",
        "tenant_id": binding.tenant_id,
        "projection_id": binding.projection_id,
        "target_ref": binding.target_ref,
        "action": binding.provider_action,
        "plan_sha256": binding.provider_plan_sha256,
        "idempotency_key": binding.provider_idempotency_key,
        "target_exists": True,
        "target_content_sha256": "c" * 64,
        "target_row_count": 3,
        "observed_at": datetime(2026, 8, 17, 10, tzinfo=UTC),
    }
    values.update(changes)
    commit_ref = {
        "provider": "postgresql",
        "provider_commit": "commit-42",
        "plan_sha256": values["plan_sha256"],
        "idempotency_key": values["idempotency_key"],
    }
    receipt_sha256 = postgis_projection_receipt_fingerprint(
        tenant_id=values["tenant_id"],
        projection_id=values["projection_id"],
        target_ref=values["target_ref"],
        action=values["action"],
        plan_sha256=values["plan_sha256"],
        idempotency_key=values["idempotency_key"],
        provider_commit_ref=commit_ref,
        target_exists=values["target_exists"],
        target_content_sha256=values["target_content_sha256"],
        target_row_count=values["target_row_count"],
    )
    values["provider_commit_ref"] = {
        **commit_ref,
        "receipt_sha256": receipt_sha256,
    }
    return values


def _receipt_document(binding):
    if binding.target_engine is ProjectionEngine.POSTGIS:
        return _postgis_receipt_document(binding)
    values = {
        "status": "completed",
        "tenant_id": binding.tenant_id,
        "projection_id": binding.projection_id,
        "target_ref": binding.target_ref,
        "action": binding.provider_action,
        "plan_sha256": binding.provider_plan_sha256,
        "idempotency_key": binding.provider_idempotency_key,
        "target_exists": True,
        "target_content_sha256": "c" * 64,
        "target_row_count": 3,
        "observed_at": datetime(2026, 8, 17, 10, tzinfo=UTC),
    }
    commit_ref = {
        "provider": (
            "fuseki" if binding.target_engine is ProjectionEngine.RDF else "spark_iceberg"
        ),
        "provider_commit": "commit-42",
        "plan_sha256": values["plan_sha256"],
        "idempotency_key": values["idempotency_key"],
    }
    fingerprint = (
        rdf_projection_receipt_fingerprint
        if binding.target_engine is ProjectionEngine.RDF
        else lakehouse_projection_receipt_fingerprint
    )
    receipt_sha256 = fingerprint(
        tenant_id=values["tenant_id"],
        projection_id=values["projection_id"],
        target_ref=values["target_ref"],
        action=values["action"],
        plan_sha256=values["plan_sha256"],
        idempotency_key=values["idempotency_key"],
        provider_commit_ref=commit_ref,
        target_exists=values["target_exists"],
        target_content_sha256=values["target_content_sha256"],
        target_row_count=values["target_row_count"],
    )
    values["provider_commit_ref"] = {
        **commit_ref,
        "receipt_sha256": receipt_sha256,
    }
    if binding.target_engine is ProjectionEngine.LAKEHOUSE:
        values["snapshot_id"] = 4242
    return values


def _reseal_candidate(candidate, **changes):
    values = candidate.model_dump(mode="json", exclude={"receipt_candidate_sha256"})
    values.update(changes)
    receipt_candidate_sha256 = canonical_json_fingerprint(
        {
            "schema": FederatedProjectionCompensationProviderReceiptCandidate.schema_id,
            "data": values,
        }
    )
    return FederatedProjectionCompensationProviderReceiptCandidate(
        **values,
        receipt_candidate_sha256=receipt_candidate_sha256,
    )


def test_provider_native_receipt_is_validated_without_authority_admission() -> None:
    materialization, binding = _materialization()
    candidate = build_federated_compensation_provider_receipt_candidate(
        materialization,
        binding,
        _postgis_receipt_document(binding),
    )

    validation = validate_federated_compensation_provider_receipt_candidate(
        materialization,
        candidate,
    )

    assert validation.validation_state == "validated_not_authority_admitted"
    assert validation.provider_plan_sha256 == binding.provider_plan_sha256
    assert validation.provider_idempotency_key == binding.provider_idempotency_key
    assert validation.authority_write_allowed is False
    assert validation.provider_execution_performed is False
    assert validation.receipt_is_authority_record is False
    assert validation.review_state == "technical_baseline_unreviewed"
    assert validation.intended_use == "assisted_precheck_not_for_production_decision"
    assert "receipt_document" not in validation.model_dump(mode="json")


def test_all_chongqing_materialized_targets_reuse_native_receipt_contracts() -> None:
    materialization, _ = _materialization()

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

    assert tuple(validation.target_engine for validation in validations) == (
        ProjectionEngine.POSTGIS,
        ProjectionEngine.RDF,
        ProjectionEngine.LAKEHOUSE,
    )
    assert all(
        validation.validation_state == "validated_not_authority_admitted"
        and validation.authority_write_allowed is False
        for validation in validations
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("plan_sha256", "d" * 64),
        ("idempotency_key", "e" * 64),
        ("target_ref", "postgis://customer/drifted"),
    ],
)
def test_provider_native_receipt_rejects_materialized_plan_drift(
    field: str,
    value: str,
) -> None:
    materialization, binding = _materialization()
    candidate = build_federated_compensation_provider_receipt_candidate(
        materialization,
        binding,
        _postgis_receipt_document(binding, **{field: value}),
    )

    with pytest.raises(
        FederatedProjectionCompensationProviderReceiptValidationError,
        match="differs from materialized plan",
    ):
        validate_federated_compensation_provider_receipt_candidate(
            materialization,
            candidate,
        )


def test_provider_native_receipt_rejects_bad_fingerprint() -> None:
    materialization, binding = _materialization()
    document = _postgis_receipt_document(binding)
    document["provider_commit_ref"]["receipt_sha256"] = "f" * 64
    candidate = build_federated_compensation_provider_receipt_candidate(
        materialization,
        binding,
        document,
    )

    with pytest.raises(
        FederatedProjectionCompensationProviderReceiptValidationError,
        match="fingerprint is invalid",
    ):
        validate_federated_compensation_provider_receipt_candidate(
            materialization,
            candidate,
        )


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"status": "deleted"}, "status differs from provider action"),
        (
            {
                "target_exists": False,
                "target_content_sha256": None,
                "target_row_count": 0,
            },
            "rebuild receipt reports a missing target",
        ),
    ],
)
def test_provider_native_receipt_rejects_action_outcome_mismatch(
    changes: dict,
    message: str,
) -> None:
    materialization, binding = _materialization()
    candidate = build_federated_compensation_provider_receipt_candidate(
        materialization,
        binding,
        _postgis_receipt_document(binding, **changes),
    )

    with pytest.raises(
        FederatedProjectionCompensationProviderReceiptValidationError,
        match=message,
    ):
        validate_federated_compensation_provider_receipt_candidate(
            materialization,
            candidate,
        )


def test_provider_native_receipt_rejects_drift_from_materialized_expected_state() -> None:
    materialization, binding = _materialization(
        expected_target_content_sha256="d" * 64,
    )
    candidate = build_federated_compensation_provider_receipt_candidate(
        materialization,
        binding,
        _postgis_receipt_document(binding),
    )

    with pytest.raises(
        FederatedProjectionCompensationProviderReceiptValidationError,
        match="outcome differs from materialized expectation",
    ):
        validate_federated_compensation_provider_receipt_candidate(
            materialization,
            candidate,
        )


def test_provider_native_receipt_rejects_wrong_receipt_schema() -> None:
    materialization, binding = _materialization()
    candidate = build_federated_compensation_provider_receipt_candidate(
        materialization,
        binding,
        _postgis_receipt_document(binding),
    )
    candidate = _reseal_candidate(
        candidate,
        receipt_schema_id="gda.rdf-projection-repair-receipt.v1",
    )

    with pytest.raises(
        FederatedProjectionCompensationProviderReceiptValidationError,
        match="differs from materialization",
    ):
        validate_federated_compensation_provider_receipt_candidate(
            materialization,
            candidate,
        )
