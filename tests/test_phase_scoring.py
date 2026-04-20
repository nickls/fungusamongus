"""
TDD: 21 scenarios for phase-based scoring model (v0.7.0).

Each scenario defines a 44-day weather timeline and the expected outcome.
Write these FIRST, then build classify_day/build_timeline/score_readiness to pass them.

The scoring model classifies each day as START/GROW/BAD, then looks at the
rolling window to determine readiness phase (EMERGING/GROWING/WAITING/TOO_EARLY).
"""

import pytest


# ── Helpers to build 44-day weather data ──

def make_timeline_weather(soil_temps, precip_daily, snow_depths=None):
    """
    Build a weather dict from 44 daily values (30 hist + 14 forecast).
    soil_temps: list of 44 daily soil temps (F)
    precip_daily: list of 44 daily precip (inches) — or 30 for hist only
    snow_depths: list of 44 daily snow depths (inches) — or None for no snow
    """
    assert len(soil_temps) == 44, f"Need 44 soil temps, got {len(soil_temps)}"
    hist_soil = soil_temps[:30]
    fc_soil = soil_temps[30:]
    hist_precip = precip_daily[:30] if len(precip_daily) >= 30 else precip_daily + [0] * (30 - len(precip_daily))
    if snow_depths is None:
        snow_depths = [0] * 44
    # forecast_snow_depth is 14 values (7 past + 7 future from forecast API)
    # For simplicity in tests, take last 14 of snow_depths
    fc_snow = snow_depths[30:]
    return {
        "hist_soil_temp": hist_soil,
        "forecast_soil_temp": fc_soil,
        "hist_precip": hist_precip,
        "hist_snowfall": [],
        "hist_temps_max": [t + 10 for t in soil_temps[:30]],  # rough proxy
        "hist_temps_min": [t - 10 for t in soil_temps[:30]],
        "forecast_temps_max": [t + 10 for t in fc_soil],
        "forecast_temps_min": [t - 10 for t in fc_soil],
        "forecast_snow_depth": fc_snow,
        "forecast_soil_moisture": [0.3] * 14,
        "current_temp": soil_temps[30] + 10,
    }


def ramp(start, end, days):
    """Generate a linear ramp from start to end over N days."""
    if days <= 1:
        return [end]
    return [start + (end - start) * i / (days - 1) for i in range(days)]


def constant(val, days):
    """Generate a constant value for N days."""
    return [val] * days


def make_fire(burn_type="Underburn", acres=30, months_ago=5):
    from datetime import datetime, timedelta
    date = (datetime.now() - timedelta(days=months_ago * 30)).strftime("%Y-%m-%d")
    return {
        "is_rx": True, "date": date, "acres": acres, "pfirs_burn_type": burn_type,
    }


GOOD_TERRAIN = {"slope": 12, "aspect": 180}


# ══════════════════════════════════════════════════════════════════════
# GOOD scenarios — should produce phase=EMERGING, readiness 70+
# ══════════════════════════════════════════════════════════════════════

