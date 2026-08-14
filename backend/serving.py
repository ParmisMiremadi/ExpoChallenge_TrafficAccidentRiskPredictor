"""Live scoring of the map, dangerous zones, and forecast from the serving
sample + weather grid.

For a requested hour (and today's date) the temporal features and coarse-grid
weather are stamped onto the per-county serving points, the model is run, and
results are aggregated to county and state. Aggregates are cached per
(date, hour, weather-version) so the hour slider is instant after the first hit.

Conventions mirror the training pipeline exactly (clean_dataset_v2 /
join_features): Season by month, Time_Period by hour band, Month cyclic on
(month-1), DayOfWeek Monday=0.
"""
import datetime
import os
import threading

import numpy as np
import pandas as pd

import model_service as ms
import weather_service as ws

ART = os.path.join(os.path.dirname(os.path.abspath(__file__)), "artifacts")

SEASON_OF_MONTH = {12: "Winter", 1: "Winter", 2: "Winter",
                   3: "Spring", 4: "Spring", 5: "Spring",
                   6: "Summer", 7: "Summer", 8: "Summer",
                   9: "Autumn", 10: "Autumn", 11: "Autumn"}

STATE_FULL = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho",
    "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi",
    "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
    "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina",
    "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah",
    "VT": "Vermont", "VA": "Virginia", "WA": "Washington", "WV": "West Virginia",
    "WI": "Wisconsin", "WY": "Wyoming", "DC": "District of Columbia",
}

_pts = None
_state_sev = None
_county_meta = None       # indexed by (State, County): centroid, infra, n_acc, severity
_infra_hi = None          # infra-rate cutoffs (per-column median) for "dense" flags
_acc_hi = None            # n_acc cutoff for "high-exposure" flag
_city_state = None        # (city_lower, STATE) -> dominant county + centroid
_city_any = None          # city_lower -> best-by-exposure county across states
_road_feats = None        # per primary-road features, aligned to geojson order
_agg_cache = {}
_road_cache = {}
_lock = threading.Lock()

INFRA = ["Junction", "Crossing", "Traffic_Signal", "Stop", "Station", "Amenity"]


def _load():
    global _pts, _state_sev, _county_meta, _infra_hi, _acc_hi
    if _pts is not None:
        return _pts

    pts = pd.read_csv(os.path.join(ART, "serving_points.csv"), keep_default_na=False)
    pts["_gidx"] = ws.nearest_index(pts["Start_Lat"].to_numpy(),
                                    pts["Start_Lng"].to_numpy())
    _pts = pts

    # Per-road severity -> per-state and per-county weighted means.
    sev = pd.read_csv(os.path.join(ART, "severity_by_road.csv"), keep_default_na=False)
    parts = sev["road"].str.split("|")
    sev["State"] = parts.str[0]
    sev["County"] = parts.str[1]
    _state_sev = (sev.groupby("State")
                  .apply(lambda d: np.average(d["severity"], weights=d["count"]))
                  .to_dict())
    cty_sev = (sev.groupby(["State", "County"])
               .apply(lambda d: np.average(d["severity"], weights=d["count"]))
               .rename("severity"))

    profile = pd.read_csv(os.path.join(ART, "county_profile.csv"), keep_default_na=False)
    meta = profile.merge(cty_sev, on=["State", "County"], how="left")
    meta["severity"] = meta["severity"].fillna(float(np.mean(list(_state_sev.values()))))
    _county_meta = meta.set_index(["State", "County"])
    _infra_hi = {c: float(profile[c].quantile(0.75)) for c in INFRA}
    _acc_hi = float(profile["n_acc"].quantile(0.75))

    # City -> county lookups so users can search by city name.
    global _city_state, _city_any
    cl = pd.read_csv(os.path.join(ART, "city_lookup.csv"), keep_default_na=False)
    _city_state = {}
    for r in cl.itertuples(index=False):
        _city_state[(r.City.lower(), r.State)] = (r.County, r.Start_Lat, r.Start_Lng)
    _city_any = {}
    for r in cl.sort_values("n_acc", ascending=False).itertuples(index=False):
        _city_any.setdefault(r.City.lower(), (r.State, r.County, r.Start_Lat, r.Start_Lng))
    return _pts


def time_period(hour):
    if 5 <= hour < 9:   return "Morning Peak"
    if 9 <= hour < 12:  return "Morning"
    if 12 <= hour < 16: return "Afternoon"
    if 16 <= hour < 20: return "Evening Peak"
    if 20 <= hour < 24: return "Night"
    return "Late Night"


