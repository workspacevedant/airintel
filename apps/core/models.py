"""
Core & Spatial Models for AERO-OPS (Project ID: SIH26250).
Enforces PostGIS spatial indexing (SRID 4326), B-tree indexes, check constraints,
and append-only immutability on AuditLog.
"""
import uuid
from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.contrib.gis.db import models as gis_models
from django.contrib.postgres.indexes import GistIndex
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone


class DesignationChoices(models.TextChoices):
    AIRBASE_COMMANDER = "AIRBASE_COMMANDER", "Airbase Commander"
    SQUADRON_LEADER = "SQUADRON_LEADER", "Squadron Leader"
    ZONAL_COMMANDER = "ZONAL_COMMANDER", "Zonal Commander"


class User(AbstractUser):
    """
    Custom User model for AERO-OPS (Section 04 & 09).
    Stores display_name and requested_designation.
    Self-selected designation at registration never grants automatic scope access;
    object-level permissions require an active RoleAssignment.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True, db_index=True)
    display_name = models.CharField(max_length=120)
    requested_designation = models.CharField(
        max_length=32,
        choices=DesignationChoices.choices,
        default=DesignationChoices.SQUADRON_LEADER,
        db_index=True,
    )
    active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    REQUIRED_FIELDS = ["email", "display_name", "requested_designation"]

    class Meta:
        db_table = "core_user"
        ordering = ["username"]
        indexes = [
            models.Index(fields=["requested_designation", "active"], name="idx_user_desig_active"),
            models.Index(fields=["created_at"], name="idx_user_created_at"),
        ]

    def save(self, *args, **kwargs):
        self.is_active = self.active
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.display_name} ({self.get_requested_designation_display()})"


class Profile(models.Model):
    """
    Explicit Profile record paired 1-to-1 with User (Section 04 & 09).
    Maintains compatibility with views/services inspecting user.profile.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profile",
        primary_key=True,
    )
    display_name = models.CharField(max_length=120)
    requested_designation = models.CharField(
        max_length=32,
        choices=DesignationChoices.choices,
        default=DesignationChoices.SQUADRON_LEADER,
    )
    service_number = models.CharField(max_length=32, blank=True, default="SYNTH-MOD-000")
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        db_table = "core_profile"

    def __str__(self) -> str:
        return f"Profile: {self.display_name} [{self.requested_designation}]"


