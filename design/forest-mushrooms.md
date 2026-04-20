# Design: Forest Mushroom Support (Matsutake, Porcini, Chanterelle)

## Context

Adding non-fire-associated mushroom types to the foraging tool. Morels use burn sites as candidates; these three species need mature forest with specific tree associations — completely different candidate generation. All three share the same LANDFIRE-based infrastructure but differ in target vegetation, season, and environmental triggers.

Key discovery: **LANDFIRE has a free REST API** (`lfps.usgs.gov/arcgis/rest/services/.../ImageServer`) with `identify` (single point) and `getSamples` (batch) endpoints. No auth, no raster download. This gives us vegetation type (EVT), tree height (EVH), and canopy cover (EVC) at any lat/lon — exactly what we need for forest maturity scoring.

## Approach

Build matsutake as a second candidate pipeline alongside morels. Morels keep the burn-location approach. Matsutake generates a grid of candidate points, filters by elevation + LANDFIRE vegetation data, then scores on weather/terrain/forest maturity.

Mapping already supports `results_by_type` dict — zero changes needed to render matsutake as a separate toggle layer.

## Implementation Steps

### Step 1: `utils/landfire.py` (new file)

Query LANDFIRE ImageServer for vegetation data at any point.

- `get_vegetation(lat, lon)` -> `{evt, evh, evc}` — single-point query via `identify`
- `get_vegetation_batch(points)` -> list of vegetation dicts — batch query via `getSamples` (chunks of 50)
- `score_forest_maturity(evt, evh, evc, target_evt)` -> 0.0-1.0 score
- `EVT_MATSUTAKE` dict mapping EVT codes -> quality scores:
  - 7032 Red Fir, 7058 Lodgepole Pine, 7031 Jeffrey Pine -> 1.0
  - 7027 Dry Mixed Conifer, 7033 Mesic Mixed Conifer -> 0.7
- Cache with 720h TTL (vegetation is static)
- Endpoints:
  - EVT: `https://lfps.usgs.gov/arcgis/rest/services/Landfire_LF2022/LF2022_EVT_CONUS/ImageServer`
  - EVH: `https://lfps.usgs.gov/arcgis/rest/services/Landfire_LF2022/LF2022_EVH_CONUS/ImageServer`
  - EVC: `https://lfps.usgs.gov/arcgis/rest/services/Landfire_LF2022/LF2022_EVC_CONUS/ImageServer`

### Step 2: `candidates.py` (new file)

Pluggable candidate generation.

- `generate_burn_candidates(center, radius_km)` — extract existing logic from `morel_finder.py` (`gather_fire_data` + `dedupe_burns`)
- `generate_grid_candidates(center, radius_km, profile)` — for matsutake:
  1. Generate hex grid at 2km spacing within radius
  2. Filter by elevation (USGS, cached) — keep 5000-8000ft
  3. Query LANDFIRE batch — keep points where EVT is target forest AND tree height >10m AND canopy >40%
  4. Return candidate dicts: `{name, lat, lon, source: "grid", vegetation: {evt, evh, evc, forest_score}}`
  5. Cache the filtered grid as `cache/grid_matsutake.json` (subsequent runs skip LANDFIRE entirely)

~120km radius at 2km step = ~11k raw points -> ~3k after elevation filter -> ~500-1000 after LANDFIRE filter. First run slow (LANDFIRE queries), cached runs instant.

### Step 3: Rework `scoring.py`

Add forest-type scoring path alongside existing morel path. Dispatch based on weight names in profile.

- If `"soil_threshold"` in weights -> morel path (existing, untouched)
- If `"forest_maturity"` in weights -> forest path (new):
  - **temperature (20)**: Same soil gate logic but with matsutake thresholds (40-55F). Key difference: matsutake prefer **cooling** trends (first fall cold snap), so invert the warming trend logic.
  - **moisture (30)**: "dry-then-wet" pattern. Dry summer followed by first soaking rain = trigger. Score recent precip events heavily.
  - **elevation (20)**: Band check using config values (5000-8000ft, shifts downhill in fall at -200ft/month)
  - **forest_maturity (30)**: Direct from `vegetation.forest_score` in the candidate dict. EVT match + tree height + canopy cover.

### Step 4: Flesh out matsutake profile in `config.py`

Add missing params: `candidate_method: "grid"`, `grid_step_km: 2.0`, `prefer_cooling: True`, `target_evt` dict, `min_tree_height_m: 10`, `min_canopy_cover_pct: 40`, `precip_thresholds`, `soil_moisture_ideal`, full scoring params.

### Step 5: Update `morel_finder.py`

Add `--types morel,matsutake` CLI arg (default: morel only). For each type:
- Read `candidate_method` from profile
- Call appropriate generator from `candidates.py`
- Score each candidate
- Collect into `results_by_type` dict

