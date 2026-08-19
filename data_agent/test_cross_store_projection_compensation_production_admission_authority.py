from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, text

from data_agent.cross_store_projection_compensation_production_admission import (
    ChongqingFiveProviderProductionAdmissionHistory,
    build_chongqing_five_provider_production_admission_target,
    build_initial_chongqing_five_provider_production_admission_history,
    revoke_chongqing_five_provider_production_admission,
    rollback_chongqing_five_provider_production_admission,
)
from data_agent.cross_store_projection_compensation_production_admission_authority import (
    CHONGQING_FIVE_PROVIDER_PRODUCTION_ADMISSION_AUTHORITY_MIGRATION,
    ChongqingFiveProviderProductionAdmissionAuthorityConfigurationError,
    ChongqingFiveProviderProductionAdmissionAuthorityForbiddenError,
    ChongqingFiveProviderProductionAdmissionAuthorityValidationError,
    PostgresChongqingFiveProviderProductionAdmissionAuthorityStore,
)
from data_agent.cross_store_projection_postgres_rehearsal import _temporary_postgres
from data_agent.test_cross_store_projection_compensation_chongqing_five_provider_execution import (
    _five_provider_inputs,
    _rule_current_preflight,
)

_AUTHORIZED_AT = datetime(2026, 8, 18, 12, tzinfo=UTC)
_EXPIRES_AT = _AUTHORIZED_AT + timedelta(hours=2)


def _target(monkeypatch: pytest.MonkeyPatch, *, request_bundle_sha256: str | None = None):
    inputs = _five_provider_inputs(monkeypatch)
    _, rule_binding, _ = _rule_current_preflight(inputs[0])
    target = build_chongqing_five_provider_production_admission_target(
        inputs[0],
        inputs[1],
        inputs[2],
        inputs[4],
        inputs[9],
        rule_binding,
        request_bundle_sha256=request_bundle_sha256
        or inputs[11].request_bundle_sha256,
    )
    return target, inputs, rule_binding


def _initial(monkeypatch: pytest.MonkeyPatch):
    target, inputs, rule_binding = _target(monkeypatch)
    history = build_initial_chongqing_five_provider_production_admission_history(
        target,
        authorized_by="human:customer-production-controller",
        authorization_evidence_sha256="a" * 64,
        trust_anchor_sha256="b" * 64,
        authorization_reason="explicit bounded production admission",
        authorized_at=_AUTHORIZED_AT,
        expires_at=_EXPIRES_AT,
    )
    return history, target, inputs, rule_binding


def test_explicit_admission_is_separate_from_unreviewed_technical_bindings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    history, target, inputs, rule_binding = _initial(monkeypatch)
    current = history.current_event

    assert inputs[9].production_execution_authorized is False
    assert rule_binding.production_execution_authorized is False
    assert current.target == target
    assert current.technical_baseline_grants_production_authority is False
    assert current.production_execution_authorized is True
    assert history.authorizes(target, evaluated_at=_AUTHORIZED_AT + timedelta(minutes=1))
    assert not history.authorizes(target, evaluated_at=_EXPIRES_AT)

    tampered_target = target.model_copy(update={"target_sha256": "f" * 64})
    with pytest.raises(ValueError, match="target fingerprint"):
        build_initial_chongqing_five_provider_production_admission_history(
            tampered_target,
            authorized_by="human:customer-production-controller",
            authorization_evidence_sha256="a" * 64,
            trust_anchor_sha256="b" * 64,
            authorization_reason="tampered target must not be admitted",
            authorized_at=_AUTHORIZED_AT,
            expires_at=_EXPIRES_AT,
        )


@pytest.mark.parametrize(
    ("authorized_by", "expires_at", "error"),
    (
        ("agent:auto-promoter", _EXPIRES_AT, "human identity"),
        (
            "human:customer-production-controller",
            _AUTHORIZED_AT,
            "expiry must follow",
        ),
    ),
)
def test_technical_or_unbounded_input_cannot_create_production_admission(
    monkeypatch: pytest.MonkeyPatch,
    authorized_by: str,
    expires_at: datetime,
    error: str,
) -> None:
    target, *_ = _target(monkeypatch)

    with pytest.raises(ValueError, match=error):
        build_initial_chongqing_five_provider_production_admission_history(
            target,
            authorized_by=authorized_by,
            authorization_evidence_sha256="a" * 64,
            trust_anchor_sha256="b" * 64,
            authorization_reason="must be independently authorized",
            authorized_at=_AUTHORIZED_AT,
            expires_at=expires_at,
        )


def test_revocation_and_rollback_are_new_append_only_authority_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    initial, target, *_ = _initial(monkeypatch)
    revoked = revoke_chongqing_five_provider_production_admission(
        initial,
        authorized_by="human:customer-production-controller",
        authorization_evidence_sha256="c" * 64,
        trust_anchor_sha256="b" * 64,
        authorization_reason="incident containment",
        authorized_at=_AUTHORIZED_AT + timedelta(minutes=10),
    )
    rolled_back = rollback_chongqing_five_provider_production_admission(
        revoked,
        initial.current_event.event_sha256,
        authorized_by="human:customer-production-controller",
        authorization_evidence_sha256="d" * 64,
        trust_anchor_sha256="b" * 64,
        authorization_reason="explicitly restore the prior bounded grant",
        authorized_at=_AUTHORIZED_AT + timedelta(minutes=20),
        expires_at=_EXPIRES_AT + timedelta(hours=1),
    )

    assert tuple(event.event_kind for event in rolled_back.events) == (
        "promotion",
        "revocation",
        "rollback",
    )
    assert rolled_back.events[:2] == revoked.events
    assert rolled_back.current_event.rollback_target_event_sha256 == (
        initial.current_event.event_sha256
    )
    assert rolled_back.authorizes(
        target,
        evaluated_at=_AUTHORIZED_AT + timedelta(minutes=21),
    )

    tampered = rolled_back.model_dump(mode="python")
    tampered["events"][0]["authorization_reason"] = "rewritten authority"
    with pytest.raises(ValidationError):
        ChongqingFiveProviderProductionAdmissionHistory.model_validate(tampered)


