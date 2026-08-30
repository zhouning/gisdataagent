"""Contract tests for the metric-query to business-observation projection."""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock
from urllib.parse import urlencode
from uuid import UUID, uuid5

import pytest
from pydantic import ValidationError

from data_agent.metric_observation import (
    OBSERVATION_PROJECTOR_SUBJECT,
    MetricObservation,
    MetricObservationAuthority,
    MetricObservationBatchProjection,
    MetricObservationPage,
    MetricObservationProjectionSpec,
    MetricObservationQuery,
    MetricObservationResultProjection,
    MetricObservationRowProjection,
    _postgres_jsonb_text,
    metric_observation_fingerprint,
    metric_observation_id,
)

NOW = datetime(2026, 8, 19, 12, 0, tzinfo=UTC)
TENANT = "metric-observation"
RUN_ID = UUID("00000000-0000-4000-8000-000000000501")


def _observation() -> MetricObservation:
    observation_id = uuid5(RUN_ID, "metric-observation:v1")
    value = MetricObservation.model_construct(
        tenant_id=TENANT,
        observation_id=observation_id,
        run_id=RUN_ID,
        query_observation_id=UUID("00000000-0000-4000-8000-000000000502"),
        result_artifact_id=UUID("00000000-0000-4000-8000-000000000503"),
        metric_version_ref=f"gda://{TENANT}/metric_definition/land-area.v1",
        metric_fingerprint="a" * 64,
        projection_version_ref=f"gda://{TENANT}/metric_projection/land-area.v1",
        projection_fingerprint="b" * 64,
        output_resource_version_id=UUID("00000000-0000-4000-8000-000000000504"),
        value=Decimal("123.4500"),
        unit="m2",
        dimensions={"district": "d01", "year": 2026},
        observed_at=NOW,
        recorded_by=OBSERVATION_PROJECTOR_SUBJECT,
        observation_fingerprint="0" * 64,
    )
    fingerprint = metric_observation_fingerprint(value._fingerprint_payload())
    return MetricObservation.model_validate(
        {**value.model_dump(), "observation_fingerprint": fingerprint}
    )


def test_projection_spec_normalizes_decimal_and_dimensions() -> None:
    spec = MetricObservationProjectionSpec(
        value="123.4500",
        dimensions={"year": 2026, "district": "d01"},
        window_start=NOW,
        window_end=NOW,
    )

    assert spec.value == Decimal("123.4500")
    assert tuple(spec.dimensions) == ("district", "year")
    assert spec.window_start == NOW


def test_result_projection_binds_one_scalar_result_row() -> None:
    projection = MetricObservationResultProjection(
        result_sha256="a" * 64,
        projection=MetricObservationProjectionSpec(
            value="25.00",
            dimensions={"district": "d01"},
        ),
    )

    assert projection.result_rows == 1
    assert projection.result_columns == ("metric_value",)
    with pytest.raises(ValidationError):
        MetricObservationResultProjection(
            result_sha256="a" * 64,
            result_columns=(),
            projection=projection.projection,
        )


def test_grouped_projection_requires_a_complete_ordered_batch() -> None:
    rows = tuple(
        MetricObservationRowProjection(
            result_row_index=index,
            result_row_fingerprint=fingerprint * 64,
            projection=MetricObservationProjectionSpec(
                value=value,
                dimensions={"district": district},
            ),
        )
        for index, (fingerprint, district, value) in enumerate(
            (("a", "d01", "25.00"), ("b", "d02", "30.00"))
        )
    )
    batch = MetricObservationBatchProjection(
        result_sha256="c" * 64,
        result_rows=2,
        result_columns=("district_code", "metric_value"),
        projections=rows,
    )

    assert tuple(item.result_row_index for item in batch.projections) == (0, 1)
    with pytest.raises(ValidationError, match="contiguous and ordered"):
        MetricObservationBatchProjection(
            result_sha256="c" * 64,
            result_rows=2,
            result_columns=("district_code", "metric_value"),
            projections=tuple(reversed(rows)),
        )


def test_grouped_observation_ids_are_stable_without_changing_scalar_identity() -> None:
    assert metric_observation_id(RUN_ID) == uuid5(RUN_ID, "metric-observation:v1")
    first = metric_observation_id(
        RUN_ID, result_row_ordinal=0, result_row_fingerprint="a" * 64
    )
    replay = metric_observation_id(
        RUN_ID, result_row_ordinal=0, result_row_fingerprint="a" * 64
    )
    second = metric_observation_id(
        RUN_ID, result_row_ordinal=1, result_row_fingerprint="a" * 64
    )
    assert first == replay
    assert first != second


def test_fingerprint_renderer_matches_postgresql_jsonb_key_order() -> None:
    assert _postgres_jsonb_text(
        {"long": "value", "a": 1, "bb": {"yy": None, "x": True}}
    ) == '{"a": 1, "bb": {"x": true, "yy": null}, "long": "value"}'


