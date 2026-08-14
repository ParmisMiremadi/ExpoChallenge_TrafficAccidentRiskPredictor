"""Serving layer for the trained occurrence model.

Loads the deploy XGBoost model and its serving artifacts once, then turns a
DataFrame of feature rows into calibrated accident probabilities, risk tiers,
and a 0-100 relative score. Mirrors the training pipeline exactly:

  raw = model.predict_proba(X)[:, 1]                     # balanced-prior score
  prob = prior_correction(raw, pi_train, pi_true)        # true absolute prob
  tier = Low/Medium/High/Critical  via risk_bins quantile cutoffs

Categorical features (Season, Time_Period) are label-encoded with the same
maps saved at training time (encoder.json).

All artifacts are stored in version-portable formats (XGBoost JSON + plain
JSON), so the app loads on any Python / pandas / numpy version.
"""

import json
import os

import numpy as np
from xgboost import XGBClassifier

ARTIFACTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "artifacts")

_state = {}


def _load():
    if _state:
        return _state
    model = XGBClassifier()
    model.load_model(os.path.join(ARTIFACTS_DIR, "final_model.json"))

    def load_json(name):
        with open(os.path.join(ARTIFACTS_DIR, name), encoding="utf-8") as f:
            return json.load(f)

    _state.update(
        model=model,
        features=load_json("feature_columns.json"),
        encoder=load_json("encoder.json"),
        calibration=load_json("calibration.json"),
        risk_bins=load_json("risk_bins.json"),
    )
    return _state


def prior_correction(p, pi_train, pi_true):
    """Log-odds shift from the balanced training prior to the true base rate."""
    p = np.clip(np.asarray(p, dtype=float), 1e-6, 1 - 1e-6)
    odds = p / (1 - p)
    factor = (pi_true / (1 - pi_true)) / (pi_train / (1 - pi_train))
    odds_c = odds * factor
    return odds_c / (1 + odds_c)


def _encode(df):
    df = df.copy()
    for col, mapping in _load()["encoder"].items():
        if col in df.columns:
            df[col] = df[col].map(mapping).fillna(-1).astype(int)
    return df


def predict_raw(df):
    """Raw (balanced-prior) accident probability for each row."""
    s = _load()
    X = _encode(df)[s["features"]]
    return s["model"].predict_proba(X)[:, 1]


def calibrate(raw):
    cal = _load()["calibration"]
    return prior_correction(raw, cal["pi_train"], cal["pi_true"])


def tier_of(prob):
    """Vectorised tier label(s) from calibrated probability via risk_bins."""
    b = _load()["risk_bins"]
    p = np.asarray(prob, dtype=float)
    out = np.where(p >= b["high"], "Critical",
          np.where(p >= b["medium"], "High",
          np.where(p >= b["low"], "Medium", "Low")))
    return out


def score_of(prob):
    """0-100 relative index for UI convenience. Log-scaled between the Low and
    High cutoffs so the tiers spread across the range; not a probability."""
    b = _load()["risk_bins"]
    p = np.clip(np.asarray(prob, dtype=float), 1e-9, 1.0)
    lo, hi = np.log(b["low"]), np.log(b["high"])
    frac = (np.log(p) - lo) / (hi - lo)
    return np.clip(np.round(frac * 75 + 12), 0, 100).astype(int)


def predict(df):
    """Return calibrated prob, tier, and score arrays for a feature DataFrame."""
    raw = predict_raw(df)
    prob = calibrate(raw)
    return {"prob": prob, "tier": tier_of(prob), "score": score_of(prob)}


def info():
    s = _load()
    return {
        "n_features": len(s["features"]),
        "features": s["features"],
        "calibration": s["calibration"],
        "risk_bins": s["risk_bins"],
    }
