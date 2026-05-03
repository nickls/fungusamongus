// Morel Foraging SPA — loads scored burn data, renders map with day picker + filter sliders

const ALDER_CREEK = [39.3187, -120.2125];
const LOCAL_BOUNDS = [[39.0, -120.65], [39.65, -119.75]];
const BASIN_BOUNDS = [[38.5, -121.3], [39.9, -119.3]];

const FILTERS = [
  // Phase scores
  { key: "potential", label: "Min Potential", max: 100, default: 0, color: "#53a8b6", tip: "Site quality — burn recency, type, elevation, aspect." },
  { key: "readiness", label: "Min Readiness", max: 100, default: 0, color: "#e94560", tip: "How close to fruiting — start days, grow days, weather." },
  { key: "burn_age_max", label: "Max Burn Age (mo)", max: 36, default: 36, color: "#e67e22", tip: "Hide burns older than N months. Default 36 = no limit.", mode: "max", source: "burn_age_months" },
  // Raw conditions (from legacy day scores)
  { key: "soil_threshold", label: "Min Soil Temp", max: 25, default: 0, color: "#c0392b", tip: "Filter by soil temperature score." },
  { key: "recent_moisture", label: "Min Moisture", max: 20, default: 0, color: "#2980b9", tip: "Filter by moisture score." },
  { key: "burn_quality", label: "Min Burn Quality", max: 15, default: 0, color: "#f39c12", tip: "Filter by burn recency + type." },
  { key: "air_temp", label: "Min Air Temp", max: 5, default: 0, color: "#7f8c8d", tip: "Filter by air temperature score." },
];

let map, markersLayer, heatLayer;
let data = null;
let selectedDay = 0;
let filters = {};
let currentZoom = "local";
let layerMode = "both"; // "both", "markers", "heat"

// ── Init ──

