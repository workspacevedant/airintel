"""
Root URL configuration for AERO-OPS (SIH26250).
Mounts the core auth and REST API contract from apps/core/urls.py and serves static assets.
"""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.staticfiles.urls import staticfiles_urlpatterns
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("apps.core.urls")),
]

# Serve static files through Daphne ASGI server in development
urlpatterns += staticfiles_urlpatterns()
if settings.STATICFILES_DIRS:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATICFILES_DIRS[0])
elif settings.STATIC_ROOT:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
