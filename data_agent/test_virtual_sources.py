"""
Tests for Virtual Data Sources (v13.0).

Covers: table constant, table init, validation, CRUD (mocked DB),
encryption round-trip, connectors (mocked httpx), auth header builder,
schema mapping, health check, unified dispatcher.
"""
import json
import unittest
from unittest.mock import MagicMock, patch, AsyncMock


# ---------------------------------------------------------------------------
# Table constant
# ---------------------------------------------------------------------------

class TestTableConstant(unittest.TestCase):
    def test_constant_exists(self):
        from data_agent.database_tools import T_VIRTUAL_SOURCES
        self.assertEqual(T_VIRTUAL_SOURCES, "agent_virtual_sources")


# ---------------------------------------------------------------------------
# Encryption round-trip
# ---------------------------------------------------------------------------

class TestEncryption(unittest.TestCase):
    def test_encrypt_empty_dict(self):
        from data_agent.virtual_sources import _encrypt_dict, _decrypt_dict
        enc = _encrypt_dict({})
        self.assertEqual(json.loads(enc), {})
        self.assertEqual(_decrypt_dict(enc), {})

    @patch.dict("os.environ", {"CHAINLIT_AUTH_SECRET": "test-secret-for-vs"})
    def test_encrypt_decrypt_roundtrip(self):
        import data_agent.virtual_sources as vs
        vs._FERNET_KEY = None  # Reset cached key
        data = {"type": "bearer", "token": "my-secret-token"}
        enc = vs._encrypt_dict(data)
        parsed = json.loads(enc)
        self.assertIn("_enc", parsed)
        result = vs._decrypt_dict(enc)
        self.assertEqual(result, data)
        vs._FERNET_KEY = None  # Cleanup

    def test_decrypt_plain_dict(self):
        from data_agent.virtual_sources import _decrypt_dict
        d = {"type": "basic", "username": "u", "password": "p"}
        self.assertEqual(_decrypt_dict(d), d)

    def test_decrypt_invalid_enc(self):
        from data_agent.virtual_sources import _decrypt_dict
        result = _decrypt_dict({"_enc": "invalid-data"})
        self.assertEqual(result, {})

    def test_decrypt_non_dict(self):
        from data_agent.virtual_sources import _decrypt_dict
        self.assertEqual(_decrypt_dict(None), {})
        self.assertEqual(_decrypt_dict(42), {})
        self.assertEqual(_decrypt_dict(""), {})


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class TestValidation(unittest.TestCase):
    def test_valid_source(self):
        from data_agent.virtual_sources import _validate_source
        self.assertIsNone(_validate_source({
            "source_name": "test-wfs",
            "source_type": "wfs",
            "endpoint_url": "https://example.com/wfs",
        }))

    def test_missing_name(self):
        from data_agent.virtual_sources import _validate_source
        self.assertIsNotNone(_validate_source({
            "source_name": "",
            "source_type": "wfs",
            "endpoint_url": "https://example.com/wfs",
        }))

    def test_invalid_type(self):
        from data_agent.virtual_sources import _validate_source
        self.assertIsNotNone(_validate_source({
            "source_name": "test",
            "source_type": "invalid",
            "endpoint_url": "https://example.com",
        }))

    def test_missing_url(self):
        from data_agent.virtual_sources import _validate_source
        self.assertIsNotNone(_validate_source({
            "source_name": "test",
            "source_type": "wfs",
            "endpoint_url": "",
        }))

    def test_invalid_auth_type(self):
        from data_agent.virtual_sources import _validate_source
        self.assertIsNotNone(_validate_source({
            "source_name": "test",
            "source_type": "wfs",
            "endpoint_url": "https://example.com",
            "auth_config": {"type": "oauth2"},
        }))

    def test_name_too_long(self):
        from data_agent.virtual_sources import _validate_source
        self.assertIsNotNone(_validate_source({
            "source_name": "x" * 201,
            "source_type": "wfs",
            "endpoint_url": "https://example.com",
        }))


# ---------------------------------------------------------------------------
# Auth header builder
# ---------------------------------------------------------------------------

