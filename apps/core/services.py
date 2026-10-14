"""
Transactional Domain Services for AERO-OPS (SIH26250).
Implements Section 04, 05, 07, 10, 11 & 12:
- update_equipment_status()
- acknowledge_order_or_alert()
- override_fdtl_or_infrastructure()
- recalculate_airbase_readiness()
- broadcast_scoped_ws_event()
"""
import uuid
from decimal import Decimal
from typing import Any, Dict, List, Optional, Set, Union
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

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
)
from apps.core.permissions import (
    assert_can_acknowledge_alert,
    assert_can_acknowledge_order,
    assert_can_mutate_airbase,
    assert_can_update_crew,
    assert_can_update_equipment,
)


ALLOWED_EQUIPMENT_TRANSITIONS: Dict[str, Set[str]] = {
    Equipment.EquipmentStatus.AVAILABLE: {
        Equipment.EquipmentStatus.AIRBORNE,
        Equipment.EquipmentStatus.MAINTENANCE,
        Equipment.EquipmentStatus.UNAVAILABLE,
        Equipment.EquipmentStatus.INSPECTED,
    },
    Equipment.EquipmentStatus.AIRBORNE: {
        Equipment.EquipmentStatus.AVAILABLE,
        Equipment.EquipmentStatus.MAINTENANCE,
        Equipment.EquipmentStatus.INSPECTED,
    },
    Equipment.EquipmentStatus.MAINTENANCE: {
        Equipment.EquipmentStatus.INSPECTED,
        Equipment.EquipmentStatus.AVAILABLE,
        Equipment.EquipmentStatus.UNAVAILABLE,
    },
    Equipment.EquipmentStatus.UNAVAILABLE: {
        Equipment.EquipmentStatus.MAINTENANCE,
        Equipment.EquipmentStatus.INSPECTED,
        Equipment.EquipmentStatus.AVAILABLE,
    },
    Equipment.EquipmentStatus.INSPECTED: {
        Equipment.EquipmentStatus.AVAILABLE,
        Equipment.EquipmentStatus.MAINTENANCE,
    },
}

ALLOWED_ALERT_TRANSITIONS: Dict[str, Set[str]] = {
    Alert.AlertStatus.NEW: {
        Alert.AlertStatus.ACKNOWLEDGED,
        Alert.AlertStatus.IN_REVIEW,
        Alert.AlertStatus.ESCALATED,
    },
    Alert.AlertStatus.ACKNOWLEDGED: {
        Alert.AlertStatus.IN_REVIEW,
        Alert.AlertStatus.RESOLVED,
        Alert.AlertStatus.ESCALATED,
    },
    Alert.AlertStatus.IN_REVIEW: {
        Alert.AlertStatus.RESOLVED,
        Alert.AlertStatus.ESCALATED,
    },
    Alert.AlertStatus.ESCALATED: {
        Alert.AlertStatus.IN_REVIEW,
        Alert.AlertStatus.RESOLVED,
    },
    Alert.AlertStatus.RESOLVED: set(),
}


def broadcast_scoped_ws_event(
    groups: List[str],
    message_type: str,
    payload: Dict[str, Any],
) -> None:
    """
    Transaction-safe publication of minimal event notifications to authorised WebSocket groups (Section 07 & 10).
    Fails gracefully if Redis is temporarily unreachable in local test mode.
    """
    channel_layer = get_channel_layer()
    if not channel_layer:
        return

    envelope = {
        "type": " aero_event_message".strip(),
        "message_type": message_type,
        "timestamp": timezone.now().isoformat(),
        "data_mode": "synthetic",
        "payload": payload,
    }
    for group_name in set(groups):
        if not group_name:
            continue
        try:
            async_to_sync(channel_layer.group_send)(group_name, envelope)
        except Exception:
            # Retain durable DB state if Redis broker is offline during unit tests
            pass


