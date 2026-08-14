"""
Exploratory-analysis images for the v3 dataset -- the occurrence-framed
equivalent of the EDA section in Traffic_Accident_Risk_Predictor_v2.ipynb.

Reads the cleaned accident table (positives) and the modeling table (for weather
+ class balance), and saves PNGs to artifacts/plots/.
"""
import os

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
PLOTS_DIR = os.path.join(BASE_DIR, "..", "artifacts", "plots")
ACC_CSV = os.path.join(OUTPUT_DIR, "accidents_clean_2021_2023_v2.csv")
TABLE_PATH = os.path.join(OUTPUT_DIR, "modeling_table.pkl")

INFRA = ["Junction", "Crossing", "Traffic_Signal", "Stop", "Station", "Amenity"]
DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
WX = ["Wx_Temp_C", "Wx_Precip_mm", "Wx_Wind_kmh", "Wx_Humidity"]


def save(fig, name):
    fig.tight_layout()
    fig.savefig(os.path.join(PLOTS_DIR, name), dpi=120)
    plt.close(fig)
    print("  ", name)


def main():
    os.makedirs(PLOTS_DIR, exist_ok=True)
    acc = pd.read_csv(ACC_CSV, usecols=["Severity", "Hour", "DayOfWeek", "Month",
                                        "Year", "Time_Period", "State", "County",
                                        "Start_Lat", "Start_Lng"] + INFRA)
    print(f"Loaded {len(acc):,} accidents. Building EDA plots ...")

    # 1. Temporal patterns
    fig, ax = plt.subplots(2, 2, figsize=(13, 9))
    acc["Hour"].value_counts().sort_index().plot.bar(ax=ax[0, 0], color="C0")
    ax[0, 0].set_title("Accidents by hour of day"); ax[0, 0].set_xlabel("hour")
    acc["DayOfWeek"].value_counts().sort_index().plot.bar(ax=ax[0, 1], color="C1")
    ax[0, 1].set_title("Accidents by day of week"); ax[0, 1].set_xticklabels(DOW, rotation=0)
    acc["Month"].value_counts().sort_index().plot.bar(ax=ax[1, 0], color="C2")
    ax[1, 0].set_title("Accidents by month"); ax[1, 0].set_xlabel("month")
    acc["Year"].value_counts().sort_index().plot.bar(ax=ax[1, 1], color="C3")
    ax[1, 1].set_title("Accidents by year (2023 = Q1 only)")
    save(fig, "eda_temporal.png")

    # 2. Severity distribution + severity by time-of-day band
    fig, ax = plt.subplots(1, 2, figsize=(13, 5))
    (acc["Severity"].value_counts(normalize=True).sort_index() * 100).plot.bar(
        ax=ax[0], color="C4")
    ax[0].set_title("Severity distribution (%)"); ax[0].set_xlabel("severity (1-4)")
    order = ["Morning Peak", "Morning", "Afternoon", "Evening Peak", "Night", "Late Night"]
    acc.groupby("Time_Period")["Severity"].mean().reindex(order).plot.bar(ax=ax[1], color="C5")
    ax[1].set_title("Average severity by time-of-day"); ax[1].set_xticklabels(order, rotation=30, ha="right")
    save(fig, "eda_severity.png")

    # 3. Geographic accident density
    fig, ax = plt.subplots(figsize=(11, 6))
    hb = ax.hexbin(acc["Start_Lng"], acc["Start_Lat"], gridsize=110, cmap="inferno",
                   mincnt=1, bins="log")
    ax.set_xlim(-125, -66); ax.set_ylim(24, 50)
    ax.set_title("Accident geographic density (2021-2023)")
    ax.set_xlabel("Longitude"); ax.set_ylabel("Latitude")
    fig.colorbar(hb, label="log count")
    save(fig, "eda_geographic_density.png")

    # 4. Top states + counties
    fig, ax = plt.subplots(1, 2, figsize=(13, 6))
    acc["State"].value_counts().head(15)[::-1].plot.barh(ax=ax[0], color="C0")
    ax[0].set_title("Top 15 states by accident count")
    acc["County"].value_counts().head(15)[::-1].plot.barh(ax=ax[1], color="C1")
    ax[1].set_title("Top 15 counties by accident count")
    save(fig, "eda_top_locations.png")

    # 5. Road-feature prevalence at accidents
    fig, ax = plt.subplots(figsize=(8, 5))
    (acc[INFRA].mean() * 100).sort_values().plot.barh(ax=ax, color="C2")
    ax.set_title("Road features present at accident sites (%)")
    ax.set_xlabel("% of accidents")
    save(fig, "eda_road_features.png")

    # 6. Weather distributions at accidents (from modeling table positives)
    tbl = pd.read_pickle(TABLE_PATH)
    pos = tbl[tbl["Is_Accident"] == 1]
    fig, ax = plt.subplots(2, 2, figsize=(13, 9))
    for a, col in zip(ax.ravel(), WX):
        pos[col].plot.hist(ax=a, bins=50, color="C0")
        a.set_title(col); a.set_ylabel("")
    fig.suptitle("Weather conditions at accidents", fontsize=13)
    save(fig, "eda_weather.png")

    # 7. Numeric feature correlation heatmap
    num = ["Start_Lat", "Start_Lng", "Is_Weekend", "DayOfWeek"] + INFRA + WX + ["Is_Accident"]
    corr = tbl[num].sample(min(300000, len(tbl)), random_state=0).corr()
    fig, ax = plt.subplots(figsize=(11, 9))
    im = ax.imshow(corr, cmap="coolwarm", vmin=-1, vmax=1)
    ax.set_xticks(range(len(num))); ax.set_xticklabels(num, rotation=90)
    ax.set_yticks(range(len(num))); ax.set_yticklabels(num)
    ax.set_title("Feature correlation")
    fig.colorbar(im)
    save(fig, "eda_correlation.png")

    # 8. Class balance / calendar-match proof
    fig, ax = plt.subplots(1, 2, figsize=(12, 5))
    wk = tbl.groupby("Is_Accident")["Is_Weekend"].mean() * 100
    ax[0].bar(["No-accident", "Accident"], [wk[0], wk[1]], color=["C7", "C3"])
    ax[0].axhline(100 * 2 / 7, ls="--", color="k", label="real calendar (28.6%)")
    ax[0].set_title("Weekend share (calendar-matched)"); ax[0].set_ylabel("% weekend"); ax[0].legend()
    tbl.groupby("Year")["Is_Accident"].mean().mul(100).plot.bar(ax=ax[1], color="C4")
    ax[1].set_title("Accident rate per year in dataset"); ax[1].set_ylabel("%")
    save(fig, "eda_class_balance.png")

    print("Saved EDA plots ->", os.path.abspath(PLOTS_DIR))


if __name__ == "__main__":
    main()
