# Scoring Algorithm

Full documentation of the morel foraging scoring model. Each burn site is scored 0-100 across six factors. The burn **is** the candidate — we score the burn location itself, not a point near it.

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
| **0.6.1** | **2026-04-20** | **Cooling trend penalty on GDD, freeze damage detection** | |

## The Biological Model

The weight distribution is grounded in morel biology research:

- **Temperature system (threshold + accumulation) dominates timing (~50%)**. Studies show cumulative warming is more predictive than rainfall for first emergence ([NAMA](https://namyco.org/publications/mcilvainea-journal-of-american-amateur-mycology/is-it-time-for-morels-yet/)).
- **Moisture system controls success (~20%)**. Drought kills the flush entirely, but moisture alone doesn't determine timing ([Nebraskaland](https://magazine.outdoornebraska.gov/blogs/in-the-wild/when-and-where-to-find-morels/)).
- **Everything else is local optimization (~30%)**.

The decision logic:

```
soil >= 50F AND rising temps AND recent moisture  ->  HIGH probability
soil ~= 50F BUT flat temps OR weak moisture       ->  MEDIUM
soil < 48F OR dry                                  ->  LOW
```

## Factor Weights (total: 100)

| Factor | Max | System | What it measures |
|--------|-----|--------|-----------------|
| **A. Soil Temp Threshold** | 25 | Heat (gate) | Is soil 48-58F? Hard gate — below 40F, entire score is crushed. |
| **B. Warming Trend** | 25 | Heat (trigger) | Is soil rising over 2-3 weeks? The actual emergence trigger. |
| **C. Recent Moisture** | 20 | Water | Rain/snowmelt in last 3-10 days. Drives yield. |
| **D. Burn Quality** | 15 | Opportunity | Recency, type (underburn > pile), acreage. |
| **E. Sun / Aspect** | 10 | Modifier | Slope, aspect (S-facing = faster warming), elevation band. |
| **F. Air Temperature** | 5 | Proxy | Daily highs/lows. Indirect driver via soil temps. |

---

## A. Soil Temperature Threshold (0-25) — hard gate

Soil temperature is the non-negotiable prerequisite. Morels will not fruit until soil hits ~48-55F. This factor also acts as a **gate on the entire score** — if soil is too cold, all other factors are scaled down.

From Open-Meteo hourly `soil_temperature_0cm`, aggregated to daily max, averaged over forecast period.

| Avg soil temp | Points | Gate effect on other factors |
|---------------|--------|---------------------------|
| 48-58F (ideal) | 25 | None — full scoring |
| 45-62F (acceptable) | 15 | None |
| 45-48F (approaching) | 8 | All other scores x 0.7 |
| 40-45F (cold) | 3 | All other scores x 0.3 |
| <40F (blocked) | 0 | **All other scores x 0.1** |

*Why a gate?* A burn with perfect moisture, perfect trend, ideal elevation — but 35F soil — will not produce morels. Period. The gate ensures this reality shows up in the score instead of being masked by high marks elsewhere.

---

## B. Warming Trend (0-25) — the timing trigger

The most predictive single factor for morel emergence. Not "is it warm?" but "is it *getting* warmer?" Morels respond to heat accumulation over 20-30 days, not a single temperature reading.

Computed via linear regression (np.polyfit) across the soil temp time series to extract F/day slope. This is robust to single-day spikes unlike the half-split comparison used in earlier versions.

| Trend (F/day) | Points | Signal |
|-------|--------|--------|
| >1.0 | 25 | **RAPID WARMING** — strong flush imminent |
| >0.5 | 21 | **WARMING** — conditions priming |
| >0.2 | 14 | Moderate warming — improving |
| +/- 0.2 | 5 | Flat — not triggering |
| <-0.2 | 0 | Cooling — fruiting stalls |

*This is the key differentiator.* Two burns at the same elevation with the same 52F soil: one warming +0.8F/day scores 21, the other flat scores 5. The warming site will fruit first.

Note: the warming trend score is also subject to the soil gate from factor A. A strong warming trend from 30F to 35F still scores near zero because soil is blocked.

### GDD Modifiers (v0.6.1)

The raw GDD score is modified by two conditions:

**Cooling trend penalty:** If the soil temperature trend is negative (cooling), the GDD score is reduced. Accumulated heat matters, but if temps are dropping, growth stalls and the GDD "bank" isn't being spent productively.

| Trend | GDD modifier |
|-------|-------------|
| Cooling >0.3F/day | GDD score x 0.5 |
| Cooling 0.1-0.3F/day | GDD score x 0.7 |
| Stable or warming | No penalty |

**Freeze damage:** If soil was warm (>45F) at any point in the forecast window, then dropped below freezing (32F) in the last 4 days, primordia that were developing may be damaged or killed. This applies a 0.6x penalty to GDD score.

The freeze penalty only triggers if there was prior warmth — soil that was never above 45F hasn't started growing primordia, so a freeze is not "damage," it's just continued cold.

*These modifiers stack multiplicatively.* A site with strong cooling + freeze after warmth could see GDD score reduced to ~30% of its raw value (0.5 x 0.6 = 0.3).

---

## C. Recent Moisture (0-20) — drives yield

Moisture enables mycelium growth and sustains fruiting. The ideal is active snowmelt (constant seepage) or a solid rain event in the last 3-10 days.

### Precipitation (0-10 pts, 50%)

From Open-Meteo historical daily data, summed over last 14 days:

| 14-day precip | Points |
|---------------|--------|
| >1.5 inches | 10 |
| 0.5-1.5 in | 6 |
| 0.1-0.5 in | 2 |
| <0.1 in | 0 |

### Snowmelt Status (0-8 pts, 40%)

Derived from hourly `snow_depth`, comparing prior period vs current:

| Status | Points | How detected |
|--------|--------|-------------|
| **ACTIVE MELT** | 8 | Past depth >1in, current <50% of past |
| Recently melted | 6.4 | Past >0.5in, current <0.5in |
| Recent snowfall, tapering | 4.8 | Snowfall >2in/30d, last 7d <0.5in |
| Snow-free | 3.2 | No snow in either period |
| Some snow | 2.4 | Present but not trending |
| Snow cover (2-10in) | 1.6 | Moderate pack |
| Deep snowpack (>10in) | -1.6 | Still buried |

### Soil Moisture (0-2 pts, 10%)

From hourly `soil_moisture_0_1cm`, averaged over 7 days:

| Soil moisture | Points |
|---------------|--------|
| 0.20-0.45 m3/m3 | 2 (ideal) |
| Outside range | 0 |

---

## D. Burn Quality (0-15) — the opportunity

Is this a good burn for morels? Recency, type, and size determine whether the mycelium has colonized and is ready to fruit. If the burn is too old (>30 months), type and size bonuses are not awarded — the burn is dead.

### Recency (0-7.5 pts, 50%)

| Age | Points | Rationale |
|-----|--------|-----------|
| 0-2 months | 4.5 | Too fresh — hasn't weathered through a moisture cycle yet |
| **3-8 months** | **7.5** | **Prime window.** Winter burn fruiting in spring. |
| 9-14 months | 6 | Previous year's burn, second flush potential |
| 15-20 months | 3 | Declining — competing fungi establishing |
| 21-30 months | 1.5 | Marginal |
| >30 months | 0 | Done. Type and size bonuses also zeroed. |

### Burn Type (0-4.5 pts, 30%)

Our proxy for burn severity. PFIRS tells us the intended burn type, which correlates with severity.

| Type | Points | Severity proxy |
|------|--------|---------------|
| Underburn / broadcast | 4.5 | Moderate severity. Wide area soil heating, duff removal. Best morel habitat. |
| Hand pile | 3 | Moderate-low. Each ash circle is a micro-habitat. |
| Machine pile | 2.25 | Low-moderate. Intense center heat can sterilize; best at edges. |
| Generic RX | 2.25 | Unknown type, assume moderate. |
| Wildfire | 1.5 | Variable. Low-severity flanks are great; high-severity crown fire often too hot. |

### Size (0-2.25 pts, 15%)

| Acreage | Points |
|---------|--------|
| 20+ acres | 2.25 |
| 5-20 acres | 1.5 |
| <5 acres | 0.75 |

*Note: For hand pile burns, PFIRS "acres" is the project area, not actual burned ground.*

---

## E. Sun / Aspect / Elevation (0-10) — local optimization

Controls local soil warming rate. Computed by sampling USGS elevation points near the burn center to derive slope and aspect.

### Aspect (0-5 pts)

South-facing slopes receive more direct sunlight, melt 1-3 weeks before north-facing at the same elevation, and warm soil faster.

| Aspect | Points |
|--------|--------|
| South (135-225 deg) | 5 |
| East/West (90-270 deg) | 2 |
| North | 0 |

### Slope (0-2 pts)

| Slope | Points |
|-------|--------|
| 5-25 degrees | 2 (good drainage, walkable) |
| <5 degrees | 1 (flat, can waterlog) |
| >25 degrees | 0 (steep, hard to forage) |

### Elevation Band (0-3 pts)

The fruiting band moves upslope ~300ft/month from April:

| Month | Ideal Band |
|-------|-----------|
| April | 4,500 - 7,000 ft |
| May | 4,800 - 7,300 ft |
| June | 5,100 - 7,600 ft |
| July | 5,400 - 7,900 ft |

| Position | Points |
|----------|--------|
| In band | 3 |
| Within 500ft | 2 |
| Within 1000ft | 1 |

---

## F. Air Temperature (0-5) — proxy only

Indirect driver. Air temp influences soil temp over days but is noisy day-to-day. The soil factors above capture the actual biology.

| Sub-factor | Points |
|-----------|--------|
| Daily highs 55-75F | 3 |
| Daily highs 45-85F | 1 |
| Daily lows 30-50F | 2 |
| Daily lows 25-55F | 1 |

---

## Season Gate

Outside **April-July**, all factor scores are halved. Morels can fruit outside this window in the Sierra but it's uncommon. Prevents off-season runs from generating false positives.

---

## Rating Thresholds

| Score | Rating | Map Marker | Meaning |
|-------|--------|-----------|---------|
| 80+ | EXCELLENT | Purple diamond | Go now. Everything aligned. |
| 70-79 | GOOD | Green diamond | Strong candidate, worth the trip. |
| 50-69 | FAIR | Small orange dot | Marginal — check back in a week. |
| <50 | POOR | Not rendered | Not worth showing on the map. |

---

## What the Score Does NOT Capture

- **Vegetation type** — Mixed conifer (ideal) vs chaparral (poor). LANDFIRE data would help.
- **Actual burn severity** — PFIRS burn type is a proxy. dNBR from Sentinel-2 would give real severity maps, but isn't available for small RX burns.
- **Soil type** — Sandy/well-drained soils produce better. NRCS Web Soil Survey API could provide this.
- **Access** — Some burns are on private land, behind locked gates, or in trailless wilderness.
- **Competition** — Popular, accessible burns get picked clean.
- **Surface burn fraction** — Research shows no morels below 50% ground surface burned. We don't have this data for prescribed burns.
- **Cumulative degree-days** — Literature shows 365-580 soil GDD above 0C predicts onset. Planned for v0.6.0.
- **Microsite proximity** — Morels cluster within 3m of burned trunks. Not modelable at our resolution.

---

## Research Basis

The scoring model draws from peer-reviewed field studies. Key findings:

- Soil temp onset at **43F (6.1C)** — [USDA synthesis, French field studies](reference/predictive-modeling-for-burn-scar-morel-mushrooms.md)
- **365-580 cumulative soil degree-days** predict emergence — Missouri 5-year study
- **Rain events >10mm in prior 30 days** increase abundance — Missouri field study
- **First post-fire season** is the dominant fruiting pulse — multiple western NA studies
- South-facing slopes fruit first, moving upslope through season — USDA synthesis
- **3-4 week pre-emergence lag** after soil warms — French development studies
- **Moderate severity** ("red needle zone", 60-80% duff consumed) = peak production — USDA, Kootenay, Yosemite studies

Full literature review: [`reference/predictive-modeling-for-burn-scar-morel-mushrooms.md`](reference/predictive-modeling-for-burn-scar-morel-mushrooms.md)
