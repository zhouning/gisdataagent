"""Machine-verifiable capability truth and multi-surface projections.

The registry describes existing platform behavior. It does not execute jobs,
authorize subjects, or become another metadata store. A capability owns one
input/output contract that every user and agent surface must reuse.
"""

from __future__ import annotations

import hmac
import re
from enum import StrEnum
from typing import Any, Literal

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from jsonschema.exceptions import ValidationError as JsonSchemaError
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .chongqing_data_package_reconciliation_job import (
    ChongqingDataPackageReconciliationJob,
    ChongqingDataPackageReconciliationJobCancelRequest,
    ChongqingDataPackageReconciliationJobQuery,
)
from .chongqing_data_package_reconciliation_service import (
    ChongqingDataPackageReconciliationRequest,
    ChongqingDataPackageReconciliationResponse,
)
from .cross_store_projection_compensation_approval import (
    FederatedProjectionCompensationApprovalCaseRequest,
    FederatedProjectionCompensationApprovalCaseResult,
    FederatedProjectionCompensationExecutionApprovalRequest,
    FederatedProjectionCompensationExecutionApprovalResult,
)
from .cross_store_projection_compensation_proposal import (
    FederatedProjectionCompensationProposal,
    FederatedProjectionCompensationProposalReadRequest,
    FederatedProjectionCompensationProposalReadResponse,
    FederatedProjectionCompensationProposalRequest,
)
from .cross_store_projection_compensation_rule_contract import (
    CustomerCompensationRuleAuthorityReadRequest,
    CustomerCompensationRuleAuthorityReadResponse,
    FederatedProjectionCompensationRuleAssessment,
    FederatedProjectionCompensationRuleAssessmentRequest,
    FederatedProjectionCompensationRuleAuthorityAssessmentRequest,
)
from .dataops_cancel import DataOpsCancelRequest, DataOpsCancelResponse
from .dataops_manual import ManualDataOpsRunRequest, ManualDataOpsRunResponse
from .entity_authority_batch import (
    EntityAuthorityBatchRequest,
    EntityAuthorityBatchResponse,
)
from .entity_lineage_authority import (
    EntityLineageReceipt,
    EntityLineageRequest,
)
from .gis_analysis_execution import (
    GISAnalysisRunAdmissionRequest,
    GISAnalysisRunRecord,
)
from .governed_query import GovernedQueryRequest, GovernedQueryResponse
from .lakehouse_projection_service import (
    LakehouseProjectionRepairRequest,
    LakehouseProjectionRepairResult,
)
from .object_projection_service import (
    ObjectProjectionRepairRequest,
    ObjectProjectionRepairResult,
)
from .platform_contracts import canonical_json_fingerprint
from .postgis_projection_service import (
    PostGISProjectionRepairRequest,
    PostGISProjectionRepairResult,
)
from .rdf_projection_service import (
    RDFProjectionRepairRequest,
    RDFProjectionRepairResult,
)
from .vector_projection_service import (
    VectorProjectionRepairRequest,
    VectorProjectionRepairResult,
)

CAPABILITY_SPEC_SCHEMA = "gda.capability-spec.v1"
CAPABILITY_REGISTRY_SCHEMA = "gda.capability-registry.v1"
CAPABILITY_FINGERPRINT_HEADER = "X-GDA-Capability-Fingerprint"
_CAPABILITY_ID_RE = re.compile(r"^[a-z][a-z0-9]*(?:\.[a-z][a-z0-9_-]*){2,7}$")
_SEMVER_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
_SEMANTIC_TYPE_RE = re.compile(r"^[a-z][a-z0-9_.-]{2,127}$")
_MCP_TOOL_RE = re.compile(r"^[a-z][a-z0-9_]{1,63}$")


class CapabilityContractError(ValueError):
    """Base error for invalid registry state or capability payloads."""


class CapabilityNotFoundError(CapabilityContractError):
    """The requested capability or version is not registered."""


class CapabilityInputError(CapabilityContractError):
    """A capability invocation does not satisfy its canonical input schema."""


class CapabilityOutputError(CapabilityContractError):
    """A capability implementation violated its canonical output schema."""


class CapabilityFingerprintMismatchError(CapabilityContractError):
    """A caller is bound to a different version of the serving contract."""


def build_capability_json_schema(
    model: type[BaseModel],
    semantic_type: str,
) -> dict[str, Any]:
    """Build an embeddable Draft 2020-12 schema with stable absolute refs."""
    if not _SEMANTIC_TYPE_RE.fullmatch(semantic_type):
        raise CapabilityContractError("invalid capability schema semantic type")
    schema_id = f"https://geospatial-data-agent.local/schemas/{semantic_type}.json"
    schema = model.model_json_schema(ref_template=f"{schema_id}#/$defs/{{model}}")
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": schema_id,
        **schema,
    }


class OperationKind(StrEnum):
    QUERY = "query"
    COMMAND = "command"
    LONG_RUNNING = "long_running"


