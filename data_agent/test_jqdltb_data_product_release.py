from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from pydantic import ValidationError

from data_agent.data_product_registry import DataProductSpec
from data_agent.jqdltb_data_product_release import (
    JQDLTB_PRODUCT_RELEASE_ACTION,
    JqdltbDataProductReleasePlan,
    JqdltbDataProductReleaseService,
    JqdltbReleaseOperatingContract,
    build_jqdltb_data_product_release_plan,
)
from data_agent.jqdltb_transformation_executor import JqdltbTransformationResult
from data_agent.platform_contracts import (
    ApprovalCase,
    ApprovalCaseStatus,
    Artifact,
    ArtifactRole,
    JqdltbDecision,
    JqdltbDecisionEvidence,
    JqdltbDecisionIdentity,
    LineageEvent,
    LineageEventType,
    QualityResult,
    RunStatus,
    build_jqdltb_decision_packet,
    canonical_json_fingerprint,
    compile_jqdltb_executable_contract,
    quality_result_fingerprint,
)
from data_agent.test_jqdltb_transformation_executor import (
    NOW,
    RUN_ID,
    SOURCE_ID,
    _approved,
    _Gateway,
    _proposal,
)

OUTPUT_VERSION_ID = UUID("d2000000-0000-4000-8000-000000000001")
OUTPUT_ARTIFACT_ID = UUID("d2000000-0000-4000-8000-000000000002")
QUALITY_RESULT_ID = UUID("d2000000-0000-4000-8000-000000000003")
QUALITY_EVIDENCE_ID = UUID("d2000000-0000-4000-8000-000000000004")
LINEAGE_EVENT_ID = UUID("d2000000-0000-4000-8000-000000000005")
BACKUP_EVIDENCE_ID = UUID("d2000000-0000-4000-8000-000000000006")


class _Authority:
    def __init__(self) -> None:
        self.cases: dict[str, ApprovalCase] = {}

    def create(self, case: ApprovalCase, *, owner_ref: str):
        assert owner_ref == "team:cq-land-data"
        self.cases[case.approval_case_ref] = case
        return SimpleNamespace(approval_case=case, created=True)

    def get(self, tenant_id: str, approval_case_ref: str) -> ApprovalCase:
        case = self.cases[approval_case_ref]
        assert case.tenant_id == tenant_id
        return case


def _layers() -> dict[str, dict[str, object]]:
    counts = {
        "raw": 3,
        "ods": 2,
        "dim": 2,
        "dwd": 2,
        "ads": 2,
        "quarantine": 1,
    }
    return {
        name: {
            "relative_path": f"{name}/jqdltb.json",
            "records": count,
            "sha256": canonical_json_fingerprint({"layer": name, "records": count}),
        }
        for name, count in counts.items()
    }


