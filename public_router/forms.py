from django import forms
from django.core.validators import RegexValidator
from django.core.exceptions import ValidationError
from django.core.cache import cache
from .models import TenantSignupRequest, SubdomainReservation
from company.models import Company, Domain
import re


class TenantSignupForm(forms.ModelForm):
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter password',
            'minlength': '8'
        }),
        min_length=8,
        help_text='At least 8 characters, including one uppercase letter and one number'
    )
    password_confirm = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Confirm password'
        }),
        label='Confirm Password',
        help_text='Re-enter your password'
    )

    accept_terms = forms.BooleanField(
        required=True,
        error_messages={'required': 'You must accept the terms and conditions'},
        help_text='You must accept the terms to proceed'
    )

    class Meta:
        model = TenantSignupRequest
        fields = [
            'company_name', 'trading_name', 'subdomain',
            'email', 'phone', 'country',
            'first_name', 'last_name', 'admin_email', 'admin_phone',
            'industry', 'business_type', 'estimated_users',
            'selected_plan'
        ]
        widgets = {
            'company_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g., Prime Focus Uganda'
            }),
            'trading_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Optional trading name'
            }),
            'subdomain': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g., prime (if Prime Focus Uganda)',
                'pattern': '[a-z0-9-]+',
                'maxlength': '63'
            }),
            'email': forms.EmailInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter company email'
            }),
            'phone': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Must include country code e.g +256'
            }),
            'country': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Country of operation'
            }),
            'first_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Admin first name'
            }),
            'last_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Admin last name'
            }),
            'admin_email': forms.EmailInput(attrs={
                'class': 'form-control',
                'placeholder': 'Admin email'
            }),
            'admin_phone': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Must include country code e.g +256'
            }),
            'industry': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Industry your company belongs to'
            }),
            'business_type': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Type of business'
            }),
            'estimated_users': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': 'Estimated number of users'
            }),
            'selected_plan': forms.Select(attrs={
                'class': 'form-control'
            }),
        }

    def clean_subdomain(self):
        subdomain = self.cleaned_data['subdomain'].lower().strip()

        # Basic validation
        if not re.match(r'^[a-z0-9-]+$', subdomain):
            raise ValidationError('Only lowercase letters, numbers, and hyphens allowed.')

        if len(subdomain) < 3:
            raise ValidationError('Subdomain must be at least 3 characters.')

        if subdomain.startswith('-') or subdomain.endswith('-'):
            raise ValidationError('Subdomain cannot start or end with a hyphen.')

        # Cache-based duplicate check (fast)
        cache_key = f'subdomain_check_{subdomain}'
        cached_result = cache.get(cache_key)

        if cached_result == 'taken':
            raise ValidationError('This subdomain is already taken.')

        # Reserved subdomains
        reserved = ['www', 'api', 'admin', 'app', 'mail', 'ftp', 'localhost',
                    'staging', 'dev', 'test', 'demo', 'public', 'static', 'media',
                    'blog', 'support', 'help', 'docs', 'status','prime','test','ug']

        if subdomain in reserved:
            raise ValidationError('This subdomain is reserved.')

        # Database checks (with timeout)
        schema_name = f"tenant_{subdomain}"

        # Check blacklist
        if SubdomainReservation.objects.filter(subdomain=subdomain).exists():
            cache.set(cache_key, 'taken', 300)  # Cache for 5 minutes
            raise ValidationError('This subdomain is not available.')

        # Check existing companies
        if Company.objects.filter(schema_name=schema_name).exists():
            cache.set(cache_key, 'taken', 300)
            raise ValidationError('This subdomain is already taken.')

        # Check existing domains
        domain_name = f"{subdomain}.{self.get_base_domain()}"
        if Domain.objects.filter(domain=domain_name).exists():
            cache.set(cache_key, 'taken', 300)
            raise ValidationError('This subdomain is already in use.')

        # Check pending signups
        if TenantSignupRequest.objects.filter(
                subdomain=subdomain,
                status__in=['PENDING', 'PROCESSING']
        ).exists():
            raise ValidationError('This subdomain is currently being processed.')

        # Cache as available
        cache.set(cache_key, 'available', 60)  # Cache for 1 minute

        return subdomain

    def clean_admin_email(self):
        email = self.cleaned_data['admin_email']

        # Check if email already used in recent signups
        from datetime import timedelta
        from django.utils import timezone

        recent_cutoff = timezone.now() - timedelta(hours=24)

        if TenantSignupRequest.objects.filter(
                admin_email=email,
                created_at__gte=recent_cutoff
        ).exists():
            raise ValidationError(
                'This email was recently used for signup. '
                'Please wait 24 hours or use a different email.'
            )

        return email

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get('password')
        password_confirm = cleaned_data.get('password_confirm')

        if password and password_confirm and password != password_confirm:
            raise ValidationError('Passwords do not match.')

        # Password strength check
        if password:
            if len(password) < 8:
                raise ValidationError('Password must be at least 8 characters.')
            if not any(c.isdigit() for c in password):
                raise ValidationError('Password must contain at least one number.')
            if not any(c.isupper() for c in password):
                raise ValidationError('Password must contain at least one uppercase letter.')

        return cleaned_data

    def get_base_domain(self):
        from django.conf import settings
        return getattr(settings, 'BASE_DOMAIN', 'localhost')