class TestAuthHeaders(unittest.TestCase):
    def test_bearer(self):
        from data_agent.virtual_sources import _build_auth_headers
        h = _build_auth_headers({"type": "bearer", "token": "abc123"})
        self.assertEqual(h, {"Authorization": "Bearer abc123"})

    def test_basic(self):
        from data_agent.virtual_sources import _build_auth_headers
        h = _build_auth_headers({"type": "basic", "username": "u", "password": "p"})
        self.assertIn("Authorization", h)
        self.assertTrue(h["Authorization"].startswith("Basic "))

    def test_apikey(self):
        from data_agent.virtual_sources import _build_auth_headers
        h = _build_auth_headers({"type": "apikey", "header": "X-Key", "key": "k"})
        self.assertEqual(h, {"X-Key": "k"})

    def test_none_type(self):
        from data_agent.virtual_sources import _build_auth_headers
        self.assertEqual(_build_auth_headers({"type": "none"}), {})

    def test_empty_config(self):
        from data_agent.virtual_sources import _build_auth_headers
        self.assertEqual(_build_auth_headers({}), {})


# ---------------------------------------------------------------------------
# CRUD (mocked DB)
# ---------------------------------------------------------------------------

class TestCRUD(unittest.TestCase):
    def _mock_engine(self):
        engine = MagicMock()
        conn = MagicMock()
        engine.connect.return_value.__enter__ = MagicMock(return_value=conn)
        engine.connect.return_value.__exit__ = MagicMock(return_value=False)
        return engine, conn

    @patch("data_agent.virtual_sources.get_engine", return_value=None)
    def test_create_no_db(self, mock_eng):
        from data_agent.virtual_sources import create_virtual_source
        r = create_virtual_source("test", "wfs", "https://x.com/wfs", "admin")
        self.assertEqual(r["status"], "error")

    @patch("data_agent.virtual_sources.get_engine")
    def test_create_success(self, mock_get):
        engine, conn = self._mock_engine()
        mock_get.return_value = engine
        conn.execute.side_effect = [
            MagicMock(scalar=MagicMock(return_value=0)),  # count
            MagicMock(),  # insert
            MagicMock(fetchone=MagicMock(return_value=(42,))),  # select id
        ]
        from data_agent.virtual_sources import create_virtual_source
        r = create_virtual_source("test-wfs", "wfs", "https://x.com/wfs", "admin")
        self.assertEqual(r["status"], "ok")
        self.assertEqual(r["id"], 42)

    @patch("data_agent.virtual_sources.get_engine")
    def test_create_duplicate(self, mock_get):
        engine, conn = self._mock_engine()
        mock_get.return_value = engine
        conn.execute.side_effect = [
            MagicMock(scalar=MagicMock(return_value=0)),
            Exception("uq_vsource unique constraint"),
        ]
        from data_agent.virtual_sources import create_virtual_source
        r = create_virtual_source("dup", "wfs", "https://x.com/wfs", "admin")
        self.assertEqual(r["status"], "error")
        self.assertIn("already exists", r["message"])

    @patch("data_agent.virtual_sources.get_engine")
    def test_create_over_limit(self, mock_get):
        engine, conn = self._mock_engine()
        mock_get.return_value = engine
        conn.execute.return_value = MagicMock(scalar=MagicMock(return_value=50))
        from data_agent.virtual_sources import create_virtual_source
        r = create_virtual_source("new", "wfs", "https://x.com/wfs", "admin")
        self.assertEqual(r["status"], "error")
        self.assertIn("Max", r["message"])

    def test_create_invalid_type(self):
        from data_agent.virtual_sources import create_virtual_source
        r = create_virtual_source("test", "invalid", "https://x.com", "admin")
        self.assertEqual(r["status"], "error")

    @patch("data_agent.virtual_sources.get_engine", return_value=None)
    def test_list_no_db(self, _):
        from data_agent.virtual_sources import list_virtual_sources
        self.assertEqual(list_virtual_sources("admin"), [])

    @patch("data_agent.virtual_sources.get_engine")
    def test_list_returns_rows(self, mock_get):
        engine, conn = self._mock_engine()
        mock_get.return_value = engine
        conn.execute.return_value = MagicMock(fetchall=MagicMock(return_value=[
            (1, "wfs1", "wfs", "https://x.com/wfs", {}, "EPSG:4326",
             None, "on_demand", True, "admin", False, "healthy",
             "2026-01-01", "2026-01-01"),
        ]))
        from data_agent.virtual_sources import list_virtual_sources
        r = list_virtual_sources("admin")
        self.assertEqual(len(r), 1)
        self.assertEqual(r[0]["source_name"], "wfs1")

    @patch("data_agent.virtual_sources.get_engine", return_value=None)
    def test_get_no_db(self, _):
        from data_agent.virtual_sources import get_virtual_source
        self.assertIsNone(get_virtual_source(1, "admin"))

    @patch("data_agent.virtual_sources.get_engine")
    def test_get_found(self, mock_get):
        engine, conn = self._mock_engine()
        mock_get.return_value = engine
        conn.execute.return_value = MagicMock(fetchone=MagicMock(return_value=(
            1, "wfs1", "wfs", "https://x.com/wfs", {}, {}, {},
            "EPSG:4326", None, "on_demand", True, "admin", False,
            "healthy", None, "2026-01-01", "2026-01-01",
        )))
        from data_agent.virtual_sources import get_virtual_source
        r = get_virtual_source(1, "admin")
        self.assertIsNotNone(r)
        self.assertEqual(r["source_name"], "wfs1")

    @patch("data_agent.virtual_sources.get_engine")
    def test_get_not_found(self, mock_get):
        engine, conn = self._mock_engine()
        mock_get.return_value = engine
        conn.execute.return_value = MagicMock(fetchone=MagicMock(return_value=None))
        from data_agent.virtual_sources import get_virtual_source
        self.assertIsNone(get_virtual_source(999, "admin"))

    @patch("data_agent.virtual_sources.get_engine")
    def test_update_success(self, mock_get):
        engine, conn = self._mock_engine()
        mock_get.return_value = engine
        conn.execute.return_value = MagicMock(rowcount=1)
        from data_agent.virtual_sources import update_virtual_source
        r = update_virtual_source(1, "admin", source_name="renamed")
        self.assertEqual(r["status"], "ok")

    @patch("data_agent.virtual_sources.get_engine")
    def test_update_not_found(self, mock_get):
        engine, conn = self._mock_engine()
        mock_get.return_value = engine
        conn.execute.return_value = MagicMock(rowcount=0)
        from data_agent.virtual_sources import update_virtual_source
        r = update_virtual_source(999, "admin", source_name="x")
        self.assertEqual(r["status"], "error")

    def test_update_no_fields(self):
        from data_agent.virtual_sources import update_virtual_source
        r = update_virtual_source(1, "admin", invalid_field="x")
        self.assertEqual(r["status"], "error")

    def test_update_invalid_type(self):
        from data_agent.virtual_sources import update_virtual_source
        r = update_virtual_source(1, "admin", source_type="bad")
        self.assertEqual(r["status"], "error")

    @patch("data_agent.virtual_sources.get_engine")
    def test_delete_success(self, mock_get):
        engine, conn = self._mock_engine()
        mock_get.return_value = engine
        conn.execute.return_value = MagicMock(rowcount=1)
        from data_agent.virtual_sources import delete_virtual_source
        r = delete_virtual_source(1, "admin")
        self.assertEqual(r["status"], "ok")

    @patch("data_agent.virtual_sources.get_engine")
    def test_delete_not_found(self, mock_get):
        engine, conn = self._mock_engine()
        mock_get.return_value = engine
        conn.execute.return_value = MagicMock(rowcount=0)
        from data_agent.virtual_sources import delete_virtual_source
        r = delete_virtual_source(999, "admin")
        self.assertEqual(r["status"], "error")


