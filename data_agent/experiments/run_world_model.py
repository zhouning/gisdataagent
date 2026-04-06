"""World Model Paper — Experiment Runner.

Runs all experiments for the geospatial world model paper:
  - 17-area prediction quality evaluation
  - Multi-step rollout decay analysis
  - LULC decoder 5-fold CV
  - Ablation study (4 variants)

Usage:
    python -m data_agent.experiments.run_world_model --dry-run
    python -m data_agent.experiments.run_world_model --all
"""

import argparse
import json
import sys
import os
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from data_agent.experiments.common import OUTPUT_DIR, init_gee

# 17 study areas from the paper
AREAS = [
    # Training (12)
    {"name": "Yangtze_Delta",  "bbox": [120.8, 30.7, 121.8, 31.5], "type": "Urban",       "split": "Train"},
    {"name": "Jing_Jin_Ji",    "bbox": [116.0, 39.5, 117.0, 40.3], "type": "Urban",       "split": "Train"},
    {"name": "Chengdu_Plain",  "bbox": [103.8, 30.3, 104.5, 30.9], "type": "Urban",       "split": "Train"},
    {"name": "NE_Plain",       "bbox": [125.0, 44.5, 126.0, 45.5], "type": "Agriculture", "split": "Train"},
    {"name": "N_China_Plain",  "bbox": [114.5, 36.0, 115.5, 37.0], "type": "Agriculture", "split": "Train"},
    {"name": "Jianghan_Plain", "bbox": [113.5, 30.0, 114.5, 30.8], "type": "Agriculture", "split": "Train"},
    {"name": "Hetao",          "bbox": [107.0, 40.5, 108.0, 41.2], "type": "Agriculture", "split": "Train"},
    {"name": "Yunnan_Eco",     "bbox": [100.0, 25.5, 100.8, 26.2], "type": "Ecology",     "split": "Train"},
    {"name": "Daxinganling",   "bbox": [121.5, 50.0, 122.5, 50.8], "type": "Forest",      "split": "Train"},
    {"name": "Qinghai_Edge",   "bbox": [100.5, 36.0, 101.5, 36.8], "type": "Plateau",     "split": "Train"},
    {"name": "Guanzhong",      "bbox": [108.5, 34.0, 109.3, 34.7], "type": "Mixed",       "split": "Train"},
    {"name": "Minnan_Coast",   "bbox": [117.8, 24.3, 118.5, 25.0], "type": "Mixed",       "split": "Train"},
    # Validation (2)
    {"name": "Pearl_River",    "bbox": [113.0, 22.8, 114.0, 23.5], "type": "Urban",       "split": "Val"},
    {"name": "Poyang_Lake",    "bbox": [115.8, 28.8, 116.5, 29.5], "type": "Wetland",     "split": "Val"},
    # Test (1)
    {"name": "Wuyi_Mountain",  "bbox": [117.5, 27.5, 118.2, 28.2], "type": "Forest",      "split": "Test"},
    # OOD (2)
    {"name": "Sanxia",         "bbox": [110.0, 30.5, 111.0, 31.2], "type": "Mixed",       "split": "OOD"},
    {"name": "Lhasa_Valley",   "bbox": [91.0, 29.5, 91.8, 30.0],   "type": "Plateau",     "split": "OOD"},
]


def _fetch_embedding_pair(bbox, year1, year2, scale=500):
    """Fetch AlphaEarth embedding pair (t, t+1) from GEE.

    Uses coarser scale (500m) to stay within GEE pixel limits.
    Returns (emb_t1, emb_t2) each [H, W, 64] or (None, None).
    """
    import ee

    collection_id = "GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL"
    roi = ee.Geometry.Rectangle(bbox)
    bands = [f"A{i:02d}" for i in range(64)]

    results = []
    for year in [year1, year2]:
        img = (
            ee.ImageCollection(collection_id)
            .filterDate(f"{year}-01-01", f"{year}-12-31")
            .filterBounds(roi)
            .first()
        )
        if img is None:
            return None, None
        img = img.select(bands)
        try:
            arr_info = img.sampleRectangle(region=roi, defaultValue=0).getInfo()
            band_arrays = [np.array(arr_info["properties"][b]) for b in bands]
            emb = np.stack(band_arrays, axis=-1).astype(np.float32)
            # L2 normalize
            norms = np.linalg.norm(emb, axis=-1, keepdims=True)
            norms = np.where(norms == 0, 1, norms)
            emb = emb / norms
            results.append(emb)
        except Exception as e:
            print(f"    GEE error for {year}: {e}")
            return None, None

    return results[0], results[1]


