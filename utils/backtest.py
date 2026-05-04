"""
Backtest the current scoring model against past dates using the cached
weather timeline. Each burn's timeline in latest.json spans 30 historical
days + 14 forecast = 44 days, with index 30 = today. Shifting target_day
backwards lets us see what the CURRENT model would have computed from
the same weather observations on a past date.

Usage:
    python -m utils.backtest                         # default sites, last 7 days
    python -m utils.backtest --slug unit-2-3-underburn-2025 --slug b-1-underburn-2025
    python -m utils.backtest --days 14               # 14 days of history

Caveat: uses currently-cached weather. Open-Meteo's archive can revise
old data, but soil temps are usually stable. Forecast data isn't
available for past dates — backtest only validates against past
observations, not predictions made from a past forecast.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path

from phase_scoring import extract_features, classify_phase, score_readiness
from config import MUSHROOM_TYPES


DEFAULT_SLUGS = [
    "unit-2-3-underburn-2025",
    "unit-2-6-underburn-2025",
    "waddle-ranch-rx-2024",
    "b-1-underburn-2025",
    "independence-9-machine-pile-2024",
]


def reconstruct_weather(history_entry):
    """Pull the weather arrays back out of history.json into the shape
    extract_features expects."""
    return {
        "hist_soil_temp": history_entry.get("hist_soil_temp", []),
        "forecast_soil_temp": history_entry.get("forecast_soil_temp", []),
        "hist_precip": history_entry.get("hist_precip", []),
        "forecast_snow_depth": history_entry.get("forecast_snow_depth", []),
    }


def main():
    parser = argparse.ArgumentParser(description="Backtest current model on past dates")
    parser.add_argument("--slug", action="append", help="Site slug to backtest (repeatable)")
    parser.add_argument("--days", type=int, default=7, help="Number of past days to score (default 7)")
    parser.add_argument("--mushroom", default="morel", help="Mushroom type profile")
    args = parser.parse_args()

    slugs = args.slug if args.slug else DEFAULT_SLUGS

    data = json.loads(Path("docs/data/latest.json").read_text())
    hist = json.loads(Path("docs/data/history.json").read_text())
    config = MUSHROOM_TYPES[args.mushroom]
    run_date = datetime.strptime(data["run_date"], "%Y-%m-%d")

    # Find sites
    sites_by_slug = {}
    for i, b in enumerate(data["burns"]):
        if b["slug"] in slugs:
            sites_by_slug[b["slug"]] = (i, b)

    # Build target dates: oldest first
    backtest_dates = []
    for offset in range(-args.days, 1):
        bt_date = run_date + timedelta(days=offset)
        target_day = 30 + offset
        backtest_dates.append((bt_date.strftime("%Y-%m-%d"), target_day))

    print(f"BACKTEST — model {data['algo_version']} against runs anchored to {data['run_date']}\n")
    header = " | ".join(d[0][5:] for d in backtest_dates)
    print(f"{'site':28s} | {header}")
    print("-" * (28 + len(header) + 3))

    phase_letter = {"EMERGING": "E", "GROWING": "G", "WAITING": "W", "TOO_EARLY": "T"}

    for slug in slugs:
        if slug not in sites_by_slug:
            print(f"{slug:28s} | (not in catalog)")
            continue
        idx, burn = sites_by_slug[slug]
        weather = reconstruct_weather(hist[idx])
        timeline = burn["timeline"]

        cells = []
        for date_str, target_day in backtest_dates:
            if target_day < 0 or target_day >= len(timeline):
                cells.append("  --")
                continue
            feats = extract_features(timeline, weather, target_day, config)
            readiness = score_readiness(feats)
            phase = classify_phase(feats)
            cells.append(f"{phase_letter.get(phase, '?')} {readiness:>3d}")

        short = burn["name"][:27]
        print(f"{short:28s} | {' | '.join(cells)}")

    print("\nLegend: E=EMERGING G=GROWING W=WAITING T=TOO_EARLY, number=readiness 0-100")


if __name__ == "__main__":
    main()
