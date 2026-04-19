"""
PFIRS (Prescribed Fire Information Reporting System) scraper.

CARB's PFIRS has no public API — burn data is server-rendered into the HTML
as inline Google Maps marker JavaScript. This module scrapes and parses it.

Usage:
    from utils.pfirs import fetch_pfirs, load_pfirs_cache

    # Fetch fresh data (requires session cookie from browser)
    burns = fetch_pfirs("10/01/2025", "04/19/2026", cookie="PHPSESSID=...")

    # Load from cache
    burns = load_pfirs_cache()
    burns = load_pfirs_cache(region="tahoe")

To get a session cookie:
    1. Open https://ssl.arb.ca.gov/pfirs/index.php in Chrome
    2. Open DevTools > Network tab
    3. Submit a date range query
    4. Copy the Cookie header from the request
"""

import json
import math
import re
from datetime import datetime
from pathlib import Path

import requests

CACHE_DIR = Path(__file__).parent.parent / "cache"
PFIRS_URL = "https://ssl.arb.ca.gov/pfirs/index.php"

# Greater Tahoe / Sierra bounding box
# Covers Nevada City to south, Sierraville to north, South Lake to south
TAHOE_BOUNDS = {"lat_min": 38.3, "lat_max": 40.0, "lon_min": -121.5, "lon_max": -119.3}


def fetch_pfirs(date_begin: str, date_end: str,
                cookie: str | None = None,
                save_raw: bool = True) -> list[dict]:
    """
    Fetch prescribed burn data from PFIRS for a date range.

    Args:
        date_begin: Start date in MM/DD/YYYY format
        date_end: End date in MM/DD/YYYY format
        cookie: Browser cookie string (PHPSESSID + TS01ad8875).
                Without it, PFIRS may return limited results.
        save_raw: Save the raw HTML response for debugging
    """
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Origin": "https://ssl.arb.ca.gov",
        "Referer": PFIRS_URL,
        "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/145.0.0.0 Safari/537.36"),
    }
    if cookie:
        headers["Cookie"] = cookie

    data = {
        "show": "1",
        "viewby": "1",
        "date_begin": date_begin,
        "date_end": date_end,
        "submit": "View",
    }

    print(f"  Fetching PFIRS ({date_begin} - {date_end})...")
    r = requests.post(PFIRS_URL, headers=headers, data=data,
                      timeout=120, verify=False)
    r.raise_for_status()
    html = r.text

    if save_raw:
        CACHE_DIR.mkdir(exist_ok=True)
        (CACHE_DIR / "pfirs_raw.html").write_text(html)

    burns = parse_pfirs_html(html)
    print(f"  Parsed {len(burns)} unique burns from PFIRS")

    # Cache results
    CACHE_DIR.mkdir(exist_ok=True)
    (CACHE_DIR / "pfirs_all.json").write_text(json.dumps(burns, indent=2))

    tahoe = filter_bounds(burns, **TAHOE_BOUNDS)
    (CACHE_DIR / "pfirs_tahoe.json").write_text(json.dumps(tahoe, indent=2))
    print(f"  Cached: {len(burns)} total, {len(tahoe)} Tahoe area")

    return burns


def parse_pfirs_html(html: str) -> list[dict]:
    """Parse PFIRS HTML to extract all burn ignition records."""
    lat_lons = re.findall(r'LatLng\(([-\d.]+),\s*([-\d.]+)\)', html)
    blocks = re.split(r'LatLng\([-\d.]+,\s*[-\d.]+\)', html)[1:]

    burns = []
    for i, (lat, lon) in enumerate(lat_lons):
        if i >= len(blocks):
            break
        block = blocks[i]

        name_m = re.search(r'<h1>([^<]+)</h1>', block)
        date_m = re.search(r'Date:</td><td>([^<]+)', block)
        agency_m = re.search(r'Managing Agency:</td><td>([^<]+)', block)
        burn_type_m = re.search(r'Burn Type:</td><td>([^<]+)', block)
        acres_m = re.search(r'Acres:</td><td>([\d.]+)', block)
        status_m = re.search(r'Status:</td><td>([^<]+)', block)

        burns.append({
            "lat": float(lat),
            "lon": float(lon),
            "name": name_m.group(1).strip() if name_m else "?",
            "date": date_m.group(1).strip() if date_m else "?",
            "agency": agency_m.group(1).strip() if agency_m else "?",
            "burn_type": burn_type_m.group(1).strip() if burn_type_m else "?",
            "acres": float(acres_m.group(1)) if acres_m else 0,
            "status": status_m.group(1).strip() if status_m else "?",
        })

    # Dedupe — each burn appears twice (project info tab + activity tab)
    seen = set()
    unique = []
    for b in burns:
        key = (round(b["lat"], 5), round(b["lon"], 5), b["name"])
        if key not in seen:
            seen.add(key)
            unique.append(b)

    return unique


