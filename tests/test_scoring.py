"""
Tests for the scoring engine.

These define expected behavior for known weather scenarios so we can
iterate on the scoring logic without guessing at outcomes.
"""

import pytest
from scoring import score_burn_site, make_day_weather, extract_weather_details


# ── Helpers ──

def make_fire(burn_type="Underburn", acres=30, months_ago=5):
    """Create a fire dict for testing."""
    from datetime import datetime, timedelta
    date = (datetime.now() - timedelta(days=months_ago * 30)).strftime("%Y-%m-%d")
    return {
        "is_rx": True,
        "date": date,
        "acres": acres,
        "pfirs_burn_type": burn_type,
    }


def make_weather(soil_temps, highs, lows, precip_14d, snow_depths=None):
    """
    Create a weather dict for testing.
    soil_temps: list of 14 daily soil temps (F) — index 7 = today
    highs/lows: list of 14 daily air temps (F)
    precip_14d: total inches in last 14 days
    snow_depths: list of 14 daily snow depths (inches)
    """
    return {
        "hist_temps_max": [],
        "hist_temps_min": [],
        "hist_precip": [precip_14d / 14] * 30,  # spread evenly
        "hist_snowfall": [],
        "forecast_temps_max": highs,
        "forecast_temps_min": lows,
        "forecast_soil_temp": soil_temps,
        "forecast_soil_moisture": [0.3] * 14,
        "forecast_snow_depth": snow_depths or [0] * 14,
        "current_temp": highs[7] if len(highs) > 7 else 55,
    }


GOOD_TERRAIN = {"slope": 12, "aspect": 180}  # south-facing moderate slope
NORTH_FLAT = {"slope": 2, "aspect": 10}       # north-facing flat
EAST_STEEP = {"slope": 30, "aspect": 90}      # east-facing steep


# ══════════════════════════════════════════════════════════════════
# A. Soil Threshold Gate
# ══════════════════════════════════════════════════════════════════

class TestSoilThresholdGate:

    def test_frozen_soil_kills_score(self):
        """35F soil should produce near-zero total regardless of other factors."""
        weather = make_weather(
            soil_temps=[35] * 14,
            highs=[60] * 14, lows=[40] * 14,
            precip_14d=2.0,
        )
        fire = make_fire(burn_type="Underburn", acres=50, months_ago=5)
        result = score_burn_site(fire, weather, 5500, "morel", GOOD_TERRAIN)
        assert result["total"] < 30, f"Frozen soil scored {result['total']} — should be <30"

    def test_ideal_soil_gets_full_marks(self):
        """52F soil should get full soil_threshold score."""
        weather = make_weather(
            soil_temps=[52] * 14,
            highs=[65] * 14, lows=[40] * 14,
            precip_14d=2.0,
        )
        fire = make_fire()
        result = score_burn_site(fire, weather, 5500, "morel", GOOD_TERRAIN)
        assert result["scores"]["soil_threshold"] == 25

    def test_approaching_soil_gets_partial(self):
        """43F soil — above gate but below ideal — should get partial credit."""
        weather = make_weather(
            soil_temps=[43] * 14,
            highs=[55] * 14, lows=[35] * 14,
            precip_14d=2.0,
        )
        fire = make_fire()
        result = score_burn_site(fire, weather, 5500, "morel", GOOD_TERRAIN)
        s = result["scores"]["soil_threshold"]
        assert 3 <= s <= 15, f"Approaching soil scored {s} — expected 3-15"

    def test_gate_scales_other_factors(self):
        """When soil is below gate (35F), warming_trend and moisture should also be reduced."""
        weather = make_weather(
            soil_temps=[35] * 14,
            highs=[60] * 14, lows=[40] * 14,
            precip_14d=2.0,
        )
        fire = make_fire()
        result = score_burn_site(fire, weather, 5500, "morel", GOOD_TERRAIN)
        # The gate should reduce warming_trend even though temps are flat (not warming)
        assert result["scores"]["warming_trend"] <= 5

    def test_soil_58_is_ideal(self):
        """58F is within ideal range (48-58F)."""
        weather = make_weather(
            soil_temps=[58] * 14,
            highs=[65] * 14, lows=[42] * 14, precip_14d=2.0,
        )
        fire = make_fire()
        result = score_burn_site(fire, weather, 5500, "morel", GOOD_TERRAIN)
        assert result["scores"]["soil_threshold"] == 25

    def test_soil_65_acceptable(self):
        """65F is above ideal but within acceptable (45-62F) — should get partial."""
        weather = make_weather(
            soil_temps=[65] * 14,
            highs=[75] * 14, lows=[50] * 14, precip_14d=1.0,
        )
        fire = make_fire()
        result = score_burn_site(fire, weather, 5500, "morel", GOOD_TERRAIN)
        s = result["scores"]["soil_threshold"]
        assert 10 <= s <= 20, f"65F soil scored {s} — expected 10-20 (acceptable range)"


