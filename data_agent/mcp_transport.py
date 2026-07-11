"""Security helpers for MCP HTTP transports.

This module resolves runtime-only secret and CA references. Callers should
persist reference names, never the values returned by these functions.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterable
from pathlib import Path

import httpx


class McpConfigurationError(RuntimeError):
    """An MCP runtime configuration error with a stable machine-readable code."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _token_missing() -> McpConfigurationError:
    return McpConfigurationError(
        "ARCPY_MCP_TOKEN_MISSING", "MCP bearer token is not available"
    )


def _ca_missing() -> McpConfigurationError:
    return McpConfigurationError(
        "ARCPY_MCP_CA_MISSING", "MCP CA bundle is not available"
    )


def resolve_secret_reference(value_env: str, file_env: str) -> str:
    """Resolve a secret from environment or an environment-referenced file.

    A non-empty file path supplied by ``file_env`` takes precedence. Invalid
    configured files fail closed instead of falling back to the value source.
    """

    file_path = os.environ.get(file_env, "").strip() if file_env else ""
    if file_path:
        try:
            path = Path(file_path)
            if not path.is_file():
                raise _token_missing()
            value = path.read_text(encoding="utf-8").strip()
        except McpConfigurationError:
            raise
        except (OSError, UnicodeError):
            raise _token_missing() from None
        if not value:
            raise _token_missing()
        return value

    value = os.environ.get(value_env, "").strip() if value_env else ""
    if not value:
        raise _token_missing()
    return value


def resolve_ca_bundle(env_name: str) -> str:
    """Resolve and validate a private CA bundle path from the environment."""

    file_path = os.environ.get(env_name, "").strip() if env_name else ""
    if not file_path:
        raise _ca_missing()

    try:
        path = Path(file_path)
        if not path.is_file():
            raise _ca_missing()
        contents = path.read_bytes()
    except McpConfigurationError:
        raise
    except OSError:
        raise _ca_missing() from None

    if b"PRIVATE KEY" in contents:
        raise _ca_missing()
    return file_path


def build_httpx_client_factory(ca_bundle: str):
    """Build an ADK-compatible HTTP client factory using a private CA bundle."""

    def create_client(headers=None, timeout=None, auth=None):
        return httpx.AsyncClient(
            headers=headers,
            timeout=timeout,
            auth=auth,
            verify=ca_bundle,
            follow_redirects=True,
        )

    return create_client


_BEARER_VALUE_RE = re.compile(r"(?i)(\bBearer\s+)([^\s,;]+)")
_SIGNED_QUERY_VALUE_RE = re.compile(
    r"(?i)([?&](?:token|signature|sig)=)([^&#\s\"']*)"
)


def redact_mcp_text(value: str, secrets: Iterable[str] = ()) -> str:
    """Return MCP diagnostic text with credentials and signatures removed."""

    redacted = str(value)
    exact_secrets = sorted(
        {secret for secret in secrets if isinstance(secret, str) and secret},
        key=len,
        reverse=True,
    )
    for secret in exact_secrets:
        redacted = redacted.replace(secret, "[REDACTED]")

    redacted = _BEARER_VALUE_RE.sub(r"\1[REDACTED]", redacted)
    return _SIGNED_QUERY_VALUE_RE.sub(r"\1[REDACTED]", redacted)

