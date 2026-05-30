"""World Model v2 — Bishan county farmland optimization via Dual-Layer Geospatial Dreamer.

Supports three inference modes:
  - "ppo" (default): Fast PPO policy (seed 10 iter 1 best checkpoint, ~1s per episode)
  - "dream_v5": PPO trained inside contrastive dream env (~4s per episode, -0.859%)
  - "mpc": Contrastive-trained ensemble + MPC H=5 K=50 greedy (~230s per episode,
    5-seed mean -1.286% ± 0.079%, 6.2x better than baseline MPC ceiling -0.209%,
    p=1.07e-05 vs baseline)

Deployed MPC ensemble is the seed 0 member from the 5-seed statistical
replication (single-seed eval -1.4235%, the best single ensemble among 5).

See paper9 contrastive breakthrough (2026-05-06/07) for background.
"""

import json
import logging
import os
import sys
import threading
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

_CHECKPOINT_DIR = Path(r"D:\adk\results_dual_dreamer_real_control_blind_full")
_DEFAULT_CHECKPOINT = _CHECKPOINT_DIR / "dagger_ensemble_seed10_iter1_best.zip"

_CONTRASTIVE_ENSEMBLE_DIR = Path(r"D:\test\paper9_contrastive\multi_seed")
_CONTRASTIVE_LAMBDA = 5.0
_CONTRASTIVE_SEED = 0  # 5-seed replication best single ensemble
_CONTRASTIVE_N_MODELS = 3

_DREAM_V5_CHECKPOINT = Path(r"D:\test\paper9_contrastive\dream_v5\dream_ppo_lam5.0_seed0.zip")

_instance_lock = threading.Lock()
_instance = None


def get_world_model_v2_service():
    """Return singleton WorldModelV2Service instance."""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = WorldModelV2Service()
    return _instance


