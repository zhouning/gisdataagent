#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import sys
import tempfile
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.run_twm_dongguan_geosos_validation import (  # noqa: E402
    CLAIM_BOUNDARY,
    DEFAULT_INPUT,
    landuse_label,
    load_landuse_rasters,
    parse_landuse_info,
    parse_suitability_matrix,
    raster_profile,
    transition_allowed,
)

DEFAULT_OUTPUT = REPO_ROOT / "docs/reports/twm_dongguan_geosos_simopt_2026-06-22.json"
DEFAULT_MARKDOWN = REPO_ROOT / "docs/twm-dongguan-geosos-simulation-optimization-2026-06-22.md"
DEFAULT_ASSET_DIR = REPO_ROOT / "docs/assets"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run pixel/grid simulation and planning optimization comparison on GeoSOS DongGuan 80m data."
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN)
    parser.add_argument("--asset-dir", type=Path, default=DEFAULT_ASSET_DIR)
    parser.add_argument("--no-render", action="store_true")
    args = parser.parse_args()

    report = run_dongguan_geosos_simulation_optimization(
        args.input,
        asset_dir=args.asset_dir,
        render=not args.no_render,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    if args.markdown_output:
        args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_output.write_text(render_markdown_report(report), encoding="utf-8")
    print(json.dumps({"status": report["status"], "output": str(args.output)}, ensure_ascii=False))


def run_dongguan_geosos_simulation_optimization(
    zip_path: Path,
    *,
    asset_dir: Path | None = DEFAULT_ASSET_DIR,
    render: bool = True,
) -> dict[str, Any]:
    zip_path = Path(zip_path).expanduser()
    if not zip_path.exists():
        raise FileNotFoundError(str(zip_path))

    with tempfile.TemporaryDirectory(prefix="twm_dongguan_geosos_simopt_") as tmp:
        root = extract_zip(zip_path, Path(tmp))
        landuse_info = parse_landuse_info(root / "Config Files" / "DefaultLanduseInfo.xml")
        suitability = parse_suitability_matrix(root / "Config Files" / "SuitableMatrix.xml", landuse_info)
        rasters = load_landuse_rasters(root)
        drivers = load_driver_layers(root, rasters[2005]["data"].shape)
        profile = raster_profile(rasters)

        landuse2000 = rasters[2000]["data"].astype(np.int16)
        landuse2005 = rasters[2005]["data"].astype(np.int16)
        landuse2006 = rasters[2006]["data"].astype(np.int16)
        valid = valid_mask(landuse2000, landuse2005, landuse2006, landuse_info, rasters)
        classes = sorted(int(key) for key in (landuse_info.get("types") or {}))
        urban_values = {int(value) for value in landuse_info.get("urban_values") or [5]}
        urban_value = sorted(urban_values)[0] if urban_values else 5
        cell_area_ha = float(profile["cell_area_ha"])

        train = build_training_transition_profile(
            landuse2000,
            landuse2005,
            valid,
            classes,
            train_years=5,
            horizon_years=1,
        )
        model_inputs = {
            "initial": landuse2005,
            "actual": landuse2006,
            "valid": valid,
            "classes": classes,
            "landuse_info": landuse_info,
            "suitability": suitability,
            "drivers": drivers,
            "train": train,
            "urban_value": urban_value,
        }

        simulations = build_simulation_candidates(model_inputs)
        metrics = {
            name: pixel_metrics(
                prediction,
                landuse2006,
                landuse2005,
                valid,
                classes,
                suitability,
                landuse_info,
                cell_area_ha,
                urban_value=urban_value,
            )
            for name, prediction in simulations.items()
        }
        planner = build_planner_report(simulations, metrics, model_inputs, cell_area_ha)
        renderer_assets: dict[str, str] = {}
        if render and asset_dir is not None:
            asset_dir.mkdir(parents=True, exist_ok=True)
            renderer_assets = render_assets(
                asset_dir,
                simulations,
                metrics,
                planner,
                landuse2005,
                landuse2006,
                valid,
                landuse_info,
                cell_area_ha,
            )

        baselines = {
            key: metrics[key]
            for key in ("persistence", "markov_pair_budget", "ca_neighborhood", "flus_like_proxy")
            if key in metrics
        }
        twm_candidates = {key: value for key, value in metrics.items() if key.startswith("twm_")}
        best_baseline = max(baselines, key=lambda name: baselines[name]["change_fom"]) if baselines else None
        best_twm_by_change = max(twm_candidates, key=lambda name: twm_candidates[name]["change_fom"]) if twm_candidates else None
        selected = planner.get("selected_candidate_id")

        return {
            "schema": "territory_world_model.dongguan_geosos_simulation_optimization_report.v1",
            "status": "pass",
            "claim_boundary": "geosos_dongguan_pixel_benchmark_not_actual_flus_output",
            "source": {
                "zip_path": str(zip_path),
                "dataset": "GeoSOS DongGuan 80m tutorial data",
                "task": "pixel/grid simulation and planning optimization comparison",
            },
            "data_profile": {
                "raster_profile": profile,
                "landuse_types": landuse_info,
                "driver_layers": drivers["summary"],
                "training_period": "2000->2005",
                "holdout_period": "2005->2006",
                "valid_cell_count": int(valid.sum()),
                "cell_area_ha": cell_area_ha,
            },
            "simulator": {
                "training_transition_profile": train,
                "candidate_count": len(simulations),
                "candidates": list(simulations),
                "baseline_candidate_ids": list(baselines),
                "twm_candidate_ids": list(twm_candidates),
                "metrics": metrics,
                "best_baseline_by_change_fom": best_baseline,
                "best_twm_by_change_fom": best_twm_by_change,
                "selected_planner_candidate": selected,
            },
            "planner": planner,
            "renderer": {
                "assets": renderer_assets,
                "rendered": bool(renderer_assets),
            },
            "comparison_interpretation": {
                "what_this_adds_over_previous_validation": [
                    "It produces full pixel/grid prediction maps for the 2005->2006 holdout period.",
                    "It computes same-pixel metrics against landuse2006.tif.",
                    "It adds transparent baseline candidates and TWM planning scenarios on the same data.",
                    "It renders simulator and planner outputs as comparison figures.",
                ],
                "what_this_still_does_not_validate": [
                    "It is not an actual GeoSOS/FLUS software run because no GeoSOS/FLUS predicted output map is available in the provided data.",
                    "The flus_like_proxy is a transparent proxy using Markov demand, neighborhood, suitability and conversion constraints; it must not be cited as the official FLUS result.",
                    "The planner optimizes policy-style objectives, so the selected plan may not maximize ex-post pixel accuracy.",
                ],
                "next_tasks": [
                    "Export or obtain the actual GeoSOS/FLUS 2006 predicted map and add it as an official baseline row.",
                    "Add a calibrated ANN/logistic suitability model over dtcity, dtroad, dtfreeway and dtrailway.",
                    "Add production governance layers before claiming TWM beats GeoSOS/FLUS in natural-resource decision support.",
                ],
            },
        }


def extract_zip(zip_path: Path, output_dir: Path) -> Path:
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(output_dir)
    candidates = [path for path in output_dir.iterdir() if path.is_dir()]
    if len(candidates) == 1:
        return candidates[0]
    return output_dir


def load_driver_layers(root: Path, shape: tuple[int, int]) -> dict[str, Any]:
    import rasterio

    variable_dir = root / "Variables Data"
    names = ("dtcity", "dtfreeway", "dtrailway", "dtroad")
    layers: dict[str, np.ndarray] = {}
    summary: dict[str, Any] = {}
    for name in names:
        path = variable_dir / name
        if not path.exists():
            layers[name] = np.zeros(shape, dtype=np.float32)
            summary[name] = {"status": "missing", "min": None, "max": None}
            continue
        with rasterio.open(path) as src:
            arr = src.read(1, masked=True).astype(np.float32)
            data = np.asarray(arr.filled(np.nan), dtype=np.float32)
        norm = normalize_01(data)
        layers[name] = norm
        finite = data[np.isfinite(data)]
        summary[name] = {
            "status": "loaded",
            "min": float(finite.min()) if finite.size else None,
            "max": float(finite.max()) if finite.size else None,
        }
    urban_access = normalize_01(
        layers["dtcity"] * 0.35
        + layers["dtroad"] * 0.25
        + layers["dtfreeway"] * 0.25
        + layers["dtrailway"] * 0.15
    )
    layers["urban_access"] = urban_access
    summary["urban_access"] = {
        "status": "derived",
        "min": float(np.nanmin(urban_access)),
        "max": float(np.nanmax(urban_access)),
    }
    return {"layers": layers, "summary": summary}


def normalize_01(arr: np.ndarray) -> np.ndarray:
    data = np.asarray(arr, dtype=np.float32)
    finite = np.isfinite(data)
    if not finite.any():
        return np.zeros(data.shape, dtype=np.float32)
    lo = float(np.nanmin(data[finite]))
    hi = float(np.nanmax(data[finite]))
    if math.isclose(lo, hi):
        return np.zeros(data.shape, dtype=np.float32)
    out = (data - lo) / (hi - lo)
    out[~np.isfinite(out)] = 0.0
    return np.clip(out, 0.0, 1.0).astype(np.float32)


def valid_mask(
    landuse2000: np.ndarray,
    landuse2005: np.ndarray,
    landuse2006: np.ndarray,
    landuse_info: dict[str, Any],
    rasters: dict[int, dict[str, Any]],
) -> np.ndarray:
    invalid_values = {0, int(landuse_info.get("null_value", -9999))}
    for raster in rasters.values():
        nodata = raster.get("nodata")
        if nodata is not None and np.isfinite(float(nodata)):
            invalid_values.add(int(nodata))
    valid = np.ones(landuse2005.shape, dtype=bool)
    for value in invalid_values:
        valid &= landuse2000 != value
        valid &= landuse2005 != value
        valid &= landuse2006 != value
    return valid


def build_training_transition_profile(
    start: np.ndarray,
    end: np.ndarray,
    valid: np.ndarray,
    classes: list[int],
    *,
    train_years: int,
    horizon_years: int,
) -> dict[str, Any]:
    pair_counts: Counter[tuple[int, int]] = Counter()
    source_counts: Counter[int] = Counter()
    target_counts: Counter[int] = Counter()
    for source, target in zip(start[valid].astype(int).tolist(), end[valid].astype(int).tolist()):
        pair_counts[(source, target)] += 1
        source_counts[source] += 1
        target_counts[target] += 1
    pair_budgets = {}
    for (source, target), count in sorted(pair_counts.items()):
        if source == target:
            continue
        budget = int(round(count * horizon_years / max(1, train_years)))
        if budget > 0:
            pair_budgets[f"{source}->{target}"] = budget
    class_delta_budget = {
        str(cls): int(round((target_counts.get(cls, 0) - source_counts.get(cls, 0)) * horizon_years / max(1, train_years)))
        for cls in classes
    }
    return {
        "schema": "territory_world_model.geosos_transition_training_profile.v1",
        "train_years": train_years,
        "horizon_years": horizon_years,
        "pair_counts": {f"{s}->{t}": c for (s, t), c in sorted(pair_counts.items())},
        "source_counts": {str(k): v for k, v in sorted(source_counts.items())},
        "target_counts": {str(k): v for k, v in sorted(target_counts.items())},
        "projected_pair_budgets": pair_budgets,
        "projected_class_delta_budget": class_delta_budget,
        "changed_cell_budget": int(sum(pair_budgets.values())),
    }


def build_simulation_candidates(model_inputs: dict[str, Any]) -> dict[str, np.ndarray]:
    initial = model_inputs["initial"]
    valid = model_inputs["valid"]
    train = model_inputs["train"]
    pair_budgets = parse_pair_budgets(train["projected_pair_budgets"])
    simulations = {
        "persistence": initial.copy(),
        "markov_pair_budget": allocate_pair_budget(model_inputs, pair_budgets, strategy="markov", hard_constraints=False),
        "ca_neighborhood": allocate_pair_budget(model_inputs, pair_budgets, strategy="ca_neighborhood", hard_constraints=True),
        "flus_like_proxy": allocate_pair_budget(model_inputs, pair_budgets, strategy="flus_like", hard_constraints=True),
        "twm_balanced": allocate_pair_budget(model_inputs, pair_budgets, strategy="twm_balanced", hard_constraints=True),
        "twm_compact_growth": allocate_pair_budget(model_inputs, scale_urban_budget(pair_budgets, 1.0, model_inputs["urban_value"]), strategy="twm_compact_growth", hard_constraints=True),
        "twm_accessibility_corridor": allocate_pair_budget(model_inputs, scale_urban_budget(pair_budgets, 1.15, model_inputs["urban_value"]), strategy="twm_accessibility_corridor", hard_constraints=True),
        "twm_arable_protection": allocate_pair_budget(model_inputs, scale_urban_budget(pair_budgets, 0.82, model_inputs["urban_value"]), strategy="twm_arable_protection", hard_constraints=True),
    }
    for prediction in simulations.values():
        prediction[~valid] = 0
    return simulations


def parse_pair_budgets(raw: dict[str, Any]) -> dict[tuple[int, int], int]:
    budgets: dict[tuple[int, int], int] = {}
    for key, value in raw.items():
        source, target = key.split("->", 1)
        budgets[(int(source), int(target))] = int(value)
    return budgets


def scale_urban_budget(
    budgets: dict[tuple[int, int], int],
    multiplier: float,
    urban_value: int,
) -> dict[tuple[int, int], int]:
    scaled = {}
    for pair, value in budgets.items():
        scaled[pair] = int(round(value * multiplier)) if pair[1] == urban_value else value
    return scaled


def allocate_pair_budget(
    model_inputs: dict[str, Any],
    pair_budgets: dict[tuple[int, int], int],
    *,
    strategy: str,
    hard_constraints: bool,
) -> np.ndarray:
    initial = model_inputs["initial"]
    valid = model_inputs["valid"]
    suitability = model_inputs["suitability"]
    landuse_info = model_inputs["landuse_info"]
    urban_value = int(model_inputs["urban_value"])
    prediction = initial.copy()
    reserved = np.zeros(initial.shape, dtype=bool)
    scores = score_layers(model_inputs, strategy)

    ordered_pairs = sorted(pair_budgets.items(), key=lambda item: (item[0][1] != urban_value, -item[1], item[0]))
    for (source, target), budget in ordered_pairs:
        if budget <= 0 or source == target:
            continue
        allowed_by_matrix = transition_allowed(suitability, source, target)
        if hard_constraints and not allowed_by_matrix:
            continue
        candidate_mask = valid & (~reserved) & (prediction == source)
        if hard_constraints:
            candidate_mask &= allowed_by_matrix
        if not np.any(candidate_mask):
            continue
        score = scores.get(target)
        if score is None:
            score = stable_cell_hash(initial.shape, target)
        score = score.copy()
        score += transition_prior(model_inputs, source, target)
        score += source_strategy_adjustment(initial, source, target, strategy, urban_value)
        if not allowed_by_matrix:
            score -= 2.0
        rows, cols = np.where(candidate_mask)
        if rows.size == 0:
            continue
        values = score[rows, cols]
        take = min(int(budget), rows.size)
        if take <= 0:
            continue
        selected_idx = np.argpartition(values, -take)[-take:]
        rr = rows[selected_idx]
        cc = cols[selected_idx]
        prediction[rr, cc] = target
        reserved[rr, cc] = True
    prediction[~valid] = 0
    return prediction


def score_layers(model_inputs: dict[str, Any], strategy: str) -> dict[int, np.ndarray]:
    initial = model_inputs["initial"]
    valid = model_inputs["valid"]
    classes = model_inputs["classes"]
    drivers = model_inputs["drivers"]["layers"]
    urban_value = int(model_inputs["urban_value"])
    urban_access = drivers.get("urban_access", np.zeros(initial.shape, dtype=np.float32))
    hash_base = stable_cell_hash(initial.shape, 17)
    scores: dict[int, np.ndarray] = {}
    for cls in classes:
        neighborhood = neighbor_density(initial, cls, valid)
        if cls == urban_value:
            if strategy == "markov":
                score = hash_base
            elif strategy == "ca_neighborhood":
                score = 0.65 * neighborhood + 0.25 * urban_access + 0.10 * hash_base
            elif strategy == "flus_like":
                score = 0.42 * urban_access + 0.38 * neighborhood + 0.20 * hash_base
            elif strategy == "twm_compact_growth":
                score = 0.58 * neighborhood + 0.27 * urban_access + 0.15 * hash_base
            elif strategy == "twm_accessibility_corridor":
                score = 0.62 * urban_access + 0.22 * neighborhood + 0.16 * hash_base
            elif strategy == "twm_arable_protection":
                score = 0.45 * urban_access + 0.35 * neighborhood + 0.20 * hash_base
            else:
                score = 0.45 * urban_access + 0.40 * neighborhood + 0.15 * hash_base
        else:
            score = 0.55 * neighborhood + 0.25 * (1.0 - urban_access) + 0.20 * stable_cell_hash(initial.shape, cls)
        score = np.asarray(score, dtype=np.float32)
        score[~valid] = -999.0
        scores[cls] = score
    return scores


def transition_prior(model_inputs: dict[str, Any], source: int, target: int) -> float:
    counts = model_inputs["train"]["pair_counts"]
    source_counts = model_inputs["train"]["source_counts"]
    pair_count = float(counts.get(f"{source}->{target}", 0))
    source_count = float(source_counts.get(str(source), 0))
    if source_count <= 0:
        return 0.0
    return min(0.35, pair_count / source_count)


def source_strategy_adjustment(
    initial: np.ndarray,
    source: int,
    target: int,
    strategy: str,
    urban_value: int,
) -> np.ndarray | float:
    if target != urban_value:
        return 0.0
    if strategy == "twm_arable_protection":
        adjustment = np.zeros(initial.shape, dtype=np.float32)
        adjustment[initial == 1] -= 0.55
        adjustment[initial == 2] -= 0.30
        adjustment[initial == 3] += 0.25
        adjustment[initial == 6] += 0.40
        return adjustment
    if strategy == "twm_balanced":
        adjustment = np.zeros(initial.shape, dtype=np.float32)
        adjustment[initial == 1] -= 0.16
        adjustment[initial == 2] -= 0.10
        adjustment[initial == 6] += 0.18
        return adjustment
    if strategy == "twm_compact_growth":
        adjustment = np.zeros(initial.shape, dtype=np.float32)
        adjustment[initial == 1] -= 0.10
        adjustment[initial == 2] -= 0.08
        return adjustment
    return 0.0


def neighbor_density(arr: np.ndarray, cls: int, valid: np.ndarray) -> np.ndarray:
    mask = ((arr == cls) & valid).astype(np.float32)
    padded = np.pad(mask, 1, mode="constant", constant_values=0.0)
    total = np.zeros(arr.shape, dtype=np.float32)
    for dr in (0, 1, 2):
        for dc in (0, 1, 2):
            if dr == 1 and dc == 1:
                continue
            total += padded[dr : dr + arr.shape[0], dc : dc + arr.shape[1]]
    return total / 8.0


def stable_cell_hash(shape: tuple[int, int], salt: int) -> np.ndarray:
    rows, cols = np.indices(shape)
    hashed = (rows * 73856093 + cols * 19349663 + salt * 83492791) % 1000003
    return (hashed.astype(np.float32) / 1000003.0).astype(np.float32)


def pixel_metrics(
    prediction: np.ndarray,
    actual: np.ndarray,
    initial: np.ndarray,
    valid: np.ndarray,
    classes: list[int],
    suitability: dict[str, Any],
    landuse_info: dict[str, Any],
    cell_area_ha: float,
    *,
    urban_value: int,
) -> dict[str, Any]:
    pred = prediction[valid].astype(int)
    truth = actual[valid].astype(int)
    base = initial[valid].astype(int)
    n = int(valid.sum())
    correct = int((pred == truth).sum())
    confusion = {(int(a), int(p)): int(((truth == a) & (pred == p)).sum()) for a in classes for p in classes}
    po = correct / max(1, n)
    pred_counts = Counter(pred.tolist())
    truth_counts = Counter(truth.tolist())
    pe = sum(pred_counts.get(cls, 0) * truth_counts.get(cls, 0) for cls in classes) / float(max(1, n * n))
    kappa = (po - pe) / max(1e-12, 1.0 - pe)

    pred_change = pred != base
    actual_change = truth != base
    tp = int((pred_change & actual_change).sum())
    fp = int((pred_change & ~actual_change).sum())
    fn = int((~pred_change & actual_change).sum())
    change_precision = tp / max(1, tp + fp)
    change_recall = tp / max(1, tp + fn)
    change_f1 = harmonic(change_precision, change_recall)
    change_fom = tp / max(1, tp + fp + fn)
    transition_accuracy_on_actual_change = float((pred[actual_change] == truth[actual_change]).sum() / max(1, int(actual_change.sum())))

    pred_urban_expansion = (base != urban_value) & (pred == urban_value)
    actual_urban_expansion = (base != urban_value) & (truth == urban_value)
    urban_tp = int((pred_urban_expansion & actual_urban_expansion).sum())
    urban_fp = int((pred_urban_expansion & ~actual_urban_expansion).sum())
    urban_fn = int((~pred_urban_expansion & actual_urban_expansion).sum())
    urban_precision = urban_tp / max(1, urban_tp + urban_fp)
    urban_recall = urban_tp / max(1, urban_tp + urban_fn)

    violations = 0
    predicted_changed = 0
    for source, target in zip(base.tolist(), pred.tolist()):
        if source == target:
            continue
        predicted_changed += 1
        if not transition_allowed(suitability, int(source), int(target)):
            violations += 1
    per_class_f1 = {}
    for cls in classes:
        cls_tp = int(((pred == cls) & (truth == cls)).sum())
        cls_fp = int(((pred == cls) & (truth != cls)).sum())
        cls_fn = int(((pred != cls) & (truth == cls)).sum())
        precision = cls_tp / max(1, cls_tp + cls_fp)
        recall = cls_tp / max(1, cls_tp + cls_fn)
        per_class_f1[str(cls)] = round(harmonic(precision, recall), 6)

    return {
        "schema": "territory_world_model.geosos_pixel_metric.v1",
        "valid_cell_count": n,
        "overall_accuracy": round(po, 6),
        "kappa": round(kappa, 6),
        "correct_cell_count": correct,
        "predicted_change_count": int(pred_change.sum()),
        "actual_change_count": int(actual_change.sum()),
        "change_hit_count": tp,
        "change_false_alarm_count": fp,
        "change_miss_count": fn,
        "change_precision": round(change_precision, 6),
        "change_recall": round(change_recall, 6),
        "change_f1": round(change_f1, 6),
        "change_fom": round(change_fom, 6),
        "transition_accuracy_on_actual_change": round(transition_accuracy_on_actual_change, 6),
        "urban_expansion_precision": round(urban_precision, 6),
        "urban_expansion_recall": round(urban_recall, 6),
        "urban_expansion_f1": round(harmonic(urban_precision, urban_recall), 6),
        "urban_expansion_hit_count": urban_tp,
        "predicted_urban_expansion_count": int(pred_urban_expansion.sum()),
        "actual_urban_expansion_count": int(actual_urban_expansion.sum()),
        "predicted_changed_area_ha": round(float(pred_change.sum()) * cell_area_ha, 4),
        "actual_changed_area_ha": round(float(actual_change.sum()) * cell_area_ha, 4),
        "predicted_urban_expansion_area_ha": round(float(pred_urban_expansion.sum()) * cell_area_ha, 4),
        "actual_urban_expansion_area_ha": round(float(actual_urban_expansion.sum()) * cell_area_ha, 4),
        "predicted_arable_to_urban_count": int(((base == 1) & (pred == urban_value)).sum()),
        "actual_arable_to_urban_count": int(((base == 1) & (truth == urban_value)).sum()),
        "predicted_woodland_to_urban_count": int(((base == 2) & (pred == urban_value)).sum()),
        "actual_woodland_to_urban_count": int(((base == 2) & (truth == urban_value)).sum()),
        "suitability_violation_count": violations,
        "suitability_violation_rate": round(violations / max(1, predicted_changed), 6),
        "macro_f1": round(float(np.mean(list(per_class_f1.values()))) if per_class_f1 else 0.0, 6),
        "per_class_f1": per_class_f1,
        "landuse_labels": {str(cls): landuse_label(landuse_info, cls) for cls in classes},
    }


def harmonic(precision: float, recall: float) -> float:
    if precision + recall <= 0:
        return 0.0
    return 2.0 * precision * recall / (precision + recall)


def build_planner_report(
    simulations: dict[str, np.ndarray],
    metrics: dict[str, dict[str, Any]],
    model_inputs: dict[str, Any],
    cell_area_ha: float,
) -> dict[str, Any]:
    initial = model_inputs["initial"]
    valid = model_inputs["valid"]
    drivers = model_inputs["drivers"]["layers"]
    urban_value = int(model_inputs["urban_value"])
    urban_neighbor = neighbor_density(initial, urban_value, valid)
    urban_access = drivers.get("urban_access", np.zeros(initial.shape, dtype=np.float32))
    target_urban_budget = sum(
        value for (source, target), value in parse_pair_budgets(model_inputs["train"]["projected_pair_budgets"]).items() if target == urban_value
    )

    candidate_ids = [name for name in simulations if name.startswith("twm_")]
    candidate_scores = []
    for name in candidate_ids:
        pred = simulations[name]
        m = metrics[name]
        new_urban = valid & (initial != urban_value) & (pred == urban_value)
        demand_fit = 1.0 - abs(int(new_urban.sum()) - target_urban_budget) / max(1, target_urban_budget)
        demand_fit = max(0.0, min(1.0, demand_fit))
        compactness = float(urban_neighbor[new_urban].mean()) if np.any(new_urban) else 0.0
        accessibility = float(urban_access[new_urban].mean()) if np.any(new_urban) else 0.0
        arable_share = m["predicted_arable_to_urban_count"] / max(1, m["predicted_urban_expansion_count"])
        woodland_share = m["predicted_woodland_to_urban_count"] / max(1, m["predicted_urban_expansion_count"])
        constraint_score = 1.0 - float(m["suitability_violation_rate"])
        protection_score = 1.0 - min(1.0, arable_share * 0.75 + woodland_share * 0.55)
        policy_score = (
            0.26 * demand_fit
            + 0.22 * constraint_score
            + 0.18 * protection_score
            + 0.16 * compactness
            + 0.12 * accessibility
            + 0.06 * float(m["change_fom"])
        )
        candidate_scores.append(
            {
                "candidate_id": name,
                "policy_score": round(policy_score, 6),
                "demand_fit": round(demand_fit, 6),
                "constraint_score": round(constraint_score, 6),
                "protection_score": round(protection_score, 6),
                "compactness": round(compactness, 6),
                "accessibility": round(accessibility, 6),
                "ex_post_change_fom": m["change_fom"],
                "ex_post_overall_accuracy": m["overall_accuracy"],
                "predicted_urban_expansion_area_ha": m["predicted_urban_expansion_area_ha"],
                "predicted_arable_to_urban_area_ha": round(m["predicted_arable_to_urban_count"] * cell_area_ha, 4),
            }
        )
    ranking = sorted(candidate_scores, key=lambda item: item["policy_score"], reverse=True)
    selected = ranking[0]["candidate_id"] if ranking else None
    return {
        "schema": "territory_world_model.dongguan_geosos_planner_report.v1",
        "status": "pass" if selected else "blocked",
        "planner_role": "rank_twm_policy_scenarios_using_simulator_outputs",
        "target_urban_expansion_budget_cells": int(target_urban_budget),
        "target_urban_expansion_budget_area_ha": round(target_urban_budget * cell_area_ha, 4),
        "ranking_policy": {
            "demand_fit": 0.26,
            "constraint_score": 0.22,
            "protection_score": 0.18,
            "compactness": 0.16,
            "accessibility": 0.12,
            "ex_post_change_fom_diagnostic": 0.06,
        },
        "ranking": ranking,
        "selected_candidate_id": selected,
        "claim_boundary": "policy_ranking_on_tutorial_data_not_production_decision",
    }


def render_assets(
    asset_dir: Path,
    simulations: dict[str, np.ndarray],
    metrics: dict[str, dict[str, Any]],
    planner: dict[str, Any],
    initial: np.ndarray,
    actual: np.ndarray,
    valid: np.ndarray,
    landuse_info: dict[str, Any],
    cell_area_ha: float,
) -> dict[str, str]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import BoundaryNorm, ListedColormap
    from matplotlib.patches import Patch

    plt.rcParams["font.sans-serif"] = ["PingFang SC", "Heiti SC", "Arial Unicode MS", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False

    labels = {int(key): value["zh"] for key, value in (landuse_info.get("types") or {}).items()}
    colors = {0: "#f5f5f2", 1: "#f4d35e", 2: "#2f7d32", 3: "#8fbc8f", 4: "#3b82c4", 5: "#c2412d", 6: "#b8b0a4"}
    cmap = ListedColormap([colors.get(i, "#cccccc") for i in range(max(7, max(labels) + 1))])
    norm = BoundaryNorm(np.arange(-0.5, cmap.N + 0.5, 1), cmap.N)

    selected = planner.get("selected_candidate_id") or "twm_balanced"
    map_names = ["initial_2005", "actual_2006", "persistence", "flus_like_proxy", selected]
    map_arrays = {
        "initial_2005": initial,
        "actual_2006": actual,
        **simulations,
    }
    fig, axes = plt.subplots(1, len(map_names), figsize=(18, 4.8), constrained_layout=True)
    for ax, name in zip(axes, map_names):
        arr = map_arrays[name].copy()
        arr[~valid] = 0
        ax.imshow(arr, cmap=cmap, norm=norm, interpolation="nearest")
        title = name.replace("_", " ")
        if name in metrics:
            title += f"\nOA={metrics[name]['overall_accuracy']:.3f}, FoM={metrics[name]['change_fom']:.3f}"
        ax.set_title(title, fontsize=10)
        ax.set_xticks([])
        ax.set_yticks([])
    handles = [Patch(facecolor=colors.get(k, "#ccc"), edgecolor="none", label=f"{k} {labels[k]}") for k in sorted(labels)]
    fig.legend(handles=handles, loc="lower center", ncol=min(6, len(handles)), frameon=False, fontsize=9)
    prediction_maps = asset_dir / "twm_dongguan_simopt_prediction_maps.png"
    fig.savefig(prediction_maps, bbox_inches="tight", dpi=180)
    plt.close(fig)

    metric_names = list(metrics)
    fig, ax = plt.subplots(figsize=(11, 5.2), constrained_layout=True)
    x = np.arange(len(metric_names))
    width = 0.25
    ax.bar(x - width, [metrics[n]["overall_accuracy"] for n in metric_names], width, label="overall accuracy", color="#5b6c8f")
    ax.bar(x, [metrics[n]["change_fom"] for n in metric_names], width, label="change FoM", color="#c2412d")
    ax.bar(x + width, [metrics[n]["urban_expansion_f1"] for n in metric_names], width, label="urban expansion F1", color="#2f7d32")
    ax.set_xticks(x)
    ax.set_xticklabels(metric_names, rotation=35, ha="right")
    ax.set_ylim(0, 1.02)
    ax.grid(axis="y", color="#e6e6e6", linewidth=0.8)
    ax.legend(frameon=False)
    ax.set_title("DongGuan 2005->2006 pixel/grid simulation metrics")
    metric_plot = asset_dir / "twm_dongguan_simopt_metrics.png"
    fig.savefig(metric_plot, bbox_inches="tight", dpi=180)
    plt.close(fig)

    ranking = planner.get("ranking") or []
    fig, ax = plt.subplots(figsize=(9.5, 4.8), constrained_layout=True)
    names = [item["candidate_id"] for item in ranking][::-1]
    values = [item["policy_score"] for item in ranking][::-1]
    ax.barh(names, values, color="#5a7f60")
    ax.set_xlim(0, max(1.0, max(values, default=0.0) * 1.1))
    ax.grid(axis="x", color="#e6e6e6", linewidth=0.8)
    ax.set_title("TWM planner policy ranking on DongGuan tutorial data")
    for yi, value in enumerate(values):
        ax.text(value, yi, f" {value:.3f}", va="center", fontsize=9)
    planner_plot = asset_dir / "twm_dongguan_simopt_planner_candidates.png"
    fig.savefig(planner_plot, bbox_inches="tight", dpi=180)
    plt.close(fig)

    fig, axes = plt.subplots(1, 3, figsize=(12, 4.4), constrained_layout=True)
    for ax, (title, arr) in zip(
        axes,
        [
            ("Actual change 2005->2006", actual != initial),
            ("FLUS-like proxy change", simulations["flus_like_proxy"] != initial),
            (f"Selected TWM change\n{selected}", simulations[selected] != initial),
        ],
    ):
        rgb = np.zeros((*arr.shape, 4), dtype=float)
        rgb[..., :3] = np.array([0.94, 0.94, 0.91])
        rgb[..., 3] = 1.0
        rgb[arr & valid, :3] = np.array([0.76, 0.20, 0.14])
        ax.imshow(rgb, interpolation="nearest")
        ax.set_title(title, fontsize=10)
        ax.set_xticks([])
        ax.set_yticks([])
    change_plot = asset_dir / "twm_dongguan_simopt_change_comparison.png"
    fig.savefig(change_plot, bbox_inches="tight", dpi=180)
    plt.close(fig)

    return {
        "prediction_maps": rel_asset(prediction_maps),
        "metrics": rel_asset(metric_plot),
        "planner_candidates": rel_asset(planner_plot),
        "change_comparison": rel_asset(change_plot),
    }


def rel_asset(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT / "docs"))
    except ValueError:
        return str(path)


def render_markdown_report(report: dict[str, Any]) -> str:
    metrics = report["simulator"]["metrics"]
    planner = report["planner"]
    assets = report["renderer"]["assets"]
    lines = [
        "# TWM DongGuan GeoSOS 像元级模拟与规划优化对比",
        "",
        "更新日期：2026-06-22",
        "",
        "## 1. 结论",
        "",
        "这次结果比前一版“数据适配和门控通过”更进一步：已经生成 2005->2006 holdout 的像元级预测图、同口径像元指标、透明 baseline，以及 TWM planner 候选方案排序。",
        "",
        "但这里仍然不能写成“已经击败官方 GeoSOS/FLUS”。原因是当前数据包没有提供 GeoSOS/FLUS 软件实际导出的 2006 预测图；本报告中的 `flus_like_proxy` 是透明代理基线，不是官方 FLUS 结果。",
        "",
        "## 2. 渲染器输出",
        "",
        f"![Prediction maps]({assets.get('prediction_maps', '')})",
        "",
        f"![Change comparison]({assets.get('change_comparison', '')})",
        "",
        "## 3. 模拟器指标",
        "",
        f"![Simulation metrics]({assets.get('metrics', '')})",
        "",
        "| candidate | OA | Kappa | change FoM | change F1 | urban F1 | violation rate | predicted change area |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, metric in metrics.items():
        lines.append(
            f"| {name} | {metric['overall_accuracy']:.6f} | {metric['kappa']:.6f} | {metric['change_fom']:.6f} | "
            f"{metric['change_f1']:.6f} | {metric['urban_expansion_f1']:.6f} | {metric['suitability_violation_rate']:.6f} | "
            f"{metric['predicted_changed_area_ha']:.2f} ha |"
        )
    lines.extend(
        [
            "",
            "## 4. 规划器候选方案",
            "",
            f"![Planner candidates]({assets.get('planner_candidates', '')})",
            "",
            f"规划器选择：`{planner.get('selected_candidate_id')}`。",
            "",
            "| candidate | policy score | demand fit | constraint | protection | compactness | accessibility | ex-post FoM |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for item in planner.get("ranking") or []:
        lines.append(
            f"| {item['candidate_id']} | {item['policy_score']:.6f} | {item['demand_fit']:.6f} | {item['constraint_score']:.6f} | "
            f"{item['protection_score']:.6f} | {item['compactness']:.6f} | {item['accessibility']:.6f} | {item['ex_post_change_fom']:.6f} |"
        )
    lines.extend(
        [
            "",
            "## 5. 研究边界",
            "",
            "可以说：TWM 已经能在 DongGuan GeoSOS 教程数据上形成渲染器、模拟器、规划器组合输出，且能与 persistence、Markov、CA-neighborhood、FLUS-like proxy 做同案指标对比。",
            "",
            "不能说：TWM 已经击败官方 GeoSOS/FLUS。要做这个结论，必须拿到 GeoSOS/FLUS 对同一训练期和 holdout 期导出的预测图，加入同一张指标表。",
            "",
            "下一步应该补：实际 FLUS 输出图、ANN/logistic suitability、完整驱动因子校准、以及自然资源业务治理图层。",
            "",
        ]
    )
    return "\n".join(lines)


if __name__ == "__main__":
    main()
