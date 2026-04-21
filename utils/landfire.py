"""LANDFIRE Existing Vegetation Type (EVT) lookup.

Queries the LANDFIRE LF2024 ImageServer to get vegetation type for a lat/lon
point, then maps the EVT code to a morel suitability score.

Uses the same cache pattern as elevation.py — results are cached locally since
vegetation doesn't change between runs.
"""

from utils.cache import cache_key, cache_get, cache_set
from utils.http import fetch_json
from config import CACHE_TTL_FIRE_HOURS

EVT_URL = (
    "https://lfps.usgs.gov/arcgis/rest/services/"
    "Landfire_LF2024/LF2024_EVT_CONUS/ImageServer/identify"
)

# LANDFIRE EVT codes → vegetation name + morel suitability (0.0-1.0)
#
# Codes are NatureServe Ecological System IDs from LANDFIRE LF2024.
# Suitability reflects how likely a burn in this vegetation type produces morels:
#   1.0 = prime (mixed conifer, true fir)
#   0.8 = good (Jeffrey/ponderosa pine, aspen-conifer)
#   0.5 = marginal (subalpine, lodgepole)
#   0.2 = poor (pinyon-juniper, single-species)
#   0.0 = none (sagebrush, grassland, water, developed)
#
# Sources:
#   - Pilz et al. 2007: morels fruit best in mixed conifer with moderate severity burns
#   - NAMA guidelines: true fir + Douglas fir stands are highest producers
#   - Local knowledge: Jeffrey pine burns near Truckee produce well
#
EVT_LOOKUP = {
    # ── Mixed Conifer (PRIME for morels) ──
    7027: ("Mediterranean California Mesic Mixed Conifer Forest and Woodland", 1.0),
    7028: ("Mediterranean California Dry-Mesic Mixed Conifer Forest and Woodland", 1.0),
    7058: ("Mediterranean California Mixed Evergreen Forest", 0.9),
    7080: ("Inter-Mountain Basins Aspen-Mixed Conifer Forest and Woodland", 0.9),

    # ── Pine-dominant (GOOD) ──
    7031: ("California Montane Jeffrey Pine-(Ponderosa Pine) Woodland", 0.8),
    7032: ("Mediterranean California Lower Montane Conifer Forest and Woodland", 0.8),

    # ── True Fir (GOOD) ──
    7033: ("Mediterranean California Red Fir Forest", 0.8),

    # ── Subalpine / Lodgepole (MARGINAL — cold, short season) ──
    7044: ("Sierra Nevada Subalpine Lodgepole Pine Forest and Woodland", 0.5),
    7098: ("Mediterranean California Subalpine Woodland", 0.4),
    7105: ("Northern California Mesic Subalpine Woodland", 0.4),
    7011: ("East Cascades Mesic Montane Mixed-Conifer Forest and Woodland", 0.7),

    # ── Pinyon-Juniper / Dry woodland (POOR) ──
    7126: ("Great Basin Pinyon-Juniper Woodland", 0.2),

    # ── Shrubland / Sagebrush (NO morels) ──
    7299: ("Inter-Mountain Basins Big Sagebrush Shrubland", 0.0),
    7300: ("Inter-Mountain Basins Big Sagebrush Steppe", 0.0),
    7195: ("Great Basin Xeric Mixed Sagebrush Shrubland", 0.0),
    7063: ("Rocky Mountain Lower Montane-Foothill Shrubland", 0.1),

    # ── Non-vegetated ──
    7292: ("Open Water", 0.0),
    7296: ("Barren", 0.0),
    7967: ("Recently Burned", 0.7),  # trust the burn data instead
    7298: ("Quarries-Strip Mines-Gravel Pits", 0.0),

    # ── Developed / Agriculture ──
    9125: ("Developed-Upland Deciduous Forest", 0.1),
    9213: ("Developed-Medium Intensity", 0.0),
    9272: ("Developed-Roads", 0.0),
    9308: ("Developed-Open Space", 0.0),
    9503: ("Developed-Upland Herbaceous", 0.0),
}

# Default suitability for codes not in our lookup
EVT_DEFAULT_SUITABILITY = 0.3


def get_evt(lat: float, lon: float) -> dict:
    """
    Query LANDFIRE EVT for a point. Returns:
      {"evt_code": 7028, "evt_name": "Med CA Dry-Mesic Mixed Conifer...", "evt_suitability": 1.0}
    """
    key = cache_key("evt", lat=round(lat, 4), lon=round(lon, 4))
    cached = cache_get(key, CACHE_TTL_FIRE_HOURS)
    if cached:
        return cached

    params = {
        "geometry": f'{{"x":{lon},"y":{lat},"spatialReference":{{"wkid":4326}}}}',
        "geometryType": "esriGeometryPoint",
        "returnGeometry": "false",
        "returnCatalogItems": "false",
        "f": "json",
    }
    data = fetch_json(EVT_URL, params)

    result = {"evt_code": None, "evt_name": "Unknown", "evt_suitability": EVT_DEFAULT_SUITABILITY}

    if data:
        val = data.get("value", "NoData")
        if val != "NoData":
            try:
                code = int(val)
                result["evt_code"] = code
                if code in EVT_LOOKUP:
                    result["evt_name"] = EVT_LOOKUP[code][0]
                    result["evt_suitability"] = EVT_LOOKUP[code][1]
                else:
                    result["evt_name"] = f"EVT {code} (unmapped)"
            except (ValueError, TypeError):
                pass

    cache_set(key, result)
    return result


def evt_score_for_morels(evt_suitability: float) -> float:
    """
    Convert EVT suitability (0-1) to a score contribution.
    This is used as a multiplier on the burn_quality potential component.
    Mixed conifer = 1.0x (no penalty), sagebrush = 0.0x (total penalty).
    """
    return evt_suitability
