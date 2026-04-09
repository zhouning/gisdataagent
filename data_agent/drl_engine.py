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

import json
import logging
from typing import Optional

import numpy as np
import geopandas as gpd
import gymnasium as gym
from gymnasium import spaces
from sqlalchemy import text

logger = logging.getLogger(__name__)


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


# ---------------------------------------------------------------------------
# Scenario Templates (v14.0)
# ---------------------------------------------------------------------------

class DRLScenario:
    """Configuration template for DRL optimization scenarios."""
    def __init__(self, name: str, description: str,
                 source_types: set, target_types: set,
                 slope_weight: float = 1000.0,
                 contiguity_weight: float = 500.0,
                 balance_weight: float = 500.0,
                 pair_bonus: float = 1.0,
                 max_conversions: int = 200,
                 # v23.0 — Constraint modeling
                 min_retention_rate: float = 0.0,
                 max_area_cap: float = float('inf'),
                 budget_cap: float = float('inf'),
                 budget_per_conversion: float = 1.0):
        self.name = name
        self.description = description
        self.source_types = source_types
        self.target_types = target_types
        self.slope_weight = slope_weight
        self.contiguity_weight = contiguity_weight
        self.balance_weight = balance_weight
        self.pair_bonus = pair_bonus
        self.max_conversions = max_conversions
        # Hard constraint: minimum source type retention ratio (0.0 = no limit, 0.8 = keep >=80%)
        self.min_retention_rate = min_retention_rate
        # Soft constraint: max total converted area (sq meters)
        self.max_area_cap = max_area_cap
        # Soft constraint: budget cap (abstract units)
        self.budget_cap = budget_cap
        self.budget_per_conversion = budget_per_conversion


# Built-in scenario templates
SCENARIOS: dict[str, DRLScenario] = {
    "farmland_optimization": DRLScenario(
        name="耕地布局优化",
        description="优化耕地与林地的空间分布，最小化耕地坡度、最大化连片度",
        source_types={'旱地', '水田'},
        target_types={'果园', '有林地'},
        slope_weight=1000.0,
        contiguity_weight=500.0,
        balance_weight=500.0,
    ),
    "urban_green_space": DRLScenario(
        name="城市绿地布局",
        description="优化城市绿地空间分布，最大化绿地可达性和连通性",
        source_types={'绿地', '公园', '草地'},
        target_types={'建设用地', '硬化地面'},
        slope_weight=200.0,
        contiguity_weight=1000.0,
        balance_weight=800.0,
    ),
    "facility_siting": DRLScenario(
        name="设施选址优化",
        description="优化公共设施布局，平衡服务覆盖和交通可达",
        source_types={'公共服务设施', '公共设施'},
        target_types={'居住用地', '商业用地'},
        slope_weight=300.0,
        contiguity_weight=800.0,
        balance_weight=600.0,
        max_conversions=100,
    ),
    # v23.0 — New scenarios
    "road_network": DRLScenario(
        name="道路网络优化",
        description="优化道路网络布局，最小化通行坡度、最大化路网连通性，保留主干道",
        source_types={'公路用地', '农村道路', '城镇道路', '村道'},
        target_types={'耕地', '林地', '草地'},
        slope_weight=1200.0,
        contiguity_weight=1000.0,
        balance_weight=400.0,
        pair_bonus=1.5,
        max_conversions=150,
        min_retention_rate=0.7,
    ),
    "public_facility_layout": DRLScenario(
        name="公共设施布局优化",
        description="优化学校/医院/公园等公共设施空间分布，最大化服务覆盖均匀性",
        source_types={'教育用地', '医疗卫生用地', '文化设施用地', '体育用地', '公园'},
        target_types={'居住用地', '商业用地', '工业用地'},
        slope_weight=100.0,
        contiguity_weight=300.0,
        balance_weight=1000.0,
        pair_bonus=2.0,
        max_conversions=80,
        min_retention_rate=0.85,
        budget_cap=200.0,
        budget_per_conversion=3.0,
    ),
}


