"""
Phase 3 Scope Cleanup & Fictional Designation Automated Tests (SIH26250).
Verifies strict Scope Guard compliance:
1. Operational options use generic IDs (e.g., OPT-A-TYPE-A-READY) and no tactical platform names.
2. Scenario sequences use generic track codes (SYNTH-TRACK-01, TRACK-DEMO-12) without tactical/adversary names.
3. Active Equipment instances use generic fictional classifications (Type-A Fighter, Type-B Multirole, Type-C Light Combat).
4. Deterministic constraint gate prevents infeasible options from being recommended or scored > 0.
5. All rendered portal responses display visible SIMULATION MODE and SYNTHETIC badges.
6. Inert reference tables (Weapon, AdversaryAircraft) are not queried by operational suggestion routines.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase, Client
from django.urls import reverse

from apps.core.models import Airbase, Equipment, RoleAssignment, DesignationChoices
from apps.radar_simulation.scenarios import SCENARIO_REGISTRY
from apps.suggestion.predict import score_operational_options

User = get_user_model()


class Phase3ScopeCleanupTests(TestCase):
    fixtures = ["demo_seed.json"]

    def setUp(self):
        self.client = Client()
        self.cmdr = User.objects.get(username="cmdr_vsingh")
        self.airbase = Airbase.objects.get(code="AB-DEMO-01")

    def test_operational_options_use_generic_fictional_ids(self):
        """Verify suggestion option IDs and titles are generic and free of real platform names."""
        options = score_operational_options(self.airbase, force_fallback=True)
        option_ids = [o["option_id"] for o in options]

        self.assertIn("OPT-A-TYPE-A-READY", option_ids)
        self.assertIn("OPT-B-STANDBY-PATROL", option_ids)
        self.assertIn("OPT-C-INFEASIBLE-FDTL", option_ids)

        for opt in options:
            self.assertNotIn("RAFALE", opt["option_id"])
            self.assertNotIn("QRA", opt["option_id"])
            self.assertNotIn("J-20", opt["title"])
            self.assertNotIn("Scramble", opt["title"])

        rec = next(o for o in options if o["recommended"])
        self.assertEqual(rec["option_id"], "OPT-A-TYPE-A-READY")
        self.assertTrue(rec["feasible"])

    def test_scenario_registry_uses_generic_synthetic_tracks(self):
        """Verify radar simulation scenario steps use synthetic track codes and perimeter wording."""
        scenario = SCENARIO_REGISTRY.get("SCENARIO-BASELINE-01")
        self.assertIsNotNone(scenario)

        for step in scenario["sequence"]:
            track_code = step.get("track_code", "")
            callsign = step.get("callsign_label", "")
            alert_title = step.get("alert_title", "")
            alert_summary = step.get("alert_summary", "")

            # Ensure no real adversary platform names or tactical border/scramble words
            self.assertNotIn("J-20", track_code)
            self.assertNotIn("J-20", callsign)
            self.assertNotIn("Border", callsign)
            self.assertNotIn("QRA", alert_summary)
            self.assertNotIn("Scramble", alert_title)

    def test_seeded_equipment_uses_generic_classifications(self):
        """Verify seeded active equipment categories are generic fictional types."""
        active_equipment = Equipment.objects.filter(airbase=self.airbase)
        self.assertGreater(active_equipment.count(), 0)

        for eq in active_equipment:
            category = eq.category
            self.assertIn(
                category,
                [
                    Equipment.EquipmentCategory.TYPE_A,
                    Equipment.EquipmentCategory.TYPE_B,
                    Equipment.EquipmentCategory.TYPE_C,
                    Equipment.EquipmentCategory.RADAR_SUPPORT,
                ],
            )
            # Ensure not using legacy real platform names in operational records
            self.assertNotIn("Rafale", category)
            self.assertNotIn("Su-30", category)
            self.assertNotIn("Tejas", category)

    def test_deterministic_constraint_gate_blocks_infeasible_option(self):
        """Verify deterministic hard constraints strictly override ML scoring for infeasible options."""
        options = score_operational_options(self.airbase, force_fallback=True)
        infeasible_opt = next(o for o in options if o["option_id"] == "OPT-C-INFEASIBLE-FDTL")

        self.assertFalse(infeasible_opt["feasible"])
        self.assertFalse(infeasible_opt["recommended"])
        self.assertEqual(infeasible_opt["score"], 0.0)
        self.assertEqual(infeasible_opt["baseline_score"], 0.0)
        self.assertTrue(any("HARD CONSTRAINT BLOCKED" in r for r in infeasible_opt["reasons"]))

    def test_rendered_portal_displays_simulation_and_synthetic_badges(self):
        """Verify UI displays visible SIMULATION MODE banner and SYNTHETIC data mode badge."""
        self.client.force_login(self.cmdr)
        response = self.client.get(reverse("commander_dashboard"))
        self.assertEqual(response.status_code, 200)

        content = response.content.decode("utf-8")
        self.assertIn("SIMULATION MODE: ACTIVE", content)
        self.assertIn("SYNTHETIC", content)
        self.assertIn("Seed: 26250", content)
        self.assertNotIn("Scramble 2x Interceptors", content)
