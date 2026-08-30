#!/usr/bin/env python3
"""Admit one governed Chongqing JQDLTB schedule window atomically."""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from data_agent.dataops_invocation import dataops_invocation_version_id
from data_agent.dataops_schedule import (
    DataOpsScheduleController,
    DataOpsScheduleWindowSpec,
)
from data_agent.platform_contracts import ResourceBinding
from data_agent.platform_gateway import PlatformGateway

DEFINITION_VERSION_ID = UUID("b1c933bd-8968-559f-b2b1-228fe5dc6f24")
SOURCE_RESOURCE_VERSION_ID = UUID("34441c77-2cf0-5ca2-83bf-81dd6a488d5b")
WORKLOAD_SUBJECT_ID = "dolphinscheduler-gda-dataops"
POLICY_EVALUATOR = "workload:gda-policy-evaluator"
DEFAULT_LOGICAL_START = "2026-07-02T00:00:00+00:00"
DEFAULT_LOGICAL_END = "2026-07-03T00:00:00+00:00"
DEFAULT_SCHEDULED_FOR = "2026-07-03T00:05:00+00:00"
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
    scheduled_for: datetime,
    schedule_ref: str,
) -> dict[str, Any]:
    deployment = _read_json(deployment_path)
    if UUID(deployment["definition_version_id"]) != DEFINITION_VERSION_ID:
        raise ValueError("deployment report definition does not match schedule contract")
    binding_artifact_id = UUID(deployment["binding_artifact_id"])
    spec = DataOpsScheduleWindowSpec(
        tenant_id="local-dev",
        definition_version_id=DEFINITION_VERSION_ID,
        schedule_ref=schedule_ref,
        scheduled_for=scheduled_for,
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
        workload_subject_id=WORKLOAD_SUBJECT_ID,
        workload_roles=("platform_operator",),
        purpose="recover a governed Chongqing JQDLTB daily schedule window",
        policy_version_ref="gda://local-dev/policy/jqdltb-schedule-sandbox:v1",
        policy_evaluator_subject=POLICY_EVALUATOR,
        policy_ttl_seconds=86400,
        config_fingerprint=deployment["compiled_sha256"],
    )
    result = DataOpsScheduleController(PlatformGateway()).submit_window(spec)
    invocation_version_id = dataops_invocation_version_id(result.invocation)
    recovery_lag_seconds = result.recovery_lag_seconds(spec.scheduled_for)
    report = {
        "schema": "gda.chongqing_jqdltb_schedule_window_submission.v1",
        "status": result.run.status.value,
        "run_id": str(result.run.run_id),
        "state_version": result.run.state_version,
        "definition_version_id": str(DEFINITION_VERSION_ID),
        "source_resource_version_id": str(SOURCE_RESOURCE_VERSION_ID),
        "window_sha256": result.window_sha256,
        "invocation_resource_version_id": str(invocation_version_id),
        "invocation_sha256": result.invocation.invocation_sha256,
        "trigger_kind": result.invocation.trigger_kind,
        "logical_start": result.invocation.logical_start.isoformat(),
        "logical_end": result.invocation.logical_end.isoformat(),
        "window_semantics": result.invocation.window_semantics,
        "scheduled_for": spec.scheduled_for.isoformat(),
        "schedule_ref": result.invocation.schedule_ref,
        "admitted_at": result.admitted_at.isoformat(),
        "recovery_lag_seconds": recovery_lag_seconds,
        "missed_window_recovery": recovery_lag_seconds > 0,
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
        "native_online_schedule_enabled": False,
        "authoritative_quality_result_recorded": False,
        "data_product_version_created": False,
    }
    _write_json(runtime_dir / "jqdltb-schedule-window-submission-report.json", report)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deployment", required=True, type=Path)
    parser.add_argument("--runtime-dir", required=True, type=Path)
    parser.add_argument("--logical-start", default=DEFAULT_LOGICAL_START)
    parser.add_argument("--logical-end", default=DEFAULT_LOGICAL_END)
    parser.add_argument("--scheduled-for", default=DEFAULT_SCHEDULED_FOR)
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
                scheduled_for=_timestamp(args.scheduled_for, "scheduled_for"),
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
