import hashlib
import json
from datetime import timedelta

import httpx
import pytest
from pydantic import ValidationError

from data_agent.metadata_fabric_lineage_delivery import (
    DEFAULT_EVIDENCE_PATH,
    build_contract_report,
    build_lineage_delivery_bundle,
    validate_rehearsal_evidence,
)
from data_agent.metadata_fabric_lineage_delivery_contract import (
    MetadataFabricLineageDelivery,
    build_metadata_fabric_lineage_delivery,
)
from data_agent.metadata_fabric_lineage_emitter import (
    LineageEmitterProfile,
    LineageHttpDeliveryError,
    OpenLineageHttpEmitter,
)
from data_agent.platform_contracts import (
    canonical_json_bytes,
    canonical_json_fingerprint,
)


def _claimed_delivery():
    delivery = build_lineage_delivery_bundle().delivery
    payload = delivery.model_dump(mode="json", by_alias=True)
    payload.update(
        {
            "status": "in_flight",
            "attempt_count": 1,
            "claimed_by": "worker:test-lineage-1",
            "claimed_until": (delivery.created_at + timedelta(minutes=1)).isoformat(),
        }
    )
    return MetadataFabricLineageDelivery.model_validate(payload)


def test_delivery_is_deterministic_and_bound_to_authorized_source_plan():
    first = build_lineage_delivery_bundle()
    second = build_lineage_delivery_bundle()

    assert first == second
    assert str(first.delivery.delivery_id) == ("49a54408-b3a8-5843-a27d-6395c080af99")
    assert first.delivery.event_sha256 == (
        "4929e51c4126e09415a9fc1578c9401077c5d7c374294e70deeebd29c8216dd2"
    )
    assert first.delivery.idempotency_key == (
        "e1a2862b7e246b3717ee2e65cf1a765a40865fdce13eed1b129319d9772c0073"
    )
    assert first.delivery.actor_subject != (first.binding_bundle.record.recorded_by)


def test_delivery_rejects_event_and_binding_tampering():
    bundle = build_lineage_delivery_bundle()
    payload = bundle.delivery.model_dump(mode="json", by_alias=True)
    payload["event"]["job"]["name"] = "tampered"
    with pytest.raises(ValidationError, match="event SHA-256"):
        MetadataFabricLineageDelivery.model_validate(payload)

    apply_plan_artifact = bundle.binding_bundle.artifacts[0]
    from data_agent.metadata_fabric_binding_contract import (
        parse_metadata_fabric_execution_plan_artifact,
    )

    apply_plan = parse_metadata_fabric_execution_plan_artifact(apply_plan_artifact)
    mismatched_plan = bundle.source_plan.model_copy(
        update={"resource_version_id": bundle.source_plan.source_resource_version_id}
    )
    with pytest.raises(ValueError, match="binding identity"):
        build_metadata_fabric_lineage_delivery(
            binding=bundle.binding_bundle.record,
            source_plan=mismatched_plan,
            apply_plan=apply_plan,
            actor_subject=bundle.delivery.actor_subject,
            created_at=bundle.delivery.created_at,
        )


def test_emitter_profile_rejects_remote_credentials_and_redirect_targets():
    common = {
        "target_name": "sink",
        "actor_subject": "workload:lineage",
    }
    for endpoint in (
        "https://example.com/api/v1/lineage",
        "http://user:pass@127.0.0.1/api/v1/lineage",
        "http://127.0.0.1/redirect",
        "http://127.0.0.1/api/v1/lineage?token=x",
    ):
        with pytest.raises(ValidationError, match="loopback"):
            LineageEmitterProfile(endpoint_url=endpoint, **common)


def test_http_emitter_uses_canonical_body_and_stable_idempotency_headers():
    delivery = _claimed_delivery()
    success_body = b'{"duplicate":true}'
    responses = [
        httpx.Response(503, json={"accepted": True}),
        httpx.Response(200, content=success_body),
    ]
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return responses.pop(0)

    profile = LineageEmitterProfile(
        target_name=delivery.target_name,
        endpoint_url="http://127.0.0.1:9999/api/v1/lineage",
        actor_subject=delivery.actor_subject,
    )
    with OpenLineageHttpEmitter(profile, transport=httpx.MockTransport(handler)) as emitter:
        with pytest.raises(LineageHttpDeliveryError) as first:
            emitter.emit(delivery)
        receipt = emitter.emit(delivery)

    assert first.value.code == "http_5xx"
    assert first.value.retryable is True
    expected = canonical_json_bytes(delivery.event.model_dump(mode="json", by_alias=True))
    assert [request.content for request in requests] == [expected, expected]
    assert all(
        request.headers["Idempotency-Key"] == delivery.idempotency_key for request in requests
    )
    assert receipt.response_status == 200
    assert receipt.response_body_sha256 == hashlib.sha256(success_body).hexdigest()


def test_lineage_delivery_contract_and_committed_evidence_validate():
    report = build_contract_report()
    evidence = json.loads(DEFAULT_EVIDENCE_PATH.read_text(encoding="utf-8"))

    assert report["status"] == "valid"
    assert report["errors"] == []
    assert report["local_wire_openlineage_delivery_verified"] is False
    assert report["live_openlineage_emission_verified"] is False
    assert validate_rehearsal_evidence(evidence) == []
    assert evidence["local_wire_openlineage_delivery_verified"] is True
    assert evidence["live_openlineage_emission_verified"] is False
    tampered = {**evidence, "receiver_unique_accept_count": 2}
    assert "lineage delivery evidence SHA-256 does not match" in (
        validate_rehearsal_evidence(tampered)
    )
    tampered["evidence_sha256"] = canonical_json_fingerprint(
        {key: value for key, value in tampered.items() if key != "evidence_sha256"}
    )
    assert "lineage delivery evidence receiver_unique_accept_count does not match" in (
        validate_rehearsal_evidence(tampered)
    )
