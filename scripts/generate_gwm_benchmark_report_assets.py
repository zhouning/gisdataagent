#!/usr/bin/env python3
"""Generate report figures from frozen GWM-Bench data and results."""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import BoundaryNorm, ListedColormap
from matplotlib.lines import Line2D
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch
import numpy as np
import pandas as pd
import rasterio


ROOT = Path(__file__).resolve().parents[1]
BENCHMARK_ROOT = ROOT / "benchmarks/gwm_bench_foundation_v0_1"
DEVELOPMENT_ROOT = BENCHMARK_ROOT / "development"
DATA_ROOT = ROOT / "data/twm_public_landcover/gee_dynamic_world"
OUTPUT_ROOT = (
    ROOT
    / "docs/research/assets/gwm_benchmark_data_architecture_comparison_2026-07-23"
)
MANIFEST_PATH = DATA_ROOT / "twm_dynamic_world_manifest.json"
INPUTS_PATH = DEVELOPMENT_ROOT / "observed_inputs.parquet"
TWM_PREDICTION_PATH = (
    DEVELOPMENT_ROOT / "twm_v3_historical_backtest/twm_v3_prediction.parquet"
)
FLUS_PREDICTION_PATH = (
    DEVELOPMENT_ROOT
    / "flus_full_grid_historical_backtest_ensemble/"
    "flus_full_grid_historical_ensemble_prediction.parquet"
)
EVALUATION_PATH = DEVELOPMENT_ROOT / "twm_v3_historical_backtest/evaluation.json"
PREVIEW_REGION = "天津市_滨海新区_临港工业区"
PREVIEW_YEAR = 2020

DW_NAMES = [
    "水体",
    "树木",
    "草地",
    "淹水植被",
    "农作物",
    "灌木",
    "建成区",
    "裸地",
    "冰雪",
]
DW_COLORS = [
    "#419BDF",
    "#397D49",
    "#88B053",
    "#7A87C6",
    "#E49635",
    "#DFC35A",
    "#C4281B",
    "#A59B8F",
    "#B39FE1",
]
MODEL_COLORS = {"TWM": "#167D72", "FLUS": "#C7543D"}


def configure_plotting() -> None:
    plt.rcParams.update(
        {
            "font.family": ["Arial Unicode MS", "Hiragino Sans GB", "sans-serif"],
            "font.size": 10,
            "axes.titlesize": 12,
            "axes.labelsize": 10,
            "axes.edgecolor": "#343A40",
            "axes.linewidth": 0.8,
            "xtick.color": "#4A4F55",
            "ytick.color": "#4A4F55",
            "text.color": "#202428",
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "savefig.facecolor": "white",
        }
    )


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def short_region_name(region_id: str) -> str:
    parts = region_id.split("_")
    if len(parts) >= 3:
        return f"{parts[0].removesuffix('市')}·{parts[-1]}"
    return region_id


def city_name(region_id: str) -> str:
    return region_id.split("_")[0].removesuffix("市")


def read_masked(path: Path) -> tuple[np.ma.MaskedArray, tuple[float, ...]]:
    with rasterio.open(path) as dataset:
        return dataset.read(1, masked=True), dataset.bounds


def raster_path(region_id: str, suffix: str) -> Path:
    return DATA_ROOT / region_id / f"{region_id}_{suffix}_100m.tif"


def save_figure(fig: plt.Figure, name: str) -> None:
    path = OUTPUT_ROOT / name
    fig.savefig(path, dpi=180, bbox_inches="tight", pad_inches=0.12)
    plt.close(fig)


