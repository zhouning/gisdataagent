"""
Phase 1 Validation: World Model Prediction Quality Assessment
==============================================================

Answers 4 critical questions from the advisor:
1. Embedding accuracy: How close are predicted embeddings to actual? (cosine sim, MSE)
2. Baseline comparison: Does the model beat naive persistence (copy last year)?
3. Multi-step degradation: How does quality decay over 1/2/3/.../6 steps?
4. Spatial generalization: Does it work on unseen regions (OOD)?

Experimental design:
- Temporal holdout: Train on 2017-2022, predict 2023+2024, compare with ground truth
- Spatial holdout: Train on 2 regions, test on 3rd + 2 completely new regions
- Baselines: Persistence (z_{t+1} = z_t), Linear extrapolation (z_{t+1} = 2*z_t - z_{t-1})
- Metrics: Cosine similarity, MSE, L2 distance (per-pixel, averaged)
- Data: 500 random point samples per area per year (same as Phase 0)

Usage:
    python scripts/phase1_validation.py
"""

import sys
import io
import os

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import json
import time
import logging
import numpy as np
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger(__name__)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

OUTPUT_DIR = Path("scripts/phase1_results")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

N_POINTS = 500  # samples per area per year
SEED = 42

# Areas: 2 for training, 1 holdout, 2 completely OOD
TRAINING_AREAS = [
    {"name": "yangtze_delta", "bbox": [121.2, 31.0, 121.3, 31.1]},
    {"name": "northeast_plain", "bbox": [126.5, 45.7, 126.6, 45.8]},
]
HOLDOUT_AREA = {"name": "yunnan_eco", "bbox": [100.2, 25.0, 100.3, 25.1]}
OOD_AREAS = [
    {"name": "jing_jin_ji", "bbox": [116.3, 39.8, 116.4, 39.9]},
    {"name": "pearl_river", "bbox": [113.2, 23.0, 113.3, 23.1]},
]

TRAIN_YEARS = list(range(2017, 2023))  # 2017-2022
ALL_YEARS = list(range(2017, 2025))    # 2017-2024


# ====================================================================
# Data loading (point samples, cached as .npy)
# ====================================================================

CACHE_DIR = Path("data_agent/weights/raw_data")
CACHE_DIR.mkdir(parents=True, exist_ok=True)


def load_or_fetch_points(area_name: str, bbox: list, year: int) -> np.ndarray | None:
    """Load point embeddings from cache or GEE. Returns [N, 64]."""
    cache_path = CACHE_DIR / f"pts_{area_name}_{year}.npy"
    if cache_path.exists():
        return np.load(cache_path)

    from data_agent.world_model import sample_embeddings_as_points
    pts = sample_embeddings_as_points(bbox, year, n_points=N_POINTS, seed=SEED)
    if pts is not None:
        np.save(cache_path, pts)
        logger.info("  Saved %s %d -> %s  shape=%s", area_name, year, cache_path, pts.shape)
    return pts


def download_all_points():
    """Download/cache point embeddings for all areas x all years."""
    print("Downloading/loading point embeddings...")
    all_data = {}
    all_areas = TRAINING_AREAS + [HOLDOUT_AREA] + OOD_AREAS
    for area in all_areas:
        name = area["name"]
        all_data[name] = {}
        for year in ALL_YEARS:
            pts = load_or_fetch_points(name, area["bbox"], year)
            if pts is not None:
                all_data[name][year] = pts
        n = len(all_data[name])
        print(f"  {name}: {n} years, {all_data[name].get(2020, np.empty(0)).shape[0] if 2020 in all_data[name] else '?'} points/year")
    return all_data


# ====================================================================
# Metrics
# ====================================================================


def compute_metrics(z_pred: np.ndarray, z_true: np.ndarray) -> dict:
    """Compute per-pixel metrics between two [N, 64] arrays."""
    n = min(len(z_pred), len(z_true))
    z_pred, z_true = z_pred[:n], z_true[:n]

    # L2 normalize for cos_sim
    pred_n = z_pred / (np.linalg.norm(z_pred, axis=1, keepdims=True) + 1e-10)
    true_n = z_true / (np.linalg.norm(z_true, axis=1, keepdims=True) + 1e-10)

    cos_sim = np.sum(pred_n * true_n, axis=1)
    mse = np.mean((z_pred - z_true) ** 2, axis=1)
    l2 = np.linalg.norm(z_pred - z_true, axis=1)

    return {
        "cos_sim_mean": float(np.mean(cos_sim)),
        "cos_sim_std": float(np.std(cos_sim)),
        "cos_sim_p05": float(np.percentile(cos_sim, 5)),
        "cos_sim_p50": float(np.median(cos_sim)),
        "mse_mean": float(np.mean(mse)),
        "l2_mean": float(np.mean(l2)),
        "l2_std": float(np.std(l2)),
        "n": n,
    }


