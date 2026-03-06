from django import forms
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from django.contrib.auth import get_user_model
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Fieldset, Row, Column, Submit, Reset, HTML, Div
from crispy_forms.bootstrap import InlineRadios, PrependedText, AppendedText
from .models import Customer, CustomerGroup, CustomerNote, EFRISCustomerSync
from stores.models import Store
from stores.mixins import StoreRestrictedModelForm

User = get_user_model()


class CustomerForm(StoreRestrictedModelForm):
    """Advanced Customer Form with conditional fields and validation"""

    confirm_email = forms.EmailField(
        required=False,
        label=_("Confirm Email"),
        help_text=_("Please confirm the email address")
    )

    class Meta:
        model = Customer
        fields = [
            'customer_type', 'name', 'store', 'email', 'phone', 'tin', 'nin', 'brn',
            'physical_address', 'postal_address', 'district', 'country',
            'is_vat_registered', 'credit_limit', 'is_active', 'allow_credit'
        ]
        widgets = {
            'customer_type': forms.RadioSelect(attrs={'class': 'form-check-inline'}),
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': _('Enter customer name')
            }),
            'email': forms.EmailInput(attrs={
                'class': 'form-control',
                'placeholder': 'customer@example.com'
            }),
            'phone': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': '+256700000000'
            }),
            'tin': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': '1000000000',
                'maxlength': '20'
            }),
            'nin': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'CF12345678901234',
                'maxlength': '20'
            }),
            'brn': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'BRN12345',
                'maxlength': '20'
            }),
            'physical_address': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': _('Enter physical address')
            }),
            'postal_address': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': _('P.O. Box 1234, City')
            }),
            'district': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': _('Enter district')
            }),
            'country': forms.TextInput(attrs={
                'class': 'form-control'
            }),
            'credit_limit': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '0',
                'step': '0.01'
            }),
            'is_vat_registered': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
            'is_active': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
            'allow_credit': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        # Make email confirmation required if email is provided
        if self.data.get('email'):
            self.fields['confirm_email'].required = True

    def clean(self):
        cleaned_data = super().clean()
        email = cleaned_data.get('email')
        confirm_email = cleaned_data.get('confirm_email')
        customer_type = cleaned_data.get('customer_type')
        name = cleaned_data.get('name')
        phone = cleaned_data.get('phone')
        tin = cleaned_data.get('tin')

        # Email confirmation validation
        if email and confirm_email and email != confirm_email:
            raise ValidationError(_("Email addresses do not match."))

        # Basic requirements for all customers
        if not name or not name.strip():
            self.add_error('name', _("Customer name is required."))

        if not phone or not phone.strip():
            self.add_error('phone', _("Phone number is required."))

        # Business/Government/NGO requirements
        if customer_type in ['BUSINESS', 'GOVERNMENT', 'NGO']:
            if not tin:
                self.add_error('tin', _("TIN is required for Business, Government, and NGO customers."))

        # Individual customers - all fields optional except name and phone
        # No validation needed for NIN or other fields

        return cleaned_data

    def clean_phone(self):
        phone = self.cleaned_data.get('phone')
        if phone:
            phone = phone.strip()
            if not phone.startswith('+'):
                # Auto-add Uganda country code if not provided
                if phone.startswith('0'):
                    phone = '+256' + phone[1:]
                elif phone.startswith('256'):
                    phone = '+' + phone
                else:
                    phone = '+256' + phone
        return phone

    def clean_name(self):
        name = self.cleaned_data.get('name')
        if name:
            name = name.strip()
            if len(name) < 2:
                raise ValidationError(_("Customer name must be at least 2 characters long."))
        return name

    def clean_tin(self):
        tin = self.cleaned_data.get('tin')
        if tin:
            tin = tin.upper().strip()
            # Basic TIN format validation (can be customized based on country requirements)
            if len(tin) < 3:
                raise ValidationError(_("TIN appears to be too short."))
        return tin


