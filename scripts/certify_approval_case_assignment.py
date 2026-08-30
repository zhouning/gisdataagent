#!/usr/bin/env python3
"""Certify ApprovalCase assignment authority in disposable PostgreSQL 16."""

from __future__ import annotations

import argparse
import json
import secrets
import subprocess
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from data_agent.approval_case_authority import (
    ApprovalCaseAuthority,
    ApprovalCaseConflictError,
    ApprovalCaseForbiddenError,
    ApprovalCaseValidationError,
)
from data_agent.platform_contracts import ApprovalCase, ApprovalCaseAssignmentOperation

REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = tuple(
    REPO_ROOT / "data_agent/migrations" / name
    for name in (
        "092_platform_control_ledger.sql",
        "094_platform_control_gateway.sql",
        "102_source_schema_drift_ledger.sql",
        "103_unified_approval_case_authority.sql",
        "118_approval_case_sla_notification_outbox.sql",
        "119_approval_notification_governed_recovery.sql",
        "120_approval_case_assignment_authority.sql",
        "121_approval_principal_directory.sql",
    )
)
RUNTIME_ROLE = "gda_approval_assignment_runtime"
TENANT_A = "assignment-cert-a"
TENANT_B = "assignment-cert-b"


def _docker(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", *args],
        check=check,
        capture_output=True,
        text=True,
    )


def _start_postgres(image: str) -> tuple[str, int]:
    last_error = ""
    container = ""
    for _ in range(3):
        container = f"gda-approval-assignment-{secrets.token_hex(5)}"
        started = _docker(
            "run",
            "--rm",
            "--detach",
            "--name",
            container,
            "--publish",
            "127.0.0.1::5432",
            "--env",
            "POSTGRES_HOST_AUTH_METHOD=trust",
            image,
            check=False,
        )
        if started.returncode == 0:
            break
        last_error = started.stderr.strip() or started.stdout.strip()
        time.sleep(0.5)
    else:
        raise RuntimeError(f"could not start disposable PostgreSQL: {last_error}")
    for _ in range(120):
        ready = _docker("exec", container, "pg_isready", "-U", "postgres", check=False)
        if ready.returncode == 0:
            binding = _docker("port", container, "5432/tcp").stdout.strip()
            return container, int(binding.splitlines()[0].rsplit(":", 1)[1])
        time.sleep(0.25)
    raise RuntimeError("disposable PostgreSQL did not become ready")


def _wait_for_connection(engine) -> None:
    last_error = None
    for _ in range(120):
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            return
        except DBAPIError as error:
            last_error = error
            engine.dispose()
            time.sleep(0.25)
    raise RuntimeError("PostgreSQL host port did not become ready") from last_error


def _bootstrap(admin_engine) -> None:
    with admin_engine.begin() as connection:
        for migration in MIGRATIONS:
            connection.execute(text(migration.read_text(encoding="utf-8")))
        connection.exec_driver_sql(
            f"CREATE ROLE {RUNTIME_ROLE} LOGIN NOINHERIT NOSUPERUSER NOBYPASSRLS"
        )
        connection.exec_driver_sql(f"GRANT gda_control_gateway TO {RUNTIME_ROLE}")


def _case(case_id: str, requester: str = "workload:release-controller") -> ApprovalCase:
    now = datetime.now(UTC)
    return ApprovalCase(
        tenant_id=TENANT_A,
        approval_case_ref=f"gda://{TENANT_A}/approval_case/{case_id}",
        target_resource_urn=f"gda://{TENANT_A}/dataset/{case_id}",
        target_fingerprint="b" * 64,
        action="data_product.release",
        requester_subject=requester,
        request_reason="certify governed assignment authority",
        requested_at=now,
        expires_at=now + timedelta(hours=1),
    )


def _route(
    authority: ApprovalCaseAuthority,
    approval_case: ApprovalCase,
    *,
    version: int,
    operation: ApprovalCaseAssignmentOperation,
    actor: str,
    assignee: str | None,
    reason: str,
):
    return authority.transition_assignment(
        tenant_id=TENANT_A,
        approval_case_ref=approval_case.approval_case_ref,
        expected_assignment_version=version,
        operation=operation,
        actor_subject=actor,
        assignee_subject=assignee,
        reason=reason,
    )


def _tenant_assignment_count(runtime_engine, tenant_id: str) -> int:
    with runtime_engine.begin() as connection:
        connection.exec_driver_sql('SET LOCAL ROLE "gda_control_gateway"')
        connection.execute(
            text("SELECT set_config('app.current_tenant', :tenant_id, true)"),
            {"tenant_id": tenant_id},
        )
        return int(
            connection.execute(
                text("SELECT COUNT(*) FROM gda_control.approval_case_assignment")
            ).scalar_one()
        )


