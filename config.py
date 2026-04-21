"""
Configuration — all scoring parameters, thresholds, and weights.

To experiment with different scoring algorithms:
  1. Copy this file to config_experimental.py
  2. Tweak weights, recency curves, thresholds
  3. Run: python morel_finder.py --config config_experimental.py
"""

ALGO_VERSION = "0.7.1"
# 0.7.1 — LANDFIRE EVT vegetation scoring (15pts in potential), burn type fix
#          (machine pile > wildfire > hand pile > underburn), UI clarity pass,
#          vegetation overlay + legend, detail page "Where to look" recommendations,
#          first field report (T27 underburn — negative)
# 0.1.0 — Fixed zone scoring with fire proximity
# 0.2.0 — Burn-location-based scoring, PFIRS integration
# 0.3.0 — Moisture gate / soil temp trigger model, warming trend detection,
#          config-driven scoring, terrain (slope/aspect), refactored modules
# 0.4.0 — Soil temp as hard gate (not just weighted), warming trend is biggest
#          temp factor (35%), recency curve refined (0-2mo penalty), rating
#          thresholds tightened (80+=excellent, <50 hidden)
# 0.5.0 — 6-factor model (soil threshold, warming trend, moisture, burn quality,
#          sun/aspect, air temp). Per-day scoring (days 0-7) with proper windowing.
#          SPA frontend with Leaflet, day picker, filter sliders, heatmap toggle.
#          Linear regression for trend. Soil gate applies to all factors.
#          39 unit tests. Bug fixes: target window, gate application, recency curve.

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
        "soil_threshold": 25,    # Hard gate: soil must be 45-58F (literature: 43F onset)
        "soil_gdd": 25,          # Cumulative soil degree-days (365-580 GDD = onset)
        "recent_moisture": 20,   # Rain/snowmelt in last 3-10 days = drives yield
        "burn_quality": 15,      # Recency, type, size of the burn itself
        "sun_aspect": 10,        # Slope + aspect = local soil warming rate
        "air_temp": 5,           # Proxy only — indirect via soil temps
    },

    # ── Soil temperature thresholds ──
    # Literature: fruiting begins above 43F (6.1C). Ideal 50-55F.
    "soil_temp_ideal": (45, 58),   # lowered from 48 per research
    "soil_temp_ok": (43, 66),      # 43F is the documented minimum
    "soil_temp_gate": 38,          # hard block below this
    "soil_temp_approaching": 43,   # documented onset temperature

    # ── Soil GDD (Growing Degree Days) ──
    # Literature: onset at 365-580 GDD above 0C (32F) over ~30 days
    # We compute from 30-day air temp history (proxy) + 14-day forecast soil temps
    "gdd_base_temp": 32,           # base temp in F (0C)
    "gdd_onset": 365,              # GDD where fruiting begins
    "gdd_peak": 580,               # GDD where fruiting is at peak
    "gdd_max_window_days": 44,     # 30 days hist + 14 days forecast

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
    # Machine pile > hand pile > underburn for morels.
    # Mechanism: duff removal + mineral soil exposure + root death + reduced competition.
    # Machine pile = deep soil heating, full duff consumption → strongest trigger but patchy.
    # Hand pile = similar but weaker, smaller footprint, more numerous.
    # Underburn = generally poor — low duff consumption, minimal soil heating, trees survive.
    "burn_type_scores": {
        "machine pile": 0.45,  # highest yield potential, very localized microclusters
        "hand pile": 0.30,     # moderate probability, better spatial coverage
        "pile": 0.30,          # generic pile = assume hand pile
        "broadcast": 0.25,     # moderate severity, variable
        "rx_generic": 0.15,    # unspecified RX — assume moderate
        "wildfire": 0.35,      # best when moderate severity, variable — needs dNBR to score accurately
        "underburn": 0.05,     # near-zero unless co-occurring with high-severity patches
    },
    # Acreage curve: list of (min_acres, fraction)
    "acreage_curve": [
        (20, 0.15),
        (5,  0.10),
        (0,  0.05),
    ],

    # ── Terrain sub-scoring ──
    # Month-adjusted aspect: south matters more early, north catches up late
    "aspect_month_weights": {
        4: {"south": 5, "east_west": 2, "north": 0},  # April
        5: {"south": 4, "east_west": 3, "north": 1},  # May
        6: {"south": 3, "east_west": 3, "north": 2},  # June
        7: {"south": 2, "east_west": 3, "north": 3},  # July
    },
    "aspect_default": {"south": 3, "east_west": 1, "north": 0},
    "slope_scores": {
        "moderate": 2,  # 5-25 deg
        "flat": 1,      # <5 deg
        "steep": 0,     # >25 deg
    },

    # ── Potential weights (site quality — stable across days) ──
    # Must sum to 100. Used by phase_scoring.score_potential().
    "potential_weights": {
        "burn_quality": 40,   # recency, type, size
        "elevation": 15,      # seasonal band
        "aspect": 10,         # south-facing advantage
        "vegetation": 15,     # LANDFIRE EVT — mixed conifer best
        "season": 10,         # Apr-Jul
        "freeze_damage": 10,  # penalty if freeze killed primordia
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
