#!/usr/bin/env python3
"""
Morel Mushroom Foraging Recommender — Truckee / Tahoe Area
===========================================================
Combines weather, fire history (wildfires + prescribed burns),
elevation, and snowmelt data to score candidate foraging zones.

Data sources (all free, no API keys):
- Open-Meteo: weather, soil temp, snow depth, forecast
- PFIRS (CARB): prescribed fire ignitions scraped from ssl.arb.ca.gov
- Tahoe Forest Fuels Treatments (USFS ArcGIS): prescribed burns + mechanical
- NIFC Interagency Fire Perimeter History: wildfire perimeters
- USGS Elevation Point Query Service

Morel biology (Sierra Nevada):
- Best in areas burned within last 12 months (moderate-high severity)
- Prescribed burns (even small pile burns) produce localized flushes
- Soil temp 45-60F, air highs 55-75F, cool nights
- Adequate moisture: recent rain or active snowmelt
- Elevation band: 5000-8000ft near Tahoe, moves upslope through season
- Mixed conifer forest preferred
- Typically fruit 1-3 weeks after snowmelt at a given elevation
"""

import hashlib
import json
import math
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import folium
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests

from utils.pfirs import load_pfirs_cache, pfirs_to_fire_records, filter_radius as pfirs_filter

# ── Configuration ──────────────────────────────────────────────────────────

ALDER_CREEK = (39.3187, -120.2125)  # Alder Creek Adventure Center
TAHOE_BASIN_CENTER = (39.1, -120.15)  # Greater Tahoe Basin center
SEARCH_RADIUS_KM = 120  # covers Nevada City to South Lake
LOCAL_RADIUS_KM = 48  # ~30mi

CACHE_DIR = Path("cache")
CACHE_TTL_HOURS = 6
CACHE_TTL_FIRE_HOURS = 24

# ── Mushroom type scoring profiles ─────────────────────────────────────────
# Each type defines ideal conditions. Weights must sum to 100.
MUSHROOM_TYPES = {
    "morel": {
        "label": "Morels (Morchella)",
        "color": "#DAA520",  # goldenrod
        "icon": "M",
        "needs_fire": True,
        "weights": {"temperature": 20, "moisture": 25, "elevation": 15, "burn_quality": 40},
        "temp_ideal_high": (55, 75),   # F
        "temp_ok_high": (45, 85),
        "temp_ideal_low": (30, 50),
        "soil_temp_ideal": (45, 60),
        "elev_base": 4500,             # shifts +300ft/month from April
        "elev_range": 2500,
        "season_months": (4, 7),       # Apr-Jul
        "notes": "Fire-associated. Best 3-12mo post-burn, moderate severity, "
                 "after snowmelt when soil warms to 50F+.",
    },
    "chanterelle": {
        "label": "Chanterelles (Cantharellus)",
        "color": "#FF8C00",  # dark orange
        "icon": "C",
        "needs_fire": False,
        "weights": {"temperature": 25, "moisture": 35, "elevation": 15, "forest_maturity": 25},
        "temp_ideal_high": (65, 85),
        "temp_ok_high": (55, 95),
        "temp_ideal_low": (45, 60),
        "soil_temp_ideal": (55, 70),
        "elev_base": 4000,
        "elev_range": 3000,
        "season_months": (7, 10),      # Jul-Oct
        "notes": "Mature conifer/hardwood forest. Needs sustained moisture, "
                 "warm soil. NOT fire-associated — avoid burns.",
    },
    "porcini": {
        "label": "King Bolete / Porcini (Boletus)",
        "color": "#8B4513",  # saddle brown
        "icon": "P",
        "needs_fire": False,
        "weights": {"temperature": 25, "moisture": 30, "elevation": 20, "forest_maturity": 25},
        "temp_ideal_high": (60, 80),
        "temp_ok_high": (50, 90),
        "temp_ideal_low": (40, 55),
        "soil_temp_ideal": (50, 65),
        "elev_base": 5000,
        "elev_range": 3000,
        "season_months": (6, 10),      # Jun-Oct
        "notes": "Mycorrhizal with conifers (pine, spruce, fir). Needs rain "
                 "events followed by warm days. Mature forest preferred.",
    },
    "matsutake": {
        "label": "Matsutake (Tricholoma)",
        "color": "#CD853F",  # peru
        "icon": "T",
        "needs_fire": False,
        "weights": {"temperature": 20, "moisture": 30, "elevation": 20, "forest_maturity": 30},
        "temp_ideal_high": (50, 70),
        "temp_ok_high": (40, 75),
        "temp_ideal_low": (30, 50),
        "soil_temp_ideal": (40, 55),
        "elev_base": 5000,
        "elev_range": 3000,
        "season_months": (9, 11),      # Sep-Nov
        "notes": "Pine/fir forests, sandy or well-drained soil. Late season, "
                 "needs first fall rains + cooling temps. Undisturbed forest.",
    },
}

