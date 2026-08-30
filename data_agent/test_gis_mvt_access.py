from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID

import pytest

from data_agent.gis_mvt_access import (
    MVTAccessDeniedError,
    MVTAccessService,
    MVTAccessUnavailableError,
    build_mvt_access_decision,
)
from data_agent.platform_contracts import SubjectContext, SubjectType
from data_agent.security_event_ledger import SecurityEventLedgerUnavailableError

NOW = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)
ATTEMPT_ID = UUID("00000000-0000-4000-8000-000000000801")
RELEASE_ID = UUID("00000000-0000-4000-8000-000000000802")
POLICY_ID = UUID("00000000-0000-4000-8000-000000000803")
PROJECTION_ID = UUID("00000000-0000-4000-8000-000000000804")
BINDING_ID = UUID("00000000-0000-4000-8000-000000000805")
PRODUCT_VERSION_ID = UUID("00000000-0000-4000-8000-000000000806")
DEFINITION_ID = UUID("00000000-0000-4000-8000-000000000807")


def _subject(role: str = "analyst") -> SubjectContext:
    return SubjectContext(
        tenant_id="planning",
        subject_id="analyst-01",
        subject_type=SubjectType.HUMAN,
        roles=(role,),
        purpose="gis_mvt_read",
        trace_id="request-801",
    )


def _components(*, binding=True, allowed_roles=("analyst",)):
    definition = SimpleNamespace(
        service_definition_version_id=DEFINITION_ID,
        source_product_urn="gda://planning/data_product/district-features",
        source_data_product_version_id=PRODUCT_VERSION_ID,
    )
    release = SimpleNamespace(
        service_release_binding_id=RELEASE_ID,
        binding_sha256="a" * 64,
    )
    policy = SimpleNamespace(
        service_policy_binding_id=POLICY_ID,
        policy_sha256="b" * 64,
        version_key="v1.0.0",
        allowed_roles=allowed_roles,
        consumer_binding_required_roles=("analyst",),
        required_consumer_operation="read",
    )
    projection = SimpleNamespace(
        mvt_serving_projection_version_id=PROJECTION_ID,
        projection_sha256="c" * 64,
    )
    service_consumer_binding = None
    if binding:
        service_consumer_binding = SimpleNamespace(
            tenant_id="planning",
            service_urn="gda://planning/gis_service/district-features",
            service_definition_version_id=DEFINITION_ID,
            service_release_binding_id=RELEASE_ID,
            consumer_ref="human:analyst-01",
            action="mvt.read",
            purpose="gis_mvt_read",
            scope={"operations": ["read"]},
            expires_at=NOW + timedelta(hours=1),
            service_consumer_binding_id=BINDING_ID,
            binding_sha256="d" * 64,
        )
    return definition, release, policy, projection, service_consumer_binding


def _admit(
    service: MVTAccessService,
    *,
    binding=True,
    allowed_roles=("analyst",),
    binding_override=None,
):
    definition, release, policy, projection, service_consumer_binding = _components(
        binding=binding, allowed_roles=allowed_roles
    )
    if binding_override is not None:
        service_consumer_binding = binding_override
    return service.admit(
        request_id="request-801",
        subject_context=_subject(),
        service_urn="gda://planning/gis_service/district-features",
        definition=definition,
        release=release,
        service_policy=policy,
        serving_projection=projection,
        service_consumer_binding=service_consumer_binding,
        z=0,
        x=0,
        y=0,
    )


def test_admission_seals_http_subject_release_policy_binding_and_projection() -> None:
    ledger = Mock()
    service = MVTAccessService(
        ledger=ledger,
        now=lambda: NOW,
        attempt_id_factory=lambda: ATTEMPT_ID,
    )

    admission = _admit(service)

    assert admission.attempt_id == ATTEMPT_ID
    assert admission.decision.request.subject_context == _subject()
    assert admission.decision.request.service_release_binding_id == RELEASE_ID
    assert admission.decision.request.service_policy_binding_id == POLICY_ID
    assert admission.decision.request.mvt_serving_projection_version_id == PROJECTION_ID
    assert admission.decision.request.service_consumer_binding_id == BINDING_ID
    assert ledger.append.call_args.kwargs["phase"] == "admitted"
    assert ledger.append.call_args.kwargs["details"]["provider_invocations"] == 0


def test_success_outcome_is_audited_before_any_tile_can_be_returned() -> None:
    ledger = Mock()
    service = MVTAccessService(
        ledger=ledger,
        now=lambda: NOW,
        attempt_id_factory=lambda: ATTEMPT_ID,
    )
    admission = _admit(service)

    service.record_success(
        admission,
        content=b"tile-payload",
        status_code=200,
        media_type="application/vnd.mapbox-vector-tile",
    )

    assert [call.kwargs["phase"] for call in ledger.append.call_args_list] == [
        "admitted",
        "outcome",
    ]
    details = ledger.append.call_args.kwargs["details"]
    assert details["provider_invocations"] == 1
    assert details["delivery_source"] == "provider"
    assert details["tile_content_bytes"] == len(b"tile-payload")
    assert "tile-payload" not in json.dumps(details)


