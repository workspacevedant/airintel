"""
Feature Preparation, Schema Validation & Synthetic Dataset Generator for AERO-OPS (Section 08 & 12).
Uses fixed seed 26250 so synthetic training/validation/test splits are 100% reproducible.
"""
from typing import Any, Dict, List, Tuple
import numpy as np
import pandas as pd
from django.utils import timezone

from apps.core.models import Airbase, CrewReadiness, Equipment, MaintenanceTask

MODEL_A_FEATURES: List[str] = [
    "days_since_last_service",
    "days_until_next_due",
    "past_fault_count",
    "open_maintenance_tasks",
    "usage_band_encoded",
    "age_band_encoded",
]

MODEL_B_FEATURES: List[str] = [
    "aircraft_ready_ratio",
    "crew_fdtl_compliant",
    "runway_primary_clear",
    "fuel_reserves_adequacy",
    "maintenance_conflict_score",
    "data_freshness_score",
]

USAGE_BAND_MAP = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
AGE_BAND_MAP = {"1-3_YEARS": 0, "3-5_YEARS": 1, "5-8_YEARS": 2, "8+_YEARS": 3}


def extract_equipment_features(equipment: Equipment, reference_time=None) -> Dict[str, float]:
    """
    Extracts and validates Model A features for a single Equipment record (Section 08).
    """
    ref = reference_time or timezone.now()
    days_since = max(0.0, (ref - equipment.last_service_at).total_seconds() / 86400.0)
    days_until = (equipment.next_due_at - ref).total_seconds() / 86400.0
    open_tasks = equipment.maintenance_tasks.exclude(
        status__in=[MaintenanceTask.TaskStatus.COMPLETED, MaintenanceTask.TaskStatus.VERIFIED]
    ).count()

    usage_enc = float(USAGE_BAND_MAP.get(str(equipment.usage_band).upper(), 1))
    age_enc = float(AGE_BAND_MAP.get(str(equipment.age_band).upper(), 1))

    return {
        "days_since_last_service": round(float(days_since), 2),
        "days_until_next_due": round(float(days_until), 2),
        "past_fault_count": float(equipment.past_fault_count),
        "open_maintenance_tasks": float(open_tasks),
        "usage_band_encoded": usage_enc,
        "age_band_encoded": age_enc,
    }


def validate_feature_vector(features: Dict[str, Any], expected_schema: List[str]) -> Tuple[bool, List[str]]:
    """
    Validates feature dictionary at inference time against expected schema and numeric bounds (Section 08 & 14).
    """
    errors: List[str] = []
    if not isinstance(features, dict):
        return False, ["Feature input must be a dictionary."]

    for col in expected_schema:
        if col not in features:
            errors.append(f"Missing required feature: {col}")
            continue
        val = features[col]
        if val is None or (isinstance(val, float) and np.isnan(val)):
            errors.append(f"Null/NaN value in feature: {col}")
            continue
        try:
            fval = float(val)
        except (TypeError, ValueError):
            errors.append(f"Non-numeric value in feature: {col}")
            continue

        if col == "days_since_last_service" and (fval < 0 or fval > 3650):
            errors.append(f"Out-of-range {col}: {fval}")
        elif col == "past_fault_count" and (fval < 0 or fval > 500):
            errors.append(f"Out-of-range {col}: {fval}")

    return len(errors) == 0, errors


def generate_synthetic_readiness_dataset(n_samples: int = 600, seed: int = 26250) -> pd.DataFrame:
    """
    Generates a documented, internally consistent synthetic dataset for Model A
    (7-day equipment unavailability prediction) with a time-ordered group column (Section 08).
    """
    rng = np.random.default_rng(seed)
    days_since = rng.uniform(1, 35, size=n_samples).round(1)
    days_until = (30.0 - days_since + rng.normal(0, 2.5, size=n_samples)).round(1)
    past_faults = rng.poisson(lam=1.6, size=n_samples)
    open_tasks = rng.binomial(n=2, p=0.28, size=n_samples)
    usage_band = rng.choice([0, 1, 2], size=n_samples, p=[0.30, 0.45, 0.25])
    age_band = rng.choice([0, 1, 2, 3], size=n_samples, p=[0.35, 0.35, 0.20, 0.10])
    time_Window = np.arange(n_samples) // 50  # Time-based split index to prevent leakage

    # Ground-truth synthetic log-odds (no post-outcome leakage)
    logit = (
        -2.4
        + 0.08 * days_since
        - 0.14 * days_until
        + 0.42 * past_faults
        + 0.85 * open_tasks
        + 0.45 * usage_band
        + 0.25 * age_band
        + rng.normal(0, 0.35, size=n_samples)
    )
    prob = 1.0 / (1.0 + np.exp(-logit))
    target = (prob >= 0.50).astype(int)

    return pd.DataFrame(
        {
            "time_group": time_Window,
            "days_since_last_service": days_since,
            "days_until_next_due": days_until,
            "past_fault_count": past_faults,
            "open_maintenance_tasks": open_tasks,
            "usage_band_encoded": usage_band,
            "age_band_encoded": age_band,
            "unavailable_7d": target,
        }
    )


def generate_synthetic_option_scoring_dataset(n_samples: int = 500, seed: int = 26250) -> pd.DataFrame:
    """
    Generates a documented synthetic dataset for Model B (generic option scoring) (Section 08).
    """
    rng = np.random.default_rng(seed + 100)
    aircraft_ready_ratio = rng.uniform(0.3, 1.0, size=n_samples).round(3)
    crew_fdtl_compliant = rng.choice([0.0, 1.0], size=n_samples, p=[0.2, 0.8])
    runway_primary_clear = rng.choice([0.0, 1.0], size=n_samples, p=[0.15, 0.85])
    fuel_reserves_adequacy = rng.uniform(0.4, 1.0, size=n_samples).round(3)
    maintenance_conflict_score = rng.uniform(0.0, 0.8, size=n_samples).round(3)
    data_freshness_score = rng.choice([0.4, 0.75, 1.0], size=n_samples, p=[0.1, 0.2, 0.7])
    scenario_group = np.arange(n_samples) // 25

    raw_score = (
        0.30 * aircraft_ready_ratio
        + 0.25 * crew_fdtl_compliant
        + 0.20 * runway_primary_clear
        + 0.15 * fuel_reserves_adequacy
        - 0.20 * maintenance_conflict_score
        + 0.10 * data_freshness_score
        + rng.normal(0, 0.02, size=n_samples)
    )
    suitability_score = np.clip(raw_score, 0.05, 0.98).round(4)

    return pd.DataFrame(
        {
            "scenario_group": scenario_group,
            "aircraft_ready_ratio": aircraft_ready_ratio,
            "crew_fdtl_compliant": crew_fdtl_compliant,
            "runway_primary_clear": runway_primary_clear,
            "fuel_reserves_adequacy": fuel_reserves_adequacy,
            "maintenance_conflict_score": maintenance_conflict_score,
            "data_freshness_score": data_freshness_score,
            "suitability_score": suitability_score,
        }
    )
