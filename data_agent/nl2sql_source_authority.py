"""Version-locked physical source admission for governed NL2SQL."""

from __future__ import annotations

import json
import re
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, SQLAlchemyError

from .db_engine import get_engine
from .platform_contracts import (
    ResourceVersion,
    SubjectContext,
    canonical_json_fingerprint,
)
from .platform_gateway import GATEWAY_DATABASE_ROLE, PlatformGateway


class NL2SQLSourceAuthorityError(ValueError):
    """Base error for source binding registration or resolution."""


class NL2SQLSourceAdmissionError(NL2SQLSourceAuthorityError):
    """The generated query cannot be admitted against immutable sources."""


class NL2SQLSourceAuthorityUnavailableError(NL2SQLSourceAuthorityError):
    """The persistent source binding authority is unavailable."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class NL2SQLSourceBinding(_FrozenModel):
    schema_version: Literal["gda.nl2sql-source-binding.v1"] = Field(
        default="gda.nl2sql-source-binding.v1",
        alias="schema",
    )
    tenant_id: str = Field(min_length=1, max_length=64)
    binding_id: UUID
    semantic_source_name: str = Field(
        min_length=1,
        max_length=255,
        pattern=r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?$",
    )
    execution_engine: Literal["postgis", "lake"]
    physical_locator: str = Field(min_length=1, max_length=2_048)
    source_mode: Literal["immutable_snapshot", "mutable_view"]
    resource_version_id: UUID
    resource_urn: str = Field(min_length=1, max_length=512)
    version_key: str = Field(min_length=1, max_length=128)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    authority_version_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    physical_binding_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    registered_by: str = Field(pattern=r"^(human|workload|agent):[^\s]{1,128}$")
    registered_at: datetime

    @field_validator("registered_at")
    @classmethod
    def _utc_registered_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("source binding time must be timezone-aware")
        return value.astimezone(UTC)

    @staticmethod
    def fingerprint_document(values: dict[str, Any]) -> dict[str, Any]:
        return {
            "tenant_id": str(values["tenant_id"]),
            "binding_id": str(values["binding_id"]),
            "semantic_source_name": str(values["semantic_source_name"]),
            "execution_engine": str(values["execution_engine"]),
            "physical_locator": str(values["physical_locator"]),
            "source_mode": str(values["source_mode"]),
            "resource_version_id": str(values["resource_version_id"]),
            "resource_urn": str(values["resource_urn"]),
            "version_key": str(values["version_key"]),
            "content_sha256": str(values["content_sha256"]),
            "authority_version_sha256": str(values["authority_version_sha256"]),
        }

    @model_validator(mode="after")
    def _exact_fingerprint(self) -> "NL2SQLSourceBinding":
        expected = canonical_json_fingerprint(
            self.fingerprint_document(self.model_dump(mode="python"))
        )
        if self.physical_binding_sha256 != expected:
            raise ValueError("physical binding fingerprint does not match its contract")
        return self

    @classmethod
    def create(
        cls,
        *,
        tenant_id: str,
        semantic_source_name: str,
        execution_engine: Literal["postgis", "lake"],
        physical_locator: str,
        source_mode: Literal["immutable_snapshot", "mutable_view"],
        resource_version: ResourceVersion,
        registered_by: str | None = None,
        registered_at: datetime | None = None,
        binding_id: UUID | None = None,
    ) -> "NL2SQLSourceBinding":
        at = (registered_at or resource_version.created_at).astimezone(UTC)
        seed: dict[str, Any] = {
            "tenant_id": tenant_id,
            "semantic_source_name": semantic_source_name,
            "execution_engine": execution_engine,
            "physical_locator": physical_locator,
            "source_mode": source_mode,
            "resource_version_id": resource_version.resource_version_id,
            "resource_urn": resource_version.resource_urn,
            "version_key": resource_version.version_key,
            "content_sha256": resource_version.content_sha256,
            "authority_version_sha256": canonical_json_fingerprint(
                resource_version.authority_version_ref
            ),
            "registered_by": registered_by or resource_version.created_by,
            "registered_at": at,
        }
        identity = binding_id or uuid5(
            NAMESPACE_URL,
            "gda:nl2sql-source-binding:"
            + canonical_json_fingerprint({
                key: str(value) if isinstance(value, UUID) else value
                for key, value in seed.items()
                if key not in {"registered_by", "registered_at"}
            }),
        )
        values = {**seed, "binding_id": identity}
        values["physical_binding_sha256"] = canonical_json_fingerprint(
            cls.fingerprint_document(values)
        )
        return cls.model_validate(values)


def _authority_locator_values(value: Any, *, parent_key: str = "") -> set[str]:
    accepted_keys = {
        "postgis_table",
        "table",
        "storage_uri",
        "lakehouse_uri",
        "warehouse_uri",
        "projection_path",
    }
    values: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            values.update(_authority_locator_values(item, parent_key=str(key)))
    elif isinstance(value, (list, tuple)):
        for item in value:
            values.update(_authority_locator_values(item, parent_key=parent_key))
    elif parent_key in accepted_keys and value is not None:
        values.add(str(value).strip())
    return {item for item in values if item}


def _normalized_postgis_locator(value: str) -> str:
    normalized = re.sub(r"^postgis://", "", str(value).strip(), flags=re.IGNORECASE)
    if normalized.startswith("public."):
        normalized = normalized[len("public.") :]
    return normalized.casefold()


def _locator_is_authoritative(binding: NL2SQLSourceBinding, version: ResourceVersion) -> bool:
    candidates = _authority_locator_values(version.authority_version_ref)
    if binding.execution_engine == "postgis":
        expected = _normalized_postgis_locator(binding.physical_locator)
        return any(_normalized_postgis_locator(item) == expected for item in candidates)
    return binding.physical_locator in candidates


def _immutable_mode_is_authoritative(version: ResourceVersion) -> bool:
    evidence = version.authority_version_ref
    return bool(
        evidence.get("immutable_snapshot") is True
        or evidence.get("source_mode") == "immutable_snapshot"
    )


class NL2SQLSourceAuthority:
    """Register and resolve tenant-scoped active NL2SQL source bindings."""

    def __init__(self, engine=None, gateway: PlatformGateway | None = None):
        self._engine = engine
        self._gateway = gateway

    def _get_engine(self):
        engine = self._engine or get_engine()
        if engine is None:
            raise NL2SQLSourceAuthorityUnavailableError(
                "NL2SQL source binding database is not configured"
            )
        if engine.dialect.name != "postgresql":
            raise NL2SQLSourceAuthorityUnavailableError(
                "NL2SQL source binding authority requires PostgreSQL"
            )
        return engine

    @contextmanager
    def _transaction(self, tenant_id: str):
        try:
            with self._get_engine().connect() as connection:
                with connection.begin():
                    connection.exec_driver_sql(
                        f'SET LOCAL ROLE "{GATEWAY_DATABASE_ROLE}"'
                    )
                    connection.execute(
                        text("SELECT set_config('app.current_tenant', :tenant, true)"),
                        {"tenant": tenant_id},
                    )
                    yield connection
        except NL2SQLSourceAuthorityError:
            raise
        except (DBAPIError, SQLAlchemyError) as exc:
            raise NL2SQLSourceAuthorityUnavailableError(
                "NL2SQL source binding authority is unavailable or not migrated"
            ) from exc

    def activate(
        self,
        binding: NL2SQLSourceBinding,
        subject_context: SubjectContext,
    ) -> NL2SQLSourceBinding:
        if binding.tenant_id != subject_context.tenant_id:
            raise NL2SQLSourceAdmissionError("source binding tenant mismatch")
        if not set(subject_context.roles) & {"admin", "platform_operator"}:
            raise NL2SQLSourceAdmissionError(
                "source binding activation requires admin or platform_operator"
            )
        gateway = self._gateway or PlatformGateway(self._engine)
        try:
            version = gateway.get_resource_version(
                binding.tenant_id,
                binding.resource_version_id,
            )
        except Exception as exc:
            raise NL2SQLSourceAdmissionError(
                "bound ResourceVersion cannot be verified"
            ) from exc
        if (
            version.resource_urn != binding.resource_urn
            or version.version_key != binding.version_key
            or version.content_sha256 != binding.content_sha256
            or canonical_json_fingerprint(version.authority_version_ref)
            != binding.authority_version_sha256
        ):
            raise NL2SQLSourceAdmissionError(
                "source binding does not match the immutable ResourceVersion"
            )
        if not _locator_is_authoritative(binding, version):
            raise NL2SQLSourceAdmissionError(
                "physical locator is absent from ResourceVersion authority evidence"
            )
        if (
            binding.source_mode == "immutable_snapshot"
            and not _immutable_mode_is_authoritative(version)
        ):
            raise NL2SQLSourceAdmissionError(
                "ResourceVersion does not attest an immutable physical snapshot"
            )
        params = binding.model_dump(mode="python", by_alias=False)
        params.pop("schema_version", None)
        params["activated_by"] = (
            f"{subject_context.subject_type.value}:{subject_context.subject_id}"
        )
        with self._transaction(binding.tenant_id) as connection:
            stored_id = connection.execute(
                text(
                    "SELECT gda_control.activate_nl2sql_source_binding("
                    ":tenant_id, :binding_id, :semantic_source_name, "
                    ":execution_engine, :physical_locator, :source_mode, "
                    ":resource_version_id, :resource_urn, :version_key, "
                    ":content_sha256, :authority_version_sha256, "
                    ":physical_binding_sha256, :registered_by, :registered_at, "
                    ":activated_by)"
                ),
                params,
            ).scalar_one()
        if UUID(str(stored_id)) != binding.binding_id:
            raise NL2SQLSourceAuthorityUnavailableError(
                "source binding recorder returned a different identity"
            )
        return self.resolve(
            binding.tenant_id,
            binding.semantic_source_name,
            binding.execution_engine,
        )

    def resolve(
        self,
        tenant_id: str,
        semantic_source_name: str,
        execution_engine: Literal["postgis", "lake"],
    ) -> NL2SQLSourceBinding:
        with self._transaction(tenant_id) as connection:
            row = connection.execute(
                text(
                    "SELECT binding.*, version.authority_version_ref AS "
                    "resource_authority_version_ref FROM "
                    "gda_control.nl2sql_source_binding_activation AS active "
                    "JOIN gda_control.nl2sql_source_binding AS binding "
                    "  ON binding.tenant_id = active.tenant_id "
                    " AND binding.binding_id = active.binding_id "
                    "JOIN gda_control.resource_version AS version "
                    "  ON version.tenant_id = binding.tenant_id "
                    " AND version.resource_version_id = binding.resource_version_id "
                    " AND version.resource_urn = binding.resource_urn "
                    " AND version.version_key = binding.version_key "
                    " AND version.content_sha256 = binding.content_sha256 "
                    "WHERE active.tenant_id = :tenant_id "
                    "  AND active.semantic_source_name = :semantic_source_name "
                    "  AND active.execution_engine = :execution_engine"
                ),
                {
                    "tenant_id": tenant_id,
                    "semantic_source_name": semantic_source_name,
                    "execution_engine": execution_engine,
                },
            ).mappings().one_or_none()
        if row is None:
            raise NL2SQLSourceAdmissionError(
                f"no active version binding for {semantic_source_name} on {execution_engine}"
            )
        value = dict(row)
        authority_version_ref = value.pop("resource_authority_version_ref", None)
        binding = NL2SQLSourceBinding.model_validate(value)
        if isinstance(authority_version_ref, str):
            try:
                authority_version_ref = json.loads(authority_version_ref)
            except ValueError:
                authority_version_ref = None
        if not isinstance(authority_version_ref, dict):
            raise NL2SQLSourceAdmissionError(
                "bound ResourceVersion authority evidence is unavailable"
            )
        version = ResourceVersion(
            tenant_id=binding.tenant_id,
            resource_urn=binding.resource_urn,
            resource_version_id=binding.resource_version_id,
            version_key=binding.version_key,
            content_sha256=binding.content_sha256,
            authority_version_ref=authority_version_ref,
            created_by=binding.registered_by,
            created_at=binding.registered_at,
        )
        if (
            canonical_json_fingerprint(authority_version_ref)
            != binding.authority_version_sha256
            or not _locator_is_authoritative(binding, version)
        ):
            raise NL2SQLSourceAdmissionError(
                "active NL2SQL binding no longer matches ResourceVersion evidence"
            )
        if (
            binding.source_mode == "immutable_snapshot"
            and not _immutable_mode_is_authoritative(version)
        ):
            raise NL2SQLSourceAdmissionError(
                "active NL2SQL binding has no immutable snapshot attestation"
            )
        return binding

    def list_active(
        self,
        tenant_id: str,
        execution_engine: Literal["postgis", "lake"],
    ) -> tuple[NL2SQLSourceBinding, ...]:
        """Return verified active bindings available for governed planning."""
        with self._transaction(tenant_id) as connection:
            rows = connection.execute(
                text(
                    "SELECT semantic_source_name FROM "
                    "gda_control.nl2sql_source_binding_activation "
                    "WHERE tenant_id = :tenant_id "
                    "AND execution_engine = :execution_engine "
                    "ORDER BY semantic_source_name"
                ),
                {
                    "tenant_id": tenant_id,
                    "execution_engine": execution_engine,
                },
            ).all()
        return tuple(
            self.resolve(tenant_id, str(row[0]), execution_engine)
            for row in rows
        )


__all__ = [
    "NL2SQLSourceAdmissionError",
    "NL2SQLSourceAuthority",
    "NL2SQLSourceAuthorityError",
    "NL2SQLSourceAuthorityUnavailableError",
    "NL2SQLSourceBinding",
]
