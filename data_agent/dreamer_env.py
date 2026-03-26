"""Dreamer-style DRL environment with World Model integration.

Wraps LandUseOptEnv to add:
- ParcelEmbeddingMapper: 宗地级 AlphaEarth 64D 嵌入 (zonal mean)
- ActionToScenarioEncoder: 动作历史 → 世界模型情景向量
- DreamerEnv: look-ahead 辅助奖励 (每 K 步调用世界模型预测)
- run_dreamer_optimization: 端到端 Dreamer 优化入口
"""

import logging
import numpy as np
import geopandas as gpd
from typing import Optional, Dict, List, Any

logger = logging.getLogger(__name__)


# ---- World model access helpers (mockable at module level) ----

def _wm_extract_embeddings(bbox: list, year: int):
    """Proxy to world_model.extract_embeddings (deferred import for testability)."""
    from .world_model import extract_embeddings
    return extract_embeddings(bbox, year)


def _wm_predict_sequence(bbox: list, scenario: str, start_year: int, n_years: int):
    """Proxy to world_model.predict_sequence (deferred import for testability)."""
    from .world_model import predict_sequence
    return predict_sequence(bbox=bbox, scenario=scenario,
                            start_year=start_year, n_years=n_years)


# ---- ParcelEmbeddingMapper ----
class ParcelEmbeddingMapper:
    """Map GeoDataFrame parcels to AlphaEarth 64D embeddings via zonal mean.

    Uses the same zonal aggregation pattern as
    causal_inference._extract_geofm_confounders(), adapted for per-parcel
    centroid sampling.
    """

    def __init__(self, gdf: gpd.GeoDataFrame, bbox: list, year: int = 2023):
        """
        Args:
            gdf: parcels GeoDataFrame with geometry column
            bbox: [lon_min, lat_min, lon_max, lat_max]
            year: year for embedding extraction
        """
        self.gdf = gdf
        self.bbox = bbox
        self.year = year
        self.embeddings: Optional[np.ndarray] = None  # shape: (n_parcels, 64)
        self._extract()

    def _extract(self):
        """Extract embeddings, with graceful fallback to zeros."""
        n = len(self.gdf)
        try:
            grid_emb = _wm_extract_embeddings(self.bbox, self.year)
            if grid_emb is not None and hasattr(grid_emb, 'shape'):
                # Zonal mean: for each parcel, sample nearest grid cell via centroid
                self.embeddings = self._zonal_mean(grid_emb)
                return
        except Exception as e:
            logger.warning("Embedding extraction failed, using zeros: %s", e)
        self.embeddings = np.zeros((n, 64), dtype=np.float32)

    def _zonal_mean(self, grid_emb: np.ndarray) -> np.ndarray:
        """Compute zonal mean embeddings per parcel using centroids.

        grid_emb 可能是 [H, W, 64] (world_model.extract_embeddings 返回格式)
        或 [64, H, W]。统一处理后按 centroid 坐标采样最近网格点。
        """
        n = len(self.gdf)
        emb = np.zeros((n, 64), dtype=np.float32)
        if grid_emb is None or len(grid_emb.shape) < 3:
            return emb

        # Normalize to (64, H, W) layout
        if grid_emb.shape[0] == 64:
            H, W = grid_emb.shape[1], grid_emb.shape[2]
        elif grid_emb.shape[-1] == 64:
            H, W = grid_emb.shape[0], grid_emb.shape[1]
            grid_emb = grid_emb.transpose(2, 0, 1)  # -> (64, H, W)
        else:
            return emb

        lon_min, lat_min, lon_max, lat_max = self.bbox
        lon_range = lon_max - lon_min
        lat_range = lat_max - lat_min
        if lon_range < 1e-12 or lat_range < 1e-12:
            return emb

        for i, geom in enumerate(self.gdf.geometry):
            cx, cy = geom.centroid.x, geom.centroid.y
            # Map centroid to grid indices
            px = int((cx - lon_min) / lon_range * (W - 1))
            py = int((lat_max - cy) / lat_range * (H - 1))
            px = max(0, min(px, W - 1))
            py = max(0, min(py, H - 1))
            emb[i] = grid_emb[:, py, px]
        return emb

    def get_embedding(self, parcel_idx: int) -> np.ndarray:
        """Return 64D embedding for a parcel by index."""
        if self.embeddings is None:
            return np.zeros(64, dtype=np.float32)
        return self.embeddings[parcel_idx]

    def get_coherence(self, parcel_idx: int, neighbor_indices: List[int]) -> float:
        """Mean cosine similarity between a parcel and its neighbors."""
        if self.embeddings is None or len(neighbor_indices) == 0:
            return 0.0
        e = self.embeddings[parcel_idx]
        ne = self.embeddings[neighbor_indices]
        norm_e = np.linalg.norm(e)
        if norm_e < 1e-8:
            return 0.0
        cos_sims = ne @ e / (np.linalg.norm(ne, axis=1) * norm_e + 1e-8)
        return float(np.mean(cos_sims))


