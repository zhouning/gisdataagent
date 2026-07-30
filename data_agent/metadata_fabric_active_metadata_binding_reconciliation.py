"""Persist a scheduler-triggered Active Metadata provider binding.

M3-19 consumes the checked M3-18 execution evidence and reconciles the exact
real Chongqing projection through DolphinScheduler. An exact retained
OpenMetadata projection is mandatory. The only permitted provider repair is
recreating the missing Gravitino projection, followed by a mutation-free
read-back. The same transaction chain then records the content-bound provider
evidence and an immutable Metadata Fabric binding through PlatformGateway.

This remains a local Docker Desktop rehearsal. Provider and scheduler success
leave PlatformRun in ``reconciling`` and do not establish production identity,
terminal run evidence, or production ingestion.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

from pydantic import SecretStr
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from . import metadata_fabric_active_metadata_authorization as authorization
from . import metadata_fabric_active_metadata_projection_execution as execution
from . import metadata_fabric_active_metadata_scheduler_delivery as delivery
from . import metadata_fabric_bridge as bridge
from . import metadata_fabric_ingestion as ingestion
from . import metadata_fabric_ingestion_replay as replay
from . import metadata_fabric_provider_metrics as provider_metrics
from .active_metadata_authorization import build_metadata_activation_authorization
from .dolphinscheduler_adapter import (
    DOLPHINSCHEDULER_API_PROFILE,
    DOLPHINSCHEDULER_SERVER_VERSION,
    DolphinSchedulerAdapter,
    DolphinSchedulerClient,
    DolphinSchedulerDefinitionBinding,
    DolphinSchedulerProfile,
    DolphinSchedulerWorkflowSpec,
    build_dolphinscheduler_binding_artifact,
    compile_dolphinscheduler_workflow,
)
from .dolphinscheduler_command_consumer import DolphinSchedulerCommandConsumer
from .metadata_fabric_binding_contract import (
    ACTIVE_METADATA_PROJECTION_EVIDENCE_SCHEMA,
    MetadataFabricBindingRecord,
    build_metadata_fabric_binding_record,
    build_metadata_fabric_provider_evidence,
    build_metadata_fabric_provider_evidence_artifact,
)
from .platform_authorization import (
    build_approval_artifact,
    build_policy_decision_artifact,
)
from .platform_contracts import (
    ApprovalRecord,
    Artifact,
    PlatformDefinitionVersion,
    PlatformRun,
    PolicyDecision,
    Resource,
    ResourceVersion,
    RunPolicyReferences,
    RunStatus,
    SubjectContext,
    canonical_json_fingerprint,
    platform_definition_fingerprint,
)
from .platform_gateway import (
    DefinitionRegistration,
    GatewayNotFoundError,
    PlatformGateway,
)
from .spatial_dataset_bundle import validate_shapefile_bundle_inventory

CONTRACT_SCHEMA = "gda.active_metadata_binding_reconciliation_contract.v1"
EVIDENCE_SCHEMA = "gda.active_metadata_binding_reconciliation_evidence.v1"
REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE_EVIDENCE_PATH = execution.DEFAULT_EVIDENCE_PATH
DEFAULT_EVIDENCE_PATH = (
    REPO_ROOT
    / "docs/evidence/metadata-fabric-active-metadata-binding-reconciliation-2026-07-30.json"
)
DEFAULT_WRAPPER_PATH = (
    REPO_ROOT / "scripts/metadata-fabric-active-metadata-binding-reconciliation.sh"
)
TENANT = authorization.TENANT
SOURCE_ID = authorization.SOURCE_ID
DEFINITION_ID = UUID("a9000000-0000-4000-8000-000000000002")
RUN_ID = UUID("a9000000-0000-4000-8000-000000000003")
TASK_CODE = 180000000000002
WORKER = "worker:active-metadata-binding-reconciliation-1"
RUNNER = delivery.RUNNER
POLICY_EVALUATOR = delivery.POLICY_EVALUATOR
AUTHORIZER = delivery.AUTHORIZER
APPROVER = delivery.APPROVER
MIGRATIONS = tuple(
    Path(__file__).resolve().parent / "migrations" / filename
    for filename in (
        "092_platform_control_ledger.sql",
        "093_app_user_tenant_context.sql",
        "094_platform_control_gateway.sql",
        "095_platform_command_outbox.sql",
        "096_platform_success_verdict.sql",
        "097_metadata_fabric_binding_ledger.sql",
        "099_active_metadata_change_outbox.sql",
        "100_active_metadata_activation_request.sql",
        "101_active_metadata_authorization.sql",
    )
)
FALSE_CLAIMS = (
    "dataset_source_committed",
    "dataset_absolute_path_committed",
    "dataset_required_in_ci",
    "deployment_applied",
    "protected_workload_identity_verified",
    "provider_minimum_privilege_verified",
    "gravitino_authentication_verified",
    "durable_catalog_verified",
    "oidc_verified",
    "tls_verified",
    "live_openlineage_emission_verified",
    "production_scheduler_submission_verified",
    "production_ingestion_verified",
    "production_ready",
    "platform_run_succeeded",
)


class ActiveMetadataBindingReconciliationError(RuntimeError):
    """The scheduler-triggered binding reconciliation failed closed."""


@dataclass(frozen=True)
class BoundSource:
    resource: Resource
    version: ResourceVersion
    binding: bridge.MetadataFabricBinding


@dataclass(frozen=True)
class ProjectionDefinitionBundle:
    registration: DefinitionRegistration
    definition: PlatformDefinitionVersion
    workflow: DolphinSchedulerWorkflowSpec


@dataclass(frozen=True)
class ProjectionDispatchBundle:
    source_resource: Resource
    source_version: ResourceVersion
    request: Any
    registration: Any
    definition_registration: DefinitionRegistration
    dispatch_plan: Artifact
    dispatch_policy_decision: Artifact
    dispatch_approval: Artifact
    run: PlatformRun
    activation_authorization: Any


def _load_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ActiveMetadataBindingReconciliationError(
            f"{path.name} is not valid JSON"
        ) from exc
    if not isinstance(value, dict):
        raise ActiveMetadataBindingReconciliationError(
            f"{path.name} must contain an object"
        )
    return value


def _file_record(path: Path) -> dict[str, str | None]:
    resolved = path.resolve()
    return {
        "path": resolved.relative_to(REPO_ROOT).as_posix(),
        "sha256": hashlib.sha256(resolved.read_bytes()).hexdigest()
        if resolved.is_file()
        else None,
    }


def validate_source_evidence(source: dict[str, Any]) -> None:
    errors = execution.validate_rehearsal_evidence(source)
    if errors:
        raise ActiveMetadataBindingReconciliationError(
            "M3-18 projection execution evidence is invalid: " + ", ".join(errors)
        )
    if source.get("binding_persisted_to_gda_control") is not False:
        raise ActiveMetadataBindingReconciliationError(
            "M3-18 source must not already claim binding persistence"
        )
    first = source.get("first_apply")
    replayed = source.get("replay")
    if not isinstance(first, dict) or not isinstance(replayed, dict):
        raise ActiveMetadataBindingReconciliationError(
            "M3-18 provider observations are missing"
        )
    if (
        first.get("status") != "created"
        or first.get("mutation_count", 0) <= 0
        or replayed.get("status") != "no_op"
        or replayed.get("mutation_count") != 0
        or first.get("binding_candidate_sha256")
        != replayed.get("binding_candidate_sha256")
    ):
        raise ActiveMetadataBindingReconciliationError(
            "M3-18 source does not prove create plus zero-mutation replay"
        )


def build_bound_source(
    source: dict[str, Any],
    profile: replay.LocalIngestionProfile,
) -> BoundSource:
    validate_source_evidence(source)
    content_sha256 = str(source["resource_version_content_sha256"])
    base = authorization.build_authorization_bundle(content_sha256)
    first = source["first_apply"]
    open_observation = first["openmetadata"]
    gravitino_observation = first["gravitino"]
    openmetadata_ref = bridge.OpenMetadataTableRef(
        entity_id=UUID(open_observation["entity_id"]),
        fully_qualified_name=open_observation["fully_qualified_name"],
        entity_version=open_observation["entity_version"],
        server_version=profile.providers.openmetadata.version,
    )
    gravitino_ref = bridge.GravitinoTableRef(
        metalake=profile.targets.gravitino.metalake,
        catalog=profile.targets.gravitino.catalog,
        schema_name=profile.targets.gravitino.schema_name,
        table_name=profile.targets.gravitino.table,
        provider_revision=gravitino_observation["provider_revision"],
        server_version=profile.providers.gravitino.version,
    )
    expected_identity = (
        base.source_resource.resource_urn,
        str(base.registration.resource_version.resource_version_id),
        content_sha256,
    )
    for observation in (open_observation, gravitino_observation):
        if tuple(
            observation[key]
            for key in ("resource_urn", "resource_version_id", "content_sha256")
        ) != expected_identity:
            raise ActiveMetadataBindingReconciliationError(
                "M3-18 provider observation does not match the ResourceVersion"
            )
    if openmetadata_ref.fully_qualified_name != profile.targets.openmetadata.table_fqn:
        raise ActiveMetadataBindingReconciliationError(
            "M3-18 OpenMetadata target does not match the M3-19 profile"
        )
    if gravitino_ref.identity != gravitino_observation["identity"]:
        raise ActiveMetadataBindingReconciliationError(
            "M3-18 Gravitino target identity does not match"
        )
    resource = base.source_resource.model_copy(
        update={
            "governance_ref": bridge.openmetadata_governance_ref(openmetadata_ref),
            "technical_refs": (bridge.gravitino_technical_ref(gravitino_ref),),
        }
    )
    version = base.registration.resource_version
    binding = bridge.build_metadata_fabric_binding(
        resource,
        version,
        openmetadata=openmetadata_ref,
        gravitino=(gravitino_ref,),
    )
    if binding.binding_sha256 != first["binding_candidate_sha256"]:
        raise ActiveMetadataBindingReconciliationError(
            "M3-18 binding candidate does not match exact provider refs"
        )
    return BoundSource(resource=resource, version=version, binding=binding)


def build_projection_plan(
    content_sha256: str,
    profile: replay.LocalIngestionProfile,
) -> replay.LocalApplyPlan:
    resource_urn = f"gda://{TENANT}/dataset/chongqing-cultural-districts"
    common = {
        "resource_urn": resource_urn,
        "resource_version_id": str(SOURCE_ID),
        "content_sha256": content_sha256,
    }
    projections = (
        ingestion._projection(
            provider="openmetadata",
            target_identity=profile.targets.openmetadata.table_fqn,
            desired_state={
                **common,
                "owner_refs": ["team:data-platform"],
                "domain_refs": ["domain:natural-resources"],
                "tag_refs": [
                    "CulturalHeritage.CulturalDistrict",
                    "Sensitivity.Internal",
                ],
            },
        ),
        ingestion._projection(
            provider="gravitino",
            target_identity=profile.targets.gravitino.identity,
            desired_state={
                **common,
                "provider_revision": f"shapefile-bundle-{content_sha256[:16]}",
            },
        ),
    )
    source_plan_sha256 = canonical_json_fingerprint(
        {
            "schema": "gda.active_metadata_binding_reconciliation_intent.v1",
            "tenant_id": TENANT,
            "resource_urn": resource_urn,
            "resource_version_id": str(SOURCE_ID),
            "content_sha256": content_sha256,
            "source_execution_evidence_schema": execution.EVIDENCE_SCHEMA,
            "targets": [item.target_identity for item in projections],
        }
    )
    values: dict[str, Any] = {
        "source_plan_sha256": source_plan_sha256,
        "tenant_id": TENANT,
        "run_id": RUN_ID,
        "definition_version_id": DEFINITION_ID,
        "source_resource_version_id": SOURCE_ID,
        "resource_urn": resource_urn,
        "resource_version_id": SOURCE_ID,
        "content_sha256": content_sha256,
        "openmetadata_fqn": profile.targets.openmetadata.table_fqn,
        "gravitino_identity": profile.targets.gravitino.identity,
        "projections": projections,
    }
    stable = {
        "schema": replay.APPLY_PLAN_SCHEMA,
        **{
            key: (
                [item.model_dump(mode="json") for item in value]
                if key == "projections"
                else str(value)
                if isinstance(value, UUID)
                else value
            )
            for key, value in values.items()
        },
        "provider_apply_authorized": False,
        "writes_to_gda_control": False,
        "writes_to_legacy": False,
    }
    return replay.LocalApplyPlan(
        **values,
        apply_plan_sha256=canonical_json_fingerprint(stable),
    )


def _verify_retained_openmetadata(
    plan: replay.LocalApplyPlan,
    profile: replay.LocalIngestionProfile,
    payload: dict[str, Any],
    source_evidence: dict[str, Any],
    *,
    observed_at: datetime,
) -> bridge.OpenMetadataObservation:
    source = source_evidence["first_apply"]["openmetadata"]
    ref = bridge.OpenMetadataTableRef(
        entity_id=UUID(str(payload["id"])),
        fully_qualified_name=profile.targets.openmetadata.table_fqn,
        entity_version=str(payload["version"]),
        server_version=profile.providers.openmetadata.version,
    )
    observation = bridge.parse_openmetadata_table_observation(
        ref,
        payload,
        observed_at=observed_at,
    )
    projection = next(
        item for item in plan.projections if item.provider == "openmetadata"
    )
    desired = projection.desired_state
    exact_identity = (
        observation.resource_urn == plan.resource_urn
        and observation.resource_version_id == plan.resource_version_id
        and observation.content_sha256 == plan.content_sha256
        and sorted(observation.owner_refs) == desired["owner_refs"]
        and sorted(observation.domain_refs) == desired["domain_refs"]
        and sorted(observation.tag_refs) == desired["tag_refs"]
    )
    source_matches = (
        str(observation.ref.entity_id) == source["entity_id"]
        and observation.ref.fully_qualified_name == source["fully_qualified_name"]
        and observation.ref.entity_version == source["entity_version"]
        and observation.snapshot_sha256 == source["snapshot_sha256"]
    )
    if not exact_identity or not source_matches:
        raise ActiveMetadataBindingReconciliationError(
            "retained OpenMetadata projection drifted from M3-18 evidence"
        )
    return observation


def _reset_stale_empty_gravitino_memory_catalog(
    gravitino: replay.GravitinoApplyClient,
    target: replay.GravitinoTarget,
) -> bool:
    if target.catalog_backend != "memory":
        raise replay.MetadataFabricPartialProjectionError(
            "stale catalog reset is limited to the memory backend"
        )
    catalog_path = f"metalakes/{target.metalake}/catalogs/{target.catalog}"
    catalog_payload = gravitino._request("GET", catalog_path, allow_not_found=True)
    if catalog_payload is None:
        return False
    catalog = catalog_payload.get("catalog")
    if not isinstance(catalog, dict):
        raise replay.MetadataFabricPartialProjectionError(
            "Gravitino catalog read-back is incomplete"
        )
    properties = catalog.get("properties")
    expected_properties = {
        "catalog-backend": target.catalog_backend,
        "uri": target.uri,
        "warehouse": target.warehouse,
    }
    if (
        catalog.get("name") != target.catalog
        or str(catalog.get("type", "")).upper() != target.catalog_type
        or catalog.get("provider") != target.catalog_provider
        or not isinstance(properties, dict)
        or any(
            properties.get(key) != value
            for key, value in expected_properties.items()
        )
    ):
        raise replay.MetadataFabricPartialProjectionError(
            "Gravitino memory catalog configuration drifted"
        )
    schema_path = f"{catalog_path}/schemas/{target.schema_name}"
    if gravitino._request("GET", schema_path, allow_not_found=True) is not None:
        return False
    schema_listing = gravitino._request("GET", f"{catalog_path}/schemas")
    identifiers = None if schema_listing is None else schema_listing.get("identifiers")
    if identifiers != []:
        raise replay.MetadataFabricPartialProjectionError(
            "Gravitino memory catalog is not visibly empty"
        )
    gravitino._request("DELETE", catalog_path, params={"force": "true"})
    gravitino.mutations.append("gravitino.catalog.reset_stale_empty_memory")
    return True


def apply_or_repair_once(
    plan: replay.LocalApplyPlan,
    profile: replay.LocalIngestionProfile,
    apply_authorization: replay.ApplyAuthorizationBundle,
    run: PlatformRun,
    source_evidence: dict[str, Any],
    *,
    openmetadata: replay.OpenMetadataApplyClient,
    gravitino: replay.GravitinoApplyClient,
    at: datetime,
) -> replay.ApplyOutcome:
    replay.validate_apply_authorization(
        plan,
        run,
        apply_authorization,
        at=at,
    )
    openmetadata_before = openmetadata.get_table(
        profile.targets.openmetadata.table_fqn
    )
    gravitino_before = gravitino.get_table(profile.targets.gravitino)
    if openmetadata_before is None:
        raise replay.MetadataFabricPartialProjectionError(
            "M3-19 requires the exact retained M3-18 OpenMetadata projection"
        )
    retained = _verify_retained_openmetadata(
        plan,
        profile,
        openmetadata_before,
        source_evidence,
        observed_at=at,
    )
    if gravitino_before is not None:
        outcome = replay.apply_once(
            plan,
            profile,
            apply_authorization,
            run,
            openmetadata=openmetadata,
            gravitino=gravitino,
            at=at,
        )
        if outcome.binding_candidate_sha256 != source_evidence["first_apply"][
            "binding_candidate_sha256"
        ]:
            raise ActiveMetadataBindingReconciliationError(
                "retained provider binding drifted from M3-18 evidence"
            )
        return outcome

    start_om = len(openmetadata.mutations)
    start_gravitino = len(gravitino.mutations)
    try:
        _reset_stale_empty_gravitino_memory_catalog(
            gravitino,
            profile.targets.gravitino,
        )
        gravitino_payload = gravitino.apply(plan, profile.targets.gravitino)
        governance, technical, binding_sha256 = replay._verify_provider_state(
            plan,
            profile,
            openmetadata_before,
            gravitino_payload,
            observed_at=at,
        )
        mutations = (
            *openmetadata.mutations[start_om:],
            *gravitino.mutations[start_gravitino:],
        )
        if governance != retained:
            raise ActiveMetadataBindingReconciliationError(
                "OpenMetadata changed during technical projection repair"
            )
        if not mutations or any(
            not mutation.startswith("gravitino.") for mutation in mutations
        ):
            raise ActiveMetadataBindingReconciliationError(
                "partial projection repair must mutate only Gravitino"
            )
        if binding_sha256 != source_evidence["first_apply"][
            "binding_candidate_sha256"
        ]:
            raise ActiveMetadataBindingReconciliationError(
                "repaired provider binding does not match M3-18 evidence"
            )
    except Exception:
        try:
            gravitino.compensate()
        except Exception as compensation_exc:
            raise ActiveMetadataBindingReconciliationError(
                "Gravitino repair failed and compensation was incomplete"
            ) from compensation_exc
        raise
    return replay.ApplyOutcome(
        status=replay.ApplyStatus.CREATED,
        mutations=mutations,
        openmetadata=governance,
        gravitino=technical,
        binding_candidate_sha256=binding_sha256,
    )


class BindingReconciliationExecutor(execution.ProjectionExecutor):
    def __init__(self, *args: Any, source_evidence: dict[str, Any], **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.source_evidence = source_evidence

    def execute(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.request_count += 1
        try:
            observed = execution.ProjectionExecutionRequest.model_validate(payload)
            if observed != self.request:
                raise ActiveMetadataBindingReconciliationError(
                    "binding callback request does not match the compiled workflow"
                )
            if self.request_count != 1:
                raise ActiveMetadataBindingReconciliationError(
                    "binding executor accepts exactly one scheduler callback"
                )
            self.first = apply_or_repair_once(
                self.plan,
                self.profile,
                self.apply_authorization,
                self.run,
                self.source_evidence,
                openmetadata=self.openmetadata,
                gravitino=self.gravitino,
                at=datetime.now(UTC),
            )
            self.replayed = replay.apply_once(
                self.plan,
                self.profile,
                self.apply_authorization,
                self.run,
                openmetadata=self.openmetadata,
                gravitino=self.gravitino,
                at=datetime.now(UTC),
            )
            if self.replayed.status != replay.ApplyStatus.NO_OP or self.replayed.mutations:
                raise ActiveMetadataBindingReconciliationError(
                    "exact repaired provider replay performed duplicate mutations"
                )
            if self.first.binding_candidate_sha256 != self.replayed.binding_candidate_sha256:
                raise ActiveMetadataBindingReconciliationError(
                    "provider binding drifted across repair and replay"
                )
            return {
                "schema": "gda.active_metadata_binding_reconciliation_response.v1",
                "status": "reconciled_and_replayed",
                "request_sha256": self.request.request_sha256,
            }
        except Exception as exc:
            self.error_type = type(exc).__name__
            raise


def build_scheduler_definition(
    callback_url: str,
    request: execution.ProjectionExecutionRequest,
    *,
    created_at: datetime,
) -> ProjectionDefinitionBundle:
    definition_document = execution._workflow_document(callback_url, request)
    scheduler = definition_document["dolphinscheduler"]
    scheduler["name"] = "gda_active_metadata_binding_reconciliation_v1"
    scheduler["description"] = "Read back and persist an authorized provider binding"
    task = scheduler["task_definitions"][0]
    task["code"] = TASK_CODE
    task["name"] = "reconcile_active_metadata_binding"
    task["description"] = "Verify retained provider projections before binding commit"
    relation = scheduler["task_relations"][0]
    relation["postTaskCode"] = TASK_CODE
    definition_urn = f"gda://{TENANT}/definition/metadata-binding-reconciliation"
    input_contract = {
        "metadata_change": "gis.cultural_districts",
        "execution_request_sha256": request.request_sha256,
        "source_execution_evidence_schema": execution.EVIDENCE_SCHEMA,
    }
    output_contract = {
        "provider_projection_readback": True,
        "metadata_fabric_binding_commit": True,
        "platform_run_terminal_success": False,
    }
    definition_sha256 = platform_definition_fingerprint(
        orchestration_class="dataops",
        capability_id="metadata_fabric.projection_plan",
        portability_class="provider_native",
        definition_document=definition_document,
        input_contract=input_contract,
        output_contract=output_contract,
    )
    resource = Resource(
        tenant_id=TENANT,
        resource_urn=definition_urn,
        resource_kind="definition",
        authority_system="gda",
        authority_locator="definition/metadata-binding-reconciliation",
        owner_ref="team:metadata-platform",
    )
    resource_version = ResourceVersion(
        tenant_id=TENANT,
        resource_urn=definition_urn,
        resource_version_id=DEFINITION_ID,
        version_key="dolphinscheduler-3.4.2-local-binding-reconciliation-v1",
        content_sha256=definition_sha256,
        authority_version_ref={
            "api_profile": DOLPHINSCHEDULER_API_PROFILE,
            "server_version": DOLPHINSCHEDULER_SERVER_VERSION,
            "callback_transport": "docker_desktop_host_gateway_http",
        },
        created_by="workload:metadata-definition-registrar",
        created_at=created_at,
    )
    definition = PlatformDefinitionVersion(
        tenant_id=TENANT,
        definition_urn=definition_urn,
        definition_version_id=DEFINITION_ID,
        orchestration_class="dataops",
        capability_id="metadata_fabric.projection_plan",
        portability_class="provider_native",
        definition_document=definition_document,
        input_contract=input_contract,
        output_contract=output_contract,
        definition_sha256=definition_sha256,
    )
    return ProjectionDefinitionBundle(
        registration=DefinitionRegistration(
            resource=resource,
            resource_version=resource_version,
            definition=definition,
        ),
        definition=definition,
        workflow=compile_dolphinscheduler_workflow(definition),
    )


def build_dispatch_bundle(
    content_sha256: str,
    bound_source: BoundSource,
    definition_bundle: ProjectionDefinitionBundle,
    scheduler_binding: DolphinSchedulerDefinitionBinding,
    *,
    authorized_at: datetime,
) -> ProjectionDispatchBundle:
    base = authorization.build_authorization_bundle(content_sha256)
    if base.registration.resource_version != bound_source.version:
        raise ActiveMetadataBindingReconciliationError(
            "bound source version does not match the activation registration"
        )
    if scheduler_binding.definition_version_id != DEFINITION_ID:
        raise ActiveMetadataBindingReconciliationError(
            "DolphinScheduler binding does not match the reconciliation definition"
        )
    if scheduler_binding.compiled_sha256 != definition_bundle.workflow.compiled_sha256:
        raise ActiveMetadataBindingReconciliationError(
            "DolphinScheduler binding does not match the compiled workflow"
        )
    dispatch_plan = build_dolphinscheduler_binding_artifact(
        scheduler_binding,
        created_by=RUNNER,
        created_at=authorized_at - timedelta(seconds=3),
    )
    subject = SubjectContext(
        tenant_id=TENANT,
        subject_id=RUNNER.removeprefix("workload:"),
        subject_type="workload",
        roles=("metadata_projector",),
        purpose="reconcile and persist authorized active metadata binding",
    )
    decision = PolicyDecision(
        tenant_id=TENANT,
        run_id=RUN_ID,
        subject_context=subject,
        action="dolphinscheduler.dispatch",
        definition_version_id=DEFINITION_ID,
        resource_version_ids=(DEFINITION_ID, SOURCE_ID),
        execution_plan_artifact_id=dispatch_plan.artifact_id,
        effect="allow",
        policy_version_ref=f"gda://{TENANT}/policy/metadata-dispatch-v1",
        evaluator_subject=POLICY_EVALUATOR,
        requires_approval=True,
        decided_at=authorized_at - timedelta(seconds=3),
        expires_at=authorized_at + timedelta(days=365),
    )
    dispatch_policy = build_policy_decision_artifact(decision)
    dispatch_approval = build_approval_artifact(
        ApprovalRecord(
            tenant_id=TENANT,
            run_id=RUN_ID,
            definition_version_id=DEFINITION_ID,
            policy_decision_artifact_id=dispatch_policy.artifact_id,
            policy_decision_sha256=dispatch_policy.content_sha256,
            verdict="approved",
            approver_subject=APPROVER,
            reason="approved local scheduler-triggered binding reconciliation",
            decided_at=authorized_at - timedelta(seconds=2),
            expires_at=authorized_at + timedelta(days=180),
        )
    )
    run = PlatformRun(
        tenant_id=TENANT,
        run_id=RUN_ID,
        definition_version_id=DEFINITION_ID,
        orchestration_class="dataops",
        subject_context=subject,
        input_bindings=(
            {
                "binding_name": "metadata_change",
                "resource_version_id": SOURCE_ID,
                "semantic_type": "gis.cultural_districts",
            },
        ),
        idempotency_key="metadata-binding:cultural-districts:reconcile:v1",
        policy_refs=RunPolicyReferences(
            policy_decision_artifact_id=dispatch_policy.artifact_id,
            approval_artifact_id=dispatch_approval.artifact_id,
        ),
        submitted_at=authorized_at - timedelta(seconds=1),
    )
    activation = build_metadata_activation_authorization(
        base.request,
        bound_source.version,
        definition_bundle.definition,
        run,
        dispatch_plan,
        dispatch_policy,
        dispatch_approval,
        authorized_by=AUTHORIZER,
        authorized_at=authorized_at,
    )
    return ProjectionDispatchBundle(
        source_resource=bound_source.resource,
        source_version=bound_source.version,
        request=base.request,
        registration=base.registration,
        definition_registration=definition_bundle.registration,
        dispatch_plan=dispatch_plan,
        dispatch_policy_decision=dispatch_policy,
        dispatch_approval=dispatch_approval,
        run=run,
        activation_authorization=activation,
    )


def _apply_migrations(engine: Any) -> None:
    with engine.begin() as connection:
        is_superuser = connection.exec_driver_sql(
            "SELECT rolsuper FROM pg_roles WHERE rolname = current_user"
        ).scalar_one()
        if not is_superuser:
            raise ActiveMetadataBindingReconciliationError(
                "local reconciliation requires a fresh superuser database"
            )
        connection.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS agent_app_users (
                id SERIAL PRIMARY KEY,
                username VARCHAR(100) UNIQUE NOT NULL
            )
            """
        )
        for migration in MIGRATIONS:
            connection.execute(text(migration.read_text(encoding="utf-8")))


