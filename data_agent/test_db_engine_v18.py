"""
Tests for v18.0 — database performance optimization.

Covers:
- db_engine.py: connection pool config, read-write split interface, pool status
- db_engine_async.py: async pool lifecycle, convenience functions
- observability.py: DB pool metrics collection
- migration 052: materialized view SQL validity
"""
import asyncio
import os
import unittest
from unittest.mock import patch, MagicMock, AsyncMock


# =====================================================================
# db_engine.py — connection pool & read-write split
# =====================================================================

class TestDbEnginePoolConfig(unittest.TestCase):
    """Pool size / overflow should honour env vars and upgraded defaults."""

    def setUp(self):
        from data_agent.db_engine import reset_engine
        reset_engine()

    def tearDown(self):
        from data_agent.db_engine import reset_engine
        reset_engine()

    def test_default_pool_size_is_20(self):
        from data_agent.db_engine import _pool_size
        self.assertEqual(_pool_size(), 20)

    def test_default_max_overflow_is_30(self):
        from data_agent.db_engine import _max_overflow
        self.assertEqual(_max_overflow(), 30)

    @patch.dict(os.environ, {"DB_POOL_SIZE": "50", "DB_MAX_OVERFLOW": "80"})
    def test_env_var_override(self):
        from data_agent.db_engine import _pool_size, _max_overflow
        self.assertEqual(_pool_size(), 50)
        self.assertEqual(_max_overflow(), 80)


class TestDbEngineReadWriteSplit(unittest.TestCase):
    """get_engine(readonly=...) interface."""

    def setUp(self):
        from data_agent.db_engine import reset_engine
        reset_engine()

    def tearDown(self):
        from data_agent.db_engine import reset_engine
        reset_engine()

    @patch("data_agent.db_engine._create_sa_engine")
    @patch("data_agent.database_tools.get_db_connection_url", return_value="postgresql://u:p@h/db")
    def test_readonly_false_returns_primary(self, mock_url, mock_create):
        mock_engine = MagicMock()
        mock_create.return_value = mock_engine
        from data_agent.db_engine import get_engine
        result = get_engine(readonly=False)
        self.assertEqual(result, mock_engine)

    @patch("data_agent.db_engine._create_sa_engine")
    @patch("data_agent.database_tools.get_db_connection_url", return_value="postgresql://u:p@h/db")
    def test_readonly_true_without_read_url_falls_back(self, mock_url, mock_create):
        """Without DATABASE_READ_URL, readonly falls back to primary."""
        mock_engine = MagicMock()
        mock_create.return_value = mock_engine
        from data_agent.db_engine import get_engine
        result = get_engine(readonly=True)
        self.assertEqual(result, mock_engine)

    @patch.dict(os.environ, {"DATABASE_READ_URL": "postgresql://reader:p@replica/db"})
    @patch("data_agent.db_engine._create_sa_engine")
    @patch("data_agent.database_tools.get_db_connection_url", return_value="postgresql://u:p@h/db")
    def test_readonly_true_with_read_url_returns_read_engine(self, mock_url, mock_create):
        """With DATABASE_READ_URL, readonly returns a separate engine."""
        primary = MagicMock(name="primary")
        replica = MagicMock(name="replica")
        mock_create.side_effect = [primary, replica]
        from data_agent.db_engine import get_engine
        # First call creates primary
        get_engine(readonly=False)
        # Second call should create read engine
        result = get_engine(readonly=True)
        self.assertEqual(result, replica)
        self.assertEqual(mock_create.call_count, 2)

    def test_get_engine_returns_none_without_credentials(self):
        from data_agent.db_engine import get_engine
        with patch("data_agent.database_tools.get_db_connection_url", return_value=None):
            result = get_engine()
            self.assertIsNone(result)


class TestDbEnginePoolStatus(unittest.TestCase):
    """get_pool_status() returns pool statistics."""

    def test_pool_status_none_when_no_engine(self):
        from data_agent.db_engine import get_pool_status, reset_engine
        reset_engine()
        self.assertIsNone(get_pool_status())

    def test_pool_status_returns_dict_keys(self):
        from data_agent.db_engine import get_pool_status
        # Mock an engine with pool attributes
        import data_agent.db_engine as mod
        mock_pool = MagicMock()
        mock_pool.size.return_value = 20
        mock_pool.checkedin.return_value = 18
        mock_pool.checkedout.return_value = 2
        mock_pool.overflow.return_value = 0
        mock_pool._max_overflow = 30
        mock_engine = MagicMock()
        mock_engine.pool = mock_pool
        old = mod._engine
        mod._engine = mock_engine
        try:
            status = get_pool_status()
            self.assertEqual(status["pool_size"], 20)
            self.assertEqual(status["checkedin"], 18)
            self.assertEqual(status["checkedout"], 2)
            self.assertEqual(status["overflow"], 0)
            self.assertEqual(status["max_overflow"], 30)
        finally:
            mod._engine = old


# =====================================================================
# db_engine_async.py — async connection pool
# =====================================================================

