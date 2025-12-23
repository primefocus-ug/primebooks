from decimal import Decimal, InvalidOperation

from rest_framework import serializers
from .models import Customer, CustomerGroup, CustomerNote, EFRISCustomerSync, CustomerCreditStatement
from accounts.serializers import UserSerializer


class CustomerSerializer(serializers.ModelSerializer):
    primary_identification = serializers.ReadOnlyField()
    is_efris_registered = serializers.ReadOnlyField()
    can_sync_to_efris = serializers.ReadOnlyField()
    tax_details = serializers.ReadOnlyField()
    has_overdue_invoices = serializers.ReadOnlyField()
    total_outstanding = serializers.ReadOnlyField()
    overdue_amount = serializers.ReadOnlyField()
    credit_status_display = serializers.CharField(source='get_credit_status_display', read_only=True)
    customer_type_display = serializers.CharField(source='get_customer_type_display', read_only=True)
    efris_status_display = serializers.CharField(source='get_efris_status_display', read_only=True)
    store_name = serializers.CharField(source='store.name', read_only=True)

    # Computed credit methods
    can_purchase_on_credit = serializers.SerializerMethodField()

    class Meta:
        model = Customer
        fields = [
            'id', 'customer_id',
            'customer_type', 'customer_type_display', 'name', 'store', 'store_name', 'email', 'phone',
            'tin', 'nin', 'brn',
            'physical_address', 'postal_address', 'district', 'country',
            'is_vat_registered', 'is_active',

            # Credit management fields
            'credit_limit', 'credit_balance', 'credit_available',
            'allow_credit', 'credit_days', 'last_credit_review',
            'credit_status', 'credit_status_display',

            # eFRIS fields
            'efris_customer_type', 'efris_customer_id', 'efris_status', 'efris_status_display',
            'efris_registered_at', 'efris_last_sync', 'efris_reference_no',
            'efris_sync_error',

            # Additional identification fields
            'passport_number', 'driving_license', 'voter_id', 'alien_id',

            # Computed properties
            'primary_identification', 'is_efris_registered', 'can_sync_to_efris',
            'tax_details', 'has_overdue_invoices', 'total_outstanding',
            'overdue_amount', 'can_purchase_on_credit',

            # User and timestamps
            'created_by', 'created_at', 'updated_at'
        ]
        read_only_fields = (
            'customer_id', 'efris_customer_type', 'efris_customer_id',
            'efris_status', 'efris_registered_at', 'efris_last_sync',
            'efris_reference_no', 'efris_sync_error',
            'primary_identification', 'is_efris_registered', 'can_sync_to_efris',
            'tax_details', 'has_overdue_invoices', 'total_outstanding',
            'overdue_amount', 'can_purchase_on_credit',
            'credit_balance', 'credit_available', 'credit_status',
            'created_by', 'created_at', 'updated_at'
        )

    def validate(self, data):
        customer_type = data.get('customer_type')

        # Business type validations
        if customer_type == 'BUSINESS':
            if not data.get('tin') and not data.get('brn'):
                raise serializers.ValidationError(
                    "Business customers must have either TIN or BRN."
                )

        # Individual type validations
        if customer_type == 'INDIVIDUAL':
            if not any([data.get('nin'), data.get('passport_number'),
                        data.get('driving_license'), data.get('voter_id')]):
                raise serializers.ValidationError(
                    "Individual customers must have at least one form of identification "
                    "(NIN, Passport, Driving License, or Voter ID)."
                )

        # Credit limit validation
        credit_limit = data.get('credit_limit')
        if credit_limit is not None:
            try:
                credit_limit_decimal = Decimal(str(credit_limit))
                if credit_limit_decimal < Decimal('0'):
                    raise serializers.ValidationError({
                        'credit_limit': "Credit limit cannot be negative."
                    })
            except (ValueError, TypeError, InvalidOperation):
                raise serializers.ValidationError({
                    'credit_limit': "Invalid credit limit value."
                })

        # Credit days validation
        credit_days = data.get('credit_days')
        if credit_days is not None and credit_days < 0:
            raise serializers.ValidationError({
                'credit_days': "Credit days cannot be negative."
            })

        return data

    def validate_phone(self, value):
        if value:
            # Remove any spaces
            phone = value.strip()

            # Auto-add Uganda country code if not provided
            if not phone.startswith('+'):
                if phone.startswith('0'):
                    phone = '+256' + phone[1:]
                elif phone.startswith('256'):
                    phone = '+' + phone
                else:
                    phone = '+256' + phone

            # Validate phone number format
            import re
            phone_pattern = r'^\+[1-9]\d{1,14}$'  # E.164 format
            if not re.match(phone_pattern, phone):
                raise serializers.ValidationError(
                    "Enter a valid phone number in international format (e.g., +256XXXXXXXXX)."
                )

            return phone
        return value

    def get_can_purchase_on_credit(self, obj):
        """Serialize the can_purchase_on_credit property"""
        can_purchase, reason = obj.can_purchase_on_credit
        return {
            'can_purchase': can_purchase,
            'reason': reason,
            'limit_exceeded': obj.credit_balance + Decimal('0.01') > obj.credit_limit
        }

    def create(self, validated_data):
        # Set created_by to current user
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            validated_data['created_by'] = request.user

        # Calculate initial credit available
        if 'credit_limit' in validated_data:
            validated_data['credit_available'] = validated_data['credit_limit']

        return super().create(validated_data)

    def update(self, instance, validated_data):
        # Update credit available if credit limit changes
        if 'credit_limit' in validated_data:
            new_limit = validated_data['credit_limit']
            old_limit = instance.credit_limit

            if new_limit != old_limit:
                # Calculate new credit available
                validated_data['credit_available'] = max(
                    Decimal('0'),
                    new_limit - instance.credit_balance
                )

        return super().update(instance, validated_data)

