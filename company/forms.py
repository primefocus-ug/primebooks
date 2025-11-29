from django import forms
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from django.forms import inlineformset_factory
from .models import Company, Domain, SubscriptionPlan

# Update imports - remove CompanyBranch, add Store
try:
    from stores.models import Store
except ImportError:
    Store = None
    print("WARNING: Store model not available")

try:
    from accounts.models import CustomUser
except ImportError:
    CustomUser = None


class CompanyForm(forms.ModelForm):
    """Enhanced company form with proper field configuration."""

    class Meta:
        model = Company
        fields = [
            # Core Information
            'name',
            'trading_name',
            'schema_name',
            'description',

            # Contact Information
            'physical_address',
            'postal_address',
            'phone',
            'email',
            'website',

            # Tax Information
            'tin',
            'brn',
            'nin',
            'is_vat_enabled',
            'vat_registration_date',
            'preferred_currency',

            # Subscription & Status
            'plan',
            'status',
            'is_trial',
            'trial_ends_at',
            'subscription_starts_at',
            'subscription_ends_at',

            # EFRIS Settings - MATCHING YOUR MODEL EXACTLY
            'efris_enabled',
            'efris_is_production',
            'efris_integration_mode',
            'efris_device_number',
            'efris_auto_fiscalize_sales',
            'efris_auto_sync_products',

            # Localization
            'time_zone',
            'locale',
            'date_format',
            'time_format',

            # Branding
            'logo',
            'favicon',

            # Security
            'is_verified',
            'two_factor_required',

            # Admin
            'notes'
        ]

        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter legal company name',
            }),
            'trading_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter trading name (if different)'
            }),
            'schema_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Database schema name (auto-generated if empty)',
                'readonly': False  # Will be set readonly in __init__ for updates
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Brief description of the company'
            }),
            'physical_address': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Enter physical address'
            }),
            'postal_address': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'P.O. Box address'
            }),
            'phone': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g., +256700000000',
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
            'is_vat_enabled': forms.CheckboxInput(attrs={
                'class': 'form-check-input',
            }),
            'vat_registration_date': forms.DateInput(attrs={
                'class': 'form-control',
                'type': 'date'
            }),
            'preferred_currency': forms.Select(attrs={
                'class': 'form-select'
            }),
            'plan': forms.Select(attrs={
                'class': 'form-select'
            }),
            'status': forms.Select(attrs={
                'class': 'form-select'
            }),
            'is_trial': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
            'trial_ends_at': forms.DateInput(attrs={
                'class': 'form-control',
                'type': 'date'
            }),
            'subscription_starts_at': forms.DateInput(attrs={
                'class': 'form-control',
                'type': 'date'
            }),
            'subscription_ends_at': forms.DateInput(attrs={
                'class': 'form-control',
                'type': 'date'
            }),
            'time_zone': forms.Select(attrs={
                'class': 'form-select'
            }),
            'locale': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g., en-UG, en-US'
            }),
            'date_format': forms.Select(attrs={
                'class': 'form-select'
            }),
            'time_format': forms.Select(attrs={
                'class': 'form-select',
                'required': True
            }),
            # EFRIS widgets - using correct field names from model
            'efris_enabled': forms.CheckboxInput(attrs={
                'class': 'form-check-input',
                'id': 'id_efris_enabled'
            }),
            'efris_is_production': forms.CheckboxInput(attrs={
                'class': 'form-check-input',
                'id': 'id_efris_is_production'
            }),
            'efris_integration_mode': forms.Select(attrs={
                'class': 'form-select'
            }),
            'efris_device_number': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g., 1026925503_01'
            }),
            'efris_auto_fiscalize_sales': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
            'efris_auto_sync_products': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
            'logo': forms.FileInput(attrs={
                'class': 'form-control',
                'accept': 'image/*'
            }),
            'favicon': forms.FileInput(attrs={
                'class': 'form-control',
                'accept': 'image/*'
            }),
            'is_verified': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
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
            'is_vat_enabled': _('Are you VAT'),
            'vat_registration_date': _('VAT Registration Date'),
            'preferred_currency': _('Preferred Currency'),
            'plan': _('Subscription Plan'),
            'status': _('Status'),
            'is_trial': _('Is Trial Account'),
            'trial_ends_at': _('Trial Ends At'),
            'subscription_starts_at': _('Subscription Starts At'),
            'subscription_ends_at': _('Subscription Ends At'),
            'time_zone': _('Time Zone'),
            'locale': _('Locale'),
            'date_format': _('Date Format'),
            'time_format': _('Time Format'),
            # EFRIS labels - matching model fields
            'efris_enabled': _('Enable EFRIS Integration'),
            'efris_is_production': _('Use Production Mode'),
            'efris_integration_mode': _('Integration Mode'),
            'efris_device_number': _('Device Number'),
            'efris_auto_fiscalize_sales': _('Auto-Fiscalize Sales'),
            'efris_auto_sync_products': _('Auto-Sync Products'),
            'logo': _('Company Logo'),
            'favicon': _('Favicon'),
            'is_verified': _('Verified Company'),
            'two_factor_required': _('Require Two-Factor Authentication'),
            'notes': _('Internal Notes'),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Set field requirements
        self.fields['name'].required = True
        self.fields['email'].required = False

        # Schema name handling
        if self.instance and self.instance.pk:
            # For updates, make schema_name readonly
            self.fields['schema_name'].widget.attrs['readonly'] = True
            self.fields['schema_name'].help_text = _('Schema name cannot be changed after creation')
            self.fields['schema_name'].required = False
        else:
            # For new companies, schema_name is required or will be auto-generated
            self.fields['schema_name'].required = False
            self.fields['schema_name'].help_text = _('Leave blank to auto-generate from company name')

        # Populate timezone choices
        try:
            import pytz
            timezone_choices = [(tz, tz.replace('_', ' ')) for tz in pytz.common_timezones]
            self.fields['time_zone'].widget.choices = timezone_choices
        except ImportError:
            self.fields['time_zone'].widget.choices = [
                ('Africa/Kampala', 'Africa/Kampala'),
                ('UTC', 'UTC'),
                ('Africa/Nairobi', 'Africa/Nairobi'),
                ('America/New_York', 'America/New York'),
                ('Europe/London', 'Europe/London'),
            ]

        # Date format choices
        self.fields['date_format'].widget.choices = [
            ('%d/%m/%Y', 'DD/MM/YYYY (31/12/2023)'),
            ('%m/%d/%Y', 'MM/DD/YYYY (12/31/2023)'),
            ('%Y-%m-%d', 'YYYY-MM-DD (2023-12-31)'),
            ('%d-%m-%Y', 'DD-MM-YYYY (31-12-2023)'),
        ]

        # Time format choices - These are already defined in the model
        # No need to override, the model's choices will be used

        # Populate plan choices
        try:
            from .models import SubscriptionPlan
            self.fields['plan'].queryset = SubscriptionPlan.objects.filter(is_active=True).order_by('sort_order',
                                                                                                    'price')
            self.fields['plan'].empty_label = 'Select a plan'
            self.fields['plan'].required = False
        except:
            pass

        # Set initial values for new companies
        if not self.instance.pk:
            self.fields['preferred_currency'].initial = 'UGX'
            self.fields['time_zone'].initial = 'Africa/Kampala'
            self.fields['locale'].initial = 'en-UG'
            self.fields['date_format'].initial = '%d/%m/%Y'
            self.fields['time_format'].initial = '24'
            self.fields['is_trial'].initial = True
            self.fields['status'].initial = 'TRIAL'

        # Add help texts
        self.fields['tin'].help_text = 'Tax Identification Number from URA (required for EFRIS)'
        self.fields['brn'].help_text = 'Business Registration Number from URSB'
        self.fields['nin'].help_text = 'National Identification Number'
        self.fields['efris_enabled'].help_text = 'Master switch for EFRIS integration'
        self.fields['efris_is_production'].help_text = 'Use production EFRIS servers (uncheck for testing)'
        self.fields['efris_integration_mode'].help_text = 'Online or offline mode'
        self.fields['efris_device_number'].help_text = 'EFRIS registered device number'
        self.fields['time_zone'].help_text = 'Company timezone for operations'
        self.fields['locale'].help_text = 'Language and region settings (e.g., en-UG, en-US)'
        self.fields['notes'].help_text = 'Internal notes visible only to administrators'

        # Make EFRIS fields conditionally required in JavaScript, not in Django form
        # They will be validated in clean() method
        self.fields['efris_integration_mode'].required = False
        self.fields['efris_device_number'].required = False

    def clean_schema_name(self):
        """Validate schema name uniqueness and format."""
        schema_name = self.cleaned_data.get('schema_name', '').strip()

        # If this is an update and schema_name hasn't changed, return it
        if self.instance and self.instance.pk:
            if not schema_name or schema_name == self.instance.schema_name:
                return self.instance.schema_name

        # If creating new and no schema_name provided, it will be auto-generated in save()
        if not schema_name:
            return ''

        # Validate format
        schema_name = schema_name.lower()
        import re
        if not re.match(r'^[a-z][a-z0-9_]*$', schema_name):
            raise ValidationError(
                _('Schema name must start with a letter and contain only lowercase letters, numbers, and underscores.')
            )

        # Check length
        if len(schema_name) > 63:
            raise ValidationError(_('Schema name must be 63 characters or less.'))

        # Check uniqueness
        qs = Company.objects.filter(schema_name__iexact=schema_name)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise ValidationError(_('A company with this schema name already exists.'))

        return schema_name

    def clean_tin(self):
        """Validate and format TIN."""
        tin = (self.cleaned_data.get('tin') or '').strip().upper()
        return tin

    def clean_brn(self):
        brn = self.cleaned_data.get('brn')
        if brn:
            brn = brn.strip()
        else:
            brn = ''
        return brn

    def clean_nin(self):
        """Validate and format NIN."""
        nin = (self.cleaned_data.get('nin') or '').strip()  # safe against None
        if nin:
            nin = nin.upper()
        return nin

    def clean_email(self):
        """Validate email format and uniqueness."""
        email = self.cleaned_data.get('email', '').strip().lower()
        if email:
            # Check uniqueness
            qs = Company.objects.filter(email__iexact=email)
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise ValidationError(_('A company with this email already exists.'))
        return email

    def clean_phone(self):
        """Clean and validate phone number."""
        phone = self.cleaned_data.get('phone', '').strip()
        if phone:
            # Remove common formatting characters
            phone = phone.replace(' ', '').replace('-', '').replace('(', '').replace(')', '')
        return phone

    def clean(self):
        """Cross-field validation."""
        cleaned_data = super().clean()

        # EFRIS validation - using correct field names from model
        efris_enabled = cleaned_data.get('efris_enabled', False)

        if efris_enabled:
            # Check required business fields for EFRIS
            tin = cleaned_data.get('tin')
            name = cleaned_data.get('name')
            email = cleaned_data.get('email')
            phone = cleaned_data.get('phone')
            physical_address = cleaned_data.get('physical_address')

            # These are the actual required fields for EFRIS according to your model
            if not tin:
                self.add_error('tin', _('TIN is required when EFRIS is enabled.'))
            if not name:
                self.add_error('name', _('Company name is required when EFRIS is enabled.'))
            if not email:
                self.add_error('email', _('Email is required when EFRIS is enabled.'))
            if not phone:
                self.add_error('phone', _('Phone is required when EFRIS is enabled.'))
            if not physical_address:
                self.add_error('physical_address', _('Physical address is required when EFRIS is enabled.'))

        # Validate subscription dates
        is_trial = cleaned_data.get('is_trial')
        trial_ends_at = cleaned_data.get('trial_ends_at')
        subscription_starts_at = cleaned_data.get('subscription_starts_at')
        subscription_ends_at = cleaned_data.get('subscription_ends_at')

        if is_trial and not trial_ends_at and not self.instance.pk:
            # For new trial accounts, trial_ends_at will be auto-generated in model save
            pass

        if not is_trial:
            if subscription_starts_at and subscription_ends_at:
                if subscription_ends_at <= subscription_starts_at:
                    self.add_error('subscription_ends_at',
                                   _('Subscription end date must be after start date.'))

        return cleaned_data

    def save(self, commit=True):
        """Save with additional processing."""
        instance = super().save(commit=False)

        # Auto-generate schema_name if not provided and it's a new company
        if not instance.pk and not instance.schema_name:
            from django.utils.text import slugify
            import uuid

            # Generate base from company name
            base_name = slugify(instance.name or f"company_{uuid.uuid4().hex[:8]}")
            base_name = base_name.replace('-', '_')[:20]  # Replace hyphens with underscores

            # Ensure it starts with a letter
            if not base_name[0].isalpha():
                base_name = f"c_{base_name}"

            # Add unique suffix
            schema_name = f"{base_name}_{uuid.uuid4().hex[:8]}"

            # Ensure uniqueness
            counter = 1
            original_schema = schema_name
            while Company.objects.filter(schema_name=schema_name).exists():
                schema_name = f"{original_schema}_{counter}"
                counter += 1

            instance.schema_name = schema_name[:63]  # Respect max length

        if commit:
            instance.save()
            self.save_m2m()

        return instance