def recalculate_airbase_readiness(airbase: Airbase, trigger_reason: str = "state_change") -> ReadinessSnapshot:
    """
    Recomputes deterministic readiness scores for an Airbase and refreshes advisory suggestions (Section 05.5 & 08).
    """
    equip_qs = Equipment.objects.filter(airbase=airbase)
    total_eq = max(equip_qs.count(), 1)
    avail_eq = equip_qs.filter(status=Equipment.EquipmentStatus.AVAILABLE).count()
    aircraft_score = round(avail_eq / total_eq, 3)

    crew_qs = CrewReadiness.objects.filter(squadron__airbase=airbase)
    total_crew = max(crew_qs.count(), 1)
    ready_crew = crew_qs.filter(
        duty_state__in=[CrewReadiness.DutyState.READY, CrewReadiness.DutyState.ON_DUTY],
        rest_required=False,
    ).count()
    crew_score = round(ready_crew / total_crew, 3)

    rwy_primary_ok = 1.0 if airbase.runway_primary_status == Airbase.RunwayStatus.CLEAR else 0.35
    rwy_secondary_ok = 1.0 if airbase.runway_secondary_status == Airbase.RunwayStatus.CLEAR else 0.75
    fuel_ok = 1.0 if float(airbase.fuel_reserves_mt) >= 200.0 else 0.40
    gear_ok = 1.0 if airbase.arrestor_gear_status == Airbase.ArrestorGearStatus.OPERATIONAL else 0.60
    infra_score = round((rwy_primary_ok * 0.45) + (rwy_secondary_ok * 0.15) + (fuel_ok * 0.25) + (gear_ok * 0.15), 3)

    from apps.radar_simulation.models import SensorNode

    sensors = SensorNode.objects.filter(zone=airbase.zone)
    total_s = max(sensors.count(), 1)
    live_s = sensors.filter(health_state=SensorNode.HealthState.LIVE).count()
    sensor_score = round(live_s / total_s, 3)
    freshness = "LIVE" if sensor_score == 1.0 else ("DEGRADED" if sensor_score > 0 else "OFFLINE")

    overall = round(
        (aircraft_score * 0.35) + (crew_score * 0.25) + (infra_score * 0.25) + (sensor_score * 0.15),
        3,
    )

    fdtl_violations = crew_qs.filter(rest_required=True).count()
    explanation = (
        f"{avail_eq}/{total_eq} aircraft available; "
        f"{airbase.runway_primary_label} {airbase.runway_primary_status}, "
        f"{airbase.runway_secondary_label} {airbase.runway_secondary_status}; "
        f"Fuel {airbase.fuel_reserves_mt} MT; "
        f"{fdtl_violations} crew FDTL rest lockout(s); trigger={trigger_reason}."
    )

    snapshot = ReadinessSnapshot.objects.create(
        scope=airbase.code,
        airbase=airbase,
        squadron=airbase.squadrons.first(),
        calculated_at=timezone.now(),
        overall_score=overall,
        component_scores={
            "aircraft_availability": aircraft_score,
            "crew_readiness": crew_score,
            "infrastructure_health": infra_score,
            "sensor_freshness": sensor_score,
        },
        source_freshness=freshness,
        explanation=explanation,
    )

    # Re-evaluate explainable suggestions for this airbase
    try:
        from apps.suggestion.predict import refresh_airbase_suggestions

        refresh_airbase_suggestions(airbase=airbase)
    except Exception:
        pass

    return snapshot


