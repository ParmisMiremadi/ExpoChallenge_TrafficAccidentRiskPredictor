"""
Stage 2a: fetch daily historical weather for the grid dataset (Meteostat).

Every row in grid_dataset_v2.pkl (accidents and generated no-accident cells
alike) needs a weather reading taken from the SAME source, so that weather can
never act as a hidden label -- an accident row and a no-accident row on the same
day and place receive identical weather.

Source: Meteostat, which serves free bulk historical station observations (no
API key, no per-request credit limit). Each point is snapped to a 0.5-degree
grid and interpolated from up to five nearby stations, which fills the gaps a
single station would leave. A validation against an independent reanalysis put
temperature at corr 0.99 / MAE <1 C and precipitation at corr 0.78, with ~100%
coverage on the dates the grid uses.

Daily columns produced (metric):
    Wx_Temp_C        mean temperature (C)
    Wx_Precip_mm     total precipitation (mm)
    Wx_Wind_kmh      mean wind speed (km/h)
    Wx_Humidity      relative humidity (%)
    Wx_SnowDepth_mm  snow depth on the ground (mm)
    Wx_Adverse       1 if precipitation or lying snow raise driving risk

Day/night is not fetched here: it is astronomical, not weather, and is derived
per row from latitude/longitude/date/hour at the feature stage.

Output (webapp_v3/backend/pipeline/output/):
    weather_points.csv   map of point_id -> snapped (lat, lng)
    weather_daily.pkl    (point_id, Date) -> weather columns, reduced to the
                         dates the grid dataset actually uses

Usage (from the project root):
    ./webapp/backend/data/venv/Scripts/python.exe \
        webapp_v3/backend/pipeline/fetch_weather.py [max_points]

An integer max_points restricts the run to the first N points (smoke test).
"""
import os
import sys
import warnings

import numpy as np
import pandas as pd
import meteostat as ms

warnings.filterwarnings("ignore")

# --- Paths -------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
CACHE_DIR = os.path.join(BASE_DIR, "weather_cache")
GRID_PATH = os.path.join(OUTPUT_DIR, "grid_dataset_v2.pkl")
POINTS_CSV = os.path.join(OUTPUT_DIR, "weather_points.csv")
OUT_PATH = os.path.join(OUTPUT_DIR, "weather_daily.pkl")

# --- Weather grid ------------------------------------------------------------
GRID_DEG = 0.5                 # spatial snapping resolution (degrees)
NEARBY_RADIUS_M = 120_000      # search radius for stations to interpolate from
NEARBY_LIMIT = 5               # stations blended per point
MAX_RETRIES = 3

# Meteostat -> our column names (metric units are Meteostat's default).
COLUMN_MAP = {"temp": "Wx_Temp_C", "prcp": "Wx_Precip_mm", "wspd": "Wx_Wind_kmh",
              "rhum": "Wx_Humidity", "snwd": "Wx_SnowDepth_mm"}
WEATHER_COLS = list(COLUMN_MAP.values()) + ["Wx_Adverse"]


def snap(series):
    """Round coordinates to the weather grid so nearby rows share one request."""
    return (np.round(series / GRID_DEG) * GRID_DEG).round(2)