def _register_control_chain(
    gateway: PlatformGateway,
    bundle: ProjectionDispatchBundle,
    apply_authorization: replay.ApplyAuthorizationBundle,
) -> None:
    gateway.register_resource(bundle.source_resource)
    gateway.register_resource_version_with_metadata_event(bundle.registration)
    claimed = gateway.claim_metadata_changes(
        TENANT,
        WORKER,
        consumer_subject=authorization.CONSUMER_SUBJECT,
    )
    if len(claimed) != 1:
        raise ActiveMetadataBindingReconciliationError(
            "expected exactly one Active Metadata change"
        )
    gateway.stage_metadata_activation_request(
        TENANT,
        claimed[0].event.event_id,
        worker_id=WORKER,
        request=bundle.request,
    )
    gateway.register_definition(bundle.definition_registration)
    for artifact in (
        bundle.dispatch_plan,
        bundle.dispatch_policy_decision,
        bundle.dispatch_approval,
        apply_authorization.execution_plan_artifact,
        apply_authorization.policy_decision_artifact,
        apply_authorization.approval_artifact,
    ):
        gateway.record_artifact(artifact)
    gateway.submit_run(bundle.run)


def _direct_binding_mutations_blocked(
    gateway: PlatformGateway,
    record: MetadataFabricBindingRecord,
) -> tuple[bool, bool]:
    results: list[bool] = []
    with gateway._transaction(record.tenant_id) as connection:
        for statement in (
            """
            UPDATE gda_control.metadata_fabric_binding
            SET recorded_by = 'workload:tamper'
            WHERE tenant_id = :tenant_id AND binding_id = :binding_id
            """,
            """
            DELETE FROM gda_control.metadata_fabric_binding
            WHERE tenant_id = :tenant_id AND binding_id = :binding_id
            """,
        ):
            blocked = False
            try:
                with connection.begin_nested():
                    connection.execute(
                        text(statement),
                        {
                            "tenant_id": record.tenant_id,
                            "binding_id": record.binding_id,
                        },
                    )
            except DBAPIError:
                blocked = True
            results.append(blocked)
    return results[0], results[1]


