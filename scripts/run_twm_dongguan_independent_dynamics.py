#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
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

from scripts.run_twm_dongguan_geosos_simulation_optimization import (  # noqa: E402
    DEFAULT_INPUT,
    build_training_transition_profile,
    harmonic,
    load_driver_layers,
    neighbor_density,
    normalize_01,
    pixel_metrics,
    raster_profile,
    stable_cell_hash,
    valid_mask,
)
from scripts.run_twm_dongguan_geosos_validation import (  # noqa: E402
    landuse_label,
    load_landuse_rasters,
    parse_landuse_info,
    parse_suitability_matrix,
    transition_allowed,
)

DEFAULT_OUTPUT = REPO_ROOT / "docs/reports/twm_dongguan_independent_dynamics_2026-06-22.json"
DEFAULT_MARKDOWN = REPO_ROOT / "docs/twm-dongguan-independent-dynamics-2026-06-22.md"
DEFAULT_ASSET_DIR = REPO_ROOT / "docs/assets"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Train an independent TWM transition-dynamics candidate on DongGuan 2000->2005 and evaluate 2005->2006."
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN)
    parser.add_argument("--asset-dir", type=Path, default=DEFAULT_ASSET_DIR)
    parser.add_argument("--no-render", action="store_true")
    args = parser.parse_args()

    report = run_independent_dynamics(args.input, asset_dir=args.asset_dir, render=not args.no_render)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    if args.markdown_output:
        args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_output.write_text(render_markdown_report(report), encoding="utf-8")
    print(json.dumps({"status": report["status"], "output": str(args.output)}, ensure_ascii=False))


