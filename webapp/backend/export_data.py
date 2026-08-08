"""
Regenerates every JSON payload the web dashboard needs, straight from the
saved model artifacts + the 2023 held-out slice of the dataset. This keeps
the web app and the notebook using the exact same prediction pipeline —
nothing here is hand-typed or faked.
"""
import json
import os

import joblib
import numpy as np
import pandas as pd

DATA_CSV = r"E:\USA Atlanta\Dataset\cleaned_us_accidents.csv"
ARTIFACTS_DIR = r"E:\USA Atlanta\AI accident\webapp\backend\artifacts"
OUT_DIR = r"E:\USA Atlanta\AI accident\webapp\backend\data"
os.makedirs(OUT_DIR, exist_ok=True)

RANDOM_STATE = 42


def load_artifact(name):
    return joblib.load(os.path.join(ARTIFACTS_DIR, name))


final_model = load_artifact("final_model.pkl")
encoder = load_artifact("encoder.pkl")
best_threshold = load_artifact("best_threshold.pkl")
feature_columns = load_artifact("feature_columns.pkl")
county_risk = load_artifact("county_risk.pkl")
state_risk = load_artifact("state_risk.pkl")
county_density = load_artifact("county_density.pkl")

CATEGORICAL_FEATURES = ["County", "State", "Season", "Time_Period"]
ROAD_FEATURES = ["Traffic_Signal", "Crossing", "Junction", "Stop", "Station", "Amenity"]

print("Loading dataset...")
# Load every original column (not just the ones the model uses) so that
# drop_duplicates() below sees exactly the same row-uniqueness the notebook
# saw -- deduplicating on a narrower column subset would silently collapse
# rows that only differ in a column we dropped, shrinking the test set.
df = pd.read_csv(DATA_CSV)
df = df.drop_duplicates()

keep_cols = [
    "Source", "Severity", "Start_Lat", "Start_Lng", "County", "State",
    "Amenity", "Crossing", "Junction", "Station", "Stop", "Traffic_Signal",
    "Year", "Month", "Hour", "DayOfWeek", "Is_Weekend", "Is_Rush_Hour",
]
df = df[keep_cols]

model_df = df[(df["Source"] == "Source1") & (df["Year"] >= 2021)].copy()

season_map = {
    12: "Winter", 1: "Winter", 2: "Winter",
    3: "Spring", 4: "Spring", 5: "Spring",
    6: "Summer", 7: "Summer", 8: "Summer",
    9: "Autumn", 10: "Autumn", 11: "Autumn",
}
model_df["Season"] = model_df["Month"].map(season_map)


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


model_df["Time_Period"] = model_df["Hour"].apply(time_period)
model_df["Risk"] = (model_df["Severity"] >= 3).astype(int)
model_df["Hour_sin"] = np.sin(2 * np.pi * model_df["Hour"] / 24)
model_df["Hour_cos"] = np.cos(2 * np.pi * model_df["Hour"] / 24)
# Matches the notebook exactly: month is zero-indexed before the cyclical transform.
model_df["Month_sin"] = np.sin(2 * np.pi * (model_df["Month"] - 1) / 12)
model_df["Month_cos"] = np.cos(2 * np.pi * (model_df["Month"] - 1) / 12)

train_df = model_df[model_df["Year"].isin([2021, 2022])]
test_df = model_df[model_df["Year"] == 2023].copy()
global_risk_mean = float(train_df["Risk"].mean())
print(f"Train rows: {len(train_df):,}  Test (2023) rows: {len(test_df):,}  "
      f"Global risk mean: {global_risk_mean:.4f}")


def attach_geo_features(frame):
    frame = frame.copy()
    idx = frame.set_index(["State", "County"]).index
    frame["County_Risk"] = idx.map(county_risk).fillna(global_risk_mean)
    frame["State_Risk"] = frame["State"].map(state_risk).fillna(global_risk_mean)
    frame["County_Density"] = idx.map(county_density).fillna(county_density.mean())
    return frame


test_df = attach_geo_features(test_df)

