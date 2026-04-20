#!/usr/bin/env python3
"""
Morel Foraging Recommender — Burn Site Analysis
================================================
Scores burn locations for morel foraging potential using weather,
terrain, and fire recency data. See README.md for full methodology.

Usage:
    python morel_finder.py                     # default config
    python morel_finder.py --config alt.py     # custom scoring config
"""

import math
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import pandas as pd

from config import (ALDER_CREEK, TAHOE_BASIN_CENTER, SEARCH_RADIUS_KM,
                    LOCAL_RADIUS_KM, CACHE_DIR, MUSHROOM_TYPES)
from scoring import score_burn_site
from mapping import build_map, build_chart, print_report, rating
from utils.weather import get_weather
from utils.elevation import get_elevation_ft, get_slope_aspect
from utils.fires import get_recent_fires, get_tahoe_fuels_treatments
from utils.pfirs import load_pfirs_cache, pfirs_to_fire_records, filter_radius as pfirs_filter


def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat/2)**2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon/2)**2)
    return R * 2 * math.asin(math.sqrt(a))


def score_burn(fire, mushroom_type="morel"):
    """Fetch weather + elevation + terrain for a burn and score it."""
    lat = fire.get("centroid_lat")
    lon = fire.get("centroid_lon")
    if lat is None or lon is None:
        return None
    weather = get_weather(lat, lon)
    elev = get_elevation_ft(lat, lon)
    terrain = get_slope_aspect(lat, lon)
    name = fire.get("name", "?")
    zone = {"name": name, "lat": lat, "lon": lon, "elevation_ft": elev,
            "slope": terrain.get("slope"), "aspect": terrain.get("aspect")}
    result = score_burn_site(fire, weather, elev, mushroom_type, terrain=terrain)
    return {"zone": zone, "fire": fire, "weather": weather, "result": result}


def gather_fire_data(center, radius_km):
    """Fetch all fire/treatment/PFIRS data for a center point."""
    all_fires = get_recent_fires(center[0], center[1], radius_km)
    fuels_tx = get_tahoe_fuels_treatments(center[0], center[1], radius_km + 20)
    all_fires.extend(fuels_tx)

    pfirs_burns = load_pfirs_cache(region="all")
    if pfirs_burns:
        nearby_pfirs = pfirs_filter(pfirs_burns, center[0], center[1], radius_km)
        pfirs_records = pfirs_to_fire_records(nearby_pfirs)
        all_fires.extend(pfirs_records)

    wildfire_ct = sum(1 for f in all_fires if not f.get("is_rx") and not f.get("is_treatment"))
    rx_ct = sum(1 for f in all_fires if f.get("is_rx"))
    tx_ct = sum(1 for f in all_fires if f.get("is_treatment") and not f.get("is_rx"))
    print(f"  Total: {len(all_fires)} ({wildfire_ct} wildfire, {rx_ct} burns, {tx_ct} mechanical)")
    return all_fires


def dedupe_burns(fires, min_dist_km=0.5):
    """Dedupe fires at essentially the same location."""
    unique = []
    for f in fires:
        lat, lon = f.get("centroid_lat"), f.get("centroid_lon")
        if lat is None or lon is None:
            continue
        dupe = False
        for u in unique:
            if haversine_km(lat, lon, u["centroid_lat"], u["centroid_lon"]) < min_dist_km:
                if (f.get("acres", 0) > u.get("acres", 0) or
                        (f.get("date") or "") > (u.get("date") or "")):
                    unique.remove(u)
                    unique.append(f)
                dupe = True
                break
        if not dupe:
            unique.append(f)
    return unique


def main():
    print("MOREL FORAGING — Burn Site Analysis")
    print("=" * 60)
    CACHE_DIR.mkdir(exist_ok=True)

    # Step 1: Gather all fire/burn data
    print(f"\n[1/4] Fetching fire + treatment data ({SEARCH_RADIUS_KM}km)...")
    all_fires = gather_fire_data(ALDER_CREEK, SEARCH_RADIUS_KM)

    # Step 2: Filter to RX burns with coordinates, dedupe
    burns_to_score = [f for f in all_fires
                      if f.get("centroid_lat") and f.get("centroid_lon")
                      and f.get("is_rx")]
    burns_to_score = dedupe_burns(burns_to_score, min_dist_km=0.3)
    print(f"\n[2/4] {len(burns_to_score)} unique burn sites to score")

    # Step 3: Score each burn for morels (parallel)
    print(f"\n[3/4] Scoring burns...")
    results = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(score_burn, f, "morel"): f for f in burns_to_score}
        for fut in as_completed(futures):
            try:
                r = fut.result()
                if r and r["result"]["total"] > 0:
                    results.append(r)
            except Exception:
                pass
    results.sort(key=lambda r: r["result"]["total"], reverse=True)

    for r in results[:5]:
        lbl, _ = rating(r["result"]["total"])
        print(f"  {r['zone']['name']:40s} {r['result']['total']:3d}/100 [{lbl}]")

    print_report(results, "morel")

    # Step 4: Maps + outputs (dated)
    run_date = datetime.now().strftime("%Y-%m-%d")
    print(f"\n[4/4] Building maps ({run_date})...")
    morel_results = {"morel": results}

    # Local map
    local = {"morel": [r for r in results
                       if haversine_km(r["zone"]["lat"], r["zone"]["lon"],
                                       ALDER_CREEK[0], ALDER_CREEK[1]) <= LOCAL_RADIUS_KM]}
    local_fires = [f for f in all_fires
                   if f.get("centroid_lat") and f.get("centroid_lon")
                   and haversine_km(f["centroid_lat"], f["centroid_lon"],
                                    ALDER_CREEK[0], ALDER_CREEK[1]) <= LOCAL_RADIUS_KM]
    m_local = build_map(local, local_fires, center=ALDER_CREEK)
    m_local.save(f"morel_local_{run_date}.html")
    print(f"  morel_local_{run_date}.html ({len(local['morel'])} scored burns)")

    # Basin map
    m_basin = build_map(morel_results, all_fires, center=TAHOE_BASIN_CENTER)
    m_basin.save(f"morel_basin_{run_date}.html")
    print(f"  morel_basin_{run_date}.html ({len(results)} scored burns)")

    # Chart + CSV
    build_chart(results, f"morel_{run_date}")

    summary = []
    for r in results[:100]:
        lbl, _ = rating(r["result"]["total"])
        dist = haversine_km(r["zone"]["lat"], r["zone"]["lon"],
                            ALDER_CREEK[0], ALDER_CREEK[1])
        summary.append({
            "burn_name": r["zone"]["name"],
            "lat": r["zone"]["lat"], "lon": r["zone"]["lon"],
            "elevation_ft": r["zone"].get("elevation_ft"),
            "dist_from_alder_mi": round(dist / 1.609, 1),
            "total_score": r["result"]["total"], "rating": lbl,
            **r["result"]["scores"], **r["result"]["details"],
        })
    if summary:
        pd.DataFrame(summary).to_csv(f"morel_results_{run_date}.csv", index=False)
        print(f"  morel_results_{run_date}.csv")

    print(f"\nDone! Cache: {CACHE_DIR}/")


if __name__ == "__main__":
    main()
