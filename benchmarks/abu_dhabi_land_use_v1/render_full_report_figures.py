#!/usr/bin/env python3
"""Render data, experiment and result figures for the full Chinese report."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import rasterio
from matplotlib.colors import ListedColormap
from matplotlib.patches import FancyBboxPatch, Patch
from sklearn.decomposition import PCA

HERE = Path(__file__).resolve().parent
FIGURE_ROOT = HERE / "figures"
INPUT_ROOT = HERE / "artifacts/gee"
BUNDLE_ROOT = HERE / "artifacts/bundle"
OSM_ROOT = HERE / "artifacts/osm"
MODEL_IDS = ("geosos_flus", "geospatial_kernel", "paper58")
MODEL_LABELS = {
    "geosos_flus": "GeoSOS-FLUS",
    "geospatial_kernel": "Geospatial Kernel",
    "paper58": "Paper58",
}
MODEL_COLORS = {
    "geosos_flus": "#4477aa",
    "geospatial_kernel": "#228833",
    "paper58": "#cc6677",
}
SCENARIO_IDS = ("compact", "ecological_priority", "outward_growth")
SCENARIO_LABELS = {
    "compact": "紧凑增长",
    "ecological_priority": "生态优先",
    "outward_growth": "外延增长",
}
CLASS_LABELS = {
    1: "水体",
    2: "木本植被",
    3: "低矮植被",
    4: "湿地",
    5: "建成区",
    6: "裸地",
}
CLASS_COLORS = (
    "#ffffff",
    "#4d9bd6",
    "#27734a",
    "#8ac66d",
    "#57b8b0",
    "#d1493f",
    "#d9d4c7",
)


def configure_style() -> None:
    plt.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.sans-serif": ["Arial Unicode MS", "DejaVu Sans"],
            "axes.unicode_minus": False,
            "axes.titlesize": 12,
            "axes.labelsize": 10,
            "xtick.labelsize": 9,
            "ytick.labelsize": 9,
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "axes.edgecolor": "#aeb4b8",
            "axes.titleweight": "bold",
        }
    )


def _read(path: Path) -> np.ndarray:
    with rasterio.open(path) as dataset:
        return dataset.read()


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _save(figure: plt.Figure, name: str) -> Path:
    FIGURE_ROOT.mkdir(parents=True, exist_ok=True)
    path = FIGURE_ROOT / name
    figure.savefig(path, dpi=210, bbox_inches="tight", facecolor="white")
    plt.close(figure)
    return path


def _map_axis(axis: plt.Axes) -> None:
    axis.set_xticks([])
    axis.set_yticks([])
    for spine in axis.spines.values():
        spine.set_color("#b8bec2")
        spine.set_linewidth(0.7)


def _land_cover_legend(figure: plt.Figure, *, y: float = 0.01) -> None:
    handles = [
        Patch(facecolor=CLASS_COLORS[value], label=CLASS_LABELS[value])
        for value in range(1, 7)
    ]
    figure.legend(
        handles=handles,
        loc="lower center",
        bbox_to_anchor=(0.5, y),
        ncol=6,
        frameon=False,
        fontsize=9,
    )


def render_land_cover_overview(valid: np.ndarray, audit: dict[str, Any]) -> Path:
    state_2017 = _read(INPUT_ROOT / "land_cover/land_cover_2017_100m.tif")[0]
    state_2024 = _read(INPUT_ROOT / "land_cover/land_cover_2024_100m.tif")[0]
    cmap = ListedColormap(CLASS_COLORS)
    figure, axes = plt.subplots(2, 2, figsize=(12.5, 9.2), constrained_layout=True)
    for axis, state, year in (
        (axes[0, 0], state_2017, 2017),
        (axes[0, 1], state_2024, 2024),
    ):
        display = state.copy()
        display[~valid] = 0
        axis.imshow(display, cmap=cmap, vmin=0, vmax=6, interpolation="nearest")
        axis.set_title(f"{year} 年土地覆盖")
        _map_axis(axis)

    change = np.zeros_like(state_2017, dtype=np.uint8)
    change[valid] = 1
    change[valid & (state_2017 != state_2024)] = 2
    axes[1, 0].imshow(
        change,
        cmap=ListedColormap(("#ffffff", "#d9dde0", "#d1493f")),
        vmin=0,
        vmax=2,
        interpolation="nearest",
    )
    changed = int(np.count_nonzero(valid & (state_2017 != state_2024)))
    axes[1, 0].set_title(
        f"2017–2024 标签变化位置（{changed:,} 像元，{changed / valid.sum():.1%}）"
    )
    _map_axis(axes[1, 0])

    years = [row["year"] for row in audit["land_cover_by_year"]]
    for value in range(1, 7):
        area = [row["class_area_km2"][str(value)] for row in audit["land_cover_by_year"]]
        axes[1, 1].plot(
            years,
            area,
            marker="o",
            linewidth=2,
            markersize=4,
            label=CLASS_LABELS[value],
            color=CLASS_COLORS[value],
        )
    axes[1, 1].set_title("年度类别面积轨迹")
    axes[1, 1].set_xlabel("年份")
    axes[1, 1].set_ylabel("面积（km²，对数坐标）")
    axes[1, 1].set_yscale("log")
    axes[1, 1].grid(axis="y", color="#e3e6e8", linewidth=0.7)
    axes[1, 1].legend(ncol=2, frameon=False, fontsize=8)
    figure.suptitle("阿布扎比统一网格上的年度土地覆盖输入", fontsize=17, fontweight="bold")
    _land_cover_legend(figure, y=-0.018)
    return _save(figure, "fig01_land_cover_overview.png")


def _masked(values: np.ndarray, valid: np.ndarray) -> np.ma.MaskedArray:
    return np.ma.masked_where(~valid, values)


def _continuous_map(
    axis: plt.Axes,
    values: np.ndarray,
    valid: np.ndarray,
    *,
    title: str,
    cmap: str,
    percentile: tuple[float, float] = (2, 98),
    colorbar_label: str,
) -> None:
    valid_values = values[valid & np.isfinite(values)]
    vmin, vmax = np.percentile(valid_values, percentile)
    image = axis.imshow(
        _masked(values, valid),
        cmap=cmap,
        vmin=float(vmin),
        vmax=float(vmax),
        interpolation="nearest",
    )
    axis.set_title(title)
    _map_axis(axis)
    colorbar = axis.figure.colorbar(image, ax=axis, fraction=0.035, pad=0.02)
    colorbar.set_label(colorbar_label, fontsize=8)
    colorbar.ax.tick_params(labelsize=7)


def alphaearth_pca_rgb(valid: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    embeddings = _read(INPUT_ROOT / "alphaearth/alphaearth_2024_100m.tif").astype(
        np.float32
    )
    matrix = embeddings[:, valid].T
    pca = PCA(n_components=3, svd_solver="randomized", random_state=31)
    components = pca.fit_transform(matrix)
    rgb_values = np.zeros_like(components, dtype=np.float32)
    for index in range(3):
        low, high = np.percentile(components[:, index], (2, 98))
        rgb_values[:, index] = np.clip((components[:, index] - low) / (high - low), 0, 1)
    rgb = np.ones((*valid.shape, 3), dtype=np.float32)
    rgb[valid] = rgb_values
    return rgb, pca.explained_variance_ratio_


def render_driver_inputs(valid: np.ndarray) -> Path:
    terrain = _read(INPUT_ROOT / "terrain/copernicus_dem_2024_1_slope_100m.tif")
    viirs = _read(INPUT_ROOT / "viirs/viirs_2024_100m.tif")[0]
    roads = _read(OSM_ROOT / "road_accessibility_100m.tif")
    quality = _read(INPUT_ROOT / "land_cover/land_cover_quality_2024_100m.tif")
    pca_rgb, explained = alphaearth_pca_rgb(valid)
    figure, axes = plt.subplots(2, 3, figsize=(13.5, 8.8), constrained_layout=True)
    _continuous_map(
        axes[0, 0],
        terrain[0],
        valid,
        title="Copernicus DEM 高程",
        cmap="terrain",
        colorbar_label="米",
    )
    _continuous_map(
        axes[0, 1],
        terrain[1],
        valid,
        title="由 100 m DEM 计算的坡度",
        cmap="magma",
        percentile=(0, 99),
        colorbar_label="度",
    )
    _continuous_map(
        axes[0, 2],
        np.log1p(np.clip(viirs, 0, None)),
        valid,
        title="2024 VIIRS 夜间灯光",
        cmap="inferno",
        colorbar_label="log(1 + 辐亮度)",
    )
    _continuous_map(
        axes[1, 0],
        roads[1],
        valid,
        title="距 OSM 主干道路距离",
        cmap="viridis_r",
        percentile=(0, 98),
        colorbar_label="米",
    )
    _continuous_map(
        axes[1, 1],
        quality[0],
        valid,
        title="2024 Dynamic World 平均最高概率",
        cmap="RdYlGn",
        percentile=(0, 100),
        colorbar_label="概率",
    )
    axes[1, 2].imshow(pca_rgb, interpolation="nearest")
    axes[1, 2].set_title(
        "2024 AlphaEarth 64 维嵌入 PCA-RGB\n"
        f"前三主成分解释 {explained.sum():.1%} 方差"
    )
    _map_axis(axes[1, 2])
    figure.suptitle("模型实际使用的主要空间驱动与表征", fontsize=17, fontweight="bold")
    figure.text(
        0.5,
        -0.015,
        "地图均裁剪到同一阿布扎比城市有效域；连续变量按城市像元分位数拉伸。",
        ha="center",
        fontsize=9,
        color="#50575b",
    )
    return _save(figure, "fig02_driver_inputs.png")


def render_temporal_quality(audit: dict[str, Any]) -> Path:
    figure, axes = plt.subplots(2, 2, figsize=(12.5, 8.4), constrained_layout=True)
    quality_rows = audit["land_cover_quality_by_year"]
    years = [row["year"] for row in quality_rows]
    below = [row["fraction_below_confidence_0_5"] * 100 for row in quality_rows]
    mean_probability = [row["mean_top_probability"]["mean"] for row in quality_rows]
    axes[0, 0].bar(years, below, color="#cc6677", width=0.7)
    axes[0, 0].axhline(50, color="#30373b", linestyle="--", linewidth=1)
    axes[0, 0].set_title("Dynamic World 低置信度像元比例")
    axes[0, 0].set_ylabel("最高概率 < 0.5 的像元（%）")
    axes[0, 0].set_ylim(0, 70)
    for year, value in zip(years, below, strict=True):
        axes[0, 0].text(year, value + 1.2, f"{value:.1f}", ha="center", fontsize=8)

    axes[0, 1].plot(years, mean_probability, marker="o", color="#4477aa", linewidth=2)
    axes[0, 1].axhline(0.5, color="#30373b", linestyle="--", linewidth=1)
    axes[0, 1].set_title("年度平均标签最高概率")
    axes[0, 1].set_ylabel("平均概率")
    axes[0, 1].set_ylim(0.4, 0.53)
    axes[0, 1].grid(axis="y", color="#e2e5e7")

    transitions = audit["land_cover_transitions"]
    labels = [f"{row['start_year']}→{row['target_year']}" for row in transitions]
    change = [row["change_fraction"] * 100 for row in transitions]
    axes[1, 0].bar(labels, change, color="#ddaa33")
    axes[1, 0].set_title("相邻年度标签变化比例")
    axes[1, 0].set_ylabel("变化像元（%）")
    axes[1, 0].tick_params(axis="x", rotation=35)

    reversions = audit["one_year_reversions"]
    reversion_labels = [f"{row['years'][0]}–{row['years'][2]}" for row in reversions]
    reversion = [row["one_year_reversion_fraction"] * 100 for row in reversions]
    axes[1, 1].bar(reversion_labels, reversion, color="#aa4499")
    axes[1, 1].set_title("一年后回退到原标签的比例")
    axes[1, 1].set_ylabel("回退占中间年变化像元（%）")
    axes[1, 1].tick_params(axis="x", rotation=35)
    for axis in axes.flat:
        axis.spines[["top", "right"]].set_visible(False)
    figure.suptitle(
        "输入标签质量诊断：存在真实变化信号，也存在显著年度波动",
        fontsize=17,
        fontweight="bold",
    )
    return _save(figure, "fig03_temporal_quality.png")


def _box(
    axis: plt.Axes,
    xy: tuple[float, float],
    width: float,
    height: float,
    text: str,
    color: str,
    *,
    fontsize: float = 10,
) -> None:
    patch = FancyBboxPatch(
        xy,
        width,
        height,
        boxstyle="round,pad=0.018,rounding_size=0.018",
        facecolor=color,
        edgecolor="#5f686d",
        linewidth=0.8,
    )
    axis.add_patch(patch)
    axis.text(
        xy[0] + width / 2,
        xy[1] + height / 2,
        text,
        ha="center",
        va="center",
        fontsize=fontsize,
        linespacing=1.35,
    )


def render_experiment_design() -> Path:
    figure, axis = plt.subplots(figsize=(13, 7.2))
    axis.set_xlim(0, 1)
    axis.set_ylim(0, 1)
    axis.axis("off")
    _box(
        axis,
        (0.03, 0.62),
        0.20,
        0.25,
        "真实输入数据\n2017–2024 土地覆盖\n地形 / 夜光 / 道路\nAlphaEarth / 生态约束",
        "#dceaf4",
    )
    _box(
        axis,
        (0.285, 0.62),
        0.18,
        0.25,
        "统一实验契约\nEPSG:32640 / 100 m\n79,726 共同有效像元\n同一需求与硬约束",
        "#e7e5df",
    )
    models = (
        ("GeoSOS-FLUS\n外部 ANN + CA", "#dce8f5"),
        ("Geospatial Kernel\n显式状态 + 空间适宜性", "#dcefdc"),
        ("Paper58\n需求条件 LDN + 潜状态", "#f2dfe5"),
    )
    for index, (text, color) in enumerate(models):
        _box(axis, (0.52, 0.70 - index * 0.25), 0.20, 0.17, text, color, fontsize=9.5)
    _box(
        axis,
        (0.78, 0.62),
        0.19,
        0.25,
        "历史模拟\n2022→2023→2024\n三随机种子\n状态逐年写回",
        "#f3ead7",
    )
    _box(
        axis,
        (0.78, 0.21),
        0.19,
        0.25,
        "规划推演\n2024→2025…2030\n三种需求情景\n多目标 Pareto 对比",
        "#e4e0ef",
    )
    arrow_pairs = (
        ((0.23, 0.745), (0.285, 0.745)),
        ((0.465, 0.745), (0.52, 0.785)),
        ((0.465, 0.745), (0.52, 0.535)),
        ((0.465, 0.745), (0.52, 0.285)),
        ((0.72, 0.785), (0.78, 0.745)),
        ((0.72, 0.535), (0.78, 0.745)),
        ((0.72, 0.285), (0.78, 0.335)),
        ((0.72, 0.535), (0.78, 0.335)),
        ((0.72, 0.785), (0.78, 0.335)),
    )
    for start, end in arrow_pairs:
        axis.annotate(
            "",
            xy=end,
            xytext=start,
            arrowprops={"arrowstyle": "->", "color": "#6e777c", "lw": 1.2},
        )
    axis.text(
        0.5,
        0.055,
        "公平性原则：模型只改变“如何分配空间”，不改变城市边界、网格、需求、约束和评价器。",
        ha="center",
        fontsize=11,
        color="#30373b",
        fontweight="bold",
    )
    figure.suptitle("阿布扎比三模型统一实验设计", fontsize=18, fontweight="bold")
    return _save(figure, "fig04_experiment_design.png")


def _prediction_path(
    comparison: dict[str, Any], model_id: str, year: int
) -> Path:
    return HERE / comparison["ensembles"][model_id][str(year)]["prediction_path"]


def render_historical_maps(valid: np.ndarray, comparison: dict[str, Any]) -> Path:
    observed = _read(INPUT_ROOT / "land_cover/land_cover_2024_100m.tif")[0]
    figure, axes = plt.subplots(1, 4, figsize=(15.5, 4.4), constrained_layout=True)
    rows = [("2024 观测标签", observed)] + [
        (MODEL_LABELS[model], _read(_prediction_path(comparison, model, 2024))[0])
        for model in MODEL_IDS
    ]
    cmap = ListedColormap(CLASS_COLORS)
    for axis, (title, state) in zip(axes, rows, strict=True):
        display = state.copy()
        display[~valid] = 0
        axis.imshow(display, cmap=cmap, vmin=0, vmax=6, interpolation="nearest")
        axis.set_title(title)
        _map_axis(axis)
    figure.suptitle(
        "2022 起点两步开环推演到 2024：观测与三模型集成结果",
        fontsize=16,
        fontweight="bold",
    )
    _land_cover_legend(figure, y=-0.04)
    return _save(figure, "fig05_historical_2024_maps.png")


def _error_map(
    origin: np.ndarray,
    target: np.ndarray,
    prediction: np.ndarray,
    valid: np.ndarray,
) -> np.ndarray:
    observed_change = valid & (target != origin)
    predicted_change = valid & (prediction != origin)
    result = np.zeros(origin.shape, dtype=np.uint8)
    result[valid & ~observed_change & ~predicted_change] = 1
    result[observed_change & predicted_change & (prediction == target)] = 2
    result[observed_change & predicted_change & (prediction != target)] = 3
    result[observed_change & ~predicted_change] = 4
    result[~observed_change & predicted_change] = 5
    return result


def render_historical_errors(valid: np.ndarray, comparison: dict[str, Any]) -> Path:
    origin = _read(INPUT_ROOT / "land_cover/land_cover_2022_100m.tif")[0]
    target = _read(INPUT_ROOT / "land_cover/land_cover_2024_100m.tif")[0]
    colors = ("#ffffff", "#d9dde0", "#228833", "#ddaa33", "#4477aa", "#cc3311")
    labels = (
        "稳定且正确",
        "变化位置与类别均正确",
        "命中变化位置但类别错误",
        "漏报变化",
        "误报变化",
    )
    figure, axes = plt.subplots(1, 3, figsize=(13.5, 4.6), constrained_layout=True)
    for axis, model_id in zip(axes, MODEL_IDS, strict=True):
        prediction = _read(_prediction_path(comparison, model_id, 2024))[0]
        error = _error_map(origin, target, prediction, valid)
        axis.imshow(
            error,
            cmap=ListedColormap(colors),
            vmin=0,
            vmax=5,
            interpolation="nearest",
        )
        metric = comparison["ensembles"][model_id]["2024"]["evaluation"]
        axis.set_title(
            f"{MODEL_LABELS[model_id]}\n"
            f"change FoM={metric['change_figure_of_merit']:.3f}"
        )
        _map_axis(axis)
    handles = [Patch(facecolor=colors[index], label=label) for index, label in enumerate(labels, 1)]
    figure.legend(
        handles=handles,
        loc="lower center",
        bbox_to_anchor=(0.5, -0.055),
        ncol=5,
        frameon=False,
        fontsize=8.5,
    )
    figure.suptitle("2024 变化位置和类别误差分解", fontsize=16, fontweight="bold")
    return _save(figure, "fig06_historical_change_errors.png")


def _grouped_metric(
    axis: plt.Axes,
    comparison: dict[str, Any],
    metric: str,
    *,
    title: str,
    ylim: tuple[float, float] | None = None,
) -> None:
    years = (2023, 2024)
    x = np.arange(len(years), dtype=float)
    width = 0.23
    for index, model_id in enumerate(MODEL_IDS):
        values = [
            comparison["summaries"][model_id][str(year)][metric]["mean"]
            for year in years
        ]
        positions = x + (index - 1) * width
        bars = axis.bar(
            positions,
            values,
            width,
            label=MODEL_LABELS[model_id],
            color=MODEL_COLORS[model_id],
        )
        axis.bar_label(bars, fmt="%.3f", fontsize=7, padding=2)
    axis.set_xticks(x, [str(year) for year in years])
    axis.set_title(title)
    if ylim:
        axis.set_ylim(*ylim)
    axis.grid(axis="y", color="#e5e8e9", linewidth=0.7)
    axis.spines[["top", "right"]].set_visible(False)


def render_historical_metrics(comparison: dict[str, Any]) -> Path:
    figure, axes = plt.subplots(2, 2, figsize=(12.5, 8.2), constrained_layout=True)
    _grouped_metric(
        axes[0, 0],
        comparison,
        "change_figure_of_merit",
        title="变化 Figure of Merit（主指标）",
        ylim=(0, 0.34),
    )
    _grouped_metric(
        axes[0, 1],
        comparison,
        "change_f1",
        title="变化 F1",
        ylim=(0, 0.52),
    )
    _grouped_metric(
        axes[1, 0],
        comparison,
        "overall_accuracy",
        title="总体准确率",
        ylim=(0.8, 0.97),
    )
    _grouped_metric(
        axes[1, 1],
        comparison,
        "reliability_change_figure_of_merit",
        title="高置信度子集变化 FoM",
        ylim=(0, 0.025),
    )
    handles = [
        Patch(facecolor=MODEL_COLORS[model], label=MODEL_LABELS[model])
        for model in MODEL_IDS
    ]
    figure.legend(
        handles=handles,
        loc="center right",
        bbox_to_anchor=(1.11, 0.5),
        ncol=1,
        frameon=False,
    )
    figure.suptitle(
        "历史模拟指标：2023 单步与 2024 两步开环",
        fontsize=17,
        fontweight="bold",
    )
    return _save(figure, "fig07_historical_metrics.png")


def _planning_bars(
    axis: plt.Axes,
    planning: dict[str, Any],
    metric: str,
    *,
    title: str,
    multiplier: float = 1.0,
    fmt: str = "%.1f",
) -> None:
    x = np.arange(len(SCENARIO_IDS), dtype=float)
    width = 0.23
    by_id = {row["candidate_id"]: row for row in planning["final_candidates"]}
    for index, model_id in enumerate(MODEL_IDS):
        values = [
            by_id[f"{model_id}:{scenario}"][metric] * multiplier
            for scenario in SCENARIO_IDS
        ]
        positions = x + (index - 1) * width
        bars = axis.bar(
            positions,
            values,
            width,
            color=MODEL_COLORS[model_id],
            label=MODEL_LABELS[model_id],
        )
        axis.bar_label(bars, fmt=fmt, fontsize=6.8, padding=2)
    axis.set_xticks(x, [SCENARIO_LABELS[value] for value in SCENARIO_IDS])
    axis.set_title(title)
    axis.grid(axis="y", color="#e5e8e9", linewidth=0.7)
    axis.spines[["top", "right"]].set_visible(False)


def render_planning_metrics(planning: dict[str, Any]) -> Path:
    figure, axes = plt.subplots(2, 3, figsize=(14.5, 8.5), constrained_layout=True)
    _planning_bars(
        axes[0, 0],
        planning,
        "demand_total_variation",
        title="需求总变差（×1000，越低越好）",
        multiplier=1000,
        fmt="%.2f",
    )
    _planning_bars(
        axes[0, 1],
        planning,
        "ecological_conversion_rate",
        title="新增建成占用原植被（%，越低越好）",
        multiplier=100,
        fmt="%.2f",
    )
    _planning_bars(
        axes[0, 2],
        planning,
        "new_built_neighbor_fraction",
        title="新增建成邻域紧凑度（越高越好）",
        fmt="%.3f",
    )
    _planning_bars(
        axes[1, 0],
        planning,
        "new_built_mean_major_road_distance_m",
        title="新增建成距主干路（m，越低越好）",
    )
    _planning_bars(
        axes[1, 1],
        planning,
        "new_built_mean_prior_built_distance_m",
        title="新增建成距既有建成区（m，越低越好）",
    )
    _planning_bars(
        axes[1, 2],
        planning,
        "removed_built_pixels",
        title="既有建成退出像元（越低越好）",
        fmt="%.0f",
    )
    handles = [
        Patch(facecolor=MODEL_COLORS[model], label=MODEL_LABELS[model])
        for model in MODEL_IDS
    ]
    figure.legend(
        handles=handles,
        loc="center right",
        bbox_to_anchor=(1.11, 0.5),
        ncol=1,
        frameon=False,
    )
    figure.suptitle(
        "2030 三情景规划结果的多目标分量",
        fontsize=17,
        fontweight="bold",
    )
    return _save(figure, "fig08_planning_metrics.png")


def render_all() -> list[Path]:
    configure_style()
    valid = _read(BUNDLE_ROOT / "common_valid_mask_100m.tif")[0].astype(bool)
    audit = _load_json(HERE / "data_audit.json")
    historical = _load_json(HERE / "comparison_report.json")
    planning = _load_json(HERE / "planning_comparison_report.json")
    return [
        render_land_cover_overview(valid, audit),
        render_driver_inputs(valid),
        render_temporal_quality(audit),
        render_experiment_design(),
        render_historical_maps(valid, historical),
        render_historical_errors(valid, historical),
        render_historical_metrics(historical),
        render_planning_metrics(planning),
    ]


def main() -> None:
    global FIGURE_ROOT
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, default=FIGURE_ROOT)
    args = parser.parse_args()
    FIGURE_ROOT = args.output_root
    for path in render_all():
        print(path)


if __name__ == "__main__":
    main()
