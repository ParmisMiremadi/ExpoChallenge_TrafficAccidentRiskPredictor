"""
TraffiQ - Traffic Accident Risk Predictor.

Flask backend. Serves the frontend and the live API, all backed by the trained
occurrence model:

  - model_service   : load model + calibrate raw scores -> absolute probability
  - serving         : score the state map, road network, dangerous zones, and
                      forecast from per-county/road serving tables + weather
  - weather_service : cached coarse Open-Meteo forecast grid
  - routing_service : OSRM routes ranked by model risk
  - news_service    : NWS alerts (+ optional Jina/Gemini) for the live ticker

Run: webapp/backend/data/venv/Scripts/python.exe webapp_v3/backend/app.py
"""

import json as _json
import os
import threading
import urllib.parse
import urllib.request
from datetime import datetime

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

import news_service
import routing_service
import serving
import weather_service

FRONTEND_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "frontend")
)
ARTIFACTS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "artifacts")
)

app = Flask(__name__, static_folder=None)
CORS(app)


# Neutral fallback shown only if a live weather lookup fails; the frontend
# replaces it with the user's live local weather when available.
WEATHER_SAMPLE = {"text": "Weather unavailable", "adverse": False}


# --------------------------------------------------------------------------- #
# Static frontend                                                              #
# --------------------------------------------------------------------------- #
@app.route("/")
def index():
    return send_from_directory(os.path.join(FRONTEND_DIR, "html"), "index.html")


@app.route("/css/<path:filename>")
def css(filename):
    return send_from_directory(os.path.join(FRONTEND_DIR, "css"), filename)


@app.route("/js/<path:filename>")
def js(filename):
    return send_from_directory(os.path.join(FRONTEND_DIR, "js"), filename)


@app.route("/data/<path:filename>")
def data(filename):
    return send_from_directory(os.path.join(FRONTEND_DIR, "data"), filename)


# --------------------------------------------------------------------------- #
# API                                                                          #
# --------------------------------------------------------------------------- #
# WMO weather-code -> (label, is_adverse). Adverse = precipitation/fog/storm.
WMO = {
    0: ("Clear sky", False), 1: ("Mainly clear", False), 2: ("Partly cloudy", False),
    3: ("Overcast", False), 45: ("Fog", True), 48: ("Freezing fog", True),
    51: ("Light drizzle", True), 53: ("Drizzle", True), 55: ("Heavy drizzle", True),
    56: ("Freezing drizzle", True), 57: ("Freezing drizzle", True),
    61: ("Light rain", True), 63: ("Rain", True), 65: ("Heavy rain", True),
    66: ("Freezing rain", True), 67: ("Freezing rain", True),
    71: ("Light snow", True), 73: ("Snow", True), 75: ("Heavy snow", True),
    77: ("Snow grains", True), 80: ("Rain showers", True), 81: ("Rain showers", True),
    82: ("Violent rain showers", True), 85: ("Snow showers", True), 86: ("Snow showers", True),
    95: ("Thunderstorm", True), 96: ("Thunderstorm with hail", True), 99: ("Thunderstorm with hail", True),
}


@app.route("/api/weather")
def weather():
    """Live current weather for a coordinate via Open-Meteo (keyless).

    Falls back to the placeholder sample if the request fails, so the UI always
    has something to show.
    """
    try:
        lat = round(float(request.args.get("lat")), 2)
        lng = round(float(request.args.get("lng")), 2)
    except (TypeError, ValueError):
        return jsonify({"ok": False, **WEATHER_SAMPLE, "temp_c": None})

    q = urllib.parse.urlencode({
        "latitude": lat, "longitude": lng,
        "current": "temperature_2m,precipitation,weather_code,wind_speed_10m,is_day",
        "timezone": "auto",
    })
    url = f"https://api.open-meteo.com/v1/forecast?{q}"
    try:
        with urllib.request.urlopen(url, timeout=6) as r:
            cur = _json.load(r)["current"]
        label, adverse = WMO.get(int(cur["weather_code"]), ("Unknown", False))
        temp = round(cur["temperature_2m"])
        text = f"{label}, {temp} C"
        return jsonify({
            "ok": True,
            "text": text,
            "label": label,
            "temp_c": temp,
            "precip_mm": cur.get("precipitation", 0),
            "wind_kmh": cur.get("wind_speed_10m", 0),
            "is_day": bool(cur.get("is_day", 1)),
            "adverse": adverse,
            "lat": lat, "lng": lng,
        })
    except Exception:
        return jsonify({"ok": False, **WEATHER_SAMPLE, "temp_c": None})


@app.route("/api/news")
def news():
    force = request.args.get("force") in ("1", "true")
    return jsonify(news_service.get_news(force=force))