def _facts():
    proposal = _proposal(semantic_candidate_audit_sha256="a" * 64)
    transform_case = _approved(proposal)
    contract = compile_jqdltb_executable_contract(
        proposal,
        approval_case=transform_case,
        created_by="workload:ar0-contract-compiler",
        created_at=datetime(2026, 8, 23, 3, tzinfo=UTC),
    )
    run = _Gateway().run.model_copy(update={"status": RunStatus.SUCCEEDED, "state_version": 4})
    result = JqdltbTransformationResult(
        status="completed",
        run_id=RUN_ID,
        source_resource_version_id=SOURCE_ID,
        output_resource_version_id=OUTPUT_VERSION_ID,
        output_artifact_id=OUTPUT_ARTIFACT_ID,
        quality_result_id=QUALITY_RESULT_ID,
        lineage_event_id=LINEAGE_EVENT_ID,
        output_root="/var/lib/gda/jqdltb/candidate",
        records_read=3,
        records_materialized=2,
        records_quarantined=1,
        quality_verdict="passed",
    )
    layers = _layers()
    bundle_sha = canonical_json_fingerprint(layers)
    output = Artifact(
        tenant_id="local-dev",
        artifact_id=OUTPUT_ARTIFACT_ID,
        artifact_key="cq_jqdltb_layers_d10000000000",
        artifact_role=ArtifactRole.OUTPUT,
        storage_uri="s3://gda-products/jqdltb/v1/layer-manifest.json",
        media_type="application/vnd.gda.immutable-object-bundle+json",
        content_sha256=bundle_sha,
        size_bytes=1024,
        run_id=RUN_ID,
        resource_version_id=OUTPUT_VERSION_ID,
        manifest={
            "schema": "gda.jqdltb_transformation_executor.v1",
            "layers": layers,
            "bundle_sha256": bundle_sha,
        },
        created_by="workload:dolphinscheduler-gda-dataops",
        created_at=NOW,
    )
    quality_evidence = Artifact(
        tenant_id="local-dev",
        artifact_id=QUALITY_EVIDENCE_ID,
        artifact_key="cq_jqdltb_quality_d10000000000",
        artifact_role=ArtifactRole.EVIDENCE,
        storage_uri="s3://gda-evidence/jqdltb/v1/quality.json",
        media_type="application/vnd.gda.jqdltb-transformation-evidence+json",
        content_sha256="a" * 64,
        size_bytes=512,
        run_id=RUN_ID,
        resource_version_id=OUTPUT_VERSION_ID,
        manifest={"schema": "gda.jqdltb_transformation_evidence.v1"},
        created_by="workload:jqdltb-transformation-quality-evaluator",
        created_at=NOW,
    )
    quality_values = {
        "tenant_id": "local-dev",
        "quality_result_id": QUALITY_RESULT_ID,
        "run_id": RUN_ID,
        "resource_version_id": OUTPUT_VERSION_ID,
        "rule_version_ref": "gda://local-dev/quality_rule/chongqing-jqdltb-transformation:v1",
        "verdict": "passed",
        "metrics": {"verdict": "passed", "records_materialized": 2},
        "evidence_artifact_id": QUALITY_EVIDENCE_ID,
        "evaluated_by": "workload:jqdltb-transformation-quality-evaluator",
        "evaluated_at": NOW,
    }
    quality = QualityResult(
        **quality_values,
        result_sha256=quality_result_fingerprint(
            **{key: value for key, value in quality_values.items() if key != "quality_result_id"}
        ),
    )
    lineage = LineageEvent(
        tenant_id="local-dev",
        lineage_event_id=LINEAGE_EVENT_ID,
        event_type=LineageEventType.COPY,
        source_resource_version_id=SOURCE_ID,
        target_resource_version_id=OUTPUT_VERSION_ID,
        producer="workload:dolphinscheduler-gda-dataops",
        event_sha256=canonical_json_fingerprint(
            {"source": str(SOURCE_ID), "target": str(OUTPUT_VERSION_ID)}
        ),
        run_id=RUN_ID,
        definition_version_id=run.definition_version_id,
        artifact_id=OUTPUT_ARTIFACT_ID,
        facets={"layers": layers},
        occurred_at=NOW,
    )
    backup = Artifact(
        tenant_id="local-dev",
        artifact_id=BACKUP_EVIDENCE_ID,
        artifact_key="jqdltb_backup_restore_v1",
        artifact_role=ArtifactRole.EVIDENCE,
        storage_uri="s3://gda-evidence/jqdltb/v1/restore.json",
        media_type="application/json",
        content_sha256="b" * 64,
        size_bytes=256,
        manifest={"schema": "gda.recovery.rehearsal.v1", "passed": True},
        created_by="workload:recovery-controller",
        created_at=NOW,
    )
    operating = JqdltbReleaseOperatingContract(
        tenant_id="local-dev",
        environment="development",
        business_steward_ref="team:cq-land-data",
        license_id="internal-evaluation-approved",
        data_slo_ref="gda://local-dev/data_slo/jqdltb-v1",
        service_slo_ref="gda://local-dev/service_slo/jqdltb-v1",
        on_call_ref="team:data-platform-on-call",
        environment_owner_ref="team:platform-runtime",
        deployment_profile_ref="gda://local-dev/deployment_profile/main-compose-dev",
        backup_restore_evidence_artifact_id=BACKUP_EVIDENCE_ID,
    )
    product = DataProductSpec(
        tenant_id="local-dev",
        product_urn="gda://local-dev/data_product/chongqing-bizhu-jqdltb",
        product_slug="chongqing-bizhu-jqdltb",
        title="Chongqing Bizhu JQDLTB",
        description="Governed current parcel product",
        domain="natural-resources",
        owner_ref=operating.business_steward_ref,
        governance_ref={
            "classification": "internal",
            "visibility": "private",
            "license_id": operating.license_id,
            "attribution": "Chongqing Bizhu data steward",
        },
        created_at=NOW,
    )
    return {
        "product": product,
        "version_key": "v1.0.0",
        "predecessor_version_id": None,
        "run": run,
        "transformation_contract": contract,
        "transformation_result": result,
        "output_artifact": output,
        "quality_result": quality,
        "quality_evidence_artifact": quality_evidence,
        "lineage_event": lineage,
        "operating_contract": operating,
        "backup_restore_evidence_artifact": backup,
        "published_by": "workload:data-product-controller",
        "published_at": NOW + timedelta(hours=2),
    }


