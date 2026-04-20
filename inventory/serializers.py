from rest_framework import serializers
from rest_framework import serializers
from django.db import transaction
from .models import Service,StockTransfer
from .models import Category, Supplier, Product, Stock, StockMovement, ImportLog, ImportResult, ImportSession
from company.serializers import CompanySerializer
from stores.serializers import StoreSerializer
from company.models import EFRISCommodityCategory

class EFRISCommodityCategorySerializer(serializers.ModelSerializer):
    """Serializer for EFRIS Commodity Categories"""
    class Meta:
        model = EFRISCommodityCategory
        fields = [
            'id', 'commodity_category_code', 'commodity_category_name',
            'is_exempt', 'is_leaf_node', 'is_zero_rate', 'last_synced'
        ]
        read_only_fields = ['last_synced']


class CategoryBasicSerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ['id', 'name', 'code']



class StockTransferListSerializer(serializers.ModelSerializer):
    """
    Lightweight serializer used for the list endpoint.
    Flat field names match what renderTransferItem() in the panel expects.
    """
    product_name    = serializers.CharField(source='product.name',        read_only=True)
    product_sku     = serializers.CharField(source='product.sku',         read_only=True)
    unit            = serializers.CharField(source='product.unit_of_measure', read_only=True)
    from_store_name = serializers.CharField(source='from_store.name',     read_only=True)
    to_store_name   = serializers.CharField(source='to_store.name',       read_only=True)
    requested_by_name = serializers.SerializerMethodField()
    approved_by_name  = serializers.SerializerMethodField()
    completed_by_name = serializers.SerializerMethodField()
    can_be_approved  = serializers.BooleanField(read_only=True)
    can_be_completed = serializers.BooleanField(read_only=True)
    can_be_cancelled = serializers.BooleanField(read_only=True)

    class Meta:
        model  = StockTransfer
        fields = [
            'id',
            'transfer_number',
            'status',
            # product
            'product', 'product_name', 'product_sku', 'unit',
            # stores
            'from_store', 'from_store_name',
            'to_store',   'to_store_name',
            # transfer details
            'quantity', 'reference', 'notes',
            # people
            'requested_by_name',
            'approved_by_name',
            'completed_by_name',
            # timestamps
            'created_at', 'approved_at', 'completed_at', 'cancelled_at',
            # computed
            'can_be_approved', 'can_be_completed', 'can_be_cancelled',
        ]

    def get_requested_by_name(self, obj):
        u = obj.requested_by
        return u.get_full_name() or u.username if u else None

    def get_approved_by_name(self, obj):
        u = obj.approved_by
        return u.get_full_name() or u.username if u else None

    def get_completed_by_name(self, obj):
        u = obj.completed_by
        return u.get_full_name() or u.username if u else None


class StockTransferCreateSerializer(serializers.ModelSerializer):
    """
    Used for POST /api/v1/transfers/
    The panel's saveTransfer() currently POSTs as a form to the Django view,
    but if you ever switch to a JSON API this serializer is ready.
    """
    class Meta:
        model  = StockTransfer
        fields = ['product', 'from_store', 'to_store', 'quantity', 'reference', 'notes']

    def validate(self, attrs):
        if attrs['from_store'] == attrs['to_store']:
            raise serializers.ValidationError(
                "Source and destination stores must be different."
            )
        # Check source stock exists and has enough quantity
        try:
            stock = Stock.objects.get(
                product=attrs['product'],
                store=attrs['from_store'],
            )
            if stock.quantity < attrs['quantity']:
                raise serializers.ValidationError(
                    f"Insufficient stock in {attrs['from_store'].name}. "
                    f"Available: {stock.quantity}, Requested: {attrs['quantity']}."
                )
        except Stock.DoesNotExist:
            raise serializers.ValidationError(
                f"No stock record found for this product in {attrs['from_store'].name}."
            )
        return attrs

    def create(self, validated_data):
        request = self.context['request']
        with transaction.atomic():
            transfer = StockTransfer.objects.create(
                **validated_data,
                requested_by=request.user,
                status='pending',
            )
        return transfer


