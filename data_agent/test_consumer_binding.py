"""Contract and static-boundary tests for formal DataProduct consumers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from data_agent.consumer_binding import (
    ConsumerBinding,
    ConsumerBindingMigrationNotification,
    ConsumerBindingMigrationState,
    build_consumer_binding_notification_terminal_state,
    consumer_binding_fingerprint,
    consumer_binding_migration_state_fingerprint,
)
from data_agent.data_product_registry import DataProductRegistry, _build_promotion_impact


def _binding_payload() -> dict:
    payload = {
        "tenant_id": "planning",
        "binding_id": uuid4(),
        "product_urn": "gda://planning/data_product/districts",
        "consumer_ref": "workload:planner-api",
        "purpose": "serve district search",
        "scope": {"operations": ["read"], "spatial_extent": "chongqing"},
        "min_product_version": "v1.0.0",
        "max_product_version": "v2.0.0",
        "credential_ref": "credential:planner-api",
        "quota": {"max_packages": 5, "max_bytes": 500000000},
        "expires_at": datetime(2026, 9, 1, tzinfo=UTC),
        "compatibility_fingerprint": "a" * 64,
        "compatibility_evidence": {"schema": "districts.v1", "required": ["geom"]},
        "created_by": "human:data-steward",
        "created_at": datetime(2026, 8, 1, tzinfo=UTC),
    }
    payload["binding_sha256"] = consumer_binding_fingerprint(payload)
    return payload


def _migration_state_payload(
    *,
    binding_id=None,
    from_version_id=None,
    to_version_id=None,
    state_version: int = 1,
    previous_state_sha256: str | None = None,
    notification_status: str = "pending",
    notification_evidence: dict | None = None,
    consumer_acknowledgement: dict | None = None,
) -> dict:
    recorded_at = datetime(2026, 8, 7, 12, tzinfo=UTC)
    payload = {
        "tenant_id": "planning",
        "migration_state_id": uuid4(),
        "binding_id": binding_id or uuid4(),
        "product_urn": "gda://planning/data_product/districts",
        "from_product_version_id": from_version_id or uuid4(),
        "to_product_version_id": to_version_id or uuid4(),
        "state_version": state_version,
        "compatibility_conclusion": "breaking",
        "compatibility_evidence": {"removed_fields": ["legacy_code"]},
        "notification_status": notification_status,
        "notification_evidence": notification_evidence or {},
        "migration_deadline": recorded_at + timedelta(days=14),
        "consumer_acknowledgement": consumer_acknowledgement,
        "previous_state_sha256": previous_state_sha256,
        "recorded_by": "human:data-steward",
        "recorded_at": recorded_at,
    }
    payload["state_sha256"] = consumer_binding_migration_state_fingerprint(payload)
    return payload


def _receipt_evidence(notification_id=None) -> dict:
    return {
        "notification_id": str(notification_id or uuid4()),
        "receipt_sha256": "d" * 64,
    }


def test_consumer_binding_is_tamper_evident_and_version_bounded() -> None:
    binding = ConsumerBinding.model_validate(_binding_payload())
    assert consumer_binding_fingerprint(binding) == binding.binding_sha256

    payload = binding.model_dump(mode="python")
    payload["purpose"] = "changed purpose"
    with pytest.raises(ValueError, match="binding_sha256"):
        ConsumerBinding.model_validate(payload)


def test_consumer_binding_rejects_invalid_quota_and_range() -> None:
    payload = _binding_payload()
    payload["quota"] = {"max_packages": 0}
    payload["binding_sha256"] = consumer_binding_fingerprint(payload)
    with pytest.raises(ValueError, match="max_packages"):
        ConsumerBinding.model_validate(payload)

    payload = _binding_payload()
    payload["min_product_version"] = "v3.0.0"
    payload["max_product_version"] = "v2.0.0"
    payload["binding_sha256"] = consumer_binding_fingerprint(payload)
    with pytest.raises(ValueError, match="must not exceed"):
        ConsumerBinding.model_validate(payload)


def test_consumer_migration_state_is_tamper_evident_and_cas_linked() -> None:
    initial_payload = _migration_state_payload()
    initial = ConsumerBindingMigrationState.model_validate(initial_payload)
    assert (
        consumer_binding_migration_state_fingerprint(initial)
        == initial.state_sha256
    )

    successor_payload = _migration_state_payload(
        binding_id=initial.binding_id,
        from_version_id=initial.from_product_version_id,
        to_version_id=initial.to_product_version_id,
        state_version=2,
        previous_state_sha256=initial.state_sha256,
        notification_status="delivered",
        notification_evidence=_receipt_evidence(),
    )
    successor = ConsumerBindingMigrationState.model_validate(successor_payload)
    assert successor.previous_state_sha256 == initial.state_sha256

    tampered = successor.model_dump(mode="python")
    tampered["migration_deadline"] += timedelta(days=1)
    with pytest.raises(ValueError, match="state_sha256"):
        ConsumerBindingMigrationState.model_validate(tampered)


def test_terminal_notification_rejects_arbitrary_client_evidence() -> None:
    payload = _migration_state_payload(
        state_version=2,
        previous_state_sha256="a" * 64,
        notification_status="delivered",
        notification_evidence={"delivery_id": "notice-17"},
    )
    payload["state_sha256"] = consumer_binding_migration_state_fingerprint(payload)

    with pytest.raises(ValueError, match="notification_id"):
        ConsumerBindingMigrationState.model_validate(payload)


def test_terminal_outbox_receipt_builds_deterministic_cas_successor() -> None:
    source = ConsumerBindingMigrationState.model_validate(_migration_state_payload())
    completed_at = source.recorded_at + timedelta(minutes=1)
    notification_payload = {
        "tenant_id": source.tenant_id,
        "notification_id": uuid4(),
        "migration_state_id": source.migration_state_id,
        "binding_id": source.binding_id,
        "product_urn": source.product_urn,
        "from_product_version_id": source.from_product_version_id,
        "to_product_version_id": source.to_product_version_id,
        "source_state_sha256": source.state_sha256,
        "channel": "alertmanager",
        "destination_ref": "alertmanager:consumer-binding-default",
        "status": "done",
        "attempt_count": 1,
        "max_attempts": 10,
        "available_at": source.recorded_at,
        "claimed_by": None,
        "claimed_until": None,
        "last_error": None,
        "provider_receipt": {
            "schema": "gda.alertmanager_provider_receipt.v1",
            "provider": "alertmanager",
            "accepted": True,
            "http_status": 202,
        },
        "receipt_sha256": "e" * 64,
        "terminal_worker_id": "worker:test",
        "created_at": source.recorded_at,
        "completed_at": completed_at,
    }
    notification = ConsumerBindingMigrationNotification.model_validate(
        notification_payload
    )

    first = build_consumer_binding_notification_terminal_state(
        notification,
        source,
        recorded_by="service:consumer-binding-notification-worker",
    )
    replay = build_consumer_binding_notification_terminal_state(
        notification,
        source,
        recorded_by="service:consumer-binding-notification-worker",
    )

    assert first == replay
    assert first.state_version == source.state_version + 1
    assert first.previous_state_sha256 == source.state_sha256
    assert first.notification_evidence == {
        "notification_id": str(notification.notification_id),
        "receipt_sha256": notification.receipt_sha256,
    }


def test_consumer_acknowledgement_requires_delivered_breaking_notice() -> None:
    payload = _migration_state_payload(
        consumer_acknowledgement={
            "consumer_ref": "workload:planner-api",
            "acknowledgement_ref": "ack:17",
            "evidence": {"migration_plan": "plan:17"},
            "acknowledged_at": datetime(2026, 8, 7, 11, tzinfo=UTC),
        }
    )
    payload["state_sha256"] = consumer_binding_migration_state_fingerprint(payload)
    with pytest.raises(ValueError, match="delivered notification"):
        ConsumerBindingMigrationState.model_validate(payload)


def test_formal_binding_impact_is_authoritative_and_stable() -> None:
    product = {
        "tenant_id": "planning",
        "product_urn": "gda://planning/data_product/districts",
        "current_version_id": str(uuid4()),
        "current_version_key": "v1.0.0",
    }
    target = {"data_product_version_id": str(uuid4()), "version_key": "v1.1.0"}
    rows = [
        {
            "binding_id": uuid4(),
            "consumer_ref": "workload:planner-b",
            "purpose": "tiles",
            "scope": {"operations": ["read"]},
            "min_product_version": "v1.0.0",
            "max_product_version": None,
            "credential_ref": "credential:b",
            "quota": {"max_packages": 2},
            "expires_at": datetime(2026, 9, 1, tzinfo=UTC),
            "compatibility_fingerprint": "b" * 64,
            "compatibility_evidence": {"schema": "v1"},
        },
        {
            "binding_id": uuid4(),
            "consumer_ref": "workload:planner-a",
            "purpose": "search",
            "scope": {"operations": ["read"]},
            "min_product_version": None,
            "max_product_version": "v2.0.0",
            "credential_ref": "credential:a",
            "quota": {"max_packages": 4},
            "expires_at": datetime(2026, 9, 2, tzinfo=UTC),
            "compatibility_fingerprint": "c" * 64,
            "compatibility_evidence": {"schema": "v1"},
        },
    ]
    impact = _build_promotion_impact(
        product,
        target,
        rows,
        consumer_authority="consumer_binding",
    )
    replay = _build_promotion_impact(
        product,
        target,
        list(reversed(rows)),
        consumer_authority="consumer_binding",
    )

    assert impact["schema"] == "gda.data_product_promotion_impact.v3"
    assert impact["consumer_authority"] == "consumer_binding"
    assert impact["active_binding_count"] == 2
    assert impact["active_grant_count"] == 0
    assert impact["impacted_consumers"] == [
        "workload:planner-a",
        "workload:planner-b",
    ]
    assert impact["acknowledgement_required"] is True
    assert impact["consumer_migration_ready"] is False
    assert {item["reason"] for item in impact["promotion_blockers"]} == {
        "migration_state_missing",
        "compatibility_indeterminate",
    }
    assert impact["impact_fingerprint"] == replay["impact_fingerprint"]


def test_migration_state_changes_invalidate_promotion_impact_fingerprint() -> None:
    product = {
        "tenant_id": "planning",
        "product_urn": "gda://planning/data_product/districts",
        "current_version_id": str(uuid4()),
        "current_version_key": "v1.0.0",
    }
    target = {"data_product_version_id": str(uuid4()), "version_key": "v2.0.0"}
    binding_id = uuid4()
    common = {
        "binding_id": binding_id,
        "consumer_ref": "workload:planner-api",
        "purpose": "serve search",
        "scope": {"operations": ["read"]},
        "min_product_version": "v1.0.0",
        "max_product_version": "v1.9.0",
        "credential_ref": "credential:planner-api",
        "quota": {"max_packages": 5},
        "expires_at": datetime(2026, 9, 1, tzinfo=UTC),
        "compatibility_fingerprint": "a" * 64,
        "binding_compatibility_evidence": {"schema": "districts.v1"},
        "compatibility_conclusion": "breaking",
        "transition_compatibility_evidence": {"removed": ["legacy_code"]},
        "migration_deadline": datetime(2026, 8, 21, tzinfo=UTC),
    }
    pending = {
        **common,
        "migration_state_id": uuid4(),
        "migration_state_version": 1,
        "notification_status": "pending",
        "notification_evidence": {},
        "consumer_acknowledgement": None,
        "migration_state_sha256": "b" * 64,
    }
    delivered = {
        **common,
        "migration_state_id": uuid4(),
        "migration_state_version": 2,
        "notification_status": "delivered",
        "notification_evidence": _receipt_evidence(),
        "consumer_acknowledgement": None,
        "migration_state_sha256": "c" * 64,
    }
    acknowledged = {
        **delivered,
        "migration_state_id": uuid4(),
        "migration_state_version": 3,
        "consumer_acknowledgement": {
            "consumer_ref": "workload:planner-api",
            "acknowledgement_ref": "ack:17",
            "evidence": {"migration_plan": "plan:17"},
            "acknowledged_at": "2026-08-08T00:00:00+00:00",
        },
        "migration_state_sha256": "d" * 64,
    }

    pending_impact = _build_promotion_impact(
        product, target, [pending], consumer_authority="consumer_binding"
    )
    delivered_impact = _build_promotion_impact(
        product, target, [delivered], consumer_authority="consumer_binding"
    )
    acknowledged_impact = _build_promotion_impact(
        product, target, [acknowledged], consumer_authority="consumer_binding"
    )

    assert len(
        {
            pending_impact["impact_fingerprint"],
            delivered_impact["impact_fingerprint"],
            acknowledged_impact["impact_fingerprint"],
        }
    ) == 3
    assert acknowledged_impact["consumer_migration_ready"] is True
    assert acknowledged_impact["promotion_blockers"] == []
    assert acknowledged_impact["acknowledgement_required"] is True


def test_registry_queries_formal_impact_before_transitional_grants() -> None:
    connection = MagicMock()
    formal_result = MagicMock()
    formal_result.mappings.return_value.all.return_value = [
        {
            "binding_id": uuid4(),
            "consumer_ref": "workload:planner-api",
            "purpose": "serve search",
            "scope": {"operations": ["read"]},
            "min_product_version": "v1.0.0",
            "max_product_version": "v2.0.0",
            "credential_ref": "credential:planner-api",
            "quota": {"max_packages": 5},
            "expires_at": datetime(2026, 9, 1, tzinfo=UTC),
            "compatibility_fingerprint": "a" * 64,
            "compatibility_evidence": {"schema": "districts.v1"},
        }
    ]
    connection.execute.return_value = formal_result
    impact = DataProductRegistry._promotion_impact(
        connection,
        {
            "tenant_id": "planning",
            "product_urn": "gda://planning/data_product/districts",
            "current_version_id": str(uuid4()),
            "current_version_key": "v1.0.0",
        },
        {"data_product_version_id": str(uuid4()), "version_key": "v1.1.0"},
    )

    assert impact["consumer_authority"] == "consumer_binding"
    assert impact["active_binding_count"] == 1
    assert connection.execute.call_count == 1


def test_consumer_binding_migration_is_rls_and_minimum_privilege() -> None:
    migration = (
        Path(__file__).parent / "migrations/149_consumer_binding.sql"
    ).read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS gda_control.consumer_binding" in migration
    assert "FORCE ROW LEVEL SECURITY" in migration
    assert "CREATE OR REPLACE FUNCTION gda_control.record_consumer_binding" in migration
    assert "SECURITY DEFINER" in migration
    assert "CREATE OR REPLACE FUNCTION gda_control.active_consumer_binding_impact" in migration
    assert "REVOKE ALL ON TABLE gda_control.consumer_binding" in migration
    assert "GRANT SELECT ON TABLE gda_control.consumer_binding" in migration
    assert "GRANT EXECUTE ON FUNCTION gda_control.record_consumer_binding" in migration
    assert "ck_gda_promotion_impact_consumer_authority" in migration


def test_consumer_migration_state_migration_is_append_only_and_locked() -> None:
    migration = (
        Path(__file__).parent
        / "migrations/150_consumer_binding_migration_state.sql"
    ).read_text(encoding="utf-8")
    assert "consumer_binding_migration_state" in migration
    assert "record_consumer_binding_migration_state" in migration
    assert "previous_state_sha256" in migration
    assert "consumer_acknowledgement" in migration
    assert "migration_deadline" in migration
    assert "pg_advisory_xact_lock" in migration
    assert "data-product-promotion:" in migration
    assert "FORCE ROW LEVEL SECURITY" in migration
    assert "trg_gda_consumer_migration_state_immutable" in migration
    assert "REVOKE ALL ON TABLE gda_control.consumer_binding_migration_state" in migration
    assert "active_consumer_binding_impact" in migration


def test_consumer_notification_outbox_is_durable_and_receipt_bound() -> None:
    migration = (
        Path(__file__).parent
        / "migrations/152_consumer_binding_migration_notification_outbox.sql"
    ).read_text(encoding="utf-8")
    assert "consumer_binding_migration_notification_outbox" in migration
    assert "enqueue_consumer_binding_migration_notification" in migration
    assert "FOR UPDATE SKIP LOCKED" in migration
    assert "claim_consumer_binding_migration_notifications" in migration
    assert "complete_consumer_binding_migration_notification" in migration
    assert "fail_consumer_binding_migration_notification" in migration
    assert "consumer_binding_notification_receipt_fingerprint" in migration
    assert "terminal notification evidence is not backed by a valid outbox receipt" in migration
    assert "gda.consumer_binding_notification_outbox_allowed" in migration
    assert "FORCE ROW LEVEL SECURITY" in migration
    assert (
        "GRANT SELECT ON TABLE "
        "gda_control.consumer_binding_migration_notification_outbox"
    ) in migration
