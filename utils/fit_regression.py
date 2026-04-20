"""
Fit logistic regression on labeled scenarios to learn readiness weights.

Usage:
    python -m utils.fit_regression

This extracts features from all 21+ scenarios, fits a logistic regression,
and prints the coefficients. These coefficients can be baked into
phase_scoring.score_readiness() to replace hand-tuned weights.

As field reports are added, they become additional training samples.
"""

import numpy as np
from sklearn.linear_model import LogisticRegression

from phase_scoring import build_timeline, extract_features, classify_phase, score_readiness_manual
from tests.test_phase_scoring import make_timeline_weather, ramp, constant


# ── Labeled scenarios ──
# Each: (name, label, soil_temps_44, precip_44, snow_44_or_None)
# Labels: 1.0 = GOOD (go forage), 0.5 = BORDERLINE, 0.0 = BAD (don't go)

SCENARIOS = [
    # GOOD (label=1.0) — should produce EMERGING
    ("G1_textbook_spring", 1.0,
     ramp(35, 55, 30) + ramp(55, 57, 14),
     [0]*8 + [0.5] + [0]*6 + [0.6] + [0]*6 + [0.8] + [0]*6 + [0]*14,
     None),

    ("G2_post_snowmelt", 1.0,
     constant(33, 9) + ramp(33, 40, 3) + ramp(40, 52, 18) + ramp(52, 54, 14),
     constant(0, 9) + constant(0.2, 21) + constant(0.1, 14),
     constant(12, 9) + ramp(12, 0, 6) + constant(0, 29)),

    ("G3_rain_triggered", 1.0,
     constant(50, 9) + constant(50, 21) + constant(55, 14),
     constant(0, 9) + [1.0] + constant(0.15, 20) + constant(0.1, 14),
     None),

    ("G4_south_facing_early", 1.0,
     constant(38, 5) + ramp(38, 43, 2) + ramp(43, 52, 23) + ramp(52, 54, 14),
     constant(0, 5) + constant(0.2, 25) + constant(0.1, 14),
     None),

    ("G5_recovery_after_snap", 1.0,
     constant(38, 2) + ramp(38, 48, 5) + constant(50, 10) + [30, 30] + constant(50, 11) + constant(52, 14),
     constant(0.15, 44),
     None),

    ("G6_multiple_moisture", 1.0,
     constant(40, 9) + ramp(40, 48, 3) + constant(52, 18) + constant(54, 14),
     [0]*10 + [0.5, 0, 0, 0, 0, 0.6, 0, 0, 0, 0, 0.8, 0, 0, 0, 0, 0.5, 0, 0, 0, 0] + [0.1]*14,
     None),

    ("G7_real_truckee", 1.0,
     [40, 41, 45, 46, 48, 50, 52, 48, 45, 43, 42, 44, 46, 48, 50, 52, 53, 50, 48, 46,
      48, 45, 38, 37, 46, 46, 48, 48, 54, 54] +
     [53, 57, 59, 61, 66, 74, 68, 66, 42, 51, 69, 69, 66, 60],
     [0]*20 + [0.18, 0.55, 0.62, 0.02, 0, 0, 0.01, 0, 0, 0] + [0]*14,
     None),

    # BAD (label=0.0) — should produce TOO_EARLY or WAITING
    ("B1_still_frozen", 0.0,
     constant(32, 30) + constant(33, 14),
     constant(0, 44),
     constant(30, 44)),

    ("B2_warm_but_dry", 0.0,
     constant(52, 30) + constant(54, 14),
     constant(0, 44),
     None),

    ("B3_freeze_killed", 0.0,
     constant(38, 5) + ramp(38, 48, 5) + constant(50, 8) + constant(28, 5) + ramp(28, 45, 7) + constant(48, 14),
     constant(0.15, 44),
     None),

    ("B4_too_early", 0.0,
     constant(33, 26) + ramp(33, 46, 4) + ramp(46, 50, 14),
     constant(0, 26) + constant(0.2, 18),
     None),

    ("B5_hot_past_season", 0.0,
     ramp(55, 68, 30) + constant(70, 14),
     constant(0, 44),
     None),

    ("B6_oscillating", 0.0,
     ([40, 45, 50, 38, 42, 48, 35, 40, 52, 40] * 3)[:30] + [40, 45, 50, 38] + [45]*10,
     [0.3 if i % 5 == 0 else 0 for i in range(44)],
     None),

    ("B7_deep_snowpack", 0.0,
     constant(33, 30) + constant(30, 14),
     constant(0, 44),
     constant(36, 44)),

    # BORDERLINE (label=0.5) — GROWING or marginal
    ("M1_almost_enough_grow", 0.5,
     constant(38, 12) + ramp(38, 48, 5) + constant(50, 13) + constant(52, 14),
     constant(0, 12) + constant(0.2, 32),
     None),

    ("M2_marginal_start", 0.5,
     constant(38, 10) + [43, 44] + constant(50, 18) + constant(52, 14),
     constant(0, 10) + constant(0.2, 34),
     None),

    ("M3_two_day_snap", 0.5,
     constant(38, 7) + ramp(38, 48, 5) + constant(50, 12) + [32, 33] + constant(50, 4) + constant(52, 14),
     constant(0.15, 44),
     None),

    ("M4_moisture_uncertain", 0.5,
     ramp(38, 50, 30) + constant(52, 14),
     constant(0, 15) + [0.5] + constant(0, 28),
     None),

    ("M5_wrong_elevation", 0.5,
     ramp(35, 42, 30) + constant(43, 14),
     constant(0.15, 44),
     None),

    ("M6_second_year_burn", 0.5,
     ramp(35, 55, 30) + constant(55, 14),
     constant(0.2, 44),
     None),

    ("M7_north_facing_slow", 0.5,
     constant(38, 20) + ramp(38, 50, 10) + ramp(50, 53, 14),
     constant(0, 20) + constant(0.2, 24),
     None),
]

