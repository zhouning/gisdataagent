#!/usr/bin/env python3
"""Certify source sync authority behavior in an isolated PostgreSQL database."""

from __future__ import annotations

import argparse
import json
import os
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import psycopg2
from dotenv import dotenv_values
from psycopg2 import sql
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError

from data_agent.approval_case_authority import ApprovalCaseAuthority
from data_agent.platform_contracts import (
    ApprovalCase,
    ApprovalCaseStatus,
    Artifact,
    LineageEvent,
    PlatformDefinitionVersion,
    PlatformRun,
    QualityResult,
    Resource,
    ResourceVersion,
    SourceSyncCommit,
    SourceSyncCommitGovernanceEvidence,
    SourceSyncDefinitionVersion,
    SourceSyncQuarantineEvidence,
    SubjectContext,
    canonical_json_fingerprint,
    platform_definition_fingerprint,
    quality_result_fingerprint,
    source_sync_commit_fingerprint,
    source_sync_commit_governance_evidence_fingerprint,
    source_sync_definition_fingerprint,
    source_sync_quarantine_evidence_fingerprint,
)
from data_agent.platform_gateway import DefinitionRegistration, PlatformGateway
from data_agent.source_sync_authority import (
    SourceSyncAuthority,
    SourceSyncConflictError,
    SourceSyncNotFoundError,
    SourceSyncValidationError,
)
from scripts.source_sync_certification_support import (
    connection_url as _connection_url,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT = REPO_ROOT / ".tmp/source-sync-certification/authority-report.json"
MIGRATIONS = (
    REPO_ROOT / "data_agent/migrations/092_platform_control_ledger.sql",
    REPO_ROOT / "data_agent/migrations/094_platform_control_gateway.sql",
    REPO_ROOT / "data_agent/migrations/095_platform_command_outbox.sql",
    REPO_ROOT / "data_agent/migrations/096_platform_success_verdict.sql",
    REPO_ROOT / "data_agent/migrations/102_source_schema_drift_ledger.sql",
    REPO_ROOT / "data_agent/migrations/103_unified_approval_case_authority.sql",
    REPO_ROOT / "data_agent/migrations/104_source_sync_checkpoint_authority.sql",
    REPO_ROOT / "data_agent/migrations/112_metadata_fabric_binding_outbox.sql",
    REPO_ROOT / "data_agent/migrations/130_metadata_projection_binding_dependency.sql",
    REPO_ROOT / "data_agent/migrations/141_source_sync_governance_contract.sql",
    REPO_ROOT / "data_agent/migrations/142_source_sync_commit_governance_evidence.sql",
    REPO_ROOT / "data_agent/migrations/143_source_sync_quarantine_evidence.sql",
)
WORKLOAD = "workload:dataops-controller"


def _settings() -> dict[str, str]:
    values = {
        key: str(value)
        for key, value in dotenv_values(REPO_ROOT / ".env").items()
        if value is not None
    }
    return {**values, **os.environ}


def _sqlstate(exc: DBAPIError) -> str | None:
    original = getattr(exc, "orig", None)
    return getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)


class _PostgresDatabaseSandbox:
    """Own one random database and remove only that exact database."""

    def __init__(self, admin_url: str) -> None:
        self.database = f"gda_sync_cert_{secrets.token_hex(5)}"
        parsed = make_url(admin_url)
        self.database_url = parsed.set(database=self.database).render_as_string(
            hide_password=False
        )
        maintenance_url = parsed.set(database="postgres").render_as_string(
            hide_password=False
        )
        self._maintenance = psycopg2.connect(maintenance_url)
        self._maintenance.autocommit = True
        self._created = False
        self.engine = None

    def setup(self) -> None:
        with self._maintenance.cursor() as cursor:
            cursor.execute(
                "SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = %s)",
                ("gda_control_gateway",),
            )
            if not cursor.fetchone()[0]:
                raise RuntimeError("gda_control_gateway role must preexist")
            cursor.execute(
                "SELECT EXISTS (SELECT 1 FROM pg_database WHERE datname = %s)",
                (self.database,),
            )
            if cursor.fetchone()[0]:
                raise RuntimeError("random certification database already exists")
            cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(self.database)))
            self._created = True

        self.engine = create_engine(self.database_url, pool_size=1, max_overflow=0)
        with self.engine.begin() as connection:
            for migration in MIGRATIONS:
                connection.execute(text(migration.read_text(encoding="utf-8")))

    def cleanup(self) -> dict[str, bool]:
        if self.engine is not None:
            self.engine.dispose()
        with self._maintenance.cursor() as cursor:
            if self._created:
                cursor.execute(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = %s AND pid <> pg_backend_pid()",
                    (self.database,),
                )
                cursor.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(self.database)))
            cursor.execute(
                "SELECT NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = %s)",
                (self.database,),
            )
            database_removed = bool(cursor.fetchone()[0])
        self._maintenance.close()
        return {"database_removed": database_removed}


def _definition_registration(
    tenant_id: str,
    definition_version_id: UUID,
    name: str,
    created_at: datetime,
) -> DefinitionRegistration:
    definition_urn = f"gda://{tenant_id}/definition/{name}"
    definition_document = {"kind": "source_sync", "revision": 1}
    input_contract = {"type": "object", "required": ["source"]}
    output_contract = {"type": "object", "required": ["target"]}
    definition_sha256 = platform_definition_fingerprint(
        orchestration_class="dataops",
        capability_id="source.sync",
        portability_class="portable",
        definition_document=definition_document,
        input_contract=input_contract,
        output_contract=output_contract,
    )
    resource = Resource(
        tenant_id=tenant_id,
        resource_urn=definition_urn,
        resource_kind="definition",
        authority_system="gda_control",
        authority_locator=definition_urn,
        owner_ref="team:data-platform",
    )
    version = ResourceVersion(
        tenant_id=tenant_id,
        resource_urn=definition_urn,
        resource_version_id=definition_version_id,
        version_key=f"sha256-{definition_sha256[:12]}",
        content_sha256=definition_sha256,
        authority_version_ref={"capability_id": "source.sync"},
        created_by=WORKLOAD,
        created_at=created_at,
    )
    definition = PlatformDefinitionVersion(
        tenant_id=tenant_id,
        definition_urn=definition_urn,
        definition_version_id=definition_version_id,
        orchestration_class="dataops",
        capability_id="source.sync",
        portability_class="portable",
        definition_document=definition_document,
        input_contract=input_contract,
        output_contract=output_contract,
        definition_sha256=definition_sha256,
    )
    return DefinitionRegistration(
        resource=resource,
        resource_version=version,
        definition=definition,
    )


def _sync_definition(
    tenant_id: str,
    sync_definition_version_id: UUID,
    platform_definition_version_id: UUID,
    created_at: datetime,
    *,
    name: str = "osm-roads-incremental-v1",
    source_resource_urn: str | None = None,
    target_resource_urn: str | None = None,
    governance_overrides: dict[str, Any] | None = None,
) -> SourceSyncDefinitionVersion:
    governance: dict[str, Any] = {
        "schema": "gda.source_sync_governance.v1",
        "target_layer": "ods",
        "data_kind": "vector",
        "capture_kind": "micro_batch",
        "source_adapter": {
            "adapter_id": "source-sync-certification",
            "adapter_version": "1.0.0",
            "adapter_fingerprint": "d" * 64,
        },
        "standard_mapping_contract_id": None,
        "standard_version_id": None,
        "data_model_version_id": None,
        "quality_rule_version_refs": ["quality:source-integrity-v1"],
        "classification_policy_version_ref": "classification:internal-v1",
        "retention_policy_version_ref": "retention:ods-v1",
        "schema_change_policy": "approval_required",
        "promotion_mode": "blocked",
        "quarantine_resource_urn": None,
        "event_time_field": None,
        "watermark_delay_seconds": None,
    }
    governance.update(governance_overrides or {})
    values: dict[str, Any] = {
        "tenant_id": tenant_id,
        "sync_definition_urn": f"gda://{tenant_id}/sync_definition/{name}",
        "sync_definition_version_id": sync_definition_version_id,
        "platform_definition_version_id": platform_definition_version_id,
        "source_resource_urn": source_resource_urn
        or f"gda://{tenant_id}/source/osm-roads",
        "source_definition_fingerprint": "a" * 64,
        "target_resource_urn": target_resource_urn
        or f"gda://{tenant_id}/table/osm-roads-bronze",
        "mode": "incremental",
        "write_disposition": "merge",
        "cursor_kind": "field",
        "cursor_field": "updated_at",
        "primary_keys": ("road_id",),
        "delete_mode": "hard_delete",
        "config": {"late_arrival_seconds": 300},
        "governance_contract": governance,
    }
    return SourceSyncDefinitionVersion(
        **values,
        definition_sha256=source_sync_definition_fingerprint(**values),
        created_by=WORKLOAD,
        created_at=created_at,
    )