def list_scenarios() -> list[dict]:
    """Return available DRL scenario templates."""
    return [
        {
            "id": sid,
            "name": s.name,
            "description": s.description,
            "source_types": sorted(s.source_types),
            "target_types": sorted(s.target_types),
            "weights": {
                "slope": s.slope_weight,
                "contiguity": s.contiguity_weight,
                "balance": s.balance_weight,
            },
            "max_conversions": s.max_conversions,
        }
        for sid, s in SCENARIOS.items()
    ]


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

    def __init__(self, shp_path, max_conversions=200, scenario: 'DRLScenario | None' = None):
        super().__init__()

        # Apply scenario config if provided
        self.scenario = scenario
        if scenario:
            self.source_types = scenario.source_types
            self.target_types = scenario.target_types
            self.slope_w = scenario.slope_weight
            self.cont_w = scenario.contiguity_weight
            self.balance_w = scenario.balance_weight
            self.pair_b = scenario.pair_bonus
            max_conversions = scenario.max_conversions
            # v23.0 constraints
            self.min_retention_rate = scenario.min_retention_rate
            self.max_area_cap = scenario.max_area_cap
            self.budget_cap = scenario.budget_cap
            self.budget_per_conversion = scenario.budget_per_conversion
        else:
            self.source_types = FARMLAND_TYPES
            self.target_types = FOREST_TYPES
            self.slope_w = SLOPE_REWARD_WEIGHT
            self.cont_w = CONT_REWARD_WEIGHT
            self.balance_w = COUNT_PENALTY_WEIGHT
            self.pair_b = PAIR_BONUS
            # v23.0 defaults — no constraints
            self.min_retention_rate = 0.0
            self.max_area_cap = float('inf')
            self.budget_cap = float('inf')
            self.budget_per_conversion = 1.0

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

        # Classify parcels (v14.1: use scenario types if provided)
        self.initial_types = np.full(self.n_parcels, OTHER, dtype=np.int8)
        for i, t in enumerate(dlmc):
            if t in self.source_types:
                self.initial_types[i] = FARMLAND
            elif t in self.target_types:
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
        """Return boolean mask of valid actions (size = n_swappable).

        v23.0: Enforces hard constraints — masks out actions that would
        violate min_retention_rate for source types.
        """
        si = self.swappable_indices
        mask = (self.land_use[si] == FARMLAND) | (self.land_use[si] == FOREST)
        mask = mask & ~self._converted

        # Hard constraint: min retention rate for source (farmland) type
        if self.min_retention_rate > 0 and self.initial_n_farmland_count > 0:
            min_farmland = int(self.initial_n_farmland_count * self.min_retention_rate)
            if self.n_farmland <= min_farmland:
                # Block all farmland→forest conversions (only allow forest→farmland)
                farmland_mask = self.land_use[si] == FARMLAND
                mask = mask & ~farmland_mask

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
        # v23.0 constraint tracking
        self.total_converted_area = 0.0
        self.total_budget_spent = 0.0

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

        # v23.0: Track converted area and budget
        self.total_converted_area += float(self.areas[parcel_idx])
        self.total_budget_spent += self.budget_per_conversion

        # Compute reward
        avg_sl = self.avg_farmland_slope
        cont = self.contiguity

        slope_r = (self.prev_avg_slope - avg_sl) / (abs(self.initial_avg_slope) + 1e-8)
        cont_r = (cont - self.prev_contiguity) / (abs(self.initial_contiguity) + 1e-8)
        count_dev = abs(self.n_farmland - self.initial_n_farmland_count) / self.initial_n_farmland_count

        reward = (self.slope_w * slope_r
                  + self.cont_w * cont_r
                  - self.balance_w * count_dev * count_dev)

        # Pair completion bonus
        if self.n_farmland == self.initial_n_farmland_count:
            reward += self.pair_b
            self.completed_pairs += 1

        # v23.0: Soft constraint penalties
        if self.total_converted_area > self.max_area_cap:
            overshoot = (self.total_converted_area - self.max_area_cap) / self.max_area_cap
            reward -= self.balance_w * overshoot
        if self.total_budget_spent > self.budget_cap:
            overshoot = (self.total_budget_spent - self.budget_cap) / self.budget_cap
            reward -= self.balance_w * overshoot

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


