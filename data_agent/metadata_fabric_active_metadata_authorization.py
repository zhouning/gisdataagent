"""Validate and rehearse evidence-bound Active Metadata dispatch promotion."""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from .active_metadata_authorization import (
    MetadataActivationAuthorization,
    build_metadata_activation_authorization,
)
from .active_metadata_change_contract import (
    ActiveMetadataRegistration,
    MetadataActivationRequest,
    build_active_metadata_registration,
    build_metadata_activation_intent,
    build_metadata_activation_request,
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
    SubjectContext,
    canonical_json_fingerprint,
    platform_definition_fingerprint,
)
from .platform_gateway import (
    DefinitionRegistration,
    GatewayNotFoundError,
    GatewayValidationError,
    PlatformGateway,
)
from .spatial_dataset_bundle import (
    build_shapefile_bundle_inventory,
    validate_shapefile_bundle_inventory,
)

CONTRACT_SCHEMA = "gda.active_metadata_authorization_contract.v1"
EVIDENCE_SCHEMA = "gda.active_metadata_authorization_evidence.v1"
REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_EVIDENCE_PATH = (
    REPO_ROOT
    / "docs/evidence/metadata-fabric-active-metadata-authorization-2026-07-30.json"
)
DEFAULT_WRAPPER_PATH = (
    REPO_ROOT / "scripts/metadata-fabric-active-metadata-authorization.sh"
)
TENANT = "metadata-authorization-local"
CONSUMER_SUBJECT = "workload:active-metadata-consumer"
WORKER = "worker:active-metadata-consumer-1"
AUTHORIZER = "workload:metadata-activation-authorizer"
SOURCE_ID = UUID("a6000000-0000-4000-8000-000000000001")
DEFINITION_ID = UUID("a6000000-0000-4000-8000-000000000002")
RUN_ID = UUID("a6000000-0000-4000-8000-000000000003")
PLAN_ID = UUID("a6000000-0000-4000-8000-000000000004")
REHEARSAL_TIME = datetime(2026, 7, 30, 8, 0, tzinfo=UTC)
MIGRATIONS = tuple(
    Path(__file__).resolve().parent / "migrations" / filename
    for filename in (
        "092_platform_control_ledger.sql",
        "093_app_user_tenant_context.sql",
        "094_platform_control_gateway.sql",
        "095_platform_command_outbox.sql",
        "096_platform_success_verdict.sql",
        "099_active_metadata_change_outbox.sql",
        "100_active_metadata_activation_request.sql",
        "101_active_metadata_authorization.sql",
    )
)


class ActiveMetadataAuthorizationEvidenceError(RuntimeError):
    """The authorization contract or local rehearsal failed closed."""


@dataclass(frozen=True)
class AuthorizationBundle:
    source_resource: Resource
    registration: ActiveMetadataRegistration
    request: MetadataActivationRequest
    definition_registration: DefinitionRegistration
    execution_plan: Artifact
    policy_decision: Artifact
    approval: Artifact
    run: PlatformRun
    authorization: MetadataActivationAuthorization


