# Design: GitHub Pages Deployment + Automated Scoring via Actions

## Context

The scoring pipeline runs locally today: `python morel_finder.py` fetches weather, elevation, and fire data, scores burns, and writes output files. The SPA design (see `predictive-mode-and-spa.md`) puts the frontend in `docs/` and the scored data in `docs/data/latest.json`.

The next step is automating this: a GitHub Action runs the pipeline on a schedule, commits the updated `latest.json`, and GitHub Pages serves the SPA. The user never has to run anything locally for the map to stay current.

Two big constraints:

1. **Some data sources require manual intervention.** PFIRS has no API -- it requires a browser session cookie. The Action can't scrape PFIRS. PFIRS data changes slowly (new burns are filed weekly/monthly), so a committed cache file is fine.

2. **External APIs have rate limits and latency.** Scoring ~600 burns means ~600 calls to Open-Meteo (weather) and ~600 to USGS EPQS (elevation). Elevation is static and should be cached permanently. Weather has a 6h TTL. A full run from cold cache takes 5-10 minutes; with warm cache it's ~2 minutes.

## Refresh Cadence

Morel conditions change on the scale of days, not hours. Weather forecasts update twice daily but the scoring factors (soil temp trends, 14-day precip sums) smooth out sub-daily noise.

**Recommendation: every 3 days during season (Apr-Jul), weekly off-season, on-demand via workflow_dispatch.**

Rationale:
- Every 24h is overkill -- soil temp trends barely move day to day, and we'd burn through Actions minutes
- Every 7 days risks missing a warming spike during prime season
- 3-day cadence catches the "snow just melted, soil warming fast" transitions that matter most
- `workflow_dispatch` lets you trigger a run after updating PFIRS data or config changes

## What Gets Cached (and Where)

### Committed to repo (long-lived, changes slowly)

| File | Contents | Update frequency |
|------|----------|-----------------|
| `cache/pfirs_burns.json` | Parsed PFIRS burn records | Manual (after PFIRS scrape) |
| `cache/elevation.json` | USGS EPQS results by lat/lon | Never changes (static terrain) |
| `cache/fire_perimeters.json` | NIFC + Tahoe Fuels treatment polygons | Weekly (Action refreshes) |

These get committed so the Action doesn't start from a cold cache every run. Elevation alone saves ~600 API calls.

### Generated per-run (committed by Action)

| File | Contents | Lifetime |
|------|----------|----------|
| `docs/data/latest.json` | Scored burns, current run | Overwritten each run |
| `docs/data/scores_YYYY-MM-DD.json` | Dated snapshot | Keep rolling 30 days |

### Ephemeral (Action workspace only, not committed)

| File | Contents | Notes |
|------|----------|-------|
| `cache/weather_*.json` | Open-Meteo responses | 6h TTL, fetched fresh each run |
| `cache/soil_*.json` | Soil temp/moisture series | Same, part of weather fetch |

Weather is always fetched fresh because the forecast portion changes. No point caching it across runs.

## GitHub Action Workflow

```yaml
# .github/workflows/score.yml
name: Score Burns

on:
  schedule:
    # Every 3 days at 6am PT (1pm UTC) during season
    - cron: '0 13 */3 * *'
  workflow_dispatch:  # manual trigger

permissions:
  contents: write     # to push updated data

jobs:
  score:
    runs-on: ubuntu-latest
    timeout-minutes: 15

    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Restore cache files
        # Elevation + fire perimeters are committed to repo
        # Nothing to restore -- they're already in the checkout

      - name: Run scoring pipeline
        run: python morel_finder.py
        env:
          CI: true   # pipeline can check this to skip interactive prompts

      - name: Commit updated data
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add docs/data/ cache/fire_perimeters.json
          # Only commit if there are changes
          git diff --staged --quiet || \
            git commit -m "chore: update scores $(date +%Y-%m-%d)"
          git push
```

## Pipeline Changes for CI Mode

`morel_finder.py` needs minor adjustments to run headlessly in Actions:

### 1. Skip folium HTML generation in CI

The folium maps (`morel_local_*.html`, `morel_basin_*.html`) are 7-13MB each and not needed for GH Pages (the SPA reads from JSON). In CI mode, skip them:

```python
if not os.environ.get("CI"):
    m_local = build_map(...)
    m_local.save(f"morel_local_{run_date}.html")
    # ... basin map, chart, CSV
```

The SPA's `docs/data/latest.json` is the only required output.

### 2. Committed cache for elevation

Currently `cache/` is fully gitignored. Change to:

```gitignore
# Cached API responses (ephemeral)
cache/weather_*.json
cache/soil_*.json

# Keep these committed (expensive to re-fetch, rarely change)
!cache/elevation.json
!cache/fire_perimeters.json
!cache/pfirs_burns.json
```

The cache module already handles this -- `cache_get` reads from `cache/` regardless of how the file got there. No code changes needed.

### 3. Consolidate elevation cache into a single file

Currently each elevation lookup writes its own `cache/<hash>.json`. For committing, consolidate into a single `cache/elevation.json` keyed by `lat,lon`:

```python
# utils/elevation.py -- add at module level
ELEVATION_STORE = Path("cache/elevation.json")

def _load_store():
    if ELEVATION_STORE.exists():
        return json.loads(ELEVATION_STORE.read_text())
    return {}

def _save_store(store):
    ELEVATION_STORE.write_text(json.dumps(store))
```

This makes the committed cache a single predictable file instead of hundreds of hash-named files.

### 4. Fire perimeter consolidation (same pattern)

