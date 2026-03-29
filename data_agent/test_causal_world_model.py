"""Tests for causal_world_model.py — Angle C: interventional prediction via world model.

Covers all 4 tool functions (intervention_predict, counterfactual_comparison,
embedding_treatment_effect, integrate_statistical_prior), internal helpers,
and the CausalWorldModelToolset registration.

Mock strategy:
- Tool functions use deferred ``from .world_model import ...`` inside function
  bodies, which creates local bindings.  We must therefore patch at the *source*
  module — ``data_agent.world_model.<name>`` — so that Python re-imports pick up
  the mocked object.
- Helpers that live directly on causal_world_model (e.g. _render_diff_map,
  _generate_output_path) are patched at ``data_agent.causal_world_model.<name>``.
- The embedding_store import is guarded by try/except inside the functions, so
  it falls through to extract_embeddings naturally.
"""

import contextlib
import json
import unittest
from unittest.mock import patch, MagicMock

import numpy as np
import torch

from data_agent.causal_world_model import (
    _parse_bbox,
    _create_spatial_mask,
    _lulc_name_to_id,
    intervention_predict,
    counterfactual_comparison,
    embedding_treatment_effect,
    integrate_statistical_prior,
)


# ====================================================================
#  Synthetic data fixtures
# ====================================================================

def _make_embeddings(h=8, w=8, z_dim=64):
    """Create synthetic embedding grid [H, W, C]."""
    return np.random.RandomState(42).randn(h, w, z_dim).astype(np.float32)


def _make_model_mock():
    """Create a mock NN model that returns slightly modified input."""
    model = MagicMock()

    def forward(z, s, context=None):
        delta = torch.randn_like(z) * 0.01
        return z + delta

    model.side_effect = forward
    model.__call__ = forward
    return model


def _make_identity_model_mock():
    """Create a mock NN model that returns the input unchanged."""
    model = MagicMock()
    model.side_effect = lambda z, s, context=None: z
    model.__call__ = lambda z, s, context=None: z
    return model


def _make_decoder_mock(n_classes=9):
    """Create a mock LULC decoder."""
    decoder = MagicMock()

    def predict(X):
        rng = np.random.RandomState(0)
        return rng.choice([1, 2, 4, 5, 7, 8, 9], size=X.shape[0])

    decoder.predict = predict
    return decoder


def _make_predict_result(scenario, start_year=2023, n_years=3):
    """Create a synthetic predict_sequence result."""
    years = list(range(start_year, start_year + n_years + 1))
    return {
        "status": "ok",
        "scenario": scenario,
        "bbox": [121.0, 31.0, 121.1, 31.1],
        "years": years,
        "grid_shape": [8, 8],
        "area_distribution": {
            str(y): {
                "建设用地": {"count": 20 + i * 2, "percentage": 20 + i * 2},
                "耕地": {"count": 40 - i * 2, "percentage": 40 - i * 2},
                "树木": {"count": 25, "percentage": 25},
                "水体": {"count": 15, "percentage": 15},
            }
            for i, y in enumerate(years)
        },
        "transition_matrix": {"建设用地→耕地": 5, "耕地→建设用地": 10},
        "geojson_layers": {
            str(y): {"type": "FeatureCollection", "features": []}
            for y in years
        },
        "summary": f"Prediction complete for {scenario}",
    }


def _make_predict_result_with_change(scenario, start_year=2023, n_years=5):
    """Create predict result where 树木 changes from 25% to 20%."""
    years = list(range(start_year, start_year + n_years + 1))
    return {
        "status": "ok",
        "scenario": scenario,
        "bbox": [121.0, 31.0, 121.1, 31.1],
        "years": years,
        "grid_shape": [8, 8],
        "area_distribution": {
            str(y): {
                "建设用地": {"count": 20 + i * 2, "percentage": 20 + i * 2.0},
                "耕地": {"count": 30, "percentage": 30.0},
                "树木": {"count": 25 - i, "percentage": 25.0 - i * 1.0},
                "水体": {"count": 15, "percentage": 15.0},
            }
            for i, y in enumerate(years)
        },
        "summary": f"Prediction for {scenario}",
    }


