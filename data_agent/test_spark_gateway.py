"""Tests for SparkGateway and SparkToolset (v15.0)."""
import unittest
from unittest.mock import patch


class TestDetermineTier(unittest.TestCase):
    def test_l1_small(self):
        from data_agent.spark_gateway import determine_tier, ExecutionTier
        self.assertEqual(determine_tier(data_size_bytes=50 * 1024 * 1024), ExecutionTier.L1_INSTANT)

    def test_l2_medium(self):
        from data_agent.spark_gateway import determine_tier, ExecutionTier
        self.assertEqual(determine_tier(data_size_bytes=500 * 1024 * 1024), ExecutionTier.L2_QUEUE)

    def test_l3_large(self):
        from data_agent.spark_gateway import determine_tier, ExecutionTier
        self.assertEqual(determine_tier(data_size_bytes=2000 * 1024 * 1024), ExecutionTier.L3_DISTRIBUTED)

    def test_zero_size(self):
        from data_agent.spark_gateway import determine_tier, ExecutionTier
        self.assertEqual(determine_tier(data_size_bytes=0), ExecutionTier.L1_INSTANT)


class TestSparkGateway(unittest.TestCase):
    def test_singleton(self):
        from data_agent.spark_gateway import get_spark_gateway
        g1 = get_spark_gateway()
        g2 = get_spark_gateway()
        self.assertIs(g1, g2)

    def test_list_jobs_empty(self):
        from data_agent.spark_gateway import SparkGateway
        gw = SparkGateway()
        self.assertEqual(gw.list_jobs(), [])


class TestSparkJob(unittest.TestCase):
    def test_job_creation(self):
        from data_agent.spark_gateway import SparkJob, ExecutionTier
        job = SparkJob(job_id="test_1", task_type="describe", tier=ExecutionTier.L1_INSTANT)
        self.assertEqual(job.status, "submitted")
        self.assertEqual(job.tier, ExecutionTier.L1_INSTANT)


class TestSparkSubmitTask(unittest.IsolatedAsyncioTestCase):
    @patch("data_agent.utils._load_spatial_data")
    async def test_submit_describe(self, mock_load):
        import geopandas as gpd
        from shapely.geometry import Point
        mock_load.return_value = gpd.GeoDataFrame(
            {"a": [1, 2]}, geometry=[Point(0, 0), Point(1, 1)], crs="EPSG:4326"
        )
        from data_agent.toolsets.spark_tools import spark_submit_task
        import json
        result = json.loads(await spark_submit_task("/test.shp", "describe"))
        self.assertIn(result["status"], ("completed", "ok"))
        self.assertEqual(result["tier"], "instant")


class TestSparkCheckTier(unittest.TestCase):
    @patch("os.path.exists", return_value=True)
    @patch("os.path.getsize", return_value=50 * 1024 * 1024)
    def test_check_small(self, mock_size, mock_exists):
        from data_agent.toolsets.spark_tools import spark_check_tier
        import json
        result = json.loads(spark_check_tier("/test.shp"))
        self.assertEqual(result["tier"], "instant")


class TestConstants(unittest.TestCase):
    def test_execution_tiers(self):
        from data_agent.spark_gateway import ExecutionTier
        self.assertEqual(len(ExecutionTier), 3)

    def test_backends(self):
        from data_agent.spark_gateway import SparkBackend
        self.assertIn("local", [b.value for b in SparkBackend])


if __name__ == "__main__":
    unittest.main()
