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

    # ── Temperature ──
    max_pts = w.get("temperature", 25)
    sub = mt.get("temp_sub_weights", {"soil_trend": 0.35, "high": 0.30, "low": 0.20, "soil": 0.15})
    temp_score = 0
    avg_high = wx.get("avg_high")
    avg_low = wx.get("avg_low")
    avg_soil = wx.get("avg_soil")

    # Soil temp is a GATE — if soil is too cold, entire temp score is capped
    soil_gate_open = True
    soil_gate_factor = 1.0
    if avg_soil is not None:
        lo, hi = mt["soil_temp_ideal"]
        if avg_soil < lo - 7:
            # Way too cold — soil not even close. Cap total temp score hard.
            soil_gate_open = False
            soil_gate_factor = 0.1
            details["soil_gate"] = f"BLOCKED ({avg_soil:.0f}F < {lo}F)"
        elif avg_soil < lo:
            # Below threshold but approaching — partial credit
            soil_gate_factor = 0.4
            details["soil_gate"] = f"approaching ({avg_soil:.0f}F)"
        else:
            # Threshold met
            temp_score += max_pts * sub.get("soil", 0.15)
            if avg_soil > hi:
                temp_score += max_pts * sub.get("soil", 0.15) * 0.3  # past peak but ok

    if avg_high is not None:
        lo, hi = mt["temp_ideal_high"]
        ok_lo, ok_hi = mt["temp_ok_high"]
        if lo <= avg_high <= hi:
            temp_score += max_pts * sub.get("high", 0.30)
        elif ok_lo <= avg_high <= ok_hi:
            temp_score += max_pts * sub.get("high", 0.30) * 0.5

    if avg_low is not None:
        lo, hi = mt["temp_ideal_low"]
        if lo <= avg_low <= hi:
            temp_score += max_pts * sub.get("low", 0.20)
        elif lo - 5 <= avg_low <= hi + 5:
            temp_score += max_pts * sub.get("low", 0.20) * 0.5

    # Warming trend — the actual trigger, biggest piece of temp score
    soil_temps = weather.get("forecast_soil_temp", [])
    trend_sub = sub.get("soil_trend", 0.35)
    if len(soil_temps) >= 6:
        first_half = np.mean(soil_temps[:len(soil_temps)//2])
        second_half = np.mean(soil_temps[len(soil_temps)//2:])
        trend = second_half - first_half
        if trend > 3:
            temp_score += max_pts * trend_sub
            details["soil_trend"] = f"WARMING (+{trend:.0f}F)"
        elif trend > 1:
            temp_score += max_pts * trend_sub * 0.65
            details["soil_trend"] = f"warming (+{trend:.0f}F)"
        elif trend > -1:
            temp_score += max_pts * trend_sub * 0.25
            details["soil_trend"] = "stable"
        else:
            details["soil_trend"] = f"cooling ({trend:.0f}F)"
    elif avg_soil is not None:
        details["soil_trend"] = "insufficient data"

    # Apply soil gate — if soil is too cold, scale down entire temp score
    temp_score = temp_score * soil_gate_factor
    scores["temperature"] = min(round(temp_score), max_pts)

    # ── Moisture ──
    max_pts = w.get("moisture", 25)
    moisture_score = 0
    precip_14d = wx.get("precip_14d_val", 0)
    melt = wx.get("melt_score", 0)

    for threshold, frac in mt.get("precip_thresholds", [(1.5, 0.4), (0.5, 0.25), (0.1, 0.1)]):
        if precip_14d > threshold:
            moisture_score += max_pts * frac
            break

    melt_weight = mt.get("melt_weight", 0.5)
    moisture_score += max_pts * melt_weight * max(melt, 0)

    sm_range = mt.get("soil_moisture_ideal", (0.2, 0.45))
    sm_weight = mt.get("soil_moisture_weight", 0.1)
    avg_sm = wx.get("avg_sm")
    if avg_sm is not None and sm_range[0] <= avg_sm <= sm_range[1]:
        moisture_score += max_pts * sm_weight

    scores["moisture"] = min(round(moisture_score), max_pts)

    # ── Elevation ──
    max_pts = w.get("elevation", 15)
    elev_score = 0
    if elev is not None:
        month = datetime.now().month
        base = mt.get("elev_base", 4500)
        rng = mt.get("elev_range", 2500)
        shift = mt.get("elev_shift_per_month", 300)
        ideal_low = base + (month - 4) * shift
        ideal_high = ideal_low + rng

        es = mt.get("elev_scoring", {"in_band": 1.0, "within_500ft": 0.6, "within_1000ft": 0.25})
        if ideal_low <= elev <= ideal_high:
            elev_score = round(max_pts * es["in_band"])
        elif ideal_low - 500 <= elev <= ideal_high + 500:
            elev_score = round(max_pts * es["within_500ft"])
        elif ideal_low - 1000 <= elev <= ideal_high + 1000:
            elev_score = round(max_pts * es["within_1000ft"])

        details["elevation"] = f"{elev:.0f}ft"
        details["ideal_band"] = f"{ideal_low:.0f}-{ideal_high:.0f}ft"
    scores["elevation"] = elev_score

    # ── Terrain bonus ──
    terrain_max = mt.get("terrain_bonus_max", 5)
    terrain_bonus = 0
    if terrain and terrain.get("slope") is not None:
        slope = terrain["slope"]
        aspect = terrain["aspect"]
        details["slope"] = f"{slope:.0f}deg"
        details["aspect"] = f"{aspect:.0f}deg ({aspect_label(aspect)})"

        asp = mt.get("aspect_scores", {"south": 3, "east_west": 1, "north": 0})
        if 135 <= aspect <= 225:
            terrain_bonus += asp["south"]
        elif 90 <= aspect <= 270:
            terrain_bonus += asp["east_west"]

        sl = mt.get("slope_scores", {"moderate": 2, "flat": 1, "steep": 0})
        if 5 <= slope <= 25:
            terrain_bonus += sl["moderate"]
        elif slope < 5:
            terrain_bonus += sl["flat"]

    scores["terrain"] = min(terrain_bonus, terrain_max)

    # ── Burn Quality / Forest Maturity ──
    burn_key = "burn_quality" if mt.get("needs_fire") else "forest_maturity"
    max_pts = w.get(burn_key, 30)
    burn_score = 0

    if mt.get("needs_fire"):
        # Recency
        fire_date = fire.get("date")
        recency_curve = mt.get("recency_curve", [(8, 0.5), (14, 0.4), (20, 0.2), (30, 0.1)])
        if fire_date:
            try:
                fire_dt = datetime.strptime(fire_date, "%Y-%m-%d")
                months_ago = (datetime.now() - fire_dt).days / 30
                for max_months, frac in recency_curve:
                    if months_ago <= max_months:
                        burn_score += max_pts * frac
                        break
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

        # Burn type
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

        # Acreage
        acres = fire.get("acres", 0)
        for min_acres, frac in mt.get("acreage_curve", [(20, 0.15), (5, 0.1), (0, 0.05)]):
            if acres >= min_acres:
                burn_score += max_pts * frac
                break

        details["burn_type"] = fire.get("pfirs_burn_type") or ("RX" if fire.get("is_rx") else "wildfire")
        details["burn_acres"] = f"{acres:.1f}ac"
    else:
        # Non-fire mushrooms: penalize recent burns
        fire_date = fire.get("date")
        if fire_date:
            try:
                years_ago = (datetime.now() - datetime.strptime(fire_date, "%Y-%m-%d")).days / 365
                if years_ago < 3:
                    burn_score = 0
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

    # ── Season gate ──
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
