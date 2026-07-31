"""Atomically promote the checked M3-22 real-feature output ledger bundle.

M3-23 consumes only the path-free M3-22 evidence. It appends the output
ResourceVersion, output Artifact, quality evidence Artifact, independent passed
QualityResult, and source-to-output LineageEvent through one PlatformGateway
transaction. The correlated PlatformRun stays accepted: this slice does not
fabricate the success observation or independent evidence provenance required by
the existing terminal success gate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import uuid5

from pydantic import BaseModel, ConfigDict, model_validator
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from . import metadata_fabric_active_metadata_authorization as m316
from . import metadata_fabric_real_feature_ingestion as m322
from .platform_contracts import (
    Artifact,
    LineageEvent,
    PlatformDefinitionVersion,
    PlatformRun,
    QualityResult,
    Resource,
    ResourceVersion,
    RunStatus,
    RunSuccessEvidence,
    SubjectContext,
    canonical_json_fingerprint,
    platform_definition_fingerprint,
    run_success_evidence_fingerprint,
)
from .platform_gateway import (
    DefinitionRegistration,
    GatewayConflictError,
    GatewayNotFoundError,
    GatewayValidationError,
    GatewayWriteResult,
    PlatformGateway,
    PlatformGatewayError,
)

CONTRACT_SCHEMA = "gda.real_feature_ledger_promotion_contract.v1"
EVIDENCE_SCHEMA = "gda.real_feature_ledger_promotion_evidence.v1"
VALIDATION_SCHEMA = "gda.real_feature_ledger_promotion_validation.v1"
SOURCE_EVIDENCE_SHA256 = (
    "42abd82613eaf28cb53c64280258bc75dba6cf841f9a513a4c801a9f798b9899"
)
SOURCE_CONTRACT_SHA256 = (
    "af211f2d2f4830decb9ffe369cd9e7ec2c9349c2e2c8bd789347a6fdc288e1dc"
)
TENANT = m322.TENANT
SOURCE_RESOURCE_VERSION_ID = m322.SOURCE_RESOURCE_VERSION_ID
OUTPUT_RESOURCE_VERSION_ID = m322.OUTPUT_RESOURCE_VERSION_ID
DEFINITION_VERSION_ID = m322.DEFINITION_VERSION_ID
RUN_ID = m322.RUN_ID
WORKLOAD = "workload:real-feature-ledger-promoter"
REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE_EVIDENCE_PATH = m322.DEFAULT_EVIDENCE_PATH
DEFAULT_EVIDENCE_PATH = (
    REPO_ROOT
    / "docs/evidence/metadata-fabric-real-feature-ledger-promotion-2026-07-31.json"
)
DEFAULT_WRAPPER_PATH = (
    REPO_ROOT / "scripts/metadata-fabric-real-feature-ledger-promotion.sh"
)
MIGRATIONS = tuple(
    Path(__file__).resolve().parent / "migrations" / filename
    for filename in (
        "092_platform_control_ledger.sql",
        "093_app_user_tenant_context.sql",
        "094_platform_control_gateway.sql",
        "095_platform_command_outbox.sql",
        "096_platform_success_verdict.sql",
    )
)
FALSE_CLAIMS = (
    "source_dataset_committed",
    "source_absolute_path_committed",
    "source_feature_payload_committed",
    "m322_authorization_persisted_to_gda_control",
    "output_material_retained",
    "platform_run_succeeded",
    "protected_workload_identity_verified",
    "durable_catalog_verified",
    "production_object_store_verified",
    "production_ingestion_verified",
    "production_ready",
)


class RealFeatureLedgerPromotionError(RuntimeError):
    """The M3-23 output ledger promotion failed closed."""


class _InjectedPromotionFailure(RuntimeError):
    pass


class RunOutputLedgerPromotion(BaseModel):
    """Atomic, content-bound output, quality and lineage bundle."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    authority_resource: Resource
    output_resource_version: ResourceVersion
    output_artifact: Artifact
    quality_evidence_artifact: Artifact
    quality_result: QualityResult
    lineage_event: LineageEvent

    @model_validator(mode="after")
    def _consistent_promotion(self) -> RunOutputLedgerPromotion:
        resource = self.authority_resource
        version = self.output_resource_version
        output = self.output_artifact
        quality_artifact = self.quality_evidence_artifact
        quality = self.quality_result
        lineage = self.lineage_event
        if len(
            {
                resource.tenant_id,
                version.tenant_id,
                output.tenant_id,
                quality_artifact.tenant_id,
                quality.tenant_id,
                lineage.tenant_id,
            }
        ) != 1:
            raise ValueError("output promotion tenants must match")
        if resource.resource_urn != version.resource_urn:
            raise ValueError("output ResourceVersion must bind the authority Resource")
        if output.artifact_role.value != "output":
            raise ValueError("output promotion requires one output Artifact")
        if quality_artifact.artifact_role.value != "evidence":
            raise ValueError("output promotion requires one quality evidence Artifact")
        if output.artifact_id == quality_artifact.artifact_id:
            raise ValueError("output and quality evidence Artifacts must be distinct")
        if (
            output.run_id is None
            or quality_artifact.run_id != output.run_id
            or quality.run_id != output.run_id
            or lineage.run_id != output.run_id
        ):
            raise ValueError("output promotion Run bindings must match")
        if (
            output.resource_version_id != version.resource_version_id
            or quality_artifact.resource_version_id != version.resource_version_id
            or quality.resource_version_id != version.resource_version_id
            or lineage.target_resource_version_id != version.resource_version_id
        ):
            raise ValueError("output promotion ResourceVersion bindings must match")
        if output.content_sha256 != version.content_sha256:
            raise ValueError("output Artifact must bind ResourceVersion content")
        if quality.evidence_artifact_id != quality_artifact.artifact_id:
            raise ValueError("QualityResult must bind the quality evidence Artifact")
        if quality.verdict.value != "passed":
            raise ValueError("output promotion requires a passed QualityResult")
        if quality.evaluated_by == version.created_by:
            raise ValueError("output promotion quality evaluation must be independent")
        if quality_artifact.manifest.get("rule_version_ref") != quality.rule_version_ref:
            raise ValueError("quality evidence rule binding does not match")
        if quality_artifact.manifest.get("metrics") != quality.metrics:
            raise ValueError("quality evidence metrics do not match")
        if lineage.artifact_id != output.artifact_id:
            raise ValueError("LineageEvent must bind the output Artifact")
        if lineage.definition_version_id is None:
            raise ValueError("output promotion lineage requires a DefinitionVersion")
        if any(
            output.manifest.get(key) != value
            for key, value in lineage.facets.items()
        ):
            raise ValueError("lineage facets do not match the output manifest")
        return self


