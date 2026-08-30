"""Contract tests for the canonical metric-definition authority."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest
from pydantic import ValidationError

from data_agent.metric_authority import (
    MetricAggregationSemantics,
    MetricDefinitionActivation,
    MetricDefinitionAuthority,
    MetricDefinitionDocument,
    MetricDefinitionDraft,
    MetricDefinitionVersion,
    MetricMaterializationPolicy,
    MetricMeasureBinding,
    MetricQueryCompilationError,
    MetricSourceBinding,
    MetricSpatialSemantics,
    MetricTimeSemantics,
    require_active_metric,
)

NOW = datetime(2026, 8, 5, 8, tzinfo=UTC)
TENANT = "metric-contract"
METRIC_REF = f"gda://{TENANT}/metric_definition/construction-land-coverage"
VERSION_REF = f"{METRIC_REF}.v1"
SEMANTIC_MODEL_REF = f"gda://{TENANT}/semantic_model/land-use.v3"


def _source(**changes) -> MetricSourceBinding:
    values = {
        "product_urn": f"gda://{TENANT}/data_product/land-use-silver",
        "data_product_version_id": UUID("00000000-0000-4000-8000-000000000101"),
        "version_key": "v3.1.0",
        "output_resource_version_id": UUID(
            "00000000-0000-4000-8000-000000000102"
        ),
    }
    values.update(changes)
    return MetricSourceBinding(**values)


def _document(**changes) -> MetricDefinitionDocument:
    values = {
        "canonical_name": "construction_land_coverage",
        "display_name": "Construction land coverage",
        "description": "Construction land area divided by governed reporting area.",
        "aliases": ("built-up coverage", "construction coverage"),
        "domain": "land_use",
        "semantic_model_version_ref": SEMANTIC_MODEL_REF,
        "formula_expression": "construction_area / reporting_area * 100",
        "value_type": "percentage",
        "unit": "%",
        "aggregation": MetricAggregationSemantics(
            kind="semi_additive",
            non_additive_dimensions=("observation_date",),
        ),
        "time_semantics": MetricTimeSemantics(
            dimension="observation_date",
            kind="snapshot",
            grain="day",
            timezone="Asia/Shanghai",
        ),
        "spatial_semantics": MetricSpatialSemantics(
            dimension="district",
            grain="administrative_unit",
            crs="EPSG:4490",
            relationship="centroid_within",
            area_unit="m2",
        ),
        "dimensions": ("district", "observation_date"),
        "measures": (
            MetricMeasureBinding(
                binding_name="construction_area",
                semantic_model_version_ref=SEMANTIC_MODEL_REF,
                measure_name="construction_area",
            ),
            MetricMeasureBinding(
                binding_name="reporting_area",
                semantic_model_version_ref=SEMANTIC_MODEL_REF,
                measure_name="reporting_area",
            ),
        ),
        "source_bindings": (_source(),),
        "materialization_policy": MetricMaterializationPolicy(
            mode="precompute",
            preferred_tier="gold",
            cache_ttl_seconds=3600,
            maximum_staleness_seconds=86400,
            group_by_dimensions=("district",),
        ),
        "owner_subject": "team:natural-resources",
        "steward_subject": "human:metric-steward",
    }
    values.update(changes)
    return MetricDefinitionDocument(**values)


def _draft(**changes) -> MetricDefinitionDraft:
    values = {
        "tenant_id": TENANT,
        "metric_ref": METRIC_REF,
        "metric_version_ref": VERSION_REF,
        "version": 1,
        "definition": _document(),
        "created_by": "human:platform-operator",
        "creation_reason": "stage canonical natural-resource metric",
        "created_at": NOW,
    }
    values.update(changes)
    return MetricDefinitionDraft(**values)


def _version(**changes) -> MetricDefinitionVersion:
    values = {**_draft().model_dump(), "definition_fingerprint": "a" * 64}
    values.update(changes)
    return MetricDefinitionVersion(**values)


def _activation(**changes) -> MetricDefinitionActivation:
    values = {
        "tenant_id": TENANT,
        "metric_ref": METRIC_REF,
        "canonical_name": "construction_land_coverage",
        "active_version_ref": VERSION_REF,
        "active_fingerprint": "a" * 64,
        "approval_case_ref": (
            f"gda://{TENANT}/approval_case/construction-land-coverage-v1"
        ),
        "activation_version": 1,
        "activated_by": "human:platform-admin",
        "activation_reason": "publish approved metric",
        "activated_at": NOW,
    }
    values.update(changes)
    return MetricDefinitionActivation(**values)


def _database_row(definition: MetricDefinitionVersion) -> dict:
    row = definition.model_dump(mode="python")
    row["definition_document"] = row.pop("definition")
    return row


def test_metric_document_captures_lakehouse_semantic_and_spatial_contract() -> None:
    document = _document()

    assert document.formula_language == "semantic_expression_v1"
    assert document.source_bindings[0].version_key == "v3.1.0"
    assert document.aggregation.non_additive_dimensions == ("observation_date",)
    assert document.spatial_semantics is not None
    assert document.spatial_semantics.crs == "EPSG:4490"
    assert document.materialization_policy.preferred_tier == "gold"


def test_metric_contract_rejects_sql_statements_and_incoherent_snapshot_grain() -> None:
    with pytest.raises(ValidationError, match="cannot contain statements"):
        _document(formula_expression="SUM(area); DROP TABLE facts")
    with pytest.raises(ValidationError, match="snapshot metrics cannot be additive"):
        _document(aggregation=MetricAggregationSemantics(kind="additive"))
    with pytest.raises(ValidationError, match="time dimension"):
        _document(dimensions=("district",))


def test_metric_draft_is_frozen_tenant_bound_and_version_bound() -> None:
    draft = _draft()

    with pytest.raises(ValidationError, match="frozen"):
        draft.version = 2  # type: ignore[misc]
    with pytest.raises(ValidationError, match="identity tenant"):
        _draft(metric_ref="gda://other/metric_definition/construction-land")
    with pytest.raises(ValidationError, match="version reference"):
        _draft(metric_version_ref=f"{METRIC_REF}.v2")
    with pytest.raises(ValidationError, match="data product tenant"):
        _draft(
            definition=_document(
                source_bindings=(
                    _source(product_urn="gda://other/data_product/land-use"),
                )
            )
        )


def test_metric_draft_rejects_self_dependency_and_unversioned_semantic_model() -> None:
    with pytest.raises(ValidationError, match="own metric identity"):
        _draft(definition=_document(dependency_version_refs=(VERSION_REF,)))
    with pytest.raises(ValidationError, match="immutable semantic model version"):
        _document(
            semantic_model_version_ref=(
                f"gda://{TENANT}/semantic_model/land-use"
            )
        )


def test_query_compilation_requires_exact_active_pointer() -> None:
    definition = _version()

    with pytest.raises(MetricQueryCompilationError, match="not active"):
        require_active_metric(definition, None)
    with pytest.raises(MetricQueryCompilationError, match="exact definition"):
        require_active_metric(definition, _activation(active_fingerprint="b" * 64))
    require_active_metric(definition, _activation())


def test_metric_authority_version_list_is_bounded_and_detects_next_page() -> None:
    newest = _version(
        metric_version_ref=f"{METRIC_REF}.v2",
        version=2,
        definition_fingerprint="b" * 64,
    )
    oldest = _version()
    result = MagicMock()
    result.mappings.return_value.all.return_value = [
        _database_row(newest),
        _database_row(oldest),
    ]
    connection = MagicMock()
    connection.execute.return_value = result
    transaction = MagicMock()
    transaction.__enter__.return_value = connection
    transaction.__exit__.return_value = False
    authority = MetricDefinitionAuthority()

    with patch.object(authority, "_transaction", return_value=transaction):
        page = authority.list_versions(TENANT, METRIC_REF, limit=1, offset=3)

    assert page.items == (newest,)
    assert page.offset == 3
    assert page.limit == 1
    assert page.has_more is True
    assert connection.execute.call_args.args[1] == {
        "tenant_id": TENANT,
        "metric_ref": METRIC_REF,
        "row_limit": 2,
        "offset": 3,
    }


def test_metric_routes_expose_governed_lifecycle_and_resolution() -> None:
    from data_agent.api.metric_routes import get_metric_routes

    routes = get_metric_routes()
    operations = {route.operation_id for route in routes}
    paths = {route.path for route in routes}

    assert len(routes) == 21
    assert len(operations) == len(routes)
    assert "platform_stage_metric_definition_version" in operations
    assert "platform_activate_metric_definition_version" in operations
    assert "platform_resolve_active_metric" in operations
    assert "platform_list_metric_observations" in operations
    assert "/api/platform/v1/metric-resolution" in paths


def test_migration_enforces_source_binding_approval_rls_and_least_privilege() -> None:
    sql = (
        Path(__file__).parent
        / "migrations/135_metric_definition_authority.sql"
    ).read_text(encoding="utf-8")

    for marker in (
        "CREATE TABLE IF NOT EXISTS gda_control.metric_definition_version",
        "CREATE TABLE IF NOT EXISTS gda_control.metric_definition_activation",
        "CREATE TABLE IF NOT EXISTS gda_control.metric_definition_event",
        "stage_metric_definition_version",
        "activate_metric_definition_version",
        "metric_definition.activate",
        "DataProductVersion",
        "metric dependencies must be active at their exact versions",
        "ApprovalCase does not authorize this metric activation",
        "FORCE ROW LEVEL SECURITY",
        "reject_immutable_mutation",
        "GRANT SELECT ON gda_control.metric_definition_version",
    ):
        assert marker in sql
    assert "GRANT INSERT ON gda_control.metric_definition_version" not in sql
    assert "GRANT UPDATE ON gda_control.metric_definition_activation" not in sql
    assert "GRANT INSERT ON gda_control.metric_definition_event" not in sql
