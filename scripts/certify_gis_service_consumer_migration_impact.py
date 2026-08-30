#!/usr/bin/env python3
"""Certify GIS service migration-impact authority on disposable PostgreSQL."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

try:  # Support package imports and direct script invocation.
    from scripts.certify_gis_service_control_plane import (
        MIGRATIONS as GIS_CONTROL_PLANE_MIGRATIONS,
    )
    from scripts.certify_gis_service_control_plane import (
        _definition,
        _deployment,
        _endpoint,
        _release_bundle,
        _seed_authorities,
        _service_policy,
        _sql_file,
    )
except ModuleNotFoundError:  # pragma: no cover - direct script invocation path.
    from certify_gis_service_control_plane import (
        MIGRATIONS as GIS_CONTROL_PLANE_MIGRATIONS,
    )
    from certify_gis_service_control_plane import (
        _definition,
        _deployment,
        _endpoint,
        _release_bundle,
        _seed_authorities,
        _service_policy,
        _sql_file,
    )
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import DBAPIError

from data_agent.approval_case_authority import ApprovalCaseAuthority
from data_agent.consumer_binding import (
    ConsumerBinding,
    ConsumerBindingMigrationState,
    consumer_binding_fingerprint,
    consumer_binding_migration_state_fingerprint,
)
from data_agent.gis_mvt_cache_purge import (
    GIS_MVT_CACHE_PURGE_WORKLOAD,
    GISMVTCachePurgeTask,
)
from data_agent.gis_mvt_response_cache import mvt_response_cache_namespace
from data_agent.gis_service_consumer_binding_migration import (
    GISServiceConsumerBindingMigrationImpact,
    gis_service_consumer_binding_migration_impact_fingerprint,
)
from data_agent.gis_service_control_plane import (
    GISServiceDefinitionVersion,
    gis_service_definition_fingerprint,
)
from data_agent.gis_service_endpoint_warmup import (
    GISServiceEndpointWarmupReceipt,
    gis_service_endpoint_warmup_artifact_manifest,
    gis_service_endpoint_warmup_fingerprint,
)
from data_agent.gis_service_migration_cutover import (
    GISServiceMigrationCutoverRequest,
    gis_service_migration_cutover_fingerprint,
)
from data_agent.gis_service_migration_rollback import (
    GISServiceMigrationRollbackRequest,
    gis_service_migration_rollback_approval_context,
    gis_service_migration_rollback_fingerprint,
    gis_service_migration_rollback_operation_fingerprint,
)
from data_agent.migration_runner import catalog_fingerprint, discover_migrations
from data_agent.platform_contracts import (
    ApprovalAvailabilityStatus,
    ApprovalCase,
    ApprovalCaseStatus,
    ApprovalPrincipalStatus,
    ApprovalPrincipalType,
    Artifact,
    FrameworkAttemptObservation,
    IncidentSeverity,
    LineageEvent,
    PlatformDefinitionVersion,
    PlatformRun,
    QualityResult,
    Resource,
    ResourceBinding,
    ResourceVersion,
    RunSuccessEvidence,
    SubjectContext,
    canonical_json_fingerprint,
    platform_definition_fingerprint,
    quality_result_fingerprint,
    run_success_evidence_fingerprint,
)
from data_agent.platform_gateway import (
    DefinitionRegistration,
    GatewayConflictError,
    GatewayForbiddenError,
    GatewayValidationError,
    PlatformGateway,
    PlatformGatewayError,
)
from data_agent.service_consumer_binding import (
    ServiceConsumerBinding,
    service_consumer_binding_fingerprint,
)
from data_agent.service_consumer_binding_grant import (
    ServiceConsumerBindingGrantService,
    build_service_consumer_binding_grant_plan,
)

MIGRATIONS = tuple(
    sorted(
        {
            *GIS_CONTROL_PLANE_MIGRATIONS,
            "098_platform_data_incident.sql",
            "123_resource_bound_data_incident.sql",
            "150_consumer_binding_migration_state.sql",
            "152_consumer_binding_migration_notification_outbox.sql",
            "217_gis_service_consumer_binding_migration_impact.sql",
            "218_gis_service_migration_cutover.sql",
            "219_gis_service_migration_rollback.sql",
            "220_gis_service_endpoint_warmup.sql",
            "222_gis_mvt_cache_purge_outbox.sql",
        },
        key=lambda name: int(name.split("_", 1)[0]),
    )
)


def _bootstrap(engine: Engine, login_role: str) -> None:
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE agent_data_assets ("
            "id SERIAL PRIMARY KEY, asset_name TEXT NOT NULL, "
            "operational_metadata JSONB NOT NULL DEFAULT '{}'::jsonb)"
        )
        connection.exec_driver_sql(
            "CREATE TABLE agent_data_requests ("
            "id SERIAL PRIMARY KEY, asset_id INTEGER NOT NULL "
            "REFERENCES agent_data_assets(id), requester VARCHAR(100) NOT NULL, "
            "status VARCHAR(30) NOT NULL DEFAULT 'pending', approver VARCHAR(100), "
            "approved_at TIMESTAMP, created_at TIMESTAMP NOT NULL DEFAULT NOW())"
        )
        for filename in MIGRATIONS:
            connection.exec_driver_sql(_sql_file(filename))
        connection.exec_driver_sql(f'GRANT gda_control_gateway TO "{login_role}"')


def _seed_successor_product(
    engine: Engine,
    source: dict[str, object],
    now: datetime,
) -> dict[str, object]:
    target_output_id = uuid4()
    target_product_version_id = uuid4()
    target_run_id = uuid4()
    target_manifest_sha256 = "8" * 64
    target_output_sha256 = "9" * 64
    with engine.begin() as connection:
        output_urn = connection.execute(
            text(
                "SELECT resource_urn FROM gda_control.resource_version "
                "WHERE tenant_id = :tenant AND resource_version_id = :output_id"
            ),
            {"tenant": source["tenant"], "output_id": source["output_id"]},
        ).scalar_one()
        connection.execute(
            text(
                """
                INSERT INTO gda_control.resource_version (
                    tenant_id, resource_version_id, resource_urn, version_key,
                    predecessor_version_id, content_sha256,
                    authority_version_ref, created_by, created_at
                ) VALUES (
                    :tenant, :output_id, :output_urn, 'snapshot-2',
                    :predecessor_id, :output_sha, '{}'::jsonb,
                    'workload:product-publisher', :created_at
                )
                """
            ),
            {
                "tenant": source["tenant"],
                "output_id": target_output_id,
                "output_urn": output_urn,
                "predecessor_id": source["output_id"],
                "output_sha": target_output_sha256,
                "created_at": now,
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO gda_control.platform_run (
                    tenant_id, run_id, definition_version_id,
                    orchestration_class, subject_context, idempotency_key,
                    policy_refs, status, state_version,
                    submitted_by, submitted_at, updated_at
                ) VALUES (
                    :tenant, :run_id, :definition_id, 'dataops',
                    CAST(:subject_context AS jsonb), 'deploy-district-v2',
                    '{}'::jsonb, 'accepted', 0,
                    'workload:service-controller', :submitted_at, :submitted_at
                )
                """
            ),
            {
                "tenant": source["tenant"],
                "run_id": target_run_id,
                "definition_id": source["platform_definition_id"],
                "subject_context": json.dumps(
                    {
                        "tenant_id": source["tenant"],
                        "subject_type": "workload",
                        "subject_id": "service-controller",
                        "roles": ["service_operator"],
                        "purpose": "deploy target GIS service release",
                    }
                ),
                "submitted_at": now,
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO gda_control.platform_run_input_binding (
                    tenant_id, run_id, binding_name,
                    resource_version_id, semantic_type
                ) VALUES
                    (:tenant, :run_id, 'source_dataset', :source_id,
                     'gda.data_product.source'),
                    (:tenant, :run_id, 'source_product', :output_id,
                     'gda.data_product.output')
                """
            ),
            {
                "tenant": source["tenant"],
                "run_id": target_run_id,
                "source_id": source["source_id"],
                "output_id": target_output_id,
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO gda_control.data_product_version (
                    tenant_id, data_product_version_id, product_urn,
                    version_key, predecessor_version_id,
                    source_resource_version_id, output_resource_version_id,
                    standard_version_ref, mapping_contract, quality_contract,
                    quality_verdict, quality_evidence_artifact_id,
                    distribution_manifest, manifest_sha256,
                    published_by, published_at
                ) VALUES (
                    :tenant, :version_id, :product_urn, 'v2.0.0',
                    :predecessor_id, :source_id, :output_id,
                    'standard:district-v2',
                    '{"mapping":{"district_id":"district_id"}}'::jsonb,
                    '{"verdict":"passed"}'::jsonb, 'passed', :artifact_id,
                    '{"formats":["geoparquet"]}'::jsonb, :manifest_sha,
                    'workload:product-publisher', :published_at
                )
                """
            ),
            {
                "tenant": source["tenant"],
                "version_id": target_product_version_id,
                "product_urn": source["product_urn"],
                "predecessor_id": source["product_version_id"],
                "source_id": source["source_id"],
                "output_id": target_output_id,
                "artifact_id": source["quality_artifact_id"],
                "manifest_sha": target_manifest_sha256,
                "published_at": now,
            },
        )
        connection.execute(
            text(
                """
                UPDATE gda_control.data_product
                   SET current_version_id = :version_id, updated_at = :updated_at
                 WHERE tenant_id = :tenant AND product_urn = :product_urn
                """
            ),
            {
                "version_id": target_product_version_id,
                "updated_at": now,
                "tenant": source["tenant"],
                "product_urn": source["product_urn"],
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO gda_control.data_product_event (
                    tenant_id, event_id, product_urn, event_type,
                    from_version_id, to_version_id, actor_subject,
                    reason, idempotency_key, occurred_at
                ) VALUES (
                    :tenant, :event_id, :product_urn, 'promoted',
                    :from_id, :to_id, 'workload:product-publisher',
                    'certify GIS service migration impact',
                    'promote-v2-for-gis-impact', :occurred_at
                )
                """
            ),
            {
                "tenant": source["tenant"],
                "event_id": uuid4(),
                "product_urn": source["product_urn"],
                "from_id": source["product_version_id"],
                "to_id": target_product_version_id,
                "occurred_at": now,
            },
        )
    return {
        **source,
        "output_id": target_output_id,
        "output_content_sha256": target_output_sha256,
        "product_version_id": target_product_version_id,
        "product_manifest_sha256": target_manifest_sha256,
        "run_id": target_run_id,
    }


def _target_definition(
    source: GISServiceDefinitionVersion,
    target_seed: dict[str, object],
    now: datetime,
) -> GISServiceDefinitionVersion:
    values = source.model_dump(mode="python", exclude={"definition_sha256"})
    values.update(
        service_definition_version_id=uuid4(),
        version_key="v2.0.0",
        predecessor_version_id=source.service_definition_version_id,
        source_data_product_version_id=target_seed["product_version_id"],
        source_manifest_sha256=target_seed["product_manifest_sha256"],
        created_at=now,
    )
    return GISServiceDefinitionVersion(
        **values,
        definition_sha256=gis_service_definition_fingerprint(values),
    )


def _issue_source_service_binding(
    gateway: PlatformGateway,
    login_engine: Engine,
    source: dict[str, object],
    definition: GISServiceDefinitionVersion,
    release_id,
    now: datetime,
    *,
    register_principal: bool = True,
    consumer_ref: str = "workload:planner-api",
) -> ServiceConsumerBinding:
    values = {
        "tenant_id": source["tenant"],
        "service_consumer_binding_id": uuid4(),
        "service_urn": source["service_urn"],
        "service_definition_version_id": definition.service_definition_version_id,
        "service_release_binding_id": release_id,
        "consumer_ref": consumer_ref,
        "action": "mvt.read",
        "purpose": "gis_mvt_read",
        "scope": {"operations": ["read"]},
        "credential_ref": f"credential:{consumer_ref.split(':', 1)[1]}-mvt",
        "expires_at": now + timedelta(days=30),
        "compatibility_fingerprint": "a" * 64,
        "compatibility_evidence": {
            "schema": "gda.gis_service_consumer_binding_compatibility.v1",
            "service_release_binding_id": str(release_id),
        },
        "created_by": "workload:service-controller",
        "created_at": now,
    }
    proposed = ServiceConsumerBinding(
        **values,
        binding_sha256=service_consumer_binding_fingerprint(values),
    )
    approvals = ApprovalCaseAuthority(login_engine)
    if register_principal:
        approvals.upsert_principal(
            tenant_id=str(source["tenant"]),
            principal_subject="human:service-owner",
            expected_directory_version=0,
            principal_type=ApprovalPrincipalType.HUMAN,
            display_name="Service Owner",
            status=ApprovalPrincipalStatus.ACTIVE,
            approval_eligible=True,
            availability_status=ApprovalAvailabilityStatus.AVAILABLE,
            valid_from=now - timedelta(minutes=1),
            valid_until=None,
            actor_subject="human:service-owner",
            reason="register migration impact certifier",
        )
    service = ServiceConsumerBindingGrantService(gateway, approvals)
    plan = build_service_consumer_binding_grant_plan(proposed)
    request = service.request_grant(
        plan,
        requester_subject="workload:service-controller",
        request_reason="authorize exact source release",
        owner_ref="team:spatial-data",
        requested_at=now,
        expires_at=now + timedelta(hours=1),
    )
    approved = approvals.decide(
        tenant_id=str(source["tenant"]),
        approval_case_ref=request.approval_case.approval_case_ref,
        expected_state_version=0,
        verdict=ApprovalCaseStatus.APPROVED,
        actor_subject="human:service-owner",
        reason="approve exact source release binding",
    )
    return service.issue(
        plan, approval_case_ref=approved.approval_case_ref
    ).value


def _product_migration(
    gateway: PlatformGateway,
    source: dict[str, object],
    target: dict[str, object],
    now: datetime,
) -> tuple[ConsumerBinding, ConsumerBindingMigrationState, object]:
    values = {
        "tenant_id": source["tenant"],
        "binding_id": uuid4(),
        "product_urn": source["product_urn"],
        "consumer_ref": "workload:planner-api",
        "purpose": "serve district search",
        "scope": {"operations": ["read"]},
        "min_product_version": "v1.0.0",
        "max_product_version": "v2.0.0",
        "credential_ref": "credential:planner-api",
        "quota": {"max_packages": 5},
        "expires_at": now + timedelta(days=30),
        "compatibility_fingerprint": "b" * 64,
        "compatibility_evidence": {"schema": "districts.v1-to-v2"},
        "created_by": "human:data-steward",
        "created_at": now,
    }
    binding = ConsumerBinding(
        **values,
        binding_sha256=consumer_binding_fingerprint(values),
    )
    gateway.register_consumer_binding(binding)
    state_values = {
        "tenant_id": source["tenant"],
        "migration_state_id": uuid4(),
        "binding_id": binding.binding_id,
        "product_urn": source["product_urn"],
        "from_product_version_id": source["product_version_id"],
        "to_product_version_id": target["product_version_id"],
        "state_version": 1,
        "compatibility_conclusion": "breaking",
        "compatibility_evidence": {"removed_fields": ["legacy_code"]},
        "notification_status": "pending",
        "notification_evidence": {},
        "migration_deadline": now + timedelta(days=14),
        "consumer_acknowledgement": None,
        "previous_state_sha256": None,
        "recorded_by": "human:data-steward",
        "recorded_at": now + timedelta(seconds=1),
    }
    state = ConsumerBindingMigrationState(
        **state_values,
        state_sha256=consumer_binding_migration_state_fingerprint(state_values),
    )
    gateway.record_consumer_binding_migration_state(state)
    notifications = gateway.list_consumer_binding_migration_notifications(
        str(source["tenant"]),
        str(source["product_urn"]),
        binding_id=binding.binding_id,
    )
    if len(notifications) != 1:
        raise RuntimeError(f"expected one migration notification, found {len(notifications)}")
    return binding, state, notifications[0]


def _ready_endpoint_fixture(
    gateway: PlatformGateway,
    owner_engine: Engine,
    seed: dict[str, object],
    definition: GISServiceDefinitionVersion,
    release,
    serving_projection,
    now: datetime,
    *,
    revision_key: str,
    suffix: str,
    provider_revision_ref: str,
    provider_system: str = "pygeoapi",
):
    """Create a ready endpoint fixture without re-certifying provider lifecycle."""
    endpoint_uri = f"https://geo.example.test/tiles/districts-{suffix}"
    deployment = _deployment(
        seed,
        definition,
        release,
        now,
        revision_key=revision_key,
        provider_system=provider_system,
        provider_deployment_id=f"district-features-{suffix}",
        provider_revision_ref=provider_revision_ref,
        config_sha256=("6" if revision_key == "r1" else "7") * 64,
    )
    gateway.register_service_deployment_revision(deployment)
    observation_id = uuid4()
    evidence = {
        "schema": "gda.gis_service_deployment_observation.v2",
        "deployment_revision_id": str(deployment.deployment_revision_id),
        "service_definition_version_id": str(
            deployment.service_definition_version_id
        ),
        "service_release_binding_id": str(deployment.service_release_binding_id),
        "provider_system": deployment.provider_system,
        "provider_version": "fixture-1",
        "provider_namespace": deployment.provider_namespace,
        "provider_deployment_id": deployment.provider_deployment_id,
        "provider_revision_ref": deployment.provider_revision_ref,
        "config_sha256": deployment.config_sha256,
        "endpoint_uri": endpoint_uri,
        "health_evidence_sha256": "8" * 64,
        "provider_receipt": {"fixture": True, "health_status": 200},
    }
    terminal_at = deployment.created_at + timedelta(seconds=1)
    with owner_engine.begin() as connection:
        connection.execute(
            text("SELECT set_config('app.current_tenant', :tenant, true)"),
            {"tenant": seed["tenant"]},
        )
        connection.execute(
            text(
                "SELECT set_config("
                "'gda.gis_service_deployment_observation_allowed', '1', true)"
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO gda_control.framework_attempt_observation (
                    tenant_id, observation_id, run_id, attempt_no,
                    framework_kind, external_namespace, external_run_id,
                    external_attempt_id, observed_state, observation_sha256,
                    evidence, observed_at
                ) VALUES (
                    :tenant, :observation_id, :run_id, 91, 'cloud',
                    :namespace, :external_run_id, :external_attempt_id,
                    'ready', :observation_sha256, CAST(:evidence AS jsonb),
                    :observed_at
                )
                """
            ),
            {
                "tenant": seed["tenant"],
                "observation_id": observation_id,
                "run_id": deployment.run_id,
                "namespace": deployment.provider_namespace,
                "external_run_id": deployment.provider_deployment_id,
                "external_attempt_id": deployment.provider_revision_ref,
                "observation_sha256": canonical_json_fingerprint(evidence),
                "evidence": json.dumps(evidence, sort_keys=True),
                "observed_at": terminal_at,
            },
        )
        connection.execute(
            text(
                "SELECT set_config("
                "'gda.service_deployment_transition_allowed', '1', true)"
            )
        )
        connection.execute(
            text(
                """
                UPDATE gda_control.service_deployment_revision
                   SET state = 'ready', state_version = 1,
                       terminal_observation_id = :observation_id,
                       updated_at = :terminal_at, terminal_at = :terminal_at
                 WHERE tenant_id = :tenant
                   AND deployment_revision_id = :deployment_id
                """
            ),
            {
                "tenant": seed["tenant"],
                "deployment_id": deployment.deployment_revision_id,
                "observation_id": observation_id,
                "terminal_at": terminal_at,
            },
        )
    endpoint = _endpoint(
        seed,
        deployment,
        serving_projection,
        terminal_at + timedelta(seconds=1),
        suffix=suffix,
        endpoint_uri=endpoint_uri,
    )
    gateway.register_endpoint_revision(endpoint)
    return deployment, endpoint