def _packet_for_contract(contract, operating: JqdltbReleaseOperatingContract):
    identity = JqdltbDecisionIdentity(
        source_resource_version_id=contract.source_resource_version_id,
        archive_sha256=contract.archive_sha256,
        bundle_sha256=contract.bundle_sha256,
        standard_version_ref=contract.standard_version_ref,
        standard_fingerprint=contract.standard_fingerprint,
        diagnostic_sha256=contract.diagnostic_sha256,
        semantic_candidate_audit_sha256=contract.semantic_candidate_audit_sha256,
    )
    evidence = JqdltbDecisionEvidence(
        evidence_ref="fixture:jqdltb-business-evidence",
        evidence_sha256="b" * 64,
        digest_kind="canonical_json_sha256",
        extraction_method="canonical_json_fingerprint(fixture)",
        identity=identity,
    )
    values = {
        "canonical_key": contract.canonical_key,
        "nonpositive_area_policy": contract.nonpositive_area_policy.value,
        "area_deviation_policy": contract.area_deviation_policy.value,
        "SJNF": "2025",
        "MSSM": "01",
        "business_steward": operating.business_steward_ref,
        "license_status": operating.license_id,
        "slo_on_call": operating.on_call_ref,
        "environment_owner.staging": operating.environment_owner_ref,
        "environment_owner.production": operating.environment_owner_ref,
    }
    derivations = {
        item.target_field: item for item in contract.derivation_contracts
    }
    decisions = []
    for target, selected_value in values.items():
        kwargs = {
            "target": target,
            "status": "submitted",
            "current_state": "fixture evidence",
            "owner_ref": "human:business-steward",
            "selected_value": selected_value,
            "evidence": evidence,
        }
        if target in derivations:
            derivation = derivations[target]
            kwargs.update(
                source_fields=derivation.source_fields,
                semantic_contract_ref=derivation.semantic_contract_ref,
                semantic_contract_sha256=derivation.semantic_contract_sha256,
                method=derivation.method,
            )
        decisions.append(JqdltbDecision(**kwargs))
    return build_jqdltb_decision_packet(
        packet_id="jqdltb-release-packet-fixture-v1",
        identity=identity,
        decisions=tuple(decisions),
        created_by="workload:test",
        created_at=NOW,
        status="submitted",
        submitted_by="human:business-steward",
        submitted_at=NOW + timedelta(minutes=1),
    )


def test_release_plan_binds_same_run_layers_quality_lineage_and_operations() -> None:
    plan = build_jqdltb_data_product_release_plan(**_facts())

    assert plan.data_product_version.source_resource_version_id == SOURCE_ID
    assert plan.data_product_version.output_resource_version_id == OUTPUT_VERSION_ID
    assert plan.data_product_version.distribution_manifest["layers"] == _layers()
    assert plan.data_product_version.distribution_manifest["serving_layer"]["name"] == "ads"
    assert (
        plan.data_product_version.distribution_manifest["release_approval_case_ref"]
        == plan.release_approval_case_ref
    )
    assert plan.approval_context()["quality_result_id"] == str(QUALITY_RESULT_ID)


def test_release_plan_binds_submitted_decision_packet_across_release_surfaces() -> None:
    facts = _facts()
    packet = _packet_for_contract(
        facts["transformation_contract"], facts["operating_contract"]
    )
    facts["decision_packet"] = packet
    plan = build_jqdltb_data_product_release_plan(**facts)

    assert plan.data_product_version.mapping_contract["decision_packet_sha256"] == (
        packet.packet_sha256
    )
    assert plan.data_product_version.distribution_manifest[
        "decision_packet_sha256"
    ] == packet.packet_sha256
    assert plan.approval_context()["decision_packet_sha256"] == packet.packet_sha256
    assert plan.registry_binding()["decision_packet_sha256"] == packet.packet_sha256


