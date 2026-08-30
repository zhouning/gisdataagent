"""Contract tests for the unified metadata catalog read model."""

import json

from types import SimpleNamespace

from starlette.testclient import TestClient
from starlette.applications import Starlette
from starlette.routing import Route

from data_agent.api import metadata_routes
from data_agent import frontend_api


def test_virtual_catalog_projects_semantic_status_and_field_evidence(monkeypatch, tmp_path):
    semantic_path = tmp_path / "semantic.json"
    candidate_path = tmp_path / "candidates.json"
    semantic_path.write_text(json.dumps({
        "table_bindings": [{
            "physical_table": "public.parcels",
            "semantic_coverage_status": "reviewed_business_semantics",
            "execution_eligible": True,
            "retrieval_eligible": True,
            "dictionary_mapping": {"status": "dictionary_exact_supported"},
        }],
        "semantic_assets": [{
            "asset_id": "abu_dhabi.liveability.parcels",
            "review_status": "reviewed_candidate",
            "physical_tables": ["public.parcels"],
            "fields": [{
                "semantic_field": "parcel_id",
                "physical_field": "parcel_id",
                "labels": {"zh": "地块标识"},
                "business_role": "identifier",
            }],
        }],
    }), encoding="utf-8")
    candidate_path.write_text(json.dumps({
        "assets": [{
            "candidate_id": "abu_dhabi.liveability.parcels",
            "physical_table": "public.parcels",
            "asset_state": "published_reviewed_asset",
            "retrieval_eligible": True,
            "published_runtime_asset": {"asset_id": "abu_dhabi.liveability.parcels"},
            "dictionary_alignment": {"status": "dictionary_exact_supported", "matched_field_count": 1},
            "fields": [{
                "physical_field": "parcel_id",
                "data_type": "BIGINT",
                "dictionary_supported": True,
                "published_semantic": {
                    "semantic_field": "parcel_id",
                    "labels": {"zh": "地块标识"},
                    "business_role": "identifier",
                },
            }],
        }]
    }), encoding="utf-8")

    def fake_path(source_key, role):
        return semantic_path if role == "semantic" else candidate_path

    monkeypatch.setattr("data_agent.abu_dhabi_artifact_registry.current_artifact_path", fake_path)
    resources = metadata_routes._attach_semantic_evidence([{
        "qualified_name": "public.parcels",
        "columns": [{"name": "parcel_id", "type": "BIGINT", "nullable": False}],
    }], 12)
    assert resources[0]["semantic_status"] == "reviewed_business_semantics"
    assert resources[0]["semantic_execution_eligible"] is True
    assert resources[0]["semantic_evidence"]["dictionary_alignment_status"] == "dictionary_exact_supported"
    assert resources[0]["columns"][0]["semantic_labels"]["zh"] == "地块标识"
    assert resources[0]["columns"][0]["business_role"] == "identifier"


def test_physical_catalog_projects_column_schema_into_resources():
    item = metadata_routes._physical_catalog_item(
        {
            "id": 9,
            "asset_name": "makani_sync_full",
            "technical_metadata": {
                "storage": {"backend": "postgis", "postgis_table": "public.buildings"},
                "structure": {
                    "column_schema": [
                        {"name": "fid", "type": "integer", "nullable": False},
                        {"name": "geom", "data_type": "geometry"},
                    ],
                    "primary_key": ["fid"],
                },
            },
            "business_metadata": {},
            "operational_metadata": {},
            "lineage_metadata": {},
        },
        include_resources=True,
    )
    assert item["resource_count"] == 1
    resource = item["resources"][0]
    assert resource["qualified_name"] == "public.buildings"
    assert [column["name"] for column in resource["columns"]] == ["fid", "geom"]
    assert resource["primary_key"] == ["fid"]


def test_physical_catalog_projects_multiple_tables():
    item = metadata_routes._physical_catalog_item(
        {
            "id": 10,
            "asset_name": "lakehouse",
            "technical_metadata": {
                "storage": {"backend": "iceberg"},
                "structure": {"tables": [
                    {"schema": "analytics", "name": "roads", "columns": [{"column_name": "id", "dtype": "bigint"}]},
                    {"qualified_name": "analytics.zones", "columns": [{"name": "code", "type": "text"}]},
                ]},
            },
            "business_metadata": {},
            "operational_metadata": {},
            "lineage_metadata": {},
        },
        include_resources=True,
    )
    assert [resource["qualified_name"] for resource in item["resources"]] == ["analytics.roads", "analytics.zones"]
    assert item["resources"][0]["columns"][0]["type"] == "bigint"


def test_virtual_catalog_uses_field_complete_artifact_fallback(monkeypatch):
    monkeypatch.setattr(
        metadata_routes,
        "_artifact_virtual_resources",
        lambda source_id: [
            {
                "schema": "public",
                "name": "parcels",
                "qualified_name": "public.parcels",
                "resource_type": "table",
                "columns": [
                    {"name": "parcel_id", "type": "BIGINT", "nullable": False},
                    {"name": "shape", "type": "geometry(POLYGON,EPSG:4326)", "nullable": True},
                ],
                "primary_key": ["parcel_id"],
                "foreign_keys": [],
                "indexes": [],
                "estimated_record_count": 12,
            }
        ],
    )
    item = metadata_routes._virtual_catalog_item(
        {
            "id": 12,
            "source_name": "Liveability",
            "source_type": "database",
            "query_config": {"database": "liveability_data_20260730"},
        },
        {
            "discovery_snapshot": {
                "database_name": "liveability_data_20260730",
                "resources": [{"schema": "public", "name": "parcels", "columns": []}],
            },
            "profile_snapshot": {},
        },
        include_resources=True,
    )

    assert item["metadata_origin"] == "virtual_source_discovery_with_catalog_field_fallback"
    assert item["resource_count"] == 1
    assert [column["name"] for column in item["resources"][0]["columns"]] == [
        "parcel_id",
        "shape",
    ]
    assert item["resources"][0]["columns"][0]["type"] == "BIGINT"


