"""Approval-bound publication of an approved JQDLTB layered candidate."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .data_product_registry import (
    DataProductRegistry,
    DataProductSpec,
    DataProductVersionSpec,
    data_product_manifest_fingerprint,
)
from .jqdltb_transformation_executor import JqdltbTransformationResult
from .platform_contracts import (
    ApprovalCase,
    ApprovalCaseStatus,
    Artifact,
    ArtifactRole,
    JqdltbDecisionPacket,
    JqdltbDecisionPacketStatus,
    JqdltbDecisionStatus,
    JqdltbTransformationContract,
    JqdltbTransformationMode,
    LineageEvent,
    PlatformRun,
    QualityResult,
    QualityVerdict,
    RunStatus,
    Sha256,
    TenantId,
    build_resource_urn,
    canonical_json_fingerprint,
)

JQDLTB_PRODUCT_RELEASE_SCHEMA = "gda.jqdltb_data_product_release.v1"
JQDLTB_PRODUCT_RELEASE_ACTION = "data_product.publish_jqdltb"
JQDLTB_LAYERED_DISTRIBUTION_SCHEMA = "gda.jqdltb_layered_distribution.v1"
JQDLTB_MAPPING_BINDING_SCHEMA = "gda.jqdltb_mapping_binding.v1"
JQDLTB_QUALITY_BINDING_SCHEMA = "gda.jqdltb_quality_binding.v1"
_REQUIRED_LAYERS = frozenset({"raw", "ods", "dim", "dwd", "ads", "quarantine"})
_UNRESOLVED_MARKERS = ("pending", "unknown", "unassigned", "tbd", "todo")


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must include a timezone")
    return value.astimezone(UTC)


def _require_resolved(value: str, label: str) -> None:
    normalized = value.strip().lower()
    if not normalized or any(marker in normalized for marker in _UNRESOLVED_MARKERS):
        raise ValueError(f"{label} must be resolved before JQDLTB publication")


class JqdltbReleaseOperatingContract(_FrozenModel):
    """Business and runtime ownership required before a candidate can publish."""

    tenant_id: TenantId
    environment: Literal["development", "staging", "production"]
    business_steward_ref: str = Field(min_length=1, max_length=512)
    license_id: str = Field(min_length=1, max_length=512)
    data_slo_ref: str = Field(min_length=1, max_length=512)
    service_slo_ref: str = Field(min_length=1, max_length=512)
    on_call_ref: str = Field(min_length=1, max_length=512)
    environment_owner_ref: str = Field(min_length=1, max_length=512)
    deployment_profile_ref: str = Field(min_length=1, max_length=512)
    backup_restore_evidence_artifact_id: UUID

    @model_validator(mode="after")
    def _resolved_operating_authority(self) -> JqdltbReleaseOperatingContract:
        for field_name in (
            "business_steward_ref",
            "license_id",
            "data_slo_ref",
            "service_slo_ref",
            "on_call_ref",
            "environment_owner_ref",
            "deployment_profile_ref",
        ):
            _require_resolved(str(getattr(self, field_name)), field_name)
        return self


def _mapping_binding(
    contract: JqdltbTransformationContract,
    decision_packet_sha256: str | None = None,
) -> dict[str, Any]:
    assert contract.approval_case is not None
    return {
        "schema": JQDLTB_MAPPING_BINDING_SCHEMA,
        "transformation_plan_sha256": contract.plan_sha256,
        "transformation_contract_sha256": contract.contract_sha256,
        "transformation_approval_case_ref": contract.approval_case.approval_case_ref,
        "canonical_key": contract.canonical_key,
        "standard_fingerprint": contract.standard_fingerprint,
        "decision_packet_sha256": decision_packet_sha256,
    }


def _quality_binding(quality: QualityResult) -> dict[str, Any]:
    return {
        "schema": JQDLTB_QUALITY_BINDING_SCHEMA,
        "verdict": quality.verdict.value,
        "quality_result_id": str(quality.quality_result_id),
        "quality_result_sha256": quality.result_sha256,
        "rule_version_ref": quality.rule_version_ref,
    }


def _release_approval_case_ref(tenant_id: str, version_id: UUID) -> str:
    return build_resource_urn(
        tenant_id,
        "approval_case",
        f"jqdltb-product-release-{version_id.hex}",
    )


def _layered_distribution(
    *,
    run: PlatformRun,
    result: JqdltbTransformationResult,
    output_artifact: Artifact,
    lineage_event: LineageEvent,
    operating_contract: JqdltbReleaseOperatingContract,
    release_approval_case_ref: str,
    decision_packet_sha256: str | None = None,
) -> dict[str, Any]:
    layers = output_artifact.manifest["layers"]
    return {
        "schema": JQDLTB_LAYERED_DISTRIBUTION_SCHEMA,
        "run_id": str(run.run_id),
        "definition_version_id": str(run.definition_version_id),
        "transformation_output_artifact_id": str(output_artifact.artifact_id),
        "lineage_event_id": str(lineage_event.lineage_event_id),
        "release_approval_case_ref": release_approval_case_ref,
        "decision_packet_sha256": decision_packet_sha256,
        "layer_manifest_sha256": canonical_json_fingerprint(layers),
        "layers": layers,
        "serving_layer": {"name": "ads", **layers["ads"]},
        "formats": [
            {
                "kind": "LayerManifest",
                "artifact_id": str(output_artifact.artifact_id),
                "content_sha256": output_artifact.content_sha256,
                "size_bytes": output_artifact.size_bytes,
                "media_type": output_artifact.media_type,
            }
        ],
        "operating_contract": operating_contract.model_dump(mode="json"),
        "records": {
            "read": result.records_read,
            "materialized": result.records_materialized,
            "quarantined": result.records_quarantined,
        },
    }


def jqdltb_product_release_fingerprint(values: dict[str, Any]) -> str:
    return canonical_json_fingerprint(
        {key: value for key, value in values.items() if key != "plan_sha256"}
    )


def _validate_decision_packet_binding(
    packet: JqdltbDecisionPacket,
    *,
    contract: JqdltbTransformationContract,
    operating: JqdltbReleaseOperatingContract,
) -> None:
    """Ensure release uses the exact business packet that produced its contracts."""

    if packet.status is not JqdltbDecisionPacketStatus.SUBMITTED:
        raise ValueError("JQDLTB release requires a submitted decision packet")
    identity = packet.identity
    expected_identity = (
        contract.source_resource_version_id,
        contract.archive_sha256,
        contract.bundle_sha256,
        contract.standard_version_ref,
        contract.standard_fingerprint,
        contract.diagnostic_sha256,
        contract.semantic_candidate_audit_sha256,
    )
    actual_identity = (
        identity.source_resource_version_id,
        identity.archive_sha256,
        identity.bundle_sha256,
        identity.standard_version_ref,
        identity.standard_fingerprint,
        identity.diagnostic_sha256,
        identity.semantic_candidate_audit_sha256,
    )
    if actual_identity != expected_identity:
        raise ValueError("JQDLTB decision packet identity differs from transformation contract")

    by_target = {item.target: item for item in packet.decisions}
    required_targets = (
        "canonical_key",
        "nonpositive_area_policy",
        "area_deviation_policy",
        "SJNF",
        "MSSM",
        "business_steward",
        "license_status",
        "slo_on_call",
        "environment_owner.staging",
        "environment_owner.production",
    )
    if any(target not in by_target for target in required_targets):
        raise ValueError("JQDLTB decision packet is missing a release decision")
    if any(
        by_target[target].status
        not in {JqdltbDecisionStatus.SUBMITTED, JqdltbDecisionStatus.ACCEPTED}
        for target in required_targets
    ):
        raise ValueError("JQDLTB release requires all packet decisions to be submitted")

    def selected(target: str) -> Any:
        value = by_target[target].selected_value
        if value is None:
            raise ValueError(f"JQDLTB decision packet has no selected value: {target}")
        return value

    if selected("canonical_key") != contract.canonical_key:
        raise ValueError("JQDLTB decision packet canonical key differs from contract")
    if selected("nonpositive_area_policy") != contract.nonpositive_area_policy.value:
        raise ValueError("JQDLTB decision packet non-positive area policy differs from contract")
    if selected("area_deviation_policy") != contract.area_deviation_policy.value:
        raise ValueError("JQDLTB decision packet area deviation policy differs from contract")

    for target in ("SJNF", "MSSM"):
        decision = by_target[target]
        derivation = next(
            item
            for item in contract.derivation_contracts
            if item.target_field == target
        )
        if (
            decision.source_fields != derivation.source_fields
            or decision.semantic_contract_ref != derivation.semantic_contract_ref
            or decision.semantic_contract_sha256 != derivation.semantic_contract_sha256
            or decision.method != derivation.method
        ):
            raise ValueError(f"JQDLTB decision packet semantic binding differs for {target}")

    nonpositive = by_target["nonpositive_area_policy"]
    if (
        nonpositive.selected_resource_version_id
        != contract.business_correction_resource_version_id
        or nonpositive.selected_artifact_sha256 != contract.business_correction_sha256
    ):
        raise ValueError("JQDLTB decision packet correction binding differs from contract")
    deviation = by_target["area_deviation_policy"]
    if (
        deviation.selected_rule_ref != contract.geometry_area_rule_ref
        or deviation.selected_rule_sha256 != contract.geometry_area_rule_sha256
    ):
        raise ValueError("JQDLTB decision packet geometry rule differs from contract")

    if selected("business_steward") != operating.business_steward_ref:
        raise ValueError("JQDLTB decision packet business steward differs from operating contract")
    if selected("license_status") != operating.license_id:
        raise ValueError("JQDLTB decision packet license differs from operating contract")
    if selected("slo_on_call") != operating.on_call_ref:
        raise ValueError("JQDLTB decision packet on-call differs from operating contract")
    environment_target = f"environment_owner.{operating.environment}"
    if (
        operating.environment in {"staging", "production"}
        and selected(environment_target) != operating.environment_owner_ref
    ):
        raise ValueError("JQDLTB decision packet environment owner differs from operating contract")


class JqdltbDataProductReleasePlan(_FrozenModel):
    schema_name: str = Field(default=JQDLTB_PRODUCT_RELEASE_SCHEMA, alias="schema")
    tenant_id: TenantId
    product: DataProductSpec
    data_product_version: DataProductVersionSpec
    run: PlatformRun
    transformation_contract: JqdltbTransformationContract
    transformation_result: JqdltbTransformationResult
    output_artifact: Artifact
    quality_result: QualityResult
    quality_evidence_artifact: Artifact
    lineage_event: LineageEvent
    operating_contract: JqdltbReleaseOperatingContract
    backup_restore_evidence_artifact: Artifact
    decision_packet: JqdltbDecisionPacket | None = None
    plan_sha256: Sha256

    @model_validator(mode="after")
    def _consistent_release(self) -> JqdltbDataProductReleasePlan:
        contract = self.transformation_contract
        result = self.transformation_result
        version = self.data_product_version
        output = self.output_artifact
        quality = self.quality_result
        evidence = self.quality_evidence_artifact
        lineage = self.lineage_event
        operating = self.operating_contract
        packet = self.decision_packet

        if self.schema_name != JQDLTB_PRODUCT_RELEASE_SCHEMA:
            raise ValueError("unsupported JQDLTB product release schema")
        if operating.environment in {"staging", "production"} and packet is None:
            raise ValueError("staging and production JQDLTB releases require a decision packet")
        if any(
            tenant != self.tenant_id
            for tenant in (
                self.product.tenant_id,
                version.tenant_id,
                self.run.tenant_id,
                contract.tenant_id,
                output.tenant_id,
                quality.tenant_id,
                evidence.tenant_id,
                lineage.tenant_id,
                operating.tenant_id,
                self.backup_restore_evidence_artifact.tenant_id,
            )
        ):
            raise ValueError("JQDLTB release objects must share one tenant")
        if self.run.status is not RunStatus.SUCCEEDED:
            raise ValueError("JQDLTB publication requires a succeeded PlatformRun")
        source = {item.binding_name: item for item in self.run.input_bindings}.get("source")
        if source is None or source.resource_version_id != contract.source_resource_version_id:
            raise ValueError("JQDLTB release Run must bind the approved source version")
        if (
            contract.mode is not JqdltbTransformationMode.EXECUTE
            or contract.approval_case is None
            or contract.approval_case.status is not ApprovalCaseStatus.APPROVED
        ):
            raise ValueError("JQDLTB release requires an approved executable contract")
        if packet is not None:
            _validate_decision_packet_binding(
                packet,
                contract=contract,
                operating=operating,
            )
        if (
            result.status != "completed"
            or result.run_id != self.run.run_id
            or result.source_resource_version_id != contract.source_resource_version_id
            or result.quality_verdict != "passed"
            or result.output_resource_version_id is None
            or result.output_artifact_id is None
            or result.quality_result_id is None
            or result.lineage_event_id is None
            or result.data_product_version_created
        ):
            raise ValueError("JQDLTB transformation result is not a publishable candidate")
        if (
            output.artifact_id != result.output_artifact_id
            or output.artifact_role is not ArtifactRole.OUTPUT
            or output.run_id != self.run.run_id
            or output.resource_version_id != result.output_resource_version_id
        ):
            raise ValueError("JQDLTB output Artifact does not match the candidate")
        layers = output.manifest.get("layers")
        if not isinstance(layers, dict) or set(layers) != _REQUIRED_LAYERS:
            raise ValueError("JQDLTB output Artifact requires the complete layer manifest")
        layer_sha = canonical_json_fingerprint(layers)
        if (
            output.manifest.get("bundle_sha256") != layer_sha
            or output.content_sha256 != layer_sha
            or layers["raw"].get("records") != result.records_read
            or layers["ads"].get("records") != result.records_materialized
            or layers["quarantine"].get("records") != result.records_quarantined
        ):
            raise ValueError("JQDLTB layer manifest does not match transformation evidence")
        if (
            quality.quality_result_id != result.quality_result_id
            or quality.run_id != self.run.run_id
            or quality.resource_version_id != result.output_resource_version_id
            or quality.verdict is not QualityVerdict.PASSED
            or evidence.artifact_id != quality.evidence_artifact_id
            or evidence.artifact_role is not ArtifactRole.EVIDENCE
            or evidence.run_id != self.run.run_id
            or evidence.resource_version_id != result.output_resource_version_id
        ):
            raise ValueError("JQDLTB quality evidence does not match the candidate")
        if (
            lineage.lineage_event_id != result.lineage_event_id
            or lineage.run_id != self.run.run_id
            or lineage.source_resource_version_id != contract.source_resource_version_id
            or lineage.target_resource_version_id != result.output_resource_version_id
            or lineage.artifact_id != output.artifact_id
        ):
            raise ValueError("JQDLTB lineage does not match source, Run, and ADS candidate")
        backup = self.backup_restore_evidence_artifact
        if (
            backup.artifact_id != operating.backup_restore_evidence_artifact_id
            or backup.artifact_role is not ArtifactRole.EVIDENCE
        ):
            raise ValueError("JQDLTB operating contract lacks exact backup/restore evidence")
        if (
            self.product.product_urn != version.product_urn
            or self.product.owner_ref != operating.business_steward_ref
            or self.product.governance_ref.get("license_id") != operating.license_id
        ):
            raise ValueError("JQDLTB product ownership or license is not release-bound")
        expected_case_ref = _release_approval_case_ref(
            self.tenant_id, version.data_product_version_id
        )
        expected_distribution = _layered_distribution(
            run=self.run,
            result=result,
            output_artifact=output,
            lineage_event=lineage,
            operating_contract=operating,
            release_approval_case_ref=expected_case_ref,
            decision_packet_sha256=packet.packet_sha256 if packet is not None else None,
        )
        if (
            version.source_resource_version_id != contract.source_resource_version_id
            or version.output_resource_version_id != result.output_resource_version_id
            or version.standard_version_ref != contract.standard_version_ref
            or version.quality_evidence_artifact_id != evidence.artifact_id
            or version.mapping_contract
            != _mapping_binding(
                contract,
                packet.packet_sha256 if packet is not None else None,
            )
            or version.quality_contract != _quality_binding(quality)
            or version.distribution_manifest != expected_distribution
        ):
            raise ValueError("DataProductVersion does not bind the exact JQDLTB evidence graph")
        if not version.published_by.startswith("workload:"):
            raise ValueError("JQDLTB publication must use workload identity")
        if version.published_at < max(
            contract.created_at,
            quality.evaluated_at,
            evidence.created_at,
            output.created_at,
            lineage.occurred_at,
            backup.created_at,
        ):
            raise ValueError("JQDLTB publication time predates required evidence")
        expected_plan = jqdltb_product_release_fingerprint(
            self.model_dump(mode="json", by_alias=True)
        )
        if self.plan_sha256 != expected_plan:
            raise ValueError("plan_sha256 does not match JQDLTB release evidence")
        return self

    @property
    def release_approval_case_ref(self) -> str:
        return str(self.data_product_version.distribution_manifest["release_approval_case_ref"])

    def approval_context(self) -> dict[str, Any]:
        version = self.data_product_version
        contract = self.transformation_contract
        return {
            "schema": JQDLTB_PRODUCT_RELEASE_SCHEMA,
            "plan_sha256": self.plan_sha256,
            "product_urn": version.product_urn,
            "data_product_version_id": str(version.data_product_version_id),
            "version_key": version.version_key,
            "manifest_sha256": version.manifest_sha256,
            "run_id": str(self.run.run_id),
            "source_resource_version_id": str(contract.source_resource_version_id),
            "output_resource_version_id": str(version.output_resource_version_id),
            "transformation_approval_case_ref": (
                contract.approval_case.approval_case_ref
                if contract.approval_case is not None
                else None
            ),
            "quality_result_id": str(self.quality_result.quality_result_id),
            "lineage_event_id": str(self.lineage_event.lineage_event_id),
            "operating_contract": self.operating_contract.model_dump(mode="json"),
            "decision_packet_sha256": (
                self.decision_packet.packet_sha256
                if self.decision_packet is not None
                else None
            ),
        }

    def registry_binding(self) -> dict[str, Any]:
        """Return the immutable row written beside DataProductVersion."""

        contract = self.transformation_contract
        assert contract.approval_case is not None
        return {
            "tenant_id": str(self.tenant_id),
            "data_product_version_id": str(self.data_product_version.data_product_version_id),
            "product_urn": self.product.product_urn,
            "run_id": str(self.run.run_id),
            "source_resource_version_id": str(self.data_product_version.source_resource_version_id),
            "output_resource_version_id": str(self.data_product_version.output_resource_version_id),
            "output_artifact_id": str(self.output_artifact.artifact_id),
            "quality_result_id": str(self.quality_result.quality_result_id),
            "quality_evidence_artifact_id": str(self.quality_evidence_artifact.artifact_id),
            "lineage_event_id": str(self.lineage_event.lineage_event_id),
            "transformation_approval_case_ref": (contract.approval_case.approval_case_ref),
            "release_approval_case_ref": self.release_approval_case_ref,
            "release_plan_sha256": self.plan_sha256,
            "decision_packet_sha256": (
                self.decision_packet.packet_sha256
                if self.decision_packet is not None
                else None
            ),
            "operating_contract": self.operating_contract.model_dump(mode="json"),
            "bound_by": self.data_product_version.published_by,
            "bound_at": self.data_product_version.published_at.isoformat(),
        }


def build_jqdltb_data_product_release_plan(
    *,
    product: DataProductSpec,
    version_key: str,
    predecessor_version_id: UUID | None,
    run: PlatformRun,
    transformation_contract: JqdltbTransformationContract,
    transformation_result: JqdltbTransformationResult,
    output_artifact: Artifact,
    quality_result: QualityResult,
    quality_evidence_artifact: Artifact,
    lineage_event: LineageEvent,
    operating_contract: JqdltbReleaseOperatingContract,
    backup_restore_evidence_artifact: Artifact,
    decision_packet: JqdltbDecisionPacket | None = None,
    published_by: str,
    published_at: datetime,
) -> JqdltbDataProductReleasePlan:
    if transformation_result.output_resource_version_id is None:
        raise ValueError("JQDLTB candidate has no output ResourceVersion")
    version_id = uuid5(
        NAMESPACE_URL,
        f"{product.product_urn}:{version_key}:{transformation_result.output_resource_version_id}",
    )
    release_case_ref = _release_approval_case_ref(product.tenant_id, version_id)
    version_values: dict[str, Any] = {
        "tenant_id": product.tenant_id,
        "data_product_version_id": version_id,
        "product_urn": product.product_urn,
        "version_key": version_key,
        "predecessor_version_id": predecessor_version_id,
        "source_resource_version_id": transformation_contract.source_resource_version_id,
        "output_resource_version_id": transformation_result.output_resource_version_id,
        "standard_version_ref": transformation_contract.standard_version_ref,
        "mapping_contract": _mapping_binding(
            transformation_contract,
            decision_packet.packet_sha256 if decision_packet is not None else None,
        ),
        "quality_contract": _quality_binding(quality_result),
        "quality_evidence_artifact_id": quality_evidence_artifact.artifact_id,
        "distribution_manifest": _layered_distribution(
            run=run,
            result=transformation_result,
            output_artifact=output_artifact,
            lineage_event=lineage_event,
            operating_contract=operating_contract,
            release_approval_case_ref=release_case_ref,
            decision_packet_sha256=(
                decision_packet.packet_sha256 if decision_packet is not None else None
            ),
        ),
        "published_by": published_by,
        "published_at": _aware_utc(published_at),
    }
    version_values["manifest_sha256"] = data_product_manifest_fingerprint(version_values)
    version = DataProductVersionSpec.model_validate(version_values)
    plan_values = {
        "schema": JQDLTB_PRODUCT_RELEASE_SCHEMA,
        "tenant_id": product.tenant_id,
        "product": product,
        "data_product_version": version,
        "run": run,
        "transformation_contract": transformation_contract,
        "transformation_result": transformation_result,
        "output_artifact": output_artifact,
        "quality_result": quality_result,
        "quality_evidence_artifact": quality_evidence_artifact,
        "lineage_event": lineage_event,
        "operating_contract": operating_contract,
        "backup_restore_evidence_artifact": backup_restore_evidence_artifact,
        "decision_packet": decision_packet,
    }
    fingerprint_payload = {
        key: value.model_dump(mode="json", by_alias=True) if isinstance(value, BaseModel) else value
        for key, value in plan_values.items()
    }
    return JqdltbDataProductReleasePlan.model_validate(
        plan_values | {"plan_sha256": jqdltb_product_release_fingerprint(fingerprint_payload)}
    )


def build_jqdltb_data_product_release_approval_case(
    plan: JqdltbDataProductReleasePlan,
    *,
    requester_subject: str,
    request_reason: str,
    requested_at: datetime,
    expires_at: datetime,
) -> ApprovalCase:
    requested_at = _aware_utc(requested_at)
    if requested_at >= plan.data_product_version.published_at:
        raise ValueError("release approval must be requested before publication time")
    return ApprovalCase(
        tenant_id=plan.tenant_id,
        approval_case_ref=plan.release_approval_case_ref,
        target_resource_urn=plan.product.product_urn,
        target_fingerprint=plan.plan_sha256,
        action=JQDLTB_PRODUCT_RELEASE_ACTION,
        requester_subject=requester_subject,
        request_reason=request_reason,
        request_context=plan.approval_context(),
        requested_at=requested_at,
        expires_at=expires_at,
    )


class _ApprovalWriteResult(Protocol):
    approval_case: ApprovalCase
    created: bool


class _ApprovalAuthority(Protocol):
    def create(self, case: ApprovalCase, *, owner_ref: str) -> _ApprovalWriteResult: ...

    def get(self, tenant_id: str, approval_case_ref: str) -> ApprovalCase: ...


@dataclass(frozen=True)
class JqdltbReleaseRequestResult:
    plan: JqdltbDataProductReleasePlan
    approval_case: ApprovalCase
    created: bool


class JqdltbDataProductReleaseService:
    """Request release approval and publish through the existing registry."""

    def __init__(
        self,
        registry: DataProductRegistry,
        approval_authority: _ApprovalAuthority,
    ) -> None:
        self._registry = registry
        self._approval_authority = approval_authority

    def request_release(
        self,
        plan: JqdltbDataProductReleasePlan,
        *,
        requester_subject: str,
        request_reason: str,
        owner_ref: str,
        requested_at: datetime,
        expires_at: datetime,
    ) -> JqdltbReleaseRequestResult:
        case = build_jqdltb_data_product_release_approval_case(
            plan,
            requester_subject=requester_subject,
            request_reason=request_reason,
            requested_at=requested_at,
            expires_at=expires_at,
        )
        written = self._approval_authority.create(case, owner_ref=owner_ref)
        return JqdltbReleaseRequestResult(plan, written.approval_case, written.created)

    def publish(
        self,
        plan: JqdltbDataProductReleasePlan,
        *,
        idempotency_key: str,
        reason: str,
        now: datetime,
    ) -> dict[str, Any]:
        now = _aware_utc(now)
        case = self._approval_authority.get(plan.tenant_id, plan.release_approval_case_ref)
        if (
            case.status is not ApprovalCaseStatus.APPROVED
            or case.target_resource_urn != plan.product.product_urn
            or case.target_fingerprint != plan.plan_sha256
            or case.action != JQDLTB_PRODUCT_RELEASE_ACTION
            or case.request_context != plan.approval_context()
            or case.decided_at is None
            or case.decided_at > plan.data_product_version.published_at
            or plan.data_product_version.published_at > now
            or now >= case.expires_at
        ):
            raise ValueError("authoritative JQDLTB release ApprovalCase is not executable")
        return self._registry.publish(
            plan.product,
            plan.data_product_version,
            idempotency_key=idempotency_key,
            reason=reason,
            jqdltb_release_plan=plan,
            jqdltb_release_approval_case_ref=plan.release_approval_case_ref,
        )


__all__ = [
    "JQDLTB_PRODUCT_RELEASE_ACTION",
    "JQDLTB_PRODUCT_RELEASE_SCHEMA",
    "JqdltbDataProductReleasePlan",
    "JqdltbDataProductReleaseService",
    "JqdltbReleaseOperatingContract",
    "JqdltbReleaseRequestResult",
    "build_jqdltb_data_product_release_approval_case",
    "build_jqdltb_data_product_release_plan",
    "jqdltb_product_release_fingerprint",
]