# ---- ActionToScenarioEncoder ----
class ActionToScenarioEncoder:
    """Convert DRL action history to world model scenario vector (16D).

    根据耕地→林地 / 林地→耕地的累计转换比例，映射到世界模型的
    5 种情景权重 (urban_sprawl, ecological_restoration,
    agricultural_intensification, climate_adaptation, baseline)。
    """

    SCENARIO_DIM = 16

    def __init__(self):
        self.reset()

    def reset(self):
        self.farmland_to_forest = 0
        self.forest_to_farmland = 0

    def record_action(self, from_type: int, to_type: int):
        """Record a land-use conversion action.

        Uses DRL constants: FARMLAND=1, FOREST=2.
        """
        if from_type == 1 and to_type == 2:  # FARMLAND -> FOREST
            self.farmland_to_forest += 1
        elif from_type == 2 and to_type == 1:  # FOREST -> FARMLAND
            self.forest_to_farmland += 1

    def encode(self) -> np.ndarray:
        """Return 16D scenario vector based on cumulative actions."""
        vec = np.zeros(self.SCENARIO_DIM, dtype=np.float32)
        total = self.farmland_to_forest + self.forest_to_farmland
        if total == 0:
            vec[4] = 1.0  # baseline
            return vec

        f2f_ratio = self.farmland_to_forest / total

        if f2f_ratio > 0.7:
            # Net reforestation -> ecological_restoration (id=1)
            vec[1] = f2f_ratio
            vec[4] = 1.0 - f2f_ratio  # baseline residual
        elif f2f_ratio < 0.3:
            # Net deforestation -> agricultural_intensification (id=2)
            vec[2] = 1.0 - f2f_ratio
            vec[4] = f2f_ratio
        else:
            # Balanced -> blend of ecological + agricultural
            vec[1] = f2f_ratio
            vec[2] = 1.0 - f2f_ratio
            vec[4] = 0.2  # baseline anchor

        # L1 normalize to sum to ~1
        total_weight = vec.sum()
        if total_weight > 0:
            vec /= total_weight
        return vec

    @property
    def net_conversions(self) -> int:
        return self.farmland_to_forest - self.forest_to_farmland


