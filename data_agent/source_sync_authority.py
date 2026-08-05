"""Tenant-scoped authority for source sync definitions and committed cursors."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from pydantic import TypeAdapter
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, SQLAlchemyError

from .db_engine import get_engine
from .platform_contracts import (
    Resource,
    ResourceVersion,
    Sha256,
    SourceSyncCheckpoint,
    SourceSyncCommit,
    SourceSyncCommitGovernanceEvidence,
    SourceSyncDefinitionVersion,
    SourceSyncQuarantineEvidence,
    TenantId,
    canonical_json_fingerprint,
)

GATEWAY_DATABASE_ROLE = "gda_control_gateway"
AUTHORITY_SYSTEM = "gda_control"
_TENANT_ADAPTER = TypeAdapter(TenantId)
_SHA256_ADAPTER = TypeAdapter(Sha256)


class SourceSyncAuthorityError(RuntimeError):
    code = "source_sync_error"


class SourceSyncConflictError(SourceSyncAuthorityError):
    code = "source_sync_conflict"


class SourceSyncNotFoundError(SourceSyncAuthorityError):
    code = "source_sync_not_found"


class SourceSyncForbiddenError(SourceSyncAuthorityError):
    code = "source_sync_forbidden"


class SourceSyncValidationError(SourceSyncAuthorityError):
    code = "source_sync_validation_error"


class SourceSyncConfigurationError(SourceSyncAuthorityError):
    code = "source_sync_unavailable"


@dataclass(frozen=True)
class SourceSyncDefinitionWriteResult:
    definition: SourceSyncDefinitionVersion
    checkpoint: SourceSyncCheckpoint
    created: bool


@dataclass(frozen=True)
class SourceSyncCommitWriteResult:
    commit: SourceSyncCommit
    checkpoint: SourceSyncCheckpoint
    governance_evidence: SourceSyncCommitGovernanceEvidence | None
    quarantine_evidence: SourceSyncQuarantineEvidence | None
    created: bool
    replayed_commit_id: UUID | None = None


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _json_value(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def _sqlstate(exc: DBAPIError) -> str | None:
    original = getattr(exc, "orig", None)
    return getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)


def source_sync_resource(
    definition: SourceSyncDefinitionVersion,
    *,
    owner_ref: str,
) -> Resource:
    governance_ref: dict[str, Any] = {
        "source_resource_urn": definition.source_resource_urn,
        "target_resource_urn": definition.target_resource_urn,
    }
    if definition.governance_contract is not None:
        governance_ref["source_sync_governance"] = (
            definition.governance_contract.model_dump(mode="json", by_alias=True)
        )
    return Resource(
        tenant_id=definition.tenant_id,
        resource_urn=definition.sync_definition_urn,
        resource_kind="sync_definition",
        authority_system=AUTHORITY_SYSTEM,
        authority_locator=definition.sync_definition_urn,
        owner_ref=owner_ref,
        governance_ref=governance_ref,
    )


def source_sync_resource_version(
    definition: SourceSyncDefinitionVersion,
) -> ResourceVersion:
    authority_version_ref: dict[str, Any] = {
        "mode": definition.mode.value,
        "write_disposition": definition.write_disposition.value,
        "cursor_kind": definition.cursor_kind.value,
        "source_definition_fingerprint": definition.source_definition_fingerprint,
        "platform_definition_version_id": str(
            definition.platform_definition_version_id
        ),
    }
    if definition.governance_contract is not None:
        governance_document = definition.governance_contract.model_dump(
            mode="json", by_alias=True
        )
        authority_version_ref.update(
            {
                "target_layer": definition.governance_contract.target_layer.value,
                "data_kind": definition.governance_contract.data_kind.value,
                "capture_kind": definition.governance_contract.capture_kind.value,
                "governance_contract_sha256": canonical_json_fingerprint(
                    governance_document
                ),
            }
        )
    return ResourceVersion(
        tenant_id=definition.tenant_id,
        resource_urn=definition.sync_definition_urn,
        resource_version_id=definition.sync_definition_version_id,
        version_key=f"sha256-{definition.definition_sha256[:12]}",
        content_sha256=definition.definition_sha256,
        authority_version_ref=authority_version_ref,
        created_by=definition.created_by,
        created_at=definition.created_at,
    )


class SourceSyncAuthority:
    """PostgreSQL authority with CAS cursor advancement and replay recovery."""

    def __init__(self, engine=None):
        self._engine = engine

    def _get_engine(self):
        engine = self._engine or get_engine()
        if engine is None or engine.dialect.name != "postgresql":
            raise SourceSyncConfigurationError("source sync authority requires PostgreSQL")
        return engine

    @contextmanager
    def _transaction(self, tenant_id: str) -> Iterator[Any]:
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        try:
            with self._get_engine().connect() as connection:
                with connection.begin():
                    try:
                        connection.exec_driver_sql(f'SET LOCAL ROLE "{GATEWAY_DATABASE_ROLE}"')
                    except DBAPIError as exc:
                        raise SourceSyncConfigurationError(
                            "database login is not a member of the platform gateway role"
                        ) from exc
                    connection.execute(
                        text("SELECT set_config('app.current_tenant', :tenant, true)"),
                        {"tenant": tenant},
                    )
                    yield connection
        except SourceSyncAuthorityError:
            raise
        except DBAPIError as exc:
            state = _sqlstate(exc)
            if state in {"40001", "23505"}:
                raise SourceSyncConflictError("source sync state conflict") from exc
            if state == "P0002":
                raise SourceSyncNotFoundError("source sync object was not found") from exc
            if state == "42501":
                raise SourceSyncForbiddenError("source sync tenant access was denied") from exc
            if state in {
                "22003",
                "22023",
                "22P02",
                "23502",
                "23503",
                "23514",
                "55000",
            }:
                raise SourceSyncValidationError("source sync contract was rejected") from exc
            raise SourceSyncAuthorityError("source sync database operation failed") from exc
        except SQLAlchemyError as exc:
            raise SourceSyncAuthorityError("source sync database operation failed") from exc

    @staticmethod
    def _definition_from_row(row) -> SourceSyncDefinitionVersion:
        value = dict(row)
        value["primary_keys"] = tuple(value["primary_keys"])
        value["config"] = _json_value(value["config"])
        value["governance_contract"] = _json_value(value["governance_contract"])
        return SourceSyncDefinitionVersion.model_validate(value)

    @staticmethod
    def _checkpoint_from_row(row) -> SourceSyncCheckpoint:
        value = dict(row)
        value["cursor"] = _json_value(value["cursor"])
        value["target_commit_ref"] = _json_value(value["target_commit_ref"])
        return SourceSyncCheckpoint.model_validate(value)

    @staticmethod
    def _commit_from_row(row) -> SourceSyncCommit:
        value = dict(row)
        for name in ("previous_cursor", "next_cursor", "target_commit_ref"):
            value[name] = _json_value(value[name])
        return SourceSyncCommit.model_validate(value)

    @staticmethod
    def _governance_evidence_from_row(
        row,
    ) -> SourceSyncCommitGovernanceEvidence:
        value = dict(row)
        value["quality_result_ids"] = tuple(value["quality_result_ids"])
        return SourceSyncCommitGovernanceEvidence.model_validate(value)

    @staticmethod
    def _quarantine_evidence_from_row(row) -> SourceSyncQuarantineEvidence:
        value = dict(row)
        value["reason_counts"] = _json_value(value["reason_counts"])
        return SourceSyncQuarantineEvidence.model_validate(value)

    @classmethod
    def _load_definition(
        cls,
        connection,
        tenant_id: str,
        sync_definition_version_id: UUID,
    ) -> SourceSyncDefinitionVersion | None:
        row = (
            connection.execute(
                text(
                    """
                    SELECT tenant_id, sync_definition_urn,
                           sync_definition_version_id,
                           platform_definition_version_id,
                           source_resource_urn, source_definition_fingerprint,
                           target_resource_urn, mode, write_disposition,
                           cursor_kind, cursor_field, primary_keys, delete_mode,
                           config, governance_contract, definition_sha256,
                           created_by, created_at
                    FROM gda_control.source_sync_definition
                    WHERE tenant_id = :tenant_id
                      AND sync_definition_version_id = :sync_definition_version_id
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "sync_definition_version_id": sync_definition_version_id,
                },
            )
            .mappings()
            .one_or_none()
        )
        return cls._definition_from_row(row) if row is not None else None

    @classmethod
    def _load_checkpoint(
        cls,
        connection,
        tenant_id: str,
        sync_definition_version_id: UUID,
    ) -> SourceSyncCheckpoint | None:
        row = (
            connection.execute(
                text(
                    """
                    SELECT tenant_id, sync_definition_version_id, state_version,
                           cursor, cursor_sha256, last_sync_commit_id,
                           last_run_id, target_commit_ref,
                           target_content_sha256, updated_by, updated_at
                    FROM gda_control.source_sync_checkpoint
                    WHERE tenant_id = :tenant_id
                      AND sync_definition_version_id = :sync_definition_version_id
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "sync_definition_version_id": sync_definition_version_id,
                },
            )
            .mappings()
            .one_or_none()
        )
        return cls._checkpoint_from_row(row) if row is not None else None

    @classmethod
    def _load_commit(
        cls,
        connection,
        tenant_id: str,
        sync_commit_id: UUID,
    ) -> SourceSyncCommit | None:
        row = (
            connection.execute(
                text(
                    """
                    SELECT tenant_id, sync_commit_id,
                           sync_definition_version_id, run_id,
                           from_state_version, to_state_version,
                           previous_cursor, previous_cursor_sha256,
                           next_cursor, next_cursor_sha256,
                           source_slice_sha256, target_commit_ref,
                           target_content_sha256, records_read,
                           records_inserted, records_updated, records_deleted,
                           records_output, committed_by, committed_at,
                           commit_sha256
                    FROM gda_control.source_sync_commit
                    WHERE tenant_id = :tenant_id
                      AND sync_commit_id = :sync_commit_id
                    """
                ),
                {"tenant_id": tenant_id, "sync_commit_id": sync_commit_id},
            )
            .mappings()
            .one_or_none()
        )
        return cls._commit_from_row(row) if row is not None else None

    @classmethod
    def _load_governance_evidence(
        cls,
        connection,
        tenant_id: str,
        sync_commit_id: UUID,
    ) -> SourceSyncCommitGovernanceEvidence | None:
        row = (
            connection.execute(
                text(
                    """
                    SELECT tenant_id, sync_commit_id,
                           target_resource_version_id, output_artifact_id,
                           quality_result_ids, lineage_event_id,
                           metadata_change_id, approval_case_ref,
                           evidence_sha256
                    FROM gda_control.source_sync_commit_governance_evidence
                    WHERE tenant_id = :tenant_id
                      AND sync_commit_id = :sync_commit_id
                    """
                ),
                {"tenant_id": tenant_id, "sync_commit_id": sync_commit_id},
            )
            .mappings()
            .one_or_none()
        )
        return cls._governance_evidence_from_row(row) if row is not None else None

    @classmethod
    def _load_quarantine_evidence(
        cls,
        connection,
        tenant_id: str,
        sync_commit_id: UUID,
    ) -> SourceSyncQuarantineEvidence | None:
        row = (
            connection.execute(
                text(
                    """
                    SELECT tenant_id, sync_commit_id, source_slice_sha256,
                           quarantine_resource_version_id,
                           quarantine_artifact_id, records_rejected,
                           reason_counts, evidence_sha256
                    FROM gda_control.source_sync_quarantine_evidence
                    WHERE tenant_id = :tenant_id
                      AND sync_commit_id = :sync_commit_id
                    """
                ),
                {"tenant_id": tenant_id, "sync_commit_id": sync_commit_id},
            )
            .mappings()
            .one_or_none()
        )
        return cls._quarantine_evidence_from_row(row) if row is not None else None

    @staticmethod
    def _load_resource(connection, tenant_id: str, resource_urn: str) -> Resource | None:
        row = (
            connection.execute(
                text(
                    """
                    SELECT tenant_id, resource_urn, resource_kind,
                           authority_system, authority_locator, owner_ref,
                           governance_ref, technical_refs
                    FROM gda_control.resource
                    WHERE tenant_id = :tenant_id AND resource_urn = :resource_urn
                    """
                ),
                {"tenant_id": tenant_id, "resource_urn": resource_urn},
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        value = dict(row)
        value["governance_ref"] = _json_value(value["governance_ref"])
        value["technical_refs"] = _json_value(value["technical_refs"])
        return Resource.model_validate(value)

    @staticmethod
    def _load_resource_version(
        connection,
        tenant_id: str,
        resource_version_id: UUID,
    ) -> ResourceVersion | None:
        row = (
            connection.execute(
                text(
                    """
                    SELECT tenant_id, resource_urn, resource_version_id,
                           version_key, predecessor_version_id, content_sha256,
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
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        value = dict(row)
        value["authority_version_ref"] = _json_value(value["authority_version_ref"])
        return ResourceVersion.model_validate(value)

    @staticmethod
    def _definition_binding(definition: SourceSyncDefinitionVersion) -> dict[str, Any]:
        return definition.model_dump(mode="json")

    def create_definition(
        self,
        definition: SourceSyncDefinitionVersion,
        *,
        owner_ref: str,
        initial_cursor: dict[str, Any] | None = None,
    ) -> SourceSyncDefinitionWriteResult:
        if definition.governance_contract is None:
            raise SourceSyncValidationError(
                "new source sync definitions require a governance contract"
            )
        cursor = initial_cursor or {}
        checkpoint = SourceSyncCheckpoint(
            tenant_id=definition.tenant_id,
            sync_definition_version_id=definition.sync_definition_version_id,
            cursor=cursor,
            cursor_sha256=canonical_json_fingerprint(cursor),
            updated_by=definition.created_by,
            updated_at=definition.created_at,
        )
        resource = source_sync_resource(definition, owner_ref=owner_ref)
        resource_version = source_sync_resource_version(definition)

        with self._transaction(definition.tenant_id) as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO gda_control.resource (
                        tenant_id, resource_urn, resource_kind, authority_system,
                        authority_locator, owner_ref, governance_ref, technical_refs
                    ) VALUES (
                        :tenant_id, :resource_urn, :resource_kind, :authority_system,
                        :authority_locator, :owner_ref,
                        CAST(:governance_ref AS jsonb), CAST(:technical_refs AS jsonb)
                    ) ON CONFLICT DO NOTHING
                    """
                ),
                {
                    **resource.model_dump(
                        mode="json",
                        exclude={"governance_ref", "technical_refs"},
                    ),
                    "governance_ref": _json(resource.governance_ref),
                    "technical_refs": _json(list(resource.technical_refs)),
                },
            )
            stored_resource = self._load_resource(
                connection,
                definition.tenant_id,
                definition.sync_definition_urn,
            )
            if stored_resource != resource:
                raise SourceSyncConflictError(
                    "sync definition Resource identity has different evidence"
                )

            connection.execute(
                text(
                    """
                    INSERT INTO gda_control.resource_version (
                        tenant_id, resource_urn, resource_version_id, version_key,
                        predecessor_version_id, content_sha256,
                        authority_version_ref, created_by, created_at
                    ) VALUES (
                        :tenant_id, :resource_urn, :resource_version_id,
                        :version_key, :predecessor_version_id, :content_sha256,
                        CAST(:authority_version_ref AS jsonb), :created_by, :created_at
                    ) ON CONFLICT DO NOTHING
                    """
                ),
                {
                    **resource_version.model_dump(
                        mode="python",
                        exclude={"authority_version_ref"},
                    ),
                    "authority_version_ref": _json(resource_version.authority_version_ref),
                },
            )
            stored_version = self._load_resource_version(
                connection,
                definition.tenant_id,
                definition.sync_definition_version_id,
            )
            if stored_version != resource_version:
                raise SourceSyncConflictError(
                    "sync definition ResourceVersion identity has different evidence"
                )

            inserted = connection.execute(
                text(
                    """
                    INSERT INTO gda_control.source_sync_definition (
                        tenant_id, sync_definition_urn,
                        sync_definition_version_id,
                        platform_definition_version_id,
                        source_resource_urn, source_definition_fingerprint,
                        target_resource_urn, mode, write_disposition,
                        cursor_kind, cursor_field, primary_keys, delete_mode,
                        config, governance_contract, definition_sha256,
                        created_by, created_at
                    ) VALUES (
                        :tenant_id, :sync_definition_urn,
                        :sync_definition_version_id,
                        :platform_definition_version_id,
                        :source_resource_urn, :source_definition_fingerprint,
                        :target_resource_urn, :mode, :write_disposition,
                        :cursor_kind, :cursor_field, :primary_keys, :delete_mode,
                        CAST(:config AS jsonb), CAST(:governance_contract AS jsonb),
                        :definition_sha256,
                        :created_by, :created_at
                    ) ON CONFLICT DO NOTHING
                    RETURNING sync_definition_version_id
                    """
                ),
                {
                    **definition.model_dump(
                        mode="python",
                        exclude={"config", "governance_contract"},
                    ),
                    "mode": definition.mode.value,
                    "write_disposition": definition.write_disposition.value,
                    "cursor_kind": definition.cursor_kind.value,
                    "delete_mode": definition.delete_mode.value,
                    "primary_keys": list(definition.primary_keys),
                    "config": _json(definition.config),
                    "governance_contract": _json(
                        definition.governance_contract.model_dump(
                            mode="json", by_alias=True
                        )
                    ),
                },
            ).first()
            stored = self._load_definition(
                connection,
                definition.tenant_id,
                definition.sync_definition_version_id,
            )
            if stored is None:
                raise SourceSyncNotFoundError("sync definition was not visible after insert")
            if self._definition_binding(stored) != self._definition_binding(definition):
                raise SourceSyncConflictError(
                    "sync definition identity already has different evidence"
                )

            connection.execute(
                text(
                    """
                    INSERT INTO gda_control.source_sync_checkpoint (
                        tenant_id, sync_definition_version_id, state_version,
                        cursor, cursor_sha256, updated_by, updated_at
                    ) VALUES (
                        :tenant_id, :sync_definition_version_id, :state_version,
                        CAST(:cursor AS jsonb), :cursor_sha256,
                        :updated_by, :updated_at
                    ) ON CONFLICT DO NOTHING
                    """
                ),
                {
                    **checkpoint.model_dump(
                        mode="python",
                        exclude={"cursor", "target_commit_ref"},
                    ),
                    "cursor": _json(checkpoint.cursor),
                },
            )
            stored_checkpoint = self._load_checkpoint(
                connection,
                definition.tenant_id,
                definition.sync_definition_version_id,
            )
            if stored_checkpoint != checkpoint:
                raise SourceSyncConflictError(
                    "sync checkpoint identity already has different evidence"
                )
            return SourceSyncDefinitionWriteResult(
                definition=stored,
                checkpoint=stored_checkpoint,
                created=inserted is not None,
            )

    def get_definition(
        self,
        tenant_id: str,
        sync_definition_version_id: UUID,
    ) -> SourceSyncDefinitionVersion:
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        with self._transaction(tenant) as connection:
            stored = self._load_definition(
                connection,
                tenant,
                sync_definition_version_id,
            )
            if stored is None:
                raise SourceSyncNotFoundError("source sync definition was not found")
            return stored

    def get_checkpoint(
        self,
        tenant_id: str,
        sync_definition_version_id: UUID,
    ) -> SourceSyncCheckpoint:
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        with self._transaction(tenant) as connection:
            stored = self._load_checkpoint(
                connection,
                tenant,
                sync_definition_version_id,
            )
            if stored is None:
                raise SourceSyncNotFoundError("source sync checkpoint was not found")
            return stored

    def find_source_slice_commit(
        self,
        tenant_id: str,
        sync_definition_version_id: UUID,
        *,
        previous_cursor: dict[str, Any],
        next_cursor: dict[str, Any],
        source_slice_sha256: str,
    ) -> SourceSyncCommit | None:
        """Return prior commit evidence before a provider writes the same slice."""

        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        source_slice = _SHA256_ADAPTER.validate_python(source_slice_sha256)
        previous_cursor_sha256 = canonical_json_fingerprint(previous_cursor)
        next_cursor_sha256 = canonical_json_fingerprint(next_cursor)
        with self._transaction(tenant) as connection:
            if self._load_definition(
                connection,
                tenant,
                sync_definition_version_id,
            ) is None:
                raise SourceSyncNotFoundError("source sync definition was not found")
            row = (
                connection.execute(
                    text(
                        """
                        SELECT tenant_id, sync_commit_id,
                               sync_definition_version_id, run_id,
                               from_state_version, to_state_version,
                               previous_cursor, previous_cursor_sha256,
                               next_cursor, next_cursor_sha256,
                               source_slice_sha256, target_commit_ref,
                               target_content_sha256, records_read,
                               records_inserted, records_updated,
                               records_deleted, records_output,
                               committed_by, committed_at, commit_sha256
                        FROM gda_control.source_sync_commit
                        WHERE tenant_id = :tenant_id
                          AND sync_definition_version_id = :sync_definition_version_id
                          AND previous_cursor_sha256 = :previous_cursor_sha256
                          AND next_cursor_sha256 = :next_cursor_sha256
                          AND source_slice_sha256 = :source_slice_sha256
                        """
                    ),
                    {
                        "tenant_id": tenant,
                        "sync_definition_version_id": sync_definition_version_id,
                        "previous_cursor_sha256": previous_cursor_sha256,
                        "next_cursor_sha256": next_cursor_sha256,
                        "source_slice_sha256": source_slice,
                    },
                )
                .mappings()
                .one_or_none()
            )
            return self._commit_from_row(row) if row is not None else None

    def commit(
        self,
        commit: SourceSyncCommit,
        governance_evidence: SourceSyncCommitGovernanceEvidence | None = None,
        quarantine_evidence: SourceSyncQuarantineEvidence | None = None,
    ) -> SourceSyncCommitWriteResult:
        if governance_evidence is not None and (
            governance_evidence.tenant_id != commit.tenant_id
            or governance_evidence.sync_commit_id != commit.sync_commit_id
        ):
            raise SourceSyncValidationError(
                "source sync governance evidence must bind the requested commit"
            )
        if quarantine_evidence is not None and (
            quarantine_evidence.tenant_id != commit.tenant_id
            or quarantine_evidence.sync_commit_id != commit.sync_commit_id
        ):
            raise SourceSyncValidationError(
                "source sync quarantine evidence must bind the requested commit"
            )
        with self._transaction(commit.tenant_id) as connection:
            definition = self._load_definition(
                connection,
                commit.tenant_id,
                commit.sync_definition_version_id,
            )
            if definition is None:
                raise SourceSyncNotFoundError("source sync definition was not found")
            target_layer = (
                definition.governance_contract.target_layer.value
                if definition.governance_contract is not None
                else None
            )
            governed_commit_available = bool(
                connection.execute(
                    text(
                        """
                        SELECT to_regprocedure(
                            'gda_control.commit_source_sync(text,uuid,uuid,uuid,integer,integer,jsonb,text,jsonb,text,text,jsonb,text,bigint,bigint,bigint,bigint,bigint,text,timestamptz,text,jsonb)'
                        ) IS NOT NULL
                        """
                    )
                ).scalar_one()
            )
            quarantine_binding_available = bool(
                connection.execute(
                    text(
                        """
                        SELECT to_regprocedure(
                            'gda_control.bind_source_sync_quarantine_evidence(text,uuid,jsonb)'
                        ) IS NOT NULL
                        """
                    )
                ).scalar_one()
            )
            if target_layer in {"silver", "gold"} and not quarantine_binding_available:
                raise SourceSyncConfigurationError(
                    "governed source sync commit requires database migration 143"
                )
            if target_layer not in {"silver", "gold"} and quarantine_evidence is not None:
                raise SourceSyncValidationError(
                    "Landing and ODS commits must not bind quarantine evidence"
                )
            if governed_commit_available:
                commit_statement = """
                    SELECT result_sync_commit_id, result_created
                    FROM gda_control.commit_source_sync(
                        :tenant_id, :sync_commit_id,
                        :sync_definition_version_id, :run_id,
                        :from_state_version, :to_state_version,
                        CAST(:previous_cursor AS jsonb),
                        :previous_cursor_sha256,
                        CAST(:next_cursor AS jsonb), :next_cursor_sha256,
                        :source_slice_sha256,
                        CAST(:target_commit_ref AS jsonb),
                        :target_content_sha256, :records_read,
                        :records_inserted, :records_updated,
                        :records_deleted, :records_output,
                        :committed_by, :committed_at, :commit_sha256,
                        CAST(:governance_evidence AS jsonb)
                    )
                """
            else:
                if governance_evidence is not None or target_layer in {"silver", "gold"}:
                    raise SourceSyncConfigurationError(
                        "governed source sync commit requires database migration 142"
                    )
                commit_statement = """
                    SELECT result_sync_commit_id, result_created
                    FROM gda_control.commit_source_sync(
                        :tenant_id, :sync_commit_id,
                        :sync_definition_version_id, :run_id,
                        :from_state_version, :to_state_version,
                        CAST(:previous_cursor AS jsonb),
                        :previous_cursor_sha256,
                        CAST(:next_cursor AS jsonb), :next_cursor_sha256,
                        :source_slice_sha256,
                        CAST(:target_commit_ref AS jsonb),
                        :target_content_sha256, :records_read,
                        :records_inserted, :records_updated,
                        :records_deleted, :records_output,
                        :committed_by, :committed_at, :commit_sha256
                    )
                """
            row = (
                connection.execute(
                    text(commit_statement),
                    {
                        **commit.model_dump(
                            mode="python",
                            exclude={
                                "previous_cursor",
                                "next_cursor",
                                "target_commit_ref",
                            },
                        ),
                        "previous_cursor": _json(commit.previous_cursor),
                        "next_cursor": _json(commit.next_cursor),
                        "target_commit_ref": _json(commit.target_commit_ref),
                        "governance_evidence": (
                            _json(governance_evidence.model_dump(mode="json"))
                            if governance_evidence is not None
                            else None
                        ),
                    },
                )
                .mappings()
                .one()
            )
            stored_commit_id = row["result_sync_commit_id"]
            if target_layer in {"silver", "gold"}:
                if stored_commit_id != commit.sync_commit_id:
                    if quarantine_evidence is not None:
                        raise SourceSyncValidationError(
                            "cross-run replay must reuse original quarantine evidence"
                        )
                else:
                    if quarantine_evidence is None:
                        raise SourceSyncValidationError(
                            "governed commit requires its quarantine evidence"
                        )
                    connection.execute(
                        text(
                            """
                            SELECT gda_control.bind_source_sync_quarantine_evidence(
                                :tenant_id, :sync_commit_id,
                                CAST(:quarantine_evidence AS jsonb)
                            )
                            """
                        ),
                        {
                            "tenant_id": commit.tenant_id,
                            "sync_commit_id": commit.sync_commit_id,
                            "quarantine_evidence": _json(
                                quarantine_evidence.model_dump(mode="json")
                            ),
                        },
                    )
            stored = self._load_commit(connection, commit.tenant_id, stored_commit_id)
            checkpoint = self._load_checkpoint(
                connection,
                commit.tenant_id,
                commit.sync_definition_version_id,
            )
            if stored is None or checkpoint is None:
                raise SourceSyncNotFoundError("source sync commit was not visible")
            stored_governance_evidence = (
                self._load_governance_evidence(
                    connection,
                    commit.tenant_id,
                    stored_commit_id,
                )
                if governed_commit_available
                else None
            )
            stored_quarantine_evidence = (
                self._load_quarantine_evidence(
                    connection,
                    commit.tenant_id,
                    stored_commit_id,
                )
                if target_layer in {"silver", "gold"}
                else None
            )
            if (
                target_layer in {"silver", "gold"}
                and stored_quarantine_evidence is None
            ):
                raise SourceSyncValidationError(
                    "governed source sync commit lacks quarantine evidence"
                )
            if stored.sync_commit_id == commit.sync_commit_id and stored != commit:
                raise SourceSyncConflictError(
                    "source sync commit identity has different evidence"
                )
            return SourceSyncCommitWriteResult(
                commit=stored,
                checkpoint=checkpoint,
                governance_evidence=stored_governance_evidence,
                quarantine_evidence=stored_quarantine_evidence,
                created=bool(row["result_created"]),
                replayed_commit_id=(
                    None
                    if stored.sync_commit_id == commit.sync_commit_id
                    else stored.sync_commit_id
                ),
            )

    def commits(
        self,
        tenant_id: str,
        sync_definition_version_id: UUID,
    ) -> tuple[SourceSyncCommit, ...]:
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
        with self._transaction(tenant) as connection:
            if self._load_definition(connection, tenant, sync_definition_version_id) is None:
                raise SourceSyncNotFoundError("source sync definition was not found")
            rows = (
                connection.execute(
                    text(
                        """
                        SELECT tenant_id, sync_commit_id,
                               sync_definition_version_id, run_id,
                               from_state_version, to_state_version,
                               previous_cursor, previous_cursor_sha256,
                               next_cursor, next_cursor_sha256,
                               source_slice_sha256, target_commit_ref,
                               target_content_sha256, records_read,
                               records_inserted, records_updated,
                               records_deleted, records_output,
                               committed_by, committed_at, commit_sha256
                        FROM gda_control.source_sync_commit
                        WHERE tenant_id = :tenant_id
                          AND sync_definition_version_id = :sync_definition_version_id
                        ORDER BY to_state_version
                        """
                    ),
                    {
                        "tenant_id": tenant,
                        "sync_definition_version_id": sync_definition_version_id,
                    },
                )
                .mappings()
                .all()
            )
            return tuple(self._commit_from_row(row) for row in rows)