# ---------------------------------------------------------------------------
# Multi-Objective Optimization (v12.0.1, Design Pattern Ch14)
# ---------------------------------------------------------------------------

class ParetoFrontier:
    """Maintains a set of non-dominated solutions (Pareto front).

    Each solution is a tuple of (objectives_vector, metadata_dict).
    A solution A dominates B iff A is at least as good in all objectives
    and strictly better in at least one.
    """

    def __init__(self, maximize: list[bool] = None):
        """
        Args:
            maximize: list of bools indicating direction per objective.
                      True = higher is better, False = lower is better.
                      Default: all True (maximize).
        """
        self._solutions: list[tuple[list[float], dict]] = []
        self._maximize = maximize

    def _dominates(self, a: list[float], b: list[float]) -> bool:
        """Check if solution a dominates solution b."""
        dirs = self._maximize or [True] * len(a)
        at_least_as_good = True
        strictly_better = False
        for i in range(len(a)):
            if dirs[i]:  # maximize
                if a[i] < b[i]:
                    at_least_as_good = False
                    break
                if a[i] > b[i]:
                    strictly_better = True
            else:  # minimize
                if a[i] > b[i]:
                    at_least_as_good = False
                    break
                if a[i] < b[i]:
                    strictly_better = True
        return at_least_as_good and strictly_better

    def add_solution(self, objectives: list[float], metadata: dict = None) -> bool:
        """Add a solution if it is not dominated by existing solutions.

        Also removes any existing solutions dominated by the new one.
        Returns True if solution was added to the frontier.
        """
        metadata = metadata or {}

        # Check if new solution is dominated by any existing
        for obj, _ in self._solutions:
            if self._dominates(obj, objectives):
                return False  # dominated, don't add

        # Remove solutions dominated by the new one
        self._solutions = [
            (obj, meta) for obj, meta in self._solutions
            if not self._dominates(objectives, obj)
        ]

        self._solutions.append((objectives, metadata))
        return True

    def get_frontier(self) -> list[dict]:
        """Return all Pareto-optimal solutions as dicts."""
        return [
            {"objectives": obj, "metadata": meta}
            for obj, meta in self._solutions
        ]

    @property
    def size(self) -> int:
        return len(self._solutions)

    def clear(self):
        self._solutions.clear()


def compute_objectives(env: LandUseOptEnv) -> list[float]:
    """Compute individual objective values from current environment state.

    Returns [slope_score, contiguity_score, area_balance_score].
    - slope_score: lower avg farmland slope is better (minimize) → negate for maximize
    - contiguity_score: higher farmland clustering (maximize)
    - area_balance_score: 1.0 - deviation ratio (maximize, 1.0 = perfect balance)
    """
    slope_score = -env.avg_farmland_slope  # negate: lower slope → higher score
    contiguity_score = env.contiguity
    count_dev = abs(env.n_farmland - env.initial_n_farmland_count) / max(env.initial_n_farmland_count, 1)
    area_balance = 1.0 - min(count_dev, 1.0)  # 1.0 = perfect, 0.0 = max deviation
    return [round(slope_score, 4), round(contiguity_score, 4), round(area_balance, 4)]


