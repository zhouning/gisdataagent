#!/usr/bin/env python3
"""Rehearse durable AgentOps specialist retry budget across worker processes."""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from data_agent.agentops_specialist_retry_budget import (
    RETRY_BUDGET_MIGRATION,
    PostgresSpecialistRetryBudgetAuthority,
    provider_operation_family_key,
)
from data_agent.agentops_temporal_contracts import (
    TemporalActivityRequest,
    derive_temporal_activity_id,
    temporal_contract_fingerprint,
)
from data_agent.cross_store_projection_postgres_rehearsal import (
    _execute_migration,
    _temporary_postgres,
)
from data_agent.platform_contracts import FrozenContract, canonical_json_fingerprint
from data_agent.test_agentops_specialist_operation_authority import _request

REPORT_SCHEMA = "gda.agentops_specialist_retry_budget_postgres_rehearsal.v1"
_BASE_MIGRATIONS = (
    "092_platform_control_ledger.sql",
    "094_platform_control_gateway.sql",
)


class RetryBudgetRehearsalReport(FrozenContract):
    schema_id: str = REPORT_SCHEMA
    checked_at: datetime
    database_scope: str = "temporary_database_only"
    migration_ids: tuple[str, ...]
    checks: dict[str, bool]
    passed: bool
    failure_reasons: tuple[str, ...]
    production_readiness_claimed: bool = False
    report_sha256: str


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


def _attempt(request: TemporalActivityRequest, attempt_no: int) -> TemporalActivityRequest:
    values = request.model_dump(mode="python")
    values["attempt_no"] = attempt_no
    values["activity_id"] = derive_temporal_activity_id(
        run_id=request.run_id,
        tool_call_id=request.tool_call_id,
        attempt_no=attempt_no,
    )
    values["request_sha256"] = temporal_contract_fingerprint(
        TemporalActivityRequest.schema_id, values, "request_sha256"
    )
    return TemporalActivityRequest(**values)


def run_rehearsal(admin_url: str) -> RetryBudgetRehearsalReport:
    checks: dict[str, bool] = {}
    failures: list[str] = []

    def check(name: str, passed: bool, reason: str) -> None:
        checks[name] = passed
        if not passed:
            failures.append(reason)

    first = _request()
    second = _attempt(first, 2)
    operation_key = provider_operation_family_key(first)
    with _temporary_postgres(admin_url) as sandbox:
        if sandbox.runtime_engine is None:
            raise RuntimeError("temporary PostgreSQL runtime was not initialized")
        with sandbox.admin_connection() as connection:
            connection.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA public")
            for filename in _BASE_MIGRATIONS:
                migration = (
                    Path(__file__).resolve().parent.parent
                    / "data_agent"
                    / "migrations"
                    / filename
                )
                _execute_migration(connection, migration.read_text(encoding="utf-8"))
            _execute_migration(
                connection,
                RETRY_BUDGET_MIGRATION.read_text(encoding="utf-8"),
            )

        worker_a = PostgresSpecialistRetryBudgetAuthority(
            "planning", sandbox.runtime_engine, recorded_by="workload:retry-worker-a"
        )
        worker_b = PostgresSpecialistRetryBudgetAuthority(
            "planning", sandbox.runtime_engine, recorded_by="workload:retry-worker-b"
        )
        first_admission = worker_a.admit(
            first,
            operation_key=operation_key,
            max_attempts=1,
            worker_id="workload:retry-worker-a",
        )
        replay = worker_b.admit(
            first,
            operation_key=operation_key,
            max_attempts=1,
            worker_id="workload:retry-worker-b",
        )
        check(
            "same_attempt_replay_is_idempotent_across_workers",
            first_admission == replay and first_admission.admitted,
            "worker replacement consumed a second retry slot for the same activity attempt",
        )
        denied = worker_b.admit(
            second,
            operation_key=operation_key,
            max_attempts=1,
            worker_id="workload:retry-worker-b",
        )
        check(
            "new_attempt_is_denied_after_budget_exhaustion",
            not denied.admitted and denied.reason == "retry_budget_exhausted",
            "explicit new attempt was admitted after the retry budget was exhausted",
        )
        observation = worker_a.observe(tenant_id="planning", operation_key=operation_key)
        check(
            "budget_count_is_shared_and_not_reset",
            observation is not None
            and observation.attempt_count == 1
            and observation.status == "exhausted"
            and len(observation.admissions) == 2,
            "durable budget count or admission history did not survive worker replacement",
        )

    values: dict[str, Any] = {
        "checked_at": datetime.now(UTC),
        "migration_ids": tuple(
            [filename.split("_", 1)[0] for filename in _BASE_MIGRATIONS]
            + [RETRY_BUDGET_MIGRATION.name.split("_", 1)[0]]
        ),
        "checks": checks,
        "passed": not failures,
        "failure_reasons": tuple(failures),
        "production_readiness_claimed": False,
    }
    values["report_sha256"] = _report_hash(values)
    return RetryBudgetRehearsalReport(**values)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if not args.database_url:
        raise SystemExit("--database-url or DATABASE_URL is required")
    report = run_rehearsal(args.database_url)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