def filter_bounds(burns: list[dict], lat_min: float, lat_max: float,
                  lon_min: float, lon_max: float) -> list[dict]:
    """Filter burns to a bounding box."""
    return [b for b in burns
            if lat_min <= b["lat"] <= lat_max and lon_min <= b["lon"] <= lon_max]


def filter_radius(burns: list[dict], center_lat: float, center_lon: float,
                  radius_km: float) -> list[dict]:
    """Filter burns within radius_km of a center point."""
    result = []
    for b in burns:
        dlat = math.radians(b["lat"] - center_lat)
        dlon = math.radians(b["lon"] - center_lon)
        a = (math.sin(dlat/2)**2 +
             math.cos(math.radians(center_lat)) *
             math.cos(math.radians(b["lat"])) *
             math.sin(dlon/2)**2)
        dist = 6371 * 2 * math.asin(math.sqrt(a))
        if dist <= radius_km:
            result.append({**b, "distance_km": round(dist, 2)})
    return sorted(result, key=lambda x: x["distance_km"])


def load_pfirs_cache(region: str = "all") -> list[dict]:
    """
    Load cached PFIRS data.

    Args:
        region: "all" for statewide, "tahoe" for Tahoe area only
    """
    filename = "pfirs_tahoe.json" if region == "tahoe" else "pfirs_all.json"
    path = CACHE_DIR / filename
    if not path.exists():
        print(f"  No PFIRS cache at {path}")
        print("  Run: python -m utils.pfirs --fetch --cookie 'PHPSESSID=...'")
        return []
    data = json.loads(path.read_text())
    print(f"  [cached] {len(data)} PFIRS burns ({region})")
    return data


def pfirs_to_fire_records(burns: list[dict]) -> list[dict]:
    """Convert PFIRS burns to the fire record format used by morel_finder."""
    records = []
    for b in burns:
        # Parse the human-readable date (e.g. "April 19, 2026")
        fire_date = None
        try:
            dt = datetime.strptime(b["date"], "%B %d, %Y")
            fire_date = dt.strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            pass

        records.append({
            "name": f"{b['name']} ({b['burn_type']})",
            "source": f"PFIRS ({b['agency']})",
            "acres": b["acres"],
            "date": fire_date,
            "year": fire_date[:4] if fire_date else None,
            "is_rx": True,
            "is_treatment": True,
            "centroid_lat": b["lat"],
            "centroid_lon": b["lon"],
            "geometry": None,
            "pfirs_status": b["status"],
            "pfirs_burn_type": b["burn_type"],
            "pfirs_agency": b["agency"],
        })
    return records


# ── CLI ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="PFIRS prescribed burn scraper")
    parser.add_argument("--fetch", action="store_true", help="Fetch fresh data from PFIRS")
    parser.add_argument("--begin", default="01/01/2025", help="Start date MM/DD/YYYY")
    parser.add_argument("--end", default=datetime.now().strftime("%m/%d/%Y"), help="End date MM/DD/YYYY")
    parser.add_argument("--cookie", help="Browser cookie string for PFIRS session")
    parser.add_argument("--center-lat", type=float, default=39.328, help="Center latitude")
    parser.add_argument("--center-lon", type=float, default=-120.183, help="Center longitude")
    parser.add_argument("--radius", type=float, default=50, help="Radius in km")
    parser.add_argument("--parse-raw", action="store_true",
                        help="Parse existing pfirs_raw.html instead of fetching")
    args = parser.parse_args()

    if args.fetch:
        burns = fetch_pfirs(args.begin, args.end, cookie=args.cookie)
    elif args.parse_raw:
        raw_path = CACHE_DIR / "pfirs_raw.html"
        if not raw_path.exists():
            # Try project root
            raw_path = Path("pfirs_raw.html")
        if raw_path.exists():
            print(f"  Parsing {raw_path}...")
            html = raw_path.read_text()
            burns = parse_pfirs_html(html)
            print(f"  Parsed {len(burns)} unique burns")
            CACHE_DIR.mkdir(exist_ok=True)
            (CACHE_DIR / "pfirs_all.json").write_text(json.dumps(burns, indent=2))
            tahoe = filter_bounds(burns, **TAHOE_BOUNDS)
            (CACHE_DIR / "pfirs_tahoe.json").write_text(json.dumps(tahoe, indent=2))
            print(f"  Cached: {len(burns)} total, {len(tahoe)} Tahoe area")
        else:
            print("  No pfirs_raw.html found. Use --fetch or save the HTML manually.")
            burns = []
    else:
        burns = load_pfirs_cache()

    if burns:
        nearby = filter_radius(burns, args.center_lat, args.center_lon, args.radius)
        print(f"\n{len(nearby)} burns within {args.radius}km of ({args.center_lat}, {args.center_lon}):\n")
        for b in nearby[:40]:
            d = b.get("distance_km", 0)
            print(f"  {d:5.1f}km  {b['name']:35s} {b['acres']:7.1f}ac  "
                  f"{b['burn_type']:15s} {b['date']}")
