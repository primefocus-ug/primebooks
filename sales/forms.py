from django import forms
from django.core.exceptions import ValidationError
from django.db.models import Q
from decimal import Decimal
import json

from .models import Sale, SaleItem, Payment, Cart, CartItem, Receipt
from inventory.models import Product, Stock
from customers.models import Customer
from stores.models import Store


class SaleForm(forms.ModelForm):
    """Enhanced Sale form with branch-based store filtering and validation"""

    customer_search = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Search customer by name, phone, or email...',
            'data-toggle': 'customer-search',
            'autocomplete': 'off'
        }),
        label='Customer'
    )

    class Meta:
        model = Sale
        fields = [
            'store', 'customer', 'transaction_type', 'document_type',
            'payment_method', 'currency', 'discount_amount', 'notes'
        ]
        widgets = {
            'store': forms.Select(attrs={'class': 'form-select', 'required': True}),
            'customer': forms.HiddenInput(),
            'transaction_type': forms.Select(attrs={'class': 'form-select'}),
            'document_type': forms.Select(attrs={'class': 'form-select'}),
            'payment_method': forms.Select(attrs={'class': 'form-select', 'required': True}),
            'currency': forms.Select(attrs={'class': 'form-select'}),
            'discount_amount': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '0',
                'step': '0.01',
                'placeholder': '0.00'
            }),
            'notes': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Additional notes...'
            })
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        # Set currency choices
        self.fields['currency'].widget = forms.Select(
            choices=[('UGX', 'UGX'), ('USD', 'USD')],
            attrs={'class': 'form-select'}
        )

        # Filter stores based on branch/staff
        if self.user:
            if self.user.is_superuser:
                self.fields['store'].queryset = Store.objects.filter(is_active=True)
            else:
                self.fields['store'].queryset = Store.objects.filter(
                    staff=self.user,
                    is_active=True
                ).distinct()

        # Set initial customer search value
        if self.instance.pk and self.instance.customer:
            self.fields['customer_search'].initial = str(self.instance.customer)

        # Set defaults for new instances
        if not self.instance.pk:
            self.fields['currency'].initial = 'UGX'
            self.fields['transaction_type'].initial = 'SALE'
            self.fields['document_type'].initial = 'ORIGINAL'
            self.fields['discount_amount'].initial = 0

    def clean_store(self):
        store = self.cleaned_data.get('store')
        if not store:
            raise ValidationError("Store is required.")

        if self.user and not self.user.is_superuser:
            has_access = Store.objects.filter(
                Q(staff=self.user) | Q(branch__staff=self.user),
                id=store.id
            ).exists()
            if not has_access:
                raise ValidationError("You don't have access to this store.")

        return store

    def clean_discount_amount(self):
        discount = self.cleaned_data.get('discount_amount', 0)
        if discount is None:
            discount = Decimal('0.00')
        if discount < 0:
            raise ValidationError("Discount amount cannot be negative.")
        return discount

    def clean_customer(self):
        customer = self.cleaned_data.get('customer')
        if customer and self.user:
            # Optional: check customer belongs to user's branch stores
            has_access = True  # adjust if branch/customer access is enforced
            if not has_access:
                raise ValidationError("Invalid customer selected.")
        return customer

    def clean(self):
        cleaned_data = super().clean()
        transaction_type = cleaned_data.get('transaction_type')
        document_type = cleaned_data.get('document_type')

        # Business logic: refunds cannot use Original document type
        if transaction_type == 'REFUND' and document_type == 'ORIGINAL':
            raise ValidationError("Refunds cannot use Original document type. Use Credit Note instead.")

        return cleaned_data


