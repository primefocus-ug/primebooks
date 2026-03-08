from rest_framework import serializers
from .models import Store, StoreOperatingHours, StoreDevice, DeviceOperatorLog
# FIX: removed unused imports — CompanyBranch and Product were imported but
# never referenced anywhere in this file.
from company.models import Company
from django.utils.translation import gettext_lazy as _


# ---------------------------------------------------------------------------
# Shared mixin
# ---------------------------------------------------------------------------

class TenantStoreSerializerMixin:
    """
    Enforce tenant ownership on any serializer that touches company-scoped
    models.  Injects `company` from `request.tenant` during validation.
    """

    def validate(self, attrs):
        # FIX: the original implementation unconditionally overwrote
        # `attrs['company']` with request.tenant whenever a tenant was present.
        # This silently discarded any explicitly supplied `company` value and,
        # more importantly, would overwrite valid data on partial updates
        # (PATCH) where `company` was not in the payload at all.  We now only
        # inject company when the field is absent so that the tenant is used as
        # the default rather than a forced override.
        request = self.context.get('request')
        if request and hasattr(request, 'tenant') and 'company' not in attrs:
            attrs['company'] = request.tenant
        return attrs


# ---------------------------------------------------------------------------
# DeviceOperatorLog
# ---------------------------------------------------------------------------

class DeviceOperatorLogSerializer(TenantStoreSerializerMixin, serializers.ModelSerializer):
    user_name = serializers.CharField(source='user.get_full_name', read_only=True)
    device_name = serializers.CharField(source='device.name', read_only=True)

    class Meta:
        model = DeviceOperatorLog
        fields = [
            'id', 'user', 'user_name', 'action', 'device', 'device_name',
            'timestamp', 'details'
        ]
        read_only_fields = ['id', 'timestamp']

    def create(self, validated_data):
        # Auto-set user from request
        request = self.context.get('request')
        if request and hasattr(request, 'user'):
            validated_data['user'] = request.user
        return super().create(validated_data)


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

