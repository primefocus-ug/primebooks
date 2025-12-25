from .models import Store, StoreOperatingHours, StoreDevice
import json
from django.core.exceptions import ValidationError
from datetime import datetime, timedelta
from django.utils.translation import gettext_lazy as _
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Fieldset, Row, Column, Field, HTML, Submit
from django import forms
from .models import Store, StoreAccess
from accounts.models import CustomUser

class StoreStaffAssignmentForm(forms.Form):
    """Form for assigning staff to stores with access control"""

    # ✅ NEW: Access level field
    access_level = forms.ChoiceField(
        choices=StoreAccess.ACCESS_LEVELS,
        initial='staff',
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'}),
        label=_('Access Level for New Staff'),
        help_text=_('Select the access level for newly added staff members')
    )

    # ✅ NEW: Permission fields
    can_view_sales = forms.BooleanField(
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        label=_('Can View Sales')
    )

    can_create_sales = forms.BooleanField(
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        label=_('Can Create Sales')
    )

    can_view_inventory = forms.BooleanField(
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        label=_('Can View Inventory')
    )

    can_manage_inventory = forms.BooleanField(
        required=False,
        initial=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        label=_('Can Manage Inventory')
    )

    can_view_reports = forms.BooleanField(
        required=False,
        initial=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        label=_('Can View Reports')
    )

    can_fiscalize = forms.BooleanField(
        required=False,
        initial=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        label=_('Can Fiscalize Invoices')
    )

    can_manage_staff = forms.BooleanField(
        required=False,
        initial=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        label=_('Can Manage Staff')
    )

    def __init__(self, store_instance=None, user=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.store = store_instance
        self.current_user = user

        if store_instance and user:
            # Get users that the current user can manage
            manageable_users = user.get_manageable_users()

            # Get current staff for the store (excluding hidden users)
            current_staff_ids = store_instance.staff.filter(
                is_hidden=False
            ).values_list('id', flat=True)

            # Get available users (excluding current staff)
            available_users = manageable_users.filter(
                company=store_instance.company,
                is_active=True
            ).exclude(id__in=current_staff_ids)

            # Create add_staff field with available users
            staff_choices = [
                (u.id, f"{u.get_full_name()} ({u.email}) - {u.display_role}")
                for u in available_users
            ]

            self.fields['add_staff'] = forms.MultipleChoiceField(
                choices=staff_choices,
                required=False,
                widget=forms.SelectMultiple(attrs={
                    'class': 'form-select',
                    'size': '10'
                }),
                label=_('Add Staff Members'),
                help_text=_('Select users to add to this store')
            )

            # Create remove_staff field with current staff
            current_staff = store_instance.staff.filter(
                is_hidden=False,
                is_active=True
            )

            # Only show staff that the current user can manage
            removable_staff = [
                s for s in current_staff
                if user.can_manage_user(s)
            ]

            remove_choices = [
                (s.id, f"{s.get_full_name()} ({s.email}) - {s.display_role}")
                for s in removable_staff
            ]

            self.fields['remove_staff'] = forms.MultipleChoiceField(
                choices=remove_choices,
                required=False,
                widget=forms.SelectMultiple(attrs={
                    'class': 'form-select',
                    'size': '10'
                }),
                label=_('Remove Staff Members'),
                help_text=_('Select users to remove from this store')
            )

        # Setup crispy forms helper
        self.helper = FormHelper()
        self.helper.form_method = 'post'
        self.helper.layout = Layout(
            Fieldset(
                'Add Staff Members',
                Field('add_staff'),
                HTML('<hr>'),
                'access_level',
                HTML('<div class="row">'),
                Column('can_view_sales', css_class='col-md-6'),
                Column('can_create_sales', css_class='col-md-6'),
                HTML('</div>'),
                HTML('<div class="row">'),
                Column('can_view_inventory', css_class='col-md-6'),
                Column('can_manage_inventory', css_class='col-md-6'),
                HTML('</div>'),
                HTML('<div class="row">'),
                Column('can_view_reports', css_class='col-md-6'),
                Column('can_fiscalize', css_class='col-md-6'),
                HTML('</div>'),
                Field('can_manage_staff'),
            ),
            HTML('<hr>'),
            Fieldset(
                'Remove Staff Members',
                Field('remove_staff'),
            ),
            Submit('submit', 'Update Staff Assignments', css_class='btn btn-primary')
        )

    def clean(self):
        cleaned_data = super().clean()

        # Convert string IDs to actual User objects
        add_ids = cleaned_data.get('add_staff', [])
        remove_ids = cleaned_data.get('remove_staff', [])

        try:
            if add_ids:
                cleaned_data['add_staff'] = CustomUser.objects.filter(
                    id__in=[int(id) for id in add_ids if id]
                )
            else:
                cleaned_data['add_staff'] = CustomUser.objects.none()

            if remove_ids:
                cleaned_data['remove_staff'] = CustomUser.objects.filter(
                    id__in=[int(id) for id in remove_ids if id]
                )
            else:
                cleaned_data['remove_staff'] = CustomUser.objects.none()

        except (ValueError, TypeError):
            raise forms.ValidationError(_('Invalid user selection'))

        # Validate permissions based on access level
        access_level = cleaned_data.get('access_level', 'staff')

        if access_level == 'view':
            # View-only access shouldn't have write permissions
            if cleaned_data.get('can_create_sales') or cleaned_data.get('can_manage_inventory'):
                self.add_error(
                    'access_level',
                    _('View-only access cannot have create or manage permissions')
                )

        return cleaned_data


class StoreAccessForm(forms.ModelForm):
    """Form for managing detailed store access permissions."""

    class Meta:
        model = StoreAccess
        fields = [
            'user', 'store', 'access_level',
            'can_view_sales', 'can_create_sales',
            'can_view_inventory', 'can_manage_inventory',
            'can_view_reports', 'can_fiscalize',
            'can_manage_staff', 'notes'
        ]
        widgets = {
            'user': forms.Select(attrs={'class': 'form-select'}),
            'store': forms.Select(attrs={'class': 'form-select'}),
            'access_level': forms.Select(attrs={'class': 'form-select'}),
            'can_view_sales': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'can_create_sales': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'can_view_inventory': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'can_manage_inventory': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'can_view_reports': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'can_fiscalize': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'can_manage_staff': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'notes': forms.Textarea(attrs={'rows': 3, 'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        requesting_user = kwargs.pop('requesting_user', None)
        super().__init__(*args, **kwargs)

        if requesting_user:
            # Filter users to those the requesting user can manage
            self.fields['user'].queryset = requesting_user.get_manageable_users()

            # Filter stores to those the requesting user can access
            self.fields['store'].queryset = requesting_user.get_accessible_stores()

        # Setup crispy forms helper
        self.helper = FormHelper()
        self.helper.form_method = 'post'
        self.helper.layout = Layout(
            Fieldset(
                'User & Store',
                Row(
                    Column('user', css_class='col-md-6'),
                    Column('store', css_class='col-md-6'),
                ),
            ),
            Fieldset(
                'Access Level',
                'access_level',
                HTML('<small class="text-muted">View: Read-only | Staff: Basic operations | Manager: Advanced operations | Admin: Full control</small>'),
            ),
            Fieldset(
                'Sales Permissions',
                Row(
                    Column('can_view_sales', css_class='col-md-6'),
                    Column('can_create_sales', css_class='col-md-6'),
                ),
            ),
            Fieldset(
                'Inventory Permissions',
                Row(
                    Column('can_view_inventory', css_class='col-md-6'),
                    Column('can_manage_inventory', css_class='col-md-6'),
                ),
            ),
            Fieldset(
                'Advanced Permissions',
                Row(
                    Column('can_view_reports', css_class='col-md-6'),
                    Column('can_fiscalize', css_class='col-md-6'),
                ),
                'can_manage_staff',
            ),
            Fieldset(
                'Notes',
                'notes',
            ),
            Submit('submit', 'Save Access Permissions', css_class='btn btn-primary')
        )

    def clean(self):
        cleaned_data = super().clean()
        access_level = cleaned_data.get('access_level')

        # Auto-configure permissions based on access level
        if access_level == 'view':
            # View-only: no write permissions
            cleaned_data['can_create_sales'] = False
            cleaned_data['can_manage_inventory'] = False
            cleaned_data['can_fiscalize'] = False
            cleaned_data['can_manage_staff'] = False
        elif access_level == 'staff':
            # Staff: basic operations
            cleaned_data['can_view_sales'] = True
            cleaned_data['can_create_sales'] = True
            cleaned_data['can_view_inventory'] = True
            # Keep other permissions as user set them
        elif access_level == 'manager':
            # Manager: most permissions
            cleaned_data['can_view_sales'] = True
            cleaned_data['can_create_sales'] = True
            cleaned_data['can_view_inventory'] = True
            cleaned_data['can_manage_inventory'] = True
            cleaned_data['can_view_reports'] = True
            cleaned_data['can_fiscalize'] = True
            # Keep can_manage_staff as user set it
        elif access_level == 'admin':
            # Admin: all permissions
            for field in ['can_view_sales', 'can_create_sales', 'can_view_inventory',
                         'can_manage_inventory', 'can_view_reports', 'can_fiscalize',
                         'can_manage_staff']:
                cleaned_data[field] = True

        return cleaned_data


class StoreForm(forms.ModelForm):
    """Advanced form for Store model with enhanced validation and UI"""

    copy_from_company = forms.BooleanField(
        required=False,
        initial=False,
        label=_('Copy from Company Configuration'),
        help_text=_('Check this to copy company EFRIS settings to store-specific fields'),
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )

    geocode_address = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'placeholder': 'Enter address to find coordinates automatically',
            'class': 'form-control'
        }),
        help_text='Enter full address and click "Find Coordinates" button',
        label='Search Address for Coordinates'
    )

    class Meta:
        model = Store
        fields = [
            'company', 'name', 'code', 'physical_address', 'location_gps',
            'latitude', 'longitude', 'region', 'phone', 'secondary_phone',
            'email', 'logo', 'efris_enabled',
            'is_active', 'store_type', 'is_main_branch', 'accessible_by_all',

            # EFRIS Configuration Toggle
            'use_company_efris',

            # Store-specific EFRIS fields
            'tin',
            'efris_device_number',
            'store_efris_private_key',
            'store_efris_public_certificate',
            'store_efris_key_password',
            'store_efris_certificate_fingerprint',
            'store_efris_is_production',
            'store_efris_integration_mode',
            'store_auto_fiscalize_sales',
            'store_auto_sync_products',
            'store_efris_is_active',
            'store_efris_last_sync',
        ]
        widgets = {
            'physical_address': forms.Textarea(attrs={
                'rows': 3,
                'placeholder': 'Enter full physical address...',
                'class': 'form-control',
                'id': 'physical_address_field'
            }),
            'tin': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Tax Identification Number'
            }),
            'location_gps': forms.TextInput(attrs={
                'placeholder': 'e.g., 0.347596, 32.582520',
                'class': 'form-control',
                'readonly': True
            }),
            'latitude': forms.NumberInput(attrs={
                'step': '0.000001',
                'placeholder': 'Latitude',
                'class': 'form-control',
                'id': 'latitude_field'
            }),
            'longitude': forms.NumberInput(attrs={
                'step': '0.000001',
                'placeholder': 'Longitude',
                'class': 'form-control',
                'id': 'longitude_field'
            }),
            'name': forms.TextInput(attrs={
                'placeholder': 'Store name',
                'class': 'form-control'
            }),
            'code': forms.TextInput(attrs={
                'placeholder': 'Auto-generated if left blank',
                'class': 'form-control'
            }),
            'region': forms.TextInput(attrs={
                'placeholder': 'Region or District',
                'class': 'form-control',
                'id': 'region_field',
                'list': 'regions_datalist'
            }),
            'phone': forms.TextInput(attrs={
                'placeholder': '+256XXXXXXXXX',
                'class': 'form-control'
            }),
            'secondary_phone': forms.TextInput(attrs={
                'placeholder': '+256XXXXXXXXX',
                'class': 'form-control'
            }),
            'email': forms.EmailInput(attrs={
                'placeholder': 'store@example.com',
                'class': 'form-control'
            }),
            'efris_device_number': forms.TextInput(attrs={
                'placeholder': 'EFRIS Device Number',
                'class': 'form-control'
            }),
            # ✅ NEW: Accessible by all checkbox
            'accessible_by_all': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
            'use_company_efris': forms.CheckboxInput(attrs={
                'class': 'form-check-input',
                'id': 'id_use_company_efris',
                'onchange': 'toggleEFRISFields(this.checked)'
            }),
            'store_efris_private_key': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 6,
                'placeholder': 'Store-specific RSA private key (PEM format)',
                'style': 'font-family: monospace; font-size: 12px;'
            }),
            'store_efris_public_certificate': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 6,
                'placeholder': 'Store-specific X.509 certificate (PEM format)',
                'style': 'font-family: monospace; font-size: 12px;'
            }),
            'store_efris_key_password': forms.PasswordInput(attrs={
                'class': 'form-control',
                'placeholder': 'Password for encrypted private key',
                'autocomplete': 'new-password'
            }, render_value=True),
            'store_efris_certificate_fingerprint': forms.TextInput(attrs={
                'class': 'form-control store-efris-field',
                'placeholder': 'Certificate fingerprint (auto-generated)',
                'readonly': True
            }),
            'store_efris_is_production': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
            'store_efris_integration_mode': forms.Select(attrs={
                'class': 'form-select'
            }),
            'store_auto_fiscalize_sales': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
            'store_auto_sync_products': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
            'store_efris_is_active': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
            'store_efris_last_sync': forms.DateTimeInput(attrs={
                'class': 'form-control',
                'type': 'datetime-local'
            }),
            'efris_enabled': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'is_main_branch': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'logo': forms.FileInput(attrs={'class': 'form-control'}),
            'company': forms.Select(attrs={'class': 'form-select'}),
            'store_type': forms.Select(attrs={'class': 'form-select'}),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        self.tenant = kwargs.pop('tenant', None)
        super().__init__(*args, **kwargs)

        # Set initial values
        if self.instance and self.instance.pk:
            if self.instance.physical_address:
                self.fields['geocode_address'].initial = self.instance.physical_address

        # Add help texts
        self.fields['accessible_by_all'].help_text = _(
            'If checked, all users in the company can access this store'
        )
        self.fields['use_company_efris'].help_text = _(
            'Use company-wide EFRIS configuration. Uncheck to use store-specific settings.'
        )

        # Organize fields into sections for better UX
        self.field_groups = {
            'basic': ['name', 'code', 'store_type', 'is_main_branch', 'accessible_by_all'],
            'location': ['physical_address', 'geocode_address', 'latitude', 'longitude', 'region'],
            'contact': ['phone', 'secondary_phone', 'email'],
            'efris_toggle': ['use_company_efris', 'copy_from_company'],
            'efris_store': [
                'tin', 'efris_device_number',
                 'store_efris_private_key',
                'store_efris_public_certificate', 'store_efris_key_password',
                'store_efris_certificate_fingerprint', 'store_efris_is_production',
                'store_efris_integration_mode', 'store_auto_fiscalize_sales',
                'store_auto_sync_products', 'store_efris_is_active'
            ]
        }

    def clean(self):
        cleaned_data = super().clean()
        use_company_efris = cleaned_data.get('use_company_efris', True)
        copy_from_company = cleaned_data.get('copy_from_company', False)

        # Handle copying from company
        if copy_from_company and self.instance and self.instance.pk:
            # This will be handled in save()
            pass

        # Validate coordinates
        latitude = cleaned_data.get('latitude')
        longitude = cleaned_data.get('longitude')

        if (latitude is not None and longitude is None) or (longitude is not None and latitude is None):
            raise forms.ValidationError(_('Both latitude and longitude must be provided together.'))

        if latitude and longitude:
            cleaned_data['location_gps'] = f"{latitude}, {longitude}"

        # Validate store-specific EFRIS config if not using company config
        if not use_company_efris:
            required_store_fields = {
                'tin': 'TIN number',
                'store_efris_private_key': 'Private Key',
                'store_efris_public_certificate': 'Public Certificate',
            }

            for field, label in required_store_fields.items():
                if not cleaned_data.get(field):
                    self.add_error(
                        field,
                        _(f'{label} is required when using store-specific EFRIS configuration.')
                    )

            # Validate TIN (can use store or company)
            if not cleaned_data.get('tin') and self.instance:
                company_config = self.instance.get_company_efris_config()
                if not company_config.get('tin'):
                    self.add_error(
                        'tin',
                        _('Either store TIN or company TIN must be provided.')
                    )

        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)

        # Handle copy from company
        if self.cleaned_data.get('copy_from_company'):
            instance.copy_company_efris_to_store()

        if commit:
            instance.save()

        return instance

    def clean_phone(self):
        phone = self.cleaned_data.get('phone')
        if phone and not phone.startswith('+'):
            raise forms.ValidationError(_('Phone number must start with country code (+)'))
        return phone

    def clean_secondary_phone(self):
        phone = self.cleaned_data.get('secondary_phone')
        if phone and not phone.startswith('+'):
            raise forms.ValidationError(_('Phone number must start with country code (+)'))
        return phone