X_test = test_df[feature_columns].copy()
X_test[CATEGORICAL_FEATURES] = encoder.transform(X_test[CATEGORICAL_FEATURES])

print("Scoring the 2023 test slice with the deployed model...")
test_prob = final_model.predict_proba(X_test)[:, 1]
test_pred = (test_prob >= best_threshold).astype(int)

predictions_df = test_df[["State", "County", "Season", "Time_Period"]].copy()
predictions_df["Risk_Probability"] = test_prob
predictions_df["Predicted_Risk"] = test_pred

# ---------------------------------------------------------------------
# Dangerous zones (State + County aggregation)
# ---------------------------------------------------------------------
dangerous_zones = (
    predictions_df.groupby(["State", "County"])
    .agg(
        Total_Records=("Predicted_Risk", "count"),
        High_Risk_Count=("Predicted_Risk", "sum"),
        Average_Risk_Probability=("Risk_Probability", "mean"),
    )
    .reset_index()
)
dangerous_zones["Risk_Score"] = (
    dangerous_zones["High_Risk_Count"] * dangerous_zones["Average_Risk_Probability"]
)
dangerous_zones = dangerous_zones.sort_values("Risk_Score", ascending=False).reset_index(drop=True)

q50, q75, q90 = dangerous_zones["Risk_Score"].quantile([0.50, 0.75, 0.90])


def classify_zone(score):
    if score >= q90:
        return "Critical"
    if score >= q75:
        return "High"
    if score >= q50:
        return "Medium"
    return "Low"


dangerous_zones["Risk_Level"] = dangerous_zones["Risk_Score"].apply(classify_zone)
ACTION_MAP = {
    "Critical": "Deploy immediate emergency response",
    "High": "Increase traffic patrol and monitoring",
    "Medium": "Schedule regular safety monitoring",
    "Low": "Maintain routine observation",
}
dangerous_zones["Recommended_Action"] = dangerous_zones["Risk_Level"].map(ACTION_MAP)

dangerous_zones.head(300).to_json(
    os.path.join(OUT_DIR, "dangerous_zones.json"), orient="records"
)
print(f"dangerous_zones.json: {min(300, len(dangerous_zones))} rows "
      f"(of {len(dangerous_zones)} counties)")

# ---------------------------------------------------------------------
# State-level summary, for the map (needs real-world coordinates, so we
# join against a fixed public reference table of US state centroids —
# the model's own Start_Lat/Start_Lng are standardized and cannot be
# converted back to real degrees).
# ---------------------------------------------------------------------
STATE_CENTROIDS = {
    "AL": (32.8, -86.8), "AK": (64.2, -149.5), "AZ": (34.2, -111.7), "AR": (34.9, -92.4),
    "CA": (37.2, -119.4), "CO": (39.0, -105.5), "CT": (41.6, -72.7), "DE": (39.0, -75.5),
    "FL": (28.6, -82.4), "GA": (32.6, -83.4), "HI": (20.3, -156.4), "ID": (44.4, -114.6),
    "IL": (40.0, -89.2), "IN": (39.9, -86.3), "IA": (42.0, -93.5), "KS": (38.5, -98.4),
    "KY": (37.5, -85.3), "LA": (31.0, -92.0), "ME": (45.4, -69.2), "MD": (39.0, -76.7),
    "MA": (42.3, -71.8), "MI": (44.3, -85.4), "MN": (46.3, -94.3), "MS": (32.7, -89.7),
    "MO": (38.5, -92.5), "MT": (46.9, -110.0), "NE": (41.5, -99.7), "NV": (39.3, -117.0),
    "NH": (43.7, -71.6), "NJ": (40.1, -74.7), "NM": (34.5, -106.1), "NY": (42.9, -75.5),
    "NC": (35.6, -79.4), "ND": (47.5, -100.5), "OH": (40.3, -82.8), "OK": (35.6, -97.5),
    "OR": (43.9, -120.6), "PA": (40.9, -77.7), "RI": (41.7, -71.5), "SC": (33.9, -80.9),
    "SD": (44.4, -100.2), "TN": (35.9, -86.4), "TX": (31.5, -99.3), "UT": (39.3, -111.7),
    "VT": (44.0, -72.7), "VA": (37.5, -78.8), "WA": (47.4, -121.5), "WV": (38.6, -80.7),
    "WI": (44.6, -89.9), "WY": (43.0, -107.5), "DC": (38.9, -77.0),
}

