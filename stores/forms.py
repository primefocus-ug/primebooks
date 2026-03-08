# ---------------------------------------------------------------------------
# forms.py — consolidated, deduplicated, all bugs fixed
# ---------------------------------------------------------------------------
# FIX: Removed all duplicate imports. Each module imported exactly once.
import json
from datetime import datetime, timedelta

from django import forms
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Fieldset, Row, Column, Field, HTML, Submit

from accounts.models import CustomUser
from .models import Store, StoreAccess, StoreOperatingHours, StoreDevice


# ---------------------------------------------------------------------------
# StoreStaffAssignmentForm
# ---------------------------------------------------------------------------

class StoreStaffAssignmentForm(forms.Form):
    """Form for assigning staff to stores with access control."""

    access_level = forms.ChoiceField(
        choices=StoreAccess.ACCESS_LEVELS,
        initial="staff",
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
        label=_("Access Level for New Staff"),
        help_text=_("Select the access level for newly added staff members"),
    )
    can_view_sales = forms.BooleanField(
        required=False, initial=True,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
        label=_("Can View Sales"),
    )
    can_create_sales = forms.BooleanField(
        required=False, initial=True,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
        label=_("Can Create Sales"),
    )
    can_view_inventory = forms.BooleanField(
        required=False, initial=True,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
        label=_("Can View Inventory"),
    )
    can_manage_inventory = forms.BooleanField(
        required=False, initial=False,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
        label=_("Can Manage Inventory"),
    )
    can_view_reports = forms.BooleanField(
        required=False, initial=False,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
        label=_("Can View Reports"),
    )
    can_fiscalize = forms.BooleanField(
        required=False, initial=False,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
        label=_("Can Fiscalize Invoices"),
    )
    can_manage_staff = forms.BooleanField(
        required=False, initial=False,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
        label=_("Can Manage Staff"),
    )

    def __init__(self, store_instance=None, user=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.store = store_instance
        self.current_user = user

        # FIX: add_staff / remove_staff are conditionally built; clean() checks
        # for their presence before operating on them, so a missing user/store
        # no longer causes a silent empty-queryset path or an AttributeError.
        if store_instance and user:
            manageable_users = user.get_manageable_users()

            current_staff_ids = store_instance.staff.filter(
                is_hidden=False
            ).values_list("id", flat=True)

            available_users = manageable_users.filter(
                company=store_instance.company,
                is_active=True,
            ).exclude(id__in=current_staff_ids)

            staff_choices = [
                (u.id, f"{u.get_full_name()} ({u.email}) - {u.display_role}")
                for u in available_users
            ]
            self.fields["add_staff"] = forms.MultipleChoiceField(
                choices=staff_choices,
                required=False,
                widget=forms.SelectMultiple(attrs={"class": "form-select", "size": "10"}),
                label=_("Add Staff Members"),
                help_text=_("Select users to add to this store"),
            )

            current_staff = store_instance.staff.filter(is_hidden=False, is_active=True)
            removable_staff = [s for s in current_staff if user.can_manage_user(s)]
            remove_choices = [
                (s.id, f"{s.get_full_name()} ({s.email}) - {s.display_role}")
                for s in removable_staff
            ]
            self.fields["remove_staff"] = forms.MultipleChoiceField(
                choices=remove_choices,
                required=False,
                widget=forms.SelectMultiple(attrs={"class": "form-select", "size": "10"}),
                label=_("Remove Staff Members"),
                help_text=_("Select users to remove from this store"),
            )

        self.helper = FormHelper()
        self.helper.form_method = "post"
        self.helper.layout = Layout(
            Fieldset(
                "Add Staff Members",
                Field("add_staff"),
                HTML("<hr>"),
                "access_level",
                HTML('<div class="row">'),
                Column("can_view_sales", css_class="col-md-6"),
                Column("can_create_sales", css_class="col-md-6"),
                HTML("</div>"),
                HTML('<div class="row">'),
                Column("can_view_inventory", css_class="col-md-6"),
                Column("can_manage_inventory", css_class="col-md-6"),
                HTML("</div>"),
                HTML('<div class="row">'),
                Column("can_view_reports", css_class="col-md-6"),
                Column("can_fiscalize", css_class="col-md-6"),
                HTML("</div>"),
                Field("can_manage_staff"),
            ),
            HTML("<hr>"),
            Fieldset(
                "Remove Staff Members",
                Field("remove_staff"),
            ),
            Submit("submit", "Update Staff Assignments", css_class="btn btn-primary"),
        )

    def clean(self):
        cleaned_data = super().clean()

        # FIX: Only process add_staff / remove_staff if those fields were
        # actually created (i.e. the form was initialised with store + user).
        try:
            add_ids = cleaned_data.get("add_staff", [])
            if add_ids:
                cleaned_data["add_staff"] = CustomUser.objects.filter(
                    id__in=[int(i) for i in add_ids if i]
                )
            else:
                cleaned_data["add_staff"] = CustomUser.objects.none()

            remove_ids = cleaned_data.get("remove_staff", [])
            if remove_ids:
                cleaned_data["remove_staff"] = CustomUser.objects.filter(
                    id__in=[int(i) for i in remove_ids if i]
                )
            else:
                cleaned_data["remove_staff"] = CustomUser.objects.none()

        except (ValueError, TypeError):
            raise forms.ValidationError(_("Invalid user selection"))

        access_level = cleaned_data.get("access_level", "staff")
        if access_level == "view":
            if cleaned_data.get("can_create_sales") or cleaned_data.get("can_manage_inventory"):
                self.add_error(
                    "access_level",
                    _("View-only access cannot have create or manage permissions"),
                )

        return cleaned_data


# ---------------------------------------------------------------------------
# StoreAccessForm
# ---------------------------------------------------------------------------

class StoreAccessForm(forms.ModelForm):
    """Form for managing detailed store access permissions."""

    class Meta:
        model = StoreAccess
        fields = [
            "user", "store", "access_level",
            "can_view_sales", "can_create_sales",
            "can_view_inventory", "can_manage_inventory",
            "can_view_reports", "can_fiscalize",
            "can_manage_staff", "notes",
        ]
        widgets = {
            "user": forms.Select(attrs={"class": "form-select"}),
            "store": forms.Select(attrs={"class": "form-select"}),
            "access_level": forms.Select(attrs={"class": "form-select"}),
            "can_view_sales": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "can_create_sales": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "can_view_inventory": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "can_manage_inventory": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "can_view_reports": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "can_fiscalize": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "can_manage_staff": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "notes": forms.Textarea(attrs={"rows": 3, "class": "form-control"}),
        }

    def __init__(self, *args, **kwargs):
        requesting_user = kwargs.pop("requesting_user", None)
        super().__init__(*args, **kwargs)

        if requesting_user:
            self.fields["user"].queryset = requesting_user.get_manageable_users()
            self.fields["store"].queryset = requesting_user.get_accessible_stores()

        self.helper = FormHelper()
        self.helper.form_method = "post"
        self.helper.layout = Layout(
            Fieldset(
                "User & Store",
                Row(
                    Column("user", css_class="col-md-6"),
                    Column("store", css_class="col-md-6"),
                ),
            ),
            Fieldset(
                "Access Level",
                "access_level",
                HTML(
                    "<small class=\"text-muted\">"
                    "View: Read-only | Staff: Basic operations | "
                    "Manager: Advanced operations | Admin: Full control"
                    "</small>"
                ),
            ),
            Fieldset(
                "Sales Permissions",
                Row(
                    Column("can_view_sales", css_class="col-md-6"),
                    Column("can_create_sales", css_class="col-md-6"),
                ),
            ),
            Fieldset(
                "Inventory Permissions",
                Row(
                    Column("can_view_inventory", css_class="col-md-6"),
                    Column("can_manage_inventory", css_class="col-md-6"),
                ),
            ),
            Fieldset(
                "Advanced Permissions",
                Row(
                    Column("can_view_reports", css_class="col-md-6"),
                    Column("can_fiscalize", css_class="col-md-6"),
                ),
                "can_manage_staff",
            ),
            Fieldset("Notes", "notes"),
            Submit("submit", "Save Access Permissions", css_class="btn btn-primary"),
        )

    def clean(self):
        cleaned_data = super().clean()
        access_level = cleaned_data.get("access_level")

        # Auto-configure permissions based on access level
        if access_level == "view":
            cleaned_data["can_create_sales"] = False
            cleaned_data["can_manage_inventory"] = False
            cleaned_data["can_fiscalize"] = False
            cleaned_data["can_manage_staff"] = False
        elif access_level == "staff":
            cleaned_data["can_view_sales"] = True
            cleaned_data["can_create_sales"] = True
            cleaned_data["can_view_inventory"] = True
        elif access_level == "manager":
            cleaned_data["can_view_sales"] = True
            cleaned_data["can_create_sales"] = True
            cleaned_data["can_view_inventory"] = True
            cleaned_data["can_manage_inventory"] = True
            cleaned_data["can_view_reports"] = True
            cleaned_data["can_fiscalize"] = True
        elif access_level == "admin":
            for field in [
                "can_view_sales", "can_create_sales", "can_view_inventory",
                "can_manage_inventory", "can_view_reports", "can_fiscalize",
                "can_manage_staff",
            ]:
                cleaned_data[field] = True

        return cleaned_data


# ---------------------------------------------------------------------------
# StoreForm
# ---------------------------------------------------------------------------

class StoreForm(forms.ModelForm):
    """Advanced form for Store model with enhanced validation and UI."""

    copy_from_company = forms.BooleanField(
        required=False,
        initial=False,
        label=_("Copy from Company Configuration"),
        help_text=_("Check this to copy company EFRIS settings to store-specific fields"),
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
    )
    geocode_address = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            "placeholder": "Enter address to find coordinates automatically",
            "class": "form-control",
        }),
        help_text='Enter full address and click "Find Coordinates" button',
        label="Search Address for Coordinates",
    )

    class Meta:
        model = Store
        fields = [
            # Basic Information
            "company", "name", "code", "store_type", "is_main_branch", "accessible_by_all",
            # Location
            "physical_address", "location", "location_gps",
            "latitude", "longitude", "region",
            # Contact
            "phone", "secondary_phone", "email", "logo",
            # Management
            "allows_sales", "allows_inventory",
            "manager_name", "manager_phone",
            "operating_hours", "timezone", "sort_order", "notes",
            # Staff
            "staff", "store_managers",
            # Identifiers
            "nin", "tin", "device_serial_number",
            # EFRIS Basic
            "efris_enabled", "efris_device_number",
            "is_registered_with_efris", "efris_registration_date",
            "efris_last_sync", "last_stock_sync",
            "auto_fiscalize_sales", "allow_manual_fiscalization",
            "report_stock_movements",
            # Status
            "is_active",
            "store_efris_integration_mode",
            # EFRIS Toggle
            "use_company_efris",
            # Store-specific EFRIS
            "store_efris_private_key", "store_efris_public_certificate",
            "store_efris_key_password", "store_efris_certificate_fingerprint",
            "store_efris_is_production",
            "store_auto_fiscalize_sales", "store_auto_sync_products",
            "store_efris_is_active", "store_efris_last_sync",
        ]
        widgets = {
            "company": forms.Select(attrs={"class": "form-select"}),
            "name": forms.TextInput(attrs={"placeholder": "Store name", "class": "form-control"}),
            "code": forms.TextInput(attrs={"placeholder": "Auto-generated if left blank", "class": "form-control"}),
            "store_type": forms.Select(attrs={"class": "form-select"}),
            "is_main_branch": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "accessible_by_all": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "physical_address": forms.Textarea(attrs={
                "rows": 3, "placeholder": "Enter full physical address...",
                "class": "form-control", "id": "physical_address_field",
            }),
            "location": forms.TextInput(attrs={"placeholder": "Location/Area", "class": "form-control"}),
            "location_gps": forms.TextInput(attrs={
                "placeholder": "e.g., 0.347596, 32.582520",
                "class": "form-control", "readonly": True,
            }),
            "latitude": forms.NumberInput(attrs={
                "step": "0.000001", "placeholder": "Latitude",
                "class": "form-control", "id": "latitude_field",
            }),
            "longitude": forms.NumberInput(attrs={
                "step": "0.000001", "placeholder": "Longitude",
                "class": "form-control", "id": "longitude_field",
            }),
            "region": forms.TextInput(attrs={
                "placeholder": "Region or District", "class": "form-control",
                "id": "region_field", "list": "regions_datalist",
            }),
            "phone": forms.TextInput(attrs={"placeholder": "+256XXXXXXXXX", "class": "form-control"}),
            "secondary_phone": forms.TextInput(attrs={"placeholder": "+256XXXXXXXXX", "class": "form-control"}),
            "email": forms.EmailInput(attrs={"placeholder": "store@example.com", "class": "form-control"}),
            "logo": forms.FileInput(attrs={"class": "form-control"}),
            "allows_sales": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "allows_inventory": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "manager_name": forms.TextInput(attrs={"placeholder": "Store Manager Name", "class": "form-control"}),
            "manager_phone": forms.TextInput(attrs={"placeholder": "+256XXXXXXXXX", "class": "form-control"}),
            "operating_hours": forms.Textarea(attrs={
                "rows": 4, "placeholder": "Operating hours in JSON format",
                "class": "form-control", "style": "font-family: monospace;",
            }),
            "timezone": forms.Select(attrs={"class": "form-select"}),
            "sort_order": forms.NumberInput(attrs={"placeholder": "0", "class": "form-control"}),
            "notes": forms.Textarea(attrs={
                "rows": 3, "placeholder": "Additional notes about the store...",
                "class": "form-control",
            }),
            "staff": forms.SelectMultiple(attrs={"class": "form-select", "size": "5"}),
            "store_managers": forms.SelectMultiple(attrs={"class": "form-select", "size": "5"}),
            "nin": forms.TextInput(attrs={"class": "form-control", "placeholder": "National Identification Number"}),
            "tin": forms.TextInput(attrs={"class": "form-control", "placeholder": "Tax Identification Number"}),
            "device_serial_number": forms.TextInput(attrs={"class": "form-control", "placeholder": "Device Serial Number"}),
            "efris_enabled": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "efris_device_number": forms.TextInput(attrs={"placeholder": "EFRIS Device Number", "class": "form-control"}),
            "is_registered_with_efris": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "efris_registration_date": forms.DateTimeInput(attrs={"class": "form-control", "type": "datetime-local"}),
            "efris_last_sync": forms.DateTimeInput(attrs={"class": "form-control", "type": "datetime-local"}),
            "last_stock_sync": forms.DateTimeInput(attrs={"class": "form-control", "type": "datetime-local"}),
            "auto_fiscalize_sales": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "allow_manual_fiscalization": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "report_stock_movements": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "use_company_efris": forms.CheckboxInput(attrs={
                "class": "form-check-input", "id": "id_use_company_efris",
                "onchange": "toggleEFRISFields(this.checked)",
            }),
            "store_efris_integration_mode": forms.Select(attrs={"class": "form-select"}),
            "store_efris_private_key": forms.Textarea(attrs={
                "class": "form-control", "rows": 6,
                "placeholder": "Store-specific RSA private key (PEM format)",
                "style": "font-family: monospace; font-size: 12px;",
            }),
            "store_efris_public_certificate": forms.Textarea(attrs={
                "class": "form-control", "rows": 6,
                "placeholder": "Store-specific X.509 certificate (PEM format)",
                "style": "font-family: monospace; font-size: 12px;",
            }),
            "store_efris_key_password": forms.PasswordInput(
                attrs={"class": "form-control", "placeholder": "Password for encrypted private key",
                       "autocomplete": "new-password"},
                render_value=True,
            ),
            "store_efris_certificate_fingerprint": forms.TextInput(attrs={
                "class": "form-control store-efris-field",
                "placeholder": "Certificate fingerprint (auto-generated)", "readonly": True,
            }),
            "store_efris_is_production": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "store_auto_fiscalize_sales": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "store_auto_sync_products": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "store_efris_is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "store_efris_last_sync": forms.DateTimeInput(attrs={"class": "form-control", "type": "datetime-local"}),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user", None)
        self.tenant = kwargs.pop("tenant", None)
        super().__init__(*args, **kwargs)

        # EFRIS fields not required by default — validated conditionally in clean()
        efris_fields = [
            "tin", "nin", "efris_device_number",
            "store_efris_private_key", "store_efris_public_certificate",
            "store_efris_key_password",
            # FIX: store_efris_integration_mode was missing from this list.
            # The model field has no blank=True so Django auto-sets required=True
            # on the form field.  Since the field has a default ('online') and is
            # only meaningful when EFRIS is enabled, it must be optional here —
            # exactly like every other EFRIS field in this list.
            "store_efris_integration_mode",
        ]
        for field_name in efris_fields:
            if field_name in self.fields:
                self.fields[field_name].required = False

        if self.instance and self.instance.pk and self.instance.physical_address:
            self.fields["geocode_address"].initial = self.instance.physical_address

        self.fields["accessible_by_all"].help_text = _(
            "If checked, all users in the company can access this store"
        )
        self.fields["use_company_efris"].help_text = _(
            "Use company-wide EFRIS configuration. Uncheck to use store-specific settings."
        )
        self.fields["allows_sales"].help_text = _(
            "Check if this store is allowed to make sales"
        )
        self.fields["allows_inventory"].help_text = _(
            "Check if this store manages its own inventory"
        )
        self.fields["operating_hours"].help_text = _(
            "Enter operating hours in JSON format. "
            'Example: {"monday": {"is_open": true, "open_time": "08:00", "close_time": "18:00"}}'
        )

        if self.instance and self.instance.company:
            from django.contrib.auth import get_user_model

            User = get_user_model()
            company_users = User.objects.filter(
                company_id=self.instance.company.company_id,
                is_active=True,
            )
            self.fields["staff"].queryset = company_users
            self.fields["store_managers"].queryset = company_users

        self.field_groups = {
            "basic": ["name", "code", "store_type", "is_main_branch", "accessible_by_all"],
            "location": ["physical_address", "location", "geocode_address", "latitude", "longitude", "region"],
            "contact": ["phone", "secondary_phone", "email"],
            "management": [
                "allows_sales", "allows_inventory", "manager_name", "manager_phone",
                "operating_hours", "timezone", "sort_order", "notes",
            ],
            "staff": ["staff", "store_managers"],
            "identifiers": ["nin", "tin", "device_serial_number", "store_efris_integration_mode"],
            "efris_basic": [
                "efris_enabled", "efris_device_number", "is_registered_with_efris",
                "efris_registration_date", "efris_last_sync", "last_stock_sync",
                "auto_fiscalize_sales", "allow_manual_fiscalization", "report_stock_movements",
            ],
            "efris_toggle": ["use_company_efris", "copy_from_company"],
            "efris_store": [
                "store_efris_private_key", "store_efris_public_certificate",
                "store_efris_key_password", "store_efris_certificate_fingerprint",
                "store_efris_is_production",
                "store_auto_fiscalize_sales", "store_auto_sync_products",
                "store_efris_is_active", "store_efris_last_sync",
            ],
        }

    def _is_efris_enabled(self, cleaned_data):
        """
        Return True if EFRIS should be enforced.

        FIX: Accepts cleaned_data explicitly so there is no implicit dependency
        on field processing order and no risk of accessing a partially-built
        cleaned_data dict via self.cleaned_data.
        """
        if cleaned_data.get("efris_enabled"):
            return True
        if self.instance and self.instance.company:
            company = self.instance.company
            if getattr(company, "efris_enabled", False):
                return True
        if self.tenant and getattr(self.tenant, "efris_enabled", False):
            return True
        return False

    def clean(self):
        cleaned_data = super().clean()
        use_company_efris = cleaned_data.get("use_company_efris", True)

        # FIX: pass cleaned_data explicitly instead of relying on self.cleaned_data
        efris_enabled = self._is_efris_enabled(cleaned_data)

        # Validate coordinates
        latitude = cleaned_data.get("latitude")
        longitude = cleaned_data.get("longitude")

        if (latitude is not None) != (longitude is not None):
            raise forms.ValidationError(
                _("Both latitude and longitude must be provided together.")
            )

        # FIX: use explicit None check so that 0.0 coordinates are handled correctly
        if latitude is not None and longitude is not None:
            cleaned_data["location_gps"] = f"{latitude}, {longitude}"

        # Validate store-specific EFRIS fields only when EFRIS is on and
        # store is NOT delegating to company config
        if efris_enabled and not use_company_efris:
            required_store_fields = {
                "tin": "TIN number",
                "store_efris_private_key": "Private Key",
                "store_efris_public_certificate": "Public Certificate",
            }
            for field, label in required_store_fields.items():
                if not cleaned_data.get(field):
                    self.add_error(
                        field,
                        _(f"{label} is required when using store-specific EFRIS configuration."),
                    )

            # Additional TIN check against company config
            if not cleaned_data.get("tin") and self.instance:
                company_config = self.instance.get_company_efris_config()
                if not company_config.get("tin"):
                    self.add_error(
                        "tin",
                        _("TIN must be provided at either store or company level for EFRIS."),
                    )

        # Warning (non-blocking) when using company EFRIS but company config is incomplete
        if efris_enabled and use_company_efris and self.instance and self.instance.company:
            company_config = self.instance.get_company_efris_config()
            missing_company_fields = []
            if not company_config.get("tin"):
                missing_company_fields.append("TIN")
            if not company_config.get("efris_private_key"):
                missing_company_fields.append("Private Key")
            if not company_config.get("efris_public_certificate"):
                missing_company_fields.append("Public Certificate")

            if missing_company_fields:
                if not hasattr(self, "_warnings"):
                    self._warnings = []
                self._warnings.append(
                    _(
                        f"Note: Company EFRIS configuration is incomplete. "
                        f'Missing: {", ".join(missing_company_fields)}. '
                        f"EFRIS features may not work until company configuration is complete."
                    )
                )

        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.cleaned_data.get("copy_from_company"):
            instance.copy_company_efris_to_store()
        if commit:
            instance.save()
            self.save_m2m()
        return instance

    def clean_phone(self):
        phone = self.cleaned_data.get("phone")
        if phone and not phone.startswith("+"):
            raise forms.ValidationError(_("Phone number must start with country code (+)"))
        return phone

    def clean_secondary_phone(self):
        phone = self.cleaned_data.get("secondary_phone")
        if phone and not phone.startswith("+"):
            raise forms.ValidationError(_("Phone number must start with country code (+)"))
        return phone

    def clean_manager_phone(self):
        phone = self.cleaned_data.get("manager_phone")
        if phone and not phone.startswith("+"):
            raise forms.ValidationError(
                _("Manager phone number must start with country code (+)")
            )
        return phone

    def clean_operating_hours(self):
        operating_hours = self.cleaned_data.get("operating_hours")
        if operating_hours:
            if isinstance(operating_hours, dict):
                return operating_hours
            if isinstance(operating_hours, str):
                try:
                    return json.loads(operating_hours)
                except json.JSONDecodeError:
                    raise forms.ValidationError(
                        _("Invalid JSON format for operating hours")
                    )
        return operating_hours