def _run(
    tenant_id: str,
    run_id: UUID,
    definition_version_id: UUID,
    submitted_at: datetime,
    *,
    subject_id: str = "dataops-controller",
    sequence: str,
) -> PlatformRun:
    return PlatformRun(
        tenant_id=tenant_id,
        run_id=run_id,
        definition_version_id=definition_version_id,
        orchestration_class="dataops",
        subject_context=SubjectContext(
            tenant_id=tenant_id,
            subject_id=subject_id,
            subject_type="workload",
            roles=("platform_operator",),
            purpose="certify source sync commit authority",
        ),
        idempotency_key=f"source-sync-certification:{sequence}",
        submitted_at=submitted_at,
    )


def _submit_run(
    gateway: PlatformGateway,
    run: PlatformRun,
    *,
    running: bool = True,
) -> PlatformRun:
    stored = gateway.submit_run(run).value
    if not running:
        return stored
    dispatching = gateway.transition_run(
        run.tenant_id,
        run.run_id,
        0,
        "dispatching",
        WORKLOAD,
        "source sync certification dispatch",
    )
    return gateway.transition_run(
        run.tenant_id,
        run.run_id,
        dispatching.state_version,
        "running",
        WORKLOAD,
        "source sync certification execution",
    )


def _commit(
    *,
    tenant_id: str,
    sync_commit_id: UUID,
    sync_definition_version_id: UUID,
    run_id: UUID,
    committed_at: datetime,
    committed_by: str = WORKLOAD,
    **overrides: Any,
) -> SourceSyncCommit:
    values: dict[str, Any] = {
        "tenant_id": tenant_id,
        "sync_commit_id": sync_commit_id,
        "sync_definition_version_id": sync_definition_version_id,
        "run_id": run_id,
        "from_state_version": 0,
        "to_state_version": 1,
        "previous_cursor": {
            "updated_at": "2026-08-02T00:00:00Z",
            "road_id": "r-000",
        },
        "next_cursor": {
            "updated_at": "2026-08-02T01:00:00Z",
            "road_id": "r-100",
        },
        "source_slice_sha256": "b" * 64,
        "target_commit_ref": {"provider": "iceberg", "snapshot_id": 1001},
        "target_content_sha256": "c" * 64,
        "records_read": 3,
        "records_inserted": 1,
        "records_updated": 1,
        "records_deleted": 1,
        "records_output": 50366,
        "committed_by": committed_by,
        "committed_at": committed_at,
    }
    values.update(overrides)
    return SourceSyncCommit(
        **values,
        previous_cursor_sha256=canonical_json_fingerprint(values["previous_cursor"]),
        next_cursor_sha256=canonical_json_fingerprint(values["next_cursor"]),
        commit_sha256=source_sync_commit_fingerprint(**values),
    )


def _commit_governance_evidence(
    *,
    tenant_id: str,
    sync_commit_id: UUID,
    target_resource_version_id: UUID,
    output_artifact_id: UUID,
    quality_result_ids: tuple[UUID, ...],
    lineage_event_id: UUID,
    metadata_change_id: UUID,
    approval_case_ref: str | None = None,
) -> SourceSyncCommitGovernanceEvidence:
    values = {
        "tenant_id": tenant_id,
        "sync_commit_id": sync_commit_id,
        "target_resource_version_id": target_resource_version_id,
        "output_artifact_id": output_artifact_id,
        "quality_result_ids": tuple(sorted(quality_result_ids, key=str)),
        "lineage_event_id": lineage_event_id,
        "metadata_change_id": metadata_change_id,
        "approval_case_ref": approval_case_ref,
    }
    return SourceSyncCommitGovernanceEvidence(
        **values,
        evidence_sha256=source_sync_commit_governance_evidence_fingerprint(**values),
    )


def _quarantine_evidence(
    *,
    tenant_id: str,
    sync_commit_id: UUID,
    source_slice_sha256: str,
    quarantine_resource_version_id: UUID,
    quarantine_artifact_id: UUID,
    records_rejected: int,
    reason_counts: dict[str, int],
) -> SourceSyncQuarantineEvidence:
    values = {
        "tenant_id": tenant_id,
        "sync_commit_id": sync_commit_id,
        "source_slice_sha256": source_slice_sha256,
        "quarantine_resource_version_id": quarantine_resource_version_id,
        "quarantine_artifact_id": quarantine_artifact_id,
        "records_rejected": records_rejected,
        "reason_counts": reason_counts,
    }
    return SourceSyncQuarantineEvidence(
        **values,
        evidence_sha256=source_sync_quarantine_evidence_fingerprint(**values),
    )


def _register_resource_version(
    gateway: PlatformGateway,
    *,
    tenant_id: str,
    resource_urn: str,
    resource_version_id: UUID,
    content_sha256: str,
    created_at: datetime,
) -> ResourceVersion:
    resource = Resource(
        tenant_id=tenant_id,
        resource_urn=resource_urn,
        resource_kind=resource_urn.split("/")[3],
        authority_system="gda_control",
        authority_locator=resource_urn,
        owner_ref="team:data-platform",
    )
    gateway.register_resource(resource)
    version = ResourceVersion(
        tenant_id=tenant_id,
        resource_urn=resource_urn,
        resource_version_id=resource_version_id,
        version_key=f"sha256-{content_sha256[:12]}",
        content_sha256=content_sha256,
        authority_version_ref={"certification": "source-sync-governance"},
        created_by=WORKLOAD,
        created_at=created_at,
    )
    gateway.register_resource_version(version)
    return version


def _register_resource_only(
    gateway: PlatformGateway,
    *,
    tenant_id: str,
    resource_urn: str,
) -> None:
    gateway.register_resource(
        Resource(
            tenant_id=tenant_id,
            resource_urn=resource_urn,
            resource_kind=resource_urn.split("/")[3],
            authority_system="gda_control",
            authority_locator=resource_urn,
            owner_ref="team:data-platform",
        )
    )


def _metadata_change_id(engine, tenant_id: str, lineage_event_id: UUID) -> UUID:
    with engine.begin() as connection:
        connection.exec_driver_sql('SET LOCAL ROLE "gda_control_gateway"')
        connection.execute(
            text("SELECT set_config('app.current_tenant', :tenant, true)"),
            {"tenant": tenant_id},
        )
        return connection.execute(
            text(
                """
                SELECT change_id
                FROM gda_control.metadata_change_outbox
                WHERE tenant_id = :tenant_id
                  AND aggregate_id = :lineage_event_id
                  AND change_type = 'lineage_upsert'
                  AND destination_ref = 'openmetadata:default'
                """
            ),
            {"tenant_id": tenant_id, "lineage_event_id": lineage_event_id},
        ).scalar_one()


def _governed_counts(
    engine,
    tenant_id: str,
    sync_definition_version_id: UUID,
) -> tuple[int, int, int, int]:
    with engine.begin() as connection:
        connection.exec_driver_sql('SET LOCAL ROLE "gda_control_gateway"')
        connection.execute(
            text("SELECT set_config('app.current_tenant', :tenant, true)"),
            {"tenant": tenant_id},
        )
        row = connection.execute(
            text(
                """
                SELECT
                    (SELECT state_version
                     FROM gda_control.source_sync_checkpoint
                     WHERE tenant_id = :tenant_id
                       AND sync_definition_version_id = :definition_id),
                    (SELECT count(*)
                     FROM gda_control.source_sync_commit
                     WHERE tenant_id = :tenant_id
                       AND sync_definition_version_id = :definition_id),
                    (SELECT count(*)
                     FROM gda_control.source_sync_commit_governance_evidence AS evidence
                     JOIN gda_control.source_sync_commit AS commit
                       ON commit.tenant_id = evidence.tenant_id
                      AND commit.sync_commit_id = evidence.sync_commit_id
                     WHERE commit.tenant_id = :tenant_id
                       AND commit.sync_definition_version_id = :definition_id),
                    (SELECT count(*)
                     FROM gda_control.source_sync_quarantine_evidence AS evidence
                     JOIN gda_control.source_sync_commit AS commit
                       ON commit.tenant_id = evidence.tenant_id
                      AND commit.sync_commit_id = evidence.sync_commit_id
                     WHERE commit.tenant_id = :tenant_id
                       AND commit.sync_definition_version_id = :definition_id)
                """
            ),
            {"tenant_id": tenant_id, "definition_id": sync_definition_version_id},
        ).one()
    return tuple(int(value) for value in row)


