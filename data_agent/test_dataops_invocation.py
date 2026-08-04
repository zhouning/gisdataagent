from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID

import pytest

from data_agent.dataops_invocation import (
    DATAOPS_INVOCATION_SEMANTIC_TYPE,
    DataOpsInvocation,
    DataOpsInvocationError,
    build_dataops_invocation_resources,
    dataops_invocation_version_id,
    parse_dataops_invocation_version,
)

TENANT = "tenant-a"
DEFINITION_ID = UUID("10000000-0000-4000-8000-000000000010")
START = datetime(2026, 7, 1, tzinfo=UTC)
END = datetime(2026, 7, 3, tzinfo=UTC)
REQUESTED_AT = datetime(2026, 8, 1, 1, 2, 3, tzinfo=UTC)


def _invocation(**overrides):
    values = {
        "tenant_id": TENANT,
        "definition_version_id": DEFINITION_ID,
        "trigger_kind": "backfill",
        "logical_start": START,
        "logical_end": END,
        "schedule_times": (START,),
        "schedule_ref": "gda://tenant-a/schedule/land-use-daily",
        "requested_by": "human:data-platform-operator",
        "requested_at": REQUESTED_AT,
    }
    values.update(overrides)
    return DataOpsInvocation.create(**values)


def test_invocation_resources_are_deterministic_and_round_trip():
    invocation = _invocation(
        logical_start=START.astimezone(timezone(timedelta(hours=8))),
        logical_end=END.astimezone(timezone(timedelta(hours=8))),
    )
    first_resource, first_version = build_dataops_invocation_resources(invocation)
    replay_resource, replay_version = build_dataops_invocation_resources(invocation)

    assert first_resource == replay_resource
    assert first_version == replay_version
    assert first_resource.resource_urn == f"gda://{TENANT}/trigger/{DEFINITION_ID}"
    assert first_version.resource_version_id == dataops_invocation_version_id(invocation)
    assert first_version.content_sha256 == invocation.invocation_sha256
    assert parse_dataops_invocation_version(first_version) == invocation
    assert DATAOPS_INVOCATION_SEMANTIC_TYPE == "platform.dataops.invocation"


@pytest.mark.parametrize(
    "overrides",
    (
        {"logical_start": START.replace(tzinfo=None)},
        {"logical_end": START},
        {"logical_start": END, "logical_end": START},
        {"trigger_kind": "schedule", "schedule_ref": None},
        {"trigger_kind": "manual", "schedule_ref": "schedule:daily"},
        {"trigger_kind": "manual", "schedule_ref": None, "schedule_times": ()},
        {"trigger_kind": "replay", "schedule_ref": "schedule:daily"},
        {"schedule_times": ()},
        {"schedule_times": (START, START + timedelta(days=1))},
        {"schedule_times": (END,)},
    ),
)
def test_invocation_rejects_ambiguous_or_invalid_windows(overrides):
    with pytest.raises(ValueError):
        _invocation(**overrides)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("tenant_id", "tenant-b"),
        ("resource_urn", f"gda://{TENANT}/trigger/tampered"),
        ("resource_version_id", UUID("10000000-0000-4000-8000-000000000099")),
        ("version_key", "inv-tampered"),
        ("predecessor_version_id", UUID("10000000-0000-4000-8000-000000000098")),
        ("content_sha256", "f" * 64),
        ("created_by", "human:someone-else"),
        ("created_at", REQUESTED_AT + timedelta(seconds=1)),
    ),
)
def test_invocation_resource_version_metadata_tampering_fails_closed(field, value):
    _resource, version = build_dataops_invocation_resources(_invocation())
    tampered = version.model_copy(update={field: value})

    with pytest.raises(DataOpsInvocationError):
        parse_dataops_invocation_version(tampered)


def test_invocation_document_and_fingerprint_tampering_fail_closed():
    _resource, version = build_dataops_invocation_resources(_invocation())
    document = dict(version.authority_version_ref["invocation"])
    document["logical_end"] = "2026-07-04T00:00:00Z"
    tampered = version.model_copy(
        update={
            "authority_version_ref": {
                "schema": version.authority_version_ref["schema"],
                "invocation": document,
            }
        }
    )

    with pytest.raises(DataOpsInvocationError, match="document is invalid"):
        parse_dataops_invocation_version(tampered)

    with pytest.raises(ValueError, match="invocation_sha256"):
        DataOpsInvocation.model_validate(
            _invocation().model_dump(mode="json", by_alias=True)
            | {"invocation_sha256": "0" * 64}
        )


def test_scheduled_invocation_binds_one_explicit_provider_time():
    scheduled_for = END + timedelta(minutes=5)
    invocation = _invocation(
        trigger_kind="schedule",
        logical_start=START,
        logical_end=END,
        schedule_times=(scheduled_for,),
    )

    assert invocation.trigger_kind == "schedule"
    assert invocation.schedule_times == (scheduled_for,)
    assert parse_dataops_invocation_version(
        build_dataops_invocation_resources(invocation)[1]
    ) == invocation


def test_manual_invocation_round_trips_client_retry_identity():
    invocation = _invocation(
        trigger_kind="manual",
        schedule_ref=None,
        schedule_times=(),
        client_request_id="operator-console-20260801-001",
    )
    _resource, version = build_dataops_invocation_resources(invocation)

    assert invocation.client_request_id == "operator-console-20260801-001"
    assert parse_dataops_invocation_version(version) == invocation

    with pytest.raises(ValueError, match="only valid for manual"):
        _invocation(client_request_id="operator-console-20260801-001")
