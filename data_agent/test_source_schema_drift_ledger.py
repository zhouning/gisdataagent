"""Contract tests for the source schema drift control ledger."""

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from data_agent.source_connector_governance import SchemaDriftEvent, SchemaFieldChange
from data_agent.source_schema_drift_ledger import (
    PersistedSchemaDrift,
    SchemaDriftLifecycleEntry,
    SchemaDriftStatus,
)

SHA_A = "a" * 64
SHA_B = "b" * 64
EVENT_ID = "c" * 64
NOW = datetime(2026, 8, 1, 12, tzinfo=UTC)


def _event(*, breaking: bool = True) -> SchemaDriftEvent:
    return SchemaDriftEvent(
        source_id="postgresql-rotation-certification",
        previous_discovery_fingerprint=SHA_A,
        current_discovery_fingerprint=SHA_B,
        changed_resources=("public.source_asset",),
        field_changes=(
            SchemaFieldChange(
                resource_name="public.source_asset",
                field_name="id",
                change_kind="type_changed" if breaking else "nullable_relaxed",
                previous_type="INTEGER",
                current_type="BIGINT" if breaking else "INTEGER",
                previous_nullable=False,
                current_nullable=False if breaking else True,
                breaking=breaking,
            ),
        ),
        breaking=breaking,
    )


def test_persisted_schema_drift_contract_is_frozen_and_timezone_aware() -> None:
    event = _event()
    drift = PersistedSchemaDrift(
        tenant_id="local-dev",
        drift_event_id=event.event_id,
        source_id=event.source_id,
        source_definition_fingerprint=EVENT_ID,
        previous_discovery_fingerprint=SHA_A,
        current_discovery_fingerprint=SHA_B,
        breaking=True,
        event_payload=event,
        detected_by="workload:connector-certification",
        status=SchemaDriftStatus.APPROVAL_REQUIRED,
        state_version=0,
        detected_at=NOW,
        updated_at=NOW,
    )
    assert drift.event_payload.event_id == event.event_id
    with pytest.raises(ValidationError, match="frozen"):
        drift.status = SchemaDriftStatus.APPROVED  # type: ignore[misc]
    with pytest.raises(ValidationError, match="timezone"):
        PersistedSchemaDrift.model_validate(
            {**drift.model_dump(), "detected_at": NOW.replace(tzinfo=None)}
        )
    with pytest.raises(ValidationError, match="binding"):
        PersistedSchemaDrift.model_validate(
            {**drift.model_dump(), "current_discovery_fingerprint": "d" * 64}
        )


def test_lifecycle_contract_requires_known_status_and_structured_details() -> None:
    entry = SchemaDriftLifecycleEntry(
        tenant_id="local-dev",
        lifecycle_event_id=UUID("00000000-0000-4000-8000-000000000001"),
        drift_event_id=EVENT_ID,
        sequence_no=1,
        from_status=SchemaDriftStatus.APPROVAL_REQUIRED,
        to_status=SchemaDriftStatus.APPROVED,
        actor_subject="human:data-steward",
        reason="approved compatible migration",
        approval_case_ref="gda://local-dev/approval_case/drift-1",
        details={"ticket": "DRIFT-1"},
        occurred_at=NOW,
    )
    assert entry.to_status is SchemaDriftStatus.APPROVED
    with pytest.raises(ValidationError):
        SchemaDriftLifecycleEntry.model_validate(
            {**entry.model_dump(), "to_status": "silently_accepted"}
        )


def test_migration_enforces_rls_append_only_cas_and_external_approval() -> None:
    sql = (Path(__file__).parent / "migrations/102_source_schema_drift_ledger.sql").read_text(
        encoding="utf-8"
    )
    for marker in (
        "CREATE TABLE IF NOT EXISTS gda_control.source_schema_drift",
        "source_schema_drift_lifecycle_event",
        "FORCE ROW LEVEL SECURITY",
        "transition_source_schema_drift",
        "p_expected_state_version INTEGER",
        "approval_case_ref",
        "use gda_control.transition_source_schema_drift()",
        "reject_immutable_mutation",
        "GRANT SELECT, INSERT ON gda_control.source_schema_drift",
    ):
        assert marker in sql
    assert "CREATE TABLE" in sql
    assert "approval_case (" not in sql.lower()
