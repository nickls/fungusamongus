"""
Phase-based scoring model (v0.7.0).

Replaces the single weighted score with a biological model:
- Each day is classified as START / START_GROW / GROW / PAST_PRIME / BAD
- Readiness is computed from a rolling window: enough START days + enough GROW days
- Potential is site quality (burn, elevation, aspect)

The readiness scoring uses coefficients learned from 21 labeled scenarios
via logistic regression.
"""

import math
from datetime import datetime

import numpy as np

from config import MUSHROOM_TYPES


# ── Daily status classification ──

def classify_day(soil_temp, prev_soil_temp, precip, snow_depth, had_thermal_peak,
                 config, prev_status=None):
    """
    Classify a single day's conditions into START / START_GROW / GROW /
    PAST_PRIME / BAD. Returns (status, reason) tuple.

    PAST_PRIME = soil above grow_max but below past_prime_max. For warming-
    trigger species (morel) the flush is declining but still harvestable.
    For cooling-trigger species (porcini) we instead return BAD — they are
    waiting for the soil to cool back into range.

    `thermal_signal` config key controls direction: "warming" (morel, spring
    emergence) or "cooling" (porcini, fall fruiting). For cooling-trigger
    species, fruiting also requires `had_thermal_peak` — the soil must have
    reached the season's warm peak before cooling can trigger fruiting.
    """
    start_min = config.get("start_soil_min", 43)
    start_max = config.get("start_soil_max", 50)
    grow_min = config.get("grow_soil_min", 45)
    grow_max = config.get("grow_soil_max", 58)
    past_prime_max = config.get("past_prime_max", 75)
    freeze = config.get("bad_freeze_threshold", 32)
    bad_snow = config.get("bad_snow_depth", 24)
    thermal_signal = config.get("thermal_signal", "warming")
    freeze_is_bad = config.get("freeze_is_bad", True)

    soil_str = f"{soil_temp:.0f}F" if soil_temp is not None else "?"

    if soil_temp is None:
        return "BAD", "no soil temp data"

    # Freeze damage — only meaningful for warming-trigger species whose
    # primordia are killed by spring frost. Porcini tolerate light frost.
    if freeze_is_bad and soil_temp <= freeze and had_thermal_peak:
        return "BAD", f"freeze damage ({soil_str} after warmth)"

    # Deep snowpack
    if snow_depth is not None and snow_depth > bad_snow:
        return "BAD", f"deep snow ({snow_depth:.0f}in)"

    # Too cold for anything
    if soil_temp < start_min:
        return "BAD", f"too cold ({soil_str}, need {start_min}F+)"

    # Way too hot — truly done
    if soil_temp > past_prime_max:
        return "BAD", f"too hot ({soil_str}, max {past_prime_max}F)"

    if prev_soil_temp is not None:
        is_warming = soil_temp > prev_soil_temp
        is_cooling = soil_temp < prev_soil_temp
    else:
        is_warming = is_cooling = False
    favorable_trend = is_warming if thermal_signal == "warming" else is_cooling
    trend_word = "warming" if thermal_signal == "warming" else "cooling"

    in_start_range = start_min <= soil_temp <= start_max
    in_grow_range = grow_min <= soil_temp <= grow_max
    in_past_prime = grow_max < soil_temp <= past_prime_max
    has_moisture = precip > 0.1 or (snow_depth is not None and 0 < snow_depth <= bad_snow)

    # Anti-oscillation: if previous day was BAD and we just crossed back into range,
    # require trend confirmation (not just a single day crossing).
    recovering_from_bad = prev_status == "BAD"

    # For cooling-trigger species, the mycelium needs heat-shock priming first.
    # Without prior thermal peak, cool wet days are out-of-season, not fruiting.
    season_primed = had_thermal_peak if thermal_signal == "cooling" else True

    # START: soil moving in favorable direction into initiation range + moisture
    if has_moisture and season_primed:
        if in_start_range and favorable_trend and not recovering_from_bad:
            if in_grow_range:
                return "START_GROW", f"{trend_word} + moisture ({soil_str}, {precip:.1f}in rain)"
            return "START", f"{trend_word} into range + moisture ({soil_str})"
        # Heavy-rain trigger in grow range. For warming-trigger species this
        # works alone (rain primes the flush). For cooling-trigger species
        # the soil must also actually be cooling — warm rain mid-summer
        # doesn't trigger porcini.
        if in_grow_range and precip > 0.3 and (thermal_signal == "warming" or favorable_trend):
            return "START_GROW", f"rain trigger in grow range ({soil_str}, {precip:.1f}in)"

    # GROW: in the sustained growth range
    if in_grow_range:
        return "GROW", f"soil in grow range ({soil_str})"

    # Past prime: above grow_max but below past_prime_max
    # Warming-trigger species taper down (still harvestable, declining yield).
    # Cooling-trigger species are waiting for the soil to cool back into range.
    if in_past_prime:
        if thermal_signal == "warming":
            return "PAST_PRIME", f"past prime — declining ({soil_str})"
        return "BAD", f"too warm — waiting for cooling ({soil_str})"

    # In start range but no favorable trend or no moisture — marginal
    if in_start_range:
        if favorable_trend:
            return "START", f"{trend_word} but dry ({soil_str})"
        return "GROW", f"holding in range ({soil_str})"

    return "BAD", f"soil {soil_str} out of range"


