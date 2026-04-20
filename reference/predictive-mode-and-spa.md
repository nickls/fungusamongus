# Design: Predictive Mode + Single-Page App + Filter Sliders

## Context

The current tool scores burn sites based on a blend of recent historical weather and forecast data, producing a single "go/no-go" score per site. Three improvements converge into one project:

1. **"Go now" vs predictive** — User wants two views: "if I get up and go right now, where?" (day 0) and "what are the best sites over the next 7 days?" (days 0-7). The forecast data already exists in Open-Meteo — we just average it instead of scoring per-day.

2. **Filter sliders** — The scoring model is conjecture + literature, not empirically tested. The ability to manually adjust factor thresholds ("show me only sites where soil temp is 25/25 AND moisture is 18+/20") lets the user empirically discover which factors actually matter by cross-referencing with field results.

3. **Single-page app for GH Pages** — Two folium HTML files at 7MB and 13MB is unsustainable. A static HTML/JS app loading scored data from JSON would be ~500KB for data + tile CDN for maps. Local vs basin becomes a zoom toggle, not two separate files.

These three converge: **a lightweight JS map app that loads per-day scored data from JSON, with a date picker + factor sliders + zoom toggle.**

## Architecture

### Data pipeline (Python — runs daily or on-demand)

```
morel_finder.py
  -> score each burn for day 0, day 1, ... day 7
  -> output: docs/data/scores_2026-04-19.json
```

The JSON contains all scored burns with per-day breakdowns:

```json
{
  "run_date": "2026-04-19",
  "algo_version": "0.5.0",
  "center": {"lat": 39.3187, "lon": -120.2125, "name": "Alder Creek"},
  "burns": [
    {
      "name": "Shake Omo (Underburn)",
      "lat": 39.42, "lon": -120.65,
      "acres": 82, "burn_type": "Underburn", "burn_age_months": 6,
      "elevation_ft": 4950, "slope": 12, "aspect": 185,
      "days": [
        {
          "day": 0, "date": "2026-04-19",
          "total": 82,
          "soil_threshold": 25, "warming_trend": 14,
          "recent_moisture": 18, "burn_quality": 12,
          "sun_aspect": 10, "air_temp": 3,
          "soil_temp_f": 57, "soil_trend_f": 4,
          "precip_14d_in": 3.9, "snow_status": "snow-free",
          "avg_high_f": 47, "avg_low_f": 31
        },
        {
          "day": 1, "date": "2026-04-20",
          "total": 84,
          ...
        },
        ...day 2-7
      ]
    },
    ...
  ]
}
```

### Frontend (static HTML/JS/CSS — served from `docs/`)

```
docs/
  index.html      — single-page app
  app.js           — map rendering, sliders, date picker
  style.css        — minimal styling
  data/
    scores_2026-04-19.json   — latest run
    scores_2026-04-18.json   — previous day (optional, for comparison)
```

No build step, no framework. Vanilla JS + Leaflet (open source, no tile auth issues) + noUiSlider (lightweight range slider library, ~30KB).

## Frontend Features

### 1. Day selector (top bar)

```
[ TODAY ] [ +1 ] [ +2 ] [ +3 ] [ +4 ] [ +5 ] [ +6 ] [ +7 ]
```

- **TODAY** = "go now" mode. Scores from day 0.
- Clicking a day re-renders all markers using that day's scores.
- Each button shows the date and a quick summary ("Apr 19 — 12 excellent")
- Color-coded by how many EXCELLENT sites exist that day (green = many, gray = few)

### 2. Filter sliders (side panel)

One slider per scoring factor, each ranging from 0 to factor max:

```
Soil Threshold   [====|==========] 15 / 25
Warming Trend    [=|==============] 5 / 25
Recent Moisture  [========|======] 12 / 20
Burn Quality     [===========|===] 10 / 15
Sun / Aspect     [===|===========] 3 / 10
Air Temp         [=============|=] 4 / 5
──────────────────────────────────────────
Total Minimum    [========|======] 50 / 100
```

- Dragging a slider hides all markers below that threshold for that factor
- "Total Minimum" is a master filter
- Slider positions persist in URL hash so you can share filtered views
- Reset button returns all to 0

### 3. Map view

- Leaflet with CARTO Voyager + Esri Topo layer toggle
- Markers: purple diamonds (80+), green diamonds (70-79), orange dots (50-69), hidden below 50
- Heatmap layer (Leaflet.heat) — acre-proportional scatter, same as current
- Click marker -> popup with full score breakdown for selected day
- Zoom toggle: "Local" (30mi) / "Basin" (75mi) buttons that just set map bounds, not reload data

### 4. Trend sparkline (in popup)

When you click a marker, the popup shows the 8-day score trend as a tiny sparkline:

```
Shake Omo (Underburn) — 82ac, 6mo ago
Day:  0   1   2   3   4   5   6   7
     82  84  85  86  84  80  78  75
     ──  ──  ██  ██  ──  ──  ──  ──
     ↑ today        peak
```

This shows "when is the best day to go to THIS specific site?"

## Python Changes

### Scoring per-day

Currently `get_weather()` returns blended 7-day averages. For per-day scoring:

