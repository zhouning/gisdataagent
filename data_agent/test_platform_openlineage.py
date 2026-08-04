import asyncio
import json
from contextlib import nullcontext
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest
from pydantic import ValidationError

from data_agent.api import platform_gateway_routes as routes
from data_agent.platform_contracts import (
    Artifact,
    PlatformRun,
    ResourceBinding,
    ResourceVersion,
    SubjectContext,
)
from data_agent.platform_gateway import (
    GatewayForbiddenError,
    GatewayValidationError,
    GatewayWriteResult,
    PlatformGateway,
)
from data_agent.platform_openlineage import (
    MAX_GENERATED_EDGES,
    OpenLineageRunEvent,
    openlineage_to_lineage_events,
)

TENANT = "tenant-a"
RUN_ID = UUID("10000000-0000-4000-8000-000000000001")
OPENLINEAGE_RUN_ID = UUID("10000000-0000-4000-8000-000000000002")
DEFINITION_ID = UUID("10000000-0000-4000-8000-000000000003")
ARTIFACT_ID = UUID("10000000-0000-4000-8000-000000000004")
SOURCE_ID = UUID("10000000-0000-4000-8000-000000000005")
TARGET_ID = UUID("10000000-0000-4000-8000-000000000006")
SECOND_TARGET_ID = UUID("10000000-0000-4000-8000-000000000007")
NOW = datetime(2026, 8, 3, 8, 30, tzinfo=UTC)
WORKLOAD_ACTOR = "workload:lineage-emitter"


def _dataset(resource_version_id: UUID, *, name: str, secret: str = "not-stored") -> dict:
    return {
        "namespace": "iceberg://catalog/geo",
        "name": name,
        "facets": {
            "gda_resource": {"resourceVersionId": str(resource_version_id)},
            "schema": {"fields": [{"name": "secret", "description": secret}]},
        },
    }


def _payload(*, outputs: list[dict] | None = None) -> dict:
    return {
        "eventType": "COMPLETE",
        "eventTime": NOW.isoformat(),
        "run": {
            "runId": str(OPENLINEAGE_RUN_ID),
            "facets": {
                "gda_platform": {
                    "tenantId": TENANT,
                    "platformRunId": str(RUN_ID),
                    "definitionVersionId": str(DEFINITION_ID),
                    "artifactId": str(ARTIFACT_ID),
                    "operation": "derive",
                },
                "nominalTime": {"nominalStartTime": NOW.isoformat()},
            },
        },
        "job": {
            "namespace": "dolphinscheduler://prod",
            "name": "publish_parcels",
            "facets": {"jobType": {"processingType": "BATCH"}},
        },
        "inputs": [_dataset(SOURCE_ID, name="raw.parcels")],
        "outputs": outputs
        or [
            _dataset(TARGET_ID, name="gold.parcels", secret="output-contract"),
            _dataset(SECOND_TARGET_ID, name="gold.parcel_metrics"),
        ],
        "producer": "https://scheduler.example/openlineage/1.0",
        "schemaURL": "https://openlineage.io/spec/2-0-2/OpenLineage.json",
    }


def _run(*, subject_id: str = "lineage-emitter") -> PlatformRun:
    return PlatformRun(
        tenant_id=TENANT,
        run_id=RUN_ID,
        definition_version_id=DEFINITION_ID,
        orchestration_class="dataops",
        subject_context=SubjectContext(
            tenant_id=TENANT,
            subject_id=subject_id,
            subject_type="workload",
            roles=("platform_operator",),
            purpose="publish governed parcels",
        ),
        input_bindings=(
            ResourceBinding(
                binding_name="source",
                resource_version_id=SOURCE_ID,
                semantic_type="parcel_source",
            ),
        ),
        idempotency_key="openlineage-test",
        submitted_at=NOW,
    )