def build_timeline(weather, config):
    """
    Build a 44-day timeline of daily statuses from weather data.
    Returns (timeline, reasons) — both lists of 44 strings.
    """
    hist_soil = weather.get("hist_soil_temp", [])
    fc_soil = weather.get("forecast_soil_temp", [])
    all_soil = list(hist_soil) + list(fc_soil)

    hist_precip = weather.get("hist_precip", [])
    # Pad precip to 44 days (we don't have forecast precip)
    all_precip = list(hist_precip) + [0] * max(0, 44 - len(hist_precip))

    fc_snow = weather.get("forecast_snow_depth", [])
    # Snow: pad 30 nulls for history (we don't have it) + 14 forecast
    all_snow = [None] * 30 + list(fc_snow) + [None] * max(0, 44 - 30 - len(fc_snow))

    thermal_peak_threshold = config.get("thermal_peak_threshold", 45)

    timeline = []
    reasons = []
    had_thermal_peak = False
    prev_status = None

    for i in range(min(44, len(all_soil))):
        soil = all_soil[i]
        prev = all_soil[i - 1] if i > 0 else None
        precip = all_precip[i] if i < len(all_precip) else 0
        snow = all_snow[i] if i < len(all_snow) else None

        if soil is not None and soil >= thermal_peak_threshold:
            had_thermal_peak = True

        status, reason = classify_day(soil, prev, precip, snow if snow is not None else 0,
                                      had_thermal_peak, config, prev_status)
        timeline.append(status)
        reasons.append(reason)
        prev_status = status

    # Pad to 44 if needed
    while len(timeline) < 44:
        timeline.append("BAD")
        reasons.append("")

    return timeline, reasons


# ── Feature extraction from timeline ──

