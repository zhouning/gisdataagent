import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest
from pydantic import ValidationError

from data_agent.api import platform_gateway_routes as routes
from data_agent.approval_case_authority import (
    ApprovalCaseAuthority,
    ApprovalCaseConflictError,
    ApprovalCasePage,
    ApprovalCaseValidationError,
    ApprovalCaseWriteResult,
)
from data_agent.architecture_change_approval import (
    ARCHITECTURE_CHANGE_REVIEW_ACTION,
    ArchitectureChangeApprovalError,
    ArchitectureChangeApprovalRequestResult,
    ArchitectureChangeReview,
    architecture_change_review_fingerprint,
    build_architecture_change_approval_case,
)
from data_agent.architecture_change_assessment import (
    SUCCESSOR_BLOCKERS,
    AssessedArchitectureChangeReview,
    assessed_architecture_change_fingerprint,
    build_assessed_architecture_change_approval_case,
)
from data_agent.architecture_successor_adoption import (
    ArchitectureSuccessorAdoptionRequestResult,
    build_architecture_successor_adoption_case,
    build_architecture_successor_plan,
)
from data_agent.architecture_successor_data_product_release import (
    ArchitectureSuccessorReleaseRequestResult,
    build_architecture_successor_data_product_release_plan,
    build_architecture_successor_release_approval_case,
)
from data_agent.capability_registry import (
    CAPABILITY_FINGERPRINT_HEADER,
    DATAOPS_MANUAL_RUN_SUBMIT,
    DATAOPS_RUN_CANCEL,
)
from data_agent.data_architecture_ledger import (
    ResourceVersionArchitecture,
    ResourceVersionArchitectureReconciliation,
)
from data_agent.data_product_blueprint import DataProductBlueprintReleaseBinding
from data_agent.data_product_registry import (
    DataProductConflictError,
    DataProductSpec,
    DataProductVersionSpec,
    data_product_manifest_fingerprint,
)
from data_agent.dataops_cancel import (
    DataOpsCancelRequest,
    DataOpsCancelResponse,
    DataOpsCancelSpec,
    DataOpsCancelWriteResult,
    build_dataops_cancel_submission,
)
from data_agent.dataops_manual import (
    DataOpsManualTriggerSpec,
    ManualDataOpsRunRequest,
    ManualTriggerWriteResult,
    build_manual_dataops_submission,
)
from data_agent.platform_contracts import (
    ApprovalAssignmentActorAccess,
    ApprovalCase,
    ApprovalCaseAssignment,
    ApprovalCaseAssignmentEvent,
    ApprovalCaseAssignmentOperation,
    ApprovalCaseEvent,
    ApprovalCaseNotification,
    ApprovalCaseNotificationRecoveryEvent,
    ApprovalCaseStatus,
    ApprovalPrincipal,
    ApprovalTeamMembership,
    Artifact,
    DataIncident,
    IncidentStatus,
    LineageEvent,
    PlatformCommand,
    PlatformRun,
    QualityResult,
    Resource,
    ResourceVersion,
    RunStatus,
    SubjectContext,
    canonical_json_fingerprint,
    data_incident_fingerprint,
    platform_definition_fingerprint,
    quality_result_fingerprint,
)
from data_agent.platform_gateway import (
    COMMAND_OUTBOX_MIGRATION,
    GATEWAY_ROLE_MIGRATION,
    GIS_SERVICE_ENDPOINT_WARMUP_COMMAND_MIGRATION,
    MASTER_METADATA_PROJECTION_MIGRATION,
    MASTER_RESOURCE_PROJECTION_MIGRATION,
    CallbackWriteResult,
    DefinitionRegistration,
    GatewayConfigurationError,
    GatewayConflictError,
    GatewayForbiddenError,
    GatewayNotFoundError,
    GatewayResourceVersionPage,
    GatewayTraversalLimitError,
    GatewayValidationError,
    GatewayWriteResult,
    PlatformGateway,
    build_gateway_report,
)
from data_agent.platform_lineage import (
    ImpactChangeType,
    ImpactDisposition,
    ImpactedDataProduct,
    ImpactReviewReason,
    LineageGraph,
    LineageGraphEdge,
    LineageGraphNode,
    LineageImpactAssessment,
    lineage_impact_fingerprint,
)
from data_agent.postgis_schema_evidence import (
    PostgisSchemaColumn,
    PostgisSchemaCompatibilityAssessment,
    PostgisSchemaCompatibilityChange,
    PostgisSchemaSnapshot,
    SchemaCompatibilityChangeKind,
    SchemaCompatibilityVerdict,
    postgis_schema_compatibility_fingerprint,
    postgis_schema_snapshot_fingerprint,
)
from data_agent.slo_authority import (
    SLOAuthorityError,
    SLOConfigurationError,
    SLOConflictError,
    SLODefinitionActivation,
    SLODefinitionEvent,
    SLODefinitionVersion,
    SLODefinitionVersionPage,
    SLOForbiddenError,
    SLONotFoundError,
    SLOValidationError,
)
from data_agent.slo_incident import (
    SLOAlertReconciliationResult,
    SLOIncidentValidationError,
)
from data_agent.test_architecture_successor_adoption import _facts as _successor_facts
from data_agent.test_architecture_successor_data_product_release import (
    _release_facts,
)

TENANT = "tenant-a"
ACTOR = "human:operator-1"
DEFINITION_ID = UUID("00000000-0000-4000-8000-000000000010")
RUN_ID = UUID("00000000-0000-4000-8000-000000000020")
SOURCE_ID = UUID("00000000-0000-4000-8000-000000000030")
TARGET_ID = UUID("00000000-0000-4000-8000-000000000031")
LINEAGE_ID = UUID("00000000-0000-4000-8000-000000000032")
PLAN_ID = UUID("00000000-0000-4000-8000-000000000040")
APPROVAL_CASE_REF = "gda://tenant-a/approval_case/schema-drift-1"
SLO_ID = "approval-notification-delivery"
SLO_REF = f"gda://{TENANT}/slo_definition/{SLO_ID}"
SLO_VERSION_REF = f"{SLO_REF}.v1"
NOW = datetime(2026, 7, 24, 12, 0, tzinfo=UTC)


def _blueprint_release_publication_payload(
    *, published_by: str = "workload:data-product-controller"
):
    product = DataProductSpec(
        tenant_id=TENANT,
        product_urn=f"gda://{TENANT}/data_product/parcels",
        product_slug="parcels",
        title="Parcels",
        description="Governed parcel product",
        domain="land",
        owner_ref="team:geo-platform",
        governance_ref={
            "classification": "internal",
            "visibility": "private",
            "license_id": "internal",
            "attribution": "geo-platform",
        },
        created_at=NOW,
    )
    binding = DataProductBlueprintReleaseBinding(
        tenant_id=TENANT,
        product_urn=product.product_urn,
        version_key="v1.0.0",
        definition_urn=f"gda://{TENANT}/definition/parcels-build",
        definition_version_id=UUID("00000000-0000-4000-8000-000000000050"),
        blueprint_sha256="a" * 64,
        definition_sha256="b" * 64,
        change_set_sha256="c" * 64,
        test_report_sha256="d" * 64,
        approval_case_ref=f"gda://{TENANT}/approval_case/parcels-v1",
    )
    version_payload = {
        "tenant_id": TENANT,
        "data_product_version_id": UUID("00000000-0000-4000-8000-000000000051"),
        "product_urn": product.product_urn,
        "version_key": "v1.0.0",
        "predecessor_version_id": None,
        "source_resource_version_id": UUID("00000000-0000-4000-8000-000000000052"),
        "output_resource_version_id": UUID("00000000-0000-4000-8000-000000000053"),
        "standard_version_ref": "standard:parcel:v1",
        "mapping_contract": {"geometry": "polygon"},
        "quality_contract": {"verdict": "passed", "checks": []},
        "quality_evidence_artifact_id": UUID("00000000-0000-4000-8000-000000000054"),
        "distribution_manifest": {
            "formats": [{"kind": "GeoParquet", "uri": "s3://geo/parcels/v1"}],
            "blueprint_release": binding.model_dump(mode="json", by_alias=True),
        },
        "published_by": published_by,
        "published_at": NOW,
    }
    version_payload["manifest_sha256"] = data_product_manifest_fingerprint(version_payload)
    return product, DataProductVersionSpec.model_validate(version_payload), binding


def _request(*, body=None, path=None, headers=None, query=None):
    request = MagicMock()
    request.json = MagicMock()

    async def read_json():
        return body or {}

    request.json.side_effect = read_json
    request.path_params = path or {}
    request.headers = headers or {"x-request-id": "request-1"}
    request.query_params = query or {}
    return request


def _user(
    role="platform_operator",
    tenant_id=TENANT,
    *,
    subject_type=None,
    identifier="operator-1",
):
    metadata = {"role": role, "tenant_id": tenant_id}
    if subject_type is not None:
        metadata["subject_type"] = subject_type
    return SimpleNamespace(
        identifier=identifier,
        metadata=metadata,
    )


def _resource(**overrides):
    values = {
        "tenant_id": TENANT,
        "resource_urn": "gda://tenant-a/dataset/source-parcels",
        "resource_kind": "dataset",
        "authority_system": "iceberg",
        "authority_locator": "geo.source_parcels",
        "owner_ref": "team:data-platform",
    }
    values.update(overrides)
    return Resource(**values)


def _version(**overrides):
    values = {
        "tenant_id": TENANT,
        "resource_urn": "gda://tenant-a/dataset/source-parcels",
        "resource_version_id": SOURCE_ID,
        "version_key": "snapshot-1",
        "content_sha256": "a" * 64,
        "authority_version_ref": {"snapshot": 1},
        "created_by": ACTOR,
        "created_at": NOW,
    }
    values.update(overrides)
    return ResourceVersion(**values)


def _architecture(**overrides):
    values = {
        "tenant_id": TENANT,
        "resource_version_id": SOURCE_ID,
        "architecture_ready": False,
        "missing_components": (
            "schema_version",
            "data_contract_version",
            "physical_location",
            "architecture_binding",
        ),
    }
    values.update(overrides)
    return ResourceVersionArchitecture(**values)


def _lineage_graph(**overrides):
    root = _version()
    values = {
        "tenant_id": TENANT,
        "root_resource_version_id": SOURCE_ID,
        "direction": "downstream",
        "requested_max_depth": 6,
        "requested_max_edges": 500,
        "reached_depth": 0,
        "complete": True,
        "nodes": (
            LineageGraphNode(resource_version=root, min_depth=0, is_root=True),
        ),
        "edges": (),
        "node_count": 1,
        "edge_count": 0,
    }
    values.update(overrides)
    return LineageGraph(**values)


def _lineage_row(
    event: LineageEvent,
    source: ResourceVersion,
    target: ResourceVersion,
    *,
    from_version_id: UUID,
    to_version_id: UUID,
    depth: int,
) -> dict:
    row = {
        **event.model_dump(mode="python"),
        "from_version_id": from_version_id,
        "to_version_id": to_version_id,
        "depth": depth,
    }
    for prefix, version in (("source", source), ("target", target)):
        for field, value in version.model_dump(mode="python").items():
            if field != "resource_version_id":
                row[f"{prefix}_{field}"] = value
    return row


def _run():
    return PlatformRun(
        tenant_id=TENANT,
        run_id=RUN_ID,
        definition_version_id=DEFINITION_ID,
        orchestration_class="dataops",
        subject_context=SubjectContext(
            tenant_id=TENANT,
            subject_id="operator-1",
            subject_type="human",
            roles=("platform_operator",),
            purpose="publish parcels",
        ),
        input_bindings=(
            {
                "binding_name": "source",
                "resource_version_id": SOURCE_ID,
                "semantic_type": "gis.land_use.parcels",
            },
        ),
        idempotency_key="publish:parcels:1",
        submitted_at=NOW,
    )


def _command():
    return PlatformCommand(
        tenant_id=TENANT,
        command_id=UUID("00000000-0000-4000-8000-000000000070"),
        run_id=RUN_ID,
        command_type="dolphinscheduler.reconcile",
        execution_plan_artifact_id=DEFINITION_ID,
        trigger_observation_id=UUID("00000000-0000-4000-8000-000000000060"),
        dedupe_key="dolphinscheduler.reconcile:callback-1",
        actor_subject="workload:dataops-adapter",
        available_at=NOW,
        created_at=NOW,
    )


def _incident(**overrides):
    incident_id = UUID("00000000-0000-4000-8000-000000000080")
    observation_id = UUID("00000000-0000-4000-8000-000000000081")
    details = {"provider_state": "FAILURE", "workflow_instance_id": 7}
    values = {
        "tenant_id": TENANT,
        "incident_id": incident_id,
        "run_id": RUN_ID,
        "dedupe_key": f"cancel-terminal:{observation_id}",
        "incident_type": "provider_cancel_terminal_mismatch",
        "severity": "high",
        "summary": "provider cancellation did not converge",
        "trigger_observation_id": observation_id,
        "details": details,
        "detected_by": "workload:dataops-adapter",
        "status": "open",
        "state_version": 0,
        "opened_at": NOW,
        "updated_at": NOW,
    }
    values["incident_sha256"] = data_incident_fingerprint(
        **{
            key: values[key]
            for key in (
                "tenant_id",
                "run_id",
                "dedupe_key",
                "incident_type",
                "severity",
                "summary",
                "trigger_observation_id",
                "details",
                "detected_by",
                "opened_at",
            )
        }
    )
    values.update(overrides)
    return DataIncident(**values)


def _approval_case(**overrides):
    values = {
        "tenant_id": TENANT,
        "approval_case_ref": APPROVAL_CASE_REF,
        "target_resource_urn": "gda://tenant-a/schema_drift/" + "a" * 64,
        "target_fingerprint": "a" * 64,
        "action": "source_schema_drift.reconcile",
        "requester_subject": ACTOR,
        "request_reason": "review breaking source schema drift",
        "request_context": {"compatibility": "breaking"},
        "requested_at": NOW,
        "expires_at": NOW + timedelta(hours=4),
    }
    values.update(overrides)
    return ApprovalCase(**values)


def _slo_definition(**overrides):
    values = {
        "tenant_id": TENANT,
        "slo_definition_ref": SLO_REF,
        "slo_version_ref": SLO_VERSION_REF,
        "version": 1,
        "service_resource_urn": f"gda://{TENANT}/service/approval-notification",
        "indicator": {
            "metric_name": "gda_approval_notification_operations_total",
            "good_outcomes": ("delivered",),
            "bad_outcomes": ("dead_lettered", "retrying"),
            "match_labels": {},
        },
        "objective_basis_points": 9900,
        "objective_window_seconds": 30 * 24 * 60 * 60,
        "owner_subject": "team:data-platform",
        "oncall_ref": "oncall:approval-primary",
        "burn_rate_windows": (
            {
                "name": "fast",
                "short_window_seconds": 300,
                "long_window_seconds": 3600,
                "burn_rate_milli": 14400,
                "minimum_events": 20,
                "for_seconds": 120,
                "severity": "critical",
            },
        ),
        "created_by": ACTOR,
        "creation_reason": "stage a candidate for service-owner review",
        "created_at": NOW,
        "definition_fingerprint": "a" * 64,
    }
    values.update(overrides)
    return SLODefinitionVersion(**values)


def _slo_activation(**overrides):
    values = {
        "tenant_id": TENANT,
        "slo_definition_ref": SLO_REF,
        "active_version_ref": SLO_VERSION_REF,
        "active_fingerprint": "a" * 64,
        "approval_case_ref": f"gda://{TENANT}/approval_case/slo-v1-activation",
        "activation_version": 1,
        "activated_by": "human:platform-admin",
        "activation_reason": "activate the approved SLO",
        "activated_at": NOW,
    }
    values.update(overrides)
    return SLODefinitionActivation(**values)


def _slo_stage_body(**overrides):
    definition = _slo_definition()
    values = {
        "version": definition.version,
        "service_resource_urn": definition.service_resource_urn,
        "indicator": definition.indicator.model_dump(mode="json"),
        "objective_basis_points": definition.objective_basis_points,
        "objective_window_seconds": definition.objective_window_seconds,
        "owner_subject": definition.owner_subject,
        "oncall_ref": definition.oncall_ref,
        "burn_rate_windows": [
            item.model_dump(mode="json") for item in definition.burn_rate_windows
        ],
        "creation_reason": definition.creation_reason,
    }
    values.update(overrides)
    return values


def _slo_webhook_body(**overrides):
    values = {
        "version": "4",
        "groupKey": "{}:{alertname=\"GDASLOErrorBudgetBurn\"}",
        "truncatedAlerts": 0,
        "status": "firing",
        "receiver": "gda-slo-incident",
        "groupLabels": {"alertname": "GDASLOErrorBudgetBurn"},
        "commonLabels": {},
        "commonAnnotations": {},
        "externalURL": "https://alertmanager.example.test",
        "alerts": [
            {
                "status": "firing",
                "labels": {
                    "alertname": "GDASLOErrorBudgetBurn",
                    "slo_id": SLO_ID,
                    "slo_version": "1",
                    "slo_fingerprint": "a" * 64,
                    "service": "approval-notification",
                    "owner": "team:data-platform",
                    "oncall": "oncall:approval-primary",
                    "burn_window": "fast",
                    "severity": "critical",
                },
                "annotations": {
                    "approval_case_ref": (
                        f"gda://{TENANT}/approval_case/slo-v1-activation"
                    )
                },
                "startsAt": NOW.isoformat(),
                "endsAt": (NOW + timedelta(hours=1)).isoformat(),
                "generatorURL": "https://prometheus.example.test/graph",
                "fingerprint": "0123456789abcdef",
            }
        ],
    }
    values.update(overrides)
    return values


def _architecture_change_review_result(*, created=True):
    review_values = {
        "tenant_id": TENANT,
        "target_resource_urn": _version().resource_urn,
        "resource_version_id": SOURCE_ID,
        "observation_id": LINEAGE_ID,
        "observation_sha256": "b" * 64,
        "binding_sha256": "c" * 64,
        "reconciliation_status": "schema_drift",
        "candidate_schema_sha256": "d" * 64,
        "candidate_location_sha256": "e" * 64,
        "required_actions": ("review_schema_drift",),
    }
    review = ArchitectureChangeReview(
        review_sha256=architecture_change_review_fingerprint(**review_values),
        **review_values,
    )
    reconciliation = ResourceVersionArchitectureReconciliation(
        tenant_id=TENANT,
        resource_version_id=SOURCE_ID,
        status="schema_drift",
        architecture=_architecture(),
        schema_matches=False,
        location_matches=True,
        evaluated_at=NOW,
        required_actions=("review_schema_drift",),
    )
    approval_case = build_architecture_change_approval_case(
        review,
        requester_subject=ACTOR,
        request_reason="review provider schema drift",
        requested_at=NOW,
        expires_at=NOW + timedelta(hours=48),
    )
    return ArchitectureChangeApprovalRequestResult(
        reconciliation=reconciliation,
        review=review,
        approval_case=approval_case,
        created=created,
    )