# ══════════════════════════════════════════════════════════════════
# B. Warming Trend
# ══════════════════════════════════════════════════════════════════

class TestWarmingTrend:

    def test_strong_warming_beats_flat(self):
        """Soil rising from 40->55F should outscore flat 50F."""
        warming = make_weather(
            soil_temps=[40, 42, 44, 46, 48, 50, 52, 53, 54, 55, 55, 55, 55, 55],
            highs=[60] * 14, lows=[35] * 14, precip_14d=2.0,
        )
        flat = make_weather(
            soil_temps=[50] * 14,
            highs=[60] * 14, lows=[35] * 14, precip_14d=2.0,
        )
        fire = make_fire()
        r_warming = score_burn_site(fire, warming, 5500, "morel", GOOD_TERRAIN)
        r_flat = score_burn_site(fire, flat, 5500, "morel", GOOD_TERRAIN)
        assert r_warming["scores"]["warming_trend"] > r_flat["scores"]["warming_trend"]

    def test_cooling_scores_zero(self):
        """Soil dropping from 55->40F should score 0 on warming trend."""
        weather = make_weather(
            soil_temps=[55, 54, 52, 50, 48, 46, 44, 43, 42, 41, 40, 40, 40, 40],
            highs=[50] * 14, lows=[30] * 14, precip_14d=2.0,
        )
        fire = make_fire()
        result = score_burn_site(fire, weather, 5500, "morel", GOOD_TERRAIN)
        assert result["scores"]["warming_trend"] == 0

    def test_rapid_warming_gets_max(self):
        """Consistent +1.5F/day warming should get near-max trend score."""
        weather = make_weather(
            soil_temps=[35, 37, 38, 40, 42, 44, 46, 48, 50, 52, 54, 56, 58, 60],
            highs=[60] * 14, lows=[35] * 14, precip_14d=2.0,
        )
        fire = make_fire()
        result = score_burn_site(fire, weather, 5500, "morel", GOOD_TERRAIN)
        assert result["scores"]["warming_trend"] >= 20, \
            f"Rapid warming scored {result['scores']['warming_trend']} — expected 20+"

    def test_slight_warming_moderate_score(self):
        """Gentle +0.3F/day warming should get moderate score."""
        weather = make_weather(
            soil_temps=[48, 48, 48, 49, 49, 49, 50, 50, 50, 51, 51, 51, 52, 52],
            highs=[60] * 14, lows=[35] * 14, precip_14d=2.0,
        )
        fire = make_fire()
        result = score_burn_site(fire, weather, 5500, "morel", GOOD_TERRAIN)
        s = result["scores"]["warming_trend"]
        assert 10 <= s <= 18, f"Slight warming scored {s} — expected 10-18"

    def test_single_spike_doesnt_inflate(self):
        """One 72F spike day among 50F days should not produce high trend."""
        weather = make_weather(
            soil_temps=[50, 50, 50, 50, 50, 72, 50, 50, 50, 50, 50, 50, 50, 50],
            highs=[60] * 14, lows=[35] * 14, precip_14d=2.0,
        )
        fire = make_fire()
        result = score_burn_site(fire, weather, 5500, "morel", GOOD_TERRAIN)
        # Linear regression should see near-zero slope despite spike
        assert result["scores"]["warming_trend"] <= 10, \
            f"Single spike scored {result['scores']['warming_trend']} — should be <=10"


# ══════════════════════════════════════════════════════════════════
# C. Cold Snap Scenarios
# ══════════════════════════════════════════════════════════════════

