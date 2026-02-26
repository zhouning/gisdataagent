"""Tests for v4.0 new features: driving distance, user file mgmt, self-correction, basemap helper."""
import unittest
import os
import tempfile
import shutil
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))


class TestDrivingDistance(unittest.TestCase):
    """Test calculate_driving_distance (Amap API)."""

    def test_driving_distance_basic(self):
        from data_agent.geocoding import calculate_driving_distance
        # Beijing (Tiananmen) → Shanghai (The Bund)
        result = calculate_driving_distance(
            origin_lng=116.397, origin_lat=39.908,
            dest_lng=121.490, dest_lat=31.236
        )
        print(f"\nBeijing → Shanghai:\n{result}")
        self.assertIn("直线距离", result)
        # If API key is configured, should have driving distance
        if os.environ.get("GAODE_API_KEY"):
            self.assertIn("驾车距离", result)
            self.assertIn("预计驾车时间", result)
        else:
            self.assertIn("未配置", result)

    def test_driving_distance_same_city(self):
        from data_agent.geocoding import calculate_driving_distance
        # Within Beijing: Tiananmen → Beijing West Station
        result = calculate_driving_distance(
            origin_lng=116.397, origin_lat=39.908,
            dest_lng=116.322, dest_lat=39.896
        )
        print(f"\nTiananmen → Beijing West:\n{result}")
        self.assertIn("直线距离", result)

    def test_haversine_accuracy(self):
        from data_agent.geocoding import calculate_driving_distance
        # Known distance: Beijing-Shanghai ~1060 km straight line
        result = calculate_driving_distance(
            origin_lng=116.397, origin_lat=39.908,
            dest_lng=121.490, dest_lat=31.236
        )
        # Extract straight-line distance
        for line in result.split("\n"):
            if "直线距离" in line:
                dist_str = line.split(":")[1].strip().replace("km", "").strip()
                dist = float(dist_str)
                self.assertAlmostEqual(dist, 1068, delta=50)
                print(f"\nHaversine distance: {dist} km (expected ~1068 km)")
                break


class TestUserFileManagement(unittest.TestCase):
    """Test list_user_files and delete_user_file."""

    def setUp(self):
        # Create a temporary user dir and mock user context
        self.test_dir = tempfile.mkdtemp(prefix="test_user_files_")

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_list_user_files(self):
        from data_agent.agent import list_user_files
        from data_agent import user_context

        # Create some test files
        for name in ["result_abc.csv", "map_def.html", "data_ghi.shp"]:
            with open(os.path.join(self.test_dir, name), "w") as f:
                f.write("test content")

        # Mock get_user_upload_dir
        original_fn = user_context.get_user_upload_dir
        user_context.get_user_upload_dir = lambda: self.test_dir

        try:
            result = list_user_files()
            print(f"\nlist_user_files result:\n{result}")
            self.assertIn("3 个文件", result)
            self.assertIn("result_abc.csv", result)
            self.assertIn("map_def.html", result)
        finally:
            user_context.get_user_upload_dir = original_fn

    def test_delete_user_file(self):
        from data_agent.agent import delete_user_file
        from data_agent import user_context

        # Create a test file
        test_file = os.path.join(self.test_dir, "to_delete.csv")
        with open(test_file, "w") as f:
            f.write("data")

        original_fn = user_context.get_user_upload_dir
        user_context.get_user_upload_dir = lambda: self.test_dir

        try:
            # Delete it
            result = delete_user_file("to_delete.csv")
            print(f"\ndelete result: {result}")
            self.assertIn("删除", result)
            self.assertFalse(os.path.exists(test_file))

            # Try deleting non-existent file
            # Note: when OBS is configured, S3 delete returns success for non-existent keys
            result2 = delete_user_file("no_such_file.csv")
            self.assertTrue("不存在" in result2 or "删除" in result2)
        finally:
            user_context.get_user_upload_dir = original_fn

    def test_delete_shapefile_sidecars(self):
        from data_agent.agent import delete_user_file
        from data_agent import user_context

        # Create SHP + sidecar files
        for ext in [".shp", ".dbf", ".shx", ".prj", ".cpg"]:
            with open(os.path.join(self.test_dir, f"test_data{ext}"), "w") as f:
                f.write("x")

        original_fn = user_context.get_user_upload_dir
        user_context.get_user_upload_dir = lambda: self.test_dir

        try:
            result = delete_user_file("test_data.shp")
            print(f"\nSHP delete result: {result}")
            self.assertIn("删除", result)
            # All sidecar files should be deleted too
            for ext in [".shp", ".dbf", ".shx", ".prj", ".cpg"]:
                self.assertFalse(
                    os.path.exists(os.path.join(self.test_dir, f"test_data{ext}")),
                    f"Sidecar {ext} still exists"
                )
        finally:
            user_context.get_user_upload_dir = original_fn

    def test_path_traversal_blocked(self):
        from data_agent.agent import delete_user_file
        from data_agent import user_context

        original_fn = user_context.get_user_upload_dir
        user_context.get_user_upload_dir = lambda: self.test_dir

        try:
            result = delete_user_file("../../etc/passwd")
            print(f"\nPath traversal result: {result}")
            self.assertIn("安全限制", result)
        finally:
            user_context.get_user_upload_dir = original_fn


