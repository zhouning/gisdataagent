from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID

import pytest

from data_agent.gis_ogc_api_features_access import (
    OGCFeaturesAccessDeniedError,
    OGCFeaturesAccessService,
    OGCFeaturesAccessUnavailableError,
)
from data_agent.platform_contracts import SubjectContext, SubjectType

NOW = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)
IDS = [UUID(f"00000000-0000-4000-8000-0000000008{i:02d}") for i in range(1, 7)]


def _subject(role="analyst"):
    return SubjectContext(
        tenant_id="planning",
        subject_id="analyst-01",
        subject_type=SubjectType.HUMAN,
        roles=(role,),
        purpose="ogc_features_read",
        trace_id="request-801",
    )


def _components(binding=True, action="ogc_features.read"):
    definition = SimpleNamespace(
        service_type="feature",
        service_definition_version_id=IDS[0],
        source_product_urn="gda://planning/data_product/districts",
        source_data_product_version_id=IDS[1],
    )
    release = SimpleNamespace(service_release_binding_id=IDS[2], binding_sha256="a" * 64)
    policy = SimpleNamespace(
        service_policy_binding_id=IDS[3], policy_sha256="b" * 64,
        version_key="v1.0.0", action=action, allowed_roles=("analyst",),
        consumer_binding_required_roles=("analyst",), required_consumer_operation="read",
    )
    grant = None
    if binding:
        grant = SimpleNamespace(
            tenant_id="planning", service_urn="gda://planning/gis_service/district-features",
            service_definition_version_id=IDS[0], service_release_binding_id=IDS[2],
            consumer_ref="human:analyst-01", action="ogc_features.read",
            purpose="ogc_features_read", scope={"operations": ["read"]},
            expires_at=NOW + timedelta(hours=1), service_consumer_binding_id=IDS[4],
            binding_sha256="d" * 64,
        )
    return definition, release, policy, grant


def _admit(service, **kwargs):
    definition, release, policy, binding = _components(**kwargs)
    return service.admit(
        request_id="request-801", subject_context=_subject(),
        service_urn="gda://planning/gis_service/district-features",
        definition=definition, release=release, service_policy=policy,
        service_consumer_binding=binding, collection_id="districts", limit=2,
        bbox=(120.0, 30.0, 122.0, 32.0),
    )


def test_features_admission_seals_independent_action_and_collection():
    ledger = Mock()
    service = OGCFeaturesAccessService(
        ledger=ledger, now=lambda: NOW, attempt_id_factory=lambda: IDS[5]
    )
    admission = _admit(service)
    assert admission.decision.request.action == "ogc_features.read"
    assert admission.decision.request.collection_id == "districts"
    assert ledger.append.call_args.kwargs["action"] == "ogc_features.read"


def test_features_binding_denial_is_audited_before_provider():
    ledger = Mock()
    service = OGCFeaturesAccessService(ledger=ledger, now=lambda: NOW)
    with pytest.raises(OGCFeaturesAccessDeniedError) as error:
        _admit(service, binding=False)
    assert error.value.code == "service_consumer_binding_required"
    assert ledger.append.call_args.kwargs["phase"] == "denied"


def test_features_policy_action_cannot_fall_back_to_mvt():
    ledger = Mock()
    service = OGCFeaturesAccessService(ledger=ledger, now=lambda: NOW)
    with pytest.raises(OGCFeaturesAccessDeniedError) as error:
        _admit(service, action="mvt.read")
    assert error.value.code == "service_policy_action_mismatch"


def test_features_outcome_records_count_and_content_digest():
    ledger = Mock()
    service = OGCFeaturesAccessService(ledger=ledger, now=lambda: NOW)
    admission = _admit(service)
    service.record_success(admission, content=b"features", status_code=200,
                           media_type="application/geo+json", feature_count=2)
    details = ledger.append.call_args.kwargs["details"]
    assert details["feature_count"] == 2
    assert details["response_content_bytes"] == 8
    assert "response_content_sha256" in details


def test_features_admission_audit_failure_withholds_provider_access():
    ledger = Mock()
    ledger.append.side_effect = OGCFeaturesAccessUnavailableError("offline")
    service = OGCFeaturesAccessService(ledger=ledger, now=lambda: NOW)
    with pytest.raises(OGCFeaturesAccessUnavailableError):
        _admit(service)
