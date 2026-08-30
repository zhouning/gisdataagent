#!/usr/bin/env python3
"""Register and deploy the real Chongqing JQDLTB audit definition."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from data_agent.dolphinscheduler_adapter import (
    DolphinSchedulerAdapter,
    DolphinSchedulerClient,
    DolphinSchedulerDefinitionBinding,
    DolphinSchedulerProfile,
    compile_dolphinscheduler_workflow,
)
from data_agent.platform_contracts import (
    PlatformDefinitionVersion,
    Resource,
    ResourceVersion,
    platform_definition_fingerprint,
)
from data_agent.platform_gateway import DefinitionRegistration, PlatformGateway

DEFINITION_URN = "gda://local-dev/definition/chongqing-jqdltb-full-audit"
DEFINITION_VERSION_ID = uuid5(NAMESPACE_URL, f"{DEFINITION_URN}:v1")
SOURCE_RESOURCE_VERSION_ID = UUID("34441c77-2cf0-5ca2-83bf-81dd6a488d5b")
WORKFLOW_NAME = "gda_chongqing_jqdltb_full_audit_v1"
WORKLOAD_SUBJECT = "workload:dolphinscheduler-gda-dataops"
POLICY_EVALUATOR_SUBJECT = "workload:gda-policy-evaluator"


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
    token_path = Path(str(value["token_file"]))
    token = token_path.read_text(encoding="utf-8").strip()
    return DolphinSchedulerProfile(
        base_url=str(value["base_url"]),
        access_token=token,
        project_code=int(value["project_code"]),
        workload_subject=WORKLOAD_SUBJECT,
        policy_evaluator_subject=POLICY_EVALUATOR_SUBJECT,
        tenant_code=str(value["tenant_code"]),
        worker_group=str(value["worker_group"]),
        timezone_name="Asia/Tokyo",
    )


def _raw_script() -> str:
    return """set -eu
payload='{\"tenant_id\":\"${gda_tenant_id}\",'
payload=$payload'\"run_id\":\"${gda_run_id}\",'
payload=$payload'\"source_resource_version_id\":\"${gda_source_resource_version_id}\"}'
curl --fail --silent --show-error --retry 2 --connect-timeout 5 --max-time 300 \\
  --header \"Authorization: Bearer $(cat /run/secrets/gda-dataops-executor-token)\" \\
  --header \"Content-Type: application/json\" \\
  --data \"$payload\" \\
  http://host.docker.internal:8090/v1/execute/chongqing-jqdltb-audit
