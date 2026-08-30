#!/usr/bin/env python3
"""Submit one governed real-data JQDLTB audit run to the platform outbox."""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from data_agent.platform_authorization import build_policy_decision_artifact
from data_agent.platform_contracts import (
    PlatformRun,
    PolicyDecision,
    ResourceBinding,
    RunPolicyReferences,
    SubjectContext,
)
from data_agent.platform_gateway import PlatformGateway

DEFINITION_VERSION_ID = UUID("b1c933bd-8968-559f-b2b1-228fe5dc6f24")
SOURCE_RESOURCE_VERSION_ID = UUID("34441c77-2cf0-5ca2-83bf-81dd6a488d5b")
RUN_ID = uuid5(
    NAMESPACE_URL,
    f"gda:run:jqdltb-full-audit:v1:{DEFINITION_VERSION_ID}:{SOURCE_RESOURCE_VERSION_ID}",
)
WORKLOAD_SUBJECT_ID = "dolphinscheduler-gda-dataops"
WORKLOAD_SUBJECT = f"workload:{WORKLOAD_SUBJECT_ID}"
POLICY_EVALUATOR = "workload:gda-policy-evaluator"


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


def submit(*, deployment_path: Path, runtime_dir: Path) -> dict[str, Any]:
    deployment = _read_json(deployment_path)
    if UUID(deployment["definition_version_id"]) != DEFINITION_VERSION_ID:
        raise ValueError("deployment report definition does not match the run contract")
    binding_artifact_id = UUID(deployment["binding_artifact_id"])
    gateway = PlatformGateway()
    execution_plan = gateway.get_artifact("local-dev", binding_artifact_id)

    state_path = runtime_dir / "jqdltb-run-state.json"
    if state_path.exists():
        state = _read_json(state_path)
        submitted_at = datetime.fromisoformat(state["submitted_at"])
    else:
        submitted_at = datetime.now(UTC).replace(microsecond=0)
        state = {
            "schema": "gda.jqdltb_run_state.v1",
            "run_id": str(RUN_ID),
            "submitted_at": submitted_at.isoformat(),
        }
        _write_json(state_path, state)
    if UUID(state["run_id"]) != RUN_ID:
        raise ValueError("run state identity does not match the immutable run contract")

    subject = SubjectContext(
        tenant_id="local-dev",
        subject_id=WORKLOAD_SUBJECT_ID,
        subject_type="workload",
        roles=("platform_operator",),
        purpose="execute the governed full-dataset Chongqing JQDLTB quality audit",
        trace_id="jqdltb-full-audit-v1",
    )
    decision = PolicyDecision(
        tenant_id="local-dev",
        run_id=RUN_ID,
        subject_context=subject,
        action="dolphinscheduler.dispatch",
        definition_version_id=DEFINITION_VERSION_ID,
        resource_version_ids=(DEFINITION_VERSION_ID, SOURCE_RESOURCE_VERSION_ID),
        execution_plan_artifact_id=execution_plan.artifact_id,
        effect="allow",
        policy_version_ref="gda://local-dev/policy/jqdltb-audit-sandbox:v1",
        evaluator_subject=POLICY_EVALUATOR,
        requires_approval=False,
        obligations=(),
        decided_at=submitted_at,
        expires_at=submitted_at + timedelta(hours=24),
    )
    policy_artifact = build_policy_decision_artifact(decision)
    policy_result = gateway.record_artifact(policy_artifact)
    run = PlatformRun(
        tenant_id="local-dev",
        run_id=RUN_ID,
        definition_version_id=DEFINITION_VERSION_ID,
        orchestration_class="dataops",
        subject_context=subject,
        input_bindings=(
            ResourceBinding(
                binding_name="source",
                resource_version_id=SOURCE_RESOURCE_VERSION_ID,
                semantic_type="gis.land_use.parcel.source",
            ),
        ),
        idempotency_key=(
            f"jqdltb-full-audit:v1:{SOURCE_RESOURCE_VERSION_ID}"
        ),
        policy_refs=RunPolicyReferences(
            policy_decision_artifact_id=policy_artifact.artifact_id
        ),
        config_fingerprint=deployment["compiled_sha256"],
        submitted_at=submitted_at,
    )
    run_result = gateway.submit_run(run, request_dispatch=True)
    report = {
        "schema": "gda.chongqing_jqdltb_dataops_run_submission.v1",
        "status": run_result.value.status.value,
        "run_id": str(run_result.value.run_id),
        "state_version": run_result.value.state_version,
        "definition_version_id": str(DEFINITION_VERSION_ID),
        "source_resource_version_id": str(SOURCE_RESOURCE_VERSION_ID),
        "binding_artifact_id": str(binding_artifact_id),
        "policy_artifact_id": str(policy_artifact.artifact_id),
        "policy_artifact_created": policy_result.created,
        "platform_run_created": run_result.created,
        "dispatch_requested": True,
        "authoritative_quality_result_recorded": False,
        "data_product_version_created": False,
    }
    _write_json(runtime_dir / "jqdltb-run-submission-report.json", report)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deployment", required=True, type=Path)
    parser.add_argument("--runtime-dir", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    print(
        json.dumps(
            submit(deployment_path=args.deployment, runtime_dir=args.runtime_dir),
            ensure_ascii=True,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