def optimize_multi_objective(
    gdf: gpd.GeoDataFrame,
    weight_sets: list[tuple[float, float, float]] = None,
    max_steps: int = 200,
) -> dict:
    """Run multi-objective optimization with different weight combinations.

    Collects Pareto-optimal solutions across runs.

    Args:
        gdf: GeoDataFrame with land-use parcels.
        weight_sets: List of (slope_w, cont_w, count_w) weight tuples.
                     Default: 5 evenly spaced weight combinations.
        max_steps: Steps per optimization run.

    Returns:
        dict with pareto_frontier, run_count, objective_names.
    """
    if weight_sets is None:
        weight_sets = [
            (1000, 200, 500),   # slope-focused
            (500, 500, 500),    # balanced
            (200, 1000, 500),   # contiguity-focused
            (800, 400, 200),    # relaxed area constraint
            (400, 800, 800),    # strict area + contiguity
        ]

    # Objective directions: all maximize (slope is negated in compute_objectives)
    frontier = ParetoFrontier(maximize=[True, True, True])

    for i, (sw, cw, pw) in enumerate(weight_sets):
        try:
            # Create env with custom weights
            env = LandUseOptEnv(gdf, max_steps=max_steps)

            # Override reward weights for this run
            global SLOPE_REWARD_WEIGHT, CONT_REWARD_WEIGHT, COUNT_PENALTY_WEIGHT
            orig_sw, orig_cw, orig_pw = SLOPE_REWARD_WEIGHT, CONT_REWARD_WEIGHT, COUNT_PENALTY_WEIGHT
            SLOPE_REWARD_WEIGHT, CONT_REWARD_WEIGHT, COUNT_PENALTY_WEIGHT = sw, cw, pw

            # Run random policy (lightweight — no training needed for demonstration)
            obs, _ = env.reset()
            for step in range(max_steps):
                mask = env.action_masks()
                valid = np.where(mask)[0]
                if len(valid) == 0:
                    break
                action = np.random.choice(valid)
                obs, reward, done, truncated, info = env.step(action)
                if done:
                    break

            # Restore weights
            SLOPE_REWARD_WEIGHT, CONT_REWARD_WEIGHT, COUNT_PENALTY_WEIGHT = orig_sw, orig_cw, orig_pw

            # Record objectives
            objectives = compute_objectives(env)
            metadata = {
                "run_index": i,
                "weights": {"slope": sw, "contiguity": cw, "count_penalty": pw},
                "steps": env.step_count,
                "pairs": env.completed_pairs,
                "farmland_change": env.n_farmland - env.initial_n_farmland_count,
            }
            frontier.add_solution(objectives, metadata)

        except Exception:
            continue

    return {
        "pareto_frontier": frontier.get_frontier(),
        "frontier_size": frontier.size,
        "run_count": len(weight_sets),
        "objective_names": ["slope_score", "contiguity_score", "area_balance"],
        "objective_directions": ["maximize", "maximize", "maximize"],
    }


# ---------------------------------------------------------------------------
# NSGA-II Multi-Objective Optimizer (v14.3)
# ---------------------------------------------------------------------------

def _dominates(a: list[float], b: list[float]) -> bool:
    """True if solution a Pareto-dominates solution b (all >= and at least one >)."""
    at_least_one_better = False
    for ai, bi in zip(a, b):
        if ai < bi:
            return False
        if ai > bi:
            at_least_one_better = True
    return at_least_one_better


def _fast_nondominated_sort(population: list[dict]) -> list[list[int]]:
    """NSGA-II fast non-dominated sorting. Returns list of fronts (index lists)."""
    n = len(population)
    domination_count = [0] * n
    dominated_by = [[] for _ in range(n)]
    fronts = [[]]

    for i in range(n):
        for j in range(i + 1, n):
            oi = population[i]["objectives"]
            oj = population[j]["objectives"]
            if _dominates(oi, oj):
                dominated_by[i].append(j)
                domination_count[j] += 1
            elif _dominates(oj, oi):
                dominated_by[j].append(i)
                domination_count[i] += 1

    for i in range(n):
        if domination_count[i] == 0:
            fronts[0].append(i)

    k = 0
    while fronts[k]:
        next_front = []
        for i in fronts[k]:
            for j in dominated_by[i]:
                domination_count[j] -= 1
                if domination_count[j] == 0:
                    next_front.append(j)
        k += 1
        fronts.append(next_front)

    return [f for f in fronts if f]


