"""Generate architecture diagram for the world model paper (Figure 1)."""
import sys, io
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

fig, ax = plt.subplots(1, 1, figsize=(12, 8))
ax.set_xlim(0, 12)
ax.set_ylim(0, 10)
ax.axis("off")

# Colors
FROZEN_BG = "#D6EAF8"
FROZEN_EDGE = "#2980B9"
LEARNED_BG = "#FDEBD0"
LEARNED_EDGE = "#E67E22"
INPUT_BG = "#D5F5E3"
INPUT_EDGE = "#27AE60"
OUTPUT_BG = "#F2F3F4"
OUTPUT_EDGE = "#7F8C8D"
ARROW_COLOR = "#2C3E50"
LOOP_COLOR = "#2980B9"

def draw_box(x, y, w, h, text, bg, edge, fontsize=9, bold=False):
    box = FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.15",
                         facecolor=bg, edgecolor=edge, linewidth=1.8)
    ax.add_patch(box)
    weight = "bold" if bold else "normal"
    ax.text(x + w/2, y + h/2, text, ha="center", va="center",
            fontsize=fontsize, fontweight=weight, linespacing=1.4)

def arrow(x1, y1, x2, y2, color=ARROW_COLOR, style="-", lw=1.5):
    ax.annotate("", xy=(x2, y2), xytext=(x1, y1),
                arrowprops=dict(arrowstyle="-|>", color=color,
                                lw=lw, linestyle=style,
                                connectionstyle="arc3,rad=0"))

# ── Row 1: Inputs (y=8.5) ──
draw_box(0.3, 8.3, 2.4, 1.0, "Satellite\nObservations", INPUT_BG, INPUT_EDGE, 9)
draw_box(4.8, 8.3, 2.4, 1.0, "Scenario\n$\\sigma \\in \\mathbb{R}^{16}$", INPUT_BG, INPUT_EDGE, 9)
draw_box(9.3, 8.3, 2.4, 1.0, "Terrain Context\nDEM + Slope", INPUT_BG, INPUT_EDGE, 9)

# ── Row 2: Encoder + Scenario MLP (y=6.5) ──
draw_box(0.0, 6.3, 2.9, 1.2, "AlphaEarth Encoder\n(480M params, frozen)", FROZEN_BG, FROZEN_EDGE, 9, bold=True)
draw_box(4.55, 6.3, 2.9, 1.2, "Scenario MLP\n$s_\\phi: \\mathbb{R}^{16} \\to \\mathbb{R}^{64}$", LEARNED_BG, LEARNED_EDGE, 9)

# Label: Layer 1
ax.text(0.0, 7.65, "Layer 1: Frozen", fontsize=7.5, fontstyle="italic", color="#2980B9")
# Label: Layer 2
ax.text(4.55, 7.65, "Layer 2: Learned", fontsize=7.5, fontstyle="italic", color="#E67E22")

# ── Row 3: Embedding (y=4.8) ──
draw_box(0.15, 4.8, 2.6, 0.8, "$z_t \\in \\mathbb{R}^{64 \\times H \\times W}$", OUTPUT_BG, OUTPUT_EDGE, 9)

# ── Row 4: Dynamics (y=3.2) ──
draw_box(1.5, 3.0, 9.0, 1.2, "LatentDynamicsNet  $f_\\theta$\nDilated Conv (d=1, 2, 4) + Residual  |  459K params, learned",
         LEARNED_BG, LEARNED_EDGE, 9.5, bold=True)

# ── Row 5: L2 Normalize (y=1.6) ──
draw_box(3.5, 1.5, 5.0, 0.8, "L2 Normalize:  $z / \\|z\\|_2$", LEARNED_BG, LEARNED_EDGE, 9.5)

# ── Row 6: Output + Decoder (y=0.1) ──
draw_box(2.5, 0.0, 3.0, 0.8, "$\\hat{z}_{t+1} \\in S^{63}$", OUTPUT_BG, OUTPUT_EDGE, 9.5, bold=True)
draw_box(8.0, 0.0, 2.6, 0.8, "LULC Map", OUTPUT_BG, OUTPUT_EDGE, 9.5)

# Decoder box
draw_box(6.2, 0.0, 1.4, 0.8, "Linear\nProbe", FROZEN_BG, FROZEN_EDGE, 8)
ax.text(6.9, -0.2, "(viz only)", fontsize=7, fontstyle="italic", color="#7F8C8D", ha="center")

# ── Arrows ──
# Inputs → processing
arrow(1.5, 8.3, 1.45, 7.5)   # Sat → Encoder
arrow(6.0, 8.3, 6.0, 7.5)    # Scenario → MLP
arrow(1.45, 6.3, 1.45, 5.6)  # Encoder → z_t

# z_t → Dynamics (left input)
arrow(1.45, 4.8, 3.5, 4.2)

# Scenario MLP → Dynamics (middle input)
arrow(6.0, 6.3, 6.0, 4.2)

# Terrain → Dynamics (right input)
arrow(10.5, 8.3, 10.5, 4.2)

# Dynamics → L2 Normalize
arrow(6.0, 3.0, 6.0, 2.3)

# L2 Normalize → z_{t+1}
arrow(6.0, 1.5, 4.0, 0.8)

# z_{t+1} → Linear Probe → LULC
arrow(5.5, 0.4, 6.2, 0.4)
arrow(7.6, 0.4, 8.0, 0.4)

# ── Autoregressive loop (dashed blue) ──
# From z_{t+1} left side, curve up to Dynamics left input
ax.annotate("", xy=(1.5, 3.6), xytext=(2.5, 0.4),
            arrowprops=dict(arrowstyle="-|>", color=LOOP_COLOR,
                            lw=1.8, linestyle="--",
                            connectionstyle="arc3,rad=-0.4"))
ax.text(0.3, 2.0, "autoregressive\nloop", fontsize=7.5, fontstyle="italic",
        color=LOOP_COLOR, ha="center")

# ── Concat annotation ──
ax.text(6.0, 4.35, "concat [ $z_t$ ,  $s_\\phi(\\sigma)$ ,  $c$ ]",
        fontsize=8, ha="center", va="bottom", color="#555555", fontstyle="italic")

# ── Legend ──
legend_items = [
    mpatches.Patch(facecolor=FROZEN_BG, edgecolor=FROZEN_EDGE, label="Frozen (not trained)"),
    mpatches.Patch(facecolor=LEARNED_BG, edgecolor=LEARNED_EDGE, label="Learned (trained)"),
    mpatches.Patch(facecolor=INPUT_BG, edgecolor=INPUT_EDGE, label="Input data"),
    mpatches.Patch(facecolor=OUTPUT_BG, edgecolor=OUTPUT_EDGE, label="Intermediate / Output"),
]
ax.legend(handles=legend_items, loc="upper right", fontsize=8, framealpha=0.9)

plt.tight_layout()
out_path = "D:/adk/docs/fig_architecture.png"
fig.savefig(out_path, dpi=200, bbox_inches="tight", facecolor="white")
plt.close()
print(f"Saved: {out_path}")
