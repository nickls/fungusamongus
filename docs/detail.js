const PHASE_COLORS = { EMERGING: "#27ae60", GROWING: "#f39c12", WAITING: "#e67e22", TOO_EARLY: "#95a5a6" };

const EVT_COLORS = {
  "Mediterranean California Dry-Mesic Mixed Conifer Forest and Woodland": "#00de00",
  "Mediterranean California Mesic Mixed Conifer Forest and Woodland": "#00cc00",
  "California Montane Jeffrey Pine-(Ponderosa Pine) Woodland": "#00ad00",
  "Mediterranean California Red Fir Forest": "#009e00",
  "Mediterranean California Lower Montane Conifer Forest and Woodland": "#00bd00",
  "Inter-Mountain Basins Aspen-Mixed Conifer Forest and Woodland": "#c0ff8a",
  "Sierra Nevada Subalpine Lodgepole Pine Forest and Woodland": "#a3f0db",
  "Mediterranean California Subalpine Woodland": "#009100",
  "Inter-Mountain Basins Big Sagebrush Shrubland": "#826548",
  "Mediterranean California Mixed Evergreen Forest": "#003d00",
};

const EVT_SUIT = {
  "Mixed Conifer": "Prime — highest morel producer",
  "Jeffrey Pine": "Good — produces well after burns",
  "Red Fir": "Good — true fir stands are productive",
  "Lower Montane": "Good — mixed species",
  "Aspen-Conifer": "Good — aspen mix is productive",
  "Mixed Evergreen": "Decent — variable results",
  "Lodgepole": "Marginal — cold, short season",
  "Subalpine": "Marginal — high elevation, cold",
  "Sagebrush": "Poor — no trees, no morels",
};