def hour_label(h):
    ap = "am" if h < 12 else "pm"
    hr = h % 12
    return f"{12 if hr == 0 else hr}{ap}"


def temporal_features(date, hour):
    dow = date.weekday()
    return {
        "Is_Weekend": int(dow >= 5),
        "DayOfWeek": dow,
        "Hour_sin": np.sin(2 * np.pi * hour / 24),
        "Hour_cos": np.cos(2 * np.pi * hour / 24),
        "Month_sin": np.sin(2 * np.pi * (date.month - 1) / 12),
        "Month_cos": np.cos(2 * np.pi * (date.month - 1) / 12),
        "Season": SEASON_OF_MONTH[date.month],
        "Time_Period": time_period(hour),
    }


def _quantile_tiers(values):
    """Relative tier cutoffs from the [.50,.80,.95] quantiles of `values`."""
    q = np.quantile(np.asarray(values, dtype=float), [0.50, 0.80, 0.95])

    def tier(v):
        if v >= q[2]: return "Critical"
        if v >= q[1]: return "High"
        if v >= q[0]: return "Medium"
        return "Low"
    return tier


def _score_points(hour, date, points=None):
    df = (_load() if points is None else points).copy()
    for k, v in temporal_features(date, hour).items():
        df[k] = v
    for k, v in ws.features_for(df["_gidx"].to_numpy(), 0, hour).items():
        df[k] = v
    df["prob"] = ms.predict(df)["prob"]
    return df


def _aggregates(hour, date):
    """Cached (state_prob Series, county_prob Series) for an hour/date."""
    key = (date.isoformat(), int(hour), ws._state["ts"])
    with _lock:
        if key in _agg_cache:
            return _agg_cache[key]
    df = _score_points(hour, date)
    state = df.groupby("State")["prob"].mean()
    county = df.groupby(["State", "County"])["prob"].mean()
    with _lock:
        _agg_cache[key] = (state, county)
    return state, county


# --------------------------------------------------------------------------- #
# Live risk map (state choropleth)                                            #
# --------------------------------------------------------------------------- #
def compute(hour, date=None, metric="risk"):
    date = date or datetime.date.today()
    state, county = _aggregates(hour, date)

    pi_true = ms._load()["calibration"]["pi_true"]
    sev_map = {abbr: float(_state_sev.get(abbr, 2.0)) for abbr in state.index}
    sev_tier = _quantile_tiers(list(sev_map.values())) if metric == "severity" else None

    states = {}
    for abbr, prob in state.items():
        full = STATE_FULL.get(abbr, abbr)
        sev = sev_map[abbr]
        tier = sev_tier(sev) if metric == "severity" else str(ms.tier_of(prob))
        states[full] = {
            "risk": round(float(prob), 6),
            "prob": round(float(prob), 6),
            "score": int(ms.score_of(prob)),
            "x_baseline": round(float(prob) / pi_true, 1),
            "severity": round(sev, 2),
            "tier": tier,
            "value": round(sev / 4.0, 3) if metric == "severity" else round(float(prob), 6),
        }

    top_abbr = max(sev_map, key=sev_map.get) if metric == "severity" else state.idxmax()
    high = sum(1 for s in states.values() if s["tier"] in ("High", "Critical"))
    # "Active alerts" counts High+Critical COUNTIES (finer grain than states) so
    # the tile stays meaningful even when no whole-state average reaches a top
    # tier, and stays distinct from the state-level "high-risk zones" count.
    county_tiers = ms.tier_of(county.to_numpy())
    alerts = int(np.isin(county_tiers, ["High", "Critical"]).sum())
    return {
        "level": "state", "hour": int(hour), "metric": metric,
        "time_period": time_period(hour), "states": states,
        "summary": {"total": len(states), "high_risk": high, "alerts": alerts,
                    "top_zone": STATE_FULL.get(top_abbr, top_abbr)},
    }


# --------------------------------------------------------------------------- #
# Location search suggestions (autocomplete)                                   #
# --------------------------------------------------------------------------- #
_suggest_idx = None


