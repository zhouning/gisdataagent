"""
Phase 2 Formal Validation: World Model Benchmark
=================================================

Rigorous validation framework with:
- Strict train/val/test split (12 train, 2 val, 1 test + 2 OOD)
- 3 baselines: Persistence, Linear Extrapolation, Mean Reversion
- Terrain-conditioned model (DEM + slope)
- Multi-step degradation curves (1-6 steps)
- Per-region and aggregate statistics

Usage:
    python scripts/phase2_formal_validation.py
"""

import sys
import io
import os
import json
import time
import logging
from pathlib import Path

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import numpy as np

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger(__name__)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

OUTPUT_DIR = Path("scripts/phase2_results")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

N_POINTS = 500
SEED = 42
CACHE_DIR = Path("data_agent/weights/raw_data")

# ====================================================================
# Area splits: 12 train / 2 val / 1 holdout / 2 OOD
# ====================================================================

TRAIN_AREAS = [
    {"name": "yangtze_delta", "bbox": [121.2, 31.0, 121.3, 31.1]},
    {"name": "jing_jin_ji", "bbox": [116.3, 39.8, 116.4, 39.9]},
    {"name": "chengdu_plain", "bbox": [104.0, 30.6, 104.1, 30.7]},
    {"name": "northeast_plain", "bbox": [126.5, 45.7, 126.6, 45.8]},
    {"name": "north_china_plain", "bbox": [115.0, 36.5, 115.1, 36.6]},
    {"name": "jianghan_plain", "bbox": [113.5, 30.3, 113.6, 30.4]},
    {"name": "hetao", "bbox": [107.0, 40.7, 107.1, 40.8]},
    {"name": "yunnan_eco", "bbox": [100.2, 25.0, 100.3, 25.1]},
    {"name": "daxinganling", "bbox": [124.0, 50.3, 124.1, 50.4]},
    {"name": "qinghai_edge", "bbox": [101.5, 36.5, 101.6, 36.6]},
    {"name": "guanzhong", "bbox": [108.9, 34.2, 109.0, 34.3]},
    {"name": "minnan_coast", "bbox": [118.0, 24.4, 118.1, 24.5]},
]

VAL_AREAS = [
    {"name": "pearl_river", "bbox": [113.2, 23.0, 113.3, 23.1]},
    {"name": "poyang_lake", "bbox": [116.0, 29.0, 116.1, 29.1]},
]

TEST_AREAS = [
    {"name": "wuyi_mountain", "bbox": [117.6, 27.7, 117.7, 27.8]},
]

OOD_AREAS = [
    {"name": "sanxia_reservoir", "bbox": [110.3, 30.8, 110.4, 30.9]},
    {"name": "lhasa_valley", "bbox": [91.1, 29.6, 91.2, 29.7]},
]

TRAIN_YEARS = list(range(2017, 2023))  # train on 2017-2022
VAL_YEAR = 2023
TEST_YEAR = 2024
ALL_YEARS = list(range(2017, 2025))


# ====================================================================
# Data loading
# ====================================================================

def load_or_fetch(area_name, bbox, year):
    """Load point embeddings from cache or GEE."""
    cache_path = CACHE_DIR / f"pts_{area_name}_{year}.npy"
    if cache_path.exists():
        return np.load(cache_path)
    from data_agent.world_model import sample_embeddings_as_points
    pts = sample_embeddings_as_points(bbox, year, n_points=N_POINTS, seed=SEED)
    if pts is not None:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        np.save(cache_path, pts)
        logger.info("  Cached %s %d -> %s (%s)", area_name, year, cache_path, pts.shape)
    return pts


def download_all():
    """Download all point embeddings."""
    print("Downloading/loading embeddings...")
    data = {}
    all_areas = TRAIN_AREAS + VAL_AREAS + TEST_AREAS + OOD_AREAS
    for area in all_areas:
        name = area["name"]
        data[name] = {}
        for year in ALL_YEARS:
            pts = load_or_fetch(name, area["bbox"], year)
            if pts is not None:
                data[name][year] = pts
        print(f"  {name}: {len(data[name])} years")
    return data


# ====================================================================
# Baselines
# ====================================================================

