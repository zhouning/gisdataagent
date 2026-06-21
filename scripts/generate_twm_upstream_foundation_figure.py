#!/usr/bin/env python3
"""Generate the upstream engineering foundation figure for TWM."""

from __future__ import annotations

from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "docs" / "assets"
OUT_STEM = OUT_DIR / "twm_upstream_foundation_overview"


def choose_font() -> str:
    available = {font.name for font in font_manager.fontManager.ttflist}
    for name in [
        "PingFang SC",
        "Songti SC",
        "Heiti SC",
        "Arial Unicode MS",
        "Noto Sans CJK SC",
        "SimHei",
        "Microsoft YaHei",
        "DejaVu Sans",
    ]:
        if name in available:
            return name
    return "DejaVu Sans"


def apply_style() -> None:
    font = choose_font()
    mpl.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.sans-serif": [font, "Arial", "DejaVu Sans"],
            "svg.fonttype": "none",
            "pdf.fonttype": 42,
            "font.size": 7.2,
            "axes.linewidth": 0.8,
            "axes.unicode_minus": False,
            "figure.facecolor": "white",
            "savefig.facecolor": "white",
        }
    )


def box(
    ax,
    x,
    y,
    w,
    h,
    text,
    *,
    face="#F7F8FA",
    edge="#4D4D4D",
    lw=0.9,
    fontsize=6.7,
    weight="normal",
    radius=0.02,
    color="#272727",
    zorder=2,
):
    patch = FancyBboxPatch(
        (x, y),
        w,
        h,
        boxstyle=f"round,pad=0.016,rounding_size={radius}",
        linewidth=lw,
        edgecolor=edge,
        facecolor=face,
        zorder=zorder,
    )
    ax.add_patch(patch)
    ax.text(
        x + w / 2,
        y + h / 2,
        text,
        ha="center",
        va="center",
        fontsize=fontsize,
        fontweight=weight,
        color=color,
        linespacing=1.22,
        zorder=zorder + 1,
    )
    return patch


def arrow(ax, start, end, *, color="#606060", lw=1.0, rad=0.0, style="-|>"):
    ax.add_patch(
        FancyArrowPatch(
            start,
            end,
            arrowstyle=style,
            mutation_scale=7.5,
            linewidth=lw,
            color=color,
            connectionstyle=f"arc3,rad={rad}",
            shrinkA=2,
            shrinkB=2,
            zorder=1,
        )
    )


def label(ax, x, y, text, *, size=6.2, color="#606060", weight="normal", ha="center"):
    ax.text(x, y, text, fontsize=size, color=color, fontweight=weight, ha=ha, va="center")


