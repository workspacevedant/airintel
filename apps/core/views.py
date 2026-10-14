"""
REST API Views for AERO-OPS (SIH26250).
Implements all 16 endpoints from Section 10 of the Master Specification + Variant C Commander overrides,
enforcing strict server-side RBAC, object-level scope isolation (403 on cross-scope access),
and append-only AuditLog recording.
"""
import json
from typing import Any, Dict
from django.contrib.auth import authenticate, login, logout
from django.contrib.gis.geos import Point
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.http import HttpRequest, JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.http import require_http_methods

from apps.core.ratelimit import check_rate_limit, rate_limit_response

from apps.core.forms import RegistrationForm
from apps.core.models import (
    Airbase,
    Alert,
    AuditLog,
    CrewReadiness,
    DesignationChoices,
    Equipment,
    Event,
    MaintenanceTask,
    Order,
    Profile,
    RoleAssignment,
    Squadron,
    User,
    Zone,
)
from apps.core.permissions import (
    assert_can_control_simulation,
    assert_can_manage_maintenance,
    assert_can_mutate_airbase,
    assert_can_update_equipment,
    enforce_query_scope,
    get_user_scope,
    log_security_denial,
)
from apps.core.selectors import (
    build_dashboard_summary,
    get_visible_airbases,
    get_visible_alerts,
    get_visible_crew_readiness,
    get_visible_equipment,
    get_visible_events,
    get_visible_maintenance_tasks,
    get_visible_orders,
    get_visible_suggestions,
)
from apps.core.services import (
    acknowledge_order_or_alert,
    override_fdtl_or_infrastructure,
    transition_crew_report_status,
    update_crew_duty_state,
    update_equipment_status,
)
from apps.radar_simulation.engine import HybridRadarEngine
from apps.radar_simulation.models import SensorNode, SimulationRun, Track
from apps.suggestion.models import Suggestion
from apps.suggestion.predict import predict_equipment_readiness, score_operational_options


def _parse_body(request: HttpRequest) -> Dict[str, Any]:
    if request.content_type and "application/json" in request.content_type:
        try:
            return json.loads(request.body.decode("utf-8") or "{}")
        except json.JSONDecodeError as exc:
            raise ValidationError(f"Malformed JSON payload: {exc}")
    return request.POST.dict()


def _require_auth(request: HttpRequest) -> User:
    if not request.user or not request.user.is_authenticated:
        raise PermissionDenied("Authentication required.")
    return request.user


def _json_error(message: str, status: int = 400, extra: Dict[str, Any] = None) -> JsonResponse:
    payload = {"error": message, "status": status, "data_mode": "synthetic"}
    if extra:
        payload.update(extra)
    return JsonResponse(payload, status=status)


# -------------------------------------------------------------------------
# 1. AUTHENTICATION & REGISTRATION ENDPOINTS (POST /auth/register/, /auth/login/, /auth/logout/)
# -------------------------------------------------------------------------
@require_http_methods(["POST"])
def auth_register_view(request: HttpRequest) -> JsonResponse:
    """
    POST /auth/register/
    Creates an account with self-selected designation.
    Applies a safe default scope: RoleAssignment starts in PENDING state with NO arbitrary
    airbase or zone access until approved/assigned (Section 04, 10 & 11).
    """
    if not check_rate_limit(request, "register", limit=5, timeout=60):
        return rate_limit_response("Rate limit of 5 registration requests per minute exceeded.")

    try:
        data = _parse_body(request)
    except ValidationError as exc:
        return _json_error(str(exc), status=400)

    form = RegistrationForm(data)
    if not form.is_valid():
        return _json_error("Invalid registration input.", status=400, extra={"errors": form.errors})

    cleaned = form.cleaned_data
    if User.objects.filter(username=cleaned["username"]).exists():
        return _json_error("Username is already registered.", status=400)
    if User.objects.filter(email=cleaned["email"]).exists():
        return _json_error("Email is already registered.", status=400)

    # Reject any attempt to self-assign an active airbase_id or zone_id directly at sign-up (Section 04 & 11)
    if data.get("airbase_id") or data.get("zone_id") or data.get("status") == "ACTIVE":
        log_security_denial(
            user=None,
            action="SELF_REGISTRATION_SCOPE_TAMPERING_BLOCKED",
            object_type="User",
            object_id=cleaned["username"],
            reason="Self-registered user attempted to supply unrestricted scope IDs at sign-up.",
            source="api:/auth/register/",
        )

    with transaction.atomic():
        user = User.objects.create_user(
            username=cleaned["username"],
            email=cleaned["email"],
            password=cleaned["password"],
            display_name=cleaned["display_name"],
            requested_designation=cleaned["requested_designation"],
            active=True,
        )
        Profile.objects.create(
            user=user,
            display_name=cleaned["display_name"],
            requested_designation=cleaned["requested_designation"],
            active=True,
        )
        # Safe default scope: PENDING and unscoped (no airbase/zone visible until administrator approval)
        assignment = RoleAssignment.objects.create(
            user=user,
            role=cleaned["requested_designation"],
            airbase=None,
            squadron=None,
            zone=None,
            status=RoleAssignment.AssignmentStatus.PENDING,
            can_control_simulation=False,
        )
        AuditLog.objects.create(
            actor=user,
            action="USER_REGISTERED_SAFE_DEFAULT_SCOPE",
            object_type="RoleAssignment",
            object_id=str(assignment.id),
            before=None,
            after={
                "username": user.username,
                "requested_designation": user.requested_designation,
                "assignment_status": assignment.status,
                "airbase": None,
                "zone": None,
            },
            source="api:/auth/register/",
        )

    return JsonResponse(
        {
            "id": str(user.id),
            "username": user.username,
            "email": user.email,
            "display_name": user.display_name,
            "requested_designation": user.requested_designation,
            "role_assignment_status": assignment.status,
            "assigned_scope": None,
            "notice": "Account created with safe default scope (PENDING approval). No airbase or zone records are visible until assigned.",
        },
        status=201,
    )


