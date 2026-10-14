"""
URL configuration for AERO-OPS Core Portal Views & Section 10 REST APIs.
Includes the Variant C screenshot URL alias (/acommarcatosn) alongside standard routes.
"""
from django.urls import path
from apps.core import portal_views, views

urlpatterns = [
    # Variant C NIC/GovTech Portal Pages
    path("", portal_views.commander_dashboard_page, name="commander_dashboard"),
    path("acommarcatosn", portal_views.commander_dashboard_page, name="variant_c_alias"),
    path("acommarcatosn/", portal_views.commander_dashboard_page, name="variant_c_alias_slash"),
    path("commander/", portal_views.commander_dashboard_page, name="commander_dashboard_explicit"),
    path("squadron/", portal_views.squadron_dashboard_page, name="squadron_dashboard"),
    path("zonal/", portal_views.zonal_dashboard_page, name="zonal_dashboard"),
    path("login/", portal_views.portal_login_page, name="portal_login"),
    path("switch-role/", portal_views.portal_switch_role_view, name="portal_switch_role"),
    # Authentication & Registration APIs
    path("auth/register/", views.auth_register_view, name="auth_register"),
    path("auth/login/", views.auth_login_view, name="auth_login"),
    path("auth/logout/", views.auth_logout_view, name="auth_logout"),
    # Section 10 REST API Contract (16 Endpoints)
    path("api/me/", views.api_me_view, name="api_me"),
    path("api/dashboard/summary/", views.api_dashboard_summary_view, name="api_dashboard_summary"),
    path("api/airbases/", views.api_airbases_view, name="api_airbases"),
    path("api/equipment/", views.api_equipment_list_view, name="api_equipment_list"),
    path(
        "api/equipment/<str:equipment_id>/status/",
        views.api_equipment_status_update_view,
        name="api_equipment_status_update",
    ),
    path("api/crew/", views.api_crew_list_view, name="api_crew_list"),
    path(
        "api/crew/<str:crew_id>/status/",
        views.api_crew_status_update_view,
        name="api_crew_status_update",
    ),
    path("api/maintenance/", views.api_maintenance_view, name="api_maintenance"),
    path("api/orders/", views.api_orders_list_view, name="api_orders_list"),
    path(
        "api/orders/<str:order_id>/acknowledge/",
        views.api_order_acknowledge_view,
        name="api_order_acknowledge",
    ),
    path("api/events/", views.api_events_list_view, name="api_events_list"),
    path("api/simulation/status/", views.api_simulation_status_view, name="api_simulation_status"),
    path("api/simulation/control/", views.api_simulation_control_view, name="api_simulation_control"),
    path("api/suggestions/", views.api_suggestions_list_view, name="api_suggestions_list"),
    path(
        "api/suggestions/<str:suggestion_id>/review/",
        views.api_suggestion_review_view,
        name="api_suggestion_review",
    ),
    # Variant C Commander Console Override Endpoint
    path("api/commander/override/", views.api_commander_override_view, name="api_commander_override"),
    # Administrative Role Assignment Review & Scope Assignment Endpoints (Section 04 & 11)
    path("api/admin/role-assignments/", views.api_role_assignments_list_view, name="api_admin_role_assignments_list"),
    path(
        "api/admin/role-assignments/<uuid:assignment_id>/review/",
        views.api_role_assignment_review_view,
        name="api_admin_role_assignment_review",
    ),
]
