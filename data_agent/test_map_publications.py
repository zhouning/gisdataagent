from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from data_agent.map_publications import (
    MapPublicationForbidden,
    MapPublicationMaterializationRequired,
    MapPublicationService,
)
from data_agent.user_context import current_user_id, current_user_role


def _service_with_asset(asset: dict) -> MapPublicationService:
    engine = MagicMock()
    service = MapPublicationService(engine=engine)
    service._load_asset = MagicMock(return_value=asset)
    return service


def test_publish_requires_asset_owner_or_admin():
    service = _service_with_asset(
        {
            "owner_username": "asset-owner",
            "technical_metadata": {},
        }
    )
    user_token = current_user_id.set("other-user")
    role_token = current_user_role.set("analyst")
    try:
        with pytest.raises(MapPublicationForbidden, match="owner or an admin"):
            service.publish(7)
    finally:
        current_user_id.reset(user_token)
        current_user_role.reset(role_token)


def test_lake_asset_without_postgis_projection_requires_materialization():
    service = _service_with_asset(
        {
            "owner_username": "asset-owner",
            "technical_metadata": {
                "storage": {"lakehouse_uri": "s3://lake/asset/snapshot=1"}
            },
        }
    )
    user_token = current_user_id.set("asset-owner")
    role_token = current_user_role.set("analyst")
    try:
        with pytest.raises(
            MapPublicationMaterializationRequired,
            match="scheduled PostGIS serving projection",
        ):
            service.publish(7)
    finally:
        current_user_id.reset(user_token)
        current_user_role.reset(role_token)


def test_default_tile_properties_filter_sensitive_fields():
    columns = [
        {"name": "OBJECTID", "data_type": "integer"},
        {"name": "NAMEENGLISH", "data_type": "text"},
        {"name": "BUILDINGHEIGHT", "data_type": "double precision"},
        {"name": "owner_email", "data_type": "text"},
        {"name": "api_token", "data_type": "text"},
    ]

    properties = MapPublicationService._choose_properties(
        columns,
        "OBJECTID",
        requested=None,
    )

    assert properties[:2] == ["NAMEENGLISH", "BUILDINGHEIGHT"]
    assert "owner_email" not in properties
    assert "api_token" not in properties


def test_public_layer_contract_hides_physical_postgis_reference():
    publication_id = uuid4()
    serialized = MapPublicationService._serialize(
        {
            "publication_id": publication_id,
            "publication_run_id": uuid4(),
            "asset_id": 7,
            "asset_name": "dmt-buildings",
            "display_name": "DMT Buildings",
            "source_schema": "public",
            "source_table": "dmt_building_survey_buildings",
            "geometry_column": "geom",
            "property_allowlist": ["NAMEENGLISH"],
            "data_extent": {},
            "display_extent": {
                "minx": 53.0,
                "miny": 23.0,
                "maxx": 55.0,
                "maxy": 25.0,
            },
            "style_config": {"fillColor": "#0f766e"},
            "min_zoom": 9,
            "max_zoom": 20,
            "created_at": None,
            "published_at": None,
            "updated_at": None,
            "retired_at": None,
        }
    )

    assert "source_schema" not in serialized
    assert "source_table" not in serialized
    assert "geometry_column" not in serialized
    assert serialized["layer"]["source_layer"] == "map_publication"
    assert serialized["layer"]["center"] == [24.0, 54.0]
    assert "dmt_building_survey_buildings" not in json.dumps(serialized)


def test_idempotent_publish_retries_platform_lineage_bridge():
    publication_id = uuid4()
    service = _service_with_asset(
        {
            "owner_username": "asset-owner",
            "technical_metadata": {
                "storage": {"postgis_table": "public.dmt_buildings"},
                "structure": {"feature_count": 1000},
            },
            "operational_metadata": {"version": {"version": 1}},
            "ingestion_tenant_id": "local-dev",
        }
    )
    service._source_metadata = MagicMock(
        return_value={
            "geometry": {"f_geometry_column": "geom", "type": "MULTIPOLYGON", "srid": 4326},
            "columns": [
                {"name": "OBJECTID", "data_type": "integer"},
                {"name": "NAMEENGLISH", "data_type": "text"},
            ],
        }
    )
    existing = MagicMock()
    existing._mapping = {
        "publication_id": publication_id,
        "publication_run_id": uuid4(),
        "tenant_id": "local-dev",
        "asset_id": 7,
        "asset_version": 1,
        "asset_name": "dmt-buildings",
        "display_name": "DMT Buildings",
        "source_content_sha256": "a" * 64,
        "config_sha256": "b" * 64,
        "source_schema": "public",
        "source_table": "dmt_buildings",
        "geometry_column": "geom",
        "property_allowlist": ["NAMEENGLISH"],
        "data_extent": {},
        "display_extent": {"minx": 53, "miny": 23, "maxx": 55, "maxy": 25},
        "style_config": {"fillColor": "#0f766e"},
        "min_zoom": 0,
        "max_zoom": 20,
        "created_at": None,
        "published_at": None,
        "updated_at": None,
        "retired_at": None,
    }
    connection = service.engine.begin.return_value.__enter__.return_value
    connection.execute.return_value.one_or_none.return_value = existing
    service._publish_platform_lineage = MagicMock(return_value={"status": "recorded"})
    user_token = current_user_id.set("asset-owner")
    role_token = current_user_role.set("analyst")
    try:
        result = service.publish(7)
    finally:
        current_user_id.reset(user_token)
        current_user_role.reset(role_token)

    service._publish_platform_lineage.assert_called_once()
    assert result["publication_id"] == str(publication_id)
    assert result["platform_lineage"] == {"status": "recorded"}


def test_platform_lineage_retry_reuses_existing_target_timestamp():
    existing_timestamp = datetime(2026, 8, 5, 1, 1, 41, tzinfo=UTC)
    gateway = MagicMock()
    gateway.get_resource_version.side_effect = [
        MagicMock(),
        MagicMock(created_at=existing_timestamp),
    ]
    publication = {
        "tenant_id": "local-dev",
        "asset_id": 7,
        "asset_version": 1,
        "asset_name": "DMT Building Survey Buildings ODS",
        "publication_id": str(uuid4()),
        "source_content_sha256": "a" * 64,
        "config_sha256": "b" * 64,
        "created_by": "admin",
        "published_at": datetime(2026, 8, 5, 0, 0, tzinfo=UTC),
    }

    with patch("data_agent.platform_gateway.PlatformGateway", return_value=gateway):
        result = MapPublicationService._publish_platform_lineage(publication)

    target_version = gateway.register_resource_version.call_args.args[0]
    lineage_event = gateway.record_lineage.call_args.args[0]
    assert target_version.created_at == existing_timestamp
    assert lineage_event.occurred_at == existing_timestamp
    assert result["status"] == "recorded"