class RunOutputLedgerPromoter:
    """Compose existing gateway primitives under one gateway transaction."""

    def __init__(self, gateway: PlatformGateway):
        self.gateway = gateway

    @staticmethod
    def _sql_json(value: Any) -> str:
        return json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )

    def _put_artifact(self, connection, artifact: Artifact) -> GatewayWriteResult:
        inserted = connection.execute(
            text(
                """
                INSERT INTO gda_control.artifact (
                    tenant_id, artifact_id, artifact_key, artifact_role,
                    storage_uri, media_type, content_sha256, size_bytes,
                    run_id, resource_version_id, manifest, created_by, created_at
                ) VALUES (
                    :tenant_id, :artifact_id, :artifact_key, :artifact_role,
                    :storage_uri, :media_type, :content_sha256, :size_bytes,
                    :run_id, :resource_version_id,
                    CAST(:manifest AS jsonb), :created_by, :created_at
                )
                ON CONFLICT DO NOTHING
                RETURNING artifact_id
                """
            ),
            {
                **artifact.model_dump(mode="python", exclude={"manifest"}),
                "artifact_role": artifact.artifact_role.value,
                "manifest": self._sql_json(artifact.manifest),
            },
        ).first()
        stored = self.gateway._load_artifact(
            connection, artifact.tenant_id, artifact.artifact_id
        )
        if stored is None or stored != artifact:
            raise GatewayConflictError(
                "Artifact identity already has a different payload"
            )
        return GatewayWriteResult(stored, inserted is not None)

    def _put_quality_result(
        self, connection, quality: QualityResult
    ) -> GatewayWriteResult:
        inserted = connection.execute(
            text(
                """
                INSERT INTO gda_control.quality_result (
                    tenant_id, quality_result_id, run_id,
                    resource_version_id, rule_version_ref, verdict,
                    metrics, evidence_artifact_id, result_sha256,
                    evaluated_by, evaluated_at
                ) VALUES (
                    :tenant_id, :quality_result_id, :run_id,
                    :resource_version_id, :rule_version_ref, :verdict,
                    CAST(:metrics AS jsonb), :evidence_artifact_id,
                    :result_sha256, :evaluated_by, :evaluated_at
                )
                ON CONFLICT DO NOTHING
                RETURNING quality_result_id
                """
            ),
            {
                **quality.model_dump(mode="python", exclude={"metrics"}),
                "verdict": quality.verdict.value,
                "metrics": self._sql_json(quality.metrics),
            },
        ).first()
        stored = self.gateway._load_quality_result(
            connection,
            quality.tenant_id,
            quality.quality_result_id,
        )
        if stored is None or stored != quality:
            raise GatewayConflictError(
                "QualityResult identity already has a different payload"
            )
        return GatewayWriteResult(stored, inserted is not None)

    def _put_lineage(
        self, connection, event: LineageEvent
    ) -> GatewayWriteResult:
        inserted = connection.execute(
            text(
                """
                INSERT INTO gda_control.lineage_event (
                    tenant_id, lineage_event_id, event_type,
                    source_resource_version_id, target_resource_version_id,
                    producer, event_sha256, run_id, definition_version_id,
                    artifact_id, facets, occurred_at
                ) VALUES (
                    :tenant_id, :lineage_event_id, :event_type,
                    :source_resource_version_id, :target_resource_version_id,
                    :producer, :event_sha256, :run_id, :definition_version_id,
                    :artifact_id, CAST(:facets AS jsonb), :occurred_at
                )
                ON CONFLICT DO NOTHING
                RETURNING lineage_event_id
                """
            ),
            {
                **event.model_dump(mode="python", exclude={"facets"}),
                "event_type": event.event_type.value,
                "facets": self._sql_json(event.facets),
            },
        ).first()
        stored = self.gateway._load_lineage(
            connection, event.tenant_id, event.lineage_event_id
        )
        if stored is None or stored != event:
            raise GatewayConflictError(
                "LineageEvent identity already has a different payload"
            )
        return GatewayWriteResult(stored, inserted is not None)

    def promote(
        self, promotion: RunOutputLedgerPromotion
    ) -> GatewayWriteResult:
        try:
            promotion = RunOutputLedgerPromotion.model_validate(
                promotion.model_dump(mode="json")
            )
        except ValueError as exc:
            raise GatewayValidationError(
                "Run output ledger promotion is not content-bound"
            ) from exc
        tenant_id = promotion.output_resource_version.tenant_id
        run_id = promotion.output_artifact.run_id
        assert run_id is not None
        gateway = self.gateway
        with gateway._transaction(tenant_id) as connection:
            authority = gateway._load_resource(
                connection,
                tenant_id,
                promotion.output_resource_version.resource_urn,
            )
            if authority is None:
                raise GatewayValidationError(
                    "output Resource authority record was not found"
                )
            if authority != promotion.authority_resource:
                raise GatewayConflictError(
                    "output Resource authority record has different content"
                )
            run = gateway._load_run(connection, tenant_id, run_id)
            source = gateway._load_resource_version(
                connection,
                tenant_id,
                promotion.lineage_event.source_resource_version_id,
            )
            definition = gateway._load_definition(
                connection,
                tenant_id,
                promotion.lineage_event.definition_version_id,
            )
            if run is None or source is None or definition is None:
                raise GatewayValidationError(
                    "Run output promotion prerequisite was not found"
                )
            if (
                run.definition_version_id != definition.definition_version_id
                or run.definition_version_id
                != promotion.lineage_event.definition_version_id
                or promotion.lineage_event.source_resource_version_id
                not in {
                    binding.resource_version_id for binding in run.input_bindings
                }
            ):
                raise GatewayValidationError(
                    "Run output promotion prerequisite binding does not match"
                )
            if run.status not in {RunStatus.ACCEPTED, RunStatus.RECONCILING}:
                raise GatewayValidationError(
                    "Run output promotion requires an accepted or reconciling Run"
                )

            results = (
                gateway._put_resource_version(
                    connection, promotion.output_resource_version
                ),
                self._put_artifact(connection, promotion.output_artifact),
                self._put_artifact(
                    connection, promotion.quality_evidence_artifact
                ),
                self._put_quality_result(connection, promotion.quality_result),
                self._put_lineage(connection, promotion.lineage_event),
            )
            creation_states = {result.created for result in results}
            if len(creation_states) != 1:
                raise GatewayConflictError(
                    "Run output promotion has partial pre-existing state"
                )
            final_run = gateway._load_run(connection, tenant_id, run_id)
            if final_run != run:
                raise GatewayConflictError(
                    "Run changed while its output ledger was promoted"
                )
            stored = RunOutputLedgerPromotion(
                authority_resource=authority,
                output_resource_version=results[0].value,
                output_artifact=results[1].value,
                quality_evidence_artifact=results[2].value,
                quality_result=results[3].value,
                lineage_event=results[4].value,
            )
            return GatewayWriteResult(stored, results[0].created)