class TestSelfCorrectionCallback(unittest.TestCase):
    """Test _self_correction_after_tool callback logic."""

    def test_non_error_passthrough(self):
        from data_agent.agent import _self_correction_after_tool
        # Non-error response should return None (no modification)
        result = _self_correction_after_tool(
            tool=type('T', (), {'name': 'test'})(),
            args={},
            tool_context=type('TC', (), {})(),
            tool_response={"status": "success", "result": "ok"}
        )
        self.assertIsNone(result)

    def test_column_error_hint(self):
        from data_agent.agent import _self_correction_after_tool
        result = _self_correction_after_tool(
            tool=type('T', (), {'name': 'test'})(),
            args={},
            tool_context=type('TC', (), {})(),
            tool_response={"error": "Column 'area' not found in table"}
        )
        self.assertIsNotNone(result)
        self.assertIn("describe_table", result.get("_correction_hint", ""))
        print(f"\nColumn error hint: {result.get('_correction_hint')}")

    def test_file_error_hint(self):
        from data_agent.agent import _self_correction_after_tool
        result = _self_correction_after_tool(
            tool=type('T', (), {'name': 'test2'})(),
            args={},
            tool_context=type('TC', (), {})(),
            tool_response={"result": "Error: file 'data.shp' not found"}
        )
        self.assertIsNotNone(result)
        self.assertIn("list_user_files", result.get("_correction_hint", ""))
        print(f"\nFile error hint: {result.get('_correction_hint')}")

    def test_retry_limit(self):
        from data_agent.agent import _self_correction_after_tool, _tool_retry_counts
        # Same context + tool should hit retry limit after 3 attempts
        ctx = type('TC', (), {})()
        tool = type('T', (), {'name': 'retry_test'})()
        for i in range(4):
            result = _self_correction_after_tool(
                tool=tool, args={}, tool_context=ctx,
                tool_response={"error": "Column not found"}
            )
        self.assertIn("停止重试", result.get("_hint", ""))
        print(f"\nRetry limit hit: {result.get('_hint')}")


class TestBasemapHelper(unittest.TestCase):
    """Test _add_basemap_layers helper."""

    def test_basemap_without_tianditu(self):
        import folium
        from data_agent.agent import _add_basemap_layers, TIANDITU_TOKEN

        m = folium.Map(location=[39.9, 116.4], zoom_start=10)
        _add_basemap_layers(m)

        html = m._repr_html_()
        self.assertIn("openstreetmap.org", html)
        self.assertIn("cartocdn.com", html)
        self.assertIn("autonavi.com", html)

        if TIANDITU_TOKEN:
            self.assertIn("tianditu", html)
            print("\nTianditu layers: ENABLED")
        else:
            print("\nTianditu layers: DISABLED (no token)")
        print("Basemap layers added successfully")


if __name__ == "__main__":
    unittest.main()