def _schema_snapshot(*, include_zoning_code=False):
    columns = [
        PostgisSchemaColumn(
            ordinal=1,
            name="parcel_id",
            data_type="uuid",
            not_null=True,
        )
    ]
    if include_zoning_code:
        columns.append(
            PostgisSchemaColumn(
                ordinal=2,
                name="zoning_code",
                data_type="text",
                not_null=False,
            )
        )
    values = {
        "provider_namespace": "provider_geo",
        "provider_object_id": "parcels",
        "relation_kind": "r",
        "columns": tuple(columns),
        "constraints": (),
        "indexes": (),
    }
    return PostgisSchemaSnapshot(
        snapshot_sha256=postgis_schema_snapshot_fingerprint(**values),
        **values,
    )


def _architecture_change_assessment_result(*, created=True):
    base_review = _architecture_change_review_result(created=created).review
    compatibility_change = PostgisSchemaCompatibilityChange(
        component="column",
        subject="zoning_code",
        change_kind=SchemaCompatibilityChangeKind.COLUMN_ADDED,
        verdict=SchemaCompatibilityVerdict.BACKWARD_COMPATIBLE,
        current_fingerprint="d" * 64,
    )
    compatibility_values = {
        "tenant_id": TENANT,
        "resource_version_id": SOURCE_ID,
        "baseline_observation_id": UUID("00000000-0000-4000-8000-000000000033"),
        "candidate_observation_id": LINEAGE_ID,
        "baseline_evidence_artifact_id": UUID(
            "00000000-0000-4000-8000-000000000034"
        ),
        "candidate_evidence_artifact_id": UUID(
            "00000000-0000-4000-8000-000000000035"
        ),
        "baseline_snapshot_sha256": "e" * 64,
        "candidate_snapshot_sha256": "f" * 64,
        "baseline_evidence_sha256": "1" * 64,
        "candidate_evidence_sha256": "2" * 64,
        "changes": (compatibility_change,),
        "verdict": SchemaCompatibilityVerdict.BACKWARD_COMPATIBLE,
    }
    compatibility = PostgisSchemaCompatibilityAssessment(
        breaking_change_count=0,
        indeterminate_change_count=0,
        assessment_sha256=postgis_schema_compatibility_fingerprint(
            **compatibility_values
        ),
        **compatibility_values,
    )
    impact_values = {
        "tenant_id": TENANT,
        "root_resource_version": _version(),
        "change_type": ImpactChangeType.SCHEMA,
        "lineage": _lineage_graph(),
        "impacted_data_products": (),
        "quality_signals": (),
        "disposition": ImpactDisposition.REVIEW_REQUIRED,
        "review_reasons": (ImpactReviewReason.CHANGE_TYPE_REQUIRES_REVIEW,),
    }
    impact = LineageImpactAssessment(
        impacted_resource_version_count=1,
        impacted_data_product_count=0,
        quality_signal_count=0,
        assessment_sha256=lineage_impact_fingerprint(**impact_values),
        **impact_values,
    )
    review_values = {
        "tenant_id": TENANT,
        "target_resource_urn": base_review.target_resource_urn,
        "resource_version_id": SOURCE_ID,
        "observation_id": LINEAGE_ID,
        "observation_sha256": base_review.observation_sha256,
        "binding_sha256": base_review.binding_sha256,
        "base_review_sha256": base_review.review_sha256,
        "compatibility_assessment_sha256": compatibility.assessment_sha256,
        "compatibility_verdict": compatibility.verdict,
        "baseline_schema_artifact_id": compatibility.baseline_evidence_artifact_id,
        "candidate_schema_artifact_id": compatibility.candidate_evidence_artifact_id,
        "baseline_schema_evidence_sha256": compatibility.baseline_evidence_sha256,
        "candidate_schema_evidence_sha256": compatibility.candidate_evidence_sha256,
        "breaking_change_count": compatibility.breaking_change_count,
        "indeterminate_change_count": compatibility.indeterminate_change_count,
        "lineage_impact_sha256": impact.assessment_sha256,
        "impact_disposition": impact.disposition,
        "lineage_edge_count": impact.lineage.edge_count,
        "impacted_resource_version_count": impact.impacted_resource_version_count,
        "impacted_data_product_count": impact.impacted_data_product_count,
        "successor_blockers": SUCCESSOR_BLOCKERS,
    }
    review = AssessedArchitectureChangeReview(
        assessment_sha256=assessed_architecture_change_fingerprint(**review_values),
        **review_values,
    )
    approval_case = build_assessed_architecture_change_approval_case(
        review,
        requester_subject=ACTOR,
        request_reason="review compatibility and downstream impact",
        requested_at=NOW,
        expires_at=NOW + timedelta(hours=48),
    )
    return SimpleNamespace(
        base_review=base_review,
        compatibility=compatibility,
        impact=impact,
        review=review,
        approval_case=approval_case,
        created=created,
    )


def _architecture_successor_adoption_result(*, created=True):
    facts = _successor_facts()
    plan = build_architecture_successor_plan(**facts)
    approval_case = build_architecture_successor_adoption_case(
        plan,
        requester_subject="workload:architecture-successor-controller",
        request_reason="adopt approved provider snapshot and contract",
        requested_at=NOW,
        expires_at=NOW + timedelta(hours=48),
    )
    return facts, ArchitectureSuccessorAdoptionRequestResult(
        plan=plan,
        approval_case=approval_case,
        created=created,
    )


def _architecture_successor_data_product_release_result(*, created=True):
    facts = _release_facts()
    plan = build_architecture_successor_data_product_release_plan(**facts)
    approval_case = build_architecture_successor_release_approval_case(
        plan,
        requester_subject="workload:data-product-controller",
        request_reason="release approved parcel successor",
        requested_at=NOW,
        expires_at=NOW + timedelta(hours=48),
    )
    return facts, ArchitectureSuccessorReleaseRequestResult(
        plan=plan,
        approval_case=approval_case,
        created=created,
    )


def _manual_spec(**overrides):
    values = {
        "tenant_id": TENANT,
        "client_request_id": "operator-console-20260801-001",
        "definition_version_id": DEFINITION_ID,
        "logical_start": NOW,
        "logical_end": datetime(2026, 7, 25, 12, 0, tzinfo=UTC),
        "input_bindings": (
            {
                "binding_name": "source",
                "resource_version_id": SOURCE_ID,
                "semantic_type": "gis.land_use.parcels",
            },
        ),
        "execution_plan_artifact_id": PLAN_ID,
        "requester_subject": ACTOR,
        "workload_subject_id": "dataops-adapter",
        "purpose": "run an operator-requested governed parcel audit",
        "policy_version_ref": "gda://tenant-a/policy/dataops-manual:v1",
        "policy_evaluator_subject": "workload:policy-evaluator",
        "config_fingerprint": "a" * 64,
    }
    values.update(overrides)
    return DataOpsManualTriggerSpec(**values)


def _manual_result() -> ManualTriggerWriteResult:
    submission = build_manual_dataops_submission(_manual_spec(), admitted_at=NOW)
    command = PlatformCommand(
        tenant_id=TENANT,
        command_id=UUID("00000000-0000-4000-8000-000000000071"),
        run_id=submission.run.run_id,
        command_type="dolphinscheduler.dispatch",
        execution_plan_artifact_id=PLAN_ID,
        dedupe_key=f"dolphinscheduler.dispatch:{submission.run.run_id}:{PLAN_ID}",
        actor_subject="workload:dataops-adapter",
        payload={"schema": "gda.dolphinscheduler_dispatch_command.v1"},
        available_at=NOW,
        created_at=NOW,
    )
    return ManualTriggerWriteResult(
        request_sha256=submission.request_sha256,
        admitted_at=NOW,
        invocation=submission.invocation,
        run=submission.run,
        command=command,
        invocation_resource_created=True,
        invocation_version_created=True,
        policy_artifact_created=True,
        run_created=True,
        command_created=True,
    )


def _cancel_result() -> DataOpsCancelWriteResult:
    manual = build_manual_dataops_submission(_manual_spec(), admitted_at=NOW)
    run = manual.run.model_copy(update={"status": RunStatus.DISPATCHING, "state_version": 1})
    manifest = {"schema": "gda.test_execution_plan.v1"}
    plan = Artifact(
        tenant_id=TENANT,
        artifact_id=PLAN_ID,
        artifact_key="test-execution-plan",
        artifact_role="execution_plan",
        storage_uri="postgresql://gda-control/execution-plans/tenant-a/test",
        media_type="application/vnd.gda.test-plan+json",
        content_sha256=canonical_json_fingerprint(manifest),
        size_bytes=39,
        run_id=None,
        resource_version_id=DEFINITION_ID,
        manifest=manifest,
        created_by="workload:dataops-adapter",
        created_at=NOW,
    )
    spec = DataOpsCancelSpec(
        tenant_id=TENANT,
        run_id=run.run_id,
        client_request_id="cancel-console-20260801-001",
        expected_state_version=1,
        requester_subject=ACTOR,
        reason="operator cancelled an obsolete source refresh",
        workload_subject="workload:dataops-adapter",
        policy_version_ref="gda://tenant-a/policy/dataops-cancel:v1",
        policy_evaluator_subject="workload:policy-evaluator",
    )
    submission = build_dataops_cancel_submission(spec, run, plan, admitted_at=NOW)
    return DataOpsCancelWriteResult(
        request_sha256=submission.request_sha256,
        admitted_at=NOW,
        run=run.model_copy(update={"status": RunStatus.CANCELLING, "state_version": 2}),
        policy_artifact=submission.policy_artifact,
        command=submission.command,
        policy_artifact_created=True,
        command_created=True,
    )


def test_run_immutable_binding_comparison_is_input_order_independent():
    first_payload = _run().model_dump(mode="python")
    first_payload["input_bindings"] = (
        *first_payload["input_bindings"],
        {
            "binding_name": "invocation",
            "resource_version_id": UUID("00000000-0000-4000-8000-000000000040"),
            "semantic_type": "platform.dataops.invocation",
        },
    )
    first = PlatformRun(**first_payload)
    replay = PlatformRun(
        **{
            **first.model_dump(mode="python"),
            "input_bindings": tuple(reversed(first.input_bindings)),
        }
    )

    assert PlatformGateway._run_binding(first) == PlatformGateway._run_binding(replay)


def test_cancel_terminal_timing_allows_provider_second_precision():
    cancel_requested_at = datetime(2026, 8, 18, 15, 13, 29, 477_639, tzinfo=UTC)
    provider_terminal_at = cancel_requested_at.replace(microsecond=0)

    assert PlatformGateway._cancel_terminal_evidence_is_current(
        provider_terminal_at,
        cancel_requested_at,
    )


def test_cancel_terminal_timing_rejects_pre_admission_evidence():
    cancel_requested_at = datetime(2026, 8, 18, 15, 13, 29, 477_639, tzinfo=UTC)
    stale_terminal_at = cancel_requested_at - timedelta(seconds=2)

    assert not PlatformGateway._cancel_terminal_evidence_is_current(
        stale_terminal_at,
        cancel_requested_at,
    )


def _quality():
    quality_result_id = UUID("00000000-0000-4000-8000-0000000000a0")
    evidence_artifact_id = UUID("00000000-0000-4000-8000-0000000000b0")
    metrics = {"feature_count": 3, "geometry_errors": 0}
    return QualityResult(
        tenant_id=TENANT,
        quality_result_id=quality_result_id,
        run_id=RUN_ID,
        resource_version_id=DEFINITION_ID,
        rule_version_ref="gda://tenant-a/quality-rule/dltb-v1",
        verdict="passed",
        metrics=metrics,
        evidence_artifact_id=evidence_artifact_id,
        result_sha256=quality_result_fingerprint(
            tenant_id=TENANT,
            run_id=RUN_ID,
            resource_version_id=DEFINITION_ID,
            rule_version_ref="gda://tenant-a/quality-rule/dltb-v1",
            verdict="passed",
            metrics=metrics,
            evidence_artifact_id=evidence_artifact_id,
            evaluated_by="workload:quality-evaluator",
            evaluated_at=NOW,
        ),
        evaluated_by="workload:quality-evaluator",
        evaluated_at=NOW,
    )


def test_definition_registration_requires_resource_version_identity_chain():
    fingerprint = platform_definition_fingerprint(
        orchestration_class="dataops",
        capability_id="land_use.publish",
        portability_class="portable",
        definition_document={"tasks": ["publish"]},
        input_contract={"source": "dataset"},
        output_contract={"product": "dataset"},
    )
    definition_resource = _resource(
        resource_urn="gda://tenant-a/definition/parcel-publish",
        resource_kind="definition",
        authority_system="gda",
        authority_locator="definition/parcel-publish",
    )
    definition_version = _version(
        resource_urn=definition_resource.resource_urn,
        resource_version_id=DEFINITION_ID,
        content_sha256=fingerprint,
    )
    definition = {
        "tenant_id": TENANT,
        "definition_urn": definition_resource.resource_urn,
        "definition_version_id": DEFINITION_ID,
        "orchestration_class": "dataops",
        "capability_id": "land_use.publish",
        "portability_class": "portable",
        "definition_document": {"tasks": ["publish"]},
        "input_contract": {"source": "dataset"},
        "output_contract": {"product": "dataset"},
        "definition_sha256": fingerprint,
    }

    registration = DefinitionRegistration(
        resource=definition_resource,
        resource_version=definition_version,
        definition=definition,
    )

    assert registration.definition.definition_version_id == DEFINITION_ID
    with pytest.raises(ValidationError, match="IDs must match"):
        DefinitionRegistration(
            resource=definition_resource,
            resource_version=definition_version.model_copy(
                update={"resource_version_id": SOURCE_ID}
            ),
            definition=definition,
        )


def test_resource_route_requires_authentication_and_platform_role():
    request = _request(body=_resource().model_dump(mode="json"))
    with patch.object(routes, "_get_user_from_request", return_value=None):
        response = asyncio.run(routes.create_resource(request))
    assert response.status_code == 401

    with patch.object(routes, "_get_user_from_request", return_value=_user(role="analyst")):
        response = asyncio.run(routes.create_resource(request))
    assert response.status_code == 403
    assert json.loads(response.body)["error"]["code"] == "platform_role_required"


def test_resource_route_fails_closed_without_tenant_and_rejects_tenant_override():
    request = _request(body=_resource().model_dump(mode="json"))
    with patch.object(routes, "_get_user_from_request", return_value=_user(tenant_id=None)):
        response = asyncio.run(routes.create_resource(request))
    assert response.status_code == 403
    assert json.loads(response.body)["error"]["code"] == "tenant_context_required"

    other = _resource(
        tenant_id="tenant-b",
        resource_urn="gda://tenant-b/dataset/source-parcels",
    )
    request = _request(body=other.model_dump(mode="json"))
    with patch.object(routes, "_get_user_from_request", return_value=_user()):
        response = asyncio.run(routes.create_resource(request))
    assert response.status_code == 403
    assert json.loads(response.body)["error"]["code"] == "tenant_mismatch"


def test_resource_route_distinguishes_created_and_idempotent_replay():
    resource = _resource()
    gateway = MagicMock()
    gateway.register_resource.side_effect = (
        GatewayWriteResult(resource, True),
        GatewayWriteResult(resource, False),
    )
    request = _request(body=resource.model_dump(mode="json"))
    with (
        patch.object(routes, "_get_user_from_request", return_value=_user()),
        patch.object(routes, "_gateway", return_value=gateway),
    ):
        created = asyncio.run(routes.create_resource(request))
        replay = asyncio.run(routes.create_resource(request))

    assert created.status_code == 201
    assert replay.status_code == 200
    assert json.loads(replay.body)["created"] is False


def test_resource_version_route_rejects_actor_spoofing():
    request = _request(body=_version(created_by="human:someone-else").model_dump(mode="json"))
    with patch.object(routes, "_get_user_from_request", return_value=_user()):
        response = asyncio.run(routes.create_resource_version(request))
    assert response.status_code == 403
    assert json.loads(response.body)["error"]["code"] == "actor_mismatch"


def test_resource_version_list_route_is_tenant_scoped_and_paginated():
    gateway = MagicMock()
    gateway.list_resource_versions.return_value = GatewayResourceVersionPage(
        items=(_version(),),
        offset=20,
        limit=20,
        has_more=True,
    )
    request = _request(query={"limit": "20", "offset": "20"})
    with (
        patch.object(routes, "_get_user_from_request", return_value=_user()),
        patch.object(routes, "_gateway", return_value=gateway),
    ):
        response = asyncio.run(routes.list_resource_versions(request))

    assert response.status_code == 200
    payload = json.loads(response.body)["data"]
    assert payload["items"][0]["resource_version_id"] == str(SOURCE_ID)
    assert payload["count"] == 1
    assert payload["offset"] == 20
    assert payload["limit"] == 20
    assert payload["has_more"] is True
    gateway.list_resource_versions.assert_called_once_with(
        TENANT,
        limit=20,
        offset=20,
    )


@pytest.mark.parametrize(
    "query",
    (
        {"limit": "101"},
        {"offset": "-1"},
        {"limit": "many"},
    ),
)
def test_resource_version_list_route_rejects_unbounded_query(query):
    gateway = MagicMock()
    request = _request(query=query)
    with (
        patch.object(routes, "_get_user_from_request", return_value=_user()),
        patch.object(routes, "_gateway", return_value=gateway),
    ):
        response = asyncio.run(routes.list_resource_versions(request))

    assert response.status_code == 400
    assert json.loads(response.body)["error"]["code"] == (
        "invalid_resource_version_query"
    )
    gateway.list_resource_versions.assert_not_called()


def test_gateway_resource_version_list_is_bounded_and_detects_next_page():
    next_id = UUID("00000000-0000-4000-8000-000000000034")
    first = _version().model_dump(mode="python")
    second = _version(
        resource_version_id=next_id,
        version_key="snapshot-0",
        content_sha256="b" * 64,
        created_at=NOW - timedelta(hours=1),
    ).model_dump(mode="python")
    rows_result = MagicMock()
    rows_result.mappings.return_value.all.return_value = [first, second]
    connection = MagicMock()
    connection.execute.return_value = rows_result
    transaction = MagicMock()
    transaction.__enter__.return_value = connection
    transaction.__exit__.return_value = False
    gateway = PlatformGateway()

    with patch.object(gateway, "_transaction", return_value=transaction):
        page = gateway.list_resource_versions(TENANT, limit=1, offset=3)

    assert page.items == (_version(),)
    assert page.offset == 3
    assert page.limit == 1
    assert page.has_more is True
    assert connection.execute.call_args.args[1] == {
        "tenant_id": TENANT,
        "row_limit": 2,
        "offset": 3,
    }


