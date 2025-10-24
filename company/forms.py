from django import forms
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from django.forms import inlineformset_factory
from .models import Company, Domain, SubscriptionPlan
from branches.models import CompanyBranch

try:
    from branches.models import CompanyBranch
except ImportError:
    # Fallback if the import doesn't work - define a basic model
    class CompanyBranch:
        pass


class CompanyForm(forms.ModelForm):
    """Enhanced company form with proper field configuration."""

    # Define choice fields explicitly to ensure they work correctly
    time_zone = forms.ChoiceField(
        choices=[],  # Will be populated in __init__
        required=True,  # Make this required
        widget=forms.Select(attrs={
            'class': 'form-select',
            'required': True
        })
    )

    date_format = forms.ChoiceField(
        choices=[],  # Will be populated in __init__
        required=True,  # Make this required
        widget=forms.Select(attrs={
            'class': 'form-select',
            'required': True
        })
    )

    time_format = forms.ChoiceField(
        choices=[],  # Will be populated in __init__
        required=True,  # Make this required
        widget=forms.Select(attrs={
            'class': 'form-select',
            'required': True
        })
    )

    preferred_currency = forms.ChoiceField(
        choices=[],  # Will be populated in __init__
        required=False,
        widget=forms.Select(attrs={
            'class': 'form-select'
        })
    )

    class Meta:
        model = Company
        fields = [
            'name', 'trading_name', 'schema_name', 'description', 'physical_address',
            'postal_address', 'phone', 'email', 'website', 'tin', 'brn',
            'nin', 'vat_registration_number', 'vat_registration_date',
            'preferred_currency', 'time_zone', 'locale', 'date_format',
            'time_format', 'efris_enabled', 'efris_client_id',
            'efris_device_number', 'plan', 'logo', 'favicon',
            'two_factor_required', 'notes'
        ]

        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter legal company name',
                'required': True
            }),
            'trading_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter trading name (if different)'
            }),
            'schema_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Database schema name (auto-generated if empty)',
                'required': True
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Brief description of the company'
            }),
            'physical_address': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Enter physical address',
                'required': True
            }),
            'postal_address': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'P.O. Box address'
            }),
            'phone': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g., +256700000000',
                'pattern': r'^\+?[0-9]+$'
            }),
            'email': forms.EmailInput(attrs={
                'class': 'form-control',
                'placeholder': 'company@example.com'
            }),
            'website': forms.URLInput(attrs={
                'class': 'form-control',
                'placeholder': 'https://www.example.com'
            }),
            'tin': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Tax Identification Number',
                'style': 'text-transform: uppercase;'
            }),
            'brn': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Business Registration Number',
                'style': 'text-transform: uppercase;'
            }),
            'nin': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'National Identification Number',
                'style': 'text-transform: uppercase;'
            }),
            'vat_registration_number': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'VAT Registration Number'
            }),
            'vat_registration_date': forms.DateInput(attrs={
                'class': 'form-control',
                'type': 'date'
            }),
            'locale': forms.TextInput(attrs={
                'class': 'form-control',
                'required': True,
                'placeholder': 'e.g., en-US, en-GB'
            }),
            'efris_enabled': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
            'efris_client_id': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'EFRIS Client ID'
            }),
            'efris_device_number': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'EFRIS Device Number'
            }),
            'plan': forms.Select(attrs={
                'class': 'form-select'
            }),
            'logo': forms.FileInput(attrs={
                'class': 'form-control',
                'accept': 'image/*'
            }),
            'favicon': forms.FileInput(attrs={
                'class': 'form-control',
                'accept': 'image/*'
            }),
            'two_factor_required': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
            'notes': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Internal notes about this company'
            })
        }

        labels = {
            'name': _('Legal Company Name'),
            'trading_name': _('Trading Name'),
            'schema_name': _('Database Schema'),
            'description': _('Company Description'),
            'physical_address': _('Physical Address'),
            'postal_address': _('Postal Address'),
            'phone': _('Primary Phone'),
            'email': _('Primary Email'),
            'website': _('Website'),
            'tin': _('TIN'),
            'brn': _('BRN'),
            'nin': _('NIN'),
            'vat_registration_number': _('VAT Registration Number'),
            'vat_registration_date': _('VAT Registration Date'),
            'preferred_currency': _('Preferred Currency'),
            'time_zone': _('Time Zone'),
            'locale': _('Locale'),
            'date_format': _('Date Format'),
            'time_format': _('Time Format'),
            'efris_enabled': _('Enable EFRIS Integration'),
            'efris_client_id': _('EFRIS Client ID'),
            'efris_device_number': _('EFRIS Device Number'),
            'plan': _('Subscription Plan'),
            'logo': _('Company Logo'),
            'favicon': _('Favicon'),
            'two_factor_required': _('Require Two-Factor Authentication'),
            'notes': _('Internal Notes')
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Set field requirements based on your business logic
        self.fields['name'].required = True
        self.fields['schema_name'].required = True
        self.fields['physical_address'].required = True
        self.fields['time_zone'].required = True
        self.fields['locale'].required = True
        self.fields['date_format'].required = True
        self.fields['time_format'].required = True

        # Populate choices - this is critical!
        try:
            import pytz
            timezone_choices = [(tz, tz.replace('_', ' ')) for tz in pytz.common_timezones]
            self.fields['time_zone'].choices = [('', 'Select timezone')] + timezone_choices
            print(f"DEBUG: Loaded {len(timezone_choices)} timezones")
        except ImportError:
            print("WARNING: pytz not available, using fallback timezones")
            self.fields['time_zone'].choices = [
                ('', 'Select timezone'),
                ('Africa/Kampala', 'Africa/Kampala'),
                ('UTC', 'UTC'),
                ('Africa/Nairobi', 'Africa/Nairobi'),
            ]

        # Date format choices
        self.fields['date_format'].choices = [
            ('', 'Select date format'),
            ('%d/%m/%Y', 'DD/MM/YYYY (31/12/2023)'),
            ('%m/%d/%Y', 'MM/DD/YYYY (12/31/2023)'),
            ('%Y-%m-%d', 'YYYY-MM-DD (2023-12-31)'),
            ('%d-%m-%Y', 'DD-MM-YYYY (31-12-2023)'),
        ]

        # Time format choices
        self.fields['time_format'].choices = [
            ('', 'Select time format'),
            ('12', '12 Hour (AM/PM)'),
            ('24', '24 Hour'),
        ]

        # Currency choices
        self.fields['preferred_currency'].choices = [
            ('', 'Select currency'),
            ('UGX', 'Ugandan Shilling (UGX)'),
            ('USD', 'US Dollar (USD)'),
            ('EUR', 'Euro (EUR)'),
            ('GBP', 'British Pound (GBP)'),
            ('KES', 'Kenyan Shilling (KES)'),
        ]

        # Populate plan choices safely
        try:
            # Try to import SubscriptionPlan - adjust the import path as needed
            from companies.models import SubscriptionPlan
            self.fields['plan'].queryset = SubscriptionPlan.objects.filter(is_active=True)
            self.fields['plan'].empty_label = 'Select a plan'
        except (ImportError, AttributeError):
            print("DEBUG: SubscriptionPlan not available")
            pass

        # Set initial values for new companies
        if not self.instance.pk:
            self.fields['preferred_currency'].initial = 'UGX'
            self.fields['time_zone'].initial = 'Africa/Kampala'
            self.fields['locale'].initial = 'en-UG'
            self.fields['date_format'].initial = '%d/%m/%Y'
            self.fields['time_format'].initial = '24'
            print("DEBUG: Set initial values for new company")

        # Add help texts
        self.fields['schema_name'].help_text = 'Unique database schema name (leave blank for auto-generation)'
        self.fields['tin'].help_text = 'Tax Identification Number from URA'
        self.fields['brn'].help_text = 'Business Registration Number from URSB'
        self.fields['nin'].help_text = 'National Identification Number'
        self.fields['efris_enabled'].help_text = 'Enable integration with EFRIS system'
        self.fields['time_zone'].help_text = 'Company timezone for operations'
        self.fields['locale'].help_text = 'Language and region settings (e.g., en-UG, en-US)'

    def clean_schema_name(self):
        """Validate schema name uniqueness and format."""
        schema_name = self.cleaned_data.get('schema_name')
        if schema_name:
            schema_name = schema_name.lower().strip()

            # Basic schema name validation
            import re
            if not re.match(r'^[a-z][a-z0-9_]*$', schema_name):
                raise ValidationError(
                    _('Schema name must start with a letter and contain only lowercase letters, numbers, and underscores.'))

            # Check uniqueness
            qs = Company.objects.filter(schema_name__iexact=schema_name)
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise ValidationError(_('A company with this schema name already exists.'))

        return schema_name

    def clean_tin(self):
        """Validate TIN format."""
        tin = self.cleaned_data.get('tin')
        if tin:
            tin = tin.upper().strip()
            if len(tin) < 8 or not tin.replace('-', '').isalnum():
                raise ValidationError(_('Enter a valid TIN format'))
        return tin

    def clean_email(self):
        """Validate email uniqueness."""
        email = self.cleaned_data.get('email')
        if email:
            qs = Company.objects.filter(email__iexact=email)
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise ValidationError(_('A company with this email already exists.'))
        return email

    def clean(self):
        """Cross-field validation."""
        cleaned_data = super().clean()

        # EFRIS validation
        efris_enabled = cleaned_data.get('efris_enabled')
        if efris_enabled:
            if not cleaned_data.get('efris_client_id'):
                self.add_error('efris_client_id', _('EFRIS Client ID is required when EFRIS is enabled.'))
            if not cleaned_data.get('efris_device_number'):
                self.add_error('efris_device_number', _('EFRIS Device Number is required when EFRIS is enabled.'))

        return cleaned_data

# --------------------------------------------------------------------
# Company Branch Formset
# --------------------------------------------------------------------
try:
    from branches.models import CompanyBranch

    CompanyBranchFormSet = inlineformset_factory(
        Company,
        CompanyBranch,
        fields=['name', 'code', 'location', 'phone', 'email', 'tin', 'is_main_branch', 'is_active'],
        extra=1,
        can_delete=True,
        widgets={
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': _('Branch name')}),
            'code': forms.TextInput(attrs={'class': 'form-control', 'placeholder': _('Branch code')}),
            'location': forms.TextInput(attrs={'class': 'form-control', 'placeholder': _('Branch location')}),
            'phone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': _('Branch phone')}),
            'email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': _('Branch email')}),
            'tin': forms.TextInput(attrs={'class': 'form-control', 'placeholder': _('Branch TIN')}),
            'is_main_branch': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
    )
