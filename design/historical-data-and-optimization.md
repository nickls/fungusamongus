# Design: Historical Data Storage + Algorithm Optimization from Field Reports

## Context

The current scoring model is built on literature and ecological reasoning — not empirical data. We have no way to know if a site that scored 82 actually produced morels. To improve the algorithm, we need:

1. **Historical score snapshots** — what did the model predict for each site on each day?
2. **Field reports** — what did the forager actually find (or not find)?
3. **A feedback loop** — compare predictions to reality, adjust weights.

## Part 1: Historical JSON Storage

### What to store

Each run of `morel_finder.py` produces `docs/data/latest.json` (~2.8MB, 622 burns x 8 days). This gets overwritten every run. We should archive each run.

### Storage scheme

```
docs/data/
  latest.json                    # always the most recent (SPA reads this)
  history/
    2026-04-19.json              # archived daily snapshots
    2026-04-20.json
    ...
```

### Implementation

In `morel_finder.py`'s `export_json()`:

```python
# Write latest
Path("docs/data/latest.json").write_text(json_str)

# Archive
history_dir = Path("docs/data/history")
history_dir.mkdir(exist_ok=True)
(history_dir / f"{run_date}.json").write_text(json_str)
```

### Size management

At ~2.8MB/day:
- 30 days = 84MB
- 1 season (120 days) = 336MB

Options:
- **Compress**: gzip reduces to ~400KB/day (JSON compresses well). SPA can fetch `.json.gz` and decompress in JS.
- **Prune**: Keep only last 30 days, plus weekly snapshots for older data.
- **Slim format**: Strip per-day weather details, keep only scores + key metrics. Cuts to ~500KB/day.
- **Don't gitignore**: For GH Pages, we actually want these committed so they're served. But the repo will grow. Recommendation: gzip + keep 30 days, slim older ones.

### What this enables

- **Hindcast validation**: "What did the model predict for site X on April 15? I found morels there on April 17."
- **Score trajectory**: How did a site's score evolve over the season?
- **Algorithm A/B testing**: Run two configs on the same historical weather data, compare which would have been more accurate.
- **SPA timeline**: Date picker in the frontend to view any past day's predictions.

## Part 2: Field Reports

### Data model

A field report is:

```json
{
  "date": "2026-04-20",
  "reporter": "nick",
  "lat": 39.375,
  "lon": -120.170,
  "burn_name": "Donner Camp (Hand Pile)",
  "found_morels": true,
  "quantity": "moderate",         // "none", "few", "moderate", "abundant"
  "notes": "Found ~30 morels on south slope near pile scar edges",
  "conditions_observed": {
    "soil_moist": true,
    "ground_snow": false,
    "soil_warm_to_touch": true,
    "canopy_open": true
  }
}
```

### Storage

```
data/
  field_reports.json             # array of reports, manually edited or via CLI
```

### CLI for adding reports

```bash
python -m utils.field_report \
  --date 2026-04-20 \
  --burn "Donner Camp" \
  --found yes \
  --quantity moderate \
  --notes "South slope, pile scar edges"
```

This finds the closest burn by name match, records lat/lon, and appends to `field_reports.json`.

## Part 3: Feedback Loop — Comparing Predictions to Reality

### The core question

For each field report, look up what the model predicted for that site on that date:

```
Report: "Found morels at Donner Camp on April 20"
Model said: score 72/100 on April 20
→ Correct prediction (score > 70 = GOOD, found morels = true)
```

```
Report: "No morels at Block B-01 on April 22"
Model said: score 85/100 on April 22
→ False positive (predicted EXCELLENT, found nothing)
```

### Metrics

- **Precision**: Of sites we said "go" (score >= 70), how many actually had morels?
- **Recall**: Of sites where morels were found, how many did we score >= 70?
- **False positive rate**: High-scoring sites with no morels = model is wrong about something.
- **False negative rate**: Low-scoring sites where morels were found = model is missing a signal.

### Using this to tune weights

Each field report with a false positive/negative tells us something:

