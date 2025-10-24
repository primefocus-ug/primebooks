from rest_framework import serializers
from .models import Sale, SaleItem, Receipt, Payment,Cart , CartItem
from inventory.serializers import ProductSerializer
from stores.serializers import StoreSerializer
from accounts.serializers import UserSerializer
from customers.serializers import CustomerSerializer

class SaleItemSerializer(serializers.ModelSerializer):
    product_details = ProductSerializer(source='product', read_only=True)

    class Meta:
        model = SaleItem
        fields = '__all__'
        read_only_fields = ('total_price', 'tax_amount', 'discount_amount')

    def validate(self, data):
        product = data['product']
        quantity = data['quantity']
        request = self.context.get('request')
        sale = self.context.get('sale')

        store = sale.store if sale else None
        if not store:
            raise serializers.ValidationError("Store is required to validate stock.")

        # Use the correct related_name 'store_inventory' instead of 'stock_levels'
        stock = product.store_inventory.filter(store=store).first()
        if not stock or stock.quantity < quantity:
            raise serializers.ValidationError(
                f"Insufficient stock for {product.name}. Available: {stock.quantity if stock else 0}"
            )
        return data

class SaleSerializer(serializers.ModelSerializer):
    items = SaleItemSerializer(many=True)
    store_details = StoreSerializer(source='store', read_only=True)
    created_by_details = UserSerializer(source='created_by', read_only=True)
    customer_details = CustomerSerializer(source='customer', read_only=True)

    class Meta:
        model = Sale
        fields = '__all__'
        read_only_fields = (
            'transaction_id', 'created_at', 'updated_at', 'subtotal', 
            'tax_amount', 'total_amount', 'is_fiscalized', 'fiscalization_time',
            'efris_invoice_number', 'verification_code', 'qr_code'
        )

    def create(self, validated_data):
        request = self.context.get('request')
        user = request.user if request else None
        items_data = validated_data.pop('items')

        store = validated_data['store']
        if store.company != user.company:
            raise serializers.ValidationError("You can only create sales for your own company's stores.")

        sale = Sale.objects.create(
            created_by=user,
            **validated_data
        )

        subtotal = 0
        tax_amount = 0
        for item_data in items_data:
            item = SaleItem.objects.create(sale=sale, **item_data)
            subtotal += item.total_price - item.discount_amount
            tax_amount += item.tax_amount

        sale.subtotal = subtotal
        sale.tax_amount = tax_amount
        sale.total_amount = subtotal + tax_amount
        sale.save()
        return sale


class ReceiptSerializer(serializers.ModelSerializer):
    sale_details = SaleSerializer(source='sale', read_only=True)
    printed_by_details = UserSerializer(source='printed_by', read_only=True)

    class Meta:
        model = Receipt
        fields = '__all__'
        read_only_fields = ('printed_at', 'receipt_number', 'print_count')

    def validate(self, data):
        user = self.context['request'].user
        sale = data['sale']
        if sale.store.company != user.company:
            raise serializers.ValidationError("You cannot create a receipt for another company's sale.")
        return data


class PaymentSerializer(serializers.ModelSerializer):
    sale_details = SaleSerializer(source='sale', read_only=True)

    class Meta:
        model = Payment
        fields = '__all__'
        read_only_fields = ('created_at', 'is_confirmed', 'confirmed_at')

    def validate(self, data):
        user = self.context['request'].user
        sale = data['sale']
        if sale.store.company != user.company:
            raise serializers.ValidationError("You cannot create a payment for another company's sale.")
        return data

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
    
    class Meta:
        model = Cart
        fields = [
            'id', 'session_key', 'user', 'customer', 'customer_name',
            'store', 'store_name', 'status', 'created_at', 'updated_at',
            'notes', 'subtotal', 'tax_amount', 'discount_amount', 
            'total_amount', 'items', 'item_count'
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


class CartConfirmSerializer(serializers.Serializer):
    """Serializer for confirming a cart (converting to sale)"""
    payment_method = serializers.ChoiceField(choices=Sale.PAYMENT_METHODS)
    
    def validate(self, data):
        cart = self.instance
        if cart.status != 'OPEN':
            raise serializers.ValidationError("Only open carts can be confirmed.")
        if not cart.items.exists():
            raise serializers.ValidationError("Cannot confirm empty cart.")
        return data


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
    transaction_type = serializers.CharField()
    document_type = serializers.CharField()
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
    total_sales = serializers.DecimalField(max_digits=12, decimal_places=2)
    total_tax = serializers.DecimalField(max_digits=12, decimal_places=2)
    total_items = serializers.IntegerField()
    payment_methods = serializers.DictField(child=serializers.DecimalField(max_digits=12, decimal_places=2))


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
