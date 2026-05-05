#!/usr/bin/env python3
"""
Build the porcini candidate catalog (data/porcini_sites.json).

Porcini are mycorrhizal with mature conifers — they don't need fire. So
candidate generation is fundamentally different from morels (which start
from a known fire perimeter):

  1. Download a clipped LANDFIRE EVT raster for the Tahoe Basin (one-time)
  2. Sample the raster on a grid; filter to suitable conifer EVT codes
  3. Cluster surviving pixels into stand-level candidates (~hundreds, not 10k+)
  4. Enrich each cluster centroid with elevation, slope, aspect (USGS EPQS)
  5. Filter by elevation band; persist as catalog

Run this manually when you want to (re)build the porcini site catalog. The
daily scorer just reads the catalog and fetches weather.

Usage:
    python build_porcini_sites.py --fetch-raster   # one-time raster download
    python build_porcini_sites.py                  # full rebuild from raster
"""
from __future__ import annotations

import argparse
import json
import math
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import rasterio
from utils.landfire import EVT_LOOKUP
from utils.landfire_raster import (
    download_evt_raster, iter_evt_grid,
    download_elevation_raster, download_aspect_raster, download_slope_raster,
)


# AOI — matches the morel SEARCH_RADIUS_KM (~120km) coverage so both species
# show the same geographic extent. Wider than just the basin.
TAHOE_BBOX = (-121.6, 38.2, -119.2, 40.4)
RASTER_PATH = Path("data/raster/tahoe_evt.tif")
ELEV_RASTER_PATH = Path("data/raster/tahoe_elev.tif")
ASPECT_RASTER_PATH = Path("data/raster/tahoe_aspect.tif")
SLOPE_RASTER_PATH = Path("data/raster/tahoe_slope.tif")
OUTPUT_PATH = Path("data/porcini_sites.json")

# Native LANDFIRE resolution is 30m, but at the wider AOI that exceeds
# ArcGIS exportImage's 4000x4000 pixel cap. 100m is plenty for visualization.
RASTER_RESOLUTION_M = 100

# Sampling stride on the raster grid. At 100m raster, stride=3 ≈ 300m grid.
SAMPLE_STRIDE = 3

# EVT suitability threshold — anything ≥ 0.5 is potentially porcini habitat.
# Lower threshold than morel because porcini cluster in stands, not at burns,
# so the vegetation IS the site quality (not a modifier on it).
PORCINI_EVT_THRESHOLD = 0.5

# Elevation band — porcini fruit from snow line down to the base of conifer
# forest. Below 4500ft is foothill chaparral; above 8500ft is alpine/krummholz.
PORCINI_ELEV_MIN_FT = 4500
PORCINI_ELEV_MAX_FT = 8500

# Slope filter — drop cliffs and water-pooling flats
PORCINI_SLOPE_MIN_DEG = 0
PORCINI_SLOPE_MAX_DEG = 35

# Cluster radius for grouping pixels into stand-level candidates. ~500m is
# the right scale for "one mature conifer grove" — coarser merges adjacent
# distinct stands. Slow builds are fine; the catalog gets cached.
CLUSTER_BIN_DEG = 0.005  # ~500m at this latitude


def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))


def suitable_evt_codes():
    """EVT codes that are potentially porcini habitat (suitability >= threshold)."""
    return {code for code, (_, suit) in EVT_LOOKUP.items() if suit >= PORCINI_EVT_THRESHOLD}


def sample_and_filter(raster_path):
    """Iterate raster, return list of (lat, lon, evt_code) for suitable pixels."""
    suitable = suitable_evt_codes()
    print(f"  suitable EVT codes (suitability >= {PORCINI_EVT_THRESHOLD}): {sorted(suitable)}")
    survivors = []
    total = 0
    for lat, lon, code in iter_evt_grid(raster_path, stride=SAMPLE_STRIDE):
        total += 1
        if code in suitable:
            survivors.append((lat, lon, code))
    print(f"  sampled {total:,} pixels at stride {SAMPLE_STRIDE} → {len(survivors):,} suitable")
    return survivors


