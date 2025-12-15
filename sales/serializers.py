from rest_framework import serializers
from .models import Sale, SaleItem, Receipt, Payment, Cart, CartItem
from inventory.serializers import ProductSerializer
from stores.serializers import StoreSerializer
from accounts.serializers import UserSerializer
from customers.serializers import CustomerSerializer
from decimal import Decimal
from django.utils import timezone


class SaleItemSerializer(serializers.ModelSerializer):
    product_details = ProductSerializer(source='product', read_only=True)

    class Meta:
        model = SaleItem
        fields = '__all__'
        read_only_fields = ('total_price', 'tax_amount', 'discount_amount', 'net_amount', 'line_total')

    def validate(self, data):
        """Validate sale item with document type context"""
        product = data.get('product')
        quantity = data.get('quantity')
        request = self.context.get('request')
        sale = self.context.get('sale')

        # Get document type from sale
        document_type = getattr(sale, 'document_type', 'RECEIPT') if sale else 'RECEIPT'

        # Only validate stock for receipts and invoices (not proforma/estimate)
        if product and quantity and document_type in ['RECEIPT', 'INVOICE']:
            store = sale.store if sale else None
            if not store:
                raise serializers.ValidationError("Store is required to validate stock.")

            stock = product.store_inventory.filter(store=store).first()
            if not stock or stock.quantity < quantity:
                raise serializers.ValidationError(
                    f"Insufficient stock for {product.name}. Available: {stock.quantity if stock else 0}"
                )
        return data