def plot_dataset_coverage(inputs: pd.DataFrame, manifest: dict) -> dict:
    test_inputs = inputs.loc[inputs["split"] == "test"].copy()
    node_counts = (
        test_inputs.groupby("region_id", as_index=False)
        .size()
        .rename(columns={"size": "node_count"})
    )
    region_rows = []
    for region in manifest["regions"]:
        west, south, east, north = region["bbox"]
        region_rows.append(
            {
                "region_id": region["region_id"],
                "lon": (west + east) / 2.0,
                "lat": (south + north) / 2.0,
                "area_km2": float(region["admin"]["area_km2"]),
            }
        )
    regions = pd.DataFrame(region_rows).merge(node_counts, on="region_id")

    fig, axes = plt.subplots(1, 2, figsize=(14, 7), gridspec_kw={"width_ratios": [1, 1.25]})
    ax = axes[0]
    sizes = 35 + 150 * regions["node_count"] / regions["node_count"].max()
    scatter = ax.scatter(
        regions["lon"],
        regions["lat"],
        s=sizes,
        c=regions["node_count"],
        cmap="viridis",
        edgecolor="white",
        linewidth=0.8,
        zorder=3,
    )
    label_offsets = {
        "北京": (4, 4),
        "天津": (4, 4),
        "上海": (5, 8),
        "苏州": (5, -7),
        "杭州": (-32, -8),
        "宁波": (5, -9),
        "合肥": (-32, 6),
        "南京": (-34, 8),
        "武汉": (-33, 6),
        "长沙": (-34, -7),
        "成都": (-34, -7),
        "西安": (-29, 6),
        "郑州": (5, 5),
        "厦门": (-28, -10),
        "福州": (5, -7),
        "广州": (-30, 10),
        "深圳": (5, -11),
        "东莞": (-31, -8),
        "佛山": (-29, -18),
        "重庆": (-34, 7),
    }
    for row in regions.itertuples():
        label = city_name(row.region_id)
        ax.annotate(
            label,
            (row.lon, row.lat),
            xytext=label_offsets.get(label, (4, 3)),
            textcoords="offset points",
            fontsize=7.8,
        )
    ax.set_xlim(100, 124)
    ax.set_ylim(21, 42)
    ax.set_xlabel("经度")
    ax.set_ylabel("纬度")
    ax.set_title("20 个真实地区的空间覆盖")
    ax.grid(color="#D9DEE3", linewidth=0.5, alpha=0.8)
    colorbar = fig.colorbar(scatter, ax=ax, shrink=0.78, pad=0.02)
    colorbar.set_label("冻结节点数")

    ax = axes[1]
    ordered = regions.sort_values("node_count", ascending=True)
    y = np.arange(len(ordered))
    ax.barh(y, ordered["node_count"], color="#4C78A8", height=0.68)
    ax.set_yticks(y, [short_region_name(value) for value in ordered["region_id"]])
    ax.set_xlabel("节点数（每个节点代表一个冻结的 100 m 像元位置）")
    ax.set_title("各地区节点量；总计 1,055")
    ax.grid(axis="x", color="#D9DEE3", linewidth=0.5)
    for index, value in enumerate(ordered["node_count"]):
        ax.text(value + 0.8, index, str(int(value)), va="center", fontsize=8)
    ax.spines[["top", "right"]].set_visible(False)
    fig.suptitle(
        "GWM-Bench OBSERVED-O1：跨地区空间覆盖与冻结抽样规模",
        fontsize=16,
        fontweight="bold",
        y=1.01,
    )
    fig.tight_layout()
    save_figure(fig, "01_dataset_coverage_and_nodes.png")
    return {
        "region_count": int(regions.shape[0]),
        "unique_node_count": int(node_counts["node_count"].sum()),
        "total_admin_area_km2": float(regions["area_km2"].sum()),
        "minimum_region_node_count": int(regions["node_count"].min()),
        "maximum_region_node_count": int(regions["node_count"].max()),
    }