state_summary = (
    dangerous_zones.groupby("State")
    .apply(lambda g: pd.Series({
        "County_Count": len(g),
        "Critical_County_Count": int((g["Risk_Level"] == "Critical").sum()),
        "Avg_Risk_Score": g["Risk_Score"].mean(),
        "Top_County": g.iloc[0]["County"],
        "Top_County_Risk_Score": g.iloc[0]["Risk_Score"],
        "Top_County_Risk_Level": g.iloc[0]["Risk_Level"],
    }))
    .reset_index()
)
state_summary["Lat"] = state_summary["State"].map(lambda s: STATE_CENTROIDS.get(s, (None, None))[0])
state_summary["Lng"] = state_summary["State"].map(lambda s: STATE_CENTROIDS.get(s, (None, None))[1])
state_summary = state_summary.dropna(subset=["Lat", "Lng"])
state_summary.to_json(os.path.join(OUT_DIR, "state_summary.json"), orient="records")
print(f"state_summary.json: {len(state_summary)} states")

# ---------------------------------------------------------------------
# Season / time-of-day risk
# ---------------------------------------------------------------------
def risk_by_group(frame, col):
    out = (
        frame.groupby(col)
        .agg(
            Total_Records=("Predicted_Risk", "count"),
            High_Risk=("Predicted_Risk", "sum"),
            Average_Risk_Probability=("Risk_Probability", "mean"),
        )
        .reset_index()
    )
    out["High_Risk_Percentage"] = out["High_Risk"] / out["Total_Records"] * 100
    return out.sort_values("High_Risk_Percentage", ascending=False)


season_time = {
    "by_season": json.loads(risk_by_group(predictions_df, "Season").to_json(orient="records")),
    "by_time_period": json.loads(risk_by_group(predictions_df, "Time_Period").to_json(orient="records")),
    "months_covered": sorted(int(m) for m in test_df["Month"].unique()),
}
with open(os.path.join(OUT_DIR, "season_time_risk.json"), "w") as f:
    json.dump(season_time, f)
print("season_time_risk.json written")

# ---------------------------------------------------------------------
# Alerts (adaptive tercile tiers on the flagged test predictions)
# ---------------------------------------------------------------------
flagged = test_prob[test_prob >= best_threshold]
tier_med_high, tier_high_crit = np.quantile(flagged, [1 / 3, 2 / 3])


def alert_level(prob):
    if prob < best_threshold:
        return "No Alert"
    if prob < tier_med_high:
        return "Medium Alert"
    if prob < tier_high_crit:
        return "High Alert"
    return "Critical Alert"


predictions_df["Alert_Level"] = predictions_df["Risk_Probability"].apply(alert_level)


def prevention_recommendation(row):
    actions = []
    if row["Alert_Level"] == "Critical Alert":
        actions += ["Deploy emergency response teams.", "Increase police patrols."]
    elif row["Alert_Level"] == "High Alert":
        actions += ["Increase traffic monitoring.", "Deploy additional patrol units."]
    if row["Time_Period"] == "Morning Peak":
        actions.append("Optimize traffic signal timing for rush-hour flow.")
    elif row["Time_Period"] == "Evening Peak":
        actions.append("Increase congestion monitoring.")
    elif row["Time_Period"] in ("Night", "Late Night"):
        actions += ["Improve roadway lighting.", "Increase highway patrol visibility."]
    if row["Season"] == "Winter":
        actions += ["Prepare winter road maintenance.", "Issue weather safety warnings."]
    elif row["Season"] == "Spring":
        actions.append("Inspect road surface conditions after winter wear.")
    return " | ".join(dict.fromkeys(actions)) if actions else "Maintain routine monitoring."