def _build_suggest_index():
    """Flat searchable list of states, counties, and cities (with centroids),
    built once and reused for every autocomplete request."""
    global _suggest_idx
    if _suggest_idx is not None:
        return _suggest_idx
    _load()
    items = []

    prof = _county_meta.reset_index()
    # States (centroid = mean of the state's county centroids).
    st_cent = prof.groupby("State")[["Start_Lat", "Start_Lng"]].mean()
    for abbr, row in st_cent.iterrows():
        full = STATE_FULL.get(abbr, abbr)
        items.append({"label": full, "type": "state",
                      "q": f"{full} {abbr}".lower(),
                      "lat": float(row["Start_Lat"]), "lng": float(row["Start_Lng"]),
                      "state": full, "county": "", "weight": 50000.0})

    # Counties.
    for r in prof.itertuples(index=False):
        lab = f"{r.County}, {r.State}"
        items.append({"label": lab, "type": "county", "q": lab.lower(),
                      "lat": float(r.Start_Lat), "lng": float(r.Start_Lng),
                      "state": STATE_FULL.get(r.State, r.State), "county": r.County,
                      "weight": float(r.n_acc)})

    # Cities.
    cl = pd.read_csv(os.path.join(ART, "city_lookup.csv"), keep_default_na=False)
    for r in cl.itertuples(index=False):
        lab = f"{r.City}, {r.State}"
        items.append({"label": lab, "type": "city", "q": lab.lower(),
                      "lat": float(r.Start_Lat), "lng": float(r.Start_Lng),
                      "state": STATE_FULL.get(r.State, r.State), "county": r.County,
                      "weight": float(r.n_acc)})

    _suggest_idx = items
    return items


def suggest(q, limit=8):
    """Ranked location suggestions for a partial query. Prefix matches and more
    accident-heavy (better-known) places rank higher; states rank above cities,
    cities above counties, for an equally good text match."""
    q = (q or "").strip().lower()
    if len(q) < 2:
        return []
    type_boost = {"state": 400, "city": 150, "county": 80}
    scored = []
    for it in _build_suggest_index():
        lab = it["q"]
        pos = lab.find(q)
        if pos < 0:
            continue
        if lab.startswith(q):
            score = 3000
        elif any(tok.startswith(q) for tok in lab.replace(",", " ").split()):
            score = 1500
        else:
            score = 500 - pos
        score += type_boost.get(it["type"], 0)
        score += min(it["weight"], 20000.0) / 20000.0 * 200
        scored.append((score, it))

    scored.sort(key=lambda x: x[0], reverse=True)
    out, seen = [], set()
    for _, it in scored:
        key = (it["label"], it["type"])
        if key in seen:
            continue
        seen.add(key)
        out.append({"label": it["label"], "type": it["type"],
                    "lat": it["lat"], "lng": it["lng"],
                    "state": it["state"], "county": it["county"]})
        if len(out) >= limit:
            break
    return out


# --------------------------------------------------------------------------- #
# County-level scoring (choropleth shown when zooming into the state map)      #
# --------------------------------------------------------------------------- #
def compute_counties(hour, date=None, metric="risk"):
    """Per-county risk + severity for the current hour, keyed by "STATE|County"
    (state abbreviation + county name) so the frontend can join it to a counties
    GeoJSON. Same model + calibration as the state choropleth, just not
    aggregated up to the state level."""
    date = date or datetime.date.today()
    _load()
    _, county = _aggregates(hour, date)

    # Severity per county from the county metadata (weighted per-road means).
    sev_series = _county_meta["severity"]

    sev_tier = (_quantile_tiers(sev_series.to_numpy())
                if metric == "severity" else None)

    counties = {}
    for (abbr, name), prob in county.items():
        prob = float(prob)
        try:
            sev = float(sev_series.loc[(abbr, name)])
        except KeyError:
            sev = 2.0
        tier = sev_tier(sev) if metric == "severity" else str(ms.tier_of(prob))
        counties[f"{abbr}|{name}"] = {
            "risk": round(prob, 6),
            "prob": round(prob, 6),
            "severity": round(sev, 2),
            "tier": tier,
            "state": STATE_FULL.get(abbr, abbr),
            "county": name,
            "value": round(sev / 4.0, 3) if metric == "severity" else round(prob, 6),
        }

    return {
        "level": "county", "hour": int(hour), "metric": metric,
        "time_period": time_period(hour), "counties": counties,
    }


# --------------------------------------------------------------------------- #
# Road-level scoring (primary-road network)                                   #
# --------------------------------------------------------------------------- #
def _load_roads():
    global _road_feats
    if _road_feats is None:
        _road_feats = pd.read_csv(os.path.join(ART, "road_features.csv"), keep_default_na=False)
    return _road_feats


