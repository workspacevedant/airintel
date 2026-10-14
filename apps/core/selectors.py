"""
Scope-filtered query selectors for AERO-OPS (Section 04, 10 & 12).
Guarantees that every query is filtered by the authenticated user's RoleAssignment scope.
"""
from typing import Dict, Any
from django.db.models import QuerySet, Q

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
    ReadinessSnapshot,
    Squadron,
    User,
    Zone,
)
from apps.core.permissions import UserScopeContext, get_user_scope
from apps.radar_simulation.models import SensorNode, SimulationRun, Track
from apps.suggestion.models import Suggestion


def get_visible_zones(user: User) -> QuerySet[Zone]:
    ctx = get_user_scope(user)
    if ctx.is_squadron_leader and not (ctx.is_airbase_commander or ctx.is_zonal_commander):
        return Zone.objects.none()
    return Zone.objects.filter(id__in=ctx.zone_ids).order_by("code")


def get_visible_airbases(user: User) -> QuerySet[Airbase]:
    ctx = get_user_scope(user)
    return (
        Airbase.objects.filter(id__in=ctx.airbase_ids)
        .select_related("zone")
        .prefetch_related("squadrons")
        .order_by("code")
    )


def get_visible_squadrons(user: User) -> QuerySet[Squadron]:
    ctx = get_user_scope(user)
    return (
        Squadron.objects.filter(id__in=ctx.squadron_ids)
        .select_related("airbase", "leader_user")
        .order_by("code")
    )


def get_visible_equipment(user: User) -> QuerySet[Equipment]:
    ctx = get_user_scope(user)
    qs = Equipment.objects.select_related("airbase", "squadron")
    if ctx.is_zonal_commander or ctx.is_airbase_commander:
        return qs.filter(airbase_id__in=ctx.airbase_ids).order_by("fictional_code")
    if ctx.is_squadron_leader:
        return qs.filter(squadron_id__in=ctx.squadron_ids).order_by("fictional_code")
    return Equipment.objects.none()


def get_visible_maintenance_tasks(user: User) -> QuerySet[MaintenanceTask]:
    ctx = get_user_scope(user)
    qs = MaintenanceTask.objects.select_related("equipment", "equipment__airbase", "equipment__squadron", "assigned_to")
    if ctx.is_zonal_commander or ctx.is_airbase_commander:
        return qs.filter(equipment__airbase_id__in=ctx.airbase_ids).order_by("-opened_at")
    if ctx.is_squadron_leader:
        return qs.filter(equipment__squadron_id__in=ctx.squadron_ids).order_by("-opened_at")
    return MaintenanceTask.objects.none()


def get_visible_crew_readiness(user: User) -> QuerySet[CrewReadiness]:
    ctx = get_user_scope(user)
    qs = CrewReadiness.objects.select_related("squadron", "squadron__airbase", "updated_by")
    if ctx.is_zonal_commander or ctx.is_airbase_commander:
        return qs.filter(squadron__airbase_id__in=ctx.airbase_ids).order_by("squadron__code", "crew_ref")
    if ctx.is_squadron_leader:
        return qs.filter(squadron_id__in=ctx.squadron_ids).order_by("crew_ref")
    return CrewReadiness.objects.none()


def get_visible_orders(user: User) -> QuerySet[Order]:
    ctx = get_user_scope(user)
    q_filter = (
        Q(recipient_scope__in=ctx.squadron_codes)
        | Q(recipient_scope__in=ctx.airbase_codes)
        | Q(recipient_scope__in=ctx.zone_codes)
        | Q(target_squadron_id__in=ctx.squadron_ids)
        | Q(target_airbase_id__in=ctx.airbase_ids)
        | Q(target_zone_id__in=ctx.zone_ids)
        | Q(issuer=user)
    )
    if not (ctx.squadron_codes or ctx.airbase_codes or ctx.zone_codes):
        return Order.objects.none()
    return (
        Order.objects.filter(q_filter)
        .select_related("issuer", "target_airbase", "target_squadron", "target_zone", "acknowledged_by")
        .distinct()
        .order_by("-issued_at")
    )


def get_visible_alerts(user: User) -> QuerySet[Alert]:
    ctx = get_user_scope(user)
    if not (ctx.airbase_ids or ctx.zone_ids):
        return Alert.objects.none()
    q_filter = Q(airbase_id__in=ctx.airbase_ids)
    if ctx.is_airbase_commander or ctx.is_zonal_commander:
        q_filter |= Q(zone_id__in=ctx.zone_ids)
    return Alert.objects.filter(q_filter).select_related("event", "zone", "airbase").order_by("-created_at")


