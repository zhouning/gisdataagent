"""Tests for certification-driven schema drift observation."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from data_agent.source_connector_governance import (
    CertificationStatus,
    DiscoveredResource,
    DiscoverySnapshot,
    ProfileField,
)
from data_agent.source_schema_drift_observer import observe_certification_schema_drift


def _snapshot(*, field_type: str = "string", token: str = "v1") -> DiscoverySnapshot:
    return DiscoverySnapshot(
        provider="STAC",
        provider_version="1.0.0",
        resources=(
            DiscoveredResource(
                name="chongqing-osm-roads",
                resource_type="collection",
                fields=(
                    ProfileField(
                        name="properties.road_class",
                        data_type=field_type,
                        nullable=False,
                    ),
                ),
                provider_version_token=token,
            ),
        ),
    )


def _report(snapshot: DiscoverySnapshot, **changes):
    values = {
        "status": CertificationStatus.PASSED,
        "discovery": snapshot,
        "source_id": "chongqing-osm-stac",
        "source_definition_fingerprint": "a" * 64,
        "connector_id": "stac",
        "provider": "STAC",
        "certified_at": datetime(2026, 8, 1, tzinfo=UTC),
    }
    values.update(changes)
    return SimpleNamespace(**values)


class _Ledger:
    def __init__(self) -> None:
        self.calls = []

    def record(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(created=True)


def test_observer_records_breaking_drift_with_certification_binding() -> None:
    ledger = _Ledger()
    observation = observe_certification_schema_drift(
        tenant_id="tenant-a",
        previous=_report(_snapshot()),
        current=_report(_snapshot(field_type="integer", token="v2")),
        ledger=ledger,
        detected_by="workload:source-certifier",
    )

    assert observation.event is not None
    assert observation.event.breaking
    assert observation.write_result.created
    assert ledger.calls[0]["source_definition_fingerprint"] == "a" * 64
    assert ledger.calls[0]["event"] == observation.event


def test_observer_ignores_content_version_churn_when_schema_is_stable() -> None:
    ledger = _Ledger()
    observation = observe_certification_schema_drift(
        tenant_id="tenant-a",
        previous=_report(_snapshot(token="etag-a")),
        current=_report(_snapshot(token="etag-b")),
        ledger=ledger,
        detected_by="workload:source-certifier",
    )

    assert observation.event is None
    assert observation.write_result is None
    assert ledger.calls == []


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"status": CertificationStatus.FAILED}, "two passed certifications"),
        ({"source_id": "another-source"}, "cross source identities"),
        ({"source_definition_fingerprint": "b" * 64}, "immutable source definition"),
        ({"connector_id": "object_storage"}, "cross connector identities"),
        ({"provider": "another-provider"}, "cross provider identities"),
    ],
)
def test_observer_rejects_unbound_certification_pairs(changes, message) -> None:
    with pytest.raises(ValueError, match=message):
        observe_certification_schema_drift(
            tenant_id="tenant-a",
            previous=_report(_snapshot()),
            current=_report(_snapshot(field_type="integer"), **changes),
            ledger=_Ledger(),
            detected_by="workload:source-certifier",
        )