Consolidate NIFC + Tahoe Fuels responses into `cache/fire_perimeters.json` with a `fetched_at` timestamp. The Action commits this so the next run only re-fetches if >24h old (which it will be on a 3-day cadence, but that's fine -- fire data is fast to fetch).

## GitHub Pages Setup

### Repository settings

- **Source**: Deploy from branch, `main`, `/docs` folder
- No custom domain needed (works at `<user>.github.io/<repo>/`)

### `docs/` structure (post-SPA)

```
docs/
  index.html          # SPA (from predictive-mode-and-spa.md design)
  app.js
  style.css
  data/
    latest.json        # current scored data (committed by Action)
    scores_2026-04-19.json   # dated snapshots (rolling 30 days)
  .nojekyll            # tell GH Pages not to process with Jekyll
```

The `.nojekyll` file is important -- without it, GitHub Pages runs Jekyll which ignores files starting with `_` and adds processing overhead.

## PFIRS: The Manual Piece

PFIRS can't be automated in Actions (requires browser session cookie). The workflow for updating PFIRS data:

1. User scrapes PFIRS locally: `python -m utils.pfirs --fetch --cookie '...'`
2. This writes `cache/pfirs_burns.json`
3. User commits and pushes: `git add cache/pfirs_burns.json && git commit`
4. Next Action run picks up the new burns

PFIRS data is slow-moving (new prescribed burns are filed weeks/months after they happen), so manual monthly updates are fine. The scoring pipeline already handles missing PFIRS gracefully -- it just scores fewer burns.

### Future: PFIRS via headless browser

If PFIRS automation becomes important, a headless Playwright step could be added to the Action. But the CARB site requires solving a session flow, and the data value vs. effort isn't there yet. Flag for later.

## Keeping Dated Snapshots

Dated score files (`scores_YYYY-MM-DD.json`) serve two purposes:

1. **Debugging**: compare today's scores to last week's to see what changed
2. **Historical view**: the SPA could add a "compare to last run" feature

Cleanup: the Action should delete snapshots older than 30 days to prevent repo bloat:

```yaml
- name: Clean old snapshots
  run: |
    find docs/data -name 'scores_*.json' -mtime +30 -delete
```

At ~200KB per snapshot and runs every 3 days, that's ~10 snapshots = ~2MB. Negligible.

## Seasonal Schedule

The Action doesn't need to run year-round. Morel season is Apr-Jul. Options:

**Option A: Cron with season check** -- run the cron year-round but have the Python script exit early outside season:

```python
if not (4 <= datetime.now().month <= 7) and not os.environ.get("FORCE_RUN"):
    print("Off-season, skipping. Use FORCE_RUN=1 to override.")
    sys.exit(0)
```

**Option B: Multiple cron schedules** -- define two schedules in the workflow:

```yaml
on:
  schedule:
    - cron: '0 13 */3 4-7 *'   # every 3 days, Apr-Jul
    - cron: '0 13 1 1-3,8-12 *' # 1st of month, off-season
```

**Recommendation: Option B.** Clearer intent, doesn't waste Actions runner spin-up time. Off-season monthly runs catch any config changes and keep fire perimeter data fresh for when season starts.

## Requirements File

The repo doesn't have a `requirements.txt` yet. Needed for the Action:

```
pandas
requests
folium
matplotlib
```

(Or use a `pyproject.toml` with `pip install .` -- but `requirements.txt` is simpler for a script-based project.)

## Failure Modes

| Failure | Impact | Mitigation |
|---------|--------|------------|
| Open-Meteo API down | No weather data, scores are 0 | Action fails, previous `latest.json` stays live. Retry on next scheduled run. |
| USGS EPQS 504 | Missing elevation for some burns | Elevation is cached/committed. Only new burns need API calls. Partial results still usable. |
| NIFC API changed/auth required | No wildfire data | PFIRS + Tahoe Fuels still work. Log warning. |
| GitHub Pages deploy fails | SPA shows stale data | `latest.json` has `run_date` field -- SPA can show "data from X days ago" warning |
| Action exceeds 15min timeout | No update | Increase timeout, or reduce burn count. Unlikely with cached elevation. |

## Implementation Steps

1. **Create `requirements.txt`** from current imports
2. **Consolidate elevation cache** into single `cache/elevation.json` file
3. **Update `.gitignore`** to track elevation, fire perimeters, and PFIRS cache
4. **Add CI mode to `morel_finder.py`** -- skip folium output, keep JSON export
5. **Add `.github/workflows/score.yml`** with 3-day schedule
6. **Add `docs/.nojekyll`**
7. **Enable GH Pages** in repo settings (manual, one-time)
8. **Test with `workflow_dispatch`** before relying on scheduled runs
9. **Add dated snapshot cleanup** step to workflow

## File Changes

| File | Action |
|------|--------|
| `requirements.txt` | **New** -- Python dependencies for CI |
| `.github/workflows/score.yml` | **New** -- scheduled Action |
| `.gitignore` | **Modify** -- selective cache tracking |
| `morel_finder.py` | **Modify** -- CI mode (skip folium), snapshot export |
| `utils/elevation.py` | **Modify** -- consolidated cache file |
| `utils/cache.py` | No change (already works with committed files) |
| `docs/.nojekyll` | **New** -- empty file |
| `cache/elevation.json` | **Generated, committed** -- consolidated elevation data |
| `cache/fire_perimeters.json` | **Generated, committed** -- fire API responses |

## Relationship to Other Design Docs

- **`predictive-mode-and-spa.md`**: This doc assumes the SPA exists and serves from `docs/`. The SPA design owns the frontend; this design owns the pipeline automation that feeds it.
- **`forest-mushrooms.md`**: When matsutake/chanterelle scoring is added, the Action runs those too. The `latest.json` format already supports multiple mushroom types. The LANDFIRE API calls for grid candidates will be the slowest part -- may need a separate cache file committed like elevation.