def test_resource_version_architecture_route_is_tenant_scoped_and_fail_closed():
    architecture = _architecture()
    gateway = MagicMock()
    gateway.get_resource_version_architecture.return_value = architecture
    request = _request(path={"resource_version_id": str(SOURCE_ID)})
    with (
        patch.object(routes, "_get_user_from_request", return_value=_user()),
        patch.object(routes, "_gateway", return_value=gateway),
    ):
        response = asyncio.run(routes.get_resource_version_architecture(request))

    assert response.status_code == 200
    payload = json.loads(response.body)["data"]
    assert payload["resource_version_id"] == str(SOURCE_ID)
    assert payload["architecture_ready"] is False
    assert payload["missing_components"] == [
        "schema_version",
        "data_contract_version",
        "physical_location",
        "architecture_binding",
    ]
    gateway.get_resource_version_architecture.assert_called_once_with(TENANT, SOURCE_ID)


def test_resource_version_architecture_reconciliation_uses_server_evaluation_time():
    architecture = _architecture()
    reconciliation = ResourceVersionArchitectureReconciliation(
        tenant_id=TENANT,
        resource_version_id=SOURCE_ID,
        status="unobserved",
        architecture=architecture,
        evaluated_at=NOW,
        required_actions=("harvest_provider",),
    )
    gateway = MagicMock()
    gateway.reconcile_resource_version_architecture.return_value = reconciliation
    request = _request(path={"resource_version_id": str(SOURCE_ID)})
    with (
        patch.object(routes, "_get_user_from_request", return_value=_user()),
        patch.object(routes, "_gateway", return_value=gateway),
    ):
        response = asyncio.run(
            routes.get_resource_version_architecture_reconciliation(request)
        )

    assert response.status_code == 200
    payload = json.loads(response.body)["data"]
    assert payload["status"] == "unobserved"
    assert payload["required_actions"] == ["harvest_provider"]
    gateway.reconcile_resource_version_architecture.assert_called_once_with(
        TENANT, SOURCE_ID
    )


def test_architecture_review_route_derives_authority_and_server_time():
    service = MagicMock()
    service.request_review.return_value = _architecture_change_review_result()
    request = _request(
        body={
            "request_reason": "review provider schema drift",
            "expires_in_hours": 48,
        },
        path={"resource_version_id": str(SOURCE_ID)},
    )
    with (
        patch.object(routes, "_get_user_from_request", return_value=_user()),
        patch.object(
            routes,
            "_architecture_change_approval_service",
            return_value=service,
        ),
        patch.object(routes, "_utc_now", return_value=NOW),
        patch.dict(
            routes.os.environ,
            {"GDA_APPROVAL_CASE_OWNER_REF": "team:data-governance"},
        ),
    ):
        response = asyncio.run(
            routes.create_resource_version_architecture_review(request)
        )

    assert response.status_code == 201
    payload = json.loads(response.body)
    assert payload["created"] is True
    assert payload["data"]["review"]["reconciliation_status"] == "schema_drift"
    assert payload["data"]["approval_case"]["action"] == (
        ARCHITECTURE_CHANGE_REVIEW_ACTION
    )
    assert service.request_review.call_args.kwargs == {
        "tenant_id": TENANT,
        "resource_version_id": SOURCE_ID,
        "requester_subject": ACTOR,
        "request_reason": "review provider schema drift",
        "owner_ref": "team:data-governance",
        "requested_at": NOW,
        "expires_at": NOW + timedelta(hours=48),
    }


def test_architecture_assessment_route_derives_authority_and_server_time():
    service = MagicMock()
    service.request_review.return_value = _architecture_change_assessment_result()
    baseline_snapshot = _schema_snapshot()
    candidate_snapshot = _schema_snapshot(include_zoning_code=True)
    baseline_artifact_id = UUID("00000000-0000-4000-8000-000000000034")
    candidate_artifact_id = UUID("00000000-0000-4000-8000-000000000035")
    request = _request(
        body={
            "baseline_schema_snapshot": baseline_snapshot.model_dump(mode="json"),
            "candidate_schema_snapshot": candidate_snapshot.model_dump(mode="json"),
            "baseline_schema_artifact_id": str(baseline_artifact_id),
            "candidate_schema_artifact_id": str(candidate_artifact_id),
            "request_reason": "review schema compatibility and downstream impact",
            "expires_in_hours": 48,
            "max_lineage_depth": 3,
            "max_lineage_edges": 20,
        },
        path={"resource_version_id": str(SOURCE_ID)},
    )
    with (
        patch.object(routes, "_get_user_from_request", return_value=_user()),
        patch.object(
            routes,
            "_architecture_change_assessment_service",
            return_value=service,
        ),
        patch.object(routes, "_utc_now", return_value=NOW),
        patch.dict(
            routes.os.environ,
            {"GDA_APPROVAL_CASE_OWNER_REF": "team:data-governance"},
        ),
    ):
        response = asyncio.run(
            routes.create_resource_version_postgis_architecture_assessment(request)
        )

    assert response.status_code == 201
    payload = json.loads(response.body)
    assert payload["created"] is True
    assert payload["data"]["review"]["compatibility_verdict"] == (
        "backward_compatible"
    )
    assert payload["data"]["approval_case"]["action"] == (
        "data_architecture.assessed_change_review"
    )
    assert service.request_review.call_args.kwargs == {
        "tenant_id": TENANT,
        "resource_version_id": SOURCE_ID,
        "baseline_snapshot": baseline_snapshot,
        "candidate_snapshot": candidate_snapshot,
        "baseline_schema_artifact_id": baseline_artifact_id,
        "candidate_schema_artifact_id": candidate_artifact_id,
        "requester_subject": ACTOR,
        "request_reason": "review schema compatibility and downstream impact",
        "owner_ref": "team:data-governance",
        "requested_at": NOW,
        "expires_at": NOW + timedelta(hours=48),
        "evaluated_at": NOW,
        "max_lineage_depth": 3,
        "max_lineage_edges": 20,
    }


def test_architecture_assessment_route_rejects_identity_spoofing_before_service():
    service = MagicMock()
    baseline_snapshot = _schema_snapshot()
    candidate_snapshot = _schema_snapshot(include_zoning_code=True)
    request = _request(
        body={
            "tenant_id": "tenant-b",
            "baseline_schema_snapshot": baseline_snapshot.model_dump(mode="json"),
            "candidate_schema_snapshot": candidate_snapshot.model_dump(mode="json"),
            "baseline_schema_artifact_id": "00000000-0000-4000-8000-000000000034",
            "candidate_schema_artifact_id": "00000000-0000-4000-8000-000000000035",
            "request_reason": "attempt to override tenant scope",
        },
        path={"resource_version_id": str(SOURCE_ID)},
    )
    with (
        patch.object(routes, "_get_user_from_request", return_value=_user()),
        patch.object(
            routes,
            "_architecture_change_assessment_service",
            return_value=service,
        ),
    ):
        response = asyncio.run(
            routes.create_resource_version_postgis_architecture_assessment(request)
        )

    assert response.status_code == 422
    assert json.loads(response.body)["error"]["code"] == "contract_validation_failed"
    service.request_review.assert_not_called()


def test_architecture_successor_adoption_approval_derives_workload_identity():
    facts, result = _architecture_successor_adoption_result()
    predecessor = facts["predecessor"]
    successor = facts["successor_resource_version"]
    architecture = facts["successor_architecture"]
    service = MagicMock()
    service.request_adoption.return_value = result
    request = _request(
        body={
            "assessed_approval_case_ref": facts["assessed_case"].approval_case_ref,
            "successor_resource_version": successor.model_dump(mode="json"),
            "successor_architecture": architecture.model_dump(mode="json"),
            "request_reason": "adopt approved provider snapshot and contract",
            "expires_in_hours": 48,
        },
        path={"resource_version_id": str(predecessor.resource_version_id)},
    )
    with (
        patch.object(
            routes,
            "_get_user_from_request",
            return_value=_user(
                tenant_id=predecessor.tenant_id,
                subject_type="workload",
                identifier="architecture-successor-controller",
            ),
        ),
        patch.object(
            routes,
            "_architecture_successor_adoption_service",
            return_value=service,
        ),
        patch.object(routes, "_utc_now", return_value=NOW),
        patch.dict(
            routes.os.environ,
            {"GDA_APPROVAL_CASE_OWNER_REF": "team:data-governance"},
        ),
    ):
        response = asyncio.run(
            routes.create_resource_version_architecture_successor_adoption_approval(
                request
            )
        )

    assert response.status_code == 201
    payload = json.loads(response.body)
    assert payload["created"] is True
    assert payload["data"]["approval_case"]["action"] == (
        "data_architecture.create_successor_version"
    )
    assert service.request_adoption.call_args.kwargs == {
        "tenant_id": predecessor.tenant_id,
        "assessed_approval_case_ref": facts["assessed_case"].approval_case_ref,
        "successor_resource_version": successor,
        "successor_architecture": architecture,
        "requester_subject": "workload:architecture-successor-controller",
        "request_reason": "adopt approved provider snapshot and contract",
        "owner_ref": "team:data-governance",
        "requested_at": NOW,
        "expires_at": NOW + timedelta(hours=48),
    }


def test_architecture_successor_adoption_rejects_spoofed_or_human_actor():
    facts, _ = _architecture_successor_adoption_result()
    predecessor = facts["predecessor"]
    successor = facts["successor_resource_version"]
    architecture = facts["successor_architecture"]
    service = MagicMock()
    body = {
        "assessed_approval_case_ref": facts["assessed_case"].approval_case_ref,
        "successor_resource_version": successor.model_dump(mode="json"),
        "successor_architecture": architecture.model_dump(mode="json"),
        "request_reason": "attempt to submit a successor as another controller",
    }
    request = _request(
        body=body,
        path={"resource_version_id": str(predecessor.resource_version_id)},
    )
    with (
        patch.object(
            routes,
            "_get_user_from_request",
            return_value=_user(
                tenant_id=predecessor.tenant_id,
                subject_type="workload",
                identifier="other-controller",
            ),
        ),
        patch.object(
            routes,
            "_architecture_successor_adoption_service",
            return_value=service,
        ),
    ):
        spoofed = asyncio.run(
            routes.create_resource_version_architecture_successor_adoption_approval(
                request
            )
        )
    assert spoofed.status_code == 403
    assert json.loads(spoofed.body)["error"]["code"] == "actor_mismatch"
    service.request_adoption.assert_not_called()

    with patch.object(
        routes,
        "_get_user_from_request",
        return_value=_user(tenant_id=predecessor.tenant_id),
    ):
        human = asyncio.run(
            routes.create_resource_version_architecture_successor_adoption_approval(
                request
            )
        )
    assert human.status_code == 403
    assert json.loads(human.body)["error"]["code"] == "workload_identity_required"


def test_architecture_successor_adoption_execution_binds_path_and_workload():
    facts, request_result = _architecture_successor_adoption_result()
    predecessor = facts["predecessor"]
    plan = request_result.plan
    service = MagicMock()
    service.adopt.return_value = GatewayWriteResult(value=plan, created=True)
    request = _request(
        body={
            "plan": plan.model_dump(mode="json"),
            "adoption_approval_case_ref": request_result.approval_case.approval_case_ref,
        },
        path={"resource_version_id": str(predecessor.resource_version_id)},
    )
    with (
        patch.object(
            routes,
            "_get_user_from_request",
            return_value=_user(
                tenant_id=predecessor.tenant_id,
                subject_type="workload",
                identifier="architecture-successor-controller",
            ),
        ),
        patch.object(
            routes,
            "_architecture_successor_adoption_service",
            return_value=service,
        ),
        patch.object(routes, "_utc_now", return_value=NOW),
    ):
        response = asyncio.run(
            routes.adopt_resource_version_architecture_successor(request)
        )

    assert response.status_code == 201
    assert json.loads(response.body)["data"]["plan_sha256"] == plan.plan_sha256
    assert service.adopt.call_args.args == (plan,)
    assert service.adopt.call_args.kwargs == {
        "adoption_approval_case_ref": request_result.approval_case.approval_case_ref,
        "evaluated_at": NOW,
    }

    request.path_params = {"resource_version_id": str(TARGET_ID)}
    with patch.object(
        routes,
        "_get_user_from_request",
        return_value=_user(
            tenant_id=predecessor.tenant_id,
            subject_type="workload",
            identifier="architecture-successor-controller",
        ),
    ):
        mismatch = asyncio.run(
            routes.adopt_resource_version_architecture_successor(request)
        )
    assert mismatch.status_code == 422
    assert json.loads(mismatch.body)["error"]["code"] == "successor_predecessor_mismatch"
    assert service.adopt.call_count == 1


def test_successor_data_product_release_approval_derives_workload_identity():
    _, result = _architecture_successor_data_product_release_result()
    plan = result.plan
    service = MagicMock()
    service.request_release.return_value = result
    request = _request(
        body={
            "plan": plan.model_dump(mode="json"),
            "request_reason": "release approved parcel successor",
            "expires_in_hours": 48,
        }
    )
    with (
        patch.object(
            routes,
            "_get_user_from_request",
            return_value=_user(
                tenant_id=plan.tenant_id,
                subject_type="workload",
                identifier="data-product-controller",
            ),
        ),
        patch.object(
            routes,
            "_architecture_successor_data_product_release_service",
            return_value=service,
        ),
        patch.object(routes, "_utc_now", return_value=NOW),
        patch.dict(
            routes.os.environ,
            {"GDA_APPROVAL_CASE_OWNER_REF": "team:data-governance"},
        ),
    ):
        response = asyncio.run(
            routes.create_architecture_successor_data_product_release_approval(request)
        )

    assert response.status_code == 201
    payload = json.loads(response.body)
    assert payload["data"]["approval_case"]["action"] == (
        "data_product.publish_architecture_successor"
    )
    assert service.request_release.call_args.args == (plan,)
    assert service.request_release.call_args.kwargs == {
        "requester_subject": "workload:data-product-controller",
        "request_reason": "release approved parcel successor",
        "owner_ref": "team:data-governance",
        "requested_at": NOW,
        "expires_at": NOW + timedelta(hours=48),
    }


def test_successor_data_product_release_publish_requires_product_workload():
    _, request_result = _architecture_successor_data_product_release_result()
    plan = request_result.plan
    service = MagicMock()
    service.publish.return_value = {
        "product": {"product_urn": plan.product_urn},
        "version": {
            "data_product_version_id": str(
                plan.successor_data_product_version.data_product_version_id
            )
        },
        "idempotent_replay": False,
    }
    request = _request(
        body={
            "plan": plan.model_dump(mode="json"),
            "release_approval_case_ref": request_result.approval_case.approval_case_ref,
            "idempotency_key": "release-parcels-v2-001",
            "reason": "publish the independently approved successor",
        }
    )
    with (
        patch.object(
            routes,
            "_get_user_from_request",
            return_value=_user(
                tenant_id=plan.tenant_id,
                subject_type="workload",
                identifier="data-product-controller",
            ),
        ),
        patch.object(
            routes,
            "_architecture_successor_data_product_release_service",
            return_value=service,
        ),
    ):
        response = asyncio.run(
            routes.publish_architecture_successor_data_product_release(request)
        )

    assert response.status_code == 201
    assert json.loads(response.body)["created"] is True
    assert service.publish.call_args.args == (plan,)
    assert service.publish.call_args.kwargs == {
        "release_approval_case_ref": request_result.approval_case.approval_case_ref,
        "idempotency_key": "release-parcels-v2-001",
        "reason": "publish the independently approved successor",
    }

    with patch.object(
        routes,
        "_get_user_from_request",
        return_value=_user(tenant_id=plan.tenant_id),
    ):
        rejected = asyncio.run(
            routes.publish_architecture_successor_data_product_release(request)
        )
    assert rejected.status_code == 403
    assert json.loads(rejected.body)["error"]["code"] == "workload_identity_required"
    assert service.publish.call_count == 1


def test_blueprint_release_publish_delegates_to_registry_with_workload_binding():
    product, version, binding = _blueprint_release_publication_payload()
    registry = MagicMock()
    registry.publish.return_value = {
        "idempotent_replay": False,
        "version_created": True,
        "blueprint_release_validated": True,
    }
    request = _request(
        body={
            "product": product.model_dump(mode="json"),
            "version": version.model_dump(mode="json"),
            "blueprint_release_binding": binding.model_dump(mode="json", by_alias=True),
            "idempotency_key": "publish-parcels-v1",
            "reason": "publish approved parcel blueprint",
        }
    )
    with (
        patch.object(
            routes,
            "_get_user_from_request",
            return_value=_user(
                subject_type="workload",
                identifier="data-product-controller",
            ),
        ),
        patch.object(routes, "DataProductRegistry", return_value=registry),
    ):
        response = asyncio.run(routes.publish_data_product_blueprint_release(request))

    assert response.status_code == 201
    assert json.loads(response.body)["created"] is True
    assert registry.publish.call_args.args == (product, version)
    assert registry.publish.call_args.kwargs == {
        "idempotency_key": "publish-parcels-v1",
        "reason": "publish approved parcel blueprint",
        "blueprint_release_binding": binding,
    }


def test_blueprint_release_publish_requires_bound_workload_and_rejects_actor_spoofing():
    product, version, binding = _blueprint_release_publication_payload()
    registry = MagicMock()
    request = _request(
        body={
            "product": product.model_dump(mode="json"),
            "version": version.model_dump(mode="json"),
            "blueprint_release_binding": binding.model_dump(mode="json", by_alias=True),
            "idempotency_key": "publish-parcels-v1",
            "reason": "publish approved parcel blueprint",
        }
    )
    with (
        patch.object(routes, "_get_user_from_request", return_value=_user()),
        patch.object(routes, "DataProductRegistry", return_value=registry),
    ):
        human = asyncio.run(routes.publish_data_product_blueprint_release(request))
    assert human.status_code == 403
    assert json.loads(human.body)["error"]["code"] == "workload_identity_required"
    registry.publish.assert_not_called()

    spoofed_product, spoofed_version, spoofed_binding = _blueprint_release_publication_payload(
        published_by="workload:someone-else"
    )
    spoofed_request = _request(
        body={
            "product": spoofed_product.model_dump(mode="json"),
            "version": spoofed_version.model_dump(mode="json"),
            "blueprint_release_binding": spoofed_binding.model_dump(
                mode="json", by_alias=True
            ),
            "idempotency_key": "publish-parcels-v1",
            "reason": "publish approved parcel blueprint",
        }
    )
    with patch.object(
        routes,
        "_get_user_from_request",
        return_value=_user(
            subject_type="workload",
            identifier="data-product-controller",
        ),
    ):
        spoofed = asyncio.run(
            routes.publish_data_product_blueprint_release(spoofed_request)
        )
    assert spoofed.status_code == 403
    assert json.loads(spoofed.body)["error"]["code"] == "actor_mismatch"
    registry.publish.assert_not_called()