class TestColdSnap:

    def test_snow_day_scores_low(self):
        """Day with snow + freezing temps should score much lower than warm day."""
        warm_day = make_weather(
            soil_temps=[50, 51, 52, 53, 54, 55, 55, 55, 55, 55, 55, 55, 55, 55],
            highs=[55, 58, 60, 62, 63, 65, 65, 65, 65, 65, 65, 65, 65, 65],
            lows=[35, 36, 38, 40, 40, 42, 42, 42, 42, 42, 42, 42, 42, 42],
            precip_14d=1.5,
            snow_depths=[0] * 14,
        )
        cold_snap = make_weather(
            soil_temps=[50, 51, 52, 53, 54, 55, 55, 40, 35, 33, 30, 30, 35, 40],
            highs=[55, 58, 60, 62, 63, 65, 65, 38, 32, 28, 26, 30, 40, 48],
            lows=[35, 36, 38, 40, 40, 42, 42, 25, 20, 18, 15, 20, 28, 35],
            precip_14d=2.0,
            snow_depths=[0, 0, 0, 0, 0, 0, 0, 0, 2, 5, 8, 6, 3, 0],
        )
        fire = make_fire()
        r_warm = score_burn_site(fire, warm_day, 5500, "morel", GOOD_TERRAIN)
        r_cold = score_burn_site(fire, cold_snap, 5500, "morel", GOOD_TERRAIN)
        assert r_cold["total"] < r_warm["total"] - 20, \
            f"Cold snap {r_cold['total']} vs warm {r_warm['total']} — gap should be >20"

    def test_deep_snow_negative_moisture(self):
        """10+ inches of snow should produce negative melt score."""
        weather = make_weather(
            soil_temps=[35] * 14,
            highs=[30] * 14, lows=[15] * 14,
            precip_14d=3.0,
            snow_depths=[12] * 14,
        )
        fire = make_fire()
        result = score_burn_site(fire, weather, 5500, "morel", GOOD_TERRAIN)
        # Deep snowpack should not help moisture
        assert result["scores"]["recent_moisture"] <= 10


# ══════════════════════════════════════════════════════════════════
# D. Per-Day Scoring (make_day_weather)
# ══════════════════════════════════════════════════════════════════