except ImportError:
    CompanyBranchFormSet = None

try:
    from accounts.models import CustomUser
    CompanyEmployeeFormSet = inlineformset_factory(
        Company,
        CustomUser,
        fields=[
            'email', 'username', 'first_name', 'middle_name', 'last_name',
            'user_type', 'phone_number', 'is_active', 'company_admin'
        ],
        extra=1,
        can_delete=True,
        widgets={
            'email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': _('Email')}),
            'username': forms.TextInput(attrs={'class': 'form-control', 'placeholder': _('Username')}),
            'first_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': _('First Name')}),
            'middle_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': _('Middle Name')}),
            'last_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': _('Last Name')}),
            'user_type': forms.Select(attrs={'class': 'form-select'}),
            'phone_number': forms.TextInput(attrs={'class': 'form-control', 'placeholder': _('Phone Number')}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'company_admin': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
    )
except ImportError:
    CompanyEmployeeFormSet = None

class DomainForm(forms.ModelForm):
    """Form for managing company domains."""

    class Meta:
        model = Domain
        fields = ['tenant', 'domain', 'is_primary', 'ssl_enabled', 'redirect_to_primary']

        widgets = {
            'tenant': forms.Select(attrs={'class': 'form-select', 'required': True}),
            'domain': forms.TextInput(attrs={'class': 'form-control', 'placeholder': _('example.com or subdomain.example.com'), 'required': True}),
            'is_primary': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'ssl_enabled': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'redirect_to_primary': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

        labels = {
            'tenant': _('Company'),
            'domain': _('Domain Name'),
            'is_primary': _('Primary Domain'),
            'ssl_enabled': _('SSL Enabled'),
            'redirect_to_primary': _('Redirect to Primary Domain'),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        # Limit tenant to logged-in user's company
        if user and hasattr(user, 'company'):
            company = user.company  # This has company_id
            self.fields['tenant'].queryset = Company.objects.filter(company_id=company.company_id)
            self.fields['tenant'].initial = company
        else:
            self.fields['tenant'].queryset = Company.objects.none()

        # Help texts
        self.fields['domain'].help_text = _('Enter domain without http:// or https://')
        self.fields['is_primary'].help_text = _('Primary domain is used for company URLs')
        self.fields['redirect_to_primary'].help_text = _('Redirect this domain to the primary domain')


class SearchForm(forms.Form):
    """Enhanced search form with multiple filters."""

    q = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': _('Search companies, TIN, BRN, email...'),
            'autocomplete': 'off'
        }),
        label=_('Search')
    )

    is_verified = forms.ChoiceField(
        required=False,
        choices=[('', _('All')), ('true', _('Verified')), ('false', _('Not Verified'))],
        widget=forms.Select(attrs={'class': 'form-select'}),
        label=_('Verification Status')
    )

    efris_enabled = forms.ChoiceField(
        required=False,
        choices=[('', _('All')), ('true', _('EFRIS Enabled')), ('false', _('EFRIS Disabled'))],
        widget=forms.Select(attrs={'class': 'form-select'}),
        label=_('EFRIS Status')
    )

    currency = forms.ChoiceField(
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'}),
        label=_('Currency')
    )

    status = forms.ChoiceField(
        required=False,
        choices=[('', _('All'))] + Company.STATUS_CHOICES,
        widget=forms.Select(attrs={'class': 'form-select'}),
        label=_('Status')
    )

    plan = forms.ModelChoiceField(
        required=False,
        queryset=SubscriptionPlan.objects.filter(is_active=True),
        empty_label=_('All Plans'),
        widget=forms.Select(attrs={'class': 'form-select'}),
        label=_('Subscription Plan')
    )

    created_after = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={
            'class': 'form-control',
            'type': 'date'
        }),
        label=_('Created After')
    )

    created_before = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={
            'class': 'form-control',
            'type': 'date'
        }),
        label=_('Created Before')
    )

    sort = forms.ChoiceField(
        required=False,
        choices=[
            ('-created_at', _('Newest First')),
            ('created_at', _('Oldest First')),
            ('name', _('Name A-Z')),
            ('-name', _('Name Z-A')),
            ('-is_verified', _('Verified First')),
            ('is_verified', _('Unverified First'))
        ],
        widget=forms.Select(attrs={'class': 'form-select'}),
        label=_('Sort By'),
        initial='-created_at'
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Populate currency choices dynamically
        currency_choices = [('', _('All Currencies'))]
        for choice in Company.CURRENCY_CHOICES:
            currency_choices.append(choice)
        self.fields['currency'].choices = currency_choices


class BulkActionForm(forms.Form):
    """Form for bulk actions on companies."""

    ACTION_CHOICES = [
        ('', _('Select Action')),
        ('verify', _('Mark as Verified')),
        ('unverify', _('Mark as Unverified')),
        ('enable_efris', _('Enable EFRIS')),
        ('disable_efris', _('Disable EFRIS')),
        ('suspend', _('Suspend')),
        ('activate', _('Activate')),
        ('delete', _('Delete'))
    ]

    action = forms.ChoiceField(
        choices=ACTION_CHOICES,
        required=True,
        widget=forms.Select(attrs={
            'class': 'form-select',
            'id': 'bulk-action-select'
        }),
        label=_('Action')
    )

    selected_items = forms.CharField(
        widget=forms.HiddenInput(),
        required=True
    )

    confirm = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(attrs={
            'class': 'form-check-input'
        }),
        label=_('I confirm this action')
    )

    def clean(self):
        """Validate bulk action form."""
        cleaned_data = super().clean()
        action = cleaned_data.get('action')
        selected_items = cleaned_data.get('selected_items')
        confirm = cleaned_data.get('confirm')

        if not action:
            raise ValidationError(_('Please select an action.'))

        if not selected_items:
            raise ValidationError(_('Please select at least one item.'))

        # Validate JSON format of selected items
        try:
            import json
            items = json.loads(selected_items)
            if not isinstance(items, list) or not items:
                raise ValidationError(_('Invalid selection.'))
        except (json.JSONDecodeError, ValueError):
            raise ValidationError(_('Invalid selection format.'))

        # Require confirmation for destructive actions
        if action in ['delete', 'suspend'] and not confirm:
            raise ValidationError(_('Please confirm this action.'))

        return cleaned_data