from django import forms
from django.utils.translation import gettext_lazy as _
from .models import Store


class StoreAdminForm(forms.ModelForm):
    class Meta:
        model = Store
        fields = '__all__'

    def clean(self):
        cleaned_data = super().clean()

        # Validate that only one main branch per company exists
        is_main_branch = cleaned_data.get('is_main_branch')
        company = cleaned_data.get('company')

        if is_main_branch and company:
            existing_main = Store.objects.filter(
                company=company,
                is_main_branch=True
            ).exclude(pk=self.instance.pk if self.instance else None)

            if existing_main.exists():
                raise forms.ValidationError(
                    _('Company already has a main branch. Only one main branch is allowed per company.')
                )

        # Validate EFRIS configuration
        use_company_efris = cleaned_data.get('use_company_efris')

        if not use_company_efris:
            # Validate store-specific EFRIS fields
            tin = cleaned_data.get('tin')
            efris_device_number = cleaned_data.get('efris_device_number')
            store_efris_private_key = cleaned_data.get('store_efris_private_key')
            store_efris_public_certificate = cleaned_data.get('store_efris_public_certificate')

            if not tin:
                self.add_error('tin', _('TIN is required when using store-specific EFRIS configuration'))

            if not efris_device_number:
                self.add_error('efris_device_number',
                               _('Device number is required when using store-specific EFRIS configuration'))

            if not store_efris_private_key:
                self.add_error('store_efris_private_key',
                               _('Private key is required when using store-specific EFRIS configuration'))

            if not store_efris_public_certificate:
                self.add_error('store_efris_public_certificate',
                               _('Public certificate is required when using store-specific EFRIS configuration'))

        return cleaned_data


