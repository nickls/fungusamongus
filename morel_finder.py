#!/usr/bin/env python3
"""
Foraging Recommender — Site Analysis
================================================
Scores candidate locations for mushroom foraging potential using weather,
terrain, and (for fire-associated species) fire recency data. See README.md.

Reads static site data from data/<type>_sites.json (built by build_sites.py
or build_porcini_sites.py). Only fetches weather per-run.

Usage:
    python morel_finder.py                            # morel (default)
    python morel_finder.py --mushroom-type=porcini    # porcini
"""

import argparse
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


# Per-mushroom-type site catalog. Morel uses the historical sites.json (burn
# perimeters); other species use <type>_sites.json (e.g. porcini_sites.json
# from build_porcini_sites.py). Falls back to sites.json so Phase A can run
# porcini end-to-end against burn sites before its dedicated catalog exists.
def sites_path_for(mushroom_type):
    if mushroom_type == "morel":
        return Path("data/sites.json")
    type_path = Path(f"data/{mushroom_type}_sites.json")
    if type_path.exists():
        return type_path
    return Path("data/sites.json")  # fallback during Phase A bringup


def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat/2)**2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon/2)**2)
    return R * 2 * math.asin(math.sqrt(a))


def load_sites(mushroom_type="morel"):
    """Load the static site catalog for the given mushroom type."""
    path = sites_path_for(mushroom_type)
    if not path.exists():
        builder = "build_sites.py" if mushroom_type == "morel" else f"build_{mushroom_type}_sites.py"
        print(f"  ERROR: {path} not found. Run: python {builder}")
        return []
    data = json.loads(path.read_text())
    sites = data.get("sites", [])
    print(f"  Loaded {len(sites)} sites from {path} (built {data.get('generated', '?')})")
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

    # Compute raw readiness + phase for EVERY day in the 44-day timeline.
    raw_readiness = []
    daily_phase = []
    daily_features = []
    for i in range(len(timeline)):
        feats = extract_features(timeline, weather, i, config)
        raw_readiness.append(score_readiness(feats, config))
        daily_phase.append(classify_phase(feats, config))
        daily_features.append(feats)

    # Anti-whiplash ratchet: existing fruits persist N days; if the site had
    # high readiness recently, today's reading is floored by the decayed peak.
    # Decay/lookback are config-driven (morel=0.93/14d, porcini=0.95/21d).
    DECAY = config.get("ratchet_decay", 0.93)
    LOOKBACK = config.get("ratchet_lookback", 14)
    ratcheted_readiness = []
    for i in range(len(raw_readiness)):
        floor = 0
        for back in range(1, LOOKBACK + 1):
            j = i - back
            if j < 0:
                break
            decayed = raw_readiness[j] * (DECAY ** back)
            if decayed > floor:
                floor = decayed
        ratcheted_readiness.append(max(raw_readiness[i], round(floor)))

    # Days harvestable: consecutive days ending at i where ratcheted readiness >= 50.
    # Higher value = mushrooms have been harvestable longer = more picked-over risk.
    HARVEST_THRESH = 50
    days_harvestable = []
    streak = 0
    for r in ratcheted_readiness:
        if r >= HARVEST_THRESH:
            streak += 1
        else:
            streak = 0
        days_harvestable.append(streak)

    phase_days = []
    for d in range(8):
        target = 30 + d  # 30 = today in 44-day timeline
        if target >= len(timeline):
            break
        feats = daily_features[target]
        phase_days.append({
            "day": d,
            "readiness": ratcheted_readiness[target],
            "readiness_raw": raw_readiness[target],
            "days_harvestable": days_harvestable[target],
            "phase": daily_phase[target],
            "status": timeline[target],
            "start_days": feats["start_days"],
            "grow_days": feats["grow_days"],
            "max_bad_streak": feats["max_bad_streak"],
        })

    return {"zone": zone, "fire": fire, "weather": weather,
            "result": result, "day_scores": day_scores,
            "potential": potential, "timeline": timeline,
            "timeline_reasons": reasons, "phase_days": phase_days,
            "readiness_timeline": ratcheted_readiness,
            "raw_readiness_timeline": raw_readiness,
            "days_harvestable_timeline": days_harvestable}


