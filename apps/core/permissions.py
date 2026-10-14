"""
Central Object-Level Permission & Scope Isolation Service for AERO-OPS (SIH26250).
Implements Section 04 (Role capability matrix) and Section 11 (Security, privacy & audit).
"""
from dataclasses import dataclass, field
from typing import Optional, Set
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest

from apps.core.models import (
    Airbase,
    Alert,
    AuditLog,
    CrewReadiness,
    DesignationChoices,
    Equipment,
    MaintenanceTask,
    Order,
    RoleAssignment,
    Squadron,
    User,
    Zone,
)


@dataclass
class UserScopeContext:
    """Resolved server-side authority and object-level scope for an authenticated User."""

    user: User
    roles: Set[str] = field(default_factory=set)
    zone_ids: Set[str] = field(default_factory=set)
    zone_codes: Set[str] = field(default_factory=set)
    airbase_ids: Set[str] = field(default_factory=set)
    airbase_codes: Set[str] = field(default_factory=set)
    squadron_ids: Set[str] = field(default_factory=set)
    squadron_codes: Set[str] = field(default_factory=set)
    can_control_simulation: bool = False
    primary_assignment: Optional[RoleAssignment] = None
    primary_airbase: Optional[Airbase] = None
    primary_squadron: Optional[Squadron] = None
    primary_zone: Optional[Zone] = None

    @property
    def is_zonal_commander(self) -> bool:
        return DesignationChoices.ZONAL_COMMANDER in self.roles

    @property
    def is_airbase_commander(self) -> bool:
        return DesignationChoices.AIRBASE_COMMANDER in self.roles

    @property
    def is_squadron_leader(self) -> bool:
        return DesignationChoices.SQUADRON_LEADER in self.roles

    @property
    def primary_role(self) -> Optional[str]:
        for r in (
            DesignationChoices.ZONAL_COMMANDER,
            DesignationChoices.AIRBASE_COMMANDER,
            DesignationChoices.SQUADRON_LEADER,
        ):
            if r in self.roles:
                return r
        return None

    @property
    def assigned_airbase_code(self) -> Optional[str]:
        if self.primary_airbase:
            return self.primary_airbase.code
        return next(iter(self.airbase_codes), None)

    @property
    def assigned_airbase_name(self) -> Optional[str]:
        if self.primary_airbase:
            return self.primary_airbase.name
        return None

    @property
    def assigned_squadron_code(self) -> Optional[str]:
        if self.primary_squadron:
            return self.primary_squadron.code
        return next(iter(self.squadron_codes), None)

    @property
    def assigned_squadron_name(self) -> Optional[str]:
        if self.primary_squadron:
            return self.primary_squadron.name
        return None

    @property
    def assigned_zone_code(self) -> Optional[str]:
        if self.primary_zone:
            return self.primary_zone.code
        return next(iter(self.zone_codes), None)

    @property
    def assigned_zone_name(self) -> Optional[str]:
        if self.primary_zone:
            return self.primary_zone.name
        return None

    @property
    def role_label(self) -> str:
        if self.is_zonal_commander:
            return "Zonal Commander"
        elif self.is_airbase_commander:
            return "Airbase Commander"
        elif self.is_squadron_leader:
            return "Squadron Leader"
        return "Authorised Officer"

    @property
    def location_label(self) -> str:
        if self.is_zonal_commander:
            if self.primary_zone:
                return f"{self.primary_zone.name} ({self.primary_zone.code})"
            return "Northern Sector Airspace (ZONE-DEMO-A)"
        elif self.is_airbase_commander:
            if self.primary_airbase:
                return f"{self.primary_airbase.name} ({self.primary_airbase.code})"
            return "Forward Air Base"
        elif self.is_squadron_leader:
            sq_part = f"{self.primary_squadron.name} ({self.primary_squadron.code})" if self.primary_squadron else "Assigned Squadron"
            ab_part = f" · {self.primary_airbase.name} ({self.primary_airbase.code})" if self.primary_airbase else ""
            return f"{sq_part}{ab_part}"
        return "Unassigned Scope"


def log_security_denial(
    user: Optional[User],
    action: str,
    object_type: str,
    object_id: str,
    reason: str,
    source: str = "rbac_guard",
) -> None:
    """Record failed privileged actions or cross-scope tampering attempts in AuditLog (Section 04 & 11)."""
    actor = user if (user and getattr(user, "is_authenticated", False)) else None
    AuditLog.objects.create(
        actor=actor,
        action=action,
        object_type=object_type,
        object_id=str(object_id)[:64],
        before=None,
        after={"denied": True, "reason": reason},
        source=source,
    )