@transaction.atomic
def update_equipment_status(
    *,
    actor: User,
    equipment: Equipment,
    new_status: str,
    new_readiness_state: Optional[str] = None,
    notes: Optional[str] = None,
) -> Equipment:
    """
    Validates allowed equipment state transitions, records before/after snapshots in AuditLog,
    recalculates base readiness, and broadcasts via Django Channels (Section 05.5, 07, 10 & 11).
    """
    assert_can_update_equipment(actor, equipment)

    new_status_clean = str(new_status).upper().strip()
    valid_statuses = {choice[0] for choice in Equipment.EquipmentStatus.choices}
    if new_status_clean not in valid_statuses:
        raise ValidationError(f"Invalid equipment status '{new_status}'. Allowed: {sorted(valid_statuses)}")

    old_status = equipment.status
    old_readiness = equipment.readiness_state
    old_notes = equipment.notes

    if old_status != new_status_clean:
        allowed_next = ALLOWED_EQUIPMENT_TRANSITIONS.get(old_status, set())
        if new_status_clean not in allowed_next:
            raise ValidationError(
                f"Invalid state transition for {equipment.fictional_code}: {old_status} -> {new_status_clean}."
            )

    if new_readiness_state:
        readiness_clean = str(new_readiness_state).upper().strip()
        valid_readiness = {choice[0] for choice in Equipment.ReadinessState.choices}
        if readiness_clean not in valid_readiness:
            raise ValidationError(f"Invalid readiness_state '{new_readiness_state}'.")
        equipment.readiness_state = readiness_clean
    else:
        if new_status_clean == Equipment.EquipmentStatus.AVAILABLE:
            equipment.readiness_state = Equipment.ReadinessState.READY
        elif new_status_clean == Equipment.EquipmentStatus.MAINTENANCE:
            equipment.readiness_state = Equipment.ReadinessState.DEGRADED
        elif new_status_clean == Equipment.EquipmentStatus.UNAVAILABLE:
            equipment.readiness_state = Equipment.ReadinessState.GROUNDED

    equipment.status = new_status_clean
    if notes is not None:
        equipment.notes = notes
    equipment.save()

    before_snapshot = {
        "fictional_code": equipment.fictional_code,
        "status": old_status,
        "readiness_state": old_readiness,
        "notes": old_notes,
    }
    after_snapshot = {
        "fictional_code": equipment.fictional_code,
        "status": equipment.status,
        "readiness_state": equipment.readiness_state,
        "notes": equipment.notes,
    }

    AuditLog.objects.create(
        actor=actor,
        action="EQUIPMENT_STATUS_UPDATED",
        object_type="Equipment",
        object_id=equipment.fictional_code,
        before=before_snapshot,
        after=after_snapshot,
        source="service:update_equipment_status",
    )

    event_id_str = f"evt-equip-{equipment.fictional_code.lower()}-{uuid.uuid4().hex[:8]}"
    Event.objects.create(
        event_id=event_id_str,
        scenario_id="SCENARIO-BASELINE-01",
        event_type="EQUIPMENT_STATUS_CHANGED",
        source_type="equipment_service",
        source_id=equipment.fictional_code,
        occurred_at=timezone.now(),
        received_at=timezone.now(),
        quality="simulated",
        payload={
            "fictional_code": equipment.fictional_code,
            "airbase_code": equipment.airbase.code,
            "squadron_code": equipment.squadron.code if equipment.squadron else None,
            "before_status": old_status,
            "after_status": equipment.status,
            "readiness_state": equipment.readiness_state,
        },
        idempotency_key=f"idem-{event_id_str}",
    )

    snapshot = recalculate_airbase_readiness(
        equipment.airbase, trigger_reason=f"equipment:{equipment.fictional_code}->{equipment.status}"
    )

    target_groups = [f"airbase_{equipment.airbase.code}"]
    if equipment.airbase.zone:
        target_groups.append(f"zone_{equipment.airbase.zone.code}")
    if equipment.squadron:
        target_groups.append(f"squadron_{equipment.squadron.code}")

    def _publish():
        broadcast_scoped_ws_event(
            groups=target_groups,
            message_type="equipment.updated",
            payload={
                "event_id": event_id_str,
                "equipment_id": str(equipment.id),
                "fictional_code": equipment.fictional_code,
                "status": equipment.status,
                "readiness_state": equipment.readiness_state,
                "airbase_code": equipment.airbase.code,
                "summary": f"{equipment.fictional_code} status changed {old_status} -> {equipment.status}",
            },
        )
        broadcast_scoped_ws_event(
            groups=target_groups,
            message_type="readiness.updated",
            payload={
                "scope": snapshot.scope,
                "overall_score": snapshot.overall_score,
                "component_scores": snapshot.component_scores,
                "explanation": snapshot.explanation,
            },
        )

    transaction.on_commit(_publish)
    return equipment


