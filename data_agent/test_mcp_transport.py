"""Tests for secure MCP transport configuration helpers."""

import io
import logging
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def empty_runtime_secret_registry():
    from data_agent.mcp_transport import (
        current_runtime_secrets,
        unregister_runtime_secrets,
    )

    while secrets := current_runtime_secrets():
        unregister_runtime_secrets(secrets)
    yield
    while secrets := current_runtime_secrets():
        unregister_runtime_secrets(secrets)


def test_secret_file_takes_precedence_and_strips_whitespace(tmp_path: Path):
    from data_agent.mcp_transport import resolve_secret_reference

    secret_file = tmp_path / "token"
    secret_file.write_text("  file-secret\n", encoding="utf-8")

    with patch.dict(
        os.environ,
        {"TOKEN_VALUE": "environment-secret", "TOKEN_FILE": str(secret_file)},
        clear=True,
    ):
        result = resolve_secret_reference("TOKEN_VALUE", "TOKEN_FILE")

    assert result == "file-secret"


def test_secret_environment_value_is_stripped_when_no_file_is_available():
    from data_agent.mcp_transport import resolve_secret_reference

    with patch.dict(os.environ, {"TOKEN_VALUE": "  environment-secret \n"}, clear=True):
        result = resolve_secret_reference("TOKEN_VALUE", "TOKEN_FILE")

    assert result == "environment-secret"


@pytest.mark.parametrize("file_contents", [None, " \n\t"])
def test_secret_configured_file_must_exist_and_be_non_empty(
    tmp_path: Path, file_contents: str | None
):
    from data_agent.mcp_transport import McpConfigurationError, resolve_secret_reference

    secret_file = tmp_path / "token"
    if file_contents is not None:
        secret_file.write_text(file_contents, encoding="utf-8")

    with patch.dict(
        os.environ,
        {"TOKEN_VALUE": "fallback-must-not-be-used", "TOKEN_FILE": str(secret_file)},
        clear=True,
    ):
        with pytest.raises(McpConfigurationError) as exc_info:
            resolve_secret_reference("TOKEN_VALUE", "TOKEN_FILE")

    assert exc_info.value.code == "ARCPY_MCP_TOKEN_MISSING"
    assert "fallback-must-not-be-used" not in str(exc_info.value)
    assert str(secret_file) not in str(exc_info.value)


def test_secret_requires_at_least_one_available_source():
    from data_agent.mcp_transport import McpConfigurationError, resolve_secret_reference

    with patch.dict(os.environ, {}, clear=True):
        with pytest.raises(McpConfigurationError) as exc_info:
            resolve_secret_reference("TOKEN_VALUE", "TOKEN_FILE")

    assert exc_info.value.code == "ARCPY_MCP_TOKEN_MISSING"
    assert str(exc_info.value) == "MCP credential is not available"


@pytest.mark.parametrize("invalid_token", ["valid-prefix\rinjected", "valid-prefix\ninjected"])
def test_secret_environment_rejects_embedded_line_breaks(invalid_token: str):
    from data_agent.mcp_transport import McpConfigurationError, resolve_secret_reference

    with patch.dict(os.environ, {"TOKEN_VALUE": invalid_token}, clear=True):
        with pytest.raises(McpConfigurationError) as exc_info:
            resolve_secret_reference("TOKEN_VALUE", "TOKEN_FILE")

    assert exc_info.value.code == "ARCPY_MCP_TOKEN_MISSING"
    assert invalid_token not in str(exc_info.value)


def test_secret_file_rejects_embedded_line_breaks(tmp_path: Path):
    from data_agent.mcp_transport import McpConfigurationError, resolve_secret_reference

    secret_file = tmp_path / "token"
    secret_file.write_text("valid-prefix\ninjected", encoding="utf-8")

    with patch.dict(os.environ, {"TOKEN_FILE": str(secret_file)}, clear=True):
        with pytest.raises(McpConfigurationError) as exc_info:
            resolve_secret_reference("TOKEN_VALUE", "TOKEN_FILE")

    assert exc_info.value.code == "ARCPY_MCP_TOKEN_MISSING"
    assert "valid-prefix" not in str(exc_info.value)


def test_ca_bundle_resolves_existing_regular_file(tmp_path: Path):
    from data_agent.mcp_transport import resolve_ca_bundle

    ca_file = tmp_path / "private-ca.pem"
    ca_file.write_text(
        "-----BEGIN CERTIFICATE-----\ncertificate\n-----END CERTIFICATE-----\n",
        encoding="utf-8",
    )

    with patch.dict(os.environ, {"CA_FILE": str(ca_file)}, clear=True):
        assert resolve_ca_bundle("CA_FILE") == str(ca_file)


@pytest.mark.parametrize("environment_value", [None, "", "missing.pem"])
def test_ca_bundle_rejects_missing_or_empty_reference(environment_value: str | None):
    from data_agent.mcp_transport import McpConfigurationError, resolve_ca_bundle

    environment = {} if environment_value is None else {"CA_FILE": environment_value}
    with patch.dict(os.environ, environment, clear=True):
        with pytest.raises(McpConfigurationError) as exc_info:
            resolve_ca_bundle("CA_FILE")

    assert exc_info.value.code == "ARCPY_MCP_CA_MISSING"
    assert "missing.pem" not in str(exc_info.value)


