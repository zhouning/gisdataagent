from __future__ import annotations

import json
import os
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

import data_agent.test_cross_store_projection_compensation_approval as approval_fixtures
from data_agent.cross_store_projection_compensation_chongqing_deployment import (
    build_chongqing_federated_compensation_deployment_binding,
    build_chongqing_federated_compensation_source_catalog,
)
from data_agent.cross_store_projection_compensation_chongqing_execution_security import (
    CHONGQING_FIVE_PROVIDER_EXECUTION_PURPOSE,
    build_chongqing_federated_compensation_execution_security_decision,
)
from data_agent.cross_store_projection_compensation_chongqing_five_provider_execution import (
    ChongqingFederatedCompensationFiveProviderExecutionValidationError,
    build_chongqing_federated_compensation_five_provider_request_bundle,
    execute_chongqing_federated_compensation_profiled_five_provider_with_receipt_set,
)
from data_agent.cross_store_projection_compensation_chongqing_security_audit import (
    InMemoryChongqingCompensationSecurityAudit,
)
from data_agent.cross_store_projection_compensation_chongqing_source_lineage import (
    build_chongqing_federated_compensation_source_lineage_set,
)
from data_agent.cross_store_projection_compensation_chongqing_source_selection_profile import (
    build_chongqing_federated_compensation_profiled_source_lineage_binding,
    build_chongqing_federated_compensation_source_selection_profile,
)
from data_agent.cross_store_projection_compensation_chongqing_source_selection_profile_release import (  # noqa: E501
    build_chongqing_source_selection_profile_execution_release_binding,
    build_initial_chongqing_source_selection_profile_release_history,
)
from data_agent.cross_store_projection_compensation_customer_action_mapping import (
    CustomerCompensationRuleProviderActionMappingError,
    CustomerCompensationRuleProviderRequestBindingInput,
    build_customer_compensation_rule_provider_action_map,
    build_customer_compensation_rule_provider_execution_binding,
)
from data_agent.cross_store_projection_compensation_dispatch import (
    build_federated_projection_compensation_dispatch_rule_current_binding,
)
from data_agent.cross_store_projection_compensation_federated_receipt_execution import (
    FederatedCompensationRegisteredReceiptExecutionState,
)
from data_agent.cross_store_projection_compensation_federated_run import (
    FederatedCompensationProviderInvokerRegistry,
    FederatedCompensationRunProviderFailureError,
)
from data_agent.cross_store_projection_compensation_lakehouse_adapter import (
    build_federated_compensation_lakehouse_mutation_request,
    federated_compensation_lakehouse_payload_fingerprint,
)
from data_agent.cross_store_projection_compensation_object_adapter import (
    build_federated_compensation_object_mutation_request,
    federated_compensation_object_payload_fingerprint,
)
from data_agent.cross_store_projection_compensation_postgis_adapter import (
    build_federated_compensation_postgis_mutation_request,
    federated_compensation_postgis_payload_fingerprint,
)
from data_agent.cross_store_projection_compensation_production_admission import (
    build_chongqing_five_provider_production_admission_target,
    build_initial_chongqing_five_provider_production_admission_history,
    revoke_chongqing_five_provider_production_admission,
)
from data_agent.cross_store_projection_compensation_proposal import (
    build_federated_projection_compensation_proposal,
)
from data_agent.cross_store_projection_compensation_provider_adapter import (
    resolve_federated_compensation_provider_adapter,
)
from data_agent.cross_store_projection_compensation_provider_materialization import (
    FederatedProjectionCompensationProviderMaterializationInput,
    build_federated_compensation_provider_materialization_set,
)
from data_agent.cross_store_projection_compensation_provider_native_invokers import (
    build_federated_compensation_provider_native_invoker_registry,
)
from data_agent.cross_store_projection_compensation_provider_plan import (
    build_federated_compensation_provider_plan_set,
)
from data_agent.cross_store_projection_compensation_rdf_adapter import (
    build_federated_compensation_rdf_mutation_request,
    federated_compensation_rdf_payload_fingerprint,
)
from data_agent.cross_store_projection_compensation_rule_contract import (
    CustomerCompensationRuleStatus,
    build_customer_compensation_rule_contract,
)
from data_agent.cross_store_projection_compensation_vector_adapter import (
    build_federated_compensation_vector_mutation_request,
    federated_compensation_vector_payload_fingerprint,
)
from data_agent.cross_store_projection_consistency import (
    ProjectionDesiredState,
    ProjectionEngine,
    ProjectionTargetObservation,
    build_projection_repair_plan,
)
from data_agent.lakehouse_projection_executor import (
    LakehouseProjectionRepairExecutor,
    LakehouseProjectionTargetRegistry,
    lakehouse_projection_receipt_fingerprint,
)
from data_agent.lakehouse_projection_executor_rehearsal import (
    _DEFAULT_BUNDLE as _LAKEHOUSE_BUNDLE,
)
from data_agent.lakehouse_projection_executor_rehearsal import (
    _DEFAULT_MINIO_IMAGE as _LAKEHOUSE_MINIO_IMAGE,
)
from data_agent.lakehouse_projection_executor_rehearsal import (
    _DEFAULT_SPARK_IMAGE as _LAKEHOUSE_SPARK_IMAGE,
)
from data_agent.lakehouse_projection_executor_rehearsal import _desired as _lakehouse_desired
from data_agent.lakehouse_projection_executor_rehearsal import _target as _lakehouse_target
from data_agent.lakehouse_projection_executor_rehearsal import _TemporaryLakehouse
from data_agent.lakehouse_projection_spark_provider import (
    DockerSparkIcebergProjectionProvider,
)
from data_agent.object_projection_executor import (
    ObjectProjectionRepairExecutor,
    ObjectProjectionTargetRegistry,
    object_projection_receipt_fingerprint,
)
from data_agent.object_projection_executor_rehearsal import (
    _DEFAULT_BUNDLE as _OBJECT_BUNDLE,
)
from data_agent.object_projection_executor_rehearsal import _DEFAULT_IMAGE as _OBJECT_IMAGE
from data_agent.object_projection_executor_rehearsal import _desired as _object_desired
from data_agent.object_projection_executor_rehearsal import _target as _object_target
from data_agent.object_projection_executor_rehearsal import _TemporaryMinio
from data_agent.platform_contracts import SubjectContext, canonical_json_fingerprint
from data_agent.postgis_projection_executor import (
    PostGISProjectionRepairExecutor,
    PostGISProjectionTargetRegistry,
    postgis_projection_receipt_fingerprint,
    projection_rows_fingerprint,
)
from data_agent.postgis_projection_executor_rehearsal import (
    _TemporaryPostgres as _PostGISTemporaryPostgres,
)
from data_agent.rdf_projection_executor import (
    RDFProjectionRepairExecutor,
    RDFProjectionTargetRegistry,
    rdf_projection_receipt_fingerprint,
)
from data_agent.rdf_projection_executor_rehearsal import _DEFAULT_IMAGE as _RDF_IMAGE
from data_agent.rdf_projection_executor_rehearsal import (
    _DEFAULT_PACKAGE,
    _registered_target,
    _TemporaryFuseki,
)
from data_agent.rdf_projection_executor_rehearsal import _desired as _rdf_desired
from data_agent.test_cross_store_projection_compensation_dispatch import (
    _updated_rule_evidence,
)
from data_agent.test_cross_store_projection_compensation_federated_receipt_execution import (
    _NativeResult,
)
from data_agent.test_cross_store_projection_compensation_postgis_adapter import (
    _ROWS as _POSTGIS_ROWS,
)
from data_agent.test_cross_store_projection_compensation_postgis_adapter import (
    _target as _postgis_target,
)
from data_agent.test_cross_store_projection_compensation_provider_adapter import (
    _inputs,
)
from data_agent.test_cross_store_projection_compensation_rule_contract import (
    _build_approval_evidence,
)
from data_agent.test_cross_store_projection_federated_recovery import (
    NOW,
    _coordinator,
    _dependencies,
)
from data_agent.vector_projection_executor import (
    VectorProjectionRepairExecutor,
    VectorProjectionTargetRegistry,
    vector_projection_receipt_fingerprint,
)
from data_agent.vector_projection_executor_rehearsal import _desired as _vector_desired
from data_agent.vector_projection_executor_rehearsal import _rows as _vector_rows
from data_agent.vector_projection_executor_rehearsal import _target as _vector_target
from data_agent.vector_projection_executor_rehearsal import (
    _TemporaryPostgres as _VectorTemporaryPostgres,
)