def _make_flat_predict_result(scenario, start_year=2023, n_years=5):
    """Create predict result where nothing changes (flat percentages)."""
    years = list(range(start_year, start_year + n_years + 1))
    return {
        "status": "ok",
        "scenario": scenario,
        "years": years,
        "area_distribution": {
            str(y): {
                "树木": {"count": 25, "percentage": 25.0},
                "耕地": {"count": 30, "percentage": 30.0},
            }
            for y in years
        },
    }


# Fake SCENARIOS dict used by mocks
_FAKE_SCENARIOS = {}
for _key, _name_zh, _id in [
    ("baseline", "基线趋势", 4),
    ("urban_sprawl", "城市蔓延", 0),
    ("ecological_restoration", "生态修复", 1),
    ("agricultural_intensification", "农业集约化", 2),
    ("climate_adaptation", "气候适应", 3),
]:
    _sc = MagicMock()
    _sc.name_zh = _name_zh
    _sc.id = _id
    _FAKE_SCENARIOS[_key] = _sc

_FAKE_LULC_CLASSES = {
    1: "水体", 2: "树木", 4: "草地", 5: "灌木",
    7: "耕地", 8: "建设用地", 9: "裸地", 10: "冰雪", 11: "湿地",
}

# Prefix for world_model source patches
_WM = "data_agent.world_model"
# Prefix for causal_world_model local patches
_CWM = "data_agent.causal_world_model"


# ====================================================================
#  Helper: build ExitStack with patches at the *source* module
# ====================================================================

def _apply_patches(stack, source_patches, local_patches=None):
    """Enter patches on the ExitStack.

    Args:
        stack: contextlib.ExitStack
        source_patches: dict of name -> mock for data_agent.world_model.<name>
        local_patches:  dict of name -> mock for data_agent.causal_world_model.<name>
    """
    for name, val in source_patches.items():
        stack.enter_context(patch(f"{_WM}.{name}", val))
    if local_patches:
        for name, val in local_patches.items():
            stack.enter_context(patch(f"{_CWM}.{name}", val))


def _base_source_patches(
    *,
    model=None,
    decoder=None,
    emb=None,
    predict_fn=None,
    extra=None,
):
    """Build a dict of world_model patches suitable for most tool tests."""
    if model is None:
        model = _make_model_mock()
    if decoder is None:
        decoder = _make_decoder_mock()
    if emb is None:
        emb = _make_embeddings()

    if predict_fn is None:
        predict_fn = lambda bbox, sc, yr, steps: _make_predict_result(sc, yr, steps)

    patches = {
        "extract_embeddings": MagicMock(return_value=emb),
        "_load_model": MagicMock(return_value=model),
        "_load_decoder": MagicMock(return_value=decoder),
        "extract_terrain_context": MagicMock(return_value=None),
        "encode_scenario": MagicMock(
            side_effect=lambda s: torch.zeros(1, 16)
        ),
        "predict_sequence": MagicMock(side_effect=predict_fn),
        "SCENARIOS": _FAKE_SCENARIOS,
        "_embeddings_to_lulc": MagicMock(
            side_effect=lambda z_np, dec: np.random.RandomState(0).choice(
                [1, 2, 4, 7, 8], size=(z_np.shape[1], z_np.shape[2])
            )
        ),
        "_compute_area_distribution": MagicMock(
            return_value={
                "建设用地": {"count": 20, "percentage": 31.25},
                "耕地": {"count": 15, "percentage": 23.44},
            }
        ),
        "_lulc_grid_to_geojson": MagicMock(
            return_value={
                "type": "FeatureCollection",
                "features": [],
                "properties": {},
            }
        ),
        "_compute_transition_matrix": MagicMock(return_value={}),
        "LULC_CLASSES": _FAKE_LULC_CLASSES,
    }
    if extra:
        patches.update(extra)
    return patches


# ====================================================================
#  TestHelpers
# ====================================================================