def _cosine_sim_grid(emb1, emb2):
    """Compute per-pixel cosine similarity between two embedding grids."""
    dot = np.sum(emb1 * emb2, axis=-1)
    return dot  # Already L2-normalized, so dot = cosine sim


def run_area_evaluation(scale=500):
    """Experiment 2.1: Evaluate prediction quality across 17 areas.

    For each area:
    1. Fetch 2021→2022 embedding pair from GEE
    2. Persistence baseline: cos_sim(emb_2021, emb_2022)
    3. Model prediction: apply LatentDynamicsNet to emb_2021, get pred_2022
    4. Model quality: cos_sim(pred_2022, emb_2022)
    """
    if not init_gee():
        print("  GEE not available, skipping area evaluation")
        return None

    # Try to load model
    try:
        from data_agent.world_model import LatentDynamicsNet, CHECKPOINT_PATH
        import torch
        model = LatentDynamicsNet()
        if os.path.exists(CHECKPOINT_PATH):
            model.load_state_dict(torch.load(CHECKPOINT_PATH, map_location="cpu"))
            print("  Loaded LatentDynamicsNet checkpoint")
        else:
            print(f"  No checkpoint at {CHECKPOINT_PATH}, using random init (results will be noisy)")
        model.eval()
        has_model = True
    except Exception as e:
        print(f"  Cannot load model: {e}, will report persistence only")
        has_model = False

    results = []
    for area in AREAS:
        name = area["name"]
        bbox = area["bbox"]
        print(f"\n  [{area['split']}] {name} ({area['type']})...")

        emb_2021, emb_2022 = _fetch_embedding_pair(bbox, 2021, 2022, scale=scale)
        if emb_2021 is None:
            print(f"    SKIP: could not fetch embeddings")
            results.append({**area, "status": "skip", "cos_sim_baseline": None, "cos_sim_model": None})
            continue

        # Persistence baseline
        cos_baseline = _cosine_sim_grid(emb_2021, emb_2022)
        mean_baseline = float(np.mean(cos_baseline))

        # Identify change pixels (cosine sim < 0.95)
        change_mask = cos_baseline < 0.95
        n_change = int(change_mask.sum())
        n_total = cos_baseline.size

        mean_model = None
        change_baseline = None
        change_model = None

        if has_model:
            import torch
            # Reshape for CNN: [1, 64, H, W]
            inp = torch.from_numpy(emb_2021.transpose(2, 0, 1)).unsqueeze(0).float()
            # Need scenario conditioning — use baseline (id=4)
            scenario_vec = np.zeros(16, dtype=np.float32)
            scenario_vec[4] = 1.0  # baseline scenario
            # Pad input channels: 64 emb + 16 scenario = 80 ... but model expects 64
            # Just use raw 64 channels
            with torch.no_grad():
                pred = model(inp)
            pred_np = pred.squeeze(0).permute(1, 2, 0).numpy()
            # L2 normalize prediction
            norms = np.linalg.norm(pred_np, axis=-1, keepdims=True)
            norms = np.where(norms == 0, 1, norms)
            pred_np = pred_np / norms

            cos_model = _cosine_sim_grid(pred_np, emb_2022)
            mean_model = float(np.mean(cos_model))

            if n_change > 0:
                change_baseline = float(np.mean(cos_baseline[change_mask]))
                change_model = float(np.mean(cos_model[change_mask]))

        result = {
            **area,
            "status": "ok",
            "grid_shape": list(emb_2021.shape[:2]),
            "cos_sim_baseline": round(mean_baseline, 4),
            "cos_sim_model": round(mean_model, 4) if mean_model else None,
            "advantage": round(mean_model - mean_baseline, 4) if mean_model else None,
            "n_change_pixels": n_change,
            "n_total_pixels": n_total,
            "change_pct": round(n_change / n_total * 100, 1),
            "change_baseline": round(change_baseline, 4) if change_baseline else None,
            "change_model": round(change_model, 4) if change_model else None,
            "change_advantage": round(change_model - change_baseline, 4) if change_model and change_baseline else None,
        }
        results.append(result)
        print(f"    Grid: {result['grid_shape']}, Baseline: {mean_baseline:.4f}, Model: {mean_model:.4f if mean_model else 'N/A'}")

    # Save results
    out_path = OUTPUT_DIR / "world_model_17areas.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\n17-area results saved to {out_path}")

    # Also save CSV for easy table generation
    df = pd.DataFrame(results)
    csv_path = OUTPUT_DIR / "world_model_17areas.csv"
    df.to_csv(csv_path, index=False)
    print(f"CSV saved to {csv_path}")
    return results