# ── Fixed reference zones (commented out — burn-location approach active) ──
# Uncomment and use with score_zone() to score arbitrary points.
# ALL_ZONES = [
#     ("Alder Creek",              39.3187, -120.2125, "adventure center"),
#     ("Truckee (town)",           39.3280, -120.1833, "baseline"),
#     ("Donner Lake W",            39.3280, -120.2700, "west end, conifer"),
#     ("Coldstream Valley",        39.3100, -120.2900, "drainage"),
#     ("Tahoe Donner N",           39.3650, -120.2400, "managed forest"),
#     ("Tahoe Donner W",           39.3500, -120.2600, "deeper conifer"),
#     ("Prosser Creek S",          39.3750, -120.1700, "understory burns"),
#     ("Prosser Creek N",          39.3950, -120.1500, "fuel reduction"),
#     ("Boca Reservoir W",         39.3870, -120.1050, "conifer-sage"),
#     ("Boca Reservoir E",         39.3900, -120.0750, "east side"),
#     ("Prosser-Boca ridge",       39.3850, -120.1200, "ridge"),
#     ("Stampede Reservoir SW",    39.4600, -120.1250, "early melt"),
#     ("Stampede Reservoir NE",    39.4800, -120.0900, "later melt"),
#     ("Martis Valley",            39.3100, -120.1500, "meadow-conifer"),
#     ("Sagehen Creek",            39.4314, -120.2406, "research station"),
#     ("Donner Summit",            39.3190, -120.3290, "high elevation"),
#     ("Soda Springs",             39.3260, -120.3800, "high elev"),
#     ("Cisco Grove",              39.3150, -120.4500, "I-80 corridor"),
#     ("Tahoe NF Kyburz Flat",     39.3600, -120.4200, "fuel work"),
#     ("Northstar",                39.2740, -120.1200, "managed forest"),
#     ("Kings Beach",              39.2350, -120.0300, "north shore"),
#     ("Incline Village",          39.2510, -119.9720, "east shore"),
#     ("Verdi / Dog Valley",       39.5200, -119.9800, "dry conifer"),
#     ("Tahoe City",               39.1680, -120.1450, "west shore"),
#     ("Alpine Meadows",           39.1640, -120.2380, "ski area"),
#     ("Squaw / Palisades",        39.1960, -120.2350, "fuel work"),
#     ("Tahoe NF Yuba Pass",       39.4280, -120.5820, "high conifer"),
#     ("Sierra Co Haypress",       39.5100, -120.4500, "fuel reduction"),
#     ("Sierraville",              39.5700, -120.3600, "conifer-range"),
#     ("LTBMU South Shore",        38.9300, -120.0200, "USFS RX"),
#     ("Meeks Bay",                39.0350, -120.1300, "mixed conifer"),
#     ("Blackwood Canyon",         39.1100, -120.1900, "managed burns"),
#     ("Caldor pile burns",        38.7900, -120.2200, "Caldor + pile burns"),
#     ("Nevada City",              39.2600, -121.0200, "lower elev"),
#     ("Hwy 49 Camptonville",     39.4500, -121.0600, "pile burns"),
#     ("Hwy 49 Downieville",      39.5590, -120.8270, "repeated burns"),
#     ("Foresthill Divide",        39.0200, -120.8200, "lower elev"),
# ]


# ── Cache ──────────────────────────────────────────────────────────────────

def cache_key(prefix: str, **kwargs) -> str:
    raw = f"{prefix}:{json.dumps(kwargs, sort_keys=True)}"
    return hashlib.md5(raw.encode()).hexdigest()[:12]

def cache_get(key: str, ttl_hours: float) -> dict | None:
    path = CACHE_DIR / f"{key}.json"
    if not path.exists():
        return None
    age_hours = (time.time() - path.stat().st_mtime) / 3600
    if age_hours > ttl_hours:
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None

def cache_set(key: str, data: dict):
    CACHE_DIR.mkdir(exist_ok=True)
    (CACHE_DIR / f"{key}.json").write_text(json.dumps(data))


# ── Helpers ────────────────────────────────────────────────────────────────

def fetch_json(url: str, params: dict | None = None, timeout: int = 30) -> dict | None:
    try:
        r = requests.get(url, params=params, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"  [warn] {url[:60]}… — {e}")
        return None

def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat/2)**2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon/2)**2)
    return R * 2 * math.asin(math.sqrt(a))


# ── 1) Weather (Open-Meteo) ───────────────────────────────────────────────

