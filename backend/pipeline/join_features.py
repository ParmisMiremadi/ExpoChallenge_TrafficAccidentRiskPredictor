"""
Stage 3: join weather onto the grid dataset and engineer model features,
producing the single modeling table used for training.

Inputs (webapp_v3/backend/pipeline/output/):
    grid_dataset_v2.pkl   balanced positives + negatives (label Is_Accident)
    weather_points.csv    point_id -> snapped (lat, lng)
    weather_daily.pkl     (point_id, Date) -> daily weather columns

Join key: each row is snapped to the same 0.5-degree weather grid used by the
fetcher, mapped to its point_id, then merged on (point_id, Date). Weather comes
from one source for accident and no-accident rows alike, so it cannot act as a
hidden label.

Feature policy (see project notes):
    * model on road ATTRIBUTES + real conditions, never the Street identity;
    * NO accident-count exposure feature (circular with the synthetic negatives);
    * cyclical encodings for Hour/Month so 23:00 sits next to 00:00.

Output:
    output/modeling_table.pkl   features + target + keys for train/eval
    output/feature_columns.pkl  ordered feature list (categoricals flagged)
"""
import os

import joblib
import numpy as np
import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
GRID_PATH = os.path.join(OUTPUT_DIR, "grid_dataset_v2.pkl")
WPOINTS_PATH = os.path.join(OUTPUT_DIR, "weather_points.csv")
WDAILY_PATH = os.path.join(OUTPUT_DIR, "weather_daily.pkl")
OUT_PATH = os.path.join(OUTPUT_DIR, "modeling_table.pkl")
FEATCOLS_PATH = os.path.join(OUTPUT_DIR, "feature_columns.pkl")

GRID_DEG = 0.5
INFRA_FLAGS = ["Junction", "Crossing", "Traffic_Signal", "Stop", "Station", "Amenity"]
WEATHER_COLS = ["Wx_Temp_C", "Wx_Precip_mm", "Wx_Wind_kmh", "Wx_Humidity",
                "Wx_SnowDepth_mm", "Wx_Adverse"]
NUMERIC_FEATURES = (["Start_Lat", "Start_Lng", "Is_Weekend", "DayOfWeek",
                     "Hour_sin", "Hour_cos", "Month_sin", "Month_cos"]
                    + INFRA_FLAGS + WEATHER_COLS)
CATEGORICAL_FEATURES = ["Season", "Time_Period"]
FEATURE_COLUMNS = NUMERIC_FEATURES + CATEGORICAL_FEATURES

# Real-calendar weights used to de-bias the synthetic no-accident sample.
SEASON_OF_MONTH = {12: "Winter", 1: "Winter", 2: "Winter", 3: "Spring",
                   4: "Spring", 5: "Spring", 6: "Summer", 7: "Summer",
                   8: "Summer", 9: "Autumn", 10: "Autumn", 11: "Autumn"}
TP_HOURS = {"Morning Peak": 4, "Morning": 3, "Afternoon": 4,
            "Evening Peak": 4, "Night": 4, "Late Night": 5}


def snap(series):
    return (np.round(series / GRID_DEG) * GRID_DEG).round(2)


def match_negatives_to_calendar(grid, seed=42):
    """Subsample no-accident rows so their (Season, Time_Period, Is_Weekend)
    distribution matches the real calendar's opportunity distribution.

    The grid built negatives uniformly over condition combos, which made e.g.
    weekends ~52% of negatives vs the true ~29% -- turning Is_Weekend into an
    artificial separator. Re-weighting negatives to the real calendar makes those
    flags predictive only to the extent they genuinely are."""
    pos = grid[grid["Is_Accident"] == 1]
    neg = grid[grid["Is_Accident"] == 0].copy()
    dr = pd.date_range(grid["Start_Time"].min().normalize(),
                       grid["Start_Time"].max().normalize(), freq="D")
    cal = pd.DataFrame({"Season": [SEASON_OF_MONTH[m] for m in dr.month],
                        "Is_Weekend": (dr.dayofweek >= 5).astype(int)})
    days = cal.groupby(["Season", "Is_Weekend"]).size()
    target = {f"{s}|{tp}|{w}": d * h
              for (s, w), d in days.items() for tp, h in TP_HOURS.items()}
    total = sum(target.values())
    target = {k: v / total for k, v in target.items()}
    neg["_k"] = (neg["Season"] + "|" + neg["Time_Period"] + "|"
                 + neg["Is_Weekend"].astype(str))
    counts = neg["_k"].value_counts().to_dict()
    # Largest sample whose strata can all hit the target proportions.
    limiting = min(counts.get(k, 0) / p for k, p in target.items() if p > 0)
    rng = np.random.default_rng(seed)
    keep = []
    for k, p in target.items():
        idx = neg.index[neg["_k"] == k].to_numpy()
        n_keep = int(round(p * limiting))
        if len(idx) > n_keep:
            idx = rng.choice(idx, size=n_keep, replace=False)
        keep.append(idx)
    neg = neg.loc[np.concatenate(keep)].drop(columns="_k")
    return pd.concat([pos, neg], ignore_index=True)


