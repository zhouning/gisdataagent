#!/usr/bin/env python3
"""Verify governed manual-run acceptance against real Chongqing evidence."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any
from uuid import UUID

from data_agent.dataops_invocation import parse_dataops_invocation_version
from data_agent.dolphinscheduler_adapter import (
    DolphinSchedulerClient,
    DolphinSchedulerProfile,
    parse_dolphinscheduler_binding_artifact,
)
from data_agent.platform_gateway import PlatformGateway

WORKLOAD_SUBJECT = "workload:dolphinscheduler-gda-dataops"
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


def _profile(value: dict[str, Any]) -> DolphinSchedulerProfile:
    token = Path(str(value["token_file"])).read_text(encoding="utf-8").strip()
    return DolphinSchedulerProfile(
        base_url=str(value["base_url"]),
        access_token=token,
        project_code=int(value["project_code"]),
        workload_subject=WORKLOAD_SUBJECT,
        policy_evaluator_subject=POLICY_EVALUATOR,
        tenant_code=str(value["tenant_code"]),
        worker_group=str(value["worker_group"]),
        timezone_name="Asia/Tokyo",
    )


def audit(
    *,
    profile_path: Path,
    deployment_path: Path,
    submission_path: Path,
    finalization_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    profile = _profile(_read_json(profile_path))
    deployment = _read_json(deployment_path)
    submission = _read_json(submission_path)
    finalization = _read_json(finalization_path)
    tenant_id = "local-dev"
    run_id = UUID(submission["run_id"])
    invocation_version_id = UUID(submission["invocation_resource_version_id"])
    command_id = UUID(submission["dispatch_command_id"])
    quality_result_id = UUID(finalization["quality_result_id"])

    gateway = PlatformGateway()
    run = gateway.get_run(tenant_id, run_id)
    invocation_version = gateway.get_resource_version(
        tenant_id,
        invocation_version_id,
    )
    invocation = parse_dataops_invocation_version(invocation_version)
    command = gateway.get_command(tenant_id, command_id)
    quality = gateway.get_quality_result(tenant_id, quality_result_id)
    binding_artifact = gateway.get_artifact(
        tenant_id,
        UUID(deployment["binding_artifact_id"]),
    )
    binding = parse_dolphinscheduler_binding_artifact(binding_artifact)

    client = DolphinSchedulerClient(profile)
    try:
        matches = client.find_instances(binding, run, invocation)
        if len(matches) != 1:
            raise ValueError("manual Run must correlate to exactly one provider instance")
        instance = client.get_instance(
            matches[0].instance_id,
            binding.workflow_definition_code,
        )
        variables = client.get_instance_variables(instance.instance_id)
    finally:
        client.close()

    expected_correlation = DolphinSchedulerClient.start_params(run, invocation)
    gda_variables = {
        key: value for key, value in variables.items() if key.startswith("gda_")
    }
    terminal_replay_created = any(
        bool(finalization[name])
        for name in (
            "attempt_observation_created",
            "assessment_version_created",
            "lineage_created",
            "platform_run_transitioned",
            "data_product_version_created",
        )
    )
    atomic_replay_created = any(
        bool(submission[name])
        for name in (
            "invocation_resource_created",
            "invocation_version_created",
            "policy_artifact_created",
            "platform_run_created",
            "dispatch_command_created",
        )
    )
    checks = {
        "atomic_replay_created_nothing": not atomic_replay_created,
        "terminal_replay_created_nothing": not terminal_replay_created,
        "manual_request_identity_retained": (
            invocation.trigger_kind == "manual"
            and invocation.client_request_id == submission["client_request_id"]
            and invocation.requested_by == submission["requester_subject"]
        ),
        "human_to_workload_delegation_retained": (
            invocation.requested_by.startswith("human:")
            and run.subject_context.subject_type.value == "workload"
            and run.subject_context.delegated_by == invocation.requested_by
        ),
        "exactly_one_provider_instance": len(matches) == 1,
        "provider_succeeded": instance.state == "SUCCESS",
        "provider_uses_correlated_start": (
            instance.command_type == "START_PROCESS" and instance.schedule_time is None
        ),
        "provider_correlation_complete": all(
            variables.get(key) == value for key, value in expected_correlation.items()
        ),
        "provider_manual_request_correlation_present": (
            gda_variables.get("gda_client_request_id")
            == invocation.client_request_id
            and len(gda_variables) >= 13
        ),
        "dispatch_command_terminal": command.status.value == "done",
        "platform_run_quality_failed": (
            run.status.value == "failed"
            and finalization["quality_verdict"] == "failed"
            and quality.verdict.value == "failed"
        ),
        "real_source_scanned": finalization["records_scanned"] == 1555,
        "no_data_product_published": not finalization[
            "data_product_version_created"
        ],
    }
    report = {
        "schema": "gda.chongqing_jqdltb_manual_acceptance.v1",
        "status": "verified" if all(checks.values()) else "failed",
        "run_id": str(run.run_id),
        "request_sha256": submission["request_sha256"],
        "client_request_id": invocation.client_request_id,
        "requester_subject": invocation.requested_by,
        "workload_subject": (
            f"{run.subject_context.subject_type.value}:"
            f"{run.subject_context.subject_id}"
        ),
        "delegated_by": run.subject_context.delegated_by,
        "invocation_version_id": str(invocation_version.resource_version_id),
        "invocation_sha256": invocation.invocation_sha256,
        "logical_start": invocation.logical_start.isoformat(),
        "logical_end": invocation.logical_end.isoformat(),
        "admitted_at": submission["admitted_at"],
        "dispatch_command_id": str(command.command_id),
        "dispatch_command_status": command.status.value,
        "provider_instance_count": len(matches),
        "provider_instance_id": instance.instance_id,
        "provider_state": instance.state,
        "provider_command_type": instance.command_type,
        "provider_schedule_time": instance.schedule_time,
        "provider_gda_variable_count": len(gda_variables),
        "provider_correlation": {
            key: gda_variables[key] for key in sorted(gda_variables)
        },
        "quality_result_id": str(quality.quality_result_id),
        "quality_verdict": quality.verdict.value,
        "records_scanned": finalization["records_scanned"],
        "platform_run_status": run.status.value,
        "platform_run_state_version": run.state_version,
        "data_product_version_created": finalization[
            "data_product_version_created"
        ],
        "checks": checks,
    }
    _write_json(output_path, report)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True, type=Path)
    parser.add_argument("--deployment", required=True, type=Path)
    parser.add_argument("--submission", required=True, type=Path)
    parser.add_argument("--finalization", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = audit(
        profile_path=args.profile,
        deployment_path=args.deployment,
        submission_path=args.submission,
        finalization_path=args.finalization,
        output_path=args.output,
    )
    print(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True))
    return 0 if report["status"] == "verified" else 1


if __name__ == "__main__":
    raise SystemExit(main())