async function init() {
  // Load data
  try {
    const resp = await fetch("data/latest.json");
    data = await resp.json();
  } catch (e) {
    document.getElementById("sidebar").innerHTML =
      "<h1>No data</h1><p>Run <code>python morel_finder.py</code> first.</p>";
    return;
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

  L.control.layers(
    {"Esri Topo": esriTopo, "CARTO": carto},
    {"Vegetation (LANDFIRE)": landfireEVT},
    {position: "topright"}
  ).addTo(map);

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

function buildSliders() {
  const group = document.getElementById("slider-group");

  for (const f of FILTERS) {
    const row = makeSlider(f.key, f.label, f.max, f.default || 0, f.tip);
    group.appendChild(row);
  }
  group.appendChild(buildBurnTypeFilter());
}

const BURN_TYPES = ["Machine Pile", "Hand Pile", "Pile Burn", "Underburn", "Broadcast", "RX", "wildfire"];

function buildBurnTypeFilter() {
  // Initialize all enabled
  filters.burn_types = new Set(BURN_TYPES);

  const row = document.createElement("div");
  row.className = "slider-row";
  row.innerHTML = `<label>Burn Types <span style="font-size:10px;color:#666;">(click to toggle)</span></label>`;

  const tipEl = document.createElement("div");
  tipEl.style.cssText = "font-size:10px;color:#666;margin-top:-1px;margin-bottom:4px;";
  tipEl.textContent = "Show only selected burn types.";
  row.appendChild(tipEl);

  const chipBox = document.createElement("div");
  chipBox.style.cssText = "display:flex;flex-wrap:wrap;gap:4px;";

  for (const t of BURN_TYPES) {
    const chip = document.createElement("button");
    chip.textContent = t;
    chip.dataset.type = t;
    chip.style.cssText = "background:#0f3460;color:#fff;border:1px solid #53a8b6;border-radius:12px;padding:3px 9px;font-size:10px;cursor:pointer;";
    chip.classList.add("burn-chip", "active");
    chip.onclick = () => {
      const active = chip.classList.toggle("active");
      if (active) {
        chip.style.background = "#0f3460";
        chip.style.color = "#fff";
        filters.burn_types.add(t);
      } else {
        chip.style.background = "#16213e";
        chip.style.color = "#666";
        filters.burn_types.delete(t);
      }
      render();
    };
    chipBox.appendChild(chip);
  }
  row.appendChild(chipBox);
  return row;
}

function matchesBurnType(burn) {
  if (!filters.burn_types || filters.burn_types.size === BURN_TYPES.length) return true;  // all enabled = no filter
  const t = burn.burn_type || "";
  // Match against each selected type case-insensitively
  for (const sel of filters.burn_types) {
    if (t.toLowerCase().includes(sel.toLowerCase())) return true;
  }
  return false;
}

function makeSlider(key, label, max, initial, tip) {
  filters[key] = initial;

  const row = document.createElement("div");
  row.className = "slider-row";

  const lbl = document.createElement("label");
  lbl.innerHTML = `${label} <span class="val" id="val-${key}">${initial}/${max}</span>`;

  if (tip) {
    const tipEl = document.createElement("div");
    tipEl.style.cssText = "font-size:10px;color:#666;margin-top:-1px;margin-bottom:2px;";
    tipEl.textContent = tip;
    row.appendChild(lbl);
    row.appendChild(tipEl);
  } else {
    row.appendChild(lbl);
  }

  const input = document.createElement("input");
  input.type = "range";
  input.min = 0;
  input.max = max;
  input.value = initial;
  input.dataset.key = key;
  input.oninput = () => {
    filters[key] = parseInt(input.value);
    document.getElementById(`val-${key}`).textContent = `${input.value}/${max}`;
    render();
  };

  row.appendChild(input);
  return row;
}

function resetSliders() {
  const defaults = {};
  for (const f of FILTERS) defaults[f.key] = f.default || 0;

  document.querySelectorAll("#slider-group .slider-row").forEach(row => {
    const input = row.querySelector("input[type=range]");
    const valSpan = row.querySelector(".val");
    if (input && input.dataset.key) {
      const def = defaults[input.dataset.key] || 0;
      input.value = def;
      filters[input.dataset.key] = def;
      if (valSpan) valSpan.textContent = `${def}/${input.max}`;
    }
  });

  // Re-enable all burn type chips
  filters.burn_types = new Set(BURN_TYPES);
  document.querySelectorAll(".burn-chip").forEach(chip => {
    chip.classList.add("active");
    chip.style.background = "#0f3460";
    chip.style.color = "#fff";
  });

  render();
}

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
  render();
}

// ── Render ──

function render() {
  markersLayer.clearLayers();
  if (heatLayer) { map.removeLayer(heatLayer); heatLayer = null; }

  if (!data) return;

  let shown = 0, hidden = 0;
  const heatData = [];

  for (let burnIdx = 0; burnIdx < data.burns.length; burnIdx++) {
    const burn = data.burns[burnIdx];
    const day = burn.days[selectedDay];
    if (!day) continue;

    // Apply filters — potential and readiness
    const pd0 = (burn.phase_days || [])[selectedDay] || {};
    const potential = burn.potential || 0;
    const readiness0 = pd0.readiness || 0;

    if (potential < (filters.potential || 0)) { hidden++; continue; }
    if (readiness0 < (filters.readiness || 0)) { hidden++; continue; }

    // Burn age filter (max — hide older than slider value)
    if (filters.burn_age_max != null && burn.burn_age_months != null
        && burn.burn_age_months > filters.burn_age_max) { hidden++; continue; }

    // Burn type filter
    if (!matchesBurnType(burn)) { hidden++; continue; }

    // Raw condition filters (from legacy day scores)
    let filtered = false;
    for (const f of FILTERS) {
      if (f.key === "potential" || f.key === "readiness" || f.key === "burn_age_max") continue;
      if (filters[f.key] && day[f.key] != null && day[f.key] < filters[f.key]) {
        filtered = true;
        break;
      }
    }
    if (filtered) { hidden++; continue; }

    shown++;

    // Heatmap data — scatter points across burn acreage
    const acres = burn.acres || 1;
    const weight = potential / 100;
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

    // Marker (only if layerMode includes markers)
    if (layerMode === "both" || layerMode === "markers") {
      // Color by phase (from phase_days for selected day)
      const pd = (burn.phase_days || [])[selectedDay] || {};
      const phase = pd.phase || "?";
      const readiness = pd.readiness || 0;
      const potential = burn.potential || 0;
      const phaseColorMap = { EMERGING: "purple", GROWING: "green", WAITING: "orange", TOO_EARLY: "gray" };
      // Shape = potential (site quality), number inside = readiness
      const color = phaseColorMap[phase] || "orange";
      const showDiamond = potential >= 70;  // good burn sites always get diamonds

      if (showDiamond) {
        const size = potential >= 90 ? 32 : potential >= 75 ? 22 : 14;  // big / medium / small
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
      } else {
        L.circleMarker([burn.lat, burn.lon], {
          radius: 4,
          color: color,
          fillColor: color,
          fillOpacity: 0.6,
          weight: 1,
        })
          .bindPopup(() => makePopup(burn, day, burnIdx), {maxWidth: 360})
          .addTo(markersLayer);
      }
    }
  }

  // Heatmap (only if layerMode includes heat)
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

function makePopup(burn, day, burnIdx) {
  const pd = (burn.phase_days || [])[selectedDay] || {};
  const phase = pd.phase || "?";
  const readiness = pd.readiness || 0;
  const potential = burn.potential || 0;
  const phaseColors = { EMERGING: "#27ae60", GROWING: "#f39c12", WAITING: "#e67e22", TOO_EARLY: "#95a5a6" };
  const phaseColor = phaseColors[phase] || "#888";

  // Header — name links to detail page
  let html = `<div class="burn-popup" style="min-width:280px;max-width:340px;">`;
  html += `<h3 style="margin:0 0 4px;"><a href="detail.html?site=${burn.slug}&day=${selectedDay}" style="color:inherit;text-decoration:underline;" target="_blank">${burn.name}</a></h3>`;
  html += `<div style="font-size:11px;color:#888;margin-bottom:6px;">`;
  html += `${(burn.acres||0).toFixed(0)}ac | ${burn.burn_type} | ${burn.elevation_ft?.toFixed(0)||"?"}ft`;
  if (burn.slope != null) html += ` | ${burn.slope.toFixed(0)}deg ${aspectDir(burn.aspect)}`;
  if (burn.evt_name) html += `<br>${burn.evt_name}`;
  html += ` | <a href="https://www.google.com/maps?q=${burn.lat},${burn.lon}" target="_blank" style="color:#53a8b6;">Map</a>`;
  html += `</div>`;

  // Phase banner
  html += `<div style="display:flex;gap:8px;align-items:center;margin:6px 0;padding:6px 8px;background:${phaseColor}20;border-left:3px solid ${phaseColor};border-radius:0 4px 4px 0;">`;
  html += `<span style="font-size:11px;font-weight:bold;color:${phaseColor};">${phase}</span>`;
  html += `<span style="font-size:10px;color:#aaa;">Potential: ${potential}/100</span>`;
  html += `<span style="font-size:10px;color:#aaa;">Readiness: ${readiness}/100</span>`;
  if (pd.grow_days) html += `<span style="font-size:10px;color:#888;">${pd.grow_days} grow days</span>`;
  html += `</div>`;

  // Phase-based summary (replaces old score display)
  html += `<div style="display:flex;align-items:center;gap:12px;margin:6px 0;">`;
  html += `<div style="text-align:center;min-width:60px;">`;
  html += `<div style="font-size:11px;color:#888;">Potential</div>`;
  html += `<div style="font-size:20px;font-weight:bold;color:#53a8b6;">${potential}<span style="font-size:11px;color:#666;">/100</span></div>`;
  html += `</div>`;
  html += `<div style="text-align:center;min-width:60px;">`;
  html += `<div style="font-size:11px;color:#888;">Readiness</div>`;
  html += `<div style="font-size:20px;font-weight:bold;color:${phaseColor};">${readiness}<span style="font-size:11px;color:#666;">/100</span></div>`;
  html += `</div>`;
  html += `<div style="font-size:10px;color:#888;line-height:1.4;">`;
  html += `${pd.grow_days || 0} grow / ${pd.start_days || 0} start days<br>`;
  html += `Soil: ${day.soil_temp || "?"} | Age: ${day.burn_age || "?"}<br>`;
  if (day.snow_status) html += `${day.snow_status}`;
  html += `</div>`;
  html += `</div>`;

  // Key details — compact
  html += `<div style="margin-top:8px;font-size:11px;color:#888;line-height:1.6;">`;
  const show = ["snow_status", "burn_age"];
  for (const k of show) {
    if (day[k]) {
      const label = k.replace(/_/g, " ");
      const val = day[k];
      const highlight = val.includes("MELT");
      html += `<span style="color:${highlight ? '#53a8b6' : '#888'};">${label}: <b>${val}</b></span><br>`;
    }
  }

  // Soil trend visualization
  const trendStr = day.soil_trend || "";
  const trendPerDay = day.soil_trend_per_day;
  if (trendStr) {
    const isWarming = trendStr.includes("WARMING") || trendStr.includes("warming");
    const isCooling = trendStr.includes("cooling");
    const trendColor = isWarming ? "#e67e22" : isCooling ? "#3498db" : "#888";
    const arrowCount = Math.min(Math.abs(Math.round((trendPerDay || 0) * 3)), 5);
    const arrows = isWarming ? "&#9650;".repeat(Math.max(arrowCount, 1))
                 : isCooling ? "&#9660;".repeat(Math.max(arrowCount, 1))
                 : "&#9654;";

    html += `<div style="margin:6px 0;padding:6px 8px;background:${trendColor}15;border-left:3px solid ${trendColor};border-radius:0 4px 4px 0;">`;
    html += `<div style="display:flex;align-items:center;gap:6px;">`;
    html += `<span style="font-size:14px;color:${trendColor};">${arrows}</span>`;
    html += `<div>`;
    html += `<div style="font-weight:bold;color:${trendColor};font-size:12px;">${trendStr}</div>`;
    if (trendPerDay != null) {
      const absRate = Math.abs(trendPerDay).toFixed(1);
      const rateLabel = trendPerDay > 0.5 ? "Strong" : trendPerDay > 0.2 ? "Moderate" : trendPerDay > 0 ? "Slight" : trendPerDay > -0.2 ? "Flat" : "Dropping";
      html += `<div style="font-size:10px;color:#999;">${rateLabel} — ${absRate}F per day over 14 days</div>`;
    }
    html += `</div></div></div>`;
  }

  // In season
  if (day.in_season) {
    const inSeason = day.in_season === "YES";
    html += `<span style="color:${inSeason ? '#53a8b6' : '#888'};">season: <b>${day.in_season}</b></span>`;
  }

  html += `</div>`;
  return html;
}

function aspectDir(deg) {
  if (deg == null) return "?";
  const dirs = ["N","NE","E","SE","S","SW","W","NW"];
  return dirs[Math.floor(((deg + 22.5) % 360) / 45)];
}

// ── Sidebar toggle ──

function toggleSidebar() {
  document.getElementById("app").classList.toggle("sidebar-hidden");
  // Leaflet needs to recalculate map size after sidebar shows/hides
  setTimeout(() => { if (map) map.invalidateSize(); }, 50);
}

// ── Boot ──

document.addEventListener("DOMContentLoaded", init);
