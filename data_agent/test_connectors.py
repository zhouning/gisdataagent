"""Tests for the pluggable connector architecture (v14.5)."""
import unittest
from unittest.mock import patch, MagicMock, AsyncMock


# ---------------------------------------------------------------------------
# ConnectorRegistry
# ---------------------------------------------------------------------------

class TestConnectorRegistry(unittest.TestCase):
    def test_builtin_types_registered(self):
        from data_agent.connectors import ConnectorRegistry
        types = ConnectorRegistry.all_types()
        for t in ("wfs", "stac", "ogc_api", "custom_api", "wms", "arcgis_rest"):
            self.assertIn(t, types)

    def test_get_known_type(self):
        from data_agent.connectors import ConnectorRegistry
        connector = ConnectorRegistry.get("wfs")
        self.assertIsNotNone(connector)
        self.assertEqual(connector.SOURCE_TYPE, "wfs")

    def test_get_unknown_returns_none(self):
        from data_agent.connectors import ConnectorRegistry
        self.assertIsNone(ConnectorRegistry.get("nonexistent_type"))

    def test_unregister(self):
        from data_agent.connectors import ConnectorRegistry, BaseConnector

        class DummyConnector(BaseConnector):
            SOURCE_TYPE = "_test_dummy"
            async def query(self, *a, **kw): pass
            async def health_check(self, *a, **kw): return {}
            async def get_capabilities(self, *a, **kw): return {}

        ConnectorRegistry.register(DummyConnector())
        self.assertIn("_test_dummy", ConnectorRegistry.all_types())
        ConnectorRegistry.unregister("_test_dummy")
        self.assertNotIn("_test_dummy", ConnectorRegistry.all_types())


# ---------------------------------------------------------------------------
# WFS Connector
# ---------------------------------------------------------------------------

class TestWfsConnector(unittest.IsolatedAsyncioTestCase):
    @patch("httpx.AsyncClient")
    async def test_query_success(self, mock_client_cls):
        geojson = {
            "type": "FeatureCollection",
            "features": [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [1, 2]},
                          "properties": {"name": "A"}}],
        }
        mock_resp = MagicMock()
        mock_resp.json.return_value = geojson
        mock_resp.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        from data_agent.connectors.wfs import WfsConnector
        gdf = await WfsConnector().query("https://example.com/wfs", {}, {"feature_type": "test"})
        self.assertEqual(len(gdf), 1)

    @patch("httpx.AsyncClient")
    async def test_health_check_healthy(self, mock_client_cls):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        from data_agent.connectors.wfs import WfsConnector
        result = await WfsConnector().health_check("https://example.com/wfs", {})
        self.assertEqual(result["health"], "healthy")

    @patch("httpx.AsyncClient")
    async def test_get_capabilities(self, mock_client_cls):
        caps_xml = """<?xml version="1.0"?>
        <WFS_Capabilities version="2.0.0">
          <FeatureTypeList>
            <FeatureType><Name>roads</Name><Title>Roads Layer</Title></FeatureType>
            <FeatureType><Name>buildings</Name><Title>Buildings</Title></FeatureType>
          </FeatureTypeList>
        </WFS_Capabilities>"""
        mock_resp = MagicMock()
        mock_resp.text = caps_xml
        mock_resp.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        from data_agent.connectors.wfs import WfsConnector
        caps = await WfsConnector().get_capabilities("https://example.com/wfs", {})
        self.assertEqual(len(caps["layers"]), 2)
        self.assertEqual(caps["layers"][0]["name"], "roads")


# ---------------------------------------------------------------------------
# WMS Connector
# ---------------------------------------------------------------------------

class TestWmsConnector(unittest.IsolatedAsyncioTestCase):
    async def test_query_returns_layer_config(self):
        from data_agent.connectors.wms import WmsConnector
        result = await WmsConnector().query(
            "https://example.com/wms", {},
            {"layers": "dem", "styles": "default", "format": "image/png"},
        )
        self.assertEqual(result["type"], "wms_tile")
        self.assertEqual(result["url"], "https://example.com/wms")
        self.assertEqual(result["wms_params"]["layers"], "dem")

    @patch("httpx.AsyncClient")
    async def test_health_check_healthy(self, mock_client_cls):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        from data_agent.connectors.wms import WmsConnector
        result = await WmsConnector().health_check("https://example.com/wms", {})
        self.assertEqual(result["health"], "healthy")

    @patch("httpx.AsyncClient")
    async def test_get_capabilities_parses_xml(self, mock_client_cls):
        caps_xml = """<?xml version="1.0"?>
        <WMS_Capabilities version="1.1.1">
          <Capability>
            <Layer>
              <Title>Root</Title>
              <Layer queryable="1"><Name>ndvi</Name><Title>NDVI Index</Title></Layer>
              <Layer queryable="1"><Name>elevation</Name><Title>Elevation Model</Title></Layer>
            </Layer>
          </Capability>
        </WMS_Capabilities>"""
        mock_resp = MagicMock()
        mock_resp.text = caps_xml
        mock_resp.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        from data_agent.connectors.wms import WmsConnector
        caps = await WmsConnector().get_capabilities("https://example.com/wms", {})
        self.assertEqual(len(caps["layers"]), 2)
        self.assertEqual(caps["layers"][0]["name"], "ndvi")
        self.assertEqual(caps["version"], "1.1.1")


# ---------------------------------------------------------------------------
# ArcGIS REST Connector
# ---------------------------------------------------------------------------