@require_http_methods(["POST"])
def auth_login_view(request: HttpRequest) -> JsonResponse:
    """POST /auth/login/ — Authenticates session and audits login (Section 04 & 11)."""
    if not check_rate_limit(request, "login", limit=5, timeout=60):
        return rate_limit_response("Rate limit of 5 login requests per minute exceeded.")

    try:
        data = _parse_body(request)
    except ValidationError as exc:
        return _json_error(str(exc), status=400)

    username = data.get("username", "").strip()
    password = data.get("password", "")
    user = authenticate(request, username=username, password=password)
    if user is None:
        log_security_denial(
            user=None,
            action="AUTH_LOGIN_FAILED",
            object_type="User",
            object_id=username or "ANONYMOUS",
            reason="Invalid credentials supplied.",
            source="api:/auth/login/",
        )
        return _json_error("Invalid username or password.", status=401)

    login(request, user)
    AuditLog.objects.create(
        actor=user,
        action="USER_SIGN_IN",
        object_type="User",
        object_id=user.username,
        before=None,
        after={"session_authenticated": True},
        source="api:/auth/login/",
    )
    ctx = get_user_scope(user)
    return JsonResponse(
        {
            "authenticated": True,
            "username": user.username,
            "display_name": user.display_name,
            "role": ctx.primary_role,
            "airbase_codes": sorted(ctx.airbase_codes),
            "squadron_codes": sorted(ctx.squadron_codes),
            "zone_codes": sorted(ctx.zone_codes),
        }
    )


@require_http_methods(["POST"])
def auth_logout_view(request: HttpRequest) -> JsonResponse:
    """POST /auth/logout/ — Terminates session and audits sign-out."""
    if request.user and request.user.is_authenticated:
        AuditLog.objects.create(
            actor=request.user,
            action="USER_SIGN_OUT",
            object_type="User",
            object_id=request.user.username,
            before={"session_authenticated": True},
            after={"session_authenticated": False},
            source="api:/auth/logout/",
        )
    logout(request)
    return JsonResponse({"authenticated": False, "detail": "Logged out successfully."})


# -------------------------------------------------------------------------
# 2. CURRENT USER & DASHBOARD SUMMARY (GET /api/me/, GET /api/dashboard/summary/)
# -------------------------------------------------------------------------
@require_http_methods(["GET"])
def api_me_view(request: HttpRequest) -> JsonResponse:
    """GET /api/me/ — Current user, role, and assigned object-level scope (Section 10)."""
    try:
        user = _require_auth(request)
        ctx = enforce_query_scope(user, request)
    except PermissionDenied as exc:
        return _json_error(str(exc), status=403)

    return JsonResponse(
        {
            "id": str(user.id),
            "username": user.username,
            "email": user.email,
            "display_name": user.display_name,
            "requested_designation": user.requested_designation,
            "active_role": ctx.primary_role,
            "roles": sorted(ctx.roles),
            "scope": {
                "zone_codes": sorted(ctx.zone_codes),
                "airbase_codes": sorted(ctx.airbase_codes),
                "squadron_codes": sorted(ctx.squadron_codes),
                "can_control_simulation": ctx.can_control_simulation,
            },
            "data_mode": "synthetic",
        }
    )


@require_http_methods(["GET"])
def api_dashboard_summary_view(request: HttpRequest) -> JsonResponse:
    """GET /api/dashboard/summary/ — Role-scoped dashboard counters and operational state (Section 10)."""
    try:
        user = _require_auth(request)
        enforce_query_scope(user, request)
        summary = build_dashboard_summary(user)
    except PermissionDenied as exc:
        return _json_error(str(exc), status=403)

    return JsonResponse(summary)


