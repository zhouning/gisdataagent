"""DolphinScheduler definition for governed spatial anonymization Runs."""

from __future__ import annotations

from urllib.parse import urlsplit
from uuid import UUID

from .platform_contracts import (
    PlatformDefinitionVersion,
    platform_definition_fingerprint,
)
from .spatial_anonymization_run import SPATIAL_ANONYMIZATION_SEMANTIC_TYPE

SPATIAL_ANONYMIZATION_DEFINITION_SCHEMA = (
    "gda.spatial_anonymization_dataops_definition.v1"
)
SPATIAL_ANONYMIZATION_CAPABILITY_ID = "spatial.anonymize"
SPATIAL_ANONYMIZATION_EXECUTOR_PATH = (
    "/v1/execute/spatial-anonymization-run"
)


def _executor_url(value: str) -> str:
    normalized = value.rstrip("/")
    parts = urlsplit(normalized)
    if (
        parts.scheme not in {"http", "https"}
        or not parts.netloc
        or parts.username
        or parts.password
        or parts.query
        or parts.fragment
        or parts.path not in {"", "/"}
    ):
        raise ValueError("executor_base_url must be an origin without credentials")
    return normalized


def spatial_anonymization_raw_script(executor_base_url: str) -> str:
    endpoint = f"{_executor_url(executor_base_url)}{SPATIAL_ANONYMIZATION_EXECUTOR_PATH}"
    return f"""set -eu
payload='{{\"tenant_id\":\"${{gda_tenant_id}}\",'
payload=$payload'\"run_id\":\"${{gda_run_id}}\"}}'
curl --fail --silent --show-error --retry 2 --connect-timeout 5 --max-time 3600 \\
  --header \"Authorization: Bearer $(cat /run/secrets/gda-dataops-executor-token)\" \\
  --header \"Content-Type: application/json\" \\
  --data \"$payload\" \\
  {endpoint}
"""


def build_spatial_anonymization_definition(
    *,
    tenant_id: str,
    definition_urn: str,
    definition_version_id: UUID,
    task_code: int,
    worker_group: str,
    executor_base_url: str,
    workflow_name: str = "gda_spatial_anonymization_run_v1",
) -> PlatformDefinitionVersion:
    if isinstance(task_code, bool) or not isinstance(task_code, int) or task_code <= 0:
        raise ValueError("task_code must be a positive integer")
    if not worker_group.strip():
        raise ValueError("worker_group must not be blank")
    task = {
        "code": task_code,
        "name": "execute_spatial_anonymization_run",
        "version": 1,
        "description": "Execute one immutable governed spatial anonymization Run",
        "delayTime": 0,
        "taskType": "SHELL",
        "taskParams": {
            "localParams": [],
            "rawScript": spatial_anonymization_raw_script(executor_base_url),
            "resourceList": [],
        },
        "flag": "YES",
        "taskPriority": "MEDIUM",
        "workerGroup": worker_group.strip(),
        "environmentCode": -1,
        "failRetryTimes": 0,
        "failRetryInterval": 1,
        "timeoutFlag": "OPEN",
        "timeoutNotifyStrategy": "WARN",
        "timeout": 3600,
        "taskGroupId": 0,
        "taskGroupPriority": 0,
        "cpuQuota": -1,
        "memoryMax": -1,
    }
    definition_document = {
        "schema": SPATIAL_ANONYMIZATION_DEFINITION_SCHEMA,
        "authority": {
            "scheduler": "dolphinscheduler",
            "request": "gda-control-resource-version",
            "security_receipt": "gda-control-postgresql",
            "run_terminal_verdict": "gda-control-evidence-gate",
        },
        "dolphinscheduler": {
            "name": workflow_name,
            "description": "Governed PostGIS spatial anonymization from an immutable Run binding",
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
            "global_params": [],
            "timeout_seconds": 3900,
            "execution_type": "PARALLEL",
        },
    }
    input_contract = {
        "anonymization_request": {
            "semantic_type": SPATIAL_ANONYMIZATION_SEMANTIC_TYPE,
            "authority": "gda-control-resource-version",
            "runtime_parameters": ["gda_tenant_id", "gda_run_id"],
        }
    }
    output_contract = {
        "postgis_output": "required",
        "gist_index": "required",
        "security_receipt": "required",
        "security_outcome": "required_or_reconciled",
        "run_success_evidence": "separate_gate",
    }
    fingerprint = platform_definition_fingerprint(
        orchestration_class="dataops",
        capability_id=SPATIAL_ANONYMIZATION_CAPABILITY_ID,
        portability_class="provider_native",
        definition_document=definition_document,
        input_contract=input_contract,
        output_contract=output_contract,
    )
    return PlatformDefinitionVersion(
        tenant_id=tenant_id,
        definition_urn=definition_urn,
        definition_version_id=definition_version_id,
        orchestration_class="dataops",
        capability_id=SPATIAL_ANONYMIZATION_CAPABILITY_ID,
        portability_class="provider_native",
        definition_document=definition_document,
        input_contract=input_contract,
        output_contract=output_contract,
        definition_sha256=fingerprint,
    )