def get_weather(lat: float, lon: float) -> dict[str, Any]:
    key = cache_key("wx", lat=round(lat, 3), lon=round(lon, 3))
    cached = cache_get(key, CACHE_TTL_HOURS)
    if cached:
        return cached

    today = datetime.now().date()
    start = today - timedelta(days=30)

    # Historical weather (last 30 days)
    hist = fetch_json("https://archive-api.open-meteo.com/v1/archive", {
        "latitude": lat, "longitude": lon,
        "start_date": start.isoformat(),
        "end_date": (today - timedelta(days=1)).isoformat(),
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,snowfall_sum",
        "temperature_unit": "fahrenheit",
        "precipitation_unit": "inch",
        "timezone": "America/Los_Angeles",
    })

    # Forecast (7 days + 7 past) — confirmed working variables
    forecast = fetch_json("https://api.open-meteo.com/v1/forecast", {
        "latitude": lat, "longitude": lon,
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,snowfall_sum",
        "hourly": "soil_temperature_0cm,soil_moisture_0_1cm,snow_depth",
        "current_weather": "true",
        "temperature_unit": "fahrenheit",
        "precipitation_unit": "inch",
        "timezone": "America/Los_Angeles",
        "forecast_days": 7,
        "past_days": 7,
    })

    def safe_list(d, field):
        return [x for x in (d.get(field) or []) if x is not None]

    def hourly_to_daily_max(hourly_vals):
        daily = []
        for i in range(0, len(hourly_vals), 24):
            chunk = [x for x in hourly_vals[i:i+24] if x is not None]
            if chunk:
                daily.append(max(chunk))
        return daily

    def hourly_to_daily_mean(hourly_vals):
        daily = []
        for i in range(0, len(hourly_vals), 24):
            chunk = [x for x in hourly_vals[i:i+24] if x is not None]
            if chunk:
                daily.append(sum(chunk) / len(chunk))
        return daily

    result = {
        "lat": lat, "lon": lon,
        "hist_temps_max": [], "hist_temps_min": [],
        "hist_precip": [], "hist_snowfall": [],
        "forecast_temps_max": [], "forecast_temps_min": [],
        "forecast_soil_temp": [], "forecast_soil_moisture": [],
        "forecast_snow_depth": [],
        "current_temp": None, "current_soil_temp": None,
    }

    if hist and "daily" in hist:
        d = hist["daily"]
        result["hist_temps_max"] = safe_list(d, "temperature_2m_max")
        result["hist_temps_min"] = safe_list(d, "temperature_2m_min")
        result["hist_precip"] = safe_list(d, "precipitation_sum")
        result["hist_snowfall"] = safe_list(d, "snowfall_sum")

    if forecast and "daily" in forecast:
        d = forecast["daily"]
        result["forecast_temps_max"] = safe_list(d, "temperature_2m_max")
        result["forecast_temps_min"] = safe_list(d, "temperature_2m_min")

    if forecast and "hourly" in forecast:
        h = forecast["hourly"]
        soil_t = h.get("soil_temperature_0cm", [])
        soil_m = h.get("soil_moisture_0_1cm", [])
        snow_d = h.get("snow_depth", [])
        if soil_t:
            result["forecast_soil_temp"] = hourly_to_daily_max(soil_t)
        if soil_m:
            result["forecast_soil_moisture"] = hourly_to_daily_mean(soil_m)
        if snow_d:
            result["forecast_snow_depth"] = hourly_to_daily_max(snow_d)

    if forecast and "current_weather" in forecast:
        c = forecast["current_weather"]
        result["current_temp"] = c.get("temperature")

    cache_set(key, result)
    return result


# ── 2) Elevation (USGS) ───────────────────────────────────────────────────

def get_elevation_ft(lat: float, lon: float) -> float | None:
    key = cache_key("elev", lat=round(lat, 4), lon=round(lon, 4))
    cached = cache_get(key, CACHE_TTL_FIRE_HOURS)
    if cached:
        return cached.get("value")

    data = fetch_json("https://epqs.nationalmap.gov/v1/json", {
        "x": lon, "y": lat, "units": "Feet", "wkid": 4326,
    })
    val = None
    if data and "value" in data:
        try:
            val = float(data["value"])
        except (ValueError, TypeError):
            pass
    cache_set(key, {"value": val})
    return val


# ── 3) Fire Perimeters (NIFC Interagency History — the one that works) ────

def get_recent_fires(center_lat: float, center_lon: float,
                     radius_km: float = 70) -> list[dict]:
    """
    Query NIFC Interagency Fire Perimeter History (public, no auth).
    This is the only reliable free federal fire perimeter API as of 2026.
    WFIGS year-specific endpoints are dead; CAL FIRE + IRWIN now require tokens.
    """
    key = cache_key("fires_nifc", lat=round(center_lat, 2), lon=round(center_lon, 2), r=radius_km)
    cached = cache_get(key, CACHE_TTL_FIRE_HOURS)
    if cached:
        print(f"  [cached] {len(cached)} NIFC fire perimeters")
        return cached

    fires = []
    deg = radius_km / 111.0
    envelope = f"{center_lon-deg},{center_lat-deg},{center_lon+deg},{center_lat+deg}"
    url = ("https://services3.arcgis.com/T4QMspbfLg3qTGWY/arcgis/rest/services"
           "/InteragencyFirePerimeterHistory_All_Years_View/FeatureServer/0/query")

    # Fetch fires from last 3 years
    current_year = datetime.now().year
    print(f"  Querying NIFC Interagency Fire History ({current_year-3}+)...")
    offset = 0
    while True:
        data = fetch_json(url, {
            "geometry": envelope,
            "geometryType": "esriGeometryEnvelope",
            "spatialRel": "esriSpatialRelIntersects",
            "inSR": "4326", "outSR": "4326",
            "where": f"FIRE_YEAR_INT >= {current_year - 3}",
            "outFields": "INCIDENT,GIS_ACRES,DATE_CUR,FIRE_YEAR_INT,AGENCY,SOURCE,FEATURE_CA,COMMENTS",
            "returnGeometry": "true", "f": "json",
            "resultRecordCount": 2000,
            "resultOffset": offset,
        }, timeout=60)

        if not data or "features" not in data or not data["features"]:
            break

        for feat in data["features"]:
            a = feat.get("attributes", {})
            g = feat.get("geometry", {})
            name = a.get("INCIDENT") or "Unknown"
            acres = float(a.get("GIS_ACRES") or 0)
            year = a.get("FIRE_YEAR_INT")
            feature_cat = (a.get("FEATURE_CA") or "").lower()

            # Parse DATE_CUR (format: "20240913150000" or "20240820")
            fire_date = None
            dc = a.get("DATE_CUR")
            if dc and len(str(dc)) >= 8:
                try:
                    fire_date = f"{str(dc)[:4]}-{str(dc)[4:6]}-{str(dc)[6:8]}"
                except (IndexError, ValueError):
                    pass

            # Detect prescribed fires from feature category or name
            is_rx = ("prescribed" in feature_cat or "rx" in feature_cat
                     or "prescribed" in name.lower() or "rx " in name.lower())

            clat, clon = None, None
            if "rings" in g and g["rings"] and g["rings"][0]:
                ring = g["rings"][0]
                clon = sum(p[0] for p in ring) / len(ring)
                clat = sum(p[1] for p in ring) / len(ring)

            fires.append({
                "name": name, "source": "NIFC", "acres": acres,
                "date": fire_date, "year": str(year) if year else None,
                "is_rx": is_rx, "is_treatment": False,
                "centroid_lat": clat, "centroid_lon": clon,
                "geometry": g if g else None,
            })

        if not data.get("exceededTransferLimit"):
            break
        offset += len(data["features"])

    rx_ct = sum(1 for f in fires if f["is_rx"])
    print(f"  Found {len(fires)} fire perimeters ({rx_ct} prescribed, {len(fires)-rx_ct} wildfire)")
    cache_set(key, fires)
    return fires


