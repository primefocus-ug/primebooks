from rest_framework import serializers
from .models import Store, StoreOperatingHours, StoreDevice, DeviceOperatorLog
from branches.models import CompanyBranch
from company.models import Company
from inventory.models import Product
from django.utils.translation import gettext_lazy as _


# Shared mixin to enforce tenant ownership
class TenantStoreSerializerMixin:
    def validate(self, attrs):
        request = self.context.get('request')
        if request and hasattr(request, 'tenant'):
            attrs['company'] = request.tenant
        return attrs


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


class StoreSerializer(serializers.ModelSerializer):
    company = serializers.PrimaryKeyRelatedField(
        queryset=Company.objects.all(),
        required=False
    )

    # Add computed properties
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
            'use_company_efris', 'store_efris_client_id', 'store_efris_api_key',
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

    def get_effective_efris_config(self, obj):
        """Get effective EFRIS configuration"""
        return obj.effective_efris_config

    def get_can_fiscalize(self, obj):
        """Check if store can fiscalize"""
        return obj.can_fiscalize

    def validate(self, attrs):
        """
        Enhanced validation for EFRIS override fields
        """
        attrs = super().validate(attrs)

        request = self.context.get('request')
        use_company_efris = attrs.get('use_company_efris', True)

        # If using store-specific EFRIS, validate required fields
        if not use_company_efris:
            required_fields = [
                'store_efris_client_id',
                'store_efris_api_key',
                'store_efris_private_key',
                'store_efris_public_certificate'
            ]

            for field in required_fields:
                if field not in attrs or not attrs[field]:
                    raise serializers.ValidationError({
                        field: f'This field is required when using store-specific EFRIS configuration.'
                    })

            # Validate store has TIN or company has TIN
            if not attrs.get('tin'):
                company = attrs.get('company') or getattr(request, 'tenant', None)
                if not company or not company.tin:
                    raise serializers.ValidationError({
                        'tin': 'Store TIN is required when using store-specific EFRIS configuration.'
                    })

        return attrs

    def create(self, validated_data):
        """
        Handle EFRIS override fields during creation
        """
        # Extract password and private key for special handling
        store_efris_key_password = validated_data.pop('store_efris_key_password', None)
        store_efris_private_key = validated_data.pop('store_efris_private_key', None)

        # Create the store
        store = super().create(validated_data)

        # Set password and private key if provided
        if store_efris_key_password:
            store.store_efris_key_password = store_efris_key_password
        if store_efris_private_key:
            store.store_efris_private_key = store_efris_private_key

        store.save()
        return store

    def update(self, instance, validated_data):
        """
        Handle EFRIS override fields during update
        """
        # Handle password field specially (don't overwrite if not provided)
        if 'store_efris_key_password' in validated_data:
            password = validated_data.pop('store_efris_key_password')
            if password:  # Only update if new password provided
                instance.store_efris_key_password = password

        # Handle private key specially
        if 'store_efris_private_key' in validated_data:
            private_key = validated_data.pop('store_efris_private_key')
            if private_key:  # Only update if new private key provided
                instance.store_efris_private_key = private_key

        # Update other fields
        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        instance.save()
        return instance


class StoreOperatingHoursSerializer(TenantStoreSerializerMixin, serializers.ModelSerializer):
    store = serializers.PrimaryKeyRelatedField(queryset=Store.objects.all())

    class Meta:
        model = StoreOperatingHours
        fields = ['id', 'store', 'day', 'opening_time', 'closing_time', 'is_closed']
        read_only_fields = ['id']

    def validate_store(self, value):
        request = self.context.get('request')
        if request and hasattr(request, 'tenant') and value.company != request.tenant:
            raise serializers.ValidationError(_("Store must belong to your company."))
        return value


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

    def validate_store(self, value):
        request = self.context.get('request')
        if request and hasattr(request, 'tenant') and value.company != request.tenant:
            raise serializers.ValidationError(_("Store must belong to your company."))
        return value