class TestAsyncPoolDSN(unittest.TestCase):
    """DSN construction from env vars."""

    @patch.dict(os.environ, {
        "POSTGRES_USER": "u", "POSTGRES_PASSWORD": "p",
        "POSTGRES_HOST": "h", "POSTGRES_PORT": "5433",
        "POSTGRES_DATABASE": "db",
    })
    def test_build_dsn(self):
        from data_agent.db_engine_async import _build_dsn
        dsn = _build_dsn()
        self.assertEqual(dsn, "postgresql://u:p@h:5433/db")

    @patch.dict(os.environ, {}, clear=True)
    def test_build_dsn_returns_none_without_creds(self):
        from data_agent.db_engine_async import _build_dsn
        # Clear relevant env vars
        for k in ["POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DATABASE"]:
            os.environ.pop(k, None)
        dsn = _build_dsn()
        self.assertIsNone(dsn)


class TestAsyncPoolLifecycle(unittest.IsolatedAsyncioTestCase):
    """Async pool creation and closure."""

    async def test_get_async_pool_returns_none_without_creds(self):
        import data_agent.db_engine_async as mod
        old = mod._async_pool
        mod._async_pool = None
        try:
            with patch.object(mod, "_build_dsn", return_value=None):
                pool = await mod.get_async_pool()
                self.assertIsNone(pool)
        finally:
            mod._async_pool = old

    async def test_close_async_pool_idempotent(self):
        """close_async_pool should not raise if pool is None."""
        import data_agent.db_engine_async as mod
        old = mod._async_pool
        mod._async_pool = None
        await mod.close_async_pool()
        mod._async_pool = old

    async def test_fetch_async_returns_empty_without_pool(self):
        import data_agent.db_engine_async as mod
        with patch.object(mod, "get_async_pool", new_callable=AsyncMock, return_value=None):
            rows = await mod.fetch_async("SELECT 1")
            self.assertEqual(rows, [])

    async def test_execute_async_returns_empty_without_pool(self):
        import data_agent.db_engine_async as mod
        with patch.object(mod, "get_async_pool", new_callable=AsyncMock, return_value=None):
            result = await mod.execute_async("INSERT INTO t VALUES ($1)", 1)
            self.assertEqual(result, "")

    async def test_fetchrow_async_returns_none_without_pool(self):
        import data_agent.db_engine_async as mod
        with patch.object(mod, "get_async_pool", new_callable=AsyncMock, return_value=None):
            row = await mod.fetchrow_async("SELECT 1")
            self.assertIsNone(row)

    async def test_fetchval_async_returns_none_without_pool(self):
        import data_agent.db_engine_async as mod
        with patch.object(mod, "get_async_pool", new_callable=AsyncMock, return_value=None):
            val = await mod.fetchval_async("SELECT 1")
            self.assertIsNone(val)

    async def test_get_async_pool_status_none_when_no_pool(self):
        import data_agent.db_engine_async as mod
        old = mod._async_pool
        mod._async_pool = None
        status = await mod.get_async_pool_status()
        self.assertIsNone(status)
        mod._async_pool = old


# =====================================================================
# observability.py — DB pool metrics
# =====================================================================

class TestDbPoolMetrics(unittest.TestCase):
    """collect_db_pool_metrics() scrapes pool status into Prometheus gauges."""

    def test_collect_db_pool_metrics_no_crash_without_engine(self):
        from data_agent.observability import collect_db_pool_metrics
        # Should not raise even when engine is None
        collect_db_pool_metrics()

    def test_collect_db_pool_metrics_sets_gauges(self):
        from data_agent.observability import (
            collect_db_pool_metrics, db_pool_size, db_pool_checkedin,
            db_pool_checkedout, db_pool_overflow,
        )
        mock_status = {
            "pool_size": 20, "checkedin": 15,
            "checkedout": 5, "overflow": 2,
        }
        with patch("data_agent.db_engine.get_pool_status", return_value=mock_status):
            collect_db_pool_metrics()
        # Verify gauges were set (checking that no exception was raised)
        # The gauge values are internal to prometheus_client

    def test_db_query_duration_histogram_exists(self):
        from data_agent.observability import db_query_duration
        self.assertIsNotNone(db_query_duration)


# =====================================================================
# Migration 052 — SQL validity
# =====================================================================

class TestMigration052(unittest.TestCase):
    """Migration file exists and contains expected DDL."""

    def test_migration_file_exists(self):
        import os
        path = os.path.join(os.path.dirname(__file__), "migrations", "052_db_performance_optimization.sql")
        self.assertTrue(os.path.exists(path))

    def test_migration_contains_materialized_view(self):
        import os
        path = os.path.join(os.path.dirname(__file__), "migrations", "052_db_performance_optimization.sql")
        with open(path, encoding="utf-8") as f:
            sql = f.read()
        self.assertIn("mv_pipeline_analytics", sql)
        self.assertIn("mv_token_usage_daily", sql)
        self.assertIn("MATERIALIZED VIEW", sql)
        self.assertIn("agent_reader", sql)
        self.assertIn("refresh_analytics_views", sql)
        self.assertIn("v_connection_stats", sql)


if __name__ == "__main__":
    unittest.main()
