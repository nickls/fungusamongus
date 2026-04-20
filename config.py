"""
Configuration — all scoring parameters, thresholds, and weights.

To experiment with different scoring algorithms:
  1. Copy this file to config_experimental.py
  2. Tweak weights, recency curves, thresholds
  3. Run: python morel_finder.py --config config_experimental.py
"""

ALGO_VERSION = "0.4.0"
# 0.1.0 — Fixed zone scoring with fire proximity
# 0.2.0 — Burn-location-based scoring, PFIRS integration
# 0.3.0 — Moisture gate / soil temp trigger model, warming trend detection,
#          config-driven scoring, terrain (slope/aspect), refactored modules
# 0.4.0 — Soil temp as hard gate (not just weighted), warming trend is biggest
#          temp factor (35%), recency curve refined (0-2mo penalty), rating
#          thresholds tightened (80+=excellent, <50 hidden)

from pathlib import Path

# ── Geography ──────────────────────────────────────────────────────────────

ALDER_CREEK = (39.3187, -120.2125)  # Alder Creek Adventure Center
TAHOE_BASIN_CENTER = (39.1, -120.15)
SEARCH_RADIUS_KM = 120
LOCAL_RADIUS_KM = 48  # ~30mi

# ── Caching ────────────────────────────────────────────────────────────────

CACHE_DIR = Path("cache")
CACHE_TTL_HOURS = 6       # weather
CACHE_TTL_FIRE_HOURS = 24  # fire/elevation/terrain

# ── Rating thresholds ──────────────────────────────────────────────────────

RATINGS = [
    (80, "EXCELLENT", "purple"),   # diamond marker
    (70, "GOOD", "green"),         # diamond marker
    (50, "FAIR", "orange"),        # small dot
    (0,  "POOR", None),            # not rendered on map
]

DIAMOND_THRESHOLD = 70  # scores >= this get diamond markers
RENDER_THRESHOLD = 50   # scores below this are hidden from map

# ── Morel scoring profile ─────────────────────────────────────────────────
# All sub-scores are expressed as fractions (0.0-1.0) of their factor weight.
# This makes it easy to tune without recalculating point values.