def build_authorization_bundle(content_sha256: str) -> AuthorizationBundle:
    source_urn = f"gda://{TENANT}/dataset/chongqing-cultural-districts"
    source_resource = Resource(
        tenant_id=TENANT,
        resource_urn=source_urn,
        resource_kind="dataset",
        authority_system="local_acceptance_bundle",
        authority_locator="chongqing-cultural-districts",
        owner_ref="team:metadata-platform",
        governance_ref={"claim_level": "acceptance_input_only"},
    )
    source_version = ResourceVersion(
        tenant_id=TENANT,
        resource_urn=source_urn,
        resource_version_id=SOURCE_ID,
        version_key="cultural-district-bundle-v1",
        content_sha256=content_sha256,
        authority_version_ref={
            "source_label": "chongqing-central-cultural-districts",
            "path_committed": False,
        },
        created_by="workload:metadata-registrar",
        created_at=REHEARSAL_TIME - timedelta(hours=2),
    )
    registration = build_active_metadata_registration(
        source_version,
        consumer_subject=CONSUMER_SUBJECT,
    )
    request = build_metadata_activation_request(
        build_metadata_activation_intent(
            registration.event,
            routed_by=CONSUMER_SUBJECT,
        )
    )

    definition_urn = f"gda://{TENANT}/definition/metadata-projection"
    definition_document = {"tasks": ["project-governance-metadata"]}
    input_contract = {"metadata_change": "dataset"}
    output_contract = {"projection_plan": "artifact"}
    definition_sha256 = platform_definition_fingerprint(
        orchestration_class="dataops",
        capability_id="metadata_fabric.projection_plan",
        portability_class="portable",
        definition_document=definition_document,
        input_contract=input_contract,
        output_contract=output_contract,
    )
    definition_resource = Resource(
        tenant_id=TENANT,
        resource_urn=definition_urn,
        resource_kind="definition",
        authority_system="gda",
        authority_locator="definition/metadata-projection",
        owner_ref="team:metadata-platform",
    )
    definition_version = ResourceVersion(
        tenant_id=TENANT,
        resource_urn=definition_urn,
        resource_version_id=DEFINITION_ID,
        version_key="v1",
        content_sha256=definition_sha256,
        authority_version_ref={"definition_revision": 1},
        created_by="workload:metadata-definition-registrar",
        created_at=REHEARSAL_TIME - timedelta(hours=2),
    )
    definition = PlatformDefinitionVersion(
        tenant_id=TENANT,
        definition_urn=definition_urn,
        definition_version_id=DEFINITION_ID,
        orchestration_class="dataops",
        capability_id="metadata_fabric.projection_plan",
        portability_class="portable",
        definition_document=definition_document,
        input_contract=input_contract,
        output_contract=output_contract,
        definition_sha256=definition_sha256,
    )
    definition_registration = DefinitionRegistration(
        resource=definition_resource,
        resource_version=definition_version,
        definition=definition,
    )
    plan_manifest = {
        "schema": "gda.metadata_projection_execution_plan.v1",
        "route": "metadata_fabric.projection_plan",
    }
    execution_plan = Artifact(
        tenant_id=TENANT,
        artifact_id=PLAN_ID,
        artifact_key="metadata-projection-plan",
        artifact_role="execution_plan",
        storage_uri=f"postgresql://gda-control/execution-plans/{TENANT}/{PLAN_ID}",
        media_type="application/vnd.gda.metadata-projection-plan+json",
        content_sha256=canonical_json_fingerprint(plan_manifest),
        size_bytes=len(
            json.dumps(
                plan_manifest,
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ),
        resource_version_id=DEFINITION_ID,
        manifest=plan_manifest,
        created_by="workload:metadata-plan-compiler",
        created_at=REHEARSAL_TIME - timedelta(hours=1),
    )
    subject = SubjectContext(
        tenant_id=TENANT,
        subject_id="metadata-projection-runner",
        subject_type="workload",
        roles=("metadata_projector",),
        purpose="project active metadata change",
    )
    decision = PolicyDecision(
        tenant_id=TENANT,
        run_id=RUN_ID,
        subject_context=subject,
        action="dolphinscheduler.dispatch",
        definition_version_id=DEFINITION_ID,
        resource_version_ids=(DEFINITION_ID, SOURCE_ID),
        execution_plan_artifact_id=PLAN_ID,
        effect="allow",
        policy_version_ref=f"gda://{TENANT}/policy/metadata-dispatch-v1",
        evaluator_subject="workload:metadata-policy-evaluator",
        requires_approval=True,
        decided_at=REHEARSAL_TIME - timedelta(minutes=30),
        expires_at=REHEARSAL_TIME + timedelta(days=365),
    )
    policy_decision = build_policy_decision_artifact(decision)
    approval_record = ApprovalRecord(
        tenant_id=TENANT,
        run_id=RUN_ID,
        definition_version_id=DEFINITION_ID,
        policy_decision_artifact_id=policy_decision.artifact_id,
        policy_decision_sha256=policy_decision.content_sha256,
        verdict="approved",
        approver_subject="human:metadata-governance-approver",
        reason="approved bounded metadata projection",
        decided_at=REHEARSAL_TIME - timedelta(minutes=20),
        expires_at=REHEARSAL_TIME + timedelta(days=180),
    )
    approval = build_approval_artifact(approval_record)
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
        idempotency_key="metadata-projection:cultural-districts:v1",
        policy_refs=RunPolicyReferences(
            policy_decision_artifact_id=policy_decision.artifact_id,
            approval_artifact_id=approval.artifact_id,
        ),
        submitted_at=REHEARSAL_TIME - timedelta(minutes=10),
    )
    authorization = build_metadata_activation_authorization(
        request,
        source_version,
        definition,
        run,
        execution_plan,
        policy_decision,
        approval,
        authorized_by=AUTHORIZER,
        authorized_at=REHEARSAL_TIME,
    )
    return AuthorizationBundle(
        source_resource=source_resource,
        registration=registration,
        request=request,
        definition_registration=definition_registration,
        execution_plan=execution_plan,
        policy_decision=policy_decision,
        approval=approval,
        run=run,
        authorization=authorization,
    )


