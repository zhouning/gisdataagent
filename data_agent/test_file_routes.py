"""Tests for file management API routes (v15.1)."""
import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch


class TestFileRouteHelpers(unittest.TestCase):
    """Test helper functions in file_routes.py."""

    def test_safe_join_normal(self):
        from data_agent.api.file_routes import _safe_join
        result = _safe_join("/base", "sub/file.txt")
        self.assertIsNotNone(result)
        self.assertTrue(result.startswith(os.path.normpath("/base")))

    def test_safe_join_escape(self):
        from data_agent.api.file_routes import _safe_join
        result = _safe_join("/base", "../../etc/passwd")
        self.assertIsNone(result)

    def test_safe_join_dotdot(self):
        from data_agent.api.file_routes import _safe_join
        result = _safe_join("/base", "sub/../sub/file.txt")
        self.assertIsNotNone(result)

    def test_scan_dir(self):
        from data_agent.api.file_routes import _scan_dir
        with tempfile.TemporaryDirectory() as tmp:
            # Create files
            with open(os.path.join(tmp, "test.shp"), "w") as f:
                f.write("shp")
            with open(os.path.join(tmp, "test.dbf"), "w") as f:
                f.write("dbf")
            with open(os.path.join(tmp, "data.csv"), "w") as f:
                f.write("a,b\n1,2")
            os.makedirs(os.path.join(tmp, "subfolder"))

            entries = _scan_dir(tmp)
            names = [e["name"] for e in entries]
            # .dbf should be hidden (shapefile sidecar)
            self.assertIn("test.shp", names)
            self.assertNotIn("test.dbf", names)
            self.assertIn("data.csv", names)
            self.assertIn("subfolder", names)
            # Folder entry
            folder = next(e for e in entries if e["name"] == "subfolder")
            self.assertEqual(folder["type"], "folder")

    def test_group_shapefiles(self):
        from data_agent.api.file_routes import _group_shapefiles
        files = [
            ("roads.shp", b"shp"),
            ("roads.dbf", b"dbf"),
            ("roads.prj", b"prj"),
            ("data.csv", b"csv"),
        ]
        shp_groups, others = _group_shapefiles(files)
        self.assertIn("roads", shp_groups)
        self.assertEqual(len(shp_groups["roads"]), 3)
        self.assertEqual(len(others), 1)
        self.assertEqual(others[0][0], "data.csv")


class TestLocalDataDirs(unittest.TestCase):
    """Test LOCAL_DATA_DIRS parsing."""

    @patch.dict(os.environ, {"LOCAL_DATA_DIRS": ""})
    def test_empty(self):
        from data_agent.api.file_routes import _get_local_data_dirs
        self.assertEqual(_get_local_data_dirs(), [])

    @patch.dict(os.environ, {"LOCAL_DATA_DIRS": ""})
    def test_not_set(self):
        from data_agent.api.file_routes import _get_local_data_dirs
        os.environ.pop("LOCAL_DATA_DIRS", None)
        self.assertEqual(_get_local_data_dirs(), [])

    def test_single_path(self):
        from data_agent.api.file_routes import _get_local_data_dirs
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"LOCAL_DATA_DIRS": tmp}):
                dirs = _get_local_data_dirs()
                self.assertEqual(len(dirs), 1)
                self.assertEqual(dirs[0]["path"], tmp)

    def test_nonexistent_filtered(self):
        from data_agent.api.file_routes import _get_local_data_dirs
        with patch.dict(os.environ, {"LOCAL_DATA_DIRS": "/nonexistent/path/abc123"}):
            dirs = _get_local_data_dirs()
            self.assertEqual(len(dirs), 0)

    def test_multiple_paths(self):
        from data_agent.api.file_routes import _get_local_data_dirs
        with tempfile.TemporaryDirectory() as t1, tempfile.TemporaryDirectory() as t2:
            with patch.dict(os.environ, {"LOCAL_DATA_DIRS": f"{t1},{t2}"}):
                dirs = _get_local_data_dirs()
                self.assertEqual(len(dirs), 2)


class TestFileUploadAPI(unittest.TestCase):
    """Test upload endpoint logic."""

    def test_upload_route_registered(self):
        from data_agent.api.file_routes import get_file_routes
        routes = get_file_routes()
        paths = [r.path for r in routes]
        self.assertIn("/api/user/files/upload", paths)
        self.assertIn("/api/user/files/browse", paths)
        self.assertIn("/api/user/files/delete", paths)
        self.assertIn("/api/user/files/mkdir", paths)
        self.assertIn("/api/user/files/preview/{path:path}", paths)
        self.assertIn("/api/user/files/download-url", paths)
        self.assertIn("/api/local-data/browse", paths)
        self.assertIn("/api/local-data/import", paths)
        self.assertIn("/api/data/import-postgis", paths)

    def test_route_count(self):
        from data_agent.api.file_routes import get_file_routes
        self.assertEqual(len(get_file_routes()), 9)


class TestScanDirShapefileSidecars(unittest.TestCase):
    """Verify that shapefile sidecars are hidden in directory listings."""

    def test_hides_all_sidecar_types(self):
        from data_agent.api.file_routes import _scan_dir
        with tempfile.TemporaryDirectory() as tmp:
            for ext in [".shp", ".dbf", ".shx", ".prj", ".cpg", ".sbn", ".sbx"]:
                with open(os.path.join(tmp, f"test{ext}"), "w") as f:
                    f.write("x")
            entries = _scan_dir(tmp)
            names = [e["name"] for e in entries]
            self.assertEqual(names, ["test.shp"])

    def test_shows_non_shapefile_files(self):
        from data_agent.api.file_routes import _scan_dir
        with tempfile.TemporaryDirectory() as tmp:
            for name in ["data.csv", "map.geojson", "raster.tif"]:
                with open(os.path.join(tmp, name), "w") as f:
                    f.write("x")
            entries = _scan_dir(tmp)
            names = sorted(e["name"] for e in entries)
            self.assertEqual(names, ["data.csv", "map.geojson", "raster.tif"])


if __name__ == "__main__":
    unittest.main()
