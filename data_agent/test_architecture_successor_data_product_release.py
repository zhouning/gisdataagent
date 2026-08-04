"""Contract tests for approval-bound architecture successor product release."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from data_agent.architecture_successor_adoption import (
    build_architecture_successor_adoption_case,
    build_architecture_successor_plan,
)
from data_agent.architecture_successor_data_product_release import (
    ARCHITECTURE_SUCCESSOR_RELEASE_ACTION,
    ArchitectureSuccessorDataProductReleasePlan,
    build_architecture_successor_data_product_release_plan,
    build_architecture_successor_release_approval_case,
)
from data_agent.data_product_registry import (
    DataProductSpec,
    DataProductVersionSpec,
    data_product_manifest_fingerprint,
)
from data_agent.platform_contracts import ApprovalCaseStatus, Artifact, ArtifactRole
from data_agent.test_architecture_successor_adoption import (
    NOW,
    PREDECESSOR_ID,
    SUCCESSOR_ID,
    TENANT,
    _facts,
)

PRODUCT_URN = f"gda://{TENANT}/data_product/parcels"
PREDECESSOR_PRODUCT_VERSION_ID = UUID("70000000-0000-4000-8000-000000000001")
SUCCESSOR_PRODUCT_VERSION_ID = UUID("70000000-0000-4000-8000-000000000002")
QUALITY_ARTIFACT_ID = UUID("80000000-0000-4000-8000-000000000001")
DISTRIBUTION_ARTIFACT_ID = UUID("80000000-0000-4000-8000-000000000002")


def _version(**updates) -> DataProductVersionSpec:
    values = {
        "tenant_id": TENANT,
        "data_product_version_id": PREDECESSOR_PRODUCT_VERSION_ID,
        "product_urn": PRODUCT_URN,
        "version_key": "v1.0.0",
        "predecessor_version_id": None,
        "source_resource_version_id": UUID(
            "90000000-0000-4000-8000-000000000001"
        ),
        "output_resource_version_id": PREDECESSOR_ID,
        "standard_version_ref": "standard:parcel:v1",
        "mapping_contract": {"mapping": {"parcel_id": "parcel_id"}},
        "quality_contract": {"verdict": "passed", "checks": ["geometry"]},
        "quality_evidence_artifact_id": UUID(
            "80000000-0000-4000-8000-000000000010"
        ),
        "distribution_manifest": {
            "formats": [
                {
                    "kind": "GeoParquet",
                    "artifact_id": "80000000-0000-4000-8000-000000000010",
                    "content_sha256": "1" * 64,
                    "size_bytes": 10,
                }
            ]
        },
        "published_by": "workload:data-product-controller",
        "published_at": NOW,
    }
    values.update(updates)
    values["manifest_sha256"] = data_product_manifest_fingerprint(values)
    return DataProductVersionSpec.model_validate(values)


def _release_facts(*, timeline_start=NOW):
    architecture_plan = build_architecture_successor_plan(**_facts())
    pending_adoption = build_architecture_successor_adoption_case(
        architecture_plan,
        requester_subject="workload:architecture-controller",
        request_reason="adopt reviewed successor",
        requested_at=NOW + timedelta(minutes=5),
        expires_at=NOW + timedelta(hours=1),
    )
    adoption_case = pending_adoption.model_copy(
        update={
            "status": ApprovalCaseStatus.APPROVED,
            "state_version": 1,
            "decided_by": "human:architecture-owner",
            "decision_reason": "successor architecture approved",
            "decided_at": NOW + timedelta(minutes=6),
        }
    )
    product = DataProductSpec(
        tenant_id=TENANT,
        product_urn=PRODUCT_URN,
        product_slug="parcels",
        title="Parcels",
        description="Governed parcel product",
        domain="land",
        owner_ref="team:spatial-data",
        governance_ref={
            "classification": "internal",
            "visibility": "private",
            "license_id": "internal",
            "attribution": "spatial data team",
        },
        created_at=timeline_start,
    )
    predecessor = _version(published_at=timeline_start)
    successor = _version(
        data_product_version_id=SUCCESSOR_PRODUCT_VERSION_ID,
        version_key="v2.0.0",
        predecessor_version_id=PREDECESSOR_PRODUCT_VERSION_ID,
        source_resource_version_id=UUID(
            "90000000-0000-4000-8000-000000000002"
        ),
        output_resource_version_id=SUCCESSOR_ID,
        standard_version_ref="standard:parcel:v2",
        quality_evidence_artifact_id=QUALITY_ARTIFACT_ID,
        distribution_manifest={
            "formats": [
                {
                    "kind": "GeoParquet",
                    "artifact_id": str(DISTRIBUTION_ARTIFACT_ID),
                    "content_sha256": "e" * 64,
                    "size_bytes": 2048,
                }
            ]
        },
        published_at=timeline_start + timedelta(minutes=9),
    )
    quality = Artifact(
        tenant_id=TENANT,
        artifact_id=QUALITY_ARTIFACT_ID,
        artifact_key="quality.parcels-v2.json",
        artifact_role=ArtifactRole.EVIDENCE,
        storage_uri="s3://product-evidence/quality/parcels-v2.json",
        media_type="application/json",
        content_sha256="f" * 64,
        size_bytes=512,
        resource_version_id=SUCCESSOR_ID,
        manifest={"schema": "gda.quality_report.v1", "verdict": "passed"},
        created_by="workload:quality-controller",
        created_at=timeline_start + timedelta(minutes=7),
    )
    distribution = Artifact(
        tenant_id=TENANT,
        artifact_id=DISTRIBUTION_ARTIFACT_ID,
        artifact_key="distribution.parcels-v2.parquet",
        artifact_role=ArtifactRole.OUTPUT,
        storage_uri="s3://product-distribution/parcels-v2.parquet",
        media_type="application/vnd.apache.parquet",
        content_sha256="e" * 64,
        size_bytes=2048,
        resource_version_id=SUCCESSOR_ID,
        manifest={"schema": "gda.distribution.v1"},
        created_by="workload:data-product-controller",
        created_at=timeline_start + timedelta(minutes=7),
    )
    return {
        "product": product,
        "predecessor_data_product_version": predecessor,
        "successor_data_product_version": successor,
        "architecture_successor_plan": architecture_plan,
        "architecture_adoption_case": adoption_case,
        "quality_evidence_artifact": quality,
        "distribution_artifacts": (distribution,),
    }


def test_release_plan_binds_adoption_architecture_artifacts_and_rollback() -> None:
    plan = build_architecture_successor_data_product_release_plan(**_release_facts())
    case = build_architecture_successor_release_approval_case(
        plan,
        requester_subject="workload:data-product-controller",
        request_reason="release approved parcel successor",
        requested_at=NOW + timedelta(minutes=7),
        expires_at=NOW + timedelta(hours=1),
    )

    assert case.action == ARCHITECTURE_SUCCESSOR_RELEASE_ACTION
    assert case.target_fingerprint == plan.plan_sha256
    assert case.target_resource_urn == PRODUCT_URN
    assert case.request_context["architecture_successor_plan_sha256"] == (
        plan.architecture_successor_plan.plan_sha256
    )
    assert case.request_context["rollback_target_version_id"] == str(
        PREDECESSOR_PRODUCT_VERSION_ID
    )
    assert case.request_context["release_plan"]["plan_sha256"] == plan.plan_sha256


def test_release_plan_rejects_product_and_architecture_chain_mismatch() -> None:
    facts = _release_facts()
    wrong_output = _version(
        data_product_version_id=SUCCESSOR_PRODUCT_VERSION_ID,
        version_key="v2.0.0",
        predecessor_version_id=PREDECESSOR_PRODUCT_VERSION_ID,
        output_resource_version_id=UUID("10000000-0000-4000-8000-000000000099"),
        quality_evidence_artifact_id=QUALITY_ARTIFACT_ID,
        published_at=NOW + timedelta(minutes=9),
    )
    with pytest.raises(ValueError, match="architecture successor chain"):
        build_architecture_successor_data_product_release_plan(
            **facts | {"successor_data_product_version": wrong_output}
        )


def test_release_plan_rejects_wrong_quality_and_distribution_bindings() -> None:
    facts = _release_facts()
    wrong_quality = facts["quality_evidence_artifact"].model_copy(
        update={"resource_version_id": PREDECESSOR_ID}
    )
    with pytest.raises(ValueError, match="quality evidence Artifact"):
        build_architecture_successor_data_product_release_plan(
            **facts | {"quality_evidence_artifact": wrong_quality}
        )

    wrong_distribution = facts["distribution_artifacts"][0].model_copy(
        update={"content_sha256": "0" * 64}
    )
    with pytest.raises(ValueError, match="distribution Artifact content"):
        build_architecture_successor_data_product_release_plan(
            **facts | {"distribution_artifacts": (wrong_distribution,)}
        )


def test_release_plan_and_approval_context_are_tamper_evident() -> None:
    plan = build_architecture_successor_data_product_release_plan(**_release_facts())
    with pytest.raises(ValidationError, match="plan_sha256"):
        ArchitectureSuccessorDataProductReleasePlan.model_validate(
            plan.model_dump() | {"plan_sha256": "0" * 64}
        )


def test_release_requires_nonempty_distribution_artifact_manifest() -> None:
    facts = _release_facts()
    successor = facts["successor_data_product_version"]
    payload = successor.model_dump(exclude={"manifest_sha256"}) | {
        "distribution_manifest": {"formats": []}
    }
    payload["manifest_sha256"] = data_product_manifest_fingerprint(payload)
    without_distribution = DataProductVersionSpec.model_validate(payload)
    with pytest.raises(ValueError, match="at least one distribution Artifact"):
        build_architecture_successor_data_product_release_plan(
            **facts
            | {
                "successor_data_product_version": without_distribution,
                "distribution_artifacts": (),
            }
        )


def test_release_migration_enforces_atomic_binding_and_approved_rollback_pointer() -> None:
    sql = (
        Path(__file__).resolve().parent
        / "migrations"
        / "116_architecture_successor_data_product_release.sql"
    ).read_text(encoding="utf-8")

    assert "DEFERRABLE INITIALLY DEFERRED" in sql
    assert "require_architecture_successor_release" in sql
    assert "data_product.publish_architecture_successor" in sql
    assert "rollback_target_version_id = predecessor_data_product_version_id" in sql
    assert "trg_gda_product_architecture_release_immutable" in sql
    assert "FORCE ROW LEVEL SECURITY" in sql