def extract_features(timeline, weather, target_day=30, config=None):
    """
    Extract numeric features from a timeline for scoring/regression.

    Args:
        timeline: list of 44 status strings
        weather: raw weather dict (for soil temps, precip)
        target_day: index in timeline (30 = today)
        config: thresholds dict

    Returns dict of features.
    """
    if config is None:
        config = {}

    lookback_min = config.get("start_lookback_min", 7)
    lookback_max = config.get("start_lookback_max", 30)
    max_bad_streak = config.get("max_bad_streak", 3)

    # Count START days in the lookback window
    start_window_begin = max(0, target_day - lookback_max)
    start_window_end = max(0, target_day - lookback_min)
    start_days = sum(1 for i in range(start_window_begin, start_window_end + 1)
                     if i < len(timeline) and timeline[i] in ("START", "START_GROW"))

    # Find first START cluster. If none in window, the START happened earlier
    # (before our 30-day lookback) — count from beginning of window if the site
    # has continuous GROW activity. This catches sites that warmed up before
    # our window started (common in late spring / early summer).
    first_start = None
    for i in range(start_window_begin, min(target_day, len(timeline))):
        if timeline[i] in ("START", "START_GROW"):
            first_start = i
            break

    # If no START in window but plenty of GROW days, treat the window
    # beginning as the implicit start point. PAST_PRIME days count too —
    # a site declining from peak still had a START before the window.
    grow_in_window = sum(1 for i in range(start_window_begin, min(target_day + 1, len(timeline)))
                         if i < len(timeline) and timeline[i] in ("GROW", "START_GROW", "START", "PAST_PRIME"))
    implicit_start = first_start is None and grow_in_window >= 7

    grow_days_total = 0  # never resets — biological progress
    grow_days = 0        # resets on bad streak — for phase classification
    current_bad_streak = 0
    longest_bad_streak = 0
    growth_reset = False

    count_from = first_start if first_start is not None else (start_window_begin if implicit_start else None)

    if count_from is not None:
        for i in range(count_from, min(target_day + 1, len(timeline))):
            status = timeline[i]
            if status in ("GROW", "START_GROW", "START", "PAST_PRIME"):
                # PAST_PRIME counts as biological growth (still harvestable),
                # just declining — the regression-friendly penalty is applied
                # via past_prime_recent below.
                grow_days += 1
                grow_days_total += 1
                current_bad_streak = 0
            elif status == "BAD":
                current_bad_streak += 1
                longest_bad_streak = max(longest_bad_streak, current_bad_streak)
                if current_bad_streak >= max_bad_streak:
                    growth_reset = True
                    grow_days = 0

    # If we used implicit start (window onset), credit start_days too —
    # the START happened, we just didn't see it in our window.
    if implicit_start and start_days == 0:
        start_days = 1

    # Soil temp features
    hist_soil = weather.get("hist_soil_temp", [])
    fc_soil = weather.get("forecast_soil_temp", [])
    all_soil = list(hist_soil) + list(fc_soil)

    # Average soil temp over last 14 days
    soil_14d = [t for t in all_soil[max(0, target_day-13):target_day+1] if t is not None]
    soil_avg_14d = np.mean(soil_14d) if soil_14d else 0

    # Current soil temp
    current_soil = all_soil[target_day] if target_day < len(all_soil) else 0

    # Warming rate (7-day rolling)
    if len(soil_14d) >= 7:
        recent = np.mean(soil_14d[-3:])
        prior = np.mean(soil_14d[:4])
        warming_rate = (recent - prior) / 7
    else:
        warming_rate = 0

    # Precip events >0.4in in last 30 days
    hist_precip = weather.get("hist_precip", [])
    precip_events = sum(1 for p in hist_precip if p > 0.4)

    # Total precip 14 days
    precip_14d = sum(hist_precip[-14:]) if hist_precip else 0

    # Snow depth at target day
    fc_snow = weather.get("forecast_snow_depth", [])
    snow_idx = target_day - 30
    snow_depth = fc_snow[snow_idx] if 0 <= snow_idx < len(fc_snow) else 0

    # Smoothed "currently good" — ratio of good days in last 5 days
    # instead of binary today-only. Prevents single bad day from
    # crashing readiness. PAST_PRIME does NOT count as currently good —
    # we want the recent surface state to reflect heat decline.
    window = 5
    good_recent = 0
    for i in range(max(0, target_day - window + 1), target_day + 1):
        if i < len(timeline) and timeline[i] in ("GROW", "START_GROW"):
            good_recent += 1
    is_currently_good = round(good_recent / window, 2)

    # Past-prime recent: count of PAST_PRIME days in last 7 days.
    # Drives the deterministic readiness taper in score_readiness — sites
    # holding above grow_max for days drop off gradually instead of cliff-
    # falling at past_prime_max.
    pp_window = 7
    past_prime_recent = sum(
        1 for i in range(max(0, target_day - pp_window + 1), target_day + 1)
        if i < len(timeline) and timeline[i] == "PAST_PRIME"
    )

    return {
        "start_days": start_days,
        "grow_days": grow_days_total,  # total for readiness
        "grow_days_since_reset": grow_days,  # for phase classification
        "max_bad_streak": longest_bad_streak,
        "growth_was_reset": 1 if growth_reset else 0,
        "soil_avg_14d": round(soil_avg_14d, 1),
        "current_soil": round(current_soil, 1) if current_soil else 0,
        "warming_rate": round(warming_rate, 2),
        "precip_events": precip_events,
        "precip_14d": round(precip_14d, 2),
        "snow_depth": round(snow_depth, 1) if snow_depth else 0,
        "is_currently_good": is_currently_good,
        "past_prime_recent": past_prime_recent,
    }


# ── Phase classification from features ──