1. Keep the current weather fetch (it already gets daily data for past 7 + forecast 7).
2. Add `score_burn_for_day(fire, weather, elev, terrain, day_offset)` that:
   - Shifts the "recent" window: day 0 = today's actual data, day 3 = forecast for 3 days out
   - For soil threshold: use the specific day's soil temp (not average)
   - For warming trend: still uses the multi-day trend leading up to that day
   - For moisture: precipitation sum shifts by day_offset
   - For burn quality / sun_aspect / air_temp: mostly stable across days (burn age doesn't change in 7 days)
3. Return scores for each day as a list.

### JSON output

Add to `morel_finder.py`:

```python
def export_json(results, run_date):
    """Export scored burns as JSON for the frontend."""
    data = {
        "run_date": run_date,
        "algo_version": ALGO_VERSION,
        "center": {"lat": ALDER_CREEK[0], "lon": ALDER_CREEK[1]},
        "burns": []
    }
    for r in results:
        burn = {
            "name": r["zone"]["name"],
            "lat": r["zone"]["lat"], "lon": r["zone"]["lon"],
            "acres": r["fire"].get("acres", 0),
            "burn_type": r.get("fire", {}).get("pfirs_burn_type", ""),
            "elevation_ft": r["zone"].get("elevation_ft"),
            "slope": r["zone"].get("slope"),
            "aspect": r["zone"].get("aspect"),
            "days": r["day_scores"],  # list of per-day score dicts
        }
        data["burns"].append(burn)
    
    Path("docs/data").mkdir(parents=True, exist_ok=True)
    Path(f"docs/data/scores_{run_date}.json").write_text(json.dumps(data))
    # Also write as "latest" for the frontend to find
    Path("docs/data/latest.json").write_text(json.dumps(data))
```

## Implementation Steps

### Step 1: Per-day scoring in `scoring.py`

Add `score_burn_for_day()` that takes a `day_offset` (0-7) and extracts that day's specific weather values from the existing weather data arrays instead of averaging.

Key changes from current averaging:
- `soil_temps[day_index]` instead of `np.mean(soil_temps)`
- Trend is still multi-day (compare days 0-3 vs days 4-7 for any given scoring day)
- Precip shifts: for day 3, "last 14 days" means days -11 to +3

### Step 2: Update `morel_finder.py`

For each burn, score for days 0-7. Collect into `r["day_scores"]` list. Export JSON alongside HTML maps.

Keep the existing folium map generation as-is (it still works, uses day-0 scores). The SPA is a parallel output, not a replacement.

### Step 3: Build `docs/app.js`

Vanilla JS:
- Load `data/latest.json` on page load
- Initialize Leaflet map with CARTO tiles
- Render markers for day 0
- Day selector buttons: re-render markers from `burn.days[selectedDay]`
- Slider panel: filter markers where `burn.days[selectedDay][factor] >= sliderValue`
- Popup: show score breakdown + 8-day sparkline
- Zoom buttons: `map.fitBounds(localBounds)` / `map.fitBounds(basinBounds)`
- URL hash state: `#day=3&soil=20&moisture=15&zoom=local`

### Step 4: Build `docs/index.html` + `docs/style.css`

Replace the current simple landing page with the SPA. Include Leaflet and noUiSlider from CDN.

### Step 5: Update `.gitignore`

Track `docs/data/latest.json` (the current run's data). Gitignore dated score files (`docs/data/scores_*.json`) or keep a rolling window.

## File Changes

| File | Action |
|------|--------|
| `scoring.py` | **Modify** — add `score_burn_for_day()` |
| `morel_finder.py` | **Modify** — per-day scoring loop + JSON export |
| `docs/index.html` | **Rewrite** — SPA with Leaflet map |
| `docs/app.js` | **New** — map rendering, sliders, day picker |
| `docs/style.css` | **New** — layout styling |
| `docs/data/latest.json` | **Generated** — scored burn data |

## Verification

1. `python morel_finder.py` — should produce `docs/data/latest.json` alongside existing HTML maps
2. Open `docs/index.html` locally — map loads with day-0 markers
3. Click day buttons — markers update scores
4. Drag sliders — markers filter in real-time
5. Click marker — popup shows breakdown + sparkline
6. Push to GH Pages — verify tiles load, data loads, sliders work
7. File size: `latest.json` should be <1MB for 600 burns x 8 days

## Dependencies (frontend, from CDN)

- Leaflet ~40KB — map rendering (replaces folium)
- Leaflet.heat ~5KB — heatmap layer
- noUiSlider ~30KB — range sliders
- No build step, no npm, no framework

## Relationship to Other Design Docs

- **Matsutake support** (`design/matsutake-support.md`): The JSON format supports multiple mushroom types via a `type` field per burn. The SPA can add a mushroom type toggle alongside the day picker. But matsutake candidates come from grid generation, not burns — the JSON schema is the same, just different `source` field.
- **Filter sliders**: Originally discussed as a folium post-processing hack. This design replaces that — sliders are native to the SPA.
- **Folium maps**: Kept as a parallel output for now (useful for quick local viewing). Can be deprecated once the SPA is stable.