class StoreEFRISOverrideForm(forms.ModelForm):
    """Form specifically for managing store EFRIS override"""

    class Meta:
        model = Store
        fields = [
            'use_company_efris',
            'store_efris_private_key',
            'store_efris_public_certificate',
            'store_efris_key_password',
            'store_efris_is_production',
            'store_efris_integration_mode',
            'store_auto_fiscalize_sales',
            'store_auto_sync_products',
            'store_efris_is_active',
        ]

        widgets = {
            'store_efris_private_key': forms.Textarea(attrs={
                'rows': 8,
                'class': 'form-control',
                'placeholder': 'Paste RSA private key here...',
                'style': 'font-family: monospace;'
            }),
            'store_efris_public_certificate': forms.Textarea(attrs={
                'rows': 8,
                'class': 'form-control',
                'placeholder': 'Paste X.509 certificate here...',
                'style': 'font-family: monospace;'
            }),
            'store_efris_key_password': forms.PasswordInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter key password...'
            }, render_value=True),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.layout = Layout(
            Fieldset(
                'Store-Specific EFRIS Configuration',
                Field('use_company_efris'),

                Field('store_efris_private_key'),
                Field('store_efris_public_certificate'),
                Field('store_efris_key_password'),
                Row(
                    Column('store_efris_is_production', css_class='col-md-6'),
                    Column('store_efris_integration_mode', css_class='col-md-6'),
                ),
                Row(
                    Column('store_auto_fiscalize_sales', css_class='col-md-6'),
                    Column('store_auto_sync_products', css_class='col-md-6'),
                ),
                Field('store_efris_is_active'),
            ),
            Submit('submit', 'Save EFRIS Configuration', css_class='btn btn-primary')
        )

