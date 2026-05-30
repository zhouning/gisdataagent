"""Resumable 5-seed DAgger experiment runner.

Runs 5 seeds x 3 DAgger iterations and saves progress after each seed so the
experiment can be safely paused/resumed.
"""

from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path

import numpy as np
import torch

# Large discrete action spaces trigger Categorical validation failures
torch.distributions.Distribution.set_default_validate_args(False)

ROOT_TEST = r"D:/test"
if ROOT_TEST not in sys.path:
    sys.path.insert(0, ROOT_TEST)

from county_env import CountyLevelEnv
from parcel_scoring_policy import ParcelScoringPolicy
from sb3_contrib import MaskablePPO

from data_agent.transition_model import (
    LearnedBlockEnv,
    TrajectoryCollector,
    TransitionModel,
    TransitionModelTrainer,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

OUT_DIR = Path("D:/adk/results_dual_dreamer_real")
OUT_DIR.mkdir(parents=True, exist_ok=True)
PROGRESS_PATH = OUT_DIR / "dagger_5seeds_progress.json"
FINAL_PATH = OUT_DIR / "dagger_5seeds_final.json"


def load_progress() -> dict:
    if PROGRESS_PATH.exists():
        return json.loads(PROGRESS_PATH.read_text(encoding="utf-8"))
    return {"seeds": {}, "aggregate": {}}


def save_progress(progress: dict) -> None:
    PROGRESS_PATH.write_text(json.dumps(progress, indent=2, ensure_ascii=False), encoding="utf-8")


def aggregate(progress: dict) -> dict:
    agg = {}
    seeds = progress.get("seeds", {})
    for it in range(3):
        rewards = []
        slopes = []
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
            }
    if "iter2" in agg and len(agg["iter2"]["all_rewards"]) == 5:
        from scipy.stats import mannwhitneyu
        greedy = [5.51] * 5
        stat, p = mannwhitneyu(agg["iter2"]["all_rewards"], greedy, alternative="greater")
        agg["mann_whitney_iter2_vs_greedy"] = {"U": round(float(stat), 2), "p": round(float(p), 4)}
    return agg


def run_seed(seed: int, real_env: CountyLevelEnv) -> list[dict]:
    base = TrajectoryCollector()
    base.load(str(OUT_DIR / "trajectories_6k.npz"))
    n_blocks = real_env.n_blocks
    results = []

    for iteration in range(3):
        data = base.as_arrays()
        n_data = len(data["actions"])

        tm = TransitionModel(n_blocks)
        trainer = TransitionModelTrainer(tm, lr=1e-3, epochs=30)
        history = trainer.train(data)
        cos_sim = history["cosine_sim"][-1]

        tm.eval()
        dream_env = LearnedBlockEnv(
            tm,
            data,
            max_steps=100,
            reward_scale=1.577,
            reward_clip=10.0,
            state_reset_interval=20,
            noise_std=0.02,
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
        t0 = time.time()
        ppo.learn(total_timesteps=50_000)
        dream_time = time.time() - t0
        ppo.save(str(OUT_DIR / f"dagger_seed{seed}_iter{iteration}.zip"))

        rewards = []
        slopes = []
        conts = []
        for _ in range(10):
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

        result = {
            "iter": iteration,
            "n_data": n_data,
            "cos_sim": round(float(cos_sim), 6),
            "reward": round(float(np.mean(rewards)), 2),
            "slope_pct": round(float(np.mean(slopes)), 4),
            "cont_delta": round(float(np.mean(conts)), 4),
            "time_s": round(float(dream_time), 0),
        }
        logger.info("Seed %d Iter %d: data=%d reward=%.2f slope=%.4f%%", seed, iteration, n_data, result["reward"], result["slope_pct"])
        results.append(result)

        if iteration < 2:
            for _ep in range(10):
                obs, _ = real_env.reset()
                done = False
                while not done:
                    bf = obs[: n_blocks * 17].reshape(n_blocks, 17)
                    gf = obs[n_blocks * 17 :]
                    action, _ = ppo.predict(obs, deterministic=False, action_masks=real_env.action_masks())
                    action = int(action)
                    next_obs, reward, term, trunc, _info = real_env.step(action)
                    nbf = next_obs[: n_blocks * 17].reshape(n_blocks, 17)
                    ngf = next_obs[n_blocks * 17 :]
                    base.block_features.append(bf.astype(np.float32))
                    base.global_features.append(gf.astype(np.float32))
                    base.actions.append(action)
                    base.rewards.append(reward)
                    base.next_block_features.append(nbf.astype(np.float32))
                    base.next_global_features.append(ngf.astype(np.float32))
                    obs = next_obs
                    done = term or trunc

    return results


def main() -> None:
    progress = load_progress()
    real_env = CountyLevelEnv()

    for seed in [1, 2, 3, 4, 5]:
        key = str(seed)
        if key in progress["seeds"] and len(progress["seeds"][key]) == 3:
            logger.info("Skip seed %d: already complete", seed)
            continue
        logger.info("Running seed %d", seed)
        progress["seeds"][key] = run_seed(seed, real_env)
        progress["aggregate"] = aggregate(progress)
        save_progress(progress)

    progress["aggregate"] = aggregate(progress)
    FINAL_PATH.write_text(json.dumps(progress, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Saved final results to %s", FINAL_PATH)
    print(json.dumps(progress["aggregate"], indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
