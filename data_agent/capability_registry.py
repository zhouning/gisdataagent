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

from .dataops_cancel import DataOpsCancelRequest, DataOpsCancelResponse
from .dataops_manual import ManualDataOpsRunRequest, ManualDataOpsRunResponse
from .platform_contracts import canonical_json_fingerprint

CAPABILITY_SPEC_SCHEMA = "gda.capability-spec.v1"
CAPABILITY_REGISTRY_SCHEMA = "gda.capability-registry.v1"
CAPABILITY_FINGERPRINT_HEADER = "X-GDA-Capability-Fingerprint"
_CAPABILITY_ID_RE = re.compile(
    r"^[a-z][a-z0-9]*(?:\.[a-z][a-z0-9_-]*){2,7}$"
)
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
    schema_id = (
        "https://geospatial-data-agent.local/schemas/"
        f"{semantic_type}.json"
    )
    schema = model.model_json_schema(
        ref_template=f"{schema_id}#/$defs/{{model}}"
    )
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
        if any(
            not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", item)
            for item in value
        ):
            raise ValueError("invalid HTTP path parameter")
        return value

    @model_validator(mode="after")
    def _coherent_response_envelope(self) -> HttpProjection:
        if self.success_status in self.additional_success_statuses:
            raise ValueError(
                "primary HTTP success status cannot be repeated as additional"
            )
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
            binding
            for binding in self.surfaces
            if binding.status is SurfaceStatus.IMPLEMENTED
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
                raise ValueError(
                    "HTTP aliases reference unknown canonical input properties"
                )
            input_properties = set(self.input.json_schema.get("properties", {}))
            unknown_path_parameters = set(self.http.path_parameters) - input_properties
            if unknown_path_parameters:
                raise ValueError(
                    "HTTP path parameters reference unknown canonical input properties"
                )
            required_input = set(self.input.json_schema.get("required", []))
            optional_path_parameters = (
                set(self.http.path_parameters) - required_input
            )
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
        return canonical_json_fingerprint(
            self.model_dump(mode="json", by_alias=True)
        )

    def assert_invocation_fingerprint(self, value: str | None) -> None:
        """Reject an explicitly bound caller when its contract has drifted."""
        if value is None:
            return
        candidate = value.strip()
        if not hmac.compare_digest(candidate, self.fingerprint):
            raise CapabilityFingerprintMismatchError(
                f"capability contract mismatch for "
                f"{self.capability_id}@{self.version}"
            )

    def validate_input(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            Draft202012Validator(self.input.json_schema).validate(payload)
        except JsonSchemaError as exc:
            path = ".".join(str(part) for part in exc.absolute_path) or "$"
            raise CapabilityInputError(
                f"{self.capability_id} input {path}: {exc.message}"
            ) from exc
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
                    "content": {
                        "application/json": {"schema": response_schema}
                    },
                }
                for status in self.http.success_statuses
            } | {
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
        operation.setdefault("parameters", []).append({
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
        })
        return {
            "openapi": "3.1.0",
            "info": {"title": self.title, "version": self.version},
            "paths": {
                self.http.path: {self.http.method.lower(): operation}
            },
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
                                "accepted", "dispatching", "running", "cancelling",
                                "reconciling", "succeeded", "failed", "cancelled",
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
                "specversion", "id", "source", "type", "subject", "time",
                "datacontenttype", "data",
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
                        "capabilityEvent": {
                            "$ref": "#/components/messages/capabilityEvent"
                        }
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
            spec for (registered_id, _), spec in self._specs.items()
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
        return tuple(sorted(
            specs,
            key=lambda item: (item.capability_id, _semver_key(item.version)),
        ))

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
                    "id", "name", "type", "format", "backend", "crs",
                    "features", "size_bytes", "tags", "description", "owner",
                    "shared", "relevance", "access_path",
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
) -> tuple[SurfaceBinding, ...]:
    """Bind deterministic clients to the same authenticated HTTP projection."""
    entrypoints = {
        Surface.WEB: "frontend:PlatformCapabilitiesPanel",
        Surface.API: api_entrypoint,
        Surface.SDK: "python:data_agent.capability_client:CapabilityClient.invoke",
        Surface.CLI: (
            "cli:python -m data_agent capability invoke "
            f"{capability_id}"
        ),
        Surface.NOTEBOOK: (
            "python:data_agent.capability_client:CapabilityClient.invoke"
        ),
        Surface.TUI: (
            "tui:/capability invoke "
            f"{capability_id} <json-object>"
        ),
    }
    return tuple(
        SurfaceBinding(
            surface=surface,
            status=(
                SurfaceStatus.IMPLEMENTED
                if surface in entrypoints
                else SurfaceStatus.PLANNED
            ),
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


_REGISTRY = CapabilityRegistry(
    (CATALOG_ASSET_SEARCH, DATAOPS_MANUAL_RUN_SUBMIT, DATAOPS_RUN_CANCEL)
)


def get_capability_registry() -> CapabilityRegistry:
    return _REGISTRY
