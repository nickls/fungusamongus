// Smoke test for docs/detail.js — runs init() against real data with a
// minimal DOM stub. Catches the "blank page" class of bugs (runtime
// errors, broken scope, missing data) without spinning up a browser.
//
// Run: node test_detail.mjs

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), "docs");
const latest = JSON.parse(fs.readFileSync(path.join(ROOT, "data/latest.json"), "utf8"));
const SLUG = latest.burns[0].slug;

let renderedHTML = "";
const appendedNodes = [];
const errors = [];

function makeNode(tag = "div") {
  return {
    tagName: tag.toUpperCase(),
    _innerHTML: "",
    style: {},
    classList: {
      _set: new Set(),
      add(c) { this._set.add(c); },
      remove(c) { this._set.delete(c); },
      contains(c) { return this._set.has(c); },
    },
    dataset: {},
    children: [],
    set innerHTML(v) {
      this._innerHTML = v;
      if (this._id === "content") renderedHTML = v;
    },
    get innerHTML() { return this._innerHTML; },
    set textContent(v) { this._textContent = v; },
    get textContent() { return this._textContent || ""; },
    set className(v) { this._className = v; },
    get className() { return this._className || ""; },
    appendChild(n) { this.children.push(n); appendedNodes.push(n); },
    addEventListener() {},
    querySelector() { return makeNode("div"); },
    querySelectorAll() { return []; },
    closest() { return null; },
    setAttribute() {},
    get offsetWidth() { return 200; },
    get offsetHeight() { return 100; },
  };
}
const contentNode = makeNode("div");
contentNode._id = "content";

global.document = {
  getElementById(id) {
    if (id === "content") return contentNode;
    if (id === "tl-strip") return makeNode("div");
    if (id === "weatherChart" || id === "warmingChart" || id === "readinessChart") return makeNode("canvas");
    return null;
  },
  createElement: makeNode,
  body: makeNode("body"),
  addEventListener(ev, cb) {
    if (ev === "DOMContentLoaded") global.__init = cb;
  },
};
global.window = { location: { search: `?site=${SLUG}` }, innerWidth: 1200, innerHeight: 800 };
global.URLSearchParams = URLSearchParams;
global.Chart = class { constructor() {} };
global.fetch = async (url) => {
  const filePath = path.join(ROOT, url);
  if (!fs.existsSync(filePath)) {
    return { json: async () => { throw new Error("404: " + url); } };
  }
  const text = fs.readFileSync(filePath, "utf8");
  return { json: async () => JSON.parse(text), text: async () => text };
};

process.on("unhandledRejection", (e) => { errors.push(["unhandledRejection", e]); });
process.on("uncaughtException", (e) => { errors.push(["uncaughtException", e]); });

const code = fs.readFileSync(path.join(ROOT, "detail.js"), "utf8");
try {
  new Function(code)();
} catch (e) {
  console.error("EVAL ERROR:", e);
  process.exit(1);
}

if (typeof global.__init !== "function") {
  console.error("init() never registered on DOMContentLoaded");
  process.exit(1);
}

await global.__init();
await new Promise((r) => setTimeout(r, 200));

if (errors.length) {
  console.error("RUNTIME ERRORS:");
  for (const [type, e] of errors) console.error(`  [${type}]`, e);
  process.exit(1);
}

const sections = ["<h1>", "Potential Breakdown", "Site Details", "44-Day Timeline", "weatherChart", "warmingChart", "readinessChart"];
const missing = sections.filter((s) => !renderedHTML.includes(s));

console.log(`✓ init() ran without errors (slug: ${SLUG})`);
console.log(`✓ rendered ${renderedHTML.length.toLocaleString()} chars into #content`);
console.log(`✓ appended ${appendedNodes.length} nodes (timeline pop)`);
if (missing.length) {
  console.error(`✗ missing sections: ${missing.join(", ")}`);
  process.exit(1);
}
console.log(`✓ all expected sections present`);

// ── Phase A: structural check on per-type JSON outputs ──
// Detail page still loads latest.json (the morel alias). Phase C will switch
// it to per-type loading. For now, just verify the per-type files exist with
// the expected shape if the morel/porcini runs have produced them.
function checkPerTypeJSON(label, file) {
  const p = path.join(ROOT, "data", file);
  if (!fs.existsSync(p)) {
    console.log(`  (${label}: ${file} not generated yet — skip)`);
    return;
  }
  const j = JSON.parse(fs.readFileSync(p, "utf8"));
  const requiredTop = ["run_date", "algo_version", "mushroom_type", "burns"];
  const missingTop = requiredTop.filter((k) => !(k in j));
  if (missingTop.length) {
    console.error(`✗ ${label}: missing top-level fields: ${missingTop.join(", ")}`);
    process.exit(1);
  }
  if (!Array.isArray(j.burns) || j.burns.length === 0) {
    console.error(`✗ ${label}: burns array empty`);
    process.exit(1);
  }
  const b = j.burns[0];
  const requiredBurn = ["slug", "name", "lat", "lon", "potential", "timeline", "phase_days"];
  const missingBurn = requiredBurn.filter((k) => !(k in b));
  if (missingBurn.length) {
    console.error(`✗ ${label}: burn[0] missing fields: ${missingBurn.join(", ")}`);
    process.exit(1);
  }
  if (j.mushroom_type !== label) {
    console.error(`✗ ${label}: mushroom_type=${j.mushroom_type}, expected ${label}`);
    process.exit(1);
  }
  console.log(`✓ ${label}-latest.json shape valid (${j.burns.length} sites, algo ${j.algo_version})`);
}
checkPerTypeJSON("morel", "morel-latest.json");
checkPerTypeJSON("porcini", "porcini-latest.json");
