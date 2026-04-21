# CLAUDE.md

## Project overview

Morel mushroom foraging recommender for the Greater Tahoe Basin. Scores burn sites for foraging potential by combining fire history, real-time weather, elevation, slope/aspect, and snowmelt data.

## Architecture

```
morel_finder.py    # Runner/orchestrator (~180 lines)
config.py          # ALL scoring parameters — weights, thresholds, curves
phase_scoring.py   # v0.7.0 phase model — classify_day, build_timeline, score_potential/readiness
scoring.py         # Legacy v0.6 scoring engine (kept for backward compat, pending consolidation)
mapping.py         # Folium maps, matplotlib charts, text reports
ALGO.md            # Full scoring algorithm documentation — KEEP UPDATED
docs/              # SPA frontend (Leaflet map, detail page) — hosted on GitHub Pages
  app.js           # Map, markers, day picker, filter sliders
  detail.html      # Per-burn detail page with timeline, charts
  index.html       # Main map page
utils/
  cache.py         # JSON file cache with TTL
  http.py          # fetch_json wrapper
  weather.py       # Open-Meteo API (historical + forecast)
  elevation.py     # USGS EPQS elevation + slope/aspect computation
  fires.py         # NIFC Interagency History + Tahoe Fuels Treatments (ArcGIS)
  pfirs.py         # PFIRS scraper (CARB prescribed fire data, no API)
  landfire.py      # LANDFIRE EVT vegetation type (ImageServer identify)
  fit_regression.py # Logistic regression training on labeled scenarios
```

## Key design decisions

- **Score burn locations directly** — don't score arbitrary points and check proximity to fires. The burn IS the candidate.
- **Dual-score phase model (v0.7.0)** — Potential (0-100, site quality, stable) + Readiness (0-100, weather conditions, changes daily). Each day classified as START/GROW/BAD. Readiness via logistic regression on 70 labeled scenarios.
- **Moisture is the gate, soil temp is the trigger** — the biology demands moisture first (non-negotiable), then warming soil temps to initiate fruiting.
- **Warming trend matters more than threshold** — a soil temp of 52F that's been rising for 2 weeks is better signal than 52F that's been flat.
- **PFIRS is the highest-signal fire source** — small prescribed burns (5-50ac) are the best morel habitat and only exist in PFIRS. MTBS, WFIGS, CAL FIRE all miss them.
- **All scoring params live in config.py** — to experiment with different algorithms, copy config.py, adjust weights/curves, run with --config.

## When making changes

- **Changing scoring logic**: Edit `phase_scoring.py` (primary) or `scoring.py` (legacy). All thresholds come from `config.py` via the mushroom type profile. **IMPORTANT: Update ALGO.md whenever scoring logic, weights, thresholds, or factors change.** ALGO.md is the canonical documentation of how the algorithm works — it must stay in sync with the code.
- **Changing map appearance**: Edit `docs/app.js` (SPA) or `mapping.py` (static Folium maps).
- **Adding a data source**: Add to `utils/`, import in `morel_finder.py`'s `gather_fire_data()`.
- **Adding a mushroom type**: Add profile to `MUSHROOM_TYPES` in `config.py`. Will need different candidate generation (not burn sites) — that logic goes in `morel_finder.py`.

## Bump the version

After meaningful scoring changes, bump `ALGO_VERSION` in `config.py`. This shows on the map legend so you can tell which algorithm produced which map. Also create an annotated git tag: `git tag -a v0.X.Y -m "description"`.

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

## Project management

No GitHub Issues or PRs — all task tracking lives in `TODO.md`.
