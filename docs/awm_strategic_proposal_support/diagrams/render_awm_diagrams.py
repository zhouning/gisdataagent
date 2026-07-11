from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch


OUT = Path(__file__).resolve().parent


def setup() -> None:
    plt.rcParams["font.sans-serif"] = [
        "PingFang SC",
        "Hiragino Sans GB",
        "Arial Unicode MS",
        "DejaVu Sans",
    ]
    plt.rcParams["axes.unicode_minus"] = False


def box(ax, x, y, w, h, text, *, fc="#F8FAFC", ec="#64748B", size=10.5):
    patch = FancyBboxPatch(
        (x, y),
        w,
        h,
        boxstyle="round,pad=0.018,rounding_size=0.025",
        linewidth=1.5,
        edgecolor=ec,
        facecolor=fc,
    )
    ax.add_patch(patch)
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=size)
    return patch


def arrow(ax, x1, y1, x2, y2, *, color="#64748B", dashed=False, label=None):
    patch = FancyArrowPatch(
        (x1, y1),
        (x2, y2),
        arrowstyle="-|>",
        mutation_scale=14,
        linewidth=1.4,
        linestyle="--" if dashed else "-",
        color=color,
        shrinkA=2,
        shrinkB=2,
    )
    ax.add_patch(patch)
    if label:
        ax.text((x1 + x2) / 2, (y1 + y2) / 2 + 0.025, label, ha="center", va="bottom", fontsize=8.5, color=color)


def render_data_state_foundation() -> None:
    fig, ax = plt.subplots(figsize=(16, 8.5), dpi=180)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    ax.set_title("AWM 数据与状态基础（目标架构）", fontsize=20, fontweight="bold", pad=16)

    inputs = [
        (0.03, 0.76, "空间对象\n田块·农场·渠系·水源·行政单元"),
        (0.03, 0.59, "连续观测\n遥感·气象·墒情·流量·作物观测"),
        (0.03, 0.42, "经营与干预记录\n播种·灌溉·施肥·防治·收获"),
        (0.03, 0.25, "治理与约束\n水权·配额·农艺规则·预算·安全边界"),
        (0.03, 0.08, "结果与复核\n产量·用水·成本·生态影响·专家记录"),
    ]
    for x, y, label in inputs:
        box(ax, x, y, 0.22, 0.115, label, size=9.6)

    box(ax, 0.32, 0.40, 0.17, 0.20, "Agricultural Data Manifest\n\n来源·时空范围·许可\n质量·证据等级", fc="#DBEAFE", ec="#2563EB")
    box(ax, 0.55, 0.40, 0.17, 0.20, "语义与数据契约\n\n对象角色·字段绑定\n单位·CRS·时间对齐", fc="#DBEAFE", ec="#2563EB")
    box(ax, 0.78, 0.68, 0.18, 0.15, "Agricultural Renderer\n观测对齐·质量标记·空间聚合", fc="#FFEDD5", ec="#EA580C")
    box(ax, 0.78, 0.43, 0.18, 0.15, "Belief-State Estimator\n推断根区水分·生物量·胁迫", fc="#FFEDD5", ec="#EA580C")
    box(ax, 0.78, 0.18, 0.18, 0.15, "分层农业状态图\n田块—农场—渠系—灌区/县域", fc="#FFEDD5", ec="#EA580C")
    box(ax, 0.53, 0.08, 0.21, 0.16, "证据与 Claim Boundary\nobserved / simulated / learned / causal", fc="#FEE2E2", ec="#DC2626")

    for _, y, _ in inputs:
        arrow(ax, 0.25, y + 0.057, 0.32, 0.50)
    arrow(ax, 0.49, 0.50, 0.55, 0.50)
    arrow(ax, 0.72, 0.50, 0.78, 0.755)
    arrow(ax, 0.87, 0.68, 0.87, 0.58)
    arrow(ax, 0.87, 0.43, 0.87, 0.33)
    arrow(ax, 0.405, 0.40, 0.57, 0.24, dashed=True)
    arrow(ax, 0.78, 0.255, 0.74, 0.16, dashed=True)

    ax.text(0.14, 0.94, "农业多源输入", ha="center", va="center", fontsize=13, fontweight="bold", color="#334155")
    ax.text(0.50, 0.94, "可复用的数据治理与语义基础", ha="center", va="center", fontsize=13, fontweight="bold", color="#2563EB")
    ax.text(0.86, 0.94, "AWM 待建设核心", ha="center", va="center", fontsize=13, fontweight="bold", color="#EA580C")
    fig.tight_layout()
    fig.savefig(OUT / "awm_data_state_foundation.png", bbox_inches="tight", facecolor="white")
    plt.close(fig)


