"""
Ablation Study: Validate three core architectural claims
=========================================================
Exp A: w/o L2 Normalization — observe norm drift + decode collapse
Exp B: w/o Dilated Conv     — standard 3x3, observe change-pixel drop
Exp C: w/o Unrolled Loss    — K=1 single-step, observe multi-step decay

Each experiment trains a variant model and evaluates on the same
val/test/OOD splits as Phase 2.
"""

import sys, io, os, json, time, logging
from pathlib import Path

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import numpy as np
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

OUTPUT_DIR = Path("scripts/ablation_results")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

CACHE_DIR = Path("data_agent/weights/raw_data")
N_POINTS = 500
SEED = 42

# Same splits as Phase 2
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
OOD_AREAS = [
    {"name": "sanxia_reservoir", "bbox": [110.3, 30.8, 110.4, 30.9]},
    {"name": "lhasa_valley", "bbox": [91.1, 29.6, 91.2, 29.7]},
]
TRAIN_YEARS = list(range(2017, 2023))
ALL_YEARS = list(range(2017, 2025))


def load_point(name, bbox, year):
    p = CACHE_DIR / f"pts_{name}_{year}.npy"
    if p.exists():
        return np.load(p)
    from data_agent.world_model import sample_embeddings_as_points
    pts = sample_embeddings_as_points(bbox, year, N_POINTS, SEED)
    if pts is not None:
        np.save(p, pts)
    return pts


def load_all():
    data = {}
    for area in TRAIN_AREAS + VAL_AREAS + OOD_AREAS:
        n = area["name"]
        data[n] = {}
        for y in ALL_YEARS:
            pts = load_point(n, area["bbox"], y)
            if pts is not None:
                data[n][y] = pts
    return data


def metrics(z_pred, z_true):
    n = min(len(z_pred), len(z_true))
    p, t = z_pred[:n], z_true[:n]
    pn = p / (np.linalg.norm(p, axis=1, keepdims=True) + 1e-10)
    tn = t / (np.linalg.norm(t, axis=1, keepdims=True) + 1e-10)
    cs = np.sum(pn * tn, axis=1)
    return {"cos_sim": float(np.mean(cs)), "n": n}


def change_metrics(z_prev, z_pred, z_true):
    n = min(len(z_prev), len(z_pred), len(z_true))
    z_prev, z_pred, z_true = z_prev[:n], z_pred[:n], z_true[:n]
    change_mag = np.linalg.norm(z_true - z_prev, axis=1)
    thr = np.percentile(change_mag, 80)
    mask = change_mag >= thr
    if mask.sum() == 0:
        return None
    m = metrics(z_pred[mask], z_true[mask])
    p = metrics(z_prev[mask], z_true[mask])
    return {"changed_model": m["cos_sim"], "changed_persist": p["cos_sim"],
            "advantage": m["cos_sim"] - p["cos_sim"]}


def predict_1step(z_t, model, scenario_tensor):
    import torch
    n = z_t.shape[0]
    z = torch.tensor(z_t.T[np.newaxis, :, np.newaxis, :]).float()
    with torch.no_grad():
        z_next = model(z, scenario_tensor)
    return z_next.squeeze(0).squeeze(1).numpy().T[:n]


def predict_nsteps_with_norm(z_start, model, scenario_tensor, n_steps, do_normalize=True):
    import torch
    n = z_start.shape[0]
    z = torch.tensor(z_start.T[np.newaxis, :, np.newaxis, :]).float()
    results = []
    norms = []
    with torch.no_grad():
        for _ in range(n_steps):
            z = model(z, scenario_tensor)
            if do_normalize:
                z = torch.nn.functional.normalize(z, p=2, dim=1)
            # Track norms
            z_np = z.squeeze(0).squeeze(1).numpy().T[:n]
            pixel_norms = np.linalg.norm(z_np, axis=1)
            norms.append({"mean": float(np.mean(pixel_norms)),
                          "min": float(np.min(pixel_norms)),
                          "max": float(np.max(pixel_norms))})
            results.append(z_np)
    return results, norms


# ====================================================================
# Training variants
# ====================================================================