def get_user_scope(user: User) -> UserScopeContext:
    """
    Build authoritative UserScopeContext from active RoleAssignments.
    Self-selected designation on User never grants access without an ACTIVE RoleAssignment (Section 04).
    """
    if not user or not user.is_authenticated or not user.active:
        raise PermissionDenied("Authentication required.")

    ctx = UserScopeContext(user=user)
    assignments = (
        RoleAssignment.objects.filter(
            user=user,
            status=RoleAssignment.AssignmentStatus.ACTIVE,
        )
        .select_related("zone", "airbase", "airbase__zone", "squadron", "squadron__airbase")
    )

    for assignment in assignments:
        ctx.roles.add(assignment.role)
        if ctx.primary_assignment is None:
            ctx.primary_assignment = assignment

        if assignment.can_control_simulation:
            ctx.can_control_simulation = True

        if assignment.role == DesignationChoices.ZONAL_COMMANDER and assignment.zone:
            if ctx.primary_zone is None:
                ctx.primary_zone = assignment.zone
            ctx.zone_ids.add(str(assignment.zone.id))
            ctx.zone_codes.add(assignment.zone.code)
            for ab in Airbase.objects.filter(zone=assignment.zone).prefetch_related("squadrons"):
                ctx.airbase_ids.add(str(ab.id))
                ctx.airbase_codes.add(ab.code)
                for sq in ab.squadrons.all():
                    ctx.squadron_ids.add(str(sq.id))
                    ctx.squadron_codes.add(sq.code)

        elif assignment.role == DesignationChoices.AIRBASE_COMMANDER and assignment.airbase:
            ab = assignment.airbase
            if ctx.primary_airbase is None:
                ctx.primary_airbase = ab
            if ab.zone and ctx.primary_zone is None:
                ctx.primary_zone = ab.zone
            ctx.airbase_ids.add(str(ab.id))
            ctx.airbase_codes.add(ab.code)
            if ab.zone_id:
                ctx.zone_ids.add(str(ab.zone_id))
                ctx.zone_codes.add(ab.zone.code)
            for sq in Squadron.objects.filter(airbase=ab):
                ctx.squadron_ids.add(str(sq.id))
                ctx.squadron_codes.add(sq.code)

        elif assignment.role == DesignationChoices.SQUADRON_LEADER and assignment.squadron:
            sq = assignment.squadron
            if ctx.primary_squadron is None:
                ctx.primary_squadron = sq
            if sq.airbase and ctx.primary_airbase is None:
                ctx.primary_airbase = sq.airbase
            ctx.squadron_ids.add(str(sq.id))
            ctx.squadron_codes.add(sq.code)
            if sq.airbase_id:
                ctx.airbase_ids.add(str(sq.airbase_id))
                ctx.airbase_codes.add(sq.airbase.code)

    return ctx


