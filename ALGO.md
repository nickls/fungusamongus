# Scoring Algorithm

Full documentation of the morel foraging scoring model.

See also: [Predictive Modeling Research](reference/predictive-modeling-for-burn-scar-morel-mushrooms.md)

## Version History

| Version | Date | Key Changes | Details |
|---------|------|-------------|---------|
| 0.1.0 | 2026-04-19 | Fixed zone scoring with fire proximity | |
| 0.2.0 | 2026-04-19 | Burn-location-based scoring, PFIRS integration | |
| 0.3.0 | 2026-04-19 | Moisture gate, warming trend, config-driven, terrain | |
| 0.4.0 | 2026-04-19 | Soil temp hard gate, 4-factor model | [v0.4.0](reference/algo/v0.4.0.md) |
| 0.5.0 | 2026-04-20 | 6-factor model, per-day scoring, SPA, 59 tests | [v0.5.0](reference/algo/v0.5.0.md) |
| 0.6.0 | 2026-04-20 | Soil GDD, historical soil temp, multi-point aspect, rain events | [v0.6.0](reference/algo/v0.6.0.md) |
| 0.6.1 | 2026-04-20 | Cooling trend penalty on GDD, freeze damage detection | |
| 0.7.0 | 2026-04-20 | Phase-based model: Potential + Readiness replaces single score | [v0.7.0](reference/algo/v0.7.0.md) |
| 0.7.1 | 2026-04-21 | LANDFIRE EVT vegetation (15pts), burn type fix, field report #1 | |
| 0.8.0 | 2026-05-02 | Multi-species scaffolding (porcini biology wired, per-type output paths) | |
| 0.8.1 | 2026-05-03 | PAST_PRIME status + readiness taper, smooth diamond size 60→90 | |
| **0.8.2** | **2026-05-03** | **Field-anchored PAST_PRIME thresholds (grow_max 68F, taper 2-day grace)** | |

---

## Current Model (v0.8.2) — Phase-Based Scoring

The v0.5/0.6 model used a single 0-100 weighted score that conflated site quality with daily weather. A burn could score 82 on a snowy day because accumulated GDD was high. Users read "82" as "go today" when it really meant "this site has good long-term conditions."

**v0.7.0 splits into two independent scores:**

### Potential (0-100) — "Is this a good burn site?"

Stable. Doesn't change day to day. Based on the burn itself, not weather.

| Factor | Weight | What it measures |
|--------|--------|-----------------|
| **Burn Quality** | 40 | Recency (3-8mo prime), type (machine pile > hand pile > underburn), acreage |
| **Vegetation** | 15 | LANDFIRE EVT — mixed conifer best, sagebrush worst |
| **Elevation** | 15 | Is this in the current seasonal fruiting band? |
| **Aspect** | 10 | South-facing advantage (month-adjusted) |
| **Season** | 10 | Are we in the Apr-Jul window? |
| **Freeze Damage** | 10 | Penalty if freeze killed developing primordia |

Burn quality recency curve:

| Age | % of weight | Rationale |
|-----|------------|-----------|
| 0-2 months | 30% | Too fresh — hasn't weathered through moisture cycle |
| **3-8 months** | **50%** | **Prime window** |
| 9-14 months | 40% | Second season, still productive |
| 15-20 months | 20% | Declining |
| 21-30 months | 10% | Marginal |
| >30 months | 0% | Done — type/size bonus also zeroed |

Burn type scores (fraction of burn_quality weight):

| Burn Type | Score | Rationale |
|-----------|-------|-----------|
| **Machine pile** | 0.45 | Deep soil heating, full duff consumption, heavy ash. Highest yield but very patchy (1-5m clusters around pile scars). |
| **Wildfire** | 0.35 | Best when moderate severity. Highly variable — needs dNBR for accurate scoring. |
| **Hand pile** | 0.30 | Similar mechanism to machine pile but weaker intensity, smaller footprint. More numerous = better coverage. |
| **Broadcast** | 0.25 | Moderate severity, variable results. |
| **RX (generic)** | 0.15 | Unspecified prescribed burn — assume moderate. |
| **Underburn** | 0.05 | Generally poor — low duff consumption, minimal soil heating, trees survive. Near-zero unless localized hotspots. |

**Why this ordering:** Morels respond to duff removal + mineral soil exposure + root death + reduced microbial competition. Machine pile > hand pile > underburn in all three variables. Confirmed by T27 field report (underburn, no morels despite "good" weather scores).

Vegetation type suitability (from LANDFIRE LF2024 EVT via ImageServer identify):

| Vegetation Type | Suitability | Code Examples |
|----------------|-------------|---------------|
| **Mixed conifer** (white fir, sugar pine) | 1.0 | 7027, 7028 |
| **Aspen-mixed conifer** | 0.9 | 7080 |
| **Jeffrey/ponderosa pine** | 0.8 | 7031 |
| **Red fir** | 0.8 | 7033 |
| **East Cascades mixed conifer** | 0.7 | 7011 |
| **Subalpine lodgepole** | 0.5 | 7044 |
| **Subalpine woodland** | 0.4 | 7098, 7105 |
| **Pinyon-juniper** | 0.2 | 7126 |
| **Sagebrush / shrubland** | 0.0 | 7299 |
| **Developed / water** | 0.0 | 9xxx, 7292 |

### Readiness (0-100) — "Is this site ready to produce morels?"

Changes daily. Based on a rolling window analysis of weather conditions.

**How it works:** Each of the last 44 days (30 history + 14 forecast) is classified as one of:

