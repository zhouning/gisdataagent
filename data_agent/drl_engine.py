"""
Custom Gymnasium environment for land use optimization (v2).

v2 changes vs v1:
  - Early termination when a swap pair yields negative reward.
    The episode ends automatically if the combined slope+contiguity
    reward for a completed swap pair is < 0, meaning the swap was
    not beneficial.  This allows the model to perform a variable
    number of swaps per episode instead of always doing max_swaps.
  - Added 'completed_swaps' counter exposed in info dict.
  - Added 'early_stop' flag in info dict indicating whether the
    episode ended due to negative reward.
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


class LandUseOptEnv(gym.Env):
    """
    Land use optimization environment with action masking (v2).

    Each episode alternates between two phases:
      Phase 0: Agent selects a farmland parcel → converts to forest
      Phase 1: Agent selects a forest parcel → converts to farmland
    This ensures paired swaps that maintain total farmland/forest counts.

    v2: Episode terminates early when a swap pair yields negative reward,
    allowing the model to adaptively decide how many swaps to perform.
    """

    metadata = {"render_modes": []}

    def __init__(self, shp_path, max_swaps=100):
        super().__init__()

        # Load shapefile
        print(f"Loading shapefile: {shp_path}")
        self.gdf = gpd.read_file(shp_path)
        self.n_parcels = len(self.gdf)

        # Episode length
        self.max_swaps = max_swaps
        self.max_steps = max_swaps * 2

        # Extract attributes
        # Ensure 'Slope' and 'DLMC' exist
        if 'Slope' not in self.gdf.columns:
             # Fallback if Slope is missing, though real data should have it
             print("Warning: 'Slope' column missing, initializing with zeros.")
             self.gdf['Slope'] = 0.0
        
        self.slopes = self.gdf['Slope'].values.astype(np.float64)
        
        if 'DLMC' not in self.gdf.columns:
             print("Warning: 'DLMC' column missing, initializing with default.")
             self.gdf['DLMC'] = 'Unknown'
             
        dlmc = self.gdf['DLMC'].values

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

        # Build spatial adjacency graph
        print("Building adjacency graph...")
        self._build_adjacency()

        # Total neighbor count per parcel (for normalization)
        self.total_nbr_count = np.array(
            [len(self.adjacency[i]) for i in range(self.n_parcels)], dtype=np.float32
        )

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

        # Pre-compute static per-parcel slope features for swappable parcels
        self._swappable_slopes_norm = self.slopes_norm[self.swappable_indices]

        # Define spaces
        self.action_space = spaces.Discrete(self.n_swappable)
        # Obs: per-swappable type (n_swappable) + global features (8)
        obs_dim = self.n_swappable + 8
        self.observation_space = spaces.Box(
            low=-np.inf, high=np.inf, shape=(obs_dim,), dtype=np.float32
        )

        # Print summary
        init_slope = self._cache['total_farmland_slope'] / max(self._cache['n_farmland'], 1)
        init_cont = self._cache['total_farmland_adj'] / max(self._cache['n_farmland'], 1)
        print(f"Environment initialized (v2 - early stop on negative reward):")
        print(f"  Total parcels: {self.n_parcels}")
        print(f"  Swappable: {self.n_swappable} "
              f"(farmland={self._cache['n_farmland']}, forest={self._cache['n_forest']})")
        print(f"  Initial avg farmland slope: {init_slope:.4f}")
        print(f"  Initial farmland contiguity: {init_cont:.4f}")
        print(f"  Observation dim: {obs_dim}, Action dim: {self.n_swappable}")
        print(f"  Max steps/episode: {self.max_steps} (may terminate earlier)")

        # Track converted parcels (prevents undo within episode)
        self._converted = np.zeros(self.n_swappable, dtype=bool)

    # ------------------------------------------------------------------
    # Adjacency
    # ------------------------------------------------------------------

    def _build_adjacency(self):
        """Build adjacency lists using geopandas spatial join."""
        gdf_idx = gpd.GeoDataFrame(geometry=self.gdf.geometry)
        # Use only geometries that are valid
        if not gdf_idx.is_valid.all():
             gdf_idx['geometry'] = gdf_idx.geometry.buffer(0)
             
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
        """Convert parcel k: farmland → forest. Update metrics incrementally."""
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
        """Convert parcel k: forest → farmland. Update metrics incrementally."""
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
        """Build observation vector: per-parcel types + global features."""
        si = self.swappable_indices

        # Per-parcel: current type (1.0=farmland, 0.0=forest)
        types = (self.land_use[si] == FARMLAND).astype(np.float32)

        # Global features
        avg_sl = self.avg_farmland_slope
        cont = self.contiguity
        global_f = np.array([
            (avg_sl - self.slope_min) / self.slope_range,   # normalized avg slope
            cont / 10.0,                                     # normalized contiguity
            float(self.phase),                                # current phase
            self.step_count / self.max_steps,                 # progress
            self.n_farmland / self.n_parcels,                 # farmland fraction
            self.n_forest / self.n_parcels,                   # forest fraction
            (avg_sl - self.initial_avg_slope) / (abs(self.initial_avg_slope) + 1e-8),
            (cont - self.initial_contiguity) / (abs(self.initial_contiguity) + 1e-8),
        ], dtype=np.float32)

        return np.concatenate([types, global_f])

    def action_masks(self):
        """Return boolean mask of valid actions (size = n_swappable)."""
        si = self.swappable_indices
        if self.phase == 0:
            mask = (self.land_use[si] == FARMLAND)
        else:
            mask = (self.land_use[si] == FOREST)
        # Exclude parcels already converted this episode (prevents undo)
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
        self.phase = 0
        self.completed_swaps = 0
        self.early_stopped = False
        self._converted[:] = False

        # Record initial metrics for reward computation
        self.initial_avg_slope = self.avg_farmland_slope
        self.initial_contiguity = self.contiguity
        self.prev_avg_slope = self.initial_avg_slope
        self.prev_contiguity = self.initial_contiguity

        info = {
            'avg_slope': self.avg_farmland_slope,
            'contiguity': self.contiguity,
            'completed_swaps': 0,
            'early_stop': False,
        }
        return self._get_obs(), info

    def step(self, action):
        action = int(action)
        # Map action index to actual parcel index
        parcel_idx = self.swappable_indices[action]

        # Mark parcel as converted (prevents undo)
        self._converted[action] = True

        # Execute swap based on current phase
        if self.phase == 0:
            self._swap_to_forest(parcel_idx)
        else:
            self._swap_to_farmland(parcel_idx)

        self.step_count += 1

        # Compute reward after each swap pair (phase 1 completes a pair)
        reward = 0.0
        pair_completed = (self.phase == 1)
        if pair_completed:
            avg_sl = self.avg_farmland_slope
            cont = self.contiguity

            # Normalized slope improvement (positive = good)
            slope_r = (self.prev_avg_slope - avg_sl) / (abs(self.initial_avg_slope) + 1e-8)
            # Normalized contiguity change (positive = good)
            cont_r = (cont - self.prev_contiguity) / (abs(self.initial_contiguity) + 1e-8)

            # Weighted reward: prioritize slope reduction, penalize contiguity loss
            reward = 1000.0 * slope_r + 500.0 * cont_r

            self.prev_avg_slope = avg_sl
            self.prev_contiguity = cont
            self.completed_swaps += 1

        # Toggle phase
        self.phase = 1 - self.phase

        # Check termination
        terminated = self.step_count >= self.max_steps

        # v2: Early termination when swap pair yields negative reward
        if not terminated and pair_completed and reward < 0:
            terminated = True
            self.early_stopped = True

        if not terminated:
            mask = self.action_masks()
            if not mask.any():
                terminated = True

        info = {
            'avg_slope': self.avg_farmland_slope,
            'contiguity': self.contiguity,
            'completed_swaps': self.completed_swaps,
            'early_stop': self.early_stopped,
        }

        return self._get_obs(), float(reward), terminated, False, info