Mapping and chart code already handles multi-type — just pass the dict.

### Step 6: Minor `mapping.py` updates

- `print_report`: handle matsutake detail keys (vegetation_type, tree_height, canopy_cover instead of burn_type, burn_acres)
- `build_chart`: use weight names from profile for bar segments
- Heatmap for grid candidates: use fixed 2km radius (no acreage to expand)

## Species Comparison

| Aspect | Morel | Matsutake | Porcini | Chanterelle |
|--------|-------|-----------|---------|-------------|
| Candidate source | Burn sites | Grid + LANDFIRE | Grid + LANDFIRE | Grid + LANDFIRE |
| Tree association | Any (burned) | Pine/fir, sandy soil | Spruce/fir/pine | Oak, tanoak, mixed conifer |
| Fire association | **Required** (recent burn) | Avoided | Avoided | Avoided |
| Temp trigger | WARMING soil into 48-58F | COOLING soil into 40-55F | Warm soil 50-65F after rain | Warm soil 55-70F, sustained |
| Moisture trigger | Snowmelt / spring rain | First fall rains after dry summer | Rain events + warm days | Sustained moisture over weeks |
| Season | Apr-Jul | Sep-Nov | Jun-Oct | Jul-Oct |
| Elevation trend | Moves uphill through season | Moves downhill through season | Stable mid-elevation | Stable, lower elevations |
| Fruiting pattern | Flush (days) | Flush (days) | Extended (weeks) | Extended (weeks) |
| Priority | **P0** (built) | P2 (fall) | **P1** (in season) | P3 (fall) |

---

## Matsutake (Tricholoma murrillianum) — P2 (Sep-Nov)

### Scoring Model (total: 100)

| Factor | Max | What it measures |
|--------|-----|-----------------|
| **Forest Maturity** | 30 | EVT match (pine/fir), tree height >10m, canopy >40% |
| **Moisture** | 30 | "Dry-then-wet" pattern: dry summer + first soaking fall rain |
| **Temperature** | 20 | Soil 40-55F, COOLING trend (invert morel logic), cold nights |
| **Elevation** | 20 | 5000-8000ft, shifts downhill in fall (-200ft/month) |

### Target EVT Codes (Tahoe area)

| EVT Code | Name | Quality | Why |
|----------|------|---------|-----|
| 7032 | Mediterranean California Red Fir Forest | 1.0 | Classic matsutake habitat, high elevation |
| 7058 | Sierra Nevada Subalpine Lodgepole Pine Forest | 1.0 | Pine association, sandy substrate |
| 7031 | California Montane Jeffrey Pine-(Ponderosa Pine) Woodland | 1.0 | Open pine, well-drained soil |
| 7027 | Mediterranean California Dry-Mesic Mixed Conifer | 0.7 | Some pine component |
| 7033 | Mediterranean California Mesic Mixed Conifer | 0.7 | Fir-heavy, less ideal |
| 7050 | Rocky Mountain Lodgepole Pine Forest | 0.7 | Lodgepole pine |

### Key Biology

- Mycorrhizal with pine and fir — needs living root systems in undisturbed forest
- Sandy, well-drained soils strongly preferred (future: NRCS soil data)
- First fall rains after a dry summer trigger massive flushes
- Cooling soil temps (first cold snap) are the timing trigger — opposite of morel
- Returns to same spots year after year ("shiros" — underground mycelial mats)
- Competitive foraging pressure is high — popular, valuable mushroom

### Moisture Model (differs from morel)

Matsutake moisture is "dry-then-wet": a dry summer followed by the first soaking rain. This is different from morels which want sustained moisture.

- Score recent precip events (last 7 days) heavily
- Bonus if preceded by dry period (check 14-30 day historical — low precip followed by spike)
- Soil moisture in 0.15-0.40 m3/m3 range (slightly drier than morel preference)
- Snowfall = season is over (penalize)

---

## King Bolete / Porcini (Boletus edulis/rex-veris) — P1 (Jun-Oct, spring kings May-Jun)

### Scoring Model (total: 100)

| Factor | Max | What it measures |
|--------|-----|-----------------|
| **Forest Maturity** | 25 | EVT match (spruce/fir/pine), tree height >10m, canopy >40% |
| **Moisture** | 30 | Rain events followed by warm days — the "summer rain + sun" pattern |
| **Temperature** | 25 | Soil 50-65F, warm but not hot. Steady warmth, not extreme swings. |
| **Elevation** | 20 | 5000-8000ft, stable through season |

### Target EVT Codes (Tahoe area)