class ServiceSerializer(serializers.ModelSerializer):
    # --- Read-only computed / derived fields ---
    efris_commodity_category_id = serializers.ReadOnlyField()
    efris_commodity_category_name = serializers.ReadOnlyField()
    efris_tax_category_id = serializers.ReadOnlyField()
    efris_tax_rate = serializers.ReadOnlyField()
    efris_excise_duty_rate = serializers.ReadOnlyField()
    efris_unit_of_measure_code = serializers.ReadOnlyField()
    final_price = serializers.ReadOnlyField()
    efris_status_display = serializers.ReadOnlyField()
    efris_configuration_complete = serializers.ReadOnlyField()
    effective_tax_rate = serializers.ReadOnlyField()

    # Optional: expose category as ID only (clean for APIs)
    category_id = serializers.PrimaryKeyRelatedField(
        source='category',
        queryset=Service._meta.get_field('category').remote_field.model.objects.filter(
            category_type='service'
        ),
        required=False,
        allow_null=True
    )

    class Meta:
        model = Service

        fields = [
            # Core
            'id',
            'name',
            'code',
            'description',
            'category_id',
            'unit_price',
            'unit_of_measure',
            'is_active',
            'image',

            # Tax
            'tax_rate',
            'excise_duty_rate',
            'effective_tax_rate',

            # EFRIS flags
            'efris_is_uploaded',
            'efris_upload_date',
            'efris_service_id',
            'efris_auto_sync_enabled',

            # EFRIS computed fields
            'efris_commodity_category_id',
            'efris_commodity_category_name',
            'efris_tax_category_id',
            'efris_tax_rate',
            'efris_excise_duty_rate',
            'efris_unit_of_measure_code',
            'efris_status_display',
            'efris_configuration_complete',

            # Pricing
            'final_price',

            # Metadata
            'created_at',
            'updated_at',
            'created_by',
        ]

        read_only_fields = [
            'id',
            'efris_is_uploaded',
            'efris_upload_date',
            'efris_service_id',
            'created_at',
            'updated_at',
            'created_by',
        ]

    # -------------------------------
    # Validation
    # -------------------------------
    def validate_excise_duty_rate(self, value):
        tax_rate = self.initial_data.get('tax_rate')
        if tax_rate != 'E' and value and value > 0:
            raise serializers.ValidationError(
                "Excise duty rate is only allowed when tax rate is 'E'."
            )
        return value

    def validate(self, attrs):
        """
        Cross-field validation
        """
        tax_rate = attrs.get('tax_rate', getattr(self.instance, 'tax_rate', None))
        excise = attrs.get(
            'excise_duty_rate',
            getattr(self.instance, 'excise_duty_rate', 0)
        )

        if tax_rate == 'E' and excise <= 0:
            raise serializers.ValidationError({
                'excise_duty_rate': "Excise duty rate must be greater than 0 when tax rate is 'E'."
            })

        return attrs

    # -------------------------------
    # Create / Update hooks
    # -------------------------------
    def create(self, validated_data):
        request = self.context.get('request')

        if request and request.user.is_authenticated:
            validated_data['created_by'] = request.user

        return super().create(validated_data)

    def update(self, instance, validated_data):
        return super().update(instance, validated_data)

class SupplierBasicSerializer(serializers.ModelSerializer):
    class Meta:
        model = Supplier
        fields = ['id', 'name', 'tin']


class ProductBasicSerializer(serializers.ModelSerializer):
    class Meta:
        model = Product
        fields = ['id', 'name', 'sku']


class CategorySerializer(serializers.ModelSerializer):
    # Nested read-only EFRIS details
    efris_commodity_category_details = EFRISCommodityCategorySerializer(
        source='efris_commodity_category', read_only=True
    )
    efris_commodity_category_id = serializers.ReadOnlyField(source='efris_commodity_category.id')
    efris_commodity_category_name = serializers.ReadOnlyField(source='efris_commodity_category.name')

    class Meta:
        model = Category
        # Exclude the raw ForeignKey field to avoid JSON serialization errors
        fields = [
            'id',
            'name',
            'code',
            'description',
            'efris_commodity_category_details',  # Only include nested JSON
            'efris_commodity_category_id',       # Read-only computed
            'efris_commodity_category_name',     # Read-only computed
            'efris_auto_sync',
            'efris_is_uploaded',
            'efris_upload_date',
            'is_active',
            'created_at',
            'updated_at',
        ]
        read_only_fields = (
            'created_at',
            'updated_at',
            'efris_upload_date',
            'efris_commodity_category_id',
            'efris_commodity_category_name',
        )