MOREL_PROFILE = {
    "label": "Morels (Morchella)",
    "color": "#DAA520",
    "icon": "M",
    "needs_fire": True,
    "season_months": (4, 7),  # outside this range, all scores halved
    "notes": "Fire-associated. Best 3-12mo post-burn, moderate severity, "
             "after snowmelt when soil warms to 50F+.",

    # Factor weights (must sum to 100)
    #
    # Temperature system (threshold + rise) dominates TIMING (~50%)
    # Moisture system controls SUCCESS (~30%)
    # Burn quality is the OPPORTUNITY (~15%)
    # Sun aspect / terrain is local optimization (~5%)
    #
    # Sources:
    #   - NAMA: warming trends more predictive than rainfall for emergence
    #   - Nebraskaland: no fruiting below ~50F soil; drought kills flush
    #   - Iowa DNR: south-facing slopes first
    "weights": {
        "soil_threshold": 25,    # Hard gate: soil must be 48-55F
        "warming_trend": 25,     # Rising temps over 2-3 weeks = timing trigger
        "recent_moisture": 20,   # Rain/snowmelt in last 3-10 days = drives yield
        "burn_quality": 15,      # Recency, type, size of the burn itself
        "sun_aspect": 10,        # Slope + aspect = local soil warming rate
        "air_temp": 5,           # Proxy only — indirect via soil temps
    },

    # ── Soil temperature thresholds ──
    "soil_temp_ideal": (48, 58),   # sweet spot for fruiting
    "soil_temp_ok": (45, 66),      # acceptable but not prime
    "soil_temp_gate": 40,          # below this = hard block (score * 0.1)
    "soil_temp_approaching": 45,   # below ideal but above gate (score * 0.4)

    # ── Air temperature (proxy, low weight) ──
    "temp_ideal_high": (55, 75),
    "temp_ok_high": (45, 85),
    "temp_ideal_low": (30, 50),

    # ── Moisture sub-scoring ──
    "precip_thresholds": [       # (min_inches in last 10 days, fraction_of_weight)
        (1.5, 0.50),
        (0.5, 0.30),
        (0.1, 0.10),
    ],
    "melt_weight": 0.40,         # snowmelt status
    "soil_moisture_ideal": (0.20, 0.45),
    "soil_moisture_weight": 0.10,

    # ── Elevation (folded into sun_aspect for seasonal timing) ──
    "elev_base": 4500,
    "elev_range": 2500,
    "elev_shift_per_month": 300,
    "elev_scoring": {
        "in_band": 1.0,
        "within_500ft": 0.6,
        "within_1000ft": 0.25,
    },

    # ── Burn quality sub-scoring ──
    # Recency curve: list of (max_months, fraction_of_weight)
    # Evaluated in order — first match wins
    "recency_curve": [
        (2,  0.30),   # 0-2 months: too fresh
        (8,  0.50),   # 3-8 months: prime window
        (14, 0.40),   # 9-14 months: still good
        (20, 0.20),   # 15-20 months: declining
        (30, 0.10),   # 21-30 months: marginal
        # >30 months: 0
    ],
    # Burn type: maps burn_type string -> fraction of weight
    "burn_type_scores": {
        "underburn": 0.30,
        "broadcast": 0.30,
        "hand pile": 0.20,
        "pile": 0.20,
        "machine pile": 0.15,
        "rx_generic": 0.15,  # fallback for unspecified RX
        "wildfire": 0.10,
    },
    # Acreage curve: list of (min_acres, fraction)
    "acreage_curve": [
        (20, 0.15),
        (5,  0.10),
        (0,  0.05),
    ],

    # ── Terrain sub-scoring ──
    "aspect_scores": {
        "south": 3,    # 135-225 deg
        "east_west": 1,  # 90-270 deg
        "north": 0,
    },
    "slope_scores": {
        "moderate": 2,  # 5-25 deg
        "flat": 1,      # <5 deg
        "steep": 0,     # >25 deg
    },
}

# ── Mushroom type registry ─────────────────────────────────────────────────
# Only morel is scored today. Others defined for future candidate generation.

MUSHROOM_TYPES = {
    "morel": MOREL_PROFILE,
    "chanterelle": {
        "label": "Chanterelles (Cantharellus)",
        "color": "#FF8C00",
        "icon": "C",
        "needs_fire": False,
        "season_months": (7, 10),
        "weights": {"temperature": 25, "moisture": 35, "elevation": 15, "forest_maturity": 25},
        "temp_ideal_high": (65, 85),
        "temp_ok_high": (55, 95),
        "temp_ideal_low": (45, 60),
        "soil_temp_ideal": (55, 70),
        "elev_base": 4000,
        "elev_range": 3000,
        "notes": "Mature conifer/hardwood forest. NOT fire-associated.",
    },
    "porcini": {
        "label": "King Bolete / Porcini (Boletus)",
        "color": "#8B4513",
        "icon": "P",
        "needs_fire": False,
        "season_months": (6, 10),
        "weights": {"temperature": 25, "moisture": 30, "elevation": 20, "forest_maturity": 25},
        "temp_ideal_high": (60, 80),
        "temp_ok_high": (50, 90),
        "temp_ideal_low": (40, 55),
        "soil_temp_ideal": (50, 65),
        "elev_base": 5000,
        "elev_range": 3000,
        "notes": "Mycorrhizal with conifers. Needs rain events + warm days.",
    },
    "matsutake": {
        "label": "Matsutake (Tricholoma)",
        "color": "#CD853F",
        "icon": "T",
        "needs_fire": False,
        "season_months": (9, 11),
        "weights": {"temperature": 20, "moisture": 30, "elevation": 20, "forest_maturity": 30},
        "temp_ideal_high": (50, 70),
        "temp_ok_high": (40, 75),
        "temp_ideal_low": (30, 50),
        "soil_temp_ideal": (40, 55),
        "elev_base": 5000,
        "elev_range": 3000,
        "notes": "Pine/fir, sandy soil. Late season, first fall rains.",
    },
}