def _artifact(*, run_id: UUID = RUN_ID) -> Artifact:
    return Artifact(
        tenant_id=TENANT,
        artifact_id=ARTIFACT_ID,
        artifact_key="published-parcels",
        artifact_role="output",
        storage_uri="s3://governed/gold/parcels.parquet",
        media_type="application/vnd.apache.parquet",
        content_sha256="a" * 64,
        size_bytes=100,
        run_id=run_id,
        resource_version_id=TARGET_ID,
        created_by=WORKLOAD_ACTOR,
        created_at=NOW,
    )


def _version(resource_version_id: UUID) -> ResourceVersion:
    return ResourceVersion(
        tenant_id=TENANT,
        resource_urn=f"gda://{TENANT}/dataset/resource-{str(resource_version_id)[-4:]}",
        resource_version_id=resource_version_id,
        version_key=str(resource_version_id),
        content_sha256="b" * 64,
        authority_version_ref={"snapshot": str(resource_version_id)},
        created_by=WORKLOAD_ACTOR,
        created_at=NOW,
    )


def _request(*, body: dict) -> MagicMock:
    request = MagicMock()

    async def read_json():
        return body

    request.json.side_effect = read_json
    request.path_params = {}
    request.query_params = {}
    request.headers = {"x-request-id": "openlineage-request"}
    return request


def _user(*, subject_type: str = "workload", tenant_id: str = TENANT):
    return SimpleNamespace(
        identifier="lineage-emitter",
        metadata={
            "role": "platform_operator",
            "tenant_id": tenant_id,
            "subject_type": subject_type,
        },
    )


def test_openlineage_complete_generates_stable_bounded_edges_without_copying_facets():
    event = OpenLineageRunEvent.model_validate(_payload())

    first = openlineage_to_lineage_events(
        event,
        authenticated_producer=WORKLOAD_ACTOR,
    )
    replay = openlineage_to_lineage_events(
        event,
        authenticated_producer=WORKLOAD_ACTOR,
    )

    assert len(first) == 2
    assert first == replay
    assert {item.target_resource_version_id for item in first} == {
        TARGET_ID,
        SECOND_TARGET_ID,
    }
    assert all(item.producer == WORKLOAD_ACTOR for item in first)
    assert all(item.run_id == RUN_ID for item in first)
    assert all(len(item.event_sha256) == 64 for item in first)
    assert "not-stored" not in json.dumps(first[0].facets)
    assert "output-contract" not in json.dumps(first[0].facets)
    assert len(first[0].facets["openlineage"]["input_dataset"]["facets_sha256"]) == 64

    changed_payload = _payload()
    changed_payload["inputs"][0]["facets"]["schema"]["fields"][0]["description"] = (
        "changed-but-not-stored"
    )
    changed = openlineage_to_lineage_events(
        OpenLineageRunEvent.model_validate(changed_payload),
        authenticated_producer=WORKLOAD_ACTOR,
    )
    assert changed[0].lineage_event_id == first[0].lineage_event_id
    assert changed[0].event_sha256 != first[0].event_sha256


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda value: value.update(eventType="START"), "COMPLETE"),
        (
            lambda value: value["inputs"][0]["facets"].pop("gda_resource"),
            "gda_resource",
        ),
    ],
)
def test_openlineage_contract_fails_closed_for_unsupported_or_uncorrelated_events(
    mutate,
    message,
):
    value = _payload()
    mutate(value)
    with pytest.raises(ValidationError, match=message):
        OpenLineageRunEvent.model_validate(value)


def test_openlineage_contract_rejects_cartesian_edge_explosion():
    value = _payload()
    value["inputs"] = [
        _dataset(UUID(int=index + 1), name=f"input-{index}") for index in range(17)
    ]
    value["outputs"] = [
        _dataset(UUID(int=index + 100), name=f"output-{index}") for index in range(16)
    ]
    with pytest.raises(ValidationError, match=str(MAX_GENERATED_EDGES)):
        OpenLineageRunEvent.model_validate(value)