# 🔹 Customer Group Serializer
class CustomerGroupSerializer(serializers.ModelSerializer):
    customer_count = serializers.SerializerMethodField()
    efris_registered_count = serializers.ReadOnlyField()
    efris_pending_count = serializers.ReadOnlyField()

    class Meta:
        model = CustomerGroup
        fields = [
            'id', 'name', 'description', 'discount_percentage',
            'customers', 'auto_sync_to_efris',
            'customer_count', 'efris_registered_count', 'efris_pending_count',
            'created_at', 'updated_at'
        ]
        read_only_fields = ('created_at', 'updated_at', 'efris_registered_count', 'efris_pending_count')

    def get_customer_count(self, obj):
        return obj.customers.count()


# Add to your serializers.py
class CustomerCreditInfoSerializer(serializers.ModelSerializer):
    """Serializer for customer credit information"""
    can_purchase_on_credit = serializers.SerializerMethodField()
    credit_status_display = serializers.CharField(source='get_credit_status_display')

    class Meta:
        model = Customer
        fields = [
            'id', 'name', 'phone', 'email',
            'credit_limit', 'credit_balance', 'credit_available',
            'credit_status', 'credit_status_display',
            'allow_credit', 'credit_days', 'has_overdue_invoices',
            'overdue_amount', 'can_purchase_on_credit'
        ]

    def get_can_purchase_on_credit(self, obj):
        can_purchase, reason = obj.can_purchase_on_credit
        return {
            'can_purchase': can_purchase,
            'reason': reason
        }


class CustomerCreditStatementSerializer(serializers.ModelSerializer):
    """Serializer for customer credit statements"""
    customer_name = serializers.CharField(source='customer.name', read_only=True)
    transaction_type_display = serializers.CharField(source='get_transaction_type_display', read_only=True)

    class Meta:
        model = CustomerCreditStatement
        fields = [
            'id', 'customer', 'customer_name', 'transaction_type',
            'transaction_type_display', 'amount', 'balance_before',
            'balance_after', 'description', 'reference_number',
            'created_by', 'created_at'
        ]
        read_only_fields = ['created_at']

# 🔹 Customer Note Serializer
class CustomerNoteSerializer(serializers.ModelSerializer):
    customer_details = CustomerSerializer(source='customer', read_only=True)
    author_details = UserSerializer(source='author', read_only=True)

    class Meta:
        model = CustomerNote
        fields = [
            'id', 'customer', 'customer_details',
            'author', 'author_details',
            'note', 'category', 'is_important',
            'created_at', 'updated_at'
        ]
        read_only_fields = ('created_at', 'updated_at')


# 🔹 eFRIS Customer Serializer
class EFRISCustomerSerializer(serializers.ModelSerializer):
    """Serializer for eFRIS-specific customer data"""
    efris_payload = serializers.SerializerMethodField()

    class Meta:
        model = Customer
        fields = [
            'id', 'customer_id', 'name', 'customer_type',
            'efris_customer_type', 'efris_customer_id', 'efris_status',
            'efris_registered_at', 'efris_last_sync', 'efris_reference_no',
            'efris_sync_error', 'phone', 'email',
            'tin', 'nin', 'brn', 'passport_number', 'driving_license',
            'voter_id', 'alien_id', 'physical_address', 'postal_address',
            'can_sync_to_efris', 'is_efris_registered', 'efris_payload'
        ]
        read_only_fields = (
            'customer_id', 'efris_customer_type', 'efris_customer_id',
            'efris_status', 'efris_registered_at', 'efris_last_sync',
            'efris_reference_no', 'efris_sync_error', 'can_sync_to_efris',
            'is_efris_registered', 'efris_payload'
        )

    def get_efris_payload(self, obj):
        """Get the eFRIS payload for this customer"""
        return obj.get_efris_payload()