# ---- DreamerEnv ----
class DreamerEnv:
    """Dreamer-style wrapper around LandUseOptEnv with world model look-ahead.

    Adds:
    - Embedding-enriched observations (coherence features)
    - Auxiliary reward from world model predictions every K steps
    - Graceful degradation when world model unavailable
    """

    def __init__(
        self,
        base_env,  # LandUseOptEnv instance
        bbox: Optional[list] = None,
        year: int = 2023,
        look_ahead_years: int = 3,
        look_ahead_interval: int = 10,
        aux_reward_weight: float = 0.1,
        enable_world_model: bool = True,
    ):
        self.base_env = base_env
        self.bbox = bbox or self._extract_bbox()
        self.year = year
        self.look_ahead_years = look_ahead_years
        self.look_ahead_interval = look_ahead_interval
        self.aux_reward_weight = aux_reward_weight
        self.enable_world_model = enable_world_model

        # World model components
        self.embedding_mapper: Optional[ParcelEmbeddingMapper] = None
        self.scenario_encoder = ActionToScenarioEncoder()
        self.world_model_available = False
        self._step_counter = 0
        self._cached_aux_reward = 0.0
        self._wm_predict = None

        if enable_world_model:
            self._init_world_model()

    def _extract_bbox(self) -> list:
        """Extract bounding box from the base env's GeoDataFrame."""
        try:
            bounds = self.base_env.gdf.total_bounds  # [minx, miny, maxx, maxy]
            return list(bounds)
        except Exception:
            return [0, 0, 1, 1]

    def _init_world_model(self):
        """Initialize world model components with graceful fallback."""
        try:
            self.embedding_mapper = ParcelEmbeddingMapper(
                self.base_env.gdf, self.bbox, self.year
            )
            # Verify world model proxy is callable
            self._wm_predict = _wm_predict_sequence
            self.world_model_available = True
            logger.info(
                "DreamerEnv: world model initialized, %d parcels embedded",
                len(self.base_env.gdf),
            )
        except Exception as e:
            logger.warning(
                "DreamerEnv: world model unavailable, using base env only: %s", e
            )
            self.world_model_available = False

    def reset(self, **kwargs):
        """Reset environment and world model state."""
        obs, info = self.base_env.reset(**kwargs)
        self.scenario_encoder.reset()
        self._step_counter = 0
        self._cached_aux_reward = 0.0
        return obs, info

    def step(self, action):
        """Execute action with optional world model auxiliary reward."""
        # Track the conversion type before stepping
        parcel_idx = action
        old_type = (
            self.base_env.land_use[self.base_env.swappable_indices[parcel_idx]]
            if hasattr(self.base_env, 'land_use')
            else 0
        )

        # Execute base environment step
        obs, reward, terminated, truncated, info = self.base_env.step(action)

        new_type = (
            self.base_env.land_use[self.base_env.swappable_indices[parcel_idx]]
            if hasattr(self.base_env, 'land_use')
            else 0
        )
        self.scenario_encoder.record_action(old_type, new_type)
        self._step_counter += 1

        # Compute auxiliary reward every K steps
        aux_reward = 0.0
        if (
            self.world_model_available
            and self._step_counter % self.look_ahead_interval == 0
        ):
            aux_reward = self._compute_auxiliary_reward()
            self._cached_aux_reward = aux_reward

        # Combine rewards
        total_reward = reward + self.aux_reward_weight * self._cached_aux_reward
        info['base_reward'] = reward
        info['aux_reward'] = self._cached_aux_reward
        info['scenario_vector'] = self.scenario_encoder.encode().tolist()
        info['net_conversions'] = self.scenario_encoder.net_conversions

        return obs, total_reward, terminated, truncated, info

    def _compute_auxiliary_reward(self) -> float:
        """Run world model look-ahead and compute reward signal.

        使用当前 DRL 动作历史编码的情景向量，通过世界模型预测未来
        若干年的 LULC 变化，将预测结果转化为辅助奖励信号。
        """
        try:
            scenario_vec = self.scenario_encoder.encode()

            # Find dominant scenario name for the world model API
            scenario_names = [
                'urban_sprawl', 'ecological_restoration',
                'agricultural_intensification', 'climate_adaptation', 'baseline',
            ]
            dominant_idx = int(np.argmax(scenario_vec[:5]))
            scenario_name = scenario_names[dominant_idx]

            # Run world model prediction
            result = self._wm_predict(
                bbox=self.bbox,
                scenario=scenario_name,
                start_year=self.year,
                n_years=self.look_ahead_years,
            )

            if result is None or not isinstance(result, dict):
                return 0.0

            # Extract predicted improvement from area_distribution
            area_dist = result.get('area_distribution', {})
            if len(area_dist) < 2:
                return 0.0

            years_sorted = sorted(area_dist.keys())
            first_key = years_sorted[0]
            last_key = years_sorted[-1]
            first_dist = area_dist[first_key]
            last_dist = area_dist[last_key]

            # Extract pixel counts for forest (树木) and cropland (耕地)
            forest_first = first_dist.get('树木', {}).get('percentage', 0)
            forest_last = last_dist.get('树木', {}).get('percentage', 0)
            crop_first = first_dist.get('耕地', {}).get('percentage', 0)
            crop_last = last_dist.get('耕地', {}).get('percentage', 0)

            forest_change = forest_last - forest_first
            farmland_change = crop_last - crop_first

            # Reward aligned with DRL action direction
            aux = 0.0
            if self.scenario_encoder.farmland_to_forest > self.scenario_encoder.forest_to_farmland:
                # DRL is doing reforestation — reward if world model predicts forest increase
                aux = forest_change * 10.0
            else:
                # DRL is doing agricultural expansion — reward if world model predicts stable farmland
                aux = -abs(farmland_change) * 5.0

            return float(np.clip(aux, -5.0, 5.0))

        except Exception as e:
            logger.debug("Auxiliary reward computation failed: %s", e)
            return 0.0

    # Delegate gym.Env interface to base_env
    @property
    def observation_space(self):
        return self.base_env.observation_space

    @property
    def action_space(self):
        return self.base_env.action_space

    def action_masks(self):
        return self.base_env.action_masks() if hasattr(self.base_env, 'action_masks') else None

    def render(self, *args, **kwargs):
        return self.base_env.render(*args, **kwargs)

    def close(self):
        return self.base_env.close()