def train_variant(data, variant_name, use_l2_norm=True, use_dilated=True, unroll_steps=3):
    """Train a model variant and return it."""
    import torch
    import torch.nn as nn
    from data_agent.world_model import encode_scenario, Z_DIM, SCENARIO_DIM, N_CONTEXT

    s_baseline = encode_scenario("baseline")

    # Build training pairs
    z_t_list, z_tp1_list = [], []
    for area in TRAIN_AREAS:
        n = area["name"]
        for i in range(len(TRAIN_YEARS) - 1):
            y1, y2 = TRAIN_YEARS[i], TRAIN_YEARS[i + 1]
            if y1 in data.get(n, {}) and y2 in data.get(n, {}):
                z_t_list.append(data[n][y1])
                z_tp1_list.append(data[n][y2])

    # Build model variant
    in_ch = Z_DIM * 2 + N_CONTEXT
    if use_dilated:
        dynamics = nn.Sequential(
            nn.Conv2d(in_ch, 128, 3, padding=1, dilation=1), nn.GroupNorm(8, 128), nn.GELU(),
            nn.Conv2d(128, 128, 3, padding=2, dilation=2), nn.GroupNorm(8, 128), nn.GELU(),
            nn.Conv2d(128, 128, 3, padding=4, dilation=4), nn.GroupNorm(8, 128), nn.GELU(),
            nn.Conv2d(128, Z_DIM, 1),
        )
    else:
        dynamics = nn.Sequential(
            nn.Conv2d(in_ch, 128, 3, padding=1), nn.GroupNorm(8, 128), nn.GELU(),
            nn.Conv2d(128, 128, 3, padding=1), nn.GroupNorm(8, 128), nn.GELU(),
            nn.Conv2d(128, 128, 3, padding=1), nn.GroupNorm(8, 128), nn.GELU(),
            nn.Conv2d(128, Z_DIM, 1),
        )

    scenario_enc = nn.Sequential(nn.Linear(SCENARIO_DIM, 64), nn.ReLU(), nn.Linear(64, Z_DIM))

    class VariantModel(nn.Module):
        def __init__(self):
            super().__init__()
            self.scenario_enc = scenario_enc
            self.dynamics = dynamics
            self.z_dim = Z_DIM
            self.n_context = N_CONTEXT

        def forward(self, z_t, scenario, context=None):
            s = self.scenario_enc(scenario)[:, :, None, None].expand_as(z_t)
            B, _, H, W = z_t.shape
            zeros = torch.zeros(B, self.n_context, H, W, device=z_t.device)
            inp = torch.cat([z_t, s, zeros], dim=1)
            delta_z = self.dynamics(inp)
            return z_t + delta_z

    model = VariantModel()
    optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)
    mse_loss = torch.nn.MSELoss()

    print(f"  Training [{variant_name}]: {len(z_t_list)} pairs, unroll={unroll_steps}, "
          f"dilated={use_dilated}, l2_norm={use_l2_norm}")

    model.train()
    for epoch in range(100):
        eloss = 0
        for zt, ztp1 in zip(z_t_list, z_tp1_list):
            n = min(zt.shape[0], ztp1.shape[0])

            if unroll_steps == 1:
                # Single-step (teacher forcing)
                z = torch.tensor(zt[:n].T[np.newaxis, :, np.newaxis, :]).float()
                ztrue = torch.tensor(ztp1[:n].T[np.newaxis, :, np.newaxis, :]).float()
                zpred = model(z, s_baseline)
                if use_l2_norm:
                    zpred = torch.nn.functional.normalize(zpred, p=2, dim=1)
                    ztrue = torch.nn.functional.normalize(ztrue, p=2, dim=1)
                loss = mse_loss(zpred, ztrue)
            else:
                # Multi-step unrolled
                z = torch.tensor(zt[:n].T[np.newaxis, :, np.newaxis, :]).float()
                ztrue = torch.tensor(ztp1[:n].T[np.newaxis, :, np.newaxis, :]).float()
                loss = torch.tensor(0.0)
                zpred = model(z, s_baseline)
                if use_l2_norm:
                    zpred = torch.nn.functional.normalize(zpred, p=2, dim=1)
                    ztrue_n = torch.nn.functional.normalize(ztrue, p=2, dim=1)
                else:
                    ztrue_n = ztrue
                loss = loss + mse_loss(zpred, ztrue_n)
                # Steps 2+ use same target (approximate, since we don't have z_{t+2} for every pair)
                for k in range(1, unroll_steps):
                    zpred = model(zpred.detach(), s_baseline)
                    if use_l2_norm:
                        zpred = torch.nn.functional.normalize(zpred, p=2, dim=1)
                    loss = loss + (1.0 / (2 ** k)) * mse_loss(zpred, ztrue_n)

            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
            eloss += loss.item()

        if (epoch + 1) % 25 == 0:
            print(f"    Epoch {epoch+1}/100  loss={eloss/len(z_t_list):.6f}")

    model.eval()
    return model


