"""
Configuration — all scoring parameters, thresholds, and weights.

To experiment with different scoring algorithms:
  1. Copy this file to config_experimental.py
  2. Tweak weights, recency curves, thresholds
  3. Run: python morel_finder.py --config config_experimental.py
"""

ALGO_VERSION = "0.8.2"
# 0.8.2 — Field-anchored PAST_PRIME thresholds for morel: grow_soil_max raised
#          58F → 68F (Unit 2.3 5lb harvest at 60s validates); past_prime_max
#          75F → 78F. Taper softened: 2-day grace before any penalty, then 8%
#          per day with 0.50 floor (was 12%/day, 0.30 floor). A site touching
#          60F a couple days no longer drops out of the "ready" rating.
# 0.8.1 — PAST_PRIME status: warming-trigger species (morel) above grow_max
#          (58F) but below past_prime_max (75F) now classified as PAST_PRIME
#          instead of GROW. Deterministic readiness taper (max(0.30, 1 - 0.12 *
#          past_prime_recent)) gives a smooth heat-decline instead of cliff at
#          75F. SPA: smooth diamond-size taper from 60→90 (replaces 70/75/90
#          step function), DIAMOND_THRESHOLD lowered to 60. PAST_PRIME shown
#          amber on detail timeline.
# 0.8.0 — Multi-species scaffolding. Porcini biology fully wired: thermal_signal
#          ("warming"|"cooling") in classify_day, freeze_is_bad gate, season-priming
#          (had_thermal_peak) for cooling-trigger species, config-driven ratchet
#          decay/lookback. Per-mushroom-type output paths (morel-latest.json,
#          porcini-latest.json) with morel writing legacy filenames for SPA
#          backward-compat. Phase B (porcini candidate generation) and C (SPA
#          toggle) still pending.
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