@transaction.atomic
def acknowledge_order_or_alert(
    *,
    actor: User,
    target: Union[Order, Alert],
    new_status: Optional[str] = None,
    reason: str = "Acknowledged by authorised officer.",
) -> Union[Order, Alert]:
    """
    Transitions Order or Alert state (e.g., NEW -> ACKNOWLEDGED -> IN_REVIEW -> RESOLVED -> ESCALATED),
    records actor/timestamp/before/after in AuditLog, marks Notifications acknowledged,
    and notifies the Zonal & Airbase WebSocket groups (Section 07, 10 & 11).
    """
    now = timezone.now()

    if isinstance(target, Order):
        assert_can_acknowledge_order(actor, target)
        old_status = target.status
        desired_status = (new_status or Order.OrderStatus.ACKNOWLEDGED).upper().strip()
        valid_order_statuses = {c[0] for c in Order.OrderStatus.choices}
        if desired_status not in valid_order_statuses:
            raise ValidationError(f"Invalid Order status '{desired_status}'.")

        target.status = desired_status
        target.acknowledged_by = actor
        target.acknowledged_at = now
        target.save()

        Notification.objects.filter(
            recipient=actor, acknowledged_at__isnull=True
        ).update(acknowledged_at=now)

        AuditLog.objects.create(
            actor=actor,
            action="ORDER_ACKNOWLEDGED",
            object_type="Order",
            object_id=target.order_code,
            before={"status": old_status, "acknowledged_by": None},
            after={
                "status": target.status,
                "acknowledged_by": actor.username,
                "acknowledged_at": now.isoformat(),
                "reason": reason,
            },
            source="service:acknowledge_order_or_alert",
        )

        groups = []
        if target.target_zone:
            groups.append(f"zone_{target.target_zone.code}")
        if target.target_airbase:
            groups.append(f"airbase_{target.target_airbase.code}")
            if target.target_airbase.zone:
                groups.append(f"zone_{target.target_airbase.zone.code}")
        if target.target_squadron:
            groups.append(f"squadron_{target.target_squadron.code}")

        transaction.on_commit(
            lambda: broadcast_scoped_ws_event(
                groups=groups,
                message_type="alert.updated",
                payload={
                    "kind": "order",
                    "order_id": str(target.id),
                    "order_code": target.order_code,
                    "status": target.status,
                    "acknowledged_by": actor.display_name,
                    "acknowledged_at": now.isoformat(),
                    "summary": f"Order {target.order_code} {target.status} by {actor.display_name}",
                },
            )
        )
        return target

    elif isinstance(target, Alert):
        assert_can_acknowledge_alert(actor, target)
        old_status = target.status
        desired_status = (new_status or Alert.AlertStatus.ACKNOWLEDGED).upper().strip()
        if old_status != desired_status:
            allowed = ALLOWED_ALERT_TRANSITIONS.get(old_status, set())
            if desired_status not in allowed:
                raise ValidationError(
                    f"Invalid Alert transition: {old_status} -> {desired_status}."
                )

        history = list(target.transition_history or [])
        history.append(
            {
                "actor": actor.username,
                "actor_display": actor.display_name,
                "timestamp": now.isoformat(),
                "previous_state": old_status,
                "new_state": desired_status,
                "reason": reason,
            }
        )
        target.status = desired_status
        target.transition_history = history
        if desired_status == Alert.AlertStatus.RESOLVED:
            target.resolved_at = now
        target.save()

        Notification.objects.filter(
            alert=target, recipient=actor, acknowledged_at__isnull=True
        ).update(acknowledged_at=now)

        AuditLog.objects.create(
            actor=actor,
            action=f"ALERT_{desired_status}",
            object_type="Alert",
            object_id=str(target.id),
            before={"status": old_status},
            after={"status": target.status, "reason": reason, "timestamp": now.isoformat()},
            source="service:acknowledge_order_or_alert",
        )

        groups = []
        if target.zone:
            groups.append(f"zone_{target.zone.code}")
        if target.airbase:
            groups.append(f"airbase_{target.airbase.code}")
            if target.airbase.zone:
                groups.append(f"zone_{target.airbase.zone.code}")

        transaction.on_commit(
            lambda: broadcast_scoped_ws_event(
                groups=groups,
                message_type="alert.updated",
                payload={
                    "kind": "alert",
                    "alert_id": str(target.id),
                    "severity": target.severity,
                    "status": target.status,
                    "actor": actor.display_name,
                    "summary": f"Alert '{target.title}' transitioned {old_status} -> {target.status}",
                },
            )
        )
        return target

    raise ValidationError("Target must be an Order or Alert instance.")