def test_blueprint_release_publish_validates_manifest_conflict_and_maps_registry_errors():
    product, version, binding = _blueprint_release_publication_payload()
    body = {
        "product": product.model_dump(mode="json"),
        "version": version.model_dump(mode="json"),
        "blueprint_release_binding": {
            **binding.model_dump(mode="json", by_alias=True),
            "change_set_sha256": "f" * 64,
        },
        "idempotency_key": "publish-parcels-v1",
        "reason": "publish approved parcel blueprint",
    }
    request = _request(body=body)
    with patch.object(
        routes,
        "_get_user_from_request",
        return_value=_user(
            subject_type="workload",
            identifier="data-product-controller",
        ),
    ):
        invalid = asyncio.run(routes.publish_data_product_blueprint_release(request))
    assert invalid.status_code == 422
    assert json.loads(invalid.body)["error"]["code"] == "contract_validation_failed"

    registry = MagicMock()
    registry.publish.side_effect = DataProductConflictError("immutable release conflict")
    valid_request = _request(
        body={
            "product": product.model_dump(mode="json"),
            "version": version.model_dump(mode="json"),
            "blueprint_release_binding": binding.model_dump(mode="json", by_alias=True),
            "idempotency_key": "publish-parcels-v1",
            "reason": "publish approved parcel blueprint",
        }
    )
    with (
        patch.object(
            routes,
            "_get_user_from_request",
            return_value=_user(
                subject_type="workload",
                identifier="data-product-controller",
            ),
        ),
        patch.object(routes, "DataProductRegistry", return_value=registry),
    ):
        conflict = asyncio.run(
            routes.publish_data_product_blueprint_release(valid_request)
        )
    assert conflict.status_code == 409
    assert json.loads(conflict.body)["error"]["code"] == (
        "data_product_blueprint_release_conflict"
    )


def test_blueprint_release_publish_maps_idempotent_replay_to_http_200():
    product, version, binding = _blueprint_release_publication_payload()
    registry = MagicMock()
    registry.publish.return_value = {"idempotent_replay": True}
    request = _request(
        body={
            "product": product.model_dump(mode="json"),
            "version": version.model_dump(mode="json"),
            "blueprint_release_binding": binding.model_dump(mode="json", by_alias=True),
            "idempotency_key": "publish-parcels-v1",
            "reason": "replay approved parcel blueprint",
        }
    )
    with (
        patch.object(
            routes,
            "_get_user_from_request",
            return_value=_user(
                subject_type="workload",
                identifier="data-product-controller",
            ),
        ),
        patch.object(routes, "DataProductRegistry", return_value=registry),
    ):
        response = asyncio.run(routes.publish_data_product_blueprint_release(request))
    assert response.status_code == 200
    assert json.loads(response.body)["created"] is False


def test_architecture_review_route_rejects_identity_spoofing_before_service():
    service = MagicMock()
    request = _request(
        body={
            "request_reason": "review provider schema drift",
            "expires_in_hours": 48,
            "tenant_id": "tenant-b",
            "requester_subject": "human:spoofed",
            "target_fingerprint": "f" * 64,
        },
        path={"resource_version_id": str(SOURCE_ID)},
    )
    with (
        patch.object(routes, "_get_user_from_request", return_value=_user()),
        patch.object(
            routes,
            "_architecture_change_approval_service",
            return_value=service,
        ),
    ):
        response = asyncio.run(
            routes.create_resource_version_architecture_review(request)
        )

    assert response.status_code == 422
    assert json.loads(response.body)["error"]["code"] == "contract_validation_failed"
    service.request_review.assert_not_called()


def test_architecture_review_route_fails_closed_for_non_reviewable_state():
    service = MagicMock()
    service.request_review.side_effect = ArchitectureChangeApprovalError(
        "architecture status 'unobserved' is not reviewable"
    )
    request = _request(
        body={"request_reason": "request unsupported review"},
        path={"resource_version_id": str(SOURCE_ID)},
    )
    with (
        patch.object(routes, "_get_user_from_request", return_value=_user()),
        patch.object(
            routes,
            "_architecture_change_approval_service",
            return_value=service,
        ),
        patch.object(routes, "_utc_now", return_value=NOW),
    ):
        response = asyncio.run(
            routes.create_resource_version_architecture_review(request)
        )

    assert response.status_code == 422
    assert json.loads(response.body)["error"]["code"] == (
        "architecture_change_not_reviewable"
    )


def test_resource_version_architecture_route_rejects_invalid_id_before_gateway_access():
    gateway = MagicMock()
    request = _request(path={"resource_version_id": "not-a-uuid"})
    with (
        patch.object(routes, "_get_user_from_request", return_value=_user()),
        patch.object(routes, "_gateway", return_value=gateway),
    ):
        response = asyncio.run(routes.get_resource_version_architecture(request))

    assert response.status_code == 400
    assert json.loads(response.body)["error"]["code"] == "invalid_resource_version_id"
    gateway.get_resource_version_architecture.assert_not_called()


def test_resource_version_architecture_route_maps_not_found_and_requires_role():
    gateway = MagicMock()
    gateway.get_resource_version_architecture.side_effect = GatewayNotFoundError(
        "ResourceVersion was not found"
    )
    request = _request(path={"resource_version_id": str(SOURCE_ID)})
    with (
        patch.object(routes, "_get_user_from_request", return_value=_user()),
        patch.object(routes, "_gateway", return_value=gateway),
    ):
        missing = asyncio.run(routes.get_resource_version_architecture(request))

    assert missing.status_code == 404
    assert json.loads(missing.body)["error"]["code"] == "platform_not_found"

    with (
        patch.object(
            routes,
            "_get_user_from_request",
            return_value=_user(role="analyst"),
        ),
        patch.object(routes, "_gateway", return_value=gateway),
    ):
        forbidden = asyncio.run(routes.get_resource_version_architecture(request))

    assert forbidden.status_code == 403
    assert json.loads(forbidden.body)["error"]["code"] == "platform_role_required"
    assert gateway.get_resource_version_architecture.call_count == 1


def test_postgresql_cdc_recovery_observation_route_is_tenant_scoped():
    artifact_id = UUID("00000000-0000-4000-8000-000000000090")
    observation = MagicMock()
    observation.model_dump.return_value = {
        "tenant_id": TENANT,
        "artifact_id": str(artifact_id),
        "disposition": "schedule_resnapshot",
    }
    gateway = MagicMock()
    gateway.get_postgresql_cdc_recovery_observation.return_value = observation
    request = _request(
        path={"artifact_id": str(artifact_id)},
        query={"tenant_id": "tenant-b"},
    )
    with (
        patch.object(routes, "_get_user_from_request", return_value=_user()),
        patch.object(routes, "_gateway", return_value=gateway),
    ):
        response = asyncio.run(routes.get_postgresql_cdc_recovery_observation(request))

    assert response.status_code == 200
    payload = json.loads(response.body)["data"]
    assert payload["tenant_id"] == TENANT
    assert payload["artifact_id"] == str(artifact_id)
    gateway.get_postgresql_cdc_recovery_observation.assert_called_once_with(
        TENANT, artifact_id
    )


def test_postgresql_cdc_recovery_observation_route_rejects_invalid_id_before_gateway_access():
    gateway = MagicMock()
    request = _request(path={"artifact_id": "not-a-uuid"})
    with (
        patch.object(routes, "_get_user_from_request", return_value=_user()),
        patch.object(routes, "_gateway", return_value=gateway),
    ):
        response = asyncio.run(routes.get_postgresql_cdc_recovery_observation(request))

    assert response.status_code == 400
    assert json.loads(response.body)["error"]["code"] == "invalid_artifact_id"
    gateway.get_postgresql_cdc_recovery_observation.assert_not_called()


def test_postgresql_cdc_recovery_observation_route_maps_errors_and_requires_platform_identity():
    artifact_id = UUID("00000000-0000-4000-8000-000000000090")
    gateway = MagicMock()
    gateway.get_postgresql_cdc_recovery_observation.side_effect = GatewayNotFoundError(
        "PostgreSQL CDC recovery observation was not found"
    )
    request = _request(path={"artifact_id": str(artifact_id)})
    with (
        patch.object(routes, "_get_user_from_request", return_value=_user()),
        patch.object(routes, "_gateway", return_value=gateway),
    ):
        missing = asyncio.run(routes.get_postgresql_cdc_recovery_observation(request))

    assert missing.status_code == 404
    assert json.loads(missing.body)["error"]["code"] == "platform_not_found"

    gateway.get_postgresql_cdc_recovery_observation.reset_mock()
    gateway.get_postgresql_cdc_recovery_observation.side_effect = GatewayForbiddenError(
        "tenant access is forbidden"
    )
    with (
        patch.object(routes, "_get_user_from_request", return_value=_user()),
        patch.object(routes, "_gateway", return_value=gateway),
    ):
        forbidden = asyncio.run(routes.get_postgresql_cdc_recovery_observation(request))

    assert forbidden.status_code == 403
    assert json.loads(forbidden.body)["error"]["code"] == "platform_forbidden"

    gateway.get_postgresql_cdc_recovery_observation.reset_mock()
    with patch.object(routes, "_get_user_from_request", return_value=None):
        unauthorized = asyncio.run(
            routes.get_postgresql_cdc_recovery_observation(request)
        )
    assert unauthorized.status_code == 401
    gateway.get_postgresql_cdc_recovery_observation.assert_not_called()

    with patch.object(
        routes, "_get_user_from_request", return_value=_user(role="analyst")
    ):
        role_rejected = asyncio.run(
            routes.get_postgresql_cdc_recovery_observation(request)
        )
    assert role_rejected.status_code == 403
    assert json.loads(role_rejected.body)["error"]["code"] == "platform_role_required"


def test_resource_version_lineage_route_is_tenant_scoped_and_bounded():
    graph = _lineage_graph()
    gateway = MagicMock()
    gateway.query_lineage.return_value = graph
    request = _request(
        path={"resource_version_id": str(SOURCE_ID)},
        query={
            "direction": "downstream",
            "max_depth": "4",
            "max_edges": "25",
            "require_complete": "true",
        },
    )
    with (
        patch.object(routes, "_get_user_from_request", return_value=_user()),
        patch.object(routes, "_gateway", return_value=gateway),
    ):
        response = asyncio.run(routes.get_resource_version_lineage(request))

    assert response.status_code == 200
    payload = json.loads(response.body)["data"]
    assert payload["schema_version"] == "gda.lineage_graph.v1"
    assert payload["root_resource_version_id"] == str(SOURCE_ID)
    assert gateway.query_lineage.call_args.args == (TENANT, SOURCE_ID)
    assert gateway.query_lineage.call_args.kwargs == {
        "direction": "downstream",
        "max_depth": 4,
        "max_edges": 25,
        "require_complete": True,
    }


def test_resource_version_lineage_route_rejects_invalid_query_before_database_access():
    gateway = MagicMock()
    request = _request(
        path={"resource_version_id": str(SOURCE_ID)},
        query={"direction": "sideways", "max_depth": "0"},
    )
    with (
        patch.object(routes, "_get_user_from_request", return_value=_user()),
        patch.object(routes, "_gateway", return_value=gateway),
    ):
        response = asyncio.run(routes.get_resource_version_lineage(request))

    assert response.status_code == 400
    assert json.loads(response.body)["error"]["code"] == "invalid_lineage_query"
    gateway.query_lineage.assert_not_called()


def test_resource_version_lineage_route_exposes_fail_closed_incomplete_error():
    gateway = MagicMock()
    gateway.query_lineage.side_effect = GatewayTraversalLimitError(
        "lineage traversal is incomplete because of: depth_limit"
    )
    request = _request(
        path={"resource_version_id": str(SOURCE_ID)},
        query={"require_complete": "true"},
    )
    with (
        patch.object(routes, "_get_user_from_request", return_value=_user()),
        patch.object(routes, "_gateway", return_value=gateway),
    ):
        response = asyncio.run(routes.get_resource_version_lineage(request))

    assert response.status_code == 422
    assert json.loads(response.body)["error"]["code"] == "lineage_traversal_incomplete"


def test_resource_version_impact_route_requires_typed_change_and_uses_tenant():
    assessment = MagicMock()
    assessment.model_dump.return_value = {
        "schema_version": "gda.lineage_impact.v1",
        "scope": "gda_control_ledger",
    }
    gateway = MagicMock()
    gateway.assess_lineage_impact.return_value = assessment
    request = _request(
        path={"resource_version_id": str(SOURCE_ID)},
        query={"change_type": "crs", "max_depth": "4", "max_edges": "25"},
    )
    with (
        patch.object(routes, "_get_user_from_request", return_value=_user()),
        patch.object(routes, "_gateway", return_value=gateway),
    ):
        response = asyncio.run(routes.get_resource_version_impact(request))

    assert response.status_code == 200
    assert json.loads(response.body)["data"]["schema_version"] == "gda.lineage_impact.v1"
    assert gateway.assess_lineage_impact.call_args.args == (TENANT, SOURCE_ID)
    assert gateway.assess_lineage_impact.call_args.kwargs == {
        "change_type": "crs",
        "max_depth": 4,
        "max_edges": 25,
    }

    missing_change = _request(path={"resource_version_id": str(SOURCE_ID)})
    with (
        patch.object(routes, "_get_user_from_request", return_value=_user()),
        patch.object(routes, "_gateway", return_value=gateway),
    ):
        rejected = asyncio.run(routes.get_resource_version_impact(missing_change))
    assert rejected.status_code == 400
    assert json.loads(rejected.body)["error"]["code"] == "invalid_lineage_impact_query"


def test_gateway_lineage_query_builds_version_graph_and_preserves_traversal_direction():
    target = _version(
        resource_urn="gda://tenant-a/dataset/published-parcels",
        resource_version_id=TARGET_ID,
        version_key="snapshot-2",
        content_sha256="b" * 64,
        authority_version_ref={"snapshot": 2},
    )
    event = LineageEvent(
        tenant_id=TENANT,
        lineage_event_id=LINEAGE_ID,
        event_type="publish",
        source_resource_version_id=SOURCE_ID,
        target_resource_version_id=TARGET_ID,
        producer=ACTOR,
        event_sha256="c" * 64,
        facets={"operation": "publish"},
        occurred_at=NOW,
    )
    root_result = MagicMock()
    root_result.mappings.return_value.one_or_none.return_value = _version().model_dump(
        mode="python"
    )
    row = _lineage_row(
        event,
        _version(),
        target,
        from_version_id=SOURCE_ID,
        to_version_id=TARGET_ID,
        depth=1,
    )
    rows_result = MagicMock()
    rows_result.mappings.return_value.all.return_value = [row]
    connection = MagicMock()
    connection.execute.side_effect = [root_result, rows_result]
    transaction = MagicMock()
    transaction.__enter__.return_value = connection
    transaction.__exit__.return_value = False
    gateway = PlatformGateway()

    with patch.object(gateway, "_transaction", return_value=transaction):
        graph = gateway.query_lineage(
            TENANT,
            SOURCE_ID,
            direction="downstream",
            max_depth=3,
            max_edges=10,
        )

    assert graph.complete is True
    assert graph.reached_depth == 1
    node_depths = [
        (node.resource_version.resource_version_id, node.min_depth) for node in graph.nodes
    ]
    assert node_depths == [
        (SOURCE_ID, 0),
        (TARGET_ID, 1),
    ]
    assert graph.edges[0] == LineageGraphEdge(
        event=event,
        depth=1,
        traversal_from_resource_version_id=SOURCE_ID,
        traversal_to_resource_version_id=TARGET_ID,
    )
    query_parameters = connection.execute.call_args_list[1].args[1]
    assert query_parameters == {
        "tenant_id": TENANT,
        "root_resource_version_id": SOURCE_ID,
        "direction": "downstream",
        "search_depth": 4,
        "row_limit": 11,
    }


def test_gateway_lineage_query_fails_closed_when_edge_limit_is_exceeded():
    first_target = _version(
        resource_urn="gda://tenant-a/dataset/first-output",
        resource_version_id=TARGET_ID,
        version_key="snapshot-2",
        content_sha256="b" * 64,
    )
    second_target_id = UUID("00000000-0000-4000-8000-000000000033")
    second_target = _version(
        resource_urn="gda://tenant-a/dataset/second-output",
        resource_version_id=second_target_id,
        version_key="snapshot-3",
        content_sha256="d" * 64,
    )

    def event(event_id: UUID, target_id: UUID, fingerprint: str) -> LineageEvent:
        return LineageEvent(
            tenant_id=TENANT,
            lineage_event_id=event_id,
            event_type="derive",
            source_resource_version_id=SOURCE_ID,
            target_resource_version_id=target_id,
            producer=ACTOR,
            event_sha256=fingerprint * 64,
            occurred_at=NOW,
        )

    first_event = event(LINEAGE_ID, TARGET_ID, "c")
    second_event = event(
        UUID("00000000-0000-4000-8000-000000000034"), second_target_id, "e"
    )
    rows = [
        _lineage_row(
            first_event,
            _version(),
            first_target,
            from_version_id=SOURCE_ID,
            to_version_id=TARGET_ID,
            depth=1,
        ),
        _lineage_row(
            second_event,
            _version(),
            second_target,
            from_version_id=SOURCE_ID,
            to_version_id=second_target_id,
            depth=1,
        ),
    ]
    root_result = MagicMock()
    root_result.mappings.return_value.one_or_none.return_value = _version().model_dump(
        mode="python"
    )
    rows_result = MagicMock()
    rows_result.mappings.return_value.all.return_value = rows
    connection = MagicMock()
    connection.execute.side_effect = [root_result, rows_result]
    transaction = MagicMock()
    transaction.__enter__.return_value = connection
    transaction.__exit__.return_value = False
    gateway = PlatformGateway()

    with (
        patch.object(gateway, "_transaction", return_value=transaction),
        pytest.raises(GatewayTraversalLimitError, match="edge_limit"),
    ):
        gateway.query_lineage(
            TENANT,
            SOURCE_ID,
            direction="downstream",
            max_depth=3,
            max_edges=1,
            require_complete=True,
        )


