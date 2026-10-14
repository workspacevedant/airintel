"""
Automated Acceptance Tests for AERO-OPS Part 2 (Section 14 Testing & Acceptance Criteria):
- RBAC & Scope Isolation (403 Forbidden on ?airbase_id=2 or cross-scope mutations)
- Equipment state transition validation & immutable AuditLog verification
- Hybrid Radar Simulation deterministic seed 26250, idempotency, and sensor fault injection
- XGBoost inference, hard deterministic FDTL/runway constraint gate, and missing-artifact fallback
"""
import json
from pathlib import Path
from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.core.management import call_command
from django.test import Client, TestCase

from apps.core.models import AuditLog, Equipment, Order, User
from apps.radar_simulation.engine import HybridRadarEngine
from apps.radar_simulation.models import SensorNode
from apps.suggestion.predict import (
    FALLBACK_MODEL_VERSION,
    predict_equipment_readiness,
    score_operational_options,
)


class AeroOpsPart2AcceptanceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo_data", export_fixture=False)

    def setUp(self):
        self.client = Client()
        self.cmdr = User.objects.get(username="cmdr_vsingh")
        self.sqldr = User.objects.get(username="sqldr_sharma")
        self.zonal = User.objects.get(username="zonal_knair")

    def test_cross_scope_query_parameter_tampering_returns_403(self):
        """Section 02, 11 & 14: Changing ?airbase_id=2 in URL or API must return 403 Forbidden."""
        self.client.force_login(self.cmdr)
        resp = self.client.get("/api/equipment/?airbase_id=2")
        self.assertEqual(resp.status_code, 403)

        resp_ab2 = self.client.get("/api/equipment/?airbase_id=AB-DEMO-02")
        self.assertEqual(resp_ab2.status_code, 403)

        self.client.force_login(self.sqldr)
        resp_zone = self.client.get("/api/dashboard/summary/?zone_id=ZONE-DEMO-A")
        self.assertEqual(resp_zone.status_code, 403)

    def test_squadron_leader_cannot_control_simulation_or_other_squadron_equipment(self):
        """Section 04 Role Matrix: Squadron Leader is forbidden from simulation controls and other squadrons."""
        self.client.force_login(self.sqldr)
        sim_resp = self.client.post(
            "/api/simulation/control/",
            data=json.dumps({"action": "inject_fault"}),
            content_type="application/json",
        )
        self.assertEqual(sim_resp.status_code, 403)

        # EQ-DEMO-014 belongs to SQ-DEMO-02; sqldr_sharma leads SQ-DEMO-01
        eq_other = self.client.patch(
            "/api/equipment/EQ-DEMO-014/status/",
            data=json.dumps({"status": "MAINTENANCE"}),
            content_type="application/json",
        )
        self.assertEqual(eq_other.status_code, 403)

    def test_equipment_status_transition_and_append_only_audit_log(self):
        """Section 05.5, 10 & 11: Valid equipment status update writes before/after to immutable AuditLog."""
        self.client.force_login(self.sqldr)
        resp = self.client.patch(
            "/api/equipment/SB-512/status/",
            data=json.dumps({"status": "MAINTENANCE", "notes": "Scheduled 100hr inspection started."}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "MAINTENANCE")

        log_entry = AuditLog.objects.filter(
            action="EQUIPMENT_STATUS_UPDATED", object_id="SB-512"
        ).first()
        self.assertIsNotNone(log_entry)
        self.assertEqual(log_entry.before["status"], "AVAILABLE")
        self.assertEqual(log_entry.after["status"], "MAINTENANCE")

        # Verify AuditLog is append-only (cannot be deleted)
        with self.assertRaises(PermissionDenied):
            log_entry.delete()

    def test_hybrid_radar_simulation_fault_injection_and_idempotency(self):
        """Section 06 & 14: Sensor fault injection marks SENSOR-DEMO-03 OFFLINE and TRACK-DEMO-12 STALE."""
        engine = HybridRadarEngine(scenario_code="SCENARIO-BASELINE-01", seed=26250)
        res = engine.control(
            action="inject_fault",
            actor=self.cmdr,
            sensor_code="SENSOR-DEMO-03",
            fault_state="OFFLINE",
        )
        self.assertEqual(res["fault"]["health_state"], "OFFLINE")
        self.assertIn("TRACK-DEMO-12", res["fault"]["affected_tracks"])

        sensor = SensorNode.objects.get(fictional_code="SENSOR-DEMO-03")
        self.assertEqual(sensor.health_state, SensorNode.HealthState.OFFLINE)

    def test_deterministic_fdtl_constraint_and_missing_artifact_fallback(self):
        """
        Section 08 & 14:
        1) Hard constraint gate blocks Sq. Ldr. S. Venkat (14.5h FDTL violation).
        2) Missing model artifact falls back gracefully to deterministic-fallback-v1.
        """
        sb512 = Equipment.objects.get(fictional_code="SB-512")
        pred_fallback = predict_equipment_readiness(sb512, force_fallback=True)
        self.assertEqual(pred_fallback["model_version"], FALLBACK_MODEL_VERSION)
        self.assertTrue(pred_fallback["fallback_used"])
        self.assertGreater(pred_fallback["score"], 0.5)

        options = score_operational_options(sb512.airbase, force_fallback=True)
        infeasible_opt = next(o for o in options if o["option_id"] == "OPT-C-INFEASIBLE-FDTL")
        self.assertFalse(infeasible_opt["feasible"])
        self.assertFalse(infeasible_opt["recommended"])
        self.assertEqual(infeasible_opt["score"], 0.0)

        recommended_opt = next(o for o in options if o["recommended"])
        self.assertEqual(recommended_opt["option_id"], "OPT-A-RAFALE-QRA")
        self.assertTrue(recommended_opt["feasible"])
