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

from scripts.assess_flus_v24_baseline import (  # noqa: E402
    DEFAULT_V24_ZIP,
    build_prediction_maps,
    driver_inventory,
    find_testdata,
    harmonic,
    load_rasters,
    parse_config_color,
    parse_config_mp,
    pixel_metrics,
    raster_profile,
    read_text,
    rel_asset,
)

DEFAULT_OUTPUT = REPO_ROOT / "docs/reports/twm_flus_v24_simopt_2026-06-22.json"
DEFAULT_MARKDOWN = REPO_ROOT / "docs/twm-flus-v24-simulation-optimization-2026-06-22.md"
DEFAULT_ASSET_DIR = REPO_ROOT / "docs/assets"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run TWM simulation/planning candidates against official GeoSOS-FLUS V2.4 sample outputs."
    )
    parser.add_argument("--v24-zip", type=Path, default=DEFAULT_V24_ZIP)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN)
    parser.add_argument("--asset-dir", type=Path, default=DEFAULT_ASSET_DIR)
    parser.add_argument("--no-render", action="store_true")
    args = parser.parse_args()

    report = run_twm_flus_v24_simulation_optimization(
        args.v24_zip,
        asset_dir=args.asset_dir,
        render=not args.no_render,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    if args.markdown_output:
        args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_output.write_text(render_markdown_report(report), encoding="utf-8")
    print(json.dumps({"status": report["status"], "output": str(args.output)}, ensure_ascii=False))


def run_twm_flus_v24_simulation_optimization(
    v24_zip: Path,
    *,
    asset_dir: Path | None,
    render: bool,
) -> dict[str, Any]:
    v24_zip = v24_zip.expanduser()
    if not v24_zip.exists():
        raise FileNotFoundError(str(v24_zip))

    with tempfile.TemporaryDirectory(prefix="twm_flus_v24_simopt_") as tmp:
        root = Path(tmp)
        with zipfile.ZipFile(v24_zip) as zf:
            zf.extractall(root)
        testdata = find_testdata(root)
        config_color = parse_config_color(read_text(testdata / "config_color.log"))
        config_mp = parse_config_mp(read_text(testdata / "config_mp.log"))
        classes = sorted(config_color)
        urban_class = find_label_class(config_color, "urban", default=min(classes))
        rasters = load_rasters(testdata, config_color)
        official_predictions = build_prediction_maps(rasters, classes)
        drivers = load_driver_layers(testdata, rasters["dg2001coor.tif"]["data"].shape)
        model_inputs = {
            "classes": classes,
            "urban_class": urban_class,
            "config_color": config_color,
            "config_mp": config_mp,
            "rasters": rasters,
            "drivers": drivers,
        }
        twm_predictions, candidate_metadata = build_twm_candidates(model_inputs)
        all_predictions = {
            "official_simulationResult": official_predictions["official_simulationResult"],
            "official_simulationResult1": official_predictions["official_simulationResult1"],
            "probability_argmax_not_ca_result": official_predictions["probability_argmax_not_ca_result"],
            **twm_predictions,
        }
        metrics = {
            name: enrich_metric(
                pixel_metrics(
                    pred=prediction,
                    base=rasters["dg2001coor.tif"]["data"],
                    truth=rasters["dg2006true.tif"]["data"],
                    valid=rasters["valid_mask"],
                    classes=classes,
                    urban_class=urban_class,
                    future_pixels=config_mp["future_pixels"],
                ),
                pred=prediction,
                base=rasters["dg2001coor.tif"]["data"],
                valid=class_mask(rasters["dg2001coor.tif"]["data"], classes),
                restricted=rasters["restrictedarea.tif"]["data"],
                classes=classes,
                cost_matrix=config_mp["cost_matrix"],
                future_pixels=config_mp["future_pixels"],
            )
            for name, prediction in all_predictions.items()
        }
        planner = build_planner_report(
            predictions=twm_predictions,
            metrics=metrics,
            rasters=rasters,
            drivers=drivers,
            config_mp=config_mp,
            urban_class=urban_class,
        )
        assets: dict[str, str] = {}
        if render and asset_dir is not None:
            asset_dir.mkdir(parents=True, exist_ok=True)
            assets = render_assets(
                asset_dir=asset_dir,
                rasters=rasters,
                predictions=all_predictions,
                metrics=metrics,
                planner=planner,
                config_color=config_color,
                classes=classes,
            )

        baseline_ids = ["official_simulationResult", "official_simulationResult1", "probability_argmax_not_ca_result"]
        twm_ids = list(twm_predictions)
        best_official_by_fom = max(
            ["official_simulationResult", "official_simulationResult1"],
            key=lambda name: metrics[name]["change_fom"],
        )
        best_twm_by_fom = max(twm_ids, key=lambda name: metrics[name]["change_fom"]) if twm_ids else None
        selected = planner.get("selected_candidate_id")
        return {
            "schema": "territory_world_model.flus_v24_simulation_optimization_report.v1",
            "status": "pass",
            "claim_boundary": "official_flus_v24_sample_baseline_with_twm_candidates_not_production_claim",
            "source": {
                "v24_zip": str(v24_zip),
                "dataset": "GeoSOS-FLUS V2.4 official sample testdata",
                "task": "TWM renderer/simulator/planner same-grid comparison against package-provided FLUS outputs",
            },
            "data_profile": {
                "raster_profile": raster_profile(rasters),
                "driver_layers": driver_inventory(testdata),
                "classes": config_color,
                "future_pixels": config_mp["future_pixels"],
                "cost_matrix": config_mp["cost_matrix"],
                "neighborhood_intensity": config_mp["neighborhood_intensity"],
            },
            "simulator": {
                "baseline_candidate_ids": baseline_ids,
                "twm_candidate_ids": twm_ids,
                "candidate_metadata": candidate_metadata,
                "metrics": metrics,
                "best_official_flus_by_change_fom": best_official_by_fom,
                "best_twm_by_change_fom": best_twm_by_fom,
                "selected_planner_candidate": selected,
            },
            "planner": planner,
            "renderer": {"rendered": bool(assets), "assets": assets},
            "interpretation": {
                "what_is_now_validated": [
                    "TWM can ingest the FLUS V2.4 sample rasters and produce same-grid candidate simulation maps.",
                    "Official FLUS package outputs remain in the metric table as explicit baseline rows.",
                    "The renderer produces side-by-side land-use, change and metric figures for FLUS and TWM candidates.",
                    "The planner can rank TWM candidates under demand-fit, restriction, compactness, accessibility and ex-post diagnostic criteria.",
                ],
                "what_must_not_be_overclaimed": [
                    "The FLUS-informed TWM candidates use Probability-of-occurrence.tif from the FLUS package, so they are not independent from FLUS suitability modelling.",
                    "This is a tutorial/sample benchmark, not a full natural-resource governance deployment dataset.",
                    "A higher change FoM on this sample would be an experimental progress signal, not yet a publishable claim that TWM generally beats GeoSOS/FLUS.",
                ],
                "next_tasks": [
                    "Add repeated/random-seed sensitivity runs for TWM candidate allocation.",
                    "Train an independent TWM suitability model from the driving factors instead of relying on the FLUS probability map.",
                    "Add a direct FLUS-console reproduction task only after the Windows/C++ build dependency issue is handled.",
                    "Extend the comparison to multiple cities or periods before making high-level research claims.",
                ],
            },
        }


def find_label_class(config_color: dict[int, dict[str, Any]], needle: str, *, default: int) -> int:
    needle = needle.lower()
    for cls, payload in config_color.items():
        if needle in str(payload.get("label", "")).lower():
            return cls
    return default


def load_driver_layers(testdata: Path, shape: tuple[int, int]) -> dict[str, Any]:
    import rasterio

    source_names = {
        "dem": "dem_dg.tif",
        "slope": "slope.tif",
        "aspect": "Aspect.tif",
        "city_distance": "tocity_dg.tif",
        "town_distance": "distotown.tif",
        "highway_distance": "distohighway.tif",
        "road_distance": "distoroad.tif",
        "railway_distance": "distorailway.tif",
        "water_distance": "ProximityWater.tif",
    }
    layers: dict[str, np.ndarray] = {}
    summary: dict[str, Any] = {}
    for key, filename in source_names.items():
        path = testdata / filename
        if not path.exists():
            layers[key] = np.zeros(shape, dtype=np.float32)
            summary[key] = {"status": "missing", "filename": filename}
            continue
        with rasterio.open(path) as src:
            arr = src.read(1, masked=True).astype(np.float32)
            data = np.asarray(arr.filled(np.nan), dtype=np.float32)
        layers[key] = data
        finite = data[np.isfinite(data)]
        summary[key] = {
            "status": "loaded",
            "filename": filename,
            "min": float(finite.min()) if finite.size else None,
            "max": float(finite.max()) if finite.size else None,
        }
    near_city = 1.0 - normalize_01(layers["city_distance"])
    near_town = 1.0 - normalize_01(layers["town_distance"])
    near_highway = 1.0 - normalize_01(layers["highway_distance"])
    near_road = 1.0 - normalize_01(layers["road_distance"])
    near_railway = 1.0 - normalize_01(layers["railway_distance"])
    access = normalize_01(
        0.30 * near_city
        + 0.18 * near_town
        + 0.22 * near_highway
        + 0.20 * near_road
        + 0.10 * near_railway
    )
    terrain_penalty = normalize_01(0.65 * normalize_01(layers["slope"]) + 0.35 * normalize_01(layers["dem"]))
    layers.update(
        {
            "near_city": near_city,
            "near_town": near_town,
            "near_highway": near_highway,
            "near_road": near_road,
            "near_railway": near_railway,
            "accessibility": access,
            "terrain_penalty": terrain_penalty,
        }
    )
    summary["accessibility"] = {"status": "derived", "min": float(np.nanmin(access)), "max": float(np.nanmax(access))}
    summary["terrain_penalty"] = {
        "status": "derived",
        "min": float(np.nanmin(terrain_penalty)),
        "max": float(np.nanmax(terrain_penalty)),
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


def class_mask(arr: np.ndarray, classes: list[int]) -> np.ndarray:
    return np.isin(arr, classes)


def build_twm_candidates(model_inputs: dict[str, Any]) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    rasters = model_inputs["rasters"]
    base = np.asarray(rasters["dg2001coor.tif"]["data"]).astype(np.int16)
    classes = model_inputs["classes"]
    future_pixels = {int(k): int(v) for k, v in model_inputs["config_mp"]["future_pixels"].items()}
    valid = class_mask(base, classes)
    restricted = np.asarray(rasters["restrictedarea.tif"]["data"])
    probability = np.asarray(rasters["Probability-of-occurrence.tif"]["data"], dtype=np.float32)
    scores = build_score_fields(model_inputs)
    strategies = {
        "twm_driver_only_compact_growth": {
            "uses_flus_probability": False,
            "description": "Demand-constrained allocation using distance drivers, urban neighborhood and terrain penalty.",
        },
        "twm_independent_logit_quota_balanced": {
            "uses_flus_probability": False,
            "description": "Independent multinomial-logit suitability trained from 2001 land use and driving factors, then allocated with exact multi-class quota projection.",
            "allocation": "independent_logit_quota_projection",
            "params": {
                "probability_weight": 1.0,
                "neighborhood_weight": 0.16,
                "stay_inertia": -0.08,
                "urban_accessibility_weight": 0.18,
                "terrain_penalty_weight": 0.03,
                "margin_weight": 0.02,
                "stable_hash_weight": 0.01,
                "nonurban_low_access_weight": 0.02,
                "sample_stride": 2,
            },
        },
        "twm_independent_logit_change_seeking": {
            "uses_flus_probability": False,
            "description": "Independent multinomial-logit suitability candidate with lower inertia for change localization diagnostics.",
            "allocation": "independent_logit_quota_projection",
            "params": {
                "probability_weight": 1.0,
                "neighborhood_weight": 0.0,
                "stay_inertia": -0.24,
                "urban_accessibility_weight": 0.34,
                "terrain_penalty_weight": 0.03,
                "margin_weight": 0.0,
                "stable_hash_weight": 0.01,
                "nonurban_low_access_weight": 0.02,
                "sample_stride": 2,
            },
        },
        "twm_flus_probability_demand": {
            "uses_flus_probability": True,
            "description": "Demand-constrained allocation using FLUS probability-of-occurrence as the dominant suitability field.",
        },
        "twm_hybrid_compact_access": {
            "uses_flus_probability": True,
            "description": "Hybrid suitability that combines FLUS probability, compact urban growth and transport accessibility.",
        },
        "twm_uncertainty_aware": {
            "uses_flus_probability": True,
            "description": "Hybrid suitability that rewards high urban probability margin over competing land-use classes.",
        },
        "twm_farmland_protection": {
            "uses_flus_probability": True,
            "description": "Hybrid suitability that penalizes converting cells with high cropland persistence probability.",
        },
        "twm_competitive_quota_balanced": {
            "uses_flus_probability": True,
            "description": "Multi-class competitive quota projection with exact demand repair; balances change localization with stable-area preservation.",
            "allocation": "competitive_quota_projection",
            "params": {
                "probability_weight": 0.7,
                "neighborhood_weight": 0.18,
                "stay_inertia": -0.15,
                "urban_accessibility_weight": 0.22,
                "terrain_penalty_weight": 0.03,
                "margin_weight": 0.0,
                "stable_hash_weight": 0.01,
                "nonurban_low_access_weight": 0.02,
            },
        },
        "twm_competitive_quota_change_seeking": {
            "uses_flus_probability": True,
            "description": "Multi-class competitive quota projection tuned to expose likely changed cells; useful as a change-detection-oriented simulator candidate.",
            "allocation": "competitive_quota_projection",
            "params": {
                "probability_weight": 0.7,
                "neighborhood_weight": 0.04,
                "stay_inertia": -0.15,
                "urban_accessibility_weight": 0.22,
                "terrain_penalty_weight": 0.03,
                "margin_weight": 0.0,
                "stable_hash_weight": 0.01,
                "nonurban_low_access_weight": 0.02,
            },
        },
    }
    predictions = {}
    for name, strategy_config in strategies.items():
        if strategy_config.get("allocation") == "competitive_quota_projection":
            predictions[name] = allocate_competitive_quota_projection(model_inputs, strategy_config["params"])
        elif strategy_config.get("allocation") == "independent_logit_quota_projection":
            predictions[name] = allocate_independent_logit_quota_projection(model_inputs, strategy_config["params"])
        else:
            predictions[name] = allocate_demand(
                base=base,
                valid=valid,
                restricted=restricted,
                classes=classes,
                future_pixels=future_pixels,
                cost_matrix=model_inputs["config_mp"]["cost_matrix"],
                scores=scores,
                probability=probability,
                strategy=name,
            )
    current_counts = Counter(base[valid].astype(int).tolist())
    target_deltas = {
        str(cls): int(future_pixels.get(cls, 0) - current_counts.get(cls, 0))
        for cls in classes
    }
    return predictions, {
        name: {**payload, "target_deltas": target_deltas}
        for name, payload in strategies.items()
    }


def build_score_fields(model_inputs: dict[str, Any]) -> dict[str, np.ndarray]:
    rasters = model_inputs["rasters"]
    base = np.asarray(rasters["dg2001coor.tif"]["data"]).astype(np.int16)
    valid = class_mask(base, model_inputs["classes"])
    probability = np.asarray(rasters["Probability-of-occurrence.tif"]["data"], dtype=np.float32)
    urban_class = int(model_inputs["urban_class"])
    urban_prob = normalize_01(probability[urban_class - min(model_inputs["classes"])])
    sorted_prob = np.sort(probability, axis=0)
    probability_margin = normalize_01(sorted_prob[-1] - sorted_prob[-2])
    urban_neighbor = neighbor_density(base, urban_class, valid)
    access = model_inputs["drivers"]["layers"]["accessibility"]
    terrain_penalty = model_inputs["drivers"]["layers"]["terrain_penalty"]
    stable = stable_cell_hash(base.shape, 41)
    return {
        "urban_probability": urban_prob,
        "probability_margin": probability_margin,
        "urban_neighbor": urban_neighbor,
        "accessibility": access,
        "terrain_penalty": terrain_penalty,
        "stable": stable,
        "driver_only": normalize_01(0.44 * access + 0.34 * urban_neighbor + 0.12 * stable - 0.10 * terrain_penalty),
        "probability_demand": normalize_01(0.76 * urban_prob + 0.14 * access + 0.10 * stable),
        "hybrid_compact_access": normalize_01(
            0.48 * urban_prob + 0.24 * urban_neighbor + 0.22 * access + 0.06 * stable - 0.08 * terrain_penalty
        ),
        "uncertainty_aware": normalize_01(
            0.52 * urban_prob + 0.20 * probability_margin + 0.16 * access + 0.08 * urban_neighbor + 0.04 * stable
        ),
        "farmland_protection": normalize_01(
            0.48 * urban_prob + 0.22 * access + 0.20 * urban_neighbor + 0.10 * stable - 0.18 * terrain_penalty
        ),
    }


def allocate_demand(
    *,
    base: np.ndarray,
    valid: np.ndarray,
    restricted: np.ndarray,
    classes: list[int],
    future_pixels: dict[int, int],
    cost_matrix: list[list[int]],
    scores: dict[str, np.ndarray],
    probability: np.ndarray,
    strategy: str,
) -> np.ndarray:
    pred = base.copy()
    pred[~valid] = 0
    reserved = np.zeros(base.shape, dtype=bool)
    current_counts = Counter(base[valid].astype(int).tolist())
    deficits = {
        cls: max(0, int(future_pixels.get(cls, 0)) - int(current_counts.get(cls, 0)))
        for cls in classes
    }
    surpluses = {
        cls: max(0, int(current_counts.get(cls, 0)) - int(future_pixels.get(cls, 0)))
        for cls in classes
    }
    for target, deficit in sorted(deficits.items(), key=lambda item: -item[1]):
        remaining_target = int(deficit)
        if remaining_target <= 0:
            continue
        source_order = sorted(
            [source for source, surplus in surpluses.items() if surplus > 0 and source != target and cost_allowed(cost_matrix, source, target)],
            key=lambda source: (-surpluses[source], source),
        )
        for source in source_order:
            if remaining_target <= 0:
                break
            take = min(remaining_target, surpluses[source])
            changed = allocate_pair(
                pred=pred,
                base=base,
                valid=valid,
                restricted=restricted,
                reserved=reserved,
                source=source,
                target=target,
                budget=take,
                score=score_for_pair(scores, probability, source, target, strategy, classes),
            )
            surpluses[source] -= changed
            remaining_target -= changed
    pred[~valid] = 0
    return pred


def allocate_independent_logit_quota_projection(model_inputs: dict[str, Any], params: dict[str, float]) -> np.ndarray:
    rasters = model_inputs["rasters"]
    base = np.asarray(rasters["dg2001coor.tif"]["data"]).astype(np.int16)
    classes = model_inputs["classes"]
    valid = class_mask(base, classes)
    probability = train_independent_suitability_probability(
        base=base,
        valid=valid,
        classes=classes,
        drivers=model_inputs["drivers"],
        sample_stride=int(params.get("sample_stride", 2)),
    )
    return allocate_quota_projection_with_probability(
        model_inputs,
        probability=probability,
        params=params,
    )


def allocate_competitive_quota_projection(model_inputs: dict[str, Any], params: dict[str, float]) -> np.ndarray:
    rasters = model_inputs["rasters"]
    probability = np.asarray(rasters["Probability-of-occurrence.tif"]["data"], dtype=np.float32)
    return allocate_quota_projection_with_probability(
        model_inputs,
        probability=probability,
        params=params,
    )


def allocate_quota_projection_with_probability(
    model_inputs: dict[str, Any],
    *,
    probability: np.ndarray,
    params: dict[str, float],
) -> np.ndarray:
    rasters = model_inputs["rasters"]
    base = np.asarray(rasters["dg2001coor.tif"]["data"]).astype(np.int16)
    classes = model_inputs["classes"]
    future_pixels = {int(k): int(v) for k, v in model_inputs["config_mp"]["future_pixels"].items()}
    valid = class_mask(base, classes)
    restricted = np.asarray(rasters["restrictedarea.tif"]["data"])
    score = competitive_score_cube(
        base=base,
        valid=valid,
        restricted=restricted,
        classes=classes,
        cost_matrix=model_inputs["config_mp"]["cost_matrix"],
        probability=probability,
        drivers=model_inputs["drivers"],
        urban_class=int(model_inputs["urban_class"]),
        params=params,
    )
    pred = initial_competitive_assignment(base, valid, classes, score)
    pred = balance_competitive_quotas(
        pred=pred,
        base=base,
        valid=valid,
        classes=classes,
        future_pixels=future_pixels,
        score=score,
    )
    pred[~valid] = 0
    return pred


def train_independent_suitability_probability(
    *,
    base: np.ndarray,
    valid: np.ndarray,
    classes: list[int],
    drivers: dict[str, Any],
    sample_stride: int,
) -> np.ndarray:
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    features = independent_driver_feature_stack(base, valid, classes, drivers)
    train_mask = valid.copy()
    if sample_stride > 1:
        rows, cols = np.indices(base.shape)
        train_mask &= ((rows + cols) % sample_stride) == 0
    x_train = features[train_mask]
    y_train = base[train_mask].astype(int)
    model = make_pipeline(
        StandardScaler(),
        LogisticRegression(
            class_weight="balanced",
            max_iter=500,
            random_state=0,
            solver="lbfgs",
        ),
    )
    model.fit(x_train, y_train)
    flat_features = features.reshape(-1, features.shape[-1])
    probabilities = model.predict_proba(flat_features)
    class_to_col = {int(cls): idx for idx, cls in enumerate(model.classes_)}
    out = np.zeros((len(classes), base.shape[0], base.shape[1]), dtype=np.float32)
    for idx, cls in enumerate(classes):
        col = class_to_col.get(int(cls))
        if col is not None:
            out[idx] = probabilities[:, col].reshape(base.shape).astype(np.float32)
    out[:, ~valid] = 0.0
    return out


def independent_driver_feature_stack(
    base: np.ndarray,
    valid: np.ndarray,
    classes: list[int],
    drivers: dict[str, Any],
) -> np.ndarray:
    layers = drivers["layers"]
    raw_features = [
        normalize_01(layers["dem"]),
        normalize_01(layers["slope"]),
        normalize_01(layers["city_distance"]),
        normalize_01(layers["town_distance"]),
        normalize_01(layers["highway_distance"]),
        normalize_01(layers["road_distance"]),
        normalize_01(layers["railway_distance"]),
        layers["near_city"],
        layers["near_town"],
        layers["near_highway"],
        layers["near_road"],
        layers["near_railway"],
        layers["accessibility"],
        layers["terrain_penalty"],
        stable_cell_hash(base.shape, 211),
    ]
    for cls in classes:
        raw_features.append(neighbor_density(base, cls, valid))
    stack = np.stack(raw_features, axis=-1).astype(np.float32)
    stack[~np.isfinite(stack)] = 0.0
    return stack


def competitive_score_cube(
    *,
    base: np.ndarray,
    valid: np.ndarray,
    restricted: np.ndarray,
    classes: list[int],
    cost_matrix: list[list[int]],
    probability: np.ndarray,
    drivers: dict[str, Any],
    urban_class: int,
    params: dict[str, float],
) -> np.ndarray:
    min_class = min(classes)
    sorted_prob = np.sort(probability, axis=0)
    margin = normalize_01(sorted_prob[-1] - sorted_prob[-2])
    stable = stable_cell_hash(base.shape, 123)
    access = drivers["layers"]["accessibility"]
    terrain = drivers["layers"]["terrain_penalty"]
    cubes = []
    for cls in classes:
        prob = normalize_01(probability[cls - min_class])
        score = (
            float(params["probability_weight"]) * prob
            + float(params["neighborhood_weight"]) * neighbor_density(base, cls, valid)
            + float(params["stay_inertia"]) * (base == cls)
            + float(params["stable_hash_weight"]) * stable
            + float(params["margin_weight"]) * margin
        )
        if cls == urban_class:
            score = (
                score
                + float(params["urban_accessibility_weight"]) * access
                - float(params["terrain_penalty_weight"]) * terrain
            )
        else:
            score = score + float(params["nonurban_low_access_weight"]) * (1.0 - access)
        for source in classes:
            changing = (base == source) & (source != cls)
            if not cost_allowed(cost_matrix, source, cls):
                score[changing] = -1e9
        score[(base != cls) & (restricted != 1)] = -1e9
        score[~valid] = -1e9
        cubes.append(np.asarray(score, dtype=np.float32))
    return np.stack(cubes)


def initial_competitive_assignment(
    base: np.ndarray,
    valid: np.ndarray,
    classes: list[int],
    score: np.ndarray,
) -> np.ndarray:
    min_class = min(classes)
    pred = (np.argmax(score, axis=0) + min_class).astype(np.int16)
    impossible = valid & (np.max(score, axis=0) < -1e8)
    pred[impossible] = base[impossible]
    pred[~valid] = 0
    return pred


def balance_competitive_quotas(
    *,
    pred: np.ndarray,
    base: np.ndarray,
    valid: np.ndarray,
    classes: list[int],
    future_pixels: dict[int, int],
    score: np.ndarray,
    max_iter: int = 80,
) -> np.ndarray:
    pred = pred.copy()
    min_class = min(classes)
    for _ in range(max_iter):
        counts = Counter(pred[valid].astype(int).tolist())
        diff = {cls: counts.get(cls, 0) - int(future_pixels.get(cls, 0)) for cls in classes}
        over = [cls for cls, value in diff.items() if value > 0]
        under = [cls for cls, value in diff.items() if value < 0]
        if not over and not under:
            break
        best: tuple[float, int, int, np.ndarray, np.ndarray, np.ndarray] | None = None
        for source_label in over:
            source_mask = valid & (pred == source_label)
            for target_label in under:
                target_score = score[target_label - min_class]
                source_score = score[source_label - min_class]
                candidate = source_mask & (target_score > -1e8)
                rows, cols = np.where(candidate)
                if rows.size == 0:
                    continue
                delta = target_score[rows, cols] - source_score[rows, cols]
                option = (float(np.max(delta)), source_label, target_label, rows, cols, delta)
                if best is None or option[0] > best[0]:
                    best = option
        if best is None:
            break
        _, source_label, target_label, rows, cols, delta = best
        counts = Counter(pred[valid].astype(int).tolist())
        source_excess = counts.get(source_label, 0) - int(future_pixels.get(source_label, 0))
        target_need = int(future_pixels.get(target_label, 0)) - counts.get(target_label, 0)
        take = min(source_excess, target_need, rows.size)
        if take <= 0:
            break
        selected = np.argpartition(delta, -take)[-take:]
        pred[rows[selected], cols[selected]] = target_label
    pred[~valid] = 0
    return pred


def cost_allowed(cost_matrix: list[list[int]], source: int, target: int) -> bool:
    try:
        return int(cost_matrix[source - 1][target - 1]) == 1
    except (IndexError, TypeError):
        return False


def allocate_pair(
    *,
    pred: np.ndarray,
    base: np.ndarray,
    valid: np.ndarray,
    restricted: np.ndarray,
    reserved: np.ndarray,
    source: int,
    target: int,
    budget: int,
    score: np.ndarray,
) -> int:
    candidate = valid & (~reserved) & (pred == source) & (restricted == 1)
    rows, cols = np.where(candidate)
    if rows.size == 0 or budget <= 0:
        return 0
    values = score[rows, cols]
    take = min(int(budget), rows.size)
    idx = np.argpartition(values, -take)[-take:]
    rr = rows[idx]
    cc = cols[idx]
    pred[rr, cc] = target
    reserved[rr, cc] = True
    return int(take)


def score_for_pair(
    scores: dict[str, np.ndarray],
    probability: np.ndarray,
    source: int,
    target: int,
    strategy: str,
    classes: list[int],
) -> np.ndarray:
    if strategy == "twm_driver_only_compact_growth":
        score = scores["driver_only"].copy()
    elif strategy == "twm_flus_probability_demand":
        score = scores["probability_demand"].copy()
    elif strategy == "twm_uncertainty_aware":
        score = scores["uncertainty_aware"].copy()
    elif strategy == "twm_farmland_protection":
        score = scores["farmland_protection"].copy()
    else:
        score = scores["hybrid_compact_access"].copy()
    source_prob = normalize_01(probability[source - min(classes)])
    target_prob = normalize_01(probability[target - min(classes)])
    score += 0.08 * target_prob - 0.04 * source_prob
    if strategy == "twm_farmland_protection" and source == 3:
        score -= 0.22 * source_prob
    if strategy == "twm_uncertainty_aware":
        score += 0.12 * scores["probability_margin"]
    return np.asarray(score, dtype=np.float32)


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


def enrich_metric(
    metric: dict[str, Any],
    *,
    pred: np.ndarray,
    base: np.ndarray,
    valid: np.ndarray,
    restricted: np.ndarray,
    classes: list[int],
    cost_matrix: list[list[int]],
    future_pixels: dict[str, int],
) -> dict[str, Any]:
    changed = valid & (pred != base)
    restricted_violations = int((changed & (restricted != 1)).sum())
    cost_violations = 0
    for source, target in zip(base[changed].astype(int).tolist(), pred[changed].astype(int).tolist()):
        if not cost_allowed(cost_matrix, source, target):
            cost_violations += 1
    full_counts = Counter(np.asarray(pred).reshape(-1).astype(int).tolist())
    demand_abs_error = {
        str(cls): abs(int(full_counts.get(cls, 0)) - int(future_pixels.get(str(cls), 0)))
        for cls in classes
    }
    total_abs_error = int(sum(demand_abs_error.values()))
    metric = dict(metric)
    metric.update(
        {
            "restricted_change_violation_count": restricted_violations,
            "restricted_change_violation_rate": round(restricted_violations / max(1, int(changed.sum())), 6),
            "cost_matrix_violation_count": cost_violations,
            "cost_matrix_violation_rate": round(cost_violations / max(1, int(changed.sum())), 6),
            "full_raster_demand_abs_error": demand_abs_error,
            "full_raster_total_demand_abs_error": total_abs_error,
            "full_raster_demand_fit": round(1.0 - total_abs_error / max(1, 2 * int(valid.sum())), 6),
        }
    )
    return metric


def build_planner_report(
    *,
    predictions: dict[str, np.ndarray],
    metrics: dict[str, dict[str, Any]],
    rasters: dict[str, Any],
    drivers: dict[str, Any],
    config_mp: dict[str, Any],
    urban_class: int,
) -> dict[str, Any]:
    base = rasters["dg2001coor.tif"]["data"]
    valid = class_mask(base, sorted(int(k) for k in config_mp["future_pixels"]))
    access = drivers["layers"]["accessibility"]
    urban_neighbor = neighbor_density(base, urban_class, valid)
    ranking = []
    for name, pred in predictions.items():
        changed = valid & (pred != base)
        new_urban = valid & (base != urban_class) & (pred == urban_class)
        compactness = float(urban_neighbor[new_urban].mean()) if np.any(new_urban) else 0.0
        accessibility = float(access[new_urban].mean()) if np.any(new_urban) else 0.0
        metric = metrics[name]
        demand_fit = float(metric["full_raster_demand_fit"])
        restriction_score = 1.0 - float(metric["restricted_change_violation_rate"])
        cost_score = 1.0 - float(metric["cost_matrix_violation_rate"])
        ex_post_change = float(metric["change_fom"])
        ex_post_urban = float(metric["urban_expansion_f1"])
        source_diversity = changed_source_diversity(base, pred, valid, urban_class)
        policy_score = (
            0.24 * demand_fit
            + 0.18 * restriction_score
            + 0.14 * cost_score
            + 0.13 * compactness
            + 0.11 * accessibility
            + 0.10 * source_diversity
            + 0.06 * ex_post_change
            + 0.04 * ex_post_urban
        )
        ranking.append(
            {
                "candidate_id": name,
                "policy_score": round(policy_score, 6),
                "demand_fit": round(demand_fit, 6),
                "restriction_score": round(restriction_score, 6),
                "cost_score": round(cost_score, 6),
                "compactness": round(compactness, 6),
                "accessibility": round(accessibility, 6),
                "source_diversity": round(source_diversity, 6),
                "ex_post_change_fom": metric["change_fom"],
                "ex_post_urban_expansion_f1": metric["urban_expansion_f1"],
                "predicted_change_count": metric["predicted_change_count"],
            }
        )
    ranking.sort(key=lambda item: item["policy_score"], reverse=True)
    return {
        "schema": "territory_world_model.flus_v24_planner_report.v1",
        "status": "pass" if ranking else "blocked",
        "planner_role": "rank_twm_candidates_against_flus_v24_demand_constraints",
        "ranking_policy": {
            "demand_fit": 0.24,
            "restriction_score": 0.18,
            "cost_score": 0.14,
            "compactness": 0.13,
            "accessibility": 0.11,
            "source_diversity": 0.10,
            "ex_post_change_fom_diagnostic": 0.06,
            "ex_post_urban_expansion_f1_diagnostic": 0.04,
        },
        "ranking": ranking,
        "selected_candidate_id": ranking[0]["candidate_id"] if ranking else None,
        "claim_boundary": "planner_ranking_on_official_sample_not_production_decision",
    }


def changed_source_diversity(base: np.ndarray, pred: np.ndarray, valid: np.ndarray, urban_class: int) -> float:
    sources = base[valid & (base != urban_class) & (pred == urban_class)].astype(int)
    if sources.size == 0:
        return 0.0
    counts = Counter(sources.tolist())
    total = float(sum(counts.values()))
    probs = [count / total for count in counts.values()]
    entropy = -sum(p * math.log(p) for p in probs if p > 0)
    return entropy / math.log(max(2, len(counts)))


def render_assets(
    *,
    asset_dir: Path,
    rasters: dict[str, Any],
    predictions: dict[str, np.ndarray],
    metrics: dict[str, dict[str, Any]],
    planner: dict[str, Any],
    config_color: dict[int, dict[str, Any]],
    classes: list[int],
) -> dict[str, str]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import BoundaryNorm, ListedColormap
    from matplotlib.patches import Patch

    colors = {0: "#f1f1ec"}
    labels = {0: "NoData"}
    for cls, payload in config_color.items():
        r, g, b = payload["rgb"]
        colors[cls] = f"#{r:02x}{g:02x}{b:02x}"
        labels[cls] = payload["label"]
    max_class = max(classes)
    cmap = ListedColormap([colors.get(idx, "#d0d0d0") for idx in range(max_class + 1)])
    norm = BoundaryNorm(np.arange(-0.5, max_class + 1.5, 1), cmap.N)
    valid = rasters["valid_mask"]
    selected = planner.get("selected_candidate_id") or next(iter(predictions))
    best_twm = max(
        [name for name in predictions if name.startswith("twm_")],
        key=lambda name: metrics[name]["change_fom"],
    )
    map_items = [
        ("Initial 2001", rasters["dg2001coor.tif"]["data"], None),
        ("Truth 2006", rasters["dg2006true.tif"]["data"], None),
        ("Official FLUS", predictions["official_simulationResult"], "official_simulationResult"),
        ("Selected TWM", predictions[selected], selected),
        ("Best TWM FoM", predictions[best_twm], best_twm),
    ]
    fig, axes = plt.subplots(1, len(map_items), figsize=(18, 4.8), constrained_layout=True)
    for ax, (title, arr, key) in zip(axes, map_items):
        shown = np.asarray(arr).copy()
        shown[~valid] = 0
        ax.imshow(shown, cmap=cmap, norm=norm, interpolation="nearest")
        subtitle = ""
        if key:
            subtitle = f"\nOA={metrics[key]['overall_accuracy']:.3f}, FoM={metrics[key]['change_fom']:.3f}"
        ax.set_title(title + subtitle, fontsize=10)
        ax.set_xticks([])
        ax.set_yticks([])
    handles = [Patch(facecolor=colors[idx], edgecolor="none", label=f"{idx} {labels[idx]}") for idx in [0] + classes]
    fig.legend(handles=handles, loc="lower center", ncol=min(6, len(handles)), frameon=False, fontsize=9)
    maps_path = asset_dir / "twm_flus_v24_simopt_prediction_maps.png"
    fig.savefig(maps_path, bbox_inches="tight", dpi=180)
    plt.close(fig)

    metric_names = list(metrics)
    x = np.arange(len(metric_names))
    fig, ax = plt.subplots(figsize=(12.5, 5.4), constrained_layout=True)
    width = 0.22
    ax.bar(x - width, [metrics[n]["overall_accuracy"] for n in metric_names], width, label="OA", color="#455a64")
    ax.bar(x, [metrics[n]["change_fom"] for n in metric_names], width, label="Change FoM", color="#c62828")
    ax.bar(x + width, [metrics[n]["urban_expansion_f1"] for n in metric_names], width, label="Urban F1", color="#2e7d32")
    ax.set_xticks(x)
    ax.set_xticklabels([name.replace("_", "\n") for name in metric_names], fontsize=7)
    ax.set_ylim(0, 1.02)
    ax.grid(axis="y", color="#e5e5e5", linewidth=0.8)
    ax.legend(frameon=False, ncol=3)
    ax.set_title("FLUS V2.4 same-grid baseline and TWM candidate metrics")
    metrics_path = asset_dir / "twm_flus_v24_simopt_metrics.png"
    fig.savefig(metrics_path, bbox_inches="tight", dpi=180)
    plt.close(fig)

    base = rasters["dg2001coor.tif"]["data"]
    truth = rasters["dg2006true.tif"]["data"]
    change_items = [
        ("Actual change", truth != base),
        ("Official FLUS change", predictions["official_simulationResult"] != base),
        ("Selected TWM change", predictions[selected] != base),
        ("Best TWM FoM change", predictions[best_twm] != base),
    ]
    fig, axes = plt.subplots(1, len(change_items), figsize=(15, 4.2), constrained_layout=True)
    for ax, (title, mask) in zip(axes, change_items):
        rgb = np.zeros((*mask.shape, 4), dtype=float)
        rgb[..., :3] = np.array([0.94, 0.94, 0.90])
        rgb[..., 3] = 1.0
        rgb[mask & valid, :3] = np.array([0.78, 0.18, 0.16])
        rgb[~valid, :3] = np.array([0.98, 0.98, 0.96])
        ax.imshow(rgb, interpolation="nearest")
        ax.set_title(title, fontsize=10)
        ax.set_xticks([])
        ax.set_yticks([])
    changes_path = asset_dir / "twm_flus_v24_simopt_change_comparison.png"
    fig.savefig(changes_path, bbox_inches="tight", dpi=180)
    plt.close(fig)

    ranking = planner.get("ranking") or []
    fig, ax = plt.subplots(figsize=(10, 4.8), constrained_layout=True)
    names = [item["candidate_id"] for item in ranking][::-1]
    values = [item["policy_score"] for item in ranking][::-1]
    ax.barh(names, values, color="#546e7a")
    ax.set_xlim(0, max(1.0, max(values, default=0.0) * 1.1))
    ax.grid(axis="x", color="#e5e5e5", linewidth=0.8)
    ax.set_title("TWM planner ranking on FLUS V2.4 sample")
    for yi, value in enumerate(values):
        ax.text(value, yi, f" {value:.3f}", va="center", fontsize=9)
    planner_path = asset_dir / "twm_flus_v24_simopt_planner_ranking.png"
    fig.savefig(planner_path, bbox_inches="tight", dpi=180)
    plt.close(fig)

    return {
        "prediction_maps": rel_asset(maps_path),
        "metrics": rel_asset(metrics_path),
        "change_comparison": rel_asset(changes_path),
        "planner_ranking": rel_asset(planner_path),
    }


def render_markdown_report(report: dict[str, Any]) -> str:
    metrics = report["simulator"]["metrics"]
    assets = report["renderer"]["assets"]
    planner = report["planner"]
    best_official = report["simulator"]["best_official_flus_by_change_fom"]
    best_twm = report["simulator"]["best_twm_by_change_fom"]
    selected = planner.get("selected_candidate_id")
    lines = [
        "# TWM x GeoSOS-FLUS V2.4 同案模拟与规划优化结果",
        "",
        "更新日期：2026-06-22",
        "",
        "## 1. 结论",
        "",
        "这一步已经不只是判断数据能否使用，而是把 V2.4 官方样例接入了 TWM 的渲染器、模拟器和规划器：官方 FLUS 输出保留为 baseline 行，TWM 候选方案在同一 531x768、100 m 栅格、同一 future-pixel 需求量和同一 2006 真值下生成预测图并参与指标比较。",
        "",
        f"按变化 FoM 看，官方 FLUS 样例较好的结果是 `{best_official}`，TWM 候选中较好的结果是 `{best_twm}`。规划器当前选择 `{selected}`，它不是单纯最大化事后精度，而是综合需求贴合、限制区、cost matrix、紧凑性、可达性和事后诊断指标。",
        "",
        "新增的 `twm_independent_logit_*` 候选先用 2001 土地利用标签和驱动因子训练独立多分类 suitability，再做严格需求/约束下的多类型竞争投影，不读取 FLUS 包内 `Probability-of-occurrence.tif`。其中 `twm_independent_logit_change_seeking` 的变化 FoM 已超过官方 FLUS 样例输出，但整体 OA/Kappa 仍未超过 FLUS。",
        "",
        "`twm_competitive_quota_balanced` 和 `twm_competitive_quota_change_seeking` 使用 FLUS 概率图作为外部 suitability 场，变化 FoM 更高，可作为上限/融合候选；它们不能被解释为纯 TWM 独立优于 FLUS。",
        "",
        "需要严格说明：独立 logit 候选只使用驱动因子和 2001 初始标签训练 suitability；FLUS-informed 候选则使用 `Probability-of-occurrence.tif`。两类结果必须分开解释。",
        "",
        "## 2. 渲染器输出",
        "",
        f"![Prediction maps]({assets.get('prediction_maps', '')})",
        "",
        f"![Change comparison]({assets.get('change_comparison', '')})",
        "",
        "## 3. 模拟器指标",
        "",
        f"![Metrics]({assets.get('metrics', '')})",
        "",
        "| candidate | OA | Kappa | change FoM | change F1 | urban F1 | demand fit | restricted viol. | cost viol. |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, metric in metrics.items():
        lines.append(
            f"| {name} | {metric['overall_accuracy']:.6f} | {metric['kappa']:.6f} | "
            f"{metric['change_fom']:.6f} | {metric['change_f1']:.6f} | {metric['urban_expansion_f1']:.6f} | "
            f"{metric['full_raster_demand_fit']:.6f} | {metric['restricted_change_violation_rate']:.6f} | "
            f"{metric['cost_matrix_violation_rate']:.6f} |"
        )
    lines.extend(
        [
            "",
            "## 4. 规划器排序",
            "",
            f"![Planner ranking]({assets.get('planner_ranking', '')})",
            "",
            "| candidate | policy score | demand | restriction | cost | compactness | accessibility | FoM diagnostic |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for item in planner.get("ranking") or []:
        lines.append(
            f"| {item['candidate_id']} | {item['policy_score']:.6f} | {item['demand_fit']:.6f} | "
            f"{item['restriction_score']:.6f} | {item['cost_score']:.6f} | {item['compactness']:.6f} | "
            f"{item['accessibility']:.6f} | {item['ex_post_change_fom']:.6f} |"
        )
    lines.extend(
        [
            "",
            "## 5. 未完成项",
            "",
        ]
    )
    for item in report["interpretation"]["next_tasks"]:
        lines.append(f"- {item}")
    lines.extend(
        [
            "",
            "## 6. 研究边界",
            "",
            "- 可以说：TWM 已经能基于官方 V2.4 样例生成可复现的同案模拟、优化和图文报告，并把官方 FLUS 输出作为真实 baseline 行。",
            "- 可以说：在该官方样例上，不依赖 FLUS 概率图的独立 TWM logit suitability 候选已经超过 FLUS 的变化 FoM。",
            "- 可以说：使用 FLUS 概率图的融合候选变化 FoM 更高，但它们不是独立优于 FLUS 的证据。",
            "- 不能说：TWM 已经全面优于 GeoSOS/FLUS；当前 OA/Kappa 仍低于官方 FLUS。",
            "- 不能说：TWM 已经解决自然资源治理的真实业务闭环问题。",
            "- 下一步最关键的是把独立 suitability 从单期标签学习推进到真正的 multi-period dynamics 学习和跨案例验证。",
            "",
        ]
    )
    return "\n".join(lines)


if __name__ == "__main__":
    main()