@app.route("/api/meta")
def meta():
    serving._load()
    return jsonify({
        "model_name": "XGBoost occurrence classifier",
        "target": "P(accident) per road x time",
        "coverage": f"{len(serving._county_meta):,} US counties, "
                    f"{len(serving._load_roads()):,} primary roads",
        "server_time": datetime.now().isoformat(timespec="minutes"),
        "weather": WEATHER_SAMPLE,
    })


@app.route("/api/metrics")
def metrics():
    """Model-performance metrics for the Project Overview view.

    Returns the trained model's evaluation metrics (from artifacts/metrics.json)
    reshaped into a small, UI-friendly payload of gauges + context.
    """
    try:
        with open(os.path.join(ARTIFACTS_DIR, "metrics.json"), encoding="utf-8") as f:
            m = _json.load(f)
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(exc)}), 200

    op = m.get("operating_point", {})
    sp = m.get("spatial", {})

    # Each gauge: value in [0,1] unless noted; `higher_better` drives coloring.
    gauges = [
        {"key": "roc_auc", "label": "ROC-AUC", "value": m.get("xgb_roc_auc"),
         "baseline": m.get("lr_roc_auc"), "higher_better": True,
         "hint": "Ranking quality vs. logistic-regression baseline"},
        {"key": "pr_auc", "label": "PR-AUC", "value": m.get("xgb_pr_auc"),
         "baseline": m.get("lr_pr_auc"), "higher_better": True,
         "hint": "Precision–recall area (PR-ROC)"},
        {"key": "precision", "label": "Precision", "value": op.get("precision"),
         "higher_better": True, "hint": f"At threshold {op.get('threshold')}"},
        {"key": "recall", "label": "Recall", "value": op.get("recall"),
         "higher_better": True, "hint": f"At threshold {op.get('threshold')}"},
        {"key": "f1", "label": "F1 score", "value": op.get("f1"),
         "higher_better": True, "hint": "Harmonic mean of precision & recall"},
        {"key": "brier", "label": "Brier score", "value": m.get("brier_raw"),
         "higher_better": False, "hint": "Calibration error (lower is better)"},
        {"key": "county_spearman", "label": "County risk Spearman",
         "value": sp.get("county_risk_spearman"), "higher_better": True,
         "hint": "Spatial rank agreement across counties"},
        {"key": "hotspot_precision", "label": "Hotspot precision",
         "value": sp.get("hotspot_precision"), "higher_better": True,
         "hint": "Predicted hotspots that are real"},
        {"key": "hotspot_recall", "label": "Hotspot recall",
         "value": sp.get("hotspot_recall"), "higher_better": True,
         "hint": "Real hotspots that were caught"},
    ]

    return jsonify({
        "ok": True,
        "model_name": "XGBoost occurrence classifier",
        "gauges": gauges,
        "dataset": {
            "n_train": m.get("n_train"),
            "n_test": m.get("n_test"),
            "top20_overlap": sp.get("top20_overlap"),
        },
        "feature_importance": m.get("feature_importance_top", []),
        "reliability": m.get("reliability_raw", []),
        "note": m.get("calibration_note", ""),
    })


@app.route("/api/risk-map")
def risk_map():
    hour = int(request.args.get("hour", datetime.now().hour))
    metric = request.args.get("metric", "risk")
    level = request.args.get("level", "state")

    if level == "road":
        return jsonify(serving.road_scores(hour))

    # Default: state choropleth, scored live by the real model.
    return jsonify(serving.compute(hour, metric=metric))


@app.route("/api/zones")
def zones():
    hour = int(request.args.get("hour", datetime.now().hour))
    tier = request.args.get("tier", "all")
    return jsonify(serving.zones(hour=hour, tier=tier))


@app.route("/api/forecast")
def forecast():
    place = request.args.get("place", "Los Angeles, CA")
    return jsonify(serving.forecast(place))


@app.route("/api/route")
def route():
    frm = request.args.get("from", "")
    to = request.args.get("to", "")
    when = request.args.get("when", "now")
    if not frm or not to:
        return jsonify({"from": frm, "to": to, "options": [],
                        "error": "Enter a start and destination."})
    try:
        return jsonify(routing_service.safe_route(frm, to, when))
    except Exception as exc:  # noqa: BLE001
        return jsonify({"from": frm, "to": to, "options": [],
                        "error": f"Routing unavailable: {exc}"}), 200


def _warm():
    """Pre-fetch the weather grid and score the current hour so the first map
    request is fast. Runs in the background at startup."""
    try:
        serving.compute(datetime.now().hour)
    except Exception as exc:  # noqa: BLE001
        print("warm-up skipped:", exc)


if __name__ == "__main__":
    # Only warm in the reloader's worker process, not the supervisor.
    if os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        threading.Thread(target=_warm, daemon=True).start()
    app.run(host="127.0.0.1", port=5000, debug=True, threaded=True)