def test_gateway_lineage_impact_combines_current_product_and_latest_quality():
    source = _version()
    target = _version(
        resource_urn="gda://tenant-a/dataset/published-parcels",
        resource_version_id=TARGET_ID,
        version_key="snapshot-2",
        content_sha256="b" * 64,
    )
    event = LineageEvent(
        tenant_id=TENANT,
        lineage_event_id=LINEAGE_ID,
        event_type="publish",
        source_resource_version_id=SOURCE_ID,
        target_resource_version_id=TARGET_ID,
        producer=ACTOR,
        event_sha256="c" * 64,
        occurred_at=NOW,
    )
    graph = LineageGraph(
        tenant_id=TENANT,
        root_resource_version_id=SOURCE_ID,
        direction="downstream",
        requested_max_depth=4,
        requested_max_edges=25,
        reached_depth=1,
        complete=True,
        nodes=(
            LineageGraphNode(resource_version=source, min_depth=0, is_root=True),
            LineageGraphNode(resource_version=target, min_depth=1),
        ),
        edges=(
            LineageGraphEdge(
                event=event,
                depth=1,
                traversal_from_resource_version_id=SOURCE_ID,
                traversal_to_resource_version_id=TARGET_ID,
            ),
        ),
        node_count=2,
        edge_count=1,
    )
    product_version_id = UUID("00000000-0000-4000-8000-000000000035")
    product_result = MagicMock()
    product_result.mappings.return_value.all.return_value = [
        {
            "tenant_id": TENANT,
            "product_urn": "gda://tenant-a/data_product/published-parcels",
            "product_slug": "published-parcels",
            "title": "Published parcels",
            "domain": "planning",
            "owner_ref": "team:data-platform",
            "governance_ref": {
                "classification": "internal",
                "visibility": "private",
            },
            "data_product_version_id": product_version_id,
            "version_key": "v1.0.0",
            "source_resource_version_id": SOURCE_ID,
            "output_resource_version_id": TARGET_ID,
            "quality_verdict": "passed",
            "manifest_sha256": "f" * 64,
            "published_at": NOW,
        }
    ]
    metrics = {"invalid_geometry_count": 2}
    quality_result_id = UUID("00000000-0000-4000-8000-000000000036")
    evidence_artifact_id = UUID("00000000-0000-4000-8000-000000000037")
    failed_quality = QualityResult(
        tenant_id=TENANT,
        quality_result_id=quality_result_id,
        run_id=RUN_ID,
        resource_version_id=TARGET_ID,
        rule_version_ref="gda://tenant-a/quality-rule/geometry-v1",
        verdict="failed",
        metrics=metrics,
        evidence_artifact_id=evidence_artifact_id,
        result_sha256=quality_result_fingerprint(
            tenant_id=TENANT,
            run_id=RUN_ID,
            resource_version_id=TARGET_ID,
            rule_version_ref="gda://tenant-a/quality-rule/geometry-v1",
            verdict="failed",
            metrics=metrics,
            evidence_artifact_id=evidence_artifact_id,
            evaluated_by="workload:quality-evaluator",
            evaluated_at=NOW,
        ),
        evaluated_by="workload:quality-evaluator",
        evaluated_at=NOW,
    )
    quality_result = MagicMock()
    quality_result.mappings.return_value.all.return_value = [
        failed_quality.model_dump(mode="python")
    ]
    connection = MagicMock()
    connection.execute.side_effect = [product_result, quality_result]
    transaction = MagicMock()
    transaction.__enter__.return_value = connection
    transaction.__exit__.return_value = False
    gateway = PlatformGateway()

    with (
        patch.object(gateway, "_transaction", return_value=transaction),
        patch.object(gateway, "_query_lineage_in_transaction", return_value=graph),
    ):
        assessment = gateway.assess_lineage_impact(
            TENANT,
            SOURCE_ID,
            change_type="schema",
            max_depth=4,
            max_edges=25,
        )

    assert assessment.scope == "gda_control_ledger"
    assert assessment.disposition == "quality_attention_required"
    assert assessment.review_reasons == (
        "change_type_requires_review",
        "downstream_lineage_present",
        "current_data_product_affected",
        "failed_quality_evidence",
    )
    assert assessment.impacted_data_products[0].matched_resource_version_ids == (
        SOURCE_ID,
        TARGET_ID,
    )
    assert assessment.quality_signals[0].resource_min_depth == 1
    assert len(assessment.assessment_sha256) == 64
    assert connection.execute.call_args_list[0].args[1]["version_ids"] == [
        SOURCE_ID,
        TARGET_ID,
    ]


def test_lineage_impact_contract_rejects_a_stale_assessment_fingerprint():
    graph = _lineage_graph(direction="downstream")
    product = ImpactedDataProduct(
        tenant_id=TENANT,
        product_urn="gda://tenant-a/data_product/source-parcels",
        product_slug="source-parcels",
        title="Source parcels",
        domain="planning",
        owner_ref="team:data-platform",
        governance_ref={"classification": "internal"},
        data_product_version_id=TARGET_ID,
        version_key="v1.0.0",
        source_resource_version_id=SOURCE_ID,
        output_resource_version_id=TARGET_ID,
        quality_verdict="passed",
        manifest_sha256="f" * 64,
        published_at=NOW,
        matched_resource_version_ids=(SOURCE_ID,),
    )
    fingerprint = lineage_impact_fingerprint(
        tenant_id=TENANT,
        root_resource_version=_version(),
        change_type="content",
        lineage=graph,
        impacted_data_products=(product,),
        quality_signals=(),
        disposition="review_required",
        review_reasons=("current_data_product_affected",),
    )
    payload = {
        "tenant_id": TENANT,
        "root_resource_version": _version(),
        "change_type": "content",
        "lineage": graph,
        "impacted_data_products": (product,),
        "quality_signals": (),
        "disposition": "review_required",
        "review_reasons": ("current_data_product_affected",),
        "impacted_resource_version_count": 1,
        "impacted_data_product_count": 1,
        "quality_signal_count": 0,
        "assessment_sha256": fingerprint,
    }
    assert LineageImpactAssessment(**payload).assessment_sha256 == fingerprint
    with pytest.raises(ValidationError, match="assessment_sha256"):
        LineageImpactAssessment(**{**payload, "assessment_sha256": "0" * 64})


def test_run_route_derives_subject_and_tenant_from_authenticated_principal():
    gateway = MagicMock()
    gateway.submit_run.side_effect = lambda run, **_kwargs: GatewayWriteResult(run, True)
    body = {
        "run_id": str(RUN_ID),
        "definition_version_id": str(DEFINITION_ID),
        "orchestration_class": "dataops",
        "input_bindings": [
            {
                "binding_name": "source",
                "resource_version_id": str(SOURCE_ID),
                "semantic_type": "gis.land_use.parcels",
            }
        ],
        "idempotency_key": "publish:parcels:1",
        "purpose": "publish parcels",
        "submitted_at": NOW.isoformat(),
    }
    request = _request(body=body)
    with (
        patch.object(routes, "_get_user_from_request", return_value=_user()),
        patch.object(routes, "_gateway", return_value=gateway),
    ):
        response = asyncio.run(routes.create_run(request))

    assert response.status_code == 201
    submitted = gateway.submit_run.call_args.args[0]
    assert submitted == _run()
    assert submitted.subject_context.tenant_id == TENANT
    assert submitted.subject_context.subject_id == "operator-1"


def test_run_route_preserves_policy_refs_for_workload_identity():
    gateway = MagicMock()
    gateway.submit_run.side_effect = lambda run, **_kwargs: GatewayWriteResult(run, True)
    decision_id = UUID("00000000-0000-4000-8000-000000000080")
    approval_id = UUID("00000000-0000-4000-8000-000000000090")
    body = {
        "run_id": str(RUN_ID),
        "definition_version_id": str(DEFINITION_ID),
        "orchestration_class": "dataops",
        "input_bindings": [],
        "idempotency_key": "publish:authorized:1",
        "policy_refs": {
            "policy_decision_artifact_id": str(decision_id),
            "approval_artifact_id": str(approval_id),
        },
        "request_dispatch": True,
        "purpose": "execute authorized dataops run",
        "submitted_at": NOW.isoformat(),
    }
    request = _request(body=body)
    with (
        patch.object(
            routes,
            "_get_user_from_request",
            return_value=_user(subject_type="workload", identifier="dataops-adapter"),
        ),
        patch.object(routes, "_gateway", return_value=gateway),
    ):
        response = asyncio.run(routes.create_run(request))

    assert response.status_code == 201
    submitted = gateway.submit_run.call_args.args[0]
    assert submitted.subject_context.subject_type.value == "workload"
    assert submitted.policy_refs.policy_decision_artifact_id == decision_id
    assert submitted.policy_refs.approval_artifact_id == approval_id
    assert gateway.submit_run.call_args.kwargs == {"request_dispatch": True}


def test_approval_case_create_derives_tenant_requester_and_canonical_resource():
    authority = MagicMock()
    authority.create.side_effect = lambda case, **_kwargs: ApprovalCaseWriteResult(case, True)
    body = {
        "case_id": "schema-drift-1",
        "target_resource_urn": "gda://tenant-a/schema_drift/" + "a" * 64,
        "target_fingerprint": "a" * 64,
        "action": "source_schema_drift.reconcile",
        "request_reason": "review breaking source schema drift",
        "request_context": {"compatibility": "breaking"},
        "requested_at": NOW.isoformat(),
        "expires_at": (NOW + timedelta(hours=4)).isoformat(),
    }
    request = _request(body=body)
    with (
        patch.object(
            routes,
            "_get_user_from_request",
            return_value=_user(subject_type="workload", identifier="schema-drift-observer"),
        ),
        patch.object(routes, "_approval_case_authority", return_value=authority),
        patch.dict(
            routes.os.environ,
            {"GDA_APPROVAL_CASE_OWNER_REF": "team:data-governance"},
        ),
    ):
        response = asyncio.run(routes.create_approval_case(request))

    assert response.status_code == 201
    payload = json.loads(response.body)
    assert payload["created"] is True
    assert payload["data"]["approval_case_ref"] == APPROVAL_CASE_REF
    created = authority.create.call_args.args[0]
    assert created.tenant_id == TENANT
    assert created.requester_subject == "workload:schema-drift-observer"
    assert authority.create.call_args.kwargs == {"owner_ref": "team:data-governance"}


def test_approval_case_create_rejects_identity_fields_and_maps_conflicts():
    body = {
        "case_id": "schema-drift-1",
        "target_resource_urn": "gda://tenant-a/schema_drift/" + "a" * 64,
        "target_fingerprint": "a" * 64,
        "action": "source_schema_drift.reconcile",
        "request_reason": "review breaking source schema drift",
        "requested_at": NOW.isoformat(),
        "expires_at": (NOW + timedelta(hours=4)).isoformat(),
        "tenant_id": "tenant-b",
        "requester_subject": "human:spoofed",
    }
    request = _request(body=body)
    with patch.object(routes, "_get_user_from_request", return_value=_user()):
        rejected = asyncio.run(routes.create_approval_case(request))
    assert rejected.status_code == 422
    assert json.loads(rejected.body)["error"]["code"] == "contract_validation_failed"

    authority = MagicMock()
    authority.create.side_effect = ApprovalCaseConflictError("immutable binding conflict")
    body.pop("tenant_id")
    body.pop("requester_subject")
    request = _request(body=body)
    with (
        patch.object(routes, "_get_user_from_request", return_value=_user()),
        patch.object(routes, "_approval_case_authority", return_value=authority),
    ):
        conflict = asyncio.run(routes.create_approval_case(request))
    assert conflict.status_code == 409
    assert json.loads(conflict.body)["error"]["code"] == "approval_case_conflict"


def test_approval_case_get_and_events_are_tenant_scoped():
    approval_case = _approval_case()
    event = ApprovalCaseEvent(
        tenant_id=TENANT,
        approval_event_id=UUID("00000000-0000-4000-8000-000000000091"),
        approval_case_ref=APPROVAL_CASE_REF,
        sequence_no=0,
        to_status="pending",
        actor_subject=ACTOR,
        reason="review breaking source schema drift",
        occurred_at=NOW,
    )
    authority = MagicMock()
    authority.get.return_value = approval_case
    authority.events.return_value = (event,)
    notification = ApprovalCaseNotification(
        tenant_id=TENANT,
        notification_id=UUID("00000000-0000-4000-8000-000000000092"),
        approval_case_ref=APPROVAL_CASE_REF,
        approval_event_sequence_no=0,
        notification_kind="requested",
        channel="alertmanager",
        destination_ref="alertmanager:approval-default",
        delivery_order=0,
        status="pending",
        available_at=NOW,
        created_at=NOW,
    )
    authority.notifications.return_value = (notification,)
    authority.notification_recoveries.return_value = ()
    request = _request(path={"case_id": "schema-drift-1"})
    with (
        patch.object(routes, "_get_user_from_request", return_value=_user()),
        patch.object(routes, "_approval_case_authority", return_value=authority),
    ):
        fetched = asyncio.run(routes.get_approval_case(request))
        listed = asyncio.run(routes.list_approval_case_events(request))
        notification_list = asyncio.run(
            routes.list_approval_case_notifications(request)
        )

    assert fetched.status_code == 200
    assert listed.status_code == 200
    assert notification_list.status_code == 200
    assert json.loads(listed.body)["data"]["count"] == 1
    assert json.loads(notification_list.body)["data"]["items"][0]["status"] == (
        "pending"
    )
    assert authority.get.call_args.args == (TENANT, APPROVAL_CASE_REF)
    assert authority.events.call_args.args == (TENANT, APPROVAL_CASE_REF)
    assert authority.notifications.call_args.args == (TENANT, APPROVAL_CASE_REF)
    assert authority.notification_recoveries.call_args.args == (
        TENANT,
        APPROVAL_CASE_REF,
    )


def test_approval_notification_recovery_is_admin_human_scoped_and_audited():
    notification_id = UUID("00000000-0000-4000-8000-000000000093")
    recovered = ApprovalCaseNotification(
        tenant_id=TENANT,
        notification_id=notification_id,
        approval_case_ref=APPROVAL_CASE_REF,
        approval_event_sequence_no=0,
        notification_kind="requested",
        channel="alertmanager",
        destination_ref="alertmanager:approval-default",
        delivery_order=0,
        status="pending",
        available_at=NOW,
        created_at=NOW,
        recovery_count=1,
        last_recovered_by="human:platform-admin",
        last_recovery_reason="receiver route repaired",
        last_recovered_at=NOW,
    )
    audit = ApprovalCaseNotificationRecoveryEvent(
        tenant_id=TENANT,
        recovery_event_id=UUID("00000000-0000-4000-8000-000000000094"),
        notification_id=notification_id,
        approval_case_ref=APPROVAL_CASE_REF,
        recovery_no=1,
        actor_subject="human:platform-admin",
        reason="receiver route repaired",
        previous_attempt_count=10,
        previous_last_error="receiver unavailable",
        occurred_at=NOW,
    )
    authority = MagicMock()
    authority.retry_notification.return_value = recovered
    authority.notifications.return_value = (recovered,)
    authority.notification_recoveries.return_value = (audit,)
    path = {
        "case_id": "schema-drift-1",
        "notification_id": str(notification_id),
    }
    request = _request(
        body={
            "expected_attempt_count": 10,
            "reason": "receiver route repaired",
        },
        path=path,
    )
    with (
        patch.object(
            routes,
            "_get_user_from_request",
            return_value=_user(role="admin", identifier="platform-admin"),
        ),
        patch.object(routes, "_approval_case_authority", return_value=authority),
    ):
        response = asyncio.run(routes.retry_approval_case_notification(request))
        notification_view = asyncio.run(
            routes.list_approval_case_notifications(
                _request(path={"case_id": "schema-drift-1"})
            )
        )

    assert response.status_code == 200
    assert json.loads(response.body)["data"]["recovery_count"] == 1
    assert json.loads(notification_view.body)["data"]["recoveries"][0]["reason"] == (
        "receiver route repaired"
    )
    authority.retry_notification.assert_called_once_with(
        tenant_id=TENANT,
        approval_case_ref=APPROVAL_CASE_REF,
        notification_id=notification_id,
        expected_attempt_count=10,
        actor_subject="human:platform-admin",
        reason="receiver route repaired",
    )

    for user in (
        _user(role="platform_operator"),
        _user(role="admin", subject_type="workload"),
    ):
        authority.retry_notification.reset_mock()
        with (
            patch.object(routes, "_get_user_from_request", return_value=user),
            patch.object(routes, "_approval_case_authority", return_value=authority),
        ):
            forbidden = asyncio.run(
                routes.retry_approval_case_notification(
                    _request(
                        body={
                            "expected_attempt_count": 10,
                            "reason": "unauthorized retry",
                        },
                        path=path,
                    )
                )
            )
        assert forbidden.status_code == 403
        authority.retry_notification.assert_not_called()


def test_approval_assignment_api_is_tenant_scoped_cas_and_role_governed():
    assignment = ApprovalCaseAssignment(
        tenant_id=TENANT,
        approval_case_ref=APPROVAL_CASE_REF,
        assignment_version=1,
        status="assigned",
        assignee_subject="human:data-steward",
        last_actor_subject="human:platform-admin",
        last_reason="route to domain steward",
        assigned_at=NOW,
        updated_at=NOW,
    )
    event = ApprovalCaseAssignmentEvent(
        tenant_id=TENANT,
        assignment_event_id=UUID("00000000-0000-4000-8000-000000000095"),
        approval_case_ref=APPROVAL_CASE_REF,
        assignment_version=1,
        action="assigned",
        to_assignee_subject="human:data-steward",
        actor_subject="human:platform-admin",
        reason="route to domain steward",
        occurred_at=NOW,
    )
    authority = MagicMock()
    authority.assignment.return_value = assignment
    authority.assignment_events.return_value = (event,)
    authority.assignment_actor_access.return_value = ApprovalAssignmentActorAccess(
        actor_subject="human:platform-admin",
        can_decide=False,
        can_delegate=False,
        access_reason="reserved",
    )
    authority.transition_assignment.return_value = assignment
    path = {"case_id": "schema-drift-1"}

    with (
        patch.object(
            routes,
            "_get_user_from_request",
            return_value=_user(role="admin", identifier="platform-admin"),
        ),
        patch.object(routes, "_approval_case_authority", return_value=authority),
    ):
        view = asyncio.run(routes.get_approval_case_assignment(_request(path=path)))
        assigned = asyncio.run(
            routes.transition_approval_case_assignment(
                _request(
                    body={
                        "expected_assignment_version": 0,
                        "operation": "assign",
                        "assignee_id": "data-steward",
                        "reason": "route to domain steward",
                    },
                    path=path,
                )
            )
        )

    assert view.status_code == 200
    assert json.loads(view.body)["data"]["event_count"] == 1
    assert json.loads(view.body)["data"]["actor_access"]["access_reason"] == "reserved"
    assert assigned.status_code == 200
    authority.transition_assignment.assert_called_once_with(
        tenant_id=TENANT,
        approval_case_ref=APPROVAL_CASE_REF,
        expected_assignment_version=0,
        operation=ApprovalCaseAssignmentOperation.ASSIGN,
        actor_subject="human:platform-admin",
        assignee_subject="human:data-steward",
        reason="route to domain steward",
    )

    authority.transition_assignment.reset_mock()
    with (
        patch.object(
            routes,
            "_get_user_from_request",
            return_value=_user(role="admin", identifier="platform-admin"),
        ),
        patch.object(routes, "_approval_case_authority", return_value=authority),
    ):
        team_routed = asyncio.run(
            routes.transition_approval_case_assignment(
                _request(
                    body={
                        "expected_assignment_version": 1,
                        "operation": "reassign",
                        "assignee_subject": "team:data-governance",
                        "reason": "route to governed team",
                    },
                    path=path,
                )
            )
        )
    assert team_routed.status_code == 200
    assert authority.transition_assignment.call_args.kwargs["assignee_subject"] == (
        "team:data-governance"
    )

    authority.transition_assignment.reset_mock()
    with (
        patch.object(
            routes,
            "_get_user_from_request",
            return_value=_user(identifier="data-steward"),
        ),
        patch.object(routes, "_approval_case_authority", return_value=authority),
    ):
        delegated = asyncio.run(
            routes.transition_approval_case_assignment(
                _request(
                    body={
                        "expected_assignment_version": 1,
                        "operation": "delegate",
                        "assignee_id": "next-steward",
                        "reason": "delegate to specialist",
                    },
                    path=path,
                )
            )
        )
    assert delegated.status_code == 200
    assert authority.transition_assignment.call_args.kwargs["actor_subject"] == (
        "human:data-steward"
    )
    assert authority.transition_assignment.call_args.kwargs["assignee_subject"] == (
        "human:next-steward"
    )

    for user, operation in (
        (_user(role="platform_operator"), "reassign"),
        (_user(role="admin", subject_type="workload"), "delegate"),
    ):
        authority.transition_assignment.reset_mock()
        with (
            patch.object(routes, "_get_user_from_request", return_value=user),
            patch.object(routes, "_approval_case_authority", return_value=authority),
        ):
            forbidden = asyncio.run(
                routes.transition_approval_case_assignment(
                    _request(
                        body={
                            "expected_assignment_version": 1,
                            "operation": operation,
                            "assignee_id": "next-steward",
                            "reason": "unauthorized routing change",
                        },
                        path=path,
                    )
                )
            )
        assert forbidden.status_code == 403
        authority.transition_assignment.assert_not_called()