class RiskClass(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class SideEffect(StrEnum):
    NONE = "none"
    CONTROL_WRITE = "control_write"
    DATA_WRITE = "data_write"
    EXTERNAL_WRITE = "external_write"


class IdempotencyMode(StrEnum):
    NOT_APPLICABLE = "not_applicable"
    OPTIONAL = "optional"
    REQUIRED = "required"


class PreviewMode(StrEnum):
    UNSUPPORTED = "unsupported"
    OPTIONAL = "optional"
    REQUIRED = "required"


class ResultMode(StrEnum):
    SYNCHRONOUS = "synchronous"
    RUN_REF = "run_ref"


class CapabilityLifecycle(StrEnum):
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    RETIRED = "retired"


class Surface(StrEnum):
    WEB = "web"
    API = "api"
    SDK = "sdk"
    CLI = "cli"
    TUI = "tui"
    NOTEBOOK = "notebook"
    AGENT = "agent"


class SurfaceStatus(StrEnum):
    IMPLEMENTED = "implemented"
    PLANNED = "planned"
    NOT_APPLICABLE = "not_applicable"


class LlmMode(StrEnum):
    DISABLED = "disabled"
    OPTIONAL = "optional"
    REQUIRED_FOR_AGENT_FEATURE = "required_for_agent_feature"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


class SemanticJsonSchema(StrictModel):
    semantic_type: str
    json_schema: dict[str, Any]

    @field_validator("semantic_type")
    @classmethod
    def _valid_semantic_type(cls, value: str) -> str:
        if not _SEMANTIC_TYPE_RE.fullmatch(value):
            raise ValueError("semantic_type must be a canonical dotted identifier")
        return value

    @field_validator("json_schema")
    @classmethod
    def _valid_json_schema(cls, value: dict[str, Any]) -> dict[str, Any]:
        try:
            Draft202012Validator.check_schema(value)
        except SchemaError as exc:
            raise ValueError(f"invalid JSON Schema: {exc.message}") from exc
        if value.get("type") != "object":
            raise ValueError("capability JSON Schema root must use type object")
        return value


class PolicyContract(StrictModel):
    action: str = Field(pattern=r"^[a-z][a-z0-9_.-]{2,127}$")
    allowed_roles: tuple[str, ...]
    tenant_scoped: bool = True
    resource_kinds: tuple[str, ...]

    @model_validator(mode="after")
    def _non_empty_policy(self) -> PolicyContract:
        if not self.allowed_roles:
            raise ValueError("allowed_roles cannot be empty")
        if not self.resource_kinds:
            raise ValueError("resource_kinds cannot be empty")
        if len(set(self.allowed_roles)) != len(self.allowed_roles):
            raise ValueError("allowed_roles must be unique")
        return self


class ExecutionContract(StrictModel):
    idempotency: IdempotencyMode
    preview: PreviewMode
    result: ResultMode
    cancellable: bool = False
    compensatable: bool = False
    reconcilable: bool = False


class SurfaceBinding(StrictModel):
    surface: Surface
    status: SurfaceStatus
    entrypoint: str = ""
    requires_llm: bool = False

    @model_validator(mode="after")
    def _entrypoint_matches_status(self) -> SurfaceBinding:
        if self.status is SurfaceStatus.IMPLEMENTED and not self.entrypoint.strip():
            raise ValueError("implemented surface requires an entrypoint")
        if self.status is not SurfaceStatus.IMPLEMENTED and self.entrypoint:
            raise ValueError("non-implemented surface cannot declare an entrypoint")
        if self.requires_llm and self.surface is not Surface.AGENT:
            raise ValueError("only the agent surface may require an LLM")
        return self


class HttpProjection(StrictModel):
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
    path: str = Field(pattern=r"^/api/[A-Za-z0-9_./{}:-]+$")
    operation_id: str = Field(pattern=r"^[a-z][A-Za-z0-9]{2,127}$")
    input_location: Literal["query", "body"]
    success_status: int = Field(default=200, ge=200, le=299)
    additional_success_statuses: tuple[int, ...] = ()
    parameter_aliases: dict[str, str] = Field(default_factory=dict)
    path_parameters: tuple[str, ...] = ()
    response_envelope: Literal["direct", "platform_v1"] = "direct"
    include_created: bool = False

    @field_validator("additional_success_statuses")
    @classmethod
    def _valid_additional_success_statuses(
        cls,
        value: tuple[int, ...],
    ) -> tuple[int, ...]:
        if len(value) != len(set(value)):
            raise ValueError("additional HTTP success statuses must be unique")
        if any(status < 200 or status > 299 for status in value):
            raise ValueError("additional HTTP success statuses must be 2xx")
        return value

    @field_validator("parameter_aliases")
    @classmethod
    def _valid_parameter_aliases(cls, value: dict[str, str]) -> dict[str, str]:
        if len(set(value.values())) != len(value):
            raise ValueError("HTTP parameter aliases must be unique")
        if any(not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", item) for item in value.values()):
            raise ValueError("invalid HTTP parameter alias")
        return value

    @field_validator("path_parameters")
    @classmethod
    def _valid_path_parameters(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("HTTP path parameters must be unique")
        if any(not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", item) for item in value):
            raise ValueError("invalid HTTP path parameter")
        return value

    @model_validator(mode="after")
    def _coherent_response_envelope(self) -> HttpProjection:
        if self.success_status in self.additional_success_statuses:
            raise ValueError("primary HTTP success status cannot be repeated as additional")
        if self.include_created and self.response_envelope != "platform_v1":
            raise ValueError("created is only available in the platform_v1 envelope")
        placeholders = tuple(re.findall(r"{([A-Za-z][A-Za-z0-9_-]{0,63})}", self.path))
        if set(placeholders) != set(self.path_parameters):
            raise ValueError("HTTP path placeholders must match path_parameters")
        return self

    @property
    def success_statuses(self) -> tuple[int, ...]:
        return (self.success_status, *self.additional_success_statuses)


class McpProjection(StrictModel):
    tool_name: str
    title: str

    @field_validator("tool_name")
    @classmethod
    def _valid_tool_name(cls, value: str) -> str:
        if not _MCP_TOOL_RE.fullmatch(value):
            raise ValueError("invalid MCP tool name")
        return value


class AsyncApiProjection(StrictModel):
    channel: str = Field(pattern=r"^[a-z][a-z0-9._/-]{2,127}$")
    message_type: str = Field(pattern=r"^[a-z][a-z0-9_.-]{2,127}$")
    operation_id: str = Field(pattern=r"^[a-z][A-Za-z0-9]{2,127}$")


class CapabilitySpec(StrictModel):
    schema_version: Literal["gda.capability-spec.v1"] = Field(
        default=CAPABILITY_SPEC_SCHEMA,
        alias="schema",
    )
    capability_id: str
    version: str
    title: str = Field(min_length=1, max_length=128)
    description: str = Field(min_length=1, max_length=512)
    owner: str = Field(pattern=r"^[a-z][a-z0-9_.-]{2,127}$")
    tier: Literal["P0", "P1", "P2"]
    lifecycle: CapabilityLifecycle
    operation: OperationKind
    risk: RiskClass
    side_effect: SideEffect
    input: SemanticJsonSchema
    output: SemanticJsonSchema
    policy: PolicyContract
    execution: ExecutionContract
    surfaces: tuple[SurfaceBinding, ...]
    http: HttpProjection | None = None
    mcp: McpProjection | None = None
    async_api: AsyncApiProjection | None = None

    @field_validator("capability_id")
    @classmethod
    def _valid_capability_id(cls, value: str) -> str:
        if not _CAPABILITY_ID_RE.fullmatch(value):
            raise ValueError("capability_id must be a canonical dotted identifier")
        return value

    @field_validator("version")
    @classmethod
    def _valid_version(cls, value: str) -> str:
        if not _SEMVER_RE.fullmatch(value):
            raise ValueError("version must use semantic versioning")
        return value

    @model_validator(mode="after")
    def _coherent_contract(self) -> CapabilitySpec:
        bindings = {binding.surface: binding for binding in self.surfaces}
        if len(bindings) != len(self.surfaces):
            raise ValueError("surface bindings must be unique")
        if self.tier == "P0" and set(bindings) != set(Surface):
            raise ValueError("P0 capability must declare the full parity surface matrix")
        implemented = [
            binding for binding in self.surfaces if binding.status is SurfaceStatus.IMPLEMENTED
        ]
        if not any(not item.requires_llm for item in implemented):
            raise ValueError("capability requires an implemented LLM-free surface")
        if Surface.AGENT not in bindings:
            raise ValueError("capability must declare an agent surface")
        if self.http is not None:
            api = bindings.get(Surface.API)
            if api is None or api.status is not SurfaceStatus.IMPLEMENTED:
                raise ValueError("HTTP projection requires an implemented API surface")
            unknown_aliases = set(self.http.parameter_aliases) - set(
                self.input.json_schema.get("properties", {})
            )
            if unknown_aliases:
                raise ValueError("HTTP aliases reference unknown canonical input properties")
            input_properties = set(self.input.json_schema.get("properties", {}))
            unknown_path_parameters = set(self.http.path_parameters) - input_properties
            if unknown_path_parameters:
                raise ValueError(
                    "HTTP path parameters reference unknown canonical input properties"
                )
            required_input = set(self.input.json_schema.get("required", []))
            optional_path_parameters = set(self.http.path_parameters) - required_input
            if optional_path_parameters:
                raise ValueError("HTTP path parameters must be required canonical input")
            if set(self.http.parameter_aliases) & set(self.http.path_parameters):
                raise ValueError("HTTP path parameters cannot use query aliases")
            if self.http.input_location == "body" and self.http.parameter_aliases:
                raise ValueError("body projection cannot declare query aliases")
        if self.mcp is not None:
            agent = bindings.get(Surface.AGENT)
            if agent is None or agent.status is not SurfaceStatus.IMPLEMENTED:
                raise ValueError("MCP projection requires an implemented agent surface")

        if self.operation is OperationKind.QUERY:
            if self.side_effect is not SideEffect.NONE:
                raise ValueError("query capability cannot declare side effects")
            if self.execution.idempotency is not IdempotencyMode.NOT_APPLICABLE:
                raise ValueError("query capability cannot require idempotency keys")
            if self.execution.result is not ResultMode.SYNCHRONOUS:
                raise ValueError("query capability must return synchronously")
            if self.execution.preview is not PreviewMode.UNSUPPORTED:
                raise ValueError("read-only query does not use a preview mutation")
            if self.async_api is not None:
                raise ValueError("synchronous query cannot declare AsyncAPI projection")
        elif self.operation is OperationKind.LONG_RUNNING:
            if self.side_effect is SideEffect.NONE:
                raise ValueError("long-running capability must declare its side effect")
            if self.execution.result is not ResultMode.RUN_REF:
                raise ValueError("long-running capability must return RunRef")
            if self.execution.idempotency is not IdempotencyMode.REQUIRED:
                raise ValueError("long-running capability requires idempotency")
            if self.async_api is None:
                raise ValueError("long-running capability requires AsyncAPI projection")
        else:
            if self.side_effect is SideEffect.NONE:
                raise ValueError("command capability must declare its side effect")
            if self.execution.result is not ResultMode.SYNCHRONOUS:
                raise ValueError("command capability must return synchronously")
            if (
                self.risk in {RiskClass.HIGH, RiskClass.CRITICAL}
                and self.execution.idempotency is not IdempotencyMode.REQUIRED
            ):
                raise ValueError("high-risk command capability requires idempotency")
        return self

    @property
    def fingerprint(self) -> str:
        return canonical_json_fingerprint(self.model_dump(mode="json", by_alias=True))

    def assert_invocation_fingerprint(self, value: str | None) -> None:
        """Reject an explicitly bound caller when its contract has drifted."""
        if value is None:
            return
        candidate = value.strip()
        if not hmac.compare_digest(candidate, self.fingerprint):
            raise CapabilityFingerprintMismatchError(
                f"capability contract mismatch for {self.capability_id}@{self.version}"
            )

    def validate_input(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            Draft202012Validator(self.input.json_schema).validate(payload)
        except JsonSchemaError as exc:
            path = ".".join(str(part) for part in exc.absolute_path) or "$"
            raise CapabilityInputError(f"{self.capability_id} input {path}: {exc.message}") from exc
        return payload

    def validate_output(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            Draft202012Validator(self.output.json_schema).validate(payload)
        except JsonSchemaError as exc:
            path = ".".join(str(part) for part in exc.absolute_path) or "$"
            raise CapabilityOutputError(
                f"{self.capability_id} output {path}: {exc.message}"
            ) from exc
        return payload

    def available_surfaces(self, llm_mode: LlmMode | str) -> tuple[Surface, ...]:
        mode = LlmMode(llm_mode)
        return tuple(
            binding.surface
            for binding in self.surfaces
            if binding.status is SurfaceStatus.IMPLEMENTED
            and not (mode is LlmMode.DISABLED and binding.requires_llm)
        )

    def openapi_projection(self) -> dict[str, Any]:
        if self.http is None:
            raise CapabilityContractError("capability has no HTTP projection")
        response_schema = self.output.json_schema
        if self.http.response_envelope == "platform_v1":
            properties: dict[str, Any] = {
                "data": response_schema,
                "error": {"type": "null"},
                "request_id": {"type": "string", "minLength": 1},
            }
            required = ["data", "error", "request_id"]
            if self.http.include_created:
                properties["created"] = {"type": "boolean"}
                required.append("created")
            response_schema = {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "$id": (
                    "https://geospatial-data-agent.local/schemas/capabilities/"
                    f"{self.capability_id}/{self.version}/http-response.json"
                ),
                "type": "object",
                "properties": properties,
                "required": required,
                "additionalProperties": False,
            }
        operation: dict[str, Any] = {
            "operationId": self.http.operation_id,
            "summary": self.title,
            "description": self.description,
            "tags": ["Capability Registry"],
            "security": [{"cookieAuth": []}],
            "responses": {
                str(status): {
                    "description": "Canonical capability result",
                    "content": {"application/json": {"schema": response_schema}},
                }
                for status in self.http.success_statuses
            }
            | {
                "401": {"description": "Unauthorized"},
                "403": {"description": "Policy denied"},
            },
            "x-gda-capability-id": self.capability_id,
            "x-gda-capability-version": self.version,
            "x-gda-capability-fingerprint": self.fingerprint,
        }
        input_properties = self.input.json_schema.get("properties", {})
        required_input = set(self.input.json_schema.get("required", []))
        path_parameters = set(self.http.path_parameters)
        if path_parameters:
            operation["parameters"] = [
                {
                    "name": name,
                    "in": "path",
                    "required": True,
                    "schema": input_properties[name],
                    "x-gda-canonical-name": name,
                }
                for name in self.http.path_parameters
            ]
        if self.http.input_location == "body":
            body_properties = {
                name: schema
                for name, schema in input_properties.items()
                if name not in path_parameters
            }
            if body_properties:
                body_schema = self.input.json_schema
                if path_parameters:
                    canonical_id = self.input.json_schema.get("$id", "")
                    body_schema = {
                        **self.input.json_schema,
                        "$id": (
                            f"{canonical_id.removesuffix('.json')}.http-body.json"
                            if canonical_id
                            else canonical_id
                        ),
                        "properties": body_properties,
                        "required": [
                            name
                            for name in self.input.json_schema.get("required", [])
                            if name not in path_parameters
                        ],
                    }
                operation["requestBody"] = {
                    "required": bool(required_input - path_parameters),
                    "content": {"application/json": {"schema": body_schema}},
                }
        else:
            query_parameters = [
                {
                    "name": self.http.parameter_aliases.get(name, name),
                    "in": "query",
                    "required": name in required_input,
                    "schema": schema,
                    "x-gda-canonical-name": name,
                }
                for name, schema in input_properties.items()
                if name not in path_parameters
            ]
            operation.setdefault("parameters", []).extend(query_parameters)
        operation.setdefault("parameters", []).append(
            {
                "name": CAPABILITY_FINGERPRINT_HEADER,
                "in": "header",
                "required": False,
                "description": (
                    "Installed client CapabilitySpec fingerprint. When supplied, "
                    "the server rejects contract drift before execution."
                ),
                "schema": {
                    "type": "string",
                    "pattern": "^[0-9a-f]{64}$",
                },
            }
        )
        return {
            "openapi": "3.1.0",
            "info": {"title": self.title, "version": self.version},
            "paths": {self.http.path: {self.http.method.lower(): operation}},
            "components": {
                "securitySchemes": {
                    "cookieAuth": {"type": "apiKey", "in": "cookie", "name": "access_token"}
                }
            },
        }

    def mcp_projection(self) -> dict[str, Any]:
        if self.mcp is None:
            raise CapabilityContractError("capability has no MCP projection")
        return {
            "name": self.mcp.tool_name,
            "title": self.mcp.title,
            "description": self.description,
            "inputSchema": self.input.json_schema,
            "outputSchema": self.output.json_schema,
            "annotations": {
                "readOnlyHint": self.side_effect is SideEffect.NONE,
                "destructiveHint": self.risk in {RiskClass.HIGH, RiskClass.CRITICAL},
                "idempotentHint": (
                    self.operation is OperationKind.QUERY
                    or self.execution.idempotency is IdempotencyMode.REQUIRED
                ),
            },
            "_meta": {
                "gda/capabilityId": self.capability_id,
                "gda/capabilityVersion": self.version,
                "gda/fingerprint": self.fingerprint,
            },
        }

    def asyncapi_projection(self) -> dict[str, Any]:
        if self.async_api is None:
            raise CapabilityContractError("capability has no AsyncAPI projection")
        event_schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "specversion": {"const": "1.0"},
                "id": {"type": "string", "format": "uuid"},
                "source": {"type": "string", "format": "uri-reference"},
                "type": {"const": self.async_api.message_type},
                "subject": {"type": "string", "minLength": 1},
                "time": {"type": "string", "format": "date-time"},
                "datacontenttype": {"const": "application/json"},
                "data": {
                    "type": "object",
                    "properties": {
                        "tenant_id": {"type": "string", "minLength": 1},
                        "run_id": {"type": "string", "format": "uuid"},
                        "status": {
                            "enum": [
                                "accepted",
                                "dispatching",
                                "running",
                                "cancelling",
                                "reconciling",
                                "succeeded",
                                "failed",
                                "cancelled",
                                "timed_out",
                            ]
                        },
                        "state_version": {"type": "integer", "minimum": 0},
                        "artifact_ids": {
                            "type": "array",
                            "items": {"type": "string", "format": "uuid"},
                            "uniqueItems": True,
                        },
                    },
                    "required": ["tenant_id", "run_id", "status", "state_version"],
                    "additionalProperties": False,
                },
            },
            "required": [
                "specversion",
                "id",
                "source",
                "type",
                "subject",
                "time",
                "datacontenttype",
                "data",
            ],
            "additionalProperties": False,
        }
        return {
            "asyncapi": "3.0.0",
            "info": {"title": self.title, "version": self.version},
            "defaultContentType": "application/cloudevents+json",
            "channels": {
                "capabilityEvents": {
                    "address": self.async_api.channel,
                    "messages": {
                        "capabilityEvent": {"$ref": "#/components/messages/capabilityEvent"}
                    },
                }
            },
            "operations": {
                self.async_api.operation_id: {
                    "action": "receive",
                    "channel": {"$ref": "#/channels/capabilityEvents"},
                }
            },
            "components": {
                "messages": {
                    "capabilityEvent": {
                        "name": self.async_api.message_type,
                        "title": f"{self.title} status event",
                        "contentType": "application/cloudevents+json",
                        "payload": event_schema,
                        "x-gda-capability-id": self.capability_id,
                        "x-gda-capability-version": self.version,
                        "x-gda-capability-fingerprint": self.fingerprint,
                    }
                }
            },
        }


class CapabilityRegistry:
    """Immutable-in-practice in-process view of versioned capability truth."""

    def __init__(self, specs: tuple[CapabilitySpec, ...] = ()) -> None:
        self._specs: dict[tuple[str, str], CapabilitySpec] = {}
        for spec in specs:
            self.register(spec)

    def register(self, spec: CapabilitySpec) -> None:
        key = (spec.capability_id, spec.version)
        if key in self._specs:
            raise CapabilityContractError(
                f"duplicate capability version {spec.capability_id}@{spec.version}"
            )
        self._specs[key] = spec

    def get(self, capability_id: str, version: str | None = None) -> CapabilitySpec:
        candidates = [
            spec
            for (registered_id, _), spec in self._specs.items()
            if registered_id == capability_id
        ]
        if not candidates:
            raise CapabilityNotFoundError(capability_id)
        if version is not None:
            try:
                return self._specs[(capability_id, version)]
            except KeyError as exc:
                raise CapabilityNotFoundError(f"{capability_id}@{version}") from exc
        return max(candidates, key=lambda item: _semver_key(item.version))

    def list_specs(
        self,
        *,
        surface: Surface | str | None = None,
        llm_mode: LlmMode | str = LlmMode.OPTIONAL,
    ) -> tuple[CapabilitySpec, ...]:
        selected_surface = Surface(surface) if surface is not None else None
        mode = LlmMode(llm_mode)
        specs = []
        for spec in self._specs.values():
            available = set(spec.available_surfaces(mode))
            if selected_surface is None or selected_surface in available:
                specs.append(spec)
        return tuple(
            sorted(
                specs,
                key=lambda item: (item.capability_id, _semver_key(item.version)),
            )
        )

    @property
    def fingerprint(self) -> str:
        entries = [
            {
                "capability_id": spec.capability_id,
                "version": spec.version,
                "fingerprint": spec.fingerprint,
            }
            for spec in self.list_specs()
        ]
        return canonical_json_fingerprint(entries)


def _semver_key(value: str) -> tuple[int, int, int]:
    match = _SEMVER_RE.fullmatch(value)
    if match is None:
        raise CapabilityContractError(f"invalid semantic version {value!r}")
    return tuple(int(part) for part in match.groups())


_CATALOG_SEARCH_INPUT = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "minLength": 1,
            "maxLength": 512,
            "pattern": r"\S",
        }
    },
    "required": ["query"],
    "additionalProperties": False,
}

_NULLABLE_STRING = {"type": ["string", "null"]}
_NULLABLE_INTEGER = {"type": ["integer", "null"]}
_CATALOG_SEARCH_OUTPUT = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "status": {"enum": ["success", "error"]},
        "message": {"type": "string"},
        "count": {"type": "integer", "minimum": 0},
        "assets": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "name": {"type": "string"},
                    "type": _NULLABLE_STRING,
                    "format": _NULLABLE_STRING,
                    "backend": _NULLABLE_STRING,
                    "crs": _NULLABLE_STRING,
                    "features": _NULLABLE_INTEGER,
                    "size_bytes": _NULLABLE_INTEGER,
                    "tags": {"type": ["array", "null"], "items": {"type": "string"}},
                    "description": _NULLABLE_STRING,
                    "owner": {"type": "string"},
                    "shared": {"type": "boolean"},
                    "relevance": {"type": "number", "minimum": 0, "maximum": 1},
                    "access_path": {"type": "string"},
                    "postgis_table": {"type": "string"},
                    "local_path": {"type": "string"},
                },
                "required": [
                    "id",
                    "name",
                    "type",
                    "format",
                    "backend",
                    "crs",
                    "features",
                    "size_bytes",
                    "tags",
                    "description",
                    "owner",
                    "shared",
                    "relevance",
                    "access_path",
                ],
                "additionalProperties": False,
            },
        },
    },
    "required": ["status", "message"],
    "allOf": [
        {
            "if": {"properties": {"status": {"const": "success"}}},
            "then": {"required": ["count", "assets"]},
        }
    ],
    "additionalProperties": False,
}