_TENANT = "cq-federated-recovery"
_PRODUCTION_ADMISSION_EVALUATED_AT = datetime(2026, 8, 18, 12, tzinfo=UTC)


def _reseal_model(model, hash_field):
    values = model.model_dump(mode="python")
    values[hash_field] = canonical_json_fingerprint(
        {
            "schema": model.schema_id,
            "data": model.model_dump(mode="json", exclude={hash_field}),
        }
    )
    return model.__class__.model_validate(values)


class _LakehouseEndpoint:
    bucket = "cq-five-provider-lakehouse"
    container_endpoint = "http://minio-lakehouse.test:9000"


_REAL_IMAGES = (
    _RDF_IMAGE,
    _OBJECT_IMAGE,
    _LAKEHOUSE_MINIO_IMAGE,
    _LAKEHOUSE_SPARK_IMAGE,
)


def _real_dependencies_available() -> bool:
    if not os.environ.get("DATABASE_URL"):
        return False
    try:
        return all(
            subprocess.run(
                ("docker", "image", "inspect", image),
                check=False,
                capture_output=True,
                timeout=10,
            ).returncode
            == 0
            for image in _REAL_IMAGES
        )
    except (OSError, subprocess.SubprocessError):
        return False


def _missing(target) -> ProjectionTargetObservation:
    return ProjectionTargetObservation(
        tenant_id=target.tenant_id,
        projection_id=target.projection_id,
        target_engine=_engine(target),
        target_ref=target.target_ref,
        target_exists=False,
        observed_content_sha256=None,
        observed_row_count=0,
        observed_by="workload:chongqing-five-provider-preflight-test",
        observed_at=NOW,
    )


def _engine(target) -> ProjectionEngine:
    target_type = type(target).__name__
    return {
        "PostGISProjectionTarget": ProjectionEngine.POSTGIS,
        "VectorProjectionTarget": ProjectionEngine.VECTOR,
        "RDFProjectionTarget": ProjectionEngine.RDF,
        "ObjectProjectionTarget": ProjectionEngine.OBJECT_STORE,
        "LakehouseProjectionTarget": ProjectionEngine.LAKEHOUSE,
    }[target_type]


def _receipt_document(binding):
    values = {
        "status": "completed",
        "tenant_id": binding.tenant_id,
        "projection_id": binding.projection_id,
        "target_ref": binding.target_ref,
        "action": binding.provider_action,
        "plan_sha256": binding.provider_plan_sha256,
        "idempotency_key": binding.provider_idempotency_key,
        "target_exists": binding.expected_target_exists,
        "target_content_sha256": binding.expected_target_content_sha256,
        "target_row_count": binding.expected_target_row_count,
        "observed_at": datetime(2026, 8, 17, 10, tzinfo=UTC),
    }
    commit_ref = {
        "provider": binding.target_engine.value,
        "provider_commit": f"{binding.target_engine.value}:commit-five-provider",
        "plan_sha256": binding.provider_plan_sha256,
        "idempotency_key": binding.provider_idempotency_key,
    }
    fingerprint_kwargs = {
        "tenant_id": binding.tenant_id,
        "projection_id": binding.projection_id,
        "target_ref": binding.target_ref,
        "action": binding.provider_action,
        "plan_sha256": binding.provider_plan_sha256,
        "idempotency_key": binding.provider_idempotency_key,
        "provider_commit_ref": commit_ref,
        "target_exists": binding.expected_target_exists,
        "target_content_sha256": binding.expected_target_content_sha256,
        "target_row_count": binding.expected_target_row_count,
    }
    if binding.target_engine is ProjectionEngine.POSTGIS:
        receipt_sha256 = postgis_projection_receipt_fingerprint(**fingerprint_kwargs)
    elif binding.target_engine is ProjectionEngine.VECTOR:
        receipt_sha256 = vector_projection_receipt_fingerprint(**fingerprint_kwargs)
    elif binding.target_engine is ProjectionEngine.RDF:
        receipt_sha256 = rdf_projection_receipt_fingerprint(**fingerprint_kwargs)
    elif binding.target_engine is ProjectionEngine.OBJECT_STORE:
        values.update(
            target_size_bytes=1,
            object_version_id="version-five-provider",
            object_etag="etag-five-provider",
        )
        receipt_sha256 = object_projection_receipt_fingerprint(
            **fingerprint_kwargs,
            target_size_bytes=1,
        )
    else:
        values["snapshot_id"] = 4242
        receipt_sha256 = lakehouse_projection_receipt_fingerprint(
            **fingerprint_kwargs,
        )
    values["provider_commit_ref"] = {
        **commit_ref,
        "receipt_sha256": receipt_sha256,
    }
    return values


def _five_provider_registry(materialization, *, fail_engine=None):
    materialized_by_position = {binding.position: binding for binding in materialization.bindings}
    calls: list[ProjectionEngine] = []

    def make_invoker(engine: ProjectionEngine):
        def invoke(binding):
            calls.append(engine)
            if engine is fail_engine:
                raise FederatedCompensationRunProviderFailureError(
                    "provider_rejected"
                )
            materialized = materialized_by_position[binding.position]
            return _NativeResult(
                tenant_id=binding.tenant_id,
                run_id=binding.run_id,
                position=binding.position,
                materialization_binding_sha256=(binding.materialization_binding_sha256),
                provider_plan_sha256=binding.provider_plan_sha256,
                provider_idempotency_key=binding.provider_idempotency_key,
                provider_execution_status="provider_mutation_committed",
                provider_execution_performed_by_adapter=True,
                checkpoint_authority_write_performed_by_adapter=False,
                compensation_completion_recorded_by_adapter=False,
                receipt=_receipt_document(materialized),
            )

        return invoke

    return (
        FederatedCompensationProviderInvokerRegistry(
            {engine: make_invoker(engine) for engine in ProjectionEngine}
        ),
        calls,
    )


def _normalized_targets(postgis, vector, rdf, object_store, lakehouse):
    postgis = postgis.model_copy(update={"tenant_id": _TENANT})
    vector = vector.model_copy(
        update={
            "tenant_id": _TENANT,
            "projection_id": "cq.five.vector",
            "target_ref": "vector://temporary/public.cq_five_vector",
            "table_name": "cq_five_vector",
        }
    )
    rdf = rdf.model_copy(
        update={
            "tenant_id": _TENANT,
            "projection_id": "cq.five.rdf",
            "target_ref": "rdf://temporary/cq-five/default",
        }
    )
    object_store = object_store.model_copy(
        update={
            "tenant_id": _TENANT,
            "projection_id": "cq.five.object",
        }
    )
    lakehouse = lakehouse.model_copy(
        update={
            "tenant_id": _TENANT,
            "projection_id": "cq.five.lakehouse",
            "target_ref": "iceberg://lakehouse/cq_customer/cq_five_lakehouse",
            "table": "cq_five_lakehouse",
        }
    )
    return postgis, vector, rdf, object_store, lakehouse, _vector_rows()


