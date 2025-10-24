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


class DeviceOperatorLogSerializer(TenantStoreSerializerMixin,serializers.ModelSerializer):
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

    class Meta:
        model = Store
        fields = [
            'id', 'company',  'name', 'code', 'physical_address',
            'location_gps', 'latitude', 'longitude', 'region',
            'phone', 'secondary_phone', 'email', 'logo',
            'efris_enabled', 'efris_device_number', 'efris_last_sync',
            'is_active', 'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'code', 'created_at', 'updated_at', 'efris_last_sync'
        ]

    def validate_company(self, value):
        request = self.context.get('request')
        if request and hasattr(request, 'tenant') and value != request.tenant:
            raise serializers.ValidationError(_("Cannot assign store to another company."))
        return value

    def validate(self, attrs):
        """
        Ensure the selected branch belongs to the same company.
        """
        company = attrs.get("company") or getattr(self.context.get("request"), "tenant", None)
        branch = attrs.get("branch")

        if branch and company and branch.company != company:
            raise serializers.ValidationError(
                {"branch": _("Selected branch does not belong to the specified company.")}
            )

        return attrs

    def create(self, validated_data):
        """
        Automatically set company from request.tenant if not explicitly provided.
        """
        request = self.context.get("request")
        if request and hasattr(request, "tenant") and not validated_data.get("company"):
            validated_data["company"] = request.tenant
        return super().create(validated_data)

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
