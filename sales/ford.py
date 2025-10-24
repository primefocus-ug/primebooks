# forms.py
from django import forms
from django.core.exceptions import ValidationError
from django.db import transaction
from decimal import Decimal
from .models import Sale, SaleItem
from inventory.models import Product
from customers.models import Customer
from stores.models import Store
import json


class AdvancedSaleForm(forms.ModelForm):
    """
    Advanced sale form with enhanced validation and features
    beyond basic Django admin capabilities
    """

    # Additional fields not directly in the model
    items_data = forms.CharField(
        widget=forms.HiddenInput(),
        required=False,
        help_text="JSON data containing sale items"
    )

    payment_amount = forms.DecimalField(
        max_digits=12,
        decimal_places=2,
        required=False,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'step': '0.01',
            'min': '0',
            'placeholder': '0.00'
        }),
        help_text="Amount paid by customer"
    )

    payment_reference = forms.CharField(
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Transaction reference (optional)'
        }),
        help_text="Payment reference number"
    )

    is_draft = forms.BooleanField(
        required=False,
        widget=forms.HiddenInput()
    )

    # Custom customer creation fields
    create_customer = forms.BooleanField(
        required=False,
        widget=forms.HiddenInput()
    )

    customer_name = forms.CharField(
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Customer name'
        })
    )

    customer_phone = forms.CharField(
        max_length=20,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Phone number'
        })
    )

    customer_email = forms.EmailField(
        required=False,
        widget=forms.EmailInput(attrs={
            'class': 'form-control',
            'placeholder': 'Email address'
        })
    )

    customer_address = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 2,
            'placeholder': 'Customer address'
        })
    )

    class Meta:
        model = Sale
        fields = [
            'store', 'customer', 'transaction_type', 'document_type',
            'payment_method', 'currency', 'discount_amount', 'notes'
        ]

        widgets = {
            'store': forms.Select(attrs={
                'class': 'form-select',
                'required': True
            }),
            'customer': forms.Select(attrs={
                'class': 'form-select'
            }),
            'transaction_type': forms.Select(attrs={
                'class': 'form-select',
                'required': True
            }),
            'document_type': forms.Select(attrs={
                'class': 'form-select',
                'required': True
            }),
            'payment_method': forms.Select(attrs={
                'class': 'form-select',
                'required': True
            }),
            'currency': forms.Select(attrs={
                'class': 'form-select'
            }),
            'discount_amount': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'min': '0',
                'value': '0'
            }),
            'notes': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Add any additional notes...'
            })
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        self.store_id = kwargs.pop('store_id', None)
        super().__init__(*args, **kwargs)

        # Filter stores based on user permissions
        if self.user:
            if hasattr(self.user, 'stores'):
                self.fields['store'].queryset = self.user.stores.all()
            else:
                self.fields['store'].queryset = Store.objects.filter(
                    is_active=True
                )

        # Pre-select store if provided
        if self.store_id:
            self.fields['store'].initial = self.store_id

        # Filter customers to active ones only
        self.fields['customer'].queryset = Customer.objects.filter(
            is_active=True
        ).order_by('name')

        # Add empty option for customer (optional field)
        self.fields['customer'].empty_label = "Walk-in Customer"

        # Enhance field labels and help texts
        self._enhance_field_properties()

    def _enhance_field_properties(self):
        """Add enhanced labels and help texts"""
        field_enhancements = {
            'store': {
                'label': 'Store *',
                'help_text': 'Select the store where this sale is taking place'
            },
            'customer': {
                'label': 'Customer',
                'help_text': 'Optional - Select existing customer or leave blank for walk-in'
            },
            'transaction_type': {
                'label': 'Transaction Type *',
                'help_text': 'Type of transaction being processed'
            },
            'document_type': {
                'label': 'Document Type *',
                'help_text': 'Type of document to generate'
            },
            'payment_method': {
                'label': 'Payment Method *',
                'help_text': 'How the customer is paying'
            },
            'currency': {
                'label': 'Currency',
                'help_text': 'Transaction currency'
            },
            'discount_amount': {
                'label': 'Additional Discount',
                'help_text': 'Extra discount amount (beyond item discounts)'
            },
            'notes': {
                'label': 'Notes',
                'help_text': 'Any additional information about this sale'
            }
        }

        for field_name, properties in field_enhancements.items():
            if field_name in self.fields:
                for prop_name, prop_value in properties.items():
                    setattr(self.fields[field_name], prop_name, prop_value)

    def clean_items_data(self):
        """Validate and parse items JSON data"""
        items_data = self.cleaned_data.get('items_data', '')

        if not items_data:
            if not self.cleaned_data.get('is_draft'):
                raise ValidationError("At least one item is required for a sale")
            return []

        try:
            items = json.loads(items_data)
        except (json.JSONDecodeError, TypeError):
            raise ValidationError("Invalid items data format")

        if not isinstance(items, list):
            raise ValidationError("Items data must be a list")

        if not items and not self.cleaned_data.get('is_draft'):
            raise ValidationError("At least one item is required for a sale")

        # Validate each item
        validated_items = []
        for i, item in enumerate(items):
            try:
                validated_item = self._validate_sale_item(item, i)
                validated_items.append(validated_item)
            except ValidationError as e:
                raise ValidationError(f"Item {i + 1}: {e.message}")

        return validated_items

    def _validate_sale_item(self, item, index):
        """Validate individual sale item"""
        required_fields = ['product_id', 'quantity', 'unit_price']

        # Check required fields
        for field in required_fields:
            if field not in item or item[field] is None:
                raise ValidationError(f"Missing required field: {field}")

        # Validate product exists and is active
        try:
            product = Product.objects.get(
                id=item['product_id'],
                is_active=True
            )
        except Product.DoesNotExist:
            raise ValidationError(f"Product with ID {item['product_id']} not found or inactive")

        # Validate numeric fields
        try:
            quantity = Decimal(str(item['quantity']))
            unit_price = Decimal(str(item['unit_price']))
            discount = Decimal(str(item.get('discount', 0)))
        except (ValueError, TypeError):
            raise ValidationError("Invalid numeric values in item data")

        # Business logic validations
        if quantity <= 0:
            raise ValidationError("Quantity must be greater than 0")

        if unit_price < 0:
            raise ValidationError("Unit price cannot be negative")

        if discount < 0:
            raise ValidationError("Discount cannot be negative")

        # Stock validation (if applicable)
        if hasattr(product, 'track_inventory') and product.track_inventory:
            # Get current stock for the store
            store_id = self.cleaned_data.get('store')
            if store_id:
                # This would typically involve checking inventory levels
                # Implementation depends on your inventory management system
                pass

        # Tax rate validation
        tax_rate = item.get('tax_rate', 'A')
        valid_tax_rates = ['A', 'B', 'C', 'D', 'E']
        if tax_rate not in valid_tax_rates:
            raise ValidationError(f"Invalid tax rate: {tax_rate}")

        return {
            'product': product,
            'quantity': quantity,
            'unit_price': unit_price,
            'tax_rate': tax_rate,
            'discount': discount,
            'name': item.get('name', product.name)
        }

    def clean_payment_amount(self):
        """Validate payment amount"""
        payment_amount = self.cleaned_data.get('payment_amount')
        payment_method = self.cleaned_data.get('payment_method')
        is_draft = self.cleaned_data.get('is_draft', False)

        # Payment amount is required for non-draft sales
        if not is_draft and payment_method != 'CREDIT':
            if payment_amount is None or payment_amount < 0:
                raise ValidationError("Valid payment amount is required")

        return payment_amount

    def clean(self):
        """Cross-field validation"""
        cleaned_data = super().clean()

        # Create customer if needed
        if cleaned_data.get('create_customer'):
            customer = self._create_customer(cleaned_data)
            if customer:
                cleaned_data['customer'] = customer

        # Validate payment method specific requirements
        self._validate_payment_method(cleaned_data)

        # Calculate and validate totals
        self._validate_totals(cleaned_data)

        return cleaned_data

    def _create_customer(self, cleaned_data):
        """Create new customer if requested"""
        customer_name = cleaned_data.get('customer_name')
        customer_phone = cleaned_data.get('customer_phone')

        if not customer_name or not customer_phone:
            raise ValidationError("Customer name and phone are required to create new customer")

        # Check if customer with same phone already exists
        existing_customer = Customer.objects.filter(phone=customer_phone).first()
        if existing_customer:
            return existing_customer

        # Create new customer
        try:
            customer = Customer.objects.create(
                name=customer_name,
                phone=customer_phone,
                email=cleaned_data.get('customer_email', ''),
                address=cleaned_data.get('customer_address', ''),
                created_by=self.user
            )
            return customer
        except Exception as e:
            raise ValidationError(f"Failed to create customer: {str(e)}")

    def _validate_payment_method(self, cleaned_data):
        """Validate payment method specific requirements"""
        payment_method = cleaned_data.get('payment_method')
        payment_reference = cleaned_data.get('payment_reference')

        # Require reference for certain payment methods
        if payment_method in ['MOBILE_MONEY', 'BANK_TRANSFER'] and not payment_reference:
            if not cleaned_data.get('is_draft'):
                raise ValidationError({
                    'payment_reference': f'{payment_method.replace("_", " ").title()} requires a payment reference'
                })

    def _validate_totals(self, cleaned_data):
        """Validate calculated totals make sense"""
        items = cleaned_data.get('items_data', [])
        discount_amount = cleaned_data.get('discount_amount', Decimal('0'))
        payment_amount = cleaned_data.get('payment_amount')
        is_draft = cleaned_data.get('is_draft', False)

        if not items:
            return

        # Calculate expected total
        subtotal = sum(item['quantity'] * item['unit_price'] for item in items)
        total_tax = sum(self._calculate_tax(item) for item in items)
        item_discounts = sum(item.get('discount', Decimal('0')) for item in items)

        expected_total = subtotal + total_tax - item_discounts - discount_amount

        # Validate payment amount against total (for non-draft, non-credit sales)
        if not is_draft and cleaned_data.get('payment_method') != 'CREDIT':
            if payment_amount is not None and payment_amount < expected_total:
                shortfall = expected_total - payment_amount
                raise ValidationError({
                    'payment_amount': f'Payment amount is {shortfall} short of total amount'
                })

    def _calculate_tax(self, item):
        """Calculate tax for an item"""
        tax_rate = item.get('tax_rate', 'C')
        amount = item['quantity'] * item['unit_price'] - item.get('discount', Decimal('0'))

        if tax_rate == 'A':  # Standard rate
            return amount * Decimal('0.18')
        elif tax_rate == 'B':  # Reduced rate
            return amount * Decimal('0.12')
        elif tax_rate == 'D':  # Deemed rate
            return amount * Decimal('0.18')
        elif tax_rate == 'E':  # Excise duty
            # This would need product-specific excise rates
            product = item.get('product')
            if product and hasattr(product, 'excise_duty_rate'):
                return amount * (product.excise_duty_rate / Decimal('100'))

        return Decimal('0')  # Tax rates B and C

    def save(self, commit=True):
        """Enhanced save method with transaction handling"""
        sale = super().save(commit=False)

        # Set created_by if user is provided
        if self.user:
            sale.created_by = self.user

        # Set completion status based on draft flag
        is_draft = self.cleaned_data.get('is_draft', False)
        sale.is_completed = not is_draft

        if commit:
            with transaction.atomic():
                # Save the sale
                sale.save()

                # Create sale items
                items_data = self.cleaned_data.get('items_data', [])
                for item_data in items_data:
                    self._create_sale_item(sale, item_data)

                # Update totals
                sale.update_totals()

                # Handle payment information
                self._handle_payment(sale)

        return sale

    def _create_sale_item(self, sale, item_data):
        """Create individual sale item"""
        sale_item = SaleItem(
            store=sale.store,
            sale=sale,
            product=item_data['product'],
            quantity=item_data['quantity'],
            unit_price=item_data['unit_price'],
            tax_rate=item_data['tax_rate'],
            discount=item_data.get('discount', Decimal('0')),
            description=item_data.get('description', '')
        )
        sale_item.save()
        return sale_item

    def _handle_payment(self, sale):
        """Handle payment information"""
        payment_amount = self.cleaned_data.get('payment_amount')
        payment_reference = self.cleaned_data.get('payment_reference')

        # Store payment information (you might have a separate Payment model)
        # For now, we'll store it in the sale notes if not already present
        payment_info = []

        if payment_amount:
            payment_info.append(f"Payment: {payment_amount} {sale.currency}")

        if payment_reference:
            payment_info.append(f"Reference: {payment_reference}")

        if payment_info:
            payment_text = " | ".join(payment_info)
            if sale.notes:
                sale.notes += f"\n{payment_text}"
            else:
                sale.notes = payment_text
            sale.save(update_fields=['notes'])


