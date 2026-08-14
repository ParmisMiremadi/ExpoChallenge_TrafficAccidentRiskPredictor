"""Coarse, cached weather grid for live model scoring.

Fetches an hourly Open-Meteo forecast for a regular grid of points over the
continental US (keyless), caches it, and exposes fast nearest-point lookups so
every county/road can be given the six weather features the model expects:

  Wx_Temp_C, Wx_Precip_mm, Wx_Wind_kmh, Wx_Humidity, Wx_SnowDepth_mm, Wx_Adverse

Times use each point's local timezone (Open-Meteo `timezone=auto`), so hour H
means local hour H everywhere -- e.g. "evening peak" is evening in each place.
Index for day D (0=today) hour H is D*24 + H.
"""
import json
import threading
import time
import urllib.parse
import urllib.request

import numpy as np

# Regular CONUS grid.
LAT0, LAT1, STEP = 25.0, 49.0, 2.5
LNG0, LNG1 = -125.0, -66.0
FORECAST_DAYS = 7
CACHE_TTL = 2 * 3600  # refresh the grid every 2 hours

HOURLY_VARS = ["temperature_2m", "precipitation", "wind_speed_10m",
               "relative_humidity_2m", "snow_depth", "weather_code"]

_lats = np.arange(LAT0, LAT1 + 1e-9, STEP)
_lngs = np.arange(LNG0, LNG1 + 1e-9, STEP)
NLAT, NLNG = len(_lats), len(_lngs)

# Grid point order: row-major over (lat, lng).
_grid_lat = np.repeat(_lats, NLNG)
_grid_lng = np.tile(_lngs, NLAT)
N_POINTS = len(_grid_lat)

_state = {"arrays": None, "ts": 0}
_lock = threading.Lock()


def _fetch_batch(lats, lngs):
    q = urllib.parse.urlencode({
        "latitude": ",".join(f"{x:.2f}" for x in lats),
        "longitude": ",".join(f"{x:.2f}" for x in lngs),
        "hourly": ",".join(HOURLY_VARS),
        "forecast_days": FORECAST_DAYS,
        "timezone": "auto",
    })
    url = f"https://api.open-meteo.com/v1/forecast?{q}"
    last = None
    for _ in range(3):
        try:
            with urllib.request.urlopen(url, timeout=45) as r:
                data = json.load(r)
            return data if isinstance(data, list) else [data]
        except Exception as e:
            last = e
            time.sleep(2)
    raise last


def _refresh():
    """(Re)download the whole grid into numpy arrays [N_POINTS, N_HOURS].

    A batch that keeps failing is skipped (its points stay NaN and get filled
    with column medians below), so a transient outage degrades rather than
    breaks the map."""
    n_hours = FORECAST_DAYS * 24
    arr = {v: np.full((N_POINTS, n_hours), np.nan) for v in HOURLY_VARS}
    B = 100  # Open-Meteo bulk batch size
    for i in range(0, N_POINTS, B):
        try:
            results = _fetch_batch(_grid_lat[i:i + B], _grid_lng[i:i + B])
        except Exception:
            continue
        for j, res in enumerate(results):
            p = i + j
            h = res.get("hourly", {})
            for v in HOURLY_VARS:
                vals = h.get(v)
                if vals:
                    arr[v][p, :len(vals)] = vals[:n_hours]
    # Fill any gaps with column medians so scoring never sees NaN. If a whole
    # variable failed to download, fall back to 0 rather than NaN.
    import warnings
    for v in HOURLY_VARS:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=RuntimeWarning)
            col_med = np.nanmedian(arr[v])
        if not np.isfinite(col_med):
            col_med = 0.0
        arr[v] = np.nan_to_num(arr[v], nan=col_med)
    _state["arrays"] = arr
    _state["ts"] = time.time()


def _ensure():
    with _lock:
        if _state["arrays"] is None or (time.time() - _state["ts"]) > CACHE_TTL:
            _refresh()
    return _state["arrays"]


def nearest_index(lats, lngs):
    """O(1) nearest grid-point index for arrays of coordinates."""
    ilat = np.clip(np.round((np.asarray(lats) - LAT0) / STEP), 0, NLAT - 1).astype(int)
    ilng = np.clip(np.round((np.asarray(lngs) - LNG0) / STEP), 0, NLNG - 1).astype(int)
    return ilat * NLNG + ilng


def features_for(idx, day, hour):
    """Return the six Wx_* feature arrays for grid indices `idx` at day/hour."""
    arr = _ensure()
    t = min(day * 24 + hour, arr["temperature_2m"].shape[1] - 1)
    temp = arr["temperature_2m"][idx, t]
    precip = arr["precipitation"][idx, t]
    wind = arr["wind_speed_10m"][idx, t]
    humid = arr["relative_humidity_2m"][idx, t]
    snow_mm = arr["snow_depth"][idx, t] * 1000.0  # meters -> mm
    adverse = ((precip > 0.1) | (snow_mm > 0)).astype(float)
    return {
        "Wx_Temp_C": temp, "Wx_Precip_mm": precip, "Wx_Wind_kmh": wind,
        "Wx_Humidity": humid, "Wx_SnowDepth_mm": snow_mm, "Wx_Adverse": adverse,
    }


def summary_at(lat, lng, day=0, hour=None):
    """Human-readable current weather for one point (for the conditions widget)."""
    import datetime
    if hour is None:
        hour = datetime.datetime.now().hour
    i = nearest_index([lat], [lng])
    f = features_for(i, day, hour)
    return {k: float(v[0]) for k, v in f.items()}