def export_json(results, run_date, mushroom_type="morel"):
    """Export scored sites as JSON for the SPA frontend."""
    today = datetime.now()
    data = {
        "run_date": run_date,
        "algo_version": ALGO_VERSION,
        "mushroom_type": mushroom_type,
        "center": {"lat": ALDER_CREEK[0], "lon": ALDER_CREEK[1], "name": "Alder Creek"},
        "local_radius_km": LOCAL_RADIUS_KM,
        "burns": [],  # historical key — kept as "burns" in the JSON for SPA backward-compat
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
            "readiness_timeline": r.get("readiness_timeline", []),
            "raw_readiness_timeline": r.get("raw_readiness_timeline", []),
            "days_harvestable_timeline": r.get("days_harvestable_timeline", []),
            "phase_days": phase_days,
            # Legacy per-day scores
            "days": days,
        })
        history_data.append(history)

    out_dir = Path("docs/data")
    out_dir.mkdir(parents=True, exist_ok=True)
    compact = json.dumps(data, indent=None, separators=(",", ":"))
    hist_compact = json.dumps(history_data, indent=None, separators=(",", ":"))

    # Per-type files — Phase C will switch the SPA to read these directly.
    out_path = out_dir / f"{mushroom_type}-latest.json"
    out_path.write_text(compact)
    hist_path = out_dir / f"{mushroom_type}-history.json"
    hist_path.write_text(hist_compact)

    # Backward-compat: morel run also writes the legacy unprefixed filenames
    # so the existing SPA keeps working until Phase C wires per-type loading.
    if mushroom_type == "morel":
        (out_dir / "latest.json").write_text(compact)
        (out_dir / "history.json").write_text(hist_compact)

    # Archive — date-stamped copies for hindcasting (per-type)
    runs_dir = out_dir / "runs"
    runs_dir.mkdir(exist_ok=True)
    (runs_dir / f"{run_date}_{mushroom_type}.json").write_text(compact)
    (runs_dir / f"{run_date}_{mushroom_type}_history.json").write_text(hist_compact)
    if mushroom_type == "morel":
        # Legacy archive names — keep for hindcast tooling
        (runs_dir / f"{run_date}.json").write_text(compact)
        (runs_dir / f"{run_date}_history.json").write_text(hist_compact)

    size_kb = out_path.stat().st_size / 1024
    hist_kb = hist_path.stat().st_size / 1024
    print(f"  docs/data/{out_path.name} ({size_kb:.0f}KB) + {hist_path.name} ({hist_kb:.0f}KB)")
    print(f"  docs/data/runs/{run_date}_{mushroom_type}.json archived")


def main():
    parser = argparse.ArgumentParser(description="Mushroom foraging recommender")
    parser.add_argument("--mushroom-type", default="morel",
                        choices=list(MUSHROOM_TYPES.keys()),
                        help="Which mushroom species to score (default: morel)")
    args = parser.parse_args()
    mushroom_type = args.mushroom_type
    profile = MUSHROOM_TYPES[mushroom_type]

    print(f"{profile['label'].upper()} — Site Analysis")
    print("=" * 60)
    CACHE_DIR.mkdir(exist_ok=True)

    # Step 1: Load site catalog
    print(f"\n[1/3] Loading site catalog...")
    sites = load_sites(mushroom_type)
    if not sites:
        return

    if profile.get("needs_fire"):
        rx = sum(1 for s in sites if s.get("is_rx"))
        wf = len(sites) - rx
        print(f"  {rx} RX burns, {wf} wildfires")

    # Step 2a: Pre-rank by static potential (vegetation + elevation + aspect
    # + season — no weather needed). For species with huge catalogs (porcini
    # can have ~10k stand candidates), cap to top-N before fetching weather
    # to keep the output JSON manageable. Morel has a smaller catalog so the
    # cap doesn't bind.
    max_sites = profile.get("max_scored_sites")
    if max_sites and len(sites) > max_sites:
        print(f"\n[2a/3] Pre-ranking {len(sites)} sites by static potential (no weather)...")
        scored = []
        for s in sites:
            fire = site_to_fire(s)
            evt = {"evt_code": s.get("evt_code"), "evt_name": s.get("evt_name", "Unknown"),
                   "evt_suitability": s.get("evt_suitability")}
            terrain = {"slope": s.get("slope"), "aspect": s.get("aspect")}
            pot = score_potential(fire, s.get("elevation_ft"), terrain, mushroom_type, evt=evt)
            scored.append((pot.get("potential", 0), s))
        scored.sort(key=lambda t: t[0], reverse=True)
        sites = [s for _, s in scored[:max_sites]]
        print(f"  kept top {len(sites)} by static potential (min={scored[max_sites-1][0]}, "
              f"max={scored[0][0]})")

    # Step 2b: Score each kept site with full weather + phase + readiness
    print(f"\n[2/3] Scoring {len(sites)} sites (fetching weather)...")
    results = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(score_site, s, mushroom_type): s for s in sites}
        for fut in as_completed(futures):
            try:
                r = fut.result()
                if not r:
                    continue
                # Keep result if EITHER legacy or phase scoring shows non-zero.
                legacy_total = r["result"]["total"]
                phase_potential = r.get("potential", {}).get("potential", 0)
                if legacy_total > 0 or phase_potential > 0:
                    results.append(r)
            except Exception:
                pass
    # Sort by phase potential (the v0.7+ score) with legacy total as tiebreaker.
    results.sort(key=lambda r: (r.get("potential", {}).get("potential", 0),
                                r["result"]["total"]), reverse=True)

    for r in results[:5]:
        lbl, _ = rating(r["result"]["total"])
        print(f"  {r['zone']['name']:40s} {r['result']['total']:3d}/100 [{lbl}]")

    # Step 3: Export JSON for SPA
    run_date = datetime.now().strftime("%Y-%m-%d")
    print(f"\n[3/3] Exporting JSON ({run_date})...")
    export_json(results, run_date, mushroom_type)

    print(f"\nDone! {len(results)} sites scored.")


if __name__ == "__main__":
    main()