class EnhancedStoreReportForm(forms.Form):
    """Enhanced form for generating store reports"""

    REPORT_TYPE_CHOICES = [
        ('', 'Select report type...'),
        ('store_summary', 'Store Summary'),
        ('inventory', 'Inventory Report'),
        ('operating_hours', 'Operating Hours'),
        ('device_status', 'Device Status'),
        ('staff_assignment', 'Staff Assignment'),
        ('comprehensive', 'Comprehensive Report'),
    ]

    EXPORT_FORMAT_CHOICES = [
        ('csv', 'CSV'),
        ('excel', 'Excel'),
        ('pdf', 'PDF'),
    ]

    report_type = forms.ChoiceField(
        choices=REPORT_TYPE_CHOICES,
        required=True,
        widget=forms.Select(attrs={
            'class': 'form-select',
            'id': 'report_type'
        })
    )

    store_select = forms.ChoiceField(
        required=True,
        widget=forms.Select(attrs={
            'class': 'form-select',
            'id': 'store_select'
        })
    )

    start_date = forms.DateField(
        required=True,
        widget=forms.DateInput(attrs={
            'type': 'date',
            'class': 'form-control',
            'id': 'start_date'
        })
    )

    end_date = forms.DateField(
        required=True,
        widget=forms.DateInput(attrs={
            'type': 'date',
            'class': 'form-control',
            'id': 'end_date'
        })
    )

    export_format = forms.ChoiceField(
        choices=EXPORT_FORMAT_CHOICES,
        required=True,
        widget=forms.RadioSelect(attrs={
            'class': 'd-none'
        })
    )

    include_charts = forms.BooleanField(
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={
            'class': 'form-check-input',
            'id': 'include_charts'
        })
    )

    include_summary = forms.BooleanField(
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={
            'class': 'form-check-input',
            'id': 'include_summary'
        })
    )

    include_raw_data = forms.BooleanField(
        required=False,
        initial=False,
        widget=forms.CheckboxInput(attrs={
            'class': 'form-check-input',
            'id': 'include_raw_data'
        })
    )

    include_images = forms.BooleanField(
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={
            'class': 'form-check-input',
            'id': 'include_images'
        })
    )

    detailed_breakdown = forms.BooleanField(
        required=False,
        initial=False,
        widget=forms.CheckboxInput(attrs={
            'class': 'form-check-input',
            'id': 'detailed_breakdown'
        })
    )

    compare_periods = forms.BooleanField(
        required=False,
        initial=False,
        widget=forms.CheckboxInput(attrs={
            'class': 'form-check-input',
            'id': 'compare_periods'
        })
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)

        # ✅ Use new access control for populating store choices
        if user:
            accessible_stores = user.get_accessible_stores()

            store_choices = [('all', 'All Accessible Stores')]
            store_choices.extend([
                (store.id, store.name)
                for store in accessible_stores.order_by('name')
            ])
            self.fields['store_select'].choices = store_choices
        else:
            self.fields['store_select'].choices = [('', 'Select store...')]

        # Set default dates
        today = datetime.now().date()
        last_month = today - timedelta(days=30)
        self.fields['start_date'].initial = last_month
        self.fields['end_date'].initial = today

    def clean(self):
        cleaned_data = super().clean()
        start_date = cleaned_data.get('start_date')
        end_date = cleaned_data.get('end_date')

        if start_date and end_date:
            # Validate date range
            if start_date > end_date:
                raise ValidationError(_('Start date must be before end date'))

            # Validate date range is not too long
            date_diff = (end_date - start_date).days
            if date_diff > 365:
                raise ValidationError(_('Date range cannot exceed 1 year'))

            if date_diff < 0:
                raise ValidationError(_('Invalid date range'))

        return cleaned_data


