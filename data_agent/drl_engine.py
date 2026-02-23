"""
Custom Gymnasium environment for land use optimization (v7).

v7 changes vs v6:
  - Drastically reduces COUNT_PENALTY_WEIGHT from 100,000 to 500.
    v6's penalty was catastrophically large for 200-step episodes:
    random exploration caused deviation ~90 parcels, penalty ~17.8/step,
    total ~-1,243 per episode, drowning all gradient signal.
    With weight=500, random exploration penalty is ~6.3 total (manageable),
    while single-direction becomes unprofitable at ~6 removals.
  - Increases PAIR_BONUS from 0.5 to 1.0, making paired strategy
    clearly dominant: ~1.4 per pair (0.7/step) vs ~0.2/step single.
  - Keeps no early termination (full 200 steps) from v6.
  - All other features preserved: free flip, action masking,
    incremental metrics, no-undo mechanism.
"""

import numpy as np
import geopandas as gpd
import gymnasium as gym
from gymnasium import spaces


# Land use type constants
OTHER = 0
FARMLAND = 1
FOREST = 2

FARMLAND_TYPES = {'旱地', '水田'}
FOREST_TYPES = {'果园', '有林地'}

# Per-parcel feature count
K_PARCEL = 6
# Global feature count
K_GLOBAL = 8

# Reward weights
SLOPE_REWARD_WEIGHT = 1000.0
CONT_REWARD_WEIGHT = 500.0
COUNT_PENALTY_WEIGHT = 500.0     # v7: drastically reduced from 100,000
PAIR_BONUS = 1.0                 # v7: increased from 0.5