async function init() {
  const params = new URLSearchParams(window.location.search);
  const slug = params.get("site");
  const day = parseInt(params.get("day") || "0");

  let data, historyData;
  try {
    const [resp, histResp] = await Promise.all([
      fetch("data/latest.json"),
      fetch("data/history.json").catch(() => null),
    ]);
    data = await resp.json();
    historyData = histResp ? await histResp.json() : [];
  } catch (e) {
    document.getElementById("content").innerHTML = "<p>No data. Run morel_finder.py first.</p>";
    return;
  }

  // Look up by slug (stable), fall back to index for old links
  let idx, burn;
  if (slug) {
    idx = data.burns.findIndex(b => b.slug === slug);
    burn = idx >= 0 ? data.burns[idx] : null;
  } else {
    idx = parseInt(params.get("i"));
    burn = (idx >= 0 && idx < data.burns.length) ? data.burns[idx] : null;
  }
  if (!burn) {
    document.getElementById("content").innerHTML = "<p>Burn not found.</p>";
    return;
  }
  burn.history = historyData[idx] || {};
  const d = burn.days[day] || burn.days[0];

  const pd = (burn.phase_days || [])[day] || {};
  const phase = pd.phase || "?";
  const readiness = pd.readiness || 0;
  const potential = burn.potential || 0;
  const phaseColor = PHASE_COLORS[phase] || "#888";
  const phaseAdvice = {
    EMERGING: "GO NOW — conditions have built up, morels are emerging or about to",
    GROWING: "Go soon — growth accumulating, scout for early ones",
    WAITING: "Not yet — start happened but not enough grow days",
    TOO_EARLY: "No start event detected — conditions haven't triggered",
  };

  const dayNames = ["Sun","Mon","Tue","Wed","Thu","Fri","Sat"];
  const monthNames = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
  function fmtDate(dateStr, i) {
    if (!dateStr) return i === 0 ? "Today" : `+${i}`;
    if (i === 0) return "Today";
    return dayNames[new Date(dateStr + "T12:00:00").getDay()];
  }

  let html = "";

  // ════════════════════════════════════════════════════════════════
  // HEADER
  // ════════════════════════════════════════════════════════════════
  html += `<h1>${burn.name}</h1>`;
  html += `<div class="meta">`;
  html += `${(burn.acres||0).toFixed(0)}ac | ${burn.burn_type} | ${burn.elevation_ft?.toFixed(0)||"?"}ft`;
  html += ` | <a href="https://www.google.com/maps?q=${burn.lat},${burn.lon}" target="_blank">Google Maps</a>`;
  html += ` | Algo ${data.algo_version} | Run ${data.run_date}`;
  html += `</div>`;

  // ════════════════════════════════════════════════════════════════
  // PHASE HERO + DAY SELECTOR
  // ════════════════════════════════════════════════════════════════
  html += `<div style="display:flex;gap:16px;align-items:center;padding:12px 16px;background:${phaseColor}15;border-left:4px solid ${phaseColor};border-radius:0 8px 8px 0;">`;
  html += `<div>`;
  html += `<div style="font-size:28px;font-weight:bold;color:${phaseColor};">${phase}</div>`;
  html += `<div style="font-size:11px;color:#888;max-width:280px;">${phaseAdvice[phase] || ""}</div>`;
  html += `</div>`;
  html += `<div style="margin-left:auto;display:flex;gap:20px;align-items:center;">`;
  html += `<div style="text-align:center;"><div style="font-size:11px;color:#888;">Potential</div><div style="font-size:24px;font-weight:bold;color:#53a8b6;">${potential}<span style="font-size:11px;color:#666;">/100</span></div></div>`;
  html += `<div style="text-align:center;"><div style="font-size:11px;color:#888;">Readiness</div><div style="font-size:24px;font-weight:bold;color:${phaseColor};">${readiness}<span style="font-size:11px;color:#666;">/100</span></div></div>`;
  html += `<div style="text-align:center;font-size:11px;color:#888;line-height:1.6;">${pd.grow_days || 0} grow<br>${pd.start_days || 0} start</div>`;
  html += `</div></div>`;

  // 8-day forecast — selectable, replaces both old day selector and forecast section
  if (burn.phase_days && burn.phase_days.length > 0) {
    html += `<div style="display:flex;gap:3px;margin-top:4px;">`;
    for (let i = 0; i < burn.phase_days.length; i++) {
      const pd2 = burn.phase_days[i];
      const pc = PHASE_COLORS[pd2.phase] || "#888";
      const sel = i === day;
      html += `<a href="?site=${burn.slug}&day=${i}" style="flex:1;padding:6px 2px;text-align:center;background:${sel ? pc+'30' : '#16213e'};color:${sel ? 'white' : '#888'};border:1px solid ${sel ? pc : '#0f3460'};border-top:${sel ? '2px solid '+pc : 'none'};border-radius:0 0 6px 6px;text-decoration:none;cursor:pointer;">`;
      html += `<div style="font-size:10px;color:${sel ? '#ccc' : '#666'};">${fmtDate(burn.days[i]?.date, i)}</div>`;
      html += `<div style="font-size:16px;font-weight:bold;color:${pc};">${pd2.readiness}</div>`;
      html += `<div style="font-size:9px;color:${sel ? '#ccc' : pc};text-transform:lowercase;">${pd2.phase}</div>`;
      html += `<div style="font-size:9px;color:#666;">${pd2.grow_days}g ${pd2.start_days || 0}s</div>`;
      html += `</a>`;
    }
    html += `</div>`;
  }

  // ════════════════════════════════════════════════════════════════
  // SITE — two columns: potential breakdown | site details
  // ════════════════════════════════════════════════════════════════
  html += `<div class="section"><div class="section-title">Site</div>`;
  html += `<div class="two-col">`;

  // Left: potential breakdown
  html += `<div class="card">`;
  html += `<h3>Potential Breakdown</h3>`;
  const potScores = burn.potential_scores || {};
  const potFactors = [
    { key: "burn_quality", label: "Burn Quality", max: 40, color: "#f39c12" },
    { key: "vegetation", label: "Vegetation", max: 15, color: "#00de00" },
    { key: "elevation", label: "Elevation", max: 15, color: "#3498db" },
    { key: "aspect", label: "Aspect", max: 10, color: "#27ae60" },
    { key: "season", label: "Season", max: 10, color: "#e67e22" },
    { key: "freeze_damage", label: "Freeze", max: 10, color: "#9b59b6" },
  ];
  for (const f of potFactors) {
    const v = potScores[f.key] || 0;
    const pct = (v / f.max) * 100;
    html += `<div style="display:flex;align-items:center;gap:6px;margin:4px 0;font-size:11px;">`;
    html += `<div style="width:75px;color:#aaa;text-align:right;">${f.label}</div>`;
    html += `<div style="flex:1;height:10px;background:#0f3460;border-radius:3px;overflow:hidden;">`;
    html += `<div style="height:100%;width:${pct}%;background:${f.color};border-radius:3px;"></div></div>`;
    html += `<div style="width:36px;font-weight:bold;color:${v >= f.max * 0.7 ? f.color : '#666'};">${v}/${f.max}</div>`;
    html += `</div>`;
  }
  html += `</div>`;

  // Right: site details
  html += `<div class="card">`;
  html += `<h3>Site Details</h3>`;

  // Vegetation
  const evtName = burn.evt_name;
  if (evtName) {
    const evtColor = EVT_COLORS[evtName] || "#444";
    let suitLabel = "";
    for (const [key, val] of Object.entries(EVT_SUIT)) {
      if (evtName.includes(key)) { suitLabel = val; break; }
    }
    html += `<div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;padding-bottom:8px;border-bottom:1px solid #0f3460;">`;
    html += `<div style="width:12px;height:12px;border-radius:50%;background:${evtColor};flex-shrink:0;"></div>`;
    html += `<div style="flex:1;font-size:11px;"><div style="color:#ccc;">${evtName}</div>`;
    if (suitLabel) html += `<div style="color:#888;font-size:10px;">${suitLabel}</div>`;
    html += `</div></div>`;
  }

  // Detail items
  const siteTips = {
    burn_age: "Months since burn. Prime: 3-8mo. Second season (9-14mo) still good. >30mo = done.",
    burn_type: "Machine pile > wildfire > hand pile > underburn for morels.",
    burn_acres: "Larger burns = more area to search, but morels cluster in hotspots.",
    elevation: "Fruiting band moves uphill through the season (~300ft/month).",
    aspect: "South-facing warms first (April). North-facing comes on last (June+).",
    slope: "5-15 deg ideal. Flat = poor drainage. Steep = thin soil.",
    ideal_band: "Whether this elevation is in the current seasonal fruiting band.",
    in_season: "Morel season is April through July in the Tahoe Basin.",
  };
  html += `<div class="details-grid">`;
  const siteDetails = [
    ["burn_age", "Burn Age"], ["burn_type", "Type"], ["burn_acres", "Size"],
    ["elevation", "Elevation"], ["aspect", "Aspect"], ["slope", "Slope"],
    ["ideal_band", "Ideal Band"], ["in_season", "Season"],
  ];
  for (const [key, label] of siteDetails) {
    if (d[key] != null) {
      const tip = siteTips[key] ? ` title="${siteTips[key]}"` : "";
      html += `<div class="detail-item"${tip} style="cursor:${tip ? 'help' : 'default'}"><div class="label">${label}</div><div class="value">${d[key]}</div></div>`;
    }
  }
  html += `</div>`;
  html += `</div>`; // end right card

  html += `</div></div>`; // end two-col, end section

  // ════════════════════════════════════════════════════════════════
  // CONDITIONS — timeline, forecast, weather charts
  // ════════════════════════════════════════════════════════════════
  html += `<div class="section"><div class="section-title">Conditions</div>`;

  // Current conditions row (for selected day)
  const tooltips = {
    soil_temp: "Soil temperature at 0-7cm depth. Morels need 43-58F. From Open-Meteo.",
    d_soil_gdd: "Growing Degree Days — cumulative warmth above 32F. Literature: 365-580 GDD predicts onset.",
    snow_status: "Snow cover status. 'Recently melted' is ideal — provides moisture as soil warms.",
    precip_14d: "Total precipitation in the last 14 days. Rain events >0.4in are most significant.",
    rain_events: "Count of rain events >0.4in in the last 30 days. More events = better sustained moisture.",
  };
  html += `<div class="details-grid" style="margin-bottom:12px;">`;
  const wxDetails = [
    ["soil_temp", "Soil Temp"], ["d_soil_gdd", "Soil GDD"], ["snow_status", "Snow"],
    ["precip_14d", "Precip (14d)"], ["rain_events", "Rain Events"],
  ];
  for (const [key, label] of wxDetails) {
    if (d[key] != null) {
      const tip = tooltips[key] ? ` title="${tooltips[key]}"` : "";
      html += `<div class="detail-item"${tip} style="cursor:${tip ? 'help' : 'default'}"><div class="label">${label}</div><div class="value">${d[key]}</div></div>`;
    }
  }
  html += `</div>`;

  // 44-day timeline strip with day-of-week labels
  const tl = burn.timeline || [];
  const tlReasons = burn.timeline_reasons || [];
  if (tl.length > 0) {
    const statusColors = { START: "#27ae60", START_GROW: "#2ecc71", GROW: "#3498db", BAD: "#e74c3c" };
    html += `<div class="card">`;
    html += `<h3>44-Day Timeline — <span style="color:#27ae60">START</span> <span style="color:#3498db">GROW</span> <span style="color:#e74c3c">BAD</span> <span style="color:#666;font-weight:normal;font-size:10px;margin-left:6px;">hover a day for why</span></h3>`;
    html += `<div class="tl-strip" id="tl-strip">`;
    const tlRunDate = new Date(data.run_date + "T12:00:00");
    for (let i = 0; i < tl.length; i++) {
      const c = statusColors[tl[i]] || "#333";
      const isToday = i === 30;
      const border = isToday ? "outline:2px solid #e94560;" : "";
      html += `<div class="tl-cell" data-i="${i}" style="background:${c};${border}"></div>`;
    }
    html += `</div>`;
    // Day-of-week labels at weekly intervals
    html += `<div style="display:flex;font-size:8px;color:#555;margin-top:2px;">`;
    for (let i = 0; i < tl.length; i++) {
      const tlDate = new Date(tlRunDate);
      tlDate.setDate(tlDate.getDate() + (i - 30));
      const isMonday = tlDate.getDay() === 1;
      const isToday = i === 30;
      if (isToday) {
        html += `<div style="flex:1;text-align:center;color:#e94560;font-weight:bold;">today</div>`;
      } else if (isMonday) {
        html += `<div style="flex:1;text-align:center;">${monthNames[tlDate.getMonth()]} ${tlDate.getDate()}</div>`;
      } else {
        html += `<div style="flex:1;"></div>`;
      }
    }
    html += `</div></div>`;
  }

  // Weather charts (initialized after innerHTML)
  const h = burn.history || {};
  const HIST_DAYS = 30, FC_DAYS = 14, TODAY_IDX = 30;
  const totalDays = HIST_DAYS + FC_DAYS;
  const labels = [];      // sparse labels for x-axis ticks
  const fullLabels = [];  // full labels for every bar (used in tooltips)
  const runDate = new Date(data.run_date + "T12:00:00");
  for (let i = 0; i < totalDays; i++) {
    const dt = new Date(runDate);
    dt.setDate(dt.getDate() + (i - HIST_DAYS));
    const mon = monthNames[dt.getMonth()];
    const dayStr = `${dayNames[dt.getDay()]} ${mon} ${dt.getDate()}`;
    fullLabels.push(i === HIST_DAYS ? `TODAY — ${dayStr}` : dayStr);
    if (i === HIST_DAYS) labels.push("TODAY");
    else if (i % 7 === 0 || i === totalDays - 1) labels.push(`${mon} ${dt.getDate()}`);
    else labels.push("");
  }

  html += `<div class="card" style="margin-top:8px;"><canvas id="weatherChart"></canvas></div>`;
  html += `<div class="card" style="margin-top:8px;height:250px;"><canvas id="warmingChart"></canvas></div>`;
  html += `<div class="card" style="margin-top:8px;height:250px;"><canvas id="readinessChart"></canvas></div>`;

  html += `</div>`; // end conditions section

  // ════════════════════════════════════════════════════════════════
  // SCOUTING TIPS
  // ════════════════════════════════════════════════════════════════
  const siteSlope = burn.slope || null;
  const siteAspect = burn.aspect != null ? burn.aspect : null;
  const curMonth = new Date().getMonth() + 1;
  const siteElev = burn.elevation_ft || 0;
  const tips = [];

  if (siteSlope != null) {
    if (siteSlope < 5) tips.push("Flat terrain — focus on raised areas or edges with better drainage. Avoid low spots that pool water.");
    else if (siteSlope <= 15) tips.push("Ideal slope range (5-15 deg). Good drainage + sun exposure. Search the full slope face.");
    else if (siteSlope <= 25) tips.push("Moderate-steep slope. Focus on benches and where the grade eases — morels cluster where debris collects.");
    else tips.push("Steep terrain — concentrate on any benches or flat spots. Slope face is likely too thin-soiled.");
  }

  if (siteAspect != null) {
    const isSouth = siteAspect >= 135 && siteAspect <= 225;
    const isEastWest = (siteAspect >= 45 && siteAspect < 135) || (siteAspect > 225 && siteAspect <= 315);
    if (curMonth <= 4) {
      if (isSouth) tips.push("South-facing in April — prime timing. Soil warms first here. Start at the bottom and work up.");
      else if (isEastWest) tips.push("East/west in April — look for south-facing micro-features (small ridges, sun-exposed cuts).");
      else tips.push("North-facing in April — likely still too cold. Check back in May, or find south-facing pockets.");
    } else if (curMonth === 5) {
      if (isSouth) tips.push("South in May — peak window. Low-elevation south faces may already be drying out. Check shaded edges.");
      else if (isEastWest) tips.push("East/west in May — warming up now. Focus on morning-sun (east) faces first.");
      else tips.push("North in May — just starting. These are the second wave. Good time to scout.");
    } else {
      if (isSouth) tips.push("South in June+ — past peak at lower elevations. Move uphill or look for stragglers in shade.");
      else if (isEastWest) tips.push("East/west in June+ — still producing at higher elevations. Look in shaded draws and near logs.");
      else tips.push("North in June+ — the late-season sweet spot. North aspects come on last and hold moisture longest.");
    }
  }

  const bType = (burn.burn_type || "").toLowerCase();
  if (bType.includes("machine pile")) {
    tips.push("Machine pile — look for distinct pile scars (blackened circles 3-10ft). Morels cluster within 1-5m of each. Walk pile to pile.");
  } else if (bType.includes("hand pile")) {
    tips.push("Hand pile — smaller, more numerous scars. Walk a grid. Check edges where ash meets unburned duff.");
  } else if (bType.includes("underburn")) {
    tips.push("Underburn — generally low severity. Focus on hotspots around stumps, root wads, downed logs. Skip intact duff.");
  } else if (bType.includes("wildfire")) {
    tips.push("Wildfire — focus on moderate burn: dead standing trees but not moonscaped. Avoid unburned patches and scorched zones.");
  }

  if (siteElev > 7000 && curMonth <= 5) tips.push("High elevation (>7000ft) — snowmelt may still be in progress. Return when soil has had 2-3 weeks to warm.");
  else if (siteElev < 5000 && curMonth >= 6) tips.push("Low elevation (<5000ft) in summer — may be too hot and dry. Season could be over here.");

  if (tips.length > 0) {
    html += `<div class="section"><div class="section-title">Scouting Tips</div>`;
    html += `<div class="card" style="border-left:4px solid #53a8b6;border-radius:0 8px 8px 0;">`;
    for (const tip of tips) {
      html += `<div style="font-size:12px;color:#bbb;margin:5px 0;line-height:1.5;">&#x2022; ${tip}</div>`;
    }
    html += `</div></div>`;
  }

  // ════════════════════════════════════════════════════════════════
  // RENDER + CHARTS
  // ════════════════════════════════════════════════════════════════
  document.getElementById("content").innerHTML = html;

  // Timeline floating tooltip — hover a day to see why it's START / GROW / BAD
  (function wireTimelinePop() {
    const strip = document.getElementById("tl-strip");
    if (!strip || !tl.length) return;

    const pop = document.createElement("div");
    pop.className = "tl-pop";
    pop.innerHTML = `<div class="tt-date"></div><div class="tt-status"></div><div class="tt-reason"></div><div class="tt-stats"></div>`;
    document.body.appendChild(pop);
    const elDate = pop.querySelector(".tt-date");
    const elStatus = pop.querySelector(".tt-status");
    const elReason = pop.querySelector(".tt-reason");
    const elStats = pop.querySelector(".tt-stats");

    const STATUS_COLOR = { START: "#27ae60", START_GROW: "#2ecc71", GROW: "#3498db", BAD: "#e74c3c" };
    const histSoil = (burn.history && burn.history.hist_soil_temp) || [];
    const fcSoil = (burn.history && burn.history.forecast_soil_temp) || [];
    const histPrecip = (burn.history && burn.history.hist_precip) || [];
    const fcSnow = (burn.history && burn.history.forecast_snow_depth) || [];
    const readyTL = burn.readiness_timeline || [];
    const popRunDate = new Date(data.run_date + "T12:00:00");

    function fill(cell) {
      const i = parseInt(cell.dataset.i);
      if (isNaN(i)) return;
      const dt = new Date(popRunDate);
      dt.setDate(dt.getDate() + (i - 30));
      const dateLabel = `${dayNames[dt.getDay()]}, ${monthNames[dt.getMonth()]} ${dt.getDate()}`;
      const isToday = i === 30, isFuture = i > 30;
      const tag = isToday ? ` <span style="color:#e94560;">(today)</span>`
                : isFuture ? ` <span style="color:#888;">(forecast)</span>`
                : ` <span style="color:#888;">(${30 - i}d ago)</span>`;
      const status = tl[i];
      const reason = tlReasons[i] || "";
      const soil = i < 30 ? histSoil[i] : fcSoil[i - 30];
      const precip = i < 30 ? histPrecip[i] : null;
      const snow = i >= 30 ? fcSnow[i - 30] : null;
      const ready = readyTL[i];

      elDate.innerHTML = dateLabel + tag;
      elStatus.textContent = status;
      elStatus.style.color = STATUS_COLOR[status] || "#888";
      elReason.textContent = reason;
      elReason.style.display = reason ? "block" : "none";

      const stats = [];
      if (soil != null) stats.push(["Soil", `${soil.toFixed(0)}F`]);
      if (ready != null) stats.push(["Readiness", `${ready}`]);
      if (precip != null) stats.push(["Rain", precip > 0 ? `${precip.toFixed(2)}in` : "—"]);
      if (snow != null && snow > 0) stats.push(["Snow", `${snow.toFixed(1)}in`]);
      elStats.innerHTML = stats.map(([k, v]) => `<div>${k} <b>${v}</b></div>`).join("");
    }
    function place(ev) {
      const pad = 10, w = pop.offsetWidth, hgt = pop.offsetHeight;
      let x = ev.clientX + 14, y = ev.clientY + 14;
      if (x + w + pad > window.innerWidth) x = ev.clientX - w - 14;
      if (y + hgt + pad > window.innerHeight) y = ev.clientY - hgt - 14;
      pop.style.left = Math.max(pad, x) + "px";
      pop.style.top = Math.max(pad, y) + "px";
    }
    strip.addEventListener("mouseover", (ev) => {
      const cell = ev.target.closest(".tl-cell");
      if (!cell) return;
      fill(cell);
      pop.classList.add("open");
      place(ev);
    });
    strip.addEventListener("mousemove", (ev) => {
      if (!pop.classList.contains("open")) return;
      const cell = ev.target.closest(".tl-cell");
      if (cell) fill(cell);
      place(ev);
    });
    strip.addEventListener("mouseleave", () => pop.classList.remove("open"));
  })();

  // Chart.js — weather
  const soilHist = h.hist_soil_temp || [];
  const soilFc = h.forecast_soil_temp || [];
  const airHist = h.hist_temps_max || [];
  const airFc = h.forecast_temps_max || [];
  const soilAll = [...soilHist, ...new Array(Math.max(0, HIST_DAYS - soilHist.length)).fill(null), ...soilFc];
  const airAll = [...airHist, ...new Array(Math.max(0, HIST_DAYS - airHist.length)).fill(null), ...airFc];

  const precip = h.hist_precip || [];
  const snowAll2 = h.forecast_snow_depth || [];
  const precipFull = [...precip, ...new Array(FC_DAYS).fill(null)];
  const snowPad = new Array(HIST_DAYS - 7).fill(null);
  const snowFull = [...snowPad, ...snowAll2, ...new Array(Math.max(0, totalDays - snowPad.length - snowAll2.length)).fill(null)];

  let warmingRate = null;
  if (soilAll.filter(v => v != null).length >= 14) {
    warmingRate = soilAll.map((v, i) => {
      if (i < 7) return null;
      let recent = [], prior = [];
      for (let j = i - 6; j <= i; j++) { if (soilAll[j] != null) recent.push(soilAll[j]); }
      for (let j = i - 13; j <= i - 7; j++) { if (j >= 0 && soilAll[j] != null) prior.push(soilAll[j]); }
      if (recent.length < 3 || prior.length < 3) return null;
      return +((recent.reduce((a,b)=>a+b,0)/recent.length - prior.reduce((a,b)=>a+b,0)/prior.length) / 7).toFixed(2);
    });
  }

  const wxCtx = document.getElementById("weatherChart");
  if (wxCtx) {
    const datasets = [];
    if (soilAll.some(v=>v!=null)) datasets.push({
      type: "line", label: "Soil Temp (F)", data: soilAll,
      borderColor: "#8B5E3C", borderWidth: 2.5, pointRadius: 0, tension: 0.3,
      fill: false, yAxisID: "yTemp",
    });
    if (airAll.some(v=>v!=null)) datasets.push({
      type: "line", label: "Air High (F)", data: airAll,
      borderColor: "#9b59b6", borderWidth: 1.5, pointRadius: 0, tension: 0.3,
      fill: false, borderDash: [4, 2], yAxisID: "yTemp",
    });
    if (precip.some(v=>v>0)) datasets.push({
      type: "bar", label: "Rain (in)", data: precipFull.map(v => v > 0 ? v : null),
      backgroundColor: "#5bc0de", borderRadius: 2, barPercentage: 0.7,
      yAxisID: "yMoist", order: 10,
    });
    if (snowAll2.some(v=>v>0)) datasets.push({
      type: "bar", label: "Snow Depth (in)", data: snowFull.map(v => v > 0 ? v : null),
      backgroundColor: "rgba(255,255,255,0.3)", borderColor: "rgba(255,255,255,0.5)",
      borderWidth: 1, borderRadius: 2, barPercentage: 0.9,
      yAxisID: "yMoist", order: 11,
    });
    new Chart(wxCtx, {
      data: { labels, datasets },
      options: {
        responsive: true,
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: { labels: { color: "#aaa", font: { size: 11 } } },
          title: { display: true, text: "Weather — 30-day history + 7-day forecast", color: "#aaa", font: { size: 13 } },
          tooltip: { callbacks: { title: (items) => items.length ? fullLabels[items[0].dataIndex] || "" : "" } },
        },
        scales: {
          x: { ticks: { color: "#666", font: { size: 9 }, maxRotation: 0 }, grid: { color: "#0f3460" } },
          yTemp: { type: "linear", position: "left", title: { display: true, text: "Temperature (F)", color: "#8B5E3C" }, ticks: { color: "#888" }, grid: { color: "#0f3460" } },
          yMoist: { type: "linear", position: "right", title: { display: true, text: "Precip / Snow (in)", color: "#5bc0de" }, ticks: { color: "#888" }, grid: { drawOnChartArea: false }, min: 0, max: Math.max(3, ...precipFull.filter(v=>v!=null), ...snowFull.filter(v=>v!=null)) },
        },
      },
    });
  }

  const warmCtx = document.getElementById("warmingChart");
  if (warmCtx && warmingRate && warmingRate.some(v => v != null)) {
    const barColors = warmingRate.map(v =>
      v == null ? "transparent" : v >= 0 ? "rgba(233,69,96,0.8)" : "rgba(52,152,219,0.8)"
    );
    new Chart(warmCtx, {
      type: "bar",
      data: { labels, datasets: [{ label: "F/day", data: warmingRate, backgroundColor: barColors, borderRadius: 2, barPercentage: 0.9 }] },
      options: {
        responsive: true, maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        plugins: { legend: { display: false }, title: { display: true, text: "Soil Warming Rate (F/day) — red = warming, blue = cooling", color: "#888", font: { size: 11 } }, tooltip: { callbacks: { title: (items) => items.length ? fullLabels[items[0].dataIndex] || "" : "" } } },
        scales: {
          x: { ticks: { color: "#666", font: { size: 8 }, maxRotation: 0 }, grid: { color: "#0f3460" } },
          y: { ticks: { color: "#888", font: { size: 9 } }, grid: { color: "#0f3460" }, min: -3, max: 3 },
        },
      },
    });
  }

  // Readiness chart — ratcheted readiness vs raw vs days harvestable
  const readyCtx = document.getElementById("readinessChart");
  const readyTL = burn.readiness_timeline || [];
  const rawReadyTL = burn.raw_readiness_timeline || [];
  const harvestTL = burn.days_harvestable_timeline || [];
  if (readyCtx && readyTL.length) {
    new Chart(readyCtx, {
      data: {
        labels,
        datasets: [
          {
            type: "line", label: "Readiness (anti-whiplash)", data: readyTL,
            borderColor: "#e94560", backgroundColor: "rgba(233,69,96,0.15)",
            fill: true, tension: 0.3, pointRadius: 0, borderWidth: 2, yAxisID: "yScore",
          },
          {
            type: "line", label: "Raw readiness", data: rawReadyTL,
            borderColor: "#888", borderDash: [4, 3], borderWidth: 1.5,
            fill: false, tension: 0.3, pointRadius: 0, yAxisID: "yScore",
          },
          {
            type: "bar", label: "Days harvestable", data: harvestTL,
            backgroundColor: "rgba(243,156,18,0.5)", borderRadius: 2,
            barPercentage: 0.9, yAxisID: "yDays", order: 10,
          },
        ],
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: { labels: { color: "#aaa", font: { size: 11 } } },
          title: { display: true, text: "Readiness over time — anti-whiplash floor + days harvestable", color: "#888", font: { size: 11 } },
          tooltip: { callbacks: { title: (items) => items.length ? fullLabels[items[0].dataIndex] || "" : "" } },
        },
        scales: {
          x: { ticks: { color: "#666", font: { size: 8 }, maxRotation: 0 }, grid: { color: "#0f3460" } },
          yScore: { type: "linear", position: "left", title: { display: true, text: "Readiness (0-100)", color: "#e94560" }, ticks: { color: "#888" }, grid: { color: "#0f3460" }, min: 0, max: 100 },
          yDays: { type: "linear", position: "right", title: { display: true, text: "Days harvestable", color: "#f39c12" }, ticks: { color: "#888" }, grid: { drawOnChartArea: false }, min: 0 },
        },
      },
    });
  }
}

document.addEventListener("DOMContentLoaded", init);
