from rest_framework import serializers
from .models import (
    SavedReport, 
    ReportSchedule, 
    GeneratedReport,
    EFRISReportTemplate
)
from accounts.serializers import UserSerializer



class SavedReportSerializer(serializers.ModelSerializer):
    created_by_details = UserSerializer(source='created_by', read_only=True)

    class Meta:
        model = SavedReport
        fields = '__all__'
        read_only_fields = (
            'created_at',
            'last_modified',
            'is_efris_approved',
            'created_by'
        )

    def create(self, validated_data):
        user = self.context['request'].user
        validated_data['created_by'] = user
        return super().create(validated_data)


class ReportScheduleSerializer(serializers.ModelSerializer):
    report_details = SavedReportSerializer(source='report', read_only=True)

    class Meta:
        model = ReportSchedule
        fields = '__all__'
        read_only_fields = ('last_sent', 'next_scheduled')

    def validate(self, data):
        report = data.get('report') or (self.instance.report if self.instance else None)
        user = self.context['request'].user
        if report and report.created_by.company != getattr(user, 'company', None):
            raise serializers.ValidationError("You do not have access to this report.")
        return data


class GeneratedReportSerializer(serializers.ModelSerializer):
    report_details = SavedReportSerializer(source='report', read_only=True)
    generated_by_details = UserSerializer(source='generated_by', read_only=True)
    download_url = serializers.SerializerMethodField()

    class Meta:
        model = GeneratedReport
        fields = '__all__'
        read_only_fields = (
            'generated_at',
            'is_efris_verified',
            'efris_verification_code',
            'file_path',
            'generated_by'
        )

    def get_download_url(self, obj):
        request = self.context.get('request')
        if request and obj.file_path:
            return request.build_absolute_uri(obj.file_path)
        return None

    def create(self, validated_data):
        validated_data['generated_by'] = self.context['request'].user
        return super().create(validated_data)


class EFRISReportTemplateSerializer(serializers.ModelSerializer):
    download_url = serializers.SerializerMethodField()

    class Meta:
        model = EFRISReportTemplate
        fields = '__all__'
        read_only_fields = ('version', 'valid_from', 'template_file')

    def get_download_url(self, obj):
        request = self.context.get('request')
        if request and obj.template_file:
            return request.build_absolute_uri(obj.template_file.url)
        return None



class ZReportRequestSerializer(serializers.Serializer):
    store_id = serializers.IntegerField()
    start_date = serializers.DateField()
    end_date = serializers.DateField()
    include_efris_data = serializers.BooleanField(default=True)
    format = serializers.ChoiceField(choices=['PDF', 'XLSX', 'CSV'])


class TaxReportRequestSerializer(serializers.Serializer):
    period = serializers.ChoiceField(choices=[
        ('DAILY', 'Daily'),
        ('WEEKLY', 'Weekly'),
        ('MONTHLY', 'Monthly'),
        ('QUARTERLY', 'Quarterly'),
        ('YEARLY', 'Yearly'),
        ('CUSTOM', 'Custom Date Range'),
    ])
    start_date = serializers.DateField(required=False)
    end_date = serializers.DateField(required=False)
    tax_type = serializers.ChoiceField(choices=[
        ('VAT', 'Value Added Tax'),
        ('INCOME', 'Income Tax'),
        ('EXCISE', 'Excise Duty'),
        ('ALL', 'All Taxes'),
    ])
    include_breakdown = serializers.BooleanField(default=True)


class EFRISComplianceReportSerializer(serializers.Serializer):
    start_date = serializers.DateField()
    end_date = serializers.DateField()
    report_type = serializers.ChoiceField(choices=[
        ('FISCALIZATION', 'Fiscalization Status'),
        ('DOCUMENTS', 'Document Compliance'),
        ('DEVICES', 'Device Compliance'),
        ('FULL', 'Full Compliance Report'),
    ])
    format = serializers.ChoiceField(choices=['PDF', 'XLSX'])


class ReportExportSerializer(serializers.Serializer):
    report_id = serializers.IntegerField()
    format = serializers.ChoiceField(choices=['PDF', 'XLSX', 'CSV', 'JSON'])
    parameters = serializers.JSONField(required=False, default=dict)

    def validate_report_id(self, value):
        user = self.context['request'].user
        # Since company field is removed, validate report belongs to user's scope in other way if needed
        if not SavedReport.objects.filter(id=value, created_by=user).exists():
            raise serializers.ValidationError("You do not have access to this report.")
        return value
