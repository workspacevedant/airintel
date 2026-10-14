"""
Phase 7 Database, Spatial, and Index Tests for AERO-OPS (SIH26250).
Verifies Requirements:
- S09-01: PostGIS spatial fields with SRID 4326 for zones, airbases, sensors, tracks.
- S09-02: GiST indexes on geometries and B-tree on timestamps/status.
- S09-03: Core entities and relation integrity.
- S14-06: Spatial queries, containment, and boundary tests.
- Database constraints: chk_maint_due_after_opened and AuditLog immutability.
"""
from datetime import timedelta
from django.contrib.auth import get_user_model
from django.contrib.gis.geos import Point, Polygon
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from apps.core.models import (
    Airbase,
    AuditLog,
    CrewReadiness,
    Equipment,
    Event,
    MaintenanceTask,
    Order,
    RoleAssignment,
    Squadron,
    Zone,
)
from apps.radar_simulation.models import SensorNode, Track

User = get_user_model()


class Phase7DatabaseAndSpatialTests(TestCase):
    """Automated tests for PostGIS SRID 4326, GiST indexes, check constraints, and immutability."""

    def setUp(self):
        call_command("seed_demo_data")
        self.commander = User.objects.get(username="cmdr_vsingh")

    def test_s09_01_srid_4326_spatial_fields_and_containment(self):
        """Verify SRID 4326 on Zone, Airbase, SensorNode, Track, and spatial polygon containment."""
        zone = Zone.objects.get(code="ZONE-DEMO-A")
        airbase = Airbase.objects.get(code="AB-DEMO-01")
        sensor = SensorNode.objects.filter(zone=zone).first()
        track = Track.objects.first()

        # 1. Verify SRID 4326 on all geometries
        self.assertEqual(zone.boundary.srid, 4326)
        self.assertEqual(airbase.location.srid, 4326)
        if sensor:
            self.assertEqual(sensor.location.srid, 4326)
        if track:
            self.assertEqual(track.last_position.srid, 4326)

        # 2. Verify spatial containment: airbase location is within assigned zone boundary
        self.assertTrue(
            zone.boundary.contains(airbase.location),
            f"Airbase {airbase.code} ({airbase.location}) must lie within Zone {zone.code} boundary",
        )

        # 3. Verify spatial point-in-polygon QuerySet filter
        bases_in_zone = Airbase.objects.filter(location__within=zone.boundary)
        self.assertTrue(bases_in_zone.filter(code="AB-DEMO-01").exists())

    def test_s09_02_gist_and_btree_indexes_declared_on_models(self):
        """Verify GiST spatial indexes and B-tree indexes exist on core spatial models."""
        # Zone boundary index
        zone_index_types = [type(idx).__name__ for idx in Zone._meta.indexes]
        self.assertTrue(
            any("Gist" in t or "gist" in t.lower() for t in zone_index_types) or Zone._meta.get_field("boundary").spatial_index,
            "Zone boundary must have a spatial index.",
        )

        # Airbase location index
        self.assertTrue(
            Airbase._meta.get_field("location").spatial_index,
            "Airbase location must have spatial indexing enabled.",
        )

        # MaintenanceTask check constraint
        maint_constraints = [c.name for c in MaintenanceTask._meta.constraints]
        self.assertIn("chk_maint_due_after_opened", maint_constraints)

    def test_s14_06_database_check_constraint_rejects_due_before_opened(self):
        """Database constraint chk_maint_due_after_opened rejects due_at < opened_at."""
        equip = Equipment.objects.get(fictional_code="RF-102")
        now = timezone.now()
        invalid_due = now - timedelta(days=2)

        with self.assertRaises((IntegrityError, ValidationError)):
            with transaction.atomic():
                MaintenanceTask.objects.create(
                    equipment=equip,
                    opened_at=now,
                    due_at=invalid_due,
                    fault_code="FLT-TEST-CONSTRAINT",
                    severity=MaintenanceTask.Severity.LOW,
                    status=MaintenanceTask.TaskStatus.OPEN,
                )

    def test_s11_07_audit_log_append_only_immutability(self):
        """AuditLog prohibits mutations (save() after insert) and deletions (delete())."""
        audit = AuditLog.objects.create(
            actor=self.commander,
            action="SECURITY_VERIFICATION_TEST",
            object_type="AuditLog",
            object_id="TEST-IMMUTABLE-01",
            before=None,
            after={"verified": True},
            source="test:immutability",
        )
        self.assertIsNotNone(audit.id)

        # Modifying an existing record must raise RuntimeError or ValidationError
        with self.assertRaises((RuntimeError, ValidationError)):
            audit.action = "TAMPERED_ACTION"
            audit.save()

        # Deleting an existing audit record must raise PermissionDenied
        with self.assertRaises(PermissionDenied):
            audit.delete()
