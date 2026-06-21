#!/usr/bin/env python3
"""Generate a publication-style TWM architecture figure."""

from __future__ import annotations

from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "docs" / "assets"
OUT_STEM = OUT_DIR / "twm_architecture_overview"


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
            "font.size": 7.6,
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
    fontsize=7.2,
    weight="normal",
    color="#272727",
    radius=0.025,
    zorder=2,
):
    patch = FancyBboxPatch(
        (x, y),
        w,
        h,
        boxstyle=f"round,pad=0.018,rounding_size={radius}",
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
        linespacing=1.25,
        zorder=zorder + 1,
    )
    return patch


def arrow(ax, start, end, *, color="#606060", lw=1.1, rad=0.0, style="-|>"):
    ax.add_patch(
        FancyArrowPatch(
            start,
            end,
            arrowstyle=style,
            mutation_scale=8,
            linewidth=lw,
            color=color,
            connectionstyle=f"arc3,rad={rad}",
            shrinkA=2,
            shrinkB=2,
            zorder=1,
        )
    )


def main() -> None:
    apply_style()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    fig, ax = plt.subplots(figsize=(7.2, 5.1))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    neutral = "#F5F6F7"
    blue = "#DCEAF7"
    blue_edge = "#0F4D92"
    teal = "#DDF2F0"
    teal_edge = "#2B7C83"
    green = "#E3F2E4"
    green_edge = "#3E8F52"
    peach = "#F7E5D6"
    peach_edge = "#B56A2C"
    lilac = "#ECE7F5"
    lilac_edge = "#6B5FA6"
    red_soft = "#F8E2E0"
    red_edge = "#B64342"
    dark = "#272727"

    ax.text(
        0.5,
        0.965,
        "面向自然资源治理的地理空间世界模型（TWM）总体技术架构",
        ha="center",
        va="top",
        fontsize=10.5,
        fontweight="bold",
        color=dark,
    )
    ax.text(
        0.5,
        0.925,
        "核心主张：以层次化空间治理状态为中心，将权威数据、法定规则、行动推演、规划优化、因果校准和证据审计组织为闭环",
        ha="center",
        va="top",
        fontsize=6.9,
        color="#4D4D4D",
    )

    box(
        ax,
        0.045,
        0.74,
        0.18,
        0.13,
        "权威数据与标准\n国土调查 / 变更调查\n规划一张图 / 三条控制线\n审批监管 / 遥感监测",
        face=neutral,
        edge="#767676",
        fontsize=6.5,
        weight="bold",
    )
    box(
        ax,
        0.285,
        0.74,
        0.18,
        0.13,
        "语义组织与融合\n本体语义层\n多模态地理空间语义融合\n对象-关系-规则-证据",
        face=neutral,
        edge="#767676",
        fontsize=6.5,
        weight="bold",
    )
    box(
        ax,
        0.535,
        0.74,
        0.18,
        0.13,
        "候选行动与情景\n规划调整 / 用途管制\n保护修复 / 整治治理\n审批审查 / 监管行动",
        face=neutral,
        edge="#767676",
        fontsize=6.5,
        weight="bold",
    )
    box(
        ax,
        0.775,
        0.74,
        0.18,
        0.13,
        "业务输出入口\n风险预警 / 方案比选\n证据审计 / 人工复核\n业务系统与智能体调用",
        face=neutral,
        edge="#767676",
        fontsize=6.5,
        weight="bold",
    )

    arrow(ax, (0.225, 0.805), (0.285, 0.805), color="#767676")
    arrow(ax, (0.465, 0.805), (0.535, 0.805), color="#767676")

    box(
        ax,
        0.12,
        0.40,
        0.76,
        0.26,
        "",
        face="#FBFCFD",
        edge=blue_edge,
        lw=1.15,
        radius=0.03,
        zorder=0,
    )
    ax.text(
        0.5,
        0.635,
        "TWM 核心：状态-行动-规则-证据联合建模",
        ha="center",
        va="center",
        fontsize=9.1,
        fontweight="bold",
        color=blue_edge,
    )

    box(
        ax,
        0.155,
        0.475,
        0.18,
        0.105,
        "层次化空间治理状态\n地块-片区-区县\n规划分区-管控边界\n项目-规则-证据",
        face=blue,
        edge=blue_edge,
        fontsize=6.55,
        weight="bold",
    )
    box(
        ax,
        0.41,
        0.475,
        0.18,
        0.105,
        "行动条件模拟器\n规则模型 / 空间统计\n图模型 / 时空 Transformer\n行业模型组合",
        face=teal,
        edge=teal_edge,
        fontsize=6.55,
        weight="bold",
    )
    box(
        ax,
        0.665,
        0.475,
        0.18,
        0.105,
        "多头推演输出\n未来状态\n约束风险 / 规划效用\n不确定性 / 证据缺口",
        face=green,
        edge=green_edge,
        fontsize=6.55,
        weight="bold",
    )

    arrow(ax, (0.335, 0.528), (0.41, 0.528), color=blue_edge, lw=1.25)
    arrow(ax, (0.59, 0.528), (0.665, 0.528), color=teal_edge, lw=1.25)
    arrow(ax, (0.715, 0.74), (0.735, 0.585), color="#767676", rad=-0.08)
    arrow(ax, (0.775, 0.585), (0.835, 0.74), color="#767676", rad=-0.08)
    arrow(ax, (0.375, 0.74), (0.245, 0.585), color="#767676", rad=0.06)
    arrow(ax, (0.625, 0.74), (0.505, 0.585), color="#767676", rad=0.06)

    box(
        ax,
        0.075,
        0.235,
        0.17,
        0.09,
        "硬约束门控\n法定规则优先\n禁止高分越界方案",
        face=red_soft,
        edge=red_edge,
        fontsize=6.5,
        weight="bold",
    )
    box(
        ax,
        0.29,
        0.235,
        0.17,
        0.09,
        "规划器与优化器\n束搜索 / 模型预测控制\n外部优化方案接入",
        face=peach,
        edge=peach_edge,
        fontsize=6.5,
        weight="bold",
    )
    box(
        ax,
        0.505,
        0.235,
        0.17,
        0.09,
        "因果校准与空间因果证据\n观测历史 / 反事实检验\nSCCA 证据增强",
        face=lilac,
        edge=lilac_edge,
        fontsize=6.5,
        weight="bold",
    )
    box(
        ax,
        0.72,
        0.235,
        0.17,
        0.09,
        "证据门控与验证阶梯\n通过 / 复核 / 阻断\n结论可信等级控制",
        face=red_soft,
        edge=red_edge,
        fontsize=6.5,
        weight="bold",
    )
    arrow(ax, (0.245, 0.28), (0.29, 0.28), color="#606060")
    arrow(ax, (0.46, 0.28), (0.505, 0.28), color="#606060")
    arrow(ax, (0.675, 0.28), (0.72, 0.28), color="#606060")
    arrow(ax, (0.805, 0.325), (0.78, 0.475), color=red_edge, rad=-0.08)
    arrow(ax, (0.16, 0.325), (0.20, 0.475), color=red_edge, rad=0.08)

    box(
        ax,
        0.18,
        0.075,
        0.26,
        0.085,
        "可审计成果\nGIS 图层 / 指标表 / 风险清单 / 方案排序 / 证据链报告",
        face="#FFFFFF",
        edge="#767676",
        fontsize=6.8,
        weight="bold",
    )
    box(
        ax,
        0.56,
        0.075,
        0.26,
        0.085,
        "人工复核与业务闭环\n专家确认 / 责任留痕 / 规则修订 / 模型再验证",
        face="#FFFFFF",
        edge="#767676",
        fontsize=6.8,
        weight="bold",
    )
    arrow(ax, (0.805, 0.235), (0.69, 0.16), color="#606060", rad=0.08)
    arrow(ax, (0.56, 0.118), (0.44, 0.118), color="#606060")
    arrow(ax, (0.31, 0.16), (0.16, 0.235), color="#606060", rad=-0.08)
    arrow(ax, (0.69, 0.16), (0.87, 0.74), color="#606060", rad=-0.28)

    ax.text(
        0.5,
        0.018,
        "说明：规划器、深度学习模型和外部优化算法不是 TWM 的全部；TWM 的关键在于治理状态表达、行动条件推演、法定规则约束、因果证据校准和可审计验证闭环。",
        ha="center",
        va="bottom",
        fontsize=6.2,
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