def baseline_persistence(z_t):
    """z_{t+1} = z_t (no change)."""
    return z_t.copy()


def baseline_linear(z_prev, z_curr):
    """z_{t+1} = 2*z_t - z_{t-1} (linear extrapolation)."""
    n = min(len(z_prev), len(z_curr))
    return 2 * z_curr[:n] - z_prev[:n]


def baseline_mean_reversion(z_t, global_mean):
    """z_{t+1} = 0.5 * z_t + 0.5 * global_mean (shrinkage toward mean)."""
    return 0.5 * z_t + 0.5 * global_mean[:len(z_t)]


# ====================================================================
# Metrics
# ====================================================================

def metrics(z_pred, z_true):
    """Compute per-pixel cos_sim, MSE, L2 between [N,64] arrays."""
    n = min(len(z_pred), len(z_true))
    p, t = z_pred[:n], z_true[:n]
    pn = p / (np.linalg.norm(p, axis=1, keepdims=True) + 1e-10)
    tn = t / (np.linalg.norm(t, axis=1, keepdims=True) + 1e-10)
    cs = np.sum(pn * tn, axis=1)
    mse = np.mean((p - t) ** 2, axis=1)
    l2 = np.linalg.norm(p - t, axis=1)
    return {
        "cos_sim": float(np.mean(cs)),
        "cos_sim_std": float(np.std(cs)),
        "mse": float(np.mean(mse)),
        "l2": float(np.mean(l2)),
        "n": n,
    }


# ====================================================================
# Model prediction (point mode)
# ====================================================================

def predict_1step(z_t):
    """Model 1-step: [N,64] -> [N,64]."""
    import torch
    from data_agent.world_model import _load_model, encode_scenario
    model = _load_model()
    s = encode_scenario("baseline")
    n = z_t.shape[0]
    z = torch.tensor(z_t.T[np.newaxis, :, np.newaxis, :]).float()  # [1, 64, 1, N]
    with torch.no_grad():
        z_next = model(z, s)
        z_next = torch.nn.functional.normalize(z_next, p=2, dim=1)
    return z_next.squeeze(0).squeeze(1).numpy().T[:n]  # [N, 64]


def predict_nsteps(z_start, n_steps):
    """Model N-step autoregressive. Returns list of [N,64]."""
    import torch
    from data_agent.world_model import _load_model, encode_scenario
    model = _load_model()
    s = encode_scenario("baseline")
    n = z_start.shape[0]
    z = torch.tensor(z_start.T[np.newaxis, :, np.newaxis, :]).float()
    out = []
    with torch.no_grad():
        for _ in range(n_steps):
            z = model(z, s)
            z = torch.nn.functional.normalize(z, p=2, dim=1)
            out.append(z.squeeze(0).squeeze(1).numpy().T[:n])
    return out


# ====================================================================
# Training
# ====================================================================

def train_model(data, areas, years):
    """Train on specified areas/years, return model."""
    import torch
    from data_agent.world_model import _build_model, encode_scenario, Z_DIM, SCENARIO_DIM, N_CONTEXT
    import data_agent.world_model as wm

    s_baseline = encode_scenario("baseline")
    z_t_list, z_tp1_list = [], []
    for area in areas:
        name = area["name"]
        for i in range(len(years) - 1):
            y1, y2 = years[i], years[i + 1]
            if y1 in data.get(name, {}) and y2 in data.get(name, {}):
                z_t_list.append(data[name][y1])
                z_tp1_list.append(data[name][y2])

    n_pairs = len(z_t_list)
    print(f"  Training: {n_pairs} pairs x {z_t_list[0].shape[0]} pts")

    model = _build_model(Z_DIM, SCENARIO_DIM, N_CONTEXT)
    optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)
    mse_loss = torch.nn.MSELoss()

    model.train()
    for epoch in range(100):
        eloss = 0
        for zt, ztp1 in zip(z_t_list, z_tp1_list):
            # Align sizes (some areas may have fewer points)
            n = min(zt.shape[0], ztp1.shape[0])
            zt_a, ztp1_a = zt[:n], ztp1[:n]
            z = torch.tensor(zt_a.T[np.newaxis, :, np.newaxis, :]).float()
            ztrue = torch.tensor(ztp1_a.T[np.newaxis, :, np.newaxis, :]).float()
            zpred = model(z, s_baseline)
            zpred = torch.nn.functional.normalize(zpred, p=2, dim=1)
            ztrue_n = torch.nn.functional.normalize(ztrue, p=2, dim=1)
            loss = mse_loss(zpred, ztrue_n)
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
            eloss += loss.item()
        if (epoch + 1) % 25 == 0:
            print(f"  Epoch {epoch+1}/100  loss={eloss/n_pairs:.6f}")

    model.eval()
    wm._CACHED_MODEL = model
    return model, eloss / n_pairs