class SubscriptionPlanForm(forms.ModelForm):
    """Form for managing subscription plans."""

    class Meta:
        model = SubscriptionPlan
        fields = [
            'name', 'display_name', 'description', 'price', 'setup_fee',
            'billing_cycle', 'trial_days', 'max_users', 'max_branches',
            'max_storage_gb', 'max_api_calls_per_month', 'max_transactions_per_month',
            'can_use_api', 'can_export_data', 'can_use_integrations',
            'can_use_advanced_reports', 'can_use_multi_currency',
            'can_use_custom_branding', 'support_level', 'is_active',
            'is_popular', 'sort_order'
        ]

        widgets = {
            'name': forms.Select(attrs={'class': 'form-select'}),
            'display_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': _('Display name for customers')
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': _('Plan description and features')
            }),
            'price': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01'
            }),
            'setup_fee': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01'
            }),
            'billing_cycle': forms.Select(attrs={'class': 'form-select'}),
            'trial_days': forms.NumberInput(attrs={'class': 'form-control'}),
            'max_users': forms.NumberInput(attrs={'class': 'form-control'}),
            'max_branches': forms.NumberInput(attrs={'class': 'form-control'}),
            'max_storage_gb': forms.NumberInput(attrs={'class': 'form-control'}),
            'max_api_calls_per_month': forms.NumberInput(attrs={'class': 'form-control'}),
            'max_transactions_per_month': forms.NumberInput(attrs={'class': 'form-control'}),
            'support_level': forms.Select(attrs={'class': 'form-select'}),
            'sort_order': forms.NumberInput(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Add Bootstrap classes to checkboxes
        checkbox_fields = [
            'can_use_api', 'can_export_data', 'can_use_integrations',
            'can_use_advanced_reports', 'can_use_multi_currency',
            'can_use_custom_branding', 'is_active', 'is_popular'
        ]

        for field_name in checkbox_fields:
            self.fields[field_name].widget.attrs.update({'class': 'form-check-input'})


# Create the formset for company branches
CompanyBranchFormSet = inlineformset_factory(
    Company,
    CompanyBranch,
    fields=['name', 'code', 'location', 'phone', 'email', 'tin', 'is_main_branch', 'is_active'],
    extra=1,
    can_delete=True,
    widgets={
        'name': forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': _('Branch name')
        }),
        'code': forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': _('Branch code')
        }),
        'location': forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': _('Branch location')
        }),
        'phone': forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': _('Branch phone')
        }),
        'email': forms.EmailInput(attrs={
            'class': 'form-control',
            'placeholder': _('Branch email')
        }),
        'tin': forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': _('Branch TIN')
        }),
        'is_main_branch': forms.CheckboxInput(attrs={
            'class': 'form-check-input'
        }),
        'is_active': forms.CheckboxInput(attrs={
            'class': 'form-check-input'
        })
    }
)