def test_migration_exposes_only_governed_append_only_admission_storage() -> None:
    migration = CHONGQING_FIVE_PROVIDER_PRODUCTION_ADMISSION_AUTHORITY_MIGRATION.read_text(
        encoding="utf-8"
    )

    assert "chongqing_five_provider_production_admission_history" in migration
    assert "chongqing_five_provider_production_admission_history_current" in migration
    assert "SECURITY DEFINER" in migration
    assert "SET row_security = on" in migration
    assert "ENABLE ROW LEVEL SECURITY" in migration
    assert "FORCE ROW LEVEL SECURITY" in migration
    assert "BEFORE UPDATE OR DELETE" in migration
    assert "technical_baseline_grants_production_authority" in migration
    assert "GRANT INSERT" not in migration


def test_repository_requires_postgresql() -> None:
    store = PostgresChongqingFiveProviderProductionAdmissionAuthorityStore(
        "cq-federated-recovery",
        create_engine("sqlite://"),
    )

    with pytest.raises(
        ChongqingFiveProviderProductionAdmissionAuthorityConfigurationError,
        match="requires PostgreSQL",
    ):
        store.admission_history_current("run-1")


def test_repository_rejects_cross_tenant_history_before_database_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    history, *_ = _initial(monkeypatch)
    store = PostgresChongqingFiveProviderProductionAdmissionAuthorityStore(
        "another-tenant",
        create_engine("sqlite://"),
    )

    with pytest.raises(
        ChongqingFiveProviderProductionAdmissionAuthorityForbiddenError,
        match="tenant differs",
    ):
        store.record(history)


@pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL is not configured",
)
def test_real_postgres_admission_authority_is_append_only_and_tenant_scoped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    initial, *_ = _initial(monkeypatch)
    revoked = revoke_chongqing_five_provider_production_admission(
        initial,
        authorized_by="human:customer-production-controller",
        authorization_evidence_sha256="c" * 64,
        trust_anchor_sha256="b" * 64,
        authorization_reason="incident containment",
        authorized_at=_AUTHORIZED_AT + timedelta(minutes=10),
    )
    competing_revocation = revoke_chongqing_five_provider_production_admission(
        initial,
        authorized_by="human:customer-production-controller",
        authorization_evidence_sha256="e" * 64,
        trust_anchor_sha256="b" * 64,
        authorization_reason="competing stale revocation",
        authorized_at=_AUTHORIZED_AT + timedelta(minutes=11),
    )
    rolled_back = rollback_chongqing_five_provider_production_admission(
        revoked,
        initial.current_event.event_sha256,
        authorized_by="human:customer-production-controller",
        authorization_evidence_sha256="d" * 64,
        trust_anchor_sha256="b" * 64,
        authorization_reason="restore prior bounded admission",
        authorized_at=_AUTHORIZED_AT + timedelta(minutes=20),
        expires_at=_EXPIRES_AT + timedelta(hours=1),
    )

    with _temporary_postgres(os.environ["DATABASE_URL"]) as sandbox:
        assert sandbox.runtime_engine is not None
        with sandbox.admin_connection() as connection:
            connection.exec_driver_sql(
                CHONGQING_FIVE_PROVIDER_PRODUCTION_ADMISSION_AUTHORITY_MIGRATION.read_text(
                    encoding="utf-8"
                ).replace("%", "%%")
            )

        store = PostgresChongqingFiveProviderProductionAdmissionAuthorityStore(
            initial.tenant_id,
            sandbox.runtime_engine,
        )
        assert store.record(initial) == initial
        assert store.record(initial) == initial
        assert store.record(revoked) == revoked
        assert store.record(rolled_back) == rolled_back
        assert store.admission_history_current(initial.run_id) == rolled_back
        assert store.history_snapshots(initial.run_id) == (
            initial,
            revoked,
            rolled_back,
        )

        with pytest.raises(
            ChongqingFiveProviderProductionAdmissionAuthorityValidationError,
            match="version is not contiguous",
        ):
            store.record(competing_revocation)

        other_tenant = PostgresChongqingFiveProviderProductionAdmissionAuthorityStore(
            "another-tenant",
            sandbox.runtime_engine,
        )
        assert other_tenant.admission_history_current(initial.run_id) is None

        with pytest.raises(
            ChongqingFiveProviderProductionAdmissionAuthorityForbiddenError,
            match="tenant or role was denied",
        ):
            with store._transaction() as connection:
                connection.execute(
                    text(
                        """
                        INSERT INTO gda_control.
                            chongqing_five_provider_production_admission_history (
                            tenant_id, run_id, current_event_version,
                            current_event_sha256, history_sha256, history_document
                        ) VALUES (
                            :tenant_id, :run_id, 9, :event_sha256,
                            :history_sha256, CAST(:history_document AS jsonb)
                        )
                        """
                    ),
                    {
                        "tenant_id": initial.tenant_id,
                        "run_id": initial.run_id,
                        "event_sha256": "f" * 64,
                        "history_sha256": "e" * 64,
                        "history_document": json.dumps(initial.model_dump(mode="json")),
                    },
                )