def _attempt_summary(engine: Any) -> tuple[int, int, int, int, list[str]]:
    with engine.connect() as connection:
        row = connection.execute(
            text(
                """
                SELECT
                    count(*) AS total,
                    count(DISTINCT external_namespace || ':' || external_run_id)
                        AS correlations,
                    count(*) FILTER (WHERE observed_state = 'submitted') AS submitted,
                    count(*) FILTER (WHERE observed_state = 'success') AS succeeded,
                    array_agg(observed_state ORDER BY observed_at, observation_id)
                        AS states
                FROM gda_control.framework_attempt_observation
                WHERE tenant_id = :tenant_id AND run_id = :run_id
                """
            ),
            {"tenant_id": TENANT, "run_id": RUN_ID},
        ).one()
    return row.total, row.correlations, row.submitted, row.succeeded, list(row.states)


def _binding_ledger_state(
    engine: Any,
    record: MetadataFabricBindingRecord,
) -> tuple[int, bool, bool]:
    with engine.connect() as connection:
        count = connection.execute(
            text(
                """
                SELECT count(*)
                FROM gda_control.metadata_fabric_binding
                WHERE tenant_id = :tenant_id AND resource_version_id = :version_id
                """
            ),
            {
                "tenant_id": record.tenant_id,
                "version_id": record.binding.resource_version_id,
            },
        ).scalar_one()
        append_only = connection.exec_driver_sql(
            """
            SELECT NOT has_table_privilege(
                       'gda_control_gateway',
                       'gda_control.metadata_fabric_binding', 'UPDATE'
                   )
                   AND NOT has_table_privilege(
                       'gda_control_gateway',
                       'gda_control.metadata_fabric_binding', 'DELETE'
                   )
            """
        ).scalar_one()
        force_rls = connection.exec_driver_sql(
            """
            SELECT relforcerowsecurity
            FROM pg_class
            WHERE oid = 'gda_control.metadata_fabric_binding'::regclass
            """
        ).scalar_one()
    return int(count), bool(append_only), bool(force_rls)


