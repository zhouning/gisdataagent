"""Block-level neural transition model for county-level farmland consolidation.

Learns state dynamics from trajectory data: given current block states + action,
predicts next-step block states + reward. Enables model-based RL training
entirely on CPU without the expensive real environment.

Paper reference: "Causally Calibrated Model-Based RL for Farmland Consolidation"
"""

import logging
import pathlib
from typing import Optional, Tuple

import numpy as np
import torch
import torch.nn as nn
import gymnasium as gym
from gymnasium import spaces

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
N_BLOCKS_MAX = 338   # max blocks per township (MARL) or 2600 (county)
K_BLOCK = 17         # features per block
K_GLOBAL = 12        # global features
BUDGET_PER_STEP = 5  # swaps executed per block selection


# ---------------------------------------------------------------------------
# TransitionModel (~237K params)
# ---------------------------------------------------------------------------
class TransitionModel(nn.Module):
    """Predicts block-level state transitions and reward.

    Architecture:
        - Block encoder: shared MLP (17->64->32) applied per block
        - Action embedding: Embed(n_actions) -> R^32
        - Global encoder: MLP (12->64->32)
        - Context: concat [selected_block_enc, action_emb, global_enc, mean_pool] -> 128D
        - Heads: block_delta (128->256->256->17), global_delta (128->256->12), reward (128->64->1)

    Only the selected block changes (residual formulation).
    """

    def __init__(self, n_blocks: int, n_actions: Optional[int] = None):
        super().__init__()
        self.n_blocks = n_blocks
        self.n_actions = n_actions or n_blocks

        # Block encoder (shared across all blocks)
        self.block_enc = nn.Sequential(
            nn.Linear(K_BLOCK, 64), nn.ReLU(),
            nn.Linear(64, 32), nn.ReLU(),
        )
        # Action embedding
        self.action_emb = nn.Embedding(self.n_actions, 32)
        # Global encoder
        self.global_enc = nn.Sequential(
            nn.Linear(K_GLOBAL, 64), nn.ReLU(),
            nn.Linear(64, 32), nn.ReLU(),
        )
        # Context aggregation: selected_block(32) + action(32) + global(32) + mean_pool(32) = 128
        ctx_dim = 128
        # Output heads
        self.block_delta_head = nn.Sequential(
            nn.Linear(ctx_dim, 256), nn.ReLU(),
            nn.Linear(256, 256), nn.ReLU(),
            nn.Linear(256, K_BLOCK),
        )
        self.global_delta_head = nn.Sequential(
            nn.Linear(ctx_dim, 256), nn.ReLU(),
            nn.Linear(256, K_GLOBAL),
        )
        self.reward_head = nn.Sequential(
            nn.Linear(ctx_dim, 64), nn.ReLU(),
            nn.Linear(64, 1),
        )

    def forward(
        self,
        block_features: torch.Tensor,   # (B, n_blocks, K_BLOCK)
        global_features: torch.Tensor,   # (B, K_GLOBAL)
        action: torch.Tensor,            # (B,) int64
    ) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        """Predict next state and reward.

        Returns:
            next_block_features: (B, n_blocks, K_BLOCK)
            next_global_features: (B, K_GLOBAL)
            reward: (B, 1)
        """
        B = block_features.shape[0]

        # Encode all blocks: (B, n_blocks, 32)
        all_enc = self.block_enc(block_features)
        mean_pool = all_enc.mean(dim=1)  # (B, 32)

        # Selected block encoding
        idx = action.long().unsqueeze(-1).unsqueeze(-1).expand(B, 1, 32)
        selected_enc = all_enc.gather(1, idx).squeeze(1)  # (B, 32)

        # Action + global
        act_emb = self.action_emb(action.long())  # (B, 32)
        glb_enc = self.global_enc(global_features)  # (B, 32)

        # Context vector
        ctx = torch.cat([selected_enc, act_emb, glb_enc, mean_pool], dim=-1)  # (B, 128)

        # Predict deltas
        b_delta = self.block_delta_head(ctx)   # (B, K_BLOCK)
        g_delta = self.global_delta_head(ctx)  # (B, K_GLOBAL)
        reward = self.reward_head(ctx)         # (B, 1)

        # Residual: only selected block changes
        next_block = block_features.clone()
        action_idx = action.long().unsqueeze(-1).unsqueeze(-1).expand(B, 1, K_BLOCK)
        selected_block = next_block.gather(1, action_idx)
        updated = selected_block + b_delta.unsqueeze(1)
        next_block.scatter_(1, action_idx, updated)

        next_global = global_features + g_delta
        return next_block, next_global, reward


