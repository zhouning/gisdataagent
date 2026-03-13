"""Tests for Advanced Analysis Engine (v8.0.4).

Covers: time series forecast, spatial trend, what-if, scenario compare,
network centrality, community detection, accessibility analysis.
All tests use synthetic data — no DB mocks needed.
"""
import json
import os
import tempfile
import unittest

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import Point, Polygon, LineString, box


# ---------------------------------------------------------------------------
# Helpers — create synthetic data files for tests
# ---------------------------------------------------------------------------

def _make_ts_csv(n=30):
    """Create a simple time-series CSV and return its path."""
    dates = pd.date_range("2020-01-01", periods=n, freq="ME")
    values = np.cumsum(np.random.RandomState(42).randn(n)) + 100
    df = pd.DataFrame({"date": dates, "value": np.round(values, 2)})
    path = os.path.join(tempfile.gettempdir(), "ts_test.csv")
    df.to_csv(path, index=False)
    return path


def _make_polygon_gdf(n=20):
    """Create a GeoDataFrame with adjacent square polygons and a numeric column."""
    rng = np.random.RandomState(42)
    # Make touching polygons (full 1x1 grid)
    polys = [box(i % 5, i // 5, i % 5 + 1, i // 5 + 1) for i in range(n)]
    gdf = gpd.GeoDataFrame(
        {"value": rng.rand(n) * 100, "pop": rng.randint(10, 1000, n)},
        geometry=polys,
        crs="EPSG:4326",
    )
    path = os.path.join(tempfile.gettempdir(), "poly_test.geojson")
    gdf.to_file(path, driver="GeoJSON")
    return path, gdf


def _make_line_gdf():
    """Create a simple road-network-like line GeoDataFrame."""
    lines = [
        LineString([(0, 0), (1, 0)]),
        LineString([(1, 0), (2, 0)]),
        LineString([(1, 0), (1, 1)]),
        LineString([(2, 0), (2, 1)]),
        LineString([(1, 1), (2, 1)]),
    ]
    gdf = gpd.GeoDataFrame(
        {"road_id": range(5), "length": [1.0, 1.0, 1.0, 1.0, 1.0]},
        geometry=lines,
        crs="EPSG:3857",
    )
    path = os.path.join(tempfile.gettempdir(), "line_test.geojson")
    gdf.to_file(path, driver="GeoJSON")
    return path


def _make_point_gdf(n=15):
    """Create point GeoDataFrame for accessibility tests."""
    rng = np.random.RandomState(42)
    pts = [Point(rng.rand() * 100, rng.rand() * 100) for _ in range(n)]
    gdf = gpd.GeoDataFrame(
        {"id": range(n), "val": rng.rand(n) * 50},
        geometry=pts,
        crs="EPSG:3857",
    )
    path = os.path.join(tempfile.gettempdir(), "point_test.geojson")
    gdf.to_file(path, driver="GeoJSON")
    return path


def _make_facility_gdf():
    """Create facility points for accessibility analysis."""
    pts = [Point(25, 25), Point(75, 75)]
    gdf = gpd.GeoDataFrame(
        {"name": ["Hospital A", "Hospital B"]},
        geometry=pts,
        crs="EPSG:3857",
    )
    path = os.path.join(tempfile.gettempdir(), "facility_test.geojson")
    gdf.to_file(path, driver="GeoJSON")
    return path


# ---------------------------------------------------------------------------
# Tests — Category 1: Spatiotemporal
# ---------------------------------------------------------------------------

class TestTimeSeriesForecast(unittest.TestCase):
    """Test time_series_forecast with synthetic time-series data."""

    def setUp(self):
        self.csv_path = _make_ts_csv(30)

    def test_auto_method(self):
        from data_agent.advanced_analysis import time_series_forecast
        result = time_series_forecast(self.csv_path, "date", "value", periods=6, method="auto")
        self.assertIsInstance(result, dict)
        self.assertIn("forecast_path", result)
        self.assertIn("plot_path", result)
        self.assertTrue(os.path.exists(result["forecast_path"]))
        self.assertTrue(os.path.exists(result["plot_path"]))
        self.assertEqual(result["summary"]["forecast_periods"], 6)

    def test_arima_method(self):
        from data_agent.advanced_analysis import time_series_forecast
        result = time_series_forecast(self.csv_path, "date", "value", periods=3, method="arima")
        self.assertIsInstance(result, dict)
        self.assertIn("ARIMA", result["summary"]["model"])

    def test_ets_method(self):
        from data_agent.advanced_analysis import time_series_forecast
        result = time_series_forecast(self.csv_path, "date", "value", periods=3, method="ets")
        self.assertIsInstance(result, dict)
        self.assertIn("ETS", result["summary"]["model"])

    def test_missing_column(self):
        from data_agent.advanced_analysis import time_series_forecast
        result = time_series_forecast(self.csv_path, "date", "nonexistent")
        self.assertIsInstance(result, str)
        self.assertIn("Error", result)

    def test_too_few_points(self):
        path = _make_ts_csv(3)
        from data_agent.advanced_analysis import time_series_forecast
        result = time_series_forecast(path, "date", "value")
        self.assertIsInstance(result, str)
        self.assertIn("Error", result)


class TestSpatialTrendAnalysis(unittest.TestCase):
    """Test spatial_trend_analysis with polygon GeoDataFrame."""

    def setUp(self):
        self.geojson_path, _ = _make_polygon_gdf(20)

    def test_ols_trend(self):
        from data_agent.advanced_analysis import spatial_trend_analysis
        result = spatial_trend_analysis(self.geojson_path, "value")
        self.assertIsInstance(result, dict)
        self.assertIn("trend_path", result)
        self.assertIn("plot_path", result)
        self.assertIn("coefficients", result)
        self.assertTrue(os.path.exists(result["trend_path"]))

    def test_missing_column(self):
        from data_agent.advanced_analysis import spatial_trend_analysis
        result = spatial_trend_analysis(self.geojson_path, "nonexistent")
        self.assertIsInstance(result, str)
        self.assertIn("Error", result)

    def test_moran_computed(self):
        from data_agent.advanced_analysis import spatial_trend_analysis
        result = spatial_trend_analysis(self.geojson_path, "value")
        # Moran's I should be computed for spatial data with enough features
        if isinstance(result, dict):
            self.assertIn("moran_i", result)


# ---------------------------------------------------------------------------
# Tests — Category 2: Scenario Simulation
# ---------------------------------------------------------------------------

class TestWhatIfAnalysis(unittest.TestCase):
    """Test what_if_analysis with synthetic data."""

    def setUp(self):
        self.geojson_path, _ = _make_polygon_gdf(20)

    def test_basic_scenario(self):
        from data_agent.advanced_analysis import what_if_analysis
        result = what_if_analysis(
            self.geojson_path,
            json.dumps({"pop": 1.5}),
            "pop",
        )
        self.assertIsInstance(result, dict)
        self.assertIn("result_path", result)
        self.assertEqual(result["summary"]["delta_pct"], 50.0)

    def test_multiple_factors(self):
        from data_agent.advanced_analysis import what_if_analysis
        result = what_if_analysis(
            self.geojson_path,
            json.dumps({"pop": 2.0, "value": 0.5}),
            "pop",
        )
        self.assertIsInstance(result, dict)
        self.assertEqual(result["summary"]["delta_pct"], 100.0)

    def test_missing_target(self):
        from data_agent.advanced_analysis import what_if_analysis
        result = what_if_analysis(
            self.geojson_path,
            json.dumps({"pop": 1.5}),
            "nonexistent",
        )
        self.assertIsInstance(result, str)
        self.assertIn("Error", result)

    def test_invalid_scenario_json(self):
        from data_agent.advanced_analysis import what_if_analysis
        result = what_if_analysis(self.geojson_path, "not valid json", "pop")
        self.assertIsInstance(result, str)
        self.assertIn("Error", result)


class TestScenarioCompare(unittest.TestCase):
    """Test scenario_compare with multiple scenarios."""

    def setUp(self):
        self.geojson_path, _ = _make_polygon_gdf(20)

    def test_two_scenarios(self):
        from data_agent.advanced_analysis import scenario_compare
        scenarios = json.dumps([
            {"name": "Growth", "pop": 1.5},
            {"name": "Decline", "pop": 0.7},
        ])
        result = scenario_compare(self.geojson_path, scenarios, "pop")
        self.assertIsInstance(result, dict)
        self.assertIn("comparison_path", result)
        self.assertIn("chart_path", result)
        self.assertEqual(len(result["rankings"]), 2)
        # Growth should rank higher
        self.assertEqual(result["rankings"][0]["scenario"], "Growth")

    def test_too_few_scenarios(self):
        from data_agent.advanced_analysis import scenario_compare
        scenarios = json.dumps([{"name": "Only one", "pop": 1.5}])
        result = scenario_compare(self.geojson_path, scenarios, "pop")
        self.assertIsInstance(result, str)
        self.assertIn("Error", result)

    def test_missing_target(self):
        from data_agent.advanced_analysis import scenario_compare
        scenarios = json.dumps([
            {"name": "A", "pop": 1.5},
            {"name": "B", "pop": 0.5},
        ])
        result = scenario_compare(self.geojson_path, scenarios, "nonexistent")
        self.assertIsInstance(result, str)
        self.assertIn("Error", result)


# ---------------------------------------------------------------------------
# Tests — Category 3: Network Analysis
# ---------------------------------------------------------------------------

class TestNetworkCentrality(unittest.TestCase):
    """Test network_centrality with spatial data."""

    def setUp(self):
        self.line_path = _make_line_gdf()
        self.poly_path, _ = _make_polygon_gdf(20)

    def test_betweenness(self):
        from data_agent.advanced_analysis import network_centrality
        result = network_centrality(self.line_path, method="betweenness")
        self.assertIsInstance(result, dict)
        self.assertIn("result_path", result)
        self.assertIn("top_nodes", result)
        self.assertEqual(result["stats"]["method"], "betweenness")

    def test_degree(self):
        from data_agent.advanced_analysis import network_centrality
        result = network_centrality(self.line_path, method="degree")
        self.assertIsInstance(result, dict)
        self.assertEqual(result["stats"]["method"], "degree")

    def test_closeness(self):
        from data_agent.advanced_analysis import network_centrality
        result = network_centrality(self.poly_path, method="closeness")
        self.assertIsInstance(result, dict)

    def test_eigenvector(self):
        from data_agent.advanced_analysis import network_centrality
        result = network_centrality(self.poly_path, method="eigenvector")
        self.assertIsInstance(result, dict)

    def test_invalid_method(self):
        from data_agent.advanced_analysis import network_centrality
        result = network_centrality(self.line_path, method="invalid")
        self.assertIsInstance(result, str)
        self.assertIn("Error", result)


class TestCommunityDetection(unittest.TestCase):
    """Test community_detection with polygon data."""

    def setUp(self):
        self.poly_path, _ = _make_polygon_gdf(20)

    def test_louvain(self):
        from data_agent.advanced_analysis import community_detection
        result = community_detection(self.poly_path, method="louvain")
        self.assertIsInstance(result, dict)
        self.assertIn("n_communities", result)
        self.assertGreaterEqual(result["n_communities"], 1)
        self.assertIn("modularity", result)
        self.assertEqual(result["method"], "louvain")

    def test_label_propagation(self):
        from data_agent.advanced_analysis import community_detection
        result = community_detection(self.poly_path, method="label_propagation")
        self.assertIsInstance(result, dict)
        self.assertGreaterEqual(result["n_communities"], 1)

    def test_invalid_method(self):
        from data_agent.advanced_analysis import community_detection
        result = community_detection(self.poly_path, method="invalid")
        self.assertIsInstance(result, str)
        self.assertIn("Error", result)


class TestAccessibilityAnalysis(unittest.TestCase):
    """Test accessibility_analysis with point/facility data."""

    def setUp(self):
        self.point_path = _make_point_gdf(15)
        self.facility_path = _make_facility_gdf()

    def test_basic_accessibility(self):
        from data_agent.advanced_analysis import accessibility_analysis
        result = accessibility_analysis(
            self.point_path, self.facility_path, threshold=100,
        )
        self.assertIsInstance(result, dict)
        self.assertIn("result_path", result)
        self.assertIn("stats", result)
        self.assertEqual(result["stats"]["facility_count"], 2)
        self.assertIn("pct_within_threshold", result["stats"])

    def test_large_threshold(self):
        from data_agent.advanced_analysis import accessibility_analysis
        result = accessibility_analysis(
            self.point_path, self.facility_path, threshold=100000,
        )
        self.assertIsInstance(result, dict)
        # All points should be within a very large threshold
        self.assertEqual(result["stats"]["pct_within_threshold"], 100.0)

    def test_zero_threshold(self):
        from data_agent.advanced_analysis import accessibility_analysis
        result = accessibility_analysis(
            self.point_path, self.facility_path, threshold=0,
        )
        self.assertIsInstance(result, dict)
        # No points should be within threshold of 0
        self.assertEqual(result["stats"]["pct_within_threshold"], 0.0)


# ---------------------------------------------------------------------------
# Tests — Internal helpers
# ---------------------------------------------------------------------------

class TestBuildSpatialGraph(unittest.TestCase):
    """Test _build_spatial_graph for different geometry types."""

    def test_polygon_graph(self):
        from data_agent.advanced_analysis import _build_spatial_graph
        _, gdf = _make_polygon_gdf(20)
        G = _build_spatial_graph(gdf)
        self.assertEqual(G.number_of_nodes(), 20)
        self.assertGreater(G.number_of_edges(), 0)

    def test_line_graph(self):
        from data_agent.advanced_analysis import _build_spatial_graph
        gdf = gpd.read_file(_make_line_gdf())
        G = _build_spatial_graph(gdf)
        self.assertEqual(G.number_of_nodes(), 5)
        self.assertGreater(G.number_of_edges(), 0)

    def test_point_graph(self):
        from data_agent.advanced_analysis import _build_spatial_graph
        gdf = gpd.read_file(_make_point_gdf(10))
        G = _build_spatial_graph(gdf)
        self.assertEqual(G.number_of_nodes(), 10)
        self.assertGreater(G.number_of_edges(), 0)

    def test_empty_gdf(self):
        from data_agent.advanced_analysis import _build_spatial_graph
        gdf = gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")
        G = _build_spatial_graph(gdf)
        self.assertEqual(G.number_of_nodes(), 0)


# ---------------------------------------------------------------------------
# Tests — Toolset integration
# ---------------------------------------------------------------------------

class TestAdvancedAnalysisToolset(unittest.TestCase):
    """Test AdvancedAnalysisToolset wrapping."""

    def _run(self, coro):
        import asyncio
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    def test_get_tools_returns_all(self):
        from data_agent.toolsets.advanced_analysis_tools import AdvancedAnalysisToolset
        ts = AdvancedAnalysisToolset()
        tools = self._run(ts.get_tools())
        names = [t.name for t in tools]
        self.assertEqual(len(tools), 7)
        self.assertIn("time_series_forecast", names)
        self.assertIn("network_centrality", names)
        self.assertIn("accessibility_analysis", names)

    def test_tool_filter(self):
        from data_agent.toolsets.advanced_analysis_tools import AdvancedAnalysisToolset
        ts = AdvancedAnalysisToolset(tool_filter=["time_series_forecast", "what_if_analysis"])
        tools = self._run(ts.get_tools())
        names = [t.name for t in tools]
        self.assertEqual(len(tools), 2)
        self.assertIn("time_series_forecast", names)
        self.assertIn("what_if_analysis", names)


if __name__ == "__main__":
    unittest.main()