| EVT Code | Name | Quality | Why |
|----------|------|---------|-----|
| 7033 | Mediterranean California Mesic Mixed Conifer | 1.0 | Classic porcini habitat — fir/spruce mix |
| 7032 | Mediterranean California Red Fir Forest | 1.0 | High-elevation fir, excellent |
| 7027 | Mediterranean California Dry-Mesic Mixed Conifer | 0.8 | Mixed conifer, good |
| 7058 | Sierra Nevada Subalpine Lodgepole Pine Forest | 0.7 | Pine association works |
| 7050 | Rocky Mountain Lodgepole Pine Forest | 0.7 | Lodgepole |
| 7031 | California Montane Jeffrey Pine Woodland | 0.5 | Drier, less ideal |

### Key Biology

- Mycorrhizal with spruce, fir, and pine — broadly associated with conifers
- Two species in Sierra: B. rex-veris (spring king, May-Jun) and B. edulis (summer-fall, Jul-Oct)
- Spring kings fruit at snowmelt edge — similar timing signal to morels but different habitat
- Summer/fall porcini need rain events followed by warm sunny days
- Fruit over extended period (weeks), not a single flush
- Found in same forests year after year — mycelial networks are perennial
- Less specific about soil type than matsutake — not sandy-soil dependent

### Moisture Model

Porcini want "rain then sun" — a soaking rain event (>0.5in) followed by 2-3 warm dry days. This triggers fruiting.

- Score recent rain events (not just total precip — look for spikes)
- Bonus if followed by warm dry forecast
- Extended dry periods = bad (unlike matsutake which benefits from prior dry)
- Snowmelt edge is relevant for spring kings (B. rex-veris) — similar to morel snowmelt signal

### Note on Spring Kings

B. rex-veris fruits May-June at snowmelt edge, often in the same conditions where morels are found (but not on burns — in undisturbed adjacent forest). Could share the morel weather scoring with different candidate generation (LANDFIRE forest near but not on burns). This is a unique hybrid — fire-adjacent but not fire-dependent.

---

## Chanterelle (Cantharellus formosus/cibarius) — P3 (Jul-Oct)

### Scoring Model (total: 100)

| Factor | Max | What it measures |
|--------|-----|-----------------|
| **Forest Maturity** | 30 | EVT match (oak/tanoak/mixed hardwood-conifer), old growth preferred |
| **Moisture** | 35 | Sustained moisture over weeks — not a single event but a wet pattern |
| **Temperature** | 20 | Warm soil 55-70F, warm humid conditions |
| **Elevation** | 15 | 3000-6000ft in Sierra, lower than matsutake/porcini |

### Target EVT Codes (Tahoe area)

| EVT Code | Name | Quality | Why |
|----------|------|---------|-----|
| 7029 | California Montane Hardwood-Conifer | 1.0 | Oak + conifer mix, ideal |
| 7019 | California Montane Hardwood | 1.0 | Hardwood dominant, tanoak/black oak |
| 7033 | Mediterranean California Mesic Mixed Conifer | 0.8 | Mesic = moist, good habitat |
| 7027 | Mediterranean California Dry-Mesic Mixed Conifer | 0.5 | Drier, less ideal |
| 7032 | Mediterranean California Red Fir Forest | 0.3 | Too high/cold usually |

### Key Biology

- Mycorrhizal with oaks (tanoak, black oak, live oak) and Douglas fir
- Strong preference for **old growth or mature second growth** — canopy closure matters more than for other species
- Need **sustained moisture over weeks**, not a single rain event — the "rainy season" mushroom
- Warm, humid microclimate under closed canopy
- Lower elevation than matsutake/porcini in the Sierra — foothills to mid-elevation
- Fruit over extended periods (weeks to months) when conditions stay wet
- Often found on moss-covered slopes with deep duff layer

### Moisture Model

Chanterelles need sustained, multi-week moisture — they're not triggered by a single rain event. The scoring model should look at cumulative precipitation over 21-30 days, not just 14 days.

- Extended wet period (>3 inches over 30 days) = high score
- Soil moisture sustained above 0.25 m3/m3 for multiple weeks
- Humidity matters — closed canopy traps moisture (proxy: EVC >60%)
- Single rain event after dry spell = low score (unlike matsutake which loves this)

### Tahoe Area Limitation

Chanterelles are more commonly found in the western Sierra foothills (Nevada City, Georgetown, Foresthill) and coastal ranges where oak/tanoak is dominant. The Truckee/Tahoe core area is too high and too conifer-dominant for prime chanterelle habitat. The search radius would need to extend further west to capture the best chanterelle zones.

---

## Shared Infrastructure

All three species use the same LANDFIRE + grid pipeline:

