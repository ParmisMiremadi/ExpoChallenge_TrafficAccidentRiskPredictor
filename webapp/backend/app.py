"""
Flask API for the Traffic Accident Risk Predictor.

This is the serving layer for the model trained in
Traffic_Accident_Risk_Predictor_v2.ipynb. It exposes the same five
competition deliverables the notebook produces -- risk-level prediction,
dangerous-zone detection, seasonal adaptation, safety alerts/reports, and
prevention recommendations -- as JSON endpoints, and serves the static
dashboard that consumes them.
"""
import json
import os

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

import model_service as ms

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.abspath(os.path.join(BASE_DIR, "..", "frontend"))
DATA_DIR = os.path.join(BASE_DIR, "data")


def load_json(name):
    with open(os.path.join(DATA_DIR, name), encoding="utf-8") as f:
        return json.load(f)


# Precomputed tables (dangerous zones, alerts, seasonal breakdowns, ...) are
# generated once from the 2023 test set by export_data.py and just served
# from memory here -- only /api/predict and /api/scenario-simulator run the
# model live, on demand.
DANGEROUS_ZONES = load_json("dangerous_zones.json")
STATE_SUMMARY = load_json("state_summary.json")
SEASON_TIME_RISK = load_json("season_time_risk.json")
ALERTS = load_json("alerts.json")
DASHBOARD_SUMMARY = load_json("dashboard_summary.json")
STATES_COUNTIES = load_json("states_counties.json")

app = Flask(__name__, static_folder=None)
CORS(app)


def _road_feature_ints(body):
    return {
        "crossing": int(bool(body.get("crossing"))),
        "junction": int(bool(body.get("junction"))),
        "station": int(bool(body.get("station"))),
        "stop": int(bool(body.get("stop"))),
        "traffic_signal": int(bool(body.get("traffic_signal"))),
        "amenity": int(bool(body.get("amenity"))),
    }


def _required_fields(body):
    missing = [f for f in ("state", "county", "season", "hour") if body.get(f) in (None, "")]
    return missing


# ----------------------------------------------------------------------
# Static frontend
# ----------------------------------------------------------------------
@app.route("/")
def index():
    return send_from_directory(os.path.join(FRONTEND_DIR, "html"), "index.html")


@app.route("/css/<path:path>")
def css(path):
    return send_from_directory(os.path.join(FRONTEND_DIR, "css"), path)


@app.route("/js/<path:path>")
def js(path):
    return send_from_directory(os.path.join(FRONTEND_DIR, "js"), path)


# ----------------------------------------------------------------------
# Reference data (dropdowns)
# ----------------------------------------------------------------------
@app.get("/api/states")
def states():
    return jsonify(sorted(STATES_COUNTIES.keys()))


@app.get("/api/counties")
def counties():
    state = request.args.get("state", "").upper()
    return jsonify(STATES_COUNTIES.get(state, []))


# ----------------------------------------------------------------------
# Expected Output: Risk-level predictions (live, on demand)
# ----------------------------------------------------------------------
@app.post("/api/predict")
def predict():
    body = request.get_json(force=True) or {}
    missing = _required_fields(body)
    if missing:
        return jsonify({"error": f"Missing required field(s): {', '.join(missing)}"}), 400

    try:
        result, _ = ms.run_prediction(
            state=body["state"].upper(),
            county=body["county"],
            season=body["season"],
            hour=int(body["hour"]),
            is_weekend=bool(body.get("is_weekend", False)),
            **_road_feature_ints(body),
        )
    except KeyError:
        return jsonify({"error": "Unknown state/county combination."}), 400
    except Exception as exc:  # pragma: no cover - defensive guard for a live demo
        return jsonify({"error": str(exc)}), 400

    return jsonify(result)


# ----------------------------------------------------------------------
# Innovation 2 + 3: scenario simulator & best-improvement recommendation
# ----------------------------------------------------------------------
@app.post("/api/scenario-simulator")
def scenario_simulator():
    body = request.get_json(force=True) or {}
    missing = _required_fields(body)
    if missing:
        return jsonify({"error": f"Missing required field(s): {', '.join(missing)}"}), 400

    try:
        result = ms.run_scenario_simulation(
            state=body["state"].upper(),
            county=body["county"],
            season=body["season"],
            hour=int(body["hour"]),
            is_weekend=bool(body.get("is_weekend", False)),
            **_road_feature_ints(body),
        )
    except KeyError:
        return jsonify({"error": "Unknown state/county combination."}), 400
    except Exception as exc:  # pragma: no cover
        return jsonify({"error": str(exc)}), 400

    return jsonify(result)


# ----------------------------------------------------------------------
# Expected Output: dangerous-zone detection
# ----------------------------------------------------------------------
@app.get("/api/dangerous-zones")
def dangerous_zones():
    limit = request.args.get("limit", 50, type=int)
    return jsonify(DANGEROUS_ZONES[:limit])


@app.get("/api/state-summary")
def state_summary():
    return jsonify(STATE_SUMMARY)


# ----------------------------------------------------------------------
# Main task: adapt predictions to seasonal conditions
# ----------------------------------------------------------------------
@app.get("/api/season-time-risk")
def season_time_risk():
    return jsonify(SEASON_TIME_RISK)


# ----------------------------------------------------------------------
# Expected Output: safety alerts and reports / prevention recommendations
# ----------------------------------------------------------------------
@app.get("/api/alerts")
def alerts():
    limit = request.args.get("limit", 25, type=int)
    return jsonify(ALERTS[:limit])


@app.get("/api/dashboard-summary")
def dashboard_summary():
    return jsonify(DASHBOARD_SUMMARY)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
