"""
Stage 1 (v3): clean the RAW US Accidents file AND build the balanced,
street-level grid dataset for occurrence modelling.

Two parts, one file (per the current step -- later stages split out):

PART A -- CLEAN
    Read US_Accidents_March23.csv, keep 2021-2023, drop duplicates, keep only
    the columns we need. Weather is intentionally NOT kept (it will be fetched
    from Open-Meteo in a later stage). End_Lat/End_Lng (all null), Zipcode,
    Distance, ID, the twilight/day-night flags, and the near-constant infra
    flags are dropped as redundant.

PART B -- GRID  (balanced no-accident data)
    A "condition" is (road x Season x Time_Period x Is_Weekend), where a road is
    (State, County, City, Street). Every cleaned accident row is a POSITIVE
    (Severity 1-4). For NEGATIVES we take road/condition combinations that never
    appear in the accident data and label them Severity = 0 ("no accident").

    Negatives are drawn UNIFORMLY across the whole road x condition space (not a
    fixed count per county). This preserves exposure: busy roads saturate their
    conditions and stay mostly positive, quiet roads stay mostly negative -- so
    the model still learns that busy places crash more often. Forcing an equal
    positive/negative count *within* each county would erase that signal.

    We draw as many negatives as there are accident rows -> a 1:1 balance.
    Each negative is given the road's centroid coordinates and a synthetic
    timestamp consistent with its (Season, Is_Weekend, Time_Period), so it is a
    fully-specified spatiotemporal point ready for the later weather join.

Run (from the project root):
    ./webapp/backend/data/venv/Scripts/python.exe \
        webapp_v3/backend/pipeline/clean_dataset_v2.py

Outputs (webapp_v3/backend/pipeline/output/):
    accidents_clean_2021_2023_v2.csv   cleaned per-accident table (positives)
    grid_dataset_v2.pkl                balanced positives + negatives (1:1)
"""
import os

import numpy as np
import pandas as pd

# --- Paths -------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(BASE_DIR, "..", "..", ".."))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")

RAW = os.path.join(PROJECT_ROOT, "US_Accidents_March23.csv")
CLEAN_OUT = os.path.join(OUTPUT_DIR, "accidents_clean_2021_2023_v2.csv")
GRID_OUT = os.path.join(OUTPUT_DIR, "grid_dataset_v2.pkl")

RANDOM_STATE = 42

# --- Columns -----------------------------------------------------------------
INFRA_FLAGS = ["Junction", "Crossing", "Traffic_Signal", "Stop", "Station", "Amenity"]
ROAD_KEYS = ["State", "County", "City", "Street"]

USECOLS = ["Severity", "Start_Time", "Start_Lat", "Start_Lng",
           "Street", "City", "County", "State"] + INFRA_FLAGS

# --- Condition / grid vocab --------------------------------------------------
SEASONS = ["Winter", "Spring", "Summer", "Autumn"]
TIME_PERIODS = ["Morning Peak", "Morning", "Afternoon", "Evening Peak",
                "Night", "Late Night"]
N_COND = len(SEASONS) * len(TIME_PERIODS) * 2   # 4 x 6 x 2 = 48 per road

SEASON_OF_MONTH = {12: "Winter", 1: "Winter", 2: "Winter",
                   3: "Spring", 4: "Spring", 5: "Spring",
                   6: "Summer", 7: "Summer", 8: "Summer",
                   9: "Autumn", 10: "Autumn", 11: "Autumn"}
TIME_PERIOD_HOURS = {
    "Morning Peak": [5, 6, 7, 8],
    "Morning": [9, 10, 11],
    "Afternoon": [12, 13, 14, 15],
    "Evening Peak": [16, 17, 18, 19],
    "Night": [20, 21, 22, 23],
    "Late Night": [0, 1, 2, 3, 4],
}
SEASON_IDX = {s: i for i, s in enumerate(SEASONS)}
TP_IDX = {p: i for i, p in enumerate(TIME_PERIODS)}


def time_period(hour):
    if 5 <= hour < 9:   return "Morning Peak"
    if 9 <= hour < 12:  return "Morning"
    if 12 <= hour < 16: return "Afternoon"
    if 16 <= hour < 20: return "Evening Peak"
    if 20 <= hour < 24: return "Night"
    return "Late Night"