def run_scheduler_binding_reconciliation(
    database_url: str,
    scheduler_profile: DolphinSchedulerProfile,
    source_evidence: dict[str, Any],
    projection_profile: replay.LocalIngestionProfile,
    runtime_identity: dict[str, Any],
    principal: dict[str, Any],
    gravitino_version: str,
    openmetadata: replay.OpenMetadataApplyClient,
    gravitino: replay.GravitinoApplyClient,
    callback_server: execution.ProjectionExecutionServer,
    *,
    terminal_timeout_seconds: float = 600,
) -> dict[str, Any]:
    validate_source_evidence(source_evidence)
    dataset = source_evidence["dataset_bundle"]
    if validate_shapefile_bundle_inventory(dataset):
        raise ActiveMetadataBindingReconciliationError(
            "real Chongqing dataset bundle inventory is invalid"
        )
    if scheduler_profile.workload_subject != RUNNER:
        raise ActiveMetadataBindingReconciliationError(
            "scheduler workload does not match the authorized runner"
        )
    if scheduler_profile.policy_evaluator_subject != POLICY_EVALUATOR:
        raise ActiveMetadataBindingReconciliationError(
            "scheduler evaluator does not match policy evidence"
        )

    started_at = datetime.now(UTC)
    bound_source = build_bound_source(source_evidence, projection_profile)
    plan = build_projection_plan(dataset["content_sha256"], projection_profile)
    request = execution.build_execution_request(plan)
    if callback_server.request != request:
        raise ActiveMetadataBindingReconciliationError(
            "callback server is not bound to the exact reconciliation request"
        )
    definition_bundle = build_scheduler_definition(
        callback_server.callback_url,
        request,
        created_at=started_at,
    )
    engine = create_engine(database_url)
    client = DolphinSchedulerClient(scheduler_profile)
    try:
        scheduler_binding = client.create_workflow(definition_bundle.workflow)
        authorized_at = datetime.now(UTC)
        bundle = build_dispatch_bundle(
            dataset["content_sha256"],
            bound_source,
            definition_bundle,
            scheduler_binding,
            authorized_at=authorized_at,
        )
        apply_authorization = execution.build_provider_apply_authorization(
            plan,
            bundle.run,
            projection_profile,
        )
        callback_server.executor = BindingReconciliationExecutor(
            request,
            projection_profile,
            plan,
            bundle.run,
            apply_authorization,
            source_evidence=source_evidence,
            openmetadata=openmetadata,
            gravitino=gravitino,
        )
        _apply_migrations(engine)
        gateway = PlatformGateway(engine)
        _register_control_chain(gateway, bundle, apply_authorization)
        first_auth = gateway.authorize_metadata_activation(
            bundle.activation_authorization
        )
        replay_auth = gateway.authorize_metadata_activation(
            bundle.activation_authorization
        )
        callback_server.start()

        adapter = DolphinSchedulerAdapter(
            scheduler_profile,
            gateway=gateway,
            client=client,
            clock=lambda: authorized_at,
        )
        consumer_result = DolphinSchedulerCommandConsumer(
            adapter,
            gateway=gateway,
        ).run_once(TENANT, worker_id=WORKER, limit=1, lease_seconds=600)
        if consumer_result.completed != 1:
            raise ActiveMetadataBindingReconciliationError(
                "authorized binding reconciliation command was not completed"
            )
        command = gateway.get_command(
            TENANT,
            bundle.activation_authorization.command_id,
        )
        with engine.connect() as connection:
            instance_id = int(
                connection.execute(
                    text(
                        """
                        SELECT external_run_id
                        FROM gda_control.framework_attempt_observation
                        WHERE tenant_id = :tenant_id
                          AND run_id = :run_id
                          AND observed_state = 'submitted'
                        """
                    ),
                    {"tenant_id": TENANT, "run_id": RUN_ID},
                ).scalar_one()
            )
        terminal = delivery._wait_for_terminal_instance(
            client,
            instance_id,
            scheduler_binding.workflow_definition_code,
            timeout_seconds=terminal_timeout_seconds,
        )
        variables = client.get_instance_variables(instance_id)
        expected_variables = {
            str(item["prop"]): str(item["value"])
            for item in definition_bundle.workflow.global_params
        }
        expected_variables.update(DolphinSchedulerClient.start_params(bundle.run))
        matching_instances = client.find_instances(scheduler_binding, bundle.run)
        reconciled = adapter.reconcile(
            TENANT,
            RUN_ID,
            bundle.dispatch_plan.artifact_id,
            actor_subject=RUNNER,
            attempt_no=1,
        )
        attempts = _attempt_summary(engine)
        executor = callback_server.executor
        if executor is None or executor.first is None or executor.replayed is None:
            raise ActiveMetadataBindingReconciliationError(
                "scheduler callback did not produce both provider read-backs: "
                f"request_count={0 if executor is None else executor.request_count}, "
                f"error_type={None if executor is None else executor.error_type}, "
                f"first_present={False if executor is None else executor.first is not None}, "
                "replay_present="
                f"{False if executor is None else executor.replayed is not None}"
            )
        first_outcome = replay._outcome_evidence(executor.first)
        replay_outcome = replay._outcome_evidence(executor.replayed)
        live_binding = bridge.build_metadata_fabric_binding(
            bound_source.resource,
            bound_source.version,
            openmetadata=executor.first.openmetadata.ref,
            gravitino=(executor.first.gravitino.ref,),
        )
        observed_at = max(
            executor.first.openmetadata.observed_at,
            executor.first.gravitino.observed_at,
        )
        provider_evidence = build_metadata_fabric_provider_evidence(
            binding=live_binding,
            source_evidence_schema=ACTIVE_METADATA_PROJECTION_EVIDENCE_SCHEMA,
            source_evidence_sha256=source_evidence["evidence_sha256"],
            openmetadata_snapshot_sha256=(executor.first.openmetadata.snapshot_sha256),
            gravitino_snapshot_sha256=executor.first.gravitino.snapshot_sha256,
            first_apply_status=executor.first.status.value,
            first_apply_mutation_count=len(executor.first.mutations),
            observed_at=observed_at,
        )
        provider_artifact = build_metadata_fabric_provider_evidence_artifact(
            provider_evidence,
            created_by=RUNNER,
        )
        record = build_metadata_fabric_binding_record(
            binding=live_binding,
            execution_plan_artifact_id=(
                apply_authorization.execution_plan_artifact.artifact_id
            ),
            policy_decision_artifact_id=(
                apply_authorization.policy_decision_artifact.artifact_id
            ),
            approval_artifact_id=apply_authorization.approval_artifact.artifact_id,
            provider_evidence_artifact_id=provider_artifact.artifact_id,
            recorded_by=RUNNER,
            recorded_at=datetime.now(UTC),
        )
        gateway.record_artifact(provider_artifact)
        first_commit = gateway.commit_metadata_fabric_binding(record)
        replay_commit = gateway.commit_metadata_fabric_binding(record)
        stored = gateway.get_metadata_fabric_binding(TENANT, SOURCE_ID)
        cross_tenant_read_blocked = False
        try:
            gateway.get_metadata_fabric_binding("isolated-tenant", SOURCE_ID)
        except GatewayNotFoundError:
            cross_tenant_read_blocked = True
        update_blocked, delete_blocked = _direct_binding_mutations_blocked(
            gateway,
            record,
        )
        binding_count, append_only, force_rls = _binding_ledger_state(engine, record)
        final_run = gateway.get_run(TENANT, RUN_ID)

        verified = (
            first_auth.created
            and not replay_auth.created
            and command.status.value == "done"
            and consumer_result.claimed == consumer_result.completed == 1
            and terminal.state.upper() == "SUCCESS"
            and variables == expected_variables
            and len(matching_instances) == 1
            and matching_instances[0].instance_id == instance_id
            and reconciled.provider_state == "SUCCESS"
            and attempts[:4] == (2, 1, 1, 1)
            and attempts[4] == ["submitted", "success"]
            and final_run.status == RunStatus.RECONCILING
            and executor.request_count == 1
            and first_outcome["status"] in {"created", "no_op"}
            and (
                (
                    first_outcome["status"] == "created"
                    and first_outcome["mutation_count"] > 0
                    and all(
                        mutation.startswith("gravitino.")
                        for mutation in first_outcome["mutations"]
                    )
                )
                or (
                    first_outcome["status"] == "no_op"
                    and first_outcome["mutation_count"] == 0
                )
            )
            and replay_outcome["status"] == "no_op"
            and replay_outcome["mutation_count"] == 0
            and first_outcome["binding_candidate_sha256"]
            == replay_outcome["binding_candidate_sha256"]
            == live_binding.binding_sha256
            == bound_source.binding.binding_sha256
            and first_commit.created
            and not replay_commit.created
            and first_commit.value == replay_commit.value == stored == record
            and binding_count == 1
            and cross_tenant_read_blocked
            and update_blocked
            and delete_blocked
            and append_only
            and force_rls
        )
        contract = build_contract_report()
        stable = {
            "schema": EVIDENCE_SCHEMA,
            "status": (
                "local_scheduler_binding_reconciliation_verified"
                if verified
                else "blocked"
            ),
            "contract_sha256": contract["contract_sha256"],
            "source_execution_evidence_sha256": source_evidence["evidence_sha256"],
            "dataset_bundle": dataset,
            "dataset_source_committed": False,
            "dataset_absolute_path_committed": False,
            "dataset_required_in_ci": False,
            "real_dataset_resource_version_bound": True,
            "resource_version_id": str(SOURCE_ID),
            "resource_version_content_sha256": bound_source.version.content_sha256,
            "definition_version_id": str(DEFINITION_ID),
            "definition_sha256": definition_bundle.definition.definition_sha256,
            "compiled_workflow_sha256": definition_bundle.workflow.compiled_sha256,
            "run_id": str(RUN_ID),
            "dispatch_execution_plan_artifact_id": str(bundle.dispatch_plan.artifact_id),
            "dispatch_authorization_id": str(
                bundle.activation_authorization.authorization_id
            ),
            "dispatch_authorization_created": first_auth.created,
            "exact_dispatch_authorization_replay_created": replay_auth.created,
            "provider_apply_execution_plan_artifact_id": str(
                apply_authorization.execution_plan_artifact.artifact_id
            ),
            "provider_apply_policy_decision_artifact_id": str(
                apply_authorization.policy_decision_artifact.artifact_id
            ),
            "provider_apply_approval_artifact_id": str(
                apply_authorization.approval_artifact.artifact_id
            ),
            "provider_apply_authorization_sha256": (
                apply_authorization.authorization_sha256
            ),
            "provider_evidence_artifact_id": str(provider_artifact.artifact_id),
            "provider_evidence_sha256": provider_evidence.evidence_sha256,
            "provider_apply_authorized": True,
            "execution_request_sha256": request.request_sha256,
            "execution_callback_request_count": executor.request_count,
            "execution_callback_exact_request_verified": executor.error_type is None,
            "command_id": str(bundle.activation_authorization.command_id),
            "command_status": command.status.value,
            "command_claimed_count": consumer_result.claimed,
            "command_completed_count": consumer_result.completed,
            "scheduler_provider": {
                "name": "apache-dolphinscheduler",
                "server_version": scheduler_binding.server_version,
                "api_profile": scheduler_binding.api_profile,
                "image": delivery.IMAGE,
                "image_id": delivery.IMAGE_ID,
                "architecture": platform.machine(),
                "project_code": scheduler_binding.project_code,
                "workflow_definition_code": (
                    scheduler_binding.workflow_definition_code
                ),
                "workflow_definition_version": (
                    scheduler_binding.workflow_definition_version
                ),
                "workflow_instance_id": instance_id,
                "terminal_state": terminal.state.upper(),
            },
            "correlation_variables": variables,
            "exact_correlation_variable_readback_verified": (
                variables == expected_variables
            ),
            "matching_provider_instance_count": len(matching_instances),
            "attempt_observation_count": attempts[0],
            "external_correlation_count": attempts[1],
            "submitted_observation_count": attempts[2],
            "success_observation_count": attempts[3],
            "attempt_states": attempts[4],
            "scheduler_success_readback_verified": (
                reconciled.provider_state == "SUCCESS"
            ),
            "platform_run_status": final_run.status.value,
            "platform_run_succeeded": final_run.status == RunStatus.SUCCEEDED,
            "provider_runtime": runtime_identity,
            "provider_security": {
                "openmetadata": {
                    "auth_mode": projection_profile.providers.openmetadata.auth_mode,
                    "authenticated_principal": principal,
                    "minimum_privilege_verified": False,
                },
                "gravitino": {
                    "auth_mode": projection_profile.providers.gravitino.auth_mode,
                    "version": gravitino_version,
                    "authentication_verified": False,
                },
            },
            "first_readback": first_outcome,
            "replay_readback": replay_outcome,
            "source_created_apply_verified": True,
            "partial_projection_detected": (
                first_outcome["status"] == "created"
            ),
            "gravitino_partial_projection_repaired": (
                first_outcome["status"] == "created"
            ),
            "openmetadata_mutations_executed": False,
            "provider_mutations_executed": bool(first_outcome["mutation_count"]),
            "scheduler_triggered_provider_readback_verified": verified,
            "binding_id": str(record.binding_id),
            "binding_sha256": record.binding.binding_sha256,
            "binding_record_sha256": record.record_sha256,
            "openmetadata_entity_id": str(record.binding.openmetadata.entity_id),
            "openmetadata_fqn": record.binding.openmetadata.fully_qualified_name,
            "gravitino_identity": record.binding.gravitino[0].identity,
            "gravitino_provider_revision": (
                record.binding.gravitino[0].provider_revision
            ),
            "first_binding_commit_created": first_commit.created,
            "replay_binding_commit_created": replay_commit.created,
            "binding_row_count": binding_count,
            "stored_binding_matches": stored == record,
            "binding_persisted_to_gda_control": verified,
            "writes_to_gda_control": verified,
            "append_only_privileges_verified": append_only,
            "force_rls_verified": force_rls,
            "cross_tenant_read_blocked": cross_tenant_read_blocked,
            "direct_binding_update_blocked": update_blocked,
            "direct_binding_delete_blocked": delete_blocked,
            "callback_server_cleanup_verified": False,
            "provider_port_forwards_cleanup_verified": False,
            "standalone_container_cleanup_verified": False,
            "temporary_database_cleanup_verified": False,
            "provider_objects_retained_for_readback": True,
            "writes_to_legacy": False,
            "deployment_applied": False,
            "protected_workload_identity_verified": False,
            "provider_minimum_privilege_verified": False,
            "gravitino_authentication_verified": False,
            "durable_catalog_verified": False,
            "oidc_verified": False,
            "tls_verified": False,
            "live_openlineage_emission_verified": False,
            "production_scheduler_submission_verified": False,
            "production_ingestion_verified": False,
            "production_ready": False,
            "errors": [] if verified else ["local binding reconciliation failed"],
        }
        return stable
    finally:
        client.close()
        engine.dispose()