def test_release_plan_rejects_decision_packet_identity_and_contract_drift() -> None:
    facts = _facts()
    packet = _packet_for_contract(
        facts["transformation_contract"], facts["operating_contract"]
    )
    drifted_identity = packet.identity.model_copy(update={"bundle_sha256": "f" * 64})
    drifted_decisions = tuple(
        item.model_copy(
            update={
                "evidence": item.evidence.model_copy(update={"identity": drifted_identity})
            }
        )
        for item in packet.decisions
    )
    facts["decision_packet"] = build_jqdltb_decision_packet(
        packet_id=packet.packet_id,
        identity=drifted_identity,
        decisions=drifted_decisions,
        created_by=packet.created_by,
        created_at=packet.created_at,
        status="submitted",
        submitted_by=packet.submitted_by,
        submitted_at=packet.submitted_at,
    )
    with pytest.raises(ValueError, match="identity differs"):
        build_jqdltb_data_product_release_plan(**facts)

    facts = _facts()
    packet = _packet_for_contract(
        facts["transformation_contract"], facts["operating_contract"]
    )
    decisions = tuple(
        item.model_copy(
            update={
                "selected_value": "use_geometry",
                "selected_rule_ref": "gda://local-dev/area_rule/drift-v1",
                "selected_rule_sha256": "c" * 64,
            }
        )
        if item.target == "area_deviation_policy"
        else item
        for item in packet.decisions
    )
    facts["decision_packet"] = build_jqdltb_decision_packet(
        packet_id=packet.packet_id,
        identity=packet.identity,
        decisions=decisions,
        created_by=packet.created_by,
        created_at=packet.created_at,
        status="submitted",
        submitted_by=packet.submitted_by,
        submitted_at=packet.submitted_at,
    )
    with pytest.raises(ValueError, match="area deviation policy differs"):
        build_jqdltb_data_product_release_plan(**facts)


@pytest.mark.parametrize(
    ("target", "selected_value", "message"),
    (
        ("business_steward", "team:other-steward", "business steward differs"),
        ("license_status", "restricted", "license differs"),
        ("slo_on_call", "team:other-on-call", "on-call differs"),
        (
            "environment_owner.staging",
            "team:other-runtime",
            "environment owner differs",
        ),
    ),
)
def test_release_plan_rejects_packet_operating_decision_drift(
    target: str, selected_value: str, message: str
) -> None:
    facts = _facts()
    operating = facts["operating_contract"].model_copy(update={"environment": "staging"})
    facts["operating_contract"] = operating
    packet = _packet_for_contract(facts["transformation_contract"], operating)
    decisions = tuple(
        item.model_copy(update={"selected_value": selected_value})
        if item.target == target
        else item
        for item in packet.decisions
    )
    facts["decision_packet"] = build_jqdltb_decision_packet(
        packet_id=packet.packet_id,
        identity=packet.identity,
        decisions=decisions,
        created_by=packet.created_by,
        created_at=packet.created_at,
        status="submitted",
        submitted_by=packet.submitted_by,
        submitted_at=packet.submitted_at,
    )
    with pytest.raises(ValueError, match=message):
        build_jqdltb_data_product_release_plan(**facts)


@pytest.mark.parametrize("environment", ("staging", "production"))
def test_release_plan_requires_decision_packet_outside_development(
    environment: str,
) -> None:
    facts = _facts()
    facts["operating_contract"] = facts["operating_contract"].model_copy(
        update={"environment": environment}
    )
    with pytest.raises(ValueError, match="require a decision packet"):
        build_jqdltb_data_product_release_plan(**facts)


