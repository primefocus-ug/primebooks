from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.db.models import Q
from decimal import Decimal
import json

from .models import Invoice, InvoicePayment, InvoiceTemplate
from sales.models import Sale


class InvoiceForm(forms.ModelForm):
    """Enhanced invoice creation/edit form"""

    class Meta:
        model = Invoice
        fields = [
            'sale', 'terms', 'purchase_order', 'efris_document_type',
            'business_type', 'auto_fiscalize'
        ]
        widgets = {
            'sale': forms.Select(attrs={
                'class': 'form-select',
                'required': True
            }),
            'terms': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Payment terms and conditions...'
            }),
            'purchase_order': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'PO Number (optional)'
            }),
            'efris_document_type': forms.Select(attrs={
                'class': 'form-select'
            }),
            'business_type': forms.Select(attrs={
                'class': 'form-select'
            }),
            'auto_fiscalize': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        # Filter sales to only show invoiceable sales
        if self.user:
            # Get company from user
            user_company = getattr(self.user, 'company', None)

            if user_company:
                # Filter sales that don't have invoice details yet
                self.fields['sale'].queryset = Sale.objects.filter(
                    store__company=user_company,
                    document_type='INVOICE',
                    status__in=['COMPLETED', 'PAID', 'PARTIALLY_PAID']
                ).exclude(
                    invoice_detail__isnull=False
                ).select_related('customer', 'store')
            else:
                self.fields['sale'].queryset = Sale.objects.none()

        # Set field help texts
        self.fields['terms'].help_text = 'Payment terms, delivery conditions, etc.'
        self.fields['efris_document_type'].help_text = 'Select document type for EFRIS'
        self.fields['business_type'].help_text = 'Transaction type for EFRIS'

    def clean_sale(self):
        """Validate sale can have an invoice"""
        sale = self.cleaned_data.get('sale')

        if not sale:
            raise ValidationError("Sale is required.")

        # Check if sale already has an invoice detail
        if hasattr(sale, 'invoice_detail') and sale.invoice_detail:
            if not self.instance.pk or self.instance.pk != sale.invoice_detail.pk:
                raise ValidationError("This sale already has an invoice detail.")

        # Check if sale is in correct status
        if sale.status not in ['COMPLETED', 'PAID', 'PARTIALLY_PAID']:
            raise ValidationError("Only completed or paid sales can have invoices.")

        # Check if sale document type is INVOICE
        if sale.document_type != 'INVOICE':
            raise ValidationError("Only invoice-type sales can have invoice details.")

        return sale

    def clean(self):
        """Additional validation"""
        cleaned_data = super().clean()

        efris_document_type = cleaned_data.get('efris_document_type')

        # Validate credit/debit notes
        if efris_document_type in ['2', '3']:
            # These require original FDN
            if not self.instance.pk:
                raise ValidationError(
                    "Credit/Debit notes must be created from existing invoices."
                )

        return cleaned_data


class InvoicePaymentForm(forms.ModelForm):
    """Payment form for invoices"""

    class Meta:
        model = InvoicePayment
        fields = [
            'amount', 'payment_method', 'transaction_reference',
            'payment_date', 'notes'
        ]
        widgets = {
            'amount': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '0.01',
                'step': '0.01',
                'required': True
            }),
            'payment_method': forms.Select(attrs={
                'class': 'form-select',
                'required': True
            }),
            'transaction_reference': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Transaction reference (optional)'
            }),
            'payment_date': forms.DateInput(attrs={
                'class': 'form-control',
                'type': 'date'
            }),
            'notes': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 2,
                'placeholder': 'Payment notes...'
            }),
        }

    def __init__(self, *args, **kwargs):
        self.invoice = kwargs.pop('invoice', None)
        super().__init__(*args, **kwargs)

        # Set initial payment date to today
        if not self.instance.pk:
            self.fields['payment_date'].initial = timezone.now().date()

        # Set max amount to outstanding amount
        if self.invoice:
            outstanding = self.invoice.amount_outstanding
            self.fields['amount'].widget.attrs['max'] = str(outstanding)
            self.fields['amount'].help_text = (
                f'Outstanding amount: {outstanding:,.2f} '
                f'{self.invoice.currency_code}'
            )

    def clean_amount(self):
        """Validate payment amount"""
        amount = self.cleaned_data.get('amount')

        if amount <= 0:
            raise ValidationError("Payment amount must be greater than 0.")

        if self.invoice:
            outstanding = self.invoice.amount_outstanding

            # Allow for existing payment updates
            if self.instance.pk:
                current_payment = InvoicePayment.objects.filter(
                    pk=self.instance.pk
                ).first()
                if current_payment:
                    outstanding += current_payment.amount

            if amount > outstanding:
                raise ValidationError(
                    f"Payment amount cannot exceed outstanding amount "
                    f"({outstanding:,.2f})."
                )

        return amount


class InvoiceSearchForm(forms.Form):
    """Advanced search form for invoices"""

    search = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Search by invoice number, customer...'
        })
    )

    status = forms.MultipleChoiceField(
        required=False,
        choices=Sale.STATUS_CHOICES,
        widget=forms.SelectMultiple(attrs={
            'class': 'form-select'
        })
    )

    document_type = forms.ChoiceField(
        required=False,
        choices=[('', 'All Types')] + Sale.DOCUMENT_TYPE_CHOICES,
        widget=forms.Select(attrs={
            'class': 'form-select'
        })
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

    amount_min = forms.DecimalField(
        required=False,
        min_value=0,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': 'Min amount'
        })
    )

    amount_max = forms.DecimalField(
        required=False,
        min_value=0,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': 'Max amount'
        })
    )

    is_overdue = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(attrs={
            'class': 'form-check-input'
        }),
        label='Show overdue only'
    )

    is_fiscalized = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(attrs={
            'class': 'form-check-input'
        }),
        label='Show fiscalized only'
    )


