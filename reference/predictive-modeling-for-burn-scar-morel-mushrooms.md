# Predictive Modeling for Burn-Scar Morel Mushrooms

## Executive summary

- The strongest directly supported predictors are **time since fire**, **local burn severity/forest-floor combustion**, **spring soil warming**, **recent precipitation/soil moisture**, and **microsite proximity to burned trees with thin residual duff**. Across post-fire studies, the dominant fruiting pulse is usually the **first post-fire season**, with reduced second-year production; morels were absent in one Yosemite plot study where **less than 50% of the ground surface had burned**, and clustered strongly at **less than 3 m**, with spatial signal extending to about **7 m**. 

- The best-supported thermal cue is **soil warmth**, not a single air-temperature cutoff. Published field observations show morel fruiting can begin once soil temperature exceeds about **6.1 °C / 43 °F**, with onset also aligning with roughly **365 to 580 soil degree-days above 0 °C** in one long-term field study; the pre-emergence phase lasts about **3 to 4 weeks**, then expansion can be rapid once conditions are favorable. 

- Moisture modulates whether that thermal signal produces mushrooms. In Missouri, abundance rose with **rain events greater than 10 mm** in the **30 days before fruiting**; in Alaska, **cool, overcast, moist** conditions extended pickable lifespan, while hot, dry weather shortened it, and an unusually wet May was followed by abundant fruiting the next month. 

- Burn severity is not one-dimensional. Several western North American sources indicate peak production in the **moderate “red needle” zone** or where roughly **60% to 80% of duff was consumed**, yet the Yosemite study found strongest occurrence on nearly completely burned ground. A predictive model should therefore separate **canopy/tree mortality**, **surface burn fraction**, **duff consumption**, and **local ash/mineral-soil exposure** rather than collapsing severity to one class. 

- A practical modeling architecture is a **two-stage, multi-scale spatiotemporal model**: first, predict **where first-year burn morels are possible** at 10 to 30 m resolution; second, predict **when and how intensely they fruit** at the plot or transect level using repeated visits, soil sensors, and microsite covariates. This is justified by the observed mix of strong fire-level controls, high zero inflation, and fine-scale clustering. 

## Ecological signal and variable-by-variable evidence

Fire-adapted burn morels are concentrated in western North American conifer-burn systems. A 2017 taxonomic paper states that **five fire-adapted black morel species** had been documented in western North America and that their fruiting appears restricted to **conifer burn sites**, with eastern North American post-fire records much rarer. That means a model should treat **forest type and pre-fire host composition** as primary screening variables, not merely background covariates. 

Vegetation matters biologically as well as structurally. In pure-culture synthesis, Morchella isolates formed ectomycorrhiza-like structures with **Larix occidentalis, Pinus contorta, Pinus ponderosa, and Pseudotsuga menziesii**, but not with *Arbutus menziesii*. Separately, Morchella was detected as an endophyte in cheatgrass, and one study reported increased cheatgrass biomass and fecundity from that association. The safest interpretation is that burn-morel nutritional ecology is flexible, so the model should include **pre-fire tree species**, **canopy condition**, and, where relevant, **post-fire grass invasion/regrowth**. 

Fire alters substrate in ways that plausibly favor morels. A USDA synthesis reports that fire can reduce microbial biomass in the humus layer by roughly **30% to 85%**, sometimes persisting **5 years or more**, and that morels are often most abundant where **60% to 80% of the duff layer** was consumed. The same synthesis notes field reports of heavy fruiting in the **“red needle zone,”** where trees are killed but needles are not fully consumed. Mechanistically, that points to a variable set built around **duff loss**, **tree mortality**, **necromass formation**, and **canopy opening**, not just mapped severity class. 

The strongest microsite evidence comes from post-fire field studies. In the Kootenay study, ascocarps were strongly biased toward **thin post-fire duff** and **proximity to standing burned trunks**, and the bases of ascocarps were consistently just below the **mineral-soil surface**. In the Yosemite study, morels occurred in **17.8%** of 1,119 plots, with a mean standing crop of **1,693 morels/ha**, and occupancy was strongly spatially autocorrelated at **less than 7 m**, especially **less than 3 m**. Those are direct arguments for adding **distance to burned stems**, **distance to prior detections**, **post-fire duff depth**, **surface mineral-soil exposure**, and **local spatial random effects**. 