def _expect_governance_rejection(
    authority: SourceSyncAuthority,
    commit: SourceSyncCommit,
    evidence: SourceSyncCommitGovernanceEvidence | None,
    quarantine_evidence: SourceSyncQuarantineEvidence | None = None,
) -> bool:
    try:
        authority.commit(commit, evidence, quarantine_evidence)
    except SourceSyncValidationError:
        return True
    return False


def _direct_statement_denied(
    engine,
    tenant_id: str,
    statement: str,
    parameters: dict[str, Any],
    *,
    gateway_role: bool,
    expected_sqlstates: frozenset[str] = frozenset({"42501", "55000"}),
) -> bool:
    try:
        with engine.begin() as connection:
            if gateway_role:
                connection.exec_driver_sql('SET LOCAL ROLE "gda_control_gateway"')
            connection.execute(
                text("SELECT set_config('app.current_tenant', :tenant, true)"),
                {"tenant": tenant_id},
            )
            connection.execute(text(statement), parameters)
    except DBAPIError as exc:
        return _sqlstate(exc) in expected_sqlstates
    return False


def _database_controls(engine, tenant_id: str, sync_version_id: UUID) -> dict[str, bool]:
    missing_governance_insert = """
        INSERT INTO gda_control.source_sync_definition (
            tenant_id, sync_definition_urn, sync_definition_version_id,
            platform_definition_version_id, source_resource_urn,
            source_definition_fingerprint, target_resource_urn, mode,
            write_disposition, cursor_kind, cursor_field, primary_keys,
            delete_mode, config, definition_sha256, created_by, created_at
        )
        SELECT tenant_id, sync_definition_urn, gen_random_uuid(),
               platform_definition_version_id, source_resource_urn,
               source_definition_fingerprint, target_resource_urn, mode,
               write_disposition, cursor_kind, cursor_field, primary_keys,
               delete_mode, config, definition_sha256, created_by, created_at
        FROM gda_control.source_sync_definition
        WHERE tenant_id = :tenant_id
          AND sync_definition_version_id = :sync_definition_version_id
    """
    duplicate_quality_insert = """
        INSERT INTO gda_control.source_sync_definition (
            tenant_id, sync_definition_urn, sync_definition_version_id,
            platform_definition_version_id, source_resource_urn,
            source_definition_fingerprint, target_resource_urn, mode,
            write_disposition, cursor_kind, cursor_field, primary_keys,
            delete_mode, config, governance_contract, definition_sha256,
            created_by, created_at
        )
        SELECT tenant_id, sync_definition_urn, gen_random_uuid(),
               platform_definition_version_id, source_resource_urn,
               source_definition_fingerprint, target_resource_urn, mode,
               write_disposition, cursor_kind, cursor_field, primary_keys,
               delete_mode, config,
               jsonb_set(
                   governance_contract,
                   '{quality_rule_version_refs}',
                   '["quality:duplicate-v1","quality:duplicate-v1"]'::jsonb
               ),
               definition_sha256, created_by, created_at
        FROM gda_control.source_sync_definition
        WHERE tenant_id = :tenant_id
          AND sync_definition_version_id = :sync_definition_version_id
    """
    checkpoint_update = """
        UPDATE gda_control.source_sync_checkpoint
        SET updated_at = updated_at
        WHERE tenant_id = :tenant_id
          AND sync_definition_version_id = :sync_definition_version_id
    """
    commit_insert = """
        INSERT INTO gda_control.source_sync_commit
        SELECT tenant_id, gen_random_uuid(), sync_definition_version_id, run_id,
               from_state_version, to_state_version,
               previous_cursor, previous_cursor_sha256,
               next_cursor, next_cursor_sha256,
               source_slice_sha256, target_commit_ref, target_content_sha256,
               records_read, records_inserted, records_updated, records_deleted,
               records_output, committed_by, committed_at, commit_sha256
        FROM gda_control.source_sync_commit
        WHERE tenant_id = :tenant_id
          AND sync_definition_version_id = :sync_definition_version_id
    """
    commit_update = """
        UPDATE gda_control.source_sync_commit
        SET target_content_sha256 = :target_content_sha256
        WHERE tenant_id = :tenant_id
          AND sync_definition_version_id = :sync_definition_version_id
    """
    governance_evidence_insert = """
        INSERT INTO gda_control.source_sync_commit_governance_evidence (
            tenant_id, sync_commit_id, target_resource_version_id,
            output_artifact_id, quality_result_ids, lineage_event_id,
            metadata_change_id, approval_case_ref, evidence_sha256
        ) VALUES (
            :tenant_id, gen_random_uuid(), gen_random_uuid(), gen_random_uuid(),
            ARRAY[gen_random_uuid()], gen_random_uuid(), gen_random_uuid(),
            NULL, repeat('f', 64)
        )
    """
    quarantine_evidence_insert = """
        INSERT INTO gda_control.source_sync_quarantine_evidence (
            tenant_id, sync_commit_id, source_slice_sha256,
            quarantine_resource_version_id, quarantine_artifact_id,
            records_rejected, reason_counts, evidence_sha256
        ) VALUES (
            :tenant_id, gen_random_uuid(), repeat('a', 64),
            gen_random_uuid(), gen_random_uuid(), 1,
            jsonb_build_object('forged', 1), repeat('f', 64)
        )
    """
    params = {
        "tenant_id": tenant_id,
        "sync_definition_version_id": sync_version_id,
    }
    with engine.connect() as connection:
        privileges = connection.execute(
            text(
                """
                SELECT
                    has_table_privilege(
                        'gda_control_gateway',
                        'gda_control.source_sync_checkpoint', 'UPDATE'
                    ),
                    has_table_privilege(
                        'gda_control_gateway',
                        'gda_control.source_sync_commit', 'INSERT'
                    ),
                    EXISTS (
                        SELECT 1
                        FROM pg_proc p
                        JOIN pg_namespace n ON n.oid = p.pronamespace
                        WHERE n.nspname = 'gda_control'
                          AND p.proname = 'commit_source_sync'
                          AND has_function_privilege(
                              'gda_control_gateway', p.oid, 'EXECUTE'
                          )
                    ),
                    EXISTS (
                        SELECT 1
                        FROM pg_constraint
                        WHERE conname = 'fk_gda_source_sync_checkpoint_last_commit'
                    ),
                    EXISTS (
                        SELECT 1
                        FROM information_schema.columns
                        WHERE table_schema = 'gda_control'
                          AND table_name = 'source_sync_definition'
                          AND column_name = 'governance_contract'
                    ),
                    EXISTS (
                        SELECT 1
                        FROM pg_constraint
                        WHERE conname = 'ck_gda_source_sync_governance_contract'
                    ),
                    EXISTS (
                        SELECT 1
                        FROM pg_proc p
                        JOIN pg_namespace n ON n.oid = p.pronamespace
                        WHERE n.nspname = 'gda_control'
                          AND p.proname = 'source_sync_quality_refs_valid'
                          AND has_function_privilege(
                              'gda_control_gateway', p.oid, 'EXECUTE'
                          )
                    ),
                    has_table_privilege(
                        'gda_control_gateway',
                        'gda_control.source_sync_commit_governance_evidence',
                        'INSERT'
                    ),
                    EXISTS (
                        SELECT 1
                        FROM pg_proc p
                        JOIN pg_namespace n ON n.oid = p.pronamespace
                        WHERE n.nspname = 'gda_control'
                          AND p.proname = 'commit_source_sync_v104'
                          AND has_function_privilege(
                              'gda_control_gateway', p.oid, 'EXECUTE'
                          )
                    ),
                    EXISTS (
                        SELECT 1
                        FROM pg_constraint
                        WHERE conname =
                            'fk_gda_source_sync_commit_governance_commit'
                    ),
                    has_table_privilege(
                        'gda_control_gateway',
                        'gda_control.source_sync_quarantine_evidence',
                        'INSERT'
                    ),
                    has_function_privilege(
                        'gda_control_gateway',
                        'gda_control.bind_source_sync_quarantine_evidence(text,uuid,jsonb)',
                        'EXECUTE'
                    ),
                    EXISTS (
                        SELECT 1
                        FROM pg_constraint
                        WHERE conname = 'fk_gda_source_sync_quarantine_commit'
                    ),
                    EXISTS (
                        SELECT 1
                        FROM pg_trigger
                        WHERE tgname =
                            'trg_gda_source_sync_commit_requires_quarantine'
                          AND tgconstraint <> 0
                          AND tgdeferrable
                          AND tginitdeferred
                    )
                """
            )
        ).one()
        rls_rows = connection.execute(
            text(
                """
                SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'gda_control'
                  AND c.relname IN (
                      'source_sync_definition',
                      'source_sync_checkpoint',
                      'source_sync_commit',
                      'source_sync_commit_governance_evidence',
                      'source_sync_quarantine_evidence'
                  )
                """
            )
        ).all()
        connection.rollback()
    rls = {row[0]: bool(row[1] and row[2]) for row in rls_rows}
    return {
        "gateway_checkpoint_update_denied": not bool(privileges[0]),
        "gateway_commit_insert_denied": not bool(privileges[1]),
        "gateway_commit_function_execute": bool(privileges[2]),
        "checkpoint_commit_fk_present": bool(privileges[3]),
        "governance_contract_column_present": bool(privileges[4]),
        "governance_contract_check_present": bool(privileges[5]),
        "gateway_quality_validator_execute": bool(privileges[6]),
        "gateway_governance_evidence_insert_denied": not bool(privileges[7]),
        "gateway_v104_commit_primitive_execute_denied": not bool(privileges[8]),
        "governance_evidence_commit_fk_present": bool(privileges[9]),
        "gateway_quarantine_evidence_insert_denied": not bool(privileges[10]),
        "gateway_quarantine_bind_function_execute": bool(privileges[11]),
        "quarantine_evidence_commit_fk_present": bool(privileges[12]),
        "quarantine_evidence_requirement_is_deferred": bool(privileges[13]),
        "gateway_missing_governance_rejected": _direct_statement_denied(
            engine,
            tenant_id,
            missing_governance_insert,
            params,
            gateway_role=True,
            expected_sqlstates=frozenset({"23514"}),
        ),
        "gateway_duplicate_quality_refs_rejected": _direct_statement_denied(
            engine,
            tenant_id,
            duplicate_quality_insert,
            params,
            gateway_role=True,
            expected_sqlstates=frozenset({"23514"}),
        ),
        "rls_forced_on_all_sync_tables": len(rls) == 5 and all(rls.values()),
        "direct_checkpoint_update_denied": _direct_statement_denied(
            engine, tenant_id, checkpoint_update, params, gateway_role=False
        ),
        "direct_commit_insert_denied": _direct_statement_denied(
            engine, tenant_id, commit_insert, params, gateway_role=False
        ),
        "gateway_checkpoint_update_statement_denied": _direct_statement_denied(
            engine, tenant_id, checkpoint_update, params, gateway_role=True
        ),
        "gateway_commit_insert_statement_denied": _direct_statement_denied(
            engine, tenant_id, commit_insert, params, gateway_role=True
        ),
        "direct_governance_evidence_insert_denied": _direct_statement_denied(
            engine,
            tenant_id,
            governance_evidence_insert,
            params,
            gateway_role=False,
        ),
        "gateway_governance_evidence_insert_statement_denied": (
            _direct_statement_denied(
                engine,
                tenant_id,
                governance_evidence_insert,
                params,
                gateway_role=True,
            )
        ),
        "direct_quarantine_evidence_insert_denied": _direct_statement_denied(
            engine,
            tenant_id,
            quarantine_evidence_insert,
            params,
            gateway_role=False,
        ),
        "gateway_quarantine_evidence_insert_statement_denied": (
            _direct_statement_denied(
                engine,
                tenant_id,
                quarantine_evidence_insert,
                params,
                gateway_role=True,
            )
        ),
        "append_only_commit_mutation_denied": _direct_statement_denied(
            engine,
            tenant_id,
            commit_update,
            params | {"target_content_sha256": "f" * 64},
            gateway_role=False,
        ),
    }


