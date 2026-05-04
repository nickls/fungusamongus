// Foraging SPA — loads scored data per mushroom type, renders map.
// Type is selected via the species buttons or ?type= URL param. Default: morel.
// Per-species rendering / filter / detail config lives in species.js.

const ALDER_CREEK = [39.3187, -120.2125];
const LOCAL_BOUNDS = [[39.0, -120.65], [39.65, -119.75]];
const BASIN_BOUNDS = [[38.5, -121.3], [39.9, -119.3]];

// Active species config (set in init); FILTERS derives from it.
let speciesConfig = null;
let FILTERS = [];

let map, markersLayer, heatLayer, suitabilityOverlay;
let data = null;
let selectedDay = 0;
let filters = {};
let currentZoom = "local";
let layerMode = "both"; // "both", "markers", "heat"

// ── Init ──

async function init() {
  const species = getSpeciesFromURL();
  speciesConfig = SPECIES[species];
  // Hydrate FILTERS from species config — references FILTER_LIBRARY in species.js
  FILTERS = speciesConfig.filters.map((k) => FILTER_LIBRARY[k]).filter(Boolean);

  // Load data — per-type JSON. Falls back to legacy latest.json (= morel alias).
  try {
    const url = species === "morel"
      ? "data/morel-latest.json"
      : `data/${species}-latest.json`;
    let resp = await fetch(url);
    if (!resp.ok && species === "morel") resp = await fetch("data/latest.json");
    if (!resp.ok) throw new Error(`HTTP ${resp.status} for ${url}`);
    data = await resp.json();
  } catch (e) {
    document.getElementById("sidebar").innerHTML =
      `<h1>No ${species} data</h1><p>Run <code>python morel_finder.py --mushroom-type=${species}</code> first.</p>`;
    return;
  }

  // Sync active species button to URL
  document.querySelectorAll(".species-btn").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.species === species);
  });

  // Show only the legend rows that apply to the active species
  document.querySelectorAll("[class*='legend-'][class$='-only']").forEach((row) => {
    const matchClass = `legend-${species}-only`;
    row.style.display = row.classList.contains(matchClass) ? "" : "none";
  });

  // Relabel the third Layers button to match the species: "Heatmap" for
  // morel (Gaussian density), "Overlay" for porcini (suitability raster).
  const heatBtn = document.querySelector('.layer-btn[data-layer="heat"]');
  if (heatBtn) {
    heatBtn.textContent = speciesConfig.useHeatmap ? "Heatmap" : "Overlay";
  }

  // Set metadata
  document.getElementById("run-date").textContent = data.run_date;
  document.getElementById("algo-version").textContent = data.algo_version;

  // Init map with layer control for base maps
  map = L.map("map", { zoomControl: true });
  const carto = L.tileLayer("https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png", {
    attribution: '&copy; <a href="https://carto.com/">CARTO</a>',
    maxZoom: 18,
  });
  const esriTopo = L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}", {
    attribution: "Esri",
    maxZoom: 18,
  });
  const esriSat = L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", {
    attribution: "Esri, Maxar, Earthstar Geographics",
    maxZoom: 18,
  });
  esriTopo.addTo(map);

  // LANDFIRE EVT vegetation overlay (ArcGIS ImageServer — needs bbox per tile)
  const LandfireLayer = L.TileLayer.extend({
    getTileUrl: function(coords) {
      const tileSize = this.getTileSize();
      const nwPoint = coords.scaleBy(tileSize);
      const sePoint = nwPoint.add(tileSize);
      const nw = this._map.unproject(nwPoint, coords.z);
      const se = this._map.unproject(sePoint, coords.z);
      return "https://lfps.usgs.gov/arcgis/rest/services/Landfire_LF2024/LF2024_EVT_CONUS/ImageServer/exportImage"
        + `?bbox=${nw.lng},${se.lat},${se.lng},${nw.lat}&bboxSR=4326&size=256,256&format=png&transparent=true&f=image`;
    },
  });
  const landfireEVT = new LandfireLayer("", {
    attribution: "LANDFIRE",
    opacity: 0.5,
    maxZoom: 16,
  });

  // Build the overlay layer set, including any species-specific suitability
  // raster (porcini gets a pre-rendered PNG of pixel-level porcini score).
  const overlayLayers = { "Vegetation (LANDFIRE)": landfireEVT };
  if (speciesConfig.overlay) {
    // Prefer the sidecar JSON's actual raster bounds (ArcGIS pads the
    // requested bbox to preserve pixel aspect). Fall back to declared bounds.
    let bounds = speciesConfig.overlay.bounds;
    if (speciesConfig.overlay.boundsURL) {
      try {
        const r = await fetch(speciesConfig.overlay.boundsURL);
        if (r.ok) {
          const meta = await r.json();
          if (meta.leaflet_bounds) bounds = meta.leaflet_bounds;
        }
      } catch (e) { /* keep fallback */ }
    }
    suitabilityOverlay = L.imageOverlay(
      speciesConfig.overlay.url, bounds,
      { opacity: speciesConfig.overlay.opacity || 0.55 }
    );
    suitabilityOverlay.addTo(map);
    overlayLayers[`${speciesConfig.label.split(" ")[0]} suitability`] = suitabilityOverlay;
  }

  L.control.layers(
    {"Esri Topo": esriTopo, "Satellite": esriSat, "CARTO": carto},
    overlayLayers,
    {position: "topright"}
  ).addTo(map);

  // Locate-me control (top-left, under the zoom buttons)
  const LocateControl = L.Control.extend({
    options: { position: "topleft" },
    onAdd: function() {
      const container = L.DomUtil.create("div", "leaflet-bar leaflet-control");
      const btn = L.DomUtil.create("a", "locate-btn", container);
      btn.href = "#";
      btn.title = "Show my location";
      btn.innerHTML = "&#9678;";
      L.DomEvent.on(btn, "click", (e) => {
        L.DomEvent.preventDefault(e);
        L.DomEvent.stopPropagation(e);
        btn.classList.add("locate-btn-loading");
        map.locate({ setView: true, maxZoom: 13, enableHighAccuracy: true, timeout: 10000 });
      });
      L.DomEvent.disableClickPropagation(container);
      return container;
    },
  });
  new LocateControl().addTo(map);

  let locateMarker = null;
  let locateCircle = null;
  map.on("locationfound", (e) => {
    document.querySelector(".locate-btn")?.classList.remove("locate-btn-loading");
    if (locateMarker) map.removeLayer(locateMarker);
    if (locateCircle) map.removeLayer(locateCircle);
    locateCircle = L.circle(e.latlng, {
      radius: e.accuracy,
      color: "#1e90ff",
      weight: 1,
      fillOpacity: 0.1,
    }).addTo(map);
    locateMarker = L.circleMarker(e.latlng, {
      radius: 6,
      color: "#fff",
      weight: 2,
      fillColor: "#1e90ff",
      fillOpacity: 1,
    }).addTo(map);
  });
  map.on("locationerror", (e) => {
    document.querySelector(".locate-btn")?.classList.remove("locate-btn-loading");
    alert("Couldn't get your location: " + e.message);
  });

  // Show/hide veg legend when overlay is toggled
  map.on("overlayadd", (e) => {
    if (e.name === "Vegetation (LANDFIRE)") {
      document.getElementById("veg-legend").style.display = "";
    }
  });
  map.on("overlayremove", (e) => {
    if (e.name === "Vegetation (LANDFIRE)") {
      document.getElementById("veg-legend").style.display = "none";
    }
  });

  markersLayer = L.layerGroup().addTo(map);

  // Build UI
  buildDayBar();
  buildSliders();
  buildZoomBar();

  // Initial render
  setZoom("local");
  render();
}

