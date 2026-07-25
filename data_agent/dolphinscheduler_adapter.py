"""DolphinScheduler 3.4.2 adapter for PlatformRun correlation.

The adapter compiles provider-specific workflow documents and bridges external
workflow instances into the GDA control ledger. It is not a scheduler, queue,
retry engine, or source of platform terminal verdicts.
"""

from __future__ import annotations

import argparse
import json
import re
import stat
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Self
from urllib.parse import urlsplit
from uuid import UUID, uuid5
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    TypeAdapter,
    field_validator,
    model_validator,
)

from .platform_contracts import (
    Artifact,
    FrameworkAttemptObservation,
    PlatformDefinitionVersion,
    PlatformRun,
    RunStatus,
    TenantId,
    canonical_json_bytes,
    canonical_json_fingerprint,
)
from .platform_gateway import GatewayWriteResult, PlatformGateway

DOLPHINSCHEDULER_SERVER_VERSION = "3.4.2"
DOLPHINSCHEDULER_API_PROFILE = "3.4"
DOLPHINSCHEDULER_ADAPTER_SCHEMA = "gda.dolphinscheduler_adapter.v1"
DOLPHINSCHEDULER_BINDING_SCHEMA = "gda.dolphinscheduler_definition_binding.v1"
DOLPHINSCHEDULER_BINDING_MEDIA_TYPE = (
    "application/vnd.gda.dolphinscheduler-binding+json"
)
DOLPHINSCHEDULER_RELEASE_URL = (
    "https://github.com/apache/dolphinscheduler/releases/tag/3.4.2"
)
_TENANT_ADAPTER = TypeAdapter(TenantId)
_WORKFLOW_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.-]{0,254}$")
_SECRET_KEYS = frozenset(
    {
        "access_key",
        "accesskey",
        "api_key",
        "apikey",
        "password",
        "passwd",
        "private_key",
        "privatekey",
        "secret",
        "secret_key",
        "secretkey",
        "token",
    }
)
_CORRELATION_KEYS = (
    "gda_run_id",
    "gda_tenant_id",
    "gda_definition_version_id",
    "gda_idempotency_key",
)
_RUNNING_STATES = frozenset(
    {
        "RUNNING_EXECUTION",
        "READY_PAUSE",
        "READY_STOP",
        "SERIAL_WAIT",
    }
)
_TERMINAL_PROVIDER_STATES = frozenset(
    {
        "SUCCESS",
        "FAILURE",
        "STOP",
        "PAUSE",
    }
)


class DolphinSchedulerError(RuntimeError):
    code = "dolphinscheduler_error"


class DolphinSchedulerConfigurationError(DolphinSchedulerError):
    code = "dolphinscheduler_configuration_error"


class DolphinSchedulerContractError(DolphinSchedulerError):
    code = "dolphinscheduler_contract_error"


class DolphinSchedulerUnavailableError(DolphinSchedulerError):
    code = "dolphinscheduler_unavailable"


class DolphinSchedulerRejectedError(DolphinSchedulerError):
    code = "dolphinscheduler_rejected"


class DolphinSchedulerProtocolError(DolphinSchedulerError):
    code = "dolphinscheduler_protocol_error"


class DolphinSchedulerCorrelationNotFoundError(DolphinSchedulerError):
    code = "dolphinscheduler_correlation_not_found"


class DolphinSchedulerCorrelationConflictError(DolphinSchedulerError):
    code = "dolphinscheduler_correlation_conflict"