def _load_json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ActiveMetadataAuthorizationEvidenceError(
            f"{path.name} must contain an object"
        )
    return value


def build_contract_report() -> dict[str, Any]:
    errors: list[str] = []
    paths = {
        "authorization_contract": Path(__file__).resolve().parent
        / "active_metadata_authorization.py",
        "dataset_bundle": Path(__file__).resolve().parent
        / "spatial_dataset_bundle.py",
        "gateway": Path(__file__).resolve().parent / "platform_gateway.py",
        "migration": Path(__file__).resolve().parent
        / "migrations/101_active_metadata_authorization.sql",
        "rehearsal": Path(__file__).resolve(),
        "wrapper": DEFAULT_WRAPPER_PATH,
    }
    required = {
        "authorization_contract": (
            "class MetadataActivationAuthorization",
            "build_metadata_activation_authorization",
            "Active Metadata dispatch requires approval evidence",
            "scheduler_command_enqueued: Literal[True]",
            "production_ready: Literal[False]",
        ),
        "dataset_bundle": (
            "build_shapefile_bundle_inventory",
            "validate_shapefile_bundle_inventory",
            "content_sha256",
        ),
        "gateway": (
            "def authorize_metadata_activation(",
            "Active Metadata dispatch requires activation authorization",
            "metadata_activation_authorization_id",
        ),
        "migration": (
            "CREATE TABLE IF NOT EXISTS gda_control.metadata_activation_authorization",
            "DEFERRABLE INITIALLY DEFERRED",
            "authorize_metadata_activation",
            "guard_active_metadata_dispatch",
            "Active Metadata dispatch requires exact authorization",
            "FORCE ROW LEVEL SECURITY",
        ),
        "rehearsal": (
            "def run_local_rehearsal(",
            "orphan_authorization_rollback_verified",
            "real_dataset_resource_version_bound",
        ),
        "wrapper": (
            "data_agent.metadata_fabric_active_metadata_authorization",
            '"$@"',
        ),
    }
    files: dict[str, dict[str, Any]] = {}
    for name, path in paths.items():
        if not path.is_file():
            errors.append(f"{name} is missing")
            files[name] = {
                "path": path.resolve().relative_to(REPO_ROOT).as_posix(),
                "sha256": None,
            }
            continue
        raw = path.read_bytes()
        source = raw.decode("utf-8")
        files[name] = {
            "path": path.resolve().relative_to(REPO_ROOT).as_posix(),
            "sha256": hashlib.sha256(raw).hexdigest(),
        }
        if any(marker not in source for marker in required[name]):
            errors.append(f"{name} is missing required authorization markers")
    stable = {
        "schema": CONTRACT_SCHEMA,
        "activation_route": "metadata_fabric.projection_plan",
        "promotion_boundary": "authorization_and_dispatch_same_transaction",
        "approval_required": True,
        "real_data_role": "acceptance_input_and_resource_version_fingerprint",
        "files": files,
        "errors": errors,
    }
    return {
        **stable,
        "status": "valid" if not errors else "invalid",
        "contract_sha256": canonical_json_fingerprint(stable),
        "provider_apply_authorized": False,
        "provider_mutations_executed": False,
        "production_scheduler_submission_verified": False,
        "production_ingestion_verified": False,
        "production_ready": False,
    }


