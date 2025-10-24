from rest_framework import serializers
from .models import EFRISConfiguration, EFRISAPILog, FiscalizationAudit
from company.models import Company


class EFRISConfigurationSerializer(serializers.ModelSerializer):
    """Serializer for EFRIS Configuration"""

    class Meta:
        model = EFRISConfiguration
        fields = [
            'id', 'environment', 'mode', 'api_base_url', 'device_mac',
            'device_number', 'app_id', 'version', 'timeout_seconds',
            'max_retry_attempts', 'auto_sync_enabled', 'auto_fiscalize',
            'is_initialized', 'is_active', 'last_test_connection',
            'test_connection_success', 'certificate_expires_at',
            'last_dictionary_sync', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'last_test_connection']

    def validate_environment(self, value):
        if value not in ['sandbox', 'production']:
            raise serializers.ValidationError("Environment must be 'sandbox' or 'production'")
        return value

    def validate_mode(self, value):
        if value not in ['online', 'offline']:
            raise serializers.ValidationError("Mode must be 'online' or 'offline'")
        return value

    def validate_timeout_seconds(self, value):
        if value < 5 or value > 300:
            raise serializers.ValidationError("Timeout must be between 5 and 300 seconds")
        return value


class EFRISAPILogSerializer(serializers.ModelSerializer):
    """Serializer for EFRIS API Logs"""

    company_name = serializers.CharField(source='company.display_name', read_only=True)
    user_name = serializers.CharField(source='user.get_full_name', read_only=True)

    class Meta:
        model = EFRISAPILog
        fields = [
            'id', 'company_name', 'interface_code', 'status', 'return_code',
            'return_message', 'duration_ms', 'request_time', 'response_time',
            'user_name', 'invoice', 'product'
        ]


class FiscalizationAuditSerializer(serializers.ModelSerializer):
    """Serializer for Fiscalization Audit"""

    company_name = serializers.CharField(source='company.display_name', read_only=True)
    user_name = serializers.CharField(source='user.get_full_name', read_only=True)
    invoice_number = serializers.CharField(source='invoice.invoice_number', read_only=True)
    duration_display = serializers.CharField(read_only=True)

    class Meta:
        model = FiscalizationAudit
        fields = [
            'id', 'company_name', 'action', 'status', 'severity',
            'invoice_number', 'fiscal_document_number', 'verification_code',
            'efris_return_code', 'efris_return_message', 'error_message',
            'started_at', 'completed_at', 'duration_seconds', 'duration_display',
            'user_name', 'retry_count', 'amount', 'tax_amount'
        ]