def plot_raw_data_preview() -> dict:
    land_2017, _ = read_masked(raster_path(PREVIEW_REGION, "dynamic_world_2017"))
    land_2020, _ = read_masked(raster_path(PREVIEW_REGION, "dynamic_world_2020"))
    viirs_2020, _ = read_masked(raster_path(PREVIEW_REGION, "viirs_nightlight_2020"))
    elevation, _ = read_masked(raster_path(PREVIEW_REGION, "srtm_elevation"))

    class_cmap = ListedColormap(DW_COLORS)
    class_cmap.set_bad("#F1F3F5")
    class_norm = BoundaryNorm(np.arange(-0.5, 9.5, 1), class_cmap.N)
    fig, axes = plt.subplots(2, 2, figsize=(12, 10))
    axes[0, 0].imshow(land_2017, cmap=class_cmap, norm=class_norm)
    axes[0, 0].set_title("Dynamic World 年度众数：2017（训练输入）")
    image = axes[0, 1].imshow(land_2020, cmap=class_cmap, norm=class_norm)
    axes[0, 1].set_title("Dynamic World 年度众数：2020（预测起点）")
    vmax = float(np.nanpercentile(viirs_2020.filled(np.nan), 98))
    night = axes[1, 0].imshow(viirs_2020, cmap="magma", vmin=0, vmax=vmax)
    axes[1, 0].set_title("VIIRS 年均夜间灯光：2020（训练输入）")
    terrain = axes[1, 1].imshow(elevation, cmap="terrain")
    axes[1, 1].set_title("SRTM 高程（静态输入）")
    for ax in axes.flat:
        ax.set_xticks([])
        ax.set_yticks([])
        ax.spines[:].set_visible(False)
    land_colorbar = fig.colorbar(image, ax=axes[0, :], fraction=0.035, pad=0.02, ticks=range(9))
    land_colorbar.ax.set_yticklabels(DW_NAMES)
    fig.colorbar(night, ax=axes[1, 0], fraction=0.045, pad=0.02, label="nW/cm²/sr")
    fig.colorbar(terrain, ax=axes[1, 1], fraction=0.045, pad=0.02, label="米")
    fig.suptitle(
        "原始 GeoTIFF 预览：天津市滨海新区临港工业区（100 m）",
        fontsize=16,
        fontweight="bold",
        y=0.98,
    )
    fig.subplots_adjust(top=0.91, bottom=0.04, left=0.04, right=0.94, hspace=0.15, wspace=0.1)
    save_figure(fig, "02_raw_geotiff_preview_tianjin.png")
    return {
        "region_id": PREVIEW_REGION,
        "raster_shape": [int(land_2020.shape[0]), int(land_2020.shape[1])],
        "valid_land_pixels": int(land_2020.count()),
        "land_classes_present": sorted(int(value) for value in np.unique(land_2020.compressed())),
        "viirs_2020_min": float(viirs_2020.min()),
        "viirs_2020_max": float(viirs_2020.max()),
        "elevation_min_m": float(elevation.min()),
        "elevation_max_m": float(elevation.max()),
    }


def add_box(
    ax: plt.Axes,
    x: float,
    y: float,
    width: float,
    height: float,
    title: str,
    body: str,
    *,
    facecolor: str,
    edgecolor: str,
    title_color: str = "#17212B",
) -> None:
    patch = FancyBboxPatch(
        (x, y),
        width,
        height,
        boxstyle="round,pad=0.012,rounding_size=0.015",
        linewidth=1.3,
        edgecolor=edgecolor,
        facecolor=facecolor,
    )
    ax.add_patch(patch)
    ax.text(x + 0.018, y + height - 0.034, title, fontsize=12, fontweight="bold", color=title_color, va="top")
    ax.text(x + 0.018, y + height - 0.085, body, fontsize=9.2, color="#303840", va="top", linespacing=1.45)


def arrow(ax: plt.Axes, start: tuple[float, float], end: tuple[float, float]) -> None:
    ax.add_patch(
        FancyArrowPatch(
            start,
            end,
            arrowstyle="-|>",
            mutation_scale=14,
            linewidth=1.5,
            color="#5E6973",
            connectionstyle="arc3,rad=0",
        )
    )


