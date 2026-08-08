"""
Thin wrapper around the exact prediction pipeline built and validated in
Traffic_Accident_Risk_Predictor_v2.ipynb (sections 23-26). Every function
here is a direct port of a notebook cell -- nothing new is invented for the
web app, so the numbers a user sees here match what the notebook reported.
"""
import json
import os

import joblib
import numpy as np
import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ARTIFACTS_DIR = os.path.join(BASE_DIR, "artifacts")
DATA_DIR = os.path.join(BASE_DIR, "data")


def _artifact(name):
    return joblib.load(os.path.join(ARTIFACTS_DIR, name))


def _data(name):
    with open(os.path.join(DATA_DIR, name), encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------
# Load the trained pipeline once, at import time.
# ---------------------------------------------------------------------
final_model = _artifact("final_model.pkl")
encoder = _artifact("encoder.pkl")
scaler = _artifact("scaler.pkl")
BEST_THRESHOLD = float(_artifact("best_threshold.pkl"))
FEATURE_COLUMNS = _artifact("feature_columns.pkl")
county_risk = _artifact("county_risk.pkl")
state_risk = _artifact("state_risk.pkl")
county_density = _artifact("county_density.pkl")
county_coords = _artifact("county_coords.pkl")
state_coords = _artifact("state_coords.pkl")

_meta = _data("meta.json")
global_risk_mean = _meta["global_risk_mean"]
global_density_mean = _meta["global_density_mean"]

_tiers = _data("alert_tiers.json")
TIER_MEDIUM_HIGH = _tiers["medium_alert_below"]
TIER_HIGH_CRITICAL = _tiers["high_alert_below"]

CATEGORICAL_FEATURES = ["County", "State", "Season", "Time_Period"]
SEASON_TO_MONTH = {"Winter": 1, "Spring": 4, "Summer": 7, "Autumn": 10}

# XGBoost won the model comparison in the notebook, so this is False in
# practice -- kept so the service still works unmodified if the notebook is
# re-run later and a scaled linear model happens to win instead.
FINAL_MODEL_USES_SCALING = type(final_model).__name__ == "LogisticRegression"


def time_period(hour):
    if 5 <= hour < 9:
        return "Morning Peak"
    if 9 <= hour < 12:
        return "Morning"
    if 12 <= hour < 16:
        return "Afternoon"
    if 16 <= hour < 20:
        return "Evening Peak"
    if 20 <= hour < 24:
        return "Night"
    return "Late Night"


def locate(state, county):
    """Return (lat, lng) for a county, falling back to its state average."""
    try:
        row = county_coords.loc[(state, county)]
        return float(row["Start_Lat"]), float(row["Start_Lng"])
    except KeyError:
        row = state_coords.loc[state]
        return float(row["Start_Lat"]), float(row["Start_Lng"])


def lookup_risk(state, county):
    try:
        return float(county_risk.loc[(state, county)])
    except KeyError:
        return float(state_risk.get(state, global_risk_mean))


def lookup_density(state, county):
    try:
        return float(county_density.loc[(state, county)])
    except KeyError:
        return float(global_density_mean)


def _score(encoded_row):
    if FINAL_MODEL_USES_SCALING:
        return float(final_model.predict_proba(scaler.transform(encoded_row))[0, 1])
    return float(final_model.predict_proba(encoded_row)[0, 1])


def predict_accident_risk(state, county, season, hour, is_weekend,
                           crossing=0, junction=0, station=0, stop=0,
                           traffic_signal=0, amenity=0):
    """Direct port of the notebook's `predict_accident_risk` (section 23)."""
    month = SEASON_TO_MONTH[season]
    day_of_week = 6 if is_weekend else 2
    is_rush_hour = int((7 <= hour <= 9) or (16 <= hour <= 18))
    period = time_period(hour)

    lat, lng = locate(state, county)

    row = pd.DataFrame([{
        "Start_Lat": lat, "Start_Lng": lng,
        "County": county, "State": state,
        "Amenity": amenity, "Crossing": crossing, "Junction": junction,
        "Station": station, "Stop": stop, "Traffic_Signal": traffic_signal,
        "Month": month, "Hour": hour, "DayOfWeek": day_of_week,
        "Is_Weekend": int(is_weekend), "Is_Rush_Hour": is_rush_hour,
        "Hour_sin": np.sin(2 * np.pi * hour / 24), "Hour_cos": np.cos(2 * np.pi * hour / 24),
        "Month_sin": np.sin(2 * np.pi * (month - 1) / 12), "Month_cos": np.cos(2 * np.pi * (month - 1) / 12),
        "Season": season, "Time_Period": period,
        "County_Risk": lookup_risk(state, county),
        "State_Risk": float(state_risk.get(state, global_risk_mean)),
        "County_Density": lookup_density(state, county),
    }])[FEATURE_COLUMNS]

    encoded = row.copy()
    encoded[CATEGORICAL_FEATURES] = encoder.transform(encoded[CATEGORICAL_FEATURES])
    probability = _score(encoded)
    return row, probability


def safety_score(risk_probability):
    score = round((1 - risk_probability) * 100, 2)
    if score >= 80:
        status = "Very Safe"
    elif score >= 60:
        status = "Safe"
    elif score >= 40:
        status = "Moderate"
    elif score >= 20:
        status = "High Risk"
    else:
        status = "Critical"
    return score, status


def alert_level(prob):
    if prob < BEST_THRESHOLD:
        return "No Alert"
    if prob < TIER_MEDIUM_HIGH:
        return "Medium Alert"
    if prob < TIER_HIGH_CRITICAL:
        return "High Alert"
    return "Critical Alert"


def prevention_recommendation(alert, period, season):
    actions = []
    if alert == "Critical Alert":
        actions += ["Deploy emergency response teams.", "Increase police patrols."]
    elif alert == "High Alert":
        actions += ["Increase traffic monitoring.", "Deploy additional patrol units."]

    if period == "Morning Peak":
        actions.append("Optimize traffic signal timing for rush-hour flow.")
    elif period == "Evening Peak":
        actions.append("Increase congestion monitoring.")
    elif period in ("Night", "Late Night"):
        actions += ["Improve roadway lighting.", "Increase highway patrol visibility."]

    if season == "Winter":
        actions += ["Prepare winter road maintenance.", "Issue weather safety warnings."]
    elif season == "Spring":
        actions.append("Inspect road surface conditions after winter wear.")

    return " | ".join(dict.fromkeys(actions)) if actions else "Maintain routine monitoring."


# ---------------------------------------------------------------------
# Innovation 2 -- AI Scenario Simulator (notebook section 25)
# ---------------------------------------------------------------------
SCENARIO_CHANGES = {
    "Without Junction": {"Junction": 0},
    "Without Crossing": {"Crossing": 0},
    "Without Traffic Signal": {"Traffic_Signal": 0},
    "Shifted Off Rush Hour": {
        "Hour": 14, "Is_Rush_Hour": 0, "Time_Period": "Afternoon",
        "Hour_sin": np.sin(2 * np.pi * 14 / 24), "Hour_cos": np.cos(2 * np.pi * 14 / 24),
    },
    "Weekend Instead of Weekday": {"Is_Weekend": 1, "DayOfWeek": 6},
}

ACTION_MAP = {
    "Without Junction": "Improve intersection traffic management.",
    "Without Crossing": "Improve pedestrian crossing safety.",
    "Without Traffic Signal": "Optimize traffic signal control.",
    "Shifted Off Rush Hour": "Reduce congestion during peak hours.",
    "Weekend Instead of Weekday": "Increase weekend traffic monitoring.",
    "Current Situation": "Current conditions are already the safest option evaluated.",
}


def build_scenarios(base_row):
    scenarios = {"Current Situation": base_row.copy()}
    for name, changes in SCENARIO_CHANGES.items():
        variant = base_row.copy()
        for col, value in changes.items():
            variant[col] = value
        scenarios[name] = variant
    return scenarios


def score_scenarios(scenarios):
    results = []
    for name, row in scenarios.items():
        encoded = row.copy()
        encoded[CATEGORICAL_FEATURES] = encoder.transform(encoded[CATEGORICAL_FEATURES])
        results.append({"scenario": name, "risk_probability_pct": round(_score(encoded) * 100, 2)})
    return results


def best_improvement(scenario_results):
    current = next(r["risk_probability_pct"] for r in scenario_results if r["scenario"] == "Current Situation")
    best = min(scenario_results, key=lambda r: r["risk_probability_pct"])

    reduction = round(current - best["risk_probability_pct"], 2)
    improvement_rate = round(reduction / current * 100, 2) if current > 0 else 0.0
    priority = "High" if improvement_rate >= 20 else "Medium" if improvement_rate >= 10 else "Low"

    return {
        "current_risk_pct": current,
        "best_scenario": best["scenario"],
        "improved_risk_pct": best["risk_probability_pct"],
        "risk_reduction_pts": reduction,
        "improvement_rate_pct": improvement_rate,
        "priority": priority,
        "recommended_action": ACTION_MAP.get(best["scenario"], "No action needed."),
    }


# ---------------------------------------------------------------------
# Public entry points used by app.py
# ---------------------------------------------------------------------
def run_prediction(state, county, season, hour, is_weekend, **road_features):
    row, probability = predict_accident_risk(
        state=state, county=county, season=season, hour=hour, is_weekend=is_weekend, **road_features
    )
    score, status = safety_score(probability)
    alert = alert_level(probability)
    period = row.iloc[0]["Time_Period"]

    return {
        "state": state,
        "county": county,
        "season": season,
        "hour": hour,
        "time_period": period,
        "risk_probability": probability,
        "risk_probability_pct": round(probability * 100, 2),
        "predicted_high_risk": bool(probability >= BEST_THRESHOLD),
        "decision_threshold": BEST_THRESHOLD,
        "safety_score": score,
        "safety_status": status,
        "alert_level": alert,
        "prevention_recommendation": prevention_recommendation(alert, period, season),
    }, row


def run_scenario_simulation(state, county, season, hour, is_weekend, **road_features):
    base_row, _ = predict_accident_risk(
        state=state, county=county, season=season, hour=hour, is_weekend=is_weekend, **road_features
    )
    scenarios = build_scenarios(base_row)
    results = score_scenarios(scenarios)
    improvement = best_improvement(results)
    return {"scenarios": results, "best_improvement": improvement}
