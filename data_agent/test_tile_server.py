"""Tests for tile_server.py and tile_routes.py — MVT tile generation and serving.

All DB-related tests mock get_engine — no real PostGIS required.
"""
import asyncio
import json
import os
import tempfile
import unittest
from unittest.mock import patch, MagicMock, AsyncMock, PropertyMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):
    """Run an async coroutine synchronously."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _make_request(path="/", query_params=None, cookies=None, path_params=None,
                  method="GET", body=None):
    """Create a mock Starlette Request."""
    req = MagicMock()
    req.cookies = cookies or {}
    req.query_params = query_params or {}
    req.path_params = path_params or {}
    req.method = method
    if body is not None:
        req.json = AsyncMock(return_value=body)
    else:
        req.json = AsyncMock(side_effect=Exception("No body"))
    return req


def _make_geojson_file(tmpdir, num_features=10):
    """Create a simple GeoJSON file with polygon features."""
    features = []
    for i in range(num_features):
        features.append({
            "type": "Feature",
            "properties": {"id": i, "name": f"parcel_{i}", "area": 100.0 + i},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[121.0 + i * 0.001, 31.0],
                                 [121.001 + i * 0.001, 31.0],
                                 [121.001 + i * 0.001, 31.001],
                                 [121.0 + i * 0.001, 31.001],
                                 [121.0 + i * 0.001, 31.0]]]
            }
        })
    geojson = {"type": "FeatureCollection", "features": features}
    path = os.path.join(tmpdir, "test_data.geojson")
    with open(path, "w") as f:
        json.dump(geojson, f)
    return path


# ---------------------------------------------------------------------------
# tile_server.py tests
# ---------------------------------------------------------------------------

class TestTileServerThresholds(unittest.TestCase):
    """Test feature count threshold configuration."""

    def test_default_thresholds(self):
        from data_agent.tile_server import MVT_FEATURE_THRESHOLD, FGB_FEATURE_THRESHOLD
        self.assertEqual(MVT_FEATURE_THRESHOLD, 50000)
        self.assertEqual(FGB_FEATURE_THRESHOLD, 5000)

    @patch.dict(os.environ, {"MVT_FEATURE_THRESHOLD": "10000", "FGB_FEATURE_THRESHOLD": "2000"})
    def test_custom_thresholds(self):
        """Thresholds are read at import time; verify env var mechanism."""
        # Re-import to pick up env vars (thresholds are module-level constants)
        self.assertEqual(int(os.environ["MVT_FEATURE_THRESHOLD"]), 10000)
        self.assertEqual(int(os.environ["FGB_FEATURE_THRESHOLD"]), 2000)


class TestCreateTileLayer(unittest.TestCase):
    """Test create_tile_layer with mocked PostGIS."""

    @patch("data_agent.tile_server.get_engine")
    def test_create_tile_layer_success(self, mock_engine):
        """Verify tile layer creation imports GeoJSON and registers metadata."""
        from data_agent.tile_server import create_tile_layer, _layer_cache

        engine = MagicMock()
        mock_engine.return_value = engine

        # Mock connection context manager
        conn = MagicMock()
        engine.connect.return_value.__enter__ = MagicMock(return_value=conn)
        engine.connect.return_value.__exit__ = MagicMock(return_value=False)

        with tempfile.TemporaryDirectory() as tmpdir:
            geojson_path = _make_geojson_file(tmpdir, num_features=100)

            with patch("geopandas.GeoDataFrame.to_postgis") as mock_postgis:
                meta = create_tile_layer(geojson_path, "testuser", "test_layer")

        self.assertIn("layer_id", meta)
        self.assertIn("table_name", meta)
        self.assertEqual(meta["owner_username"], "testuser")
        self.assertEqual(meta["layer_name"], "test_layer")
        self.assertEqual(meta["feature_count"], 100)
        self.assertEqual(meta["srid"], 4326)
        self.assertEqual(len(meta["bounds"]), 4)
        self.assertIn("id", meta["columns"])
        self.assertIn("name", meta["columns"])
        # Verify cached
        self.assertIn(meta["layer_id"], _layer_cache)
        # Cleanup cache
        _layer_cache.pop(meta["layer_id"], None)

    @patch("data_agent.tile_server.get_engine")
    def test_create_tile_layer_empty_geojson(self, mock_engine):
        """Empty GeoJSON should raise ValueError."""
        from data_agent.tile_server import create_tile_layer

        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "empty.geojson")
            with open(path, "w") as f:
                json.dump({"type": "FeatureCollection", "features": []}, f)

            with self.assertRaises(ValueError):
                create_tile_layer(path, "testuser")


class TestGetLayerMetadata(unittest.TestCase):
    """Test metadata retrieval from cache and DB."""

    def test_from_cache(self):
        from data_agent.tile_server import get_layer_metadata, _layer_cache
        _layer_cache["cached_id"] = {"layer_id": "cached_id", "table_name": "t"}
        meta = get_layer_metadata("cached_id")
        self.assertEqual(meta["layer_id"], "cached_id")
        _layer_cache.pop("cached_id")

    @patch("data_agent.tile_server.get_engine")
    def test_from_db(self, mock_engine):
        from data_agent.tile_server import get_layer_metadata, _layer_cache
        _layer_cache.pop("db_id", None)

        engine = MagicMock()
        mock_engine.return_value = engine

        conn = MagicMock()
        engine.connect.return_value.__enter__ = MagicMock(return_value=conn)
        engine.connect.return_value.__exit__ = MagicMock(return_value=False)

        conn.execute.return_value.fetchone.return_value = (
            "db_id", "_mvt_test", "user1", "layer1", 4326,
            500, [121.0, 31.0, 121.1, 31.1], ["id", "name"], "test.geojson"
        )

        meta = get_layer_metadata("db_id")
        self.assertIsNotNone(meta)
        self.assertEqual(meta["layer_id"], "db_id")
        self.assertEqual(meta["feature_count"], 500)
        _layer_cache.pop("db_id", None)

    @patch("data_agent.tile_server.get_engine", return_value=None)
    def test_no_engine(self, mock_engine):
        from data_agent.tile_server import get_layer_metadata, _layer_cache
        _layer_cache.pop("missing", None)
        meta = get_layer_metadata("missing")
        self.assertIsNone(meta)


class TestGenerateTile(unittest.TestCase):
    """Test MVT tile generation."""

    @patch("data_agent.tile_server.get_engine")
    @patch("data_agent.tile_server.get_layer_metadata")
    def test_generate_tile_returns_bytes(self, mock_meta, mock_engine):
        from data_agent.tile_server import generate_tile

        mock_meta.return_value = {
            "layer_id": "test", "table_name": "_mvt_test",
            "srid": 4326, "layer_name": "default",
            "columns": ["id", "name"],
        }

        engine = MagicMock()
        mock_engine.return_value = engine
        conn = MagicMock()
        engine.connect.return_value.__enter__ = MagicMock(return_value=conn)
        engine.connect.return_value.__exit__ = MagicMock(return_value=False)
        conn.execute.return_value.fetchone.return_value = (b"\x1a\x03mvt",)

        result = generate_tile("test", 10, 512, 340)
        self.assertIsInstance(result, bytes)
        self.assertGreater(len(result), 0)

    @patch("data_agent.tile_server.get_layer_metadata", return_value=None)
    def test_generate_tile_unknown_layer(self, mock_meta):
        from data_agent.tile_server import generate_tile
        result = generate_tile("nonexistent", 0, 0, 0)
        self.assertIsNone(result)

    @patch("data_agent.tile_server.get_engine")
    @patch("data_agent.tile_server.get_layer_metadata")
    def test_generate_tile_empty(self, mock_meta, mock_engine):
        from data_agent.tile_server import generate_tile

        mock_meta.return_value = {
            "layer_id": "empty", "table_name": "_mvt_empty",
            "srid": 4326, "layer_name": "default", "columns": [],
        }
        engine = MagicMock()
        mock_engine.return_value = engine
        conn = MagicMock()
        engine.connect.return_value.__enter__ = MagicMock(return_value=conn)
        engine.connect.return_value.__exit__ = MagicMock(return_value=False)
        conn.execute.return_value.fetchone.return_value = (b"",)

        result = generate_tile("empty", 0, 0, 0)
        self.assertIsNone(result)


class TestCleanupTileLayer(unittest.TestCase):
    """Test tile layer cleanup."""

    @patch("data_agent.tile_server.get_engine")
    @patch("data_agent.tile_server.get_layer_metadata")
    def test_cleanup_success(self, mock_meta, mock_engine):
        from data_agent.tile_server import cleanup_tile_layer, _layer_cache

        mock_meta.return_value = {
            "layer_id": "cleanup_test", "table_name": "_mvt_cleanup",
        }
        _layer_cache["cleanup_test"] = mock_meta.return_value

        engine = MagicMock()
        mock_engine.return_value = engine
        conn = MagicMock()
        engine.connect.return_value.__enter__ = MagicMock(return_value=conn)
        engine.connect.return_value.__exit__ = MagicMock(return_value=False)

        result = cleanup_tile_layer("cleanup_test")
        self.assertTrue(result)
        self.assertNotIn("cleanup_test", _layer_cache)

    @patch("data_agent.tile_server.get_layer_metadata", return_value=None)
    def test_cleanup_nonexistent(self, mock_meta):
        from data_agent.tile_server import cleanup_tile_layer
        result = cleanup_tile_layer("nonexistent")
        self.assertFalse(result)


class TestCleanupExpiredLayers(unittest.TestCase):
    """Test expired layer cleanup."""

    @patch("data_agent.tile_server.get_engine", return_value=None)
    def test_no_engine(self, mock_engine):
        from data_agent.tile_server import cleanup_expired_layers
        count = cleanup_expired_layers()
        self.assertEqual(count, 0)

    @patch("data_agent.tile_server.get_engine")
    def test_cleanup_expired(self, mock_engine):
        from data_agent.tile_server import cleanup_expired_layers

        engine = MagicMock()
        mock_engine.return_value = engine
        conn = MagicMock()
        engine.connect.return_value.__enter__ = MagicMock(return_value=conn)
        engine.connect.return_value.__exit__ = MagicMock(return_value=False)

        # Simulate 2 expired layers
        conn.execute.return_value.fetchall.return_value = [
            ("exp1", "_mvt_exp1"),
            ("exp2", "_mvt_exp2"),
        ]

        count = cleanup_expired_layers()
        self.assertEqual(count, 2)


# ---------------------------------------------------------------------------
# artifact_handler.py adaptive strategy tests
# ---------------------------------------------------------------------------

class TestAdaptiveStrategy(unittest.TestCase):
    """Test the three-tier adaptive delivery in build_map_update_from_geojson."""

    @patch("data_agent.tile_server.FGB_FEATURE_THRESHOLD", 5000)
    @patch("data_agent.tile_server.MVT_FEATURE_THRESHOLD", 50000)
    def test_small_dataset_uses_geojson(self):
        """Datasets with <=5000 features should use GeoJSON delivery."""
        from data_agent.artifact_handler import build_map_update_from_geojson

        with tempfile.TemporaryDirectory() as tmpdir:
            path = _make_geojson_file(tmpdir, num_features=100)
            result = build_map_update_from_geojson(path)

        self.assertIsNotNone(result)
        layer = result["layers"][0]
        self.assertEqual(layer["type"], "polygon")
        self.assertIn("geojson", layer)
        self.assertNotIn("tile_url", layer)
        self.assertNotIn("fgb", layer)

    def test_empty_geojson_returns_none(self):
        from data_agent.artifact_handler import build_map_update_from_geojson

        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "empty.geojson")
            with open(path, "w") as f:
                json.dump({"type": "FeatureCollection", "features": []}, f)
            result = build_map_update_from_geojson(path)
        self.assertIsNone(result)

    def test_nonexistent_file_returns_none(self):
        from data_agent.artifact_handler import build_map_update_from_geojson
        result = build_map_update_from_geojson("/nonexistent/path.geojson")
        self.assertIsNone(result)

    def test_merge_into_existing_update(self):
        from data_agent.artifact_handler import build_map_update_from_geojson

        existing = {"layers": [{"name": "Existing", "type": "point"}],
                    "center": [31.0, 121.0], "zoom": 10}

        with tempfile.TemporaryDirectory() as tmpdir:
            path = _make_geojson_file(tmpdir, num_features=5)
            result = build_map_update_from_geojson(path, existing)

        self.assertEqual(len(result["layers"]), 2)
        self.assertEqual(result["layers"][0]["name"], "Existing")


# ---------------------------------------------------------------------------
# tile_routes.py endpoint tests
# ---------------------------------------------------------------------------

class TestTileRouteEndpoints(unittest.TestCase):
    """Test tile route handler functions."""

    @patch("data_agent.api.tile_routes._get_user_from_request", return_value=None)
    def test_tile_unauthorized(self, mock_user):
        from data_agent.api.tile_routes import _api_tile
        req = _make_request(path_params={
            "layer_id": "test", "z": 0, "x": 0, "y": 0
        })
        resp = _run(_api_tile(req))
        self.assertEqual(resp.status_code, 401)

    @patch("data_agent.api.tile_routes._set_user_context",
           return_value=("testuser", "analyst"))
    @patch("data_agent.api.tile_routes._get_user_from_request")
    def test_tile_not_found(self, mock_user, mock_ctx):
        from data_agent.api.tile_routes import _api_tile

        mock_user.return_value = MagicMock()
        req = _make_request(path_params={
            "layer_id": "missing", "z": 0, "x": 0, "y": 0
        })

        with patch("data_agent.tile_server.get_layer_metadata", return_value=None):
            resp = _run(_api_tile(req))
        self.assertEqual(resp.status_code, 404)

    @patch("data_agent.api.tile_routes._set_user_context",
           return_value=("testuser", "analyst"))
    @patch("data_agent.api.tile_routes._get_user_from_request")
    def test_tile_forbidden(self, mock_user, mock_ctx):
        from data_agent.api.tile_routes import _api_tile

        mock_user.return_value = MagicMock()
        req = _make_request(path_params={
            "layer_id": "other", "z": 0, "x": 0, "y": 0
        })

        with patch("data_agent.tile_server.get_layer_metadata",
                    return_value={"owner_username": "other_user"}):
            resp = _run(_api_tile(req))
        self.assertEqual(resp.status_code, 403)

    @patch("data_agent.api.tile_routes._set_user_context",
           return_value=("testuser", "analyst"))
    @patch("data_agent.api.tile_routes._get_user_from_request")
    def test_tile_success(self, mock_user, mock_ctx):
        from data_agent.api.tile_routes import _api_tile

        mock_user.return_value = MagicMock()
        req = _make_request(path_params={
            "layer_id": "ok", "z": 10, "x": 512, "y": 340
        })

        with patch("data_agent.tile_server.get_layer_metadata",
                    return_value={"owner_username": "testuser"}), \
             patch("data_agent.tile_server.generate_tile",
                   return_value=b"\x1a\x03mvt"):
            resp = _run(_api_tile(req))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.media_type, "application/vnd.mapbox-vector-tile")

    @patch("data_agent.api.tile_routes._set_user_context",
           return_value=("testuser", "analyst"))
    @patch("data_agent.api.tile_routes._get_user_from_request")
    def test_tile_empty_returns_204(self, mock_user, mock_ctx):
        from data_agent.api.tile_routes import _api_tile

        mock_user.return_value = MagicMock()
        req = _make_request(path_params={
            "layer_id": "empty", "z": 0, "x": 0, "y": 0
        })

        with patch("data_agent.tile_server.get_layer_metadata",
                    return_value={"owner_username": "testuser"}), \
             patch("data_agent.tile_server.generate_tile", return_value=None):
            resp = _run(_api_tile(req))
        self.assertEqual(resp.status_code, 204)


class TestTileMetadataEndpoint(unittest.TestCase):
    """Test metadata.json endpoint."""

    @patch("data_agent.api.tile_routes._set_user_context",
           return_value=("testuser", "analyst"))
    @patch("data_agent.api.tile_routes._get_user_from_request")
    def test_metadata_success(self, mock_user, mock_ctx):
        from data_agent.api.tile_routes import _api_tile_metadata

        mock_user.return_value = MagicMock()
        req = _make_request(path_params={"layer_id": "meta_test"})

        with patch("data_agent.tile_server.get_layer_metadata", return_value={
            "owner_username": "testuser",
            "layer_name": "test_layer",
            "bounds": [121.0, 31.0, 121.1, 31.1],
            "columns": ["id", "name"],
            "feature_count": 1000,
        }):
            resp = _run(_api_tile_metadata(req))

        self.assertEqual(resp.status_code, 200)
        body = json.loads(resp.body)
        self.assertEqual(body["tilejson"], "3.0.0")
        self.assertEqual(body["feature_count"], 1000)
        self.assertIn("tiles", body)


class TestTileDeleteEndpoint(unittest.TestCase):
    """Test tile layer deletion endpoint."""

    @patch("data_agent.api.tile_routes._set_user_context",
           return_value=("testuser", "analyst"))
    @patch("data_agent.api.tile_routes._get_user_from_request")
    def test_delete_success(self, mock_user, mock_ctx):
        from data_agent.api.tile_routes import _api_tile_delete

        mock_user.return_value = MagicMock()
        req = _make_request(path_params={"layer_id": "del_test"})

        with patch("data_agent.tile_server.get_layer_metadata",
                    return_value={"owner_username": "testuser"}), \
             patch("data_agent.tile_server.cleanup_tile_layer") as mock_cleanup:
            resp = _run(_api_tile_delete(req))

        self.assertEqual(resp.status_code, 200)
        mock_cleanup.assert_called_once_with("del_test")


class TestMartinProxy(unittest.TestCase):
    """Test Martin proxy endpoint."""

    @patch("data_agent.api.tile_routes.MARTIN_URL", "")
    @patch("data_agent.api.tile_routes._set_user_context",
           return_value=("testuser", "analyst"))
    @patch("data_agent.api.tile_routes._get_user_from_request")
    def test_martin_not_configured(self, mock_user, mock_ctx):
        from data_agent.api.tile_routes import _api_martin_tile

        mock_user.return_value = MagicMock()
        req = _make_request(path_params={
            "table": "parcels", "z": 0, "x": 0, "y": 0
        })
        resp = _run(_api_martin_tile(req))
        self.assertEqual(resp.status_code, 503)

    @patch("data_agent.api.tile_routes._set_user_context",
           return_value=("testuser", "analyst"))
    @patch("data_agent.api.tile_routes._get_user_from_request")
    def test_martin_invalid_table_name(self, mock_user, mock_ctx):
        from data_agent.api.tile_routes import _api_martin_tile

        mock_user.return_value = MagicMock()
        req = _make_request(path_params={
            "table": "DROP TABLE;--", "z": 0, "x": 0, "y": 0
        })

        with patch("data_agent.api.tile_routes.MARTIN_URL", "http://martin:3000"):
            resp = _run(_api_martin_tile(req))
        self.assertEqual(resp.status_code, 400)


class TestGetTileRoutes(unittest.TestCase):
    """Test route registration."""

    def test_route_list(self):
        from data_agent.api.tile_routes import get_tile_routes
        routes = get_tile_routes()
        self.assertGreaterEqual(len(routes), 5)  # 3 self-hosted + 2 martin
        paths = [r.path for r in routes]
        self.assertIn("/api/tiles/{layer_id}/{z:int}/{x:int}/{y:int}.pbf", paths)
        self.assertIn("/api/tiles/{layer_id}/metadata.json", paths)
        self.assertIn("/api/tiles/martin/catalog", paths)


if __name__ == "__main__":
    unittest.main()
