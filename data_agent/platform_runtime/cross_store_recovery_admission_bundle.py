"""Canonical admission bundle parsing and rotation for recovery workers.

The bundle is deployment evidence produced by an environment-owned recovery
controller.  It contains no provider credentials or row data.  This module
keeps serialization strict and makes file rotation atomic so a worker cannot
observe a half-written bundle during admission refresh.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .cross_store_recovery import CrossStoreRecoveryBinding
from .cross_store_recovery_admission import CrossStoreRecoveryAdmission

ADMISSION_BUNDLE_SCHEMA = "gda.cross_store_recovery_admission_bundle.v1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_REQUIRED_DOCUMENT_KEYS = frozenset(("schema_id", "admissions"))
_REQUIRED_ENTRY_KEYS = frozenset(
    ("binding", "persisted_tenant_ids", "object_version_id_remap_allowed")
)


class ProjectionRecoveryAdmissionBundleError(ValueError):
    """Raised when recovery admission evidence is malformed or unsafe."""


def _binding_from_document(document: Mapping[str, Any]) -> CrossStoreRecoveryBinding:
    if set(document) != {
        "schema",
        "tenant_ids",
        "source_resource_version_ref",
        "source_content_sha256",
        "control_manifest_sha256",
        "object_manifest_sha256",
        "binding_sha256",
    }:
        raise ProjectionRecoveryAdmissionBundleError(
            "controller admission binding fields are not canonical"
        )
    tenant_ids = document.get("tenant_ids")
    if not isinstance(tenant_ids, list):
        raise ProjectionRecoveryAdmissionBundleError(
            "controller admission binding tenant_ids must be a list"
        )
    try:
        binding = CrossStoreRecoveryBinding(
            **{**document, "tenant_ids": tuple(tenant_ids)}
        )
        binding.validate()
    except (TypeError, ValueError) as exc:
        raise ProjectionRecoveryAdmissionBundleError(
            "controller admission binding is invalid"
        ) from exc
    return binding


@dataclass(frozen=True)
class ProjectionRecoveryAdmissionBundle:
    """Strict, deterministic set of plan-bound recovery admissions."""

    admissions: tuple[tuple[str, CrossStoreRecoveryAdmission], ...]

    def __post_init__(self) -> None:
        keys = tuple(plan_sha256 for plan_sha256, _ in self.admissions)
        if not keys:
            raise ProjectionRecoveryAdmissionBundleError(
                "controller admission bundle must contain at least one plan"
            )
        if any(not isinstance(plan_sha256, str) for plan_sha256 in keys):
            raise ProjectionRecoveryAdmissionBundleError(
                "controller admission plan key must be a lowercase SHA-256"
            )
        if keys != tuple(sorted(keys)) or len(set(keys)) != len(keys):
            raise ProjectionRecoveryAdmissionBundleError(
                "controller admission plans must be sorted and unique"
            )
        for plan_sha256, admission in self.admissions:
            if not _SHA256.fullmatch(plan_sha256):
                raise ProjectionRecoveryAdmissionBundleError(
                    "controller admission plan key must be a lowercase SHA-256"
                )
            if not isinstance(admission, CrossStoreRecoveryAdmission):
                raise ProjectionRecoveryAdmissionBundleError(
                    "controller admission entry has an invalid type"
                )
            try:
                admission.binding.validate()
            except (TypeError, ValueError) as exc:
                raise ProjectionRecoveryAdmissionBundleError(
                    "controller admission binding is invalid"
                ) from exc
            if admission.persisted_tenant_ids != admission.binding.tenant_ids:
                raise ProjectionRecoveryAdmissionBundleError(
                    "controller admission tenant copies are incomplete"
                )
            if not isinstance(admission.object_version_id_remap_allowed, bool):
                raise ProjectionRecoveryAdmissionBundleError(
                    "controller admission remap flag is invalid"
                )

    @classmethod
    def from_admissions(
        cls, admissions: Mapping[str, CrossStoreRecoveryAdmission]
    ) -> ProjectionRecoveryAdmissionBundle:
        if not isinstance(admissions, Mapping):
            raise ProjectionRecoveryAdmissionBundleError(
                "controller admissions must be a mapping"
            )
        items = tuple(admissions.items())
        if any(
            not isinstance(plan_sha256, str) or not _SHA256.fullmatch(plan_sha256)
            for plan_sha256, _ in items
        ):
            raise ProjectionRecoveryAdmissionBundleError(
                "controller admission plan key must be a lowercase SHA-256"
            )
        return cls(tuple(sorted(items, key=lambda item: item[0])))

    @classmethod
    def from_dict(cls, document: Mapping[str, Any]) -> ProjectionRecoveryAdmissionBundle:
        if not isinstance(document, Mapping):
            raise ProjectionRecoveryAdmissionBundleError(
                "controller admission bundle must be an object"
            )
        if set(document) != _REQUIRED_DOCUMENT_KEYS:
            raise ProjectionRecoveryAdmissionBundleError(
                "controller admission bundle fields are not canonical"
            )
        if document.get("schema_id") != ADMISSION_BUNDLE_SCHEMA:
            raise ProjectionRecoveryAdmissionBundleError(
                "unsupported controller admission bundle schema"
            )
        entries = document.get("admissions")
        if not isinstance(entries, Mapping):
            raise ProjectionRecoveryAdmissionBundleError(
                "controller admissions must be an object"
            )
        parsed: dict[str, CrossStoreRecoveryAdmission] = {}
        for plan_sha256, entry in entries.items():
            if not isinstance(plan_sha256, str) or not _SHA256.fullmatch(plan_sha256):
                raise ProjectionRecoveryAdmissionBundleError(
                    "controller admission plan key must be a lowercase SHA-256"
                )
            if not isinstance(entry, Mapping) or set(entry) != _REQUIRED_ENTRY_KEYS:
                raise ProjectionRecoveryAdmissionBundleError(
                    "controller admission entry fields are not canonical"
                )
            binding_document = entry.get("binding")
            persisted = entry.get("persisted_tenant_ids")
            remap_allowed = entry.get("object_version_id_remap_allowed")
            if not isinstance(binding_document, Mapping):
                raise ProjectionRecoveryAdmissionBundleError(
                    "controller admission binding is missing"
                )
            if not isinstance(persisted, list) or any(
                not isinstance(item, str) for item in persisted
            ):
                raise ProjectionRecoveryAdmissionBundleError(
                    "controller admission tenant copies are invalid"
                )
            if not isinstance(remap_allowed, bool):
                raise ProjectionRecoveryAdmissionBundleError(
                    "controller admission remap flag is invalid"
                )
            binding = _binding_from_document(binding_document)
            parsed[plan_sha256] = CrossStoreRecoveryAdmission(
                binding=binding,
                persisted_tenant_ids=tuple(persisted),
                object_version_id_remap_allowed=remap_allowed,
            )
        return cls.from_admissions(parsed)

    @classmethod
    def from_json_bytes(
        cls, raw: bytes, *, max_bytes: int = 10_000_000
    ) -> ProjectionRecoveryAdmissionBundle:
        if not isinstance(raw, bytes) or not raw or len(raw) > max_bytes:
            raise ProjectionRecoveryAdmissionBundleError(
                "controller admission bundle exceeds its byte budget"
            )
        try:
            document = json.loads(raw)
        except (TypeError, ValueError) as exc:
            raise ProjectionRecoveryAdmissionBundleError(
                "controller admission bundle is not valid JSON"
            ) from exc
        return cls.from_dict(document)

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_id": ADMISSION_BUNDLE_SCHEMA,
            "admissions": {
                plan_sha256: {
                    "binding": admission.binding.as_dict(),
                    "persisted_tenant_ids": list(admission.persisted_tenant_ids),
                    "object_version_id_remap_allowed": admission.object_version_id_remap_allowed,
                }
                for plan_sha256, admission in self.admissions
            },
        }

    def for_plan(self, plan_sha256: str) -> CrossStoreRecoveryAdmission:
        for candidate, admission in self.admissions:
            if candidate == plan_sha256:
                return admission
        raise ProjectionRecoveryAdmissionBundleError(
            "no controller admission evidence is registered for the sealed plan"
        )

    def json_bytes(self) -> bytes:
        return (
            json.dumps(
                self.as_dict(),
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            + b"\n"
        )


def load_projection_recovery_admission_bundle(
    path: str | Path, *, max_bytes: int = 10_000_000
) -> ProjectionRecoveryAdmissionBundle:
    """Read and strictly validate one server-owned admission bundle file."""

    candidate = Path(path).expanduser().resolve()
    if not candidate.is_file():
        raise ProjectionRecoveryAdmissionBundleError(
            "controller admission bundle is unavailable"
        )
    try:
        raw = candidate.read_bytes()
    except OSError as exc:
        raise ProjectionRecoveryAdmissionBundleError(
            "controller admission bundle could not be read"
        ) from exc
    return ProjectionRecoveryAdmissionBundle.from_json_bytes(raw, max_bytes=max_bytes)


def rotate_projection_recovery_admission_bundle(
    path: str | Path, bundle: ProjectionRecoveryAdmissionBundle
) -> None:
    """Atomically replace a bundle after canonical validation."""

    candidate = Path(path).expanduser().resolve()
    parent = candidate.parent
    if not parent.is_dir():
        raise ProjectionRecoveryAdmissionBundleError(
            "controller admission bundle parent directory is unavailable"
        )
    payload = bundle.json_bytes()
    temporary_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=parent, prefix=f".{candidate.name}.", delete=False
        ) as temporary:
            temporary_path = temporary.name
            temporary.write(payload)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.chmod(temporary_path, 0o440)
        os.replace(temporary_path, candidate)
        temporary_path = None
    except OSError as exc:
        raise ProjectionRecoveryAdmissionBundleError(
            "controller admission bundle rotation failed"
        ) from exc
    finally:
        if temporary_path is not None:
            try:
                os.unlink(temporary_path)
            except OSError:
                pass


__all__ = [
    "ADMISSION_BUNDLE_SCHEMA",
    "ProjectionRecoveryAdmissionBundle",
    "ProjectionRecoveryAdmissionBundleError",
    "load_projection_recovery_admission_bundle",
    "rotate_projection_recovery_admission_bundle",
]
