import os
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client, TestCase

User = get_user_model()


class Phase4DataDrivenUITests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from django.core.management import call_command
        call_command("seed_demo_data", export_fixture=False)

    def setUp(self):
        self.client = Client()
        self.cmdr = User.objects.get(username="cmdr_vsingh")
        self.sqldr = User.objects.get(username="sqldr_sharma")

    def test_s05_01_api_crew_endpoint_authenticated(self):
        """S05-01: /api/crew/ endpoint returns role-scoped crew roster with FDTL status."""
        self.client.force_login(self.cmdr)
        response = self.client.get("/api/crew/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("results", data)
        self.assertIn("count", data)
        self.assertGreaterEqual(data["count"], 1)

        first_crew = data["results"][0]
        self.assertIn("crew_code", first_crew)
        self.assertIn("crew_ref", first_crew)
        self.assertIn("duty_state", first_crew)
        self.assertIn("fdtl_hours_logged", first_crew)
        self.assertIn("rest_required", first_crew)

    def test_s05_02_api_crew_anonymous_blocked(self):
        """S05-02: Anonymous users are rejected from /api/crew/."""
        response = self.client.get("/api/crew/")
        self.assertIn(response.status_code, [401, 403])

    def test_s05_03_dashboard_summary_contains_full_portal_datasets(self):
        """S05-03: /api/dashboard/summary/ delivers equipment, crew, maintenance, orders, and airbases."""
        self.client.force_login(self.cmdr)
        response = self.client.get("/api/dashboard/summary/")
        self.assertEqual(response.status_code, 200)
        data = response.json()

        # Check all required top-level keys for data-driven UI
        self.assertIn("equipment", data)
        self.assertIn("crew_members", data)
        self.assertIn("maintenance_tasks", data)
        self.assertIn("orders", data)
        self.assertIn("airbases", data)
        self.assertIn("counters", data)
        self.assertIn("simulation", data)
        self.assertIn("server_time", data)

        # Assert equipment dataset richness
        self.assertGreaterEqual(len(data["equipment"]), 4)
        eq = data["equipment"][0]
        self.assertIn("code", eq)
        self.assertIn("category", eq)
        self.assertIn("status", eq)
        self.assertIn("readiness", eq)
        self.assertIn("radius_km", eq)

        # Assert airbase dataset contains runways and fuel
        self.assertGreaterEqual(len(data["airbases"]), 1)
        ab = data["airbases"][0]
        self.assertIn("runway_primary_label", ab)
        self.assertIn("runway_primary_status", ab)
        self.assertIn("fuel_reserves_mt", ab)

    def test_s06_01_leaflet_offline_vendor_files_exist(self):
        """S06-01: Leaflet assets are vendored locally in static/vendor/leaflet for offline judging."""
        base_dir = settings.BASE_DIR
        leaflet_js = os.path.join(base_dir, "static", "vendor", "leaflet", "leaflet.js")
        leaflet_css = os.path.join(base_dir, "static", "vendor", "leaflet", "leaflet.css")
        marker_icon = os.path.join(base_dir, "static", "vendor", "leaflet", "images", "marker-icon.png")

        self.assertTrue(os.path.exists(leaflet_js), "leaflet.js missing from static/vendor/leaflet")
        self.assertTrue(os.path.exists(leaflet_css), "leaflet.css missing from static/vendor/leaflet")
        self.assertTrue(os.path.exists(marker_icon), "marker-icon.png missing from static/vendor/leaflet/images")

        self.assertGreater(os.path.getsize(leaflet_js), 50000, "leaflet.js is truncated or empty")
        self.assertGreater(os.path.getsize(leaflet_css), 5000, "leaflet.css is truncated or empty")

    def test_s04_02_template_contains_dynamic_container_ids_and_clocks(self):
        """S04-02: Commander template contains all data-driven DOM container IDs and clock elements."""
        self.client.force_login(self.cmdr)
        response = self.client.get("/commander/")
        self.assertEqual(response.status_code, 200)
        html = response.content.decode("utf-8")

        # Dynamic table/list container IDs
        self.assertIn('id="active-aircraft-tbody"', html)
        self.assertIn('id="crew-roster-tbody"', html)
        self.assertIn('id="maintenance-board-tbody"', html)
        self.assertIn('id="infra-airbases-tbody"', html)
        self.assertIn('id="fleet-25-tbody"', html)
        self.assertIn('id="actions-bullet-list"', html)
        self.assertIn('id="suggestions-table-tbody"', html)

        # Clocks and Freshness indicators
        self.assertIn('id="sim-clock-display"', html)
        self.assertIn('id="wall-clock-display"', html)
        self.assertIn('id="data-freshness-pill"', html)
        self.assertIn('id="last-updated-display"', html)

        # Local vendored Leaflet paths
        self.assertIn('/static/vendor/leaflet/leaflet.css', html)
        self.assertIn('/static/vendor/leaflet/leaflet.js', html)
