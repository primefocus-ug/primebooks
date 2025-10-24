from rest_framework import serializers
from .models import Invoice, InvoiceTemplate, InvoicePayment
from sales.serializers import SaleSerializer

class InvoicePaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = InvoicePayment
        fields = '__all__'
        read_only_fields = ('created_at',)

    def validate(self, data):
        # Only validate logical constraints (no company checks needed)
        if 'invoice' in data and data['invoice'].amount_outstanding < data.get('amount', 0):
            raise serializers.ValidationError("Payment exceeds outstanding invoice amount.")
        return data
class InvoiceSerializer(serializers.ModelSerializer):
    sale_details = SaleSerializer(source='sale', read_only=True)
    payments = InvoicePaymentSerializer(many=True, read_only=True)
    days_overdue = serializers.IntegerField(read_only=True)

    class Meta:
        model = Invoice
        fields = '__all__'
        read_only_fields = (
            'invoice_number', 'created_at', 'updated_at',
            'fiscal_number', 'verification_code', 'qr_code',
            'is_fiscalized', 'fiscalization_time'
        )

    def validate(self, data):
        # Ensure due_date is not before issue_date
        if 'due_date' in data and 'issue_date' in data:
            if data['due_date'] < data['issue_date']:
                raise serializers.ValidationError("Due date must be after issue date")
        return data
class InvoiceTemplateSerializer(serializers.ModelSerializer):
    download_url = serializers.SerializerMethodField()

    class Meta:
        model = InvoiceTemplate
        fields = '__all__'
        read_only_fields = ('created_at', 'updated_at')

    def get_download_url(self, obj):
        request = self.context.get('request')
        if request and obj.template_file:
            return request.build_absolute_uri(obj.template_file.url)
        return None