class CompanyFilterForm(forms.Form):
    """Advanced filtering form for company lists."""

    name = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': _('Company name contains...')
        })
    )

    location = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': _('Location contains...')
        })
    )

    has_branches = forms.ChoiceField(
        required=False,
        choices=[('', _('Any')), ('yes', _('Has Branches')), ('no', _('No Branches'))],
        widget=forms.Select(attrs={'class': 'form-select'})
    )

    employee_count_min = forms.IntegerField(
        required=False,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': _('Min employees')
        })
    )

    employee_count_max = forms.IntegerField(
        required=False,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': _('Max employees')
        })
    )


class CompanyImportForm(forms.Form):
    """Form for importing companies from CSV."""

    csv_file = forms.FileField(
        widget=forms.FileInput(attrs={
            'class': 'form-control',
            'accept': '.csv',
            'required': True
        }),
        label=_('CSV File'),
        help_text=_('Upload a CSV file with company data. Required columns: name, email, phone')
    )

    update_existing = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(attrs={
            'class': 'form-check-input'
        }),
        label=_('Update Existing Companies'),
        help_text=_('Update existing companies if email matches')
    )

    send_notifications = forms.BooleanField(
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={
            'class': 'form-check-input'
        }),
        label=_('Send Welcome Notifications'),
        help_text=_('Send welcome emails to newly created companies')
    )