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
        """When soil is below gate (35F), soil_gdd and moisture should also be reduced."""
        weather = make_weather(
            soil_temps=[35] * 14,
            highs=[60] * 14, lows=[40] * 14,
            precip_14d=2.0,
        )
        fire = make_fire()
        result = score_burn_site(fire, weather, 5500, "morel", GOOD_TERRAIN)
        # The gate should reduce soil_gdd via gate factor
        assert result["scores"]["soil_gdd"] <= 8

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

class TestSoilGDD:
    """GDD = cumulative growing degree-days (base 32F). Literature: 365-580 = onset."""

    def test_high_gdd_beats_low(self):
        """Warm soil history (high GDD) should outscore cold history (low GDD)."""
        warm = make_weather(
            soil_temps=[55] * 14, highs=[65] * 14, lows=[42] * 14, precip_14d=2.0,
        )
        # Add warm hist soil temps: 30 days at 55F = 30*23 = 690 GDD from history alone
        warm["hist_soil_temp"] = [55] * 30

        cold = make_weather(
            soil_temps=[40] * 14, highs=[45] * 14, lows=[30] * 14, precip_14d=2.0,
        )
        cold["hist_soil_temp"] = [38] * 30  # 30 * 6 = 180 GDD

        fire = make_fire()
        r_warm = score_burn_site(fire, warm, 5500, "morel", GOOD_TERRAIN)
        r_cold = score_burn_site(fire, cold, 5500, "morel", GOOD_TERRAIN)
        assert r_warm["scores"]["soil_gdd"] > r_cold["scores"]["soil_gdd"]

    def test_gdd_in_onset_range_scores_high(self):
        """GDD of ~450 (in 365-580 range) should score well."""
        # 30 days at 47F avg = 30 * 15 = 450 GDD from history
        weather = make_weather(
            soil_temps=[50] * 14, highs=[60] * 14, lows=[35] * 14, precip_14d=2.0,
        )
        weather["hist_soil_temp"] = [47] * 30
        fire = make_fire()
        result = score_burn_site(fire, weather, 5500, "morel", GOOD_TERRAIN)
        assert result["scores"]["soil_gdd"] >= 17, \
            f"GDD ~450 scored {result['scores']['soil_gdd']} — expected 17+"

    def test_very_low_gdd_scores_zero(self):
        """GDD < 200 (30 days of freezing) should score near zero."""
        weather = make_weather(
            soil_temps=[35] * 14, highs=[40] * 14, lows=[25] * 14, precip_14d=1.0,
        )
        weather["hist_soil_temp"] = [33] * 30  # 30 * 1 + 14 * 3 = 72 GDD
        fire = make_fire()
        result = score_burn_site(fire, weather, 5500, "morel", GOOD_TERRAIN)
        assert result["scores"]["soil_gdd"] <= 3, \
            f"Very low GDD scored {result['scores']['soil_gdd']} — expected <=3"

    def test_gdd_reported_in_details(self):
        """Result details should include the computed GDD value."""
        weather = make_weather(
            soil_temps=[50] * 14, highs=[60] * 14, lows=[40] * 14, precip_14d=1.5,
        )
        weather["hist_soil_temp"] = [48] * 30
        fire = make_fire()
        result = score_burn_site(fire, weather, 5500, "morel", GOOD_TERRAIN)
        assert "soil_gdd" in result["details"]

    def test_no_hist_soil_uses_forecast_only(self):
        """Without historical soil temp, GDD uses only 14-day forecast temps."""
        weather = make_weather(
            soil_temps=[52] * 14, highs=[60] * 14, lows=[40] * 14, precip_14d=2.0,
        )
        # No hist_soil_temp — should still compute from forecast soil temps
        fire = make_fire()
        result = score_burn_site(fire, weather, 5500, "morel", GOOD_TERRAIN)
        assert result["scores"]["soil_gdd"] >= 0
        assert "soil_gdd" in result["details"]

    def test_cooling_trend_reduces_gdd_score(self):
        """GDD score should be penalized when soil temp is trending downward."""
        weather_warming = make_weather(
            soil_temps=[45, 47, 49, 50, 51, 52, 53, 54, 55, 55, 55, 55, 55, 55],
            highs=[60] * 14, lows=[38] * 14, precip_14d=2.0,
        )
        weather_warming["hist_soil_temp"] = [40, 41, 42, 43, 44, 44, 45, 45, 46, 46,
                                             47, 47, 48, 48, 49, 49, 50, 50, 50, 50,
                                             51, 51, 51, 52, 52, 52, 53, 53, 53, 53]
        weather_cooling = make_weather(
            soil_temps=[55, 54, 52, 50, 48, 46, 44, 43, 42, 41, 40, 40, 40, 40],
            highs=[50] * 14, lows=[30] * 14, precip_14d=2.0,
        )
        weather_cooling["hist_soil_temp"] = [55, 55, 54, 54, 53, 53, 52, 52, 51, 51,
                                             50, 50, 50, 49, 49, 48, 48, 47, 47, 46,
                                             46, 45, 45, 44, 44, 43, 43, 42, 42, 42]
        fire = make_fire()
        r_warm = score_burn_site(fire, weather_warming, 5500, "morel", GOOD_TERRAIN)
        r_cool = score_burn_site(fire, weather_cooling, 5500, "morel", GOOD_TERRAIN)
        # Both have similar total GDD but cooling should score lower
        assert r_warm["scores"]["soil_gdd"] > r_cool["scores"]["soil_gdd"], \
            f"Warming GDD {r_warm['scores']['soil_gdd']} should beat cooling {r_cool['scores']['soil_gdd']}"

    def test_freeze_after_warmth_penalizes(self):
        """Soil at 55F then dropping to 30F should trigger freeze damage penalty."""
        weather = make_weather(
            soil_temps=[50, 52, 54, 55, 55, 55, 55, 55, 40, 35, 30, 28, 32, 38],
            highs=[60] * 14, lows=[35] * 14, precip_14d=2.0,
        )
        weather["hist_soil_temp"] = [50] * 30
        fire = make_fire()
        result = score_burn_site(fire, weather, 5500, "morel", GOOD_TERRAIN)
        assert "freeze_damage" in result["details"], \
            "Should detect freeze after warmth"
        # Score should be reduced
        assert result["scores"]["soil_gdd"] < 20, \
            f"Freeze-damaged GDD scored {result['scores']['soil_gdd']} — expected <20"

    def test_no_freeze_penalty_without_prior_warmth(self):
        """Cold soil that never warmed up shouldn't get freeze 'damage' — it was never growing."""
        weather = make_weather(
            soil_temps=[35, 34, 33, 32, 31, 30, 30, 30, 30, 30, 30, 30, 30, 30],
            highs=[40] * 14, lows=[25] * 14, precip_14d=1.0,
        )
        weather["hist_soil_temp"] = [33] * 30
        fire = make_fire()
        result = score_burn_site(fire, weather, 5500, "morel", GOOD_TERRAIN)
        assert "freeze_damage" not in result["details"], \
            "No freeze damage if soil was never warm enough to start growth"

    def test_trend_uses_full_history_not_just_forecast(self):
        """Trend should use full hist+forecast, not just 14-day forecast.
        Bug: short forecast window with high variance inflated slope to +2.3F/day
        when actual full-history slope was +0.2F/day."""
        weather = make_weather(
            # Forecast: noisy but roughly flat around 50F
            soil_temps=[46, 50, 49, 53, 58, 64, 61, 57, 34, 42, 60, 60, 58, 53],
            highs=[60] * 14, lows=[38] * 14, precip_14d=1.5,
        )
        # 30-day history: oscillating 33-52F, slight upward trend
        weather["hist_soil_temp"] = [33, 48, 46, 50, 51, 52, 53, 55, 54, 51,
                                     40, 35, 40, 33, 35, 45, 50, 52, 52, 47,
                                     43, 39, 35, 35, 35, 34, 42, 37, 47, 50]
        fire = make_fire()
        result = score_burn_site(fire, weather, 5500, "morel", GOOD_TERRAIN)
        trend = result["details"].get("soil_trend_per_day", 0)
        # With full 44-day history, trend should be modest (~0.2F/day), not 2.3F/day
        assert abs(trend) < 1.0, \
            f"Trend {trend}F/day — should be <1.0 with full history (was 2.3 with forecast only)"


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
        # 30 days of warming soil history — GDD should be in onset range
        weather["hist_soil_temp"] = [42, 43, 44, 44, 45, 45, 46, 46, 47, 47,
                                     48, 48, 49, 49, 50, 50, 50, 51, 51, 51,
                                     52, 52, 52, 53, 53, 53, 54, 54, 54, 55]
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

    def test_real_truckee_data(self):
        """Test with actual Truckee April 2026 data patterns — noisy, not smooth."""
        weather = make_weather(
            # Real forecast: 74 to 42 to 68 swing
            soil_temps=[53, 57, 59, 61, 66, 74, 68, 66, 42, 51, 68, 69, 66, 60],
            highs=[45, 48, 50, 49, 53, 62, 61, 57, 42, 37, 50, 55, 49, 45],
            lows=[23, 30, 30, 31, 28, 27, 34, 38, 26, 23, 20, 27, 34, 30],
            precip_14d=1.6,
            snow_depths=[0.6, 0, 0, 0, 0, 0, 0, 0, 0.1, 0.3, 0.2, 0.1, 0, 0],
        )
        weather["hist_soil_temp"] = [49, 46, 38, 38, 46, 46, 50, 49, 55, 55,
                                     35, 42, 48, 52, 53, 50, 40, 38, 43, 48,
                                     50, 52, 54, 48, 42, 45, 50, 52, 48, 50]
        fire = make_fire(burn_type="Underburn", acres=30, months_ago=5)
        result = score_burn_site(fire, weather, 5800, "morel", GOOD_TERRAIN)
        # Should produce a reasonable score, not crash or produce extremes
        assert 40 <= result["total"] <= 90, \
            f"Real Truckee data scored {result['total']} — expected 40-90"
        # Trend should be modest with noisy oscillating data
        trend = result["details"].get("soil_trend_per_day", 0)
        assert abs(trend) < 1.5, \
            f"Noisy data trend {trend} — should be moderate, not extreme"

    def test_real_cold_snap_wednesday(self):
        """Real pattern: warm week then snow Wednesday (day 3)."""
        weather = make_weather(
            soil_temps=[53, 57, 59, 61, 66, 74, 68, 66, 42, 51, 68, 69, 66, 60],
            highs=[45, 48, 50, 49, 53, 62, 61, 57, 42, 37, 50, 55, 49, 45],
            lows=[23, 30, 30, 31, 28, 27, 34, 38, 26, 23, 20, 27, 34, 30],
            precip_14d=1.6,
            snow_depths=[0.6, 0, 0, 0, 0, 0, 0, 0, 0.1, 0.3, 0.2, 0.1, 0, 0],
        )
        weather["hist_soil_temp"] = [45, 47, 48, 50, 52, 50, 48, 50, 52, 55,
                                     53, 50, 48, 50, 52, 54, 52, 50, 48, 50,
                                     52, 53, 54, 55, 53, 50, 52, 54, 55, 55]
        fire = make_fire()
        day0_wx = make_day_weather(weather, 0)  # today: warm
        day3_wx = make_day_weather(weather, 3)  # wednesday: cold snap, snow
        r0 = score_burn_site(fire, day0_wx, 5500, "morel", GOOD_TERRAIN)
        r3 = score_burn_site(fire, day3_wx, 5500, "morel", GOOD_TERRAIN)
        # Day 3 has 42F soil + snow — should score meaningfully lower
        assert r3["total"] < r0["total"], \
            f"Cold snap day 3 ({r3['total']}) should be lower than day 0 ({r0['total']})"

    def test_noisy_precip_rain_events(self):
        """Real precip pattern: mostly dry with a few big events."""
        weather = make_weather(
            soil_temps=[52] * 14, highs=[60] * 14, lows=[38] * 14,
            precip_14d=1.6,  # this gets spread evenly in make_weather
        )
        # Override with real pattern: mostly 0 with spikes
        weather["hist_precip"] = [0, 0, 0, 0.8, 0, 0, 0, 0.1, 0, 0,
                                  0, 0, 0, 0, 0.5, 0.3, 0, 0, 0, 0,
                                  0.29, 0.50, 0.78, 0.01, 0, 0, 0, 0, 0, 0]
        weather["hist_soil_temp"] = [48] * 30
        fire = make_fire()
        result = score_burn_site(fire, weather, 5500, "morel", GOOD_TERRAIN)
        # Should detect rain events (3 events > 0.4in)
        assert "rain_events" in result["details"], "Should report rain events"

    def test_snow_appears_mid_forecast(self):
        """Snow absent then appearing mid-forecast should affect score."""
        weather = make_weather(
            soil_temps=[55, 55, 55, 55, 55, 55, 55, 55, 40, 35, 38, 45, 50, 52],
            highs=[60] * 14, lows=[38] * 14,
            precip_14d=1.5,
            snow_depths=[0, 0, 0, 0, 0, 0, 0, 0, 3, 5, 4, 2, 0, 0],
        )
        weather["hist_soil_temp"] = [50] * 30
        fire = make_fire()
        # Day 0 (no snow, warm) vs Day 3 (snow, cold)
        day0_wx = make_day_weather(weather, 0)
        day3_wx = make_day_weather(weather, 3)
        r0 = score_burn_site(fire, day0_wx, 5500, "morel", GOOD_TERRAIN)
        r3 = score_burn_site(fire, day3_wx, 5500, "morel", GOOD_TERRAIN)
        assert r0["total"] > r3["total"], \
            f"Clear day 0 ({r0['total']}) should beat snowy day 3 ({r3['total']})"

    def test_extreme_soil_swing_doesnt_crash(self):
        """Soil going 74->42->68 in 3 days should not produce NaN or crash."""
        weather = make_weather(
            soil_temps=[50, 52, 55, 60, 74, 42, 68, 55, 50, 48, 52, 55, 53, 50],
            highs=[60] * 14, lows=[35] * 14, precip_14d=1.5,
        )
        weather["hist_soil_temp"] = [45, 48, 50, 52, 55, 42, 38, 45, 50, 55,
                                     60, 55, 48, 45, 50, 52, 48, 42, 45, 50,
                                     52, 55, 50, 48, 52, 55, 53, 50, 52, 50]
        fire = make_fire()
        result = score_burn_site(fire, weather, 5500, "morel", GOOD_TERRAIN)
        assert 0 <= result["total"] <= 105
        assert result["details"].get("soil_trend_per_day") is not None

    def test_real_prosser_creek(self):
        """Prosser Creek: moderate soil, snow clearing, 4 rain events."""
        weather = make_weather(
            soil_temps=[53, 57, 59, 61, 66, 74, 68, 66, 42, 51, 69, 69, 66, 60],
            highs=[44, 47, 49, 48, 53, 62, 59, 57, 42, 41, 56, 61, 54, 48],
            lows=[22, 29, 32, 31, 27, 28, 35, 39, 27, 23, 22, 33, 37, 31],
            precip_14d=1.4,
            snow_depths=[0.8, 0.3, 0, 0, 0, 0, 0, 0, 0.1, 0.1, 0.1, 0, 0, 0],
        )
        weather["hist_soil_temp"] = [40, 41, 45, 46, 48, 50, 52, 48, 45, 43,
                                     42, 44, 46, 48, 50, 52, 53, 50, 48, 46,
                                     48, 45, 38, 37, 46, 46, 48, 48, 54, 54]
        weather["hist_precip"] = [0]*20 + [0.18, 0.55, 0.62, 0.02, 0, 0, 0.01, 0, 0, 0]
        fire = make_fire(burn_type="Underburn", acres=17, months_ago=6)
        result = score_burn_site(fire, weather, 5734, "morel", GOOD_TERRAIN)
        assert 40 <= result["total"] <= 90
        # Should have rain events detected
        assert result["details"].get("rain_events_30d", 0) >= 1 or "rain_events" in result["details"]

    def test_real_soda_springs_deep_snow(self):
        """Soda Springs: high elevation, still has 2.7in snow, cold soil history."""
        weather = make_weather(
            soil_temps=[47, 51, 50, 54, 59, 65, 62, 58, 35, 43, 61, 61, 59, 54],
            highs=[38, 39, 40, 39, 44, 50, 48, 45, 35, 32, 43, 48, 43, 38],
            lows=[25, 24, 27, 20, 19, 30, 32, 32, 24, 22, 16, 25, 29, 26],
            precip_14d=3.0,
            snow_depths=[2.7, 2.1, 1.8, 1.5, 1.2, 0.9, 0.5, 0.3, 1.2, 1.2, 0.6, 0.2, 0.1, 0],
        )
        weather["hist_soil_temp"] = [33, 33, 33, 34, 34, 35, 35, 34, 33, 33,
                                     34, 34, 35, 36, 36, 35, 34, 34, 33, 33,
                                     39, 34, 33, 33, 33, 34, 34, 34, 34, 40]
        fire = make_fire(burn_type="Machine Pile", acres=18, months_ago=3)
        result = score_burn_site(fire, weather, 6825, "morel", GOOD_TERRAIN)
        # Snow mostly melted (0.3in left at day 0), soil warming to 47F.
        # Low GDD from cold history (33F avg) should hold score down, but
        # active melt + moisture means it's coming into season.
        # Verify GDD is low (cold history) even if total is moderate
        # GDD should be moderate — cold 30-day history (33F avg) but warm forecast
        # pushes total GDD up. Shouldn't be max though.
        assert result["scores"]["soil_gdd"] <= 20, \
            f"Cold-history Soda Springs GDD score {result['scores']['soil_gdd']} — expected <=20"

    def test_real_dog_valley_warm_dry(self):
        """Dog Valley: warm soil (70F), no snow, but only 1 rain event — drier."""
        weather = make_weather(
            soil_temps=[56, 60, 59, 57, 63, 70, 69, 68, 47, 55, 67, 70, 67, 60],
            highs=[51, 56, 58, 52, 56, 68, 67, 65, 48, 48, 59, 62, 59, 53],
            lows=[33, 34, 41, 33, 29, 33, 47, 49, 34, 31, 31, 39, 41, 37],
            precip_14d=0.9,
            snow_depths=[0] * 14,
        )
        weather["hist_soil_temp"] = [50, 52, 55, 58, 60, 58, 55, 53, 55, 58,
                                     60, 62, 60, 58, 55, 58, 60, 62, 60, 58,
                                     63, 62, 56, 56, 62, 60, 60, 57, 64, 70]
        weather["hist_precip"] = [0]*20 + [0.54, 0.10, 0.27, 0, 0, 0, 0.02, 0, 0, 0]
        fire = make_fire(burn_type="Underburn", acres=117, months_ago=0.3)
        result = score_burn_site(fire, weather, 4874, "morel",
                                 {"slope": 12, "aspect": 185})
        # Warm but dry — moisture should be the limiting factor
        assert result["scores"]["recent_moisture"] <= 12, \
            f"Dry Dog Valley moisture {result['scores']['recent_moisture']} — expected <=12"

    def test_real_nevada_city_low_elevation(self):
        """Nevada City: 2536ft, too low for April band, but warm + wet."""
        weather = make_weather(
            soil_temps=[57, 63, 63, 66, 71, 74, 74, 64, 50, 59, 69, 71, 70, 62],
            highs=[55, 57, 60, 60, 62, 67, 68, 60, 48, 52, 62, 65, 59, 51],
            lows=[39, 42, 47, 45, 41, 48, 51, 46, 43, 39, 37, 42, 46, 43],
            precip_14d=3.1,
            snow_depths=[0] * 14,
        )
        weather["hist_soil_temp"] = [48, 50, 52, 55, 58, 60, 58, 55, 53, 50,
                                     48, 50, 52, 55, 58, 60, 62, 60, 58, 55,
                                     54, 50, 43, 53, 55, 57, 60, 62, 64, 64]
        fire = make_fire(acres=20, months_ago=5)
        result = score_burn_site(fire, weather, 2536, "morel", GOOD_TERRAIN)
        # Too low elevation for April — sun_aspect should lose elev points
        assert result["scores"]["sun_aspect"] <= 7, \
            f"2536ft in April sun_aspect {result['scores']['sun_aspect']} — expected <=7"

    def test_real_south_lake_cold_snap(self):
        """South Lake: forecast shows soil dropping from 66 to 39 (freeze risk)."""
        weather = make_weather(
            soil_temps=[45, 52, 51, 54, 60, 66, 63, 62, 39, 49, 61, 64, 61, 57],
            highs=[41, 47, 48, 48, 49, 58, 58, 56, 43, 41, 52, 57, 54, 50],
            lows=[22, 24, 33, 30, 25, 30, 35, 41, 26, 22, 28, 35, 37, 34],
            precip_14d=1.9,
            snow_depths=[0.9, 0.4, 0, 0, 0, 0, 0, 0, 0.4, 0.4, 0.1, 0, 0, 0],
        )
        weather["hist_soil_temp"] = [40, 42, 45, 48, 50, 48, 45, 42, 40, 42,
                                     45, 48, 50, 52, 50, 48, 45, 42, 45, 48,
                                     50, 44, 41, 41, 41, 41, 41, 39, 48, 53]
        fire = make_fire(months_ago=5)
        # Score day 0 (warm, 62F soil) vs day 1 (cold snap, 39F at index 8)
        from scoring import make_day_weather
        day0_wx = make_day_weather(weather, 0)
        day1_wx = make_day_weather(weather, 1)  # index 8 = 39F
        r0 = score_burn_site(fire, day0_wx, 6235, "morel", GOOD_TERRAIN)
        r1 = score_burn_site(fire, day1_wx, 6235, "morel", GOOD_TERRAIN)
        assert r0["total"] > r1["total"], \
            f"Warm day 0 ({r0['total']}) should beat cold snap day 1 ({r1['total']})"

    def test_real_stampede_moderate(self):
        """Stampede: moderate conditions, soil 54F, some snow clearing."""
        weather = make_weather(
            soil_temps=[53, 61, 57, 57, 64, 72, 66, 66, 44, 54, 65, 68, 65, 60],
            highs=[43, 49, 51, 49, 54, 63, 61, 58, 41, 40, 56, 60, 53, 48],
            lows=[25, 31, 34, 30, 28, 30, 37, 40, 29, 26, 22, 32, 36, 30],
            precip_14d=0.8,
            snow_depths=[0.7, 0.2, 0, 0, 0, 0, 0, 0, 0, 0.1, 0.1, 0, 0, 0],
        )
        weather["hist_soil_temp"] = [42, 43, 45, 46, 48, 50, 48, 45, 43, 42,
                                     44, 46, 48, 50, 52, 50, 48, 46, 48, 50,
                                     48, 45, 37, 37, 45, 47, 47, 46, 54, 54]
        fire = make_fire(burn_type="Hand Pile", acres=20, months_ago=5)
        result = score_burn_site(fire, weather, 6055, "morel", GOOD_TERRAIN)
        # Should be a reasonable mid-range score
        assert 45 <= result["total"] <= 85, \
            f"Stampede scored {result['total']} — expected 45-85"

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


