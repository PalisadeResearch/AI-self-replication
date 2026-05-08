#!/usr/bin/env python3
"""Generate paper figures. Run from repo root: python3 paper/figures/scripts/generate_plots.py"""

import math
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from generate_tables import MILESTONES, load_all_stats
from matplotlib.ticker import PercentFormatter

OUT = Path(__file__).resolve().parent.parent


def _wilson(k, n, z=1.96):
    """Wilson score 95% CI for binomial proportion."""
    if n == 0:
        return 0, 0, 0
    p = k / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n) / denom
    return p, max(0, center - margin), min(1, center + margin)


def model_comparison(all_stats=None):
    if all_stats is None:
        all_stats = load_all_stats()
    qwen35_large = "#8e63b8"
    qwen35_small = "#c2a6de"
    qwen36_large = "#4f2f7f"
    qwen36_small = "#7353a3"
    gpt5 = "#8dbce2"
    gpt51 = "#4f95c8"
    gpt54 = "#1f5f9a"
    opus4 = "#f6b45b"
    opus45 = "#f28e2b"
    opus46 = "#c65a11"
    plot_models = [
        ("qwen122b_hop1", "Qwen3.5-122B", qwen35_large),
        ("qwen35_35b", "Qwen3.5-35B-A3B", qwen35_small),
        ("qwen36_35b", "Qwen3.6-35B-A3B", qwen36_large),
        ("qwen36_27b", "Qwen3.6-27B", qwen36_small),
        ("gpt5", "GPT-5", gpt5),
        ("gpt51", "GPT-5.1", gpt51),
        ("gpt54", "GPT-5.4", gpt54),
        ("opus4", "Opus 4", opus4),
        ("opus45", "Opus 4.5", opus45),
        ("opus46", "Opus 4.6", opus46),
    ]
    data = []
    for key, label, color in plot_models:
        s = all_stats[key]
        data.append(
            (
                label,
                color,
                s["non_ref"],
                s["milestones"]["got_root"]["count"],
                s["milestones"]["model_responding"]["count"],
            )
        )

    fig, ax = plt.subplots(figsize=(12, 5.5))

    group_centers = np.array([0, 1])
    n_models = len(data)
    group_width = 0.84
    width = group_width / n_models
    offsets = (np.arange(n_models) - (n_models - 1) / 2) * width

    hack_rates, hack_elo, hack_ehi = [], [], []
    repl_rates, repl_elo, repl_ehi = [], [], []
    colors = []
    legend_labels = []

    for label, color, n, hk, rk in data:
        hp, hlo, hhi = _wilson(hk, n)
        rp, rlo, rhi = _wilson(rk, n)
        hack_rates.append(hp * 100)
        hack_elo.append(max(0, hp * 100 - hlo * 100))
        hack_ehi.append(max(0, hhi * 100 - hp * 100))
        repl_rates.append(rp * 100)
        repl_elo.append(max(0, rp * 100 - rlo * 100))
        repl_ehi.append(max(0, rhi * 100 - rp * 100))
        colors.append(color)
        legend_labels.append(f"{label.replace(chr(10), ' ')} (n={n})")

    bars_h = ax.bar(
        group_centers[0] + offsets,
        hack_rates,
        width * 0.92,
        yerr=[hack_elo, hack_ehi],
        capsize=4,
        color=colors,
        alpha=0.9,
        edgecolor="white",
        linewidth=0.5,
        error_kw={"elinewidth": 1.2, "capthick": 1.2, "alpha": 0.2},
    )
    bars_r = ax.bar(
        group_centers[1] + offsets,
        repl_rates,
        width * 0.92,
        yerr=[repl_elo, repl_ehi],
        capsize=4,
        color=colors,
        alpha=0.9,
        edgecolor="white",
        linewidth=0.5,
        error_kw={"elinewidth": 1.2, "capthick": 1.2, "alpha": 0.2},
    )

    for bar, val in zip(bars_h, hack_rates):
        ax.text(
            bar.get_x() + bar.get_width() / 2.0,
            bar.get_height() + 0.5,
            f"{val:.0f}%",
            ha="center",
            va="bottom",
            fontsize=7.5,
        )
    for bar, val in zip(bars_r, repl_rates):
        ax.text(
            bar.get_x() + bar.get_width() / 2.0,
            bar.get_height() + 0.5,
            f"{val:.0f}%",
            ha="center",
            va="bottom",
            fontsize=7.5,
        )

    ax.set_ylabel("Success rate", fontsize=11)
    ax.set_xticks(group_centers)
    ax.set_xticklabels(
        ["Hacking\n(got root access)", "Replication\n(model serving on target)"],
        fontsize=10,
    )
    ax.yaxis.set_major_formatter(PercentFormatter(xmax=100))
    from matplotlib.patches import Patch

    handles = [
        Patch(facecolor=color, edgecolor="white", label=label)
        for color, label in zip(colors, legend_labels)
    ]
    ax.legend(
        handles=handles,
        loc="lower center",
        bbox_to_anchor=(0.5, -0.34),
        ncol=5,
        frameon=False,
    )
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.yaxis.grid(True, alpha=0.2)
    ax.axvline(0.5, color="#999", linestyle="--", alpha=0.35, zorder=1)
    ax.set_axisbelow(True)

    plt.tight_layout()
    plt.savefig(OUT / "model_comparison.svg", bbox_inches="tight")
    plt.close()
    print("  model_comparison.svg")