"""


def _definition(task_code: int) -> PlatformDefinitionVersion:
    task = {
        "code": task_code,
        "name": "audit_jqdltb_full_dataset",
        "version": 1,
        "description": "Run the governed full-dataset JQDLTB quality audit",
        "delayTime": 0,
        "taskType": "SHELL",
        "taskParams": {
            "localParams": [],
            "rawScript": _raw_script(),
            "resourceList": [],
        },
        "flag": "YES",
        "taskPriority": "MEDIUM",
        "workerGroup": "gda_dataops_sandbox",
        "environmentCode": -1,
        "failRetryTimes": 0,
        "failRetryInterval": 1,
        "timeoutFlag": "OPEN",
        "timeoutNotifyStrategy": "WARN",
        "timeout": 600,
        "taskGroupId": 0,
        "taskGroupPriority": 0,
        "cpuQuota": -1,
        "memoryMax": -1,
    }
    definition_document = {
        "schema": "gda.chongqing_jqdltb_dataops_definition.v1",
        "authority": {
            "scheduler": "dolphinscheduler",
            "quality_result": "gda-control-postgresql",
            "data_product_publication": "not_permitted_when_quality_fails",
        },
        "dolphinscheduler": {
            "name": WORKFLOW_NAME,
            "description": "Full audit of the immutable Chongqing Bishan JQDLTB source",
            "task_definitions": [task],
            "task_relations": [
                {
                    "name": "",
                    "preTaskCode": 0,
                    "preTaskVersion": 0,
                    "postTaskCode": task_code,
                    "postTaskVersion": 1,
                    "conditionType": "NONE",
                    "conditionParams": {},
                }
            ],
            "locations": [{"taskCode": task_code, "x": 180, "y": 120}],
            "global_params": [
                {
                    "prop": "gda_source_resource_version_id",
                    "direct": "IN",
                    "type": "VARCHAR",
                    "value": str(SOURCE_RESOURCE_VERSION_ID),
                }
            ],
            "timeout_seconds": 900,
            "execution_type": "PARALLEL",
        },
    }
    input_contract = {
        "source": {
            "semantic_type": "gis.land_use.parcel.source",
            "resource_version_id": str(SOURCE_RESOURCE_VERSION_ID),
            "bundle_sha256": "cae2047f6b72127e5eae0651909761c0f06d8c3e0491921dbd806c653ba715c3",
            "access": "read_only",
        }
    }
    output_contract = {
        "quality_result": "authoritative",
        "evidence_artifact": "required",
        "lineage": "required_before_terminalization",
        "data_product_version": "forbidden_when_quality_fails",
    }
    fingerprint = platform_definition_fingerprint(
        orchestration_class="dataops",
        capability_id="land_use.jqdltb.audit",
        portability_class="provider_native",
        definition_document=definition_document,
        input_contract=input_contract,
        output_contract=output_contract,
    )
    return PlatformDefinitionVersion(
        tenant_id="local-dev",
        definition_urn=DEFINITION_URN,
        definition_version_id=DEFINITION_VERSION_ID,
        orchestration_class="dataops",
        capability_id="land_use.jqdltb.audit",
        portability_class="provider_native",
        definition_document=definition_document,
        input_contract=input_contract,
        output_contract=output_contract,
        definition_sha256=fingerprint,
    )


def deploy(*, profile_path: Path, runtime_dir: Path) -> dict[str, Any]:
    profile = _profile(_read_json(profile_path))
    state_path = runtime_dir / "jqdltb-definition-state.json"
    gateway = PlatformGateway()
    with DolphinSchedulerClient(profile) as client:
        state = _read_json(state_path) if state_path.exists() else None
        if state is None:
            task_code = client.generate_task_codes(1)[0]
            _write_json(
                state_path,
                {
                    "schema": "gda.jqdltb_definition_state.v1",
                    "task_code": task_code,
                },
            )
        else:
            task_code = int(state["task_code"])

        definition = _definition(task_code)
        created_at = datetime.fromisoformat("2026-08-01T00:00:00+09:00")
        registration = DefinitionRegistration(
            resource=Resource(
                tenant_id="local-dev",
                resource_urn=DEFINITION_URN,
                resource_kind="definition",
                authority_system="gda-control",
                authority_locator="definitions/chongqing-jqdltb-full-audit/v1",
                owner_ref="team:data-platform",
                governance_ref={"classification": "internal", "release_stage": "sandbox"},
            ),
            resource_version=ResourceVersion(
                tenant_id="local-dev",
                resource_urn=DEFINITION_URN,
                resource_version_id=DEFINITION_VERSION_ID,
                version_key="v1",
                content_sha256=definition.definition_sha256,
                authority_version_ref={"schema": "gda.chongqing_jqdltb_dataops_definition.v1"},
                created_by=WORKLOAD_SUBJECT,
                created_at=created_at,
            ),
            definition=definition,
        )
        definition_result = gateway.register_definition(registration)
        spec = compile_dolphinscheduler_workflow(definition)
        existing = [
            item
            for item in client.list_workflows(search_value=WORKFLOW_NAME)
            if item.get("name") == WORKFLOW_NAME
        ]
        if len(existing) > 1:
            raise RuntimeError(
                "multiple DolphinScheduler workflows share the JQDLTB definition name"
            )
        workflow_created = not existing
        if existing:
            item = existing[0]
            binding = DolphinSchedulerDefinitionBinding(
                tenant_id="local-dev",
                definition_version_id=DEFINITION_VERSION_ID,
                project_code=profile.project_code,
                workflow_definition_code=int(item["code"]),
                workflow_definition_version=int(item["version"]),
                compiled_sha256=spec.compiled_sha256,
            )
            client.release_workflow(binding.workflow_definition_code)
        else:
            binding = client.create_workflow(spec)

    adapter = DolphinSchedulerAdapter(profile, gateway=gateway)
    try:
        binding_result = adapter.persist_binding(
            binding,
            actor_subject=WORKLOAD_SUBJECT,
            created_at=created_at,
        )
    finally:
        adapter.client.close()
    report = {
        "schema": "gda.chongqing_jqdltb_dataops_deployment.v1",
        "status": "ready",
        "definition_version_id": str(DEFINITION_VERSION_ID),
        "definition_sha256": definition.definition_sha256,
        "compiled_sha256": spec.compiled_sha256,
        "source_resource_version_id": str(SOURCE_RESOURCE_VERSION_ID),
        "project_code": profile.project_code,
        "workflow_definition_code": binding.workflow_definition_code,
        "workflow_definition_version": binding.workflow_definition_version,
        "binding_artifact_id": str(binding_result.value.artifact_id),
        "definition_created": definition_result.created,
        "workflow_created": workflow_created,
        "binding_created": binding_result.created,
        "authoritative_quality_result_recorded": False,
        "platform_run_created": False,
        "data_product_version_created": False,
    }
    _write_json(runtime_dir / "jqdltb-deployment-report.json", report)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True, type=Path)
    parser.add_argument("--runtime-dir", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    print(
        json.dumps(
            deploy(profile_path=args.profile, runtime_dir=args.runtime_dir),
            ensure_ascii=True,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