def cluster_pixels(pixels):
    """
    Bin pixels into a coarse spatial grid and emit cluster summaries.
    Each cluster: centroid (mean lat/lon), pixel_count, dominant_evt_code, dominant_evt_name.
    """
    bins = defaultdict(list)
    for lat, lon, code in pixels:
        key = (round(lat / CLUSTER_BIN_DEG), round(lon / CLUSTER_BIN_DEG))
        bins[key].append((lat, lon, code))
    clusters = []
    for members in bins.values():
        # Drop tiny clusters — likely just transition pixels at stand edges.
        if len(members) < 3:
            continue
        c_lat = sum(m[0] for m in members) / len(members)
        c_lon = sum(m[1] for m in members) / len(members)
        # Dominant EVT code
        code_counts = defaultdict(int)
        for _, _, code in members:
            code_counts[code] += 1
        dom_code = max(code_counts, key=code_counts.get)
        dom_name, dom_suit = EVT_LOOKUP.get(dom_code, (f"EVT {dom_code} (unmapped)", 0.5))
        clusters.append({
            "lat": round(c_lat, 6),
            "lon": round(c_lon, 6),
            "pixel_count": len(members),
            "evt_code": dom_code,
            "evt_name": dom_name,
            "evt_suitability": dom_suit,
        })
    print(f"  clustered into {len(clusters)} stand-level candidates "
          f"(median {sorted(c['pixel_count'] for c in clusters)[len(clusters)//2]} pixels each)")
    return clusters


def enrich_clusters_from_rasters(clusters, elev_path, aspect_path, slope_path):
    """Read elevation/slope/aspect for every cluster centroid in one pass
    by sampling the LANDFIRE topo rasters locally. No API calls, no rate
    limits — just numpy indexing.
    """
    with rasterio.open(elev_path) as elev_src, \
         rasterio.open(aspect_path) as aspect_src, \
         rasterio.open(slope_path) as slope_src:
        elev_band = elev_src.read(1)
        aspect_band = aspect_src.read(1)
        slope_band = slope_src.read(1)
        for c in clusters:
            lat, lon = c["lat"], c["lon"]
            try:
                er, ec = elev_src.index(lon, lat)
                ar, ac = aspect_src.index(lon, lat)
                sr, sc = slope_src.index(lon, lat)
                if 0 <= er < elev_src.height and 0 <= ec < elev_src.width:
                    elev_m = float(elev_band[er, ec])
                    # Negative or zero = nodata
                    c["elevation_ft"] = round(elev_m * 3.28084, 1) if elev_m > 0 else None
                if 0 <= ar < aspect_src.height and 0 <= ac < aspect_src.width:
                    asp = int(aspect_band[ar, ac])
                    c["aspect"] = asp if 0 <= asp <= 360 else None
                if 0 <= sr < slope_src.height and 0 <= sc < slope_src.width:
                    slope = int(slope_band[sr, sc])
                    c["slope"] = slope if 0 <= slope <= 90 else None
            except Exception as e:
                pass
    return clusters


def passes_terrain_filter(cluster):
    elev = cluster.get("elevation_ft")
    slope = cluster.get("slope")
    if elev is None:
        return False
    if not (PORCINI_ELEV_MIN_FT <= elev <= PORCINI_ELEV_MAX_FT):
        return False
    if slope is not None and not (PORCINI_SLOPE_MIN_DEG <= slope <= PORCINI_SLOPE_MAX_DEG):
        return False
    return True


def make_slug(cluster, seen_slugs):
    """Generate a URL-friendly slug. Uses dominant EVT name + lat/lon hash."""
    veg_short = (cluster["evt_name"].split(" ")[-1] if cluster["evt_name"] else "stand").lower()
    lat_key = f"{cluster['lat']:.3f}".replace(".", "").replace("-", "")
    lon_key = f"{cluster['lon']:.3f}".replace(".", "").replace("-", "")
    base = f"porcini-{veg_short}-{lat_key}-{lon_key}"
    base = re.sub(r"[^a-z0-9-]+", "-", base).strip("-")
    slug = base
    counter = 2
    while slug in seen_slugs:
        slug = f"{base}-{counter}"
        counter += 1
    seen_slugs.add(slug)
    return slug


def cluster_to_site(cluster, slug):
    """Convert an enriched cluster to a site catalog entry (mirrors sites.json shape)."""
    return {
        "id": f"porcini_{cluster['lat']:.4f}_{cluster['lon']:.4f}",
        "name": f"{cluster['evt_name']} stand @ {cluster['elevation_ft']:.0f}ft" if cluster.get('elevation_ft') else cluster['evt_name'],
        "source": "LANDFIRE EVT cluster",
        "lat": cluster["lat"],
        "lon": cluster["lon"],
        "acres": round(cluster["pixel_count"] * (RASTER_RESOLUTION_M * SAMPLE_STRIDE) ** 2 / 4046.86, 1),  # approx, m²→acres
        "date": None,        # no burn date — porcini are mycorrhizal
        "is_rx": False,
        "burn_type": "",
        "elevation_ft": cluster.get("elevation_ft"),
        "slope": cluster.get("slope"),
        "aspect": cluster.get("aspect"),
        "evt_code": cluster["evt_code"],
        "evt_name": cluster["evt_name"],
        "evt_suitability": cluster["evt_suitability"],
        "pixel_count": cluster["pixel_count"],
        "slug": slug,
    }