# 🔹 eFRIS Sync Serializer
class EFRISSyncSerializer(serializers.ModelSerializer):
    """Serializer for eFRIS sync operations"""
    customer_name = serializers.CharField(source='customer.name', read_only=True)
    customer_phone = serializers.CharField(source='customer.phone', read_only=True)
    can_retry = serializers.ReadOnlyField()

    class Meta:
        model = EFRISCustomerSync
        fields = [
            'id', 'customer', 'customer_name', 'customer_phone',
            'sync_type', 'status', 'request_payload', 'response_data',
            'error_message', 'efris_reference', 'retry_count', 'max_retries',
            'can_retry', 'created_at', 'updated_at', 'processed_at'
        ]
        read_only_fields = (
            'customer_name', 'customer_phone', 'can_retry',
            'created_at', 'updated_at', 'processed_at'
        )

    def validate(self, data):
        """Validate sync data"""
        customer = data.get('customer')
        sync_type = data.get('sync_type')

        if customer and not customer.can_sync_to_efris:
            raise serializers.ValidationError(
                f"Customer {customer.name} does not have required data for eFRIS sync."
            )

        return data


# 🔹 Tax-only Serializer (for EFRIS, etc.)
class CustomerTaxInfoSerializer(serializers.ModelSerializer):
    primary_identification = serializers.ReadOnlyField()

    class Meta:
        model = Customer
        fields = [
            'customer_id', 'name', 'customer_type',
            'tin', 'nin', 'brn', 'passport_number',
            'is_vat_registered', 'physical_address', 'postal_address',
            'efris_customer_id', 'efris_status',
            'primary_identification'
        ]
        read_only_fields = ('primary_identification',)


# 🔹 Import Serializer
class CustomerImportSerializer(serializers.Serializer):
    file = serializers.FileField()
    update_existing = serializers.BooleanField(default=False)

    def validate_file(self):
        file = self.validated_data.get('file')
        if file:
            if not file.name.endswith(('.csv', '.xlsx', '.xls')):
                raise serializers.ValidationError('Only CSV and Excel files are allowed.')
            if file.size > 5 * 1024 * 1024:  # 5MB limit
                raise serializers.ValidationError('File size cannot exceed 5MB.')
        return file


# 🔹 Export Serializer
class CustomerExportSerializer(serializers.Serializer):
    format = serializers.ChoiceField(choices=['CSV', 'XLSX', 'JSON'])
    include_tax_info = serializers.BooleanField(default=True)
    include_efris_info = serializers.BooleanField(default=False)
    customer_type = serializers.ChoiceField(
        choices=[('ALL', 'All')] + Customer.CUSTOMER_TYPES,
        default='ALL',
        required=False
    )
    efris_status = serializers.ChoiceField(
        choices=[('ALL', 'All')] + Customer.EFRIS_STATUS_CHOICES,
        default='ALL',
        required=False
    )


# 🔹 Bulk Action Serializer
class CustomerBulkActionSerializer(serializers.Serializer):
    ACTION_CHOICES = [
        ('activate', 'Activate Selected'),
        ('deactivate', 'Deactivate Selected'),
        ('sync_to_efris', 'Sync to eFRIS'),
        ('add_to_group', 'Add to Group'),
        ('remove_from_group', 'Remove from Group'),
        ('export', 'Export Selected'),
        ('delete', 'Delete Selected'),
    ]

    action = serializers.ChoiceField(choices=ACTION_CHOICES)
    customer_ids = serializers.ListField(
        child=serializers.IntegerField(),
        allow_empty=False
    )
    group_id = serializers.IntegerField(required=False)

    def validate(self, data):
        action = data.get('action')
        group_id = data.get('group_id')

        if action in ['add_to_group', 'remove_from_group'] and not group_id:
            raise serializers.ValidationError(
                'Group ID is required for group actions.'
            )

        return data


# 🔹 Customer Search Serializer
class CustomerSearchSerializer(serializers.Serializer):
    search = serializers.CharField(required=False, allow_blank=True)
    customer_type = serializers.ChoiceField(
        choices=[('', 'All')] + Customer.CUSTOMER_TYPES,
        required=False,
        allow_blank=True
    )
    store = serializers.IntegerField(required=False)
    is_vat_registered = serializers.BooleanField(required=False)
    is_active = serializers.BooleanField(required=False)
    efris_status = serializers.ChoiceField(
        choices=[('', 'All')] + Customer.EFRIS_STATUS_CHOICES,
        required=False,
        allow_blank=True
    )
    district = serializers.CharField(required=False, allow_blank=True)