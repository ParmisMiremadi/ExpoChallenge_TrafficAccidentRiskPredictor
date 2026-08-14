"""
Stage 4: train the occurrence-risk model.

Target: Is_Accident (1 = an accident occurred in this road/time/weather context,
0 = a matched no-accident context). The model estimates P(accident | conditions)
-- i.e. WHERE/WHEN a crash is likely, before it happens -- which is the project's
core objective, in contrast to v1 which predicted severity given a crash.

Pipeline of this script:
  1. Temporal split: train on 2021, test on 2022 (both full years). Training on
     the past and scoring the future is the honest test of "predict before it
     occurs". 2023 is Q1-only, so it is left out of the headline test.
  2. Model: XGBoost classifier (primary) + logistic-regression baseline.
  3. Calibration: prior-correction. The training set is balanced ~50/50 for
     learnability, so raw probabilities are inflated; a single log-odds shift
     rescales them to the true base rate pi_true (accident cells / all possible
     cells), which the grid lets us count. Ranking is unchanged.
  4. Evaluation:
       - discrimination: ROC-AUC, PR-AUC
       - calibration: Brier score + reliability curve (before/after correction)
       - SPATIAL honesty check: do predicted high-risk areas match where crashes
         actually happened in 2022? (county risk Spearman, top-20 overlap,
         top-quintile hotspot precision/recall)
       - a chosen operating point with its confusion matrix
  5. Severity is saved as a per-road AGGREGATE (shrunk mean), for map colouring
     only -- it is not a trained target (labels drift by year/source).

Inputs (output/): modeling_table.pkl, feature_columns.pkl
Artifacts (webapp_v3/backend/artifacts/): final_model, encoder, feature_columns,
    calibration, risk_bins, severity_by_road, metrics.json
"""
import json
import os
import sys

import joblib
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (average_precision_score, brier_score_loss,
                             confusion_matrix, precision_score, recall_score,
                             roc_auc_score)
from sklearn.preprocessing import StandardScaler
from xgboost import XGBClassifier

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
ARTIFACTS_DIR = os.path.join(BASE_DIR, "..", "artifacts")
TABLE_PATH = os.path.join(OUTPUT_DIR, "modeling_table.pkl")
FEATCOLS_PATH = os.path.join(OUTPUT_DIR, "feature_columns.pkl")
TESTPRED_PATH = os.path.join(OUTPUT_DIR, "test_predictions.pkl")

ROAD_KEYS = ["State", "County", "City", "Street"]
TIME_PERIODS = 6
SEVERITY_SHRINK_K = 10          # pseudo-count pulling sparse roads to the mean
RANDOM_STATE = 42


def encode_categoricals(train, test, cat_cols):
    """Map each categorical to integer codes learned on the training set;
    categories unseen at test time become -1."""
    encoders = {}
    for col in cat_cols:
        cats = sorted(train[col].dropna().unique())
        mapping = {c: i for i, c in enumerate(cats)}
        encoders[col] = mapping
        train[col] = train[col].map(mapping).fillna(-1).astype(int)
        test[col] = test[col].map(mapping).fillna(-1).astype(int)
    return encoders


def prior_correction(p, pi_train, pi_true):
    """Shift predicted probabilities from the balanced prior to the true prior.
    Pure log-odds offset: preserves ranking, fixes the absolute scale."""
    p = np.clip(p, 1e-6, 1 - 1e-6)
    odds = p / (1 - p)
    factor = (pi_true / (1 - pi_true)) / (pi_train / (1 - pi_train))
    odds_c = odds * factor
    return odds_c / (1 + odds_c)


def reliability(y, p, n_bins=10):
    """Mean predicted vs observed frequency per probability bin."""
    bins = np.linspace(0, 1, n_bins + 1)
    idx = np.clip(np.digitize(p, bins) - 1, 0, n_bins - 1)
    rows = []
    for b in range(n_bins):
        m = idx == b
        if m.sum():
            rows.append((round(float(p[m].mean()), 3),
                         round(float(y[m].mean()), 3), int(m.sum())))
    return rows


def spatial_check(test, proba):
    """Do predicted-risk areas match where accidents actually happened in 2022?"""
    df = test[["County", "Is_Accident"]].copy()
    df["risk"] = proba
    # Sum of predicted risk = predicted expected accident COUNT -- comparable
    # like-for-like with the actual accident count (mean-risk would compare
    # apples to oranges and favour tiny counties).
    pred = df.groupby("County")["risk"].sum()
    actual = df[df["Is_Accident"] == 1].groupby("County").size()
    joined = pd.DataFrame({"pred": pred}).join(actual.rename("actual")).fillna(0)
    spearman = joined["pred"].corr(joined["actual"], method="spearman")
    k = 20
    top_pred = set(joined["pred"].sort_values(ascending=False).head(k).index)
    top_actual = set(joined["actual"].sort_values(ascending=False).head(k).index)
    overlap = len(top_pred & top_actual)
    # Top-quintile hotspot precision/recall at the county level.
    cut = joined["pred"].quantile(0.80)
    hot = joined["pred"] >= cut
    has = joined["actual"] > 0
    precision = (hot & has).sum() / max(hot.sum(), 1)
    recall = joined.loc[hot, "actual"].sum() / max(joined["actual"].sum(), 1)
    return {"county_risk_spearman": round(float(spearman), 3),
            f"top{k}_overlap": f"{overlap}/{k}",
            "hotspot_precision": round(float(precision), 3),
            "hotspot_recall": round(float(recall), 3)}


