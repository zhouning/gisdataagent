"""Tests for DreamerEnv — World Model + DRL integration."""

import unittest
import numpy as np
from unittest.mock import patch, MagicMock
import geopandas as gpd
from shapely.geometry import box
from gymnasium import spaces


# --- Test data helper ---
def _make_gdf(n=10):
    """Create synthetic parcel GeoDataFrame."""
    geoms = [box(i * 0.01, 0, (i + 1) * 0.01, 0.01) for i in range(n)]
    return gpd.GeoDataFrame(
        {
            'geometry': geoms,
            'DLBM': ['旱地'] * (n // 2) + ['有林地'] * (n - n // 2),
        },
        crs='EPSG:4326',
    )


# --- ActionToScenarioEncoder tests ---
class TestActionToScenarioEncoder(unittest.TestCase):

    def test_empty_history_gives_baseline(self):
        from data_agent.dreamer_env import ActionToScenarioEncoder
        enc = ActionToScenarioEncoder()
        vec = enc.encode()
        self.assertAlmostEqual(vec[4], 1.0)  # baseline
        self.assertAlmostEqual(vec.sum(), 1.0)

    def test_reforestation_dominant(self):
        from data_agent.dreamer_env import ActionToScenarioEncoder
        enc = ActionToScenarioEncoder()
        for _ in range(8):
            enc.record_action(1, 2)  # farmland -> forest
        for _ in range(2):
            enc.record_action(2, 1)
        vec = enc.encode()
        self.assertGreater(vec[1], vec[2])  # ecological > agricultural

    def test_deforestation_dominant(self):
        from data_agent.dreamer_env import ActionToScenarioEncoder
        enc = ActionToScenarioEncoder()
        for _ in range(8):
            enc.record_action(2, 1)  # forest -> farmland
        for _ in range(2):
            enc.record_action(1, 2)
        vec = enc.encode()
        self.assertGreater(vec[2], vec[1])  # agricultural > ecological

    def test_reset_clears_history(self):
        from data_agent.dreamer_env import ActionToScenarioEncoder
        enc = ActionToScenarioEncoder()
        enc.record_action(1, 2)
        enc.reset()
        self.assertEqual(enc.net_conversions, 0)
        self.assertAlmostEqual(enc.encode()[4], 1.0)

    def test_net_conversions(self):
        from data_agent.dreamer_env import ActionToScenarioEncoder
        enc = ActionToScenarioEncoder()
        enc.record_action(1, 2)
        enc.record_action(1, 2)
        enc.record_action(2, 1)
        self.assertEqual(enc.net_conversions, 1)

    def test_unrelated_action_ignored(self):
        """Actions not involving FARMLAND(1)/FOREST(2) are ignored."""
        from data_agent.dreamer_env import ActionToScenarioEncoder
        enc = ActionToScenarioEncoder()
        enc.record_action(0, 1)
        enc.record_action(3, 2)
        self.assertEqual(enc.net_conversions, 0)
        self.assertAlmostEqual(enc.encode()[4], 1.0)

    def test_encode_l1_normalized(self):
        from data_agent.dreamer_env import ActionToScenarioEncoder
        enc = ActionToScenarioEncoder()
        for _ in range(5):
            enc.record_action(1, 2)
        for _ in range(5):
            enc.record_action(2, 1)
        vec = enc.encode()
        self.assertAlmostEqual(vec.sum(), 1.0, places=5)


# --- ParcelEmbeddingMapper tests ---
class TestParcelEmbeddingMapper(unittest.TestCase):

    @patch('data_agent.dreamer_env._wm_extract_embeddings')
    def test_fallback_to_zeros(self, mock_extract):
        mock_extract.side_effect = RuntimeError("no GEE")
        from data_agent.dreamer_env import ParcelEmbeddingMapper
        gdf = _make_gdf(5)
        mapper = ParcelEmbeddingMapper(gdf, [0, 0, 0.1, 0.01], 2023)
        self.assertEqual(mapper.embeddings.shape, (5, 64))
        self.assertTrue(np.allclose(mapper.embeddings, 0))

    @patch('data_agent.dreamer_env._wm_extract_embeddings')
    def test_extraction_success_hwc(self, mock_extract):
        """Test with [H, W, 64] grid layout (extract_embeddings default)."""
        grid = np.random.randn(10, 10, 64).astype(np.float32)
        mock_extract.return_value = grid
        from data_agent.dreamer_env import ParcelEmbeddingMapper
        gdf = _make_gdf(5)
        mapper = ParcelEmbeddingMapper(gdf, [0, 0, 0.1, 0.01], 2023)
        self.assertEqual(mapper.embeddings.shape, (5, 64))
        self.assertFalse(np.allclose(mapper.embeddings, 0))

    @patch('data_agent.dreamer_env._wm_extract_embeddings')
    def test_extraction_success_chw(self, mock_extract):
        """Test with [64, H, W] grid layout."""
        grid = np.random.randn(64, 10, 10).astype(np.float32)
        mock_extract.return_value = grid
        from data_agent.dreamer_env import ParcelEmbeddingMapper
        gdf = _make_gdf(5)
        mapper = ParcelEmbeddingMapper(gdf, [0, 0, 0.1, 0.01], 2023)
        self.assertEqual(mapper.embeddings.shape, (5, 64))
        self.assertFalse(np.allclose(mapper.embeddings, 0))

    @patch('data_agent.dreamer_env._wm_extract_embeddings')
    def test_coherence_no_neighbors(self, mock_extract):
        mock_extract.side_effect = RuntimeError("no GEE")
        from data_agent.dreamer_env import ParcelEmbeddingMapper
        gdf = _make_gdf(3)
        mapper = ParcelEmbeddingMapper(gdf, [0, 0, 0.1, 0.01])
        self.assertEqual(mapper.get_coherence(0, []), 0.0)

    @patch('data_agent.dreamer_env._wm_extract_embeddings')
    def test_get_embedding_returns_64d(self, mock_extract):
        mock_extract.return_value = None
        from data_agent.dreamer_env import ParcelEmbeddingMapper
        gdf = _make_gdf(3)
        mapper = ParcelEmbeddingMapper(gdf, [0, 0, 0.1, 0.01])
        emb = mapper.get_embedding(0)
        self.assertEqual(emb.shape, (64,))


# --- DreamerEnv tests ---
class TestDreamerEnv(unittest.TestCase):

    def _make_base_env(self, n=10):
        """Create a mock base environment mimicking LandUseOptEnv."""
        env = MagicMock()
        env.gdf = _make_gdf(n)
        env.land_use = np.array([1] * (n // 2) + [2] * (n - n // 2))
        env.swappable_indices = np.arange(n)
        env.observation_space = MagicMock()
        env.action_space = MagicMock()
        env.reset.return_value = (np.zeros(68), {})
        env.step.return_value = (np.zeros(68), 1.5, False, False, {})
        return env

    def test_init_without_world_model(self):
        from data_agent.dreamer_env import DreamerEnv
        base = self._make_base_env()
        env = DreamerEnv(base, enable_world_model=False)
        self.assertFalse(env.world_model_available)

    def test_reset_clears_state(self):
        from data_agent.dreamer_env import DreamerEnv
        base = self._make_base_env()
        env = DreamerEnv(base, enable_world_model=False)
        env.scenario_encoder.record_action(1, 2)
        env.reset()
        self.assertEqual(env.scenario_encoder.net_conversions, 0)
        self.assertEqual(env._step_counter, 0)

    def test_step_returns_augmented_info(self):
        from data_agent.dreamer_env import DreamerEnv
        base = self._make_base_env()
        env = DreamerEnv(base, enable_world_model=False)
        env.reset()
        obs, reward, term, trunc, info = env.step(0)
        self.assertIn('base_reward', info)
        self.assertIn('aux_reward', info)
        self.assertIn('scenario_vector', info)
        self.assertIn('net_conversions', info)

    def test_reward_equals_base_when_no_world_model(self):
        from data_agent.dreamer_env import DreamerEnv
        base = self._make_base_env()
        env = DreamerEnv(base, enable_world_model=False)
        env.reset()
        obs, reward, _, _, info = env.step(0)
        # Without world model, total reward = base_reward + 0
        self.assertEqual(reward, info['base_reward'])

    def test_step_counter_increments(self):
        from data_agent.dreamer_env import DreamerEnv
        base = self._make_base_env()
        env = DreamerEnv(base, enable_world_model=False)
        env.reset()
        env.step(0)
        env.step(1)
        self.assertEqual(env._step_counter, 2)

    @patch('data_agent.dreamer_env._wm_extract_embeddings')
    def test_graceful_degradation_on_wm_error(self, mock_extract):
        mock_extract.side_effect = RuntimeError("fail")
        from data_agent.dreamer_env import DreamerEnv
        base = self._make_base_env()
        env = DreamerEnv(base, enable_world_model=True)
        # Should not raise, just log warning
        env.reset()
        obs, reward, _, _, _ = env.step(0)
        self.assertIsNotNone(reward)

    def test_extract_bbox_from_gdf(self):
        from data_agent.dreamer_env import DreamerEnv
        base = self._make_base_env()
        env = DreamerEnv(base, enable_world_model=False)
        # bbox should be derived from gdf total_bounds
        self.assertEqual(len(env.bbox), 4)

    def test_delegation_observation_space(self):
        from data_agent.dreamer_env import DreamerEnv
        base = self._make_base_env()
        env = DreamerEnv(base, enable_world_model=False)
        self.assertIs(env.observation_space, base.observation_space)

    def test_delegation_action_space(self):
        from data_agent.dreamer_env import DreamerEnv
        base = self._make_base_env()
        env = DreamerEnv(base, enable_world_model=False)
        self.assertIs(env.action_space, base.action_space)

    def test_scenario_vector_in_info(self):
        """Scenario vector should be a 16-element list."""
        from data_agent.dreamer_env import DreamerEnv
        base = self._make_base_env()
        env = DreamerEnv(base, enable_world_model=False)
        env.reset()
        _, _, _, _, info = env.step(0)
        self.assertEqual(len(info['scenario_vector']), 16)


# --- EmbeddingAugmentedEnv tests ---
class TestEmbeddingAugmentedEnv(unittest.TestCase):

    def test_augmented_obs_dimension(self):
        from data_agent.dreamer_env import DreamerEnv, EmbeddingAugmentedEnv
        base = MagicMock()
        base.gdf = _make_gdf(10)
        base.types = np.array([1] * 5 + [2] * 5)
        base.n_swappable = 10
        base.swappable_indices = list(range(10))
        base.observation_space = spaces.Box(low=-np.inf, high=np.inf, shape=(68,))
        base.action_space = spaces.Discrete(10)
        base.reset.return_value = (np.zeros(68), {})
        base.step.return_value = (np.zeros(68), 1.0, False, False, {})
        base.total_bounds = base.gdf.total_bounds

        dreamer = DreamerEnv(base, enable_world_model=False)
        aug_env = EmbeddingAugmentedEnv(dreamer)
        self.assertEqual(aug_env.observation_space.shape[0], 68 + 20)  # +2*10

    def test_augmented_reset_returns_correct_shape(self):
        from data_agent.dreamer_env import DreamerEnv, EmbeddingAugmentedEnv
        base = MagicMock()
        base.gdf = _make_gdf(10)
        base.types = np.array([1] * 5 + [2] * 5)
        base.n_swappable = 10
        base.swappable_indices = list(range(10))
        base.observation_space = spaces.Box(low=-np.inf, high=np.inf, shape=(68,))
        base.action_space = spaces.Discrete(10)
        base.reset.return_value = (np.zeros(68), {})
        base.total_bounds = base.gdf.total_bounds

        dreamer = DreamerEnv(base, enable_world_model=False)
        aug_env = EmbeddingAugmentedEnv(dreamer)
        obs, info = aug_env.reset()
        self.assertEqual(obs.shape[0], 88)

    def test_augment_passthrough_when_no_mapper(self):
        """When embedding_mapper is None, obs is returned unchanged."""
        from data_agent.dreamer_env import DreamerEnv, EmbeddingAugmentedEnv
        base = MagicMock()
        base.gdf = _make_gdf(4)
        base.n_swappable = 0
        base.observation_space = spaces.Box(low=-np.inf, high=np.inf, shape=(68,))
        base.action_space = spaces.Discrete(4)
        base.reset.return_value = (np.ones(68), {})
        base.total_bounds = base.gdf.total_bounds

        dreamer = DreamerEnv(base, enable_world_model=False)
        aug_env = EmbeddingAugmentedEnv(dreamer)
        obs, _ = aug_env.reset()
        self.assertEqual(obs.shape[0], 68)


# --- DreamPlanner tests ---
class TestDreamPlanner(unittest.TestCase):

    def test_dream_trajectory_without_model(self):
        from data_agent.dreamer_env import DreamPlanner, ParcelEmbeddingMapper, ActionToScenarioEncoder
        mapper = MagicMock(spec=ParcelEmbeddingMapper)
        encoder = ActionToScenarioEncoder()
        planner = DreamPlanner(mapper, encoder)
        # Force model loading to fail so trajectory returns empty
        with patch('data_agent.dreamer_env.DreamPlanner._ensure_model', return_value=False):
            result = planner.dream_trajectory(np.zeros((64, 8, 8)), np.zeros(16))
        self.assertEqual(result, [])

    def test_evaluate_candidates_without_model(self):
        from data_agent.dreamer_env import DreamPlanner, ParcelEmbeddingMapper, ActionToScenarioEncoder
        mapper = MagicMock(spec=ParcelEmbeddingMapper)
        mapper.embeddings = None
        encoder = ActionToScenarioEncoder()
        planner = DreamPlanner(mapper, encoder)
        result = planner.evaluate_action_candidates(mapper, [0, 1, 2], np.array([1, 2, 1]))
        self.assertEqual(len(result), 3)
        self.assertTrue(all(score == 0.0 for _, score in result))

    def test_default_horizon(self):
        from data_agent.dreamer_env import DreamPlanner, ActionToScenarioEncoder
        mapper = MagicMock()
        encoder = ActionToScenarioEncoder()
        planner = DreamPlanner(mapper, encoder, horizon=5)
        self.assertEqual(planner.horizon, 5)
        self.assertAlmostEqual(planner.gamma, 0.95)


# --- LatentValueEstimator tests ---
class TestLatentValueEstimator(unittest.TestCase):

    def test_predict_returns_scalar(self):
        from data_agent.dreamer_env import LatentValueEstimator
        estimator = LatentValueEstimator()
        v = estimator.predict(np.zeros(64), np.zeros(8))
        self.assertIsInstance(v, float)

    def test_add_experience_and_train(self):
        from data_agent.dreamer_env import LatentValueEstimator
        estimator = LatentValueEstimator()
        for i in range(50):
            estimator.add_experience(np.random.randn(64), np.random.randn(8), float(i))
        loss = estimator.train_step(batch_size=32)
        self.assertGreater(loss, 0.0)

    def test_clear_buffer(self):
        from data_agent.dreamer_env import LatentValueEstimator
        estimator = LatentValueEstimator()
        estimator.add_experience(np.zeros(64), np.zeros(8), 1.0)
        self.assertEqual(len(estimator._buffer), 1)
        estimator.clear_buffer()
        self.assertEqual(len(estimator._buffer), 0)

    def test_train_step_insufficient_data(self):
        """train_step returns 0 when buffer has fewer items than batch_size."""
        from data_agent.dreamer_env import LatentValueEstimator
        estimator = LatentValueEstimator()
        estimator.add_experience(np.zeros(64), np.zeros(8), 1.0)
        loss = estimator.train_step(batch_size=32)
        self.assertEqual(loss, 0.0)


# --- DreamerToolset registration ---
class TestDreamerToolsetRegistration(unittest.TestCase):

    def test_in_toolset_names(self):
        from data_agent.custom_skills import TOOLSET_NAMES
        self.assertIn("DreamerToolset", TOOLSET_NAMES)

    def test_toolset_get_tools(self):
        import asyncio
        from data_agent.toolsets.dreamer_tools import DreamerToolset
        toolset = DreamerToolset()
        tools = asyncio.get_event_loop().run_until_complete(toolset.get_tools())
        tool_names = [t.name for t in tools]
        self.assertIn("dreamer_optimize", tool_names)
        self.assertIn("dreamer_status", tool_names)


if __name__ == "__main__":
    unittest.main()