def test_cache_success_is_audited_without_a_provider_invocation() -> None:
    ledger = Mock()
    service = MVTAccessService(
        ledger=ledger,
        now=lambda: NOW,
        attempt_id_factory=lambda: ATTEMPT_ID,
    )
    admission = _admit(service)

    service.record_success(
        admission,
        content=b"cached-tile-payload",
        status_code=200,
        media_type="application/vnd.mapbox-vector-tile",
        delivery_source="redis_cache",
    )

    outcome = ledger.append.call_args.kwargs
    assert outcome["reason"] == "release_bound_mvt_redis_cache_read_succeeded"
    assert outcome["details"]["delivery_source"] == "redis_cache"
    assert outcome["details"]["provider_invocations"] == 0


def test_missing_binding_denies_before_provider_and_records_only_a_safe_denial() -> None:
    ledger = Mock()
    service = MVTAccessService(
        ledger=ledger,
        now=lambda: NOW,
        attempt_id_factory=lambda: ATTEMPT_ID,
    )

    with pytest.raises(MVTAccessDeniedError) as error:
        _admit(service, binding=False)

    assert error.value.code == "service_consumer_binding_required"
    assert ledger.append.call_args.kwargs["phase"] == "denied"
    assert ledger.append.call_args.kwargs["details"]["denial_code"] == (
        "service_consumer_binding_required"
    )


@pytest.mark.parametrize("attribute", ["service_release_binding_id", "expires_at"])
def test_mismatched_or_expired_service_binding_denies_before_provider(attribute: str) -> None:
    ledger = Mock()
    service = MVTAccessService(
        ledger=ledger,
        now=lambda: NOW,
        attempt_id_factory=lambda: ATTEMPT_ID,
    )
    _, _, _, _, binding = _components()
    assert binding is not None
    setattr(
        binding,
        attribute,
        UUID("00000000-0000-4000-8000-000000000808")
        if attribute == "service_release_binding_id"
        else NOW,
    )

    with pytest.raises(MVTAccessDeniedError) as error:
        _admit(service, binding_override=binding)

    assert error.value.code == "service_consumer_binding_denied"
    assert ledger.append.call_args.kwargs["phase"] == "denied"


def test_policy_role_denial_prevents_admission() -> None:
    ledger = Mock()
    service = MVTAccessService(
        ledger=ledger,
        now=lambda: NOW,
        attempt_id_factory=lambda: ATTEMPT_ID,
    )

    with pytest.raises(MVTAccessDeniedError) as error:
        _admit(service, allowed_roles=("viewer",))

    assert error.value.code == "service_policy_denied"
    assert ledger.append.call_args.kwargs["phase"] == "denied"


def test_admission_audit_failure_withholds_provider_access() -> None:
    ledger = Mock()
    ledger.append.side_effect = SecurityEventLedgerUnavailableError("offline")
    service = MVTAccessService(ledger=ledger, now=lambda: NOW)

    with pytest.raises(MVTAccessUnavailableError, match="admission"):
        _admit(service)


def test_provider_failure_audits_only_the_error_type() -> None:
    ledger = Mock()
    service = MVTAccessService(
        ledger=ledger,
        now=lambda: NOW,
        attempt_id_factory=lambda: ATTEMPT_ID,
    )
    admission = _admit(service)

    service.record_failure(admission, error=OSError("https://tiles.invalid?token=secret"))

    details = ledger.append.call_args.kwargs["details"]
    assert details["provider_error_type"] == "OSError"
    assert "tiles.invalid" not in json.dumps(details)
    assert "secret" not in json.dumps(details)


def test_decision_rejects_tampered_release_scope() -> None:
    definition, release, policy, projection, binding = _components()
    decision = build_mvt_access_decision(
        request_id="request-801",
        subject_context=_subject(),
        service_urn="gda://planning/gis_service/district-features",
        definition=definition,
        release=release,
        service_policy=policy,
        serving_projection=projection,
        service_consumer_binding=binding,
        z=0,
        x=0,
        y=0,
        evaluated_at=NOW,
        expires_at=NOW + timedelta(minutes=5),
    )

    with pytest.raises(ValueError, match="fingerprint"):
        type(decision)(
            **{
                **decision.model_dump(),
                "request": {
                    **decision.request.model_dump(),
                    "service_release_sha256": "f" * 64,
                },
            }
        )