class TestHelpers(unittest.TestCase):
    """Tests for internal helper functions."""

    def test_parse_bbox(self):
        result = _parse_bbox("121.0,31.0,121.1,31.1")
        self.assertEqual(result, [121.0, 31.0, 121.1, 31.1])

    def test_parse_bbox_with_spaces(self):
        result = _parse_bbox(" 121.0 , 31.0 , 121.1 , 31.1 ")
        self.assertEqual(result, [121.0, 31.0, 121.1, 31.1])

    def test_parse_bbox_invalid_count(self):
        with self.assertRaises(ValueError):
            _parse_bbox("121.0,31.0,121.1")

    def test_parse_bbox_invalid_type(self):
        with self.assertRaises(ValueError):
            _parse_bbox("abc,31.0,121.1,31.1")

    def test_create_spatial_mask(self):
        """Sub-bbox covers the bottom-right quadrant of an 8x8 grid."""
        bbox = [121.0, 31.0, 121.1, 31.1]
        sub_bbox = [121.05, 31.0, 121.1, 31.05]
        rows, cols = _create_spatial_mask(bbox, sub_bbox, (8, 8))
        self.assertTrue(np.all(rows >= 0))
        self.assertTrue(np.all(rows < 8))
        self.assertTrue(np.all(cols >= 0))
        self.assertTrue(np.all(cols < 8))
        self.assertGreater(len(rows), 0)

    def test_create_spatial_mask_full_coverage(self):
        """Sub-bbox equals bbox — mask covers all pixels."""
        bbox = [121.0, 31.0, 121.1, 31.1]
        rows, cols = _create_spatial_mask(bbox, bbox, (8, 8))
        self.assertEqual(len(rows), 64)
        self.assertEqual(len(cols), 64)

    @patch(f"{_WM}.LULC_CLASSES", _FAKE_LULC_CLASSES)
    def test_lulc_name_to_id_exact(self):
        """Test exact name mapping."""
        self.assertEqual(_lulc_name_to_id("建设用地"), 8)
        self.assertEqual(_lulc_name_to_id("耕地"), 7)
        self.assertEqual(_lulc_name_to_id("树木"), 2)
        self.assertEqual(_lulc_name_to_id("水体"), 1)

    @patch(f"{_WM}.LULC_CLASSES", _FAKE_LULC_CLASSES)
    def test_lulc_name_to_id_unknown(self):
        """Unknown class name returns None."""
        self.assertIsNone(_lulc_name_to_id("未知类别"))


# ====================================================================
#  TestInterventionPredict
# ====================================================================

