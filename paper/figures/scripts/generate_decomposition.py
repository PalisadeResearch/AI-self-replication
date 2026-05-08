#!/usr/bin/env python3
"""Generate the self-replication decomposition figure.

Self-Replication = Propensity* (out of scope) + Capability
Capability → Hacking ✓, Copying ✓
Copying: Prompts ✓, Weights ✓, Harness ✓

Run from paper/:
    python figures/scripts/generate_decomposition.py
"""

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

plt.rcParams.update(
    {
        "font.family": "serif",
        "font.serif": ["CMU Serif", "Computer Modern Roman", "DejaVu Serif"],
        "mathtext.fontset": "cm",
        "font.size": 9,
    }
)

fig, ax = plt.subplots(figsize=(6.5, 2.0))
ax.set_xlim(0, 10)
ax.set_ylim(0.2, 3.0)
ax.set_aspect("equal")
ax.axis("off")

cap_fill = "#e9edf4"
out_fill = "#d6d6d6"
ink = "#1a1a1a"
muted = "#555555"
border_color = "#3a3a3a"
tick_color = "#1a1a1a"


def draw_box(cx, cy, w, h, label, bg="white", border_style="-", fontsize=9):
    ls = "--" if border_style == "dashed" else "-"
    rect = mpatches.FancyBboxPatch(
        (cx - w / 2, cy - h / 2), w, h,
        boxstyle="round,pad=0.05", facecolor=bg,
        edgecolor=border_color, linewidth=0.8, linestyle=ls,
    )
    ax.add_patch(rect)
    ax.text(cx, cy, label, ha="center", va="center", fontsize=fontsize,
            fontweight="bold", color=ink if bg != out_fill else muted)


def tick(x, y):
    ax.text(x, y, "✓", ha="left", va="center", fontsize=7,
            fontweight="bold", color=tick_color, fontfamily="DejaVu Sans")


def draw_arrow(x1, y1, x2, y2):
    ax.annotate("", xy=(x2, y2), xytext=(x1, y1),
                arrowprops=dict(arrowstyle="-|>", color=muted, lw=0.9))


def draw_subtitle(cx, cy, text):
    ax.text(cx, cy, text, ha="center", va="top", fontsize=5.8,
            color=muted, style="italic")


# Horizontal offset to center the figure
dx = 0.65

# Row 1: Self-Replication = Propensity* + Capability
row_y = 1.95
draw_box(0.9 + dx, row_y, 1.5, 0.65, "Self-\nReplication", bg="white", fontsize=8)
ax.text(1.9 + dx, row_y, "=", ha="center", va="center", fontsize=12, color=muted)
draw_box(2.85 + dx, row_y, 1.4, 0.65, "Propensity*", bg=out_fill, border_style="dashed", fontsize=8)
draw_subtitle(2.85 + dx, row_y - 0.43, "Does AI want to replicate?")
ax.text(3.8 + dx, row_y, "+", ha="center", va="center", fontsize=12, color=muted)
draw_box(4.75 + dx, row_y, 1.4, 0.65, "Capability", bg=cap_fill, fontsize=8)
draw_subtitle(4.75 + dx, row_y - 0.43, "Can it replicate if it wants?")

# Footnote
ax.text(0.15 + dx, 0.30, "* Out of scope of this paper",
        ha="left", va="bottom", fontsize=6, color=muted, style="italic")

# Hacking and Copying: symmetric above/below capability
gap = 0.52
hack_cx = 7.0 + dx
hack_y = row_y + gap
copy_y = row_y - gap

draw_arrow(5.6 + dx, row_y + 0.18, 6.3 + dx, hack_y)
draw_arrow(5.6 + dx, row_y - 0.18, 6.3 + dx, copy_y)

draw_box(hack_cx, hack_y, 1.2, 0.50, "Hacking", bg=cap_fill, fontsize=8)
tick(hack_cx + 0.42, hack_y)
draw_subtitle(hack_cx, hack_y - 0.37, "Can it acquire compute?")

draw_box(hack_cx, copy_y, 1.2, 0.50, "Copying", bg=cap_fill, fontsize=8)
tick(hack_cx + 0.42, copy_y)
draw_subtitle(hack_cx, copy_y - 0.37, "Can it copy itself?")

# Prompts, Weights, Harness — listed next to Copying box, no arrow
list_x = 7.85 + dx
spacing = 0.26
list_top = copy_y + spacing

items = ["Prompts", "Weights", "Harness"]
for i, item in enumerate(items):
    iy = list_top - i * spacing
    ax.text(list_x, iy, item, ha="left", va="center", fontsize=7.5, color=ink)
    tick(list_x + 0.73, iy)

plt.tight_layout()
plt.savefig("figures/decomposition_self_replication.svg", bbox_inches="tight")
print("Saved figures/decomposition_self_replication.svg")