class _RollbackProbePromoter(RunOutputLedgerPromoter):
    def _put_quality_result(self, connection, quality):
        raise _InjectedPromotionFailure("injected before QualityResult append")


@dataclass(frozen=True)
class PromotionPrerequisites:
    source_resource: Resource
    source_version: ResourceVersion
    definition_registration: DefinitionRegistration
    output_resource: Resource
    run: PlatformRun


def _load_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RealFeatureLedgerPromotionError(
            f"{path.name} is not valid JSON"
        ) from exc
    if not isinstance(value, dict):
        raise RealFeatureLedgerPromotionError(f"{path.name} must contain an object")
    return value


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _file_record(path: Path) -> dict[str, str | None]:
    resolved = path.resolve()
    return {
        "path": resolved.relative_to(REPO_ROOT).as_posix(),
        "sha256": (
            hashlib.sha256(resolved.read_bytes()).hexdigest()
            if resolved.is_file()
            else None
        ),
    }


def validate_source_evidence(source: Mapping[str, Any]) -> None:
    errors = m322.verify_evidence_integrity(source)
    if errors:
        raise RealFeatureLedgerPromotionError(
            "M3-22 evidence is invalid: " + ", ".join(errors)
        )
    if (
        source.get("evidence_sha256") != SOURCE_EVIDENCE_SHA256
        or source.get("contract_sha256") != SOURCE_CONTRACT_SHA256
    ):
        raise RealFeatureLedgerPromotionError("M3-22 evidence identity drifted")
    if (
        source.get("ingestion_persisted_to_gda_control") is not False
        or source.get("platform_run_succeeded") is not False
    ):
        raise RealFeatureLedgerPromotionError(
            "M3-22 source must contain unpromoted, non-terminal candidates"
        )


def build_output_authority_resource(source: Mapping[str, Any]) -> Resource:
    validate_source_evidence(source)
    observation = _mapping(source.get("observation"))
    plan = _mapping(observation.get("plan"))
    target = _mapping(plan.get("target"))
    contracts = _mapping(observation.get("output_contracts"))
    output = ResourceVersion.model_validate(contracts.get("output_resource_version"))
    artifact = Artifact.model_validate(contracts.get("output_artifact"))
    locator = "/".join(
        str(target.get(name) or "")
        for name in ("metalake", "catalog", "schema", "table")
    )
    if not all(target.get(name) for name in ("metalake", "catalog", "schema", "table")):
        raise RealFeatureLedgerPromotionError("M3-22 authority target is incomplete")
    return Resource(
        tenant_id=TENANT,
        resource_urn=output.resource_urn,
        resource_kind="data_product",
        authority_system="gravitino",
        authority_locator=locator,
        owner_ref="team:metadata-platform",
        governance_ref={
            "claim_level": "local_verified_ingestion_output",
            "source_evidence_schema": m322.EVIDENCE_SCHEMA,
            "source_evidence_sha256": SOURCE_EVIDENCE_SHA256,
            "production_ready": False,
        },
        technical_refs=(
            {
                "system": "iceberg",
                "catalog": target["catalog"],
                "schema": target["schema"],
                "table": target["table"],
                "content_sha256": output.content_sha256,
            },
            {
                "system": "object_store",
                "storage_uri": artifact.storage_uri,
                "material_retained": False,
            },
        ),
    )