def _register_warmup_definition(
    gateway: PlatformGateway,
    seed: dict[str, object],
    now: datetime,
) -> PlatformDefinitionVersion:
    tenant = str(seed["tenant"])
    definition_id = uuid4()
    definition_urn = f"gda://{tenant}/definition/gis-service-endpoint-warmup"
    definition_document = {
        "schema": "gda.gis_service_endpoint_warmup_definition.v1",
        "operation": "warmup_exact_endpoint_release",
    }
    input_contract = {
        "required_semantic_type": "gda.gis_service.warmup_source",
    }
    output_contract = {
        "receipt_schema": "gda.gis_service_endpoint_warmup_receipt.v1",
    }
    definition_sha256 = platform_definition_fingerprint(
        orchestration_class="dataops",
        capability_id="gis-service-endpoint-warmup",
        portability_class="engine_family",
        definition_document=definition_document,
        input_contract=input_contract,
        output_contract=output_contract,
    )
    definition = PlatformDefinitionVersion(
        tenant_id=tenant,
        definition_urn=definition_urn,
        definition_version_id=definition_id,
        orchestration_class="dataops",
        capability_id="gis-service-endpoint-warmup",
        portability_class="engine_family",
        definition_document=definition_document,
        input_contract=input_contract,
        output_contract=output_contract,
        definition_sha256=definition_sha256,
    )
    gateway.register_definition(
        DefinitionRegistration(
            resource=Resource(
                tenant_id=tenant,
                resource_urn=definition_urn,
                resource_kind="definition",
                authority_system="gis-service-control",
                authority_locator="platform-gateway",
                owner_ref="team:spatial-data",
            ),
            resource_version=ResourceVersion(
                tenant_id=tenant,
                resource_urn=definition_urn,
                resource_version_id=definition_id,
                version_key="v1.0.0",
                content_sha256=definition_sha256,
                authority_version_ref={"capability_id": definition.capability_id},
                created_by="workload:gis-warmup-controller",
                created_at=now,
            ),
            definition=definition,
        )
    )
    return definition