def get_visible_events(user: User) -> QuerySet[Event]:
    ctx = get_user_scope(user)
    if not (ctx.airbase_codes or ctx.zone_codes or ctx.squadron_codes):
        return Event.objects.none()
    if ctx.is_squadron_leader and not (ctx.is_airbase_commander or ctx.is_zonal_commander):
        # Squadron leaders only see events tied to their squadron or airbase orders/equipment
        return Event.objects.filter(
            Q(source_id__in=ctx.squadron_codes)
            | Q(source_id__in=ctx.airbase_codes)
            | Q(payload__airbase_code__in=ctx.airbase_codes)
            | Q(payload__squadron_code__in=ctx.squadron_codes)
        ).order_by("-occurred_at")
    return Event.objects.all().order_by("-occurred_at")


def get_visible_suggestions(user: User) -> QuerySet[Suggestion]:
    ctx = get_user_scope(user)
    if not (ctx.airbase_ids or ctx.squadron_ids or ctx.zone_codes):
        return Suggestion.objects.none()
    q_filter = (
        Q(scope__in=ctx.airbase_codes)
        | Q(scope__in=ctx.squadron_codes)
        | Q(scope__in=ctx.zone_codes)
        | Q(airbase_id__in=ctx.airbase_ids)
        | Q(squadron_id__in=ctx.squadron_ids)
    )
    if ctx.is_squadron_leader and not (ctx.is_airbase_commander or ctx.is_zonal_commander):
        q_filter = Q(squadron_id__in=ctx.squadron_ids) | Q(scope__in=ctx.squadron_codes)
    return (
        Suggestion.objects.filter(q_filter)
        .select_related("model_version", "airbase", "squadron", "equipment", "related_order")
        .order_by("-created_at", "-score")
    )


def get_visible_audit_logs(user: User) -> QuerySet[AuditLog]:
    ctx = get_user_scope(user)
    if ctx.is_zonal_commander or ctx.is_airbase_commander:
        return AuditLog.objects.select_related("actor").order_by("-created_at")[:100]
    if ctx.is_squadron_leader:
        return (
            AuditLog.objects.filter(Q(actor=user) | Q(object_id__in=ctx.squadron_codes))
            .select_related("actor")
            .order_by("-created_at")[:50]
        )
    return AuditLog.objects.none()