def test_ca_bundle_rejects_private_key_material(tmp_path: Path):
    from data_agent.mcp_transport import McpConfigurationError, resolve_ca_bundle

    key_file = tmp_path / "not-a-ca.pem"
    key_file.write_text(
        "-----BEGIN PRIVATE KEY-----\nprivate material\n-----END PRIVATE KEY-----\n",
        encoding="utf-8",
    )

    with patch.dict(os.environ, {"CA_FILE": str(key_file)}, clear=True):
        with pytest.raises(McpConfigurationError) as exc_info:
            resolve_ca_bundle("CA_FILE")

    assert exc_info.value.code == "ARCPY_MCP_CA_MISSING"
    assert str(key_file) not in str(exc_info.value)


def test_httpx_client_factory_forwards_adk_arguments_and_private_ca():
    from data_agent.mcp_transport import build_httpx_client_factory

    client = MagicMock()
    headers = {"Authorization": "Bearer runtime-secret"}
    timeout = MagicMock(name="timeout")
    auth = MagicMock(name="auth")

    with patch("httpx.AsyncClient", return_value=client) as async_client:
        factory = build_httpx_client_factory("/runtime/private-ca.pem")
        result = factory(headers=headers, timeout=timeout, auth=auth)

    assert result is client
    async_client.assert_called_once_with(
        headers=headers,
        timeout=timeout,
        auth=auth,
        verify="/runtime/private-ca.pem",
        follow_redirects=True,
    )


def test_redaction_removes_exact_secrets_without_mutating_inputs():
    from data_agent.mcp_transport import redact_mcp_text

    value = "connection failed for exact-secret while contacting host"
    secrets = ["exact-secret"]

    result = redact_mcp_text(value, secrets)

    assert result == "connection failed for [REDACTED] while contacting host"
    assert value == "connection failed for exact-secret while contacting host"
    assert secrets == ["exact-secret"]


@pytest.mark.parametrize("bearer_value", ["header-secret", "token", "token-abc"])
def test_redaction_removes_bearer_authorization_value(bearer_value: str):
    from data_agent.mcp_transport import redact_mcp_text

    result = redact_mcp_text(
        f"request failed: Authorization: Bearer {bearer_value}; retry disabled"
    )

    assert result == "request failed: Authorization: Bearer [REDACTED]; retry disabled"
    assert bearer_value not in result


def test_redaction_preserves_non_secret_credential_diagnostic():
    from data_agent.mcp_transport import redact_mcp_text

    message = "MCP credential is not available"

    assert redact_mcp_text(message) == message


def test_redaction_removes_signed_query_values_and_preserves_other_context():
    from data_agent.mcp_transport import redact_mcp_text

    result = redact_mcp_text(
        "GET https://host/mcp?layer=roads&token=abc123&signature=long-value&sig=short#frag failed"
    )

    assert result == (
        "GET https://host/mcp?layer=roads&token=[REDACTED]&signature=[REDACTED]"
        "&sig=[REDACTED]#frag failed"
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (
            "GET https://s3.test/bucket/key?partNumber=1&X-Amz-Algorithm=AWS4-HMAC-SHA256"
            "&X-Amz-Credential=AKIA%2Fscope&X-Amz-Date=20260711T000000Z&X-Amz-Expires=900"
            "&X-Amz-SignedHeaders=host&X-Amz-Signature=deadbeef"
            "&X-Amz-Security-Token=session-token failed",
            "GET https://s3.test/bucket/key?partNumber=1&X-Amz-Algorithm=[REDACTED]"
            "&X-Amz-Credential=[REDACTED]&X-Amz-Date=[REDACTED]&X-Amz-Expires=[REDACTED]"
            "&X-Amz-SignedHeaders=[REDACTED]&X-Amz-Signature=[REDACTED]"
            "&X-Amz-Security-Token=[REDACTED] failed",
        ),
        (
            "https://storage.googleapis.test/object?alt=media&GoogleAccessId=svc%40project.iam"
            "&Expires=1780000000&Signature=gcs-v2-signature&x-goog-algorithm=GOOG4-RSA-SHA256"
            "&X-Goog-Credential=service%2Fscope&X-Goog-Date=20260711T000000Z"
            "&X-Goog-Expires=600&X-Goog-SignedHeaders=host&X-Goog-Signature=feedface",
            "https://storage.googleapis.test/object?alt=media&GoogleAccessId=[REDACTED]"
            "&Expires=[REDACTED]&Signature=[REDACTED]&x-goog-algorithm=[REDACTED]"
            "&X-Goog-Credential=[REDACTED]&X-Goog-Date=[REDACTED]"
            "&X-Goog-Expires=[REDACTED]&X-Goog-SignedHeaders=[REDACTED]"
            "&X-Goog-Signature=[REDACTED]",
        ),
        (
            "https://account.blob.test/container/item?comp=metadata&sv=2025-05-05&se=expiry"
            "&sr=b&sp=r&spr=https&st=start&SIG=azure-signature&sip=10.0.0.1"
            "&si=policy&skoid=object&sktid=tenant&ske=key-expiry&sks=b&skv=version",
            "https://account.blob.test/container/item?comp=metadata&sv=[REDACTED]&se=[REDACTED]"
            "&sr=[REDACTED]&sp=[REDACTED]&spr=[REDACTED]&st=[REDACTED]"
            "&SIG=[REDACTED]&sip=[REDACTED]&si=[REDACTED]&skoid=[REDACTED]"
            "&sktid=[REDACTED]&ske=[REDACTED]&sks=[REDACTED]&skv=[REDACTED]",
        ),
    ],
)
def test_redaction_removes_cloud_signed_url_values(value: str, expected: str):
    from data_agent.mcp_transport import redact_mcp_text

    assert redact_mcp_text(value) == expected