# ---------------------------------------------------------------------------
# Table init
# ---------------------------------------------------------------------------

class TestTableInit(unittest.TestCase):
    @patch("data_agent.virtual_sources.get_engine", return_value=None)
    def test_no_db_warns(self, _):
        from data_agent.virtual_sources import ensure_virtual_sources_table
        ensure_virtual_sources_table()  # should not raise

    @patch("data_agent.virtual_sources.get_engine")
    def test_reads_sql_file(self, mock_get):
        engine = MagicMock()
        conn = MagicMock()
        engine.connect.return_value.__enter__ = MagicMock(return_value=conn)
        engine.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_get.return_value = engine
        from data_agent.virtual_sources import ensure_virtual_sources_table
        ensure_virtual_sources_table()
        self.assertTrue(conn.execute.called)


# ---------------------------------------------------------------------------
# Schema mapping
# ---------------------------------------------------------------------------

class TestSchemaMapping(unittest.TestCase):
    def test_rename_columns(self):
        import pandas as pd
        from data_agent.virtual_sources import apply_schema_mapping
        df = pd.DataFrame({"old_name": [1], "keep": [2]})
        result = apply_schema_mapping(df, {"old_name": "new_name"})
        self.assertIn("new_name", result.columns)
        self.assertNotIn("old_name", result.columns)
        self.assertIn("keep", result.columns)

    def test_empty_mapping(self):
        import pandas as pd
        from data_agent.virtual_sources import apply_schema_mapping
        df = pd.DataFrame({"a": [1]})
        result = apply_schema_mapping(df, {})
        self.assertIn("a", result.columns)

    def test_mapping_nonexistent_col(self):
        import pandas as pd
        from data_agent.virtual_sources import apply_schema_mapping
        df = pd.DataFrame({"a": [1]})
        result = apply_schema_mapping(df, {"nonexistent": "b"})
        self.assertIn("a", result.columns)

    def test_auto_infer_false_by_default(self):
        import pandas as pd
        from data_agent.virtual_sources import apply_schema_mapping
        df = pd.DataFrame({"population_count": [1000]})
        result = apply_schema_mapping(df, {})
        # auto_infer defaults to False, so no renaming
        self.assertIn("population_count", result.columns)

    @patch("data_agent.virtual_sources._get_schema_embeddings")
    def test_auto_infer_with_embeddings(self, mock_emb):
        import pandas as pd
        from data_agent.virtual_sources import apply_schema_mapping
        # Simulate: "pop" column maps to "population" canonical via embeddings
        # Embeddings: col=[1,0], canonical_population=[0.9,0.1], others=[0,1]
        col_emb = [1.0, 0.0]
        pop_emb = [0.95, 0.05]  # high similarity
        other_emb = [0.0, 1.0]  # low similarity
        # all_texts = col_texts + canonical_descs
        from data_agent.virtual_sources import _CANONICAL_FIELDS
        n_canonical = len(_CANONICAL_FIELDS)
        # First is col embedding, then canonical embeddings
        mock_emb.return_value = [col_emb] + [other_emb] * 4 + [pop_emb] + [other_emb] * (n_canonical - 5 - 1)
        df = pd.DataFrame({"pop": [1000]})
        result = apply_schema_mapping(df, {}, auto_infer=True)
        # Should have attempted mapping (exact result depends on canonical order)
        mock_emb.assert_called_once()