1. `utils/landfire.py` — same API, different EVT code target dicts per species
2. `candidates.py` — same `generate_grid_candidates()`, parameterized by profile (EVT targets, elevation band, canopy thresholds)
3. `scoring.py` — same forest-type scoring path, dispatched by weight names in profile
4. `config.py` — each species has its own profile with specific params
5. `mapping.py` — already supports multi-type via `results_by_type` dict

Adding porcini or chanterelle after matsutake is mostly config work:
1. Define EVT target codes
2. Set temperature/moisture/elevation params
3. Adjust the moisture model (rain-then-sun vs dry-then-wet vs sustained-wet)
4. Run

The scoring engine handles the differences through the profile params. No new code paths needed beyond what matsutake requires.

## Files Modified/Created

| File | Action |
|------|--------|
| `utils/landfire.py` | **New** — LANDFIRE API queries |
| `candidates.py` | **New** — pluggable candidate generation |
| `scoring.py` | **Modify** — add forest-type scoring path |
| `config.py` | **Modify** — flesh out matsutake profile |
| `morel_finder.py` | **Modify** — multi-type orchestrator |
| `mapping.py` | **Minor** — report/chart weight name handling |

## Verification

1. `python -c "from utils.landfire import get_vegetation; print(get_vegetation(39.328, -120.183))"` — should return EVT/EVH/EVC dict for Truckee
2. `python morel_finder.py --types morel` — identical output to current (regression check)
3. `python morel_finder.py --types matsutake` — grid candidates, scored, map layer (low scores in April due to season gate)
4. `python morel_finder.py --types morel,matsutake` — combined map with both layers togglable
5. Second run should be fast (LANDFIRE + elevation cached)

## Risks

- `lfps.usgs.gov` may not be in sandbox allowlist — user runs locally so not a blocker
- LANDFIRE API could be slow/down — graceful degradation: skip forest_maturity, score on remaining factors
- ~500 weather API calls for grid candidates on first run — mitigated by ThreadPoolExecutor + caching
- No ground truth for matsutake locations — model is "habitat suitability", not "mushrooms are here"

## Known Scoring Limitations

### Aspect: single-point sampling on multi-acre burns

**Problem:** We sample one centroid point for aspect. A 71-acre burn (~500m across) has south slopes, north slopes, ridges, and ravines. The centroid might be east-facing while the best morel habitat is on the south-facing edge 200m away. Scoring "6/10 sun_aspect" for a burn that clearly contains south-facing terrain is wrong.

**Fix — multi-point sampling:**
- For burns with polygon geometry (NIFC, Tahoe Fuels Tx): sample 5-9 points across the polygon (centroid + boundary ring). Take the **best** aspect, not the average. A burn with ANY south-facing terrain should get full credit.
- For PFIRS point burns (no polygon): sample a small grid around the center (8 points at ~100m spacing in a ring). Report the best aspect found.
- Store both `aspect_best` and `aspect_centroid` in details so the user can see both.

### Aspect: static seasonal value

**Problem:** South-facing = 5pts always. But the value of south-facing changes through the season:
- **Early spring (April):** South-facing is huge — melts 2-3 weeks before north. S=5, N=0 is correct.
- **Late spring (May-Jun):** South-facing has already melted and may be drying out. North-facing just melted and is moist. The gap should narrow.
- **Mid-summer (Jul):** South can be too hot/dry. North-facing at the same elevation is now the moister, cooler option.

**Fix — month-adjusted aspect scoring:**

| Month | South | East/West | North | Rationale |
|-------|-------|-----------|-------|-----------|
| April | 5 | 2 | 0 | South melts first, huge advantage |
| May | 4 | 3 | 1 | Gap narrowing, N starting to melt |
| June | 3 | 3 | 2 | South drying, N freshly melted + moist |
| July | 2 | 3 | 3 | South too dry, N is the moist option |

Add `aspect_month_weights` to the morel profile in `config.py`. The scoring engine reads the current month and applies the corresponding row.

This also applies to forest mushroom types but with different patterns (matsutake in fall: north-facing holds moisture longer, which is good).

## Future Enhancements

- **NRCS soil type data** — sandy = strong matsutake indicator, well-drained = porcini, deep duff = chanterelle. USDA Web Soil Survey API.
- **Adaptive grid refinement** — coarse 2km pass -> fine 500m pass around top clusters
- **Reverse geocoding** — name grid points by nearest feature ("Pole Creek Ridge" not "Grid 39.28/-120.30")
- **Spring king detection** — B. rex-veris hybrid model: LANDFIRE forest candidates near (but not on) active morel burn sites, scored with morel snowmelt timing
- **Chanterelle western extension** — extend search radius west to Nevada City / Georgetown foothills where oak/tanoak dominates
- **Multi-species "best day" view** — in the SPA (see `design/predictive-mode-and-spa.md`), show which species are in season and scoring well on any given day
