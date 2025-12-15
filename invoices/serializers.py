from rest_framework import serializers
from decimal import Decimal
from .models import Invoice, InvoicePayment, InvoiceTemplate
from sales.serializers import SaleSerializer


class InvoicePaymentSerializer(serializers.ModelSerializer):
    """Serializer for invoice payments"""

    processed_by_name = serializers.CharField(
        source='processed_by.get_full_name',
        read_only=True
    )
    payment_method_display = serializers.CharField(
        source='get_payment_method_display',
        read_only=True
    )

    class Meta:
        model = InvoicePayment
        fields = [
            'id', 'invoice', 'amount', 'payment_method',
            'payment_method_display', 'transaction_reference',
            'payment_date', 'notes', 'processed_by',
            'processed_by_name', 'created_at'
        ]
        read_only_fields = ['id', 'created_at', 'processed_by']

    def validate_amount(self, value):
        """Validate payment amount"""
        if value <= 0:
            raise serializers.ValidationError(
                "Payment amount must be greater than 0."
            )
        return value


class InvoiceListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for invoice lists"""

    invoice_number = serializers.CharField(read_only=True)
    issue_date = serializers.DateField(read_only=True)
    due_date = serializers.DateField(read_only=True)
    total_amount = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        read_only=True
    )
    amount_paid = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        read_only=True
    )
    amount_outstanding = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        read_only=True
    )

    customer_name = serializers.SerializerMethodField()
    status_display = serializers.SerializerMethodField()
    days_overdue = serializers.IntegerField(read_only=True)

    class Meta:
        model = Invoice
        fields = [
            'id', 'invoice_number', 'issue_date', 'due_date',
            'total_amount', 'amount_paid', 'amount_outstanding',
            'customer_name', 'status_display', 'is_fiscalized',
            'fiscal_document_number', 'days_overdue', 'created_at'
        ]

    def get_customer_name(self, obj):
        """Get customer name from sale"""
        return obj.customer.name if obj.customer else 'Walk-in Customer'

    def get_status_display(self, obj):
        """Get status display from sale"""
        return obj.sale.get_status_display() if obj.sale else ''


class InvoiceDetailSerializer(serializers.ModelSerializer):
    """Detailed serializer for invoice detail views"""

    # Read-only properties from sale
    invoice_number = serializers.CharField(read_only=True)
    issue_date = serializers.DateField(read_only=True)
    due_date = serializers.DateField(read_only=True)
    subtotal = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        read_only=True
    )
    tax_amount = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        read_only=True
    )
    discount_amount = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        read_only=True
    )
    total_amount = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        read_only=True
    )
    amount_paid = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        read_only=True
    )
    amount_outstanding = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        read_only=True
    )
    currency_code = serializers.CharField(read_only=True)

    # Related data
    sale = SaleSerializer(read_only=True)
    payments = InvoicePaymentSerializer(many=True, read_only=True)

    # Display fields
    efris_document_type_display = serializers.CharField(
        source='get_efris_document_type_display',
        read_only=True
    )
    business_type_display = serializers.CharField(
        source='get_business_type_display',
        read_only=True
    )
    fiscalization_status_display = serializers.CharField(
        source='get_fiscalization_status_display',
        read_only=True
    )

    # Computed fields
    customer_name = serializers.SerializerMethodField()
    days_overdue = serializers.IntegerField(read_only=True)
    is_overdue = serializers.BooleanField(read_only=True)
    can_fiscalize_status = serializers.BooleanField(read_only=True)

    # User info
    created_by_name = serializers.CharField(
        source='created_by.get_full_name',
        read_only=True
    )
    fiscalized_by_name = serializers.CharField(
        source='fiscalized_by.get_full_name',
        read_only=True
    )

    class Meta:
        model = Invoice
        fields = [
            'id', 'sale', 'invoice_number', 'issue_date', 'due_date',
            'subtotal', 'tax_amount', 'discount_amount', 'total_amount',
            'amount_paid', 'amount_outstanding', 'currency_code',
            'terms', 'purchase_order', 'efris_document_type',
            'efris_document_type_display', 'business_type',
            'business_type_display', 'fiscal_document_number',
            'fiscal_number', 'verification_code', 'qr_code',
            'fiscalization_error', 'efris_status', 'device_number',
            'operator_name', 'fiscalization_status',
            'fiscalization_status_display', 'is_fiscalized',
            'fiscalization_time', 'original_fdn', 'requires_ura_approval',
            'ura_approved', 'ura_approval_date', 'auto_fiscalize',
            'customer_name', 'days_overdue', 'is_overdue',
            'can_fiscalize_status', 'payments', 'created_by_name',
            'fiscalized_by_name', 'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'fiscal_document_number', 'fiscal_number',
            'verification_code', 'qr_code', 'fiscalization_status',
            'is_fiscalized', 'fiscalization_time', 'created_at',
            'updated_at'
        ]

    def get_customer_name(self, obj):
        """Get customer name"""
        return obj.customer.name if obj.customer else 'Walk-in Customer'


class InvoiceCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating invoices"""

    class Meta:
        model = Invoice
        fields = [
            'sale', 'terms', 'purchase_order', 'efris_document_type',
            'business_type', 'auto_fiscalize'
        ]

    def validate_sale(self, value):
        """Validate sale can have an invoice"""
        # Check if sale already has invoice detail
        if hasattr(value, 'invoice_detail') and value.invoice_detail:
            raise serializers.ValidationError(
                "This sale already has an invoice detail."
            )

        # Check sale status
        if value.status not in ['COMPLETED', 'PAID', 'PARTIALLY_PAID']:
            raise serializers.ValidationError(
                "Only completed or paid sales can have invoices."
            )

        # Check document type
        if value.document_type != 'INVOICE':
            raise serializers.ValidationError(
                "Only invoice-type sales can have invoice details."
            )

        return value

    def create(self, validated_data):
        """Create invoice with user context"""
        user = self.context.get('request').user if self.context.get('request') else None

        invoice = Invoice.objects.create(
            **validated_data,
            created_by=user
        )

        return invoice


