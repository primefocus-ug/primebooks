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
    """Enhanced Sale form with document type selection and validation"""

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

    # ==================== NEW: Document Type Specific Fields ====================
    due_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={
            'class': 'form-control',
            'type': 'date',
            'id': 'due_date_field'
        }),
        label='Due Date'
    )

    terms = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 2,
            'id': 'terms_field',
            'placeholder': 'Payment terms...'
        }),
        label='Terms'
    )

    purchase_order = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'id': 'purchase_order_field',
            'placeholder': 'Purchase Order Number...'
        }),
        label='Purchase Order'
    )

    class Meta:
        model = Sale
        fields = [
            'store', 'customer', 'document_type', 'payment_method',
            'currency', 'discount_amount', 'notes', 'due_date'
        ]
        widgets = {
            'store': forms.Select(attrs={'class': 'form-select', 'required': True}),
            'customer': forms.HiddenInput(),
            'document_type': forms.Select(attrs={
                'class': 'form-select',
                'id': 'document_type_select',
                'onchange': 'updateFormFields()'
            }),
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
            }),
            'due_date': forms.HiddenInput()  # Will be shown conditionally
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
            self.fields['document_type'].initial = 'RECEIPT'

            # Set payment method based on document type
            doc_type = self.data.get('document_type', 'RECEIPT') if self.data else 'RECEIPT'
            if doc_type == 'RECEIPT':
                self.fields['payment_method'].initial = 'CASH'
            elif doc_type == 'INVOICE':
                self.fields['payment_method'].initial = 'CREDIT'
            else:
                self.fields['payment_method'].initial = 'CASH'

        # Set initial values for invoice-specific fields
        if self.instance.pk and self.instance.is_invoice:
            invoice_detail = getattr(self.instance, 'invoice_detail', None)
            if invoice_detail:
                self.fields['terms'].initial = invoice_detail.terms
                self.fields['purchase_order'].initial = invoice_detail.purchase_order

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

    def clean_due_date(self):
        """Validate due date for invoices"""
        due_date = self.cleaned_data.get('due_date')
        document_type = self.cleaned_data.get('document_type')

        if document_type == 'INVOICE' and not due_date:
            raise ValidationError("Due date is required for invoices.")

        return due_date

    def clean_payment_method(self):
        """Validate payment method based on document type"""
        payment_method = self.cleaned_data.get('payment_method')
        document_type = self.cleaned_data.get('document_type')

        # Receipts cannot be credit sales
        if document_type == 'RECEIPT' and payment_method == 'CREDIT':
            raise ValidationError("Receipts must have immediate payment (not credit).")

        # Proforma/Estimate can be any payment method
        return payment_method

    def save(self, commit=True):
        """Save sale with document type specific handling"""
        sale = super().save(commit=False)

        if commit:
            sale.save()

            # Create invoice detail if it's an invoice
            if sale.document_type == 'INVOICE':
                from invoices.models import Invoice
                invoice_data = {
                    'sale': sale,
                    'terms': self.cleaned_data.get('terms', ''),
                    'purchase_order': self.cleaned_data.get('purchase_order', ''),
                }

                # Update existing or create new invoice detail
                if hasattr(sale, 'invoice_detail'):
                    for field, value in invoice_data.items():
                        setattr(sale.invoice_detail, field, value)
                    sale.invoice_detail.save()
                else:
                    Invoice.objects.create(**invoice_data)

        return sale


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
        self.sale = kwargs.pop('sale', None)  # NEW: Get sale context
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

        # Check stock availability if store is provided and not proforma/estimate
        if (product and self.store and quantity and self.sale and
                self.sale.document_type in ['RECEIPT', 'INVOICE']):
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

    # ==================== NEW: Payment Type Field ====================
    payment_type = forms.ChoiceField(
        choices=Payment.PAYMENT_TYPE_CHOICES,
        initial='FULL',
        widget=forms.Select(attrs={
            'class': 'form-select payment-type-select'
        })
    )

    class Meta:
        model = Payment
        fields = [
            'amount', 'payment_method', 'transaction_reference',
            'payment_type', 'notes'
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
    """Enhanced Cart form with document type selection"""

    customer_search = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Search customer...',
            'data-toggle': 'customer-search'
        })
    )

    # ==================== NEW: Document Type for Cart ====================
    due_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={
            'class': 'form-control',
            'type': 'date',
            'id': 'cart_due_date'
        }),
        label='Due Date'
    )

    terms = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 2,
            'id': 'cart_terms',
            'placeholder': 'Payment terms...'
        }),
        label='Terms'
    )

    purchase_order = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'id': 'cart_purchase_order',
            'placeholder': 'Purchase Order Number...'
        }),
        label='Purchase Order'
    )

    class Meta:
        model = Cart
        fields = ['customer', 'document_type', 'notes', 'due_date', 'terms', 'purchase_order']
        widgets = {
            'customer': forms.HiddenInput(),
            'document_type': forms.Select(attrs={
                'class': 'form-select',
                'id': 'cart_document_type',
                'onchange': 'updateCartFields()'
            }),
            'notes': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 2,
                'placeholder': 'Cart notes...'
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Set default document type
        if not self.instance.pk:
            self.fields['document_type'].initial = 'RECEIPT'


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
    """Quick sale form for fast transactions - UPDATED"""

    products_data = forms.CharField(widget=forms.HiddenInput())
    customer = forms.ModelChoiceField(
        queryset=Customer.objects.all(),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'})
    )

    # ==================== NEW: Document Type ====================
    document_type = forms.ChoiceField(
        choices=Sale.DOCUMENT_TYPE_CHOICES,
        initial='RECEIPT',
        widget=forms.Select(attrs={'class': 'form-select'})
    )

    payment_method = forms.ChoiceField(
        choices=Sale.PAYMENT_METHODS,
        widget=forms.Select(attrs={'class': 'form-select'})
    )

    # ==================== NEW: Conditional Fields ====================
    due_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={
            'class': 'form-control',
            'type': 'date'
        })
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

    def clean_due_date(self):
        """Validate due date for invoices"""
        due_date = self.cleaned_data.get('due_date')
        document_type = self.cleaned_data.get('document_type')

        if document_type == 'INVOICE' and not due_date:
            raise ValidationError("Due date is required for invoices.")

        return due_date

    def clean_payment_method(self):
        """Validate payment method based on document type"""
        payment_method = self.cleaned_data.get('payment_method')
        document_type = self.cleaned_data.get('document_type')

        if document_type == 'RECEIPT' and payment_method == 'CREDIT':
            raise ValidationError("Receipts must have immediate payment (not credit).")

        return payment_method