def _mutation_denied(engine, statement: str, *, set_gateway: bool = False) -> bool:
    try:
        with engine.begin() as connection:
            if set_gateway:
                connection.exec_driver_sql('SET LOCAL ROLE "gda_control_gateway"')
                connection.execute(
                    text("SELECT set_config('app.current_tenant', :tenant_id, true)"),
                    {"tenant_id": TENANT_A},
                )
            connection.execute(text(statement))
    except DBAPIError:
        return True
    return False


def _privileges(admin_engine) -> dict[str, bool]:
    with admin_engine.connect() as connection:
        values = connection.execute(
            text(
                """
                SELECT
                    has_table_privilege(
                        'gda_control_gateway',
                        'gda_control.approval_case_assignment', 'SELECT'
                    ),
                    has_table_privilege(
                        'gda_control_gateway',
                        'gda_control.approval_case_assignment', 'UPDATE'
                    ),
                    has_table_privilege(
                        'gda_control_gateway',
                        'gda_control.approval_case_assignment_event', 'SELECT'
                    ),
                    has_table_privilege(
                        'gda_control_gateway',
                        'gda_control.approval_case_assignment_event', 'INSERT'
                    ),
                    has_function_privilege(
                        'gda_control_gateway',
                        'gda_control.transition_approval_case_assignment('
                        'text,text,integer,text,text,text,text)', 'EXECUTE'
                    ),
                    has_table_privilege(
                        'gda_control_gateway',
                        'gda_control.approval_principal', 'SELECT'
                    ),
                    has_table_privilege(
                        'gda_control_gateway',
                        'gda_control.approval_principal', 'UPDATE'
                    ),
                    has_function_privilege(
                        'gda_control_gateway',
                        'gda_control.upsert_approval_principal('
                        'text,text,integer,text,text,boolean,text,'
                        'timestamp with time zone,timestamp with time zone,text,text)',
                        'EXECUTE'
                    )
                """
            )
        ).one()
    return {
        "assignment_select": bool(values[0]),
        "assignment_update": bool(values[1]),
        "event_select": bool(values[2]),
        "event_insert": bool(values[3]),
        "transition_execute": bool(values[4]),
        "principal_select": bool(values[5]),
        "principal_update": bool(values[6]),
        "principal_upsert_execute": bool(values[7]),
    }


def _register_principal(
    authority: ApprovalCaseAuthority,
    subject: str,
    *,
    status: str = "active",
    available: str = "available",
):
    now = datetime.now(UTC)
    return authority.upsert_principal(
        tenant_id=TENANT_A,
        principal_subject=subject,
        expected_directory_version=0,
        principal_type=subject.split(":", 1)[0],
        display_name=subject.split(":", 1)[1],
        status=status,
        approval_eligible=True,
        availability_status=available,
        valid_from=now - timedelta(minutes=1),
        valid_until=now + timedelta(hours=2),
        actor_subject="human:platform-admin",
        reason="register certification approval principal",
    )