def _tenant_hidden(engine, visible_tenant: str, hidden_tenant: str) -> bool:
    with engine.begin() as connection:
        connection.exec_driver_sql('SET LOCAL ROLE "gda_control_gateway"')
        connection.execute(
            text("SELECT set_config('app.current_tenant', :tenant, true)"),
            {"tenant": visible_tenant},
        )
        visible_count = connection.execute(
            text(
                """
                SELECT count(*)
                FROM gda_control.source_sync_definition
                WHERE tenant_id = :hidden_tenant
                """
            ),
            {"hidden_tenant": hidden_tenant},
        ).scalar_one()
    return visible_count == 0


def _certify_governed_silver(
    engine,
    *,
    tenant_id: str,
    now: datetime,
) -> dict[str, Any]:
    gateway = PlatformGateway(engine)
    authority = SourceSyncAuthority(engine)
    platform_definition_id = uuid4()
    sync_definition_version_id = uuid4()
    run_id = uuid4()
    replay_run_id = uuid4()
    source_urn = f"gda://{tenant_id}/source/roads-silver-input"
    target_urn = f"gda://{tenant_id}/table/roads-silver"
    quarantine_urn = f"gda://{tenant_id}/table/roads-quarantine"
    source_version_id = uuid4()
    target_version_id = uuid4()
    quarantine_version_id = uuid4()
    target_content_sha256 = "c" * 64
    rejected_content_sha256 = "6" * 64
    quality_rule_refs = ("quality:geometry-v1", "quality:standard-v1")

    gateway.register_definition(
        _definition_registration(
            tenant_id,
            platform_definition_id,
            "source-sync-silver-v1",
            now,
        )
    )
    _register_resource_version(
        gateway,
        tenant_id=tenant_id,
        resource_urn=source_urn,
        resource_version_id=source_version_id,
        content_sha256="a" * 64,
        created_at=now,
    )
    _register_resource_version(
        gateway,
        tenant_id=tenant_id,
        resource_urn=target_urn,
        resource_version_id=target_version_id,
        content_sha256=target_content_sha256,
        created_at=now,
    )
    _register_resource_version(
        gateway,
        tenant_id=tenant_id,
        resource_urn=quarantine_urn,
        resource_version_id=quarantine_version_id,
        content_sha256=rejected_content_sha256,
        created_at=now,
    )

    definition = _sync_definition(
        tenant_id,
        sync_definition_version_id,
        platform_definition_id,
        now,
        name="roads-silver-v1",
        source_resource_urn=source_urn,
        target_resource_urn=target_urn,
        governance_overrides={
            "target_layer": "silver",
            "standard_mapping_contract_id": uuid4(),
            "standard_version_id": uuid4(),
            "data_model_version_id": uuid4(),
            "quality_rule_version_refs": list(quality_rule_refs),
            "retention_policy_version_ref": "retention:silver-v1",
            "promotion_mode": "quality_gated",
            "quarantine_resource_urn": quarantine_urn,
        },
    )
    initial_cursor = {
        "updated_at": "2026-08-02T00:00:00Z",
        "road_id": "r-000",
    }
    authority.create_definition(
        definition,
        owner_ref="team:data-platform",
        initial_cursor=initial_cursor,
    )
    _submit_run(
        gateway,
        _run(
            tenant_id,
            run_id,
            platform_definition_id,
            now + timedelta(seconds=1),
            sequence="silver-primary",
        ),
    )
    _submit_run(
        gateway,
        _run(
            tenant_id,
            replay_run_id,
            platform_definition_id,
            now + timedelta(seconds=2),
            sequence="silver-replay",
        ),
    )

    evidence_time = now + timedelta(minutes=1)
    output = Artifact(
        tenant_id=tenant_id,
        artifact_id=uuid4(),
        artifact_key="roads-silver-output",
        artifact_role="output",
        storage_uri=f"s3://source-sync-cert/{tenant_id}/roads-silver.parquet",
        media_type="application/vnd.apache.parquet",
        content_sha256=target_content_sha256,
        size_bytes=4096,
        run_id=run_id,
        resource_version_id=target_version_id,
        manifest={"row_count": 50366},
        created_by=WORKLOAD,
        created_at=evidence_time,
    )
    quality_evaluator = "workload:quality-evaluator"
    quality_artifact = Artifact(
        tenant_id=tenant_id,
        artifact_id=uuid4(),
        artifact_key="roads-silver-quality-evidence",
        artifact_role="evidence",
        storage_uri=f"s3://source-sync-cert/{tenant_id}/roads-silver-quality.json",
        media_type="application/vnd.gda.quality-evidence+json",
        content_sha256="e" * 64,
        size_bytes=512,
        run_id=run_id,
        resource_version_id=target_version_id,
        manifest={"checks": list(quality_rule_refs)},
        created_by=quality_evaluator,
        created_at=evidence_time,
    )
    quarantine_manifest = {
        "schema": "gda.source_sync_quarantine.v1",
        "source_slice_sha256": "b" * 64,
        "sync_definition_version_id": str(sync_definition_version_id),
        "records_rejected": 2,
        "reason_counts": {"duplicate": 1, "late": 1},
        "target_content_sha256": target_content_sha256,
        "rejected_content_sha256": rejected_content_sha256,
    }

    def quarantine_artifact(
        artifact_key: str,
        *,
        artifact_role: str = "quarantine",
        artifact_run_id: UUID = run_id,
    ) -> Artifact:
        return Artifact(
            tenant_id=tenant_id,
            artifact_id=uuid4(),
            artifact_key=artifact_key,
            artifact_role=artifact_role,
            storage_uri=(
                f"s3://source-sync-cert/{tenant_id}/{artifact_key}.jsonl"
            ),
            media_type="application/x-ndjson",
            content_sha256=rejected_content_sha256,
            size_bytes=256,
            run_id=artifact_run_id,
            resource_version_id=quarantine_version_id,
            manifest=quarantine_manifest,
            created_by=WORKLOAD,
            created_at=evidence_time,
        )

    quarantine = quarantine_artifact("roads-silver-quarantine")
    alternate_quarantine = quarantine_artifact("roads-silver-quarantine-alternate")
    wrong_role_quarantine = quarantine_artifact(
        "roads-silver-quarantine-wrong-role",
        artifact_role="evidence",
    )
    wrong_run_quarantine = quarantine_artifact(
        "roads-silver-quarantine-wrong-run",
        artifact_run_id=replay_run_id,
    )
    gateway.record_artifact(output)
    gateway.record_artifact(quality_artifact)
    for artifact in (
        quarantine,
        alternate_quarantine,
        wrong_role_quarantine,
        wrong_run_quarantine,
    ):
        gateway.record_artifact(artifact)

    def quality_result(
        rule_version_ref: str,
        verdict: str,
        evaluated_by: str,
    ) -> QualityResult:
        quality_result_id = uuid4()
        metrics = {"checked": 50366, "violations": 0 if verdict == "passed" else 1}
        return QualityResult(
            tenant_id=tenant_id,
            quality_result_id=quality_result_id,
            run_id=run_id,
            resource_version_id=target_version_id,
            rule_version_ref=rule_version_ref,
            verdict=verdict,
            metrics=metrics,
            evidence_artifact_id=quality_artifact.artifact_id,
            result_sha256=quality_result_fingerprint(
                tenant_id=tenant_id,
                run_id=run_id,
                resource_version_id=target_version_id,
                rule_version_ref=rule_version_ref,
                verdict=verdict,
                metrics=metrics,
                evidence_artifact_id=quality_artifact.artifact_id,
                evaluated_by=evaluated_by,
                evaluated_at=evidence_time,
            ),
            evaluated_by=evaluated_by,
            evaluated_at=evidence_time,
        )

    passed_geometry = quality_result(quality_rule_refs[0], "passed", quality_evaluator)
    passed_standard = quality_result(quality_rule_refs[1], "passed", quality_evaluator)
    failed_geometry = quality_result(quality_rule_refs[0], "failed", quality_evaluator)
    same_actor_geometry = quality_result(quality_rule_refs[0], "passed", WORKLOAD)
    for quality in (
        passed_geometry,
        passed_standard,
        failed_geometry,
        same_actor_geometry,
    ):
        gateway.record_quality_result(quality)

    lineage = LineageEvent(
        tenant_id=tenant_id,
        lineage_event_id=uuid4(),
        event_type="materialize",
        source_resource_version_id=source_version_id,
        target_resource_version_id=target_version_id,
        producer=WORKLOAD,
        event_sha256=canonical_json_fingerprint(
            {
                "source": str(source_version_id),
                "target": str(target_version_id),
                "run": str(run_id),
                "artifact": str(output.artifact_id),
            }
        ),
        run_id=run_id,
        definition_version_id=platform_definition_id,
        artifact_id=output.artifact_id,
        facets={"capture_kind": "micro_batch", "target_layer": "silver"},
        occurred_at=evidence_time,
    )
    gateway.record_lineage(lineage)
    metadata_change_id = _metadata_change_id(engine, tenant_id, lineage.lineage_event_id)

    commit = _commit(
        tenant_id=tenant_id,
        sync_commit_id=uuid4(),
        sync_definition_version_id=sync_definition_version_id,
        run_id=run_id,
        committed_at=now + timedelta(minutes=2),
        target_content_sha256=target_content_sha256,
    )

    def evidence(
        quality_result_ids: tuple[UUID, ...],
        **overrides: Any,
    ) -> SourceSyncCommitGovernanceEvidence:
        values: dict[str, Any] = {
            "tenant_id": tenant_id,
            "sync_commit_id": commit.sync_commit_id,
            "target_resource_version_id": target_version_id,
            "output_artifact_id": output.artifact_id,
            "quality_result_ids": quality_result_ids,
            "lineage_event_id": lineage.lineage_event_id,
            "metadata_change_id": metadata_change_id,
        }
        values.update(overrides)
        return _commit_governance_evidence(**values)

    valid_evidence = evidence(
        (passed_geometry.quality_result_id, passed_standard.quality_result_id)
    )

    def quarantine_evidence(
        *,
        artifact_id: UUID = quarantine.artifact_id,
        resource_version_id: UUID = quarantine_version_id,
        records_rejected: int = 2,
        reason_counts: dict[str, int] | None = None,
    ) -> SourceSyncQuarantineEvidence:
        return _quarantine_evidence(
            tenant_id=tenant_id,
            sync_commit_id=commit.sync_commit_id,
            source_slice_sha256=commit.source_slice_sha256,
            quarantine_resource_version_id=resource_version_id,
            quarantine_artifact_id=artifact_id,
            records_rejected=records_rejected,
            reason_counts=reason_counts or {"duplicate": 1, "late": 1},
        )

    valid_quarantine_evidence = quarantine_evidence()
    before_failures = _governed_counts(
        engine, tenant_id, sync_definition_version_id
    )
    rejection_checks = {
        "silver_missing_governance_evidence_rejected":
            _expect_governance_rejection(
                authority, commit, None, valid_quarantine_evidence
            ),
        "silver_missing_quality_rule_rejected": _expect_governance_rejection(
            authority,
            commit,
            evidence((passed_geometry.quality_result_id,)),
            valid_quarantine_evidence,
        ),
        "silver_failed_quality_rejected": _expect_governance_rejection(
            authority,
            commit,
            evidence(
                (failed_geometry.quality_result_id, passed_standard.quality_result_id)
            ),
            valid_quarantine_evidence,
        ),
        "silver_same_actor_quality_rejected": _expect_governance_rejection(
            authority,
            commit,
            evidence(
                (
                    same_actor_geometry.quality_result_id,
                    passed_standard.quality_result_id,
                )
            ),
            valid_quarantine_evidence,
        ),
        "silver_wrong_target_version_rejected": _expect_governance_rejection(
            authority,
            commit,
            evidence(
                valid_evidence.quality_result_ids,
                target_resource_version_id=source_version_id,
            ),
            valid_quarantine_evidence,
        ),
        "silver_wrong_output_artifact_rejected": _expect_governance_rejection(
            authority,
            commit,
            evidence(
                valid_evidence.quality_result_ids,
                output_artifact_id=quality_artifact.artifact_id,
            ),
            valid_quarantine_evidence,
        ),
        "silver_wrong_lineage_rejected": _expect_governance_rejection(
            authority,
            commit,
            evidence(valid_evidence.quality_result_ids, lineage_event_id=uuid4()),
            valid_quarantine_evidence,
        ),
        "silver_wrong_metadata_outbox_rejected": _expect_governance_rejection(
            authority,
            commit,
            evidence(valid_evidence.quality_result_ids, metadata_change_id=uuid4()),
            valid_quarantine_evidence,
        ),
        "silver_missing_quarantine_evidence_rejected": _expect_governance_rejection(
            authority, commit, valid_evidence
        ),
        "silver_wrong_quarantine_role_rejected": _expect_governance_rejection(
            authority,
            commit,
            valid_evidence,
            quarantine_evidence(artifact_id=wrong_role_quarantine.artifact_id),
        ),
        "silver_wrong_quarantine_run_rejected": _expect_governance_rejection(
            authority,
            commit,
            valid_evidence,
            quarantine_evidence(artifact_id=wrong_run_quarantine.artifact_id),
        ),
        "silver_wrong_quarantine_count_rejected": _expect_governance_rejection(
            authority,
            commit,
            valid_evidence,
            quarantine_evidence(records_rejected=1, reason_counts={"duplicate": 1}),
        ),
        "silver_forged_quarantine_resource_rejected": _expect_governance_rejection(
            authority,
            commit,
            valid_evidence,
            quarantine_evidence(resource_version_id=source_version_id),
        ),
    }
    after_failures = _governed_counts(
        engine, tenant_id, sync_definition_version_id
    )

    first_write = authority.commit(commit, valid_evidence, valid_quarantine_evidence)
    same_id_replay = authority.commit(
        commit, valid_evidence, valid_quarantine_evidence
    )
    mismatched_replay_rejected = False
    try:
        authority.commit(
            commit,
            evidence(valid_evidence.quality_result_ids, metadata_change_id=uuid4()),
        )
    except SourceSyncConflictError:
        mismatched_replay_rejected = True
    mismatched_quarantine_replay_rejected = False
    try:
        authority.commit(
            commit,
            valid_evidence,
            quarantine_evidence(artifact_id=alternate_quarantine.artifact_id),
        )
    except SourceSyncConflictError:
        mismatched_quarantine_replay_rejected = True

    cross_run_commit = _commit(
        tenant_id=tenant_id,
        sync_commit_id=uuid4(),
        sync_definition_version_id=sync_definition_version_id,
        run_id=replay_run_id,
        committed_at=now + timedelta(minutes=3),
        target_content_sha256=target_content_sha256,
    )
    cross_run_replay = authority.commit(cross_run_commit)
    final_counts = _governed_counts(engine, tenant_id, sync_definition_version_id)

    checks = {
        **rejection_checks,
        "silver_failed_promotions_rolled_back_atomically": (
            before_failures == (0, 0, 0, 0) and after_failures == before_failures
        ),
        "silver_governed_commit_bound_atomically": (
            first_write.created
            and first_write.governance_evidence == valid_evidence
            and first_write.quarantine_evidence == valid_quarantine_evidence
            and first_write.checkpoint.state_version == 1
            and final_counts == (1, 1, 1, 1)
        ),
        "silver_same_id_replay_requires_identical_evidence": (
            not same_id_replay.created
            and same_id_replay.governance_evidence == valid_evidence
            and same_id_replay.quarantine_evidence == valid_quarantine_evidence
            and mismatched_replay_rejected
            and mismatched_quarantine_replay_rejected
        ),
        "silver_cross_run_replay_reuses_original_evidence": (
            not cross_run_replay.created
            and cross_run_replay.commit.sync_commit_id == commit.sync_commit_id
            and cross_run_replay.replayed_commit_id == commit.sync_commit_id
            and cross_run_replay.governance_evidence == valid_evidence
            and cross_run_replay.quarantine_evidence == valid_quarantine_evidence
            and final_counts == (1, 1, 1, 1)
        ),
    }
    return {
        "checks": checks,
        "commit": first_write.commit.model_dump(mode="json"),
        "governance_evidence": valid_evidence.model_dump(mode="json"),
        "quarantine_evidence": valid_quarantine_evidence.model_dump(mode="json"),
    }


