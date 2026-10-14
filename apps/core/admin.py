"""
Django Admin registration for AERO-OPS internal fixture setup convenience (Section 12).
"""
from django.contrib import admin
from django.contrib.gis.admin import GISModelAdmin

from apps.core.models import (
    Airbase,
    Alert,
    AuditLog,
    CrewReadiness,
    Equipment,
    Event,
    MaintenanceTask,
    Notification,
    Order,
    Profile,
    ReadinessSnapshot,
    RoleAssignment,
    Squadron,
    User,
    Zone,
)
from apps.radar_simulation.models import (
    Scenario,
    SensorNode,
    SensorObservation,
    SimulationRun,
    Track,
)
from apps.suggestion.models import ModelVersion, Suggestion


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ("username", "display_name", "email", "requested_designation", "active", "created_at")
    search_fields = ("username", "display_name", "email")
    list_filter = ("requested_designation", "active")


@admin.register(RoleAssignment)
class RoleAssignmentAdmin(admin.ModelAdmin):
    list_display = ("user", "role", "zone", "airbase", "squadron", "status", "can_control_simulation")
    list_filter = ("role", "status", "can_control_simulation")


@admin.register(Zone)
class ZoneAdmin(GISModelAdmin):
    list_display = ("code", "name", "is_demo", "created_at")


@admin.register(Airbase)
class AirbaseAdmin(GISModelAdmin):
    list_display = (
        "code",
        "name",
        "zone",
        "fuel_reserves_mt",
        "runway_primary_status",
        "runway_secondary_status",
        "arrestor_gear_status",
        "status",
    )


@admin.register(Squadron)
class SquadronAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "airbase", "leader_user", "assigned_aircraft_type", "status")


@admin.register(Equipment)
class EquipmentAdmin(admin.ModelAdmin):
    list_display = ("fictional_code", "category", "airbase", "squadron", "status", "readiness_state", "next_due_at")
    list_filter = ("status", "readiness_state", "category")


@admin.register(MaintenanceTask)
class MaintenanceTaskAdmin(admin.ModelAdmin):
    list_display = ("fault_code", "equipment", "severity", "status", "opened_at", "due_at")
    list_filter = ("severity", "status")


@admin.register(CrewReadiness)
class CrewReadinessAdmin(admin.ModelAdmin):
    list_display = ("crew_ref", "squadron", "duty_state", "fdtl_hours_logged", "rest_required", "qualification_status")
    list_filter = ("duty_state", "rest_required", "qualification_status")


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("order_code", "title", "recipient_scope", "priority", "status", "issued_at", "due_at")
    list_filter = ("priority", "status")


@admin.register(Alert)
class AlertAdmin(admin.ModelAdmin):
    list_display = ("title", "severity", "status", "zone", "airbase", "created_at")
    list_filter = ("severity", "status")


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "actor", "action", "object_type", "object_id", "source")
    readonly_fields = ("id", "actor", "action", "object_type", "object_id", "before", "after", "source", "created_at")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


admin.site.register(Profile)
admin.site.register(ReadinessSnapshot)
admin.site.register(Event)
admin.site.register(Notification)
admin.site.register(Scenario)
admin.site.register(SimulationRun)
admin.site.register(SensorNode, GISModelAdmin)
admin.site.register(Track, GISModelAdmin)
admin.site.register(SensorObservation, GISModelAdmin)
admin.site.register(ModelVersion)
admin.site.register(Suggestion)

from apps.core.models import AircraftSpecification, Weapon, AdversaryAircraft
admin.site.register(AircraftSpecification)
admin.site.register(Weapon)
admin.site.register(AdversaryAircraft)

