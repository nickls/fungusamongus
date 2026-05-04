"""
Field validator: runs the current model against ground-truth field reports.

For each report in data/field_reports.json with a site_slug, reconstructs
the weather state on the report date (using cached history.json) and asks
the current model what it would have predicted. Then asserts agreement
with the field outcome:

  - "positive" / "positive but weak" / "positive (reduced)":
        model must NOT say TOO_EARLY, and readiness must be >= 30
  - "negative":
        model SHOULD NOT say EMERGING, readiness must be <= 60
  - "MODEL FAILED": informational — these documented past failures.
        We assert the current model now passes them.

Run after every algo change:
    python -m utils.validate_field

Exit code is non-zero if any anchor disagrees, so this slots into CI / a
pre-commit hook later.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

from phase_scoring import build_timeline, classify_phase, extract_features, score_readiness
from config import MUSHROOM_TYPES


def reconstruct_weather(history_entry):
    return {
        "hist_soil_temp": history_entry.get("hist_soil_temp", []),
        "forecast_soil_temp": history_entry.get("forecast_soil_temp", []),
        "hist_precip": history_entry.get("hist_precip", []),
        "forecast_snow_depth": history_entry.get("forecast_snow_depth", []),
    }


def evaluate_report(report, sites_by_slug, hist, run_date, config):
    """Return (status, message). status ∈ {'PASS', 'FAIL', 'SKIP', 'INFO'}."""
    slug = report.get("site_slug")
    if not slug:
        return "SKIP", "no site_slug"
    if slug not in sites_by_slug:
        return "SKIP", f"site '{slug}' not in current catalog"

    idx, burn = sites_by_slug[slug]
    weather = reconstruct_weather(hist[idx])
    # Re-classify the timeline using CURRENT config — this is the whole
    # point: validate the current model against past observations, not the
    # cached labels from whichever version generated the snapshot.
    timeline, _ = build_timeline(weather, config)

    # Map report date to a target_day index in the 44-day window.
    # run_date is the day of the latest.json snapshot. target_day = 30 means
    # "today as of run_date". Earlier reports map to lower target_day indices.
    report_date = datetime.strptime(report["date"], "%Y-%m-%d")
    days_offset = (report_date - run_date).days
    target_day = 30 + days_offset
    if target_day < 0 or target_day >= len(timeline):
        return "SKIP", f"date {report['date']} outside 44-day window from {run_date.date()}"

    feats = extract_features(timeline, weather, target_day, config)
    readiness = score_readiness(feats, config)
    phase = classify_phase(feats, config)

    outcome = (report.get("model_validation", {}).get("outcome") or "").lower()
    found = report.get("morels_found", "?")

    summary = f"{report['id']:7s} {report['site'][:32]:32s} {report['date']}  →  phase={phase:9s} readiness={readiness:>3d}  (found: {found})"

    # Assertions per outcome category. Check "failed" first because the
    # phrase "false negative" contains the substring "negative".
    if "failed" in outcome or "false negative" in outcome:
        # Past documented failure — celebrate when we no longer fail it
        if phase != "TOO_EARLY" and readiness >= 30:
            return "PASS", f"{summary}  ✓ recovered from past failure"
        return "FAIL", f"{summary}  ✗ STILL fails this case"
    if "positive" in outcome:
        # Strong vs weak positive — weak/reduced harvests get a lower bar.
        # "Weak" = older site, smaller mushrooms, drier conditions, etc.
        is_weak = "weak" in outcome or "reduced" in outcome
        min_readiness = 15 if is_weak else 40
        if phase == "TOO_EARLY":
            return "FAIL", f"{summary}  ✗ predicted TOO_EARLY but field PRODUCED"
        if readiness < min_readiness:
            return "FAIL", f"{summary}  ✗ readiness {readiness} below {min_readiness} for {'weak ' if is_weak else ''}positive"
        return "PASS", summary
    if "negative" in outcome:
        # Model should not declare EMERGING for a confirmed negative
        if phase == "EMERGING" or readiness >= 60:
            return "FAIL", f"{summary}  ✗ predicted ready but field was NEGATIVE"
        return "PASS", summary

    return "INFO", summary


def load_catalog(species):
    """Return (data, history, run_date) for the given species, or (None, None, None)."""
    base = Path("docs/data")
    data_path = base / f"{species}-latest.json"
    hist_path = base / f"{species}-history.json"
    if not data_path.exists() and species == "morel":
        # legacy filenames (back-compat for the morel run)
        data_path = base / "latest.json"
        hist_path = base / "history.json"
    if not data_path.exists():
        return None, None, None
    data = json.loads(data_path.read_text())
    hist = json.loads(hist_path.read_text()) if hist_path.exists() else []
    run_date = datetime.strptime(data["run_date"], "%Y-%m-%d")
    return data, hist, run_date


def main():
    reports = json.loads(Path("data/field_reports.json").read_text())

    # Group by mushroom_type (default "morel" for legacy reports)
    by_species = {}
    for r in reports:
        sp = r.get("mushroom_type", "morel")
        by_species.setdefault(sp, []).append(r)

    counts = {"PASS": 0, "FAIL": 0, "SKIP": 0, "INFO": 0}

    for species, sp_reports in by_species.items():
        if species not in MUSHROOM_TYPES:
            print(f"ERROR: unknown mushroom_type '{species}' in field reports", file=sys.stderr)
            sys.exit(2)

        data, hist, run_date = load_catalog(species)
        if data is None:
            print(f"  · {species}: no catalog at docs/data/{species}-latest.json — "
                  f"run morel_finder.py --mushroom-type={species} first")
            counts["SKIP"] += len(sp_reports)
            continue

        config = MUSHROOM_TYPES[species]
        sites_by_slug = {b["slug"]: (i, b) for i, b in enumerate(data["burns"])}

        print(f"FIELD VALIDATION ({species}) — model {data['algo_version']} vs {len(sp_reports)} reports")
        print(f"  Catalog snapshot: {data['run_date']}")

        for r in sp_reports:
            status, msg = evaluate_report(r, sites_by_slug, hist, run_date, config)
            counts[status] += 1
            marker = {"PASS": "✓", "FAIL": "✗", "SKIP": "·", "INFO": "·"}[status]
            print(f"  {marker} {msg}")
        print()

    print(f"Summary: {counts['PASS']} pass, {counts['FAIL']} fail, "
          f"{counts['SKIP']} skip, {counts['INFO']} info")

    if counts["FAIL"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