def _certify_governed_gold(
    engine,
    *,
    tenant_id: str,
    now: datetime,
) -> dict[str, Any]:
    gateway = PlatformGateway(engine)
    sync_authority = SourceSyncAuthority(engine)
    approval_authority = ApprovalCaseAuthority(engine)
    platform_definition_id = uuid4()
    sync_definition_version_id = uuid4()
    run_id = uuid4()
    source_urn = f"gda://{tenant_id}/source/roads-gold-input"
    target_urn = f"gda://{tenant_id}/table/roads-gold"
    quarantine_urn = f"gda://{tenant_id}/table/roads-gold-quarantine"
    source_version_id = uuid4()
    target_version_id = uuid4()
    quarantine_version_id = uuid4()
    target_content_sha256 = "9" * 64
    rejected_content_sha256 = "5" * 64
    quality_rule_ref = "quality:gold-publish-v1"

    gateway.register_definition(
        _definition_registration(
            tenant_id,
            platform_definition_id,
            "source-sync-gold-v1",
            now,
        )
    )
    _register_resource_version(
        gateway,
        tenant_id=tenant_id,
        resource_urn=source_urn,
        resource_version_id=source_version_id,
        content_sha256="8" * 64,
        created_at=now,
    )
    _register_resource_version(
        gateway,
        tenant_id=tenant_id,
        resource_urn=target_urn,
        resource_version_id=target_version_id,
        content_sha256=target_content_sha256,
        created_at=now,
    )
    _register_resource_version(
        gateway,
        tenant_id=tenant_id,
        resource_urn=quarantine_urn,
        resource_version_id=quarantine_version_id,
        content_sha256=rejected_content_sha256,
        created_at=now,
    )
    definition = _sync_definition(
        tenant_id,
        sync_definition_version_id,
        platform_definition_id,
        now,
        name="roads-gold-v1",
        source_resource_urn=source_urn,
        target_resource_urn=target_urn,
        governance_overrides={
            "target_layer": "gold",
            "standard_mapping_contract_id": uuid4(),
            "standard_version_id": uuid4(),
            "data_model_version_id": uuid4(),
            "quality_rule_version_refs": [quality_rule_ref],
            "retention_policy_version_ref": "retention:gold-v1",
            "promotion_mode": "approval_gated",
            "quarantine_resource_urn": quarantine_urn,
        },
    )
    sync_authority.create_definition(
        definition,
        owner_ref="team:data-platform",
        initial_cursor={
            "updated_at": "2026-08-02T00:00:00Z",
            "road_id": "r-000",
        },
    )
    _submit_run(
        gateway,
        _run(
            tenant_id,
            run_id,
            platform_definition_id,
            now + timedelta(seconds=1),
            sequence="gold-primary",
        ),
    )

    evidence_time = now + timedelta(minutes=1)
    output = Artifact(
        tenant_id=tenant_id,
        artifact_id=uuid4(),
        artifact_key="roads-gold-output",
        artifact_role="output",
        storage_uri=f"s3://source-sync-cert/{tenant_id}/roads-gold.parquet",
        media_type="application/vnd.apache.parquet",
        content_sha256=target_content_sha256,
        size_bytes=2048,
        run_id=run_id,
        resource_version_id=target_version_id,
        manifest={"row_count": 50366},
        created_by=WORKLOAD,
        created_at=evidence_time,
    )
    quality_artifact = Artifact(
        tenant_id=tenant_id,
        artifact_id=uuid4(),
        artifact_key="roads-gold-quality-evidence",
        artifact_role="evidence",
        storage_uri=f"s3://source-sync-cert/{tenant_id}/roads-gold-quality.json",
        media_type="application/vnd.gda.quality-evidence+json",
        content_sha256="7" * 64,
        size_bytes=256,
        run_id=run_id,
        resource_version_id=target_version_id,
        manifest={"checks": [quality_rule_ref]},
        created_by="workload:quality-evaluator",
        created_at=evidence_time,
    )
    quarantine = Artifact(
        tenant_id=tenant_id,
        artifact_id=uuid4(),
        artifact_key="roads-gold-quarantine",
        artifact_role="quarantine",
        storage_uri=f"s3://source-sync-cert/{tenant_id}/roads-gold-quarantine.jsonl",
        media_type="application/x-ndjson",
        content_sha256=rejected_content_sha256,
        size_bytes=2,
        run_id=run_id,
        resource_version_id=quarantine_version_id,
        manifest={
            "schema": "gda.source_sync_quarantine.v1",
            "source_slice_sha256": "b" * 64,
            "sync_definition_version_id": str(sync_definition_version_id),
            "records_rejected": 0,
            "reason_counts": {},
            "target_content_sha256": target_content_sha256,
            "rejected_content_sha256": rejected_content_sha256,
        },
        created_by=WORKLOAD,
        created_at=evidence_time,
    )
    gateway.record_artifact(output)
    gateway.record_artifact(quality_artifact)
    gateway.record_artifact(quarantine)
    quality_metrics = {"checked": 50366, "violations": 0}
    quality = QualityResult(
        tenant_id=tenant_id,
        quality_result_id=uuid4(),
        run_id=run_id,
        resource_version_id=target_version_id,
        rule_version_ref=quality_rule_ref,
        verdict="passed",
        metrics=quality_metrics,
        evidence_artifact_id=quality_artifact.artifact_id,
        result_sha256=quality_result_fingerprint(
            tenant_id=tenant_id,
            run_id=run_id,
            resource_version_id=target_version_id,
            rule_version_ref=quality_rule_ref,
            verdict="passed",
            metrics=quality_metrics,
            evidence_artifact_id=quality_artifact.artifact_id,
            evaluated_by="workload:quality-evaluator",
            evaluated_at=evidence_time,
        ),
        evaluated_by="workload:quality-evaluator",
        evaluated_at=evidence_time,
    )
    gateway.record_quality_result(quality)
    lineage = LineageEvent(
        tenant_id=tenant_id,
        lineage_event_id=uuid4(),
        event_type="publish",
        source_resource_version_id=source_version_id,
        target_resource_version_id=target_version_id,
        producer=WORKLOAD,
        event_sha256=canonical_json_fingerprint(
            {
                "source": str(source_version_id),
                "target": str(target_version_id),
                "run": str(run_id),
                "artifact": str(output.artifact_id),
            }
        ),
        run_id=run_id,
        definition_version_id=platform_definition_id,
        artifact_id=output.artifact_id,
        facets={"target_layer": "gold"},
        occurred_at=evidence_time,
    )
    gateway.record_lineage(lineage)
    metadata_change_id = _metadata_change_id(engine, tenant_id, lineage.lineage_event_id)
    commit = _commit(
        tenant_id=tenant_id,
        sync_commit_id=uuid4(),
        sync_definition_version_id=sync_definition_version_id,
        run_id=run_id,
        committed_at=now + timedelta(minutes=2),
        target_content_sha256=target_content_sha256,
    )

    def create_case(
        name: str,
        *,
        target_fingerprint: str = target_content_sha256,
        action: str = "source_sync.promote",
        approve: bool,
    ) -> str:
        approval_case_ref = f"gda://{tenant_id}/approval_case/{name}"
        approval_authority.create(
            ApprovalCase(
                tenant_id=tenant_id,
                approval_case_ref=approval_case_ref,
                target_resource_urn=target_urn,
                target_fingerprint=target_fingerprint,
                action=action,
                requester_subject=WORKLOAD,
                request_reason="certify governed Gold promotion",
                request_context={"sync_commit_id": str(commit.sync_commit_id)},
                requested_at=now - timedelta(minutes=1),
                expires_at=now + timedelta(hours=1),
            ),
            owner_ref="team:data-platform",
        )
        if approve:
            approval_authority.decide(
                tenant_id=tenant_id,
                approval_case_ref=approval_case_ref,
                expected_state_version=0,
                verdict=ApprovalCaseStatus.APPROVED,
                actor_subject="human:data-steward",
                reason="certification approval",
            )
        return approval_case_ref

    pending_case_ref = create_case("gold-pending", approve=False)
    wrong_fingerprint_ref = create_case(
        "gold-wrong-fingerprint",
        target_fingerprint="f" * 64,
        approve=True,
    )
    wrong_action_ref = create_case(
        "gold-wrong-action",
        action="source_sync.preview",
        approve=True,
    )
    approved_case_ref = create_case("gold-approved", approve=True)

    def evidence(approval_case_ref: str | None) -> SourceSyncCommitGovernanceEvidence:
        return _commit_governance_evidence(
            tenant_id=tenant_id,
            sync_commit_id=commit.sync_commit_id,
            target_resource_version_id=target_version_id,
            output_artifact_id=output.artifact_id,
            quality_result_ids=(quality.quality_result_id,),
            lineage_event_id=lineage.lineage_event_id,
            metadata_change_id=metadata_change_id,
            approval_case_ref=approval_case_ref,
        )

    valid_quarantine_evidence = _quarantine_evidence(
        tenant_id=tenant_id,
        sync_commit_id=commit.sync_commit_id,
        source_slice_sha256=commit.source_slice_sha256,
        quarantine_resource_version_id=quarantine_version_id,
        quarantine_artifact_id=quarantine.artifact_id,
        records_rejected=0,
        reason_counts={},
    )
    before_failures = _governed_counts(
        engine, tenant_id, sync_definition_version_id
    )
    rejection_checks = {
        "gold_missing_approval_rejected": _expect_governance_rejection(
            sync_authority, commit, evidence(None), valid_quarantine_evidence
        ),
        "gold_pending_approval_rejected": _expect_governance_rejection(
            sync_authority,
            commit,
            evidence(pending_case_ref),
            valid_quarantine_evidence,
        ),
        "gold_wrong_fingerprint_approval_rejected": _expect_governance_rejection(
            sync_authority,
            commit,
            evidence(wrong_fingerprint_ref),
            valid_quarantine_evidence,
        ),
        "gold_wrong_action_approval_rejected": _expect_governance_rejection(
            sync_authority,
            commit,
            evidence(wrong_action_ref),
            valid_quarantine_evidence,
        ),
    }
    after_failures = _governed_counts(
        engine, tenant_id, sync_definition_version_id
    )
    valid_evidence = evidence(approved_case_ref)
    write = sync_authority.commit(
        commit, valid_evidence, valid_quarantine_evidence
    )
    final_counts = _governed_counts(engine, tenant_id, sync_definition_version_id)
    checks = {
        **rejection_checks,
        "gold_failed_approvals_rolled_back_atomically": (
            before_failures == (0, 0, 0, 0) and after_failures == before_failures
        ),
        "gold_approved_commit_bound_atomically": (
            write.created
            and write.governance_evidence == valid_evidence
            and write.quarantine_evidence == valid_quarantine_evidence
            and final_counts == (1, 1, 1, 1)
        ),
    }
    return {
        "checks": checks,
        "commit": write.commit.model_dump(mode="json"),
        "governance_evidence": valid_evidence.model_dump(mode="json"),
        "quarantine_evidence": valid_quarantine_evidence.model_dump(mode="json"),
    }


