"""
Validation forms for AERO-OPS registration, Variant C Crew Status Entry,
and Infrastructure Limits / Input Forms (Section 04, 05 & 11).
"""
from django import forms
from apps.core.models import Airbase, DesignationChoices, Equipment, MaintenanceTask


class RegistrationForm(forms.Form):
    username = forms.CharField(max_length=64)
    email = forms.EmailField()
    password = forms.CharField(min_length=8, widget=forms.PasswordInput)
    display_name = forms.CharField(max_length=120)
    requested_designation = forms.ChoiceField(choices=DesignationChoices.choices)
    requested_scope_code = forms.CharField(max_length=64, required=False)


class EquipmentStatusUpdateForm(forms.Form):
    status = forms.ChoiceField(choices=Equipment.EquipmentStatus.choices)
    readiness_state = forms.ChoiceField(choices=Equipment.ReadinessState.choices, required=False)
    notes = forms.CharField(required=False, widget=forms.Textarea)


class MaintenanceTaskForm(forms.Form):
    equipment_id = forms.CharField(max_length=64)
    due_at = forms.DateTimeField()
    severity = forms.ChoiceField(choices=MaintenanceTask.Severity.choices)
    fault_code = forms.CharField(max_length=48)
    description = forms.CharField(widget=forms.Textarea)
    notes = forms.CharField(required=False, widget=forms.Textarea)


class VariantCCommanderOverrideForm(forms.Form):
    """Validates Variant C 'Crew Status Entry' and 'Infrastructure Limits / Input Forms'."""

    INPUT_FORM_CHOICES = [
        ("air_unmanned", "Air Unmanned"),
        ("runway_status", "Runway Status"),
        ("runway_request", "Runway Request"),
        ("resource_allotment", "Resource Allotment"),
    ]

    airbase_code = forms.CharField(max_length=32, initial="AB-DEMO-01")
    form_mode = forms.ChoiceField(choices=INPUT_FORM_CHOICES, initial="runway_status", required=False)
    runway_required = forms.CharField(max_length=32, required=False)
    crew_name = forms.CharField(max_length=120, required=False)
    first_name = forms.CharField(max_length=64, required=False)
    last_name = forms.CharField(max_length=64, required=False)
    crew_code = forms.CharField(max_length=32, required=False)
    fdtl_hours_logged = forms.DecimalField(max_digits=5, decimal_places=2, required=False)
    rest_required = forms.BooleanField(required=False)
    fuel_reserves_mt = forms.DecimalField(max_digits=8, decimal_places=2, required=False)
    runway_primary_status = forms.ChoiceField(choices=Airbase.RunwayStatus.choices, required=False)
    runway_secondary_status = forms.ChoiceField(choices=Airbase.RunwayStatus.choices, required=False)
    arrestor_gear_status = forms.ChoiceField(choices=Airbase.ArrestorGearStatus.choices, required=False)