def run_managed_rehearsal(
    database_admin_url: str,
    source_evidence: dict[str, Any],
    admin_password: SecretStr,
    openmetadata_username: str,
    openmetadata_password: SecretStr,
    *,
    readiness_timeout_seconds: float = 180,
    terminal_timeout_seconds: float = 600,
) -> dict[str, Any]:
    validate_source_evidence(source_evidence)
    authorized_at = datetime.now(UTC)
    profile = execution.build_projection_profile(authorized_at)
    plan = build_projection_plan(
        source_evidence["dataset_bundle"]["content_sha256"],
        profile,
    )
    request = execution.build_execution_request(plan)
    database = delivery.EphemeralPostgresDatabase(database_admin_url)
    scheduler = delivery.EphemeralDolphinScheduler(
        admin_password,
        readiness_timeout=readiness_timeout_seconds,
    )
    callback_server = execution.ProjectionExecutionServer(request)
    om_forward = provider_metrics._PortForward(
        kubectl="kubectl",
        context=profile.cluster.context,
        namespace=profile.cluster.namespace,
        service=profile.providers.openmetadata.service,
        target_port=profile.providers.openmetadata.service_port,
    )
    gravitino_forward = provider_metrics._PortForward(
        kubectl="kubectl",
        context=profile.cluster.context,
        namespace=profile.cluster.namespace,
        service=profile.providers.gravitino.service,
        target_port=profile.providers.gravitino.service_port,
    )
    evidence: dict[str, Any] | None = None
    provider_forwards_stopped = False
    openmetadata: replay.OpenMetadataApplyClient | None = None
    gravitino: replay.GravitinoApplyClient | None = None
    try:
        om_forward.start()
        gravitino_forward.start()
        openmetadata = replay.OpenMetadataApplyClient(
            base_url=f"http://127.0.0.1:{om_forward.local_port}/api/v1",
            username=openmetadata_username,
            password=openmetadata_password,
        )
        gravitino = replay.GravitinoApplyClient(
            base_url=f"http://127.0.0.1:{gravitino_forward.local_port}/api"
        )
        principal = openmetadata.authenticated_principal()
        gravitino_version = gravitino.version()
        runtime_identity = replay._provider_runtime_identity(profile)
        with database:
            with scheduler:
                project_code, access_token = scheduler.provision_project()
                scheduler_profile = DolphinSchedulerProfile(
                    base_url=scheduler.base_url,
                    access_token=access_token,
                    project_code=project_code,
                    workload_subject=RUNNER,
                    policy_evaluator_subject=POLICY_EVALUATOR,
                    tenant_code="default",
                    worker_group="default",
                    timezone_name="UTC",
                    request_timeout_seconds=300,
                    reconciliation_page_limit=5,
                )
                if database.database_url is None:
                    raise ActiveMetadataBindingReconciliationError(
                        "temporary PostgreSQL database was not created"
                    )
                evidence = run_scheduler_binding_reconciliation(
                    database.database_url,
                    scheduler_profile,
                    source_evidence,
                    profile,
                    runtime_identity,
                    principal,
                    gravitino_version,
                    openmetadata,
                    gravitino,
                    callback_server,
                    terminal_timeout_seconds=terminal_timeout_seconds,
                )
    finally:
        callback_server.stop()
        if openmetadata is not None:
            openmetadata.close()
        if gravitino is not None:
            gravitino.close()
        provider_forwards_stopped = om_forward.stop() and gravitino_forward.stop()
    if evidence is None:
        raise ActiveMetadataBindingReconciliationError(
            "local scheduler binding rehearsal produced no evidence"
        )
    evidence["callback_server_cleanup_verified"] = callback_server.cleanup_verified
    evidence["provider_port_forwards_cleanup_verified"] = provider_forwards_stopped
    evidence["standalone_container_cleanup_verified"] = scheduler.cleanup_verified
    evidence["temporary_database_cleanup_verified"] = database.cleanup_verified
    cleanup_verified = all(
        (
            callback_server.cleanup_verified,
            provider_forwards_stopped,
            scheduler.cleanup_verified,
            database.cleanup_verified,
        )
    )
    if not cleanup_verified:
        evidence["errors"].append("ephemeral binding runtime cleanup failed")
        evidence["status"] = "blocked"
        evidence["binding_persisted_to_gda_control"] = False
    stable = {key: value for key, value in evidence.items() if key != "evidence_sha256"}
    return {**stable, "evidence_sha256": canonical_json_fingerprint(stable)}