def plot_architecture() -> None:
    fig, ax = plt.subplots(figsize=(15, 9))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    ax.text(0.5, 0.965, "GWM → TWM 技术架构：运行边界与空间动力学分层", ha="center", fontsize=17, fontweight="bold")
    ax.text(
        0.5,
        0.925,
        "Runtime Kernel 组织一次可审计的世界模型运行；DAM-GK 计算空间状态如何变化",
        ha="center",
        fontsize=10.5,
        color="#4B5560",
    )

    add_box(
        ax,
        0.04,
        0.72,
        0.92,
        0.14,
        "数据与证据层",
        "Dynamic World 年度土地覆盖  |  VIIRS 年均夜光  |  SRTM 高程/坡度  |  地区边界与 CRS\n"
        "来源与许可、时间可用性、栅格对齐、SHA256、未来标签隔离",
        facecolor="#EDF4FA",
        edgecolor="#4C78A8",
    )
    add_box(
        ax,
        0.04,
        0.48,
        0.42,
        0.18,
        "GWM Runtime Kernel（平台运行边界）",
        "StateSnapshot / 状态版本\nCanonicalAction 与转移路由\n状态写回、多步 rollout、不确定性传播\n评价器、证据账本、主张降级、人工复核",
        facecolor="#F4F0FA",
        edgecolor="#7A5AA6",
    )
    add_box(
        ax,
        0.54,
        0.48,
        0.42,
        0.18,
        "TWM 领域适配层",
        "把土地类别、夜光、地形与空间节点编译为 DAMGKBatch\n绑定九类土地转移头、地区留出、递归年份与评分协议\n本 benchmark 不把遥感变化解释为政策因果效应",
        facecolor="#FFF5E8",
        edgecolor="#D18B2C",
    )
    add_box(
        ax,
        0.17,
        0.16,
        0.66,
        0.23,
        "Geospatial Kernel / DAM-GK（现有可训练空间动力学算子）",
        "输入：(候选空间图 Gₜ，节点状态 Sₜ，行动 Aₜ，上下文 Cₜ)\n"
        "节点/行动/区域/关系编码 → 动态关系门控 → 时滞分布 → 候选边软拓扑概率\n"
        "多关系消息传播与融合 → 变化概率 + 目标类别 + 不确定性 → 写回 Sₜ₊₁ 后递归",
        facecolor="#EAF6F1",
        edgecolor="#167D72",
    )
    add_box(
        ax,
        0.17,
        0.015,
        0.66,
        0.11,
        "Benchmark 输出与门禁",
        "九类概率、变化定位、类别状态、Brier；基线/负对照/隐藏评测共同限制可声称结论",
        facecolor="#F8F9FA",
        edgecolor="#69737D",
    )
    arrow(ax, (0.5, 0.72), (0.5, 0.665))
    arrow(ax, (0.25, 0.48), (0.35, 0.39))
    arrow(ax, (0.75, 0.48), (0.65, 0.39))
    arrow(ax, (0.5, 0.16), (0.5, 0.125))
    ax.text(
        0.035,
        0.445,
        "当前实现边界：共享 Runtime Kernel 尚未完成平台级抽取；\n"
        "TWM benchmark 直接调用已实现的 DAM-GK 研究包和冻结评分协议。",
        fontsize=9,
        color="#8C2F39",
        va="top",
    )
    save_figure(fig, "03_gwm_runtime_dam_gk_twm_architecture.png")


def prediction_classes(frame: pd.DataFrame) -> pd.DataFrame:
    probability_columns = [f"probability_{index}" for index in range(9)]
    result = frame[["fold_index", "region_id", "node_id", "target_year"]].copy()
    result["predicted_class"] = np.argmax(
        frame[probability_columns].to_numpy(dtype=np.float64), axis=1
    )
    return result


def change_confusion(
    positions: pd.DataFrame, predictions: pd.DataFrame, year: int
) -> pd.DataFrame:
    selected = predictions[
        (predictions["region_id"] == PREVIEW_REGION)
        & (predictions["target_year"] == year)
    ]
    result = positions.merge(
        selected[["fold_index", "region_id", "node_id", "predicted_class"]],
        on=["fold_index", "region_id", "node_id"],
        validate="one_to_one",
    )
    result["predicted_change"] = (
        result["predicted_class"] != result[f"land_class_{year - 1}"]
    )
    result["confusion"] = np.select(
        [
            result["observed_change"] & result["predicted_change"],
            ~result["observed_change"] & result["predicted_change"],
            result["observed_change"] & ~result["predicted_change"],
        ],
        ["TP", "FP", "FN"],
        default="TN",
    )
    return result


