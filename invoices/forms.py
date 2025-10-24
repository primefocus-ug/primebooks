from django import forms
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from django.utils import timezone
from django.db.models import Q
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Submit, Row, Column, Div, HTML
from crispy_forms.bootstrap import Field, InlineRadios, PrependedText
import json
from efris.models import FiscalizationAudit
from .models import Invoice, InvoiceTemplate, InvoicePayment
from sales.models import Sale
from stores.models import Store


class InvoiceForm(forms.ModelForm):
    """Advanced invoice creation and editing form with dynamic features"""
    
    class Meta:
        model = Invoice
        fields = [
            'sale', 'store', 'invoice_number', 'issue_date', 'due_date',
            'status', 'document_type', 'subtotal', 'tax_amount', 
            'discount_amount', 'total_amount', 'notes', 'terms'
        ]
        widgets = {
            'issue_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'due_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'notes': forms.Textarea(attrs={'rows': 3, 'class': 'form-control'}),
            'terms': forms.Textarea(attrs={'rows': 3, 'class': 'form-control'}),
            'subtotal': forms.NumberInput(attrs={'step': '0.01', 'class': 'form-control'}),
            'tax_amount': forms.NumberInput(attrs={'step': '0.01', 'class': 'form-control'}),
            'discount_amount': forms.NumberInput(attrs={'step': '0.01', 'class': 'form-control'}),
            'total_amount': forms.NumberInput(attrs={'step': '0.01', 'class': 'form-control', 'readonly': True}),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        
        # Dynamic queryset filtering based on user permissions
        if self.user:
            self.fields['store'].queryset = Store.objects.filter(
                Q(staff=self.user)
            ).distinct()
            
        # Auto-populate fields from sale if creating new invoice
        if not self.instance.pk and 'sale' in self.initial:
            try:
                sale = Sale.objects.get(pk=self.initial['sale'])
                self.fields['subtotal'].initial = sale.subtotal
                self.fields['tax_amount'].initial = sale.tax_amount
                self.fields['discount_amount'].initial = sale.discount_amount
                self.fields['total_amount'].initial = sale.total_amount
            except Sale.DoesNotExist:
                pass

        self.helper = FormHelper()
        self.helper.layout = Layout(
            Row(
                Column('document_type', css_class='col-md-4'),
                Column('status', css_class='col-md-4'),
                Column('invoice_number', css_class='col-md-4'),
            ),
            Row(
                Column('sale', css_class='col-md-6'),
                Column('store', css_class='col-md-6'),
            ),
            Row(
                Column('issue_date', css_class='col-md-6'),
                Column('due_date', css_class='col-md-6'),
            ),
            HTML('<hr><h5>Financial Details</h5>'),
            Row(
                Column(PrependedText('subtotal', 'UGX'), css_class='col-md-3'),
                Column(PrependedText('tax_amount', 'UGX'), css_class='col-md-3'),
                Column(PrependedText('discount_amount', 'UGX'), css_class='col-md-3'),
                Column(PrependedText('total_amount', 'UGX'), css_class='col-md-3'),
            ),
            HTML('<hr><h5>Additional Information</h5>'),
            Row(
                Column('notes', css_class='col-md-6'),
                Column('terms', css_class='col-md-6'),
            ),
            Div(
                Submit('submit', 'Save Invoice', css_class='btn btn-primary me-2'),
                HTML('<a href="{% url "invoices:list" %}" class="btn btn-secondary">Cancel</a>'),
                css_class='d-flex justify-content-end mt-3'
            )
        )

    def clean(self):
        cleaned_data = super().clean()
        subtotal = cleaned_data.get('subtotal', 0)
        tax_amount = cleaned_data.get('tax_amount', 0)
        discount_amount = cleaned_data.get('discount_amount', 0)
        
        # Auto-calculate total if not provided
        if subtotal and tax_amount is not None and discount_amount is not None:
            calculated_total = subtotal + tax_amount - discount_amount
            cleaned_data['total_amount'] = max(0, calculated_total)
            
        return cleaned_data


class InvoiceSearchForm(forms.Form):
    """Advanced search form for invoices with multiple filters"""
    
    search = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'placeholder': 'Search by invoice number, customer, etc.',
            'class': 'form-control'
        })
    )
    
    status = forms.MultipleChoiceField(
        choices=Invoice.STATUS_CHOICES,
        required=False,
        widget=forms.CheckboxSelectMultiple(attrs={'class': 'form-check-input'})
    )
    
    document_type = forms.ChoiceField(
        choices=[('', 'All Types')] + Invoice.DOCUMENT_TYPES,
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    
    date_from = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'})
    )
    
    date_to = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'})
    )
    
    amount_min = forms.DecimalField(
        required=False,
        widget=forms.NumberInput(attrs={'step': '0.01', 'class': 'form-control'})
    )
    
    amount_max = forms.DecimalField(
        required=False,
        widget=forms.NumberInput(attrs={'step': '0.01', 'class': 'form-control'})
    )
    
    is_overdue = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )
    
    is_fiscalized = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_method = 'GET'
        self.helper.layout = Layout(
            Row(
                Column('search', css_class='col-md-6'),
                Column('document_type', css_class='col-md-3'),
                Column(
                    Submit('submit', 'Search', css_class='btn btn-primary'),
                    css_class='col-md-3 d-flex align-items-end'
                ),
            ),
            Row(
                Column('date_from', css_class='col-md-3'),
                Column('date_to', css_class='col-md-3'),
                Column('amount_min', css_class='col-md-3'),
                Column('amount_max', css_class='col-md-3'),
            ),
            Row(
                Column(
                    Field('status', template='invoices/checkbox_multiple.html'),
                    css_class='col-md-6'
                ),
                Column(
                    'is_overdue',
                    'is_fiscalized',
                    css_class='col-md-6'
                ),
            ),
        )