def classify_phase(features, config=None):
    """
    Determine the phase label from extracted features.
    Returns one of: EMERGING, GROWING, WAITING, TOO_EARLY
    """
    if config is None:
        config = {}
    min_start = config.get("min_start_days", 1)
    min_grow = config.get("min_grow_days", 14)

    start = features["start_days"]
    grow = features.get("grow_days_since_reset", features["grow_days"])
    reset = features["growth_was_reset"]

    if start >= min_start and grow >= min_grow and not reset:
        return "EMERGING"
    elif start >= min_start and grow >= min_grow * 0.5:
        return "GROWING"
    elif start >= 1:
        return "WAITING"
    else:
        return "TOO_EARLY"


# ── Readiness score (will be replaced by regression coefficients) ──

# Learned from 21 labeled scenarios via logistic regression (95% accuracy)
# See utils/fit_regression.py for details. Re-fit with:
#   python -m utils.fit_regression --save coefficients.json
# Learned from 70 labeled scenarios (21 synthetic + 49 real-world from cache)
# via logistic regression. 89% accuracy. Re-fit with:
#   python -m utils.fit_regression --json data/real_scenarios_labeled.json
READINESS_COEFFICIENTS = {
    "start_days": 0.094569,
    "grow_days": 0.194117,
    "max_bad_streak": -0.204683,
    "growth_was_reset": 0.846759,
    "soil_avg_14d": 0.338649,
    "current_soil": -0.271436,
    "warming_rate": 0.374796,
    "precip_events": 0.702138,
    "is_currently_good": 1.041947,
    "intercept": -7.674090,
}


def score_readiness(features, config=None):
    """
    Readiness score (0-100) using logistic regression coefficients
    learned from 70 labeled scenarios.

    Returns probability * 100, where probability = sigmoid(coefficients · features).
    Capped by phase: no start days → max 25, waiting → max 50.
    """
    coefs = READINESS_COEFFICIENTS
    z = coefs["intercept"]
    for key in coefs:
        if key != "intercept" and key in features:
            z += coefs[key] * features[key]

    # Sigmoid → probability → scale to 0-100
    prob = 1 / (1 + math.exp(-z))
    raw = round(prob * 100)

    # Past-prime taper: PAST_PRIME means soil above grow_max (e.g. 68F+ for
    # morel) — declining but harvestable. We only penalize SUSTAINED heat,
    # not noise. First 2 PAST_PRIME days in last 7 are free; beyond that,
    # 8% drop per additional day, floored at 0.50. So a fully past-prime
    # week (7 days) = 0.60x; 4 days = 0.84x; 2 days = no penalty.
    # This matches the field anchor (Unit 2.3, 4-5lbs at 6mo with soils
    # touching the 60s in late April — those days are GROW, not PAST_PRIME).
    pp_recent = features.get("past_prime_recent", 0)
    pp_grace = 2
    taper = max(0.50, 1.0 - 0.08 * max(0, pp_recent - pp_grace))
    raw = round(raw * taper)

    # Cap readiness by phase — the regression doesn't weight start_days
    # heavily enough, so warm soil with no triggering event (START) can
    # produce high readiness despite being biologically too early.
    phase = classify_phase(features, config)
    if phase == "TOO_EARLY":
        return min(raw, 25)
    elif phase == "WAITING":
        return min(raw, 50)
    return raw


def score_readiness_manual(features, config=None):
    """Legacy hand-tuned readiness. Use score_readiness() instead."""
    return score_readiness(features, config)


# ── Potential score (site quality — no weather dependency) ──

