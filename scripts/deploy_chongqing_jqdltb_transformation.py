#!/usr/bin/env python3
"""Deploy the approval-bound Chongqing JQDLTB transformation workflow."""

from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from data_agent.approval_case_authority import ApprovalCaseAuthority
from data_agent.dolphinscheduler_adapter import (
    DolphinSchedulerClient,
    DolphinSchedulerDefinitionBinding,
    DolphinSchedulerProfile,
    build_dolphinscheduler_jqdltb_transformation_plan_artifact,
    compile_dolphinscheduler_workflow,
)
from data_agent.platform_contracts import (
    JQDLTB_TRANSFORMATION_ACTION,
    JqdltbTransformationContract,
    JqdltbTransformationMode,
    PlatformDefinitionVersion,
    Resource,
    ResourceVersion,
    canonical_json_bytes,
    platform_definition_fingerprint,
)
from data_agent.platform_gateway import DefinitionRegistration, PlatformGateway

DEFINITION_URN = "gda://local-dev/definition/chongqing-jqdltb-transformation"
DEFINITION_VERSION_ID = uuid5(NAMESPACE_URL, f"{DEFINITION_URN}:v1")
SOURCE_RESOURCE_VERSION_ID = UUID("34441c77-2cf0-5ca2-83bf-81dd6a488d5b")
WORKFLOW_NAME = "gda_chongqing_jqdltb_transformation_v1"
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


def _validate_contract(
    contract: JqdltbTransformationContract,
    *,
    approval_authority: ApprovalCaseAuthority,
) -> None:
    if contract.mode is not JqdltbTransformationMode.EXECUTE:
        raise ValueError("transformation deployment requires mode=execute")
    if contract.source_resource_version_id != SOURCE_RESOURCE_VERSION_ID:
        raise ValueError("transformation contract source version is not the frozen JQDLTB source")
    case = contract.approval_case
    if case is None:
        raise ValueError("transformation deployment requires an embedded ApprovalCase")
    if case.action != JQDLTB_TRANSFORMATION_ACTION:
        raise ValueError("ApprovalCase action does not authorize JQDLTB transformation")
    authoritative = approval_authority.get(contract.tenant_id, case.approval_case_ref)
    if authoritative != case:
        raise ValueError("embedded ApprovalCase does not match authoritative ApprovalCase")
    if authoritative.target_fingerprint != contract.plan_sha256:
        raise ValueError("authoritative ApprovalCase does not bind the exact transformation plan")


def _raw_script(contract: JqdltbTransformationContract) -> str:
    encoded = base64.b64encode(
        canonical_json_bytes(contract.model_dump(mode="json"))
    ).decode("ascii")
    return f"""set -eu
contract_b64='{encoded}'
contract_json=$(printf '%s' "$contract_b64" | base64 --decode)
payload=$(printf '%s' "$contract_json" | python3 -c '
import json, sys
c = json.load(sys.stdin)
print(json.dumps({{
    "tenant_id": sys.argv[1],
    "run_id": sys.argv[2],
    "source_resource_version_id": sys.argv[3],
    "contract": c,
}}, separators=(",", ":")))
' "$gda_tenant_id" "$gda_run_id" "$gda_source_resource_version_id")
curl --fail --silent --show-error --retry 2 --connect-timeout 5 --max-time 1800 \\
  --header "Authorization: Bearer $(cat /run/secrets/gda-dataops-executor-token)" \\
  --header "Content-Type: application/json" \\
  --data "$payload" \\
  http://host.docker.internal:8090/v1/execute/chongqing-jqdltb-transformation
"""


