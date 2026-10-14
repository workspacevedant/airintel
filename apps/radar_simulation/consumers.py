"""
Django Channels WebSocket Consumer for AERO-OPS (/ws/events/).
Implements Section 07, 10 & 11:
- Authenticates connections using the standard Django session.
- Rejects anonymous or inactive users.
- Subscribes strictly to server-derived groups (zone_<code>, airbase_<code>, squadron_<code>).
- Rejects client attempts to subscribe to arbitrary group names.
- Supports reconnect state synchronization.
"""
from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.utils import timezone

from apps.core.models import Event
from apps.core.permissions import get_authorised_ws_groups, get_user_scope, log_security_denial
from apps.core.selectors import build_dashboard_summary


class OperationalEventsConsumer(AsyncJsonWebsocketConsumer):
    """Real-time event consumer scoped strictly by the user's server-side RoleAssignment."""

    async def connect(self):
        user = self.scope.get("user")
        if not user or not user.is_authenticated or not getattr(user, "active", True):
            await self.close(code=4403)
            return

        try:
            self.authorised_groups = await database_sync_to_async(get_authorised_ws_groups)(user)
            self.user_scope_info = await database_sync_to_async(self._get_scope_summary)(user)
        except Exception:
            await self.close(code=4403)
            return

        if not self.authorised_groups:
            # Authenticated user with no active scope assignment cannot receive scoped feeds
            await self.close(code=4403)
            return

        for group_name in self.authorised_groups:
            await self.channel_layer.group_add(group_name, self.channel_name)

        await self.accept()

        await self.send_json(
            {
                "message_type": "connection.established",
                "simulation_mode_banner": "SYNTHETIC SIMULATION MODE — NON-OPERATIONAL DEMO (SIH26250)",
                "subscribed_groups": sorted(self.authorised_groups),
                "scope": self.user_scope_info,
                "timestamp": timezone.now().isoformat(),
            }
        )

    async def disconnect(self, close_code):
        for group_name in getattr(self, "authorised_groups", set()):
            try:
                await self.channel_layer.group_discard(group_name, self.channel_name)
            except Exception:
                pass

    async def receive_json(self, content, **kwargs):
        """
        Handle client messages:
        - Reject any attempt to subscribe to a client-supplied group outside authorised_groups (Section 10 & 11).
        - Support 'sync_state' on reconnect to fetch authoritative state and last event sequence.
        """
        action = content.get("action")
        user = self.scope.get("user")

        if action == "subscribe":
            requested_group = str(content.get("group", "")).strip()
            if requested_group not in self.authorised_groups:
                await database_sync_to_async(log_security_denial)(
                    user=user,
                    action="WS_UNAUTHORIZED_GROUP_SUBSCRIBE",
                    object_type="WebSocketGroup",
                    object_id=requested_group or "UNKNOWN",
                    reason=f"Client attempted to subscribe to unauthorised group '{requested_group}'.",
                    source="ws:/ws/events/",
                )
                await self.send_json(
                    {
                        "message_type": "error.forbidden",
                        "status": 403,
                        "detail": "Forbidden: Server-derived group policy prohibits client-supplied group subscription.",
                    }
                )
                return

        if action in ("sync_state", "reconnect", "ping"):
            state_snapshot = await database_sync_to_async(self._get_reconnect_snapshot)(user)
            await self.send_json(
                {
                    "message_type": "state.synchronized",
                    "timestamp": timezone.now().isoformat(),
                    "data": state_snapshot,
                }
            )

    async def aero_event_message(self, event):
        """Forwards group_send envelopes to the connected browser client."""
        await self.send_json(
            {
                "message_type": event.get("message_type", "event.created"),
                "timestamp": event.get("timestamp", timezone.now().isoformat()),
                "data_mode": event.get("data_mode", "synthetic"),
                "payload": event.get("payload", {}),
            }
        )

    @staticmethod
    def _get_scope_summary(user):
        ctx = get_user_scope(user)
        return {
            "username": user.username,
            "role": ctx.primary_role,
            "airbase_codes": sorted(ctx.airbase_codes),
            "squadron_codes": sorted(ctx.squadron_codes),
            "zone_codes": sorted(ctx.zone_codes),
        }

    @staticmethod
    def _get_reconnect_snapshot(user):
        summary = build_dashboard_summary(user)
        latest_evt = Event.objects.order_by("-occurred_at").first()
        return {
            "last_event_id": latest_evt.event_id if latest_evt else None,
            "counters": summary["counters"],
            "simulation": summary["simulation"],
            "readiness_snapshot": summary["readiness_snapshot"],
        }
