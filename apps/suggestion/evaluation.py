"""
Model Evaluation Metrics & Baseline Comparison for AERO-OPS (Section 08 & 12).
Computes ROC-AUC, precision, recall, Brier calibration, confusion matrix (Model A)
and ranking agreement / NDCG@3 (Model B).
"""
from typing import Any, Dict
import numpy as np
from sklearn.metrics import (
    brier_score_loss,
    confusion_matrix,
    ndcg_score,
    precision_score,
    recall_score,
    roc_auc_score,
)


def evaluate_binary_readiness_model(
    y_true: np.ndarray,
    y_prob_xgb: np.ndarray,
    y_prob_baseline: np.ndarray,
    threshold: float = 0.50,
) -> Dict[str, Any]:
    """Compare Model A (XGBoost) against the Logistic Regression / majority baseline."""
    y_pred_xgb = (y_prob_xgb >= threshold).astype(int)
    y_pred_base = (y_prob_baseline >= threshold).astype(int)
    tn, fp, fn, tp = confusion_matrix(y_true, y_pred_xgb, labels=[0, 1]).ravel()

    return {
        "roc_auc": round(float(roc_auc_score(y_true, y_prob_xgb)), 4),
        "precision": round(float(precision_score(y_true, y_pred_xgb, zero_division=0)), 4),
        "recall": round(float(recall_score(y_true, y_pred_xgb, zero_division=0)), 4),
        "brier_calibration": round(float(brier_score_loss(y_true, y_prob_xgb)), 4),
        "confusion_matrix": {"tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)},
        "baseline_logistic_roc_auc": round(float(roc_auc_score(y_true, y_prob_baseline)), 4),
        "baseline_precision": round(float(precision_score(y_true, y_pred_base, zero_division=0)), 4),
        "baseline_recall": round(float(recall_score(y_true, y_pred_base, zero_division=0)), 4),
    }


def evaluate_option_scoring_model(
    y_true: np.ndarray,
    y_pred_xgb: np.ndarray,
    y_pred_baseline: np.ndarray,
) -> Dict[str, Any]:
    """Compare Model B (XGBoost) against the weighted deterministic baseline using NDCG@3 and correlation."""
    n_groups = max(1, len(y_true) // 5)
    trimmed = n_groups * 5
    true_mat = y_true[:trimmed].reshape(n_groups, 5)
    xgb_mat = y_pred_xgb[:trimmed].reshape(n_groups, 5)

    ndcg_val = float(ndcg_score(true_mat, xgb_mat, k=3))
    corr = float(np.corrcoef(y_pred_xgb, y_pred_baseline)[0, 1])
    rmse = float(np.sqrt(np.mean((y_true - y_pred_xgb) ** 2)))

    return {
        "ndcg_at_3": round(ndcg_val, 4),
        "ranking_agreement_vs_baseline": round(corr, 4),
        "rmse": round(rmse, 4),
    }
