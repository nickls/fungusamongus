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

## Scoring Model

Each burn site is scored 0-100 across four factors, plus a terrain bonus. The burn **is** the candidate — there's no "proximity to fire" calculation because we're scoring the burn location itself.

Every factor uses percentage-based sub-scoring against its weight, so the math is transparent and tunable. The popup on each map marker shows the exact breakdown.

### Factor Weights (total: 100 + up to 5 terrain bonus)

The weight distribution reflects the biological model: **moisture is the gate, soil temperature is the trigger, burn is the opportunity.**

- Dry + perfect temp = nothing
- Wet + wrong temp = nothing
- Wet + warming soil + recent burn = **morels**

| Factor | Max | Role | What it measures |
|--------|-----|------|-----------------|
| **Burn Quality** | 35 | Opportunity | Recency, type, acreage — is this burn producing? |
| **Moisture** | 30 | Gate | Recent precip, snowmelt, soil moisture — is there water? |
| **Temperature** | 25 | Trigger | Soil temp (45% of this), air temps — is it warm enough? |
| **Elevation** | 10 | Timing | Is this site in the current seasonal fruiting band? |
| **Terrain** | +5 | Bonus | Slope + aspect — south-facing melts first |

---

### Burn Quality (0-40)

The dominant factor. Morels fruit on burns, and recency + type determine productivity. This factor has three sub-components.

#### Recency (0-20 pts, 50% of burn_quality)

A burn needs to weather through at least one moisture cycle (snow + melt, or sustained rain) before morel mycelium colonizes and fruits. A burn from last week hasn't had that cycle. A burn from 3 years ago has been colonized and exhausted.

| Age | Points | % of 40 | Rationale |
|-----|--------|---------|-----------|
| 0-2 months | 12 | 30% | Too fresh — hasn't weathered yet. Soil biology hasn't responded. *Exception:* if heavy rain/snow has already cycled (captured by moisture score). |
| 3-8 months | 20 | 50% | **Prime window.** Winter burn (Oct-Feb) fruiting the following spring (Apr-Jul). One full moisture cycle complete. |
| 9-14 months | 16 | 40% | Previous year's burn, potential second flush. Still productive but peak has passed. |
| 15-20 months | 8 | 20% | Declining. Mycelium moving on, competing fungi establishing. |
| 21-30 months | 4 | 10% | Marginal. Occasional finds but not worth targeting. |
| >30 months | 0 | 0% | Done. The morel window has closed for this burn. |

*Why the 0-2 month penalty?* A January burn under 4 feet of snow hasn't had any biological response yet. The moisture score will be high (active melt) but the burn itself hasn't produced mycelium. In practice, a 2-month-old burn that has already melted out and received rain can still score well overall because the moisture and temperature factors compensate. The burn_quality score just reflects that it's not as proven as a 5-month-old burn with the same conditions.

#### Burn Type (0-12 pts, 30% of burn_quality)

Not all burns produce morels equally. The type of burn determines severity and ground disturbance:

| Type | Points | % of 40 | Why |
|------|--------|---------|-----|
| Underburn / broadcast | 12 | 30% | Best for morels. Wide area of moderate soil heating. Kills surface duff, exposes mineral soil, creates ideal pH shift. The fire passes through but doesn't sterilize. |
| Hand pile | 8 | 20% | Good but localized. Each pile site is a morel micro-habitat (the ash circle). Need to check each pile scar individually. |
| Machine pile | 6 | 15% | Decent. Larger piles = more intense heat at center, which can sterilize soil. Best morels around edges of pile scars. |
| Generic prescribed (RX) | 6 | 15% | Source didn't specify type. Assume moderate. |
| Wildfire | 4 | 10% | Variable. Low-severity flanks are great, but high-severity crown fire zones are often too hot and lack surviving root systems. NIFC perimeters don't tell us severity within the perimeter. |

#### Size (0-6 pts, 15% of burn_quality)

Bigger burns = more area to search = higher probability of finding productive patches:

| Acreage | Points | % of 40 |
|---------|--------|---------|
| 20+ acres | 6 | 15% |
| 5-20 acres | 4 | 10% |
| <5 acres | 2 | 5% |

*Note: For hand pile burns, the "acres" from PFIRS is the project area, not the actual burned area. A "5 acre hand pile" project might have 20 individual pile scars totaling 0.5 acres of actual burned ground.*