def main():
    parser = argparse.ArgumentParser(description="Build porcini candidate site catalog")
    parser.add_argument("--fetch-raster", action="store_true",
                        help="Download the LANDFIRE EVT raster (one-time)")
    parser.add_argument("--force", action="store_true",
                        help="Rebuild catalog from scratch (don't reuse cached enrichment)")
    args = parser.parse_args()

    print("PORCINI SITE CATALOG BUILDER")
    print("=" * 60)

    # Step 0: ensure all four rasters exist (EVT, elev, aspect, slope).
    # Downloaded once from LANDFIRE LFPS; sampling is local from then on.
    rasters = [
        ("EVT", RASTER_PATH, download_evt_raster),
        ("Elevation", ELEV_RASTER_PATH, download_elevation_raster),
        ("Aspect", ASPECT_RASTER_PATH, download_aspect_raster),
        ("Slope", SLOPE_RASTER_PATH, download_slope_raster),
    ]
    print(f"\n[0/4] Ensuring rasters exist for AOI {TAHOE_BBOX}...")
    for label, path, downloader in rasters:
        if args.fetch_raster or not path.exists():
            downloader(TAHOE_BBOX, path, resolution_m=RASTER_RESOLUTION_M)
        else:
            size_kb = path.stat().st_size / 1024
            print(f"  {label}: using existing {path} ({size_kb:.0f}KB)")

    # Step 1: sample raster, filter to suitable EVT codes
    print(f"\n[1/4] Sampling raster and filtering by EVT...")
    pixels = sample_and_filter(RASTER_PATH)
    if not pixels:
        print("  no suitable pixels found — check bbox + EVT threshold")
        return

    # Step 2: cluster pixels into stand-level candidates
    print(f"\n[2/4] Clustering pixels into stands ({CLUSTER_BIN_DEG:.4f}° bins)...")
    clusters = cluster_pixels(pixels)

    # Step 3: enrich centroids with elevation/slope/aspect from LANDFIRE
    # topo rasters (already downloaded in step 0). Pure local sampling — no
    # API calls, no rate limits.
    print(f"\n[3/4] Sampling elevation/aspect/slope rasters at {len(clusters)} centroids...")
    enriched = enrich_clusters_from_rasters(
        clusters, ELEV_RASTER_PATH, ASPECT_RASTER_PATH, SLOPE_RASTER_PATH)
    have_elev = sum(1 for c in enriched if c.get("elevation_ft") is not None)
    print(f"  {have_elev}/{len(enriched)} have elevation data")

    # Step 4: filter by elevation/slope, assign slugs, write
    print(f"\n[4/4] Applying terrain filters ({PORCINI_ELEV_MIN_FT}-{PORCINI_ELEV_MAX_FT}ft, "
          f"slope {PORCINI_SLOPE_MIN_DEG}-{PORCINI_SLOPE_MAX_DEG}°)...")
    survivors = [c for c in enriched if passes_terrain_filter(c)]
    print(f"  {len(survivors)} clusters survive terrain filter")

    seen_slugs = set()
    sites = []
    for c in sorted(survivors, key=lambda c: (-c["pixel_count"], c["lat"])):
        slug = make_slug(c, seen_slugs)
        sites.append(cluster_to_site(c, slug))

    catalog = {
        "generated": datetime.now().strftime("%Y-%m-%d"),
        "mushroom_type": "porcini",
        "source": "LANDFIRE LF2024 EVT raster + USGS 3DEP",
        "bbox": TAHOE_BBOX,
        "sample_stride_m": RASTER_RESOLUTION_M * SAMPLE_STRIDE,
        "cluster_bin_deg": CLUSTER_BIN_DEG,
        "evt_threshold": PORCINI_EVT_THRESHOLD,
        "elev_band_ft": [PORCINI_ELEV_MIN_FT, PORCINI_ELEV_MAX_FT],
        "sites": sites,
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(catalog, indent=2))
    size_kb = OUTPUT_PATH.stat().st_size / 1024
    print(f"\nWrote {len(sites)} porcini candidate sites to {OUTPUT_PATH} ({size_kb:.0f}KB)")

    # Stats by EVT type
    by_evt = defaultdict(int)
    for s in sites:
        by_evt[s["evt_name"]] += 1
    print(f"\nSites by vegetation type:")
    for name, n in sorted(by_evt.items(), key=lambda kv: -kv[1])[:8]:
        print(f"  {n:4d}  {name}")


if __name__ == "__main__":
    main()
