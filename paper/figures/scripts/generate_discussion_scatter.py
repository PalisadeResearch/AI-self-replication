#!/usr/bin/env python3
"""Generate the discussion scatter chart.

X-axis: Replication complexity (what must be replicated)
Y-axis: Hacking complexity (how access is gained)

Run from paper/:
    python figures/scripts/generate_discussion_scatter.py
"""

import matplotlib.pyplot as plt

plt.rcParams.update(
    {
        "font.family": "serif",
        "font.serif": ["CMU Serif", "Computer Modern Roman", "DejaVu Serif"],
        "mathtext.fontset": "cm",
        "font.size": 9,
    }
)

x_labels = [
    "No replication",
    "Small open model,\nsingle GPU",
    "Large open model,\nmulti-GPU",
    "Specialized private\n model, cluster",
    "Frontier bespoke\ninfrastructure",
]
y_labels = [
    "Access granted",
    "High-school\nCTF",
    "Professional\npentesting",
    "APT",
    "Strategic supply\nchain attacks\n(SolarWinds)",
]

# Points on a tick sit exactly on integer coords
points = [
    # Original dots — unchanged placements
    (1.4, 0.55, "Black et al. (2025)", "#888888", "D", 5),
    (2.0, 0.05, "Pan et al. (2025)", "#888888", "D", 5),
    (1.0, 0.05, "Zhang et al. (2025)", "#888888", "D", 5),
    (1.0, 1.15, "This paper\n(27B, 35B)", "#d45500", "*", 14),
    (1.85, 1.15, "This paper\n(122B, API)", "#d45500", "*", 14),
    # New dots
    (0.05, 1.0, "CyBench (2025)", "#888888", "D", 5),
    (0.05, 1.5, "Fang et al. (2024)", "#888888", "D", 5),
    (0.05, 2.0, "Zhu et al. (2024)", "#888888", "D", 5),
    (0.05, 2.3, "Mythos (2026)", "#888888", "D", 5),
]

label_offsets = {
    # Original label offsets — unchanged
    "Black et al. (2025)": (0.04, 0.04, "left", "bottom"),
    "Pan et al. (2025)": (0.04, 0.04, "left", "bottom"),
    "Zhang et al. (2025)": (0.0, 0.22, "center", "top"),
    "This paper\n(27B, 35B)": (-0.08, 0.18, "left", "bottom"),
    "This paper\n(122B, API)": (0.0, 0.18, "center", "bottom"),
    # New label offsets
    "CyBench (2025)": (0.12, 0.0, "left", "center"),
    "Fang et al. (2024)": (0.12, 0.0, "left", "center"),
    "Zhu et al. (2024)": (0.12, 0.0, "left", "center"),
    "Mythos (2026)": (0.12, 0.0, "left", "center"),
}

fig, ax = plt.subplots(figsize=(6.5, 3.2))

# Zero-baseline lines
ax.axhline(y=0, color="#aaaaaa", linewidth=0.8, linestyle=":", alpha=0.7, zorder=1)
ax.axvline(x=0, color="#aaaaaa", linewidth=0.8, linestyle=":", alpha=0.7, zorder=1)

for x, y, label, color, marker, ms in points:
    ax.plot(
        x,
        y,
        marker=marker,
        color=color,
        markersize=ms,
        markeredgecolor="black",
        markeredgewidth=0.5,
        zorder=5,
    )
    dx, dy, ha, va = label_offsets[label]
    fontweight = "bold" if "This paper" in label else "normal"
    fontsize = 8 if "This paper" in label else 7
    ax.annotate(
        label,
        (x, y),
        xytext=(x + dx, y + dy),
        ha=ha,
        va=va,
        fontsize=fontsize,
        fontweight=fontweight,
        color=color if "This paper" in label else "#444444",
        zorder=6,
    )

# Dashed arrow to "future" -- pale orange
ax.annotate(
    "",
    xy=(3.3, 2.5),
    xytext=(1.85, 1.15),
    arrowprops=dict(
        arrowstyle="-|>",
        color="#e0a070",
        lw=1.5,
        linestyle="dashed",
        connectionstyle="arc3,rad=0.15",
    ),
    zorder=3,
)
ax.text(
    3.4,
    2.55,
    "Future\ncapability?",
    fontsize=7,
    color="#c07030",
    fontstyle="italic",
    ha="left",
    va="bottom",
)

ax.set_xlim(0, len(x_labels) - 1)
ax.set_ylim(0, len(y_labels) - 1)
ax.set_xticks(range(len(x_labels)))
ax.set_xticklabels(x_labels, fontsize=7)
ax.set_yticks(range(len(y_labels)))
ax.set_yticklabels(y_labels, fontsize=7)

ax.set_xlabel("Replication complexity", labelpad=8)
ax.set_ylabel("Hacking complexity", labelpad=8)

ax.spines["top"].set_visible(False)
ax.spines["right"].set_visible(False)
ax.grid(True, alpha=0.15, linestyle="--")

plt.tight_layout()
plt.savefig("figures/discussion_scatter.svg", bbox_inches="tight")
print("Saved figures/discussion_scatter.svg")