class Zone(gis_models.Model):
    """
    Fictional operational sector/zone polygon in SRID 4326 (Section 09 & Appendix A).
    Example: ZONE-DEMO-A.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=32, unique=True, db_index=True)
    name = models.CharField(max_length=120)
    boundary = gis_models.PolygonField(srid=4326, spatial_index=True)
    is_demo = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        db_table = "core_zone"
        ordering = ["code"]
        indexes = [
            GistIndex(fields=["boundary"], name="gist_zone_boundary"),
            models.Index(fields=["code", "is_demo"], name="idx_zone_code_demo"),
        ]

    def __str__(self) -> str:
        return f"{self.code} — {self.name}"


class Airbase(gis_models.Model):
    """
    Fictional airbase resource parent scope in SRID 4326 (Section 05, 09 & Variant C UI).
    Example: AB-DEMO-01 / Avalon Forward Base.
    """

    class AirbaseStatus(models.TextChoices):
        OPERATIONAL = "OPERATIONAL", "Operational"
        DEGRADED = "DEGRADED", "Degraded"
        MAINTENANCE = "MAINTENANCE", "Maintenance"
        OFFLINE = "OFFLINE", "Offline"

    class RunwayStatus(models.TextChoices):
        CLEAR = "CLEAR", "CLEAR"
        MAINT = "MAINT", "MAINT"
        CLOSED = "CLOSED", "CLOSED"

    class ArrestorGearStatus(models.TextChoices):
        OPERATIONAL = "OPERATIONAL", "OPERATIONAL"
        DEGRADED = "DEGRADED", "DEGRADED"
        OFFLINE = "OFFLINE", "OFFLINE"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=32, unique=True, db_index=True)
    name = models.CharField(max_length=120)
    zone = models.ForeignKey(
        Zone,
        on_delete=models.PROTECT,
        related_name="airbases",
        db_index=True,
    )
    location = gis_models.PointField(srid=4326, spatial_index=True)
    runway_primary_label = models.CharField(max_length=32, default="Runway 09/27")
    runway_primary_m = models.PositiveIntegerField(default=3200)
    runway_primary_status = models.CharField(
        max_length=16,
        choices=RunwayStatus.choices,
        default=RunwayStatus.CLEAR,
        db_index=True,
    )
    runway_secondary_label = models.CharField(max_length=32, default="Runway 14/32")
    runway_secondary_m = models.PositiveIntegerField(default=2800)
    runway_secondary_status = models.CharField(
        max_length=16,
        choices=RunwayStatus.choices,
        default=RunwayStatus.MAINT,
        db_index=True,
    )
    arrestor_gear_status = models.CharField(
        max_length=16,
        choices=ArrestorGearStatus.choices,
        default=ArrestorGearStatus.OPERATIONAL,
        db_index=True,
    )
    fuel_reserves_mt = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        default=450.00,
        help_text="Jet-A1 Fuel reserves in Metric Tonnes (MT).",
    )
    status = models.CharField(
        max_length=20,
        choices=AirbaseStatus.choices,
        default=AirbaseStatus.OPERATIONAL,
        db_index=True,
    )
    is_demo = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_airbases",
    )
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "core_airbase"
        ordering = ["code"]
        indexes = [
            GistIndex(fields=["location"], name="gist_airbase_location"),
            models.Index(fields=["zone", "status"], name="idx_airbase_zone_status"),
            models.Index(fields=["created_at"], name="idx_airbase_created_at"),
        ]
        constraints = [
            models.CheckConstraint(
                check=Q(runway_primary_m__gte=500) & Q(runway_secondary_m__gte=0),
                name="chk_airbase_runway_lengths_valid",
            ),
            models.CheckConstraint(
                check=Q(fuel_reserves_mt__gte=0),
                name="chk_airbase_fuel_non_negative",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.code})"


class Squadron(models.Model):
    """
    Fictional organisational unit under an Airbase (Section 05, 09 & Appendix A).
    Example: SQ-DEMO-01 / No. 17 Squadron.
    """

    class SquadronStatus(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        STAND_DOWN = "STAND_DOWN", "Stand Down"
        DEPLOYED = "DEPLOYED", "Deployed"
        MAINTENANCE_HOLD = "MAINTENANCE_HOLD", "Maintenance Hold"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=32, unique=True, db_index=True)
    name = models.CharField(max_length=120)
    airbase = models.ForeignKey(
        Airbase,
        on_delete=models.CASCADE,
        related_name="squadrons",
        db_index=True,
    )
    leader_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="led_squadrons",
        db_index=True,
    )
    assigned_aircraft_type = models.CharField(max_length=64, default="Dassault Rafale / Su-30MKI")
    status = models.CharField(
        max_length=24,
        choices=SquadronStatus.choices,
        default=SquadronStatus.ACTIVE,
        db_index=True,
    )
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "core_squadron"
        ordering = ["code"]
        indexes = [
            models.Index(fields=["airbase", "status"], name="idx_squadron_airbase_status"),
            models.Index(fields=["leader_user"], name="idx_squadron_leader"),
        ]

    def __str__(self) -> str:
        return f"{self.code} — {self.name} ({self.airbase.code})"


class RoleAssignment(models.Model):
    """
    Explicit server-side RBAC role and scope binding (Section 04 & 09).
    Restricts users to an assigned Airbase, Squadron, or Zone.
    """

    class AssignmentStatus(models.TextChoices):
        PENDING = "PENDING", "Pending Approval"
        ACTIVE = "ACTIVE", "Active"
        REVOKED = "REVOKED", "Revoked"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="role_assignments",
        db_index=True,
    )
    role = models.CharField(
        max_length=32,
        choices=DesignationChoices.choices,
        db_index=True,
    )
    airbase = models.ForeignKey(
        Airbase,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="role_assignments",
        db_index=True,
    )
    squadron = models.ForeignKey(
        Squadron,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="role_assignments",
        db_index=True,
    )
    zone = models.ForeignKey(
        Zone,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="role_assignments",
        db_index=True,
    )
    status = models.CharField(
        max_length=16,
        choices=AssignmentStatus.choices,
        default=AssignmentStatus.PENDING,
        db_index=True,
    )
    can_control_simulation = models.BooleanField(
        default=False,
        help_text="Demo-only permission for starting/pausing/resetting scenarios.",
    )
    granted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="granted_role_assignments",
    )
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "core_role_assignment"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "status", "role"], name="idx_role_user_status"),
            models.Index(fields=["airbase", "status"], name="idx_role_airbase_status"),
            models.Index(fields=["zone", "status"], name="idx_role_zone_status"),
        ]
        constraints = [
            models.CheckConstraint(
                check=Q(
                    role__in=[
                        "AIRBASE_COMMANDER",
                        "SQUADRON_LEADER",
                        "ZONAL_COMMANDER",
                    ]
                ),
                name="chk_role_assignment_valid_role",
            ),
        ]

    def __str__(self) -> str:
        scope_parts = [
            s.code for s in (self.zone, self.airbase, self.squadron) if s is not None
        ]
        scope_label = "/".join(scope_parts) if scope_parts else "UNSCOPED"
        return f"{self.user.username} -> {self.role} [{scope_label}] ({self.status})"


class Equipment(models.Model):
    """
    Fictional aircraft/equipment inventory item (Section 05.5 & 09).
    Examples: SB-512, SB-514, RF-102, RF-104, EQ-DEMO-014.
    Workflow: AVAILABLE -> AIRBORNE / MAINTENANCE / UNAVAILABLE -> INSPECTED -> AVAILABLE.
    """

    class EquipmentCategory(models.TextChoices):
        SU_30MKI = "Su-30MKI", "Su-30MKI"
        DASSAULT_RAFALE = "Dassault Rafale", "Dassault Rafale"
        TEJAS_MK1A = "HAL Tejas Mk1A", "HAL Tejas Mk1A"
        RADAR_SUPPORT = "Ground Support / Radar Unit", "Ground Support / Radar Unit"

    class EquipmentStatus(models.TextChoices):
        AVAILABLE = "AVAILABLE", "Available"
        AIRBORNE = "AIRBORNE", "Airborne"
        MAINTENANCE = "MAINTENANCE", "Maintenance"
        UNAVAILABLE = "UNAVAILABLE", "Unavailable"
        INSPECTED = "INSPECTED", "Inspected"

    class ReadinessState(models.TextChoices):
        READY = "READY", "Ready"
        DEGRADED = "DEGRADED", "Degraded"
        GROUNDED = "GROUNDED", "Grounded"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    fictional_code = models.CharField(max_length=32, unique=True, db_index=True)
    category = models.CharField(
        max_length=64,
        choices=EquipmentCategory.choices,
        default=EquipmentCategory.DASSAULT_RAFALE,
        db_index=True,
    )
    squadron = models.ForeignKey(
        Squadron,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="equipment",
        db_index=True,
    )
    airbase = models.ForeignKey(
        Airbase,
        on_delete=models.CASCADE,
        related_name="equipment",
        db_index=True,
    )
    payload_config = models.CharField(
        max_length=120,
        default="Standard Patrol / Surveillance Config",
        help_text="Generic non-tactical load configuration label.",
    )
    weight_delta_kg = models.IntegerField(default=0)
    combat_radius_km = models.PositiveIntegerField(default=1200)
    status = models.CharField(
        max_length=20,
        choices=EquipmentStatus.choices,
        default=EquipmentStatus.AVAILABLE,
        db_index=True,
    )
    readiness_state = models.CharField(
        max_length=20,
        choices=ReadinessState.choices,
        default=ReadinessState.READY,
        db_index=True,
    )
    last_service_at = models.DateTimeField(default=timezone.now, db_index=True)
    next_due_at = models.DateTimeField(db_index=True)
    past_fault_count = models.PositiveIntegerField(default=0)
    usage_band = models.CharField(max_length=32, default="MEDIUM")
    age_band = models.CharField(max_length=32, default="3-5_YEARS")
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True, db_index=True)

    class Meta:
        db_table = "core_equipment"
        ordering = ["fictional_code"]
        indexes = [
            models.Index(
                fields=["airbase", "status", "readiness_state"],
                name="idx_equip_base_status_ready",
            ),
            models.Index(fields=["squadron", "status"], name="idx_equip_sq_status"),
            models.Index(fields=["next_due_at"], name="idx_equip_next_due"),
        ]
        constraints = [
            models.CheckConstraint(
                check=Q(combat_radius_km__gt=0),
                name="chk_equipment_combat_radius_positive",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.fictional_code} ({self.category}) — {self.status}"


class MaintenanceTask(models.Model):
    """
    Equipment maintenance workflow tracking (Section 05.5 & 09).
    Workflow: OPEN -> IN_PROGRESS -> WAITING_PARTS -> COMPLETED -> VERIFIED.
    """

    class Severity(models.TextChoices):
        LOW = "LOW", "Low"
        MEDIUM = "MEDIUM", "Medium"
        HIGH = "HIGH", "High"
        CRITICAL = "CRITICAL", "Critical"

    class TaskStatus(models.TextChoices):
        OPEN = "OPEN", "Open"
        IN_PROGRESS = "IN_PROGRESS", "In Progress"
        WAITING_PARTS = "WAITING_PARTS", "Waiting Parts"
        COMPLETED = "COMPLETED", "Completed"
        VERIFIED = "VERIFIED", "Verified"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    equipment = models.ForeignKey(
        Equipment,
        on_delete=models.CASCADE,
        related_name="maintenance_tasks",
        db_index=True,
    )
    opened_at = models.DateTimeField(default=timezone.now, db_index=True)
    due_at = models.DateTimeField(db_index=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    severity = models.CharField(
        max_length=16,
        choices=Severity.choices,
        default=Severity.MEDIUM,
        db_index=True,
    )
    fault_code = models.CharField(max_length=48, db_index=True)
    description = models.TextField()
    notes = models.TextField(blank=True, default="")
    status = models.CharField(
        max_length=20,
        choices=TaskStatus.choices,
        default=TaskStatus.OPEN,
        db_index=True,
    )
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_maintenance_tasks",
        db_index=True,
    )
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "core_maintenance_task"
        ordering = ["-opened_at"]
        indexes = [
            models.Index(
                fields=["equipment", "status", "due_at"],
                name="idx_maint_equip_status_due",
            ),
            models.Index(fields=["status", "severity"], name="idx_maint_status_sev"),
        ]
        constraints = [
            models.CheckConstraint(
                check=Q(due_at__gte=models.F("opened_at")),
                name="chk_maint_due_after_opened",
            ),
        ]

    def __str__(self) -> str:
        return f"[{self.fault_code}] {self.equipment.fictional_code} ({self.status})"


class CrewReadiness(models.Model):
    """
    Flight crew and ground support readiness & FDTL tracking (Section 05.5 & 09).
    Example: Sq. Ldr. S. Venkat (FDTL rest violation).
    """

    class DutyState(models.TextChoices):
        READY = "READY", "Ready"
        ON_DUTY = "ON_DUTY", "On Duty"
        REST_REQUIRED = "REST_REQUIRED", "Rest Required"
        TRAINING = "TRAINING", "Training"
        UNAVAILABLE = "UNAVAILABLE", "Unavailable"

    class QualificationStatus(models.TextChoices):
        QUALIFIED = "QUALIFIED", "Fully Qualified"
        RECURRENT_DUE = "RECURRENT_DUE", "Recurrent Check Due"
        SUSPENDED = "SUSPENDED", "FDTL / Medical Hold"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    squadron = models.ForeignKey(
        Squadron,
        on_delete=models.CASCADE,
        related_name="crew_readiness_records",
        db_index=True,
    )
    crew_ref = models.CharField(
        max_length=120,
        db_index=True,
        help_text="Fictional crew identifier or officer designation (e.g., Sq. Ldr. S. Venkat).",
    )
    first_name = models.CharField(max_length=64, blank=True, default="")
    last_name = models.CharField(max_length=64, blank=True, default="")
    crew_code = models.CharField(max_length=32, blank=True, default="CRW-DEMO-01")
    pilot_group_count = models.PositiveIntegerField(default=1)
    ground_support_count = models.PositiveIntegerField(default=4)
    duty_state = models.CharField(
        max_length=20,
        choices=DutyState.choices,
        default=DutyState.READY,
        db_index=True,
    )
    fdtl_hours_logged = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=4.00,
        help_text="Flight Duty Time Limitation hours logged in current window.",
    )
    rest_required = models.BooleanField(default=False, db_index=True)
    qualification_status = models.CharField(
        max_length=24,
        choices=QualificationStatus.choices,
        default=QualificationStatus.QUALIFIED,
        db_index=True,
    )
    report_status = models.CharField(
        max_length=20,
        default="REVIEWED",
        help_text="Workflow state: DRAFT -> SUBMITTED -> REVIEWED (Section 5.2).",
    )
    notes = models.TextField(blank=True, default="")
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="updated_crew_records",
    )
    updated_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        db_table = "core_crew_readiness"
        ordering = ["squadron", "crew_ref"]
        indexes = [
            models.Index(
                fields=["squadron", "duty_state", "rest_required"],
                name="idx_crew_sq_duty_rest",
            ),
            models.Index(fields=["updated_at"], name="idx_crew_updated_at"),
        ]
        constraints = [
            models.CheckConstraint(
                check=Q(fdtl_hours_logged__gte=0),
                name="chk_crew_fdtl_non_negative",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.crew_ref} ({self.squadron.code}) — {self.duty_state}"


class ReadinessSnapshot(models.Model):
    """
    Computed periodic or event-driven readiness summary for an Airbase or Squadron (Section 05.5).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    scope = models.CharField(max_length=64, db_index=True)
    airbase = models.ForeignKey(
        Airbase,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="readiness_snapshots",
    )
    squadron = models.ForeignKey(
        Squadron,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="readiness_snapshots",
    )
    calculated_at = models.DateTimeField(default=timezone.now, db_index=True)
    overall_score = models.FloatField(default=0.85)
    component_scores = models.JSONField(default=dict)
    source_freshness = models.CharField(max_length=32, default="LIVE")
    explanation = models.TextField(blank=True, default="")

    class Meta:
        db_table = "core_readiness_snapshot"
        ordering = ["-calculated_at"]
        indexes = [
            models.Index(fields=["scope", "calculated_at"], name="idx_snapshot_scope_time"),
        ]

    def __str__(self) -> str:
        return f"ReadinessSnapshot[{self.scope}] = {self.overall_score:.2f} @ {self.calculated_at.isoformat()}"


