# TODO

## Scoring refinements
- [ ] Expand training scenarios to 100+ (currently 70) — more edge cases, field reports when available
- [ ] Fix `growth_was_reset` positive coefficient (+0.85) — likely regression quirk
- [ ] Consider replacing logistic regression with ordinal/ranking model for better score spread
- [ ] Add driving time estimation (Google Maps API) — straight-line distance is misleading
- [ ] Consolidate `scoring.py` (old) + `phase_scoring.py` (new) — remove legacy code

## Data sources
- [ ] LANDFIRE vegetation type (EVT/EVH/EVC) for matsutake/porcini candidates
- [ ] NRCS soil type data (sandy = strong indicator)
- [ ] Burn severity (dNBR from Sentinel-2) for actual severity vs PFIRS burn type proxy
- [ ] PFIRS auto-refresh without browser cookie

## Frontend
- [ ] Remove old 8-day mini-charts from popup (still showing legacy factor scores)
- [ ] Heatmap uses old `day.total` — switch to potential-weighted
- [ ] Detail page: clean up old score hero section, keep phase + charts
- [ ] Detail page: timeline strip needs day-of-week labels
- [ ] Filter sliders: add "By Conditions" tab (raw soil temp, precip, snow depth ranges)
- [ ] Interactive score filter sliders (JS-based, from design doc)
- [ ] Static PNG map export for GitHub Pages

## Multi-species
- [ ] Porcini (P1 — in season) — needs LANDFIRE grid candidate generation
- [ ] Matsutake (P2 — Sep-Nov) — needs LANDFIRE + different scoring model
- [ ] Chanterelle (P3 — Jul-Oct) — needs hardwood EVT codes

## Infrastructure
- [ ] Historical JSON archival (`docs/data/history/`) for hindcast validation
- [ ] Field report CLI (`utils/field_report.py`) for recording finds
- [ ] Prediction vs reality comparison tool (`utils/analyze_reports.py`)
- [ ] Multi-point aspect sampling causes slow first run (~3100 extra API calls)
- [ ] Weather cache invalidation — clear only weather, not elevation/terrain

## Documentation
- [x] ALGO.md updated for v0.7.0
- [x] reference/algo/v0.7.0.md snapshot
- [ ] README.md scoring section still references old model — needs update
- [ ] CLAUDE.md architecture section needs phase_scoring.py added
