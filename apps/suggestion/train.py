"""
Training Pipeline for AERO-OPS Model A (Readiness Prediction) & Model B (Option Scoring) (Section 08, 12 & 16).
Never called inside web request handlers; executed via management command or setup script.
"""
import hashlib
from pathlib import Path
from typing import Any, Dict

from django.conf import settings
from django.utils import timezone
from sklearn.linear_model import LogisticRegression
from xgboost import XGBClassifier, XGBRegressor

from apps.suggestion.evaluation import (
    evaluate_binary_readiness_model,
    evaluate_option_scoring_model,
)
from apps.suggestion.features import (
    MODEL_A_FEATURES,
    MODEL_B_FEATURES,
    generate_synthetic_option_scoring_dataset,
    generate_synthetic_readiness_dataset,
)
from apps.suggestion.models import ModelVersion


def _compute_sha256(filepath: Path) -> str:
    h = hashlib.sha256()
    h.update(filepath.read_bytes())
    return f"sha256:{h.hexdigest()}"


def train_and_register_models(seed: int = 26250) -> Dict[str, Any]:
    """
    Trains Model A (readiness-xgb-v1) and Model B (option-scorer-xgb-v1) on time/scenario-split
    synthetic datasets, compares against baselines, writes artifacts to ML_ARTIFACTS_DIR,
    and updates ModelVersion records in PostgreSQL (Section 08).
    """
    artifacts_dir = Path(settings.ML_ARTIFACTS_DIR)
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # 1. Train Model A — 7-Day Equipment Readiness Prediction
    # ------------------------------------------------------------------
    df_a = generate_synthetic_readiness_dataset(n_samples=5000, seed=seed)
    # Time-based split: groups 0..8 train, 9..11 test (prevents leakage)
    train_a = df_a[df_a["time_group"] < 9]
    test_a = df_a[df_a["time_group"] >= 9]

    X_train_a = train_a[MODEL_A_FEATURES]
    y_train_a = train_a["unavailable_7d"].values
    X_test_a = test_a[MODEL_A_FEATURES]
    y_test_a = test_a["unavailable_7d"].values

    baseline_clf = LogisticRegression(random_state=seed, max_iter=500)
    baseline_clf.fit(X_train_a, y_train_a)
    y_prob_base = baseline_clf.predict_proba(X_test_a)[:, 1]

    xgb_clf = XGBClassifier(
        n_estimators=65,
        max_depth=3,
        learning_rate=0.08,
        subsample=0.9,
        colsample_bytree=0.9,
        random_state=seed,
        eval_metric="logloss",
    )
    xgb_clf.fit(X_train_a, y_train_a)
    y_prob_xgb = xgb_clf.predict_proba(X_test_a)[:, 1]

    metrics_a = evaluate_binary_readiness_model(
        y_true=y_test_a,
        y_prob_xgb=y_prob_xgb,
        y_prob_baseline=y_prob_base,
        threshold=0.50,
    )

    artifact_a_path = artifacts_dir / "readiness_xgb_v1.json"
    xgb_clf.save_model(str(artifact_a_path))
    # Also save .xgb alias for compatibility
    artifact_a_xgb = artifacts_dir / "readiness_xgb_v1.xgb"
    xgb_clf.save_model(str(artifact_a_xgb))
    checksum_a = _compute_sha256(artifact_a_path)

    mv_a, _ = ModelVersion.objects.update_or_create(
        model_name="readiness-xgb-v1",
        version="1.0.0",
        defaults={
            "task_type": ModelVersion.ModelTask.READINESS_PREDICTION,
            "artifact_path": str(artifact_a_path),
            "artifact_checksum": checksum_a,
            "feature_schema": MODEL_A_FEATURES,
            "metrics": metrics_a,
            "decision_threshold": 0.50,
            "training_seed": seed,
            "training_data_version": f"synth-readiness-v1-seed{seed}",
            "is_active": True,
            "trained_at": timezone.now(),
        },
    )

    # ------------------------------------------------------------------
    # 2. Train Model B — Generic Option Scoring
    # ------------------------------------------------------------------
    df_b = generate_synthetic_option_scoring_dataset(n_samples=5000, seed=seed)
    train_b = df_b[df_b["scenario_group"] < 15]
    test_b = df_b[df_b["scenario_group"] >= 15]

    X_train_b = train_b[MODEL_B_FEATURES]
    y_train_b = train_b["suitability_score"].values
    X_test_b = test_b[MODEL_B_FEATURES]
    y_test_b = test_b["suitability_score"].values

    xgb_reg = XGBRegressor(
        n_estimators=60,
        max_depth=3,
        learning_rate=0.08,
        random_state=seed,
    )
    xgb_reg.fit(X_train_b, y_train_b)
    y_pred_b_xgb = xgb_reg.predict(X_test_b)

    # Weighted deterministic baseline for comparison
    y_pred_b_base = (
        0.30 * X_test_b["aircraft_ready_ratio"].values
        + 0.25 * X_test_b["crew_fdtl_compliant"].values
        + 0.20 * X_test_b["runway_primary_clear"].values
        + 0.15 * X_test_b["fuel_reserves_adequacy"].values
        - 0.20 * X_test_b["maintenance_conflict_score"].values
        + 0.10 * X_test_b["data_freshness_score"].values
    )

    metrics_b = evaluate_option_scoring_model(
        y_true=y_test_b,
        y_pred_xgb=y_pred_b_xgb,
        y_pred_baseline=y_pred_b_base,
    )

    artifact_b_path = artifacts_dir / "option_scorer_xgb_v1.json"
    xgb_reg.save_model(str(artifact_b_path))
    artifact_b_xgb = artifacts_dir / "option_scorer_xgb_v1.xgb"
    xgb_reg.save_model(str(artifact_b_xgb))
    checksum_b = _compute_sha256(artifact_b_path)

    mv_b, _ = ModelVersion.objects.update_or_create(
        model_name="option-scorer-xgb-v1",
        version="1.0.0",
        defaults={
            "task_type": ModelVersion.ModelTask.OPTION_SCORING,
            "artifact_path": str(artifact_b_path),
            "artifact_checksum": checksum_b,
            "feature_schema": MODEL_B_FEATURES,
            "metrics": metrics_b,
            "decision_threshold": 0.60,
            "training_seed": seed,
            "training_data_version": f"synth-options-v1-seed{seed}",
            "is_active": True,
            "trained_at": timezone.now(),
        },
    )

    return {
        "model_a": {
            "model_name": mv_a.model_name,
            "version": mv_a.version,
            "artifact_path": mv_a.artifact_path,
            "checksum": checksum_a,
            "metrics": metrics_a,
        },
        "model_b": {
            "model_name": mv_b.model_name,
            "version": mv_b.version,
            "artifact_path": mv_b.artifact_path,
            "checksum": checksum_b,
            "metrics": metrics_b,
        },
    }