def test_release_plan_rejects_pending_governance_and_layer_tampering() -> None:
    with pytest.raises(ValidationError, match="business_steward_ref must be resolved"):
        JqdltbReleaseOperatingContract(
            tenant_id="local-dev",
            environment="development",
            business_steward_ref="pending_assignment",
            license_id="internal-evaluation-approved",
            data_slo_ref="gda://local-dev/data_slo/jqdltb-v1",
            service_slo_ref="gda://local-dev/service_slo/jqdltb-v1",
            on_call_ref="team:data-platform-on-call",
            environment_owner_ref="team:platform-runtime",
            deployment_profile_ref="profile:main-compose-dev",
            backup_restore_evidence_artifact_id=BACKUP_EVIDENCE_ID,
        )

    facts = _facts()
    output = facts["output_artifact"]
    layers = dict(output.manifest["layers"])
    layers["ads"] = dict(layers["ads"]) | {"records": 999}
    layer_sha = canonical_json_fingerprint(layers)
    facts["output_artifact"] = output.model_copy(
        update={
            "content_sha256": layer_sha,
            "manifest": output.manifest | {"layers": layers, "bundle_sha256": layer_sha},
        }
    )
    with pytest.raises(ValueError, match="layer manifest does not match"):
        build_jqdltb_data_product_release_plan(**facts)


def test_release_plan_fingerprint_is_tamper_evident() -> None:
    plan = build_jqdltb_data_product_release_plan(**_facts())
    with pytest.raises(ValidationError, match="plan_sha256"):
        JqdltbDataProductReleasePlan.model_validate(
            plan.model_dump(mode="json", by_alias=True) | {"plan_sha256": "0" * 64}
        )


def test_release_service_requires_live_approval_then_reuses_registry() -> None:
    plan = build_jqdltb_data_product_release_plan(**_facts())
    authority = _Authority()
    registry = MagicMock()
    registry.publish.return_value = {"pointer_changed": True}
    service = JqdltbDataProductReleaseService(registry, authority)
    requested = service.request_release(
        plan,
        requester_subject="workload:data-product-controller",
        request_reason="publish the approved JQDLTB layered product",
        owner_ref="team:cq-land-data",
        requested_at=NOW + timedelta(minutes=15),
        expires_at=NOW + timedelta(days=1),
    )
    assert requested.approval_case.action == JQDLTB_PRODUCT_RELEASE_ACTION
    assert requested.approval_case.target_fingerprint == plan.plan_sha256

    with pytest.raises(ValueError, match="not executable"):
        service.publish(
            plan,
            idempotency_key="publish-jqdltb-v1",
            reason="release approved layered product",
            now=NOW + timedelta(hours=2),
        )
    registry.publish.assert_not_called()

    approved = requested.approval_case.model_copy(
        update={
            "status": ApprovalCaseStatus.APPROVED,
            "state_version": 1,
            "decided_by": "human:cq-land-release-owner",
            "decision_reason": "quality, license and operating ownership approved",
            "decided_at": NOW + timedelta(hours=1),
        }
    )
    authority.cases[approved.approval_case_ref] = approved
    result = service.publish(
        plan,
        idempotency_key="publish-jqdltb-v1",
        reason="release approved layered product",
        now=NOW + timedelta(hours=2),
    )
    assert result == {"pointer_changed": True}
    registry.publish.assert_called_once_with(
        plan.product,
        plan.data_product_version,
        idempotency_key="publish-jqdltb-v1",
        reason="release approved layered product",
        jqdltb_release_plan=plan,
        jqdltb_release_approval_case_ref=plan.release_approval_case_ref,
    )


def test_release_service_rejects_approval_context_drift() -> None:
    plan = build_jqdltb_data_product_release_plan(**_facts())
    authority = _Authority()
    registry = MagicMock()
    service = JqdltbDataProductReleaseService(registry, authority)
    requested = service.request_release(
        plan,
        requester_subject="workload:data-product-controller",
        request_reason="publish the approved JQDLTB layered product",
        owner_ref="team:cq-land-data",
        requested_at=NOW + timedelta(minutes=15),
        expires_at=NOW + timedelta(days=1),
    )
    drifted = requested.approval_case.model_copy(
        update={
            "status": ApprovalCaseStatus.APPROVED,
            "state_version": 1,
            "request_context": requested.approval_case.request_context
            | {"quality_result_id": str(UUID(int=0))},
            "decided_by": "human:cq-land-release-owner",
            "decision_reason": "drifted approval",
            "decided_at": NOW + timedelta(hours=1),
        }
    )
    authority.cases[drifted.approval_case_ref] = drifted

    with pytest.raises(ValueError, match="not executable"):
        service.publish(
            plan,
            idempotency_key="publish-jqdltb-v1",
            reason="release approved layered product",
            now=NOW + timedelta(hours=2),
        )
    registry.publish.assert_not_called()
