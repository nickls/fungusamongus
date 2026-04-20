"""Open-Meteo weather data fetching."""

from datetime import datetime, timedelta
from typing import Any

from utils.cache import cache_key, cache_get, cache_set
from utils.http import fetch_json
from config import CACHE_TTL_HOURS


def get_weather(lat: float, lon: float) -> dict[str, Any]:
    key = cache_key("wx", lat=round(lat, 3), lon=round(lon, 3))
    cached = cache_get(key, CACHE_TTL_HOURS)
    if cached:
        return cached

    today = datetime.now().date()
    start = today - timedelta(days=30)

    hist = fetch_json("https://archive-api.open-meteo.com/v1/archive", {
        "latitude": lat, "longitude": lon,
        "start_date": start.isoformat(),
        "end_date": (today - timedelta(days=1)).isoformat(),
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,snowfall_sum",
        "temperature_unit": "fahrenheit",
        "precipitation_unit": "inch",
        "timezone": "America/Los_Angeles",
    })

    forecast = fetch_json("https://api.open-meteo.com/v1/forecast", {
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

    def safe_list(d, field):
        return [x for x in (d.get(field) or []) if x is not None]

    def hourly_to_daily_max(vals):
        daily = []
        for i in range(0, len(vals), 24):
            chunk = [x for x in vals[i:i+24] if x is not None]
            if chunk:
                daily.append(max(chunk))
        return daily

    def hourly_to_daily_mean(vals):
        daily = []
        for i in range(0, len(vals), 24):
            chunk = [x for x in vals[i:i+24] if x is not None]
            if chunk:
                daily.append(sum(chunk) / len(chunk))
        return daily

    result = {
        "lat": lat, "lon": lon,
        "hist_temps_max": [], "hist_temps_min": [],
        "hist_precip": [], "hist_snowfall": [],
        "forecast_temps_max": [], "forecast_temps_min": [],
        "forecast_soil_temp": [], "forecast_soil_moisture": [],
        "forecast_snow_depth": [],
        "current_temp": None,
    }

    if hist and "daily" in hist:
        d = hist["daily"]
        result["hist_temps_max"] = safe_list(d, "temperature_2m_max")
        result["hist_temps_min"] = safe_list(d, "temperature_2m_min")
        result["hist_precip"] = safe_list(d, "precipitation_sum")
        result["hist_snowfall"] = safe_list(d, "snowfall_sum")

    if forecast and "daily" in forecast:
        d = forecast["daily"]
        result["forecast_temps_max"] = safe_list(d, "temperature_2m_max")
        result["forecast_temps_min"] = safe_list(d, "temperature_2m_min")

    if forecast and "hourly" in forecast:
        h = forecast["hourly"]
        soil_t = h.get("soil_temperature_0cm", [])
        soil_m = h.get("soil_moisture_0_1cm", [])
        snow_d = h.get("snow_depth", [])
        if soil_t:
            result["forecast_soil_temp"] = hourly_to_daily_max(soil_t)
        if soil_m:
            result["forecast_soil_moisture"] = hourly_to_daily_mean(soil_m)
        if snow_d:
            result["forecast_snow_depth"] = hourly_to_daily_max(snow_d)

    if forecast and "current_weather" in forecast:
        result["current_temp"] = forecast["current_weather"].get("temperature")

    cache_set(key, result)
    return result