# ---------------------------------------------------------------------------
# TrajectoryCollector
# ---------------------------------------------------------------------------
class TrajectoryCollector:
    """Collects (state, action, reward, next_state) tuples from a Gymnasium env.

    Supports behavioral policies: 'random', 'greedy' (highest slope gap block).
    """

    def __init__(self):
        self.block_features: list = []
        self.global_features: list = []
        self.actions: list = []
        self.rewards: list = []
        self.next_block_features: list = []
        self.next_global_features: list = []

    def _split_obs(self, obs: np.ndarray, n_blocks: int):
        """Split flat observation into block_features and global_features."""
        block_flat = obs[:n_blocks * K_BLOCK]
        block_feat = block_flat.reshape(n_blocks, K_BLOCK)
        global_feat = obs[n_blocks * K_BLOCK: n_blocks * K_BLOCK + K_GLOBAL]
        return block_feat, global_feat

    def _select_action(self, policy: str, obs: np.ndarray, n_blocks: int,
                       mask: Optional[np.ndarray] = None) -> int:
        """Select action according to behavioral policy."""
        if mask is None:
            mask = np.ones(n_blocks, dtype=bool)
        valid = np.where(mask)[0]
        if len(valid) == 0:
            return 0

        if policy == 'greedy':
            block_feat, _ = self._split_obs(obs, n_blocks)
            # Heuristic: pick block with largest slope gap (feature index 0 assumed)
            scores = block_feat[valid, 0]
            return int(valid[np.argmax(scores)])
        # default: random
        return int(np.random.choice(valid))

    def collect(self, env: gym.Env, n_episodes: int = 10,
                policy: str = 'random', n_blocks: Optional[int] = None):
        """Run episodes and store transitions."""
        for ep in range(n_episodes):
            obs, info = env.reset()
            if n_blocks is None:
                # infer from observation space
                obs_dim = obs.shape[0]
                n_blocks = (obs_dim - K_GLOBAL) // K_BLOCK
            done = False
            while not done:
                mask = None
                if hasattr(env, 'action_masks'):
                    mask = env.action_masks()
                action = self._select_action(policy, obs, n_blocks, mask)
                next_obs, reward, terminated, truncated, info = env.step(action)
                bf, gf = self._split_obs(obs, n_blocks)
                nbf, ngf = self._split_obs(next_obs, n_blocks)
                self.block_features.append(bf)
                self.global_features.append(gf)
                self.actions.append(action)
                self.rewards.append(reward)
                self.next_block_features.append(nbf)
                self.next_global_features.append(ngf)
                obs = next_obs
                done = terminated or truncated
            logger.info("TrajectoryCollector: episode %d/%d done, %d transitions total",
                        ep + 1, n_episodes, len(self.actions))

    @property
    def size(self) -> int:
        return len(self.actions)

    def as_arrays(self):
        """Return structured numpy arrays."""
        return {
            'block_features': np.array(self.block_features, dtype=np.float32),
            'global_features': np.array(self.global_features, dtype=np.float32),
            'actions': np.array(self.actions, dtype=np.int64),
            'rewards': np.array(self.rewards, dtype=np.float32),
            'next_block_features': np.array(self.next_block_features, dtype=np.float32),
            'next_global_features': np.array(self.next_global_features, dtype=np.float32),
        }

    def save(self, path: str):
        """Save trajectory data to .npz file."""
        np.savez_compressed(path, **self.as_arrays())
        logger.info("Saved %d transitions to %s", self.size, path)

    def load(self, path: str):
        """Load trajectory data from .npz file."""
        data = np.load(path)
        self.block_features = list(data['block_features'])
        self.global_features = list(data['global_features'])
        self.actions = list(data['actions'])
        self.rewards = list(data['rewards'])
        self.next_block_features = list(data['next_block_features'])
        self.next_global_features = list(data['next_global_features'])
        logger.info("Loaded %d transitions from %s", self.size, path)