def _targets_and_rows():
    return _normalized_targets(
        _postgis_target(),
        _vector_target(),
        _registered_target(
            _DEFAULT_PACKAGE,
            "http://fuseki.test/ontology/data?default",
            "http://fuseki.test/ontology/update",
        ),
        _object_target(
            _OBJECT_BUNDLE,
            "http://minio-object.test:9000",
            "cq-five-provider-object",
        ),
        _lakehouse_target(
            _LAKEHOUSE_BUNDLE,
            _LakehouseEndpoint(),
        ),
    )


def _plans_and_targets(targets_and_rows=None):
    postgis, vector, rdf, object_store, lakehouse, vector_rows = (
        targets_and_rows or _targets_and_rows()
    )
    rdf_executor = RDFProjectionRepairExecutor(RDFProjectionTargetRegistry((rdf,)))
    _, rdf_content_sha256, rdf_triple_count = rdf_executor._load_package(rdf)
    desired = (
        ProjectionDesiredState(
            tenant_id=postgis.tenant_id,
            projection_id=postgis.projection_id,
            source_resource_version_ref=(
                f"gda://{_TENANT}/data_product/chongqing-postgis-five-provider-v1"
            ),
            source_content_sha256="4" * 64,
            target_engine=ProjectionEngine.POSTGIS,
            target_ref=postgis.target_ref,
            target_exists=True,
            expected_target_content_sha256=projection_rows_fingerprint(
                postgis,
                _POSTGIS_ROWS,
            ),
            expected_row_count=len(_POSTGIS_ROWS),
        ),
        _vector_desired(vector, vector_rows, "5" * 64),
        _rdf_desired(
            rdf,
            target_content_sha256=rdf_content_sha256,
            triple_count=rdf_triple_count,
            source_content_sha256=rdf.package_content_sha256,
            source_version=rdf.semantic_version,
        ),
        _object_desired(
            object_store,
            source_sha256=object_store.artifact_sha256,
            source_version=object_store.bundle_version,
        ),
        _lakehouse_desired(
            lakehouse,
            source_sha256=lakehouse.artifact_sha256,
            source_version=lakehouse.bundle_version,
        ),
    )
    targets = (postgis, vector, rdf, object_store, lakehouse)
    plans = tuple(
        build_projection_repair_plan(item, _missing(target), None)
        for item, target in zip(desired, targets, strict=True)
    )
    return plans, targets, vector_rows


def _five_provider_inputs(monkeypatch: pytest.MonkeyPatch, targets_and_rows=None):
    plans, targets, vector_rows = _plans_and_targets(targets_and_rows)
    providers, authorities = _dependencies(
        plans,
        provider_modes={1: "unknown_without_receipt"},
    )
    snapshot = _coordinator(plans, providers, authorities).advance()
    proposal = build_federated_projection_compensation_proposal(plans, snapshot)
    monkeypatch.setattr(approval_fixtures, "_proposal", lambda: proposal)

    intent, _, adapter_registry, resolution_request = _inputs()
    resolution = resolve_federated_compensation_provider_adapter(
        intent,
        resolution_request,
        adapter_registry,
    )
    plan_set = build_federated_compensation_provider_plan_set(intent, resolution)
    by_engine = dict(zip((plan.target_engine for plan in plans), targets, strict=True))
    plan_by_engine = {plan.target_engine: plan for plan in plans}
    payloads = {
        ProjectionEngine.POSTGIS: federated_compensation_postgis_payload_fingerprint(
            by_engine[ProjectionEngine.POSTGIS],
            plan_by_engine[ProjectionEngine.POSTGIS].action,
            _POSTGIS_ROWS,
        ),
        ProjectionEngine.VECTOR: federated_compensation_vector_payload_fingerprint(
            by_engine[ProjectionEngine.VECTOR],
            plan_by_engine[ProjectionEngine.VECTOR].action,
            vector_rows,
        ),
        ProjectionEngine.RDF: federated_compensation_rdf_payload_fingerprint(
            by_engine[ProjectionEngine.RDF],
            plan_by_engine[ProjectionEngine.RDF].action,
        ),
        ProjectionEngine.OBJECT_STORE: federated_compensation_object_payload_fingerprint(
            by_engine[ProjectionEngine.OBJECT_STORE],
            plan_by_engine[ProjectionEngine.OBJECT_STORE].action,
        ),
        ProjectionEngine.LAKEHOUSE: federated_compensation_lakehouse_payload_fingerprint(
            by_engine[ProjectionEngine.LAKEHOUSE],
            plan_by_engine[ProjectionEngine.LAKEHOUSE].action,
        ),
    }
    plans_by_sha256 = {plan.plan_sha256: plan for plan in plans}
    materialization = build_federated_compensation_provider_materialization_set(
        plan_set,
        tuple(
            FederatedProjectionCompensationProviderMaterializationInput(
                position=binding.position,
                projection_id=plans_by_sha256[binding.source_plan_sha256].projection_id,
                payload_sha256=payloads[binding.target_engine],
                expected_target_exists=(
                    plans_by_sha256[binding.source_plan_sha256].desired_state.target_exists
                ),
                expected_target_content_sha256=(
                    plans_by_sha256[
                        binding.source_plan_sha256
                    ].desired_state.expected_target_content_sha256
                ),
                expected_target_row_count=(
                    plans_by_sha256[binding.source_plan_sha256].desired_state.expected_row_count
                ),
            )
            for binding in plan_set.plan_bindings
        ),
        materialized_by="workload:chongqing-five-provider-materializer",
    )
    requests = {
        ProjectionEngine.POSTGIS: build_federated_compensation_postgis_mutation_request(
            intent,
            plan_set,
            materialization,
            plan_by_engine[ProjectionEngine.POSTGIS],
            by_engine[ProjectionEngine.POSTGIS],
            _POSTGIS_ROWS,
            dispatched_by="workload:chongqing-five-provider-dispatcher",
        ),
        ProjectionEngine.VECTOR: build_federated_compensation_vector_mutation_request(
            intent,
            plan_set,
            materialization,
            plan_by_engine[ProjectionEngine.VECTOR],
            by_engine[ProjectionEngine.VECTOR],
            vector_rows,
            dispatched_by="workload:chongqing-five-provider-dispatcher",
        ),
        ProjectionEngine.RDF: build_federated_compensation_rdf_mutation_request(
            intent,
            plan_set,
            materialization,
            plan_by_engine[ProjectionEngine.RDF],
            by_engine[ProjectionEngine.RDF],
            dispatched_by="workload:chongqing-five-provider-dispatcher",
        ),
        ProjectionEngine.OBJECT_STORE: build_federated_compensation_object_mutation_request(
            intent,
            plan_set,
            materialization,
            plan_by_engine[ProjectionEngine.OBJECT_STORE],
            by_engine[ProjectionEngine.OBJECT_STORE],
            dispatched_by="workload:chongqing-five-provider-dispatcher",
        ),
        ProjectionEngine.LAKEHOUSE: build_federated_compensation_lakehouse_mutation_request(
            intent,
            plan_set,
            materialization,
            plan_by_engine[ProjectionEngine.LAKEHOUSE],
            by_engine[ProjectionEngine.LAKEHOUSE],
            dispatched_by="workload:chongqing-five-provider-dispatcher",
        ),
    }
    source_catalog = build_chongqing_federated_compensation_source_catalog()
    deployment_binding = build_chongqing_federated_compensation_deployment_binding(
        intent,
        plan_set,
        materialization,
        source_catalog,
    )
    profile = build_chongqing_federated_compensation_source_selection_profile(
        source_catalog,
        "banzhu_adjustment",
    )
    profile_release_history = build_initial_chongqing_source_selection_profile_release_history(
        profile,
        tenant_id=deployment_binding.tenant_id,
    )
    roles = profile.required_source_roles
    source_lineage_set = build_chongqing_federated_compensation_source_lineage_set(
        source_catalog,
        deployment_binding,
        {item.position: (roles[item.position % len(roles)],) for item in deployment_binding.items},
    )
    profiled_binding = build_chongqing_federated_compensation_profiled_source_lineage_binding(
        source_catalog,
        deployment_binding,
        profile,
        source_lineage_set,
    )
    profile_execution_release_binding = (
        build_chongqing_source_selection_profile_execution_release_binding(
            profile_release_history,
            profile,
            deployment_binding,
            profiled_binding,
        )
    )
    request_bundle = build_chongqing_federated_compensation_five_provider_request_bundle(
        intent,
        plan_set,
        materialization,
        deployment_binding,
        requests,
    )
    return (
        intent,
        plan_set,
        materialization,
        source_catalog,
        deployment_binding,
        profile,
        profile_release_history,
        source_lineage_set,
        profiled_binding,
        profile_execution_release_binding,
        requests,
        request_bundle,
    )