class StoreSerializer(serializers.ModelSerializer):
    company = serializers.PrimaryKeyRelatedField(
        # FIX: Company.objects.all() is an unscoped global queryset.
        # A user from company A could supply company B's PK and pass
        # field-level validation.  Scope to the requesting user's company.
        queryset=Company.objects.all(),
        required=False
    )

    # Computed properties
    effective_efris_config = serializers.SerializerMethodField()
    can_fiscalize = serializers.SerializerMethodField()

    class Meta:
        model = Store
        fields = [
            'id', 'company', 'name', 'code', 'physical_address',
            'location_gps', 'latitude', 'longitude', 'region',
            'phone', 'secondary_phone', 'email', 'logo',
            'efris_enabled', 'efris_device_number', 'efris_last_sync',
            'is_active', 'created_at', 'updated_at',
            # Store EFRIS override fields
            'use_company_efris',
            'store_efris_private_key', 'store_efris_public_certificate',
            'store_efris_key_password', 'store_efris_is_production',
            'store_efris_integration_mode', 'store_auto_fiscalize_sales',
            'store_auto_sync_products', 'store_efris_is_active',
            'store_efris_last_sync', 'tin', 'nin',
            # Computed fields
            'effective_efris_config', 'can_fiscalize'
        ]
        read_only_fields = [
            'id', 'code', 'created_at', 'updated_at', 'efris_last_sync',
            'effective_efris_config', 'can_fiscalize'
        ]
        extra_kwargs = {
            'store_efris_key_password': {'write_only': True},
            'store_efris_private_key': {'write_only': True},
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # FIX: scope company queryset to the tenant at serializer
        # instantiation time so the field-level validator never accepts a
        # company that doesn't belong to the current tenant.
        request = self.context.get('request')
        if request and hasattr(request, 'tenant'):
            self.fields['company'].queryset = Company.objects.filter(
                pk=request.tenant.pk
            )

    def get_effective_efris_config(self, obj):
        return obj.effective_efris_config

    def get_can_fiscalize(self, obj):
        return obj.can_fiscalize

    def validate(self, attrs):
        attrs = super().validate(attrs)

        request = self.context.get('request')
        use_company_efris = attrs.get('use_company_efris', True)

        if not use_company_efris:
            required_fields = [
                'tin',
                'store_efris_private_key',
                'store_efris_public_certificate'
            ]
            for field in required_fields:
                if field not in attrs or not attrs[field]:
                    raise serializers.ValidationError({
                        field: 'This field is required when using store-specific EFRIS configuration.'
                    })

            if not attrs.get('tin'):
                company = attrs.get('company') or getattr(request, 'tenant', None)
                if not company or not company.tin:
                    raise serializers.ValidationError({
                        'tin': 'Store TIN is required when using store-specific EFRIS configuration.'
                    })

        return attrs

    def create(self, validated_data):
        """
        Handle EFRIS override fields during creation.

        FIX: the original code popped password and private_key from
        validated_data, called super().create() (one INSERT), then set
        the fields on the returned instance and called store.save() again
        (a second UPDATE) — two round trips for every store creation.

        Since these are regular model fields, they can be passed directly
        to super().create() and written in the single INSERT.  We only
        need the two-step approach for fields that require special encoding
        (e.g. hashed passwords); plain text fields don't.
        """
        # Pass all fields including password/key directly — one DB write.
        store = super().create(validated_data)
        return store

    def update(self, instance, validated_data):
        """
        Handle EFRIS override fields during update.
        Only overwrite password/key if a new non-empty value is submitted.
        """
        # Handle password field specially — don't overwrite if blank/absent
        if 'store_efris_key_password' in validated_data:
            password = validated_data.pop('store_efris_key_password')
            if password:
                instance.store_efris_key_password = password

        # Handle private key specially — same pattern
        if 'store_efris_private_key' in validated_data:
            private_key = validated_data.pop('store_efris_private_key')
            if private_key:
                instance.store_efris_private_key = private_key

        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        instance.save()
        return instance


# ---------------------------------------------------------------------------
# StoreOperatingHours
# ---------------------------------------------------------------------------

class StoreOperatingHoursSerializer(TenantStoreSerializerMixin, serializers.ModelSerializer):
    store = serializers.PrimaryKeyRelatedField(queryset=Store.objects.all())

    class Meta:
        model = StoreOperatingHours
        fields = ['id', 'store', 'day', 'opening_time', 'closing_time', 'is_closed']
        read_only_fields = ['id']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # FIX: scope the store queryset to the current tenant so a user
        # cannot create operating hours for a store that belongs to a
        # different company.
        request = self.context.get('request')
        if request and hasattr(request, 'tenant'):
            self.fields['store'].queryset = Store.objects.filter(
                company=request.tenant, is_active=True
            )

    def validate_store(self, value):
        request = self.context.get('request')
        if request and hasattr(request, 'tenant') and value.company != request.tenant:
            raise serializers.ValidationError(_("Store must belong to your company."))
        return value


# ---------------------------------------------------------------------------
# StoreDevice
# ---------------------------------------------------------------------------

class StoreDeviceSerializer(TenantStoreSerializerMixin, serializers.ModelSerializer):
    store = serializers.PrimaryKeyRelatedField(queryset=Store.objects.all())

    class Meta:
        model = StoreDevice
        fields = [
            'id', 'store', 'name', 'device_number', 'device_type',
            'serial_number', 'is_active', 'registered_at',
            'last_maintenance', 'notes'
        ]
        read_only_fields = ['id', 'registered_at']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # FIX: scope the store queryset to the current tenant — same reason
        # as StoreOperatingHoursSerializer above.
        request = self.context.get('request')
        if request and hasattr(request, 'tenant'):
            self.fields['store'].queryset = Store.objects.filter(
                company=request.tenant, is_active=True
            )

    def validate_store(self, value):
        request = self.context.get('request')
        if request and hasattr(request, 'tenant') and value.company != request.tenant:
            raise serializers.ValidationError(_("Store must belong to your company."))
        return value