class SaleItemForm(forms.ModelForm):
    """Enhanced Sale Item form with product search and dynamic pricing"""

    product_search = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Search product by name, SKU, or barcode...',
            'data-toggle': 'product-search',
            'autocomplete': 'off'
        }),
        label='Product'
    )

    class Meta:
        model = SaleItem
        fields = [
            'product', 'quantity', 'unit_price', 'tax_rate',
            'discount', 'description'
        ]
        widgets = {
            'product': forms.HiddenInput(),
            'quantity': forms.NumberInput(attrs={
                'class': 'form-control quantity-input',
                'min': '1',
                'step': '1',
                'required': True
            }),
            'unit_price': forms.NumberInput(attrs={
                'class': 'form-control price-input',
                'min': '0',
                'step': '0.01',
                'required': True
            }),
            'tax_rate': forms.Select(attrs={
                'class': 'form-select tax-rate-select'
            }),
            'discount': forms.NumberInput(attrs={
                'class': 'form-control discount-input',
                'min': '0',
                'max': '100',
                'step': '0.01',
                'placeholder': '0.00'
            }),
            'description': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Item description (optional)'
            })
        }

    def __init__(self, *args, **kwargs):
        self.store = kwargs.pop('store', None)
        super().__init__(*args, **kwargs)

        # Filter products based on store if provided
        if self.store:
            self.fields['product'].queryset = Product.objects.filter(
                stock_levels__store=self.store,
                is_active=True
            ).distinct()

        # Set initial product search value
        if self.instance.pk and self.instance.product:
            self.fields['product_search'].initial = str(self.instance.product)

    def clean_quantity(self):
        quantity = self.cleaned_data.get('quantity')
        product = self.cleaned_data.get('product')

        if quantity and quantity <= 0:
            raise ValidationError("Quantity must be greater than 0.")

        # Check stock availability if store is provided
        if product and self.store and quantity:
            try:
                stock = Stock.objects.get(product=product, store=self.store)
                if stock.quantity < quantity:
                    raise ValidationError(
                        f"Insufficient stock. Available: {stock.quantity}, Required: {quantity}"
                    )
            except Stock.DoesNotExist:
                raise ValidationError(f"No stock record found for {product.name} in this store.")

        return quantity

    def clean_unit_price(self):
        price = self.cleaned_data.get('unit_price')
        if price and price < 0:
            raise ValidationError("Unit price cannot be negative.")
        return price


class PaymentForm(forms.ModelForm):
    """Enhanced Payment form with method-specific fields"""

    class Meta:
        model = Payment
        fields = [
            'amount', 'payment_method', 'transaction_reference', 'notes'
        ]
        widgets = {
            'amount': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '0.01',
                'step': '0.01',
                'required': True
            }),
            'payment_method': forms.Select(attrs={
                'class': 'form-select payment-method-select',
                'required': True
            }),
            'transaction_reference': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Transaction reference (optional)'
            }),
            'notes': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 2,
                'placeholder': 'Payment notes...'
            })
        }

    def clean_amount(self):
        amount = self.cleaned_data.get('amount')
        if amount and amount <= 0:
            raise ValidationError("Payment amount must be greater than 0.")
        return amount


class CartForm(forms.ModelForm):
    """Enhanced Cart form"""

    customer_search = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Search customer...',
            'data-toggle': 'customer-search'
        })
    )

    class Meta:
        model = Cart
        fields = ['customer', 'notes']
        widgets = {
            'customer': forms.HiddenInput(),
            'notes': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 2,
                'placeholder': 'Cart notes...'
            })
        }


class CartItemForm(forms.ModelForm):
    """Enhanced Cart Item form"""

    class Meta:
        model = CartItem
        fields = ['product', 'quantity', 'unit_price', 'tax_rate', 'discount', 'description']
        widgets = {
            'product': forms.Select(attrs={'class': 'form-select'}),
            'quantity': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '1',
                'step': '1'
            }),
            'unit_price': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '0',
                'step': '0.01'
            }),
            'tax_rate': forms.Select(attrs={'class': 'form-select'}),
            'discount': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '0',
                'max': '100',
                'step': '0.01'
            }),
            'description': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Optional description'
            })
        }

    def clean_quantity(self):
        quantity = self.cleaned_data.get('quantity')
        if quantity and quantity <= 0:
            raise ValidationError("Quantity must be greater than 0.")
        return quantity