CATALOG_ASSET_SEARCH = CapabilitySpec(
    capability_id="catalog.asset.search",
    version="1.0.0",
    title="Search governed data assets",
    description=(
        "Search tenant-visible data assets with the same typed contract across "
        "Web, API, SDK, CLI, TUI, Notebook, MCP, and the governed Agent tool."
    ),
    owner="data-platform.catalog",
    tier="P0",
    lifecycle=CapabilityLifecycle.ACTIVE,
    operation=OperationKind.QUERY,
    risk=RiskClass.LOW,
    side_effect=SideEffect.NONE,
    input=SemanticJsonSchema(
        semantic_type="gda.catalog.asset-search-request.v1",
        json_schema=_CATALOG_SEARCH_INPUT,
    ),
    output=SemanticJsonSchema(
        semantic_type="gda.catalog.asset-search-result.v1",
        json_schema=_CATALOG_SEARCH_OUTPUT,
    ),
    policy=PolicyContract(
        action="catalog.asset.search",
        allowed_roles=("viewer", "analyst", "admin"),
        tenant_scoped=True,
        resource_kinds=("data_asset",),
    ),
    execution=ExecutionContract(
        idempotency=IdempotencyMode.NOT_APPLICABLE,
        preview=PreviewMode.UNSUPPORTED,
        result=ResultMode.SYNCHRONOUS,
    ),
    surfaces=(
        SurfaceBinding(
            surface=Surface.WEB,
            status=SurfaceStatus.IMPLEMENTED,
            entrypoint="frontend:CatalogTab/semantic-search",
        ),
        SurfaceBinding(
            surface=Surface.API,
            status=SurfaceStatus.IMPLEMENTED,
            entrypoint="http:GET:/api/catalog/search",
        ),
        SurfaceBinding(
            surface=Surface.SDK,
            status=SurfaceStatus.IMPLEMENTED,
            entrypoint="python:data_agent.data_catalog:search_data_assets",
        ),
        SurfaceBinding(
            surface=Surface.CLI,
            status=SurfaceStatus.IMPLEMENTED,
            entrypoint="cli:python -m data_agent catalog search",
        ),
        SurfaceBinding(
            surface=Surface.TUI,
            status=SurfaceStatus.IMPLEMENTED,
            entrypoint="tui:/catalog <query>",
        ),
        SurfaceBinding(
            surface=Surface.NOTEBOOK,
            status=SurfaceStatus.IMPLEMENTED,
            entrypoint="python:data_agent.data_catalog:search_data_assets",
        ),
        SurfaceBinding(
            surface=Surface.AGENT,
            status=SurfaceStatus.IMPLEMENTED,
            entrypoint="mcp:search_catalog|adk:search_data_assets",
            requires_llm=True,
        ),
    ),
    http=HttpProjection(
        method="GET",
        path="/api/catalog/search",
        operation_id="searchCatalogAssets",
        input_location="query",
        parameter_aliases={"query": "q"},
    ),
    mcp=McpProjection(
        tool_name="search_catalog",
        title="Search governed data assets",
    ),
)


def _governed_http_client_surfaces(
    capability_id: str,
    api_entrypoint: str,
    *,
    agent_entrypoint: str | None = None,
) -> tuple[SurfaceBinding, ...]:
    """Bind deterministic clients to the same authenticated HTTP projection."""
    entrypoints = {
        Surface.WEB: "frontend:PlatformCapabilitiesPanel",
        Surface.API: api_entrypoint,
        Surface.SDK: "python:data_agent.capability_client:CapabilityClient.invoke",
        Surface.CLI: (f"cli:python -m data_agent capability invoke {capability_id}"),
        Surface.NOTEBOOK: ("python:data_agent.capability_client:CapabilityClient.invoke"),
        Surface.TUI: (f"tui:/capability invoke {capability_id} <json-object>"),
    }
    if agent_entrypoint is not None:
        entrypoints[Surface.AGENT] = agent_entrypoint
    return tuple(
        SurfaceBinding(
            surface=surface,
            status=(SurfaceStatus.IMPLEMENTED if surface in entrypoints else SurfaceStatus.PLANNED),
            entrypoint=entrypoints.get(surface, ""),
        )
        for surface in Surface
    )


DATAOPS_MANUAL_RUN_SUBMIT = CapabilitySpec(
    capability_id="dataops.run.submit-manual",
    version="1.0.0",
    title="Submit a governed manual DataOps run",
    description=(
        "Admit one human-requested DataOps run through the platform gateway, "
        "binding a stable client request identity, reviewed execution-plan "
        "artifact, server-owned workload delegation, policy evidence, Run, "
        "and transactional DolphinScheduler dispatch command."
    ),
    owner="data-platform.operations",
    tier="P0",
    lifecycle=CapabilityLifecycle.ACTIVE,
    operation=OperationKind.LONG_RUNNING,
    risk=RiskClass.HIGH,
    side_effect=SideEffect.EXTERNAL_WRITE,
    input=SemanticJsonSchema(
        semantic_type="gda.dataops.manual-run-request.v1",
        json_schema=build_capability_json_schema(
            ManualDataOpsRunRequest,
            "gda.dataops.manual-run-request.v1",
        ),
    ),
    output=SemanticJsonSchema(
        semantic_type="gda.dataops.manual-run-admission.v1",
        json_schema=build_capability_json_schema(
            ManualDataOpsRunResponse,
            "gda.dataops.manual-run-admission.v1",
        ),
    ),
    policy=PolicyContract(
        action="dataops.run.submit-manual",
        allowed_roles=("admin", "platform_operator"),
        tenant_scoped=True,
        resource_kinds=(
            "definition",
            "resource_version",
            "execution_plan_artifact",
            "platform_run",
        ),
    ),
    execution=ExecutionContract(
        idempotency=IdempotencyMode.REQUIRED,
        preview=PreviewMode.REQUIRED,
        result=ResultMode.RUN_REF,
        cancellable=True,
        reconcilable=True,
    ),
    surfaces=_governed_http_client_surfaces(
        "dataops.run.submit-manual",
        "http:POST:/api/platform/v1/dataops/manual-runs",
    ),
    http=HttpProjection(
        method="POST",
        path="/api/platform/v1/dataops/manual-runs",
        operation_id="submitManualDataOpsRun",
        input_location="body",
        success_status=202,
        additional_success_statuses=(200,),
        response_envelope="platform_v1",
        include_created=True,
    ),
    async_api=AsyncApiProjection(
        channel="gda.platform-runs.status",
        message_type="gda.platform-run.status-changed.v1",
        operation_id="receiveManualDataOpsRunStatus",
    ),
)