class FiscalizationForm(forms.Form):
    """Form for EFRIS fiscalization"""

    confirm = forms.BooleanField(
        required=True,
        widget=forms.CheckboxInput(attrs={
            'class': 'form-check-input'
        }),
        label='I confirm this invoice is ready for fiscalization'
    )

    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 2,
            'placeholder': 'Fiscalization notes (optional)...'
        })
    )

    def __init__(self, *args, **kwargs):
        self.invoice = kwargs.pop('invoice', None)
        super().__init__(*args, **kwargs)

        if self.invoice:
            # Add validation messages
            can_fiscalize, message = self.invoice.can_fiscalize()

            if not can_fiscalize:
                self.fields['confirm'].help_text = f'⚠️ {message}'
                self.fields['confirm'].disabled = True

    def clean_confirm(self):
        """Validate fiscalization confirmation"""
        confirm = self.cleaned_data.get('confirm')

        if not confirm:
            raise ValidationError("You must confirm before fiscalization.")

        if self.invoice:
            can_fiscalize, message = self.invoice.can_fiscalize()
            if not can_fiscalize:
                raise ValidationError(message)

        return confirm


class BulkInvoiceActionForm(forms.Form):
    """Form for bulk actions on invoices"""

    ACTION_CHOICES = [
        ('mark_sent', 'Mark as Sent'),
        ('mark_paid', 'Mark as Paid'),
        ('fiscalize', 'Fiscalize with EFRIS'),
        ('export_pdf', 'Export to PDF'),
        ('export_csv', 'Export to CSV'),
        ('send_email', 'Send Email Reminders'),
    ]

    action = forms.ChoiceField(
        choices=ACTION_CHOICES,
        widget=forms.Select(attrs={
            'class': 'form-select'
        })
    )

    selected_invoices = forms.CharField(
        widget=forms.HiddenInput()
    )

    def clean_selected_invoices(self):
        """Validate selected invoices"""
        data = self.cleaned_data.get('selected_invoices')

        try:
            invoice_ids = json.loads(data)
            if not invoice_ids:
                raise ValidationError("No invoices selected.")
            return invoice_ids
        except (json.JSONDecodeError, ValueError):
            raise ValidationError("Invalid invoice selection data.")


class InvoiceTemplateForm(forms.ModelForm):
    """Form for invoice templates"""

    class Meta:
        model = InvoiceTemplate
        fields = [
            'name', 'template_file', 'is_default',
            'is_efris_compliant', 'version'
        ]
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Template name'
            }),
            'template_file': forms.FileInput(attrs={
                'class': 'form-control'
            }),
            'is_default': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
            'is_efris_compliant': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
            'version': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': '1.0'
            }),
        }

    def clean_is_default(self):
        """Ensure only one default template"""
        is_default = self.cleaned_data.get('is_default')

        if is_default:
            # Check if another default exists
            existing_default = InvoiceTemplate.objects.filter(
                is_default=True
            ).exclude(pk=self.instance.pk if self.instance else None)

            if existing_default.exists():
                raise ValidationError(
                    "Another default template already exists. "
                    "Please unset it first."
                )

        return is_default


class CreditNoteForm(forms.ModelForm):
    """Form for creating credit notes"""

    original_invoice = forms.ModelChoiceField(
        queryset=Invoice.objects.filter(is_fiscalized=True),
        widget=forms.Select(attrs={
            'class': 'form-select'
        }),
        label='Original Invoice'
    )

    reason = forms.CharField(
        required=True,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 3,
            'placeholder': 'Reason for credit note...'
        }),
        label='Reason for Credit Note'
    )

    class Meta:
        model = Invoice
        fields = ['sale', 'terms', 'business_type']
        widgets = {
            'sale': forms.HiddenInput(),
            'terms': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 2
            }),
            'business_type': forms.Select(attrs={
                'class': 'form-select'
            }),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        # Filter original invoices
        if self.user:
            user_company = getattr(self.user, 'company', None)
            if user_company:
                self.fields['original_invoice'].queryset = Invoice.objects.filter(
                    sale__store__company=user_company,
                    is_fiscalized=True,
                    efris_document_type='1'  # Normal invoices only
                ).select_related('sale', 'sale__customer')

    def clean(self):
        """Validate credit note creation"""
        cleaned_data = super().clean()
        original_invoice = cleaned_data.get('original_invoice')

        if original_invoice:
            # Set the EFRIS document type for credit note
            cleaned_data['efris_document_type'] = '2'

            # Copy business type from original
            if not cleaned_data.get('business_type'):
                cleaned_data['business_type'] = original_invoice.business_type

        return cleaned_data

    def save(self, commit=True):
        """Create credit note invoice"""
        invoice = super().save(commit=False)

        original_invoice = self.cleaned_data.get('original_invoice')
        if original_invoice:
            invoice.efris_document_type = '2'  # Credit note
            invoice.original_fdn = original_invoice.fiscal_document_number
            invoice.business_type = original_invoice.business_type

            # Check if URA approval is required
            if invoice.business_type in ['B2B', 'B2G']:
                invoice.requires_ura_approval = True

        if self.user:
            invoice.created_by = self.user

        if commit:
            invoice.save()

        return invoice