class TestInterventionPredict(unittest.TestCase):
    """Tests for intervention_predict tool."""

    @patch(f"{_CWM}._render_diff_map", return_value="/tmp/diff.png")
    @patch(f"{_CWM}._generate_output_path", return_value="/tmp/test.png")
    def test_basic_intervention(self, mock_outpath, mock_render):
        """Valid bbox + sub_bbox returns JSON with expected top-level keys."""
        with contextlib.ExitStack() as stack:
            _apply_patches(stack, _base_source_patches())

            result_str = intervention_predict(
                bbox="121.0,31.0,121.1,31.1",
                intervention_sub_bbox="121.02,31.02,121.08,31.08",
                intervention_type="urban_sprawl",
                baseline_scenario="baseline",
                start_year="2023",
                n_years="3",
            )
        result = json.loads(result_str)
        self.assertEqual(result["status"], "ok")
        self.assertIn("baseline_result", result)
        self.assertIn("intervention_result", result)
        self.assertIn("spillover_analysis", result)
        self.assertIn("summary", result)
        self.assertIn("spillover_percentage", result["spillover_analysis"])

    @patch(f"{_CWM}._render_diff_map", return_value="/tmp/diff.png")
    @patch(f"{_CWM}._generate_output_path", return_value="/tmp/test.png")
    def test_invalid_sub_bbox(self, mock_outpath, mock_render):
        """Sub-bbox outside bbox returns error status."""
        with contextlib.ExitStack() as stack:
            _apply_patches(stack, _base_source_patches())

            result_str = intervention_predict(
                bbox="121.0,31.0,121.1,31.1",
                intervention_sub_bbox="120.0,30.0,120.5,30.5",
                intervention_type="urban_sprawl",
                baseline_scenario="baseline",
            )
        result = json.loads(result_str)
        self.assertEqual(result["status"], "error")
        self.assertIn("bbox", result["error"])

    @patch(f"{_CWM}._render_diff_map", return_value="/tmp/diff.png")
    @patch(f"{_CWM}._generate_output_path", return_value="/tmp/test.png")
    def test_same_scenario(self, mock_outpath, mock_render):
        """Intervention type == baseline still works (no-op intervention)."""
        with contextlib.ExitStack() as stack:
            _apply_patches(stack, _base_source_patches())

            result_str = intervention_predict(
                bbox="121.0,31.0,121.1,31.1",
                intervention_sub_bbox="121.02,31.02,121.08,31.08",
                intervention_type="baseline",
                baseline_scenario="baseline",
                start_year="2023",
                n_years="2",
            )
        result = json.loads(result_str)
        self.assertEqual(result["status"], "ok")
        self.assertIn("spillover_analysis", result)

    @patch(f"{_CWM}._render_diff_map", return_value="/tmp/diff.png")
    @patch(f"{_CWM}._generate_output_path", return_value="/tmp/test.png")
    def test_unknown_scenario(self, mock_outpath, mock_render):
        """Unknown scenario name returns error."""
        with contextlib.ExitStack() as stack:
            _apply_patches(stack, _base_source_patches())

            result_str = intervention_predict(
                bbox="121.0,31.0,121.1,31.1",
                intervention_sub_bbox="121.02,31.02,121.08,31.08",
                intervention_type="nonexistent_scenario",
                baseline_scenario="baseline",
            )
        result = json.loads(result_str)
        self.assertEqual(result["status"], "error")
        self.assertIn("未知情景", result["error"])


# ====================================================================
#  TestCounterfactualComparison
# ====================================================================

class TestCounterfactualComparison(unittest.TestCase):
    """Tests for counterfactual_comparison tool."""

    @patch(f"{_CWM}._render_comparison_plot", return_value="/tmp/compare.png")
    @patch(f"{_CWM}._generate_output_path", return_value="/tmp/cf_diff.geojson")
    def test_two_scenarios(self, mock_outpath, mock_render):
        """Baseline vs ecological_restoration returns JSON with per_year_effects."""
        with contextlib.ExitStack() as stack:
            _apply_patches(stack, _base_source_patches())

            result_str = counterfactual_comparison(
                bbox="121.0,31.0,121.1,31.1",
                scenario_a="baseline",
                scenario_b="ecological_restoration",
                start_year="2023",
                n_years="3",
            )
        result = json.loads(result_str)
        self.assertEqual(result["status"], "ok")
        self.assertIn("per_year_effects", result)
        self.assertIn("aggregate_effects", result)
        self.assertIn("transition_diff_matrix", result)
        self.assertIn("scenario_a_result", result)
        self.assertIn("scenario_b_result", result)
        self.assertIn("summary", result)

    @patch(f"{_CWM}._render_comparison_plot", return_value="/tmp/compare.png")
    @patch(f"{_CWM}._generate_output_path", return_value="/tmp/cf_diff.geojson")
    def test_identical_scenarios(self, mock_outpath, mock_render):
        """Same scenario for both — effects should be zero."""
        model = _make_identity_model_mock()
        source = _base_source_patches(model=model)
        # Override _embeddings_to_lulc to return deterministic grid
        source["_embeddings_to_lulc"] = MagicMock(
            side_effect=lambda z_np, dec: np.ones(
                (z_np.shape[1], z_np.shape[2]), dtype=int
            ) * 7
        )

        with contextlib.ExitStack() as stack:
            _apply_patches(stack, source)

            result_str = counterfactual_comparison(
                bbox="121.0,31.0,121.1,31.1",
                scenario_a="baseline",
                scenario_b="baseline",
                start_year="2023",
                n_years="3",
            )
        result = json.loads(result_str)
        self.assertEqual(result["status"], "ok")
        for yr_key, eff in result.get("per_year_effects", {}).items():
            self.assertEqual(eff["changed_pixels"], 0)
            self.assertAlmostEqual(eff["changed_percentage"], 0.0)

    def test_error_propagation(self):
        """predict_sequence returning error is propagated to caller."""
        error_result = {"status": "error", "error": "GEE connection failed"}

        with contextlib.ExitStack() as stack:
            _apply_patches(stack, {
                "predict_sequence": MagicMock(return_value=error_result),
                "SCENARIOS": _FAKE_SCENARIOS,
            })

            result_str = counterfactual_comparison(
                bbox="121.0,31.0,121.1,31.1",
                scenario_a="baseline",
                scenario_b="ecological_restoration",
                start_year="2023",
                n_years="3",
            )
        result = json.loads(result_str)
        self.assertEqual(result["status"], "error")
        self.assertIn("GEE connection failed", result["error"])

    def test_unknown_scenario_error(self):
        """Unknown scenario returns error before prediction."""
        with contextlib.ExitStack() as stack:
            _apply_patches(stack, {"SCENARIOS": _FAKE_SCENARIOS})

            result_str = counterfactual_comparison(
                bbox="121.0,31.0,121.1,31.1",
                scenario_a="baseline",
                scenario_b="nonexistent",
            )
        result = json.loads(result_str)
        self.assertEqual(result["status"], "error")
        self.assertIn("未知情景", result["error"])


