"""Build the fail-closed M3-1 Metadata Fabric ingestion projection contract.

M3-1 joins the immutable platform success evidence to the M1 Metadata Fabric
binding and produces deterministic provider projection intents plus an
OpenLineage RunEvent candidate. It deliberately has no provider mutation
client: matching state replays as a no-op, while drift is blocked for a later
authorized adapter to handle.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any, Literal, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from . import metadata_fabric_bridge as bridge
from . import platform_crosswalk
from .platform_contracts import (
    Artifact,
    ArtifactRole,
    LineageEvent,
    LineageEventType,
    PlatformDefinitionVersion,
    PlatformRun,
    QualityResult,
    QualityVerdict,
    Resource,
    ResourceVersion,
    RunSuccessEvidence,
    Sha256,
    TenantId,
    canonical_json_fingerprint,
    parse_resource_urn,
)

INGESTION_PLAN_SCHEMA = "gda.metadata_fabric_ingestion_plan.v1"
REPLAY_DECISION_SCHEMA = "gda.metadata_fabric_ingestion_replay.v1"
REPORT_SCHEMA = "gda.metadata_fabric_ingestion_contract_report.v1"
EXPECTED_SCHEMA = "gda.metadata_fabric_ingestion_expected.v1"
OPENLINEAGE_SCHEMA_URL = "https://openlineage.io/spec/2-0-2/OpenLineage.json#/definitions/RunEvent"
OPENLINEAGE_PRODUCER = (
    "https://github.com/zhouning/gisdataagent/data_agent/metadata_fabric_ingestion.py"
)

DEFAULT_PLATFORM_FIXTURE = (
    Path(__file__).resolve().parent / "test_data" / "platform" / "land_use_parcel_golden.json"
)
DEFAULT_METADATA_FIXTURE = bridge.DEFAULT_GOLDEN_FIXTURE
DEFAULT_EXPECTED_FIXTURE = (
    Path(__file__).resolve().parent
    / "test_data"
    / "platform"
    / "metadata_fabric_ingestion_expected.json"
)

OPENMETADATA_AUTHORITY_FIELDS = (
    "classification",
    "domain",
    "generic_lineage",
    "glossary",
    "owner",
    "quality_discovery",
)
GRAVITINO_AUTHORITY_FIELDS = (
    "catalog",
    "metalake",
    "schema",
    "table",
    "technical_access_metadata",
)
OPENMETADATA_STATE_FIELDS = {
    "resource_urn",
    "resource_version_id",
    "content_sha256",
    "owner_refs",
    "domain_refs",
    "tag_refs",
}
GRAVITINO_STATE_FIELDS = {
    "resource_urn",
    "resource_version_id",
    "content_sha256",
    "provider_revision",
}
SENSITIVE_KEY_PARTS = (
    "access_key",
    "api_key",
    "authorization",
    "client_secret",
    "credential",
    "password",
    "private_key",
    "secret",
    "token",
)
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")

NonEmptyText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=1024),
]


class MetadataFabricIngestionError(RuntimeError):
    """The deterministic Metadata Fabric ingestion contract failed closed."""


class ReplayStatus(StrEnum):
    NO_OP = "no_op"
    BLOCKED = "blocked"


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _load_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise MetadataFabricIngestionError(f"fixture is not an object: {path.name}")
    return payload


def _normalized_key(value: object) -> str:
    return str(value).strip().lower().replace("-", "_").replace(".", "_")


def _reject_sensitive_fields(value: Any, *, path: str = "payload") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = _normalized_key(key)
            if any(part in normalized for part in SENSITIVE_KEY_PARTS):
                raise ValueError(f"{path}.{key} is secret-bearing")
            _reject_sensitive_fields(item, path=f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _reject_sensitive_fields(item, path=f"{path}[{index}]")


def _projection_state_sha256(state: dict[str, Any]) -> str:
    return canonical_json_fingerprint(state)


def _projection_idempotency_key(
    *,
    provider: str,
    target_identity: str,
    desired_state_sha256: str,
) -> str:
    return canonical_json_fingerprint(
        {
            "provider": provider,
            "operation": "upsert_projection",
            "target_identity": target_identity,
            "desired_state_sha256": desired_state_sha256,
        }
    )


class ProviderProjection(_FrozenModel):
    provider: Literal["openmetadata", "gravitino"]
    operation: Literal["upsert_projection"] = "upsert_projection"
    target_identity: NonEmptyText
    authority_fields: tuple[NonEmptyText, ...] = Field(min_length=1)
    desired_state: dict[str, Any] = Field(min_length=1)
    desired_state_sha256: Sha256
    idempotency_key: Sha256

    @model_validator(mode="after")
    def _content_bound_projection(self) -> Self:
        _reject_sensitive_fields(self.desired_state, path="desired_state")
        expected_authority = (
            OPENMETADATA_AUTHORITY_FIELDS
            if self.provider == "openmetadata"
            else GRAVITINO_AUTHORITY_FIELDS
        )
        expected_state_fields = (
            OPENMETADATA_STATE_FIELDS if self.provider == "openmetadata" else GRAVITINO_STATE_FIELDS
        )
        if self.authority_fields != expected_authority:
            raise ValueError("projection authority fields do not match provider")
        if set(self.desired_state) != expected_state_fields:
            raise ValueError("projection desired-state fields do not match provider")
        resource_urn = self.desired_state.get("resource_urn")
        resource_version_id = self.desired_state.get("resource_version_id")
        content_sha256 = self.desired_state.get("content_sha256")
        if not isinstance(resource_urn, str):
            raise TypeError("projection ResourceURN is invalid")
        try:
            parse_resource_urn(resource_urn)
            UUID(str(resource_version_id))
        except (TypeError, ValueError) as exc:
            raise ValueError("projection GDA identity is invalid") from exc
        if not SHA256_PATTERN.fullmatch(str(content_sha256 or "")):
            raise ValueError("projection content_sha256 is invalid")
        if self.provider == "openmetadata":
            for field in ("owner_refs", "domain_refs", "tag_refs"):
                refs = self.desired_state.get(field)
                if (
                    not isinstance(refs, list)
                    or not all(isinstance(item, str) and item for item in refs)
                    or refs != sorted(set(refs))
                ):
                    raise ValueError(f"OpenMetadata {field} must be canonical")
            if not self.desired_state["owner_refs"]:
                raise ValueError("OpenMetadata owner_refs must not be empty")
        elif (
            not isinstance(self.desired_state.get("provider_revision"), str)
            or not (self.desired_state["provider_revision"])
        ):
            raise ValueError("Gravitino provider_revision is invalid")
        expected_state_sha = _projection_state_sha256(self.desired_state)
        if self.desired_state_sha256 != expected_state_sha:
            raise ValueError("projection desired_state_sha256 does not match state")
        expected_key = _projection_idempotency_key(
            provider=self.provider,
            target_identity=self.target_identity,
            desired_state_sha256=self.desired_state_sha256,
        )
        if self.idempotency_key != expected_key:
            raise ValueError("projection idempotency_key does not match content")
        return self


class OpenLineageRun(_FrozenModel):
    run_id: UUID = Field(alias="runId")


class OpenLineageJob(_FrozenModel):
    namespace: NonEmptyText
    name: NonEmptyText


class OpenLineageDataset(_FrozenModel):
    namespace: NonEmptyText
    name: NonEmptyText


class OpenLineageRunEvent(_FrozenModel):
    schema_url: Literal[
        "https://openlineage.io/spec/2-0-2/OpenLineage.json#/definitions/RunEvent"
    ] = Field(default=OPENLINEAGE_SCHEMA_URL, alias="schemaURL")
    event_type: Literal["COMPLETE"] = Field(default="COMPLETE", alias="eventType")
    event_time: datetime = Field(alias="eventTime")
    producer: Literal[
        "https://github.com/zhouning/gisdataagent/data_agent/metadata_fabric_ingestion.py"
    ] = OPENLINEAGE_PRODUCER
    run: OpenLineageRun
    job: OpenLineageJob
    inputs: tuple[OpenLineageDataset, ...] = Field(min_length=1)
    outputs: tuple[OpenLineageDataset, ...] = Field(min_length=1)

    @field_validator("event_time")
    @classmethod
    def _aware_event_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("OpenLineage eventTime must include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _unique_datasets(self) -> Self:
        inputs = [(item.namespace, item.name) for item in self.inputs]
        outputs = [(item.namespace, item.name) for item in self.outputs]
        if len(inputs) != len(set(inputs)) or len(outputs) != len(set(outputs)):
            raise ValueError("OpenLineage datasets must be unique")
        return self


def _openlineage_sha256(event: OpenLineageRunEvent) -> str:
    return canonical_json_fingerprint(event.model_dump(mode="json", by_alias=True))


def _plan_idempotency_payload(values: dict[str, Any]) -> dict[str, Any]:
    projection_keys = [
        (item["idempotency_key"] if isinstance(item, dict) else item.idempotency_key)
        for item in values["projections"]
    ]
    return {
        "tenant_id": values["tenant_id"],
        "resource_urn": values["resource_urn"],
        "resource_version_id": str(values["resource_version_id"]),
        "content_sha256": values["content_sha256"],
        "run_success_evidence_sha256": values["run_success_evidence_sha256"],
        "quality_result_sha256": values["quality_result_sha256"],
        "lineage_event_sha256": values["lineage_event_sha256"],
        "binding_sha256": values["binding_sha256"],
        "projection_idempotency_keys": projection_keys,
        "openlineage_event_sha256": values["openlineage_event_sha256"],
    }


class MetadataFabricIngestionPlan(_FrozenModel):
    ingestion_schema: Literal["gda.metadata_fabric_ingestion_plan.v1"] = Field(
        default=INGESTION_PLAN_SCHEMA,
        alias="schema",
    )
    tenant_id: TenantId
    resource_urn: NonEmptyText
    resource_version_id: UUID
    source_resource_version_id: UUID
    content_sha256: Sha256
    run_id: UUID
    definition_version_id: UUID
    output_artifact_id: UUID
    quality_result_id: UUID
    lineage_event_id: UUID
    run_success_evidence_sha256: Sha256
    quality_result_sha256: Sha256
    lineage_event_sha256: Sha256
    binding_sha256: Sha256
    projections: tuple[ProviderProjection, ...] = Field(min_length=2)
    openlineage_event: OpenLineageRunEvent
    openlineage_event_sha256: Sha256
    provider_apply_authorized: Literal[False] = False
    provider_mutations_executed: Literal[False] = False
    writes_to_gda_control: Literal[False] = False
    writes_to_legacy: Literal[False] = False
    production_ingestion_verified: Literal[False] = False
    idempotency_key: Sha256
    plan_sha256: Sha256

    @model_validator(mode="after")
    def _content_bound_plan(self) -> Self:
        if parse_resource_urn(self.resource_urn)["tenant_id"] != self.tenant_id:
            raise ValueError("ingestion ResourceURN tenant does not match")
        providers = [projection.provider for projection in self.projections]
        if providers.count("openmetadata") != 1 or providers.count("gravitino") < 1:
            raise ValueError("ingestion plan requires one governance projection")
        targets = [projection.target_identity for projection in self.projections]
        if len(targets) != len(set(targets)):
            raise ValueError("ingestion projection targets must be unique")
        expected_identity = (
            self.resource_urn,
            str(self.resource_version_id),
            self.content_sha256,
        )
        for projection in self.projections:
            observed_identity = tuple(
                projection.desired_state[field]
                for field in (
                    "resource_urn",
                    "resource_version_id",
                    "content_sha256",
                )
            )
            if observed_identity != expected_identity:
                raise ValueError("projection GDA identity does not match plan")
        if self.openlineage_event.run.run_id != self.run_id:
            raise ValueError("OpenLineage run does not match ingestion run")
        expected_namespace = f"gda://{self.tenant_id}"
        if (
            len(self.openlineage_event.inputs) != 1
            or len(self.openlineage_event.outputs) != 1
            or self.openlineage_event.inputs[0].namespace != expected_namespace
            or self.openlineage_event.outputs[0].namespace != expected_namespace
            or not self.openlineage_event.inputs[0].name.endswith(
                f"@{self.source_resource_version_id}"
            )
            or not self.openlineage_event.outputs[0].name.endswith(f"@{self.resource_version_id}")
        ):
            raise ValueError("OpenLineage datasets do not match ingestion versions")
        if self.openlineage_event_sha256 != _openlineage_sha256(self.openlineage_event):
            raise ValueError("OpenLineage event fingerprint does not match")
        values = self.model_dump(mode="python")
        expected_key = canonical_json_fingerprint(_plan_idempotency_payload(values))
        if self.idempotency_key != expected_key:
            raise ValueError("ingestion idempotency_key does not match evidence")
        stable = self.model_dump(mode="json", by_alias=True, exclude={"plan_sha256"})
        if self.plan_sha256 != canonical_json_fingerprint(stable):
            raise ValueError("ingestion plan_sha256 does not match plan")
        return self


def _replay_fingerprint(values: dict[str, Any]) -> str:
    return canonical_json_fingerprint(
        {
            "schema": REPLAY_DECISION_SCHEMA,
            "plan_sha256": values["plan_sha256"],
            "reconciliation_sha256": values["reconciliation_sha256"],
            "status": values["status"],
            "blockers": list(values["blockers"]),
            "projection_idempotency_keys": list(values["projection_idempotency_keys"]),
            "provider_apply_authorized": False,
            "provider_mutations_executed": False,
            "writes_to_gda_control": False,
            "writes_to_legacy": False,
            "production_ingestion_verified": False,
        }
    )


class MetadataFabricReplayDecision(_FrozenModel):
    replay_schema: Literal["gda.metadata_fabric_ingestion_replay.v1"] = Field(
        default=REPLAY_DECISION_SCHEMA,
        alias="schema",
    )
    plan_sha256: Sha256
    reconciliation_sha256: Sha256
    status: ReplayStatus
    blockers: tuple[NonEmptyText, ...] = ()
    projection_idempotency_keys: tuple[Sha256, ...] = Field(min_length=2)
    provider_apply_authorized: Literal[False] = False
    provider_mutations_executed: Literal[False] = False
    writes_to_gda_control: Literal[False] = False
    writes_to_legacy: Literal[False] = False
    production_ingestion_verified: Literal[False] = False
    replay_sha256: Sha256

    @model_validator(mode="after")
    def _consistent_replay(self) -> Self:
        if (self.status == ReplayStatus.NO_OP) != (not self.blockers):
            raise ValueError("no-op replay must have no blockers")
        values = self.model_dump(mode="python")
        values["status"] = self.status.value
        if self.replay_sha256 != _replay_fingerprint(values):
            raise ValueError("replay_sha256 does not match decision")
        return self


def _openmetadata_state(
    observation: bridge.OpenMetadataObservation,
) -> dict[str, Any]:
    return {
        "resource_urn": observation.resource_urn,
        "resource_version_id": str(observation.resource_version_id),
        "content_sha256": observation.content_sha256,
        "owner_refs": sorted(set(observation.owner_refs)),
        "domain_refs": sorted(set(observation.domain_refs)),
        "tag_refs": sorted(set(observation.tag_refs)),
    }


def _gravitino_state(
    observation: bridge.GravitinoObservation,
) -> dict[str, Any]:
    return {
        "resource_urn": observation.resource_urn,
        "resource_version_id": str(observation.resource_version_id),
        "content_sha256": observation.content_sha256,
        "provider_revision": observation.provider_revision,
    }


def _projection(
    *,
    provider: Literal["openmetadata", "gravitino"],
    target_identity: str,
    desired_state: dict[str, Any],
) -> ProviderProjection:
    desired_sha = _projection_state_sha256(desired_state)
    return ProviderProjection(
        provider=provider,
        target_identity=target_identity,
        authority_fields=(
            OPENMETADATA_AUTHORITY_FIELDS
            if provider == "openmetadata"
            else GRAVITINO_AUTHORITY_FIELDS
        ),
        desired_state=desired_state,
        desired_state_sha256=desired_sha,
        idempotency_key=_projection_idempotency_key(
            provider=provider,
            target_identity=target_identity,
            desired_state_sha256=desired_sha,
        ),
    )


def _dataset_identity(version: ResourceVersion) -> OpenLineageDataset:
    parsed = parse_resource_urn(version.resource_urn)
    return OpenLineageDataset(
        namespace=f"gda://{version.tenant_id}",
        name=(f"{parsed['resource_kind']}/{parsed['resource_id']}@{version.resource_version_id}"),
    )


def _lineage_event(
    *,
    run: PlatformRun,
    definition: PlatformDefinitionVersion,
    source: ResourceVersion,
    target: ResourceVersion,
    lineage: LineageEvent,
) -> OpenLineageRunEvent:
    return OpenLineageRunEvent(
        eventTime=lineage.occurred_at,
        run={"runId": run.run_id},
        job={
            "namespace": f"gda://{run.tenant_id}/dataops",
            "name": definition.capability_id,
        },
        inputs=(_dataset_identity(source),),
        outputs=(_dataset_identity(target),),
    )


def _validate_terminal_evidence(
    *,
    metadata_resource: Resource,
    target: ResourceVersion,
    binding: bridge.MetadataFabricBinding,
    definition: PlatformDefinitionVersion,
    run: PlatformRun,
    source: ResourceVersion,
    artifact: Artifact,
    quality: QualityResult,
    lineage: LineageEvent,
    success: RunSuccessEvidence,
) -> None:
    errors: list[str] = []
    identities = {
        metadata_resource.tenant_id,
        target.tenant_id,
        binding.tenant_id,
        definition.tenant_id,
        run.tenant_id,
        source.tenant_id,
        artifact.tenant_id,
        quality.tenant_id,
        lineage.tenant_id,
        success.tenant_id,
    }
    if len(identities) != 1:
        errors.append("tenant identity differs across ingestion evidence")
    if (
        target.resource_urn != metadata_resource.resource_urn
        or target.resource_version_id != binding.resource_version_id
        or target.content_sha256 != binding.content_sha256
    ):
        errors.append("target ResourceVersion does not match Metadata Fabric binding")
    if run.definition_version_id != definition.definition_version_id:
        errors.append("run does not match definition")
    if source.resource_version_id not in {item.resource_version_id for item in run.input_bindings}:
        errors.append("lineage source is not an immutable run input")
    if artifact.artifact_role != ArtifactRole.OUTPUT:
        errors.append("ingestion output artifact role is not output")
    if (
        artifact.run_id != run.run_id
        or artifact.resource_version_id != target.resource_version_id
        or artifact.content_sha256 != target.content_sha256
    ):
        errors.append("output artifact does not bind the target ResourceVersion")
    if (
        quality.run_id != run.run_id
        or quality.resource_version_id != target.resource_version_id
        or quality.verdict != QualityVerdict.PASSED
    ):
        errors.append("passed QualityResult does not bind the target ResourceVersion")
    if quality.evaluated_by == artifact.created_by:
        errors.append("quality evaluator is not independent from output producer")
    if (
        lineage.event_type != LineageEventType.DERIVE
        or lineage.source_resource_version_id != source.resource_version_id
        or lineage.target_resource_version_id != target.resource_version_id
        or lineage.run_id != run.run_id
        or lineage.definition_version_id != definition.definition_version_id
        or lineage.artifact_id != artifact.artifact_id
    ):
        errors.append("lineage event does not bind source, target, run and artifact")
    lineage_evidence = {
        "event_type": lineage.event_type.value,
        "source_resource_version_id": str(lineage.source_resource_version_id),
        "target_resource_version_id": str(lineage.target_resource_version_id),
        "run_id": str(lineage.run_id),
        "definition_version_id": str(lineage.definition_version_id),
        "artifact_id": str(lineage.artifact_id),
        "producer": lineage.producer,
        "facets": lineage.facets,
        "occurred_at": lineage.occurred_at.isoformat().replace("+00:00", "Z"),
    }
    if lineage.event_sha256 != canonical_json_fingerprint(lineage_evidence):
        errors.append("LineageEvent content hash does not match evidence")
    if (
        success.run_id != run.run_id
        or success.output_artifact_id != artifact.artifact_id
        or success.quality_result_id != quality.quality_result_id
        or success.lineage_event_id != lineage.lineage_event_id
    ):
        errors.append("RunSuccessEvidence does not bind terminal evidence")
    if errors:
        raise MetadataFabricIngestionError("; ".join(errors))


def build_ingestion_plan(
    *,
    metadata_resource: Resource,
    target: ResourceVersion,
    binding: bridge.MetadataFabricBinding,
    definition: PlatformDefinitionVersion,
    run: PlatformRun,
    source: ResourceVersion,
    artifact: Artifact,
    quality: QualityResult,
    lineage: LineageEvent,
    success: RunSuccessEvidence,
    openmetadata: bridge.OpenMetadataObservation,
    gravitino: tuple[bridge.GravitinoObservation, ...],
) -> MetadataFabricIngestionPlan:
    """Build a deterministic projection plan from terminal platform evidence."""
    _validate_terminal_evidence(
        metadata_resource=metadata_resource,
        target=target,
        binding=binding,
        definition=definition,
        run=run,
        source=source,
        artifact=artifact,
        quality=quality,
        lineage=lineage,
        success=success,
    )
    reconciliation = bridge.reconcile_metadata_fabric(
        metadata_resource,
        target,
        binding,
        openmetadata,
        gravitino,
    )
    if reconciliation.status != bridge.ReconciliationStatus.VERIFIED:
        raise MetadataFabricIngestionError(
            "provider observations do not match binding: " + ", ".join(reconciliation.blockers)
        )
    projections = (
        _projection(
            provider="openmetadata",
            target_identity=f"table:{binding.openmetadata.entity_id}",
            desired_state=_openmetadata_state(openmetadata),
        ),
        *(
            _projection(
                provider="gravitino",
                target_identity=f"table:{observation.ref.identity}",
                desired_state=_gravitino_state(observation),
            )
            for observation in sorted(
                gravitino,
                key=lambda item: item.ref.identity,
            )
        ),
    )
    openlineage = _lineage_event(
        run=run,
        definition=definition,
        source=source,
        target=target,
        lineage=lineage,
    )
    values: dict[str, Any] = {
        "tenant_id": target.tenant_id,
        "resource_urn": target.resource_urn,
        "resource_version_id": target.resource_version_id,
        "source_resource_version_id": source.resource_version_id,
        "content_sha256": target.content_sha256,
        "run_id": run.run_id,
        "definition_version_id": definition.definition_version_id,
        "output_artifact_id": artifact.artifact_id,
        "quality_result_id": quality.quality_result_id,
        "lineage_event_id": lineage.lineage_event_id,
        "run_success_evidence_sha256": success.evidence_sha256,
        "quality_result_sha256": quality.result_sha256,
        "lineage_event_sha256": lineage.event_sha256,
        "binding_sha256": binding.binding_sha256,
        "projections": projections,
        "openlineage_event": openlineage,
        "openlineage_event_sha256": _openlineage_sha256(openlineage),
    }
    values["idempotency_key"] = canonical_json_fingerprint(_plan_idempotency_payload(values))
    stable = {
        "schema": INGESTION_PLAN_SCHEMA,
        **{
            key: (
                value.model_dump(mode="json", by_alias=True)
                if isinstance(value, BaseModel)
                else [item.model_dump(mode="json", by_alias=True) for item in value]
                if key == "projections"
                else str(value)
                if isinstance(value, UUID)
                else value
            )
            for key, value in values.items()
        },
        "provider_apply_authorized": False,
        "provider_mutations_executed": False,
        "writes_to_gda_control": False,
        "writes_to_legacy": False,
        "production_ingestion_verified": False,
    }
    values["plan_sha256"] = canonical_json_fingerprint(stable)
    return MetadataFabricIngestionPlan(**values)


def evaluate_replay(
    plan: MetadataFabricIngestionPlan,
    *,
    resource: Resource,
    version: ResourceVersion,
    binding: bridge.MetadataFabricBinding,
    openmetadata: bridge.OpenMetadataObservation,
    gravitino: tuple[bridge.GravitinoObservation, ...],
) -> MetadataFabricReplayDecision:
    """Return no-op for identical projection state and block every drift."""
    reconciliation = bridge.reconcile_metadata_fabric(
        resource,
        version,
        binding,
        openmetadata,
        gravitino,
    )
    blockers = list(reconciliation.blockers)
    observed = {
        ("openmetadata", f"table:{openmetadata.ref.entity_id}"): (
            _openmetadata_state(openmetadata)
        ),
        **{
            ("gravitino", f"table:{item.ref.identity}"): _gravitino_state(item)
            for item in gravitino
        },
    }
    expected_targets = {
        (projection.provider, projection.target_identity) for projection in plan.projections
    }
    if set(observed) != expected_targets:
        blockers.append("projection_target_inventory_drift")
    for projection in plan.projections:
        state = observed.get((projection.provider, projection.target_identity))
        if state is None:
            continue
        if _projection_state_sha256(state) != projection.desired_state_sha256:
            blockers.append(
                f"projection_state_drift:{projection.provider}:{projection.target_identity}"
            )
    blocker_tuple = tuple(sorted(set(blockers)))
    status = ReplayStatus.BLOCKED if blocker_tuple else ReplayStatus.NO_OP
    values = {
        "plan_sha256": plan.plan_sha256,
        "reconciliation_sha256": reconciliation.reconciliation_sha256,
        "status": status.value,
        "blockers": blocker_tuple,
        "projection_idempotency_keys": tuple(
            projection.idempotency_key for projection in plan.projections
        ),
    }
    return MetadataFabricReplayDecision(
        **values,
        replay_sha256=_replay_fingerprint(values),
    )


def _load_contract_inputs(
    platform_path: Path,
    metadata_path: Path,
) -> tuple[
    dict[str, Any],
    dict[str, Any],
    Resource,
    ResourceVersion,
    bridge.MetadataFabricBinding,
    PlatformDefinitionVersion,
    PlatformRun,
    ResourceVersion,
    Artifact,
    QualityResult,
    LineageEvent,
    RunSuccessEvidence,
    bridge.OpenMetadataObservation,
    tuple[bridge.GravitinoObservation, ...],
]:
    platform_report = platform_crosswalk.validate_golden_fixture(platform_path)
    if platform_report["status"] != "valid":
        raise MetadataFabricIngestionError(
            "platform golden fixture is invalid: " + ", ".join(platform_report["errors"])
        )
    bridge.build_metadata_fabric_bridge_report(metadata_path)
    platform_payload = _load_json_object(platform_path)
    metadata_payload = _load_json_object(metadata_path)
    contracts = platform_payload["contracts"]
    metadata_resource = Resource.model_validate(metadata_payload["resource"])
    target = ResourceVersion.model_validate(contracts["target_resource_version"])
    metadata_target = ResourceVersion.model_validate(metadata_payload["resource_version"])
    if target != metadata_target:
        raise MetadataFabricIngestionError(
            "platform and Metadata Fabric target ResourceVersion differ"
        )
    openmetadata_ref = bridge.OpenMetadataTableRef.model_validate(
        metadata_payload["openmetadata_ref"]
    )
    gravitino_refs = tuple(
        bridge.GravitinoTableRef.model_validate(item) for item in metadata_payload["gravitino_refs"]
    )
    binding = bridge.build_metadata_fabric_binding(
        metadata_resource,
        target,
        openmetadata=openmetadata_ref,
        gravitino=gravitino_refs,
    )
    observed_at = datetime.fromisoformat(metadata_payload["observed_at"])
    openmetadata = bridge.parse_openmetadata_table_observation(
        openmetadata_ref,
        metadata_payload["openmetadata_response"],
        observed_at=observed_at,
    )
    gravitino = tuple(
        bridge.parse_gravitino_table_observation(
            ref,
            response,
            observed_at=observed_at,
        )
        for ref, response in zip(
            gravitino_refs,
            metadata_payload["gravitino_responses"],
            strict=True,
        )
    )
    return (
        platform_payload,
        metadata_payload,
        metadata_resource,
        target,
        binding,
        PlatformDefinitionVersion.model_validate(contracts["definition"]),
        PlatformRun.model_validate(contracts["run"]),
        ResourceVersion.model_validate(contracts["source_resource_version"]),
        Artifact.model_validate(contracts["artifact"]),
        QualityResult.model_validate(contracts["quality_result"]),
        LineageEvent.model_validate(contracts["lineage_event"]),
        RunSuccessEvidence.model_validate(contracts["run_success_evidence"]),
        openmetadata,
        gravitino,
    )


def build_ingestion_contract_report(
    *,
    platform_path: Path = DEFAULT_PLATFORM_FIXTURE,
    metadata_path: Path = DEFAULT_METADATA_FIXTURE,
    expected_path: Path = DEFAULT_EXPECTED_FIXTURE,
) -> dict[str, Any]:
    """Validate the checked-in M3-1 golden projection and replay contract."""
    (
        platform_payload,
        metadata_payload,
        metadata_resource,
        target,
        binding,
        definition,
        run,
        source,
        artifact,
        quality,
        lineage,
        success,
        openmetadata,
        gravitino,
    ) = _load_contract_inputs(platform_path.resolve(), metadata_path.resolve())
    plan = build_ingestion_plan(
        metadata_resource=metadata_resource,
        target=target,
        binding=binding,
        definition=definition,
        run=run,
        source=source,
        artifact=artifact,
        quality=quality,
        lineage=lineage,
        success=success,
        openmetadata=openmetadata,
        gravitino=gravitino,
    )
    replay = evaluate_replay(
        plan,
        resource=metadata_resource,
        version=target,
        binding=binding,
        openmetadata=openmetadata,
        gravitino=gravitino,
    )
    expected = _load_json_object(expected_path.resolve())
    if expected.get("schema") != EXPECTED_SCHEMA:
        raise MetadataFabricIngestionError("ingestion expected fixture schema drift")
    actual = {
        "platform_fixture_sha256": canonical_json_fingerprint(platform_payload),
        "metadata_fixture_sha256": canonical_json_fingerprint(metadata_payload),
        "plan_sha256": plan.plan_sha256,
        "openlineage_event_sha256": plan.openlineage_event_sha256,
        "replay_sha256": replay.replay_sha256,
    }
    if {key: expected.get(key) for key in actual} != actual:
        raise MetadataFabricIngestionError("ingestion golden fingerprint drift")
    return {
        "schema": REPORT_SCHEMA,
        "m3_1_contract_verified": True,
        "terminal_evidence_bound": True,
        "deterministic_replay_verified": replay.status == ReplayStatus.NO_OP,
        "openlineage_candidate_contract_verified": True,
        "projection_count": len(plan.projections),
        "plan_sha256": plan.plan_sha256,
        "openlineage_event_sha256": plan.openlineage_event_sha256,
        "replay_sha256": replay.replay_sha256,
        "replay_status": replay.status.value,
        "provider_apply_authorized": False,
        "provider_mutations_executed": False,
        "writes_to_gda_control": False,
        "writes_to_legacy": False,
        "live_provider_ingestion_verified": False,
        "production_ingestion_verified": False,
        "production_ready": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate")
    validate.add_argument("--platform-fixture", type=Path, default=DEFAULT_PLATFORM_FIXTURE)
    validate.add_argument("--metadata-fixture", type=Path, default=DEFAULT_METADATA_FIXTURE)
    validate.add_argument("--expected", type=Path, default=DEFAULT_EXPECTED_FIXTURE)
    args = parser.parse_args(argv)
    if args.command == "validate":
        try:
            report = build_ingestion_contract_report(
                platform_path=args.platform_fixture,
                metadata_path=args.metadata_fixture,
                expected_path=args.expected,
            )
        except (
            OSError,
            ValueError,
            json.JSONDecodeError,
            MetadataFabricIngestionError,
        ) as exc:
            print(f"metadata fabric ingestion contract: {exc}")
            return 1
        print(json.dumps(report, ensure_ascii=True, sort_keys=True, indent=2))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