def build_dashboard_summary(user: User) -> Dict[str, Any]:
    """
    Aggregates role-scoped operational counters, infrastructure limits, crew status,
    sensor health, tracks, orders, alerts, and explainable suggestions (Section 05 & 10).
    """
    ctx = get_user_scope(user)
    airbases = list(get_visible_airbases(user))
    equipment_qs = get_visible_equipment(user)
    crew_qs = get_visible_crew_readiness(user)
    maint_qs = get_visible_maintenance_tasks(user)
    orders_qs = get_visible_orders(user)
    alerts_qs = get_visible_alerts(user)
    suggestions_qs = get_visible_suggestions(user)

    primary_airbase = airbases[0] if airbases else None
    latest_run = SimulationRun.objects.select_related("scenario").order_by("-started_at").first()

    sensors = []
    tracks = []
    if ctx.is_zonal_commander or ctx.is_airbase_commander:
        sensor_qs = SensorNode.objects.filter(
            Q(zone_id__in=ctx.zone_ids) | Q(zone__isnull=True)
        ).order_by("fictional_code")
        for s in sensor_qs:
            sensors.append(
                {
                    "fictional_code": s.fictional_code,
                    "name": s.name,
                    "health_state": s.health_state,
                    "lat": s.location.y,
                    "lon": s.location.x,
                    "coverage_radius_km": s.coverage_radius_km,
                    "last_seen_at": s.last_seen_at.isoformat(),
                }
            )
        if latest_run:
            for t in Track.objects.filter(run=latest_run).select_related("source_sensor", "zone"):
                tracks.append(
                    {
                        "fictional_track_code": t.fictional_track_code,
                        "callsign_label": t.callsign_label,
                        "state": t.state,
                        "quality": t.quality,
                        "lat": t.last_position.y,
                        "lon": t.last_position.x,
                        "bearing": t.bearing,
                        "range_km": t.range_km,
                        "altitude_m": t.altitude_m,
                        "speed_kts": t.speed_kts,
                        "source_sensor": t.source_sensor.fictional_code if t.source_sensor else None,
                        "zone_code": t.zone.code if t.zone else None,
                        "last_seen_at": t.last_seen_at.isoformat(),
                    }
                )

    latest_snapshot = (
        ReadinessSnapshot.objects.filter(airbase=primary_airbase).order_by("-calculated_at").first()
        if primary_airbase
        else None
    )

    return {
        "simulation_mode_banner": "SYNTHETIC SIMULATION MODE — NON-OPERATIONAL DEMO (SIH26250)",
        "user": {
            "username": user.username,
            "display_name": user.display_name,
            "role": ctx.primary_role,
            "roles": sorted(ctx.roles),
            "airbase_codes": sorted(ctx.airbase_codes),
            "squadron_codes": sorted(ctx.squadron_codes),
            "zone_codes": sorted(ctx.zone_codes),
            "can_control_simulation": ctx.can_control_simulation,
        },
        "counters": {
            "equipment_total": equipment_qs.count(),
            "equipment_available": equipment_qs.filter(status=Equipment.EquipmentStatus.AVAILABLE).count(),
            "equipment_maintenance": equipment_qs.filter(status=Equipment.EquipmentStatus.MAINTENANCE).count(),
            "crew_ready_groups": crew_qs.filter(
                duty_state__in=[CrewReadiness.DutyState.READY, CrewReadiness.DutyState.ON_DUTY],
                rest_required=False,
            ).count(),
            "crew_fdtl_violations": crew_qs.filter(rest_required=True).count(),
            "open_maintenance_tasks": maint_qs.exclude(
                status__in=[MaintenanceTask.TaskStatus.COMPLETED, MaintenanceTask.TaskStatus.VERIFIED]
            ).count(),
            "open_alerts": alerts_qs.exclude(status=Alert.AlertStatus.RESOLVED).count(),
            "pending_orders": orders_qs.filter(status=Order.OrderStatus.PENDING).count(),
            "pending_notifications": Notification.objects.filter(
                recipient=user, acknowledged_at__isnull=True
            ).count(),
        },
        "infrastructure_limits": (
            {
                "airbase_code": primary_airbase.code,
                "airbase_name": primary_airbase.name,
                "fuel_reserves_mt": float(primary_airbase.fuel_reserves_mt),
                "runway_primary_label": primary_airbase.runway_primary_label,
                "runway_primary_m": primary_airbase.runway_primary_m,
                "runway_primary_status": primary_airbase.runway_primary_status,
                "runway_secondary_label": primary_airbase.runway_secondary_label,
                "runway_secondary_m": primary_airbase.runway_secondary_m,
                "runway_secondary_status": primary_airbase.runway_secondary_status,
                "arrestor_gear_status": primary_airbase.arrestor_gear_status,
                "status": primary_airbase.status,
            }
            if primary_airbase
            else None
        ),
        "readiness_snapshot": (
            {
                "scope": latest_snapshot.scope,
                "overall_score": latest_snapshot.overall_score,
                "component_scores": latest_snapshot.component_scores,
                "source_freshness": latest_snapshot.source_freshness,
                "explanation": latest_snapshot.explanation,
                "calculated_at": latest_snapshot.calculated_at.isoformat(),
            }
            if latest_snapshot
            else None
        ),
        "simulation": (
            {
                "run_code": latest_run.run_code,
                "scenario_code": latest_run.scenario.code,
                "state": latest_run.state,
                "seed": latest_run.seed,
                "current_sequence": latest_run.current_sequence,
                "simulated_clock": latest_run.simulated_clock.isoformat(),
                "last_heartbeat_at": latest_run.last_heartbeat_at.isoformat(),
            }
            if latest_run
            else None
        ),
        "sensors": sensors,
        "tracks": tracks,
        "suggestions": [
            {
                "id": str(s.id),
                "suggestion_code": s.suggestion_code,
                "kind": s.kind,
                "title": s.title,
                "status": s.status,
                "score": s.score,
                "baseline_score": s.baseline_score,
                "uncertainty": s.uncertainty,
                "model_version": s.model_version.model_name if s.model_version else "deterministic-fallback-v1",
                "fallback_used": s.fallback_used,
                "reasons": s.reasons,
                "data_mode": s.data_mode,
                "created_at": s.created_at.isoformat(),
            }
            for s in suggestions_qs[:10]
        ],
    }