---

### Moisture (0-25)

Morels need sustained moisture to initiate fruiting. The ideal is active snowmelt (constant soil moisture from above) or a solid rain event.

#### Precipitation (0-10 pts, 40% of moisture)

From Open-Meteo historical daily data, summed over the last 14 days:

| 14-day precip | Points | % of 25 |
|---------------|--------|---------|
| >1.5 inches | 10 | 40% |
| 0.5-1.5 in | ~6 | 25% |
| 0.1-0.5 in | ~3 | 10% |
| <0.1 in | 0 | 0% |

#### Snowmelt Status (0-12.5 pts, 50% of moisture)

Derived from Open-Meteo hourly `snow_depth` data, comparing the 7-day-ago average to the current average:

| Status | Melt Score | Points | How detected |
|--------|-----------|--------|-------------|
| **ACTIVE MELT** | 1.0 | 12.5 | Past depth >1in, current <50% of past |
| Recently melted | 0.8 | 10 | Past >0.5in, current <0.5in |
| Recent snowfall, tapering | 0.6 | 7.5 | Historical snowfall >2in, last 7d <0.5in |
| Snow-free | 0.4 | 5 | No snow in either period |
| Some snow | 0.3 | 3.8 | Snow present but not trending |
| Snow cover (2-10in) | 0.2 | 2.5 | Moderate pack, not melting fast |
| **Deep snowpack (>10in)** | -0.2 | -2.5 | Still buried — not accessible |

*ACTIVE MELT is the money signal.* It means constant moisture seeping through the burn scar right now. Combined with warming soil temps, this is what triggers fruiting.

#### Soil Moisture (0-2.5 pts, 10% of moisture)

From Open-Meteo hourly `soil_moisture_0_1cm`, averaged over last 7 days:

| Soil moisture (m3/m3) | Points |
|----------------------|--------|
| 0.20 - 0.45 | 2.5 (ideal) |
| >0.45 | 0 (saturated) |
| <0.20 | 0 (too dry) |

---

### Temperature (0-25)

Moisture enables growth; temperature triggers the fruiting window. Specifically, morels respond to **rising (accumulating) soil temperatures** over days to weeks, not a single threshold crossing. A soil reading of 52F for one day is weak signal. Soil climbing 40->45->50->55F over 2-3 weeks is a strong flush trigger.

The temperature score has three sub-components, weighted to emphasize soil temp:

| Sub-factor | Sub-weight | Why |
|------------|-----------|-----|
| **Soil temp (threshold + trend)** | 45% | The actual trigger. Morels won't fruit until soil hits ~47-55F AND is trending upward. |
| **Air temp highs** | 35% | Proxy for solar warming. Drives soil temp over days. |
| **Air temp lows** | 20% | Freeze risk. Hard freezes stall fruiting. |

#### Soil Temperature — Threshold (0-6.75 pts, 27% of temp score)

From Open-Meteo hourly `soil_temperature_0cm`, aggregated to daily max:

| Avg soil temp | Points | Fraction |
|---------------|--------|----------|
| 45-60F | 6.75 | 60% of soil's 45% | Mycelium active, fruiting conditions met |
| 38-65F | 3.4 | 30% of soil's 45% | Getting close or past peak |
| <38F or >65F | 0 | | Dormant or past season |

#### Soil Temperature — Warming Trend (0-4.5 pts, 18% of temp score)

Compares the first half vs second half of the soil temp time series (~7 days each). This captures the **heat accumulation** pattern that research shows is more predictive than rainfall for morel emergence.

| Trend | Points | Signal |
|-------|--------|--------|
| Rising >3F | 4.5 | **WARMING** — strong flush trigger. "soil climbing 40->50F over a week" |
| Rising 1-3F | 2.8 | Moderate warming — conditions improving |
| Stable (+/- 1F) | 1.1 | Flat — not getting worse, not triggering |
| Falling >1F | 0 | Cooling — fruiting stalls or delays |

*This is the key differentiator.* Two burns at the same elevation with the same 52F soil temp will score differently if one is warming and the other is cooling.

#### Air Temperature — Highs (0-8.75 pts, 35% of temp)

| Avg 7-day high | Points | |
|----------------|--------|---|
| 55-75F | 8.75 | Ideal daytime warmth, drives soil warming |
| 45-85F | 4.4 | Acceptable |
| Outside | 0 | |