DATAOPS_RUN_CANCEL = CapabilitySpec(
    capability_id="dataops.run.cancel",
    version="1.0.0",
    title="Cancel a governed DataOps run",
    description=(
        "Admit one human-requested cancellation against an existing DataOps Run, "
        "enforcing expected state version, stable client request identity, the "
        "Run-bound execution plan, independent policy evidence, and transactional "
        "DolphinScheduler cancellation delivery."
    ),
    owner="data-platform.operations",
    tier="P0",
    lifecycle=CapabilityLifecycle.ACTIVE,
    operation=OperationKind.COMMAND,
    risk=RiskClass.HIGH,
    side_effect=SideEffect.EXTERNAL_WRITE,
    input=SemanticJsonSchema(
        semantic_type="gda.dataops.cancel-request.v1",
        json_schema=build_capability_json_schema(
            DataOpsCancelRequest,
            "gda.dataops.cancel-request.v1",
        ),
    ),
    output=SemanticJsonSchema(
        semantic_type="gda.dataops.cancel-admission.v1",
        json_schema=build_capability_json_schema(
            DataOpsCancelResponse,
            "gda.dataops.cancel-admission.v1",
        ),
    ),
    policy=PolicyContract(
        action="dolphinscheduler.cancel",
        allowed_roles=("admin", "platform_operator"),
        tenant_scoped=True,
        resource_kinds=(
            "platform_run",
            "execution_plan_artifact",
            "policy_decision_artifact",
            "platform_command",
        ),
    ),
    execution=ExecutionContract(
        idempotency=IdempotencyMode.REQUIRED,
        preview=PreviewMode.UNSUPPORTED,
        result=ResultMode.SYNCHRONOUS,
        reconcilable=True,
    ),
    surfaces=_governed_http_client_surfaces(
        "dataops.run.cancel",
        "http:POST:/api/platform/v1/runs/{run_id}/cancel",
    ),
    http=HttpProjection(
        method="POST",
        path="/api/platform/v1/runs/{run_id}/cancel",
        operation_id="cancelDataOpsRun",
        input_location="body",
        path_parameters=("run_id",),
        success_status=202,
        additional_success_statuses=(200,),
        response_envelope="platform_v1",
        include_created=True,
    ),
    async_api=AsyncApiProjection(
        channel="gda.platform-runs.status",
        message_type="gda.platform-run.status-changed.v1",
        operation_id="receiveDataOpsCancelStatus",
    ),
)


GOVERNED_SEMANTIC_QUERY = CapabilitySpec(
    capability_id="semantic.query.execute",
    version="4.1.0",
    title="Execute a governed semantic query",
    description=(
        "Route typed tenant-bound questions to admitted deterministic adapters, "
        "return verified versioned evidence, and admit metric or PostGIS Runs. "
        "Ontology, NL2SQL, and tenant-bound RAG remain version-locked."
    ),
    owner="data-platform.semantic-query",
    tier="P1",
    lifecycle=CapabilityLifecycle.ACTIVE,
    operation=OperationKind.COMMAND,
    risk=RiskClass.MEDIUM,
    side_effect=SideEffect.CONTROL_WRITE,
    input=SemanticJsonSchema(
        semantic_type="gda.governed-query-request.v4",
        json_schema=build_capability_json_schema(
            GovernedQueryRequest,
            "gda.governed-query-request.v4",
        ),
    ),
    output=SemanticJsonSchema(
        semantic_type="gda.governed-query-result.v4",
        json_schema=build_capability_json_schema(
            GovernedQueryResponse,
            "gda.governed-query-result.v4",
        ),
    ),
    policy=PolicyContract(
        action="semantic.query.execute",
        allowed_roles=("viewer", "analyst", "admin", "platform_operator"),
        tenant_scoped=True,
        resource_kinds=(
            "ontology_package",
            "semantic_model",
            "dataset",
            "document",
            "metric_definition",
            "metric_projection",
            "data_product",
            "source_snapshot",
            "table",
        ),
    ),
    execution=ExecutionContract(
        idempotency=IdempotencyMode.REQUIRED,
        preview=PreviewMode.UNSUPPORTED,
        result=ResultMode.SYNCHRONOUS,
    ),
    surfaces=(
        SurfaceBinding(
            surface=Surface.API,
            status=SurfaceStatus.IMPLEMENTED,
            entrypoint="http:POST:/api/governed-query",
        ),
        SurfaceBinding(
            surface=Surface.AGENT,
            status=SurfaceStatus.IMPLEMENTED,
            entrypoint="mcp:execute_governed_query",
        ),
    ),
    http=HttpProjection(
        method="POST",
        path="/api/governed-query",
        operation_id="executeGovernedSemanticQuery",
        input_location="body",
        additional_success_statuses=(202,),
    ),
    mcp=McpProjection(
        tool_name="execute_governed_query",
        title="Execute a governed semantic query",
    ),
)


GIS_ANALYSIS_EXECUTE = CapabilitySpec(
    capability_id="gis.analysis.execute",
    version="1.2.0",
    title="Execute a governed GIS analysis",
    description=(
        "Admit a registry-selected, version-bound PostGIS buffer, clip, or "
        "intersection Run over active immutable source bindings and publish a "
        "verified GeoJSON Artifact."
    ),
    owner="data-platform.gis-analysis",
    tier="P1",
    lifecycle=CapabilityLifecycle.ACTIVE,
    operation=OperationKind.LONG_RUNNING,
    risk=RiskClass.MEDIUM,
    side_effect=SideEffect.DATA_WRITE,
    input=SemanticJsonSchema(
        semantic_type="gda.gis-analysis-run-request.v1",
        json_schema=build_capability_json_schema(
            GISAnalysisRunAdmissionRequest,
            "gda.gis-analysis-run-request.v1",
        ),
    ),
    output=SemanticJsonSchema(
        semantic_type="gda.gis-analysis-run-record.v1",
        json_schema=build_capability_json_schema(
            GISAnalysisRunRecord,
            "gda.gis-analysis-run-record.v1",
        ),
    ),
    policy=PolicyContract(
        action="gis.analysis.execute",
        allowed_roles=("viewer", "analyst", "admin", "platform_operator"),
        tenant_scoped=True,
        resource_kinds=(
            "dataset",
            "source_snapshot",
            "table",
            "execution_plan_artifact",
            "query_result",
            "platform_run",
        ),
    ),
    execution=ExecutionContract(
        idempotency=IdempotencyMode.REQUIRED,
        preview=PreviewMode.UNSUPPORTED,
        result=ResultMode.RUN_REF,
        cancellable=True,
        reconcilable=False,
    ),
    surfaces=(
        SurfaceBinding(
            surface=Surface.API,
            status=SurfaceStatus.IMPLEMENTED,
            entrypoint="http:POST:/api/platform/v1/gis-analysis-runs",
        ),
        SurfaceBinding(
            surface=Surface.AGENT,
            status=SurfaceStatus.PLANNED,
        ),
    ),
    http=HttpProjection(
        method="POST",
        path="/api/platform/v1/gis-analysis-runs",
        operation_id="executeGovernedGisAnalysis",
        input_location="body",
        success_status=202,
        additional_success_statuses=(200,),
        response_envelope="platform_v1",
    ),
    async_api=AsyncApiProjection(
        channel="gda.platform-runs.status",
        message_type="gda.platform-run.status-changed.v1",
        operation_id="receiveGisAnalysisRunStatus",
    ),
)


ENTITY_AUTHORITY_BATCH_INGEST = CapabilitySpec(
    capability_id="entity.authority.batch.ingest",
    version="1.0.0",
    title="Ingest governed entity authority evidence in batches",
    description=(
        "Write typed temporal-entity, source-identity, Link-type, or Link-assertion "
        "drafts through the tenant-bound authority in bounded idempotent chunks. "
        "The natural-resource ontology and Chongqing customer data remain a technical "
        "baseline and are not domain approval or a production decision."
    ),
    owner="data-platform.entity-authority",
    tier="P1",
    lifecycle=CapabilityLifecycle.ACTIVE,
    operation=OperationKind.COMMAND,
    risk=RiskClass.HIGH,
    side_effect=SideEffect.DATA_WRITE,
    input=SemanticJsonSchema(
        semantic_type="gda.entity-authority-batch-request.v1",
        json_schema=build_capability_json_schema(
            EntityAuthorityBatchRequest,
            "gda.entity-authority-batch-request.v1",
        ),
    ),
    output=SemanticJsonSchema(
        semantic_type="gda.entity-authority-batch-response.v1",
        json_schema=build_capability_json_schema(
            EntityAuthorityBatchResponse,
            "gda.entity-authority-batch-response.v1",
        ),
    ),
    policy=PolicyContract(
        action="entity.authority.batch.ingest",
        allowed_roles=("admin", "platform_operator"),
        tenant_scoped=True,
        resource_kinds=(
            "entity",
            "source_identity",
            "entity_link",
            "link_type",
            "ontology_package",
            "source_snapshot",
        ),
    ),
    execution=ExecutionContract(
        idempotency=IdempotencyMode.REQUIRED,
        preview=PreviewMode.UNSUPPORTED,
        result=ResultMode.SYNCHRONOUS,
        reconcilable=True,
    ),
    surfaces=_governed_http_client_surfaces(
        "entity.authority.batch.ingest",
        "http:POST:/api/platform/v1/entity-authority/batches",
        agent_entrypoint="mcp:ingest_entity_authority_batch",
    ),
    http=HttpProjection(
        method="POST",
        path="/api/platform/v1/entity-authority/batches",
        operation_id="ingestEntityAuthorityBatch",
        input_location="body",
        response_envelope="platform_v1",
    ),
    mcp=McpProjection(
        tool_name="ingest_entity_authority_batch",
        title="Ingest governed entity authority evidence in batches",
    ),
)