def _apply_migrations(engine: Any) -> None:
    with engine.begin() as connection:
        is_superuser = connection.exec_driver_sql(
            "SELECT rolsuper FROM pg_roles WHERE rolname = current_user"
        ).scalar_one()
        if not is_superuser:
            raise ActiveMetadataAuthorizationEvidenceError(
                "local authorization rehearsal requires a fresh superuser database"
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


def run_local_rehearsal(
    database_url: str,
    dataset_inventory: dict[str, Any],
) -> dict[str, Any]:
    if validate_shapefile_bundle_inventory(dataset_inventory):
        raise ActiveMetadataAuthorizationEvidenceError(
            "real dataset bundle inventory is invalid"
        )
    bundle = build_authorization_bundle(dataset_inventory["content_sha256"])
    engine = create_engine(database_url)
    try:
        _apply_migrations(engine)
        gateway = PlatformGateway(engine)
        gateway.register_resource(bundle.source_resource)
        gateway.register_resource_version_with_metadata_event(bundle.registration)
        claimed = gateway.claim_metadata_changes(
            TENANT,
            WORKER,
            consumer_subject=CONSUMER_SUBJECT,
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

        ordinary_dispatch_blocked = False
        try:
            gateway.submit_run(bundle.run, request_dispatch=True)
        except GatewayValidationError:
            ordinary_dispatch_blocked = True

        orphan_authorization_rollback_verified = False
        try:
            with gateway._transaction(TENANT) as connection:
                connection.execute(
                    text(
                        """
                        SELECT * FROM gda_control.authorize_metadata_activation(
                            :tenant_id, CAST(:authorization AS jsonb)
                        )
                        """
                    ),
                    {
                        "tenant_id": TENANT,
                        "authorization": json.dumps(
                            bundle.authorization.model_dump(
                                mode="json", by_alias=True
                            ),
                            ensure_ascii=True,
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                    },
                ).one()
        except GatewayValidationError:
            orphan_authorization_rollback_verified = True

        authorization_absent_after_rollback = False
        try:
            gateway.get_metadata_activation_authorization(
                TENANT, bundle.authorization.authorization_id
            )
        except GatewayNotFoundError:
            authorization_absent_after_rollback = True

        first = gateway.authorize_metadata_activation(bundle.authorization)
        replay = gateway.authorize_metadata_activation(bundle.authorization)
        stored = gateway.get_metadata_activation_authorization(
            TENANT, bundle.authorization.authorization_id
        )
        command = gateway.get_command(TENANT, bundle.authorization.command_id)

        direct_mutation_blocked = True
        with gateway._transaction(TENANT) as connection:
            for statement in (
                """
                UPDATE gda_control.metadata_activation_authorization
                SET status = 'authorized_for_dispatch'
                WHERE authorization_id = :authorization_id
                """,
                """
                DELETE FROM gda_control.metadata_activation_authorization
                WHERE authorization_id = :authorization_id
                """,
            ):
                try:
                    with connection.begin_nested():
                        connection.execute(
                            text(statement),
                            {
                                "authorization_id": (
                                    bundle.authorization.authorization_id
                                )
                            },
                        )
                except DBAPIError:
                    continue
                direct_mutation_blocked = False

        with engine.connect() as connection:
            privileges = connection.exec_driver_sql(
                """
                SELECT
                    has_table_privilege(
                        'gda_control_gateway',
                        'gda_control.metadata_activation_authorization', 'SELECT'
                    ),
                    NOT has_table_privilege(
                        'gda_control_gateway',
                        'gda_control.metadata_activation_authorization', 'INSERT'
                    ),
                    NOT has_table_privilege(
                        'gda_control_gateway',
                        'gda_control.metadata_activation_authorization', 'UPDATE'
                    ),
                    NOT has_table_privilege(
                        'gda_control_gateway',
                        'gda_control.metadata_activation_authorization', 'DELETE'
                    ),
                    has_function_privilege(
                        'gda_control_gateway',
                        'gda_control.authorize_metadata_activation(text,jsonb)',
                        'EXECUTE'
                    )
                """
            ).one()
            force_rls = connection.exec_driver_sql(
                """
                SELECT relforcerowsecurity
                FROM pg_class
                WHERE oid =
                    'gda_control.metadata_activation_authorization'::regclass
                """
            ).scalar_one()
            counts = connection.execute(
                text(
                    """
                    SELECT
                        (
                            SELECT count(*)
                            FROM gda_control.metadata_activation_authorization
                            WHERE tenant_id = :tenant_id
                        ) AS authorizations,
                        (
                            SELECT count(*)
                            FROM gda_control.platform_command_outbox
                            WHERE tenant_id = :tenant_id
                              AND command_type = 'dolphinscheduler.dispatch'
                        ) AS dispatch_commands
                    """
                ),
                {"tenant_id": TENANT},
            ).one()
    finally:
        engine.dispose()

    real_dataset_resource_version_bound = (
        bundle.registration.resource_version.content_sha256
        == dataset_inventory["content_sha256"]
        == stored.content_sha256
    )
    verified = (
        len(claimed) == 1
        and ordinary_dispatch_blocked
        and orphan_authorization_rollback_verified
        and authorization_absent_after_rollback
        and first.created
        and not replay.created
        and replay.value == stored == bundle.authorization
        and counts.authorizations == counts.dispatch_commands == 1
        and command.status.value == "pending"
        and command.payload.get("metadata_activation_authorization_id")
        == str(bundle.authorization.authorization_id)
        and direct_mutation_blocked
        and privileges == (True, True, True, True, True)
        and bool(force_rls)
        and real_dataset_resource_version_bound
    )
    contract = build_contract_report()
    stable = {
        "schema": EVIDENCE_SCHEMA,
        "status": (
            "local_real_data_authorization_dispatch_verified"
            if verified
            else "blocked"
        ),
        "contract_sha256": contract["contract_sha256"],
        "dataset_bundle": dataset_inventory,
        "dataset_source_committed": False,
        "dataset_absolute_path_committed": False,
        "dataset_required_in_ci": False,
        "real_dataset_inspected": dataset_inventory.get("spatial_inventory")
        is not None,
        "real_dataset_resource_version_bound": real_dataset_resource_version_bound,
        "request_id": str(bundle.request.request_id),
        "resource_version_id": str(SOURCE_ID),
        "resource_version_content_sha256": (
            bundle.registration.resource_version.content_sha256
        ),
        "definition_version_id": str(DEFINITION_ID),
        "run_id": str(RUN_ID),
        "execution_plan_artifact_id": str(PLAN_ID),
        "policy_decision_artifact_id": str(bundle.policy_decision.artifact_id),
        "approval_artifact_id": str(bundle.approval.artifact_id),
        "authorization_id": str(bundle.authorization.authorization_id),
        "authorization_sha256": bundle.authorization.authorization_sha256,
        "command_id": str(bundle.authorization.command_id),
        "authorization_count": counts.authorizations,
        "dispatch_command_count": counts.dispatch_commands,
        "dispatch_command_status": command.status.value,
        "ordinary_dispatch_without_activation_authorization_blocked": (
            ordinary_dispatch_blocked
        ),
        "orphan_authorization_rollback_verified": (
            orphan_authorization_rollback_verified
        ),
        "authorization_absent_after_rollback": (
            authorization_absent_after_rollback
        ),
        "exact_authorization_replay_created": replay.created,
        "gateway_function_only_insert_verified": privileges
        == (True, True, True, True, True),
        "direct_authorization_mutation_blocked": direct_mutation_blocked,
        "force_rls_verified": bool(force_rls),
        "local_postgresql_authorization_dispatch_verified": verified,
        "deployment_applied": False,
        "production_workload_identity_verified": False,
        "provider_apply_authorized": False,
        "provider_mutations_executed": False,
        "production_scheduler_submission_verified": False,
        "production_ingestion_verified": False,
        "production_ready": False,
        "errors": [] if verified else ["local authorization rehearsal failed"],
    }
    return {**stable, "evidence_sha256": canonical_json_fingerprint(stable)}


def validate_rehearsal_evidence(evidence: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    stable = {key: value for key, value in evidence.items() if key != "evidence_sha256"}
    if evidence.get("schema") != EVIDENCE_SCHEMA:
        errors.append("Active Metadata authorization evidence schema does not match")
    if evidence.get("evidence_sha256") != canonical_json_fingerprint(stable):
        errors.append("Active Metadata authorization evidence SHA-256 does not match")
    contract = build_contract_report()
    if evidence.get("contract_sha256") != contract.get("contract_sha256"):
        errors.append("Active Metadata authorization contract fingerprint is stale")
    dataset = evidence.get("dataset_bundle")
    if not isinstance(dataset, dict):
        errors.append("Active Metadata authorization dataset bundle is missing")
    else:
        errors.extend(validate_shapefile_bundle_inventory(dataset))
        if evidence.get("resource_version_content_sha256") != dataset.get(
            "content_sha256"
        ):
            errors.append("real dataset fingerprint is not bound to ResourceVersion")
    for claim in (
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
    ):
        if evidence.get(claim) is not False:
            errors.append(f"local authorization evidence may not claim {claim}")
    for claim in (
        "real_dataset_inspected",
        "real_dataset_resource_version_bound",
        "ordinary_dispatch_without_activation_authorization_blocked",
        "orphan_authorization_rollback_verified",
        "authorization_absent_after_rollback",
        "gateway_function_only_insert_verified",
        "direct_authorization_mutation_blocked",
        "force_rls_verified",
        "local_postgresql_authorization_dispatch_verified",
    ):
        if evidence.get(claim) is not True:
            errors.append(f"Active Metadata authorization did not verify {claim}")
    if evidence.get("authorization_count") != 1:
        errors.append("authorization evidence must contain one authorization")
    if evidence.get("dispatch_command_count") != 1:
        errors.append("authorization evidence must contain one dispatch command")
    if evidence.get("dispatch_command_status") != "pending":
        errors.append("local dispatch command must remain pending")
    if evidence.get("exact_authorization_replay_created") is not False:
        errors.append("authorization replay must not create a row")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate")
    validate.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE_PATH)
    rehearse = subparsers.add_parser("rehearse")
    rehearse.add_argument("--database-url", required=True)
    rehearse.add_argument("--shapefile", type=Path, required=True)
    rehearse.add_argument("--source-label", required=True)
    rehearse.add_argument("--ogrinfo", type=Path, required=True)
    rehearse.add_argument("--proj-data", type=Path)
    rehearse.add_argument("--evidence-out", type=Path, required=True)
    args = parser.parse_args(argv)

    if args.command == "validate":
        report = build_contract_report()
        try:
            report["errors"].extend(
                validate_rehearsal_evidence(_load_json_object(args.evidence))
            )
        except (OSError, ValueError) as exc:
            report["errors"].append(
                f"Active Metadata authorization evidence is invalid: {type(exc).__name__}"
            )
        report["status"] = "valid" if not report["errors"] else "invalid"
        print(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True))
        return 0 if not report["errors"] else 1

    inventory = build_shapefile_bundle_inventory(
        args.shapefile,
        source_label=args.source_label,
        ogrinfo_path=args.ogrinfo,
        proj_data_path=args.proj_data,
    )
    evidence = run_local_rehearsal(args.database_url, inventory)
    args.evidence_out.write_text(
        json.dumps(evidence, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(evidence, ensure_ascii=True, indent=2, sort_keys=True))
    return 0 if not evidence["errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