class TestGoodScenarios:

    def test_G1_textbook_spring(self):
        """Steady warming 35→55F over 30 days, 3 rain events, no snow."""
        soil = ramp(35, 55, 30) + ramp(55, 57, 14)
        precip = [0]*8 + [0.5] + [0]*6 + [0.6] + [0]*6 + [0.8] + [0]*6 + [0]*14
        weather = make_timeline_weather(soil, precip)
        fire = make_fire()
        # TODO: result = score_burn_complete(fire, weather, 5500, GOOD_TERRAIN, "morel")
        # assert result["days"][0]["phase"] == "EMERGING"
        # assert result["days"][0]["readiness"] >= 70
        pytest.skip("Not implemented yet")

    def test_G2_post_snowmelt(self):
        """Snow melted 3 weeks ago, soil warmed 40→52F, melt moisture sustained."""
        soil = constant(33, 9) + ramp(33, 40, 3) + ramp(40, 52, 18) + ramp(52, 54, 14)
        precip = constant(0, 9) + constant(0.2, 21) + constant(0.1, 14)  # melt moisture
        snow = constant(12, 9) + ramp(12, 0, 6) + constant(0, 29)
        weather = make_timeline_weather(soil, precip, snow)
        fire = make_fire()
        pytest.skip("Not implemented yet")

    def test_G3_rain_triggered(self):
        """Warm and dry, then 1in rain 3 weeks ago triggered start, moist since."""
        soil = constant(50, 9) + constant(50, 21) + constant(55, 14)
        precip = constant(0, 9) + [1.0] + constant(0.15, 20) + constant(0.1, 14)
        weather = make_timeline_weather(soil, precip)
        fire = make_fire()
        pytest.skip("Not implemented yet")

    def test_G4_south_facing_early(self):
        """Soil crossed 43F early (3.5 weeks ago), 45-52F since with moisture."""
        soil = constant(38, 5) + ramp(38, 43, 2) + ramp(43, 52, 23) + ramp(52, 54, 14)
        precip = constant(0, 5) + constant(0.2, 25) + constant(0.1, 14)
        weather = make_timeline_weather(soil, precip)
        fire = make_fire()
        pytest.skip("Not implemented yet")

    def test_G5_recovery_after_brief_snap(self):
        """START 4wk ago, 10 GROW, 2 BAD (freeze), 10 more GROW. 2 < 3 threshold."""
        soil = (constant(38, 2) + ramp(38, 48, 5) +  # start ~day 5
                constant(50, 10) +  # grow
                [30, 30] +  # 2-day freeze
                constant(50, 11) +  # more grow
                constant(52, 14))  # forecast
        precip = constant(0.15, 44)
        weather = make_timeline_weather(soil, precip)
        fire = make_fire()
        pytest.skip("Not implemented yet")

    def test_G6_multiple_moisture_events(self):
        """Soil 48-55F for 3 weeks, 4 rain events >0.4in."""
        soil = constant(40, 9) + ramp(40, 48, 3) + constant(52, 18) + constant(54, 14)
        precip = [0]*10 + [0.5, 0, 0, 0, 0, 0.6, 0, 0, 0, 0, 0.8, 0, 0, 0, 0, 0.5, 0, 0, 0, 0] + [0.1]*14
        weather = make_timeline_weather(soil, precip)
        fire = make_fire()
        pytest.skip("Not implemented yet")

    def test_G7_real_truckee_data(self):
        """Use actual cached Prosser Creek weather pattern."""
        soil = ([40, 41, 45, 46, 48, 50, 52, 48, 45, 43,
                 42, 44, 46, 48, 50, 52, 53, 50, 48, 46,
                 48, 45, 38, 37, 46, 46, 48, 48, 54, 54] +
                [53, 57, 59, 61, 66, 74, 68, 66, 42, 51, 69, 69, 66, 60])
        precip = [0]*20 + [0.18, 0.55, 0.62, 0.02, 0, 0, 0.01, 0, 0, 0] + [0]*14
        weather = make_timeline_weather(soil, precip)
        fire = make_fire(burn_type="Underburn", acres=17, months_ago=6)
        # Real data — accept EMERGING or GROWING
        pytest.skip("Not implemented yet")


# ══════════════════════════════════════════════════════════════════════
# BAD scenarios — readiness <30, phase=TOO_EARLY or WAITING
# ══════════════════════════════════════════════════════════════════════

class TestBadScenarios:

    def test_B1_still_frozen(self):
        """Soil 28-35F, deep snowpack 24in+. No start possible."""
        soil = constant(32, 30) + constant(33, 14)
        precip = constant(0, 44)
        snow = constant(30, 44)
        weather = make_timeline_weather(soil, precip, snow)
        fire = make_fire()
        pytest.skip("Not implemented yet")

    def test_B2_warm_but_dry(self):
        """Soil 50-55F but zero precipitation. No moisture = no START."""
        soil = constant(52, 30) + constant(54, 14)
        precip = constant(0, 44)
        weather = make_timeline_weather(soil, precip)
        fire = make_fire()
        pytest.skip("Not implemented yet")

    def test_B3_freeze_killed_flush(self):
        """Had START, 8 GROW, then 5-day freeze (>3 threshold). Growth reset."""
        soil = (constant(38, 5) + ramp(38, 48, 5) +  # start
                constant(50, 8) +  # grow
                constant(28, 5) +  # 5-day freeze — kills it
                ramp(28, 45, 7) +  # recovering
                constant(48, 14))  # forecast
        precip = constant(0.15, 44)
        weather = make_timeline_weather(soil, precip)
        fire = make_fire()
        pytest.skip("Not implemented yet")

    def test_B4_too_early_just_started(self):
        """Soil was 30-35F for 25 days, just crossed 43F 4 days ago."""
        soil = constant(33, 26) + ramp(33, 46, 4) + ramp(46, 50, 14)
        precip = constant(0, 26) + constant(0.2, 18)
        weather = make_timeline_weather(soil, precip)
        fire = make_fire()
        pytest.skip("Not implemented yet")

    def test_B5_hot_past_season(self):
        """Soil 60-70F, air 85-95F, no rain in 3 weeks. Season over."""
        soil = ramp(55, 68, 30) + constant(70, 14)
        precip = constant(0, 44)
        weather = make_timeline_weather(soil, precip)
        fire = make_fire()
        pytest.skip("Not implemented yet")

    def test_B6_oscillating_never_sustained(self):
        """Soil bounces 40→50→38→48→35→52→40 every 3-4 days."""
        pattern = [40, 45, 50, 38, 42, 48, 35, 40, 52, 40]
        soil = (pattern * 3)[:30] + (pattern[:4] + [45]*10)  # 44 days
        precip = [0.3 if i % 5 == 0 else 0 for i in range(44)]
        weather = make_timeline_weather(soil, precip)
        fire = make_fire()
        pytest.skip("Not implemented yet")

    def test_B7_deep_snowpack(self):
        """3+ feet snow, soil 33F, no melt. All BAD."""
        soil = constant(33, 30) + constant(30, 14)
        precip = constant(0, 44)
        snow = constant(36, 44)
        weather = make_timeline_weather(soil, precip, snow)
        fire = make_fire()
        pytest.skip("Not implemented yet")