# --------------------------------------------------------------------
# Company Store Formset (UPDATED - replacing CompanyBranch)
# --------------------------------------------------------------------
if Store is not None:
    CompanyStoreFormSet = inlineformset_factory(
        Company,
        Store,
        fields=[
            'name', 'code', 'location', 'physical_address', 'phone',
            'email', 'tin', 'is_main_branch', 'is_active', 'store_type',
            'efris_enabled', 'efris_device_number'
        ],
        extra=1,
        can_delete=True,
        widgets={
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': _('Store name')
            }),
            'code': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': _('Store code (auto-generated if empty)')
            }),
            'location': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': _('Location/Area')
            }),
            'physical_address': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 2,
                'placeholder': _('Physical address')
            }),
            'phone': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': _('Store phone')
            }),
            'email': forms.EmailInput(attrs={
                'class': 'form-control',
                'placeholder': _('Store email')
            }),
            'tin': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': _('Store TIN (optional)')
            }),
            'store_type': forms.Select(attrs={
                'class': 'form-select'
            }),
            'is_main_branch': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
            'is_active': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
            'efris_enabled': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
            'efris_device_number': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': _('EFRIS device number')
            }),
        }
    )
else:
    CompanyStoreFormSet = None

# Keep backward compatibility alias
CompanyBranchFormSet = CompanyStoreFormSet


# --------------------------------------------------------------------
# Company Employee Formset
# --------------------------------------------------------------------
if CustomUser is not None:
    CompanyEmployeeFormSet = inlineformset_factory(
        Company,
        CustomUser,
        fields=[
            'email', 'username', 'first_name', 'middle_name', 'last_name',
             'phone_number', 'is_active', 'company_admin'
        ],
        extra=1,
        can_delete=True,
        widgets={
            'email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': _('Email')}),
            'username': forms.TextInput(attrs={'class': 'form-control', 'placeholder': _('Username')}),
            'first_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': _('First Name')}),
            'middle_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': _('Middle Name')}),
            'last_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': _('Last Name')}),
            'phone_number': forms.TextInput(attrs={'class': 'form-control', 'placeholder': _('Phone Number')}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'company_admin': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
    )
else:
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
            company = user.company
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

    has_stores = forms.ChoiceField(
        required=False,
        choices=[('', _('Any')), ('yes', _('Has Stores')), ('no', _('No Stores'))],
        widget=forms.Select(attrs={'class': 'form-select'}),
        label=_('Store Status')
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