def build_promotion(source: Mapping[str, Any]) -> RunOutputLedgerPromotion:
    validate_source_evidence(source)
    contracts = _mapping(
        _mapping(source.get("observation")).get("output_contracts")
    )
    if contracts.get("persisted_to_gda_control") is not False:
        raise RealFeatureLedgerPromotionError("M3-22 candidates already claim persistence")
    try:
        promotion = RunOutputLedgerPromotion(
            authority_resource=build_output_authority_resource(source),
            output_resource_version=ResourceVersion.model_validate(
                contracts.get("output_resource_version")
            ),
            output_artifact=Artifact.model_validate(contracts.get("output_artifact")),
            quality_evidence_artifact=Artifact.model_validate(
                contracts.get("quality_evidence_artifact")
            ),
            quality_result=contracts.get("quality_result"),
            lineage_event=contracts.get("lineage_event"),
        )
    except ValueError as exc:
        raise RealFeatureLedgerPromotionError(
            "M3-22 output ledger candidates are invalid"
        ) from exc
    plan = _mapping(_mapping(source.get("observation")).get("plan"))
    if (
        promotion.output_resource_version.resource_version_id
        != OUTPUT_RESOURCE_VERSION_ID
        or promotion.output_resource_version.resource_urn != m322.OUTPUT_RESOURCE_URN
        or promotion.lineage_event.source_resource_version_id
        != SOURCE_RESOURCE_VERSION_ID
        or promotion.lineage_event.definition_version_id != DEFINITION_VERSION_ID
        or promotion.output_artifact.run_id != RUN_ID
        or promotion.output_resource_version.content_sha256
        != plan.get("output_content_sha256")
    ):
        raise RealFeatureLedgerPromotionError("M3-22 promotion identity drifted")
    return promotion


def build_prerequisites(
    source: Mapping[str, Any], promotion: RunOutputLedgerPromotion
) -> PromotionPrerequisites:
    validate_source_evidence(source)
    observation = _mapping(source.get("observation"))
    plan = _mapping(observation.get("plan"))
    authorization = _mapping(observation.get("authorization"))
    source_bundle = m316.build_authorization_bundle(
        str(plan.get("source_content_sha256") or "")
    )
    source_resource = source_bundle.source_resource
    source_version = source_bundle.registration.resource_version
    if (
        source_version.resource_version_id != SOURCE_RESOURCE_VERSION_ID
        or source_version.content_sha256 != plan.get("source_content_sha256")
    ):
        raise RealFeatureLedgerPromotionError("M3-22 source prerequisite drifted")

    definition_urn = f"gda://{TENANT}/definition/real-feature-ingestion"
    definition_document = {
        "action": m322.ACTION,
        "ingestion_plan_sha256": plan.get("ingestion_plan_sha256"),
        "engine": "spark-sedona-iceberg",
        "terminal_success": False,
    }
    input_contract = {
        "source_resource_version_id": str(SOURCE_RESOURCE_VERSION_ID),
        "semantic_type": "gis.cultural_districts",
    }
    output_contract = {
        "output_resource_version_id": str(OUTPUT_RESOURCE_VERSION_ID),
        "output_artifact": True,
        "independent_quality_result": True,
        "source_to_output_lineage": True,
        "platform_run_terminal_success": False,
    }
    definition_sha256 = platform_definition_fingerprint(
        orchestration_class="dataops",
        capability_id=m322.ACTION,
        portability_class="engine_family",
        definition_document=definition_document,
        input_contract=input_contract,
        output_contract=output_contract,
    )
    created_at = promotion.output_resource_version.created_at - timedelta(minutes=5)
    definition_resource = Resource(
        tenant_id=TENANT,
        resource_urn=definition_urn,
        resource_kind="definition",
        authority_system="gda",
        authority_locator="definition/real-feature-ingestion",
        owner_ref="team:metadata-platform",
    )
    definition_version = ResourceVersion(
        tenant_id=TENANT,
        resource_urn=definition_urn,
        resource_version_id=DEFINITION_VERSION_ID,
        version_key="m3-22-spark-sedona-iceberg-v1",
        content_sha256=definition_sha256,
        authority_version_ref={
            "source_evidence_sha256": SOURCE_EVIDENCE_SHA256,
            "ingestion_plan_sha256": plan.get("ingestion_plan_sha256"),
        },
        created_by=WORKLOAD,
        created_at=created_at,
    )
    definition = PlatformDefinitionVersion(
        tenant_id=TENANT,
        definition_urn=definition_urn,
        definition_version_id=DEFINITION_VERSION_ID,
        orchestration_class="dataops",
        capability_id=m322.ACTION,
        portability_class="engine_family",
        definition_document=definition_document,
        input_contract=input_contract,
        output_contract=output_contract,
        definition_sha256=definition_sha256,
    )
    run = PlatformRun(
        tenant_id=TENANT,
        run_id=RUN_ID,
        definition_version_id=DEFINITION_VERSION_ID,
        orchestration_class="dataops",
        subject_context=SubjectContext(
            tenant_id=TENANT,
            subject_id=m322.WORKLOAD.removeprefix("workload:"),
            subject_type="workload",
            roles=("spatial_ingestion_executor",),
            purpose="correlate checked M3-22 output candidates for ledger promotion",
        ),
        input_bindings=(
            {
                "binding_name": "source_dataset",
                "resource_version_id": SOURCE_RESOURCE_VERSION_ID,
                "semantic_type": "gis.cultural_districts",
            },
        ),
        idempotency_key=f"real-feature-ingestion:{promotion.output_resource_version.content_sha256}",
        config_fingerprint=str(authorization.get("authorization_sha256") or ""),
        submitted_at=created_at + timedelta(seconds=1),
    )
    return PromotionPrerequisites(
        source_resource=source_resource,
        source_version=source_version,
        definition_registration=DefinitionRegistration(
            resource=definition_resource,
            resource_version=definition_version,
            definition=definition,
        ),
        output_resource=promotion.authority_resource,
        run=run,
    )