# ---------------------------------------------------------------------------
# StoreAdminForm
# ---------------------------------------------------------------------------

class StoreAdminForm(forms.ModelForm):
    class Meta:
        model = Store
        fields = "__all__"

    def clean(self):
        cleaned_data = super().clean()
        is_main_branch = cleaned_data.get("is_main_branch")
        company = cleaned_data.get("company")

        # Enforce single main branch per company
        if is_main_branch and company:
            existing_main = Store.objects.filter(
                company=company, is_main_branch=True
            ).exclude(pk=self.instance.pk if self.instance else None)
            if existing_main.exists():
                raise forms.ValidationError(
                    _("Company already has a main branch. Only one main branch is allowed per company.")
                )

        use_company_efris = cleaned_data.get("use_company_efris")
        efris_enabled = cleaned_data.get("efris_enabled", False)

        # FIX: only run EFRIS field validation when EFRIS is actually enabled,
        # matching the logic in StoreForm and preventing spurious errors on
        # stores that have EFRIS completely disabled.
        if efris_enabled and not use_company_efris:
            if not cleaned_data.get("tin"):
                self.add_error(
                    "tin",
                    _("TIN is required when using store-specific EFRIS configuration"),
                )
            if not cleaned_data.get("efris_device_number"):
                self.add_error(
                    "efris_device_number",
                    _("Device number is required when using store-specific EFRIS configuration"),
                )
            if not cleaned_data.get("store_efris_private_key"):
                self.add_error(
                    "store_efris_private_key",
                    _("Private key is required when using store-specific EFRIS configuration"),
                )
            if not cleaned_data.get("store_efris_public_certificate"):
                self.add_error(
                    "store_efris_public_certificate",
                    _("Public certificate is required when using store-specific EFRIS configuration"),
                )

        return cleaned_data


