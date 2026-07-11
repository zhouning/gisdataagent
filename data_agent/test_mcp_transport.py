"""Tests for secure MCP transport configuration helpers."""

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


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
    assert str(exc_info.value) == "MCP bearer token is not available"


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


def test_redaction_removes_bearer_authorization_value():
    from data_agent.mcp_transport import redact_mcp_text

    result = redact_mcp_text(
        "request failed: Authorization: Bearer header-secret; retry disabled"
    )

    assert result == "request failed: Authorization: Bearer [REDACTED]; retry disabled"
    assert "header-secret" not in result


def test_redaction_removes_signed_query_values_and_preserves_other_context():
    from data_agent.mcp_transport import redact_mcp_text

    result = redact_mcp_text(
        "GET https://host/mcp?layer=roads&token=abc123&signature=long-value&sig=short#frag failed"
    )

    assert result == (
        "GET https://host/mcp?layer=roads&token=[REDACTED]&signature=[REDACTED]"
        "&sig=[REDACTED]#frag failed"
    )

