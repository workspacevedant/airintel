"""
WebSocket URL routing for AERO-OPS (Section 10 & 12).
"""
from django.urls import re_path
from apps.radar_simulation.consumers import OperationalEventsConsumer

websocket_urlpatterns = [
    re_path(r"^ws/events/?$", OperationalEventsConsumer.as_asgi()),
]