def enforce_query_scope(user: User, request: HttpRequest) -> UserScopeContext:
    """
    Inspect URL query parameters and payload scope filters (?airbase_id=, ?squadron_id=, ?zone_id=).
    If a user attempts to query an out-of-scope airbase, squadron, or zone (including numeric IDs like ?airbase_id=2),
    log the violation and raise 403 PermissionDenied immediately (Section 02, 04, 11 & 14).
    """
    ctx = get_user_scope(user)

    airbase_param = request.GET.get("airbase_id") or request.GET.get("airbase")
    if airbase_param:
        param_str = str(airbase_param).strip()
        # Check if it matches an allowed UUID or code
        if param_str not in ctx.airbase_ids and param_str not in ctx.airbase_codes:
            log_security_denial(
                user=user,
                action="CROSS_SCOPE_QUERY_BLOCKED",
                object_type="Airbase",
                object_id=param_str,
                reason=f"User {user.username} attempted out-of-scope airbase query: {param_str}",
            )
            raise PermissionDenied("Forbidden: Requested airbase_id is outside your authorised scope.")
        # Even for Squadron Leader, cross-squadron airbase-wide queries are restricted if not scoped
        if ctx.is_squadron_leader and not (ctx.is_airbase_commander or ctx.is_zonal_commander):
            # Squadron leader may only query their own parent airbase if permitted, never another airbase
            pass

    squadron_param = request.GET.get("squadron_id") or request.GET.get("squadron")
    if squadron_param:
        param_str = str(squadron_param).strip()
        if param_str not in ctx.squadron_ids and param_str not in ctx.squadron_codes:
            log_security_denial(
                user=user,
                action="CROSS_SCOPE_QUERY_BLOCKED",
                object_type="Squadron",
                object_id=param_str,
                reason=f"User {user.username} attempted out-of-scope squadron query: {param_str}",
            )
            raise PermissionDenied("Forbidden: Requested squadron_id is outside your authorised scope.")

    zone_param = request.GET.get("zone_id") or request.GET.get("zone")
    if zone_param:
        param_str = str(zone_param).strip()
        if ctx.is_squadron_leader and not (ctx.is_airbase_commander or ctx.is_zonal_commander):
            log_security_denial(
                user=user,
                action="CROSS_SCOPE_QUERY_BLOCKED",
                object_type="Zone",
                object_id=param_str,
                reason="Squadron Leader is not permitted to query zone-level summaries.",
            )
            raise PermissionDenied("Forbidden: Squadron Leaders do not have zone-wide access.")
        if param_str not in ctx.zone_ids and param_str not in ctx.zone_codes:
            log_security_denial(
                user=user,
                action="CROSS_SCOPE_QUERY_BLOCKED",
                object_type="Zone",
                object_id=param_str,
                reason=f"User {user.username} attempted out-of-scope zone query: {param_str}",
            )
            raise PermissionDenied("Forbidden: Requested zone_id is outside your authorised scope.")

    return ctx


def assert_can_view_airbase(user: User, airbase: Airbase) -> UserScopeContext:
    ctx = get_user_scope(user)
    if str(airbase.id) not in ctx.airbase_ids and airbase.code not in ctx.airbase_codes:
        log_security_denial(
            user=user,
            action="UNAUTHORIZED_AIRBASE_READ",
            object_type="Airbase",
            object_id=airbase.code,
            reason="Airbase not in user's active scope.",
        )
        raise PermissionDenied(f"Forbidden: No access to airbase {airbase.code}.")
    return ctx


def assert_can_mutate_airbase(user: User, airbase: Optional[Airbase] = None) -> UserScopeContext:
    """
    Section 04 Role Matrix: Only Airbase Commander (within scope) can register/edit airbase structure.
    Zonal Commander has Read/oversight; Squadron Leader has No access.
    """
    ctx = get_user_scope(user)
    if not ctx.is_airbase_commander:
        log_security_denial(
            user=user,
            action="UNAUTHORIZED_AIRBASE_MUTATION",
            object_type="Airbase",
            object_id=airbase.code if airbase else "NEW",
            reason=f"Role {ctx.primary_role} cannot mutate airbase structure.",
        )
        raise PermissionDenied("Forbidden: Only an authorised Airbase Commander may modify airbase structure.")

    if airbase and (str(airbase.id) not in ctx.airbase_ids and airbase.code not in ctx.airbase_codes):
        log_security_denial(
            user=user,
            action="CROSS_SCOPE_AIRBASE_MUTATION",
            object_type="Airbase",
            object_id=airbase.code,
            reason="Airbase Commander attempted to mutate another airbase.",
        )
        raise PermissionDenied(f"Forbidden: Airbase {airbase.code} is outside your assigned command scope.")
    return ctx


def assert_can_update_equipment(user: User, equipment: Equipment) -> UserScopeContext:
    """
    Section 04 Role Matrix:
    - Airbase Commander: Review/override with audit within assigned airbase.
    - Squadron Leader: Assigned squadron only.
    - Zonal Commander: Read/oversight only (cannot mutate equipment state directly).
    """
    ctx = get_user_scope(user)
    if ctx.is_airbase_commander and str(equipment.airbase_id) in ctx.airbase_ids:
        return ctx
    if (
        ctx.is_squadron_leader
        and equipment.squadron_id
        and str(equipment.squadron_id) in ctx.squadron_ids
    ):
        return ctx

    log_security_denial(
        user=user,
        action="UNAUTHORIZED_EQUIPMENT_UPDATE",
        object_type="Equipment",
        object_id=equipment.fictional_code,
        reason=f"User {user.username} ({ctx.primary_role}) lacks write scope for {equipment.fictional_code}.",
    )
    raise PermissionDenied(
        f"Forbidden: You do not have permission to update equipment {equipment.fictional_code}."
    )


