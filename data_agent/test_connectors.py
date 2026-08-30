"""Tests for the pluggable connector architecture (v14.5)."""
import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

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
        from data_agent.connectors import BaseConnector, ConnectorRegistry

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
            "https://example.com/arcgis/rest/services/T/FeatureServer", {}, {"layer_id": 0},
            bbox=[116, 39, 117, 40],
        )
        self.assertEqual(len(gdf), 0)
        # Verify geometry param was included in request
        call_kwargs = mock_client.get.call_args
        params = (
            call_kwargs.kwargs.get("params", {})
            if call_kwargs.kwargs else call_kwargs[1].get("params", {})
        )
        self.assertIn("geometry", params)

    @patch("httpx.AsyncClient")
    async def test_query_uses_bounded_object_id_snapshot(self, mock_client_cls):
        id_resp = MagicMock()
        id_resp.status_code = 200
        id_resp.json.return_value = {
            "objectIdFieldName": "OBJECTID",
            "objectIds": [3, 1, 2, 4],
        }
        id_resp.raise_for_status = MagicMock()

        first_page = MagicMock()
        first_page.status_code = 200
        first_page.json.return_value = {
            "type": "FeatureCollection",
            "features": [
                {"type": "Feature", "id": 1,
                 "geometry": {"type": "Point", "coordinates": [1, 1]},
                 "properties": {"OBJECTID": 1}},
                {"type": "Feature", "id": 2,
                 "geometry": {"type": "Point", "coordinates": [2, 2]},
                 "properties": {"OBJECTID": 2}},
            ],
        }
        first_page.raise_for_status = MagicMock()

        second_page = MagicMock()
        second_page.status_code = 200
        second_page.json.return_value = {
            "type": "FeatureCollection",
            "features": [
                {"type": "Feature", "id": 3,
                 "geometry": {"type": "Point", "coordinates": [3, 3]},
                 "properties": {"OBJECTID": 3}},
            ],
        }
        second_page.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=id_resp)
        mock_client.post = AsyncMock(side_effect=[first_page, second_page])
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        from data_agent.connectors.arcgis_rest import ArcGISRestConnector
        gdf = await ArcGISRestConnector().query(
            "https://example.com/arcgis/rest/services/Test/FeatureServer", {},
            {"layer_id": 0, "max_records": 3, "page_size": 2},
            limit=10,
        )

        self.assertEqual(len(gdf), 3)
        id_call = mock_client.get.call_args
        page_calls = mock_client.post.call_args_list
        self.assertEqual(id_call.kwargs["params"]["returnIdsOnly"], "true")
        self.assertEqual(page_calls[0].kwargs["data"]["objectIds"], "1,2")
        self.assertEqual(page_calls[1].kwargs["data"]["objectIds"], "3")
        self.assertEqual(page_calls[0].kwargs["data"]["outSR"], "4326")
        self.assertNotIn("resultOffset", page_calls[0].kwargs["data"])

    @patch("httpx.AsyncClient")
    async def test_ingestion_snapshot_streams_bounded_pages(self, mock_client_cls):
        responses = []
        for payload in (
            {"objectIdFieldName": "OID", "objectIds": [10, 2, 3, 1]},
            {
                "type": "FeatureCollection",
                "features": [
                    {"type": "Feature", "geometry": None,
                     "properties": {"OID": 1}},
                    {"type": "Feature", "geometry": None,
                     "properties": {"OID": 2}},
                ],
            },
            {
                "type": "FeatureCollection",
                "features": [
                    {"type": "Feature", "geometry": None,
                     "properties": {"OID": 3}},
                ],
            },
        ):
            response = MagicMock()
            response.status_code = 200
            response.json.return_value = payload
            response.raise_for_status = MagicMock()
            responses.append(response)

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=responses[0])
        mock_client.post = AsyncMock(side_effect=responses[1:])
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        from data_agent.connectors.arcgis_rest import ArcGISRestConnector

        connector = ArcGISRestConnector()
        snapshot = await connector.create_query_snapshot(
            "https://example.com/arcgis/rest/services/Test/FeatureServer/0",
            {},
            {"out_fields": "OID,name"},
            max_records=3,
        )
        pages = [
            page
            async for page in connector.iter_snapshot_pages(
                snapshot, {}, page_size=2,
            )
        ]

        self.assertEqual(snapshot.object_ids, (1, 2, 3))
        self.assertEqual(snapshot.object_id_field, "OID")
        self.assertEqual([page["records_read"] for page in pages], [2, 1])
        calls = mock_client.post.call_args_list
        self.assertEqual(calls[0].kwargs["data"]["objectIds"], "1,2")
        self.assertEqual(calls[1].kwargs["data"]["objectIds"], "3")

    @patch("httpx.AsyncClient")
    async def test_ingestion_snapshot_falls_back_to_ordered_id_pages(
        self, mock_client_cls,
    ):
        payloads = (
            {"error": {"code": 500, "message": "ID response is too large"}},
            {"count": 5},
            {
                "features": [
                    {"attributes": {"OBJECTID": 1}},
                    {"attributes": {"OBJECTID": 2}},
                ],
                "exceededTransferLimit": True,
            },
            {
                "features": [
                    {"attributes": {"OBJECTID": 3}},
                    {"attributes": {"OBJECTID": 4}},
                ],
                "exceededTransferLimit": True,
            },
        )
        responses = []
        for payload in payloads:
            response = MagicMock()
            response.status_code = 200
            response.json.return_value = payload
            response.raise_for_status = MagicMock()
            responses.append(response)

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=responses)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        from data_agent.connectors.arcgis_rest import ArcGISRestConnector

        snapshot = await ArcGISRestConnector().create_query_snapshot(
            "https://example.com/arcgis/rest/services/Test/FeatureServer/0",
            {},
            {"object_id_field": "OBJECTID", "snapshot_id_page_size": 2},
            max_records=4,
        )

        self.assertEqual(snapshot.object_ids, (1, 2, 3, 4))
        self.assertEqual(snapshot.matched_record_count, 5)
        self.assertTrue(snapshot.truncated)
        self.assertEqual(snapshot.snapshot_strategy, "ordered_id_paging")
        calls = mock_client.get.call_args_list
        self.assertEqual(calls[0].kwargs["params"]["returnIdsOnly"], "true")
        self.assertEqual(calls[1].kwargs["params"]["returnCountOnly"], "true")
        self.assertEqual(calls[2].kwargs["params"]["resultOffset"], "0")
        self.assertEqual(calls[3].kwargs["params"]["resultOffset"], "2")
        self.assertEqual(calls[2].kwargs["params"]["orderByFields"], "OBJECTID ASC")

    @patch("httpx.AsyncClient")
    async def test_ordered_snapshot_uses_statistics_when_count_query_is_slow(
        self, mock_client_cls,
    ):
        payloads = (
            {},
            {
                "features": [
                    {"attributes": {"record_count": 2}},
                ],
            },
            {
                "features": [
                    {"attributes": {"OBJECTID": 7}},
                    {"attributes": {"OBJECTID": 9}},
                ],
            },
        )
        responses = []
        for payload in payloads:
            response = MagicMock()
            response.status_code = 200
            response.json.return_value = payload
            response.raise_for_status = MagicMock()
            responses.append(response)

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=responses)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client
        progress = AsyncMock()

        from data_agent.connectors.arcgis_rest import ArcGISRestConnector

        snapshot = await ArcGISRestConnector().create_query_snapshot(
            "https://example.com/arcgis/rest/services/Test/FeatureServer/0",
            {},
            {
                "object_id_field": "OBJECTID",
                "snapshot_strategy": "ordered_id_paging",
            },
            progress_callback=progress,
        )

        self.assertEqual(snapshot.object_ids, (7, 9))
        self.assertEqual(snapshot.matched_record_count, 2)
        calls = mock_client.get.call_args_list
        self.assertIn("outStatistics", calls[1].kwargs["params"])
        self.assertEqual(progress.await_count, 2)

    @patch("httpx.AsyncClient")
    async def test_snapshot_pages_fall_back_to_exact_object_id_where_clause(
        self, mock_client_cls,
    ):
        payloads = (
            {"error": {"code": 400, "message": "Unable to complete operation."}},
            {
                "type": "FeatureCollection",
                "features": [
                    {"type": "Feature", "geometry": None, "properties": {"OBJECTID": 1}},
                    {"type": "Feature", "geometry": None, "properties": {"OBJECTID": 2}},
                ],
            },
            {
                "type": "FeatureCollection",
                "features": [
                    {"type": "Feature", "geometry": None, "properties": {"OBJECTID": 3}},
                ],
            },
        )
        responses = []
        for payload in payloads:
            response = MagicMock()
            response.status_code = 200
            response.json.return_value = payload
            response.raise_for_status = MagicMock()
            responses.append(response)

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=responses)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        from data_agent.connectors.arcgis_rest import (
            ArcGISQuerySnapshot,
            ArcGISRestConnector,
        )

        snapshot = ArcGISQuerySnapshot(
            query_url="https://example.com/FeatureServer/0/query",
            service_url="https://example.com/FeatureServer",
            layer_id=0,
            object_id_field="OBJECTID",
            object_ids=(1, 2, 3),
            matched_record_count=3,
            where="1=1",
            out_fields="*",
            return_geometry=True,
            snapshot_strategy="ordered_id_paging",
        )
        pages = [
            page async for page in ArcGISRestConnector().iter_snapshot_pages(
                snapshot, {}, page_size=2,
            )
        ]

        self.assertEqual([page["records_read"] for page in pages], [2, 1])
        calls = mock_client.post.call_args_list
        self.assertEqual(calls[0].kwargs["data"]["objectIds"], "1,2")
        self.assertEqual(
            calls[1].kwargs["data"]["where"], "OBJECTID BETWEEN 1 AND 2",
        )
        self.assertNotIn("objectIds", calls[2].kwargs["data"])
        self.assertEqual(
            calls[2].kwargs["data"]["where"], "OBJECTID BETWEEN 3 AND 3",
        )

    @patch("httpx.AsyncClient")
    async def test_snapshot_can_page_ids_in_bounded_object_id_ranges(
        self, mock_client_cls,
    ):
        payloads = (
            {"features": [{"attributes": {"min_oid": 10, "max_oid": 35, "record_count": 3}}]},
            {
                "features": [
                    {"attributes": {"OBJECTID": 10}},
                    {"attributes": {"OBJECTID": 19}},
                ],
            },
            {"features": [{"attributes": {"OBJECTID": 35}}]},
        )
        responses = []
        for payload in payloads:
            response = MagicMock()
            response.status_code = 200
            response.json.return_value = payload
            response.raise_for_status = MagicMock()
            responses.append(response)

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=responses)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client
        progress = AsyncMock()

        from data_agent.connectors.arcgis_rest import ArcGISRestConnector

        snapshot = await ArcGISRestConnector().create_query_snapshot(
            "https://example.com/arcgis/rest/services/Test/FeatureServer/0",
            {},
            {
                "object_id_field": "OBJECTID",
                "snapshot_strategy": "object_id_range_paging",
                "snapshot_id_page_size": 3,
                "snapshot_id_range_size": 20,
            },
            progress_callback=progress,
        )

        self.assertEqual(snapshot.object_ids, (10, 19, 35))
        self.assertEqual(snapshot.matched_record_count, 3)
        self.assertEqual(snapshot.snapshot_strategy, "object_id_range_paging")
        calls = mock_client.get.call_args_list
        self.assertIn("outStatistics", calls[0].kwargs["params"])
        self.assertEqual(calls[1].kwargs["params"]["where"], "OBJECTID BETWEEN 10 AND 29")
        self.assertEqual(calls[2].kwargs["params"]["where"], "OBJECTID BETWEEN 30 AND 35")
        self.assertEqual(progress.await_count, 3)

    @patch("httpx.AsyncClient")
    async def test_exact_where_page_splits_when_a_geometry_batch_is_too_heavy(
        self, mock_client_cls,
    ):
        payloads = (
            {"error": {"code": 400, "message": "objectIds unsupported"}},
            {"error": {"code": 400, "message": "batch too heavy"}},
            {
                "type": "FeatureCollection",
                "features": [
                    {"type": "Feature", "geometry": None, "properties": {"OBJECTID": 1}},
                ],
            },
            {
                "type": "FeatureCollection",
                "features": [
                    {"type": "Feature", "geometry": None, "properties": {"OBJECTID": 2}},
                ],
            },
        )
        responses = []
        for payload in payloads:
            response = MagicMock()
            response.status_code = 200
            response.json.return_value = payload
            response.raise_for_status = MagicMock()
            responses.append(response)

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=responses)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client
        progress = AsyncMock()

        from data_agent.connectors.arcgis_rest import (
            ArcGISQuerySnapshot,
            ArcGISRestConnector,
        )

        snapshot = ArcGISQuerySnapshot(
            query_url="https://example.com/FeatureServer/0/query",
            service_url="https://example.com/FeatureServer",
            layer_id=0,
            object_id_field="OBJECTID",
            object_ids=(1, 2),
            matched_record_count=2,
            where="1=1",
            out_fields="*",
            return_geometry=True,
            snapshot_strategy="ordered_id_paging",
        )
        pages = [
            page async for page in ArcGISRestConnector().iter_snapshot_pages(
                snapshot, {}, page_size=2, progress_callback=progress,
            )
        ]

        self.assertEqual(pages[0]["records_read"], 2)
        calls = mock_client.post.call_args_list
        self.assertEqual(
            calls[1].kwargs["data"]["where"], "OBJECTID BETWEEN 1 AND 2",
        )
        self.assertEqual(
            calls[2].kwargs["data"]["where"], "OBJECTID BETWEEN 1 AND 1",
        )
        self.assertEqual(
            calls[3].kwargs["data"]["where"], "OBJECTID BETWEEN 2 AND 2",
        )
        self.assertEqual(progress.await_count, 2)

    @patch("httpx.AsyncClient")
    async def test_partial_page_is_split_and_missing_geometry_is_normalized(
        self, mock_client_cls,
    ):
        async def post(_url, *, data, headers):
            where = data["where"]
            bounds = where.split(" BETWEEN ", 1)[1]
            lower, upper = (int(value) for value in bounds.split(" AND ", 1))
            object_ids = list(range(lower, upper + 1))
            if object_ids == [1, 2, 3, 4]:
                object_ids = object_ids[:2]
            response = MagicMock()
            response.status_code = 200
            response.json.return_value = {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"OBJECTID": object_id},
                    }
                    for object_id in object_ids
                ],
            }
            response.raise_for_status = MagicMock()
            return response

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=post)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        from data_agent.connectors.arcgis_rest import (
            ArcGISQuerySnapshot,
            ArcGISRestConnector,
        )

        snapshot = ArcGISQuerySnapshot(
            query_url="https://example.com/FeatureServer/0/query",
            service_url="https://example.com/FeatureServer",
            layer_id=0,
            object_id_field="OBJECTID",
            object_ids=(1, 2, 3, 4),
            matched_record_count=4,
            where="1=1",
            out_fields="*",
            return_geometry=True,
            snapshot_strategy="object_id_range_paging",
            page_query_strategy="where",
        )
        pages = [
            page async for page in ArcGISRestConnector().iter_snapshot_pages(
                snapshot, {}, page_size=4,
            )
        ]

        self.assertEqual(pages[0]["records_read"], 4)
        self.assertEqual(mock_client.post.await_count, 3)
        self.assertIn("geometry", pages[0]["frame"].columns)
        self.assertTrue(pages[0]["frame"].geometry.isna().all())

    @patch("httpx.AsyncClient")
    async def test_nullable_and_default_null_fields_are_merged_by_object_id(
        self, mock_client_cls,
    ):
        responses = []
        for payload in (
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": None,
                        "properties": {"OBJECTID": 1, "name": "one"},
                    },
                    {
                        "type": "Feature",
                        "geometry": None,
                        "properties": {"OBJECTID": 2, "name": "two"},
                    },
                ],
            },
            {
                "features": [
                    {
                        "attributes": {
                            "OBJECTID": 1,
                            "statusdescriptoin": "active",
                        },
                    },
                ],
            },
        ):
            response = MagicMock()
            response.status_code = 200
            response.json.return_value = payload
            response.raise_for_status = MagicMock()
            responses.append(response)

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=responses)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        from data_agent.connectors.arcgis_rest import (
            ArcGISQuerySnapshot,
            ArcGISRestConnector,
        )

        snapshot = ArcGISQuerySnapshot(
            query_url="https://example.com/FeatureServer/0/query",
            service_url="https://example.com/FeatureServer",
            layer_id=0,
            object_id_field="OBJECTID",
            object_ids=(1, 2),
            matched_record_count=2,
            where="1=1",
            out_fields="OBJECTID,name",
            return_geometry=True,
            snapshot_strategy="object_id_range_paging",
            page_query_strategy="where",
            nullable_out_fields=("statusdescriptoin",),
            default_null_out_fields=("id",),
        )
        pages = [
            page async for page in ArcGISRestConnector().iter_snapshot_pages(
                snapshot, {}, page_size=2,
            )
        ]

        frame = pages[0]["frame"]
        self.assertEqual(frame["statusdescriptoin"].iloc[0], "active")
        self.assertTrue(frame["statusdescriptoin"].isna().iloc[1])
        self.assertTrue(frame["id"].isna().all())

    @patch("httpx.AsyncClient")
    async def test_where_pages_are_prefetched_with_bounded_ordered_concurrency(
        self, mock_client_cls,
    ):
        active_requests = 0
        max_active_requests = 0

        async def post(_url, *, data, headers):
            nonlocal active_requests, max_active_requests
            active_requests += 1
            max_active_requests = max(max_active_requests, active_requests)
            await asyncio.sleep(0.01)
            active_requests -= 1
            bounds = data["where"].split(" BETWEEN ", 1)[1]
            lower, upper = (int(value) for value in bounds.split(" AND ", 1))
            object_ids = list(range(lower, upper + 1))
            response = MagicMock()
            response.status_code = 200
            response.json.return_value = {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": None,
                        "properties": {"OBJECTID": object_id},
                    }
                    for object_id in object_ids
                ],
            }
            response.raise_for_status = MagicMock()
            return response

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=post)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client
        progress = AsyncMock()

        from data_agent.connectors.arcgis_rest import (
            ArcGISQuerySnapshot,
            ArcGISRestConnector,
        )

        snapshot = ArcGISQuerySnapshot(
            query_url="https://example.com/FeatureServer/0/query",
            service_url="https://example.com/FeatureServer",
            layer_id=0,
            object_id_field="OBJECTID",
            object_ids=tuple(range(1, 9)),
            matched_record_count=8,
            where="1=1",
            out_fields="*",
            return_geometry=True,
            snapshot_strategy="object_id_range_paging",
            page_query_strategy="where",
            page_concurrency=2,
        )
        pages = [
            page async for page in ArcGISRestConnector().iter_snapshot_pages(
                snapshot, {}, page_size=2, progress_callback=progress,
            )
        ]

        self.assertEqual([page["object_ids"][0] for page in pages], [1, 3, 5, 7])
        self.assertEqual(max_active_requests, 2)
        self.assertEqual(progress.await_count, 4)

    @patch("httpx.AsyncClient")
    async def test_page_progress_failure_is_not_treated_as_query_failure(
        self, mock_client_cls,
    ):
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {
            "type": "FeatureCollection",
            "features": [
                {"type": "Feature", "geometry": None, "properties": {"OBJECTID": 1}},
                {"type": "Feature", "geometry": None, "properties": {"OBJECTID": 2}},
            ],
        }
        response.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client
        progress = AsyncMock(side_effect=RuntimeError("lease lost"))

        from data_agent.connectors.arcgis_rest import (
            ArcGISQuerySnapshot,
            ArcGISRestConnector,
        )

        snapshot = ArcGISQuerySnapshot(
            query_url="https://example.com/FeatureServer/0/query",
            service_url="https://example.com/FeatureServer",
            layer_id=0,
            object_id_field="OBJECTID",
            object_ids=(1, 2),
            matched_record_count=2,
            where="1=1",
            out_fields="*",
            return_geometry=True,
            snapshot_strategy="ordered_id_paging",
            page_query_strategy="where",
        )

        with self.assertRaisesRegex(RuntimeError, "lease lost"):
            _ = [
                page async for page in ArcGISRestConnector().iter_snapshot_pages(
                    snapshot, {}, page_size=2, progress_callback=progress,
                )
            ]
        self.assertEqual(mock_client.post.await_count, 1)

    @patch("httpx.AsyncClient")
    async def test_hot_object_id_range_is_split_without_duplicate_partial_ids(
        self, mock_client_cls,
    ):
        payloads = (
            {"features": [{"attributes": {"min_oid": 10, "max_oid": 19, "record_count": 2}}]},
            {"error": {"code": 400, "message": "range too expensive"}},
            {"features": [{"attributes": {"OBJECTID": 10}}]},
            {"features": [{"attributes": {"OBJECTID": 19}}]},
        )
        responses = []
        for payload in payloads:
            response = MagicMock()
            response.status_code = 200
            response.json.return_value = payload
            response.raise_for_status = MagicMock()
            responses.append(response)

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=responses)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client
        progress = AsyncMock()

        from data_agent.connectors.arcgis_rest import ArcGISRestConnector

        snapshot = await ArcGISRestConnector().create_query_snapshot(
            "https://example.com/arcgis/rest/services/Test/FeatureServer/0",
            {},
            {
                "object_id_field": "OBJECTID",
                "snapshot_strategy": "object_id_range_paging",
                "snapshot_id_page_size": 100,
                "snapshot_id_range_size": 10,
            },
            progress_callback=progress,
        )

        self.assertEqual(snapshot.object_ids, (10, 19))
        calls = mock_client.get.call_args_list
        self.assertEqual(calls[1].kwargs["params"]["where"], "OBJECTID BETWEEN 10 AND 19")
        self.assertEqual(calls[2].kwargs["params"]["where"], "OBJECTID BETWEEN 10 AND 14")
        self.assertEqual(calls[3].kwargs["params"]["where"], "OBJECTID BETWEEN 15 AND 19")
        self.assertEqual(progress.await_count, 3)

    @patch("httpx.AsyncClient")
    async def test_hot_dense_range_can_partition_directly_into_small_chunks(
        self, mock_client_cls,
    ):
        payloads = (
            {"features": [{"attributes": {
                "min_oid": 10, "max_oid": 17, "record_count": 4,
            }}]},
            {"error": {"code": 500, "message": "range too expensive"}},
            {"features": [{"attributes": {"OBJECTID": 10}}]},
            {"features": [{"attributes": {"OBJECTID": 12}}]},
            {"features": [{"attributes": {"OBJECTID": 14}}]},
            {"features": [{"attributes": {"OBJECTID": 16}}]},
        )
        responses = []
        for payload in payloads:
            response = MagicMock()
            response.status_code = 200
            response.json.return_value = payload
            response.raise_for_status = MagicMock()
            responses.append(response)

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=responses)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client
        progress = AsyncMock()

        from data_agent.connectors.arcgis_rest import ArcGISRestConnector

        snapshot = await ArcGISRestConnector().create_query_snapshot(
            "https://example.com/arcgis/rest/services/Test/FeatureServer/0",
            {},
            {
                "object_id_field": "OBJECTID",
                "snapshot_strategy": "object_id_range_paging",
                "snapshot_id_page_size": 100,
                "snapshot_id_range_size": 8,
                "snapshot_id_dense_range_size": 2,
            },
            progress_callback=progress,
        )

        self.assertEqual(snapshot.object_ids, (10, 12, 14, 16))
        calls = mock_client.get.call_args_list
        self.assertEqual(calls[1].kwargs["params"]["where"], "OBJECTID BETWEEN 10 AND 17")
        self.assertEqual(calls[2].kwargs["params"]["where"], "OBJECTID BETWEEN 10 AND 11")
        self.assertEqual(calls[3].kwargs["params"]["where"], "OBJECTID BETWEEN 12 AND 13")
        self.assertEqual(calls[4].kwargs["params"]["where"], "OBJECTID BETWEEN 14 AND 15")
        self.assertEqual(calls[5].kwargs["params"]["where"], "OBJECTID BETWEEN 16 AND 17")
        self.assertEqual(progress.await_count, 5)

    @patch("httpx.AsyncClient")
    async def test_hot_dense_ranges_use_bounded_concurrency_in_order(
        self, mock_client_cls,
    ):
        active_requests = 0
        max_active_requests = 0

        def response(payload):
            result = MagicMock()
            result.status_code = 200
            result.json.return_value = payload
            result.raise_for_status = MagicMock()
            return result

        async def get(_url, *, params, headers):
            nonlocal active_requests, max_active_requests
            if "outStatistics" in params:
                return response({"features": [{"attributes": {
                    "min_oid": 10, "max_oid": 17, "record_count": 4,
                }}]})
            if params["where"] == "OBJECTID BETWEEN 10 AND 17":
                return response({
                    "error": {"code": 500, "message": "range too expensive"},
                })

            active_requests += 1
            max_active_requests = max(max_active_requests, active_requests)
            await asyncio.sleep(0.01)
            active_requests -= 1
            lower = int(params["where"].split(" BETWEEN ")[1].split(" AND ")[0])
            return response({
                "features": [{"attributes": {"OBJECTID": lower}}],
            })

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=get)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client
        progress = AsyncMock()

        from data_agent.connectors.arcgis_rest import ArcGISRestConnector

        snapshot = await ArcGISRestConnector().create_query_snapshot(
            "https://example.com/arcgis/rest/services/Test/FeatureServer/0",
            {},
            {
                "object_id_field": "OBJECTID",
                "snapshot_strategy": "object_id_range_paging",
                "snapshot_id_page_size": 100,
                "snapshot_id_range_size": 8,
                "snapshot_id_dense_range_size": 2,
                "snapshot_id_range_concurrency": 2,
            },
            progress_callback=progress,
        )

        self.assertEqual(snapshot.object_ids, (10, 12, 14, 16))
        self.assertEqual(max_active_requests, 2)
        self.assertEqual(progress.await_count, 5)

    @patch("httpx.AsyncClient")
    async def test_contiguous_range_statistics_materialize_verified_ids(
        self, mock_client_cls,
    ):
        payloads = (
            {"features": [{"attributes": {
                "min_oid": 10, "max_oid": 19, "record_count": 6,
            }}]},
            {"features": [{"attributes": {
                "min_oid": 12, "max_oid": 17, "record_count": 6,
            }}]},
        )
        responses = []
        for payload in payloads:
            response = MagicMock()
            response.status_code = 200
            response.json.return_value = payload
            response.raise_for_status = MagicMock()
            responses.append(response)

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=responses)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client
        progress = AsyncMock()

        from data_agent.connectors.arcgis_rest import ArcGISRestConnector

        snapshot = await ArcGISRestConnector().create_query_snapshot(
            "https://example.com/arcgis/rest/services/Test/FeatureServer/0",
            {},
            {
                "object_id_field": "OBJECTID",
                "snapshot_strategy": "object_id_range_paging",
                "snapshot_id_page_size": 100,
                "snapshot_id_range_size": 10,
                "snapshot_id_dense_range_size": 2,
                "snapshot_id_contiguous_range_stats": True,
            },
            progress_callback=progress,
        )

        self.assertEqual(snapshot.object_ids, (12, 13, 14, 15, 16, 17))
        self.assertIn("outStatistics", mock_client.get.call_args_list[1].kwargs["params"])
        self.assertEqual(progress.await_count, 2)

    @patch("httpx.AsyncClient")
    async def test_top_level_oid_ranges_use_bounded_concurrency(
        self, mock_client_cls,
    ):
        active_requests = 0
        max_active_requests = 0

        def response(payload):
            result = MagicMock()
            result.status_code = 200
            result.json.return_value = payload
            result.raise_for_status = MagicMock()
            return result

        async def get(_url, *, params, headers, **_kwargs):
            nonlocal active_requests, max_active_requests
            if params["where"] == "1=1":
                return response({"features": [{"attributes": {
                    "min_oid": 10,
                    "max_oid": 25,
                    "record_count": 16,
                }}]})
            active_requests += 1
            max_active_requests = max(max_active_requests, active_requests)
            await asyncio.sleep(0.01)
            active_requests -= 1
            bounds = params["where"].split(" BETWEEN ", 1)[1]
            lower, upper = (int(value) for value in bounds.split(" AND ", 1))
            return response({"features": [{"attributes": {
                "min_oid": lower,
                "max_oid": upper,
                "record_count": upper - lower + 1,
            }}]})

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=get)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client
        progress = AsyncMock()

        from data_agent.connectors.arcgis_rest import ArcGISRestConnector

        snapshot = await ArcGISRestConnector().create_query_snapshot(
            "https://example.com/arcgis/rest/services/Test/FeatureServer/0",
            {},
            {
                "object_id_field": "OBJECTID",
                "snapshot_strategy": "object_id_range_paging",
                "snapshot_id_range_size": 4,
                "snapshot_id_dense_range_size": 2,
                "snapshot_id_range_concurrency": 2,
                "snapshot_id_contiguous_range_stats": True,
            },
            progress_callback=progress,
        )

        self.assertEqual(snapshot.object_ids, tuple(range(10, 26)))
        self.assertEqual(max_active_requests, 2)
        self.assertEqual(progress.await_count, 5)

    @patch("httpx.AsyncClient")
    async def test_range_transport_disconnect_retries_before_partitioning(
        self, mock_client_cls,
    ):
        statistics = MagicMock()
        statistics.status_code = 200
        statistics.json.return_value = {"features": [{"attributes": {
            "min_oid": 10, "max_oid": 19, "record_count": 1,
        }}]}
        statistics.raise_for_status = MagicMock()
        recovered = MagicMock()
        recovered.status_code = 200
        recovered.json.return_value = {
            "features": [{"attributes": {"OBJECTID": 19}}],
        }
        recovered.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=[
            statistics,
            httpx.RemoteProtocolError("server disconnected"),
            recovered,
        ])
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client
        progress = AsyncMock()

        from data_agent.connectors.arcgis_rest import ArcGISRestConnector

        snapshot = await ArcGISRestConnector().create_query_snapshot(
            "https://example.com/arcgis/rest/services/Test/FeatureServer/0",
            {},
            {
                "object_id_field": "OBJECTID",
                "snapshot_strategy": "object_id_range_paging",
                "snapshot_id_page_size": 100,
                "snapshot_id_range_size": 10,
                "snapshot_id_dense_range_size": 2,
            },
            progress_callback=progress,
        )

        self.assertEqual(snapshot.object_ids, (19,))
        calls = mock_client.get.call_args_list
        self.assertEqual(calls[1].kwargs["params"]["where"], "OBJECTID BETWEEN 10 AND 19")
        self.assertEqual(calls[2].kwargs["params"]["where"], "OBJECTID BETWEEN 10 AND 19")
        self.assertEqual(progress.await_count, 2)

    @patch("httpx.AsyncClient")
    async def test_range_timeout_retries_before_partitioning(
        self, mock_client_cls,
    ):
        statistics = MagicMock()
        statistics.status_code = 200
        statistics.json.return_value = {"features": [{"attributes": {
            "min_oid": 10, "max_oid": 19, "record_count": 1,
        }}]}
        statistics.raise_for_status = MagicMock()
        recovered = MagicMock()
        recovered.status_code = 200
        recovered.json.return_value = {
            "features": [{"attributes": {"OBJECTID": 19}}],
        }
        recovered.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=[
            statistics,
            httpx.ReadTimeout("range timed out"),
            recovered,
        ])
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        from data_agent.connectors.arcgis_rest import ArcGISRestConnector

        snapshot = await ArcGISRestConnector().create_query_snapshot(
            "https://example.com/arcgis/rest/services/Test/FeatureServer/0",
            {},
            {
                "object_id_field": "OBJECTID",
                "snapshot_strategy": "object_id_range_paging",
                "snapshot_id_page_size": 100,
                "snapshot_id_range_size": 10,
                "snapshot_id_dense_range_size": 2,
            },
        )

        self.assertEqual(snapshot.object_ids, (19,))
        calls = mock_client.get.call_args_list
        self.assertEqual(calls[1].kwargs["params"]["where"], "OBJECTID BETWEEN 10 AND 19")
        self.assertEqual(calls[2].kwargs["params"]["where"], "OBJECTID BETWEEN 10 AND 19")

    @patch("httpx.AsyncClient")
    async def test_dense_chunk_timeout_splits_without_repeating_chunk(
        self, mock_client_cls,
    ):
        payloads = (
            {"features": [{"attributes": {
                "min_oid": 10, "max_oid": 13, "record_count": 2,
            }}]},
            {"error": {"code": 500, "message": "broad range too heavy"}},
        )
        responses = []
        for payload in payloads:
            response = MagicMock()
            response.status_code = 200
            response.json.return_value = payload
            response.raise_for_status = MagicMock()
            responses.append(response)
        for object_ids in ((10,), (), (13,)):
            response = MagicMock()
            response.status_code = 200
            response.json.return_value = {"features": [
                {"attributes": {"OBJECTID": object_id}}
                for object_id in object_ids
            ]}
            response.raise_for_status = MagicMock()
            responses.append(response)

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=[
            responses[0],
            responses[1],
            httpx.ReadTimeout("dense chunk timed out"),
            responses[2],
            responses[3],
            responses[4],
        ])
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        from data_agent.connectors.arcgis_rest import ArcGISRestConnector

        snapshot = await ArcGISRestConnector().create_query_snapshot(
            "https://example.com/arcgis/rest/services/Test/FeatureServer/0",
            {},
            {
                "object_id_field": "OBJECTID",
                "snapshot_strategy": "object_id_range_paging",
                "snapshot_id_page_size": 100,
                "snapshot_id_range_size": 4,
                "snapshot_id_dense_range_size": 2,
            },
        )

        self.assertEqual(snapshot.object_ids, (10, 13))
        calls = mock_client.get.call_args_list
        self.assertEqual(calls[2].kwargs["params"]["where"], "OBJECTID BETWEEN 10 AND 11")
        self.assertEqual(calls[3].kwargs["params"]["where"], "OBJECTID BETWEEN 10 AND 10")
        self.assertEqual(calls[4].kwargs["params"]["where"], "OBJECTID BETWEEN 11 AND 11")
        self.assertEqual(calls[5].kwargs["params"]["where"], "OBJECTID BETWEEN 12 AND 13")

    async def test_query_rejects_services_directory(self):
        from data_agent.connectors.arcgis_rest import ArcGISRestConnector
        result = await ArcGISRestConnector().query(
            "https://example.com/arcgis/rest/services?f=pjson", {}, {},
        )
        self.assertEqual(result["status"], "error")
        self.assertIn("discovery", result["message"])

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
            "https://example.com/arcgis/FeatureServer", {}, {"layer_id": 0},
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
        result = await ArcGISRestConnector().health_check(
            "https://example.com/FeatureServer", {},
        )
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
        caps = await ArcGISRestConnector().get_capabilities(
            "https://example.com/FeatureServer", {},
        )
        self.assertEqual(len(caps["layers"]), 2)
        self.assertEqual(caps["layers"][0]["name"], "Points")

    @patch("httpx.AsyncClient")
    async def test_directory_discovery_returns_queryable_leaf_layers(self, mock_client_cls):
        root_resp = MagicMock()
        root_resp.status_code = 200
        root_resp.json.return_value = {"folders": ["Public"], "services": []}
        root_resp.raise_for_status = MagicMock()

        folder_resp = MagicMock()
        folder_resp.status_code = 200
        folder_resp.json.return_value = {
            "folders": [],
            "services": [
                {"name": "Public/Buildings", "type": "FeatureServer"},
                {"name": "Public/Imagery", "type": "ImageServer"},
            ],
        }
        folder_resp.raise_for_status = MagicMock()

        service_resp = MagicMock()
        service_resp.status_code = 200
        service_resp.json.return_value = {
            "layers": [
                {"id": 0, "name": "Group", "subLayerIds": [1]},
                {"id": 1, "name": "Building", "subLayerIds": None,
                 "geometryType": "esriGeometryPolygon"},
            ],
        }
        service_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(
            side_effect=[root_resp, folder_resp, service_resp],
        )
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        from data_agent.connectors.arcgis_rest import ArcGISRestConnector
        caps = await ArcGISRestConnector().get_capabilities(
            "https://example.com/arcgis/rest/services?f=pjson", {},
        )

        self.assertEqual(len(caps["layers"]), 1)
        self.assertEqual(caps["layers"][0]["id"], 1)
        self.assertEqual(caps["layers"][0]["service_name"], "Public/Buildings")
        self.assertEqual(
            caps["layers"][0]["endpoint_url"],
            "https://example.com/arcgis/rest/services/Public/Buildings/FeatureServer",
        )


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
    async def test_query_uses_timeout_and_proxy_config(self, mock_client_cls):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"features": []}
        mock_resp.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        from data_agent.connectors.stac import StacConnector
        await StacConnector().query(
            "https://example.com/v1",
            {"timeout_seconds": 12, "proxy_url": "http://proxy.example:8080"},
            {},
        )

        self.assertEqual(mock_client_cls.call_args.kwargs["timeout"], 12)
        self.assertEqual(mock_client_cls.call_args.kwargs["proxy"], "http://proxy.example:8080")

    @patch("httpx.AsyncClient")
    async def test_query_pushes_bounded_stac_query_extensions(self, mock_client_cls):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"features": []}
        mock_resp.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        from data_agent.connectors.stac import StacConnector
        await StacConnector().query(
            "https://example.com/v1",
            {},
            {},
            extra_params={
                "query": {"eo:cloud_cover": {"lte": 30}},
                "unapproved": "ignored",
            },
        )

        body = mock_client.post.call_args.kwargs["json"]
        self.assertEqual(body["query"], {"eo:cloud_cover": {"lte": 30}})
        self.assertNotIn("unapproved", body)

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

    @patch("httpx.AsyncClient")
    async def test_get_capabilities_uses_timeout_and_proxy_config(self, mock_client_cls):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"collections": []}
        mock_resp.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        from data_agent.connectors.stac import StacConnector
        await StacConnector().get_capabilities(
            "https://example.com/v1",
            {"timeout_seconds": 9, "proxy_url": "http://proxy.example:8080"},
        )

        self.assertEqual(mock_client_cls.call_args.kwargs["timeout"], 9)
        self.assertEqual(mock_client_cls.call_args.kwargs["proxy"], "http://proxy.example:8080")

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