def score_locations(lats, lngs, hour=None, date=None):
    """Calibrated accident probability for arbitrary points (infra from the
    nearest county, weather from the grid, temporal from the given hour).
    Used to score route geometries."""
    _load()
    date = date or datetime.date.today()
    if hour is None:
        hour = datetime.datetime.now().hour
    lats = np.asarray(lats, dtype=float)
    lngs = np.asarray(lngs, dtype=float)

    prof = _county_meta.reset_index()
    cent = prof[["Start_Lat", "Start_Lng"]].to_numpy()
    d = (lats[:, None] - cent[None, :, 0]) ** 2 + (lngs[:, None] - cent[None, :, 1]) ** 2
    ci = d.argmin(axis=1)

    df = pd.DataFrame({"Start_Lat": lats, "Start_Lng": lngs})
    for c in INFRA:
        df[c] = prof[c].to_numpy()[ci]
    for k, v in temporal_features(date, hour).items():
        df[k] = v
    gidx = ws.nearest_index(lats, lngs)
    for k, v in ws.features_for(gidx, 0, hour).items():
        df[k] = v
    return ms.predict(df)["prob"]


def road_scores(hour=None, date=None):
    """Per-segment risk tier for every primary road, aligned to geojson order."""
    date = date or datetime.date.today()
    if hour is None:
        hour = datetime.datetime.now().hour
    key = (date.isoformat(), int(hour), ws._state["ts"])
    with _lock:
        if key in _road_cache:
            return _road_cache[key]

    rf = _load_roads().copy()
    for k, v in temporal_features(date, hour).items():
        rf[k] = v
    for k, v in ws.features_for(rf["_gidx"].to_numpy(), 0, hour).items():
        rf[k] = v
    prob = ms.predict(rf)["prob"]
    tiers = ms.tier_of(prob)
    high = int(np.isin(tiers, ["High", "Critical"]).sum())
    result = {
        "level": "road", "hour": int(hour), "time_period": time_period(hour),
        "tiers": tiers.tolist(),
        "summary": {"total": int(len(rf)), "high_risk": high,
                    "alerts": int((tiers == "Critical").sum()),
                    "top_zone": "Road network"},
    }
    with _lock:
        _road_cache[key] = result
    return result


# --------------------------------------------------------------------------- #
# Dangerous zones (top counties, live)                                        #
# --------------------------------------------------------------------------- #
def _factors(row, tp, adverse):
    f = []
    if tp in ("Morning Peak", "Evening Peak"):
        f.append(f"{tp} traffic volume")
    if adverse:
        f.append("Rain or snow and reduced visibility")
    if row["Traffic_Signal"] >= _infra_hi["Traffic_Signal"] or \
       row["Junction"] >= _infra_hi["Junction"]:
        f.append("Dense junctions and traffic signals")
    if row["Crossing"] >= _infra_hi["Crossing"]:
        f.append("Frequent pedestrian crossings")
    if row["n_acc"] >= _acc_hi:
        f.append("High-exposure, high-traffic area")
    return f or ["Typical conditions"]


def _recommendation(tp, adverse, dense):
    if adverse:
        return "Reduce speed and increase following distance in wet or low-visibility conditions"
    if tp in ("Morning Peak", "Evening Peak"):
        return "Expect congestion; consider off-peak travel or added patrol"
    if dense:
        return "Junction-dense area — watch for turning and cross traffic"
    return "Maintain standard caution"


def zones(hour=None, date=None, tier=None, top_n=60):
    date = date or datetime.date.today()
    if hour is None:
        hour = datetime.datetime.now().hour
    _load()
    _, county = _aggregates(hour, date)

    cf = county.rename("prob").reset_index().merge(
        _county_meta.reset_index(), on=["State", "County"], how="left").dropna(subset=["Start_Lat"])
    cf = cf.sort_values("prob", ascending=False).head(top_n).reset_index(drop=True)

    gidx = ws.nearest_index(cf["Start_Lat"].to_numpy(), cf["Start_Lng"].to_numpy())
    wx = ws.features_for(gidx, 0, hour)
    tp = time_period(hour)

    rows = []
    for i, r in cf.iterrows():
        prob = float(r["prob"])
        adverse = bool(wx["Wx_Adverse"][i])
        dense = (r["Traffic_Signal"] >= _infra_hi["Traffic_Signal"] or
                 r["Junction"] >= _infra_hi["Junction"])
        factors = _factors(r, tp, adverse)
        rows.append({
            "rank": i + 1,
            "name": f"{r['County']}, {r['State']}",
            "state": r["State"],
            "lat": round(float(r["Start_Lat"]), 4),
            "lng": round(float(r["Start_Lng"]), 4),
            "prob": round(prob, 6),
            "score": int(ms.score_of(prob)),
            "severity": round(float(r["severity"]), 2),
            "tier": str(ms.tier_of(prob)),
            "reason": ", ".join(x.lower() for x in factors),
            "factors": factors,
            "recommendation": _recommendation(tp, adverse, dense),
            "time_period": tp,
            "weather": f"{round(float(wx['Wx_Temp_C'][i]))} C"
                       + (", adverse" if adverse else ", clear"),
        })
    if tier and tier != "all":
        rows = [r for r in rows if r["tier"] == tier]
    return rows