CHONGQING_DATA_PACKAGE_RECONCILE = CapabilitySpec(
    capability_id="entity.data-package.reconcile",
    version="1.0.0",
    title="Reconcile a governed Chongqing entity data package",
    description=(
        "Resolve current entity, source-identity, and Link authority state inside "
        "the service; compile and apply one sealed Chongqing customer-package delta "
        "in resumable idempotent phases; and return proof hashes and operation counts. "
        "Results are an unreviewed technical baseline for assisted precheck only."
    ),
    owner="data-platform.entity-authority",
    tier="P1",
    lifecycle=CapabilityLifecycle.ACTIVE,
    operation=OperationKind.COMMAND,
    risk=RiskClass.HIGH,
    side_effect=SideEffect.DATA_WRITE,
    input=SemanticJsonSchema(
        semantic_type="gda.chongqing-data-package-reconciliation-request.v1",
        json_schema=build_capability_json_schema(
            ChongqingDataPackageReconciliationRequest,
            "gda.chongqing-data-package-reconciliation-request.v1",
        ),
    ),
    output=SemanticJsonSchema(
        semantic_type="gda.chongqing-data-package-reconciliation-response.v1",
        json_schema=build_capability_json_schema(
            ChongqingDataPackageReconciliationResponse,
            "gda.chongqing-data-package-reconciliation-response.v1",
        ),
    ),
    policy=PolicyContract(
        action="entity.data-package.reconcile",
        allowed_roles=("admin", "platform_operator"),
        tenant_scoped=True,
        resource_kinds=(
            "entity",
            "source_identity",
            "entity_link",
            "link_type",
            "ontology_package",
            "source_snapshot",
        ),
    ),
    execution=ExecutionContract(
        idempotency=IdempotencyMode.REQUIRED,
        preview=PreviewMode.UNSUPPORTED,
        result=ResultMode.SYNCHRONOUS,
        reconcilable=True,
    ),
    surfaces=_governed_http_client_surfaces(
        "entity.data-package.reconcile",
        "http:POST:/api/platform/v1/entity-authority/reconciliations",
        agent_entrypoint="mcp:reconcile_entity_data_package",
    ),
    http=HttpProjection(
        method="POST",
        path="/api/platform/v1/entity-authority/reconciliations",
        operation_id="reconcileEntityDataPackage",
        input_location="body",
        response_envelope="platform_v1",
    ),
    mcp=McpProjection(
        tool_name="reconcile_entity_data_package",
        title="Reconcile a governed Chongqing entity data package",
    ),
)


CHONGQING_DATA_PACKAGE_RECONCILIATION_JOB_SUBMIT = CapabilitySpec(
    capability_id="entity.data-package.reconcile-job.submit",
    version="1.0.0",
    title="Submit an asynchronous Chongqing package reconciliation job",
    description=(
        "Durably enqueue one sealed Chongqing package reconciliation request, "
        "returning a tenant-scoped job reference whose progress, cancellation, "
        "lease recovery, and result are queryable."
    ),
    owner="data-platform.entity-authority",
    tier="P1",
    lifecycle=CapabilityLifecycle.ACTIVE,
    operation=OperationKind.LONG_RUNNING,
    risk=RiskClass.HIGH,
    side_effect=SideEffect.DATA_WRITE,
    input=SemanticJsonSchema(
        semantic_type="gda.chongqing-data-package-reconciliation-job-submit.v1",
        json_schema=build_capability_json_schema(
            ChongqingDataPackageReconciliationRequest,
            "gda.chongqing-data-package-reconciliation-job-submit.v1",
        ),
    ),
    output=SemanticJsonSchema(
        semantic_type="gda.chongqing-data-package-reconciliation-job.v1",
        json_schema=build_capability_json_schema(
            ChongqingDataPackageReconciliationJob,
            "gda.chongqing-data-package-reconciliation-job.v1",
        ),
    ),
    policy=PolicyContract(
        action="entity.data-package.reconcile-job.submit",
        allowed_roles=("admin", "platform_operator"),
        tenant_scoped=True,
        resource_kinds=(
            "entity",
            "source_identity",
            "entity_link",
            "reconciliation_job",
        ),
    ),
    execution=ExecutionContract(
        idempotency=IdempotencyMode.REQUIRED,
        preview=PreviewMode.UNSUPPORTED,
        result=ResultMode.RUN_REF,
        cancellable=True,
        reconcilable=True,
    ),
    surfaces=_governed_http_client_surfaces(
        "entity.data-package.reconcile-job.submit",
        "http:POST:/api/platform/v1/entity-authority/reconciliation-jobs",
        agent_entrypoint="mcp:submit_entity_data_package_reconciliation",
    ),
    http=HttpProjection(
        method="POST",
        path="/api/platform/v1/entity-authority/reconciliation-jobs",
        operation_id="submitEntityDataPackageReconciliationJob",
        input_location="body",
        success_status=202,
        additional_success_statuses=(200,),
        response_envelope="platform_v1",
        include_created=True,
    ),
    mcp=McpProjection(
        tool_name="submit_entity_data_package_reconciliation",
        title="Submit an asynchronous Chongqing package reconciliation",
    ),
    async_api=AsyncApiProjection(
        channel="gda.entity-data-package-reconciliation.jobs",
        message_type="gda.entity-data-package-reconciliation-job.status-changed.v1",
        operation_id="receiveEntityDataPackageReconciliationJobStatus",
    ),
)


CHONGQING_DATA_PACKAGE_RECONCILIATION_JOB_GET = CapabilitySpec(
    capability_id="entity.data-package.reconcile-job.get",
    version="1.0.0",
    title="Get asynchronous Chongqing package reconciliation job status",
    description=(
        "Read one tenant-scoped reconciliation job state, progress, cancellation "
        "evidence, and completed technical result."
    ),
    owner="data-platform.entity-authority",
    tier="P1",
    lifecycle=CapabilityLifecycle.ACTIVE,
    operation=OperationKind.QUERY,
    risk=RiskClass.MEDIUM,
    side_effect=SideEffect.NONE,
    input=SemanticJsonSchema(
        semantic_type="gda.chongqing-data-package-reconciliation-job-query.v1",
        json_schema=build_capability_json_schema(
            ChongqingDataPackageReconciliationJobQuery,
            "gda.chongqing-data-package-reconciliation-job-query.v1",
        ),
    ),
    output=SemanticJsonSchema(
        semantic_type="gda.chongqing-data-package-reconciliation-job.v1",
        json_schema=build_capability_json_schema(
            ChongqingDataPackageReconciliationJob,
            "gda.chongqing-data-package-reconciliation-job.v1",
        ),
    ),
    policy=PolicyContract(
        action="entity.data-package.reconcile-job.get",
        allowed_roles=("admin", "platform_operator"),
        tenant_scoped=True,
        resource_kinds=("reconciliation_job",),
    ),
    execution=ExecutionContract(
        idempotency=IdempotencyMode.NOT_APPLICABLE,
        preview=PreviewMode.UNSUPPORTED,
        result=ResultMode.SYNCHRONOUS,
    ),
    surfaces=_governed_http_client_surfaces(
        "entity.data-package.reconcile-job.get",
        "http:GET:/api/platform/v1/entity-authority/reconciliation-jobs/{job_id}",
        agent_entrypoint="mcp:get_entity_data_package_reconciliation_job",
    ),
    http=HttpProjection(
        method="GET",
        path="/api/platform/v1/entity-authority/reconciliation-jobs/{job_id}",
        operation_id="getEntityDataPackageReconciliationJob",
        input_location="query",
        path_parameters=("job_id",),
        response_envelope="platform_v1",
    ),
    mcp=McpProjection(
        tool_name="get_entity_data_package_reconciliation_job",
        title="Get asynchronous Chongqing reconciliation job status",
    ),
)


CHONGQING_DATA_PACKAGE_RECONCILIATION_JOB_CANCEL = CapabilitySpec(
    capability_id="entity.data-package.reconcile-job.cancel",
    version="1.0.0",
    title="Cancel an asynchronous Chongqing package reconciliation job",
    description=(
        "Request cooperative cancellation of one queued or running reconciliation "
        "job; committed atomic batches are retained and never presented as rolled back."
    ),
    owner="data-platform.entity-authority",
    tier="P1",
    lifecycle=CapabilityLifecycle.ACTIVE,
    operation=OperationKind.COMMAND,
    risk=RiskClass.HIGH,
    side_effect=SideEffect.CONTROL_WRITE,
    input=SemanticJsonSchema(
        semantic_type="gda.chongqing-data-package-reconciliation-job-cancel-request.v1",
        json_schema=build_capability_json_schema(
            ChongqingDataPackageReconciliationJobCancelRequest,
            "gda.chongqing-data-package-reconciliation-job-cancel-request.v1",
        ),
    ),
    output=SemanticJsonSchema(
        semantic_type="gda.chongqing-data-package-reconciliation-job.v1",
        json_schema=build_capability_json_schema(
            ChongqingDataPackageReconciliationJob,
            "gda.chongqing-data-package-reconciliation-job.v1",
        ),
    ),
    policy=PolicyContract(
        action="entity.data-package.reconcile-job.cancel",
        allowed_roles=("admin", "platform_operator"),
        tenant_scoped=True,
        resource_kinds=("reconciliation_job",),
    ),
    execution=ExecutionContract(
        idempotency=IdempotencyMode.REQUIRED,
        preview=PreviewMode.UNSUPPORTED,
        result=ResultMode.SYNCHRONOUS,
        reconcilable=True,
    ),
    surfaces=_governed_http_client_surfaces(
        "entity.data-package.reconcile-job.cancel",
        "http:POST:/api/platform/v1/entity-authority/reconciliation-jobs/{job_id}/cancel",
        agent_entrypoint="mcp:cancel_entity_data_package_reconciliation_job",
    ),
    http=HttpProjection(
        method="POST",
        path="/api/platform/v1/entity-authority/reconciliation-jobs/{job_id}/cancel",
        operation_id="cancelEntityDataPackageReconciliationJob",
        input_location="body",
        path_parameters=("job_id",),
        success_status=202,
        additional_success_statuses=(200,),
        response_envelope="platform_v1",
        include_created=True,
    ),
    mcp=McpProjection(
        tool_name="cancel_entity_data_package_reconciliation_job",
        title="Cancel an asynchronous Chongqing reconciliation",
    ),
)


FEDERATED_PROJECTION_COMPENSATION_PROPOSAL_READ = CapabilitySpec(
    capability_id="projection.federated.compensation-proposal",
    version="1.0.0",
    title="Generate a bounded federated projection compensation proposal",
    description=(
        "Generate a deterministic, read-only compensation proposal from sealed "
        "projection plans and their exact federated recovery snapshot. The result "
        "is bound to the Chongqing customer dataset and natural-resource-one-map "
        "2.3.0; it may recommend read-only reconciliation but never persists, "
        "selects, approves, or executes a mutating candidate. Missing customer "
        "rollback, delete, restore, corrective-forward, or reconciliation rules "
        "remain explicit in the result."
    ),
    owner="data-platform.projection-consistency",
    tier="P1",
    lifecycle=CapabilityLifecycle.ACTIVE,
    operation=OperationKind.QUERY,
    risk=RiskClass.MEDIUM,
    side_effect=SideEffect.NONE,
    input=SemanticJsonSchema(
        semantic_type="gda.federated-projection-compensation-proposal-request.v1",
        json_schema=build_capability_json_schema(
            FederatedProjectionCompensationProposalRequest,
            "gda.federated-projection-compensation-proposal-request.v1",
        ),
    ),
    output=SemanticJsonSchema(
        semantic_type="gda.federated-projection-compensation-proposal.v1",
        json_schema=build_capability_json_schema(
            FederatedProjectionCompensationProposal,
            "gda.federated-projection-compensation-proposal.v1",
        ),
    ),
    policy=PolicyContract(
        action="projection.federated.compensation-proposal.read",
        allowed_roles=("admin", "platform_operator"),
        tenant_scoped=True,
        resource_kinds=(
            "projection",
            "federated_recovery_snapshot",
            "compensation_proposal",
        ),
    ),
    execution=ExecutionContract(
        idempotency=IdempotencyMode.NOT_APPLICABLE,
        preview=PreviewMode.UNSUPPORTED,
        result=ResultMode.SYNCHRONOUS,
    ),
    surfaces=_governed_http_client_surfaces(
        "projection.federated.compensation-proposal",
        "http:POST:/api/platform/v1/projections/federated/compensation-proposals",
        agent_entrypoint="mcp:generate_federated_projection_compensation_proposal",
    ),
    http=HttpProjection(
        method="POST",
        path="/api/platform/v1/projections/federated/compensation-proposals",
        operation_id="generateFederatedProjectionCompensationProposal",
        input_location="body",
        response_envelope="platform_v1",
    ),
    mcp=McpProjection(
        tool_name="generate_federated_projection_compensation_proposal",
        title="Generate a bounded federated compensation proposal",
    ),
)