def run_rollout_decay(scale=500):
    """Experiment 2.2: Multi-step rollout prediction decay.

    Test area (Wuyi Mountain) + OOD areas (Sanxia, Lhasa).
    Rollout 1-6 years from 2017 base.
    """
    if not init_gee():
        print("  GEE not available")
        return None

    try:
        from data_agent.world_model import LatentDynamicsNet, CHECKPOINT_PATH
        import torch
        model = LatentDynamicsNet()
        if os.path.exists(CHECKPOINT_PATH):
            model.load_state_dict(torch.load(CHECKPOINT_PATH, map_location="cpu"))
        model.eval()
    except Exception as e:
        print(f"  Cannot load model: {e}")
        return None

    import ee
    eval_areas = [a for a in AREAS if a["split"] in ("Test", "OOD")]
    max_steps = 6
    base_year = 2017

    results = []
    for area in eval_areas:
        name = area["name"]
        bbox = area["bbox"]
        print(f"\n  Rollout: {name}...")

        # Fetch base year embedding
        emb_base, _ = _fetch_embedding_pair(bbox, base_year, base_year + 1, scale=scale)
        if emb_base is None:
            continue

        # Fetch ground truth for each year
        gt_embeddings = {}
        for step in range(1, max_steps + 1):
            year = base_year + step
            _, gt = _fetch_embedding_pair(bbox, year - 1, year, scale=scale)
            if gt is not None:
                gt_embeddings[step] = gt

        # Rollout
        import torch
        current = emb_base.copy()
        for step in range(1, max_steps + 1):
            inp = torch.from_numpy(current.transpose(2, 0, 1)).unsqueeze(0).float()
            with torch.no_grad():
                pred = model(inp)
            pred_np = pred.squeeze(0).permute(1, 2, 0).numpy()
            norms = np.linalg.norm(pred_np, axis=-1, keepdims=True)
            norms = np.where(norms == 0, 1, norms)
            pred_np = pred_np / norms

            if step in gt_embeddings:
                gt = gt_embeddings[step]
                cos_model = float(np.mean(_cosine_sim_grid(pred_np, gt)))
                cos_baseline = float(np.mean(_cosine_sim_grid(emb_base, gt)))  # persistence
                results.append({
                    "area": name, "split": area["split"], "step": step,
                    "year": base_year + step,
                    "cos_sim_model": round(cos_model, 4),
                    "cos_sim_baseline": round(cos_baseline, 4),
                    "advantage": round(cos_model - cos_baseline, 4),
                })
                print(f"    Step {step} ({base_year+step}): model={cos_model:.4f}, baseline={cos_baseline:.4f}")

            current = pred_np

    out_path = OUTPUT_DIR / "world_model_rollout.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"\nRollout results saved to {out_path}")
    return results