# ══════════════════════════════════════════════════════════════════
# L. "Now" Scenarios — realistic edge cases for day-0 scoring
# ══════════════════════════════════════════════════════════════════

class TestNowScenarios:
    """These simulate real conditions you'd check before going out."""

    def test_spring_morning_frost_but_warming(self):
        """Frosty mornings (28F lows) but soil is 50F and warming — should still score well."""
        weather = make_weather(
            soil_temps=[45, 46, 47, 48, 49, 50, 50, 51, 51, 52, 52, 52, 53, 53],
            highs=[55, 58, 60, 60, 62, 62, 63, 63, 63, 63, 63, 63, 63, 63],
            lows=[25, 26, 27, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28],
            precip_14d=1.5,
        )
        fire = make_fire(months_ago=5)
        result = score_burn_site(fire, weather, 5500, "morel", GOOD_TERRAIN)
        assert result["total"] >= 60, \
            f"Frosty mornings + warming soil scored {result['total']} — should be 60+"

    def test_rain_event_after_dry_spell(self):
        """Dry for 3 weeks then 2in rain — should boost moisture significantly."""
        precip = [0] * 20 + [0.3, 0.5, 0.4, 0.3, 0.2, 0.1, 0.1, 0.05, 0.02, 0.01]
        weather = {
            "hist_temps_max": [], "hist_temps_min": [],
            "hist_precip": precip,
            "hist_snowfall": [],
            "forecast_temps_max": [60] * 14, "forecast_temps_min": [38] * 14,
            "forecast_soil_temp": [52] * 14,
            "forecast_soil_moisture": [0.35] * 14,
            "forecast_snow_depth": [0] * 14,
            "current_temp": 60,
        }
        fire = make_fire()
        result = score_burn_site(fire, weather, 5500, "morel", GOOD_TERRAIN)
        assert result["scores"]["recent_moisture"] >= 8, \
            f"Rain after dry spell moisture: {result['scores']['recent_moisture']} — expected 8+"

    def test_wildfire_vs_rx_burn(self):
        """Wildfire should score lower than RX burn on burn quality."""
        weather = make_weather(
            soil_temps=[52] * 14, highs=[60] * 14, lows=[40] * 14, precip_14d=2.0,
        )
        rx = make_fire(burn_type="Underburn", months_ago=5)
        wildfire = {"is_rx": False, "date": rx["date"], "acres": 30,
                    "pfirs_burn_type": ""}
        r_rx = score_burn_site(rx, weather, 5500, "morel", GOOD_TERRAIN)
        r_wild = score_burn_site(wildfire, weather, 5500, "morel", GOOD_TERRAIN)
        assert r_rx["scores"]["burn_quality"] > r_wild["scores"]["burn_quality"]

    def test_high_elevation_late_season(self):
        """7500ft in April should score lower on elevation than 5500ft."""
        weather = make_weather(
            soil_temps=[48] * 14, highs=[50] * 14, lows=[30] * 14, precip_14d=2.0,
        )
        fire = make_fire()
        r_high = score_burn_site(fire, weather, 7500, "morel", GOOD_TERRAIN)
        r_mid = score_burn_site(fire, weather, 5500, "morel", GOOD_TERRAIN)
        # 7500ft is at upper edge of April band — should get less than 5500ft
        assert r_mid["scores"]["sun_aspect"] >= r_high["scores"]["sun_aspect"]

    def test_very_wet_but_cold_is_bad(self):
        """3in of rain but soil at 38F — moisture is there but soil gate kills it."""
        weather = make_weather(
            soil_temps=[38] * 14,
            highs=[45] * 14, lows=[30] * 14,
            precip_14d=3.0,
        )
        fire = make_fire()
        result = score_burn_site(fire, weather, 5500, "morel", GOOD_TERRAIN)
        assert result["total"] < 40, \
            f"Wet but cold scored {result['total']} — should be <40 (soil gate)"

    def test_hot_dry_summer_day(self):
        """85F highs, 65F soil, no rain — past prime, should score lower than ideal."""
        weather = make_weather(
            soil_temps=[65] * 14,
            highs=[85] * 14, lows=[55] * 14,
            precip_14d=0.0,
        )
        weather["hist_soil_temp"] = [60] * 30  # warm history = high GDD
        fire = make_fire()
        result = score_burn_site(fire, weather, 5500, "morel", GOOD_TERRAIN)
        # High GDD but no moisture = not great. Should be below ideal conditions.
        assert result["total"] < 75, \
            f"Hot dry summer scored {result['total']} — should be <75"

    def test_ideal_day_high_score(self):
        """The textbook perfect morel day: 55F, moist, recent burn, south slope."""
        weather = make_weather(
            soil_temps=[48, 49, 50, 50, 51, 52, 52, 53, 53, 54, 54, 54, 55, 55],
            highs=[60, 62, 63, 65, 65, 65, 65, 65, 65, 65, 65, 65, 65, 65],
            lows=[35, 36, 38, 38, 40, 40, 40, 40, 40, 40, 40, 40, 40, 40],
            precip_14d=1.8,
            snow_depths=[2, 1, 0.5, 0.2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
        )
        fire = make_fire(burn_type="Underburn", acres=50, months_ago=6)
        result = score_burn_site(fire, weather, 5500, "morel", GOOD_TERRAIN)
        assert result["total"] >= 70, \
            f"Textbook day scored {result['total']} — should be 70+"

    def test_two_week_old_burn_in_perfect_weather(self):
        """2-week-old burn — too fresh penalty even with perfect conditions."""
        weather = make_weather(
            soil_temps=[48, 49, 50, 51, 52, 53, 53, 54, 54, 54, 55, 55, 55, 55],
            highs=[65] * 14, lows=[40] * 14, precip_14d=2.0,
        )
        fresh = make_fire(burn_type="Underburn", acres=50, months_ago=0.5)
        prime = make_fire(burn_type="Underburn", acres=50, months_ago=5)
        r_fresh = score_burn_site(fresh, weather, 5500, "morel", GOOD_TERRAIN)
        r_prime = score_burn_site(prime, weather, 5500, "morel", GOOD_TERRAIN)
        assert r_prime["total"] > r_fresh["total"], \
            f"Fresh burn {r_fresh['total']} should be less than prime {r_prime['total']}"

    def test_flat_soil_temp_low_warming(self):
        """Soil stuck at 50F for 2 weeks — no warming trend despite good threshold."""
        weather = make_weather(
            soil_temps=[50] * 14,
            highs=[60] * 14, lows=[38] * 14, precip_14d=1.5,
        )
        fire = make_fire()
        result = score_burn_site(fire, weather, 5500, "morel", GOOD_TERRAIN)
        # Flat 50F soil for 14 days with no history = 14*18 = 252 GDD
        # Below onset (365) so should be moderate, not high
        assert result["scores"]["soil_gdd"] <= 15, \
            f"Low GDD scored {result['scores']['soil_gdd']} — should be <=15"

    def test_soil_temp_details_in_output(self):
        """Result should include soil_temp, soil_trend, and soil_trend_per_day."""
        weather = make_weather(
            soil_temps=[45, 46, 47, 48, 49, 50, 51, 52, 53, 54, 55, 55, 55, 55],
            highs=[60] * 14, lows=[38] * 14, precip_14d=1.5,
        )
        fire = make_fire()
        result = score_burn_site(fire, weather, 5500, "morel", GOOD_TERRAIN)
        assert "soil_temp" in result["details"]
        assert "soil_trend" in result["details"]
        assert "soil_trend_per_day" in result["details"]


# ══════════════════════════════════════════════════════════════════
# M. Predictive Scenarios — multi-day scoring behavior
# ══════════════════════════════════════════════════════════════════

class TestPredictiveScenarios:
    """Test that per-day scoring correctly reflects forecast changes."""

    def test_multiday_returns_8_days(self):
        """score_burn_multiday should return exactly 8 day scores."""
        from scoring import score_burn_multiday
        weather = make_weather(
            soil_temps=[50] * 14, highs=[60] * 14, lows=[40] * 14, precip_14d=1.5,
        )
        fire = make_fire()
        days = score_burn_multiday(fire, weather, 5500, GOOD_TERRAIN, "morel", days=8)
        assert len(days) == 8
        assert all("total" in d for d in days)
        assert all("scores" in d for d in days)

    def test_multiday_day_indices(self):
        """Each day score should have the correct day index."""
        from scoring import score_burn_multiday
        weather = make_weather(
            soil_temps=[50] * 14, highs=[60] * 14, lows=[40] * 14, precip_14d=1.0,
        )
        fire = make_fire()
        days = score_burn_multiday(fire, weather, 5500, GOOD_TERRAIN)
        for i, d in enumerate(days):
            assert d["day"] == i

    def test_warming_week_scores_increase(self):
        """If soil warms steadily over the forecast, later days should score higher."""
        weather = make_weather(
            soil_temps=[40, 41, 42, 43, 44, 45, 46, 48, 50, 52, 54, 55, 56, 57],
            highs=[50, 52, 54, 56, 58, 60, 62, 64, 65, 66, 67, 68, 68, 68],
            lows=[30, 31, 32, 33, 34, 35, 36, 38, 40, 40, 42, 42, 42, 42],
            precip_14d=1.5,
        )
        fire = make_fire()
        day0_wx = make_day_weather(weather, 0)
        day5_wx = make_day_weather(weather, 5)
        r0 = score_burn_site(fire, day0_wx, 5500, "morel", GOOD_TERRAIN)
        r5 = score_burn_site(fire, day5_wx, 5500, "morel", GOOD_TERRAIN)
        # Day 5 has warmer soil — should score higher on soil_threshold
        assert r5["scores"]["soil_threshold"] >= r0["scores"]["soil_threshold"], \
            f"Day 5 soil ({r5['scores']['soil_threshold']}) should >= day 0 ({r0['scores']['soil_threshold']})"

    def test_cold_snap_then_recovery_v_shape(self):
        """Scores should form a V: high now, drop mid-week, recover by weekend."""
        from scoring import score_burn_multiday
        weather = make_weather(
            soil_temps=[52, 53, 54, 55, 55, 55, 55, 55, 42, 38, 35, 38, 45, 52],
            highs=[62, 63, 65, 65, 65, 65, 65, 65, 42, 35, 30, 38, 52, 60],
            lows=[38, 40, 42, 42, 42, 42, 42, 42, 28, 22, 18, 25, 35, 40],
            precip_14d=1.5,
            snow_depths=[0, 0, 0, 0, 0, 0, 0, 0, 2, 5, 6, 3, 0.5, 0],
        )
        fire = make_fire()
        days = score_burn_multiday(fire, weather, 5500, GOOD_TERRAIN)
        # Day 0 should be good, day 3 should dip, day 6 should recover
        assert days[0]["total"] > days[3]["total"], \
            f"Day 0 ({days[0]['total']}) should beat cold snap day 3 ({days[3]['total']})"
        assert days[6]["total"] > days[3]["total"], \
            f"Recovery day 6 ({days[6]['total']}) should beat day 3 ({days[3]['total']})"

    def test_stable_weather_stable_scores(self):
        """If weather is constant across forecast, all days should score similarly."""
        from scoring import score_burn_multiday
        weather = make_weather(
            soil_temps=[52] * 14, highs=[62] * 14, lows=[40] * 14, precip_14d=1.5,
        )
        fire = make_fire()
        days = score_burn_multiday(fire, weather, 5500, GOOD_TERRAIN)
        totals = [d["total"] for d in days]
        spread = max(totals) - min(totals)
        assert spread <= 10, \
            f"Stable weather score spread {spread} — should be <=10"

    def test_snow_day_soil_threshold_drops(self):
        """Day with snow on ground should have lower soil_threshold than clear day."""
        weather = make_weather(
            soil_temps=[52, 52, 52, 52, 52, 52, 52, 52, 38, 35, 32, 35, 42, 50],
            highs=[60] * 14, lows=[40] * 14, precip_14d=1.5,
            snow_depths=[0, 0, 0, 0, 0, 0, 0, 0, 3, 6, 8, 5, 1, 0],
        )
        fire = make_fire()
        day0_wx = make_day_weather(weather, 0)
        day3_wx = make_day_weather(weather, 3)
        r0 = score_burn_site(fire, day0_wx, 5500, "morel", GOOD_TERRAIN)
        r3 = score_burn_site(fire, day3_wx, 5500, "morel", GOOD_TERRAIN)
        assert r0["scores"]["soil_threshold"] > r3["scores"]["soil_threshold"], \
            f"Day 0 soil ({r0['scores']['soil_threshold']}) should beat snowy day 3 ({r3['scores']['soil_threshold']})"

    def test_forecast_drying_reduces_moisture(self):
        """If forecast shows no more rain, moisture should decline for later days."""
        # Heavy recent rain but forecast is dry
        weather = make_weather(
            soil_temps=[52] * 14, highs=[65] * 14, lows=[40] * 14,
            precip_14d=2.5,  # past rain
            snow_depths=[0] * 14,
        )
        fire = make_fire()
        # Moisture score is currently based on hist_precip which doesn't shift per day
        # This test documents the current behavior — moisture stays constant
        day0_wx = make_day_weather(weather, 0)
        day5_wx = make_day_weather(weather, 5)
        r0 = score_burn_site(fire, day0_wx, 5500, "morel", GOOD_TERRAIN)
        r5 = score_burn_site(fire, day5_wx, 5500, "morel", GOOD_TERRAIN)
        # Currently both get same moisture — this is a known limitation
        # The test passes but documents that we should fix this later
        assert abs(r0["scores"]["recent_moisture"] - r5["scores"]["recent_moisture"]) <= 5

    def test_burn_quality_stable_across_days(self):
        """Burn quality should not change across forecast days (burn age is fixed)."""
        from scoring import score_burn_multiday
        weather = make_weather(
            soil_temps=[52] * 14, highs=[60] * 14, lows=[40] * 14, precip_14d=1.5,
        )
        fire = make_fire()
        days = score_burn_multiday(fire, weather, 5500, GOOD_TERRAIN)
        bq_scores = [d["scores"]["burn_quality"] for d in days]
        assert len(set(bq_scores)) == 1, \
            f"Burn quality should be constant across days, got {bq_scores}"

    def test_best_day_identification(self):
        """Should be able to find the highest-scoring day programmatically."""
        from scoring import score_burn_multiday
        weather = make_weather(
            soil_temps=[45, 47, 49, 50, 51, 52, 53, 55, 56, 57, 55, 50, 48, 47],
            highs=[55, 58, 60, 62, 64, 65, 66, 67, 65, 60, 55, 52, 50, 52],
            lows=[32, 34, 36, 38, 40, 42, 42, 42, 40, 36, 32, 30, 28, 30],
            precip_14d=1.5,
        )
        fire = make_fire()
        days = score_burn_multiday(fire, weather, 5500, GOOD_TERRAIN)
        best_day = max(days, key=lambda d: d["total"])
        # Best day should be around day 0-2 (soil at 55-57F, warming)
        # not day 5+ (soil dropping)
        assert best_day["day"] <= 3, \
            f"Best day is {best_day['day']} — expected 0-3 (peak warmth)"

    def test_each_day_has_details(self):
        """Every day score should include soil_temp, soil_trend, snow_status."""
        from scoring import score_burn_multiday
        weather = make_weather(
            soil_temps=[50, 51, 52, 53, 54, 55, 55, 55, 50, 45, 42, 45, 50, 53],
            highs=[60] * 14, lows=[38] * 14, precip_14d=1.5,
            snow_depths=[0, 0, 0, 0, 0, 0, 0, 0, 2, 4, 3, 1, 0, 0],
        )
        fire = make_fire()
        days = score_burn_multiday(fire, weather, 5500, GOOD_TERRAIN)
        for d in days:
            assert "soil_temp" in d["details"], f"Day {d['day']} missing soil_temp"
            assert "soil_trend" in d["details"], f"Day {d['day']} missing soil_trend"
