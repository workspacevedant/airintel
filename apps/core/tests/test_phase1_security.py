"""
Phase 1 Security Automated Tests (Section 02, 04, 10, 11, 14 & Master Spec).
Tests:
1. Anonymous users redirected to /login/ from all dashboard pages.
2. /switch-role/ blocked when DEMO_MODE=False; method & account guards; audited.
3. CSRF protection strictly enforced on all mutating endpoints.
4. Rate limiting triggers (HTTP 429) on login, registration, and simulation control.
5. Registration safe default scope: PENDING, no arbitrary access; admin approval path audits changes and activates scope.
6. Generic error messages without credential leakage; demo credentials hidden when DEMO_MODE=False.
"""
import json
import uuid
from django.conf import settings
from django.core.cache import cache
from django.core.management import call_command
from django.test import Client, TestCase, override_settings

from apps.core.models import Airbase, AuditLog, DesignationChoices, Equipment, Order, RoleAssignment, User
from apps.core.permissions import get_user_scope


class Phase1SecurityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo_data", export_fixture=False)

    def setUp(self):
        cache.clear()
        self.cmdr = User.objects.get(username="cmdr_vsingh")
        self.sqldr = User.objects.get(username="sqldr_sharma")
        self.zonal = User.objects.get(username="zonal_knair")
        self.admin_user = User.objects.create_superuser(
            username="admin_sec",
            email="admin_sec@mod.gov.in",
            password="AdminSecretPassword123!",
        )

    def test_anonymous_access_redirects_to_login(self):
        """Dashboard pages must redirect unauthenticated users to /login/."""
        client = Client()
        for path in ["/", "/commander/", "/squadron/", "/zonal/", "/acommarcatosn"]:
            resp = client.get(path)
            self.assertEqual(resp.status_code, 302, f"Failed on path {path}")
            self.assertTrue(resp.url.startswith("/login/"), f"Unexpected redirect target {resp.url} for {path}")

    @override_settings(DEMO_MODE=False)
    def test_switch_role_blocked_when_demo_mode_false(self):
        """When DEMO_MODE is False, /switch-role/ returns 403 Forbidden."""
        client = Client()
        resp = client.post("/switch-role/", data={"username": "cmdr_vsingh"})
        self.assertEqual(resp.status_code, 403)

    @override_settings(DEMO_MODE=True)
    def test_switch_role_guards_and_auditing(self):
        """When DEMO_MODE is True, /switch-role/ enforces POST, valid accounts, and audits."""
        client = Client()
        # GET should be rejected (405)
        resp_get = client.get("/switch-role/")
        self.assertEqual(resp_get.status_code, 405)

        # Invalid username should be rejected (400)
        resp_bad = client.post("/switch-role/", data={"username": "hacker_account"})
        self.assertEqual(resp_bad.status_code, 400)

        # Valid demo account switches and audits
        resp_ok = client.post("/switch-role/", data={"username": "sqldr_sharma"})
        self.assertEqual(resp_ok.status_code, 302)
        log = AuditLog.objects.filter(action="DEMO_ACCOUNT_SWITCHED", object_id="sqldr_sharma").first()
        self.assertIsNotNone(log)
        self.assertEqual(log.after["switched_to"], "sqldr_sharma")

    def test_csrf_enforced_on_all_mutating_endpoints(self):
        """
        Enforce CSRF checks: all mutating endpoints must return 403 if CSRF token is missing,
        and succeed when a valid CSRF token is provided.
        """
        csrf_client = Client(enforce_csrf_checks=True)

        # 1. POST /auth/login/ without CSRF -> 403
        resp = csrf_client.post("/auth/login/", data=json.dumps({"username": "cmdr_vsingh", "password": "x"}), content_type="application/json")
        self.assertEqual(resp.status_code, 403)

        # 2. POST /auth/register/ without CSRF -> 403
        resp = csrf_client.post("/auth/register/", data=json.dumps({"username": "new_sec_user"}), content_type="application/json")
        self.assertEqual(resp.status_code, 403)

        # 3. Obtain CSRF cookie by visiting /login/
        get_resp = csrf_client.get("/login/")
        self.assertIn("csrftoken", csrf_client.cookies)
        csrf_token = csrf_client.cookies["csrftoken"].value

        # 4. Authenticate using CSRF token
        login_resp = csrf_client.post(
            "/auth/login/",
            data=json.dumps({"username": "cmdr_vsingh", "password": "AeroOps@26250"}),
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        self.assertEqual(login_resp.status_code, 200)

        # Refresh CSRF token from client cookies after login (session/CSRF rotation)
        active_csrf_token = csrf_client.cookies["csrftoken"].value

        # 5. Mutating PATCH without CSRF -> 403
        no_csrf_patch = csrf_client.patch(
            "/api/equipment/SB-512/status/",
            data=json.dumps({"status": "MAINTENANCE"}),
            content_type="application/json",
        )
        self.assertEqual(no_csrf_patch.status_code, 403)

        # 6. Mutating PATCH with CSRF -> 200
        csrf_patch = csrf_client.patch(
            "/api/equipment/SB-512/status/",
            data=json.dumps({"status": "AVAILABLE"}),
            content_type="application/json",
            HTTP_X_CSRFTOKEN=active_csrf_token,
        )
        self.assertEqual(csrf_patch.status_code, 200)

    def test_rate_limiting_on_login_and_registration(self):
        """Rate limiter must return HTTP 429 when threshold (5/min) is exceeded."""
        client = Client()
        cache.clear()

        # Login rate limiting: 5 allowed, 6th rejected with 429
        for i in range(5):
            resp = client.post(
                "/auth/login/",
                data=json.dumps({"username": "cmdr_vsingh", "password": "wrong_password"}),
                content_type="application/json",
            )
            self.assertEqual(resp.status_code, 401, f"Attempt {i+1} unexpected status")

        resp_blocked = client.post(
            "/auth/login/",
            data=json.dumps({"username": "cmdr_vsingh", "password": "wrong_password"}),
            content_type="application/json",
        )
        self.assertEqual(resp_blocked.status_code, 429)
        self.assertIn("Rate limit", resp_blocked.json()["error"])

        # Registration rate limiting: 5 allowed, 6th rejected with 429
        cache.clear()
        for i in range(5):
            resp = client.post(
                "/auth/register/",
                data=json.dumps({
                    "username": f"user_rate_{i}",
                    "email": f"rate_{i}@test.com",
                    "display_name": f"User {i}",
                    "password": "ValidPassword123!",
                    "confirm_password": "ValidPassword123!",
                    "requested_designation": "AIRBASE_COMMANDER",
                }),
                content_type="application/json",
            )
            self.assertEqual(resp.status_code, 201)

        resp_reg_blocked = client.post(
            "/auth/register/",
            data=json.dumps({
                "username": "user_rate_blocked",
                "email": "rate_blocked@test.com",
                "display_name": "User Blocked",
                "password": "ValidPassword123!",
                "confirm_password": "ValidPassword123!",
                "requested_designation": "AIRBASE_COMMANDER",
            }),
            content_type="application/json",
        )
        self.assertEqual(resp_reg_blocked.status_code, 429)

    def test_simulation_control_rate_limiting(self):
        """Simulation control rate limiter must return HTTP 429 after 20 calls/min."""
        client = Client()
        client.force_login(self.cmdr)
        cache.clear()

        for i in range(20):
            resp = client.post(
                "/api/simulation/control/",
                data=json.dumps({"action": "pause", "scenario_code": "SCENARIO-BASELINE-01", "seed": 26250}),
                content_type="application/json",
            )
            self.assertEqual(resp.status_code, 200, f"Attempt {i+1} failed with {resp.status_code}")

        # 21st call must be blocked with HTTP 429
        resp_blocked = client.post(
            "/api/simulation/control/",
            data=json.dumps({"action": "pause", "scenario_code": "SCENARIO-BASELINE-01", "seed": 26250}),
            content_type="application/json",
        )
        self.assertEqual(resp_blocked.status_code, 429)
        self.assertIn("Rate limit", resp_blocked.json()["error"])

    def test_registration_safe_default_scope_and_admin_review_approval(self):
        """
        Self-registered user receives safe default scope (PENDING, no airbase/zone).
        They can see zero operational records.
        An admin approves the assignment and assigns AB-DEMO-01, audited in AuditLog.
        The user then has scope-isolated access to AB-DEMO-01.
        """
        client = Client()
        # 1. Register new user
        reg_resp = client.post(
            "/auth/register/",
            data=json.dumps({
                "username": "officer_patel",
                "email": "patel@airintel.mil",
                "display_name": "Flt Lt Patel",
                "password": "AeroOpsPassword2026!",
                "confirm_password": "AeroOpsPassword2026!",
                "requested_designation": "AIRBASE_COMMANDER",
            }),
            content_type="application/json",
        )
        self.assertEqual(reg_resp.status_code, 201)
        data = reg_resp.json()
        self.assertEqual(data["role_assignment_status"], "PENDING")
        self.assertIsNone(data["assigned_scope"])

        new_user = User.objects.get(username="officer_patel")
        client.force_login(new_user)

        # 2. Check scope: no airbase or zone is visible
        eq_resp = client.get("/api/equipment/")
        self.assertEqual(eq_resp.status_code, 200)
        self.assertEqual(eq_resp.json()["count"], 0)

        # 3. Non-staff user cannot review role assignments
        bad_review = client.post(
            f"/api/admin/role-assignments/{new_user.role_assignments.first().id}/review/",
            data=json.dumps({"status": "ACTIVE"}),
            content_type="application/json",
        )
        self.assertEqual(bad_review.status_code, 403)

        # 4. Staff/Admin reviews and approves role assignment
        client.force_login(self.admin_user)
        assignment_id = str(new_user.role_assignments.first().id)
        review_resp = client.post(
            f"/api/admin/role-assignments/{assignment_id}/review/",
            data=json.dumps({
                "status": "ACTIVE",
                "airbase_code": "AB-DEMO-01",
                "can_control_simulation": True,
            }),
            content_type="application/json",
        )
        self.assertEqual(review_resp.status_code, 200)
        rev_data = review_resp.json()
        self.assertEqual(rev_data["after"]["status"], "ACTIVE")
        self.assertEqual(rev_data["after"]["airbase"], "AB-DEMO-01")

        # 5. Verify audit log entry
        audit_entry = AuditLog.objects.filter(
            action="ROLE_ASSIGNMENT_REVIEWED_AND_UPDATED",
            object_id=assignment_id,
        ).first()
        self.assertIsNotNone(audit_entry)
        self.assertEqual(audit_entry.before["status"], "PENDING")
        self.assertEqual(audit_entry.after["status"], "ACTIVE")
        self.assertEqual(audit_entry.after["airbase"], "AB-DEMO-01")

        # 6. User now has access to AB-DEMO-01
        client.force_login(new_user)
        eq_resp_after = client.get("/api/equipment/")
        self.assertEqual(eq_resp_after.status_code, 200)
        self.assertGreater(eq_resp_after.json()["count"], 0)

    @override_settings(DEMO_MODE=False)
    def test_demo_credentials_hidden_when_demo_mode_false(self):
        """When DEMO_MODE is False, the login page must not display demo credentials."""
        client = Client()
        resp = client.get("/login/")
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode("utf-8")
        self.assertNotIn("Seeded Demo Credentials", content)
        self.assertNotIn("AeroOps@26250", content)
