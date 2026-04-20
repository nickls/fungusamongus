# Morel Foraging Recommender

Scores burn sites in the Greater Tahoe Basin for morel mushroom foraging potential by combining fire history, real-time weather, elevation, and snowmelt data.

Centered on **Alder Creek Adventure Center** (Truckee, CA). Produces two interactive maps per run:
- **Local map** (~30mi radius) — nearby burns for day trips
- **Basin map** (~75mi radius) — Nevada City to South Lake Tahoe

Each run is date-stamped (`morel_local_2026-04-19.html`) so you can compare conditions across days.

## Why burn sites?

Morels (*Morchella* spp.) in the Sierra Nevada are strongly fire-associated. The key insight driving this tool:

**Score the burn, not a random point near the burn.** Early versions scored named locations ("Tahoe Donner", "Prosser Creek") and checked for nearby fires. This is backwards — a pile burn 4km from "Tahoe Donner N" means the *burn itself* is the spot. We now score every known burn location directly.

## Datasets

### PFIRS (Prescribed Fire Information Reporting System)
- **Source:** California Air Resources Board — `ssl.arb.ca.gov/pfirs/`
- **What it has:** Every prescribed burn ignition in California with lat/lon, date, acres, burn type (underburn, hand pile, machine pile), managing agency, status
- **Why it matters:** This is the **highest-signal data source**. Small 5-50ac USFS pile burns and underburns are the best morel habitat, and they only exist here. MTBS misses them (>1000ac threshold), WFIGS misses them, CAL FIRE perimeters miss them.
- **Catch:** No public API. Data is server-rendered into the HTML as inline Google Maps markers. We scrape it with `utils/pfirs.py`.
- **Refresh:** Run `python -m utils.pfirs --fetch --cookie 'PHPSESSID=...'` with a browser session cookie. Date range selectable. Cached as `cache/pfirs_all.json`.

