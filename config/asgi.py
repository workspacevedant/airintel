"""
ASGI config for AERO-OPS (SIH26250).
Exposes the ASGI callable as a module-level variable named ``application``.
Supports HTTP and session-authenticated Django Channels WebSockets.
"""
import os
from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django_asgi_app = get_asgi_application()

from channels.auth import AuthMiddlewareStack  # noqa: E402
from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402
from channels.security.websocket import AllowedHostsOriginValidator  # noqa: E402


def get_websocket_urlpatterns():
    """Lazily load WebSocket URL patterns from radar_simulation.routing when present."""
    try:
        from apps.radar_simulation.routing import websocket_urlpatterns

        return websocket_urlpatterns
    except ImportError:
        return []


application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": AllowedHostsOriginValidator(
            AuthMiddlewareStack(URLRouter(get_websocket_urlpatterns()))
        ),
    }
)