DIAMOND_THRESHOLD = 60  # scores >= this get diamond markers (smooth taper above)
RENDER_THRESHOLD = 0    # show everything — filter sliders handle visibility

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

    # ── Phase classification biology ──
    "thermal_signal": "warming",       # spring-emergence species
    "freeze_is_bad": True,             # primordia damaged by freeze after warmth
    "thermal_peak_threshold": 45,      # tracks "had_warmth" in build_timeline
    # ── Soil temp bands for classify_day ──
    # Field-anchored: Unit 2.3 produced 4-5lbs at 6mo with soil hitting 60s
    # in late April. 58F as grow_max was too tight — morels fruit well into
    # the mid-60s. PAST_PRIME band (68-78F) is "declining but harvestable",
    # and past_prime_max (78F) is the hard "season over" cliff.
    "start_soil_min": 43,
    "start_soil_max": 50,
    "grow_soil_min": 45,
    "grow_soil_max": 68,               # raised from default 58 per field data
    "past_prime_max": 78,              # raised from default 75
    "bad_freeze_threshold": 32,
    "bad_snow_depth": 24,
    # ── Anti-whiplash ratchet ──
    "ratchet_decay": 0.93,             # 9.5-day half-life — observed morel persistence
    "ratchet_lookback": 14,

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
    # 4-5lbs harvested at 6mo (Unit 2.3 Underburn) — solidly inside the prime
    # window. ~2lbs at 18mo (Waddle Ranch RX) — declining, as original curve
    # predicted. Reverted to original after misattribution was corrected on
    # 2026-05-02. Note: moisture/age confounded across the two sites.
    "recency_curve": [
        (2,  0.30),   # 0-2 months: too fresh
        (8,  0.50),   # 3-8 months: prime window (FR-002b confirms)
        (14, 0.40),   # 9-14 months: still good
        (20, 0.20),   # 15-20 months: declining (FR-002a: ~2lbs at 18mo)
        (30, 0.10),   # 21-30 months: marginal
        # >30 months: 0
    ],
    # Burn type: maps burn_type string -> fraction of weight
    # Machine pile > hand pile > underburn for morels.
    # Mechanism: duff removal + mineral soil exposure + root death + reduced competition.
    # Machine pile = deep soil heating, full duff consumption → strongest trigger but patchy.
    # Hand pile = similar but weaker, smaller footprint, more numerous.
    # Underburn = generally poor — low duff consumption, minimal soil heating, trees survive.
    # Field validation 2026-05-02: Unit 2.3 underburn produced 4-5lbs at 6mo
    # (FR-002b). Underburns are highly severity-dependent — ranges from FR-001
    # (T27 "patchy, shallow", 0 morels) to FR-002b (4-5lbs). Without dNBR
    # severity data we treat them as moderate-uncertain.
    "burn_type_scores": {
        "machine pile": 0.45,  # deepest soil heating, highest single-yield potential
        "hand pile": 0.30,     # moderate severity, broader spatial coverage
        "pile": 0.30,          # generic pile = assume hand pile
        "broadcast": 0.30,     # moderate severity, variable
        "rx_generic": 0.20,    # unspecified RX — assume moderate
        "wildfire": 0.35,      # best when moderate severity, variable
        "underburn": 0.25,     # variable: from 0 (T27) to 4-5lbs (Unit 2.3)
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
        "label": "King Bolete / Porcini (Boletus edulis)",
        "color": "#8B4513",
        "icon": "P",
        "needs_fire": False,
        "season_months": (7, 11),  # July through November in Sierra
        # Catalog has ~10k stand candidates across the Sierra; cap at top-N
        # by static potential before weather scoring to keep output JSON
        # manageable. The suitability raster overlay covers the rest visually.
        "max_scored_sites": 500,
        # Catalog + overlay paths — porcini owns these; spring_king reuses them
        # via the same paths since they share habitat (mature conifer stands).
        "catalog_path": "data/porcini_sites.json",
        "overlay_path": "docs/data/porcini-overlay.png",
        "notes": "Mycorrhizal with mature conifers (red fir, mixed conifer, Jeffrey "
                 "pine). Fall-fruiting — triggered by cooling soils + sustained "
                 "moisture after late-summer warmth. Flushes last weeks, not days.",

        # ── Phase classification biology (cooling-trigger) ──
        "thermal_signal": "cooling",       # vs morel "warming"
        "freeze_is_bad": False,            # tolerate light frost; freeze isn't damage
        "thermal_peak_threshold": 60,      # need to hit 60F+ during the season
        "start_soil_min": 50,              # too cold below this
        "start_soil_max": 60,              # cooling INTO this range triggers START
        "grow_soil_min": 50,
        "grow_soil_max": 65,               # above 65F = too hot for fruiting
        "past_prime_max": 70,              # above 70F = season over
        "bad_freeze_threshold": 25,        # hard freeze; lower than morel's 32F
        "bad_snow_depth": 12,              # less snow tolerance than morel

        # ── Anti-whiplash ratchet (longer persistence than morel) ──
        "ratchet_decay": 0.95,             # vs morel 0.93 — flushes last weeks
        "ratchet_lookback": 21,            # vs morel 14

        # ── Potential factor weights (must sum to 100) ──
        # No burn_quality (mycorrhizal, gated by needs_fire=False).
        # Vegetation dominates — porcini are obligate symbionts with conifers.
        "potential_weights": {
            "burn_quality": 0,
            "vegetation": 50,
            "elevation": 25,
            "aspect": 5,
            "season": 20,
            "freeze_damage": 0,
        },

        # ── Air temp ranges (proxy, low weight) ──
        "temp_ideal_high": (60, 80),
        "temp_ok_high": (50, 90),
        "temp_ideal_low": (40, 55),
        "soil_temp_ideal": (50, 65),
        "elev_base": 5000,
        "elev_range": 3000,
    },
    "spring_king": {
        "label": "Spring King (Boletus rex-veris)",
        "color": "#A0522D",
        "icon": "S",
        "needs_fire": False,
        # Spring/early summer fruiting near snowmelt at higher elevations
        "season_months": (5, 7),
        "max_scored_sites": 500,
        # Reuses porcini's catalog + overlay — same habitat (mature conifer
        # stands), just a different elevation band and biology.
        "catalog_path": "data/porcini_sites.json",
        # Dedicated overlay rendered with the spring_king-specific EVT
        # weights below, so the basin tint reflects spring-king habitat,
        # not porcini's denser-forest preference.
        "overlay_path": "docs/data/spring_king-overlay.png",
        "notes": "Sierra spring porcini. Mycorrhizal with conifers but favors "
                 "OPEN stands (lodgepole, parkland Jeffrey pine, subalpine "
                 "woodland) over dense mixed conifer. Fruits at higher elevations "
                 "than fall king (B. edulis), triggered by snowmelt + warming "
                 "soils — biologically more like morel than fall porcini.",

        # Per-species EVT suitability override — spring king prefers open,
        # sunny conifer over closed-canopy mixed conifer, so we bump open-
        # canopy types up and trim dense mixed conifer slightly. Codes not
        # listed fall through to the global EVT_LOOKUP value.
        "evt_lookup_overrides": {
            7044: 0.95,  # Lodgepole pine — open, snowmelt zone, classic SK habitat
            7098: 0.85,  # Subalpine woodland — open at high elev
            7105: 0.85,  # Northern California Mesic Subalpine
            7031: 0.95,  # Jeffrey pine — often parkland, very open
            7033: 0.85,  # Red fir — suitable but denser than lodgepole
            7032: 0.85,  # Lower montane conifer
            7027: 0.75,  # Mesic mixed conifer — OK but often too dense
            7028: 0.80,  # Dry-mesic mixed conifer — slightly more open
            7080: 0.80,  # Aspen-mixed conifer
            7058: 0.65,  # Mixed evergreen — too closed-canopy
        },

        # ── Phase classification biology (warming-trigger like morel) ──
        "thermal_signal": "warming",
        "freeze_is_bad": True,             # primordia damaged by spring frost
        "thermal_peak_threshold": 42,      # snowmelt → soil hits 42F is the "primed" cue
        # Cooler soil range than morel — spring king fruits in colder soils
        # near melting snowbanks
        "start_soil_min": 38,
        "start_soil_max": 48,
        "grow_soil_min": 40,
        "grow_soil_max": 55,
        "past_prime_max": 65,              # declines fast once midsummer hits
        "bad_freeze_threshold": 28,
        "bad_snow_depth": 18,              # tolerates more snow than fall king

        # ── Anti-whiplash ratchet ──
        "ratchet_decay": 0.93,             # similar to morel — spring flushes are short
        "ratchet_lookback": 14,

        # ── Potential factor weights (must sum to 100) ──
        "potential_weights": {
            "burn_quality": 0,
            "vegetation": 45,
            "elevation": 25,               # higher elev band matters more
            "aspect": 10,                  # snowmelt timing varies by aspect
            "season": 20,
            "freeze_damage": 0,
        },

        # ── Air temp ranges (proxy, low weight) ──
        "temp_ideal_high": (50, 70),
        "temp_ok_high": (40, 80),
        "temp_ideal_low": (28, 45),
        "soil_temp_ideal": (40, 55),
        # Higher elevation band — snowmelt zone in late spring
        "elev_base": 5500,
        "elev_range": 3500,
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