def fetch_point(lat, lng, start, end):
    """Daily weather for one point, interpolated from nearby stations.

    Returns a frame of Date + weather columns, or None if no station covers it."""
    pt = ms.Point(float(lat), float(lng))
    for attempt in range(MAX_RETRIES):
        try:
            near = ms.stations.nearby(pt, radius=NEARBY_RADIUS_M, limit=NEARBY_LIMIT)
            if near.empty:
                return None
            ts = ms.daily(list(near.index), start, end)
            if ts.count() == 0:
                return None
            try:
                ts = ms.interpolate(ts, pt)      # blend the nearby stations
            except Exception:
                pass                              # fall back to the raw blend
            df = ts.fetch()
            if df is None or df.empty:
                return None
            # Column labels can be plain strings or Parameter enums; normalise.
            df = df.reset_index()
            df.columns = [c.value if hasattr(c, "value") else str(c) for c in df.columns]
            time_col = "time" if "time" in df.columns else df.columns[0]
            out = pd.DataFrame({"Date": pd.to_datetime(df[time_col]).dt.strftime("%Y-%m-%d")})
            for src, dst in COLUMN_MAP.items():
                out[dst] = df[src].values if src in df.columns else np.nan
            # If a point returned several rows per day (multiple sources), keep
            # the first non-null per date.
            out = out.groupby("Date", as_index=False).first()
            snow = out["Wx_SnowDepth_mm"].fillna(0)
            precip = out["Wx_Precip_mm"].fillna(0)
            out["Wx_Adverse"] = ((precip > 0.5) | (snow > 0)).astype(int)
            return out
        except Exception:
            if attempt == MAX_RETRIES - 1:
                return None
    return None


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(CACHE_DIR, exist_ok=True)
    max_points = int(sys.argv[1]) if len(sys.argv) > 1 else None

    print("Loading grid dataset ...")
    grid = pd.read_pickle(GRID_PATH)
    grid["Start_Time"] = pd.to_datetime(grid["Start_Time"])
    grid["plat"] = snap(grid["Start_Lat"])
    grid["plng"] = snap(grid["Start_Lng"])

    points = grid[["plat", "plng"]].drop_duplicates().reset_index(drop=True)
    points["point_id"] = points.index
    grid = grid.merge(points, on=["plat", "plng"], how="left")
    grid["Date"] = grid["Start_Time"].dt.strftime("%Y-%m-%d")

    needed = grid[["point_id", "Date"]].drop_duplicates()
    needed_groups = {pid: g[["Date"]] for pid, g in needed.groupby("point_id")}

    start = grid["Start_Time"].min().to_pydatetime()
    end = grid["Start_Time"].max().to_pydatetime()
    points.to_csv(POINTS_CSV, index=False)
    print(f"Grid points: {len(points):,}  |  date range: {start.date()} -> {end.date()}")
    print(f"Needed (point,date) pairs: {len(needed):,}")

    todo = points if max_points is None else points.head(max_points)
    print(f"Fetching {len(todo):,} point(s) "
          f"({'SMOKE TEST' if max_points else 'FULL RUN'}) ...")

    misses = 0
    for n, row in enumerate(todo.itertuples(index=False), start=1):
        cache_file = os.path.join(CACHE_DIR, f"point_{row.point_id}.pkl")
        if os.path.exists(cache_file):
            continue
        df = fetch_point(row.plat, row.plng, start, end)
        if df is None:
            misses += 1
            df = pd.DataFrame(columns=["Date"] + WEATHER_COLS)
        else:
            need = needed_groups.get(row.point_id)
            if need is not None:
                df = df.merge(need, on="Date", how="inner")
        df.insert(0, "point_id", row.point_id)
        df.to_pickle(cache_file)
        print(f"  [{n}/{len(todo)}] point {row.point_id} "
              f"({row.plat},{row.plng}) -> {len(df):,} rows", end="\r")

    print(f"\nAssembling weather lookup from cache (points with no station: {misses}) ...")
    frames = []
    for pid in todo["point_id"]:
        cache_file = os.path.join(CACHE_DIR, f"point_{pid}.pkl")
        if os.path.exists(cache_file):
            frames.append(pd.read_pickle(cache_file))
    weather = pd.concat(frames, ignore_index=True)
    weather.to_pickle(OUT_PATH)

    print(f"Saved weather lookup: {len(weather):,} rows -> {OUT_PATH}")
    print("Column coverage (non-null %):")
    for col in WEATHER_COLS:
        pct = 100 * weather[col].notna().mean() if len(weather) else 0.0
        print(f"  {col:<16} {pct:5.1f}%")


if __name__ == "__main__":
    main()