Thermal timing is best represented as a cumulative process. Published field observations summarized by the USDA report place initial fruiting above about **43 °F / 6.1 °C soil temperature**. The Missouri field study found onset at roughly **365 to 580 soil degree-days above 0 °C**, similar to the **425 to 580** range reported by Buscot, and showed that the day of initiation was inversely related to accumulated spring air and soil warmth. The same literature indicates a **3 to 4 week** pre-emergence phase, followed by **1 day** to reach roughly two-thirds of final size under optimal conditions and another **1 to 10 days** to mature. 

Moisture gates the expression of that thermal signal. In Missouri, abundance rose with rain events over **10 mm** during the **30 days preceding fruiting**. In Alaska, cool overcast weather with moist soils prolonged development; a wet May, about **2 inches** versus a long-term mean of **0.6 inches**, was followed by abundant fruiting a month later. Rain can also be double-edged, stimulating additional fruiting while damaging standing mushrooms and speeding decay. For modeling, this supports **lagged precipitation totals**, **event counts above a threshold**, **vapor pressure deficit**, **surface soil moisture**, and **cloudiness or radiation** as separate predictors. 

Topography mostly controls **timing** and **desiccation risk**, with less direct evidence for a universal directional effect on occurrence. The USDA synthesis notes that in mountainous terrain morels fruit first at **lower elevation** or on **south-facing slopes**, then later at **higher elevation** and on **north-facing slopes**, and that burned soils warm faster than unburned soils because their dark surface absorbs more radiation. In the Sierra Nevada section of that same report, fruiting in burned areas generally starts in early March at roughly **4,000 ft / 1,219 m** in the northern Sierra and **5,000 ft / 1,524 m** in the southern Sierra, then moves upslope; burned riparian forests in eastern drainages can also be productive. 

The effect of **elevation** is therefore strongly regional and interacts with latitude and snowpack. Western Canada reports show production starting at lower elevations and southern latitudes and moving to higher and more northern sites through the season; high-elevation central British Columbia burns produced morels in **June through July**, while near Cranbrook fruiting ran from **early May to early August**, and near Yellowknife the season was reported as **July 1 to July 30**. Gray burn morels are also reported to be more abundant at **higher elevations and northern latitudes** and to fruit later than pink and green burn morels. 

Direct burn-morel evidence for soil type and pH is sparse. The best quantitative ranges come from non-burn Morchella habitat studies, which found morels in **sandy loam to loamy soils**, at **slightly acidic to neutral pH** with one mean at **pH 6.4**, air temperatures of **13 to 27 °C**, soil temperatures of **6 to 26 °C**, and canopy cover averaging about **57%**; another site-based study reported a mean around **pH 7.4** and higher canopy cover. These findings are useful as weak priors, but they should not override direct burn variables because post-fire ash and combustion can transiently shift pH, texture expression, and organic-matter exposure. 

Evidence on **water bodies**, **forest edge**, and **post-fire regrowth** is weaker and more indirect. Productive burned riparian forests are documented in Sierra drainages; a Yellowknife study reported early-season morels in **wet habitats**, later-season fruiting in **transition zones**, and persistent fruiting on **dry ground** by another species. For edge effects, the best direct clue is that morels often occur in **sheltered microsites**, such as along logs or in depressions, where wind and sunlight are reduced. That makes **distance to streams**, **riparian mask**, **distance to forest edge**, **canopy openness**, and **depression or shelter index** reasonable exploratory variables, but currently lower-confidence than burn severity, soil warming, and tree proximity. 

A simple seasonal signal is:

```mermaid
flowchart LR
A[Fire year\nfuel load, host trees, burn pattern] --> B[Post-fire substrate\nresidual duff, ash, tree mortality, canopy opening]
B --> C[Spring forcing\nsnowmelt, soil warming, recent rain]
C --> D[Pre-emergence phase\nabout 3 to 4 weeks]
D --> E[Emergence\nsoil temp above about 6 C and degree-day target reached]
E --> F[Fruiting window\nvery short in hot/dry conditions, longer in cool/moist conditions]
```

This sequence is directly supported for temperature, growth timing, and seasonal compression or extension; the uncertainty is greatest in the substrate-to-emergence mechanism, not in the existence of the overall sequence. 

