"""Checksum-verified current artifact lookup for the Abu Dhabi query routes."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_ROOT = ROOT / "docs/customer/abu_dhabi_liveability_site_validation"
# The filename is intentionally date-free.  Versioned manifests remain
# immutable release evidence, while the alias is the only runtime pointer and
# is atomically replaced by the publisher after all artifact checksums exist.
_MANIFEST_BY_SOURCE = {
    "liveability": ARTIFACT_ROOT / "abu_dhabi_current_artifact_bundle.json",
    "makani": ARTIFACT_ROOT / "makani_current_artifact_bundle.json",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_manifest(source_key: str) -> dict[str, Any]:
    try:
        path = _MANIFEST_BY_SOURCE[source_key]
    except KeyError as exc:
        raise ValueError(f"unknown_abu_dhabi_source:{source_key}") from exc
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema") != "gda.abu-dhabi-artifact-bundle.v1":
        raise ValueError("abu_dhabi_artifact_bundle_schema_invalid")
    if payload.get("status") != "current_source_bound":
        raise ValueError("abu_dhabi_artifact_bundle_not_current")
    return payload


def current_artifact_manifest(source_key: str) -> dict[str, Any]:
    """Return the immutable source-bound manifest for a product source."""

    return _load_manifest(source_key)


def registered_source_keys() -> tuple[str, ...]:
    """Return source scopes registered in the central artifact registry."""
    return tuple(sorted(_MANIFEST_BY_SOURCE))


def current_artifact_path(source_key: str, role: str) -> Path:
    """Resolve and checksum-verify one artifact from the current bundle."""

    manifest = _load_manifest(source_key)
    descriptor = (manifest.get("artifacts") or {}).get(role) or {}
    relative = Path(str(descriptor.get("path") or ""))
    expected = str(descriptor.get("sha256") or "")
    if relative.is_absolute() or ".." in relative.parts or len(expected) != 64:
        raise ValueError(f"abu_dhabi_artifact_descriptor_invalid:{source_key}:{role}")
    path = (ROOT / relative).resolve()
    try:
        path.relative_to(ROOT.resolve())
    except ValueError as exc:
        raise ValueError("abu_dhabi_artifact_path_outside_repository") from exc
    if not path.is_file() or _sha256(path) != expected:
        raise ValueError(f"abu_dhabi_artifact_checksum_mismatch:{source_key}:{role}")
    return path


__all__ = [
    "ARTIFACT_ROOT",
    "ROOT",
    "current_artifact_manifest",
    "current_artifact_path",
    "registered_source_keys",
]