class QuickSaleForm(forms.Form):
    """Quick sale form for fast transactions"""

    products_data = forms.CharField(widget=forms.HiddenInput())
    customer = forms.ModelChoiceField(
        queryset=Customer.objects.all(),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    payment_method = forms.ChoiceField(
        choices=Sale.PAYMENT_METHODS,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    cash_received = forms.DecimalField(
        required=False,
        min_value=0,
        decimal_places=2,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': 'Cash received...'
        })
    )
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 2
        })
    )

    def clean_products_data(self):
        data = self.cleaned_data.get('products_data')
        try:
            products = json.loads(data)
            if not products:
                raise ValidationError("At least one product is required.")
            return products
        except json.JSONDecodeError:
            raise ValidationError("Invalid products data.")


class SaleSearchForm(forms.Form):
    """Advanced search form for sales"""

    search = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Search by invoice, customer, or transaction ID...'
        })
    )

    store = forms.ModelChoiceField(
        queryset=Store.objects.all(),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'})
    )

    transaction_type = forms.ChoiceField(
        choices=[('', 'All Types')] + Sale.TRANSACTION_TYPES,
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'})
    )

    payment_method = forms.ChoiceField(
        choices=[('', 'All Methods')] + Sale.PAYMENT_METHODS,
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'})
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

    min_amount = forms.DecimalField(
        required=False,
        min_value=0,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': 'Min amount'
        })
    )

    max_amount = forms.DecimalField(
        required=False,
        min_value=0,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': 'Max amount'
        })
    )

    is_fiscalized = forms.ChoiceField(
        choices=[
            ('', 'All'),
            ('1', 'Fiscalized'),
            ('0', 'Not Fiscalized')
        ],
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'})
    )


class RefundForm(forms.Form):
    """Form for processing refunds"""

    reason = forms.CharField(
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 3,
            'placeholder': 'Reason for refund...',
            'required': True
        })
    )

    items_to_refund = forms.CharField(
        widget=forms.HiddenInput()
    )

    refund_amount = forms.DecimalField(
        min_value=0.01,
        decimal_places=2,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'readonly': True
        })
    )

    refund_method = forms.ChoiceField(
        choices=[
            ('CASH', 'Cash'),
            ('CARD', 'Credit Card'),
            ('MOBILE_MONEY', 'Mobile Money'),
            ('BANK_TRANSFER', 'Bank Transfer'),
        ],
        widget=forms.Select(attrs={'class': 'form-select'})
    )

    def clean_items_to_refund(self):
        data = self.cleaned_data.get('items_to_refund')
        try:
            items = json.loads(data)
            if not items:
                raise ValidationError("At least one item must be selected for refund.")
            return items
        except json.JSONDecodeError:
            raise ValidationError("Invalid refund items data.")


class ReceiptForm(forms.ModelForm):
    """Form for receipt generation and reprinting"""

    class Meta:
        model = Receipt
        fields = ['is_duplicate']
        widgets = {
            'is_duplicate': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            })
        }


class BulkActionForm(forms.Form):
    """Form for bulk actions on sales"""

    ACTION_CHOICES = [
        ('fiscalize', 'Fiscalize Selected'),
        ('print_receipts', 'Print Receipts'),
        ('export_csv', 'Export to CSV'),
        ('export_excel', 'Export to Excel'),
    ]

    action = forms.ChoiceField(
        choices=ACTION_CHOICES,
        widget=forms.Select(attrs={'class': 'form-select'})
    )

    selected_sales = forms.CharField(
        widget=forms.HiddenInput()
    )

    def clean_selected_sales(self):
        data = self.cleaned_data.get('selected_sales')
        try:
            sale_ids = json.loads(data)
            if not sale_ids:
                raise ValidationError("No sales selected.")
            return sale_ids
        except json.JSONDecodeError:
            raise ValidationError("Invalid selection data.")


# Dynamic FormSets for handling multiple items
SaleItemFormSet = forms.inlineformset_factory(
    Sale,
    SaleItem,
    form=SaleItemForm,
    extra=1,
    can_delete=True,
    min_num=1,
    validate_min=True
)

PaymentFormSet = forms.inlineformset_factory(
    Sale,
    Payment,
    form=PaymentForm,
    extra=1,
    can_delete=True,
    min_num=0
)

CartItemFormSet = forms.inlineformset_factory(
    Cart,
    CartItem,
    form=CartItemForm,
    extra=1,
    can_delete=True,
    min_num=1,
    validate_min=True
)