def test_unified_catalog_adds_governed_artifact_sources_when_registry_is_unavailable(monkeypatch):
    class EmptyManager:
        def search_assets(self, query=None, limit=500):
            return []

    monkeypatch.setattr("data_agent.metadata_manager.MetadataManager", EmptyManager)
    monkeypatch.setattr("data_agent.virtual_sources.list_virtual_sources", lambda *args, **kwargs: [])
    monkeypatch.setattr("data_agent.virtual_sources.get_virtual_source_discovery", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        metadata_routes,
        "_artifact_virtual_source",
        lambda source_id: {
            "id": source_id,
            "source_name": f"database-{source_id}",
            "source_type": "database",
            "query_config": {"database": f"database-{source_id}"},
        },
    )
    monkeypatch.setattr(
        metadata_routes,
        "_artifact_virtual_resources",
        lambda source_id: [
            {
                "schema": "public",
                "name": "example",
                "qualified_name": "public.example",
                "columns": [{"name": "id", "type": "BIGINT", "nullable": False}],
            }
        ],
    )

    items = metadata_routes._unified_catalog_items("analyst", include_resources=True)

    assert [item["source_id"] for item in items] == [12, 13]
    assert all(item["ingestion_mode"] == "virtual_source" for item in items)
    assert all(item["resources"][0]["columns"][0]["name"] == "id" for item in items)


def _client(monkeypatch, items):
    user = SimpleNamespace(identifier="analyst", metadata={"role": "analyst"})
    monkeypatch.setattr(metadata_routes, "_get_user_from_request", lambda request: user)
    monkeypatch.setattr(metadata_routes, "_set_user_context", lambda value: ("analyst", "analyst"))
    monkeypatch.setattr(metadata_routes, "_unified_catalog_items", lambda username, query="": items)
    return TestClient(Starlette(routes=metadata_routes.get_metadata_routes()))


def test_unified_catalog_lists_ingestion_modes(monkeypatch):
    items = [
        {
            "asset_id": "asset:7",
            "asset_name": "roads",
            "display_name": "Roads",
            "ingestion_mode": "physical_lake",
            "source_type": "iceberg",
            "source_rows_persisted": True,
        },
        {
            "asset_id": "virtual-source:12",
            "asset_name": "Liveability",
            "display_name": "liveability_db",
            "ingestion_mode": "virtual_source",
            "source_type": "database",
            "source_rows_persisted": False,
        },
    ]
    response = _client(monkeypatch, items).get("/api/metadata/unified?limit=50")
    assert response.status_code == 200
    payload = response.json()
    assert payload["schema"] == "gda.unified-metadata-catalog.v1"
    assert {item["ingestion_mode"] for item in payload["items"]} == {"physical_lake", "virtual_source"}
    virtual_item = next(item for item in payload["items"] if item["asset_id"] == "virtual-source:12")
    assert virtual_item["source_rows_persisted"] is False


def test_unified_catalog_rejects_invalid_key(monkeypatch):
    response = _client(monkeypatch, []).get("/api/metadata/unified/not-an-asset")
    assert response.status_code == 400


def test_semantic_catalog_keeps_unregistered_tables_and_physical_fields(monkeypatch):
    user = SimpleNamespace(identifier="analyst", metadata={"role": "analyst"})
    monkeypatch.setattr(frontend_api, "_get_user_from_request", lambda request: user)
    monkeypatch.setattr(frontend_api, "_set_user_context", lambda value: ("analyst", "analyst"))
    monkeypatch.setattr(frontend_api, "get_engine", lambda: None)
    monkeypatch.setattr(metadata_routes, "_unified_catalog_items", lambda username, include_resources=False: [
        {
            "asset_id": "virtual-source:7",
            "asset_name": "makani_sync_full",
            "display_name": "Makani",
            "source_id": 7,
            "source_name": "Makani database",
            "source_type": "postgresql",
            "ingestion_mode": "virtual_source",
            "resources": [{
                "qualified_name": "public.parcels",
                "columns": [
                    {"name": "parcel_id", "type": "integer", "nullable": False},
                    {"name": "geom", "type": "geometry", "nullable": True},
                ],
            }],
        },
    ])

    client = TestClient(Starlette(routes=[Route(
        "/api/semantic/catalog", endpoint=frontend_api._api_semantic_catalog, methods=["GET"]
    )]))
    response = client.get("/api/semantic/catalog?limit=10&source_key=source:7")
    assert response.status_code == 200
    payload = response.json()
    assert payload["schema"] == "gda.semantic-catalog.v1"
    assert payload["total"] == 1
    assert payload["tables"][0]["table_name"] == "public.parcels"
    assert [column["column_name"] for column in payload["tables"][0]["columns"]] == ["parcel_id", "geom"]
    assert payload["tables"][0]["ingestion_mode"] == "virtual_source"