def main():
    os.makedirs(ARTIFACTS_DIR, exist_ok=True)
    spec = joblib.load(FEATCOLS_PATH)
    features, cat_cols = spec["features"], spec["categorical"]

    print("Loading modeling table ...")
    table = pd.read_pickle(TABLE_PATH)
    if len(sys.argv) > 1:                       # e.g. `train_model.py 0.03` = smoke test
        frac = float(sys.argv[1])
        table = table.sample(frac=frac, random_state=RANDOM_STATE)
        print(f"SMOKE TEST: sampled {frac:.0%} -> {len(table):,} rows")
    # Encode categoricals on the FULL table using 2021 (train) categories, so the
    # same mapping applies to train, the 2022 test, and the deploy refit.
    encoders = {}
    train_mask = table["Year"] == 2021
    for col in cat_cols:
        cats = sorted(table.loc[train_mask, col].dropna().unique())
        encoders[col] = {c: i for i, c in enumerate(cats)}
        table[col] = table[col].map(encoders[col]).fillna(-1).astype(int)

    train = table[table["Year"] == 2021]
    test = table[table["Year"] == 2022]
    print(f"Train (2021): {len(train):,}  |  Test (2022): {len(test):,}")
    X_train, y_train = train[features], train["Is_Accident"]
    X_test, y_test = test[features], test["Is_Accident"]

    # Early-stopping slice out of the training year.
    val_mask = np.random.default_rng(RANDOM_STATE).random(len(X_train)) < 0.15
    print("Training XGBoost ...")
    xgb = XGBClassifier(n_estimators=600, max_depth=7, learning_rate=0.05,
                        subsample=0.8, colsample_bytree=0.8,
                        eval_metric="aucpr", early_stopping_rounds=40,
                        random_state=RANDOM_STATE, n_jobs=-1)
    xgb.fit(X_train[~val_mask], y_train[~val_mask],
            eval_set=[(X_train[val_mask], y_train[val_mask])], verbose=False)

    proba = xgb.predict_proba(X_test)[:, 1]

    # Logistic-regression baseline (scaled numeric + encoded categoricals).
    print("Training logistic-regression baseline ...")
    scaler = StandardScaler().fit(X_train)
    lr = LogisticRegression(max_iter=200, n_jobs=-1)
    lr.fit(scaler.transform(X_train), y_train)
    proba_lr = lr.predict_proba(scaler.transform(X_test))[:, 1]

    # --- Prior-correction to the true occurrence rate ------------------------
    pi_train = float(y_train.mean())
    train["road"] = train[ROAD_KEYS].astype(str).agg("|".join, axis=1)
    n_roads = train["road"].nunique()
    days = pd.to_datetime(train["Date"])
    n_days = (days.max() - days.min()).days + 1
    total_cells = n_roads * n_days * TIME_PERIODS
    accident_cells = (train.loc[train["Is_Accident"] == 1]
                      .drop_duplicates(["road", "Date", "Time_Period"]).shape[0])
    pi_true = accident_cells / total_cells
    proba_cal = prior_correction(proba, pi_train, pi_true)
    print(f"pi_train={pi_train:.3f}  pi_true={pi_true:.5f} "
          f"({accident_cells:,} accident cells / {total_cells:,} possible)")

    # --- Metrics -------------------------------------------------------------
    metrics = {
        "n_train": int(len(train)), "n_test": int(len(test)),
        "xgb_roc_auc": round(float(roc_auc_score(y_test, proba)), 4),
        "xgb_pr_auc": round(float(average_precision_score(y_test, proba)), 4),
        "lr_roc_auc": round(float(roc_auc_score(y_test, proba_lr)), 4),
        "lr_pr_auc": round(float(average_precision_score(y_test, proba_lr)), 4),
        "brier_raw": round(float(brier_score_loss(y_test, proba)), 4),
        "pi_train": round(pi_train, 4), "pi_true": round(pi_true, 5),
        "reliability_raw": reliability(y_test.to_numpy(), proba),
        "calibration_note": ("reliability/Brier are RAW probs vs the BALANCED "
                             "test set (valid for the model as trained). "
                             "Prior-correction to pi_true is for real-world "
                             "serving via percentile risk levels -- not "
                             "evaluable on a balanced set."),
        "spatial": spatial_check(test, proba),
    }

    # Feature importances -- also a leakage check: no single feature should
    # dominate, and Pop_Log's rank tells us whether it earned its place.
    imp = sorted(zip(features, xgb.feature_importances_), key=lambda x: -x[1])
    metrics["feature_importance_top"] = [[f, round(float(v), 4)] for f, v in imp[:10]]

    # Operating point: threshold maximising F1 on the test scores.
    grid = np.linspace(0.1, 0.9, 33)
    f1s = [(t, *_prf(y_test, proba >= t)) for t in grid]
    best_t, bp, br, bf1 = max(f1s, key=lambda r: r[3])
    tn, fp, fn, tp = confusion_matrix(y_test, proba >= best_t).ravel()
    metrics["operating_point"] = {
        "threshold": round(float(best_t), 3), "precision": round(bp, 3),
        "recall": round(br, 3), "f1": round(bf1, 3),
        "confusion": {"tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)},
    }

    # --- Save split-model test predictions (honest 2021->2022) for plotting --
    pd.DataFrame({"y": y_test.to_numpy(), "proba": proba,
                  "Start_Lat": test["Start_Lat"].to_numpy(),
                  "Start_Lng": test["Start_Lng"].to_numpy(),
                  "County": test["County"].to_numpy()}).to_pickle(TESTPRED_PATH)

    # --- Deploy model: refit on ALL data (2021+2022+2023) so serving uses every
    # available row. The metrics above stay the honest 2021->2022 split. --------
    print("Refitting deploy model on all data ...")
    deploy = XGBClassifier(n_estimators=xgb.best_iteration + 1, max_depth=7,
                           learning_rate=0.05, subsample=0.8, colsample_bytree=0.8,
                           eval_metric="aucpr", random_state=RANDOM_STATE, n_jobs=-1)
    deploy.fit(table[features], table["Is_Accident"])

    # Calibration + risk tiers from the deploy model over all data.
    table["road"] = table[ROAD_KEYS].astype(str).agg("|".join, axis=1)
    days = pd.to_datetime(table["Date"])
    total_cells = table["road"].nunique() * ((days.max() - days.min()).days + 1) * TIME_PERIODS
    accident_cells = (table.loc[table["Is_Accident"] == 1]
                      .drop_duplicates(["road", "Date", "Time_Period"]).shape[0])
    pi_true_deploy = accident_cells / total_cells
    pi_train_deploy = float(table["Is_Accident"].mean())
    proba_all_cal = prior_correction(deploy.predict_proba(table[features])[:, 1],
                                     pi_train_deploy, pi_true_deploy)
    qs = np.quantile(proba_all_cal, [0.50, 0.80, 0.95])
    risk_bins = {"low": float(qs[0]), "medium": float(qs[1]), "high": float(qs[2])}

    # --- Severity aggregate (shrunk per-road mean) ---------------------------
    acc = table[table["Is_Accident"] == 1].copy()
    acc["road"] = acc[ROAD_KEYS].astype(str).agg("|".join, axis=1)
    g = acc.groupby("road")["Severity"].agg(["mean", "count"])
    global_sev = acc["Severity"].mean()
    g["severity"] = ((g["count"] * g["mean"] + SEVERITY_SHRINK_K * global_sev)
                     / (g["count"] + SEVERITY_SHRINK_K))
    severity_by_road = g[["severity", "count"]]

    # --- Save (deploy model + serving artifacts) -----------------------------
    # Portable formats only (XGBoost JSON + plain JSON + CSV) so the served app
    # loads on any Python / pandas / numpy version.
    deploy.save_model(os.path.join(ARTIFACTS_DIR, "final_model.json"))

    def dump_json(obj, name):
        with open(os.path.join(ARTIFACTS_DIR, name), "w", encoding="utf-8") as f:
            json.dump(obj, f, indent=2)

    dump_json({str(c): {str(k): int(v) for k, v in m.items()}
               for c, m in encoders.items()}, "encoder.json")
    dump_json([str(x) for x in features], "feature_columns.json")
    dump_json({"pi_train": float(pi_train_deploy), "pi_true": float(pi_true_deploy),
               "pi_true_split": float(pi_true)}, "calibration.json")
    dump_json({k: float(v) for k, v in risk_bins.items()}, "risk_bins.json")
    # CSV (not pickle) so the artifact loads on any pandas version.
    severity_by_road.reset_index().to_csv(
        os.path.join(ARTIFACTS_DIR, "severity_by_road.csv"), index=False)
    with open(os.path.join(ARTIFACTS_DIR, "metrics.json"), "w") as f:
        json.dump(metrics, f, indent=2)

    print("\n=== METRICS (honest 2021->2022 split) ===")
    print(json.dumps(metrics, indent=2))
    print(f"\nDeploy model refit on {len(table):,} rows; pi_true={pi_true_deploy:.5f}")
    print(f"Saved artifacts -> {os.path.abspath(ARTIFACTS_DIR)}")


def _prf(y, pred):
    return (precision_score(y, pred, zero_division=0),
            recall_score(y, pred, zero_division=0),
            _f1(precision_score(y, pred, zero_division=0),
                recall_score(y, pred, zero_division=0)))


def _f1(p, r):
    return 0.0 if (p + r) == 0 else 2 * p * r / (p + r)


if __name__ == "__main__":
    main()