# ---- Top-level entry point ----

def run_dreamer_optimization(
    shp_path: str,
    bbox: Optional[list] = None,
    year: int = 2023,
    max_steps: int = 200,
    look_ahead_years: int = 3,
    aux_reward_weight: float = 0.1,
    scenario_id: str = "",
) -> Dict[str, Any]:
    """Run DRL optimization with Dreamer-style world model integration.

    Args:
        shp_path: path to Shapefile / GeoJSON with land-use parcels
        bbox: optional [minx, miny, maxx, maxy] override for embedding extraction
        year: base year for embeddings (default 2023)
        max_steps: max steps per episode
        look_ahead_years: how many years world model predicts ahead
        aux_reward_weight: weight for auxiliary reward term
        scenario_id: optional DRL scenario template id

    Returns:
        dict with optimization results including world model metrics.
    """
    import json
    import os
    import torch
    from .drl_engine import LandUseOptEnv, SCENARIOS as DRL_SCENARIOS, DRLScenario

    # Build scenario
    scenario = DRL_SCENARIOS.get(scenario_id) if scenario_id else None

    # Create base environment
    base_env = LandUseOptEnv(
        shp_path=shp_path,
        max_conversions=max_steps,
        scenario=scenario,
    )

    # Wrap with DreamerEnv
    env = DreamerEnv(
        base_env=base_env,
        bbox=bbox,
        year=year,
        look_ahead_years=look_ahead_years,
        aux_reward_weight=aux_reward_weight,
    )

    # Load pre-trained DRL model (same approach as analysis_tools.drl_model)
    from sb3_contrib import MaskablePPO
    from stable_baselines3.common.monitor import Monitor
    weights_path = os.path.join(os.path.dirname(__file__), 'scorer_weights_v7.pt')

    if not os.path.exists(weights_path):
        return {
            'status': 'error',
            'error': f'DRL model weights not found: {weights_path}',
        }

    checkpoint = torch.load(weights_path, map_location='cpu', weights_only=False)

    # Import ParcelScoringPolicy from analysis_tools
    from .toolsets.analysis_tools import ParcelScoringPolicy

    env_mon = Monitor(base_env)
    model = MaskablePPO(
        ParcelScoringPolicy,
        env_mon,
        policy_kwargs=dict(
            k_parcel=checkpoint.get('k_parcel', 6),
            k_global=checkpoint.get('k_global', 8),
            scorer_hiddens=checkpoint.get('scorer_hiddens', [128, 64]),
            value_hiddens=checkpoint.get('value_hiddens', [128, 64]),
        ),
        device='cpu',
    )
    model.policy.scorer_net.load_state_dict(checkpoint['scorer_net'])
    model.policy.value_net.load_state_dict(checkpoint['value_net'])
    model.policy.eval()

    # Run evaluation episode through DreamerEnv wrapper
    obs, _ = env.reset()
    total_reward = 0.0
    episode_info = []

    for step in range(max_steps):
        masks = env.action_masks()
        if masks is None or not np.any(masks):
            break
        action, _ = model.predict(obs, deterministic=True, action_masks=masks)
        obs, reward, terminated, truncated, info = env.step(int(action))
        total_reward += reward
        episode_info.append(info)
        if terminated or truncated:
            break

    return {
        'status': 'ok',
        'total_reward': total_reward,
        'steps': len(episode_info),
        'world_model_available': env.world_model_available,
        'final_scenario_vector': env.scenario_encoder.encode().tolist(),
        'net_conversions': env.scenario_encoder.net_conversions,
        'aux_rewards': [info.get('aux_reward', 0) for info in episode_info],
    }