def run_independent_dynamics(
    zip_path: Path,
    *,
    asset_dir: Path | None,
    render: bool,
) -> dict[str, Any]:
    zip_path = Path(zip_path).expanduser()
    if not zip_path.exists():
        raise FileNotFoundError(str(zip_path))

    with tempfile.TemporaryDirectory(prefix="twm_dongguan_independent_dynamics_") as tmp:
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

        train_profile = build_training_transition_profile(
            landuse2000,
            landuse2005,
            valid,
            classes,
            train_years=5,
            horizon_years=1,
        )
        target_counts = Counter(landuse2006[valid].astype(int).tolist())
        future_pixels = {cls: int(target_counts.get(cls, 0)) for cls in classes}
        model_inputs = {
            "train_start": landuse2000,
            "train_end": landuse2005,
            "initial": landuse2005,
            "actual": landuse2006,
            "valid": valid,
            "classes": classes,
            "landuse_info": landuse_info,
            "suitability": suitability,
            "drivers": drivers,
            "urban_value": urban_value,
            "future_pixels": future_pixels,
        }
        predictions, metadata = build_independent_dynamics_candidates(model_inputs)
        metrics = {
            name: pixel_metrics(
                pred,
                landuse2006,
                landuse2005,
                valid,
                classes,
                suitability,
                landuse_info,
                cell_area_ha,
                urban_value=urban_value,
            )
            for name, pred in predictions.items()
        }
        assets: dict[str, str] = {}
        if render and asset_dir is not None:
            asset_dir.mkdir(parents=True, exist_ok=True)
            assets = render_assets(
                asset_dir=asset_dir,
                predictions=predictions,
                metrics=metrics,
                initial=landuse2005,
                actual=landuse2006,
                valid=valid,
                landuse_info=landuse_info,
            )
        baseline_ids = ["persistence_2005_as_2006", "markov_pair_budget_projection"]
        twm_ids = [name for name in predictions if name.startswith("twm_")]
        best_baseline = max(baseline_ids, key=lambda name: metrics[name]["change_fom"])
        best_twm = max(twm_ids, key=lambda name: metrics[name]["change_fom"])
        return {
            "schema": "territory_world_model.dongguan_independent_dynamics_report.v1",
            "status": "pass",
            "claim_boundary": "independent_transition_dynamics_on_three_time_dongguan_tutorial_not_production_claim",
            "source": {
                "zip_path": str(zip_path),
                "dataset": "GeoSOS DongGuan 80m tutorial data",
                "task": "independent TWM transition dynamics train 2000->2005, holdout 2005->2006",
            },
            "data_profile": {
                "raster_profile": profile,
                "landuse_types": landuse_info,
                "training_period": "2000->2005",
                "holdout_period": "2005->2006",
                "valid_cell_count": int(valid.sum()),
                "cell_area_ha": cell_area_ha,
                "training_transition_profile": train_profile,
                "holdout_future_pixels_from_2006": {str(k): v for k, v in future_pixels.items()},
                "driver_layers": drivers["summary"],
            },
            "simulator": {
                "baseline_candidate_ids": baseline_ids,
                "twm_candidate_ids": twm_ids,
                "candidate_metadata": metadata,
                "metrics": metrics,
                "best_baseline_by_change_fom": best_baseline,
                "best_twm_by_change_fom": best_twm,
            },
            "renderer": {"rendered": bool(assets), "assets": assets},
            "interpretation": {
                "what_is_validated": [
                    "The dynamics candidate trains from an observed historical transition pair, not from the holdout target map.",
                    "The simulator predicts a full 2006 raster from the 2005 state using learned transition probabilities, demand projection and policy constraints.",
                    "The holdout 2006 raster is used for target demand and ex-post metrics only.",
                ],
                "what_is_still_missing": [
                    "Only one observed training transition is available, so the model is not yet a robust multi-period world model.",
                    "The holdout demand uses 2006 class totals; a production forecast needs demand from a scenario model rather than from the holdout truth.",
                    "There is still no official FLUS output for this 80 m package, so comparison is against transparent baselines, not official FLUS.",
                ],
                "next_tasks": [
                    "Add more historical periods or more cities to train true temporal dynamics.",
                    "Replace holdout-derived demand with an independent demand/scenario model.",
                    "Cross-validate the transition model on FLUS V2.4 when intermediate period labels are available or generated by an official run.",
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


def build_independent_dynamics_candidates(model_inputs: dict[str, Any]) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    initial = model_inputs["initial"]
    predictions: dict[str, np.ndarray] = {
        "persistence_2005_as_2006": initial.copy(),
        "markov_pair_budget_projection": allocate_markov_pair_budget_projection(model_inputs),
    }
    configs = {
        "twm_independent_transition_logit": {
            "backend": "multinomial_logit_transition",
            "uses_holdout_labels_for_training": False,
            "description": "Per-source transition classifier trained on 2000->2005 observed transitions and projected to 2005->2006 demand.",
            "params": {
                "sample_stride": 2,
                "probability_weight": 1.0,
                "neighborhood_weight": 0.12,
                "stay_inertia": -0.04,
                "urban_access_weight": 0.16,
                "transition_prior_weight": 0.65,
            },
        },
        "twm_independent_transition_change_seeking": {
            "backend": "multinomial_logit_transition",
            "uses_holdout_labels_for_training": False,
            "description": "Lower-inertia transition classifier candidate for change-localization diagnostics.",
            "params": {
                "sample_stride": 2,
                "probability_weight": 1.0,
                "neighborhood_weight": 0.06,
                "stay_inertia": -0.18,
                "urban_access_weight": 0.20,
                "transition_prior_weight": 0.45,
            },
        },
    }
    for name, config in configs.items():
        predictions[name] = allocate_independent_transition_model(model_inputs, config["params"])
    for pred in predictions.values():
        pred[~model_inputs["valid"]] = 0
    return predictions, configs


def allocate_markov_pair_budget_projection(model_inputs: dict[str, Any]) -> np.ndarray:
    train_start = model_inputs["train_start"]
    train_end = model_inputs["train_end"]
    initial = model_inputs["initial"]
    valid = model_inputs["valid"]
    classes = model_inputs["classes"]
    future_pixels = model_inputs["future_pixels"]
    pair_counts: Counter[tuple[int, int]] = Counter(
        zip(train_start[valid].astype(int).tolist(), train_end[valid].astype(int).tolist())
    )
    source_counts = Counter(train_start[valid].astype(int).tolist())
    current_counts = Counter(initial[valid].astype(int).tolist())
    deficits = {cls: max(0, int(future_pixels[cls]) - current_counts.get(cls, 0)) for cls in classes}
    surpluses = {cls: max(0, current_counts.get(cls, 0) - int(future_pixels[cls])) for cls in classes}
    pred = initial.copy()
    reserved = np.zeros(initial.shape, dtype=bool)
    stable = stable_cell_hash(initial.shape, 311)
    for target, need in sorted(deficits.items(), key=lambda item: -item[1]):
        remaining = int(need)
        source_order = sorted(
            [cls for cls, surplus in surpluses.items() if surplus > 0 and cls != target],
            key=lambda src: pair_counts.get((src, target), 0) / max(1, source_counts.get(src, 0)),
            reverse=True,
        )
        for source in source_order:
            if remaining <= 0:
                break
            if not transition_allowed(model_inputs["suitability"], source, target):
                continue
            take = min(remaining, surpluses[source])
            mask = valid & (~reserved) & (pred == source)
            rows, cols = np.where(mask)
            if rows.size == 0:
                continue
            selected = np.argpartition(stable[rows, cols], -min(take, rows.size))[-min(take, rows.size) :]
            pred[rows[selected], cols[selected]] = target
            reserved[rows[selected], cols[selected]] = True
            changed = int(selected.size)
            surpluses[source] -= changed
            remaining -= changed
    pred[~valid] = 0
    return pred


def allocate_independent_transition_model(model_inputs: dict[str, Any], params: dict[str, float]) -> np.ndarray:
    probability = train_transition_probability_cube(model_inputs, int(params["sample_stride"]))
    score = transition_score_cube(model_inputs, probability, params)
    pred = initial_transition_assignment(model_inputs, score)
    pred = balance_to_future_pixels(model_inputs, pred, score)
    pred[~model_inputs["valid"]] = 0
    return pred


def train_transition_probability_cube(model_inputs: dict[str, Any], sample_stride: int) -> np.ndarray:
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    train_start = model_inputs["train_start"]
    train_end = model_inputs["train_end"]
    valid = model_inputs["valid"]
    classes = model_inputs["classes"]
    features = feature_stack(train_start, valid, classes, model_inputs["drivers"])
    rows, cols = np.indices(train_start.shape)
    train_mask = valid & (((rows + cols) % max(1, sample_stride)) == 0)
    out = np.zeros((len(classes), train_start.shape[0], train_start.shape[1]), dtype=np.float32)
    source_global_counts = Counter(train_end[valid].astype(int).tolist())
    global_prior = np.array([source_global_counts.get(cls, 0) for cls in classes], dtype=np.float32)
    global_prior = global_prior / max(1.0, float(global_prior.sum()))
    for source in classes:
        source_train = train_mask & (train_start == source)
        source_apply = valid & (model_inputs["initial"] == source)
        if int(source_train.sum()) < len(classes) * 3 or len(np.unique(train_end[source_train])) < 2:
            out[:, source_apply] = global_prior[:, None]
            continue
        x_train = features[source_train]
        y_train = train_end[source_train].astype(int)
        model = make_pipeline(
            StandardScaler(),
            LogisticRegression(class_weight="balanced", max_iter=500, random_state=0, solver="lbfgs"),
        )
        model.fit(x_train, y_train)
        x_apply = feature_stack(model_inputs["initial"], valid, classes, model_inputs["drivers"])[source_apply]
        probs = model.predict_proba(x_apply)
        class_to_col = {int(cls): idx for idx, cls in enumerate(model.classes_)}
        for target_idx, target in enumerate(classes):
            col = class_to_col.get(int(target))
            if col is not None:
                out[target_idx, source_apply] = probs[:, col]
    out[:, ~valid] = 0.0
    return out


def feature_stack(arr: np.ndarray, valid: np.ndarray, classes: list[int], drivers: dict[str, Any]) -> np.ndarray:
    layers = drivers["layers"]
    raw = [
        layers["dtcity"],
        layers["dtfreeway"],
        layers["dtrailway"],
        layers["dtroad"],
        layers["urban_access"],
        stable_cell_hash(arr.shape, 419),
    ]
    for cls in classes:
        raw.append(neighbor_density(arr, cls, valid))
    stack = np.stack(raw, axis=-1).astype(np.float32)
    stack[~np.isfinite(stack)] = 0.0
    return stack


def transition_score_cube(model_inputs: dict[str, Any], probability: np.ndarray, params: dict[str, float]) -> np.ndarray:
    initial = model_inputs["initial"]
    valid = model_inputs["valid"]
    classes = model_inputs["classes"]
    suitability = model_inputs["suitability"]
    urban_value = int(model_inputs["urban_value"])
    urban_access = model_inputs["drivers"]["layers"]["urban_access"]
    train_pair_prior = transition_prior_matrix(model_inputs)
    scores = []
    for idx, target in enumerate(classes):
        score = (
            float(params["probability_weight"]) * normalize_01(probability[idx])
            + float(params["neighborhood_weight"]) * neighbor_density(initial, target, valid)
            + float(params["stay_inertia"]) * (initial == target)
            + train_pair_prior[target] * float(params["transition_prior_weight"])
        )
        if target == urban_value:
            score = score + float(params["urban_access_weight"]) * urban_access
        else:
            score = score + 0.04 * (1.0 - urban_access)
        for source in classes:
            changing = (initial == source) & (source != target)
            if not transition_allowed(suitability, source, target):
                score[changing] = -1e9
        score[~valid] = -1e9
        scores.append(np.asarray(score, dtype=np.float32))
    return np.stack(scores)


def transition_prior_matrix(model_inputs: dict[str, Any]) -> dict[int, np.ndarray]:
    train_start = model_inputs["train_start"]
    train_end = model_inputs["train_end"]
    valid = model_inputs["valid"]
    classes = model_inputs["classes"]
    pair_counts: Counter[tuple[int, int]] = Counter(
        zip(train_start[valid].astype(int).tolist(), train_end[valid].astype(int).tolist())
    )
    source_counts = Counter(train_start[valid].astype(int).tolist())
    priors = {}
    for target in classes:
        arr = np.zeros(train_start.shape, dtype=np.float32)
        for source in classes:
            prior = pair_counts.get((source, target), 0) / max(1, source_counts.get(source, 0))
            arr[model_inputs["initial"] == source] = prior
        priors[target] = normalize_01(arr)
    return priors


def initial_transition_assignment(model_inputs: dict[str, Any], score: np.ndarray) -> np.ndarray:
    classes = model_inputs["classes"]
    pred = (np.argmax(score, axis=0) + min(classes)).astype(np.int16)
    impossible = model_inputs["valid"] & (np.max(score, axis=0) < -1e8)
    pred[impossible] = model_inputs["initial"][impossible]
    pred[~model_inputs["valid"]] = 0
    return pred


def balance_to_future_pixels(model_inputs: dict[str, Any], pred: np.ndarray, score: np.ndarray) -> np.ndarray:
    classes = model_inputs["classes"]
    valid = model_inputs["valid"]
    future_pixels = model_inputs["future_pixels"]
    pred = pred.copy()
    for _ in range(80):
        counts = Counter(pred[valid].astype(int).tolist())
        diff = {cls: counts.get(cls, 0) - int(future_pixels[cls]) for cls in classes}
        over = [cls for cls, value in diff.items() if value > 0]
        under = [cls for cls, value in diff.items() if value < 0]
        if not over and not under:
            break
        best: tuple[float, int, int, np.ndarray, np.ndarray, np.ndarray] | None = None
        for source_label in over:
            source_mask = valid & (pred == source_label)
            for target_label in under:
                target_score = score[target_label - min(classes)]
                source_score = score[source_label - min(classes)]
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
        source_excess = counts.get(source_label, 0) - int(future_pixels[source_label])
        target_need = int(future_pixels[target_label]) - counts.get(target_label, 0)
        take = min(source_excess, target_need, rows.size)
        if take <= 0:
            break
        selected = np.argpartition(delta, -take)[-take:]
        pred[rows[selected], cols[selected]] = target_label
    pred[~valid] = 0
    return pred


def render_assets(
    *,
    asset_dir: Path,
    predictions: dict[str, np.ndarray],
    metrics: dict[str, dict[str, Any]],
    initial: np.ndarray,
    actual: np.ndarray,
    valid: np.ndarray,
    landuse_info: dict[str, Any],
) -> dict[str, str]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import BoundaryNorm, ListedColormap
    from matplotlib.patches import Patch

    labels = {int(key): value["zh"] for key, value in (landuse_info.get("types") or {}).items()}
    colors = {0: "#f5f5f2", 1: "#f4d35e", 2: "#2f7d32", 3: "#8fbc8f", 4: "#3b82c4", 5: "#c2412d", 6: "#b8b0a4"}
    cmap = ListedColormap([colors.get(i, "#cccccc") for i in range(max(7, max(labels) + 1))])
    norm = BoundaryNorm(np.arange(-0.5, cmap.N + 0.5, 1), cmap.N)
    best_twm = max([name for name in predictions if name.startswith("twm_")], key=lambda name: metrics[name]["change_fom"])
    map_items = [
        ("Initial 2005", initial, None),
        ("Truth 2006", actual, None),
        ("Markov projection", predictions["markov_pair_budget_projection"], "markov_pair_budget_projection"),
        ("TWM independent dynamics", predictions[best_twm], best_twm),
    ]
    fig, axes = plt.subplots(1, len(map_items), figsize=(15, 4.8), constrained_layout=True)
    for ax, (title, arr, key) in zip(axes, map_items):
        shown = np.asarray(arr).copy()
        shown[~valid] = 0
        ax.imshow(shown, cmap=cmap, norm=norm, interpolation="nearest")
        if key:
            title += f"\nOA={metrics[key]['overall_accuracy']:.3f}, FoM={metrics[key]['change_fom']:.3f}"
        ax.set_title(title, fontsize=10)
        ax.set_xticks([])
        ax.set_yticks([])
    handles = [Patch(facecolor=colors.get(k, "#ccc"), edgecolor="none", label=f"{k} {labels[k]}") for k in sorted(labels)]
    fig.legend(handles=handles, loc="lower center", ncol=min(6, len(handles)), frameon=False, fontsize=9)
    maps_path = asset_dir / "twm_dongguan_independent_dynamics_maps.png"
    fig.savefig(maps_path, bbox_inches="tight", dpi=180)
    plt.close(fig)

    names = list(metrics)
    x = np.arange(len(names))
    fig, ax = plt.subplots(figsize=(10.5, 5.2), constrained_layout=True)
    width = 0.24
    ax.bar(x - width, [metrics[n]["overall_accuracy"] for n in names], width, label="OA", color="#455a64")
    ax.bar(x, [metrics[n]["change_fom"] for n in names], width, label="Change FoM", color="#c62828")
    ax.bar(x + width, [metrics[n]["urban_expansion_f1"] for n in names], width, label="Urban F1", color="#2e7d32")
    ax.set_ylim(0, 1.02)
    ax.set_xticks(x)
    ax.set_xticklabels([name.replace("_", "\n") for name in names], fontsize=8)
    ax.grid(axis="y", color="#e5e5e5", linewidth=0.8)
    ax.legend(frameon=False, ncol=3)
    metrics_path = asset_dir / "twm_dongguan_independent_dynamics_metrics.png"
    fig.savefig(metrics_path, bbox_inches="tight", dpi=180)
    plt.close(fig)
    return {
        "maps": rel_asset(maps_path),
        "metrics": rel_asset(metrics_path),
    }


def rel_asset(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT / "docs"))
    except ValueError:
        return str(path)


def render_markdown_report(report: dict[str, Any]) -> str:
    metrics = report["simulator"]["metrics"]
    assets = report["renderer"]["assets"]
    best_twm = report["simulator"]["best_twm_by_change_fom"]
    best_baseline = report["simulator"]["best_baseline_by_change_fom"]
    lines = [
        "# TWM DongGuan 独立 Transition Dynamics 验证",
        "",
        "更新日期：2026-06-22",
        "",
        "## 1. 结论",
        "",
        "这一步从单期 suitability 推进到独立 transition dynamics：模型只用 2000->2005 的真实转移训练，预测 2005->2006，2006 图只用于 holdout demand 和事后指标。",
        "",
        f"当前最佳 TWM dynamics 候选是 `{best_twm}`，最佳透明 baseline 是 `{best_baseline}`。这不是官方 FLUS 对比，因为 80m 包没有官方 FLUS 输出图；它验证的是 TWM 能否从历史转移学习 dynamics。",
        "",
        "## 2. 渲染器输出",
        "",
        f"![Maps]({assets.get('maps', '')})",
        "",
        f"![Metrics]({assets.get('metrics', '')})",
        "",
        "## 3. 指标",
        "",
        "| candidate | OA | Kappa | change FoM | change F1 | urban F1 | violation rate | predicted change |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, metric in metrics.items():
        lines.append(
            f"| {name} | {metric['overall_accuracy']:.6f} | {metric['kappa']:.6f} | {metric['change_fom']:.6f} | "
            f"{metric['change_f1']:.6f} | {metric['urban_expansion_f1']:.6f} | {metric['suitability_violation_rate']:.6f} | "
            f"{metric['predicted_change_count']} |"
        )
    lines.extend(
        [
            "",
            "## 4. 边界",
            "",
            "- 可以说：TWM 已经具备从历史转移对训练独立 dynamics 的实验链路。",
            "- 不能说：这已经是稳健的 multi-period world model；当前只有一个训练转移对。",
            "- 不能说：这项 80m 实验已经击败官方 FLUS；该数据包没有官方 FLUS 输出图。",
            "- 下一步需要更多时期或多城市样本，并把 holdout demand 替换为独立 scenario/demand model。",
            "",
        ]
    )
    return "\n".join(lines)


if __name__ == "__main__":
    main()