def score_potential(fire, elev, terrain, mushroom_type="morel", evt=None):
    """Score site quality. Stable — doesn't change with weather."""
    mt = MUSHROOM_TYPES[mushroom_type]
    w = mt.get("potential_weights", {
        "burn_quality": 40, "elevation": 15, "aspect": 15, "vegetation": 15, "season": 10, "freeze_damage": 5
    })
    scores = {}
    details = {}

    # Burn quality: recency is a MULTIPLIER on type + acreage (not additive).
    # An old burn can't hide behind being a machine pile — age dominates.
    max_pts = w.get("burn_quality", 35)
    fire_date = fire.get("date")
    recency_curve = mt.get("recency_curve", [(2, 0.3), (8, 0.5), (14, 0.4), (20, 0.2), (30, 0.1)])

    # Recency: yield potential as fraction of peak (0.0-1.0).
    # The recency curve fractions are normalized so the prime bucket = 1.0.
    peak_frac = max(f for _, f in recency_curve)  # 0.50 in default curve
    recency_mult = 0.0
    if fire_date:
        try:
            months_ago = (datetime.now() - datetime.strptime(fire_date, "%Y-%m-%d")).days / 30
            for max_months, frac in recency_curve:
                if months_ago <= max_months:
                    recency_mult = frac / peak_frac  # 1.0 at peak, 0.4 at 17mo, etc.
                    break
            details["burn_age"] = f"{months_ago:.0f}mo ago"
        except ValueError:
            recency_mult = 0.2

    # Type + acreage: these are the "intrinsic burn quality" — what the burn
    # is, regardless of age. Sum to max ~0.60 of weight (type 0.45 + acres 0.15).
    intrinsic = 0.0
    burn_type_str = (fire.get("pfirs_burn_type", "") or "").lower()
    type_scores = mt.get("burn_type_scores", {})
    matched = False
    for key_str, frac in type_scores.items():
        if key_str in burn_type_str:
            intrinsic += frac
            matched = True
            break
    if not matched:
        intrinsic += 0.15 if fire.get("is_rx") else 0.10

    acres = fire.get("acres", 0)
    for min_acres, frac in mt.get("acreage_curve", [(20, 0.15), (5, 0.1), (0, 0.05)]):
        if acres >= min_acres:
            intrinsic += frac
            break

    # Final: intrinsic quality scaled by recency multiplier.
    # Peak burn @ 6mo = full intrinsic. Same burn @ 17mo = 0.4x intrinsic.
    burn_score = max_pts * intrinsic * recency_mult

    details["burn_type"] = fire.get("pfirs_burn_type") or ("RX" if fire.get("is_rx") else "wildfire")
    details["burn_acres"] = f"{fire.get('acres', 0):.1f}ac"
    scores["burn_quality"] = min(round(burn_score), max_pts)

    # Elevation
    max_pts = w.get("elevation", 25)
    elev_score = 0
    if elev is not None:
        month = datetime.now().month
        base = mt.get("elev_base", 4500)
        rng = mt.get("elev_range", 2500)
        shift = mt.get("elev_shift_per_month", 300)
        ideal_low = base + (month - 4) * shift
        ideal_high = ideal_low + rng
        if ideal_low <= elev <= ideal_high:
            elev_score = max_pts
        elif ideal_low - 500 <= elev <= ideal_high + 500:
            elev_score = round(max_pts * 0.6)
        elif ideal_low - 1000 <= elev <= ideal_high + 1000:
            elev_score = round(max_pts * 0.25)
        details["elevation"] = f"{elev:.0f}ft"
    scores["elevation"] = elev_score

    # Aspect (month-adjusted)
    max_pts = w.get("aspect", 20)
    aspect_score = 0
    if terrain and terrain.get("aspect") is not None:
        aspect = terrain["aspect"]
        month = datetime.now().month
        month_weights = mt.get("aspect_month_weights", {})
        asp = month_weights.get(month, mt.get("aspect_default", {"south": 3, "east_west": 1, "north": 0}))
        if 135 <= aspect <= 225:
            aspect_score = round(max_pts * asp["south"] / 5)
        elif 90 <= aspect <= 270:
            aspect_score = round(max_pts * asp["east_west"] / 5)
        else:
            aspect_score = round(max_pts * asp.get("north", 0) / 5)
        details["aspect"] = f"{aspect:.0f}deg"
    scores["aspect"] = aspect_score

    # Season
    max_pts = w.get("season", 10)
    month = datetime.now().month
    lo, hi = mt.get("season_months", (4, 7))
    in_season = lo <= month <= hi
    scores["season"] = max_pts if in_season else round(max_pts * 0.3)
    details["in_season"] = "YES" if in_season else f"no ({lo}-{hi})"

    # Vegetation type (from LANDFIRE EVT)
    max_pts = w.get("vegetation", 15)
    if evt and evt.get("evt_suitability") is not None:
        veg_score = round(max_pts * evt["evt_suitability"])
        details["vegetation"] = evt.get("evt_name", "Unknown")
    else:
        veg_score = round(max_pts * 0.5)  # unknown = assume moderate
        details["vegetation"] = "No data"
    scores["vegetation"] = veg_score

    # Freeze damage — placeholder, computed from timeline
    scores["freeze_damage"] = w.get("freeze_damage", 5)  # full marks if no freeze

    potential = sum(scores.values())
    return {"potential": potential, "scores": scores, "details": details}