class Event(models.Model):
    """
    Shared idempotent Event envelope across radar simulation, maintenance, and manual actions (Section 07 & 09).
    Example: evt-demo-000104.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    event_id = models.CharField(max_length=64, unique=True, db_index=True)
    scenario_id = models.CharField(max_length=64, blank=True, default="SCENARIO-BASELINE-01", db_index=True)
    event_type = models.CharField(max_length=64, db_index=True)
    source_type = models.CharField(max_length=64, default="synthetic_sensor", db_index=True)
    source_id = models.CharField(max_length=64, db_index=True)
    occurred_at = models.DateTimeField(default=timezone.now, db_index=True)
    received_at = models.DateTimeField(default=timezone.now)
    quality = models.CharField(max_length=32, default="simulated")
    payload = models.JSONField(default=dict)
    idempotency_key = models.CharField(max_length=128, unique=True, db_index=True)

    class Meta:
        db_table = "core_event"
        ordering = ["-occurred_at"]
        indexes = [
            models.Index(fields=["event_type", "occurred_at"], name="idx_event_type_time"),
            models.Index(fields=["source_type", "source_id"], name="idx_event_source"),
        ]

    def __str__(self) -> str:
        return f"{self.event_id} [{self.event_type}] from {self.source_id}"


class Alert(models.Model):
    """
    Scoped alert state machine (Section 07 & 09):
    NEW -> ACKNOWLEDGED -> IN_REVIEW -> RESOLVED (or ESCALATED).
    """

    class Severity(models.TextChoices):
        INFO = "INFO", "Info"
        WARNING = "WARNING", "Warning"
        HIGH = "HIGH", "High"
        CRITICAL = "CRITICAL", "Critical"

    class AlertStatus(models.TextChoices):
        NEW = "NEW", "New"
        ACKNOWLEDGED = "ACKNOWLEDGED", "Acknowledged"
        IN_REVIEW = "IN_REVIEW", "In Review"
        RESOLVED = "RESOLVED", "Resolved"
        ESCALATED = "ESCALATED", "Escalated"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    event = models.ForeignKey(
        Event,
        on_delete=models.CASCADE,
        related_name="alerts",
        db_index=True,
    )
    severity = models.CharField(
        max_length=16,
        choices=Severity.choices,
        default=Severity.WARNING,
        db_index=True,
    )
    zone = models.ForeignKey(
        Zone,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="alerts",
        db_index=True,
    )
    airbase = models.ForeignKey(
        Airbase,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="alerts",
        db_index=True,
    )
    title = models.CharField(max_length=160)
    summary = models.TextField(blank=True, default="")
    status = models.CharField(
        max_length=20,
        choices=AlertStatus.choices,
        default=AlertStatus.NEW,
        db_index=True,
    )
    transition_history = models.JSONField(
        default=list,
        help_text="List of {actor, timestamp, previous_state, new_state, reason} transitions.",
    )
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    resolved_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        db_table = "core_alert"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "severity", "created_at"], name="idx_alert_status_sev_time"),
            models.Index(fields=["zone", "status"], name="idx_alert_zone_status"),
            models.Index(fields=["airbase", "status"], name="idx_alert_base_status"),
        ]

    def __str__(self) -> str:
        return f"Alert[{self.severity}:{self.status}] {self.title}"


class Notification(models.Model):
    """
    Scoped delivery and acknowledgement record for a User (Section 07 & 09).
    """

    class ChannelType(models.TextChoices):
        WEBSOCKET = "WEBSOCKET", "WebSocket Live Feed"
        INBOX = "INBOX", "Dashboard Inbox"
        SYSTEM = "SYSTEM", "System Banner"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    alert = models.ForeignKey(
        Alert,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="notifications",
        db_index=True,
    )
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
        db_index=True,
    )
    channel = models.CharField(
        max_length=20,
        choices=ChannelType.choices,
        default=ChannelType.INBOX,
    )
    message = models.TextField()
    delivered_at = models.DateTimeField(default=timezone.now, db_index=True)
    acknowledged_at = models.DateTimeField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "core_notification"
        ordering = ["-delivered_at"]
        indexes = [
            models.Index(
                fields=["recipient", "acknowledged_at", "delivered_at"],
                name="idx_notif_recip_ack_deliv",
            ),
        ]

    def __str__(self) -> str:
        ack_state = "ACK" if self.acknowledged_at else "UNREAD"
        return f"Notification({ack_state}) -> {self.recipient.username}"


class Order(models.Model):
    """
    Role-scoped operational/drill coordination order (Section 05.2, 09 & Appendix A).
    Example: ORD-0092 ("Scramble 2x Interceptors to Sector 7").
    """

    class Priority(models.TextChoices):
        LOW = "LOW", "Low"
        NORMAL = "NORMAL", "Normal"
        HIGH = "HIGH", "High"
        FLASH = "FLASH", "Flash / Immediate"

    class OrderStatus(models.TextChoices):
        PENDING = "PENDING", "Pending Acknowledgement"
        ACKNOWLEDGED = "ACKNOWLEDGED", "Acknowledged"
        IN_PROGRESS = "IN_PROGRESS", "In Execution"
        COMPLETED = "COMPLETED", "Completed"
        CANCELLED = "CANCELLED", "Cancelled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order_code = models.CharField(max_length=32, unique=True, db_index=True)
    issuer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="issued_orders",
        db_index=True,
    )
    recipient_scope = models.CharField(
        max_length=64,
        db_index=True,
        help_text="Target scope code such as AB-DEMO-01, SQ-DEMO-01, or ZONE-DEMO-A.",
    )
    target_zone = models.ForeignKey(
        Zone,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="orders",
    )
    target_airbase = models.ForeignKey(
        Airbase,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="orders",
        db_index=True,
    )
    target_squadron = models.ForeignKey(
        Squadron,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="orders",
        db_index=True,
    )
    title = models.CharField(max_length=180)
    body = models.TextField()
    priority = models.CharField(
        max_length=16,
        choices=Priority.choices,
        default=Priority.HIGH,
        db_index=True,
    )
    status = models.CharField(
        max_length=20,
        choices=OrderStatus.choices,
        default=OrderStatus.PENDING,
        db_index=True,
    )
    issued_at = models.DateTimeField(default=timezone.now, db_index=True)
    due_at = models.DateTimeField(db_index=True)
    acknowledged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="acknowledged_orders",
    )
    acknowledged_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "core_order"
        ordering = ["-issued_at"]
        indexes = [
            models.Index(
                fields=["recipient_scope", "status", "priority"],
                name="idx_order_scope_status_prio",
            ),
            models.Index(fields=["due_at"], name="idx_order_due_at"),
        ]

    def __str__(self) -> str:
        return f"{self.order_code}: {self.title} [{self.status}]"


class ImmutableAuditQuerySet(models.QuerySet):
    """Prevents bulk mutation or deletion on the append-only AuditLog table."""

    def update(self, **kwargs):
        raise PermissionDenied("AuditLog is strictly append-only; bulk updates are prohibited.")

    def delete(self):
        raise PermissionDenied("AuditLog is strictly append-only; bulk deletions are prohibited.")


class ImmutableAuditManager(models.Manager):
    def get_queryset(self):
        return ImmutableAuditQuerySet(self.model, using=self._db)


class AuditLog(models.Model):
    """
    Append-only immutable audit log capturing every security/state transition (Section 09 & 11).
    Overrides save() and delete() to prohibit editing or removal after creation.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="audit_logs",
        db_index=True,
    )
    action = models.CharField(max_length=80, db_index=True)
    object_type = models.CharField(max_length=64, db_index=True)
    object_id = models.CharField(max_length=64, db_index=True)
    before = models.JSONField(null=True, blank=True)
    after = models.JSONField(null=True, blank=True)
    source = models.CharField(max_length=64, default="web_api")
    created_at = models.DateTimeField(default=timezone.now, editable=False, db_index=True)

    objects = ImmutableAuditManager()

    class Meta:
        db_table = "core_audit_log"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["object_type", "object_id", "created_at"], name="idx_audit_obj_time"),
            models.Index(fields=["actor", "created_at"], name="idx_audit_actor_time"),
            models.Index(fields=["action", "created_at"], name="idx_audit_action_time"),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding and AuditLog.objects.filter(pk=self.pk).exists():
            raise ValidationError("AuditLog records are append-only and cannot be modified once persisted.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionDenied("AuditLog records are append-only and cannot be deleted.")

    def __str__(self) -> str:
        actor_label = self.actor.username if self.actor else "SYSTEM"
        return f"[{self.created_at.isoformat()}] {actor_label} -> {self.action} ({self.object_type}:{self.object_id})"


class AircraftSpecification(models.Model):
    """
    Technical specifications and operational flight envelope for IAF aircraft.
    Ingested from fixtures/raw_data/SIH250.csv (25 IAF aircraft).
    """

    aircraft_id = models.IntegerField(unique=True, db_index=True)
    model = models.CharField(max_length=120, db_index=True)
    aircraft_type = models.CharField(max_length=120)
    role = models.CharField(max_length=150)
    generation = models.CharField(max_length=50, blank=True, default="")
    max_speed_mach = models.FloatField(null=True, blank=True)
    max_altitude_ft = models.FloatField(null=True, blank=True)
    max_range_km = models.FloatField(null=True, blank=True)
    combat_radius_km = models.FloatField(null=True, blank=True)
    flight_endurance_hours = models.FloatField(null=True, blank=True)
    max_takeoff_weight_kg = models.FloatField(null=True, blank=True)
    empty_weight_kg = models.FloatField(null=True, blank=True)
    max_payload_kg = models.FloatField(null=True, blank=True)
    internal_fuel_capacity_kg = models.FloatField(null=True, blank=True)
    aircraft_weight_kg = models.FloatField(null=True, blank=True)
    engine_type = models.CharField(max_length=150, blank=True, default="")
    number_of_engines = models.IntegerField(default=1)
    rate_of_climb = models.CharField(max_length=50, blank=True, default="")
    rate_of_climb_ms = models.FloatField(null=True, blank=True)
    aircraft_length_m = models.FloatField(null=True, blank=True)
    aircraft_height_m = models.FloatField(null=True, blank=True)
    takeoff_runway_length_m = models.FloatField(null=True, blank=True)
    landing_runway_length_m = models.FloatField(null=True, blank=True)
    is_vtol = models.BooleanField(default=False)
    number_of_hardpoints = models.IntegerField(default=0)
    limitations = models.TextField(blank=True, default="")
    crew_capacity = models.CharField(max_length=50, blank=True, default="")
    max_passenger_capacity = models.CharField(max_length=50, blank=True, default="")
    crew_qualification = models.CharField(max_length=150, blank=True, default="")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "core_aircraft_specification"
        ordering = ["aircraft_id"]

    def __str__(self) -> str:
        return f"{self.aircraft_id}: {self.model} ({self.aircraft_type})"


class Weapon(models.Model):
    """
    Weapon systems, missiles, and precision-guided munitions.
    Ingested from fixtures/raw_data/Weapon_data.csv (69 weapons across INDIA, PAKISTAN, CHINA).
    """

    weapon_id = models.CharField(max_length=32, unique=True, db_index=True)
    name = models.CharField(max_length=255, db_index=True)
    country_deployed = models.CharField(max_length=150, db_index=True)
    category = models.CharField(max_length=150, db_index=True)
    weapon_type = models.TextField(blank=True, default="")
    guidance_type = models.TextField(blank=True, default="")
    propulsion_type = models.TextField(blank=True, default="")
    max_range_km = models.CharField(max_length=100, blank=True, default="")
    max_range_val_km = models.FloatField(null=True, blank=True)
    max_speed_mach = models.CharField(max_length=100, blank=True, default="")
    max_speed_mach_val = models.FloatField(null=True, blank=True)
    length_m = models.FloatField(null=True, blank=True)
    diameter_mm = models.FloatField(null=True, blank=True)
    warhead_type = models.TextField(blank=True, default="")
    target_type = models.TextField(blank=True, default="")
    launch_platform = models.TextField(blank=True, default="")
    weight_kg = models.FloatField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "core_weapon"
        ordering = ["weapon_id"]

    def __str__(self) -> str:
        return f"{self.weapon_id}: {self.name} [{self.country_deployed}] ({self.category})"


class AdversaryAircraft(models.Model):
    """
    Adversary combat aircraft specifications, combat radius, and radar detection ranges.
    Ingested from fixtures/raw_data/enemy aircraft.xlsx (9 aircraft across Pakistan & China).
    """

    aircraft_id = models.IntegerField(unique=True, db_index=True)
    model = models.CharField(max_length=120, db_index=True)
    country = models.CharField(max_length=80, db_index=True)
    aircraft_type = models.CharField(max_length=100)
    role = models.CharField(max_length=150)
    generation = models.CharField(max_length=50, blank=True, default="")
    max_speed_mach = models.FloatField(null=True, blank=True)
    max_altitude_ft = models.FloatField(null=True, blank=True)
    max_range_km = models.FloatField(null=True, blank=True)
    combat_radius_km = models.FloatField(null=True, blank=True)
    flight_endurance_hours = models.FloatField(null=True, blank=True)
    max_takeoff_weight_kg = models.FloatField(null=True, blank=True)
    empty_weight_kg = models.FloatField(null=True, blank=True)
    max_payload_kg = models.FloatField(null=True, blank=True)
    internal_fuel_capacity_kg = models.FloatField(null=True, blank=True)
    aircraft_weight_kg = models.FloatField(null=True, blank=True)
    engine_type = models.CharField(max_length=150, blank=True, default="")
    number_of_engines = models.IntegerField(default=1)
    rate_of_climb = models.CharField(max_length=50, blank=True, default="")
    length_m = models.FloatField(null=True, blank=True)
    height_m = models.FloatField(null=True, blank=True)
    takeoff_runway_m = models.FloatField(null=True, blank=True)
    landing_runway_m = models.FloatField(null=True, blank=True)
    number_of_hardpoints = models.IntegerField(default=0)
    radar_detection_range_km = models.FloatField(null=True, blank=True)
    weather_operating_limits = models.TextField(blank=True, default="")
    crew_capacity = models.CharField(max_length=50, blank=True, default="")
    max_passenger_capacity = models.CharField(max_length=50, blank=True, default="")
    crew_qualification = models.CharField(max_length=150, blank=True, default="")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "core_adversary_aircraft"
        ordering = ["aircraft_id"]

    def __str__(self) -> str:
        return f"{self.aircraft_id}: {self.model} [{self.country}] ({self.role})"

