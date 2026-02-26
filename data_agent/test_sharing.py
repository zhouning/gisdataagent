"""Tests for the result sharing module."""
import json
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


class TestSharing(unittest.TestCase):
    """Tests for sharing.py functions.

    These tests require a PostgreSQL database configured via env vars.
    They will be skipped if the database is not available.
    """

    @classmethod
    def setUpClass(cls):
        from data_agent.database_tools import get_db_connection_url
        cls.db_url = get_db_connection_url()
        if not cls.db_url:
            raise unittest.SkipTest("Database not configured — skipping sharing tests")

        from data_agent.sharing import ensure_share_links_table
        ensure_share_links_table()

        # Create a temp dir to simulate user upload dir
        cls.tmp_dir = tempfile.mkdtemp()
        cls._test_user = f"test_share_{int(time.time())}"
        cls._user_dir = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "data_agent", "uploads", cls._test_user
        )
        os.makedirs(cls._user_dir, exist_ok=True)

        # Create test files
        cls._html_file = "test_map_abc12345.html"
        cls._png_file = "test_chart_def67890.png"
        with open(os.path.join(cls._user_dir, cls._html_file), "w") as f:
            f.write("<html><body>Test Map</body></html>")
        with open(os.path.join(cls._user_dir, cls._png_file), "wb") as f:
            f.write(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

    @classmethod
    def tearDownClass(cls):
        # Clean up test files
        import shutil
        if hasattr(cls, '_user_dir') and os.path.exists(cls._user_dir):
            shutil.rmtree(cls._user_dir, ignore_errors=True)

        # Clean up test share links
        if cls.db_url:
            from sqlalchemy import create_engine, text
            from data_agent.database_tools import T_SHARE_LINKS
            try:
                engine = create_engine(cls.db_url)
                with engine.connect() as conn:
                    conn.execute(text(
                        f"DELETE FROM {T_SHARE_LINKS} WHERE owner_username = :u"
                    ), {"u": cls._test_user})
                    conn.commit()
            except Exception:
                pass

    def _set_user(self):
        """Set the test user context."""
        from data_agent.user_context import current_user_id
        current_user_id.set(self._test_user)

    def test_create_share_link_returns_token(self):
        """create_share_link returns a valid token and URL."""
        self._set_user()
        from data_agent.sharing import create_share_link
        result = create_share_link(
            title="Test Analysis",
            summary="Test summary text",
            files=[{"filename": self._html_file, "type": "html"}],
            pipeline_type="general",
        )
        self.assertEqual(result["status"], "success")
        self.assertIn("token", result)
        self.assertTrue(len(result["token"]) >= 12)
        self.assertTrue(result["url"].startswith("/s/"))

    def test_validate_token_success(self):
        """validate_share_token returns data for valid token."""
        self._set_user()
        from data_agent.sharing import create_share_link, validate_share_token
        link = create_share_link(
            title="Valid Link", summary="Summary",
            files=[{"filename": self._html_file, "type": "html"}],
            pipeline_type="general",
        )
        result = validate_share_token(link["token"])
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["data"]["title"], "Valid Link")
        self.assertEqual(result["data"]["pipeline_type"], "general")

    def test_expired_token(self):
        """Expired token returns 'expired' reason."""
        self._set_user()
        from data_agent.sharing import create_share_link, validate_share_token
        # Create with 0 hours (already expired — we use a negative trick)
        from sqlalchemy import create_engine, text
        from data_agent.database_tools import T_SHARE_LINKS
        import secrets
        token = secrets.token_urlsafe(12)
        engine = create_engine(self.db_url)
        with engine.connect() as conn:
            conn.execute(text(f"""
                INSERT INTO {T_SHARE_LINKS}
                    (token, owner_username, title, summary, files, pipeline_type, expires_at)
                VALUES (:t, :o, 'Expired', '', '[]'::jsonb, 'general',
                        NOW() - interval '1 hour')
            """), {"t": token, "o": self._test_user})
            conn.commit()

        result = validate_share_token(token)
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["reason"], "expired")

    def test_password_required(self):
        """Password-protected link requires password."""
        self._set_user()
        from data_agent.sharing import create_share_link, validate_share_token
        link = create_share_link(
            title="Protected", summary="Secret",
            files=[{"filename": self._html_file, "type": "html"}],
            pipeline_type="general", password="test1234",
        )
        # No password
        result = validate_share_token(link["token"])
        self.assertEqual(result["reason"], "password_required")

        # Wrong password
        result = validate_share_token(link["token"], "wrongpass")
        self.assertEqual(result["reason"], "wrong_password")

        # Correct password
        result = validate_share_token(link["token"], "test1234")
        self.assertEqual(result["status"], "success")

    def test_get_share_file_path_rejects_traversal(self):
        """get_share_file_path rejects directory traversal."""
        self._set_user()
        from data_agent.sharing import create_share_link, get_share_file_path
        link = create_share_link(
            title="Traversal Test", summary="",
            files=[{"filename": self._html_file, "type": "html"}],
            pipeline_type="general",
        )
        result = get_share_file_path(link["token"], "../../../etc/passwd")
        self.assertIsNone(result)
        result = get_share_file_path(link["token"], "..\\..\\secret.txt")
        self.assertIsNone(result)

    def test_get_share_file_path_rejects_non_whitelisted(self):
        """get_share_file_path rejects files not in whitelist."""
        self._set_user()
        from data_agent.sharing import create_share_link, get_share_file_path
        link = create_share_link(
            title="Whitelist Test", summary="",
            files=[{"filename": self._html_file, "type": "html"}],
            pipeline_type="general",
        )
        result = get_share_file_path(link["token"], "not_in_whitelist.csv")
        self.assertIsNone(result)

    def test_get_share_file_path_success(self):
        """get_share_file_path returns valid path for whitelisted file."""
        self._set_user()
        from data_agent.sharing import create_share_link, get_share_file_path
        link = create_share_link(
            title="File Serve Test", summary="",
            files=[{"filename": self._html_file, "type": "html"}],
            pipeline_type="general",
        )
        result = get_share_file_path(link["token"], self._html_file)
        self.assertIsNotNone(result)
        self.assertTrue(os.path.exists(result))
        self.assertTrue(result.endswith(self._html_file))

    def test_delete_share_link(self):
        """delete_share_link removes the link."""
        self._set_user()
        from data_agent.sharing import create_share_link, delete_share_link, validate_share_token
        link = create_share_link(
            title="To Delete", summary="",
            files=[], pipeline_type="general",
        )
        token = link["token"]
        result = delete_share_link(token)
        self.assertEqual(result["status"], "success")

        # Verify deleted
        result = validate_share_token(token)
        self.assertEqual(result["reason"], "not_found")