def _record_endpoint_warmup(
    gateway: PlatformGateway,
    login_engine: Engine,
    seed: dict[str, object],
    definition: GISServiceDefinitionVersion,
    release,
    cache_policy,
    deployment,
    endpoint,
    warmup_definition: PlatformDefinitionVersion,
    *,
    label: str,
) -> tuple[GISServiceEndpointWarmupReceipt, bool]:
    tenant = str(seed["tenant"])
    with login_engine.connect() as connection:
        database_now = connection.execute(text("SELECT clock_timestamp()" )).scalar_one()
    submitted_at = database_now - timedelta(seconds=2)
    started_at = database_now - timedelta(seconds=1)
    completed_at = database_now
    valid_until = completed_at + timedelta(
        seconds=cache_policy.cache_max_age_seconds
    )
    run_id = uuid4()
    warmup_id = uuid4()
    evidence_artifact_id = uuid4()
    recorder = "workload:gis-warmup-controller"
    sample_set = {
        "schema": "gda.gis_service_endpoint_warmup_samples.v1",
        "endpoint_revision_id": str(endpoint.endpoint_revision_id),
        "samples": [
            {"path": "/0/0/0.mvt", "status": 200},
            {"path": "/8/212/105.mvt", "status": 200},
            {"path": "/12/3391/1685.mvt", "status": 200},
            {"path": "/health/ready", "status": 200},
        ],
    }
    provider_receipt = {
        "schema": "gda.gis_service_endpoint_warmup_provider_receipt.v1",
        "provider_system": deployment.provider_system,
        "provider_revision_ref": deployment.provider_revision_ref,
        "endpoint_uri": endpoint.endpoint_uri,
        "sample_set": sample_set,
    }
    sample_set_sha256 = canonical_json_fingerprint(sample_set)
    provider_receipt_sha256 = canonical_json_fingerprint(provider_receipt)
    run = PlatformRun(
        tenant_id=tenant,
        run_id=run_id,
        definition_version_id=warmup_definition.definition_version_id,
        orchestration_class="dataops",
        subject_context=SubjectContext(
            tenant_id=tenant,
            subject_id="gis-warmup-controller",
            subject_type="workload",
            roles=("service_operator",),
            purpose="gis_service.endpoint_warmup",
        ),
        input_bindings=(
            ResourceBinding(
                binding_name="source_dataset",
                resource_version_id=UUID(str(seed["source_id"])),
                semantic_type="gda.data_product.source",
            ),
            ResourceBinding(
                binding_name="product_output",
                resource_version_id=UUID(str(seed["output_id"])),
                semantic_type="gda.gis_service.warmup_source",
            ),
        ),
        idempotency_key=f"gis-endpoint-warmup-{label}-{warmup_id}",
        submitted_at=submitted_at,
    )
    gateway.submit_run(run)
    gateway.transition_run(
        tenant,
        run_id,
        0,
        "dispatching",
        recorder,
        "warmup provider dispatch accepted",
    )
    gateway.transition_run(
        tenant,
        run_id,
        1,
        "running",
        recorder,
        "endpoint sample warmup running",
    )
    observation_evidence = {
        "schema": "gda.dolphinscheduler_observation.v1",
        "provider_state": "SUCCESS",
        "endpoint_revision_id": str(endpoint.endpoint_revision_id),
    }
    observation = FrameworkAttemptObservation(
        tenant_id=tenant,
        observation_id=uuid4(),
        run_id=run_id,
        attempt_no=1,
        framework_kind="dolphinscheduler",
        external_namespace="gis-service-endpoint-warmup",
        external_run_id=f"warmup-{label}-{run_id}",
        external_attempt_id="attempt-1",
        observed_state="success",
        observation_sha256=canonical_json_fingerprint(observation_evidence),
        evidence=observation_evidence,
        observed_at=completed_at,
    )
    gateway.record_attempt(observation)
    output_artifact = Artifact(
        tenant_id=tenant,
        artifact_id=uuid4(),
        artifact_key=f"warmup-output-{label}",
        artifact_role="output",
        storage_uri=f"s3://gis-warmup-cert/{label}/output.parquet",
        media_type="application/vnd.apache.parquet",
        content_sha256=str(seed["output_content_sha256"]),
        size_bytes=1024,
        run_id=run_id,
        resource_version_id=UUID(str(seed["output_id"])),
        manifest={"endpoint_revision_id": str(endpoint.endpoint_revision_id)},
        created_by=recorder,
        created_at=completed_at,
    )
    quality_evidence = Artifact(
        tenant_id=tenant,
        artifact_id=uuid4(),
        artifact_key=f"warmup-quality-{label}",
        artifact_role="evidence",
        storage_uri=f"s3://gis-warmup-cert/{label}/quality.json",
        media_type="application/json",
        content_sha256=("c" if label == "source" else "d") * 64,
        size_bytes=256,
        run_id=run_id,
        resource_version_id=UUID(str(seed["output_id"])),
        manifest={"all_samples_succeeded": True},
        created_by="workload:gis-warmup-quality-controller",
        created_at=completed_at,
    )
    warmup_evidence_values = {
        "tenant_id": tenant,
        "warmup_id": warmup_id,
        "service_urn": str(seed["service_urn"]),
        "endpoint_revision_id": endpoint.endpoint_revision_id,
        "deployment_revision_id": deployment.deployment_revision_id,
        "service_definition_version_id": definition.service_definition_version_id,
        "service_release_binding_id": release.service_release_binding_id,
        "cache_policy_version_id": cache_policy.cache_policy_version_id,
        "cache_namespace": cache_policy.cache_namespace,
        "run_id": run_id,
        "evidence_artifact_id": evidence_artifact_id,
        "requested_sample_count": 4,
        "successful_sample_count": 4,
        "sample_set_sha256": sample_set_sha256,
        "provider_receipt_sha256": provider_receipt_sha256,
        "started_at": started_at,
        "completed_at": completed_at,
        "valid_until": valid_until,
        "recorded_by": recorder,
    }
    warmup_evidence = Artifact(
        tenant_id=tenant,
        artifact_id=evidence_artifact_id,
        artifact_key=f"warmup-receipt-{label}",
        artifact_role="evidence",
        storage_uri=f"s3://gis-warmup-cert/{label}/provider-receipt.json",
        media_type="application/json",
        content_sha256=provider_receipt_sha256,
        size_bytes=512,
        run_id=run_id,
        manifest=gis_service_endpoint_warmup_artifact_manifest(
            warmup_evidence_values
        ),
        created_by=recorder,
        created_at=completed_at,
    )
    for artifact in (output_artifact, quality_evidence, warmup_evidence):
        gateway.record_artifact(artifact)
    quality_values = {
        "tenant_id": tenant,
        "run_id": run_id,
        "resource_version_id": UUID(str(seed["output_id"])),
        "rule_version_ref": "gis-endpoint-warmup:v1",
        "verdict": "passed",
        "metrics": {"requested": 4, "successful": 4},
        "evidence_artifact_id": quality_evidence.artifact_id,
        "evaluated_by": "workload:gis-warmup-quality-controller",
        "evaluated_at": completed_at,
    }
    quality = QualityResult(
        quality_result_id=uuid4(),
        **quality_values,
        result_sha256=quality_result_fingerprint(**quality_values),
    )
    gateway.record_quality_result(quality)
    lineage_facets = {
        "schema": "gda.gis_service_endpoint_warmup_lineage.v1",
        "endpoint_revision_id": str(endpoint.endpoint_revision_id),
    }
    lineage = LineageEvent(
        tenant_id=tenant,
        lineage_event_id=uuid4(),
        event_type="publish",
        source_resource_version_id=UUID(str(seed["source_id"])),
        target_resource_version_id=UUID(str(seed["output_id"])),
        producer=recorder,
        event_sha256=canonical_json_fingerprint(lineage_facets),
        run_id=run_id,
        definition_version_id=warmup_definition.definition_version_id,
        artifact_id=output_artifact.artifact_id,
        facets=lineage_facets,
        occurred_at=completed_at,
    )
    gateway.record_lineage(lineage)
    success_values = {
        "tenant_id": tenant,
        "run_id": run_id,
        "attempt_observation_id": observation.observation_id,
        "output_artifact_id": output_artifact.artifact_id,
        "quality_result_id": quality.quality_result_id,
        "lineage_event_id": lineage.lineage_event_id,
    }
    gateway.finalize_run_success(
        RunSuccessEvidence(
            **success_values,
            evidence_sha256=run_success_evidence_fingerprint(**success_values),
        ),
        expected_state_version=2,
        actor_subject=recorder,
        reason="all endpoint warmup samples succeeded",
    )
    with login_engine.connect() as connection:
        recorded_at = connection.execute(text("SELECT clock_timestamp()" )).scalar_one()
    receipt_values = {**warmup_evidence_values, "recorded_at": recorded_at}
    receipt = GISServiceEndpointWarmupReceipt(
        **receipt_values,
        warmup_sha256=gis_service_endpoint_warmup_fingerprint(receipt_values),
    )
    result = gateway.record_gis_service_endpoint_warmup(receipt)
    return receipt, result.created


def _sqlstate(exc: DBAPIError) -> str | None:
    original = getattr(exc, "orig", None)
    return getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)


def _list_gis_mvt_cache_purges(
    engine: Engine, tenant: str
) -> tuple[GISMVTCachePurgeTask, ...]:
    """Read the gateway-visible purge projection under an explicit tenant."""
    with engine.connect() as connection:
        with connection.begin():
            connection.exec_driver_sql("SET LOCAL ROLE gda_control_gateway")
            connection.execute(
                text("SELECT set_config('app.current_tenant', :tenant, true)"),
                {"tenant": tenant},
            )
            rows = connection.execute(
                text(
                    """
                    SELECT *
                      FROM gda_control.gis_mvt_cache_purge_outbox
                     WHERE tenant_id = :tenant
                     ORDER BY created_at, purge_task_id
                    """
                ),
                {"tenant": tenant},
            ).mappings()
            return tuple(GISMVTCachePurgeTask.model_validate(dict(row)) for row in rows)


def _certify_gis_mvt_cache_purge_security(
    engine: Engine, tenant: str
) -> dict[str, object]:
    with engine.connect() as connection:
        with connection.begin():
            connection.exec_driver_sql("SET LOCAL ROLE gda_control_gateway")
            connection.execute(
                text("SELECT set_config('app.current_tenant', :tenant, true)"),
                {"tenant": tenant},
            )
            privileges = connection.execute(
                text(
                    """
                    SELECT
                      has_table_privilege(
                        current_user,
                        'gda_control.gis_mvt_cache_purge_outbox', 'SELECT'
                      ),
                      has_table_privilege(
                        current_user,
                        'gda_control.gis_mvt_cache_purge_outbox', 'INSERT'
                      ),
                      has_function_privilege(
                        current_user,
                        'gda_control.claim_gis_mvt_cache_purges(text,text,text,integer,integer)',
                        'EXECUTE'
                      ),
                      has_function_privilege(
                        'public',
                        'gda_control.claim_gis_mvt_cache_purges(text,text,text,integer,integer)',
                        'EXECUTE'
                      )
                    """
                )
            ).one()
            try:
                with connection.begin_nested():
                    connection.execute(
                        text(
                            "INSERT INTO "
                            "gda_control.gis_mvt_cache_purge_outbox (tenant_id) "
                            "VALUES (:tenant)"
                        ),
                        {"tenant": tenant},
                    )
            except DBAPIError as exc:
                direct_insert_sqlstate = _sqlstate(exc)
            else:
                direct_insert_sqlstate = None
    with engine.connect() as connection:
        with connection.begin():
            connection.exec_driver_sql("SET LOCAL ROLE gda_control_gateway")
            connection.execute(
                text("SELECT set_config('app.current_tenant', 'other', true)")
            )
            cross_tenant_rows = connection.execute(
                text("SELECT count(*) FROM gda_control.gis_mvt_cache_purge_outbox")
            ).scalar_one()
    return {
        "gateway_privileges": [bool(value) for value in privileges],
        "direct_insert_sqlstate": direct_insert_sqlstate,
        "cross_tenant_rows": int(cross_tenant_rows),
    }