FEATURE_NAMES = [
    "start_days", "grow_days", "max_bad_streak", "growth_was_reset",
    "soil_avg_14d", "current_soil", "warming_rate", "precip_events",
    "is_currently_good",
]


def build_dataset(scenarios=None, config=None):
    """Extract features from all scenarios. Returns (X, y, names, all_features)."""
    if scenarios is None:
        scenarios = SCENARIOS
    if config is None:
        config = {}

    X = []
    y = []
    names = []
    all_features = []

    for name, label, soil, precip, snow in scenarios:
        weather = make_timeline_weather(soil, precip, snow)
        timeline = build_timeline(weather, config)
        features = extract_features(timeline, weather, 30, config)
        phase = classify_phase(features)
        readiness = score_readiness_manual(features)

        feature_vec = [features[k] for k in FEATURE_NAMES]
        X.append(feature_vec)
        y.append(label)
        names.append(name)
        all_features.append(features)

    return np.array(X), np.array(y), names, all_features


def fit_model(X, y, threshold=0.75):
    """Fit logistic regression. Returns model + predictions."""
    y_binary = (y >= threshold).astype(int)
    model = LogisticRegression(max_iter=1000)
    model.fit(X, y_binary)
    return model


def print_results(model, X, y, names):
    """Print coefficients and predictions."""
    print("\n" + "=" * 60)
    print("LOGISTIC REGRESSION COEFFICIENTS")
    print("=" * 60)
    for name, coef in zip(FEATURE_NAMES, model.coef_[0]):
        bar = "+" * int(abs(coef) * 10) if coef > 0 else "-" * int(abs(coef) * 10)
        print(f"  {name:20s}: {coef:+.4f}  {bar}")
    print(f"  {'intercept':20s}: {model.intercept_[0]:+.4f}")

    print("\n" + "=" * 60)
    print("PREDICTIONS")
    print("=" * 60)
    probs = model.predict_proba(X)[:, 1]
    correct = 0
    for name, label, prob in zip(names, y, probs):
        pred = "GOOD" if prob > 0.5 else "BAD"
        # Borderline (0.5) is acceptable either way
        is_borderline = 0.25 < label < 0.75
        match = (label >= 0.75) == (prob > 0.5) or is_borderline
        correct += match
        symbol = "✓" if match else "✗"
        print(f"  {name:30s}: label={label:.1f}  prob={prob:.2f}  {pred:4s}  {symbol}")

    accuracy = correct / len(names) * 100
    print(f"\nAccuracy: {correct}/{len(names)} ({accuracy:.0f}%)")

    # Feature importance ranking
    print("\n" + "=" * 60)
    print("FEATURE IMPORTANCE (by |coefficient|)")
    print("=" * 60)
    importance = sorted(zip(FEATURE_NAMES, model.coef_[0]),
                        key=lambda x: abs(x[1]), reverse=True)
    for name, coef in importance:
        direction = "↑ more = GOOD" if coef > 0 else "↓ more = BAD"
        print(f"  {name:20s}: {coef:+.4f}  ({direction})")

    return probs


