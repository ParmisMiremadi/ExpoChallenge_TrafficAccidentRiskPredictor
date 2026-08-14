"""
Dataset reliability report for modeling_table.pkl.

Runs a battery of checks and prints numbers + percentages with PASS/WARN/FAIL
tags, so the final dataset can be trusted before any model is trained.
"""
import os

import joblib
import numpy as np
import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
TABLE_PATH = os.path.join(OUTPUT_DIR, "modeling_table.pkl")
FEATCOLS_PATH = os.path.join(OUTPUT_DIR, "feature_columns.pkl")

# Plausible bounds for the continental US + weather sanity.
BOUNDS = {
    "Start_Lat": (24, 50), "Start_Lng": (-125, -66),
    "Wx_Temp_C": (-50, 57), "Wx_Precip_mm": (0, 500),
    "Wx_Wind_kmh": (0, 200), "Wx_Humidity": (0, 100),
    "Wx_SnowDepth_mm": (0, 5000),
}
INFRA = ["Junction", "Crossing", "Traffic_Signal", "Stop", "Station", "Amenity"]


def tag(ok):
    return "PASS" if ok else "WARN"


def main():
    spec = joblib.load(FEATCOLS_PATH)
    feats = spec["features"]
    df = pd.read_pickle(TABLE_PATH)
    n = len(df)
    print("=" * 64)
    print(f"DATASET VALIDATION  —  {n:,} rows x {df.shape[1]} cols")
    print("=" * 64)

    # 1. Split + balance
    print("\n[1] SPLIT & LABEL BALANCE")
    yr = df.groupby("Year")["Is_Accident"].agg(["size", "mean"])
    for y, r in yr.iterrows():
        print(f"    {int(y)}: {int(r['size']):>9,} rows  |  accident rate {r['mean']*100:5.1f}%")
    overall = df["Is_Accident"].mean()
    print(f"    overall accident rate: {overall*100:.1f}%  [{tag(0.45 <= overall <= 0.55)}]")

    # 2. Null check on features
    print("\n[2] NULLS IN FEATURE COLUMNS")
    nulls = df[feats].isna().mean().sort_values(ascending=False)
    worst = nulls.head(5)
    for c, v in worst.items():
        print(f"    {c:<16} {v*100:5.2f}% null")
    print(f"    max null across features: {nulls.max()*100:.2f}%  [{tag(nulls.max() < 0.001)}]")

    # 3. Value ranges
    print("\n[3] VALUE RANGES (within plausible bounds)")
    for col, (lo, hi) in BOUNDS.items():
        pct = ((df[col] >= lo) & (df[col] <= hi)).mean() * 100
        print(f"    {col:<16} {pct:6.2f}% in [{lo},{hi}]  "
              f"(min {df[col].min():.1f}, max {df[col].max():.1f})  [{tag(pct > 99.5)}]")
    infra_ok = all(set(df[c].dropna().unique()) <= {0, 1} for c in INFRA)
    print(f"    infra flags all in {{0,1}}: {infra_ok}  [{tag(infra_ok)}]")
    cyc = ["Hour_sin", "Hour_cos", "Month_sin", "Month_cos"]
    cyc_ok = all(df[c].between(-1.001, 1.001).all() for c in cyc)
    print(f"    cyclical features in [-1,1]: {cyc_ok}  [{tag(cyc_ok)}]")

    # 4. Categoricals
    print("\n[4] CATEGORICAL VOCAB")
    print(f"    Season      : {sorted(df['Season'].unique())}")
    print(f"    Time_Period : {sorted(df['Time_Period'].unique())}")

    # 5. Leakage guard
    print("\n[5] LEAKAGE GUARD")
    bad = [c for c in ["Is_Accident", "Severity"] if c in feats]
    print(f"    target/severity NOT among features: {not bad}  [{tag(not bad)}]")

    # 6. Severity integrity
    print("\n[6] SEVERITY INTEGRITY")
    neg_zero = (df.loc[df["Is_Accident"] == 0, "Severity"] == 0).mean() * 100
    pos_valid = df.loc[df["Is_Accident"] == 1, "Severity"].between(1, 4).mean() * 100
    print(f"    negatives with Severity==0 : {neg_zero:5.1f}%  [{tag(neg_zero > 99.9)}]")
    print(f"    positives with Severity 1-4: {pos_valid:5.1f}%  [{tag(pos_valid > 99.9)}]")

    # 7. Duplicates
    print("\n[7] DUPLICATE ROWS")
    dup = df.duplicated().sum()
    print(f"    exact duplicate rows: {dup:,} ({dup/n*100:.3f}%)  [{tag(dup/n < 0.01)}]")

    # 8. Exposure/spatial sanity (busy vs quiet counties keep the signal)
    print("\n[8] EXPOSURE SIGNAL (busy counties should crash more)")
    cnt = df["County"].value_counts()
    rate = df.groupby("County")["Is_Accident"].mean()
    top = rate[cnt.head(5).index].mean() * 100
    bot = rate[cnt.tail(2000).index].mean() * 100
    print(f"    accident rate, 5 busiest counties : {top:.1f}%")
    print(f"    accident rate, quietest counties  : {bot:.1f}%")
    print(f"    busy > quiet (signal preserved): {top > bot}  [{tag(top > bot)}]")

    print("\n" + "=" * 64)
    print("VALIDATION COMPLETE")
    print("=" * 64)


if __name__ == "__main__":
    main()