def build_contract_report(
    *,
    source_evidence_path: Path = DEFAULT_SOURCE_EVIDENCE_PATH,
    wrapper_path: Path = DEFAULT_WRAPPER_PATH,
) -> dict[str, Any]:
    errors: list[str] = []
    source_evidence_sha256: str | None = None
    binding_sha256: str | None = None
    try:
        source = _load_json_object(source_evidence_path)
        validate_source_evidence(source)
        profile = execution.build_projection_profile(
            datetime(2026, 7, 30, 12, 0, tzinfo=UTC)
        )
        bound = build_bound_source(source, profile)
        source_evidence_sha256 = source["evidence_sha256"]
        binding_sha256 = bound.binding.binding_sha256
    except (KeyError, TypeError, ValueError, ActiveMetadataBindingReconciliationError) as exc:
        errors.append(f"M3-19 source contract is invalid: {type(exc).__name__}")
    try:
        wrapper = wrapper_path.read_text(encoding="utf-8")
        for marker in (
            "set -euo pipefail",
            "metadata_fabric_active_metadata_binding_reconciliation",
            '"$@"',
        ):
            if marker not in wrapper:
                errors.append(f"M3-19 wrapper is missing marker: {marker}")
    except OSError as exc:
        errors.append(f"M3-19 wrapper is invalid: {type(exc).__name__}")
    files = {
        "implementation": _file_record(Path(__file__)),
        "binding_contract": _file_record(
            REPO_ROOT / "data_agent/metadata_fabric_binding_contract.py"
        ),
        "source_evidence": _file_record(source_evidence_path),
        "wrapper": _file_record(wrapper_path),
        **{path.name: _file_record(path) for path in MIGRATIONS},
    }
    stable = {
        "schema": CONTRACT_SCHEMA,
        "source_execution_evidence_sha256": source_evidence_sha256,
        "expected_binding_sha256": binding_sha256,
        "provider_operation_mode": (
            "authorized_gravitino_partial_repair_then_no_op_replay_and_binding_commit"
        ),
        "platform_run_terminal_gate": "reconciling_until_success_evidence",
        "files": files,
        "errors": errors,
    }
    return {
        **stable,
        "status": "valid" if not errors else "invalid",
        "contract_sha256": canonical_json_fingerprint(stable),
        "binding_persisted_to_gda_control": False,
        "provider_mutations_executed": False,
        "production_ingestion_verified": False,
        "production_ready": False,
    }


