"""Tests for the metadata management system."""
import json
import pytest
from unittest.mock import patch, MagicMock
from data_agent.user_context import current_user_id

# ---- MetadataExtractor ----

class TestMetadataExtractor:
    def test_extract_from_file_unknown_format(self, tmp_path):
        from data_agent.metadata_extractor import MetadataExtractor
        f = tmp_path / "test.csv"
        f.write_text("a,b\n1,2\n")
        ext = MetadataExtractor()
        meta = ext.extract_from_file(str(f))
        assert meta["technical"]["storage"]["format"] == "csv"
        assert meta["technical"]["storage"]["size_bytes"] > 0
        assert meta["operational"]["source"]["type"] == "uploaded"

    def test_extract_spatial_metadata_exception(self):
        from data_agent.metadata_extractor import MetadataExtractor
        ext = MetadataExtractor()
        result = ext.extract_spatial_metadata("/nonexistent/file.shp")
        assert result == {"spatial": {}}

    def test_extract_schema_metadata_exception(self):
        from data_agent.metadata_extractor import MetadataExtractor
        ext = MetadataExtractor()
        result = ext.extract_schema_metadata("/nonexistent/file.shp")
        assert result == {"structure": {}}

    def test_extract_raster_metadata_exception(self):
        from data_agent.metadata_extractor import MetadataExtractor
        ext = MetadataExtractor()
        result = ext._extract_raster_metadata("/nonexistent/file.tif")
        assert result == {"spatial": {}, "structure": {}}


# ---- MetadataEnricher ----

class TestMetadataEnricher:
    def test_enrich_geography_chongqing(self):
        from data_agent.metadata_enricher import MetadataEnricher
        enricher = MetadataEnricher()
        meta = {
            "technical": {
                "spatial": {
                    "extent": {"minx": 106.5, "miny": 29.5, "maxx": 107.0, "maxy": 30.0}
                }
            }
        }
        result = enricher.enrich_geography(meta)
        regions = result["business"]["geography"]["region_tags"]
        assert "重庆市" in regions
        assert "西南" in result["business"]["geography"]["area_tags"]

    def test_enrich_geography_no_extent(self):
        from data_agent.metadata_enricher import MetadataEnricher
        enricher = MetadataEnricher()
        meta = {"technical": {}}
        result = enricher.enrich_geography(meta)
        assert "business" not in result or "geography" not in result.get("business", {})

    def test_enrich_geography_shanghai(self):
        from data_agent.metadata_enricher import MetadataEnricher
        enricher = MetadataEnricher()
        meta = {
            "technical": {
                "spatial": {
                    "extent": {"minx": 121.0, "miny": 31.0, "maxx": 121.5, "maxy": 31.5}
                }
            }
        }
        result = enricher.enrich_geography(meta)
        regions = result["business"]["geography"]["region_tags"]
        assert "上海市" in regions

    def test_enrich_domain_landuse(self):
        from data_agent.metadata_enricher import MetadataEnricher
        enricher = MetadataEnricher()
        meta = {}
        result = enricher.enrich_domain(meta, "重庆市_土地利用_2023.shp")
        assert result["business"]["classification"]["domain"] == "LAND_USE"

    def test_enrich_domain_elevation(self):
        from data_agent.metadata_enricher import MetadataEnricher
        enricher = MetadataEnricher()
        meta = {}
        result = enricher.enrich_domain(meta, "dem_30m.tif")
        assert result["business"]["classification"]["domain"] == "ELEVATION"

    def test_enrich_domain_no_match(self):
        from data_agent.metadata_enricher import MetadataEnricher
        enricher = MetadataEnricher()
        meta = {}
        result = enricher.enrich_domain(meta, "random_file.shp")
        assert "business" not in result or "classification" not in result.get("business", {})

    def test_enrich_quality_full(self):
        from data_agent.metadata_enricher import MetadataEnricher
        enricher = MetadataEnricher()
        meta = {
            "technical": {
                "spatial": {"crs": "EPSG:4326", "extent": {"minx": 1}},
                "structure": {"columns": [{"name": "a", "type": "int"}]}
            }
        }
        result = enricher.enrich_quality(meta)
        score = result["business"]["quality"]["completeness_score"]
        assert score == 1.0

    def test_enrich_quality_minimal(self):
        from data_agent.metadata_enricher import MetadataEnricher
        enricher = MetadataEnricher()
        meta = {"technical": {}}
        result = enricher.enrich_quality(meta)
        score = result["business"]["quality"]["completeness_score"]
        assert score == 0.5