# -------------------------------------------------------------------------
# 3. AIRBASES ENDPOINTS (GET/POST /api/airbases/)
# -------------------------------------------------------------------------
@require_http_methods(["GET", "POST"])
def api_airbases_view(request: HttpRequest) -> JsonResponse:
    """
    GET /api/airbases/ — Scope-filtered list of visible airbases.
    POST /api/airbases/ — Create fictional airbase (Airbase Commander permission).
    """
    try:
        user = _require_auth(request)
        ctx = enforce_query_scope(user, request)
    except PermissionDenied as exc:
        return _json_error(str(exc), status=403)

    if request.method == "GET":
        airbases = get_visible_airbases(user)
        return JsonResponse(
            {
                "count": airbases.count(),
                "results": [
                    {
                        "id": str(ab.id),
                        "code": ab.code,
                        "name": ab.name,
                        "zone_code": ab.zone.code,
                        "lat": ab.location.y,
                        "lon": ab.location.x,
                        "runway_primary_label": ab.runway_primary_label,
                        "runway_primary_m": ab.runway_primary_m,
                        "runway_primary_status": ab.runway_primary_status,
                        "runway_secondary_label": ab.runway_secondary_label,
                        "runway_secondary_m": ab.runway_secondary_m,
                        "runway_secondary_status": ab.runway_secondary_status,
                        "arrestor_gear_status": ab.arrestor_gear_status,
                        "fuel_reserves_mt": float(ab.fuel_reserves_mt),
                        "status": ab.status,
                    }
                    for ab in airbases
                ],
            }
        )

    # POST /api/airbases/
    try:
        assert_can_mutate_airbase(user)
        data = _parse_body(request)
    except PermissionDenied as exc:
        return _json_error(str(exc), status=403)
    except ValidationError as exc:
        return _json_error(str(exc), status=400)

    code = str(data.get("code", "")).upper().strip()
    name = str(data.get("name", "")).strip()
    zone_code = str(data.get("zone_code", "ZONE-DEMO-A")).upper().strip()
    if not code or not name:
        return _json_error("Both 'code' and 'name' are required to register a fictional airbase.", status=400)

    zone = Zone.objects.filter(code=zone_code, id__in=ctx.zone_ids).first()
    if not zone:
        log_security_denial(
            user=user,
            action="CROSS_SCOPE_AIRBASE_CREATE_BLOCKED",
            object_type="Zone",
            object_id=zone_code,
            reason="Attempted to create airbase in an unassigned zone.",
        )
        return _json_error("Forbidden: Target zone is outside your authorised scope.", status=403)

    lat = float(data.get("lat", 30.40))
    lon = float(data.get("lon", 76.85))

    with transaction.atomic():
        ab = Airbase.objects.create(
            code=code,
            name=name,
            zone=zone,
            location=Point(lon, lat, srid=4326),
            runway_primary_m=int(data.get("runway_primary_m", 3000)),
            runway_secondary_m=int(data.get("runway_secondary_m", 2500)),
            fuel_reserves_mt=data.get("fuel_reserves_mt", 400.0),
            created_by=user,
            is_demo=True,
        )
        RoleAssignment.objects.create(
            user=user,
            role=DesignationChoices.AIRBASE_COMMANDER,
            airbase=ab,
            zone=zone,
            status=RoleAssignment.AssignmentStatus.ACTIVE,
            granted_by=user,
        )
        AuditLog.objects.create(
            actor=user,
            action="AIRBASE_CREATED",
            object_type="Airbase",
            object_id=ab.code,
            before=None,
            after={"code": ab.code, "name": ab.name, "zone": zone.code},
            source="api:POST /api/airbases/",
        )

    return JsonResponse(
        {"id": str(ab.id), "code": ab.code, "name": ab.name, "zone_code": zone.code, "status": ab.status},
        status=201,
    )


# -------------------------------------------------------------------------
# 4. EQUIPMENT ENDPOINTS (GET /api/equipment/, PATCH /api/equipment/{id}/status/)
# -------------------------------------------------------------------------
@require_http_methods(["GET"])
def api_equipment_list_view(request: HttpRequest) -> JsonResponse:
    """GET /api/equipment/ — Scope-filtered list of fictional aircraft/equipment (Section 10)."""
    try:
        user = _require_auth(request)
        enforce_query_scope(user, request)
        qs = get_visible_equipment(user)
    except PermissionDenied as exc:
        return _json_error(str(exc), status=403)

    return JsonResponse(
        {
            "count": qs.count(),
            "results": [
                {
                    "id": str(e.id),
                    "fictional_code": e.fictional_code,
                    "category": e.category,
                    "airbase_code": e.airbase.code,
                    "squadron_code": e.squadron.code if e.squadron else None,
                    "payload_config": e.payload_config,
                    "combat_radius_km": e.combat_radius_km,
                    "status": e.status,
                    "readiness_state": e.readiness_state,
                    "last_service_at": e.last_service_at.isoformat(),
                    "next_due_at": e.next_due_at.isoformat(),
                    "past_fault_count": e.past_fault_count,
                    "notes": e.notes,
                }
                for e in qs
            ],
        }
    )


@require_http_methods(["PATCH", "POST", "PUT"])
def api_equipment_status_update_view(request: HttpRequest, equipment_id: str) -> JsonResponse:
    """
    PATCH /api/equipment/{id}/status/
    Validates scope, checks allowed state transitions, writes before/after to AuditLog,
    recalculates readiness, and broadcasts via Channels (Section 10).
    """
    try:
        user = _require_auth(request)
        enforce_query_scope(user, request)
        data = _parse_body(request)
    except PermissionDenied as exc:
        return _json_error(str(exc), status=403)
    except ValidationError as exc:
        return _json_error(str(exc), status=400)

    equipment = (
        Equipment.objects.filter(fictional_code__iexact=equipment_id).select_related("airbase", "squadron").first()
    )
    if not equipment:
        try:
            equipment = Equipment.objects.select_related("airbase", "squadron").get(pk=equipment_id)
        except Exception:
            return _json_error(f"Equipment '{equipment_id}' not found.", status=404)

    try:
        updated = update_equipment_status(
            actor=user,
            equipment=equipment,
            new_status=data.get("status", ""),
            new_readiness_state=data.get("readiness_state"),
            notes=data.get("notes"),
        )
    except PermissionDenied as exc:
        return _json_error(str(exc), status=403)
    except ValidationError as exc:
        return _json_error(exc.message if hasattr(exc, "message") else str(exc), status=400)

    return JsonResponse(
        {
            "id": str(updated.id),
            "fictional_code": updated.fictional_code,
            "status": updated.status,
            "readiness_state": updated.readiness_state,
            "notes": updated.notes,
            "updated_at": updated.updated_at.isoformat(),
        }
    )


# -------------------------------------------------------------------------
# 4b. CREW ROSTER ENDPOINT (GET /api/crew/)
# -------------------------------------------------------------------------
@require_http_methods(["GET"])
def api_crew_list_view(request: HttpRequest) -> JsonResponse:
    """GET /api/crew/ — Scope-filtered list of flight crew readiness and FDTL status (Section 05 & 10)."""
    try:
        user = _require_auth(request)
        enforce_query_scope(user, request)
        crews = get_visible_crew_readiness(user)
    except PermissionDenied as exc:
        return _json_error(str(exc), status=403)

    return JsonResponse(
        {
            "count": crews.count(),
            "results": [
                {
                    "id": str(c.id),
                    "crew_ref": c.crew_ref,
                    "crew_code": c.crew_code,
                    "first_name": c.first_name,
                    "last_name": c.last_name,
                    "squadron_code": c.squadron.code,
                    "airbase_code": c.squadron.airbase.code if c.squadron.airbase else None,
                    "pilot_group_count": c.pilot_group_count,
                    "ground_support_count": c.ground_support_count,
                    "duty_state": c.duty_state,
                    "fdtl_hours_logged": float(c.fdtl_hours_logged),
                    "rest_required": c.rest_required,
                    "qualification_status": c.qualification_status,
                    "notes": c.notes,
                }
                for c in crews.order_by("crew_ref")
            ],
        }
    )