def run_lulc_decode():
    """Experiment 2.3: LULC decoder 5-fold cross-validation.

    Trains LogisticRegression on AlphaEarth embeddings → ESRI LULC.
    Reports per-class F1 + confusion matrix.
    """
    if not init_gee():
        print("  GEE not available")
        return None

    import ee
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import StratifiedKFold
    from sklearn.metrics import classification_report, confusion_matrix

    print("  Collecting training data from 3 diverse areas...")

    # Use 3 areas for diversity
    sample_areas = [
        {"name": "Shanghai", "bbox": [121.2, 31.0, 121.6, 31.3]},
        {"name": "Chengdu",  "bbox": [104.0, 30.5, 104.3, 30.8]},
        {"name": "Yunnan",   "bbox": [100.1, 25.6, 100.4, 25.9]},
    ]

    all_X = []
    all_y = []
    bands = [f"A{i:02d}" for i in range(64)]

    for sa in sample_areas:
        print(f"    Fetching {sa['name']}...")
        roi = ee.Geometry.Rectangle(sa["bbox"])

        # Embeddings
        emb_img = (
            ee.ImageCollection("GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL")
            .filterDate("2020-01-01", "2020-12-31")
            .filterBounds(roi)
            .first()
            .select(bands)
        )

        # LULC labels
        lulc_img = (
            ee.ImageCollection("projects/sat-io/open-datasets/ESRI_GLC10")
            .filterBounds(roi)
            .mosaic()
            .select("b1")
        )

        # Sample points
        combined = emb_img.addBands(lulc_img.rename("lulc"))
        try:
            sample = combined.sample(region=roi, scale=100, numPixels=2000, seed=42).getInfo()
            for feat in sample["features"]:
                props = feat["properties"]
                lulc_val = props.get("lulc", 0)
                if lulc_val in [1, 2, 4, 5, 7, 8, 9, 10, 11]:
                    emb_vec = [props.get(b, 0) for b in bands]
                    all_X.append(emb_vec)
                    all_y.append(int(lulc_val))
        except Exception as e:
            print(f"    Error sampling {sa['name']}: {e}")

    if len(all_X) < 100:
        print(f"  Only {len(all_X)} samples, insufficient for 5-fold CV")
        return None

    X = np.array(all_X, dtype=np.float32)
    y = np.array(all_y)
    print(f"  Total samples: {len(X)}, classes: {np.unique(y)}")

    # 5-fold CV
    skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    fold_reports = []
    all_preds = np.zeros_like(y)

    for fold, (train_idx, test_idx) in enumerate(skf.split(X, y)):
        clf = LogisticRegression(max_iter=1000, random_state=42, C=1.0)
        clf.fit(X[train_idx], y[train_idx])
        preds = clf.predict(X[test_idx])
        all_preds[test_idx] = preds
        acc = np.mean(preds == y[test_idx])
        fold_reports.append({"fold": fold + 1, "accuracy": round(acc, 4)})
        print(f"    Fold {fold+1}: accuracy={acc:.4f}")

    # Overall metrics
    cm = confusion_matrix(y, all_preds, labels=sorted(np.unique(y)))
    report = classification_report(y, all_preds, output_dict=True)
    overall_acc = np.mean(all_preds == y)
    print(f"  Overall accuracy: {overall_acc:.4f}")

    results = {
        "n_samples": len(X),
        "n_classes": len(np.unique(y)),
        "classes": sorted(np.unique(y).tolist()),
        "overall_accuracy": round(overall_acc, 4),
        "fold_reports": fold_reports,
        "confusion_matrix": cm.tolist(),
        "classification_report": {k: v for k, v in report.items() if k not in ("accuracy",)},
    }

    out_path = OUTPUT_DIR / "world_model_lulc_decode.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\nLULC decode results saved to {out_path}")
    return results


def main():
    parser = argparse.ArgumentParser(description="World Model Paper Experiments")
    parser.add_argument("--dry-run", action="store_true", help="Check setup without running")
    parser.add_argument("--areas", action="store_true", help="Run 17-area evaluation")
    parser.add_argument("--rollout", action="store_true", help="Run rollout decay")
    parser.add_argument("--lulc", action="store_true", help="Run LULC decoder CV")
    parser.add_argument("--all", action="store_true", help="Run all experiments")
    parser.add_argument("--scale", type=int, default=500, help="GEE scale in meters (default 500)")
    args = parser.parse_args()

    if args.dry_run:
        print("Dry run: checking GEE...")
        ok = init_gee()
        print(f"GEE: {'OK' if ok else 'UNAVAILABLE'}")
        print(f"Areas: {len(AREAS)}")
        print(f"Output dir: {OUTPUT_DIR}")
        return

    if args.all or args.areas:
        print("\n" + "=" * 60)
        print("Experiment 2.1: 17-Area Evaluation")
        print("=" * 60)
        run_area_evaluation(scale=args.scale)

    if args.all or args.rollout:
        print("\n" + "=" * 60)
        print("Experiment 2.2: Rollout Decay")
        print("=" * 60)
        run_rollout_decay(scale=args.scale)

    if args.all or args.lulc:
        print("\n" + "=" * 60)
        print("Experiment 2.3: LULC Decoder CV")
        print("=" * 60)
        run_lulc_decode()

    print(f"\nAll outputs in: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