class CustomerSearchForm(forms.Form):
    """Advanced search form for customers"""

    search = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': _('Search by name, phone, TIN, NIN, or BRN...'),
            'autocomplete': 'off'
        }),
        label=_('Search')
    )

    customer_type = forms.ChoiceField(
        choices=[('', _('All Types'))] + Customer.CUSTOMER_TYPES,
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'}),
        label=_('Customer Type')
    )

    store = forms.ModelChoiceField(
        queryset=Store.objects.all(),
        required=False,
        empty_label=_('All Stores'),
        widget=forms.Select(attrs={'class': 'form-select'}),
        label=_('Store')
    )

    is_vat_registered = forms.ChoiceField(
        choices=[('', _('All')), ('1', _('VAT Registered')), ('0', _('Not VAT Registered'))],
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'}),
        label=_('VAT Status')
    )

    is_active = forms.ChoiceField(
        choices=[('', _('All')), ('1', _('Active')), ('0', _('Inactive'))],
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'}),
        label=_('Status')
    )

    district = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': _('Filter by district')
        }),
        label=_('District')
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_method = 'get'
        self.helper.form_class = 'row g-3'
        self.helper.layout = Layout(
            Row(
                Column('search', css_class='col-md-4'),
                Column('customer_type', css_class='col-md-2'),
                Column('store', css_class='col-md-2'),
                Column('is_vat_registered', css_class='col-md-2'),
                Column('is_active', css_class='col-md-2'),
            ),
            Row(
                Column('district', css_class='col-md-4'),
                Column(
                    Submit('submit', _('Search'), css_class='btn btn-primary'),
                    HTML('<a href="?" class="btn btn-outline-secondary ms-2">Clear</a>'),
                    css_class='col-md-8 d-flex align-items-end'
                ),
            )
        )

