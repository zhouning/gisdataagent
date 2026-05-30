"""Tests for Dual-Layer Geospatial Dreamer modules."""

import unittest
import tempfile
import os
import numpy as np
import torch


class TestTransitionModel(unittest.TestCase):

    def test_forward_shape(self):
        from data_agent.transition_model import TransitionModel
        n_blocks = 50
        model = TransitionModel(n_blocks)
        bf = torch.randn(2, n_blocks, 17)
        gf = torch.randn(2, 12)
        a = torch.tensor([3, 10])
        nbf, ngf, r = model(bf, gf, a)
        self.assertEqual(nbf.shape, (2, n_blocks, 17))
        self.assertEqual(ngf.shape, (2, 12))
        self.assertEqual(r.shape, (2, 1))

    def test_residual_only_selected_block(self):
        from data_agent.transition_model import TransitionModel
        n_blocks = 20
        model = TransitionModel(n_blocks)
        bf = torch.randn(1, n_blocks, 17)
        gf = torch.randn(1, 12)
        a = torch.tensor([5])
        with torch.no_grad():
            nbf, _, _ = model(bf, gf, a)
        for i in range(n_blocks):
            if i != 5:
                self.assertTrue(torch.allclose(nbf[0, i], bf[0, i]),
                                f"Block {i} should not change")

    def test_param_count(self):
        from data_agent.transition_model import TransitionModel
        model = TransitionModel(338)
        n_params = sum(p.numel() for p in model.parameters())
        self.assertGreater(n_params, 100_000)
        self.assertLess(n_params, 500_000)


class TestTrajectoryCollector(unittest.TestCase):

    def test_save_load_roundtrip(self):
        from data_agent.transition_model import TrajectoryCollector
        c = TrajectoryCollector()
        n_blocks = 10
        for _ in range(5):
            c.block_features.append(np.random.randn(n_blocks, 17).astype(np.float32))
            c.global_features.append(np.random.randn(12).astype(np.float32))
            c.actions.append(np.random.randint(0, n_blocks))
            c.rewards.append(np.random.randn())
            c.next_block_features.append(np.random.randn(n_blocks, 17).astype(np.float32))
            c.next_global_features.append(np.random.randn(12).astype(np.float32))

        with tempfile.NamedTemporaryFile(suffix=".npz", delete=False) as f:
            path = f.name
        try:
            c.save(path)
            c2 = TrajectoryCollector()
            c2.load(path)
            self.assertEqual(c2.size, 5)
            data = c2.as_arrays()
            self.assertEqual(data["block_features"].shape, (5, n_blocks, 17))
        finally:
            os.unlink(path)


class TestTransitionModelTrainer(unittest.TestCase):

    def test_train_reduces_loss(self):
        from data_agent.transition_model import TransitionModel, TransitionModelTrainer
        n_blocks = 10
        model = TransitionModel(n_blocks)
        trainer = TransitionModelTrainer(model, epochs=5)

        rng = np.random.default_rng(42)
        n = 100
        bf = rng.normal(0, 1, (n, n_blocks, 17)).astype(np.float32)
        gf = rng.normal(0, 1, (n, 12)).astype(np.float32)
        actions = rng.integers(0, n_blocks, n).astype(np.int64)
        rewards = rng.normal(-1, 0.2, n).astype(np.float32)
        nbf = bf.copy()
        for i in range(n):
            nbf[i, actions[i]] += rng.normal(0, 0.05, 17).astype(np.float32)
        ngf = gf + rng.normal(0, 0.02, (n, 12)).astype(np.float32)

        data = {
            "block_features": bf, "global_features": gf,
            "actions": actions, "rewards": rewards,
            "next_block_features": nbf, "next_global_features": ngf,
        }
        history = trainer.train(data)
        self.assertGreater(len(history["train_loss"]), 0)
        self.assertLess(history["train_loss"][-1], history["train_loss"][0])


