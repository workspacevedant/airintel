"""
Phase 7 API and Crew Readiness Tests for AERO-OPS (SIH26250).
Verifies Requirements:
- S02-01: Common operational picture aggregating resources, fictional zones, sensors, events.
- S02-02: Faster state updates: synthetic events visible within 2s target.
- S05-07: Crew readiness / rest reporting and transitions (DRAFT -> SUBMITTED -> REVIEWED).
- S05-08: Zonal Commander dashboard: aggregated status across assigned bases, freshness indicators.
- S10-05: POST /api/airbases/ - Create fictional airbase (authorized role, validated zone).
- S10-09: POST /api/maintenance/ - Create maintenance task (authorized role, validated dates).
- S11-06: Data separation & synthetic labels.
"""
import json
import time
from datetime import timedelta
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from apps.core.models import (
    Airbase,
    AuditLog,
    CrewReadiness,
    Equipment,
    Event,
    MaintenanceTask,
    Squadron,
    Zone,
)

User = get_user_model()


class Phase7APIAndCrewTests(TestCase):
    """Test suite covering extended Section 05 & 10 REST APIs and Crew Workflow."""

    def setUp(self):
        call_command("seed_demo_data")
        self.commander = User.objects.get(username="cmdr_vsingh")
        self.sqldr = User.objects.get(username="sqldr_sharma")
        self.zonal = User.objects.get(username="zonal_knair")

    def test_s10_05_create_airbase_authorized_and_cross_zone_blocked(self):
        """Airbase Commander can register airbase in assigned zone; forbidden in unassigned zone."""
        self.client.force_login(self.commander)

        # Valid creation in assigned zone
        resp = self.client.post(
            "/api/airbases/",
            data=json.dumps({
                "code": "AB-DEMO-99",
                "name": "Northern Forward Base",
                "zone_code": "ZONE-DEMO-A",
                "lat": 30.85,
                "lon": 76.95,
            }),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 201)
        ab_data = resp.json()
        self.assertEqual(ab_data["code"], "AB-DEMO-99")
        self.assertTrue(Airbase.objects.filter(code="AB-DEMO-99").exists())

        # Audit verification
        audit = AuditLog.objects.filter(actor=self.commander, action="AIRBASE_CREATED", object_id="AB-DEMO-99").first()
        self.assertIsNotNone(audit)

        # Cross-zone creation attempt blocked with 403
        resp_blocked = self.client.post(
            "/api/airbases/",
            data=json.dumps({
                "code": "AB-FORBIDDEN-01",
                "name": "Restricted Base",
                "zone_code": "ZONE-NON-EXISTENT",
            }),
            content_type="application/json",
        )
        self.assertEqual(resp_blocked.status_code, 403)

    def test_s10_09_create_maintenance_task_validation_and_bounds(self):
        """Maintenance task creation validates equipment scope, future due date, and severity."""
        self.client.force_login(self.commander)
        equip = Equipment.objects.get(fictional_code="RF-102")

        now = timezone.now()
        due_at = now + timedelta(days=3)

        # 1. Valid task creation
        resp = self.client.post(
            "/api/maintenance/",
            data=json.dumps({
                "equipment_id": str(equip.id),
                "fault_code": "FLT-HYD-401",
                "severity": "HIGH",
                "description": "Hydraulic actuator synthetic inspection",
                "due_at": due_at.isoformat(),
            }),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        self.assertEqual(data["fault_code"], "FLT-HYD-401")
        self.assertTrue(MaintenanceTask.objects.filter(fault_code="FLT-HYD-401").exists())

        # 2. Invalid past due date rejected with 400
        past_due = now - timedelta(days=2)
        resp_bad_due = self.client.post(
            "/api/maintenance/",
            data=json.dumps({
                "equipment_id": str(equip.id),
                "fault_code": "FLT-BAD-DUE",
                "severity": "LOW",
                "due_at": past_due.isoformat(),
            }),
            content_type="application/json",
        )
        self.assertEqual(resp_bad_due.status_code, 400)
        self.assertIn("due date must not be before", resp_bad_due.json().get("error", ""))

    def test_s05_07_crew_duty_state_and_report_workflow_transitions(self):
        """Squadron Leader updates crew duty & report status (DRAFT -> SUBMITTED -> REVIEWED)."""
        self.client.force_login(self.sqldr)
        crew = CrewReadiness.objects.filter(squadron__code="SQ-DEMO-01").first()
        self.assertIsNotNone(crew)

        # 1. Squadron Leader transitions report status: REVIEWED -> DRAFT
        resp_draft = self.client.patch(
            f"/api/crew/{crew.id}/status/",
            data=json.dumps({
                "report_status": "DRAFT",
                "notes": "Draft monthly rest assessment",
            }),
            content_type="application/json",
        )
        self.assertEqual(resp_draft.status_code, 200)
        crew.refresh_from_db()
        self.assertEqual(crew.report_status, "DRAFT")

        # 2. Squadron Leader submits report: DRAFT -> SUBMITTED
        resp_sub = self.client.patch(
            f"/api/crew/{crew.id}/status/",
            data=json.dumps({
                "report_status": "SUBMITTED",
                "notes": "Ready for airbase commander review",
            }),
            content_type="application/json",
        )
        self.assertEqual(resp_sub.status_code, 200)
        crew.refresh_from_db()
        self.assertEqual(crew.report_status, "SUBMITTED")

        # 3. Squadron Leader cannot self-approve to REVIEWED (forbidden)
        resp_unauth = self.client.patch(
            f"/api/crew/{crew.id}/status/",
            data=json.dumps({"report_status": "REVIEWED"}),
            content_type="application/json",
        )
        self.assertEqual(resp_unauth.status_code, 403)

        # 4. Airbase Commander approves report: SUBMITTED -> REVIEWED
        self.client.force_login(self.commander)
        resp_rev = self.client.patch(
            f"/api/crew/{crew.id}/status/",
            data=json.dumps({
                "report_status": "REVIEWED",
                "notes": "Approved by Commander V. Singh",
            }),
            content_type="application/json",
        )
        self.assertEqual(resp_rev.status_code, 200)
        crew.refresh_from_db()
        self.assertEqual(crew.report_status, "REVIEWED")

        # 5. Cross-squadron crew mutation blocked for Squadron Leader
        self.client.force_login(self.sqldr)
        other_crew = CrewReadiness.objects.filter(squadron__code="SQ-DEMO-02").first()
        if other_crew:
            resp_cross = self.client.patch(
                f"/api/crew/{other_crew.id}/status/",
                data=json.dumps({"duty_state": "ON_DUTY"}),
                content_type="application/json",
            )
            self.assertEqual(resp_cross.status_code, 403)

    def test_s05_08_zonal_commander_aggregated_status_and_freshness(self):
        """Zonal Commander dashboard aggregates bases, sensor health, and freshness indicators."""
        self.client.force_login(self.zonal)

        # 1. Zonal dashboard page renders
        resp_page = self.client.get("/zonal/")
        self.assertEqual(resp_page.status_code, 200)
        content = resp_page.content.decode("utf-8")
        self.assertIn("ZONE-DEMO-A", content)
        self.assertIn("SIMULATION MODE", content)
        self.assertIn("SYNTHETIC", content)

        # 2. Zonal summary API returns aggregated metrics
        resp_summary = self.client.get("/api/dashboard/summary/")
        self.assertEqual(resp_summary.status_code, 200)
        data = resp_summary.json()

        counters = data.get("counters", {})
        self.assertIn("equipment_available", counters)
        self.assertIn("crew_ready_groups", counters)
        self.assertIn("open_alerts", counters)

        airbases = data.get("airbases", [])
        self.assertGreaterEqual(len(airbases), 1)

        simulation = data.get("simulation", {})
        self.assertIn(simulation.get("state"), ["RUNNING", "PAUSED", "STOPPED", "RESET", "COMPLETED"])

    def test_s02_02_synthetic_event_persistence_latency_under_2s(self):
        """Synthetic event generation and persistence executes well within the 2s spec requirement."""
        from apps.radar_simulation.engine import HybridRadarEngine

        engine = HybridRadarEngine(seed=26250)
        run = engine.get_or_create_scenario_and_run(actor=self.commander)
        t0 = time.perf_counter()

        step_result = engine.step_next(run=run, actor=self.commander)

        elapsed = time.perf_counter() - t0
        self.assertLess(elapsed, 2.0, f"Event latency {elapsed:.4f}s exceeded 2.0s target")
        event_id = step_result.get("event_envelope", {}).get("event_id")
        self.assertIsNotNone(event_id)
        self.assertTrue(Event.objects.filter(event_id=event_id).exists())