class CustomerGroupForm(forms.ModelForm):
    """Form for customer groups"""

    class Meta:
        model = CustomerGroup
        fields = ['name', 'description', 'discount_percentage', 'customers']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': _('Enter group name')
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': _('Enter group description')
            }),
            'discount_percentage': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '0',
                'max': '100',
                'step': '0.01'
            }),
            'customers': forms.CheckboxSelectMultiple(attrs={
                'class': 'form-check-input'
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.layout = Layout(
            Fieldset(
                _('Group Information'),
                'name',
                'description',
                AppendedText('discount_percentage', '%'),
            ),
            Fieldset(
                _('Customers'),
                'customers',
            ),
            Submit('submit', _('Save Group'), css_class='btn btn-primary')
        )


class CustomerNoteForm(forms.ModelForm):
    """Form for customer notes"""

    class Meta:
        model = CustomerNote
        fields = ['note']
        widgets = {
            'note': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 4,
                'placeholder': _('Enter note about this customer...')
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.layout = Layout(
            'note',
            Submit('submit', _('Add Note'), css_class='btn btn-primary')
        )


class BulkCustomerActionForm(forms.Form):
    """Form for bulk actions on customers"""

    ACTION_CHOICES = [
        ('', '--- Select Action ---'),
        ('activate', _('Activate Selected')),
        ('deactivate', _('Deactivate Selected')),
        ('add_to_group', _('Add to Group')),
        ('remove_from_group', _('Remove from Group')),
        ('export', _('Export Selected')),
        ('delete', _('Delete Selected')),
        ('update_credit_limit', _('Update Credit Limit')),
        ('enable_credit', _('Enable Credit')),
        ('disable_credit', _('Disable Credit')),
    ]

    action = forms.ChoiceField(
        choices=ACTION_CHOICES,
        widget=forms.Select(attrs={'class': 'form-select'}),
        label=_('Action'),
        required=True
    )

    group = forms.ModelChoiceField(
        queryset=CustomerGroup.objects.all(),
        required=False,
        empty_label=_('Select Group'),
        widget=forms.Select(attrs={'class': 'form-select'}),
        label=_('Customer Group')
    )

    credit_limit = forms.DecimalField(
        max_digits=12,
        decimal_places=2,
        required=False,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': '0.00',
            'min': '0'
        }),
        label=_('New Credit Limit'),
        help_text=_('Required when updating credit limits')
    )

    selected_customers = forms.CharField(widget=forms.HiddenInput())

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_id = 'bulk-action-form'
        self.helper.layout = Layout(
            Row(
                Column('action', css_class='col-md-6'),
                Column('group', css_class='col-md-6'),
            ),
            Row(
                Column('credit_limit', css_class='col-md-6'),
                css_class='credit-limit-field',
            ),
            'selected_customers',
            Submit('submit', _('Apply Action'), css_class='btn btn-warning')
        )

        # Add JavaScript to show/hide credit_limit field
        self.helper.layout[1].css_class = 'd-none'  # Initially hide credit_limit field

    def clean(self):
        cleaned_data = super().clean()
        action = cleaned_data.get('action')
        credit_limit = cleaned_data.get('credit_limit')

        # Validate credit limit when updating
        if action == 'update_credit_limit':
            if credit_limit is None:
                self.add_error('credit_limit', _('Credit limit is required for this action.'))
            elif credit_limit < 0:
                self.add_error('credit_limit', _('Credit limit cannot be negative.'))

        return cleaned_data


class CustomerImportForm(forms.Form):
    """Form for importing customers from CSV/Excel"""

    file = forms.FileField(
        widget=forms.FileInput(attrs={
            'class': 'form-control',
            'accept': '.csv,.xlsx,.xls'
        }),
        label=_('Import File'),
        help_text=_('Upload CSV or Excel file with customer data')
    )

    update_existing = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        label=_('Update Existing Customers'),
        help_text=_('Update customers if they already exist (match by phone/email)')
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.layout = Layout(
            'file',
            'update_existing',
            Submit('submit', _('Import'), css_class='btn btn-success')
        )

    def clean_file(self):
        file = self.cleaned_data.get('file')
        if file:
            if not file.name.endswith(('.csv', '.xlsx', '.xls')):
                raise ValidationError(_('Only CSV and Excel files are allowed.'))
            if file.size > 5 * 1024 * 1024:  # 5MB limit
                raise ValidationError(_('File size cannot exceed 5MB.'))
        return file

class EFRISCustomerForm(forms.ModelForm):
    """Form for managing eFRIS customer registration and updates"""

    class Meta:
        model = Customer
        fields = [
            'name', 'customer_type', 'phone', 'email',
            'tin', 'nin', 'brn', 'passport_number', 'driving_license',
            'voter_id', 'alien_id', 'physical_address', 'postal_address'
        ]
        widgets = {
            'customer_type': forms.RadioSelect(attrs={'class': 'form-check-inline'}),
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': _('Enter customer name'),
                'required': True
            }),
            'phone': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': '+256700000000',
                'required': True
            }),
            'email': forms.EmailInput(attrs={
                'class': 'form-control',
                'placeholder': 'customer@example.com'
            }),
            'tin': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': '1000000000',
                'maxlength': '20'
            }),
            'nin': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'CF12345678901234',
                'maxlength': '20'
            }),
            'brn': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'BRN12345',
                'maxlength': '20'
            }),
            'passport_number': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'A1234567',
                'maxlength': '20'
            }),
            'driving_license': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'DL123456',
                'maxlength': '20'
            }),
            'voter_id': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'V123456789',
                'maxlength': '20'
            }),
            'alien_id': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'A123456789',
                'maxlength': '20'
            }),
            'physical_address': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': _('Enter physical address')
            }),
            'postal_address': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': _('P.O. Box 1234, City')
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Add CSS classes and help text for eFRIS requirements
        self.fields['name'].help_text = _('Required for eFRIS registration')
        self.fields['phone'].help_text = _('Required for eFRIS registration')
        self.fields['tin'].help_text = _('Required for Business, Government, and NGO customers')

        # Update the identification field help text
        self.fields['nin'].help_text = _('Optional for individual customers')
        self.fields['brn'].help_text = _('Optional for business customers')
        self.fields['passport_number'].help_text = _('Optional identification')
        self.fields['driving_license'].help_text = _('Optional identification')
        self.fields['voter_id'].help_text = _('Optional identification')
        self.fields['alien_id'].help_text = _('Optional identification')

        self.helper = FormHelper()
        self.helper.layout = Layout(
            Fieldset(
                _('Basic Information'),
                HTML('<p class="text-muted"><small>Name and phone are required for all customers</small></p>'),
                Row(
                    Column('name', css_class='col-md-6'),
                    Column('phone', css_class='col-md-6'),
                ),
                Row(
                    Column('email', css_class='col-md-6'),
                    Column(InlineRadios('customer_type'), css_class='col-md-6'),
                ),
            ),
            Fieldset(
                _('Identification Numbers'),
                HTML(
                    '<p class="text-muted"><small>TIN is required for Business, Government, and NGO customers. All other fields are optional.</small></p>'),
                Row(
                    Column('tin', css_class='col-md-6'),
                    Column('brn', css_class='col-md-6'),
                ),
                Row(
                    Column('nin', css_class='col-md-6'),
                    Column('passport_number', css_class='col-md-6'),
                ),
                Row(
                    Column('driving_license', css_class='col-md-6'),
                    Column('voter_id', css_class='col-md-6'),
                ),
                Row(
                    Column('alien_id', css_class='col-md-6'),
                ),
            ),
            Fieldset(
                _('Address Information'),
                'physical_address',
                'postal_address',
            ),
            Div(
                Submit('submit', _('Save Customer'), css_class='btn btn-primary'),
                Submit('submit_and_sync', _('Save & Sync to eFRIS'), css_class='btn btn-success ms-2'),
                Reset('reset', _('Reset'), css_class='btn btn-outline-secondary ms-2'),
                css_class='d-flex justify-content-end'
            )
        )

    def clean(self):
        cleaned_data = super().clean()
        customer_type = cleaned_data.get('customer_type')
        name = cleaned_data.get('name')
        phone = cleaned_data.get('phone')
        tin = cleaned_data.get('tin')

        # Basic requirements for all customers
        if not name or not name.strip():
            self.add_error('name', _('Customer name is required'))

        if not phone or not phone.strip():
            self.add_error('phone', _('Phone number is required'))

        # Business/Government/NGO requirements
        if customer_type in ['BUSINESS', 'GOVERNMENT', 'NGO']:
            if not tin:
                self.add_error('tin', _('TIN is required for Business, Government, and NGO customers'))

        return cleaned_data

    def clean_phone(self):
        phone = self.cleaned_data.get('phone')
        if phone and not phone.startswith('+'):
            # Auto-add Uganda country code if not provided
            if phone.startswith('0'):
                phone = '+256' + phone[1:]
            else:
                phone = '+256' + phone
        return phone