class TestPerDayScoring:

    def test_day0_vs_day3_cold_snap(self):
        """If forecast shows cold snap on day 3, day 3 should score much lower than day 0."""
        weather = make_weather(
            soil_temps=[50, 51, 52, 53, 54, 55, 55, 55, 40, 35, 30, 30, 35, 40],
            highs=[60, 62, 63, 65, 65, 65, 65, 65, 40, 32, 26, 30, 42, 50],
            lows=[38, 40, 40, 42, 42, 42, 42, 42, 25, 20, 15, 20, 30, 35],
            precip_14d=1.5,
            snow_depths=[0, 0, 0, 0, 0, 0, 0, 0, 0, 3, 6, 4, 1, 0],
        )
        fire = make_fire()

        day0_wx = make_day_weather(weather, 0)
        day3_wx = make_day_weather(weather, 3)

        r0 = score_burn_site(fire, day0_wx, 5500, "morel", GOOD_TERRAIN)
        r3 = score_burn_site(fire, day3_wx, 5500, "morel", GOOD_TERRAIN)

        assert r3["total"] < r0["total"] - 15, \
            f"Day 3 cold snap: {r3['total']} vs day 0: {r0['total']} — gap should be >15"

    def test_day0_soil_uses_today_value(self):
        """Day 0 should use today's soil temp (index 7), not average."""
        weather = make_weather(
            soil_temps=[60, 62, 63, 65, 64, 62, 60, 35, 30, 28, 25, 28, 35, 42],
            highs=[65] * 14, lows=[40] * 14, precip_14d=2.0,
        )
        day0_wx = make_day_weather(weather, 0)
        details = extract_weather_details(day0_wx)
        assert details["avg_soil"] < 45, \
            f"Day 0 soil temp {details['avg_soil']} — should be <45 (today is 35F)"

    def test_days_monotonically_respond_to_cold_snap(self):
        """Days closer to a cold snap should score progressively lower."""
        weather = make_weather(
            soil_temps=[52, 53, 54, 55, 55, 55, 55, 55, 45, 38, 32, 30, 35, 42],
            highs=[62, 63, 65, 65, 65, 65, 65, 65, 45, 35, 28, 32, 45, 55],
            lows=[40, 40, 42, 42, 42, 42, 42, 42, 30, 22, 18, 22, 32, 38],
            precip_14d=1.5,
            snow_depths=[0, 0, 0, 0, 0, 0, 0, 0, 0, 2, 5, 3, 0, 0],
        )
        fire = make_fire()
        scores = []
        for d in range(5):
            dw = make_day_weather(weather, d)
            r = score_burn_site(fire, dw, 5500, "morel", GOOD_TERRAIN)
            scores.append(r["total"])
        # Day 0 should be highest, day 3 (cold snap peak) should be lowest
        assert scores[0] > scores[3], \
            f"Day 0 ({scores[0]}) should beat day 3 ({scores[3]})"
        assert scores[3] < scores[0] - 10, \
            f"Day 3 ({scores[3]}) should be >10 less than day 0 ({scores[0]})"

    def test_recovery_after_cold_snap(self):
        """Days after a cold snap, as temps recover, scores should improve."""
        weather = make_weather(
            soil_temps=[55, 55, 55, 55, 55, 55, 55, 35, 30, 28, 30, 38, 45, 50],
            highs=[65, 65, 65, 65, 65, 65, 65, 35, 28, 26, 32, 42, 52, 58],
            lows=[42, 42, 42, 42, 42, 42, 42, 22, 18, 15, 20, 28, 35, 40],
            precip_14d=1.5,
            snow_depths=[0, 0, 0, 0, 0, 0, 0, 2, 5, 6, 3, 1, 0, 0],
        )
        fire = make_fire()
        dw2 = make_day_weather(weather, 2)  # day 2 = peak cold (index 9)
        dw6 = make_day_weather(weather, 6)  # day 6 = recovery (index 13)
        r2 = score_burn_site(fire, dw2, 5500, "morel", GOOD_TERRAIN)
        r6 = score_burn_site(fire, dw6, 5500, "morel", GOOD_TERRAIN)
        assert r6["total"] > r2["total"], \
            f"Recovery day ({r6['total']}) should beat cold peak ({r2['total']})"


# ══════════════════════════════════════════════════════════════════
# E. make_day_weather Windows
# ══════════════════════════════════════════════════════════════════

class TestMakeDayWeather:

    def test_soil_temps_end_at_target_day(self):
        """The target window's last element should be the target day's value."""
        weather = make_weather(
            soil_temps=[40, 42, 44, 46, 48, 50, 52, 54, 56, 58, 60, 62, 64, 66],
            highs=[60] * 14, lows=[40] * 14, precip_14d=1.0,
        )
        # Day 0 = index 7 = 54F
        dw0 = make_day_weather(weather, 0)
        target0 = dw0["forecast_soil_temp_target"]
        assert target0[-1] == 54, f"Day 0 target soil should be 54F, got {target0[-1]}"

        # Day 3 = index 10 = 60F
        dw3 = make_day_weather(weather, 3)
        target3 = dw3["forecast_soil_temp_target"]
        assert target3[-1] == 60, f"Day 3 target soil should be 60F, got {target3[-1]}"

    def test_snow_window_ends_at_target(self):
        """Snow depth window should end at the target day."""
        weather = make_weather(
            soil_temps=[50] * 14, highs=[60] * 14, lows=[40] * 14,
            precip_14d=1.0,
            snow_depths=[0, 0, 0, 0, 0, 0, 0, 0, 0, 3, 6, 4, 1, 0],
        )
        # Day 3 = index 10, snow should be 6
        dw3 = make_day_weather(weather, 3)
        snow = dw3["forecast_snow_depth"]
        assert snow[-1] == 6, f"Day 3 snow should be 6in, got {snow[-1]}"

    def test_day0_highs_are_near_today(self):
        """Day 0 air temps should reflect today, not a week ago."""
        weather = make_weather(
            soil_temps=[50] * 14,
            highs=[70, 70, 70, 70, 70, 70, 70, 40, 35, 30, 28, 32, 40, 50],
            lows=[40] * 14, precip_14d=1.0,
        )
        dw0 = make_day_weather(weather, 0)
        highs = dw0["forecast_temps_max"]
        # Should include today (40F), not just past warm days
        assert max(highs) <= 70
        assert min(highs) <= 45, \
            f"Day 0 highs {highs} should include today's cold (40F)"

    def test_day5_highs_reflect_forecast(self):
        """Day 5 air temps should reflect the forecast, not today."""
        weather = make_weather(
            soil_temps=[50] * 14,
            highs=[60, 60, 60, 60, 60, 60, 60, 60, 40, 35, 30, 28, 55, 58],
            lows=[40] * 14, precip_14d=1.0,
        )
        dw5 = make_day_weather(weather, 5)
        highs = dw5["forecast_temps_max"]
        # Day 5 = index 12. Should see the recovery temps (55, 58)
        assert any(h >= 50 for h in highs), \
            f"Day 5 highs {highs} should reflect forecast recovery"


