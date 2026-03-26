from django import forms
from django.core.validators import RegexValidator
from django.core.exceptions import ValidationError
from django.core.cache import cache
from .models import TenantSignupRequest, SubdomainReservation
from company.models import Company, Domain, SubscriptionPlan, AvailableModule
import re


# Modules the tenant can opt into at signup.
# Each entry is (db_key, human_label, description).
# Keep in sync with AvailableModule seed data.
MODULE_CHOICES = [
    ('sales',       'Sales',          'Invoices, quotes, and customer sales'),
    ('inventory',   'Inventory',      'Stock management and product tracking'),
    ('expenses',    'Expenses',       'Record and categorise business expenses'),
    ('reports',     'Reports',        'Financial and operational reporting'),
    ('customers',   'Customers',      'Customer relationship management'),
    ('driving_school', 'Driving School', 'Driving school management'),
]


class ModuleCheckboxSelectMultiple(forms.CheckboxSelectMultiple):
    """
    Thin subclass so we can attach a CSS class to the <ul> wrapper
    from the widget attrs without patching every template.
    """
    pass


class TenantSignupForm(forms.ModelForm):
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter password',
            'minlength': '8',
        }),
        min_length=8,
        help_text='At least 8 characters, including one uppercase letter and one number',
    )
    password_confirm = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Confirm password',
        }),
        label='Confirm Password',
        help_text='Re-enter your password',
    )
    accept_terms = forms.BooleanField(
        required=True,
        error_messages={'required': 'You must accept the terms and conditions'},
        help_text='You must accept the terms to proceed',
    )

    # ── Module selection ──────────────────────────────────────────────────────
    # Rendered as checkboxes in the template.  The cleaned value is a list of
    # string keys (e.g. ['sales', 'inventory']) which is stored directly in
    # the JSONField.  Not required — tenant can add modules later from settings.
    selected_modules = forms.MultipleChoiceField(
        choices=[(key, label) for key, label, _ in MODULE_CHOICES],
        widget=ModuleCheckboxSelectMultiple(attrs={'class': 'module-checkbox'}),
        required=False,
        label='Modules',
        help_text='Choose the features you need. You can add more later.',
        # Sales + Inventory pre-ticked — most tenants need these from day one.
        initial=['sales', 'inventory'],
    )

    class Meta:
        model = TenantSignupRequest
        fields = [
            'company_name', 'trading_name', 'subdomain',
            'email', 'phone', 'country',
            'first_name', 'last_name', 'admin_email', 'admin_phone',
            'industry', 'business_type', 'estimated_users',
            'selected_plan',
            'selected_modules',
        ]
        widgets = {
            'company_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g., Prime Focus Uganda',
            }),
            'trading_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Optional trading name',
            }),
            'subdomain': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g., prime',
                'pattern': '[a-z0-9-]+',
                'maxlength': '63',
            }),
            'email': forms.EmailInput(attrs={
                'class': 'form-control',
                'placeholder': 'Company email',
            }),
            'phone': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g., +256700000000',
            }),
            'country': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Country of operation',
            }),
            'first_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Admin first name',
            }),
            'last_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Admin last name',
            }),
            'admin_email': forms.EmailInput(attrs={
                'class': 'form-control',
                'placeholder': 'Admin email',
            }),
            'admin_phone': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g., +256700000000',
            }),
            'industry': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Industry your company belongs to',
            }),
            'business_type': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Type of business',
            }),
            'estimated_users': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': 'Estimated number of users',
            }),
            # selected_plan widget is built dynamically in __init__ below
            # selected_modules widget is declared on the field above
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # ── Plan field: load from DB, default to FREE ─────────────────────────
        plans = SubscriptionPlan.objects.filter(is_active=True).order_by('sort_order', 'price')
        free_plan = plans.filter(name='FREE').first()

        self.fields['selected_plan'] = forms.ModelChoiceField(
            queryset=plans,
            empty_label=None,           # no blank "— select —" option
            required=True,
            widget=forms.Select(attrs={'class': 'form-control'}),
            help_text='Choose the plan that fits your business.',
            label='Subscription Plan',
        )
        self.fields['selected_plan'].label_from_instance = self._plan_label

        # Pre-select FREE on a fresh (unbound) form
        if free_plan and not self.instance.pk:
            self.initial['selected_plan'] = free_plan.pk

        # ── Module field: restore initial ticks from existing instance ────────
        # On edit (instance.pk exists) show whatever was saved; on create the
        # field-level `initial` already sets ['sales', 'inventory'].
        if self.instance.pk and self.instance.selected_modules:
            self.initial['selected_modules'] = self.instance.selected_modules

    # ── Label helpers ─────────────────────────────────────────────────────────

    @staticmethod
    def _plan_label(plan):
        """Human-readable option label rendered in the <select> dropdown."""
        name = plan.display_name or plan.get_name_display()
        if plan.price == 0:
            return f"{name} — Free"
        return f"{name} — UGX {int(plan.price):,}/{plan.get_billing_cycle_display().lower()}"

    # ── Field-level validators ────────────────────────────────────────────────

    def clean_subdomain(self):
        subdomain = self.cleaned_data['subdomain'].lower().strip()

        if not re.match(r'^[a-z0-9-]+$', subdomain):
            raise ValidationError('Only lowercase letters, numbers, and hyphens allowed.')
        if len(subdomain) < 3:
            raise ValidationError('Subdomain must be at least 3 characters.')
        if subdomain.startswith('-') or subdomain.endswith('-'):
            raise ValidationError('Subdomain cannot start or end with a hyphen.')

        cache_key = f'subdomain_check_{subdomain}'
        if cache.get(cache_key) == 'taken':
            raise ValidationError('This subdomain is already taken.')

        reserved = [
            'www', 'api', 'admin', 'app', 'mail', 'ftp', 'localhost',
            'staging', 'dev', 'test', 'demo', 'public', 'static', 'media',
            'blog', 'support', 'help', 'docs', 'status', 'prime', 'ug',
        ]
        if subdomain in reserved:
            raise ValidationError('This subdomain is reserved.')

        schema_name = f"tenant_{subdomain}"

        if SubdomainReservation.objects.filter(subdomain=subdomain).exists():
            cache.set(cache_key, 'taken', 300)
            raise ValidationError('This subdomain is not available.')

        if Company.objects.filter(schema_name=schema_name).exists():
            cache.set(cache_key, 'taken', 300)
            raise ValidationError('This subdomain is already taken.')

        domain_name = f"{subdomain}.{self._get_base_domain()}"
        if Domain.objects.filter(domain=domain_name).exists():
            cache.set(cache_key, 'taken', 300)
            raise ValidationError('This subdomain is already in use.')

        if TenantSignupRequest.objects.filter(
            subdomain=subdomain, status__in=['PENDING', 'PROCESSING']
        ).exists():
            raise ValidationError('This subdomain is currently being processed.')

        cache.set(cache_key, 'available', 60)
        return subdomain

    def clean_admin_email(self):
        email = self.cleaned_data['admin_email']
        from datetime import timedelta
        from django.utils import timezone

        recent_cutoff = timezone.now() - timedelta(hours=24)
        if TenantSignupRequest.objects.filter(
            admin_email=email, created_at__gte=recent_cutoff
        ).exists():
            raise ValidationError(
                'This email was recently used for signup. '
                'Please wait 24 hours or use a different email.'
            )
        return email

    def clean_selected_modules(self):
        """
        Validate that every submitted key exists in MODULE_CHOICES.
        Returns a plain list of strings ready for the JSONField.
        """
        valid_keys = {key for key, _, _ in MODULE_CHOICES}
        submitted  = self.cleaned_data.get('selected_modules') or []

        invalid = [k for k in submitted if k not in valid_keys]
        if invalid:
            raise ValidationError(
                f"Unknown module(s): {', '.join(invalid)}. "
                "Please select from the available options."
            )

        # Always include 'sales' and 'inventory' as a minimum baseline.
        # This prevents a tenant from accidentally deselecting core modules.
        baseline = {'sales', 'inventory'}
        merged   = list(baseline | set(submitted))
        return merged

    def clean(self):
        cleaned_data     = super().clean()
        password         = cleaned_data.get('password')
        password_confirm = cleaned_data.get('password_confirm')

        if password and password_confirm and password != password_confirm:
            raise ValidationError('Passwords do not match.')

        if password:
            if len(password) < 8:
                raise ValidationError('Password must be at least 8 characters.')
            if not any(c.isdigit() for c in password):
                raise ValidationError('Password must contain at least one number.')
            if not any(c.isupper() for c in password):
                raise ValidationError('Password must contain at least one uppercase letter.')

        return cleaned_data

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _get_base_domain(self):
        from django.conf import settings
        return getattr(settings, 'BASE_DOMAIN', 'localhost')

    # Keep old name for any callers that used it
    def get_base_domain(self):
        return self._get_base_domain()