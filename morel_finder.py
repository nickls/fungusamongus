#!/usr/bin/env python3
"""
Morel Foraging Recommender — Burn Site Analysis
================================================
Scores burn locations for morel foraging potential using weather,
terrain, and fire recency data. See README.md for full methodology.

Reads static site data from data/sites.json (built by build_sites.py).
Only fetches weather per-run — everything else is pre-computed.

Usage:
    python morel_finder.py                     # default config
    python morel_finder.py --config alt.py     # custom scoring config
"""

import json
import math
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path

from config import (ALDER_CREEK, LOCAL_RADIUS_KM, CACHE_DIR,
                    MUSHROOM_TYPES, ALGO_VERSION)
from scoring import score_burn_site, score_burn_multiday
from phase_scoring import (build_timeline, extract_features, classify_phase,
                           score_readiness, score_potential)
from mapping import print_report, rating
from utils.weather import get_weather


SITES_PATH = Path("data/sites.json")


def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat/2)**2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon/2)**2)
    return R * 2 * math.asin(math.sqrt(a))


def load_sites():
    """Load the static site catalog built by build_sites.py."""
    if not SITES_PATH.exists():
        print(f"  ERROR: {SITES_PATH} not found. Run: python build_sites.py")
        return []
    data = json.loads(SITES_PATH.read_text())
    sites = data.get("sites", [])
    print(f"  Loaded {len(sites)} sites from {SITES_PATH} (built {data.get('generated', '?')})")
    return sites


def site_to_fire(site):
    """Convert a site catalog entry back to the fire dict format used by scoring."""
    return {
        "name": site["name"],
        "slug": site.get("slug", ""),
        "source": site.get("source", ""),
        "centroid_lat": site["lat"],
        "centroid_lon": site["lon"],
        "acres": site.get("acres", 0),
        "date": site.get("date"),
        "is_rx": site.get("is_rx", False),
        "pfirs_burn_type": site.get("burn_type", ""),
    }


def score_site(site, mushroom_type="morel"):
    """Fetch weather and compute scores for a site from the catalog."""
    lat, lon = site["lat"], site["lon"]
    weather = get_weather(lat, lon)

    # Static data from catalog
    elev = site.get("elevation_ft")
    terrain = {"slope": site.get("slope"), "aspect": site.get("aspect")}
    evt = {
        "evt_code": site.get("evt_code"),
        "evt_name": site.get("evt_name", "Unknown"),
        "evt_suitability": site.get("evt_suitability"),
    }
    fire = site_to_fire(site)

    zone = {"name": site["name"], "lat": lat, "lon": lon, "elevation_ft": elev,
            "slope": terrain.get("slope"), "aspect": terrain.get("aspect"),
            "evt_code": evt.get("evt_code"), "evt_name": evt.get("evt_name")}

    # Legacy scoring (kept for folium maps + backward compat)
    result = score_burn_site(fire, weather, elev, mushroom_type, terrain=terrain)
    day_scores = score_burn_multiday(fire, weather, elev, terrain, mushroom_type)

    # Phase scoring (v0.7.0)
    config = MUSHROOM_TYPES.get(mushroom_type, {})
    timeline, reasons = build_timeline(weather, config)
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
            "potential": potential, "timeline": timeline,
            "timeline_reasons": reasons, "phase_days": phase_days}


def export_json(results, run_date):
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
            detail_items = {}
            for k, v in ds.get("details", {}).items():
                if isinstance(v, (str, int, float)):
                    if k in ds["scores"]:
                        detail_items["d_" + k] = v
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
        tl_reasons = r.get("timeline_reasons", [])

        # Compute burn age in months for filter
        burn_age_months = None
        if f.get("date"):
            try:
                burn_age_months = round((today - datetime.strptime(f["date"], "%Y-%m-%d")).days / 30, 1)
            except (ValueError, TypeError):
                pass

        data["burns"].append({
            "slug": f.get("slug", ""),
            "name": z["name"],
            "lat": z["lat"],
            "lon": z["lon"],
            "acres": f.get("acres", 0),
            "burn_type": f.get("pfirs_burn_type", "") or ("RX" if f.get("is_rx") else "wildfire"),
            "burn_date": f.get("date", ""),
            "burn_age_months": burn_age_months,
            "elevation_ft": z.get("elevation_ft"),
            "slope": z.get("slope"),
            "aspect": z.get("aspect"),
            "evt_name": z.get("evt_name"),
            # Phase scoring (v0.7.0)
            "potential": pot.get("potential", 0),
            "potential_scores": pot.get("scores", {}),
            "timeline": tl,
            "timeline_reasons": tl_reasons,
            "phase_days": phase_days,
            # Legacy per-day scores
            "days": days,
        })
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


def main():
    print("MOREL FORAGING — Burn Site Analysis")
    print("=" * 60)
    CACHE_DIR.mkdir(exist_ok=True)

    # Step 1: Load site catalog
    print(f"\n[1/3] Loading site catalog...")
    sites = load_sites()
    if not sites:
        return

    rx = sum(1 for s in sites if s.get("is_rx"))
    wf = len(sites) - rx
    print(f"  {rx} RX burns, {wf} wildfires")

    # Step 2: Score each site (weather only — static data from catalog)
    print(f"\n[2/3] Scoring {len(sites)} sites (fetching weather)...")
    results = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(score_site, s, "morel"): s for s in sites}
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

    # Step 3: Export JSON for SPA
    run_date = datetime.now().strftime("%Y-%m-%d")
    print(f"\n[3/3] Exporting JSON ({run_date})...")
    export_json(results, run_date)

    print(f"\nDone! {len(results)} sites scored.")


if __name__ == "__main__":
    main()
