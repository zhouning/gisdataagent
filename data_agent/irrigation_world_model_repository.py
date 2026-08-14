"""Durable PostgreSQL storage for irrigation world-model evidence.

The repository owns persistence only.  Numerical scenario calculation remains
in ``irrigation_world_model_demo`` and is explicitly labelled as a synthetic
scenario kernel until a customer calibration package is supplied.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError, SQLAlchemyError

from .db_engine import get_engine

TENANT_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
RUN_RE = re.compile(r"^irr-run-([0-9a-f-]{36})$")
PROPOSAL_RE = re.compile(r"^irr-proposal-([0-9a-f-]{36})$")


class IrrigationPersistenceError(RuntimeError):
    """Database is unavailable or cannot enforce the storage contract."""


class IrrigationPersistenceNotFound(IrrigationPersistenceError):
    """A run or Proposal is absent or hidden by tenant/user isolation."""


class IrrigationPersistenceConflict(IrrigationPersistenceError):
    """An immutable identity or one-time review transition conflicted."""


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _json_value(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def _timestamp_value(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _sha256(value: Any) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _tenant(tenant_id: str) -> str:
    normalized = str(tenant_id or "").strip().casefold()
    if not TENANT_RE.fullmatch(normalized):
        raise IrrigationPersistenceError("authenticated identity has no valid tenant binding")
    return normalized


def _subject(username: str) -> str:
    value = str(username or "").strip()
    if not value or any(char.isspace() for char in value):
        raise IrrigationPersistenceError("authenticated identity is invalid")
    return f"human:{value}"


def _external_uuid(value: str, pattern: re.Pattern[str], label: str) -> str:
    match = pattern.fullmatch(value or "")
    if not match:
        raise IrrigationPersistenceError(f"invalid irrigation {label} id")
    return match.group(1)


class PostgresIrrigationWorldModelRepository:
    """Tenant-scoped repository backed by the platform control database."""

    def __init__(self, engine=None):
        self._engine = engine

    def _get_engine(self):
        engine = self._engine or get_engine()
        if engine is None or engine.dialect.name != "postgresql":
            raise IrrigationPersistenceError(
                "irrigation world-model requires a configured PostgreSQL database"
            )
        return engine

    @contextmanager
    def _transaction(self, tenant_id: str) -> Iterator[Any]:
        tenant = _tenant(tenant_id)
        try:
            with self._get_engine().connect() as connection:
                with connection.begin():
                    # The application login is only a member of this NOLOGIN
                    # gateway role.  RLS remains enabled and tenant-bound.
                    connection.exec_driver_sql('SET LOCAL ROLE "gda_control_gateway"')
                    connection.execute(
                        text("SELECT set_config('app.current_tenant', :tenant, true)"),
                        {"tenant": tenant},
                    )
                    yield connection
        except (
            IrrigationPersistenceError,
            IrrigationPersistenceNotFound,
            IrrigationPersistenceConflict,
        ):
            raise
        except DBAPIError as exc:
            state = getattr(getattr(exc, "orig", None), "sqlstate", None) or getattr(
                getattr(exc, "orig", None), "pgcode", None
            )
            if state in {"40001", "23505"}:
                raise IrrigationPersistenceConflict(
                    "irrigation evidence identity conflicted"
                ) from exc
            if state in {"42501", "55000", "23514", "22023"}:
                raise IrrigationPersistenceError(
                    "irrigation evidence contract was rejected"
                ) from exc
            raise IrrigationPersistenceError("irrigation database operation failed") from exc
        except SQLAlchemyError as exc:
            raise IrrigationPersistenceError("irrigation database operation failed") from exc

    @staticmethod
    def _run_fingerprint(run: dict[str, Any]) -> str:
        document = copy.deepcopy(run)
        document.pop("audit_events", None)
        document.pop("created_at", None)
        document.pop("version", None)
        return _sha256(document)

    @staticmethod
    def _resource(
        connection,
        *,
        tenant: str,
        urn: str,
        kind: str,
        owner_ref: str,
        governance: dict[str, Any],
    ):
        connection.execute(
            text(
                """
                INSERT INTO gda_control.resource (
                    tenant_id, resource_urn, resource_kind, authority_system,
                    authority_locator, owner_ref, governance_ref, technical_refs
                ) VALUES (
                    :tenant, :urn, :kind, 'gda_control', :urn, :owner,
                    CAST(:governance AS jsonb), '[]'::jsonb
                )
                ON CONFLICT DO NOTHING
                """
            ),
            {
                "tenant": tenant,
                "urn": urn,
                "kind": kind,
                "owner": owner_ref,
                "governance": _json(governance),
            },
        )

    @staticmethod
    def _audit_insert(
        connection,
        *,
        tenant: str,
        run_id: str,
        events: list[dict[str, Any]],
        actor_subject: str,
    ):
        for sequence_no, event in enumerate(events):
            connection.execute(
                text(
                    """
                    INSERT INTO gda_control.irrigation_world_model_audit_event (
                        tenant_id, run_id, sequence_no, step, event_status,
                        detail, evidence, actor_subject, occurred_at
                    ) VALUES (
                        :tenant, CAST(:run_id AS uuid), :sequence_no, :step,
                        :event_status, :detail, CAST(:evidence AS jsonb),
                        :actor_subject, CAST(:occurred_at AS timestamptz)
                    ) ON CONFLICT (tenant_id, run_id, sequence_no) DO NOTHING
                    """
                ),
                {
                    "tenant": tenant,
                    "run_id": run_id,
                    "sequence_no": sequence_no,
                    "step": event["step"],
                    "event_status": event["status"],
                    "detail": event["detail"],
                    "evidence": _json({"schema": "gda.irrigation.audit-event.v1"}),
                    "actor_subject": actor_subject,
                    "occurred_at": _timestamp_value(event["timestamp"]),
                },
            )

    def next_version(self, _actor: str, _tenant_id: str = "local-dev") -> int:
        with self._transaction(_tenant_id) as connection:
            return int(
                connection.execute(
                    text("SELECT nextval('gda_control.irrigation_world_model_run_version_seq')")
                ).scalar_one()
            )

    def save(self, run: dict[str, Any], tenant_id: str) -> dict[str, Any]:
        tenant = _tenant(tenant_id)
        actor = str(run["actor"])
        owner = _subject(actor)
        run_uuid = _external_uuid(run["run_id"], RUN_RE, "run")
        proposal_external_id = run["proposal"]["proposal_id"]
        _external_uuid(proposal_external_id, PROPOSAL_RE, "Proposal")
        run_urn = f"gda://{tenant}/irrigation_run/{run_uuid}"
        approval_ref = f"gda://{tenant}/approval_case/{proposal_external_id}"
        fingerprint = self._run_fingerprint(run)
        created_at = _timestamp_value(run["created_at"])

        try:
            with self._transaction(tenant) as connection:
                self._resource(
                    connection,
                    tenant=tenant,
                    urn=run_urn,
                    kind="irrigation_run",
                    owner_ref=owner,
                    governance={"domain": "irrigation", "fingerprint": fingerprint},
                )
                connection.execute(
                    text(
                        """
                        INSERT INTO gda_control.irrigation_world_model_run (
                            tenant_id, run_id, run_external_id, run_resource_urn,
                            proposal_external_id, approval_case_ref, owner_subject,
                            run_version, parameters, ontology_snapshot, state_snapshot,
                            model_contract, planner_contract, pipeline, results, proposal,
                            claim_boundary,
                            run_fingerprint, status, created_at, updated_at
                        ) VALUES (
                            :tenant, CAST(:run_id AS uuid), :run_external_id, :run_resource,
                            :proposal_external_id, :approval_case_ref, :owner_subject,
                            :run_version, CAST(:parameters AS jsonb), CAST(:ontology AS jsonb),
                            CAST(:state_snapshot AS jsonb), CAST(:model AS jsonb),
                            CAST(:planner AS jsonb), CAST(:pipeline AS jsonb), CAST(:results AS jsonb),
                            CAST(:proposal AS jsonb), CAST(:claim AS jsonb), :fingerprint,
                            'awaiting_review', :created_at, :created_at
                        ) ON CONFLICT (tenant_id, run_external_id) DO NOTHING
                        """
                    ),
                    {
                        "tenant": tenant,
                        "run_id": run_uuid,
                        "run_external_id": run["run_id"],
                        "run_resource": run_urn,
                        "proposal_external_id": run["proposal"]["proposal_id"],
                        "approval_case_ref": approval_ref,
                        "owner_subject": owner,
                        "run_version": int(run["version"]),
                        "parameters": _json(run["parameters"]),
                        "ontology": _json(run["ontology_profile"]),
                        "state_snapshot": _json(run["state_snapshot"]),
                        "model": _json(run["model"]),
                        "planner": _json(run["planner"]),
                        "pipeline": _json(run["pipeline"]),
                        "results": _json(run["results"]),
                        "proposal": _json(run["proposal"]),
                        "claim": _json(run["claim_boundary"]),
                        "fingerprint": fingerprint,
                        "created_at": created_at,
                    },
                )
                self._resource(
                    connection,
                    tenant=tenant,
                    urn=approval_ref,
                    kind="approval_case",
                    owner_ref="agent:irrigation-world-model",
                    governance={
                        "run_resource_urn": run_urn,
                        "action": "irrigation.proposal.review",
                    },
                )
                connection.execute(
                    text(
                        """
                        INSERT INTO gda_control.approval_case (
                            tenant_id, approval_case_ref, target_resource_urn,
                            target_fingerprint, action, requester_subject,
                            request_reason, request_context, status, state_version,
                            requested_at, expires_at, updated_at
                        ) VALUES (
                            :tenant, :approval_case_ref, :target_resource_urn,
                            :target_fingerprint, 'irrigation.proposal.review',
                            'agent:irrigation-world-model', :request_reason,
                            CAST(:request_context AS jsonb), 'pending', 0,
                            :requested_at, :expires_at, :requested_at
                        ) ON CONFLICT DO NOTHING
                        """
                    ),
                    {
                        "tenant": tenant,
                        "approval_case_ref": approval_ref,
                        "target_resource_urn": run_urn,
                        "target_fingerprint": fingerprint,
                        "request_reason": "Review the candidate irrigation allocation Proposal",
                        "request_context": _json(
                            {
                                "schema": "gda.irrigation-proposal-review-context.v1",
                                "run_external_id": run["run_id"],
                                "proposal_external_id": run["proposal"]["proposal_id"],
                                "execution_allowed": False,
                            }
                        ),
                        "requested_at": created_at,
                        "expires_at": created_at + timedelta(days=7),
                    },
                )
                self._audit_insert(
                    connection,
                    tenant=tenant,
                    run_id=run_uuid,
                    events=run["audit_events"],
                    actor_subject=owner,
                )
                return self._load(connection, tenant, run["run_id"], owner)
        except IntegrityError as exc:
            raise IrrigationPersistenceConflict(
                "irrigation run identity already has different evidence"
            ) from exc

    def latest(self, actor: str, tenant_id: str = "local-dev") -> dict[str, Any] | None:
        with self._transaction(tenant_id) as connection:
            row = connection.execute(
                text(
                    """
                    SELECT run_external_id
                    FROM gda_control.irrigation_world_model_run
                    WHERE tenant_id = :tenant AND owner_subject = :owner
                    ORDER BY created_at DESC, run_version DESC
                    LIMIT 1
                    """
                ),
                {"tenant": _tenant(tenant_id), "owner": _subject(actor)},
            ).scalar_one_or_none()
            if row is None:
                return None
            return self._load(connection, _tenant(tenant_id), row, _subject(actor))

    def get(self, run_id: str, actor: str, tenant_id: str = "local-dev") -> dict[str, Any]:
        with self._transaction(tenant_id) as connection:
            return self._load(connection, _tenant(tenant_id), run_id, _subject(actor))

    def update_proposal(
        self,
        proposal_id: str,
        actor: str,
        decision: str,
        note: str,
        tenant_id: str = "local-dev",
    ) -> dict[str, Any]:
        tenant = _tenant(tenant_id)
        owner = _subject(actor)
        verdict = "approved" if decision == "approved" else "rejected"
        with self._transaction(tenant) as connection:
            _external_uuid(proposal_id, PROPOSAL_RE, "Proposal")
            row = connection.execute(
                text(
                    """
                    SELECT run_external_id, run_id, approval_case_ref
                    FROM gda_control.irrigation_world_model_run
                    WHERE tenant_id = :tenant
                      AND proposal_external_id = :proposal
                      AND owner_subject = :owner
                    """
                ),
                {"tenant": tenant, "proposal": proposal_id, "owner": owner},
            ).mappings().one_or_none()
            if row is None:
                raise IrrigationPersistenceNotFound("irrigation Proposal not found")
            case = connection.execute(
                text(
                    """
                    SELECT status, state_version
                    FROM gda_control.approval_case
                    WHERE tenant_id = :tenant AND approval_case_ref = :ref
                    """
                ),
                {"tenant": tenant, "ref": row["approval_case_ref"]},
            ).mappings().one_or_none()
            if case is None:
                raise IrrigationPersistenceNotFound("irrigation ApprovalCase not found")
            if case["status"] != "pending":
                raise IrrigationPersistenceConflict(
                    "Proposal has already been reviewed; run a new scenario to create a new version"
                )
            connection.execute(
                text(
                    """
                    SELECT gda_control.transition_approval_case(
                        :tenant, :ref, :expected_version, :verdict,
                        :actor_subject, :reason, CAST(:details AS jsonb)
                    )
                    """
                ),
                {
                    "tenant": tenant,
                    "ref": row["approval_case_ref"],
                    "expected_version": int(case["state_version"]),
                    "verdict": verdict,
                    "actor_subject": owner,
                    "reason": note,
                    "details": _json({"execution_allowed": False, "proposal_id": proposal_id}),
                },
            )
            max_sequence = connection.execute(
                text(
                    """
                    SELECT COALESCE(MAX(sequence_no), -1)
                    FROM gda_control.irrigation_world_model_audit_event
                    WHERE tenant_id = :tenant AND run_id = :run_id
                    """
                ),
                {"tenant": tenant, "run_id": row["run_id"]},
            ).scalar_one()
            connection.execute(
                text(
                    """
                    INSERT INTO gda_control.irrigation_world_model_audit_event (
                        tenant_id, run_id, sequence_no, step, event_status,
                        detail, evidence, actor_subject, occurred_at
                    ) VALUES (
                        :tenant, :run_id, :sequence_no, '人工审查', :event_status,
                        :detail, CAST(:evidence AS jsonb), :actor_subject, clock_timestamp()
                    )
                    """
                ),
                {
                    "tenant": tenant,
                    "run_id": row["run_id"],
                    "sequence_no": int(max_sequence) + 1,
                    "event_status": "通过" if decision == "approved" else "记录",
                    "detail": "已通过审查（不执行）" if decision == "approved" else "已退回修改",
                    "evidence": _json({"proposal_id": proposal_id, "review_note": note}),
                    "actor_subject": owner,
                },
            )
            return self._load(connection, tenant, row["run_external_id"], owner)

    @staticmethod
    def _load(connection, tenant: str, run_external_id: str, owner: str) -> dict[str, Any]:
        row = connection.execute(
            text(
                """
                SELECT run_id, run_external_id, run_version, owner_subject,
                       parameters, ontology_snapshot, state_snapshot, model_contract,
                       planner_contract, pipeline, results, proposal, claim_boundary,
                       status, created_at, approval_case_ref
                FROM gda_control.irrigation_world_model_run
                WHERE tenant_id = :tenant
                  AND run_external_id = :run_external_id
                  AND owner_subject = :owner
                """
            ),
            {"tenant": tenant, "run_external_id": run_external_id, "owner": owner},
        ).mappings().one_or_none()
        if row is None:
            raise IrrigationPersistenceNotFound("irrigation scenario run not found")
        case = connection.execute(
            text(
                """
                SELECT status, decided_by, decision_reason, decided_at
                FROM gda_control.approval_case
                WHERE tenant_id = :tenant AND approval_case_ref = :approval_case_ref
                """
            ),
            {"tenant": tenant, "approval_case_ref": row["approval_case_ref"]},
        ).mappings().one_or_none()
        audit_rows = connection.execute(
            text(
                """
                SELECT step, event_status, detail, occurred_at
                FROM gda_control.irrigation_world_model_audit_event
                WHERE tenant_id = :tenant AND run_id = :run_id
                ORDER BY sequence_no
                """
            ),
            {"tenant": tenant, "run_id": row["run_id"]},
        ).mappings().all()
        proposal = copy.deepcopy(_json_value(row["proposal"]))
        if case is not None:
            proposal["status"] = (
                "approved" if case["status"] == "approved" else
                "returned" if case["status"] in {"rejected", "cancelled"} else "pending"
            )
            proposal["reviewed_by"] = (
                str(case["decided_by"] or "").removeprefix("human:") or None
            )
            proposal["review_note"] = case["decision_reason"] or proposal.get("review_note")
            proposal["reviewed_at"] = (
                case["decided_at"].isoformat().replace("+00:00", "Z")
                if case["decided_at"] else None
            )
            proposal["execution_allowed"] = False
        audit_events = []
        for item in audit_rows:
            occurred = item["occurred_at"].astimezone(UTC).isoformat().replace("+00:00", "Z")
            audit_events.append(
                {
                    "timestamp": occurred,
                    "time": item["occurred_at"].astimezone().strftime("%H:%M:%S"),
                    "step": item["step"],
                    "status": item["event_status"],
                    "detail": item["detail"],
                }
            )
        status = "reviewed" if case is not None and case["status"] != "pending" else row["status"]
        return {
            "schema": "gda.irrigation-world-model.run.v1",
            "run_id": row["run_external_id"],
            "version": int(row["run_version"]),
            "actor": owner.removeprefix("human:"),
            "created_at": row["created_at"].astimezone(UTC).isoformat().replace("+00:00", "Z"),
            "status": status,
            "parameters": copy.deepcopy(_json_value(row["parameters"])),
            "ontology_profile": copy.deepcopy(_json_value(row["ontology_snapshot"])),
            "state_snapshot": copy.deepcopy(_json_value(row["state_snapshot"])),
            "model": copy.deepcopy(_json_value(row["model_contract"])),
            "planner": copy.deepcopy(_json_value(row["planner_contract"])),
            "pipeline": copy.deepcopy(_json_value(row["pipeline"])),
            "results": copy.deepcopy(_json_value(row["results"])),
            "proposal": proposal,
            "audit_events": audit_events,
            "claim_boundary": copy.deepcopy(_json_value(row["claim_boundary"])),
        }
