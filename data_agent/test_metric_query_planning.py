"""Contract tests for governed metric projections and query planning."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from data_agent.metric_authority import (
    MetricAggregationSemantics,
    MetricDefinitionDocument,
    MetricDefinitionVersion,
    MetricMaterializationPolicy,
    MetricMeasureBinding,
    MetricSourceBinding,
    MetricSpatialSemantics,
    MetricTimeSemantics,
)
from data_agent.metric_projection_authority import (
    ActiveMetricProjection,
    MetricProjectionActivation,
    MetricProjectionDocument,
    MetricProjectionDraft,
    MetricProjectionVersion,
)
from data_agent.metric_query import (
    MetricDimensionFilter,
    MetricQueryPlanner,
    MetricQueryPlanningError,
    MetricQueryRequest,
    MetricQuerySecurityContext,
    MetricSpatialFilter,
)

NOW = datetime(2026, 8, 5, 8, tzinfo=UTC)
TENANT = "metric-planning"
METRIC_REF = f"gda://{TENANT}/metric_definition/land-area"
METRIC_VERSION_REF = f"{METRIC_REF}.v1"
SEMANTIC_MODEL_REF = f"gda://{TENANT}/semantic_model/land-use.v1"
PRODUCT_URN = f"gda://{TENANT}/data_product/land-use-gold"
PRODUCT_VERSION_ID = UUID("00000000-0000-4000-8000-000000000301")
OUTPUT_VERSION_ID = UUID("00000000-0000-4000-8000-000000000302")


def _metric(
    *,
    aggregation_kind: str = "additive",
    non_additive_dimensions: tuple[str, ...] = (),
    maximum_staleness_seconds: int = 86_400,
) -> MetricDefinitionVersion:
    definition = MetricDefinitionDocument(
        canonical_name="land_area",
        display_name="Land area",
        description="Governed land area for query planning tests.",
        domain="land_use",
        semantic_model_version_ref=SEMANTIC_MODEL_REF,
        formula_expression="land_area",
        value_type="decimal",
        unit="m2",
        aggregation=MetricAggregationSemantics(
            kind=aggregation_kind,
            non_additive_dimensions=non_additive_dimensions,
        ),
        time_semantics=MetricTimeSemantics(
            dimension="observation_date",
            kind="snapshot" if aggregation_kind == "semi_additive" else "periodic",
            grain="day",
        ),
        spatial_semantics=MetricSpatialSemantics(
            dimension="district",
            grain="administrative_unit",
            crs="EPSG:4490",
            relationship="intersects",
            area_unit="m2",
        ),
        dimensions=("district", "observation_date"),
        measures=(
            MetricMeasureBinding(
                binding_name="land_area",
                semantic_model_version_ref=SEMANTIC_MODEL_REF,
                measure_name="land_area",
            ),
        ),
        source_bindings=(
            MetricSourceBinding(
                product_urn=PRODUCT_URN,
                data_product_version_id=PRODUCT_VERSION_ID,
                version_key="v1.0.0",
                output_resource_version_id=OUTPUT_VERSION_ID,
            ),
        ),
        materialization_policy=MetricMaterializationPolicy(
            mode="precompute",
            preferred_tier="serving",
            cache_ttl_seconds=900,
            maximum_staleness_seconds=maximum_staleness_seconds,
            group_by_dimensions=("district", "observation_date"),
        ),
        owner_subject="team:natural-resources",
        steward_subject="human:metric-steward",
    )
    return MetricDefinitionVersion(
        tenant_id=TENANT,
        metric_ref=METRIC_REF,
        metric_version_ref=METRIC_VERSION_REF,
        version=1,
        definition=definition,
        definition_fingerprint="a" * 64,
        created_by="human:metric-owner",
        creation_reason="publish query planning fixture",
        created_at=NOW - timedelta(days=1),
    )


def _projection_document(**changes) -> MetricProjectionDocument:
    values = {
        "metric_version_ref": METRIC_VERSION_REF,
        "metric_fingerprint": "a" * 64,
        "product_urn": PRODUCT_URN,
        "data_product_version_id": PRODUCT_VERSION_ID,
        "output_resource_version_id": OUTPUT_VERSION_ID,
        "source_manifest_sha256": "b" * 64,
        "source_snapshot_ref": "iceberg-snapshot:12345",
        "engine": "postgis",
        "serving_tier": "serving",
        "relation_ref": "postgis://serving/metrics.land_area_daily",
        "value_column": "metric_value",
        "dimension_columns": {
            "district": "district_code",
            "observation_date": "observation_date",
        },
        "projection_dimensions": ("district", "observation_date"),
        "time_column": "observation_date",
        "time_grain": "day",
        "geometry_column": "geom",
        "geometry_srid": 4490,
        "geometry_crs": "EPSG:4490",
        "refreshed_at": NOW - timedelta(minutes=10),
        "estimated_rows": 10_000,
        "p95_latency_ms": 400,
    }
    values.update(changes)
    return MetricProjectionDocument(**values)


def _active_projection(
    projection_id: str = "land-area-serving",
    *,
    fingerprint: str = "c" * 64,
    **document_changes,
) -> ActiveMetricProjection:
    projection_ref = f"gda://{TENANT}/metric_projection/{projection_id}"
    version_ref = f"{projection_ref}.v1"
    version = MetricProjectionVersion(
        tenant_id=TENANT,
        projection_ref=projection_ref,
        projection_version_ref=version_ref,
        version=1,
        projection=_projection_document(**document_changes),
        projection_fingerprint=fingerprint,
        created_by="workload:metric-materializer",
        creation_reason="materialize governed metric",
        created_at=NOW - timedelta(minutes=10),
    )
    activation = MetricProjectionActivation(
        tenant_id=TENANT,
        projection_ref=projection_ref,
        active_version_ref=version_ref,
        active_fingerprint=fingerprint,
        activation_version=1,
        activated_by="human:platform-admin",
        activation_reason="serve verified metric projection",
        activated_at=NOW - timedelta(minutes=9),
    )
    return ActiveMetricProjection(version=version, activation=activation)


def _security(**changes) -> MetricQuerySecurityContext:
    values = {
        "tenant_id": TENANT,
        "subject_ref": "human:analyst",
        "roles": ("analyst",),
        "purpose": "natural_resource_reporting",
    }
    values.update(changes)
    return MetricQuerySecurityContext(**values)


def test_projection_contract_binds_engine_tier_grain_and_exact_versions() -> None:
    document = _projection_document()
    draft = MetricProjectionDraft(
        tenant_id=TENANT,
        projection_ref=f"gda://{TENANT}/metric_projection/land-area-serving",
        projection_version_ref=(
            f"gda://{TENANT}/metric_projection/land-area-serving.v1"
        ),
        version=1,
        projection=document,
        created_by="workload:metric-materializer",
        creation_reason="materialize governed metric",
        created_at=NOW,
    )

    assert draft.projection.engine == "postgis"
    assert draft.projection.projection_dimensions == (
        "district",
        "observation_date",
    )
    with pytest.raises(ValidationError, match="serving tier"):
        _projection_document(serving_tier="batch")
    with pytest.raises(ValidationError, match="atomic"):
        _projection_document(geometry_srid=None)
    with pytest.raises(ValidationError, match="refresh cannot occur"):
        MetricProjectionDraft(
            **{
                **draft.model_dump(),
                "projection": _projection_document(
                    refreshed_at=NOW + timedelta(seconds=1)
                ),
            }
        )
    with pytest.raises(ValidationError, match="share tenant_id"):
        MetricProjectionDraft(
            **{
                **draft.model_dump(),
                "tenant_id": "other",
            }
        )


def test_additive_rollup_prefers_postgis_serving_and_emits_no_sql() -> None:
    postgis = _active_projection(p95_latency_ms=600)
    duckdb = _active_projection(
        "land-area-interactive",
        fingerprint="d" * 64,
        engine="duckdb",
        serving_tier="interactive",
        relation_ref="duckdb://interactive/metrics/land_area_daily",
        p95_latency_ms=50,
    )
    request = MetricQueryRequest(
        metric_name="land_area", group_by_dimensions=("district",)
    )

    plan = MetricQueryPlanner().plan_from(
        request, _security(), _metric(), (duckdb, postgis), now=NOW
    )

    assert plan.engine == "postgis"
    assert plan.execution_mode == "synchronous"
    assert plan.physical_intent.group_by_columns == ("district_code",)
    assert plan.physical_intent.rollup_operator == "sum"
    assert "sql" not in plan.model_dump(mode="json")


def test_semi_and_non_additive_rollups_fail_closed_but_exact_filter_is_safe() -> None:
    projection = _active_projection()
    semi = _metric(
        aggregation_kind="semi_additive",
        non_additive_dimensions=("observation_date",),
    )
    planner = MetricQueryPlanner()

    with pytest.raises(MetricQueryPlanningError) as semi_error:
        planner.plan_from(
            MetricQueryRequest(
                metric_name="land_area", group_by_dimensions=("district",)
            ),
            _security(),
            semi,
            (projection,),
            now=NOW,
        )
    assert "semi_additive_rollup" in " ".join(semi_error.value.rejections)

    exact_date = MetricQueryRequest(
        metric_name="land_area",
        group_by_dimensions=("district",),
        filters=(
            MetricDimensionFilter(
                dimension="observation_date",
                operator="eq",
                values=("2026-08-05",),
            ),
        ),
    )
    exact_plan = planner.plan_from(
        exact_date, _security(), semi, (projection,), now=NOW
    )
    assert exact_plan.physical_intent.rollup_operator == "none"

    non_additive = _metric(aggregation_kind="non_additive")
    with pytest.raises(MetricQueryPlanningError) as non_additive_error:
        planner.plan_from(
            MetricQueryRequest(
                metric_name="land_area", group_by_dimensions=("district",)
            ),
            _security(),
            non_additive,
            (projection,),
            now=NOW,
        )
    assert "non_additive_rollup" in " ".join(
        non_additive_error.value.rejections
    )


def test_stale_and_spatially_incompatible_projections_are_rejected() -> None:
    planner = MetricQueryPlanner()
    stale = _active_projection(refreshed_at=NOW - timedelta(days=2))
    with pytest.raises(MetricQueryPlanningError) as stale_error:
        planner.plan_from(
            MetricQueryRequest(metric_name="land_area"),
            _security(),
            _metric(),
            (stale,),
            now=NOW,
        )
    assert "projection_stale" in " ".join(stale_error.value.rejections)

    no_geometry = _active_projection(
        geometry_column=None,
        geometry_srid=None,
        geometry_crs=None,
    )
    spatial_request = MetricQueryRequest(
        metric_name="land_area",
        group_by_dimensions=("district", "observation_date"),
        spatial_filter=MetricSpatialFilter(
            bbox=(105.0, 28.0, 107.0, 30.0), crs="EPSG:4490"
        ),
    )
    with pytest.raises(MetricQueryPlanningError) as spatial_error:
        planner.plan_from(
            spatial_request,
            _security(),
            _metric(),
            (no_geometry,),
            now=NOW,
        )
    assert "geometry_binding_missing" in " ".join(
        spatial_error.value.rejections
    )


def test_large_scan_routes_to_async_iceberg_spark_and_honors_opt_out() -> None:
    serving = _active_projection(estimated_rows=1_001)
    batch = _active_projection(
        "land-area-batch",
        fingerprint="e" * 64,
        engine="iceberg_spark",
        serving_tier="batch",
        relation_ref="iceberg://lakehouse/gold/land_area_daily",
        estimated_rows=2_000_000,
        p95_latency_ms=30_000,
    )
    planner = MetricQueryPlanner(synchronous_row_limit=1_000)
    request = MetricQueryRequest(
        metric_name="land_area",
        group_by_dimensions=("district", "observation_date"),
    )

    plan = planner.plan_from(
        request, _security(), _metric(), (serving, batch), now=NOW
    )
    assert plan.engine == "iceberg_spark"
    assert plan.execution_mode == "asynchronous"

    with pytest.raises(MetricQueryPlanningError) as error:
        planner.plan_from(
            request.model_copy(update={"allow_async": False}),
            _security(),
            _metric(),
            (serving, batch),
            now=NOW,
        )
    assert "asynchronous_execution_disabled" in " ".join(
        error.value.rejections
    )


def test_cache_key_changes_with_filter_snapshot_projection_and_security() -> None:
    planner = MetricQueryPlanner()
    metric = _metric()
    request = MetricQueryRequest(
        metric_name="land_area",
        group_by_dimensions=("district", "observation_date"),
    )
    projection = _active_projection()
    baseline = planner.plan_from(
        request, _security(), metric, (projection,), now=NOW
    ).cache_key
    filtered = planner.plan_from(
        request.model_copy(
            update={
                "filters": (
                    MetricDimensionFilter(
                        dimension="district", operator="eq", values=("500105",)
                    ),
                )
            }
        ),
        _security(),
        metric,
        (projection,),
        now=NOW,
    ).cache_key
    new_snapshot = planner.plan_from(
        request,
        _security(),
        metric,
        (
            _active_projection(
                fingerprint="f" * 64,
                source_snapshot_ref="iceberg-snapshot:12346",
            ),
        ),
        now=NOW,
    ).cache_key
    other_subject = planner.plan_from(
        request,
        _security(subject_ref="human:other-analyst"),
        metric,
        (projection,),
        now=NOW,
    ).cache_key

    assert len({baseline, filtered, new_snapshot, other_subject}) == 4


def test_metric_projection_migration_enforces_exact_binding_and_least_privilege() -> None:
    sql = (
        Path(__file__).parent
        / "migrations/136_metric_projection_query_planning.sql"
    ).read_text(encoding="utf-8")
    for marker in (
        "CREATE TABLE IF NOT EXISTS gda_control.metric_projection_version",
        "CREATE TABLE IF NOT EXISTS gda_control.metric_projection_activation",
        "CREATE TABLE IF NOT EXISTS gda_control.metric_projection_event",
        "stage_metric_projection_version",
        "activate_metric_projection_version",
        "projection metric must be active at its exact version",
        "exact passed DataProductVersion manifest",
        "FORCE ROW LEVEL SECURITY",
        "reject_immutable_mutation",
        "GRANT SELECT ON gda_control.metric_projection_version",
    ):
        assert marker in sql
    assert "GRANT INSERT ON gda_control.metric_projection_version" not in sql
    assert "GRANT UPDATE ON gda_control.metric_projection_activation" not in sql
    assert "GRANT INSERT ON gda_control.metric_projection_event" not in sql


def test_metric_query_routes_expose_projection_lifecycle_and_planning() -> None:
    from data_agent.api.metric_routes import get_metric_routes

    routes = get_metric_routes()
    operations = {route.operation_id for route in routes}
    paths = {route.path for route in routes}

    assert len(routes) == 21
    assert len(operations) == len(routes)
    assert "platform_stage_metric_projection_version" in operations
    assert "platform_activate_metric_projection_version" in operations
    assert "platform_list_active_metric_projections" in operations
    assert "platform_create_metric_query_plan" in operations
    assert "platform_create_metric_query_run" in operations
    assert "platform_get_metric_query_run" in operations
    assert "platform_create_metric_query_result_access" in operations
    assert "platform_list_metric_observations" in operations
    assert "platform_start_metric_query_run" in operations
    assert "platform_complete_metric_query_run" in operations
    assert "/api/platform/v1/metric-query-plans" in paths
    assert "/api/platform/v1/metric-query-runs" in paths