class InvoicePaymentForm(forms.ModelForm):
    """Form for recording invoice payments"""
    
    class Meta:
        model = InvoicePayment
        fields = [
            'amount', 'payment_method', 'transaction_reference',
            'payment_date', 'notes'
        ]
        widgets = {
            'payment_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'amount': forms.NumberInput(attrs={'step': '0.01', 'class': 'form-control'}),
            'notes': forms.Textarea(attrs={'rows': 2, 'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        self.invoice = kwargs.pop('invoice', None)
        super().__init__(*args, **kwargs)

        if self.invoice:
            # Attach the invoice to the model instance
            self.instance.invoice = self.invoice  

            outstanding = self.invoice.amount_outstanding
            self.fields['amount'].widget.attrs['max'] = str(outstanding)
            self.fields['amount'].initial = outstanding
            self.fields['amount'].help_text = f'Outstanding amount: UGX {outstanding:,.2f}'

        self.helper = FormHelper()
        self.helper.layout = Layout(
            Row(
                Column(PrependedText('amount', 'UGX'), css_class='col-md-6'),
                Column('payment_method', css_class='col-md-6'),
            ),
            Row(
                Column('transaction_reference', css_class='col-md-6'),
                Column('payment_date', css_class='col-md-6'),
            ),
            'notes',
            Div(
                Submit('submit', 'Record Payment', css_class='btn btn-success me-2'),
                HTML('<button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button>'),
                css_class='d-flex justify-content-end mt-3'
            )
        )

    def clean_amount(self):
        amount = self.cleaned_data.get('amount')
        if self.invoice and amount:
            outstanding = self.invoice.amount_outstanding
            if amount > outstanding:
                raise ValidationError(
                    f'Payment amount cannot exceed outstanding amount of UGX {outstanding:,.2f}'
                )
        return amount


class InvoiceTemplateForm(forms.ModelForm):
    """Form for managing invoice templates"""
    
    class Meta:
        model = InvoiceTemplate
        fields = [
            'name', 'template_file', 'is_default', 'is_efris_compliant',
            'version'
        ]
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'version': forms.TextInput(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.layout = Layout(
            Row(
                Column('name', css_class='col-md-8'),
                Column('version', css_class='col-md-4'),
            ),
            'template_file',
            Row(
                Column('is_default', css_class='col-md-6'),
                Column('is_efris_compliant', css_class='col-md-6'),
            ),
            Div(
                Submit('submit', 'Save Template', css_class='btn btn-primary me-2'),
                HTML('<a href="{% url "invoices:templates" %}" class="btn btn-secondary">Cancel</a>'),
                css_class='d-flex justify-content-end mt-3'
            )
        )

    def clean(self):
        cleaned_data = super().clean()
        is_default = cleaned_data.get('is_default')
        
        # Ensure only one default template exists
        if is_default and not self.instance.pk:
            if InvoiceTemplate.objects.filter(is_default=True).exists():
                raise ValidationError({
                    'is_default': _('Only one default template can exist. Please uncheck the current default first.')
                })
                
        return cleaned_data


class BulkInvoiceActionForm(forms.Form):
    """Form for bulk actions on invoices"""
    
    ACTION_CHOICES = [
        ('', 'Select Action'),
        ('mark_sent', 'Mark as Sent'),
        ('mark_paid', 'Mark as Paid'),
        ('export_pdf', 'Export to PDF'),
        ('send_email', 'Send Email Reminders'),
        ('fiscalize', 'Fiscalize Selected'),
    ]
    
    action = forms.ChoiceField(
        choices=ACTION_CHOICES,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    
    selected_invoices = forms.CharField(
        widget=forms.HiddenInput()
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.layout = Layout(
            Row(
                Column('action', css_class='col-md-8'),
                Column(
                    Submit('submit', 'Execute', css_class='btn btn-warning'),
                    css_class='col-md-4 d-flex align-items-end'
                ),
            ),
            'selected_invoices'
        )

    def clean_selected_invoices(self):
        selected = self.cleaned_data.get('selected_invoices', '')
        if not selected:
            raise ValidationError('No invoices selected.')
        
        try:
            invoice_ids = [int(x) for x in selected.split(',') if x.strip()]
            if not invoice_ids:
                raise ValidationError('No valid invoices selected.')
            return invoice_ids
        except ValueError:
            raise ValidationError('Invalid invoice selection.')


class FiscalizationForm(forms.Form):
    """Form for fiscalizing invoices with EFRIS"""

    confirm_fiscalization = forms.BooleanField(
        required=True,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        label=_('I confirm that this invoice should be fiscalized with URA EFRIS')
    )

    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'rows': 2, 'class': 'form-control'}),
        label=_('Additional Notes')
    )

    severity = forms.ChoiceField(
        required=False,
        choices=FiscalizationAudit.SEVERITY_CHOICES,
        initial='medium',
        widget=forms.Select(attrs={'class': 'form-select'}),
        label=_('Severity Level')
    )

    tags = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control'}),
        label=_('Tags (comma-separated)'),
        help_text=_('Add tags to categorize this fiscalization attempt')
    )

    def __init__(self, *args, **kwargs):
        self.invoice = kwargs.pop('invoice', None)
        self.user = kwargs.pop('user', None)
        self.company = kwargs.pop('company', None)
        super().__init__(*args, **kwargs)

        # Set initial values based on invoice data
        if self.invoice:
            self.fields['severity'].initial = self._determine_initial_severity()

        self.helper = FormHelper()
        self.helper.layout = Layout(
            HTML(f'''
                <div class="alert alert-warning">
                    <h6>Fiscalization Details</h6>
                    <p><strong>Invoice:</strong> {self.invoice.invoice_number if self.invoice else 'N/A'}</p>
                    <p><strong>Amount:</strong> UGX {(self.invoice.total_amount if self.invoice else 0):,.2f}</p>
                    <p><strong>Warning:</strong> This action cannot be undone once completed.</p>
                </div>
            '''),
            'confirm_fiscalization',
            'severity',
            'tags',
            'notes',
            Div(
                Submit('submit', 'Fiscalize Invoice', css_class='btn btn-danger me-2'),
                HTML('<button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button>'),
                css_class='d-flex justify-content-end mt-3'
            )
        )

    def _determine_initial_severity(self):
        """Determine initial severity based on invoice amount"""
        if not self.invoice:
            return 'medium'

        amount = self.invoice.total_amount
        if amount > 1000000:  # High amount threshold
            return 'high'
        elif amount > 500000:  # Medium amount threshold
            return 'medium'
        else:
            return 'low'

    def prepare_audit_data(self, request=None):
        """Prepare data for creating a FiscalizationAudit record"""
        if not self.invoice:
            return {}

        # Get client IP and user agent if available
        ip_address = None
        user_agent = None
        if request:
            ip_address = self._get_client_ip(request)
            user_agent = request.META.get('HTTP_USER_AGENT', '')

        # Get customer information
        customer = self.invoice.customer
        customer_tin = customer.tin if customer else ''
        customer_name = customer.name if customer else ''

        return {
            'company': self.company,
            'action': 'FISCALIZE',
            'status': 'pending',
            'severity': self.cleaned_data.get('severity', 'medium'),
            'invoice': self.invoice,
            'invoice_number': self.invoice.invoice_number,
            'user': self.user,
            'ip_address': ip_address,
            'user_agent': user_agent,
            'amount': self.invoice.total_amount,
            'tax_amount': self.invoice.tax_amount if hasattr(self.invoice, 'tax_amount') else 0,
            'customer_tin': customer_tin,
            'customer_name': customer_name,
            'notes': self.cleaned_data.get('notes', ''),
            'tags': self.cleaned_data.get('tags', ''),
        }

    def _get_client_ip(self, request):
        """Get client IP address from request"""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip



"""                    <p><strong>Customer:</strong> {self.invoice.customer.name if self.invoice and self.invoice.customer else 'N/A'}</p>
"""