class SaleSerializer(serializers.ModelSerializer):
    items = SaleItemSerializer(many=True, required=False)
    store_details = StoreSerializer(source='store', read_only=True)
    created_by_details = UserSerializer(source='created_by', read_only=True)
    customer_details = CustomerSerializer(source='customer', read_only=True)

    # ==================== NEW: Payment Status and Document Type Properties ====================
    payment_status_display = serializers.CharField(source='get_payment_status_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    document_type_display = serializers.CharField(source='get_document_type_display', read_only=True)

    # ==================== NEW: Invoice-specific fields ====================
    invoice_detail = serializers.SerializerMethodField(read_only=True)
    receipt_detail = serializers.SerializerMethodField(read_only=True)
    amount_paid = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    amount_outstanding = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    days_overdue = serializers.IntegerField(read_only=True)

    class Meta:
        model = Sale
        fields = '__all__'
        read_only_fields = (
            'transaction_id', 'created_at', 'updated_at', 'subtotal',
            'tax_amount', 'total_amount', 'is_fiscalized', 'fiscalization_time',
            'efris_invoice_number', 'verification_code', 'qr_code',
            'document_number', 'payment_status', 'status', 'amount_paid',
            'amount_outstanding', 'days_overdue'
        )

    def get_invoice_detail(self, obj):
        """Get invoice detail data if exists"""
        if hasattr(obj, 'invoice_detail') and obj.invoice_detail:
            from invoices.serializers import InvoiceSerializer
            return InvoiceSerializer(obj.invoice_detail).data
        return None

    def get_receipt_detail(self, obj):
        """Get receipt detail data if exists"""
        if hasattr(obj, 'receipt_detail') and obj.receipt_detail:
            return ReceiptSerializer(obj.receipt_detail).data
        return None

    def validate(self, data):
        """Enhanced validation with document type logic"""
        document_type = data.get('document_type', 'RECEIPT')
        payment_method = data.get('payment_method')
        due_date = data.get('due_date')

        # Validate due date for invoices
        if document_type == 'INVOICE' and not due_date:
            raise serializers.ValidationError({
                'due_date': 'Due date is required for invoices'
            })

        # Validate payment method based on document type
        if document_type == 'RECEIPT' and payment_method == 'CREDIT':
            raise serializers.ValidationError({
                'payment_method': 'Receipts must have immediate payment (not credit)'
            })

        # Validate due date is not in the past
        if due_date and due_date < timezone.now().date():
            raise serializers.ValidationError({
                'due_date': 'Due date cannot be in the past'
            })

        return data

    def create(self, validated_data):
        request = self.context.get('request')
        user = request.user if request else None
        items_data = validated_data.pop('items', [])

        store = validated_data.get('store')
        if store and user and store.company != user.company:
            raise serializers.ValidationError("You can only create sales for your own company's stores.")

        # Set appropriate status based on document type
        document_type = validated_data.get('document_type', 'RECEIPT')
        payment_method = validated_data.get('payment_method', 'CASH')

        # Auto-set statuses based on document type
        if document_type == 'RECEIPT':
            validated_data['payment_status'] = 'PAID'
            validated_data['status'] = 'COMPLETED'
        elif document_type == 'INVOICE':
            if payment_method == 'CREDIT':
                validated_data['payment_status'] = 'PENDING'
                validated_data['status'] = 'PENDING_PAYMENT'
            else:
                validated_data['payment_status'] = 'PAID'
                validated_data['status'] = 'COMPLETED'
        elif document_type in ['PROFORMA', 'ESTIMATE']:
            validated_data['payment_status'] = 'NOT_APPLICABLE'
            validated_data['status'] = 'DRAFT'

        # Create sale
        sale = Sale.objects.create(
            created_by=user,
            **validated_data
        )

        # Create sale items
        subtotal = Decimal('0')
        tax_amount = Decimal('0')
        for item_data in items_data:
            item = SaleItem.objects.create(
                sale=sale,
                **item_data,
                _skip_sale_update=True  # Skip immediate update
            )
            subtotal += item.total_price
            tax_amount += item.tax_amount

        # Calculate totals
        discount_amount = validated_data.get('discount_amount', Decimal('0'))

        sale.subtotal = subtotal
        sale.tax_amount = tax_amount
        sale.discount_amount = discount_amount
        sale.total_amount = (subtotal - discount_amount).quantize(Decimal('0.01'))
        sale.save()

        # Create document-specific records
        if document_type == 'RECEIPT':
            Receipt.objects.create(
                sale=sale,
                printed_by=user,
                receipt_number=f"RCP-{sale.document_number}",
                receipt_data={
                    'items': [item.item_name for item in sale.items.all()],
                    'totals': {
                        'subtotal': str(sale.subtotal),
                        'tax': str(sale.tax_amount),
                        'discount': str(sale.discount_amount),
                        'total': str(sale.total_amount),
                    }
                }
            )
        elif document_type == 'INVOICE':
            from invoices.models import Invoice
            Invoice.objects.create(
                sale=sale,
                terms='',
                purchase_order='',
                due_date=sale.due_date
            )

        return sale

    def update(self, instance, validated_data):
        """Update sale with document type specific logic"""
        items_data = validated_data.pop('items', None)

        # Update basic fields
        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        # Update items if provided
        if items_data is not None:
            # Clear existing items
            instance.items.all().delete()

            # Create new items
            for item_data in items_data:
                SaleItem.objects.create(sale=instance, **item_data)

        # Update totals
        instance.update_totals()

        # Update status based on document type
        document_type = instance.document_type
        if document_type == 'RECEIPT':
            instance.payment_status = 'PAID'
            instance.status = 'COMPLETED'
        elif document_type == 'INVOICE' and instance.payment_method == 'CREDIT':
            instance.payment_status = 'PENDING'
            instance.status = 'PENDING_PAYMENT'

        instance.save()
        return instance


class ReceiptSerializer(serializers.ModelSerializer):
    sale_details = SaleSerializer(source='sale', read_only=True)
    printed_by_details = UserSerializer(source='printed_by', read_only=True)

    # ==================== NEW: Document Number Access ====================
    document_number = serializers.CharField(source='sale.document_number', read_only=True)

    class Meta:
        model = Receipt
        fields = '__all__'
        read_only_fields = ('printed_at', 'receipt_number', 'print_count', 'is_duplicate')

    def validate(self, data):
        user = self.context['request'].user
        sale = data['sale']
        if sale.store.company != user.company:
            raise serializers.ValidationError("You cannot create a receipt for another company's sale.")

        # Ensure sale is a receipt type
        if sale.document_type != 'RECEIPT':
            raise serializers.ValidationError("Receipts can only be created for receipt-type sales.")

        return data

    def create(self, validated_data):
        """Auto-generate receipt number"""
        receipt = super().create(validated_data)
        if not receipt.receipt_number:
            receipt.receipt_number = f"RCP-{receipt.sale.document_number}"
            receipt.save()
        return receipt


class PaymentSerializer(serializers.ModelSerializer):
    sale_details = SaleSerializer(source='sale', read_only=True)

    # ==================== NEW: Document Number Access ====================
    document_number = serializers.CharField(source='sale.document_number', read_only=True)
    payment_type_display = serializers.CharField(source='get_payment_type_display', read_only=True)

    class Meta:
        model = Payment
        fields = '__all__'
        read_only_fields = ('created_at', 'is_confirmed', 'confirmed_at', 'voided_at')

    def validate(self, data):
        user = self.context['request'].user
        sale = data['sale']

        if sale.store.company != user.company:
            raise serializers.ValidationError("You cannot create a payment for another company's sale.")

        # Validate payment amount for invoices
        if sale.document_type == 'INVOICE':
            amount = data.get('amount', Decimal('0'))
            outstanding = sale.amount_outstanding

            if amount > outstanding:
                raise serializers.ValidationError({
                    'amount': f'Payment amount ({amount}) exceeds outstanding amount ({outstanding})'
                })

        return data

    def create(self, validated_data):
        """Create payment and update sale status"""
        payment = super().create(validated_data)

        # Update sale payment status
        if payment.sale.document_type == 'INVOICE':
            payment.update_payment_status()

        return payment


class CartItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name', read_only=True)
    product_code = serializers.CharField(source='product.code', read_only=True)

    class Meta:
        model = CartItem
        fields = [
            'id', 'cart', 'product', 'product_name', 'product_code',
            'quantity', 'unit_price', 'total_price', 'tax_rate',
            'tax_amount', 'discount', 'discount_amount', 'description',
            'added_at'
        ]
        read_only_fields = ['id', 'total_price', 'tax_amount', 'discount_amount', 'added_at']

    def validate_product(self, value):
        """Ensure product belongs to user's company"""
        request = self.context.get('request')
        if request and hasattr(request.user, 'company'):
            if value.company != request.user.company:
                raise serializers.ValidationError("Product not found or not accessible.")
        return value

    def validate_quantity(self, value):
        """Ensure quantity doesn't exceed available stock"""
        if value <= 0:
            raise serializers.ValidationError("Quantity must be greater than 0.")
        return value

    def validate(self, data):
        """Additional validation for cart items"""
        product = data.get('product')
        quantity = data.get('quantity')

        if product and quantity:
            # Check stock availability
            if product.stock_level < quantity:
                raise serializers.ValidationError({
                    'quantity': f'Only {product.stock_level} units available in stock.'
                })

            # Set unit price from product if not provided
            if 'unit_price' not in data or not data['unit_price']:
                data['unit_price'] = product.selling_price

        return data


class CartSerializer(serializers.ModelSerializer):
    items = CartItemSerializer(many=True, read_only=True)
    store_name = serializers.CharField(source='store.name', read_only=True)
    customer_name = serializers.CharField(source='customer.name', read_only=True)
    item_count = serializers.SerializerMethodField()

    # ==================== NEW: Document Type Properties ====================
    document_type_display = serializers.CharField(source='get_document_type_display', read_only=True)

    class Meta:
        model = Cart
        fields = [
            'id', 'session_key', 'user', 'customer', 'customer_name',
            'store', 'store_name', 'status', 'created_at', 'updated_at',
            'notes', 'subtotal', 'tax_amount', 'discount_amount',
            'total_amount', 'items', 'item_count', 'document_type',
            'document_type_display', 'due_date', 'terms', 'purchase_order'
        ]
        read_only_fields = [
            'id', 'created_at', 'updated_at', 'subtotal', 'tax_amount',
            'discount_amount', 'total_amount', 'item_count'
        ]

    def get_item_count(self, obj):
        return obj.items.count()

    def validate_store(self, value):
        """Ensure store belongs to user's company"""
        request = self.context.get('request')
        if request and hasattr(request.user, 'company'):
            if value.company != request.user.company:
                raise serializers.ValidationError("Store not found or not accessible.")
        return value

    def validate_customer(self, value):
        """Ensure customer belongs to user's company"""
        if value:  # customer is optional
            request = self.context.get('request')
            if request and hasattr(request.user, 'company'):
                if value.company != request.user.company:
                    raise serializers.ValidationError("Customer not found or not accessible.")
        return value

    def validate_due_date(self, value):
        """Validate due date for invoice carts"""
        document_type = self.initial_data.get('document_type', 'RECEIPT')
        if document_type == 'INVOICE' and not value:
            raise serializers.ValidationError("Due date is required for invoice carts.")
        return value

    def create(self, validated_data):
        """Create cart with document type"""
        cart = super().create(validated_data)

        # Set initial totals
        cart.update_totals()

        return cart


class CartConfirmSerializer(serializers.Serializer):
    """Serializer for confirming a cart (converting to sale)"""
    payment_method = serializers.ChoiceField(choices=Sale.PAYMENT_METHODS)

    # ==================== NEW: Invoice-specific fields ====================
    terms = serializers.CharField(required=False, allow_blank=True)
    purchase_order = serializers.CharField(required=False, allow_blank=True)

    def validate(self, data):
        cart = self.instance

        if cart.status != 'OPEN':
            raise serializers.ValidationError("Only open carts can be confirmed.")

        if not cart.items.exists():
            raise serializers.ValidationError("Cannot confirm empty cart.")

        # Validate due date for invoice carts
        if cart.document_type == 'INVOICE' and not cart.due_date:
            raise serializers.ValidationError("Due date is required for invoice carts.")

        return data

    def save(self, **kwargs):
        """Confirm cart and create sale"""
        request = self.context.get('request')
        user = request.user if request else None

        # Get cart from instance
        cart = self.instance

        # Confirm cart and create sale
        sale = cart.confirm(
            payment_method=self.validated_data['payment_method'],
            created_by=user,
            terms=self.validated_data.get('terms', ''),
            purchase_order=self.validated_data.get('purchase_order', '')
        )

        return sale


# ==================== NEW: Document Type Serializers ====================
class DocumentTypeSelectionSerializer(serializers.Serializer):
    """Serializer for document type selection"""
    document_type = serializers.ChoiceField(choices=Sale.DOCUMENT_TYPE_CHOICES)
    customer_id = serializers.IntegerField(required=False, allow_null=True)
    store_id = serializers.IntegerField()

    def validate(self, data):
        """Validate document type selection"""
        document_type = data.get('document_type')

        if document_type not in ['RECEIPT', 'INVOICE', 'PROFORMA', 'ESTIMATE']:
            raise serializers.ValidationError({
                'document_type': 'Invalid document type'
            })

        return data


class ProformaConvertSerializer(serializers.Serializer):
    """Serializer for converting proforma/estimate to invoice"""
    due_date = serializers.DateField()
    terms = serializers.CharField(required=False, allow_blank=True)

    def validate_due_date(self, value):
        """Validate due date is in the future"""
        if value < timezone.now().date():
            raise serializers.ValidationError("Due date cannot be in the past")
        return value


# EFRIS Integration Serializers
class EFRISSaleRequestSerializer(serializers.Serializer):
    transaction_id = serializers.UUIDField()
    invoice_number = serializers.CharField()
    store_id = serializers.IntegerField()
    seller_tin = serializers.CharField()
    seller_name = serializers.CharField()
    seller_address = serializers.CharField()
    device_number = serializers.CharField()
    operator_name = serializers.CharField()
    customer_tin = serializers.CharField(required=False, allow_null=True)
    customer_name = serializers.CharField(required=False, allow_null=True)
    customer_address = serializers.CharField(required=False, allow_null=True)
    document_type = serializers.CharField()  # Changed from transaction_type
    payment_method = serializers.CharField()
    currency = serializers.CharField()
    subtotal = serializers.DecimalField(max_digits=12, decimal_places=2)
    tax_amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    discount_amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    total_amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    items = serializers.ListField(child=serializers.DictField())


class EFRISSaleResponseSerializer(serializers.Serializer):
    status = serializers.CharField()
    efris_invoice_number = serializers.CharField()
    verification_code = serializers.CharField()
    qr_code = serializers.CharField()
    fiscalization_time = serializers.DateTimeField()
    error_message = serializers.CharField(required=False, allow_null=True)
    error_code = serializers.CharField(required=False, allow_null=True)


# Reporting Serializers
class SalesReportSerializer(serializers.Serializer):
    start_date = serializers.DateField()
    end_date = serializers.DateField()
    store_id = serializers.IntegerField(required=False)
    document_type = serializers.ChoiceField(
        choices=[('', 'All')] + Sale.DOCUMENT_TYPE_CHOICES,
        required=False
    )
    payment_status = serializers.ChoiceField(
        choices=[('', 'All')] + Sale.PAYMENT_STATUS_CHOICES,
        required=False
    )
    total_sales = serializers.DecimalField(max_digits=12, decimal_places=2)
    total_tax = serializers.DecimalField(max_digits=12, decimal_places=2)
    total_items = serializers.IntegerField()
    payment_methods = serializers.DictField(child=serializers.DecimalField(max_digits=12, decimal_places=2))
    document_types = serializers.DictField(child=serializers.DecimalField(max_digits=12, decimal_places=2))


class ZReportSerializer(serializers.Serializer):
    store_id = serializers.IntegerField()
    report_date = serializers.DateField()
    start_time = serializers.DateTimeField()
    end_time = serializers.DateTimeField()
    total_sales = serializers.DecimalField(max_digits=12, decimal_places=2)
    total_tax = serializers.DecimalField(max_digits=12, decimal_places=2)
    total_discount = serializers.DecimalField(max_digits=12, decimal_places=2)
    total_refunds = serializers.DecimalField(max_digits=12, decimal_places=2)
    transaction_count = serializers.IntegerField()
    items_sold = serializers.IntegerField()
    # ==================== NEW: Document Type Breakdown ====================
    document_type_breakdown = serializers.DictField(child=serializers.IntegerField())
    payment_method_breakdown = serializers.DictField(child=serializers.DecimalField(max_digits=12, decimal_places=2))