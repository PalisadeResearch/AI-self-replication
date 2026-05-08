#!/usr/bin/env python3
"""Generate the prior work scatter chart.

X-axis: Replication complexity (what must be replicated)
Y-axis: Hacking complexity (how access is gained)

Run from paper/:
    python figures/scripts/generate_prior_work_scatter.py
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
    "Small open model,\nsingle GPU",
    "Large open model,\nmulti-GPU",
    "Specialized private\n model, cluster",
    # "Frontier bespoke\ninfrastructure",
]
y_labels = [
    "Access granted",
    "High-school\nCTF",
    "Professional\npentesting",
    # "APT",
    # "Strategic supply\nchain attacks\n(SolarWinds)",
]

# Points on a tick sit exactly on integer coords
points = [
    (0.4, 0.55, "Black et al. (2025)", "#888888", "D", 5),
    (1.0, 0.05, "Pan et al. (2025)", "#888888", "D", 5),
    (0.05, 0.05, "Zhang et al. (2025)", "#888888", "D", 5),
    (0.05, 1.1, "This paper\n(27B, 35B)", "#d45500", "*", 14),
    (0.85, 1.1, "This paper\n(122B, API)", "#d45500", "*", 14),
]

label_offsets = {
    "Black et al. (2025)": (0.04, 0.04, "left", "bottom"),
    "Pan et al. (2025)": (0.04, 0.04, "left", "bottom"),
    "Zhang et al. (2025)": (0.04, 0.04, "left", "bottom"),
    "This paper\n(27B, 35B)": (0.04, 0.04, "left", "bottom"),
    "This paper\n(122B, API)": (0.04, 0.04, "left", "bottom"),
}

fig, ax = plt.subplots(figsize=(6, 3))

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

ax.set_xlim(xmin=0)
ax.set_ylim(ymin=0)
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
plt.savefig("figures/prior_work_scatter.svg", bbox_inches="tight")
print("Saved figures/prior_work_scatter.svg")