# ══════════════════════════════════════════════════════════════════
# F. Burn Quality
# ══════════════════════════════════════════════════════════════════

class TestBurnQuality:

    def test_fresh_burn_penalized(self):
        """1-month-old burn should score lower than 5-month-old."""
        weather = make_weather(
            soil_temps=[52] * 14, highs=[60] * 14, lows=[40] * 14, precip_14d=2.0,
        )
        fresh = make_fire(months_ago=1)
        prime = make_fire(months_ago=5)

        r_fresh = score_burn_site(fresh, weather, 5500, "morel", GOOD_TERRAIN)
        r_prime = score_burn_site(prime, weather, 5500, "morel", GOOD_TERRAIN)

        assert r_prime["scores"]["burn_quality"] > r_fresh["scores"]["burn_quality"]

    def test_old_burn_scores_low(self):
        """3-year-old burn should score near zero on burn quality."""
        weather = make_weather(
            soil_temps=[52] * 14, highs=[60] * 14, lows=[40] * 14, precip_14d=2.0,
        )
        old = make_fire(months_ago=36)
        result = score_burn_site(old, weather, 5500, "morel", GOOD_TERRAIN)
        assert result["scores"]["burn_quality"] <= 3

    def test_underburn_beats_pile(self):
        """Underburn should score higher than hand pile (same age/size)."""
        weather = make_weather(
            soil_temps=[52] * 14, highs=[60] * 14, lows=[40] * 14, precip_14d=2.0,
        )
        underburn = make_fire(burn_type="Underburn", acres=30, months_ago=5)
        pile = make_fire(burn_type="Hand Pile", acres=30, months_ago=5)

        r_under = score_burn_site(underburn, weather, 5500, "morel", GOOD_TERRAIN)
        r_pile = score_burn_site(pile, weather, 5500, "morel", GOOD_TERRAIN)

        assert r_under["scores"]["burn_quality"] > r_pile["scores"]["burn_quality"]

    def test_large_burn_beats_small(self):
        """50ac burn should outscore 2ac burn (same type/age)."""
        weather = make_weather(
            soil_temps=[52] * 14, highs=[60] * 14, lows=[40] * 14, precip_14d=2.0,
        )
        big = make_fire(acres=50, months_ago=5)
        small = make_fire(acres=2, months_ago=5)

        r_big = score_burn_site(big, weather, 5500, "morel", GOOD_TERRAIN)
        r_small = score_burn_site(small, weather, 5500, "morel", GOOD_TERRAIN)

        assert r_big["scores"]["burn_quality"] > r_small["scores"]["burn_quality"]

    def test_prime_window_5_months(self):
        """5-month-old burn should get best recency score."""
        weather = make_weather(
            soil_temps=[52] * 14, highs=[60] * 14, lows=[40] * 14, precip_14d=2.0,
        )
        fire = make_fire(months_ago=5)
        result = score_burn_site(fire, weather, 5500, "morel", GOOD_TERRAIN)
        s = result["scores"]["burn_quality"]
        assert s >= 10, f"5-month burn quality {s} — expected 10+"


# ══════════════════════════════════════════════════════════════════
# G. Terrain / Aspect
# ══════════════════════════════════════════════════════════════════

