"""Bounded OpenLineage ingestion contracts for the platform control ledger."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any, Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StringConstraints,
    field_validator,
    model_validator,
)

from .platform_contracts import (
    LineageEvent,
    LineageEventType,
    TenantId,
    canonical_json_bytes,
    canonical_json_fingerprint,
)

OPENLINEAGE_INGESTION_SCHEMA = "gda.openlineage_ingestion.v1"
OPENLINEAGE_FACETS_SCHEMA = "gda.openlineage_facets.v1"
MAX_INPUT_DATASETS = 64
MAX_OUTPUT_DATASETS = 64
MAX_GENERATED_EDGES = 256
MAX_EVENT_BYTES = 1_048_576

_LINEAGE_EVENT_NAMESPACE = uuid5(
    NAMESPACE_URL,
    "https://gis-data-agent.local/contracts/openlineage-lineage-event/v1",
)

FacetName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=256),
]
FacetMap = Annotated[dict[FacetName, JsonValue], Field(max_length=32)]
NamespaceText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=512),
]
DatasetName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=1024),
]
ProducerUri = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=2048),
]


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class GdaPlatformRunFacet(_FrozenModel):
    """GDA correlation keys required on an OpenLineage Run facet."""

    tenant_id: TenantId = Field(alias="tenantId")
    platform_run_id: UUID = Field(alias="platformRunId")
    definition_version_id: UUID = Field(alias="definitionVersionId")
    artifact_id: UUID = Field(alias="artifactId")
    operation: LineageEventType
    facet_producer: ProducerUri | None = Field(default=None, alias="_producer")
    schema_url: ProducerUri | None = Field(default=None, alias="_schemaURL")


class GdaResourceFacet(_FrozenModel):
    """GDA immutable resource version required on every Dataset facet."""

    resource_version_id: UUID = Field(alias="resourceVersionId")
    facet_producer: ProducerUri | None = Field(default=None, alias="_producer")
    schema_url: ProducerUri | None = Field(default=None, alias="_schemaURL")


class OpenLineageRun(_FrozenModel):
    run_id: UUID = Field(alias="runId")
    facets: FacetMap = Field(default_factory=dict)

    def gda_platform(self) -> GdaPlatformRunFacet:
        value = self.facets.get("gda_platform")
        if value is None:
            raise ValueError("run facets must include gda_platform")
        return GdaPlatformRunFacet.model_validate(value)


class OpenLineageJob(_FrozenModel):
    namespace: NamespaceText
    name: DatasetName
    facets: FacetMap = Field(default_factory=dict)


class OpenLineageDataset(_FrozenModel):
    namespace: NamespaceText
    name: DatasetName
    facets: FacetMap

    def gda_resource(self) -> GdaResourceFacet:
        value = self.facets.get("gda_resource")
        if value is None:
            raise ValueError("dataset facets must include gda_resource")
        return GdaResourceFacet.model_validate(value)


class OpenLineageRunEvent(_FrozenModel):
    """The supported, deliberately narrow OpenLineage RunEvent surface."""

    event_type: Literal["COMPLETE"] = Field(alias="eventType")
    event_time: datetime = Field(alias="eventTime")
    run: OpenLineageRun
    job: OpenLineageJob
    inputs: tuple[OpenLineageDataset, ...] = Field(
        min_length=1,
        max_length=MAX_INPUT_DATASETS,
    )
    outputs: tuple[OpenLineageDataset, ...] = Field(
        min_length=1,
        max_length=MAX_OUTPUT_DATASETS,
    )
    producer: ProducerUri
    schema_url: ProducerUri | None = Field(default=None, alias="schemaURL")

    @field_validator("event_time")
    @classmethod
    def _aware_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("eventTime must include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _bounded_and_correlated(self) -> OpenLineageRunEvent:
        try:
            self.run.gda_platform()
            input_ids = [dataset.gda_resource().resource_version_id for dataset in self.inputs]
            output_ids = [dataset.gda_resource().resource_version_id for dataset in self.outputs]
        except (TypeError, ValueError) as exc:
            raise ValueError(str(exc)) from exc

        edge_count = len(self.inputs) * len(self.outputs)
        if edge_count > MAX_GENERATED_EDGES:
            raise ValueError(
                f"OpenLineage event would generate {edge_count} edges; "
                f"limit is {MAX_GENERATED_EDGES}"
            )
        if len(input_ids) != len(set(input_ids)):
            raise ValueError("input resourceVersionId values must be unique")
        if len(output_ids) != len(set(output_ids)):
            raise ValueError("output resourceVersionId values must be unique")
        if set(input_ids).intersection(output_ids):
            raise ValueError("input and output resourceVersionId values must not overlap")

        encoded = canonical_json_bytes(self.model_dump(mode="json", by_alias=True))
        if len(encoded) > MAX_EVENT_BYTES:
            raise ValueError(f"OpenLineage event exceeds {MAX_EVENT_BYTES} bytes")
        return self


class OpenLineageIngestionItem(_FrozenModel):
    lineage_event: LineageEvent
    created: bool


class OpenLineageIngestionResult(_FrozenModel):
    schema_version: Literal[OPENLINEAGE_INGESTION_SCHEMA] = OPENLINEAGE_INGESTION_SCHEMA
    run_id: UUID
    event_count: int = Field(ge=1, le=MAX_GENERATED_EDGES)
    created_count: int = Field(ge=0, le=MAX_GENERATED_EDGES)
    replayed_count: int = Field(ge=0, le=MAX_GENERATED_EDGES)
    items: tuple[OpenLineageIngestionItem, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _counts_match_items(self) -> OpenLineageIngestionResult:
        created = sum(item.created for item in self.items)
        if self.event_count != len(self.items):
            raise ValueError("event_count must match items")
        if self.created_count != created:
            raise ValueError("created_count must match items")
        if self.replayed_count != self.event_count - self.created_count:
            raise ValueError("replayed_count must match items")
        return self


def _dataset_ref(dataset: OpenLineageDataset) -> dict[str, Any]:
    return {
        "namespace": dataset.namespace,
        "name": dataset.name,
        "facets_sha256": canonical_json_fingerprint(dataset.facets),
    }


def _lineage_event_id(
    event: OpenLineageRunEvent,
    *,
    tenant_id: str,
    operation: LineageEventType,
    source: OpenLineageDataset,
    target: OpenLineageDataset,
) -> UUID:
    platform = event.run.gda_platform()
    identity = {
        "schema": OPENLINEAGE_FACETS_SCHEMA,
        "tenant_id": tenant_id,
        "openlineage_run_id": str(event.run.run_id),
        "platform_run_id": str(platform.platform_run_id),
        "definition_version_id": str(platform.definition_version_id),
        "artifact_id": str(platform.artifact_id),
        "job": {"namespace": event.job.namespace, "name": event.job.name},
        "operation": operation.value,
        "source": {
            "namespace": source.namespace,
            "name": source.name,
            "resource_version_id": str(source.gda_resource().resource_version_id),
        },
        "target": {
            "namespace": target.namespace,
            "name": target.name,
            "resource_version_id": str(target.gda_resource().resource_version_id),
        },
    }
    return uuid5(_LINEAGE_EVENT_NAMESPACE, canonical_json_fingerprint(identity))


def _event_fingerprint(event: LineageEvent) -> str:
    logical_event = event.model_dump(mode="json", exclude={"event_sha256"})
    return canonical_json_fingerprint(
        {"schema": "gda.lineage_event_fingerprint.v1", "event": logical_event}
    )


def openlineage_to_lineage_events(
    event: OpenLineageRunEvent,
    *,
    authenticated_producer: str,
) -> tuple[LineageEvent, ...]:
    """Convert one COMPLETE event into stable input-to-output ledger edges."""
    if not authenticated_producer.startswith("workload:"):
        raise ValueError("authenticated_producer must use workload identity")

    platform = event.run.gda_platform()
    shared_openlineage = {
        "event_type": event.event_type,
        "run_id": str(event.run.run_id),
        "job": {"namespace": event.job.namespace, "name": event.job.name},
        "producer": event.producer,
        "schema_url": event.schema_url,
        "run_facets_sha256": canonical_json_fingerprint(event.run.facets),
        "job_facets_sha256": canonical_json_fingerprint(event.job.facets),
    }
    converted: list[LineageEvent] = []
    for source in event.inputs:
        source_id = source.gda_resource().resource_version_id
        for target in event.outputs:
            target_id = target.gda_resource().resource_version_id
            facets = {
                "schema_version": OPENLINEAGE_FACETS_SCHEMA,
                "openlineage": {
                    **shared_openlineage,
                    "input_dataset": _dataset_ref(source),
                    "output_dataset": _dataset_ref(target),
                },
            }
            lineage = LineageEvent(
                tenant_id=platform.tenant_id,
                lineage_event_id=_lineage_event_id(
                    event,
                    tenant_id=platform.tenant_id,
                    operation=platform.operation,
                    source=source,
                    target=target,
                ),
                event_type=platform.operation,
                source_resource_version_id=source_id,
                target_resource_version_id=target_id,
                producer=authenticated_producer,
                event_sha256="0" * 64,
                run_id=platform.platform_run_id,
                definition_version_id=platform.definition_version_id,
                artifact_id=platform.artifact_id,
                facets=facets,
                occurred_at=event.event_time,
            )
            converted.append(
                lineage.model_copy(update={"event_sha256": _event_fingerprint(lineage)})
            )
    return tuple(converted)