# =============================================================================
# PART A -- CLEAN
# =============================================================================
def clean():
    print("[A] Reading raw file in chunks and filtering to 2021-2023 ...")
    parts, rows_seen = [], 0
    for chunk in pd.read_csv(RAW, usecols=USECOLS, chunksize=500_000,
                             low_memory=False):
        rows_seen += len(chunk)
        chunk["Start_Time"] = pd.to_datetime(chunk["Start_Time"], errors="coerce")
        yr = chunk["Start_Time"].dt.year
        parts.append(chunk[(yr >= 2021) & (yr <= 2023)])
        print(f"    scanned {rows_seen:,} rows", end="\r")

    df = pd.concat(parts, ignore_index=True)
    print(f"\n[A] Kept {len(df):,} rows from 2021-2023.")

    # Dedup: exact-row, then collapse same-time-same-coordinate re-reports.
    before = len(df)
    df = df.drop_duplicates()
    print(f"[A] After exact-row dedup:      {len(df):,}  (-{before - len(df):,})")
    before = len(df)
    df = df.drop_duplicates(subset=["Start_Time", "Start_Lat", "Start_Lng"],
                            keep="first")
    print(f"[A] After time+coord dedup:     {len(df):,}  (-{before - len(df):,})")

    # Valid keys.
    before = len(df)
    df = df.dropna(subset=["Start_Time", "Start_Lat", "Start_Lng", "State", "County"])
    print(f"[A] After valid-key filter:     {len(df):,}  (-{before - len(df):,})")

    # Infra flags -> 0/1.
    for col in INFRA_FLAGS:
        df[col] = df[col].fillna(False).astype(int)

    # Road-identity text: normalise nulls to "" ("" Street = unknown road).
    df["City"] = df["City"].fillna("").astype(str)
    df["Street"] = df["Street"].fillna("").astype(str)

    # Time features (the ones the grid + later stages need).
    t = df["Start_Time"]
    df["Year"] = t.dt.year
    df["Month"] = t.dt.month
    df["Hour"] = t.dt.hour
    df["DayOfWeek"] = t.dt.dayofweek
    df["Is_Weekend"] = (df["DayOfWeek"] >= 5).astype(int)
    df["Season"] = df["Month"].map(SEASON_OF_MONTH)
    df["Time_Period"] = df["Hour"].map(time_period)

    df.to_csv(CLEAN_OUT, index=False)
    print(f"[A] Saved cleaned positives: {len(df):,} rows x {df.shape[1]} cols")
    print(f"    -> {CLEAN_OUT}")
    print("[A] Rows per year:",
          df["Year"].value_counts().sort_index().to_dict())
    for col in ["Street", "City"]:
        print(f"    {col} non-empty: {100 * (df[col] != '').mean():.1f}%")
    return df


# =============================================================================
# PART B -- GRID (balanced negatives)
# =============================================================================
def sample_negatives(pos_cells, n_roads, total_neg):
    """Draw accident-free (road_idx, condition_idx) cells uniformly across the
    whole road x condition space -- exposure-preserving (see module docstring).
    Mirrors the fixed v2 sampler but keyed on roads instead of counties."""
    rng = np.random.default_rng(RANDOM_STATE)
    picked = set()
    while len(picked) < total_neg:
        size = min(2_000_000, (total_neg - len(picked)) * 2)
        r = rng.integers(0, n_roads, size=size)
        c = rng.integers(0, N_COND, size=size)
        for a, b in zip(r.tolist(), c.tolist()):
            cell = (a, b)
            if cell not in pos_cells and cell not in picked:
                picked.add(cell)
                if len(picked) >= total_neg:
                    break
    return list(picked)


