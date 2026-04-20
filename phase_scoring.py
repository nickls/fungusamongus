"""
Phase-based scoring model (v0.7.0).

Replaces the single weighted score with a biological model:
- Each day is classified as START / START_GROW / GROW / BAD
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

def classify_day(soil_temp, prev_soil_temp, precip, snow_depth, had_warmth, config,
                 prev_status=None):
    """
    Classify a single day's conditions into START / START_GROW / GROW / BAD.

    Args:
        soil_temp: soil temperature (F) for this day
        prev_soil_temp: previous day's soil temp (F), or None
        precip: precipitation (inches) for this day
        snow_depth: snow depth (inches) for this day
        had_warmth: whether soil was ever >45F before this day
        config: dict with thresholds
        prev_status: previous day's status (for oscillation filtering)
    """
    start_min = config.get("start_soil_min", 43)
    start_max = config.get("start_soil_max", 50)
    grow_min = config.get("grow_soil_min", 45)
    grow_max = config.get("grow_soil_max", 58)
    freeze = config.get("bad_freeze_threshold", 32)
    bad_snow = config.get("bad_snow_depth", 24)

    if soil_temp is None:
        return "BAD"

    # Freeze after warmth = damage
    if soil_temp <= freeze and had_warmth:
        return "BAD"

    # Deep snowpack
    if snow_depth is not None and snow_depth > bad_snow:
        return "BAD"

    # Too cold for anything
    if soil_temp < start_min:
        return "BAD"

    # Too hot — past prime
    if soil_temp > grow_max:
        return "BAD"

    is_warming = prev_soil_temp is not None and soil_temp > prev_soil_temp
    in_start_range = start_min <= soil_temp <= start_max
    in_grow_range = grow_min <= soil_temp <= grow_max
    has_moisture = precip > 0.1 or (snow_depth is not None and 0 < snow_depth <= bad_snow)

    # Anti-oscillation: if previous day was BAD and we just popped above start_min,
    # require warming trend (not just a single day crossing). A true START needs
    # the previous day to also be trending up, not bouncing from a crash.
    recovering_from_bad = prev_status == "BAD"

    # START: soil warming into initiation range + moisture
    # Also: soil already in grow range but a NEW moisture event arrives (rain trigger)
    if has_moisture:
        if in_start_range and is_warming and not recovering_from_bad:
            return "START_GROW" if in_grow_range else "START"
        if in_grow_range and precip > 0.3:
            # Significant rain event while in grow range = can trigger new starts
            return "START_GROW"

    # GROW: in the sustained growth range with or without moisture
    if in_grow_range:
        return "GROW"

    # In start range but not warming or no moisture — marginal
    if in_start_range:
        if is_warming:
            return "START"  # warming but dry
        return "GROW"  # holding in range, not warming — treat as marginal grow

    return "BAD"


def build_timeline(weather, config):
    """
    Build a 44-day timeline of daily statuses from weather data.
    Returns list of 44 status strings.
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

    timeline = []
    had_warmth = False
    prev_status = None

    for i in range(min(44, len(all_soil))):
        soil = all_soil[i]
        prev = all_soil[i - 1] if i > 0 else None
        precip = all_precip[i] if i < len(all_precip) else 0
        snow = all_snow[i] if i < len(all_snow) else None

        if soil is not None and soil >= 45:
            had_warmth = True

        status = classify_day(soil, prev, precip, snow if snow is not None else 0,
                              had_warmth, config, prev_status)
        timeline.append(status)
        prev_status = status

    # Pad to 44 if needed
    while len(timeline) < 44:
        timeline.append("BAD")

    return timeline


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

    # Find first START cluster, then count GROW days after it
    first_start = None
    for i in range(start_window_begin, min(target_day, len(timeline))):
        if timeline[i] in ("START", "START_GROW"):
            first_start = i
            break

    grow_days = 0
    current_bad_streak = 0
    longest_bad_streak = 0
    growth_reset = False

    if first_start is not None:
        for i in range(first_start, min(target_day + 1, len(timeline))):
            status = timeline[i]
            if status in ("GROW", "START_GROW", "START"):
                grow_days += 1
                current_bad_streak = 0
            elif status == "BAD":
                current_bad_streak += 1
                longest_bad_streak = max(longest_bad_streak, current_bad_streak)
                if current_bad_streak >= max_bad_streak:
                    growth_reset = True
                    # Reset: count from after this bad streak
                    grow_days = 0

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

    # Current day status
    current_status = timeline[target_day] if target_day < len(timeline) else "BAD"
    is_currently_good = 1 if current_status in ("GROW", "START_GROW") else 0

    return {
        "start_days": start_days,
        "grow_days": grow_days,
        "max_bad_streak": longest_bad_streak,
        "growth_was_reset": 1 if growth_reset else 0,
        "soil_avg_14d": round(soil_avg_14d, 1),
        "current_soil": round(current_soil, 1) if current_soil else 0,
        "warming_rate": round(warming_rate, 2),
        "precip_events": precip_events,
        "precip_14d": round(precip_14d, 2),
        "snow_depth": round(snow_depth, 1) if snow_depth else 0,
        "is_currently_good": is_currently_good,
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
    grow = features["grow_days"]
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
    learned from 21 labeled scenarios.

    Returns probability * 100, where probability = sigmoid(coefficients · features).
    """
    coefs = READINESS_COEFFICIENTS
    z = coefs["intercept"]
    for key in coefs:
        if key != "intercept" and key in features:
            z += coefs[key] * features[key]

    # Sigmoid → probability → scale to 0-100
    prob = 1 / (1 + math.exp(-z))
    return round(prob * 100)


def score_readiness_manual(features, config=None):
    """Legacy hand-tuned readiness. Use score_readiness() instead."""
    return score_readiness(features, config)


# ── Potential score (site quality — no weather dependency) ──

def score_potential(fire, elev, terrain, mushroom_type="morel"):
    """Score site quality. Stable — doesn't change with weather."""
    mt = MUSHROOM_TYPES[mushroom_type]
    w = mt.get("potential_weights", {
        "burn_quality": 35, "elevation": 25, "aspect": 20, "season": 10, "freeze_damage": 10
    })
    scores = {}
    details = {}

    # Burn quality (existing logic)
    max_pts = w.get("burn_quality", 35)
    burn_score = 0
    fire_date = fire.get("date")
    recency_curve = mt.get("recency_curve", [(2, 0.3), (8, 0.5), (14, 0.4), (20, 0.2), (30, 0.1)])
    burn_viable = False

    if fire_date:
        try:
            months_ago = (datetime.now() - datetime.strptime(fire_date, "%Y-%m-%d")).days / 30
            for max_months, frac in recency_curve:
                if months_ago <= max_months:
                    burn_score += max_pts * frac
                    burn_viable = True
                    break
            details["burn_age"] = f"{months_ago:.0f}mo ago"
        except ValueError:
            burn_score += max_pts * 0.1
            burn_viable = True

    if burn_viable:
        burn_type_str = (fire.get("pfirs_burn_type", "") or "").lower()
        type_scores = mt.get("burn_type_scores", {})
        matched = False
        for key_str, frac in type_scores.items():
            if key_str in burn_type_str:
                burn_score += max_pts * frac
                matched = True
                break
        if not matched:
            burn_score += max_pts * (0.15 if fire.get("is_rx") else 0.10)

        acres = fire.get("acres", 0)
        for min_acres, frac in mt.get("acreage_curve", [(20, 0.15), (5, 0.1), (0, 0.05)]):
            if acres >= min_acres:
                burn_score += max_pts * frac
                break

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

    # Freeze damage — placeholder, computed from timeline
    scores["freeze_damage"] = w.get("freeze_damage", 10)  # full marks if no freeze

    potential = sum(scores.values())
    return {"potential": potential, "scores": scores, "details": details}