def certify(database_url: str, *, report_path: Path | None = None) -> dict[str, object]:
    source_url = make_url(database_url)
    admin = create_engine(source_url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    database = f"gda_gis_impact_cert_{uuid4().hex[:10]}"
    login_role = f"gda_gis_impact_login_{uuid4().hex[:10]}"
    password = uuid4().hex
    with admin.connect() as connection:
        connection.execute(
            text(f'CREATE ROLE "{login_role}" LOGIN PASSWORD :password'),
            {"password": password},
        )
        connection.execute(text(f'CREATE DATABASE "{database}"'))
    owner_engine = create_engine(source_url.set(database=database))
    login_engine = create_engine(
        source_url.set(username=login_role, password=password, database=database)
    )
    fixture_now = datetime(2026, 8, 21, 12, tzinfo=UTC)
    runtime_now = datetime.now(UTC).replace(microsecond=0) - timedelta(minutes=30)
    try:
        _bootstrap(owner_engine, login_role)
        source = _seed_authorities(owner_engine, fixture_now)
        gateway = PlatformGateway(login_engine)
        warmup_definition = _register_warmup_definition(
            gateway, source, fixture_now
        )
        source_definition = _definition(source, fixture_now)
        gateway.register_gis_service_definition_version(source_definition)
        source_bundle = _release_bundle(source, source_definition, fixture_now)
        for item, register in zip(
            source_bundle[:-1],
            (
                gateway.register_layer_definition_version,
                gateway.register_style_definition_version,
                gateway.register_tile_matrix_set_definition_version,
                gateway.register_cache_policy_version,
                gateway.register_mvt_serving_projection_version,
            ),
            strict=True,
        ):
            register(item)
        source_release = source_bundle[-1]
        gateway.register_service_release_binding(source_release)
        gateway.register_service_policy_binding(
            _service_policy(source, source_definition, source_release, fixture_now)
        )
        source_service_binding = _issue_source_service_binding(
            gateway,
            login_engine,
            source,
            source_definition,
            source_release.service_release_binding_id,
            runtime_now,
        )

        target = _seed_successor_product(
            owner_engine, source, fixture_now + timedelta(minutes=1)
        )
        target_definition = _target_definition(
            source_definition, target, fixture_now + timedelta(minutes=2)
        )
        gateway.register_gis_service_definition_version(target_definition)
        target_bundle = _release_bundle(
            target,
            target_definition,
            fixture_now + timedelta(minutes=2),
            layer_key="districts-v2",
        )
        for item, register in zip(
            target_bundle[:-1],
            (
                gateway.register_layer_definition_version,
                gateway.register_style_definition_version,
                gateway.register_tile_matrix_set_definition_version,
                gateway.register_cache_policy_version,
                gateway.register_mvt_serving_projection_version,
            ),
            strict=True,
        ):
            register(item)
        target_release = target_bundle[-1]
        gateway.register_service_release_binding(target_release)
        gateway.register_service_policy_binding(
            _service_policy(
                target,
                target_definition,
                target_release,
                fixture_now + timedelta(minutes=2),
            )
        )

        source_deployment, source_endpoint = _ready_endpoint_fixture(
            gateway,
            owner_engine,
            source,
            source_definition,
            source_release,
            source_bundle[-2],
            runtime_now,
            revision_key="r1",
            suffix="source",
            provider_revision_ref="deployment:migration-source",
        )
        target_deployment, target_endpoint = _ready_endpoint_fixture(
            gateway,
            owner_engine,
            target,
            target_definition,
            target_release,
            target_bundle[-2],
            runtime_now + timedelta(seconds=30),
            revision_key="r1",
            suffix="target",
            provider_revision_ref="deployment:migration-target",
        )
        source_projection = gateway.activate_gis_service_endpoint(
            str(source["tenant"]),
            str(source["service_urn"]),
            source_endpoint.endpoint_revision_id,
            expected_state_version=0,
            actor_subject="service:gis-migration-controller",
            reason="activate source release before migration",
            idempotency_key="activate-migration-source",
            occurred_at=runtime_now + timedelta(minutes=1),
        )

        product_binding, migration_state, notification = _product_migration(
            gateway, source, target, runtime_now + timedelta(minutes=1)
        )
        values = {
            "tenant_id": source["tenant"],
            "impact_id": uuid4(),
            "source_service_consumer_binding_id": (
                source_service_binding.service_consumer_binding_id
            ),
            "source_binding_sha256": source_service_binding.binding_sha256,
            "service_urn": source["service_urn"],
            "consumer_ref": product_binding.consumer_ref,
            "source_service_definition_version_id": (
                source_definition.service_definition_version_id
            ),
            "source_service_release_binding_id": (
                source_release.service_release_binding_id
            ),
            "target_service_definition_version_id": (
                target_definition.service_definition_version_id
            ),
            "target_service_release_binding_id": (
                target_release.service_release_binding_id
            ),
            "source_product_urn": source["product_urn"],
            "from_product_version_id": source["product_version_id"],
            "to_product_version_id": target["product_version_id"],
            "migration_state_id": migration_state.migration_state_id,
            "notification_id": notification.notification_id,
            "recorded_by": "service:gis-migration-impact-controller",
            "recorded_at": runtime_now + timedelta(minutes=2),
        }
        impact = GISServiceConsumerBindingMigrationImpact(
            **values,
            impact_sha256=gis_service_consumer_binding_migration_impact_fingerprint(
                values
            ),
        )
        first = gateway.record_gis_service_consumer_binding_migration_impact(impact)
        replay = gateway.record_gis_service_consumer_binding_migration_impact(impact)
        listed = gateway.list_gis_service_consumer_binding_migration_impacts(
            str(source["tenant"]), notification.notification_id
        )

        forged_values = impact.model_dump(mode="python", exclude={"impact_sha256"})
        forged_values["target_service_release_binding_id"] = uuid4()
        forged = GISServiceConsumerBindingMigrationImpact(
            **forged_values,
            impact_sha256=gis_service_consumer_binding_migration_impact_fingerprint(
                forged_values
            ),
        )
        try:
            gateway.record_gis_service_consumer_binding_migration_impact(forged)
        except PlatformGatewayError as exc:
            forged_lineage_error_code = exc.code
        else:
            forged_lineage_error_code = None

        drifted = impact.model_copy(update={"recorded_by": "service:other-controller"})
        try:
            gateway.record_gis_service_consumer_binding_migration_impact(drifted)
        except GatewayConflictError:
            identity_drift_rejected = True
        else:
            identity_drift_rejected = False

        def cutover_request(
            *,
            cutover_id=None,
            expected_state_version: int = 1,
            reason: str = "cut over acknowledged GIS service consumers",
            idempotency_key: str | None = None,
        ) -> GISServiceMigrationCutoverRequest:
            identity = cutover_id or uuid4()
            return GISServiceMigrationCutoverRequest(
                tenant_id=str(source["tenant"]),
                cutover_id=identity,
                service_urn=str(source["service_urn"]),
                source_endpoint_revision_id=source_endpoint.endpoint_revision_id,
                target_endpoint_revision_id=target_endpoint.endpoint_revision_id,
                source_service_definition_version_id=(
                    source_definition.service_definition_version_id
                ),
                source_service_release_binding_id=(
                    source_release.service_release_binding_id
                ),
                target_service_definition_version_id=(
                    target_definition.service_definition_version_id
                ),
                target_service_release_binding_id=(
                    target_release.service_release_binding_id
                ),
                source_product_urn=str(source["product_urn"]),
                from_product_version_id=UUID(str(source["product_version_id"])),
                to_product_version_id=UUID(str(target["product_version_id"])),
                expected_state_version=expected_state_version,
                actor_subject="service:gis-migration-controller",
                reason=reason,
                idempotency_key=idempotency_key or f"cutover-{identity}",
                occurred_at=datetime.now(UTC),
            )

        try:
            gateway.cutover_gis_service_migration(cutover_request())
        except GatewayValidationError:
            pending_acknowledgement_rejected = True
        else:
            pending_acknowledgement_rejected = False
        pending_projection = gateway.get_gis_service_control_projection(
            str(source["tenant"]), str(source["service_urn"])
        )

        claimed = gateway.claim_consumer_binding_migration_notifications(
            str(source["tenant"]),
            "worker:gis-migration-certifier",
            recorded_by="service:consumer-notification-worker",
            limit=1,
            lease_seconds=60,
        )
        if len(claimed) != 1:
            raise RuntimeError(f"expected one claimed notification, found {len(claimed)}")
        settlement = gateway.complete_consumer_binding_migration_notification(
            str(source["tenant"]),
            notification.notification_id,
            worker_id="worker:gis-migration-certifier",
            recorded_by="service:consumer-notification-worker",
            provider_receipt={
                "schema": "gda.alertmanager_provider_receipt.v1",
                "provider": "alertmanager",
                "accepted": True,
                "http_status": 202,
                "destination_ref": "alertmanager:consumer-binding-default",
                "provider_message_id": "gis-migration-impact-certification",
            },
        )
        if settlement.migration_state is None:
            raise RuntimeError("notification completion did not append migration state")
        delivered_state = settlement.migration_state
        acknowledged_at = datetime.now(UTC)
        acknowledged_values = delivered_state.model_dump(
            mode="python",
            exclude={
                "migration_state_id",
                "state_version",
                "consumer_acknowledgement",
                "previous_state_sha256",
                "recorded_by",
                "recorded_at",
                "state_sha256",
            },
        )
        acknowledged_values.update(
            migration_state_id=uuid4(),
            state_version=delivered_state.state_version + 1,
            consumer_acknowledgement={
                "consumer_ref": product_binding.consumer_ref,
                "acknowledgement_ref": "change:planner-api-v2-ready",
                "evidence": {
                    "schema": "gda.consumer_migration_acknowledgement.v1",
                    "target_service_release_binding_id": str(
                        target_release.service_release_binding_id
                    ),
                },
                "acknowledged_at": acknowledged_at,
            },
            previous_state_sha256=delivered_state.state_sha256,
            recorded_by=product_binding.consumer_ref,
            recorded_at=acknowledged_at,
        )
        acknowledged_state = ConsumerBindingMigrationState(
            **acknowledged_values,
            state_sha256=consumer_binding_migration_state_fingerprint(
                acknowledged_values
            ),
        )
        gateway.record_consumer_binding_migration_state(acknowledged_state)

        try:
            gateway.cutover_gis_service_migration(cutover_request())
        except GatewayValidationError:
            missing_target_binding_rejected = True
        else:
            missing_target_binding_rejected = False
        missing_target_projection = gateway.get_gis_service_control_projection(
            str(source["tenant"]), str(source["service_urn"])
        )

        target_service_binding = _issue_source_service_binding(
            gateway,
            login_engine,
            target,
            target_definition,
            target_release.service_release_binding_id,
            datetime.now(UTC),
            register_principal=False,
        )

        try:
            gateway.activate_gis_service_endpoint(
                str(source["tenant"]),
                str(source["service_urn"]),
                target_endpoint.endpoint_revision_id,
                expected_state_version=1,
                actor_subject="service:gis-migration-controller",
                reason="attempt generic cross-product activation",
                idempotency_key="generic-migration-bypass",
                occurred_at=datetime.now(UTC),
            )
        except PlatformGatewayError as exc:
            generic_activation_bypass_error_code = exc.code
        else:
            generic_activation_bypass_error_code = None
        bypass_projection = gateway.get_gis_service_control_projection(
            str(source["tenant"]), str(source["service_urn"])
        )

        final_request = cutover_request()
        stale_request = final_request.model_copy(update={"expected_state_version": 0})
        try:
            gateway.cutover_gis_service_migration(stale_request)
        except GatewayConflictError:
            stale_cutover_rejected = True
        else:
            stale_cutover_rejected = False

        try:
            gateway.cutover_gis_service_migration(final_request)
        except GatewayValidationError:
            missing_target_warmup_rejected = True
        else:
            missing_target_warmup_rejected = False
        missing_target_warmup_projection = (
            gateway.get_gis_service_control_projection(
                str(source["tenant"]), str(source["service_urn"])
            )
        )
        target_warmup, target_warmup_created = _record_endpoint_warmup(
            gateway,
            login_engine,
            target,
            target_definition,
            target_release,
            target_bundle[-3],
            target_deployment,
            target_endpoint,
            warmup_definition,
            label="target",
        )
        target_warmup_replay = gateway.record_gis_service_endpoint_warmup(
            target_warmup
        )
        listed_target_warmups = gateway.list_gis_service_endpoint_warmups(
            str(source["tenant"]),
            str(source["service_urn"]),
            target_endpoint.endpoint_revision_id,
        )
        drift_values = target_warmup.model_dump(
            mode="python", exclude={"warmup_sha256"}
        )
        drift_values["sample_set_sha256"] = "e" * 64
        drifted_warmup = GISServiceEndpointWarmupReceipt(
            **drift_values,
            warmup_sha256=gis_service_endpoint_warmup_fingerprint(
                drift_values
            ),
        )
        try:
            gateway.record_gis_service_endpoint_warmup(drifted_warmup)
        except GatewayConflictError:
            warmup_identity_drift_rejected = True
        else:
            warmup_identity_drift_rejected = False

        cutover = gateway.cutover_gis_service_migration(final_request)
        replay_cutover = gateway.cutover_gis_service_migration(final_request)
        cutover_projection = gateway.get_gis_service_control_projection(
            str(source["tenant"]), str(source["service_urn"])
        )
        listed_cutovers = gateway.list_gis_service_migration_cutovers(
            str(source["tenant"]), str(source["service_urn"])
        )

        # The transition receipt must enqueue exactly one durable purge task.
        # Exercise the worker lease lifecycle against the task created by the
        # real cutover transaction, including a retry before completion.
        purge_tasks_after_cutover = _list_gis_mvt_cache_purges(
            login_engine, str(source["tenant"])
        )
        cutover_purge_tasks = tuple(
            task
            for task in purge_tasks_after_cutover
            if task.source_kind.value == "cutover"
        )
        if len(cutover_purge_tasks) != 1:
            raise RuntimeError(
                "expected exactly one MVT purge task after cutover, found "
                f"{len(cutover_purge_tasks)}"
            )
        cutover_purge = cutover_purge_tasks[0]
        cutover_purge_generation_parity = (
            cutover_purge.generation_token is not None
            and cutover_purge.cache_context is not None
            and mvt_response_cache_namespace(cutover_purge.cache_context)
            == cutover_purge.generation_token
        )
        try:
            gateway.claim_gis_mvt_cache_purges(
                str(source["tenant"]),
                "worker:gis-mvt-purge-cert",
                actor_subject="workload:wrong-worker",
                limit=1,
                lease_seconds=60,
            )
        except GatewayForbiddenError:
            wrong_purge_workload_rejected = True
        else:
            wrong_purge_workload_rejected = False
        claimed_purges = gateway.claim_gis_mvt_cache_purges(
            str(source["tenant"]),
            "worker:gis-mvt-purge-cert",
            actor_subject=GIS_MVT_CACHE_PURGE_WORKLOAD,
            limit=1,
            lease_seconds=60,
        )
        if len(claimed_purges) != 1:
            raise RuntimeError(
                f"expected one claimed MVT purge task, found {len(claimed_purges)}"
            )
        retry_purge = gateway.fail_gis_mvt_cache_purge(
            str(source["tenant"]),
            cutover_purge.purge_task_id,
            worker_id="worker:gis-mvt-purge-cert",
            error="certified Redis outage",
            retry_delay_seconds=0,
        )
        reclaimed_purges = gateway.claim_gis_mvt_cache_purges(
            str(source["tenant"]),
            "worker:gis-mvt-purge-cert",
            actor_subject=GIS_MVT_CACHE_PURGE_WORKLOAD,
            limit=1,
            lease_seconds=60,
        )
        completed_purge = gateway.complete_gis_mvt_cache_purge(
            str(source["tenant"]),
            cutover_purge.purge_task_id,
            worker_id="worker:gis-mvt-purge-cert",
            matched_keys=2,
            deleted_keys=2,
            remaining_keys=0,
        )
        purge_tasks_after_cutover_settled = _list_gis_mvt_cache_purges(
            login_engine, str(source["tenant"])
        )
        drifted_request = final_request.model_copy(
            update={"reason": "different cutover reason"}
        )
        try:
            gateway.cutover_gis_service_migration(drifted_request)
        except GatewayConflictError:
            cutover_identity_drift_rejected = True
        else:
            cutover_identity_drift_rejected = False

        # A consumer that appears on the current target release after cutover
        # must also have an effective binding on the rollback release.
        late_consumer_ref = "workload:late-planner-api"
        _issue_source_service_binding(
            gateway,
            login_engine,
            target,
            target_definition,
            target_release.service_release_binding_id,
            datetime.now(UTC),
            register_principal=False,
            consumer_ref=late_consumer_ref,
        )

        def database_now() -> datetime:
            with login_engine.connect() as connection:
                return connection.execute(
                    text("SELECT clock_timestamp()")
                ).scalar_one()

        def rollback_request(
            *,
            rollback_id=None,
            expected_state_version: int = cutover.to_state_version,
            authorization_kind: str = "incident",
            authorization_ref: str | None = None,
            reason: str = "restore the certified GIS service release",
            idempotency_key: str | None = None,
        ) -> GISServiceMigrationRollbackRequest:
            identity = rollback_id or uuid4()
            return GISServiceMigrationRollbackRequest(
                tenant_id=str(source["tenant"]),
                rollback_id=identity,
                cutover_id=cutover.cutover_id,
                cutover_sha256=cutover.cutover_sha256,
                service_urn=str(source["service_urn"]),
                from_endpoint_revision_id=target_endpoint.endpoint_revision_id,
                to_endpoint_revision_id=source_endpoint.endpoint_revision_id,
                expected_state_version=expected_state_version,
                authorization_kind=authorization_kind,
                authorization_ref=authorization_ref or str(uuid4()),
                actor_subject="service:gis-migration-controller",
                reason=reason,
                idempotency_key=idempotency_key or f"rollback-{identity}",
                occurred_at=database_now(),
            )

        try:
            gateway.rollback_gis_service_migration(rollback_request())
        except GatewayValidationError:
            missing_rollback_binding_rejected = True
        else:
            missing_rollback_binding_rejected = False
        missing_rollback_projection = gateway.get_gis_service_control_projection(
            str(source["tenant"]), str(source["service_urn"])
        )

        _issue_source_service_binding(
            gateway,
            login_engine,
            source,
            source_definition,
            source_release.service_release_binding_id,
            datetime.now(UTC),
            register_principal=False,
            consumer_ref=late_consumer_ref,
        )

        try:
            gateway.rollback_gis_service_migration(rollback_request())
        except GatewayValidationError:
            missing_rollback_authority_rejected = True
        else:
            missing_rollback_authority_rejected = False

        wrong_incident = gateway.open_resource_incident(
            tenant_id=str(source["tenant"]),
            subject_resource_urn=str(source["product_urn"]),
            incident_id=uuid4(),
            dedupe_key=f"gis-rollback-wrong-subject-{uuid4().hex}",
            incident_type="gis_service.migration_failure",
            severity=IncidentSeverity.HIGH,
            summary="wrong rollback subject",
            details={"cutover_id": str(cutover.cutover_id)},
            detected_by="workload:gis-observer",
        ).value
        try:
            gateway.rollback_gis_service_migration(
                rollback_request(authorization_ref=str(wrong_incident.incident_id))
            )
        except GatewayValidationError:
            wrong_incident_subject_rejected = True
        else:
            wrong_incident_subject_rejected = False

        try:
            gateway.activate_gis_service_endpoint(
                str(source["tenant"]),
                str(source["service_urn"]),
                source_endpoint.endpoint_revision_id,
                expected_state_version=cutover.to_state_version,
                actor_subject="service:gis-migration-controller",
                reason="attempt generic migration rollback",
                idempotency_key="generic-rollback-bypass",
                occurred_at=datetime.now(UTC),
            )
        except PlatformGatewayError as exc:
            generic_rollback_bypass_error_code = exc.code
        else:
            generic_rollback_bypass_error_code = None

        stale_rollback = rollback_request(expected_state_version=1)
        try:
            gateway.rollback_gis_service_migration(stale_rollback)
        except GatewayConflictError:
            stale_rollback_rejected = True
        else:
            stale_rollback_rejected = False

        incident = gateway.open_resource_incident(
            tenant_id=str(source["tenant"]),
            subject_resource_urn=str(source["service_urn"]),
            incident_id=uuid4(),
            dedupe_key=f"gis-rollback-service-{uuid4().hex}",
            incident_type="gis_service.migration_failure",
            severity=IncidentSeverity.HIGH,
            summary="target GIS release failed after cutover",
            details={"cutover_id": str(cutover.cutover_id)},
            detected_by="workload:gis-observer",
        ).value
        try:
            gateway.rollback_gis_service_migration(
                rollback_request(authorization_ref=str(incident.incident_id))
            )
        except GatewayValidationError:
            missing_source_warmup_rejected = True
        else:
            missing_source_warmup_rejected = False
        missing_source_warmup_projection = (
            gateway.get_gis_service_control_projection(
                str(source["tenant"]), str(source["service_urn"])
            )
        )
        source_warmup, source_warmup_created = _record_endpoint_warmup(
            gateway,
            login_engine,
            source,
            source_definition,
            source_release,
            source_bundle[-3],
            source_deployment,
            source_endpoint,
            warmup_definition,
            label="source",
        )

        approval_seed = rollback_request(
            authorization_kind="approval_case",
            authorization_ref=(
                f"gda://{source['tenant']}/approval_case/"
                f"gis-rollback-{uuid4().hex}"
            ),
        )
        approval_context = gis_service_migration_rollback_approval_context(
            approval_seed
        )
        approval_operation_sha256 = (
            gis_service_migration_rollback_operation_fingerprint(approval_seed)
        )
        rollback_approval = ApprovalCase(
            tenant_id=str(source["tenant"]),
            approval_case_ref=approval_seed.authorization_ref,
            target_resource_urn=str(source["service_urn"]),
            target_fingerprint=approval_operation_sha256,
            action="gis_service_migration.rollback",
            requester_subject="workload:gis-migration-controller",
            request_reason="approve exact GIS migration rollback",
            request_context=approval_context,
            requested_at=database_now(),
            expires_at=database_now() + timedelta(hours=1),
        )
        approvals = ApprovalCaseAuthority(login_engine)
        approvals.create(rollback_approval, owner_ref="team:spatial-data")
        approvals.decide(
            tenant_id=str(source["tenant"]),
            approval_case_ref=rollback_approval.approval_case_ref,
            expected_state_version=0,
            verdict=ApprovalCaseStatus.APPROVED,
            actor_subject="human:service-owner",
            reason="approve exact rollback operation",
        )
        approval_request = approval_seed.model_copy(
            update={"occurred_at": database_now()}
        )
        with login_engine.connect() as connection:
            transaction = connection.begin()
            try:
                connection.exec_driver_sql("SET LOCAL ROLE gda_control_gateway")
                connection.execute(
                    text("SELECT set_config('app.current_tenant', :tenant, true)"),
                    {"tenant": source["tenant"]},
                )
                approval_rollback_row = (
                    connection.execute(
                        text(
                            """
                            SELECT *
                              FROM gda_control.rollback_gis_service_migration(
                                  :tenant_id, CAST(:rollback_id AS uuid),
                                  CAST(:cutover_id AS uuid), :cutover_sha256,
                                  :service_urn,
                                  CAST(:from_endpoint_revision_id AS uuid),
                                  CAST(:to_endpoint_revision_id AS uuid),
                                  :expected_state_version, :authorization_kind,
                                  :authorization_ref, :actor_subject, :reason,
                                  :idempotency_key, :occurred_at
                              )
                            """
                        ),
                        approval_request.model_dump(mode="python"),
                    )
                    .mappings()
                    .one()
                )
                approval_rollback = (
                    gateway._gis_service_migration_rollback_from_row(
                        approval_rollback_row
                    )
                )
                approval_rollback_succeeded = (
                    approval_rollback.authorization_kind == "approval_case"
                    and approval_rollback.authorization_ref
                    == rollback_approval.approval_case_ref
                    and approval_rollback.to_state_version
                    == cutover.to_state_version + 1
                )
            finally:
                transaction.rollback()

        final_rollback_request = rollback_request(
            authorization_ref=str(incident.incident_id)
        )
        rollback = gateway.rollback_gis_service_migration(
            final_rollback_request
        )
        replay_rollback = gateway.rollback_gis_service_migration(
            final_rollback_request
        )
        rollback_projection = gateway.get_gis_service_control_projection(
            str(source["tenant"]), str(source["service_urn"])
        )
        listed_rollbacks = gateway.list_gis_service_migration_rollbacks(
            str(source["tenant"]), str(source["service_urn"])
        )
        try:
            gateway.rollback_gis_service_migration(
                final_rollback_request.model_copy(
                    update={"reason": "different rollback reason"}
                )
            )
        except GatewayConflictError:
            rollback_identity_drift_rejected = True
        else:
            rollback_identity_drift_rejected = False

        purge_tasks_after_rollback = _list_gis_mvt_cache_purges(
            login_engine, str(source["tenant"])
        )
        rollback_purge_tasks = tuple(
            task
            for task in purge_tasks_after_rollback
            if task.source_kind.value == "rollback"
        )
        if len(rollback_purge_tasks) != 1:
            raise RuntimeError(
                "expected exactly one MVT purge task after rollback, found "
                f"{len(rollback_purge_tasks)}"
            )
        rollback_purge = rollback_purge_tasks[0]
        rollback_purge_generation_parity = (
            rollback_purge.generation_token is not None
            and rollback_purge.cache_context is not None
            and mvt_response_cache_namespace(rollback_purge.cache_context)
            == rollback_purge.generation_token
        )
        rollback_claimed = gateway.claim_gis_mvt_cache_purges(
            str(source["tenant"]),
            "worker:gis-mvt-purge-cert-rollback",
            actor_subject=GIS_MVT_CACHE_PURGE_WORKLOAD,
            limit=1,
            lease_seconds=60,
        )
        rollback_completed = gateway.complete_gis_mvt_cache_purge(
            str(source["tenant"]),
            rollback_purge.purge_task_id,
            worker_id="worker:gis-mvt-purge-cert-rollback",
            matched_keys=0,
            deleted_keys=0,
            remaining_keys=0,
        )
        purge_tasks_settled = _list_gis_mvt_cache_purges(
            login_engine, str(source["tenant"])
        )

        with login_engine.connect() as connection:
            with connection.begin():
                connection.exec_driver_sql("SET LOCAL ROLE gda_control_gateway")
                connection.execute(
                    text("SELECT set_config('app.current_tenant', :tenant, true)"),
                    {"tenant": source["tenant"]},
                )
                privileges = connection.execute(
                    text(
                        """
                        SELECT
                            has_table_privilege(
                                current_user,
                                'gda_control.gis_service_consumer_binding_migration_impact',
                                'SELECT'
                            ),
                            has_table_privilege(
                                current_user,
                                'gda_control.gis_service_consumer_binding_migration_impact',
                                'INSERT'
                            ),
                            has_function_privilege(
                                current_user,
                                'gda_control.record_gis_service_consumer_binding_migration_impact('
                                'text,uuid,uuid,character,text,text,uuid,uuid,uuid,uuid,text,'
                                'uuid,uuid,uuid,uuid,text,timestamptz,character)',
                                'EXECUTE'
                            )
                        """
                    )
                ).one()
                sql_fingerprint = connection.execute(
                    text(
                        """
                        SELECT gda_control.
                            gis_service_consumer_binding_migration_impact_fingerprint(
                            :tenant, CAST(:impact_id AS uuid),
                            CAST(:source_binding_id AS uuid), :source_binding_sha,
                            :service_urn, :consumer_ref,
                            CAST(:source_definition_id AS uuid),
                            CAST(:source_release_id AS uuid),
                            CAST(:target_definition_id AS uuid),
                            CAST(:target_release_id AS uuid), :product_urn,
                            CAST(:from_version_id AS uuid), CAST(:to_version_id AS uuid),
                            CAST(:migration_state_id AS uuid),
                            CAST(:notification_id AS uuid)
                        )
                        """
                    ),
                    {
                        "tenant": impact.tenant_id,
                        "impact_id": impact.impact_id,
                        "source_binding_id": impact.source_service_consumer_binding_id,
                        "source_binding_sha": impact.source_binding_sha256,
                        "service_urn": impact.service_urn,
                        "consumer_ref": impact.consumer_ref,
                        "source_definition_id": impact.source_service_definition_version_id,
                        "source_release_id": impact.source_service_release_binding_id,
                        "target_definition_id": impact.target_service_definition_version_id,
                        "target_release_id": impact.target_service_release_binding_id,
                        "product_urn": impact.source_product_urn,
                        "from_version_id": impact.from_product_version_id,
                        "to_version_id": impact.to_product_version_id,
                        "migration_state_id": impact.migration_state_id,
                        "notification_id": impact.notification_id,
                    },
                ).scalar_one()
                try:
                    with connection.begin_nested():
                        connection.execute(
                            text(
                                """
                                INSERT INTO gda_control
                                    .gis_service_consumer_binding_migration_impact (
                                    tenant_id, impact_id, source_service_consumer_binding_id,
                                    source_binding_sha256, service_urn, consumer_ref,
                                    source_service_definition_version_id,
                                    source_service_release_binding_id,
                                    target_service_definition_version_id,
                                    target_service_release_binding_id, source_product_urn,
                                    from_product_version_id, to_product_version_id,
                                    migration_state_id, notification_id, recorded_by,
                                    recorded_at, impact_sha256
                                ) SELECT tenant_id, gen_random_uuid(),
                                    source_service_consumer_binding_id, source_binding_sha256,
                                    service_urn, consumer_ref,
                                    source_service_definition_version_id,
                                    source_service_release_binding_id,
                                    target_service_definition_version_id,
                                    target_service_release_binding_id, source_product_urn,
                                    from_product_version_id, to_product_version_id,
                                    migration_state_id, notification_id, recorded_by,
                                    recorded_at, impact_sha256
                                  FROM gda_control.gis_service_consumer_binding_migration_impact
                                 WHERE impact_id = :impact_id
                                """
                            ),
                            {"impact_id": impact.impact_id},
                        )
                except DBAPIError as exc:
                    direct_insert_sqlstate = _sqlstate(exc)
                else:
                    direct_insert_sqlstate = None
                cutover_privileges = connection.execute(
                    text(
                        """
                        SELECT
                            has_table_privilege(
                                current_user,
                                'gda_control.gis_service_migration_cutover',
                                'SELECT'
                            ),
                            has_table_privilege(
                                current_user,
                                'gda_control.gis_service_migration_cutover',
                                'INSERT'
                            ),
                            has_function_privilege(
                                current_user,
                                'gda_control.cutover_gis_service_migration('
                                'text,uuid,text,uuid,uuid,uuid,uuid,uuid,uuid,text,'
                                'uuid,uuid,integer,text,text,text,timestamptz)',
                                'EXECUTE'
                            ),
                            has_function_privilege(
                                current_user,
                                'gda_control.activate_gis_service_endpoint_unverified('
                                'text,text,uuid,integer,text,text,text,timestamptz)',
                                'EXECUTE'
                            )
                        """
                    )
                ).one()
                cutover_sql_fingerprint = connection.execute(
                    text(
                        """
                        SELECT gda_control.gis_service_migration_cutover_fingerprint(
                            :tenant_id, CAST(:cutover_id AS uuid), :service_urn,
                            CAST(:source_endpoint_revision_id AS uuid),
                            CAST(:target_endpoint_revision_id AS uuid),
                            CAST(:source_service_definition_version_id AS uuid),
                            CAST(:source_service_release_binding_id AS uuid),
                            CAST(:target_service_definition_version_id AS uuid),
                            CAST(:target_service_release_binding_id AS uuid),
                            :source_product_urn,
                            CAST(:from_product_version_id AS uuid),
                            CAST(:to_product_version_id AS uuid),
                            :source_binding_count, :impact_count,
                            :acknowledged_count, :target_binding_count,
                            :impact_set_sha256, :acknowledgement_set_sha256,
                            :target_binding_set_sha256, :from_state_version,
                            :to_state_version, CAST(:activation_event_id AS uuid),
                            :cache_transition_mode, :actor_subject, :reason,
                            :idempotency_key, :occurred_at
                        )
                        """
                    ),
                    cutover.model_dump(
                        mode="python", exclude={"cutover_sha256"}
                    ),
                ).scalar_one()
                try:
                    with connection.begin_nested():
                        connection.execute(
                            text(
                                """
                                INSERT INTO gda_control.gis_service_migration_cutover
                                SELECT tenant_id, gen_random_uuid(), service_urn,
                                       source_endpoint_revision_id,
                                       target_endpoint_revision_id,
                                       source_service_definition_version_id,
                                       source_service_release_binding_id,
                                       target_service_definition_version_id,
                                       target_service_release_binding_id,
                                       source_product_urn, from_product_version_id,
                                       to_product_version_id, source_binding_count,
                                       impact_count, acknowledged_count,
                                       target_binding_count, impact_set_sha256,
                                       acknowledgement_set_sha256,
                                       target_binding_set_sha256, from_state_version,
                                       to_state_version, activation_event_id,
                                       cache_transition_mode, actor_subject, reason,
                                       idempotency_key || '-direct', occurred_at,
                                       cutover_sha256
                                  FROM gda_control.gis_service_migration_cutover
                                 WHERE cutover_id = :cutover_id
                                """
                            ),
                            {"cutover_id": cutover.cutover_id},
                        )
                except DBAPIError as exc:
                    direct_cutover_insert_sqlstate = _sqlstate(exc)
                else:
                    direct_cutover_insert_sqlstate = None
                rollback_privileges = connection.execute(
                    text(
                        """
                        SELECT
                            has_table_privilege(
                                current_user,
                                'gda_control.gis_service_migration_rollback',
                                'SELECT'
                            ),
                            has_table_privilege(
                                current_user,
                                'gda_control.gis_service_migration_rollback',
                                'INSERT'
                            ),
                            has_function_privilege(
                                current_user,
                                'gda_control.rollback_gis_service_migration('
                                'text,uuid,uuid,text,text,uuid,uuid,integer,text,text,'
                                'text,text,text,timestamptz)',
                                'EXECUTE'
                            ),
                            has_function_privilege(
                                current_user,
                                'gda_control.activate_gis_service_endpoint_unverified('
                                'text,text,uuid,integer,text,text,text,timestamptz)',
                                'EXECUTE'
                            )
                        """
                    )
                ).one()
                warmup_privileges = connection.execute(
                    text(
                        """
                        SELECT
                            has_table_privilege(
                                current_user,
                                'gda_control.gis_service_endpoint_warmup',
                                'SELECT'
                            ),
                            has_table_privilege(
                                current_user,
                                'gda_control.gis_service_endpoint_warmup',
                                'INSERT'
                            ),
                            has_function_privilege(
                                current_user,
                                'gda_control.record_gis_service_endpoint_warmup('
                                'text,uuid,text,uuid,uuid,uuid,uuid,uuid,text,uuid,uuid,'
                                'integer,integer,text,text,timestamptz,timestamptz,'
                                'timestamptz,text,timestamptz,text)',
                                'EXECUTE'
                            ),
                            has_function_privilege(
                                current_user,
                                'gda_control.gis_service_endpoint_warmup_fingerprint('
                                'text,uuid,text,uuid,uuid,uuid,uuid,uuid,text,uuid,uuid,'
                                'integer,integer,text,text,timestamptz,timestamptz,'
                                'timestamptz,text,timestamptz)',
                                'EXECUTE'
                            )
                        """
                    )
                ).one()
                warmup_sql_fingerprint = connection.execute(
                    text(
                        """
                        SELECT gda_control.gis_service_endpoint_warmup_fingerprint(
                            :tenant_id, CAST(:warmup_id AS uuid), :service_urn,
                            CAST(:endpoint_revision_id AS uuid),
                            CAST(:deployment_revision_id AS uuid),
                            CAST(:service_definition_version_id AS uuid),
                            CAST(:service_release_binding_id AS uuid),
                            CAST(:cache_policy_version_id AS uuid),
                            :cache_namespace, CAST(:run_id AS uuid),
                            CAST(:evidence_artifact_id AS uuid),
                            :requested_sample_count, :successful_sample_count,
                            :sample_set_sha256, :provider_receipt_sha256,
                            :started_at, :completed_at, :valid_until,
                            :recorded_by, :recorded_at
                        )
                        """
                    ),
                    target_warmup.model_dump(
                        mode="python", exclude={"warmup_sha256"}
                    ),
                ).scalar_one()
                try:
                    with connection.begin_nested():
                        connection.execute(
                            text(
                                """
                                INSERT INTO gda_control.gis_service_endpoint_warmup
                                SELECT tenant_id, gen_random_uuid(), service_urn,
                                       endpoint_revision_id,
                                       deployment_revision_id,
                                       service_definition_version_id,
                                       service_release_binding_id,
                                       cache_policy_version_id, cache_namespace,
                                       run_id, evidence_artifact_id,
                                       requested_sample_count,
                                       successful_sample_count,
                                       sample_set_sha256,
                                       provider_receipt_sha256, started_at,
                                       completed_at, valid_until, recorded_by,
                                       recorded_at, warmup_sha256
                                  FROM gda_control.gis_service_endpoint_warmup
                                 WHERE warmup_id = :warmup_id
                                """
                            ),
                            {"warmup_id": target_warmup.warmup_id},
                        )
                except DBAPIError as exc:
                    direct_warmup_insert_sqlstate = _sqlstate(exc)
                else:
                    direct_warmup_insert_sqlstate = None
                rollback_sql_fingerprint = connection.execute(
                    text(
                        """
                        SELECT gda_control.gis_service_migration_rollback_fingerprint(
                            :tenant_id, CAST(:rollback_id AS uuid),
                            CAST(:cutover_id AS uuid), :cutover_sha256,
                            :service_urn,
                            CAST(:from_endpoint_revision_id AS uuid),
                            CAST(:to_endpoint_revision_id AS uuid),
                            CAST(:from_service_definition_version_id AS uuid),
                            CAST(:from_service_release_binding_id AS uuid),
                            CAST(:to_service_definition_version_id AS uuid),
                            CAST(:to_service_release_binding_id AS uuid),
                            :source_product_urn,
                            CAST(:from_product_version_id AS uuid),
                            CAST(:to_product_version_id AS uuid),
                            :current_binding_count, :current_consumer_count,
                            :rollback_binding_count, :rollback_consumer_count,
                            :rollback_binding_set_sha256, :from_state_version,
                            :to_state_version, CAST(:activation_event_id AS uuid),
                            :cache_transition_mode, :authorization_kind,
                            :authorization_ref, :authorization_sha256,
                            :authorization_status,
                            :authorization_state_version, :actor_subject,
                            :reason, :idempotency_key, :occurred_at
                        )
                        """
                    ),
                    rollback.model_dump(
                        mode="python", exclude={"rollback_sha256"}
                    ),
                ).scalar_one()
                rollback_operation_sql_fingerprint = connection.execute(
                    text(
                        """
                        SELECT gda_control.
                            gis_service_migration_rollback_operation_fingerprint(
                                :tenant_id, :service_urn,
                                CAST(:cutover_id AS uuid), :cutover_sha256,
                                CAST(:from_endpoint_revision_id AS uuid),
                                CAST(:to_endpoint_revision_id AS uuid),
                                :expected_state_version
                            )
                        """
                    ),
                    approval_seed.model_dump(mode="python"),
                ).scalar_one()
                try:
                    with connection.begin_nested():
                        connection.execute(
                            text(
                                """
                                INSERT INTO gda_control.gis_service_migration_rollback
                                SELECT tenant_id, gen_random_uuid(), cutover_id,
                                       cutover_sha256, service_urn,
                                       from_endpoint_revision_id,
                                       to_endpoint_revision_id,
                                       from_service_definition_version_id,
                                       from_service_release_binding_id,
                                       to_service_definition_version_id,
                                       to_service_release_binding_id,
                                       source_product_urn, from_product_version_id,
                                       to_product_version_id,
                                       current_binding_count, current_consumer_count,
                                       rollback_binding_count,
                                       rollback_consumer_count,
                                       rollback_binding_set_sha256,
                                       from_state_version, to_state_version,
                                       activation_event_id,
                                       cache_transition_mode, authorization_kind,
                                       authorization_ref, authorization_sha256,
                                       authorization_status,
                                       authorization_state_version,
                                       actor_subject, reason,
                                       idempotency_key || '-direct', occurred_at,
                                       rollback_sha256
                                  FROM gda_control.gis_service_migration_rollback
                                 WHERE rollback_id = :rollback_id
                                """
                            ),
                            {"rollback_id": rollback.rollback_id},
                        )
                except DBAPIError as exc:
                    direct_rollback_insert_sqlstate = _sqlstate(exc)
                else:
                    direct_rollback_insert_sqlstate = None

        with login_engine.connect() as connection:
            with connection.begin():
                connection.exec_driver_sql("SET LOCAL ROLE gda_control_gateway")
                connection.execute(
                    text("SELECT set_config('app.current_tenant', 'other', true)")
                )
                cross_tenant_rows = connection.execute(
                    text(
                        "SELECT count(*) FROM "
                        "gda_control.gis_service_consumer_binding_migration_impact"
                    )
                ).scalar_one()
                cross_tenant_cutover_rows = connection.execute(
                    text(
                        "SELECT count(*) FROM "
                        "gda_control.gis_service_migration_cutover"
                    )
                ).scalar_one()
                cross_tenant_rollback_rows = connection.execute(
                    text(
                        "SELECT count(*) FROM "
                        "gda_control.gis_service_migration_rollback"
                    )
                ).scalar_one()
                cross_tenant_warmup_rows = connection.execute(
                    text(
                        "SELECT count(*) FROM "
                        "gda_control.gis_service_endpoint_warmup"
                    )
                ).scalar_one()

        with owner_engine.connect() as connection:
            transaction = connection.begin()
            try:
                connection.execute(
                    text(
                        "UPDATE gda_control.gis_service_consumer_binding_migration_impact "
                        "SET recorded_by = 'service:tamper' WHERE impact_id = :impact_id"
                    ),
                    {"impact_id": impact.impact_id},
                )
            except DBAPIError as exc:
                immutable_update_sqlstate = _sqlstate(exc)
                transaction.rollback()
            else:
                immutable_update_sqlstate = None
                transaction.rollback()

        with owner_engine.connect() as connection:
            transaction = connection.begin()
            try:
                connection.execute(
                    text(
                        "UPDATE gda_control.gis_service_migration_cutover "
                        "SET reason = 'tamper' WHERE cutover_id = :cutover_id"
                    ),
                    {"cutover_id": cutover.cutover_id},
                )
            except DBAPIError as exc:
                immutable_cutover_update_sqlstate = _sqlstate(exc)
                transaction.rollback()
            else:
                immutable_cutover_update_sqlstate = None
                transaction.rollback()

        with owner_engine.connect() as connection:
            transaction = connection.begin()
            try:
                connection.execute(
                    text(
                        "UPDATE gda_control.gis_service_migration_rollback "
                        "SET reason = 'tamper' WHERE rollback_id = :rollback_id"
                    ),
                    {"rollback_id": rollback.rollback_id},
                )
            except DBAPIError as exc:
                immutable_rollback_update_sqlstate = _sqlstate(exc)
                transaction.rollback()
            else:
                immutable_rollback_update_sqlstate = None
                transaction.rollback()

        with owner_engine.connect() as connection:
            transaction = connection.begin()
            try:
                connection.execute(
                    text(
                        "UPDATE gda_control.gis_service_endpoint_warmup "
                        "SET recorded_by = 'workload:tamper' "
                        "WHERE warmup_id = :warmup_id"
                    ),
                    {"warmup_id": target_warmup.warmup_id},
                )
            except DBAPIError as exc:
                immutable_warmup_update_sqlstate = _sqlstate(exc)
                transaction.rollback()
            else:
                immutable_warmup_update_sqlstate = None
                transaction.rollback()

        purge_security = _certify_gis_mvt_cache_purge_security(
            login_engine, str(source["tenant"])
        )

        report = {
            "schema": "gda.gis_service_endpoint_warmup_certification.v1",
            "status": "passed",
            "database": database,
            "catalog_count": len(discover_migrations()),
            "catalog_fingerprint": catalog_fingerprint(),
            "last_migration": discover_migrations()[-1].migration_id,
            "impact_id": str(impact.impact_id),
            "source_service_release_binding_id": str(
                impact.source_service_release_binding_id
            ),
            "target_service_release_binding_id": str(
                impact.target_service_release_binding_id
            ),
            "notification_id": str(notification.notification_id),
            "impact_sha256": impact.impact_sha256,
            "sql_fingerprint": sql_fingerprint,
            "fingerprint_parity": sql_fingerprint == impact.impact_sha256,
            "first_created": first.created,
            "replay_created": replay.created,
            "listed_count": len(listed),
            "forged_lineage_error_code": forged_lineage_error_code,
            "identity_drift_rejected": identity_drift_rejected,
            "gateway_privileges": list(privileges),
            "direct_insert_sqlstate": direct_insert_sqlstate,
            "immutable_update_sqlstate": immutable_update_sqlstate,
            "cross_tenant_rows": int(cross_tenant_rows),
            "source_endpoint_revision_id": str(source_endpoint.endpoint_revision_id),
            "target_endpoint_revision_id": str(target_endpoint.endpoint_revision_id),
            "source_state_version": source_projection.endpoint_state_version,
            "pending_acknowledgement_rejected": pending_acknowledgement_rejected,
            "missing_target_binding_rejected": missing_target_binding_rejected,
            "failed_gates_preserved_source": all(
                projection.active_endpoint_revision.endpoint_revision_id
                == source_endpoint.endpoint_revision_id
                for projection in (
                    pending_projection,
                    missing_target_projection,
                    bypass_projection,
                    missing_target_warmup_projection,
                )
            ),
            "claimed_impact_count": len(claimed[0].gis_service_impacts),
            "acknowledged_migration_state_id": str(
                acknowledged_state.migration_state_id
            ),
            "target_service_consumer_binding_id": str(
                target_service_binding.service_consumer_binding_id
            ),
            "generic_activation_bypass_error_code": (
                generic_activation_bypass_error_code
            ),
            "stale_cutover_rejected": stale_cutover_rejected,
            "missing_target_warmup_rejected": (
                missing_target_warmup_rejected
            ),
            "target_warmup": {
                "warmup_id": str(target_warmup.warmup_id),
                "run_id": str(target_warmup.run_id),
                "created": target_warmup_created,
                "replay_created": target_warmup_replay.created,
                "listed_count": len(listed_target_warmups),
                "identity_drift_rejected": warmup_identity_drift_rejected,
                "sql_fingerprint": warmup_sql_fingerprint,
                "fingerprint_parity": (
                    warmup_sql_fingerprint == target_warmup.warmup_sha256
                ),
            },
            "cutover_identity_drift_rejected": cutover_identity_drift_rejected,
            "cutover_id": str(cutover.cutover_id),
            "cutover_sha256": cutover.cutover_sha256,
            "cutover_sql_fingerprint": cutover_sql_fingerprint,
            "cutover_fingerprint_parity": (
                cutover_sql_fingerprint
                == gis_service_migration_cutover_fingerprint(cutover)
                == cutover.cutover_sha256
            ),
            "cutover_replay_equal": replay_cutover == cutover,
            "cutover_listed_count": len(listed_cutovers),
            "cutover_purge": {
                "task_id": str(cutover_purge.purge_task_id),
                "status_after_settlement": (
                    purge_tasks_after_cutover_settled[
                        next(
                            index
                            for index, task in enumerate(
                                purge_tasks_after_cutover_settled
                            )
                            if task.purge_task_id == cutover_purge.purge_task_id
                        )
                    ].status.value
                ),
                "generation_parity": cutover_purge_generation_parity,
                "retry_status": retry_purge.status.value,
                "reclaimed_count": len(reclaimed_purges),
                "wrong_workload_rejected": wrong_purge_workload_rejected,
                "completed": completed_purge.status.value == "done",
            },
            "cutover_counts": {
                "source": cutover.source_binding_count,
                "impact": cutover.impact_count,
                "acknowledged": cutover.acknowledged_count,
                "target": cutover.target_binding_count,
            },
            "target_active": (
                cutover_projection.active_endpoint_revision.endpoint_revision_id
                == target_endpoint.endpoint_revision_id
                and cutover_projection.endpoint_state_version == 2
            ),
            "cache_transition_mode": cutover.cache_transition_mode,
            "cutover_gateway_privileges": list(cutover_privileges),
            "direct_cutover_insert_sqlstate": direct_cutover_insert_sqlstate,
            "immutable_cutover_update_sqlstate": (
                immutable_cutover_update_sqlstate
            ),
            "cross_tenant_cutover_rows": int(cross_tenant_cutover_rows),
            "missing_rollback_binding_rejected": (
                missing_rollback_binding_rejected
            ),
            "failed_rollback_gate_preserved_target": (
                missing_rollback_projection.active_endpoint_revision
                .endpoint_revision_id
                == target_endpoint.endpoint_revision_id
                and missing_rollback_projection.endpoint_state_version
                == cutover.to_state_version
            ),
            "missing_rollback_authority_rejected": (
                missing_rollback_authority_rejected
            ),
            "wrong_incident_subject_rejected": wrong_incident_subject_rejected,
            "generic_rollback_bypass_error_code": (
                generic_rollback_bypass_error_code
            ),
            "stale_rollback_rejected": stale_rollback_rejected,
            "missing_source_warmup_rejected": (
                missing_source_warmup_rejected
            ),
            "failed_source_warmup_gate_preserved_target": (
                missing_source_warmup_projection.active_endpoint_revision
                .endpoint_revision_id
                == target_endpoint.endpoint_revision_id
                and missing_source_warmup_projection.endpoint_state_version
                == cutover.to_state_version
            ),
            "source_warmup": {
                "warmup_id": str(source_warmup.warmup_id),
                "run_id": str(source_warmup.run_id),
                "created": source_warmup_created,
            },
            "approval_operation_fingerprint_parity": (
                rollback_operation_sql_fingerprint
                == approval_operation_sha256
            ),
            "approval_rollback_succeeded_in_reverted_transaction": (
                approval_rollback_succeeded
            ),
            "rollback_id": str(rollback.rollback_id),
            "rollback_sha256": rollback.rollback_sha256,
            "rollback_sql_fingerprint": rollback_sql_fingerprint,
            "rollback_fingerprint_parity": (
                rollback_sql_fingerprint
                == gis_service_migration_rollback_fingerprint(rollback)
                == rollback.rollback_sha256
            ),
            "rollback_replay_equal": replay_rollback == rollback,
            "rollback_identity_drift_rejected": (
                rollback_identity_drift_rejected
            ),
            "rollback_listed_count": len(listed_rollbacks),
            "rollback_purge": {
                "task_id": str(rollback_purge.purge_task_id),
                "status_after_settlement": rollback_completed.status.value,
                "generation_parity": rollback_purge_generation_parity,
                "claimed_count": len(rollback_claimed),
                "completed": rollback_completed.status.value == "done",
                "settled_task_count": len(purge_tasks_settled),
            },
            "rollback_counts": {
                "current_bindings": rollback.current_binding_count,
                "current_consumers": rollback.current_consumer_count,
                "rollback_bindings": rollback.rollback_binding_count,
                "rollback_consumers": rollback.rollback_consumer_count,
            },
            "source_restored": (
                rollback_projection.active_endpoint_revision.endpoint_revision_id
                == source_endpoint.endpoint_revision_id
                and rollback_projection.endpoint_state_version
                == cutover.to_state_version + 1
            ),
            "rollback_authority": {
                "kind": rollback.authorization_kind,
                "ref": rollback.authorization_ref,
                "status": rollback.authorization_status,
            },
            "rollback_gateway_privileges": list(rollback_privileges),
            "direct_rollback_insert_sqlstate": (
                direct_rollback_insert_sqlstate
            ),
            "immutable_rollback_update_sqlstate": (
                immutable_rollback_update_sqlstate
            ),
            "cross_tenant_rollback_rows": int(cross_tenant_rollback_rows),
            "warmup_gateway_privileges": list(warmup_privileges),
            "direct_warmup_insert_sqlstate": direct_warmup_insert_sqlstate,
            "immutable_warmup_update_sqlstate": (
                immutable_warmup_update_sqlstate
            ),
            "cross_tenant_warmup_rows": int(cross_tenant_warmup_rows),
            "purge_security": purge_security,
        }
        if (
            not first.created
            or replay.created
            or len(listed) != 1
            or listed[0] != impact
            or sql_fingerprint != impact.impact_sha256
            or forged_lineage_error_code not in {
                "platform_not_found",
                "platform_validation_error",
            }
            or not identity_drift_rejected
            or tuple(privileges) != (True, False, True)
            or direct_insert_sqlstate != "42501"
            or immutable_update_sqlstate != "55000"
            or int(cross_tenant_rows) != 0
            or not pending_acknowledgement_rejected
            or not missing_target_binding_rejected
            or not report["failed_gates_preserved_source"]
            or report["claimed_impact_count"] != 1
            or generic_activation_bypass_error_code is None
            or not stale_cutover_rejected
            or not missing_target_warmup_rejected
            or not target_warmup_created
            or target_warmup_replay.created
            or len(listed_target_warmups) != 1
            or listed_target_warmups[0] != target_warmup
            or not warmup_identity_drift_rejected
            or not report["target_warmup"]["fingerprint_parity"]
            or not cutover_identity_drift_rejected
            or not report["cutover_fingerprint_parity"]
            or not report["cutover_replay_equal"]
            or len(listed_cutovers) != 1
            or not report["cutover_purge"]["generation_parity"]
            or report["cutover_purge"]["retry_status"] != "pending"
            or report["cutover_purge"]["reclaimed_count"] != 1
            or not report["cutover_purge"]["wrong_workload_rejected"]
            or not report["cutover_purge"]["completed"]
            or set(report["cutover_counts"].values()) != {1}
            or not report["target_active"]
            or cutover.cache_transition_mode != "release_namespace_rollover"
            or tuple(cutover_privileges) != (True, False, True, False)
            or direct_cutover_insert_sqlstate != "42501"
            or immutable_cutover_update_sqlstate != "55000"
            or int(cross_tenant_cutover_rows) != 0
            or not missing_rollback_binding_rejected
            or not report["failed_rollback_gate_preserved_target"]
            or not missing_rollback_authority_rejected
            or not wrong_incident_subject_rejected
            or generic_rollback_bypass_error_code is None
            or not stale_rollback_rejected
            or not missing_source_warmup_rejected
            or not report["failed_source_warmup_gate_preserved_target"]
            or not source_warmup_created
            or not report["approval_operation_fingerprint_parity"]
            or not approval_rollback_succeeded
            or not report["rollback_fingerprint_parity"]
            or not report["rollback_replay_equal"]
            or not rollback_identity_drift_rejected
            or len(listed_rollbacks) != 1
            or not report["rollback_purge"]["generation_parity"]
            or report["rollback_purge"]["claimed_count"] != 1
            or not report["rollback_purge"]["completed"]
            or report["rollback_purge"]["settled_task_count"] != 2
            or set(report["rollback_counts"].values()) != {2}
            or not report["source_restored"]
            or rollback.authorization_kind != "incident"
            or rollback.authorization_ref != str(incident.incident_id)
            or rollback.authorization_status != "open"
            or rollback.cache_transition_mode != "release_namespace_rollover"
            or tuple(rollback_privileges) != (True, False, True, False)
            or direct_rollback_insert_sqlstate != "42501"
            or immutable_rollback_update_sqlstate != "55000"
            or int(cross_tenant_rollback_rows) != 0
            or tuple(warmup_privileges) != (True, False, True, True)
            or direct_warmup_insert_sqlstate != "42501"
            or immutable_warmup_update_sqlstate != "55000"
            or int(cross_tenant_warmup_rows) != 0
            or purge_security["gateway_privileges"] != [True, False, True, False]
            or purge_security["direct_insert_sqlstate"] != "42501"
            or purge_security["cross_tenant_rows"] != 0
            or report["last_migration"]
            != "222_gis_mvt_cache_purge_outbox"
        ):
            report["status"] = "failed"
            raise RuntimeError(f"GIS service migration-impact certification failed: {report}")
        if report_path is not None:
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(
                json.dumps(report, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        return report
    finally:
        owner_engine.dispose()
        login_engine.dispose()
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)'))
            connection.execute(text(f'DROP ROLE IF EXISTS "{login_role}"'))
        admin.dispose()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--database-url",
        default="postgresql://postgres:postgres@127.0.0.1:5433/gis_agent",
    )
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    print(
        json.dumps(
            certify(args.database_url, report_path=args.report),
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