def _crowding_distance(population: list[dict], front: list[int]) -> list[float]:
    """Compute crowding distance for a Pareto front."""
    n = len(front)
    if n <= 2:
        return [float('inf')] * n
    n_obj = len(population[front[0]]["objectives"])
    distances = [0.0] * n

    for m in range(n_obj):
        sorted_idx = sorted(range(n), key=lambda i: population[front[i]]["objectives"][m])
        distances[sorted_idx[0]] = float('inf')
        distances[sorted_idx[-1]] = float('inf')
        obj_range = (population[front[sorted_idx[-1]]]["objectives"][m]
                     - population[front[sorted_idx[0]]]["objectives"][m])
        if obj_range == 0:
            continue
        for i in range(1, n - 1):
            distances[sorted_idx[i]] += (
                population[front[sorted_idx[i + 1]]]["objectives"][m]
                - population[front[sorted_idx[i - 1]]]["objectives"][m]
            ) / obj_range

    return distances


def nsga2_optimize(
    gdf: gpd.GeoDataFrame,
    population_size: int = 20,
    generations: int = 10,
    max_steps: int = 200,
    scenario: 'DRLScenario | None' = None,
) -> dict:
    """NSGA-II multi-objective optimization.

    Generates diverse Pareto-optimal solutions via evolutionary selection
    with non-dominated sorting and crowding distance.
    """
    import random
    import tempfile
    import os

    # Save GeoDataFrame to temp file for env loading
    tmp_path = os.path.join(tempfile.gettempdir(), f"nsga2_{id(gdf)}.shp")
    gdf.to_file(tmp_path)

    # Generate initial population with random weight combinations
    population = []
    for _ in range(population_size):
        sw = random.uniform(100, 2000)
        cw = random.uniform(100, 1500)
        bw = random.uniform(100, 1000)

        try:
            sc = DRLScenario(
                name="nsga2_run",
                description="",
                source_types=scenario.source_types if scenario else FARMLAND_TYPES,
                target_types=scenario.target_types if scenario else FOREST_TYPES,
                slope_weight=sw, contiguity_weight=cw, balance_weight=bw,
                max_conversions=max_steps,
            )
            env = LandUseOptEnv(tmp_path, scenario=sc)
            obs, _ = env.reset()
            for _ in range(max_steps):
                masks = env.action_masks()
                if not masks.any():
                    break
                action = random.choice(np.where(masks)[0])
                obs, _, done, trunc, _ = env.step(action)
                if done or trunc:
                    break

            slope_score = max(0, 1.0 - env.avg_farmland_slope / (env.initial_avg_slope + 1e-8))
            cont_score = env.contiguity / (env.initial_contiguity + 1e-8)
            balance = 1.0 - abs(env.n_farmland - env.initial_n_farmland_count) / (env.initial_n_farmland_count + 1e-8)

            population.append({
                "objectives": [slope_score, cont_score, balance],
                "weights": [sw, cw, bw],
                "conversions": env.step_count,
            })
        except Exception:
            continue

    if not population:
        return {"status": "error", "message": "All runs failed"}

    # NSGA-II selection over generations
    for gen in range(generations):
        fronts = _fast_nondominated_sort(population)
        new_pop = []
        for front in fronts:
            if len(new_pop) + len(front) <= population_size:
                new_pop.extend(front)
            else:
                dist = _crowding_distance(population, front)
                ranked = sorted(range(len(front)), key=lambda i: dist[i], reverse=True)
                remaining = population_size - len(new_pop)
                new_pop.extend([front[ranked[i]] for i in range(remaining)])
                break
        population = [population[i] for i in new_pop]

    # Return Pareto front
    fronts = _fast_nondominated_sort(population)
    pareto = [population[i] for i in fronts[0]] if fronts else population

    # Cleanup
    try:
        os.remove(tmp_path)
    except Exception:
        pass

    return {
        "status": "ok",
        "pareto_frontier": [
            {
                "objectives": p["objectives"],
                "weights": p["weights"],
                "slope_score": round(p["objectives"][0], 4),
                "contiguity_score": round(p["objectives"][1], 4),
                "area_balance": round(p["objectives"][2], 4),
            }
            for p in pareto
        ],
        "frontier_size": len(pareto),
        "generations": generations,
        "population_size": population_size,
        "objective_names": ["slope_score", "contiguity_score", "area_balance"],
    }