def test_approval_principal_directory_api_is_tenant_scoped_cas_and_admin_governed():
    principal_entry = ApprovalPrincipal(
        tenant_id=TENANT,
        principal_subject="team:data-governance",
        principal_type="team",
        display_name="Data Governance",
        directory_version=1,
        status="active",
        approval_eligible=True,
        availability_status="available",
        valid_from=NOW,
        last_actor_subject="human:platform-admin",
        last_reason="register approval team",
        updated_at=NOW,
        eligible_now=True,
        eligibility_reason="eligible",
    )
    membership = ApprovalTeamMembership(
        tenant_id=TENANT,
        team_subject="team:data-governance",
        member_subject="human:data-steward",
        membership_version=1,
        status="active",
        can_delegate=True,
        valid_from=NOW,
        last_actor_subject="human:platform-admin",
        last_reason="register team lead",
        updated_at=NOW,
    )
    authority = MagicMock()
    authority.list_principals.return_value = (principal_entry,)
    authority.list_team_memberships.return_value = (membership,)
    authority.upsert_principal.return_value = principal_entry
    authority.upsert_team_membership.return_value = membership
    admin = _user(role="admin", identifier="platform-admin")

    with (
        patch.object(routes, "_get_user_from_request", return_value=admin),
        patch.object(routes, "_approval_case_authority", return_value=authority),
    ):
        listed = asyncio.run(
            routes.list_approval_principals(
                _request(query={"eligible_only": "true"})
            )
        )
        registered = asyncio.run(
            routes.upsert_approval_principal(
                _request(
                    body={
                        "expected_directory_version": 0,
                        "display_name": "Data Governance",
                        "reason": "register approval team",
                    },
                    path={
                        "principal_type": "team",
                        "principal_id": "data-governance",
                    },
                )
            )
        )
        member_registered = asyncio.run(
            routes.upsert_approval_team_membership(
                _request(
                    body={
                        "expected_membership_version": 0,
                        "can_delegate": True,
                        "reason": "register team lead",
                    },
                    path={
                        "team_id": "data-governance",
                        "member_id": "data-steward",
                    },
                )
            )
        )
        members = asyncio.run(
            routes.list_approval_team_memberships(
                _request(path={"team_id": "data-governance"})
            )
        )

    assert listed.status_code == 200
    assert json.loads(listed.body)["data"]["count"] == 1
    assert registered.status_code == 200
    assert json.loads(registered.body)["created"] is True
    assert member_registered.status_code == 200
    assert json.loads(members.body)["data"]["items"][0]["membership_version"] == 1
    authority.list_principals.assert_called_once_with(TENANT, eligible_only=True)
    assert authority.upsert_principal.call_args.kwargs["principal_subject"] == (
        "team:data-governance"
    )
    assert authority.upsert_team_membership.call_args.kwargs["member_subject"] == (
        "human:data-steward"
    )
    authority.list_team_memberships.assert_called_once_with(
        TENANT, "team:data-governance"
    )

    authority.upsert_principal.reset_mock()
    with (
        patch.object(
            routes,
            "_get_user_from_request",
            return_value=_user(role="platform_operator"),
        ),
        patch.object(routes, "_approval_case_authority", return_value=authority),
    ):
        forbidden = asyncio.run(
            routes.upsert_approval_principal(
                _request(
                    body={
                        "expected_directory_version": 0,
                        "display_name": "Unauthorized",
                        "reason": "must fail",
                    },
                    path={"principal_type": "human", "principal_id": "reviewer"},
                )
            )
        )
    assert forbidden.status_code == 403
    authority.upsert_principal.assert_not_called()


def test_approval_case_list_is_tenant_scoped_filtered_and_paginated():
    authority = MagicMock()
    authority.list.return_value = ApprovalCasePage(
        items=(_approval_case(),),
        offset=20,
        limit=20,
        has_more=True,
    )
    request = _request(
        query={
            "status": "pending",
            "action": "source_schema_drift.reconcile",
            "limit": "20",
            "offset": "20",
        }
    )
    with (
        patch.object(routes, "_get_user_from_request", return_value=_user()),
        patch.object(routes, "_approval_case_authority", return_value=authority),
    ):
        response = asyncio.run(routes.list_approval_cases(request))

    assert response.status_code == 200
    payload = json.loads(response.body)["data"]
    assert payload["items"][0]["approval_case_ref"] == APPROVAL_CASE_REF
    assert payload["count"] == 1
    assert payload["has_more"] is True
    authority.list.assert_called_once_with(
        TENANT,
        status=ApprovalCaseStatus.PENDING,
        action="source_schema_drift.reconcile",
        limit=20,
        offset=20,
    )


@pytest.mark.parametrize(
    "query",
    (
        {"status": "expired"},
        {"limit": "101"},
        {"offset": "-1"},
        {"limit": "many"},
        {"action": "a" * 129},
        {"action": "invalid action"},
    ),
)
def test_approval_case_list_rejects_invalid_query_before_database_access(query):
    authority = MagicMock()
    request = _request(query=query)
    with (
        patch.object(routes, "_get_user_from_request", return_value=_user()),
        patch.object(routes, "_approval_case_authority", return_value=authority),
    ):
        response = asyncio.run(routes.list_approval_cases(request))

    assert response.status_code == 400
    assert json.loads(response.body)["error"]["code"] == "invalid_approval_case_query"
    authority.list.assert_not_called()


def test_approval_case_authority_list_is_bounded_and_detects_next_page():
    first = _approval_case().model_dump(mode="python")
    second = _approval_case(
        approval_case_ref="gda://tenant-a/approval_case/schema-drift-0",
        target_fingerprint="b" * 64,
        requested_at=NOW - timedelta(hours=1),
        expires_at=NOW + timedelta(hours=3),
    ).model_dump(mode="python")
    rows_result = MagicMock()
    rows_result.mappings.return_value.all.return_value = [first, second]
    connection = MagicMock()
    connection.execute.return_value = rows_result
    transaction = MagicMock()
    transaction.__enter__.return_value = connection
    transaction.__exit__.return_value = False
    authority = ApprovalCaseAuthority()

    with patch.object(authority, "_transaction", return_value=transaction):
        page = authority.list(
            TENANT,
            status=ApprovalCaseStatus.PENDING,
            action="source_schema_drift.reconcile",
            limit=1,
            offset=3,
        )

    assert page.items == (_approval_case(),)
    assert page.offset == 3
    assert page.limit == 1
    assert page.has_more is True
    assert connection.execute.call_args.args[1] == {
        "tenant_id": TENANT,
        "status": "pending",
        "action": "source_schema_drift.reconcile",
        "row_limit": 2,
        "offset": 3,
    }


def test_approval_case_decision_requires_human_and_injects_actor():
    body = {
        "expected_state_version": 0,
        "verdict": "approved",
        "reason": "compatibility plan is acceptable",
        "details": {"ticket": "GOV-101"},
    }
    request = _request(body=body, path={"case_id": "schema-drift-1"})
    with patch.object(
        routes,
        "_get_user_from_request",
        return_value=_user(subject_type="workload", identifier="auto-approver"),
    ):
        rejected = asyncio.run(routes.decide_approval_case(request))
    assert rejected.status_code == 403
    assert json.loads(rejected.body)["error"]["code"] == "human_identity_required"

    approved = _approval_case(
        status="approved",
        state_version=1,
        decided_by="human:data-steward",
        decision_reason="compatibility plan is acceptable",
        decided_at=NOW + timedelta(minutes=5),
    )
    authority = MagicMock()
    authority.decide.return_value = approved
    request = _request(body=body, path={"case_id": "schema-drift-1"})
    with (
        patch.object(
            routes,
            "_get_user_from_request",
            return_value=_user(identifier="data-steward"),
        ),
        patch.object(routes, "_approval_case_authority", return_value=authority),
    ):
        response = asyncio.run(routes.decide_approval_case(request))

    assert response.status_code == 200
    assert authority.decide.call_args.kwargs == {
        "tenant_id": TENANT,
        "approval_case_ref": APPROVAL_CASE_REF,
        "expected_state_version": 0,
        "verdict": ApprovalCaseStatus.APPROVED,
        "actor_subject": "human:data-steward",
        "reason": "compatibility plan is acceptable",
        "details": {"ticket": "GOV-101"},
    }


def test_approval_case_decision_rejects_pending_and_maps_authority_validation():
    request = _request(
        body={
            "expected_state_version": 0,
            "verdict": "pending",
            "reason": "not a terminal decision",
        },
        path={"case_id": "schema-drift-1"},
    )
    with patch.object(routes, "_get_user_from_request", return_value=_user()):
        rejected = asyncio.run(routes.decide_approval_case(request))
    assert rejected.status_code == 422
    assert json.loads(rejected.body)["error"]["code"] == "terminal_verdict_required"

    authority = MagicMock()
    authority.decide.side_effect = ApprovalCaseValidationError(
        "ApprovalCase verdict requires an independent human approver"
    )
    request = _request(
        body={
            "expected_state_version": 0,
            "verdict": "approved",
            "reason": "self approval must fail",
        },
        path={"case_id": "schema-drift-1"},
    )
    with (
        patch.object(routes, "_get_user_from_request", return_value=_user()),
        patch.object(routes, "_approval_case_authority", return_value=authority),
    ):
        rejected = asyncio.run(routes.decide_approval_case(request))
    assert rejected.status_code == 422
    assert json.loads(rejected.body)["error"]["code"] == "approval_case_validation_error"


def test_manual_dataops_route_derives_requester_and_uses_trusted_runtime_profile():
    assert routes.ManualDataOpsRunRequest is ManualDataOpsRunRequest
    gateway = MagicMock()
    gateway.submit_manual_trigger.return_value = _manual_result()
    profile = routes.ManualDataOpsRuntimeProfile(
        workload_subject="workload:dataops-adapter",
        workload_roles=("platform_operator",),
        policy_version_ref="gda://tenant-a/policy/dataops-manual:v1",
        policy_evaluator_subject="workload:policy-evaluator",
    )
    body = {
        "client_request_id": "operator-console-20260801-001",
        "definition_version_id": str(DEFINITION_ID),
        "logical_start": NOW.isoformat(),
        "logical_end": "2026-07-25T12:00:00+00:00",
        "input_bindings": [
            {
                "binding_name": "source",
                "resource_version_id": str(SOURCE_ID),
                "semantic_type": "gis.land_use.parcels",
            }
        ],
        "execution_plan_artifact_id": str(PLAN_ID),
        "purpose": "run an operator-requested governed parcel audit",
        "config_fingerprint": "a" * 64,
    }
    request = _request(
        body=body,
        headers={
            "x-request-id": "request-1",
            CAPABILITY_FINGERPRINT_HEADER: DATAOPS_MANUAL_RUN_SUBMIT.fingerprint,
        },
    )
    with (
        patch.object(routes, "_get_user_from_request", return_value=_user()),
        patch.object(routes, "_manual_runtime_profile", return_value=profile),
        patch.object(routes, "_gateway", return_value=gateway),
    ):
        response = asyncio.run(routes.create_manual_dataops_run(request))

    assert response.status_code == 202
    response_payload = json.loads(response.body)
    assert response_payload["created"] is True
    assert DATAOPS_MANUAL_RUN_SUBMIT.validate_input(body) == body
    assert DATAOPS_MANUAL_RUN_SUBMIT.validate_output(response_payload["data"])[
        "request_sha256"
    ] == response_payload["data"]["request_sha256"]
    assert response_payload["data"]["invocation"]["schema"] == (
        "gda.dataops_invocation.v1"
    )
    assert "schema_name" not in response_payload["data"]["invocation"]
    spec = gateway.submit_manual_trigger.call_args.args[0]
    assert spec.requester_subject == ACTOR
    assert spec.tenant_id == TENANT
    assert spec.workload_subject_id == "dataops-adapter"
    assert spec.policy_evaluator_subject == "workload:policy-evaluator"


def test_manual_dataops_route_rejects_identity_spoofing_and_workload_callers():
    body = {
        "client_request_id": "operator-console-20260801-001",
        "definition_version_id": str(DEFINITION_ID),
        "logical_start": NOW.isoformat(),
        "logical_end": "2026-07-25T12:00:00+00:00",
        "input_bindings": [],
        "execution_plan_artifact_id": str(PLAN_ID),
        "purpose": "run a governed parcel audit",
        "requester_subject": "human:spoofed-operator",
    }
    request = _request(body=body)
    with patch.object(routes, "_get_user_from_request", return_value=_user()):
        spoofed = asyncio.run(routes.create_manual_dataops_run(request))
    assert spoofed.status_code == 422

    body.pop("requester_subject")
    request = _request(body=body)
    with patch.object(
        routes,
        "_get_user_from_request",
        return_value=_user(subject_type="workload", identifier="dataops-adapter"),
    ):
        workload = asyncio.run(routes.create_manual_dataops_run(request))
    assert workload.status_code == 403
    assert json.loads(workload.body)["error"]["code"] == "human_identity_required"


@pytest.mark.parametrize(
    ("endpoint", "spec", "path"),
    (
        (
            routes.create_manual_dataops_run,
            DATAOPS_MANUAL_RUN_SUBMIT,
            {},
        ),
        (
            routes.create_dataops_cancel,
            DATAOPS_RUN_CANCEL,
            {"run_id": str(RUN_ID)},
        ),
    ),
)
def test_dataops_routes_reject_contract_drift_before_domain_parsing(
    endpoint,
    spec,
    path,
):
    gateway = MagicMock()
    request = _request(
        body={},
        path=path,
        headers={
            "x-request-id": "contract-drift-1",
            CAPABILITY_FINGERPRINT_HEADER: "f" * 64,
        },
    )
    with (
        patch.object(routes, "_get_user_from_request", return_value=_user()),
        patch.object(routes, "_gateway", return_value=gateway),
    ):
        response = asyncio.run(endpoint(request))

    assert response.status_code == 409
    payload = json.loads(response.body)
    assert payload["error"]["code"] == "capability_contract_mismatch"
    assert payload["error"]["details"] == [
        {
            "capability_id": spec.capability_id,
            "version": spec.version,
            "fingerprint": spec.fingerprint,
        }
    ]
    assert gateway.mock_calls == []


def test_dolphinscheduler_callback_requires_workload_and_enqueues_reconcile():
    command = _command()
    gateway = MagicMock()
    gateway.record_attempt_and_enqueue_reconcile.side_effect = lambda observation, **_kwargs: (
        CallbackWriteResult(
            observation=observation,
            command=command,
            observation_created=True,
            command_created=True,
            ignored_terminal=False,
        )
    )
    body = {
        "callback_id": "00000000-0000-4000-8000-000000000060",
        "attempt_no": 1,
        "project_code": 1001,
        "workflow_instance_id": 901,
        "workflow_definition_code": 701,
        "workflow_definition_version": 1,
        "provider_state": "SUCCESS",
        "observed_at": NOW.isoformat(),
    }
    request = _request(body=body, path={"run_id": str(RUN_ID)})
    with patch.object(routes, "_get_user_from_request", return_value=_user()):
        rejected = asyncio.run(routes.create_dolphinscheduler_callback(request))
    assert rejected.status_code == 403

    request = _request(body=body, path={"run_id": str(RUN_ID)})
    with (
        patch.object(
            routes,
            "_get_user_from_request",
            return_value=_user(subject_type="workload", identifier="dataops-adapter"),
        ),
        patch.object(routes, "_gateway", return_value=gateway),
    ):
        response = asyncio.run(routes.create_dolphinscheduler_callback(request))

    assert response.status_code == 202
    observation = gateway.record_attempt_and_enqueue_reconcile.call_args.args[0]
    assert observation.framework_kind.value == "dolphinscheduler"
    assert observation.observation_id == command.trigger_observation_id
    assert observation.observed_state == "success"
    assert gateway.record_attempt_and_enqueue_reconcile.call_args.kwargs == {
        "actor_subject": "workload:dataops-adapter"
    }