@require_http_methods(["POST", "PATCH"])
def api_crew_status_update_view(request: HttpRequest, crew_id: str) -> JsonResponse:
    """
    POST / PATCH /api/crew/<crew_id>/status/
    Updates crew duty state and/or crew readiness report status (Section 05.2, 05.5 & 10).
    Scope-isolated:
    - Squadron Leader can only update crew within their assigned squadron.
    - Airbase Commander can review reports and update crew within their airbase.
    - Zonal Commander / unscoped users cannot directly mutate squadron crew.
    """
    try:
        user = _require_auth(request)
        ctx = enforce_query_scope(user, request)
    except PermissionDenied as exc:
        return _json_error(str(exc), status=403)

    crew = CrewReadiness.objects.filter(pk=crew_id).select_related("squadron", "squadron__airbase").first()
    if not crew:
        crew = CrewReadiness.objects.filter(crew_code__iexact=crew_id).select_related("squadron", "squadron__airbase").first()
    if not crew:
        return _json_error("Crew member not found.", status=404)

    # Strict scope isolation checks
    if ctx.is_squadron_leader:
        if crew.squadron.code not in ctx.squadron_codes:
            log_security_denial(
                user=user,
                action="CROSS_SQUADRON_CREW_MUTATE_BLOCKED",
                object_type="CrewReadiness",
                object_id=str(crew.id),
                reason="Squadron leader attempted to mutate crew in another squadron.",
            )
            return _json_error("Forbidden: You cannot modify crew outside your assigned squadron.", status=403)
    elif ctx.is_airbase_commander:
        if crew.squadron.airbase and crew.squadron.airbase.code not in ctx.airbase_codes:
            return _json_error("Forbidden: You cannot modify crew outside your assigned airbase.", status=403)
    elif not user.is_staff:
        log_security_denial(
            user=user,
            action="UNAUTHORIZED_CREW_MUTATION_BLOCKED",
            object_type="CrewReadiness",
            object_id=str(crew.id),
            reason="User role does not allow modifying unit-level crew records.",
        )
        return _json_error("Forbidden: Your role does not allow modifying unit-level crew records.", status=403)

    try:
        data = _parse_body(request)
    except ValidationError as exc:
        return _json_error(str(exc), status=400)

    duty_state = data.get("duty_state")
    report_status = data.get("report_status")
    fdtl_hours = data.get("fdtl_hours")
    notes = data.get("notes")
    reason = data.get("reason", "API crew status update")

    try:
        if duty_state:
            update_crew_duty_state(
                actor=user,
                crew=crew,
                new_state=duty_state,
                fdtl_hours=fdtl_hours,
                reason=reason,
            )
        if report_status:
            transition_crew_report_status(
                actor=user,
                crew=crew,
                new_report_status=report_status,
                notes=notes,
            )
        elif notes is not None and not duty_state:
            crew.notes = notes
            crew.updated_by = user
            crew.updated_at = timezone.now()
            crew.save(update_fields=["notes", "updated_by", "updated_at"])
    except ValidationError as exc:
        return _json_error(str(exc), status=400)
    except PermissionDenied as exc:
        return _json_error(str(exc), status=403)

    crew.refresh_from_db()
    return JsonResponse(
        {
            "status": "success",
            "message": f"Updated crew record {crew.crew_ref}.",
            "crew": {
                "id": str(crew.id),
                "crew_ref": crew.crew_ref,
                "crew_code": crew.crew_code,
                "duty_state": crew.duty_state,
                "report_status": crew.report_status,
                "fdtl_hours_logged": float(crew.fdtl_hours_logged),
                "rest_required": crew.rest_required,
                "qualification_status": crew.qualification_status,
                "notes": crew.notes,
            },
        }
    )