@pytest.mark.parametrize(
    "payload",
    (
        {"value": "NaN"},
        {"value": "1", "dimensions": {"District": "d01"}},
        {"value": "1", "window_start": NOW, "window_end": NOW.replace(hour=11)},
        {"value": "1", "dimensions": {"district": {"nested": True}}},
    ),
)
def test_projection_spec_rejects_ambiguous_business_values(payload: dict) -> None:
    with pytest.raises(ValidationError):
        MetricObservationProjectionSpec(**payload)


def test_observation_fingerprint_is_stable_and_detects_tampering() -> None:
    observation = _observation()
    assert observation.observation_fingerprint == metric_observation_fingerprint(
        observation._fingerprint_payload()
    )
    with pytest.raises(ValidationError, match="observation_fingerprint"):
        MetricObservation.model_validate(
            {
                **observation.model_dump(),
                "value": "999",
            }
        )


def test_observation_query_requires_versioned_tenant_consistent_scope() -> None:
    query = MetricObservationQuery(
        metric_version_ref=f"gda://{TENANT}/metric_definition/land-area.v1",
        projection_version_ref=f"gda://{TENANT}/metric_projection/land-area.v2",
        dimensions={"district": "d01"},
        observed_after=NOW,
        observed_before=NOW,
        limit=25,
    )

    assert query.dimensions == {"district": "d01"}
    assert query.observed_after == NOW
    assert query.limit == 25

    with pytest.raises(ValidationError):
        MetricObservationQuery(
            metric_version_ref=f"gda://{TENANT}/metric_definition/land-area",
        )
    with pytest.raises(ValidationError):
        MetricObservationQuery(
            metric_version_ref=f"gda://{TENANT}/metric_definition/land-area.v1",
            projection_version_ref="gda://another/metric_projection/land-area.v1",
        )
    with pytest.raises(ValidationError):
        MetricObservationQuery(
            metric_version_ref=f"gda://{TENANT}/metric_definition/land-area.v1",
            observed_after=NOW,
            observed_before=NOW.replace(hour=11),
        )


def _observation_row(observation: MetricObservation) -> dict:
    row = observation.model_dump(exclude={"schema_id"})
    row["value_canonical"] = observation.canonical_value(row.pop("value"))
    return row


def test_observation_search_enforces_owner_scope_and_bounded_pagination() -> None:
    connection = Mock()
    connection.execute.return_value.mappings.return_value.all.return_value = [
        _observation_row(_observation()),
        _observation_row(_observation()),
    ]
    authority = MetricObservationAuthority()

    @contextmanager
    def transaction(_tenant_id: str):
        yield connection

    authority._transaction = transaction  # type: ignore[method-assign]
    query = MetricObservationQuery(
        metric_version_ref=f"gda://{TENANT}/metric_definition/land-area.v1",
        dimensions={"district": "d01"},
        observed_after=NOW,
        limit=1,
    )

    page = authority.search(
        TENANT,
        query,
        actor_subject="human:analyst",
        role="analyst",
    )

    statement, parameters = connection.execute.call_args.args
    assert "a.admitted_by = :actor_subject" in str(statement)
    assert "o.dimensions @> CAST(:dimensions AS jsonb)" in str(statement)
    assert parameters["actor_subject"] == "human:analyst"
    assert parameters["dimensions"] == '{"district":"d01"}'
    assert parameters["fetch_limit"] == 2
    assert page.count == 1
    assert page.has_more is True


def test_observation_search_operator_has_tenant_wide_scope() -> None:
    connection = Mock()
    connection.execute.return_value.mappings.return_value.all.return_value = []
    authority = MetricObservationAuthority()

    @contextmanager
    def transaction(_tenant_id: str):
        yield connection

    authority._transaction = transaction  # type: ignore[method-assign]
    authority.search(
        TENANT,
        MetricObservationQuery(
            metric_version_ref=f"gda://{TENANT}/metric_definition/land-area.v1"
        ),
        actor_subject="human:operator",
        role="platform_operator",
    )

    statement, parameters = connection.execute.call_args.args
    assert "a.admitted_by = :actor_subject" not in str(statement)
    assert "actor_subject" not in parameters


def test_metric_observation_migration_is_append_only_and_least_privilege() -> None:
    sql = (
        Path(__file__).parent / "migrations/192_metric_observation_projection.sql"
    ).read_text(encoding="utf-8")
    for marker in (
        "CREATE TABLE IF NOT EXISTS gda_control.metric_observation",
        "record_metric_observation",
        "metric query has no successful result evidence",
        "reject_immutable_mutation",
        "FORCE ROW LEVEL SECURITY",
        "GRANT SELECT ON gda_control.metric_observation",
    ):
        assert marker in sql
    assert "GRANT INSERT ON gda_control.metric_observation" not in sql
    assert "DROP TABLE" not in sql


