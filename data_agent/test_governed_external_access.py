from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock
from uuid import UUID

import pytest

from data_agent.governed_external_access import (
    GovernedExternalAccessForbidden,
    GovernedExternalAccessService,
    GovernedExternalAccessUnavailable,
)
from data_agent.governed_query_policy_authority import (
    InMemoryGovernedQueryPolicyAuthority,
    build_policy_version,
    build_purpose_registration,
)
from data_agent.platform_contracts import SubjectType
from data_agent.security_event_ledger import SecurityEventLedgerUnavailableError

NOW = datetime(2026, 8, 19, 14, 0, tzinfo=UTC)
ACCESS_ID = UUID("00000000-0000-4000-8000-000000000701")


def _authority(
    *,
    channel: str,
    adapter_id: str,
    subject_type: SubjectType,
    resource_prefix: str,
    publish_policy: bool = True,
) -> InMemoryGovernedQueryPolicyAuthority:
    authority = InMemoryGovernedQueryPolicyAuthority(
        "tenant-a", clock=lambda: NOW
    )
    authority.register_purpose(
        build_purpose_registration(
            tenant_id="tenant-a",
            purpose_code="external_access",
            description="Bounded non-result external access",
            registered_by="human:policy-admin",
            registered_at=NOW - timedelta(minutes=2),
        )
    )
    if publish_policy:
        authority.register_policy(
            build_policy_version(
                tenant_id="tenant-a",
                policy_ref=f"policy:{channel}:{adapter_id}",
                policy_version="v1",
                purpose_code="external_access",
                subject_types=(subject_type,),
                required_roles=("analyst",),
                channels=(channel,),
                adapter_ids=(adapter_id,),
                resource_prefixes=(resource_prefix,),
                valid_from=NOW - timedelta(minutes=1),
                expires_at=NOW + timedelta(days=1),
                published_at=NOW - timedelta(seconds=1),
                published_by="human:policy-admin",
            )
        )
    return authority


def _execute(
    service: GovernedExternalAccessService,
    operation,
    *,
    access_mode: str = "retrieve",
    channel: str = "rag",
    adapter_id: str = "gda.rag.immutable-document.v1",
    actor_subject: str = "human:analyst-a",
    resource_ref: str = "kb:7/documents/11@sha256-" + "a" * 64,
    reader=None,
):
    return service.execute(
        tenant_id="tenant-a",
        actor_subject=actor_subject,
        roles=("analyst",),
        channel=channel,
        adapter_id=adapter_id,
        access_mode=access_mode,
        resource_refs=(resource_ref,),
        request_payload={
            "query": "private planning question",
            "credential": "Bearer should-not-be-audited",
        },
        action="external.access.test",
        operation=operation,
        security_reader=reader,
    )


def test_records_admission_before_external_call_and_outcome_before_return() -> None:
    ledger = Mock()
    service = GovernedExternalAccessService(
        ledger=ledger,
        now=lambda: NOW,
        access_id_factory=lambda: ACCESS_ID,
    )

    def operation() -> dict[str, str]:
        assert ledger.append.call_count == 1
        assert ledger.append.call_args.kwargs["phase"] == "admitted"
        return {"content": "private provider payload"}

    result = _execute(
        service,
        operation,
        reader=_authority(
            channel="rag",
            adapter_id="gda.rag.immutable-document.v1",
            subject_type=SubjectType.HUMAN,
            resource_prefix="kb:7/documents/",
        ),
    )

    assert result == {"content": "private provider payload"}
    assert [call.kwargs["phase"] for call in ledger.append.call_args_list] == [
        "admitted",
        "outcome",
    ]
    assert ledger.append.call_args.kwargs["outcome"] == "success"
    rendered = json.dumps(
        [call.kwargs for call in ledger.append.call_args_list], default=str
    )
    assert "private planning question" not in rendered
    assert "Bearer should-not-be-audited" not in rendered
    assert "private provider payload" not in rendered


@pytest.mark.parametrize(
    ("access_mode", "channel", "adapter_id", "actor_subject", "subject_type", "resource"),
    [
        (
            "retrieve",
            "rag",
            "gda.rag.immutable-document.v1",
            "human:analyst-a",
            SubjectType.HUMAN,
            "kb:7/documents/11@sha256-" + "a" * 64,
        ),
        (
            "invoke",
            "mcp",
            "gda.mcp.remote-tool.v1",
            "agent:gis-agent",
            SubjectType.AGENT,
            "mcp:arcpy/tools/buffer",
        ),
        (
            "acquire",
            "observation_provider",
            "gda.smartmakani.arcgis.v1",
            "workload:smartmakani-acquisition",
            SubjectType.WORKLOAD,
            "provider:smartmakani/layers/pipelines",
        ),
    ],
)
def test_cross_channel_policy_deny_never_invokes_external_operation(
    access_mode: str,
    channel: str,
    adapter_id: str,
    actor_subject: str,
    subject_type: SubjectType,
    resource: str,
) -> None:
    ledger = Mock()
    operation = Mock()
    service = GovernedExternalAccessService(ledger=ledger, now=lambda: NOW)

    with pytest.raises(GovernedExternalAccessForbidden):
        _execute(
            service,
            operation,
            access_mode=access_mode,
            channel=channel,
            adapter_id=adapter_id,
            actor_subject=actor_subject,
            resource_ref=resource,
            reader=_authority(
                channel=channel,
                adapter_id=adapter_id,
                subject_type=subject_type,
                resource_prefix=resource,
                publish_policy=False,
            ),
        )

    operation.assert_not_called()
    assert ledger.append.call_count == 1
    assert ledger.append.call_args.kwargs["phase"] == "denied"