def test_gateway_lineage_batch_validates_immutable_run_bindings():
    events = openlineage_to_lineage_events(
        OpenLineageRunEvent.model_validate(_payload()),
        authenticated_producer=WORKLOAD_ACTOR,
    )
    versions = {SOURCE_ID, TARGET_ID, SECOND_TARGET_ID}
    with (
        patch.object(PlatformGateway, "_load_run", return_value=_run()),
        patch.object(PlatformGateway, "_load_artifact", return_value=_artifact()),
        patch.object(
            PlatformGateway,
            "_load_resource_version",
            side_effect=lambda _, __, version_id: (
                _version(version_id) if version_id in versions else None
            ),
        ),
    ):
        PlatformGateway._validate_lineage_batch_bindings(MagicMock(), events)

    with (
        patch.object(
            PlatformGateway,
            "_load_run",
            return_value=_run(subject_id="another-emitter"),
        ),
        patch.object(PlatformGateway, "_load_artifact", return_value=_artifact()),
        pytest.raises(GatewayForbiddenError, match="does not own"),
    ):
        PlatformGateway._validate_lineage_batch_bindings(MagicMock(), events)

    with (
        patch.object(PlatformGateway, "_load_run", return_value=_run()),
        patch.object(
            PlatformGateway,
            "_load_artifact",
            return_value=_artifact(run_id=UUID(int=999)),
        ),
        pytest.raises(GatewayValidationError, match="does not belong"),
    ):
        PlatformGateway._validate_lineage_batch_bindings(MagicMock(), events)


def test_gateway_lineage_batch_uses_one_transaction_and_preserves_item_replay_state():
    events = openlineage_to_lineage_events(
        OpenLineageRunEvent.model_validate(_payload()),
        authenticated_producer=WORKLOAD_ACTOR,
    )
    gateway = PlatformGateway()
    connection = MagicMock()
    expected = (
        GatewayWriteResult(events[0], True),
        GatewayWriteResult(events[1], False),
    )
    with (
        patch.object(gateway, "_transaction", return_value=nullcontext(connection)) as tx,
        patch.object(gateway, "_validate_lineage_batch_bindings") as validate,
        patch.object(gateway, "_put_lineage", side_effect=expected) as put,
    ):
        result = gateway.record_lineage_batch(events)

    assert result == expected
    tx.assert_called_once_with(TENANT)
    validate.assert_called_once_with(connection, events)
    assert [call.args[1] for call in put.call_args_list] == list(events)


def test_openlineage_route_requires_workload_and_uses_authenticated_producer():
    event = OpenLineageRunEvent.model_validate(_payload())
    converted = openlineage_to_lineage_events(
        event,
        authenticated_producer=WORKLOAD_ACTOR,
    )
    gateway = MagicMock()
    gateway.record_lineage_batch.return_value = tuple(
        GatewayWriteResult(item, True) for item in converted
    )
    request = _request(body=_payload())
    with (
        patch.object(routes, "_get_user_from_request", return_value=_user()),
        patch.object(routes, "_gateway", return_value=gateway),
    ):
        response = asyncio.run(routes.create_openlineage_event(request))

    body = json.loads(response.body)
    assert response.status_code == 201
    assert body["data"]["event_count"] == 2
    assert body["data"]["created_count"] == 2
    recorded = gateway.record_lineage_batch.call_args.args[0]
    assert all(item.producer == WORKLOAD_ACTOR for item in recorded)

    human_request = _request(body=_payload())
    with (
        patch.object(
            routes,
            "_get_user_from_request",
            return_value=_user(subject_type="human"),
        ),
        patch.object(routes, "_gateway", return_value=gateway),
    ):
        rejected = asyncio.run(routes.create_openlineage_event(human_request))
    assert rejected.status_code == 403
    assert json.loads(rejected.body)["error"]["code"] == "workload_identity_required"


def test_openlineage_route_rejects_facet_tenant_mismatch_before_database_access():
    gateway = MagicMock()
    request = _request(body=_payload())
    with (
        patch.object(
            routes,
            "_get_user_from_request",
            return_value=_user(tenant_id="tenant-b"),
        ),
        patch.object(routes, "_gateway", return_value=gateway),
    ):
        response = asyncio.run(routes.create_openlineage_event(request))

    assert response.status_code == 403
    assert json.loads(response.body)["error"]["code"] == "tenant_mismatch"
    gateway.record_lineage_batch.assert_not_called()
