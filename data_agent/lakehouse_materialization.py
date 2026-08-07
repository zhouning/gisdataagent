"""Product-neutral recording for governed Iceberg materializations."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from data_agent.platform_contracts import (
    Artifact,
    ArtifactRole,
    LineageEvent,
    LineageEventType,
    PlatformRun,
    QualityResult,
    Resource,
    ResourceVersion,
    canonical_json_bytes,
    canonical_json_fingerprint,
    quality_result_fingerprint,
)
from data_agent.platform_gateway import GatewayNotFoundError, PlatformGateway


@dataclass(frozen=True)
class LakehouseMaterializationContract:
    """Stable identities and governance policy for one Iceberg target."""

    output_resource_urn: str
    iceberg_table: str
    iceberg_storage_uri: str
    source_resource_version_id: UUID
    workload_subject: str
    quality_evaluator: str
    quality_rule_version: str
    governance_ref: dict[str, Any]
    technical_refs: tuple[dict[str, Any], ...]
    output_artifact_identity: str
    evidence_artifact_identity: str
    lineage_event_identity: str
    output_artifact_key_prefix: str
    evidence_artifact_key_prefix: str
    lineage_schema: str = "gda.default_lakehouse_materialization_lineage.v1"
    evidence_media_type: str = (
        "application/vnd.gda.lakehouse-quality-evidence+json"
    )

    def output_artifact_id(self, run_id: UUID) -> UUID:
        return uuid5(run_id, self.output_artifact_identity)

    def evidence_artifact_id(self, run_id: UUID) -> UUID:
        return uuid5(run_id, self.evidence_artifact_identity)

    def quality_result_id(self, run_id: UUID) -> UUID:
        return uuid5(run_id, f"quality:{self.quality_rule_version}")

    def lineage_event_id(self, run_id: UUID) -> UUID:
        return uuid5(run_id, self.lineage_event_identity)

    def output_resource_version_id(self, snapshot_id: int) -> UUID:
        return uuid5(
            NAMESPACE_URL,
            f"{self.output_resource_urn}:snapshot:{snapshot_id}",
        )


@dataclass(frozen=True)
class LakehouseMaterializationEvidence:
    """Product-specific evidence already validated by its provider adapter."""

    evidence_document: dict[str, Any]
    output_manifest: dict[str, Any]
    lineage_facets: dict[str, Any]
    quality_metrics: dict[str, Any]
    quality_verdict: str = "passed"


@dataclass(frozen=True)
class LakehouseMaterializationRecord:
    run_id: UUID
    definition_version_id: UUID
    source_resource_version_id: UUID
    output_resource_version_id: UUID
    output_artifact_id: UUID
    evidence_artifact_id: UUID
    quality_result_id: UUID
    lineage_event_id: UUID
    iceberg_table: str
    snapshot_id: int
    feature_count: int
    replayed: bool


class LakehouseMaterializationRecorder:
    """Persist the common evidence graph for a validated provider commit."""

    def __init__(
        self,
        contract: LakehouseMaterializationContract,
        *,
        gateway: PlatformGateway,
    ) -> None:
        self.contract = contract
        self.gateway = gateway

    def existing(
        self,
        *,
        tenant_id: str,
        run_id: UUID,
        definition_version_id: UUID,
    ) -> LakehouseMaterializationRecord | None:
        try:
            quality = self.gateway.get_quality_result(
                tenant_id,
                self.contract.quality_result_id(run_id),
            )
            artifact = self.gateway.get_artifact(
                tenant_id,
                self.contract.output_artifact_id(run_id),
            )
        except GatewayNotFoundError:
            return None
        if quality.run_id != run_id or artifact.run_id != run_id:
            raise ValueError("stored lakehouse evidence does not match the requested run")
        if artifact.resource_version_id is None:
            raise ValueError("stored lakehouse output does not bind a resource version")
        manifest = artifact.manifest
        return LakehouseMaterializationRecord(
            run_id=run_id,
            definition_version_id=definition_version_id,
            source_resource_version_id=self.contract.source_resource_version_id,
            output_resource_version_id=artifact.resource_version_id,
            output_artifact_id=artifact.artifact_id,
            evidence_artifact_id=quality.evidence_artifact_id,
            quality_result_id=quality.quality_result_id,
            lineage_event_id=self.contract.lineage_event_id(run_id),
            iceberg_table=str(manifest["iceberg_table"]),
            snapshot_id=int(manifest["snapshot_id"]),
            feature_count=int(manifest["feature_count"]),
            replayed=True,
        )

    def record(
        self,
        *,
        run: PlatformRun,
        provider_report: dict[str, Any],
        provider_report_path: Path,
        evidence: LakehouseMaterializationEvidence,
    ) -> LakehouseMaterializationRecord:
        snapshot_id = int(provider_report["snapshot_id"])
        target_version_id = self.contract.output_resource_version_id(snapshot_id)
        occurred_at = run.submitted_at.astimezone(UTC)

        resource_result = self.gateway.register_resource(
            Resource(
                tenant_id=run.tenant_id,
                resource_urn=self.contract.output_resource_urn,
                resource_kind="table",
                authority_system="iceberg",
                authority_locator=self.contract.iceberg_table,
                owner_ref="team:data-platform",
                governance_ref=self.contract.governance_ref,
                technical_refs=self.contract.technical_refs,
            )
        )
        version_result = self.gateway.register_resource_version(
            ResourceVersion(
                tenant_id=run.tenant_id,
                resource_urn=self.contract.output_resource_urn,
                resource_version_id=target_version_id,
                version_key=f"snapshot-{snapshot_id}",
                content_sha256=str(provider_report["content_fingerprint"]),
                authority_version_ref={
                    "provider": "iceberg",
                    "table": self.contract.iceberg_table,
                    "snapshot_id": snapshot_id,
                    "format_version": 2,
                    "warehouse_uri": provider_report["warehouse_uri"],
                    "source_semantic_sha256": provider_report["semantic_sha256"],
                },
                created_by=self.contract.workload_subject,
                created_at=occurred_at,
            )
        )

        evidence_bytes = canonical_json_bytes(evidence.evidence_document)
        evidence_path = provider_report_path.with_name("quality-evidence.json")
        if evidence_path.exists():
            if evidence_path.read_bytes() != evidence_bytes:
                raise RuntimeError("stored lakehouse evidence differs from replay")
        else:
            temporary = evidence_path.with_name(f".{evidence_path.name}.{os.getpid()}.tmp")
            temporary.write_bytes(evidence_bytes)
            temporary.chmod(0o640)
            os.replace(temporary, evidence_path)

        evidence_id = self.contract.evidence_artifact_id(run.run_id)
        evidence_result = self.gateway.record_artifact(
            Artifact(
                tenant_id=run.tenant_id,
                artifact_id=evidence_id,
                artifact_key=(
                    f"{self.contract.evidence_artifact_key_prefix}_"
                    f"{run.run_id.hex[:12]}"
                ),
                artifact_role=ArtifactRole.EVIDENCE,
                storage_uri=evidence_path.resolve().as_uri(),
                media_type=self.contract.evidence_media_type,
                content_sha256=canonical_json_fingerprint(
                    evidence.evidence_document
                ),
                size_bytes=len(evidence_bytes),
                run_id=run.run_id,
                resource_version_id=target_version_id,
                manifest=evidence.evidence_document,
                created_by=self.contract.quality_evaluator,
                created_at=occurred_at,
            )
        )

        output_id = self.contract.output_artifact_id(run.run_id)
        output_result = self.gateway.record_artifact(
            Artifact(
                tenant_id=run.tenant_id,
                artifact_id=output_id,
                artifact_key=(
                    f"{self.contract.output_artifact_key_prefix}_"
                    f"{run.run_id.hex[:12]}"
                ),
                artifact_role=ArtifactRole.OUTPUT,
                storage_uri=(
                    f"{self.contract.iceberg_storage_uri}/snapshots/{snapshot_id}"
                ),
                media_type="application/vnd.apache.iceberg.snapshot+json",
                content_sha256=str(provider_report["content_fingerprint"]),
                size_bytes=0,
                run_id=run.run_id,
                resource_version_id=target_version_id,
                manifest=evidence.output_manifest,
                created_by=self.contract.workload_subject,
                created_at=occurred_at,
            )
        )

        lineage = LineageEvent(
            tenant_id=run.tenant_id,
            lineage_event_id=self.contract.lineage_event_id(run.run_id),
            event_type=LineageEventType.MATERIALIZE,
            source_resource_version_id=self.contract.source_resource_version_id,
            target_resource_version_id=target_version_id,
            producer=self.contract.workload_subject,
            event_sha256=canonical_json_fingerprint(evidence.lineage_facets),
            run_id=run.run_id,
            definition_version_id=run.definition_version_id,
            artifact_id=output_id,
            facets=evidence.lineage_facets,
            occurred_at=occurred_at,
        )
        lineage_result = self.gateway.record_lineage(lineage)

        quality_id = self.contract.quality_result_id(run.run_id)
        quality = QualityResult(
            tenant_id=run.tenant_id,
            quality_result_id=quality_id,
            run_id=run.run_id,
            resource_version_id=target_version_id,
            rule_version_ref=self.contract.quality_rule_version,
            verdict=evidence.quality_verdict,
            metrics=evidence.quality_metrics,
            evidence_artifact_id=evidence_id,
            result_sha256=quality_result_fingerprint(
                tenant_id=run.tenant_id,
                run_id=run.run_id,
                resource_version_id=target_version_id,
                rule_version_ref=self.contract.quality_rule_version,
                verdict=evidence.quality_verdict,
                metrics=evidence.quality_metrics,
                evidence_artifact_id=evidence_id,
                evaluated_by=self.contract.quality_evaluator,
                evaluated_at=occurred_at,
            ),
            evaluated_by=self.contract.quality_evaluator,
            evaluated_at=occurred_at,
        )
        quality_result = self.gateway.record_quality_result(quality)

        return LakehouseMaterializationRecord(
            run_id=run.run_id,
            definition_version_id=run.definition_version_id,
            source_resource_version_id=self.contract.source_resource_version_id,
            output_resource_version_id=target_version_id,
            output_artifact_id=output_id,
            evidence_artifact_id=evidence_id,
            quality_result_id=quality_id,
            lineage_event_id=lineage.lineage_event_id,
            iceberg_table=self.contract.iceberg_table,
            snapshot_id=snapshot_id,
            feature_count=int(provider_report["row_count"]),
            replayed=not any(
                result.created
                for result in (
                    resource_result,
                    version_result,
                    evidence_result,
                    output_result,
                    lineage_result,
                    quality_result,
                )
            ),
        )