class TestExpandShapefileSidecars(unittest.TestCase):
    """Test shapefile sidecar expansion (no DB required)."""

    def test_expand_adds_sidecars(self):
        from data_agent.sharing import expand_shapefile_sidecars
        files = [{"filename": "data.shp", "type": "shp"}]
        result = expand_shapefile_sidecars(files)
        names = {f["filename"] for f in result}
        self.assertIn("data.shp", names)
        self.assertIn("data.dbf", names)
        self.assertIn("data.shx", names)
        self.assertIn("data.prj", names)
        self.assertIn("data.cpg", names)

    def test_no_duplication(self):
        from data_agent.sharing import expand_shapefile_sidecars
        files = [
            {"filename": "data.shp", "type": "shp"},
            {"filename": "data.dbf", "type": "dbf"},
        ]
        result = expand_shapefile_sidecars(files)
        dbf_count = sum(1 for f in result if f["filename"] == "data.dbf")
        self.assertEqual(dbf_count, 1)

    def test_non_shp_unchanged(self):
        from data_agent.sharing import expand_shapefile_sidecars
        files = [{"filename": "report.csv", "type": "csv"}]
        result = expand_shapefile_sidecars(files)
        self.assertEqual(len(result), 1)


if __name__ == "__main__":
    unittest.main()
