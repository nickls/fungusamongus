# CLAUDE.md

## Project overview

Morel mushroom foraging recommender for the Greater Tahoe Basin. Scores burn sites for foraging potential by combining fire history, real-time weather, elevation, slope/aspect, and snowmelt data.

## Architecture

```
build_sites.py     # Manual rebuild of data/sites.json (fire + elevation + slope + EVT)
morel_finder.py    # Daily runner — reads sites.json, fetches weather, scores
data/sites.json    # CHECKED IN. Static catalog: location, elevation, slope, aspect, EVT
data/field_reports.json  # CHECKED IN. Real harvest data (ground truth for model)
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

## Operating principles

These are non-negotiable rules learned the hard way:

### 1. Save ALL non-changing or slow-changing data — and check it in

Anything that doesn't change between runs (fire site locations, elevation,
slope, aspect, vegetation type, burn date, acres) lives in
`data/sites.json` and is committed to git. The daily run only fetches
weather. We do NOT re-query USGS / LANDFIRE / NIFC every run.

If you discover another slow-changing data source (soil type, watershed,
land ownership, road network), add it to `build_sites.py`'s enrichment
step and persist it in `sites.json`.

Why: USGS 504s constantly, LANDFIRE is slow, GH Action minutes are
finite. Re-fetching geological constants every day is waste, hides
bugs (sites silently disappearing), and burns API quota.

### 2. Filter LATE — gather wide, narrow in the UI

Pull MORE data than you think you need at the source layer:

- PFIRS: scrape from `01/01/2023` (NOT current year), even if we only
  expect to score recent burns
- NIFC + Tahoe Fuels: 4-year window (NOT 3) — prevents losing edge cases
- Wildfires: included in catalog, NOT filtered out at the build step
- Burn types: ALL of them in the catalog — Underburn, Hand Pile, Machine
  Pile, Broadcast, RX-generic, wildfire

Filtering belongs in the UI (sliders, type chips, age filter), NOT in
the data pipeline. The user changes their mind about what's interesting;
the catalog should support them without a re-scrape.

Past failure: the 2024 Waddle Ranch RX got dropped from the catalog when
PFIRS scrape was tightened to 2025+. Field report had 4-5lbs from there.

### 3. The model flip-flops — distrust single-day signals

The readiness regression has historically swung wildly day-to-day
(0 → 100 → 2 across 3 consecutive runs in late April). Causes:

- `is_currently_good` was binary today-only — one BAD day flipped a
  major feature, swinging readiness ±30 points
- `grow_days` reset to zero on a 3-day bad streak — wiped accumulated
  biological progress
- `extract_features` only counted GROW days AFTER a START in the 30-day
  window — sites with continuous GROW activity but earlier-than-window
  START got `start_days=0, grow_days=0` despite being clearly producing

Current mitigations:
- `is_currently_good` is a 5-day rolling ratio, not binary
- `grow_days_total` (never resets) for readiness; `grow_days_since_reset`
  for phase classification
- `extract_features` falls back to window-onset if no START found but
  GROW is present
- Readiness is capped by phase: TOO_EARLY ≤ 25, WAITING ≤ 50

When changing scoring: smooth over windows, prefer cumulative features,
distrust binary today-only signals. Validate against
`data/field_reports.json`.

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
source .venv/bin/activate && .venv/bin/python morel_finder.py
```

## Project management

No GitHub Issues or PRs — all task tracking lives in `TODO.md`.