def main():
    print("Loading grid dataset ...")
    grid = pd.read_pickle(GRID_PATH)
    grid["Start_Time"] = pd.to_datetime(grid["Start_Time"])
    before = len(grid)
    grid = match_negatives_to_calendar(grid)
    print(f"Calendar-matched negatives: {before:,} -> {len(grid):,} rows "
          f"(accident rate now {grid['Is_Accident'].mean()*100:.1f}%)")
    grid["plat"] = snap(grid["Start_Lat"])
    grid["plng"] = snap(grid["Start_Lng"])
    grid["Date"] = grid["Start_Time"].dt.strftime("%Y-%m-%d")

    # Map each row to its weather point, then join daily weather on (point, date).
    points = pd.read_csv(WPOINTS_PATH)
    grid = grid.merge(points, on=["plat", "plng"], how="left")
    weather = pd.read_pickle(WDAILY_PATH)
    grid = grid.merge(weather, on=["point_id", "Date"], how="left")

    matched = grid["Wx_Temp_C"].notna().mean()
    print(f"Weather match coverage: {matched*100:.1f}% of rows")
    if matched < 0.99:
        print("  NOTE: <99% -- weather fetch is probably still incomplete; "
              "re-run this once fetch_weather.py has finished all points.")

    # Meteostat returns weather values as object dtype -- coerce to numeric so
    # the model gets float columns (values are already clean numbers).
    for col in WEATHER_COLS:
        grid[col] = pd.to_numeric(grid[col], errors="coerce")

    # Fill weather gaps: snow depth absent = no snow; others = global median.
    grid["Wx_SnowDepth_mm"] = grid["Wx_SnowDepth_mm"].fillna(0)
    grid["Wx_Adverse"] = grid["Wx_Adverse"].fillna(0)
    for col in ["Wx_Temp_C", "Wx_Precip_mm", "Wx_Wind_kmh", "Wx_Humidity"]:
        grid[col] = grid[col].fillna(grid[col].median())

    # Cyclical time encodings (Hour/Month are periodic).
    grid["Hour_sin"] = np.sin(2 * np.pi * grid["Hour"] / 24)
    grid["Hour_cos"] = np.cos(2 * np.pi * grid["Hour"] / 24)
    grid["Month_sin"] = np.sin(2 * np.pi * (grid["Month"] - 1) / 12)
    grid["Month_cos"] = np.cos(2 * np.pi * (grid["Month"] - 1) / 12)

    # Keys/labels kept alongside features (Severity + road identity are NOT model
    # inputs -- they feed the severity aggregate and the map).
    keep = (FEATURE_COLUMNS + ["Is_Accident", "Severity", "Year", "Date",
                               "Start_Lat", "Start_Lng", "State", "County",
                               "City", "Street"])
    keep = list(dict.fromkeys(keep))          # dedupe columns, preserve order
    table = grid[keep].copy()

    before = len(table)
    table = table.drop_duplicates().reset_index(drop=True)
    print(f"Dropped {before - len(table):,} exact-duplicate rows -> {len(table):,} rows")

    table.to_pickle(OUT_PATH)
    joblib.dump({"features": FEATURE_COLUMNS,
                 "numeric": NUMERIC_FEATURES,
                 "categorical": CATEGORICAL_FEATURES}, FEATCOLS_PATH)

    print(f"\nSaved modeling table: {len(table):,} rows x {table.shape[1]} cols")
    print(f"  -> {OUT_PATH}")
    print(f"Features: {len(FEATURE_COLUMNS)} "
          f"({len(NUMERIC_FEATURES)} numeric + {len(CATEGORICAL_FEATURES)} categorical)")
    print("Rows per year:", table["Year"].value_counts().sort_index().to_dict())
    print("Accident rate:", round(table["Is_Accident"].mean(), 3))


if __name__ == "__main__":
    main()
