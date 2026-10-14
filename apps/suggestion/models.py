"""
AI Advisory Models for AERO-OPS (Section 08, 09 & 10).
Stores versioned XGBoost model metadata, evaluation metrics, feature schemas,
and human-reviewed advisory Suggestions with plain-language reason codes.
"""
import uuid
from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone


class ModelVersion(models.Model):
    """
    Versioned ML artifact metadata and evaluation metrics (Section 08 & 09).
    Examples: readiness-xgb-v1 (Model A), option-scorer-xgb-v1 (Model B).
    """

    class ModelTask(models.TextChoices):
        READINESS_PREDICTION = "READINESS_PREDICTION", "Model A — 7-Day Equipment Readiness Prediction"
        OPTION_SCORING = "OPTION_SCORING", "Model B — Generic Resource Option Scoring"
        DETERMINISTIC_BASELINE = "DETERMINISTIC_BASELINE", "Deterministic Weighted Rule Baseline"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    model_name = models.CharField(max_length=80, db_index=True)
    version = models.CharField(max_length=32, db_index=True)
    task_type = models.CharField(
        max_length=32,
        choices=ModelTask.choices,
        default=ModelTask.READINESS_PREDICTION,
        db_index=True,
    )
    artifact_path = models.CharField(max_length=255)
    artifact_checksum = models.CharField(
        max_length=128,
        default="sha256:synthetic-demo-verified",
        help_text="SHA-256 digest for model integrity verification (Section 11).",
    )
    feature_schema = models.JSONField(
        default=list,
        help_text="Ordered feature names and expected ranges/types validated at inference time.",
    )
    metrics = models.JSONField(
        default=dict,
        help_text="ROC-AUC, precision, recall, calibration, or NDCG vs baseline.",
    )
    decision_threshold = models.FloatField(default=0.50)
    training_seed = models.IntegerField(default=26250)
    training_data_version = models.CharField(max_length=64, default="synth-dataset-v1-seed26250")
    is_active = models.BooleanField(default=True, db_index=True)
    trained_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        db_table = "suggestion_model_version"
        ordering = ["-trained_at"]
        unique_together = [("model_name", "version")]
        indexes = [
            models.Index(fields=["model_name", "is_active"], name="idx_modelver_name_active"),
            models.Index(fields=["task_type", "is_active"], name="idx_modelver_task_active"),
        ]

    def __str__(self) -> str:
        return f"{self.model_name} ({self.version}) [{self.task_type}]"


class Suggestion(models.Model):
    """
    Explainable human-in-the-loop advisory recommendation (Section 08, 09 & 10).
    Never executes operational actions autonomously; requires human review.
    """

    class SuggestionKind(models.TextChoices):
        READINESS_WARNING = "readiness_warning", "7-Day Equipment Readiness Warning"
        OPTION_SCORE = "option_score", "Generic Resource Option Score"
        CREW_CONSTRAINT = "crew_constraint", "FDTL / Crew Availability Constraint"
        SENSOR_DEGRADATION = "sensor_degradation", "Sensor Feed Freshness Advisory"

    class SuggestionStatus(models.TextChoices):
        ADVISORY = "advisory", "Advisory (Pending Human Review)"
        ACCEPTED = "accepted", "Accepted by Authorised Officer"
        DISMISSED = "dismissed", "Dismissed"
        REVIEW_REQUESTED = "review_requested", "Escalated for Command Review"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    suggestion_code = models.CharField(max_length=64, unique=True, db_index=True)
    kind = models.CharField(
        max_length=32,
        choices=SuggestionKind.choices,
        default=SuggestionKind.READINESS_WARNING,
        db_index=True,
    )
    scope = models.CharField(
        max_length=64,
        db_index=True,
        help_text="Target scope code (e.g., AB-DEMO-01, SQ-DEMO-01, ZONE-DEMO-A).",
    )
    airbase = models.ForeignKey(
        "core.Airbase",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="suggestions",
        db_index=True,
    )
    squadron = models.ForeignKey(
        "core.Squadron",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="suggestions",
    )
    equipment = models.ForeignKey(
        "core.Equipment",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="suggestions",
    )
    related_order = models.ForeignKey(
        "core.Order",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="suggestions",
    )
    model_version = models.ForeignKey(
        ModelVersion,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="suggestions",
        db_index=True,
    )
    title = models.CharField(max_length=180)
    input_snapshot = models.JSONField(
        default=dict,
        help_text="Exact validated feature dictionary used to compute the prediction/score.",
    )
    score = models.FloatField(
        help_text="Primary model probability or option suitability score in [0.0, 1.0].",
    )
    baseline_score = models.FloatField(
        default=0.50,
        help_text="Deterministic rule-based baseline score for side-by-side comparison (Section 15).",
    )
    uncertainty = models.FloatField(
        default=0.08,
        help_text="Calibration uncertainty margin displayed alongside score (Section 08).",
    )
    data_freshness_label = models.CharField(max_length=32, default="LIVE (<30s)")
    fallback_used = models.BooleanField(
        default=False,
        help_text="True if XGBoost artifact was unavailable and deterministic rules were used.",
    )
    reasons = models.JSONField(
        default=list,
        help_text="Plain-language explanation strings and top feature contributions.",
    )
    disclaimer = models.CharField(
        max_length=240,
        default="SYNTHETIC ADVISORY ONLY — Requires authorised human commander review.",
    )
    data_mode = models.CharField(max_length=24, default="synthetic")
    status = models.CharField(
        max_length=24,
        choices=SuggestionStatus.choices,
        default=SuggestionStatus.ADVISORY,
        db_index=True,
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_suggestions",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        db_table = "suggestion_advisory"
        ordering = ["-created_at", "-score"]
        indexes = [
            models.Index(fields=["scope", "status", "created_at"], name="idx_sugg_scope_status_time"),
            models.Index(fields=["airbase", "kind", "status"], name="idx_sugg_base_kind_status"),
        ]
        constraints = [
            models.CheckConstraint(
                check=Q(score__gte=0.0) & Q(score__lte=1.0),
                name="chk_suggestion_score_unit_interval",
            ),
            models.CheckConstraint(
                check=Q(baseline_score__gte=0.0) & Q(baseline_score__lte=1.0),
                name="chk_suggestion_baseline_unit_interval",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.suggestion_code} [{self.kind}] score={self.score:.2f} ({self.status})"