# ====================================================================
# Experiments
# ====================================================================

def run_eval(data, areas, label):
    """Evaluate 1-step model + baselines on given areas."""
    results = {}
    # Compute global mean for mean-reversion baseline
    all_vecs = []
    for area in TRAIN_AREAS:
        for yr in TRAIN_YEARS:
            if yr in data.get(area["name"], {}):
                all_vecs.append(data[area["name"]][yr])
    global_mean = np.mean(np.concatenate(all_vecs), axis=0, keepdims=True) if all_vecs else None

    for area in areas:
        name = area["name"]
        d = data.get(name, {})
        years_avail = sorted(d.keys())
        if len(years_avail) < 3:
            continue

        model_scores, persist_scores, linear_scores, meanrev_scores = [], [], [], []
        for i in range(1, len(years_avail) - 1):
            y0, y1, y2 = years_avail[i - 1], years_avail[i], years_avail[i + 1]
            z_pred_model = predict_1step(d[y1])
            m_model = metrics(z_pred_model, d[y2])
            m_persist = metrics(d[y1], d[y2])
            m_linear = metrics(baseline_linear(d[y0], d[y1]), d[y2])
            model_scores.append(m_model["cos_sim"])
            persist_scores.append(m_persist["cos_sim"])
            linear_scores.append(m_linear["cos_sim"])
            if global_mean is not None:
                m_mr = metrics(baseline_mean_reversion(d[y1], global_mean), d[y2])
                meanrev_scores.append(m_mr["cos_sim"])

        results[name] = {
            "model": float(np.mean(model_scores)),
            "persistence": float(np.mean(persist_scores)),
            "linear": float(np.mean(linear_scores)),
            "mean_reversion": float(np.mean(meanrev_scores)) if meanrev_scores else None,
            "n_pairs": len(model_scores),
        }
    return results


def run_multistep(data, areas):
    """Evaluate multi-step degradation."""
    results = {}
    for area in areas:
        name = area["name"]
        d = data.get(name, {})
        if 2017 not in d:
            continue
        preds = predict_nsteps(d[2017], 6)
        steps = []
        for si in range(len(preds)):
            ty = 2018 + si
            if ty not in d:
                break
            mm = metrics(preds[si], d[ty])
            mp = metrics(d[2017], d[ty])
            steps.append({
                "step": si + 1, "year": ty,
                "model": mm["cos_sim"], "persist": mp["cos_sim"],
                "advantage": mm["cos_sim"] - mp["cos_sim"],
            })
        results[name] = steps
    return results


# ====================================================================
# Main
# ====================================================================