def plot_result_preview(
    inputs: pd.DataFrame, twm: pd.DataFrame, flus: pd.DataFrame
) -> dict:
    positions = inputs[
        (inputs["split"] == "test") & (inputs["region_id"] == PREVIEW_REGION)
    ][
        [
            "fold_index",
            "region_id",
            "node_id",
            "raster_row",
            "raster_column",
            "land_class_2019",
            "land_class_2020",
        ]
    ].copy()
    positions["observed_change"] = (
        positions["land_class_2020"] != positions["land_class_2019"]
    )
    twm_confusion = change_confusion(positions, prediction_classes(twm), PREVIEW_YEAR)
    flus_confusion = change_confusion(positions, prediction_classes(flus), PREVIEW_YEAR)
    background, _ = read_masked(raster_path(PREVIEW_REGION, "dynamic_world_2020"))
    class_cmap = ListedColormap(DW_COLORS)
    class_cmap.set_bad("white")
    class_norm = BoundaryNorm(np.arange(-0.5, 9.5, 1), class_cmap.N)

    fig, axes = plt.subplots(1, 3, figsize=(15, 5.4))
    for ax in axes:
        ax.imshow(background, cmap=class_cmap, norm=class_norm, alpha=0.28)
        ax.set_xlim(-0.5, background.shape[1] - 0.5)
        ax.set_ylim(background.shape[0] - 0.5, -0.5)
        ax.set_xticks([])
        ax.set_yticks([])
        ax.spines[:].set_visible(False)

    axes[0].scatter(
        positions["raster_column"],
        positions["raster_row"],
        s=25,
        c=np.where(positions["observed_change"], "#202428", "#C9CED3"),
        edgecolor="white",
        linewidth=0.45,
    )
    axes[0].set_title("真实变化\n11 / 54 个冻结节点")

    confusion_colors = {"TP": "#168B62", "FP": "#F39C35", "FN": "#C73E4D", "TN": "#C9CED3"}
    labels = {
        "TP": "命中",
        "FP": "误报",
        "FN": "漏报",
        "TN": "正确不变",
    }
    summaries = {}
    for ax, name, frame in (
        (axes[1], "TWM", twm_confusion),
        (axes[2], "FLUS", flus_confusion),
    ):
        colors = frame["confusion"].map(confusion_colors)
        ax.scatter(
            frame["raster_column"],
            frame["raster_row"],
            s=31,
            c=colors,
            edgecolor="white",
            linewidth=0.5,
        )
        counts = frame["confusion"].value_counts().to_dict()
        tp = int(counts.get("TP", 0))
        fp = int(counts.get("FP", 0))
        fn = int(counts.get("FN", 0))
        f1 = 2 * tp / (2 * tp + fp + fn)
        ax.set_title(f"{name} 变化定位\nTP={tp}  FP={fp}  FN={fn}  F1={f1:.3f}")
        summaries[name] = {
            "true_positive": tp,
            "false_positive": fp,
            "false_negative": fn,
            "change_f1": f1,
            "predicted_change_count": int(frame["predicted_change"].sum()),
        }

    legend_handles = [
        Line2D(
            [0],
            [0],
            marker="o",
            color="none",
            markerfacecolor=color,
            markeredgecolor="white",
            markersize=8,
            label=labels[key],
        )
        for key, color in confusion_colors.items()
    ]
    fig.legend(handles=legend_handles, loc="lower center", ncol=4, frameon=False, bbox_to_anchor=(0.5, -0.01))
    fig.suptitle(
        "结果空间预览：天津市滨海新区临港工业区，预测 2020 年变化",
        fontsize=16,
        fontweight="bold",
        y=1.02,
    )
    fig.tight_layout(rect=(0, 0.05, 1, 0.95))
    save_figure(fig, "04_result_spatial_preview_tianjin_2020.png")
    return {
        "region_id": PREVIEW_REGION,
        "target_year": PREVIEW_YEAR,
        "node_count": int(len(positions)),
        "observed_change_count": int(positions["observed_change"].sum()),
        "models": summaries,
    }


