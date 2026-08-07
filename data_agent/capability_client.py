"""Contract-driven SDK for invoking governed platform capabilities."""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import quote, urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field

from .capability_registry import (
    CAPABILITY_FINGERPRINT_HEADER,
    CAPABILITY_REGISTRY_SCHEMA,
    CapabilitySpec,
    LlmMode,
    Surface,
    get_capability_registry,
)

DEFAULT_PLATFORM_URL = "http://127.0.0.1:8000"


class CapabilityClientError(RuntimeError):
    """Base error for SDK configuration, transport, or remote contract failures."""


class CapabilityClientConfigurationError(CapabilityClientError):
    """The SDK cannot create an authenticated platform client."""


class CapabilityTransportError(CapabilityClientError):
    """The platform could not be reached."""


class CapabilityRemoteProtocolError(CapabilityClientError):
    """The platform returned a response that violates its discovery protocol."""


class CapabilityContractDriftError(CapabilityClientError):
    """The installed SDK contract differs from the serving platform contract."""


class CapabilityInvocationError(CapabilityClientError):
    """The platform rejected a capability invocation."""

    def __init__(self, message: str, *, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CapabilityHttpRequest(_FrozenModel):
    """One HTTP request projected from canonical capability input."""

    method: str
    path: str
    query: dict[str, Any] = Field(default_factory=dict)
    body: dict[str, Any] | None = None
    headers: dict[str, str]


class CapabilityInvocationResult(_FrozenModel):
    """Canonical output plus transport-owned admission metadata."""

    capability_id: str
    version: str
    fingerprint: str
    status_code: int
    data: dict[str, Any]
    request_id: str | None = None
    created: bool | None = None


def normalize_platform_base_url(value: str) -> str:
    """Return a root HTTP(S) platform URL without embedded credentials."""
    normalized = value.strip().rstrip("/")
    parsed = urlsplit(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise CapabilityClientConfigurationError(
            "platform base URL must be an absolute HTTP(S) URL"
        )
    if parsed.username is not None or parsed.password is not None:
        raise CapabilityClientConfigurationError(
            "platform base URL cannot contain credentials"
        )
    if parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
        raise CapabilityClientConfigurationError(
            "platform base URL must not contain a path, query, or fragment"
        )
    return normalized


def project_capability_http_request(
    spec: CapabilitySpec,
    payload: dict[str, Any],
) -> CapabilityHttpRequest:
    """Project already validated canonical input onto the declared HTTP surface."""
    if spec.http is None:
        raise CapabilityClientConfigurationError(
            f"{spec.capability_id}@{spec.version} has no HTTP projection"
        )

    path = spec.http.path
    path_parameters = set(spec.http.path_parameters)
    for name in spec.http.path_parameters:
        encoded = quote(str(payload[name]), safe="")
        path = path.replace(f"{{{name}}}", encoded)

    projected = {
        name: value
        for name, value in payload.items()
        if name not in path_parameters
    }
    query: dict[str, Any] = {}
    body: dict[str, Any] | None = None
    if spec.http.input_location == "body":
        body = projected
    else:
        query = {
            spec.http.parameter_aliases.get(name, name): value
            for name, value in projected.items()
        }

    return CapabilityHttpRequest(
        method=spec.http.method,
        path=path,
        query=query,
        body=body,
        headers={CAPABILITY_FINGERPRINT_HEADER: spec.fingerprint},
    )


class CapabilityClient:
    """Authenticated SDK that keeps every invocation bound to CapabilitySpec."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        access_token: str | None = None,
        timeout_seconds: float = 15.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        platform_url = normalize_platform_base_url(
            base_url or os.environ.get("GDA_PLATFORM_URL", DEFAULT_PLATFORM_URL)
        )
        token = (
            access_token
            if access_token is not None
            else os.environ.get("GDA_ACCESS_TOKEN", "")
        ).strip()
        if not token:
            raise CapabilityClientConfigurationError(
                "authenticated access token is required via access_token or "
                "GDA_ACCESS_TOKEN"
            )
        if timeout_seconds <= 0:
            raise CapabilityClientConfigurationError(
                "timeout_seconds must be greater than zero"
            )

        self._client = httpx.Client(
            base_url=platform_url,
            cookies={"access_token": token},
            headers={
                "Accept": "application/json",
                "User-Agent": "geospatial-data-agent-capability-sdk/1",
            },
            timeout=timeout_seconds,
            follow_redirects=False,
            transport=transport,
        )

    def __enter__(self) -> CapabilityClient:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def list_capabilities(
        self,
        *,
        surface: Surface | str | None = None,
        llm_mode: LlmMode | str = LlmMode.OPTIONAL,
    ) -> dict[str, Any]:
        """Read the authenticated server capability manifest."""
        mode = LlmMode(llm_mode)
        selected_surface = Surface(surface) if surface is not None else None
        params = {"llm_mode": mode.value}
        if selected_surface is not None:
            params["surface"] = selected_surface.value
        payload = self._get_json("/api/capability-specs", params=params)
        if payload.get("schema") != CAPABILITY_REGISTRY_SCHEMA:
            raise CapabilityRemoteProtocolError(
                "platform returned an unsupported capability registry schema"
            )
        if not isinstance(payload.get("capabilities"), list):
            raise CapabilityRemoteProtocolError(
                "platform capability manifest is missing capabilities"
            )
        return payload

    def get_capability(
        self,
        capability_id: str,
        *,
        version: str | None = None,
    ) -> dict[str, Any]:
        """Read one authenticated server CapabilitySpec and its projections."""
        path = f"/api/capability-specs/{quote(capability_id, safe='')}"
        params = {"version": version} if version is not None else None
        payload = self._get_json(path, params=params)
        remote_spec = payload.get("spec")
        if not isinstance(remote_spec, dict) or not isinstance(
            payload.get("fingerprint"), str
        ):
            raise CapabilityRemoteProtocolError(
                "platform capability detail is missing spec or fingerprint"
            )
        return payload

    def invoke(
        self,
        capability_id: str,
        payload: dict[str, Any],
        *,
        version: str | None = None,
    ) -> CapabilityInvocationResult:
        """Validate, project, execute, and validate one capability invocation."""
        spec = get_capability_registry().get(capability_id, version)
        canonical_input = spec.validate_input(payload)
        self._verify_remote_contract(spec)
        projected = project_capability_http_request(spec, canonical_input)

        try:
            response = self._client.request(
                projected.method,
                projected.path,
                params=projected.query or None,
                json=projected.body,
                headers=projected.headers,
            )
        except httpx.HTTPError as exc:
            raise CapabilityTransportError(
                f"platform request failed for {spec.capability_id}"
            ) from exc

        response_payload = self._decode_json(response)
        expected_statuses = spec.http.success_statuses if spec.http is not None else (200,)
        if response.status_code not in expected_statuses:
            if self._is_contract_mismatch(response_payload):
                raise CapabilityContractDriftError(
                    f"capability contract drift for "
                    f"{spec.capability_id}@{spec.version}"
                )
            raise CapabilityInvocationError(
                self._remote_error_message(response_payload, response.status_code),
                status_code=response.status_code,
            )

        data: Any = response_payload
        request_id = response.headers.get("x-request-id")
        created: bool | None = None
        if spec.http is not None and spec.http.response_envelope == "platform_v1":
            envelope_fields = {"data", "error", "request_id"}
            if spec.http.include_created:
                envelope_fields.add("created")
            if set(response_payload) != envelope_fields:
                raise CapabilityRemoteProtocolError(
                    "platform response fields do not match the capability envelope"
                )
            if response_payload.get("error") is not None:
                raise CapabilityRemoteProtocolError(
                    "successful platform response contains an error"
                )
            data = response_payload.get("data")
            request_id = response_payload.get("request_id")
            if not isinstance(request_id, str) or not request_id.strip():
                raise CapabilityRemoteProtocolError(
                    "platform response is missing a non-empty request_id"
                )
            if spec.http.include_created:
                created_value = response_payload.get("created")
                if not isinstance(created_value, bool):
                    raise CapabilityRemoteProtocolError(
                        "platform response is missing boolean created metadata"
                    )
                created = created_value

        if not isinstance(data, dict):
            raise CapabilityRemoteProtocolError(
                "canonical capability output must be a JSON object"
            )
        canonical_output = spec.validate_output(data)
        return CapabilityInvocationResult(
            capability_id=spec.capability_id,
            version=spec.version,
            fingerprint=spec.fingerprint,
            status_code=response.status_code,
            data=canonical_output,
            request_id=request_id,
            created=created,
        )

    def _verify_remote_contract(self, spec: CapabilitySpec) -> None:
        detail = self.get_capability(spec.capability_id, version=spec.version)
        remote_spec = detail["spec"]
        remote_identity = (
            remote_spec.get("capability_id"),
            remote_spec.get("version"),
        )
        local_identity = (spec.capability_id, spec.version)
        if remote_identity != local_identity or detail["fingerprint"] != spec.fingerprint:
            raise CapabilityContractDriftError(
                f"capability contract drift for {spec.capability_id}@{spec.version}"
            )

    def _get_json(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            response = self._client.get(path, params=params)
        except httpx.HTTPError as exc:
            raise CapabilityTransportError(
                "platform capability discovery request failed"
            ) from exc
        payload = self._decode_json(response)
        if response.status_code != 200:
            raise CapabilityInvocationError(
                self._remote_error_message(payload, response.status_code),
                status_code=response.status_code,
            )
        return payload

    @staticmethod
    def _decode_json(response: httpx.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise CapabilityRemoteProtocolError(
                f"platform returned non-JSON HTTP {response.status_code}"
            ) from exc
        if not isinstance(payload, dict):
            raise CapabilityRemoteProtocolError(
                "platform response must be a JSON object"
            )
        return payload

    @staticmethod
    def _remote_error_message(payload: dict[str, Any], status_code: int) -> str:
        error = payload.get("error")
        if isinstance(error, dict):
            detail = error.get("message") or error.get("code")
            if isinstance(detail, str) and detail:
                return f"platform rejected capability invocation: {detail}"
        if isinstance(error, str) and error:
            return f"platform rejected capability invocation: {error}"
        message = payload.get("message")
        if isinstance(message, str) and message:
            return f"platform rejected capability invocation: {message}"
        return f"platform rejected capability invocation with HTTP {status_code}"

    @staticmethod
    def _is_contract_mismatch(payload: dict[str, Any]) -> bool:
        if payload.get("code") == "capability_contract_mismatch":
            return True
        error = payload.get("error")
        return (
            isinstance(error, dict)
            and error.get("code") == "capability_contract_mismatch"
        )