# ====================================================================
#  TestEmbeddingTreatmentEffect
# ====================================================================

class TestEmbeddingTreatmentEffect(unittest.TestCase):
    """Tests for embedding_treatment_effect tool."""

    def _source_patches(self, **overrides):
        """Minimal source patches for embedding_treatment_effect."""
        patches = {
            "extract_embeddings": MagicMock(return_value=_make_embeddings()),
            "_load_model": MagicMock(return_value=_make_model_mock()),
            "extract_terrain_context": MagicMock(return_value=None),
            "encode_scenario": MagicMock(
                side_effect=lambda s: torch.zeros(1, 16)
            ),
            "SCENARIOS": _FAKE_SCENARIOS,
        }
        patches.update(overrides)
        return patches

    @patch(f"{_CWM}._render_effect_heatmap", return_value="/tmp/heatmap.png")
    def test_cosine_metric(self, mock_render):
        """Cosine metric produces per_year_distances with statistical keys."""
        with contextlib.ExitStack() as stack:
            _apply_patches(stack, self._source_patches())

            result_str = embedding_treatment_effect(
                bbox="121.0,31.0,121.1,31.1",
                scenario_a="baseline",
                scenario_b="urban_sprawl",
                start_year="2023",
                n_years="3",
                metric="cosine",
            )
        result = json.loads(result_str)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["metric"], "cosine")
        self.assertIn("per_year_distances", result)
        self.assertEqual(len(result["per_year_distances"]), 3)
        for yr_key, stats in result["per_year_distances"].items():
            self.assertIn("mean", stats)
            self.assertIn("max", stats)
            self.assertIn("p95", stats)
            self.assertIn("p50", stats)
            self.assertIn("std", stats)

    @patch(f"{_CWM}._render_effect_heatmap", return_value="/tmp/heatmap.png")
    def test_euclidean_metric(self, mock_render):
        """Euclidean metric field is 'euclidean'."""
        with contextlib.ExitStack() as stack:
            _apply_patches(stack, self._source_patches())

            result_str = embedding_treatment_effect(
                bbox="121.0,31.0,121.1,31.1",
                scenario_a="baseline",
                scenario_b="ecological_restoration",
                metric="euclidean",
            )
        result = json.loads(result_str)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["metric"], "euclidean")
        self.assertIn("per_year_distances", result)

    @patch(f"{_CWM}._render_effect_heatmap", return_value="/tmp/heatmap.png")
    def test_manhattan_metric(self, mock_render):
        """Manhattan metric field is 'manhattan'."""
        with contextlib.ExitStack() as stack:
            _apply_patches(stack, self._source_patches())

            result_str = embedding_treatment_effect(
                bbox="121.0,31.0,121.1,31.1",
                scenario_a="baseline",
                scenario_b="ecological_restoration",
                metric="manhattan",
            )
        result = json.loads(result_str)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["metric"], "manhattan")

    @patch(f"{_CWM}._render_effect_heatmap", return_value="/tmp/heatmap.png")
    def test_hotspot_detection(self, mock_render):
        """Verify hotspot_count and hotspot_percentage in result."""
        with contextlib.ExitStack() as stack:
            _apply_patches(stack, self._source_patches())

            result_str = embedding_treatment_effect(
                bbox="121.0,31.0,121.1,31.1",
                scenario_a="baseline",
                scenario_b="urban_sprawl",
                start_year="2023",
                n_years="3",
                metric="cosine",
            )
        result = json.loads(result_str)
        self.assertEqual(result["status"], "ok")
        self.assertIn("hotspot_count", result)
        self.assertIn("hotspot_percentage", result)
        self.assertGreaterEqual(result["hotspot_percentage"], 0.0)
        self.assertLessEqual(result["hotspot_percentage"], 100.0)
        self.assertEqual(result["grid_shape"], [8, 8])

    def test_invalid_metric(self):
        """Invalid metric name returns error."""
        with contextlib.ExitStack() as stack:
            _apply_patches(stack, {"SCENARIOS": _FAKE_SCENARIOS})

            result_str = embedding_treatment_effect(
                bbox="121.0,31.0,121.1,31.1",
                scenario_a="baseline",
                scenario_b="urban_sprawl",
                metric="hamming",
            )
        result = json.loads(result_str)
        self.assertEqual(result["status"], "error")
        self.assertIn("不支持", result["error"])

    def test_no_embeddings(self):
        """extract_embeddings returns None produces error."""
        with contextlib.ExitStack() as stack:
            _apply_patches(stack, self._source_patches(
                extract_embeddings=MagicMock(return_value=None),
            ))

            result_str = embedding_treatment_effect(
                bbox="121.0,31.0,121.1,31.1",
                scenario_a="baseline",
                scenario_b="urban_sprawl",
                metric="cosine",
            )
        result = json.loads(result_str)
        self.assertEqual(result["status"], "error")
        self.assertIn("嵌入", result["error"])