FEDERATED_PROJECTION_COMPENSATION_PROPOSAL_GET = CapabilitySpec(
    capability_id="projection.federated.compensation-proposal.get",
    version="1.0.0",
    title="Read a persisted federated projection compensation proposal",
    description=(
        "Read the current and complete immutable compensation proposal history "
        "for one federated recovery run from the tenant-scoped PostgreSQL "
        "authority. Tenant identity comes only from authenticated context. The "
        "query never records, selects, approves, or executes a candidate, and "
        "returns only technical-baseline assisted-precheck evidence whose "
        "execution_allowed field remains false."
    ),
    owner="data-platform.projection-consistency",
    tier="P1",
    lifecycle=CapabilityLifecycle.ACTIVE,
    operation=OperationKind.QUERY,
    risk=RiskClass.MEDIUM,
    side_effect=SideEffect.NONE,
    input=SemanticJsonSchema(
        semantic_type="gda.federated-projection-compensation-proposal-read-request.v1",
        json_schema=build_capability_json_schema(
            FederatedProjectionCompensationProposalReadRequest,
            "gda.federated-projection-compensation-proposal-read-request.v1",
        ),
    ),
    output=SemanticJsonSchema(
        semantic_type="gda.federated-projection-compensation-proposal-read-response.v1",
        json_schema=build_capability_json_schema(
            FederatedProjectionCompensationProposalReadResponse,
            "gda.federated-projection-compensation-proposal-read-response.v1",
        ),
    ),
    policy=PolicyContract(
        action="projection.federated.compensation-proposal.read",
        allowed_roles=("admin", "platform_operator"),
        tenant_scoped=True,
        resource_kinds=(
            "federated_recovery_run",
            "compensation_proposal",
        ),
    ),
    execution=ExecutionContract(
        idempotency=IdempotencyMode.NOT_APPLICABLE,
        preview=PreviewMode.UNSUPPORTED,
        result=ResultMode.SYNCHRONOUS,
    ),
    surfaces=_governed_http_client_surfaces(
        "projection.federated.compensation-proposal.get",
        "http:GET:/api/platform/v1/projections/federated/compensation-proposals/{run_id}",
        agent_entrypoint="mcp:get_federated_projection_compensation_proposal",
    ),
    http=HttpProjection(
        method="GET",
        path="/api/platform/v1/projections/federated/compensation-proposals/{run_id}",
        operation_id="getFederatedProjectionCompensationProposal",
        input_location="query",
        path_parameters=("run_id",),
        response_envelope="platform_v1",
    ),
    mcp=McpProjection(
        tool_name="get_federated_projection_compensation_proposal",
        title="Read a persisted federated compensation proposal",
    ),
)


FEDERATED_PROJECTION_COMPENSATION_RULE_GET = CapabilitySpec(
    capability_id="projection.federated.compensation-rule.get",
    version="1.0.0",
    title="Read customer compensation rule authority",
    description=(
        "Read the tenant-scoped current and complete immutable history of "
        "customer compensation rule contracts from PostgreSQL. The optional "
        "rule_id narrows the query; tenant identity comes only from authenticated "
        "context. This surface reports technical-baseline assisted-precheck "
        "evidence and never writes, approves, selects, or executes a rule. "
        "The returned execution_allowed and automatic_mutating_selection_allowed "
        "fields remain false."
    ),
    owner="data-platform.projection-consistency",
    tier="P1",
    lifecycle=CapabilityLifecycle.ACTIVE,
    operation=OperationKind.QUERY,
    risk=RiskClass.MEDIUM,
    side_effect=SideEffect.NONE,
    input=SemanticJsonSchema(
        semantic_type="gda.customer-compensation-rule-authority-read-request.v1",
        json_schema=build_capability_json_schema(
            CustomerCompensationRuleAuthorityReadRequest,
            "gda.customer-compensation-rule-authority-read-request.v1",
        ),
    ),
    output=SemanticJsonSchema(
        semantic_type="gda.customer-compensation-rule-authority-read-response.v1",
        json_schema=build_capability_json_schema(
            CustomerCompensationRuleAuthorityReadResponse,
            "gda.customer-compensation-rule-authority-read-response.v1",
        ),
    ),
    policy=PolicyContract(
        action="projection.federated.compensation-rule.read",
        allowed_roles=("admin", "platform_operator"),
        tenant_scoped=True,
        resource_kinds=("customer_compensation_rule",),
    ),
    execution=ExecutionContract(
        idempotency=IdempotencyMode.NOT_APPLICABLE,
        preview=PreviewMode.UNSUPPORTED,
        result=ResultMode.SYNCHRONOUS,
    ),
    surfaces=_governed_http_client_surfaces(
        "projection.federated.compensation-rule.get",
        "http:GET:/api/platform/v1/projections/federated/compensation-rules",
        agent_entrypoint="mcp:get_federated_projection_compensation_rules",
    ),
    http=HttpProjection(
        method="GET",
        path="/api/platform/v1/projections/federated/compensation-rules",
        operation_id="getFederatedProjectionCompensationRules",
        input_location="query",
        response_envelope="platform_v1",
    ),
    mcp=McpProjection(
        tool_name="get_federated_projection_compensation_rules",
        title="Read customer compensation rule authority",
    ),
)


FEDERATED_PROJECTION_COMPENSATION_RULE_ASSESS = CapabilitySpec(
    capability_id="projection.federated.compensation-rule.assess",
    version="1.1.0",
    title="Assess customer compensation rule readiness",
    description=(
        "Assess caller-supplied customer compensation rule contracts against a "
        "sealed proposal for the Chongqing customer dataset and "
        "natural-resource-one-map 2.3.0. Report missing, unreviewed, awaiting, "
        "approved-but-not-executable, and drifted states. Approved evidence "
        "also requires the deployment-owned tenant trust registry to match "
        "authority, key, algorithm, fingerprint, validity, and revocation. "
        "The request cannot override that registry; no candidate is persisted, "
        "selected, approved, or executed."
    ),
    owner="data-platform.projection-consistency",
    tier="P1",
    lifecycle=CapabilityLifecycle.ACTIVE,
    operation=OperationKind.QUERY,
    risk=RiskClass.MEDIUM,
    side_effect=SideEffect.NONE,
    input=SemanticJsonSchema(
        semantic_type=(
            "gda.federated-projection-compensation-rule-assessment-request.v1"
        ),
        json_schema=build_capability_json_schema(
            FederatedProjectionCompensationRuleAssessmentRequest,
            "gda.federated-projection-compensation-rule-assessment-request.v1",
        ),
    ),
    output=SemanticJsonSchema(
        semantic_type="gda.federated-projection-compensation-rule-assessment.v2",
        json_schema=build_capability_json_schema(
            FederatedProjectionCompensationRuleAssessment,
            "gda.federated-projection-compensation-rule-assessment.v2",
        ),
    ),
    policy=PolicyContract(
        action="projection.federated.compensation-rule.read",
        allowed_roles=("admin", "platform_operator"),
        tenant_scoped=True,
        resource_kinds=(
            "compensation_proposal",
            "customer_compensation_rule",
        ),
    ),
    execution=ExecutionContract(
        idempotency=IdempotencyMode.NOT_APPLICABLE,
        preview=PreviewMode.UNSUPPORTED,
        result=ResultMode.SYNCHRONOUS,
    ),
    surfaces=_governed_http_client_surfaces(
        "projection.federated.compensation-rule.assess",
        "http:POST:/api/platform/v1/projections/federated/compensation-rule-assessments",
        agent_entrypoint="mcp:assess_federated_projection_compensation_rules",
    ),
    http=HttpProjection(
        method="POST",
        path=(
            "/api/platform/v1/projections/federated/"
            "compensation-rule-assessments"
        ),
        operation_id="assessFederatedProjectionCompensationRules",
        input_location="body",
        response_envelope="platform_v1",
    ),
    mcp=McpProjection(
        tool_name="assess_federated_projection_compensation_rules",
        title="Assess federated compensation customer rules",
    ),
)


FEDERATED_PROJECTION_COMPENSATION_RULE_AUTHORITY_ASSESS = CapabilitySpec(
    capability_id="projection.federated.compensation-rule.assess-current",
    version="1.0.0",
    title="Assess persisted federated compensation rule readiness",
    description=(
        "Read one tenant-scoped persisted compensation proposal and the "
        "customer compensation rule authority current view in one PostgreSQL "
        "snapshot, then report missing, draft, awaiting, approved-but-not-"
        "executable, and drifted states. The caller supplies only run_id; it "
        "cannot replace proposal evidence, rule contracts, tenant identity, or "
        "deployment trust anchors. This query never writes, approves, selects, "
        "or executes a compensation action."
    ),
    owner="data-platform.projection-consistency",
    tier="P1",
    lifecycle=CapabilityLifecycle.ACTIVE,
    operation=OperationKind.QUERY,
    risk=RiskClass.MEDIUM,
    side_effect=SideEffect.NONE,
    input=SemanticJsonSchema(
        semantic_type=(
            "gda.federated-projection-compensation-rule-authority-"
            "assessment-request.v1"
        ),
        json_schema=build_capability_json_schema(
            FederatedProjectionCompensationRuleAuthorityAssessmentRequest,
            "gda.federated-projection-compensation-rule-authority-"
            "assessment-request.v1",
        ),
    ),
    output=SemanticJsonSchema(
        semantic_type="gda.federated-projection-compensation-rule-assessment.v2",
        json_schema=build_capability_json_schema(
            FederatedProjectionCompensationRuleAssessment,
            "gda.federated-projection-compensation-rule-assessment.v2",
        ),
    ),
    policy=PolicyContract(
        action="projection.federated.compensation-rule.read",
        allowed_roles=("admin", "platform_operator"),
        tenant_scoped=True,
        resource_kinds=(
            "federated_recovery_run",
            "compensation_proposal",
            "customer_compensation_rule",
        ),
    ),
    execution=ExecutionContract(
        idempotency=IdempotencyMode.NOT_APPLICABLE,
        preview=PreviewMode.UNSUPPORTED,
        result=ResultMode.SYNCHRONOUS,
    ),
    surfaces=_governed_http_client_surfaces(
        "projection.federated.compensation-rule.assess-current",
        "http:GET:/api/platform/v1/projections/federated/"
        "compensation-rule-assessments/{run_id}",
        agent_entrypoint=(
            "mcp:assess_persisted_federated_projection_compensation_rules"
        ),
    ),
    http=HttpProjection(
        method="GET",
        path=(
            "/api/platform/v1/projections/federated/"
            "compensation-rule-assessments/{run_id}"
        ),
        operation_id="assessPersistedFederatedProjectionCompensationRules",
        input_location="query",
        path_parameters=("run_id",),
        response_envelope="platform_v1",
    ),
    mcp=McpProjection(
        tool_name="assess_persisted_federated_projection_compensation_rules",
        title="Assess persisted federated compensation customer rules",
    ),
)


