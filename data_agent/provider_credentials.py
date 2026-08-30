"""Shared provider credential-source resolution with fail-closed semantics."""

from __future__ import annotations

import os
import stat
from collections.abc import Callable, Mapping
from pathlib import Path

CredentialErrorFactory = Callable[[str], Exception]


class ProviderCredentialConfigurationError(RuntimeError):
    """A provider credential source is missing, ambiguous, or unsafe."""


def validate_bearer_token_file(
    path: Path,
    *,
    error_factory: CredentialErrorFactory,
    label: str = "bearer token file",
    require_absolute: bool = True,
) -> Path:
    """Resolve and validate a token path without reading its secret content."""
    candidate = path
    if require_absolute and not candidate.is_absolute():
        raise error_factory(f"{label} must be an absolute path")
    try:
        resolved = candidate.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise error_factory(f"{label} does not exist") from exc
    try:
        mode = resolved.stat().st_mode
    except OSError as exc:
        raise error_factory(f"{label} could not be inspected") from exc
    if not stat.S_ISREG(mode):
        raise error_factory(f"{label} path must be a regular file")
    return resolved


def resolve_bearer_token_file(
    *,
    file_env_name: str,
    source_env_name: str,
    error_factory: CredentialErrorFactory,
    required: bool = False,
    environ: Mapping[str, str] | None = None,
    cwd: Path | None = None,
) -> Path | None:
    """Resolve a provider token from FILE/SOURCE environment variables.

    ``*_FILE`` is the direct runtime mount contract and must be absolute.
    ``*_SOURCE`` is suitable for Compose interpolation and may be relative to
    the process working directory. If both are present they must identify the
    same canonical regular file.
    """
    values = os.environ if environ is None else environ
    file_value = values.get(file_env_name, "").strip()
    source_value = values.get(source_env_name, "").strip()
    if not file_value and not source_value:
        if required:
            raise error_factory(
                f"at least one of {file_env_name} or {source_env_name} is required"
            )
        return None

    file_path = (
        validate_bearer_token_file(
            Path(file_value),
            error_factory=error_factory,
            label=file_env_name,
        )
        if file_value
        else None
    )
    source_path = None
    if source_value:
        source_candidate = Path(source_value)
        if not source_candidate.is_absolute():
            source_candidate = (cwd or Path.cwd()) / source_candidate
        source_path = validate_bearer_token_file(
            source_candidate,
            error_factory=error_factory,
            label=source_env_name,
            require_absolute=False,
        )

    if file_path is not None and source_path is not None and file_path != source_path:
        raise error_factory(
            f"{file_env_name} and {source_env_name} must resolve to the same file"
        )
    return file_path or source_path
