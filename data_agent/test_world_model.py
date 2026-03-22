"""
Tests for world_model.py — World Model Tech Preview (Plan D).

Tests cover:
- LatentDynamicsNet architecture (shape, residual, params, gradients)
- Scenario encoding
- Area distribution & transition matrix computation
- Predict sequence (mocked GEE + model)
- LULC decoder
- WorldModelToolset
- World Model API routes
"""

import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

import numpy as np


# ---------------------------------------------------------------------------
# Test: LatentDynamicsNet
# ---------------------------------------------------------------------------


class TestLatentDynamicsNet(unittest.TestCase):
    """Test the core neural network architecture."""

    def test_output_shape(self):
        """Model output should match input spatial dims."""
        import torch
        from data_agent.world_model import _build_model, Z_DIM, SCENARIO_DIM

        model = _build_model(Z_DIM, SCENARIO_DIM)
        z_t = torch.randn(1, Z_DIM, 8, 8)
        scenario = torch.randn(1, SCENARIO_DIM)
        z_tp1 = model(z_t, scenario)
        self.assertEqual(z_tp1.shape, (1, Z_DIM, 8, 8))

    def test_batch_output_shape(self):
        """Model should handle batch size > 1."""
        import torch
        from data_agent.world_model import _build_model

        model = _build_model()
        z_t = torch.randn(4, 64, 16, 16)
        scenario = torch.randn(4, 16)
        z_tp1 = model(z_t, scenario)
        self.assertEqual(z_tp1.shape, (4, 64, 16, 16))

    def test_residual_connection(self):
        """With zero-initialized weights, output should be close to input (residual identity)."""
        import torch
        from data_agent.world_model import _build_model

        model = _build_model()
        # Zero out the last conv layer to make delta_z ≈ 0
        with torch.no_grad():
            for p in model.dynamics[-1].parameters():
                p.zero_()
        z_t = torch.randn(1, 64, 8, 8)
        scenario = torch.zeros(1, 16)
        z_tp1 = model(z_t, scenario)
        # Output should be very close to input
        diff = (z_tp1 - z_t).abs().max().item()
        self.assertLess(diff, 1e-5)

    def test_parameter_count(self):
        """Model should have roughly 50K parameters."""
        from data_agent.world_model import _build_model

        model = _build_model()
        total = sum(p.numel() for p in model.parameters())
        self.assertGreater(total, 20_000)
        self.assertLess(total, 400_000)

    def test_gradient_flow(self):
        """Gradients should flow through all layers."""
        import torch
        from data_agent.world_model import _build_model

        model = _build_model()
        z_t = torch.randn(1, 64, 8, 8, requires_grad=True)
        scenario = torch.randn(1, 16)
        z_tp1 = model(z_t, scenario)
        loss = z_tp1.sum()
        loss.backward()
        for name, p in model.named_parameters():
            self.assertIsNotNone(p.grad, f"No gradient for {name}")
            self.assertFalse(
                torch.all(p.grad == 0).item(),
                f"Zero gradient for {name}",
            )


# ---------------------------------------------------------------------------
# Test: Scenario Encoding
# ---------------------------------------------------------------------------


class TestScenarioEncoding(unittest.TestCase):
    """Test scenario name to tensor encoding."""

    def test_all_scenarios_valid(self):
        """All 5 scenarios should produce [1, 16] tensors."""
        from data_agent.world_model import encode_scenario, SCENARIOS

        for name in SCENARIOS:
            t = encode_scenario(name)
            self.assertEqual(t.shape, (1, 16), f"Bad shape for {name}")

    def test_invalid_scenario_raises(self):
        """Unknown scenario should raise ValueError."""
        from data_agent.world_model import encode_scenario

        with self.assertRaises(ValueError):
            encode_scenario("nonexistent_scenario")

    def test_one_hot_correctness(self):
        """First 5 dims should be one-hot, rest zero."""
        from data_agent.world_model import encode_scenario, SCENARIOS

        for name, sc in SCENARIOS.items():
            t = encode_scenario(name)
            vec = t.squeeze(0).numpy()
            # Check one-hot
            self.assertAlmostEqual(vec[sc.id], 1.0)
            for i in range(5):
                if i != sc.id:
                    self.assertAlmostEqual(vec[i], 0.0)
            # Reserved dims should be zero
            for i in range(5, 16):
                self.assertAlmostEqual(vec[i], 0.0)


# ---------------------------------------------------------------------------
# Test: Area Distribution & Transition Matrix
# ---------------------------------------------------------------------------