# ── 5) Tahoe Forest Fuels Treatments (USFS ArcGIS) ────────────────────────

RX_KEYWORDS = {"burn", "rx", "prescribed", "pile", "underburn", "broadcast", "fire", "ignit"}

def get_tahoe_fuels_treatments(center_lat, center_lon, radius_km=80):
    key = cache_key("fuels", lat=round(center_lat, 2), lon=round(center_lon, 2), r=radius_km)
    cached = cache_get(key, CACHE_TTL_FIRE_HOURS)
    if cached:
        print(f"  [cached] {len(cached)} fuel treatments")
        return cached

    fires = []
    deg = radius_km / 111.0
    envelope = f"{center_lon-deg},{center_lat-deg},{center_lon+deg},{center_lat+deg}"
    url = ("https://services6.arcgis.com/1KtlSd2mklZMBKaz/arcgis/rest/services"
           "/Tahoe_Forest_Fuels_Tx_OFFICIAL_Public_View/FeatureServer/0/query")

    current_year = datetime.now().year
    print("  Querying Tahoe Forest Fuels Treatments...")

    # Paginate — ArcGIS caps at 1000/2000 per request
    offset = 0
    while True:
        data = fetch_json(url, {
            "geometry": envelope,
            "geometryType": "esriGeometryEnvelope",
            "spatialRel": "esriSpatialRelIntersects",
            "inSR": "4326", "outSR": "4326",
            "where": f"YEAR >= {current_year - 3}",
            "outFields": "ACT,YEAR,ACRES,CATEGORY,PROJ,FuelsTx",
            "returnGeometry": "true", "f": "json",
            "resultRecordCount": 2000,
            "resultOffset": offset,
        }, timeout=60)

        if not data or "features" not in data or not data["features"]:
            break

        for feat in data["features"]:
            a = feat.get("attributes", {})
            g = feat.get("geometry", {})
            act = (a.get("ACT") or "").lower()
            year = a.get("YEAR")
            acres = float(a.get("ACRES") or 0)
            is_burn = any(kw in act for kw in RX_KEYWORDS)

            clat, clon = None, None
            if "rings" in g and g["rings"] and g["rings"][0]:
                ring = g["rings"][0]
                clon = sum(p[0] for p in ring) / len(ring)
                clat = sum(p[1] for p in ring) / len(ring)

            name = f"{a.get('PROJ', '?')} — {a.get('ACT', '?')}"
            fires.append({
                "name": name, "source": "Tahoe Fuels Tx",
                "acres": acres, "date": f"{year}-01-15" if year else None,
                "year": str(year) if year else None,
                "is_rx": is_burn, "is_treatment": True,
                "activity": act, "category": (a.get("CATEGORY") or "").lower(),
                "centroid_lat": clat, "centroid_lon": clon,
                "geometry": g if g else None,
            })

        if not data.get("exceededTransferLimit"):
            break
        offset += len(data["features"])

    burn_count = sum(1 for f in fires if f["is_rx"])
    print(f"  Found {len(fires)} fuel treatments ({burn_count} burns, {len(fires) - burn_count} mechanical)")
    cache_set(key, fires)
    return fires


# ── 6) Scoring Engine ─────────────────────────────────────────────────────