def test_dataops_cancel_requires_human_and_derives_governed_identity():
    result = _cancel_result()
    gateway = MagicMock()
    gateway.admit_dataops_cancel.return_value = result
    profile = routes.DataOpsCancelRuntimeProfile(
        workload_subject="workload:dataops-adapter",
        policy_version_ref="gda://tenant-a/policy/dataops-cancel:v1",
        policy_evaluator_subject="workload:policy-evaluator",
    )
    body = {
        "client_request_id": "cancel-console-20260801-001",
        "expected_state_version": 1,
        "reason": "operator cancelled an obsolete source refresh",
    }

    request = _request(body=body, path={"run_id": str(result.run.run_id)})
    with patch.object(
        routes,
        "_get_user_from_request",
        return_value=_user(subject_type="workload", identifier="dataops-adapter"),
    ):
        rejected = asyncio.run(routes.create_dataops_cancel(request))
    assert rejected.status_code == 403

    spoofed_request = _request(
        body={**body, "run_id": str(UUID(int=1))},
        path={"run_id": str(result.run.run_id)},
    )
    with patch.object(routes, "_get_user_from_request", return_value=_user()):
        spoofed = asyncio.run(routes.create_dataops_cancel(spoofed_request))
    assert spoofed.status_code == 422

    request = _request(
        body=body,
        path={"run_id": str(result.run.run_id)},
        headers={
            "x-request-id": "request-1",
            CAPABILITY_FINGERPRINT_HEADER: DATAOPS_RUN_CANCEL.fingerprint,
        },
    )
    with (
        patch.object(routes, "_get_user_from_request", return_value=_user()),
        patch.object(routes, "_cancel_runtime_profile", return_value=profile),
        patch.object(routes, "_gateway", return_value=gateway),
    ):
        response = asyncio.run(routes.create_dataops_cancel(request))

    assert response.status_code == 202
    assert routes.DataOpsCancelRequest is DataOpsCancelRequest
    assert routes.DataOpsCancelResponse is DataOpsCancelResponse
    payload = json.loads(response.body)
    DATAOPS_RUN_CANCEL.validate_output(payload["data"])
    spec = gateway.admit_dataops_cancel.call_args.args[0]
    assert spec.tenant_id == TENANT
    assert spec.requester_subject == ACTOR
    assert spec.workload_subject == "workload:dataops-adapter"
    assert spec.policy_evaluator_subject == "workload:policy-evaluator"


def test_incident_api_lists_attention_queue_and_requires_human_remediation():
    incident = _incident()
    gateway = MagicMock()
    gateway.list_incidents.return_value = (incident,)
    list_request = _request(
        query={"status": "open", "run_id": str(RUN_ID), "limit": "25"}
    )
    with (
        patch.object(routes, "_get_user_from_request", return_value=_user()),
        patch.object(routes, "_gateway", return_value=gateway),
    ):
        listed = asyncio.run(routes.list_data_incidents(list_request))

    assert listed.status_code == 200
    payload = json.loads(listed.body)["data"]
    assert payload["count"] == 1
    assert payload["items"][0]["incident_id"] == str(incident.incident_id)
    assert gateway.list_incidents.call_args.kwargs == {
        "status": IncidentStatus.OPEN,
        "run_id": RUN_ID,
        "limit": 25,
    }

    transition_request = _request(
        body={
            "expected_state_version": 0,
            "to_status": "acknowledged",
            "reason": "operator owns provider remediation",
            "details": {"ticket": "INC-2026-0801-001"},
        },
        path={"incident_id": str(incident.incident_id)},
    )
    with patch.object(
        routes,
        "_get_user_from_request",
        return_value=_user(subject_type="workload", identifier="dataops-adapter"),
    ):
        rejected = asyncio.run(routes.transition_data_incident(transition_request))
    assert rejected.status_code == 403

    acknowledged = _incident(
        status="acknowledged",
        state_version=1,
        updated_at=datetime(2026, 7, 24, 12, 5, tzinfo=UTC),
    )
    gateway.transition_incident.return_value = acknowledged
    transition_request = _request(
        body={
            "expected_state_version": 0,
            "to_status": "acknowledged",
            "reason": "operator owns provider remediation",
            "details": {"ticket": "INC-2026-0801-001"},
        },
        path={"incident_id": str(incident.incident_id)},
    )
    with (
        patch.object(routes, "_get_user_from_request", return_value=_user()),
        patch.object(routes, "_gateway", return_value=gateway),
    ):
        transitioned = asyncio.run(routes.transition_data_incident(transition_request))

    assert transitioned.status_code == 200
    assert json.loads(transitioned.body)["data"]["status"] == "acknowledged"
    assert gateway.transition_incident.call_args.args == (
        TENANT,
        incident.incident_id,
        0,
        IncidentStatus.ACKNOWLEDGED,
        ACTOR,
        "operator owns provider remediation",
        {"ticket": "INC-2026-0801-001"},
    )


def test_quality_result_requires_evaluator_identity_and_preserves_contract():
    quality = _quality()
    gateway = MagicMock()
    gateway.record_quality_result.return_value = GatewayWriteResult(quality, True)
    body = quality.model_dump(mode="json")

    request = _request(body=body)
    with patch.object(routes, "_get_user_from_request", return_value=_user()):
        rejected = asyncio.run(routes.create_quality_result(request))
    assert rejected.status_code == 403

    request = _request(body=body)
    with (
        patch.object(
            routes,
            "_get_user_from_request",
            return_value=_user(subject_type="workload", identifier="quality-evaluator"),
        ),
        patch.object(routes, "_gateway", return_value=gateway),
    ):
        response = asyncio.run(routes.create_quality_result(request))
    assert response.status_code == 201
    assert gateway.record_quality_result.call_args.args == (quality,)


def test_success_finalization_requires_run_workload_and_builds_evidence():
    succeeded = _run().model_copy(update={"status": RunStatus.SUCCEEDED, "state_version": 3})
    gateway = MagicMock()
    gateway.finalize_run_success.return_value = succeeded
    body = {
        "expected_state_version": 2,
        "attempt_observation_id": "00000000-0000-4000-8000-000000000050",
        "output_artifact_id": "00000000-0000-4000-8000-000000000060",
        "quality_result_id": "00000000-0000-4000-8000-000000000090",
        "lineage_event_id": "00000000-0000-4000-8000-000000000070",
        "reason": "all platform success evidence passed",
    }
    request = _request(body=body, path={"run_id": str(RUN_ID)})
    with patch.object(routes, "_get_user_from_request", return_value=_user()):
        rejected = asyncio.run(routes.finalize_run_success(request))
    assert rejected.status_code == 403

    request = _request(body=body, path={"run_id": str(RUN_ID)})
    with (
        patch.object(
            routes,
            "_get_user_from_request",
            return_value=_user(subject_type="workload", identifier="dataops-adapter"),
        ),
        patch.object(routes, "_gateway", return_value=gateway),
    ):
        response = asyncio.run(routes.finalize_run_success(request))
    assert response.status_code == 200
    evidence = gateway.finalize_run_success.call_args.args[0]
    assert evidence.tenant_id == TENANT
    assert evidence.run_id == RUN_ID
    assert gateway.finalize_run_success.call_args.kwargs == {
        "expected_state_version": 2,
        "actor_subject": "workload:dataops-adapter",
        "reason": "all platform success evidence passed",
    }


def test_generic_gateway_transition_cannot_bypass_success_evidence_gate():
    with pytest.raises(GatewayValidationError, match="evidence-gated"):
        PlatformGateway().transition_run(
            TENANT,
            RUN_ID,
            2,
            "succeeded",
            "workload:dataops-adapter",
            "provider said success",
        )


def test_gateway_conflict_has_stable_safe_error_envelope():
    gateway = MagicMock()
    gateway.register_resource.side_effect = GatewayConflictError("identity conflict")
    request = _request(body=_resource().model_dump(mode="json"))
    with (
        patch.object(routes, "_get_user_from_request", return_value=_user()),
        patch.object(routes, "_gateway", return_value=gateway),
    ):
        response = asyncio.run(routes.create_resource(request))

    body = json.loads(response.body)
    assert response.status_code == 409
    assert body["error"]["code"] == "platform_conflict"
    assert body["request_id"] == "request-1"


def test_run_transition_rejects_negative_state_version_at_http_boundary():
    request = _request(
        body={
            "expected_state_version": -1,
            "to_status": "dispatching",
            "reason": "invalid replay cursor",
        },
        path={"run_id": str(RUN_ID)},
    )
    with patch.object(routes, "_get_user_from_request", return_value=_user()):
        response = asyncio.run(routes.create_run_transition(request))

    assert response.status_code == 422
    assert json.loads(response.body)["error"]["code"] == "contract_validation_failed"


def test_transition_api_cannot_bypass_governed_cancel_admission():
    gateway = MagicMock()
    request = _request(
        body={
            "expected_state_version": 2,
            "to_status": "cancelled",
            "reason": "bypass provider cancellation",
        },
        path={"run_id": str(RUN_ID)},
    )
    with (
        patch.object(routes, "_get_user_from_request", return_value=_user()),
        patch.object(routes, "_gateway", return_value=gateway),
    ):
        response = asyncio.run(routes.create_run_transition(request))

    assert response.status_code == 422
    assert json.loads(response.body)["error"]["code"] == "governed_cancel_required"
    gateway.transition_run.assert_not_called()


def test_slo_stage_route_injects_tenant_actor_identity_and_rejects_spoofing():
    authority = MagicMock()
    authority.stage.side_effect = lambda draft: SLODefinitionVersion(
        **draft.model_dump(),
        definition_fingerprint="a" * 64,
    )
    request = _request(
        body=_slo_stage_body(),
        path={"slo_definition_id": SLO_ID},
    )
    with (
        patch.object(routes, "_get_user_from_request", return_value=_user()),
        patch.object(routes, "_slo_authority", return_value=authority),
        patch.object(routes, "_utc_now", return_value=NOW),
    ):
        response = asyncio.run(routes.stage_slo_definition_version(request))

    assert response.status_code == 200
    staged = authority.stage.call_args.args[0]
    assert staged.tenant_id == TENANT
    assert staged.slo_definition_ref == SLO_REF
    assert staged.slo_version_ref == SLO_VERSION_REF
    assert staged.created_by == ACTOR
    assert staged.created_at == NOW

    spoofed_body = _slo_stage_body(
        tenant_id="tenant-b",
        created_by="human:spoofed",
        definition_fingerprint="b" * 64,
    )
    with patch.object(routes, "_get_user_from_request", return_value=_user()):
        rejected = asyncio.run(
            routes.stage_slo_definition_version(
                _request(
                    body=spoofed_body,
                    path={"slo_definition_id": SLO_ID},
                )
            )
        )
    assert rejected.status_code == 422
    assert json.loads(rejected.body)["error"]["code"] == "contract_validation_failed"


def test_slo_version_list_is_tenant_scoped_and_paginated():
    authority = MagicMock()
    authority.list_versions.return_value = SLODefinitionVersionPage(
        items=(_slo_definition(),),
        offset=10,
        limit=10,
        has_more=True,
    )
    request = _request(
        path={"slo_definition_id": SLO_ID},
        query={"limit": "10", "offset": "10"},
    )
    with (
        patch.object(routes, "_get_user_from_request", return_value=_user()),
        patch.object(routes, "_slo_authority", return_value=authority),
    ):
        response = asyncio.run(routes.list_slo_definition_versions(request))

    assert response.status_code == 200
    payload = json.loads(response.body)["data"]
    assert payload["items"][0]["slo_version_ref"] == SLO_VERSION_REF
    assert payload["has_more"] is True
    authority.list_versions.assert_called_once_with(
        TENANT,
        SLO_REF,
        limit=10,
        offset=10,
    )


def test_slo_activation_approval_derives_exact_stored_target_and_fingerprint():
    slo_authority = MagicMock()
    slo_authority.get.return_value = _slo_definition()
    approval_authority = MagicMock()
    approval_authority.create.side_effect = (
        lambda approval_case, **_kwargs: ApprovalCaseWriteResult(approval_case, True)
    )
    request = _request(
        body={
            "case_id": "slo-v1-activation",
            "request_reason": "service owner review for the candidate objective",
            "expires_in_hours": 48,
        },
        path={"slo_definition_id": SLO_ID, "version": "1"},
    )
    with (
        patch.object(routes, "_get_user_from_request", return_value=_user()),
        patch.object(routes, "_slo_authority", return_value=slo_authority),
        patch.object(
            routes,
            "_approval_case_authority",
            return_value=approval_authority,
        ),
        patch.object(routes, "_utc_now", return_value=NOW),
    ):
        response = asyncio.run(routes.create_slo_activation_approval_case(request))

    assert response.status_code == 201
    approval_case = approval_authority.create.call_args.args[0]
    assert approval_case.tenant_id == TENANT
    assert approval_case.requester_subject == ACTOR
    assert approval_case.target_resource_urn == SLO_VERSION_REF
    assert approval_case.target_fingerprint == "a" * 64
    assert approval_case.action == "slo_definition.activate"
    assert approval_case.request_context["definition_fingerprint"] == "a" * 64
    assert approval_case.requested_at == NOW
    assert approval_case.expires_at == NOW + timedelta(hours=48)


def test_slo_activation_is_admin_only_and_uses_database_version_fingerprint():
    authority = MagicMock()
    authority.get.return_value = _slo_definition()
    authority.activate.return_value = _slo_activation()
    body = {
        "approval_case_id": "slo-v1-activation",
        "expected_activation_version": 0,
        "reason": "activate the independently approved objective",
    }
    path = {"slo_definition_id": SLO_ID, "version": "1"}
    with (
        patch.object(routes, "_get_user_from_request", return_value=_user()),
        patch.object(routes, "_slo_authority", return_value=authority),
    ):
        forbidden = asyncio.run(
            routes.activate_slo_definition_version(_request(body=body, path=path))
        )
    assert forbidden.status_code == 403
    assert json.loads(forbidden.body)["error"]["code"] == (
        "slo_activation_admin_required"
    )
    authority.get.assert_not_called()

    with (
        patch.object(
            routes,
            "_get_user_from_request",
            return_value=_user(role="admin", identifier="platform-admin"),
        ),
        patch.object(routes, "_slo_authority", return_value=authority),
    ):
        response = asyncio.run(
            routes.activate_slo_definition_version(_request(body=body, path=path))
        )

    assert response.status_code == 200
    assert authority.activate.call_args.kwargs == {
        "tenant_id": TENANT,
        "slo_version_ref": SLO_VERSION_REF,
        "definition_fingerprint": "a" * 64,
        "approval_case_ref": f"gda://{TENANT}/approval_case/slo-v1-activation",
        "expected_activation_version": 0,
        "actor_subject": "human:platform-admin",
        "reason": "activate the independently approved objective",
    }


def test_slo_rule_preview_fails_closed_for_candidate_and_compiles_active_version():
    active_definition = _slo_definition()
    activation = _slo_activation()
    candidate = _slo_definition(
        slo_version_ref=f"{SLO_REF}.v2",
        version=2,
        definition_fingerprint="b" * 64,
    )
    authority = MagicMock()
    authority.get.return_value = candidate
    authority.active.return_value = (active_definition, activation)
    path = {"slo_definition_id": SLO_ID, "version": "2"}
    with (
        patch.object(routes, "_get_user_from_request", return_value=_user()),
        patch.object(routes, "_slo_authority", return_value=authority),
    ):
        rejected = asyncio.run(
            routes.preview_slo_prometheus_rules(_request(path=path))
        )
    assert rejected.status_code == 409
    assert json.loads(rejected.body)["error"]["code"] == "slo_version_not_active"

    authority.get.return_value = active_definition
    path["version"] = "1"
    with (
        patch.object(routes, "_get_user_from_request", return_value=_user()),
        patch.object(routes, "_slo_authority", return_value=authority),
    ):
        response = asyncio.run(
            routes.preview_slo_prometheus_rules(_request(path=path))
        )
    assert response.status_code == 200
    payload = json.loads(response.body)["data"]
    assert payload["definition"]["definition_fingerprint"] == "a" * 64
    assert payload["activation"]["activation_version"] == 1
    assert payload["prometheus_rules"]["groups"][0]["name"].endswith("-v1")


def test_slo_active_pointer_and_events_are_tenant_scoped():
    definition = _slo_definition()
    activation = _slo_activation()
    event = SLODefinitionEvent(
        tenant_id=TENANT,
        slo_event_id=UUID("00000000-0000-4000-8000-0000000000c0"),
        slo_definition_ref=SLO_REF,
        slo_version_ref=SLO_VERSION_REF,
        definition_fingerprint="a" * 64,
        event_type="activated",
        approval_case_ref=activation.approval_case_ref,
        actor_subject="human:platform-admin",
        reason="activate the independently approved objective",
        occurred_at=NOW,
    )
    authority = MagicMock()
    authority.active.return_value = (definition, activation)
    authority.events.return_value = (event,)
    path = {"slo_definition_id": SLO_ID}
    with (
        patch.object(routes, "_get_user_from_request", return_value=_user()),
        patch.object(routes, "_slo_authority", return_value=authority),
    ):
        active_response = asyncio.run(
            routes.get_active_slo_definition(_request(path=path))
        )
        events_response = asyncio.run(
            routes.list_slo_definition_events(_request(path=path))
        )

    assert active_response.status_code == 200
    assert json.loads(active_response.body)["data"]["definition"][
        "slo_version_ref"
    ] == SLO_VERSION_REF
    assert json.loads(events_response.body)["data"]["count"] == 1
    authority.active.assert_called_once_with(TENANT, SLO_REF)
    authority.events.assert_called_once_with(TENANT, SLO_REF)


@pytest.mark.parametrize(
    ("error", "status"),
    (
        (SLOConflictError("conflict"), 409),
        (SLONotFoundError("missing"), 404),
        (SLOForbiddenError("forbidden"), 403),
        (SLOValidationError("invalid"), 422),
        (SLOConfigurationError("unavailable"), 503),
        (SLOAuthorityError("failed"), 500),
    ),
)
def test_slo_authority_errors_map_to_stable_http_status(error, status):
    response = routes._slo_error(_request(), error)

    assert response.status_code == status
    assert json.loads(response.body)["error"]["code"] == error.code


def test_slo_alert_webhook_requires_the_configured_workload_and_injects_tenant():
    body = _slo_webhook_body()
    with patch.object(routes, "_get_user_from_request", return_value=_user()):
        human = asyncio.run(
            routes.reconcile_slo_alertmanager_webhook(_request(body=body))
        )
    assert human.status_code == 403
    assert json.loads(human.body)["error"]["code"] == "slo_alert_workload_required"

    reconciler = MagicMock()
    workload = _user(
        subject_type="workload",
        identifier="other-ingestor",
    )
    with (
        patch.object(routes, "_get_user_from_request", return_value=workload),
        patch.object(
            routes,
            "_slo_alert_detector_subject",
            return_value="workload:slo-alert-ingestor",
        ),
        patch.object(routes, "_slo_incident_reconciler", return_value=reconciler),
    ):
        mismatch = asyncio.run(
            routes.reconcile_slo_alertmanager_webhook(_request(body=body))
        )
    assert mismatch.status_code == 403
    assert json.loads(mismatch.body)["error"]["code"] == "slo_alert_detector_mismatch"
    reconciler.reconcile.assert_not_called()

    accepted_workload = _user(
        subject_type="workload",
        identifier="slo-alert-ingestor",
    )
    reconciler.reconcile.return_value = SLOAlertReconciliationResult(
        tenant_id=TENANT,
        items=(),
        created_count=0,
        resolved_count=0,
        unchanged_count=0,
    )
    with (
        patch.object(
            routes,
            "_get_user_from_request",
            return_value=accepted_workload,
        ),
        patch.object(
            routes,
            "_slo_alert_detector_subject",
            return_value="workload:slo-alert-ingestor",
        ),
        patch.object(routes, "_slo_incident_reconciler", return_value=reconciler),
    ):
        response = asyncio.run(
            routes.reconcile_slo_alertmanager_webhook(_request(body=body))
        )
    assert response.status_code == 200
    args = reconciler.reconcile.call_args
    assert args.args[0] == TENANT
    assert args.kwargs == {"detector_subject": "workload:slo-alert-ingestor"}


