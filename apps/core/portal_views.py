"""
Template-rendering Portal Views for AERO-OPS (SIH26250).
Strictly implements Phase 1 Security Controls:
1. No auto-login: unauthenticated users are redirected to /login/.
2. /switch-role/ is enabled ONLY when settings.DEMO_MODE is True, POST + CSRF only, restricted to 3 seeded accounts, audited.
3. Zero @csrf_exempt decorators; CSRF enforced on all mutating requests.
4. Generic error messages (no leaked credentials); demo helper displayed only when DEMO_MODE is True.
"""
from typing import Dict
from django.conf import settings
from django.contrib.auth import authenticate, login
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.http import (
    HttpRequest,
    HttpResponse,
    HttpResponseBadRequest,
    HttpResponseForbidden,
    HttpResponseNotAllowed,
)
from django.shortcuts import redirect, render

from apps.core.models import AuditLog, User
from apps.core.permissions import get_user_scope

ALLOWED_DEMO_ACCOUNTS = {"cmdr_vsingh", "sqldr_sharma", "zonal_knair"}


def demo_mode_context_processor(request: HttpRequest) -> Dict[str, bool]:
    """Exposes DEMO_MODE to templates so demo helpers render only during testing/demo."""
    return {"DEMO_MODE": getattr(settings, "DEMO_MODE", False)}


def _check_ip_rate_limit(request: HttpRequest, key_prefix: str, limit: int = 5, timeout: int = 60) -> bool:
    """Returns True if within limit, False if rate limit exceeded."""
    ip = request.META.get("HTTP_X_FORWARDED_FOR", request.META.get("REMOTE_ADDR", "127.0.0.1")).split(",")[0].strip()
    cache_key = f"ratelimit:{key_prefix}:{ip}"
    count = cache.get(cache_key, 0)
    if count >= limit:
        return False
    cache.set(cache_key, count + 1, timeout=timeout)
    return True


@login_required(login_url="/login/")
def commander_dashboard_page(request: HttpRequest) -> HttpResponse:
    """Renders the primary Variant C Compact Multi-Section Layout dashboard."""
    user = request.user
    role_label = "Airbase Commander"
    airbase_label = "Avalon Forward Base (AB-DEMO-01)"
    can_sim = False

    try:
        ctx = get_user_scope(user)
        can_sim = ctx.can_control_simulation
        if ctx.is_zonal_commander:
            role_label = "Zonal Commander"
            airbase_label = "Sector 7 Forward Zone (ZONE-DEMO-A)"
        elif ctx.is_squadron_leader:
            role_label = "Squadron Leader"
            airbase_label = f"{ctx.assigned_squadron_code or 'Assigned Squadron'} · AB-DEMO-01"
        else:
            role_label = "Airbase Commander"
            airbase_label = f"{ctx.assigned_airbase_code or 'Avalon Forward Base'} (AB-DEMO-01)"
    except Exception:
        pass

    return render(
        request,
        "commander/dashboard.html",
        {
            "page_title": airbase_label,
            "active_airbase_label": airbase_label,
            "active_role_label": role_label,
            "can_control_simulation": can_sim,
        },
    )


@login_required(login_url="/login/")
def squadron_dashboard_page(request: HttpRequest) -> HttpResponse:
    """Renders the Squadron Leader scoped view."""
    user = request.user
    ctx = get_user_scope(user)
    sq_label = ctx.assigned_squadron_code or "SQ-DEMO-01"
    return render(
        request,
        "squadron/dashboard.html",
        {
            "page_title": f"Squadron Operations ({sq_label})",
            "active_airbase_label": f"{sq_label} · Avalon Forward Base",
            "active_role_label": "Squadron Leader",
            "can_control_simulation": False,
        },
    )


@login_required(login_url="/login/")
def zonal_dashboard_page(request: HttpRequest) -> HttpResponse:
    """Renders the Zonal Commander cross-airbase view."""
    user = request.user
    ctx = get_user_scope(user)
    zone_label = ctx.assigned_zone_code or "ZONE-DEMO-A"
    return render(
        request,
        "commander/zonal_dashboard.html",
        {
            "page_title": f"Zonal Command Oversight ({zone_label})",
            "active_airbase_label": f"Northern Sector Airspace ({zone_label})",
            "active_role_label": "Zonal Commander",
            "can_control_simulation": ctx.can_control_simulation,
        },
    )


def portal_login_page(request: HttpRequest) -> HttpResponse:
    """Session login with CSRF enforcement and rate limiting."""
    if request.user.is_authenticated:
        return redirect("commander_dashboard")

    if request.method == "POST":
        if not _check_ip_rate_limit(request, "login", limit=5, timeout=60):
            return render(
                request,
                "auth/login.html",
                {"error_message": "Rate limit exceeded. Please wait 60 seconds before retrying."},
                status=429,
            )

        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            AuditLog.objects.create(
                actor=user,
                action="PORTAL_SIGN_IN",
                object_type="User",
                object_id=user.username,
                before=None,
                after={"role": user.requested_designation},
                source="portal:/login/",
            )
            return redirect("commander_dashboard")

        return render(
            request,
            "auth/login.html",
            {"error_message": "Invalid username or password."},
            status=401,
        )

    return render(request, "auth/login.html")


def portal_switch_role_view(request: HttpRequest) -> HttpResponse:
    """
    1-click demo role switching.
    Security Guards:
    - Disabled outside settings.DEMO_MODE (HTTP 403)
    - Restricted to POST requests only (HTTP 405)
    - Restricted to ALLOWED_DEMO_ACCOUNTS (HTTP 400)
    - Fully audited in AuditLog
    """
    if not getattr(settings, "DEMO_MODE", False):
        return HttpResponseForbidden("Demo role switching is disabled in production mode.")

    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    username = request.POST.get("username", "").strip()
    if username not in ALLOWED_DEMO_ACCOUNTS:
        return HttpResponseBadRequest("Invalid demo account identifier.")

    target_user = User.objects.filter(username=username).first()
    if target_user:
        login(request, target_user, backend="django.contrib.auth.backends.ModelBackend")
        AuditLog.objects.create(
            actor=target_user,
            action="DEMO_ACCOUNT_SWITCHED",
            object_type="User",
            object_id=target_user.username,
            before=None,
            after={"switched_to": target_user.username, "designation": target_user.requested_designation},
            source="portal:/switch-role/",
        )
        if username == "sqldr_sharma":
            return redirect("squadron_dashboard")
        if username == "zonal_knair":
            return redirect("zonal_dashboard")

    return redirect("commander_dashboard")