@transaction.atomic
def override_fdtl_or_infrastructure(
    *,
    actor: User,
    airbase: Airbase,
    form_mode: str = "runway_status",
    crew_payload: Optional[Dict[str, Any]] = None,
    infrastructure_payload: Optional[Dict[str, Any]] = None,
    reason: str = "Commander operational override via Variant C console.",
) -> Dict[str, Any]:
    """
    Handles Airbase Commander submissions from the Variant C dashboard:
    1) "Crew Status Entry" (Runway Required, Crew Name, First Name, Last Name, Crew ID, duty_state/FDTL override)
    2) "Infrastructure Limits / Input Forms" radio actions:
       - air_unmanned / resource_allotment / runway_status / runway_request
       - Jet-A1 Fuel reserves, Runway 09/27 status, Runway 14/32 status, Arrestor Gear status.
    Enforces strict Airbase Commander RBAC, writes before/after to AuditLog, recalculates readiness,
    and broadcasts live updates (Section 04, 05.1, 11 & Variant C UI).
    """
    assert_can_mutate_airbase(actor, airbase)

    results: Dict[str, Any] = {"form_mode": form_mode, "airbase_code": airbase.code}

    if infrastructure_payload:
        before_infra = {
            "fuel_reserves_mt": float(airbase.fuel_reserves_mt),
            "runway_primary_status": airbase.runway_primary_status,
            "runway_secondary_status": airbase.runway_secondary_status,
            "arrestor_gear_status": airbase.arrestor_gear_status,
            "status": airbase.status,
        }
        if "fuel_reserves_mt" in infrastructure_payload and infrastructure_payload["fuel_reserves_mt"] is not None:
            fuel_val = Decimal(str(infrastructure_payload["fuel_reserves_mt"]))
            if fuel_val < 0:
                raise ValidationError("Jet-A1 fuel reserves cannot be negative.")
            airbase.fuel_reserves_mt = fuel_val

        if "runway_primary_status" in infrastructure_payload and infrastructure_payload["runway_primary_status"]:
            r1 = str(infrastructure_payload["runway_primary_status"]).upper().strip()
            if r1 not in {c[0] for c in Airbase.RunwayStatus.choices}:
                raise ValidationError(f"Invalid primary runway status: {r1}")
            airbase.runway_primary_status = r1

        if "runway_secondary_status" in infrastructure_payload and infrastructure_payload["runway_secondary_status"]:
            r2 = str(infrastructure_payload["runway_secondary_status"]).upper().strip()
            if r2 not in {c[0] for c in Airbase.RunwayStatus.choices}:
                raise ValidationError(f"Invalid secondary runway status: {r2}")
            airbase.runway_secondary_status = r2

        if "arrestor_gear_status" in infrastructure_payload and infrastructure_payload["arrestor_gear_status"]:
            ag = str(infrastructure_payload["arrestor_gear_status"]).upper().strip()
            if ag not in {c[0] for c in Airbase.ArrestorGearStatus.choices}:
                raise ValidationError(f"Invalid arrestor gear status: {ag}")
            airbase.arrestor_gear_status = ag

        airbase.save()
        after_infra = {
            "fuel_reserves_mt": float(airbase.fuel_reserves_mt),
            "runway_primary_status": airbase.runway_primary_status,
            "runway_secondary_status": airbase.runway_secondary_status,
            "arrestor_gear_status": airbase.arrestor_gear_status,
            "status": airbase.status,
            "form_mode": form_mode,
            "reason": reason,
        }
        AuditLog.objects.create(
            actor=actor,
            action="INFRASTRUCTURE_LIMITS_OVERRIDDEN",
            object_type="Airbase",
            object_id=airbase.code,
            before=before_infra,
            after=after_infra,
            source="service:override_fdtl_or_infrastructure",
        )
        results["infrastructure"] = after_infra

    if crew_payload:
        squadron = (
            Squadron.objects.filter(airbase=airbase, code=crew_payload.get("squadron_code")).first()
            or airbase.squadrons.first()
        )
        if not squadron:
            raise ValidationError("No squadron found under this airbase for crew status entry.")
        assert_can_update_crew(actor, squadron)

        crew_ref = crew_payload.get("crew_ref") or crew_payload.get("crew_name") or "Sq. Ldr. S. Venkat"
        crew_obj = CrewReadiness.objects.filter(squadron__airbase=airbase, crew_ref=crew_ref).first()

        before_crew = (
            {
                "crew_ref": crew_obj.crew_ref,
                "duty_state": crew_obj.duty_state,
                "fdtl_hours_logged": float(crew_obj.fdtl_hours_logged),
                "rest_required": crew_obj.rest_required,
                "qualification_status": crew_obj.qualification_status,
            }
            if crew_obj
            else None
        )

        fdtl_hours = Decimal(
            str(crew_payload.get("fdtl_hours_logged", crew_obj.fdtl_hours_logged if crew_obj else "4.00"))
        )
        rest_req = bool(
            crew_payload.get(
                "rest_required",
                True if fdtl_hours >= Decimal("12.00") else False,
            )
        )
        duty_state = str(
            crew_payload.get(
                "duty_state",
                CrewReadiness.DutyState.REST_REQUIRED if rest_req else CrewReadiness.DutyState.READY,
            )
        ).upper()

        qual_status = str(
            crew_payload.get(
                "qualification_status",
                CrewReadiness.QualificationStatus.SUSPENDED
                if rest_req
                else CrewReadiness.QualificationStatus.QUALIFIED,
            )
        ).upper()

        if crew_obj:
            crew_obj.first_name = crew_payload.get("first_name", crew_obj.first_name)
            crew_obj.last_name = crew_payload.get("last_name", crew_obj.last_name)
            crew_obj.crew_code = crew_payload.get("crew_code", crew_obj.crew_code)
            crew_obj.fdtl_hours_logged = fdtl_hours
            crew_obj.rest_required = rest_req
            crew_obj.duty_state = duty_state
            crew_obj.qualification_status = qual_status
            crew_obj.report_status = "REVIEWED"
            crew_obj.notes = crew_payload.get("notes", crew_obj.notes)
            crew_obj.updated_by = actor
            crew_obj.updated_at = timezone.now()
            crew_obj.save()
        else:
            crew_obj = CrewReadiness.objects.create(
                squadron=squadron,
                crew_ref=crew_ref,
                first_name=crew_payload.get("first_name", ""),
                last_name=crew_payload.get("last_name", ""),
                crew_code=crew_payload.get("crew_code", "CRW-Entry-01"),
                fdtl_hours_logged=fdtl_hours,
                rest_required=rest_req,
                duty_state=duty_state,
                qualification_status=qual_status,
                report_status="REVIEWED",
                notes=crew_payload.get("notes", "Entered via Airbase Commander console."),
                updated_by=actor,
                updated_at=timezone.now(),
            )

        after_crew = {
            "crew_ref": crew_obj.crew_ref,
            "first_name": crew_obj.first_name,
            "last_name": crew_obj.last_name,
            "crew_code": crew_obj.crew_code,
            "duty_state": crew_obj.duty_state,
            "fdtl_hours_logged": float(crew_obj.fdtl_hours_logged),
            "rest_required": crew_obj.rest_required,
            "qualification_status": crew_obj.qualification_status,
            "form_mode": form_mode,
        }
        AuditLog.objects.create(
            actor=actor,
            action="CREW_FDTL_STATUS_UPDATED",
            object_type="CrewReadiness",
            object_id=crew_obj.crew_ref[:64],
            before=before_crew,
            after=after_crew,
            source="service:override_fdtl_or_infrastructure",
        )
        results["crew"] = after_crew

    snapshot = recalculate_airbase_readiness(airbase, trigger_reason=f"commander_override:{form_mode}")
    results["readiness_score"] = snapshot.overall_score

    groups = [f"airbase_{airbase.code}"]
    if airbase.zone:
        groups.append(f"zone_{airbase.zone.code}")

    transaction.on_commit(
        lambda: broadcast_scoped_ws_event(
            groups=groups,
            message_type="readiness.updated",
            payload={
                "scope": airbase.code,
                "form_mode": form_mode,
                "overall_score": snapshot.overall_score,
                "component_scores": snapshot.component_scores,
                "explanation": snapshot.explanation,
            },
        )
    )
    return results