# --------------------------------------------------------------------------- #
# Forecast (searched place, next 24h + 7 days)                                #
# --------------------------------------------------------------------------- #
def _resolve_place(place):
    """Resolve a free-text query to a (State, County, display) — trying city
    names first (via city_lookup), then county names, then a fallback."""
    _load()
    name, st = place.strip(), None
    if "," in place:
        name, st = [p.strip() for p in place.rsplit(",", 1)]
        st = st.upper()
    nl = name.lower()

    # 1. City match (respecting state if given).
    if st and (nl, st) in _city_state:
        county, lat, lng = _city_state[(nl, st)]
        return {"State": st, "County": county, "lat": lat, "lng": lng,
                "display": f"{name.title()}, {st}"}
    if not st and nl in _city_any:
        s, county, lat, lng = _city_any[nl]
        return {"State": s, "County": county, "lat": lat, "lng": lng,
                "display": f"{name.title()}, {s}"}

    # 2. County match.
    cand = _county_meta.reset_index()
    if st:
        sub = cand[cand["State"] == st]
        cand = sub if len(sub) else cand
    hit = cand[cand["County"].str.lower() == nl]
    if not len(hit):
        hit = cand[cand["County"].str.lower().str.contains(nl, regex=False)]
    r = (hit.iloc[0] if len(hit)
         else cand.sort_values("n_acc", ascending=False).iloc[0])
    return {"State": r["State"], "County": r["County"],
            "lat": float(r["Start_Lat"]), "lng": float(r["Start_Lng"]),
            "display": f"{r['County']}, {r['State']}"}


def forecast(place):
    _load()
    loc = _resolve_place(place)
    pts = _pts[(_pts["State"] == loc["State"]) & (_pts["County"] == loc["County"])]
    if pts.empty:
        pts = _load().iloc[[0]]
    meta = _county_meta.loc[(loc["State"], loc["County"])]
    today = datetime.date.today()

    hourly = []
    for h in range(24):
        prob = float(_score_points(h, today, pts)["prob"].mean())
        hourly.append({"label": hour_label(h), "hour": h, "prob": round(prob, 6),
                       "score": int(ms.score_of(prob)), "tier": str(ms.tier_of(prob))})

    daily = []
    for d in range(7):
        day = today + datetime.timedelta(days=d)
        # daily peak = score the evening-peak hour with that day's forecast weather
        df = pts.copy()
        for k, v in temporal_features(day, 17).items():
            df[k] = v
        for k, v in ws.features_for(df["_gidx"].to_numpy(), d, 17).items():
            df[k] = v
        prob = float(ms.predict(df)["prob"].mean())
        daily.append({"label": day.strftime("%a"), "prob": round(prob, 6),
                      "score": int(ms.score_of(prob)), "tier": str(ms.tier_of(prob))})

    peak = max(hourly, key=lambda x: x["prob"])
    safe = min(hourly, key=lambda x: x["prob"])
    gidx = ws.nearest_index([loc["lat"]], [loc["lng"]])
    adverse = bool(ws.features_for(gidx, 0, peak["hour"])["Wx_Adverse"][0])
    factors = _factors(meta, time_period(peak["hour"]), adverse)
    tip = (f"Risk peaks around {peak['label'].upper()}; safest around "
           f"{safe['label'].upper()}. "
           + ("Wet weather in the window raises risk — allow extra time."
              if adverse else "Plan trips outside the peak window where possible."))
    return {
        "place": loc["display"],
        "hourly": hourly, "daily": daily,
        "peak": {"label": peak["label"], "score": peak["score"], "prob": peak["prob"]},
        "safe": {"label": safe["label"], "score": safe["score"], "prob": safe["prob"]},
        "factors": factors, "tip": tip,
    }
