"""Build the serving artifacts used to score the live map quickly.

From the full modeling table this produces two artifacts:

  county_profile.pkl  -- one row per (State, County): centroid coordinates,
                         mean road-infrastructure rates, and row count. Used to
                         give TIGER road segments an infrastructure profile
                         (which the road shapefile lacks) and for placement.

  serving_points.pkl  -- up to K representative rows per county (real coords +
                         infra flags), so state/county risk can be estimated by
                         scoring a faithful spatial sample and averaging, rather
                         than a single centroid (the model is non-linear).

Run with the project venv:
  webapp/backend/data/venv/Scripts/python.exe \
      webapp_v3/backend/pipeline/build_serving_table.py
"""
import os

import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "output")
ART = os.path.join(BASE, "..", "artifacts")

KEYS = ["State", "County"]
INFRA = ["Junction", "Crossing", "Traffic_Signal", "Stop", "Station", "Amenity"]
K = 50  # representative rows kept per county


def main():
    print("Loading modeling table ...")
    table = pd.read_pickle(os.path.join(OUT, "modeling_table.pkl"))
    print(f"rows: {len(table):,}")

    # --- county_profile: centroid + infra means + exposure count ------------
    agg = {"Start_Lat": ("Start_Lat", "mean"), "Start_Lng": ("Start_Lng", "mean")}
    agg.update({c: (c, "mean") for c in INFRA})
    agg["n_rows"] = ("Is_Accident", "size")
    agg["n_acc"] = ("Is_Accident", "sum")
    profile = table.groupby(KEYS).agg(**agg).reset_index()
    # CSV (not pickle) so the artifacts load on any pandas version.
    profile.to_csv(os.path.join(ART, "county_profile.csv"), index=False)
    print(f"county_profile: {len(profile):,} counties -> county_profile.csv")

    # --- serving_points: K representative rows per county -------------------
    cols = KEYS + ["Start_Lat", "Start_Lng"] + INFRA
    sample = (table[cols]
              .sample(frac=1.0, random_state=42)      # shuffle so head() is random
              .groupby(KEYS, sort=False)
              .head(K)
              .reset_index(drop=True))
    sample.to_csv(os.path.join(ART, "serving_points.csv"), index=False)
    print(f"serving_points: {len(sample):,} rows "
          f"(<= {K}/county) -> serving_points.csv")

    # --- city_lookup: map each city to its dominant county ------------------
    # Lets users search by city name even though the model scores by county.
    tc = table[table["City"].notna() & (table["City"].astype(str).str.strip() != "")]
    counts = tc.groupby(["City", "State", "County"]).size().reset_index(name="n")
    dom_idx = counts.groupby(["City", "State"])["n"].idxmax()
    dominant = counts.loc[dom_idx, ["City", "State", "County"]]
    city = (tc.groupby(["City", "State"])
            .agg(Start_Lat=("Start_Lat", "mean"), Start_Lng=("Start_Lng", "mean"),
                 n_acc=("Is_Accident", "sum"), n_rows=("Is_Accident", "size"))
            .reset_index()
            .merge(dominant, on=["City", "State"]))
    city.to_csv(os.path.join(ART, "city_lookup.csv"), index=False)
    print(f"city_lookup: {len(city):,} cities -> city_lookup.csv")


if __name__ == "__main__":
    main()