# ---------------------------------------------------------------------------
# TransitionModelTrainer
# ---------------------------------------------------------------------------
class TransitionModelTrainer:
    """Train TransitionModel on collected trajectory data.

    Loss = MSE(block_delta) + MSE(global_delta) + 0.1 * MSE(reward)
    Adam optimizer, lr=1e-3, weight_decay=1e-5, 50 epochs.
    """

    def __init__(self, model: TransitionModel, lr: float = 1e-3,
                 weight_decay: float = 1e-5, epochs: int = 50,
                 val_split: float = 0.1, device: str = 'cpu',
                 patience: int = 8, min_delta: float = 1e-4,
                 restore_best: bool = True):
        self.model = model.to(device)
        self.device = device
        self.epochs = epochs
        self.val_split = val_split
        self.patience = patience
        self.min_delta = min_delta
        self.restore_best = restore_best
        self.optimizer = torch.optim.Adam(model.parameters(), lr=lr,
                                          weight_decay=weight_decay)
        self.history: dict = {
            'train_loss': [], 'val_loss': [], 'cosine_sim': [],
            'best_epoch': None, 'best_val_loss': None,
            'early_stopped': False, 'stop_reason': None,
        }

    def _prepare_data(self, data: dict):
        """Convert numpy arrays to tensors and split train/val."""
        n = len(data['actions'])
        idx = np.random.permutation(n)
        split = max(1, int(n * self.val_split))
        val_idx, train_idx = idx[:split], idx[split:]

        def to_tensors(indices):
            bf = torch.tensor(data['block_features'][indices], device=self.device)
            gf = torch.tensor(data['global_features'][indices], device=self.device)
            a = torch.tensor(data['actions'][indices], device=self.device)
            r = torch.tensor(data['rewards'][indices], device=self.device).unsqueeze(-1)
            nbf = torch.tensor(data['next_block_features'][indices], device=self.device)
            ngf = torch.tensor(data['next_global_features'][indices], device=self.device)
            return bf, gf, a, r, nbf, ngf

        return to_tensors(train_idx), to_tensors(val_idx)

    def _compute_loss(self, bf, gf, a, r, nbf, ngf):
        """Compute combined loss."""
        pred_nbf, pred_ngf, pred_r = self.model(bf, gf, a)
        # True deltas
        true_b_delta = nbf - bf
        pred_b_delta = pred_nbf - bf
        true_g_delta = ngf - gf
        pred_g_delta = pred_ngf - gf

        loss_block = nn.functional.mse_loss(pred_b_delta, true_b_delta)
        loss_global = nn.functional.mse_loss(pred_g_delta, true_g_delta)
        loss_reward = nn.functional.mse_loss(pred_r, r)
        return loss_block + loss_global + 0.1 * loss_reward, pred_nbf, pred_ngf

    def _cosine_similarity(self, pred: torch.Tensor, target: torch.Tensor) -> float:
        """Mean cosine similarity between predicted and true next states."""
        pred_flat = pred.reshape(pred.shape[0], -1)
        tgt_flat = target.reshape(target.shape[0], -1)
        cos = nn.functional.cosine_similarity(pred_flat, tgt_flat, dim=-1)
        return cos.mean().item()

    def train(self, data: dict) -> dict:
        """Train the model. Returns training history."""
        train_data, val_data = self._prepare_data(data)
        best_val_loss = float('inf')
        best_epoch = -1
        best_state_dict = None
        wait = 0

        for epoch in range(self.epochs):
            # Train step
            self.model.train()
            self.optimizer.zero_grad()
            loss, _, _ = self._compute_loss(*train_data)
            loss.backward()
            self.optimizer.step()
            self.history['train_loss'].append(loss.item())

            # Validation step
            self.model.eval()
            with torch.no_grad():
                v_loss, v_pred_nbf, v_pred_ngf = self._compute_loss(*val_data)
                cos_block = self._cosine_similarity(v_pred_nbf, val_data[4])
                cos_global = self._cosine_similarity(
                    v_pred_ngf.unsqueeze(1), val_data[5].unsqueeze(1))
            val_loss = v_loss.item()
            self.history['val_loss'].append(val_loss)
            self.history['cosine_sim'].append((cos_block + cos_global) / 2)

            improved = val_loss < (best_val_loss - self.min_delta)
            if improved:
                best_val_loss = val_loss
                best_epoch = epoch + 1
                best_state_dict = {
                    k: v.detach().cpu().clone()
                    for k, v in self.model.state_dict().items()
                }
                wait = 0
            else:
                wait += 1

            if (epoch + 1) % 10 == 0 or epoch == 0:
                logger.info(
                    "Epoch %d/%d  train_loss=%.5f  val_loss=%.5f  cos_sim=%.4f",
                    epoch + 1, self.epochs,
                    self.history['train_loss'][-1],
                    self.history['val_loss'][-1],
                    self.history['cosine_sim'][-1],
                )

            if self.patience > 0 and wait >= self.patience:
                self.history['early_stopped'] = True
                self.history['stop_reason'] = f'no_improvement_{self.patience}'
                logger.info(
                    "Early stopping at epoch %d/%d (best epoch=%d, best val_loss=%.5f)",
                    epoch + 1, self.epochs, best_epoch, best_val_loss,
                )
                break

        self.history['best_epoch'] = best_epoch
        self.history['best_val_loss'] = round(float(best_val_loss), 6) if best_epoch > 0 else None
        if self.restore_best and best_state_dict is not None:
            self.model.load_state_dict(best_state_dict)
        return self.history

    def save(self, path: str):
        """Save model weights."""
        torch.save(self.model.state_dict(), path)
        logger.info("Model saved to %s", path)

    def load(self, path: str):
        """Load model weights."""
        self.model.load_state_dict(torch.load(path, map_location=self.device))
        logger.info("Model loaded from %s", path)


