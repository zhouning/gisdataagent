"""Contract tests for governed GIS planning and durable admission."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError

from data_agent.gis_analysis_execution import (
    GISAnalysisBudget,
    GISAnalysisCompletionSpec,
    GISAnalysisExecutionObservation,
    GISAnalysisOperation,
    GISAnalysisOutcome,
    GISAnalysisPlan,
    GISAnalysisRequest,
)

NOW = datetime(2026, 8, 13, tzinfo=UTC)


def test_typed_request_rejects_ambiguous_operation_inputs() -> None:
    with pytest.raises(ValidationError, match="buffer requires"):
        GISAnalysisRequest(
            operation=GISAnalysisOperation.BUFFER,
            input_source_name="parcels",
            distance_meters=None,
            output_crs="EPSG:4490",
        )
    with pytest.raises(ValidationError, match="selected together"):
        GISAnalysisRequest(
            operation=GISAnalysisOperation.BUFFER,
            algorithm_id="postgis.st_buffer_geography",
            input_source_name="parcels",
            distance_meters=100,
            output_crs="EPSG:4490",
        )
    with pytest.raises(ValidationError, match="overlay source"):
        GISAnalysisRequest(
            operation=GISAnalysisOperation.CLIP,
            input_source_name="parcels",
            overlay_source_name=None,
            output_crs="EPSG:4490",
        )


def test_plan_budget_and_cache_key_are_immutable_contract_fields() -> None:
    source = {
        "role": "input",
        "semantic_source_name": "parcels",
        "binding_id": UUID("00000000-0000-4000-8000-000000000001"),
        "resource_version_id": UUID("00000000-0000-4000-8000-000000000002"),
        "resource_urn": "gda://tenant-a/source_snapshot/parcels",
        "version_key": "2026-08-13",
        "content_sha256": "a" * 64,
        "authority_version_sha256": "b" * 64,
        "physical_binding_sha256": "c" * 64,
        "physical_relation": "public.parcels",
        "geometry_column": "geom",
        "source_srid": 4490,
    }
    plan = GISAnalysisPlan.create(
        tenant_id="tenant-a",
        operation=GISAnalysisOperation.BUFFER,
        sources=(source,),
        distance_meters=100,
        output_srid=4490,
        budget=GISAnalysisBudget(
            max_features=100,
            max_output_bytes=100_000,
            max_duration_ms=10_000,
        ),
        security_context_fingerprint="d" * 64,
    )
    assert plan.cache_key == plan.model_dump(mode="json")["cache_key"]
    with pytest.raises(ValidationError, match="cache key"):
        type(plan).model_validate(
            plan.model_dump(mode="json") | {"cache_key": "e" * 64}
        )


def test_completion_contract_never_allows_result_and_error_together() -> None:
    with pytest.raises(ValidationError, match="failed GIS analysis"):
        GISAnalysisCompletionSpec(
            start_observation_id=UUID("00000000-0000-4000-8000-000000000003"),
            outcome=GISAnalysisOutcome.FAILED,
            duration_ms=1,
            result_storage_uri="file:///tmp/result.geojson",
            result_media_type="application/geo+json",
            result_sha256="f" * 64,
            result_size_bytes=10,
            error_code="provider_failed",
            error_message="provider failed",
            observed_at=NOW,
        )


def test_observation_requires_exactly_one_result_or_error() -> None:
    with pytest.raises(ValidationError, match="exactly one result"):
        GISAnalysisExecutionObservation(
            tenant_id="tenant-a",
            analysis_observation_id=UUID("00000000-0000-4000-8000-000000000004"),
            run_id=UUID("00000000-0000-4000-8000-000000000005"),
            attempt_no=1,
            start_observation_id=UUID("00000000-0000-4000-8000-000000000006"),
            terminal_observation_id=UUID("00000000-0000-4000-8000-000000000007"),
            outcome=GISAnalysisOutcome.SUCCEEDED,
            features_returned=0,
            bytes_scanned=0,
            duration_ms=0,
            observed_at=NOW,
            recorded_by="workload:gis-analysis-postgis",
        )