# ---------------------------------------------------------------------------
# StoreEFRISOverrideForm
# ---------------------------------------------------------------------------

class StoreEFRISOverrideForm(forms.ModelForm):
    """Form specifically for managing store EFRIS override."""

    class Meta:
        model = Store
        fields = [
            "use_company_efris",
            "store_efris_private_key", "store_efris_public_certificate",
            "store_efris_key_password", "store_efris_is_production",
            "store_efris_integration_mode",
            "store_auto_fiscalize_sales", "store_auto_sync_products",
            "store_efris_is_active",
        ]
        widgets = {
            "store_efris_private_key": forms.Textarea(attrs={
                "rows": 8, "class": "form-control",
                "placeholder": "Paste RSA private key here...",
                "style": "font-family: monospace;",
            }),
            "store_efris_public_certificate": forms.Textarea(attrs={
                "rows": 8, "class": "form-control",
                "placeholder": "Paste X.509 certificate here...",
                "style": "font-family: monospace;",
            }),
            "store_efris_key_password": forms.PasswordInput(
                attrs={"class": "form-control", "placeholder": "Enter key password..."},
                render_value=True,
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.layout = Layout(
            Fieldset(
                "Store-Specific EFRIS Configuration",
                Field("use_company_efris"),
                Field("store_efris_private_key"),
                Field("store_efris_public_certificate"),
                Field("store_efris_key_password"),
                Row(
                    Column("store_efris_is_production", css_class="col-md-6"),
                    Column("store_efris_integration_mode", css_class="col-md-6"),
                ),
                Row(
                    Column("store_auto_fiscalize_sales", css_class="col-md-6"),
                    Column("store_auto_sync_products", css_class="col-md-6"),
                ),
                Field("store_efris_is_active"),
            ),
            Submit("submit", "Save EFRIS Configuration", css_class="btn btn-primary"),
        )


# ---------------------------------------------------------------------------
# EnhancedStoreReportForm
# ---------------------------------------------------------------------------

class EnhancedStoreReportForm(forms.Form):
    """Enhanced form for generating store reports."""

    REPORT_TYPE_CHOICES = [
        ("", "Select report type..."),
        ("store_summary", "Store Summary"),
        ("inventory", "Inventory Report"),
        ("operating_hours", "Operating Hours"),
        ("device_status", "Device Status"),
        ("staff_assignment", "Staff Assignment"),
        ("comprehensive", "Comprehensive Report"),
    ]
    EXPORT_FORMAT_CHOICES = [
        ("csv", "CSV"),
        ("excel", "Excel"),
        ("pdf", "PDF"),
    ]

    report_type = forms.ChoiceField(
        choices=REPORT_TYPE_CHOICES,
        required=True,
        widget=forms.Select(attrs={"class": "form-select", "id": "report_type"}),
    )
    store_select = forms.ChoiceField(
        required=True,
        widget=forms.Select(attrs={"class": "form-select", "id": "store_select"}),
    )
    start_date = forms.DateField(
        required=True,
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control", "id": "start_date"}),
    )
    end_date = forms.DateField(
        required=True,
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control", "id": "end_date"}),
    )
    export_format = forms.ChoiceField(
        choices=EXPORT_FORMAT_CHOICES,
        required=True,
        widget=forms.RadioSelect(attrs={"class": "d-none"}),
    )
    include_charts = forms.BooleanField(
        required=False, initial=True,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input", "id": "include_charts"}),
    )
    include_summary = forms.BooleanField(
        required=False, initial=True,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input", "id": "include_summary"}),
    )
    include_raw_data = forms.BooleanField(
        required=False, initial=False,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input", "id": "include_raw_data"}),
    )
    include_images = forms.BooleanField(
        required=False, initial=True,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input", "id": "include_images"}),
    )
    detailed_breakdown = forms.BooleanField(
        required=False, initial=False,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input", "id": "detailed_breakdown"}),
    )
    compare_periods = forms.BooleanField(
        required=False, initial=False,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input", "id": "compare_periods"}),
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)

        if user:
            accessible_stores = user.get_accessible_stores()
            store_choices = [("all", "All Accessible Stores")]
            store_choices.extend(
                (store.id, store.name)
                for store in accessible_stores.order_by("name")
            )
            self.fields["store_select"].choices = store_choices
        else:
            # FIX: provide a meaningful placeholder but keep required=True so
            # the form fails cleanly with a visible validation error, rather
            # than producing a silent empty-store submission.
            self.fields["store_select"].choices = [("", "No stores available — please log in")]

        today = datetime.now().date()
        self.fields["start_date"].initial = today - timedelta(days=30)
        self.fields["end_date"].initial = today

    def clean(self):
        cleaned_data = super().clean()
        start_date = cleaned_data.get("start_date")
        end_date = cleaned_data.get("end_date")

        if start_date and end_date:
            if start_date > end_date:
                raise ValidationError(_("Start date must be before end date"))
            # FIX: removed the unreachable `date_diff < 0` branch — it can
            # never be reached because the check above already handles it.
            if (end_date - start_date).days > 365:
                raise ValidationError(_("Date range cannot exceed 1 year"))

        return cleaned_data


# ---------------------------------------------------------------------------
# StoreReportForm
# ---------------------------------------------------------------------------

class StoreReportForm(forms.Form):
    """Simple form for basic store reports."""

    REPORT_TYPE_CHOICES = [
        ("summary", "Store Summary"),
        ("detailed", "Detailed Report"),
        ("inventory", "Inventory Status"),
        ("sales", "Sales Performance"),
    ]
    FORMAT_CHOICES = [
        ("pdf", "PDF"),
        ("excel", "Excel"),
        ("csv", "CSV"),
    ]

    report_type = forms.ChoiceField(
        choices=REPORT_TYPE_CHOICES, required=True,
        widget=forms.Select(attrs={"class": "form-control"}),
    )
    date_from = forms.DateField(
        required=True,
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}),
    )
    date_to = forms.DateField(
        required=True,
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}),
    )
    format = forms.ChoiceField(
        choices=FORMAT_CHOICES, required=True, initial="pdf",
        widget=forms.Select(attrs={"class": "form-control"}),
    )
    include_charts = forms.BooleanField(
        required=False, initial=True,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
    )

    def clean(self):
        cleaned_data = super().clean()
        date_from = cleaned_data.get("date_from")
        date_to = cleaned_data.get("date_to")
        if date_from and date_to and date_from > date_to:
            raise ValidationError(_("Start date must be before end date"))
        return cleaned_data


