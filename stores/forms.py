from django import forms
from django.utils.translation import gettext_lazy as _
from .models import Store, StoreOperatingHours, StoreDevice
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Fieldset, Submit, Row, Column, HTML
from crispy_forms.bootstrap import Field
import json

from django import forms
from django.core.exceptions import ValidationError
from datetime import datetime, timedelta
from django import forms
from django.utils.translation import gettext_lazy as _
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Fieldset, Row, Column, Field, HTML, Submit
from .models import Store


class StoreForm(forms.ModelForm):
    """Advanced form for Store model with enhanced validation and UI"""

    # Add a helper field for address-based geocoding
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
            'email', 'logo', 'efris_device_number', 'efris_enabled',
            'is_active', 'store_type', 'is_main_branch'
        ]
        widgets = {
            'physical_address': forms.Textarea(attrs={
                'rows': 3,
                'placeholder': 'Enter full physical address...',
                'class': 'form-control',
                'id': 'physical_address_field'
            }),
            'location_gps': forms.TextInput(attrs={
                'placeholder': 'e.g., 0.347596, 32.582520',
                'class': 'form-control',
                'readonly': True  # Make it read-only, populated automatically
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

        if self.user and not self.user.is_saas_admin:
            self.fields['company'].initial = self.tenant
            self.fields['company'].disabled = True

        # Populate geocode_address with physical_address if editing
        if self.instance and self.instance.pk and self.instance.physical_address:
            self.fields['geocode_address'].initial = self.instance.physical_address

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

    def clean(self):
        cleaned_data = super().clean()
        latitude = cleaned_data.get('latitude')
        longitude = cleaned_data.get('longitude')

        # If one coordinate is provided, both should be provided
        if (latitude is not None and longitude is None) or (longitude is not None and latitude is None):
            raise forms.ValidationError(_('Both latitude and longitude must be provided together.'))

        # Auto-populate location_gps if coordinates are provided
        if latitude and longitude:
            cleaned_data['location_gps'] = f"{latitude}, {longitude}"

        return cleaned_data

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

        # Populate store choices based on user permissions
        if user:
            if user.is_superuser or user.primary_role and user.primary_role.priority >= 90:
                stores = Store.objects.filter(is_active=True)
            else:
                stores = user.stores.filter(is_active=True)

            store_choices = [('all', 'All Stores')]
            store_choices.extend([(store.id, store.name) for store in stores.order_by('name')])
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
                raise ValidationError('Start date must be before end date')

            # Validate date range is not too long
            date_diff = (end_date - start_date).days
            if date_diff > 365:
                raise ValidationError('Date range cannot exceed 1 year')

            if date_diff < 0:
                raise ValidationError('Invalid date range')

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
            raise ValidationError('Start date must be before end date')

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
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.layout = Layout(
            Fieldset(
                'Device Information',
                Row(
                    Column('store', css_class='form-group col-md-6 mb-3'),
                    Column('device_type', css_class='form-group col-md-6 mb-3'),
                    css_class='form-row'
                ),
                Row(
                    Column('name', css_class='form-group col-md-6 mb-3'),
                    Column('device_number', css_class='form-group col-md-6 mb-3'),
                    css_class='form-row'
                ),
                Row(
                    Column('serial_number', css_class='form-group col-md-8 mb-3'),
                    Column(
                        Field('is_active', css_class='form-check-input mt-4'),
                        css_class='form-group col-md-4 mb-3'
                    ),
                    css_class='form-row'
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


class StoreStaffAssignmentForm(forms.Form):
    """Form for assigning staff to stores"""

    def __init__(self, store_instance=None, *args, **kwargs):
        self.store = store_instance
        super().__init__(*args, **kwargs)

        if self.store:
            # Get available staff from the same branch
            from django.contrib.auth import get_user_model
            User = get_user_model()

            available_staff = User.objects.filter(
                is_active=True,
                # Add your staff filtering logic here based on your user model
            ).exclude(stores=self.store)

            current_staff = self.store.staff.all()

            self.fields['add_staff'] = forms.ModelMultipleChoiceField(
                queryset=available_staff,
                required=False,
                widget=forms.CheckboxSelectMultiple,
                label=_('Add Staff Members')
            )

            if current_staff.exists():
                self.fields['remove_staff'] = forms.ModelMultipleChoiceField(
                    queryset=current_staff,
                    required=False,
                    widget=forms.CheckboxSelectMultiple,
                    label=_('Remove Staff Members')
                )


class StoreReportForm(forms.Form):
    """Form for generating store reports"""

    REPORT_TYPES = [
        ('summary', 'Store Summary'),
        ('inventory', 'Inventory Report'),
        ('operating_hours', 'Operating Hours'),
        ('devices', 'Device Status'),
        ('staff', 'Staff Assignment'),
    ]

    FORMAT_CHOICES = [
        ('pdf', 'PDF'),
        ('excel', 'Excel'),
        ('csv', 'CSV'),
    ]

    stores = forms.ModelMultipleChoiceField(
        queryset=Store.objects.filter(is_active=True),
        widget=forms.CheckboxSelectMultiple,
        required=True,
        label=_('Select Stores')
    )

    report_type = forms.ChoiceField(
        choices=REPORT_TYPES,
        widget=forms.Select(attrs={'class': 'form-select'}),
        label=_('Report Type')
    )

    format = forms.ChoiceField(
        choices=FORMAT_CHOICES,
        widget=forms.Select(attrs={'class': 'form-select'}),
        initial='pdf',
        label=_('Export Format')
    )

    include_inactive = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        label=_('Include Inactive Items')
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.layout = Layout(
            Fieldset(
                'Report Configuration',
                'stores',
                Row(
                    Column('report_type', css_class='form-group col-md-6 mb-3'),
                    Column('format', css_class='form-group col-md-6 mb-3'),
                    css_class='form-row'
                ),
                Field('include_inactive', css_class='form-check-input mb-3'),
            ),
            Submit('generate', 'Generate Report', css_class='btn btn-success')
        )

class EnhancedStoreReportForm:
    """Enhanced form class to match the new template structure"""

    def __init__(self, data=None, user=None):
        self.data = data or {}
        self.user = user
        self.is_valid_form = True
        self.errors = {}

    def is_valid(self):
        return self.is_valid_form

    @property
    def cleaned_data(self):
        return {
            'report_type': self.data.get('report_type'),
            'store_select': self.data.get('store_select'),
            'start_date': self.data.get('start_date'),
            'end_date': self.data.get('end_date'),
            'export_format': self.data.get('export_format')}