def extract_weather_details(weather: dict) -> dict:
    """Extract common weather details from a weather dict."""
    d = {}
    fc_max = weather.get("forecast_temps_max", [])
    fc_min = weather.get("forecast_temps_min", [])
    hist_max = weather.get("hist_temps_max", [])
    hist_min = weather.get("hist_temps_min", [])

    highs = fc_max[-7:] if fc_max else hist_max[-7:]
    lows = fc_min[-7:] if fc_min else hist_min[-7:]
    if highs:
        d["avg_high"] = np.mean(highs)
        d["avg_high_7d"] = f"{d['avg_high']:.0f}F"
    if lows:
        d["avg_low"] = np.mean(lows)
        d["avg_low_7d"] = f"{d['avg_low']:.0f}F"

    soil_temps = weather.get("forecast_soil_temp", [])
    if soil_temps:
        d["avg_soil"] = np.mean(soil_temps)
        d["soil_temp"] = f"{d['avg_soil']:.0f}F"

    hist_precip = weather.get("hist_precip", [])
    if hist_precip:
        d["precip_14d_val"] = sum(hist_precip[-14:])
        d["precip_30d_val"] = sum(hist_precip)
        d["precip_14d"] = f"{d['precip_14d_val']:.1f}in"
        d["precip_30d"] = f"{d['precip_30d_val']:.1f}in"

    snow_depth = weather.get("forecast_snow_depth", [])
    if snow_depth and len(snow_depth) >= 7:
        d["snow_past"] = np.mean(snow_depth[:7])
        d["snow_now"] = np.mean(snow_depth[-3:])
        d["snow_depth_now"] = f"{d['snow_now']:.1f}in"
        if d["snow_past"] > 1.0 and d["snow_now"] < d["snow_past"] * 0.5:
            d["snow_status"] = f"ACTIVE MELT ({d['snow_past']:.0f}->{d['snow_now']:.0f}in)"
            d["melt_score"] = 1.0
        elif d["snow_now"] < 0.5 and d["snow_past"] > 0.5:
            d["snow_status"] = "recently melted"
            d["melt_score"] = 0.8
        elif d["snow_now"] > 10:
            d["snow_status"] = f"deep snowpack ({d['snow_now']:.0f}in)"
            d["melt_score"] = -0.2
        elif d["snow_now"] > 2:
            d["snow_status"] = f"snow cover ({d['snow_now']:.0f}in)"
            d["melt_score"] = 0.2
        elif d["snow_past"] < 0.5:
            d["snow_status"] = "snow-free"
            d["melt_score"] = 0.4
        else:
            d["snow_status"] = "some snow"
            d["melt_score"] = 0.3
    else:
        hist_snow = weather.get("hist_snowfall", [])
        if hist_snow and sum(hist_snow) > 2 and sum(hist_snow[-7:]) < 0.5:
            d["snow_status"] = "recent snowfall, tapering"
            d["melt_score"] = 0.6
        elif hist_snow and sum(hist_snow) > 0:
            d["snow_status"] = f"snowfall ({sum(hist_snow):.1f}in/30d)"
            d["melt_score"] = 0.3
        else:
            d["snow_status"] = "dry" if not hist_snow else "no snow"
            d["melt_score"] = 0.2

    soil_moisture = weather.get("forecast_soil_moisture", [])
    if soil_moisture:
        d["avg_sm"] = np.mean(soil_moisture[-7:])
        d["soil_moisture"] = f"{d['avg_sm']:.2f}m3/m3"

    return d