class EFRISSyncForm(forms.ModelForm):
    """Form for managing eFRIS sync operations"""

    class Meta:
        model = EFRISCustomerSync
        fields = ['sync_type', 'max_retries']
        widgets = {
            'sync_type': forms.RadioSelect(attrs={'class': 'form-check-inline'}),
            'max_retries': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '1',
                'max': '10',
                'value': '3'
            }),
        }

    def __init__(self, *args, **kwargs):
        self.customer = kwargs.pop('customer', None)
        super().__init__(*args, **kwargs)

        # Add customer information as read-only display
        if self.customer:
            self.fields['customer_info'] = forms.CharField(
                label=_('Customer'),
                initial=f"{self.customer.name} ({self.customer.phone})",
                widget=forms.TextInput(attrs={
                    'class': 'form-control',
                    'readonly': True
                }),
                required=False
            )

        self.helper = FormHelper()
        self.helper.layout = Layout(
            Fieldset(
                _('Sync Configuration'),
                'customer_info' if self.customer else None,
                InlineRadios('sync_type'),
                Row(
                    Column('max_retries', css_class='col-md-4'),
                ),
            ),
            Div(
                Submit('submit', _('Start Sync'), css_class='btn btn-primary'),
                Reset('reset', _('Reset'), css_class='btn btn-outline-secondary ms-2'),
                css_class='d-flex justify-content-end'
            )
        )

    def clean(self):
        cleaned_data = super().clean()

        if self.customer and not self.customer.can_sync_to_efris:
            raise ValidationError(
                _('Customer does not have the required information for eFRIS sync')
            )

        return cleaned_data


