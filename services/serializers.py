from rest_framework import serializers
from .models import (
    Service, ServiceCategory, ServiceType, ServicePricingTier,
    ServiceAppointment, ServicePackage, ServiceExecution
)


class ServiceCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = ServiceCategory
        fields = '__all__'


class ServiceTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = ServiceType
        fields = '__all__'


class ServicePricingTierSerializer(serializers.ModelSerializer):
    class Meta:
        model = ServicePricingTier
        fields = '__all__'


class ServiceSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source='category.name', read_only=True)
    service_type_name = serializers.CharField(source='service_type.name', read_only=True)
    pricing_tiers = ServicePricingTierSerializer(many=True, read_only=True)

    class Meta:
        model = Service
        fields = '__all__'


class ServiceAppointmentSerializer(serializers.ModelSerializer):
    service_name = serializers.CharField(source='service.name', read_only=True)
    staff_name = serializers.CharField(source='assigned_staff.get_full_name', read_only=True)

    class Meta:
        model = ServiceAppointment
        fields = '__all__'
        read_only_fields = ['appointment_number', 'created_at', 'updated_at']


class ServicePackageSerializer(serializers.ModelSerializer):
    items = serializers.SerializerMethodField()
    total_value = serializers.SerializerMethodField()
    savings = serializers.SerializerMethodField()

    class Meta:
        model = ServicePackage
        fields = '__all__'

    def get_items(self, obj):
        return [{'service': item.service.name, 'quantity': item.quantity} for item in obj.items.all()]

    def get_total_value(self, obj):
        return obj.calculate_total_value()

    def get_savings(self, obj):
        return obj.calculate_savings()


class ServiceExecutionSerializer(serializers.ModelSerializer):
    service_name = serializers.CharField(source='service.name', read_only=True)
    performed_by_name = serializers.CharField(source='performed_by.get_full_name', read_only=True)

    class Meta:
        model = ServiceExecution
        fields = '__all__'
        read_only_fields = ['execution_number', 'actual_duration_minutes', 'created_at', 'updated_at']