def build_grid(df):
    print("\n[B] Building street-level road universe ...")
    # A road must have a known Street to be identifiable / routable.
    known = df[df["Street"] != ""].copy()

    agg = {"Start_Lat": ("Start_Lat", "mean"), "Start_Lng": ("Start_Lng", "mean")}
    for col in INFRA_FLAGS:
        agg[col] = (col, "max")   # road "has" the feature if any accident saw it
    roads = known.groupby(ROAD_KEYS, dropna=False).agg(**agg).reset_index()
    roads["road_idx"] = np.arange(len(roads))
    n_roads = len(roads)
    print(f"[B] Distinct routable roads: {n_roads:,}")
    print(f"[B] Road x condition space:  {n_roads * N_COND:,} cells")

    # Positive cells = observed accident (road, condition) combos on known roads.
    known = known.merge(roads[ROAD_KEYS + ["road_idx"]], on=ROAD_KEYS, how="left")
    cond_idx = (known["Season"].map(SEASON_IDX) * (len(TIME_PERIODS) * 2)
                + known["Time_Period"].map(TP_IDX) * 2
                + known["Is_Weekend"])
    pos_cells = set(zip(known["road_idx"].to_numpy(), cond_idx.to_numpy()))
    print(f"[B] Distinct positive cells: {len(pos_cells):,}")

    # 1:1 with the number of accident rows (positives), capped by what exists.
    total_neg = len(df)
    available = n_roads * N_COND - len(pos_cells)
    if total_neg > available:
        print(f"[B] WARNING: requested {total_neg:,} negatives but only "
              f"{available:,} free cells exist -- capping.")
        total_neg = available

    print(f"[B] Sampling {total_neg:,} negative cells ...")
    picked = sample_negatives(pos_cells, n_roads, total_neg)
    picked_r = np.fromiter((r for r, _ in picked), dtype=np.int64, count=len(picked))
    picked_c = np.fromiter((c for _, c in picked), dtype=np.int64, count=len(picked))

    # Decode condition index -> Season / Time_Period / Is_Weekend.
    season_i = picked_c // (len(TIME_PERIODS) * 2)
    rem = picked_c % (len(TIME_PERIODS) * 2)
    tp_i = rem // 2
    weekend = rem % 2

    neg = roads.iloc[picked_r].reset_index(drop=True)
    neg["Severity"] = 0
    neg["Season"] = [SEASONS[i] for i in season_i]
    neg["Time_Period"] = [TIME_PERIODS[i] for i in tp_i]
    neg["Is_Weekend"] = weekend.astype(int)

    # Synthetic timestamp consistent with (Season, Is_Weekend, Time_Period).
    print("[B] Assigning synthetic timestamps to negatives ...")
    rng = np.random.default_rng(RANDOM_STATE + 1)
    dmin, dmax = df["Start_Time"].min().normalize(), df["Start_Time"].max().normalize()
    all_dates = pd.date_range(dmin, dmax, freq="D")
    d_season = all_dates.month.map(SEASON_OF_MONTH)
    d_weekend = (all_dates.dayofweek >= 5).astype(int)
    # Pools of candidate dates per (season, is_weekend).
    pools = {}
    for s in SEASONS:
        for w in (0, 1):
            mask = (d_season == s) & (d_weekend == w)
            pools[(s, w)] = all_dates[mask]

    # Vectorised per group: only a handful of (season, weekend) and time-period
    # groups, so we sample each group's rows in one shot instead of row-by-row.
    chosen = np.empty(len(neg), dtype="datetime64[ns]")
    for (s, w), pos_ix in neg.groupby(["Season", "Is_Weekend"]).indices.items():
        pool = pools[(s, int(w))].values
        chosen[pos_ix] = pool[rng.integers(0, len(pool), size=len(pos_ix))]
    hour_arr = np.empty(len(neg), dtype=np.int64)
    for tp, pos_ix in neg.groupby("Time_Period").indices.items():
        hrs = np.asarray(TIME_PERIOD_HOURS[tp])
        hour_arr[pos_ix] = hrs[rng.integers(0, len(hrs), size=len(pos_ix))]
    neg["Start_Time"] = chosen + (hour_arr * np.timedelta64(1, "h"))

    t = pd.to_datetime(neg["Start_Time"])
    neg["Year"] = t.dt.year
    neg["Month"] = t.dt.month
    neg["Hour"] = t.dt.hour
    neg["DayOfWeek"] = t.dt.dayofweek
    neg = neg.drop(columns=["road_idx"])

    # Assemble: positives (as-is) + negatives, aligned columns.
    cols = (["Severity", "Start_Time", "Start_Lat", "Start_Lng"] + ROAD_KEYS
            + INFRA_FLAGS + ["Year", "Month", "Hour", "DayOfWeek",
                             "Is_Weekend", "Season", "Time_Period"])
    pos = df.copy()
    pos["Is_Accident"] = 1
    neg["Is_Accident"] = 0
    grid = pd.concat([pos[cols + ["Is_Accident"]], neg[cols + ["Is_Accident"]]],
                     ignore_index=True)
    grid = grid.sample(frac=1.0, random_state=RANDOM_STATE).reset_index(drop=True)

    grid.to_pickle(GRID_OUT)
    print(f"[B] Saved grid dataset: {len(grid):,} rows "
          f"(positives {len(pos):,} / negatives {len(neg):,})")
    print(f"    -> {GRID_OUT}")
    print(f"[B] Overall accident rate: {grid['Is_Accident'].mean()*100:.1f}%")

    # Exposure sanity: busiest counties should keep a higher accident rate.
    rate = grid.groupby("County")["Is_Accident"].mean()
    cnt = df["County"].value_counts()
    top = cnt.head(5).index
    bottom = cnt.tail(5).index
    print("[B] Accident rate in 5 busiest counties:",
          {c: round(rate.get(c, float('nan')), 2) for c in top})
    print("[B] Accident rate in 5 quietest counties:",
          {c: round(rate.get(c, float('nan')), 2) for c in bottom})


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    df = clean()
    build_grid(df)


if __name__ == "__main__":
    main()
