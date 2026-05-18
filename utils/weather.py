"""Open-Meteo weather data fetching.

Two cache layers, keyed per (lat, lon) rounded to 3 decimals:

  cache/wxhist/<key>.json  — historical archive data, IMMUTABLE per date.
                             Each run only fetches the gap [last_cached+1, yesterday].
                             A day's values, once cached, are never re-fetched.

  cache/wxfc/<key>.json    — forecast data, single blob per site with fetched_at.
                             Fresh up to FRESH_HOURS. Beyond that, attempt refresh;
                             on failure, fall back to stale cache up to STALE_OK_HOURS
                             (marked with stale=True on the returned dict).

Past incident (2026-05-03): Open-Meteo 429s for the archive endpoint were getting
cached, leaving sites stuck at readiness 0. Fixed by refusing to cache partial responses.

Past incident (2026-05-17): same trigger (archive timeouts), different mechanism —
partial responses were correctly NOT cached, but the CURRENT run still used the
empty arrays for scoring, silently producing TOO_EARLY for sites that had been
GROWING/EMERGING the day before. Fixed structurally here: historical data is
immutable so a transient failure cannot wipe out yesterday's known-good values,
and forecast failures fall back to stale cache instead of empty arrays.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from config import (CACHE_DIR, WEATHER_FORECAST_FRESH_HOURS,
                    WEATHER_FORECAST_STALE_OK_HOURS, WEATHER_HIST_WINDOW_DAYS)
from utils.http import fetch_json


HIST_CACHE_DIR = CACHE_DIR / "wxhist"
FC_CACHE_DIR = CACHE_DIR / "wxfc"


def _site_key(lat: float, lon: float) -> str:
    return f"{round(lat, 3)}_{round(lon, 3)}".replace(".", "p").replace("-", "n")


def _hourly_to_daily_max(vals: list) -> list:
    daily = []
    for i in range(0, len(vals), 24):
        chunk = [x for x in vals[i:i + 24] if x is not None]
        if chunk:
            daily.append(max(chunk))
    return daily


def _hourly_to_daily_mean(vals: list) -> list:
    daily = []
    for i in range(0, len(vals), 24):
        chunk = [x for x in vals[i:i + 24] if x is not None]
        if chunk:
            daily.append(sum(chunk) / len(chunk))
    return daily


# ── Historical archive (immutable per date) ─────────────────────────────────

def _load_hist_cache(lat: float, lon: float) -> dict:
    path = HIST_CACHE_DIR / f"{_site_key(lat, lon)}.json"
    if not path.exists():
        return {"lat": lat, "lon": lon, "days": []}
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {"lat": lat, "lon": lon, "days": []}


def _save_hist_cache(lat: float, lon: float, data: dict) -> None:
    HIST_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    (HIST_CACHE_DIR / f"{_site_key(lat, lon)}.json").write_text(json.dumps(data))


def _archive_to_per_day(resp: dict | None) -> list[dict]:
    """Flatten an Open-Meteo archive response into per-day records."""
    if not resp or "daily" not in resp:
        return []
    daily = resp["daily"]
    dates = daily.get("time", [])
    tmax = daily.get("temperature_2m_max", [])
    tmin = daily.get("temperature_2m_min", [])
    precip = daily.get("precipitation_sum", [])
    snow = daily.get("snowfall_sum", [])
    soil_hourly = (resp.get("hourly") or {}).get("soil_temperature_0_to_7cm", [])
    # hourly_to_daily_max skips days with no data, so soil_daily can be shorter
    # than dates. We track soil per-date by walking the hourly arr in 24-hour
    # chunks aligned with dates.
    out = []
    for i, d in enumerate(dates):
        soil_chunk = [x for x in soil_hourly[i * 24:(i + 1) * 24] if x is not None]
        out.append({
            "date": d,
            "t_max": tmax[i] if i < len(tmax) else None,
            "t_min": tmin[i] if i < len(tmin) else None,
            "precip": precip[i] if i < len(precip) else None,
            "snow": snow[i] if i < len(snow) else None,
            "soil_temp": max(soil_chunk) if soil_chunk else None,
        })
    return out


def _ensure_historical(lat: float, lon: float) -> list[dict]:
    """Bring the historical cache up to yesterday and return the window slice.

    Only fetches the gap [last_cached_date + 1, yesterday]. On a warm cache
    that's typically 1 day; on first run for a site, it's the full window.
    If the fetch fails, returns whatever the cache already has — never wipes
    out previously-good data.
    """
    today = datetime.now().date()
    yesterday = today - timedelta(days=1)
    window_start = today - timedelta(days=WEATHER_HIST_WINDOW_DAYS)
    window_start_iso = window_start.isoformat()

    cache = _load_hist_cache(lat, lon)
    by_date = {d["date"]: d for d in cache.get("days", [])
               if d.get("date", "") >= window_start_iso}

    if by_date:
        last_date = max(by_date.keys())
        fetch_start = datetime.fromisoformat(last_date).date() + timedelta(days=1)
    else:
        fetch_start = window_start

    if fetch_start <= yesterday:
        resp = fetch_json("https://archive-api.open-meteo.com/v1/archive", {
            "latitude": lat, "longitude": lon,
            "start_date": fetch_start.isoformat(),
            "end_date": yesterday.isoformat(),
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,snowfall_sum",
            "hourly": "soil_temperature_0_to_7cm",
            "temperature_unit": "fahrenheit",
            "precipitation_unit": "inch",
            "timezone": "America/Los_Angeles",
        })
        for day in _archive_to_per_day(resp):
            by_date[day["date"]] = day

    # Persist only the window we care about
    days_sorted = sorted(by_date.values(), key=lambda x: x["date"])
    _save_hist_cache(lat, lon, {"lat": lat, "lon": lon, "days": days_sorted})
    return days_sorted


# ── Forecast (mutable, stale-OK fallback) ───────────────────────────────────

def _fc_cache_path(lat: float, lon: float) -> Path:
    return FC_CACHE_DIR / f"{_site_key(lat, lon)}.json"


def _load_fc_cache(lat: float, lon: float) -> dict | None:
    path = _fc_cache_path(lat, lon)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def _save_fc_cache(lat: float, lon: float, data: dict) -> None:
    FC_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _fc_cache_path(lat, lon).write_text(json.dumps(data))


def _get_forecast(lat: float, lon: float) -> dict:
    """Return forecast dict. Marks `forecast_stale: True` if served from old cache."""
    now = time.time()
    cached = _load_fc_cache(lat, lon)

    fresh_cutoff = now - WEATHER_FORECAST_FRESH_HOURS * 3600
    if cached and cached.get("fetched_at", 0) >= fresh_cutoff:
        return {**cached, "forecast_stale": False}

    resp = fetch_json("https://api.open-meteo.com/v1/forecast", {
        "latitude": lat, "longitude": lon,
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,snowfall_sum",
        "hourly": "soil_temperature_0cm,soil_moisture_0_1cm,snow_depth",
        "current_weather": "true",
        "temperature_unit": "fahrenheit",
        "precipitation_unit": "inch",
        "timezone": "America/Los_Angeles",
        "forecast_days": 7,
        "past_days": 7,
    })

    if resp:
        daily = resp.get("daily") or {}
        hourly = resp.get("hourly") or {}
        out = {
            "forecast_temps_max": [x for x in (daily.get("temperature_2m_max") or []) if x is not None],
            "forecast_temps_min": [x for x in (daily.get("temperature_2m_min") or []) if x is not None],
            "forecast_soil_temp": _hourly_to_daily_max(hourly.get("soil_temperature_0cm", [])),
            "forecast_soil_moisture": _hourly_to_daily_mean(hourly.get("soil_moisture_0_1cm", [])),
            "forecast_snow_depth": _hourly_to_daily_max(hourly.get("snow_depth", [])),
            "current_temp": (resp.get("current_weather") or {}).get("temperature"),
            "fetched_at": now,
        }
        # Only cache if the critical soil field came through (a partial response
        # without soil_temp would silently degrade scoring for FRESH_HOURS).
        if out["forecast_soil_temp"]:
            _save_fc_cache(lat, lon, out)
            return {**out, "forecast_stale": False}

    # Fresh fetch failed or was partial. Fall back to stale cache if recent enough.
    stale_cutoff = now - WEATHER_FORECAST_STALE_OK_HOURS * 3600
    if cached and cached.get("fetched_at", 0) >= stale_cutoff:
        return {**cached, "forecast_stale": True}

    # No usable data anywhere.
    return {
        "forecast_temps_max": [], "forecast_temps_min": [],
        "forecast_soil_temp": [], "forecast_soil_moisture": [],
        "forecast_snow_depth": [], "current_temp": None,
        "forecast_stale": True,
    }


# ── Public API ──────────────────────────────────────────────────────────────

def get_weather(lat: float, lon: float) -> dict[str, Any]:
    """Return historical + forecast weather for a site.

    Output shape is unchanged from earlier versions for backward compatibility
    with phase_scoring.py and scoring.py, with one additive field:
      - forecast_stale: bool — True if forecast came from cache older than
                               WEATHER_FORECAST_FRESH_HOURS.
    """
    hist_days = _ensure_historical(lat, lon)
    fc = _get_forecast(lat, lon)

    def col(key):
        return [d[key] for d in hist_days if d.get(key) is not None]

    return {
        "lat": lat, "lon": lon,
        "hist_temps_max": col("t_max"),
        "hist_temps_min": col("t_min"),
        "hist_precip": col("precip"),
        "hist_snowfall": col("snow"),
        "hist_soil_temp": col("soil_temp"),
        "forecast_temps_max": fc.get("forecast_temps_max", []),
        "forecast_temps_min": fc.get("forecast_temps_min", []),
        "forecast_soil_temp": fc.get("forecast_soil_temp", []),
        "forecast_soil_moisture": fc.get("forecast_soil_moisture", []),
        "forecast_snow_depth": fc.get("forecast_snow_depth", []),
        "current_temp": fc.get("current_temp"),
        "forecast_stale": fc.get("forecast_stale", False),
    }