### Temperature and moisture windows most useful for modeling

| Signal | Quantitative guidance | Modeling implication | Evidence |
|---|---|---|---|
| Soil temperature trigger | Fruiting begins once soil exceeds about **6.1 °C / 43 °F** | Use 5 cm and 10 cm soil temperature, plus threshold-crossing date |  |
| Cumulative warmth | Onset around **365 to 580 soil degree-days above 0 °C** in Missouri; similar to **425 to 580** reported earlier | Use cumulative soil GDD/HDD rather than one-day temperature |  |
| Primordia lag | Pre-emergence phase about **3 to 4 weeks** | Include lagged temperature and moisture windows, not same-day weather only |  |
| Rain pulse | Abundance rises with **rain events greater than 10 mm** in prior **30 days** | Count threshold events and rolling rain totals at 7, 14, 30 d |  |
| Window compression | Best fruiting years in one study had seasons only **6 to 7 days** | Revisit sites weekly or better; single-visit absence is weak evidence |  |
| Window extension | Overall season about **2 to 6 weeks** in Alaska; cool moist weather extends lifespan | Add interaction terms for soil moisture × radiation or VPD |  |

## Comparison of major studies

| Study system | What was measured | Most useful quantitative findings | What it contributes to a model |
|---|---|---|---|
| entity["country","France","european country"], forest morels | Soil temperature and development | Fruiting above about **43 °F / 6.1 °C**; maturation rate linked to degree-days | Best direct basis for **soil-temperature thresholds** and growth lag  |
| entity["state","Missouri","US state"], 5-year woodland study | Air/soil temperature, rain, woody stems | Onset tied to **365 to 580 soil degree-days**; abundance higher after rain events **greater than 10 mm**; biggest years had **6 to 7 day** seasons | Strongest source for **phenology**, **rain lag**, and **tree proximity** logic, though not fire-specific  |
| northeastern entity["state","Oregon","US state"] burned vs healthy/insect stands | Stand-level productivity | First-year burned stands yielded about **127 to 1,761 morels/acre**, while healthy and insect-damaged stands were much lower; burn morels did not fruit in nonburned stands that year | Good baseline for **time-since-disturbance** and **habitat contrast**  |
| entity["point_of_interest","Kootenay National Park","British Columbia, Canada"] and nearby burns | Duff depth, trunk proximity, year effects | Great majority of ascocarps in first post-fire summer; biased to **thin duff** and **near standing burned trunks**; fruiting bases just below mineral soil | Strongest direct evidence for **microsite covariates**  |
| interior entity["state","Alaska","US state"] | Productivity, weather, season, burn context | Fruit best near trees in **moderate to severe** burns; main season **late June to mid-July**, but overall **2 to 6 weeks**; cool moist/cloudy weather prolongs fruiting | Useful for **season length**, **tree proximity**, and **weather effects on persistence**  |
| entity["point_of_interest","Yosemite National Park","California, US"] mixed-conifer burn | Plot occupancy and spatial autocorrelation | **595 morels** in **1,119 plots**; **17.8%** occupancy; **1,693 morels/ha**; no morels where **less than 50%** of the surface burned; clustering strongest at **less than 3 m** and present to **7 m** | Best direct evidence for **zero inflation**, **severity thresholding**, and **spatial terms**  |
| northern entity["country","Israel","middle eastern country"] burn | Post-fire forestry microsites | Stump clearing, **bulldozer compaction**, and **chopped wood cover** created preferred fruiting microsites; almost none on unburned soil | Supports **anthropogenic microsite disturbance** variables where relevant  |
| entity["point_of_interest","Great Smoky Mountains National Park","Tennessee, US"] post-fire survey | Taxonomic identification | Post-fire morel discovered throughout a **severely burned area** after a 2016 fire; confirms eastern post-fire fruiting can occur though it is rare | Warning against assuming western-only models are globally transferable  |

## Modeling blueprint

The best design is a **nested model** with separate answers to two questions: **where can burn morels occur this week**, and **how many will fruit if they occur**. The Yosemite study shows why. Plot occupancy was only **17.8%**, yet nonzero plots showed tight spatial clustering. That favors a **two-part hurdle model** or **zero-inflated negative binomial** with **fire-level random effects** and **spatial terms**, rather than one global regression on counts. 

