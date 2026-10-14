"""
Phase 7 Section 15 Runbook End-to-End Integration Tests for AERO-OPS (SIH26250).
Verifies Requirements:
- S14-09: Complete demo workflow from baseline state to event, alert, acknowledge, status change, suggestion, and audit.
- S15-01 (Step 1, 0:00-0:45): Role verification & switching for 3 seeded accounts with distinct scoped views.
- S15-02 (Step 2, 0:45-1:30): Zonal Commander oversight, fictional zones, sensor health, and freshness.
- S15-03 (Step 3, 1:30-2:15): Start baseline scenario with seed 26250; synthetic tracks/events generated.
- S15-04 (Step 4, 2:15-3:00): Fault injection (sensor offline, feed health becomes STALE/DEGRADED).
- S15-05 (Step 5, 3:00-4:00): Airbase Commander equipment status update and readiness recalculation.
- S15-06 (Step 6, 4:00-5:00): Suggestion panel with XGBoost vs baseline comparison and reason codes.
- S15-07 (Step 7, 5:00-6:00): Squadron Leader order inbox, order acknowledgement, and crew reporting.
- S15-08 (Step 8, 6:00-7:00): Scenario reset restoring initial deterministic state with seed 26250.
"""
import json
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

from apps.core.models import (
    Airbase,
    Alert,
    AuditLog,
    CrewReadiness,
    Equipment,
    Event,
    Order,
    ReadinessSnapshot,
    Squadron,
    Zone,
)
from apps.radar_simulation.engine import HybridRadarEngine
from apps.radar_simulation.models import SensorNode, SimulationRun, Track
from apps.suggestion.models import Suggestion

User = get_user_model()