def score_burn_site(fire: dict, weather: dict, elev: float | None,
                    mushroom_type: str = "morel") -> dict:
    """
    Score a burn location for a specific mushroom type (0-100).
    The burn IS the candidate — no "proximity to fire" needed.
    """
    mt = MUSHROOM_TYPES[mushroom_type]
    w = mt["weights"]
    scores = {}
    details = {}
    wx = extract_weather_details(weather)
    details.update({k: v for k, v in wx.items() if isinstance(v, str)})

    # ── Temperature Score ──
    max_pts = w.get("temperature", 20)
    temp_score = 0
    avg_high = wx.get("avg_high")
    avg_low = wx.get("avg_low")
    avg_soil = wx.get("avg_soil")

    if avg_high is not None:
        lo, hi = mt["temp_ideal_high"]
        ok_lo, ok_hi = mt["temp_ok_high"]
        if lo <= avg_high <= hi:
            temp_score += max_pts * 0.5
        elif ok_lo <= avg_high <= ok_hi:
            temp_score += max_pts * 0.25

    if avg_low is not None:
        lo, hi = mt["temp_ideal_low"]
        if lo <= avg_low <= hi:
            temp_score += max_pts * 0.3
        elif lo - 5 <= avg_low <= hi + 5:
            temp_score += max_pts * 0.15

    if avg_soil is not None:
        lo, hi = mt["soil_temp_ideal"]
        if lo <= avg_soil <= hi:
            temp_score += max_pts * 0.2
        elif lo - 5 <= avg_soil <= hi + 5:
            temp_score += max_pts * 0.1

    scores["temperature"] = min(round(temp_score), max_pts)

    # ── Moisture Score ──
    max_pts = w.get("moisture", 25)
    moisture_score = 0
    precip_14d = wx.get("precip_14d_val", 0)
    melt = wx.get("melt_score", 0)

    if precip_14d > 1.5:
        moisture_score += max_pts * 0.4
    elif precip_14d > 0.5:
        moisture_score += max_pts * 0.25
    elif precip_14d > 0.1:
        moisture_score += max_pts * 0.1

    moisture_score += max_pts * 0.5 * max(melt, 0)

    avg_sm = wx.get("avg_sm")
    if avg_sm is not None and 0.2 <= avg_sm <= 0.45:
        moisture_score += max_pts * 0.1

    scores["moisture"] = min(round(moisture_score), max_pts)

    # ── Elevation Score ──
    max_pts = w.get("elevation", 15)
    elev_score = 0
    if elev is not None:
        month = datetime.now().month
        base = mt["elev_base"]
        rng = mt["elev_range"]
        ideal_low = base + (month - 4) * 300
        ideal_high = ideal_low + rng
        if ideal_low <= elev <= ideal_high:
            elev_score = max_pts
        elif ideal_low - 500 <= elev <= ideal_high + 500:
            elev_score = round(max_pts * 0.6)
        elif ideal_low - 1000 <= elev <= ideal_high + 1000:
            elev_score = round(max_pts * 0.25)
        details["elevation"] = f"{elev:.0f}ft"
        details["ideal_band"] = f"{ideal_low:.0f}-{ideal_high:.0f}ft"
    scores["elevation"] = elev_score

    # ── Burn Quality Score (morels) or Forest Maturity (others) ──
    burn_key = "burn_quality" if mt["needs_fire"] else "forest_maturity"
    max_pts = w.get(burn_key, 30)
    burn_score = 0

    if mt["needs_fire"]:
        # Score the burn itself — recency + type + size
        fire_date = fire.get("date")
        if fire_date:
            try:
                fire_dt = datetime.strptime(fire_date, "%Y-%m-%d")
                months_ago = (datetime.now() - fire_dt).days / 30
                if months_ago <= 6:
                    burn_score += max_pts * 0.5
                elif months_ago <= 12:
                    burn_score += max_pts * 0.4
                elif months_ago <= 18:
                    burn_score += max_pts * 0.25
                elif months_ago <= 24:
                    burn_score += max_pts * 0.1
                details["burn_age"] = f"{months_ago:.0f}mo ago"
            except ValueError:
                burn_score += max_pts * 0.1
        elif fire.get("year"):
            try:
                yrs = datetime.now().year - int(fire["year"])
                burn_score += max_pts * max(0.4 - yrs * 0.15, 0.05)
                details["burn_age"] = f"{fire['year']}"
            except (ValueError, TypeError):
                pass

        # Burn type bonus
        burn_type = fire.get("pfirs_burn_type", "").lower()
        if "underburn" in burn_type or "broadcast" in burn_type:
            burn_score += max_pts * 0.3   # best for morels
        elif "hand pile" in burn_type or "pile" in burn_type:
            burn_score += max_pts * 0.2   # good, localized
        elif "machine pile" in burn_type:
            burn_score += max_pts * 0.15
        elif fire.get("is_rx"):
            burn_score += max_pts * 0.15  # generic RX
        else:
            burn_score += max_pts * 0.1   # wildfire

        # Size bonus — bigger burns = more area to search
        acres = fire.get("acres", 0)
        if acres >= 20:
            burn_score += max_pts * 0.15
        elif acres >= 5:
            burn_score += max_pts * 0.1
        elif acres > 0:
            burn_score += max_pts * 0.05

        details["burn_type"] = fire.get("pfirs_burn_type") or ("RX" if fire.get("is_rx") else "wildfire")
        details["burn_acres"] = f"{acres:.1f}ac"
    else:
        # Non-fire mushrooms: penalize recent burns, reward mature forest
        # Since we're scoring burn sites, these types score LOW here —
        # they'll show up as "avoid" markers on the map
        fire_date = fire.get("date")
        if fire_date:
            try:
                fire_dt = datetime.strptime(fire_date, "%Y-%m-%d")
                years_ago = (datetime.now() - fire_dt).days / 365
                if years_ago < 3:
                    burn_score = 0  # Avoid recent burns
                    details["forest_note"] = "AVOID: recent burn"
                elif years_ago < 10:
                    burn_score = round(max_pts * 0.3)
                    details["forest_note"] = "recovering"
                else:
                    burn_score = round(max_pts * 0.7)
                    details["forest_note"] = "mature regrowth"
            except ValueError:
                burn_score = round(max_pts * 0.2)
        else:
            burn_score = round(max_pts * 0.2)

    scores[burn_key] = min(round(burn_score), max_pts)

    # ── Season check ──
    month = datetime.now().month
    lo, hi = mt["season_months"]
    in_season = lo <= month <= hi
    details["in_season"] = "YES" if in_season else f"no (best {lo}-{hi})"
    if not in_season:
        # Out of season penalty — halve the total
        for k in scores:
            scores[k] = scores[k] // 2

    total = sum(scores.values())
    return {"total": total, "scores": scores, "details": details,
            "mushroom_type": mushroom_type}


# ── 7) Output ──────────────────────────────────────────────────────────────