# ====================================================================
# Model prediction on point samples
# ====================================================================


def predict_points_1step(z_t: np.ndarray, scenario: str = "baseline") -> np.ndarray:
    """Run world model 1-step prediction on point vectors [N, 64] -> [N, 64]."""
    import torch
    from data_agent.world_model import _load_model, encode_scenario

    model = _load_model()
    s = encode_scenario(scenario)

    # Points -> pseudo-grid [1, 64, 1, N] for Conv2d compatibility
    z = torch.tensor(z_t.T[np.newaxis, :, np.newaxis, :]).float()  # [1, 64, 1, N]
    s_batch = s  # [1, 16]

    with torch.no_grad():
        z_next = model(z, s_batch)
        z_next = torch.nn.functional.normalize(z_next, p=2, dim=1)

    # Back to [N, 64]
    return z_next.squeeze(0).squeeze(1).numpy().T  # [N, 64]


def predict_points_nsteps(z_start: np.ndarray, n_steps: int, scenario: str = "baseline") -> list[np.ndarray]:
    """Run N autoregressive steps. Returns list of [N, 64] predictions."""
    import torch
    from data_agent.world_model import _load_model, encode_scenario

    model = _load_model()
    s = encode_scenario(scenario)

    z = torch.tensor(z_start.T[np.newaxis, :, np.newaxis, :]).float()
    results = []

    with torch.no_grad():
        for _ in range(n_steps):
            z = model(z, s)
            z = torch.nn.functional.normalize(z, p=2, dim=1)
            z_np = z.squeeze(0).squeeze(1).numpy().T
            results.append(z_np)

    return results


# ====================================================================
# Training on subset
# ====================================================================


def train_on_subset(all_data):
    """Train model on TRAINING_AREAS x TRAIN_YEARS only."""
    import torch
    from data_agent.world_model import (
        _build_model, encode_scenario, WEIGHTS_DIR, Z_DIM, SCENARIO_DIM
    )
    import data_agent.world_model as wm

    print("\n" + "=" * 60)
    print("  Training on subset: 2 areas x 5 year-pairs (2017-2022)")
    print("=" * 60)

    s_baseline = encode_scenario("baseline")

    # Build training pairs from point data
    z_t_list, z_tp1_list = [], []
    for area in TRAINING_AREAS:
        name = area["name"]
        for i in range(len(TRAIN_YEARS) - 1):
            y1, y2 = TRAIN_YEARS[i], TRAIN_YEARS[i + 1]
            if y1 in all_data[name] and y2 in all_data[name]:
                z_t_list.append(all_data[name][y1])    # [N, 64]
                z_tp1_list.append(all_data[name][y2])   # [N, 64]

    print(f"  Training pairs: {len(z_t_list)} (x {z_t_list[0].shape[0]} points each)")

    model = _build_model(Z_DIM, SCENARIO_DIM)
    optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)
    mse_loss = torch.nn.MSELoss()

    model.train()
    for epoch in range(80):
        epoch_loss = 0.0
        for z_t_np, z_tp1_np in zip(z_t_list, z_tp1_list):
            # [1, 64, 1, N] pseudo-grid
            z_t = torch.tensor(z_t_np.T[np.newaxis, :, np.newaxis, :]).float()
            z_tp1_true = torch.tensor(z_tp1_np.T[np.newaxis, :, np.newaxis, :]).float()
            s = s_baseline

            z_tp1_pred = model(z_t, s)
            z_tp1_pred = torch.nn.functional.normalize(z_tp1_pred, p=2, dim=1)
            z_tp1_true_n = torch.nn.functional.normalize(z_tp1_true, p=2, dim=1)
            loss = mse_loss(z_tp1_pred, z_tp1_true_n)

            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
            epoch_loss += loss.item()

        avg = epoch_loss / len(z_t_list)
        if (epoch + 1) % 20 == 0:
            print(f"  Epoch {epoch+1}/80  loss={avg:.6f}")

    model.eval()
    wm._CACHED_MODEL = model

    # Save
    val_path = os.path.join(WEIGHTS_DIR, "latent_dynamics_val.pt")
    torch.save({
        "model_state_dict": model.state_dict(),
        "z_dim": Z_DIM, "scenario_dim": SCENARIO_DIM,
        "version": "val-1.0",
    }, val_path)
    print(f"  Saved: {val_path}")
    return True