class CategoryDetailSerializer(serializers.ModelSerializer):
    product_count = serializers.SerializerMethodField()
    efris_status_display = serializers.ReadOnlyField()
    efris_commodity_category_details = EFRISCommodityCategorySerializer(
        source='efris_commodity_category',
        read_only=True
    )
    efris_commodity_category_id = serializers.ReadOnlyField()
    efris_commodity_category_name = serializers.ReadOnlyField()

    class Meta:
        model = Category
        fields = [
            'id', 'name', 'code', 'description',
            'efris_commodity_category',
            'efris_commodity_category_details',
            'category_type',
            'efris_commodity_category_id',
            'efris_commodity_category_name',
            'efris_auto_sync', 'efris_is_uploaded', 'efris_upload_date',
            'is_active', 'created_at', 'updated_at',
            'product_count', 'efris_status_display'
        ]

    def get_product_count(self, obj):
        return obj.products.filter(is_active=True).count()


class SupplierSerializer(serializers.ModelSerializer):
    tax_details = serializers.ReadOnlyField()

    class Meta:
        model = Supplier
        fields = [
            'id', 'name', 'tin', 'contact_person', 'phone', 'email',
            'address', 'country', 'is_active', 'created_at', 'updated_at',
            'tax_details'
        ]
        read_only_fields = ('created_at', 'updated_at')

class ProductSerializer(serializers.ModelSerializer):
    # Related objects
    category_details = CategoryBasicSerializer(source='category', read_only=True)
    supplier_details = SupplierBasicSerializer(source='supplier', read_only=True)

    # Computed business properties
    final_price = serializers.ReadOnlyField()
    tax_details = serializers.ReadOnlyField()
    total_stock = serializers.ReadOnlyField()
    stock_percentage = serializers.ReadOnlyField()

    # Computed EFRIS properties (read-only)
    efris_commodity_category_id = serializers.ReadOnlyField()
    efris_commodity_category_name = serializers.ReadOnlyField()
    efris_goods_code = serializers.ReadOnlyField()
    efris_goods_name = serializers.ReadOnlyField()
    efris_goods_description = serializers.ReadOnlyField()
    efris_tax_category_id = serializers.ReadOnlyField()
    efris_tax_rate = serializers.ReadOnlyField()
    efris_excise_duty_rate = serializers.ReadOnlyField()
    efris_unit_of_measure_code = serializers.ReadOnlyField()
    efris_status_display = serializers.ReadOnlyField()
    efris_configuration_complete = serializers.ReadOnlyField()

    class Meta:
        model = Product
        fields = [
            # Core product fields
            'id', 'name', 'sku', 'barcode', 'description',
            'category', 'supplier', 'category_details', 'supplier_details',
            'selling_price', 'cost_price', 'discount_percentage',
            'tax_rate', 'excise_duty_rate', 'unit_of_measure',
            'min_stock_level', 'is_active',
            'image', 'created_at', 'updated_at',

            # Keep these EFRIS fields:
            'efris_excise_duty_code', 'efris_is_uploaded', 'efris_upload_date',
            'efris_goods_id', 'efris_auto_sync_enabled',

            # Computed EFRIS fields (read-only properties)
            'efris_commodity_category_id', 'efris_commodity_category_name',
            'efris_goods_code', 'efris_goods_name', 'efris_goods_description',
            'efris_tax_category_id', 'efris_tax_rate', 'efris_excise_duty_rate',
            'efris_unit_of_measure_code', 'efris_status_display', 'efris_configuration_complete',

            # Computed business fields
            'final_price', 'tax_details', 'total_stock', 'stock_percentage',
        ]
        read_only_fields = (
            'created_at', 'updated_at', 'efris_upload_date', 'efris_goods_id',
            'imported_at', 'efris_commodity_category_id', 'efris_commodity_category_name'
        )

    def validate_sku(self, value):
        if self.instance:
            if Product.objects.exclude(pk=self.instance.pk).filter(sku=value).exists():
                raise serializers.ValidationError("Product with this SKU already exists.")
        else:
            if Product.objects.filter(sku=value).exists():
                raise serializers.ValidationError("Product with this SKU already exists.")
        return value

    def validate_barcode(self, value):
        if value:
            if self.instance:
                if Product.objects.exclude(pk=self.instance.pk).filter(barcode=value).exists():
                    raise serializers.ValidationError("Product with this barcode already exists.")
            else:
                if Product.objects.filter(barcode=value).exists():
                    raise serializers.ValidationError("Product with this barcode already exists.")
        return value

    def validate(self, data):
        """Cross-field validation"""
        selling_price = data.get('selling_price')
        cost_price = data.get('cost_price')

        # Use instance values if not provided in update
        if self.instance:
            selling_price = selling_price or self.instance.selling_price
            cost_price = cost_price or self.instance.cost_price

        if selling_price and cost_price and selling_price < cost_price:
            raise serializers.ValidationError(
                "Selling price cannot be less than cost price."
            )

        return data



class ProductListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for product lists"""
    category_name = serializers.CharField(source='category.name', read_only=True)
    supplier_name = serializers.CharField(source='supplier.name', read_only=True)
    final_price = serializers.ReadOnlyField()
    total_stock = serializers.ReadOnlyField()
    efris_status_display = serializers.ReadOnlyField()

    class Meta:
        model = Product
        fields = [
            'id', 'name', 'sku', 'category_name', 'supplier_name',
            'selling_price', 'final_price', 'total_stock', 'is_active',
            'efris_auto_sync_enabled', 'efris_status_display'
        ]

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return ProductDetailSerializer
        elif self.action == 'list':
            return ProductListSerializer
        elif self.action == 'efris_data':
            return EFRISProductSerializer
        return ProductSerializer  # ← PATCH hits this, good


class ProductDetailSerializer(ProductSerializer):
    """Extended serializer with additional computed fields for detail views"""
    store_stock_percentages = serializers.ReadOnlyField()
    current_price = serializers.ReadOnlyField()
    current_stock = serializers.ReadOnlyField()

    # EFRIS data for API consumption
    efris_data = serializers.SerializerMethodField()

    class Meta(ProductSerializer.Meta):
        fields = ProductSerializer.Meta.fields + [
            'store_stock_percentages', 'current_price', 'current_stock', 'efris_data'
        ]

    def get_efris_data(self, obj):
        """Get formatted EFRIS data"""
        if obj.efris_auto_sync_enabled:
            return obj.get_efris_data()
        return None


class StockSerializer(serializers.ModelSerializer):
    product_details = ProductBasicSerializer(source='product', read_only=True)
    store_details = StoreSerializer(source='store', read_only=True)
    status = serializers.ReadOnlyField()
    stock_percentage = serializers.ReadOnlyField()

    class Meta:
        model = Stock
        fields = [
            'id', 'product', 'store', 'quantity', 'low_stock_threshold',
            'last_updated', 'last_physical_count', 'last_physical_count_quantity',
            'last_import_update', 'product_details', 'store_details',
            'status', 'stock_percentage'
        ]
        read_only_fields = ('last_updated', 'last_import_update')

    def validate(self, data):
        # Ensure unique product-store combination
        if self.instance:
            existing = Stock.objects.exclude(pk=self.instance.pk).filter(
                product=data.get('product', self.instance.product),
                store=data.get('store', self.instance.store)
            )
        else:
            existing = Stock.objects.filter(
                product=data['product'],
                store=data['store']
            )

        if existing.exists():
            raise serializers.ValidationError(
                "Stock record for this product and store already exists."
            )
        return data


class StockMovementSerializer(serializers.ModelSerializer):
    product_details = ProductBasicSerializer(source='product', read_only=True)
    store_details = StoreSerializer(source='store', read_only=True)
    created_by_details = serializers.SerializerMethodField()

    class Meta:
        model = StockMovement
        fields = [
            'id', 'product', 'store', 'movement_type', 'quantity',
            'reference', 'notes', 'unit_price', 'total_value',
            'created_by', 'created_at',
            'product_details', 'store_details', 'created_by_details'
        ]
        read_only_fields = ('created_at', 'total_value', 'created_by')

    def get_created_by_details(self, obj):
        if obj.created_by:
            return {
                'id': obj.created_by.id,
                'name': obj.created_by.get_full_name() or obj.created_by.username,
                'email': obj.created_by.email
            }
        return None

    def create(self, validated_data):
        validated_data['created_by'] = self.context['request'].user
        return super().create(validated_data)

    def validate(self, data):
        # Check stock availability for outbound movements
        if self.instance is None and data.get('movement_type') in ['SALE', 'TRANSFER_OUT']:
            try:
                stock = Stock.objects.get(
                    product=data['product'],
                    store=data['store']
                )
                if stock.quantity < data['quantity']:
                    raise serializers.ValidationError(
                        f"Insufficient stock. Only {stock.quantity} {data['product'].unit_of_measure} available."
                    )
            except Stock.DoesNotExist:
                raise serializers.ValidationError(
                    "No stock record exists for this product in the selected store."
                )

        return data


class ImportSessionSerializer(serializers.ModelSerializer):
    duration = serializers.ReadOnlyField()
    success_rate = serializers.ReadOnlyField()
    user_name = serializers.CharField(source='user.get_full_name', read_only=True)

    class Meta:
        model = ImportSession
        fields = [
            'id', 'user', 'user_name', 'filename', 'file_size', 'status',
            'import_mode', 'conflict_resolution', 'has_header', 'column_mapping',
            'total_rows', 'processed_rows', 'created_count', 'updated_count',
            'skipped_count', 'error_count', 'created_at', 'started_at',
            'completed_at', 'error_message', 'duration', 'success_rate'
        ]
        read_only_fields = (
            'user', 'created_at', 'started_at', 'completed_at',
            'processed_rows', 'created_count', 'updated_count',
            'skipped_count', 'error_count', 'error_message'
        )


class ImportLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = ImportLog
        fields = [
            'id', 'session', 'level', 'message', 'row_number',
            'details', 'timestamp'
        ]
        read_only_fields = ('timestamp',)


class ImportResultSerializer(serializers.ModelSerializer):
    class Meta:
        model = ImportResult
        fields = [
            'id', 'session', 'result_type', 'row_number',
            'product_name', 'sku', 'store_name', 'quantity',
            'old_quantity', 'error_message', 'error_details',
            'raw_data', 'created_at'
        ]
        read_only_fields = ('created_at',)


# Report serializers
class InventoryReportSerializer(serializers.Serializer):
    product_id = serializers.IntegerField()
    product_name = serializers.CharField()
    sku = serializers.CharField()
    category = serializers.CharField(allow_null=True)
    store = serializers.CharField()
    current_stock = serializers.DecimalField(max_digits=12, decimal_places=3)
    reorder_level = serializers.DecimalField(max_digits=12, decimal_places=3)
    unit_of_measure = serializers.CharField()
    cost_price = serializers.DecimalField(max_digits=12, decimal_places=2)
    selling_price = serializers.DecimalField(max_digits=12, decimal_places=2)
    final_price = serializers.DecimalField(max_digits=12, decimal_places=2)
    total_cost = serializers.DecimalField(max_digits=15, decimal_places=2)
    total_value = serializers.DecimalField(max_digits=15, decimal_places=2)
    status = serializers.CharField()
    last_updated = serializers.DateTimeField()
    efris_sync_enabled = serializers.BooleanField()
    efris_uploaded = serializers.BooleanField()


class StockMovementReportSerializer(serializers.Serializer):
    date = serializers.DateField()
    product_name = serializers.CharField()
    product_sku = serializers.CharField()
    store_name = serializers.CharField()
    movement_type = serializers.CharField()
    quantity = serializers.DecimalField(max_digits=12, decimal_places=3)
    unit_price = serializers.DecimalField(max_digits=12, decimal_places=2, allow_null=True)
    total_value = serializers.DecimalField(max_digits=12, decimal_places=2, allow_null=True)
    reference = serializers.CharField(allow_null=True)
    notes = serializers.CharField(allow_null=True)
    created_by = serializers.CharField()


class LowStockReportSerializer(serializers.Serializer):
    product_id = serializers.IntegerField()
    product_name = serializers.CharField()
    sku = serializers.CharField()
    category = serializers.CharField(allow_null=True)
    store = serializers.CharField()
    current_stock = serializers.DecimalField(max_digits=12, decimal_places=3)
    reorder_level = serializers.DecimalField(max_digits=12, decimal_places=3)
    reorder_gap = serializers.DecimalField(max_digits=12, decimal_places=3)
    stock_percentage = serializers.FloatField()
    total_cost = serializers.DecimalField(max_digits=15, decimal_places=2)
    recommended_order_qty = serializers.DecimalField(max_digits=12, decimal_places=3)
    priority = serializers.CharField()
    status = serializers.CharField()


class ValuationReportSerializer(serializers.Serializer):
    product_id = serializers.IntegerField()
    product_name = serializers.CharField()
    sku = serializers.CharField()
    category = serializers.CharField(allow_null=True)
    store = serializers.CharField()
    quantity = serializers.DecimalField(max_digits=12, decimal_places=3)
    cost_price = serializers.DecimalField(max_digits=12, decimal_places=2)
    selling_price = serializers.DecimalField(max_digits=12, decimal_places=2)
    final_price = serializers.DecimalField(max_digits=12, decimal_places=2)
    total_cost = serializers.DecimalField(max_digits=15, decimal_places=2)
    total_selling = serializers.DecimalField(max_digits=15, decimal_places=2)
    total_final = serializers.DecimalField(max_digits=15, decimal_places=2)
    potential_profit = serializers.DecimalField(max_digits=15, decimal_places=2)
    profit_margin = serializers.DecimalField(max_digits=5, decimal_places=2)
    unit_of_measure = serializers.CharField()


# EFRIS-specific serializers
class EFRISProductSerializer(serializers.ModelSerializer):
    """Serializer specifically for EFRIS data exchange"""
    efris_goods_code = serializers.ReadOnlyField()
    efris_goods_name = serializers.ReadOnlyField()
    efris_goods_description = serializers.ReadOnlyField()
    efris_tax_category_id = serializers.ReadOnlyField()
    efris_tax_rate = serializers.ReadOnlyField()
    efris_unit_of_measure_code = serializers.ReadOnlyField()
    efris_data = serializers.SerializerMethodField()
    efris_errors = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            'id', 'name', 'sku', 'selling_price',
            'efris_goods_code', 'efris_goods_name', 'efris_goods_description',
            'efris_tax_category_id', 'efris_tax_rate', 'efris_unit_of_measure_code',
            'efris_commodity_category_id', 'efris_commodity_category_name',
            'efris_excise_duty_code', 'efris_auto_sync_enabled',
            'efris_is_uploaded', 'efris_upload_date', 'efris_goods_id',
            'efris_data', 'efris_errors'
        ]

    def get_efris_data(self, obj):
        """Get formatted EFRIS data"""
        return obj.get_efris_data()

    def get_efris_errors(self, obj):
        """Get EFRIS configuration errors"""
        return obj.get_efris_errors()


class ProductBulkActionSerializer(serializers.Serializer):
    """Serializer for bulk product operations"""
    product_ids = serializers.ListField(
        child=serializers.IntegerField(),
        min_length=1
    )
    action = serializers.ChoiceField(choices=[
        'activate', 'deactivate', 'delete',
        'enable_efris_sync', 'disable_efris_sync',
        'mark_for_efris_upload', 'update_category',
        'update_supplier', 'update_tax_rate'
    ])

    # Optional fields for specific actions
    category_id = serializers.IntegerField(required=False)
    supplier_id = serializers.IntegerField(required=False)
    tax_rate = serializers.ChoiceField(choices=Product.TAX_RATE_CHOICES, required=False)

    def validate(self, data):
        action = data.get('action')

        if action == 'update_category' and not data.get('category_id'):
            raise serializers.ValidationError("category_id is required for update_category action")

        if action == 'update_supplier' and not data.get('supplier_id'):
            raise serializers.ValidationError("supplier_id is required for update_supplier action")

        if action == 'update_tax_rate' and not data.get('tax_rate'):
            raise serializers.ValidationError("tax_rate is required for update_tax_rate action")

        return data