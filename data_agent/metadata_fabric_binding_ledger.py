"""Persist the verified M3-2 provider binding through PlatformGateway."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import create_engine, text

from . import metadata_fabric_bridge as bridge
from . import metadata_fabric_ingestion as ingestion
from . import metadata_fabric_ingestion_replay as replay
from .metadata_fabric_binding_contract import (
    MetadataFabricBindingRecord,
    build_metadata_fabric_binding_record,
    build_metadata_fabric_provider_evidence,
    build_metadata_fabric_provider_evidence_artifact,
)
from .platform_contracts import (
    Artifact,
    PlatformDefinitionVersion,
    Resource,
    ResourceVersion,
    canonical_json_fingerprint,
)
from .platform_gateway import (
    DefinitionRegistration,
    GatewayNotFoundError,
    PlatformGateway,
)

LEDGER_CONTRACT_SCHEMA = "gda.metadata_fabric_binding_ledger_contract.v1"
LEDGER_EVIDENCE_SCHEMA = "gda.metadata_fabric_binding_ledger_evidence.v1"

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE_EVIDENCE = (
    REPO_ROOT / "docs/evidence/metadata-fabric-ingestion-replay-2026-07-28.json"
)
DEFAULT_EVIDENCE_PATH = (
    REPO_ROOT / "docs/evidence/metadata-fabric-binding-ledger-2026-07-28.json"
)
DEFAULT_WRAPPER_PATH = REPO_ROOT / "scripts/metadata-fabric-binding-ledger.sh"
PLATFORM_FIXTURE = ingestion.DEFAULT_PLATFORM_FIXTURE
MIGRATIONS = tuple(
    Path(__file__).resolve().parent / "migrations" / filename
    for filename in (
        "092_platform_control_ledger.sql",
        "093_app_user_tenant_context.sql",
        "094_platform_control_gateway.sql",
        "095_platform_command_outbox.sql",
        "096_platform_success_verdict.sql",
        "097_metadata_fabric_binding_ledger.sql",
    )
)


class MetadataFabricBindingLedgerError(RuntimeError):
    """The source evidence or binding ledger rehearsal failed closed."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class BindingLedgerBundle(_FrozenModel):
    resources: tuple[Resource, ...]
    resource_versions: tuple[ResourceVersion, ...]
    definition: PlatformDefinitionVersion
    artifacts: tuple[Artifact, ...]
    record: MetadataFabricBindingRecord
    source_evidence_sha256: str


def _load_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise MetadataFabricBindingLedgerError(f"{path.name} must contain an object")
    return payload


def _source_outcome_identity(outcome: dict[str, Any]) -> tuple[str, str, str]:
    openmetadata = outcome.get("openmetadata", {})
    gravitino = outcome.get("gravitino", {})
    open_identity = (
        openmetadata.get("resource_urn"),
        openmetadata.get("resource_version_id"),
        openmetadata.get("content_sha256"),
    )
    technical_identity = (
        gravitino.get("resource_urn"),
        gravitino.get("resource_version_id"),
        gravitino.get("content_sha256"),
    )
    if open_identity != technical_identity or not all(open_identity):
        raise MetadataFabricBindingLedgerError(
            "M3-2 provider observations do not share one GDA identity"
        )
    return open_identity