FEDERATED_PROJECTION_COMPENSATION_APPROVAL_REQUEST = CapabilitySpec(
    capability_id="projection.federated.compensation-approval.request",
    version="1.0.0",
    title="Request review of a trusted federated compensation candidate",
    description=(
        "Bind one operator-selected corrective-forward, rollback, delete, or "
        "restore candidate to the tenant-scoped persisted proposal, customer "
        "compensation rule authority current, and deployment trust anchors, then "
        "create an idempotent ApprovalCase for human review. Tenant and requester "
        "come only from authenticated context. This technical-baseline assisted "
        "precheck never selects a candidate automatically, calls a Provider, "
        "authorizes execution, or represents customer, expert, production, or "
        "statutory approval."
    ),
    owner="data-platform.projection-consistency",
    tier="P1",
    lifecycle=CapabilityLifecycle.ACTIVE,
    operation=OperationKind.COMMAND,
    risk=RiskClass.MEDIUM,
    side_effect=SideEffect.CONTROL_WRITE,
    input=SemanticJsonSchema(
        semantic_type=(
            "gda.federated-projection-compensation-approval-case-request.v1"
        ),
        json_schema=build_capability_json_schema(
            FederatedProjectionCompensationApprovalCaseRequest,
            "gda.federated-projection-compensation-approval-case-request.v1",
        ),
    ),
    output=SemanticJsonSchema(
        semantic_type=(
            "gda.federated-projection-compensation-approval-case-result.v1"
        ),
        json_schema=build_capability_json_schema(
            FederatedProjectionCompensationApprovalCaseResult,
            "gda.federated-projection-compensation-approval-case-result.v1",
        ),
    ),
    policy=PolicyContract(
        action="projection.federated.compensation.review",
        allowed_roles=("admin", "platform_operator"),
        tenant_scoped=True,
        resource_kinds=(
            "federated_recovery_run",
            "compensation_proposal",
            "customer_compensation_rule",
            "approval_case",
        ),
    ),
    execution=ExecutionContract(
        idempotency=IdempotencyMode.REQUIRED,
        preview=PreviewMode.UNSUPPORTED,
        result=ResultMode.SYNCHRONOUS,
        reconcilable=True,
    ),
    surfaces=_governed_http_client_surfaces(
        "projection.federated.compensation-approval.request",
        "http:POST:/api/platform/v1/projections/federated/"
        "compensation-approval-cases",
        agent_entrypoint=(
            "mcp:request_federated_projection_compensation_approval"
        ),
    ),
    http=HttpProjection(
        method="POST",
        path=(
            "/api/platform/v1/projections/federated/"
            "compensation-approval-cases"
        ),
        operation_id="requestFederatedProjectionCompensationApproval",
        input_location="body",
        success_status=201,
        additional_success_statuses=(200,),
        response_envelope="platform_v1",
        include_created=True,
    ),
    mcp=McpProjection(
        tool_name="request_federated_projection_compensation_approval",
        title="Request review of a federated compensation candidate",
    ),
)


FEDERATED_PROJECTION_COMPENSATION_EXECUTION_APPROVAL_REQUEST = CapabilitySpec(
    capability_id=(
        "projection.federated.compensation-execution-approval.request"
    ),
    version="1.0.0",
    title="Request an independent federated compensation execution verdict",
    description=(
        "After a separate human has approved the review-only candidate case, "
        "rebuild the candidate from the tenant-scoped proposal and customer-rule "
        "authority current, bind that exact review evidence, and create a second "
        "idempotent ApprovalCase for an independent human execution verdict. The "
        "request remains a technical-baseline assisted precheck: it does not "
        "consume the verdict, call a Provider, execute a mutation, or represent "
        "customer, expert, production, or statutory approval."
    ),
    owner="data-platform.projection-consistency",
    tier="P1",
    lifecycle=CapabilityLifecycle.ACTIVE,
    operation=OperationKind.COMMAND,
    risk=RiskClass.MEDIUM,
    side_effect=SideEffect.CONTROL_WRITE,
    input=SemanticJsonSchema(
        semantic_type=(
            "gda.federated-projection-compensation-execution-approval-request.v1"
        ),
        json_schema=build_capability_json_schema(
            FederatedProjectionCompensationExecutionApprovalRequest,
            "gda.federated-projection-compensation-execution-approval-request.v1",
        ),
    ),
    output=SemanticJsonSchema(
        semantic_type=(
            "gda.federated-projection-compensation-execution-approval-result.v1"
        ),
        json_schema=build_capability_json_schema(
            FederatedProjectionCompensationExecutionApprovalResult,
            "gda.federated-projection-compensation-execution-approval-result.v1",
        ),
    ),
    policy=PolicyContract(
        action="projection.federated.compensation.execute",
        allowed_roles=("admin", "platform_operator"),
        tenant_scoped=True,
        resource_kinds=(
            "federated_recovery_run",
            "compensation_proposal",
            "compensation_candidate",
            "customer_compensation_rule",
            "approval_case",
        ),
    ),
    execution=ExecutionContract(
        idempotency=IdempotencyMode.REQUIRED,
        preview=PreviewMode.UNSUPPORTED,
        result=ResultMode.SYNCHRONOUS,
        reconcilable=True,
    ),
    surfaces=_governed_http_client_surfaces(
        "projection.federated.compensation-execution-approval.request",
        "http:POST:/api/platform/v1/projections/federated/"
        "compensation-execution-approval-cases",
        agent_entrypoint=(
            "mcp:request_federated_projection_compensation_execution_approval"
        ),
    ),
    http=HttpProjection(
        method="POST",
        path=(
            "/api/platform/v1/projections/federated/"
            "compensation-execution-approval-cases"
        ),
        operation_id=(
            "requestFederatedProjectionCompensationExecutionApproval"
        ),
        input_location="body",
        success_status=201,
        additional_success_statuses=(200,),
        response_envelope="platform_v1",
        include_created=True,
    ),
    mcp=McpProjection(
        tool_name=(
            "request_federated_projection_compensation_execution_approval"
        ),
        title="Request an independent compensation execution verdict",
    ),
)


POSTGIS_PROJECTION_REPAIR_EXECUTE = CapabilitySpec(
    capability_id="projection.postgis.repair",
    version="1.0.0",
    title="Execute a sealed PostGIS projection repair plan",
    description=(
        "Execute checkpoint, rebuild, or delete only for an explicitly registered "
        "PostGIS target. The request cannot provide SQL or target DDL; provider "
        "commit evidence is bound to the repair plan and idempotency key, then "
        "recorded in the PostgreSQL checkpoint authority."
    ),
    owner="data-platform.projection-consistency",
    tier="P1",
    lifecycle=CapabilityLifecycle.ACTIVE,
    operation=OperationKind.COMMAND,
    risk=RiskClass.CRITICAL,
    side_effect=SideEffect.DATA_WRITE,
    input=SemanticJsonSchema(
        semantic_type="gda.postgis-projection-repair-request.v1",
        json_schema=build_capability_json_schema(
            PostGISProjectionRepairRequest,
            "gda.postgis-projection-repair-request.v1",
        ),
    ),
    output=SemanticJsonSchema(
        semantic_type="gda.postgis-projection-repair-result.v1",
        json_schema=build_capability_json_schema(
            PostGISProjectionRepairResult,
            "gda.postgis-projection-repair-result.v1",
        ),
    ),
    policy=PolicyContract(
        action="projection.postgis.repair",
        allowed_roles=("admin", "platform_operator"),
        tenant_scoped=True,
        resource_kinds=("projection", "postgis_relation", "projection_checkpoint"),
    ),
    execution=ExecutionContract(
        idempotency=IdempotencyMode.REQUIRED,
        preview=PreviewMode.UNSUPPORTED,
        result=ResultMode.SYNCHRONOUS,
        reconcilable=True,
    ),
    surfaces=_governed_http_client_surfaces(
        "projection.postgis.repair",
        "http:POST:/api/platform/v1/projections/postgis/repairs",
        agent_entrypoint="mcp:execute_postgis_projection_repair",
    ),
    http=HttpProjection(
        method="POST",
        path="/api/platform/v1/projections/postgis/repairs",
        operation_id="executePostGISProjectionRepair",
        input_location="body",
        response_envelope="platform_v1",
    ),
    mcp=McpProjection(
        tool_name="execute_postgis_projection_repair",
        title="Execute a sealed PostGIS projection repair plan",
    ),
)


LAKEHOUSE_PROJECTION_REPAIR_EXECUTE = CapabilitySpec(
    capability_id="projection.lakehouse.repair",
    version="1.0.0",
    title="Execute a sealed Iceberg lakehouse projection repair plan",
    description=(
        "Execute checkpoint, rebuild, or delete only for an explicitly registered "
        "Iceberg table bound to the sealed Chongqing customer bundle. The request "
        "cannot provide rows, Spark configuration, storage endpoints, credentials, "
        "warehouse paths, or table identifiers; snapshot evidence is recorded in "
        "the PostgreSQL checkpoint authority."
    ),
    owner="data-platform.projection-consistency",
    tier="P1",
    lifecycle=CapabilityLifecycle.ACTIVE,
    operation=OperationKind.COMMAND,
    risk=RiskClass.CRITICAL,
    side_effect=SideEffect.DATA_WRITE,
    input=SemanticJsonSchema(
        semantic_type="gda.lakehouse-projection-repair-request.v1",
        json_schema=build_capability_json_schema(
            LakehouseProjectionRepairRequest,
            "gda.lakehouse-projection-repair-request.v1",
        ),
    ),
    output=SemanticJsonSchema(
        semantic_type="gda.lakehouse-projection-repair-result.v1",
        json_schema=build_capability_json_schema(
            LakehouseProjectionRepairResult,
            "gda.lakehouse-projection-repair-result.v1",
        ),
    ),
    policy=PolicyContract(
        action="projection.lakehouse.repair",
        allowed_roles=("admin", "platform_operator"),
        tenant_scoped=True,
        resource_kinds=(
            "projection",
            "iceberg_table",
            "customer_bundle",
            "projection_checkpoint",
        ),
    ),
    execution=ExecutionContract(
        idempotency=IdempotencyMode.REQUIRED,
        preview=PreviewMode.UNSUPPORTED,
        result=ResultMode.SYNCHRONOUS,
        reconcilable=True,
    ),
    surfaces=_governed_http_client_surfaces(
        "projection.lakehouse.repair",
        "http:POST:/api/platform/v1/projections/lakehouse/repairs",
        agent_entrypoint="mcp:execute_lakehouse_projection_repair",
    ),
    http=HttpProjection(
        method="POST",
        path="/api/platform/v1/projections/lakehouse/repairs",
        operation_id="executeLakehouseProjectionRepair",
        input_location="body",
        response_envelope="platform_v1",
    ),
    mcp=McpProjection(
        tool_name="execute_lakehouse_projection_repair",
        title="Execute a sealed Iceberg lakehouse projection repair plan",
    ),
)


