"""Immutable Landing execution for explicitly public/open source bytes."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated
from urllib.parse import urlsplit
from uuid import NAMESPACE_URL, uuid4, uuid5

from pydantic import Field, field_validator, model_validator
from sqlalchemy import create_engine

from .platform_contracts import (
    Artifact,
    FrozenContract,
    NonEmptyText,
    Resource,
    ResourceVersion,
    Sha256,
    ShortName,
    TenantId,
    canonical_json_bytes,
    canonical_json_fingerprint,
)
from .platform_gateway import LandingRegistration, PlatformGateway

LANDING_SCHEMA = "gda.public_source_landing.v1"
_DATASET_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,79}$")
_SAFE_SUFFIX_RE = re.compile(r"^\.[a-z0-9]{1,12}$")

DatasetId = Annotated[
    str,
    Field(min_length=1, max_length=80, pattern=r"^[a-z0-9][a-z0-9._-]{0,79}$"),
]


class PublicSourceLandingError(RuntimeError):
    """Public source bytes cannot be staged or verified safely."""


class PublicSourceLandingRequest(FrozenContract):
    schema_id = "public_source_landing_request"

    tenant_id: TenantId
    dataset_id: DatasetId
    source_uri: NonEmptyText
    license_id: ShortName
    owner_ref: NonEmptyText
    expected_sha256: Sha256
    media_type: NonEmptyText
    created_by: NonEmptyText
    created_at: datetime

    @field_validator("source_uri")
    @classmethod
    def _stable_public_source_uri(cls, value: str) -> str:
        parts = urlsplit(value)
        if parts.scheme != "https" or not parts.netloc:
            raise ValueError("public source URI must use HTTPS")
        if parts.username or parts.password or parts.query or parts.fragment:
            raise ValueError("public source URI must be stable and credential-free")
        return value

    @field_validator("created_by")
    @classmethod
    def _controlled_actor(cls, value: str) -> str:
        if not value.startswith(("human:", "workload:")):
            raise ValueError("created_by must use a human or workload identity")
        return value

    @field_validator("created_at")
    @classmethod
    def _utc_created_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must include a timezone")
        return value.astimezone(UTC)


class PublicSourceLandingResult(FrozenContract):
    schema_id = "public_source_landing_result"

    registration: LandingRegistration
    payload_path: str
    manifest_path: str
    payload_created: bool
    manifest_created: bool
    manifest_sha256: Sha256
    ledger_created: bool | None = None

    @model_validator(mode="after")
    def _consistent_paths(self) -> PublicSourceLandingResult:
        payload = Path(self.payload_path)
        manifest = Path(self.manifest_path)
        if not payload.is_absolute() or not manifest.is_absolute():
            raise ValueError("landing result paths must be absolute")
        if payload.parent != manifest.parent:
            raise ValueError("landing payload and manifest must share one version root")
        return self


def _safe_suffix(source_path: Path) -> str:
    suffix = source_path.suffix.lower()
    return suffix if _SAFE_SUFFIX_RE.fullmatch(suffix) else ".bin"


def _sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _copy_to_staging(source_path: Path, staging_path: Path) -> tuple[str, int]:
    if source_path.is_symlink():
        raise PublicSourceLandingError("landing source cannot be a symbolic link")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        source_fd = os.open(source_path, flags)
    except OSError as exc:
        raise PublicSourceLandingError("landing source is not readable") from exc
    try:
        source_stat = os.fstat(source_fd)
        if not stat.S_ISREG(source_stat.st_mode):
            raise PublicSourceLandingError("landing source must be a regular file")
        digest = hashlib.sha256()
        size = 0
        with os.fdopen(source_fd, "rb", closefd=False) as source, staging_path.open(
            "xb"
        ) as target:
            os.chmod(staging_path, 0o600)
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
                size += len(chunk)
                target.write(chunk)
            target.flush()
            os.fsync(target.fileno())
        return digest.hexdigest(), size
    finally:
        os.close(source_fd)


def _verify_payload(path: Path, expected_sha256: str, expected_size: int) -> None:
    if path.is_symlink() or not path.is_file():
        raise PublicSourceLandingError("landing payload is not an immutable regular file")
    actual_sha256, actual_size = _sha256_file(path)
    if actual_sha256 != expected_sha256 or actual_size != expected_size:
        raise PublicSourceLandingError("existing landing payload does not match its key")


def _install_staged_payload(
    staging_path: Path,
    destination: Path,
    *,
    expected_sha256: str,
    expected_size: int,
) -> bool:
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
    try:
        os.link(staging_path, destination)
        os.chmod(destination, 0o440)
        return True
    except FileExistsError:
        _verify_payload(destination, expected_sha256, expected_size)
        return False


def _install_immutable_bytes(destination: Path, payload: bytes) -> bool:
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
    temporary = destination.parent / f".{destination.name}.{uuid4().hex}.part"
    try:
        with temporary.open("xb") as handle:
            os.chmod(temporary, 0o600)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, destination)
            os.chmod(destination, 0o440)
            return True
        except FileExistsError:
            if destination.is_symlink() or destination.read_bytes() != payload:
                raise PublicSourceLandingError(
                    "existing landing manifest does not match the staged object"
                ) from None
            return False
    finally:
        temporary.unlink(missing_ok=True)


def _build_registration(
    request: PublicSourceLandingRequest,
    *,
    payload_path: Path,
    landing_root: Path,
    content_sha256: str,
    size_bytes: int,
) -> tuple[LandingRegistration, str, bytes]:
    resource_urn = f"gda://{request.tenant_id}/dataset/{request.dataset_id}"
    authority_locator = f"{request.tenant_id}/{request.dataset_id}"
    object_key = payload_path.relative_to(landing_root).as_posix()
    version_id = uuid5(NAMESPACE_URL, f"{resource_urn}@sha256:{content_sha256}")
    artifact_id = uuid5(
        NAMESPACE_URL,
        f"gda-landing-artifact:{resource_urn}@sha256:{content_sha256}",
    )
    manifest = {
        "schema": LANDING_SCHEMA,
        "admission_class": "public_open",
        "tenant_id": request.tenant_id,
        "dataset_id": request.dataset_id,
        "resource_urn": resource_urn,
        "resource_version_id": str(version_id),
        "artifact_id": str(artifact_id),
        "authority_locator": authority_locator,
        "object_key": object_key,
        "source_uri": request.source_uri,
        "license_id": request.license_id,
        "media_type": request.media_type,
        "content_sha256": content_sha256,
        "size_bytes": size_bytes,
        "created_by": request.created_by,
        "created_at": request.created_at.isoformat().replace("+00:00", "Z"),
        "content_admission_authorized": True,
        "production_ready": False,
    }
    manifest_sha256 = canonical_json_fingerprint(manifest)
    resource = Resource(
        tenant_id=request.tenant_id,
        resource_urn=resource_urn,
        resource_kind="dataset",
        authority_system="gda_landing",
        authority_locator=authority_locator,
        owner_ref=request.owner_ref,
        governance_ref={
            "admission_class": "public_open",
            "source_uri": request.source_uri,
            "license_id": request.license_id,
        },
    )
    version = ResourceVersion(
        tenant_id=request.tenant_id,
        resource_urn=resource_urn,
        resource_version_id=version_id,
        version_key=f"sha256:{content_sha256[:16]}",
        content_sha256=content_sha256,
        authority_version_ref={
            "authority_system": "gda_landing",
            "object_key": object_key,
            "manifest_sha256": manifest_sha256,
        },
        created_by=request.created_by,
        created_at=request.created_at,
    )
    artifact = Artifact(
        tenant_id=request.tenant_id,
        artifact_id=artifact_id,
        artifact_key=f"landing:{request.dataset_id}:{content_sha256[:12]}",
        artifact_role="input",
        storage_uri=payload_path.as_uri(),
        media_type=request.media_type,
        content_sha256=content_sha256,
        size_bytes=size_bytes,
        resource_version_id=version_id,
        manifest=manifest,
        created_by=request.created_by,
        created_at=request.created_at,
    )
    registration = LandingRegistration(
        resource=resource,
        resource_version=version,
        artifact=artifact,
    )
    manifest_document = {
        "manifest": manifest,
        "manifest_sha256": manifest_sha256,
    }
    return registration, manifest_sha256, canonical_json_bytes(manifest_document) + b"\n"


def stage_public_source(
    request: PublicSourceLandingRequest,
    *,
    source_path: Path,
    landing_root: Path,
) -> PublicSourceLandingResult:
    """Copy verified public bytes into a content-addressed immutable Landing."""
    if not _DATASET_ID_RE.fullmatch(request.dataset_id):
        raise PublicSourceLandingError("dataset_id is not canonical")
    if source_path.is_symlink():
        raise PublicSourceLandingError("landing source cannot be a symbolic link")
    source_path = source_path.resolve(strict=True)
    if landing_root.is_symlink():
        raise PublicSourceLandingError("landing root cannot be a symbolic link")
    landing_root = landing_root.resolve()
    landing_root.mkdir(parents=True, exist_ok=True, mode=0o750)
    staging_root = landing_root / ".staging"
    staging_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    staging_path = staging_root / f"{uuid4().hex}.part"
    try:
        content_sha256, size_bytes = _copy_to_staging(source_path, staging_path)
        if content_sha256 != request.expected_sha256:
            raise PublicSourceLandingError(
                "source SHA-256 does not match the approved public-source input"
            )
        version_root = (
            landing_root
            / request.tenant_id
            / request.dataset_id
            / "sha256"
            / content_sha256
        )
        payload_path = version_root / f"payload{_safe_suffix(source_path)}"
        payload_created = _install_staged_payload(
            staging_path,
            payload_path,
            expected_sha256=content_sha256,
            expected_size=size_bytes,
        )
        registration, manifest_sha256, manifest_bytes = _build_registration(
            request,
            payload_path=payload_path,
            landing_root=landing_root,
            content_sha256=content_sha256,
            size_bytes=size_bytes,
        )
        manifest_path = version_root / "manifest.json"
        manifest_created = _install_immutable_bytes(manifest_path, manifest_bytes)
        return PublicSourceLandingResult(
            registration=registration,
            payload_path=str(payload_path),
            manifest_path=str(manifest_path),
            payload_created=payload_created,
            manifest_created=manifest_created,
            manifest_sha256=manifest_sha256,
        )
    finally:
        staging_path.unlink(missing_ok=True)


def verify_public_source_landing(result: PublicSourceLandingResult) -> None:
    """Re-read Landing bytes and prove their ledger bindings still match."""
    registration = result.registration
    artifact = registration.artifact
    payload_path = Path(result.payload_path)
    manifest_path = Path(result.manifest_path)
    _verify_payload(payload_path, artifact.content_sha256, artifact.size_bytes)
    try:
        document = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PublicSourceLandingError("landing manifest is unreadable") from exc
    manifest = document.get("manifest")
    if manifest != artifact.manifest:
        raise PublicSourceLandingError("landing manifest does not bind the Artifact")
    if document.get("manifest_sha256") != result.manifest_sha256:
        raise PublicSourceLandingError("landing manifest fingerprint does not match")
    if canonical_json_fingerprint(manifest) != result.manifest_sha256:
        raise PublicSourceLandingError("landing manifest content was modified")
    if payload_path.as_uri() != artifact.storage_uri:
        raise PublicSourceLandingError("landing payload path does not bind the Artifact URI")


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError("timestamp must include a timezone")
    return parsed.astimezone(UTC)


def _write_result(result: PublicSourceLandingResult, output: Path | None) -> None:
    rendered = json.dumps(
        result.model_dump(mode="json"),
        ensure_ascii=True,
        indent=2,
        sort_keys=True,
    )
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    stage = subparsers.add_parser("stage", help="stage and optionally register bytes")
    stage.add_argument("--source-file", type=Path, required=True)
    stage.add_argument("--landing-root", type=Path, required=True)
    stage.add_argument("--tenant-id", required=True)
    stage.add_argument("--dataset-id", required=True)
    stage.add_argument("--source-uri", required=True)
    stage.add_argument("--license-id", required=True)
    stage.add_argument("--owner-ref", required=True)
    stage.add_argument("--expected-sha256", required=True)
    stage.add_argument("--media-type", required=True)
    stage.add_argument("--created-by", required=True)
    stage.add_argument("--created-at", type=_parse_time, required=True)
    stage.add_argument("--database-url")
    stage.add_argument("--output", type=Path)
    verify = subparsers.add_parser("verify", help="verify a staged Landing result")
    verify.add_argument("--input", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "stage":
        request = PublicSourceLandingRequest(
            tenant_id=args.tenant_id,
            dataset_id=args.dataset_id,
            source_uri=args.source_uri,
            license_id=args.license_id,
            owner_ref=args.owner_ref,
            expected_sha256=args.expected_sha256,
            media_type=args.media_type,
            created_by=args.created_by,
            created_at=args.created_at,
        )
        result = stage_public_source(
            request,
            source_path=args.source_file,
            landing_root=args.landing_root,
        )
        if args.database_url:
            gateway = PlatformGateway(create_engine(args.database_url))
            ledger = gateway.register_landing(result.registration)
            result = result.model_copy(update={"ledger_created": ledger.created})
        verify_public_source_landing(result)
        _write_result(result, args.output)
        return 0
    result = PublicSourceLandingResult.model_validate_json(
        args.input.read_text(encoding="utf-8")
    )
    verify_public_source_landing(result)
    print(json.dumps({"valid": True, "manifest_sha256": result.manifest_sha256}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