def plot_final_comparison(evaluation: dict) -> dict:
    twm = evaluation["evaluations"]["twm_v3"]
    flus = evaluation["evaluations"]["flus_full_grid"]
    twm_overall = twm["overall_secondary_metrics"]
    flus_overall = flus["overall_secondary_metrics"]
    metric_rows = [
        ("地区-年份平均\n变化 F1", twm["primary_metric"]["value"], flus["primary_metric"]["value"], "higher"),
        ("整体变化 F1", twm_overall["change_f1"], flus_overall["change_f1"], "higher"),
        ("变化后类别\nMacro-F1", twm_overall["changed_destination_macro_f1"], flus_overall["changed_destination_macro_f1"], "higher"),
        ("整体类别\nMacro-F1", twm_overall["overall_class_macro_f1"], flus_overall["overall_class_macro_f1"], "higher"),
        ("Brier\n（越低越好）", twm_overall["multiclass_brier_score"], flus_overall["multiclass_brier_score"], "lower"),
    ]
    labels = [row[0] for row in metric_rows]
    twm_values = np.array([row[1] for row in metric_rows])
    flus_values = np.array([row[2] for row in metric_rows])

    fig, axes = plt.subplots(1, 2, figsize=(14, 6), gridspec_kw={"width_ratios": [1.65, 0.8]})
    ax = axes[0]
    x = np.arange(len(labels))
    width = 0.34
    bars_twm = ax.bar(x - width / 2, twm_values, width, label="最终 TWM", color=MODEL_COLORS["TWM"])
    bars_flus = ax.bar(x + width / 2, flus_values, width, label="FLUS", color=MODEL_COLORS["FLUS"])
    ax.set_ylim(0, 0.61)
    ax.set_ylabel("指标值")
    ax.set_xticks(x, labels)
    ax.set_title("同一历史回测口径的最终指标")
    ax.grid(axis="y", color="#D9DEE3", linewidth=0.6)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False, loc="upper left")
    ax.bar_label(bars_twm, fmt="%.3f", padding=3, fontsize=8.5)
    ax.bar_label(bars_flus, fmt="%.3f", padding=3, fontsize=8.5)

    ax = axes[1]
    count_labels = ["真实变化", "最终 TWM", "FLUS"]
    counts = [
        int(twm_overall["observed_changed_count"]),
        int(twm_overall["predicted_changed_count"]),
        int(flus_overall["predicted_changed_count"]),
    ]
    count_colors = ["#343A40", MODEL_COLORS["TWM"], MODEL_COLORS["FLUS"]]
    bars = ax.bar(count_labels, counts, color=count_colors, width=0.62)
    ax.bar_label(bars, padding=4, fontsize=11, fontweight="bold")
    ax.axhline(counts[0], color="#343A40", linestyle="--", linewidth=1, alpha=0.6)
    ax.set_ylim(0, 220)
    ax.set_ylabel("2019 + 2020 变化节点数")
    ax.set_title("变化数量校准")
    ax.grid(axis="y", color="#D9DEE3", linewidth=0.6)
    ax.spines[["top", "right"]].set_visible(False)
    fig.suptitle(
        "最终 TWM 与真实 FLUS 对比（20 地区、2 年、2,110 行预测）",
        fontsize=16,
        fontweight="bold",
        y=1.02,
    )
    fig.tight_layout()
    save_figure(fig, "05_final_twm_vs_flus_comparison.png")
    return {
        "twm": {
            "primary_change_f1": float(twm["primary_metric"]["value"]),
            **{key: value for key, value in twm_overall.items() if key != "row_count"},
        },
        "flus": {
            "primary_change_f1": float(flus["primary_metric"]["value"]),
            **{key: value for key, value in flus_overall.items() if key != "row_count"},
        },
        "primary_absolute_difference": float(
            twm["primary_metric"]["value"] - flus["primary_metric"]["value"]
        ),
        "primary_relative_improvement": float(
            twm["primary_metric"]["value"] / flus["primary_metric"]["value"] - 1.0
        ),
        "paired_region_bootstrap": evaluation["primary_comparison"][
            "paired_region_bootstrap"
        ]["flus_full_grid"],
        "claim_boundary": evaluation["claim_boundary"],
    }


def main() -> int:
    configure_plotting()
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    manifest = load_json(MANIFEST_PATH)
    inputs = pd.read_parquet(INPUTS_PATH)
    twm = pd.read_parquet(TWM_PREDICTION_PATH)
    flus = pd.read_parquet(FLUS_PREDICTION_PATH)
    evaluation = load_json(EVALUATION_PATH)
    figure_data = {
        "schema": "gwm_bench.report_figure_data.v1",
        "sources": {
            "manifest": str(MANIFEST_PATH.relative_to(ROOT)),
            "observed_inputs": str(INPUTS_PATH.relative_to(ROOT)),
            "twm_prediction": str(TWM_PREDICTION_PATH.relative_to(ROOT)),
            "flus_prediction": str(FLUS_PREDICTION_PATH.relative_to(ROOT)),
            "evaluation": str(EVALUATION_PATH.relative_to(ROOT)),
        },
        "dataset_coverage": plot_dataset_coverage(inputs, manifest),
        "raw_preview": plot_raw_data_preview(),
        "result_preview": plot_result_preview(inputs, twm, flus),
        "final_comparison": plot_final_comparison(evaluation),
    }
    plot_architecture()
    (OUTPUT_ROOT / "figure_data.json").write_text(
        json.dumps(figure_data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(figure_data, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
