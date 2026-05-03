#!/usr/bin/env python3
"""
Build the static site catalog (data/sites.json).

Fetches fire/burn sites from all sources, enriches with elevation, slope,
aspect, and vegetation type, then writes a checked-in catalog. Run this
manually when you want to discover new sites — the daily scorer just reads
the catalog.

Usage:
    python build_sites.py                  # full rebuild
    python build_sites.py --update         # only fetch sites not already in catalog
"""
from __future__ import annotations

import argparse
import json
import math
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

from config import ALDER_CREEK, SEARCH_RADIUS_KM, CACHE_DIR
from utils.fires import get_recent_fires, get_tahoe_fuels_treatments
from utils.pfirs import load_pfirs_cache, pfirs_to_fire_records, filter_radius as pfirs_filter
from utils.elevation import get_elevation_ft, get_best_aspect
from utils.landfire import get_evt


SITES_PATH = Path("data/sites.json")


def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))


def dedupe_burns(fires, min_dist_km=0.3):
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


def site_id(fire):
    """Generate a stable ID from source + location."""
    lat = round(fire.get("centroid_lat", 0), 4)
    lon = round(fire.get("centroid_lon", 0), 4)
    src = (fire.get("source") or "unknown").lower().replace(" ", "_")
    return f"{src}_{lat}_{lon}"


def make_slug(name, date, seen_slugs):
    """Generate a URL-friendly slug from site name + year. Dedupes."""
    slug = re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')
    # Truncate overly long slugs
    if len(slug) > 60:
        slug = slug[:60].rsplit('-', 1)[0]
    # Append year if we have a date
    if date:
        year = date[:4]
        if not slug.endswith(year):
            slug = f"{slug}-{year}"
    # Dedupe
    base = slug
    counter = 2
    while slug in seen_slugs:
        slug = f"{base}-{counter}"
        counter += 1
    seen_slugs.add(slug)
    return slug


def enrich_site(fire):
    """Fetch elevation, slope/aspect, EVT for a fire location."""
    lat = fire.get("centroid_lat")
    lon = fire.get("centroid_lon")
    if lat is None or lon is None:
        return None

    elev = get_elevation_ft(lat, lon)
    terrain = get_best_aspect(lat, lon)
    evt = get_evt(lat, lon)

    burn_type = fire.get("pfirs_burn_type", "")
    if not burn_type:
        burn_type = "RX" if fire.get("is_rx") else "wildfire"

    return {
        "id": site_id(fire),
        "name": fire.get("name", "Unknown"),
        "source": fire.get("source", ""),
        "lat": round(lat, 6),
        "lon": round(lon, 6),
        "acres": round(fire.get("acres", 0), 1),
        "date": fire.get("date"),
        "is_rx": fire.get("is_rx", False),
        "burn_type": burn_type,
        "elevation_ft": round(elev, 1) if elev else None,
        "slope": terrain.get("slope"),
        "aspect": terrain.get("aspect"),
        "evt_code": evt.get("evt_code"),
        "evt_name": evt.get("evt_name"),
        "evt_suitability": evt.get("evt_suitability"),
    }


def load_existing():
    """Load existing catalog, returns dict keyed by site ID."""
    if SITES_PATH.exists():
        data = json.loads(SITES_PATH.read_text())
        return {s["id"]: s for s in data.get("sites", [])}
    return {}