def load_json_scenarios(path):
    """
    Load scenarios from a JSON file. Format:

    [
      {
        "name": "my_field_report",
        "label": 1.0,
        "soil_temps": [44 daily values],
        "precip": [30-44 daily values],
        "snow_depths": [44 daily values] or null
      },
      ...
    ]

    Labels: 1.0 = found morels, 0.0 = nothing, 0.5 = marginal/few
    """
    import json
    with open(path) as f:
        data = json.load(f)

    scenarios = []
    for s in data:
        soil = s["soil_temps"]
        precip = s.get("precip", [0] * 44)
        snow = s.get("snow_depths", None)
        assert len(soil) == 44, f"Scenario {s['name']}: need 44 soil temps, got {len(soil)}"
        scenarios.append((s["name"], s["label"], soil, precip, snow))
    return scenarios


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Fit readiness regression on labeled scenarios")
    parser.add_argument("--json", help="Path to JSON file with additional/override scenarios")
    parser.add_argument("--json-only", action="store_true", help="Use only JSON scenarios, not built-in 21")
    parser.add_argument("--save", help="Save coefficients to this file (JSON)")
    args = parser.parse_args()

    # Load scenarios
    scenarios = [] if args.json_only else SCENARIOS
    if args.json:
        extra = load_json_scenarios(args.json)
        scenarios = scenarios + extra
        print(f"Loaded {len(extra)} scenarios from {args.json}")

    print(f"Building dataset from {len(scenarios)} labeled scenarios...")
    X, y, names, features = build_dataset(scenarios)

    print(f"\nDataset: {len(names)} scenarios, {X.shape[1]} features")
    print(f"Labels: {sum(y >= 0.75)} good, {sum(y <= 0.25)} bad, {sum((y > 0.25) & (y < 0.75))} borderline")

    print("\nFeature summary per scenario:")
    for name, feat in zip(names, features):
        print(f"  {name:30s}: start={feat['start_days']:2d} grow={feat['grow_days']:2d} "
              f"bad={feat['max_bad_streak']:2d} soil14d={feat['soil_avg_14d']:5.1f} "
              f"precip_ev={feat['precip_events']} warm={feat['warming_rate']:+.2f}")

    model = fit_model(X, y)
    probs = print_results(model, X, y, names)

    # Save coefficients
    coefficients = {name: float(coef) for name, coef in zip(FEATURE_NAMES, model.coef_[0])}
    coefficients["intercept"] = float(model.intercept_[0])

    print("\n" + "=" * 60)
    print("READINESS_COEFFICIENTS = {")
    for k, v in coefficients.items():
        print(f'    "{k}": {v:.6f},')
    print("}")

    if args.save:
        import json
        with open(args.save, "w") as f:
            json.dump(coefficients, f, indent=2)
        print(f"\nCoefficients saved to {args.save}")