def render_target_architecture() -> None:
    fig, ax = plt.subplots(figsize=(17, 9.5), dpi=180)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    ax.set_title("AWM-CropWater 总体技术架构（目标架构，尚未形成实验验证）", fontsize=19, fontweight="bold", pad=16)

    box(ax, 0.025, 0.66, 0.15, 0.14, "Canonical Agricultural\nObservation\n多源观测与质量 sidecar", fc="#DBEAFE", ec="#2563EB", size=9.5)
    box(ax, 0.21, 0.66, 0.16, 0.14, "Belief State + Spatial Graph\n水—土—作物—经营—治理状态", fc="#FFEDD5", ec="#EA580C", size=9.5)

    ax.add_patch(FancyBboxPatch((0.40, 0.46), 0.25, 0.42, boxstyle="round,pad=0.02", linewidth=1.8, edgecolor="#EA580C", facecolor="#FFF7ED"))
    ax.text(0.525, 0.845, "Hybrid Action-Conditioned Simulator", ha="center", va="center", fontsize=12, fontweight="bold", color="#C2410C")
    box(ax, 0.425, 0.70, 0.095, 0.10, "过程模型锚定\n水量平衡·作物生长\n渠系传输", size=8.3)
    box(ax, 0.535, 0.70, 0.095, 0.10, "学习残差与图传播\n区域偏差·空间外溢\n状态更新", size=8.3)
    box(ax, 0.425, 0.55, 0.095, 0.10, "不确定性情景\n天气·参数\n观测缺失", size=8.3)
    box(ax, 0.535, 0.55, 0.095, 0.10, "多时间尺度转移\n小时·日·周\n季节", fc="#FFEDD5", ec="#EA580C", size=8.3)
    arrow(ax, 0.472, 0.70, 0.575, 0.65)
    arrow(ax, 0.582, 0.70, 0.585, 0.65)
    arrow(ax, 0.472, 0.60, 0.535, 0.60)

    box(ax, 0.405, 0.22, 0.23, 0.13, "Action Catalog + Hard Mask\n供水对象·时机·水量·重分配\n水权·容量·农艺·安全约束", fc="#FEF3C7", ec="#D97706", size=9.3)
    box(ax, 0.69, 0.66, 0.13, 0.14, "Robust MPC / Planner\n消费 rollout\n不自行生成效果", fc="#DCFCE7", ec="#16A34A", size=9.3)
    box(ax, 0.85, 0.66, 0.13, 0.14, "方案包与 Trace\n产量·用水·公平\n成本·生态风险", fc="#DCFCE7", ec="#16A34A", size=9.3)
    box(ax, 0.69, 0.40, 0.13, 0.14, "Evidence Gate\n诊断·探索情景\n历史回放·受控试点", fc="#FEE2E2", ec="#DC2626", size=9.3)
    box(ax, 0.85, 0.40, 0.13, 0.14, "业务专家与农户复核\n采纳·驳回·补证\n执行记录", fc="#EDE9FE", ec="#7C3AED", size=9.3)
    box(ax, 0.77, 0.14, 0.13, 0.14, "Failure Memory\n极端天气·异常供水\n误放·误阻·跨区迁移", fc="#EDE9FE", ec="#7C3AED", size=9.3)

    arrow(ax, 0.175, 0.73, 0.21, 0.73)
    arrow(ax, 0.37, 0.73, 0.40, 0.73)
    arrow(ax, 0.52, 0.35, 0.52, 0.46)
    arrow(ax, 0.65, 0.73, 0.69, 0.73, label="rollout trace")
    arrow(ax, 0.635, 0.285, 0.72, 0.66, label="候选动作")
    arrow(ax, 0.82, 0.73, 0.85, 0.73)
    arrow(ax, 0.915, 0.66, 0.915, 0.54)
    arrow(ax, 0.85, 0.47, 0.82, 0.47)
    arrow(ax, 0.88, 0.40, 0.835, 0.28)
    arrow(ax, 0.77, 0.21, 0.29, 0.66, dashed=True, label="replay")
    arrow(ax, 0.77, 0.18, 0.635, 0.27, dashed=True, label="约束修订")
    arrow(ax, 0.69, 0.47, 0.65, 0.60, dashed=True, label="降级/阻断")

    ax.text(0.51, 0.04, "蓝色：观测输入与可复用底座　橙色：AWM 待建设核心　绿色：规划输出　红色：证据门控　紫色：人工治理闭环", ha="center", va="center", fontsize=10, color="#475569")
    fig.tight_layout()
    fig.savefig(OUT / "awm_target_architecture.png", bbox_inches="tight", facecolor="white")
    plt.close(fig)


if __name__ == "__main__":
    setup()
    render_data_state_foundation()
    render_target_architecture()
