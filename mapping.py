"""Map and chart generation."""

import math
from datetime import datetime

import folium
from folium.plugins import HeatMap
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from config import (MUSHROOM_TYPES, RATINGS, ALDER_CREEK, ALGO_VERSION,
                    DIAMOND_THRESHOLD, RENDER_THRESHOLD)


def rating(score):
    for threshold, label, color in RATINGS:
        if score >= threshold:
            return label, color
    return "SKIP", "red"


def build_map(results_by_type, fires, center=None):
    """Build interactive map with per-type layers, heatmap, and fire perimeters."""
    c = center or ALDER_CREEK
    m = folium.Map(location=[c[0], c[1]], zoom_start=10, tiles=None)
    folium.TileLayer(
        tiles="https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png",
        attr='&copy; <a href="https://carto.com/">CARTO</a>',
        name="CARTO Voyager",
    ).add_to(m)
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}",
        attr="Esri",
        name="Esri Topo",
    ).add_to(m)

    for mtype, results in results_by_type.items():
        if not results:
            continue
        mt = MUSHROOM_TYPES[mtype]
        color = mt["color"]

        # Heatmap — scatter points across burn acreage
        heat_data = []
        for r in results:
            if r["result"]["total"] >= 30:
                acres = r.get("fire", {}).get("acres", 1) or 1
                lat, lon = r["zone"]["lat"], r["zone"]["lon"]
                weight = r["result"]["total"] / 100.0

                burn_radius_m = math.sqrt(acres * 4047 / math.pi)
                burn_radius_deg = burn_radius_m / 111000
                intensity = weight * 3

                heat_data.append([lat, lon, intensity])
                heat_data.append([lat, lon, intensity])

                if acres >= 2:
                    spread = burn_radius_deg * 0.5
                    n_ring = max(6, min(int(acres / 2), 16))
                    for i in range(n_ring):
                        angle = 2 * math.pi * i / n_ring
                        heat_data.append([
                            lat + spread * math.sin(angle),
                            lon + spread * math.cos(angle),
                            intensity * 0.8,
                        ])
                    if acres >= 15:
                        spread2 = burn_radius_deg * 0.85
                        for i in range(n_ring):
                            angle = 2 * math.pi * (i + 0.5) / n_ring
                            heat_data.append([
                                lat + spread2 * math.sin(angle),
                                lon + spread2 * math.cos(angle),
                                intensity * 0.6,
                            ])

        if heat_data:
            heat_group = folium.FeatureGroup(name=f"{mt['label']} Heatmap", show=True)
            HeatMap(
                heat_data, radius=22, blur=30, max_zoom=16, min_opacity=0.5,
                gradient={0.15: "#0000ff", 0.3: "#00ffff", 0.45: "#00ff00",
                          0.6: "#ffff00", 0.75: "#ff8800", 0.9: "#ff0000", 1.0: "#cc0000"},
            ).add_to(heat_group)
            heat_group.add_to(m)

        # Scored burn markers:
        #   80+ EXCELLENT -> purple diamond
        #   70-79 GOOD    -> green diamond
        #   50-69 FAIR    -> small orange dot
        #   <50           -> not rendered
        group = folium.FeatureGroup(name=f"{mt['label']} Sites", show=(mtype == "morel"))
        for r in sorted(results, key=lambda x: x["result"]["total"], reverse=True):
            z, res = r["zone"], r["result"]
            total = res["total"]
            label, rating_color = rating(total)

            if total < RENDER_THRESHOLD or rating_color is None:
                continue

            d = res["details"]
            acres = r.get("fire", {}).get("acres", 1) or 1
            s = res["scores"]
            score_bar = " | ".join(f"{k}: {v}/{mt['weights'].get(k, 5)}" for k, v in s.items())
            popup_lines = [f"<b>{z['name']}</b>",
                           f"<b>{mt['label']}: {total}/100 [{label}]</b>",
                           f"<small>{score_bar}</small>", ""]
            popup_lines += [f"{k}: {v}" for k, v in d.items() if isinstance(v, str)]
            popup = "<br>".join(popup_lines)

            if total >= DIAMOND_THRESHOLD:
                size = 22 + total // 10
                folium.Marker(
                    location=[z["lat"], z["lon"]],
                    popup=folium.Popup(popup, max_width=320),
                    tooltip=f"{z['name']}: {total} [{label}] ({acres:.0f}ac)",
                    icon=folium.DivIcon(
                        html=f'<div style="'
                             f'width:{size}px;height:{size}px;'
                             f'background:{rating_color};'
                             f'border:2px solid white;'
                             f'border-radius:3px;'
                             f'transform:rotate(45deg);'
                             f'box-shadow:0 0 4px rgba(0,0,0,0.5);'
                             f'display:flex;align-items:center;justify-content:center;'
                             f'">'
                             f'<span style="transform:rotate(-45deg);color:white;'
                             f'font-weight:bold;font-size:10px;">{total}</span></div>',
                        icon_size=(size, size),
                        icon_anchor=(size // 2, size // 2),
                    ),
                ).add_to(group)
            else:
                folium.CircleMarker(
                    location=[z["lat"], z["lon"]],
                    radius=4, color=rating_color,
                    fill=True, fill_color=rating_color, fill_opacity=0.6, weight=1,
                    popup=folium.Popup(popup, max_width=320),
                    tooltip=f"{z['name']}: {total} [{label}] ({acres:.0f}ac)",
                ).add_to(group)
        group.add_to(m)

    # Fire perimeter polygons
    fire_group = folium.FeatureGroup(name="Fire Perimeters", show=False)
    for fire in fires:
        g = fire.get("geometry")
        if g and "rings" in g:
            for ring in g["rings"]:
                coords = [[p[1], p[0]] for p in ring]
                if fire.get("is_rx"):
                    fc, fl = "orange", "Prescribed Burn"
                elif fire.get("is_treatment"):
                    fc, fl = "gray", "Fuel Treatment"
                else:
                    fc, fl = "red", "Wildfire"
                folium.Polygon(
                    locations=coords, color=fc, weight=2,
                    fill=True, fill_opacity=0.15,
                    popup=f"<b>{fire['name']}</b><br>{fl}<br>"
                          f"{fire.get('acres', '?')}ac / {fire.get('date') or fire.get('year', '?')}",
                ).add_to(fire_group)
    fire_group.add_to(m)

    folium.LayerControl(collapsed=False).add_to(m)

    legend_items = "".join(
        f'<span style="color:{mt["color"]};">&#9679;</span> {mt["label"]}<br>'
        for mt in MUSHROOM_TYPES.values()
    )
    legend = f"""
    <div style="position:fixed; bottom:50px; left:50px; z-index:1000;
         background:white; padding:10px; border:2px solid grey; border-radius:5px;
         font-size:12px;">
    <b>Mushroom Types</b><br>
    {legend_items}
    <hr style="margin:4px 0;">
    <b>Score</b><br>
    <span style="color:purple;">&#9670;</span> Excellent (80+)<br>
    <span style="color:green;">&#9670;</span> Good (70-79)<br>
    <span style="color:orange;">&#9679;</span> Fair (50-69)<br>
    <span style="color:gray;">&#9679;</span> &lt;50 hidden<br>
    <hr style="margin:4px 0;">
    <small>algo v{ALGO_VERSION}</small>
    </div>"""
    m.get_root().html.add_child(folium.Element(legend))
    return m


def build_chart(results, output_prefix="morel"):
    if not results:
        return
    rs = sorted(results, key=lambda r: r["result"]["total"], reverse=True)[:30]
    names = [r["zone"]["name"][:35] for r in rs]
    score_keys = list(rs[0]["result"]["scores"].keys())
    mt = MUSHROOM_TYPES.get(rs[0]["result"].get("mushroom_type", "morel"), {})
    weights = mt.get("weights", {})

    fig, ax = plt.subplots(figsize=(14, max(6, len(names) * 0.35)))
    y = np.arange(len(names))
    colors = ["#e74c3c", "#3498db", "#2ecc71", "#f39c12", "#9b59b6"]
    left = np.zeros(len(names))

    for i, key in enumerate(score_keys):
        vals = [r["result"]["scores"].get(key, 0) for r in rs]
        c = colors[i % len(colors)]
        w = weights.get(key, 5)
        ax.barh(y, vals, height=0.6, left=left, label=f"{key} ({w})", color=c)
        left += vals

    ax.set_yticks(y)
    ax.set_yticklabels(names, fontsize=8)
    ax.set_xlabel("Score")
    ax.set_title(f"Morel Foraging Potential — {datetime.now().strftime('%Y-%m-%d')}")
    ax.legend(loc="lower right", fontsize=8)
    ax.set_xlim(0, 110)
    ax.axvline(x=70, color="purple", linestyle="--", alpha=0.4)
    ax.axvline(x=55, color="green", linestyle="--", alpha=0.3)
    ax.invert_yaxis()
    plt.tight_layout()
    plt.savefig(f"{output_prefix}_scores.png", dpi=150)
    print(f"  {output_prefix}_scores.png")


def print_report(results, mushroom_type="morel"):
    mt = MUSHROOM_TYPES[mushroom_type]
    print("\n" + "=" * 78)
    print(f"  {mt['label'].upper()} FORAGING — Top Burn Sites")
    print(f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 78)

    top = sorted(results, key=lambda r: r["result"]["total"], reverse=True)[:25]
    weight_keys = list(mt["weights"].keys())

    for r in top:
        z, res = r["zone"], r["result"]
        total = res["total"]
        s, d = res["scores"], res["details"]
        label, _ = rating(total)

        print(f"\n{'~' * 78}")
        print(f"  {z['name']:45s}  {total:3d}/100  [{label}]")
        print(f"{'~' * 78}")
        score_parts = "  ".join(f"{k}: {s.get(k, 0)}/{mt['weights'][k]}" for k in weight_keys)
        print(f"  {score_parts}")

        lines = []
        for k in ["avg_high_7d", "avg_low_7d", "soil_temp", "precip_14d",
                   "snow_status", "elevation", "slope", "aspect",
                   "burn_type", "burn_acres", "burn_age", "in_season"]:
            if k in d:
                lines.append(f"{k}: {d[k]}")
        for line in lines:
            print(f"    {line}")
