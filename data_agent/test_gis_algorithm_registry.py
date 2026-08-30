"""Contract tests for versioned GIS algorithm release governance."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from data_agent.gis_algorithm_registry import (
    DEFAULT_GIS_ALGORITHM_REGISTRY,
    GISAlgorithmBudgetCeiling,
    GISAlgorithmRegistry,
    GISAlgorithmRegistryError,
    GISAlgorithmSpec,
    GISAnalysisOperation,
)
from data_agent.gis_analysis_execution import GISAnalysisPlan
from data_agent.test_gis_analysis_command_consumer import _plan


def test_registry_has_one_active_default_release_per_operation() -> None:
    catalog = DEFAULT_GIS_ALGORITHM_REGISTRY.catalog()

    assert len(catalog.algorithms) == len(GISAnalysisOperation)
    assert catalog.registry_fingerprint == DEFAULT_GIS_ALGORITHM_REGISTRY.fingerprint
    for operation in GISAnalysisOperation:
        release = DEFAULT_GIS_ALGORITHM_REGISTRY.resolve(operation)
        assert release.operation is operation
        assert release.is_default is True
        assert release.deterministic is True
        assert release.read_only is True
        assert len(release.spec_fingerprint) == 64


def test_registry_rejects_duplicate_defaults_for_an_operation() -> None:
    first = DEFAULT_GIS_ALGORITHM_REGISTRY.resolve(GISAnalysisOperation.BUFFER)
    duplicate = GISAlgorithmSpec.release(
        algorithm_id="postgis.another_buffer",
        algorithm_version="gda.postgis-spatial-analysis.v1",
        operation=GISAnalysisOperation.BUFFER,
        title="Another buffer",
        implementation_key="postgis.another_buffer.v1",
        input_roles=("input",),
        budget_ceiling=GISAlgorithmBudgetCeiling(
            max_features=10,
            max_output_bytes=10_000,
            max_duration_ms=1_000,
        ),
        is_default=True,
        released_at=datetime(2026, 8, 13, tzinfo=UTC),
    )

    with pytest.raises(GISAlgorithmRegistryError, match="more than one default"):
        GISAlgorithmRegistry((first, duplicate))


def test_plan_fails_closed_when_algorithm_release_fingerprint_is_tampered() -> None:
    plan = _plan()
    document = plan.model_dump(mode="json")
    document["algorithm_spec_fingerprint"] = "f" * 64

    with pytest.raises(ValidationError, match="exact registered algorithm release"):
        GISAnalysisPlan.model_validate(document)


def test_explicit_registered_algorithm_release_can_be_selected() -> None:
    release = DEFAULT_GIS_ALGORITHM_REGISTRY.resolve(GISAnalysisOperation.CLIP)
    implicit = _plan(GISAnalysisOperation.CLIP)
    explicit = type(implicit).create(
        tenant_id=implicit.tenant_id,
        operation=implicit.operation,
        sources=implicit.sources,
        distance_meters=implicit.distance_meters,
        output_srid=implicit.output_srid,
        budget=implicit.budget,
        security_context_fingerprint=implicit.security_context_fingerprint,
        algorithm_id=release.algorithm_id,
        algorithm_version=release.algorithm_version,
    )

    assert explicit.algorithm_spec_fingerprint == release.spec_fingerprint
    assert explicit.cache_key == implicit.cache_key