class TestCosineFunction(unittest.TestCase):
    def test_identical_vectors(self):
        from data_agent.virtual_sources import _cosine_similarity
        self.assertAlmostEqual(_cosine_similarity([1, 0], [1, 0]), 1.0)

    def test_orthogonal_vectors(self):
        from data_agent.virtual_sources import _cosine_similarity
        self.assertAlmostEqual(_cosine_similarity([1, 0], [0, 1]), 0.0)

    def test_empty_vectors(self):
        from data_agent.virtual_sources import _cosine_similarity
        self.assertEqual(_cosine_similarity([], [1, 0]), 0.0)
        self.assertEqual(_cosine_similarity([1, 0], []), 0.0)

    def test_zero_vector(self):
        from data_agent.virtual_sources import _cosine_similarity
        self.assertEqual(_cosine_similarity([0, 0], [1, 0]), 0.0)


class TestCanonicalFields(unittest.TestCase):
    def test_has_essential_fields(self):
        from data_agent.virtual_sources import _CANONICAL_FIELDS
        for key in ("geometry", "population", "area", "elevation", "land_use",
                     "longitude", "latitude", "name", "id"):
            self.assertIn(key, _CANONICAL_FIELDS)

    def test_all_values_are_strings(self):
        from data_agent.virtual_sources import _CANONICAL_FIELDS
        for k, v in _CANONICAL_FIELDS.items():
            self.assertIsInstance(v, str)