class _StaticRuleAuthorityReader:
    def __init__(self, evidence, *, error=None):
        self.tenant_id = evidence.proposal.tenant_id
        self._evidence = evidence
        self._error = error
        self.calls = 0

    def assessment_evidence_current(self, run_id):
        self.calls += 1
        if run_id != self._evidence.proposal.run_id:
            raise ValueError("unexpected run id")
        if self._error is not None:
            raise self._error
        return self._evidence


class _StaticProfileReleaseReader:
    def __init__(
        self,
        expected_history,
        *,
        returned_history=None,
        return_none=False,
        tenant_id=None,
        error=None,
    ):
        self.tenant_id = tenant_id or expected_history.tenant_id
        self._expected_history = expected_history
        self._returned_history = returned_history or expected_history
        self._return_none = return_none
        self._error = error
        self.calls = 0

    def release_history_current(self, profile_id, scenario_id):
        self.calls += 1
        if (
            profile_id != self._expected_history.profile_id
            or scenario_id != self._expected_history.scenario_id
        ):
            raise ValueError("unexpected profile release identity")
        if self._error is not None:
            raise self._error
        if self._return_none:
            return None
        return self._returned_history


class _StaticProductionAdmissionReader:
    def __init__(
        self,
        expected_history,
        *,
        returned_history=None,
        return_none=False,
        tenant_id=None,
        error=None,
    ):
        self.tenant_id = tenant_id or expected_history.tenant_id
        self._expected_history = expected_history
        self._returned_history = returned_history or expected_history
        self._return_none = return_none
        self._error = error
        self.calls = 0

    def admission_history_current(self, run_id):
        self.calls += 1
        if run_id != self._expected_history.run_id:
            raise ValueError("unexpected production admission run id")
        if self._error is not None:
            raise self._error
        if self._return_none:
            return None
        return self._returned_history


def _execution_subject(
    *,
    subject_id="chongqing-five-provider-dispatcher",
    purpose=CHONGQING_FIVE_PROVIDER_EXECUTION_PURPOSE,
):
    return SubjectContext(
        tenant_id=_TENANT,
        subject_id=subject_id,
        subject_type="workload",
        roles=("compensation_executor",),
        purpose=purpose,
        trace_id="trace-cq-five-provider",
    )


class _StaticExecutionSecurityReader:
    def __init__(
        self,
        tenant_id=_TENANT,
        *,
        effect="allow",
        obligations=(),
        expired=False,
        error=None,
    ):
        self.tenant_id = tenant_id
        self.effect = effect
        self.obligations = obligations
        self.expired = expired
        self.error = error
        self.calls = 0
        self.requests = []

    def execution_security_decision_current(self, request):
        self.calls += 1
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        if self.expired:
            decided_at = request.evaluated_at - timedelta(hours=2)
            expires_at = request.evaluated_at - timedelta(hours=1)
        else:
            decided_at = request.evaluated_at - timedelta(minutes=5)
            expires_at = request.evaluated_at + timedelta(hours=1)
        return build_chongqing_federated_compensation_execution_security_decision(
            request,
            effect=self.effect,
            policy_ref="gda://cq-federated-recovery/policy/five-provider-execution",
            policy_version="1.0.0",
            evaluator_subject="workload:compensation-policy-evaluator",
            obligations=self.obligations,
            decided_at=decided_at,
            expires_at=expires_at,
        )


def _rule_current_preflight(intent):
    evidence, *_ = approval_fixtures._approved_review()
    assert evidence.proposal.proposal_sha256 == intent.proposal_sha256
    return (
        evidence,
        build_federated_projection_compensation_dispatch_rule_current_binding(
            evidence,
            intent,
        ),
        _StaticRuleAuthorityReader(evidence),
    )


def _production_admission_history(
    inputs,
    customer_rule_current_binding,
    *,
    profile_release_binding=None,
    expires_at=None,
):
    target = build_chongqing_five_provider_production_admission_target(
        inputs[0],
        inputs[1],
        inputs[2],
        inputs[4],
        profile_release_binding or inputs[9],
        customer_rule_current_binding,
        request_bundle_sha256=inputs[11].request_bundle_sha256,
    )
    return build_initial_chongqing_five_provider_production_admission_history(
        target,
        authorized_by="human:customer-production-controller",
        authorization_evidence_sha256="a" * 64,
        trust_anchor_sha256="b" * 64,
        authorization_reason="explicit bounded five-Provider production admission",
        authorized_at=_PRODUCTION_ADMISSION_EVALUATED_AT - timedelta(minutes=5),
        expires_at=expires_at
        or _PRODUCTION_ADMISSION_EVALUATED_AT + timedelta(hours=1),
    )