class StoreReportForm(forms.Form):
    """Simple form for basic store reports"""

    REPORT_TYPE_CHOICES = [
        ('summary', 'Store Summary'),
        ('detailed', 'Detailed Report'),
        ('inventory', 'Inventory Status'),
        ('sales', 'Sales Performance'),
    ]

    FORMAT_CHOICES = [
        ('pdf', 'PDF'),
        ('excel', 'Excel'),
        ('csv', 'CSV'),
    ]

    report_type = forms.ChoiceField(
        choices=REPORT_TYPE_CHOICES,
        required=True,
        widget=forms.Select(attrs={'class': 'form-control'})
    )

    date_from = forms.DateField(
        required=True,
        widget=forms.DateInput(attrs={
            'type': 'date',
            'class': 'form-control'
        })
    )

    date_to = forms.DateField(
        required=True,
        widget=forms.DateInput(attrs={
            'type': 'date',
            'class': 'form-control'
        })
    )

    format = forms.ChoiceField(
        choices=FORMAT_CHOICES,
        required=True,
        initial='pdf',
        widget=forms.Select(attrs={'class': 'form-control'})
    )

    include_charts = forms.BooleanField(
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )

    def clean(self):
        cleaned_data = super().clean()
        date_from = cleaned_data.get('date_from')
        date_to = cleaned_data.get('date_to')

        if date_from and date_to and date_from > date_to:
            raise ValidationError(_('Start date must be before end date'))

        return cleaned_data



