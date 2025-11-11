from django.contrib.auth import get_user_model
from django.core.validators import FileExtensionValidator
from django import forms
from django.core.exceptions import ValidationError
from decimal import Decimal
from django.utils import timezone
from .models import Category, Supplier, Product, Stock, StockMovement,Service
from stores.models import Store
from company.models import EFRISCommodityCategory
from django.utils.translation import gettext_lazy as _

User = get_user_model()


class ServiceForm(forms.ModelForm):
    """
    Form for creating and updating services with EFRIS integration.
    Includes real-time validation and autocomplete for EFRIS categories.
    """

    # Override category field with custom widget
    category = forms.ModelChoiceField(
        queryset=Category.objects.filter(category_type='service', is_active=True),
        required=True,
        empty_label="-- Select Service Category --",
        widget=forms.Select(attrs={
            'class': 'form-select',
            'data-live-search': 'true',
            'id': 'id_category',
        }),
        label=_("Service Category"),
        help_text=_("Select a service category. Only leaf node EFRIS categories are allowed.")
    )

    # Add hidden field for EFRIS validation
    efris_commodity_code = forms.CharField(
        required=False,
        widget=forms.HiddenInput(attrs={'id': 'id_efris_commodity_code'}),
    )

    class Meta:
        model = Service
        fields = [
            'name', 'code', 'category', 'description',
            'unit_price',
            'tax_rate', 'excise_duty_rate',
            'unit_of_measure', 'image',
            'efris_auto_sync_enabled', 'is_active'
        ]

        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g., Software Development, Consulting',
                'required': True,
            }),
            'code': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g., SRV001, DEV-001',
                'required': True,
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Detailed description of the service...',
            }),
            'unit_price': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'min': '0',
                'placeholder': '0.00',
                'required': True,
            }),
            'tax_rate': forms.Select(attrs={
                'class': 'form-select',
            }),
            'excise_duty_rate': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'min': '0',
                'value': '0',
            }),
            'unit_of_measure': forms.Select(attrs={
                'class': 'form-select',
                'data-live-search': 'true',
            }),
            'image': forms.FileInput(attrs={
                'class': 'form-control',
                'accept': 'image/*',
            }),
            'efris_auto_sync_enabled': forms.CheckboxInput(attrs={
                'class': 'form-check-input',
            }),
            'is_active': forms.CheckboxInput(attrs={
                'class': 'form-check-input',
            }),
        }

        labels = {
            'name': _('Service Name'),
            'code': _('Service Code'),
            'category': _('Service Category'),
            'description': _('Description'),
            'unit_price': _('Unit Price (UGX)'),
            'tax_rate': _('Tax Rate'),
            'excise_duty_rate': _('Excise Duty Rate %'),
            'unit_of_measure': _('Unit of Measure'),
            'image': _('Service Image'),
            'efris_auto_sync_enabled': _('Enable EFRIS Auto-Sync'),
            'is_active': _('Active'),
        }

        help_texts = {
            'code': _('Unique identifier for this service'),
            'unit_price': _('Price per unit of service'),
            'excise_duty_rate': _('Only applicable if tax rate is E'),
            'unit_of_measure': _('Unit for measuring this service (e.g., Hours, Sessions)'),
            'efris_auto_sync_enabled': _('Automatically sync changes to EFRIS'),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Set initial value for EFRIS code if editing
        if self.instance.pk and self.instance.category:
            self.fields['efris_commodity_code'].initial = (
                self.instance.category.efris_commodity_category_code
            )

        # Add CSS classes to all fields
        for field_name, field in self.fields.items():
            if field_name not in ['efris_auto_sync_enabled', 'is_active']:
                if 'class' not in field.widget.attrs:
                    field.widget.attrs['class'] = 'form-control'

    def clean_code(self):
        """Validate service code is unique"""
        code = self.cleaned_data.get('code')
        if not code:
            raise ValidationError(_("Service code is required"))

        # Check uniqueness
        qs = Service.objects.filter(code=code)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)

        if qs.exists():
            raise ValidationError(
                _("Service with this code already exists. Please use a unique code.")
            )

        return code

    def clean_category(self):
        """Validate category is a service category with valid EFRIS settings"""
        category = self.cleaned_data.get('category')

        if not category:
            raise ValidationError(_("Service category is required"))

        # Validate it's a service category
        if category.category_type != 'service':
            raise ValidationError(
                _("Selected category is not a service category. "
                  "Please select a service category.")
            )

        # Validate EFRIS commodity category exists
        if not category.efris_commodity_category_code:
            raise ValidationError(
                _("Selected category does not have an EFRIS commodity category assigned. "
                  "Please update the category settings first.")
            )

        # Validate it's a leaf node
        if not category.efris_is_leaf_node:
            raise ValidationError(
                _("Selected category's EFRIS commodity category is not a leaf node. "
                  "Only leaf nodes (terminal categories) can be used for services.")
            )

        return category

    def clean_unit_price(self):
        """Validate unit price is positive"""
        unit_price = self.cleaned_data.get('unit_price')

        if unit_price is not None and unit_price < 0:
            raise ValidationError(_("Unit price cannot be negative"))

        return unit_price


    def clean_excise_duty_rate(self):
        """Validate excise duty rate"""
        excise_rate = self.cleaned_data.get('excise_duty_rate')
        tax_rate = self.cleaned_data.get('tax_rate')

        if excise_rate and excise_rate > 0:
            if tax_rate != 'E':
                raise ValidationError(
                    _("Excise duty rate can only be set when tax rate is 'E' (Excise Duty rate)")
                )

        return excise_rate

    def clean(self):
        """Additional cross-field validation"""
        cleaned_data = super().clean()

        # Ensure required fields are present
        required_fields = ['name', 'code', 'category', 'unit_price', 'tax_rate', 'unit_of_measure']
        for field in required_fields:
            if not cleaned_data.get(field):
                self.add_error(field, _("This field is required"))

        return cleaned_data


