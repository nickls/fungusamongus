"""Config-driven scoring engine for burn sites."""

from datetime import datetime

import numpy as np

from config import MUSHROOM_TYPES
from utils.elevation import aspect_label


def extract_weather_details(weather: dict) -> dict:
    """Extract common weather metrics from raw weather data."""
    d = {}
    fc_max = weather.get("forecast_temps_max", [])
    fc_min = weather.get("forecast_temps_min", [])
    hist_max = weather.get("hist_temps_max", [])
    hist_min = weather.get("hist_temps_min", [])

    # Use last 3 days of highs/lows for current conditions (not 7-day avg)
    highs = fc_max[-3:] if fc_max else hist_max[-3:]
    lows = fc_min[-3:] if fc_min else hist_min[-3:]
    if highs:
        d["avg_high"] = np.mean(highs)
        d["avg_high_7d"] = f"{d['avg_high']:.0f}F"
    if lows:
        d["avg_low"] = np.mean(lows)
        d["avg_low_7d"] = f"{d['avg_low']:.0f}F"

    # Use target-day soil temp (from narrow window if available, else full)
    soil_target = weather.get("forecast_soil_temp_target", weather.get("forecast_soil_temp", []))
    if soil_target:
        d["avg_soil"] = soil_target[-1]  # last element = target day
        d["soil_temp"] = f"{d['avg_soil']:.0f}F"

    hist_precip = weather.get("hist_precip", [])
    if hist_precip:
        d["precip_14d_val"] = sum(hist_precip[-14:])
        d["precip_30d_val"] = sum(hist_precip)
        d["precip_14d"] = f"{d['precip_14d_val']:.1f}in"
        d["precip_30d"] = f"{d['precip_30d_val']:.1f}in"
        # Count of rain events >0.4in (10mm) in 30 days — literature says this matters
        d["rain_events_30d"] = sum(1 for p in hist_precip if p > 0.4)

    snow_depth = weather.get("forecast_snow_depth", [])
    if snow_depth and len(snow_depth) >= 3:
        d["snow_past"] = np.mean(snow_depth[:-1]) if len(snow_depth) > 1 else snow_depth[0]
        d["snow_now"] = snow_depth[-1]  # target day's snow depth
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


def make_day_weather(weather: dict, day_offset: int) -> dict:
    """
    Build a weather dict for a specific day (0=today, 1=tomorrow, ..., 7).

    Forecast arrays: 14 entries = 7 past + 7 future. Index 7 = today.

    Key principle:
    - Soil temp threshold: use the TARGET DAY's value (not average)
    - Soil trend: use a centered window around the target day
    - Air temps: use a small window around the target day
    - Snow: use the target day's value
    - Precip: sum a window ending on the target day
    """
    today_idx = 7
    target_idx = today_idx + day_offset

    def safe_slice(arr, start, end):
        if not arr:
            return []
        s = max(0, start)
        e = min(len(arr), end)
        return [x for x in arr[s:e] if x is not None]

    # Soil target window: ends at target day. Used for threshold (last element).
    soil_all = weather.get("forecast_soil_temp", [])
    soil_window = safe_slice(soil_all, target_idx - 3, target_idx + 1)

    # Soil trend window: all data up to target day. Used for regression slope.
    soil_trend_window = safe_slice(soil_all, 0, target_idx + 1)

    # Snow depth: target day value + a few before for melt detection
    snow_all = weather.get("forecast_snow_depth", [])
    snow_window = safe_slice(snow_all, target_idx - 3, target_idx + 1)

    # Soil moisture: small window around target
    sm_all = weather.get("forecast_soil_moisture", [])
    sm_window = safe_slice(sm_all, target_idx - 3, target_idx + 1)

    # Air temps: 3-day window centered on target
    fc_max = weather.get("forecast_temps_max", [])
    fc_min = weather.get("forecast_temps_min", [])
    highs = safe_slice(fc_max, target_idx - 1, target_idx + 2)
    lows = safe_slice(fc_min, target_idx - 1, target_idx + 2)

    return {
        "hist_temps_max": weather.get("hist_temps_max", []),
        "hist_temps_min": weather.get("hist_temps_min", []),
        "hist_precip": weather.get("hist_precip", []),
        "hist_snowfall": weather.get("hist_snowfall", []),
        "hist_soil_temp": weather.get("hist_soil_temp", []),
        "forecast_temps_max": highs,
        "forecast_temps_min": lows,
        "forecast_soil_temp": soil_trend_window,  # full window for trend
        "forecast_soil_temp_target": soil_window,  # narrow window, last = target day
        "forecast_soil_moisture": sm_window,
        "forecast_snow_depth": snow_window,
        "current_temp": weather.get("current_temp"),
    }