class TestAreaDistribution(unittest.TestCase):
    """Test LULC grid analysis functions."""

    def test_compute_area_distribution(self):
        """Percentages should sum to ~100."""
        from data_agent.world_model import _compute_area_distribution

        grid = np.array([[7, 7, 8], [2, 2, 7], [8, 8, 8]], dtype=np.int32)
        dist = _compute_area_distribution(grid)
        total_pct = sum(v["percentage"] for v in dist.values())
        self.assertAlmostEqual(total_pct, 100.0, places=1)

    def test_distribution_counts(self):
        """Check specific counts."""
        from data_agent.world_model import _compute_area_distribution

        grid = np.array([[7, 7], [8, 8]], dtype=np.int32)
        dist = _compute_area_distribution(grid)
        self.assertEqual(dist["耕地"]["count"], 2)
        self.assertEqual(dist["建设用地"]["count"], 2)

    def test_compute_transition_matrix(self):
        """Transition counts should be correct."""
        from data_agent.world_model import _compute_transition_matrix

        start = np.array([[7, 7], [2, 2]], dtype=np.int32)
        end = np.array([[8, 7], [2, 8]], dtype=np.int32)
        tm = _compute_transition_matrix(start, end)
        # 耕地: 1 stayed, 1 became 建设用地
        self.assertEqual(tm["耕地"]["耕地"], 1)
        self.assertEqual(tm["耕地"]["建设用地"], 1)
        # 树木: 1 stayed, 1 became 建设用地
        self.assertEqual(tm["树木"]["树木"], 1)
        self.assertEqual(tm["树木"]["建设用地"], 1)

    def test_empty_grid(self):
        """Empty grid should return empty dict."""
        from data_agent.world_model import _compute_area_distribution

        grid = np.zeros((0, 0), dtype=np.int32)
        dist = _compute_area_distribution(grid)
        self.assertEqual(dist, {})


# ---------------------------------------------------------------------------
# Test: LULC Decoder
# ---------------------------------------------------------------------------


class TestLulcDecoder(unittest.TestCase):
    """Test embedding-to-LULC decoding."""

    def test_embeddings_to_lulc_shape(self):
        """Output should be [H, W] from [64, H, W] input."""
        from data_agent.world_model import _embeddings_to_lulc

        mock_decoder = MagicMock()
        mock_decoder.predict.return_value = np.array([7] * 64)
        z = np.random.randn(64, 8, 8).astype(np.float32)
        lulc = _embeddings_to_lulc(z, mock_decoder)
        self.assertEqual(lulc.shape, (8, 8))

    def test_decoder_receives_correct_shape(self):
        """Decoder should receive [H*W, 64] input."""
        from data_agent.world_model import _embeddings_to_lulc

        mock_decoder = MagicMock()
        mock_decoder.predict.return_value = np.array([7] * 48)
        z = np.random.randn(64, 6, 8).astype(np.float32)
        _embeddings_to_lulc(z, mock_decoder)
        call_args = mock_decoder.predict.call_args[0][0]
        self.assertEqual(call_args.shape, (48, 64))


# ---------------------------------------------------------------------------
# Test: Predict Sequence (mocked)
# ---------------------------------------------------------------------------


class TestPredictSequence(unittest.TestCase):
    """Test the full prediction pipeline with mocked GEE and model."""

    def _make_mock_model(self):
        """Create a mock model that returns input + small delta."""
        import torch

        model = MagicMock()

        def side_effect(z_t, scenario):
            return z_t + 0.01 * torch.randn_like(z_t)

        model.side_effect = side_effect
        model.return_value = None
        return model

    @patch("data_agent.world_model._load_decoder")
    @patch("data_agent.world_model._load_model")
    @patch("data_agent.world_model.extract_embeddings")
    @patch("data_agent.world_model._init_gee", return_value=True)
    def test_predict_basic(self, mock_gee, mock_extract, mock_load_model, mock_load_decoder):
        """Full prediction should return expected structure."""
        import torch
        from data_agent.world_model import predict_sequence, _build_model

        # Mock embeddings
        mock_extract.return_value = np.random.randn(8, 8, 64).astype(np.float32)

        # Use real model
        model = _build_model()
        model.eval()
        mock_load_model.return_value = model

        # Mock decoder
        mock_decoder = MagicMock()
        mock_decoder.predict.return_value = np.random.choice([2, 7, 8], size=64)
        mock_load_decoder.return_value = mock_decoder

        result = predict_sequence([121.2, 31.0, 121.3, 31.1], "baseline", 2023, 3)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["scenario"], "baseline")
        self.assertEqual(len(result["years"]), 4)  # start + 3 predicted
        self.assertIn("area_distribution", result)
        self.assertIn("transition_matrix", result)
        self.assertIn("summary", result)

    def test_predict_invalid_scenario(self):
        """Unknown scenario should return error."""
        from data_agent.world_model import predict_sequence

        result = predict_sequence([0, 0, 1, 1], "invalid_scenario", 2023, 5)
        self.assertEqual(result["status"], "error")
        self.assertIn("Unknown scenario", result["error"])

    @patch("data_agent.world_model.extract_embeddings", return_value=None)
    @patch("data_agent.world_model._init_gee", return_value=True)
    def test_predict_gee_unavailable(self, mock_gee, mock_extract):
        """Should return error when embeddings can't be extracted."""
        from data_agent.world_model import predict_sequence

        result = predict_sequence([121.2, 31.0, 121.3, 31.1], "baseline", 2023, 5)
        self.assertEqual(result["status"], "error")


