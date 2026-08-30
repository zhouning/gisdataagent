from __future__ import annotations

from copy import deepcopy

import pytest

from data_agent.dolphinscheduler_recovery import (
    ContainerSnapshot,
    DolphinSchedulerRecoveryError,
    build_recovery_report,
)


def _finalization() -> dict[str, object]:
    return {
        "schema": "gda.chongqing_jqdltb_dataops_finalization.v1",
        "run_id": "de2a6b36-4b3a-5bde-89a6-c50ef4100721",
        "platform_run_status": "failed",
        "platform_run_state_version": 3,
        "platform_run_transitioned": False,
        "provider_state": "SUCCESS",
        "workflow_instance_id": 1,
        "attempt_observation_id": "1920b879-efb3-5648-83a5-d2e66a403d73",
        "attempt_observation_created": False,
        "quality_result_id": "3cd806bb-3b3e-59c5-9526-050506ff8f96",
        "quality_verdict": "failed",
        "evidence_artifact_id": "8c1eb392-26e9-51cc-a19a-f754eb4f26c3",
        "records_scanned": 1555,
        "assessment_resource_created": False,
        "assessment_version_created": False,
        "assessment_resource_version_id": "afec3dc3-9dac-5f3a-b6e2-5afb4e38c11d",
        "lineage_event_id": "527a83c8-710b-572a-8037-4f6756c3e468",
        "lineage_created": False,
        "data_product_version_created": False,
    }


def _container(service: str, started_at: str) -> ContainerSnapshot:
    value = "a" * 64 if service == "dolphinscheduler" else "b" * 64
    return ContainerSnapshot(
        service=service,
        container_id=value,
        started_at=started_at,
    )


def _report(before: dict | None = None, after: dict | None = None) -> dict:
    return build_recovery_report(
        before_document=before or _finalization(),
        after_document=after or _finalization(),
        runtime_before=_container("dolphinscheduler", "2026-08-01T00:00:00Z"),
        runtime_after=_container("dolphinscheduler", "2026-08-01T00:01:00Z"),
        metadata_before=_container("metadata-db", "2026-07-31T00:00:00Z"),
        metadata_after=_container("metadata-db", "2026-07-31T00:00:00Z"),
        restarted_at="2026-08-01T00:00:30+00:00",
        ready_at="2026-08-01T00:01:00+00:00",
        observed_seconds=30.1234,
    )


def test_restart_recovery_preserves_authoritative_identity() -> None:
    report = _report()

    assert report["technical_pass"] is True
    assert report["promotion_ready"] is False
    assert report["observed_seconds"] == 30.123
    assert report["checks"]["idempotent_replay"] is True
    assert report["checks"]["data_product_version_created"] is False
    assert report["authoritative_state"]["workflow_instance_id"] == 1
    assert "container_id" not in report["runtime"]


def test_restart_recovery_rejects_duplicate_ledger_write() -> None:
    after = _finalization()
    after["lineage_created"] = True

    with pytest.raises(DolphinSchedulerRecoveryError) as error:
        _report(after=after)

    assert error.value.stage == "ledger.duplicate_write.lineage"


def test_restart_recovery_rejects_authoritative_identity_drift() -> None:
    after = deepcopy(_finalization())
    after["quality_result_id"] = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"

    with pytest.raises(DolphinSchedulerRecoveryError) as error:
        _report(after=after)

    assert error.value.stage == "ledger.identity_drift"


def test_restart_recovery_requires_runtime_restart() -> None:
    with pytest.raises(DolphinSchedulerRecoveryError) as error:
        build_recovery_report(
            before_document=_finalization(),
            after_document=_finalization(),
            runtime_before=_container("dolphinscheduler", "2026-08-01T00:00:00Z"),
            runtime_after=_container("dolphinscheduler", "2026-08-01T00:00:00Z"),
            metadata_before=_container("metadata-db", "2026-07-31T00:00:00Z"),
            metadata_after=_container("metadata-db", "2026-07-31T00:00:00Z"),
            restarted_at="2026-08-01T00:00:30+00:00",
            ready_at="2026-08-01T00:01:00+00:00",
            observed_seconds=30,
        )

    assert error.value.stage == "runtime.restart_not_observed"


def test_restart_recovery_rejects_metadata_database_restart() -> None:
    with pytest.raises(DolphinSchedulerRecoveryError) as error:
        build_recovery_report(
            before_document=_finalization(),
            after_document=_finalization(),
            runtime_before=_container("dolphinscheduler", "2026-08-01T00:00:00Z"),
            runtime_after=_container("dolphinscheduler", "2026-08-01T00:01:00Z"),
            metadata_before=_container("metadata-db", "2026-07-31T00:00:00Z"),
            metadata_after=_container("metadata-db", "2026-08-01T00:00:00Z"),
            restarted_at="2026-08-01T00:00:30+00:00",
            ready_at="2026-08-01T00:01:00+00:00",
            observed_seconds=30,
        )

    assert error.value.stage == "metadata.container_changed"