high_priority = predictions_df[predictions_df["Alert_Level"].isin(["High Alert", "Critical Alert"])].copy()
high_priority["Prevention_Recommendation"] = high_priority.apply(prevention_recommendation, axis=1)
high_priority["Safety_Alert"] = (
    high_priority["Alert_Level"].str.replace(" Alert", "", regex=False)
    + " accident risk detected in " + high_priority["County"] + ", " + high_priority["State"]
    + " during " + high_priority["Time_Period"]
    + ". Estimated probability: " + (high_priority["Risk_Probability"] * 100).round(2).astype(str) + "%."
)
# Keep the top rows *within each tier* (not just the top 200 overall) so a
# dashboard filtered to "Medium" or "High" still has real rows to show --
# Critical-tier probabilities are so much higher that a single global
# top-200 cut would otherwise be almost entirely Critical alerts.
high_priority = (
    high_priority.sort_values("Risk_Probability", ascending=False)
    .groupby("Alert_Level", group_keys=False)
    .head(100)
    .sort_values("Risk_Probability", ascending=False)
)
high_priority.to_json(os.path.join(OUT_DIR, "alerts.json"), orient="records")

alert_tiers = {
    "no_alert_below": float(best_threshold),
    "medium_alert_below": float(tier_med_high),
    "high_alert_below": float(tier_high_crit),
}
with open(os.path.join(OUT_DIR, "alert_tiers.json"), "w") as f:
    json.dump(alert_tiers, f)
print(f"alerts.json: {len(high_priority)} rows")

# ---------------------------------------------------------------------
# Dashboard summary
# ---------------------------------------------------------------------
alert_counts = predictions_df["Alert_Level"].value_counts().reindex(
    ["No Alert", "Medium Alert", "High Alert", "Critical Alert"], fill_value=0
)
dashboard_summary = {
    "total_records": int(len(predictions_df)),
    "predicted_high_risk": int(predictions_df["Predicted_Risk"].sum()),
    "predicted_high_risk_pct": float(predictions_df["Predicted_Risk"].mean() * 100),
    "test_base_rate_pct": float(test_df["Risk"].mean() * 100),
    "alert_counts": {k: int(v) for k, v in alert_counts.items()},
    "top_zone": {
        "state": dangerous_zones.iloc[0]["State"],
        "county": dangerous_zones.iloc[0]["County"],
        "risk_score": float(dangerous_zones.iloc[0]["Risk_Score"]),
        "risk_level": dangerous_zones.iloc[0]["Risk_Level"],
    },
    "model_name": type(final_model).__name__,
    "decision_threshold": float(best_threshold),
}
with open(os.path.join(OUT_DIR, "dashboard_summary.json"), "w") as f:
    json.dump(dashboard_summary, f)
print("dashboard_summary.json written")

# ---------------------------------------------------------------------
# States / counties reference list (for the predictor form's dropdowns)
# ---------------------------------------------------------------------
pairs = pd.Series(county_risk.index.tolist(), name="pair")
states_counties = {}
for state_code, county_name in county_risk.index:
    states_counties.setdefault(state_code, []).append(county_name)
for state_code in states_counties:
    states_counties[state_code] = sorted(set(states_counties[state_code]))

with open(os.path.join(OUT_DIR, "states_counties.json"), "w") as f:
    json.dump(states_counties, f)
print(f"states_counties.json: {len(states_counties)} states, "
      f"{sum(len(v) for v in states_counties.values())} county entries")

# ---------------------------------------------------------------------
# Small scalars the backend needs at request time but shouldn't have to
# reload the full 6.7M-row CSV just to get.
# ---------------------------------------------------------------------
meta = {
    "global_risk_mean": global_risk_mean,
    "global_density_mean": float(county_density.mean()),
}
with open(os.path.join(OUT_DIR, "meta.json"), "w") as f:
    json.dump(meta, f)
print("meta.json written:", meta)

print("\nAll export files written to", OUT_DIR)
