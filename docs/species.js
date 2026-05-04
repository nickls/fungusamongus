// Per-species UI configuration. Single source of truth for what the SPA
// shows and how, indexed by mushroom_type. Loaded before app.js / detail.js.

const SUPPORTED_SPECIES = ["morel", "porcini"];

// Filter definitions used by sidebar sliders. Each species picks which
// ones apply via SPECIES[type].filters.
const FILTER_LIBRARY = {
  potential:        { key: "potential",        label: "Min Potential",     max: 100, default: 0, color: "#53a8b6", tip: "Site quality — vegetation, elevation, aspect, burn details." },
  readiness:        { key: "readiness",        label: "Min Readiness",     max: 100, default: 0, color: "#e94560", tip: "How close to fruiting — soil temp, moisture, grow days." },
  burn_age_max:     { key: "burn_age_max",     label: "Max Burn Age (mo)", max: 36,  default: 18, color: "#e67e22", tip: "Hide burns older than N months. 36 = no limit.", mode: "max", source: "burn_age_months" },
  soil_threshold:   { key: "soil_threshold",   label: "Min Soil Temp",     max: 25,  default: 0, color: "#c0392b", tip: "Filter by soil temperature score." },
  recent_moisture:  { key: "recent_moisture",  label: "Min Moisture",      max: 20,  default: 0, color: "#2980b9", tip: "Filter by moisture score." },
  burn_quality:     { key: "burn_quality",     label: "Min Burn Quality",  max: 15,  default: 0, color: "#f39c12", tip: "Filter by burn recency + type." },
  air_temp:         { key: "air_temp",         label: "Min Air Temp",      max: 5,   default: 0, color: "#7f8c8d", tip: "Filter by air temperature score." },
  elevation_min:    { key: "elevation_min",    label: "Min Elevation (ft)",max: 9000, default: 0,    color: "#3498db", tip: "Hide sites below N feet.", source: "elevation_ft" },
  elevation_max:    { key: "elevation_max",    label: "Max Elevation (ft)",max: 9000, default: 9000, color: "#3498db", tip: "Hide sites above N feet.", mode: "max", source: "elevation_ft" },
};

const SPECIES = {
  morel: {
    label: "Morels (Morchella)",
    color: "#DAA520",
    icon: "M",
    // ── Map rendering ──
    renderMode: "both",   // diamonds + heatmap
    priorityCap: null,    // no cap — show every burn site
    showBurnType: true,
    // ── Sidebar filters (in order) ──
    filters: ["potential", "readiness", "burn_age_max", "soil_threshold",
              "recent_moisture", "burn_quality", "air_temp"],
    // ── Detail page ──
    detail: {
      headerFields: ["acres", "burn_type", "elevation_ft"],
      potentialFactors: [
        { key: "burn_quality", label: "Burn Quality",  max: 40, color: "#f39c12" },
        { key: "vegetation",   label: "Vegetation",    max: 15, color: "#00de00" },
        { key: "elevation",    label: "Elevation",     max: 15, color: "#3498db" },
        { key: "aspect",       label: "Aspect",        max: 10, color: "#27ae60" },
        { key: "season",       label: "Season",        max: 10, color: "#e67e22" },
        { key: "freeze_damage",label: "Freeze",        max: 10, color: "#9b59b6" },
      ],
      siteDetails: [
        ["burn_age",  "Burn Age"],
        ["burn_type", "Type"],
        ["burn_acres","Size"],
        ["elevation", "Elevation"],
        ["aspect",    "Aspect"],
        ["slope",     "Slope"],
        ["ideal_band","Ideal Band"],
        ["in_season", "Season"],
      ],
    },
  },
  porcini: {
    label: "King Bolete / Porcini (Boletus)",
    color: "#8B4513",
    icon: "P",
    // ── Map rendering ──
    // Porcini: ~1000 candidate stands. Markers for ALL would be a sea of
    // diamonds. Use heatmap as the spatial signal, plus markers for the
    // top-N priority sites (best potential × readiness).
    renderMode: "priority",   // heatmap always, markers for top-N only
    priorityCap: 50,
    showBurnType: false,
    // ── Sidebar filters ──
    // No burn_* sliders. Instead: vegetation-aware filters.
    filters: ["potential", "readiness", "elevation_min", "elevation_max"],
    detail: {
      // Header: vegetation + elevation, no burn data
      headerFields: ["evt_short", "elevation_ft", "slope_aspect"],
      potentialFactors: [
        { key: "vegetation",    label: "Vegetation",  max: 50, color: "#00de00" },
        { key: "elevation",     label: "Elevation",   max: 25, color: "#3498db" },
        { key: "season",        label: "Season",      max: 20, color: "#e67e22" },
        { key: "aspect",        label: "Aspect",      max: 5,  color: "#27ae60" },
      ],
      siteDetails: [
        ["elevation", "Elevation"],
        ["aspect",    "Aspect"],
        ["slope",     "Slope"],
        ["in_season", "Season"],
      ],
    },
  },
};

function getSpeciesFromURL() {
  const t = new URLSearchParams(window.location.search).get("type");
  return SUPPORTED_SPECIES.includes(t) ? t : "morel";
}

function selectSpecies(species) {
  if (!SUPPORTED_SPECIES.includes(species)) return;
  const url = new URL(window.location.href);
  if (species === "morel") url.searchParams.delete("type");
  else url.searchParams.set("type", species);
  window.location.href = url.toString();
}

// Compute "priority score" for ranking — combines static site quality with
// current weather conditions. Used to pick the top-N sites to render as
// clickable markers (rest go to heatmap only).
function prioritScore(burn, day) {
  const pd = (burn.phase_days || [])[day] || {};
  const pot = burn.potential || 0;
  const ready = pd.readiness || 0;
  return pot * (ready / 100);
}