class ServiceQuickCreateForm(forms.ModelForm):
    """
    Simplified form for quick service creation via AJAX.
    Contains only essential fields.
    """

    class Meta:
        model = Service
        fields = ['name', 'code', 'category', 'unit_price', 'tax_rate', 'unit_of_measure']

        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Service Name',
                'required': True,
            }),
            'code': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Service Code',
                'required': True,
            }),
            'category': forms.Select(attrs={
                'class': 'form-select',
                'required': True,
            }),
            'unit_price': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': '0.00',
                'step': '0.01',
                'min': '0',
                'required': True,
            }),
            'tax_rate': forms.Select(attrs={
                'class': 'form-select',
            }),
            'unit_of_measure': forms.Select(attrs={
                'class': 'form-select',
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Only show service categories
        self.fields['category'].queryset = Category.objects.filter(
            category_type='service',
            is_active=True
        )

    def clean_code(self):
        """Validate service code is unique"""
        code = self.cleaned_data.get('code')
        if Service.objects.filter(code=code).exists():
            raise ValidationError(_("Service with this code already exists"))
        return code


class ServiceFilterForm(forms.Form):
    """
    Form for filtering services in list view.
    """

    search = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Search services...',
        })
    )

    category = forms.ModelChoiceField(
        queryset=Category.objects.filter(category_type='service', is_active=True),
        required=False,
        empty_label="All Categories",
        widget=forms.Select(attrs={
            'class': 'form-select',
        })
    )

    tax_rate = forms.ChoiceField(
        required=False,
        choices=[('', 'All Tax Rates')] + Service.TAX_RATE_CHOICES,
        widget=forms.Select(attrs={
            'class': 'form-select',
        })
    )

    efris_status = forms.ChoiceField(
        required=False,
        choices=[
            ('', 'All EFRIS Status'),
            ('uploaded', 'Uploaded to EFRIS'),
            ('pending', 'Pending Upload'),
            ('disabled', 'Sync Disabled'),
        ],
        widget=forms.Select(attrs={
            'class': 'form-select',
        })
    )

    is_active = forms.ChoiceField(
        required=False,
        choices=[
            ('', 'All Status'),
            ('true', 'Active'),
            ('false', 'Inactive'),
        ],
        widget=forms.Select(attrs={
            'class': 'form-select',
        })
    )


class ServiceBulkActionForm(forms.Form):
    """
    Form for bulk actions on services.
    """

    ACTION_CHOICES = [
        ('', '-- Select Action --'),
        ('activate', 'Activate Selected'),
        ('deactivate', 'Deactivate Selected'),
        ('enable_efris', 'Enable EFRIS Sync'),
        ('disable_efris', 'Disable EFRIS Sync'),
        ('mark_for_upload', 'Mark for EFRIS Upload'),
        ('delete', 'Delete Selected'),
    ]

    action = forms.ChoiceField(
        choices=ACTION_CHOICES,
        required=True,
        widget=forms.Select(attrs={
            'class': 'form-select',
        })
    )

    service_ids = forms.CharField(
        widget=forms.HiddenInput(),
        required=True,
    )

    def clean_service_ids(self):
        """Convert comma-separated IDs to list"""
        ids_str = self.cleaned_data.get('service_ids', '')
        try:
            ids = [int(id.strip()) for id in ids_str.split(',') if id.strip()]
            if not ids:
                raise ValidationError(_("No services selected"))
            return ids
        except ValueError:
            raise ValidationError(_("Invalid service IDs"))

class CategoryForm(forms.ModelForm):
    efris_category_search = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Search EFRIS categories...',
            'autocomplete': 'off',
            'id': 'efris-category-search',
            'data-type': 'product',  # Will be set dynamically
        }),
        label="Search EFRIS Commodity Category",
        help_text="Type to search (min 3 characters). Only leaf nodes are shown."
    )

    class Meta:
        model = Category
        fields = [
            'name',
            'code',
            'category_type',
            'description',
            'efris_commodity_category_code',
            'efris_auto_sync',
            'is_active',
        ]
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g., Electronics, Cleaning Services'
            }),
            'code': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Optional internal code'
            }),
            'category_type': forms.Select(attrs={
                'class': 'form-select',
                'id': 'category-type-select',
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Optional description'
            }),
            'efris_commodity_category_code': forms.HiddenInput(attrs={
                'id': 'efris-category-code-hidden'
            }),
            'efris_auto_sync': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
            'is_active': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # If editing existing category, populate search field
        if self.instance.pk and self.instance.efris_commodity_category:
            efris_cat = self.instance.efris_commodity_category
            self.fields['efris_category_search'].initial = (
                f"{efris_cat.commodity_category_code} - {efris_cat.commodity_category_name}"
            )

    def clean_efris_commodity_category_code(self):
        """Validate EFRIS commodity category"""
        code = self.cleaned_data.get('efris_commodity_category_code')
        category_type = self.cleaned_data.get('category_type')

        if not code:
            return code

        try:
            efris_cat = EFRISCommodityCategory.objects.get(
                commodity_category_code=code
            )

            # Validate it's a leaf node
            if efris_cat.is_leaf_node != '101':
                raise ValidationError(
                    "Selected EFRIS category is not a leaf node. "
                    "Only leaf nodes can be used for products/services."
                )

            # Validate type matches
            efris_type = 'service' if efris_cat.service_mark == '102' else 'product'
            if category_type and category_type != efris_type:
                raise ValidationError(
                    f"EFRIS category is a {efris_type}, but you selected "
                    f"category type as {category_type}. Please select a matching category."
                )

            return code

        except EFRISCommodityCategory.DoesNotExist:
            raise ValidationError("Invalid EFRIS commodity category code.")

    def clean(self):
        """Additional cross-field validation"""
        cleaned_data = super().clean()

        efris_auto_sync = cleaned_data.get('efris_auto_sync')
        efris_code = cleaned_data.get('efris_commodity_category_code')

        # If auto-sync enabled, EFRIS category is required
        if efris_auto_sync and not efris_code:
            raise ValidationError(
                "EFRIS Commodity Category is required when auto-sync is enabled."
            )

        return cleaned_data


class QuickCategoryForm(forms.ModelForm):
    """
    Simplified form for quick category creation (e.g., in modals)
    """

    class Meta:
        model = Category
        fields = ['name', 'category_type']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Category name',
                'required': True,
            }),
            'category_type': forms.Select(attrs={
                'class': 'form-select',
                'required': True,
            }),
        }