def rating(score):
    if score >= 70: return "EXCELLENT", "purple"
    if score >= 55: return "GOOD", "green"
    if score >= 40: return "FAIR", "orange"
    if score >= 25: return "POOR", "lightred"
    return "SKIP", "red"


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

        print(f"\n{'─' * 78}")
        print(f"  {z['name']:45s}  {total:3d}/100  [{label}]")
        print(f"{'─' * 78}")
        score_parts = "  ".join(f"{k}: {s.get(k, 0)}/{mt['weights'][k]}" for k in weight_keys)
        print(f"  {score_parts}")

        lines = []
        if "avg_high_7d" in d:
            lines.append(f"Temps: {d['avg_high_7d']} hi / {d.get('avg_low_7d', '?')} lo")
        if "soil_temp" in d:
            lines.append(f"Soil: {d['soil_temp']}")
        if "precip_14d" in d:
            lines.append(f"Precip: {d['precip_14d']} (14d)")
        if "snow_status" in d:
            lines.append(f"Snow: {d['snow_status']}")
        if "elevation" in d:
            lines.append(f"Elev: {d['elevation']}")
        if "burn_type" in d:
            lines.append(f"Burn: {d['burn_type']} / {d.get('burn_acres', '?')} / {d.get('burn_age', '?')}")
        if "in_season" in d:
            lines.append(f"Season: {d['in_season']}")
        for line in lines:
            print(f"    {line}")


