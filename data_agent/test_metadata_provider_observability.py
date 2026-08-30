from types import SimpleNamespace

import pytest

import data_agent.metadata_provider_read as provider_read
import data_agent.metadata_provider_search as provider_search
from data_agent.metadata_fabric import MetadataFabricSystem
from data_agent.metadata_provider_read import (
    MetadataProviderReadError,
    MetadataProviderReadService,
    ProviderReadStatus,
)
from data_agent.metadata_provider_search import MetadataProviderSearchService


class _ReadClient:
    system = MetadataFabricSystem.OPENMETADATA

    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error

    def read(self, _binding):
        if self.error is not None:
            raise self.error
        return self.result

    def close(self):
        return None


class _SearchClient:
    def __init__(self, error=None):
        self.error = error

    def search(self, _tenant_id, **_kwargs):
        if self.error is not None:
            raise self.error
        return object()

    def close(self):
        return None


def test_read_metrics_use_provider_status_and_no_identifiers(monkeypatch) -> None:
    events = []
    monkeypatch.setattr(
        provider_read,
        "record_metadata_provider_operation",
        lambda *args: events.append(args),
    )
    result = SimpleNamespace(status=ProviderReadStatus.PRESENT)
    service = MetadataProviderReadService(
        {MetadataFabricSystem.OPENMETADATA: _ReadClient(result=result)}
    )

    service.read(SimpleNamespace(system=MetadataFabricSystem.OPENMETADATA))

    assert events
    provider, operation, outcome, duration = events[-1]
    assert (provider, operation, outcome) == ("openmetadata", "read", "present")
    assert duration >= 0


def test_read_metrics_record_error_without_changing_error_contract(monkeypatch) -> None:
    events = []
    monkeypatch.setattr(
        provider_read,
        "record_metadata_provider_operation",
        lambda *args: events.append(args),
    )
    error = MetadataProviderReadError(
        "provider unavailable",
        code="provider_transport_error",
        provider=MetadataFabricSystem.OPENMETADATA,
        retryable=True,
    )
    service = MetadataProviderReadService(
        {MetadataFabricSystem.OPENMETADATA: _ReadClient(error=error)}
    )

    with pytest.raises(MetadataProviderReadError, match="provider unavailable"):
        service.read(SimpleNamespace(system=MetadataFabricSystem.OPENMETADATA))

    assert events[-1][0:3] == ("openmetadata", "read", "error")


def test_search_metrics_use_bounded_success_and_error_outcomes(monkeypatch) -> None:
    events = []
    monkeypatch.setattr(
        provider_search,
        "record_metadata_provider_operation",
        lambda *args: events.append(args),
    )
    service = MetadataProviderSearchService(
        None, _SearchClient()
    )
    service.search("tenant-a", system=MetadataFabricSystem.OPENMETADATA)
    assert events[-1][0:3] == ("openmetadata", "search", "success")

    failing = MetadataProviderSearchService(
        None,
        _SearchClient(
            MetadataProviderReadError(
                "search unavailable",
                code="provider_search_transport_error",
                provider=MetadataFabricSystem.OPENMETADATA,
            )
        ),
    )
    with pytest.raises(MetadataProviderReadError, match="search unavailable"):
        failing.search("tenant-a", system=MetadataFabricSystem.OPENMETADATA)
    assert events[-1][0:3] == ("openmetadata", "search", "error")