def _execute_five_provider_inputs(
    inputs,
    registry,
    *,
    requests=None,
    request_bundle=None,
    profile_release_reader=None,
    rule_authority_reader=None,
    customer_rule_current_binding=None,
    production_admission_history=None,
    production_admission_reader=None,
    subject_context=None,
    execution_security_reader=None,
    security_audit_port=None,
    production_admission_evaluated_at=_PRODUCTION_ADMISSION_EVALUATED_AT,
):
    if rule_authority_reader is None:
        rule_authority_evidence, default_binding, rule_authority_reader = (
            _rule_current_preflight(inputs[0])
        )
    else:
        default_binding = None
    if customer_rule_current_binding is None:
        customer_rule_current_binding = default_binding or (
            build_federated_projection_compensation_dispatch_rule_current_binding(
                rule_authority_reader._evidence,
                inputs[0],
            )
        )
    if profile_release_reader is None:
        profile_release_reader = _StaticProfileReleaseReader(inputs[6])
    if production_admission_history is None:
        canonical_release_binding = (
            build_chongqing_source_selection_profile_execution_release_binding(
                inputs[6],
                inputs[5],
                inputs[4],
                inputs[8],
            )
        )
        _, canonical_rule_binding, _ = _rule_current_preflight(inputs[0])
        production_admission_history = _production_admission_history(
            inputs,
            canonical_rule_binding,
            profile_release_binding=canonical_release_binding,
        )
    if production_admission_reader is None:
        production_admission_reader = _StaticProductionAdmissionReader(
            production_admission_history
        )
    if subject_context is None:
        subject_context = _execution_subject()
    if execution_security_reader is None:
        execution_security_reader = _StaticExecutionSecurityReader()
    if security_audit_port is None:
        security_audit_port = InMemoryChongqingCompensationSecurityAudit(_TENANT)
    return execute_chongqing_federated_compensation_profiled_five_provider_with_receipt_set(
        *inputs[:-2],
        request_bundle or inputs[-1],
        requests or inputs[-2],
        registry,
        profile_release_reader=profile_release_reader,
        rule_authority_reader=rule_authority_reader,
        customer_rule_current_binding=customer_rule_current_binding,
        production_admission_history=production_admission_history,
        production_admission_reader=production_admission_reader,
        subject_context=subject_context,
        execution_security_reader=execution_security_reader,
        security_audit_port=security_audit_port,
        production_admission_evaluated_at=production_admission_evaluated_at,
    )