def test_slo_alert_webhook_maps_configuration_and_authority_validation_errors():
    workload = _user(
        subject_type="workload",
        identifier="slo-alert-ingestor",
    )
    with (
        patch.object(routes, "_get_user_from_request", return_value=workload),
        patch.object(
            routes,
            "_slo_alert_detector_subject",
            side_effect=GatewayConfigurationError("detector is not configured"),
        ),
    ):
        unavailable = asyncio.run(
            routes.reconcile_slo_alertmanager_webhook(
                _request(body=_slo_webhook_body())
            )
        )
    assert unavailable.status_code == 503

    reconciler = MagicMock()
    reconciler.reconcile.side_effect = SLOIncidentValidationError(
        "alert fingerprint does not match authority"
    )
    with (
        patch.object(routes, "_get_user_from_request", return_value=workload),
        patch.object(
            routes,
            "_slo_alert_detector_subject",
            return_value="workload:slo-alert-ingestor",
        ),
        patch.object(routes, "_slo_incident_reconciler", return_value=reconciler),
    ):
        rejected = asyncio.run(
            routes.reconcile_slo_alertmanager_webhook(
                _request(body=_slo_webhook_body())
            )
        )
    assert rejected.status_code == 422
    assert json.loads(rejected.body)["error"]["code"] == (
        "slo_alert_validation_failed"
    )


def test_platform_gateway_routes_are_versioned_and_registered():
    registered = routes.get_platform_gateway_routes()
    assert len(registered) == 113
    assert all(route.path.startswith("/api/platform/v1/") for route in registered)
    assert len({route.operation_id for route in registered}) == 113
    assert "platform_schedule_approval_case_batch_escalation" in {
        route.operation_id for route in registered
    }
    assert "platform_create_data_product_blueprint" in {
        route.operation_id for route in registered
    }
    assert "platform_preview_data_product_blueprint" in {
        route.operation_id for route in registered
    }
    assert "platform_admit_data_product_blueprint_test_run" in {
        route.operation_id for route in registered
    }
    assert "platform_execute_data_product_blueprint_test_run" in {
        route.operation_id for route in registered
    }
    assert "platform_execute_data_product_blueprint_duckdb_test_run" in {
        route.operation_id for route in registered
    }
    assert "platform_fail_data_product_blueprint_test_run" in {
        route.operation_id for route in registered
    }
    assert "platform_cancel_data_product_blueprint_test_run" in {
        route.operation_id for route in registered
    }
    assert "platform_reconcile_data_product_blueprint_test_provider" in {
        route.operation_id for route in registered
    }
    assert "platform_record_data_product_blueprint_provider_cancellation_timeout" in {
        route.operation_id for route in registered
    }
    assert "platform_retry_data_product_blueprint_test_provider" in {
        route.operation_id for route in registered
    }
    assert "platform_test_data_product_blueprint" in {
        route.operation_id for route in registered
    }
    assert "platform_create_data_product_blueprint_review" in {
        route.operation_id for route in registered
    }
    assert "platform_publish_data_product_blueprint_release" in {
        route.operation_id for route in registered
    }
    assert "platform_get_gis_service_control_projection" in {
        route.operation_id for route in registered
    }
    assert "platform_get_gis_ogc_api_features_items" in {
        route.operation_id for route in registered
    }
    assert "platform_activate_gis_service_endpoint" in {
        route.operation_id for route in registered
    }
    assert "platform_get_gis_service_deployment" in {
        route.operation_id for route in registered
    }
    assert "platform_list_gis_service_deployment_events" in {
        route.operation_id for route in registered
    }
    assert "platform_record_gis_service_deployment_observation" in {
        route.operation_id for route in registered
    }
    assert "platform_settle_gis_service_deployment_terminal" in {
        route.operation_id for route in registered
    }
    assert "platform_register_gis_service_deployment" in {
        route.operation_id for route in registered
    }
    assert "platform_transition_gis_service_deployment" in {
        route.operation_id for route in registered
    }
    assert "platform_register_gis_service_endpoint" in {
        route.operation_id for route in registered
    }
    assert "platform_create_resource_version_postgis_architecture_assessment" in {
        route.operation_id for route in registered
    }
    assert (
        "platform_create_resource_version_architecture_successor_adoption_approval"
        in {route.operation_id for route in registered}
    )
    assert "platform_adopt_resource_version_architecture_successor" in {
        route.operation_id for route in registered
    }
    assert (
        "platform_create_architecture_successor_data_product_release_approval"
        in {route.operation_id for route in registered}
    )
    assert "platform_publish_architecture_successor_data_product_release" in {
        route.operation_id for route in registered
    }
    assert "platform_ingest_entity_authority_batch" in {
        route.operation_id for route in registered
    }
    assert "platform_record_entity_lineage_event" in {
        route.operation_id for route in registered
    }
    assert "platform_generate_federated_compensation_proposal" in {
        route.operation_id for route in registered
    }
    assert "platform_get_federated_compensation_proposal" in {
        route.operation_id for route in registered
    }
    assert "platform_assess_federated_compensation_rules" in {
        route.operation_id for route in registered
    }
    assert "platform_assess_persisted_federated_compensation_rules" in {
        route.operation_id for route in registered
    }
    assert "platform_request_federated_compensation_approval" in {
        route.operation_id for route in registered
    }
    assert (
        "platform_request_federated_compensation_execution_approval"
        in {route.operation_id for route in registered}
    )
    assert "platform_search_metadata_fabric_bindings" in {
        route.operation_id for route in registered
    }
    assert "platform_read_metadata_fabric_provider" in {
        route.operation_id for route in registered
    }
    assert "platform_search_metadata_fabric_provider" in {
        route.operation_id for route in registered
    }

    from data_agent.frontend_api import get_frontend_api_routes

    mounted = {route.path for route in get_frontend_api_routes()}
    assert {route.path for route in registered}.issubset(mounted)


def test_platform_gateway_routes_are_visible_in_openapi():
    from fastapi import FastAPI

    app = FastAPI()
    app.router.routes.extend(routes.get_platform_gateway_routes())

    schema = app.openapi()
    operations = {
        operation["operationId"]
        for path, path_item in schema["paths"].items()
        if path.startswith("/api/platform/v1/")
        for method, operation in path_item.items()
        if method in {"get", "post", "put", "patch", "delete"}
    }
    assert len(operations) == 113
    assert "platform_create_data_product_blueprint" in operations
    assert "platform_preview_data_product_blueprint" in operations
    assert "platform_test_data_product_blueprint" in operations
    assert "platform_execute_data_product_blueprint_test_run" in operations
    assert "platform_execute_data_product_blueprint_duckdb_test_run" in operations
    assert "platform_fail_data_product_blueprint_test_run" in operations
    assert "platform_cancel_data_product_blueprint_test_run" in operations
    assert "platform_reconcile_data_product_blueprint_test_provider" in operations
    assert "platform_record_data_product_blueprint_provider_cancellation_timeout" in operations
    assert "platform_retry_data_product_blueprint_test_provider" in operations
    assert "platform_create_data_product_blueprint_review" in operations
    assert "platform_publish_data_product_blueprint_release" in operations
    assert "platform_get_gis_service_control_projection" in operations
    assert "platform_get_gis_ogc_api_features_items" in operations
    assert "platform_activate_gis_service_endpoint" in operations
    assert "platform_get_gis_service_deployment" in operations
    assert "platform_list_gis_service_deployment_events" in operations
    assert "platform_record_gis_service_deployment_observation" in operations
    assert "platform_settle_gis_service_deployment_terminal" in operations
    assert "platform_register_gis_service_deployment" in operations
    assert "platform_transition_gis_service_deployment" in operations
    assert "platform_register_gis_service_endpoint" in operations
    assert "platform_ingest_entity_authority_batch" in operations
    assert "platform_record_entity_lineage_event" in operations
    assert "platform_generate_federated_compensation_proposal" in operations
    assert "platform_get_federated_compensation_proposal" in operations
    assert "platform_assess_federated_compensation_rules" in operations
    assert "platform_assess_persisted_federated_compensation_rules" in operations
    assert "platform_request_federated_compensation_approval" in operations
    assert (
        "platform_request_federated_compensation_execution_approval"
        in operations
    )
    assert "platform_cancel_run" in operations
    assert "platform_list_data_incidents" in operations
    assert "platform_list_incident_notifications" in operations
    assert "platform_list_incident_notification_recoveries" in operations
    assert "platform_recover_incident_notification" in operations
    assert "platform_transition_data_incident" in operations
    assert "platform_create_approval_case" in operations
    assert "platform_list_approval_cases" in operations
    assert "platform_get_approval_case" in operations
    assert "platform_list_approval_case_events" in operations
    assert "platform_list_approval_case_notifications" in operations
    assert "platform_retry_approval_case_notification" in operations
    assert "platform_get_approval_case_assignment" in operations
    assert "platform_transition_approval_case_assignment" in operations
    assert "platform_list_approval_principals" in operations
    assert "platform_upsert_approval_principal" in operations
    assert "platform_upsert_approval_team_membership" in operations
    assert "platform_list_approval_team_memberships" in operations
    assert "platform_decide_approval_case" in operations
    assert "platform_list_resource_versions" in operations
    assert "platform_get_postgresql_cdc_recovery_observation" in operations
    assert "platform_get_resource_version_lineage" in operations
    assert "platform_get_resource_version_impact" in operations
    assert "platform_get_resource_version_architecture" in operations
    assert "platform_get_resource_version_architecture_reconciliation" in operations
    assert "platform_create_resource_version_architecture_review" in operations
    assert "platform_create_resource_version_postgis_architecture_assessment" in operations
    assert (
        "platform_create_resource_version_architecture_successor_adoption_approval"
        in operations
    )
    assert "platform_adopt_resource_version_architecture_successor" in operations
    assert (
        "platform_create_architecture_successor_data_product_release_approval"
        in operations
    )
    assert "platform_publish_architecture_successor_data_product_release" in operations
    assert "platform_create_openlineage_event" in operations
    assert "platform_create_metadata_fabric_binding" in operations
    assert "platform_list_metadata_fabric_bindings" in operations
    assert "platform_search_metadata_fabric_bindings" in operations
    assert "platform_read_metadata_fabric_provider" in operations
    assert "platform_search_metadata_fabric_provider" in operations
    assert "platform_stage_slo_definition_version" in operations
    assert "platform_list_slo_definition_versions" in operations
    assert "platform_create_slo_activation_approval_case" in operations
    assert "platform_activate_slo_definition_version" in operations
    assert "platform_get_active_slo_definition" in operations
    assert "platform_preview_slo_prometheus_rules" in operations
    assert "platform_list_slo_definition_events" in operations
    assert "platform_reconcile_slo_alertmanager_webhook" in operations
    assert "platform_observe_master_source_record" in operations
    assert "platform_propose_master_source_matches" in operations
    assert "platform_stage_master_entity_version" in operations
    assert "platform_list_master_entity_versions" in operations
    assert "platform_create_master_activation_approval_case" in operations
    assert "platform_activate_master_entity_version" in operations
    assert "platform_get_active_master_entity" in operations
    assert "platform_list_master_data_events" in operations
    assert "platform_list_master_resource_projections" in operations
    assert schema["paths"]["/api/platform/v1/runs/{run_id}/cancel"]["post"][
        "security"
    ] == [{"OAuth2PasswordBearerWithCookie": []}]
    assert schema["paths"][
        "/api/platform/v1/recovery-observations/{artifact_id}"
    ]["get"]["security"] == [{"OAuth2PasswordBearerWithCookie": []}]
    assert schema["paths"][
        "/api/platform/v1/resource-versions/{resource_version_id}/architecture"
    ]["get"]["security"] == [{"OAuth2PasswordBearerWithCookie": []}]
    assert schema["paths"][
        "/api/platform/v1/resource-versions/{resource_version_id}/architecture/reconciliation/approval-cases"
    ]["post"]["security"] == [{"OAuth2PasswordBearerWithCookie": []}]
    assert schema["paths"]["/api/platform/v1/approval-cases"]["get"][
        "security"
    ] == [{"OAuth2PasswordBearerWithCookie": []}]
    assert schema["paths"][
        "/api/platform/v1/approval-cases/{case_id}/notifications"
    ]["get"]["security"] == [{"OAuth2PasswordBearerWithCookie": []}]
    assert schema["paths"][
        "/api/platform/v1/approval-cases/{case_id}/notifications/{notification_id}/retry"
    ]["post"]["security"] == [{"OAuth2PasswordBearerWithCookie": []}]
    assert schema["paths"][
        "/api/platform/v1/approval-cases/{case_id}/assignment"
    ]["post"]["security"] == [{"OAuth2PasswordBearerWithCookie": []}]
    assert schema["paths"][
        "/api/platform/v1/incidents/{incident_id}/notifications"
    ]["get"]["security"] == [{"OAuth2PasswordBearerWithCookie": []}]
    assert schema["paths"][
        "/api/platform/v1/incidents/{incident_id}/notifications/{notification_id}/recoveries"
    ]["get"]["security"] == [{"OAuth2PasswordBearerWithCookie": []}]
    assert schema["paths"][
        "/api/platform/v1/incidents/{incident_id}/notifications/{notification_id}/recoveries"
    ]["post"]["security"] == [{"OAuth2PasswordBearerWithCookie": []}]


def test_platform_gateway_static_contract_and_fail_closed_role(tmp_path):
    report = build_gateway_report()
    assert report["status"] == "valid"
    assert report["database_role"] == "gda_control_gateway"
    assert report["route_count"] == 29
    assert report["files"]["master_data_migration"]["sha256"]
    assert report["files"]["master_resource_projection_migration"]["sha256"]
    assert report["files"]["master_metadata_projection_migration"]["sha256"]
    assert report["files"]["master_metadata_worker_source"]["sha256"]
    assert report["files"]["run_event_delivery_migration"]["sha256"]
    assert report["files"]["run_event_delivery_worker_source"]["sha256"]
    assert report["files"]["gis_service_endpoint_warmup_command_migration"]["sha256"]
    assert report["files"]["gis_service_endpoint_warmup_consumer_source"]["sha256"]
    assert report["files"]["gis_service_endpoint_warmup_worker_source"]["sha256"]
    assert report["files"]["gis_service_slo_binding_migration"]["sha256"]
    assert report["files"]["gis_service_slo_reconciliation_migration"]["sha256"]
    assert report["files"]["gis_service_slo_incident_migration"]["sha256"]
    assert report["files"]["jqdltb_serving_endpoint_promotion_migration"]["sha256"]
    assert report["files"]["mvt_serving_relation_attestation_migration"]["sha256"]
    assert report["files"]["ogc_api_features_endpoint_contract_migration"]["sha256"]
    assert report["files"]["gis_service_slo_reconciliation_worker_source"]["sha256"]

    unsafe = tmp_path / "unsafe_gateway.sql"
    unsafe.write_text(
        GATEWAY_ROLE_MIGRATION.read_text(encoding="utf-8").replace("NOBYPASSRLS", "BYPASSRLS"),
        encoding="utf-8",
    )
    unsafe_report = build_gateway_report(role_migration=unsafe)
    assert unsafe_report["status"] == "invalid"
    assert "role_migration" in unsafe_report["missing_markers"]

    unsafe_command = tmp_path / "unsafe_command.sql"
    unsafe_command.write_text(
        COMMAND_OUTBOX_MIGRATION.read_text(encoding="utf-8").replace(
            "FOR UPDATE SKIP LOCKED", "FOR UPDATE"
        ),
        encoding="utf-8",
    )
    unsafe_report = build_gateway_report(command_migration=unsafe_command)
    assert unsafe_report["status"] == "invalid"
    assert "command_migration" in unsafe_report["missing_markers"]

    unsafe_warmup_command = tmp_path / "unsafe_warmup_command.sql"
    unsafe_warmup_command.write_text(
        GIS_SERVICE_ENDPOINT_WARMUP_COMMAND_MIGRATION.read_text(
            encoding="utf-8"
        ).replace(
            "finalize_gis_service_endpoint_warmup_success(",
            "finalize_unbound_warmup_success(",
        ),
        encoding="utf-8",
    )
    unsafe_report = build_gateway_report(
        gis_service_endpoint_warmup_command_migration=unsafe_warmup_command
    )
    assert unsafe_report["status"] == "invalid"
    assert (
        "gis_service_endpoint_warmup_command_migration"
        in unsafe_report["missing_markers"]
    )

    unsafe_warmup_consumer = tmp_path / "unsafe_warmup_consumer.py"
    warmup_consumer_source = Path(
        report["files"]["gis_service_endpoint_warmup_consumer_source"]["path"]
    )
    unsafe_warmup_consumer.write_text(
        warmup_consumer_source.read_text(encoding="utf-8").replace(
            "get_object_lock_configuration",
            "get_unretained_object_configuration",
        ),
        encoding="utf-8",
    )
    unsafe_report = build_gateway_report(
        gis_service_endpoint_warmup_consumer_source=unsafe_warmup_consumer
    )
    assert unsafe_report["status"] == "invalid"
    assert (
        "gis_service_endpoint_warmup_consumer_source"
        in unsafe_report["missing_markers"]
    )

    unsafe_projection = tmp_path / "unsafe_master_projection.sql"
    unsafe_projection.write_text(
        MASTER_RESOURCE_PROJECTION_MIGRATION.read_text(encoding="utf-8").replace(
            "GRANT SELECT ON TABLE gda_control.master_resource_projection",
            "GRANT UPDATE ON TABLE gda_control.master_resource_projection",
        ),
        encoding="utf-8",
    )
    unsafe_report = build_gateway_report(
        master_resource_projection_migration=unsafe_projection
    )
    assert unsafe_report["status"] == "invalid"
    assert "master_resource_projection_migration" in unsafe_report["missing_markers"]

    unsafe_master_metadata = tmp_path / "unsafe_master_metadata.sql"
    unsafe_master_metadata.write_text(
        MASTER_METADATA_PROJECTION_MIGRATION.read_text(encoding="utf-8").replace(
            "GRANT SELECT ON TABLE gda_control.master_metadata_projection_outbox",
            "GRANT UPDATE ON TABLE gda_control.master_metadata_projection_outbox",
        ),
        encoding="utf-8",
    )
    unsafe_report = build_gateway_report(
        master_metadata_projection_migration=unsafe_master_metadata
    )
    assert unsafe_report["status"] == "invalid"
    assert "master_metadata_projection_migration" in unsafe_report["missing_markers"]