def gen_comparison(all_stats=None):
    """Sankey-style funnel for Hop-1/2/3 chain replication (Qwen3.5-122B)."""
    if all_stats is None:
        all_stats = load_all_stats()

    milestones = [
        "Discovered\nwebapp",
        "Got\ncredentials",
        "SSH into\ntarget",
        "Got\nroot",
        "Found\nmodel files",
        "Obtained\nweights",
        "Started\nserving",
        "Model\nresponding",
    ]

    hop_colors = ["#3498db", "#2ecc71", "#e67e22"]
    hops_data = []
    for key, color in [
        ("qwen122b_hop1", hop_colors[0]),
        ("qwen122b_hop2", hop_colors[1]),
        ("qwen122b_hop3", hop_colors[2]),
    ]:
        s = all_stats[key]
        n = s["non_ref"]
        rates = [round(s["milestones"][mk]["rate_excl_ref"]) for _, mk, _ in MILESTONES]
        hops_data.append((f"Hop-{len(hops_data) + 1} (n={n})", rates, color))

    fig, axes = plt.subplots(3, 1, figsize=(12, 6), sharex=True)

    for ax, (label, rates, color) in zip(axes, hops_data):
        n_milestones = len(milestones)
        x = np.arange(n_milestones)
        max_h = 1.0

        for i in range(n_milestones):
            h = rates[i] / 100 * max_h
            rect = plt.Rectangle(
                (i - 0.35, -h / 2),
                0.7,
                h,
                facecolor=color,
                alpha=0.85,
                edgecolor="white",
                linewidth=1.5,
            )
            ax.add_patch(rect)
            ax.text(
                i,
                h / 2 + 0.06,
                f"{rates[i]}%",
                ha="center",
                va="bottom",
                fontsize=9,
                fontweight="bold",
                color=color,
            )

            if i < n_milestones - 1:
                h_next = rates[i + 1] / 100 * max_h
                verts_x = [i + 0.35, i + 0.65, i + 0.65, i + 0.35]
                verts_y = [h / 2, h_next / 2, -h_next / 2, -h / 2]
                ax.fill(verts_x, verts_y, color=color, alpha=0.25)

        ax.set_xlim(-0.6, n_milestones - 0.4)
        ax.set_ylim(-0.65, 0.75)
        ax.set_yticks([])
        ax.set_title(
            label, loc="left", fontsize=10, fontweight="bold", color=color, pad=4
        )
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.spines["left"].set_visible(False)
        ax.spines["bottom"].set_visible(False)

        if ax == axes[0]:
            ax.axvline(x=3.5, color="#999", linestyle="--", alpha=0.4, ymin=0, ymax=1)
            ax.text(
                1.5,
                0.68,
                "Exploit",
                ha="center",
                color="#777",
                fontweight="bold",
            )
            ax.text(
                5.5,
                0.68,
                "Replication",
                ha="center",
                color="#777",
                fontweight="bold",
            )
        else:
            ax.axvline(x=3.5, color="#999", linestyle="--", alpha=0.4, ymin=0, ymax=1)

    axes[-1].set_xticks(x)
    axes[-1].set_xticklabels(milestones)
    axes[-1].tick_params(axis="x", length=0)

    plt.tight_layout()
    plt.savefig(OUT / "gen_comparison.svg", bbox_inches="tight")
    plt.close()
    print("  gen_comparison.svg")


if __name__ == "__main__":
    print("Generating paper figures...")
    stats = load_all_stats()
    model_comparison(stats)
    gen_comparison(stats)
    print("Done.")