class TestTerrain:

    def test_south_facing_beats_north(self):
        """South-facing slope should outscore north-facing."""
        weather = make_weather(
            soil_temps=[52] * 14, highs=[60] * 14, lows=[40] * 14, precip_14d=2.0,
        )
        fire = make_fire()
        r_south = score_burn_site(fire, weather, 5500, "morel", GOOD_TERRAIN)
        r_north = score_burn_site(fire, weather, 5500, "morel", NORTH_FLAT)
        assert r_south["scores"]["sun_aspect"] > r_north["scores"]["sun_aspect"]

    def test_steep_slope_no_bonus(self):
        """30-degree slope should get 0 slope bonus."""
        weather = make_weather(
            soil_temps=[52] * 14, highs=[60] * 14, lows=[40] * 14, precip_14d=2.0,
        )
        fire = make_fire()
        result = score_burn_site(fire, weather, 5500, "morel", EAST_STEEP)
        # East aspect gets 2, steep slope gets 0 — should be less than south moderate
        r_good = score_burn_site(fire, weather, 5500, "morel", GOOD_TERRAIN)
        assert result["scores"]["sun_aspect"] < r_good["scores"]["sun_aspect"]

    def test_no_terrain_still_scores(self):
        """Missing terrain data should not crash, terrain score = 0."""
        weather = make_weather(
            soil_temps=[52] * 14, highs=[60] * 14, lows=[40] * 14, precip_14d=2.0,
        )
        fire = make_fire()
        result = score_burn_site(fire, weather, 5500, "morel", terrain=None)
        assert result["scores"]["sun_aspect"] >= 0
        assert result["total"] > 0


# ══════════════════════════════════════════════════════════════════
# H. Elevation
# ══════════════════════════════════════════════════════════════════

class TestElevation:

    def test_ideal_elevation_full_marks(self):
        """5500ft in April should be in the ideal band."""
        weather = make_weather(
            soil_temps=[52] * 14, highs=[60] * 14, lows=[40] * 14, precip_14d=2.0,
        )
        fire = make_fire()
        result = score_burn_site(fire, weather, 5500, "morel", GOOD_TERRAIN)
        assert result["scores"]["sun_aspect"] >= 5  # elevation contributes to sun_aspect

    def test_too_low_scores_zero(self):
        """2000ft should be way below the band — zero elevation points."""
        weather = make_weather(
            soil_temps=[52] * 14, highs=[60] * 14, lows=[40] * 14, precip_14d=2.0,
        )
        fire = make_fire()
        r_low = score_burn_site(fire, weather, 2000, "morel", GOOD_TERRAIN)
        r_ideal = score_burn_site(fire, weather, 5500, "morel", GOOD_TERRAIN)
        assert r_low["scores"]["sun_aspect"] < r_ideal["scores"]["sun_aspect"]

    def test_no_elevation_still_works(self):
        """None elevation should not crash."""
        weather = make_weather(
            soil_temps=[52] * 14, highs=[60] * 14, lows=[40] * 14, precip_14d=2.0,
        )
        fire = make_fire()
        result = score_burn_site(fire, weather, None, "morel", GOOD_TERRAIN)
        assert result["total"] > 0


# ══════════════════════════════════════════════════════════════════
# I. Moisture
# ══════════════════════════════════════════════════════════════════

class TestMoisture:

    def test_wet_beats_dry(self):
        """2 inches of precip should outscore 0 precip."""
        wet = make_weather(
            soil_temps=[52] * 14, highs=[60] * 14, lows=[40] * 14, precip_14d=2.0,
        )
        dry = make_weather(
            soil_temps=[52] * 14, highs=[60] * 14, lows=[40] * 14, precip_14d=0.0,
        )
        fire = make_fire()
        r_wet = score_burn_site(fire, wet, 5500, "morel", GOOD_TERRAIN)
        r_dry = score_burn_site(fire, dry, 5500, "morel", GOOD_TERRAIN)
        assert r_wet["scores"]["recent_moisture"] > r_dry["scores"]["recent_moisture"]

    def test_active_melt_high_moisture(self):
        """Snow going from 5in to 0in = active melt = high moisture score."""
        weather = make_weather(
            soil_temps=[50] * 14, highs=[55] * 14, lows=[35] * 14,
            precip_14d=1.0,
            snow_depths=[5, 5, 4, 3, 2, 1, 0.5, 0.2, 0, 0, 0, 0, 0, 0],
        )
        fire = make_fire()
        result = score_burn_site(fire, weather, 5500, "morel", GOOD_TERRAIN)
        assert result["scores"]["recent_moisture"] >= 12, \
            f"Active melt moisture {result['scores']['recent_moisture']} — expected 12+"


