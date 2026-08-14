"""Safe routing: candidate routes ranked by model risk.

Routing provider chain (first that succeeds wins):
  1. OpenRouteService (needs a free ORS_API_KEY in .env) - reliable, gives
     alternative routes.
  2. Public OSRM demo server (keyless) - works but intermittently slow.
  3. Straight-line fallback - clearly labelled "approximate" so it is never
     mistaken for a real road route.

Endpoints are geocoded with the keyless Open-Meteo geocoder (the two lookups
run concurrently). Each candidate route is scored by sampling points along it
and running the occurrence model; the lowest-risk route is the "safest".
"""
import datetime
import json
import os
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import numpy as np

import serving

UA = {"User-Agent": "RoadGuardAI/1.0 (traffic-risk demo)"}
STATE_FULL = serving.STATE_FULL


def _ors_key():
    return os.environ.get("ORS_API_KEY", "").strip()


def _get(url, timeout=12):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return json.load(r)


# --------------------------------------------------------------------------- #
# Geocoding                                                                   #
# --------------------------------------------------------------------------- #
def geocode(place):
    """(lat, lng, label) for a free-text place, disambiguating by state."""
    name, st = place.strip(), None
    if "," in place:
        name, st = [p.strip() for p in place.rsplit(",", 1)]
        st = st.upper()
    try:
        u = "https://geocoding-api.open-meteo.com/v1/search?" + urllib.parse.urlencode(
            {"name": name, "count": 10, "country": "US"})
        results = _get(u, timeout=10).get("results", [])
        if st and st in STATE_FULL:
            match = [r for r in results if r.get("admin1") == STATE_FULL[st]]
            results = match or results
        if results:
            r = results[0]
            label = r["name"] + (f", {st}" if st else "")
            return r["latitude"], r["longitude"], label
    except Exception:
        pass
    loc = serving._resolve_place(place)          # our own city/county lookup
    return loc["lat"], loc["lng"], loc["display"]


# --------------------------------------------------------------------------- #
# Routing providers -> [{coords[[lat,lng]], duration_s, distance_m}]          #
# --------------------------------------------------------------------------- #
def ors_routes(a, b):
    """OpenRouteService directions (with alternatives). Needs ORS_API_KEY."""
    key = _ors_key()
    if not key:
        return []
    body = json.dumps({
        "coordinates": [[a[1], a[0]], [b[1], b[0]]],
        "alternative_routes": {"target_count": 3, "share_factor": 0.6, "weight_factor": 1.6},
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.openrouteservice.org/v2/directions/driving-car/geojson",
        data=body, method="POST",
        headers={"Authorization": key, "Content-Type": "application/json",
                 "Accept": "application/geo+json", **UA})
    with urllib.request.urlopen(req, timeout=12) as r:
        d = json.load(r)
    out = []
    for ft in d.get("features", []):
        coords = [[c[1], c[0]] for c in ft["geometry"]["coordinates"]]   # ->[lat,lng]
        s = ft["properties"]["summary"]
        out.append({"coords": coords, "duration_s": s["duration"], "distance_m": s["distance"]})
    return out


def osrm_routes(a, b):
    """Public OSRM demo. Fast timeout + one retry (it is intermittently slow)."""
    url = (f"http://router.project-osrm.org/route/v1/driving/"
           f"{a[1]},{a[0]};{b[1]},{b[0]}"
           f"?alternatives=3&overview=full&geometries=geojson")
    last = None
    for _ in range(2):
        try:
            d = _get(url, timeout=8)
            out = []
            for rt in d.get("routes", []):
                coords = [[c[1], c[0]] for c in rt["geometry"]["coordinates"]]
                out.append({"coords": coords, "duration_s": rt["duration"],
                            "distance_m": rt["distance"]})
            return out
        except Exception as e:
            last = e
    raise last


def _routes_for(a, b):
    """Return (routes, approximate?) using the provider chain."""
    for provider in (ors_routes, osrm_routes):
        try:
            routes = provider(a, b)
            if routes:
                return routes, False
        except Exception:
            continue
    # Straight-line fallback (clearly flagged approximate).
    dist = 111000 * ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5
    return [{"coords": [[a[0], a[1]], [b[0], b[1]]],
             "duration_s": dist / 13.9, "distance_m": dist}], True


def _when_hour(when):
    h = datetime.datetime.now().hour
    if when == "+1": return (h + 1) % 24
    if when == "+3": return (h + 3) % 24
    if when == "evening": return 18
    return h


def _downsample(coords, n):
    if len(coords) <= n:
        return coords
    idx = np.linspace(0, len(coords) - 1, n).astype(int)
    return [coords[i] for i in idx]


def safe_route(frm, to, when="now"):
    # Geocode both endpoints concurrently.
    with ThreadPoolExecutor(max_workers=2) as ex:
        fa, fb = ex.submit(geocode, frm), ex.submit(geocode, to)
        a, b = fa.result(), fb.result()
    hour = _when_hour(when)

    routes, approx = _routes_for(a, b)
    for rt in routes:
        pts = _downsample(rt["coords"], 40)
        rt["risk"] = float(np.mean(serving.score_locations(
            [p[0] for p in pts], [p[1] for p in pts], hour)))

    safest = min(routes, key=lambda r: r["risk"])
    others = [r for r in routes if r is not safest]

    def opt(rt, kind, label):
        return {"kind": kind, "label": label,
                "minutes": round(rt["duration_s"] / 60),
                "miles": round(rt["distance_m"] / 1609.34, 1),
                "risk_prob": round(rt["risk"], 6),
                "coords": _downsample(rt["coords"], 180)}

    if approx:
        options = [opt(safest, "safest", "Approximate route (routing service busy)")]
    else:
        options = [opt(safest, "safest", "Safest route" if others else "Recommended route")]
        if others:
            alt = min(others, key=lambda r: r["duration_s"])
            label = "Fastest route" if alt["duration_s"] < safest["duration_s"] else "Alternative route"
            options.append(opt(alt, "fastest", label))
    return {"from": a[2], "to": b[2], "when": when, "options": options}
