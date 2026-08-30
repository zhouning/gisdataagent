#!/usr/bin/env python3
"""Submit one governed human-requested Chongqing JQDLTB audit."""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from data_agent.dataops_invocation import dataops_invocation_version_id
from data_agent.dataops_manual import DataOpsManualTriggerSpec
from data_agent.platform_contracts import ResourceBinding
from data_agent.platform_gateway import PlatformGateway

DEFINITION_VERSION_ID = UUID("b1c933bd-8968-559f-b2b1-228fe5dc6f24")
SOURCE_RESOURCE_VERSION_ID = UUID("34441c77-2cf0-5ca2-83bf-81dd6a488d5b")
WORKLOAD_SUBJECT_ID = "dolphinscheduler-gda-dataops"
POLICY_EVALUATOR = "workload:gda-policy-evaluator"
DEFAULT_REQUESTER = "human:data-platform-operator"
DEFAULT_CLIENT_REQUEST_ID = "jqdltb-manual-20260801-001"
DEFAULT_LOGICAL_START = "2026-07-03T00:00:00+00:00"
DEFAULT_LOGICAL_END = "2026-07-04T00:00:00+00:00"


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
    client_request_id: str,
    requester_subject: str,
    logical_start: datetime,
    logical_end: datetime,
) -> dict[str, Any]:
    deployment = _read_json(deployment_path)
    if UUID(deployment["definition_version_id"]) != DEFINITION_VERSION_ID:
        raise ValueError("deployment report definition does not match manual contract")
    binding_artifact_id = UUID(deployment["binding_artifact_id"])
    spec = DataOpsManualTriggerSpec(
        tenant_id="local-dev",
        client_request_id=client_request_id,
        definition_version_id=DEFINITION_VERSION_ID,
        logical_start=logical_start,
        logical_end=logical_end,
        input_bindings=(
            ResourceBinding(
                binding_name="source",
                resource_version_id=SOURCE_RESOURCE_VERSION_ID,
                semantic_type="gis.land_use.parcel.source",
            ),
        ),
        execution_plan_artifact_id=binding_artifact_id,
        requester_subject=requester_subject,
        workload_subject_id=WORKLOAD_SUBJECT_ID,
        workload_roles=("platform_operator",),
        purpose="execute a governed human-requested Chongqing JQDLTB audit",
        policy_version_ref="gda://local-dev/policy/jqdltb-manual-sandbox:v1",
        policy_evaluator_subject=POLICY_EVALUATOR,
        policy_ttl_seconds=86400,
        config_fingerprint=deployment["compiled_sha256"],
    )
    result = PlatformGateway().submit_manual_trigger(spec)
    invocation_version_id = dataops_invocation_version_id(result.invocation)
    report = {
        "schema": "gda.chongqing_jqdltb_manual_submission.v1",
        "status": result.run.status.value,
        "admission_channel": "trusted_local_control_script",
        "requester_authentication": "operator_supplied_sandbox_identity",
        "client_request_id": result.invocation.client_request_id,
        "request_sha256": result.request_sha256,
        "run_id": str(result.run.run_id),
        "state_version": result.run.state_version,
        "definition_version_id": str(DEFINITION_VERSION_ID),
        "source_resource_version_id": str(SOURCE_RESOURCE_VERSION_ID),
        "invocation_resource_version_id": str(invocation_version_id),
        "invocation_sha256": result.invocation.invocation_sha256,
        "trigger_kind": result.invocation.trigger_kind,
        "requester_subject": result.invocation.requested_by,
        "workload_subject": (
            f"{result.run.subject_context.subject_type.value}:"
            f"{result.run.subject_context.subject_id}"
        ),
        "delegated_by": result.run.subject_context.delegated_by,
        "logical_start": result.invocation.logical_start.isoformat(),
        "logical_end": result.invocation.logical_end.isoformat(),
        "window_semantics": result.invocation.window_semantics,
        "admitted_at": result.admitted_at.isoformat(),
        "binding_artifact_id": str(binding_artifact_id),
        "policy_artifact_id": str(
            result.run.policy_refs.policy_decision_artifact_id
        ),
        "dispatch_command_id": str(result.command.command_id),
        "dispatch_command_status": result.command.status.value,
        "invocation_resource_created": result.invocation_resource_created,
        "invocation_version_created": result.invocation_version_created,
        "policy_artifact_created": result.policy_artifact_created,
        "platform_run_created": result.run_created,
        "dispatch_command_created": result.command_created,
        "atomic_objects_created": result.created,
        "dispatch_requested": True,
        "provider_exec_type": "START_PROCESS",
        "authoritative_quality_result_recorded": False,
        "data_product_version_created": False,
    }
    _write_json(runtime_dir / "jqdltb-manual-submission-report.json", report)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deployment", required=True, type=Path)
    parser.add_argument("--runtime-dir", required=True, type=Path)
    parser.add_argument("--client-request-id", default=DEFAULT_CLIENT_REQUEST_ID)
    parser.add_argument("--requester-subject", default=DEFAULT_REQUESTER)
    parser.add_argument("--logical-start", default=DEFAULT_LOGICAL_START)
    parser.add_argument("--logical-end", default=DEFAULT_LOGICAL_END)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    print(
        json.dumps(
            submit(
                deployment_path=args.deployment,
                runtime_dir=args.runtime_dir,
                client_request_id=args.client_request_id,
                requester_subject=args.requester_subject,
                logical_start=_timestamp(args.logical_start, "logical_start"),
                logical_end=_timestamp(args.logical_end, "logical_end"),
            ),
            ensure_ascii=True,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