class WorldModelV2Service:
    """Bishan county farmland optimization via Dual-Layer Geospatial Dreamer."""

    VERSION = "2.2.0"
    REGION = "璧山区 (Bishan District, Chongqing)"

    def __init__(self):
        self._checkpoint_path = str(_DEFAULT_CHECKPOINT)
        self._contrastive_path_prefix = str(
            _CONTRASTIVE_ENSEMBLE_DIR
            / f"ensemble_seed{_CONTRASTIVE_SEED}_lam{_CONTRASTIVE_LAMBDA}"
        )

    def status(self) -> dict:
        ppo_available = os.path.exists(self._checkpoint_path)
        contrastive_available = all(
            os.path.exists(f"{self._contrastive_path_prefix}_member{i}.pt")
            for i in range(_CONTRASTIVE_N_MODELS)
        )
        dream_v5_available = os.path.exists(str(_DREAM_V5_CHECKPOINT))
        return {
            "version": self.VERSION,
            "region": self.REGION,
            "modes": {
                "ppo": {
                    "model": "MaskablePPO + ParcelScoringPolicy (Blind DAgger)",
                    "checkpoint": os.path.basename(self._checkpoint_path),
                    "available": ppo_available,
                    "typical_slope_improvement_pct": -0.335,
                    "time_per_episode_s": 1.0,
                },
                "dream_v5": {
                    "model": f"MaskablePPO trained in contrastive dream env (λ={_CONTRASTIVE_LAMBDA})",
                    "checkpoint": os.path.basename(str(_DREAM_V5_CHECKPOINT)),
                    "available": dream_v5_available,
                    "typical_slope_improvement_pct": -0.859,
                    "time_per_episode_s": 4.0,
                },
                "mpc": {
                    "model": f"Contrastive Ensemble (λ={_CONTRASTIVE_LAMBDA}, N={_CONTRASTIVE_N_MODELS}, seed={_CONTRASTIVE_SEED}) + MPC H=5 K=50 greedy",
                    "checkpoint": f"ensemble_seed{_CONTRASTIVE_SEED}_lam{_CONTRASTIVE_LAMBDA}_member0..{_CONTRASTIVE_N_MODELS-1}.pt",
                    "available": contrastive_available,
                    "typical_slope_improvement_pct": -1.286,
                    "slope_improvement_pct_5seed_std": 0.079,
                    "slope_improvement_pct_this_ensemble": -1.4235,
                    "time_per_episode_s": 230.0,
                },
            },
            "default_mode": "ppo",
            "supported_actions": ["run_optimization"],
        }
    def run_optimization(self, n_episodes: int = 10, mode: str = "ppo") -> dict:
        """Run evaluation episodes and return results + GeoJSON.

        Args:
            n_episodes: number of episodes to run (1-20 recommended)
            mode: "ppo" (fast, default), "dream_v5" (medium), or "mpc" (slow, best quality)
        """
        if mode not in {"ppo", "dream_v5", "mpc"}:
            return {"status": "error", "error": f"Unknown mode '{mode}'; expected 'ppo', 'dream_v5', or 'mpc'"}

        if mode == "ppo" and not os.path.exists(self._checkpoint_path):
            return {"status": "error", "error": f"PPO checkpoint not found: {self._checkpoint_path}"}
        if mode == "dream_v5" and not os.path.exists(str(_DREAM_V5_CHECKPOINT)):
            return {"status": "error", "error": f"Dream v5 checkpoint not found: {_DREAM_V5_CHECKPOINT}"}
        if mode == "mpc":
            missing = [
                f"{self._contrastive_path_prefix}_member{i}.pt"
                for i in range(_CONTRASTIVE_N_MODELS)
                if not os.path.exists(f"{self._contrastive_path_prefix}_member{i}.pt")
            ]
            if missing:
                return {"status": "error", "error": f"Contrastive ensemble missing: {missing}"}

        try:
            env = self._create_env()
            if mode == "ppo":
                ppo = self._load_model(self._checkpoint_path, env)
                best = self._run_episodes_ppo(ppo, env, n_episodes)
                model_label = os.path.basename(self._checkpoint_path)
            elif mode == "dream_v5":
                ppo = self._load_model(str(_DREAM_V5_CHECKPOINT), env)
                best = self._run_episodes_ppo(ppo, env, n_episodes)
                model_label = os.path.basename(str(_DREAM_V5_CHECKPOINT))
            else:
                ensemble = self._load_contrastive_ensemble(env.n_blocks)
                best = self._run_episodes_mpc(ensemble, env, n_episodes)
                model_label = f"contrastive_seed{_CONTRASTIVE_SEED}_lam{_CONTRASTIVE_LAMBDA}"

            before_path, opt_path, diff_path = self._generate_geojson_layers(
                env, best["initial_types"], best["final_types"],
            )
            map_config = self._build_map_config(before_path, opt_path, diff_path)

            return {
                "status": "ok",
                "version": self.VERSION,
                "region": self.REGION,
                "mode": mode,
                "model": model_label,
                "n_episodes": n_episodes,
                "best_episode": best["episode"],
                "total_reward": round(float(best["total_reward"]), 4),
                "n_swaps": int(best["n_swaps"]),
                "initial_slope": round(float(best["initial_slope"]), 6),
                "final_slope": round(float(best["final_slope"]), 6),
                "slope_improvement": round(float(best["slope_improvement"]), 6),
                "initial_contiguity": round(float(best["initial_contiguity"]), 6),
                "final_contiguity": round(float(best["final_contiguity"]), 6),
                "contiguity_improvement": round(float(best["contiguity_improvement"]), 6),
                "geojson_before": os.path.basename(before_path),
                "geojson_optimized": os.path.basename(opt_path),
                "geojson_diff": os.path.basename(diff_path),
                "map_config": map_config,
            }
        except Exception as e:
            logger.exception("WorldModelV2 optimization failed")
            return {"status": "error", "error": str(e)}

    def _create_env(self):
        if "D:\\test" not in sys.path:
            sys.path.insert(0, "D:\\test")
        from county_env import CountyLevelEnv
        return CountyLevelEnv(total_budget=500, swaps_per_step=5)

    def _load_model(self, checkpoint_path: str, env):
        from sb3_contrib import MaskablePPO
        if "D:\\test" not in sys.path:
            sys.path.insert(0, "D:\\test")
        from parcel_scoring_policy import ParcelScoringPolicy

        model = MaskablePPO.load(
            checkpoint_path,
            env=env,
            custom_objects={"policy_class": ParcelScoringPolicy},
        )
        return model

    def _load_contrastive_ensemble(self, n_blocks: int):
        """Load contrastive-trained N-member ensemble."""
        import torch
        from data_agent.transition_model import EnsembleTransitionModel

        ensemble = EnsembleTransitionModel(n_blocks, n_models=_CONTRASTIVE_N_MODELS)
        for i in range(_CONTRASTIVE_N_MODELS):
            path = f"{self._contrastive_path_prefix}_member{i}.pt"
            ensemble.models[i].load_state_dict(torch.load(path, map_location="cpu"))
            ensemble.models[i].eval()
        return ensemble

    def _run_episodes_ppo(self, ppo, env, n_episodes: int) -> dict:
        """Run N evaluation episodes with PPO, return the best one."""
        best = None
        for ep in range(n_episodes):
            obs, info = env.reset()
            initial_types = env.initial_types.copy()
            initial_slope = float(env.avg_farmland_slope)
            initial_cont = float(env.contiguity)
            total_reward = 0.0
            done = False

            while not done:
                mask = env.action_masks()
                action, _ = ppo.predict(obs, deterministic=True, action_masks=mask)
                obs, reward, terminated, truncated, info = env.step(int(action))
                total_reward += reward
                done = terminated or truncated

            final_types = env.land_use.copy()
            result = self._package_result(ep, total_reward, env, initial_types,
                                          initial_slope, initial_cont, final_types)
            if best is None or total_reward > best["total_reward"]:
                best = result
            logger.info("PPO ep %d/%d: reward=%.4f swaps=%d",
                        ep + 1, n_episodes, total_reward, env.budget_used)
        return best

    def _run_episodes_mpc(self, ensemble, env, n_episodes: int) -> dict:
        """Run N evaluation episodes with contrastive MPC, return the best one."""
        if "D:\\test" not in sys.path:
            sys.path.insert(0, "D:\\test")
        from mpc_planner import mpc_select_action

        best = None
        for ep in range(n_episodes):
            obs, info = env.reset(seed=ep)
            initial_types = env.initial_types.copy()
            initial_slope = float(env.avg_farmland_slope)
            initial_cont = float(env.contiguity)
            rng = np.random.default_rng(ep)
            total_reward = 0.0

            for step in range(env.max_steps):
                bf = env._get_block_features()
                gf = env._get_global_features()
                mask = env.action_masks()
                action, _ = mpc_select_action(
                    ensemble, bf, gf, mask,
                    horizon=5, top_k=50, gamma=0.99,
                    n_rollouts=1, continuation="greedy",
                    greedy_sample=50, scoring="reward",
                    rng=rng,
                )
                obs, reward, terminated, truncated, info = env.step(action)
                total_reward += reward
                if terminated or truncated:
                    break

            final_types = env.land_use.copy()
            result = self._package_result(ep, total_reward, env, initial_types,
                                          initial_slope, initial_cont, final_types)
            if best is None or total_reward > best["total_reward"]:
                best = result
            logger.info("MPC ep %d/%d: reward=%.4f swaps=%d slope_pct=%.3f",
                        ep + 1, n_episodes, total_reward, env.budget_used,
                        (env.avg_farmland_slope - initial_slope) / initial_slope * 100)
        return best

    def _package_result(self, ep, total_reward, env, initial_types,
                        initial_slope, initial_cont, final_types) -> dict:
        return {
            "episode": ep,
            "total_reward": total_reward,
            "n_swaps": int(env.budget_used),
            "initial_slope": initial_slope,
            "final_slope": float(env.avg_farmland_slope),
            "slope_improvement": initial_slope - float(env.avg_farmland_slope),
            "initial_contiguity": initial_cont,
            "final_contiguity": float(env.contiguity),
            "contiguity_improvement": float(env.contiguity) - initial_cont,
            "initial_types": initial_types,
            "final_types": final_types,
        }
    def _generate_geojson_layers(self, env, initial_types, final_types) -> tuple:
        """Generate before/after/diff geometry files for the map.

        Optimizations:
          - geometry simplified (tolerance ≈ 1 m in EPSG:4326) — lossless for
            planning-scale visuals
          - coordinates quantized to 6 decimals (~11 cm) via shapely.set_precision
          - written as FlatGeobuf (binary, spatially-indexed, ~10× smaller than
            GeoJSON and streamable on the frontend)

        Layers:
          - before: original DLMC classification (Opt_Type = initial_types)
          - after:  optimized Opt_Type (from final_types) + Change_Type
          - diff:   only parcels where Change_Type > 0
        """
        import geopandas as gpd
        import shapely

        from .user_context import current_user_id
        uid = current_user_id.get("admin")
        upload_dir = os.path.join(os.path.dirname(__file__), "uploads", uid)
        os.makedirs(upload_dir, exist_ok=True)

        if "D:\\test" not in sys.path:
            sys.path.insert(0, "D:\\test")
        from county_env import DLTB_PATH, TOWNSHIP_CODES, FARMLAND_PREFIXES, FOREST_PREFIXES

        where_clause = " OR ".join(
            [f"QSDWDM LIKE '{code}%'" for code in TOWNSHIP_CODES]
        )
        gdf = gpd.read_file(DLTB_PATH, where=where_clause)

        def _classify(dlbm):
            if dlbm.startswith(FARMLAND_PREFIXES):
                return 1
            elif dlbm.startswith(FOREST_PREFIXES):
                return 2
            return 0

        gdf["type_code"] = gdf["DLBM"].apply(_classify)
        gdf_swap = gdf[gdf["type_code"].isin([1, 2])].copy().reset_index(drop=True)

        # Reproject to WGS84, simplify, quantize precision — do it ONCE, reuse for
        # before/after/diff (geometry is identical across the three layers).
        gdf_swap = gdf_swap.to_crs(epsg=4326)
        gdf_swap["geometry"] = gdf_swap.geometry.simplify(
            tolerance=1e-5, preserve_topology=True
        )
        # shapely.set_precision quantizes coords to a grid (1e-6 deg ≈ 11 cm)
        gdf_swap["geometry"] = shapely.set_precision(
            gdf_swap.geometry.values, grid_size=1e-6
        )

        attr_cols = [c for c in ("DLMC", "DLBM", "Slope", "Shape_Area") if c in gdf_swap.columns]

        initial_types = np.asarray(initial_types, dtype=np.int32)
        final_types = np.asarray(final_types, dtype=np.int32)
        assert len(initial_types) == len(gdf_swap), (
            f"initial_types length {len(initial_types)} != swap rows {len(gdf_swap)}"
        )

        change = np.zeros(len(gdf_swap), dtype=int)
        change[(initial_types == 1) & (final_types == 2)] = 1
        change[(initial_types == 2) & (final_types == 1)] = 2

        # Attach type columns BEFORE dropping empty geometries — this preserves
        # the row-to-type alignment regardless of simplification side effects.
        gdf_swap["_initial_type"] = initial_types
        gdf_swap["_final_type"] = final_types
        gdf_swap["_change_type"] = change

        # Drop any features whose geometry became empty after simplification
        n_before = len(gdf_swap)
        gdf_swap = gdf_swap[~gdf_swap.geometry.is_empty].reset_index(drop=True)
        if len(gdf_swap) != n_before:
            logger.info(
                "WM v2: dropped %d empty geoms after simplification (kept %d)",
                n_before - len(gdf_swap), len(gdf_swap),
            )

        import uuid
        tag = uuid.uuid4().hex[:8]

        # before layer
        gdf_before = gdf_swap[["geometry", *attr_cols]].copy()
        gdf_before["Opt_Type"] = gdf_swap["_initial_type"].values
        before_path = os.path.join(upload_dir, f"wm_v2_before_{tag}.fgb")
        gdf_before.to_file(before_path, driver="FlatGeobuf")

        # after layer (with Change_Type for tooltip)
        gdf_after = gdf_swap[["geometry", *attr_cols]].copy()
        gdf_after["Opt_Type"] = gdf_swap["_final_type"].values
        gdf_after["Change_Type"] = gdf_swap["_change_type"].values
        opt_path = os.path.join(upload_dir, f"wm_v2_optimized_{tag}.fgb")
        gdf_after.to_file(opt_path, driver="FlatGeobuf")

        # diff layer (sparse — typically a few hundred parcels, trivial size)
        gdf_diff = gdf_after[gdf_after["Change_Type"] > 0].copy()
        diff_path = os.path.join(upload_dir, f"wm_v2_diff_{tag}.fgb")
        gdf_diff.to_file(diff_path, driver="FlatGeobuf")

        return before_path, opt_path, diff_path

    def _build_map_config(self, before_path: str, opt_path: str, diff_path: str) -> dict:
        # Only types 1 (farmland) and 2 (forest) ever appear in these layers —
        # non-swappable parcels (type 0) are filtered out in _generate_geojson_layers.
        landuse_style = {
            "1": {"fillColor": "#FFD700", "color": "#FFD700", "fillOpacity": 0.7, "weight": 0.3},
            "2": {"fillColor": "#228B22", "color": "#228B22", "fillOpacity": 0.7, "weight": 0.3},
        }
        return {
            "layers": [
                {
                    "name": "优化前现状 (Before)",
                    "type": "fgb",
                    "fgb": os.path.basename(before_path),
                    "category_column": "Opt_Type",
                    "style_map": landuse_style,
                    "visible": False,
                },
                {
                    "name": "优化后布局 (After)",
                    "type": "fgb",
                    "fgb": os.path.basename(opt_path),
                    "category_column": "Opt_Type",
                    "style_map": landuse_style,
                    "visible": True,
                },
                {
                    "name": "空间置换差异 (Changes)",
                    "type": "fgb",
                    "fgb": os.path.basename(diff_path),
                    "category_column": "Change_Type",
                    "style_map": {
                        "1": {"fillColor": "#FF4500", "color": "#FF4500", "fillOpacity": 0.85, "weight": 0.6},
                        "2": {"fillColor": "#1E90FF", "color": "#1E90FF", "fillOpacity": 0.85, "weight": 0.6},
                    },
                    "visible": True,
                },
            ],
            "center": [29.59, 106.22],
            "zoom": 12,
        }
