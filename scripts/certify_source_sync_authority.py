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

from data_agent.connectors.database import _connection_url
from data_agent.platform_contracts import (
    PlatformDefinitionVersion,
    PlatformRun,
    Resource,
    ResourceVersion,
    SourceSyncCommit,
    SourceSyncDefinitionVersion,
    SubjectContext,
    canonical_json_fingerprint,
    platform_definition_fingerprint,
    source_sync_commit_fingerprint,
    source_sync_definition_fingerprint,
)
from data_agent.platform_gateway import DefinitionRegistration, PlatformGateway
from data_agent.source_sync_authority import (
    SourceSyncAuthority,
    SourceSyncConflictError,
    SourceSyncNotFoundError,
    SourceSyncValidationError,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT = REPO_ROOT / ".tmp/source-sync-certification/authority-report.json"
MIGRATIONS = (
    REPO_ROOT / "data_agent/migrations/092_platform_control_ledger.sql",
    REPO_ROOT / "data_agent/migrations/094_platform_control_gateway.sql",
    REPO_ROOT / "data_agent/migrations/104_source_sync_checkpoint_authority.sql",
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
) -> SourceSyncDefinitionVersion:
    values: dict[str, Any] = {
        "tenant_id": tenant_id,
        "sync_definition_urn": f"gda://{tenant_id}/sync_definition/{name}",
        "sync_definition_version_id": sync_definition_version_id,
        "platform_definition_version_id": platform_definition_version_id,
        "source_resource_urn": f"gda://{tenant_id}/source/osm-roads",
        "source_definition_fingerprint": "a" * 64,
        "target_resource_urn": f"gda://{tenant_id}/table/osm-roads-bronze",
        "mode": "incremental",
        "write_disposition": "merge",
        "cursor_kind": "field",
        "cursor_field": "updated_at",
        "primary_keys": ("road_id",),
        "delete_mode": "hard_delete",
        "config": {"late_arrival_seconds": 300},
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


def _direct_statement_denied(
    engine,
    tenant_id: str,
    statement: str,
    parameters: dict[str, Any],
    *,
    gateway_role: bool,
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
        return _sqlstate(exc) in {"42501", "55000"}
    return False


def _database_controls(engine, tenant_id: str, sync_version_id: UUID) -> dict[str, bool]:
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
                      'source_sync_commit'
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
        "rls_forced_on_all_sync_tables": len(rls) == 3 and all(rls.values()),
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
