"""Security helpers for MCP HTTP transports.

This module resolves runtime-only secret and CA references. Callers should
persist reference names, never the values returned by these functions.
"""

from __future__ import annotations

import logging
import os
import re
import threading
from collections import Counter
from collections.abc import Iterable
from pathlib import Path

import httpx


_RUNTIME_SECRET_COUNTS: Counter[str] = Counter()
_RUNTIME_SECRET_LOCK = threading.RLock()


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


def _validate_token(value: str) -> str:
    if not value or "\r" in value or "\n" in value:
        raise _token_missing()
    return value


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
        return _validate_token(value)

    value = os.environ.get(value_env, "").strip() if value_env else ""
    return _validate_token(value)


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


def _normalized_secrets(secrets: Iterable[str]) -> set[str]:
    return {
        secret for secret in secrets
        if isinstance(secret, str) and secret
    }


def register_runtime_secrets(secrets: Iterable[str]) -> None:
    """Register secrets for process-wide third-party diagnostic redaction."""
    with _RUNTIME_SECRET_LOCK:
        _RUNTIME_SECRET_COUNTS.update(_normalized_secrets(secrets))


def unregister_runtime_secrets(secrets: Iterable[str]) -> None:
    """Release one reference for each registered runtime secret."""
    with _RUNTIME_SECRET_LOCK:
        for secret in _normalized_secrets(secrets):
            count = _RUNTIME_SECRET_COUNTS.get(secret, 0)
            if count <= 1:
                _RUNTIME_SECRET_COUNTS.pop(secret, None)
            else:
                _RUNTIME_SECRET_COUNTS[secret] = count - 1


def current_runtime_secrets() -> tuple[str, ...]:
    """Return a snapshot of currently registered runtime secrets."""
    with _RUNTIME_SECRET_LOCK:
        return tuple(_RUNTIME_SECRET_COUNTS)


_BEARER_VALUE_RE = re.compile(r"(?i)(\bBearer\s+)(?!token\b)([^\s,;]+)")
_SIGNED_QUERY_VALUE_RE = re.compile(
    r"(?i)([?&](?:"
    r"token|signature|sig|googleaccessid|expires|"
    r"x-amz-(?:algorithm|credential|date|expires|signedheaders|signature|security-token)|"
    r"x-goog-[^=&#\s\"']+|"
    r"sv|se|sr|sp|spr|st|sip|si|skoid|sktid|ske|sks|skv"
    r")=)([^&#\s\"']*)"
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


class RuntimeSecretRedactionFilter(logging.Filter):
    """Sanitize third-party log records using active MCP runtime secrets."""

    def filter(self, record: logging.LogRecord) -> bool:
        secrets = current_runtime_secrets()
        try:
            try:
                message = record.getMessage()
            except Exception:
                message = f"{record.msg} {record.args}"
            record.msg = redact_mcp_text(message, secrets)
            record.args = ()

            if record.exc_info:
                exception_text = record.exc_text or logging.Formatter().formatException(
                    record.exc_info
                )
                record.exc_text = redact_mcp_text(exception_text, secrets)
            elif record.exc_text:
                record.exc_text = redact_mcp_text(record.exc_text, secrets)

            if record.stack_info:
                record.stack_info = redact_mcp_text(record.stack_info, secrets)
        except Exception:
            record.msg = "MCP diagnostic redaction failed"
            record.args = ()
            record.exc_info = None
            record.exc_text = None
        return True


_RUNTIME_LOG_FILTER = RuntimeSecretRedactionFilter()
_MCP_LOGGER_NAMESPACES = ("google.adk.tools.mcp_tool", "mcp")


def _install_filter_on_handler(handler: logging.Handler) -> None:
    if _RUNTIME_LOG_FILTER not in handler.filters:
        handler.addFilter(_RUNTIME_LOG_FILTER)


def install_runtime_secret_log_filter() -> None:
    """Install the runtime redaction filter on current MCP and root handlers."""
    root = logging.getLogger()
    for handler in root.handlers:
        _install_filter_on_handler(handler)

    logger_names = set(_MCP_LOGGER_NAMESPACES)
    for name, logger_object in logging.Logger.manager.loggerDict.items():
        if isinstance(logger_object, logging.Logger) and any(
            name == namespace or name.startswith(f"{namespace}.")
            for namespace in _MCP_LOGGER_NAMESPACES
        ):
            logger_names.add(name)

    for name in logger_names:
        logger = logging.getLogger(name)
        if _RUNTIME_LOG_FILTER not in logger.filters:
            logger.addFilter(_RUNTIME_LOG_FILTER)
        for handler in logger.handlers:
            _install_filter_on_handler(handler)


class RedactingTextIO:
    """Text stream wrapper that sanitizes MCP stderr writes."""

    def __init__(self, stream):
        self._stream = stream

    def write(self, value: str):
        return self._stream.write(
            redact_mcp_text(value, current_runtime_secrets())
        )

    def writelines(self, lines) -> None:
        self._stream.writelines(
            redact_mcp_text(line, current_runtime_secrets()) for line in lines
        )

    def flush(self):
        return self._stream.flush()

    def __getattr__(self, name):
        return getattr(self._stream, name)