class TestInferSchemaMapping(unittest.TestCase):
    def test_empty_columns(self):
        from data_agent.virtual_sources import infer_schema_mapping
        self.assertEqual(infer_schema_mapping([]), {})

    @patch("data_agent.virtual_sources._get_schema_embeddings", return_value=[])
    def test_api_failure_returns_empty(self, _):
        from data_agent.virtual_sources import infer_schema_mapping
        self.assertEqual(infer_schema_mapping(["pop"]), {})

    @patch("data_agent.virtual_sources._get_schema_embeddings")
    def test_high_similarity_maps(self, mock_emb):
        from data_agent.virtual_sources import infer_schema_mapping, _CANONICAL_FIELDS
        n = len(_CANONICAL_FIELDS)
        # Make "elev" map to "elevation" (index 7 in canonical)
        col_emb = [1.0, 0.0, 0.0]
        elev_emb = [0.98, 0.05, 0.0]  # high sim
        other_emb = [0.0, 0.0, 1.0]   # low sim
        canonical_list = list(_CANONICAL_FIELDS.keys())
        elev_idx = canonical_list.index("elevation")
        canon_embs = [other_emb] * n
        canon_embs[elev_idx] = elev_emb
        mock_emb.return_value = [col_emb] + canon_embs
        result = infer_schema_mapping(["elev"])
        self.assertEqual(result.get("elev"), "elevation")

    @patch("data_agent.virtual_sources._get_schema_embeddings")
    def test_low_similarity_no_map(self, mock_emb):
        from data_agent.virtual_sources import infer_schema_mapping, _CANONICAL_FIELDS
        n = len(_CANONICAL_FIELDS)
        # All similarities below threshold
        col_emb = [1.0, 0.0]
        other_emb = [0.0, 1.0]  # cosine sim = 0
        mock_emb.return_value = [col_emb] + [other_emb] * n
        result = infer_schema_mapping(["random_xyz"])
        self.assertEqual(result, {})


# ---------------------------------------------------------------------------
# Connectors (mocked httpx)
# ---------------------------------------------------------------------------

class TestWFSConnector(unittest.IsolatedAsyncioTestCase):
    @patch("httpx.AsyncClient")
    async def test_query_wfs_success(self, mock_client_cls):
        geojson = {
            "type": "FeatureCollection",
            "features": [
                {"type": "Feature", "geometry": {"type": "Point", "coordinates": [1, 2]},
                 "properties": {"name": "test"}}
            ],
        }
        mock_resp = MagicMock()
        mock_resp.json.return_value = geojson
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        from data_agent.virtual_sources import query_wfs
        gdf = await query_wfs(
            "https://example.com/wfs", {},
            {"feature_type": "topp:states", "version": "2.0.0"},
        )
        self.assertEqual(len(gdf), 1)
        self.assertIn("name", gdf.columns)

    @patch("httpx.AsyncClient")
    async def test_query_wfs_empty(self, mock_client_cls):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"type": "FeatureCollection", "features": []}
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        from data_agent.virtual_sources import query_wfs
        gdf = await query_wfs("https://example.com/wfs", {}, {"feature_type": "x"})
        self.assertEqual(len(gdf), 0)


class TestSTACConnector(unittest.IsolatedAsyncioTestCase):
    @patch("httpx.AsyncClient")
    async def test_search_stac_success(self, mock_client_cls):
        stac_resp = {
            "type": "FeatureCollection",
            "features": [{
                "id": "item-1",
                "bbox": [1, 2, 3, 4],
                "collection": "sentinel-2",
                "properties": {"datetime": "2024-06-01", "eo:cloud_cover": 5},
                "assets": {
                    "thumbnail": {"href": "https://example.com/thumb.png"},
                    "visual": {"href": "https://example.com/visual.tif"},
                },
            }],
        }
        mock_resp = MagicMock()
        mock_resp.json.return_value = stac_resp
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        from data_agent.virtual_sources import search_stac
        items = await search_stac(
            "https://earth-search.example.com/v1", {},
            {"collection_id": "sentinel-2"},
        )
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["id"], "item-1")
        self.assertEqual(items[0]["cloud_cover"], 5)

    @patch("httpx.AsyncClient")
    async def test_search_stac_empty(self, mock_client_cls):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"features": []}
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        from data_agent.virtual_sources import search_stac
        items = await search_stac("https://example.com/v1", {}, {})
        self.assertEqual(items, [])


class TestAPIConnector(unittest.IsolatedAsyncioTestCase):
    @patch("httpx.AsyncClient")
    async def test_query_api_get(self, mock_client_cls):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": {"features": [{"id": 1}]}}
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.request = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        from data_agent.virtual_sources import query_api
        result = await query_api(
            "https://api.example.com/data", {},
            {"method": "GET", "response_path": "data.features"},
        )
        self.assertEqual(result, {"results": [{"id": 1}]})


