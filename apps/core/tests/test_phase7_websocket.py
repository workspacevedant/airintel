"""
Phase 7 WebSocket Tests for AERO-OPS (SIH26250).
Verifies Requirements:
- S07-03: Real-time WebSocket delivery via Django Channels with session auth.
- S07-04: Server-derived authorized groups; reject untrusted group subscription.
- S07-05: Reconnect state synchronization.
- S10-17: /ws/events/ endpoint lifecycle and security.
- S11-09: Authenticate connections, server-side group authorization, minimal payloads.
- S14-05: WebSocket tests (channels.testing WebsocketCommunicator): anonymous rejected, wrong group rejected, reconnect sync.
"""
from channels.db import database_sync_to_async
from channels.layers import get_channel_layer
from channels.testing import WebsocketCommunicator
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.management import call_command
from django.test import TransactionTestCase

from apps.core.models import AuditLog, Event
from apps.radar_simulation.consumers import OperationalEventsConsumer
from config.asgi import application

User = get_user_model()


class Phase7WebSocketTests(TransactionTestCase):
    """Automated WebSocket tests verifying authentication, authorization, and isolation."""

    def setUp(self):
        call_command("seed_demo_data")
        self.commander = User.objects.get(username="cmdr_vsingh")
        self.squadron_leader = User.objects.get(username="sqldr_sharma")
        self.zonal_commander = User.objects.get(username="zonal_knair")

    async def test_s14_05_anonymous_websocket_connection_rejected_with_4403(self):
        """Anonymous or unauthenticated connection is rejected with close code 4403."""
        communicator = WebsocketCommunicator(OperationalEventsConsumer.as_asgi(), "/ws/events/")
        communicator.scope["user"] = AnonymousUser()
        communicator.scope["session"] = {}

        connected, close_code = await communicator.connect()
        self.assertFalse(connected)
        self.assertEqual(close_code, 4403)
        await communicator.disconnect()

    async def test_s07_03_authenticated_commander_connects_and_receives_server_derived_groups(self):
        """Authenticated Airbase Commander connects, receives server-derived groups & simulation banner."""
        communicator = WebsocketCommunicator(OperationalEventsConsumer.as_asgi(), "/ws/events/")
        communicator.scope["user"] = self.commander
        communicator.scope["session"] = {}

        connected, subprotocol = await communicator.connect()
        self.assertTrue(connected)

        response = await communicator.receive_json_from()
        self.assertEqual(response.get("message_type"), "connection.established")
        self.assertIn("SYNTHETIC SIMULATION MODE", response.get("simulation_mode_banner", ""))
        subscribed = response.get("subscribed_groups", [])
        self.assertIn("airbase_AB-DEMO-01", subscribed)
        self.assertIn("squadron_SQ-DEMO-01", subscribed)
        self.assertIn("zone_ZONE-DEMO-A", subscribed)

        scope = response.get("scope", {})
        self.assertEqual(scope.get("role"), "AIRBASE_COMMANDER")
        self.assertIn("AB-DEMO-01", scope.get("airbase_codes", []))

        await communicator.disconnect()

    async def test_s07_04_unauthorized_group_subscription_blocked_and_audited(self):
        """Client attempting to subscribe to an unauthorized group is rejected with 403 and logged."""
        communicator = WebsocketCommunicator(OperationalEventsConsumer.as_asgi(), "/ws/events/")
        communicator.scope["user"] = self.commander
        communicator.scope["session"] = {}

        connected, _ = await communicator.connect()
        self.assertTrue(connected)
        _ = await communicator.receive_json_from()  # consume connection.established

        # Attempt to subscribe to out-of-scope group
        await communicator.send_json_to({"action": "subscribe", "group": "airbase_AB-FORBIDDEN-99"})
        error_resp = await communicator.receive_json_from()

        self.assertEqual(error_resp.get("message_type"), "error.forbidden")
        self.assertEqual(error_resp.get("status"), 403)
        self.assertIn("Server-derived group policy prohibits", error_resp.get("detail", ""))

        await communicator.disconnect()

        # Verify audit log record
        def _get_audit():
            return AuditLog.objects.filter(
                actor=self.commander,
                action="WS_UNAUTHORIZED_GROUP_SUBSCRIBE",
                object_id="airbase_AB-FORBIDDEN-99",
            ).first()

        audit = await database_sync_to_async(_get_audit)()
        self.assertIsNotNone(audit)

    async def test_s07_05_reconnect_sync_state_returns_snapshot(self):
        """Client requesting sync_state receives authoritative state snapshot with counters."""
        communicator = WebsocketCommunicator(OperationalEventsConsumer.as_asgi(), "/ws/events/")
        communicator.scope["user"] = self.commander
        communicator.scope["session"] = {}

        connected, _ = await communicator.connect()
        self.assertTrue(connected)
        _ = await communicator.receive_json_from()

        await communicator.send_json_to({"action": "sync_state"})
        sync_resp = await communicator.receive_json_from()

        self.assertEqual(sync_resp.get("message_type"), "state.synchronized")
        data = sync_resp.get("data", {})
        self.assertIn("counters", data)
        self.assertIn("simulation", data)
        self.assertIn("readiness_snapshot", data)

        await communicator.disconnect()

    async def test_s10_17_squadron_leader_scope_isolation_no_cross_scope_groups(self):
        """Squadron Leader only receives squadron-scoped groups, never zone or airbase-level groups."""
        communicator = WebsocketCommunicator(OperationalEventsConsumer.as_asgi(), "/ws/events/")
        communicator.scope["user"] = self.squadron_leader
        communicator.scope["session"] = {}

        connected, _ = await communicator.connect()
        self.assertTrue(connected)

        conn_resp = await communicator.receive_json_from()
        subscribed = conn_resp.get("subscribed_groups", [])
        self.assertEqual(subscribed, ["squadron_SQ-DEMO-01"])
        self.assertNotIn("zone_ZONE-DEMO-A", subscribed)
        self.assertNotIn("airbase_AB-DEMO-01", subscribed)

        await communicator.disconnect()

    async def test_s11_09_scoped_event_forwarding_to_connected_client(self):
        """Group send forwards formatted synthetic event message to connected consumer."""
        channel_layer = get_channel_layer()
        communicator = WebsocketCommunicator(OperationalEventsConsumer.as_asgi(), "/ws/events/")
        communicator.scope["user"] = self.commander
        communicator.scope["session"] = {}

        connected, _ = await communicator.connect()
        self.assertTrue(connected)
        _ = await communicator.receive_json_from()

        # Broadcast test event to airbase group
        await channel_layer.group_send(
            "airbase_AB-DEMO-01",
            {
                "type": "aero.event.message",
                "message_type": "event.created",
                "data_mode": "synthetic",
                "payload": {
                    "event_id": "EVT-TEST-WS-001",
                    "event_type": "EQUIPMENT_STATUS_CHANGED",
                    "severity": "INFO",
                },
            },
        )

        msg = await communicator.receive_json_from()
        self.assertEqual(msg.get("message_type"), "event.created")
        self.assertEqual(msg.get("data_mode"), "synthetic")
        self.assertEqual(msg.get("payload", {}).get("event_id"), "EVT-TEST-WS-001")

        await communicator.disconnect()