class DolphinSchedulerReconciliationRequired(DolphinSchedulerError):
    code = "dolphinscheduler_reconciliation_required"


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DolphinSchedulerProfile(_FrozenModel):
    base_url: str
    access_token: SecretStr
    project_code: int = Field(gt=0)
    tenant_code: str = Field(default="default", min_length=1, max_length=128)
    worker_group: str = Field(default="default", min_length=1, max_length=255)
    timezone_name: str = Field(default="UTC", min_length=1, max_length=64)
    request_timeout_seconds: float = Field(default=15.0, gt=0, le=300)
    reconciliation_page_limit: int = Field(default=5, ge=1, le=100)
    api_profile: Literal["3.4"] = DOLPHINSCHEDULER_API_PROFILE
    server_version: Literal["3.4.2"] = DOLPHINSCHEDULER_SERVER_VERSION

    @field_validator("base_url")
    @classmethod
    def _safe_base_url(cls, value: str) -> str:
        normalized = value.rstrip("/")
        parts = urlsplit(normalized)
        if parts.scheme not in {"http", "https"} or not parts.netloc:
            raise ValueError("base_url must be an absolute HTTP(S) URL")
        if parts.username or parts.password or parts.query or parts.fragment:
            raise ValueError(
                "base_url must not contain credentials, query, or fragment"
            )
        return normalized

    @field_validator("access_token")
    @classmethod
    def _nonempty_token(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().strip():
            raise ValueError("access_token must not be empty")
        return value

    @field_validator("timezone_name")
    @classmethod
    def _valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("timezone_name must identify an IANA timezone") from exc
        return value


class DolphinSchedulerWorkflowDocument(_FrozenModel):
    name: str
    description: str = ""
    task_definitions: tuple[dict[str, Any], ...]
    task_relations: tuple[dict[str, Any], ...]
    locations: tuple[dict[str, Any], ...] = ()
    global_params: tuple[dict[str, Any], ...] = ()
    timeout_seconds: int = Field(default=0, ge=0)
    execution_type: Literal[
        "PARALLEL", "SERIAL_WAIT", "SERIAL_DISCARD", "SERIAL_PRIORITY"
    ] = "PARALLEL"
    api_profile: Literal["3.4"] = DOLPHINSCHEDULER_API_PROFILE

    @field_validator("name")
    @classmethod
    def _valid_name(cls, value: str) -> str:
        if not _WORKFLOW_NAME_RE.fullmatch(value):
            raise ValueError("workflow name contains unsupported characters")
        return value

    @model_validator(mode="after")
    def _nonempty_graph(self) -> DolphinSchedulerWorkflowDocument:
        if not self.task_definitions:
            raise ValueError("DolphinScheduler workflow requires at least one task")
        return self


class DolphinSchedulerWorkflowSpec(_FrozenModel):
    tenant_id: TenantId
    definition_version_id: UUID
    definition_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    name: str
    description: str
    task_definitions: tuple[dict[str, Any], ...]
    task_relations: tuple[dict[str, Any], ...]
    locations: tuple[dict[str, Any], ...]
    global_params: tuple[dict[str, Any], ...]
    timeout_seconds: int = Field(ge=0)
    execution_type: str
    compiled_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    api_profile: Literal["3.4"] = DOLPHINSCHEDULER_API_PROFILE

    @model_validator(mode="after")
    def _valid_fingerprint(self) -> DolphinSchedulerWorkflowSpec:
        expected = canonical_json_fingerprint(
            self.model_dump(mode="json", exclude={"compiled_sha256"})
        )
        if self.compiled_sha256 != expected:
            raise ValueError("compiled_sha256 does not match workflow spec")
        return self

    def as_create_form(self) -> dict[str, str]:
        return {
            "name": self.name,
            "description": self.description,
            "globalParams": _json(list(self.global_params)),
            "locations": _json(list(self.locations)),
            "timeout": str(self.timeout_seconds),
            "taskRelationJson": _json(list(self.task_relations)),
            "taskDefinitionJson": _json(list(self.task_definitions)),
            "executionType": self.execution_type,
        }


class DolphinSchedulerDefinitionBinding(_FrozenModel):
    tenant_id: TenantId
    definition_version_id: UUID
    project_code: int = Field(gt=0)
    workflow_definition_code: int = Field(gt=0)
    workflow_definition_version: int = Field(ge=1)
    compiled_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    api_profile: Literal["3.4"] = DOLPHINSCHEDULER_API_PROFILE
    server_version: Literal["3.4.2"] = DOLPHINSCHEDULER_SERVER_VERSION


class DolphinSchedulerBindingEnvelope(_FrozenModel):
    binding_schema: Literal["gda.dolphinscheduler_definition_binding.v1"] = Field(
        default=DOLPHINSCHEDULER_BINDING_SCHEMA,
        alias="schema",
    )
    binding: DolphinSchedulerDefinitionBinding


class DolphinSchedulerInstance(_FrozenModel):
    instance_id: int = Field(gt=0)
    workflow_definition_code: int = Field(gt=0)
    workflow_definition_version: int | None = Field(default=None, ge=1)
    state: str = Field(min_length=1, max_length=128)
    name: str | None = None
    start_time: str | None = None
    end_time: str | None = None


class DolphinSchedulerDispatchResult(_FrozenModel):
    run: PlatformRun
    observation: FrameworkAttemptObservation
    workflow_instance_id: int = Field(gt=0)
    observation_created: bool
    recovered: bool = False


class DolphinSchedulerReconcileResult(_FrozenModel):
    run: PlatformRun
    observation: FrameworkAttemptObservation
    workflow_instance_id: int = Field(gt=0)
    provider_state: str
    observation_created: bool


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _binding_artifact_id(binding: DolphinSchedulerDefinitionBinding) -> UUID:
    identity = binding.model_dump(mode="json")
    return uuid5(
        binding.definition_version_id,
        f"dolphinscheduler-binding:{canonical_json_fingerprint(identity)}",
    )


def _binding_artifact_key(binding: DolphinSchedulerDefinitionBinding) -> str:
    return (
        f"dolphinscheduler-binding:{binding.workflow_definition_code}:"
        f"v{binding.workflow_definition_version}"
    )


def _binding_storage_uri(tenant_id: str, artifact_id: UUID) -> str:
    return f"postgresql://gda-control/execution-plans/{tenant_id}/{artifact_id}"


def build_dolphinscheduler_binding_artifact(
    binding: DolphinSchedulerDefinitionBinding,
    *,
    created_by: str,
    created_at: datetime,
) -> Artifact:
    """Build the immutable execution-plan evidence for a provider binding."""
    envelope = DolphinSchedulerBindingEnvelope(binding=binding)
    manifest = envelope.model_dump(mode="json", by_alias=True)
    artifact_id = _binding_artifact_id(binding)
    content = canonical_json_bytes(manifest)
    return Artifact(
        tenant_id=binding.tenant_id,
        artifact_id=artifact_id,
        artifact_key=_binding_artifact_key(binding),
        artifact_role="execution_plan",
        storage_uri=_binding_storage_uri(binding.tenant_id, artifact_id),
        media_type=DOLPHINSCHEDULER_BINDING_MEDIA_TYPE,
        content_sha256=canonical_json_fingerprint(manifest),
        size_bytes=len(content),
        run_id=None,
        resource_version_id=binding.definition_version_id,
        manifest=manifest,
        created_by=created_by,
        created_at=created_at,
    )


def parse_dolphinscheduler_binding_artifact(
    artifact: Artifact,
) -> DolphinSchedulerDefinitionBinding:
    """Validate every immutable artifact field before returning its binding."""
    try:
        envelope = DolphinSchedulerBindingEnvelope.model_validate(artifact.manifest)
    except Exception as exc:
        raise DolphinSchedulerContractError(
            "binding artifact manifest does not satisfy the envelope contract"
        ) from exc

    binding = envelope.binding
    artifact_id = _binding_artifact_id(binding)
    expected = {
        "tenant_id": binding.tenant_id,
        "artifact_id": artifact_id,
        "artifact_key": _binding_artifact_key(binding),
        "artifact_role": "execution_plan",
        "storage_uri": _binding_storage_uri(binding.tenant_id, artifact_id),
        "media_type": DOLPHINSCHEDULER_BINDING_MEDIA_TYPE,
        "content_sha256": canonical_json_fingerprint(artifact.manifest),
        "size_bytes": len(canonical_json_bytes(artifact.manifest)),
        "run_id": None,
        "resource_version_id": binding.definition_version_id,
    }
    actual = artifact.model_dump(mode="python", include=set(expected))
    actual["artifact_role"] = getattr(
        artifact.artifact_role, "value", artifact.artifact_role
    )
    mismatches = [name for name, value in expected.items() if actual[name] != value]
    if mismatches:
        raise DolphinSchedulerContractError(
            "binding artifact metadata does not match its manifest"
        )
    return binding


def _reject_inline_secrets(value: Any, path: str = "definition") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).strip().lower().replace("-", "_")
            if normalized in _SECRET_KEYS and child not in (None, "", [], {}):
                raise DolphinSchedulerContractError(
                    f"inline secret material is forbidden at {path}.{key}"
                )
            _reject_inline_secrets(child, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _reject_inline_secrets(child, f"{path}[{index}]")


def _global_param(prop: str, value: str) -> dict[str, str]:
    return {"prop": prop, "direct": "IN", "type": "VARCHAR", "value": value}


def compile_dolphinscheduler_workflow(
    definition: PlatformDefinitionVersion,
) -> DolphinSchedulerWorkflowSpec:
    if definition.orchestration_class.value != "dataops":
        raise DolphinSchedulerContractError(
            "DolphinScheduler only accepts dataops definitions"
        )
    raw = definition.definition_document.get("dolphinscheduler")
    if not isinstance(raw, dict):
        raise DolphinSchedulerContractError(
            "definition_document.dolphinscheduler is required"
        )
    try:
        document = DolphinSchedulerWorkflowDocument.model_validate(raw)
    except Exception as exc:
        raise DolphinSchedulerContractError(
            "DolphinScheduler workflow document is invalid"
        ) from exc
    _reject_inline_secrets(document.model_dump(mode="python"))

    reserved = {
        "gda_definition_sha256": definition.definition_sha256,
        "gda_definition_version_id": str(definition.definition_version_id),
        "gda_definition_urn": definition.definition_urn,
        "gda_tenant_id": definition.tenant_id,
    }
    params_by_name: dict[str, dict[str, Any]] = {}
    for item in document.global_params:
        prop = str(item.get("prop") or "")
        if not prop:
            raise DolphinSchedulerContractError("global parameter prop is required")
        if prop in reserved:
            continue
        params_by_name[prop] = item
    for prop, value in reserved.items():
        params_by_name[prop] = _global_param(prop, value)

    payload = {
        "tenant_id": definition.tenant_id,
        "definition_version_id": definition.definition_version_id,
        "definition_sha256": definition.definition_sha256,
        "name": document.name,
        "description": document.description,
        "task_definitions": document.task_definitions,
        "task_relations": document.task_relations,
        "locations": document.locations,
        "global_params": tuple(params_by_name[key] for key in sorted(params_by_name)),
        "timeout_seconds": document.timeout_seconds,
        "execution_type": document.execution_type,
        "api_profile": document.api_profile,
    }
    fingerprint = canonical_json_fingerprint(
        DolphinSchedulerWorkflowSpec.model_construct(
            **payload, compiled_sha256="0" * 64
        ).model_dump(mode="json", exclude={"compiled_sha256"})
    )
    return DolphinSchedulerWorkflowSpec(**payload, compiled_sha256=fingerprint)


def _page_items(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        items = value
    elif isinstance(value, dict):
        items = None
        for key in ("totalList", "records", "items", "list"):
            nested = value.get(key)
            if isinstance(nested, list):
                items = nested
                break
        if items is None:
            raise DolphinSchedulerProtocolError(
                "DolphinScheduler paged response has an unknown shape"
            )
    else:
        raise DolphinSchedulerProtocolError(
            "DolphinScheduler paged response is invalid"
        )
    if not all(isinstance(item, dict) for item in items):
        raise DolphinSchedulerProtocolError(
            "DolphinScheduler paged response contains an invalid item"
        )
    return items


def _collect_variables(value: Any, result: dict[str, str]) -> None:
    if isinstance(value, dict):
        prop = value.get("prop") or value.get("name")
        variable_value = value.get("value")
        if isinstance(prop, str) and variable_value is not None:
            result[prop] = str(variable_value)
        for key, child in value.items():
            if key in _CORRELATION_KEYS and child is not None:
                result[key] = str(child)
            _collect_variables(child, result)
    elif isinstance(value, list):
        for child in value:
            _collect_variables(child, result)


def _instance_from_payload(
    payload: dict[str, Any], fallback_definition_code: int
) -> DolphinSchedulerInstance:
    instance_id = payload.get("id") or payload.get("workflowInstanceId")
    definition_code = (
        payload.get("workflowDefinitionCode")
        or payload.get("processDefinitionCode")
        or fallback_definition_code
    )
    state = payload.get("state") or payload.get("stateType") or "UNKNOWN"
    return DolphinSchedulerInstance(
        instance_id=instance_id,
        workflow_definition_code=definition_code,
        workflow_definition_version=(
            payload.get("workflowDefinitionVersion")
            or payload.get("processDefinitionVersion")
        ),
        state=str(state),
        name=payload.get("name"),
        start_time=payload.get("startTime"),
        end_time=payload.get("endTime"),
    )


class DolphinSchedulerClient:
    """Synchronous HTTP client for the pinned DolphinScheduler 3.4 API."""

    def __init__(
        self,
        profile: DolphinSchedulerProfile,
        *,
        transport: httpx.BaseTransport | None = None,
    ):
        self.profile = profile
        self._client = httpx.Client(
            headers={
                "Accept": "application/json",
                "token": profile.access_token.get_secret_value(),
            },
            timeout=profile.request_timeout_seconds,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def _endpoint(self, path: str) -> str:
        return f"{self.profile.base_url}/{path.lstrip('/')}"

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
    ) -> Any:
        try:
            response = self._client.request(
                method, self._endpoint(path), params=params, data=data
            )
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise DolphinSchedulerUnavailableError(
                "DolphinScheduler request outcome is unknown"
            ) from exc
        if response.status_code >= 400:
            raise DolphinSchedulerRejectedError(
                f"DolphinScheduler rejected request with HTTP {response.status_code}"
            )
        try:
            envelope = response.json()
        except ValueError as exc:
            raise DolphinSchedulerProtocolError(
                "DolphinScheduler returned a non-JSON response"
            ) from exc
        if not isinstance(envelope, dict) or "code" not in envelope:
            raise DolphinSchedulerProtocolError(
                "DolphinScheduler response envelope is invalid"
            )
        if envelope.get("code") != 0:
            raise DolphinSchedulerRejectedError(
                f"DolphinScheduler API rejected request with code {envelope.get('code')}"
            )
        return envelope.get("data")

    def list_workflows(
        self, *, search_value: str | None = None, page_no: int = 1, page_size: int = 20
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"pageNo": page_no, "pageSize": page_size}
        if search_value:
            params["searchVal"] = search_value
        data = self._request(
            "GET",
            f"/projects/{self.profile.project_code}/workflow-definition",
            params=params,
        )
        return _page_items(data)

    def create_workflow(
        self, spec: DolphinSchedulerWorkflowSpec
    ) -> DolphinSchedulerDefinitionBinding:
        data = self._request(
            "POST",
            f"/projects/{self.profile.project_code}/workflow-definition",
            data=spec.as_create_form(),
        )
        if not isinstance(data, dict):
            raise DolphinSchedulerProtocolError(
                "workflow creation did not return a definition"
            )
        code = data.get("code") or data.get("workflowDefinitionCode")
        version = data.get("version") or data.get("workflowDefinitionVersion")
        try:
            binding = DolphinSchedulerDefinitionBinding(
                tenant_id=spec.tenant_id,
                definition_version_id=spec.definition_version_id,
                project_code=self.profile.project_code,
                workflow_definition_code=code,
                workflow_definition_version=version,
                compiled_sha256=spec.compiled_sha256,
            )
        except Exception as exc:
            raise DolphinSchedulerProtocolError(
                "workflow creation response is missing code or version"
            ) from exc
        self.release_workflow(binding.workflow_definition_code)
        return binding

    def release_workflow(self, workflow_definition_code: int) -> None:
        data = self._request(
            "POST",
            f"/projects/{self.profile.project_code}/workflow-definition/"
            f"{workflow_definition_code}/release",
            data={"releaseState": "ONLINE"},
        )
        if data is not True:
            raise DolphinSchedulerProtocolError(
                "workflow release did not return an online confirmation"
            )

    @staticmethod
    def start_params(run: PlatformRun) -> dict[str, str]:
        return {
            "gda_run_id": str(run.run_id),
            "gda_tenant_id": run.tenant_id,
            "gda_definition_version_id": str(run.definition_version_id),
            "gda_idempotency_key": run.idempotency_key,
        }

    def start_workflow(
        self,
        binding: DolphinSchedulerDefinitionBinding,
        run: PlatformRun,
    ) -> int:
        data = self._request(
            "POST",
            f"/projects/{self.profile.project_code}/executors/start-workflow-instance",
            data={
                "workflowDefinitionCode": str(binding.workflow_definition_code),
                "scheduleTime": "",
                "failureStrategy": "END",
                "taskDependType": "TASK_POST",
                "execType": "START_PROCESS",
                "warningType": "NONE",
                "warningGroupId": "0",
                "workflowInstancePriority": "MEDIUM",
                "workerGroup": self.profile.worker_group,
                "tenantCode": self.profile.tenant_code,
                "environmentCode": "-1",
                "startParams": _json(self.start_params(run)),
                "dryRun": "0",
            },
        )
        if not isinstance(data, list) or len(data) != 1:
            raise DolphinSchedulerProtocolError(
                "manual start must return exactly one workflow instance ID"
            )
        try:
            instance_id = int(data[0])
        except (TypeError, ValueError) as exc:
            raise DolphinSchedulerProtocolError(
                "workflow instance ID is invalid"
            ) from exc
        if instance_id <= 0:
            raise DolphinSchedulerProtocolError("workflow instance ID must be positive")
        return instance_id

    def list_instances(
        self,
        workflow_definition_code: int,
        *,
        page_no: int = 1,
        page_size: int = 100,
    ) -> list[dict[str, Any]]:
        data = self._request(
            "GET",
            f"/projects/{self.profile.project_code}/workflow-instances",
            params={
                "workflowDefinitionCode": workflow_definition_code,
                "pageNo": page_no,
                "pageSize": page_size,
            },
        )
        return _page_items(data)

    def get_instance(
        self, instance_id: int, workflow_definition_code: int
    ) -> DolphinSchedulerInstance:
        data = self._request(
            "GET",
            f"/projects/{self.profile.project_code}/workflow-instances/{instance_id}",
        )
        if not isinstance(data, dict):
            raise DolphinSchedulerProtocolError("workflow instance response is invalid")
        return _instance_from_payload(data, workflow_definition_code)

    def get_instance_variables(self, instance_id: int) -> dict[str, str]:
        data = self._request(
            "GET",
            f"/projects/{self.profile.project_code}/workflow-instances/"
            f"{instance_id}/view-variables",
        )
        variables: dict[str, str] = {}
        _collect_variables(data, variables)
        return variables

    def find_instances(
        self,
        binding: DolphinSchedulerDefinitionBinding,
        run: PlatformRun,
    ) -> list[DolphinSchedulerInstance]:
        expected = self.start_params(run)
        matches: list[DolphinSchedulerInstance] = []
        for page_no in range(1, self.profile.reconciliation_page_limit + 1):
            page = self.list_instances(
                binding.workflow_definition_code, page_no=page_no
            )
            for item in page:
                instance = _instance_from_payload(
                    item, binding.workflow_definition_code
                )
                variables = self.get_instance_variables(instance.instance_id)
                missing = [key for key in _CORRELATION_KEYS if key not in variables]
                if missing:
                    raise DolphinSchedulerProtocolError(
                        "workflow instance is missing required correlation variables"
                    )
                if all(variables.get(key) == value for key, value in expected.items()):
                    matches.append(instance)
            if len(page) < 100:
                return matches
        raise DolphinSchedulerReconciliationRequired(
            "correlation scan reached the configured page limit"
        )

    def control_instance(self, instance_id: int, execute_type: str) -> None:
        self._request(
            "POST",
            f"/projects/{self.profile.project_code}/executors/execute",
            data={
                "workflowInstanceId": str(instance_id),
                "executeType": execute_type,
            },
        )


class DolphinSchedulerAdapter:
    """Bridge PlatformRun commands and DolphinScheduler instance evidence."""

    def __init__(
        self,
        profile: DolphinSchedulerProfile,
        *,
        gateway: PlatformGateway | None = None,
        client: DolphinSchedulerClient | None = None,
    ):
        self.profile = profile
        self.gateway = gateway or PlatformGateway()
        self.client = client or DolphinSchedulerClient(profile)

    def persist_binding(
        self,
        binding: DolphinSchedulerDefinitionBinding,
        *,
        actor_subject: str,
        created_at: datetime,
    ) -> GatewayWriteResult:
        if binding.project_code != self.profile.project_code:
            raise DolphinSchedulerContractError(
                "binding project does not match profile"
            )
        artifact = build_dolphinscheduler_binding_artifact(
            binding,
            created_by=actor_subject,
            created_at=created_at,
        )
        return self.gateway.record_artifact(artifact)

    def load_binding(
        self, tenant_id: str, artifact_id: UUID
    ) -> DolphinSchedulerDefinitionBinding:
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        artifact = self.gateway.get_artifact(tenant, artifact_id)
        return parse_dolphinscheduler_binding_artifact(artifact)

    def _resolve_binding(
        self,
        tenant_id: str,
        binding: DolphinSchedulerDefinitionBinding | UUID,
    ) -> DolphinSchedulerDefinitionBinding:
        if isinstance(binding, UUID):
            return self.load_binding(tenant_id, binding)
        if isinstance(binding, DolphinSchedulerDefinitionBinding):
            return binding
        raise DolphinSchedulerContractError(
            "binding must be a DolphinSchedulerDefinitionBinding or artifact UUID"
        )

    def _validate_binding(
        self, run: PlatformRun, binding: DolphinSchedulerDefinitionBinding
    ) -> None:
        if run.orchestration_class.value != "dataops":
            raise DolphinSchedulerContractError(
                "DolphinScheduler only dispatches dataops PlatformRuns"
            )
        if binding.tenant_id != run.tenant_id:
            raise DolphinSchedulerContractError("binding tenant does not match run")
        if binding.definition_version_id != run.definition_version_id:
            raise DolphinSchedulerContractError("binding definition does not match run")
        if binding.project_code != self.profile.project_code:
            raise DolphinSchedulerContractError(
                "binding project does not match profile"
            )

    def _find_one(
        self, binding: DolphinSchedulerDefinitionBinding, run: PlatformRun
    ) -> DolphinSchedulerInstance | None:
        matches = self.client.find_instances(binding, run)
        if len(matches) > 1:
            raise DolphinSchedulerCorrelationConflictError(
                "multiple workflow instances share the PlatformRun correlation"
            )
        return matches[0] if matches else None

    def _dispatch_observation(
        self,
        run: PlatformRun,
        binding: DolphinSchedulerDefinitionBinding,
        instance_id: int,
        attempt_no: int,
    ) -> tuple[FrameworkAttemptObservation, bool]:
        evidence = {
            "api_profile": binding.api_profile,
            "project_code": binding.project_code,
            "server_version": binding.server_version,
            "workflow_definition_code": binding.workflow_definition_code,
            "workflow_definition_version": binding.workflow_definition_version,
            "workflow_instance_id": instance_id,
            "correlation": DolphinSchedulerClient.start_params(run),
        }
        observation = FrameworkAttemptObservation(
            tenant_id=run.tenant_id,
            observation_id=uuid5(
                run.run_id,
                f"dolphinscheduler:{binding.project_code}:{instance_id}:dispatch",
            ),
            run_id=run.run_id,
            attempt_no=attempt_no,
            framework_kind="dolphinscheduler",
            external_namespace=str(binding.project_code),
            external_run_id=str(instance_id),
            external_attempt_id=None,
            observed_state="submitted",
            observation_sha256=canonical_json_fingerprint(evidence),
            evidence=evidence,
            observed_at=run.submitted_at,
        )
        result = self.gateway.record_attempt(observation)
        return observation, result.created

    def dispatch(
        self,
        tenant_id: str,
        run_id: UUID,
        binding: DolphinSchedulerDefinitionBinding | UUID,
        *,
        actor_subject: str,
        attempt_no: int = 1,
    ) -> DolphinSchedulerDispatchResult:
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        run = self.gateway.get_run(tenant, run_id)
        binding = self._resolve_binding(tenant, binding)
        self._validate_binding(run, binding)

        existing = self._find_one(binding, run)
        if existing is not None:
            if run.status == RunStatus.ACCEPTED:
                run = self.gateway.transition_run(
                    tenant,
                    run.run_id,
                    run.state_version,
                    RunStatus.DISPATCHING,
                    actor_subject,
                    "recovered existing DolphinScheduler correlation",
                    {"workflow_instance_id": existing.instance_id},
                )
            observation, created = self._dispatch_observation(
                run, binding, existing.instance_id, attempt_no
            )
            return DolphinSchedulerDispatchResult(
                run=run,
                observation=observation,
                workflow_instance_id=existing.instance_id,
                observation_created=created,
                recovered=True,
            )

        if run.status != RunStatus.ACCEPTED:
            raise DolphinSchedulerReconciliationRequired(
                "non-accepted run has no visible external correlation; do not resubmit"
            )
        run = self.gateway.transition_run(
            tenant,
            run.run_id,
            run.state_version,
            RunStatus.DISPATCHING,
            actor_subject,
            "dispatching to DolphinScheduler",
            {"workflow_definition_code": binding.workflow_definition_code},
        )
        recovered_submission = False
        try:
            instance_id = self.client.start_workflow(binding, run)
        except DolphinSchedulerError as exc:
            recovered: DolphinSchedulerInstance | None = None
            try:
                recovered = self._find_one(binding, run)
            except DolphinSchedulerError:
                recovered = None
            if recovered is None:
                self.gateway.transition_run(
                    tenant,
                    run.run_id,
                    run.state_version,
                    RunStatus.RECONCILING,
                    actor_subject,
                    "DolphinScheduler dispatch outcome requires reconciliation",
                    {"provider_error_code": exc.code},
                )
                raise DolphinSchedulerReconciliationRequired(
                    "dispatch outcome is unknown; reconcile before retry"
                ) from exc
            instance_id = recovered.instance_id
            recovered_submission = True

        observation, created = self._dispatch_observation(
            run, binding, instance_id, attempt_no
        )
        return DolphinSchedulerDispatchResult(
            run=run,
            observation=observation,
            workflow_instance_id=instance_id,
            observation_created=created,
            recovered=recovered_submission,
        )

    def _provider_timestamp(
        self, run: PlatformRun, instance: DolphinSchedulerInstance
    ) -> datetime:
        raw = instance.end_time or instance.start_time
        if not raw:
            return run.submitted_at
        normalized = raw.strip().replace("T", " ").removesuffix("Z")
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return run.submitted_at
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=ZoneInfo(self.profile.timezone_name))
        return parsed.astimezone(UTC)

    def _state_observation(
        self,
        run: PlatformRun,
        binding: DolphinSchedulerDefinitionBinding,
        instance: DolphinSchedulerInstance,
        attempt_no: int,
    ) -> tuple[FrameworkAttemptObservation, bool]:
        state = instance.state.upper()
        observed_at = self._provider_timestamp(run, instance)
        evidence = {
            "api_profile": binding.api_profile,
            "project_code": binding.project_code,
            "server_version": binding.server_version,
            "workflow_definition_code": instance.workflow_definition_code,
            "workflow_definition_version": instance.workflow_definition_version,
            "workflow_instance_id": instance.instance_id,
            "provider_state": state,
            "provider_start_time": instance.start_time,
            "provider_end_time": instance.end_time,
        }
        observation = FrameworkAttemptObservation(
            tenant_id=run.tenant_id,
            observation_id=uuid5(
                run.run_id,
                f"dolphinscheduler:{binding.project_code}:{instance.instance_id}:"
                f"{state}:{observed_at.isoformat()}",
            ),
            run_id=run.run_id,
            attempt_no=attempt_no,
            framework_kind="dolphinscheduler",
            external_namespace=str(binding.project_code),
            external_run_id=str(instance.instance_id),
            external_attempt_id=None,
            observed_state=state.lower(),
            observation_sha256=canonical_json_fingerprint(evidence),
            evidence=evidence,
            observed_at=observed_at,
        )
        result = self.gateway.record_attempt(observation)
        return observation, result.created

    def reconcile(
        self,
        tenant_id: str,
        run_id: UUID,
        binding: DolphinSchedulerDefinitionBinding | UUID,
        *,
        actor_subject: str,
        attempt_no: int = 1,
    ) -> DolphinSchedulerReconcileResult:
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        run = self.gateway.get_run(tenant, run_id)
        binding = self._resolve_binding(tenant, binding)
        self._validate_binding(run, binding)
        match = self._find_one(binding, run)
        if match is None:
            raise DolphinSchedulerCorrelationNotFoundError(
                "no workflow instance matches the PlatformRun correlation"
            )
        instance = self.client.get_instance(
            match.instance_id, binding.workflow_definition_code
        )
        observation, created = self._state_observation(
            run, binding, instance, attempt_no
        )

        if run.status == RunStatus.ACCEPTED:
            run = self.gateway.transition_run(
                tenant,
                run.run_id,
                run.state_version,
                RunStatus.DISPATCHING,
                actor_subject,
                "recovered DolphinScheduler correlation during reconcile",
                {"workflow_instance_id": instance.instance_id},
            )
        provider_state = instance.state.upper()
        if provider_state in _RUNNING_STATES and run.status in {
            RunStatus.DISPATCHING,
            RunStatus.RECONCILING,
        }:
            run = self.gateway.transition_run(
                tenant,
                run.run_id,
                run.state_version,
                RunStatus.RUNNING,
                actor_subject,
                "DolphinScheduler reports active execution",
                {"provider_state": provider_state},
            )
        elif provider_state in _TERMINAL_PROVIDER_STATES and run.status in {
            RunStatus.DISPATCHING,
            RunStatus.RUNNING,
            RunStatus.CANCELLING,
        }:
            run = self.gateway.transition_run(
                tenant,
                run.run_id,
                run.state_version,
                RunStatus.RECONCILING,
                actor_subject,
                "provider reached terminal state; platform verdict still pending",
                {"provider_state": provider_state},
            )
        return DolphinSchedulerReconcileResult(
            run=run,
            observation=observation,
            workflow_instance_id=instance.instance_id,
            provider_state=provider_state,
            observation_created=created,
        )

    def cancel(
        self,
        tenant_id: str,
        run_id: UUID,
        binding: DolphinSchedulerDefinitionBinding | UUID,
        *,
        actor_subject: str,
    ) -> PlatformRun:
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        run = self.gateway.get_run(tenant, run_id)
        binding = self._resolve_binding(tenant, binding)
        self._validate_binding(run, binding)
        match = self._find_one(binding, run)
        if match is None:
            raise DolphinSchedulerCorrelationNotFoundError(
                "cannot cancel without an external workflow correlation"
            )
        if run.status in {
            RunStatus.DISPATCHING,
            RunStatus.RUNNING,
            RunStatus.RECONCILING,
        }:
            run = self.gateway.transition_run(
                tenant,
                run.run_id,
                run.state_version,
                RunStatus.CANCELLING,
                actor_subject,
                "cancellation requested for DolphinScheduler workflow",
                {"workflow_instance_id": match.instance_id},
            )
        elif run.status != RunStatus.CANCELLING:
            raise DolphinSchedulerContractError(
                f"run in {run.status.value} cannot be cancelled through this adapter"
            )
        self.client.control_instance(match.instance_id, "STOP")
        return run


def build_dolphinscheduler_adapter_report(
    source_path: Path | None = None,
) -> dict[str, Any]:
    path = (source_path or Path(__file__)).resolve()
    errors: list[str] = []
    if not path.is_file():
        return {
            "schema": DOLPHINSCHEDULER_ADAPTER_SCHEMA,
            "status": "invalid",
            "errors": ["adapter source is missing"],
        }
    source = path.read_text(encoding="utf-8")
    required = (
        'DOLPHINSCHEDULER_SERVER_VERSION = "3.4.2"',
        'DOLPHINSCHEDULER_API_PROFILE = "3.4"',
        "/executors/start-workflow-instance",
        "/workflow-instances",
        'data={"releaseState": "ONLINE"}',
        '"startParams": _json(self.start_params(run))',
        "workflow instance is missing required correlation variables",
        "correlation scan reached the configured page limit",
        "dispatch outcome is unknown; reconcile before retry",
        "platform verdict still pending",
        "def persist_binding(",
        "def load_binding(",
        "parse_dolphinscheduler_binding_artifact",
    )
    missing = [marker for marker in required if marker not in source]
    if missing:
        errors.append("adapter source is missing required boundary markers")
    return {
        "schema": DOLPHINSCHEDULER_ADAPTER_SCHEMA,
        "status": "valid" if not errors else "invalid",
        "server_version": DOLPHINSCHEDULER_SERVER_VERSION,
        "api_profile": DOLPHINSCHEDULER_API_PROFILE,
        "official_release": DOLPHINSCHEDULER_RELEASE_URL,
        "source": path.as_posix(),
        "source_sha256": canonical_json_fingerprint({"source": source}),
        "missing_markers": missing,
        "errors": errors,
    }


def _read_token_file(path: Path) -> str:
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & 0o077:
        raise DolphinSchedulerConfigurationError(
            "token file must not be accessible by group or other users"
        )
    token = path.read_text(encoding="utf-8").strip()
    if not token:
        raise DolphinSchedulerConfigurationError("token file is empty")
    return token


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("--output")
    probe_parser = subparsers.add_parser("probe")
    probe_parser.add_argument("--base-url", required=True)
    probe_parser.add_argument("--token-file", type=Path, required=True)
    probe_parser.add_argument("--project-code", type=int, required=True)
    probe_parser.add_argument("--tenant-code", default="default")
    probe_parser.add_argument("--worker-group", default="default")
    args = parser.parse_args(argv)

    if args.command == "validate":
        report = build_dolphinscheduler_adapter_report()
        rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
        if args.output:
            Path(args.output).write_text(rendered + "\n", encoding="utf-8")
        print(rendered)
        return 0 if report["status"] == "valid" else 1

    token = _read_token_file(args.token_file)
    profile = DolphinSchedulerProfile(
        base_url=args.base_url,
        access_token=token,
        project_code=args.project_code,
        tenant_code=args.tenant_code,
        worker_group=args.worker_group,
    )
    with DolphinSchedulerClient(profile) as client:
        workflows = client.list_workflows(page_size=1)
    print(
        json.dumps(
            {
                "status": "reachable",
                "server_version": profile.server_version,
                "api_profile": profile.api_profile,
                "project_code": profile.project_code,
                "sample_count": len(workflows),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