def _certify(engine) -> dict[str, Any]:
    tenant_a = "sync-cert-a"
    tenant_b = "sync-cert-b"
    now = datetime.now(UTC).replace(microsecond=0)
    platform_definition_id = uuid4()
    wrong_platform_definition_id = uuid4()
    sync_definition_version_id = uuid4()
    gateway = PlatformGateway(engine)
    authority = SourceSyncAuthority(engine)

    gateway.register_definition(
        _definition_registration(
            tenant_a, platform_definition_id, "source-sync-v1", now
        )
    )
    gateway.register_definition(
        _definition_registration(
            tenant_a, wrong_platform_definition_id, "unrelated-sync-v1", now
        )
    )
    definition = _sync_definition(
        tenant_a,
        sync_definition_version_id,
        platform_definition_id,
        now,
    )
    initial_cursor = {
        "updated_at": "2026-08-02T00:00:00Z",
        "road_id": "r-000",
    }
    definition_first = authority.create_definition(
        definition,
        owner_ref="team:data-platform",
        initial_cursor=initial_cursor,
    )
    definition_replay = authority.create_definition(
        definition,
        owner_ref="team:data-platform",
        initial_cursor=initial_cursor,
    )

    invalid_sync_version_id = uuid4()
    invalid_definition = _sync_definition(
        tenant_a,
        invalid_sync_version_id,
        uuid4(),
        now,
        name="missing-platform-definition",
    )
    invalid_definition_failed = False
    try:
        authority.create_definition(
            invalid_definition,
            owner_ref="team:data-platform",
            initial_cursor=initial_cursor,
        )
    except SourceSyncValidationError:
        invalid_definition_failed = True

    run_ids = {name: uuid4() for name in ("primary", "replay", "wrong", "actor", "idle")}
    _submit_run(
        gateway,
        _run(
            tenant_a,
            run_ids["primary"],
            platform_definition_id,
            now + timedelta(seconds=1),
            sequence="primary",
        ),
    )
    _submit_run(
        gateway,
        _run(
            tenant_a,
            run_ids["replay"],
            platform_definition_id,
            now + timedelta(seconds=2),
            sequence="replay",
        ),
    )
    _submit_run(
        gateway,
        _run(
            tenant_a,
            run_ids["wrong"],
            wrong_platform_definition_id,
            now + timedelta(seconds=3),
            sequence="wrong-definition",
        ),
    )
    _submit_run(
        gateway,
        _run(
            tenant_a,
            run_ids["actor"],
            platform_definition_id,
            now + timedelta(seconds=4),
            subject_id="other-controller",
            sequence="wrong-actor",
        ),
    )
    _submit_run(
        gateway,
        _run(
            tenant_a,
            run_ids["idle"],
            platform_definition_id,
            now + timedelta(seconds=5),
            sequence="idle",
        ),
        running=False,
    )

    first_commit = _commit(
        tenant_id=tenant_a,
        sync_commit_id=uuid4(),
        sync_definition_version_id=sync_definition_version_id,
        run_id=run_ids["primary"],
        committed_at=now + timedelta(minutes=1),
    )
    first_write = authority.commit(first_commit)
    source_slice_preflight = authority.find_source_slice_commit(
        tenant_a,
        sync_definition_version_id,
        previous_cursor=first_commit.previous_cursor,
        next_cursor=first_commit.next_cursor,
        source_slice_sha256=first_commit.source_slice_sha256,
    )
    same_id_replay = authority.commit(first_commit)
    cross_run_commit = _commit(
        tenant_id=tenant_a,
        sync_commit_id=uuid4(),
        sync_definition_version_id=sync_definition_version_id,
        run_id=run_ids["replay"],
        committed_at=now + timedelta(minutes=2),
    )
    cross_run_replay = authority.commit(cross_run_commit)

    duplicate_target_failed = False
    try:
        authority.commit(
            _commit(
                tenant_id=tenant_a,
                sync_commit_id=uuid4(),
                sync_definition_version_id=sync_definition_version_id,
                run_id=run_ids["replay"],
                committed_at=now + timedelta(minutes=3),
                target_commit_ref={"provider": "iceberg", "snapshot_id": 9999},
                target_content_sha256="d" * 64,
            )
        )
    except SourceSyncConflictError:
        duplicate_target_failed = True

    stale_checkpoint_failed = False
    try:
        authority.commit(
            _commit(
                tenant_id=tenant_a,
                sync_commit_id=uuid4(),
                sync_definition_version_id=sync_definition_version_id,
                run_id=run_ids["replay"],
                committed_at=now + timedelta(minutes=4),
                source_slice_sha256="e" * 64,
                next_cursor={
                    "updated_at": "2026-08-02T02:00:00Z",
                    "road_id": "r-200",
                },
            )
        )
    except SourceSyncConflictError:
        stale_checkpoint_failed = True

    run_binding_checks: dict[str, bool] = {}
    invalid_runs = {
        "wrong_platform_definition_failed": run_ids["wrong"],
        "wrong_actor_failed": run_ids["actor"],
        "non_running_run_failed": run_ids["idle"],
    }
    for check_name, run_id in invalid_runs.items():
        try:
            authority.commit(
                _commit(
                    tenant_id=tenant_a,
                    sync_commit_id=uuid4(),
                    sync_definition_version_id=sync_definition_version_id,
                    run_id=run_id,
                    committed_at=now + timedelta(minutes=5),
                )
            )
        except SourceSyncValidationError:
            run_binding_checks[check_name] = True
        else:
            run_binding_checks[check_name] = False

    missing_run_failed = False
    try:
        authority.commit(
            _commit(
                tenant_id=tenant_a,
                sync_commit_id=uuid4(),
                sync_definition_version_id=sync_definition_version_id,
                run_id=uuid4(),
                committed_at=now + timedelta(minutes=5),
            )
        )
    except SourceSyncNotFoundError:
        missing_run_failed = True

    wrong_tenant_failed = False
    try:
        authority.commit(
            _commit(
                tenant_id=tenant_b,
                sync_commit_id=uuid4(),
                sync_definition_version_id=sync_definition_version_id,
                run_id=run_ids["primary"],
                committed_at=now + timedelta(minutes=5),
            )
        )
    except SourceSyncNotFoundError:
        wrong_tenant_failed = True

    with engine.connect() as connection:
        atomic_counts = connection.execute(
            text(
                """
                SELECT
                    (SELECT count(*) FROM gda_control.resource
                     WHERE tenant_id = :tenant_id AND resource_urn = :resource_urn),
                    (SELECT count(*) FROM gda_control.resource_version
                     WHERE tenant_id = :tenant_id
                       AND resource_version_id = :sync_definition_version_id),
                    (SELECT count(*) FROM gda_control.source_sync_definition
                     WHERE tenant_id = :tenant_id
                       AND sync_definition_version_id = :sync_definition_version_id),
                    (SELECT count(*) FROM gda_control.source_sync_checkpoint
                     WHERE tenant_id = :tenant_id
                       AND sync_definition_version_id = :sync_definition_version_id),
                    (SELECT count(*) FROM gda_control.resource
                     WHERE tenant_id = :tenant_id
                       AND resource_urn = :invalid_resource_urn),
                    (SELECT count(*) FROM gda_control.resource_version
                     WHERE tenant_id = :tenant_id
                       AND resource_version_id = :invalid_sync_version_id)
                """
            ),
            {
                "tenant_id": tenant_a,
                "resource_urn": definition.sync_definition_urn,
                "sync_definition_version_id": sync_definition_version_id,
                "invalid_resource_urn": invalid_definition.sync_definition_urn,
                "invalid_sync_version_id": invalid_sync_version_id,
            },
        ).one()
        connection.rollback()

    controls = _database_controls(engine, tenant_a, sync_definition_version_id)
    final_checkpoint = authority.get_checkpoint(tenant_a, sync_definition_version_id)
    commits = authority.commits(tenant_a, sync_definition_version_id)
    tenant_authority_hidden = False
    try:
        authority.get_definition(tenant_b, sync_definition_version_id)
    except SourceSyncNotFoundError:
        tenant_authority_hidden = True

    governed_silver = _certify_governed_silver(
        engine,
        tenant_id="sync-cert-governed",
        now=now + timedelta(hours=1),
    )
    governed_gold = _certify_governed_gold(
        engine,
        tenant_id="sync-cert-gold",
        now=now,
    )

    checks = {
        "definition_chain_created_atomically": (
            definition_first.created
            and tuple(atomic_counts[:4]) == (1, 1, 1, 1)
            and definition_first.checkpoint.state_version == 0
            and definition_first.checkpoint.cursor == initial_cursor
        ),
        "definition_request_replay_idempotent": (
            not definition_replay.created
            and definition_replay.definition == definition_first.definition
            and definition_replay.checkpoint == definition_first.checkpoint
        ),
        "failed_definition_creation_rolled_back": (
            invalid_definition_failed and tuple(atomic_counts[4:]) == (0, 0)
        ),
        "commit_advanced_exactly_one_version": (
            first_write.created
            and first_write.checkpoint.state_version == 1
            and first_write.checkpoint.last_sync_commit_id == first_commit.sync_commit_id
        ),
        "same_commit_replay_did_not_advance": (
            not same_id_replay.created
            and same_id_replay.checkpoint.state_version == 1
            and same_id_replay.replayed_commit_id is None
        ),
        "source_slice_preflight_found_commit": source_slice_preflight == first_commit,
        "cross_run_source_slice_recovered": (
            not cross_run_replay.created
            and cross_run_replay.commit == first_commit
            and cross_run_replay.replayed_commit_id == first_commit.sync_commit_id
            and cross_run_replay.checkpoint.state_version == 1
        ),
        "duplicate_source_slice_target_mismatch_failed": duplicate_target_failed,
        "stale_checkpoint_failed": stale_checkpoint_failed,
        **run_binding_checks,
        "missing_run_failed": missing_run_failed,
        "wrong_tenant_failed": wrong_tenant_failed,
        "one_append_only_commit_recorded": (
            len(commits) == 1
            and commits[0] == first_commit
            and final_checkpoint.state_version == 1
        ),
        "tenant_isolation_enforced": (
            tenant_authority_hidden and _tenant_hidden(engine, tenant_b, tenant_a)
        ),
        "database_controls_enforced": all(controls.values()),
        **governed_silver["checks"],
        **governed_gold["checks"],
    }
    return {
        "schema": "gda.source_sync_authority.acceptance.v1",
        "generated_at": now.isoformat(),
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "migrations": [migration.name for migration in MIGRATIONS],
        "database_controls": controls,
        "definition": definition_first.definition.model_dump(mode="json"),
        "checkpoint": final_checkpoint.model_dump(mode="json"),
        "commit": first_commit.model_dump(mode="json"),
        "governed_silver": {
            "commit": governed_silver["commit"],
            "governance_evidence": governed_silver["governance_evidence"],
        },
        "governed_gold": {
            "commit": governed_gold["commit"],
            "governance_evidence": governed_gold["governance_evidence"],
        },
        "not_claimed": [
            "real Spark or Iceberg target commit",
            "real Chongqing OSM source-slice merge",
            "Flink checkpoint or CDC throughput behavior",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--postgres-url",
        default="postgresql://127.0.0.1:5433/gis_agent",
    )
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    settings = _settings()
    admin_auth = {
        "type": "basic",
        "username": settings.get("POSTGRES_USER", "postgres"),
        "password": settings.get(
            "POSTGRES_ADMIN_PASSWORD",
            settings.get("POSTGRES_PASSWORD", "postgres"),
        ),
    }
    sandbox = _PostgresDatabaseSandbox(_connection_url(args.postgres_url, admin_auth))
    report: dict[str, Any] | None = None
    cleanup: dict[str, bool] = {}
    try:
        sandbox.setup()
        if sandbox.engine is None:
            raise RuntimeError("certification database engine was not created")
        report = _certify(sandbox.engine)
        report["sandbox"] = {"database": sandbox.database, "persistent": False}
    finally:
        cleanup = sandbox.cleanup()
    if report is None:
        raise RuntimeError("source sync certification did not produce a report")
    report["cleanup"] = cleanup
    if not all(cleanup.values()):
        report["status"] = "failed"
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "report": str(args.report),
                "checks": report["checks"],
                "cleanup": cleanup,
            },
            sort_keys=True,
        )
    )
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
