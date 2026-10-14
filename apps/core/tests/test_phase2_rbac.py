"""
Phase 2 RBAC & Scope Isolation Automated Tests (Section 04 & Section 14).
Row-by-row verification of Section 04 Role Capability Matrix:
1. Airbase Commander capabilities & boundaries
2. Squadron Leader capabilities & boundaries (forbidden from other squadrons, zones, simulation controls)
3. Zonal Commander capabilities & boundaries (read/oversight only; direct mutations forbidden)
4. Dynamic page labels derived strictly from active RoleAssignment
"""
import json
from django.core.management import call_command
from django.test import Client, TestCase

from apps.core.models import Airbase, DesignationChoices, Equipment, Order, RoleAssignment, Squadron, User, Zone
from apps.core.permissions import get_user_scope


class Phase2RBACTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo_data", export_fixture=False)

    def setUp(self):
        self.cmdr = User.objects.get(username="cmdr_vsingh")
        self.sqldr = User.objects.get(username="sqldr_sharma")
        self.zonal = User.objects.get(username="zonal_knair")
        self.client = Client()

    def test_airbase_commander_capabilities_and_boundaries(self):
        """
        Section 04 Role Matrix — Airbase Commander:
        - View airbase-wide equipment & maintenance.
        - Allowed to override/update equipment within assigned base.
        - Allowed simulation control when flagged in RoleAssignment.
        - Blocked from cross-base query tampering (403).
        """
        self.client.force_login(self.cmdr)

        # 1. Can view equipment within AB-DEMO-01
        resp = self.client.get("/api/equipment/")
        self.assertEqual(resp.status_code, 200)
        self.assertGreater(resp.json()["count"], 0)

        # 2. Can update equipment within assigned airbase
        resp_update = self.client.patch(
            "/api/equipment/RF-102/status/",
            data=json.dumps({"status": "MAINTENANCE", "notes": "Commander phased check"}),
            content_type="application/json",
        )
        self.assertEqual(resp_update.status_code, 200)

        # 3. Can control simulation
        resp_sim = self.client.post(
            "/api/simulation/control/",
            data=json.dumps({"action": "pause"}),
            content_type="application/json",
        )
        self.assertEqual(resp_sim.status_code, 200)

        # 4. Tampering ?airbase_id=AB-DEMO-02 returns 403
        resp_tamper = self.client.get("/api/equipment/?airbase_id=AB-DEMO-02")
        self.assertEqual(resp_tamper.status_code, 403)

        # 5. Can register a new airbase in assigned zone (Section 04 & 10)
        resp_create_ab = self.client.post(
            "/api/airbases/",
            data=json.dumps({
                "code": "AB-DEMO-03",
                "name": "Forward Staging Base",
                "zone_code": "ZONE-DEMO-A",
                "lat": 30.55,
                "lon": 76.90,
            }),
            content_type="application/json",
        )
        self.assertEqual(resp_create_ab.status_code, 201)
        self.assertEqual(resp_create_ab.json()["code"], "AB-DEMO-03")

    def test_squadron_leader_capabilities_and_strict_boundaries(self):
        """
        Section 04 Role Matrix — Squadron Leader:
        - View/update assigned squadron (SQ-DEMO-01) equipment only.
        - Strictly forbidden from other squadrons (403).
        - Strictly forbidden from zone-level overview (403).
        - Strictly forbidden from simulation controls (403).
        - Strictly forbidden from creating/modifying airbases (403).
        """
        self.client.force_login(self.sqldr)

        # 1. Can update equipment in SQ-DEMO-01 (SB-512)
        resp_own = self.client.patch(
            "/api/equipment/SB-512/status/",
            data=json.dumps({"status": "MAINTENANCE"}),
            content_type="application/json",
        )
        self.assertEqual(resp_own.status_code, 200)

        # 2. Forbidden from mutating equipment in SQ-DEMO-02 (EQ-DEMO-014) -> 403
        resp_other = self.client.patch(
            "/api/equipment/EQ-DEMO-014/status/",
            data=json.dumps({"status": "MAINTENANCE"}),
            content_type="application/json",
        )
        self.assertEqual(resp_other.status_code, 403)

        # 3. Forbidden from zone summary queries -> 403
        resp_zone = self.client.get("/api/dashboard/summary/?zone_id=ZONE-DEMO-A")
        self.assertEqual(resp_zone.status_code, 403)

        # 4. Forbidden from simulation controls -> 403
        resp_sim = self.client.post(
            "/api/simulation/control/",
            data=json.dumps({"action": "start"}),
            content_type="application/json",
        )
        self.assertEqual(resp_sim.status_code, 403)

        # 5. Forbidden from creating airbases -> 403
        resp_ab = self.client.post(
            "/api/airbases/",
            data=json.dumps({"code": "AB-FORBIDDEN-01", "name": "Unauthorized Base"}),
            content_type="application/json",
        )
        self.assertEqual(resp_ab.status_code, 403)

    def test_zonal_commander_oversight_and_mutation_restrictions(self):
        """
        Section 04 Role Matrix — Zonal Commander:
        - View cross-airbase summary in assigned zone (ZONE-DEMO-A).
        - Oversight read-only: forbidden from directly mutating equipment state (403).
        - Forbidden from directly mutating airbase structure (403).
        - Forbidden from directly mutating crew readiness (403).
        - Can control simulation when demo-authorised.
        """
        self.client.force_login(self.zonal)

        # 1. Can view zone-level dashboard summary
        resp_zone = self.client.get("/api/dashboard/summary/")
        self.assertEqual(resp_zone.status_code, 200)

        # 2. Oversight only: directly mutating equipment is forbidden (403)
        resp_eq_mut = self.client.patch(
            "/api/equipment/SB-512/status/",
            data=json.dumps({"status": "AVAILABLE"}),
            content_type="application/json",
        )
        self.assertEqual(resp_eq_mut.status_code, 403)

        # 3. Directly mutating airbase structure is forbidden (403)
        resp_ab_mut = self.client.post(
            "/api/airbases/",
            data=json.dumps({"code": "AB-ZONE-99", "name": "Zone Airbase"}),
            content_type="application/json",
        )
        self.assertEqual(resp_ab_mut.status_code, 403)

        # 4. Directly mutating crew readiness is forbidden (403)
        resp_crew_mut = self.client.post(
            "/api/commander/override/",
            data=json.dumps({
                "airbase_code": "AB-DEMO-01",
                "crew_payload": {"squadron_code": "SQ-DEMO-01", "crew_ref": "Venkat", "duty_state": "READY"},
            }),
            content_type="application/json",
        )
        self.assertEqual(resp_crew_mut.status_code, 403)

        # 5. Can control simulation (demo-authorised)
        resp_sim = self.client.post(
            "/api/simulation/control/",
            data=json.dumps({"action": "pause"}),
            content_type="application/json",
        )
        self.assertEqual(resp_sim.status_code, 200)

    def test_dynamic_page_labels_derived_from_active_role_assignment(self):
        """
        Section 04 & Master Spec:
        Page labels (role, airbase, squadron, zone) must be derived dynamically from the active
        RoleAssignment, not hardcoded strings.
        """
        # 1. Airbase Commander
        ctx_cmdr = get_user_scope(self.cmdr)
        self.assertEqual(ctx_cmdr.role_label, "Airbase Commander")
        self.assertIn("AB-DEMO-01", ctx_cmdr.location_label)

        self.client.force_login(self.cmdr)
        resp_cmdr = self.client.get("/commander/")
        self.assertEqual(resp_cmdr.status_code, 200)
        self.assertEqual(resp_cmdr.context["active_role_label"], "Airbase Commander")
        self.assertIn("AB-DEMO-01", resp_cmdr.context["active_airbase_label"])

        # 2. Squadron Leader
        ctx_sqldr = get_user_scope(self.sqldr)
        self.assertEqual(ctx_sqldr.role_label, "Squadron Leader")
        self.assertIn("SQ-DEMO-01", ctx_sqldr.location_label)

        self.client.force_login(self.sqldr)
        resp_sqldr = self.client.get("/squadron/")
        self.assertEqual(resp_sqldr.status_code, 200)
        self.assertEqual(resp_sqldr.context["active_role_label"], "Squadron Leader")
        self.assertIn("SQ-DEMO-01", resp_sqldr.context["active_airbase_label"])

        # 3. Zonal Commander
        ctx_zonal = get_user_scope(self.zonal)
        self.assertEqual(ctx_zonal.role_label, "Zonal Commander")
        self.assertIn("ZONE-DEMO-A", ctx_zonal.location_label)

        self.client.force_login(self.zonal)
        resp_zonal = self.client.get("/zonal/")
        self.assertEqual(resp_zonal.status_code, 200)
        self.assertEqual(resp_zonal.context["active_role_label"], "Zonal Commander")
        self.assertIn("ZONE-DEMO-A", resp_zonal.context["active_airbase_label"])
