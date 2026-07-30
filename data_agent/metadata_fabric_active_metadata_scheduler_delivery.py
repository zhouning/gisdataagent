"""Verify authorized Active Metadata delivery through real DolphinScheduler.

This local-only rehearsal carries the checked Chongqing ResourceVersion content
fingerprint into a provider-native DolphinScheduler workflow, authorizes the
exact binding through the M3-16 ledger, lets the durable command consumer submit
it, and reads the successful provider instance back into attempt evidence.  A
provider success leaves the PlatformRun in ``reconciling`` and never authorizes
or executes a governed metadata/data mutation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import secrets
import socket
import subprocess
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
from pydantic import SecretStr
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from . import metadata_fabric_active_metadata_authorization as authorization
from .active_metadata_authorization import (
    MetadataActivationAuthorization,
    build_metadata_activation_authorization,
)
from .dolphinscheduler_adapter import (
    DOLPHINSCHEDULER_ADAPTER_SCHEMA,
    DOLPHINSCHEDULER_API_PROFILE,
    DOLPHINSCHEDULER_SERVER_VERSION,
    DolphinSchedulerAdapter,
    DolphinSchedulerClient,
    DolphinSchedulerDefinitionBinding,
    DolphinSchedulerInstance,
    DolphinSchedulerProfile,
    DolphinSchedulerWorkflowSpec,
    build_dolphinscheduler_binding_artifact,
    compile_dolphinscheduler_workflow,
)
from .dolphinscheduler_command_consumer import DolphinSchedulerCommandConsumer
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
from .platform_gateway import DefinitionRegistration, PlatformGateway
from .spatial_dataset_bundle import validate_shapefile_bundle_inventory

CONTRACT_SCHEMA = "gda.active_metadata_scheduler_delivery_contract.v1"
EVIDENCE_SCHEMA = "gda.active_metadata_scheduler_delivery_evidence.v1"
IMAGE = "apache/dolphinscheduler-standalone-server:3.4.2"
IMAGE_ID = "sha256:485a1b37dd1c4088c8c8335f9fccbd229e5e703c32e21f318eb00cbb60b1af9d"
CONTAINER_PORT = 12345
REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DEPENDENCY_EVIDENCE_PATH = authorization.DEFAULT_EVIDENCE_PATH
DEFAULT_EVIDENCE_PATH = (
    REPO_ROOT
    / "docs/evidence/metadata-fabric-active-metadata-scheduler-delivery-2026-07-30.json"
)
DEFAULT_WRAPPER_PATH = (
    REPO_ROOT / "scripts/metadata-fabric-active-metadata-scheduler-delivery.sh"
)
TENANT = authorization.TENANT
SOURCE_ID = authorization.SOURCE_ID
DEFINITION_ID = UUID("a7000000-0000-4000-8000-000000000002")
RUN_ID = UUID("a7000000-0000-4000-8000-000000000003")
TASK_CODE = 170000000000001
WORKER = "worker:active-metadata-scheduler-delivery-1"
RUNNER = "workload:metadata-projection-runner"
POLICY_EVALUATOR = "workload:metadata-policy-evaluator"
AUTHORIZER = "workload:metadata-activation-authorizer"
APPROVER = "human:metadata-governance-approver"
TERMINAL_STATES = frozenset({"SUCCESS", "FAILURE", "STOP", "PAUSE"})
FALSE_CLAIMS = (
    "dataset_source_committed",
    "dataset_absolute_path_committed",
    "dataset_required_in_ci",
    "deployment_applied",
    "production_workload_identity_verified",
    "provider_apply_authorized",
    "provider_mutations_executed",
    "production_scheduler_submission_verified",
    "production_ingestion_verified",
    "production_ready",
)


class ActiveMetadataSchedulerDeliveryError(RuntimeError):
    """The scheduler delivery contract or local rehearsal failed closed."""


@dataclass(frozen=True)
class SchedulerDefinitionBundle:
    registration: DefinitionRegistration
    definition: PlatformDefinitionVersion
    workflow: DolphinSchedulerWorkflowSpec


@dataclass(frozen=True)
class SchedulerDeliveryBundle:
    source_resource: Resource
    source_version: ResourceVersion
    request: Any
    registration: Any
    definition_registration: DefinitionRegistration
    execution_plan: Artifact
    policy_decision: Artifact
    approval: Artifact
    run: PlatformRun
    authorization: MetadataActivationAuthorization


def _workflow_document() -> dict[str, Any]:
    task = {
        "code": TASK_CODE,
        "name": "project_active_metadata_noop",
        "version": 1,
        "description": "Validate delivery without mutating governed metadata",
        "delayTime": 0,
        "taskType": "SHELL",
        "taskParams": {
            "localParams": [],
            "rawScript": "printf '%s\\n' 'gda active metadata delivery verified'",
            "resourceList": [],
            "dependence": {},
            "conditionResult": {"successNode": [], "failedNode": []},
            "waitStartTimeout": {},
        },
        "flag": "YES",
        "taskPriority": "MEDIUM",
        "workerGroup": "default",
        "environmentCode": -1,
        "failRetryTimes": 0,
        "failRetryInterval": 1,
        "timeoutFlag": "CLOSE",
        "timeoutNotifyStrategy": "WARN",
        "timeout": 0,
    }
    relation = {
        "name": "",
        "preTaskCode": 0,
        "preTaskVersion": 0,
        "postTaskCode": TASK_CODE,
        "postTaskVersion": 1,
        "conditionType": "NONE",
        "conditionParams": {},
    }
    return {
        "dolphinscheduler": {
            "name": "gda_active_metadata_projection_delivery_v1",
            "description": "No-side-effect Active Metadata delivery verification",
            "task_definitions": [task],
            "task_relations": [relation],
            "locations": [{"taskCode": TASK_CODE, "x": 160, "y": 100}],
            "global_params": [],
            "timeout_seconds": 0,
            "execution_type": "PARALLEL",
        }
    }


def build_scheduler_definition(created_at: datetime) -> SchedulerDefinitionBundle:
    definition_urn = f"gda://{TENANT}/definition/metadata-projection-delivery"
    definition_document = _workflow_document()
    input_contract = {
        "metadata_change": "gis.cultural_districts",
        "delivery_mode": "no_side_effect",
    }
    output_contract = {"governed_provider_mutation": False}
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
        authority_locator="definition/metadata-projection-delivery",
        owner_ref="team:metadata-platform",
    )
    resource_version = ResourceVersion(
        tenant_id=TENANT,
        resource_urn=definition_urn,
        resource_version_id=DEFINITION_ID,
        version_key="dolphinscheduler-3.4.2-v1",
        content_sha256=definition_sha256,
        authority_version_ref={
            "api_profile": DOLPHINSCHEDULER_API_PROFILE,
            "server_version": DOLPHINSCHEDULER_SERVER_VERSION,
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
    return SchedulerDefinitionBundle(
        registration=DefinitionRegistration(
            resource=resource,
            resource_version=resource_version,
            definition=definition,
        ),
        definition=definition,
        workflow=compile_dolphinscheduler_workflow(definition),
    )


def build_scheduler_delivery_bundle(
    content_sha256: str,
    definition_bundle: SchedulerDefinitionBundle,
    binding: DolphinSchedulerDefinitionBinding,
    *,
    authorized_at: datetime,
) -> SchedulerDeliveryBundle:
    base = authorization.build_authorization_bundle(content_sha256)
    source_version = base.registration.resource_version
    if binding.definition_version_id != definition_bundle.definition.definition_version_id:
        raise ActiveMetadataSchedulerDeliveryError(
            "DolphinScheduler binding does not match the delivery definition"
        )
    if binding.compiled_sha256 != definition_bundle.workflow.compiled_sha256:
        raise ActiveMetadataSchedulerDeliveryError(
            "DolphinScheduler binding does not match the compiled workflow"
        )
    execution_plan = build_dolphinscheduler_binding_artifact(
        binding,
        created_by=RUNNER,
        created_at=authorized_at - timedelta(seconds=3),
    )
    subject = SubjectContext(
        tenant_id=TENANT,
        subject_id=RUNNER.removeprefix("workload:"),
        subject_type="workload",
        roles=("metadata_projector",),
        purpose="deliver authorized active metadata projection",
    )
    decision = PolicyDecision(
        tenant_id=TENANT,
        run_id=RUN_ID,
        subject_context=subject,
        action="dolphinscheduler.dispatch",
        definition_version_id=DEFINITION_ID,
        resource_version_ids=(DEFINITION_ID, SOURCE_ID),
        execution_plan_artifact_id=execution_plan.artifact_id,
        effect="allow",
        policy_version_ref=f"gda://{TENANT}/policy/metadata-dispatch-v1",
        evaluator_subject=POLICY_EVALUATOR,
        requires_approval=True,
        decided_at=authorized_at - timedelta(seconds=3),
        expires_at=authorized_at + timedelta(days=365),
    )
    policy_decision = build_policy_decision_artifact(decision)
    approval = build_approval_artifact(
        ApprovalRecord(
            tenant_id=TENANT,
            run_id=RUN_ID,
            definition_version_id=DEFINITION_ID,
            policy_decision_artifact_id=policy_decision.artifact_id,
            policy_decision_sha256=policy_decision.content_sha256,
            verdict="approved",
            approver_subject=APPROVER,
            reason="approved no-side-effect scheduler delivery rehearsal",
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
        idempotency_key="metadata-projection:cultural-districts:scheduler-delivery:v1",
        policy_refs=RunPolicyReferences(
            policy_decision_artifact_id=policy_decision.artifact_id,
            approval_artifact_id=approval.artifact_id,
        ),
        submitted_at=authorized_at - timedelta(seconds=1),
    )
    activation_authorization = build_metadata_activation_authorization(
        base.request,
        source_version,
        definition_bundle.definition,
        run,
        execution_plan,
        policy_decision,
        approval,
        authorized_by=AUTHORIZER,
        authorized_at=authorized_at,
    )
    return SchedulerDeliveryBundle(
        source_resource=base.source_resource,
        source_version=source_version,
        request=base.request,
        registration=base.registration,
        definition_registration=definition_bundle.registration,
        execution_plan=execution_plan,
        policy_decision=policy_decision,
        approval=approval,
        run=run,
        authorization=activation_authorization,
    )


def _load_json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ActiveMetadataSchedulerDeliveryError(
            f"{path.name} must contain an object"
        )
    return value


def _file_record(path: Path) -> dict[str, str | None]:
    relative = path.resolve().relative_to(REPO_ROOT).as_posix()
    if not path.is_file():
        return {"path": relative, "sha256": None}
    return {"path": relative, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def build_contract_report() -> dict[str, Any]:
    errors: list[str] = []
    paths = {
        "rehearsal": Path(__file__).resolve(),
        "adapter": REPO_ROOT / "data_agent/dolphinscheduler_adapter.py",
        "consumer": REPO_ROOT / "data_agent/dolphinscheduler_command_consumer.py",
        "authorization_migration": (
            REPO_ROOT / "data_agent/migrations/101_active_metadata_authorization.sql"
        ),
        "dependency_evidence": DEFAULT_DEPENDENCY_EVIDENCE_PATH,
        "wrapper": DEFAULT_WRAPPER_PATH,
    }
    required = {
        "rehearsal": (
            "def run_local_rehearsal(",
            "DolphinSchedulerCommandConsumer",
            "provider reached terminal state; platform verdict still pending",
            "local_scheduler_submission_readback_verified",
        ),
        "adapter": (
            "class DolphinSchedulerAdapter",
            "def reconcile(",
            "RunStatus.RECONCILING",
        ),
        "consumer": ("class DolphinSchedulerCommandConsumer", "self.adapter.dispatch("),
        "authorization_migration": (
            "authorize_metadata_activation",
            "Active Metadata dispatch requires exact authorization",
        ),
        "wrapper": (
            "data_agent.metadata_fabric_active_metadata_scheduler_delivery",
            '"$@"',
        ),
    }
    files = {name: _file_record(path) for name, path in paths.items()}
    for name, markers in required.items():
        path = paths[name]
        try:
            source = path.read_text(encoding="utf-8")
        except OSError:
            errors.append(f"{name} is missing")
            continue
        if any(marker not in source for marker in markers):
            errors.append(f"{name} is missing scheduler delivery markers")
    try:
        dependency = _load_json_object(DEFAULT_DEPENDENCY_EVIDENCE_PATH)
        dependency_errors = authorization.validate_rehearsal_evidence(dependency)
        if dependency_errors:
            errors.append("M3-16 authorization dependency is invalid")
    except (OSError, ValueError, ActiveMetadataSchedulerDeliveryError):
        dependency = {}
        errors.append("M3-16 authorization dependency is unavailable")
    stable = {
        "schema": CONTRACT_SCHEMA,
        "provider": "apache-dolphinscheduler",
        "server_version": DOLPHINSCHEDULER_SERVER_VERSION,
        "api_profile": DOLPHINSCHEDULER_API_PROFILE,
        "image": IMAGE,
        "image_id": IMAGE_ID,
        "adapter_schema": DOLPHINSCHEDULER_ADAPTER_SCHEMA,
        "delivery_boundary": "authorized_command_consumer_submission_and_readback",
        "provider_success_platform_state": "reconciling",
        "governed_mutation_mode": "no_side_effect",
        "dependency_evidence_sha256": dependency.get("evidence_sha256"),
        "files": files,
        "errors": errors,
    }
    return {
        **stable,
        "status": "valid" if not errors else "invalid",
        "contract_sha256": canonical_json_fingerprint(stable),
        "production_scheduler_submission_verified": False,
        "provider_mutations_executed": False,
        "production_ready": False,
    }


def _wait_for_terminal_instance(
    client: DolphinSchedulerClient,
    instance_id: int,
    workflow_definition_code: int,
    *,
    timeout_seconds: float,
) -> DolphinSchedulerInstance:
    deadline = time.monotonic() + timeout_seconds
    last: DolphinSchedulerInstance | None = None
    while time.monotonic() < deadline:
        last = client.get_instance(instance_id, workflow_definition_code)
        if last.state.upper() in TERMINAL_STATES:
            return last
        time.sleep(2)
    state = last.state if last is not None else "unobserved"
    raise ActiveMetadataSchedulerDeliveryError(
        f"DolphinScheduler instance did not reach terminal state: {state}"
    )


def _register_control_chain(
    gateway: PlatformGateway, bundle: SchedulerDeliveryBundle
) -> None:
    gateway.register_resource(bundle.source_resource)
    gateway.register_resource_version_with_metadata_event(bundle.registration)
    claimed = gateway.claim_metadata_changes(
        TENANT,
        WORKER,
        consumer_subject=authorization.CONSUMER_SUBJECT,
    )
    if len(claimed) != 1:
        raise ActiveMetadataSchedulerDeliveryError(
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
        bundle.execution_plan,
        bundle.policy_decision,
        bundle.approval,
    ):
        gateway.record_artifact(artifact)
    gateway.submit_run(bundle.run)


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


def run_local_rehearsal(
    database_url: str,
    profile: DolphinSchedulerProfile,
    dependency_evidence: dict[str, Any],
    *,
    terminal_timeout_seconds: float = 600,
) -> dict[str, Any]:
    dependency_errors = authorization.validate_rehearsal_evidence(
        dependency_evidence
    )
    if dependency_errors:
        raise ActiveMetadataSchedulerDeliveryError(
            "M3-16 authorization evidence is invalid"
        )
    dataset_inventory = dependency_evidence["dataset_bundle"]
    if validate_shapefile_bundle_inventory(dataset_inventory):
        raise ActiveMetadataSchedulerDeliveryError(
            "real dataset bundle inventory is invalid"
        )
    if profile.workload_subject != RUNNER:
        raise ActiveMetadataSchedulerDeliveryError(
            "scheduler profile workload does not match the authorized runner"
        )
    if profile.policy_evaluator_subject != POLICY_EVALUATOR:
        raise ActiveMetadataSchedulerDeliveryError(
            "scheduler profile evaluator does not match policy evidence"
        )

    started_at = datetime.now(UTC)
    definition_bundle = build_scheduler_definition(started_at)
    engine = create_engine(database_url)
    client = DolphinSchedulerClient(profile)
    try:
        binding = client.create_workflow(definition_bundle.workflow)
        authorized_at = datetime.now(UTC)
        bundle = build_scheduler_delivery_bundle(
            dataset_inventory["content_sha256"],
            definition_bundle,
            binding,
            authorized_at=authorized_at,
        )
        authorization._apply_migrations(engine)
        gateway = PlatformGateway(engine)
        _register_control_chain(gateway, bundle)
        first = gateway.authorize_metadata_activation(bundle.authorization)
        replay = gateway.authorize_metadata_activation(bundle.authorization)

        adapter = DolphinSchedulerAdapter(
            profile,
            gateway=gateway,
            client=client,
            clock=lambda: authorized_at,
        )
        consumer_result = DolphinSchedulerCommandConsumer(
            adapter, gateway=gateway
        ).run_once(TENANT, worker_id=WORKER, limit=1, lease_seconds=600)
        if consumer_result.completed != 1:
            raise ActiveMetadataSchedulerDeliveryError(
                "authorized scheduler command was not completed"
            )
        command = gateway.get_command(TENANT, bundle.authorization.command_id)
        submitted_observation = _attempt_summary(engine)
        if submitted_observation[2] != 1:
            raise ActiveMetadataSchedulerDeliveryError(
                "scheduler submission observation is missing"
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
        terminal = _wait_for_terminal_instance(
            client,
            instance_id,
            binding.workflow_definition_code,
            timeout_seconds=terminal_timeout_seconds,
        )
        variables = client.get_instance_variables(instance_id)
        expected_variables = {
            str(item["prop"]): str(item["value"])
            for item in definition_bundle.workflow.global_params
        }
        expected_variables.update(DolphinSchedulerClient.start_params(bundle.run))
        matching_instances = client.find_instances(binding, bundle.run)
        reconciled = adapter.reconcile(
            TENANT,
            RUN_ID,
            bundle.execution_plan.artifact_id,
            actor_subject=RUNNER,
            attempt_no=1,
        )
        attempts = _attempt_summary(engine)
        final_run = gateway.get_run(TENANT, RUN_ID)

        verified = (
            first.created
            and not replay.created
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
            and bundle.source_version.content_sha256
            == dataset_inventory["content_sha256"]
            == dependency_evidence["resource_version_content_sha256"]
        )
        contract = build_contract_report()
        stable = {
            "schema": EVIDENCE_SCHEMA,
            "status": (
                "local_real_data_authorized_scheduler_delivery_verified"
                if verified
                else "blocked"
            ),
            "contract_sha256": contract["contract_sha256"],
            "dependency_evidence_sha256": dependency_evidence["evidence_sha256"],
            "dataset_bundle": dataset_inventory,
            "dataset_source_committed": False,
            "dataset_absolute_path_committed": False,
            "dataset_required_in_ci": False,
            "real_dataset_resource_version_bound": True,
            "resource_version_id": str(SOURCE_ID),
            "resource_version_content_sha256": bundle.source_version.content_sha256,
            "definition_version_id": str(DEFINITION_ID),
            "definition_sha256": definition_bundle.definition.definition_sha256,
            "compiled_workflow_sha256": definition_bundle.workflow.compiled_sha256,
            "execution_plan_artifact_id": str(bundle.execution_plan.artifact_id),
            "execution_plan_sha256": bundle.execution_plan.content_sha256,
            "run_id": str(RUN_ID),
            "authorization_id": str(bundle.authorization.authorization_id),
            "authorization_sha256": bundle.authorization.authorization_sha256,
            "authorization_created": first.created,
            "exact_authorization_replay_created": replay.created,
            "command_id": str(bundle.authorization.command_id),
            "command_status": command.status.value,
            "command_claimed_count": consumer_result.claimed,
            "command_completed_count": consumer_result.completed,
            "provider": {
                "name": "apache-dolphinscheduler",
                "server_version": binding.server_version,
                "api_profile": binding.api_profile,
                "image": IMAGE,
                "image_id": IMAGE_ID,
                "architecture": platform.machine(),
                "project_code": binding.project_code,
                "workflow_definition_code": binding.workflow_definition_code,
                "workflow_definition_version": binding.workflow_definition_version,
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
            "provider_success_readback_verified": (
                reconciled.provider_state == "SUCCESS"
            ),
            "platform_run_status": final_run.status.value,
            "platform_run_succeeded": final_run.status == RunStatus.SUCCEEDED,
            "provider_workflow_definition_created": True,
            "provider_workflow_instance_executed": True,
            "no_side_effect_workflow_verified": True,
            "local_scheduler_submission_readback_verified": verified,
            "standalone_container_cleanup_verified": False,
            "temporary_database_cleanup_verified": False,
            "deployment_applied": False,
            "production_workload_identity_verified": False,
            "provider_apply_authorized": False,
            "provider_mutations_executed": False,
            "production_scheduler_submission_verified": False,
            "production_ingestion_verified": False,
            "production_ready": False,
            "errors": [] if verified else ["local scheduler delivery failed"],
        }
        return stable
    finally:
        client.close()
        engine.dispose()


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as candidate:
        candidate.bind(("127.0.0.1", 0))
        return int(candidate.getsockname()[1])


def _run_command(args: list[str]) -> str:
    completed = subprocess.run(
        args,
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if completed.returncode != 0:
        raise ActiveMetadataSchedulerDeliveryError(
            f"local runtime command failed: {Path(args[0]).name}"
        )
    return completed.stdout.strip()


class EphemeralPostgresDatabase:
    def __init__(self, admin_url: str):
        self.admin_url = admin_url
        self.database_name = f"gda_m3_17_{secrets.token_hex(6)}"
        self.database_url: str | None = None
        self.created = False
        self.cleanup_verified = False

    def __enter__(self) -> EphemeralPostgresDatabase:
        admin = create_engine(self.admin_url, isolation_level="AUTOCOMMIT")
        try:
            with admin.connect() as connection:
                connection.exec_driver_sql(f'CREATE DATABASE "{self.database_name}"')
            self.created = True
            self.database_url = make_url(self.admin_url).set(
                database=self.database_name
            ).render_as_string(
                hide_password=False
            )
            return self
        except BaseException:
            admin.dispose()
            self.__exit__()
            raise
        finally:
            admin.dispose()

    def __exit__(self, *_args: object) -> None:
        if not self.created:
            return
        admin = create_engine(self.admin_url, isolation_level="AUTOCOMMIT")
        try:
            with admin.connect() as connection:
                connection.execute(
                    text(
                        """
                        SELECT pg_terminate_backend(pid)
                        FROM pg_stat_activity
                        WHERE datname = :database_name
                          AND pid <> pg_backend_pid()
                        """
                    ),
                    {"database_name": self.database_name},
                )
                connection.exec_driver_sql(f'DROP DATABASE "{self.database_name}"')
                exists = connection.execute(
                    text("SELECT 1 FROM pg_database WHERE datname = :database_name"),
                    {"database_name": self.database_name},
                ).first()
                self.cleanup_verified = exists is None
        finally:
            admin.dispose()


class EphemeralDolphinScheduler:
    def __init__(self, admin_password: SecretStr, *, readiness_timeout: float):
        self.admin_password = admin_password
        self.readiness_timeout = readiness_timeout
        self.container_name = f"gda-m3-17-{secrets.token_hex(5)}"
        self.host_port = _free_loopback_port()
        self.base_url = f"http://127.0.0.1:{self.host_port}/dolphinscheduler"
        self.started = False
        self.cleanup_verified = False

    def __enter__(self) -> EphemeralDolphinScheduler:
        try:
            image_id = _run_command(
                ["docker", "image", "inspect", "--format", "{{.Id}}", IMAGE]
            )
            if image_id != IMAGE_ID:
                raise ActiveMetadataSchedulerDeliveryError(
                    "local DolphinScheduler image ID does not match ADR-023"
                )
            self.started = True
            _run_command(
                [
                    "docker",
                    "run",
                    "--detach",
                    "--name",
                    self.container_name,
                    "--publish",
                    f"127.0.0.1:{self.host_port}:{CONTAINER_PORT}",
                    IMAGE,
                ]
            )
            self._wait_ready()
            return self
        except BaseException:
            self.__exit__()
            raise

    def __exit__(self, *_args: object) -> None:
        if not self.started:
            return
        completed = subprocess.run(
            ["docker", "rm", "--force", self.container_name],
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if completed.returncode == 0:
            remaining = subprocess.run(
                [
                    "docker",
                    "container",
                    "inspect",
                    self.container_name,
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.cleanup_verified = remaining.returncode != 0

    def _wait_ready(self) -> None:
        deadline = time.monotonic() + self.readiness_timeout
        health_url = f"{self.base_url}/actuator/health"
        while time.monotonic() < deadline:
            try:
                response = httpx.get(health_url, timeout=5)
                if response.status_code == 200 and response.json().get("status") == "UP":
                    return
            except (httpx.HTTPError, ValueError):
                pass
            time.sleep(2)
        raise ActiveMetadataSchedulerDeliveryError(
            "DolphinScheduler standalone did not become ready"
        )

    @staticmethod
    def _api_data(response: httpx.Response) -> Any:
        try:
            value = response.json()
        except ValueError as exc:
            raise ActiveMetadataSchedulerDeliveryError(
                "DolphinScheduler provisioning returned non-JSON"
            ) from exc
        if response.status_code >= 400 or not isinstance(value, dict):
            raise ActiveMetadataSchedulerDeliveryError(
                "DolphinScheduler provisioning request failed"
            )
        if value.get("code") != 0:
            raise ActiveMetadataSchedulerDeliveryError(
                "DolphinScheduler provisioning API rejected the request"
            )
        return value.get("data")

    def provision_project(self) -> tuple[int, SecretStr]:
        with httpx.Client(timeout=30) as client:
            login = client.post(
                f"{self.base_url}/login",
                data={
                    "userName": "admin",
                    "userPassword": self.admin_password.get_secret_value(),
                },
            )
            login_data = self._api_data(login)
            if isinstance(login_data, dict) and login_data.get("sessionId"):
                client.cookies.set("sessionId", str(login_data["sessionId"]))
            project_name = f"gda_m3_17_{secrets.token_hex(5)}"
            project_data = self._api_data(
                client.post(
                    f"{self.base_url}/projects",
                    data={
                        "projectName": project_name,
                        "description": "GDA M3-17 local delivery rehearsal",
                    },
                )
            )
            if not isinstance(project_data, dict):
                raise ActiveMetadataSchedulerDeliveryError(
                    "DolphinScheduler project response is invalid"
                )
            try:
                project_code = int(project_data["code"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ActiveMetadataSchedulerDeliveryError(
                    "DolphinScheduler project code is invalid"
                ) from exc
            access_token = secrets.token_urlsafe(32)
            expires_at = datetime.now(UTC) + timedelta(days=1)
            self._api_data(
                client.post(
                    f"{self.base_url}/access-tokens",
                    data={
                        "userId": "1",
                        "expireTime": expires_at.strftime("%Y-%m-%d %H:%M:%S"),
                        "token": access_token,
                    },
                )
            )
            return project_code, SecretStr(access_token)


def run_managed_rehearsal(
    database_admin_url: str,
    dependency_evidence: dict[str, Any],
    admin_password: SecretStr,
    *,
    readiness_timeout_seconds: float = 180,
    terminal_timeout_seconds: float = 600,
) -> dict[str, Any]:
    database = EphemeralPostgresDatabase(database_admin_url)
    scheduler = EphemeralDolphinScheduler(
        admin_password,
        readiness_timeout=readiness_timeout_seconds,
    )
    evidence: dict[str, Any] | None = None
    with database:
        with scheduler:
            project_code, access_token = scheduler.provision_project()
            profile = DolphinSchedulerProfile(
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
                raise ActiveMetadataSchedulerDeliveryError(
                    "temporary PostgreSQL database was not created"
                )
            evidence = run_local_rehearsal(
                database.database_url,
                profile,
                dependency_evidence,
                terminal_timeout_seconds=terminal_timeout_seconds,
            )
    if evidence is None:
        raise ActiveMetadataSchedulerDeliveryError(
            "local scheduler delivery produced no evidence"
        )
    evidence["standalone_container_cleanup_verified"] = scheduler.cleanup_verified
    evidence["temporary_database_cleanup_verified"] = database.cleanup_verified
    if not scheduler.cleanup_verified or not database.cleanup_verified:
        evidence["errors"].append("ephemeral runtime cleanup failed")
        evidence["status"] = "blocked"
        evidence["local_scheduler_submission_readback_verified"] = False
    stable = {key: value for key, value in evidence.items() if key != "evidence_sha256"}
    return {**stable, "evidence_sha256": canonical_json_fingerprint(stable)}


def validate_rehearsal_evidence(evidence: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    stable = {key: value for key, value in evidence.items() if key != "evidence_sha256"}
    if evidence.get("schema") != EVIDENCE_SCHEMA:
        errors.append("scheduler delivery evidence schema does not match")
    if evidence.get("evidence_sha256") != canonical_json_fingerprint(stable):
        errors.append("scheduler delivery evidence SHA-256 does not match")
    contract = build_contract_report()
    if evidence.get("contract_sha256") != contract.get("contract_sha256"):
        errors.append("scheduler delivery contract fingerprint is stale")
    try:
        dependency = _load_json_object(DEFAULT_DEPENDENCY_EVIDENCE_PATH)
    except (OSError, ValueError, ActiveMetadataSchedulerDeliveryError):
        dependency = {}
        errors.append("M3-16 dependency evidence is unavailable")
    if evidence.get("dependency_evidence_sha256") != dependency.get(
        "evidence_sha256"
    ):
        errors.append("scheduler delivery dependency fingerprint is stale")
    dataset = evidence.get("dataset_bundle")
    if not isinstance(dataset, dict):
        errors.append("scheduler delivery dataset bundle is missing")
    else:
        errors.extend(validate_shapefile_bundle_inventory(dataset))
        if evidence.get("resource_version_content_sha256") != dataset.get(
            "content_sha256"
        ):
            errors.append("real dataset fingerprint is not bound to ResourceVersion")
    for claim in FALSE_CLAIMS:
        if evidence.get(claim) is not False:
            errors.append(f"local scheduler delivery may not claim {claim}")
    for claim in (
        "real_dataset_resource_version_bound",
        "authorization_created",
        "exact_correlation_variable_readback_verified",
        "provider_success_readback_verified",
        "provider_workflow_definition_created",
        "provider_workflow_instance_executed",
        "no_side_effect_workflow_verified",
        "local_scheduler_submission_readback_verified",
        "standalone_container_cleanup_verified",
        "temporary_database_cleanup_verified",
    ):
        if evidence.get(claim) is not True:
            errors.append(f"scheduler delivery did not verify {claim}")
    if evidence.get("exact_authorization_replay_created") is not False:
        errors.append("authorization replay must not create a row")
    if evidence.get("command_status") != "done":
        errors.append("authorized dispatch command must be done")
    if evidence.get("command_claimed_count") != 1:
        errors.append("scheduler delivery must claim one command")
    if evidence.get("command_completed_count") != 1:
        errors.append("scheduler delivery must complete one command")
    provider = evidence.get("provider")
    if not isinstance(provider, dict):
        errors.append("scheduler provider evidence is missing")
    else:
        expected = {
            "name": "apache-dolphinscheduler",
            "server_version": DOLPHINSCHEDULER_SERVER_VERSION,
            "api_profile": DOLPHINSCHEDULER_API_PROFILE,
            "image": IMAGE,
            "image_id": IMAGE_ID,
            "terminal_state": "SUCCESS",
        }
        if any(provider.get(key) != value for key, value in expected.items()):
            errors.append("scheduler provider identity or state does not match")
    if evidence.get("matching_provider_instance_count") != 1:
        errors.append("scheduler delivery must read back one correlated instance")
    if evidence.get("attempt_observation_count") != 2:
        errors.append("scheduler delivery must record two attempt observations")
    if evidence.get("external_correlation_count") != 1:
        errors.append("scheduler delivery must retain one external correlation")
    if evidence.get("submitted_observation_count") != 1:
        errors.append("scheduler delivery must record submission evidence")
    if evidence.get("success_observation_count") != 1:
        errors.append("scheduler delivery must record provider success evidence")
    if evidence.get("attempt_states") != ["submitted", "success"]:
        errors.append("scheduler delivery attempt states do not match")
    if evidence.get("platform_run_status") != "reconciling":
        errors.append("provider success must leave PlatformRun reconciling")
    if evidence.get("platform_run_succeeded") is not False:
        errors.append("local provider success may not claim platform success")
    serialized = json.dumps(evidence, ensure_ascii=True, sort_keys=True)
    for forbidden in ("/Users/", "Downloads/", ".tmp/", '"token"', '"password"', '"session"'):
        if forbidden in serialized:
            errors.append("scheduler delivery evidence contains sensitive local material")
            break
    return errors


def _read_admin_password(environment_name: str) -> SecretStr:
    value = os.environ.get(environment_name, "")
    if not value:
        raise ActiveMetadataSchedulerDeliveryError(
            f"{environment_name} must provide the standalone admin password"
        )
    return SecretStr(value)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate")
    validate.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE_PATH)
    rehearse = subparsers.add_parser("rehearse")
    rehearse.add_argument("--database-admin-url", required=True)
    rehearse.add_argument(
        "--admin-password-env",
        default="GDA_DOLPHINSCHEDULER_ADMIN_PASSWORD",
    )
    rehearse.add_argument(
        "--dependency-evidence",
        type=Path,
        default=DEFAULT_DEPENDENCY_EVIDENCE_PATH,
    )
    rehearse.add_argument("--readiness-timeout-seconds", type=float, default=180)
    rehearse.add_argument("--terminal-timeout-seconds", type=float, default=600)
    rehearse.add_argument("--evidence-out", type=Path, required=True)
    args = parser.parse_args(argv)

    if args.command == "validate":
        report = build_contract_report()
        try:
            report["errors"].extend(
                validate_rehearsal_evidence(_load_json_object(args.evidence))
            )
        except (OSError, ValueError, ActiveMetadataSchedulerDeliveryError) as exc:
            report["errors"].append(
                f"scheduler delivery evidence is invalid: {type(exc).__name__}"
            )
        report["status"] = "valid" if not report["errors"] else "invalid"
        print(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True))
        return 0 if not report["errors"] else 1

    dependency = _load_json_object(args.dependency_evidence)
    evidence = run_managed_rehearsal(
        args.database_admin_url,
        dependency,
        _read_admin_password(args.admin_password_env),
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
