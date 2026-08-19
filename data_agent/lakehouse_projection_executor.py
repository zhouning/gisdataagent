"""Plan-bound Iceberg projection for the sealed Chongqing customer bundle."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar, Protocol
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


class LakehouseProjectionExecutionError(ProjectionConsistencyError):
    """A plan-bound Iceberg action could not be safely completed."""


class LakehouseProjectionConfigurationError(LakehouseProjectionExecutionError):
    """The registered table, artifact, or Spark channel is unusable."""


class LakehouseProjectionValidationError(LakehouseProjectionExecutionError):
    """The plan, sealed artifact, or observed table is invalid."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class LakehouseProjectionTarget(_FrozenModel):
    """Explicit Iceberg table bound to one sealed customer artifact."""

    schema_id: ClassVar[str] = "gda.lakehouse-projection-target.v1"
    tenant_id: TenantId
    projection_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$")
    target_ref: NonEmptyText
    catalog: str = Field(pattern=r"^[a-z][a-z0-9_]{1,62}$")
    namespace: str = Field(pattern=r"^[a-z][a-z0-9_]{1,62}$")
    table: str = Field(pattern=r"^[a-z][a-z0-9_]{1,62}$")
    warehouse_uri: NonEmptyText
    endpoint_url: NonEmptyText
    region_name: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9-]{0,62}$")
    bucket: str = Field(pattern=r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")
    bundle_manifest_path: NonEmptyText
    bundle_manifest_sha256: Sha256
    bundle_id: str = Field(pattern=r"^[a-z][a-z0-9-]{2,127}$")
    bundle_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    artifact_path: NonEmptyText
    artifact_name: NonEmptyText
    artifact_sha256: Sha256
    artifact_size_bytes: int = Field(ge=1, le=500_000_000)
    expected_table_content_sha256: Sha256
    expected_row_count: int = Field(ge=1, le=5_000_000)
    ontology_package_id: NonEmptyText
    ontology_package_content_sha256: Sha256

    @model_validator(mode="after")
    def _registered_identity(self) -> LakehouseProjectionTarget:
        if (
            self.bundle_id != _BUNDLE_ID
            or self.bundle_version != _BUNDLE_VERSION
            or self.ontology_package_id != _ONTOLOGY_PACKAGE_ID
            or self.ontology_package_content_sha256 != _ONTOLOGY_PACKAGE_SHA256
        ):
            raise ValueError(
                "lakehouse projections are restricted to the sealed Chongqing customer bundle"
            )
        target = urlsplit(self.target_ref)
        if (
            target.scheme != "iceberg"
            or target.netloc != self.catalog
            or target.path.lstrip("/") != f"{self.namespace}/{self.table}"
            or target.username
            or target.password
            or target.query
            or target.fragment
        ):
            raise ValueError(
                "target_ref must exactly match the registered Iceberg table identifier"
            )
        warehouse = urlsplit(self.warehouse_uri)
        if (
            warehouse.scheme != "s3"
            or warehouse.netloc != self.bucket
            or not warehouse.path.strip("/")
            or warehouse.username
            or warehouse.password
            or warehouse.query
            or warehouse.fragment
        ):
            raise ValueError("warehouse_uri must be a normalized S3 prefix in the bucket")
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
        if Path(self.artifact_path).name != self.artifact_name:
            raise ValueError("artifact_name must match artifact_path")
        return self

    @property
    def identity(self) -> tuple[str, str, str]:
        return self.tenant_id, self.projection_id, self.target_ref

    @property
    def table_identifier(self) -> str:
        return f"{self.catalog}.{self.namespace}.{self.table}"


class LakehouseProjectionTargetRegistry:
    """Explicit immutable-by-convention Iceberg target allowlist."""

    def __init__(self, targets: tuple[LakehouseProjectionTarget, ...] = ()) -> None:
        self._targets: dict[tuple[str, str, str], LakehouseProjectionTarget] = {}
        for target in targets:
            self.register(target)

    def register(self, target: LakehouseProjectionTarget) -> None:
        if target.identity in self._targets:
            raise LakehouseProjectionConfigurationError(
                "duplicate lakehouse projection target registration"
            )
        self._targets[target.identity] = target

    def resolve(
        self, *, tenant_id: str, projection_id: str, target_ref: str
    ) -> LakehouseProjectionTarget:
        target = self._targets.get((tenant_id, projection_id, target_ref))
        if target is None:
            raise LakehouseProjectionValidationError(
                "lakehouse projection target is not explicitly registered"
            )
        return target


class LakehouseSnapshotEvidence(_FrozenModel):
    target_exists: bool
    content_sha256: Sha256 | None = None
    row_count: int = Field(ge=0)
    snapshot_id: int | None = None
    deleted_snapshot_id: int | None = None
    drop_evidence_sha256: Sha256 | None = None
    tombstone_plan_sha256: Sha256 | None = None
    tombstone_idempotency_key: Sha256 | None = None
    provider_receipt_schema: NonEmptyText | None = None
    provider_receipt_action: str | None = Field(default=None, pattern=r"^(rebuild|delete)$")
    provider_receipt_plan_sha256: Sha256 | None = None
    provider_receipt_idempotency_key: Sha256 | None = None
    provider_receipt_sha256: Sha256 | None = None

    @model_validator(mode="after")
    def _state(self) -> LakehouseSnapshotEvidence:
        if self.target_exists:
            if (
                self.content_sha256 is None
                or self.row_count < 1
                or self.snapshot_id is None
                or self.deleted_snapshot_id is not None
                or self.drop_evidence_sha256 is not None
                or self.tombstone_plan_sha256 is not None
                or self.tombstone_idempotency_key is not None
            ):
                raise ValueError("existing Iceberg evidence is incomplete")
        elif self.content_sha256 is not None or self.row_count != 0 or self.snapshot_id is not None:
            raise ValueError("missing Iceberg evidence contains table state")
        deletion_fields = (
            self.deleted_snapshot_id,
            self.drop_evidence_sha256,
            self.tombstone_plan_sha256,
            self.tombstone_idempotency_key,
        )
        if any(value is not None for value in deletion_fields) and any(
            value is None for value in deletion_fields
        ):
            raise ValueError("Iceberg drop evidence requires complete tombstone identity")
        receipt_fields = (
            self.provider_receipt_schema,
            self.provider_receipt_action,
            self.provider_receipt_plan_sha256,
            self.provider_receipt_idempotency_key,
            self.provider_receipt_sha256,
        )
        if any(value is not None for value in receipt_fields) and any(
            value is None for value in receipt_fields
        ):
            raise ValueError("Iceberg provider receipt evidence is incomplete")
        if self.provider_receipt_schema is not None and self.provider_receipt_schema != (
            "gda.iceberg-provider-receipt.v1"
        ):
            raise ValueError("Iceberg provider receipt schema is unsupported")
        if self.provider_receipt_action is not None and self.provider_receipt_action != (
            "rebuild" if self.target_exists else "delete"
        ):
            raise ValueError("Iceberg provider receipt action does not match target state")
        return self


class LakehouseProjectionProvider(Protocol):
    def observe(self, target: LakehouseProjectionTarget) -> LakehouseSnapshotEvidence: ...

    def replace(
        self,
        target: LakehouseProjectionTarget,
        records: tuple[dict[str, Any], ...],
        *,
        plan_sha256: str,
        idempotency_key: str,
        receipt_sha256: str | None = None,
    ) -> LakehouseSnapshotEvidence: ...

    def drop(
        self,
        target: LakehouseProjectionTarget,
        *,
        plan_sha256: str,
        idempotency_key: str,
        receipt_sha256: str | None = None,
    ) -> LakehouseSnapshotEvidence: ...


class LakehouseProjectionRepairReceipt(_FrozenModel):
    """Iceberg snapshot evidence suitable for checkpoint construction."""

    schema_id: ClassVar[str] = "gda.lakehouse-projection-repair-receipt.v1"
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
    target_row_count: int = Field(ge=0)
    snapshot_id: int | None = None
    deleted_snapshot_id: int | None = None
    drop_evidence_sha256: Sha256 | None = None
    observed_at: datetime

    @field_validator("observed_at")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("receipt timestamp must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _state(self) -> LakehouseProjectionRepairReceipt:
        if self.target_exists != (self.target_content_sha256 is not None):
            raise ValueError("receipt target content must match target existence")
        if self.target_exists:
            if self.target_row_count < 1 or self.snapshot_id is None:
                raise ValueError("existing Iceberg receipt lacks snapshot evidence")
        elif self.target_row_count != 0 or self.snapshot_id is not None:
            raise ValueError("deleted Iceberg receipt contains existing table evidence")
        if (self.deleted_snapshot_id is None) != (self.drop_evidence_sha256 is None):
            raise ValueError("deleted Iceberg receipt lacks complete drop evidence")
        if self.provider_commit_ref.get("plan_sha256") != self.plan_sha256:
            raise ValueError("provider commit ref must bind plan_sha256")
        if self.provider_commit_ref.get("idempotency_key") != self.idempotency_key:
            raise ValueError("provider commit ref must bind idempotency key")
        return self


def lakehouse_projection_stable_commit_ref(
    *,
    tenant_id: str,
    projection_id: str,
    target_ref: str,
    table_identifier: str,
    warehouse_uri: str,
    artifact_sha256: str,
    action: str,
    plan_sha256: str,
    idempotency_key: str,
    deleted_snapshot_id: int | None = None,
    drop_evidence_sha256: str | None = None,
) -> dict[str, Any]:
    """Build the provider commit fields that are stable across commit retries."""
    atomicity = {
        "rebuild": "single_iceberg_commit_with_snapshot_receipt",
        "delete": "plan_bound_tombstone_then_drop_table",
        "checkpoint": "target_observation_only",
    }[action]
    commit_ref: dict[str, Any] = {
        "provider": "spark_iceberg",
        "provider_atomicity": atomicity,
        "tenant_id": tenant_id,
        "projection_id": projection_id,
        "target_ref": target_ref,
        "table_identifier": table_identifier,
        "warehouse_uri": warehouse_uri,
        "artifact_sha256": artifact_sha256,
        "plan_sha256": plan_sha256,
        "idempotency_key": idempotency_key,
    }
    if deleted_snapshot_id is not None or drop_evidence_sha256 is not None:
        if deleted_snapshot_id is None or drop_evidence_sha256 is None:
            raise ValueError("Iceberg delete commit evidence must be complete")
        commit_ref.update(
            {
                "deleted_snapshot_id": deleted_snapshot_id,
                "drop_evidence_sha256": drop_evidence_sha256,
            }
        )
    return commit_ref


def lakehouse_projection_receipt_fingerprint(
    *,
    tenant_id: str,
    projection_id: str,
    target_ref: str,
    action: str,
    plan_sha256: str,
    idempotency_key: str,
    provider_commit_ref: Mapping[str, Any],
    target_exists: bool,
    target_content_sha256: str | None,
    target_row_count: int,
) -> str:
    """Fingerprint provider evidence without retry-variant snapshot identifiers."""
    commit_ref = dict(provider_commit_ref)
    for key in (
        "receipt_sha256",
        "provider_commit",
        "snapshot_id",
        "tombstone_plan_sha256",
        "tombstone_idempotency_key",
    ):
        commit_ref.pop(key, None)
    return canonical_json_fingerprint(
        {
            "schema": "gda.iceberg-provider-receipt.v1",
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
        }
    )


def lakehouse_projection_drop_evidence_sha256(
    *,
    table_identifier: str,
    deleted_snapshot_id: int,
    plan_sha256: str,
    idempotency_key: str,
) -> str:
    return canonical_json_fingerprint(
        {
            "table_identifier": table_identifier,
            "deleted_snapshot_id": deleted_snapshot_id,
            "plan_sha256": plan_sha256,
            "idempotency_key": idempotency_key,
            "target_exists": False,
        }
    )


def lakehouse_records_from_artifact(
    artifact_path: str | Path,
) -> tuple[tuple[dict[str, Any], ...], str]:
    """Normalize the customer GeoJSON into a stable Iceberg row contract."""
    document = json.loads(Path(artifact_path).read_text(encoding="utf-8"))
    features = document.get("features") if isinstance(document, dict) else None
    if (
        document.get("type") != "FeatureCollection"
        or not isinstance(features, list)
        or not features
    ):
        raise LakehouseProjectionConfigurationError(
            "registered customer artifact must be a non-empty GeoJSON FeatureCollection"
        )
    records: list[dict[str, Any]] = []
    for index, feature in enumerate(features):
        if not isinstance(feature, dict):
            raise LakehouseProjectionConfigurationError("customer feature must be an object")
        properties = feature.get("properties")
        geometry = feature.get("geometry")
        if not isinstance(properties, dict) or not isinstance(geometry, dict):
            raise LakehouseProjectionConfigurationError(
                "customer feature requires properties and geometry objects"
            )
        parcel_id = str(properties.get("parcel_id") or "").strip()
        if not parcel_id:
            raise LakehouseProjectionConfigurationError(
                "customer feature parcel identity must be non-empty"
            )
        feature_id = f"{parcel_id}#{index:06d}"
        geometry_json = json.dumps(
            geometry, ensure_ascii=True, sort_keys=True, separators=(",", ":")
        )
        properties_json = json.dumps(
            properties, ensure_ascii=True, sort_keys=True, separators=(",", ":")
        )
        feature_json = json.dumps(
            {"geometry": geometry, "properties": properties, "type": "Feature"},
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        records.append(
            {
                "feature_index": index,
                "feature_id": feature_id,
                "parcel_id": parcel_id,
                "geometry_json": geometry_json,
                "properties_json": properties_json,
                "feature_sha256": hashlib.sha256(feature_json.encode("utf-8")).hexdigest(),
            }
        )
    return tuple(records), canonical_json_fingerprint(records)


class LakehouseProjectionRepairExecutor:
    """Execute sealed plans against registered Iceberg tables."""

    def __init__(
        self,
        registry: LakehouseProjectionTargetRegistry,
        *,
        provider: LakehouseProjectionProvider,
    ) -> None:
        self.registry = registry
        self.provider = provider
        self._record_cache: dict[tuple[str, str, str], tuple[dict[str, Any], ...]] = {}

    def _load_records(self, target: LakehouseProjectionTarget) -> tuple[dict[str, Any], ...]:
        cached = self._record_cache.get(target.identity)
        if cached is not None:
            return cached
        try:
            manifest_path = Path(target.bundle_manifest_path)
            manifest_bytes = manifest_path.read_bytes()
            if hashlib.sha256(manifest_bytes).hexdigest() != target.bundle_manifest_sha256:
                raise LakehouseProjectionConfigurationError(
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
                raise LakehouseProjectionConfigurationError(
                    "registered customer bundle identity differs from its manifest"
                )
            matches = [
                item for item in manifest["files"] if item.get("name") == target.artifact_name
            ]
            if len(matches) != 1:
                raise LakehouseProjectionConfigurationError(
                    "registered customer artifact is not unique in its manifest"
                )
            artifact = Path(target.artifact_path)
            artifact_bytes = artifact.read_bytes()
            record = matches[0]
            if (
                record.get("sha256") != target.artifact_sha256
                or int(record.get("size", -1)) != target.artifact_size_bytes
                or len(artifact_bytes) != target.artifact_size_bytes
                or hashlib.sha256(artifact_bytes).hexdigest() != target.artifact_sha256
            ):
                raise LakehouseProjectionConfigurationError(
                    "registered customer artifact differs from its sealed manifest"
                )
            records, fingerprint = lakehouse_records_from_artifact(artifact)
            if (
                len(records) != target.expected_row_count
                or fingerprint != target.expected_table_content_sha256
            ):
                raise LakehouseProjectionConfigurationError(
                    "registered Iceberg row contract differs from the customer artifact"
                )
        except LakehouseProjectionExecutionError:
            raise
        except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise LakehouseProjectionConfigurationError(
                "registered customer artifact cannot be verified"
            ) from exc
        self._record_cache[target.identity] = records
        return records

    def observe_versioned(
        self, target: LakehouseProjectionTarget
    ) -> tuple[ProjectionTargetObservation, LakehouseSnapshotEvidence]:
        try:
            evidence = self.provider.observe(target)
        except LakehouseProjectionExecutionError:
            raise
        except Exception as exc:
            raise LakehouseProjectionConfigurationError(
                "registered Iceberg projection cannot be observed"
            ) from exc
        observation = ProjectionTargetObservation(
            tenant_id=target.tenant_id,
            projection_id=target.projection_id,
            target_engine=ProjectionEngine.LAKEHOUSE,
            target_ref=target.target_ref,
            target_exists=evidence.target_exists,
            observed_content_sha256=evidence.content_sha256,
            observed_row_count=evidence.row_count,
            observed_by="workload:lakehouse-projection-executor",
            observed_at=datetime.now(UTC),
        )
        return observation, evidence

    def observe(self, target: LakehouseProjectionTarget) -> ProjectionTargetObservation:
        return self.observe_versioned(target)[0]

    @staticmethod
    def _assert_plan(plan: ProjectionRepairPlan, target: LakehouseProjectionTarget) -> None:
        if plan.target_engine is not ProjectionEngine.LAKEHOUSE:
            raise LakehouseProjectionValidationError(
                "lakehouse executor only accepts lakehouse plans"
            )
        if (
            plan.tenant_id != target.tenant_id
            or plan.projection_id != target.projection_id
            or plan.target_ref != target.target_ref
        ):
            raise LakehouseProjectionValidationError(
                "repair plan target identity does not match registered Iceberg target"
            )
        if plan.action == "fail_closed":
            raise LakehouseProjectionValidationError("fail-closed plans cannot be executed")

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
            raise LakehouseProjectionValidationError(
                "Iceberg target changed after the repair plan was sealed"
            )

    @staticmethod
    def _commit_ref(
        target: LakehouseProjectionTarget,
        plan: ProjectionRepairPlan,
        evidence: LakehouseSnapshotEvidence,
    ) -> dict[str, Any]:
        commit_ref = lakehouse_projection_stable_commit_ref(
            tenant_id=plan.tenant_id,
            projection_id=plan.projection_id,
            target_ref=plan.target_ref,
            table_identifier=target.table_identifier,
            warehouse_uri=target.warehouse_uri,
            artifact_sha256=target.artifact_sha256,
            action=plan.action,
            plan_sha256=plan.plan_sha256,
            idempotency_key=plan.plan_idempotency_key,
            deleted_snapshot_id=(
                evidence.deleted_snapshot_id if plan.action == "delete" else None
            ),
            drop_evidence_sha256=(
                evidence.drop_evidence_sha256 if plan.action == "delete" else None
            ),
        )
        provider_commit = (
            str(evidence.snapshot_id)
            if evidence.snapshot_id is not None
            else evidence.drop_evidence_sha256 or "missing"
        )
        commit_ref.update(
            {
                "provider_commit": provider_commit,
                "snapshot_id": evidence.snapshot_id,
            }
        )
        if evidence.deleted_snapshot_id is not None:
            commit_ref["deleted_snapshot_id"] = evidence.deleted_snapshot_id
            commit_ref["drop_evidence_sha256"] = evidence.drop_evidence_sha256
            commit_ref["tombstone_plan_sha256"] = evidence.tombstone_plan_sha256
            commit_ref["tombstone_idempotency_key"] = evidence.tombstone_idempotency_key
        if evidence.provider_receipt_sha256 is not None:
            commit_ref["receipt_sha256"] = evidence.provider_receipt_sha256
        return commit_ref

    @staticmethod
    def _expected_receipt_sha256(
        plan: ProjectionRepairPlan,
        commit_ref: Mapping[str, Any],
    ) -> str:
        desired = plan.desired_state
        return lakehouse_projection_receipt_fingerprint(
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
        )

    def _assert_provider_receipt(
        self,
        target: LakehouseProjectionTarget,
        plan: ProjectionRepairPlan,
        observation: ProjectionTargetObservation,
        evidence: LakehouseSnapshotEvidence,
    ) -> dict[str, Any]:
        if plan.action not in {"rebuild", "delete"}:
            raise LakehouseProjectionValidationError(
                "checkpoint actions do not produce an Iceberg provider receipt"
            )
        if (
            evidence.provider_receipt_schema != "gda.iceberg-provider-receipt.v1"
            or evidence.provider_receipt_action != plan.action
            or evidence.provider_receipt_plan_sha256 != plan.plan_sha256
            or evidence.provider_receipt_idempotency_key != plan.plan_idempotency_key
            or evidence.provider_receipt_sha256 is None
        ):
            raise LakehouseProjectionValidationError(
                "stored Iceberg provider receipt is not bound to the sealed plan"
            )
        desired = plan.desired_state
        if (
            observation.target_exists != desired.target_exists
            or observation.observed_content_sha256 != desired.expected_target_content_sha256
            or observation.observed_row_count != desired.expected_row_count
        ):
            raise LakehouseProjectionValidationError(
                "stored Iceberg provider receipt does not match the current target"
            )
        if plan.action == "delete" and (
            evidence.tombstone_plan_sha256 != plan.plan_sha256
            or evidence.tombstone_idempotency_key != plan.plan_idempotency_key
        ):
            raise LakehouseProjectionValidationError(
                "stored Iceberg delete receipt lacks matching tombstone evidence"
            )
        commit_ref = self._commit_ref(target, plan, evidence)
        if evidence.provider_receipt_sha256 != self._expected_receipt_sha256(
            plan, commit_ref
        ):
            raise LakehouseProjectionValidationError(
                "stored Iceberg provider receipt fingerprint differs from the sealed plan"
            )
        return commit_ref

    def recover_receipt(
        self,
        plan: ProjectionRepairPlan,
    ) -> LakehouseProjectionRepairReceipt | None:
        """Recover snapshot-bound provider evidence without replaying a mutation."""
        target = self.registry.resolve(
            tenant_id=plan.tenant_id,
            projection_id=plan.projection_id,
            target_ref=plan.target_ref,
        )
        self._assert_plan(plan, target)
        if plan.action == "checkpoint":
            return None
        observation, evidence = self.observe_versioned(target)
        if evidence.provider_receipt_sha256 is None:
            return None
        receipt_matches_plan = (
            evidence.provider_receipt_schema == "gda.iceberg-provider-receipt.v1"
            and evidence.provider_receipt_action == plan.action
            and evidence.provider_receipt_plan_sha256 == plan.plan_sha256
            and evidence.provider_receipt_idempotency_key == plan.plan_idempotency_key
        )
        if not receipt_matches_plan:
            desired = plan.desired_state
            already_desired = (
                observation.target_exists == desired.target_exists
                and observation.observed_content_sha256
                == desired.expected_target_content_sha256
                and observation.observed_row_count == desired.expected_row_count
            )
            if already_desired:
                raise LakehouseProjectionValidationError(
                    "stored Iceberg provider receipt is not bound to the sealed plan"
                )
            return None
        commit_ref = self._assert_provider_receipt(
            target,
            plan,
            observation,
            evidence,
        )
        return LakehouseProjectionRepairReceipt(
            status="replayed",
            tenant_id=plan.tenant_id,
            projection_id=plan.projection_id,
            target_ref=plan.target_ref,
            action=plan.action,
            plan_sha256=plan.plan_sha256,
            idempotency_key=plan.plan_idempotency_key,
            provider_commit_ref=commit_ref,
            target_exists=observation.target_exists,
            target_content_sha256=observation.observed_content_sha256,
            target_row_count=observation.observed_row_count,
            snapshot_id=evidence.snapshot_id,
            deleted_snapshot_id=evidence.deleted_snapshot_id,
            drop_evidence_sha256=evidence.drop_evidence_sha256,
            observed_at=datetime.now(UTC),
        )

    def execute(
        self,
        plan: ProjectionRepairPlan,
        *,
        observed_at: datetime | None = None,
    ) -> LakehouseProjectionRepairReceipt:
        target = self.registry.resolve(
            tenant_id=plan.tenant_id,
            projection_id=plan.projection_id,
            target_ref=plan.target_ref,
        )
        self._assert_plan(plan, target)
        now = observed_at or datetime.now(UTC)
        if now.tzinfo is None or now.utcoffset() is None:
            raise LakehouseProjectionValidationError("observed_at must be timezone-aware")
        now = now.astimezone(UTC)
        stored_receipt = self.recover_receipt(plan)
        if stored_receipt is not None:
            return stored_receipt
        current, current_snapshot = self.observe_versioned(target)
        desired = plan.desired_state
        if (
            not desired.target_exists
            and current_snapshot.drop_evidence_sha256 is not None
            and (
                current_snapshot.tombstone_plan_sha256 != plan.plan_sha256
                or current_snapshot.tombstone_idempotency_key != plan.plan_idempotency_key
            )
        ):
            raise LakehouseProjectionValidationError(
                "Iceberg tombstone is not bound to the submitted repair plan"
            )
        already_desired = (
            current.target_exists == desired.target_exists
            and current.observed_content_sha256 == desired.expected_target_content_sha256
            and current.observed_row_count == desired.expected_row_count
        )
        if already_desired:
            if plan.action != "checkpoint":
                raise LakehouseProjectionValidationError(
                    "desired Iceberg state lacks a plan-bound provider receipt"
                )
            status = "checkpointed"
            post = current
            post_snapshot = current_snapshot
            commit_ref = self._commit_ref(target, plan, post_snapshot)
        else:
            self._assert_observation(plan, current)
            if plan.action == "checkpoint":
                raise LakehouseProjectionValidationError(
                    "checkpoint target does not match desired Iceberg state"
                )
            try:
                if plan.action == "delete":
                    if current_snapshot.snapshot_id is None:
                        raise LakehouseProjectionValidationError(
                            "Iceberg delete plan lacks a current snapshot"
                        )
                    drop_evidence_sha256 = lakehouse_projection_drop_evidence_sha256(
                        table_identifier=target.table_identifier,
                        deleted_snapshot_id=current_snapshot.snapshot_id,
                        plan_sha256=plan.plan_sha256,
                        idempotency_key=plan.plan_idempotency_key,
                    )
                    pending_ref = lakehouse_projection_stable_commit_ref(
                        tenant_id=plan.tenant_id,
                        projection_id=plan.projection_id,
                        target_ref=plan.target_ref,
                        table_identifier=target.table_identifier,
                        warehouse_uri=target.warehouse_uri,
                        artifact_sha256=target.artifact_sha256,
                        action=plan.action,
                        plan_sha256=plan.plan_sha256,
                        idempotency_key=plan.plan_idempotency_key,
                        deleted_snapshot_id=current_snapshot.snapshot_id,
                        drop_evidence_sha256=drop_evidence_sha256,
                    )
                    receipt_sha256 = self._expected_receipt_sha256(plan, pending_ref)
                    mutation = self.provider.drop(
                        target,
                        plan_sha256=plan.plan_sha256,
                        idempotency_key=plan.plan_idempotency_key,
                        receipt_sha256=receipt_sha256,
                    )
                    status = "deleted"
                else:
                    records = self._load_records(target)
                    if (
                        desired.source_content_sha256 != target.artifact_sha256
                        or desired.expected_target_content_sha256
                        != target.expected_table_content_sha256
                        or desired.expected_row_count != target.expected_row_count
                    ):
                        raise LakehouseProjectionValidationError(
                            "registered customer rows do not match desired Iceberg state"
                        )
                    pending_ref = lakehouse_projection_stable_commit_ref(
                        tenant_id=plan.tenant_id,
                        projection_id=plan.projection_id,
                        target_ref=plan.target_ref,
                        table_identifier=target.table_identifier,
                        warehouse_uri=target.warehouse_uri,
                        artifact_sha256=target.artifact_sha256,
                        action=plan.action,
                        plan_sha256=plan.plan_sha256,
                        idempotency_key=plan.plan_idempotency_key,
                    )
                    receipt_sha256 = self._expected_receipt_sha256(plan, pending_ref)
                    mutation = self.provider.replace(
                        target,
                        records,
                        plan_sha256=plan.plan_sha256,
                        idempotency_key=plan.plan_idempotency_key,
                        receipt_sha256=receipt_sha256,
                    )
                    status = "completed"
            except LakehouseProjectionExecutionError:
                raise
            except Exception as exc:
                raise LakehouseProjectionExecutionError("Iceberg provider mutation failed") from exc
            post, observed_mutation = self.observe_versioned(target)
            if plan.action == "delete":
                post_snapshot = mutation
                if (
                    observed_mutation.target_exists
                    or mutation.target_exists
                    or mutation != observed_mutation
                ):
                    raise LakehouseProjectionExecutionError(
                        "Iceberg drop evidence differs from the post-repair observation"
                    )
            else:
                post_snapshot = observed_mutation
                if mutation != observed_mutation:
                    raise LakehouseProjectionExecutionError(
                        "Iceberg post-repair snapshot differs from the provider commit"
                    )
            commit_ref = self._assert_provider_receipt(
                target,
                plan,
                post,
                post_snapshot,
            )
        if (
            post.target_exists != desired.target_exists
            or post.observed_content_sha256 != desired.expected_target_content_sha256
            or post.observed_row_count != desired.expected_row_count
        ):
            raise LakehouseProjectionExecutionError(
                "Iceberg post-repair observation does not match desired state"
            )
        return LakehouseProjectionRepairReceipt(
            status=status,
            tenant_id=plan.tenant_id,
            projection_id=plan.projection_id,
            target_ref=plan.target_ref,
            action=plan.action,
            plan_sha256=plan.plan_sha256,
            idempotency_key=plan.plan_idempotency_key,
            provider_commit_ref=commit_ref,
            target_exists=post.target_exists,
            target_content_sha256=post.observed_content_sha256,
            target_row_count=post.observed_row_count,
            snapshot_id=post_snapshot.snapshot_id,
            deleted_snapshot_id=post_snapshot.deleted_snapshot_id,
            drop_evidence_sha256=post_snapshot.drop_evidence_sha256,
            observed_at=now,
        )


__all__ = [
    "LakehouseProjectionConfigurationError",
    "LakehouseProjectionExecutionError",
    "LakehouseProjectionProvider",
    "LakehouseProjectionRepairExecutor",
    "LakehouseProjectionRepairReceipt",
    "LakehouseProjectionTarget",
    "LakehouseProjectionTargetRegistry",
    "LakehouseProjectionValidationError",
    "LakehouseSnapshotEvidence",
    "lakehouse_projection_drop_evidence_sha256",
    "lakehouse_projection_receipt_fingerprint",
    "lakehouse_projection_stable_commit_ref",
    "lakehouse_records_from_artifact",
]