# ---------------------------------------------------------------------------
# Additional Scenario Environments (v14.3 stubs)
# ---------------------------------------------------------------------------

# Transport Network scenario — road network optimization
SCENARIOS["transport_network"] = DRLScenario(
    name="交通网络优化",
    description="优化道路网络布局，平衡通行效率和建设成本",
    source_types={'主干路', '次干路', '支路'},
    target_types={'绿化带', '人行道'},
    slope_weight=400.0,
    contiguity_weight=1200.0,
    balance_weight=600.0,
    max_conversions=150,
)

# Public Facility Siting — already in SCENARIOS, add hospital/school variant
SCENARIOS["public_services"] = DRLScenario(
    name="公共服务设施选址",
    description="优化学校、医院等公共服务设施空间分布，最大化服务覆盖人口",
    source_types={'公共服务设施', '学校', '医院', '社区中心'},
    target_types={'居住用地', '商业用地', '工业用地'},
    slope_weight=200.0,
    contiguity_weight=600.0,
    balance_weight=1000.0,
    max_conversions=80,
)


# ---------------------------------------------------------------------------
# Run History (v15.4)
# ---------------------------------------------------------------------------

def save_run_result(username: str, scenario_id: str, weights: dict,
                    output_path: str, summary: str, metrics: dict) -> Optional[int]:
    """Save a DRL optimization run result for history/comparison."""
    from .db_engine import get_engine
    engine = get_engine()
    if not engine:
        return None
    try:
        with engine.connect() as conn:
            row = conn.execute(text(
                "INSERT INTO drl_run_history (username, scenario_id, weights, output_path, summary, metrics) "
                "VALUES (:u, :s, :w, :o, :sum, :m) RETURNING id"
            ), {"u": username, "s": scenario_id, "w": json.dumps(weights),
                "o": output_path, "sum": summary, "m": json.dumps(metrics)}).fetchone()
            conn.commit()
            return row.id if row else None
    except Exception as e:
        logger.warning("save_run_result failed: %s", e)
        return None


def list_run_history(username: str, limit: int = 20) -> list:
    """List recent DRL optimization runs for a user."""
    from .db_engine import get_engine
    engine = get_engine()
    if not engine:
        return []
    try:
        with engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT id, scenario_id, weights, summary, metrics, created_at "
                "FROM drl_run_history WHERE username = :u ORDER BY created_at DESC LIMIT :lim"
            ), {"u": username, "lim": limit}).fetchall()
            return [{"id": r.id, "scenario_id": r.scenario_id,
                     "weights": r.weights if isinstance(r.weights, dict) else json.loads(r.weights or "{}"),
                     "summary": r.summary,
                     "metrics": r.metrics if isinstance(r.metrics, dict) else json.loads(r.metrics or "{}"),
                     "created_at": str(r.created_at)} for r in rows]
    except Exception as e:
        logger.warning("list_run_history failed: %s", e)
        return []


def compare_runs(run_a: dict, run_b: dict) -> dict:
    """Compare two DRL optimization runs."""
    metrics_a = run_a.get("metrics", {})
    metrics_b = run_b.get("metrics", {})

    all_keys = set(list(metrics_a.keys()) + list(metrics_b.keys()))
    comparison = {}
    for key in sorted(all_keys):
        va = metrics_a.get(key)
        vb = metrics_b.get(key)
        comparison[key] = {
            "run_a": va,
            "run_b": vb,
            "delta": round(vb - va, 4) if isinstance(va, (int, float)) and isinstance(vb, (int, float)) else None,
        }

    return {
        "run_a": {"id": run_a.get("id"), "scenario": run_a.get("scenario_id"), "weights": run_a.get("weights")},
        "run_b": {"id": run_b.get("id"), "scenario": run_b.get("scenario_id"), "weights": run_b.get("weights")},
        "metrics_comparison": comparison,
    }