| Scenario | What it means | Action |
|----------|--------------|--------|
| High score, no morels | Some factor is overweighted | Identify which factor was high — that's the one to reduce |
| Low score, found morels | Some factor is underweighted | Identify which factor was low — that's the one to increase |
| High moisture + high soil + no morels | Maybe burn quality matters more | Increase burn_quality weight |
| Low moisture + found morels | Maybe moisture matters less | Decrease moisture weight |

### Automated weight tuning (future)

With enough field reports (20+), we can do gradient-based optimization:

1. Load all historical JSON + field reports
2. For each report, extract the model's per-factor scores from the historical snapshot
3. Define a loss function: `sum(score * found_weight - score * not_found_weight)`
4. Optimize weights to minimize false positives and false negatives
5. Output a new config.py with adjusted weights

This is essentially logistic regression where the features are the 6 factor scores and the label is found/not-found.

### Manual weight tuning (now)

More practically: after 5-10 field reports, eyeball the pattern:

1. Run `python -m utils.analyze_reports` — shows each report vs prediction
2. Look for consistent patterns ("every false positive had high moisture but low warming trend")
3. Adjust weights in `config.py`
4. Re-run on historical data to see if the change improves accuracy
5. Compare before/after using the historical JSON snapshots

## Part 4: Discussion — Trend-Based Filters vs Score-Based Filters

### Current approach: score-based sliders

The SPA has sliders for each factor score (soil_threshold: 0-25, warming_trend: 0-25, etc.). These filter by "how many points did this factor earn?"

### Problem

Score-based filters are one step removed from reality. A user doesn't think "I want sites where warming_trend > 15/25." They think:

- "Show me sites where soil temp has been rising for at least a week"
- "Show me sites where soil is above 50F right now"
- "Show me sites where it rained in the last 3 days"

### Proposed: trend-based / reality-based filters

Replace (or supplement) score sliders with **raw data filters**:

| Filter | Type | Range | What it means |
|--------|------|-------|--------------|
| Soil temp now | Range slider | 30-70F | "Only show sites where today's soil is 48-58F" |
| Soil warming rate | Range slider | -2 to +3 F/day | "Only show sites warming at least 0.3F/day" |
| Warming duration | Slider | 0-14 days | "Must have been warming for at least 7 days" |
| Precip last N days | Slider | 0-5 inches | "At least 1 inch in last 10 days" |
| Snow depth | Range slider | 0-24 inches | "No more than 2 inches of snow" |
| Burn age | Range slider | 0-36 months | "Only 3-12 month old burns" |
| Elevation | Range slider | 3000-9000 ft | "Only 5000-7000ft" |
| Aspect | Multi-select | N/NE/E/SE/S/SW/W/NW | "South and SW facing only" |

### Advantages over score-based

1. **Intuitive**: Foragers think in temperatures and inches, not abstract scores
2. **Testable**: "I've found morels when soil is 50-55F" can be directly encoded
3. **Debuggable**: When the model is wrong, you can see exactly which raw value was off
4. **Composable**: "Show me 50F+ soil AND 1in+ precip AND south-facing" is a clear filter chain

### Implementation

The JSON already contains most of these raw values in the `details` fields (soil_temp, precip_14d, snow_status, etc.). The SPA just needs to parse them and filter on the raw values instead of (or alongside) the scores.

The score sliders would remain as a "model view" — what does the algorithm think? The trend sliders would be a "data view" — what are the actual conditions?

### Recommendation

Do both. Two filter tabs in the sidebar:
- **By Score** (current) — filter on model output
- **By Conditions** (new) — filter on raw weather/terrain data

The "By Conditions" view is what you'd use to empirically test hypotheses ("do morels only appear above 50F soil?") and the "By Score" view is what you'd use when you trust the model.

## Files to create/modify

| File | Action |
|------|--------|
| `morel_finder.py` | Add history archival to `export_json()` |
| `utils/field_report.py` | **New** — CLI for adding field reports |
| `utils/analyze_reports.py` | **New** — compare reports to historical predictions |
| `docs/app.js` | Add "By Conditions" filter tab with raw-data sliders |
| `data/field_reports.json` | **New** — field report storage |
| `docs/data/history/` | **New** — daily JSON archives |