def _apply_migrations(engine: Any) -> None:
    with engine.begin() as connection:
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


def _register_prerequisites(
    gateway: PlatformGateway,
    prerequisites: PromotionPrerequisites,
    *,
    include_output_authority: bool,
) -> None:
    gateway.register_resource(prerequisites.source_resource)
    gateway.register_resource_version(prerequisites.source_version)
    gateway.register_definition(prerequisites.definition_registration)
    if include_output_authority:
        gateway.register_resource(prerequisites.output_resource)
    gateway.submit_run(prerequisites.run)


def _candidate_counts(engine: Any, promotion: RunOutputLedgerPromotion) -> dict[str, int]:
    with engine.connect() as connection:
        return {
            "resource_versions": int(
                connection.execute(
                    text(
                        "SELECT count(*) FROM gda_control.resource_version "
                        "WHERE tenant_id=:tenant_id AND resource_version_id=:object_id"
                    ),
                    {
                        "tenant_id": TENANT,
                        "object_id": promotion.output_resource_version.resource_version_id,
                    },
                ).scalar_one()
            ),
            "artifacts": int(
                connection.execute(
                    text(
                        "SELECT count(*) FROM gda_control.artifact "
                        "WHERE tenant_id=:tenant_id AND artifact_id IN (:output_id, :quality_id)"
                    ),
                    {
                        "tenant_id": TENANT,
                        "output_id": promotion.output_artifact.artifact_id,
                        "quality_id": promotion.quality_evidence_artifact.artifact_id,
                    },
                ).scalar_one()
            ),
            "quality_results": int(
                connection.execute(
                    text(
                        "SELECT count(*) FROM gda_control.quality_result "
                        "WHERE tenant_id=:tenant_id AND quality_result_id=:object_id"
                    ),
                    {
                        "tenant_id": TENANT,
                        "object_id": promotion.quality_result.quality_result_id,
                    },
                ).scalar_one()
            ),
            "lineage_events": int(
                connection.execute(
                    text(
                        "SELECT count(*) FROM gda_control.lineage_event "
                        "WHERE tenant_id=:tenant_id AND lineage_event_id=:object_id"
                    ),
                    {
                        "tenant_id": TENANT,
                        "object_id": promotion.lineage_event.lineage_event_id,
                    },
                ).scalar_one()
            ),
        }


def _security_state(engine: Any) -> dict[str, bool]:
    relations = (
        "resource_version",
        "artifact",
        "quality_result",
        "lineage_event",
    )
    with engine.connect() as connection:
        force_rls = connection.execute(
            text(
                """
                SELECT bool_and(relforcerowsecurity)
                FROM pg_class
                WHERE oid = ANY (ARRAY[
                    'gda_control.resource_version'::regclass,
                    'gda_control.artifact'::regclass,
                    'gda_control.quality_result'::regclass,
                    'gda_control.lineage_event'::regclass
                ])
                """
            )
        ).scalar_one()
        privileges = [
            connection.execute(
                text(
                    """
                    SELECT
                        has_table_privilege('gda_control_gateway', :relation, 'SELECT,INSERT'),
                        NOT has_table_privilege('gda_control_gateway', :relation, 'UPDATE'),
                        NOT has_table_privilege('gda_control_gateway', :relation, 'DELETE')
                    """
                ),
                {"relation": f"gda_control.{name}"},
            ).one()
            for name in relations
        ]
    return {
        "force_rls": bool(force_rls),
        "minimum_grants": all(bool(row[0] and row[1] and row[2]) for row in privileges),
    }