def build_binding_ledger_bundle(
    source_evidence_path: Path = DEFAULT_SOURCE_EVIDENCE,
) -> BindingLedgerBundle:
    source = _load_json_object(source_evidence_path.resolve())
    source_errors = replay.verify_evidence_integrity(source)
    if source_errors:
        raise MetadataFabricBindingLedgerError(
            "M3-2 evidence is invalid: " + ", ".join(source_errors)
        )
    observation = source.get("observation")
    if not isinstance(observation, dict):
        raise MetadataFabricBindingLedgerError("M3-2 observation is missing")
    first = observation.get("first_apply")
    second = observation.get("replay")
    authorization_observation = observation.get("authorization")
    if not all(
        isinstance(value, dict)
        for value in (first, second, authorization_observation)
    ):
        raise MetadataFabricBindingLedgerError(
            "M3-2 apply and authorization observations are incomplete"
        )
    if (
        first.get("status") != "created"
        or first.get("mutation_count", 0) <= 0
        or second.get("status") != "no_op"
        or second.get("mutation_count") != 0
        or first.get("binding_candidate_sha256")
        != second.get("binding_candidate_sha256")
    ):
        raise MetadataFabricBindingLedgerError(
            "M3-2 evidence does not prove stable zero-mutation replay"
        )
    observed_at = datetime.fromisoformat(str(observation["observed_at"]))
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise MetadataFabricBindingLedgerError(
            "M3-2 observation time must include a timezone"
        )
    observed_at = observed_at.astimezone(UTC)

    profile, plan, run, target, authorization = replay._build_contract_inputs()
    replay.validate_apply_authorization(plan, run, authorization, at=observed_at)
    expected_artifact_ids = {
        "execution_plan_artifact_id": authorization.execution_plan_artifact.artifact_id,
        "policy_decision_artifact_id": (
            authorization.policy_decision_artifact.artifact_id
        ),
        "approval_artifact_id": authorization.approval_artifact.artifact_id,
    }
    for name, artifact_id in expected_artifact_ids.items():
        if authorization_observation.get(name) != str(artifact_id):
            raise MetadataFabricBindingLedgerError(
                f"M3-2 {name} does not match the deterministic contract"
            )

    identity = _source_outcome_identity(first)
    if identity != (
        plan.resource_urn,
        str(plan.resource_version_id),
        plan.content_sha256,
    ):
        raise MetadataFabricBindingLedgerError(
            "M3-2 provider identity does not match the execution plan"
        )
    if _source_outcome_identity(second) != identity:
        raise MetadataFabricBindingLedgerError(
            "M3-2 provider identity drifted during replay"
        )

    openmetadata_observation = first["openmetadata"]
    gravitino_observation = first["gravitino"]
    openmetadata_ref = bridge.OpenMetadataTableRef(
        entity_id=UUID(openmetadata_observation["entity_id"]),
        fully_qualified_name=openmetadata_observation["fully_qualified_name"],
        entity_version=openmetadata_observation["entity_version"],
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

    platform_payload = _load_json_object(PLATFORM_FIXTURE)
    contracts = platform_payload["contracts"]
    resources = tuple(Resource.model_validate(item) for item in contracts["resources"])
    definition_version = ResourceVersion.model_validate(
        contracts["definition_resource_version"]
    )
    source_version = ResourceVersion.model_validate(
        contracts["source_resource_version"]
    )
    if target != ResourceVersion.model_validate(contracts["target_resource_version"]):
        raise MetadataFabricBindingLedgerError(
            "M3-2 target ResourceVersion drifted from platform truth fixture"
        )
    target_resource = next(
        item for item in resources if item.resource_urn == target.resource_urn
    ).model_copy(
        update={
            "governance_ref": bridge.openmetadata_governance_ref(openmetadata_ref),
            "technical_refs": (bridge.gravitino_technical_ref(gravitino_ref),),
        }
    )
    live_resources = tuple(
        target_resource if item.resource_urn == target.resource_urn else item
        for item in resources
    )
    binding = bridge.build_metadata_fabric_binding(
        target_resource,
        target,
        openmetadata=openmetadata_ref,
        gravitino=(gravitino_ref,),
    )
    if binding.binding_sha256 != first["binding_candidate_sha256"]:
        raise MetadataFabricBindingLedgerError(
            "M3-2 binding candidate does not match the provider read-back"
        )

    provider_evidence = build_metadata_fabric_provider_evidence(
        binding=binding,
        source_evidence_sha256=source["evidence_fingerprint"],
        openmetadata_snapshot_sha256=openmetadata_observation["snapshot_sha256"],
        gravitino_snapshot_sha256=gravitino_observation["snapshot_sha256"],
        first_apply_status=first["status"],
        first_apply_mutation_count=first["mutation_count"],
        observed_at=observed_at,
    )
    executor = authorization_observation["executor_subject"]
    provider_artifact = build_metadata_fabric_provider_evidence_artifact(
        provider_evidence,
        created_by=executor,
    )
    record = build_metadata_fabric_binding_record(
        binding=binding,
        execution_plan_artifact_id=authorization.execution_plan_artifact.artifact_id,
        policy_decision_artifact_id=authorization.policy_decision_artifact.artifact_id,
        approval_artifact_id=authorization.approval_artifact.artifact_id,
        provider_evidence_artifact_id=provider_artifact.artifact_id,
        recorded_by=executor,
        recorded_at=observed_at,
    )
    return BindingLedgerBundle(
        resources=live_resources,
        resource_versions=(definition_version, source_version, target),
        definition=PlatformDefinitionVersion.model_validate(contracts["definition"]),
        artifacts=(
            authorization.execution_plan_artifact,
            authorization.policy_decision_artifact,
            authorization.approval_artifact,
            provider_artifact,
        ),
        record=record,
        source_evidence_sha256=source["evidence_fingerprint"],
    )


def build_contract_report(
    *,
    source_evidence_path: Path = DEFAULT_SOURCE_EVIDENCE,
    wrapper_path: Path = DEFAULT_WRAPPER_PATH,
) -> dict[str, Any]:
    errors: list[str] = []
    bundle: BindingLedgerBundle | None = None
    try:
        bundle = build_binding_ledger_bundle(source_evidence_path)
    except (KeyError, OSError, TypeError, ValueError) as exc:
        errors.append(f"binding ledger contract is invalid: {type(exc).__name__}")
    try:
        wrapper = wrapper_path.read_text(encoding="utf-8")
        for marker in (
            "set -euo pipefail",
            "metadata_fabric_binding_ledger",
            "docker run",
        ):
            if marker not in wrapper:
                errors.append(f"binding ledger wrapper is missing marker: {marker}")
    except OSError as exc:
        errors.append(f"binding ledger wrapper is invalid: {type(exc).__name__}")
    files: dict[str, dict[str, str | None]] = {}
    for path in (
        Path(__file__).resolve(),
        source_evidence_path.resolve(),
        wrapper_path.resolve(),
        *MIGRATIONS,
    ):
        files[path.name] = {
            "path": (
                path.resolve().relative_to(REPO_ROOT).as_posix()
                if path.resolve().is_relative_to(REPO_ROOT)
                else path.resolve().as_posix()
            ),
            "sha256": (
                hashlib.sha256(path.read_bytes()).hexdigest()
                if path.is_file()
                else None
            ),
        }
    stable = {
        "schema": LEDGER_CONTRACT_SCHEMA,
        "source_evidence_sha256": (
            bundle.source_evidence_sha256 if bundle is not None else None
        ),
        "binding_sha256": (
            bundle.record.binding.binding_sha256 if bundle is not None else None
        ),
        "record_sha256": bundle.record.record_sha256 if bundle is not None else None,
        "files": files,
        "errors": errors,
    }
    return {
        **stable,
        "status": "valid" if not errors else "invalid",
        "contract_sha256": canonical_json_fingerprint(stable),
        "local_binding_persistence_verified": False,
        "production_ready": False,
    }


def _apply_migrations(engine) -> None:
    with engine.begin() as connection:
        is_superuser = connection.exec_driver_sql(
            "SELECT rolsuper FROM pg_roles WHERE rolname = current_user"
        ).scalar_one()
        if not is_superuser:
            raise MetadataFabricBindingLedgerError(
                "local binding rehearsal requires a fresh superuser database"
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
    *,
    source_evidence_path: Path = DEFAULT_SOURCE_EVIDENCE,
) -> dict[str, Any]:
    if not database_url.startswith(
        ("postgresql://", "postgresql+psycopg://", "postgresql+psycopg2://")
    ):
        raise MetadataFabricBindingLedgerError(
            "binding rehearsal requires a PostgreSQL database URL"
        )
    bundle = build_binding_ledger_bundle(source_evidence_path)
    engine = create_engine(database_url)
    try:
        _apply_migrations(engine)
        gateway = PlatformGateway(engine)
        by_urn = {item.resource_urn: item for item in bundle.resources}
        definition_version = next(
            item
            for item in bundle.resource_versions
            if item.resource_version_id == bundle.definition.definition_version_id
        )
        gateway.register_definition(
            DefinitionRegistration(
                resource=by_urn[definition_version.resource_urn],
                resource_version=definition_version,
                definition=bundle.definition,
            )
        )
        for resource in bundle.resources:
            if resource.resource_urn != definition_version.resource_urn:
                gateway.register_resource(resource)
        for version in bundle.resource_versions:
            if version.resource_version_id != definition_version.resource_version_id:
                gateway.register_resource_version(version)
        for artifact in bundle.artifacts:
            gateway.record_artifact(artifact)

        first = gateway.commit_metadata_fabric_binding(bundle.record)
        second = gateway.commit_metadata_fabric_binding(bundle.record)
        stored = gateway.get_metadata_fabric_binding(
            bundle.record.tenant_id,
            bundle.record.binding.resource_version_id,
        )
        other_tenant_visible = True
        try:
            gateway.get_metadata_fabric_binding(
                "ar0-golden-isolated",
                bundle.record.binding.resource_version_id,
            )
        except GatewayNotFoundError:
            other_tenant_visible = False

        with engine.connect() as connection:
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
            connection.rollback()
    finally:
        engine.dispose()

    verified = (
        first.created
        and not second.created
        and first.value == second.value == stored == bundle.record
        and not other_tenant_visible
        and append_only
        and force_rls
    )
    stable = {
        "schema": LEDGER_EVIDENCE_SCHEMA,
        "status": (
            "local_binding_ledger_replay_verified" if verified else "blocked"
        ),
        "source_evidence_sha256": bundle.source_evidence_sha256,
        "binding_id": str(bundle.record.binding_id),
        "binding_sha256": bundle.record.binding.binding_sha256,
        "record_sha256": bundle.record.record_sha256,
        "resource_version_id": str(bundle.record.binding.resource_version_id),
        "openmetadata_entity_id": str(
            bundle.record.binding.openmetadata.entity_id
        ),
        "first_commit_created": first.created,
        "replay_commit_created": second.created,
        "stored_record_matches": stored == bundle.record,
        "append_only_privileges_verified": bool(append_only),
        "force_rls_verified": bool(force_rls),
        "cross_tenant_read_blocked": not other_tenant_visible,
        "binding_persisted_to_gda_control": verified,
        "writes_to_gda_control": verified,
        "provider_mutations_executed": False,
        "source_provider_evidence_local_only": True,
        "provider_minimum_privilege_verified": False,
        "oidc_verified": False,
        "gravitino_authentication_verified": False,
        "durable_catalog_verified": False,
        "live_openlineage_emission_verified": False,
        "production_ingestion_verified": False,
        "production_ready": False,
        "errors": [] if verified else ["local binding ledger replay did not verify"],
    }
    return {**stable, "evidence_sha256": canonical_json_fingerprint(stable)}


def validate_rehearsal_evidence(evidence: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    stable = {key: value for key, value in evidence.items() if key != "evidence_sha256"}
    if evidence.get("schema") != LEDGER_EVIDENCE_SCHEMA:
        errors.append("binding ledger evidence schema does not match")
    if evidence.get("evidence_sha256") != canonical_json_fingerprint(stable):
        errors.append("binding ledger evidence SHA-256 does not match")
    for claim in (
        "provider_minimum_privilege_verified",
        "oidc_verified",
        "gravitino_authentication_verified",
        "durable_catalog_verified",
        "live_openlineage_emission_verified",
        "production_ingestion_verified",
        "production_ready",
    ):
        if evidence.get(claim) is not False:
            errors.append(f"local binding evidence may not claim {claim}")
    for claim in (
        "binding_persisted_to_gda_control",
        "writes_to_gda_control",
        "append_only_privileges_verified",
        "force_rls_verified",
        "cross_tenant_read_blocked",
    ):
        if evidence.get(claim) is not True:
            errors.append(f"local binding evidence did not verify {claim}")
    if evidence.get("provider_mutations_executed") is not False:
        errors.append("M3-3 must not execute provider mutations")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate")
    validate.add_argument(
        "--source-evidence",
        type=Path,
        default=DEFAULT_SOURCE_EVIDENCE,
    )
    validate.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE_PATH)
    rehearse = subparsers.add_parser("rehearse")
    rehearse.add_argument("--database-url", required=True)
    rehearse.add_argument(
        "--source-evidence",
        type=Path,
        default=DEFAULT_SOURCE_EVIDENCE,
    )
    rehearse.add_argument("--evidence-out", type=Path, required=True)
    args = parser.parse_args(argv)

    if args.command == "validate":
        report = build_contract_report(source_evidence_path=args.source_evidence)
        try:
            evidence = _load_json_object(args.evidence)
            report["errors"].extend(validate_rehearsal_evidence(evidence))
        except (OSError, ValueError) as exc:
            report["errors"].append(
                f"binding ledger evidence is invalid: {type(exc).__name__}"
            )
        report["status"] = "valid" if not report["errors"] else "invalid"
        report["local_binding_persistence_verified"] = not report["errors"]
        print(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True))
        return 0 if not report["errors"] else 1

    evidence = run_local_rehearsal(
        args.database_url,
        source_evidence_path=args.source_evidence,
    )
    args.evidence_out.write_text(
        json.dumps(evidence, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(evidence, ensure_ascii=True, indent=2, sort_keys=True))
    return 0 if not evidence["errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