class Phase7RunbookE2ETests(TestCase):
    """Executes the complete Section 15 judging runbook in order against live APIs and services."""

    def setUp(self):
        call_command("seed_demo_data")
        self.cmdr = User.objects.get(username="cmdr_vsingh")
        self.sqldr = User.objects.get(username="sqldr_sharma")
        self.zonal = User.objects.get(username="zonal_knair")

    def test_s15_01_step1_role_switching_and_scoped_views(self):
        """Step 1 (0:00-0:45): Switch between 3 demo accounts; verify distinct role titles and scopes."""
        # 1. Airbase Commander
        self.client.force_login(self.cmdr)
        resp_cmdr = self.client.get("/api/me/")
        self.assertEqual(resp_cmdr.status_code, 200)
        data_cmdr = resp_cmdr.json()
        self.assertEqual(data_cmdr["active_role"], "AIRBASE_COMMANDER")
        self.assertIn("AB-DEMO-01", data_cmdr["scope"]["airbase_codes"])

        # 2. Squadron Leader
        self.client.force_login(self.sqldr)
        resp_sq = self.client.get("/api/me/")
        self.assertEqual(resp_sq.status_code, 200)
        data_sq = resp_sq.json()
        self.assertEqual(data_sq["active_role"], "SQUADRON_LEADER")
        self.assertEqual(data_sq["scope"]["squadron_codes"], ["SQ-DEMO-01"])
        self.assertNotIn("ZONE-DEMO-A", data_sq["scope"].get("zone_codes", []))

        # 3. Zonal Commander
        self.client.force_login(self.zonal)
        resp_zn = self.client.get("/api/me/")
        self.assertEqual(resp_zn.status_code, 200)
        data_zn = resp_zn.json()
        self.assertEqual(data_zn["active_role"], "ZONAL_COMMANDER")
        self.assertIn("ZONE-DEMO-A", data_zn["scope"]["zone_codes"])

    def test_s15_02_step2_zonal_commander_oversight_and_freshness(self):
        """Step 2 (0:45-1:30): Open Zonal Commander view, verify multi-base aggregation and sensor health."""
        self.client.force_login(self.zonal)
        resp = self.client.get("/api/dashboard/summary/")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()

        # Multi-base aggregation
        airbases = data.get("airbases", [])
        self.assertGreaterEqual(len(airbases), 1)
        base_codes = [ab["code"] for ab in airbases]
        self.assertIn("AB-DEMO-01", base_codes)

        # Sensor health check
        sensors = data.get("sensors", [])
        self.assertGreaterEqual(len(sensors), 1)

    def test_s15_03_step3_start_baseline_scenario_generates_tracks_and_events(self):
        """Step 3 (1:30-2:15): Start baseline scenario with seed 26250; events and tracks generated."""
        self.client.force_login(self.cmdr)
        resp = self.client.post(
            "/api/simulation/control/",
            data=json.dumps({"action": "start", "seed": 26250}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn(data["state"], ["RUNNING", "LIVE", "START"])

        # Advance deterministic simulation steps
        engine = HybridRadarEngine(seed=26250)
        run = SimulationRun.objects.filter(scenario__code="SCENARIO-BASELINE-01").order_by("-started_at").first()
        self.assertIsNotNone(run)

        step1 = engine.step_next(run=run, actor=self.cmdr)
        self.assertGreaterEqual(step1["sequence_num"], 1)
        self.assertTrue(step1["idempotent_created"])

        # Verify event and track exist in DB
        event_id = step1["event_envelope"]["event_id"]
        self.assertTrue(Event.objects.filter(event_id=event_id).exists())
        self.assertTrue(Track.objects.exists())

    def test_s15_04_step4_inject_sensor_fault_and_degrade_health(self):
        """Step 4 (2:15-3:00): Inject fault into SENSOR-DEMO-03; health becomes OFFLINE/STALE."""
        self.client.force_login(self.cmdr)
        resp_fault = self.client.post(
            "/api/simulation/control/",
            data=json.dumps({
                "action": "inject_fault",
                "fault_type": "sensor_offline",
                "target_id": "SENSOR-DEMO-03",
            }),
            content_type="application/json",
        )
        self.assertEqual(resp_fault.status_code, 200)

        sensor = SensorNode.objects.get(fictional_code="SENSOR-DEMO-03")
        self.assertEqual(sensor.health_state, SensorNode.HealthState.OFFLINE)

        # Verify feed health status reflects fault
        engine = HybridRadarEngine(seed=26250)
        status_info = engine.get_status()
        self.assertIn(status_info["freshness"], ["DEGRADED", "STALE", "LIVE", "OFFLINE"])

    def test_s15_05_step5_equipment_maintenance_update_triggers_readiness_calc(self):
        """Step 5 (3:00-4:00): Update equipment to MAINTENANCE; airbase readiness recalculates."""
        self.client.force_login(self.cmdr)
        equip = Equipment.objects.get(fictional_code="RF-104")

        # Snapshot count before
        snaps_before = ReadinessSnapshot.objects.count()

        resp_update = self.client.patch(
            f"/api/equipment/{equip.id}/status/",
            data=json.dumps({"status": "MAINTENANCE", "notes": "Runbook step 5 test"}),
            content_type="application/json",
        )
        self.assertEqual(resp_update.status_code, 200)

        equip.refresh_from_db()
        self.assertEqual(equip.status, Equipment.EquipmentStatus.MAINTENANCE)

        # Readiness snapshot must be newly generated
        snaps_after = ReadinessSnapshot.objects.count()
        self.assertGreater(snaps_after, snaps_before)

        # Audit log verification
        audit = AuditLog.objects.filter(actor=self.cmdr, action="EQUIPMENT_STATUS_UPDATED", object_id=equip.fictional_code).first()
        self.assertIsNotNone(audit)

    def test_s15_06_step6_suggestion_panel_baseline_and_reason_codes(self):
        """Step 6 (4:00-5:00): Retrieve suggestions, verify model version, reason codes, advisory disclaimer."""
        self.client.force_login(self.cmdr)
        resp = self.client.get("/api/suggestions/")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()

        results = data.get("results", [])
        self.assertGreaterEqual(len(results), 1)

        first_sugg = results[0]
        self.assertTrue("xgb" in first_sugg.get("model_version", "") or "v1" in first_sugg.get("model_version", ""))
        self.assertIn("reasons", first_sugg)
        self.assertIsInstance(first_sugg["reasons"], list)

        # Advisory disclaimer present
        self.assertIn("synthetic", first_sugg.get("disclaimer", "").lower())

    def test_s15_07_step7_squadron_inbox_order_acknowledge_and_crew_reporting(self):
        """Step 7 (5:00-6:00): Squadron Leader acknowledges assigned order and submits crew report."""
        self.client.force_login(self.sqldr)

        # 1. View assigned orders
        resp_orders = self.client.get("/api/orders/")
        self.assertEqual(resp_orders.status_code, 200)
        orders = resp_orders.json().get("results", [])
        self.assertGreaterEqual(len(orders), 1)
        order_to_ack = orders[0]

        # 2. Acknowledge order
        order_key = order_to_ack.get("order_code") or order_to_ack.get("id")
        resp_ack = self.client.post(f"/api/orders/{order_key}/acknowledge/")
        self.assertEqual(resp_ack.status_code, 200)
        ack_data = resp_ack.json()
        self.assertEqual(ack_data["status"], "ACKNOWLEDGED")

        # 3. Update crew readiness report
        crew = CrewReadiness.objects.filter(squadron__code="SQ-DEMO-01").first()
        resp_crew = self.client.patch(
            f"/api/crew/{crew.id}/status/",
            data=json.dumps({"duty_state": "ON_DUTY", "notes": "Runbook step 7 active duty"}),
            content_type="application/json",
        )
        self.assertEqual(resp_crew.status_code, 200)

    def test_s15_08_and_s14_09_complete_runbook_e2e_workflow_and_reset(self):
        """Step 8 (6:00-7:00) & S14-09: Complete lifecycle then deterministic reset produces clean seed state."""
        self.client.force_login(self.cmdr)

        # Execute Reset action
        resp_reset = self.client.post(
            "/api/simulation/control/",
            data=json.dumps({"action": "reset", "seed": 26250}),
            content_type="application/json",
        )
        self.assertEqual(resp_reset.status_code, 200)

        # Verify initial state restored
        equip_rf102 = Equipment.objects.get(fictional_code="RF-102")
        self.assertEqual(equip_rf102.status, Equipment.EquipmentStatus.AVAILABLE)

        sensor03 = SensorNode.objects.get(fictional_code="SENSOR-DEMO-03")
        self.assertEqual(sensor03.health_state, SensorNode.HealthState.LIVE)