# ---------------------------------------------------------------------------
# Test: WorldModelToolset
# ---------------------------------------------------------------------------


class TestWorldModelTools(unittest.TestCase):
    """Test toolset functions."""

    def test_list_scenarios(self):
        """Should return JSON with 5 scenarios."""
        from data_agent.toolsets.world_model_tools import world_model_scenarios

        result = json.loads(world_model_scenarios())
        self.assertIn("scenarios", result)
        self.assertEqual(len(result["scenarios"]), 5)

    @patch("data_agent.world_model._init_gee", return_value=False)
    def test_model_status(self, mock_gee):
        """Should return JSON with expected keys."""
        from data_agent.toolsets.world_model_tools import world_model_status

        result = json.loads(world_model_status())
        self.assertIn("weights_exist", result)
        self.assertIn("gee_available", result)
        self.assertIn("z_dim", result)

    def test_toolset_get_tools(self):
        """WorldModelToolset should return 3 tools."""
        import asyncio
        from data_agent.toolsets.world_model_tools import WorldModelToolset

        ts = WorldModelToolset()
        tools = asyncio.get_event_loop().run_until_complete(ts.get_tools())
        self.assertEqual(len(tools), 3)
        names = {t.name for t in tools}
        self.assertIn("world_model_predict", names)
        self.assertIn("world_model_scenarios", names)
        self.assertIn("world_model_status", names)


# ---------------------------------------------------------------------------
# Test: World Model Routes
# ---------------------------------------------------------------------------


class TestWorldModelRoutes(unittest.TestCase):
    """Test API route factory."""

    def test_route_count(self):
        """Should return 4 routes."""
        from data_agent.api.world_model_routes import get_world_model_routes

        routes = get_world_model_routes()
        self.assertEqual(len(routes), 4)

    def test_route_paths(self):
        """Routes should have correct paths."""
        from data_agent.api.world_model_routes import get_world_model_routes

        routes = get_world_model_routes()
        paths = {r.path for r in routes}
        self.assertIn("/api/world-model/status", paths)
        self.assertIn("/api/world-model/scenarios", paths)
        self.assertIn("/api/world-model/predict", paths)
        self.assertIn("/api/world-model/history", paths)


# ---------------------------------------------------------------------------
# Test: GeoJSON Generation
# ---------------------------------------------------------------------------


class TestGeoJsonGeneration(unittest.TestCase):
    """Test LULC grid to GeoJSON conversion."""

    def test_geojson_structure(self):
        """Should produce valid GeoJSON FeatureCollection."""
        from data_agent.world_model import _lulc_grid_to_geojson

        grid = np.array([[7, 7, 8], [2, 2, 7]], dtype=np.int32)
        bbox = [121.0, 31.0, 121.1, 31.1]
        geojson = _lulc_grid_to_geojson(grid, bbox, 2025)
        self.assertEqual(geojson["type"], "FeatureCollection")
        self.assertTrue(len(geojson["features"]) > 0)
        for f in geojson["features"]:
            self.assertEqual(f["type"], "Feature")
            self.assertIn("class_name", f["properties"])
            self.assertIn("year", f["properties"])
            self.assertEqual(f["properties"]["year"], 2025)

    def test_geojson_empty_grid(self):
        """Empty grid should produce empty features."""
        from data_agent.world_model import _lulc_grid_to_geojson

        grid = np.zeros((0, 0), dtype=np.int32)
        bbox = [0, 0, 1, 1]
        geojson = _lulc_grid_to_geojson(grid, bbox, 2025)
        self.assertEqual(len(geojson["features"]), 0)


# ---------------------------------------------------------------------------
# Test: Utilities
# ---------------------------------------------------------------------------


class TestUtilities(unittest.TestCase):
    """Test list_scenarios and get_model_info."""

    def test_list_scenarios(self):
        """Should return 5 scenarios with expected keys."""
        from data_agent.world_model import list_scenarios

        scenarios = list_scenarios()
        self.assertEqual(len(scenarios), 5)
        for s in scenarios:
            self.assertIn("id", s)
            self.assertIn("name_zh", s)
            self.assertIn("description", s)

    @patch("data_agent.world_model._init_gee", return_value=False)
    def test_get_model_info(self, mock_gee):
        """Should return dict with expected keys."""
        from data_agent.world_model import get_model_info

        info = get_model_info()
        self.assertIn("weights_exist", info)
        self.assertIn("decoder_exist", info)
        self.assertIn("gee_available", info)
        self.assertIn("z_dim", info)
        self.assertEqual(info["z_dim"], 64)
        self.assertEqual(info["n_scenarios"], 5)


if __name__ == "__main__":
    unittest.main()