class SaleSearchForm(forms.Form):
    """Advanced search form for sales - UPDATED"""

    search = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Search by document number, customer, or transaction ID...'
        })
    )

    store = forms.ModelChoiceField(
        queryset=Store.objects.all(),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'})
    )

    # ==================== UPDATED: Document Type Filter ====================
    document_type = forms.ChoiceField(
        choices=[('', 'All Types')] + Sale.DOCUMENT_TYPE_CHOICES,
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'})
    )

    payment_method = forms.ChoiceField(
        choices=[('', 'All Methods')] + Sale.PAYMENT_METHODS,
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'})
    )

    # ==================== NEW: Payment Status Filter ====================
    payment_status = forms.ChoiceField(
        choices=[('', 'All Statuses')] + Sale.PAYMENT_STATUS_CHOICES,
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
    """Form for bulk actions on sales - UPDATED"""

    ACTION_CHOICES = [
        ('fiscalize', 'Fiscalize Selected'),
        ('print_receipts', 'Print Receipts'),
        ('export_csv', 'Export to CSV'),
        ('export_excel', 'Export to Excel'),
        ('convert_to_invoice', 'Convert to Invoice'),
        ('send_invoices', 'Send Invoices'),
    ]

    action = forms.ChoiceField(
        choices=ACTION_CHOICES,
        widget=forms.Select(attrs={'class': 'form-select'})
    )

    selected_sales = forms.CharField(
        widget=forms.HiddenInput()
    )

    # ==================== NEW: For invoice conversion ====================
    due_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={
            'class': 'form-control',
            'type': 'date',
            'id': 'bulk_due_date'
        })
    )

    terms = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 2,
            'id': 'bulk_terms',
            'placeholder': 'Payment terms...'
        })
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


# ==================== UPDATED: FormSets with Sale context ====================
class SaleItemFormSet(forms.BaseInlineFormSet):
    def __init__(self, *args, **kwargs):
        self.sale = kwargs.pop('sale', None)
        super().__init__(*args, **kwargs)

    def _construct_form(self, i, **kwargs):
        kwargs['sale'] = self.sale
        return super()._construct_form(i, **kwargs)


def get_sale_item_formset(sale=None):
    """Factory function to create SaleItemFormSet with sale context"""
    return forms.inlineformset_factory(
        Sale,
        SaleItem,
        form=SaleItemForm,
        formset=SaleItemFormSet,
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


# ==================== NEW: Document Type Selection Form ====================
class DocumentTypeForm(forms.Form):
    """Form for selecting document type at sale creation"""

    DOCUMENT_TYPE_CHOICES = [
        ('RECEIPT', '🧾 Receipt (Immediate Payment)'),
        ('INVOICE', '📄 Invoice (Credit Sale)'),
        ('PROFORMA', '📑 Proforma (Quotation)'),
        ('ESTIMATE', '📋 Estimate'),
    ]

    document_type = forms.ChoiceField(
        choices=DOCUMENT_TYPE_CHOICES,
        widget=forms.RadioSelect(attrs={
            'class': 'form-check-input',
            'onchange': 'documentTypeChanged(this.value)'
        }),
        initial='RECEIPT',
        label='Select Document Type'
    )

    customer = forms.ModelChoiceField(
        queryset=Customer.objects.all(),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'}),
        label='Customer (Optional)'
    )

    store = forms.ModelChoiceField(
        queryset=Store.objects.filter(is_active=True),
        widget=forms.Select(attrs={'class': 'form-select'}),
        label='Store'
    )