# ══════════════════════════════════════════════════════════════════════
# BORDERLINE scenarios — readiness 30-70, phase=GROWING or WAITING
# ══════════════════════════════════════════════════════════════════════

class TestBorderlineScenarios:

    def test_M1_almost_enough_grow(self):
        """START 2.5 weeks ago, 11 GROW days (need 14). Almost there."""
        soil = (constant(38, 12) + ramp(38, 48, 5) +  # start around day 14
                constant(50, 13) +  # 13 grow days (not quite 14)
                constant(52, 14))   # forecast
        precip = constant(0, 12) + constant(0.2, 32)
        weather = make_timeline_weather(soil, precip)
        fire = make_fire()
        pytest.skip("Not implemented yet")

    def test_M2_marginal_start(self):
        """Only 2 START days (need 3), but 18 GROW days since."""
        soil = (constant(38, 10) + [43, 44] +  # only 2 start days
                constant(50, 18) +  # long grow
                constant(52, 14))
        precip = constant(0, 10) + constant(0.2, 34)
        weather = make_timeline_weather(soil, precip)
        fire = make_fire()
        pytest.skip("Not implemented yet")

    def test_M3_two_day_cold_snap(self):
        """START 3wk ago, 12 GROW, 2 BAD (under threshold), 3 more GROW."""
        soil = (constant(38, 7) + ramp(38, 48, 5) +  # start
                constant(50, 12) +  # grow
                [32, 33] +  # 2-day cold (under 3-day reset)
                constant(50, 4) +  # more grow
                constant(52, 14))
        precip = constant(0.15, 44)
        weather = make_timeline_weather(soil, precip)
        fire = make_fire()
        pytest.skip("Not implemented yet")

    def test_M4_moisture_uncertain(self):
        """Soil warming 40→50F steadily, but only 1 rain event."""
        soil = ramp(38, 50, 30) + constant(52, 14)
        precip = constant(0, 15) + [0.5] + constant(0, 28)  # single event
        weather = make_timeline_weather(soil, precip)
        fire = make_fire()
        pytest.skip("Not implemented yet")

    def test_M5_wrong_elevation(self):
        """Perfect weather but 8500ft in April — above seasonal band."""
        soil = ramp(35, 42, 30) + constant(43, 14)  # barely warming
        precip = constant(0.15, 44)
        weather = make_timeline_weather(soil, precip)
        fire = make_fire()
        # Readiness might show GROWING but Potential is low (wrong elevation)
        pytest.skip("Not implemented yet")

    def test_M6_second_year_burn(self):
        """Perfect weather, EMERGING readiness, but burn is 14 months old."""
        soil = ramp(35, 55, 30) + constant(55, 14)
        precip = constant(0.2, 44)
        weather = make_timeline_weather(soil, precip)
        fire = make_fire(months_ago=14)  # second year — declining
        pytest.skip("Not implemented yet")

    def test_M7_north_facing_slow(self):
        """Same as G1 weather but north-facing. Soil crossed 43F only 10 days ago."""
        soil = constant(38, 20) + ramp(38, 50, 10) + ramp(50, 53, 14)
        precip = constant(0, 20) + constant(0.2, 24)
        weather = make_timeline_weather(soil, precip)
        fire = make_fire()
        # North-facing = later start, fewer grow days
        pytest.skip("Not implemented yet")