def _direct_mutations_blocked(
    gateway: PlatformGateway, promotion: RunOutputLedgerPromotion
) -> dict[str, bool]:
    targets = {
        "resource_version": (
            "resource_version_id",
            promotion.output_resource_version.resource_version_id,
        ),
        "artifact": ("artifact_id", promotion.output_artifact.artifact_id),
        "quality_result": (
            "quality_result_id",
            promotion.quality_result.quality_result_id,
        ),
        "lineage_event": (
            "lineage_event_id",
            promotion.lineage_event.lineage_event_id,
        ),
    }
    results: dict[str, bool] = {}
    with gateway._transaction(TENANT) as connection:
        for relation, (identity_column, identity) in targets.items():
            for operation in ("update", "delete"):
                statement = (
                    f"UPDATE gda_control.{relation} SET tenant_id=tenant_id "
                    f"WHERE {identity_column}=:identity"
                    if operation == "update"
                    else f"DELETE FROM gda_control.{relation} "
                    f"WHERE {identity_column}=:identity"
                )
                blocked = False
                try:
                    with connection.begin_nested():
                        connection.execute(text(statement), {"identity": identity})
                except DBAPIError:
                    blocked = True
                results[f"{relation}_{operation}"] = blocked
    return results


def _cross_tenant_direct_insert_blocked(gateway: PlatformGateway) -> bool:
    blocked = False
    with gateway._transaction(TENANT) as connection:
        try:
            with connection.begin_nested():
                connection.execute(
                    text(
                        """
                        INSERT INTO gda_control.resource (
                            tenant_id, resource_urn, resource_kind,
                            authority_system, authority_locator, owner_ref
                        ) VALUES (
                            'isolated-tenant',
                            'gda://isolated-tenant/data_product/forbidden-output',
                            'data_product', 'gda', 'forbidden-output', 'team:test'
                        )
                        """
                    )
                )
        except DBAPIError:
            blocked = True
    return blocked


def _success_finalization_rejected(
    gateway: PlatformGateway, promotion: RunOutputLedgerPromotion
) -> bool:
    observation_id = uuid5(RUN_ID, "missing-m3-23-success-observation")
    values = {
        "tenant_id": TENANT,
        "run_id": RUN_ID,
        "attempt_observation_id": observation_id,
        "output_artifact_id": promotion.output_artifact.artifact_id,
        "quality_result_id": promotion.quality_result.quality_result_id,
        "lineage_event_id": promotion.lineage_event.lineage_event_id,
    }
    evidence = RunSuccessEvidence(
        **values,
        evidence_sha256=run_success_evidence_fingerprint(**values),
    )
    try:
        gateway.finalize_run_success(
            evidence,
            expected_state_version=0,
            actor_subject=m322.WORKLOAD,
            reason="must remain rejected until terminal evidence is complete",
        )
    except PlatformGatewayError:
        return True
    return False


def run_postgres_rehearsal(
    database_url: str,
    *,
    source_evidence_path: Path = DEFAULT_SOURCE_EVIDENCE_PATH,
) -> dict[str, Any]:
    source = _load_json_object(source_evidence_path)
    promotion = build_promotion(source)
    prerequisites = build_prerequisites(source, promotion)
    contract = build_contract_report(source_evidence_path=source_evidence_path)
    if contract.get("status") != "valid":
        raise RealFeatureLedgerPromotionError("M3-23 static contract is invalid")
    engine = create_engine(database_url)
    try:
        _apply_migrations(engine)
        gateway = PlatformGateway(engine)
        promoter = RunOutputLedgerPromoter(gateway)
        _register_prerequisites(
            gateway,
            prerequisites,
            include_output_authority=False,
        )
        missing_authority_rejected = False
        try:
            promoter.promote(promotion)
        except GatewayValidationError:
            missing_authority_rejected = True
        gateway.register_resource(prerequisites.output_resource)

        rollback_injected = False
        try:
            _RollbackProbePromoter(gateway).promote(promotion)
        except _InjectedPromotionFailure:
            rollback_injected = True
        rollback_counts = _candidate_counts(engine, promotion)

        first = promoter.promote(promotion)
        replay = promoter.promote(promotion)
        counts = _candidate_counts(engine, promotion)
        run_before_finalization = gateway.get_run(TENANT, RUN_ID)
        success_finalization_rejected = _success_finalization_rejected(
            gateway, promotion
        )
        final_run = gateway.get_run(TENANT, RUN_ID)
        cross_tenant_read_blocked = False
        try:
            gateway.get_artifact(
                "isolated-tenant", promotion.output_artifact.artifact_id
            )
        except GatewayNotFoundError:
            cross_tenant_read_blocked = True
        direct_mutations = _direct_mutations_blocked(gateway, promotion)
        cross_tenant_direct_insert_blocked = _cross_tenant_direct_insert_blocked(
            gateway
        )
        security = _security_state(engine)
        with engine.connect() as connection:
            run_event_count = int(
                connection.execute(
                    text(
                        "SELECT count(*) FROM gda_control.platform_run_event "
                        "WHERE tenant_id=:tenant_id AND run_id=:run_id"
                    ),
                    {"tenant_id": TENANT, "run_id": RUN_ID},
                ).scalar_one()
            )
        verified = (
            missing_authority_rejected
            and rollback_injected
            and rollback_counts
            == {
                "resource_versions": 0,
                "artifacts": 0,
                "quality_results": 0,
                "lineage_events": 0,
            }
            and first.created
            and not replay.created
            and first.value == replay.value == promotion
            and counts
            == {
                "resource_versions": 1,
                "artifacts": 2,
                "quality_results": 1,
                "lineage_events": 1,
            }
            and run_before_finalization == final_run
            and final_run.status == RunStatus.ACCEPTED
            and final_run.state_version == 0
            and run_event_count == 1
            and success_finalization_rejected
            and cross_tenant_read_blocked
            and cross_tenant_direct_insert_blocked
            and all(direct_mutations.values())
            and security["force_rls"]
            and security["minimum_grants"]
        )
        stable = {
            "schema": EVIDENCE_SCHEMA,
            "status": (
                "local_real_feature_ledger_promotion_verified"
                if verified
                else "blocked"
            ),
            "contract_sha256": contract["contract_sha256"],
            "source_evidence_schema": m322.EVIDENCE_SCHEMA,
            "source_evidence_sha256": SOURCE_EVIDENCE_SHA256,
            "promotion_sha256": canonical_json_fingerprint(
                promotion.model_dump(mode="json")
            ),
            "tenant_id": TENANT,
            "source_resource_version_id": str(SOURCE_RESOURCE_VERSION_ID),
            "output_resource_urn": promotion.output_resource_version.resource_urn,
            "output_resource_version_id": str(OUTPUT_RESOURCE_VERSION_ID),
            "output_content_sha256": promotion.output_resource_version.content_sha256,
            "run_id": str(RUN_ID),
            "definition_version_id": str(DEFINITION_VERSION_ID),
            "authority_system": promotion.authority_resource.authority_system,
            "authority_locator": promotion.authority_resource.authority_locator,
            "missing_authority_rejected": missing_authority_rejected,
            "failure_injection_rollback_verified": (
                rollback_injected and not any(rollback_counts.values())
            ),
            "rollback_candidate_counts": rollback_counts,
            "first_promotion_created": first.created,
            "replay_promotion_created": replay.created,
            "candidate_row_counts": counts,
            "exact_replay_verified": first.value == replay.value == promotion,
            "cross_tenant_read_blocked": cross_tenant_read_blocked,
            "cross_tenant_direct_insert_blocked": (
                cross_tenant_direct_insert_blocked
            ),
            "direct_mutations_blocked": direct_mutations,
            "force_rls_verified": security["force_rls"],
            "minimum_grants_verified": security["minimum_grants"],
            "platform_run_status": final_run.status.value,
            "platform_run_state_version": final_run.state_version,
            "platform_run_event_count": run_event_count,
            "success_finalization_rejected": success_finalization_rejected,
            "promotion_persisted_to_gda_control": verified,
            "writes_to_legacy": False,
            **{claim: False for claim in FALSE_CLAIMS},
            "errors": [] if verified else ["M3-23 PostgreSQL rehearsal did not verify"],
        }
        return {**stable, "evidence_sha256": canonical_json_fingerprint(stable)}
    finally:
        engine.dispose()


