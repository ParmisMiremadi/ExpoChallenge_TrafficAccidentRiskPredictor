"""Precompute model features for every primary-road segment.

The road shapefile has geometry + route type but none of the infrastructure
flags the model needs, so each road is given:

  - Start_Lat/Start_Lng : its geometry midpoint (real spatial signal)
  - infra flags         : from its nearest county's profile, adjusted by road
                          class (interstates are limited-access: no signals /
                          stops / crossings, only junctions/interchanges)
  - _gidx               : nearest weather-grid index

Rows are written in the SAME order as primary_roads.geojson features, so the
frontend can color feature[i] by the served risk of row i.
"""
import json
import os
import sys

import numpy as np
import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(BASE, "..")))  # for weather_service
ART = os.path.join(BASE, "..", "artifacts")
GEOJSON = os.path.join(BASE, "..", "..", "frontend", "data", "primary_roads.geojson")

INFRA = ["Junction", "Crossing", "Traffic_Signal", "Stop", "Station", "Amenity"]
# Infra a limited-access interstate does NOT have at grade.
INTERSTATE_ZERO = ["Crossing", "Traffic_Signal", "Stop"]


def nearest_county(mid, centroids, chunk=2000):
    """Index of nearest county centroid for each road midpoint (chunked)."""
    idx = np.empty(len(mid), dtype=int)
    for i in range(0, len(mid), chunk):
        m = mid[i:i + chunk]
        d = ((m[:, None, 0] - centroids[None, :, 0]) ** 2 +
             (m[:, None, 1] - centroids[None, :, 1]) ** 2)
        idx[i:i + chunk] = d.argmin(axis=1)
    return idx


def main():
    import weather_service as ws  # local import so grid consts are available

    with open(GEOJSON, "r") as f:
        feats = json.load(f)["features"]

    mids, rttyp = [], []
    for ft in feats:
        c = ft["geometry"]["coordinates"]
        lng, lat = c[len(c) // 2]          # geojson is [lng, lat]
        mids.append((lat, lng))
        rttyp.append(ft["properties"]["rttyp"])
    mids = np.array(mids)
    print(f"roads: {len(mids):,}")

    profile = pd.read_csv(os.path.join(ART, "county_profile.csv"), keep_default_na=False)
    centroids = profile[["Start_Lat", "Start_Lng"]].to_numpy()
    ci = nearest_county(mids, centroids)
    county = profile.iloc[ci].reset_index(drop=True)

    df = pd.DataFrame({"Start_Lat": mids[:, 0], "Start_Lng": mids[:, 1],
                       "rttyp": rttyp})
    for c in INFRA:
        df[c] = county[c].to_numpy()
    is_i = df["rttyp"].to_numpy() == "I"
    for c in INTERSTATE_ZERO:
        df.loc[is_i, c] = 0.0
    df["_gidx"] = ws.nearest_index(df["Start_Lat"].to_numpy(),
                                   df["Start_Lng"].to_numpy())

    # CSV (not pickle) so the artifact loads on any pandas version.
    df.to_csv(os.path.join(ART, "road_features.csv"), index=False)
    print(f"road_features: {len(df):,} rows -> road_features.csv")


if __name__ == "__main__":
    main()
