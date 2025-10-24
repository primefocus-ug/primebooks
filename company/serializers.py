from rest_framework import serializers
from .models import Company, Domain, SubscriptionPlan

class CompanyMinimalSerializer(serializers.ModelSerializer):
    """Minimal serializer for lightweight references (id + name)."""
    display_name = serializers.CharField(read_only=True)

    class Meta:
        model = Company
        fields = ['company_id', 'display_name', 'slug', 'status']


class CompanySerializer(serializers.ModelSerializer):
    """Main serializer for Company model."""
    plan = serializers.SlugRelatedField(slug_field='name', queryset=SubscriptionPlan.objects.all())
    display_name = serializers.CharField(read_only=True)
    employees_count = serializers.IntegerField(read_only=True)
    branches_count = serializers.IntegerField(read_only=True)
    storage_usage_percentage = serializers.FloatField(read_only=True)

    class Meta:
        model = Company
        fields = [
            'company_id', 'name', 'trading_name', 'slug', 'description',
            'physical_address', 'postal_address', 'phone', 'email', 'website',
            'tin', 'brn', 'nin', 'vat_registration_number', 'vat_registration_date',
            'preferred_currency', 'status', 'is_trial', 'trial_ends_at',
            'subscription_starts_at', 'subscription_ends_at', 'grace_period_ends_at',
            'last_payment_date', 'next_billing_date', 'payment_method', 'billing_email',
            'time_zone', 'locale', 'date_format', 'time_format',
            'logo', 'favicon', 'brand_colors',
            'is_verified', 'two_factor_required', 'ip_whitelist',
            'storage_used_mb', 'api_calls_this_month', 'last_activity_at',
            'notes', 'tags', 'created_at', 'updated_at', 'is_active',
            'plan', 'owner', 'display_name', 'employees_count', 'branches_count', 'storage_usage_percentage'
        ]
        read_only_fields = ['company_id', 'slug', 'created_at', 'updated_at']


class CompanyDetailSerializer(CompanySerializer):
    """Detailed serializer including computed and related data."""
    has_active_access = serializers.BooleanField(read_only=True)
    is_trial_active = serializers.BooleanField(read_only=True)
    is_subscription_active = serializers.BooleanField(read_only=True)
    is_in_grace_period = serializers.BooleanField(read_only=True)
    days_until_expiry = serializers.IntegerField(read_only=True)
    domains = serializers.StringRelatedField(many=True)

    class Meta(CompanySerializer.Meta):
        fields = CompanySerializer.Meta.fields + [
            'has_active_access', 'is_trial_active', 'is_subscription_active',
            'is_in_grace_period', 'days_until_expiry', 'domains'
        ]
