from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock
from uuid import UUID

import pytest

from data_agent.governed_query_policy_authority import (
    InMemoryGovernedQueryPolicyAuthority,
    build_policy_version,
    build_purpose_registration,
)
from data_agent.governed_query_result_delivery import (
    GovernedQueryResultDeliveryForbidden,
    GovernedQueryResultDeliveryService,
    GovernedQueryResultDeliveryUnavailable,
)
from data_agent.platform_contracts import SubjectType
from data_agent.security_event_ledger import SecurityEventLedgerUnavailableError

NOW = datetime(2026, 8, 19, 12, 0, tzinfo=UTC)
ACCESS_ID = UUID("00000000-0000-4000-8000-000000000501")


def _authority(
    *,
    channel: str,
    adapter_id: str,
    publish_policy: bool = True,
) -> InMemoryGovernedQueryPolicyAuthority:
    authority = InMemoryGovernedQueryPolicyAuthority("tenant-a", clock=lambda: NOW)
    authority.register_purpose(
        build_purpose_registration(
            tenant_id="tenant-a",
            purpose_code="query_result_access",
            description="Consume a governed result",
            registered_by="human:policy-admin",
            registered_at=NOW - timedelta(minutes=2),
        )
    )
    if publish_policy:
        authority.register_policy(
            build_policy_version(
                tenant_id="tenant-a",
                policy_ref=f"policy:{channel}",
                policy_version="v1",
                purpose_code="query_result_access",
                subject_types=(SubjectType.HUMAN,),
                required_roles=("analyst",),
                channels=(channel,),
                adapter_ids=(adapter_id,),
                resource_prefixes=("gda://tenant-a/",),
                valid_from=NOW - timedelta(minutes=1),
                expires_at=NOW + timedelta(days=1),
                published_at=NOW - timedelta(seconds=1),
                published_by="human:policy-admin",
            )
        )
    return authority


def _execute(
    service: GovernedQueryResultDeliveryService,
    operation,
    *,
    channel: str = "map_result",
    adapter_id: str = "gda.map-publication.tile.v1",
    mode: str = "map",
    reader=None,
):
    return service.execute(
        tenant_id="tenant-a",
        actor_subject="human:analyst-a",
        roles=("analyst",),
        channel=channel,
        adapter_id=adapter_id,
        consumption_mode=mode,
        resource_refs=("gda://tenant-a/map_publication/pub-1",),
        request_payload={"publication_id": "pub-1", "z": 3, "x": 4, "y": 2},
        action="map.publication.tile.access",
        operation=operation,
        security_reader=reader,
    )


def test_delivery_records_admission_before_provider_and_outcome_before_return() -> None:
    ledger = Mock()
    service = GovernedQueryResultDeliveryService(
        ledger=ledger,
        now=lambda: NOW,
        access_id_factory=lambda: ACCESS_ID,
    )

    def operation() -> bytes:
        assert ledger.append.call_count == 1
        assert ledger.append.call_args.kwargs["phase"] == "admitted"
        return b"tile"

    result = _execute(
        service,
        operation,
        reader=_authority(
            channel="map_result",
            adapter_id="gda.map-publication.tile.v1",
        ),
    )

    assert result == b"tile"
    assert [call.kwargs["phase"] for call in ledger.append.call_args_list] == [
        "admitted",
        "outcome",
    ]
    assert ledger.append.call_args.kwargs["outcome"] == "success"
    rendered = json.dumps(
        [call.kwargs for call in ledger.append.call_args_list], default=str
    )
    assert "s3://" not in rendered
    assert "file://" not in rendered
    assert "X-Amz" not in rendered


@pytest.mark.parametrize(
    ("channel", "adapter_id", "mode"),
    [
        ("map_result", "gda.map-publication.tile.v1", "map"),
        ("data_product_result", "gda.data-product.download.v1", "download"),
        ("distribution_result", "gda.distribution-package.download.v1", "download"),
        ("report_result", "gda.qc-report.generate.v1", "report"),
    ],
)
def test_cross_exit_policy_deny_never_invokes_provider(
    channel: str,
    adapter_id: str,
    mode: str,
) -> None:
    ledger = Mock()
    operation = Mock()
    service = GovernedQueryResultDeliveryService(ledger=ledger, now=lambda: NOW)

    with pytest.raises(GovernedQueryResultDeliveryForbidden):
        _execute(
            service,
            operation,
            channel=channel,
            adapter_id=adapter_id,
            mode=mode,
            reader=_authority(
                channel=channel,
                adapter_id=adapter_id,
                publish_policy=False,
            ),
        )

    operation.assert_not_called()
    assert ledger.append.call_count == 1
    assert ledger.append.call_args.kwargs["phase"] == "denied"


def test_reader_failure_never_invokes_provider() -> None:
    class BrokenReader:
        tenant_id = "tenant-a"

        def governed_query_security_decision_current(self, request):
            raise RuntimeError("reader unavailable")

    operation = Mock()
    service = GovernedQueryResultDeliveryService(ledger=Mock(), now=lambda: NOW)

    with pytest.raises(GovernedQueryResultDeliveryUnavailable, match="security"):
        _execute(service, operation, reader=BrokenReader())

    operation.assert_not_called()


def test_admission_audit_failure_never_invokes_provider() -> None:
    ledger = Mock()
    ledger.append.side_effect = SecurityEventLedgerUnavailableError("ledger offline")
    operation = Mock()
    service = GovernedQueryResultDeliveryService(ledger=ledger, now=lambda: NOW)

    with pytest.raises(GovernedQueryResultDeliveryUnavailable, match="admission"):
        _execute(
            service,
            operation,
            reader=_authority(
                channel="map_result",
                adapter_id="gda.map-publication.tile.v1",
            ),
        )

    operation.assert_not_called()


def test_provider_failure_records_failure_outcome_without_payload() -> None:
    ledger = Mock()
    service = GovernedQueryResultDeliveryService(ledger=ledger, now=lambda: NOW)

    def operation():
        raise OSError("s3://secret-bucket/private-object")

    with pytest.raises(OSError):
        _execute(
            service,
            operation,
            reader=_authority(
                channel="map_result",
                adapter_id="gda.map-publication.tile.v1",
            ),
        )

    outcome = ledger.append.call_args.kwargs
    assert outcome["phase"] == "outcome"
    assert outcome["outcome"] == "failure"
    assert outcome["details"]["provider_error_type"] == "OSError"
    assert "secret-bucket" not in json.dumps(outcome, default=str)


def test_outcome_audit_failure_withholds_provider_result() -> None:
    ledger = Mock()
    ledger.append.side_effect = [None, SecurityEventLedgerUnavailableError("offline")]
    operation = Mock(return_value=b"private-result")
    service = GovernedQueryResultDeliveryService(ledger=ledger, now=lambda: NOW)

    with pytest.raises(GovernedQueryResultDeliveryUnavailable, match="outcome"):
        _execute(
            service,
            operation,
            reader=_authority(
                channel="map_result",
                adapter_id="gda.map-publication.tile.v1",
            ),
        )

    operation.assert_called_once_with()


def test_optional_development_mode_preserves_existing_provider_call() -> None:
    ledger = Mock()
    operation = Mock(return_value="legacy-result")
    service = GovernedQueryResultDeliveryService(ledger=ledger, now=lambda: NOW)

    assert _execute(service, operation, reader=None) == "legacy-result"
    operation.assert_called_once_with()
    ledger.append.assert_not_called()
