#!/usr/bin/env python3
"""Generate the capability-over-time chart.

X-axis: model release date
Y-axis: replication success rate (model_responding / non_ref)
Lines connecting model families (Opus, GPT, 35B).
One color per family for dots, text, lines, and CI.

Run from paper/:
    python figures/scripts/generate_cap_over_time.py
"""

import math
from datetime import datetime
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from generate_tables import load_all_stats

OUT = Path(__file__).resolve().parent.parent


def _wilson(k, n, z=1.96):
    if n == 0:
        return 0, 0, 0
    p = k / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n) / denom
    return p, max(0, center - margin), min(1, center + margin)


plt.rcParams.update(
    {
        "font.family": "serif",
        "font.serif": ["CMU Serif", "Computer Modern Roman", "DejaVu Serif"],
        "mathtext.fontset": "cm",
        "font.size": 9,
    }
)

# One dark color per family
opus_c = "#b35900"
gpt_c = "#1a4e7a"
qwen_c = "#4a2078"

# Map each model key to its family color
family_color = {
    "opus4": opus_c, "opus45": opus_c, "opus46": opus_c,
    "gpt5": gpt_c, "gpt51": gpt_c, "gpt54": gpt_c,
    "qwen122b_hop1": qwen_c, "qwen35_35b": qwen_c,
    "qwen36_35b": qwen_c, "qwen36_27b": qwen_c,
}

# Qwen3.5-122B and 35B released same day — offset slightly for visibility
models = [
    ("opus4", "Opus 4", datetime(2025, 5, 22)),
    ("opus45", "Opus 4.5", datetime(2025, 11, 14)),
    ("opus46", "Opus 4.6", datetime(2026, 2, 24)),
    ("gpt5", "GPT-5", datetime(2025, 8, 6)),
    ("gpt51", "GPT-5.1", datetime(2025, 11, 19)),
    ("gpt54", "GPT-5.4", datetime(2026, 3, 12)),
    ("qwen122b_hop1", "Qwen3.5-122B", datetime(2026, 2, 20)),
    ("qwen35_35b", "Qwen3.5-35B", datetime(2026, 2, 28)),
    ("qwen36_35b", "Qwen3.6-35B", datetime(2026, 4, 16)),
    ("qwen36_27b", "Qwen3.6-27B", datetime(2026, 4, 22)),
]

families = {
    "Opus": ["opus4", "opus45", "opus46"],
    "GPT": ["gpt5", "gpt51", "gpt54"],
    "35B": ["qwen35_35b", "qwen36_35b"],
}
family_line_color = {"Opus": opus_c, "GPT": gpt_c, "35B": qwen_c}


def main():
    all_stats = load_all_stats()

    fig, ax = plt.subplots(figsize=(6.5, 3.5))

    model_data = {}
    for key, label, date in models:
        s = all_stats[key]
        n = s["non_ref"]
        k = s["milestones"]["model_responding"]["count"]
        p, lo, hi = _wilson(k, n)
        model_data[key] = {
            "label": label,
            "date": date,
            "rate": p * 100,
            "lo": lo * 100,
            "hi": hi * 100,
            "n": n,
            "k": k,
        }

    # Family lines — semi-transparent
    for fname, members in families.items():
        dates = [model_data[k]["date"] for k in members]
        rates = [model_data[k]["rate"] for k in members]
        ax.plot(dates, rates, color=family_line_color[fname],
                linewidth=1.2, alpha=0.2, zorder=2)

    # Dots and CI error bars
    for key, label, date in models:
        d = model_data[key]
        c = family_color[key]
        yerr_lo = max(0, d["rate"] - d["lo"])
        yerr_hi = max(0, d["hi"] - d["rate"])
        # CI — more transparent, thin T-shape
        ax.errorbar(
            d["date"], d["rate"],
            yerr=[[yerr_lo], [yerr_hi]],
            fmt="none", color=c,
            capsize=2, elinewidth=0.8, capthick=0.7,
            alpha=0.15, zorder=4,
        )
        # Dot — family color
        ax.plot(
            d["date"], d["rate"],
            "o", color=c, markersize=5,
            markeredgecolor="white", markeredgewidth=0.5,
            zorder=5,
        )

    # Labels — family-colored text
    label_config = {
        "opus4": (6, 4, "left", "bottom"),
        "opus45": (6, 4, "left", "bottom"),
        "opus46": (6, -4, "left", "top"),
        "gpt5": (6, 4, "left", "bottom"),
        "gpt51": (6, 4, "left", "bottom"),
        "gpt54": (-6, 4, "right", "bottom"),
        "qwen122b_hop1": (-6, -8, "right", "top"),
        "qwen35_35b": (6, 4, "left", "bottom"),
        "qwen36_35b": (6, 4, "left", "bottom"),
        "qwen36_27b": (6, -8, "left", "top"),
    }

    for key, label, date in models:
        d = model_data[key]
        c = family_color[key]
        dx, dy, ha, va = label_config.get(key, (6, 0, "left", "bottom"))
        pct = f"{d['rate']:.0f}%"
        ax.annotate(
            f"{label} ({pct})",
            xy=(d["date"], d["rate"]),
            xytext=(dx, dy),
            textcoords="offset points",
            fontsize=6.5,
            color=c,
            fontweight="bold",
            ha=ha,
            va=va,
            zorder=6,
        )

    ax.set_ylabel("Replication success rate")
    ax.set_ylim(0, 100)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"{x:.0f}%"))
    ax.set_xlim(datetime(2025, 4, 15), datetime(2026, 6, 10))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
    fig.autofmt_xdate(rotation=30, ha="right")

    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.yaxis.grid(True, alpha=0.15, linestyle="--")
    ax.set_axisbelow(True)

    plt.tight_layout()
    plt.savefig(OUT / "cap_over_time.svg", bbox_inches="tight")
    plt.close()
    print("Saved figures/cap_over_time.svg")


if __name__ == "__main__":
    main()