# 5. MAINTENANCE ENDPOINTS (GET/POST /api/maintenance/)
# -------------------------------------------------------------------------
@require_http_methods(["GET", "POST"])
def api_maintenance_view(request: HttpRequest) -> JsonResponse:
    """
    GET /api/maintenance/ — Scope-filtered maintenance board.
    POST /api/maintenance/ — Create maintenance task within authorised scope (Section 10).
    """
    try:
        user = _require_auth(request)
        enforce_query_scope(user, request)
    except PermissionDenied as exc:
        return _json_error(str(exc), status=403)

    if request.method == "GET":
        qs = get_visible_maintenance_tasks(user)
        return JsonResponse(
            {
                "count": qs.count(),
                "results": [
                    {
                        "id": str(m.id),
                        "equipment_code": m.equipment.fictional_code,
                        "airbase_code": m.equipment.airbase.code,
                        "squadron_code": m.equipment.squadron.code if m.equipment.squadron else None,
                        "fault_code": m.fault_code,
                        "severity": m.severity,
                        "status": m.status,
                        "description": m.description,
                        "notes": m.notes,
                        "opened_at": m.opened_at.isoformat(),
                        "due_at": m.due_at.isoformat(),
                    }
                    for m in qs
                ],
            }
        )

    # POST /api/maintenance/
    try:
        data = _parse_body(request)
    except ValidationError as exc:
        return _json_error(str(exc), status=400)

    equip_ref = str(data.get("equipment_id") or data.get("fictional_code") or "").strip()
    equipment = Equipment.objects.filter(fictional_code__iexact=equip_ref).first()
    if not equipment:
        try:
            equipment = Equipment.objects.get(pk=equip_ref)
        except Exception:
            return _json_error("Valid equipment_id or fictional_code is required.", status=404)

    try:
        assert_can_manage_maintenance(user, equipment)
    except PermissionDenied as exc:
        return _json_error(str(exc), status=403)

    now = timezone.now()
    due_at_raw = data.get("due_at")
    due_at = parse_datetime(str(due_at_raw)) if due_at_raw else (now + timezone.timedelta(days=2))
    if not due_at or due_at < now - timezone.timedelta(minutes=5):
        return _json_error("Invalid due_at: due date must not be before opened_at.", status=400)

    fault_code = str(data.get("fault_code", "FLT-GEN-100")).strip()
    description = str(data.get("description", "Routine synthetic inspection task.")).strip()
    severity = str(data.get("severity", MaintenanceTask.Severity.MEDIUM)).upper().strip()
    if severity not in {c[0] for c in MaintenanceTask.Severity.choices}:
        return _json_error(f"Invalid severity '{severity}'.", status=400)

    with transaction.atomic():
        task = MaintenanceTask.objects.create(
            equipment=equipment,
            opened_at=now,
            due_at=due_at,
            severity=severity,
            fault_code=fault_code,
            description=description,
            notes=str(data.get("notes", "")),
            status=MaintenanceTask.TaskStatus.OPEN,
            assigned_to=user,
        )
        AuditLog.objects.create(
            actor=user,
            action="MAINTENANCE_TASK_CREATED",
            object_type="MaintenanceTask",
            object_id=task.fault_code,
            before=None,
            after={
                "equipment": equipment.fictional_code,
                "fault_code": task.fault_code,
                "severity": task.severity,
                "due_at": task.due_at.isoformat(),
            },
            source="api:POST /api/maintenance/",
        )

    return JsonResponse(
        {
            "id": str(task.id),
            "equipment_code": equipment.fictional_code,
            "fault_code": task.fault_code,
            "severity": task.severity,
            "status": task.status,
            "due_at": task.due_at.isoformat(),
        },
        status=201,
    )


# -------------------------------------------------------------------------
# 6. ORDERS & ALERTS ENDPOINTS (GET /api/orders/, POST /api/orders/{id}/acknowledge/)
# -------------------------------------------------------------------------
@require_http_methods(["GET"])
def api_orders_list_view(request: HttpRequest) -> JsonResponse:
    """GET /api/orders/ — Recipient/scope-filtered order inbox (Section 10)."""
    try:
        user = _require_auth(request)
        enforce_query_scope(user, request)
        qs = get_visible_orders(user)
    except PermissionDenied as exc:
        return _json_error(str(exc), status=403)

    return JsonResponse(
        {
            "count": qs.count(),
            "results": [
                {
                    "id": str(o.id),
                    "order_code": o.order_code,
                    "title": o.title,
                    "body": o.body,
                    "issuer": o.issuer.display_name,
                    "recipient_scope": o.recipient_scope,
                    "priority": o.priority,
                    "status": o.status,
                    "issued_at": o.issued_at.isoformat(),
                    "due_at": o.due_at.isoformat(),
                    "acknowledged_by": o.acknowledged_by.display_name if o.acknowledged_by else None,
                    "acknowledged_at": o.acknowledged_at.isoformat() if o.acknowledged_at else None,
                }
                for o in qs
            ],
        }
    )


@require_http_methods(["POST"])
def api_order_acknowledge_view(request: HttpRequest, order_id: str) -> JsonResponse:
    """
    POST /api/orders/{id}/acknowledge/
    Acknowledges an Order (or Alert if matching alert UUID), records AuditLog, and notifies Zonal group (Section 10).
    """
    try:
        user = _require_auth(request)
        enforce_query_scope(user, request)
        data = _parse_body(request)
    except PermissionDenied as exc:
        return _json_error(str(exc), status=403)
    except ValidationError as exc:
        return _json_error(str(exc), status=400)

    target = Order.objects.filter(order_code__iexact=order_id).first()
    if not target:
        try:
            target = Order.objects.filter(pk=order_id).first() or Alert.objects.filter(pk=order_id).first()
        except Exception:
            target = None

    if not target:
        return _json_error(f"Order or Alert '{order_id}' not found.", status=404)

    try:
        updated = acknowledge_order_or_alert(
            actor=user,
            target=target,
            new_status=data.get("status"),
            reason=data.get("reason", "Acknowledged via inbox API."),
        )
    except PermissionDenied as exc:
        return _json_error(str(exc), status=403)
    except ValidationError as exc:
        return _json_error(exc.message if hasattr(exc, "message") else str(exc), status=400)

    if isinstance(updated, Order):
        return JsonResponse(
            {
                "id": str(updated.id),
                "order_code": updated.order_code,
                "status": updated.status,
                "acknowledged_by": user.display_name,
                "acknowledged_at": updated.acknowledged_at.isoformat() if updated.acknowledged_at else None,
            }
        )
    return JsonResponse(
        {
            "id": str(updated.id),
            "title": updated.title,
            "status": updated.status,
            "transition_history": updated.transition_history,
        }
    )