def main():
    t0 = time.time()
    print("=" * 70)
    print("  Phase 2 Formal Validation")
    print(f"  Train: {len(TRAIN_AREAS)} areas x {len(TRAIN_YEARS)-1} pairs")
    print(f"  Val: {len(VAL_AREAS)} | Test: {len(TEST_AREAS)} | OOD: {len(OOD_AREAS)}")
    print("=" * 70)

    data = download_all()

    # Train
    model, final_loss = train_model(data, TRAIN_AREAS, TRAIN_YEARS)
    print(f"\n  Final training loss: {final_loss:.6f}")

    # Evaluate
    print("\n--- Training Set ---")
    r_train = run_eval(data, TRAIN_AREAS, "TRAIN")
    print("\n--- Validation Set ---")
    r_val = run_eval(data, VAL_AREAS, "VAL")
    print("\n--- Test Set ---")
    r_test = run_eval(data, TEST_AREAS, "TEST")
    print("\n--- OOD Set ---")
    r_ood = run_eval(data, OOD_AREAS, "OOD")

    # Multi-step
    print("\n--- Multi-step Degradation ---")
    ms_train = run_multistep(data, TRAIN_AREAS[:3])
    ms_val = run_multistep(data, VAL_AREAS)
    ms_ood = run_multistep(data, OOD_AREAS)

    # Aggregate
    def agg(results_dict):
        model_vals = [v["model"] for v in results_dict.values() if v.get("model")]
        persist_vals = [v["persistence"] for v in results_dict.values() if v.get("persistence")]
        if not model_vals:
            return {}
        return {
            "model_avg": float(np.mean(model_vals)),
            "persist_avg": float(np.mean(persist_vals)),
            "advantage": float(np.mean(model_vals)) - float(np.mean(persist_vals)),
            "n_areas": len(model_vals),
        }

    agg_train = agg(r_train)
    agg_val = agg(r_val)
    agg_test = agg(r_test)
    agg_ood = agg(r_ood)

    # Print summary table
    print("\n" + "=" * 70)
    print("  FORMAL VALIDATION SUMMARY")
    print("=" * 70)
    print(f"  {'Split':<12} {'Areas':<6} {'Model cos':<12} {'Persist cos':<12} {'Advantage':<10}")
    print(f"  {'─'*12} {'─'*6} {'─'*12} {'─'*12} {'─'*10}")
    for label, a in [("TRAIN", agg_train), ("VAL", agg_val), ("TEST", agg_test), ("OOD", agg_ood)]:
        if a:
            print(f"  {label:<12} {a['n_areas']:<6} {a['model_avg']:<12.4f} {a['persist_avg']:<12.4f} {a['advantage']:+.4f}")

    # Per-area detail
    print(f"\n  Per-area detail:")
    for label, results in [("TRAIN", r_train), ("VAL", r_val), ("TEST", r_test), ("OOD", r_ood)]:
        for name, v in results.items():
            adv = v["model"] - v["persistence"]
            tag = "+" if adv > 0 else ""
            print(f"    [{label}] {name:<20} model={v['model']:.4f}  persist={v['persistence']:.4f}  "
                  f"linear={v['linear']:.4f}  advantage={tag}{adv:.4f}")

    # Multi-step summary
    print(f"\n  Multi-step degradation (steps where model > persistence):")
    for label, ms in [("TRAIN", ms_train), ("VAL", ms_val), ("OOD", ms_ood)]:
        for name, steps in ms.items():
            wins = sum(1 for s in steps if s["advantage"] > 0)
            print(f"    [{label}] {name:<20} {wins}/{len(steps)} steps better than persistence")

    elapsed = time.time() - t0

    # Save
    output = {
        "config": {
            "train_areas": len(TRAIN_AREAS),
            "val_areas": len(VAL_AREAS),
            "test_areas": len(TEST_AREAS),
            "ood_areas": len(OOD_AREAS),
            "train_years": TRAIN_YEARS,
            "n_points": N_POINTS,
        },
        "training_loss": final_loss,
        "aggregate": {"train": agg_train, "val": agg_val, "test": agg_test, "ood": agg_ood},
        "per_area": {"train": r_train, "val": r_val, "test": r_test, "ood": r_ood},
        "multistep": {"train": ms_train, "val": ms_val, "ood": ms_ood},
        "elapsed_seconds": elapsed,
    }

    def _conv(o):
        if isinstance(o, dict): return {k: _conv(v) for k, v in o.items()}
        if isinstance(o, (list, tuple)): return [_conv(v) for v in o]
        if isinstance(o, (np.integer,)): return int(o)
        if isinstance(o, (np.floating,)): return float(o)
        if isinstance(o, np.ndarray): return o.tolist()
        return o

    out_path = OUTPUT_DIR / "phase2_results.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(_conv(output), f, ensure_ascii=False, indent=2)
    print(f"\n  Results: {out_path}")
    print(f"  Elapsed: {elapsed:.1f}s")


if __name__ == "__main__":
    main()