class InvoiceUpdateSerializer(serializers.ModelSerializer):
    """Serializer for updating invoices"""

    class Meta:
        model = Invoice
        fields = [
            'terms', 'purchase_order', 'auto_fiscalize'
        ]

    def validate(self, attrs):
        """Prevent editing fiscalized invoices"""
        if self.instance and self.instance.is_fiscalized:
            raise serializers.ValidationError(
                "Cannot edit fiscalized invoices."
            )
        return attrs


class InvoiceFiscalizationSerializer(serializers.Serializer):
    """Serializer for invoice fiscalization"""

    confirm = serializers.BooleanField(required=True)
    notes = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=500
    )

    def validate_confirm(self, value):
        """Validate fiscalization confirmation"""
        if not value:
            raise serializers.ValidationError(
                "You must confirm before fiscalization."
            )
        return value

    def validate(self, attrs):
        """Validate invoice can be fiscalized"""
        invoice = self.context.get('invoice')
        if not invoice:
            raise serializers.ValidationError("Invoice not found in context.")

        can_fiscalize, message = invoice.can_fiscalize()
        if not can_fiscalize:
            raise serializers.ValidationError(message)

        return attrs


class InvoiceTemplateSerializer(serializers.ModelSerializer):
    """Serializer for invoice templates"""

    created_by_name = serializers.CharField(
        source='created_by.get_full_name',
        read_only=True
    )

    class Meta:
        model = InvoiceTemplate
        fields = [
            'id', 'name', 'template_file', 'is_default',
            'is_efris_compliant', 'version', 'created_by',
            'created_by_name', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_by', 'created_at', 'updated_at']

    def validate_is_default(self, value):
        """Ensure only one default template"""
        if value:
            existing_default = InvoiceTemplate.objects.filter(
                is_default=True
            ).exclude(pk=self.instance.pk if self.instance else None)

            if existing_default.exists():
                raise serializers.ValidationError(
                    "Another default template already exists."
                )

        return value


class InvoiceStatsSerializer(serializers.Serializer):
    """Serializer for invoice statistics"""

    total_invoices = serializers.IntegerField()
    total_amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    pending_amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    overdue_count = serializers.IntegerField()
    fiscalized_count = serializers.IntegerField()
    fiscalization_rate = serializers.DecimalField(
        max_digits=5,
        decimal_places=2
    )
    collection_rate = serializers.DecimalField(
        max_digits=5,
        decimal_places=2
    )
    avg_invoice_amount = serializers.DecimalField(
        max_digits=12,
        decimal_places=2
    )


class BulkFiscalizationSerializer(serializers.Serializer):
    """Serializer for bulk fiscalization"""

    invoice_ids = serializers.ListField(
        child=serializers.IntegerField(),
        min_length=1,
        max_length=100
    )
    confirm = serializers.BooleanField(required=True)

    def validate_confirm(self, value):
        """Validate confirmation"""
        if not value:
            raise serializers.ValidationError(
                "You must confirm bulk fiscalization."
            )
        return value

    def validate_invoice_ids(self, value):
        """Validate invoice IDs exist"""
        if not value:
            raise serializers.ValidationError(
                "At least one invoice must be selected."
            )

        # Check if invoices exist
        existing_count = Invoice.objects.filter(id__in=value).count()
        if existing_count != len(value):
            raise serializers.ValidationError(
                f"Some invoice IDs are invalid. "
                f"Found {existing_count} of {len(value)} invoices."
            )

        return value