def build_map(results_by_type, fires, center=None):
    """
    Build map with per-mushroom-type layers.
    results_by_type: dict of {mushroom_type: [results]}
    """
    from folium.plugins import HeatMap

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

    # ── Per-mushroom-type layers ──
    for mtype, results in results_by_type.items():
        if not results:
            continue
        mt = MUSHROOM_TYPES[mtype]
        color = mt["color"]
        icon_letter = mt["icon"]

        # Heatmap for this type
        heat_data = [[r["zone"]["lat"], r["zone"]["lon"], r["result"]["total"] / 100.0]
                     for r in results if r["result"]["total"] > 30]
        if heat_data:
            HeatMap(
                heat_data, radius=25, blur=18, max_zoom=13,
                gradient={0.3: "blue", 0.5: "lime", 0.7: "yellow", 0.9: "orange", 1.0: "red"},
                name=f"{mt['label']} Heatmap",
                show=(mtype == "morel"),  # only morel heatmap on by default
            ).add_to(m)

        # Scored burn markers
        group = folium.FeatureGroup(
            name=f"{mt['label']} Sites",
            show=(mtype == "morel"),  # only morel on by default
        )
        for r in sorted(results, key=lambda x: x["result"]["total"], reverse=True)[:75]:
            z, res = r["zone"], r["result"]
            total = res["total"]
            label, rating_color = rating(total)
            d = res["details"]
            popup_lines = [f"<b>{z['name']}</b>",
                           f"<b>{mt['label']}: {total}/100 [{label}]</b>", ""]
            popup_lines += [f"{k}: {v}" for k, v in d.items() if isinstance(v, str)]
            popup = "<br>".join(popup_lines)

            size = 16 + total // 8
            folium.Marker(
                location=[z["lat"], z["lon"]],
                popup=folium.Popup(popup, max_width=320),
                tooltip=f"{icon_letter} {z['name']}: {total} [{label}]",
                icon=folium.DivIcon(
                    html=f'<div style="'
                         f'width:{size}px;height:{size}px;'
                         f'background:{rating_color};'
                         f'border:2px solid {color};'
                         f'border-radius:50%;'
                         f'box-shadow:0 0 4px rgba(0,0,0,0.4);'
                         f'display:flex;align-items:center;justify-content:center;'
                         f'font-size:9px;font-weight:bold;color:white;'
                         f'">{total}</div>',
                    icon_size=(size, size),
                    icon_anchor=(size // 2, size // 2),
                ),
            ).add_to(group)
        group.add_to(m)

    # ── Fire perimeter polygons ──
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

    # Legend
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
    <span style="color:purple;">&#9679;</span> Excellent (70+)<br>
    <span style="color:green;">&#9679;</span> Good (55-69)<br>
    <span style="color:orange;">&#9679;</span> Fair (40-54)<br>
    <span style="color:red;">&#9679;</span> Poor (&lt;40)<br>
    </div>"""
    m.get_root().html.add_child(folium.Element(legend))
    return m


def build_chart(results, output_prefix="morel"):
    rs = sorted(results, key=lambda r: r["result"]["total"], reverse=True)
    names = [r["zone"]["name"] for r in rs]
    t = [r["result"]["scores"]["temperature"] for r in rs]
    mo = [r["result"]["scores"]["moisture"] for r in rs]
    e = [r["result"]["scores"]["elevation"] for r in rs]
    f = [r["result"]["scores"]["fire"] for r in rs]

    fig, ax = plt.subplots(figsize=(14, 8))
    y = np.arange(len(names))
    h = 0.6
    ax.barh(y, t, height=h, label="Temperature (25)", color="#e74c3c")
    ax.barh(y, mo, height=h, left=t, label="Moisture (25)", color="#3498db")
    ax.barh(y, e, height=h, left=[a+b for a,b in zip(t,mo)], label="Elevation (20)", color="#2ecc71")
    ax.barh(y, f, height=h, left=[a+b+c for a,b,c in zip(t,mo,e)], label="Fire (30)", color="#f39c12")
    ax.set_yticks(y)
    ax.set_yticklabels(names, fontsize=9)
    ax.set_xlabel("Score (out of 100)")
    ax.set_title("Morel Foraging Potential — Truckee / Tahoe Area")
    ax.legend(loc="lower right")
    ax.set_xlim(0, 100)
    for x, c, a in [(70, "darkgreen", 0.5), (55, "green", 0.3), (40, "orange", 0.3)]:
        ax.axvline(x=x, color=c, linestyle="--", alpha=a)
    ax.invert_yaxis()
    plt.tight_layout()
    plt.savefig(f"{output_prefix}_scores.png", dpi=150)
    print(f"  Chart saved -> {output_prefix}_scores.png")


# ── Main ──────────────────────────────────────────────────────────────────

def score_burn(fire, mushroom_type="morel"):
    """Fetch weather + elevation for a burn location and score it."""
    lat = fire.get("centroid_lat")
    lon = fire.get("centroid_lon")
    if lat is None or lon is None:
        return None
    weather = get_weather(lat, lon)
    elev = get_elevation_ft(lat, lon)
    name = fire.get("name", "?")
    zone = {"name": name, "lat": lat, "lon": lon, "elevation_ft": elev}
    result = score_burn_site(fire, weather, elev, mushroom_type)
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
    """Dedupe fires that are essentially the same location."""
    unique = []
    for f in fires:
        lat, lon = f.get("centroid_lat"), f.get("centroid_lon")
        if lat is None or lon is None:
            continue
        dupe = False
        for u in unique:
            if haversine_km(lat, lon, u["centroid_lat"], u["centroid_lon"]) < min_dist_km:
                # Keep the one with more acres or more recent
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
    print("MUSHROOM FORAGING RECOMMENDER — Burn Site Analysis")
    print("=" * 60)
    CACHE_DIR.mkdir(exist_ok=True)

    # Step 1: Gather all fire/burn data
    print(f"\n[1/5] Fetching fire + treatment data ({SEARCH_RADIUS_KM}km)...")
    all_fires = gather_fire_data(ALDER_CREEK, SEARCH_RADIUS_KM)

    # Step 2: Filter to scoreable burn sites (need lat/lon, prefer RX burns)
    burns_to_score = [f for f in all_fires
                      if f.get("centroid_lat") and f.get("centroid_lon")
                      and f.get("is_rx")]
    burns_to_score = dedupe_burns(burns_to_score, min_dist_km=0.3)
    print(f"\n[2/5] {len(burns_to_score)} unique burn sites to score")

    # Step 3: Score each burn for each mushroom type (parallel weather/elev fetches)
    all_results = {}  # {mushroom_type: [results]}
    for mtype in MUSHROOM_TYPES:
        mt = MUSHROOM_TYPES[mtype]
        print(f"\n[3/5] Scoring {len(burns_to_score)} burns for {mt['label']}...")
        results = []
        with ThreadPoolExecutor(max_workers=6) as pool:
            futures = {pool.submit(score_burn, f, mtype): f for f in burns_to_score}
            for fut in as_completed(futures):
                try:
                    r = fut.result()
                    if r and r["result"]["total"] > 0:
                        results.append(r)
                except Exception:
                    pass
        results.sort(key=lambda r: r["result"]["total"], reverse=True)
        all_results[mtype] = results
        top3 = results[:3]
        if top3:
            print(f"  Top: {', '.join(f'{r['zone']['name']} ({r['result']['total']})' for r in top3)}")

    # Step 4: Reports
    print("\n[4/5] Reports...")
    for mtype, results in all_results.items():
        if results:
            print_report(results, mtype)

    # Step 5: Maps
    print("\n[5/5] Building maps...")

    # LOCAL MAP — 30mi from Alder Creek
    local_results = {
        mtype: [r for r in results
                if haversine_km(r["zone"]["lat"], r["zone"]["lon"],
                                ALDER_CREEK[0], ALDER_CREEK[1]) <= LOCAL_RADIUS_KM]
        for mtype, results in all_results.items()
    }
    m_local = build_map(local_results, all_fires, center=ALDER_CREEK)
    m_local.save("morel_local_map.html")
    local_ct = sum(len(v) for v in local_results.values())
    print(f"  morel_local_map.html ({local_ct} scored burns)")

    # BASIN MAP — full Greater Tahoe
    m_basin = build_map(all_results, all_fires, center=TAHOE_BASIN_CENTER)
    m_basin.save("morel_basin_map.html")
    basin_ct = sum(len(v) for v in all_results.values())
    print(f"  morel_basin_map.html ({basin_ct} scored burns)")

    # CSV — morel results (primary)
    morel_results = all_results.get("morel", [])
    summary = []
    for r in morel_results[:100]:  # top 100
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
        pd.DataFrame(summary).to_csv("morel_results.csv", index=False)
        print("  morel_results.csv")

    print(f"\nCache: {CACHE_DIR}/ (TTL: {CACHE_TTL_HOURS}h weather, {CACHE_TTL_FIRE_HOURS}h fire)")
    print("Done!")


if __name__ == "__main__":
    main()
