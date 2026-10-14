"""
Management command:
    python manage.py train_readiness_model
Trains and evaluates Model A (readiness-xgb-v1) and Model B (option-scorer-xgb-v1)
with deterministic seed 26250 and saves artifacts to ml_artifacts/ (Section 08 & 16).
"""
import json
from django.core.management.base import BaseCommand
from apps.suggestion.train import train_and_register_models


class Command(BaseCommand):
    help = "Trains and evaluates AERO-OPS XGBoost readiness and option scoring models (seed 26250)."

    def add_arguments(self, parser):
        parser.add_argument("--seed", type=int, default=26250, help="Deterministic RNG seed (default: 26250).")

    def handle(self, *args, **options):
        seed = options["seed"]
        results = train_and_register_models(seed=seed)
        self.stdout.write(
            self.style.SUCCESS(
                f"Successfully trained & evaluated AERO-OPS XGBoost models (seed={seed}):\n"
                + json.dumps(results, indent=2)
            )
        )