def validate_rehearsal_evidence(evidence: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    stable = {key: value for key, value in evidence.items() if key != "evidence_sha256"}
    if evidence.get("schema") != EVIDENCE_SCHEMA:
        errors.append("binding reconciliation evidence schema does not match")
    if evidence.get("evidence_sha256") != canonical_json_fingerprint(stable):
        errors.append("binding reconciliation evidence SHA-256 does not match")
    contract = build_contract_report()
    if evidence.get("contract_sha256") != contract.get("contract_sha256"):
        errors.append("binding reconciliation contract fingerprint is stale")
    try:
        source = _load_json_object(DEFAULT_SOURCE_EVIDENCE_PATH)
        validate_source_evidence(source)
    except ActiveMetadataBindingReconciliationError:
        source = {}
        errors.append("M3-18 source execution evidence is unavailable")
    if evidence.get("source_execution_evidence_sha256") != source.get(
        "evidence_sha256"
    ):
        errors.append("M3-18 source execution fingerprint is stale")
    dataset = evidence.get("dataset_bundle")
    if not isinstance(dataset, dict):
        errors.append("binding reconciliation dataset bundle is missing")
    else:
        errors.extend(validate_shapefile_bundle_inventory(dataset))
        if evidence.get("resource_version_content_sha256") != dataset.get(
            "content_sha256"
        ):
            errors.append("real dataset fingerprint is not bound to ResourceVersion")
    for claim in FALSE_CLAIMS:
        if evidence.get(claim) is not False:
            errors.append(f"local binding reconciliation may not claim {claim}")
    for claim in (
        "real_dataset_resource_version_bound",
        "provider_apply_authorized",
        "execution_callback_exact_request_verified",
        "exact_correlation_variable_readback_verified",
        "scheduler_success_readback_verified",
        "source_created_apply_verified",
        "scheduler_triggered_provider_readback_verified",
        "stored_binding_matches",
        "binding_persisted_to_gda_control",
        "writes_to_gda_control",
        "append_only_privileges_verified",
        "force_rls_verified",
        "cross_tenant_read_blocked",
        "direct_binding_update_blocked",
        "direct_binding_delete_blocked",
        "callback_server_cleanup_verified",
        "provider_port_forwards_cleanup_verified",
        "standalone_container_cleanup_verified",
        "temporary_database_cleanup_verified",
        "provider_objects_retained_for_readback",
    ):
        if evidence.get(claim) is not True:
            errors.append(f"binding reconciliation did not verify {claim}")
    if evidence.get("partial_projection_detected") is not True:
        errors.append("M3-19 did not record the partial provider projection")
    if evidence.get("gravitino_partial_projection_repaired") is not True:
        errors.append("M3-19 did not repair the missing Gravitino projection")
    if evidence.get("openmetadata_mutations_executed") is not False:
        errors.append("M3-19 may not mutate retained OpenMetadata state")
    if evidence.get("provider_mutations_executed") is not True:
        errors.append("M3-19 did not record the authorized Gravitino repair")
    if evidence.get("first_binding_commit_created") is not True:
        errors.append("first binding commit did not create a row")
    if evidence.get("replay_binding_commit_created") is not False:
        errors.append("exact binding replay created a row")
    if evidence.get("binding_row_count") != 1:
        errors.append("binding reconciliation must persist exactly one row")
    if evidence.get("dispatch_authorization_created") is not True:
        errors.append("binding dispatch authorization was not created")
    if evidence.get("exact_dispatch_authorization_replay_created") is not False:
        errors.append("exact binding dispatch authorization replay created a row")
    if evidence.get("execution_callback_request_count") != 1:
        errors.append("binding executor must receive exactly one callback")
    if evidence.get("command_status") != "done":
        errors.append("authorized binding command must be done")
    if evidence.get("command_claimed_count") != 1:
        errors.append("binding execution must claim one command")
    if evidence.get("command_completed_count") != 1:
        errors.append("binding execution must complete one command")
    scheduler = evidence.get("scheduler_provider")
    expected_scheduler = {
        "name": "apache-dolphinscheduler",
        "server_version": DOLPHINSCHEDULER_SERVER_VERSION,
        "api_profile": DOLPHINSCHEDULER_API_PROFILE,
        "image": delivery.IMAGE,
        "image_id": delivery.IMAGE_ID,
        "terminal_state": "SUCCESS",
    }
    if not isinstance(scheduler, dict) or any(
        scheduler.get(key) != value for key, value in expected_scheduler.items()
    ):
        errors.append("binding scheduler provider identity or state does not match")
    if evidence.get("matching_provider_instance_count") != 1:
        errors.append("binding reconciliation must read back one scheduler instance")
    if evidence.get("attempt_observation_count") != 2:
        errors.append("binding reconciliation must record two attempt observations")
    if evidence.get("external_correlation_count") != 1:
        errors.append("binding reconciliation must retain one external correlation")
    if evidence.get("attempt_states") != ["submitted", "success"]:
        errors.append("binding scheduler attempt states do not match")
    if evidence.get("platform_run_status") != "reconciling":
        errors.append("binding persistence must leave PlatformRun reconciling")
    first = evidence.get("first_readback")
    replayed = evidence.get("replay_readback")
    if not isinstance(first, dict) or not isinstance(replayed, dict):
        errors.append("provider read-back outcomes are missing")
    else:
        if (
            first.get("status") != "created"
            or first.get("mutation_count", 0) <= 0
            or any(
                not mutation.startswith("gravitino.")
                for mutation in first.get("mutations", [])
            )
        ):
            errors.append("first provider reconciliation was not Gravitino-only repair")
        if replayed.get("status") != "no_op" or replayed.get("mutation_count") != 0:
            errors.append("provider repair replay was not mutation-free")
        for key in ("binding_candidate_sha256", "openmetadata", "gravitino"):
            if first.get(key) != replayed.get(key):
                errors.append(f"provider read-back drifted across replay: {key}")
        if evidence.get("binding_sha256") != first.get("binding_candidate_sha256"):
            errors.append("stored binding does not match provider read-back")
    source_first = source.get("first_apply") if isinstance(source, dict) else None
    if isinstance(source_first, dict):
        if evidence.get("openmetadata_entity_id") != source_first.get(
            "openmetadata", {}
        ).get("entity_id"):
            errors.append("stored OpenMetadata entity does not match M3-18")
        if evidence.get("binding_sha256") != source_first.get(
            "binding_candidate_sha256"
        ):
            errors.append("stored binding does not match M3-18 candidate")
    serialized = json.dumps(evidence, ensure_ascii=True, sort_keys=True)
    for forbidden in (
        "/Users/",
        "Downloads/",
        ".tmp/",
        "host.docker.internal",
        '"token"',
        '"password"',
        '"session"',
    ):
        if forbidden in serialized:
            errors.append("binding evidence contains sensitive local material")
            break
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate")
    validate.add_argument(
        "--source-evidence",
        type=Path,
        default=DEFAULT_SOURCE_EVIDENCE_PATH,
    )
    validate.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE_PATH)
    rehearse = subparsers.add_parser("rehearse")
    rehearse.add_argument("--database-admin-url", required=True)
    rehearse.add_argument(
        "--admin-password-env",
        default="GDA_DOLPHINSCHEDULER_ADMIN_PASSWORD",
    )
    rehearse.add_argument(
        "--source-evidence",
        type=Path,
        default=DEFAULT_SOURCE_EVIDENCE_PATH,
    )
    rehearse.add_argument("--readiness-timeout-seconds", type=float, default=180)
    rehearse.add_argument("--terminal-timeout-seconds", type=float, default=600)
    rehearse.add_argument("--evidence-out", type=Path, required=True)
    args = parser.parse_args(argv)

    if args.command == "validate":
        report = build_contract_report(source_evidence_path=args.source_evidence)
        try:
            report["errors"].extend(
                validate_rehearsal_evidence(_load_json_object(args.evidence))
            )
        except ActiveMetadataBindingReconciliationError as exc:
            report["errors"].append(
                f"binding reconciliation evidence is invalid: {type(exc).__name__}"
            )
        report["status"] = "valid" if not report["errors"] else "invalid"
        print(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True))
        return 0 if not report["errors"] else 1

    source = _load_json_object(args.source_evidence)
    provider_profile = replay.load_profile()
    try:
        username = os.environ[provider_profile.providers.openmetadata.username_env]
        password = SecretStr(
            os.environ[provider_profile.providers.openmetadata.password_env]
        )
    except KeyError as exc:
        raise ActiveMetadataBindingReconciliationError(
            "OpenMetadata local bootstrap credential environment is missing"
        ) from exc
    evidence = run_managed_rehearsal(
        args.database_admin_url,
        source,
        delivery._read_admin_password(args.admin_password_env),
        username,
        password,
        readiness_timeout_seconds=args.readiness_timeout_seconds,
        terminal_timeout_seconds=args.terminal_timeout_seconds,
    )
    args.evidence_out.write_text(
        json.dumps(evidence, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(evidence, ensure_ascii=True, indent=2, sort_keys=True))
    return 0 if not evidence["errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