A practical workflow is: first, build a coarse screening model for **first-year conifer burns** using severity, elevation, aspect, burn age, riparian context, pre-fire vegetation, and weather history; second, within the shortlisted cells, model **weekly fruiting probability** from soil warming, recent rain, snowmelt timing, radiation, and surface moisture; third, estimate **local abundance** from microsite variables such as duff depth, ash/mineral-soil exposure, burned-tree proximity, and shelter. This mirrors the empirical signal in the published studies, where fire and substrate set the stage, then temperature and moisture gate emergence. 

### Feature list with variable types and suggested transformations

| Predictor | Scale | Suggested type or transform | Expected role | Evidence strength |
|---|---|---|---|---|
| Time since fire | fire, pixel | numeric; spline or bins for **year 1, year 2, year 3+** | Strongest first-year pulse, usually reduced after | Direct  |
| Burn severity | pixel, plot | continuous **dNBR/RdNBR** plus ordinal thematic class | Core filter, but nonlinear | Direct  |
| Surface burn fraction | plot | proportion 0 to 1 | Useful local severity term; hard threshold possible near **0.5** in one study | Direct  |
| Duff consumption or residual duff depth | plot | continuous; consider piecewise threshold around thin duff | Very strong microsite predictor | Direct  |
| Distance to burned tree base or standing burned trunk | plot | log1p distance | Higher probability close to trunks or tree bases | Direct  |
| Pre-fire host composition | pixel, stand | categorical type; tree basal area fractions | Restricts burn morels to suitable conifer systems | Direct to indirect  |
| Elevation | pixel | continuous; interact with latitude and snowpack | Mostly shifts season timing and species mix | Direct  |
| Aspect | pixel | sine and cosine of aspect; or heat-load index | South/low earlier, north/high later | Direct but mostly for timing  |
| Slope | pixel | continuous or spline | Proxy for drainage, insolation, snow persistence | Indirect  |
| Soil temperature at 5 and 10 cm | pixel or sensor | daily mean, threshold date, 7 d mean | Better than air temperature for onset | Direct  |
| Cumulative soil degree-days | week | cumulative above **0 °C**, optionally above **6 °C** | Strong onset feature | Direct  |
| Air temperature | weather station, grid | min, max, mean, 7 to 14 d trend, frost counts | Secondary to soil temp, still useful | Direct to indirect  |
| Precipitation | week | rolling totals at **7, 14, 30 d**; count of events **greater than 10 mm** | Moisture trigger and support | Direct  |
| Soil moisture | pixel or sensor | volumetric water content at 5 to 20 cm; anomalies | Supports emergence and persistence | Direct to indirect  |
| Snowmelt timing | pixel | day-of-year of snow disappearance | Major timing control at elevation | Indirect but strong mechanistic proxy  |
| Distance to stream or riparian zone | pixel | log1p distance; binary riparian mask | Explains some productive wet drainages and seasonal succession | Indirect  |
| Soil texture, pH, organic matter | pixel | continuous; possibly depth-specific | Weak prior, likely region-specific | Indirect  |
| Canopy opening or post-fire green-up | pixel | NDVI, EVI, canopy-cover delta | Proxy for shade, desiccation, regrowth | Indirect  |
| Fuel load and fuel moisture | fire, station | dead-fuel moisture, canopy cover, biomass proxies | Helps explain severity and duff outcome | Indirect to direct  |
| Microsite shelter | plot | depression index, log wind shelter, charred-log proximity | Morels favor sheltered positions | Direct but understudied  |

## Data sources and field sampling

### Recommended data sources