class EFRISBulkSyncForm(forms.Form):
    """Form for bulk eFRIS sync operations"""

    SYNC_TYPE_CHOICES = [
        ('REGISTER', _('Register new customers')),
        ('UPDATE', _('Update existing customers')),
        ('QUERY', _('Query customer status')),
    ]

    sync_type = forms.ChoiceField(
        choices=SYNC_TYPE_CHOICES,
        widget=forms.RadioSelect(attrs={'class': 'form-check-inline'}),
        label=_('Sync Type')
    )

    selected_customers = forms.CharField(
        widget=forms.HiddenInput(),
        required=True
    )

    max_retries = forms.IntegerField(
        min_value=1,
        max_value=10,
        initial=3,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
        }),
        label=_('Max Retries'),
        help_text=_('Number of retry attempts for failed syncs')
    )

    batch_size = forms.IntegerField(
        min_value=1,
        max_value=100,
        initial=10,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
        }),
        label=_('Batch Size'),
        help_text=_('Number of customers to sync in each batch')
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.layout = Layout(
            Fieldset(
                _('Bulk Sync Configuration'),
                InlineRadios('sync_type'),
                Row(
                    Column('max_retries', css_class='col-md-6'),
                    Column('batch_size', css_class='col-md-6'),
                ),
                'selected_customers',
            ),
            HTML('<div class="alert alert-info"><i class="fas fa-info-circle"></i> '
                 'Selected customers will be processed in batches. '
                 'You can monitor progress in the sync status page.</div>'),
            Div(
                Submit('submit', _('Start Bulk Sync'), css_class='btn btn-primary'),
                css_class='d-flex justify-content-end'
            )
        )


class EFRISStatusFilterForm(forms.Form):
    """Form for filtering eFRIS sync status"""

    STATUS_CHOICES = [
        ('', _('All Statuses')),
        ('PENDING', _('Pending')),
        ('SUCCESS', _('Success')),
        ('FAILED', _('Failed')),
        ('RETRY', _('Retry Required')),
    ]

    SYNC_TYPE_CHOICES = [
        ('', _('All Types')),
        ('REGISTER', _('Registration')),
        ('UPDATE', _('Update')),
        ('QUERY', _('Query')),
    ]

    status = forms.ChoiceField(
        choices=STATUS_CHOICES,
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'}),
        label=_('Status')
    )

    sync_type = forms.ChoiceField(
        choices=SYNC_TYPE_CHOICES,
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'}),
        label=_('Sync Type')
    )

    customer_name = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': _('Search by customer name...')
        }),
        label=_('Customer Name')
    )

    date_from = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={
            'class': 'form-control',
            'type': 'date'
        }),
        label=_('From Date')
    )

    date_to = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={
            'class': 'form-control',
            'type': 'date'
        }),
        label=_('To Date')
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_method = 'get'
        self.helper.form_class = 'row g-3'
        self.helper.layout = Layout(
            Row(
                Column('status', css_class='col-md-2'),
                Column('sync_type', css_class='col-md-2'),
                Column('customer_name', css_class='col-md-3'),
                Column('date_from', css_class='col-md-2'),
                Column('date_to', css_class='col-md-2'),
                Column(
                    Submit('submit', _('Filter'), css_class='btn btn-primary'),
                    HTML('<a href="?" class="btn btn-outline-secondary ms-2">Clear</a>'),
                    css_class='col-md-1 d-flex align-items-end'
                ),
            )
        )


class EFRISRetryForm(forms.Form):
    """Form for retrying failed eFRIS sync operations"""

    sync_ids = forms.CharField(
        widget=forms.HiddenInput(),
        required=True
    )

    reset_retry_count = forms.BooleanField(
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        label=_('Reset Retry Count'),
        help_text=_('Reset the retry counter to 0 before retrying')
    )

    increase_max_retries = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        label=_('Increase Max Retries'),
        help_text=_('Increase maximum retry attempts by 2')
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.layout = Layout(
            'sync_ids',
            Fieldset(
                _('Retry Options'),
                'reset_retry_count',
                'increase_max_retries',
            ),
            HTML('<div class="alert alert-warning"><i class="fas fa-exclamation-triangle"></i> '
                 'This will retry all selected failed sync operations.</div>'),
            Div(
                Submit('submit', _('Retry Selected'), css_class='btn btn-warning'),
                css_class='d-flex justify-content-end'
            )
        )