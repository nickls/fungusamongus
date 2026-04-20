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

Each burn site is scored 0-100 across six factors. See **[ALGO.md](ALGO.md)** for full scoring methodology, factor breakdowns, point tables, and research basis.

**Quick summary:**

| Factor | Max | Role |
|--------|-----|------|
| Soil Temp Threshold | 25 | Hard gate — cold soil crushes entire score |
| Warming Trend | 25 | Is soil rising? The emergence trigger |
| Recent Moisture | 20 | Rain/snowmelt drives yield |
| Burn Quality | 15 | Recency, type, size |
| Sun / Aspect | 10 | Slope, aspect, elevation band |
| Air Temperature | 5 | Proxy only |

Rating: 80+ = EXCELLENT (purple diamond), 70-79 = GOOD (green diamond), 50-69 = FAIR (dot), <50 = hidden.

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