#### Air Temperature — Lows (0-5 pts, 20% of temp)

| Avg 7-day low | Points | |
|---------------|--------|---|
| 30-50F | 5 | Cool nights = ideal for morels |
| 25-55F | 2.5 | Acceptable |
| Outside | 0 | Hard freezes stall growth; warm nights = wrong season |

---

### Elevation (0-15)

The morel fruiting band moves upslope through the season as snow melts at progressively higher elevations. In the Sierra Nevada, this is roughly 300ft per month:

| Month | Ideal Band (base - top) | Notes |
|-------|------------------------|-------|
| April | 4,500 - 7,000 ft | Lower slopes melting first |
| May | 4,800 - 7,300 ft | Mid-elevation sweet spot |
| June | 5,100 - 7,600 ft | Higher burns coming into season |
| July | 5,400 - 7,900 ft | Late-season high elevation |

Scoring (against max 15 pts):

| Position | Points | % of 15 |
|----------|--------|---------|
| Within ideal band | 15 | 100% |
| Within 500ft of band | 9 | 60% |
| Within 1000ft of band | 4 | 25% |
| >1000ft outside band | 0 | 0% |

*The `elev_base` (4500ft) and `elev_range` (2500ft) are configurable in the morel profile in `config.py`.*

---

### Terrain (0-5 bonus)

Computed by sampling 4 elevation points ~55m from the burn center (N/S/E/W) via USGS EPQS. The differences give us slope angle and aspect direction without needing DEM raster data.

#### Aspect (0-3 pts)

South-facing slopes receive more direct sunlight, melt snow 1-3 weeks earlier than north-facing slopes at the same elevation, and warm soil faster. This is where morels appear first each spring.

| Aspect | Direction | Points | Why |
|--------|-----------|--------|-----|
| 135-225 deg | South | 3 | First to melt, warmest soil. Prime early-season. |
| 90-135 or 225-270 deg | East/West | 1 | Moderate solar exposure. |
| 0-90 or 270-360 deg | North | 0 | Last to melt, coldest. Season starts later here. |

#### Slope (0-2 pts)

| Slope | Points | Why |
|-------|--------|-----|
| 5-25 degrees | 2 | Good drainage prevents waterlogging. Walkable for foraging. |
| <5 degrees (flat) | 1 | Can pool water, but still accessible. |
| >25 degrees (steep) | 0 | Hard to forage safely. Less habitat. |

*Terrain is a bonus (max +5) on top of the base 100. Max theoretical score is 105. In practice it helps differentiate burns with identical weather/fire scores — a south-facing 10-degree slope beats a north-facing flat every time.*

---

### Season Gate

If the current month is outside **April-July**, all factor scores are halved before summing. Morels can fruit outside this window in the Sierra, but it's uncommon. This prevents October runs from showing "EXCELLENT" scores just because a burn has good recency + elevation.

---

### Rating Thresholds

| Score | Rating | Map Marker | Meaning |
|-------|--------|-----------|---------|
| 70+ | EXCELLENT | Purple diamond with score | Go now. Conditions are aligned. |
| 55-69 | GOOD | Small green dot | Worth a trip, may need to search harder. |
| 40-54 | FAIR | Small orange dot | Marginal — check back in a week. |
| <40 | POOR | Small red dot | Not worth the drive. |

### What the score does NOT capture

- **Vegetation type** — We don't know if the burn was in mixed conifer (ideal) or chaparral (poor). LANDFIRE data would help but requires raster processing.
- **Burn severity** — A PFIRS "underburn" tells us the intended type, but not actual severity. dNBR from Sentinel-2 would give post-fire severity maps.
- **Soil type** — Sandy, well-drained soils produce better morels. NRCS Web Soil Survey API could provide this.
- **Access** — Some high-scoring burns may be on private land, behind locked gates, or in wilderness areas with no trail access.
- **Competition** — Popular, accessible burns get picked clean. Remote, hard-to-reach burns may produce less but have less pressure.

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
- Per-mushroom-type scoring (chanterelles, porcini, matsutake) with different candidate generation — mature forest sites, tree association data, not burn sites
- PFIRS auto-refresh without browser cookie
- Static PNG map export for GitHub Pages
- Multi-day forecast scoring (score burns for each of next 7 days)
- Integration with Gaia GPS / CalTopo for field navigation