### Tahoe Forest Fuels Treatments (USFS)
- **Source:** ArcGIS FeatureServer — `services6.arcgis.com/.../Tahoe_Forest_Fuels_Tx_OFFICIAL_Public_View`
- **Item:** [arcgis.com/home/item.html?id=0d3892e995644acdbb73fcb31bb07cd4](https://www.arcgis.com/home/item.html?id=0d3892e995644acdbb73fcb31bb07cd4)
- **What it has:** All fuel treatment polygons (prescribed burns + mechanical thinning) in the Tahoe area. Fields: ACT (activity type), YEAR, ACRES, CATEGORY, PROJ. Updated annually (last: Mar 2026).
- **Why it matters:** Covers treatments that PFIRS misses (mechanical work, older burns). Provides polygon geometry so we know the actual burn footprint, not just a point.
- **Limitation:** Basin-centric — coverage drops off north of Truckee. Year-level granularity only (no exact dates).

### NIFC Interagency Fire Perimeter History
- **Source:** ArcGIS FeatureServer — `services3.arcgis.com/.../InteragencyFirePerimeterHistory_All_Years_View`
- **What it has:** All federal interagency fire perimeters (wildfire + prescribed) with polygon geometry. Fields: INCIDENT, GIS_ACRES, DATE_CUR, FIRE_YEAR_INT, AGENCY.
- **Why it matters:** Only reliable free public federal fire perimeter API as of 2026. WFIGS year-specific endpoints are dead. CAL FIRE and IRWIN now require auth tokens.
- **Limitation:** Skews toward larger fires. 2025-2026 data may lag.

### Open-Meteo
- **Source:** `api.open-meteo.com` (forecast) + `archive-api.open-meteo.com` (historical)
- **What we pull:** 30-day historical temps/precip/snowfall, 7-day forecast temps/precip, hourly soil temperature (0cm depth), hourly soil moisture (0-1cm), hourly snow depth
- **Key variables:** `soil_temperature_0cm`, `soil_moisture_0_1cm`, `snow_depth` (hourly); `temperature_2m_max/min`, `precipitation_sum`, `snowfall_sum` (daily)
- **Note:** `soil_temperature_6cm_max` and `soil_temperature_0_10cm` do NOT work as daily forecast variables despite documentation. Use hourly `soil_temperature_0cm` and aggregate to daily.

### USGS Elevation Point Query Service
- **Source:** `epqs.nationalmap.gov/v1/json`
- **What it does:** Returns elevation in feet for any lat/lon point
- **Why it matters:** Elevation determines the seasonal window. Morels fruit at lower elevations first, then move upslope as snow melts.

### Dead/broken APIs (as of April 2026)
- **WFIGS 2024/2025 Wildfire Perimeters** (`services1.arcgis.com/.../WFIGS_2024_Wildfire_Perimeters`) — returns "Invalid URL"
- **CAL FIRE California_Fire_Perimeters** (`services1.arcgis.com/.../California_Fire_Perimeters`) — returns "Token Required"
- **NIFC IRWIN Incidents** (`services3.arcgis.com/.../IRWIN_Incidents`) — returns "Token Required"
- **USFS FACTS** (`apps.fs.usda.gov/arcx/rest/services/EDW/...`) — persistent timeouts

## Scoring Model (v0.4.0)

Each burn site is scored 0-100 across six factors. The burn **is** the candidate — we're scoring the burn location itself, not a point near it. The popup on each map marker shows the exact breakdown per factor.

### The biological model

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

### Factor Weights (total: 100)

| Factor | Max | System | What it measures |
|--------|-----|--------|-----------------|
| **A. Soil Temp Threshold** | 25 | Heat (gate) | Is soil 48-58F? Hard gate — below 40F, entire score is crushed. |
| **B. Warming Trend** | 25 | Heat (trigger) | Is soil rising over 2-3 weeks? The actual emergence trigger. |
| **C. Recent Moisture** | 20 | Water | Rain/snowmelt in last 3-10 days. Drives yield. |
| **D. Burn Quality** | 15 | Opportunity | Recency, type (underburn > pile), acreage. |
| **E. Sun / Aspect** | 10 | Modifier | Slope, aspect (S-facing = faster warming), elevation band. |
| **F. Air Temperature** | 5 | Proxy | Daily highs/lows. Indirect driver via soil temps. |

---

### A. Soil Temperature Threshold (0-25) — hard gate

Soil temperature is the non-negotiable prerequisite. Morels will not fruit until soil hits ~48-55F. This factor also acts as a **gate on the entire score** — if soil is too cold, all other factors are scaled down.

From Open-Meteo hourly `soil_temperature_0cm`, aggregated to daily max, averaged over forecast period.

| Avg soil temp | Points | Gate effect on other factors |
|---------------|--------|---------------------------|
| 48-58F (ideal) | 25 | None — full scoring |
| 45-62F (acceptable) | 15 | None |
| 45-48F (approaching) | 8 | All other scores x 0.7 |
| 40-45F (cold) | 3 | All other scores x 0.4 |
| <40F (blocked) | 0 | **All other scores x 0.1** |

*Why a gate?* A burn with perfect moisture, perfect trend, ideal elevation — but 35F soil — will not produce morels. Period. The gate ensures this reality shows up in the score instead of being masked by high marks elsewhere.

---

### B. Warming Trend (0-25) — the timing trigger

The most predictive single factor for morel emergence. Not "is it warm?" but "is it *getting* warmer?" Morels respond to heat accumulation over 20-30 days, not a single temperature reading.

Computed by comparing the first half vs second half of the soil temp time series (~7 days each):

| Trend | Points | Signal |
|-------|--------|--------|
| Rising >5F | 25 | **RAPID WARMING** — strong flush imminent |
| Rising >3F | 21 | **WARMING** — conditions priming |
| Rising 1-3F | 14 | Moderate warming — improving |
| Stable (+/- 1F) | 5 | Flat — not triggering |
| Falling >1F | 0 | Cooling — fruiting stalls |

*This is the key differentiator.* Two burns at the same elevation with the same 52F soil: one warming +4F/week scores 21, the other flat scores 5. The warming site will fruit first.

Note: the warming trend score is also subject to the soil gate from factor A. A strong warming trend from 30F to 35F still scores near zero because soil is blocked.

---

### C. Recent Moisture (0-20) — drives yield

Moisture enables mycelium growth and sustains fruiting. The ideal is active snowmelt (constant seepage) or a solid rain event in the last 3-10 days.

#### Precipitation (0-10 pts, 50%)

From Open-Meteo historical daily data, summed over last 14 days:

| 14-day precip | Points |
|---------------|--------|
| >1.5 inches | 10 |
| 0.5-1.5 in | 6 |
| 0.1-0.5 in | 2 |
| <0.1 in | 0 |

#### Snowmelt Status (0-8 pts, 40%)

Derived from hourly `snow_depth`, comparing 7-day-ago vs current average:

| Status | Points | How detected |
|--------|--------|-------------|
| **ACTIVE MELT** | 8 | Past depth >1in, current <50% of past |
| Recently melted | 6.4 | Past >0.5in, current <0.5in |
| Recent snowfall, tapering | 4.8 | Snowfall >2in/30d, last 7d <0.5in |
| Snow-free | 3.2 | No snow in either period |
| Some snow | 2.4 | Present but not trending |
| Snow cover (2-10in) | 1.6 | Moderate pack |
| Deep snowpack (>10in) | -1.6 | Still buried |

#### Soil Moisture (0-2 pts, 10%)

From hourly `soil_moisture_0_1cm`, averaged over 7 days:

| Soil moisture | Points |
|---------------|--------|
| 0.20-0.45 m3/m3 | 2 (ideal) |
| Outside range | 0 |

---

### D. Burn Quality (0-15) — the opportunity

Is this a good burn for morels? Recency, type, and size determine whether the mycelium has colonized and is ready to fruit.

#### Recency (0-7.5 pts, 50%)

| Age | Points | Rationale |
|-----|--------|-----------|
| 0-2 months | 4.5 | Too fresh — hasn't weathered through a moisture cycle yet |
| **3-8 months** | **7.5** | **Prime window.** Winter burn fruiting in spring. |
| 9-14 months | 6 | Previous year's burn, second flush potential |
| 15-20 months | 3 | Declining — competing fungi establishing |
| 21-30 months | 1.5 | Marginal |
| >30 months | 0 | Done |

#### Burn Type (0-4.5 pts, 30%)

Our proxy for burn severity. PFIRS tells us the intended burn type, which correlates with severity. Actual dNBR satellite data would be better but isn't available for small RX burns.

| Type | Points | Severity proxy |
|------|--------|---------------|
| Underburn / broadcast | 4.5 | Moderate severity. Wide area soil heating, duff removal, pH shift. Best morel habitat. |
| Hand pile | 3 | Moderate-low. Each ash circle is a micro-habitat. Check pile scars individually. |
| Machine pile | 2.25 | Low-moderate. Intense heat at center can sterilize; best at edges. |
| Generic RX | 2.25 | Unknown type, assume moderate. |
| Wildfire | 1.5 | Variable. Low-severity flanks are great; high-severity crown fire zones often too hot. |

#### Size (0-2.25 pts, 15%)

| Acreage | Points |
|---------|--------|
| 20+ acres | 2.25 |
| 5-20 acres | 1.5 |
| <5 acres | 0.75 |

*Note: For hand pile burns, PFIRS "acres" is the project area, not actual burned ground. A "5 acre hand pile" project might have 20 individual pile scars totaling 0.5 acres of actual burn.*

---

### E. Sun / Aspect / Elevation (0-10) — local optimization

Controls local soil warming rate. Computed by sampling 4 USGS elevation points ~55m from center to derive slope and aspect.

#### Aspect (0-5 pts)

South-facing slopes receive more direct sunlight, melt 1-3 weeks before north-facing at the same elevation, and warm soil faster.

| Aspect | Points |
|--------|--------|
| South (135-225 deg) | 5 |
| East/West (90-270 deg) | 2 |
| North | 0 |

#### Slope (0-2 pts)

| Slope | Points |
|-------|--------|
| 5-25 degrees | 2 (good drainage, walkable) |
| <5 degrees | 1 (flat, can waterlog) |
| >25 degrees | 0 (steep, hard to forage) |

#### Elevation Band (0-3 pts)

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

### F. Air Temperature (0-5) — proxy only

Indirect driver. Air temp influences soil temp over days but is noisy day-to-day. The soil factors above capture the actual biology.

| Sub-factor | Points |
|-----------|--------|
| Daily highs 55-75F | 3 |
| Daily highs 45-85F | 1 |
| Daily lows 30-50F | 2 |
| Daily lows 25-55F | 1 |

---

### Season Gate

Outside **April-July**, all factor scores are halved. Morels can fruit outside this window in the Sierra but it's uncommon. Prevents off-season runs from generating false positives.

---

### Rating Thresholds

| Score | Rating | Map Marker | Meaning |
|-------|--------|-----------|---------|
| 80+ | EXCELLENT | Purple diamond | Go now. Everything aligned. |
| 70-79 | GOOD | Green diamond | Strong candidate, worth the trip. |
| 50-69 | FAIR | Small orange dot | Marginal — check back in a week. |
| <50 | POOR | Not rendered | Not worth showing on the map. |

---

### What the score does NOT capture

- **Vegetation type** — Mixed conifer (ideal) vs chaparral (poor). LANDFIRE data would help.
- **Actual burn severity** — PFIRS burn type is a proxy. dNBR from Sentinel-2 would give real severity maps, but isn't available for small RX burns.
- **Soil type** — Sandy/well-drained soils produce better. NRCS Web Soil Survey API could provide this.
- **Access** — Some burns are on private land, behind locked gates, or in trailless wilderness.
- **Competition** — Popular, accessible burns get picked clean.

## Map Visualization

### Burn markers
- **Diamond markers** with score number — burns scoring 70+ (EXCELLENT). These are the "go here" signals.
- **Small dots** — everything scoring below 70, colored by rating tier.

### Heatmap
Each scored burn generates a cluster of heat points **scattered across its actual acreage footprint**. A single PFIRS point for a 30-acre burn gets expanded into a ring of points covering the ~350m burn radius, weighted by `score * 3`. This means:
- The heatmap blob size reflects real burn acreage, not a fixed pixel radius
- High-scoring large burns glow intensely; small low-scoring burns are dim
- Nearby burns merge into corridors showing where to focus a trip
- Burns >15ac get two rings (inner + outer) for denser fill

### Layers (toggle in top-right control)
- **Morel Sites** — scored burn markers (diamonds + dots)
- **Morel Heatmap** — acre-proportional intensity overlay
- **Fire Perimeters** — NIFC/Tahoe Fuels Tx polygon outlines (off by default)
- **CARTO Voyager / Esri Topo** — base map options

## Architecture

```
morel_finder.py        # Main script — scoring, maps, reports
utils/
  __init__.py
  pfirs.py             # PFIRS scraper + parser + cache
cache/                 # API response cache (gitignored)
  pfirs_all.json       # All PFIRS burns (statewide)
  pfirs_tahoe.json     # Filtered to greater Tahoe area
  *.json               # Weather, elevation, fire API responses
```

## Usage

```bash
# First run — set up
python3 -m venv .venv
source .venv/bin/activate
pip install requests pandas numpy folium matplotlib

# Refresh PFIRS data (need browser cookie — see utils/pfirs.py header)
python -m utils.pfirs --fetch --begin 01/01/2025 --end 04/19/2026 --cookie 'PHPSESSID=...; TS01ad8875=...'

# Or parse previously saved HTML
python -m utils.pfirs --parse-raw

# Run analysis
python morel_finder.py

# Outputs (date-stamped):
#   morel_local_2026-04-19.html   — 30mi radius from Alder Creek
#   morel_basin_2026-04-19.html   — Greater Tahoe Basin
#   morel_results_2026-04-19.csv  — Top 100 burns ranked
```

## Caching

All API responses are cached locally in `cache/`:
- **Weather:** 6-hour TTL (conditions change)
- **Fire/elevation data:** 24-hour TTL (stable)
- **PFIRS data:** Manual refresh (run `utils/pfirs.py`)

Second runs are near-instant if cache is warm.

## Future work

### Data enrichment
- **Soil type** — USDA NRCS Web Soil Survey API. Sandy/well-drained soils produce better morels. Critical for chanterelle/matsutake candidate generation.
- **Tree species / vegetation type** — LANDFIRE 30m rasters (EVT layer). Mixed conifer (fir/pine) is the Sierra morel sweet spot. Oak/tanoak association needed for chanterelles, pine for matsutake.
- **Burn severity** — dNBR from Sentinel-2. Differentiate moderate understory burns (ideal) from high-severity canopy kills (less productive for morels, though still viable).

### Features
- **Interactive score filter sliders** — JS control panel on the map to filter markers by individual factor thresholds (e.g. "show only burns where warming_trend > 20"). Requires emitting score data as JSON + custom JS overlay on the folium output.
- Per-mushroom-type scoring (chanterelles, porcini, matsutake) with different candidate generation — mature forest sites, tree association data, not burn sites
- PFIRS auto-refresh without browser cookie
- Static PNG map export for GitHub Pages
- Multi-day forecast scoring (score burns for each of next 7 days)
- Integration with Gaia GPS / CalTopo for field navigation