# ---- MetadataManager ----

class TestMetadataManager:
    @patch("data_agent.metadata_manager.get_engine")
    def test_register_asset(self, mock_engine):
        from data_agent.metadata_manager import MetadataManager
        current_user_id.set("test_user")
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value.fetchone.return_value = (42,)
        mock_engine.return_value.connect.return_value = mock_conn

        mgr = MetadataManager()
        asset_id = mgr.register_asset("test.shp", {"storage": {"path": "/tmp/test.shp"}})
        assert asset_id == 42
        mock_conn.execute.assert_called_once()
        mock_conn.commit.assert_called_once()

    @patch("data_agent.metadata_manager.get_engine")
    def test_update_metadata_no_updates(self, mock_engine):
        from data_agent.metadata_manager import MetadataManager
        mgr = MetadataManager()
        result = mgr.update_metadata(1)
        assert result is False

    @patch("data_agent.metadata_manager.get_engine")
    def test_update_metadata_with_technical(self, mock_engine):
        from data_agent.metadata_manager import MetadataManager
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_engine.return_value.connect.return_value = mock_conn

        mgr = MetadataManager()
        result = mgr.update_metadata(1, technical={"spatial": {"crs": "EPSG:4326"}})
        assert result is True
        mock_conn.commit.assert_called_once()

    @patch("data_agent.metadata_manager.get_engine")
    def test_get_metadata_not_found(self, mock_engine):
        from data_agent.metadata_manager import MetadataManager
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value.fetchone.return_value = None
        mock_engine.return_value.connect.return_value = mock_conn

        mgr = MetadataManager()
        result = mgr.get_metadata(1)
        assert result is None

    @patch("data_agent.metadata_manager.get_engine")
    def test_get_metadata_all_layers(self, mock_engine):
        from data_agent.metadata_manager import MetadataManager
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_row = MagicMock()
        mock_row.__getitem__ = lambda self, i: [{"spatial": {}}, {}, {}, {}][i]
        mock_conn.execute.return_value.fetchone.return_value = mock_row
        mock_engine.return_value.connect.return_value = mock_conn

        mgr = MetadataManager()
        result = mgr.get_metadata(1)
        assert result is not None
        assert "technical" in result

    @patch("data_agent.metadata_manager.get_engine")
    def test_get_lineage_not_found(self, mock_engine):
        from data_agent.metadata_manager import MetadataManager
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value.fetchone.return_value = None
        mock_engine.return_value.connect.return_value = mock_conn

        mgr = MetadataManager()
        result = mgr.get_lineage(999)
        assert result == {}


# ---- MetadataIntegration ----

class TestMetadataIntegration:
    def test_register_uploaded_file_success(self, tmp_path):
        from data_agent.metadata_integration import register_uploaded_file_metadata

        with patch("data_agent.metadata_extractor.MetadataExtractor") as MockExt, \
             patch("data_agent.metadata_enricher.MetadataEnricher") as MockEnr, \
             patch("data_agent.metadata_manager.MetadataManager") as MockMgr:

            mock_ext = MockExt.return_value
            mock_ext.extract_from_file.return_value = {
                "technical": {"storage": {"path": "/tmp/test.shp"}},
                "business": {},
                "operational": {},
            }

            mock_enr = MockEnr.return_value
            mock_enr.enrich_geography.side_effect = lambda m: m
            mock_enr.enrich_domain.side_effect = lambda m, f: m
            mock_enr.enrich_quality.side_effect = lambda m: m

            mock_mgr = MockMgr.return_value
            mock_mgr.register_asset.return_value = 42

            result = register_uploaded_file_metadata("/tmp/test.shp")
            assert result == 42

    def test_register_uploaded_file_failure(self):
        from data_agent.metadata_integration import register_uploaded_file_metadata
        with patch("data_agent.metadata_extractor.MetadataExtractor", side_effect=Exception("fail")):
            result = register_uploaded_file_metadata("/nonexistent.shp")
            assert result is None


# ---- API Routes ----

class TestMetadataRoutes:
    @patch("data_agent.api.metadata_routes._get_user_from_request")
    def test_search_unauthorized(self, mock_user):
        import asyncio
        from starlette.testclient import TestClient
        from starlette.applications import Starlette
        from data_agent.api.metadata_routes import get_metadata_routes

        mock_user.return_value = None
        app = Starlette(routes=get_metadata_routes())
        client = TestClient(app)
        resp = client.get("/api/metadata/search")
        assert resp.status_code == 401