def build_contract_report(
    *, source_evidence_path: Path = DEFAULT_SOURCE_EVIDENCE_PATH
) -> dict[str, Any]:
    errors: list[str] = []
    source: dict[str, Any] | None = None
    promotion: RunOutputLedgerPromotion | None = None
    try:
        source = _load_json_object(source_evidence_path)
        promotion = build_promotion(source)
        build_prerequisites(source, promotion)
    except (OSError, TypeError, ValueError, RealFeatureLedgerPromotionError) as exc:
        errors.append(f"M3-23 source contract is invalid: {type(exc).__name__}")
    paths = (
        Path(__file__).resolve(),
        (REPO_ROOT / "data_agent/platform_gateway.py").resolve(),
        DEFAULT_WRAPPER_PATH.resolve(),
        *(migration.resolve() for migration in MIGRATIONS),
    )
    files = [_file_record(path) for path in paths]
    if any(item["sha256"] is None for item in files):
        errors.append("M3-23 contract file is missing")
    promotion_source = Path(__file__).read_text(encoding="utf-8")
    for marker in (
        "class RunOutputLedgerPromotion",
        "class RunOutputLedgerPromoter",
        "def promote(",
        "Run output promotion has partial pre-existing state",
        "Run output promotion requires an accepted or reconciling Run",
    ):
        if marker not in promotion_source:
            errors.append(f"M3-23 promoter is missing marker: {marker}")
    stable = {
        "schema": CONTRACT_SCHEMA,
        "status": "valid" if not errors else "invalid",
        "source_evidence_sha256": (
            source.get("evidence_sha256") if source is not None else None
        ),
        "source_contract_sha256": (
            source.get("contract_sha256") if source is not None else None
        ),
        "promotion_sha256": (
            canonical_json_fingerprint(promotion.model_dump(mode="json"))
            if promotion is not None
            else None
        ),
        "atomic_write_order": [
            "resource_version",
            "output_artifact",
            "quality_evidence_artifact",
            "quality_result",
            "lineage_event",
        ],
        "requires_preexisting_output_authority": True,
        "partial_preexisting_state_rejected": True,
        "exact_replay_idempotent": True,
        "platform_run_terminal_success": False,
        "writes_to_legacy": False,
        "files": files,
        **{claim: False for claim in FALSE_CLAIMS},
        "errors": errors,
    }
    return {**stable, "contract_sha256": canonical_json_fingerprint(stable)}


