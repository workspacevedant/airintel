"""
Spatial & Temporal Models for the AERO-OPS Hybrid Radar Simulator (Section 06 & 09).
All coordinates use SRID 4326 (WGS 84) with GIST spatial indexes.
All sensor nodes and tracks represent synthetic, non-operational demonstration feeds.
"""
import uuid
from django.conf import settings
from django.contrib.gis.db import models as gis_models
from django.contrib.postgres.indexes import GistIndex
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone


class Scenario(models.Model):
    """
    Deterministic scenario recipe with fixed random seed 26250 (Section 06, 09 & 16).
    Example: SCENARIO-BASELINE-01.
    """

    class ScenarioStatus(models.TextChoices):
        READY = "READY", "Ready"
        ACTIVE = "ACTIVE", "Active"
        ARCHIVED = "ARCHIVED", "Archived"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=64, unique=True, db_index=True)
    name = models.CharField(max_length=140)
    version = models.CharField(max_length=24, default="1.0")
    seed = models.IntegerField(default=26250, help_text="Deterministic RNG seed (SIH26250 default: 26250).")
    status = models.CharField(
        max_length=16,
        choices=ScenarioStatus.choices,
        default=ScenarioStatus.READY,
        db_index=True,
    )
    configuration = models.JSONField(
        default=dict,
        help_text="Deterministic sequence definition, initial conditions, and fault injection steps.",
    )
    is_demo = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        db_table = "radar_scenario"
        ordering = ["code"]
        indexes = [
            models.Index(fields=["code", "status"], name="idx_scenario_code_status"),
        ]

    def __str__(self) -> str:
        return f"{self.code} (v{self.version}, seed={self.seed})"


