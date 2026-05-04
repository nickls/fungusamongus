// Map-marker popup HTML. Globals it relies on: speciesConfig, selectedDay, data.

function makePopup(burn, day, burnIdx) {
  const pd = (burn.phase_days || [])[selectedDay] || {};
  const phase = pd.phase || "?";
  const readiness = pd.readiness || 0;
  const potential = burn.potential || 0;
  const phaseColors = { EMERGING: "#27ae60", GROWING: "#f39c12", WAITING: "#e67e22", TOO_EARLY: "#95a5a6" };
  const phaseColor = phaseColors[phase] || "#888";

  // Header — name links to detail page
  let html = `<div class="burn-popup" style="min-width:280px;max-width:340px;">`;
  const species = data.mushroom_type || "morel";
  const typeQS = species === "morel" ? "" : `&type=${species}`;
  html += `<h3 style="margin:0 0 4px;"><a href="detail.html?site=${burn.slug}&day=${selectedDay}${typeQS}" style="color:inherit;text-decoration:underline;" target="_blank">${burn.name}</a></h3>`;
  html += `<div style="font-size:11px;color:#888;margin-bottom:6px;">`;
  // Header strip: burn-specific for morel, vegetation-specific for porcini
  const headerBits = [];
  if (speciesConfig.showBurnType) {
    headerBits.push(`${(burn.acres||0).toFixed(0)}ac`);
    if (burn.burn_type) headerBits.push(burn.burn_type);
  }
  if (burn.elevation_ft) headerBits.push(`${burn.elevation_ft.toFixed(0)}ft`);
  if (burn.slope != null) headerBits.push(`${burn.slope.toFixed(0)}° ${aspectDir(burn.aspect)}`);
  html += headerBits.join(" | ");
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
  // Soil + (burn age | "primed?") depending on species
  const ageBit = speciesConfig.showBurnType ? `Age: ${day.burn_age || "?"}` : "";
  html += `Soil: ${day.soil_temp || "?"}${ageBit ? " | " + ageBit : ""}<br>`;
  if (day.snow_status) html += `${day.snow_status}`;
  html += `</div>`;
  html += `</div>`;

  // Key details — compact
  html += `<div style="margin-top:8px;font-size:11px;color:#888;line-height:1.6;">`;
  const show = speciesConfig.showBurnType ? ["snow_status", "burn_age"] : ["snow_status"];
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
  const dirs = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"];
  return dirs[Math.floor(((deg + 22.5) % 360) / 45)];
}
