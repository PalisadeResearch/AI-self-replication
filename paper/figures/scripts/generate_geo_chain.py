#!/usr/bin/env python3
"""Generate the geo-chain replication map figure.

Shows four VMs on a world map with hop connections and vulnerability labels.

Run from paper/:
    python figures/scripts/generate_geo_chain.py
"""

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import cartopy.crs as ccrs
import cartopy.feature as cfeature

plt.rcParams.update(
    {
        "font.family": "serif",
        "font.serif": ["CMU Serif", "Computer Modern Roman", "DejaVu Serif"],
        "mathtext.fontset": "cm",
        "font.size": 9,
    }
)

# VM locations (lon, lat)
vms = {
    "VM1": {"loc": (-75.7, 45.4), "label": "VM1 — Canada", "role": "Origin"},
    "VM2": {"loc": (-97.0, 37.0), "label": "VM2 — US", "vuln": "Auth bypass"},
    "VM3": {"loc": (25.0, 61.5), "label": "VM3 — Finland", "vuln": "SSTI"},
    "VM4": {"loc": (78.0, 20.0), "label": "VM4 — India", "vuln": "SQL injection"},
}

# Hops: (from, to, hop_number)
hops = [
    ("VM1", "VM2", 1),
    ("VM2", "VM3", 2),
    ("VM3", "VM4", 3),
]

# Colors
ink = "#1a1a1a"
muted = "#555555"
hop_colors = {1: "#3498db", 2: "#2ecc71", 3: "#e67e22"}
dot_color = "#d45500"
origin_color = "#333333"

proj = ccrs.Robinson()
fig, ax = plt.subplots(
    figsize=(6.5, 3.2), subplot_kw={"projection": proj}
)

# Map features — white land, light gray borders
ax.set_global()
ax.add_feature(cfeature.LAND, facecolor="#f5f5f5", edgecolor="none", zorder=0)
ax.add_feature(cfeature.OCEAN, facecolor="white", edgecolor="none", zorder=0)
ax.add_feature(cfeature.BORDERS, linewidth=0.3, edgecolor="#cccccc", zorder=1)
ax.add_feature(cfeature.COASTLINE, linewidth=0.4, edgecolor="#aaaaaa", zorder=1)
ax.spines["geo"].set_visible(False)

# Crop to relevant area (North America, Europe, South Asia)
ax.set_extent([-130, 100, 5, 72], crs=ccrs.PlateCarree())

hop_vulns = {1: "Auth bypass", 2: "SSTI", 3: "SQL injection"}

# Midpoint offsets to avoid overlaps (in degrees lon, lat)
# Fixed label positions (lon, lat) chosen to sit near each line without overlapping
hop_label_positions = {
    1: (-85, 34),   # below the VM1→VM2 line, between them
    2: (-30, 58),   # above Atlantic, along VM2→VM3 line
    3: (55, 35),    # along VM3→VM4 line, over Middle East
}

# Draw hop connections
for src, dst, hop_num in hops:
    x1, y1 = vms[src]["loc"]
    x2, y2 = vms[dst]["loc"]
    ax.plot(
        [x1, x2], [y1, y2],
        transform=ccrs.Geodetic(),
        color=hop_colors[hop_num],
        linewidth=1.8,
        linestyle="-",
        zorder=3,
        alpha=0.8,
    )
    lx, ly = hop_label_positions[hop_num]
    ax.text(
        lx, ly, f"Hop {hop_num}",
        transform=ccrs.PlateCarree(),
        fontsize=6.5, fontweight="bold",
        color=hop_colors[hop_num],
        ha="center", va="center",
        bbox=dict(boxstyle="round,pad=0.15", facecolor="white",
                  edgecolor=hop_colors[hop_num], linewidth=0.5, alpha=0.9),
        zorder=6,
    )

# Draw VM dots
for name, info in vms.items():
    lon, lat = info["loc"]
    color = origin_color if name == "VM1" else dot_color
    ax.plot(
        lon, lat,
        marker="o", markersize=7, color=color,
        markeredgecolor="white", markeredgewidth=0.8,
        transform=ccrs.PlateCarree(), zorder=5,
    )

# VM labels — just name and location, consistent style
label_offsets = {
    "VM1": (6, -8),
    "VM2": (-6, -8),
    "VM3": (6, -8),
    "VM4": (6, 6),
}

for name, info in vms.items():
    lon, lat = info["loc"]
    dx, dy = label_offsets[name]
    location = info["label"].split(" — ")[1]
    label_text = f"{name}: {location}"

    ax.annotate(
        label_text,
        xy=(lon, lat),
        xycoords=ccrs.PlateCarree()._as_mpl_transform(ax),
        xytext=(dx, dy),
        textcoords="offset points",
        fontsize=6.5,
        color=ink,
        ha="left" if dx > 0 else "right",
        va="bottom" if dy > 0 else "top",
        bbox=dict(boxstyle="round,pad=0.15", facecolor="white",
                  edgecolor="#aaaaaa", linewidth=0.4, alpha=0.9),
        zorder=7,
    )

# Legend
legend_elements = [
    mpatches.Patch(facecolor=hop_colors[1], label="Hop 1: Auth bypass"),
    mpatches.Patch(facecolor=hop_colors[2], label="Hop 2: SSTI"),
    mpatches.Patch(facecolor=hop_colors[3], label="Hop 3: SQL injection"),
]
ax.legend(
    handles=legend_elements, loc="lower left",
    fontsize=6, framealpha=0.9, edgecolor="#cccccc",
    borderpad=0.5,
)

plt.tight_layout()
plt.savefig("figures/geo_chain_map.svg", bbox_inches="tight", dpi=150)
print("Saved figures/geo_chain_map.svg")