def score_burn_multiday(fire, weather, elev, terrain=None, mushroom_type="morel", days=8):
    """Score a burn for days 0-7, returning per-day score dicts."""
    day_scores = []
    for d in range(days):
        day_wx = make_day_weather(weather, d)
        result = score_burn_site(fire, day_wx, elev, mushroom_type, terrain)
        result["day"] = d
        day_scores.append(result)
    return day_scores


def score_burn_site(fire: dict, weather: dict, elev: float | None,
                    mushroom_type: str = "morel", terrain: dict | None = None) -> dict:
    """
    Score a burn location using the config-driven profile for mushroom_type.
    All thresholds and weights come from config.MUSHROOM_TYPES.
    """
    mt = MUSHROOM_TYPES[mushroom_type]
    w = mt["weights"]
    scores = {}
    details = {}
    wx = extract_weather_details(weather)
    details.update({k: v for k, v in wx.items() if isinstance(v, str)})

    avg_soil = wx.get("avg_soil")
    soil_temps = weather.get("forecast_soil_temp", [])

    # ══════════════════════════════════════════════════════════════════
    # A. SOIL TEMPERATURE THRESHOLD (25pts) — hard gate
    # ══════════════════════════════════════════════════════════════════
    max_pts = w.get("soil_threshold", 25)
    soil_score = 0
    soil_gate_factor = 1.0  # applied to ALL other scores

    ideal = mt.get("soil_temp_ideal", (48, 58))
    ok = mt.get("soil_temp_ok", (45, 62))
    gate_temp = mt.get("soil_temp_gate", 40)
    approaching_temp = mt.get("soil_temp_approaching", 45)

    if avg_soil is not None:
        if ideal[0] <= avg_soil <= ideal[1]:
            soil_score = max_pts                  # full marks
        elif ok[0] <= avg_soil <= ok[1]:
            soil_score = round(max_pts * 0.6)     # acceptable
        elif avg_soil >= approaching_temp:
            soil_score = round(max_pts * 0.3)     # approaching
            soil_gate_factor = 0.7
            details["soil_gate"] = f"approaching ({avg_soil:.0f}F)"
        elif avg_soil >= gate_temp:
            soil_score = round(max_pts * 0.15)    # cold
            soil_gate_factor = 0.3
            details["soil_gate"] = f"cold ({avg_soil:.0f}F)"
        else:
            soil_score = 0                        # blocked
            soil_gate_factor = 0.1
            details["soil_gate"] = f"BLOCKED ({avg_soil:.0f}F)"
    else:
        soil_score = round(max_pts * 0.3)  # no data, assume mediocre
        details["soil_gate"] = "no soil data"

    scores["soil_threshold"] = soil_score

    # ══════════════════════════════════════════════════════════════════
    # B. SOIL GDD (25pts) — cumulative growing degree days
    # Literature: 365-580 GDD above 32F predicts morel onset
    # ══════════════════════════════════════════════════════════════════
    max_pts = w.get("soil_gdd", 25)
    gdd_score = 0

    # Build full soil temp timeline: 30-day history + 14-day forecast
    hist_soil = weather.get("hist_soil_temp", [])
    all_soil_temps = list(hist_soil) + list(soil_temps)

    gdd_base = mt.get("gdd_base_temp", 32)
    gdd_onset = mt.get("gdd_onset", 365)
    gdd_peak = mt.get("gdd_peak", 580)

    if all_soil_temps:
        gdd = sum(max(t - gdd_base, 0) for t in all_soil_temps)
        details["soil_gdd"] = f"{gdd:.0f} GDD"

        if gdd >= gdd_peak:
            gdd_score = max_pts                        # peak fruiting window
        elif gdd >= gdd_onset:
            frac = (gdd - gdd_onset) / (gdd_peak - gdd_onset)
            gdd_score = round(max_pts * (0.7 + 0.3 * frac))  # 70-100% of max
        elif gdd >= gdd_onset * 0.55:
            frac = (gdd - gdd_onset * 0.55) / (gdd_onset * 0.45)
            gdd_score = round(max_pts * 0.3 * frac)   # approaching
        # else: too early, 0 pts
    else:
        details["soil_gdd"] = "no data"

    # Also compute trend (F/day) as secondary detail for the popup
    if len(soil_temps) >= 6:
        x = np.arange(len(soil_temps))
        slope, _ = np.polyfit(x, soil_temps, 1)
        trend_per_day = slope
        if trend_per_day > 0.5:
            details["soil_trend"] = f"WARMING (+{trend_per_day:.1f}F/day)"
        elif trend_per_day > 0.1:
            details["soil_trend"] = f"warming (+{trend_per_day:.1f}F/day)"
        elif trend_per_day > -0.2:
            details["soil_trend"] = f"stable ({trend_per_day:+.1f}F/day)"
        else:
            details["soil_trend"] = f"cooling ({trend_per_day:.1f}F/day)"
        details["soil_trend_per_day"] = round(trend_per_day, 2)

    if len(soil_temps) >= 2:
        deltas = [round(soil_temps[i] - soil_temps[i-1], 1) for i in range(1, len(soil_temps))]
        details["soil_deltas"] = deltas
        details["soil_temps_raw"] = [round(t, 1) for t in soil_temps]

    scores["soil_gdd"] = round(gdd_score)

    # ══════════════════════════════════════════════════════════════════
    # C. RECENT MOISTURE (20pts) — rain/snowmelt in last 3-10 days
    # ══════════════════════════════════════════════════════════════════
    max_pts = w.get("recent_moisture", 20)
    moisture_score = 0
    precip_14d = wx.get("precip_14d_val", 0)
    melt = wx.get("melt_score", 0)

    for threshold, frac in mt.get("precip_thresholds", [(1.5, 0.5), (0.5, 0.3), (0.1, 0.1)]):
        if precip_14d > threshold:
            moisture_score += max_pts * frac
            break

    melt_weight = mt.get("melt_weight", 0.4)
    moisture_score += max_pts * melt_weight * max(melt, 0)

    sm_range = mt.get("soil_moisture_ideal", (0.2, 0.45))
    sm_weight = mt.get("soil_moisture_weight", 0.1)
    avg_sm = wx.get("avg_sm")
    if avg_sm is not None and sm_range[0] <= avg_sm <= sm_range[1]:
        moisture_score += max_pts * sm_weight

    # Rain event bonus — literature: events >10mm in prior 30 days matter
    rain_events = wx.get("rain_events_30d", 0)
    if rain_events >= 3:
        moisture_score += max_pts * 0.15
    elif rain_events >= 2:
        moisture_score += max_pts * 0.10
    if rain_events:
        details["rain_events"] = f"{rain_events} events >0.4in/30d"

    scores["recent_moisture"] = min(round(moisture_score), max_pts)

    # ══════════════════════════════════════════════════════════════════
    # D. BURN QUALITY (15pts) — recency, type, size
    # ══════════════════════════════════════════════════════════════════
    max_pts = w.get("burn_quality", 15)
    burn_score = 0

    if mt.get("needs_fire"):
        fire_date = fire.get("date")
        recency_curve = mt.get("recency_curve", [(2, 0.3), (8, 0.5), (14, 0.4), (20, 0.2), (30, 0.1)])
        # Recency — if too old, entire burn_quality is 0 (no type/size bonus)
        burn_is_viable = False
        if fire_date:
            try:
                months_ago = (datetime.now() - datetime.strptime(fire_date, "%Y-%m-%d")).days / 30
                for max_months, frac in recency_curve:
                    if months_ago <= max_months:
                        burn_score += max_pts * frac
                        burn_is_viable = True
                        break
                details["burn_age"] = f"{months_ago:.0f}mo ago"
            except ValueError:
                burn_score += max_pts * 0.1
                burn_is_viable = True
        elif fire.get("year"):
            try:
                yrs = datetime.now().year - int(fire["year"])
                if yrs <= 2:
                    burn_score += max_pts * max(0.4 - yrs * 0.15, 0.05)
                    burn_is_viable = True
                details["burn_age"] = f"{fire['year']}"
            except (ValueError, TypeError):
                pass

        # Type and size bonus — only if burn is still viable
        if burn_is_viable:
            burn_type_str = (fire.get("pfirs_burn_type", "") or "").lower()
            type_scores = mt.get("burn_type_scores", {})
            matched = False
            for key_str, frac in type_scores.items():
                if key_str in burn_type_str:
                    burn_score += max_pts * frac
                    matched = True
                    break
            if not matched:
                if fire.get("is_rx"):
                    burn_score += max_pts * type_scores.get("rx_generic", 0.15)
                else:
                    burn_score += max_pts * type_scores.get("wildfire", 0.10)

            acres = fire.get("acres", 0)
            for min_acres, frac in mt.get("acreage_curve", [(20, 0.15), (5, 0.1), (0, 0.05)]):
                if acres >= min_acres:
                    burn_score += max_pts * frac
                    break
        else:
            acres = fire.get("acres", 0)

        details["burn_type"] = fire.get("pfirs_burn_type") or ("RX" if fire.get("is_rx") else "wildfire")
        details["burn_acres"] = f"{acres:.1f}ac"

    scores["burn_quality"] = min(round(burn_score), max_pts)

    # ══════════════════════════════════════════════════════════════════
    # E. SUN / ASPECT / ELEVATION (10pts) — local soil warming rate
    # ══════════════════════════════════════════════════════════════════
    max_pts = w.get("sun_aspect", 10)
    aspect_score = 0

    # Aspect (0-5pts) — month-adjusted from config
    if terrain and terrain.get("aspect") is not None:
        aspect = terrain["aspect"]
        slope = terrain.get("slope", 0)
        details["slope"] = f"{slope:.0f}deg"
        details["aspect"] = f"{aspect:.0f}deg ({aspect_label(aspect)})"
        if terrain.get("aspect_centroid") is not None:
            details["aspect_centroid"] = f"{terrain['aspect_centroid']:.0f}deg"

        month = datetime.now().month
        month_weights = mt.get("aspect_month_weights", {})
        asp = month_weights.get(month, mt.get("aspect_default", {"south": 3, "east_west": 1, "north": 0}))

        if 135 <= aspect <= 225:
            aspect_score += asp["south"]
        elif 90 <= aspect <= 270:
            aspect_score += asp["east_west"]
        else:
            aspect_score += asp.get("north", 0)

        if 5 <= slope <= 25:
            aspect_score += 2   # good drainage, walkable
        elif slope < 5:
            aspect_score += 1

    # Elevation band (0-3pts within sun_aspect budget)
    if elev is not None:
        month = datetime.now().month
        base = mt.get("elev_base", 4500)
        rng = mt.get("elev_range", 2500)
        shift = mt.get("elev_shift_per_month", 300)
        ideal_low = base + (month - 4) * shift
        ideal_high = ideal_low + rng
        es = mt.get("elev_scoring", {"in_band": 1.0, "within_500ft": 0.6, "within_1000ft": 0.25})

        if ideal_low <= elev <= ideal_high:
            aspect_score += 3
        elif ideal_low - 500 <= elev <= ideal_high + 500:
            aspect_score += 2
        elif ideal_low - 1000 <= elev <= ideal_high + 1000:
            aspect_score += 1

        details["elevation"] = f"{elev:.0f}ft"
        details["ideal_band"] = f"{ideal_low:.0f}-{ideal_high:.0f}ft"

    scores["sun_aspect"] = min(aspect_score, max_pts)

    # ══════════════════════════════════════════════════════════════════
    # F. AIR TEMPERATURE (5pts) — proxy only
    # ══════════════════════════════════════════════════════════════════
    max_pts = w.get("air_temp", 5)
    air_score = 0
    avg_high = wx.get("avg_high")
    avg_low = wx.get("avg_low")

    if avg_high is not None:
        lo, hi = mt.get("temp_ideal_high", (55, 75))
        ok_lo, ok_hi = mt.get("temp_ok_high", (45, 85))
        if lo <= avg_high <= hi:
            air_score += 3
        elif ok_lo <= avg_high <= ok_hi:
            air_score += 1

    if avg_low is not None:
        lo, hi = mt.get("temp_ideal_low", (30, 50))
        if lo <= avg_low <= hi:
            air_score += 2
        elif lo - 5 <= avg_low <= hi + 5:
            air_score += 1

    scores["air_temp"] = min(air_score, max_pts)

    # ══════════════════════════════════════════════════════════════════
    # ══════════════════════════════════════════════════════════════════
    # Apply soil gate to ALL factors except soil_threshold itself
    # ══════════════════════════════════════════════════════════════════
    if soil_gate_factor < 1.0:
        for k in scores:
            if k != "soil_threshold":
                scores[k] = round(scores[k] * soil_gate_factor)

    # Season gate
    # ══════════════════════════════════════════════════════════════════
    month = datetime.now().month
    lo, hi = mt.get("season_months", (4, 7))
    in_season = lo <= month <= hi
    details["in_season"] = "YES" if in_season else f"no (best {lo}-{hi})"
    if not in_season:
        for k in scores:
            scores[k] = scores[k] // 2

    total = sum(scores.values())
    return {"total": total, "scores": scores, "details": details,
            "mushroom_type": mushroom_type}