# -------------------------------------------------------------------------
# 7. EVENTS ENDPOINT (GET /api/events/)
# -------------------------------------------------------------------------
@require_http_methods(["GET"])
def api_events_list_view(request: HttpRequest) -> JsonResponse:
    """GET /api/events/ — Scope-filtered recent synthetic events with time range & limit (Section 10)."""
    try:
        user = _require_auth(request)
        enforce_query_scope(user, request)
        qs = get_visible_events(user)
    except PermissionDenied as exc:
        return _json_error(str(exc), status=403)

    since_param = request.GET.get("since")
    if since_param:
        dt = parse_datetime(since_param)
        if dt:
            qs = qs.filter(occurred_at__gte=dt)

    limit = min(int(request.GET.get("limit", 50)), 200)
    events = list(qs[:limit])
    return JsonResponse(
        {
            "count": len(events),
            "results": [
                {
                    "event_id": e.event_id,
                    "scenario_id": e.scenario_id,
                    "source_type": e.source_type,
                    "source_id": e.source_id,
                    "event_type": e.event_type,
                    "occurred_at": e.occurred_at.isoformat(),
                    "received_at": e.received_at.isoformat(),
                    "quality": e.quality,
                    "payload": e.payload,
                }
                for e in events
            ],
        }
    )


# -------------------------------------------------------------------------
# 8. SIMULATION STATUS & CONTROL (GET /api/simulation/status/, POST /api/simulation/control/)
# -------------------------------------------------------------------------
@require_http_methods(["GET"])
def api_simulation_status_view(request: HttpRequest) -> JsonResponse:
    """GET /api/simulation/status/ — Current demo runner state & sensor health (Section 10)."""
    try:
        user = _require_auth(request)
        enforce_query_scope(user, request)
    except PermissionDenied as exc:
        return _json_error(str(exc), status=403)

    run = SimulationRun.objects.select_related("scenario").order_by("-started_at").first()
    sensors = SensorNode.objects.all().order_by("fictional_code")
    tracks = Track.objects.filter(run=run).order_by("fictional_track_code") if run else []

    return JsonResponse(
        {
            "simulation_mode": True,
            "banner": "SYNTHETIC SIMULATION MODE — NON-OPERATIONAL DEMO (SIH26250)",
            "run": (
                {
                    "run_code": run.run_code,
                    "scenario_code": run.scenario.code,
                    "state": run.state,
                    "seed": run.seed,
                    "speed": run.speed,
                    "current_sequence": run.current_sequence,
                    "simulated_clock": run.simulated_clock.isoformat(),
                    "wall_clock": timezone.now().isoformat(),
                    "last_heartbeat_at": run.last_heartbeat_at.isoformat(),
                }
                if run
                else None
            ),
            "sensors": [
                {
                    "fictional_code": s.fictional_code,
                    "name": s.name,
                    "health_state": s.health_state,
                    "last_seen_at": s.last_seen_at.isoformat(),
                }
                for s in sensors
            ],
            "tracks": [
                {
                    "fictional_track_code": t.fictional_track_code,
                    "callsign_label": t.callsign_label,
                    "state": t.state,
                    "quality": t.quality,
                    "bearing": t.bearing,
                    "range_km": t.range_km,
                    "lat": t.last_position.y,
                    "lon": t.last_position.x,
                }
                for t in tracks
            ],
        }
    )


@require_http_methods(["POST"])
def api_simulation_control_view(request: HttpRequest) -> JsonResponse:
    """
    POST /api/simulation/control/
    Start/pause/resume/step/inject_fault/reset demo scenario.
    Restricted strictly to demo-authorised Commander roles; every action is audited (Section 10 & 11).
    """
    try:
        user = _require_auth(request)
        assert_can_control_simulation(user)
        if not check_rate_limit(request, "simulation_control", limit=20, timeout=60, by_user=True):
            return rate_limit_response("Rate limit of 20 simulation control requests per minute exceeded.")
        data = _parse_body(request)
    except PermissionDenied as exc:
        return _json_error(str(exc), status=403)
    except ValidationError as exc:
        return _json_error(str(exc), status=400)

    action = str(data.get("action", "start")).lower().strip()
    scenario_code = str(data.get("scenario_code", "SCENARIO-BASELINE-01"))
    seed = int(data.get("seed", 26250))
    sensor_code = str(data.get("sensor_code", "SENSOR-DEMO-03"))
    fault_state = str(data.get("fault_state", "OFFLINE"))

    engine = HybridRadarEngine(scenario_code=scenario_code, seed=seed)
    try:
        result = engine.control(
            action=action,
            actor=user,
            sensor_code=sensor_code,
            fault_state=fault_state,
        )
    except ValueError as exc:
        return _json_error(str(exc), status=400)

    return JsonResponse(result)


