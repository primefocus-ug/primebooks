from rest_framework import serializers
from .models import Customer, CustomerGroup, CustomerNote, EFRISCustomerSync
from accounts.serializers import UserSerializer


# 🔹 Customer Serializer
class CustomerSerializer(serializers.ModelSerializer):
    primary_identification = serializers.ReadOnlyField()
    is_efris_registered = serializers.ReadOnlyField()
    can_sync_to_efris = serializers.ReadOnlyField()
    tax_details = serializers.ReadOnlyField()

    class Meta:
        model = Customer
        fields = [
            'id', 'customer_id',
            'customer_type', 'name', 'store', 'email', 'phone',
            'tin', 'nin', 'brn',
            'physical_address', 'postal_address', 'district', 'country',
            'is_vat_registered', 'credit_limit', 'is_active',
            # eFRIS fields
            'efris_customer_type', 'efris_customer_id', 'efris_status',
            'efris_registered_at', 'efris_last_sync', 'efris_reference_no',
            'efris_sync_error',
            # Additional identification fields
            'passport_number', 'driving_license', 'voter_id', 'alien_id',
            # Computed properties
            'primary_identification', 'is_efris_registered', 'can_sync_to_efris',
            'tax_details',
            'created_at', 'updated_at'
        ]
        read_only_fields = (
            'customer_id', 'efris_customer_type', 'efris_customer_id',
            'efris_status', 'efris_registered_at', 'efris_last_sync',
            'efris_reference_no', 'efris_sync_error',
            'primary_identification', 'is_efris_registered', 'can_sync_to_efris',
            'tax_details', 'created_at', 'updated_at'
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

        return data

    def validate_phone(self):
        phone = self.validated_data.get('phone')
        if phone and not phone.startswith('+'):
            # Auto-add Uganda country code if not provided
            if phone.startswith('0'):
                phone = '+256' + phone[1:]
            else:
                phone = '+256' + phone
        return phone


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