def assert_can_manage_maintenance(user: User, equipment: Equipment) -> UserScopeContext:
    """
    Section 04 Role Matrix:
    - Airbase Commander: View/manage within airbase.
    - Squadron Leader: Update assigned equipment reports.
    - Zonal Commander: Aggregated readiness read-only.
    """
    return assert_can_update_equipment(user, equipment)


def assert_can_update_crew(user: User, squadron: Squadron) -> UserScopeContext:
    """
    Section 04 Role Matrix:
    - Airbase Commander: Airbase-wide view; authorised edits.
    - Squadron Leader: Assigned squadron scope.
    - Zonal Commander: Aggregated view only.
    """
    ctx = get_user_scope(user)
    if ctx.is_airbase_commander and str(squadron.airbase_id) in ctx.airbase_ids:
        return ctx
    if ctx.is_squadron_leader and str(squadron.id) in ctx.squadron_ids:
        return ctx

    log_security_denial(
        user=user,
        action="UNAUTHORIZED_CREW_UPDATE",
        object_type="Squadron",
        object_id=squadron.code,
        reason="User lacks authority to mutate crew readiness for this squadron.",
    )
    raise PermissionDenied(f"Forbidden: Cannot modify crew readiness for {squadron.code}.")


def assert_can_acknowledge_order(user: User, order: Order) -> UserScopeContext:
    """
    Section 04 & 10: Recipient (Squadron Leader / Airbase Commander in scope) or authorised supervisor.
    """
    ctx = get_user_scope(user)
    in_scope = (
        order.recipient_scope in ctx.squadron_codes
        or order.recipient_scope in ctx.airbase_codes
        or order.recipient_scope in ctx.zone_codes
        or (order.target_squadron_id and str(order.target_squadron_id) in ctx.squadron_ids)
        or (order.target_airbase_id and str(order.target_airbase_id) in ctx.airbase_ids)
        or (order.target_zone_id and str(order.target_zone_id) in ctx.zone_ids)
    )
    if not in_scope:
        log_security_denial(
            user=user,
            action="UNAUTHORIZED_ORDER_ACK",
            object_type="Order",
            object_id=order.order_code,
            reason=f"User {user.username} is outside recipient scope {order.recipient_scope}.",
        )
        raise PermissionDenied(f"Forbidden: Order {order.order_code} is outside your assigned scope.")
    return ctx


def assert_can_acknowledge_alert(user: User, alert: Alert) -> UserScopeContext:
    ctx = get_user_scope(user)
    in_scope = (
        (alert.airbase_id and str(alert.airbase_id) in ctx.airbase_ids)
        or (alert.zone_id and str(alert.zone_id) in ctx.zone_ids)
    )
    if not in_scope:
        log_security_denial(
            user=user,
            action="UNAUTHORIZED_ALERT_ACK",
            object_type="Alert",
            object_id=str(alert.id),
            reason="User attempted to transition an alert outside their assigned scope.",
        )
        raise PermissionDenied("Forbidden: Alert is outside your assigned scope.")
    return ctx


def assert_can_control_simulation(user: User) -> UserScopeContext:
    """
    Section 04 Role Matrix: Demo-only permission if enabled on Airbase Commander or Zonal Commander.
    Squadron Leader is strictly prohibited.
    """
    ctx = get_user_scope(user)
    if not ctx.can_control_simulation or ctx.is_squadron_leader:
        log_security_denial(
            user=user,
            action="UNAUTHORIZED_SIMULATION_CONTROL",
            object_type="Scenario",
            object_id="SIM_RUNNER",
            reason=f"User {user.username} ({ctx.primary_role}) attempted simulation control without permission.",
        )
        raise PermissionDenied("Forbidden: Simulation control requires demo-authorised Commander privileges.")
    return ctx


def get_authorised_ws_groups(user: User) -> Set[str]:
    """
    Derive canonical Django Channels group names strictly on the server (Section 07, 10 & 11).
    Never trust a client-supplied group name.
    """
    ctx = get_user_scope(user)
    groups: Set[str] = set()
    for z_code in ctx.zone_codes:
        if not ctx.is_squadron_leader or ctx.is_airbase_commander or ctx.is_zonal_commander:
            groups.add(f"zone_{z_code}")
    for ab_code in ctx.airbase_codes:
        groups.add(f"airbase_{ab_code}")
    for sq_code in ctx.squadron_codes:
        groups.add(f"squadron_{sq_code}")
    return groups
