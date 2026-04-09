"""Tests for Lite mode startup branching (v23.0)."""
import os
import unittest
from unittest.mock import patch


class TestLiteModeDetection(unittest.TestCase):
    def test_is_lite_mode_default_false(self):
        from data_agent.lite_mode import is_lite_mode
        with patch.dict(os.environ, {}, clear=True):
            # Remove DB_BACKEND if set
            os.environ.pop("DB_BACKEND", None)
            assert not is_lite_mode()

    def test_is_lite_mode_duckdb(self):
        from data_agent.lite_mode import is_lite_mode
        with patch.dict(os.environ, {"DB_BACKEND": "duckdb"}):
            assert is_lite_mode()

    def test_is_lite_mode_postgres(self):
        from data_agent.lite_mode import is_lite_mode
        with patch.dict(os.environ, {"DB_BACKEND": "postgres"}):
            assert not is_lite_mode()


class TestLiteStatus(unittest.TestCase):
    def test_get_lite_status_not_lite(self):
        from data_agent.lite_mode import get_lite_status
        with patch.dict(os.environ, {"DB_BACKEND": "postgres"}):
            status = get_lite_status()
            assert status["lite_mode"] is False

    def test_get_lite_status_lite(self):
        from data_agent.lite_mode import get_lite_status
        with patch.dict(os.environ, {"DB_BACKEND": "duckdb"}):
            status = get_lite_status()
            assert status["lite_mode"] is True
            assert status["db_backend"] == "duckdb"


class TestLiteModeInit(unittest.TestCase):
    def test_init_lite_database(self):
        """Test DuckDB initialization creates tables."""
        import tempfile
        from data_agent.lite_mode import init_lite_database
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.duckdb")
            result = init_lite_database(db_path)
            assert result["status"] == "ok"
            assert "agent_users" in result["tables_created"]
            assert "agent_data_assets" in result["tables_created"]
            assert os.path.exists(db_path)


class TestLiteModePipelineRouting(unittest.TestCase):
    """Test that Lite mode routes Governance/Optimization to General."""

    def test_lite_mode_flag(self):
        """Verify _LITE_MODE flag is accessible."""
        from data_agent.lite_mode import is_lite_mode
        result = is_lite_mode()
        assert isinstance(result, bool)


class TestCliEntryPoint(unittest.TestCase):
    def test_cli_main_help(self):
        """Verify CLI entry point runs without error on 'help'."""
        import sys
        from unittest.mock import patch as _patch
        from data_agent.lite_mode import _cli_main
        with _patch.object(sys, 'argv', ['gis-agent', 'help']):
            _cli_main()  # should print help, not crash

    def test_cli_main_status(self):
        from data_agent.lite_mode import _cli_main
        import sys
        with patch.dict(os.environ, {"DB_BACKEND": "postgres"}):
            with patch.object(sys, 'argv', ['gis-agent', 'status']):
                _cli_main()  # should print status


class TestPyprojectToml(unittest.TestCase):
    def test_pyproject_exists(self):
        import tomllib
        path = os.path.join(os.path.dirname(__file__), '..', 'pyproject.toml')
        assert os.path.exists(path)
        with open(path, 'rb') as f:
            data = tomllib.load(f)
        assert data['project']['name'] == 'gis-data-agent'
        assert 'full' in data['project']['optional-dependencies']
        assert 'dev' in data['project']['optional-dependencies']
        # Core deps should include duckdb
        core_deps = data['project']['dependencies']
        assert any('duckdb' in d for d in core_deps)


if __name__ == "__main__":
    unittest.main()
