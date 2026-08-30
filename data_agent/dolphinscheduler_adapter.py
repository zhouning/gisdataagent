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
from collections.abc import Callable
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

from .dataops_invocation import (
    DATAOPS_INVOCATION_SEMANTIC_TYPE,
    DataOpsInvocation,
    DataOpsInvocationError,
    dataops_invocation_version_id,
    parse_dataops_invocation_version,
)
from .platform_authorization import (
    AuthorizationEvidenceError,
    validate_run_authorization_evidence,
)
from .platform_contracts import (
    Artifact,
    FrameworkAttemptObservation,
    JqdltbTransformationContract,
    JqdltbTransformationMode,
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
DOLPHINSCHEDULER_BINDING_MEDIA_TYPE = "application/vnd.gda.dolphinscheduler-binding+json"
DOLPHINSCHEDULER_JQDLTB_PLAN_SCHEMA = "gda.dolphinscheduler_jqdltb_transformation_plan.v1"
DOLPHINSCHEDULER_JQDLTB_PLAN_MEDIA_TYPE = (
    "application/vnd.gda.dolphinscheduler-jqdltb-transformation-plan+json"
)
DOLPHINSCHEDULER_RELEASE_URL = "https://github.com/apache/dolphinscheduler/releases/tag/3.4.2"
DOLPHINSCHEDULER_CAPABILITY_SCHEMA = "gda.dolphinscheduler_capability.v1"
_CANCEL_STOP_CAPABILITIES = frozenset({"unknown", "certified", "conformance_probe"})
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
_BASE_CORRELATION_KEYS = (
    "gda_run_id",
    "gda_tenant_id",
    "gda_definition_version_id",
    "gda_idempotency_key",
)
_CORRELATION_KEYS = (
    *_BASE_CORRELATION_KEYS,
    "gda_invocation_version_id",
    "gda_invocation_sha256",
    "gda_trigger_kind",
    "gda_logical_start",
    "gda_logical_end",
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
    workload_subject: str = Field(min_length=10, max_length=512)
    policy_evaluator_subject: str = Field(min_length=10, max_length=512)
    tenant_code: str = Field(default="default", min_length=1, max_length=128)
    worker_group: str = Field(default="default", min_length=1, max_length=255)
    timezone_name: str = Field(default="UTC", min_length=1, max_length=64)
    request_timeout_seconds: float = Field(default=15.0, gt=0, le=300)
    reconciliation_page_limit: int = Field(default=5, ge=1, le=100)
    cancel_terminal_stop_capability: Literal[
        "unknown", "certified", "conformance_probe"
    ] = "unknown"
    cancel_terminal_stop_evidence_ref: str | None = Field(default=None, max_length=512)
    api_profile: Literal["3.4"] = DOLPHINSCHEDULER_API_PROFILE
    server_version: Literal["3.4.2"] = DOLPHINSCHEDULER_SERVER_VERSION

    @field_validator("workload_subject", "policy_evaluator_subject")
    @classmethod
    def _workload_identity(cls, value: str) -> str:
        if not value.startswith("workload:") or not value.removeprefix("workload:").strip():
            raise ValueError("DolphinScheduler identities must use workload subjects")
        return value

    @model_validator(mode="after")
    def _separate_policy_evaluator(self) -> DolphinSchedulerProfile:
        if self.workload_subject == self.policy_evaluator_subject:
            raise ValueError("policy evaluator must be independent from adapter workload")
        return self

    @model_validator(mode="after")
    def _cancel_capability_evidence(self) -> DolphinSchedulerProfile:
        if self.cancel_terminal_stop_capability not in _CANCEL_STOP_CAPABILITIES:
            raise ValueError("cancel terminal STOP capability is invalid")
        evidence_ref = self.cancel_terminal_stop_evidence_ref
        if self.cancel_terminal_stop_capability == "unknown" and evidence_ref is not None:
            raise ValueError("unknown cancel capability cannot carry evidence")
        if self.cancel_terminal_stop_capability != "unknown":
            if not evidence_ref or any(character.isspace() for character in evidence_ref):
                raise ValueError(
                    "certified cancel capability requires a non-empty evidence reference"
                )
        return self

    @field_validator("base_url")
    @classmethod
    def _safe_base_url(cls, value: str) -> str:
        normalized = value.rstrip("/")
        parts = urlsplit(normalized)
        if parts.scheme not in {"http", "https"} or not parts.netloc:
            raise ValueError("base_url must be an absolute HTTP(S) URL")
        if parts.username or parts.password or parts.query or parts.fragment:
            raise ValueError("base_url must not contain credentials, query, or fragment")
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


class DolphinSchedulerCapabilityReport(_FrozenModel):
    """Version-bound provider capability admission evidence."""

    schema_version: Literal[DOLPHINSCHEDULER_CAPABILITY_SCHEMA] = (
        DOLPHINSCHEDULER_CAPABILITY_SCHEMA
    )
    provider: Literal["apache_dolphinscheduler"] = "apache_dolphinscheduler"
    api_profile: Literal["3.4"]
    server_version: Literal["3.4.2"]
    cancel_terminal_stop_capability: Literal[
        "unknown", "certified", "conformance_probe"
    ]
    cancel_terminal_stop_evidence_ref: str | None = None
    cancel_admission: Literal["rejected", "allowed", "probe_only"]
    capability_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _fingerprint_is_bound(self) -> DolphinSchedulerCapabilityReport:
        expected = canonical_json_fingerprint(
            self.model_dump(mode="json", exclude={"capability_sha256"})
        )
        if expected != self.capability_sha256:
            raise ValueError("DolphinScheduler capability fingerprint is invalid")
        if self.cancel_terminal_stop_capability == "unknown":
            if (
                self.cancel_admission != "rejected"
                or self.cancel_terminal_stop_evidence_ref is not None
            ):
                raise ValueError("unknown cancel capability must be rejected without evidence")
        elif self.cancel_terminal_stop_capability == "certified":
            if self.cancel_admission != "allowed" or not self.cancel_terminal_stop_evidence_ref:
                raise ValueError("certified cancel capability must be production-allowed")
        elif self.cancel_admission != "probe_only" or not self.cancel_terminal_stop_evidence_ref:
            raise ValueError("conformance probe capability must remain probe-only")
        return self


class DolphinSchedulerWorkflowDocument(_FrozenModel):
    name: str
    description: str = ""
    task_definitions: tuple[dict[str, Any], ...]
    task_relations: tuple[dict[str, Any], ...]
    locations: tuple[dict[str, Any], ...] = ()
    global_params: tuple[dict[str, Any], ...] = ()
    timeout_seconds: int = Field(default=0, ge=0)
    execution_type: Literal["PARALLEL", "SERIAL_WAIT", "SERIAL_DISCARD", "SERIAL_PRIORITY"] = (
        "PARALLEL"
    )
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


class DolphinSchedulerJqdltbTransformationPlanEnvelope(_FrozenModel):
    """Provider binding plus the exact approved JQDLTB execution contract."""

    plan_schema: Literal[DOLPHINSCHEDULER_JQDLTB_PLAN_SCHEMA] = Field(
        default=DOLPHINSCHEDULER_JQDLTB_PLAN_SCHEMA,
        alias="schema",
    )
    binding: DolphinSchedulerDefinitionBinding
    transformation_contract: JqdltbTransformationContract

    @model_validator(mode="after")
    def _executable_contract(self) -> Self:
        if self.transformation_contract.mode is not JqdltbTransformationMode.EXECUTE:
            raise ValueError("JQDLTB scheduler plan requires an executable contract")
        if self.transformation_contract.tenant_id != self.binding.tenant_id:
            raise ValueError("JQDLTB scheduler plan tenant does not match binding")
        return self


class DolphinSchedulerInstance(_FrozenModel):
    instance_id: int = Field(gt=0)
    workflow_definition_code: int = Field(gt=0)
    workflow_definition_version: int | None = Field(default=None, ge=1)
    state: str = Field(min_length=1, max_length=128)
    name: str | None = None
    command_type: str | None = None
    schedule_time: str | None = None
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


def _jqdltb_plan_artifact_id(
    binding: DolphinSchedulerDefinitionBinding,
    contract: JqdltbTransformationContract,
) -> UUID:
    identity = {
        "binding": binding.model_dump(mode="json"),
        "contract_sha256": contract.contract_sha256,
        "plan_sha256": contract.plan_sha256,
    }
    return uuid5(
        binding.definition_version_id,
        f"dolphinscheduler-jqdltb-transformation:{canonical_json_fingerprint(identity)}",
    )


def _jqdltb_plan_artifact_key(
    binding: DolphinSchedulerDefinitionBinding,
    contract: JqdltbTransformationContract,
) -> str:
    return (
        f"dolphinscheduler-jqdltb-transformation:{binding.workflow_definition_code}:"
        f"v{binding.workflow_definition_version}:{contract.plan_sha256[:12]}"
    )


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


def build_dolphinscheduler_jqdltb_transformation_plan_artifact(
    binding: DolphinSchedulerDefinitionBinding,
    contract: JqdltbTransformationContract,
    *,
    created_by: str,
    created_at: datetime,
) -> Artifact:
    """Build an execution plan that carries one approved JQDLTB contract."""
    if contract.mode is not JqdltbTransformationMode.EXECUTE:
        raise DolphinSchedulerContractError(
            "JQDLTB scheduler plan requires an executable contract"
        )
    if contract.tenant_id != binding.tenant_id:
        raise DolphinSchedulerContractError("JQDLTB plan tenant does not match binding")
    envelope = DolphinSchedulerJqdltbTransformationPlanEnvelope(
        binding=binding,
        transformation_contract=contract,
    )
    manifest = envelope.model_dump(mode="json", by_alias=True)
    artifact_id = _jqdltb_plan_artifact_id(binding, contract)
    content = canonical_json_bytes(manifest)
    return Artifact(
        tenant_id=binding.tenant_id,
        artifact_id=artifact_id,
        artifact_key=_jqdltb_plan_artifact_key(binding, contract),
        artifact_role="execution_plan",
        storage_uri=_binding_storage_uri(binding.tenant_id, artifact_id),
        media_type=DOLPHINSCHEDULER_JQDLTB_PLAN_MEDIA_TYPE,
        content_sha256=canonical_json_fingerprint(manifest),
        size_bytes=len(content),
        run_id=None,
        resource_version_id=binding.definition_version_id,
        manifest=manifest,
        created_by=created_by,
        created_at=created_at,
    )


def parse_dolphinscheduler_jqdltb_transformation_plan_artifact(
    artifact: Artifact,
) -> tuple[DolphinSchedulerDefinitionBinding, JqdltbTransformationContract]:
    """Validate and return the scheduler binding and its approved contract."""
    try:
        envelope = DolphinSchedulerJqdltbTransformationPlanEnvelope.model_validate(
            artifact.manifest
        )
    except Exception as exc:
        raise DolphinSchedulerContractError(
            "JQDLTB scheduler plan manifest does not satisfy the envelope contract"
        ) from exc
    binding = envelope.binding
    contract = envelope.transformation_contract
    artifact_id = _jqdltb_plan_artifact_id(binding, contract)
    expected = {
        "tenant_id": binding.tenant_id,
        "artifact_id": artifact_id,
        "artifact_key": _jqdltb_plan_artifact_key(binding, contract),
        "artifact_role": "execution_plan",
        "storage_uri": _binding_storage_uri(binding.tenant_id, artifact_id),
        "media_type": DOLPHINSCHEDULER_JQDLTB_PLAN_MEDIA_TYPE,
        "content_sha256": canonical_json_fingerprint(artifact.manifest),
        "size_bytes": len(canonical_json_bytes(artifact.manifest)),
        "run_id": None,
        "resource_version_id": binding.definition_version_id,
    }
    actual = artifact.model_dump(mode="python", include=set(expected))
    actual["artifact_role"] = getattr(artifact.artifact_role, "value", artifact.artifact_role)
    if any(actual[name] != value for name, value in expected.items()):
        raise DolphinSchedulerContractError(
            "JQDLTB scheduler plan artifact metadata does not match its manifest"
        )
    return binding, contract


def parse_dolphinscheduler_binding_artifact(
    artifact: Artifact,
) -> DolphinSchedulerDefinitionBinding:
    """Validate every immutable artifact field before returning its binding."""
    if artifact.manifest.get("schema") == DOLPHINSCHEDULER_JQDLTB_PLAN_SCHEMA:
        binding, _contract = parse_dolphinscheduler_jqdltb_transformation_plan_artifact(
            artifact
        )
        return binding
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
    actual["artifact_role"] = getattr(artifact.artifact_role, "value", artifact.artifact_role)
    mismatches = [name for name, value in expected.items() if actual[name] != value]
    if mismatches:
        raise DolphinSchedulerContractError("binding artifact metadata does not match its manifest")
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
        raise DolphinSchedulerContractError("DolphinScheduler only accepts dataops definitions")
    raw = definition.definition_document.get("dolphinscheduler")
    if not isinstance(raw, dict):
        raise DolphinSchedulerContractError("definition_document.dolphinscheduler is required")
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
        raise DolphinSchedulerProtocolError("DolphinScheduler paged response is invalid")
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
            payload.get("workflowDefinitionVersion") or payload.get("processDefinitionVersion")
        ),
        state=str(state),
        name=payload.get("name"),
        command_type=payload.get("commandType"),
        schedule_time=payload.get("scheduleTime"),
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
            response = self._client.request(method, self._endpoint(path), params=params, data=data)
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
            raise DolphinSchedulerProtocolError("DolphinScheduler response envelope is invalid")
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

    def generate_task_codes(self, count: int = 1) -> tuple[int, ...]:
        if count < 1 or count > 100:
            raise DolphinSchedulerContractError("task code count must be between 1 and 100")
        data = self._request(
            "GET",
            f"/projects/{self.profile.project_code}/task-definition/gen-task-codes",
            params={"genNum": count},
        )
        if not isinstance(data, list) or len(data) != count:
            raise DolphinSchedulerProtocolError(
                "task code generation returned an unexpected result"
            )
        try:
            codes = tuple(int(value) for value in data)
        except (TypeError, ValueError) as exc:
            raise DolphinSchedulerProtocolError("generated task code is invalid") from exc
        if any(code <= 0 for code in codes) or len(set(codes)) != len(codes):
            raise DolphinSchedulerProtocolError(
                "generated task codes must be unique positive integers"
            )
        return codes

    def create_workflow(
        self, spec: DolphinSchedulerWorkflowSpec
    ) -> DolphinSchedulerDefinitionBinding:
        data = self._request(
            "POST",
            f"/projects/{self.profile.project_code}/workflow-definition",
            data=spec.as_create_form(),
        )
        if not isinstance(data, dict):
            raise DolphinSchedulerProtocolError("workflow creation did not return a definition")
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
    def start_params(
        run: PlatformRun,
        invocation: DataOpsInvocation | None = None,
    ) -> dict[str, str]:
        params = {
            "gda_run_id": str(run.run_id),
            "gda_tenant_id": run.tenant_id,
            "gda_definition_version_id": str(run.definition_version_id),
            "gda_idempotency_key": run.idempotency_key,
        }
        if invocation is not None:
            params.update(
                {
                    "gda_invocation_version_id": str(dataops_invocation_version_id(invocation)),
                    "gda_invocation_sha256": invocation.invocation_sha256,
                    "gda_trigger_kind": invocation.trigger_kind,
                    "gda_logical_start": invocation.logical_start.isoformat(),
                    "gda_logical_end": invocation.logical_end.isoformat(),
                }
            )
            if invocation.trigger_kind == "schedule":
                params.update(
                    {
                        "gda_schedule_ref": invocation.schedule_ref or "",
                        "gda_schedule_time": invocation.schedule_times[0].isoformat(),
                    }
                )
            elif invocation.trigger_kind == "manual":
                params["gda_client_request_id"] = invocation.client_request_id or ""
        return params

    def _backfill_time(self, invocation: DataOpsInvocation) -> str:
        if len(invocation.schedule_times) != 1:
            raise DolphinSchedulerContractError(
                "backfill invocation must identify exactly one provider schedule time"
            )
        provider_timezone = ZoneInfo(self.profile.timezone_name)
        schedule_time = invocation.schedule_times[0].astimezone(provider_timezone)
        return _json(
            {
                "complementStartDate": "",
                "complementEndDate": "",
                "complementScheduleDateList": f"{schedule_time:%Y-%m-%d %H:%M:%S}",
            }
        )

    def start_form(
        self,
        binding: DolphinSchedulerDefinitionBinding,
        run: PlatformRun,
        invocation: DataOpsInvocation | None = None,
    ) -> dict[str, str]:
        form = {
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
            "startParams": _json(self.start_params(run, invocation)),
            "dryRun": "0",
        }
        if invocation is not None and invocation.trigger_kind == "backfill":
            form.update(
                {
                    "scheduleTime": self._backfill_time(invocation),
                    "execType": "COMPLEMENT_DATA",
                    "runMode": "RUN_MODE_SERIAL",
                    "expectedParallelismNumber": "1",
                    "complementDependentMode": "OFF_MODE",
                    "allLevelDependent": "false",
                    "executionOrder": "ASC_ORDER",
                }
            )
        return form

    def start_workflow(
        self,
        binding: DolphinSchedulerDefinitionBinding,
        run: PlatformRun,
        invocation: DataOpsInvocation | None = None,
    ) -> int:
        data = self._request(
            "POST",
            f"/projects/{self.profile.project_code}/executors/start-workflow-instance",
            data=self.start_form(binding, run, invocation),
        )
        if not isinstance(data, list) or len(data) != 1:
            raise DolphinSchedulerProtocolError(
                "workflow start must return exactly one workflow instance ID"
            )
        try:
            instance_id = int(data[0])
        except (TypeError, ValueError) as exc:
            raise DolphinSchedulerProtocolError("workflow instance ID is invalid") from exc
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
        invocation: DataOpsInvocation | None = None,
    ) -> list[DolphinSchedulerInstance]:
        expected = self.start_params(run, invocation)
        matches: list[DolphinSchedulerInstance] = []
        for page_no in range(1, self.profile.reconciliation_page_limit + 1):
            page = self.list_instances(binding.workflow_definition_code, page_no=page_no)
            for item in page:
                instance = _instance_from_payload(item, binding.workflow_definition_code)
                variables = self.get_instance_variables(instance.instance_id)
                missing_base = [key for key in _BASE_CORRELATION_KEYS if key not in variables]
                if missing_base:
                    raise DolphinSchedulerProtocolError(
                        "workflow instance is missing required correlation variables"
                    )
                if any(variables.get(key) != expected[key] for key in _BASE_CORRELATION_KEYS):
                    continue
                missing = [key for key in expected if key not in variables]
                if missing:
                    raise DolphinSchedulerProtocolError(
                        "matching workflow instance is missing invocation correlation"
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
        clock: Callable[[], datetime] | None = None,
    ):
        self.profile = profile
        self.gateway = gateway or PlatformGateway()
        self.client = client or DolphinSchedulerClient(profile)
        self.clock = clock or (lambda: datetime.now(UTC))

    def capability_report(self) -> DolphinSchedulerCapabilityReport:
        """Derive bounded capabilities from the pinned provider profile."""
        capability = self.profile.cancel_terminal_stop_capability
        admission = {
            "unknown": "rejected",
            "certified": "allowed",
            "conformance_probe": "probe_only",
        }[capability]
        payload = {
            "api_profile": self.profile.api_profile,
            "server_version": self.profile.server_version,
            "cancel_terminal_stop_capability": capability,
            "cancel_terminal_stop_evidence_ref": self.profile.cancel_terminal_stop_evidence_ref,
            "cancel_admission": admission,
        }
        return DolphinSchedulerCapabilityReport(
            **payload,
            capability_sha256=canonical_json_fingerprint(
                {
                    "schema_version": DOLPHINSCHEDULER_CAPABILITY_SCHEMA,
                    "provider": "apache_dolphinscheduler",
                    **payload,
                }
            ),
        )

    def _require_cancel_capability(self) -> DolphinSchedulerCapabilityReport:
        report = self.capability_report()
        if report.cancel_admission == "rejected":
            raise DolphinSchedulerContractError(
                "cancel admission rejected: provider terminal STOP capability is not certified"
            )
        return report

    def persist_binding(
        self,
        binding: DolphinSchedulerDefinitionBinding,
        *,
        actor_subject: str,
        created_at: datetime,
    ) -> GatewayWriteResult:
        if actor_subject != self.profile.workload_subject:
            raise DolphinSchedulerContractError(
                "binding publisher does not match adapter workload identity"
            )
        if binding.project_code != self.profile.project_code:
            raise DolphinSchedulerContractError("binding project does not match profile")
        artifact = build_dolphinscheduler_binding_artifact(
            binding,
            created_by=actor_subject,
            created_at=created_at,
        )
        return self.gateway.record_artifact(artifact)

    def load_binding(self, tenant_id: str, artifact_id: UUID) -> DolphinSchedulerDefinitionBinding:
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        artifact = self.gateway.get_artifact(tenant, artifact_id)
        return parse_dolphinscheduler_binding_artifact(artifact)

    def _resolve_binding(
        self,
        tenant_id: str,
        binding: DolphinSchedulerDefinitionBinding | UUID,
    ) -> tuple[DolphinSchedulerDefinitionBinding, Artifact]:
        if isinstance(binding, UUID):
            artifact = self.gateway.get_artifact(tenant_id, binding)
            return parse_dolphinscheduler_binding_artifact(artifact), artifact
        if not isinstance(binding, DolphinSchedulerDefinitionBinding):
            raise DolphinSchedulerContractError(
                "binding must be a DolphinSchedulerDefinitionBinding or artifact UUID"
            )
        artifact_id = _binding_artifact_id(binding)
        artifact = self.gateway.get_artifact(tenant_id, artifact_id)
        persisted = parse_dolphinscheduler_binding_artifact(artifact)
        if persisted != binding:
            raise DolphinSchedulerContractError(
                "in-memory binding does not match persisted execution plan"
            )
        return binding, artifact

    def _validate_workload_identity(self, run: PlatformRun, actor_subject: str) -> None:
        run_actor = f"{run.subject_context.subject_type.value}:{run.subject_context.subject_id}"
        if run.subject_context.subject_type.value != "workload":
            raise DolphinSchedulerContractError(
                "DolphinScheduler commands require workload SubjectContext"
            )
        if actor_subject != self.profile.workload_subject or actor_subject != run_actor:
            raise DolphinSchedulerContractError(
                "command actor does not match adapter workload identity"
            )

    def _authorize_dispatch(
        self,
        run: PlatformRun,
        execution_plan_artifact: Artifact,
    ) -> None:
        references = run.policy_refs
        if references is None:
            raise DolphinSchedulerContractError(
                "dispatch requires immutable policy decision references"
            )
        decision_artifact = self.gateway.get_artifact(
            run.tenant_id, references.policy_decision_artifact_id
        )
        approval_artifact = None
        if references.approval_artifact_id is not None:
            approval_artifact = self.gateway.get_artifact(
                run.tenant_id, references.approval_artifact_id
            )
        try:
            decision, _approval = validate_run_authorization_evidence(
                run,
                decision_artifact,
                approval_artifact,
                execution_plan_artifact,
                at=self.clock(),
                expected_action="dolphinscheduler.dispatch",
            )
        except AuthorizationEvidenceError as exc:
            raise DolphinSchedulerContractError(f"dispatch authorization rejected: {exc}") from exc
        if decision.evaluator_subject != self.profile.policy_evaluator_subject:
            raise DolphinSchedulerContractError(
                "policy decision does not come from the configured evaluator workload"
            )

    def _authorize_cancel(
        self,
        run: PlatformRun,
        execution_plan_artifact: Artifact,
        policy_decision_artifact_id: UUID,
    ) -> None:
        decision_artifact = self.gateway.get_artifact(run.tenant_id, policy_decision_artifact_id)
        try:
            decision, _approval = validate_run_authorization_evidence(
                run,
                decision_artifact,
                None,
                execution_plan_artifact,
                at=self.clock(),
                expected_action="dolphinscheduler.cancel",
            )
        except AuthorizationEvidenceError as exc:
            raise DolphinSchedulerContractError(f"cancel authorization rejected: {exc}") from exc
        if decision.evaluator_subject != self.profile.policy_evaluator_subject:
            raise DolphinSchedulerContractError(
                "cancel policy decision does not come from the configured evaluator"
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
            raise DolphinSchedulerContractError("binding project does not match profile")

    def _resolve_invocation(self, run: PlatformRun) -> DataOpsInvocation | None:
        invocation_bindings = [
            item for item in run.input_bindings if item.binding_name == "invocation"
        ]
        if not invocation_bindings:
            return None
        binding = invocation_bindings[0]
        if binding.semantic_type != DATAOPS_INVOCATION_SEMANTIC_TYPE:
            raise DolphinSchedulerContractError(
                "invocation binding uses an unexpected semantic type"
            )
        version = self.gateway.get_resource_version(run.tenant_id, binding.resource_version_id)
        try:
            invocation = parse_dataops_invocation_version(version)
        except DataOpsInvocationError as exc:
            raise DolphinSchedulerContractError(f"invocation binding is invalid: {exc}") from exc
        if invocation.tenant_id != run.tenant_id:
            raise DolphinSchedulerContractError("invocation tenant does not match run")
        if invocation.definition_version_id != run.definition_version_id:
            raise DolphinSchedulerContractError("invocation definition does not match run")
        return invocation

    def _find_one(
        self,
        binding: DolphinSchedulerDefinitionBinding,
        run: PlatformRun,
        invocation: DataOpsInvocation | None,
    ) -> DolphinSchedulerInstance | None:
        matches = self.client.find_instances(binding, run, invocation)
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
        invocation: DataOpsInvocation | None,
    ) -> tuple[FrameworkAttemptObservation, bool]:
        evidence = {
            "api_profile": binding.api_profile,
            "project_code": binding.project_code,
            "server_version": binding.server_version,
            "workflow_definition_code": binding.workflow_definition_code,
            "workflow_definition_version": binding.workflow_definition_version,
            "workflow_instance_id": instance_id,
            "correlation": DolphinSchedulerClient.start_params(run, invocation),
            "invocation": (
                invocation.model_dump(mode="json", by_alias=True)
                if invocation is not None
                else None
            ),
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
        binding, execution_plan_artifact = self._resolve_binding(tenant, binding)
        self._validate_binding(run, binding)
        self._validate_workload_identity(run, actor_subject)
        invocation = self._resolve_invocation(run)
        self._authorize_dispatch(run, execution_plan_artifact)

        existing = self._find_one(binding, run, invocation)
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
                run, binding, existing.instance_id, attempt_no, invocation
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
            instance_id = self.client.start_workflow(binding, run, invocation)
        except DolphinSchedulerError as exc:
            recovered: DolphinSchedulerInstance | None = None
            try:
                recovered = self._find_one(binding, run, invocation)
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
            run, binding, instance_id, attempt_no, invocation
        )
        return DolphinSchedulerDispatchResult(
            run=run,
            observation=observation,
            workflow_instance_id=instance_id,
            observation_created=created,
            recovered=recovered_submission,
        )

    def _provider_timestamp(self, run: PlatformRun, instance: DolphinSchedulerInstance) -> datetime:
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
        invocation: DataOpsInvocation | None,
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
            "invocation": (
                invocation.model_dump(mode="json", by_alias=True)
                if invocation is not None
                else None
            ),
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
        binding, _artifact = self._resolve_binding(tenant, binding)
        self._validate_binding(run, binding)
        self._validate_workload_identity(run, actor_subject)
        invocation = self._resolve_invocation(run)
        match = self._find_one(binding, run, invocation)
        if match is None:
            raise DolphinSchedulerCorrelationNotFoundError(
                "no workflow instance matches the PlatformRun correlation"
            )
        instance = self.client.get_instance(match.instance_id, binding.workflow_definition_code)
        observation, created = self._state_observation(
            run, binding, instance, attempt_no, invocation
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
        if provider_state == "STOP" and run.status == RunStatus.CANCELLING:
            run = self.gateway.transition_run(
                tenant,
                run.run_id,
                run.state_version,
                RunStatus.CANCELLED,
                actor_subject,
                "DolphinScheduler confirms cancellation",
                {
                    "provider_state": provider_state,
                    "workflow_instance_id": instance.instance_id,
                    "observation_id": str(observation.observation_id),
                },
            )
        elif run.status == RunStatus.CANCELLING and provider_state in _RUNNING_STATES:
            raise DolphinSchedulerReconciliationRequired(
                "DolphinScheduler cancellation has not reached STOP"
            )
        elif run.status == RunStatus.CANCELLING and provider_state in (
            _TERMINAL_PROVIDER_STATES - {"STOP"}
        ):
            incident_result = self.gateway.record_cancellation_terminal_mismatch(
                observation,
                actor_subject=actor_subject,
            )
            run = incident_result.run
        elif provider_state in _RUNNING_STATES and run.status in {
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
        policy_decision_artifact_id: UUID,
    ) -> PlatformRun:
        capability = self._require_cancel_capability()
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        run = self.gateway.get_run(tenant, run_id)
        binding, execution_plan_artifact = self._resolve_binding(tenant, binding)
        self._validate_binding(run, binding)
        self._validate_workload_identity(run, actor_subject)
        self._authorize_cancel(
            run,
            execution_plan_artifact,
            policy_decision_artifact_id,
        )
        invocation = self._resolve_invocation(run)
        match = self._find_one(binding, run, invocation)
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
                {
                    "workflow_instance_id": match.instance_id,
                    "cancel_admission": capability.cancel_admission,
                    "capability_sha256": capability.capability_sha256,
                },
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
        '"startParams": _json(self.start_params(run, invocation))',
        '"execType": "COMPLEMENT_DATA"',
        '"runMode": "RUN_MODE_SERIAL"',
        "workflow instance is missing required correlation variables",
        "correlation scan reached the configured page limit",
        "dispatch outcome is unknown; reconcile before retry",
        "platform verdict still pending",
        "def persist_binding(",
        "def load_binding(",
        "parse_dolphinscheduler_binding_artifact",
        "dispatch requires immutable policy decision references",
        "validate_run_authorization_evidence",
        "DOLPHINSCHEDULER_CAPABILITY_SCHEMA",
        "def capability_report(",
        "provider terminal STOP capability is not certified",
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
    probe_parser.add_argument("--workload-subject", required=True)
    probe_parser.add_argument("--policy-evaluator-subject", required=True)
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
        workload_subject=args.workload_subject,
        policy_evaluator_subject=args.policy_evaluator_subject,
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