| Status | Conditions | Biology |
|--------|-----------|---------|
| **START** | Soil warming into 43-50F + moisture event | Primordia initiating |
| **START_GROW** | Soil 45-58F + warming + sustained moisture | Triggering AND sustaining |
| **GROW** | Soil 45-58F + moisture present | Development continuing |
| **PAST_PRIME** | Soil 68-78F (warming-trigger species, morel) | Flush declining but still harvestable |
| **BAD** | Soil <43F, freeze after warmth, >24in snow, or >78F | Nothing happening |

**Field-anchored thresholds (v0.8.2):** Initial v0.8.1 values used the `classify_day` defaults (grow_max=58F, past_prime_max=75F), which flagged Unit 2.3 as PAST_PRIME on Apr 30 — the same day a 4-5lb harvest happened at 60ish soil temps. Field reality: morels fruit well into the mid-60s. Morel profile now overrides:
- `grow_soil_max = 68F` (raised from 58F)
- `past_prime_max = 78F` (raised from 75F)

**Past-prime taper:** PAST_PRIME days count toward `grow_days_total` (biological progress preserved) but trigger a deterministic readiness multiplier `max(0.50, 1 - 0.08 × max(0, past_prime_recent − 2))`, where `past_prime_recent` is the count of PAST_PRIME days in the last 7 days. The 2-day grace tolerates noise (a single hot afternoon doesn't tank readiness). Effect:

| PAST_PRIME days (last 7) | Multiplier |
|---|---|
| 0-2 | 1.00 (grace window) |
| 3 | 0.92 |
| 5 | 0.76 |
| 7 | 0.60 |
| Any sustained | 0.50 (floor) |

The taper catches the regression's blind spot — `current_soil` (-0.27) and `soil_avg_14d` (+0.34) net out to ~+0.07/°F, so without the taper, hot sites looked *better* than cool ones.

Then readiness looks backward from the target day:
1. Were there **START days** in the lookback window (7-30 days ago)?
2. Were there enough **GROW days** since? (14+ = EMERGING)
3. Were there any prolonged **BAD streaks** (>3 days) that reset growth?

### Phase Labels

| Phase | Meaning | Map display |
|-------|---------|-------------|
| **EMERGING** | 1+ start days + 14+ grow days, no reset | Purple diamond — GO NOW |
| **GROWING** | Start happened, accumulating grow days | Green diamond — go soon |
| **WAITING** | Start happened but not enough grow days, or growth was reset | Orange diamond/dot — not yet |
| **TOO_EARLY** | No start event detected | Hidden from map |

### Readiness Scoring (Logistic Regression)

The readiness score is computed via logistic regression coefficients learned from 70 labeled scenarios (21 synthetic + 49 real-world from cached API data). 89% accuracy.

Features extracted from the timeline:

| Feature | Coefficient | Direction |
|---------|------------|-----------|
| is_currently_good | +1.04 | Today being a GROW day is #1 |
| precip_events | +0.70 | Count of >0.4in rain events in 30 days |
| warming_rate | +0.37 | 7-day rolling soil temp trend |
| soil_avg_14d | +0.34 | Mean soil temp over 14 days |
| max_bad_streak | -0.20 | Longest consecutive BAD days |
| grow_days | +0.19 | Count of GROW days since first START |
| start_days | +0.09 | Count of START days in lookback window |

Re-fit with: `python -m utils.fit_regression --json data/real_scenarios_labeled.json`

### Map Visualization

- **Diamond shape** = potential >= 60 (any decent burn site)
- **Diamond size** = smooth linear taper, 12px at potential 60 → 32px at potential 90+
- **Diamond color** = phase (purple=EMERGING, green=GROWING, orange=WAITING)
- **Number inside** = readiness score
- **Small dots** = potential < 60

Day picker changes readiness/phase. Potential stays stable.

### Combined Interpretation

| Potential | Readiness | Phase | Action |
|-----------|-----------|-------|--------|
| High (90+) | High (70+) | EMERGING | **DROP EVERYTHING AND GO** |
| High (90+) | Low (25) | WAITING | Great site, not ready. Check back. |
| Low (50) | High (90) | EMERGING | Mediocre burn but conditions are right. Worth a look. |
| Low (50) | Low (10) | TOO_EARLY | Skip. |

---

## Research Basis

Key findings from peer-reviewed studies (full review: [reference/predictive-modeling-for-burn-scar-morel-mushrooms.md](reference/predictive-modeling-for-burn-scar-morel-mushrooms.md)):

- Soil temp onset at **43F (6.1C)** — French field studies, USDA synthesis
- **365-580 cumulative soil GDD** above 0C predicts emergence — Missouri 5-year study
- Rain events **>10mm in prior 30 days** increase abundance
- **3-4 week pre-emergence lag** after soil warms
- First post-fire season is the dominant fruiting pulse
- **Moderate severity** ("red needle zone", 60-80% duff consumed) = peak production
- South-facing slopes fruit first, moving upslope through season

---

## What the Model Does NOT Capture

- ~~Vegetation type~~ — **Done** (v0.7.1). LANDFIRE LF2024 EVT, 15 pts in potential.
- **Actual burn severity** — PFIRS burn type is a proxy. dNBR from Sentinel-2 would score individual burns by actual fire intensity.
- **Soil type** — sandy/well-drained soils produce better.
- **Surface burn fraction** — research shows no morels below 50% ground surface burned.
- **Microsite proximity** — morels cluster within 3m of burned trunks.
- **Access** — some burns are on private land or behind locked gates.
- **Competition** — popular burns get picked clean.
- **Driving time** — straight-line distance is misleading in mountains.

---

## Field Reports

| Date | Site | Result | Key Learnings |
|------|------|--------|---------------|
| 2026-04-20 | T27 Underburn | **No morels** | Soil too cold (winter, not cold snap). Burn sporadic/shallow — underburn type ≠ adequate severity. Led to burn type score inversion fix. |

Field reports stored in `data/field_reports.json`.