class LandUseOptEnv(gym.Env):
    """
    Land use optimization environment (v7).

    Each step, the agent selects any swappable parcel to flip:
      - If farmland -> converts to forest
      - If forest  -> converts to farmland

    Key v7 design: reduced penalty + stronger pair bonus + no early termination.
    v6 failed because COUNT_PENALTY_WEIGHT=100,000 created catastrophic
    negative rewards during random exploration, preventing any learning.
    v7 reduces it to 500 so that:
      - Random exploration total penalty ~6.3 (vs v6's ~1,243)
      - Single-direction becomes unprofitable after ~6 removals
      - Paired strategy yields ~0.7/step, clearly dominating single's ~0.2/step
    """

    metadata = {"render_modes": []}

    def __init__(self, shp_path, max_conversions=200):
        super().__init__()

        # Load shapefile
        print(f"Loading shapefile: {shp_path}")
        self.gdf = gpd.read_file(shp_path)
        self.n_parcels = len(self.gdf)

        # Episode length (each step = one conversion)
        self.max_steps = max_conversions

        # Case-insensitive column handling
        columns_lower = {c.lower(): c for c in self.gdf.columns}
        
        # Extract attributes
        slope_col = columns_lower.get('slope', 'Slope')
        if slope_col not in self.gdf.columns:
             raise KeyError(f"Column 'Slope' not found (tried '{slope_col}'). Available: {list(self.gdf.columns)}")
        self.slopes = self.gdf[slope_col].values.astype(np.float64)
        
        dlmc_col = columns_lower.get('dlmc', 'DLMC')
        if dlmc_col not in self.gdf.columns:
             raise KeyError(f"Column 'DLMC' not found (tried '{dlmc_col}'). Available: {list(self.gdf.columns)}")
        dlmc = self.gdf[dlmc_col].values

        # Classify parcels
        self.initial_types = np.full(self.n_parcels, OTHER, dtype=np.int8)
        for i, t in enumerate(dlmc):
            if t in FARMLAND_TYPES:
                self.initial_types[i] = FARMLAND
            elif t in FOREST_TYPES:
                self.initial_types[i] = FOREST

        # Identify swappable parcels (farmland or forest)
        self.swappable_indices = np.where(
            (self.initial_types == FARMLAND) | (self.initial_types == FOREST)
        )[0]
        self.n_swappable = len(self.swappable_indices)

        # Normalize slopes to [0, 1]
        self.slope_min = float(self.slopes.min())
        self.slope_max = float(self.slopes.max())
        self.slope_range = self.slope_max - self.slope_min + 1e-8
        self.slopes_norm = ((self.slopes - self.slope_min) / self.slope_range).astype(np.float32)

        # Normalize areas to [0, 1]
        shape_area_col = columns_lower.get('shape_area', 'Shape_Area')
        # Some SHPs use AREA
        if shape_area_col not in self.gdf.columns:
             shape_area_col = columns_lower.get('area', 'Shape_Area')
             
        areas = self.gdf[shape_area_col].values.astype(np.float64)
        self.areas = areas
        area_min = float(areas.min())
        area_max = float(areas.max())
        area_range = area_max - area_min + 1e-8
        self.areas_norm = ((areas - area_min) / area_range).astype(np.float32)

        # Build spatial adjacency graph
        print("Building adjacency graph...")
        self._build_adjacency()

        # Total neighbor count per parcel (for normalization)
        self.total_nbr_count = np.array(
            [len(self.adjacency[i]) for i in range(self.n_parcels)], dtype=np.float32
        )

        # Pre-compute static per-parcel features for swappable parcels
        si = self.swappable_indices
        self._static_slopes_norm = self.slopes_norm[si].copy()
        self._static_areas_norm = self.areas_norm[si].copy()

        # Pre-compute neighbor average slope (static)
        self._nbr_avg_slope_norm = np.zeros(self.n_parcels, dtype=np.float32)
        for i in range(self.n_parcels):
            nbrs = self.adjacency[i]
            if len(nbrs) > 0:
                self._nbr_avg_slope_norm[i] = self.slopes_norm[nbrs].mean()
        self._static_nbr_avg_slope = self._nbr_avg_slope_norm[si].copy()

        # Pre-compute initial metrics (used for fast reset)
        self.land_use = self.initial_types.copy()
        self._compute_metrics_full()
        self._cache = {
            'n_farmland': self.n_farmland,
            'n_forest': self.n_forest,
            'total_farmland_slope': self.total_farmland_slope,
            'farmland_nbr_count': self.farmland_nbr_count.copy(),
            'total_farmland_adj': self.total_farmland_adj,
        }

        # Define spaces
        self.action_space = spaces.Discrete(self.n_swappable)
        obs_dim = self.n_swappable * K_PARCEL + K_GLOBAL
        self.observation_space = spaces.Box(
            low=-np.inf, high=np.inf, shape=(obs_dim,), dtype=np.float32
        )

        # Print summary
        init_slope = self._cache['total_farmland_slope'] / self._cache['n_farmland']
        init_cont = self._cache['total_farmland_adj'] / self._cache['n_farmland']
        print(f"Environment initialized (v7 - reduced penalty + pair bonus + no early termination):")
        print(f"  Total parcels: {self.n_parcels}")
        print(f"  Swappable: {self.n_swappable} "
              f"(farmland={self._cache['n_farmland']}, forest={self._cache['n_forest']})")
        print(f"  Initial avg farmland slope: {init_slope:.4f}")
        print(f"  Initial farmland contiguity: {init_cont:.4f}")
        print(f"  Per-parcel features: {K_PARCEL}, Global features: {K_GLOBAL}")
        print(f"  Observation dim: {obs_dim}, Action dim: {self.n_swappable}")
        print(f"  Max steps/episode: {self.max_steps}")
        print(f"  Count penalty: quadratic, weight={COUNT_PENALTY_WEIGHT} (v6: 100,000)")
        print(f"  Pair bonus: {PAIR_BONUS} (v6: 0.5)")
        print(f"  Early termination: DISABLED (full episode)")

        # Track converted parcels (prevents undo within episode)
        self._converted = np.zeros(self.n_swappable, dtype=bool)

    # ------------------------------------------------------------------
    # Adjacency
    # ------------------------------------------------------------------

    def _build_adjacency(self):
        """Build adjacency lists using geopandas spatial join."""
        gdf_idx = gpd.GeoDataFrame(geometry=self.gdf.geometry)
        joined = gpd.sjoin(gdf_idx, gdf_idx, predicate='intersects', how='inner')
        joined = joined[joined.index != joined['index_right']]

        self.adjacency = [np.array([], dtype=np.intp) for _ in range(self.n_parcels)]
        for idx, group in joined.groupby(joined.index)['index_right']:
            self.adjacency[idx] = group.values.astype(np.intp)

        avg_nbr = np.mean([len(a) for a in self.adjacency])
        print(f"  Adjacency built: avg {avg_nbr:.1f} neighbors/parcel")

    # ------------------------------------------------------------------
    # Metrics
    # ------------------------------------------------------------------

    def _compute_metrics_full(self):
        """Compute all metrics from scratch (used once at init)."""
        fm = self.land_use == FARMLAND
        self.n_farmland = int(fm.sum())
        self.n_forest = int((self.land_use == FOREST).sum())
        self.total_farmland_slope = float(self.slopes[fm].sum())

        self.farmland_nbr_count = np.zeros(self.n_parcels, dtype=np.int32)
        for i in range(self.n_parcels):
            nbrs = self.adjacency[i]
            if len(nbrs) > 0:
                self.farmland_nbr_count[i] = int((self.land_use[nbrs] == FARMLAND).sum())

        self.total_farmland_adj = int(self.farmland_nbr_count[fm].sum())

    @property
    def avg_farmland_slope(self):
        return self.total_farmland_slope / max(self.n_farmland, 1)

    @property
    def contiguity(self):
        return self.total_farmland_adj / max(self.n_farmland, 1)

    # ------------------------------------------------------------------
    # Incremental swap updates
    # ------------------------------------------------------------------

    def _swap_to_forest(self, k):
        """Convert parcel k: farmland -> forest. Update metrics incrementally."""
        self.total_farmland_adj -= self.farmland_nbr_count[k]
        self.total_farmland_slope -= self.slopes[k]

        self.land_use[k] = FOREST
        self.n_farmland -= 1
        self.n_forest += 1

        for j in self.adjacency[k]:
            self.farmland_nbr_count[j] -= 1
            if self.land_use[j] == FARMLAND:
                self.total_farmland_adj -= 1

    def _swap_to_farmland(self, k):
        """Convert parcel k: forest -> farmland. Update metrics incrementally."""
        self.land_use[k] = FARMLAND
        self.n_farmland += 1
        self.n_forest -= 1
        self.total_farmland_slope += self.slopes[k]

        self.total_farmland_adj += self.farmland_nbr_count[k]

        for j in self.adjacency[k]:
            self.farmland_nbr_count[j] += 1
            if self.land_use[j] == FARMLAND:
                self.total_farmland_adj += 1

    # ------------------------------------------------------------------
    # Gymnasium API
    # ------------------------------------------------------------------

    def _get_obs(self):
        """Build observation: per-parcel features (N*K) + global features (G)."""
        si = self.swappable_indices
        avg_sl = self.avg_farmland_slope

        # Per-parcel features (K=6 per parcel)
        f_slope = self._static_slopes_norm
        f_type = (self.land_use[si] == FARMLAND).astype(np.float32)
        f_nbr_ratio = self.farmland_nbr_count[si].astype(np.float32) / np.maximum(self.total_nbr_count[si], 1.0)
        f_nbr_slope = self._static_nbr_avg_slope
        f_area = self._static_areas_norm
        f_slope_vs = ((self.slopes[si] - avg_sl) / (abs(avg_sl) + 1e-8)).astype(np.float32)

        per_parcel = np.column_stack([f_slope, f_type, f_nbr_ratio, f_nbr_slope, f_area, f_slope_vs])

        # Global features (G=8)
        cont = self.contiguity
        farmland_dev = (self.n_farmland - self.initial_n_farmland_count) / self.initial_n_farmland_count
        global_f = np.array([
            (avg_sl - self.slope_min) / self.slope_range,
            cont / 10.0,
            farmland_dev,
            self.step_count / self.max_steps,
            self.n_farmland / self.n_parcels,
            self.n_forest / self.n_parcels,
            (avg_sl - self.initial_avg_slope) / (abs(self.initial_avg_slope) + 1e-8),
            (cont - self.initial_contiguity) / (abs(self.initial_contiguity) + 1e-8),
        ], dtype=np.float32)

        return np.concatenate([per_parcel.ravel(), global_f])

    def action_masks(self):
        """Return boolean mask of valid actions (size = n_swappable)."""
        si = self.swappable_indices
        mask = (self.land_use[si] == FARMLAND) | (self.land_use[si] == FOREST)
        mask = mask & ~self._converted
        return mask

    def reset(self, seed=None, options=None):
        super().reset(seed=seed)

        # Restore initial state from cache (fast)
        self.land_use = self.initial_types.copy()
        self.n_farmland = self._cache['n_farmland']
        self.n_forest = self._cache['n_forest']
        self.total_farmland_slope = self._cache['total_farmland_slope']
        self.farmland_nbr_count = self._cache['farmland_nbr_count'].copy()
        self.total_farmland_adj = self._cache['total_farmland_adj']

        self.step_count = 0
        self.completed_conversions = 0
        self.completed_pairs = 0
        self._converted[:] = False

        # Record initial metrics for reward computation
        self.initial_avg_slope = self.avg_farmland_slope
        self.initial_contiguity = self.contiguity
        self.initial_n_farmland_count = self.n_farmland
        self.prev_avg_slope = self.initial_avg_slope
        self.prev_contiguity = self.initial_contiguity

        info = {
            'avg_slope': self.avg_farmland_slope,
            'contiguity': self.contiguity,
            'completed_conversions': 0,
            'completed_pairs': 0,
            'farmland_change': 0,
            'early_stop': False,
        }
        return self._get_obs(), info

    def step(self, action):
        action = int(action)
        parcel_idx = self.swappable_indices[action]

        # Mark parcel as converted (prevents undo)
        self._converted[action] = True

        # Flip based on current type
        if self.land_use[parcel_idx] == FARMLAND:
            self._swap_to_forest(parcel_idx)
        else:
            self._swap_to_farmland(parcel_idx)

        self.step_count += 1
        self.completed_conversions += 1

        # Compute reward
        avg_sl = self.avg_farmland_slope
        cont = self.contiguity

        slope_r = (self.prev_avg_slope - avg_sl) / (abs(self.initial_avg_slope) + 1e-8)
        cont_r = (cont - self.prev_contiguity) / (abs(self.initial_contiguity) + 1e-8)
        count_dev = abs(self.n_farmland - self.initial_n_farmland_count) / self.initial_n_farmland_count

        reward = (SLOPE_REWARD_WEIGHT * slope_r
                  + CONT_REWARD_WEIGHT * cont_r
                  - COUNT_PENALTY_WEIGHT * count_dev * count_dev)

        # Pair completion bonus
        if self.n_farmland == self.initial_n_farmland_count:
            reward += PAIR_BONUS
            self.completed_pairs += 1

        self.prev_avg_slope = avg_sl
        self.prev_contiguity = cont

        # NO early termination — only terminate at max_steps or no valid actions
        terminated = self.step_count >= self.max_steps

        if not terminated:
            mask = self.action_masks()
            if not mask.any():
                terminated = True

        farmland_change = self.n_farmland - self.initial_n_farmland_count
        info = {
            'avg_slope': self.avg_farmland_slope,
            'contiguity': self.contiguity,
            'completed_conversions': self.completed_conversions,
            'completed_pairs': self.completed_pairs,
            'farmland_change': farmland_change,
            'early_stop': False,  # v7: never early stops
        }

        return self._get_obs(), float(reward), terminated, False, info