class CattegoryForm(forms.ModelForm):
    efris_commodity_category = forms.ModelChoiceField(
        queryset=EFRISCommodityCategory.objects.all(),
        required=False,
        widget=forms.Select(attrs={
            'class': 'form-control efris-category-select',
            'data-ajax-url': '/inventory/api/efris-categories/search/'
        }),
        label='EFRIS Commodity Category',
        help_text='Search and select the official EFRIS commodity category'
    )

    class Meta:
        model = Category
        fields = [
            'name', 'code', 'description',
            'efris_commodity_category',
            'efris_auto_sync', 'is_active'
        ]
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Category name'
            }),
            'code': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Short code (optional)'
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Category description'
            }),
            'efris_auto_sync': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
            'is_active': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Filter by company if available
        request = kwargs.get('request')
        if request and hasattr(request, 'user') and hasattr(request.user, 'company'):
            self.fields['efris_commodity_category'].queryset = (
                EFRISCommodityCategory.objects.filter(company=request.user.company)
            )


class StockManagementForm(forms.ModelForm):
    """Enhanced form for comprehensive stock management"""

    class Meta:
        model = Stock
        fields = [
            'product', 'store', 'quantity', 'low_stock_threshold',
            'reorder_quantity', 'last_physical_count_quantity'
        ]
        widgets = {
            'product': forms.Select(attrs={
                'class': 'form-control',
                'data-live-search': 'true'
            }),
            'store': forms.Select(attrs={
                'class': 'form-control'
            }),
            'quantity': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.001',
                'min': '0'
            }),
            'low_stock_threshold': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.001',
                'min': '0',
                'help_text': 'Alert when stock falls below this level'
            }),
            'reorder_quantity': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.001',
                'min': '0',
                'help_text': 'Recommended quantity to order when restocking'
            }),
            'last_physical_count_quantity': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.001',
                'min': '0',
                'readonly': True,
                'help_text': 'Last recorded physical count'
            })
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['product'].queryset = Product.objects.filter(is_active=True).select_related('category')
        self.fields['store'].queryset = Store.objects.filter(is_active=True)

        # Add labels and help text
        self.fields['low_stock_threshold'].help_text = 'System will alert when stock falls below this level'
        self.fields['reorder_quantity'].help_text = 'Suggested quantity to reorder when restocking'

    def clean(self):
        cleaned_data = super().clean()
        quantity = cleaned_data.get('quantity')
        low_stock_threshold = cleaned_data.get('low_stock_threshold')
        reorder_quantity = cleaned_data.get('reorder_quantity')

        # Validation logic
        if low_stock_threshold and reorder_quantity:
            if low_stock_threshold > reorder_quantity:
                raise ValidationError(
                    "Low stock threshold should not be higher than reorder quantity"
                )

        return cleaned_data


class SupplierForm(forms.ModelForm):
    class Meta:
        model = Supplier
        fields = [
            'name', 'tin', 'contact_person', 'phone', 'email',
            'address', 'country', 'is_active'
        ]
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Supplier name'
            }),
            'tin': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Tax Identification Number'
            }),
            'contact_person': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Contact person name'
            }),
            'phone': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Phone number'
            }),
            'email': forms.EmailInput(attrs={
                'class': 'form-control',
                'placeholder': 'Email address'
            }),
            'address': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Physical address'
            }),
            'country': forms.TextInput(attrs={
                'class': 'form-control',
                'value': 'Uganda'
            }),
            'is_active': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
        }

    def clean_phone(self):
        phone = self.cleaned_data.get('phone')
        if phone and not phone.replace('+', '').replace('-', '').replace(' ', '').isdigit():
            raise ValidationError("Please enter a valid phone number.")
        return phone