class StoreOperatingHoursForm(forms.ModelForm):
    """Form for managing store operating hours"""

    class Meta:
        model = StoreOperatingHours
        fields = ['store', 'day', 'opening_time', 'closing_time', 'is_closed']
        widgets = {
            'store': forms.Select(attrs={'class': 'form-select'}),
            'day': forms.Select(attrs={'class': 'form-select'}),
            'opening_time': forms.TimeInput(attrs={
                'type': 'time',
                'class': 'form-control'
            }),
            'closing_time': forms.TimeInput(attrs={
                'type': 'time',
                'class': 'form-control'
            }),
            'is_closed': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.layout = Layout(
            Row(
                Column('store', css_class='form-group col-md-6 mb-3'),
                Column('day', css_class='form-group col-md-6 mb-3'),
                css_class='form-row'
            ),
            HTML(
                '<div class="alert alert-warning"><i class="bi bi-clock me-2"></i>Check "Closed All Day" if the store is closed on this day.</div>'),
            Field('is_closed', css_class='form-check-input mb-3'),
            Row(
                Column('opening_time', css_class='form-group col-md-6 mb-3'),
                Column('closing_time', css_class='form-group col-md-6 mb-3'),
                css_class='form-row closed-times-row'
            ),
            Submit('submit', 'Save Hours', css_class='btn btn-primary')
        )

    def clean(self):
        cleaned_data = super().clean()
        is_closed = cleaned_data.get('is_closed')
        opening_time = cleaned_data.get('opening_time')
        closing_time = cleaned_data.get('closing_time')

        if not is_closed:
            if not opening_time:
                raise forms.ValidationError(_('Opening time is required when store is not closed.'))
            if not closing_time:
                raise forms.ValidationError(_('Closing time is required when store is not closed.'))
            if opening_time and closing_time and opening_time >= closing_time:
                raise forms.ValidationError(_('Opening time must be before closing time.'))

        return cleaned_data


class StoreDeviceForm(forms.ModelForm):
    """Form for managing store devices"""

    class Meta:
        model = StoreDevice
        fields = [
            'store', 'name', 'device_number', 'device_type',
            'serial_number', 'is_active', 'notes'
        ]
        widgets = {
            'store': forms.Select(attrs={'class': 'form-select'}),
            'name': forms.TextInput(attrs={
                'placeholder': 'Device name',
                'class': 'form-control'
            }),
            'device_number': forms.TextInput(attrs={
                'placeholder': 'URA assigned device number',
                'class': 'form-control'
            }),
            'device_type': forms.Select(attrs={'class': 'form-select'}),
            'serial_number': forms.TextInput(attrs={
                'placeholder': 'Device serial number',
                'class': 'form-control'
            }),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'notes': forms.Textarea(attrs={
                'rows': 3,
                'placeholder': 'Additional notes about this device...',
                'class': 'form-control'
            }),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)  # 👈 IMPORTANT
        super().__init__(*args, **kwargs)

        self.helper = FormHelper()
        self.helper.layout = Layout(
            Fieldset(
                'Device Information',
                Row(
                    Column('store', css_class='form-group col-md-6 mb-3'),
                    Column('device_type', css_class='form-group col-md-6 mb-3'),
                ),
                Row(
                    Column('name', css_class='form-group col-md-6 mb-3'),
                    Column('device_number', css_class='form-group col-md-6 mb-3'),
                ),
                Row(
                    Column('serial_number', css_class='form-group col-md-8 mb-3'),
                    Column(
                        Field('is_active', css_class='form-check-input mt-4'),
                        css_class='form-group col-md-4 mb-3'
                    ),
                ),
                'notes',
            ),
            Submit('submit', 'Save Device', css_class='btn btn-primary')
        )


class StoreFilterForm(forms.Form):
    """Advanced filtering form for stores"""

    STATUS_CHOICES = [
        ('', 'All Statuses'),
        ('active', 'Active'),
        ('inactive', 'Inactive'),
    ]

    EFRIS_CHOICES = [
        ('', 'All Stores'),
        ('enabled', 'EFRIS Enabled'),
        ('disabled', 'EFRIS Disabled'),
    ]

    search = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'placeholder': 'Search stores...',
            'class': 'form-control'
        })
    )

    company = forms.ModelChoiceField(
        queryset=None,
        required=False,
        empty_label="Company",
        widget=forms.Select(attrs={'class': 'form-select'})
    )

    region = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'placeholder': 'Filter by region...',
            'class': 'form-control'
        })
    )

    status = forms.ChoiceField(
        choices=STATUS_CHOICES,
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'})
    )

    efris_status = forms.ChoiceField(
        choices=EFRIS_CHOICES,
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'})
    )

    def __init__(self, *args, **kwargs):
        company_queryset = kwargs.pop('company_queryset', None)
        super().__init__(*args, **kwargs)

        if company_queryset:
            self.fields['company'].queryset = company_queryset


class BulkStoreActionForm(forms.Form):
    """Form for bulk actions on stores"""

    ACTION_CHOICES = [
        ('', 'Select Action'),
        ('activate', 'Activate Selected'),
        ('deactivate', 'Deactivate Selected'),
        ('enable_efris', 'Enable EFRIS'),
        ('disable_efris', 'Disable EFRIS'),
        ('delete', 'Delete Selected'),
    ]

    action = forms.ChoiceField(
        choices=ACTION_CHOICES,
        widget=forms.Select(attrs={'class': 'form-select'})
    )

    selected_stores = forms.CharField(
        widget=forms.HiddenInput()
    )

    def clean_selected_stores(self):
        data = self.cleaned_data['selected_stores']
        try:
            store_ids = json.loads(data)
            if not isinstance(store_ids, list):
                raise forms.ValidationError(_('Invalid store selection.'))
            return store_ids
        except (json.JSONDecodeError, ValueError):
            raise forms.ValidationError(_('Invalid store selection format.'))