# ---------------------------------------------------------------------------
# LearnedBlockEnv — Gymnasium wrapper around TransitionModel
# ---------------------------------------------------------------------------
class LearnedBlockEnv(gym.Env):
    """Gymnasium env that uses a learned TransitionModel instead of the real env.

    Observation: block_features (n_blocks * K_BLOCK) + global_features (K_GLOBAL) flattened.
    Action: Discrete(n_blocks) — select block index.
    Supports action masking via action_masks() for MaskablePPO compatibility.
    """

    metadata = {"render_modes": []}

    def __init__(self, model: TransitionModel, trajectory_data: dict,
                 max_steps: int = 200, noise_std: float = 0.01,
                 reward_scale: float = 1.0, reward_clip: float = 10.0,
                 state_reset_interval: int = 0):
        """
        Args:
            model: trained TransitionModel
            trajectory_data: dict with block_features, global_features, etc.
            max_steps: episode length
            noise_std: Gaussian noise on initial state
            reward_scale: multiply predicted reward (for calibration)
            reward_clip: clip reward to [-clip, +clip]
            state_reset_interval: if >0, reset state from real data every N steps
                                  to prevent drift accumulation
        """
        super().__init__()
        self.model = model
        self.model.eval()
        self.n_blocks = model.n_blocks
        self.max_steps = max_steps
        self.noise_std = noise_std
        self.reward_scale = reward_scale
        self.reward_clip = reward_clip
        self.state_reset_interval = state_reset_interval

        # Store ALL states from trajectory (not just initial) for diverse sampling
        self._all_block_feats = trajectory_data['block_features']
        self._all_global_feats = trajectory_data['global_features']
        # Also keep next-states for mid-episode anchoring
        self._all_next_block_feats = trajectory_data.get('next_block_features',
                                                          self._all_block_feats)
        self._all_next_global_feats = trajectory_data.get('next_global_features',
                                                           self._all_global_feats)

        obs_dim = self.n_blocks * K_BLOCK + K_GLOBAL
        self.observation_space = spaces.Box(
            low=-np.inf, high=np.inf, shape=(obs_dim,), dtype=np.float32)
        self.action_space = spaces.Discrete(self.n_blocks)

        # Runtime state
        self.block_features: Optional[np.ndarray] = None  # (n_blocks, K_BLOCK)
        self.global_features: Optional[np.ndarray] = None  # (K_GLOBAL,)
        self._step_count = 0
        self._mask: Optional[np.ndarray] = None

    def _build_obs(self) -> np.ndarray:
        return np.concatenate([
            self.block_features.flatten(),
            self.global_features,
        ]).astype(np.float32)

    def _compute_mask(self) -> np.ndarray:
        """Mask blocks with no farmland or no forest (features assumed at indices 1, 2)."""
        mask = np.ones(self.n_blocks, dtype=bool)
        for i in range(self.n_blocks):
            farmland_area = self.block_features[i, 1]
            forest_area = self.block_features[i, 2]
            if farmland_area <= 0 and forest_area <= 0:
                mask[i] = False
        self._mask = mask
        return mask

    def action_masks(self) -> np.ndarray:
        """Return boolean mask for valid actions (MaskablePPO compatible)."""
        if self._mask is None:
            return self._compute_mask()
        return self._mask

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        idx = self.np_random.integers(0, len(self._all_block_feats))
        self.block_features = self._all_block_feats[idx].copy()
        self.global_features = self._all_global_feats[idx].copy()
        if self.noise_std > 0:
            self.block_features += self.np_random.normal(
                0, self.noise_std, self.block_features.shape).astype(np.float32)
            self.global_features += self.np_random.normal(
                0, self.noise_std, self.global_features.shape).astype(np.float32)
        self._step_count = 0
        self._anchor_idx = idx
        self._compute_mask()
        return self._build_obs(), {}

    def step(self, action: int):
        """Execute one step using the learned transition model."""
        # Periodic state anchoring: blend predicted state with real data
        if (self.state_reset_interval > 0
                and self._step_count > 0
                and self._step_count % self.state_reset_interval == 0):
            anchor_idx = self.np_random.integers(0, len(self._all_block_feats))
            blend = 0.3  # 30% real, 70% predicted
            self.block_features = (
                (1 - blend) * self.block_features
                + blend * self._all_block_feats[anchor_idx]
            ).astype(np.float32)
            self.global_features = (
                (1 - blend) * self.global_features
                + blend * self._all_global_feats[anchor_idx]
            ).astype(np.float32)

        bf_t = torch.tensor(self.block_features, dtype=torch.float32).unsqueeze(0)
        gf_t = torch.tensor(self.global_features, dtype=torch.float32).unsqueeze(0)
        a_t = torch.tensor([action], dtype=torch.long)

        with torch.no_grad():
            next_bf, next_gf, reward_t = self.model(bf_t, gf_t, a_t)

        self.block_features = next_bf.squeeze(0).numpy()
        self.global_features = next_gf.squeeze(0).numpy()
        raw_reward = float(reward_t.item())
        reward = np.clip(raw_reward * self.reward_scale, -self.reward_clip, self.reward_clip)

        self._step_count += 1
        self._compute_mask()
        terminated = False
        truncated = self._step_count >= self.max_steps
        return self._build_obs(), reward, terminated, truncated, {
            'raw_reward': raw_reward,
        }


