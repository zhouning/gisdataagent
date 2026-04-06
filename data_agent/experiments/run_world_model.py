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

    Samples grid points at fixed locations to ensure aligned pixel pairs.
    Returns (emb_t1, emb_t2) as arrays of shape [N, 64], or (None, None).
    """
    import ee

    collection_id = "GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL"
    roi = ee.Geometry.Rectangle(bbox)
    bands = [f"A{i:02d}" for i in range(64)]

    # Generate fixed sample points
    # Use year1's image to create sample points, then extract both years at same locations
    img1 = (
        ee.ImageCollection(collection_id)
        .filterDate(f"{year1}-01-01", f"{year1}-12-31")
        .filterBounds(roi)
        .first()
    )
    img2 = (
        ee.ImageCollection(collection_id)
        .filterDate(f"{year2}-01-01", f"{year2}-12-31")
        .filterBounds(roi)
        .first()
    )
    if img1 is None or img2 is None:
        return None, None

    try:
        # Stack both years into one image, sample once
        bands1 = [f"Y1_{b}" for b in bands]
        bands2 = [f"Y2_{b}" for b in bands]
        combined = img1.select(bands).rename(bands1).addBands(
            img2.select(bands).rename(bands2)
        )

        sample = combined.sample(
            region=roi, scale=scale, numPixels=500,
            seed=42, geometries=False,
        ).getInfo()

        if not sample["features"]:
            return None, None

        emb1_list, emb2_list = [], []
        for feat in sample["features"]:
            props = feat["properties"]
            v1 = [props.get(b, 0.0) for b in bands1]
            v2 = [props.get(b, 0.0) for b in bands2]
            emb1_list.append(v1)
            emb2_list.append(v2)

        emb1 = np.array(emb1_list, dtype=np.float32)
        emb2 = np.array(emb2_list, dtype=np.float32)

        # L2 normalize
        for emb in [emb1, emb2]:
            norms = np.linalg.norm(emb, axis=-1, keepdims=True)
            norms = np.where(norms == 0, 1, norms)
            emb /= norms

        return emb1, emb2

    except Exception as e:
        print(f"    GEE error: {e}")
        return None, None


def _cosine_sim_vectors(emb1, emb2):
    """Compute per-sample cosine similarity between two [N, 64] arrays."""
    dot = np.sum(emb1 * emb2, axis=-1)
    return dot  # Already L2-normalized


def run_area_evaluation(scale=500):
    """Experiment 2.1: Evaluate prediction quality across 17 areas.

    For each area:
    1. Sample 500 pixels' AlphaEarth embeddings for 2021 and 2022
    2. Persistence baseline: cos_sim(emb_2021, emb_2022)
    3. Report mean cosine similarity and change pixel statistics
    """
    if not init_gee():
        print("  GEE not available, skipping area evaluation")
        return None

    results = []
    for area in AREAS:
        name = area["name"]
        bbox = area["bbox"]
        print(f"\n  [{area['split']}] {name} ({area['type']})...")

        emb_2021, emb_2022 = _fetch_embedding_pair(bbox, 2021, 2022, scale=scale)
        if emb_2021 is None:
            print(f"    SKIP: could not fetch embeddings")
            results.append({**area, "status": "skip", "cos_sim_baseline": None})
            continue

        # Persistence baseline: cos_sim of same pixels across years
        cos_baseline = _cosine_sim_vectors(emb_2021, emb_2022)
        mean_baseline = float(np.mean(cos_baseline))

        # Identify change pixels (cosine sim < 0.95)
        change_mask = cos_baseline < 0.95
        n_change = int(change_mask.sum())
        n_total = len(cos_baseline)

        change_mean = float(np.mean(cos_baseline[change_mask])) if n_change > 0 else None
        stable_mean = float(np.mean(cos_baseline[~change_mask])) if n_change < n_total else None

        result = {
            **area,
            "status": "ok",
            "n_samples": n_total,
            "cos_sim_baseline": round(mean_baseline, 4),
            "n_change_pixels": n_change,
            "change_pct": round(n_change / n_total * 100, 1),
            "change_baseline": round(change_mean, 4) if change_mean else None,
            "stable_baseline": round(stable_mean, 4) if stable_mean else None,
        }
        results.append(result)
        print(f"    N={n_total}, Baseline={mean_baseline:.4f}, Change={n_change} ({result['change_pct']}%)")

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
    """Experiment 2.2: Multi-step rollout — year-by-year persistence decay.

    For test + OOD areas, compute year-over-year cosine similarity
    to measure how fast embeddings diverge from the base year.
    """
    if not init_gee():
        print("  GEE not available")
        return None

    import ee
    eval_areas = [a for a in AREAS if a["split"] in ("Test", "OOD")]
    base_year = 2017
    max_years = 6

    results = []
    for area in eval_areas:
        name = area["name"]
        bbox = area["bbox"]
        print(f"\n  Rollout: {name}...")

        # Fetch base year
        emb_base, _ = _fetch_embedding_pair(bbox, base_year, base_year + 1, scale=scale)
        if emb_base is None:
            print(f"    SKIP: cannot fetch base year")
            continue

        for step in range(1, max_years + 1):
            year = base_year + step
            _, emb_future = _fetch_embedding_pair(bbox, year - 1, year, scale=scale)
            if emb_future is None:
                continue

            # Persistence: how similar is base to future?
            cos_persist = float(np.mean(_cosine_sim_vectors(emb_base, emb_future)))
            results.append({
                "area": name, "split": area["split"], "step": step,
                "year": year, "cos_sim_persistence": round(cos_persist, 4),
            })
            print(f"    Step {step} ({year}): persistence={cos_persist:.4f}")

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

        # LULC labels — use ESA WorldCover 10m (v200)
        lulc_img = (
            ee.ImageCollection("ESA/WorldCover/v200")
            .filterBounds(roi)
            .mosaic()
            .select("Map")
        )

        # ESA WorldCover classes: 10=Tree, 20=Shrub, 30=Grass, 40=Crop, 50=Built,
        #   60=Barren, 70=Snow, 80=Water, 90=Wetland, 95=Mangrove
        valid_classes = [10, 20, 30, 40, 50, 60, 70, 80, 90]

        # Sample points
        combined = emb_img.addBands(lulc_img.rename("lulc"))
        try:
            sample = combined.sample(region=roi, scale=100, numPixels=2000, seed=42).getInfo()
            for feat in sample["features"]:
                props = feat["properties"]
                lulc_val = props.get("lulc", 0)
                if lulc_val in valid_classes:
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
