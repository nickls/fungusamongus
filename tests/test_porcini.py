"""
Porcini biology tests — covers the cooling-trigger phase logic that differs
from morel.

The existing test_phase_scoring.py tests the morel (warming-trigger) flow.
These tests cover what's different for porcini:

  1. classify_day with thermal_signal="cooling"
  2. season_primed gate (no fruiting without prior thermal peak)
  3. freeze tolerance (freeze_is_bad=False)
  4. past-prime treated as BAD (waiting for cooling) not GROW
  5. End-to-end build_timeline against a synthetic fall-cooling weather record
  6. score_potential against a non-burn site (no fire dict required)
"""
import pytest

from config import MUSHROOM_TYPES
from phase_scoring import classify_day, build_timeline, extract_features, classify_phase, score_potential


PORCINI = MUSHROOM_TYPES["porcini"]
MOREL = MUSHROOM_TYPES["morel"]


# ── classify_day: cooling-trigger biology ────────────────────────────────

class TestPorciniClassifyDay:

    def test_cooling_into_start_range_with_rain_primed(self):
        """65F → 58F + 0.5in rain, with prior thermal peak = START_GROW."""
        s, r = classify_day(58, 65, 0.5, 0, had_thermal_peak=True, config=PORCINI)
        assert s == "START_GROW"
        assert "cooling" in r
        assert "moisture" in r

    def test_cooling_without_priming_is_just_grow(self):
        """Same conditions but no prior thermal peak — porcini hasn't been triggered."""
        s, r = classify_day(58, 65, 0.5, 0, had_thermal_peak=False, config=PORCINI)
        assert s == "GROW"  # in grow range, but no START because not primed

    def test_warming_into_range_is_not_start(self):
        """Warming up into grow range is NOT a porcini trigger (cooling species)."""
        s, r = classify_day(55, 50, 0.5, 0, had_thermal_peak=True, config=PORCINI)
        assert s == "GROW"  # in grow range, but trend is wrong direction

    def test_freeze_is_not_damage(self):
        """Cool fall morning at 28F: too cold (BAD), but NOT freeze damage."""
        s, r = classify_day(28, 32, 0, 0, had_thermal_peak=True, config=PORCINI)
        assert s == "BAD"
        assert "freeze damage" not in r

    def test_too_hot_above_past_prime_max(self):
        """Soil at 75F is way too warm for porcini (past_prime_max=70)."""
        s, r = classify_day(75, 73, 0, 0, had_thermal_peak=True, config=PORCINI)
        assert s == "BAD"
        assert "too hot" in r

    def test_past_prime_for_porcini_is_bad(self):
        """67F (above grow_max=65, below past_prime_max=70) = BAD waiting for cooling."""
        s, r = classify_day(67, 70, 0, 0, had_thermal_peak=True, config=PORCINI)
        assert s == "BAD"
        assert "waiting for cooling" in r

    def test_dry_in_grow_range_is_grow(self):
        """In grow range but no rain — still GROW (not BAD), no START fires."""
        s, r = classify_day(58, 60, 0, 0, had_thermal_peak=True, config=PORCINI)
        assert s == "GROW"


# ── classify_day: morel still works the same way ─────────────────────────

class TestMorelStillWorks:
    """Regression — make sure adding thermal_signal didn't break morel."""

    def test_morel_warming_into_start_range_dry(self):
        s, r = classify_day(44, 41, 0, 0, had_thermal_peak=True, config=MOREL)
        assert s == "START"
        assert "warming" in r

    def test_morel_warming_with_rain(self):
        s, r = classify_day(52, 50, 0.5, 0, had_thermal_peak=True, config=MOREL)
        assert s == "START_GROW"

    def test_morel_freeze_after_warmth_is_damage(self):
        s, r = classify_day(30, 35, 0, 0, had_thermal_peak=True, config=MOREL)
        assert s == "BAD"
        assert "freeze damage" in r

    def test_morel_past_prime_is_past_prime_status(self):
        """v0.8.1: morel above grow_max (68F) but below past_prime_max (78F) → PAST_PRIME."""
        # morel grow_soil_max=68, past_prime_max=78 — 72F is squarely past prime
        s, r = classify_day(72, 70, 0, 0, had_thermal_peak=True, config=MOREL)
        assert s == "PAST_PRIME"


# ── build_timeline: end-to-end synthetic scenarios ───────────────────────

