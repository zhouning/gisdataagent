#!/usr/bin/env python3
"""Submit one governed Chongqing JQDLTB backfill through the platform outbox."""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid5

from data_agent.dataops_invocation import (
    DATAOPS_INVOCATION_SEMANTIC_TYPE,
    DataOpsInvocation,
    build_dataops_invocation_resources,
)
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
WORKLOAD_SUBJECT_ID = "dolphinscheduler-gda-dataops"
WORKLOAD_SUBJECT = f"workload:{WORKLOAD_SUBJECT_ID}"
POLICY_EVALUATOR = "workload:gda-policy-evaluator"
REQUESTED_BY = "human:data-platform-operator"
DEFAULT_LOGICAL_START = "2026-07-01T00:00:00+00:00"
DEFAULT_LOGICAL_END = "2026-07-02T00:00:00+00:00"
DEFAULT_SCHEDULE_REF = "gda://local-dev/schedule/chongqing-jqdltb-daily"


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


def _timestamp(value: str, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{label} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} must include a timezone")
    return parsed.astimezone(UTC)


def submit(
    *,
    deployment_path: Path,
    runtime_dir: Path,
    logical_start: datetime,
    logical_end: datetime,
    schedule_ref: str,
) -> dict[str, Any]:
    deployment = _read_json(deployment_path)
    if UUID(deployment["definition_version_id"]) != DEFINITION_VERSION_ID:
        raise ValueError("deployment report definition does not match backfill contract")
    binding_artifact_id = UUID(deployment["binding_artifact_id"])
    gateway = PlatformGateway()
    execution_plan = gateway.get_artifact("local-dev", binding_artifact_id)

    state_path = runtime_dir / "jqdltb-backfill-state.json"
    if state_path.exists():
        state = _read_json(state_path)
        requested_at = _timestamp(state["requested_at"], "state.requested_at")
        if (
            _timestamp(state["logical_start"], "state.logical_start") != logical_start
            or _timestamp(state["logical_end"], "state.logical_end") != logical_end
            or state["schedule_ref"] != schedule_ref
        ):
            raise ValueError("backfill state does not match the requested logical window")
    else:
        requested_at = datetime.now(UTC).replace(microsecond=0)
        state = {
            "schema": "gda.jqdltb_backfill_state.v1",
            "logical_start": logical_start.isoformat(),
            "logical_end": logical_end.isoformat(),
            "schedule_ref": schedule_ref,
            "requested_at": requested_at.isoformat(),
        }

    invocation = DataOpsInvocation.create(
        tenant_id="local-dev",
        definition_version_id=DEFINITION_VERSION_ID,
        trigger_kind="backfill",
        logical_start=logical_start,
        logical_end=logical_end,
        schedule_times=(logical_start,),
        schedule_ref=schedule_ref,
        requested_by=REQUESTED_BY,
        requested_at=requested_at,
    )
    invocation_resource, invocation_version = build_dataops_invocation_resources(
        invocation
    )
    run_id = uuid5(
        DEFINITION_VERSION_ID,
        f"jqdltb-backfill-run:{invocation_version.resource_version_id}",
    )
    state.update(
        {
            "run_id": str(run_id),
            "invocation_resource_version_id": str(
                invocation_version.resource_version_id
            ),
        }
    )
    _write_json(state_path, state)

    invocation_resource_result = gateway.register_resource(invocation_resource)
    invocation_version_result = gateway.register_resource_version(invocation_version)
    subject = SubjectContext(
        tenant_id="local-dev",
        subject_id=WORKLOAD_SUBJECT_ID,
        subject_type="workload",
        roles=("platform_operator",),
        purpose="execute a governed Chongqing JQDLTB logical-window backfill",
        trace_id=f"jqdltb-backfill-{invocation.invocation_sha256[:16]}",
    )
    scoped_versions = tuple(
        sorted(
            {
                DEFINITION_VERSION_ID,
                SOURCE_RESOURCE_VERSION_ID,
                invocation_version.resource_version_id,
            },
            key=str,
        )
    )
    decision = PolicyDecision(
        tenant_id="local-dev",
        run_id=run_id,
        subject_context=subject,
        action="dolphinscheduler.dispatch",
        definition_version_id=DEFINITION_VERSION_ID,
        resource_version_ids=scoped_versions,
        execution_plan_artifact_id=execution_plan.artifact_id,
        effect="allow",
        policy_version_ref="gda://local-dev/policy/jqdltb-backfill-sandbox:v1",
        evaluator_subject=POLICY_EVALUATOR,
        requires_approval=False,
        obligations=(),
        decided_at=requested_at,
        expires_at=requested_at + timedelta(hours=24),
    )
    policy_artifact = build_policy_decision_artifact(decision)
    policy_result = gateway.record_artifact(policy_artifact)
    run = PlatformRun(
        tenant_id="local-dev",
        run_id=run_id,
        definition_version_id=DEFINITION_VERSION_ID,
        orchestration_class="dataops",
        subject_context=subject,
        input_bindings=(
            ResourceBinding(
                binding_name="source",
                resource_version_id=SOURCE_RESOURCE_VERSION_ID,
                semantic_type="gis.land_use.parcel.source",
            ),
            ResourceBinding(
                binding_name="invocation",
                resource_version_id=invocation_version.resource_version_id,
                semantic_type=DATAOPS_INVOCATION_SEMANTIC_TYPE,
            ),
        ),
        idempotency_key=(
            f"jqdltb-backfill:v1:{invocation_version.resource_version_id}"
        ),
        policy_refs=RunPolicyReferences(
            policy_decision_artifact_id=policy_artifact.artifact_id
        ),
        config_fingerprint=deployment["compiled_sha256"],
        submitted_at=requested_at,
    )
    run_result = gateway.submit_run(run, request_dispatch=True)
    report = {
        "schema": "gda.chongqing_jqdltb_backfill_submission.v1",
        "status": run_result.value.status.value,
        "run_id": str(run_result.value.run_id),
        "state_version": run_result.value.state_version,
        "definition_version_id": str(DEFINITION_VERSION_ID),
        "source_resource_version_id": str(SOURCE_RESOURCE_VERSION_ID),
        "invocation_resource_urn": invocation_resource.resource_urn,
        "invocation_resource_version_id": str(invocation_version.resource_version_id),
        "invocation_sha256": invocation.invocation_sha256,
        "trigger_kind": invocation.trigger_kind,
        "logical_start": invocation.logical_start.isoformat(),
        "logical_end": invocation.logical_end.isoformat(),
        "window_semantics": invocation.window_semantics,
        "schedule_times": [value.isoformat() for value in invocation.schedule_times],
        "schedule_ref": invocation.schedule_ref,
        "binding_artifact_id": str(binding_artifact_id),
        "policy_artifact_id": str(policy_artifact.artifact_id),
        "invocation_resource_created": invocation_resource_result.created,
        "invocation_version_created": invocation_version_result.created,
        "policy_artifact_created": policy_result.created,
        "platform_run_created": run_result.created,
        "dispatch_requested": True,
        "expected_provider_exec_type": "COMPLEMENT_DATA",
        "authoritative_quality_result_recorded": False,
        "data_product_version_created": False,
    }
    _write_json(runtime_dir / "jqdltb-backfill-submission-report.json", report)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deployment", required=True, type=Path)
    parser.add_argument("--runtime-dir", required=True, type=Path)
    parser.add_argument("--logical-start", default=DEFAULT_LOGICAL_START)
    parser.add_argument("--logical-end", default=DEFAULT_LOGICAL_END)
    parser.add_argument("--schedule-ref", default=DEFAULT_SCHEDULE_REF)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    print(
        json.dumps(
            submit(
                deployment_path=args.deployment,
                runtime_dir=args.runtime_dir,
                logical_start=_timestamp(args.logical_start, "logical_start"),
                logical_end=_timestamp(args.logical_end, "logical_end"),
                schedule_ref=args.schedule_ref,
            ),
            ensure_ascii=True,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
