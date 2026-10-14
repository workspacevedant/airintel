"""
Template-rendering Portal Views for AERO-OPS Part 3 (Variant C NIC/GovTech UI).
Provides seamless session login, 1-click demo role switching for the 7-minute SIH judge runbook,
and role-scoped rendering for Airbase Commander, Squadron Leader, and Zonal Commander.
"""
from django.contrib.auth import authenticate, login
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.csrf import csrf_exempt

from apps.core.models import AuditLog, User
from apps.core.permissions import get_user_scope


def _ensure_demo_user_logged_in(request: HttpRequest, default_username: str = "cmdr_vsingh") -> User:
    if request.user and request.user.is_authenticated:
        return request.user
    user = User.objects.filter(username=default_username).first() or User.objects.first()
    if user:
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    return user


def commander_dashboard_page(request: HttpRequest) -> HttpResponse:
    """Renders the primary Variant C Compact Multi-Section Layout dashboard."""
    user = _ensure_demo_user_logged_in(request, "cmdr_vsingh")
    role_label = "Airbase Commander"
    airbase_label = "Avalon Forward Base (AB-DEMO-01)"
    can_sim = True
    if user:
        try:
            ctx = get_user_scope(user)
            can_sim = ctx.can_control_simulation
            if ctx.is_zonal_commander:
                role_label = "Zonal Commander"
                airbase_label = "Sector 7 Forward Zone (ZONE-DEMO-A)"
            elif ctx.is_squadron_leader:
                role_label = "Squadron Leader"
                airbase_label = "No. 17 Squadron (SQ-DEMO-01) · AB-DEMO-01"
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


def squadron_dashboard_page(request: HttpRequest) -> HttpResponse:
    """Renders the Squadron Leader scoped view."""
    user = _ensure_demo_user_logged_in(request, "sqldr_sharma")
    return render(
        request,
        "squadron/dashboard.html",
        {
            "page_title": "No. 17 Squadron (SQ-DEMO-01)",
            "active_airbase_label": "No. 17 Squadron (SQ-DEMO-01) · Avalon Forward Base",
            "active_role_label": "Squadron Leader",
            "can_control_simulation": False,
        },
    )


def zonal_dashboard_page(request: HttpRequest) -> HttpResponse:
    """Renders the Zonal Commander cross-airbase view."""
    user = _ensure_demo_user_logged_in(request, "zonal_knair")
    return render(
        request,
        "commander/zonal_dashboard.html",
        {
            "page_title": "Sector 7 Zonal Command (ZONE-DEMO-A)",
            "active_airbase_label": "Sector 7 Northern Airspace (ZONE-DEMO-A)",
            "active_role_label": "Zonal Commander",
            "can_control_simulation": True,
        },
    )


@csrf_exempt
def portal_login_page(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
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
            {"error_message": "Invalid credentials. Use cmdr_vsingh / AeroOps@26250."},
            status=401,
        )
    return render(request, "auth/login.html")


@csrf_exempt
def portal_switch_role_view(request: HttpRequest) -> HttpResponse:
    """Allows 1-click switching between the 3 seeded demo accounts during the 7-minute SIH judge runbook."""
    if request.method == "POST":
        username = request.POST.get("username", "cmdr_vsingh").strip()
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