def main():
    parser = argparse.ArgumentParser(description="Build static site catalog")
    parser.add_argument("--update", action="store_true",
                        help="Only add sites not already in catalog")
    args = parser.parse_args()

    print("SITE CATALOG BUILDER")
    print("=" * 60)
    CACHE_DIR.mkdir(exist_ok=True)

    existing = load_existing() if args.update else {}
    if existing:
        print(f"  Loaded {len(existing)} existing sites (--update mode)")

    # Gather fires from all sources
    print(f"\n[1/3] Fetching fire + treatment data ({SEARCH_RADIUS_KM}km)...")
    all_fires = get_recent_fires(ALDER_CREEK[0], ALDER_CREEK[1], SEARCH_RADIUS_KM)
    fuels_tx = get_tahoe_fuels_treatments(ALDER_CREEK[0], ALDER_CREEK[1], SEARCH_RADIUS_KM + 20)
    all_fires.extend(fuels_tx)

    pfirs_burns = load_pfirs_cache(region="all")
    if pfirs_burns:
        nearby_pfirs = pfirs_filter(pfirs_burns, ALDER_CREEK[0], ALDER_CREEK[1], SEARCH_RADIUS_KM)
        pfirs_records = pfirs_to_fire_records(nearby_pfirs)
        all_fires.extend(pfirs_records)

    wildfire_ct = sum(1 for f in all_fires if not f.get("is_rx") and not f.get("is_treatment"))
    rx_ct = sum(1 for f in all_fires if f.get("is_rx"))
    tx_ct = sum(1 for f in all_fires if f.get("is_treatment") and not f.get("is_rx"))
    print(f"  Total: {len(all_fires)} ({wildfire_ct} wildfire, {rx_ct} RX burns, {tx_ct} mechanical)")

    # Filter to burns with coordinates, dedupe (NO is_rx filter — include wildfires)
    candidates = [f for f in all_fires
                  if f.get("centroid_lat") and f.get("centroid_lon")
                  and (f.get("is_rx") or not f.get("is_treatment"))]
    candidates = dedupe_burns(candidates, min_dist_km=0.3)
    print(f"\n[2/3] {len(candidates)} unique sites to catalog")

    # Skip already-known sites in update mode (by ID OR by proximity)
    if args.update:
        existing_locs = [(s["lat"], s["lon"]) for s in existing.values()]

        def already_have(f):
            if site_id(f) in existing:
                return True
            for elat, elon in existing_locs:
                if haversine_km(f["centroid_lat"], f["centroid_lon"], elat, elon) < 0.3:
                    return True
            return False

        new = [f for f in candidates if not already_have(f)]
        print(f"  {len(new)} new sites ({len(candidates) - len(new)} already cataloged)")
        candidates = new

    # Enrich each site with elevation, slope, EVT
    print(f"\n[3/3] Enriching {len(candidates)} sites (elevation, slope, EVT)...")
    sites = dict(existing)  # start with existing
    done = 0
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(enrich_site, f): f for f in candidates}
        for fut in as_completed(futures):
            try:
                site = fut.result()
                if site:
                    sites[site["id"]] = site
                    done += 1
                    if done % 50 == 0:
                        print(f"  {done}/{len(candidates)}...")
            except Exception as e:
                print(f"  [error] {e}")

    # Assign slugs
    sorted_sites = sorted(sites.values(), key=lambda s: s["name"])
    seen_slugs = set()
    for s in sorted_sites:
        if not s.get("slug"):
            s["slug"] = make_slug(s["name"], s.get("date"), seen_slugs)
        else:
            seen_slugs.add(s["slug"])

    # Write catalog
    catalog = {
        "generated": datetime.now().strftime("%Y-%m-%d"),
        "sites": sorted_sites,
    }

    SITES_PATH.parent.mkdir(parents=True, exist_ok=True)
    SITES_PATH.write_text(json.dumps(catalog, indent=2))
    size_kb = SITES_PATH.stat().st_size / 1024
    print(f"\nWrote {len(catalog['sites'])} sites to {SITES_PATH} ({size_kb:.0f}KB)")

    # Stats
    rx = sum(1 for s in catalog["sites"] if s.get("is_rx"))
    wf = sum(1 for s in catalog["sites"] if not s.get("is_rx"))
    has_elev = sum(1 for s in catalog["sites"] if s.get("elevation_ft"))
    print(f"  {rx} RX burns, {wf} wildfires")
    print(f"  {has_elev}/{len(catalog['sites'])} have elevation data")


if __name__ == "__main__":
    main()