def evaluate_model(data, model, s_tensor, areas, do_normalize=True):
    """Evaluate 1-step on areas, return per-area cos_sim."""
    results = {}
    for area in areas:
        n = area["name"]
        d = data.get(n, {})
        years = sorted(d.keys())
        if len(years) < 3:
            continue
        scores_m, scores_p = [], []
        change_advs = []
        for i in range(1, len(years) - 1):
            y0, y1, y2 = years[i-1], years[i], years[i+1]
            zp = predict_1step(d[y1], model, s_tensor)
            m = metrics(zp, d[y2])
            p = metrics(d[y1], d[y2])
            scores_m.append(m["cos_sim"])
            scores_p.append(p["cos_sim"])
            cm = change_metrics(d[y1], zp, d[y2])
            if cm:
                change_advs.append(cm["advantage"])
        results[n] = {
            "model": float(np.mean(scores_m)),
            "persist": float(np.mean(scores_p)),
            "adv": float(np.mean(scores_m)) - float(np.mean(scores_p)),
            "change_adv": float(np.mean(change_advs)) if change_advs else None,
        }
    return results


def evaluate_multistep(data, model, s_tensor, areas, do_normalize=True):
    """Evaluate multi-step degradation + norm tracking."""
    results = {}
    for area in areas[:3]:
        n = area["name"]
        d = data.get(n, {})
        if 2017 not in d:
            continue
        preds, norms = predict_nsteps_with_norm(d[2017], model, s_tensor, 6, do_normalize)
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
                "adv": mm["cos_sim"] - mp["cos_sim"],
                "norm": norms[si],
            })
        results[n] = steps
    return results


