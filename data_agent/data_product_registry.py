"""Governed DataProductVersion publication, discovery, and rollback."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, SQLAlchemyError

from .data_architecture_ledger import (
    DataArchitectureRegistration,
    DataContractVersion,
    PhysicalLocation,
    ResourceVersionArchitectureBinding,
    SchemaVersion,
)
from .db_engine import get_engine
from .platform_contracts import (
    ApprovalCase,
    ApprovalCaseStatus,
    Artifact,
    LineageEvent,
    ResourceVersion,
    TenantId,
    canonical_json_fingerprint,
)

GATEWAY_DATABASE_ROLE = "gda_control_gateway"
_PRODUCT_URN_RE = re.compile(
    r"^gda://[a-z0-9][a-z0-9._-]{0,63}/data_product/[a-z0-9][a-z0-9._-]{0,127}$"
)


class DataProductRegistryError(RuntimeError):
    """Base registry error."""


class DataProductConflictError(DataProductRegistryError):
    """An immutable identity is already bound to different content."""


class DataProductPromotionImpactError(DataProductConflictError):
    """Promotion needs acknowledgement of the latest consumer impact."""

    def __init__(self, impact: dict[str, Any]):
        super().__init__(
            "promotion requires acknowledgement of the latest consumer impact"
        )
        self.impact = impact


class DataProductNotFoundError(DataProductRegistryError):
    """The requested product or version does not exist."""


class DataProductConfigurationError(DataProductRegistryError):
    """The PostgreSQL gateway role is unavailable."""


class DataProductSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tenant_id: TenantId
    product_urn: str
    product_slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,127}$")
    title: str = Field(min_length=1, max_length=512)
    description: str = Field(min_length=1, max_length=4000)
    domain: str = Field(min_length=1, max_length=256)
    owner_ref: str = Field(min_length=1, max_length=512)
    governance_ref: dict[str, Any]
    created_at: datetime

    @field_validator("product_urn")
    @classmethod
    def _valid_product_urn(cls, value: str) -> str:
        if not _PRODUCT_URN_RE.fullmatch(value):
            raise ValueError("product_urn must use gda://{tenant}/data_product/{id}")
        return value

    @field_validator("created_at")
    @classmethod
    def _aware_created_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _consistent_product(self) -> DataProductSpec:
        if self.product_urn.split("/")[2] != self.tenant_id:
            raise ValueError("product_urn tenant must match tenant_id")
        required = {"classification", "visibility", "license_id", "attribution"}
        missing = sorted(required - self.governance_ref.keys())
        if missing or any(not str(self.governance_ref[key]).strip() for key in required):
            raise ValueError(f"governance_ref is missing required values: {missing}")
        return self


class DataProductVersionSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tenant_id: TenantId
    data_product_version_id: UUID
    product_urn: str
    version_key: str = Field(pattern=r"^v[0-9]+\.[0-9]+\.[0-9]+$")
    predecessor_version_id: UUID | None = None
    source_resource_version_id: UUID
    output_resource_version_id: UUID
    standard_version_ref: str = Field(min_length=1, max_length=512)
    mapping_contract: dict[str, Any]
    quality_contract: dict[str, Any]
    quality_evidence_artifact_id: UUID
    distribution_manifest: dict[str, Any]
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    published_by: str = Field(min_length=1, max_length=512)
    published_at: datetime

    @field_validator("published_at")
    @classmethod
    def _aware_published_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("published_at must include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _consistent_version(self) -> DataProductVersionSpec:
        if not _PRODUCT_URN_RE.fullmatch(self.product_urn):
            raise ValueError("invalid product_urn")
        if self.product_urn.split("/")[2] != self.tenant_id:
            raise ValueError("product_urn tenant must match tenant_id")
        if self.source_resource_version_id == self.output_resource_version_id:
            raise ValueError("source and output resource versions must differ")
        if self.predecessor_version_id == self.data_product_version_id:
            raise ValueError("a version cannot be its own predecessor")
        if self.quality_contract.get("verdict") != "passed":
            raise ValueError("only a passed quality contract can create a DataProductVersion")
        expected = data_product_manifest_fingerprint(self)
        if self.manifest_sha256 != expected:
            raise ValueError("manifest_sha256 does not match the version contract")
        return self


def data_product_manifest_fingerprint(version: DataProductVersionSpec | dict[str, Any]) -> str:
    """Fingerprint the immutable product contract, excluding its fingerprint."""
    if isinstance(version, BaseModel):
        payload = version.model_dump(mode="python", exclude={"manifest_sha256"})
    else:
        payload = {key: value for key, value in version.items() if key != "manifest_sha256"}
    return canonical_json_fingerprint(_canonical_contract_value(payload))


def _canonical_contract_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _canonical_contract_value(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_canonical_contract_value(item) for item in value]
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    return value


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _json_value(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def _build_promotion_impact(
    product: dict[str, Any],
    target: dict[str, Any],
    rows: list[Any],
) -> dict[str, Any]:
    impacted_grants: list[dict[str, Any]] = []
    for row in rows:
        value = dict(row)
        expiry = value.get("expires_at")
        impacted_grants.append(
            {
                "request_id": int(value["request_id"]),
                "requester": str(value.get("requester") or ""),
                "asset_id": int(value["asset_id"]),
                "locked_version_key": str(value.get("locked_version_key") or ""),
                "expires_at": expiry.isoformat() if hasattr(expiry, "isoformat") else expiry,
                "granted_package_quota": int(
                    value.get("granted_package_quota") or 0
                ),
                "packages_created": int(value.get("packages_created") or 0),
                "packages_remaining": int(value.get("packages_remaining") or 0),
            }
        )
    impacted_grants.sort(key=lambda item: (item["requester"], item["request_id"]))
    impacted_consumers = sorted(
        {item["requester"] for item in impacted_grants if item["requester"]}
    )
    evidence = {
        "schema": "gda.data_product_promotion_impact.v1",
        "tenant_id": str(product["tenant_id"]),
        "product_urn": str(product["product_urn"]),
        "from_version": {
            "data_product_version_id": str(product["current_version_id"]),
            "version_key": str(product["current_version_key"]),
        },
        "to_version": {
            "data_product_version_id": str(target["data_product_version_id"]),
            "version_key": str(target["version_key"]),
        },
        "active_grant_count": len(impacted_grants),
        "impacted_consumer_count": len(impacted_consumers),
        "remaining_package_quota": sum(
            item["packages_remaining"] for item in impacted_grants
        ),
        "impacted_grants": impacted_grants,
    }
    acknowledgement_required = bool(impacted_grants)
    return {
        **evidence,
        "impacted_consumers": impacted_consumers,
        "impact_fingerprint": canonical_json_fingerprint(evidence),
        "acknowledgement_required": acknowledgement_required,
        "promotion_ready": not acknowledgement_required,
    }


class DataProductRegistry:
    """Tenant-scoped PostgreSQL registry using the existing gateway role."""

    def __init__(self, engine=None):
        self._engine = engine

    def _get_engine(self):
        engine = self._engine or get_engine()
        if engine is None or engine.dialect.name != "postgresql":
            raise DataProductConfigurationError("data product registry requires PostgreSQL")
        return engine

    @contextmanager
    def _transaction(self, tenant_id: str) -> Iterator[Any]:
        try:
            with self._get_engine().connect() as connection:
                with connection.begin():
                    try:
                        connection.exec_driver_sql(f'SET LOCAL ROLE "{GATEWAY_DATABASE_ROLE}"')
                    except DBAPIError as exc:
                        raise DataProductConfigurationError(
                            "database login is not a member of the platform gateway role"
                        ) from exc
                    connection.execute(
                        text("SELECT set_config('app.current_tenant', :tenant, true)"),
                        {"tenant": tenant_id},
                    )
                    yield connection
        except DataProductRegistryError:
            raise
        except (DBAPIError, SQLAlchemyError) as exc:
            raise DataProductRegistryError("data product database operation failed") from exc

    @staticmethod
    def _load_product(connection, tenant_id: str, product_slug: str) -> dict[str, Any] | None:
        row = connection.execute(
            text(
                """
                SELECT p.tenant_id, p.product_urn, p.product_slug, p.title,
                       p.description, p.domain, p.owner_ref, p.governance_ref,
                       p.current_version_id, p.created_at, p.updated_at,
                       v.version_key AS current_version_key,
                       v.manifest_sha256 AS current_manifest_sha256,
                       v.published_at AS current_version_published_at,
                       v.quality_contract AS current_quality,
                       v.distribution_manifest AS current_distribution
                  FROM gda_control.data_product p
                  LEFT JOIN gda_control.data_product_version v
                    ON v.tenant_id = p.tenant_id
                   AND v.data_product_version_id = p.current_version_id
                 WHERE p.tenant_id = :tenant_id AND p.product_slug = :product_slug
                """
            ),
            {"tenant_id": tenant_id, "product_slug": product_slug},
        ).mappings().one_or_none()
        if row is None:
            return None
        value = dict(row)
        for key in ("governance_ref", "current_quality", "current_distribution"):
            value[key] = _json_value(value[key]) if value[key] is not None else None
        return _json_safe(value)

    @staticmethod
    def _load_version(
        connection, tenant_id: str, product_urn: str, version_key: str
    ) -> dict[str, Any] | None:
        row = connection.execute(
            text(
                """
                SELECT * FROM gda_control.data_product_version
                 WHERE tenant_id = :tenant_id
                   AND product_urn = :product_urn
                   AND version_key = :version_key
                """
            ),
            {
                "tenant_id": tenant_id,
                "product_urn": product_urn,
                "version_key": version_key,
            },
        ).mappings().one_or_none()
        if row is None:
            return None
        value = dict(row)
        for key in ("mapping_contract", "quality_contract", "distribution_manifest"):
            value[key] = _json_value(value[key])
        return _json_safe(value)

    @staticmethod
    def _load_version_by_id(
        connection,
        tenant_id: str,
        product_urn: str,
        data_product_version_id: UUID,
    ) -> dict[str, Any] | None:
        row = connection.execute(
            text(
                """
                SELECT * FROM gda_control.data_product_version
                 WHERE tenant_id = :tenant_id
                   AND product_urn = :product_urn
                   AND data_product_version_id = :data_product_version_id
                """
            ),
            {
                "tenant_id": tenant_id,
                "product_urn": product_urn,
                "data_product_version_id": data_product_version_id,
            },
        ).mappings().one_or_none()
        if row is None:
            return None
        value = dict(row)
        for key in ("mapping_contract", "quality_contract", "distribution_manifest"):
            value[key] = _json_value(value[key])
        return _json_safe(value)

    @staticmethod
    def _load_approval_case(
        connection, tenant_id: str, approval_case_ref: str
    ) -> ApprovalCase | None:
        row = connection.execute(
            text(
                """
                SELECT tenant_id, approval_case_ref, target_resource_urn,
                       target_fingerprint, action, requester_subject,
                       request_reason, request_context, status, state_version,
                       requested_at, expires_at, decided_by,
                       decision_reason, decided_at
                  FROM gda_control.approval_case
                 WHERE tenant_id = :tenant_id
                   AND approval_case_ref = :approval_case_ref
                """
            ),
            {"tenant_id": tenant_id, "approval_case_ref": approval_case_ref},
        ).mappings().one_or_none()
        if row is None:
            return None
        value = dict(row)
        value["request_context"] = _json_value(value["request_context"])
        return ApprovalCase.model_validate(value)

    @staticmethod
    def _load_resource_version(
        connection, tenant_id: str, resource_version_id: UUID
    ) -> ResourceVersion | None:
        row = connection.execute(
            text(
                """
                SELECT tenant_id, resource_urn, resource_version_id, version_key,
                       predecessor_version_id, content_sha256,
                       authority_version_ref, created_by, created_at
                  FROM gda_control.resource_version
                 WHERE tenant_id = :tenant_id
                   AND resource_version_id = :resource_version_id
                """
            ),
            {
                "tenant_id": tenant_id,
                "resource_version_id": resource_version_id,
            },
        ).mappings().one_or_none()
        if row is None:
            return None
        value = dict(row)
        value["authority_version_ref"] = _json_value(value["authority_version_ref"])
        return ResourceVersion.model_validate(value)

    @staticmethod
    def _load_artifact(
        connection, tenant_id: str, artifact_id: UUID
    ) -> Artifact | None:
        row = connection.execute(
            text(
                """
                SELECT tenant_id, artifact_id, artifact_key, artifact_role,
                       storage_uri, media_type, content_sha256, size_bytes,
                       run_id, resource_version_id, manifest, created_by, created_at
                  FROM gda_control.artifact
                 WHERE tenant_id = :tenant_id AND artifact_id = :artifact_id
                """
            ),
            {"tenant_id": tenant_id, "artifact_id": artifact_id},
        ).mappings().one_or_none()
        if row is None:
            return None
        value = dict(row)
        value["manifest"] = _json_value(value["manifest"])
        return Artifact.model_validate(value)

    @staticmethod
    def _load_architecture_registration(
        connection, tenant_id: str, resource_version_id: UUID
    ) -> DataArchitectureRegistration | None:
        schema = connection.execute(
            text(
                """
                SELECT tenant_id, schema_version_id, resource_version_id,
                       schema_format, authority_system, authority_namespace,
                       authority_object_id, authority_version_ref, schema_sha256,
                       created_by, created_at
                  FROM gda_control.schema_version
                 WHERE tenant_id = :tenant_id
                   AND resource_version_id = :resource_version_id
                """
            ),
            {"tenant_id": tenant_id, "resource_version_id": resource_version_id},
        ).mappings().one_or_none()
        contract = connection.execute(
            text(
                """
                SELECT tenant_id, data_contract_version_id, resource_version_id,
                       contract_kind, enforcement_mode, authority_system,
                       authority_namespace, authority_object_id,
                       authority_version_ref, contract_sha256,
                       created_by, created_at
                  FROM gda_control.data_contract_version
                 WHERE tenant_id = :tenant_id
                   AND resource_version_id = :resource_version_id
                """
            ),
            {"tenant_id": tenant_id, "resource_version_id": resource_version_id},
        ).mappings().one_or_none()
        location = connection.execute(
            text(
                """
                SELECT tenant_id, physical_location_id, resource_version_id,
                       location_kind, provider_system, provider_namespace,
                       provider_locator, snapshot_ref, revision_ref,
                       checksum_algorithm, content_checksum, location_sha256,
                       created_by, created_at
                  FROM gda_control.physical_location
                 WHERE tenant_id = :tenant_id
                   AND resource_version_id = :resource_version_id
                """
            ),
            {"tenant_id": tenant_id, "resource_version_id": resource_version_id},
        ).mappings().one_or_none()
        binding = connection.execute(
            text(
                """
                SELECT tenant_id, resource_version_id, schema_version_id,
                       data_contract_version_id, physical_location_id,
                       binding_sha256, bound_by, bound_at
                  FROM gda_control.resource_version_architecture_binding
                 WHERE tenant_id = :tenant_id
                   AND resource_version_id = :resource_version_id
                """
            ),
            {"tenant_id": tenant_id, "resource_version_id": resource_version_id},
        ).mappings().one_or_none()
        if any(value is None for value in (schema, contract, location, binding)):
            return None
        return DataArchitectureRegistration(
            schema_version=SchemaVersion.model_validate(dict(schema)),
            data_contract_version=DataContractVersion.model_validate(dict(contract)),
            physical_location=PhysicalLocation.model_validate(dict(location)),
            binding=ResourceVersionArchitectureBinding.model_validate(dict(binding)),
        )

    @staticmethod
    def _load_lineage_event(
        connection, tenant_id: str, lineage_event_id: UUID
    ) -> LineageEvent | None:
        row = connection.execute(
            text(
                """
                SELECT tenant_id, lineage_event_id, event_type,
                       source_resource_version_id, target_resource_version_id,
                       run_id, definition_version_id, artifact_id, producer,
                       event_sha256, facets, occurred_at
                  FROM gda_control.lineage_event
                 WHERE tenant_id = :tenant_id
                   AND lineage_event_id = :lineage_event_id
                """
            ),
            {"tenant_id": tenant_id, "lineage_event_id": lineage_event_id},
        ).mappings().one_or_none()
        if row is None:
            return None
        value = dict(row)
        value["facets"] = _json_value(value["facets"])
        return LineageEvent.model_validate(value)

    @staticmethod
    def _load_architecture_release_binding(
        connection, tenant_id: str, data_product_version_id: UUID
    ) -> dict[str, Any] | None:
        row = connection.execute(
            text(
                """
                SELECT tenant_id, data_product_version_id, product_urn,
                       predecessor_data_product_version_id,
                       predecessor_output_resource_version_id,
                       successor_output_resource_version_id,
                       architecture_adoption_case_ref,
                       architecture_successor_plan_sha256,
                       release_approval_case_ref, release_plan_sha256,
                       architecture_binding_sha256,
                       quality_evidence_artifact_id,
                       distribution_artifact_ids, rollback_target_version_id,
                       bound_by, bound_at
                  FROM gda_control.data_product_architecture_release
                 WHERE tenant_id = :tenant_id
                   AND data_product_version_id = :data_product_version_id
                """
            ),
            {
                "tenant_id": tenant_id,
                "data_product_version_id": data_product_version_id,
            },
        ).mappings().one_or_none()
        if row is None:
            return None
        value = _json_safe(dict(row))
        value["distribution_artifact_ids"] = _json_value(
            value["distribution_artifact_ids"]
        )
        return value

    @staticmethod
    def _lock_promotion_scope(
        connection, tenant_id: str, product_urn: str
    ) -> None:
        connection.execute(
            text(
                "SELECT pg_advisory_xact_lock("
                "hashtextextended(:promotion_scope, 0))"
            ),
            {
                "promotion_scope": (
                    f"data-product-promotion:{tenant_id}:{product_urn}"
                )
            },
        )

    @staticmethod
    def _architecture_release_binding_values(
        plan: Any,
        release_approval_case_ref: str,
    ) -> dict[str, Any]:
        successor = plan.successor_data_product_version
        predecessor = plan.predecessor_data_product_version
        architecture_plan = plan.architecture_successor_plan
        return {
            "tenant_id": str(plan.tenant_id),
            "data_product_version_id": str(successor.data_product_version_id),
            "product_urn": plan.product_urn,
            "predecessor_data_product_version_id": str(
                predecessor.data_product_version_id
            ),
            "predecessor_output_resource_version_id": str(
                predecessor.output_resource_version_id
            ),
            "successor_output_resource_version_id": str(
                successor.output_resource_version_id
            ),
            "architecture_adoption_case_ref": (
                plan.architecture_adoption_case.approval_case_ref
            ),
            "architecture_successor_plan_sha256": architecture_plan.plan_sha256,
            "release_approval_case_ref": release_approval_case_ref,
            "release_plan_sha256": plan.plan_sha256,
            "architecture_binding_sha256": (
                architecture_plan.successor_architecture.binding.binding_sha256
            ),
            "quality_evidence_artifact_id": str(
                plan.quality_evidence_artifact.artifact_id
            ),
            "distribution_artifact_ids": [
                str(artifact.artifact_id) for artifact in plan.distribution_artifacts
            ],
            "rollback_target_version_id": str(plan.rollback_target_version_id),
            "bound_by": successor.published_by,
            "bound_at": successor.published_at.astimezone(UTC).isoformat(),
        }

    def _validate_live_architecture_release(
        self,
        connection,
        *,
        plan: Any,
        release_approval_case_ref: str,
        require_publish_pointer: bool,
    ) -> dict[str, Any]:
        from .architecture_successor_data_product_release import (
            ARCHITECTURE_SUCCESSOR_RELEASE_ACTION,
            ArchitectureSuccessorDataProductReleasePlan,
            build_architecture_successor_release_approval_case,
        )

        if not isinstance(plan, ArchitectureSuccessorDataProductReleasePlan):
            raise DataProductConflictError(
                "architecture release requires a typed immutable release plan"
            )
        tenant_id = str(plan.tenant_id)
        product = plan.product
        predecessor = plan.predecessor_data_product_version
        successor = plan.successor_data_product_version
        stored_product = self._load_product(
            connection,
            tenant_id,
            product.product_slug,
        )
        if (
            stored_product is None
            or _product_binding(stored_product)
            != _product_binding(product.model_dump(mode="json"))
        ):
            raise DataProductConflictError(
                "architecture release product is not the registered immutable product"
            )
        current_id = _optional_uuid_text(stored_product["current_version_id"])
        allowed_pointer_ids = {str(predecessor.data_product_version_id)}
        if self._load_version_by_id(
            connection,
            tenant_id,
            plan.product_urn,
            successor.data_product_version_id,
        ) is not None:
            allowed_pointer_ids.add(str(successor.data_product_version_id))
        if require_publish_pointer and current_id not in allowed_pointer_ids:
            raise DataProductConflictError(
                "architecture release predecessor is no longer the product pointer"
            )
        stored_predecessor = self._load_version_by_id(
            connection,
            tenant_id,
            plan.product_urn,
            predecessor.data_product_version_id,
        )
        if (
            stored_predecessor is None
            or _version_binding(stored_predecessor)
            != _version_binding(predecessor.model_dump(mode="json"))
        ):
            raise DataProductConflictError(
                "architecture release predecessor product version changed or is missing"
            )

        architecture_plan = plan.architecture_successor_plan
        stored_output = self._load_resource_version(
            connection,
            tenant_id,
            successor.output_resource_version_id,
        )
        stored_architecture = self._load_architecture_registration(
            connection,
            tenant_id,
            successor.output_resource_version_id,
        )
        stored_lineage = self._load_lineage_event(
            connection,
            tenant_id,
            architecture_plan.lineage_event.lineage_event_id,
        )
        if (
            stored_output != architecture_plan.successor_resource_version
            or stored_architecture != architecture_plan.successor_architecture
            or stored_lineage != architecture_plan.lineage_event
        ):
            raise DataProductConflictError(
                "adopted successor architecture is incomplete or differs from the release plan"
            )

        adoption_case = self._load_approval_case(
            connection,
            tenant_id,
            plan.architecture_adoption_case.approval_case_ref,
        )
        if (
            adoption_case != plan.architecture_adoption_case
            or adoption_case is None
            or adoption_case.status is not ApprovalCaseStatus.APPROVED
        ):
            raise DataProductConflictError(
                "architecture adoption ApprovalCase is not the approved release evidence"
            )

        release_case = self._load_approval_case(
            connection,
            tenant_id,
            release_approval_case_ref,
        )
        if release_case is None:
            raise DataProductConflictError(
                "architecture successor release ApprovalCase was not found"
            )
        expected_release_case = build_architecture_successor_release_approval_case(
            plan,
            requester_subject=release_case.requester_subject,
            request_reason=release_case.request_reason,
            requested_at=release_case.requested_at,
            expires_at=release_case.expires_at,
        )
        if (
            release_case.status is not ApprovalCaseStatus.APPROVED
            or release_case.action != ARCHITECTURE_SUCCESSOR_RELEASE_ACTION
            or _approval_request_binding(release_case)
            != _approval_request_binding(expected_release_case)
            or release_case.decided_at is None
            or release_case.decided_at > successor.published_at
        ):
            raise DataProductConflictError(
                "release ApprovalCase is not an approved plan binding"
            )

        quality = self._load_artifact(
            connection,
            tenant_id,
            plan.quality_evidence_artifact.artifact_id,
        )
        if quality != plan.quality_evidence_artifact:
            raise DataProductConflictError(
                "quality evidence Artifact differs from the approved release plan"
            )
        for artifact in plan.distribution_artifacts:
            if self._load_artifact(connection, tenant_id, artifact.artifact_id) != artifact:
                raise DataProductConflictError(
                    "distribution Artifact differs from the approved release plan"
                )
        return self._architecture_release_binding_values(
            plan,
            release_approval_case_ref,
        )

    def _put_architecture_release_binding(
        self,
        connection,
        values: dict[str, Any],
    ) -> bool:
        inserted = connection.execute(
            text(
                """
                INSERT INTO gda_control.data_product_architecture_release (
                    tenant_id, data_product_version_id, product_urn,
                    predecessor_data_product_version_id,
                    predecessor_output_resource_version_id,
                    successor_output_resource_version_id,
                    architecture_adoption_case_ref,
                    architecture_successor_plan_sha256,
                    release_approval_case_ref, release_plan_sha256,
                    architecture_binding_sha256,
                    quality_evidence_artifact_id,
                    distribution_artifact_ids, rollback_target_version_id,
                    bound_by, bound_at
                ) VALUES (
                    :tenant_id, CAST(:data_product_version_id AS uuid), :product_urn,
                    CAST(:predecessor_data_product_version_id AS uuid),
                    CAST(:predecessor_output_resource_version_id AS uuid),
                    CAST(:successor_output_resource_version_id AS uuid),
                    :architecture_adoption_case_ref,
                    :architecture_successor_plan_sha256,
                    :release_approval_case_ref, :release_plan_sha256,
                    :architecture_binding_sha256,
                    CAST(:quality_evidence_artifact_id AS uuid),
                    CAST(:distribution_artifact_ids AS jsonb),
                    CAST(:rollback_target_version_id AS uuid),
                    :bound_by, :bound_at
                ) ON CONFLICT DO NOTHING
                RETURNING data_product_version_id
                """
            ),
            {
                **values,
                "distribution_artifact_ids": _json(
                    values["distribution_artifact_ids"]
                ),
            },
        ).first()
        stored = self._load_architecture_release_binding(
            connection,
            values["tenant_id"],
            UUID(values["data_product_version_id"]),
        )
        if stored != values:
            raise DataProductConflictError(
                "DataProduct architecture release already has a different immutable binding"
            )
        return inserted is not None

    def _validate_persisted_architecture_release(
        self,
        connection,
        target: dict[str, Any],
    ) -> dict[str, Any] | None:
        from .architecture_successor_data_product_release import (
            ArchitectureSuccessorDataProductReleasePlan,
        )

        tenant_id = str(target["tenant_id"])
        target_id = UUID(str(target["data_product_version_id"]))
        binding = self._load_architecture_release_binding(
            connection,
            tenant_id,
            target_id,
        )
        adopted_successor = bool(
            connection.execute(
                text(
                    """
                    SELECT EXISTS(
                        SELECT 1
                          FROM gda_control.lineage_event
                         WHERE tenant_id = :tenant_id
                           AND target_resource_version_id = :output_version_id
                           AND facets->>'operation' = 'create_successor_version'
                    )
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "output_version_id": target["output_resource_version_id"],
                },
            ).scalar_one()
        )
        if binding is None:
            if adopted_successor:
                raise DataProductConflictError(
                    "adopted architecture successor lacks an approved product release binding"
                )
            return None
        release_case = self._load_approval_case(
            connection,
            tenant_id,
            binding["release_approval_case_ref"],
        )
        if release_case is None:
            raise DataProductConflictError(
                "persisted architecture release ApprovalCase was not found"
            )
        try:
            plan = ArchitectureSuccessorDataProductReleasePlan.model_validate(
                release_case.request_context["release_plan"]
            )
        except (KeyError, ValueError) as exc:
            raise DataProductConflictError(
                "persisted architecture release plan is invalid"
            ) from exc
        expected_binding = self._validate_live_architecture_release(
            connection,
            plan=plan,
            release_approval_case_ref=release_case.approval_case_ref,
            require_publish_pointer=False,
        )
        if binding != expected_binding or _version_binding(target) != _version_binding(
            plan.successor_data_product_version.model_dump(mode="json")
        ):
            raise DataProductConflictError(
                "persisted DataProduct release differs from its approved plan"
            )
        return binding

    @staticmethod
    def _is_descendant(
        connection,
        tenant_id: str,
        product_urn: str,
        current_id: UUID,
        target_id: UUID,
    ) -> bool:
        return bool(
            connection.execute(
                text(
                    """
                    WITH RECURSIVE ancestors AS (
                        SELECT predecessor_version_id AS version_id
                          FROM gda_control.data_product_version
                         WHERE tenant_id = :tenant_id
                           AND product_urn = :product_urn
                           AND data_product_version_id = :target_id
                        UNION ALL
                        SELECT version.predecessor_version_id
                          FROM gda_control.data_product_version version
                          JOIN ancestors
                            ON version.data_product_version_id = ancestors.version_id
                         WHERE version.tenant_id = :tenant_id
                           AND version.product_urn = :product_urn
                           AND ancestors.version_id IS NOT NULL
                    )
                    SELECT EXISTS(
                        SELECT 1 FROM ancestors WHERE version_id = :current_id
                    )
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "product_urn": product_urn,
                    "current_id": current_id,
                    "target_id": target_id,
                },
            ).scalar_one()
        )

    @staticmethod
    def _promotion_impact(
        connection,
        product: dict[str, Any],
        target: dict[str, Any],
    ) -> dict[str, Any]:
        rows = connection.execute(
            text(
                """
                SELECT *
                  FROM gda_control.active_distribution_grant_impact(
                      :tenant_id, :product_urn,
                      CAST(:current_version_id AS uuid)
                  )
                """
            ),
            {
                "tenant_id": product["tenant_id"],
                "product_urn": product["product_urn"],
                "current_version_id": product["current_version_id"],
            },
        ).mappings().all()
        return _build_promotion_impact(product, target, list(rows))

    @staticmethod
    def _record_promotion_impact(
        connection,
        *,
        event_id: UUID,
        impact: dict[str, Any],
        actor_subject: str,
        assessed_at: datetime,
        acknowledgement_mode: str,
    ) -> UUID:
        impact_id = uuid5(
            event_id,
            (
                f"promotion-impact:{impact['impact_fingerprint']}:"
                f"{acknowledgement_mode}"
            ),
        )
        connection.execute(
            text(
                """
                INSERT INTO gda_control.data_product_promotion_impact (
                    tenant_id, impact_id, product_urn,
                    from_version_id, to_version_id, impact_fingerprint,
                    active_grant_count, impacted_consumer_count,
                    remaining_package_quota, impacted_grants,
                    acknowledgement_mode, assessed_by, assessed_at,
                    acknowledged_at
                ) VALUES (
                    :tenant_id, :impact_id, :product_urn,
                    CAST(:from_version_id AS uuid), CAST(:to_version_id AS uuid),
                    :impact_fingerprint, :active_grant_count,
                    :impacted_consumer_count, :remaining_package_quota,
                    CAST(:impacted_grants AS jsonb), :acknowledgement_mode,
                    :assessed_by, :assessed_at, :acknowledged_at
                )
                """
            ),
            {
                "tenant_id": impact["tenant_id"],
                "impact_id": impact_id,
                "product_urn": impact["product_urn"],
                "from_version_id": impact["from_version"][
                    "data_product_version_id"
                ],
                "to_version_id": impact["to_version"][
                    "data_product_version_id"
                ],
                "impact_fingerprint": impact["impact_fingerprint"],
                "active_grant_count": impact["active_grant_count"],
                "impacted_consumer_count": impact["impacted_consumer_count"],
                "remaining_package_quota": impact["remaining_package_quota"],
                "impacted_grants": _json(impact["impacted_grants"]),
                "acknowledgement_mode": acknowledgement_mode,
                "assessed_by": actor_subject,
                "assessed_at": assessed_at,
                "acknowledged_at": (
                    None if acknowledgement_mode == "pending" else assessed_at
                ),
            },
        )
        return impact_id

    @staticmethod
    def _load_recorded_promotion_impact(
        connection,
        tenant_id: str,
        impact_id: UUID | str,
    ) -> dict[str, Any] | None:
        row = connection.execute(
            text(
                """
                SELECT impact.*, source.version_key AS from_version_key,
                       target.version_key AS to_version_key
                  FROM gda_control.data_product_promotion_impact impact
                  JOIN gda_control.data_product_version source
                    ON source.tenant_id = impact.tenant_id
                   AND source.data_product_version_id = impact.from_version_id
                  JOIN gda_control.data_product_version target
                    ON target.tenant_id = impact.tenant_id
                   AND target.data_product_version_id = impact.to_version_id
                 WHERE impact.tenant_id = :tenant_id
                   AND impact.impact_id = CAST(:impact_id AS uuid)
                """
            ),
            {"tenant_id": tenant_id, "impact_id": impact_id},
        ).mappings().one_or_none()
        if row is None:
            return None
        value = dict(row)
        impacted_grants = _json_value(value["impacted_grants"])
        impacted_consumers = sorted(
            {
                str(grant.get("requester") or "")
                for grant in impacted_grants
                if str(grant.get("requester") or "")
            }
        )
        acknowledgement_required = int(value["active_grant_count"]) > 0
        return {
            "schema": "gda.data_product_promotion_impact.v1",
            "tenant_id": str(value["tenant_id"]),
            "product_urn": str(value["product_urn"]),
            "from_version": {
                "data_product_version_id": str(value["from_version_id"]),
                "version_key": str(value["from_version_key"]),
            },
            "to_version": {
                "data_product_version_id": str(value["to_version_id"]),
                "version_key": str(value["to_version_key"]),
            },
            "active_grant_count": int(value["active_grant_count"]),
            "impacted_consumer_count": int(value["impacted_consumer_count"]),
            "remaining_package_quota": int(value["remaining_package_quota"]),
            "impacted_grants": impacted_grants,
            "impacted_consumers": impacted_consumers,
            "impact_fingerprint": str(value["impact_fingerprint"]),
            "acknowledgement_required": acknowledgement_required,
            "promotion_ready": not acknowledgement_required,
        }

    def publish(
        self,
        product: DataProductSpec,
        version: DataProductVersionSpec,
        *,
        idempotency_key: str,
        reason: str,
        architecture_release_plan: Any | None = None,
        release_approval_case_ref: str | None = None,
    ) -> dict[str, Any]:
        """Publish a passed version, deferring activation when consumers exist."""
        if product.tenant_id != version.tenant_id or product.product_urn != version.product_urn:
            raise ValueError("product and version identities must match")
        if not idempotency_key.strip() or not reason.strip():
            raise ValueError("idempotency_key and reason are required")
        if (architecture_release_plan is None) != (release_approval_case_ref is None):
            raise ValueError(
                "architecture release plan and ApprovalCase reference are both required"
            )
        if architecture_release_plan is not None and (
            architecture_release_plan.product != product
            or architecture_release_plan.successor_data_product_version != version
        ):
            raise ValueError("published product and version must match the release plan")
        with self._transaction(product.tenant_id) as connection:
            self._lock_promotion_scope(
                connection,
                str(product.tenant_id),
                product.product_urn,
            )
            architecture_release_values = None
            if architecture_release_plan is not None:
                architecture_release_values = self._validate_live_architecture_release(
                    connection,
                    plan=architecture_release_plan,
                    release_approval_case_ref=str(release_approval_case_ref),
                    require_publish_pointer=True,
                )
            inserted_product = connection.execute(
                text(
                    """
                    INSERT INTO gda_control.data_product (
                        tenant_id, product_urn, product_slug, title, description,
                        domain, owner_ref, governance_ref, created_at, updated_at
                    ) VALUES (
                        :tenant_id, :product_urn, :product_slug, :title, :description,
                        :domain, :owner_ref, CAST(:governance_ref AS jsonb),
                        :created_at, :created_at
                    ) ON CONFLICT DO NOTHING RETURNING product_urn
                    """
                ),
                {
                    **product.model_dump(mode="python", exclude={"governance_ref"}),
                    "governance_ref": _json(product.governance_ref),
                },
            ).first()
            stored_product = self._load_product(
                connection, product.tenant_id, product.product_slug
            )
            if stored_product is None or _product_binding(stored_product) != _product_binding(
                product.model_dump(mode="json")
            ):
                raise DataProductConflictError(
                    "DataProduct identity already has different immutable metadata"
                )

            current_id = stored_product["current_version_id"]
            if current_id is not None and version.predecessor_version_id != UUID(current_id):
                existing = self._load_version(
                    connection, version.tenant_id, version.product_urn, version.version_key
                )
                if existing is None or existing["data_product_version_id"] != str(
                    version.data_product_version_id
                ):
                    raise DataProductConflictError(
                        "new DataProductVersion must name the current version as predecessor"
                    )
            elif current_id is None and version.predecessor_version_id is not None:
                raise DataProductConflictError("the first version cannot have a predecessor")

            inserted_version = connection.execute(
                text(
                    """
                    INSERT INTO gda_control.data_product_version (
                        tenant_id, data_product_version_id, product_urn, version_key,
                        predecessor_version_id, source_resource_version_id,
                        output_resource_version_id, standard_version_ref,
                        mapping_contract, quality_contract, quality_verdict,
                        quality_evidence_artifact_id, distribution_manifest,
                        manifest_sha256, published_by, published_at
                    ) VALUES (
                        :tenant_id, :data_product_version_id, :product_urn, :version_key,
                        :predecessor_version_id, :source_resource_version_id,
                        :output_resource_version_id, :standard_version_ref,
                        CAST(:mapping_contract AS jsonb), CAST(:quality_contract AS jsonb),
                        'passed', :quality_evidence_artifact_id,
                        CAST(:distribution_manifest AS jsonb), :manifest_sha256,
                        :published_by, :published_at
                    ) ON CONFLICT DO NOTHING RETURNING data_product_version_id
                    """
                ),
                {
                    **version.model_dump(
                        mode="python",
                        exclude={"mapping_contract", "quality_contract", "distribution_manifest"},
                    ),
                    "mapping_contract": _json(version.mapping_contract),
                    "quality_contract": _json(version.quality_contract),
                    "distribution_manifest": _json(version.distribution_manifest),
                },
            ).first()
            stored_version = self._load_version(
                connection, version.tenant_id, version.product_urn, version.version_key
            )
            if stored_version is None or _version_binding(stored_version) != _version_binding(
                version.model_dump(mode="json")
            ):
                raise DataProductConflictError(
                    "DataProductVersion identity already has different immutable content"
                )
            architecture_release_created = False
            if architecture_release_values is not None:
                architecture_release_created = self._put_architecture_release_binding(
                    connection,
                    architecture_release_values,
                )
            if inserted_version is None and current_id != str(
                version.data_product_version_id
            ):
                existing_event = connection.execute(
                    text(
                        """
                        SELECT event_id, event_type, from_version_id,
                               to_version_id, promotion_impact_id
                          FROM gda_control.data_product_event
                         WHERE tenant_id = :tenant_id
                           AND product_urn = :product_urn
                           AND idempotency_key = :idempotency_key
                        """
                    ),
                    {
                        "tenant_id": product.tenant_id,
                        "product_urn": product.product_urn,
                        "idempotency_key": idempotency_key,
                    },
                ).mappings().one_or_none()
                if (
                    existing_event is None
                    or existing_event["event_type"] != "staged"
                    or _optional_uuid_text(existing_event["from_version_id"])
                    != _optional_uuid_text(current_id)
                    or str(existing_event["to_version_id"])
                    != str(version.data_product_version_id)
                ):
                    raise DataProductConflictError(
                        "an existing non-current version must be activated with promote"
                    )
                recorded_impact = self._load_recorded_promotion_impact(
                    connection,
                    str(product.tenant_id),
                    existing_event["promotion_impact_id"],
                )
                if recorded_impact is None:
                    raise DataProductRegistryError(
                        "staged publication is missing promotion impact evidence"
                    )
                return {
                    "product": stored_product,
                    "version": stored_version,
                    "product_created": False,
                    "version_created": False,
                    "pointer_changed": False,
                    "event_created": False,
                    "idempotent_replay": True,
                    "promotion_deferred": True,
                    "promotion_impact": recorded_impact,
                    "architecture_release_created": architecture_release_created,
                }

            target_differs = current_id != str(version.data_product_version_id)
            pointer_changed = False
            event_created = False
            promotion_deferred = False
            promotion_impact = None
            if target_differs:
                if current_id is None:
                    event_type = "published"
                else:
                    promotion_impact = self._promotion_impact(
                        connection,
                        stored_product,
                        stored_version,
                    )
                    promotion_deferred = promotion_impact[
                        "acknowledgement_required"
                    ]
                    event_type = "staged" if promotion_deferred else "advanced"
                event_id = uuid5(
                    version.data_product_version_id,
                    f"{event_type}:{idempotency_key}:{current_id or 'none'}",
                )
                promotion_impact_id = None
                if promotion_impact is not None:
                    promotion_impact_id = self._record_promotion_impact(
                        connection,
                        event_id=event_id,
                        impact=promotion_impact,
                        actor_subject=version.published_by,
                        assessed_at=version.published_at,
                        acknowledgement_mode=(
                            "pending" if promotion_deferred else "not_required"
                        ),
                    )
                if not promotion_deferred:
                    connection.execute(
                        text(
                            """
                            UPDATE gda_control.data_product
                               SET current_version_id = :to_version_id,
                                   updated_at = :occurred_at
                             WHERE tenant_id = :tenant_id
                               AND product_urn = :product_urn
                            """
                        ),
                        {
                            "tenant_id": product.tenant_id,
                            "product_urn": product.product_urn,
                            "to_version_id": version.data_product_version_id,
                            "occurred_at": version.published_at,
                        },
                    )
                    pointer_changed = True
                inserted_event = connection.execute(
                    text(
                        """
                        INSERT INTO gda_control.data_product_event (
                            tenant_id, event_id, product_urn, event_type,
                            from_version_id, to_version_id, actor_subject,
                            reason, idempotency_key, occurred_at,
                            promotion_impact_id
                        ) VALUES (
                            :tenant_id, :event_id, :product_urn, :event_type,
                            :from_version_id, :to_version_id, :actor_subject,
                            :reason, :idempotency_key, :occurred_at,
                            :promotion_impact_id
                        ) ON CONFLICT DO NOTHING RETURNING event_id
                        """
                    ),
                    {
                        "tenant_id": product.tenant_id,
                        "event_id": event_id,
                        "product_urn": product.product_urn,
                        "event_type": event_type,
                        "from_version_id": current_id,
                        "to_version_id": version.data_product_version_id,
                        "actor_subject": version.published_by,
                        "reason": reason,
                        "idempotency_key": idempotency_key,
                        "occurred_at": version.published_at,
                        "promotion_impact_id": promotion_impact_id,
                    },
                ).first()
                event_created = inserted_event is not None
                if inserted_event is None:
                    existing_event = connection.execute(
                        text(
                            """
                            SELECT event_id, from_version_id, to_version_id
                              FROM gda_control.data_product_event
                             WHERE tenant_id = :tenant_id
                               AND product_urn = :product_urn
                               AND idempotency_key = :idempotency_key
                            """
                        ),
                        {
                            "tenant_id": product.tenant_id,
                            "product_urn": product.product_urn,
                            "idempotency_key": idempotency_key,
                        },
                    ).mappings().one_or_none()
                    if (
                        existing_event is None
                        or str(existing_event["event_id"]) != str(event_id)
                        or _optional_uuid_text(existing_event["from_version_id"])
                        != _optional_uuid_text(current_id)
                        or str(existing_event["to_version_id"])
                        != str(version.data_product_version_id)
                    ):
                        raise DataProductConflictError(
                            "publication idempotency key is bound to another event"
                        )
            return {
                "product": self._load_product(
                    connection, product.tenant_id, product.product_slug
                ),
                "version": stored_version,
                "product_created": inserted_product is not None,
                "version_created": inserted_version is not None,
                "pointer_changed": pointer_changed,
                "event_created": event_created,
                "idempotent_replay": inserted_version is None,
                "promotion_deferred": promotion_deferred,
                "promotion_impact": promotion_impact,
                "architecture_release_created": architecture_release_created,
            }

    def list_products(self, tenant_id: str, *, public_only: bool = False) -> list[dict[str, Any]]:
        where = "AND p.governance_ref->>'visibility' = 'public'" if public_only else ""
        with self._transaction(tenant_id) as connection:
            rows = connection.execute(
                text(
                    f"""
                    SELECT p.product_slug FROM gda_control.data_product p
                     WHERE p.tenant_id = :tenant_id
                       AND p.current_version_id IS NOT NULL
                       {where}
                     ORDER BY p.domain, p.title
                    """
                ),
                {"tenant_id": tenant_id},
            ).scalars().all()
            return [
                self._load_product(connection, tenant_id, slug)
                for slug in rows
            ]

    def get_product(self, tenant_id: str, product_slug: str) -> dict[str, Any]:
        with self._transaction(tenant_id) as connection:
            product = self._load_product(connection, tenant_id, product_slug)
            if product is None or product["current_version_id"] is None:
                raise DataProductNotFoundError("published DataProduct was not found")
            versions = connection.execute(
                text(
                    """
                    SELECT version_key, data_product_version_id, predecessor_version_id,
                           manifest_sha256, published_by, published_at
                      FROM gda_control.data_product_version
                     WHERE tenant_id = :tenant_id AND product_urn = :product_urn
                     ORDER BY published_at DESC
                    """
                ),
                {"tenant_id": tenant_id, "product_urn": product["product_urn"]},
            ).mappings().all()
            product["versions"] = [_json_safe(dict(row)) for row in versions]
            return product

    def resolve_current_version(self, tenant_id: str, product_urn: str) -> dict[str, Any]:
        """Resolve a catalog product reference to its immutable active version."""
        if not _PRODUCT_URN_RE.fullmatch(product_urn):
            raise ValueError("invalid product_urn")
        if product_urn.split("/")[2] != tenant_id:
            raise ValueError("product_urn tenant must match tenant_id")
        with self._transaction(tenant_id) as connection:
            row = connection.execute(
                text(
                    """
                    SELECT p.tenant_id, p.product_urn, p.product_slug,
                           v.data_product_version_id, v.version_key,
                           v.manifest_sha256, v.published_at
                      FROM gda_control.data_product p
                      JOIN gda_control.data_product_version v
                        ON v.tenant_id = p.tenant_id
                       AND v.product_urn = p.product_urn
                       AND v.data_product_version_id = p.current_version_id
                     WHERE p.tenant_id = :tenant_id
                       AND p.product_urn = :product_urn
                    """
                ),
                {"tenant_id": tenant_id, "product_urn": product_urn},
            ).mappings().one_or_none()
            if row is None:
                raise DataProductNotFoundError("published DataProduct was not found")
            return _json_safe(dict(row))

    def get_version(
        self, tenant_id: str, product_slug: str, version_key: str | None = None
    ) -> dict[str, Any]:
        with self._transaction(tenant_id) as connection:
            product = self._load_product(connection, tenant_id, product_slug)
            if product is None or product["current_version_id"] is None:
                raise DataProductNotFoundError("published DataProduct was not found")
            selected = version_key or product["current_version_key"]
            version = self._load_version(
                connection, tenant_id, product["product_urn"], selected
            )
            if version is None:
                raise DataProductNotFoundError("DataProductVersion was not found")
            version["is_current"] = version["data_product_version_id"] == product[
                "current_version_id"
            ]
            return version

    def lineage(self, tenant_id: str, product_slug: str) -> dict[str, Any]:
        with self._transaction(tenant_id) as connection:
            product = self._load_product(connection, tenant_id, product_slug)
            if product is None or product["current_version_id"] is None:
                raise DataProductNotFoundError("published DataProduct was not found")
            version = self._load_version(
                connection, tenant_id, product["product_urn"], product["current_version_key"]
            )
            events = connection.execute(
                text(
                    """
                    SELECT event_id, event_type, from_version_id, to_version_id,
                           actor_subject, reason, occurred_at,
                           promotion_impact_id
                      FROM gda_control.data_product_event
                     WHERE tenant_id = :tenant_id AND product_urn = :product_urn
                     ORDER BY occurred_at, event_id
                    """
                ),
                {"tenant_id": tenant_id, "product_urn": product["product_urn"]},
            ).mappings().all()
            lineage = connection.execute(
                text(
                    """
                    WITH RECURSIVE upstream(resource_version_id) AS (
                        SELECT CAST(:output_version_id AS uuid)
                        UNION
                        SELECT event.source_resource_version_id
                          FROM gda_control.lineage_event event
                          JOIN upstream
                            ON event.target_resource_version_id = upstream.resource_version_id
                         WHERE event.tenant_id = :tenant_id
                    )
                    SELECT l.lineage_event_id, l.event_type, l.producer,
                           l.source_resource_version_id, l.target_resource_version_id,
                           l.artifact_id, l.facets, l.occurred_at,
                           source.resource_urn AS source_resource_urn,
                           target.resource_urn AS target_resource_urn
                      FROM gda_control.lineage_event l
                      JOIN gda_control.resource_version source
                        ON source.tenant_id = l.tenant_id
                       AND source.resource_version_id = l.source_resource_version_id
                      JOIN gda_control.resource_version target_version
                        ON target_version.tenant_id = l.tenant_id
                       AND target_version.resource_version_id = l.target_resource_version_id
                      JOIN gda_control.resource target
                        ON target.tenant_id = target_version.tenant_id
                       AND target.resource_urn = target_version.resource_urn
                      JOIN upstream
                        ON upstream.resource_version_id = l.target_resource_version_id
                     WHERE l.tenant_id = :tenant_id
                     ORDER BY l.occurred_at, l.lineage_event_id
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "output_version_id": version["output_resource_version_id"],
                },
            ).mappings().all()
            return {
                "product_urn": product["product_urn"],
                "current_version": product["current_version_key"],
                "source_to_product": [
                    _json_safe({**dict(row), "facets": _json_value(row["facets"])})
                    for row in lineage
                ],
                "version_pointer_events": [_json_safe(dict(row)) for row in events],
            }

    def preview_promotion_impact(
        self,
        tenant_id: str,
        product_slug: str,
        target_version_key: str,
    ) -> dict[str, Any]:
        """Return the current consumers that must be acknowledged before promotion."""
        with self._transaction(tenant_id) as connection:
            product = self._load_product(connection, tenant_id, product_slug)
            if product is None or product["current_version_id"] is None:
                raise DataProductNotFoundError("published DataProduct was not found")
            target = self._load_version(
                connection,
                tenant_id,
                product["product_urn"],
                target_version_key,
            )
            if target is None:
                raise DataProductNotFoundError("promotion target version was not found")
            current_id = UUID(product["current_version_id"])
            target_id = UUID(target["data_product_version_id"])
            if current_id == target_id:
                raise DataProductConflictError("promotion target is already current")
            if not self._is_descendant(
                connection,
                tenant_id,
                product["product_urn"],
                current_id,
                target_id,
            ):
                raise DataProductConflictError(
                    "promotion target must be a descendant of the current version"
                )
            return self._promotion_impact(connection, product, target)

    def rollback(
        self,
        tenant_id: str,
        product_slug: str,
        target_version_key: str,
        *,
        actor_subject: str,
        reason: str,
        idempotency_key: str,
        occurred_at: datetime | None = None,
    ) -> dict[str, Any]:
        if not actor_subject.strip() or not reason.strip() or not idempotency_key.strip():
            raise ValueError("actor_subject, reason and idempotency_key are required")
        timestamp = (occurred_at or datetime.now(UTC)).astimezone(UTC)
        with self._transaction(tenant_id) as connection:
            product = self._load_product(connection, tenant_id, product_slug)
            if product is None or product["current_version_id"] is None:
                raise DataProductNotFoundError("published DataProduct was not found")
            self._lock_promotion_scope(
                connection,
                tenant_id,
                product["product_urn"],
            )
            product = self._load_product(connection, tenant_id, product_slug)
            if product is None or product["current_version_id"] is None:
                raise DataProductNotFoundError("published DataProduct was not found")
            target = self._load_version(
                connection, tenant_id, product["product_urn"], target_version_key
            )
            if target is None:
                raise DataProductNotFoundError("rollback target version was not found")
            current_id = UUID(product["current_version_id"])
            target_id = UUID(target["data_product_version_id"])
            event_id = uuid5(
                uuid5(NAMESPACE_URL, product["product_urn"]),
                f"rollback:{idempotency_key}",
            )
            existing = connection.execute(
                text(
                    """
                    SELECT from_version_id, to_version_id
                      FROM gda_control.data_product_event
                     WHERE tenant_id = :tenant_id AND event_id = :event_id
                    """
                ),
                {"tenant_id": tenant_id, "event_id": event_id},
            ).mappings().one_or_none()
            if existing is not None:
                if str(existing["to_version_id"]) != str(target_id):
                    raise DataProductConflictError(
                        "rollback idempotency key is bound to another target"
                    )
                return {
                    "product": product,
                    "target_version": target,
                    "pointer_changed": False,
                    "event_created": False,
                    "idempotent_replay": True,
                }
            if current_id == target_id:
                raise DataProductConflictError("rollback target is already current")
            current = self._load_version_by_id(
                connection,
                tenant_id,
                product["product_urn"],
                current_id,
            )
            if current is None:
                raise DataProductNotFoundError("current DataProductVersion was not found")
            current_release = self._validate_persisted_architecture_release(
                connection,
                current,
            )
            if (
                current_release is not None
                and str(current_release["rollback_target_version_id"])
                != str(target_id)
            ):
                raise DataProductConflictError(
                    "architecture successor rollback must use its approved rollback target"
                )
            is_ancestor = connection.execute(
                text(
                    """
                    WITH RECURSIVE ancestors AS (
                        SELECT predecessor_version_id AS version_id
                          FROM gda_control.data_product_version
                         WHERE tenant_id = :tenant_id
                           AND product_urn = :product_urn
                           AND data_product_version_id = :current_id
                        UNION ALL
                        SELECT version.predecessor_version_id
                          FROM gda_control.data_product_version version
                          JOIN ancestors
                            ON version.data_product_version_id = ancestors.version_id
                         WHERE version.tenant_id = :tenant_id
                           AND version.product_urn = :product_urn
                           AND ancestors.version_id IS NOT NULL
                    )
                    SELECT EXISTS(
                        SELECT 1 FROM ancestors WHERE version_id = :target_id
                    )
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "product_urn": product["product_urn"],
                    "current_id": current_id,
                    "target_id": target_id,
                },
            ).scalar_one()
            if not is_ancestor:
                raise DataProductConflictError(
                    "rollback target must be an ancestor of the current version"
                )
            connection.execute(
                text(
                    """
                    UPDATE gda_control.data_product
                       SET current_version_id = :target_id, updated_at = :occurred_at
                     WHERE tenant_id = :tenant_id AND product_urn = :product_urn
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "product_urn": product["product_urn"],
                    "target_id": target_id,
                    "occurred_at": timestamp,
                },
            )
            connection.execute(
                text(
                    """
                    INSERT INTO gda_control.data_product_event (
                        tenant_id, event_id, product_urn, event_type,
                        from_version_id, to_version_id, actor_subject,
                        reason, idempotency_key, occurred_at
                    ) VALUES (
                        :tenant_id, :event_id, :product_urn, 'rolled_back',
                        :from_version_id, :to_version_id, :actor_subject,
                        :reason, :idempotency_key, :occurred_at
                    )
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "event_id": event_id,
                    "product_urn": product["product_urn"],
                    "from_version_id": current_id,
                    "to_version_id": target_id,
                    "actor_subject": actor_subject,
                    "reason": reason,
                    "idempotency_key": idempotency_key,
                    "occurred_at": timestamp,
                },
            )
            return {
                "product": self._load_product(connection, tenant_id, product_slug),
                "target_version": target,
                "pointer_changed": True,
                "event_created": True,
                "idempotent_replay": False,
            }

    def promote(
        self,
        tenant_id: str,
        product_slug: str,
        target_version_key: str,
        *,
        actor_subject: str,
        reason: str,
        idempotency_key: str,
        impact_acknowledgement: str = "",
        occurred_at: datetime | None = None,
    ) -> dict[str, Any]:
        """Move the active pointer to a published descendant version."""
        if not actor_subject.strip() or not reason.strip() or not idempotency_key.strip():
            raise ValueError("actor_subject, reason and idempotency_key are required")
        timestamp = (occurred_at or datetime.now(UTC)).astimezone(UTC)
        with self._transaction(tenant_id) as connection:
            product = self._load_product(connection, tenant_id, product_slug)
            if product is None or product["current_version_id"] is None:
                raise DataProductNotFoundError("published DataProduct was not found")
            self._lock_promotion_scope(
                connection,
                tenant_id,
                product["product_urn"],
            )
            product = self._load_product(connection, tenant_id, product_slug)
            if product is None or product["current_version_id"] is None:
                raise DataProductNotFoundError("published DataProduct was not found")
            target = self._load_version(
                connection, tenant_id, product["product_urn"], target_version_key
            )
            if target is None:
                raise DataProductNotFoundError("promotion target version was not found")
            current_id = UUID(product["current_version_id"])
            target_id = UUID(target["data_product_version_id"])
            event_id = uuid5(
                uuid5(NAMESPACE_URL, product["product_urn"]),
                f"promote:{idempotency_key}",
            )
            existing = connection.execute(
                text(
                    """
                    SELECT from_version_id, to_version_id
                      FROM gda_control.data_product_event
                     WHERE tenant_id = :tenant_id AND event_id = :event_id
                    """
                ),
                {"tenant_id": tenant_id, "event_id": event_id},
            ).mappings().one_or_none()
            if existing is not None:
                if str(existing["to_version_id"]) != str(target_id):
                    raise DataProductConflictError(
                        "promotion idempotency key is bound to another target"
                    )
                return {
                    "product": product,
                    "target_version": target,
                    "pointer_changed": False,
                    "event_created": False,
                    "idempotent_replay": True,
                }
            if current_id == target_id:
                raise DataProductConflictError("promotion target is already current")
            self._validate_persisted_architecture_release(connection, target)
            if not self._is_descendant(
                connection,
                tenant_id,
                product["product_urn"],
                current_id,
                target_id,
            ):
                raise DataProductConflictError(
                    "promotion target must be a descendant of the current version"
                )
            impact = self._promotion_impact(connection, product, target)
            if (
                impact["acknowledgement_required"]
                and str(impact_acknowledgement or "").strip()
                != impact["impact_fingerprint"]
            ):
                raise DataProductPromotionImpactError(impact)
            impact_id = self._record_promotion_impact(
                connection,
                event_id=event_id,
                impact=impact,
                actor_subject=actor_subject,
                assessed_at=timestamp,
                acknowledgement_mode=(
                    "explicit"
                    if impact["acknowledgement_required"]
                    else "not_required"
                ),
            )
            connection.execute(
                text(
                    """
                    UPDATE gda_control.data_product
                       SET current_version_id = :target_id, updated_at = :occurred_at
                     WHERE tenant_id = :tenant_id AND product_urn = :product_urn
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "product_urn": product["product_urn"],
                    "target_id": target_id,
                    "occurred_at": timestamp,
                },
            )
            connection.execute(
                text(
                    """
                    INSERT INTO gda_control.data_product_event (
                        tenant_id, event_id, product_urn, event_type,
                        from_version_id, to_version_id, actor_subject,
                        reason, idempotency_key, occurred_at,
                        promotion_impact_id
                    ) VALUES (
                        :tenant_id, :event_id, :product_urn, 'promoted',
                        :from_version_id, :to_version_id, :actor_subject,
                        :reason, :idempotency_key, :occurred_at,
                        :promotion_impact_id
                    )
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "event_id": event_id,
                    "product_urn": product["product_urn"],
                    "from_version_id": current_id,
                    "to_version_id": target_id,
                    "actor_subject": actor_subject,
                    "reason": reason,
                    "idempotency_key": idempotency_key,
                    "occurred_at": timestamp,
                    "promotion_impact_id": impact_id,
                },
            )
            return {
                "product": self._load_product(connection, tenant_id, product_slug),
                "target_version": target,
                "pointer_changed": True,
                "event_created": True,
                "idempotent_replay": False,
                "promotion_impact": impact,
            }


def _product_binding(value: dict[str, Any]) -> dict[str, Any]:
    binding = {
        key: value.get(key)
        for key in (
            "tenant_id",
            "product_urn",
            "product_slug",
            "title",
            "description",
            "domain",
            "owner_ref",
            "governance_ref",
            "created_at",
        )
    }
    binding["created_at"] = _normalized_datetime(binding["created_at"])
    return binding


def _approval_request_binding(case: ApprovalCase) -> tuple[Any, ...]:
    return (
        case.tenant_id,
        case.approval_case_ref,
        case.target_resource_urn,
        case.target_fingerprint,
        case.action,
        case.requester_subject,
        case.request_reason,
        case.request_context,
        case.requested_at,
        case.expires_at,
    )


def _version_binding(value: dict[str, Any]) -> dict[str, Any]:
    binding = {
        key: value.get(key)
        for key in (
            "tenant_id",
            "data_product_version_id",
            "product_urn",
            "version_key",
            "predecessor_version_id",
            "source_resource_version_id",
            "output_resource_version_id",
            "standard_version_ref",
            "mapping_contract",
            "quality_contract",
            "quality_evidence_artifact_id",
            "distribution_manifest",
            "manifest_sha256",
            "published_by",
            "published_at",
        )
    }
    binding["published_at"] = _normalized_datetime(binding["published_at"])
    return binding


def _normalized_datetime(value: Any) -> str:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed.astimezone(UTC).isoformat()


def _optional_uuid_text(value: Any) -> str | None:
    return str(value) if value is not None else None


def _json_safe(value: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, item in value.items():
        if isinstance(item, UUID):
            out[key] = str(item)
        elif hasattr(item, "isoformat"):
            out[key] = item.isoformat()
        else:
            out[key] = item
    return out