def validate_rehearsal_evidence(
    evidence: Mapping[str, Any],
    *,
    source_evidence_path: Path = DEFAULT_SOURCE_EVIDENCE_PATH,
) -> list[str]:
    errors: list[str] = []
    try:
        source = _load_json_object(source_evidence_path)
        validate_source_evidence(source)
    except RealFeatureLedgerPromotionError as exc:
        return [str(exc)]
    contract = build_contract_report(source_evidence_path=source_evidence_path)
    stable = {key: value for key, value in evidence.items() if key != "evidence_sha256"}
    if evidence.get("evidence_sha256") != canonical_json_fingerprint(stable):
        errors.append("M3-23 evidence SHA-256 does not match")
    if evidence.get("schema") != EVIDENCE_SCHEMA or evidence.get("errors") != []:
        errors.append("M3-23 evidence is not verified")
    if evidence.get("contract_sha256") != contract.get("contract_sha256"):
        errors.append("M3-23 evidence contract SHA drifted")
    if evidence.get("source_evidence_sha256") != SOURCE_EVIDENCE_SHA256:
        errors.append("M3-23 evidence source SHA drifted")
    expected_true = (
        "missing_authority_rejected",
        "failure_injection_rollback_verified",
        "first_promotion_created",
        "exact_replay_verified",
        "cross_tenant_read_blocked",
        "cross_tenant_direct_insert_blocked",
        "force_rls_verified",
        "minimum_grants_verified",
        "success_finalization_rejected",
        "promotion_persisted_to_gda_control",
    )
    for claim in expected_true:
        if evidence.get(claim) is not True:
            errors.append(f"M3-23 evidence claim is false: {claim}")
    if evidence.get("replay_promotion_created") is not False:
        errors.append("M3-23 replay must not create rows")
    if evidence.get("candidate_row_counts") != {
        "resource_versions": 1,
        "artifacts": 2,
        "quality_results": 1,
        "lineage_events": 1,
    }:
        errors.append("M3-23 candidate row counts do not match")
    if evidence.get("platform_run_status") != "accepted":
        errors.append("M3-23 PlatformRun must remain accepted")
    if evidence.get("platform_run_state_version") != 0:
        errors.append("M3-23 PlatformRun state version changed")
    direct_mutations = _mapping(evidence.get("direct_mutations_blocked"))
    if len(direct_mutations) != 8 or not all(direct_mutations.values()):
        errors.append("M3-23 direct mutation rejection is incomplete")
    for claim in FALSE_CLAIMS:
        if evidence.get(claim) is not False:
            errors.append(f"M3-23 evidence may not claim {claim}")
    if evidence.get("writes_to_legacy") is not False:
        errors.append("M3-23 evidence may not claim legacy writes")
    serialized = json.dumps(evidence, ensure_ascii=True, sort_keys=True)
    for forbidden in (
        "/Users/",
        "/home/",
        "Downloads/",
        ".tmp/",
        "geometry_wkb_hex",
        '"rows"',
        '"password"',
        '"secret"',
        '"token"',
        '"access_key"',
    ):
        if forbidden in serialized:
            errors.append("M3-23 evidence contains source or secret material")
            break
    return errors


def build_validation_report(
    *,
    source_evidence_path: Path = DEFAULT_SOURCE_EVIDENCE_PATH,
    evidence_path: Path = DEFAULT_EVIDENCE_PATH,
) -> dict[str, Any]:
    contract = build_contract_report(source_evidence_path=source_evidence_path)
    errors = list(contract["errors"])
    evidence: dict[str, Any] | None = None
    try:
        evidence = _load_json_object(evidence_path)
        errors.extend(
            validate_rehearsal_evidence(
                evidence,
                source_evidence_path=source_evidence_path,
            )
        )
    except RealFeatureLedgerPromotionError as exc:
        errors.append(str(exc))
    return {
        "schema": VALIDATION_SCHEMA,
        "status": "valid" if not errors else "invalid",
        "local_real_feature_ledger_promotion_verified": not errors,
        "promotion_persisted_to_gda_control": (
            not errors
            and evidence is not None
            and evidence.get("promotion_persisted_to_gda_control") is True
        ),
        "platform_run_succeeded": False,
        "production_ready": False,
        "contract_sha256": contract["contract_sha256"],
        "evidence_sha256": evidence.get("evidence_sha256") if evidence else None,
        "errors": errors,
    }


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    contract = subparsers.add_parser("contract")
    contract.add_argument(
        "--source-evidence", type=Path, default=DEFAULT_SOURCE_EVIDENCE_PATH
    )
    validate = subparsers.add_parser("validate")
    validate.add_argument(
        "--source-evidence", type=Path, default=DEFAULT_SOURCE_EVIDENCE_PATH
    )
    validate.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE_PATH)
    rehearse = subparsers.add_parser("rehearse")
    rehearse.add_argument("--database-url", required=True)
    rehearse.add_argument(
        "--source-evidence", type=Path, default=DEFAULT_SOURCE_EVIDENCE_PATH
    )
    rehearse.add_argument("--output", type=Path, default=DEFAULT_EVIDENCE_PATH)
    args = parser.parse_args(argv)
    try:
        if args.command == "contract":
            report = build_contract_report(
                source_evidence_path=args.source_evidence
            )
        elif args.command == "rehearse":
            report = run_postgres_rehearsal(
                args.database_url,
                source_evidence_path=args.source_evidence,
            )
            _write_json(args.output, report)
        else:
            report = build_validation_report(
                source_evidence_path=args.source_evidence,
                evidence_path=args.evidence,
            )
        print(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True))
        return 0 if not report.get("errors") else 1
    except (
        OSError,
        TypeError,
        ValueError,
        RealFeatureLedgerPromotionError,
        GatewayConflictError,
        GatewayValidationError,
    ) as exc:
        print(
            json.dumps(
                {"status": "blocked", "error": type(exc).__name__},
                ensure_ascii=True,
                sort_keys=True,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
