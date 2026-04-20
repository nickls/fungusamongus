// Morel Foraging SPA — loads scored burn data, renders map with day picker + filter sliders

const ALDER_CREEK = [39.3187, -120.2125];
const LOCAL_BOUNDS = [[39.0, -120.65], [39.65, -119.75]];
const BASIN_BOUNDS = [[38.5, -121.3], [39.9, -119.3]];

const FACTORS = [
  { key: "soil_threshold", label: "Soil Temp", max: 25, default: 10, color: "#c0392b", tip: "Is soil 45-58F? Hard gate — below 38F, entire score is crushed. Literature: onset at 43F." },
  { key: "soil_gdd", label: "Soil GDD", max: 25, default: 5, color: "#e67e22", tip: "Cumulative growing degree-days (base 32F). Literature: 365-580 GDD predicts morel onset." },
  { key: "recent_moisture", label: "Moisture", max: 20, default: 5, color: "#2980b9", tip: "Rain or snowmelt in last 3-10 days. Drives fruiting yield." },
  { key: "burn_quality", label: "Burn Quality", max: 15, default: 5, color: "#f39c12", tip: "Burn recency (3-8mo ideal), type (underburn > pile), acreage." },
  { key: "sun_aspect", label: "Sun/Aspect", max: 10, default: 4, color: "#27ae60", tip: "South-facing slopes melt first. Includes slope angle + elevation band." },
  { key: "air_temp", label: "Air Temp", max: 5, default: 2, color: "#7f8c8d", tip: "Daily highs/lows. Indirect proxy — soil temp matters more." },
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
  L.control.layers({"Esri Topo": esriTopo, "CARTO": carto}, null, {position: "topright"}).addTo(map);

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

    // Count excellent sites for this day
    const excellent = data.burns.filter(b =>
      b.days[d] && b.days[d].total >= 80
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

  // Total minimum slider
  const totalRow = makeSlider("total", "Minimum Total", 100, 50);
  group.appendChild(totalRow);

  // Per-factor sliders with smart defaults
  for (const f of FACTORS) {
    const row = makeSlider(f.key, f.label, f.max, f.default || 0);
    group.appendChild(row);
  }
}

function makeSlider(key, label, max, initial) {
  filters[key] = initial;

  const row = document.createElement("div");
  row.className = "slider-row";

  const lbl = document.createElement("label");
  lbl.innerHTML = `${label} <span class="val" id="val-${key}">${initial}/${max}</span>`;

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

  row.appendChild(lbl);
  row.appendChild(input);
  return row;
}

function resetSliders() {
  // Reset to smart defaults, not zero
  const defaults = { total: 50 };
  for (const f of FACTORS) defaults[f.key] = f.default || 0;

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

  const totalMin = filters.total || 0;
  let shown = 0, hidden = 0, excellent = 0;
  const heatData = [];

  for (let burnIdx = 0; burnIdx < data.burns.length; burnIdx++) {
    const burn = data.burns[burnIdx];
    const day = burn.days[selectedDay];
    if (!day) continue;

    // Apply filters
    if (day.total < totalMin) { hidden++; continue; }
    // Hide TOO_EARLY sites — nothing happening there
    const pd0 = (burn.phase_days || [])[selectedDay] || {};
    if (pd0.phase === "TOO_EARLY") { hidden++; continue; }

    let filtered = false;
    for (const f of FACTORS) {
      if (filters[f.key] && day[f.key] < filters[f.key]) {
        filtered = true;
        break;
      }
    }
    if (filtered) { hidden++; continue; }

    shown++;
    if (day.total >= 80) excellent++;

    // Heatmap data — scatter points across burn acreage
    const acres = burn.acres || 1;
    const weight = day.total / 100;
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
      const color = phaseColorMap[phase] || "gray";
      const showDiamond = phase === "EMERGING" || phase === "GROWING";

      if (showDiamond) {
        const size = 22 + Math.floor(readiness / 10);
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

function miniChart(values, label, unit, color, highlightIdx, showLabels) {
  if (!values || values.length === 0) return "";
  const max = Math.max(...values.filter(v => v != null), 1);
  const h = showLabels ? 28 : 18;
  const top = showLabels ? 14 : 0;
  let html = `<div style="display:flex;align-items:center;gap:6px;margin:4px 0;">`;
  html += `<div style="font-size:9px;color:#999;width:50px;flex-shrink:0;text-align:right;">${label}</div>`;
  html += `<div style="display:flex;gap:1px;align-items:flex-end;height:${h}px;flex:1;padding-top:${top}px;">`;
  for (let i = 0; i < values.length; i++) {
    const v = values[i];
    if (v == null) { html += `<div style="flex:1;"></div>`; continue; }
    const pct = Math.max((v / max) * 100, 6);
    const sel = i === highlightIdx;
    const opacity = sel ? 1 : 0.6;
    const border = sel ? "outline:1.5px solid #333;" : "";
    const lbl = typeof v === "number" ? (Number.isInteger(v) ? v : v.toFixed(0)) : v;
    html += `<div style="flex:1;height:${pct}%;background:${color};opacity:${opacity};border-radius:2px 2px 0 0;${border}position:relative;" title="Day ${i}: ${lbl}${unit}">`;
    if (showLabels) {
      html += `<span style="position:absolute;top:-13px;left:50%;transform:translateX(-50%);font-size:8px;color:#555;white-space:nowrap;">${lbl}</span>`;
    }
    html += `</div>`;
  }
  html += `</div></div>`;
  return html;
}

function makePopup(burn, day, burnIdx) {
  const totalColor = day.total >= 80 ? "purple" : day.total >= 70 ? "green" : "orange";
  const pd = (burn.phase_days || [])[selectedDay] || {};
  const phase = pd.phase || "?";
  const readiness = pd.readiness || 0;
  const potential = burn.potential || 0;
  const phaseColors = { EMERGING: "#27ae60", GROWING: "#f39c12", WAITING: "#e67e22", TOO_EARLY: "#95a5a6" };
  const phaseColor = phaseColors[phase] || "#888";

  // Header — name links to detail page
  let html = `<div class="burn-popup" style="min-width:280px;max-width:340px;">`;
  html += `<h3 style="margin:0 0 4px;"><a href="detail.html?i=${burnIdx}&day=${selectedDay}" style="color:inherit;text-decoration:underline;" target="_blank">${burn.name}</a></h3>`;
  html += `<div style="font-size:11px;color:#888;margin-bottom:6px;">`;
  html += `${(burn.acres||0).toFixed(0)}ac | ${burn.burn_type} | ${burn.elevation_ft?.toFixed(0)||"?"}ft`;
  if (burn.slope != null) html += ` | ${burn.slope.toFixed(0)}deg ${aspectDir(burn.aspect)}`;
  html += ` | <a href="https://www.google.com/maps?q=${burn.lat},${burn.lon}" target="_blank" style="color:#53a8b6;">Map</a>`;
  html += `</div>`;

  // Phase banner
  html += `<div style="display:flex;gap:8px;align-items:center;margin:6px 0;padding:6px 8px;background:${phaseColor}20;border-left:3px solid ${phaseColor};border-radius:0 4px 4px 0;">`;
  html += `<span style="font-size:11px;font-weight:bold;color:${phaseColor};">${phase}</span>`;
  html += `<span style="font-size:10px;color:#aaa;">Potential: ${potential}</span>`;
  html += `<span style="font-size:10px;color:#aaa;">Readiness: ${readiness}</span>`;
  if (pd.grow_days) html += `<span style="font-size:10px;color:#888;">${pd.grow_days} grow days</span>`;
  html += `</div>`;

  // Score + factor breakdown as colored blocks
  const ratingLabel = day.total >= 80 ? "EXCELLENT" : day.total >= 70 ? "GOOD" : day.total >= 50 ? "FAIR" : "POOR";
  html += `<div style="display:flex;align-items:center;gap:10px;margin:4px 0 8px;">`;
  html += `<span style="font-size:24px;font-weight:bold;color:${totalColor};cursor:default;" title="${ratingLabel} — ${day.total}/100 total score">${day.total}</span>`;
  html += `<div style="display:flex;gap:2px;flex:1;height:16px;cursor:default;" title="Factor breakdown (hover each block)">`;
  for (const f of FACTORS) {
    const v = day[f.key] || 0;
    const pct = (v / f.max) * 100;
    const pctLabel = Math.round(pct);
    html += `<div style="flex:${f.max};background:${f.color};opacity:${pct > 50 ? 0.9 : 0.3};height:100%;border-radius:2px;cursor:help;" title="${f.label}: ${v}/${f.max} (${pctLabel}%)"></div>`;
  }
  html += `</div></div>`;

  // Factor table — compact 2-column with tooltips
  html += `<table style="width:100%;font-size:11px;border-collapse:collapse;margin-bottom:8px;">`;
  for (let i = 0; i < FACTORS.length; i += 2) {
    html += `<tr>`;
    for (let j = i; j < i + 2 && j < FACTORS.length; j++) {
      const f = FACTORS[j];
      const v = day[f.key] || 0;
      html += `<td style="padding:2px 4px;color:#aaa;width:25%;cursor:help;" title="${f.tip}">${f.label}</td>`;
      html += `<td style="padding:2px 4px;font-weight:bold;width:25%;color:${v >= f.max * 0.7 ? f.color : '#666'};cursor:help;" title="${f.tip}">${v}/${f.max}</td>`;
    }
    html += `</tr>`;
  }
  html += `</table>`;

  // 8-day charts — score gets labels, others are compact
  const totals = burn.days.map(d => d.total);
  html += miniChart(totals, "Score", "", totalColor, selectedDay, true);

  const soilTemps = burn.days.map(d => {
    const m = (d.soil_temp || "").match(/(\d+)/);
    return m ? parseInt(m[1]) : null;
  });
  if (soilTemps.some(v => v != null)) {
    html += miniChart(soilTemps, "Soil", "F", "#c0392b", selectedDay, false);
  }

  const moisture = burn.days.map(d => d.recent_moisture || 0);
  html += miniChart(moisture, "Moisture", "", "#2980b9", selectedDay, false);

  const warming = burn.days.map(d => d.warming_trend || 0);
  html += miniChart(warming, "Warming", "", "#e67e22", selectedDay, false);

  // Soil temp daily deltas — shows rate of change over 14 days
  const deltas = day.soil_deltas;
  if (deltas && deltas.length > 0) {
    html += `<div style="display:flex;align-items:center;gap:6px;margin:4px 0;">`;
    html += `<div style="font-size:9px;color:#999;width:50px;flex-shrink:0;text-align:right;">Soil &Delta;/day</div>`;
    html += `<div style="display:flex;gap:1px;align-items:center;height:24px;flex:1;">`;
    const maxDelta = Math.max(...deltas.map(d => Math.abs(d)), 1);
    for (let i = 0; i < deltas.length; i++) {
      const d = deltas[i];
      const pct = Math.max(Math.abs(d) / maxDelta * 100, 4);
      const color = d > 0 ? "#e67e22" : d < 0 ? "#3498db" : "#666";
      const up = d >= 0;
      html += `<div style="flex:1;display:flex;flex-direction:column;align-items:center;justify-content:${up ? 'flex-end' : 'flex-start'};height:100%;" title="Day ${i+1}: ${d>0?'+':''}${d}F">`;
      html += `<div style="width:100%;height:${pct/2}%;background:${color};border-radius:2px;min-height:1px;"></div>`;
      html += `</div>`;
    }
    html += `</div></div>`;
  }

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
