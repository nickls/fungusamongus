# CLAUDE.md

## Project overview

Morel mushroom foraging recommender for the Greater Tahoe Basin. Scores burn sites for foraging potential by combining fire history, real-time weather, elevation, slope/aspect, and snowmelt data.

## Architecture

```
morel_finder.py    # Runner/orchestrator (~130 lines)
config.py          # ALL scoring parameters — weights, thresholds, curves
scoring.py         # Config-driven scoring engine
mapping.py         # Folium maps, matplotlib charts, text reports
ALGO.md            # Full scoring algorithm documentation — KEEP UPDATED
utils/
  cache.py         # JSON file cache with TTL
  http.py          # fetch_json wrapper
  weather.py       # Open-Meteo API (historical + forecast)
  elevation.py     # USGS EPQS elevation + slope/aspect computation
  fires.py         # NIFC Interagency History + Tahoe Fuels Treatments (ArcGIS)
  pfirs.py         # PFIRS scraper (CARB prescribed fire data, no API)
```

## Key design decisions

- **Score burn locations directly** — don't score arbitrary points and check proximity to fires. The burn IS the candidate.
- **Moisture is the gate, soil temp is the trigger** — the biology demands moisture first (non-negotiable), then warming soil temps to initiate fruiting. The scoring weights reflect this: moisture 30, temperature 25, burn quality 35, elevation 10.
- **Warming trend matters more than threshold** — a soil temp of 52F that's been rising for 2 weeks is better signal than 52F that's been flat. We compare first-half vs second-half of the soil temp series.
- **PFIRS is the highest-signal fire source** — small prescribed burns (5-50ac) are the best morel habitat and only exist in PFIRS. MTBS, WFIGS, CAL FIRE all miss them.
- **All scoring params live in config.py** — to experiment with different algorithms, copy config.py, adjust weights/curves, run with --config.

## When making changes

- **Changing scoring logic**: Edit `scoring.py`. All thresholds come from `config.py` via the mushroom type profile. If adding a new scoring factor, add the weight to `MOREL_PROFILE["weights"]` in config.py. **IMPORTANT: Update ALGO.md whenever scoring logic, weights, thresholds, or factors change.** ALGO.md is the canonical documentation of how the algorithm works — it must stay in sync with the code.
- **Changing map appearance**: Edit `mapping.py`. Heatmap intensity, marker styles, legend are all there.
- **Adding a data source**: Add to `utils/`, import in `morel_finder.py`'s `gather_fire_data()`.
- **Adding a mushroom type**: Add profile to `MUSHROOM_TYPES` in `config.py`. Will need different candidate generation (not burn sites) — that logic goes in `morel_finder.py`.

## Bump the version

After meaningful scoring changes, bump `ALGO_VERSION` in `config.py`. This shows on the map legend so you can tell which algorithm produced which map.

## Data refresh

- **Weather**: Auto-refreshes (6h TTL in cache)
- **Fire perimeters (NIFC, Tahoe Fuels)**: Auto-refreshes (24h TTL)
- **PFIRS**: Manual. Run `python -m utils.pfirs --fetch --cookie '...'` with a browser session cookie from ssl.arb.ca.gov/pfirs/. Or `--parse-raw` if you have saved HTML.

## Gotchas

- Open-Meteo hourly variables that work: `soil_temperature_0cm`, `soil_moisture_0_1cm`, `snow_depth`. The documented `soil_temperature_0_10cm` returns 400.
- NIFC Interagency History is the only working free federal fire perimeter API. WFIGS, CAL FIRE, and IRWIN all require auth tokens now.
- USGS EPQS occasionally 504s under load. Elevation values are cached so retries are cheap.
- OSM tiles get 403 blocked in folium — we use CARTO Voyager and Esri Topo instead.
- Matplotlib needs a writable cache dir. Ignore the fontconfig warnings.

## Running

```bash
source .venv/bin/activate
python morel_finder.py
```

Outputs are date-stamped: `morel_local_2026-04-19.html`, etc.
