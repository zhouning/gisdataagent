"""Resumable DAgger + Ensemble experiment runner.

Runs 5 seeds x 3 DAgger iterations using a 5-member transition-model ensemble
with disagreement penalty, saving progress after every seed/iteration.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import sys
import time
from pathlib import Path

import numpy as np
import torch

from stable_baselines3.common.callbacks import BaseCallback

torch.distributions.Distribution.set_default_validate_args(False)

ROOT_TEST = r"D:/test"
if ROOT_TEST not in sys.path:
    sys.path.insert(0, ROOT_TEST)

from county_env import CountyLevelEnv
from parcel_scoring_policy import ParcelScoringPolicy
from sb3_contrib import MaskablePPO

from data_agent.transition_model import (
    EnsembleBlockEnv,
    EnsembleTransitionModel,
    TrajectoryCollector,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

RESULTS_DIR = os.getenv("PAPER9_RESULTS_DIR", "D:/adk/results_dual_dreamer_real")
OUT_DIR = Path(RESULTS_DIR)
OUT_DIR.mkdir(parents=True, exist_ok=True)
PROGRESS_PATH = OUT_DIR / "dagger_ensemble_progress.json"
FINAL_PATH = OUT_DIR / "dagger_ensemble_results.json"

BASE_TRAJ = Path(os.getenv("PAPER9_BASE_TRAJ", "D:/adk/results_dual_dreamer_real/trajectories_6k.npz"))

PENALTY_SCHEDULE = {0: 0.5, 1: 0.5, 2: 0.5}
RETRY_PENALTY_SCHEDULE = {0: 0.5, 1: 0.5, 2: 0.5}
N_ENSEMBLE = 5
EPOCHS = 30
TOTAL_TIMESTEPS = 50_000
EVAL_INTERVAL = 10_000
FAST_EVAL_EPISODES = 3
FINAL_EVAL_EPISODES = 10
ITER1_REWARD_DROP_THRESHOLD = 50.0
DISAGREEMENT_THRESHOLD = 2.0
DISAGREEMENT_FILTER = 0.5
MIN_DREAM_STEPS = 20


def load_progress() -> dict:
    if PROGRESS_PATH.exists():
        return json.loads(PROGRESS_PATH.read_text(encoding="utf-8"))
    return {
        "config": {
            "penalty_schedule": PENALTY_SCHEDULE,
            "n_ensemble": N_ENSEMBLE,
            "eval_interval": EVAL_INTERVAL,
            "disagreement_threshold": DISAGREEMENT_THRESHOLD,
            "disagreement_filter": DISAGREEMENT_FILTER,
            "min_dream_steps": MIN_DREAM_STEPS,
        },
        "seeds": {},
        "aggregate": {},
    }


def save_progress(progress: dict) -> None:
    PROGRESS_PATH.write_text(json.dumps(progress, indent=2, ensure_ascii=False), encoding="utf-8")


def aggregate(progress: dict) -> dict:
    agg = {}
    seeds = progress.get("seeds", {})
    for it in range(3):
        rewards, slopes = [], []
        for seed_str, seed_results in seeds.items():
            if len(seed_results) > it:
                rewards.append(seed_results[it]["reward"])
                slopes.append(seed_results[it]["slope_pct"])
        if rewards:
            agg[f"iter{it}"] = {
                "mean_reward": round(float(np.mean(rewards)), 2),
                "std_reward": round(float(np.std(rewards)), 2),
                "mean_slope": round(float(np.mean(slopes)), 4),
                "std_slope": round(float(np.std(slopes)), 4),
                "all_rewards": [round(float(r), 2) for r in rewards],
                "all_slopes": [round(float(s), 4) for s in slopes],
                "n_positive": sum(1 for r in rewards if r > 0),
            }
    return agg


def load_seed_dataset(seed: int) -> TrajectoryCollector:
    seed_path = OUT_DIR / f"dagger_ensemble_seed{seed}_dataset.npz"
    collector = TrajectoryCollector()
    if seed_path.exists():
        collector.load(str(seed_path))
    else:
        collector.load(str(BASE_TRAJ))
    return collector


def save_seed_dataset(seed: int, collector: TrajectoryCollector) -> None:
    seed_path = OUT_DIR / f"dagger_ensemble_seed{seed}_dataset.npz"
    collector.save(str(seed_path))


def clone_collector(collector: TrajectoryCollector) -> TrajectoryCollector:
    cloned = TrajectoryCollector()
    cloned.block_features = list(collector.block_features)
    cloned.global_features = list(collector.global_features)
    cloned.actions = list(collector.actions)
    cloned.rewards = list(collector.rewards)
    cloned.next_block_features = list(collector.next_block_features)
    cloned.next_global_features = list(collector.next_global_features)
    return cloned


def quick_eval_policy(ppo: MaskablePPO, real_env: CountyLevelEnv, n_episodes: int) -> dict:
    rewards, slopes, conts = [], [], []
    for _ in range(n_episodes):
        obs, info = real_env.reset()
        total_reward = 0.0
        slope0 = info["avg_slope"]
        cont0 = info["contiguity"]
        for _step in range(100):
            action, _ = ppo.predict(obs, deterministic=True, action_masks=real_env.action_masks())
            obs, reward, term, trunc, info = real_env.step(int(action))
            total_reward += reward
            if term or trunc:
                break
        slope1 = info.get("avg_slope", slope0)
        cont1 = info.get("contiguity", cont0)
        rewards.append(total_reward)
        slopes.append((slope1 - slope0) / slope0 * 100)
        conts.append(cont1 - cont0)
    return {
        "reward": float(np.mean(rewards)),
        "slope_pct": float(np.mean(slopes)),
        "cont_delta": float(np.mean(conts)),
        "n_positive_eval": sum(1 for r in rewards if r > 0),
    }


class PeriodicRealEvalCallback(BaseCallback):
    def __init__(self, real_env: CountyLevelEnv, seed: int, iteration: int, interval: int = EVAL_INTERVAL):
        super().__init__(verbose=0)
        self.real_env = real_env
        self.seed = seed
        self.iteration = iteration
        self.interval = interval
        self.best_reward = -float("inf")
        self.best_step = 0
        self.best_metrics: dict | None = None
        self.best_path = OUT_DIR / f"dagger_ensemble_seed{seed}_iter{iteration}_best.zip"
        self._last_eval = 0

    def _on_step(self) -> bool:
        if (self.num_timesteps - self._last_eval) < self.interval:
            return True
        self._last_eval = self.num_timesteps
        metrics = quick_eval_policy(self.model, self.real_env, FAST_EVAL_EPISODES)
        if metrics["reward"] > self.best_reward:
            self.best_reward = metrics["reward"]
            self.best_step = self.num_timesteps
            self.best_metrics = metrics
            self.model.save(str(self.best_path))
            logger.info(
                "Seed %d Iter %d new best checkpoint at step %d: reward=%.2f slope=%.4f%%",
                self.seed, self.iteration, self.num_timesteps,
                metrics["reward"], metrics["slope_pct"],
            )
        return True


def run_iteration(
    seed: int,
    iteration: int,
    collector: TrajectoryCollector,
    real_env: CountyLevelEnv,
    penalty_weight: float,
) -> tuple[dict, str | None]:
    data = collector.as_arrays()
    n_blocks = real_env.n_blocks
    n_data = len(data["actions"])

    logger.info(
        "Seed %d Iter %d: training %d-model ensemble on %d transitions (lambda=%.2f)",
        seed, iteration, N_ENSEMBLE, n_data, penalty_weight,
    )
    t0 = time.time()
    ensemble = EnsembleTransitionModel(n_blocks, n_models=N_ENSEMBLE)
    histories = ensemble.train_all(data, epochs=EPOCHS, lr=1e-3, patience=6, min_delta=1e-4)
    ens_time = time.time() - t0
    cos_vals = [h["cosine_sim"][-1] for h in histories]
    best_epochs = [h.get("best_epoch") for h in histories if h.get("best_epoch") is not None]

    dream_env = EnsembleBlockEnv(
        ensemble, data, max_steps=100,
        reward_scale=1.577, reward_clip=10.0,
        noise_std=0.02, penalty_weight=penalty_weight,
        disagreement_threshold=DISAGREEMENT_THRESHOLD,
        min_steps=MIN_DREAM_STEPS,
    )
    ppo = MaskablePPO(
        ParcelScoringPolicy,
        dream_env,
        learning_rate=3e-4,
        n_steps=128,
        gamma=0.995,
        batch_size=64,
        n_epochs=4,
        verbose=0,
        seed=seed * 10 + iteration,
        policy_kwargs=dict(k_parcel=17, k_global=12, scorer_hiddens=[64, 32], value_hiddens=[64, 32]),
    )
    callback = PeriodicRealEvalCallback(real_env, seed, iteration)
    t1 = time.time()
    ppo.learn(total_timesteps=TOTAL_TIMESTEPS, callback=callback)
    policy_time = time.time() - t1

    dream_ep_lengths = dream_env._episode_lengths
    avg_dream_len = float(np.mean(dream_ep_lengths)) if dream_ep_lengths else 100.0
    n_early_trunc = dream_env._n_early_truncated

    final_path = OUT_DIR / f"dagger_ensemble_seed{seed}_iter{iteration}.zip"
    ppo.save(str(final_path))
    best_checkpoint_path: str | None = None
    if callback.best_path.exists():
        best_checkpoint_path = str(callback.best_path)
        ppo = MaskablePPO.load(best_checkpoint_path, env=dream_env)

    metrics = quick_eval_policy(ppo, real_env, FINAL_EVAL_EPISODES)
    result = {
        "iter": iteration,
        "n_data": n_data,
        "lambda_used": round(float(penalty_weight), 3),
        "cos_sim_min": round(float(min(cos_vals)), 6),
        "cos_sim_max": round(float(max(cos_vals)), 6),
        "reward": round(float(metrics["reward"]), 2),
        "slope_pct": round(float(metrics["slope_pct"]), 4),
        "cont_delta": round(float(metrics["cont_delta"]), 4),
        "ensemble_time_s": round(float(ens_time), 0),
        "policy_time_s": round(float(policy_time), 0),
        "n_positive_eval": int(metrics["n_positive_eval"]),
        "best_eval_reward": round(float(callback.best_reward), 2) if callback.best_metrics else None,
        "best_eval_step": int(callback.best_step) if callback.best_step else None,
        "best_checkpoint_path": best_checkpoint_path,
        "avg_best_epoch": round(float(np.mean(best_epochs)), 2) if best_epochs else None,
        "early_stopped_members": int(sum(1 for h in histories if h.get("early_stopped"))),
        "avg_dream_episode_length": round(avg_dream_len, 1),
        "n_early_truncated_episodes": n_early_trunc,
        "candidate_status": "candidate",
        "accepted_status": "accepted",
        "rollback_applied": False,
        "rollback_reason": None,
    }
    logger.info(
        "Seed %d Iter %d result: reward=%.2f slope=%.4f%% best_step=%s",
        seed, iteration, result["reward"], result["slope_pct"], result["best_eval_step"],
    )

    n_total_onpolicy = 0
    n_filtered_onpolicy = 0
    if iteration < 2:
        for _ep in range(10):
            obs, _ = real_env.reset()
            done = False
            while not done:
                bf = obs[: n_blocks * 17].reshape(n_blocks, 17)
                gf = obs[n_blocks * 17 :]
                action, _ = ppo.predict(obs, deterministic=False, action_masks=real_env.action_masks())
                action = int(action)
                next_obs, reward, term, trunc, _ = real_env.step(action)
                nbf = next_obs[: n_blocks * 17].reshape(n_blocks, 17)
                ngf = next_obs[n_blocks * 17 :]
                n_total_onpolicy += 1
                _, _, _, r_std = ensemble.predict(bf, gf, action)
                if r_std >= DISAGREEMENT_FILTER:
                    collector.block_features.append(bf.astype(np.float32))
                    collector.global_features.append(gf.astype(np.float32))
                    collector.actions.append(action)
                    collector.rewards.append(reward)
                    collector.next_block_features.append(nbf.astype(np.float32))
                    collector.next_global_features.append(ngf.astype(np.float32))
                    n_filtered_onpolicy += 1
                obs = next_obs
                done = term or trunc

    result["n_total_onpolicy"] = n_total_onpolicy
    result["n_filtered_onpolicy"] = n_filtered_onpolicy
    result["filter_ratio"] = round(n_filtered_onpolicy / max(n_total_onpolicy, 1), 4)

    return result, best_checkpoint_path


def main() -> None:
    progress = load_progress()
    real_env = CountyLevelEnv()
    seed_env = os.getenv("PAPER9_SEEDS", "1,2,3,4,5")
    seeds = [int(x.strip()) for x in seed_env.split(",") if x.strip()]

    for seed in seeds:
        key = str(seed)
        seed_results = progress["seeds"].get(key, [])
        collector = load_seed_dataset(seed)
        logger.info("Seed %d starting with %d completed iterations, dataset size %d", seed, len(seed_results), collector.size)

        for iteration in range(len(seed_results), 3):
            accepted_collector = clone_collector(collector)
            accepted_results = list(seed_results)
            penalty_weight = PENALTY_SCHEDULE.get(iteration, PENALTY_SCHEDULE[max(PENALTY_SCHEDULE)])
            result, _ = run_iteration(seed, iteration, collector, real_env, penalty_weight)

            should_retry = False
            if iteration == 1 and seed_results:
                prev_reward = seed_results[0]["reward"]
                if result["reward"] < (prev_reward - ITER1_REWARD_DROP_THRESHOLD):
                    should_retry = True
                    result["candidate_status"] = "rejected"
                    result["accepted_status"] = "rolled_back"
                    result["rollback_applied"] = True
                    result["rollback_reason"] = (
                        f"iter1_reward_drop_{result['reward']:.2f}_vs_{prev_reward:.2f}"
                    )
                    logger.info(
                        "Seed %d Iter 1 rollback triggered: reward %.2f vs iter0 %.2f",
                        seed, result["reward"], prev_reward,
                    )

            if should_retry:
                collector = clone_collector(accepted_collector)
                retry_penalty = RETRY_PENALTY_SCHEDULE.get(iteration, penalty_weight)
                retry_result, _ = run_iteration(seed, iteration, collector, real_env, retry_penalty)
                retry_result["lambda_used"] = round(float(retry_penalty), 3)
                retry_result["rollback_applied"] = True
                retry_result["rollback_reason"] = result["rollback_reason"]
                retry_result["candidate_status"] = "retry_candidate"
                retry_result["accepted_status"] = "accepted"
                result = retry_result

            seed_results = accepted_results + [result]
            progress["seeds"][key] = seed_results
            progress["aggregate"] = aggregate(progress)
            save_seed_dataset(seed, collector)
            save_progress(progress)

    progress["aggregate"] = aggregate(progress)
    FINAL_PATH.write_text(json.dumps(progress, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Saved final results to %s", FINAL_PATH)
    print(json.dumps(progress["aggregate"], indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()