# ====================================================================
# Experiments
# ====================================================================


def exp1_temporal_holdout(all_data):
    """Train 2017-2022, test 2023/2024 on training areas."""
    print("\n" + "=" * 60)
    print("  Exp 1: Temporal Holdout (train 2017-2022, test 2023/2024)")
    print("=" * 60)

    results = {}
    for area in TRAINING_AREAS + [HOLDOUT_AREA]:
        name = area["name"]
        d = all_data.get(name, {})
        if 2022 not in d or 2023 not in d:
            continue

        z_2022 = d[2022]
        z_2023_true = d[2023]

        # 1-step model prediction
        z_2023_pred = predict_points_1step(z_2022)

        # Baselines
        z_2023_persist = z_2022.copy()  # persistence
        z_2021 = d.get(2021)
        z_2023_linear = 2 * z_2022 - z_2021 if z_2021 is not None else None

        m_model = compute_metrics(z_2023_pred, z_2023_true)
        m_persist = compute_metrics(z_2023_persist, z_2023_true)
        m_linear = compute_metrics(z_2023_linear, z_2023_true) if z_2023_linear is not None else None

        step1 = {"model": m_model, "persistence": m_persist}
        if m_linear:
            step1["linear"] = m_linear

        # 2-step if 2024 available
        step2 = None
        if 2024 in d:
            z_2024_true = d[2024]
            preds = predict_points_nsteps(z_2022, 2)
            m2_model = compute_metrics(preds[1], z_2024_true)
            m2_persist = compute_metrics(z_2022, z_2024_true)
            step2 = {"model": m2_model, "persistence": m2_persist}

        results[name] = {"1_step": step1}
        if step2:
            results[name]["2_step"] = step2

        # Print
        print(f"\n  {name} (1-step 2022->2023):")
        print(f"    Model:       cos_sim={m_model['cos_sim_mean']:.4f} +/- {m_model['cos_sim_std']:.4f}  L2={m_model['l2_mean']:.4f}")
        print(f"    Persistence: cos_sim={m_persist['cos_sim_mean']:.4f} +/- {m_persist['cos_sim_std']:.4f}  L2={m_persist['l2_mean']:.4f}")
        if m_linear:
            print(f"    Linear:      cos_sim={m_linear['cos_sim_mean']:.4f} +/- {m_linear['cos_sim_std']:.4f}  L2={m_linear['l2_mean']:.4f}")
        delta = m_model['cos_sim_mean'] - m_persist['cos_sim_mean']
        print(f"    Model vs Persist: {'+' if delta >= 0 else ''}{delta:.4f} cos_sim")

        if step2:
            print(f"  {name} (2-step 2022->2024):")
            print(f"    Model:       cos_sim={step2['model']['cos_sim_mean']:.4f}")
            print(f"    Persistence: cos_sim={step2['persistence']['cos_sim_mean']:.4f}")

    return results


def exp2_multistep_degradation(all_data):
    """How does quality degrade over 1-6 autoregressive steps?"""
    print("\n" + "=" * 60)
    print("  Exp 2: Multi-step Degradation (2017 -> 2018...2023)")
    print("=" * 60)

    results = {}
    for area in TRAINING_AREAS + [HOLDOUT_AREA]:
        name = area["name"]
        d = all_data.get(name, {})
        if 2017 not in d:
            continue

        z_start = d[2017]
        preds = predict_points_nsteps(z_start, 6)

        steps = []
        for step_i in range(len(preds)):
            target_year = 2018 + step_i
            if target_year not in d:
                break
            m_model = compute_metrics(preds[step_i], d[target_year])
            m_persist = compute_metrics(z_start, d[target_year])
            delta = m_model['cos_sim_mean'] - m_persist['cos_sim_mean']
            steps.append({
                "step": step_i + 1,
                "year": target_year,
                "model_cos": m_model['cos_sim_mean'],
                "persist_cos": m_persist['cos_sim_mean'],
                "advantage": delta,
            })
            print(f"  {name} step {step_i+1} (2017->{target_year}): "
                  f"model={m_model['cos_sim_mean']:.4f}  persist={m_persist['cos_sim_mean']:.4f}  "
                  f"delta={delta:+.4f}")

        results[name] = steps
    return results


