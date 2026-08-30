"""Temporary-PostgreSQL rehearsal for the plan-bound PostGIS executor."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import Field, model_validator
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import DBAPIError

from .cross_store_projection_authority import PostgresProjectionCheckpointAuthority
from .cross_store_projection_consistency import (
    InMemoryProjectionCheckpointLedger,
    ProjectionDesiredState,
    ProjectionEngine,
    ProjectionTargetObservation,
    build_projection_repair_plan,
)
from .cross_store_projection_recovery import InMemoryProjectionRecoveryLedger
from .cross_store_projection_recovery_worker import (
    ProjectionProviderFailure,
    ProjectionRecoveryWorker,
    RegisteredExecutorProjectionProvider,
)
from .platform_contracts import FrozenContract, canonical_json_fingerprint
from .postgis_projection_executor import (
    PostGISColumnKind,
    PostGISColumnSpec,
    PostGISProjectionRepairExecutor,
    PostGISProjectionTarget,
    PostGISProjectionTargetRegistry,
    projection_rows_fingerprint,
)
from .postgis_projection_service import (
    PostGISProjectionRepairRequest,
    PostGISProjectionServiceConflictError,
    execute_postgis_projection_repair,
)

_MIGRATIONS = (
    "092_platform_control_ledger.sql",
    "094_platform_control_gateway.sql",
    "169_cross_store_projection_checkpoint_authority.sql",
    "175_postgis_projection_provider_receipt.sql",
)


class PostGISProjectionExecutorRehearsalReport(FrozenContract):
    schema_id: str = "gda.postgis-projection-executor-rehearsal.v3"
    checked_at: datetime
    database_scope: str = "temporary_database_only"
    migration_ids: tuple[str, ...]
    checks: dict[str, bool]
    passed: bool
    failure_reasons: tuple[str, ...]
    technical_baseline_status: str = "technical_baseline_unreviewed"
    decision_status: str = "assisted_precheck_not_for_production_decision"
    report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _hash(self) -> PostGISProjectionExecutorRehearsalReport:
        payload = self.model_dump(mode="json")
        expected = canonical_json_fingerprint(
            {key: value for key, value in payload.items() if key != "report_sha256"}
        )
        if self.report_sha256 != expected:
            raise ValueError("PostGIS executor rehearsal report fingerprint is invalid")
        return self


class _TemporaryPostgres:
    def __init__(self, admin_url: str) -> None:
        parsed = make_url(admin_url)
        self.maintenance_url = parsed.set(database=parsed.database or "postgres")
        self.database = f"gda_postgis_exec_{uuid4().hex[:12]}"
        self.admin_engine: Engine | None = None
        self.engine: Engine | None = None

    def create(self) -> None:
        self.admin_engine = create_engine(
            self.maintenance_url,
            isolation_level="AUTOCOMMIT",
        )
        with self.admin_engine.connect() as connection:
            connection.exec_driver_sql(f'CREATE DATABASE "{self.database}"')
        self.engine = create_engine(self.maintenance_url.set(database=self.database))
        with self.engine.begin() as connection:
            connection.exec_driver_sql("CREATE EXTENSION postgis")
        for filename in _MIGRATIONS:
            migration = Path(__file__).resolve().parent / "migrations" / filename
            with self.engine.begin() as connection:
                connection.exec_driver_sql(migration.read_text(encoding="utf-8").replace("%", "%%"))

    def drop(self) -> None:
        if self.engine is not None:
            self.engine.dispose()
        if self.admin_engine is not None:
            with self.admin_engine.connect() as connection:
                connection.execute(
                    text(
                        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                        "WHERE datname = :database AND pid <> pg_backend_pid()",
                    ),
                    {"database": self.database},
                )
                connection.exec_driver_sql(f'DROP DATABASE IF EXISTS "{self.database}"')
            self.admin_engine.dispose()


def _target() -> PostGISProjectionTarget:
    return PostGISProjectionTarget(
        tenant_id="cq-postgis-rehearsal",
        projection_id="cq.land_parcel",
        target_ref="postgis://temporary/public.land_parcel_current",
        schema_name="public",
        table_name="land_parcel_current",
        columns=(
            PostGISColumnSpec(name="parcel_id", kind=PostGISColumnKind.BIGINT, nullable=False),
            PostGISColumnSpec(name="land_use", kind=PostGISColumnKind.TEXT, nullable=False),
            PostGISColumnSpec(
                name="geom",
                kind=PostGISColumnKind.GEOMETRY,
                geometry_srid=4326,
            ),
        ),
        order_by=("parcel_id",),
    )


def _desired(
    target: PostGISProjectionTarget, rows: tuple[dict[str, Any], ...], source_sha: str
) -> ProjectionDesiredState:
    return ProjectionDesiredState(
        tenant_id=target.tenant_id,
        projection_id=target.projection_id,
        source_resource_version_ref=f"gda://{target.tenant_id}/data_product/parcel-v2",
        source_content_sha256=source_sha,
        target_engine=ProjectionEngine.POSTGIS,
        target_ref=target.target_ref,
        target_exists=True,
        expected_target_content_sha256=projection_rows_fingerprint(target, rows),
        expected_row_count=len(rows),
    )


def run_rehearsal(admin_url: str) -> PostGISProjectionExecutorRehearsalReport:
    temporary = _TemporaryPostgres(admin_url)
    checks: dict[str, bool] = {}
    failures: list[str] = []
    checked_at = datetime.now(UTC)
    try:
        temporary.create()
        assert temporary.engine is not None
        target = _target()
        rows = (
            {
                "parcel_id": 1,
                "land_use": "farmland",
                "geom": "POINT (106.5 29.5)",
            },
            {
                "parcel_id": 2,
                "land_use": "forest",
                "geom": "POINT(106.6 29.6)",
            },
        )
        executor = PostGISProjectionRepairExecutor(
            temporary.engine, PostGISProjectionTargetRegistry((target,))
        )
        authority = PostgresProjectionCheckpointAuthority(temporary.engine)
        missing = ProjectionTargetObservation(
            tenant_id=target.tenant_id,
            projection_id=target.projection_id,
            target_engine=ProjectionEngine.POSTGIS,
            target_ref=target.target_ref,
            target_exists=False,
            observed_content_sha256=None,
            observed_row_count=0,
            observed_by="workload:rehearsal",
            observed_at=checked_at,
        )
        desired = _desired(target, rows, "a" * 64)
        rebuild_plan = build_projection_repair_plan(desired, missing, None)
        first_result = execute_postgis_projection_repair(
            PostGISProjectionRepairRequest(
                plan=rebuild_plan,
                rows=rows,
                checkpointed_by="workload:postgis-rehearsal",
            ),
            executor=executor,
            authority=authority,
        )
        first = first_result.receipt
        checks["rebuild_transaction_and_content_verification"] = (
            first.status == "completed"
            and first.target_content_sha256 == desired.expected_target_content_sha256
            and first.target_row_count == len(rows)
        )
        checks["rebuild_receipt_automatically_checkpointed"] = (
            first_result.checkpoint_created
            and first_result.checkpoint.checkpoint_version == 1
            and first_result.checkpoint.target_commit_ref == first.provider_commit_ref
            and authority.current(
                tenant_id=target.tenant_id,
                projection_id=target.projection_id,
                target_engine=ProjectionEngine.POSTGIS,
                target_ref=target.target_ref,
            )
            == first_result.checkpoint
        )
        with temporary.engine.connect() as connection:
            receipt_row = connection.execute(
                text(
                    """
                    SELECT provider_transaction_id, provider_commit_ref,
                           receipt_sha256, target_content_sha256, target_row_count
                    FROM gda_provider.postgis_projection_repair_receipt
                    WHERE tenant_id = :tenant_id
                      AND plan_idempotency_key = :plan_idempotency_key
                    """
                ),
                {
                    "tenant_id": target.tenant_id,
                    "plan_idempotency_key": rebuild_plan.plan_idempotency_key,
                },
            ).mappings().one()
        checks["provider_receipt_commits_with_target_transaction"] = (
            receipt_row["provider_transaction_id"]
            == first.provider_commit_ref.get("provider_transaction_id")
            and receipt_row["receipt_sha256"]
            == first.provider_commit_ref.get("receipt_sha256")
            and receipt_row["provider_commit_ref"] == first.provider_commit_ref
            and receipt_row["target_content_sha256"]
            == desired.expected_target_content_sha256
            and receipt_row["target_row_count"] == len(rows)
        )
        try:
            with temporary.engine.begin() as connection:
                connection.execute(
                    text(
                        """
                        UPDATE gda_provider.postgis_projection_repair_receipt
                        SET status = 'replayed'
                        WHERE tenant_id = :tenant_id
                          AND plan_idempotency_key = :plan_idempotency_key
                        """
                    ),
                    {
                        "tenant_id": target.tenant_id,
                        "plan_idempotency_key": rebuild_plan.plan_idempotency_key,
                    },
                )
        except DBAPIError:
            checks["provider_receipt_is_immutable"] = True
        else:
            checks["provider_receipt_is_immutable"] = False
        try:
            with temporary.engine.connect() as connection:
                with connection.begin():
                    connection.exec_driver_sql('SET LOCAL ROLE "gda_control_gateway"')
                    connection.execute(
                        text("SELECT set_config('app.current_tenant', :tenant, true)"),
                        {"tenant": target.tenant_id},
                    )
                    connection.execute(
                        text(
                            "SELECT 1 FROM "
                            "gda_provider.postgis_projection_repair_receipt LIMIT 1"
                        )
                    ).all()
        except DBAPIError:
            checks["control_gateway_cannot_read_provider_receipts"] = True
        else:
            checks["control_gateway_cannot_read_provider_receipts"] = False
        replay_result = execute_postgis_projection_repair(
            PostGISProjectionRepairRequest(
                plan=rebuild_plan,
                rows=rows,
                checkpointed_by="workload:postgis-rehearsal",
            ),
            executor=executor,
            authority=authority,
        )
        checks["rebuild_replay_is_idempotent"] = (
            replay_result.status == "replayed"
            and not replay_result.checkpoint_created
            and replay_result.checkpoint == first_result.checkpoint
        )

        with temporary.engine.begin() as connection:
            connection.execute(
                text(
                    'UPDATE "public"."land_parcel_current" SET "land_use" = :value '
                    'WHERE "parcel_id" = 1'
                ),
                {"value": "tampered"},
            )
        try:
            executor.execute(
                rebuild_plan,
                rows=rows,
                observed_at=checked_at + timedelta(seconds=2),
            )
        except Exception:
            checks["sealed_observation_rejects_target_drift"] = True
        else:
            checks["sealed_observation_rejects_target_drift"] = False
        try:
            execute_postgis_projection_repair(
                PostGISProjectionRepairRequest(
                    plan=rebuild_plan,
                    rows=rows,
                    checkpointed_by="workload:postgis-rehearsal",
                ),
                executor=executor,
                authority=authority,
            )
        except PostGISProjectionServiceConflictError:
            checks["checkpoint_replay_reobserves_and_rejects_target_drift"] = True
        else:
            checks["checkpoint_replay_reobserves_and_rejects_target_drift"] = False
        with temporary.engine.begin() as connection:
            connection.execute(
                text(
                    'UPDATE "public"."land_parcel_current" SET "land_use" = :value '
                    'WHERE "parcel_id" = 1'
                ),
                {"value": "farmland"},
            )

        post = executor.observe(target)
        advanced_desired = _desired(target, rows, "b" * 64)
        checkpoint_plan = build_projection_repair_plan(
            advanced_desired,
            post,
            first_result.checkpoint,
        )
        checkpoint_result = execute_postgis_projection_repair(
            PostGISProjectionRepairRequest(
                plan=checkpoint_plan,
                checkpointed_by="workload:postgis-rehearsal",
            ),
            executor=executor,
            authority=authority,
        )
        checks["checkpoint_action_rechecks_without_rebuild"] = (
            checkpoint_result.receipt.status == "checkpointed"
            and checkpoint_result.checkpoint_created
            and checkpoint_result.checkpoint.checkpoint_version == 2
        )

        stale_desired = _desired(target, rows, "d" * 64)
        stale_plan = build_projection_repair_plan(stale_desired, missing, None)
        before_stale_attempt = executor.observe(target)
        try:
            execute_postgis_projection_repair(
                PostGISProjectionRepairRequest(
                    plan=stale_plan,
                    rows=rows,
                    checkpointed_by="workload:postgis-rehearsal",
                ),
                executor=executor,
                authority=authority,
            )
        except PostGISProjectionServiceConflictError:
            after_stale_attempt = executor.observe(target)
            checks["stale_predecessor_rejected_before_provider_mutation"] = (
                before_stale_attempt.target_exists == after_stale_attempt.target_exists
                and before_stale_attempt.observed_content_sha256
                == after_stale_attempt.observed_content_sha256
                and before_stale_attempt.observed_row_count
                == after_stale_attempt.observed_row_count
            )
        else:
            checks["stale_predecessor_rejected_before_provider_mutation"] = False

        delete_desired = ProjectionDesiredState(
            tenant_id=target.tenant_id,
            projection_id=target.projection_id,
            source_resource_version_ref="gda://cq-postgis-rehearsal/data_product/parcel-v3",
            source_content_sha256="c" * 64,
            target_engine=ProjectionEngine.POSTGIS,
            target_ref=target.target_ref,
            target_exists=False,
            expected_target_content_sha256=None,
            expected_row_count=0,
        )
        delete_plan = build_projection_repair_plan(
            delete_desired,
            post,
            checkpoint_result.checkpoint,
        )
        delete_result = execute_postgis_projection_repair(
            PostGISProjectionRepairRequest(
                plan=delete_plan,
                checkpointed_by="workload:postgis-rehearsal",
            ),
            executor=executor,
            authority=authority,
        )
        deleted = delete_result.receipt
        checks["delete_transaction_and_absence_verification"] = (
            deleted.status == "deleted"
            and not deleted.target_exists
            and deleted.target_row_count == 0
        )
        checks["delete_receipt_automatically_checkpointed"] = (
            delete_result.checkpoint_created
            and delete_result.checkpoint.checkpoint_version == 3
            and not delete_result.checkpoint.target_exists
            and delete_result.checkpoint.target_commit_ref == deleted.provider_commit_ref
        )
        delete_replay = execute_postgis_projection_repair(
            PostGISProjectionRepairRequest(
                plan=delete_plan,
                checkpointed_by="workload:postgis-rehearsal",
            ),
            executor=executor,
            authority=authority,
        )
        checks["delete_replay_is_idempotent"] = (
            delete_replay.status == "replayed"
            and not delete_replay.checkpoint_created
            and delete_replay.checkpoint == delete_result.checkpoint
        )
        history = authority.history(
            tenant_id=target.tenant_id,
            projection_id=target.projection_id,
            target_engine=ProjectionEngine.POSTGIS,
            target_ref=target.target_ref,
        )
        checks["checkpoint_history_is_append_only_and_sequential"] = (
            tuple(item.checkpoint_version for item in history) == (1, 2, 3)
            and history[0].checkpoint_sha256 == first_result.checkpoint.checkpoint_sha256
            and history[1].checkpoint_sha256 == checkpoint_result.checkpoint.checkpoint_sha256
            and history[2].checkpoint_sha256 == delete_result.checkpoint.checkpoint_sha256
        )

        def isolated_target(suffix: str) -> PostGISProjectionTarget:
            table_name = f"land_parcel_{suffix}"
            return target.model_copy(
                update={
                    "projection_id": f"cq.land_parcel.{suffix}",
                    "target_ref": f"postgis://temporary/public.{table_name}",
                    "table_name": table_name,
                }
            )

        def missing_observation(
            isolated: PostGISProjectionTarget,
        ) -> ProjectionTargetObservation:
            return ProjectionTargetObservation(
                tenant_id=isolated.tenant_id,
                projection_id=isolated.projection_id,
                target_engine=ProjectionEngine.POSTGIS,
                target_ref=isolated.target_ref,
                target_exists=False,
                observed_content_sha256=None,
                observed_row_count=0,
                observed_by="workload:postgis-fault-rehearsal",
                observed_at=checked_at,
            )

        crash_target = isolated_target("commit_unknown")
        crash_plan = build_projection_repair_plan(
            _desired(crash_target, rows, "e" * 64),
            missing_observation(crash_target),
            None,
        )
        crash_registry = PostGISProjectionTargetRegistry((crash_target,))
        crash_executor = PostGISProjectionRepairExecutor(
            temporary.engine,
            crash_registry,
        )
        crash_delegate = RegisteredExecutorProjectionProvider(
            executor=crash_executor,
            registry=crash_registry,
            rows=rows,
        )

        class CrashAfterCommitProvider:
            execute_count = 0

            def execute(self, submitted_plan):
                self.execute_count += 1
                crash_delegate.execute(submitted_plan)
                raise ProjectionProviderFailure(
                    "client_connection_lost_after_commit",
                    outcome_known=False,
                )

            def observe(self, submitted_plan):
                return crash_delegate.observe(submitted_plan)

            def recover_receipt(self, submitted_plan):
                return crash_delegate.recover_receipt(submitted_plan)

        crash_provider = CrashAfterCommitProvider()
        crash_ledger = InMemoryProjectionRecoveryLedger()
        crash_authority = InMemoryProjectionCheckpointLedger()
        crash_first = ProjectionRecoveryWorker(
            crash_plan,
            checkpointed_by="workload:postgis-fault-rehearsal",
            provider=crash_provider,
            authority=crash_authority,
            ledger=crash_ledger,
        ).run_once()
        temporary.engine.dispose()
        restarted_executor = PostGISProjectionRepairExecutor(
            temporary.engine,
            crash_registry,
        )
        restarted_delegate = RegisteredExecutorProjectionProvider(
            executor=restarted_executor,
            registry=crash_registry,
            rows=rows,
        )

        class RecoveryProvider:
            execute_count = 0
            recover_count = 0

            def execute(self, submitted_plan):
                self.execute_count += 1
                return restarted_delegate.execute(submitted_plan)

            def observe(self, submitted_plan):
                return restarted_delegate.observe(submitted_plan)

            def recover_receipt(self, submitted_plan):
                self.recover_count += 1
                return restarted_delegate.recover_receipt(submitted_plan)

        recovery_provider = RecoveryProvider()
        crash_recovered = ProjectionRecoveryWorker(
            crash_plan,
            checkpointed_by="workload:postgis-fault-rehearsal",
            provider=recovery_provider,
            authority=crash_authority,
            ledger=crash_ledger,
        ).run_once()
        checks["unknown_commit_recovers_after_restart_without_provider_replay"] = (
            crash_first.action_taken == "reobserve_target"
            and crash_provider.execute_count == 1
            and crash_recovered.snapshot.state.value == "authority_committed"
            and crash_recovered.checkpoint is not None
            and recovery_provider.recover_count == 1
            and recovery_provider.execute_count == 0
            and len(
                crash_authority.history(
                    tenant_id=crash_plan.tenant_id,
                    projection_id=crash_plan.projection_id,
                    target_engine=crash_plan.target_engine,
                    target_ref=crash_plan.target_ref,
                )
            )
            == 1
        )

        drift_target = isolated_target("receipt_drift")
        drift_plan = build_projection_repair_plan(
            _desired(drift_target, rows, "f" * 64),
            missing_observation(drift_target),
            None,
        )
        drift_registry = PostGISProjectionTargetRegistry((drift_target,))
        drift_delegate = RegisteredExecutorProjectionProvider(
            executor=PostGISProjectionRepairExecutor(
                temporary.engine,
                drift_registry,
            ),
            registry=drift_registry,
            rows=rows,
        )

        class DriftCrashProvider:
            def execute(self, submitted_plan):
                drift_delegate.execute(submitted_plan)
                raise ProjectionProviderFailure(
                    "client_connection_lost_after_commit",
                    outcome_known=False,
                )

            def observe(self, submitted_plan):
                return drift_delegate.observe(submitted_plan)

        drift_ledger = InMemoryProjectionRecoveryLedger()
        drift_authority = InMemoryProjectionCheckpointLedger()
        ProjectionRecoveryWorker(
            drift_plan,
            checkpointed_by="workload:postgis-fault-rehearsal",
            provider=DriftCrashProvider(),
            authority=drift_authority,
            ledger=drift_ledger,
        ).run_once()
        with temporary.engine.begin() as connection:
            connection.execute(
                text(
                    f'UPDATE "public"."{drift_target.table_name}" '
                    'SET "land_use" = :value WHERE "parcel_id" = 1'
                ),
                {"value": "tampered-after-receipt"},
            )
        drift_recovery_provider = RecoveryProvider()
        drift_recovery_provider.recover_receipt = drift_delegate.recover_receipt
        drift_recovery_provider.observe = drift_delegate.observe
        drift_result = ProjectionRecoveryWorker(
            drift_plan,
            checkpointed_by="workload:postgis-fault-rehearsal",
            provider=drift_recovery_provider,
            authority=drift_authority,
            ledger=drift_ledger,
        ).run_once()
        checks["receipt_target_mismatch_stays_manual_and_uncheckpointed"] = (
            drift_result.action_taken == "await_operator"
            and drift_result.snapshot.state.value == "compensation_required"
            and drift_recovery_provider.execute_count == 0
            and not drift_authority.history(
                tenant_id=drift_plan.tenant_id,
                projection_id=drift_plan.projection_id,
                target_engine=drift_plan.target_engine,
                target_ref=drift_plan.target_ref,
            )
        )

        disconnect_target = isolated_target("disconnect")
        disconnect_plan = build_projection_repair_plan(
            _desired(disconnect_target, rows, "1" * 64),
            missing_observation(disconnect_target),
            None,
        )
        disconnect_registry = PostGISProjectionTargetRegistry((disconnect_target,))

        class DisconnectExecutor(PostGISProjectionRepairExecutor):
            injected = False

            def observe(self, observed_target, *, connection=None):
                if connection is not None and not self.injected:
                    self.injected = True
                    backend_pid = connection.execute(
                        text("SELECT pg_backend_pid()")
                    ).scalar_one()
                    killer = create_engine(
                        temporary.engine.url,
                        isolation_level="AUTOCOMMIT",
                    )
                    try:
                        with killer.connect() as killer_connection:
                            killer_connection.execute(
                                text("SELECT pg_terminate_backend(:backend_pid)"),
                                {"backend_pid": backend_pid},
                            )
                    finally:
                        killer.dispose()
                return super().observe(observed_target, connection=connection)

        disconnect_executor = DisconnectExecutor(
            temporary.engine,
            disconnect_registry,
        )
        try:
            disconnect_executor.execute(disconnect_plan, rows=rows)
        except Exception:
            fresh_disconnect_executor = PostGISProjectionRepairExecutor(
                temporary.engine,
                disconnect_registry,
            )
            disconnect_observation = fresh_disconnect_executor.observe(
                disconnect_target
            )
            disconnect_receipt = fresh_disconnect_executor.recover_receipt(
                disconnect_plan
            )
            checks["database_disconnect_rolls_back_target_and_provider_receipt"] = (
                not disconnect_observation.target_exists
                and disconnect_receipt is None
            )
        else:
            checks["database_disconnect_rolls_back_target_and_provider_receipt"] = False
    except Exception as exc:  # pragma: no cover - surfaced in the report
        failures.append(f"{type(exc).__name__}: {exc}")
    finally:
        temporary.drop()
    failures.extend(key for key, value in checks.items() if not value)
    payload = {
        "schema_id": "gda.postgis-projection-executor-rehearsal.v3",
        "checked_at": checked_at.isoformat().replace("+00:00", "Z"),
        "database_scope": "temporary_database_only",
        "migration_ids": _MIGRATIONS,
        "checks": checks,
        "passed": not failures and bool(checks),
        "failure_reasons": tuple(sorted(set(failures))),
        "technical_baseline_status": "technical_baseline_unreviewed",
        "decision_status": "assisted_precheck_not_for_production_decision",
    }
    report = PostGISProjectionExecutorRehearsalReport(
        **payload,
        report_sha256=canonical_json_fingerprint(payload),
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--admin-url",
        default="postgresql://postgres:postgres@localhost:5433/gis_agent",
    )
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = run_rehearsal(args.admin_url)
    document = report.model_dump(mode="json")
    output = json.dumps(document, ensure_ascii=True, indent=2, sort_keys=True)
    print(output)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(output + "\n", encoding="utf-8")
    if not report.passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
