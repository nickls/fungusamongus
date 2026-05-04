// Sidebar filter UI (sliders + burn-type chips) and matching logic.
// Globals it relies on: FILTERS (from species.js), filters (state object
// owned by app.js), speciesConfig, render() (from app.js), data, selectedDay.

function buildSliders() {
  const group = document.getElementById("slider-group");

  for (const f of FILTERS) {
    const row = makeSlider(f.key, f.label, f.max, f.default || 0, f.tip);
    group.appendChild(row);
  }
  // Burn-type chip row only applies to fire-associated species
  if (speciesConfig.showBurnType) {
    group.appendChild(buildBurnTypeFilter());
  }
}

const BURN_TYPES = ["Machine Pile", "Hand Pile", "Pile Burn", "Underburn", "Broadcast", "RX", "wildfire"];

function setChipActive(chip, active) {
  chip.classList.toggle("active", active);
  chip.style.background = active ? "#0f3460" : "#16213e";
  chip.style.color = active ? "#fff" : "#666";
}

function buildBurnTypeFilter() {
  // Default: "All" selected, no specific types
  filters.burn_types = new Set();

  const row = document.createElement("div");
  row.className = "slider-row";
  row.innerHTML = `<label>Burn Types <span style="font-size:10px;color:#666;">(click to toggle)</span></label>`;

  const tipEl = document.createElement("div");
  tipEl.style.cssText = "font-size:10px;color:#666;margin-top:-1px;margin-bottom:4px;";
  tipEl.textContent = "Show only selected burn types.";
  row.appendChild(tipEl);

  const chipBox = document.createElement("div");
  chipBox.style.cssText = "display:flex;flex-wrap:wrap;gap:4px;";

  // "All" chip — mutually exclusive with the specific-type chips
  const allChip = document.createElement("button");
  allChip.textContent = "All";
  allChip.dataset.type = "__all__";
  allChip.style.cssText = "border:1px solid #53a8b6;border-radius:12px;padding:3px 9px;font-size:10px;cursor:pointer;";
  allChip.classList.add("burn-chip");
  setChipActive(allChip, true);
  allChip.onclick = () => {
    if (allChip.classList.contains("active")) return;  // already on, no-op
    setChipActive(allChip, true);
    filters.burn_types.clear();
    chipBox.querySelectorAll(".burn-chip[data-type]:not([data-type='__all__'])").forEach(c => setChipActive(c, false));
    render();
  };
  chipBox.appendChild(allChip);

  for (const t of BURN_TYPES) {
    const chip = document.createElement("button");
    chip.textContent = t;
    chip.dataset.type = t;
    chip.style.cssText = "border:1px solid #53a8b6;border-radius:12px;padding:3px 9px;font-size:10px;cursor:pointer;";
    chip.classList.add("burn-chip");
    setChipActive(chip, false);
    chip.onclick = () => {
      const active = !chip.classList.contains("active");
      setChipActive(chip, active);
      if (active) {
        filters.burn_types.add(t);
        setChipActive(allChip, false);
      } else {
        filters.burn_types.delete(t);
        if (filters.burn_types.size === 0) setChipActive(allChip, true);
      }
      render();
    };
    chipBox.appendChild(chip);
  }
  row.appendChild(chipBox);
  return row;
}

function matchesBurnType(burn) {
  if (!filters.burn_types || filters.burn_types.size === 0) return true;  // "All" mode
  const t = burn.burn_type || "";
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

  // Reset burn-type chips: only "All" active
  filters.burn_types = new Set();
  document.querySelectorAll(".burn-chip").forEach(chip => {
    setChipActive(chip, chip.dataset.type === "__all__");
  });

  render();
}

function passesFilters(burn, day) {
  const pd0 = (burn.phase_days || [])[selectedDay] || {};
  const potential = burn.potential || 0;
  const readiness0 = pd0.readiness || 0;

  if (potential < (filters.potential || 0)) return false;
  if (readiness0 < (filters.readiness || 0)) return false;

  // Burn age filter (max — hide older than slider value)
  if (filters.burn_age_max != null && burn.burn_age_months != null
      && burn.burn_age_months > filters.burn_age_max) return false;

  // Elevation min/max filters (porcini)
  const elev = burn.elevation_ft;
  if (elev != null) {
    if (filters.elevation_min != null && elev < filters.elevation_min) return false;
    if (filters.elevation_max != null && elev < 9000 && elev > filters.elevation_max) return false;
  }

  // Burn type filter (only applies when species shows burn types)
  if (speciesConfig.showBurnType && !matchesBurnType(burn)) return false;

  // Raw condition filters (from legacy day scores)
  for (const f of FILTERS) {
    const skip = ["potential", "readiness", "burn_age_max", "elevation_min", "elevation_max"];
    if (skip.includes(f.key)) continue;
    if (filters[f.key] && day[f.key] != null && day[f.key] < filters[f.key]) return false;
  }
  return true;
}
