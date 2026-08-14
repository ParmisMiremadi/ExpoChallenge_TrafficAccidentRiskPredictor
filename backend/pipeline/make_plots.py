"""
Generate proof-of-performance images from the honest 2021->2022 split
predictions (test_predictions.pkl) and metrics.json.

Outputs (webapp_v3/backend/artifacts/plots/):
    risk_hotspot_map.png     predicted-risk vs actual-accident geographic heatmap
    roc_pr_curves.png        ROC + precision-recall curves
    calibration_curve.png    predicted vs observed probability
    confusion_matrix.png     at the chosen operating point
    feature_importance.png   top model features
"""
import json
import os

import joblib
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from sklearn.metrics import (auc, confusion_matrix, precision_recall_curve,
                             roc_curve)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
ARTIFACTS_DIR = os.path.join(BASE_DIR, "..", "artifacts")
PLOTS_DIR = os.path.join(ARTIFACTS_DIR, "plots")


def main():
    os.makedirs(PLOTS_DIR, exist_ok=True)
    pred = pd.read_pickle(os.path.join(OUTPUT_DIR, "test_predictions.pkl"))
    metrics = json.load(open(os.path.join(ARTIFACTS_DIR, "metrics.json")))
    y = pred["y"].to_numpy()
    p = pred["proba"].to_numpy()

    # --- 1. Geographic hotspot heatmap: predicted risk vs actual accidents ----
    fig, ax = plt.subplots(1, 2, figsize=(15, 6))
    hb = ax[0].hexbin(pred["Start_Lng"], pred["Start_Lat"], C=p, gridsize=90,
                      reduce_C_function=np.mean, cmap="inferno", mincnt=1)
    ax[0].set_title("Predicted accident risk (2022 test)")
    fig.colorbar(hb, ax=ax[0], label="mean predicted risk")
    pos = pred[pred["y"] == 1]
    hb2 = ax[1].hexbin(pos["Start_Lng"], pos["Start_Lat"], gridsize=90,
                       cmap="inferno", mincnt=1, bins="log")
    ax[1].set_title("Actual accidents (2022 test)")
    fig.colorbar(hb2, ax=ax[1], label="log count")
    for a in ax:
        a.set_xlabel("Longitude"); a.set_ylabel("Latitude")
        a.set_xlim(-125, -66); a.set_ylim(24, 50)
    fig.suptitle("Predicted risk lines up with where crashes actually happened",
                 fontsize=13)
    fig.tight_layout()
    fig.savefig(os.path.join(PLOTS_DIR, "risk_hotspot_map.png"), dpi=120)
    plt.close(fig)

    # --- 2. ROC + PR curves ---------------------------------------------------
    fpr, tpr, _ = roc_curve(y, p)
    prec, rec, _ = precision_recall_curve(y, p)
    fig, ax = plt.subplots(1, 2, figsize=(12, 5))
    ax[0].plot(fpr, tpr, lw=2, label=f"AUC = {auc(fpr, tpr):.3f}")
    ax[0].plot([0, 1], [0, 1], "--", color="gray")
    ax[0].set_title("ROC curve"); ax[0].set_xlabel("False positive rate")
    ax[0].set_ylabel("True positive rate"); ax[0].legend()
    ax[1].plot(rec, prec, lw=2, color="C1",
               label=f"AP = {metrics['xgb_pr_auc']:.3f}")
    ax[1].set_title("Precision-Recall curve"); ax[1].set_xlabel("Recall")
    ax[1].set_ylabel("Precision"); ax[1].legend()
    fig.tight_layout()
    fig.savefig(os.path.join(PLOTS_DIR, "roc_pr_curves.png"), dpi=120)
    plt.close(fig)

    # --- 3. Calibration curve -------------------------------------------------
    bins = np.linspace(0, 1, 11)
    idx = np.clip(np.digitize(p, bins) - 1, 0, 9)
    xs, ys = [], []
    for b in range(10):
        m = idx == b
        if m.sum():
            xs.append(p[m].mean()); ys.append(y[m].mean())
    fig, ax = plt.subplots(figsize=(6, 6))
    ax.plot([0, 1], [0, 1], "--", color="gray", label="perfect")
    ax.plot(xs, ys, "o-", lw=2, label="model")
    ax.set_title("Calibration (predicted vs observed)")
    ax.set_xlabel("Mean predicted probability"); ax.set_ylabel("Observed frequency")
    ax.legend(); fig.tight_layout()
    fig.savefig(os.path.join(PLOTS_DIR, "calibration_curve.png"), dpi=120)
    plt.close(fig)

    # --- 4. Confusion matrix at the operating point ---------------------------
    thr = metrics["operating_point"]["threshold"]
    cm = confusion_matrix(y, p >= thr)
    fig, ax = plt.subplots(figsize=(5.5, 5))
    im = ax.imshow(cm, cmap="Blues")
    for i in range(2):
        for j in range(2):
            ax.text(j, i, f"{cm[i, j]:,}", ha="center", va="center",
                    color="white" if cm[i, j] > cm.max() / 2 else "black")
    ax.set_xticks([0, 1]); ax.set_xticklabels(["No acc.", "Accident"])
    ax.set_yticks([0, 1]); ax.set_yticklabels(["No acc.", "Accident"])
    ax.set_xlabel("Predicted"); ax.set_ylabel("Actual")
    ax.set_title(f"Confusion matrix @ threshold {thr}")
    fig.colorbar(im); fig.tight_layout()
    fig.savefig(os.path.join(PLOTS_DIR, "confusion_matrix.png"), dpi=120)
    plt.close(fig)

    # --- 5. Feature importance ------------------------------------------------
    fi = metrics["feature_importance_top"][::-1]
    names = [f for f, _ in fi]
    vals = [v for _, v in fi]
    fig, ax = plt.subplots(figsize=(8, 6))
    ax.barh(names, vals, color="C2")
    ax.set_title("Top feature importances"); ax.set_xlabel("importance (gain)")
    fig.tight_layout()
    fig.savefig(os.path.join(PLOTS_DIR, "feature_importance.png"), dpi=120)
    plt.close(fig)

    print("Saved plots ->", os.path.abspath(PLOTS_DIR))
    for f in sorted(os.listdir(PLOTS_DIR)):
        print("  ", f)


if __name__ == "__main__":
    main()