def test_metric_observation_input_validation_is_an_incremental_migration() -> None:
    sql = (
        Path(__file__).parent
        / "migrations/193_metric_observation_input_validation.sql"
    ).read_text(encoding="utf-8")

    assert "RENAME TO record_metric_observation_v192" in sql
    assert "FROM PUBLIC, gda_control_gateway" in sql
    assert "v_dimension_count > 100" in sql
    assert "p_spatial_ref !~" in sql


def test_metric_observation_gateway_acl_repair_is_read_only() -> None:
    sql = (
        Path(__file__).parent
        / "migrations/194_metric_observation_gateway_privilege_repair.sql"
    ).read_text(encoding="utf-8")

    for table in (
        "metric_definition_version",
        "metric_query_execution_admission",
        "metric_query_execution_observation",
    ):
        assert f"GRANT SELECT ON gda_control.{table}" in sql
    assert "GRANT INSERT" not in sql
    assert "GRANT UPDATE" not in sql
    assert "GRANT DELETE" not in sql


def test_grouped_metric_observation_migration_is_atomic_and_least_privilege() -> None:
    sql = (
        Path(__file__).parent
        / "migrations/195_metric_observation_grouped_projection.sql"
    ).read_text(encoding="utf-8")

    for marker in (
        "UNIQUE (tenant_id, run_id, result_row_ordinal)",
        "record_metric_observation_batch",
        "metric observation replay has a partial batch",
        "FOR UPDATE",
        "GRANT EXECUTE ON FUNCTION",
    ):
        assert marker in sql
    assert "GRANT INSERT ON gda_control.metric_observation" not in sql


def test_metric_observation_routes_are_exposed() -> None:
    from data_agent.api.metric_routes import get_metric_routes

    routes = {
        (route.path, tuple(sorted(route.methods or ())))
        for route in get_metric_routes()
    }
    path = "/api/platform/v1/metric-query-runs/{run_id}/observation"
    assert (path, ("GET",)) in routes
    assert (path, ("POST",)) in routes
    assert (
        "/api/platform/v1/metric-definitions/{metric_definition_id}"
        "/versions/{version}/observations",
        ("GET",),
    ) in routes


@pytest.mark.asyncio
async def test_projection_route_delegates_business_value_to_authority(monkeypatch) -> None:
    from data_agent.api import metric_query_routes
    from data_agent.test_metric_query_execution import _request

    authority = Mock()
    authority.project.return_value = _observation()
    monkeypatch.setattr(
        metric_query_routes,
        "_get_user_from_request",
        lambda _request: {
            "identifier": "analyst",
            "metadata": {
                "tenant_id": TENANT,
                "role": "analyst",
                "subject_type": "human",
            },
        },
    )
    monkeypatch.setattr(metric_query_routes, "_metric_observation_authority", lambda: authority)

    response = await metric_query_routes.project_metric_observation(
        _request(
            "POST",
            body={"value": "123.45", "dimensions": {"district": "d01"}},
            path_params={"run_id": str(RUN_ID)},
        )
    )

    assert response.status_code == 201
    assert authority.project.call_args.kwargs == {
        "actor_subject": "human:analyst",
        "role": "analyst",
    }


@pytest.mark.asyncio
async def test_observation_query_route_delegates_typed_filters(monkeypatch) -> None:
    from data_agent.api import metric_query_routes
    from data_agent.test_metric_query_execution import _request

    authority = Mock()
    authority.search.return_value = MetricObservationPage(
        items=(_observation(),),
        count=1,
        offset=0,
        limit=10,
        has_more=False,
    )
    monkeypatch.setattr(
        metric_query_routes,
        "_get_user_from_request",
        lambda _request: {
            "identifier": "analyst",
            "metadata": {
                "tenant_id": TENANT,
                "role": "analyst",
                "subject_type": "human",
            },
        },
    )
    monkeypatch.setattr(
        metric_query_routes, "_metric_observation_authority", lambda: authority
    )
    request = _request(
        "GET",
        path_params={"metric_definition_id": "land-area", "version": "1"},
    )
    request.scope["query_string"] = urlencode(
        {
            "dimensions": json.dumps({"district": "d01"}),
            "observed_after": NOW.isoformat(),
            "limit": "10",
        }
    ).encode()

    response = await metric_query_routes.list_metric_observations(request)

    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    query = authority.search.call_args.args[1]
    assert query.metric_version_ref == (
        f"gda://{TENANT}/metric_definition/land-area.v1"
    )
    assert query.dimensions == {"district": "d01"}
    assert query.observed_after == NOW
    assert authority.search.call_args.kwargs == {
        "actor_subject": "human:analyst",
        "role": "analyst",
    }
    assert json.loads(response.body)["data"]["count"] == 1