class SalesItemForm(forms.ModelForm):
    """Advanced form for individual sale items"""

    class Meta:
        model = SaleItem
        fields = [
            'product', 'quantity', 'unit_price', 'tax_rate',
            'discount', 'description'
        ]
        widgets = {
            'product': forms.Select(attrs={
                'class': 'form-select',
                'required': True
            }),
            'quantity': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.001',
                'min': '0.001'
            }),
            'unit_price': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'min': '0'
            }),
            'tax_rate': forms.Select(attrs={
                'class': 'form-select'
            }),
            'discount': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'min': '0',
                'value': '0'
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 2
            })
        }

    def __init__(self, *args, **kwargs):
        store = kwargs.pop('store', None)
        super().__init__(*args, **kwargs)

        if store:
            # Filter products by store availability
            self.fields['product'].queryset = Product.objects.filter(
                is_active=True,
                stores=store
            ).order_by('name')


class QuickSaleForm(forms.Form):
    """Simplified form for quick sales (POS style)"""

    store = forms.ModelChoiceField(
        queryset=Store.objects.filter(is_active=True),
        widget=forms.Select(attrs={'class': 'form-select'})
    )

    customer = forms.ModelChoiceField(
        queryset=Customer.objects.filter(is_active=True),
        required=False,
        empty_label="Walk-in Customer",
        widget=forms.Select(attrs={'class': 'form-select'})
    )

    payment_method = forms.ChoiceField(
        choices=Sale.PAYMENT_METHODS,
        widget=forms.Select(attrs={'class': 'form-select'})
    )

    items_json = forms.CharField(
        widget=forms.HiddenInput()
    )

    payment_amount = forms.DecimalField(
        max_digits=12,
        decimal_places=2,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'step': '0.01'
        })
    )

    def clean_items_json(self):
        items_json = self.cleaned_data['items_json']
        try:
            items = json.loads(items_json)
            if not items:
                raise ValidationError("At least one item is required")
            return items
        except json.JSONDecodeError:
            raise ValidationError("Invalid items data")


# Formset for handling multiple sale items
SaleItemFormSet = forms.inlineformset_factory(
    Sale,
    SaleItem,
    form=SalesItemForm,
    fields=['product', 'quantity', 'unit_price', 'tax_rate', 'discount'],
    extra=1,
    can_delete=True,
    min_num=1,
    validate_min=True
)