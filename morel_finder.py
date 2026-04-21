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

import json
import math
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path

from config import (ALDER_CREEK, TAHOE_BASIN_CENTER, SEARCH_RADIUS_KM,
                    LOCAL_RADIUS_KM, CACHE_DIR, MUSHROOM_TYPES, ALGO_VERSION)
from scoring import score_burn_site, score_burn_multiday
from phase_scoring import (build_timeline, extract_features, classify_phase,
                           score_readiness, score_potential)
from mapping import print_report, rating
from utils.weather import get_weather
from utils.elevation import get_elevation_ft, get_slope_aspect, get_best_aspect
from utils.fires import get_recent_fires, get_tahoe_fuels_treatments
from utils.pfirs import load_pfirs_cache, pfirs_to_fire_records, filter_radius as pfirs_filter
from utils.landfire import get_evt


def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat/2)**2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon/2)**2)
    return R * 2 * math.asin(math.sqrt(a))


def score_burn(fire, mushroom_type="morel"):
    """Fetch weather + elevation + terrain for a burn. Compute phase + legacy scores."""
    lat = fire.get("centroid_lat")
    lon = fire.get("centroid_lon")
    if lat is None or lon is None:
        return None
    weather = get_weather(lat, lon)
    elev = get_elevation_ft(lat, lon)
    terrain = get_best_aspect(lat, lon)
    evt = get_evt(lat, lon)
    name = fire.get("name", "?")
    zone = {"name": name, "lat": lat, "lon": lon, "elevation_ft": elev,
            "slope": terrain.get("slope"), "aspect": terrain.get("aspect"),
            "evt_code": evt.get("evt_code"), "evt_name": evt.get("evt_name")}

    # Legacy scoring (kept for folium maps + backward compat)
    result = score_burn_site(fire, weather, elev, mushroom_type, terrain=terrain)
    day_scores = score_burn_multiday(fire, weather, elev, terrain, mushroom_type)

    # Phase scoring (v0.7.0)
    config = MUSHROOM_TYPES.get(mushroom_type, {})
    timeline = build_timeline(weather, config)
    potential = score_potential(fire, elev, terrain, mushroom_type, evt=evt)

    phase_days = []
    for d in range(8):
        target = 30 + d  # 30 = today in 44-day timeline
        features = extract_features(timeline, weather, target, config)
        readiness = score_readiness(features)
        phase = classify_phase(features)
        phase_days.append({
            "day": d,
            "readiness": readiness,
            "phase": phase,
            "status": timeline[target] if target < len(timeline) else "BAD",
            "start_days": features["start_days"],
            "grow_days": features["grow_days"],
            "max_bad_streak": features["max_bad_streak"],
        })

    return {"zone": zone, "fire": fire, "weather": weather,
            "result": result, "day_scores": day_scores,
            "potential": potential, "timeline": timeline, "phase_days": phase_days}


def export_json(results, all_fires, run_date):
    """Export scored burns as JSON for the SPA frontend."""
    today = datetime.now()
    data = {
        "run_date": run_date,
        "algo_version": ALGO_VERSION,
        "center": {"lat": ALDER_CREEK[0], "lon": ALDER_CREEK[1], "name": "Alder Creek"},
        "local_radius_km": LOCAL_RADIUS_KM,
        "burns": [],
    }
    history_data = []  # raw weather arrays, indexed same as burns
    for r in results:
        z = r["zone"]
        f = r.get("fire", {})
        days = []
        for ds in r.get("day_scores", []):
            day_date = (today + timedelta(days=ds["day"])).strftime("%Y-%m-%d")
            # Prefix detail keys to avoid collision with score keys
            # (e.g. "soil_gdd" exists in both scores and details)
            detail_items = {}
            for k, v in ds.get("details", {}).items():
                if isinstance(v, (str, int, float)):
                    if k in ds["scores"]:
                        detail_items["d_" + k] = v  # prefix to avoid collision
                    else:
                        detail_items[k] = v
            days.append({
                "day": ds["day"],
                "date": day_date,
                "total": ds["total"],
                **ds["scores"],
                **detail_items,
            })
        # Raw weather time series for detail page visualization
        wx = r.get("weather", {})
        history = {}
        for key in ["hist_soil_temp", "hist_precip", "hist_snowfall",
                     "hist_temps_max", "hist_temps_min"]:
            vals = wx.get(key, [])
            if vals:
                history[key] = [round(v, 1) if v is not None else None for v in vals]
        for key in ["forecast_soil_temp", "forecast_snow_depth",
                     "forecast_temps_max", "forecast_temps_min"]:
            vals = wx.get(key, [])
            if vals:
                history[key] = [round(v, 1) if v is not None else None for v in vals]

        # Phase scoring data
        pot = r.get("potential", {})
        phase_days = r.get("phase_days", [])
        tl = r.get("timeline", [])

        data["burns"].append({
            "name": z["name"],
            "lat": z["lat"],
            "lon": z["lon"],
            "acres": f.get("acres", 0),
            "burn_type": f.get("pfirs_burn_type", "") or ("RX" if f.get("is_rx") else "wildfire"),
            "burn_date": f.get("date", ""),
            "elevation_ft": z.get("elevation_ft"),
            "slope": z.get("slope"),
            "aspect": z.get("aspect"),
            "evt_name": z.get("evt_name"),
            # Phase scoring (v0.7.0)
            "potential": pot.get("potential", 0),
            "potential_scores": pot.get("scores", {}),
            "timeline": tl,
            "phase_days": phase_days,
            # Legacy per-day scores
            "days": days,
        })
        # Collect history separately to keep latest.json lean
        history_data.append(history)

    out_dir = Path("docs/data")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "latest.json"
    compact = json.dumps(data, indent=None, separators=(",", ":"))
    out_path.write_text(compact)
    size_kb = out_path.stat().st_size / 1024

    # History file — raw weather arrays for detail page charts
    hist_path = out_dir / "history.json"
    hist_compact = json.dumps(history_data, indent=None, separators=(",", ":"))
    hist_path.write_text(hist_compact)
    hist_kb = hist_path.stat().st_size / 1024

    # Archive — date-stamped copies for hindcasting
    runs_dir = out_dir / "runs"
    runs_dir.mkdir(exist_ok=True)
    (runs_dir / f"{run_date}.json").write_text(compact)
    (runs_dir / f"{run_date}_history.json").write_text(hist_compact)

    print(f"  docs/data/latest.json ({size_kb:.0f}KB) + history.json ({hist_kb:.0f}KB)")
    print(f"  docs/data/runs/{run_date}.json archived")


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

    # Step 4: Export JSON for SPA
    run_date = datetime.now().strftime("%Y-%m-%d")
    print(f"\n[4/4] Exporting JSON ({run_date})...")
    export_json(results, all_fires, run_date)

    print(f"\nDone! Cache: {CACHE_DIR}/")


if __name__ == "__main__":
    main()