// ── Day Bar ──

function buildDayBar() {
  const bar = document.getElementById("day-bar");
  if (!data || !data.burns.length || !data.burns[0].days) return;

  const numDays = data.burns[0].days.length;
  for (let d = 0; d < numDays; d++) {
    const dayData = data.burns[0].days[d];
    const label = d === 0 ? "NOW" : `+${d}`;
    const dateStr = dayData.date ? dayData.date.slice(5) : "";

    // Count EMERGING sites for this day
    const excellent = data.burns.filter(b =>
      (b.phase_days || [])[d] && (b.phase_days || [])[d].phase === "EMERGING"
    ).length;

    const btn = document.createElement("button");
    btn.className = `day-btn${d === 0 ? " active" : ""}`;
    btn.innerHTML = `<div class="day-label">${label}</div><div class="day-count">${dateStr}</div>`;
    btn.title = `${excellent} excellent sites`;
    btn.onclick = () => selectDay(d);
    bar.appendChild(btn);
  }
}

function selectDay(d) {
  selectedDay = d;
  document.querySelectorAll(".day-btn").forEach((btn, i) => {
    btn.classList.toggle("active", i === d);
  });
  render();
}

// ── Sliders ──

// Filter UI (sliders, burn-type chips) and matching logic moved to filters.js.
// Functions exposed: buildSliders, resetSliders, matchesBurnType, passesFilters.