class TestCrossLayerCalibrator(unittest.TestCase):

    def test_fit_and_predict(self):
        from data_agent.dual_layer_dreamer import CrossLayerCalibrator
        cal = CrossLayerCalibrator(n_blocks=50)
        bd = np.random.randn(100, 17).astype(np.float32)
        ed = bd @ np.random.randn(17, 64).astype(np.float32)
        cal.fit(bd, ed)
        pred = cal.predict_embedding_displacement(bd[0])
        self.assertEqual(pred.shape, (64,))

    def test_consistency_score(self):
        from data_agent.dual_layer_dreamer import CrossLayerCalibrator
        cal = CrossLayerCalibrator(n_blocks=50)
        a = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        b = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        self.assertAlmostEqual(cal.consistency_score(a, b), 1.0, places=5)

    def test_calibrate_reward(self):
        from data_agent.dual_layer_dreamer import CrossLayerCalibrator
        cal = CrossLayerCalibrator(n_blocks=50, reward_calibration_alpha=0.5)
        self.assertAlmostEqual(cal.calibrate_reward(2.0), 1.0)


class TestDualLayerDreamEnv(unittest.TestCase):

    def _make_env(self, n_blocks=20, n_states=10):
        from data_agent.transition_model import TransitionModel
        from data_agent.dual_layer_dreamer import DualLayerDreamEnv
        tm = TransitionModel(n_blocks)
        obs_dim = n_blocks * 17 + 12
        states = np.random.randn(n_states, obs_dim).astype(np.float32)
        return DualLayerDreamEnv(
            transition_model=tm,
            initial_states=states,
            n_blocks=n_blocks,
            max_steps=10,
        )

    def test_reset_and_step(self):
        env = self._make_env()
        obs, info = env.reset(seed=42)
        self.assertEqual(obs.shape, (20 * 17 + 12,))
        obs2, reward, term, trunc, info = env.step(0)
        self.assertEqual(obs2.shape, obs.shape)
        self.assertIsInstance(reward, float)

    def test_episode_terminates(self):
        env = self._make_env(n_blocks=10)
        env.reset(seed=1)
        for _ in range(10):
            _, _, term, trunc, _ = env.step(0)
        self.assertTrue(term or trunc)

    def test_action_masks(self):
        env = self._make_env()
        env.reset(seed=42)
        mask = env.action_masks()
        self.assertEqual(mask.shape, (20,))
        self.assertTrue(mask.any())


class TestDreamDatasetCollector(unittest.TestCase):

    def test_save_load(self):
        from data_agent.dual_layer_dreamer import DreamDatasetCollector
        c = DreamDatasetCollector()
        for _ in range(10):
            c.add(np.random.randn(17).astype(np.float32),
                  np.random.randn(64).astype(np.float32))
        with tempfile.NamedTemporaryFile(suffix=".npz", delete=False) as f:
            path = f.name
        try:
            c.save(path)
            c2 = DreamDatasetCollector.load(path)
            self.assertEqual(len(c2), 10)
            bd, ed = c2.get_arrays()
            self.assertEqual(bd.shape, (10, 17))
            self.assertEqual(ed.shape, (10, 64))
        finally:
            os.unlink(path)


class TestLearnedBlockEnv(unittest.TestCase):

    def test_reset_step(self):
        from data_agent.transition_model import TransitionModel, LearnedBlockEnv
        n_blocks = 15
        model = TransitionModel(n_blocks)
        rng = np.random.default_rng(0)
        data = {
            "block_features": rng.normal(0, 1, (5, n_blocks, 17)).astype(np.float32),
            "global_features": rng.normal(0, 1, (5, 12)).astype(np.float32),
        }
        env = LearnedBlockEnv(model, data, max_steps=5)
        obs, _ = env.reset(seed=42)
        self.assertEqual(obs.shape, (n_blocks * 17 + 12,))
        obs2, r, term, trunc, _ = env.step(3)
        self.assertEqual(obs2.shape, obs.shape)


if __name__ == "__main__":
    unittest.main()
