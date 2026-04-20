"""USGS elevation, slope, and aspect."""

import math

from utils.cache import cache_key, cache_get, cache_set
from utils.http import fetch_json
from config import CACHE_TTL_FIRE_HOURS


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


def get_slope_aspect(lat: float, lon: float) -> dict:
    """
    Compute slope (degrees) and aspect (0-360, 0=N, 180=S) by sampling
    4 elevation points ~55m from center.
    """
    key = cache_key("slope", lat=round(lat, 4), lon=round(lon, 4))
    cached = cache_get(key, CACHE_TTL_FIRE_HOURS)
    if cached:
        return cached

    offset = 0.0005  # ~55m
    north = get_elevation_ft(lat + offset, lon)
    south = get_elevation_ft(lat - offset, lon)
    east = get_elevation_ft(lat, lon + offset)
    west = get_elevation_ft(lat, lon - offset)

    if None in (north, south, east, west):
        result = {"slope": None, "aspect": None}
        cache_set(key, result)
        return result

    dist_ft = offset * 111000 * 3.281
    dx = (east - west) / (2 * dist_ft * math.cos(math.radians(lat)))
    dy = (north - south) / (2 * dist_ft)

    slope_deg = math.degrees(math.atan(math.sqrt(dx**2 + dy**2)))
    aspect_deg = math.degrees(math.atan2(-dx, dy)) % 360

    result = {"slope": round(slope_deg, 1), "aspect": round(aspect_deg)}
    cache_set(key, result)
    return result


def aspect_label(aspect: float | None) -> str:
    if aspect is None:
        return "?"
    dirs = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    return dirs[int((aspect + 22.5) % 360 / 45)]


def get_best_aspect(lat: float, lon: float, offset_m: float = 150) -> dict:
    """
    Sample 5 points (center + 4 cardinal at offset_m) and return the
    slope/aspect dict with the most south-facing aspect. A burn with
    ANY south-facing terrain should get credit.
    """
    deg = offset_m / 111000
    points = [
        (lat, lon),
        (lat + deg, lon),
        (lat - deg, lon),
        (lat, lon + deg),
        (lat, lon - deg),
    ]
    results = [get_slope_aspect(p[0], p[1]) for p in points]

    def south_score(r):
        a = r.get("aspect")
        if a is None:
            return -999
        # Closer to 180 (south) = better
        return -abs(a - 180)

    best = max(results, key=south_score)

    # Also store centroid for reference
    centroid = results[0]
    best["aspect_centroid"] = centroid.get("aspect")
    best["slope_centroid"] = centroid.get("slope")
    return best