# ---------------------------------------------------------------------------
# EnsembleTransitionModel — train N models, use disagreement as uncertainty
# ---------------------------------------------------------------------------

class EnsembleTransitionModel:
    """Ensemble of TransitionModels for uncertainty-aware dream training.

    Trains N independently initialized models on the same data.
    At inference, uses mean prediction and reward-variance penalty
    to discourage the policy from exploiting any single model's errors.
    """

    def __init__(self, n_blocks: int, n_models: int = 5):
        self.n_blocks = n_blocks
        self.n_models = n_models
        self.models = [TransitionModel(n_blocks) for _ in range(n_models)]

    def train_all(self, data: dict, epochs: int = 30, lr: float = 1e-3,
                  patience: int = 8, min_delta: float = 1e-4):
        """Train each model independently with different random splits."""
        histories = []
        for i, model in enumerate(self.models):
            np.random.seed(i * 1000)
            trainer = TransitionModelTrainer(
                model, lr=lr, epochs=epochs,
                patience=patience, min_delta=min_delta,
            )
            h = trainer.train(data)
            histories.append(h)
            logger.info(
                "Ensemble member %d: cos_sim=%.6f best_epoch=%s early_stopped=%s",
                i, h['cosine_sim'][-1], h.get('best_epoch'), h.get('early_stopped'),
            )
        return histories

    def predict(self, block_features, global_features, action):
        """Predict with all models, return mean + variance."""
        bf = torch.tensor(block_features, dtype=torch.float32).unsqueeze(0)
        gf = torch.tensor(global_features, dtype=torch.float32).unsqueeze(0)
        a = torch.tensor([action], dtype=torch.long)

        all_nbf, all_ngf, all_r = [], [], []
        with torch.no_grad():
            for m in self.models:
                m.eval()
                nbf, ngf, r = m(bf, gf, a)
                all_nbf.append(nbf)
                all_ngf.append(ngf)
                all_r.append(r)

        nbf_stack = torch.stack(all_nbf)
        ngf_stack = torch.stack(all_ngf)
        r_stack = torch.stack(all_r)

        mean_nbf = nbf_stack.mean(dim=0).squeeze(0).numpy()
        mean_ngf = ngf_stack.mean(dim=0).squeeze(0).numpy()
        mean_r = float(r_stack.mean().item())
        reward_std = float(r_stack.std().item())

        return mean_nbf, mean_ngf, mean_r, reward_std

    def save(self, path: str):
        for i, m in enumerate(self.models):
            torch.save(m.state_dict(), f"{path}_member{i}.pt")

    def load(self, path: str):
        for i, m in enumerate(self.models):
            m.load_state_dict(torch.load(f"{path}_member{i}.pt",
                                         map_location='cpu', weights_only=True))


