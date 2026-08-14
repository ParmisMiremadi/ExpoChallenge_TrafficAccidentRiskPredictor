"""
Evaluation-only: re-score the ALREADY-TRAINED model on a realistic (rare-event)
distribution, to get honest false-alarm / precision numbers and validate the
prior-corrected probabilities.

Nothing is retrained. We load final_model.json, score the 2022 test rows, then
re-weight the no-accident rows so the accident:no-accident ratio equals the real
per-cell base rate pi_true (from calibration.pkl -- the combinatorial rate
n_roads x days x periods, NOT the sampled negative count, so it is not circular).
All metrics are then computed with those weights.

Run:
    ./webapp/backend/data/venv/Scripts/python.exe \
        webapp_v3/backend/pipeline/evaluate_natural_prevalence.py
"""
import os

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import (average_precision_score, precision_score,
                             recall_score, roc_auc_score)
from xgboost import XGBClassifier

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
ARTIFACTS_DIR = os.path.join(BASE_DIR, "..", "artifacts")
TABLE_PATH = os.path.join(OUTPUT_DIR, "modeling_table.pkl")


def prior_correction(p, pi_train, pi_true):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    odds = p / (1 - p)
    factor = (pi_true / (1 - pi_true)) / (pi_train / (1 - pi_train))
    oc = odds * factor
    return oc / (1 + oc)


def main():
    spec = joblib.load(os.path.join(ARTIFACTS_DIR, "feature_columns.pkl"))
    encoders = joblib.load(os.path.join(ARTIFACTS_DIR, "encoder.pkl"))
    calib = joblib.load(os.path.join(ARTIFACTS_DIR, "calibration.pkl"))
    features = spec if isinstance(spec, list) else spec["features"]
    pi_train, pi_true = calib["pi_train"], calib["pi_true"]

    table = pd.read_pickle(TABLE_PATH)
    test = table[table["Year"] == 2022].copy()
    for col, mapping in encoders.items():
        test[col] = test[col].map(mapping).fillna(-1).astype(int)

    model = XGBClassifier()
    model.load_model(os.path.join(ARTIFACTS_DIR, "final_model.json"))
    y = test["Is_Accident"].to_numpy()
    proba = model.predict_proba(test[features])[:, 1]
    proba_cal = prior_correction(proba, pi_train, pi_true)

    # Re-weight negatives so the effective base rate == pi_true.
    n_pos, n_neg = int(y.sum()), int((y == 0).sum())
    w_neg = n_pos * (1 - pi_true) / (pi_true * n_neg)
    w = np.where(y == 1, 1.0, w_neg)
    eff_rate = w[y == 1].sum() / w.sum()
    print(f"Test rows: {len(y):,}  (pos {n_pos:,} / neg {n_neg:,})")
    print(f"Negative weight: {w_neg:,.1f}x  ->  effective base rate {eff_rate*100:.3f}% "
          f"(target pi_true {pi_true*100:.3f}%)")

    print("\n--- Discrimination at REAL prevalence ---")
    print(f"ROC-AUC (weighted): {roc_auc_score(y, proba, sample_weight=w):.4f}")
    print(f"PR-AUC  (weighted): {average_precision_score(y, proba, sample_weight=w):.4f}"
          f"   [random baseline = {pi_true:.5f}]")

    print("\n--- Early-warning trade-off (flag top X% of REAL cells by risk) ---")
    print(f"{'flag top %':>10} {'recall':>8} {'precision':>10} {'lift vs random':>15}")
    order = np.argsort(-proba)                    # highest risk first
    cumw = np.cumsum(w[order])                    # cumulative REAL-cell weight
    total_w, total_pos_w = w.sum(), w[y == 1].sum()
    for pct in [0.1, 1, 5, 10, 20]:
        k = int(np.searchsorted(cumw, pct / 100 * total_w)) + 1
        flagged = order[:k]
        tp_w = w[flagged][y[flagged] == 1].sum()
        rec = tp_w / total_pos_w
        prec = tp_w / w[flagged].sum()
        print(f"{pct:>9}% {rec:>8.3f} {prec:>10.4f} {prec/pi_true:>14.1f}x")

    print("\n--- Calibration of the SERVED (prior-corrected) probability ---")
    q = np.quantile(proba_cal, np.linspace(0, 1, 11))
    q = np.unique(q)
    idx = np.clip(np.digitize(proba_cal, q) - 1, 0, len(q) - 2)
    print(f"{'pred':>8} {'observed':>10} {'weight share':>14}")
    for b in range(len(q) - 1):
        m = idx == b
        if m.sum():
            pred_m = np.average(proba_cal[m], weights=w[m])
            obs_m = np.average(y[m], weights=w[m])
            share = w[m].sum() / w.sum()
            print(f"{pred_m:>8.4f} {obs_m:>10.4f} {share*100:>13.1f}%")


if __name__ == "__main__":
    main()