class TestArcGISRestConnector(unittest.IsolatedAsyncioTestCase):
    @patch("httpx.AsyncClient")
    async def test_query_geojson(self, mock_client_cls):
        geojson_resp = {
            "type": "FeatureCollection",
            "features": [
                {"type": "Feature", "geometry": {"type": "Point", "coordinates": [120, 30]},
                 "properties": {"name": "station_1"}},
            ],
        }
        mock_resp = MagicMock()
        mock_resp.json.return_value = geojson_resp
        mock_resp.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        from data_agent.connectors.arcgis_rest import ArcGISRestConnector
        gdf = await ArcGISRestConnector().query(
            "https://example.com/arcgis/rest/services/Test/FeatureServer", {},
            {"layer_id": 0},
        )
        self.assertEqual(len(gdf), 1)
        self.assertIn("name", gdf.columns)

    @patch("httpx.AsyncClient")
    async def test_query_with_bbox(self, mock_client_cls):
        geojson_resp = {"type": "FeatureCollection", "features": []}
        mock_resp = MagicMock()
        mock_resp.json.return_value = geojson_resp
        mock_resp.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        from data_agent.connectors.arcgis_rest import ArcGISRestConnector
        gdf = await ArcGISRestConnector().query(
            "https://example.com/arcgis/rest/services/T/FS", {}, {"layer_id": 0},
            bbox=[116, 39, 117, 40],
        )
        self.assertEqual(len(gdf), 0)
        # Verify geometry param was included in request
        call_kwargs = mock_client.get.call_args
        params = call_kwargs.kwargs.get("params", {}) if call_kwargs.kwargs else call_kwargs[1].get("params", {})
        self.assertIn("geometry", params)

    @patch("httpx.AsyncClient")
    async def test_query_error_response(self, mock_client_cls):
        error_resp = {"error": {"code": 400, "message": "Invalid query"}}
        mock_resp = MagicMock()
        mock_resp.json.return_value = error_resp
        mock_resp.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        from data_agent.connectors.arcgis_rest import ArcGISRestConnector
        result = await ArcGISRestConnector().query(
            "https://example.com/arcgis/FS", {}, {"layer_id": 0},
        )
        self.assertIsInstance(result, dict)
        self.assertEqual(result["status"], "error")

    @patch("httpx.AsyncClient")
    async def test_health_check(self, mock_client_cls):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"serviceDescription": "Test service"}
        mock_resp.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        from data_agent.connectors.arcgis_rest import ArcGISRestConnector
        result = await ArcGISRestConnector().health_check("https://example.com/FS", {})
        self.assertEqual(result["health"], "healthy")

    @patch("httpx.AsyncClient")
    async def test_get_capabilities(self, mock_client_cls):
        layers_resp = {
            "layers": [
                {"id": 0, "name": "Points", "geometryType": "esriGeometryPoint"},
                {"id": 1, "name": "Lines", "geometryType": "esriGeometryPolyline"},
            ],
        }
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = layers_resp
        mock_resp.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        from data_agent.connectors.arcgis_rest import ArcGISRestConnector
        caps = await ArcGISRestConnector().get_capabilities("https://example.com/FS", {})
        self.assertEqual(len(caps["layers"]), 2)
        self.assertEqual(caps["layers"][0]["name"], "Points")


# ---------------------------------------------------------------------------
# STAC Connector (verify extraction works)
# ---------------------------------------------------------------------------

class TestStacConnector(unittest.IsolatedAsyncioTestCase):
    @patch("httpx.AsyncClient")
    async def test_query_success(self, mock_client_cls):
        stac_resp = {
            "features": [{"id": "item-1", "properties": {"datetime": "2024-06-01"},
                          "assets": {}, "bbox": [1, 2, 3, 4], "collection": "s2"}],
        }
        mock_resp = MagicMock()
        mock_resp.json.return_value = stac_resp
        mock_resp.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        from data_agent.connectors.stac import StacConnector
        items = await StacConnector().query("https://example.com/v1", {}, {})
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["id"], "item-1")

    @patch("httpx.AsyncClient")
    async def test_get_capabilities(self, mock_client_cls):
        coll_resp = {
            "collections": [
                {"id": "sentinel-2", "title": "Sentinel-2", "description": "Optical imagery"},
            ],
        }
        mock_resp = MagicMock()
        mock_resp.json.return_value = coll_resp
        mock_resp.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        from data_agent.connectors.stac import StacConnector
        caps = await StacConnector().get_capabilities("https://example.com/v1", {})
        self.assertEqual(len(caps["layers"]), 1)
        self.assertEqual(caps["layers"][0]["name"], "sentinel-2")


# ---------------------------------------------------------------------------
# Custom API Connector
# ---------------------------------------------------------------------------

class TestCustomApiConnector(unittest.IsolatedAsyncioTestCase):
    async def test_get_capabilities_no_discovery(self):
        from data_agent.connectors.custom_api import CustomApiConnector
        caps = await CustomApiConnector().get_capabilities("https://example.com/api", {})
        self.assertFalse(caps["discovery"])


# ---------------------------------------------------------------------------
# Auth header builder
# ---------------------------------------------------------------------------

class TestBuildAuthHeaders(unittest.TestCase):
    def test_bearer(self):
        from data_agent.connectors import build_auth_headers
        h = build_auth_headers({"type": "bearer", "token": "abc"})
        self.assertEqual(h["Authorization"], "Bearer abc")

    def test_apikey(self):
        from data_agent.connectors import build_auth_headers
        h = build_auth_headers({"type": "apikey", "key": "k123", "header": "X-Key"})
        self.assertEqual(h["X-Key"], "k123")

    def test_empty(self):
        from data_agent.connectors import build_auth_headers
        self.assertEqual(build_auth_headers({}), {})

    def test_none_config(self):
        from data_agent.connectors import build_auth_headers
        self.assertEqual(build_auth_headers(None), {})


if __name__ == "__main__":
    unittest.main()