def main() -> None:
    apply_style()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    fig, ax = plt.subplots(figsize=(7.2, 4.9))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    dark = "#272727"
    neutral = "#F6F7F8"
    neutral_edge = "#767676"
    blue = "#DCEAF7"
    blue_edge = "#0F4D92"
    lilac = "#ECE7F5"
    lilac_edge = "#6B5FA6"
    aqua = "#DDF2F0"
    aqua_edge = "#2B7C83"
    peach = "#F7E5D6"
    peach_edge = "#B56A2C"
    green = "#E3F2E4"
    green_edge = "#3E8F52"
    red_soft = "#F8E2E0"
    red_edge = "#B64342"

    ax.text(
        0.5,
        0.965,
        "TWM 前序工程底座：标准治理、语义组织与多模态语义产品生产",
        ha="center",
        va="top",
        fontsize=10.0,
        fontweight="bold",
        color=dark,
    )
    ax.text(
        0.5,
        0.928,
        "核心主张：TWM 的可信状态不是模型凭空生成，而是由权威标准、本体规则、运行时语义映射和 MMFE 语义产品共同支撑",
        ha="center",
        va="top",
        fontsize=6.55,
        color="#4D4D4D",
    )

    box(
        ax,
        0.055,
        0.71,
        0.22,
        0.14,
        "权威标准治理层\n数据标准全生命周期\n采集-分析-起草-审定-发布-派生\n数据元 / 值域 / 质量规则 / 角色契约",
        face=blue,
        edge=blue_edge,
        fontsize=6.35,
        weight="bold",
    )
    box(
        ax,
        0.39,
        0.71,
        0.22,
        0.14,
        "语义基础设施层\n本体：等价 / 派生 / 推理规则\n语义层：业务词汇-表字段-单位-坐标系\n运行时语义解析与字段绑定",
        face=lilac,
        edge=lilac_edge,
        fontsize=6.35,
        weight="bold",
    )
    box(
        ax,
        0.725,
        0.71,
        0.22,
        0.14,
        "多模态语义产品生产层\nMMFE 多模态地理空间语义融合\n探测-对齐-融合-质检-发布\n语义图 / 证据包 / 数据产品",
        face=aqua,
        edge=aqua_edge,
        fontsize=6.35,
        weight="bold",
    )

    arrow(ax, (0.275, 0.78), (0.39, 0.78), color=blue_edge, lw=1.25)
    arrow(ax, (0.61, 0.78), (0.725, 0.78), color=lilac_edge, lw=1.25)
    label(ax, 0.333, 0.666, "派生语义提示 / 值域 / 质检规则", size=5.6)
    label(ax, 0.667, 0.666, "字段语义 / 推理规则 / 运行时绑定", size=5.6)

    box(
        ax,
        0.075,
        0.49,
        0.16,
        0.095,
        "标准平台\n权威来源\n版本化 / 审定 / 发布 / 回滚",
        face="#FFFFFF",
        edge=blue_edge,
        fontsize=6.1,
        weight="bold",
    )
    box(
        ax,
        0.295,
        0.49,
        0.16,
        0.095,
        "本体规则\n概念等价\n派生字段 / 分类推理",
        face="#FFFFFF",
        edge=lilac_edge,
        fontsize=6.1,
        weight="bold",
    )
    box(
        ax,
        0.515,
        0.49,
        0.16,
        0.095,
        "语义层\n业务术语解析\n表 / 列 / 单位 / 坐标系绑定",
        face="#FFFFFF",
        edge=lilac_edge,
        fontsize=6.1,
        weight="bold",
    )
    box(
        ax,
        0.735,
        0.49,
        0.16,
        0.095,
        "MMFE 执行引擎\n多源对齐\n融合 / 质检 / 可解释发布",
        face="#FFFFFF",
        edge=aqua_edge,
        fontsize=6.1,
        weight="bold",
    )
    arrow(ax, (0.235, 0.537), (0.295, 0.537), color="#606060")
    arrow(ax, (0.455, 0.537), (0.515, 0.537), color="#606060")
    arrow(ax, (0.675, 0.537), (0.735, 0.537), color="#606060")

    box(
        ax,
        0.125,
        0.295,
        0.24,
        0.095,
        "语义产品与发布资产\nsemantic.json / 语义图 / 本体包\nOKF / STAC / 向量索引 / Lakehouse",
        face=peach,
        edge=peach_edge,
        fontsize=6.25,
        weight="bold",
    )
    box(
        ax,
        0.565,
        0.295,
        0.24,
        0.095,
        "TWM 可消费输入\n对象-关系-规则-证据包\n一张图角色契约 / 质量报告\n可构建空间治理状态",
        face=green,
        edge=green_edge,
        fontsize=6.25,
        weight="bold",
    )
    arrow(ax, (0.815, 0.49), (0.365, 0.39), color=aqua_edge, rad=0.12, lw=1.15)
    arrow(ax, (0.365, 0.342), (0.565, 0.342), color=peach_edge, lw=1.2)
    label(ax, 0.465, 0.372, "语义产品进入 TWM", size=5.8)

    box(
        ax,
        0.24,
        0.10,
        0.52,
        0.105,
        "治理反馈闭环\nTWM 运行证据、规则命中、复核结论、数据缺口\n反向进入标准修订、语义补齐、值域完善和质检规则增强",
        face=red_soft,
        edge=red_edge,
        fontsize=6.35,
        weight="bold",
    )
    arrow(ax, (0.685, 0.295), (0.63, 0.205), color=green_edge, rad=0.08, lw=1.15)
    arrow(ax, (0.24, 0.153), (0.145, 0.49), color=red_edge, rad=-0.25, lw=1.05)
    arrow(ax, (0.5, 0.205), (0.515, 0.49), color=red_edge, rad=0.04, lw=1.05)

    ax.text(
        0.5,
        0.038,
        "说明：本体和语义层是工程手段，MMFE 是语义产品生产器；它们共同把原始数据和标准规则转化为 TWM 可推演、可审计、可复核的空间治理状态材料。",
        ha="center",
        va="center",
        fontsize=6.05,
        color="#606060",
    )

    for suffix in ["svg", "pdf", "png", "tiff"]:
        kwargs = {"bbox_inches": "tight"}
        if suffix in {"png", "tiff"}:
            kwargs["dpi"] = 600
        fig.savefig(f"{OUT_STEM}.{suffix}", **kwargs)
    plt.close(fig)


if __name__ == "__main__":
    main()
