"""
Management command: python manage.py seed_demo_data
Populates the deterministic 7-minute SIH26250 judge demonstration dataset
and writes fixtures/demo_seed.json for reproducible resets.
"""
import uuid
from datetime import datetime, timedelta, timezone as dt_tz
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.contrib.gis.geos import Point, Polygon
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import connection, transaction

from apps.core.models import (
    Airbase,
    Alert,
    AuditLog,
    CrewReadiness,
    DesignationChoices,
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


FIXED_BASE_TIME = datetime(2026, 10, 10, 10, 30, 0, tzinfo=dt_tz.utc)


def det_uuid(namespace_str: str) -> uuid.UUID:
    """Generate a deterministic UUIDv5 from a namespace string using seed 26250."""
    return uuid.uuid5(uuid.NAMESPACE_DNS, f"sih26250.aero-ops.{namespace_str}")


class Command(BaseCommand):
    help = "Seeds the deterministic SIH26250 AERO-OPS demonstration dataset and exports fixtures/demo_seed.json."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Purge existing demo records (including append-only tables via SQL TRUNCATE) before seeding.",
        )
        parser.add_argument(
            "--export-fixture",
            action="store_true",
            default=True,
            help="Export seeded database state to fixtures/demo_seed.json.",
        )

    def _reset_database(self):
        """Cleanly truncate tables for repeatable between-judge demo resets (Section 06 & 15)."""
        with connection.cursor() as cursor:
            tables = [
                "suggestion_advisory",
                "suggestion_model_version",
                "radar_sensor_observation",
                "radar_track",
                "radar_sensor_node",
                "radar_simulation_run",
                "radar_scenario",
                "core_audit_log",
                "core_notification",
                "core_alert",
                "core_event",
                "core_order",
                "core_readiness_snapshot",
                "core_crew_readiness",
                "core_maintenance_task",
                "core_equipment",
                "core_role_assignment",
                "core_squadron",
                "core_airbase",
                "core_zone",
                "core_profile",
            ]
            existing_tables = connection.introspection.table_names()
            to_truncate = [t for t in tables if t in existing_tables]
            if to_truncate:
                cursor.execute(f'TRUNCATE TABLE {", ".join(to_truncate)} RESTART IDENTITY CASCADE;')

    @transaction.atomic
    def handle(self, *args, **options):
        if options.get("reset"):
            self.stdout.write(self.style.WARNING("Resetting existing AERO-OPS demo state..."))
            self._reset_database()

        zone_a_poly = Polygon(
            (
                (76.20, 30.00),
                (77.80, 30.00),
                (77.80, 31.40),
                (76.20, 31.40),
                (76.20, 30.00),
            ),
            srid=4326,
        )
        zone_a, _ = Zone.objects.update_or_create(
            code="ZONE-DEMO-A",
            defaults={
                "id": det_uuid("zone-demo-a"),
                "name": "Sector 7 — Northern Forward Airspace (Fictional)",
                "boundary": zone_a_poly,
                "is_demo": True,
                "created_at": FIXED_BASE_TIME - timedelta(days=30),
            },
        )

        zone_b_poly = Polygon(
            (
                (77.80, 30.00),
                (79.20, 30.00),
                (79.20, 31.40),
                (77.80, 31.40),
                (77.80, 30.00),
            ),
            srid=4326,
        )
        zone_b, _ = Zone.objects.update_or_create(
            code="ZONE-DEMO-B",
            defaults={
                "id": det_uuid("zone-demo-b"),
                "name": "Sector 8 — Eastern Surveillance Buffer (Fictional)",
                "boundary": zone_b_poly,
                "is_demo": True,
                "created_at": FIXED_BASE_TIME - timedelta(days=30),
            },
        )

        cmdr_user, _ = User.objects.update_or_create(
            username="cmdr_vsingh",
            defaults={
                "id": det_uuid("user-cmdr-vsingh"),
                "email": "v.singh@aero-ops.mod.gov.in",
                "display_name": "CMDR V. SINGH",
                "first_name": "Vikram",
                "last_name": "Singh",
                "requested_designation": DesignationChoices.AIRBASE_COMMANDER,
                "active": True,
                "is_staff": True,
                "created_at": FIXED_BASE_TIME - timedelta(days=15),
            },
        )
        cmdr_user.set_password("AeroOps@26250")
        cmdr_user.save()
        Profile.objects.update_or_create(
            user=cmdr_user,
            defaults={
                "display_name": "CMDR V. SINGH",
                "requested_designation": DesignationChoices.AIRBASE_COMMANDER,
                "service_number": "MOD-SIM-10101",
                "active": True,
                "created_at": FIXED_BASE_TIME - timedelta(days=15),
            },
        )

        sqldr_user, _ = User.objects.update_or_create(
            username="sqldr_sharma",
            defaults={
                "id": det_uuid("user-sqldr-sharma"),
                "email": "r.sharma@aero-ops.mod.gov.in",
                "display_name": "SQ. LDR. R. SHARMA",
                "first_name": "Rohan",
                "last_name": "Sharma",
                "requested_designation": DesignationChoices.SQUADRON_LEADER,
                "active": True,
                "is_staff": False,
                "created_at": FIXED_BASE_TIME - timedelta(days=15),
            },
        )
        sqldr_user.set_password("AeroOps@26250")
        sqldr_user.save()
        Profile.objects.update_or_create(
            user=sqldr_user,
            defaults={
                "display_name": "SQ. LDR. R. SHARMA",
                "requested_designation": DesignationChoices.SQUADRON_LEADER,
                "service_number": "MOD-SIM-20204",
                "active": True,
                "created_at": FIXED_BASE_TIME - timedelta(days=15),
            },
        )

        zonal_user, _ = User.objects.update_or_create(
            username="zonal_knair",
            defaults={
                "id": det_uuid("user-zonal-knair"),
                "email": "k.nair@aero-ops.mod.gov.in",
                "display_name": "AVM K. NAIR",
                "first_name": "Karthik",
                "last_name": "Nair",
                "requested_designation": DesignationChoices.ZONAL_COMMANDER,
                "active": True,
                "is_staff": True,
                "created_at": FIXED_BASE_TIME - timedelta(days=15),
            },
        )
        zonal_user.set_password("AeroOps@26250")
        zonal_user.save()
        Profile.objects.update_or_create(
            user=zonal_user,
            defaults={
                "display_name": "AVM K. NAIR",
                "requested_designation": DesignationChoices.ZONAL_COMMANDER,
                "service_number": "MOD-SIM-00309",
                "active": True,
                "created_at": FIXED_BASE_TIME - timedelta(days=15),
            },
        )

        airbase_01, _ = Airbase.objects.update_or_create(
            code="AB-DEMO-01",
            defaults={
                "id": det_uuid("airbase-ab-demo-01"),
                "name": "Avalon Forward Base",
                "zone": zone_a,
                "location": Point(76.8200, 30.3800, srid=4326),
                "runway_primary_label": "Runway 09/27",
                "runway_primary_m": 3200,
                "runway_primary_status": Airbase.RunwayStatus.CLEAR,
                "runway_secondary_label": "Runway 14/32",
                "runway_secondary_m": 2800,
                "runway_secondary_status": Airbase.RunwayStatus.MAINT,
                "arrestor_gear_status": Airbase.ArrestorGearStatus.OPERATIONAL,
                "fuel_reserves_mt": Decimal("450.00"),
                "status": Airbase.AirbaseStatus.OPERATIONAL,
                "is_demo": True,
                "created_by": cmdr_user,
                "created_at": FIXED_BASE_TIME - timedelta(days=14),
            },
        )

        Airbase.objects.update_or_create(
            code="AB-DEMO-02",
            defaults={
                "id": det_uuid("airbase-ab-demo-02"),
                "name": "Vanguard Logistics Station",
                "zone": zone_a,
                "location": Point(77.3500, 30.8500, srid=4326),
                "runway_primary_label": "Runway 04/22",
                "runway_primary_m": 3000,
                "runway_primary_status": Airbase.RunwayStatus.CLEAR,
                "runway_secondary_label": "Runway 11/29",
                "runway_secondary_m": 2500,
                "runway_secondary_status": Airbase.RunwayStatus.CLEAR,
                "arrestor_gear_status": Airbase.ArrestorGearStatus.OPERATIONAL,
                "fuel_reserves_mt": Decimal("620.00"),
                "status": Airbase.AirbaseStatus.OPERATIONAL,
                "is_demo": True,
                "created_by": zonal_user,
                "created_at": FIXED_BASE_TIME - timedelta(days=14),
            },
        )

        squadron_01, _ = Squadron.objects.update_or_create(
            code="SQ-DEMO-01",
            defaults={
                "id": det_uuid("squadron-sq-demo-01"),
                "name": "No. 17 Squadron (Golden Arrows — Fictional Demo)",
                "airbase": airbase_01,
                "leader_user": sqldr_user,
                "assigned_aircraft_type": "Dassault Rafale / Su-30MKI",
                "status": Squadron.SquadronStatus.ACTIVE,
                "created_at": FIXED_BASE_TIME - timedelta(days=14),
            },
        )

        squadron_02, _ = Squadron.objects.update_or_create(
            code="SQ-DEMO-02",
            defaults={
                "id": det_uuid("squadron-sq-demo-02"),
                "name": "No. 45 Surveillance Squadron (Fictional Demo)",
                "airbase": airbase_01,
                "leader_user": None,
                "assigned_aircraft_type": "Su-30MKI",
                "status": Squadron.SquadronStatus.ACTIVE,
                "created_at": FIXED_BASE_TIME - timedelta(days=14),
            },
        )

        RoleAssignment.objects.update_or_create(
            user=cmdr_user,
            role=DesignationChoices.AIRBASE_COMMANDER,
            defaults={
                "id": det_uuid("role-cmdr-vsingh"),
                "airbase": airbase_01,
                "squadron": None,
                "zone": zone_a,
                "status": RoleAssignment.AssignmentStatus.ACTIVE,
                "can_control_simulation": True,
                "granted_by": zonal_user,
                "created_at": FIXED_BASE_TIME - timedelta(days=14),
            },
        )

        RoleAssignment.objects.update_or_create(
            user=sqldr_user,
            role=DesignationChoices.SQUADRON_LEADER,
            defaults={
                "id": det_uuid("role-sqldr-sharma"),
                "airbase": airbase_01,
                "squadron": squadron_01,
                "zone": None,
                "status": RoleAssignment.AssignmentStatus.ACTIVE,
                "can_control_simulation": False,
                "granted_by": cmdr_user,
                "created_at": FIXED_BASE_TIME - timedelta(days=14),
            },
        )

        RoleAssignment.objects.update_or_create(
            user=zonal_user,
            role=DesignationChoices.ZONAL_COMMANDER,
            defaults={
                "id": det_uuid("role-zonal-knair"),
                "airbase": None,
                "squadron": None,
                "zone": zone_a,
                "status": RoleAssignment.AssignmentStatus.ACTIVE,
                "can_control_simulation": True,
                "granted_by": zonal_user,
                "created_at": FIXED_BASE_TIME - timedelta(days=14),
            },
        )

        eq_rf102, _ = Equipment.objects.update_or_create(
            fictional_code="RF-102",
            defaults={
                "id": det_uuid("equip-rf-102"),
                "category": Equipment.EquipmentCategory.DASSAULT_RAFALE,
                "squadron": squadron_01,
                "airbase": airbase_01,
                "payload_config": "QRA Interceptor / Patrol Pod",
                "weight_delta_kg": 1250,
                "combat_radius_km": 1850,
                "status": Equipment.EquipmentStatus.AVAILABLE,
                "readiness_state": Equipment.ReadinessState.READY,
                "last_service_at": FIXED_BASE_TIME - timedelta(days=6),
                "next_due_at": FIXED_BASE_TIME + timedelta(days=24),
                "past_fault_count": 0,
                "usage_band": "LOW",
                "age_band": "1-3_YEARS",
                "notes": "Primary readiness interceptor pair #1 on QRA pad.",
            },
        )

        Equipment.objects.update_or_create(
            fictional_code="RF-104",
            defaults={
                "id": det_uuid("equip-rf-104"),
                "category": Equipment.EquipmentCategory.DASSAULT_RAFALE,
                "squadron": squadron_01,
                "airbase": airbase_01,
                "payload_config": "QRA Interceptor / Patrol Pod",
                "weight_delta_kg": 1250,
                "combat_radius_km": 1850,
                "status": Equipment.EquipmentStatus.AVAILABLE,
                "readiness_state": Equipment.ReadinessState.READY,
                "last_service_at": FIXED_BASE_TIME - timedelta(days=12),
                "next_due_at": FIXED_BASE_TIME + timedelta(days=18),
                "past_fault_count": 1,
                "usage_band": "MEDIUM",
                "age_band": "1-3_YEARS",
                "notes": "Primary readiness interceptor pair #2 on QRA pad.",
            },
        )

        eq_sb512, _ = Equipment.objects.update_or_create(
            fictional_code="SB-512",
            defaults={
                "id": det_uuid("equip-sb-512"),
                "category": Equipment.EquipmentCategory.SU_30MKI,
                "squadron": squadron_01,
                "airbase": airbase_01,
                "payload_config": "Extended Endurance Surveillance Config",
                "weight_delta_kg": 2100,
                "combat_radius_km": 1500,
                "status": Equipment.EquipmentStatus.AVAILABLE,
                "readiness_state": Equipment.ReadinessState.READY,
                "last_service_at": FIXED_BASE_TIME - timedelta(days=21),
                "next_due_at": FIXED_BASE_TIME + timedelta(days=3),
                "past_fault_count": 3,
                "usage_band": "HIGH",
                "age_band": "5-8_YEARS",
                "notes": "Scheduled 100-hr phase inspection approaching in 72 hours.",
            },
        )

        eq_sb514, _ = Equipment.objects.update_or_create(
            fictional_code="SB-514",
            defaults={
                "id": det_uuid("equip-sb-514"),
                "category": Equipment.EquipmentCategory.SU_30MKI,
                "squadron": squadron_01,
                "airbase": airbase_01,
                "payload_config": "Standard Patrol Config",
                "weight_delta_kg": 1800,
                "combat_radius_km": 1500,
                "status": Equipment.EquipmentStatus.MAINTENANCE,
                "readiness_state": Equipment.ReadinessState.DEGRADED,
                "last_service_at": FIXED_BASE_TIME - timedelta(days=28),
                "next_due_at": FIXED_BASE_TIME + timedelta(days=1),
                "past_fault_count": 5,
                "usage_band": "HIGH",
                "age_band": "5-8_YEARS",
                "notes": "In hangar bay 2 for hydraulic actuator pressure check.",
            },
        )

        Equipment.objects.update_or_create(
            fictional_code="EQ-DEMO-014",
            defaults={
                "id": det_uuid("equip-eq-demo-014"),
                "category": Equipment.EquipmentCategory.TEJAS_MK1A,
                "squadron": squadron_02,
                "airbase": airbase_01,
                "payload_config": "Light Reconnaissance Config",
                "weight_delta_kg": 850,
                "combat_radius_km": 1200,
                "status": Equipment.EquipmentStatus.AVAILABLE,
                "readiness_state": Equipment.ReadinessState.READY,
                "last_service_at": FIXED_BASE_TIME - timedelta(days=5),
                "next_due_at": FIXED_BASE_TIME + timedelta(days=25),
                "past_fault_count": 0,
                "usage_band": "LOW",
                "age_band": "1-3_YEARS",
                "notes": "Appendix A canonical reference equipment item.",
            },
        )

        MaintenanceTask.objects.update_or_create(
            id=det_uuid("maint-sb514-hyd"),
            defaults={
                "equipment": eq_sb514,
                "opened_at": FIXED_BASE_TIME - timedelta(hours=6),
                "due_at": FIXED_BASE_TIME + timedelta(hours=8),
                "completed_at": None,
                "severity": MaintenanceTask.Severity.HIGH,
                "fault_code": "FLT-HYD-402",
                "description": "Port aileron hydraulic servo pressure fluctuation during pre-flight test.",
                "notes": "Replacement seal kit staged; technician team assigned.",
                "status": MaintenanceTask.TaskStatus.IN_PROGRESS,
                "assigned_to": sqldr_user,
            },
        )

        MaintenanceTask.objects.update_or_create(
            id=det_uuid("maint-sb512-sched"),
            defaults={
                "equipment": eq_sb512,
                "opened_at": FIXED_BASE_TIME - timedelta(hours=2),
                "due_at": FIXED_BASE_TIME + timedelta(days=3),
                "completed_at": None,
                "severity": MaintenanceTask.Severity.MEDIUM,
                "fault_code": "SCH-100HR-09",
                "description": "Scheduled 100-hour avionics cooling & radar wave-guide calibration.",
                "notes": "Advisory flagged by XGBoost readiness model (score 0.73).",
                "status": MaintenanceTask.TaskStatus.OPEN,
                "assigned_to": sqldr_user,
            },
        )

        CrewReadiness.objects.update_or_create(
            id=det_uuid("crew-venkat-fdtl"),
            defaults={
                "squadron": squadron_01,
                "crew_ref": "Sq. Ldr. S. Venkat",
                "first_name": "Siddharth",
                "last_name": "Venkat",
                "crew_code": "PLT-17-004",
                "pilot_group_count": 1,
                "ground_support_count": 4,
                "duty_state": CrewReadiness.DutyState.REST_REQUIRED,
                "fdtl_hours_logged": Decimal("14.50"),
                "rest_required": True,
                "qualification_status": CrewReadiness.QualificationStatus.SUSPENDED,
                "report_status": "REVIEWED",
                "notes": "ACTIVE FDTL VIOLATION: Logged 14.5h duty in 24h window (limit 12.0h). Mandatory 10h rest enforced by deterministic rule.",
                "updated_by": sqldr_user,
                "updated_at": FIXED_BASE_TIME - timedelta(minutes=25),
            },
        )

        CrewReadiness.objects.update_or_create(
            id=det_uuid("crew-alpha-flight"),
            defaults={
                "squadron": squadron_01,
                "crew_ref": "Flt. Lt. A. Deshmukh & Wg. Cdr. M. Prasad (QRA Pair Alpha)",
                "first_name": "Arjun",
                "last_name": "Deshmukh",
                "crew_code": "PLT-17-001",
                "pilot_group_count": 2,
                "ground_support_count": 8,
                "duty_state": CrewReadiness.DutyState.READY,
                "fdtl_hours_logged": Decimal("3.50"),
                "rest_required": False,
                "qualification_status": CrewReadiness.QualificationStatus.QUALIFIED,
                "report_status": "REVIEWED",
                "notes": "Cleared for immediate Sector 7 QRA dispatch (assigned to RF-102 & RF-104).",
                "updated_by": sqldr_user,
                "updated_at": FIXED_BASE_TIME - timedelta(minutes=15),
            },
        )

        CrewReadiness.objects.update_or_create(
            id=det_uuid("crew-bravo-flight"),
            defaults={
                "squadron": squadron_01,
                "crew_ref": "Flt. Lt. K. Gill (Standby Lead)",
                "first_name": "Kabir",
                "last_name": "Gill",
                "crew_code": "PLT-17-002",
                "pilot_group_count": 1,
                "ground_support_count": 4,
                "duty_state": CrewReadiness.DutyState.ON_DUTY,
                "fdtl_hours_logged": Decimal("6.00"),
                "rest_required": False,
                "qualification_status": CrewReadiness.QualificationStatus.QUALIFIED,
                "report_status": "REVIEWED",
                "notes": "Qualified on Su-30MKI (SB-512).",
                "updated_by": sqldr_user,
                "updated_at": FIXED_BASE_TIME - timedelta(minutes=10),
            },
        )

        ReadinessSnapshot.objects.update_or_create(
            id=det_uuid("snapshot-ab-demo-01"),
            defaults={
                "scope": "AB-DEMO-01",
                "airbase": airbase_01,
                "squadron": squadron_01,
                "calculated_at": FIXED_BASE_TIME,
                "overall_score": 0.82,
                "component_scores": {
                    "aircraft_availability": 0.80,
                    "crew_readiness": 0.75,
                    "infrastructure_health": 0.88,
                    "sensor_freshness": 1.00,
                },
                "source_freshness": "LIVE",
                "explanation": "4/5 aircraft available; Runway 09/27 CLEAR, Runway 14/32 in MAINT; 1 crew member (Sq. Ldr. S. Venkat) under mandatory FDTL rest.",
            },
        )

        order_0092, _ = Order.objects.update_or_create(
            order_code="ORD-0092",
            defaults={
                "id": det_uuid("order-ord-0092"),
                "issuer": zonal_user,
                "recipient_scope": "SQ-DEMO-01",
                "target_zone": zone_a,
                "target_airbase": airbase_01,
                "target_squadron": squadron_01,
                "title": "Scramble 2x Interceptors to Sector 7",
                "body": (
                    "SYNTHETIC DRILL DIRECTIVE ORD-0092: Dispatch 2x ready interceptor aircraft from "
                    "Avalon Forward Base (AB-DEMO-01 / SQ-DEMO-01) to Sector 7 (ZONE-DEMO-A) for "
                    "visual identification and airspace surveillance of synthetic track H-01 J-20. "
                    "Use Runway 09/27 (CLEAR) and verify FDTL compliance prior to tasking."
                ),
                "priority": Order.Priority.FLASH,
                "status": Order.OrderStatus.PENDING,
                "issued_at": FIXED_BASE_TIME - timedelta(minutes=5),
                "due_at": FIXED_BASE_TIME + timedelta(minutes=15),
            },
        )

        Order.objects.update_or_create(
            order_code="ORD-DEMO-0007",
            defaults={
                "id": det_uuid("order-ord-demo-0007"),
                "issuer": cmdr_user,
                "recipient_scope": "SQ-DEMO-01",
                "target_zone": zone_a,
                "target_airbase": airbase_01,
                "target_squadron": squadron_01,
                "title": "Submit Shift Equipment & Crew FDTL Verification Report",
                "body": "Confirm squadron equipment readiness state and verify mandatory rest lockouts for all flight crews.",
                "priority": Order.Priority.HIGH,
                "status": Order.OrderStatus.PENDING,
                "issued_at": FIXED_BASE_TIME - timedelta(minutes=20),
                "due_at": FIXED_BASE_TIME + timedelta(minutes=40),
            },
        )

        scenario_01, _ = Scenario.objects.update_or_create(
            code="SCENARIO-BASELINE-01",
            defaults={
                "id": det_uuid("scenario-baseline-01"),
                "name": "Sector 7 Dynamic Readiness & Sensor Degradation Drill",
                "version": "1.0",
                "seed": 26250,
                "status": Scenario.ScenarioStatus.ACTIVE,
                "configuration": {
                    "seed": 26250,
                    "tick_interval_seconds": 2,
                    "zone_code": "ZONE-DEMO-A",
                    "airbase_code": "AB-DEMO-01",
                    "scripted_events": [
                        {"seq": 1, "type": "TRACK_UPDATED", "track": "H-01 J-20", "sensor": "SENSOR-DEMO-01"},
                        {"seq": 2, "type": "TRACK_UPDATED", "track": "TRACK-DEMO-12", "sensor": "SENSOR-DEMO-03"},
                        {"seq": 3, "type": "SENSOR_DEGRADED", "sensor": "SENSOR-DEMO-03", "health": "STALE"},
                        {"seq": 4, "type": "COORDINATION_REQUIRED", "order_code": "ORD-0092"},
                    ],
                },
                "is_demo": True,
                "created_at": FIXED_BASE_TIME - timedelta(days=7),
            },
        )

        sim_run, _ = SimulationRun.objects.update_or_create(
            run_code="RUN-DEMO-26250-01",
            defaults={
                "id": det_uuid("simrun-26250-01"),
                "scenario": scenario_01,
                "started_at": FIXED_BASE_TIME - timedelta(minutes=10),
                "simulated_clock": FIXED_BASE_TIME,
                "state": SimulationRun.RunState.RUNNING,
                "speed": 1.0,
                "seed": 26250,
                "current_sequence": 2,
                "last_heartbeat_at": FIXED_BASE_TIME,
                "initiated_by": cmdr_user,
            },
        )

        sensor_01, _ = SensorNode.objects.update_or_create(
            fictional_code="SENSOR-DEMO-01",
            defaults={
                "id": det_uuid("sensor-demo-01"),
                "scenario": scenario_01,
                "name": "Avalon High-Level Synthetic Array Alpha",
                "zone": zone_a,
                "location": Point(76.7500, 30.6500, srid=4326),
                "coverage_radius_km": 250.0,
                "health_state": SensorNode.HealthState.LIVE,
                "last_seen_at": FIXED_BASE_TIME,
                "is_synthetic": True,
            },
        )

        SensorNode.objects.update_or_create(
            fictional_code="SENSOR-DEMO-02",
            defaults={
                "id": det_uuid("sensor-demo-02"),
                "scenario": scenario_01,
                "name": "Ridgecrest Gap-Filler Synthetic Node Bravo",
                "zone": zone_a,
                "location": Point(77.2500, 31.0500, srid=4326),
                "coverage_radius_km": 180.0,
                "health_state": SensorNode.HealthState.LIVE,
                "last_seen_at": FIXED_BASE_TIME,
                "is_synthetic": True,
            },
        )

        sensor_03, _ = SensorNode.objects.update_or_create(
            fictional_code="SENSOR-DEMO-03",
            defaults={
                "id": det_uuid("sensor-demo-03"),
                "scenario": scenario_01,
                "name": "Eastern Sector Synthetic Relay Charlie",
                "zone": zone_b,
                "location": Point(78.1000, 30.7500, srid=4326),
                "coverage_radius_km": 220.0,
                "health_state": SensorNode.HealthState.LIVE,
                "last_seen_at": FIXED_BASE_TIME,
                "is_synthetic": True,
            },
        )

        track_h01, _ = Track.objects.update_or_create(
            run=sim_run,
            fictional_track_code="H-01 J-20",
            defaults={
                "id": det_uuid("track-h01-j20"),
                "callsign_label": "H-01 J-20 (Synthetic High-Altitude Profile)",
                "state": Track.TrackState.UNDER_REVIEW,
                "last_position": Point(77.1200, 31.1800, srid=4326),
                "bearing": 215.0,
                "range_km": 94.5,
                "altitude_m": 11200.0,
                "speed_kts": 540.0,
                "quality": Track.TrackQuality.SIMULATED,
                "source_sensor": sensor_01,
                "zone": zone_a,
                "last_seen_at": FIXED_BASE_TIME,
            },
        )

        track_demo12, _ = Track.objects.update_or_create(
            run=sim_run,
            fictional_track_code="TRACK-DEMO-12",
            defaults={
                "id": det_uuid("track-demo-12"),
                "callsign_label": "TRACK-DEMO-12 (Synthetic Border Buffer Track)",
                "state": Track.TrackState.UNDER_REVIEW,
                "last_position": Point(78.0500, 30.8800, srid=4326),
                "bearing": 260.0,
                "range_km": 68.0,
                "altitude_m": 7800.0,
                "speed_kts": 430.0,
                "quality": Track.TrackQuality.SIMULATED,
                "source_sensor": sensor_03,
                "zone": zone_b,
                "last_seen_at": FIXED_BASE_TIME,
            },
        )

        obs_1_key = "obs-26250-run01-seq001"
        if not SensorObservation.objects.filter(idempotency_key=obs_1_key).exists():
            SensorObservation.objects.create(
                id=det_uuid(obs_1_key),
                run=sim_run,
                sensor=sensor_01,
                track=track_h01,
                sequence_num=1,
                observed_at=FIXED_BASE_TIME - timedelta(seconds=30),
                position=Point(77.1200, 31.1800, srid=4326),
                bearing=215.0,
                range_km=94.5,
                quality="simulated",
                payload={
                    "fictional_track_code": "H-01 J-20",
                    "zone_ref": "ZONE-DEMO-A",
                    "altitude_m": 11200.0,
                },
                idempotency_key=obs_1_key,
            )

        obs_2_key = "obs-26250-run01-seq002"
        if not SensorObservation.objects.filter(idempotency_key=obs_2_key).exists():
            SensorObservation.objects.create(
                id=det_uuid(obs_2_key),
                run=sim_run,
                sensor=sensor_03,
                track=track_demo12,
                sequence_num=2,
                observed_at=FIXED_BASE_TIME,
                position=Point(78.0500, 30.8800, srid=4326),
                bearing=260.0,
                range_km=68.0,
                quality="simulated",
                payload={
                    "fictional_track_code": "TRACK-DEMO-12",
                    "zone_ref": "ZONE-DEMO-B",
                    "state": "under_review",
                },
                idempotency_key=obs_2_key,
            )

        Event.objects.update_or_create(
            event_id="evt-demo-000104",
            defaults={
                "id": det_uuid("evt-demo-000104"),
                "scenario_id": "SCENARIO-BASELINE-01",
                "event_type": "TRACK_UPDATED",
                "source_type": "synthetic_sensor",
                "source_id": "SENSOR-DEMO-03",
                "occurred_at": FIXED_BASE_TIME,
                "received_at": FIXED_BASE_TIME,
                "quality": "simulated",
                "payload": {
                    "track_ref": "TRACK-DEMO-12",
                    "zone_ref": "ZONE-DEMO-B",
                    "state": "under_review",
                },
                "idempotency_key": "idem-evt-demo-000104",
            },
        )

        evt_105, _ = Event.objects.update_or_create(
            event_id="evt-demo-000105",
            defaults={
                "id": det_uuid("evt-demo-000105"),
                "scenario_id": "SCENARIO-BASELINE-01",
                "event_type": "HIGH_PRIORITY_DRILL",
                "source_type": "synthetic_sensor",
                "source_id": "SENSOR-DEMO-01",
                "occurred_at": FIXED_BASE_TIME,
                "received_at": FIXED_BASE_TIME,
                "quality": "simulated",
                "payload": {
                    "track_ref": "H-01 J-20",
                    "zone_ref": "ZONE-DEMO-A",
                    "order_code": "ORD-0092",
                    "state": "coordination_required",
                },
                "idempotency_key": "idem-evt-demo-000105",
            },
        )

        alert_01, _ = Alert.objects.update_or_create(
            id=det_uuid("alert-sector7-scramble"),
            defaults={
                "event": evt_105,
                "severity": Alert.Severity.HIGH,
                "zone": zone_a,
                "airbase": airbase_01,
                "title": "Sector 7 Track H-01 J-20 — Urgent Dispatch Coordination (ORD-0092)",
                "summary": "Synthetic track H-01 J-20 detected at 94.5 km bearing 215°. Zonal Order ORD-0092 awaits acknowledgement.",
                "status": Alert.AlertStatus.NEW,
                "transition_history": [
                    {
                        "actor": "SYSTEM_SIMULATOR",
                        "timestamp": FIXED_BASE_TIME.isoformat(),
                        "previous_state": None,
                        "new_state": "NEW",
                        "reason": "Generated from fixed-seed scenario SCENARIO-BASELINE-01 (seed 26250).",
                    }
                ],
                "created_at": FIXED_BASE_TIME,
            },
        )

        Notification.objects.update_or_create(
            id=det_uuid("notif-cmdr-alert01"),
            defaults={
                "alert": alert_01,
                "recipient": cmdr_user,
                "channel": Notification.ChannelType.INBOX,
                "message": "Urgent dispatch coordination to Ministry of Defence: Review ORD-0092 options for AB-DEMO-01.",
                "delivered_at": FIXED_BASE_TIME,
                "acknowledged_at": None,
            },
        )

        Notification.objects.update_or_create(
            id=det_uuid("notif-sqldr-alert01"),
            defaults={
                "alert": alert_01,
                "recipient": sqldr_user,
                "channel": Notification.ChannelType.INBOX,
                "message": "Flash Order ORD-0092 in Squadron Inbox: Scramble 2x Interceptors to Sector 7.",
                "delivered_at": FIXED_BASE_TIME,
                "acknowledged_at": None,
            },
        )

        model_readiness, _ = ModelVersion.objects.update_or_create(
            model_name="readiness-xgb-v1",
            version="1.0.0",
            defaults={
                "id": det_uuid("model-readiness-xgb-v1"),
                "task_type": ModelVersion.ModelTask.READINESS_PREDICTION,
                "artifact_path": str(Path(settings.ML_ARTIFACTS_DIR) / "readiness_xgb_v1.json"),
                "artifact_checksum": "sha256:9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
                "feature_schema": [
                    "days_since_last_service",
                    "days_until_next_due",
                    "past_fault_count",
                    "open_maintenance_tasks",
                    "usage_band_encoded",
                    "age_band_encoded",
                ],
                "metrics": {
                    "roc_auc": 0.894,
                    "precision": 0.842,
                    "recall": 0.815,
                    "brier_calibration": 0.091,
                    "baseline_logistic_roc_auc": 0.762,
                },
                "decision_threshold": 0.50,
                "training_seed": 26250,
                "training_data_version": "synth-readiness-v1-seed26250",
                "is_active": True,
                "trained_at": FIXED_BASE_TIME - timedelta(days=2),
            },
        )

        model_scorer, _ = ModelVersion.objects.update_or_create(
            model_name="option-scorer-xgb-v1",
            version="1.0.0",
            defaults={
                "id": det_uuid("model-option-scorer-xgb-v1"),
                "task_type": ModelVersion.ModelTask.OPTION_SCORING,
                "artifact_path": str(Path(settings.ML_ARTIFACTS_DIR) / "option_scorer_xgb_v1.json"),
                "artifact_checksum": "sha256:4b227777d4dd1fc61c6f884f48641d02b4d121d3fd328cb08b5531fcacdabf8a",
                "feature_schema": [
                    "aircraft_ready_ratio",
                    "crew_fdtl_compliant",
                    "runway_primary_clear",
                    "fuel_reserves_adequacy",
                    "maintenance_conflict_score",
                    "data_freshness_score",
                ],
                "metrics": {
                    "ndcg_at_3": 0.932,
                    "ranking_agreement_vs_baseline": 0.885,
                },
                "decision_threshold": 0.60,
                "training_seed": 26250,
                "training_data_version": "synth-options-v1-seed26250",
                "is_active": True,
                "trained_at": FIXED_BASE_TIME - timedelta(days=2),
            },
        )

        Suggestion.objects.update_or_create(
            suggestion_code="sugg-demo-001",
            defaults={
                "id": det_uuid("sugg-demo-001"),
                "kind": Suggestion.SuggestionKind.READINESS_WARNING,
                "scope": "AB-DEMO-01",
                "airbase": airbase_01,
                "squadron": squadron_01,
                "equipment": eq_sb512,
                "related_order": None,
                "model_version": model_readiness,
                "title": "7-Day Unavailability Risk Flagged for Su-30MKI (SB-512)",
                "input_snapshot": {
                    "fictional_code": "SB-512",
                    "days_since_last_service": 21,
                    "days_until_next_due": 3,
                    "past_fault_count": 3,
                    "open_maintenance_tasks": 1,
                    "usage_band": "HIGH",
                },
                "score": 0.73,
                "baseline_score": 0.68,
                "uncertainty": 0.06,
                "data_freshness_label": "LIVE (<15s)",
                "fallback_used": False,
                "reasons": [
                    "scheduled maintenance is approaching (due in 3 days)",
                    "source status was updated recently with 3 historical fault records",
                    "high synthetic usage band increases 7-day maintenance probability",
                ],
                "data_mode": "synthetic",
                "status": Suggestion.SuggestionStatus.ADVISORY,
                "created_at": FIXED_BASE_TIME + timedelta(minutes=2),
            },
        )

        Suggestion.objects.update_or_create(
            suggestion_code="sugg-demo-002",
            defaults={
                "id": det_uuid("sugg-demo-002"),
                "kind": Suggestion.SuggestionKind.OPTION_SCORE,
                "scope": "AB-DEMO-01",
                "airbase": airbase_01,
                "squadron": squadron_01,
                "equipment": eq_rf102,
                "related_order": order_0092,
                "model_version": model_scorer,
                "title": "Option A (Recommended): Task RF-102 + RF-104 via Runway 09/27 with QRA Pair Alpha",
                "input_snapshot": {
                    "order_code": "ORD-0092",
                    "candidate_aircraft": ["RF-102", "RF-104"],
                    "excluded_aircraft": ["SB-514 (MAINTENANCE)", "SB-512 (72h inspection window)"],
                    "excluded_crew": ["Sq. Ldr. S. Venkat (FDTL 14.5h violation — hard constraint blocked)"],
                    "selected_crew": "Flt. Lt. A. Deshmukh & Wg. Cdr. M. Prasad (3.5h FDTL logged)",
                    "runway": "Runway 09/27 (CLEAR)",
                    "fuel_reserves_mt": 450.0,
                },
                "score": 0.91,
                "baseline_score": 0.88,
                "uncertainty": 0.04,
                "data_freshness_label": "LIVE (<10s)",
                "fallback_used": False,
                "reasons": [
                    "RF-102 and RF-104 have 18+ days before next scheduled maintenance",
                    "Deterministic constraint engine excluded Sq. Ldr. S. Venkat (14.5h FDTL logged; rest required)",
                    "Runway 09/27 is CLEAR (3200m) and Arrestor Gear is OPERATIONAL; Runway 14/32 bypassed due to MAINT",
                    "Avalon Forward Base Jet-A1 Fuel reserves at 450 MT exceed reserve threshold",
                ],
                "data_mode": "synthetic",
                "status": Suggestion.SuggestionStatus.ADVISORY,
                "created_at": FIXED_BASE_TIME + timedelta(minutes=2),
            },
        )

        audit_seed_id = det_uuid("audit-initial-seed")
        if not AuditLog.objects.filter(pk=audit_seed_id).exists():
            AuditLog.objects.create(
                id=audit_seed_id,
                actor=zonal_user,
                action="DEMO_SEED_INITIALIZED",
                object_type="Scenario",
                object_id="SCENARIO-BASELINE-01",
                before=None,
                after={
                    "seed": 26250,
                    "airbase": "AB-DEMO-01",
                    "fuel_reserves_mt": 450.0,
                    "runway_09_27": "CLEAR",
                    "runway_14_32": "MAINT",
                    "pending_order": "ORD-0092",
                },
                source="management_command:seed_demo_data",
                created_at=FIXED_BASE_TIME,
            )

        if options.get("export_fixture", True):
            fixtures_dir = Path(settings.BASE_DIR) / "fixtures"
            fixtures_dir.mkdir(parents=True, exist_ok=True)
            fixture_path = fixtures_dir / "demo_seed.json"
            with open(fixture_path, "w", encoding="utf-8") as f:
                call_command(
                    "dumpdata",
                    "core",
                    "radar_simulation",
                    "suggestion",
                    indent=2,
                    stdout=f,
                )
            self.stdout.write(
                self.style.SUCCESS(f"Exported deterministic fixture to {fixture_path}")
            )

        self.stdout.write(
            self.style.SUCCESS(
                "Successfully seeded AERO-OPS (SIH26250) demo dataset."
            )
        )