class TestOGCAPIConnector(unittest.IsolatedAsyncioTestCase):
    @patch("httpx.AsyncClient")
    async def test_query_ogc_api(self, mock_client_cls):
        geojson = {
            "features": [
                {"type": "Feature", "geometry": {"type": "Point", "coordinates": [1, 2]},
                 "properties": {"name": "building"}}
            ],
        }
        mock_resp = MagicMock()
        mock_resp.json.return_value = geojson
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        from data_agent.virtual_sources import query_ogc_api
        gdf = await query_ogc_api(
            "https://example.com/ogc", {},
            {"collection": "buildings"},
        )
        self.assertEqual(len(gdf), 1)


# ---------------------------------------------------------------------------
# Unified dispatcher
# ---------------------------------------------------------------------------

class TestDispatcher(unittest.IsolatedAsyncioTestCase):
    @patch("data_agent.virtual_sources.query_wfs", new_callable=AsyncMock)
    async def test_dispatch_wfs(self, mock_wfs):
        mock_wfs.return_value = "wfs-result"
        from data_agent.virtual_sources import query_virtual_source
        r = await query_virtual_source({
            "source_type": "wfs", "endpoint_url": "https://x.com",
            "auth_config": {}, "query_config": {"feature_type": "t"},
            "default_crs": "EPSG:4326",
        })
        self.assertEqual(r, "wfs-result")
        mock_wfs.assert_called_once()

    @patch("data_agent.virtual_sources.search_stac", new_callable=AsyncMock)
    async def test_dispatch_stac(self, mock_stac):
        mock_stac.return_value = []
        from data_agent.virtual_sources import query_virtual_source
        r = await query_virtual_source({
            "source_type": "stac", "endpoint_url": "https://x.com",
            "auth_config": {}, "query_config": {},
            "default_crs": "EPSG:4326",
        })
        self.assertEqual(r, [])

    @patch("data_agent.virtual_sources.query_api", new_callable=AsyncMock)
    async def test_dispatch_custom_api(self, mock_api):
        mock_api.return_value = {"result": "ok"}
        from data_agent.virtual_sources import query_virtual_source
        r = await query_virtual_source({
            "source_type": "custom_api", "endpoint_url": "https://x.com",
            "auth_config": {}, "query_config": {},
            "default_crs": "EPSG:4326",
        })
        self.assertEqual(r, {"result": "ok"})

    async def test_dispatch_unknown_type(self):
        from data_agent.virtual_sources import query_virtual_source
        r = await query_virtual_source({
            "source_type": "unknown", "endpoint_url": "https://x.com",
            "auth_config": {}, "query_config": {},
            "default_crs": "EPSG:4326",
        })
        self.assertEqual(r["status"], "error")


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

class TestHealthCheck(unittest.IsolatedAsyncioTestCase):
    @patch("data_agent.virtual_sources.get_engine")
    @patch("data_agent.virtual_sources.get_virtual_source")
    @patch("httpx.AsyncClient")
    async def test_health_check_healthy(self, mock_client_cls, mock_get_src, mock_eng):
        mock_get_src.return_value = {
            "source_type": "wfs", "endpoint_url": "https://x.com/wfs",
            "auth_config": {},
        }
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        engine = MagicMock()
        conn = MagicMock()
        engine.connect.return_value.__enter__ = MagicMock(return_value=conn)
        engine.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_eng.return_value = engine

        from data_agent.virtual_sources import check_source_health
        r = await check_source_health(1, "admin")
        self.assertEqual(r["health"], "healthy")

    @patch("data_agent.virtual_sources.get_virtual_source", return_value=None)
    async def test_health_check_not_found(self, _):
        from data_agent.virtual_sources import check_source_health
        r = await check_source_health(999, "admin")
        self.assertEqual(r["status"], "error")


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

class TestConstants(unittest.TestCase):
    def test_valid_source_types(self):
        from data_agent.virtual_sources import VALID_SOURCE_TYPES
        self.assertEqual(VALID_SOURCE_TYPES, {"wfs", "stac", "ogc_api", "custom_api"})

    def test_valid_auth_types(self):
        from data_agent.virtual_sources import VALID_AUTH_TYPES
        self.assertEqual(VALID_AUTH_TYPES, {"bearer", "basic", "apikey", "none"})


if __name__ == "__main__":
    unittest.main()