// ── Zoom ──

function buildZoomBar() {
  // Already in HTML, just wire up
}

function setZoom(mode) {
  currentZoom = mode;
  document.querySelectorAll(".zoom-btn").forEach(btn => {
    btn.classList.toggle("active", btn.dataset.zoom === mode);
  });
  const bounds = mode === "local" ? LOCAL_BOUNDS : BASIN_BOUNDS;
  map.fitBounds(bounds);
}

function setLayers(mode) {
  layerMode = mode;
  document.querySelectorAll(".layer-btn").forEach(btn => {
    btn.classList.toggle("active", btn.dataset.layer === mode);
  });
  // Suitability raster overlay (porcini): tie visibility to layerMode so the
  // "Markers / Overlay / Both" buttons work as expected.
  if (suitabilityOverlay) {
    const showOverlay = mode === "both" || mode === "heat";
    if (showOverlay && !map.hasLayer(suitabilityOverlay)) suitabilityOverlay.addTo(map);
    else if (!showOverlay && map.hasLayer(suitabilityOverlay)) map.removeLayer(suitabilityOverlay);
  }
  render();
}

// ── Render ──

function render() {
  markersLayer.clearLayers();
  if (heatLayer) { map.removeLayer(heatLayer); heatLayer = null; }

  if (!data) return;

  let shown = 0, hidden = 0;
  const heatData = [];

  // Pass 1: gather eligible burns. For "priority" render mode, also rank by
  // (potential × readiness/100) so we can mark only the top-N as marker-eligible.
  const eligible = [];
  for (let burnIdx = 0; burnIdx < data.burns.length; burnIdx++) {
    const burn = data.burns[burnIdx];
    const day = burn.days[selectedDay];
    if (!day) { hidden++; continue; }
    if (!passesFilters(burn, day)) { hidden++; continue; }
    eligible.push({ burn, day, burnIdx, score: prioritScore(burn, selectedDay) });
  }

  // Mark which burns get the diamond "priority" marker treatment.
  // For non-"both" render modes, only the top-N priority sites get diamonds.
  let markerSet;
  if (speciesConfig.renderMode !== "both") {
    const cap = speciesConfig.priorityCap || 50;
    const topN = [...eligible].sort((a, b) => b.score - a.score).slice(0, cap);
    markerSet = new Set(topN.map(e => e.burnIdx));
  } else {
    markerSet = null;  // null = all eligible get diamond markers
  }

  // Pass 2: emit discs (porcini) / heat (morel) + markers
  for (const { burn, day, burnIdx } of eligible) {
    shown++;

    const potential = burn.potential || 0;
    const pd = (burn.phase_days || [])[selectedDay] || {};
    const readiness = pd.readiness || 0;
    const phase = pd.phase || "?";

    // Heat data: only for species that actually want a Gaussian heatmap
    if (speciesConfig.useHeatmap) {
      const weight = potential / 100;
      const acres = burn.acres || 1;
      const burnRadiusM = Math.sqrt(acres * 4047 / Math.PI);
      const burnRadiusDeg = burnRadiusM / 111000;
      heatData.push([burn.lat, burn.lon, weight * 3]);
      if (acres >= 2) {
        const nRing = Math.min(Math.max(6, Math.floor(acres / 2)), 16);
        for (let i = 0; i < nRing; i++) {
          const angle = (2 * Math.PI * i) / nRing;
          heatData.push([
            burn.lat + burnRadiusDeg * 0.5 * Math.sin(angle),
            burn.lon + burnRadiusDeg * 0.5 * Math.cos(angle),
            weight * 2.4,
          ]);
        }
      }
    }

    // Disc render: every eligible stand gets a colored circle (porcini).
    // Color = readiness × potential mapped through phase color; size = stand
    // size (pixel_count for porcini, fixed otherwise).
    if (speciesConfig.renderMode === "discs"
        && (layerMode === "both" || layerMode === "heat")) {
      const score = (potential * (readiness / 100)) / 100;  // 0..1
      const discColor = scoreColor(score);
      const radius = Math.max(2.5, Math.min(10, Math.sqrt((burn.pixel_count || 4) / 2)));
      L.circleMarker([burn.lat, burn.lon], {
        radius,
        color: "#000",
        weight: 0.5,
        fillColor: discColor,
        fillOpacity: 0.7,
      })
        .bindPopup(() => makePopup(burn, day, burnIdx), {maxWidth: 360})
        .addTo(markersLayer);
    }

    // Diamond marker for priority sites OR all sites in modes "both"/"markers".
    const inMarkerSet = markerSet === null || markerSet.has(burnIdx);
    if (inMarkerSet && (layerMode === "both" || layerMode === "markers")) {
      const phaseColorMap = { EMERGING: "purple", GROWING: "green", WAITING: "orange", TOO_EARLY: "gray" };
      const color = phaseColorMap[phase] || "orange";
      const showDiamond = potential >= 60;

      if (showDiamond) {
        const t = Math.max(0, Math.min(1, (potential - 60) / 30));
        const size = Math.round(12 + t * 20);
        const icon = L.divIcon({
          className: "",
          html: `<div style="
            width:${size}px;height:${size}px;
            background:${color};
            border:2px solid white;
            border-radius:3px;
            transform:rotate(45deg);
            box-shadow:0 0 4px rgba(0,0,0,0.5);
            display:flex;align-items:center;justify-content:center;
          "><span style="transform:rotate(-45deg);color:white;
            font-weight:bold;font-size:10px;">${readiness}</span></div>`,
          iconSize: [size, size],
          iconAnchor: [size / 2, size / 2],
        });
        L.marker([burn.lat, burn.lon], { icon })
          .bindPopup(() => makePopup(burn, day, burnIdx), {maxWidth: 360})
          .addTo(markersLayer);
      } else if (speciesConfig.renderMode === "both") {
        // Small dot fallback for low-potential morel burns. Porcini doesn't
        // need this — the suitability raster already paints those areas.
        L.circleMarker([burn.lat, burn.lon], {
          radius: 4, color, fillColor: color, fillOpacity: 0.6, weight: 1,
        })
          .bindPopup(() => makePopup(burn, day, burnIdx), {maxWidth: 360})
          .addTo(markersLayer);
      }
    }
  }

  // Gaussian heatmap (only for species that opted in)
  if (heatData.length > 0 && typeof L.heatLayer === "function"
      && (layerMode === "both" || layerMode === "heat")) {
    heatLayer = L.heatLayer(heatData, {
      radius: 22,
      blur: 30,
      maxZoom: 16,
      minOpacity: 0.4,
      gradient: {
        0.15: "#0000ff", 0.3: "#00ffff", 0.45: "#00ff00",
        0.6: "#ffff00", 0.75: "#ff8800", 0.9: "#ff0000", 1.0: "#cc0000",
      },
    }).addTo(map);
  }

  // Stats
  // Count phases for stats
  let emerging = 0, growing = 0;
  for (const burn of data.burns) {
    const pd1 = (burn.phase_days || [])[selectedDay] || {};
    if (pd1.phase === "EMERGING") emerging++;
    else if (pd1.phase === "GROWING") growing++;
  }
  document.getElementById("stats").innerHTML =
    `<span>${shown}</span> shown, ${hidden} hidden | <span style="color:purple">${emerging}</span> emerging, <span style="color:green">${growing}</span> growing`;
}

// ── Popup ──

// Popup HTML (makePopup, aspectDir) moved to popup.js.

// ── Sidebar toggle ──

function toggleSidebar() {
  document.getElementById("app").classList.toggle("sidebar-hidden");
  // Leaflet needs to recalculate map size after sidebar shows/hides
  setTimeout(() => { if (map) map.invalidateSize(); }, 50);
}

// ── Boot ──

document.addEventListener("DOMContentLoaded", init);