def test_request_bundle_seals_exactly_five_engines_without_private_material(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    *_, request_bundle = _five_provider_inputs(monkeypatch)

    assert tuple(item.position for item in request_bundle.items) == tuple(range(5))
    assert {item.target_engine for item in request_bundle.items} == set(ProjectionEngine)
    document = json.dumps(request_bundle.model_dump(mode="json"), sort_keys=True)
    for forbidden in (
        "endpoint_url",
        "rows",
        "artifact_path",
        "bundle_manifest_path",
        "access_key_id",
        "secret_access_key",
        "records",
    ):
        assert forbidden not in document


def test_profiled_five_provider_chain_calls_every_registered_engine_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs = _five_provider_inputs(monkeypatch)
    materialization = inputs[2]
    registry, calls = _five_provider_registry(materialization)
    _, binding, reader = _rule_current_preflight(inputs[0])
    profile_reader = _StaticProfileReleaseReader(inputs[6])
    admission = _production_admission_history(inputs, binding)
    admission_reader = _StaticProductionAdmissionReader(admission)
    security_reader = _StaticExecutionSecurityReader()

    result = _execute_five_provider_inputs(
        inputs,
        registry,
        profile_release_reader=profile_reader,
        rule_authority_reader=reader,
        customer_rule_current_binding=binding,
        production_admission_history=admission,
        production_admission_reader=admission_reader,
        execution_security_reader=security_reader,
    )

    assert calls == [binding.target_engine for binding in materialization.bindings]
    assert len(calls) == 5
    assert profile_reader.calls == 1
    assert reader.calls == 1
    assert admission_reader.calls == 1
    assert security_reader.calls == 1
    assert result.five_provider_preflight_performed is True
    assert result.profile_release_preflight_performed is True
    assert result.profile_release_authority_live_read_performed is True
    assert result.customer_rule_current_preflight_performed is True
    assert result.customer_rule_authority_live_read_performed is True
    assert result.production_admission_preflight_performed is True
    assert result.production_admission_authority_live_read_performed is True
    assert result.subject_purpose_resource_preflight_performed is True
    assert result.execution_security_authority_live_read_performed is True
    assert result.execution_security_decision.effect == "allow"
    assert (
        result.execution_security_decision.request.operation
        == "chongqing.five_provider.execute"
    )
    assert result.production_execution_authorized is True
    assert result.profile_execution_release_binding == inputs[-3]
    assert result.customer_rule_current_binding.dispatch_intent_sha256 == (
        inputs[0].dispatch_intent_sha256
    )
    assert len(result.customer_provider_action_map.items) == 5
    assert (
        result.customer_provider_action_execution_binding.production_execution_authorized
        is False
    )
    assert result.request_bundle_items == inputs[-1].items
    assert result.profiled_execution.source_lineage_execution.deployment_execution.state is (
        FederatedCompensationRegisteredReceiptExecutionState.COMPLETED_RECEIPT_SET_PENDING_AUTHORITY
    )
    assert result.authority_admission_performed is False
    assert result.checkpoint_authority_write_performed is False
    assert result.compensation_completion_recorded is False
    assert result.security_audit_admission.request_sha256 == (
        result.execution_security_decision.request.request_sha256
    )
    assert result.security_audit_admission.decision_sha256 == (
        result.execution_security_decision.decision_sha256
    )
    assert result.security_audit_outcome.outcome == "success"
    assert result.security_audit_outcome.provider_invocations == 5

    tampered_binding = _reseal_model(
        result.customer_provider_action_execution_binding.model_copy(
            update={"plan_set_sha256": "f" * 64}
        ),
        "binding_sha256",
    )
    with pytest.raises(ValidationError, match="five-Provider result"):
        _reseal_model(
            result.model_copy(
                update={
                    "customer_provider_action_execution_binding": tampered_binding
                }
            ),
            "result_sha256",
        )


    security_decision = result.execution_security_decision
    security_request = security_decision.request
    tampered_security_resource = _reseal_model(
        security_request.resources[0].model_copy(update={"target_ref": "tampered-target"}),
        "resource_sha256",
    )
    tampered_security_request = _reseal_model(
        security_request.model_copy(
            update={
                "resources": (
                    tampered_security_resource,
                    *security_request.resources[1:],
                )
            }
        ),
        "request_sha256",
    )
    tampered_security_decision = _reseal_model(
        security_decision.model_copy(update={"request": tampered_security_request}),
        "decision_sha256",
    )
    with pytest.raises(ValidationError, match="five-Provider result"):
        _reseal_model(
            result.model_copy(
                update={"execution_security_decision": tampered_security_decision}
            ),
            "result_sha256",
        )

    tampered_projection_item = _reseal_model(
        result.request_bundle_items[0].model_copy(
            update={"projection_id": "tampered-projection"}
        ),
        "item_sha256",
    )
    with pytest.raises(ValidationError, match="five-Provider result"):
        _reseal_model(
            result.model_copy(
                update={
                    "request_bundle_items": (
                        tampered_projection_item,
                        *result.request_bundle_items[1:],
                    )
                }
            ),
            "result_sha256",
        )

    tampered_request_item = _reseal_model(
        result.request_bundle_items[0].model_copy(update={"request_sha256": "f" * 64}),
        "item_sha256",
    )
    with pytest.raises(ValidationError, match="five-Provider result"):
        _reseal_model(
            result.model_copy(
                update={
                    "request_bundle_items": (
                        tampered_request_item,
                        *result.request_bundle_items[1:],
                    )
                }
            ),
            "result_sha256",
        )


def test_security_audit_failure_stops_result_after_provider_execution(monkeypatch):
    inputs = _five_provider_inputs(monkeypatch)
    registry, calls = _five_provider_registry(inputs[2])

    class _FailingAudit(InMemoryChongqingCompensationSecurityAudit):
        def record_outcome(self, *args, **kwargs):
            raise RuntimeError("audit ledger unavailable")

    with pytest.raises(
        ChongqingFederatedCompensationFiveProviderExecutionValidationError,
        match="security outcome audit",
    ):
        _execute_five_provider_inputs(
            inputs,
            registry,
            security_audit_port=_FailingAudit(_TENANT),
        )
    assert len(calls) == 5


def test_incomplete_provider_run_records_non_success_audit_evidence(
    monkeypatch,
):
    inputs = _five_provider_inputs(monkeypatch)
    registry, calls = _five_provider_registry(
        inputs[2], fail_engine=ProjectionEngine.VECTOR
    )
    audit = InMemoryChongqingCompensationSecurityAudit(_TENANT)

    result = _execute_five_provider_inputs(
        inputs,
        registry,
        security_audit_port=audit,
    )

    assert calls == [ProjectionEngine.POSTGIS, ProjectionEngine.VECTOR]
    assert len(audit.admissions) == 1
    assert len(audit.outcomes) == 1
    assert audit.outcomes[0].outcome == "failure"
    assert audit.outcomes[0].provider_invocations == 2
    assert result.security_audit_outcome.outcome == "failure"
    assert result.security_audit_outcome.provider_invocations == 2


def test_security_audit_admission_failure_stops_before_provider_callback(monkeypatch):
    inputs = _five_provider_inputs(monkeypatch)
    registry, calls = _five_provider_registry(inputs[2])

    class _FailingAudit(InMemoryChongqingCompensationSecurityAudit):
        def record_admission(self, *args, **kwargs):
            raise RuntimeError("audit ledger unavailable")

    with pytest.raises(
        ChongqingFederatedCompensationFiveProviderExecutionValidationError,
        match="security admission audit",
    ):
        _execute_five_provider_inputs(
            inputs,
            registry,
            security_audit_port=_FailingAudit(_TENANT),
        )
    assert calls == []


@pytest.mark.parametrize(
    ("subject_context", "security_reader"),
    (
        (
            _execution_subject(purpose="uncontrolled-purpose"),
            _StaticExecutionSecurityReader(),
        ),
        (_execution_subject(), _StaticExecutionSecurityReader(effect="deny")),
        (_execution_subject(), _StaticExecutionSecurityReader(expired=True)),
        (
            _execution_subject(),
            _StaticExecutionSecurityReader(obligations=("audit",)),
        ),
        (
            _execution_subject(),
            _StaticExecutionSecurityReader(tenant_id="another-tenant"),
        ),
    ),
)
def test_subject_purpose_resource_denial_stops_before_provider_callbacks(
    monkeypatch,
    subject_context,
    security_reader,
):
    inputs = _five_provider_inputs(monkeypatch)
    registry, calls = _five_provider_registry(inputs[2])

    with pytest.raises(
        ChongqingFederatedCompensationFiveProviderExecutionValidationError,
        match="subject-purpose-resource authorization",
    ):
        _execute_five_provider_inputs(
            inputs,
            registry,
            subject_context=subject_context,
            execution_security_reader=security_reader,
        )

    assert calls == []


def test_subject_must_match_provider_dispatch_workload_before_callbacks(monkeypatch):
    inputs = _five_provider_inputs(monkeypatch)
    registry, calls = _five_provider_registry(inputs[2])

    with pytest.raises(
        ChongqingFederatedCompensationFiveProviderExecutionValidationError,
        match="subject-purpose-resource authorization",
    ):
        _execute_five_provider_inputs(
            inputs,
            registry,
            subject_context=_execution_subject(subject_id="another-workload"),
        )

    assert calls == []


def test_profile_release_binding_drift_stops_before_first_provider_callback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs = list(_five_provider_inputs(monkeypatch))
    release_binding = inputs[-3]
    inputs[-3] = release_binding.model_copy(update={"release_history_sha256": "f" * 64})
    registry, calls = _five_provider_registry(inputs[2])

    with pytest.raises(
        ChongqingFederatedCompensationFiveProviderExecutionValidationError,
        match="active source-selection profile release",
    ):
        _execute_five_provider_inputs(inputs, registry)
    assert calls == []


def test_profile_release_authority_drift_stops_before_first_provider_callback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs = _five_provider_inputs(monkeypatch)
    live_history = build_initial_chongqing_source_selection_profile_release_history(
        inputs[5],
        tenant_id=inputs[4].tenant_id,
        change_reason="independently republished technical baseline",
    )
    profile_reader = _StaticProfileReleaseReader(
        inputs[6],
        returned_history=live_history,
    )
    registry, calls = _five_provider_registry(inputs[2])

    with pytest.raises(
        ChongqingFederatedCompensationFiveProviderExecutionValidationError,
        match="profile release binding differs from current authority history",
    ):
        _execute_five_provider_inputs(
            inputs,
            registry,
            profile_release_reader=profile_reader,
        )
    assert profile_reader.calls == 1
    assert calls == []


@pytest.mark.parametrize(
    ("reader_kwargs", "expected_calls"),
    (
        ({"return_none": True}, 1),
        ({"error": RuntimeError("release authority unavailable")}, 1),
        ({"tenant_id": "another-tenant"}, 0),
    ),
    ids=("not-found", "reader-outage", "cross-tenant-reader"),
)
def test_profile_release_authority_reader_failure_stops_before_provider_callbacks(
    monkeypatch: pytest.MonkeyPatch,
    reader_kwargs,
    expected_calls: int,
) -> None:
    inputs = _five_provider_inputs(monkeypatch)
    profile_reader = _StaticProfileReleaseReader(inputs[6], **reader_kwargs)
    registry, calls = _five_provider_registry(inputs[2])

    with pytest.raises(
        ChongqingFederatedCompensationFiveProviderExecutionValidationError,
        match="profile release authority live current read",
    ):
        _execute_five_provider_inputs(
            inputs,
            registry,
            profile_release_reader=profile_reader,
        )
    assert profile_reader.calls == expected_calls
    assert calls == []


def test_tampered_profile_release_authority_history_stops_before_provider_callbacks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs = _five_provider_inputs(monkeypatch)
    tampered_history = inputs[6].model_copy(update={"history_sha256": "f" * 64})
    profile_reader = _StaticProfileReleaseReader(
        inputs[6],
        returned_history=tampered_history,
    )
    registry, calls = _five_provider_registry(inputs[2])

    with pytest.raises(
        ChongqingFederatedCompensationFiveProviderExecutionValidationError,
        match="profile release authority current",
    ):
        _execute_five_provider_inputs(
            inputs,
            registry,
            profile_release_reader=profile_reader,
        )
    assert profile_reader.calls == 1
    assert calls == []


def test_customer_rule_current_version_drift_stops_before_first_provider_callback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs = _five_provider_inputs(monkeypatch)
    evidence, binding, _ = _rule_current_preflight(inputs[0])
    updated_evidence = _updated_rule_evidence(evidence)
    updated_reader = _StaticRuleAuthorityReader(updated_evidence)
    registry, calls = _five_provider_registry(inputs[2])

    with pytest.raises(
        ChongqingFederatedCompensationFiveProviderExecutionValidationError,
        match="customer-rule authority current",
    ):
        _execute_five_provider_inputs(
            inputs,
            registry,
            rule_authority_reader=updated_reader,
            customer_rule_current_binding=binding,
        )
    assert calls == []


def test_customer_signed_action_map_artifact_drift_stops_before_first_provider_callback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_rule_contract = approval_fixtures._rule_contract

    def mismatched_rule_contract(proposal, rule_id, status):
        contract = original_rule_contract(proposal, rule_id, status)
        if status is not CustomerCompensationRuleStatus.CUSTOMER_APPROVED:
            return contract
        approval = _build_approval_evidence(
            contract.rule,
            approval_artifact_sha256="f" * 64,
        )
        return build_customer_compensation_rule_contract(
            tenant_id=contract.tenant_id,
            rule=contract.rule,
            status=status,
            approval_evidence=approval,
        )

    monkeypatch.setattr(
        approval_fixtures,
        "_rule_contract",
        mismatched_rule_contract,
    )
    inputs = _five_provider_inputs(monkeypatch)
    _, binding, reader = _rule_current_preflight(inputs[0])
    registry, calls = _five_provider_registry(inputs[2])

    with pytest.raises(
        ChongqingFederatedCompensationFiveProviderExecutionValidationError,
        match="customer-approved Provider action mapping",
    ):
        _execute_five_provider_inputs(
            inputs,
            registry,
            rule_authority_reader=reader,
            customer_rule_current_binding=binding,
        )
    assert calls == []


def test_provider_action_drift_stops_before_first_provider_callback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs = _five_provider_inputs(monkeypatch)
    evidence, rule_binding, _ = _rule_current_preflight(inputs[0])
    rule_contract = next(
        contract
        for contract in evidence.current_rules
        if contract.rule.action is inputs[0].candidate_action
    )
    action_map = build_customer_compensation_rule_provider_action_map(
        evidence.proposal,
        inputs[0].candidate_sha256,
        rule_contract.rule,
    )
    request_bindings = tuple(
        CustomerCompensationRuleProviderRequestBindingInput(
            position=request.execution_plan.position,
            target_engine=engine,
            target_ref=request.execution_plan.source_plan.target_ref,
            provider_action=(
                "delete"
                if request.execution_plan.position == 0
                else request.execution_plan.source_plan.action
            ),
            request_sha256=request.request_sha256,
            execution_plan_sha256=request.execution_plan.execution_plan_sha256,
        )
        for engine, request in sorted(
            inputs[-2].items(),
            key=lambda item: item[1].execution_plan.position,
        )
    )
    _, calls = _five_provider_registry(inputs[2])

    with pytest.raises(
        CustomerCompensationRuleProviderActionMappingError,
        match="differs from a native request",
    ):
        build_customer_compensation_rule_provider_execution_binding(
            action_map,
            rule_contract,
            rule_binding,
            inputs[0],
            inputs[1],
            inputs[2],
            request_bindings,
            request_bundle_sha256=inputs[-1].request_bundle_sha256,
        )
    assert calls == []


def test_customer_rule_current_binding_tampering_stops_before_first_provider_callback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs = _five_provider_inputs(monkeypatch)
    evidence, binding, reader = _rule_current_preflight(inputs[0])
    tampered = binding.model_copy(
        update={"rule_authority_evidence_sha256": "f" * 64}
    )
    registry, calls = _five_provider_registry(inputs[2])

    with pytest.raises(
        ChongqingFederatedCompensationFiveProviderExecutionValidationError,
        match="customer-rule authority current",
    ):
        _execute_five_provider_inputs(
            inputs,
            registry,
            rule_authority_reader=reader,
            customer_rule_current_binding=tampered,
        )
    assert calls == []


def test_customer_rule_authority_live_read_failure_stops_before_first_provider_callback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs = _five_provider_inputs(monkeypatch)
    evidence, binding, _ = _rule_current_preflight(inputs[0])
    reader = _StaticRuleAuthorityReader(evidence, error=RuntimeError("authority outage"))
    registry, calls = _five_provider_registry(inputs[2])

    with pytest.raises(
        ChongqingFederatedCompensationFiveProviderExecutionValidationError,
        match="live current read",
    ):
        _execute_five_provider_inputs(
            inputs,
            registry,
            rule_authority_reader=reader,
            customer_rule_current_binding=binding,
        )
    assert reader.calls == 1
    assert calls == []


@pytest.mark.parametrize(
    ("reader_kwargs", "expected_calls"),
    (
        ({"return_none": True}, 1),
        ({"error": RuntimeError("admission authority unavailable")}, 1),
        ({"tenant_id": "another-tenant"}, 0),
    ),
    ids=("not-found", "reader-outage", "cross-tenant-reader"),
)
def test_production_admission_reader_failure_stops_before_provider_callbacks(
    monkeypatch: pytest.MonkeyPatch,
    reader_kwargs,
    expected_calls: int,
) -> None:
    inputs = _five_provider_inputs(monkeypatch)
    _, binding, _ = _rule_current_preflight(inputs[0])
    admission = _production_admission_history(inputs, binding)
    reader = _StaticProductionAdmissionReader(admission, **reader_kwargs)
    registry, calls = _five_provider_registry(inputs[2])

    with pytest.raises(
        ChongqingFederatedCompensationFiveProviderExecutionValidationError,
        match="production admission authority live current read",
    ):
        _execute_five_provider_inputs(
            inputs,
            registry,
            customer_rule_current_binding=binding,
            production_admission_history=admission,
            production_admission_reader=reader,
        )
    assert reader.calls == expected_calls
    assert calls == []


@pytest.mark.parametrize("state", ("revoked", "expired"))
def test_revoked_or_expired_production_admission_stops_before_provider_callbacks(
    monkeypatch: pytest.MonkeyPatch,
    state: str,
) -> None:
    inputs = _five_provider_inputs(monkeypatch)
    _, binding, _ = _rule_current_preflight(inputs[0])
    if state == "expired":
        admission = _production_admission_history(
            inputs,
            binding,
            expires_at=_PRODUCTION_ADMISSION_EVALUATED_AT,
        )
    else:
        initial = _production_admission_history(inputs, binding)
        admission = revoke_chongqing_five_provider_production_admission(
            initial,
            authorized_by="human:customer-production-controller",
            authorization_evidence_sha256="c" * 64,
            trust_anchor_sha256="b" * 64,
            authorization_reason="explicit production revocation",
            authorized_at=_PRODUCTION_ADMISSION_EVALUATED_AT,
        )
    reader = _StaticProductionAdmissionReader(admission)
    registry, calls = _five_provider_registry(inputs[2])

    with pytest.raises(
        ChongqingFederatedCompensationFiveProviderExecutionValidationError,
        match="production admission is not active and current",
    ):
        _execute_five_provider_inputs(
            inputs,
            registry,
            customer_rule_current_binding=binding,
            production_admission_history=admission,
            production_admission_reader=reader,
        )
    assert reader.calls == 1
    assert calls == []


def test_production_admission_lifecycle_drift_stops_before_provider_callbacks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs = _five_provider_inputs(monkeypatch)
    _, binding, _ = _rule_current_preflight(inputs[0])
    expected = _production_admission_history(inputs, binding)
    revoked = revoke_chongqing_five_provider_production_admission(
        expected,
        authorized_by="human:customer-production-controller",
        authorization_evidence_sha256="c" * 64,
        trust_anchor_sha256="b" * 64,
        authorization_reason="authority changed after request preparation",
        authorized_at=_PRODUCTION_ADMISSION_EVALUATED_AT,
    )
    reader = _StaticProductionAdmissionReader(expected, returned_history=revoked)
    registry, calls = _five_provider_registry(inputs[2])

    with pytest.raises(
        ChongqingFederatedCompensationFiveProviderExecutionValidationError,
        match="production admission differs from current authority history",
    ):
        _execute_five_provider_inputs(
            inputs,
            registry,
            customer_rule_current_binding=binding,
            production_admission_history=expected,
            production_admission_reader=reader,
        )
    assert reader.calls == 1
    assert calls == []


def test_production_admission_target_drift_stops_before_provider_callbacks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs = _five_provider_inputs(monkeypatch)
    _, binding, _ = _rule_current_preflight(inputs[0])
    drifted_target = build_chongqing_five_provider_production_admission_target(
        inputs[0],
        inputs[1],
        inputs[2],
        inputs[4],
        inputs[9],
        binding,
        request_bundle_sha256="f" * 64,
    )
    admission = build_initial_chongqing_five_provider_production_admission_history(
        drifted_target,
        authorized_by="human:customer-production-controller",
        authorization_evidence_sha256="a" * 64,
        trust_anchor_sha256="b" * 64,
        authorization_reason="admission for a different request bundle",
        authorized_at=_PRODUCTION_ADMISSION_EVALUATED_AT - timedelta(minutes=5),
        expires_at=_PRODUCTION_ADMISSION_EVALUATED_AT + timedelta(hours=1),
    )
    reader = _StaticProductionAdmissionReader(admission)
    registry, calls = _five_provider_registry(inputs[2])

    with pytest.raises(
        ChongqingFederatedCompensationFiveProviderExecutionValidationError,
        match="production admission target differs from current sealed execution",
    ):
        _execute_five_provider_inputs(
            inputs,
            registry,
            customer_rule_current_binding=binding,
            production_admission_history=admission,
            production_admission_reader=reader,
        )
    assert reader.calls == 1
    assert calls == []


def test_request_drift_stops_before_first_provider_callback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs = _five_provider_inputs(monkeypatch)
    requests = dict(inputs[-2])
    requests[ProjectionEngine.VECTOR] = requests[ProjectionEngine.VECTOR].model_copy(
        update={"request_sha256": "f" * 64}
    )
    registry, calls = _five_provider_registry(inputs[2])

    with pytest.raises(
        ChongqingFederatedCompensationFiveProviderExecutionValidationError,
        match="sealed contract",
    ):
        _execute_five_provider_inputs(inputs, registry, requests=requests)
    assert calls == []


def test_missing_engine_request_is_rejected_without_provider_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs = _five_provider_inputs(monkeypatch)
    requests = dict(inputs[-2])
    requests.pop(ProjectionEngine.LAKEHOUSE)
    registry, calls = _five_provider_registry(inputs[2])

    with pytest.raises(
        ChongqingFederatedCompensationFiveProviderExecutionValidationError,
        match="every engine exactly once",
    ):
        _execute_five_provider_inputs(inputs, registry, requests=requests)
    assert calls == []


@pytest.mark.skipif(
    not _real_dependencies_available(),
    reason="real PostgreSQL and pinned five-Provider images are unavailable",
)
def test_real_five_provider_chongqing_run_uses_one_sealed_request_bundle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = os.environ["DATABASE_URL"]
    postgis_database = _PostGISTemporaryPostgres(database_url)
    vector_database = _VectorTemporaryPostgres(database_url)
    fuseki = _TemporaryFuseki(_RDF_IMAGE)
    object_store = _TemporaryMinio(_OBJECT_IMAGE)
    lakehouse = _TemporaryLakehouse(_LAKEHOUSE_MINIO_IMAGE)
    object_started = False
    lakehouse_started = False
    object_bucket_removed = False
    lakehouse_bucket_removed = False
    object_cleanup = (False, False)
    lakehouse_cleanup = (False, False, False)
    fuseki_cleanup = (False, False)
    try:
        postgis_database.create()
        vector_database.create()
        fuseki.start()
        object_store.start()
        object_started = True
        lakehouse.start()
        lakehouse_started = True
        assert postgis_database.engine is not None
        assert vector_database.engine is not None
        assert fuseki.endpoint is not None
        assert fuseki.update_endpoint is not None
        assert object_store.endpoint is not None
        assert object_store.client is not None

        targets_and_rows = _normalized_targets(
            _postgis_target(),
            _vector_target(),
            _registered_target(
                _DEFAULT_PACKAGE,
                fuseki.endpoint,
                fuseki.update_endpoint,
            ),
            _object_target(
                _OBJECT_BUNDLE,
                object_store.endpoint,
                object_store.bucket,
            ),
            _lakehouse_target(_LAKEHOUSE_BUNDLE, lakehouse),
        )
        postgis, vector, rdf, object_target, lakehouse_target, _ = targets_and_rows
        inputs = _five_provider_inputs(monkeypatch, targets_and_rows)
        requests = inputs[-2]
        postgis_executor = PostGISProjectionRepairExecutor(
            postgis_database.engine,
            PostGISProjectionTargetRegistry((postgis,)),
        )
        vector_executor = VectorProjectionRepairExecutor(
            vector_database.engine,
            VectorProjectionTargetRegistry((vector,)),
        )
        rdf_executor = RDFProjectionRepairExecutor(
            RDFProjectionTargetRegistry((rdf,)),
            timeout_seconds=600,
        )
        object_executor = ObjectProjectionRepairExecutor(
            ObjectProjectionTargetRegistry((object_target,)),
            client=object_store.client,
            timeout_seconds=600,
        )
        lakehouse_provider = DockerSparkIcebergProjectionProvider(
            repository_root=Path(__file__).resolve().parents[1],
            image=_LAKEHOUSE_SPARK_IMAGE,
            docker_network=lakehouse.network,
            access_key_id=lakehouse.access_key,
            secret_access_key=lakehouse.secret_key,
            java_home="/usr/lib/jvm/java-17-openjdk-arm64",
            timeout_seconds=900,
        )
        lakehouse_executor = LakehouseProjectionRepairExecutor(
            LakehouseProjectionTargetRegistry((lakehouse_target,)),
            provider=lakehouse_provider,
        )
        registry = build_federated_compensation_provider_native_invoker_registry(
            postgis_request=requests[ProjectionEngine.POSTGIS],
            postgis_executor=postgis_executor,
            vector_request=requests[ProjectionEngine.VECTOR],
            vector_executor=vector_executor,
            rdf_request=requests[ProjectionEngine.RDF],
            rdf_executor=rdf_executor,
            object_request=requests[ProjectionEngine.OBJECT_STORE],
            object_executor=object_executor,
            lakehouse_request=requests[ProjectionEngine.LAKEHOUSE],
            lakehouse_executor=lakehouse_executor,
        )

        result = _execute_five_provider_inputs(
            inputs,
            registry,
            requests=requests,
        )

        deployment_execution = (
            result.profiled_execution.source_lineage_execution.deployment_execution
        )
        registered = deployment_execution.registered_execution
        assert registered.state is (
            FederatedCompensationRegisteredReceiptExecutionState.COMPLETED_RECEIPT_SET_PENDING_AUTHORITY
        )
        assert registered.receipt_validation_set is not None
        assert registered.receipt_validation_set.receipt_count == 5
        assert registered.receipt_validation_set.provider_receipts_complete is True
        assert result.request_bundle_sha256 == inputs[-1].request_bundle_sha256
        assert result.authority_admission_performed is False
        assert result.checkpoint_authority_write_performed is False
        assert result.compensation_completion_recorded is False
    finally:
        if object_started:
            try:
                object_bucket_removed = object_store.delete_bucket_and_verify()
            finally:
                object_cleanup = object_store.stop_and_verify()
        if lakehouse_started:
            try:
                lakehouse_bucket_removed = lakehouse.delete_bucket_and_verify()
            finally:
                lakehouse_cleanup = lakehouse.stop_and_verify()
        fuseki_cleanup = fuseki.stop_and_verify()
        vector_database.drop()
        postgis_database.drop()
    assert object_bucket_removed
    assert lakehouse_bucket_removed
    assert object_cleanup == (True, True)
    assert lakehouse_cleanup == (True, True, True)
    assert fuseki_cleanup == (True, True)
