from __future__ import annotations

from datetime import UTC, datetime

import pytest

from data_agent.cross_store_projection_compensation_checkpoint_admission import (
    FederatedProjectionCompensationCheckpointAdmissionError,
    build_federated_compensation_checkpoint_admission_preview,
    build_federated_compensation_checkpoint_admission_request,
    preview_federated_compensation_checkpoint_admission,
)
from data_agent.cross_store_projection_compensation_checkpoint_candidate import (
    FederatedProjectionCompensationCheckpointPredecessor,
    build_federated_compensation_checkpoint_candidate_set,
)
from data_agent.cross_store_projection_compensation_provider_materialization import (
    FederatedProjectionCompensationProviderMaterializationInput,
    build_federated_compensation_provider_materialization_set,
)
from data_agent.cross_store_projection_compensation_provider_receipt import (
    build_federated_compensation_provider_receipt_candidate,
    validate_federated_compensation_provider_receipt_candidate,
)
from data_agent.cross_store_projection_compensation_provider_receipt_set import (
    build_federated_compensation_provider_receipt_validation_set,
)
from data_agent.cross_store_projection_consistency import (
    ProjectionRepairPlan,
    build_projection_repair_plan,
    projection_repair_plan_fingerprint,
)
from data_agent.lakehouse_projection_executor import lakehouse_projection_receipt_fingerprint
from data_agent.rdf_projection_executor import rdf_projection_receipt_fingerprint
from data_agent.test_cross_store_projection_compensation_provider_receipt import (
    _postgis_receipt_document,
)
from data_agent.test_cross_store_projection_compensation_provider_receipt_set import (
    _receipt_set_inputs,
)
from data_agent.test_cross_store_projection_federated_recovery import _plans


def _admission_inputs():
    intent, plan_set, _, _ = _receipt_set_inputs()
    source_plans = _plans()
    materialization_inputs = tuple(
        FederatedProjectionCompensationProviderMaterializationInput(
            position=binding.position,
            projection_id=source_plans[binding.position].projection_id,
            payload_sha256=f"{binding.position + 17:064x}",
            expected_target_exists=True,
            expected_target_content_sha256=(
                source_plans[binding.position].desired_state.expected_target_content_sha256
            ),
            expected_target_row_count=(
                source_plans[binding.position].desired_state.expected_row_count
            ),
        )
        for binding in plan_set.plan_bindings
    )
    materialization = build_federated_compensation_provider_materialization_set(
        plan_set,
        materialization_inputs,
        materialized_by="workload:chongqing-compensation-materializer",
    )

    def receipt_document(binding):
        expected = materialization.bindings[binding.position]
        target_sha = expected.expected_target_content_sha256
        row_count = expected.expected_target_row_count
        if binding.target_engine.value == "postgis":
            return _postgis_receipt_document(
                binding,
                target_content_sha256=target_sha,
                target_row_count=row_count,
            )
        values = {
            "status": "completed",
            "tenant_id": binding.tenant_id,
            "projection_id": binding.projection_id,
            "target_ref": binding.target_ref,
            "action": binding.provider_action,
            "plan_sha256": binding.provider_plan_sha256,
            "idempotency_key": binding.provider_idempotency_key,
            "target_exists": True,
            "target_content_sha256": target_sha,
            "target_row_count": row_count,
            "observed_at": datetime(2026, 8, 17, 10, tzinfo=UTC),
        }
        commit_ref = {
            "provider": ("fuseki" if binding.target_engine.value == "rdf" else "spark_iceberg"),
            "provider_commit": "commit-42",
            "plan_sha256": values["plan_sha256"],
            "idempotency_key": values["idempotency_key"],
        }
        fingerprint = (
            rdf_projection_receipt_fingerprint
            if binding.target_engine.value == "rdf"
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
        if binding.target_engine.value == "lakehouse":
            values["snapshot_id"] = 4242
        return values

    validations = tuple(
        validate_federated_compensation_provider_receipt_candidate(
            materialization,
            build_federated_compensation_provider_receipt_candidate(
                materialization,
                binding,
                receipt_document(binding),
            ),
        )
        for binding in materialization.bindings
    )
    receipt_set = build_federated_compensation_provider_receipt_validation_set(
        intent,
        plan_set,
        materialization,
        validations,
    )
    predecessors = tuple(
        FederatedProjectionCompensationCheckpointPredecessor(
            position=binding.position,
            tenant_id=materialization.tenant_id,
            projection_id=binding.projection_id,
            target_engine=binding.target_engine,
            target_ref=binding.target_ref,
            previous_checkpoint_sha256=None,
            next_checkpoint_version=1,
        )
        for binding in materialization.bindings
    )
    candidate_set = build_federated_compensation_checkpoint_candidate_set(
        receipt_set,
        plan_set,
        materialization,
        predecessors,
    )
    return (
        candidate_set,
        plan_set,
        materialization,
        source_plans,
    )


def test_admission_preview_rebinds_complete_plans_without_authority_write() -> None:
    candidate_set, plan_set, materialization, repair_plans = _admission_inputs()

    request = build_federated_compensation_checkpoint_admission_request(
        candidate_set,
        plan_set,
        materialization,
        repair_plans,
    )
    preview = preview_federated_compensation_checkpoint_admission(request)
    replay = build_federated_compensation_checkpoint_admission_preview(
        candidate_set,
        plan_set,
        materialization,
        repair_plans,
    )

    assert request.request_sha256
    assert preview.preview_sha256 == replay.preview_sha256
    assert tuple(item.position for item in preview.items) == (0, 1, 2)
    assert all(item.action == "rebuild" for item in preview.items)
    assert all(item.next_checkpoint_version == 1 for item in preview.items)
    assert all(item.previous_checkpoint_sha256 is None for item in preview.items)
    assert preview.all_repair_plans_admitted is True
    assert preview.authority_admission_performed is False
    assert preview.authority_write_allowed is False
    assert preview.checkpoint_write_allowed is False
    assert preview.compensation_completion_allowed is False
    document = preview.model_dump(mode="json")
    assert "ProjectionCheckpoint" not in str(document)
    assert "target_commit_ref" not in str(document)


def test_admission_rejects_plan_with_different_desired_target_state() -> None:
    candidate_set, plan_set, materialization, repair_plans = _admission_inputs()
    first = repair_plans[0]
    drifted = build_projection_repair_plan(
        first.desired_state.model_copy(
            update={
                "expected_target_content_sha256": "d" * 64,
            }
        ),
        first.observation,
        None,
    )

    with pytest.raises(
        FederatedProjectionCompensationCheckpointAdmissionError,
        match="complete repair plan set|desired target state",
    ):
        build_federated_compensation_checkpoint_admission_request(
            candidate_set,
            plan_set,
            materialization,
            (drifted, *repair_plans[1:]),
        )


def test_admission_rejects_plan_predecessor_or_version_drift() -> None:
    candidate_set, plan_set, materialization, repair_plans = _admission_inputs()
    first = repair_plans[0]
    values = first.model_dump(mode="python", exclude={"plan_sha256"})
    values["next_checkpoint_version"] = 2
    drifted = ProjectionRepairPlan(
        **values,
        plan_sha256=projection_repair_plan_fingerprint(**values),
    )
    with pytest.raises(
        FederatedProjectionCompensationCheckpointAdmissionError,
        match="complete repair plan set|predecessor or version",
    ):
        build_federated_compensation_checkpoint_admission_request(
            candidate_set,
            plan_set,
            materialization,
            (drifted, *repair_plans[1:]),
        )