def main():
    import torch
    from data_agent.world_model import encode_scenario

    t0 = time.time()
    print("=" * 70)
    print("  Ablation Study: 3 experiments")
    print("=" * 70)

    data = load_all()
    s_baseline = encode_scenario("baseline")

    all_results = {}

    # Full model (baseline for comparison)
    print("\n--- Full Model (all components) ---")
    model_full = train_variant(data, "full", use_l2_norm=True, use_dilated=True, unroll_steps=3)
    r_full_train = evaluate_model(data, model_full, s_baseline, TRAIN_AREAS)
    r_full_val = evaluate_model(data, model_full, s_baseline, VAL_AREAS)
    r_full_ood = evaluate_model(data, model_full, s_baseline, OOD_AREAS)
    ms_full = evaluate_multistep(data, model_full, s_baseline, TRAIN_AREAS)
    all_results["full"] = {"train": r_full_train, "val": r_full_val, "ood": r_full_ood, "multistep": ms_full}

    # Ablation A: w/o L2 Normalization
    print("\n--- Ablation A: w/o L2 Normalization ---")
    model_no_l2 = train_variant(data, "no_l2", use_l2_norm=False, use_dilated=True, unroll_steps=3)
    r_a_train = evaluate_model(data, model_no_l2, s_baseline, TRAIN_AREAS, do_normalize=False)
    r_a_val = evaluate_model(data, model_no_l2, s_baseline, VAL_AREAS, do_normalize=False)
    ms_a = evaluate_multistep(data, model_no_l2, s_baseline, TRAIN_AREAS, do_normalize=False)
    all_results["no_l2"] = {"train": r_a_train, "val": r_a_val, "multistep": ms_a}

    # Ablation B: w/o Dilated Conv
    print("\n--- Ablation B: w/o Dilated Conv (standard 3x3) ---")
    model_no_dil = train_variant(data, "no_dilated", use_l2_norm=True, use_dilated=False, unroll_steps=3)
    r_b_train = evaluate_model(data, model_no_dil, s_baseline, TRAIN_AREAS)
    r_b_val = evaluate_model(data, model_no_dil, s_baseline, VAL_AREAS)
    all_results["no_dilated"] = {"train": r_b_train, "val": r_b_val}

    # Ablation C: w/o Unrolled Loss (K=1)
    print("\n--- Ablation C: w/o Unrolled Loss (K=1, teacher forcing) ---")
    model_no_unroll = train_variant(data, "no_unroll", use_l2_norm=True, use_dilated=True, unroll_steps=1)
    r_c_train = evaluate_model(data, model_no_unroll, s_baseline, TRAIN_AREAS)
    r_c_val = evaluate_model(data, model_no_unroll, s_baseline, VAL_AREAS)
    ms_c = evaluate_multistep(data, model_no_unroll, s_baseline, TRAIN_AREAS)
    all_results["no_unroll"] = {"train": r_c_train, "val": r_c_val, "multistep": ms_c}

    # ========== Summary ==========
    print("\n" + "=" * 70)
    print("  ABLATION SUMMARY")
    print("=" * 70)

    def avg_adv(r):
        vals = [v["adv"] for v in r.values() if v.get("adv") is not None]
        return float(np.mean(vals)) if vals else 0

    def avg_change(r):
        vals = [v["change_adv"] for v in r.values() if v.get("change_adv") is not None]
        return float(np.mean(vals)) if vals else 0

    print(f"\n  {'Variant':<25} {'Train Adv':<12} {'Val Adv':<12} {'Change Adv':<12}")
    print(f"  {'─'*25} {'─'*12} {'─'*12} {'─'*12}")
    for label, key in [("Full Model", "full"), ("w/o L2 Norm", "no_l2"),
                        ("w/o Dilated Conv", "no_dilated"), ("w/o Unrolled Loss", "no_unroll")]:
        r = all_results[key]
        ta = avg_adv(r["train"])
        va = avg_adv(r.get("val", {}))
        ca = avg_change(r["train"])
        print(f"  {label:<25} {ta:+.4f}      {va:+.4f}      {ca:+.4f}")

    # Norm drift for w/o L2
    print(f"\n  Norm drift (w/o L2 Normalization, 6-step rollout):")
    for name, steps in all_results["no_l2"].get("multistep", {}).items():
        for s in steps:
            print(f"    {name} step {s['step']}: norm mean={s['norm']['mean']:.4f} "
                  f"min={s['norm']['min']:.4f} max={s['norm']['max']:.4f}  "
                  f"cos_sim={s['model']:.4f}")

    # Multi-step comparison: full vs no_unroll
    print(f"\n  Multi-step: Full (K=3) vs No Unroll (K=1):")
    for name in list(all_results["full"].get("multistep", {}).keys())[:2]:
        steps_f = all_results["full"]["multistep"].get(name, [])
        steps_c = all_results["no_unroll"]["multistep"].get(name, [])
        wins_f = sum(1 for s in steps_f if s["adv"] > 0)
        wins_c = sum(1 for s in steps_c if s["adv"] > 0)
        print(f"    {name}: Full={wins_f}/6 steps, No Unroll={wins_c}/6 steps")

    elapsed = time.time() - t0

    # Save
    def _conv(o):
        if isinstance(o, dict): return {k: _conv(v) for k, v in o.items()}
        if isinstance(o, (list, tuple)): return [_conv(v) for v in o]
        if isinstance(o, (np.integer,)): return int(o)
        if isinstance(o, (np.floating,)): return float(o)
        if isinstance(o, np.ndarray): return o.tolist()
        return o

    out = OUTPUT_DIR / "ablation_results.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(_conv(all_results), f, ensure_ascii=False, indent=2)
    print(f"\n  Saved: {out}")
    print(f"  Elapsed: {elapsed:.1f}s")


if __name__ == "__main__":
    main()