class SimulationRun(models.Model):
    """
    Tracks an execution or deterministic replay of a Scenario (Section 06 & 09).
    """

    class RunState(models.TextChoices):
        IDLE = "IDLE", "Idle"
        RUNNING = "RUNNING", "Running"
        PAUSED = "PAUSED", "Paused"
        COMPLETED = "COMPLETED", "Completed"
        RESET = "RESET", "Reset"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run_code = models.CharField(max_length=64, unique=True, db_index=True)
    scenario = models.ForeignKey(
        Scenario,
        on_delete=models.CASCADE,
        related_name="runs",
        db_index=True,
    )
    started_at = models.DateTimeField(default=timezone.now, db_index=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    simulated_clock = models.DateTimeField(
        default=timezone.now,
        help_text="Distinct simulated timestamp separated from wall-clock time (Section 06).",
    )
    state = models.CharField(
        max_length=16,
        choices=RunState.choices,
        default=RunState.RUNNING,
        db_index=True,
    )
    speed = models.FloatField(default=1.0, help_text="Playback time multiplier (e.g., 1.0x, 2.0x).")
    seed = models.IntegerField(default=26250)
    current_sequence = models.PositiveIntegerField(default=0)
    last_heartbeat_at = models.DateTimeField(default=timezone.now, db_index=True)
    initiated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="initiated_simulation_runs",
    )

    class Meta:
        db_table = "radar_simulation_run"
        ordering = ["-started_at"]
        indexes = [
            models.Index(fields=["scenario", "state", "started_at"], name="idx_simrun_scen_state_time"),
        ]
        constraints = [
            models.CheckConstraint(
                check=Q(speed__gt=0.0) & Q(speed__lte=20.0),
                name="chk_simrun_speed_bounds",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.run_code} [{self.scenario.code}] — {self.state}"


class SensorNode(gis_models.Model):
    """
    Synthetic radar/observation sensor node in SRID 4326 (Section 06, 09 & Appendix A).
    Example: SENSOR-DEMO-01, SENSOR-DEMO-02, SENSOR-DEMO-03.
    """

    class HealthState(models.TextChoices):
        LIVE = "LIVE", "LIVE"
        STALE = "STALE", "STALE"
        OFFLINE = "OFFLINE", "OFFLINE"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    scenario = models.ForeignKey(
        Scenario,
        on_delete=models.CASCADE,
        related_name="sensor_nodes",
        db_index=True,
    )
    fictional_code = models.CharField(max_length=48, unique=True, db_index=True)
    name = models.CharField(max_length=120)
    zone = models.ForeignKey(
        "core.Zone",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sensor_nodes",
        db_index=True,
    )
    location = gis_models.PointField(srid=4326, spatial_index=True)
    coverage_radius_km = models.FloatField(default=220.0)
    health_state = models.CharField(
        max_length=16,
        choices=HealthState.choices,
        default=HealthState.LIVE,
        db_index=True,
    )
    last_seen_at = models.DateTimeField(default=timezone.now, db_index=True)
    is_synthetic = models.BooleanField(default=True)

    class Meta:
        db_table = "radar_sensor_node"
        ordering = ["fictional_code"]
        indexes = [
            GistIndex(fields=["location"], name="gist_sensor_location"),
            models.Index(fields=["scenario", "health_state"], name="idx_sensor_scen_health"),
            models.Index(fields=["last_seen_at"], name="idx_sensor_last_seen"),
        ]
        constraints = [
            models.CheckConstraint(
                check=Q(coverage_radius_km__gt=0.0),
                name="chk_sensor_coverage_positive",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.fictional_code} ({self.health_state})"


class Track(gis_models.Model):
    """
    Synthetic map marker and lifecycle record in SRID 4326 (Section 06, 09 & Appendix A).
    Examples: H-01 J-20, TRACK-DEMO-12.
    """

    class TrackState(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        UNDER_REVIEW = "UNDER_REVIEW", "Under Review"
        STALE = "STALE", "Stale / Uncertain"
        LOST = "LOST", "Lost"
        RESOLVED = "RESOLVED", "Resolved"

    class TrackQuality(models.TextChoices):
        SIMULATED = "simulated", "Simulated (High Confidence)"
        DEGRADED = "degraded", "Degraded (Single Source)"
        UNCERTAIN = "uncertain", "Uncertain / Stale Feed"
        LOW = "low", "Low Quality"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run = models.ForeignKey(
        SimulationRun,
        on_delete=models.CASCADE,
        related_name="tracks",
        db_index=True,
    )
    fictional_track_code = models.CharField(max_length=64, db_index=True)
    callsign_label = models.CharField(
        max_length=80,
        default="SYNTHETIC-UNKNOWN-PROFILE",
        help_text="Non-operational synthetic display label (e.g., H-01 J-20).",
    )
    state = models.CharField(
        max_length=20,
        choices=TrackState.choices,
        default=TrackState.UNDER_REVIEW,
        db_index=True,
    )
    last_position = gis_models.PointField(srid=4326, spatial_index=True)
    bearing = models.FloatField(
        default=0.0,
        help_text="Heading/bearing in degrees [0.0, 360.0].",
    )
    range_km = models.FloatField(
        default=50.0,
        help_text="Range from reporting synthetic sensor node in kilometres.",
    )
    altitude_m = models.FloatField(default=8500.0)
    speed_kts = models.FloatField(default=460.0)
    quality = models.CharField(
        max_length=24,
        choices=TrackQuality.choices,
        default=TrackQuality.SIMULATED,
        db_index=True,
    )
    source_sensor = models.ForeignKey(
        SensorNode,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tracks",
    )
    zone = models.ForeignKey(
        "core.Zone",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tracks",
        db_index=True,
    )
    last_seen_at = models.DateTimeField(default=timezone.now, db_index=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "radar_track"
        ordering = ["-last_seen_at"]
        unique_together = [("run", "fictional_track_code")]
        indexes = [
            GistIndex(fields=["last_position"], name="gist_track_last_position"),
            models.Index(fields=["run", "state", "last_seen_at"], name="idx_track_run_state_seen"),
            models.Index(fields=["fictional_track_code"], name="idx_track_fictional_code"),
        ]
        constraints = [
            models.CheckConstraint(
                check=Q(bearing__gte=0.0) & Q(bearing__lte=360.0),
                name="chk_track_bearing_degrees",
            ),
            models.CheckConstraint(
                check=Q(range_km__gte=0.0),
                name="chk_track_range_non_negative",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.fictional_track_code} [{self.state}] (Brg {self.bearing:.0f}°, {self.range_km:.1f} km)"


class SensorObservation(gis_models.Model):
    """
    Append-only synthetic sensor observation history (Section 06 & 09).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run = models.ForeignKey(
        SimulationRun,
        on_delete=models.CASCADE,
        related_name="observations",
        db_index=True,
    )
    sensor = models.ForeignKey(
        SensorNode,
        on_delete=models.CASCADE,
        related_name="observations",
        db_index=True,
    )
    track = models.ForeignKey(
        Track,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="observations",
        db_index=True,
    )
    sequence_num = models.PositiveIntegerField(default=1, db_index=True)
    observed_at = models.DateTimeField(default=timezone.now, db_index=True)
    position = gis_models.PointField(srid=4326, spatial_index=True)
    bearing = models.FloatField(default=0.0)
    range_km = models.FloatField(default=0.0)
    quality = models.CharField(max_length=24, default="simulated", db_index=True)
    payload = models.JSONField(default=dict)
    idempotency_key = models.CharField(max_length=128, unique=True, db_index=True)

    class Meta:
        db_table = "radar_sensor_observation"
        ordering = ["-observed_at", "-sequence_num"]
        indexes = [
            GistIndex(fields=["position"], name="gist_obs_position"),
            models.Index(fields=["run", "sequence_num"], name="idx_obs_run_seq"),
            models.Index(fields=["sensor", "observed_at"], name="idx_obs_sensor_time"),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding and SensorObservation.objects.filter(pk=self.pk).exists():
            raise ValidationError("SensorObservation is append-only and cannot be mutated.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionDenied("SensorObservation history is append-only and cannot be deleted.")

    def __str__(self) -> str:
        return f"Obs#{self.sequence_num} @ {self.sensor.fictional_code} ({self.observed_at.isoformat()})"
