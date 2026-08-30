#!/usr/bin/env python3
"""Reconcile DS success and finalize the JQDLTB run from quality evidence."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any
from uuid import UUID, uuid5

from data_agent.dataops_executor import QUALITY_EVALUATOR, QUALITY_RULE_REF
from data_agent.dolphinscheduler_adapter import (
    DolphinSchedulerAdapter,
    DolphinSchedulerProfile,
)
from data_agent.platform_contracts import (
    LineageEvent,
    Resource,
    ResourceVersion,
    RunStatus,
    canonical_json_fingerprint,
)
from data_agent.platform_gateway import PlatformGateway

WORKLOAD_SUBJECT = "workload:dolphinscheduler-gda-dataops"
ASSESSMENT_URN = "gda://local-dev/report/chongqing-jqdltb-quality-assessment-v2"


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON document must be an object: {path}")
    return value


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.chmod(0o600)
    os.replace(temporary, path)


def _profile(value: dict[str, Any]) -> DolphinSchedulerProfile:
    token = Path(str(value["token_file"])).read_text(encoding="utf-8").strip()
    return DolphinSchedulerProfile(
        base_url=str(value["base_url"]),
        access_token=token,
        project_code=int(value["project_code"]),
        workload_subject=WORKLOAD_SUBJECT,
        policy_evaluator_subject="workload:gda-policy-evaluator",
        tenant_code=str(value["tenant_code"]),
        worker_group=str(value["worker_group"]),
        timezone_name="Asia/Tokyo",
    )


def finalize(
    *, profile_path: Path, deployment_path: Path, submission_path: Path, runtime_dir: Path
) -> dict[str, Any]:
    profile = _profile(_read_json(profile_path))
    deployment = _read_json(deployment_path)
    submission = _read_json(submission_path)
    run_id = UUID(submission["run_id"])
    source_version_id = UUID(submission["source_resource_version_id"])
    definition_version_id = UUID(submission["definition_version_id"])
    binding_artifact_id = UUID(deployment["binding_artifact_id"])
    gateway = PlatformGateway()
    adapter = DolphinSchedulerAdapter(profile, gateway=gateway)
    try:
        reconciliation = adapter.reconcile(
            "local-dev",
            run_id,
            binding_artifact_id,
            actor_subject=WORKLOAD_SUBJECT,
        )
    finally:
        adapter.client.close()
    if reconciliation.provider_state != "SUCCESS":
        raise ValueError(
            "DolphinScheduler execution is not SUCCESS; finalization is blocked"
        )

    quality_result_id = uuid5(run_id, f"quality:{QUALITY_RULE_REF}")
    quality = gateway.get_quality_result("local-dev", quality_result_id)
    evidence = gateway.get_artifact("local-dev", quality.evidence_artifact_id)
    if quality.run_id != run_id or quality.resource_version_id != source_version_id:
        raise ValueError("QualityResult is not bound to this run and source version")
    if quality.rule_version_ref != QUALITY_RULE_REF:
        raise ValueError("QualityResult uses an unexpected rule version")
    if quality.evaluated_by != QUALITY_EVALUATOR:
        raise ValueError("QualityResult uses an unexpected evaluator identity")
    if evidence.run_id != run_id or evidence.resource_version_id != source_version_id:
        raise ValueError("quality evidence is not bound to this run and source version")
    assessment_version_id = uuid5(run_id, "jqdltb-quality-assessment:v1")
    assessment_resource = Resource(
        tenant_id="local-dev",
        resource_urn=ASSESSMENT_URN,
        resource_kind="report",
        authority_system="gda-control",
        authority_locator="quality-assessments/chongqing-jqdltb/v2",
        owner_ref="team:data-platform",
        governance_ref={
            "classification": "internal",
            "promotion_allowed": False,
        },
        technical_refs=(
            {
                "kind": "quality_rule",
                "rule_version_ref": QUALITY_RULE_REF,
            },
        ),
    )
    assessment_version = ResourceVersion(
        tenant_id="local-dev",
        resource_urn=ASSESSMENT_URN,
        resource_version_id=assessment_version_id,
        version_key=f"run-{run_id.hex[:16]}",
        content_sha256=evidence.content_sha256,
        authority_version_ref={
            "run_id": str(run_id),
            "quality_result_id": str(quality.quality_result_id),
            "evidence_artifact_id": str(evidence.artifact_id),
        },
        created_by=QUALITY_EVALUATOR,
        created_at=quality.evaluated_at,
    )
    resource_result = gateway.register_resource(assessment_resource)
    version_result = gateway.register_resource_version(assessment_version)
    facets = {
        "operation": "quality_assessment",
        "provider_state": reconciliation.provider_state,
        "quality_verdict": quality.verdict.value,
        "records_scanned": quality.metrics["records_scanned"],
        "full_dataset_validated": quality.metrics["full_dataset_validated"],
        "data_product_version_created": False,
    }
    lineage_id = uuid5(run_id, "lineage:jqdltb-source-to-quality-assessment:v1")
    lineage = LineageEvent(
        tenant_id="local-dev",
        lineage_event_id=lineage_id,
        event_type="derive",
        source_resource_version_id=source_version_id,
        target_resource_version_id=assessment_version_id,
        producer=QUALITY_EVALUATOR,
        event_sha256=canonical_json_fingerprint(
            {
                "source_resource_version_id": str(source_version_id),
                "target_resource_version_id": str(assessment_version_id),
                "run_id": str(run_id),
                "definition_version_id": str(definition_version_id),
                "artifact_id": str(evidence.artifact_id),
                "facets": facets,
            }
        ),
        run_id=run_id,
        definition_version_id=definition_version_id,
        artifact_id=evidence.artifact_id,
        facets=facets,
        occurred_at=quality.evaluated_at,
    )
    lineage_result = gateway.record_lineage(lineage)

    run = gateway.get_run("local-dev", run_id)
    transitioned = False
    if run.status != RunStatus.FAILED:
        if quality.verdict.value != "failed":
            raise ValueError("this finalizer only handles the known failed JQDLTB audit")
        run = gateway.transition_run(
            "local-dev",
            run_id,
            run.state_version,
            RunStatus.FAILED,
            WORKLOAD_SUBJECT,
            "authoritative full-dataset quality assessment failed",
            {
                "provider_state": reconciliation.provider_state,
                "workflow_instance_id": reconciliation.workflow_instance_id,
                "quality_result_id": str(quality.quality_result_id),
                "evidence_artifact_id": str(evidence.artifact_id),
                "lineage_event_id": str(lineage.lineage_event_id),
                "data_product_version_created": False,
            },
        )
        transitioned = True
    report = {
        "schema": "gda.chongqing_jqdltb_dataops_finalization.v1",
        "run_id": str(run_id),
        "platform_run_status": run.status.value,
        "platform_run_state_version": run.state_version,
        "platform_run_transitioned": transitioned,
        "provider_state": reconciliation.provider_state,
        "workflow_instance_id": reconciliation.workflow_instance_id,
        "attempt_observation_id": str(reconciliation.observation.observation_id),
        "attempt_observation_created": reconciliation.observation_created,
        "quality_result_id": str(quality.quality_result_id),
        "quality_verdict": quality.verdict.value,
        "evidence_artifact_id": str(evidence.artifact_id),
        "records_scanned": quality.metrics["records_scanned"],
        "assessment_resource_created": resource_result.created,
        "assessment_version_created": version_result.created,
        "assessment_resource_version_id": str(assessment_version_id),
        "lineage_event_id": str(lineage.lineage_event_id),
        "lineage_created": lineage_result.created,
        "data_product_version_created": False,
    }
    _write_json(runtime_dir / "jqdltb-finalization-report.json", report)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True, type=Path)
    parser.add_argument("--deployment", required=True, type=Path)
    parser.add_argument("--submission", required=True, type=Path)
    parser.add_argument("--runtime-dir", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    print(
        json.dumps(
            finalize(
                profile_path=args.profile,
                deployment_path=args.deployment,
                submission_path=args.submission,
                runtime_dir=args.runtime_dir,
            ),
            ensure_ascii=True,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
