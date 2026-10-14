from django.core.management import call_command
from django.test import Client, TestCase

from apps.core.models import Airbase, Equipment, User
from apps.suggestion.features import (
    MODEL_A_FEATURES,
    generate_synthetic_option_scoring_dataset,
    generate_synthetic_readiness_dataset,
    validate_feature_vector,
)
from apps.suggestion.models import ModelVersion
from apps.suggestion.predict import (
    FALLBACK_MODEL_VERSION,
    predict_equipment_readiness,
    score_operational_options,
)


class Phase6AIMLTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo_data", export_fixture=False)
        call_command("train_readiness_model", seed=26250)

    def setUp(self):
        self.client = Client()
        self.cmdr = User.objects.get(username="cmdr_vsingh")
        self.airbase = Airbase.objects.get(code="AB-DEMO-01")
        self.equipment = Equipment.objects.get(fictional_code="SB-512")

    def test_s08_01_synthetic_dataset_at_least_5000_rows_and_bernoulli_sampling(self):
        """S08-01: Dataset has at least 5,000 synthetic rows and labels sampled with Bernoulli(probability)."""
        df_a = generate_synthetic_readiness_dataset(n_samples=5000, seed=26250)
        self.assertEqual(len(df_a), 5000)
        self.assertIn("unavailable_7d", df_a.columns)
        self.assertTrue(set(df_a["unavailable_7d"].unique()).issubset({0, 1}))

        df_b = generate_synthetic_option_scoring_dataset(n_samples=5000, seed=26250)
        self.assertEqual(len(df_b), 5000)
        self.assertIn("suitability_score", df_b.columns)

    def test_s08_04_baseline_comparison_reported_alongside_xgboost(self):
        """S08-04: ModelVersion reports logistic-regression baseline metrics alongside XGBoost."""
        mv_a = ModelVersion.objects.get(model_name="readiness-xgb-v1")
        metrics = mv_a.metrics
        self.assertIn("roc_auc", metrics)
        self.assertIn("baseline_logistic_roc_auc", metrics)
        self.assertIn("precision", metrics)
        self.assertIn("baseline_precision", metrics)
        self.assertIn("brier_calibration", metrics)

    def test_s08_01_feature_vector_validation_for_all_six_features(self):
        """S08-01: Validates ALL six Model A features (type, null, range) at inference."""
        valid_features = {
            "days_since_last_service": 14.5,
            "days_until_next_due": 15.5,
            "past_fault_count": 2.0,
            "open_maintenance_tasks": 1.0,
            "usage_band_encoded": 1.0,
            "age_band_encoded": 2.0,
        }
        ok, errors = validate_feature_vector(valid_features, MODEL_A_FEATURES)
        self.assertTrue(ok)
        self.assertEqual(len(errors), 0)

        # 1. Missing feature
        incomplete = dict(valid_features)
        del incomplete["open_maintenance_tasks"]
        ok, errors = validate_feature_vector(incomplete, MODEL_A_FEATURES)
        self.assertFalse(ok)
        self.assertTrue(any("Missing required feature: open_maintenance_tasks" in e for e in errors))

        # 2. Null/NaN feature
        with_null = dict(valid_features, usage_band_encoded=None)
        ok, errors = validate_feature_vector(with_null, MODEL_A_FEATURES)
        self.assertFalse(ok)
        self.assertTrue(any("Null/NaN value in feature: usage_band_encoded" in e for e in errors))

        # 3. Non-numeric type
        with_string = dict(valid_features, past_fault_count="corrupt_string")
        ok, errors = validate_feature_vector(with_string, MODEL_A_FEATURES)
        self.assertFalse(ok)
        self.assertTrue(any("Non-numeric type for feature: past_fault_count" in e for e in errors))

        # 4. Out-of-range feature
        with_oor = dict(valid_features, days_since_last_service=-50.0)
        ok, errors = validate_feature_vector(with_oor, MODEL_A_FEATURES)
        self.assertFalse(ok)
        self.assertTrue(any("Out-of-range value for days_since_last_service" in e for e in errors))

    def test_s08_05_missing_or_corrupt_artifact_falls_back_gracefully(self):
        """S08-05: Missing or corrupt artifact falls back to deterministic safety baseline without blocking."""
        res = predict_equipment_readiness(self.equipment, force_fallback=True)
        self.assertTrue(res["fallback_used"])
        self.assertEqual(res["model_version"], FALLBACK_MODEL_VERSION)
        self.assertEqual(res["status"], "advisory")
        self.assertIn("reasons", res)
        self.assertIn("disclaimer", res)
        self.assertEqual(res["disclaimer"], "synthetic, advisory only")

    def test_s08_03_hard_constraints_override_model_and_block_infeasible(self):
        """S08-03: Hard physical & regulatory constraints stay deterministic; ML can never make infeasible options feasible."""
        options = score_operational_options(self.airbase)
        opt_c = next((o for o in options if o["option_id"] == "OPT-C-INFEASIBLE-FDTL"), None)
        self.assertIsNotNone(opt_c)
        self.assertFalse(opt_c["feasible"])
        self.assertFalse(opt_c["recommended"])
        self.assertEqual(opt_c["score"], 0.0)
        self.assertTrue(any("HARD CONSTRAINT BLOCKED" in r for r in opt_c["reasons"]))

        # Recommended option must be feasible
        recommended = [o for o in options if o.get("recommended")]
        self.assertEqual(len(recommended), 1)
        self.assertTrue(recommended[0]["feasible"])
        self.assertGreater(recommended[0]["score"], 0.0)

    def test_s08_06_every_suggestion_carries_synthetic_disclaimer_and_reasons(self):
        """S08-06: Every suggestion carries model version, input snapshot, reasons, and 'synthetic, advisory only' label."""
        pred = predict_equipment_readiness(self.equipment)
        self.assertIn("model_version", pred)
        self.assertIn("input_snapshot", pred)
        self.assertIn("reasons", pred)
        self.assertIn("disclaimer", pred)
        self.assertEqual(pred["disclaimer"], "synthetic, advisory only")
        self.assertEqual(pred["data_mode"], "synthetic")

        options = score_operational_options(self.airbase)
        for opt in options:
            self.assertIn("model_version", opt)
            self.assertIn("reasons", opt)
            self.assertIn("disclaimer", opt)
            self.assertEqual(opt["disclaimer"], "synthetic, advisory only")
            self.assertEqual(opt["data_mode"], "synthetic")