def test_runtime_secret_registry_uses_reference_counts(empty_runtime_secret_registry):
    from data_agent.mcp_transport import (
        current_runtime_secrets,
        register_runtime_secrets,
        unregister_runtime_secrets,
    )

    register_runtime_secrets(["shared-token", "shared-token"])
    register_runtime_secrets(["shared-token", "other-token"])
    assert set(current_runtime_secrets()) == {"shared-token", "other-token"}

    unregister_runtime_secrets(["shared-token"])
    assert set(current_runtime_secrets()) == {"shared-token", "other-token"}

    unregister_runtime_secrets(["shared-token", "other-token"])
    assert current_runtime_secrets() == ()


@pytest.mark.parametrize(
    "logger_name",
    [
        "mcp.client.security_test",
        "google_adk.google.adk.tools.mcp_tool.mcp_session_manager",
    ],
)
def test_runtime_log_filter_redacts_third_party_message_and_exception(
    empty_runtime_secret_registry, logger_name,
):
    from data_agent.mcp_transport import (
        install_runtime_secret_log_filter,
        register_runtime_secrets,
    )

    token = "third-party-exact-token"
    output = io.StringIO()
    handler = logging.StreamHandler(output)
    logger = logging.getLogger(logger_name)
    old_handlers = list(logger.handlers)
    old_propagate = logger.propagate
    old_level = logger.level
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(logging.INFO)

    try:
        register_runtime_secrets([token])
        install_runtime_secret_log_filter()
        try:
            raise RuntimeError(f"transport exception exposed {token}")
        except RuntimeError:
            logger.exception("third-party request failed for %s", token)
    finally:
        logger.handlers = old_handlers
        logger.propagate = old_propagate
        logger.setLevel(old_level)

    logged = output.getvalue()
    assert token not in logged
    assert "[REDACTED]" in logged
    assert "third-party request failed" in logged
    assert "transport exception exposed" in logged


@pytest.mark.parametrize(
    "logger_name",
    [
        "mcp.client.security_test",
        "google_adk.google.adk.tools.mcp_tool.mcp_session_manager",
    ],
)
def test_runtime_log_filter_redacts_json_formatter_exception(
    empty_runtime_secret_registry, logger_name,
):
    from data_agent.mcp_transport import (
        RuntimeSecretRedactionFilter,
        install_runtime_secret_log_filter,
        register_runtime_secrets,
    )
    from data_agent.observability import JsonFormatter

    token = "json-formatter-exact-token"
    output = io.StringIO()
    handler = logging.StreamHandler(output)
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger(logger_name)
    old_handlers = list(logger.handlers)
    old_propagate = logger.propagate
    old_level = logger.level
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(logging.INFO)

    try:
        register_runtime_secrets([token])
        install_runtime_secret_log_filter()
        install_runtime_secret_log_filter()
        self_filters = [
            item for item in handler.filters
            if isinstance(item, RuntimeSecretRedactionFilter)
        ]
        assert len(self_filters) == 1
        try:
            raise RuntimeError(f"formatter retained useful context {token}")
        except RuntimeError:
            logger.exception("JSON request failed for %s", token)
    finally:
        logger.handlers = old_handlers
        logger.propagate = old_propagate
        logger.setLevel(old_level)

    formatted = output.getvalue()
    assert token not in formatted
    assert "JSON request failed" in formatted
    assert "formatter retained useful context" in formatted


def test_redacting_text_io_sanitizes_runtime_secret_writes(
    empty_runtime_secret_registry,
):
    from data_agent.mcp_transport import RedactingTextIO, register_runtime_secrets

    token = "stderr-exact-token"
    output = io.StringIO()
    register_runtime_secrets([token])
    stream = RedactingTextIO(output)

    written = stream.write(f"MCP stderr exposed {token}\n")
    stream.flush()

    assert written == len("MCP stderr exposed [REDACTED]\n")
    assert output.getvalue() == "MCP stderr exposed [REDACTED]\n"
