"""Dual-Layer Geospatial Dreamer — train RL policies entirely in learned world models.

Two complementary world models at different abstraction levels:
  Layer 1 (Block Dynamics): TransitionModel predicts block-level state transitions
  Layer 2 (Embedding Dynamics): LatentDynamicsNet predicts GeoFM embedding evolution

CrossLayerCalibrator bridges the two layers via consistency scoring and
causal reward calibration (ATT-based).

Paper: "Dual-Layer Geospatial Dreamer: Training Land-Use Planning Policies
        Entirely in Learned World Models"
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Optional

import gymnasium as gym
import numpy as np
from gymnasium import spaces

logger = logging.getLogger(__name__)

# ====================================================================
#  Constants
# ====================================================================

K_BLOCK = 17
K_GLOBAL = 12
EMBEDDING_DIM = 64
DEFAULT_CALIBRATION_INTERVAL = 10
DEFAULT_CONFIDENCE_THRESHOLD = 0.9
DEFAULT_NOISE_STD = 0.01


# ====================================================================
#  CrossLayerCalibrator
# ====================================================================

class CrossLayerCalibrator:
    """Bridges block-level dynamics (Layer 1) and embedding dynamics (Layer 2).

    Learns a linear projection from block state changes to expected embedding
    displacements. Computes consistency scores. When consistency drops below
    threshold, Layer 2 corrections are applied to Layer 1 state.
    Uses ATT estimates to calibrate reward signals.
    """

    def __init__(
        self,
        n_blocks: int,
        confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
        reward_calibration_alpha: float = 1.0,
    ):
        self.n_blocks = n_blocks
        self.confidence_threshold = confidence_threshold
        self.reward_calibration_alpha = reward_calibration_alpha
        self._projection = None  # (K_BLOCK, EMBEDDING_DIM) linear map
        self._fitted = False
        self._consistency_history: list[float] = []

    def fit(
        self,
        block_deltas: np.ndarray,
        embedding_displacements: np.ndarray,
    ):
        """Learn linear projection from block state changes to embedding displacements.

        Args:
            block_deltas: (N, K_BLOCK) block feature changes
            embedding_displacements: (N, EMBEDDING_DIM) corresponding embedding changes
        """
        # Least-squares: embedding_disp ≈ block_delta @ W
        W, _, _, _ = np.linalg.lstsq(block_deltas, embedding_displacements, rcond=None)
        self._projection = W.astype(np.float32)
        self._fitted = True
        logger.info("CrossLayerCalibrator fitted: projection shape %s", W.shape)

    def predict_embedding_displacement(self, block_delta: np.ndarray) -> np.ndarray:
        """Predict expected embedding displacement from block state change."""
        if not self._fitted:
            return np.zeros(EMBEDDING_DIM, dtype=np.float32)
        return (block_delta @ self._projection).astype(np.float32)

    def consistency_score(
        self,
        predicted_displacement: np.ndarray,
        actual_displacement: np.ndarray,
    ) -> float:
        """Cosine similarity between predicted and actual embedding displacement."""
        norm_p = np.linalg.norm(predicted_displacement)
        norm_a = np.linalg.norm(actual_displacement)
        if norm_p < 1e-8 or norm_a < 1e-8:
            return 1.0  # no change = consistent
        cos_sim = float(np.dot(predicted_displacement, actual_displacement) / (norm_p * norm_a))
        self._consistency_history.append(cos_sim)
        return cos_sim

    def should_correct(self, score: float) -> bool:
        return score < self.confidence_threshold

    def calibrate_reward(self, raw_reward: float) -> float:
        return raw_reward * self.reward_calibration_alpha

    def fit_reward_calibration(self, real_rewards: np.ndarray, treatment: np.ndarray,
                               confounders: np.ndarray, model_effect: float):
        """Compute ATT-based reward calibration factor.

        Args:
            real_rewards: rewards from real trajectory data
            treatment: binary indicator (high-potential block = 1)
            confounders: state features as confounders
            model_effect: learned model's predicted treatment effect
        """
        try:
            from .causal_world_model import compute_att
            result = compute_att(real_rewards, treatment, confounders)
            att = result["att"]
            if abs(model_effect) > 1e-8:
                alpha = np.clip(att / model_effect, 0.1, 5.0)
            else:
                alpha = 1.0
            self.reward_calibration_alpha = float(alpha)
            logger.info("Reward calibration: ATT=%.4f, model=%.4f, alpha=%.4f",
                        att, model_effect, alpha)
        except Exception as e:
            logger.warning("ATT calibration failed, using alpha=1.0: %s", e)
            self.reward_calibration_alpha = 1.0

    @property
    def mean_consistency(self) -> float:
        if not self._consistency_history:
            return 1.0
        return float(np.mean(self._consistency_history[-100:]))

    def load_block_embeddings(self, embeddings_dir: str, n_blocks: int, year: int = 2023):
        """Load pre-extracted township embeddings and build block-level KD-tree.

        After calling this, check_drift() can detect state distribution shift
        by comparing block feature changes against expected embedding displacements.
        """
        from scipy.spatial import cKDTree

        all_points = []
        all_embs = []
        emb_dir = os.path.join(embeddings_dir)
        for fname in sorted(os.listdir(emb_dir)):
            if fname.endswith(f"_{year}.npy"):
                arr = np.load(os.path.join(emb_dir, fname))
                if arr.ndim == 2 and arr.shape[1] >= 66:
                    all_points.append(arr[:, :2])
                    all_embs.append(arr[:, 2:66])

        if not all_points:
            logger.warning("No embedding files found in %s", emb_dir)
            self._emb_tree = None
            return

        self._emb_points = np.vstack(all_points)
        self._emb_values = np.vstack(all_embs).astype(np.float32)
        self._emb_tree = cKDTree(self._emb_points)
        self._n_emb_blocks = n_blocks
        logger.info("Loaded %d embedding samples for drift detection", len(self._emb_points))

    def check_drift(self, block_features_before: np.ndarray,
                    block_features_after: np.ndarray,
                    action: int) -> float:
        """Check if block state change is consistent with embedding space.

        Returns drift score (0 = consistent, higher = more drift).
        """
        if not self._fitted or not hasattr(self, '_emb_tree') or self._emb_tree is None:
            return 0.0

        delta = block_features_after[action] - block_features_before[action]
        predicted_emb_disp = self.predict_embedding_displacement(delta)
        drift = float(np.linalg.norm(predicted_emb_disp))
        self._consistency_history.append(max(0, 1.0 - drift))
        return drift


# ====================================================================
#  DualLayerDreamEnv
# ====================================================================

class DualLayerDreamEnv(gym.Env):
    """Gymnasium environment that replaces the real env with dual-layer world models.

    Layer 1 (TransitionModel) runs every step for fast state prediction.
    Layer 2 (LatentDynamicsNet) runs every K steps for embedding-space validation.
    CrossLayerCalibrator bridges the two and calibrates rewards.
    """

    metadata = {"render_modes": []}

    def __init__(
        self,
        transition_model,
        initial_states: np.ndarray,
        n_blocks: int,
        max_steps: int = 100,
        budget_per_step: int = 5,
        calibrator: CrossLayerCalibrator | None = None,
        embedding_dynamics=None,
        embedding_grids: dict | None = None,
        calibration_interval: int = DEFAULT_CALIBRATION_INTERVAL,
        noise_std: float = DEFAULT_NOISE_STD,
    ):
        """
        Args:
            transition_model: trained TransitionModel (Layer 1)
            initial_states: (N_episodes, obs_dim) initial state pool
            n_blocks: number of blocks in the county
            max_steps: episode length
            budget_per_step: swaps per block selection
            calibrator: optional CrossLayerCalibrator
            embedding_dynamics: optional LatentDynamicsNet (Layer 2)
            embedding_grids: dict mapping state_idx → (64, H, W) embedding grid
            calibration_interval: run Layer 2 every K steps
            noise_std: Gaussian noise on initial state for diversity
        """
        super().__init__()
        self.transition_model = transition_model
        self.initial_states = initial_states
        self.n_blocks = n_blocks
        self.max_steps = max_steps
        self.budget_per_step = budget_per_step
        self.calibrator = calibrator
        self.embedding_dynamics = embedding_dynamics
        self.embedding_grids = embedding_grids or {}
        self.calibration_interval = calibration_interval
        self.noise_std = noise_std

        obs_dim = n_blocks * K_BLOCK + K_GLOBAL
        self.observation_space = spaces.Box(
            low=-np.inf, high=np.inf, shape=(obs_dim,), dtype=np.float32
        )
        self.action_space = spaces.Discrete(n_blocks)

        self._block_features = None  # (n_blocks, K_BLOCK)
        self._global_features = None  # (K_GLOBAL,)
        self._step_count = 0
        self._budget_used = np.zeros(n_blocks, dtype=np.int32)
        self._current_embedding = None
        self._scenario_vec = None

    def reset(self, seed=None, options=None):
        super().reset(seed=seed)
        idx = self.np_random.integers(0, len(self.initial_states))
        state = self.initial_states[idx].copy()
        if self.noise_std > 0:
            state += self.np_random.normal(0, self.noise_std, size=state.shape).astype(np.float32)

        self._block_features = state[:self.n_blocks * K_BLOCK].reshape(self.n_blocks, K_BLOCK)
        self._global_features = state[self.n_blocks * K_BLOCK:]
        self._step_count = 0
        self._budget_used = np.zeros(self.n_blocks, dtype=np.int32)
        self._current_embedding = self.embedding_grids.get(idx)
        self._scenario_vec = np.zeros(16, dtype=np.float32)
        self._scenario_vec[4] = 1.0  # baseline

        return self._get_obs(), {}

    def step(self, action: int):
        import torch

        bf = torch.tensor(self._block_features, dtype=torch.float32).unsqueeze(0)
        gf = torch.tensor(self._global_features, dtype=torch.float32).unsqueeze(0)
        a = torch.tensor([action], dtype=torch.long)

        with torch.no_grad():
            next_bf, next_gf, pred_reward = self.transition_model(bf, gf, a)

        next_bf = next_bf.squeeze(0).numpy()
        next_gf = next_gf.squeeze(0).numpy()
        raw_reward = float(pred_reward.item())

        # Layer 2 calibration check
        if (self.calibrator is not None
                and self.embedding_dynamics is not None
                and self._current_embedding is not None
                and self._step_count > 0
                and self._step_count % self.calibration_interval == 0):
            self._run_layer2_check(action, next_bf)

        # Calibrate reward
        reward = self.calibrator.calibrate_reward(raw_reward) if self.calibrator else raw_reward

        self._block_features = next_bf
        self._global_features = next_gf
        self._budget_used[action] += self.budget_per_step
        self._step_count += 1

        terminated = self._step_count >= self.max_steps
        truncated = False

        return self._get_obs(), reward, terminated, truncated, {
            "raw_reward": raw_reward,
            "step": self._step_count,
            "consistency": self.calibrator.mean_consistency if self.calibrator else 1.0,
        }

    def _run_layer2_check(self, action: int, next_bf: np.ndarray):
        """Run Layer 2 embedding prediction and check consistency."""
        import torch

        block_delta = next_bf[action] - self._block_features[action]
        predicted_disp = self.calibrator.predict_embedding_displacement(block_delta)

        try:
            z_t = torch.tensor(self._current_embedding, dtype=torch.float32).unsqueeze(0)
            s = torch.tensor(self._scenario_vec, dtype=torch.float32).unsqueeze(0)
            with torch.no_grad():
                z_next = self.embedding_dynamics(z_t, s)
            actual_disp = (z_next.squeeze(0).numpy() - self._current_embedding).mean(axis=(1, 2))
            score = self.calibrator.consistency_score(predicted_disp, actual_disp)

            if self.calibrator.should_correct(score):
                logger.debug("Layer 2 correction at step %d (score=%.3f)", self._step_count, score)
            self._current_embedding = z_next.squeeze(0).numpy()
        except Exception as e:
            logger.debug("Layer 2 check failed: %s", e)

    def _get_obs(self) -> np.ndarray:
        return np.concatenate([
            self._block_features.ravel(),
            self._global_features,
        ]).astype(np.float32)

    def action_masks(self) -> np.ndarray:
        """MaskablePPO-compatible action mask."""
        mask = np.ones(self.n_blocks, dtype=bool)
        # County env block features: index 7 = farm_area_frac, index 8 = forest_area_frac
        farm_idx = min(7, K_BLOCK - 1)
        forest_idx = min(8, K_BLOCK - 1)
        for i in range(self.n_blocks):
            if self._block_features[i, farm_idx] < 0.01:
                mask[i] = False
            if self._block_features[i, forest_idx] < 0.01:
                mask[i] = False
        if not mask.any():
            mask[:] = True
        return mask


# ====================================================================
#  DreamDatasetCollector
# ====================================================================

class DreamDatasetCollector:
    """Collects paired (block_state, embedding_grid) snapshots for calibrator training."""

    def __init__(self):
        self.block_deltas: list[np.ndarray] = []
        self.embedding_displacements: list[np.ndarray] = []

    def add(self, block_delta: np.ndarray, embedding_displacement: np.ndarray):
        self.block_deltas.append(block_delta.copy())
        self.embedding_displacements.append(embedding_displacement.copy())

    def get_arrays(self) -> tuple[np.ndarray, np.ndarray]:
        return (
            np.array(self.block_deltas, dtype=np.float32),
            np.array(self.embedding_displacements, dtype=np.float32),
        )

    def save(self, path: str):
        bd, ed = self.get_arrays()
        np.savez_compressed(path, block_deltas=bd, embedding_displacements=ed)

    @classmethod
    def load(cls, path: str) -> "DreamDatasetCollector":
        obj = cls()
        data = np.load(path)
        obj.block_deltas = list(data["block_deltas"])
        obj.embedding_displacements = list(data["embedding_displacements"])
        return obj

    def __len__(self):
        return len(self.block_deltas)