# ══════════════════════════════════════════════════════════════════
# J. Season Gate
# ══════════════════════════════════════════════════════════════════

class TestSeasonGate:

    def test_in_season_not_halved(self):
        """April-July should get full scores."""
        from unittest.mock import patch
        from datetime import datetime
        weather = make_weather(
            soil_temps=[52] * 14, highs=[60] * 14, lows=[40] * 14, precip_14d=2.0,
        )
        fire = make_fire()
        with patch("scoring.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 5, 15)
            mock_dt.strptime = datetime.strptime
            result = score_burn_site(fire, weather, 5500, "morel", GOOD_TERRAIN)
        assert result["details"]["in_season"] == "YES"

    def test_out_of_season_halved(self):
        """October should halve all scores."""
        from unittest.mock import patch
        from datetime import datetime
        weather = make_weather(
            soil_temps=[52] * 14, highs=[60] * 14, lows=[40] * 14, precip_14d=2.0,
        )
        fire = make_fire()
        with patch("scoring.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 10, 15)
            mock_dt.strptime = datetime.strptime
            r_oct = score_burn_site(fire, weather, 5500, "morel", GOOD_TERRAIN)
        with patch("scoring.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 5, 15)
            mock_dt.strptime = datetime.strptime
            r_may = score_burn_site(fire, weather, 5500, "morel", GOOD_TERRAIN)
        assert r_oct["total"] < r_may["total"] * 0.6


# ══════════════════════════════════════════════════════════════════
# K. Integration / Sanity
# ══════════════════════════════════════════════════════════════════

class TestIntegration:

    def test_perfect_conditions_score_high(self):
        """Ideal everything: 52F soil warming, wet, 5mo underburn, south slope, 5500ft."""
        weather = make_weather(
            soil_temps=[44, 46, 48, 49, 50, 51, 52, 52, 53, 53, 54, 54, 55, 55],
            highs=[58, 60, 62, 63, 65, 65, 65, 65, 65, 65, 65, 65, 65, 65],
            lows=[35, 36, 38, 40, 40, 42, 42, 42, 42, 42, 42, 42, 42, 42],
            precip_14d=2.0,
            snow_depths=[1, 0.5, 0.2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
        )
        fire = make_fire(burn_type="Underburn", acres=40, months_ago=5)
        result = score_burn_site(fire, weather, 5500, "morel", GOOD_TERRAIN)
        assert result["total"] >= 75, \
            f"Perfect conditions scored {result['total']} — should be 75+"

    def test_worst_conditions_score_low(self):
        """Frozen, dry, old burn, north flat, wrong elevation."""
        weather = make_weather(
            soil_temps=[30] * 14,
            highs=[35] * 14, lows=[20] * 14,
            precip_14d=0.0,
            snow_depths=[15] * 14,
        )
        fire = make_fire(burn_type="Hand Pile", acres=1, months_ago=36)
        result = score_burn_site(fire, weather, 2000, "morel", NORTH_FLAT)
        assert result["total"] < 20, \
            f"Worst conditions scored {result['total']} — should be <20"

    def test_score_range_is_0_to_100(self):
        """No scenario should produce a score outside 0-100 (plus terrain bonus)."""
        for soil in [30, 45, 52, 65]:
            for precip in [0, 1, 3]:
                weather = make_weather(
                    soil_temps=[soil] * 14,
                    highs=[60] * 14, lows=[35] * 14,
                    precip_14d=precip,
                )
                fire = make_fire()
                result = score_burn_site(fire, weather, 5500, "morel", GOOD_TERRAIN)
                assert 0 <= result["total"] <= 105, \
                    f"Score {result['total']} out of range for soil={soil} precip={precip}"