def _definition(
    task_code: int,
    contract: JqdltbTransformationContract,
) -> PlatformDefinitionVersion:
    task = {
        "code": task_code,
        "name": "transform_jqdltb_to_governed_layers",
        "version": 1,
        "description": "Materialize the exact approved Chongqing JQDLTB transformation candidate",
        "delayTime": 0,
        "taskType": "SHELL",
        "taskParams": {
            "localParams": [],
            "rawScript": _raw_script(contract),
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
        "timeout": 1800,
        "taskGroupId": 0,
        "taskGroupPriority": 0,
        "cpuQuota": -1,
        "memoryMax": -1,
    }
    definition_document = {
        "schema": "gda.chongqing_jqdltb_transformation_definition.v1",
        "authority": {
            "scheduler": "dolphinscheduler",
            "approval_case": contract.approval_case.approval_case_ref,
            "contract_sha256": contract.contract_sha256,
            "plan_sha256": contract.plan_sha256,
            "data_product_publication": "forbidden_by_transformation_executor",
        },
        "dolphinscheduler": {
            "name": WORKFLOW_NAME,
            "description": "Approval-bound Chongqing Bishan JQDLTB transformation",
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
            "timeout_seconds": 1900,
            "execution_type": "PARALLEL",
        },
    }
    input_contract = {
        "source": {
            "semantic_type": "gis.land_use.parcel.source",
            "resource_version_id": str(SOURCE_RESOURCE_VERSION_ID),
            "access": "read_only",
        },
        "approval_case": {
            "approval_case_ref": contract.approval_case.approval_case_ref,
            "target_fingerprint": contract.plan_sha256,
        },
    }
    output_contract = {
        "candidate_layers": ["raw", "ods", "dim", "dwd", "ads", "quarantine"],
        "transformation_evidence": "required",
        "lineage": "required",
        "data_product_version": "forbidden",
    }
    fingerprint = platform_definition_fingerprint(
        orchestration_class="dataops",
        capability_id="land_use.jqdltb.transform",
        portability_class="provider_native",
        definition_document=definition_document,
        input_contract=input_contract,
        output_contract=output_contract,
    )
    return PlatformDefinitionVersion(
        tenant_id=contract.tenant_id,
        definition_urn=DEFINITION_URN,
        definition_version_id=DEFINITION_VERSION_ID,
        orchestration_class="dataops",
        capability_id="land_use.jqdltb.transform",
        portability_class="provider_native",
        definition_document=definition_document,
        input_contract=input_contract,
        output_contract=output_contract,
        definition_sha256=fingerprint,
    )


def deploy(
    *,
    profile_path: Path,
    contract_path: Path,
    runtime_dir: Path,
    approval_authority: ApprovalCaseAuthority | None = None,
) -> dict[str, Any]:
    profile = _profile(_read_json(profile_path))
    contract = JqdltbTransformationContract.model_validate(_read_json(contract_path))
    _validate_contract(
        contract,
        approval_authority=approval_authority or ApprovalCaseAuthority(),
    )
    state_path = runtime_dir / "jqdltb-transformation-definition-state.json"
    gateway = PlatformGateway()
    with DolphinSchedulerClient(profile) as client:
        state = _read_json(state_path) if state_path.exists() else None
        if state is None:
            task_code = client.generate_task_codes(1)[0]
            _write_json(
                state_path,
                {
                    "schema": "gda.jqdltb_transformation_definition_state.v1",
                    "task_code": task_code,
                },
            )
        else:
            task_code = int(state["task_code"])
        definition = _definition(task_code, contract)
        created_at = contract.created_at
        registration = DefinitionRegistration(
            resource=Resource(
                tenant_id=contract.tenant_id,
                resource_urn=DEFINITION_URN,
                resource_kind="definition",
                authority_system="gda-control",
                authority_locator="definitions/chongqing-jqdltb-transformation/v1",
                owner_ref="team:data-platform",
                governance_ref={"classification": "internal", "release_stage": "sandbox"},
            ),
            resource_version=ResourceVersion(
                tenant_id=contract.tenant_id,
                resource_urn=DEFINITION_URN,
                resource_version_id=DEFINITION_VERSION_ID,
                version_key="v1",
                content_sha256=definition.definition_sha256,
                authority_version_ref={
                    "schema": "gda.chongqing_jqdltb_transformation_definition.v1"
                },
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
                "multiple DolphinScheduler workflows share the JQDLTB transformation name"
            )
        workflow_created = not existing
        if existing:
            item = existing[0]
            binding = DolphinSchedulerDefinitionBinding(
                tenant_id=contract.tenant_id,
                definition_version_id=DEFINITION_VERSION_ID,
                project_code=profile.project_code,
                workflow_definition_code=int(item["code"]),
                workflow_definition_version=int(item["version"]),
                compiled_sha256=spec.compiled_sha256,
            )
            client.release_workflow(binding.workflow_definition_code)
        else:
            binding = client.create_workflow(spec)
    plan_artifact = build_dolphinscheduler_jqdltb_transformation_plan_artifact(
        binding,
        contract,
        created_by=WORKLOAD_SUBJECT,
        created_at=contract.created_at,
    )
    plan_result = gateway.record_artifact(plan_artifact)
    report = {
        "schema": "gda.chongqing_jqdltb_transformation_deployment.v1",
        "status": "ready",
        "definition_version_id": str(DEFINITION_VERSION_ID),
        "definition_sha256": definition.definition_sha256,
        "compiled_sha256": spec.compiled_sha256,
        "contract_sha256": contract.contract_sha256,
        "plan_sha256": contract.plan_sha256,
        "approval_case_ref": contract.approval_case.approval_case_ref,
        "source_resource_version_id": str(SOURCE_RESOURCE_VERSION_ID),
        "contract_path": str(contract_path.resolve()),
        "project_code": profile.project_code,
        "workflow_definition_code": binding.workflow_definition_code,
        "workflow_definition_version": binding.workflow_definition_version,
        "binding_artifact_id": str(plan_artifact.artifact_id),
        "execution_plan_artifact_id": str(plan_artifact.artifact_id),
        "plan_artifact_created": plan_result.created,
        "definition_created": definition_result.created,
        "workflow_created": workflow_created,
        "authoritative_quality_result_recorded": False,
        "platform_run_created": False,
        "data_product_version_created": False,
    }
    _write_json(runtime_dir / "jqdltb-transformation-deployment-report.json", report)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True, type=Path)
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument("--runtime-dir", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    print(
        json.dumps(
            deploy(
                profile_path=args.profile,
                contract_path=args.contract,
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