# ---------------------------------------------------------------------------
# StoreOperatingHoursForm
# ---------------------------------------------------------------------------

class StoreOperatingHoursForm(forms.ModelForm):
    """Form for managing store operating hours."""

    class Meta:
        model = StoreOperatingHours
        fields = ["store", "day", "opening_time", "closing_time", "is_closed"]
        widgets = {
            "store": forms.Select(attrs={"class": "form-select"}),
            "day": forms.Select(attrs={"class": "form-select"}),
            "opening_time": forms.TimeInput(attrs={"type": "time", "class": "form-control"}),
            "closing_time": forms.TimeInput(attrs={"type": "time", "class": "form-control"}),
            "is_closed": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.layout = Layout(
            Row(
                Column("store", css_class="form-group col-md-6 mb-3"),
                Column("day", css_class="form-group col-md-6 mb-3"),
                css_class="form-row",
            ),
            HTML(
                '<div class="alert alert-warning">'
                '<i class="bi bi-clock me-2"></i>'
                'Check "Closed All Day" if the store is closed on this day.'
                "</div>"
            ),
            Field("is_closed", css_class="form-check-input mb-3"),
            Row(
                Column("opening_time", css_class="form-group col-md-6 mb-3"),
                Column("closing_time", css_class="form-group col-md-6 mb-3"),
                css_class="form-row closed-times-row",
            ),
            Submit("submit", "Save Hours", css_class="btn btn-primary"),
        )

    def clean(self):
        cleaned_data = super().clean()
        is_closed = cleaned_data.get("is_closed")
        opening_time = cleaned_data.get("opening_time")
        closing_time = cleaned_data.get("closing_time")

        if not is_closed:
            if not opening_time:
                raise forms.ValidationError(_("Opening time is required when store is not closed."))
            if not closing_time:
                raise forms.ValidationError(_("Closing time is required when store is not closed."))
            if opening_time and closing_time and opening_time >= closing_time:
                raise forms.ValidationError(_("Opening time must be before closing time."))

        return cleaned_data


# ---------------------------------------------------------------------------
# StoreDeviceForm
# ---------------------------------------------------------------------------

class StoreDeviceForm(forms.ModelForm):
    """Form for managing store devices."""

    class Meta:
        model = StoreDevice
        fields = ["store", "name", "device_number", "device_type", "serial_number", "is_active", "notes"]
        widgets = {
            "store": forms.Select(attrs={"class": "form-select"}),
            "name": forms.TextInput(attrs={"placeholder": "Device name", "class": "form-control"}),
            "device_number": forms.TextInput(attrs={"placeholder": "URA assigned device number", "class": "form-control"}),
            "device_type": forms.Select(attrs={"class": "form-select"}),
            "serial_number": forms.TextInput(attrs={"placeholder": "Device serial number", "class": "form-control"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "notes": forms.Textarea(attrs={"rows": 3, "placeholder": "Additional notes about this device...", "class": "form-control"}),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.layout = Layout(
            Fieldset(
                "Device Information",
                Row(
                    Column("store", css_class="form-group col-md-6 mb-3"),
                    Column("device_type", css_class="form-group col-md-6 mb-3"),
                ),
                Row(
                    Column("name", css_class="form-group col-md-6 mb-3"),
                    Column("device_number", css_class="form-group col-md-6 mb-3"),
                ),
                Row(
                    Column("serial_number", css_class="form-group col-md-8 mb-3"),
                    Column(
                        Field("is_active", css_class="form-check-input mt-4"),
                        css_class="form-group col-md-4 mb-3",
                    ),
                ),
                "notes",
            ),
            Submit("submit", "Save Device", css_class="btn btn-primary"),
        )


# ---------------------------------------------------------------------------
# StoreFilterForm
# ---------------------------------------------------------------------------

class StoreFilterForm(forms.Form):
    """Advanced filtering form for stores."""

    STATUS_CHOICES = [
        ("", "All Statuses"),
        ("active", "Active"),
        ("inactive", "Inactive"),
    ]
    EFRIS_CHOICES = [
        ("", "All Stores"),
        ("enabled", "EFRIS Enabled"),
        ("disabled", "EFRIS Disabled"),
    ]

    search = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "Search stores...", "class": "form-control"}),
    )
    company = forms.ModelChoiceField(
        queryset=None,
        required=False,
        empty_label="Company",
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    region = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "Filter by region...", "class": "form-control"}),
    )
    status = forms.ChoiceField(
        choices=STATUS_CHOICES, required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    efris_status = forms.ChoiceField(
        choices=EFRIS_CHOICES, required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    def __init__(self, *args, **kwargs):
        company_queryset = kwargs.pop("company_queryset", None)
        super().__init__(*args, **kwargs)
        if company_queryset is not None:
            self.fields["company"].queryset = company_queryset


# ---------------------------------------------------------------------------
# BulkStoreActionForm
# ---------------------------------------------------------------------------

class BulkStoreActionForm(forms.Form):
    """Form for bulk actions on stores."""

    ACTION_CHOICES = [
        ("", "Select Action"),
        ("activate", "Activate Selected"),
        ("deactivate", "Deactivate Selected"),
        ("enable_efris", "Enable EFRIS"),
        ("disable_efris", "Disable EFRIS"),
        ("delete", "Delete Selected"),
    ]

    action = forms.ChoiceField(
        choices=ACTION_CHOICES,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    selected_stores = forms.CharField(widget=forms.HiddenInput())

    def clean_selected_stores(self):
        data = self.cleaned_data["selected_stores"]
        try:
            store_ids = json.loads(data)
            if not isinstance(store_ids, list):
                raise forms.ValidationError(_("Invalid store selection."))
            return store_ids
        except (json.JSONDecodeError, ValueError):
            raise forms.ValidationError(_("Invalid store selection format."))