class EnsembleBlockEnv(gym.Env):
    """LearnedBlockEnv powered by an ensemble, with disagreement penalty.

    reward_out = mean_reward - penalty_weight * reward_std
    This discourages the policy from choosing actions where models disagree.
    """

    metadata = {"render_modes": []}

    def __init__(self, ensemble: EnsembleTransitionModel, trajectory_data: dict,
                 max_steps: int = 100, noise_std: float = 0.02,
                 reward_scale: float = 1.0, reward_clip: float = 10.0,
                 penalty_weight: float = 1.0,
                 disagreement_threshold: float = 0.0,
                 min_steps: int = 20):
        super().__init__()
        self.ensemble = ensemble
        self.n_blocks = ensemble.n_blocks
        self.max_steps = max_steps
        self.noise_std = noise_std
        self.reward_scale = reward_scale
        self.reward_clip = reward_clip
        self.penalty_weight = penalty_weight
        self.disagreement_threshold = disagreement_threshold
        self.min_steps = min_steps

        self._all_block_feats = trajectory_data['block_features']
        self._all_global_feats = trajectory_data['global_features']

        obs_dim = self.n_blocks * K_BLOCK + K_GLOBAL
        self.observation_space = spaces.Box(
            low=-np.inf, high=np.inf, shape=(obs_dim,), dtype=np.float32)
        self.action_space = spaces.Discrete(self.n_blocks)

        self.block_features = None
        self.global_features = None
        self._step_count = 0
        self._episode_lengths: list[int] = []
        self._n_early_truncated = 0

    def _build_obs(self):
        return np.concatenate([
            self.block_features.flatten(), self.global_features
        ]).astype(np.float32)

    def _compute_mask(self):
        mask = np.ones(self.n_blocks, dtype=bool)
        for i in range(self.n_blocks):
            if self.block_features[i, 1] <= 0 and self.block_features[i, 2] <= 0:
                mask[i] = False
        self._mask = mask
        return mask

    def action_masks(self):
        if not hasattr(self, '_mask') or self._mask is None:
            return self._compute_mask()
        return self._mask

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        idx = self.np_random.integers(0, len(self._all_block_feats))
        self.block_features = self._all_block_feats[idx].copy()
        self.global_features = self._all_global_feats[idx].copy()
        if self.noise_std > 0:
            self.block_features += self.np_random.normal(
                0, self.noise_std, self.block_features.shape).astype(np.float32)
            self.global_features += self.np_random.normal(
                0, self.noise_std, self.global_features.shape).astype(np.float32)
        self._step_count = 0
        self._compute_mask()
        return self._build_obs(), {}

    def step(self, action: int):
        mean_nbf, mean_ngf, mean_r, r_std = self.ensemble.predict(
            self.block_features, self.global_features, action)

        self.block_features = mean_nbf
        self.global_features = mean_ngf

        penalized = mean_r - self.penalty_weight * r_std
        reward = np.clip(penalized * self.reward_scale,
                         -self.reward_clip, self.reward_clip)

        self._step_count += 1
        self._compute_mask()
        terminated = False
        truncated = self._step_count >= self.max_steps
        early_truncated = False
        if (not truncated
                and self.disagreement_threshold > 0
                and self._step_count >= self.min_steps
                and r_std > self.disagreement_threshold):
            truncated = True
            early_truncated = True
        if truncated or terminated:
            self._episode_lengths.append(self._step_count)
            if early_truncated:
                self._n_early_truncated += 1
        return self._build_obs(), reward, terminated, truncated, {
            'mean_reward': mean_r, 'reward_std': r_std,
            'early_truncated': early_truncated,
            'truncation_step': self._step_count if early_truncated else None,
        }