| Variable family | Preferred source | Typical resolution and scope | Why it fits this problem |
|---|---|---|---|
| Fire perimeter and burn severity | entity["organization","U.S. Geological Survey","federal science agency"] and MTBS, with Landsat severity products | MTBS is **30 m**, large fires in the U.S. from **1984 onward**; Landsat indices are also **30 m** | Best official source for **time since fire**, **dNBR/RdNBR**, severity class, and perimeter geometry  |
| Elevation, slope, aspect | USGS 3DEP in the U.S.; Copernicus DEM globally | 3DEP varies; Copernicus GLO-30 and GLO-90 are global | Core for elevation, heat load, drainage, and shelter derivation  |
| Daily weather | Daymet from entity["organization","Oak Ridge National Laboratory","national lab Tennessee"]; PRISM at entity["organization","Oregon State University","Corvallis university"] for U.S. normals and daily data | Daymet **1 km** daily; PRISM **800 m and 4 km** daily and normals | Good coverage for temperature, precipitation, vapor pressure, radiation, snow water equivalent, and climatology  |
| Soil moisture and soil temperature | entity["organization","NOAA","US weather agency"] USCRN; entity["organization","USDA Natural Resources Conservation Service","federal soils agency"] SCAN; ERA5-Land; SMAP from entity["organization","NASA","US space agency"] | USCRN and SCAN are stations; ERA5-Land about **9 km** hourly; SMAP top **5 cm** every **2 to 3 days** | Necessary for the most important short-term forcing variables; in-situ data are best for calibration, gridded data for mapping  |
| Vegetation and canopy cover | LANDFIRE EVT and EVC; FIA for tree composition; NLCD for land cover | LANDFIRE and NLCD are **30 m**; FIA is plot-based | Best official combination for host composition, canopy cover, forest type, and pre-fire fuels proxies  |
| Water bodies and hydrography | National Hydrography Dataset in the U.S.; HydroSHEDS globally | Vector hydrography and gridded hydro layers | For distance-to-stream and riparian masks  |
| Soils | gSSURGO and SSURGO in the U.S.; SoilGrids globally | gSSURGO is gridded national raster; SoilGrids **250 m** with depth layers | Supplies pH, texture, organic carbon, CEC, and depth-specific soil attributes  |
| Snow timing and seasonal persistence | MODIS or VIIRS snow products | **500 m** to coarser daily and composite products | Valuable in montane systems where fruiting tracks snowline retreat |  |
| Fuel moisture and station weather | RAWS and FEMS | Hourly station data and mapped fuel-moisture products | Bridges fire-weather context and short-term desiccation risk |  |

### Recommended sampling design

Use **stratified repeated-visit field sampling**, not opportunistic presence-only data. A good template is the Yosemite design of many small georeferenced plots, because it yielded unbiased abundance and clustering estimates. For each fire, stratify by **severity**, **elevation band**, **aspect**, **riparian distance**, and **forest type**. Within each stratum, place transects and **circular plots near 3.14 m²** or fixed-width belt transects, and revisit every **5 to 7 days** through the expected fruiting period. 

At each plot, record both **presence and true absence** plus microsite covariates: residual duff depth, ash depth or cover, percent mineral-soil exposure, distance to nearest burned bole and nearest tree base, canopy openness, downed charred wood, soil disturbance, topographic shelter, and visible post-fire regrowth. Install low-cost temperature and moisture sensors at representative plots, ideally at **5 and 10 cm** depths, because these depths align with available climate-network products and the published thermal literature. 

For species resolution, voucher a subset of collections and barcode them. Many abundance studies worked only at the genus level, but the literature shows species turnover by region, habitat moisture, and season. Without molecular validation, a model may unintentionally learn pooled responses from multiple burn-morel taxa. 

Validation should be **leave-one-fire-out**, then **leave-one-region-out** if enough fires are available. Spatial blocking is mandatory because morels are clustered at a few meters, and random train-test splits within a fire will overstate performance. The right scoring outputs are calibration and search-efficiency metrics, for example **top-decile hit rate**, **occupied-plot recall**, and **distance saved per detected cluster**, not only AUC. 

## Uncertainty, conflicting findings, and gaps

The main conflict is the meaning of “best severity.” Several western sources favor **moderate burns** or **moderate duff consumption**, but the Yosemite study found strongest occurrence on nearly fully burned surface plots and none below **50%** surface burn. Those findings are not actually incompatible if one study is capturing **tree mortality with partial surface retention** and another is capturing **surface burn fraction at plot scale**. A serious model should therefore include **multiple severity measurements at multiple scales**. 

The next major gap is that several variables in forager lore remain weakly quantified in the literature: **forest edge distance**, **distance to water**, **ash depth**, **charred wood amount**, **post-fire regrowth**, and **soil pH shifts in actual burn-morel microsites**. These belong in field protocols now, even if they begin as exploratory variables, because the current literature is too sparse to exclude them confidently. 