def test_reader_failure_never_invokes_external_operation() -> None:
    class BrokenReader:
        tenant_id = "tenant-a"

        def governed_query_security_decision_current(self, request):
            raise RuntimeError("reader offline")

    operation = Mock()
    service = GovernedExternalAccessService(ledger=Mock(), now=lambda: NOW)

    with pytest.raises(GovernedExternalAccessUnavailable, match="security"):
        _execute(service, operation, reader=BrokenReader())

    operation.assert_not_called()


def test_admission_audit_failure_never_invokes_external_operation() -> None:
    ledger = Mock()
    ledger.append.side_effect = SecurityEventLedgerUnavailableError("offline")
    operation = Mock()
    service = GovernedExternalAccessService(ledger=ledger, now=lambda: NOW)

    with pytest.raises(GovernedExternalAccessUnavailable, match="admission"):
        _execute(
            service,
            operation,
            reader=_authority(
                channel="rag",
                adapter_id="gda.rag.immutable-document.v1",
                subject_type=SubjectType.HUMAN,
                resource_prefix="kb:7/documents/",
            ),
        )

    operation.assert_not_called()


def test_external_failure_records_type_without_error_message() -> None:
    ledger = Mock()
    service = GovernedExternalAccessService(ledger=ledger, now=lambda: NOW)

    def operation():
        raise OSError("https://provider.invalid?token=private")

    with pytest.raises(OSError):
        _execute(
            service,
            operation,
            reader=_authority(
                channel="rag",
                adapter_id="gda.rag.immutable-document.v1",
                subject_type=SubjectType.HUMAN,
                resource_prefix="kb:7/documents/",
            ),
        )

    outcome = ledger.append.call_args.kwargs
    assert outcome["phase"] == "outcome"
    assert outcome["outcome"] == "failure"
    assert outcome["details"]["external_error_type"] == "OSError"
    assert "provider.invalid" not in json.dumps(outcome, default=str)


def test_outcome_audit_failure_withholds_external_result() -> None:
    ledger = Mock()
    ledger.append.side_effect = [None, SecurityEventLedgerUnavailableError("offline")]
    operation = Mock(return_value={"secret": "result"})
    service = GovernedExternalAccessService(ledger=ledger, now=lambda: NOW)

    with pytest.raises(GovernedExternalAccessUnavailable, match="outcome"):
        _execute(
            service,
            operation,
            reader=_authority(
                channel="rag",
                adapter_id="gda.rag.immutable-document.v1",
                subject_type=SubjectType.HUMAN,
                resource_prefix="kb:7/documents/",
            ),
        )

    operation.assert_called_once_with()


def test_async_external_access_has_the_same_audit_order() -> None:
    ledger = Mock()
    service = GovernedExternalAccessService(ledger=ledger, now=lambda: NOW)

    async def operation() -> str:
        assert ledger.append.call_args.kwargs["phase"] == "admitted"
        return "tool-result"

    result = asyncio.run(
        service.execute_async(
            tenant_id="tenant-a",
            actor_subject="agent:gis-agent",
            roles=("analyst",),
            channel="mcp",
            adapter_id="gda.mcp.remote-tool.v1",
            access_mode="invoke",
            resource_refs=("mcp:arcpy/tools/buffer",),
            request_payload={"arguments": {"distance": 100}},
            action="mcp.remote-tool.invoke",
            operation=operation,
            security_reader=_authority(
                channel="mcp",
                adapter_id="gda.mcp.remote-tool.v1",
                subject_type=SubjectType.AGENT,
                resource_prefix="mcp:arcpy/tools/",
            ),
        )
    )

    assert result == "tool-result"
    assert [call.kwargs["phase"] for call in ledger.append.call_args_list] == [
        "admitted",
        "outcome",
    ]


def test_optional_development_mode_preserves_sync_and_async_operations() -> None:
    ledger = Mock()
    service = GovernedExternalAccessService(ledger=ledger, now=lambda: NOW)
    sync_operation = Mock(return_value="legacy-sync")

    assert _execute(service, sync_operation, reader=None) == "legacy-sync"

    async def async_operation() -> str:
        return "legacy-async"

    result = asyncio.run(
        service.execute_async(
            tenant_id="",
            actor_subject="workload:local-dev",
            roles=("dataops",),
            channel="observation_provider",
            adapter_id="gda.smartmakani.arcgis.v1",
            access_mode="acquire",
            resource_refs=("provider:smartmakani/layers/pipelines",),
            request_payload={},
            action="observation.provider.acquire",
            operation=async_operation,
            security_reader=None,
        )
    )
    assert result == "legacy-async"
    ledger.append.assert_not_called()