def exp3_spatial_ood(all_data):
    """Test on completely unseen regions."""
    print("\n" + "=" * 60)
    print("  Exp 3: Spatial OOD (unseen regions)")
    print("=" * 60)

    results = {}
    for area in [HOLDOUT_AREA] + OOD_AREAS:
        name = area["name"]
        d = all_data.get(name, {})
        years_avail = sorted(d.keys())
        if len(years_avail) < 2:
            continue

        cos_model, cos_persist = [], []
        pairs = []
        for i in range(len(years_avail) - 1):
            y1, y2 = years_avail[i], years_avail[i + 1]
            z_pred = predict_points_1step(d[y1])
            m_model = compute_metrics(z_pred, d[y2])
            m_persist = compute_metrics(d[y1], d[y2])
            cos_model.append(m_model['cos_sim_mean'])
            cos_persist.append(m_persist['cos_sim_mean'])
            pairs.append({"y": f"{y1}->{y2}", "model": m_model['cos_sim_mean'], "persist": m_persist['cos_sim_mean']})

        avg_m = float(np.mean(cos_model))
        avg_p = float(np.mean(cos_persist))
        adv = avg_m - avg_p
        results[name] = {
            "pairs": pairs,
            "avg_model": avg_m,
            "avg_persist": avg_p,
            "advantage": adv,
        }

        is_training = name in [a["name"] for a in TRAINING_AREAS]
        tag = "TRAIN" if is_training else ("HOLDOUT" if name == HOLDOUT_AREA["name"] else "OOD")
        print(f"\n  {name} [{tag}]: {len(pairs)} pairs")
        print(f"    Model avg cos_sim:       {avg_m:.4f}")
        print(f"    Persistence avg cos_sim: {avg_p:.4f}")
        print(f"    Advantage:               {adv:+.4f} ({'BETTER' if adv > 0 else 'WORSE'})")

    return results


# ====================================================================
# Main
# ====================================================================


def main():
    t0 = time.time()
    print("=" * 60)
    print("  Phase 1: World Model Validation")
    print("  500 points/area, 5 areas, 8 years")
    print("=" * 60)

    all_data = download_all_points()
    if not train_on_subset(all_data):
        return

    results = {
        "config": {
            "n_points": N_POINTS,
            "train_areas": [a["name"] for a in TRAINING_AREAS],
            "train_years": TRAIN_YEARS,
            "holdout_area": HOLDOUT_AREA["name"],
            "ood_areas": [a["name"] for a in OOD_AREAS],
        },
        "exp1_temporal_holdout": exp1_temporal_holdout(all_data),
        "exp2_multistep": exp2_multistep_degradation(all_data),
        "exp3_spatial_ood": exp3_spatial_ood(all_data),
    }

    elapsed = time.time() - t0

    # Summary
    print("\n" + "=" * 60)
    print("  SUMMARY")
    print("=" * 60)

    exp1 = results["exp1_temporal_holdout"]
    for name, data in exp1.items():
        m = data["1_step"]["model"]["cos_sim_mean"]
        p = data["1_step"]["persistence"]["cos_sim_mean"]
        tag = "BETTER" if m > p else "WORSE"
        print(f"  {name}: model={m:.4f} vs persist={p:.4f} -> {tag} ({m-p:+.4f})")

    exp3 = results["exp3_spatial_ood"]
    for name, data in exp3.items():
        print(f"  {name} (OOD): advantage={data['advantage']:+.4f}")

    print(f"\n  Elapsed: {elapsed:.1f}s")

    # Save
    def _conv(o):
        if isinstance(o, dict): return {k: _conv(v) for k, v in o.items()}
        if isinstance(o, (list, tuple)): return [_conv(v) for v in o]
        if isinstance(o, (np.integer,)): return int(o)
        if isinstance(o, (np.floating,)): return float(o)
        if isinstance(o, (np.bool_,)): return bool(o)
        if isinstance(o, np.ndarray): return o.tolist()
        return o

    out_path = OUTPUT_DIR / "phase1_validation_results.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(_conv(results), f, ensure_ascii=False, indent=2)
    print(f"  Saved: {out_path}")


if __name__ == "__main__":
    main()