A third uncertainty is trophic mode. Morels show evidence of mycorrhiza-like relations with conifers, possible endophytic behavior in grasses, and strong responses to disturbance and dead organic matter. That flexibility likely explains why host, fuel, and substrate variables all matter, but it also means models trained in one forest type may transfer poorly to another if the dominant morel taxon or nutritional mode differs. 

The final gap is sample size. Even in 2026, the peer-reviewed literature still contains only a small number of unbiased post-fire abundance studies. That means a predictive system should be viewed as **regionally calibrated and updateable**, with posterior updating after each field season, rather than as a finished universal model. 

## References

- [First report of the post-fire morel *Morchella exuberans* in eastern North America (Mycologia 2017)](https://miller-mycology-lab.inhs.illinois.edu/files/2020/04/First-report-of-the-post-fire-morel-Morchella-exuberans-in-eastern-North-America-Mycologia-2017.pdf)
- [USDA PNW General Technical Report 710 — Morel mushrooms and wildfire](https://www.fs.usda.gov/pnw/pubs/pnw_gtr710.pdf)
- [Dahlstrom et al. 2000 — Post-fire morel ecology (Mycological Research)](https://www.sciencedirect.com/science/article/abs/pii/S0953756207000184)
- [Post-fire morel mushroom abundance, spatial structure, and harvest sustainability](https://www.nwfirescience.org/biblio/post-fire-morel-morchella-mushroom-abundance-spatial-structure-and-harvest-sustainability)
- [Buscot 1993 — Soil temperature and morel development (Mycological Research)](https://link.springer.com/content/pdf/10.1007/PL00009992.pdf)
- [Greene et al. 2010 — Morel and pixie cup emergence vs. intensity of forest floor combustion](https://www.researchgate.net/publication/45279823_Emergence_of_morel_Morchella_and_pixie_cup_Geopyxis_carbonaria_ascocarps_in_response_to_the_intensity_of_forest_floor_combustion_du)
- [Ecological characterization of Morel habitats — multivariate comparison from three forest types](https://www.researchgate.net/publication/346710087_Ecological_characterization_of_Morel_Morchella_spp_habitats_A_multivariate_comparison_from_three_forest_types_of_district_Swat_Pakistan)
- [Alaska morel mushroom harvesting guide (UAF AFES)](https://www.uaf.edu/afes/publications/database/miscellaneous-publications/files/pdfs/MP_2005-07.pdf)
- [Larson et al. 2016 — Post-fire morel predictors (Forest Ecology and Management)](https://www.sciencedirect.com/science/article/pii/S0378112716303413)
- [USGS 3D Elevation Program (3DEP)](https://www.usgs.gov/3d-elevation-program)
- [MODIS Snow Cover Products (MOD10)](https://modis.gsfc.nasa.gov/data/dataprod/mod10.php)
- [USDA PNW Research Note 546 — Post-fire morel productivity in Oregon](https://www.fs.usda.gov/pnw/pubs/pnw_rn546.pdf)
- [Baynes et al. 2012 — Morchella as conifer endophyte (Fungal Ecology)](https://www.sciencedirect.com/science/article/abs/pii/S1754504813000275)
- [Monitoring Trends in Burn Severity (MTBS)](https://www.mtbs.gov/)
- [Landsat Normalized Difference Vegetation Index (NDVI)](https://www.usgs.gov/landsat-missions/landsat-normalized-difference-vegetation-index)
- [NIFC Interagency Remote Automatic Weather Stations (RAWS)](https://data-nifc.opendata.arcgis.com/datasets/nifc%3A%3Apublic-view-interagency-remote-automatic-weather-stations-raws/about)
- [Daymet Daily Surface Weather Data (ORNL)](https://daymet.ornl.gov/)
- [NOAA U.S. Climate Reference Network (USCRN)](https://www.ncei.noaa.gov/products/land-based-station/us-climate-reference-network)
- [LANDFIRE Existing Vegetation Type (EVT)](https://landfire.gov/vegetation/evt)
- [USGS National Hydrography Dataset (NHD)](https://www.usgs.gov/national-hydrography/national-hydrography-dataset)
- [NRCS Gridded Soil Survey Geographic (gSSURGO) Database](https://www.nrcs.usda.gov/resources/data-and-reports/gridded-soil-survey-geographic-gssurgo-database)
