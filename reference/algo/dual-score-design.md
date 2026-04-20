# Design: Dual Score Model — Potential vs Timing

## Problem

The current single score (0-100) conflates two fundamentally different questions:

1. **"Has this burn site accumulated enough conditions to produce morels?"** — GDD, burn quality, elevation, aspect. Changes slowly over weeks.
2. **"Can I go find them right now?"** — Current soil temp, snow on ground, today's weather. Changes daily.

This creates confusing results:
- A site scores 82 on a snowy Wednesday because 30 days of warm history pushed GDD high, even though you can't forage that day
- Moisture score drops during a snowstorm because the model sees deep snow as "buried" rather than "water arriving"
- Warming rate shows negative trend but score is still in the 80s because GDD is cumulative and doesn't drop when temps drop
- Users read "82" as "go today" when it really means "this site has good accumulated conditions"

## The biological model (from research)

Morel fruiting is a **two-phase process**:

### Phase 1: Development (weeks)
- Requires cumulative soil warmth (365-580 GDD)
- Burns through one moisture cycle (snowmelt or sustained rain)
- 3-4 week primordia development period underground
- This is the **potential** — has the site banked enough conditions?

### Phase 2: Emergence (days)
- Soil crosses ~45F threshold AND is warming
- Adequate surface moisture (recent rain or active melt)
- Not buried under deep snow
- Not in a hard freeze that could damage developing primordia
- This is the **timing** — can you find them right now?

A site can have **high potential but bad timing** (great accumulated heat, but snowing today). Or **good timing but low potential** (warm sunny day, but the burn is only 1 month old with no GDD).

**You want to go when both are high.**

## Proposed: Two scores per burn site

### Potential Score (0-100) — "Is this site ready to produce?"

Slow-moving factors that represent accumulated conditions:

| Factor | Weight | What it measures |
|--------|--------|-----------------|
| **Soil GDD** | 35 | Cumulative degree-days (365-580 = onset). Doesn't reset on cold days. |
| **Burn Quality** | 30 | Recency (3-8mo prime), type (underburn > pile), acreage |
| **Elevation** | 15 | Is this in the current seasonal fruiting band? |
| **Aspect** | 10 | South-facing = earlier potential (month-adjusted) |
| **Season** | 10 | Are we in the Apr-Jul window? |

**Key properties:**
- Stable over days — doesn't swing 82 → 24 → 89 across a week
- Updates slowly as GDD accumulates through spring
- A cold snap doesn't reduce potential — the heat bank is already built
- Represents "has enough warmth accumulated for primordia to have developed?"

### Timing Score (0-100) — "Can I find them today?"

Fast-moving factors that represent current conditions:

| Factor | Weight | What it measures |
|--------|--------|-----------------|
| **Soil Temp Now** | 30 | Is soil above 45F right now? Hard gate. |
| **Warming Trend** | 20 | Is soil warming or cooling this week? (7-day rolling) |
| **Surface Moisture** | 25 | Recent rain/snowmelt. Active melt = best. |
| **Accessibility** | 15 | Snow on ground? Deep pack = can't forage. |
| **Freeze Risk** | 10 | Has there been a freeze after warmth? Primordia may be damaged. |

**Key properties:**
- Changes daily based on weather
- Drops to near-zero during a snowstorm or cold snap
- Recovers quickly when conditions improve
- The "go/no-go" signal for any specific day

### Combined: The "Go" Signal

| Potential | Timing | Recommendation |
|-----------|--------|---------------|
| High (70+) | High (70+) | **GO NOW** — conditions have built up and today is good |
| High (70+) | Low (<50) | **Wait** — site is ready but today isn't the day (snow, freeze) |
| Low (<50) | High (70+) | **Too early** — nice day but the burn hasn't developed enough yet |
| Low (<50) | Low (<50) | **Skip** — nothing happening here |

## Map visualization

### Markers
- Diamond shape: colored by **Potential** (purple = high, green = good)
- Diamond border/glow: colored by **Timing** (bright = go now, dim = wait)
- Or: show Potential as the stable base, overlay a daily "timing pulse" ring

### Day picker
- Switching days only changes **Timing** scores — Potential stays the same
- This makes the day picker intuitive: "which days have good timing at my high-potential sites?"

### Popup
```
Shake Omo (Underburn)
Potential: 85/100  |  Timing: 72/100 (TODAY)
                              24/100 (Wed — snow)
                              78/100 (Sat — recovery)
```

### Detail page
- Potential section: GDD accumulation chart, burn info, elevation/aspect (static)
- Timing section: 8-day forecast with daily timing scores, soil temp, moisture, snow

## Why this fixes the current confusion

| Current behavior | With dual scores |
|-----------------|-----------------|
| Score 82 on snowy Wednesday | Potential: 82, Timing: 15 → "Wait" |
| Moisture drops during storm | Timing moisture drops (snow = inaccessible), Potential unchanged |
| GDD score 0 for some days | GDD is in Potential only — always the same for all days |
| Warming rate negative but score high | Potential stays high (banked heat). Timing drops (cooling = bad for today) |

## Implementation approach

### Scoring changes (`scoring.py`)

Split `score_burn_site` into two functions:
- `score_potential(fire, weather, elev, terrain)` → stable score from GDD, burn, elevation, aspect
- `score_timing(weather, day_offset)` → daily score from current conditions

The combined score can still exist as `potential * 0.5 + timing * 0.5` or as two separate numbers.

### JSON changes

```json
{
  "potential": 85,
  "potential_scores": { "soil_gdd": 35, "burn_quality": 25, ... },
  "days": [
    { "day": 0, "timing": 72, "timing_scores": { "soil_now": 25, ... } },
    { "day": 1, "timing": 24, ... },
    ...
  ]
}
```

### Config changes

Two weight dicts in the morel profile:
```python
"potential_weights": { "soil_gdd": 35, "burn_quality": 30, "elevation": 15, "aspect": 10, "season": 10 },
"timing_weights": { "soil_now": 30, "warming_trend": 20, "surface_moisture": 25, "accessibility": 15, "freeze_risk": 10 },
```

### Frontend changes
- Map: marker color = Potential, marker opacity/glow = Timing for selected day
- Day picker: only Timing changes
- Detail page: Potential section (static) + Timing section (per-day)
- Filter sliders: separate tabs for Potential and Timing filters
