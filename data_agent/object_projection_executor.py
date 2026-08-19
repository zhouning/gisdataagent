"""Plan-bound S3 object projection for the sealed Chongqing customer bundle."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .cross_store_projection_consistency import (
    ProjectionConsistencyError,
    ProjectionEngine,
    ProjectionRepairPlan,
    ProjectionTargetObservation,
)
from .platform_contracts import (
    NonEmptyText,
    Sha256,
    TenantId,
    canonical_json_fingerprint,
)

_BUNDLE_ID = "natural-resource-ontology-customer-demo-v1"
_BUNDLE_VERSION = "1.0.0"
_ONTOLOGY_KEY = "natural-resource-one-map"
_ONTOLOGY_VERSION = "2.3.0"
_ONTOLOGY_PACKAGE_ID = "natural-resource-one-map:2.3.0:587915868b1221af"
_ONTOLOGY_PACKAGE_SHA256 = "587915868b1221af2315508ede7bf7babced063cba8b261de2f10afa23841019"
_MISSING_CODES = frozenset({"404", "NoSuchKey", "NotFound", "NoSuchVersion"})


class ObjectProjectionExecutionError(ProjectionConsistencyError):
    """A plan-bound object-store action could not be safely completed."""


class ObjectProjectionConfigurationError(ObjectProjectionExecutionError):
    """The registered object target, artifact, or S3 channel is unusable."""


class ObjectProjectionValidationError(ObjectProjectionExecutionError):
    """The plan, sealed artifact, or observed object is invalid."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ObjectProjectionTarget(_FrozenModel):
    """Explicit versioned S3 object bound to one sealed customer artifact."""

    schema_id: ClassVar[str] = "gda.object-projection-target.v1"
    tenant_id: TenantId
    projection_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$")
    target_ref: NonEmptyText
    endpoint_url: NonEmptyText
    region_name: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9-]{0,62}$")
    bucket: str = Field(pattern=r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")
    key: str = Field(min_length=1, max_length=1024)
    bundle_manifest_path: NonEmptyText
    bundle_manifest_sha256: Sha256
    bundle_id: str = Field(pattern=r"^[a-z][a-z0-9-]{2,127}$")
    bundle_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    artifact_path: NonEmptyText
    artifact_name: NonEmptyText
    artifact_sha256: Sha256
    artifact_size_bytes: int = Field(ge=1, le=500_000_000)
    media_type: str = Field(pattern=r"^[a-z0-9][a-z0-9.+-]*/[a-z0-9][a-z0-9.+-]*$")
    ontology_package_id: NonEmptyText
    ontology_package_content_sha256: Sha256

    @model_validator(mode="after")
    def _registered_identity(self) -> ObjectProjectionTarget:
        if (
            self.bundle_id != _BUNDLE_ID
            or self.bundle_version != _BUNDLE_VERSION
            or self.ontology_package_id != _ONTOLOGY_PACKAGE_ID
            or self.ontology_package_content_sha256 != _ONTOLOGY_PACKAGE_SHA256
        ):
            raise ValueError(
                "object projections are restricted to the sealed Chongqing customer bundle"
            )
        target = urlsplit(self.target_ref)
        if (
            target.scheme != "s3"
            or target.netloc != self.bucket
            or target.path.lstrip("/") != self.key
            or target.username
            or target.password
            or target.query
            or target.fragment
        ):
            raise ValueError("target_ref must exactly match the registered S3 bucket and key")
        endpoint = urlsplit(self.endpoint_url)
        if (
            endpoint.scheme not in {"http", "https"}
            or not endpoint.netloc
            or endpoint.username
            or endpoint.password
            or endpoint.query
            or endpoint.fragment
        ):
            raise ValueError("endpoint_url must be an absolute credential-free HTTP URL")
        components = self.key.split("/")
        if (
            self.key.startswith("/")
            or self.key.endswith("/")
            or any(component in {"", ".", ".."} for component in components)
        ):
            raise ValueError("registered object key must be a normalized object path")
        artifact = Path(self.artifact_path)
        if artifact.name != self.artifact_name:
            raise ValueError("artifact_name must match artifact_path")
        return self

    @property
    def identity(self) -> tuple[str, str, str]:
        return self.tenant_id, self.projection_id, self.target_ref


class ObjectProjectionTargetRegistry:
    """Explicit immutable-by-convention object projection allowlist."""

    def __init__(self, targets: tuple[ObjectProjectionTarget, ...] = ()) -> None:
        self._targets: dict[tuple[str, str, str], ObjectProjectionTarget] = {}
        for target in targets:
            self.register(target)

    def register(self, target: ObjectProjectionTarget) -> None:
        if target.identity in self._targets:
            raise ObjectProjectionConfigurationError(
                "duplicate object projection target registration"
            )
        self._targets[target.identity] = target

    def resolve(
        self, *, tenant_id: str, projection_id: str, target_ref: str
    ) -> ObjectProjectionTarget:
        target = self._targets.get((tenant_id, projection_id, target_ref))
        if target is None:
            raise ObjectProjectionValidationError(
                "object projection target is not explicitly registered"
            )
        return target


class ObjectVersionEvidence(_FrozenModel):
    version_id: NonEmptyText | None = None
    etag: NonEmptyText | None = None
    delete_marker_version_id: NonEmptyText | None = None
    metadata: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _one_state(self) -> ObjectVersionEvidence:
        existing = self.version_id is not None or self.etag is not None
        if existing != (self.version_id is not None and self.etag is not None):
            raise ValueError("existing object evidence requires version_id and etag")
        if existing and self.delete_marker_version_id is not None:
            raise ValueError("object and delete marker identities are mutually exclusive")
        return self


class ObjectProjectionRepairReceipt(_FrozenModel):
    """Versioned S3 commit evidence suitable for checkpoint construction."""

    schema_id: ClassVar[str] = "gda.object-projection-repair-receipt.v1"
    status: str = Field(pattern=r"^(completed|replayed|checkpointed|deleted)$")
    tenant_id: TenantId
    projection_id: str
    target_ref: NonEmptyText
    action: str = Field(pattern=r"^(checkpoint|rebuild|delete)$")
    plan_sha256: Sha256
    idempotency_key: Sha256
    provider_commit_ref: dict[str, Any]
    target_exists: bool
    target_content_sha256: Sha256 | None = None
    target_row_count: int = Field(ge=0, le=1)
    target_size_bytes: int = Field(ge=0)
    object_version_id: NonEmptyText | None = None
    object_etag: NonEmptyText | None = None
    delete_marker_version_id: NonEmptyText | None = None
    observed_at: datetime

    @field_validator("observed_at")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("receipt timestamp must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _state(self) -> ObjectProjectionRepairReceipt:
        if self.target_exists != (self.target_content_sha256 is not None):
            raise ValueError("receipt target content must match target existence")
        if self.target_exists:
            if (
                self.target_row_count != 1
                or self.target_size_bytes < 1
                or self.object_version_id is None
                or self.object_etag is None
                or self.delete_marker_version_id is not None
            ):
                raise ValueError("existing object receipt lacks immutable object evidence")
        elif (
            self.target_row_count != 0
            or self.target_size_bytes != 0
            or self.object_version_id is not None
            or self.object_etag is not None
        ):
            raise ValueError("deleted object receipt contains existing-object evidence")
        if self.provider_commit_ref.get("plan_sha256") != self.plan_sha256:
            raise ValueError("provider commit ref must bind plan_sha256")
        if self.provider_commit_ref.get("idempotency_key") != self.idempotency_key:
            raise ValueError("provider commit ref must bind idempotency key")
        return self


def object_projection_receipt_fingerprint(
    *,
    tenant_id: str,
    projection_id: str,
    target_ref: str,
    action: str,
    plan_sha256: str,
    idempotency_key: str,
    provider_commit_ref: dict[str, Any],
    target_exists: bool,
    target_content_sha256: str | None,
    target_row_count: int,
    target_size_bytes: int,
) -> str:
    """Fingerprint stable S3 receipt evidence before version IDs are known."""

    commit_ref = dict(provider_commit_ref)
    for key in (
        "receipt_sha256",
        "provider_commit",
        "version_id",
        "etag",
        "delete_marker_version_id",
    ):
        commit_ref.pop(key, None)
    return canonical_json_fingerprint(
        {
            "schema": "gda-s3-object-provider-receipt.v1",
            "tenant_id": tenant_id,
            "projection_id": projection_id,
            "target_ref": target_ref,
            "action": action,
            "plan_sha256": plan_sha256,
            "idempotency_key": idempotency_key,
            "provider_commit_ref": commit_ref,
            "target_exists": target_exists,
            "target_content_sha256": target_content_sha256,
            "target_row_count": target_row_count,
            "target_size_bytes": target_size_bytes,
        }
    )


def _error_code(exc: Exception) -> str:
    response = getattr(exc, "response", {})
    error = response.get("Error", {}) if isinstance(response, dict) else {}
    metadata = response.get("ResponseMetadata", {}) if isinstance(response, dict) else {}
    return str(error.get("Code") or metadata.get("HTTPStatusCode") or "")


def _etag(response: dict[str, Any]) -> str:
    value = str(response.get("ETag") or "").strip()
    if len(value) >= 2 and value[0] == value[-1] == '"':
        value = value[1:-1]
    if not value or not value.isascii() or any(ord(character) < 33 for character in value):
        raise ObjectProjectionConfigurationError("S3 object response lacks a valid ETag")
    return value


def _metadata(response: dict[str, Any]) -> dict[str, str]:
    raw = response.get("Metadata") or {}
    if not isinstance(raw, dict):
        raise ObjectProjectionConfigurationError(
            "S3 object response contains invalid user metadata"
        )
    metadata = {str(key).lower(): str(value) for key, value in raw.items()}
    if any(not key or not value.isascii() for key, value in metadata.items()):
        raise ObjectProjectionConfigurationError(
            "S3 object response contains unusable user metadata"
        )
    return metadata


class ObjectProjectionRepairExecutor:
    """Execute sealed plans against registered versioned S3 objects."""

    MAX_OBJECT_BYTES = 500_000_000
    MAX_RECEIPT_BYTES = 64_000
    RECEIPT_PREFIX = "_gda_projection_receipts"
    RECEIPT_METADATA_PREFIX = "gda-receipt-"

    def __init__(
        self,
        registry: ObjectProjectionTargetRegistry,
        *,
        client: Any | None = None,
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
        session_token: str | None = None,
        timeout_seconds: float = 120.0,
    ) -> None:
        if timeout_seconds <= 0 or timeout_seconds > 600:
            raise ObjectProjectionConfigurationError(
                "object projection timeout must be between 0 and 600 seconds"
            )
        self.registry = registry
        self._provided_client = client
        self.access_key_id = access_key_id
        self.secret_access_key = secret_access_key
        self.session_token = session_token
        self.timeout_seconds = timeout_seconds
        self._clients: dict[tuple[str, str], Any] = {}
        self._versioned_buckets: set[tuple[str, str]] = set()
        self._artifact_cache: dict[tuple[str, str, str], bytes] = {}

    def _client(self, target: ObjectProjectionTarget) -> Any:
        if self._provided_client is not None:
            return self._provided_client
        key = target.endpoint_url, target.region_name
        cached = self._clients.get(key)
        if cached is not None:
            return cached
        try:
            import boto3
            from botocore.config import Config as BotoConfig

            client = boto3.client(
                "s3",
                endpoint_url=target.endpoint_url,
                region_name=target.region_name,
                aws_access_key_id=self.access_key_id,
                aws_secret_access_key=self.secret_access_key,
                aws_session_token=self.session_token,
                config=BotoConfig(
                    connect_timeout=self.timeout_seconds,
                    read_timeout=self.timeout_seconds,
                    retries={"max_attempts": 2, "mode": "standard"},
                    s3={"addressing_style": "path"},
                ),
            )
        except Exception as exc:
            raise ObjectProjectionConfigurationError(
                "S3 object projection client cannot be configured"
            ) from exc
        self._clients[key] = client
        return client

    def _assert_versioning(self, target: ObjectProjectionTarget) -> None:
        identity = target.endpoint_url, target.bucket
        if identity in self._versioned_buckets:
            return
        try:
            response = self._client(target).get_bucket_versioning(Bucket=target.bucket)
        except Exception as exc:
            raise ObjectProjectionConfigurationError(
                "registered object projection bucket cannot be inspected"
            ) from exc
        if response.get("Status") != "Enabled":
            raise ObjectProjectionConfigurationError(
                "registered object projection bucket must have versioning enabled"
            )
        self._versioned_buckets.add(identity)

    def _load_artifact(self, target: ObjectProjectionTarget) -> bytes:
        cached = self._artifact_cache.get(target.identity)
        if cached is not None:
            return cached
        try:
            manifest_path = Path(target.bundle_manifest_path)
            manifest_bytes = manifest_path.read_bytes()
            if hashlib.sha256(manifest_bytes).hexdigest() != target.bundle_manifest_sha256:
                raise ObjectProjectionConfigurationError(
                    "registered customer bundle manifest fingerprint differs"
                )
            manifest = json.loads(manifest_bytes)
            bundle = manifest["bundle"]
            ontology = manifest["ontology"]
            if (
                bundle["id"] != target.bundle_id
                or bundle["version"] != target.bundle_version
                or ontology["key"] != _ONTOLOGY_KEY
                or ontology["version"] != _ONTOLOGY_VERSION
                or ontology["package_id"] != target.ontology_package_id
                or ontology["sha256"] != target.ontology_package_content_sha256
            ):
                raise ObjectProjectionConfigurationError(
                    "registered customer bundle identity differs from its manifest"
                )
            matches = [
                item for item in manifest["files"] if item.get("name") == target.artifact_name
            ]
            if len(matches) != 1:
                raise ObjectProjectionConfigurationError(
                    "registered customer artifact is not unique in its manifest"
                )
            record = matches[0]
            if (
                record.get("sha256") != target.artifact_sha256
                or int(record.get("size", -1)) != target.artifact_size_bytes
            ):
                raise ObjectProjectionConfigurationError(
                    "registered customer artifact identity differs from its manifest"
                )
            payload = Path(target.artifact_path).read_bytes()
            if (
                len(payload) != target.artifact_size_bytes
                or hashlib.sha256(payload).hexdigest() != target.artifact_sha256
            ):
                raise ObjectProjectionConfigurationError(
                    "registered customer artifact bytes differ from the sealed manifest"
                )
        except ObjectProjectionExecutionError:
            raise
        except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ObjectProjectionConfigurationError(
                "registered customer artifact cannot be verified"
            ) from exc
        self._artifact_cache[target.identity] = payload
        return payload

    @classmethod
    def _receipt_key(
        cls,
        target: ObjectProjectionTarget,
        plan: ProjectionRepairPlan,
    ) -> str:
        identity_sha256 = canonical_json_fingerprint(
            {
                "tenant_id": target.tenant_id,
                "projection_id": target.projection_id,
                "target_ref": target.target_ref,
                "plan_sha256": plan.plan_sha256,
                "idempotency_key": plan.plan_idempotency_key,
            }
        )
        return f"{cls.RECEIPT_PREFIX}/{identity_sha256}.json"

    @staticmethod
    def _stable_commit_ref(
        target: ObjectProjectionTarget,
        plan: ProjectionRepairPlan,
        *,
        previous: ObjectVersionEvidence | None = None,
        previous_size: int = 0,
        receipt_key: str | None = None,
    ) -> dict[str, Any]:
        atomicity = {
            "rebuild": "target_payload_and_plan_metadata_single_put_object",
            "delete": "versioned_intent_then_delete_marker_chain",
            "checkpoint": "target_observation_only",
        }[plan.action]
        commit_ref: dict[str, Any] = {
            "provider": "s3_object_store",
            "provider_atomicity": atomicity,
            "bucket": target.bucket,
            "key": target.key,
            "artifact_sha256": target.artifact_sha256,
            "artifact_size_bytes": target.artifact_size_bytes,
            "plan_sha256": plan.plan_sha256,
            "idempotency_key": plan.plan_idempotency_key,
        }
        if receipt_key is not None:
            commit_ref["receipt_object_key"] = receipt_key
        if previous is not None:
            commit_ref.update(
                {
                    "expected_previous_version_id": previous.version_id,
                    "expected_previous_etag": previous.etag,
                    "expected_previous_size_bytes": previous_size,
                    "expected_previous_content_sha256": (
                        plan.observation.observed_content_sha256
                    ),
                }
            )
        return commit_ref

    @staticmethod
    def _receipt_sha256(
        plan: ProjectionRepairPlan,
        commit_ref: dict[str, Any],
        *,
        target_size_bytes: int,
    ) -> str:
        desired = plan.desired_state
        return object_projection_receipt_fingerprint(
            tenant_id=plan.tenant_id,
            projection_id=plan.projection_id,
            target_ref=plan.target_ref,
            action=plan.action,
            plan_sha256=plan.plan_sha256,
            idempotency_key=plan.plan_idempotency_key,
            provider_commit_ref=commit_ref,
            target_exists=desired.target_exists,
            target_content_sha256=desired.expected_target_content_sha256,
            target_row_count=desired.expected_row_count,
            target_size_bytes=target_size_bytes,
        )

    @classmethod
    def _plan_receipt_metadata(
        cls,
        plan: ProjectionRepairPlan,
        receipt_sha256: str,
    ) -> dict[str, str]:
        prefix = cls.RECEIPT_METADATA_PREFIX
        return {
            f"{prefix}schema": "gda-s3-object-provider-receipt-v1",
            f"{prefix}action": plan.action,
            f"{prefix}plan-sha256": plan.plan_sha256,
            f"{prefix}idempotency-key": plan.plan_idempotency_key,
            f"{prefix}sha256": receipt_sha256,
        }

    @classmethod
    def _metadata_receipt_sha256(
        cls,
        metadata: dict[str, str],
        plan: ProjectionRepairPlan,
    ) -> str | None:
        prefix = cls.RECEIPT_METADATA_PREFIX
        if metadata.get(f"{prefix}schema") != "gda-s3-object-provider-receipt-v1":
            return None
        if (
            metadata.get(f"{prefix}action") != plan.action
            or metadata.get(f"{prefix}plan-sha256") != plan.plan_sha256
            or metadata.get(f"{prefix}idempotency-key")
            != plan.plan_idempotency_key
        ):
            raise ObjectProjectionValidationError(
                "stored S3 object receipt metadata is not bound to the sealed plan"
            )
        receipt_sha256 = metadata.get(f"{prefix}sha256")
        if receipt_sha256 is None or len(receipt_sha256) != 64:
            raise ObjectProjectionValidationError(
                "stored S3 object receipt metadata lacks its fingerprint"
            )
        return receipt_sha256

    def _write_delete_intent(
        self,
        target: ObjectProjectionTarget,
        plan: ProjectionRepairPlan,
        previous: ObjectVersionEvidence,
        previous_size: int,
    ) -> tuple[dict[str, Any], str]:
        receipt_key = self._receipt_key(target, plan)
        commit_ref = self._stable_commit_ref(
            target,
            plan,
            previous=previous,
            previous_size=previous_size,
            receipt_key=receipt_key,
        )
        receipt_sha256 = self._receipt_sha256(
            plan,
            commit_ref,
            target_size_bytes=0,
        )
        payload = json.dumps(
            {
                "schema_id": "gda.s3-object-delete-intent.v1",
                "tenant_id": plan.tenant_id,
                "projection_id": plan.projection_id,
                "target_ref": plan.target_ref,
                "action": plan.action,
                "plan_sha256": plan.plan_sha256,
                "idempotency_key": plan.plan_idempotency_key,
                "provider_commit_ref": commit_ref,
                "receipt_sha256": receipt_sha256,
            },
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        try:
            self._client(target).put_object(
                Bucket=target.bucket,
                Key=receipt_key,
                Body=payload,
                ContentType="application/json",
                Metadata=self._plan_receipt_metadata(plan, receipt_sha256),
            )
        except Exception as exc:
            raise ObjectProjectionExecutionError(
                "S3 delete receipt intent write failed before target mutation"
            ) from exc
        return commit_ref, receipt_sha256

    def _read_delete_intent(
        self,
        target: ObjectProjectionTarget,
        plan: ProjectionRepairPlan,
    ) -> tuple[dict[str, Any], str] | None:
        receipt_key = self._receipt_key(target, plan)
        try:
            response = self._client(target).get_object(
                Bucket=target.bucket,
                Key=receipt_key,
            )
        except Exception as exc:
            if _error_code(exc) in _MISSING_CODES:
                return None
            raise ObjectProjectionConfigurationError(
                "S3 delete receipt intent cannot be read"
            ) from exc
        body = response.get("Body")
        if body is None:
            raise ObjectProjectionValidationError(
                "stored S3 delete receipt intent lacks a body"
            )
        try:
            payload = body.read(self.MAX_RECEIPT_BYTES + 1)
        finally:
            close = getattr(body, "close", None)
            if close is not None:
                close()
        if len(payload) > self.MAX_RECEIPT_BYTES:
            raise ObjectProjectionValidationError(
                "stored S3 delete receipt intent exceeds the byte budget"
            )
        try:
            document = json.loads(payload)
            commit_ref = dict(document["provider_commit_ref"])
            receipt_sha256 = str(document["receipt_sha256"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ObjectProjectionValidationError(
                "stored S3 delete receipt intent is invalid"
            ) from exc
        if (
            document.get("schema_id") != "gda.s3-object-delete-intent.v1"
            or document.get("tenant_id") != plan.tenant_id
            or document.get("projection_id") != plan.projection_id
            or document.get("target_ref") != plan.target_ref
            or document.get("action") != plan.action
            or document.get("plan_sha256") != plan.plan_sha256
            or document.get("idempotency_key") != plan.plan_idempotency_key
            or commit_ref
            != self._stable_commit_ref(
                target,
                plan,
                previous=ObjectVersionEvidence(
                    version_id=commit_ref.get("expected_previous_version_id"),
                    etag=commit_ref.get("expected_previous_etag"),
                ),
                previous_size=int(commit_ref.get("expected_previous_size_bytes", -1)),
                receipt_key=receipt_key,
            )
            or receipt_sha256
            != self._receipt_sha256(plan, commit_ref, target_size_bytes=0)
        ):
            raise ObjectProjectionValidationError(
                "stored S3 delete receipt intent is not bound to the sealed plan"
            )
        metadata_sha256 = self._metadata_receipt_sha256(
            _metadata(response),
            plan,
        )
        if metadata_sha256 != receipt_sha256:
            raise ObjectProjectionValidationError(
                "stored S3 delete receipt intent metadata differs from its body"
            )
        return commit_ref, receipt_sha256

    def _latest_delete_marker(self, target: ObjectProjectionTarget) -> str | None:
        try:
            response = self._client(target).list_object_versions(
                Bucket=target.bucket,
                Prefix=target.key,
                MaxKeys=10,
            )
        except Exception as exc:
            raise ObjectProjectionConfigurationError(
                "S3 object version history cannot be inspected"
            ) from exc
        markers = [
            marker
            for marker in response.get("DeleteMarkers", [])
            if marker.get("Key") == target.key and marker.get("IsLatest") is True
        ]
        if not markers:
            return None
        if len(markers) != 1 or not str(markers[0].get("VersionId") or "").strip():
            raise ObjectProjectionConfigurationError(
                "S3 object delete marker identity is ambiguous"
            )
        return str(markers[0]["VersionId"])

    def observe_versioned(
        self, target: ObjectProjectionTarget
    ) -> tuple[ProjectionTargetObservation, ObjectVersionEvidence, int]:
        self._assert_versioning(target)
        try:
            response = self._client(target).get_object(Bucket=target.bucket, Key=target.key)
        except Exception as exc:
            if _error_code(exc) in _MISSING_CODES:
                return (
                    self._missing_observation(target),
                    ObjectVersionEvidence(
                        delete_marker_version_id=self._latest_delete_marker(target)
                    ),
                    0,
                )
            raise ObjectProjectionConfigurationError(
                "registered object projection cannot be observed"
            ) from exc
        version_id = str(response.get("VersionId") or "").strip()
        if not version_id or version_id == "null":
            raise ObjectProjectionConfigurationError(
                "registered object projection lacks immutable version identity"
            )
        etag = _etag(response)
        body = response.get("Body")
        if body is None:
            raise ObjectProjectionConfigurationError("S3 object response lacks a body")
        digest = hashlib.sha256()
        size = 0
        try:
            while True:
                chunk = body.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > self.MAX_OBJECT_BYTES:
                    raise ObjectProjectionValidationError(
                        "observed object exceeds the response byte budget"
                    )
                digest.update(chunk)
        finally:
            close = getattr(body, "close", None)
            if close is not None:
                close()
        try:
            declared_size = int(response.get("ContentLength"))
        except (TypeError, ValueError) as exc:
            raise ObjectProjectionConfigurationError(
                "S3 object response lacks a valid content length"
            ) from exc
        if declared_size != size:
            raise ObjectProjectionConfigurationError(
                "S3 object response content length differs from its bytes"
            )
        return (
            ProjectionTargetObservation(
                tenant_id=target.tenant_id,
                projection_id=target.projection_id,
                target_engine=ProjectionEngine.OBJECT_STORE,
                target_ref=target.target_ref,
                target_exists=True,
                observed_content_sha256=digest.hexdigest(),
                observed_row_count=1,
                observed_by="workload:object-projection-executor",
                observed_at=datetime.now(UTC),
            ),
            ObjectVersionEvidence(
                version_id=version_id,
                etag=etag,
                metadata=_metadata(response),
            ),
            size,
        )

    def observe(self, target: ObjectProjectionTarget) -> ProjectionTargetObservation:
        return self.observe_versioned(target)[0]

    @staticmethod
    def _missing_observation(target: ObjectProjectionTarget) -> ProjectionTargetObservation:
        return ProjectionTargetObservation(
            tenant_id=target.tenant_id,
            projection_id=target.projection_id,
            target_engine=ProjectionEngine.OBJECT_STORE,
            target_ref=target.target_ref,
            target_exists=False,
            observed_content_sha256=None,
            observed_row_count=0,
            observed_by="workload:object-projection-executor",
            observed_at=datetime.now(UTC),
        )

    @staticmethod
    def _assert_plan(plan: ProjectionRepairPlan, target: ObjectProjectionTarget) -> None:
        if plan.target_engine is not ProjectionEngine.OBJECT_STORE:
            raise ObjectProjectionValidationError("object executor only accepts object_store plans")
        if (
            plan.tenant_id != target.tenant_id
            or plan.projection_id != target.projection_id
            or plan.target_ref != target.target_ref
        ):
            raise ObjectProjectionValidationError(
                "repair plan target identity does not match registered object target"
            )
        if plan.action == "fail_closed":
            raise ObjectProjectionValidationError("fail-closed repair plans cannot be executed")

    @staticmethod
    def _assert_observation(
        plan: ProjectionRepairPlan, current: ProjectionTargetObservation
    ) -> None:
        expected = plan.observation
        if (
            current.target_exists != expected.target_exists
            or current.observed_content_sha256 != expected.observed_content_sha256
            or current.observed_row_count != expected.observed_row_count
        ):
            raise ObjectProjectionValidationError(
                "object target changed after the repair plan was sealed"
            )

    @staticmethod
    def _receipt_with_commit_evidence(
        plan: ProjectionRepairPlan,
        *,
        commit_ref: dict[str, Any],
        receipt_sha256: str,
        target_exists: bool,
        target_content_sha256: str | None,
        target_row_count: int,
        target_size_bytes: int,
        version: ObjectVersionEvidence,
        status: str,
        observed_at: datetime,
    ) -> ObjectProjectionRepairReceipt:
        provider_commit_ref = dict(commit_ref)
        provider_commit_ref["provider_commit"] = (
            version.version_id or version.delete_marker_version_id or "missing"
        )
        provider_commit_ref["version_id"] = version.version_id
        provider_commit_ref["etag"] = version.etag
        provider_commit_ref["delete_marker_version_id"] = version.delete_marker_version_id
        provider_commit_ref["receipt_sha256"] = receipt_sha256
        return ObjectProjectionRepairReceipt(
            status=status,
            tenant_id=plan.tenant_id,
            projection_id=plan.projection_id,
            target_ref=plan.target_ref,
            action=plan.action,
            plan_sha256=plan.plan_sha256,
            idempotency_key=plan.plan_idempotency_key,
            provider_commit_ref=provider_commit_ref,
            target_exists=target_exists,
            target_content_sha256=target_content_sha256,
            target_row_count=target_row_count,
            target_size_bytes=target_size_bytes,
            object_version_id=version.version_id,
            object_etag=version.etag,
            delete_marker_version_id=version.delete_marker_version_id,
            observed_at=observed_at,
        )

    def recover_receipt(
        self,
        plan: ProjectionRepairPlan,
    ) -> ObjectProjectionRepairReceipt | None:
        """Recover S3-native evidence without replaying a committed mutation."""

        target = self.registry.resolve(
            tenant_id=plan.tenant_id,
            projection_id=plan.projection_id,
            target_ref=plan.target_ref,
        )
        self._assert_plan(plan, target)
        if plan.action == "delete":
            intent = self._read_delete_intent(target, plan)
            if intent is None:
                return None
            commit_ref, receipt_sha256 = intent
            current, version, size = self.observe_versioned(target)
            expected_version = commit_ref.get("expected_previous_version_id")
            expected_etag = commit_ref.get("expected_previous_etag")
            if current.target_exists:
                if version.version_id == expected_version and version.etag == expected_etag:
                    return None
                raise ObjectProjectionValidationError(
                    "S3 delete intent target changed before delete completion"
                )
            marker_version = version.delete_marker_version_id
            if marker_version is None:
                raise ObjectProjectionValidationError(
                    "S3 delete intent lacks a verifiable delete marker"
                )
            receipt = self._receipt_with_commit_evidence(
                plan,
                commit_ref=commit_ref,
                receipt_sha256=receipt_sha256,
                target_exists=False,
                target_content_sha256=None,
                target_row_count=0,
                target_size_bytes=0,
                version=version,
                status="replayed",
                observed_at=datetime.now(UTC),
            )
            if (
                receipt.provider_commit_ref.get("delete_marker_version_id") != marker_version
                or size != 0
            ):
                raise ObjectProjectionValidationError(
                    "S3 delete receipt does not match the current delete marker"
                )
            return receipt
        if plan.action != "rebuild":
            return None
        current, version, size = self.observe_versioned(target)
        if not current.target_exists:
            return None
        receipt_sha256 = self._metadata_receipt_sha256(version.metadata, plan)
        if receipt_sha256 is None:
            return None
        commit_ref = self._stable_commit_ref(target, plan)
        expected_sha256 = self._receipt_sha256(
            plan,
            commit_ref,
            target_size_bytes=size,
        )
        if receipt_sha256 != expected_sha256:
            raise ObjectProjectionValidationError(
                "stored S3 object receipt fingerprint differs from the sealed plan"
            )
        desired = plan.desired_state
        if (
            current.observed_content_sha256 != desired.expected_target_content_sha256
            or current.observed_row_count != desired.expected_row_count
            or size != target.artifact_size_bytes
        ):
            raise ObjectProjectionValidationError(
                "stored S3 object receipt does not match the current target"
            )
        return self._receipt_with_commit_evidence(
            plan,
            commit_ref=commit_ref,
            receipt_sha256=receipt_sha256,
            target_exists=True,
            target_content_sha256=current.observed_content_sha256,
            target_row_count=current.observed_row_count,
            target_size_bytes=size,
            version=version,
            status="replayed",
            observed_at=datetime.now(UTC),
        )

    def _replace(
        self,
        target: ObjectProjectionTarget,
        payload: bytes,
        metadata: dict[str, str],
    ) -> ObjectVersionEvidence:
        try:
            response = self._client(target).put_object(
                Bucket=target.bucket,
                Key=target.key,
                Body=payload,
                ContentType=target.media_type,
                Metadata=metadata,
            )
        except Exception as exc:
            raise ObjectProjectionExecutionError("S3 object replace failed") from exc
        version_id = str(response.get("VersionId") or "").strip()
        if not version_id or version_id == "null":
            raise ObjectProjectionExecutionError(
                "S3 object replace did not return an immutable version"
            )
        return ObjectVersionEvidence(
            version_id=version_id,
            etag=_etag(response),
            metadata=metadata,
        )

    def _delete(self, target: ObjectProjectionTarget) -> ObjectVersionEvidence:
        try:
            response = self._client(target).delete_object(
                Bucket=target.bucket,
                Key=target.key,
            )
        except Exception as exc:
            raise ObjectProjectionExecutionError("S3 object delete failed") from exc
        version_id = str(response.get("VersionId") or "").strip()
        if response.get("DeleteMarker") is not True or not version_id or version_id == "null":
            raise ObjectProjectionExecutionError(
                "S3 object delete did not return an immutable delete marker"
            )
        return ObjectVersionEvidence(delete_marker_version_id=version_id)

    def execute(
        self,
        plan: ProjectionRepairPlan,
        *,
        observed_at: datetime | None = None,
    ) -> ObjectProjectionRepairReceipt:
        target = self.registry.resolve(
            tenant_id=plan.tenant_id,
            projection_id=plan.projection_id,
            target_ref=plan.target_ref,
        )
        self._assert_plan(plan, target)
        now = observed_at or datetime.now(UTC)
        if now.tzinfo is None or now.utcoffset() is None:
            raise ObjectProjectionValidationError("observed_at must be timezone-aware")
        now = now.astimezone(UTC)
        stored_receipt = self.recover_receipt(plan)
        if stored_receipt is not None:
            return stored_receipt.model_copy(update={"status": "replayed"})
        current, current_version, current_size = self.observe_versioned(target)
        desired = plan.desired_state
        commit_ref: dict[str, Any] | None = None
        receipt_sha256: str | None = None
        already_desired = (
            current.target_exists == desired.target_exists
            and current.observed_content_sha256 == desired.expected_target_content_sha256
            and current.observed_row_count == desired.expected_row_count
        )
        if already_desired:
            if plan.action != "checkpoint":
                raise ObjectProjectionValidationError(
                    "desired S3 state lacks a plan-bound provider receipt"
                )
            status = "checkpointed" if plan.action == "checkpoint" else "replayed"
            post = current
            post_version = current_version
            post_size = current_size
        else:
            self._assert_observation(plan, current)
            if plan.action == "checkpoint":
                raise ObjectProjectionValidationError(
                    "checkpoint target does not match desired object state"
                )
            if plan.action == "delete":
                commit_ref, receipt_sha256 = self._write_delete_intent(
                    target,
                    plan,
                    current_version,
                    current_size,
                )
                mutation = self._delete(target)
                status = "deleted"
            else:
                payload = self._load_artifact(target)
                if (
                    desired.source_content_sha256 != target.artifact_sha256
                    or desired.expected_target_content_sha256 != target.artifact_sha256
                    or desired.expected_row_count != 1
                ):
                    raise ObjectProjectionValidationError(
                        "registered customer artifact does not match desired object state"
                    )
                commit_ref = self._stable_commit_ref(target, plan)
                receipt_sha256 = self._receipt_sha256(
                    plan,
                    commit_ref,
                    target_size_bytes=target.artifact_size_bytes,
                )
                metadata = {
                    "sha256": target.artifact_sha256,
                    "bundle-id": target.bundle_id,
                    "ontology-package": target.ontology_package_id,
                    **self._plan_receipt_metadata(plan, receipt_sha256),
                }
                mutation = self._replace(target, payload, metadata)
                status = "completed"
            post, post_version, post_size = self.observe_versioned(target)
            if mutation != post_version:
                raise ObjectProjectionExecutionError(
                    "S3 post-repair version identity differs from the provider commit"
                )
        if (
            post.target_exists != desired.target_exists
            or post.observed_content_sha256 != desired.expected_target_content_sha256
            or post.observed_row_count != desired.expected_row_count
        ):
            raise ObjectProjectionExecutionError(
                "object post-repair observation does not match desired state"
            )
        if commit_ref is None:
            commit_ref = self._stable_commit_ref(target, plan)
        if receipt_sha256 is None:
            receipt_sha256 = self._receipt_sha256(
                plan,
                commit_ref,
                target_size_bytes=post_size,
            )
        return self._receipt_with_commit_evidence(
            plan,
            commit_ref=commit_ref,
            receipt_sha256=receipt_sha256,
            target_exists=post.target_exists,
            target_content_sha256=post.observed_content_sha256,
            target_row_count=post.observed_row_count,
            target_size_bytes=post_size,
            version=post_version,
            status=status,
            observed_at=now,
        )


__all__ = [
    "ObjectProjectionConfigurationError",
    "ObjectProjectionExecutionError",
    "ObjectProjectionRepairExecutor",
    "ObjectProjectionRepairReceipt",
    "ObjectProjectionTarget",
    "ObjectProjectionTargetRegistry",
    "ObjectProjectionValidationError",
    "ObjectVersionEvidence",
    "object_projection_receipt_fingerprint",
]
