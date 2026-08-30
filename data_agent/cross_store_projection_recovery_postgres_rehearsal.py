"""Isolated PostgreSQL rehearsal for the durable projection recovery ledger."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event
from typing import Any

from pydantic import Field, model_validator
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from .approval_case_authority import ApprovalCaseAuthority
from .cross_store_projection_consistency import (
    InMemoryProjectionCheckpointLedger,
    build_projection_repair_plan,
)
from .cross_store_projection_postgres_rehearsal import _temporary_postgres
from .cross_store_projection_recovery import ProjectionRecoveryCoordinator
from .cross_store_projection_recovery_authority import PostgresProjectionRecoveryLedger
from .cross_store_projection_recovery_compensation import (
    ProjectionRecoveryCompensationConfig,
    ProjectionRecoveryCompensationIndeterminateError,
    ProjectionRecoveryCompensationResolver,
    compensation_receipt_fingerprint,
    compensation_reconciliation_target_fingerprint,
    projection_recovery_compensation_attempt_id,
)
from .cross_store_projection_recovery_controller import (
    StaticProjectionRecoveryControllerBinding,
)
from .cross_store_projection_recovery_job import (
    PostgresProjectionRecoveryJobRepository,
    ProjectionRecoveryJobConflictError,
    ProjectionRecoveryJobValidationError,
    ProjectionRecoveryJobWorker,
)
from .cross_store_projection_recovery_rehearsal import _plan, _post_observation, _receipt
from .cross_store_projection_recovery_worker import (
    ProjectionProviderFailure,
    ProjectionRecoveryWorker,
)
from .platform_contracts import (
    ApprovalCase,
    ApprovalCaseStatus,
    FrozenContract,
    canonical_json_fingerprint,
)
from .platform_runtime.cross_store_recovery import (
    CROSS_STORE_RECOVERY_SCHEMA,
    CrossStoreRecoveryBinding,
)
from .platform_runtime.cross_store_recovery_admission import (
    CrossStoreRecoveryAdmission,
)
from .platform_runtime.cross_store_recovery_controller import (
    CrossStoreRecoveryController,
    CrossStoreRecoveryRunState,
)
from .platform_runtime.cross_store_recovery_controller_authority import (
    PostgresCrossStoreRecoveryControllerLedger,
)

_TENANT = "chongqing-customer"
_OTHER_TENANT = "chongqing-other"


class CrossStoreProjectionRecoveryPostgresRehearsalReport(FrozenContract):
    schema_id: str = "gda.cross-store-projection-recovery-postgres-rehearsal.v1"
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
    def _fingerprint_matches(self) -> CrossStoreProjectionRecoveryPostgresRehearsalReport:
        expected = _report_hash(self.model_dump(mode="json"))
        if self.report_sha256 != expected:
            raise ValueError("projection recovery PostgreSQL report fingerprint is invalid")
        return self


def _report_hash(payload: dict[str, Any]) -> str:
    normalized = json.loads(
        json.dumps(
            payload,
            ensure_ascii=True,
            default=lambda value: value.astimezone(UTC)
            .isoformat()
            .replace("+00:00", "Z"),
        )
    )
    return canonical_json_fingerprint(
        {key: value for key, value in normalized.items() if key != "report_sha256"}
    )


def _execute_migration(connection: Any) -> None:
    migration_dir = Path(__file__).resolve().parent / "migrations"
    for filename in (
        "102_source_schema_drift_ledger.sql",
        "103_unified_approval_case_authority.sql",
        "170_cross_store_projection_recovery_ledger.sql",
        "171_cross_store_projection_recovery_job.sql",
        "172_projection_recovery_compensation_approval.sql",
        "173_projection_recovery_compensation_execution.sql",
        "174_projection_recovery_compensation_reconciliation.sql",
        "233_cross_store_recovery_controller_authority.sql",
    ):
        sql = (migration_dir / filename).read_text(encoding="utf-8")
        connection.exec_driver_sql(sql.replace("%", "%%"))


def _controller_binding(plan: Any, engine: Any) -> StaticProjectionRecoveryControllerBinding:
    payload = {
        "schema": CROSS_STORE_RECOVERY_SCHEMA,
        "tenant_ids": (plan.tenant_id,),
        "source_resource_version_ref": plan.desired_state.source_resource_version_ref,
        "source_content_sha256": plan.desired_state.source_content_sha256,
        "control_manifest_sha256": "b" * 64,
        "object_manifest_sha256": "c" * 64,
    }
    binding = CrossStoreRecoveryBinding(
        **payload,
        binding_sha256=hashlib.sha256(
            json.dumps(
                {**payload, "tenant_ids": list(payload["tenant_ids"])},
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest(),
    )
    binding.validate()
    admission = CrossStoreRecoveryAdmission(
        binding=binding,
        persisted_tenant_ids=binding.tenant_ids,
        object_version_id_remap_allowed=False,
    )
    controller = CrossStoreRecoveryController(
        f"projection-recovery:{plan.plan_sha256}",
        ledger=PostgresCrossStoreRecoveryControllerLedger(
            binding.tenant_ids,
            engine,
        ),
    )
    return StaticProjectionRecoveryControllerBinding(controller, admission)


def _sqlstate(exc: DBAPIError) -> str | None:
    original = getattr(exc, "orig", None)
    return getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)


def run_cross_store_projection_recovery_postgres_rehearsal(
    admin_url: str,
) -> CrossStoreProjectionRecoveryPostgresRehearsalReport:
    checks: dict[str, bool] = {}
    failures: list[str] = []

    def check(name: str, passed: bool, failure: str) -> None:
        checks[name] = passed
        if not passed:
            failures.append(failure)

    with _temporary_postgres(admin_url) as sandbox:
        if sandbox.runtime_engine is None:
            raise RuntimeError("temporary runtime engine was not created")
        with sandbox.admin_connection() as connection:
            _execute_migration(connection)

        plan = _plan()
        ledger = PostgresProjectionRecoveryLedger(_TENANT, sandbox.runtime_engine)
        coordinator = ProjectionRecoveryCoordinator(
            plan,
            checkpointed_by="workload:recovery-postgres-rehearsal",
            ledger=ledger,
            now=lambda: datetime(2026, 8, 15, 17, 0, tzinfo=UTC),
        )
        planned = coordinator.snapshot
        committed = coordinator.provider_committed(_receipt(plan))
        pending = coordinator.authority_failed("postgresql_unavailable")
        check(
            "append_only_state_chain_persisted",
            planned.state.value == "planned"
            and committed.state.value == "provider_committed"
            and pending.state.value == "authority_pending",
            "recovery state chain was not persisted",
        )

        reloaded = PostgresProjectionRecoveryLedger(_TENANT, sandbox.runtime_engine)
        current = reloaded.current(plan.plan_sha256)
        history = reloaded.history(plan.plan_sha256)
        check(
            "reload_current_and_history",
            current is not None
            and current.state.value == "authority_pending"
            and len(history) == 3,
            "recovery current/history reload was incorrect",
        )
        replay = reloaded.append(current) if current is not None else None
        check(
            "snapshot_idempotent_replay",
            replay is not None and replay.snapshot_sha256 == current.snapshot_sha256,
            "same recovery snapshot did not replay idempotently",
        )

        other = PostgresProjectionRecoveryLedger(_OTHER_TENANT, sandbox.runtime_engine)
        check(
            "cross_tenant_read_hidden",
            other.current(plan.plan_sha256) is None,
            "recovery ledger exposed another tenant's snapshot",
        )

        recovered = ProjectionRecoveryCoordinator(
            plan,
            checkpointed_by="workload:recovery-postgres-rehearsal",
            ledger=reloaded,
            now=lambda: datetime(2026, 8, 15, 17, 1, tzinfo=UTC),
        )
        # The durable snapshot is already loaded; recover only checks the
        # database-backed state and does not recreate the provider event.
        recovered_snapshot = recovered.snapshot
        check(
            "new_coordinator_reuses_durable_state",
            recovered_snapshot.snapshot_sha256 == current.snapshot_sha256,
            "new coordinator did not reuse durable recovery state",
        )

        class _Provider:
            execute_count = 0

            def execute(self, _plan):
                self.execute_count += 1
                return _receipt(_plan)

            def observe(self, _plan):
                return _post_observation()

        provider = _Provider()
        checkpoint_authority = InMemoryProjectionCheckpointLedger()
        worker_result = ProjectionRecoveryWorker(
            plan,
            checkpointed_by="workload:recovery-postgres-worker-rehearsal",
            provider=provider,
            authority=checkpoint_authority,
            ledger=reloaded,
            now=lambda: datetime(2026, 8, 15, 17, 2, tzinfo=UTC),
        ).run_once()
        worker_current = reloaded.current(plan.plan_sha256)
        check(
            "durable_worker_retries_authority_without_provider_replay",
            worker_result.snapshot.state.value == "authority_committed"
            and worker_result.checkpoint is not None
            and worker_current is not None
            and worker_current.state.value == "authority_committed"
            and provider.execute_count == 0,
            "durable recovery worker did not perform authority-only retry",
        )

        jobs = PostgresProjectionRecoveryJobRepository(sandbox.runtime_engine)
        enqueued = jobs.enqueue(
            plan,
            submitted_by="agent:recovery-postgres-rehearsal",
            max_attempts=2,
        )
        replayed_job = jobs.enqueue(
            plan,
            submitted_by="agent:recovery-postgres-rehearsal",
            max_attempts=2,
        )
        check(
            "job_enqueue_is_idempotent",
            enqueued.job_id == replayed_job.job_id
            and enqueued.plan_sha256 == replayed_job.plan_sha256
            and enqueued.status == "queued",
            "sealed recovery job enqueue was not idempotent",
        )

        first_claims = jobs.claim(
            _TENANT,
            "worker:recovery-postgres-a",
            limit=1,
            lease_seconds=30,
        )
        competing_claims = jobs.claim(
            _TENANT,
            "worker:recovery-postgres-b",
            limit=1,
            lease_seconds=30,
        )
        first_job = first_claims[0].job if first_claims else None
        check(
            "leased_job_has_single_owner",
            first_job is not None
            and first_job.status == "running"
            and first_job.claimed_by == "worker:recovery-postgres-a"
            and first_job.lease_generation == 1
            and first_job.attempt_count == 1
            and not competing_claims,
            "two workers could claim the same recovery job",
        )

        renewed_job = (
            jobs.renew(
                first_job,
                "worker:recovery-postgres-a",
                lease_seconds=60,
            )
            if first_job is not None
            else None
        )
        check(
            "lease_can_be_renewed_by_owner",
            renewed_job is not None
            and first_job is not None
            and renewed_job.lease_expires_at is not None
            and first_job.lease_expires_at is not None
            and renewed_job.lease_expires_at > first_job.lease_expires_at,
            "recovery job lease owner could not renew its lease",
        )

        if renewed_job is not None:
            with sandbox.admin_connection() as connection:
                connection.execute(
                    text("SELECT set_config('app.current_tenant', :tenant, true)"),
                    {"tenant": _TENANT},
                )
                connection.execute(
                    text(
                        "SELECT set_config("
                        "'gda.cross_store_projection_recovery_job_write_allowed', "
                        "'1', true)"
                    )
                )
                connection.execute(
                    text(
                        """
                        UPDATE gda_control.cross_store_projection_recovery_job
                        SET lease_expires_at = clock_timestamp() - interval '1 second'
                        WHERE tenant_id = :tenant_id AND job_id = :job_id
                        """
                    ),
                    {"tenant_id": _TENANT, "job_id": renewed_job.job_id},
                )

        reclaimed_claims = jobs.claim(
            _TENANT,
            "worker:recovery-postgres-a",
            limit=1,
            lease_seconds=30,
        )
        reclaimed_job = reclaimed_claims[0].job if reclaimed_claims else None
        check(
            "expired_lease_is_reclaimed",
            reclaimed_job is not None
            and first_job is not None
            and reclaimed_job.claimed_by == "worker:recovery-postgres-a"
            and reclaimed_job.lease_generation == first_job.lease_generation + 1
            and reclaimed_job.attempt_count == 2,
            "expired recovery job lease was not reclaimed",
        )

        stale_finish_rejected = False
        if first_job is not None:
            try:
                jobs.fail(
                    first_job,
                    "worker:recovery-postgres-a",
                    RuntimeError("stale-worker-write"),
                )
            except ProjectionRecoveryJobConflictError:
                stale_finish_rejected = True
        check(
            "stale_lease_owner_terminal_write_rejected",
            stale_finish_rejected,
            "stale recovery worker could write a terminal result",
        )

        waiting_job = (
            jobs._finish(
                reclaimed_job,
                "worker:recovery-postgres-a",
                status="waiting_operator",
                next_action="manual_compensation",
                snapshot_sha256="e" * 64,
                error_code="manual_compensation_required",
                error_message="operator authorization is required",
                retry_delay_seconds=0,
            )
            if reclaimed_job is not None
            else None
        )
        waiting_claims = jobs.claim(
            _TENANT,
            "worker:recovery-postgres-c",
            limit=1,
            lease_seconds=30,
        )
        check(
            "waiting_operator_is_not_hot_retried",
            waiting_job is not None
            and waiting_job.status == "waiting_operator"
            and not waiting_claims,
            "manual recovery job was reclaimed without operator resume",
        )

        approval_authority = ApprovalCaseAuthority(sandbox.runtime_engine)
        approval_now = datetime.now(UTC)
        waiting_target = (
            f"gda://{_TENANT}/projection_recovery_job/{waiting_job.job_id}"
            if waiting_job is not None
            else ""
        )

        def create_resume_case(
            suffix: str,
            *,
            target_resource_urn: str = waiting_target,
            target_fingerprint: str = "e" * 64,
            action: str = "projection.recovery.compensate",
            verdict: ApprovalCaseStatus | None = ApprovalCaseStatus.APPROVED,
        ) -> str:
            case = ApprovalCase(
                tenant_id=_TENANT,
                approval_case_ref=f"gda://{_TENANT}/approval_case/{suffix}",
                target_resource_urn=target_resource_urn,
                target_fingerprint=target_fingerprint,
                action=action,
                requester_subject="workload:projection-recovery-controller",
                request_reason="manual compensation requires bounded authorization",
                request_context={"job_id": str(waiting_job.job_id)},
                requested_at=approval_now - timedelta(minutes=1),
                expires_at=approval_now + timedelta(hours=1),
            )
            approval_authority.create(case, owner_ref="team:data-platform")
            if verdict is not None:
                approval_authority.decide(
                    tenant_id=_TENANT,
                    approval_case_ref=case.approval_case_ref,
                    expected_state_version=0,
                    verdict=verdict,
                    actor_subject="human:recovery-approver",
                    reason="reviewed the exact recovery job and waiting snapshot",
                )
            return case.approval_case_ref

        def resume_is_rejected(approval_case_ref: str) -> bool:
            if waiting_job is None:
                return False
            try:
                jobs.resume(
                    waiting_job,
                    requested_by="human:recovery-operator",
                    approval_case_ref=approval_case_ref,
                    reason="reconcile target before bounded compensation",
                )
            except ProjectionRecoveryJobValidationError:
                return True
            return False

        wrong_snapshot_ref = create_resume_case(
            "projection-recovery-wrong-snapshot",
            target_fingerprint="f" * 64,
        )
        wrong_action_ref = create_resume_case(
            "projection-recovery-wrong-action",
            action="projection.recovery.observe",
        )
        rejected_ref = create_resume_case(
            "projection-recovery-rejected",
            verdict=ApprovalCaseStatus.REJECTED,
        )
        pending_ref = create_resume_case(
            "projection-recovery-exact",
            verdict=None,
        )
        check(
            "wrong_snapshot_approval_is_rejected",
            resume_is_rejected(wrong_snapshot_ref),
            "approval for a different waiting snapshot resumed the recovery job",
        )
        check(
            "wrong_action_approval_is_rejected",
            resume_is_rejected(wrong_action_ref),
            "approval for a different action resumed the recovery job",
        )
        check(
            "rejected_approval_is_rejected",
            resume_is_rejected(rejected_ref),
            "a rejected ApprovalCase resumed the recovery job",
        )
        check(
            "pending_approval_is_rejected",
            resume_is_rejected(pending_ref),
            "a pending ApprovalCase resumed the recovery job",
        )
        check(
            "cross_tenant_approval_is_rejected",
            resume_is_rejected(
                f"gda://{_OTHER_TENANT}/approval_case/projection-recovery-exact"
            ),
            "a cross-tenant ApprovalCase reference resumed the recovery job",
        )

        approval_authority.decide(
            tenant_id=_TENANT,
            approval_case_ref=pending_ref,
            expected_state_version=0,
            verdict=ApprovalCaseStatus.APPROVED,
            actor_subject="human:recovery-approver",
            reason="reviewed the exact recovery job and waiting snapshot",
        )
        resume_reason = "reconcile target before bounded compensation"
        resumed_job = (
            jobs.resume(
                waiting_job,
                requested_by="human:recovery-operator",
                approval_case_ref=pending_ref,
                reason=resume_reason,
            )
            if waiting_job is not None
            else None
        )
        resume_event = None
        if resumed_job is not None:
            with sandbox.runtime_engine.connect() as connection:
                with connection.begin():
                    connection.exec_driver_sql('SET LOCAL ROLE "gda_control_gateway"')
                    connection.execute(
                        text("SELECT set_config('app.current_tenant', :tenant, true)"),
                        {"tenant": _TENANT},
                    )
                    resume_event = (
                        connection.execute(
                            text(
                                """
                                SELECT approval_case_ref, job_id,
                                       resume_snapshot_sha256, resumed_by,
                                       resume_reason, resumed_at
                                FROM gda_control.cross_store_projection_recovery_resume_event
                                WHERE tenant_id = :tenant_id
                                  AND approval_case_ref = :approval_case_ref
                                """
                            ),
                            {
                                "tenant_id": _TENANT,
                                "approval_case_ref": pending_ref,
                            },
                        )
                        .mappings()
                        .one_or_none()
                    )
        resumed_claims = jobs.claim(
            _TENANT,
            "worker:recovery-postgres-c",
            limit=1,
            lease_seconds=30,
        )
        resumed_claim = resumed_claims[0].job if resumed_claims else None
        check(
            "operator_resume_grants_one_more_attempt",
            resumed_job is not None
            and resumed_job.status == "queued"
            and resumed_job.max_attempts == 3
            and resumed_job.resumed_by == "human:recovery-operator"
            and resumed_job.resumed_at is not None
            and resumed_job.resume_approval_case_ref == pending_ref
            and resumed_job.resume_snapshot_sha256 == "e" * 64
            and resumed_job.resume_reason == resume_reason
            and resumed_claim is not None
            and resumed_claim.attempt_count == 3
            and resumed_claim.claimed_by == "worker:recovery-postgres-c",
            "explicit operator resume did not make the recovery job claimable",
        )
        check(
            "approved_resume_has_append_only_consumption_evidence",
            resume_event is not None
            and resume_event["approval_case_ref"] == pending_ref
            and resume_event["job_id"] == waiting_job.job_id
            and resume_event["resume_snapshot_sha256"] == "e" * 64
            and resume_event["resumed_by"] == "human:recovery-operator"
            and resume_event["resume_reason"] == resume_reason,
            "approved recovery resume did not persist exact consumption evidence",
        )

        waiting_again = (
            jobs._finish(
                resumed_claim,
                "worker:recovery-postgres-c",
                status="waiting_operator",
                next_action="manual_compensation",
                snapshot_sha256="e" * 64,
                error_code="manual_compensation_required",
                error_message="a new compensation authorization is required",
                retry_delay_seconds=0,
            )
            if resumed_claim is not None
            else None
        )
        approval_reuse_rejected = False
        if waiting_again is not None:
            try:
                jobs.resume(
                    waiting_again,
                    requested_by="human:recovery-operator",
                    approval_case_ref=pending_ref,
                    reason="attempt to reuse consumed authorization",
                )
            except ProjectionRecoveryJobConflictError:
                approval_reuse_rejected = True
        check(
            "approval_case_can_authorize_only_one_resume",
            approval_reuse_rejected,
            "one ApprovalCase authorized more than one compensation resume",
        )

        heartbeat_projection = "cq.land_parcel.heartbeat"
        heartbeat_target = "postgis://cq-db/public.land_parcel_heartbeat"
        heartbeat_desired = plan.desired_state.model_copy(
            update={
                "projection_id": heartbeat_projection,
                "target_ref": heartbeat_target,
                "source_resource_version_ref": (
                    "gda://chongqing-customer/data_product/parcel-heartbeat-v1"
                ),
            }
        )
        heartbeat_observation = plan.observation.model_copy(
            update={
                "projection_id": heartbeat_projection,
                "target_ref": heartbeat_target,
            }
        )
        heartbeat_plan = build_projection_repair_plan(
            heartbeat_desired,
            heartbeat_observation,
            None,
        )
        jobs.enqueue(
            heartbeat_plan,
            submitted_by="agent:recovery-postgres-rehearsal",
        )

        class _CountingRepository:
            def __init__(self, repository):
                self.repository = repository
                self.renew_count = 0

            def get_engine(self):
                return self.repository.get_engine()

            def renew(self, *args, **kwargs):
                self.renew_count += 1
                return self.repository.renew(*args, **kwargs)

            def __getattr__(self, name):
                return getattr(self.repository, name)

        class _SlowProvider:
            def execute(self, submitted_plan):
                Event().wait(0.15)
                return _receipt(submitted_plan)

            def observe(self, submitted_plan):
                return _post_observation().model_copy(
                    update={
                        "projection_id": submitted_plan.projection_id,
                        "target_ref": submitted_plan.target_ref,
                    }
                )

        counting_jobs = _CountingRepository(jobs)
        heartbeat_outcomes = ProjectionRecoveryJobWorker(
            repository=counting_jobs,
            provider_resolver=lambda _plan: _SlowProvider(),
        ).run_once(
            _TENANT,
            "worker:recovery-postgres-heartbeat",
            lease_seconds=5,
            heartbeat_interval_seconds=0.02,
        )
        check(
            "durable_worker_heartbeats_during_provider_execution",
            len(heartbeat_outcomes) == 1
            and heartbeat_outcomes[0].status == "succeeded"
            and counting_jobs.renew_count >= 2,
            "durable recovery worker did not renew its lease during provider execution",
        )

        controller_projection = "cq.land_parcel.controller_bound"
        controller_target = "postgis://cq-db/public.land_parcel_controller_bound"
        controller_plan = _plan(
            projection_id=controller_projection,
            target_ref=controller_target,
        )
        controller_job = jobs.enqueue(
            controller_plan,
            submitted_by="agent:recovery-controller-postgres-rehearsal",
        )

        class _ControllerProvider:
            execute_count = 0

            def execute(self, submitted_plan):
                self.execute_count += 1
                return _receipt(submitted_plan)

            def observe(self, submitted_plan):
                return _post_observation(
                    projection_id=submitted_plan.projection_id,
                    target_ref=submitted_plan.target_ref,
                )

        controller_provider = _ControllerProvider()

        def controller_worker() -> ProjectionRecoveryJobWorker:
            return ProjectionRecoveryJobWorker(
                repository=jobs,
                provider_resolver=lambda _plan: controller_provider,
                authority_resolver=lambda _plan: InMemoryProjectionCheckpointLedger(),
                ledger_resolver=lambda _plan: PostgresProjectionRecoveryLedger(
                    _TENANT,
                    sandbox.runtime_engine,
                ),
                controller_binding_resolver=lambda job: _controller_binding(
                    job.plan,
                    sandbox.runtime_engine,
                ),
            )

        controller_outcomes = controller_worker().run_once(
            _TENANT,
            "worker:recovery-controller-postgres",
            lease_seconds=30,
        )
        controller_binding = _controller_binding(
            controller_plan,
            sandbox.runtime_engine,
        )
        controller_restart = CrossStoreRecoveryController(
            controller_binding.controller.run_id,
            ledger=PostgresCrossStoreRecoveryControllerLedger(
                (_TENANT,),
                sandbox.runtime_engine,
            ),
        )
        check(
            "durable_controller_settles_projection_job",
            len(controller_outcomes) == 1
            and controller_outcomes[0].job_id == controller_job.job_id
            and controller_outcomes[0].status == "succeeded"
            and controller_outcomes[0].next_action == "none"
            and controller_provider.execute_count == 1
            and controller_restart.snapshot.state is CrossStoreRecoveryRunState.COMPLETED
            and len(controller_restart.ledger.history(controller_restart.run_id)) == 3,
            "durable controller did not settle the successful projection job",
        )

        controller_unknown_plan = _plan(
            projection_id="cq.land_parcel.controller_unknown",
            target_ref="postgis://cq-db/public.land_parcel_controller_unknown",
        )
        controller_unknown_job = jobs.enqueue(
            controller_unknown_plan,
            submitted_by="agent:recovery-controller-unknown-rehearsal",
        )

        class _ControllerUnknownProvider(_ControllerProvider):
            def execute(self, _submitted_plan):
                self.execute_count += 1
                raise ProjectionProviderFailure(
                    "controller_provider_outcome_unknown",
                    outcome_known=False,
                )

        controller_unknown_provider = _ControllerUnknownProvider()

        def controller_unknown_worker() -> ProjectionRecoveryJobWorker:
            return ProjectionRecoveryJobWorker(
                repository=jobs,
                provider_resolver=lambda _plan: controller_unknown_provider,
                authority_resolver=lambda _plan: InMemoryProjectionCheckpointLedger(),
                ledger_resolver=lambda _plan: PostgresProjectionRecoveryLedger(
                    _TENANT,
                    sandbox.runtime_engine,
                ),
                controller_binding_resolver=lambda job: _controller_binding(
                    job.plan,
                    sandbox.runtime_engine,
                ),
            )

        controller_unknown_first = controller_unknown_worker().run_once(
            _TENANT,
            "worker:recovery-controller-unknown-a",
            lease_seconds=30,
            retry_delay_seconds=0,
        )
        controller_unknown_second = controller_unknown_worker().run_once(
            _TENANT,
            "worker:recovery-controller-unknown-b",
            lease_seconds=30,
            retry_delay_seconds=0,
        )
        controller_unknown_binding = _controller_binding(
            controller_unknown_plan,
            sandbox.runtime_engine,
        )
        check(
            "durable_controller_blocks_unknown_provider_replay",
            len(controller_unknown_first) == 1
            and controller_unknown_first[0].job_id == controller_unknown_job.job_id
            and controller_unknown_first[0].next_action == "reobserve_target"
            and len(controller_unknown_second) == 1
            and controller_unknown_second[0].status == "waiting_operator"
            and controller_unknown_provider.execute_count == 1
            and controller_unknown_binding.controller.snapshot.state
            is CrossStoreRecoveryRunState.RECONCILIATION_REQUIRED,
            "durable controller allowed an unknown provider outcome to replay",
        )

        unknown_projection = "cq.land_parcel.unknown_fault"
        unknown_target = "postgis://cq-db/public.land_parcel_unknown_fault"
        unknown_plan = _plan(
            projection_id=unknown_projection,
            target_ref=unknown_target,
        )

        class _UnknownOutcomeProvider:
            execute_count = 0

            def execute(self, _plan):
                self.execute_count += 1
                raise ProjectionProviderFailure(
                    "injected_provider_timeout",
                    outcome_known=False,
                )

            def observe(self, submitted_plan):
                return _post_observation(
                    projection_id=submitted_plan.projection_id,
                    target_ref=submitted_plan.target_ref,
                )

        unknown_provider = _UnknownOutcomeProvider()
        unknown_authority = InMemoryProjectionCheckpointLedger()
        unknown_first = ProjectionRecoveryWorker(
            unknown_plan,
            checkpointed_by="workload:recovery-postgres-fault-injection",
            provider=unknown_provider,
            authority=unknown_authority,
            ledger=reloaded,
            now=lambda: datetime(2026, 8, 15, 17, 3, tzinfo=UTC),
        ).run_once()
        unknown_second = ProjectionRecoveryWorker(
            unknown_plan,
            checkpointed_by="workload:recovery-postgres-fault-injection",
            provider=unknown_provider,
            authority=unknown_authority,
            ledger=reloaded,
            now=lambda: datetime(2026, 8, 15, 17, 4, tzinfo=UTC),
        ).run_once()
        unknown_current = reloaded.current(unknown_plan.plan_sha256)
        check(
            "unknown_provider_fault_stays_manual_after_reobserve",
            unknown_first.action_taken == "reobserve_target"
            and unknown_second.action_taken == "await_operator"
            and unknown_current is not None
            and unknown_current.next_action == "manual_compensation"
            and unknown_provider.execute_count == 1
            and not unknown_authority.history(
                tenant_id=_TENANT,
                projection_id=unknown_plan.projection_id,
                target_engine=unknown_plan.target_engine,
                target_ref=unknown_plan.target_ref,
            ),
            "unknown provider outcome was replayed or silently checkpointed",
        )

        heartbeat_loss_projection = "cq.land_parcel.heartbeat_loss"
        heartbeat_loss_target = "postgis://cq-db/public.land_parcel_heartbeat_loss"
        heartbeat_loss_plan = _plan(
            projection_id=heartbeat_loss_projection,
            target_ref=heartbeat_loss_target,
        )
        heartbeat_loss_job = jobs.enqueue(
            heartbeat_loss_plan,
            submitted_by="agent:recovery-postgres-fault-injection",
        )

        class _HeartbeatLossRepository:
            def __init__(self, repository):
                self.repository = repository
                self.renew_count = 0

            def get_engine(self):
                return self.repository.get_engine()

            def renew(self, *args, **kwargs):
                self.renew_count += 1
                if self.renew_count >= 2:
                    raise ProjectionRecoveryJobConflictError(
                        "injected_heartbeat_loss"
                    )
                return self.repository.renew(*args, **kwargs)

            def __getattr__(self, name):
                return getattr(self.repository, name)

        heartbeat_loss_repository = _HeartbeatLossRepository(jobs)
        heartbeat_loss_outcomes = ProjectionRecoveryJobWorker(
            repository=heartbeat_loss_repository,
            provider_resolver=lambda _plan: _SlowProvider(),
            authority_resolver=lambda _plan: InMemoryProjectionCheckpointLedger(),
        ).run_once(
            _TENANT,
            "worker:recovery-postgres-heartbeat-loss",
            lease_seconds=5,
            heartbeat_interval_seconds=0.02,
        )
        heartbeat_loss_state = jobs.get(_TENANT, heartbeat_loss_job.job_id)
        check(
            "heartbeat_loss_blocks_terminal_write",
            not heartbeat_loss_outcomes
            and heartbeat_loss_repository.renew_count >= 2
            and heartbeat_loss_state.status == "running"
            and heartbeat_loss_state.completed_at is None,
            "heartbeat loss allowed the old owner to write a terminal job state",
        )
        with sandbox.admin_connection() as connection:
            connection.execute(
                text("SELECT set_config('app.current_tenant', :tenant, true)"),
                {"tenant": _TENANT},
            )
            connection.execute(
                text(
                    "SELECT set_config("
                    "'gda.cross_store_projection_recovery_job_write_allowed', "
                    "'1', true)"
                )
            )
            connection.execute(
                text(
                    """
                    UPDATE gda_control.cross_store_projection_recovery_job
                    SET lease_expires_at = clock_timestamp() - interval '1 second'
                    WHERE tenant_id = :tenant_id AND job_id = :job_id
                    """
                ),
                {
                    "tenant_id": _TENANT,
                    "job_id": heartbeat_loss_job.job_id,
                },
            )
        reclaimed_after_heartbeat_loss = jobs.claim(
            _TENANT,
            "worker:recovery-postgres-heartbeat-reclaim",
            limit=1,
            lease_seconds=5,
        )
        reclaimed_after_loss = (
            reclaimed_after_heartbeat_loss[0].job
            if reclaimed_after_heartbeat_loss
            else None
        )
        check(
            "heartbeat_loss_job_can_be_reclaimed",
            reclaimed_after_loss is not None
            and reclaimed_after_loss.job_id == heartbeat_loss_job.job_id
            and reclaimed_after_loss.lease_generation == heartbeat_loss_state.lease_generation + 1
            and reclaimed_after_loss.claimed_by == "worker:recovery-postgres-heartbeat-reclaim",
            "heartbeat-loss job could not be reclaimed by a new owner",
        )

        try:
            with sandbox.runtime_engine.connect() as connection:
                with connection.begin():
                    connection.exec_driver_sql('SET LOCAL ROLE "gda_control_gateway"')
                    connection.execute(
                        text("SELECT set_config('app.current_tenant', :tenant, true)"),
                        {"tenant": _TENANT},
                    )
                    connection.execute(
                        text(
                            """
                            INSERT INTO gda_control.cross_store_projection_recovery_snapshot_history
                                (tenant_id, plan_sha256, snapshot_version,
                                 plan_idempotency_key, projection_id, target_engine,
                                 target_ref, snapshot_sha256, snapshot_document)
                            VALUES (:tenant_id, :plan_sha256, 99, :plan_key,
                                    :projection_id, 'postgis', :target_ref,
                                    :snapshot_sha256, CAST(:document AS jsonb))
                            """
                        ),
                        {
                            "tenant_id": _TENANT,
                            "plan_sha256": plan.plan_sha256,
                            "plan_key": plan.plan_idempotency_key,
                            "projection_id": plan.projection_id,
                            "target_ref": plan.target_ref,
                            "snapshot_sha256": "f" * 64,
                            "document": json.dumps(
                                {
                                    "tenant_id": _TENANT,
                                    "projection_id": plan.projection_id,
                                    "target_engine": "postgis",
                                    "target_ref": plan.target_ref,
                                    "plan_sha256": plan.plan_sha256,
                                    "plan_idempotency_key": plan.plan_idempotency_key,
                                    "snapshot_sha256": "f" * 64,
                                }
                            ),
                        },
                    )
            direct_write_rejected = False
        except DBAPIError as exc:
            direct_write_rejected = _sqlstate(exc) == "42501"
        check(
            "gateway_direct_table_write_rejected",
            direct_write_rejected,
            "gateway role retained direct recovery snapshot write permission",
        )

        try:
            with sandbox.runtime_engine.connect() as connection:
                with connection.begin():
                    connection.exec_driver_sql('SET LOCAL ROLE "gda_control_gateway"')
                    connection.execute(
                        text("SELECT set_config('app.current_tenant', :tenant, true)"),
                        {"tenant": _TENANT},
                    )
                    connection.execute(
                        text(
                            """
                            UPDATE gda_control.cross_store_projection_recovery_job
                            SET updated_at = clock_timestamp()
                            WHERE tenant_id = :tenant_id AND job_id = :job_id
                            """
                        ),
                        {"tenant_id": _TENANT, "job_id": enqueued.job_id},
                    )
            direct_job_write_rejected = False
        except DBAPIError as exc:
            direct_job_write_rejected = _sqlstate(exc) in {"42501", "55000"}
        check(
            "gateway_direct_job_write_rejected",
            direct_job_write_rejected,
            "gateway role retained direct recovery job write permission",
        )

        try:
            with sandbox.runtime_engine.connect() as connection:
                with connection.begin():
                    connection.exec_driver_sql('SET LOCAL ROLE "gda_control_gateway"')
                    connection.execute(
                        text("SELECT set_config('app.current_tenant', :tenant, true)"),
                        {"tenant": _TENANT},
                    )
                    connection.execute(
                        text(
                            """
                            INSERT INTO gda_control.cross_store_projection_recovery_resume_event (
                                tenant_id, approval_case_ref, job_id,
                                resume_snapshot_sha256, resumed_by, resume_reason
                            ) VALUES (
                                :tenant_id, :approval_case_ref, :job_id,
                                :snapshot_sha256, :resumed_by, :resume_reason
                            )
                            """
                        ),
                        {
                            "tenant_id": _TENANT,
                            "approval_case_ref": wrong_snapshot_ref,
                            "job_id": enqueued.job_id,
                            "snapshot_sha256": "f" * 64,
                            "resumed_by": "human:recovery-operator",
                            "resume_reason": "forged direct evidence",
                        },
                    )
            direct_resume_event_write_rejected = False
        except DBAPIError as exc:
            direct_resume_event_write_rejected = _sqlstate(exc) == "42501"
        check(
            "gateway_cannot_forge_resume_consumption_evidence",
            direct_resume_event_write_rejected,
            "gateway role could directly forge recovery resume evidence",
        )

        compensation_projection = "cq.land_parcel.approved_compensation"
        compensation_target = (
            "postgis://cq-db/public.land_parcel_approved_compensation"
        )
        compensation_plan = _plan(
            projection_id=compensation_projection,
            target_ref=compensation_target,
        )
        compensation_ledger = PostgresProjectionRecoveryLedger(
            _TENANT,
            sandbox.runtime_engine,
        )
        compensation_coordinator = ProjectionRecoveryCoordinator(
            compensation_plan,
            checkpointed_by="workload:approved-compensation-rehearsal",
            ledger=compensation_ledger,
        )
        compensation_waiting_snapshot = compensation_coordinator.require_compensation(
            "exact_approval_required"
        )
        compensation_enqueued = jobs.enqueue(
            compensation_plan,
            submitted_by="agent:approved-compensation-rehearsal",
            max_attempts=3,
        )
        compensation_first_claim = jobs.claim(
            _TENANT,
            "worker:approved-compensation-prepare",
            limit=1,
            lease_seconds=30,
        )
        compensation_waiting_job = (
            jobs._finish(
                compensation_first_claim[0].job,
                "worker:approved-compensation-prepare",
                status="waiting_operator",
                next_action="manual_compensation",
                snapshot_sha256=compensation_waiting_snapshot.snapshot_sha256,
                error_code="manual_compensation_required",
                error_message="exact ApprovalCase is required",
                retry_delay_seconds=0,
            )
            if compensation_first_claim
            else None
        )
        compensation_approval_ref = (
            f"gda://{_TENANT}/approval_case/approved-reapply-sealed-plan"
        )
        compensation_job_target = (
            f"gda://{_TENANT}/projection_recovery_job/"
            f"{compensation_enqueued.job_id}"
        )
        compensation_case = ApprovalCase(
            tenant_id=_TENANT,
            approval_case_ref=compensation_approval_ref,
            target_resource_urn=compensation_job_target,
            target_fingerprint=compensation_waiting_snapshot.snapshot_sha256,
            action="projection.recovery.compensate",
            requester_subject="workload:projection-recovery-controller",
            request_reason="reapply only the exact sealed recovery plan",
            request_context={
                "strategy": "approved_reapply_sealed_plan",
                "plan_sha256": compensation_plan.plan_sha256,
            },
            requested_at=datetime.now(UTC) - timedelta(minutes=1),
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        approval_authority.create(
            compensation_case,
            owner_ref="team:data-platform",
        )
        approval_authority.decide(
            tenant_id=_TENANT,
            approval_case_ref=compensation_approval_ref,
            expected_state_version=0,
            verdict=ApprovalCaseStatus.APPROVED,
            actor_subject="human:recovery-approver",
            reason="reviewed the exact sealed plan and waiting snapshot",
        )
        compensation_resumed = (
            jobs.resume(
                compensation_waiting_job,
                requested_by="human:recovery-operator",
                approval_case_ref=compensation_approval_ref,
                reason="execute the approved sealed-plan reapply strategy",
            )
            if compensation_waiting_job is not None
            else None
        )

        class _CompensationProvider:
            def __init__(self) -> None:
                self.executed_plans = []

            def execute(self, sealed_plan):
                self.executed_plans.append(sealed_plan)
                return _receipt(sealed_plan)

            def observe(self, _sealed_plan):
                return _post_observation(
                    projection_id=compensation_projection,
                    target_ref=compensation_target,
                )

        class _CompensationAuthorityRepository:
            def __init__(self, repository) -> None:
                self.repository = repository
                self.begin_count = 0
                self.finish_count = 0

            def begin_compensation_execution(self, *args, **kwargs):
                self.begin_count += 1
                return self.repository.begin_compensation_execution(*args, **kwargs)

            def finish_compensation_execution(self, *args, **kwargs):
                self.finish_count += 1
                return self.repository.finish_compensation_execution(*args, **kwargs)

            def __getattr__(self, name):
                return getattr(self.repository, name)

        compensation_provider = _CompensationProvider()
        checked_jobs = _CompensationAuthorityRepository(jobs)
        disabled_resolver = ProjectionRecoveryCompensationResolver(
            config=ProjectionRecoveryCompensationConfig(),
            authority=checked_jobs,
        )
        check(
            "compensation_strategy_is_disabled_by_default",
            compensation_resumed is not None
            and disabled_resolver(
                compensation_resumed,
                compensation_provider,
                compensation_ledger,
            )
            is None
            and not compensation_provider.executed_plans
            and checked_jobs.begin_count == 0
            and checked_jobs.finish_count == 0,
            "default recovery configuration resolved an executable compensation",
        )
        enabled_resolver = ProjectionRecoveryCompensationResolver(
            config=ProjectionRecoveryCompensationConfig(
                strategy="approved_reapply_sealed_plan"
            ),
            authority=checked_jobs,
        )
        crash_claims = jobs.claim(
            _TENANT,
            "worker:approved-compensation-crash",
            limit=1,
            lease_seconds=30,
        )
        crash_job = crash_claims[0].job if crash_claims else None
        crash_receipt = (
            enabled_resolver(
                crash_job,
                compensation_provider,
                compensation_ledger,
            )(compensation_plan, compensation_waiting_snapshot)
            if crash_job is not None
            else None
        )
        compensation_events = ()
        if crash_job is not None:
            with sandbox.runtime_engine.connect() as connection:
                with connection.begin():
                    connection.exec_driver_sql('SET LOCAL ROLE "gda_control_gateway"')
                    connection.execute(
                        text("SELECT set_config('app.current_tenant', :tenant, true)"),
                        {"tenant": _TENANT},
                    )
                    compensation_events = tuple(
                        connection.execute(
                            text(
                                """
                                SELECT event_index, event_type,
                                       compensation_attempt_id,
                                       provider_commit_ref, receipt_sha256
                                FROM gda_control.cross_store_projection_compensation_event
                                WHERE tenant_id = :tenant_id
                                  AND approval_case_ref = :approval_case_ref
                                ORDER BY event_index
                                """
                            ),
                            {
                                "tenant_id": _TENANT,
                                "approval_case_ref": compensation_approval_ref,
                            },
                        ).mappings()
                    )
            with sandbox.admin_connection() as connection:
                connection.execute(
                    text("SELECT set_config('app.current_tenant', :tenant, true)"),
                    {"tenant": _TENANT},
                )
                connection.execute(
                    text(
                        "SELECT set_config("
                        "'gda.cross_store_projection_recovery_job_write_allowed', "
                        "'1', true)"
                    )
                )
                connection.execute(
                    text(
                        """
                        UPDATE gda_control.cross_store_projection_recovery_job
                        SET lease_expires_at = clock_timestamp() - interval '1 second'
                        WHERE tenant_id = :tenant_id AND job_id = :job_id
                        """
                    ),
                    {"tenant_id": _TENANT, "job_id": crash_job.job_id},
                )

        compensation_outcomes = ProjectionRecoveryJobWorker(
            repository=checked_jobs,
            provider_resolver=lambda _plan: compensation_provider,
            authority_resolver=lambda _plan: InMemoryProjectionCheckpointLedger(),
            ledger_resolver=lambda _plan: compensation_ledger,
            compensation_resolver=enabled_resolver,
        ).run_once(
            _TENANT,
            "worker:approved-compensation-recover-receipt",
            lease_seconds=30,
        )
        compensation_outcome = (
            compensation_outcomes[0] if compensation_outcomes else None
        )
        compensation_current = compensation_ledger.current(
            compensation_plan.plan_sha256
        )
        check(
            "approved_reapply_executes_only_original_sealed_plan",
            compensation_outcome is not None
            and compensation_outcome.status == "succeeded"
            and compensation_outcome.next_action == "none"
            and compensation_provider.executed_plans == [compensation_plan]
            and compensation_provider.executed_plans[0].plan_sha256
            == compensation_enqueued.plan_sha256
            and compensation_provider.executed_plans[0].plan_idempotency_key
            == compensation_enqueued.plan_idempotency_key
            and compensation_provider.executed_plans[0].target_ref
            == compensation_target,
            "approved strategy changed or failed to execute the original sealed plan",
        )
        check(
            "compensation_rechecks_database_authority_and_durable_snapshot",
            checked_jobs.begin_count == 2
            and checked_jobs.finish_count == 1
            and compensation_current is not None
            and compensation_current.state.value == "authority_committed"
            and compensation_current.checkpoint_sha256 is not None,
            "controlled compensation skipped database authority or durable recovery",
        )
        check(
            "persisted_compensation_receipt_closes_worker_crash_gap",
            crash_receipt is not None
            and len(compensation_events) == 2
            and compensation_events[0]["event_type"] == "started"
            and compensation_events[1]["event_type"] == "succeeded"
            and compensation_events[0]["compensation_attempt_id"]
            == compensation_events[1]["compensation_attempt_id"]
            and compensation_events[1]["provider_commit_ref"]
            == crash_receipt.provider_commit_ref
            and compensation_events[1]["receipt_sha256"]
            == crash_receipt.receipt_sha256
            and compensation_provider.executed_plans == [compensation_plan],
            "worker restart re-executed provider or lost persisted receipt evidence",
        )

        reconciliation_projection = "cq.land_parcel.reconciled_compensation"
        reconciliation_target = (
            "postgis://cq-db/public.land_parcel_reconciled_compensation"
        )
        reconciliation_plan = _plan(
            projection_id=reconciliation_projection,
            target_ref=reconciliation_target,
        )
        reconciliation_ledger = PostgresProjectionRecoveryLedger(
            _TENANT,
            sandbox.runtime_engine,
        )
        reconciliation_waiting_snapshot = ProjectionRecoveryCoordinator(
            reconciliation_plan,
            checkpointed_by="workload:compensation-reconciliation-rehearsal",
            ledger=reconciliation_ledger,
        ).require_compensation("exact_reconciliation_required")
        reconciliation_enqueued = jobs.enqueue(
            reconciliation_plan,
            submitted_by="agent:compensation-reconciliation-rehearsal",
            max_attempts=3,
        )
        reconciliation_prepare_claims = jobs.claim(
            _TENANT,
            "worker:compensation-reconciliation-prepare",
            limit=1,
            lease_seconds=30,
        )
        reconciliation_waiting_job = (
            jobs._finish(
                reconciliation_prepare_claims[0].job,
                "worker:compensation-reconciliation-prepare",
                status="waiting_operator",
                next_action="manual_compensation",
                snapshot_sha256=reconciliation_waiting_snapshot.snapshot_sha256,
                error_code="manual_compensation_required",
                error_message="exact ApprovalCase is required",
                retry_delay_seconds=0,
            )
            if reconciliation_prepare_claims
            else None
        )
        reconciliation_execution_approval_ref = (
            f"gda://{_TENANT}/approval_case/reconciliation-original-execution"
        )
        reconciliation_job_target = (
            f"gda://{_TENANT}/projection_recovery_job/"
            f"{reconciliation_enqueued.job_id}"
        )
        reconciliation_execution_case = ApprovalCase(
            tenant_id=_TENANT,
            approval_case_ref=reconciliation_execution_approval_ref,
            target_resource_urn=reconciliation_job_target,
            target_fingerprint=reconciliation_waiting_snapshot.snapshot_sha256,
            action="projection.recovery.compensate",
            requester_subject="workload:projection-recovery-controller",
            request_reason="start only the exact sealed recovery attempt",
            request_context={
                "strategy": "approved_reapply_sealed_plan",
                "plan_sha256": reconciliation_plan.plan_sha256,
            },
            requested_at=datetime.now(UTC) - timedelta(minutes=1),
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        approval_authority.create(
            reconciliation_execution_case,
            owner_ref="team:data-platform",
        )
        approval_authority.decide(
            tenant_id=_TENANT,
            approval_case_ref=reconciliation_execution_approval_ref,
            expected_state_version=0,
            verdict=ApprovalCaseStatus.APPROVED,
            actor_subject="human:recovery-approver",
            reason="reviewed the exact sealed plan and waiting snapshot",
        )
        reconciliation_resumed = (
            jobs.resume(
                reconciliation_waiting_job,
                requested_by="human:recovery-operator",
                approval_case_ref=reconciliation_execution_approval_ref,
                reason="start the approved sealed compensation attempt",
            )
            if reconciliation_waiting_job is not None
            else None
        )
        reconciliation_claims = jobs.claim(
            _TENANT,
            "worker:compensation-reconciliation-crash",
            limit=1,
            lease_seconds=30,
        )
        reconciliation_claim = (
            reconciliation_claims[0].job if reconciliation_claims else None
        )
        reconciliation_attempt_id = (
            projection_recovery_compensation_attempt_id(reconciliation_claim)
            if reconciliation_claim is not None
            else None
        )
        started_only = (
            jobs.begin_compensation_execution(
                reconciliation_claim,
                reconciliation_waiting_snapshot,
                strategy="approved_reapply_sealed_plan",
                compensation_attempt_id=reconciliation_attempt_id,
            )
            if reconciliation_claim is not None
            and reconciliation_attempt_id is not None
            else None
        )
        indeterminate_waiting = (
            jobs.fail(
                reconciliation_claim,
                "worker:compensation-reconciliation-crash",
                ProjectionRecoveryCompensationIndeterminateError(
                    "compensation_execution_outcome_is_indeterminate",
                    outcome_known=False,
                ),
                retry_delay_seconds=0,
            )
            if reconciliation_claim is not None
            else None
        )
        hot_retry_claims = jobs.claim(
            _TENANT,
            "worker:compensation-reconciliation-hot-retry",
            limit=1,
            lease_seconds=30,
        )
        check(
            "started_only_compensation_stops_in_waiting_operator",
            reconciliation_resumed is not None
            and started_only is not None
            and started_only.outcome == "started"
            and indeterminate_waiting is not None
            and indeterminate_waiting.status == "waiting_operator"
            and indeterminate_waiting.next_action == "manual_compensation"
            and not hot_retry_claims,
            "started-only compensation remained hot-retryable",
        )

        reconciliation_observation_ref = (
            f"gda://{_TENANT}/projection_observation/"
            "reconciled-provider-commit"
        )
        reconciliation_observation_sha256 = "b" * 64
        reconciled_commit_ref = _receipt(reconciliation_plan).provider_commit_ref
        reconciled_receipt_sha256 = compensation_receipt_fingerprint(
            plan_sha256=reconciliation_plan.plan_sha256,
            idempotency_key=reconciliation_plan.plan_idempotency_key,
            provider_commit_ref=reconciled_commit_ref,
        )
        reconciliation_fingerprint = (
            compensation_reconciliation_target_fingerprint(
                tenant_id=_TENANT,
                job_id=reconciliation_enqueued.job_id,
                compensation_attempt_id=reconciliation_attempt_id,
                resume_snapshot_sha256=(
                    reconciliation_waiting_snapshot.snapshot_sha256
                ),
                plan_sha256=reconciliation_plan.plan_sha256,
                plan_idempotency_key=reconciliation_plan.plan_idempotency_key,
            )
            if reconciliation_attempt_id is not None
            else ""
        )
        reconciliation_approval_ref = (
            f"gda://{_TENANT}/approval_case/reconcile-provider-commit"
        )
        reconciliation_attempt_target = (
            f"gda://{_TENANT}/projection_compensation_attempt/"
            f"{reconciliation_attempt_id}"
        )
        reconciliation_case = ApprovalCase(
            tenant_id=_TENANT,
            approval_case_ref=reconciliation_approval_ref,
            target_resource_urn=reconciliation_attempt_target,
            target_fingerprint=reconciliation_fingerprint,
            action="projection.recovery.compensation.reconcile_committed",
            requester_subject="workload:projection-recovery-controller",
            request_reason="seal observed Provider commit for started-only attempt",
            request_context={
                "compensation_attempt_id": str(reconciliation_attempt_id),
                "original_approval_case_ref": (
                    reconciliation_execution_approval_ref
                ),
                "observed_by": "human:recovery-operator",
                "observation_ref": reconciliation_observation_ref,
                "observation_sha256": reconciliation_observation_sha256,
                "verdict": "provider_committed",
                "receipt_sha256": reconciled_receipt_sha256,
            },
            requested_at=datetime.now(UTC) - timedelta(minutes=1),
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        approval_authority.create(
            reconciliation_case,
            owner_ref="team:data-platform",
        )
        approval_authority.decide(
            tenant_id=_TENANT,
            approval_case_ref=reconciliation_approval_ref,
            expected_state_version=0,
            verdict=ApprovalCaseStatus.APPROVED,
            actor_subject="human:recovery-reconciliation-approver",
            reason="verified the Provider commit and plan-bound receipt",
        )
        reconciliation_record = (
            jobs.reconcile_compensation_execution(
                tenant_id=_TENANT,
                job_id=reconciliation_enqueued.job_id,
                original_approval_case_ref=(
                    reconciliation_execution_approval_ref
                ),
                reconciliation_approval_case_ref=reconciliation_approval_ref,
                compensation_attempt_id=reconciliation_attempt_id,
                target_fingerprint=reconciliation_fingerprint,
                verdict="provider_committed",
                observed_by="human:recovery-operator",
                observation_ref=reconciliation_observation_ref,
                observation_sha256=reconciliation_observation_sha256,
                reason="Provider commit identity matches the original sealed plan",
                provider_commit_ref=reconciled_commit_ref,
                receipt_sha256=reconciled_receipt_sha256,
            )
            if reconciliation_attempt_id is not None
            else None
        )

        class _ReconciledProvider:
            execute_count = 0

            def execute(self, submitted_plan):
                self.execute_count += 1
                return _receipt(submitted_plan)

            def observe(self, submitted_plan):
                return _post_observation(
                    projection_id=submitted_plan.projection_id,
                    target_ref=submitted_plan.target_ref,
                )

        reconciled_provider = _ReconciledProvider()
        reconciled_resolver = ProjectionRecoveryCompensationResolver(
            config=ProjectionRecoveryCompensationConfig(
                strategy="approved_reapply_sealed_plan"
            ),
            authority=jobs,
        )
        reconciled_outcomes = ProjectionRecoveryJobWorker(
            repository=jobs,
            provider_resolver=lambda _plan: reconciled_provider,
            authority_resolver=lambda _plan: InMemoryProjectionCheckpointLedger(),
            ledger_resolver=lambda _plan: reconciliation_ledger,
            compensation_resolver=reconciled_resolver,
        ).run_once(
            _TENANT,
            "worker:compensation-reconciliation-recover",
            lease_seconds=30,
        )
        reconciled_outcome = reconciled_outcomes[0] if reconciled_outcomes else None
        check(
            "approved_reconciliation_recovers_without_provider_replay",
            reconciliation_record is not None
            and reconciliation_record.verdict == "provider_committed"
            and reconciliation_record.receipt_sha256
            == reconciled_receipt_sha256
            and reconciled_outcome is not None
            and reconciled_outcome.status == "succeeded"
            and reconciled_provider.execute_count == 0,
            "approved Provider-state reconciliation replayed compensation",
        )

        not_committed_plan = _plan(
            projection_id="cq.land_parcel.not_committed_compensation",
            target_ref=(
                "postgis://cq-db/public.land_parcel_not_committed_compensation"
            ),
        )
        not_committed_ledger = PostgresProjectionRecoveryLedger(
            _TENANT,
            sandbox.runtime_engine,
        )
        not_committed_snapshot = ProjectionRecoveryCoordinator(
            not_committed_plan,
            checkpointed_by="workload:not-committed-reconciliation-rehearsal",
            ledger=not_committed_ledger,
        ).require_compensation("exact_reconciliation_required")
        not_committed_enqueued = jobs.enqueue(
            not_committed_plan,
            submitted_by="agent:not-committed-reconciliation-rehearsal",
            max_attempts=3,
        )
        not_committed_prepare = jobs.claim(
            _TENANT,
            "worker:not-committed-prepare",
            limit=1,
            lease_seconds=30,
        )
        not_committed_waiting = (
            jobs._finish(
                not_committed_prepare[0].job,
                "worker:not-committed-prepare",
                status="waiting_operator",
                next_action="manual_compensation",
                snapshot_sha256=not_committed_snapshot.snapshot_sha256,
                error_code="manual_compensation_required",
                error_message="exact ApprovalCase is required",
                retry_delay_seconds=0,
            )
            if not_committed_prepare
            else None
        )
        not_committed_execution_ref = (
            f"gda://{_TENANT}/approval_case/not-committed-original-execution"
        )
        not_committed_job_target = (
            f"gda://{_TENANT}/projection_recovery_job/"
            f"{not_committed_enqueued.job_id}"
        )
        not_committed_execution_case = ApprovalCase(
            tenant_id=_TENANT,
            approval_case_ref=not_committed_execution_ref,
            target_resource_urn=not_committed_job_target,
            target_fingerprint=not_committed_snapshot.snapshot_sha256,
            action="projection.recovery.compensate",
            requester_subject="workload:projection-recovery-controller",
            request_reason="start the exact sealed recovery attempt",
            request_context={"plan_sha256": not_committed_plan.plan_sha256},
            requested_at=datetime.now(UTC) - timedelta(minutes=1),
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        approval_authority.create(
            not_committed_execution_case,
            owner_ref="team:data-platform",
        )
        approval_authority.decide(
            tenant_id=_TENANT,
            approval_case_ref=not_committed_execution_ref,
            expected_state_version=0,
            verdict=ApprovalCaseStatus.APPROVED,
            actor_subject="human:recovery-approver",
            reason="reviewed the exact sealed plan and waiting snapshot",
        )
        not_committed_resumed = (
            jobs.resume(
                not_committed_waiting,
                requested_by="human:recovery-operator",
                approval_case_ref=not_committed_execution_ref,
                reason="start the approved sealed compensation attempt",
            )
            if not_committed_waiting is not None
            else None
        )
        not_committed_claims = jobs.claim(
            _TENANT,
            "worker:not-committed-crash",
            limit=1,
            lease_seconds=30,
        )
        not_committed_claim = (
            not_committed_claims[0].job if not_committed_claims else None
        )
        not_committed_attempt_id = (
            projection_recovery_compensation_attempt_id(not_committed_claim)
            if not_committed_claim is not None
            else None
        )
        if not_committed_claim is not None and not_committed_attempt_id is not None:
            jobs.begin_compensation_execution(
                not_committed_claim,
                not_committed_snapshot,
                strategy="approved_reapply_sealed_plan",
                compensation_attempt_id=not_committed_attempt_id,
            )
            not_committed_waiting = jobs.fail(
                not_committed_claim,
                "worker:not-committed-crash",
                ProjectionRecoveryCompensationIndeterminateError(
                    "compensation_execution_outcome_is_indeterminate",
                    outcome_known=False,
                ),
                retry_delay_seconds=0,
            )

        not_committed_observation_ref = (
            f"gda://{_TENANT}/projection_observation/provider-absence"
        )
        not_committed_observation_sha256 = "d" * 64
        not_committed_fingerprint = (
            compensation_reconciliation_target_fingerprint(
                tenant_id=_TENANT,
                job_id=not_committed_enqueued.job_id,
                compensation_attempt_id=not_committed_attempt_id,
                resume_snapshot_sha256=not_committed_snapshot.snapshot_sha256,
                plan_sha256=not_committed_plan.plan_sha256,
                plan_idempotency_key=not_committed_plan.plan_idempotency_key,
            )
            if not_committed_attempt_id is not None
            else ""
        )
        not_committed_reconciliation_ref = (
            f"gda://{_TENANT}/approval_case/reconcile-provider-absence"
        )
        not_committed_reconciliation_case = ApprovalCase(
            tenant_id=_TENANT,
            approval_case_ref=not_committed_reconciliation_ref,
            target_resource_urn=(
                f"gda://{_TENANT}/projection_compensation_attempt/"
                f"{not_committed_attempt_id}"
            ),
            target_fingerprint=not_committed_fingerprint,
            action="projection.recovery.compensation.reconcile_not_committed",
            requester_subject="workload:projection-recovery-controller",
            request_reason="seal observed absence for started-only attempt",
            request_context={
                "compensation_attempt_id": str(not_committed_attempt_id),
                "original_approval_case_ref": not_committed_execution_ref,
                "observed_by": "human:recovery-operator",
                "observation_ref": not_committed_observation_ref,
                "observation_sha256": not_committed_observation_sha256,
                "verdict": "provider_not_committed",
            },
            requested_at=datetime.now(UTC) - timedelta(minutes=1),
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        approval_authority.create(
            not_committed_reconciliation_case,
            owner_ref="team:data-platform",
        )
        approval_authority.decide(
            tenant_id=_TENANT,
            approval_case_ref=not_committed_reconciliation_ref,
            expected_state_version=0,
            verdict=ApprovalCaseStatus.APPROVED,
            actor_subject="human:recovery-reconciliation-approver",
            reason="verified Provider absence for the original idempotency key",
        )
        not_committed_record = (
            jobs.reconcile_compensation_execution(
                tenant_id=_TENANT,
                job_id=not_committed_enqueued.job_id,
                original_approval_case_ref=not_committed_execution_ref,
                reconciliation_approval_case_ref=(
                    not_committed_reconciliation_ref
                ),
                compensation_attempt_id=not_committed_attempt_id,
                target_fingerprint=not_committed_fingerprint,
                verdict="provider_not_committed",
                observed_by="human:recovery-operator",
                observation_ref=not_committed_observation_ref,
                observation_sha256=not_committed_observation_sha256,
                reason="Provider proved no commit exists for the idempotency key",
            )
            if not_committed_attempt_id is not None
            else None
        )
        not_committed_unauthorized_claims = jobs.claim(
            _TENANT,
            "worker:not-committed-without-new-approval",
            limit=1,
            lease_seconds=30,
        )

        not_committed_retry_ref = (
            f"gda://{_TENANT}/approval_case/not-committed-approved-retry"
        )
        not_committed_retry_case = ApprovalCase(
            tenant_id=_TENANT,
            approval_case_ref=not_committed_retry_ref,
            target_resource_urn=not_committed_job_target,
            target_fingerprint=not_committed_snapshot.snapshot_sha256,
            action="projection.recovery.compensate",
            requester_subject="workload:projection-recovery-controller",
            request_reason="retry after approved not-committed reconciliation",
            request_context={"plan_sha256": not_committed_plan.plan_sha256},
            requested_at=datetime.now(UTC) - timedelta(minutes=1),
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        approval_authority.create(
            not_committed_retry_case,
            owner_ref="team:data-platform",
        )
        approval_authority.decide(
            tenant_id=_TENANT,
            approval_case_ref=not_committed_retry_ref,
            expected_state_version=0,
            verdict=ApprovalCaseStatus.APPROVED,
            actor_subject="human:recovery-approver",
            reason="approved one new attempt after verified provider absence",
        )
        not_committed_retry = (
            jobs.resume(
                not_committed_waiting,
                requested_by="human:recovery-operator",
                approval_case_ref=not_committed_retry_ref,
                reason="retry only after Provider absence was verified",
            )
            if not_committed_waiting is not None
            else None
        )

        class _NotCommittedRetryProvider:
            execute_count = 0

            def execute(self, submitted_plan):
                self.execute_count += 1
                return _receipt(submitted_plan)

            def observe(self, submitted_plan):
                return _post_observation(
                    projection_id=submitted_plan.projection_id,
                    target_ref=submitted_plan.target_ref,
                )

        not_committed_provider = _NotCommittedRetryProvider()
        not_committed_resolver = ProjectionRecoveryCompensationResolver(
            config=ProjectionRecoveryCompensationConfig(
                strategy="approved_reapply_sealed_plan"
            ),
            authority=jobs,
        )
        not_committed_outcomes = ProjectionRecoveryJobWorker(
            repository=jobs,
            provider_resolver=lambda _plan: not_committed_provider,
            authority_resolver=lambda _plan: InMemoryProjectionCheckpointLedger(),
            ledger_resolver=lambda _plan: not_committed_ledger,
            compensation_resolver=not_committed_resolver,
        ).run_once(
            _TENANT,
            "worker:not-committed-approved-retry",
            lease_seconds=30,
        )
        not_committed_outcome = (
            not_committed_outcomes[0] if not_committed_outcomes else None
        )
        check(
            "not_committed_reconciliation_requires_new_approved_attempt",
            not_committed_resumed is not None
            and not_committed_record is not None
            and not_committed_record.verdict == "provider_not_committed"
            and not_committed_record.provider_commit_ref is None
            and not not_committed_unauthorized_claims
            and not_committed_retry is not None
            and not_committed_outcome is not None
            and not_committed_outcome.status == "succeeded"
            and not_committed_provider.execute_count == 1,
            "not-committed ruling bypassed approval or failed bounded retry",
        )

        try:
            with sandbox.runtime_engine.connect() as connection:
                with connection.begin():
                    connection.exec_driver_sql('SET LOCAL ROLE "gda_control_gateway"')
                    connection.execute(
                        text("SELECT set_config('app.current_tenant', :tenant, true)"),
                        {"tenant": _TENANT},
                    )
                    connection.execute(
                        text(
                            """
                            INSERT INTO
                                gda_control
                                    .cross_store_projection_compensation_reconciliation_event (
                                    tenant_id, compensation_attempt_id, job_id,
                                    original_approval_case_ref,
                                    reconciliation_approval_case_ref,
                                    target_fingerprint, resume_snapshot_sha256,
                                    plan_sha256, plan_idempotency_key, verdict,
                                    observed_by, observation_ref,
                                    observation_sha256, reason,
                                    resumed_automatically
                                ) VALUES (
                                    :tenant_id, :attempt_id, :job_id,
                                    :original_ref, :reconciliation_ref,
                                    :target_fingerprint, :snapshot_sha256,
                                    :plan_sha256, :plan_key, 'provider_not_committed',
                                    'human:forged', 'forged-observation',
                                    :observation_sha256, 'forged evidence', FALSE
                                )
                            """
                        ),
                        {
                            "tenant_id": _TENANT,
                            "attempt_id": not_committed_attempt_id,
                            "job_id": not_committed_enqueued.job_id,
                            "original_ref": not_committed_execution_ref,
                            "reconciliation_ref": not_committed_reconciliation_ref,
                            "target_fingerprint": not_committed_fingerprint,
                            "snapshot_sha256": not_committed_snapshot.snapshot_sha256,
                            "plan_sha256": not_committed_plan.plan_sha256,
                            "plan_key": not_committed_plan.plan_idempotency_key,
                            "observation_sha256": "f" * 64,
                        },
                    )
            direct_reconciliation_write_rejected = False
        except DBAPIError as exc:
            direct_reconciliation_write_rejected = _sqlstate(exc) == "42501"
        check(
            "gateway_cannot_forge_compensation_reconciliation_evidence",
            direct_reconciliation_write_rejected,
            "gateway role could directly forge compensation reconciliation evidence",
        )

        try:
            with sandbox.runtime_engine.connect() as connection:
                with connection.begin():
                    connection.exec_driver_sql('SET LOCAL ROLE "gda_control_gateway"')
                    connection.execute(
                        text("SELECT set_config('app.current_tenant', :tenant, true)"),
                        {"tenant": _TENANT},
                    )
                    connection.execute(
                        text(
                            """
                            INSERT INTO gda_control.cross_store_projection_compensation_event (
                                tenant_id, approval_case_ref, event_index,
                                compensation_attempt_id, job_id,
                                resume_snapshot_sha256, plan_sha256,
                                plan_idempotency_key, strategy, worker_id,
                                lease_generation, event_type
                            ) VALUES (
                                :tenant_id, :approval_case_ref, 1,
                                :attempt_id, :job_id, :snapshot_sha256,
                                :plan_sha256, :plan_key,
                                'approved_reapply_sealed_plan',
                                'worker:forged-compensation', 1, 'started'
                            )
                            """
                        ),
                        {
                            "tenant_id": _TENANT,
                            "approval_case_ref": wrong_snapshot_ref,
                            "attempt_id": "2774a45f-aa33-4a70-b1de-f25c60ca3236",
                            "job_id": enqueued.job_id,
                            "snapshot_sha256": "f" * 64,
                            "plan_sha256": plan.plan_sha256,
                            "plan_key": plan.plan_idempotency_key,
                        },
                    )
            direct_compensation_event_write_rejected = False
        except DBAPIError as exc:
            direct_compensation_event_write_rejected = _sqlstate(exc) == "42501"
        check(
            "gateway_cannot_forge_compensation_execution_evidence",
            direct_compensation_event_write_rejected,
            "gateway role could directly forge compensation execution evidence",
        )

        # Exercise the same sealed plan after a process boundary.
        check(
            "sealed_plan_identity_preserved",
            worker_current is not None
            and worker_current.plan_sha256 == plan.plan_sha256
            and worker_current.plan_idempotency_key == plan.plan_idempotency_key
            and worker_current.target_ref == plan.target_ref,
            "durable recovery identity changed across reload",
        )

    payload = {
        "schema_id": "gda.cross-store-projection-recovery-postgres-rehearsal.v1",
        "checked_at": datetime.now(UTC),
        "database_scope": "temporary_database_only",
        "migration_ids": (
            "092",
            "094",
            "102",
            "103",
            "169",
            "170",
            "171",
            "172",
            "173",
            "174",
            "233",
        ),
        "checks": checks,
        "passed": all(checks.values()),
        "failure_reasons": tuple(failures),
        "technical_baseline_status": "technical_baseline_unreviewed",
        "decision_status": "assisted_precheck_not_for_production_decision",
    }
    return CrossStoreProjectionRecoveryPostgresRehearsalReport(
        **payload,
        report_sha256=_report_hash(payload),
    )


def write_cross_store_projection_recovery_postgres_rehearsal_report(
    report: CrossStoreProjectionRecoveryPostgresRehearsalReport,
    output_path: str | Path,
) -> Path:
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    return target


__all__ = [
    "CrossStoreProjectionRecoveryPostgresRehearsalReport",
    "run_cross_store_projection_recovery_postgres_rehearsal",
    "write_cross_store_projection_recovery_postgres_rehearsal_report",
]