# ====================================================================
#  TestStatisticalPriorIntegration
# ====================================================================

class TestStatisticalPriorIntegration(unittest.TestCase):
    """Tests for integrate_statistical_prior tool."""

    @patch(f"{_CWM}._configure_fonts")
    @patch(f"{_CWM}._generate_output_path", return_value="/tmp/calib.png")
    @patch(f"{_WM}.LULC_CLASSES", _FAKE_LULC_CLASSES)
    def test_calibration(self, mock_outpath, mock_fonts):
        """ATT estimate -5.0 produces a calibration_factor in result."""
        source = _base_source_patches(
            predict_fn=lambda bbox, sc, yr, steps: _make_predict_result_with_change(sc, yr, steps),
            extra={
                "encode_scenario": MagicMock(
                    side_effect=lambda s: torch.ones(1, 16) * 0.5
                ),
            },
        )
        with contextlib.ExitStack() as stack:
            _apply_patches(stack, source)
            # Patch matplotlib inside integrate_statistical_prior
            mock_plt = MagicMock()
            mock_fig = MagicMock()
            mock_ax = MagicMock()
            stack.enter_context(
                patch("matplotlib.pyplot.subplots", return_value=(mock_fig, mock_ax))
            )
            stack.enter_context(patch("matplotlib.pyplot.close"))
            mock_fig.savefig = MagicMock()

            result_str = integrate_statistical_prior(
                bbox="121.0,31.0,121.1,31.1",
                att_estimate="-5.0",
                att_se="1.5",
                treatment_variable="建设用地",
                outcome_variable="树木",
                scenario="baseline",
                start_year="2023",
                n_years="5",
            )
        result = json.loads(result_str)
        self.assertEqual(result["status"], "ok")
        self.assertIn("calibration_factor", result)
        self.assertIn("predicted_effect_pct", result)
        self.assertIn("att_prior", result)
        self.assertEqual(result["att_prior"]["estimate"], -5.0)
        self.assertEqual(result["att_prior"]["se"], 1.5)
        self.assertIn("calibrated_prediction", result)
        self.assertIn("uncalibrated_prediction", result)
        self.assertGreaterEqual(result["calibration_factor"], 0.1)
        self.assertLessEqual(result["calibration_factor"], 5.0)

    @patch(f"{_WM}.LULC_CLASSES", _FAKE_LULC_CLASSES)
    def test_zero_effect_warning(self):
        """World model predicts no change produces warning status."""
        source = {
            "predict_sequence": MagicMock(
                side_effect=lambda bbox, sc, yr, steps: _make_flat_predict_result(sc, yr, steps)
            ),
            "SCENARIOS": _FAKE_SCENARIOS,
        }
        with contextlib.ExitStack() as stack:
            _apply_patches(stack, source)

            result_str = integrate_statistical_prior(
                bbox="121.0,31.0,121.1,31.1",
                att_estimate="-5.0",
                att_se="1.5",
                treatment_variable="建设用地",
                outcome_variable="树木",
                scenario="baseline",
                start_year="2023",
                n_years="5",
            )
        result = json.loads(result_str)
        self.assertEqual(result["status"], "warning")
        self.assertIn("message", result)
        self.assertIn("变化量接近 0", result["message"])

    @patch(f"{_WM}.LULC_CLASSES", _FAKE_LULC_CLASSES)
    def test_unknown_outcome_variable(self):
        """Unknown outcome variable name returns error."""
        with contextlib.ExitStack() as stack:
            _apply_patches(stack, {"SCENARIOS": _FAKE_SCENARIOS})

            result_str = integrate_statistical_prior(
                bbox="121.0,31.0,121.1,31.1",
                att_estimate="-5.0",
                att_se="1.5",
                treatment_variable="建设用地",
                outcome_variable="未知类别XYZ",
                scenario="baseline",
            )
        result = json.loads(result_str)
        self.assertEqual(result["status"], "error")
        self.assertIn("无法识别", result["error"])

    @patch(f"{_WM}.LULC_CLASSES", _FAKE_LULC_CLASSES)
    def test_predict_error_propagation(self):
        """predict_sequence returns error is propagated."""
        error_result = {"status": "error", "error": "Model not loaded"}
        source = {
            "predict_sequence": MagicMock(return_value=error_result),
            "SCENARIOS": _FAKE_SCENARIOS,
        }
        with contextlib.ExitStack() as stack:
            _apply_patches(stack, source)

            result_str = integrate_statistical_prior(
                bbox="121.0,31.0,121.1,31.1",
                att_estimate="-5.0",
                att_se="1.5",
                treatment_variable="建设用地",
                outcome_variable="树木",
                scenario="baseline",
            )
        result = json.loads(result_str)
        self.assertEqual(result["status"], "error")
        self.assertIn("Model not loaded", result["error"])


# ====================================================================
#  TestCausalWorldModelToolset
# ====================================================================

class TestCausalWorldModelToolset(unittest.TestCase):
    """Tests for the CausalWorldModelToolset registration."""

    def test_toolset_registration(self):
        """Instantiate toolset and get_tools returns 4 tools."""
        import asyncio
        from data_agent.toolsets.causal_world_model_tools import CausalWorldModelToolset

        toolset = CausalWorldModelToolset()
        tools = asyncio.get_event_loop().run_until_complete(toolset.get_tools())
        self.assertEqual(len(tools), 4)

    def test_long_running_tools(self):
        """intervention_predict and counterfactual_comparison are LongRunningFunctionTool."""
        import asyncio
        from google.adk.tools import LongRunningFunctionTool
        from data_agent.toolsets.causal_world_model_tools import CausalWorldModelToolset

        toolset = CausalWorldModelToolset()
        tools = asyncio.get_event_loop().run_until_complete(toolset.get_tools())

        long_running_count = sum(
            1 for t in tools if isinstance(t, LongRunningFunctionTool)
        )
        self.assertEqual(long_running_count, 2)


if __name__ == "__main__":
    unittest.main()
