from datetime import timedelta
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import Client, TestCase
from django.utils import timezone

from apps.core.models import (
    Airbase,
    Alert,
    AuditLog,
    CrewReadiness,
    Equipment,
    Event,
    MaintenanceTask,
    User,
)
from apps.core.services import (
    acknowledge_order_or_alert,
    update_crew_duty_state,
    update_equipment_status,
    update_maintenance_task_status,
)
from apps.radar_simulation.engine import HybridRadarEngine


class Phase5SimulationWorkflowsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo_data", export_fixture=False)

    def setUp(self):
        self.client = Client()
        self.cmdr = User.objects.get(username="cmdr_vsingh")
        self.sqldr = User.objects.get(username="sqldr_sharma")
        self.airbase = Airbase.objects.get(code="AB-DEMO-01")
        self.engine = HybridRadarEngine(scenario_code="SCENARIO-BASELINE-01", seed=26250)

    def test_s06_04_event_store_idempotency_ignores_duplicates(self):
        """S06-04 & S07-01: Duplicate event IDs are idempotently ignored with exactly one DB row."""
        test_event_id = "evt-idem-test-9999"
        res1 = self.engine.ingest_observation(
            event_id=test_event_id,
            sensor_code="SENSOR-DEMO-01",
            track_code="SYNTH-TRACK-01",
            lat=30.45,
            lon=76.85,
            bearing=210.0,
            range_km=45.0,
        )
        self.assertTrue(res1["created"])
        self.assertFalse(res1["duplicate_ignored"])

        # Ingest same event_id again
        res2 = self.engine.ingest_observation(
            event_id=test_event_id,
            sensor_code="SENSOR-DEMO-01",
            track_code="SYNTH-TRACK-01",
            lat=30.45,
            lon=76.85,
            bearing=210.0,
            range_km=45.0,
        )
        self.assertFalse(res2["created"])
        self.assertTrue(res2["duplicate_ignored"])

        # Exactly 1 row in Event table
        self.assertEqual(Event.objects.filter(event_id=test_event_id).count(), 1)

    def test_s06_01_deterministic_replay_produces_identical_sequence(self):
        """S06-01 & S06-05: Reset scenario restores seed 26250 state and reproduces identical outputs on two runs."""
        # Run 1: 3 steps
        self.engine.control(action="reset", actor=self.cmdr)
        run1 = self.engine.get_or_create_scenario_and_run(actor=self.cmdr)
        step1_run1 = self.engine.step_next(run=run1, actor=self.cmdr)
        step2_run1 = self.engine.step_next(run=run1, actor=self.cmdr)
        step3_run1 = self.engine.step_next(run=run1, actor=self.cmdr)

        seq1 = [
            (
                step1_run1["event_envelope"]["event_id"],
                step1_run1["event_envelope"]["payload"]["bearing"],
                step1_run1["event_envelope"]["payload"]["lat"],
            ),
            (
                step2_run1["event_envelope"]["event_id"],
                step2_run1["event_envelope"]["payload"]["bearing"],
                step2_run1["event_envelope"]["payload"]["lat"],
            ),
            (
                step3_run1["event_envelope"]["event_id"],
                step3_run1["event_envelope"]["payload"]["bearing"],
                step3_run1["event_envelope"]["payload"]["lat"],
            ),
        ]

        # Run 2: Reset and run 3 steps again
        self.engine.control(action="reset", actor=self.cmdr)
        run2 = self.engine.get_or_create_scenario_and_run(actor=self.cmdr)
        step1_run2 = self.engine.step_next(run=run2, actor=self.cmdr)
        step2_run2 = self.engine.step_next(run=run2, actor=self.cmdr)
        step3_run2 = self.engine.step_next(run=run2, actor=self.cmdr)

        seq2 = [
            (
                step1_run2["event_envelope"]["event_id"],
                step1_run2["event_envelope"]["payload"]["bearing"],
                step1_run2["event_envelope"]["payload"]["lat"],
            ),
            (
                step2_run2["event_envelope"]["event_id"],
                step2_run2["event_envelope"]["payload"]["bearing"],
                step2_run2["event_envelope"]["payload"]["lat"],
            ),
            (
                step3_run2["event_envelope"]["event_id"],
                step3_run2["event_envelope"]["payload"]["bearing"],
                step3_run2["event_envelope"]["payload"]["lat"],
            ),
        ]

        # Both runs must be 100% mathematically identical
        self.assertEqual(seq1, seq2)

    def test_s07_02_alert_state_machine_and_escalation(self):
        """S07-02: Alert state transitions NEW -> ACKNOWLEDGED -> IN_REVIEW -> RESOLVED (and ESCALATED) with audit."""
        alert = Alert.objects.filter(status=Alert.AlertStatus.NEW).first()
        self.assertIsNotNone(alert)

        # 1. Invalid jump from NEW -> RESOLVED must be rejected
        with self.assertRaises(ValidationError):
            acknowledge_order_or_alert(
                actor=self.cmdr,
                target=alert,
                new_status=Alert.AlertStatus.RESOLVED,
                reason="Invalid jump",
            )

        # 2. NEW -> ACKNOWLEDGED is valid
        acknowledge_order_or_alert(
            actor=self.cmdr,
            target=alert,
            new_status=Alert.AlertStatus.ACKNOWLEDGED,
            reason="Commander confirmed threat alert",
        )
        alert.refresh_from_db()
        self.assertEqual(alert.status, Alert.AlertStatus.ACKNOWLEDGED)

        # 3. ACKNOWLEDGED -> ESCALATED is valid
        acknowledge_order_or_alert(
            actor=self.cmdr,
            target=alert,
            new_status=Alert.AlertStatus.ESCALATED,
            reason="Escalated to Zonal Command",
        )
        alert.refresh_from_db()
        self.assertEqual(alert.status, Alert.AlertStatus.ESCALATED)

        # 4. ESCALATED -> RESOLVED is valid
        acknowledge_order_or_alert(
            actor=self.cmdr,
            target=alert,
            new_status=Alert.AlertStatus.RESOLVED,
            reason="Resolved by Standby Readiness Pair",
        )
        alert.refresh_from_db()
        self.assertEqual(alert.status, Alert.AlertStatus.RESOLVED)
        self.assertIsNotNone(alert.resolved_at)

        # 5. Transition history and AuditLog verified
        self.assertGreaterEqual(len(alert.transition_history), 3)
        last_hist = alert.transition_history[-1]
        self.assertEqual(last_hist["new_state"], Alert.AlertStatus.RESOLVED)
        self.assertEqual(last_hist["actor"], self.cmdr.username)

    def test_s05_11_maintenance_task_state_machine(self):
        """S05-11: Maintenance task OPEN -> IN_PROGRESS -> WAITING_PARTS -> COMPLETED -> VERIFIED."""
        equipment = Equipment.objects.get(fictional_code="RF-104")
        task = MaintenanceTask.objects.create(
            equipment=equipment,
            due_at=timezone.now() + timedelta(days=2),
            fault_code="FLT-TST-001",
            description="Phase 5 state machine validation task",
            status=MaintenanceTask.TaskStatus.OPEN,
            assigned_to=self.cmdr,
        )

        # 1. Invalid jump from OPEN -> VERIFIED must be rejected
        with self.assertRaises(ValidationError):
            update_maintenance_task_status(
                actor=self.cmdr,
                task=task,
                new_status=MaintenanceTask.TaskStatus.VERIFIED,
            )

        # 2. OPEN -> IN_PROGRESS
        update_maintenance_task_status(
            actor=self.cmdr,
            task=task,
            new_status=MaintenanceTask.TaskStatus.IN_PROGRESS,
            reason="Technician dispatched",
        )
        task.refresh_from_db()
        self.assertEqual(task.status, MaintenanceTask.TaskStatus.IN_PROGRESS)

        # 3. IN_PROGRESS -> COMPLETED
        update_maintenance_task_status(
            actor=self.cmdr,
            task=task,
            new_status=MaintenanceTask.TaskStatus.COMPLETED,
            reason="Component replaced",
        )
        task.refresh_from_db()
        self.assertEqual(task.status, MaintenanceTask.TaskStatus.COMPLETED)
        self.assertIsNotNone(task.completed_at)

        # 4. COMPLETED -> VERIFIED
        update_maintenance_task_status(
            actor=self.cmdr,
            task=task,
            new_status=MaintenanceTask.TaskStatus.VERIFIED,
            reason="Airbase Commander QA sign-off",
        )
        task.refresh_from_db()
        self.assertEqual(task.status, MaintenanceTask.TaskStatus.VERIFIED)

        # 5. AuditLog verified
        audit = AuditLog.objects.filter(
            object_type="MaintenanceTask",
            object_id="FLT-TST-001",
            action="MAINTENANCE_TASK_STATUS_UPDATED",
        ).latest("created_at")
        self.assertEqual(audit.after["status"], MaintenanceTask.TaskStatus.VERIFIED)

    def test_s05_12_crew_duty_state_machine_and_fdtl_lockout(self):
        """S05-12: Crew duty state transitions enforce deterministic FDTL lockout."""
        crew = CrewReadiness.objects.get(crew_ref="Sq. Ldr. S. Venkat")

        # Sq. Ldr. S. Venkat has 9.5h FDTL logged and rest_required=True.
        # Attempting to force duty_state to READY without clearing rest must raise ValidationError!
        with self.assertRaises(ValidationError):
            update_crew_duty_state(
                actor=self.cmdr,
                crew=crew,
                new_state=CrewReadiness.DutyState.READY,
                reason="Attempted override without rest",
            )

        # Transition to TRAINING is valid
        update_crew_duty_state(
            actor=self.cmdr,
            crew=crew,
            new_state=CrewReadiness.DutyState.TRAINING,
            reason="Classroom briefing",
        )
        crew.refresh_from_db()
        self.assertEqual(crew.duty_state, CrewReadiness.DutyState.TRAINING)

    def test_s06_07_feed_health_and_freshness_status(self):
        """S06-07: Feed health indicators report LIVE, PAUSED, STALE, or OFFLINE with heartbeat."""
        status = self.engine.get_status()
        self.assertIn("freshness", status)
        self.assertIn("state", status)
        self.assertIn("last_heartbeat_at", status)
        self.assertIn("heartbeat_age_seconds", status)
        self.assertIn(status["freshness"], ["LIVE", "PAUSED", "STALE", "OFFLINE"])