def _certify(admin_engine, runtime_engine) -> dict[str, object]:
    authority = ApprovalCaseAuthority(runtime_engine)
    human_subjects = {
        "human:data-steward",
        "human:other-operator",
        "human:specialist",
        "human:reviewer",
        "human:initial-reviewer",
        "human:pool-reviewer",
        "human:requester",
        "human:late-reviewer",
        *(f"human:delegate-{depth}" for depth in range(7)),
    }
    registered_humans = {
        subject: _register_principal(authority, subject)
        for subject in sorted(human_subjects)
    }
    team = _register_principal(authority, "team:data-governance")
    empty_team = _register_principal(authority, "team:empty-reviewers")
    unavailable = _register_principal(
        authority,
        "human:unavailable-reviewer",
        available="unavailable",
    )
    now = datetime.now(UTC)
    membership = authority.upsert_team_membership(
        tenant_id=TENANT_A,
        team_subject=team.principal_subject,
        member_subject="human:data-steward",
        expected_membership_version=0,
        status="active",
        can_delegate=True,
        valid_from=now - timedelta(minutes=1),
        valid_until=now + timedelta(hours=2),
        actor_subject="human:platform-admin",
        reason="register certification team delegate",
    )
    routed_case = _case("routed-release")
    authority.create(routed_case, owner_ref="team:data-platform")
    assigned = _route(
        authority,
        routed_case,
        version=0,
        operation=ApprovalCaseAssignmentOperation.ASSIGN,
        actor="human:platform-admin",
        assignee="human:data-steward",
        reason="route to domain steward",
    )

    non_assignee_decision_denied = False
    try:
        authority.decide(
            tenant_id=TENANT_A,
            approval_case_ref=routed_case.approval_case_ref,
            expected_state_version=0,
            verdict="approved",
            actor_subject="human:other-operator",
            reason="must not bypass active assignment",
        )
    except ApprovalCaseForbiddenError:
        non_assignee_decision_denied = True

    non_assignee_delegation_denied = False
    try:
        _route(
            authority,
            routed_case,
            version=1,
            operation=ApprovalCaseAssignmentOperation.DELEGATE,
            actor="human:other-operator",
            assignee="human:specialist",
            reason="must not delegate another operator's assignment",
        )
    except ApprovalCaseForbiddenError:
        non_assignee_delegation_denied = True

    delegated = _route(
        authority,
        routed_case,
        version=1,
        operation=ApprovalCaseAssignmentOperation.DELEGATE,
        actor="human:data-steward",
        assignee="human:specialist",
        reason="delegate to subject specialist",
    )
    stale_assignment_cas = False
    try:
        _route(
            authority,
            routed_case,
            version=1,
            operation=ApprovalCaseAssignmentOperation.REASSIGN,
            actor="human:platform-admin",
            assignee="human:reviewer",
            reason="must fail stale assignment version",
        )
    except ApprovalCaseConflictError:
        stale_assignment_cas = True

    reassigned = _route(
        authority,
        routed_case,
        version=2,
        operation=ApprovalCaseAssignmentOperation.REASSIGN,
        actor="human:platform-admin",
        assignee="human:reviewer",
        reason="balance reviewer workload",
    )
    decided = authority.decide(
        tenant_id=TENANT_A,
        approval_case_ref=routed_case.approval_case_ref,
        expected_state_version=0,
        verdict="approved",
        actor_subject="human:reviewer",
        reason="release evidence is complete",
    )
    closed = authority.assignment(TENANT_A, routed_case.approval_case_ref)
    events = authority.assignment_events(TENANT_A, routed_case.approval_case_ref)

    requester_assignment_denied = False
    requester_case = _case("requester-assignment", requester="human:requester")
    authority.create(requester_case, owner_ref="team:data-platform")
    try:
        _route(
            authority,
            requester_case,
            version=0,
            operation=ApprovalCaseAssignmentOperation.ASSIGN,
            actor="human:platform-admin",
            assignee="human:requester",
            reason="must reject requester as approver",
        )
    except ApprovalCaseValidationError:
        requester_assignment_denied = True

    released_case = _case("released-routing")
    authority.create(released_case, owner_ref="team:data-platform")
    _route(
        authority,
        released_case,
        version=0,
        operation=ApprovalCaseAssignmentOperation.ASSIGN,
        actor="human:platform-admin",
        assignee="human:initial-reviewer",
        reason="initial routing",
    )
    released = _route(
        authority,
        released_case,
        version=1,
        operation=ApprovalCaseAssignmentOperation.RELEASE,
        actor="human:platform-admin",
        assignee=None,
        reason="return to open processing pool",
    )
    authority.decide(
        tenant_id=TENANT_A,
        approval_case_ref=released_case.approval_case_ref,
        expected_state_version=0,
        verdict="rejected",
        actor_subject="human:pool-reviewer",
        reason="open-pool reviewer rejected incomplete evidence",
    )
    released_closed = authority.assignment(TENANT_A, released_case.approval_case_ref)

    depth_case = _case("delegation-depth")
    authority.create(depth_case, owner_ref="team:data-platform")
    current = _route(
        authority,
        depth_case,
        version=0,
        operation=ApprovalCaseAssignmentOperation.ASSIGN,
        actor="human:platform-admin",
        assignee="human:delegate-0",
        reason="start bounded delegation chain",
    )
    for depth in range(1, 6):
        current = _route(
            authority,
            depth_case,
            version=current.assignment_version,
            operation=ApprovalCaseAssignmentOperation.DELEGATE,
            actor=f"human:delegate-{depth - 1}",
            assignee=f"human:delegate-{depth}",
            reason=f"delegate level {depth}",
        )
    delegation_limit_enforced = False
    try:
        _route(
            authority,
            depth_case,
            version=current.assignment_version,
            operation=ApprovalCaseAssignmentOperation.DELEGATE,
            actor="human:delegate-5",
            assignee="human:delegate-6",
            reason="must exceed delegation depth",
        )
    except ApprovalCaseValidationError:
        delegation_limit_enforced = True

    post_terminal_routing_denied = False
    try:
        _route(
            authority,
            routed_case,
            version=closed.assignment_version,
            operation=ApprovalCaseAssignmentOperation.REASSIGN,
            actor="human:platform-admin",
            assignee="human:late-reviewer",
            reason="must reject terminal case routing",
        )
    except ApprovalCaseValidationError:
        post_terminal_routing_denied = True

    team_case = _case("team-routing")
    authority.create(team_case, owner_ref="team:data-platform")
    team_assigned = _route(
        authority,
        team_case,
        version=0,
        operation=ApprovalCaseAssignmentOperation.ASSIGN,
        actor="human:platform-admin",
        assignee="team:data-governance",
        reason="route to governed approval team",
    )
    team_access = authority.assignment_actor_access(
        tenant_id=TENANT_A,
        approval_case_ref=team_case.approval_case_ref,
        actor_subject="human:data-steward",
    )
    non_member_team_decision_denied = False
    try:
        authority.decide(
            tenant_id=TENANT_A,
            approval_case_ref=team_case.approval_case_ref,
            expected_state_version=0,
            verdict="approved",
            actor_subject="human:other-operator",
            reason="must not bypass team membership",
        )
    except ApprovalCaseForbiddenError:
        non_member_team_decision_denied = True
    team_delegated = _route(
        authority,
        team_case,
        version=1,
        operation=ApprovalCaseAssignmentOperation.DELEGATE,
        actor="human:data-steward",
        assignee="human:specialist",
        reason="team delegate routes to specialist",
    )
    team_case_decided = authority.decide(
        tenant_id=TENANT_A,
        approval_case_ref=team_case.approval_case_ref,
        expected_state_version=0,
        verdict="approved",
        actor_subject="human:specialist",
        reason="specialist completed team review",
    )

    ineligible_case = _case("ineligible-routing")
    authority.create(ineligible_case, owner_ref="team:data-platform")
    unavailable_target_denied = False
    try:
        _route(
            authority,
            ineligible_case,
            version=0,
            operation=ApprovalCaseAssignmentOperation.ASSIGN,
            actor="human:platform-admin",
            assignee=unavailable.principal_subject,
            reason="must reject unavailable reviewer",
        )
    except ApprovalCaseValidationError:
        unavailable_target_denied = True
    empty_team_target_denied = False
    try:
        _route(
            authority,
            ineligible_case,
            version=0,
            operation=ApprovalCaseAssignmentOperation.ASSIGN,
            actor="human:platform-admin",
            assignee=empty_team.principal_subject,
            reason="must reject team without eligible member",
        )
    except ApprovalCaseValidationError:
        empty_team_target_denied = True

    data_steward = registered_humans["human:data-steward"]
    authority.upsert_principal(
        tenant_id=TENANT_A,
        principal_subject=data_steward.principal_subject,
        expected_directory_version=data_steward.directory_version,
        principal_type="human",
        display_name=data_steward.display_name,
        status="active",
        approval_eligible=True,
        availability_status="unavailable",
        valid_from=data_steward.valid_from,
        valid_until=data_steward.valid_until,
        actor_subject="human:platform-admin",
        reason="certify immediate availability revocation",
    )
    stale_directory_cas = False
    try:
        authority.upsert_principal(
            tenant_id=TENANT_A,
            principal_subject=data_steward.principal_subject,
            expected_directory_version=data_steward.directory_version,
            principal_type="human",
            display_name=data_steward.display_name,
            status="active",
            approval_eligible=True,
            availability_status="available",
            valid_from=data_steward.valid_from,
            valid_until=data_steward.valid_until,
            actor_subject="human:platform-admin",
            reason="must reject stale directory update",
        )
    except ApprovalCaseConflictError:
        stale_directory_cas = True
    eligible_subjects = {
        principal.principal_subject
        for principal in authority.list_principals(TENANT_A, eligible_only=True)
    }
    unavailable_decision_denied = False
    try:
        authority.decide(
            tenant_id=TENANT_A,
            approval_case_ref=ineligible_case.approval_case_ref,
            expected_state_version=0,
            verdict="cancelled",
            actor_subject="human:data-steward",
            reason="must reject unavailable human decision",
        )
    except ApprovalCaseValidationError:
        unavailable_decision_denied = True
    listed_memberships = authority.list_team_memberships(
        TENANT_A, "team:data-governance"
    )

    privileges = _privileges(admin_engine)
    checks = {
        "initial_assignment_created": assigned.assignment_version == 1,
        "non_assignee_decision_denied": non_assignee_decision_denied,
        "non_assignee_delegation_denied": non_assignee_delegation_denied,
        "delegation_increments_depth": delegated.delegation_depth == 1,
        "stale_assignment_cas": stale_assignment_cas,
        "admin_reassignment_resets_depth": reassigned.delegation_depth == 0,
        "assignee_decision_succeeds": decided.status.value == "approved",
        "terminal_decision_closes_routing": closed is not None
        and closed.status.value == "closed"
        and closed.assignment_version == 4,
        "assignment_event_sequence": [event.action.value for event in events]
        == ["assigned", "delegated", "reassigned", "closed"],
        "requester_assignment_denied": requester_assignment_denied,
        "release_returns_open_pool": released.status.value == "released"
        and released.assignee_subject is None,
        "released_case_closes_after_pool_decision": released_closed is not None
        and released_closed.status.value == "closed",
        "delegation_limit_enforced": delegation_limit_enforced,
        "post_terminal_routing_denied": post_terminal_routing_denied,
        "principal_directory_registered": len(registered_humans) == 15,
        "team_membership_registered": membership.membership_version == 1,
        "team_assignment_supported": team_assigned.assignee_subject
        == "team:data-governance",
        "team_member_access_resolved": team_access.can_decide
        and team_access.can_delegate,
        "non_member_team_decision_denied": non_member_team_decision_denied,
        "team_delegate_can_route": team_delegated.assignee_subject
        == "human:specialist",
        "team_delegated_decision_succeeds": team_case_decided.status.value
        == "approved",
        "unavailable_target_denied": unavailable_target_denied,
        "empty_team_target_denied": empty_team_target_denied,
        "stale_directory_cas": stale_directory_cas,
        "availability_revocation_visible": "human:data-steward"
        not in eligible_subjects,
        "unavailable_human_decision_denied": unavailable_decision_denied,
        "team_membership_version_readable": listed_memberships == (membership,),
        "tenant_a_assignments_visible": _tenant_assignment_count(runtime_engine, TENANT_A)
        == 4,
        "tenant_b_isolated": _tenant_assignment_count(runtime_engine, TENANT_B) == 0,
        "gateway_direct_update_denied": _mutation_denied(
            runtime_engine,
            "UPDATE gda_control.approval_case_assignment "
            "SET last_reason = 'forged'",
            set_gateway=True,
        ),
        "owner_event_mutation_denied": _mutation_denied(
            admin_engine,
            "UPDATE gda_control.approval_case_assignment_event "
            "SET reason = 'forged'",
        ),
        "gateway_principal_update_denied": _mutation_denied(
            runtime_engine,
            "UPDATE gda_control.approval_principal "
            "SET display_name = 'forged'",
            set_gateway=True,
        ),
        "owner_directory_event_mutation_denied": _mutation_denied(
            admin_engine,
            "UPDATE gda_control.approval_principal_event "
            "SET reason = 'forged'",
        ),
        "gateway_least_privilege": privileges
        == {
            "assignment_select": True,
            "assignment_update": False,
            "event_select": True,
            "event_insert": False,
            "transition_execute": True,
            "principal_select": True,
            "principal_update": False,
            "principal_upsert_execute": True,
        },
    }
    return {
        "schema": "gda.approval_case_assignment_certification.v2",
        "status": "verified" if all(checks.values()) else "failed",
        "checks": checks,
        "privileges": privileges,
        "assignment_event_count": len(events),
        "eligible_principal_count": len(eligible_subjects),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default="postgres:16")
    args = parser.parse_args()
    container = None
    admin_engine = None
    runtime_engine = None
    try:
        container, port = _start_postgres(args.image)
        admin_engine = create_engine(
            f"postgresql+psycopg2://postgres@127.0.0.1:{port}/postgres"
        )
        _wait_for_connection(admin_engine)
        _bootstrap(admin_engine)
        runtime_engine = create_engine(
            f"postgresql+psycopg2://{RUNTIME_ROLE}@127.0.0.1:{port}/postgres"
        )
        _wait_for_connection(runtime_engine)
        report = _certify(admin_engine, runtime_engine)
        print(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True))
        return 0 if report["status"] == "verified" else 1
    finally:
        if runtime_engine is not None:
            runtime_engine.dispose()
        if admin_engine is not None:
            admin_engine.dispose()
        if container is not None:
            _docker("rm", "--force", container, check=False)


if __name__ == "__main__":
    raise SystemExit(main())
