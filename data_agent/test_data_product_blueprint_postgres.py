import asyncio
import hashlib
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from botocore.config import Config as BotoConfig
from shapely.geometry import box
from sqlalchemy import create_engine, text

from data_agent.api import platform_gateway_routes as platform_routes
from data_agent.approval_case_authority import (
    ApprovalCaseAuthority,
    ApprovalCaseConflictError,
)
from data_agent.data_architecture_ledger import (
    DataArchitectureRegistration,
    DataContractVersion,
    PhysicalLocation,
    ResourceVersionArchitectureBinding,
    SchemaVersion,
    architecture_binding_fingerprint,
    data_contract_version_fingerprint,
    physical_location_fingerprint,
    schema_version_fingerprint,
)
from data_agent.data_product_blueprint import (
    DataProductBlueprint,
    DataProductBlueprintProviderCancellationTimeoutRequest,
    DataProductBlueprintProviderReconcileRequest,
    DataProductBlueprintProviderRetryRequest,
    DataProductBlueprintTestCancellationRequest,
    DataProductBlueprintTestExecutionFailureRequest,
    DataProductBlueprintTestExecutionRequest,
    DataProductBlueprintTestRunRequest,
    build_data_product_blueprint_approval_case,
    build_data_product_blueprint_preview,
    build_data_product_blueprint_release_binding,
    compile_data_product_blueprint,
    data_product_blueprint_fingerprint,
    data_product_blueprint_provider_cancellation_timeout_fingerprint,
    data_product_blueprint_provider_reconcile_fingerprint,
    data_product_blueprint_provider_retry_fingerprint,
)
from data_agent.data_product_registry import (
    DataProductConflictError,
    DataProductRegistry,
    DataProductSpec,
    DataProductVersionSpec,
    data_product_manifest_fingerprint,
)
from data_agent.duckdb_blueprint_command_consumer import (
    DuckDBBlueprintCommandConsumer,
)
from data_agent.duckdb_blueprint_object_store import (
    S3DuckDBBlueprintObjectStore,
)
from data_agent.duckdb_blueprint_provider import (
    DUCKDB_BLUEPRINT_WORKLOAD,
    DuckDBBlueprintExecutionRequest,
    DuckDBBlueprintProvider,
)
from data_agent.platform_contracts import (
    ApprovalCaseStatus,
    Artifact,
    ArtifactRole,
    FrameworkAttemptObservation,
    FrameworkKind,
    Resource,
    ResourceBinding,
    ResourceVersion,
    SubjectContext,
    SubjectType,
    canonical_json_fingerprint,
)
from data_agent.platform_gateway import (
    GatewayConflictError,
    GatewayForbiddenError,
    GatewayValidationError,
    PlatformGateway,
)

DATABASE_URL = os.environ.get("DATABASE_URL")
S3_ACCEPTANCE_ENDPOINT = os.environ.get("GDA_BLUEPRINT_ACCEPTANCE_S3_ENDPOINT")
MIGRATIONS = tuple(
    Path(__file__).resolve().parent / "migrations" / filename
    for filename in (
        "092_platform_control_ledger.sql",
        "093_app_user_tenant_context.sql",
        "094_platform_control_gateway.sql",
        "095_platform_command_outbox.sql",
        "096_platform_success_verdict.sql",
        "098_platform_data_incident.sql",
        "123_resource_bound_data_incident.sql",
        "100_data_product_registry.sql",
        "101_data_product_promotion.sql",
        "102_source_schema_drift_ledger.sql",
        "103_unified_approval_case_authority.sql",
        "105_asset_distribution_grant.sql",
        "106_version_locked_distribution_grant.sql",
        "107_distribution_grant_package_quota.sql",
        "108_data_product_promotion_impact.sql",
        "113_data_architecture_version_authority.sql",
        "197_blueprint_test_execution_success.sql",
        "198_blueprint_provider_retry_command.sql",
        "199_blueprint_duckdb_provider_success.sql",
        "200_blueprint_duckdb_execute_command.sql",
        "201_blueprint_duckdb_object_storage_evidence.sql",
        "202_blueprint_duckdb_spatial_receipt_evidence.sql",
    )
)


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _duckdb_architecture(
    *,
    tenant_id: str,
    resource_version_id: UUID,
    source_path: Path,
    content_sha256: str,
    created_at: datetime,
    provider_system: str = "duckdb",
    provider_locator: str | None = None,
    revision_ref: str | None = None,
) -> DataArchitectureRegistration:
    schema_values = {
        "tenant_id": tenant_id,
        "resource_version_id": resource_version_id,
        "schema_format": "parquet",
        "authority_system": "provider",
        "authority_namespace": "blueprint-duckdb-conformance",
        "authority_object_id": source_path.name,
        "authority_version_ref": content_sha256,
    }
    schema = SchemaVersion(
        schema_version_id=uuid4(),
        schema_sha256=schema_version_fingerprint(**schema_values),
        created_by="workload:metadata-harvester",
        created_at=created_at,
        **schema_values,
    )
    contract_values = {
        "tenant_id": tenant_id,
        "resource_version_id": resource_version_id,
        "contract_kind": "data_product_input",
        "enforcement_mode": "required",
        "authority_system": "provider",
        "authority_namespace": "blueprint-duckdb-conformance",
        "authority_object_id": source_path.name,
        "authority_version_ref": content_sha256,
    }
    contract = DataContractVersion(
        data_contract_version_id=uuid4(),
        contract_sha256=data_contract_version_fingerprint(**contract_values),
        created_by="workload:governance-harvester",
        created_at=created_at,
        **contract_values,
    )
    location_values = {
        "tenant_id": tenant_id,
        "resource_version_id": resource_version_id,
        "location_kind": "parquet",
        "provider_system": provider_system,
        "provider_namespace": f"blueprint-{provider_system}-conformance",
        "provider_locator": provider_locator or source_path.as_uri(),
        "snapshot_ref": content_sha256,
        "revision_ref": revision_ref,
        "checksum_algorithm": "sha256",
        "content_checksum": content_sha256,
    }
    location = PhysicalLocation(
        physical_location_id=uuid4(),
        location_sha256=physical_location_fingerprint(**location_values),
        created_by="workload:provider-harvester",
        created_at=created_at,
        **location_values,
    )
    binding_values = {
        "tenant_id": tenant_id,
        "resource_version_id": resource_version_id,
        "schema_version_id": schema.schema_version_id,
        "data_contract_version_id": contract.data_contract_version_id,
        "physical_location_id": location.physical_location_id,
    }
    binding = ResourceVersionArchitectureBinding(
        binding_sha256=architecture_binding_fingerprint(**binding_values),
        bound_by="workload:architecture-controller",
        bound_at=created_at,
        **binding_values,
    )
    return DataArchitectureRegistration(
        schema_version=schema,
        data_contract_version=contract,
        physical_location=location,
        binding=binding,
    )


@pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL is not configured")
def test_blueprint_registers_idempotently_in_existing_postgres_authority(
    isolated_postgres_url: str,
    tmp_path: Path,
):
    engine = create_engine(isolated_postgres_url)
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "DO $$ BEGIN "
                "IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'agent_user') "
                "THEN CREATE ROLE agent_user NOLOGIN; END IF; "
                "END $$"
            )
            connection.exec_driver_sql(
                """
                CREATE TABLE agent_app_users (
                    id SERIAL PRIMARY KEY,
                    username VARCHAR(100) UNIQUE NOT NULL
                )
                """
            )
            connection.exec_driver_sql(
                """
                CREATE TABLE agent_data_assets (
                    id SERIAL PRIMARY KEY,
                    asset_name TEXT NOT NULL,
                    operational_metadata JSONB NOT NULL DEFAULT '{}'::jsonb
                )
                """
            )
            connection.exec_driver_sql(
                """
                CREATE TABLE agent_data_requests (
                    id SERIAL PRIMARY KEY,
                    asset_id INTEGER NOT NULL REFERENCES agent_data_assets(id),
                    requester VARCHAR(100) NOT NULL,
                    status VARCHAR(30) NOT NULL DEFAULT 'pending',
                    approver VARCHAR(100),
                    approved_at TIMESTAMP,
                    created_at TIMESTAMP NOT NULL DEFAULT NOW()
                )
                """
            )
            for migration in MIGRATIONS:
                connection.execute(text(migration.read_text(encoding="utf-8")))

        payload = {
            "tenant_id": "planning",
            "definition_urn": "gda://planning/definition/districts-build",
            "definition_version_id": UUID(
                "00000000-0000-4000-8000-000000000731"
            ),
            "version_key": "v1.0.0",
            "product_urn": "gda://planning/data_product/districts",
            "domain": "planning",
            "owner_ref": "team:geo-platform",
            "source_refs": ("gda://planning/dataset/district-source",),
            "storage_placement": {
                "profile": "default",
                "table_format": "iceberg",
            },
            "model_contract": {"schema": "districts.v1", "geometry": "polygon"},
            "quality_contract": {
                "verdict": "passed",
                "rules": ["geometry_valid"],
            },
            "security_policy": {
                "classification": "internal",
                "row_filter": "tenant",
            },
            "slo_contract": {"freshness_minutes": 60},
            "pipeline": {"engine": "spark", "mode": "batch"},
            "projections": ({"kind": "postgis", "name": "districts"},),
            "retention_policy": {"days": 365},
            "cost_policy": {"budget_class": "standard"},
            "created_by": "human:planner",
            "created_at": datetime(2026, 8, 20, tzinfo=UTC),
        }
        payload["blueprint_sha256"] = data_product_blueprint_fingerprint(payload)
        blueprint = DataProductBlueprint.model_validate(payload)
        registration = compile_data_product_blueprint(blueprint)

        gateway = PlatformGateway(
            engine,
            blueprint_duckdb_output_root=tmp_path / "duckdb-outputs",
        )
        assert gateway.register_definition(registration).created is True
        assert gateway.register_definition(registration).created is False

        with engine.connect() as connection:
            counts = connection.execute(
                text(
                    """
                    SELECT
                        (SELECT count(*) FROM gda_control.resource
                         WHERE tenant_id = :tenant_id AND resource_urn = :definition_urn),
                        (SELECT count(*) FROM gda_control.resource_version
                         WHERE tenant_id = :tenant_id
                           AND resource_version_id = :definition_version_id),
                        (SELECT count(*) FROM gda_control.platform_definition_version
                         WHERE tenant_id = :tenant_id
                           AND definition_version_id = :definition_version_id)
                    """
                ),
                {
                    "tenant_id": blueprint.tenant_id,
                    "definition_urn": blueprint.definition_urn,
                    "definition_version_id": blueprint.definition_version_id,
                },
            ).one()
            stored = connection.execute(
                text(
                    """
                    SELECT definition_document ->> 'blueprint_sha256',
                           definition_sha256
                    FROM gda_control.platform_definition_version
                    WHERE tenant_id = :tenant_id
                      AND definition_version_id = :definition_version_id
                    """
                ),
                {
                    "tenant_id": blueprint.tenant_id,
                    "definition_version_id": blueprint.definition_version_id,
                },
            ).one()

        assert counts == (1, 1, 1)
        assert stored == (
            blueprint.blueprint_sha256,
            registration.definition.definition_sha256,
        )

        successor_payload = {
            **payload,
            "definition_version_id": UUID(
                "00000000-0000-4000-8000-000000000732"
            ),
            "predecessor_definition_version_id": blueprint.definition_version_id,
            "version_key": "v1.1.0",
            "model_contract": {
                "schema": "districts.v2",
                "geometry": "multipolygon",
            },
        }
        successor_payload["blueprint_sha256"] = data_product_blueprint_fingerprint(
            successor_payload
        )
        successor = DataProductBlueprint.model_validate(successor_payload)
        predecessor = gateway.get_definition(
            blueprint.tenant_id,
            blueprint.definition_version_id,
        )
        preview = build_data_product_blueprint_preview(
            successor,
            predecessor=predecessor,
        )
        assert preview.compile_verdict == "passed"
        approval_requested_at = datetime.now(UTC)
        approval_case = build_data_product_blueprint_approval_case(
            preview,
            requester_subject="human:planner",
            request_reason="review model contract successor",
            requested_at=approval_requested_at,
            expires_at=approval_requested_at + timedelta(days=2),
        )
        approval_authority = ApprovalCaseAuthority(engine)
        assert approval_authority.create(
            approval_case,
            owner_ref="team:data-platform",
        ).created is True
        assert approval_authority.create(
            approval_case,
            owner_ref="team:data-platform",
        ).created is False
        stored_case = approval_authority.get(
            approval_case.tenant_id,
            approval_case.approval_case_ref,
        )
        assert stored_case.target_fingerprint == preview.change_set_sha256
        assert stored_case.request_context == preview.approval_context()
        approval_events = approval_authority.events(
            approval_case.tenant_id,
            approval_case.approval_case_ref,
        )
        assert len(approval_events) == 1
        assert approval_events[0].to_status.value == "pending"

        assert gateway.register_definition(
            compile_data_product_blueprint(successor)
        ).created is True
        assert gateway.register_definition(
            compile_data_product_blueprint(successor)
        ).created is False
        release = build_data_product_blueprint_release_binding(
            preview,
            approval_case_ref=approval_case.approval_case_ref,
        )

        def release_version(binding):
            version_payload = {
                "tenant_id": successor.tenant_id,
                "data_product_version_id": uuid4(),
                "product_urn": successor.product_urn,
                "version_key": successor.version_key,
                "predecessor_version_id": None,
                "source_resource_version_id": uuid4(),
                "output_resource_version_id": uuid4(),
                "standard_version_ref": "standard:district:v1",
                "mapping_contract": {"mapping": {"source": "district"}},
                "quality_contract": {"verdict": "passed", "checks": []},
                "quality_evidence_artifact_id": uuid4(),
                "distribution_manifest": {
                    "formats": [],
                    "blueprint_release": binding.model_dump(mode="json"),
                },
                "published_by": "workload:data-product-controller",
                "published_at": approval_requested_at + timedelta(minutes=5),
            }
            version_payload["manifest_sha256"] = data_product_manifest_fingerprint(
                version_payload
            )
            return DataProductVersionSpec.model_validate(version_payload)

        registry = DataProductRegistry(engine)
        version = release_version(release)
        with (
            registry._transaction(successor.tenant_id) as connection,
            pytest.raises(DataProductConflictError, match="not an approved exact"),
        ):
            registry._validate_live_blueprint_release(
                connection,
                version=version,
                binding=release,
            )

        changed_payload = {
            **successor_payload,
            "cost_policy": {"budget_class": "high-throughput"},
        }
        changed_payload["blueprint_sha256"] = data_product_blueprint_fingerprint(
            changed_payload
        )
        changed_successor = DataProductBlueprint.model_validate(changed_payload)
        changed_preview = build_data_product_blueprint_preview(
            changed_successor,
            predecessor=predecessor,
        )
        conflicting_case = build_data_product_blueprint_approval_case(
            changed_preview,
            requester_subject="human:planner",
            request_reason="review model contract successor",
            requested_at=approval_requested_at,
            expires_at=approval_requested_at + timedelta(days=2),
        )
        with pytest.raises(ApprovalCaseConflictError):
            approval_authority.create(
                conflicting_case,
                owner_ref="team:data-platform",
            )

        approved = approval_authority.decide(
            tenant_id=approval_case.tenant_id,
            approval_case_ref=approval_case.approval_case_ref,
            expected_state_version=0,
            verdict=ApprovalCaseStatus.APPROVED,
            actor_subject="human:reviewer",
            reason="compiled changes and evidence accepted",
            details={"change_set_sha256": preview.change_set_sha256},
        )
        assert approved.status is ApprovalCaseStatus.APPROVED
        assert approved.target_fingerprint == preview.change_set_sha256
        approval_events = approval_authority.events(
            approval_case.tenant_id,
            approval_case.approval_case_ref,
        )
        assert [event.to_status.value for event in approval_events] == [
            "pending",
            "approved",
        ]

        with registry._transaction(successor.tenant_id) as connection:
            assert registry._validate_live_blueprint_release(
                connection,
                version=version,
                binding=release,
            ) == release
            assert registry._validate_live_blueprint_release(
                connection,
                version=version,
                binding=release,
            ) == release

        tampered_release = release.model_copy(
            update={"change_set_sha256": "d" * 64}
        )
        with (
            registry._transaction(successor.tenant_id) as connection,
            pytest.raises(DataProductConflictError, match="not an approved exact"),
        ):
            registry._validate_live_blueprint_release(
                connection,
                version=release_version(tampered_release),
                binding=tampered_release,
            )

        with (
            registry._transaction(successor.tenant_id) as connection,
            pytest.raises(DataProductConflictError, match="not an approved exact"),
        ):
            registry._validate_live_blueprint_release(
                connection,
                version=version,
                binding=release,
                evaluated_at=approved.expires_at,
            )

        rejected_case = approval_case.model_copy(
            update={
                "approval_case_ref": (
                    "gda://planning/approval_case/"
                    "data-product-blueprint-rejected-0000000000000732"
                )
            }
        )
        approval_authority.create(
            rejected_case,
            owner_ref="team:data-platform",
        )
        approval_authority.decide(
            tenant_id=rejected_case.tenant_id,
            approval_case_ref=rejected_case.approval_case_ref,
            expected_state_version=0,
            verdict=ApprovalCaseStatus.REJECTED,
            actor_subject="human:reviewer",
            reason="compiled changes rejected for release",
        )
        rejected_release = release.model_copy(
            update={"approval_case_ref": rejected_case.approval_case_ref}
        )
        with (
            registry._transaction(successor.tenant_id) as connection,
            pytest.raises(DataProductConflictError, match="not an approved exact"),
        ):
            registry._validate_live_blueprint_release(
                connection,
                version=release_version(rejected_release),
                binding=rejected_release,
            )

        source_urn = "gda://planning/dataset/district-source-version"
        output_urn = "gda://planning/dataset/district-product-version"
        for resource_urn, locator in (
            (source_urn, "source/districts"),
            (output_urn, "product/districts-v1.1.0"),
        ):
            gateway.register_resource(
                Resource(
                    tenant_id=successor.tenant_id,
                    resource_urn=resource_urn,
                    resource_kind="dataset",
                    authority_system="blueprint-release-test",
                    authority_locator=locator,
                    owner_ref=successor.owner_ref,
                )
            )
        gateway.register_resource_version(
            ResourceVersion(
                tenant_id=successor.tenant_id,
                resource_urn=source_urn,
                resource_version_id=version.source_resource_version_id,
                version_key="snapshot-1",
                content_sha256="4" * 64,
                authority_version_ref={"snapshot_ref": "source-1"},
                created_by=version.published_by,
                created_at=version.published_at,
            )
        )
        gateway.register_resource_version(
            ResourceVersion(
                tenant_id=successor.tenant_id,
                resource_urn=output_urn,
                resource_version_id=version.output_resource_version_id,
                version_key="snapshot-1",
                content_sha256="5" * 64,
                authority_version_ref={"snapshot_ref": "output-1"},
                created_by=version.published_by,
                created_at=version.published_at,
            )
        )
        test_source_version_id = uuid4()
        gateway.register_resource(
            Resource(
                tenant_id=successor.tenant_id,
                resource_urn=successor.source_refs[0],
                resource_kind="dataset",
                authority_system="blueprint-test-admission",
                authority_locator="source/districts-input",
                owner_ref=successor.owner_ref,
            )
        )
        gateway.register_resource_version(
            ResourceVersion(
                tenant_id=successor.tenant_id,
                resource_urn=successor.source_refs[0],
                resource_version_id=test_source_version_id,
                version_key="snapshot-test-1",
                content_sha256="7" * 64,
                authority_version_ref={"snapshot_ref": "source-test-1"},
                created_by=version.published_by,
                created_at=version.published_at,
            )
        )
        test_request = DataProductBlueprintTestRunRequest(
            blueprint=successor,
            run_id=uuid4(),
            idempotency_key="districts-blueprint-test-1",
            input_bindings=(
                ResourceBinding(
                    binding_name="source",
                    resource_version_id=test_source_version_id,
                    semantic_type="source.dataset",
                ),
            ),
        )
        test_subject = SubjectContext(
            tenant_id=successor.tenant_id,
            subject_id="blueprint-test-executor",
            subject_type=SubjectType.WORKLOAD,
            roles=("platform_operator",),
            purpose="blueprint-test-admission",
        )
        admitted = gateway.admit_blueprint_test_run(
            test_request,
            subject_context=test_subject,
        )
        replayed_admission = gateway.admit_blueprint_test_run(
            test_request,
            subject_context=test_subject,
        )
        assert admitted.created is True
        assert replayed_admission.created is False
        assert admitted.value.run.status.value == "accepted"
        assert admitted.value.execution_plan.manifest["execution_mode"] == "admission_only"
        assert (
            admitted.value.execution_plan.manifest["test_report_sha256"]
            == admitted.value.test_report.test_report_sha256
        )
        failure_admission_request = DataProductBlueprintTestRunRequest(
            blueprint=successor,
            run_id=uuid4(),
            idempotency_key="districts-blueprint-test-failure-1",
            input_bindings=(
                ResourceBinding(
                    binding_name="source",
                    resource_version_id=test_source_version_id,
                    semantic_type="source.dataset",
                ),
            ),
        )
        failure_admission = gateway.admit_blueprint_test_run(
            failure_admission_request,
            subject_context=test_subject,
        )
        failed = gateway.fail_blueprint_test_run(
            successor.tenant_id,
            DataProductBlueprintTestExecutionFailureRequest(
                run_id=failure_admission.value.run.run_id,
                error_code="provider_timeout",
                reason="deterministic provider timeout",
            ),
            actor_subject="workload:blueprint-test-executor",
        )
        replayed_failure = gateway.fail_blueprint_test_run(
            successor.tenant_id,
            DataProductBlueprintTestExecutionFailureRequest(
                run_id=failure_admission.value.run.run_id,
                error_code="provider_timeout",
                reason="deterministic provider timeout",
            ),
            actor_subject="workload:blueprint-test-executor",
        )
        assert failed.created is True
        assert failed.value.status.value == "failed"
        assert replayed_failure.created is False
        assert replayed_failure.value == failed.value
        cancellation_admission_request = DataProductBlueprintTestRunRequest(
            blueprint=successor,
            run_id=uuid4(),
            idempotency_key="districts-blueprint-test-cancel-1",
            input_bindings=(
                ResourceBinding(
                    binding_name="source",
                    resource_version_id=test_source_version_id,
                    semantic_type="source.dataset",
                ),
            ),
        )
        cancellation_admission = gateway.admit_blueprint_test_run(
            cancellation_admission_request,
            subject_context=test_subject,
        )
        cancellation_run = cancellation_admission.value.run
        for next_status in ("dispatching", "running", "cancelling"):
            cancellation_run = gateway.transition_run(
                successor.tenant_id,
                cancellation_run.run_id,
                cancellation_run.state_version,
                next_status,
                "workload:blueprint-test-executor",
                f"prepare cancellation state {next_status}",
                {"schema": "gda.blueprint_test_cancellation_setup.v1"},
            )
        cancelled = gateway.complete_blueprint_test_run_cancellation(
            successor.tenant_id,
            DataProductBlueprintTestCancellationRequest(
                run_id=cancellation_run.run_id,
                external_cancel_ref="cancel-provider-1",
                reason="governed cancellation converged",
            ),
            actor_subject="workload:blueprint-test-executor",
        )
        replayed_cancel = gateway.complete_blueprint_test_run_cancellation(
            successor.tenant_id,
            DataProductBlueprintTestCancellationRequest(
                run_id=cancellation_run.run_id,
                external_cancel_ref="cancel-provider-1",
                reason="governed cancellation converged",
            ),
            actor_subject="workload:blueprint-test-executor",
        )
        assert cancelled.created is True
        assert cancelled.value.status.value == "cancelled"
        assert replayed_cancel.created is False
        assert replayed_cancel.value == cancelled.value

        for index, provider_state in enumerate(("running", "failed", "cancelled"), start=1):
            provider_admission = gateway.admit_blueprint_test_run(
                DataProductBlueprintTestRunRequest(
                    blueprint=successor,
                    run_id=uuid4(),
                    idempotency_key=f"districts-blueprint-provider-{provider_state}-1",
                    input_bindings=(
                        ResourceBinding(
                            binding_name="source",
                            resource_version_id=test_source_version_id,
                            semantic_type="source.dataset",
                        ),
                    ),
                ),
                subject_context=test_subject,
            )
            provider_run = provider_admission.value.run
            for next_status in ("dispatching", "reconciling"):
                provider_run = gateway.transition_run(
                    successor.tenant_id,
                    provider_run.run_id,
                    provider_run.state_version,
                    next_status,
                    "workload:blueprint-test-executor",
                    f"prepare provider reconciliation state {next_status}",
                    {"schema": "gda.blueprint_provider_reconcile_setup.v1"},
                )
            observed_at = successor.created_at + timedelta(minutes=index)
            observation_id = uuid4()
            plan_id = provider_admission.value.execution_plan.artifact_id
            provider_evidence = {
                "schema": "gda.data_product_blueprint_provider_observation.v1",
                "execution_plan_artifact_id": str(plan_id),
                "provider_state": provider_state,
                "observation_id": str(observation_id),
                "attempt_no": 1,
                "framework_kind": "spark",
                "external_namespace": "spark-blueprint-tests",
                "external_run_id": f"spark-app-{index}",
                "external_attempt_id": "attempt-1",
                "observed_at": observed_at.isoformat().replace("+00:00", "Z"),
                "provider_receipt": {"application_state": provider_state},
            }
            observation = FrameworkAttemptObservation(
                tenant_id=successor.tenant_id,
                observation_id=observation_id,
                run_id=provider_run.run_id,
                attempt_no=1,
                framework_kind=FrameworkKind.SPARK,
                external_namespace="spark-blueprint-tests",
                external_run_id=f"spark-app-{index}",
                external_attempt_id="attempt-1",
                observed_state=provider_state,
                observation_sha256=canonical_json_fingerprint(provider_evidence),
                evidence=provider_evidence,
                observed_at=observed_at,
            )
            receipt_values = {
                "tenant_id": successor.tenant_id,
                "run_id": provider_run.run_id,
                "execution_plan_artifact_id": plan_id,
                "provider_state": provider_state,
                "attempt_observation": observation,
                "reason": f"Spark provider reports {provider_state}",
            }
            receipt = DataProductBlueprintProviderReconcileRequest(
                **receipt_values,
                reconcile_receipt_sha256=(
                    data_product_blueprint_provider_reconcile_fingerprint(
                        receipt_values
                    )
                ),
            )
            if provider_state == "running":
                with pytest.raises(GatewayForbiddenError, match="does not match"):
                    gateway.reconcile_blueprint_test_provider(
                        receipt,
                        actor_subject="workload:other-provider",
                    )
            reconciled = gateway.reconcile_blueprint_test_provider(
                receipt,
                actor_subject="workload:blueprint-test-executor",
            )
            replayed_reconcile = gateway.reconcile_blueprint_test_provider(
                receipt,
                actor_subject="workload:blueprint-test-executor",
            )
            assert reconciled.created is True
            assert reconciled.value.run.status.value == provider_state
            assert reconciled.value.converged_status.value == provider_state
            assert reconciled.value.observation_created is True
            assert reconciled.value.transitioned is True
            assert replayed_reconcile.created is False
            assert replayed_reconcile.value.observation_created is False
            assert replayed_reconcile.value.transitioned is False
            assert replayed_reconcile.value.reconcile_receipt_sha256 == (
                receipt.reconcile_receipt_sha256
            )

        retry_admission = gateway.admit_blueprint_test_run(
            DataProductBlueprintTestRunRequest(
                blueprint=successor,
                run_id=uuid4(),
                idempotency_key="districts-blueprint-provider-retry-1",
                input_bindings=(
                    ResourceBinding(
                        binding_name="source",
                        resource_version_id=test_source_version_id,
                        semantic_type="source.dataset",
                    ),
                ),
            ),
            subject_context=test_subject,
        )
        retry_run = retry_admission.value.run
        for next_status in ("dispatching", "reconciling"):
            retry_run = gateway.transition_run(
                successor.tenant_id,
                retry_run.run_id,
                retry_run.state_version,
                next_status,
                "workload:blueprint-test-executor",
                f"prepare provider retry state {next_status}",
                {"schema": "gda.blueprint_provider_retry_setup.v1"},
            )
        retry_plan_id = retry_admission.value.execution_plan.artifact_id
        retry_observed_at = datetime.now(UTC) + timedelta(minutes=1)
        retry_observation_id = uuid4()
        retry_evidence = {
            "schema": "gda.data_product_blueprint_provider_retry.v1",
            "execution_plan_artifact_id": str(retry_plan_id),
            "provider_state": "failed",
            "observation_id": str(retry_observation_id),
            "attempt_no": 1,
            "framework_kind": "spark",
            "external_namespace": "spark-blueprint-tests",
            "external_run_id": "spark-app-retry",
            "external_attempt_id": "attempt-1",
            "observed_at": retry_observed_at.isoformat().replace("+00:00", "Z"),
            "retry_attempt": 1,
            "max_retry_attempts": 3,
            "provider_receipt": {"application_state": "FAILED", "retryable": True},
        }
        retry_observation = FrameworkAttemptObservation(
            tenant_id=successor.tenant_id,
            observation_id=retry_observation_id,
            run_id=retry_run.run_id,
            attempt_no=1,
            framework_kind=FrameworkKind.SPARK,
            external_namespace="spark-blueprint-tests",
            external_run_id="spark-app-retry",
            external_attempt_id="attempt-1",
            observed_state="failed",
            observation_sha256=canonical_json_fingerprint(retry_evidence),
            evidence=retry_evidence,
            observed_at=retry_observed_at,
        )
        retry_values = {
            "tenant_id": successor.tenant_id,
            "run_id": retry_run.run_id,
            "execution_plan_artifact_id": retry_plan_id,
            "provider_state": "failed",
            "retry_attempt": 1,
            "max_retry_attempts": 3,
            "attempt_observation": retry_observation,
            "reason": "transient provider failure; retry with bounded backoff",
        }
        retry_receipt = DataProductBlueprintProviderRetryRequest(
            **retry_values,
            retry_receipt_sha256=data_product_blueprint_provider_retry_fingerprint(
                retry_values
            ),
        )
        with pytest.raises(GatewayForbiddenError, match="does not match"):
            gateway.retry_blueprint_test_provider(
                retry_receipt,
                actor_subject="workload:other-provider",
            )
        retried = gateway.retry_blueprint_test_provider(
            retry_receipt,
            actor_subject="workload:blueprint-test-executor",
        )
        replayed_retry = gateway.retry_blueprint_test_provider(
            retry_receipt,
            actor_subject="workload:blueprint-test-executor",
        )
        assert retried.created is True
        assert retried.value.run.status.value == "dispatching"
        assert retried.value.backoff_seconds == 5
        assert retried.value.retry_after == retry_observed_at + timedelta(seconds=5)
        assert retried.value.retry_command.available_at == retried.value.retry_after
        assert retried.value.retry_command.status.value == "pending"
        assert retried.value.retry_command.max_attempts == 1
        assert retried.value.command_created is True
        assert retried.value.transitioned is True
        assert replayed_retry.created is False
        assert replayed_retry.value == retried.value.model_copy(
            update={
                "observation_created": False,
                "command_created": False,
                "transitioned": False,
            }
        )

        retry_run = gateway.transition_run(
            successor.tenant_id,
            retry_run.run_id,
            retried.value.run.state_version,
            "reconciling",
            "workload:blueprint-test-executor",
            "provider retry attempt 2 started",
            {"schema": "gda.blueprint_provider_retry_setup.v1"},
        )
        retry2_observed_at = datetime.now(UTC) + timedelta(minutes=2)
        retry2_observation_id = uuid4()
        retry2_evidence = {
            **retry_evidence,
            "observation_id": str(retry2_observation_id),
            "attempt_no": 2,
            "external_attempt_id": "attempt-2",
            "observed_at": retry2_observed_at.isoformat().replace("+00:00", "Z"),
            "retry_attempt": 2,
        }
        retry2_observation = FrameworkAttemptObservation(
            tenant_id=successor.tenant_id,
            observation_id=retry2_observation_id,
            run_id=retry_run.run_id,
            attempt_no=2,
            framework_kind=FrameworkKind.SPARK,
            external_namespace="spark-blueprint-tests",
            external_run_id="spark-app-retry",
            external_attempt_id="attempt-2",
            observed_state="failed",
            observation_sha256=canonical_json_fingerprint(retry2_evidence),
            evidence=retry2_evidence,
            observed_at=retry2_observed_at,
        )
        retry2_values = {
            **retry_values,
            "retry_attempt": 2,
            "attempt_observation": retry2_observation,
        }
        retry2_receipt = DataProductBlueprintProviderRetryRequest(
            **retry2_values,
            retry_receipt_sha256=data_product_blueprint_provider_retry_fingerprint(
                retry2_values
            ),
        )
        retried2 = gateway.retry_blueprint_test_provider(
            retry2_receipt,
            actor_subject="workload:blueprint-test-executor",
        )
        assert retried2.value.run.status.value == "dispatching"
        assert retried2.value.backoff_seconds == 10
        assert retried2.value.retry_after == retry2_observed_at + timedelta(seconds=10)
        assert retried2.value.command_created is True
        assert gateway.claim_commands(
            successor.tenant_id,
            "worker:blueprint-retry-before-due",
            actor_subject="workload:blueprint-test-executor",
            limit=10,
            lease_seconds=5,
        ) == []
        with engine.connect() as connection:
            retry_event_count = connection.execute(
                text(
                    """
                    SELECT count(*)
                    FROM gda_control.platform_run_event
                    WHERE tenant_id = :tenant_id
                      AND run_id = :run_id
                      AND details ->> 'schema' =
                          'gda.data_product_blueprint_provider_retry.v1'
                    """
                ),
                {"tenant_id": successor.tenant_id, "run_id": retry_run.run_id},
            ).scalar_one()
        assert retry_event_count == 2

        timeout_admission = gateway.admit_blueprint_test_run(
            DataProductBlueprintTestRunRequest(
                blueprint=successor,
                run_id=uuid4(),
                idempotency_key="districts-blueprint-provider-timeout-1",
                input_bindings=(
                    ResourceBinding(
                        binding_name="source",
                        resource_version_id=test_source_version_id,
                        semantic_type="source.dataset",
                    ),
                ),
            ),
            subject_context=test_subject,
        )
        timeout_run = timeout_admission.value.run
        for next_status in ("dispatching", "running", "cancelling"):
            timeout_run = gateway.transition_run(
                successor.tenant_id,
                timeout_run.run_id,
                timeout_run.state_version,
                next_status,
                "workload:blueprint-test-executor",
                f"prepare provider timeout state {next_status}",
                {"schema": "gda.blueprint_provider_timeout_setup.v1"},
            )
        timeout_plan_id = timeout_admission.value.execution_plan.artifact_id
        timeout_observation_id = uuid4()
        timeout_observed_at = successor.created_at + timedelta(minutes=10)
        timeout_evidence = {
            "schema": "gda.data_product_blueprint_provider_cancellation_timeout.v1",
            "execution_plan_artifact_id": str(timeout_plan_id),
            "provider_state": "ready_stop",
            "observation_id": str(timeout_observation_id),
            "attempt_no": 3,
            "framework_kind": "spark",
            "external_namespace": "spark-blueprint-tests",
            "external_run_id": "spark-app-timeout",
            "external_attempt_id": "attempt-3",
            "observed_at": timeout_observed_at.isoformat().replace("+00:00", "Z"),
            "reconcile_attempt": 3,
            "max_reconcile_attempts": 3,
            "provider_receipt": {"application_state": "READY_STOP"},
        }
        timeout_observation = FrameworkAttemptObservation(
            tenant_id=successor.tenant_id,
            observation_id=timeout_observation_id,
            run_id=timeout_run.run_id,
            attempt_no=3,
            framework_kind=FrameworkKind.SPARK,
            external_namespace="spark-blueprint-tests",
            external_run_id="spark-app-timeout",
            external_attempt_id="attempt-3",
            observed_state="ready_stop",
            observation_sha256=canonical_json_fingerprint(timeout_evidence),
            evidence=timeout_evidence,
            observed_at=timeout_observed_at,
        )
        timeout_values = {
            "tenant_id": successor.tenant_id,
            "run_id": timeout_run.run_id,
            "execution_plan_artifact_id": timeout_plan_id,
            "provider_state": "ready_stop",
            "reconcile_attempt": 3,
            "max_reconcile_attempts": 3,
            "attempt_observation": timeout_observation,
            "reason": "provider cancellation retries exhausted",
        }
        timeout_receipt = DataProductBlueprintProviderCancellationTimeoutRequest(
            **timeout_values,
            timeout_receipt_sha256=(
                data_product_blueprint_provider_cancellation_timeout_fingerprint(
                    timeout_values
                )
            ),
        )
        with pytest.raises(GatewayForbiddenError, match="does not match"):
            gateway.record_blueprint_provider_cancellation_timeout(
                timeout_receipt,
                actor_subject="workload:other-provider",
            )
        timed_out = gateway.record_blueprint_provider_cancellation_timeout(
            timeout_receipt,
            actor_subject="workload:blueprint-test-executor",
        )
        replayed_timeout = gateway.record_blueprint_provider_cancellation_timeout(
            timeout_receipt,
            actor_subject="workload:blueprint-test-executor",
        )
        assert timed_out.created is True
        assert timed_out.value.run.status.value == "failed"
        assert timed_out.value.incident.incident_type == (
            "blueprint_provider_cancellation_timeout"
        )
        assert timed_out.value.incident.severity.value == "high"
        assert timed_out.value.incident_created is True
        assert timed_out.value.transitioned is True
        assert replayed_timeout.created is False
        assert replayed_timeout.value == timed_out.value.model_copy(
            update={
                "observation_created": False,
                "incident_created": False,
                "transitioned": False,
            }
        )
        with engine.connect() as connection:
            event_count = connection.execute(
                text(
                    """
                    SELECT count(*)
                    FROM gda_control.platform_run_event
                    WHERE tenant_id = :tenant_id
                      AND run_id = :run_id
                      AND details ->> 'schema' =
                          'gda.data_incident_run_failure.v1'
                      AND details ->> 'incident_id' = :incident_id
                    """
                ),
                    {
                        "tenant_id": successor.tenant_id,
                        "run_id": timeout_run.run_id,
                        "incident_id": str(timed_out.value.incident.incident_id),
                    },
            ).scalar_one()
            incident_event_count = connection.execute(
                text(
                    """
                    SELECT count(*)
                    FROM gda_control.data_incident_event
                    WHERE tenant_id = :tenant_id
                      AND incident_id = :incident_id
                    """
                ),
                {
                    "tenant_id": successor.tenant_id,
                    "incident_id": timed_out.value.incident.incident_id,
                },
            ).scalar_one()
        assert event_count == 1
        assert incident_event_count == 1

        unreconciled_admission = gateway.admit_blueprint_test_run(
            DataProductBlueprintTestRunRequest(
                blueprint=successor,
                run_id=uuid4(),
                idempotency_key="districts-blueprint-provider-invalid-state-1",
                input_bindings=(
                    ResourceBinding(
                        binding_name="source",
                        resource_version_id=test_source_version_id,
                        semantic_type="source.dataset",
                    ),
                ),
            ),
            subject_context=test_subject,
        )
        invalid_run = unreconciled_admission.value.run
        invalid_plan_id = unreconciled_admission.value.execution_plan.artifact_id
        invalid_observed_at = successor.created_at + timedelta(minutes=4)
        invalid_observation_id = uuid4()
        invalid_evidence = {
            "schema": "gda.data_product_blueprint_provider_observation.v1",
            "execution_plan_artifact_id": str(invalid_plan_id),
            "provider_state": "running",
            "observation_id": str(invalid_observation_id),
            "attempt_no": 1,
            "framework_kind": "spark",
            "external_namespace": "spark-blueprint-tests",
            "external_run_id": "spark-app-invalid",
            "external_attempt_id": None,
            "observed_at": invalid_observed_at.isoformat().replace("+00:00", "Z"),
        }
        invalid_observation = FrameworkAttemptObservation(
            tenant_id=successor.tenant_id,
            observation_id=invalid_observation_id,
            run_id=invalid_run.run_id,
            attempt_no=1,
            framework_kind=FrameworkKind.SPARK,
            external_namespace="spark-blueprint-tests",
            external_run_id="spark-app-invalid",
            observed_state="running",
            observation_sha256=canonical_json_fingerprint(invalid_evidence),
            evidence=invalid_evidence,
            observed_at=invalid_observed_at,
        )
        invalid_values = {
            "tenant_id": successor.tenant_id,
            "run_id": invalid_run.run_id,
            "execution_plan_artifact_id": invalid_plan_id,
            "provider_state": "running",
            "attempt_observation": invalid_observation,
            "reason": "provider receipt arrived before reconciliation",
        }
        invalid_receipt = DataProductBlueprintProviderReconcileRequest(
            **invalid_values,
            reconcile_receipt_sha256=(
                data_product_blueprint_provider_reconcile_fingerprint(invalid_values)
            ),
        )
        with pytest.raises(GatewayConflictError, match="requires a reconciling"):
            gateway.reconcile_blueprint_test_provider(
                invalid_receipt,
                actor_subject="workload:blueprint-test-executor",
            )

        wrong_plan_values = {
            **invalid_values,
            "execution_plan_artifact_id": admitted.value.execution_plan.artifact_id,
        }
        wrong_plan_evidence = {
            **invalid_evidence,
            "execution_plan_artifact_id": str(
                admitted.value.execution_plan.artifact_id
            ),
        }
        wrong_plan_observation = invalid_observation.model_copy(
            update={
                "observation_sha256": canonical_json_fingerprint(
                    wrong_plan_evidence
                ),
                "evidence": wrong_plan_evidence,
            }
        )
        wrong_plan_values["attempt_observation"] = wrong_plan_observation
        wrong_plan_receipt = DataProductBlueprintProviderReconcileRequest(
            **wrong_plan_values,
            reconcile_receipt_sha256=(
                data_product_blueprint_provider_reconcile_fingerprint(
                    wrong_plan_values
                )
            ),
        )
        with pytest.raises(GatewayValidationError, match="does not match"):
            gateway.reconcile_blueprint_test_provider(
                wrong_plan_receipt,
                actor_subject="workload:blueprint-test-executor",
            )

        execution_request = DataProductBlueprintTestExecutionRequest(
            run_id=admitted.value.run.run_id,
        )
        execution = gateway.execute_blueprint_test_run(
            successor.tenant_id,
            execution_request,
            actor_subject="workload:blueprint-test-executor",
        )
        replayed_execution = gateway.execute_blueprint_test_run(
            successor.tenant_id,
            execution_request,
            actor_subject="workload:blueprint-test-executor",
        )
        assert execution.created is True
        assert replayed_execution.created is False
        assert execution.value.run.status.value == "succeeded"
        assert execution.value.executor_mode == "deterministic_local"
        assert execution.value.quality_result.verdict.value == "passed"
        assert execution.value.success_evidence.run_id == admitted.value.run.run_id

        duckdb_source_path = tmp_path / "duckdb-district-source.parquet"
        pq.write_table(
            pa.table(
                {
                    "district": ["a", "a", "b"],
                    "area": [10.5, 4.5, 7.0],
                    "min_x": [1.0, 1.5, 5.0],
                    "min_y": [2.0, 2.5, 6.0],
                    "geometry_wkb": [
                        box(106.50, 29.50, 106.51, 29.51).wkb,
                        box(106.51, 29.51, 106.52, 29.52).wkb,
                        box(106.55, 29.55, 106.56, 29.56).wkb,
                    ],
                    "srid": [4326, 4326, 4326],
                    "bbox": [
                        [106.50, 29.50, 106.51, 29.51],
                        [106.51, 29.51, 106.52, 29.52],
                        [106.55, 29.55, 106.56, 29.56],
                    ],
                }
            ),
            duckdb_source_path,
        )
        duckdb_source_sha256 = _file_sha256(duckdb_source_path)
        duckdb_source_locator = duckdb_source_path.as_uri()
        duckdb_provider_system = "duckdb"
        duckdb_object_version_id = None
        duckdb_provider = None
        if S3_ACCEPTANCE_ENDPOINT:
            import boto3

            required_s3 = {
                name: os.environ[name]
                for name in (
                    "GDA_BLUEPRINT_ACCEPTANCE_S3_BUCKET",
                    "GDA_BLUEPRINT_ACCEPTANCE_S3_ADMIN_ACCESS_KEY",
                    "GDA_BLUEPRINT_ACCEPTANCE_S3_ADMIN_SECRET_KEY",
                    "GDA_BLUEPRINT_ACCEPTANCE_S3_WORKER_ACCESS_KEY",
                    "GDA_BLUEPRINT_ACCEPTANCE_S3_WORKER_SECRET_KEY",
                )
            }
            common_s3 = {
                "endpoint_url": S3_ACCEPTANCE_ENDPOINT,
                "region_name": "us-east-1",
                "config": BotoConfig(
                    connect_timeout=5,
                    read_timeout=15,
                    retries={"total_max_attempts": 1, "mode": "standard"},
                    s3={"addressing_style": "path"},
                ),
            }
            admin_s3 = boto3.client(
                "s3",
                aws_access_key_id=required_s3[
                    "GDA_BLUEPRINT_ACCEPTANCE_S3_ADMIN_ACCESS_KEY"
                ],
                aws_secret_access_key=required_s3[
                    "GDA_BLUEPRINT_ACCEPTANCE_S3_ADMIN_SECRET_KEY"
                ],
                **common_s3,
            )
            worker_s3 = boto3.client(
                "s3",
                aws_access_key_id=required_s3[
                    "GDA_BLUEPRINT_ACCEPTANCE_S3_WORKER_ACCESS_KEY"
                ],
                aws_secret_access_key=required_s3[
                    "GDA_BLUEPRINT_ACCEPTANCE_S3_WORKER_SECRET_KEY"
                ],
                **common_s3,
            )
            bucket = required_s3["GDA_BLUEPRINT_ACCEPTANCE_S3_BUCKET"]
            input_prefix = "blueprint-inputs/v1"
            output_prefix = "blueprint-duckdb-results/v1"
            input_key = f"{input_prefix}/source.parquet"
            uploaded = admin_s3.put_object(
                Bucket=bucket,
                Key=input_key,
                Body=duckdb_source_path.read_bytes(),
                ContentType="application/vnd.apache.parquet",
                Metadata={"sha256": duckdb_source_sha256},
            )
            duckdb_object_version_id = str(uploaded.get("VersionId") or "")
            assert duckdb_object_version_id not in {"", "null"}
            duckdb_source_locator = f"s3://{bucket}/{input_key}"
            duckdb_provider_system = "s3"
            object_store = S3DuckDBBlueprintObjectStore(
                worker_s3,
                bucket=bucket,
                prefix=output_prefix,
                input_prefixes=(f"s3://{bucket}/{input_prefix}",),
            )
            object_store.probe()
            gateway = PlatformGateway(
                engine,
                blueprint_duckdb_output_root=tmp_path / "duckdb-workspace",
                blueprint_duckdb_result_backend="s3",
                blueprint_duckdb_output_s3_bucket=bucket,
                blueprint_duckdb_output_s3_prefix=output_prefix,
                blueprint_duckdb_input_s3_prefixes=(
                    f"s3://{bucket}/{input_prefix}",
                ),
                blueprint_duckdb_object_store=object_store,
            )
            duckdb_provider = DuckDBBlueprintProvider(
                object_store=object_store,
                workspace_root=tmp_path / "duckdb-workspace",
            )
        duckdb_source_urn = "gda://planning/dataset/duckdb-district-source"
        duckdb_definition_id = uuid4()
        duckdb_created_at = datetime.now(UTC)
        duckdb_blueprint_values = {
            "tenant_id": successor.tenant_id,
            "definition_urn": "gda://planning/definition/duckdb-districts-build",
            "definition_version_id": duckdb_definition_id,
            "version_key": "v1.0.0",
            "product_urn": "gda://planning/data_product/duckdb-districts",
            "domain": successor.domain,
            "owner_ref": successor.owner_ref,
            "source_refs": (duckdb_source_urn,),
            "storage_placement": {
                "profile": "lightweight",
                "table_format": "parquet",
            },
            "model_contract": {
                "schema": "duckdb-district-spatial.v1",
                "columns": ["district", "area", "geometry_wkb", "srid", "bbox"],
            },
            "quality_contract": {
                "verdict": "passed",
                "rules": ["non_empty", "source_checksum"],
            },
            "security_policy": {
                "classification": "internal",
                "external_access": "disabled",
            },
            "slo_contract": {"max_runtime_seconds": 60},
            "pipeline": {
                "schema": "gda.data_product_blueprint.duckdb_pipeline.v1",
                "engine": "duckdb",
                "mode": "batch",
                "sql": (
                    "WITH projected AS ("
                    "SELECT district, area, ST_Transform(ST_GeomFromWKB(geometry_wkb), "
                    "'EPSG:4326', 'EPSG:3857', always_xy := true) AS geom "
                    "FROM source WHERE srid = 4326"
                    ") SELECT district, area, ST_AsWKB(geom) AS geometry_wkb, "
                    "3857::INTEGER AS srid, "
                    "[ST_XMin(geom), ST_YMin(geom), ST_XMax(geom), ST_YMax(geom)]"
                    "::DOUBLE[] AS bbox FROM projected ORDER BY district, area"
                ),
                "output_format": "parquet",
                "max_output_rows": 100,
                "timeout_seconds": 60.0,
                "require_ordered_output": True,
                "require_spatial": True,
                "spatial_output_srid": 3857,
            },
            "projections": ({"kind": "parquet", "name": "districts"},),
            "retention_policy": {"days": 30},
            "cost_policy": {"budget_class": "local"},
            "created_by": DUCKDB_BLUEPRINT_WORKLOAD,
            "created_at": duckdb_created_at,
        }
        duckdb_blueprint = DataProductBlueprint(
            **duckdb_blueprint_values,
            blueprint_sha256=data_product_blueprint_fingerprint(
                duckdb_blueprint_values
            ),
        )
        duckdb_preview = build_data_product_blueprint_preview(duckdb_blueprint)
        duckdb_approval = build_data_product_blueprint_approval_case(
            duckdb_preview,
            requester_subject="human:planner",
            request_reason="review DuckDB provider conformance build",
            requested_at=duckdb_created_at,
            expires_at=duckdb_created_at + timedelta(days=2),
        )
        approval_authority.create(
            duckdb_approval,
            owner_ref="team:data-platform",
        )
        approval_authority.decide(
            tenant_id=duckdb_approval.tenant_id,
            approval_case_ref=duckdb_approval.approval_case_ref,
            expected_state_version=0,
            verdict=ApprovalCaseStatus.APPROVED,
            actor_subject="human:reviewer",
            reason="DuckDB provider conformance build approved",
        )
        gateway.register_definition(
            compile_data_product_blueprint(duckdb_blueprint)
        )
        gateway.register_resource(
            Resource(
                tenant_id=successor.tenant_id,
                resource_urn=duckdb_source_urn,
                resource_kind="dataset",
                authority_system=f"{duckdb_provider_system}-conformance",
                authority_locator=duckdb_source_locator,
                owner_ref=successor.owner_ref,
            )
        )
        duckdb_source_version_id = uuid4()
        gateway.register_resource_version(
            ResourceVersion(
                tenant_id=successor.tenant_id,
                resource_urn=duckdb_source_urn,
                resource_version_id=duckdb_source_version_id,
                version_key="snapshot-1",
                content_sha256=duckdb_source_sha256,
                authority_version_ref={
                    "snapshot_ref": duckdb_source_sha256,
                    "provider": duckdb_provider_system,
                    "object_version_id": duckdb_object_version_id,
                },
                created_by="workload:provider-harvester",
                created_at=duckdb_created_at,
            )
        )
        gateway.register_resource_version_architecture(
            _duckdb_architecture(
                tenant_id=successor.tenant_id,
                resource_version_id=duckdb_source_version_id,
                source_path=duckdb_source_path,
                content_sha256=duckdb_source_sha256,
                created_at=duckdb_created_at,
                provider_system=duckdb_provider_system,
                provider_locator=duckdb_source_locator,
                revision_ref=duckdb_object_version_id,
            )
        )
        duckdb_run_id = uuid4()
        duckdb_admission = gateway.admit_blueprint_test_run(
            DataProductBlueprintTestRunRequest(
                blueprint=duckdb_blueprint,
                run_id=duckdb_run_id,
                idempotency_key="duckdb-blueprint-provider-conformance-1",
                input_bindings=(
                    ResourceBinding(
                        binding_name="source",
                        resource_version_id=duckdb_source_version_id,
                        semantic_type="source.dataset",
                    ),
                ),
            ),
            subject_context=SubjectContext(
                tenant_id=successor.tenant_id,
                subject_id="blueprint-duckdb-executor",
                subject_type=SubjectType.WORKLOAD,
                roles=("platform_operator",),
                purpose="blueprint-duckdb-provider-conformance",
            ),
        )
        duckdb_admission_replay = gateway.admit_blueprint_test_run(
            DataProductBlueprintTestRunRequest(
                blueprint=duckdb_blueprint,
                run_id=duckdb_run_id,
                idempotency_key="duckdb-blueprint-provider-conformance-1",
                input_bindings=(
                    ResourceBinding(
                        binding_name="source",
                        resource_version_id=duckdb_source_version_id,
                        semantic_type="source.dataset",
                    ),
                ),
            ),
            subject_context=SubjectContext(
                tenant_id=successor.tenant_id,
                subject_id="blueprint-duckdb-executor",
                subject_type=SubjectType.WORKLOAD,
                roles=("platform_operator",),
                purpose="blueprint-duckdb-provider-conformance",
            ),
        )
        assert duckdb_admission_replay.created is False
        assert duckdb_admission_replay.value.provider_command == (
            duckdb_admission.value.provider_command
        )
        duckdb_plan_input = duckdb_admission.value.execution_plan.manifest[
            "inputs"
        ][0]
        assert duckdb_plan_input["content_sha256"] == duckdb_source_sha256
        assert duckdb_plan_input["physical_location"]["provider_locator"] == (
            duckdb_source_locator
        )
        assert duckdb_admission.value.provider_command is not None
        assert duckdb_admission.value.provider_command.command_type.value == (
            "blueprint_provider.execute"
        )
        duckdb_request = DuckDBBlueprintExecutionRequest(run_id=duckdb_run_id)
        with pytest.raises(GatewayForbiddenError, match="dedicated workload"):
            gateway.execute_blueprint_duckdb_test_run(
                successor.tenant_id,
                duckdb_request,
                actor_subject="workload:other-provider",
            )
        # Simulate ACK loss after the provider and Run success transaction:
        # worker A owns a short lease and executes the provider, but disappears
        # before complete_platform_command. Worker B must later reconcile the
        # terminal Run without executing DuckDB again.
        first_worker = "worker:blueprint-duckdb:postgres-ack-loss"
        claimed = gateway.claim_commands(
            successor.tenant_id,
            first_worker,
            actor_subject=DUCKDB_BLUEPRINT_WORKLOAD,
            limit=1,
            lease_seconds=5,
        )
        assert [item.command_id for item in claimed] == [
            duckdb_admission.value.provider_command.command_id
        ]
        first_execution = gateway.execute_blueprint_duckdb_test_run(
            successor.tenant_id,
            duckdb_request,
            actor_subject=DUCKDB_BLUEPRINT_WORKLOAD,
        )
        assert first_execution.created is True
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    UPDATE gda_control.platform_command_outbox
                    SET claimed_until = clock_timestamp() - interval '1 second'
                    WHERE tenant_id = :tenant_id
                      AND command_id = :command_id
                      AND claimed_by = :worker_id
                      AND status = 'in_flight'
                    """
                ),
                {
                    "tenant_id": successor.tenant_id,
                    "command_id": claimed[0].command_id,
                    "worker_id": first_worker,
                },
            )
        second_worker = "worker:blueprint-duckdb:postgres-redelivery"
        worker_result = DuckDBBlueprintCommandConsumer(
            gateway=gateway,
            provider=duckdb_provider,
        ).run_once(
            successor.tenant_id,
            worker_id=second_worker,
            limit=1,
            lease_seconds=900,
        )
        assert worker_result.claimed == 1
        assert worker_result.completed == 1
        assert worker_result.execution_succeeded == 0
        assert worker_result.terminal_reconciled == 1
        command = gateway.get_command(
            successor.tenant_id,
            duckdb_admission.value.provider_command.command_id,
        )
        assert command.status.value == "done"
        assert command.attempt_count == 2
        with pytest.raises(GatewayForbiddenError, match="dedicated workload"):
            gateway.execute_blueprint_duckdb_test_run(
                successor.tenant_id,
                duckdb_request,
                actor_subject="workload:other-provider",
            )
        duckdb_execution = gateway.execute_blueprint_duckdb_test_run(
            successor.tenant_id,
            duckdb_request,
            actor_subject=DUCKDB_BLUEPRINT_WORKLOAD,
        )
        duckdb_replay = gateway.execute_blueprint_duckdb_test_run(
            successor.tenant_id,
            duckdb_request,
            actor_subject=DUCKDB_BLUEPRINT_WORKLOAD,
        )
        assert duckdb_execution.created is False
        assert duckdb_replay.created is False
        assert duckdb_execution.value == first_execution.value
        assert duckdb_replay.value == duckdb_execution.value
        assert duckdb_execution.value.run.status.value == "succeeded"
        assert duckdb_execution.value.executor_mode == "duckdb_provider"
        assert duckdb_execution.value.attempt_observation.framework_kind.value == (
            "duckdb"
        )
        assert duckdb_execution.value.attempt_observation.evidence[
            "external_access"
        ] == "disabled"
        spatial_receipt = duckdb_execution.value.attempt_observation.evidence
        assert spatial_receipt["spatial_extension_loaded"] is True
        assert spatial_receipt["spatial_extension_evidence"]["schema"] == (
            "gda.duckdb_spatial_extension.v1"
        )
        spatial_output_evidence = spatial_receipt["spatial_output_evidence"]
        assert spatial_output_evidence["schema"] == "gda.geoparquet_spatial_output.v1"
        assert spatial_output_evidence["srid"] == 3857
        assert spatial_output_evidence["geometry_column"] == "geometry_wkb"
        assert spatial_output_evidence["srid_column"] == "srid"
        assert spatial_output_evidence["bbox_column"] == "bbox"
        assert duckdb_execution.value.quality_result.metrics[
            "spatial_requirement_satisfied"
        ] is True
        if S3_ACCEPTANCE_ENDPOINT:
            assert duckdb_execution.value.output_artifact.storage_uri.startswith(
                "s3://"
            )
            assert duckdb_execution.value.output_artifact.manifest[
                "storage_evidence"
            ] == duckdb_execution.value.attempt_observation.evidence[
                "output_storage_evidence"
            ]
        else:
            assert duckdb_execution.value.output_artifact.storage_uri.startswith(
                "file://"
            )
            spatial_output = pq.read_table(
                tmp_path / "duckdb-outputs" / f"{duckdb_run_id}.parquet"
            )
            assert spatial_output.num_rows == 3
            assert set(spatial_output["srid"].to_pylist()) == {3857}
            assert b"geo" in spatial_output.schema.metadata
        duckdb_release = build_data_product_blueprint_release_binding(
            duckdb_preview,
            approval_case_ref=duckdb_approval.approval_case_ref,
            test_execution=duckdb_execution.value,
        )
        duckdb_version_values = {
            "tenant_id": successor.tenant_id,
            "data_product_version_id": uuid4(),
            "product_urn": duckdb_blueprint.product_urn,
            "version_key": duckdb_blueprint.version_key,
            "predecessor_version_id": None,
            "source_resource_version_id": duckdb_source_version_id,
            "output_resource_version_id": (
                duckdb_execution.value.output_resource_version.resource_version_id
            ),
            "standard_version_ref": "standard:district:v1",
            "mapping_contract": {"mapping": {"source": "district"}},
            "quality_contract": {"verdict": "passed", "checks": []},
            "quality_evidence_artifact_id": (
                duckdb_execution.value.quality_evidence_artifact.artifact_id
            ),
            "distribution_manifest": {
                "formats": ["parquet"],
                "blueprint_release": duckdb_release.model_dump(mode="json"),
            },
            "published_by": "workload:data-product-controller",
            "published_at": duckdb_execution.value.run.submitted_at
            + timedelta(minutes=5),
        }
        duckdb_version = DataProductVersionSpec(
            **duckdb_version_values,
            manifest_sha256=data_product_manifest_fingerprint(
                duckdb_version_values
            ),
        )
        with registry._transaction(successor.tenant_id) as connection:
            assert registry._validate_live_blueprint_release(
                connection,
                version=duckdb_version,
                binding=duckdb_release,
            ) == duckdb_release

        release = build_data_product_blueprint_release_binding(
            preview,
            approval_case_ref=approval_case.approval_case_ref,
            test_execution=execution.value,
        )
        version_payload = version.model_dump(mode="python")
        version_payload["distribution_manifest"] = {
            "formats": [],
            "blueprint_release": release.model_dump(mode="json"),
        }
        version_payload["manifest_sha256"] = data_product_manifest_fingerprint(
            version_payload
        )
        version = DataProductVersionSpec.model_validate(version_payload)
        with registry._transaction(successor.tenant_id) as connection:
            assert registry._validate_live_blueprint_release(
                connection,
                version=version,
                binding=release,
            ) == release
        tampered_execution_release = release.model_copy(
            update={"test_success_evidence_sha256": "e" * 64}
        )
        tampered_version_payload = version.model_dump(mode="python")
        tampered_version_payload["distribution_manifest"] = {
            "formats": [],
            "blueprint_release": tampered_execution_release.model_dump(mode="json"),
        }
        tampered_version_payload["manifest_sha256"] = data_product_manifest_fingerprint(
            tampered_version_payload
        )
        tampered_version = DataProductVersionSpec.model_validate(
            tampered_version_payload
        )
        with (
            registry._transaction(successor.tenant_id) as connection,
            pytest.raises(DataProductConflictError, match="terminal event"),
        ):
            registry._validate_live_blueprint_release(
                connection,
                version=tampered_version,
                binding=tampered_execution_release,
            )
        gateway.record_artifact(
            Artifact(
                tenant_id=successor.tenant_id,
                artifact_id=version.quality_evidence_artifact_id,
                artifact_key="quality.districts-v1.1.0.json",
                artifact_role=ArtifactRole.EVIDENCE,
                storage_uri="s3://quality-evidence/districts-v1.1.0.json",
                media_type="application/json",
                content_sha256="6" * 64,
                size_bytes=128,
                resource_version_id=version.output_resource_version_id,
                manifest={"verdict": "passed"},
                created_by=version.published_by,
                created_at=version.published_at,
            )
        )
        product = DataProductSpec(
            tenant_id=successor.tenant_id,
            product_urn=successor.product_urn,
            product_slug="districts",
            title="Districts",
            description="Governed district product",
            domain=successor.domain,
            owner_ref=successor.owner_ref,
            governance_ref={
                "classification": "internal",
                "visibility": "private",
                "license_id": "internal",
                "attribution": "planning",
            },
            created_at=approval_requested_at,
        )
        route_request = MagicMock()

        async def read_route_body():
            return {
                "product": product.model_dump(mode="json"),
                "version": version.model_dump(mode="json"),
                "blueprint_release_binding": release.model_dump(mode="json"),
                "idempotency_key": "publish-districts-v1.1.0",
                "reason": "publish approved Blueprint change set",
            }

        route_request.json.side_effect = read_route_body
        route_request.headers = {"x-request-id": "blueprint-release-postgres-1"}
        route_request.path_params = {}
        route_request.query_params = {}
        workload = SimpleNamespace(
            identifier="data-product-controller",
            metadata={
                "role": "platform_operator",
                "tenant_id": successor.tenant_id,
                "subject_type": "workload",
            },
        )
        with (
            patch.object(
                platform_routes,
                "_get_user_from_request",
                return_value=workload,
            ),
            patch.object(platform_routes, "DataProductRegistry", return_value=registry),
        ):
            route_response = asyncio.run(
                platform_routes.publish_data_product_blueprint_release(route_request)
            )
            route_replay_response = asyncio.run(
                platform_routes.publish_data_product_blueprint_release(route_request)
            )
        assert route_response.status_code == 201
        route_payload = json.loads(route_response.body)
        assert route_payload["created"] is True
        assert route_replay_response.status_code == 200
        assert json.loads(route_replay_response.body)["created"] is False
        published = route_payload["data"]["publication"]

        replayed = registry.publish(
            product,
            version,
            idempotency_key="publish-districts-v1.1.0",
            reason="publish approved Blueprint change set",
            blueprint_release_binding=release,
        )
        assert published["version_created"] is True
        assert published["pointer_changed"] is True
        assert published["blueprint_release_validated"] is True
        assert replayed["idempotent_replay"] is True
        assert replayed["event_created"] is False
        assert replayed["blueprint_release_validated"] is True

        with engine.connect() as connection:
            successor_row = connection.execute(
                text(
                    """
                    SELECT predecessor_version_id, content_sha256
                    FROM gda_control.resource_version
                    WHERE tenant_id = :tenant_id
                      AND resource_version_id = :resource_version_id
                    """
                ),
                {
                    "tenant_id": successor.tenant_id,
                    "resource_version_id": successor.definition_version_id,
                },
            ).one()
            product_release_row = connection.execute(
                text(
                    """
                    SELECT version.distribution_manifest -> 'blueprint_release',
                           product.current_version_id,
                           (SELECT count(*) FROM gda_control.data_product_event
                            WHERE tenant_id = :tenant_id
                              AND product_urn = :product_urn)
                    FROM gda_control.data_product_version version
                    JOIN gda_control.data_product product
                      ON product.tenant_id = version.tenant_id
                     AND product.product_urn = version.product_urn
                    WHERE version.tenant_id = :tenant_id
                      AND version.data_product_version_id = :version_id
                    """
                ),
                {
                    "tenant_id": successor.tenant_id,
                    "product_urn": successor.product_urn,
                    "version_id": version.data_product_version_id,
                },
            ).one()
        assert successor_row == (
            blueprint.definition_version_id,
            preview.definition_sha256,
        )
        assert product_release_row == (
            release.model_dump(mode="json"),
            version.data_product_version_id,
            1,
        )
    finally:
        engine.dispose()