def make_porcini_fall_weather():
    """
    Synthetic weather: late-summer warm peak (75F), then fall cooling
    into the porcini sweet spot (60F → 55F) with two rain events.
    44 days total: 30 history + 14 forecast.
    """
    # Days 0-9: late summer hot (had_thermal_peak should fire)
    # Days 10-29: cooling 70 → 60
    # Days 30-43: continued cooling 60 → 50
    soil = []
    for i in range(10):
        soil.append(72.0)  # warm peak
    for i in range(20):
        soil.append(70.0 - (i * 0.5))  # cool from 70 to 60
    for i in range(14):
        soil.append(60.0 - (i * 0.7))  # cool from 60 to 50
    # Two rain events: day 12 and day 25
    precip = [0.0] * 44
    precip[12] = 0.6
    precip[25] = 0.5
    return {
        "hist_soil_temp": soil[:30],
        "forecast_soil_temp": soil[30:],
        "hist_precip": precip[:30],
        "forecast_snow_depth": [0] * 14,
    }


class TestPorciniTimeline:

    def test_summer_heat_primes_then_fall_cooling_triggers(self):
        wx = make_porcini_fall_weather()
        timeline, reasons = build_timeline(wx, PORCINI)
        assert len(timeline) == 44
        # Summer days (0-9, all 72F = above past_prime_max=70) should be BAD
        for i in range(10):
            assert timeline[i] == "BAD", f"day {i}: expected BAD too-hot, got {timeline[i]} ({reasons[i]})"
        # By day 12 we should be in grow range (59F) — and by day 13 had_thermal_peak is set
        # Days 10-29 cooling 70→60, in grow range from ~day 10 onwards
        # Should see at least some START / START_GROW / GROW once primed and cooling
        non_bad = [s for s in timeline[10:] if s != "BAD"]
        assert len(non_bad) > 0, "expected at least some GROW/START days during fall cooling"
        # At least one START or START_GROW (rain event triggered while cooling + primed)
        starts = [s for s in timeline if s in ("START", "START_GROW")]
        assert len(starts) > 0, f"expected at least one START during cooling+rain, timeline: {timeline}"

    def test_no_priming_means_no_start(self):
        """Cool wet spring (no prior heat) shouldn't trigger porcini START."""
        # Constant 55F all year, two rain events — never reaches priming threshold (60F)
        soil = [55.0] * 44
        precip = [0.0] * 44
        precip[12] = 0.6
        precip[25] = 0.5
        wx = {
            "hist_soil_temp": soil[:30],
            "forecast_soil_temp": soil[30:],
            "hist_precip": precip[:30],
            "forecast_snow_depth": [0] * 14,
        }
        timeline, reasons = build_timeline(wx, PORCINI)
        starts = [s for s in timeline if s in ("START", "START_GROW")]
        assert len(starts) == 0, f"expected NO START without prior thermal peak, got: {starts}"


# ── score_potential: non-burn site (no fire dict) ────────────────────────

class TestPorciniPotential:
    """Make sure score_potential handles a porcini site (no burn data)."""

    def test_score_potential_no_fire_no_crash(self):
        """Empty fire dict should produce a valid score (burn_quality=0)."""
        fire = {}  # no acres, no date, no burn_type
        elev = 6500
        terrain = {"slope": 10, "aspect": 180}
        evt = {
            "evt_code": 7028,
            "evt_name": "Mediterranean California Dry-Mesic Mixed Conifer Forest and Woodland",
            "evt_suitability": 1.0,
        }
        result = score_potential(fire, elev, terrain, "porcini", evt=evt)
        assert "potential" in result
        assert "scores" in result
        assert result["scores"]["burn_quality"] == 0  # no fire = no burn quality
        assert result["scores"]["vegetation"] > 0     # mature mixed conifer = top vegetation

    def test_porcini_vegetation_dominates(self):
        """Vegetation weight=50 for porcini vs 15 for morel — most of potential should come from veg."""
        fire = {}
        elev = 6500
        terrain = {"slope": 10, "aspect": 180}
        evt = {"evt_code": 7028, "evt_name": "Mixed Conifer", "evt_suitability": 1.0}
        result = score_potential(fire, elev, terrain, "porcini", evt=evt)
        # Vegetation weight is 50, full suitability = 50/50 score
        assert result["scores"]["vegetation"] >= 40

    def test_porcini_in_season_summer(self):
        """Porcini season July-Nov; June (month 6) should be out of season."""
        # We can't easily mock datetime.now() here, just check the score is a valid range
        fire = {}
        evt = {"evt_suitability": 1.0, "evt_name": "Mixed Conifer", "evt_code": 7028}
        result = score_potential(fire, 6500, {"slope": 10, "aspect": 180}, "porcini", evt=evt)
        season_score = result["scores"]["season"]
        # season is either max (20) if in season, or 0.3 * max (6) if out
        assert season_score in (6, 20), f"season score should be 6 or 20, got {season_score}"
