// Smoke test for docs/detail.js — runs init() against real data with a
// minimal DOM stub. Catches the "blank page" class of bugs (runtime
// errors, broken scope, missing data) without spinning up a browser.
//
// Exercises both morel and porcini.
//
// Run: node test_detail.mjs

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), "docs");
const speciesJSCode = fs.readFileSync(path.join(ROOT, "species.js"), "utf8");
const detailJSCode = fs.readFileSync(path.join(ROOT, "detail.js"), "utf8");

function makeNode(tag, ctx) {
  const n = {
    tagName: tag.toUpperCase(),
    _innerHTML: "",
    style: {},
    classList: {
      _set: new Set(),
      add(c) { this._set.add(c); },
      remove(c) { this._set.delete(c); },
      contains(c) { return this._set.has(c); },
      toggle(c, on) { if (on) this._set.add(c); else this._set.delete(c); },
    },
    dataset: {},
    children: [],
    set innerHTML(v) {
      n._innerHTML = v;
      if (n._id === "content") ctx.renderedHTML = v;
    },
    get innerHTML() { return n._innerHTML; },
    set textContent(v) { n._textContent = v; },
    get textContent() { return n._textContent || ""; },
    set className(v) { n._className = v; },
    get className() { return n._className || ""; },
    appendChild(child) { n.children.push(child); ctx.appendedNodes.push(child); },
    addEventListener() {},
    querySelector() { return makeNode("div", ctx); },
    querySelectorAll() { return []; },
    closest() { return null; },
    setAttribute() {},
    get offsetWidth() { return 200; },
    get offsetHeight() { return 100; },
  };
  return n;
}

async function runSmoke(species) {
  // Pick a slug from the matching JSON
  const dataPath = path.join(ROOT, "data", `${species}-latest.json`);
  if (!fs.existsSync(dataPath)) {
    console.log(`  (${species}: ${species}-latest.json not generated yet — skip)`);
    return { skipped: true };
  }
  const data = JSON.parse(fs.readFileSync(dataPath, "utf8"));
  const slug = data.burns[0].slug;
  const search = species === "morel" ? `?site=${slug}` : `?site=${slug}&type=${species}`;

  const ctx = { renderedHTML: "", appendedNodes: [], errors: [] };
  const contentNode = makeNode("div", ctx);
  contentNode._id = "content";

  global.document = {
    getElementById(id) {
      if (id === "content") return contentNode;
      if (id === "tl-strip") return makeNode("div", ctx);
      if (id === "weatherChart" || id === "warmingChart" || id === "readinessChart") {
        return makeNode("canvas", ctx);
      }
      return null;
    },
    createElement: (tag) => makeNode(tag, ctx),
    body: makeNode("body", ctx),
    addEventListener(ev, cb) {
      if (ev === "DOMContentLoaded") global.__init = cb;
    },
    querySelector() { return null; },
    querySelectorAll() { return []; },
  };
  global.window = { location: { search }, innerWidth: 1200, innerHeight: 800 };
  global.URLSearchParams = URLSearchParams;
  global.Chart = class { constructor() {} };
  global.fetch = async (url) => {
    const filePath = path.join(ROOT, url);
    if (!fs.existsSync(filePath)) {
      return { ok: false, status: 404, json: async () => { throw new Error("404: " + url); } };
    }
    const text = fs.readFileSync(filePath, "utf8");
    return { ok: true, status: 200, json: async () => JSON.parse(text), text: async () => text };
  };

  // Load species.js into globals first (it sets SPECIES, getSpeciesFromURL, etc.).
  // We bridge the script's top-level vars into globalThis so detail.js sees them.
  new Function(speciesJSCode + "\nglobalThis.SPECIES = SPECIES;\nglobalThis.SUPPORTED_SPECIES = SUPPORTED_SPECIES;\nglobalThis.FILTER_LIBRARY = FILTER_LIBRARY;\nglobalThis.getSpeciesFromURL = getSpeciesFromURL;\nglobalThis.selectSpecies = selectSpecies;\nglobalThis.prioritScore = prioritScore;")();

  // Re-evaluate detail.js — it registers __init on DOMContentLoaded
  global.__init = null;
  new Function(detailJSCode)();
  if (typeof global.__init !== "function") {
    throw new Error("init() never registered on DOMContentLoaded");
  }

  await global.__init();
  await new Promise((r) => setTimeout(r, 200));

  if (ctx.errors.length) {
    console.error(`✗ ${species}: runtime errors:`, ctx.errors);
    process.exit(1);
  }

  const sections = ["<h1>", "Potential Breakdown", "Site Details", "44-Day Timeline",
                    "weatherChart", "warmingChart", "readinessChart"];
  const missing = sections.filter((s) => !ctx.renderedHTML.includes(s));
  if (missing.length) {
    console.error(`✗ ${species}: missing sections: ${missing.join(", ")}`);
    console.error(`  rendered length: ${ctx.renderedHTML.length}`);
    console.error(`  first 200 chars: ${ctx.renderedHTML.slice(0, 200)}`);
    process.exit(1);
  }

  console.log(`✓ ${species}: init() ran cleanly (slug: ${slug})`);
  console.log(`  rendered ${ctx.renderedHTML.length.toLocaleString()} chars, appended ${ctx.appendedNodes.length} nodes`);
  return { skipped: false, slug, length: ctx.renderedHTML.length };
}

// ── Structural shape check on per-type JSONs ─────────────────────────────

function checkShape(species) {
  const p = path.join(ROOT, "data", `${species}-latest.json`);
  if (!fs.existsSync(p)) {
    console.log(`  (${species}-latest.json not generated yet — skip)`);
    return;
  }
  const j = JSON.parse(fs.readFileSync(p, "utf8"));
  const requiredTop = ["run_date", "algo_version", "mushroom_type", "burns"];
  const missingTop = requiredTop.filter((k) => !(k in j));
  if (missingTop.length) {
    console.error(`✗ ${species}: missing top-level fields: ${missingTop.join(", ")}`);
    process.exit(1);
  }
  if (!Array.isArray(j.burns) || j.burns.length === 0) {
    console.error(`✗ ${species}: burns array empty`);
    process.exit(1);
  }
  const requiredBurn = ["slug", "name", "lat", "lon", "potential", "timeline", "phase_days"];
  const missingBurn = requiredBurn.filter((k) => !(k in j.burns[0]));
  if (missingBurn.length) {
    console.error(`✗ ${species}: burn[0] missing fields: ${missingBurn.join(", ")}`);
    process.exit(1);
  }
  if (j.mushroom_type !== species) {
    console.error(`✗ ${species}: mushroom_type=${j.mushroom_type}`);
    process.exit(1);
  }
  console.log(`✓ ${species}-latest.json shape valid (${j.burns.length} sites, algo ${j.algo_version})`);
}

// Run
process.on("unhandledRejection", (e) => { console.error("unhandled:", e); process.exit(1); });

console.log("== Detail page smoke test ==");
await runSmoke("morel");
await runSmoke("porcini");
console.log("");
console.log("== Per-type JSON shape check ==");
checkShape("morel");
checkShape("porcini");
console.log("");
console.log("All checks passed.");