OBJECT_PROJECTION_REPAIR_EXECUTE = CapabilitySpec(
    capability_id="projection.object-store.repair",
    version="1.0.0",
    title="Execute a sealed object-store projection repair plan",
    description=(
        "Execute checkpoint, rebuild, or delete only for an explicitly registered "
        "versioned S3 object bound to the sealed Chongqing customer bundle. The "
        "request cannot provide bytes, endpoints, credentials, buckets, keys, or "
        "artifact paths; provider evidence is recorded in the PostgreSQL checkpoint "
        "authority."
    ),
    owner="data-platform.projection-consistency",
    tier="P1",
    lifecycle=CapabilityLifecycle.ACTIVE,
    operation=OperationKind.COMMAND,
    risk=RiskClass.CRITICAL,
    side_effect=SideEffect.DATA_WRITE,
    input=SemanticJsonSchema(
        semantic_type="gda.object-projection-repair-request.v1",
        json_schema=build_capability_json_schema(
            ObjectProjectionRepairRequest,
            "gda.object-projection-repair-request.v1",
        ),
    ),
    output=SemanticJsonSchema(
        semantic_type="gda.object-projection-repair-result.v1",
        json_schema=build_capability_json_schema(
            ObjectProjectionRepairResult,
            "gda.object-projection-repair-result.v1",
        ),
    ),
    policy=PolicyContract(
        action="projection.object-store.repair",
        allowed_roles=("admin", "platform_operator"),
        tenant_scoped=True,
        resource_kinds=(
            "projection",
            "object_store_object",
            "customer_bundle",
            "projection_checkpoint",
        ),
    ),
    execution=ExecutionContract(
        idempotency=IdempotencyMode.REQUIRED,
        preview=PreviewMode.UNSUPPORTED,
        result=ResultMode.SYNCHRONOUS,
        reconcilable=True,
    ),
    surfaces=_governed_http_client_surfaces(
        "projection.object-store.repair",
        "http:POST:/api/platform/v1/projections/object-store/repairs",
        agent_entrypoint="mcp:execute_object_projection_repair",
    ),
    http=HttpProjection(
        method="POST",
        path="/api/platform/v1/projections/object-store/repairs",
        operation_id="executeObjectProjectionRepair",
        input_location="body",
        response_envelope="platform_v1",
    ),
    mcp=McpProjection(
        tool_name="execute_object_projection_repair",
        title="Execute a sealed object-store projection repair plan",
    ),
)


RDF_PROJECTION_REPAIR_EXECUTE = CapabilitySpec(
    capability_id="projection.rdf.repair",
    version="1.0.0",
    title="Execute a sealed RDF projection repair plan",
    description=(
        "Execute checkpoint, rebuild, or delete only for an explicitly registered "
        "Fuseki Graph Store target and immutable ontology package. The request cannot "
        "provide RDF content, endpoints, credentials, or graph identifiers; provider "
        "evidence is recorded in the PostgreSQL checkpoint authority."
    ),
    owner="data-platform.projection-consistency",
    tier="P1",
    lifecycle=CapabilityLifecycle.ACTIVE,
    operation=OperationKind.COMMAND,
    risk=RiskClass.CRITICAL,
    side_effect=SideEffect.DATA_WRITE,
    input=SemanticJsonSchema(
        semantic_type="gda.rdf-projection-repair-request.v1",
        json_schema=build_capability_json_schema(
            RDFProjectionRepairRequest,
            "gda.rdf-projection-repair-request.v1",
        ),
    ),
    output=SemanticJsonSchema(
        semantic_type="gda.rdf-projection-repair-result.v1",
        json_schema=build_capability_json_schema(
            RDFProjectionRepairResult,
            "gda.rdf-projection-repair-result.v1",
        ),
    ),
    policy=PolicyContract(
        action="projection.rdf.repair",
        allowed_roles=("admin", "platform_operator"),
        tenant_scoped=True,
        resource_kinds=("projection", "rdf_graph", "ontology_package", "projection_checkpoint"),
    ),
    execution=ExecutionContract(
        idempotency=IdempotencyMode.REQUIRED,
        preview=PreviewMode.UNSUPPORTED,
        result=ResultMode.SYNCHRONOUS,
        reconcilable=True,
    ),
    surfaces=_governed_http_client_surfaces(
        "projection.rdf.repair",
        "http:POST:/api/platform/v1/projections/rdf/repairs",
        agent_entrypoint="mcp:execute_rdf_projection_repair",
    ),
    http=HttpProjection(
        method="POST",
        path="/api/platform/v1/projections/rdf/repairs",
        operation_id="executeRDFProjectionRepair",
        input_location="body",
        response_envelope="platform_v1",
    ),
    mcp=McpProjection(
        tool_name="execute_rdf_projection_repair",
        title="Execute a sealed RDF projection repair plan",
    ),
)


VECTOR_PROJECTION_REPAIR_EXECUTE = CapabilitySpec(
    capability_id="projection.vector.repair",
    version="1.0.0",
    title="Execute a sealed pgvector projection repair plan",
    description=(
        "Execute checkpoint, rebuild, or delete only for an explicitly registered "
        "pgvector target. The request cannot provide SQL, target DDL, or vector "
        "dimensions; provider commit evidence is bound to the repair plan and "
        "idempotency key, then recorded in the PostgreSQL checkpoint authority."
    ),
    owner="data-platform.projection-consistency",
    tier="P1",
    lifecycle=CapabilityLifecycle.ACTIVE,
    operation=OperationKind.COMMAND,
    risk=RiskClass.CRITICAL,
    side_effect=SideEffect.DATA_WRITE,
    input=SemanticJsonSchema(
        semantic_type="gda.vector-projection-repair-request.v1",
        json_schema=build_capability_json_schema(
            VectorProjectionRepairRequest,
            "gda.vector-projection-repair-request.v1",
        ),
    ),
    output=SemanticJsonSchema(
        semantic_type="gda.vector-projection-repair-result.v1",
        json_schema=build_capability_json_schema(
            VectorProjectionRepairResult,
            "gda.vector-projection-repair-result.v1",
        ),
    ),
    policy=PolicyContract(
        action="projection.vector.repair",
        allowed_roles=("admin", "platform_operator"),
        tenant_scoped=True,
        resource_kinds=("projection", "pgvector_relation", "projection_checkpoint"),
    ),
    execution=ExecutionContract(
        idempotency=IdempotencyMode.REQUIRED,
        preview=PreviewMode.UNSUPPORTED,
        result=ResultMode.SYNCHRONOUS,
        reconcilable=True,
    ),
    surfaces=_governed_http_client_surfaces(
        "projection.vector.repair",
        "http:POST:/api/platform/v1/projections/vector/repairs",
        agent_entrypoint="mcp:execute_vector_projection_repair",
    ),
    http=HttpProjection(
        method="POST",
        path="/api/platform/v1/projections/vector/repairs",
        operation_id="executeVectorProjectionRepair",
        input_location="body",
        response_envelope="platform_v1",
    ),
    mcp=McpProjection(
        tool_name="execute_vector_projection_repair",
        title="Execute a sealed pgvector projection repair plan",
    ),
)


ENTITY_LINEAGE_RECORD = CapabilitySpec(
    capability_id="entity.lineage.record",
    version="1.0.0",
    title="Record governed entity lineage and Link propagation",
    description=(
        "Atomically record an entity merge, split, or replacement; retire all "
        "source entities; retract every active source Link; create, deduplicate, "
        "or explicitly drop propagated Links; and redirect every effective source "
        "identity. Split allocations are always explicit and fail closed when any "
        "Link or source identity is omitted."
    ),
    owner="data-platform.entity-authority",
    tier="P1",
    lifecycle=CapabilityLifecycle.ACTIVE,
    operation=OperationKind.COMMAND,
    risk=RiskClass.HIGH,
    side_effect=SideEffect.DATA_WRITE,
    input=SemanticJsonSchema(
        semantic_type="gda.entity-lineage-request.v1",
        json_schema=build_capability_json_schema(
            EntityLineageRequest,
            "gda.entity-lineage-request.v1",
        ),
    ),
    output=SemanticJsonSchema(
        semantic_type="gda.entity-lineage-receipt.v1",
        json_schema=build_capability_json_schema(
            EntityLineageReceipt,
            "gda.entity-lineage-receipt.v1",
        ),
    ),
    policy=PolicyContract(
        action="entity.lineage.record",
        allowed_roles=("admin", "platform_operator"),
        tenant_scoped=True,
        resource_kinds=(
            "entity",
            "entity_lineage",
            "source_identity",
            "entity_link",
            "link_type",
            "ontology_package",
            "source_snapshot",
        ),
    ),
    execution=ExecutionContract(
        idempotency=IdempotencyMode.REQUIRED,
        preview=PreviewMode.UNSUPPORTED,
        result=ResultMode.SYNCHRONOUS,
        reconcilable=True,
    ),
    surfaces=_governed_http_client_surfaces(
        "entity.lineage.record",
        "http:POST:/api/platform/v1/entity-authority/lineage-events",
        agent_entrypoint="mcp:record_entity_lineage_event",
    ),
    http=HttpProjection(
        method="POST",
        path="/api/platform/v1/entity-authority/lineage-events",
        operation_id="recordEntityLineageEvent",
        input_location="body",
        response_envelope="platform_v1",
    ),
    mcp=McpProjection(
        tool_name="record_entity_lineage_event",
        title="Record governed entity lineage and Link propagation",
    ),
)


_REGISTRY = CapabilityRegistry(
    (
        CATALOG_ASSET_SEARCH,
        DATAOPS_MANUAL_RUN_SUBMIT,
        DATAOPS_RUN_CANCEL,
        GOVERNED_SEMANTIC_QUERY,
        GIS_ANALYSIS_EXECUTE,
        ENTITY_AUTHORITY_BATCH_INGEST,
        CHONGQING_DATA_PACKAGE_RECONCILE,
        CHONGQING_DATA_PACKAGE_RECONCILIATION_JOB_SUBMIT,
        CHONGQING_DATA_PACKAGE_RECONCILIATION_JOB_GET,
        CHONGQING_DATA_PACKAGE_RECONCILIATION_JOB_CANCEL,
        FEDERATED_PROJECTION_COMPENSATION_PROPOSAL_READ,
        FEDERATED_PROJECTION_COMPENSATION_PROPOSAL_GET,
        FEDERATED_PROJECTION_COMPENSATION_RULE_GET,
        FEDERATED_PROJECTION_COMPENSATION_RULE_ASSESS,
        FEDERATED_PROJECTION_COMPENSATION_RULE_AUTHORITY_ASSESS,
        FEDERATED_PROJECTION_COMPENSATION_APPROVAL_REQUEST,
        FEDERATED_PROJECTION_COMPENSATION_EXECUTION_APPROVAL_REQUEST,
        LAKEHOUSE_PROJECTION_REPAIR_EXECUTE,
        OBJECT_PROJECTION_REPAIR_EXECUTE,
        POSTGIS_PROJECTION_REPAIR_EXECUTE,
        RDF_PROJECTION_REPAIR_EXECUTE,
        VECTOR_PROJECTION_REPAIR_EXECUTE,
        ENTITY_LINEAGE_RECORD,
    )
)


def get_capability_registry() -> CapabilityRegistry:
    return _REGISTRY