class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = [
            'name', 'sku', 'barcode', 'description', 'category', 'supplier',
            'selling_price', 'cost_price', 'discount_percentage', 'tax_rate',
            'excise_duty_rate', 'unit_of_measure', 'min_stock_level',
            'is_active', 'image', 'efris_auto_sync_enabled', 'efris_excise_duty_code'
        ]
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Enter product name'}),
            'sku': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Enter or generate SKU'}),
            'barcode': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Enter or generate barcode'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Enter product description'}),
            'category': forms.Select(attrs={'class': 'form-select'}),
            'supplier': forms.Select(attrs={'class': 'form-select'}),
            'selling_price': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0'}),
            'cost_price': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0'}),
            'discount_percentage': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0', 'max': '100', 'value': '0'}),
            'tax_rate': forms.Select(attrs={'class': 'form-select'}),
            'excise_duty_rate': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0', 'value': '0'}),
            'unit_of_measure': forms.Select(attrs={'class': 'form-select'}),
            'min_stock_level': forms.NumberInput(attrs={'class': 'form-control', 'min': '0', 'value': '5'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input', 'checked': True}),
            'image': forms.FileInput(attrs={'class': 'form-control'}),
            'efris_auto_sync_enabled': forms.CheckboxInput(attrs={'class': 'form-check-input', 'checked': True}),
            'efris_excise_duty_code': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Enter EFRIS excise duty code'}),
        }

    def clean(self):
        cleaned_data = super().clean()
        category = cleaned_data.get('category')
        efris_auto_sync = cleaned_data.get('efris_auto_sync_enabled')
        cost_price = cleaned_data.get('cost_price')
        selling_price = cleaned_data.get('selling_price')

        # Validate EFRIS configuration if auto sync is enabled
        if efris_auto_sync and category:
            if not category.efris_commodity_category_code:
                raise ValidationError({
                    'category': f"Category '{category.name}' must have an EFRIS commodity category assigned before enabling EFRIS sync."
                })

        # Validate pricing
        if cost_price and selling_price and cost_price > selling_price:
            raise ValidationError({
                'selling_price': 'Selling price cannot be less than cost price.'
            })

        return cleaned_data


class StockForm(forms.ModelForm):
    """Form for creating and updating stock records"""

    class Meta:
        model = Stock
        fields = [
            'product',
            'store',
            'quantity',
            'low_stock_threshold',
            'reorder_quantity',
            'last_physical_count_quantity',
        ]
        widgets = {
            'product': forms.Select(attrs={
                'class': 'form-select',
                'id': 'id_product'
            }),
            'store': forms.Select(attrs={
                'class': 'form-select',
                'id': 'id_store'
            }),
            'quantity': forms.NumberInput(attrs={
                'class': 'form-control',
                'id': 'id_quantity',
                'step': '0.001',
                'min': '0'
            }),
            'low_stock_threshold': forms.NumberInput(attrs={
                'class': 'form-control',
                'id': 'id_low_stock_threshold',
                'step': '0.001',
                'min': '0'
            }),
            'reorder_quantity': forms.NumberInput(attrs={
                'class': 'form-control',
                'id': 'id_reorder_quantity',
                'step': '0.001',
                'min': '0'
            }),
            'last_physical_count_quantity': forms.NumberInput(attrs={
                'class': 'form-control',
                'id': 'id_last_physical_count_quantity',
                'step': '0.001',
                'min': '0',
                'readonly': 'readonly'
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Set queryset for product field
        self.fields['product'].queryset = Product.objects.filter(
            is_active=True
        ).select_related('category', 'supplier').order_by('name')

        # Set queryset for store field
        self.fields['store'].queryset = Store.objects.filter(
            is_active=True
        ).order_by('name')

        # Make last_physical_count_quantity read-only for display
        self.fields['last_physical_count_quantity'].required = False
        self.fields['last_physical_count_quantity'].disabled = True

        # Set help texts
        self.fields['quantity'].help_text = 'Current stock quantity'
        self.fields['low_stock_threshold'].help_text = 'Alert when stock falls below this level'
        self.fields['reorder_quantity'].help_text = 'Suggested reorder quantity'

        # If updating, make product and store read-only
        if self.instance.pk:
            self.fields['product'].disabled = True
            self.fields['store'].disabled = True
            self.fields['product'].help_text = 'Cannot change product for existing stock record'
            self.fields['store'].help_text = 'Cannot change store for existing stock record'

    def clean(self):
        cleaned_data = super().clean()
        product = cleaned_data.get('product')
        store = cleaned_data.get('store')
        quantity = cleaned_data.get('quantity')
        low_stock_threshold = cleaned_data.get('low_stock_threshold')
        reorder_quantity = cleaned_data.get('reorder_quantity')

        # Validate quantity
        if quantity is not None and quantity < 0:
            self.add_error('quantity', 'Quantity cannot be negative')

        # Validate thresholds
        if low_stock_threshold is not None and low_stock_threshold < 0:
            self.add_error('low_stock_threshold', 'Threshold cannot be negative')

        if reorder_quantity is not None and reorder_quantity < 0:
            self.add_error('reorder_quantity', 'Reorder quantity cannot be negative')

        # Check for duplicate (only on create)
        if not self.instance.pk and product and store:
            if Stock.objects.filter(product=product, store=store).exists():
                raise forms.ValidationError(
                    f'Stock record already exists for {product.name} at {store.name}'
                )

        return cleaned_data

class ProductCreateForm(ProductForm):
    """Simplified form for creating products - focuses on essential fields"""

    class Meta(ProductForm.Meta):
        fields = [
            'name', 'sku', 'barcode', 'description', 'category', 'supplier',
            'selling_price', 'cost_price', 'tax_rate', 'unit_of_measure',
            'min_stock_level', 'is_active'
            # REMOVED EFRIS fields - they're inherited from category
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Mark required fields
        self.fields['name'].required = True
        self.fields['sku'].required = True
        self.fields['category'].required = True  # Required for EFRIS
        self.fields['selling_price'].required = True
        self.fields['cost_price'].required = True

        # Set helpful defaults
        self.fields['tax_rate'].initial = 'A'  # Standard rate
        self.fields['unit_of_measure'].initial = 'each'
        self.fields['min_stock_level'].initial = 5


class ProductUpdateForm(ProductForm):
    """Full form for updating products - includes all fields including EFRIS"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Add readonly computed EFRIS fields as display
        if self.instance and self.instance.pk:
            # Show computed EFRIS values (read-only)
            efris_info = forms.CharField(
                required=False,
                widget=forms.TextInput(attrs={
                    'readonly': True,
                    'class': 'form-control-plaintext',
                }),
                help_text="Computed from category"
            )

            # Add display fields for computed EFRIS values
            self.fields['efris_commodity_category_display'] = forms.CharField(
                required=False,
                label='EFRIS Commodity Category',
                widget=forms.TextInput(attrs={
                    'readonly': True,
                    'class': 'form-control-plaintext',
                }),
                initial=f"{self.instance.efris_commodity_category_id} - {self.instance.efris_commodity_category_name}",
                help_text="Inherited from category"
            )

            self.fields['efris_tax_category_display'] = forms.CharField(
                required=False,
                label='EFRIS Tax Category',
                widget=forms.TextInput(attrs={
                    'readonly': True,
                    'class': 'form-control-plaintext',
                }),
                initial=f"{self.instance.efris_tax_category_id} ({self.instance.efris_tax_rate}%)",
                help_text="Auto-mapped from tax rate"
            )

            self.fields['efris_unit_measure_display'] = forms.CharField(
                required=False,
                label='EFRIS Unit of Measure',
                widget=forms.TextInput(attrs={
                    'readonly': True,
                    'class': 'form-control-plaintext',
                }),
                initial=self.instance.efris_unit_of_measure_code,
                help_text="Auto-mapped from unit of measure"
            )


class ProductBulkUpdateForm(forms.Form):
    """Form for bulk updating multiple products"""

    products = forms.ModelMultipleChoiceField(
        queryset=Product.objects.all(),
        widget=forms.CheckboxSelectMultiple,
        required=True
    )

    # Fields that can be bulk updated
    category = forms.ModelChoiceField(
        queryset=Category.objects.filter(is_active=True),
        required=False,
        empty_label="Keep existing"
    )

    supplier = forms.ModelChoiceField(
        queryset=Supplier.objects.filter(is_active=True),
        required=False,
        empty_label="Keep existing"
    )

    tax_rate = forms.ChoiceField(
        choices=[('', 'Keep existing')] + Product.TAX_RATE_CHOICES,
        required=False
    )

    discount_percentage = forms.DecimalField(
        max_digits=5,
        decimal_places=2,
        required=False,
        min_value=0,
        max_value=100,
        help_text="Leave blank to keep existing"
    )

    is_active = forms.ChoiceField(
        choices=[
            ('', 'Keep existing'),
            (True, 'Active'),
            (False, 'Inactive')
        ],
        required=False
    )

    # EFRIS bulk actions
    efris_auto_sync_enabled = forms.ChoiceField(
        choices=[
            ('', 'Keep existing'),
            (True, 'Enable EFRIS sync'),
            (False, 'Disable EFRIS sync')
        ],
        required=False
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        for field_name, field in self.fields.items():
            if hasattr(field.widget, 'attrs'):
                field.widget.attrs.update({'class': 'form-control'})


class ProductImportForm(forms.Form):
    """Form for importing products from CSV/Excel"""

    file = forms.FileField(
        help_text="Upload CSV or Excel file with product data",
        widget=forms.FileInput(attrs={
            'class': 'form-control',
            'accept': '.csv,.xlsx,.xls'
        })
    )

    update_existing = forms.BooleanField(
        required=False,
        initial=False,
        help_text="Update existing products if SKU matches",
        widget=forms.CheckboxInput(attrs={
            'class': 'form-check-input'
        })
    )

    create_categories = forms.BooleanField(
        required=False,
        initial=True,
        help_text="Create categories that don't exist",
        widget=forms.CheckboxInput(attrs={
            'class': 'form-check-input'
        })
    )

    create_suppliers = forms.BooleanField(
        required=False,
        initial=True,
        help_text="Create suppliers that don't exist",
        widget=forms.CheckboxInput(attrs={
            'class': 'form-check-input'
        })
    )

    def clean_file(self):
        file = self.cleaned_data.get('file')
        if file:
            # Check file size (max 5MB)
            if file.size > 5 * 1024 * 1024:
                raise ValidationError("File size cannot exceed 5MB")

            # Check file extension
            valid_extensions = ['.csv', '.xlsx', '.xls']
            if not any(file.name.lower().endswith(ext) for ext in valid_extensions):
                raise ValidationError("Only CSV and Excel files are allowed")

        return file

class StockMovementForm(forms.ModelForm):
    class Meta:
        model = StockMovement
        fields = [
            'product', 'store', 'movement_type', 'quantity',
            'reference', 'notes', 'unit_price'
        ]
        widgets = {
            'product': forms.Select(attrs={
                'class': 'form-control',
                'required': True
            }),
            'store': forms.Select(attrs={
                'class': 'form-control',
                'required': True
            }),
            'movement_type': forms.Select(attrs={
                'class': 'form-control',
                'required': True
            }),
            'quantity': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.001',
                'min': '0.001',
                'required': True
            }),
            'reference': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Reference number (optional)'
            }),
            'notes': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Additional notes (optional)'
            }),
            'unit_price': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'min': '0',
                'placeholder': 'Unit price (optional)'
            }),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        self.fields['product'].queryset = Product.objects.filter(is_active=True)
        self.fields['store'].queryset = Store.objects.filter(is_active=True)
        self.fields['product'].empty_label = "Select Product"
        self.fields['store'].empty_label = "Select Store"

    def clean(self):
        cleaned_data = super().clean()
        product = cleaned_data.get('product')
        store = cleaned_data.get('store')
        movement_type = cleaned_data.get('movement_type')
        quantity = cleaned_data.get('quantity')

        if product and store and movement_type and quantity:
            # Check stock availability for outbound movements
            if movement_type in ['SALE', 'TRANSFER_OUT']:
                try:
                    stock = Stock.objects.get(product=product, store=store)
                    if stock.quantity < quantity:
                        raise ValidationError(
                            f"Insufficient stock. Only {stock.quantity} {product.unit_of_measure} available."
                        )
                except Stock.DoesNotExist:
                    raise ValidationError(
                        "No stock record exists for this product in the selected store."
                    )

        return cleaned_data


class ProductFilterForm(forms.Form):
    search = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Search products by name, SKU, or barcode...'
        })
    )
    category = forms.ModelChoiceField(
        queryset=Category.objects.filter(is_active=True),
        required=False,
        empty_label="All Categories",
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    supplier = forms.ModelChoiceField(
        queryset=Supplier.objects.filter(is_active=True),
        required=False,
        empty_label="All Suppliers",
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    tax_rate = forms.ChoiceField(
        choices=[('', 'All Tax Rates')] + Product.TAX_RATE_CHOICES,
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    is_active = forms.ChoiceField(
        choices=[('', 'All'), ('True', 'Active'), ('False', 'Inactive')],
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    min_price = forms.DecimalField(
        required=False,
        min_value=0,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': 'Min price',
            'step': '0.01'
        })
    )
    max_price = forms.DecimalField(
        required=False,
        min_value=0,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': 'Max price',
            'step': '0.01'
        })
    )

    # Stock level filters
    stock_status = forms.ChoiceField(
        choices=[
            ('', 'All Stock Levels'),
            ('in_stock', 'In Stock'),
            ('low_stock', 'Low Stock'),
            ('out_of_stock', 'Out of Stock'),
        ],
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    has_physical_count = forms.ChoiceField(
        choices=[
            ('', 'All Products'),
            ('yes', 'Has Physical Count'),
            ('no', 'No Physical Count')
        ],
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'}),
        help_text='Filter by physical count status'
    )
    efris_sync_required = forms.ChoiceField(
        choices=[
            ('', 'All Products'),
            ('yes', 'Needs EFRIS Sync'),
            ('no', 'EFRIS Sync Up to Date')
        ],
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'}),
        help_text='Filter by EFRIS sync status'
    )

    # EFRIS filters
    efris_sync_enabled = forms.ChoiceField(
        choices=[
            ('', 'All Products'),
            ('True', 'EFRIS Sync Enabled'),
            ('False', 'EFRIS Sync Disabled')
        ],
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'})
    )

    efris_upload_status = forms.ChoiceField(
        choices=[
            ('', 'All Upload Status'),
            ('uploaded', 'Uploaded to EFRIS'),
            ('pending', 'Pending Upload'),
            ('failed', 'Upload Failed')
        ],
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'})
    )

    def clean(self):
        cleaned_data = super().clean()
        min_price = cleaned_data.get('min_price')
        max_price = cleaned_data.get('max_price')

        if min_price and max_price and min_price > max_price:
            raise ValidationError("Minimum price cannot be greater than maximum price.")

        return cleaned_data


class PhysicalStockCountForm(forms.Form):
    """Form for recording physical stock counts"""

    product = forms.ModelChoiceField(
        queryset=Product.objects.filter(is_active=True),
        widget=forms.Select(attrs={
            'class': 'form-control',
            'required': True
        }),
        empty_label="Select Product"
    )

    store = forms.ModelChoiceField(
        queryset=Store.objects.filter(is_active=True),
        widget=forms.Select(attrs={
            'class': 'form-control',
            'required': True
        }),
        empty_label="Select Store"
    )

    counted_quantity = forms.DecimalField(
        max_digits=12,
        decimal_places=3,
        min_value=0,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'step': '0.001',
            'min': '0',
            'required': True,
            'placeholder': 'Enter counted quantity'
        })
    )

    count_date = forms.DateTimeField(
        initial=timezone.now,
        widget=forms.DateTimeInput(attrs={
            'class': 'form-control',
            'type': 'datetime-local'
        })
    )

    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 3,
            'placeholder': 'Notes about the physical count (optional)'
        })
    )

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

    def save(self):
        """Process physical count and create adjustment if needed"""
        cleaned_data = self.cleaned_data
        product = cleaned_data['product']
        store = cleaned_data['store']
        counted_quantity = cleaned_data['counted_quantity']
        notes = cleaned_data.get('notes', '')

        # Get or create stock record
        stock, created = Stock.objects.get_or_create(
            product=product,
            store=store,
            defaults={'quantity': counted_quantity}
        )

        # Record physical count using the enhanced Stock model method
        stock.record_physical_count(counted_quantity, self.user)

        return stock


class StockAdjustmentForm(forms.Form):
    product = forms.ModelChoiceField(
        queryset=Product.objects.filter(is_active=True),
        widget=forms.Select(attrs={
            'class': 'form-control',
            'required': True
        }),
        empty_label="Select Product"
    )
    store = forms.ModelChoiceField(
        queryset=Store.objects.filter(is_active=True),
        widget=forms.Select(attrs={
            'class': 'form-control',
            'required': True
        }),
        empty_label="Select Store"
    )
    adjustment_type = forms.ChoiceField(
        choices=[
            ('add', 'Add Stock'),
            ('remove', 'Remove Stock'),
            ('set', 'Set Stock Level')
        ],
        widget=forms.Select(attrs={
            'class': 'form-control',
            'required': True
        })
    )
    quantity = forms.DecimalField(
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'step': '0.001',
            'min': '0.001',
            'required': True,
            'placeholder': 'Quantity'
        })
    )
    reason = forms.CharField(
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Reason for adjustment',
            'required': True
        })
    )
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 3,
            'placeholder': 'Additional notes (optional)'
        })
    )

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

    def save(self):
        """Create stock movement and update stock"""
        cleaned_data = self.cleaned_data
        product = cleaned_data['product']
        store = cleaned_data['store']
        adjustment_type = cleaned_data['adjustment_type']
        quantity = cleaned_data['quantity']
        reason = cleaned_data['reason']
        notes = cleaned_data.get('notes', '')

        # Get or create stock record
        stock, created = Stock.objects.get_or_create(
            product=product,
            store=store,
            defaults={
                'quantity': Decimal('0'),
                'low_stock_threshold': Decimal('5'),  # Default threshold
                'reorder_quantity': Decimal('10')     # Default reorder quantity
            }
        )

        old_quantity = stock.quantity

        # Calculate new quantity based on adjustment type
        if adjustment_type == 'add':
            new_quantity = old_quantity + quantity
            movement_quantity = quantity
        elif adjustment_type == 'remove':
            new_quantity = max(Decimal('0'), old_quantity - quantity)
            movement_quantity = -(min(quantity, old_quantity))
        else:  # set
            new_quantity = quantity
            movement_quantity = new_quantity - old_quantity

        # Create stock movement
        movement = StockMovement.objects.create(
            product=product,
            store=store,
            movement_type='ADJUSTMENT',
            quantity=movement_quantity,
            reference=f'ADJ-{timezone.now().strftime("%Y%m%d%H%M%S")}',
            notes=f'{reason}. {notes}'.strip(),
            created_by=self.user
        )

        # Update stock quantity
        stock.quantity = new_quantity
        stock.save()

        return movement


class BulkActionForm(forms.Form):
    action = forms.ChoiceField(
        choices=[
            ('', 'Select Action'),
            ('activate', 'Activate Selected'),
            ('deactivate', 'Deactivate Selected'),
            ('delete', 'Delete Selected'),
            ('export', 'Export Selected'),
        ],
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    selected_items = forms.CharField(
        widget=forms.HiddenInput()
    )

    def clean_selected_items(self):
        items = self.cleaned_data.get('selected_items', '')
        if not items:
            raise ValidationError("Please select items to perform the action.")

        try:
            item_ids = [int(x) for x in items.split(',') if x.strip()]
            if not item_ids:
                raise ValidationError("No valid items selected.")
            return item_ids
        except (ValueError, TypeError):
            raise ValidationError("Invalid item selection.")

    def clean(self):
        cleaned_data = super().clean()
        action = cleaned_data.get('action')
        items = cleaned_data.get('selected_items')

        if not action:
            raise ValidationError("Please select an action.")

        if not items:
            raise ValidationError("Please select items.")

        return cleaned_data


class BulkStockImportForm(forms.Form):
    """Enhanced form for bulk stock imports"""

    file = forms.FileField(
        widget=forms.FileInput(attrs={
            'class': 'form-control',
            'accept': '.csv,.xlsx,.xls'
        }),
        help_text='Upload CSV or Excel file with stock data (max 10MB)'
    )

    update_existing = forms.BooleanField(
        required=False,
        initial=True,
        help_text='Update existing stock records',
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )

    create_missing_products = forms.BooleanField(
        required=False,
        initial=False,
        help_text='Create products that don\'t exist',
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )

    update_thresholds = forms.BooleanField(
        required=False,
        initial=True,
        help_text='Update low stock thresholds and reorder quantities',
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )

    mark_efris_sync = forms.BooleanField(
        required=False,
        initial=False,
        help_text='Mark updated stock records for EFRIS sync',
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )

    conflict_resolution = forms.ChoiceField(
        choices=[
            ('overwrite', 'Overwrite existing quantities'),
            ('add', 'Add to existing quantities'),
            ('skip', 'Skip existing records'),
        ],
        initial='overwrite',
        widget=forms.Select(attrs={'class': 'form-control'}),
        help_text='How to handle existing stock records'
    )

    def clean_file(self):
        file = self.cleaned_data.get('file')
        if file:
            # Check file size (max 10MB)
            if file.size > 10 * 1024 * 1024:
                raise ValidationError("File size cannot exceed 10MB")

            # Check file extension
            valid_extensions = ['.csv', '.xlsx', '.xls']
            if not any(file.name.lower().endswith(ext) for ext in valid_extensions):
                raise ValidationError("Only CSV and Excel files are allowed")

        return file


class StockReportFilterForm(forms.Form):
    """Form for filtering stock reports"""

    store = forms.ModelChoiceField(
        queryset=Store.objects.filter(is_active=True),
        required=False,
        empty_label="All Stores",
        widget=forms.Select(attrs={'class': 'form-control'})
    )

    category = forms.ModelChoiceField(
        queryset=Category.objects.filter(is_active=True),
        required=False,
        empty_label="All Categories",
        widget=forms.Select(attrs={'class': 'form-control'})
    )

    stock_status = forms.ChoiceField(
        choices=[
            ('', 'All Stock Levels'),
            ('out_of_stock', 'Out of Stock'),
            ('critical', 'Critical (Below 50% of threshold)'),
            ('low_stock', 'Low Stock (Below threshold)'),
            ('good_stock', 'Good Stock (Above threshold)'),
        ],
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'})
    )

    has_movements = forms.ChoiceField(
        choices=[
            ('', 'All Products'),
            ('recent', 'With Recent Movements (30 days)'),
            ('none', 'No Recent Movements'),
        ],
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'})
    )

    efris_sync_status = forms.ChoiceField(
        choices=[
            ('', 'All Records'),
            ('required', 'EFRIS Sync Required'),
            ('up_to_date', 'EFRIS Up to Date'),
        ],
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'})
    )

    date_from = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={
            'class': 'form-control',
            'type': 'date'
        })
    )

    date_to = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={
            'class': 'form-control',
            'type': 'date'
        })
    )

    def clean(self):
        cleaned_data = super().clean()
        date_from = cleaned_data.get('date_from')
        date_to = cleaned_data.get('date_to')

        if date_from and date_to and date_from > date_to:
            raise ValidationError("Start date must be before end date")

        return cleaned_data


class StockForm(forms.ModelForm):
    class Meta:
        model = Stock
        fields = ['product', 'store', 'quantity', 'low_stock_threshold', 'reorder_quantity']  # Updated field names
        widgets = {
            'product': forms.Select(attrs={
                'class': 'form-select',
                'data-placeholder': 'Select product'
            }),
            'store': forms.Select(attrs={
                'class': 'form-select',
                'data-placeholder': 'Select store'
            }),
            'quantity': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.001',
                'min': '0'
            }),
            'low_stock_threshold': forms.NumberInput(attrs={  # Updated field name
                'class': 'form-control',
                'step': '0.001',
                'min': '0'
            }),
            'reorder_quantity': forms.NumberInput(attrs={  # New field
                'class': 'form-control',
                'step': '0.001',
                'min': '0'
            })
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['product'].queryset = Product.objects.filter(is_active=True)


class BulkProductImportForm(forms.Form):
    csv_file = forms.FileField(
        validators=[FileExtensionValidator(allowed_extensions=['csv', 'xlsx', 'xls'])],
        help_text='Upload a CSV or Excel file containing product data (max 10MB)',
        widget=forms.FileInput(attrs={
            'class': 'form-control',
            'accept': '.csv,.xlsx,.xls'
        })
    )

    update_existing = forms.BooleanField(
        required=False,
        initial=True,
        help_text='Update existing products when SKU matches',
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )

    create_missing_categories = forms.BooleanField(
        required=False,
        initial=True,
        help_text='Automatically create categories that don\'t exist',
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )

    create_missing_suppliers = forms.BooleanField(
        required=False,
        initial=True,
        help_text='Automatically create suppliers that don\'t exist',
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )

    validate_prices = forms.BooleanField(
        required=False,
        initial=True,
        help_text='Validate that selling price >= cost price',
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )

    enable_efris_sync = forms.BooleanField(
        required=False,
        initial=True,
        help_text='Enable EFRIS sync for imported products',
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )

    def clean_csv_file(self):
        file = self.cleaned_data.get('csv_file')
        if file:
            # Check file size (max 10MB)
            if file.size > 10 * 1024 * 1024:
                raise ValidationError("File size cannot exceed 10MB")
        return file


class ImportMappingForm(forms.Form):
    """Form for handling column mapping during import"""
    IMPORT_MODE_CHOICES = [
        ('add', 'Add new products only'),
        ('update', 'Update existing products only'),
        ('both', 'Add new and update existing'),
    ]

    CONFLICT_RESOLUTION_CHOICES = [
        ('skip', 'Skip conflicting products'),
        ('overwrite', 'Overwrite with imported data'),
        ('merge', 'Merge stock quantities only'),
    ]

    import_mode = forms.ChoiceField(
        choices=IMPORT_MODE_CHOICES,
        initial='both',
        widget=forms.Select(attrs={'class': 'form-select'})
    )

    conflict_resolution = forms.ChoiceField(
        choices=CONFLICT_RESOLUTION_CHOICES,
        initial='overwrite',
        widget=forms.Select(attrs={'class': 'form-select'})
    )

    has_header = forms.BooleanField(
        required=False,
        initial=True,
        help_text='First row contains column headers',
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )

    notify_on_completion = forms.BooleanField(
        required=False,
        initial=True,
        help_text='Send email notification when import completes',
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )

    dry_run = forms.BooleanField(
        required=False,
        initial=False,
        help_text='Preview import without making changes',
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )

    # Column mapping fields (dynamically added based on CSV headers)
    def __init__(self, *args, csv_headers=None, **kwargs):
        super().__init__(*args, **kwargs)

        if csv_headers:
            # Define available product fields for mapping
            PRODUCT_FIELDS = [
                ('', 'Skip this column'),
                ('name', 'Product Name'),
                ('sku', 'SKU Code'),
                ('barcode', 'Barcode'),
                ('description', 'Description'),
                ('selling_price', 'Selling Price'),
                ('cost_price', 'Cost Price'),
                ('discount_percentage', 'Discount Percentage'),
                ('tax_rate', 'Tax Rate'),
                ('excise_duty_rate', 'Excise Duty Rate'),
                ('unit_of_measure', 'Unit of Measure'),
                ('min_stock_level', 'Minimum Stock Level'),
                ('stock_level', 'Current Stock Level'),
                ('category_name', 'Category Name'),
                ('supplier_name', 'Supplier Name'),
                ('is_active', 'Active Status'),
            ]

            # Add mapping field for each CSV column
            for i, header in enumerate(csv_headers):
                field_name = f'column_{i}'
                self.fields[field_name] = forms.ChoiceField(
                    choices=PRODUCT_FIELDS,
                    required=False,
                    label=f'Map "{header}" to',
                    widget=forms.Select(attrs={'class': 'form-select'})
                )

                # Try to auto-match common column names
                header_lower = header.lower().replace(' ', '_')
                for field_value, field_label in PRODUCT_FIELDS[1:]:  # Skip empty option
                    if field_value in header_lower or header_lower in field_value:
                        self.fields[field_name].initial = field_value
                        break


class ProductExportForm(forms.Form):
    """Form for exporting products to CSV/Excel"""

    FORMAT_CHOICES = [
        ('csv', 'CSV File'),
        ('xlsx', 'Excel File'),
    ]

    export_format = forms.ChoiceField(
        choices=FORMAT_CHOICES,
        initial='xlsx',
        widget=forms.Select(attrs={'class': 'form-select'})
    )

    # Fields to include in export
    include_basic_info = forms.BooleanField(
        required=False,
        initial=True,
        label='Basic Information',
        help_text='Name, SKU, barcode, description',
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )

    include_pricing = forms.BooleanField(
        required=False,
        initial=True,
        label='Pricing Information',
        help_text='Selling price, cost price, discount',
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )

    include_tax_info = forms.BooleanField(
        required=False,
        initial=True,
        label='Tax Information',
        help_text='Tax rate, excise duty rate',
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )

    include_stock_info = forms.BooleanField(
        required=False,
        initial=True,
        label='Stock Information',
        help_text='Stock levels, minimum stock',
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )

    include_efris_info = forms.BooleanField(
        required=False,
        initial=False,
        label='EFRIS Information',
        help_text='EFRIS sync status, upload dates, computed EFRIS values',
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )

    include_relationships = forms.BooleanField(
        required=False,
        initial=True,
        label='Category & Supplier',
        help_text='Category and supplier information',
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )

    # Filter options
    active_only = forms.BooleanField(
        required=False,
        initial=True,
        help_text='Export only active products',
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )

    category = forms.ModelChoiceField(
        queryset=Category.objects.filter(is_active=True),
        required=False,
        empty_label="All Categories",
        help_text='Export products from specific category only',
        widget=forms.Select(attrs={'class': 'form-select'})
    )

    def clean(self):
        cleaned_data = super().clean()

        # Ensure at least one field group is selected
        field_groups = [
            'include_basic_info', 'include_pricing', 'include_tax_info',
            'include_stock_info', 'include_efris_info', 'include_relationships'
        ]

        if not any(cleaned_data.get(field) for field in field_groups):
            raise ValidationError("Please select at least one information group to export.")

        return cleaned_data


class ProductSearchForm(forms.Form):
    """Quick search form for AJAX product lookups"""

    q = forms.CharField(
        max_length=255,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Search products...',
            'autocomplete': 'off'
        })
    )

    limit = forms.IntegerField(
        initial=10,
        min_value=1,
        max_value=50,
        widget=forms.HiddenInput()
    )

    include_inactive = forms.BooleanField(
        required=False,
        initial=False,
        widget=forms.HiddenInput()
    )


class ProductStockAdjustmentForm(forms.Form):
    """Form for adjusting product stock levels"""

    ADJUSTMENT_TYPES = [
        ('add', 'Add Stock'),
        ('subtract', 'Remove Stock'),
        ('set', 'Set Stock Level'),
    ]

    products = forms.ModelMultipleChoiceField(
        queryset=Product.objects.filter(is_active=True),
        widget=forms.CheckboxSelectMultiple(attrs={'class': 'form-check-input'})
    )

    adjustment_type = forms.ChoiceField(
        choices=ADJUSTMENT_TYPES,
        widget=forms.Select(attrs={'class': 'form-select'})
    )

    quantity = forms.DecimalField(
        max_digits=10,
        decimal_places=2,
        min_value=0,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'step': '0.01'
        })
    )

    reason = forms.CharField(
        max_length=255,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Reason for adjustment (optional)'
        })
    )

    update_efris = forms.BooleanField(
        required=False,
        initial=False,
        help_text='Mark products for EFRIS re-upload after stock adjustment',
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )


class StockImportMappingForm(forms.Form):
    """Form for mapping CSV columns to Stock model fields"""

    STOCK_FIELDS = [
        ('', 'Skip this column'),
        ('product_name', 'Product Name'),
        ('product_sku', 'Product SKU'),
        ('store_name', 'Store Name'),
        ('quantity', 'Current Quantity'),
        ('low_stock_threshold', 'Low Stock Threshold'),
        ('reorder_quantity', 'Reorder Quantity'),
        ('last_physical_count_quantity', 'Last Physical Count'),
        ('cost_price', 'Cost Price'),
        ('selling_price', 'Selling Price'),
        ('category_name', 'Category Name'),
        ('supplier_name', 'Supplier Name'),
    ]

    import_mode = forms.ChoiceField(
        choices=[
            ('create_only', 'Create new stock records only'),
            ('update_only', 'Update existing stock records only'),
            ('create_and_update', 'Create new and update existing'),
        ],
        initial='create_and_update',
        widget=forms.Select(attrs={'class': 'form-control'})
    )

    has_header_row = forms.BooleanField(
        required=False,
        initial=True,
        help_text='First row contains column headers',
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )

    def __init__(self, *args, csv_columns=None, **kwargs):
        super().__init__(*args, **kwargs)

        if csv_columns:
            for i, column_name in enumerate(csv_columns):
                field_name = f'column_{i}'
                self.fields[field_name] = forms.ChoiceField(
                    choices=self.STOCK_FIELDS,
                    required=False,
                    label=f'Map "{column_name}" to:',
                    widget=forms.Select(attrs={'class': 'form-control'})
                )

                # Auto-suggest mappings based on column names
                column_lower = column_name.lower().replace(' ', '_')
                for field_value, field_label in self.STOCK_FIELDS[1:]:
                    if field_value in column_lower or any(word in column_lower for word in field_value.split('_')):
                        self.fields[field_name].initial = field_value
                        break