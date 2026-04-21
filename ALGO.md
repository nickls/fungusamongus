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
| **0.7.0** | **2026-04-20** | **Phase-based model: Potential + Readiness replaces single score** | **[v0.7.0](reference/algo/v0.7.0.md)** |

---

## Current Model (v0.7.0) — Phase-Based Scoring

The v0.5/0.6 model used a single 0-100 weighted score that conflated site quality with daily weather. A burn could score 82 on a snowy day because accumulated GDD was high. Users read "82" as "go today" when it really meant "this site has good long-term conditions."

**v0.7.0 splits into two independent scores:**

### Potential (0-100) — "Is this a good burn site?"

Stable. Doesn't change day to day. Based on the burn itself, not weather.

| Factor | Weight | What it measures |
|--------|--------|-----------------|
| **Burn Quality** | 50 | Recency (3-8mo prime), type (underburn > pile), acreage |
| **Elevation** | 20 | Is this in the current seasonal fruiting band? |
| **Aspect** | 15 | South-facing advantage (month-adjusted) |
| **Season** | 10 | Are we in the Apr-Jul window? |
| **Freeze Damage** | 5 | Penalty if freeze killed developing primordia |

Burn quality recency curve:

| Age | % of weight | Rationale |
|-----|------------|-----------|
| 0-2 months | 30% | Too fresh — hasn't weathered through moisture cycle |
| **3-8 months** | **50%** | **Prime window** |
| 9-14 months | 40% | Second season, still productive |
| 15-20 months | 20% | Declining |
| 21-30 months | 10% | Marginal |
| >30 months | 0% | Done — type/size bonus also zeroed |

### Readiness (0-100) — "Is this site ready to produce morels?"

Changes daily. Based on a rolling window analysis of weather conditions.

**How it works:** Each of the last 44 days (30 history + 14 forecast) is classified as one of:

| Status | Conditions | Biology |
|--------|-----------|---------|
| **START** | Soil warming into 43-50F + moisture event | Primordia initiating |
| **START_GROW** | Soil 45-58F + warming + sustained moisture | Triggering AND sustaining |
| **GROW** | Soil 45-58F + moisture present | Development continuing |
| **BAD** | Soil <43F, freeze after warmth, >24in snow, or >58F | Nothing happening |

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

- **Diamond shape** = potential >= 70 (good burn site)
- **Diamond size** = 3 tiers: big (pot 90+), medium (75+), small (70+)
- **Diamond color** = phase (purple=EMERGING, green=GROWING, orange=WAITING)
- **Number inside** = readiness score
- **Small dots** = potential < 70

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

- **Vegetation type** — mixed conifer (ideal) vs chaparral (poor). LANDFIRE planned.
- **Actual burn severity** — PFIRS burn type is a proxy. dNBR satellite data would be better.
- **Soil type** — sandy/well-drained soils produce better.
- **Surface burn fraction** — research shows no morels below 50% ground surface burned.
- **Microsite proximity** — morels cluster within 3m of burned trunks.
- **Access** — some burns are on private land or behind locked gates.
- **Competition** — popular burns get picked clean.
- **Driving time** — straight-line distance is misleading in mountains.