# -------------------------------------------------------------------------
# 9. SUGGESTIONS & HUMAN-IN-THE-LOOP REVIEW (GET /api/suggestions/, POST /api/suggestions/{id}/review/)
# -------------------------------------------------------------------------
@require_http_methods(["GET"])
def api_suggestions_list_view(request: HttpRequest) -> JsonResponse:
    """
    GET /api/suggestions/
    Returns scope-filtered explainable suggestions matching the exact Section 10 response shape,
    plus live option evaluations.
    """
    try:
        user = _require_auth(request)
        ctx = enforce_query_scope(user, request)
        qs = get_visible_suggestions(user)
    except PermissionDenied as exc:
        return _json_error(str(exc), status=403)

    force_fallback = request.GET.get("force_fallback") == "1"
    airbase = Airbase.objects.filter(id__in=ctx.airbase_ids).first()
    live_options = score_operational_options(airbase, force_fallback=force_fallback) if airbase else []

    results = []
    for s in qs:
        model_ver_str = (
            FALLBACK_MODEL_VERSION
            if (s.fallback_used or not s.model_version or force_fallback)
            else s.model_version.model_name
        )
        results.append(
            {
                "id": s.suggestion_code,
                "uuid": str(s.id),
                "kind": s.kind,
                "title": s.title,
                "status": s.status,
                "score": s.score,
                "baseline_score": s.baseline_score,
                "uncertainty": s.uncertainty,
                "model_version": model_ver_str,
                "fallback_used": bool(s.fallback_used or force_fallback),
                "reasons": s.reasons,
                "input_snapshot": s.input_snapshot,
                "data_mode": s.data_mode,
                "disclaimer": "synthetic, advisory only",
                "created_at": s.created_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
        )

    return JsonResponse(
        {
            "count": len(results),
            "results": results,
            "evaluated_options": live_options,
        }
    )


@require_http_methods(["POST"])
def api_suggestion_review_view(request: HttpRequest, suggestion_id: str) -> JsonResponse:
    """
    POST /api/suggestions/{id}/review/
    Records human-in-the-loop decision (accepted / dismissed / review_requested) in AuditLog.
    Intentionally does NOT autonomously execute operational actions (Section 01, 08, 10 & 11).
    """
    try:
        user = _require_auth(request)
        ctx = enforce_query_scope(user, request)
        data = _parse_body(request)
    except PermissionDenied as exc:
        return _json_error(str(exc), status=403)
    except ValidationError as exc:
        return _json_error(str(exc), status=400)

    sugg = Suggestion.objects.filter(suggestion_code__iexact=suggestion_id).first()
    if not sugg:
        try:
            sugg = Suggestion.objects.get(pk=suggestion_id)
        except Exception:
            return _json_error(f"Suggestion '{suggestion_id}' not found.", status=404)

    if sugg.airbase_id and str(sugg.airbase_id) not in ctx.airbase_ids:
        log_security_denial(
            user=user,
            action="UNAUTHORIZED_SUGGESTION_REVIEW",
            object_type="Suggestion",
            object_id=sugg.suggestion_code,
            reason="User attempted to review suggestion outside assigned scope.",
        )
        return _json_error("Forbidden: Suggestion is outside your assigned scope.", status=403)

    decision = str(data.get("decision") or data.get("status") or "accepted").lower().strip()
    decision_map = {
        "accept": Suggestion.SuggestionStatus.ACCEPTED,
        "accepted": Suggestion.SuggestionStatus.ACCEPTED,
        "dismiss": Suggestion.SuggestionStatus.DISMISSED,
        "dismissed": Suggestion.SuggestionStatus.DISMISSED,
        "request_review": Suggestion.SuggestionStatus.REVIEW_REQUESTED,
        "review_requested": Suggestion.SuggestionStatus.REVIEW_REQUESTED,
    }
    if decision not in decision_map:
        return _json_error(
            f"Invalid review decision '{decision}'. Allowed: accept, dismiss, request_review.",
            status=400,
        )

    old_status = sugg.status
    sugg.status = decision_map[decision]
    sugg.reviewed_by = user
    sugg.reviewed_at = timezone.now()
    sugg.review_notes = str(data.get("notes", ""))
    sugg.save()

    AuditLog.objects.create(
        actor=user,
        action="SUGGESTION_HUMAN_REVIEWED",
        object_type="Suggestion",
        object_id=sugg.suggestion_code,
        before={"status": old_status},
        after={
            "status": sugg.status,
            "reviewed_by": user.username,
            "notes": sugg.review_notes,
            "autonomous_execution": False,
        },
        source="api:POST /api/suggestions/{id}/review/",
    )

    return JsonResponse(
        {
            "id": sugg.suggestion_code,
            "kind": sugg.kind,
            "status": sugg.status,
            "score": sugg.score,
            "model_version": sugg.model_version.model_name if sugg.model_version else FALLBACK_MODEL_VERSION,
            "reviewed_by": user.display_name,
            "reviewed_at": sugg.reviewed_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "reasons": sugg.reasons,
            "data_mode": sugg.data_mode,
            "notice": "Human review decision recorded in AuditLog. No unsupervised operational action executed.",
        }
    )


# -------------------------------------------------------------------------
# 10. VARIANT C COMMANDER OVERRIDE ENDPOINT (POST /api/commander/override/)
# -------------------------------------------------------------------------
@require_http_methods(["POST"])
def api_commander_override_view(request: HttpRequest) -> JsonResponse:
    """
    POST /api/commander/override/
    Processes Variant C 'Crew Status Entry' and 'Infrastructure Limits / Input Forms' actions
    for the Airbase Commander with full audit logging.
    """
    try:
        user = _require_auth(request)
        enforce_query_scope(user, request)
        data = _parse_body(request)
    except PermissionDenied as exc:
        return _json_error(str(exc), status=403)
    except ValidationError as exc:
        return _json_error(str(exc), status=400)

    airbase_code = str(data.get("airbase_code", "AB-DEMO-01")).upper().strip()
    airbase = get_object_or_404(Airbase, code=airbase_code)

    try:
        res = override_fdtl_or_infrastructure(
            actor=user,
            airbase=airbase,
            form_mode=str(data.get("form_mode", "runway_status")),
            crew_payload=data.get("crew_payload"),
            infrastructure_payload=data.get("infrastructure_payload"),
            reason=str(data.get("reason", "Commander update from Variant C console.")),
        )
    except PermissionDenied as exc:
        return _json_error(str(exc), status=403)
    except ValidationError as exc:
        return _json_error(exc.message if hasattr(exc, "message") else str(exc), status=400)

    return JsonResponse({"status": "ok", "result": res})


# -------------------------------------------------------------------------
# 11. ADMINISTRATIVE ROLE ASSIGNMENT APPROVAL & REVIEW ENDPOINTS
# -------------------------------------------------------------------------
@require_http_methods(["GET"])
def api_role_assignments_list_view(request: HttpRequest) -> JsonResponse:
    """
    GET /api/admin/role-assignments/
    Lists RoleAssignments. Restricted to staff/superusers.
    Supports filtering by ?status=PENDING / ACTIVE / REVOKED.
    """
    user = _require_auth(request)
    if not (user.is_staff or user.is_superuser):
        log_security_denial(
            user=user,
            action="ROLE_ASSIGNMENTS_LIST_FORBIDDEN",
            object_type="RoleAssignment",
            object_id="LIST",
            reason="Non-staff user attempted to view administrative role assignments.",
            source="api:GET /api/admin/role-assignments/",
        )
        return _json_error("Forbidden: Administrative privilege required.", status=403)

    qs = RoleAssignment.objects.select_related("user", "airbase", "squadron", "zone").all().order_by("-id")
    status_filter = request.GET.get("status")
    if status_filter:
        qs = qs.filter(status=status_filter.upper().strip())

    results = [
        {
            "id": str(a.id),
            "user": a.user.username,
            "display_name": a.user.display_name,
            "role": a.role,
            "status": a.status,
            "airbase": a.airbase.code if a.airbase else None,
            "squadron": a.squadron.code if a.squadron else None,
            "zone": a.zone.code if a.zone else None,
            "can_control_simulation": a.can_control_simulation,
            "granted_by": a.granted_by.username if a.granted_by else None,
        }
        for a in qs
    ]
    return JsonResponse({"count": len(results), "results": results})


@require_http_methods(["POST"])
def api_role_assignment_review_view(request: HttpRequest, assignment_id: str) -> JsonResponse:
    """
    POST /api/admin/role-assignments/{id}/review/
    Allows administrative review (approve / reject / assign scope) of a RoleAssignment.
    Only users with is_staff or is_superuser can perform this action.
    Audits role and scope changes before/after to AuditLog.
    """
    user = _require_auth(request)
    if not (user.is_staff or user.is_superuser):
        log_security_denial(
            user=user,
            action="ROLE_ASSIGNMENT_REVIEW_FORBIDDEN",
            object_type="RoleAssignment",
            object_id=str(assignment_id),
            reason="Only staff/administrators can approve or modify RoleAssignments.",
            source="api:POST /api/admin/role-assignments/review/",
        )
        return _json_error("Forbidden: Administrative privilege required.", status=403)

    try:
        data = _parse_body(request)
    except ValidationError as exc:
        return _json_error(str(exc), status=400)

    assignment = get_object_or_404(RoleAssignment, id=assignment_id)
    new_status = str(data.get("status", "ACTIVE")).upper().strip()
    valid_statuses = {c[0] for c in RoleAssignment.AssignmentStatus.choices}
    if new_status not in valid_statuses:
        return _json_error(f"Invalid status '{new_status}'. Allowed: {sorted(valid_statuses)}", status=400)

    before_state = {
        "status": assignment.status,
        "role": assignment.role,
        "airbase": assignment.airbase.code if assignment.airbase else None,
        "squadron": assignment.squadron.code if assignment.squadron else None,
        "zone": assignment.zone.code if assignment.zone else None,
        "can_control_simulation": assignment.can_control_simulation,
    }

    with transaction.atomic():
        assignment.status = new_status
        if "airbase_code" in data:
            ab_code = data["airbase_code"]
            assignment.airbase = Airbase.objects.filter(code=ab_code).first() if ab_code else None
        if "squadron_code" in data:
            sq_code = data["squadron_code"]
            assignment.squadron = Squadron.objects.filter(code=sq_code).first() if sq_code else None
        if "zone_code" in data:
            z_code = data["zone_code"]
            assignment.zone = Zone.objects.filter(code=z_code).first() if z_code else None
        if "can_control_simulation" in data:
            assignment.can_control_simulation = bool(data["can_control_simulation"])
        if "role" in data and data["role"] in {c[0] for c in DesignationChoices.choices}:
            assignment.role = data["role"]

        assignment.granted_by = user
        assignment.save()

        after_state = {
            "status": assignment.status,
            "role": assignment.role,
            "airbase": assignment.airbase.code if assignment.airbase else None,
            "squadron": assignment.squadron.code if assignment.squadron else None,
            "zone": assignment.zone.code if assignment.zone else None,
            "can_control_simulation": assignment.can_control_simulation,
        }

        AuditLog.objects.create(
            actor=user,
            action="ROLE_ASSIGNMENT_REVIEWED_AND_UPDATED",
            object_type="RoleAssignment",
            object_id=str(assignment.id),
            before=before_state,
            after=after_state,
            source="api:POST /api/admin/role-assignments/review/",
        )

    return JsonResponse({
        "status": "ok",
        "assignment_id": str(assignment.id),
        "user": assignment.user.username,
        "before": before_state,
        "after": after_state,
    })


@require_http_methods(["GET"])
def api_health_check_view(request: HttpRequest) -> JsonResponse:
    """
    GET /health/ or /health
    Health check endpoint returning {status, db, redis, simulation} (Section 15/16 Demo runbook).
    Publicly accessible so operators and health checkers can verify stack status before speaking.
    """
    from django.db import connection
    from channels.layers import get_channel_layer
    from apps.radar_simulation.models import SimulationRun

    db_status = "ok"
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except Exception as exc:
        db_status = f"unhealthy: {exc}"

    redis_status = "ok"
    try:
        channel_layer = get_channel_layer()
        if channel_layer is None:
            redis_status = "unavailable"
    except Exception as exc:
        redis_status = f"unhealthy: {exc}"

    sim_status = "ready"
    try:
        run = SimulationRun.objects.order_by("-started_at").first()
        if run:
            sim_status = f"ready ({run.state})"
        else:
            sim_status = "ready (idle)"
    except Exception as exc:
        sim_status = f"unhealthy: {exc}"

    is_healthy = (
        db_status == "ok"
        and not redis_status.startswith("unhealthy")
        and not sim_status.startswith("unhealthy")
    )

    return JsonResponse(
        {
            "status": "ok" if is_healthy else "unhealthy",
            "db": db_status,
            "redis": redis_status,
            "simulation": sim_status,
        },
        status=200 if is_healthy else 503,
    )

