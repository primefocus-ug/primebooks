from django import forms
from django.utils.translation import gettext_lazy as _
from django.core.exceptions import ValidationError
from decimal import Decimal
from .models import Expense, ExpenseCategory, ExpenseAttachment, ExpenseComment
from django.utils import timezone
from django import forms
import os
from django.utils.translation import gettext_lazy as _
from django.core.exceptions import ValidationError
from decimal import Decimal
from .models import Expense

class MultipleClearableFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True  # <- This is required

    def __init__(self, attrs=None):
        default_attrs = {'multiple': True}
        if attrs:
            default_attrs.update(attrs)
        super().__init__(attrs=default_attrs)

    def value_from_datadict(self, data, files, name):
        if hasattr(files, 'getlist'):
            return files.getlist(name)
        return None


class ExpenseForm(forms.ModelForm):
    """Form for creating and editing expenses"""

    attachments = forms.FileField(
        required=False,
        widget=MultipleClearableFileInput(attrs={
            'class': 'form-control',
            'accept': 'image/*,.pdf,.doc,.docx,.xls,.xlsx,.csv,.txt',
            'multiple': True
        }),
        label=_("Attachments"),
        help_text=_("Upload receipts or supporting documents (max 10MB each, max 10 files)")
    )

    class Meta:
        model = Expense
        fields = [
            'title', 'description', 'category', 'amount', 'currency',
            'expense_date', 'due_date', 'store',
            'vendor_name', 'vendor_phone', 'vendor_email', 'vendor_tin',
            'reference_number', 'payment_method', 'payment_reference',
            'is_reimbursable', 'is_recurring', 'is_billable', 'notes'
        ]
        widgets = {
            'title': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': _('Enter expense title'),
                'required': True,
                'maxlength': '200'
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 4,
                'placeholder': _('Describe the expense in detail'),
                'required': True,
                'maxlength': '5000'
            }),
            'category': forms.Select(attrs={
                'class': 'form-select',
                'required': True
            }),
            'amount': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'min': '0.01',
                'placeholder': '0.00',
                'required': True
            }),
            'currency': forms.Select(attrs={
                'class': 'form-select',
                'required': True
            }),
            'expense_date': forms.DateInput(attrs={
                'class': 'form-control',
                'type': 'date',
                'required': True
            }),
            'due_date': forms.DateInput(attrs={
                'class': 'form-control',
                'type': 'date'
            }),
            'vendor_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': _('Vendor/Supplier name'),
                'maxlength': '200'
            }),
            'vendor_phone': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': _('Phone number'),
                'maxlength': '20'
            }),
            'vendor_email': forms.EmailInput(attrs={
                'class': 'form-control',
                'placeholder': _('Email address'),
                'maxlength': '254'
            }),
            'vendor_tin': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': _('Tax Identification Number'),
                'maxlength': '20'
            }),
            'reference_number': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': _('Receipt or invoice number'),
                'maxlength': '100'
            }),
            'payment_method': forms.Select(attrs={
                'class': 'form-select'
            }),
            'payment_reference': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': _('Transaction ID or reference'),
                'maxlength': '100'
            }),
            'notes': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': _('Additional notes'),
                'maxlength': '2000'
            }),
            'is_reimbursable': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
            'is_recurring': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
            'is_billable': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
            'store': forms.Select(attrs={
                'class': 'form-select'
            }),
        }
        help_texts = {
            'reference_number': _('If available, enter receipt/invoice number'),
            'is_reimbursable': _('Check if this expense should be reimbursed to you'),
            'is_billable': _('Check if this expense can be billed to a customer'),
            'payment_reference': _('Enter transaction ID, cheque number, or other payment reference'),
        }
        labels = {
            'payment_reference': _('Payment Reference/Txn ID'),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        self.is_edit = kwargs.pop('is_edit', False)
        self.is_admin = kwargs.pop('is_admin', False)
        super().__init__(*args, **kwargs)

        # Set category choices with default option
        self.fields['category'].choices = [('', _('-- Select Category --'))] + list(Expense.CATEGORY_CHOICES)

        # Set payment method choices with default option
        self.fields['payment_method'].choices = [('', _('-- Select Payment Method --'))] + list(Expense.PAYMENT_METHODS)

        # Set currency choices
        self.fields['currency'].choices = [
            ('', _('-- Select Currency --')),
            ('UGX', _('UGX - Uganda Shilling')),
            ('USD', _('USD - US Dollar')),
            ('EUR', _('EUR - Euro')),
            ('GBP', _('GBP - British Pound')),
        ]

        # Set store field queryset
        if self.user:
            self.fields['store'].queryset = self.get_user_stores(self.user)
            self.fields['store'].empty_label = _('-- Select Store/Branch --')

        # For existing expense, add read-only expense_number field
        if self.instance and self.instance.pk:
            self.fields['expense_number'] = forms.CharField(
                initial=self.instance.expense_number,
                widget=forms.TextInput(attrs={
                    'class': 'form-control',
                    'readonly': 'readonly'
                }),
                label=_("Expense Number"),
                required=False
            )

        # Add admin notes field only for admin users
        if self.is_admin:
            self.fields['admin_notes'] = forms.CharField(
                required=False,
                widget=forms.Textarea(attrs={
                    'class': 'form-control',
                    'rows': 2,
                    'placeholder': _('Internal notes (not visible to creator)'),
                    'maxlength': '1000'
                }),
                label=_("Admin Notes"),
                help_text=_("Internal notes not visible to expense creator")
            )
            # Add to Meta.fields for proper validation
            if 'admin_notes' not in self.Meta.fields:
                self.Meta.fields.append('admin_notes')

        # Make certain fields read-only based on status
        if self.instance and self.instance.pk and self.instance.status != 'DRAFT':
            readonly_fields = ['amount', 'category', 'expense_date', 'vendor_name']
            for field in readonly_fields:
                if field in self.fields:
                    self.fields[field].widget.attrs['readonly'] = True
                    self.fields[field].widget.attrs['class'] += ' bg-light'

        # Add CSS classes for styling
        for field_name, field in self.fields.items():
            if field_name not in ['is_reimbursable', 'is_recurring', 'is_billable']:
                if 'class' not in field.widget.attrs:
                    field.widget.attrs['class'] = 'form-control'
            if isinstance(field.widget, forms.Select):
                field.widget.attrs['class'] = 'form-select'

        # Add placeholder for vendor TIN
        self.fields['vendor_tin'].widget.attrs['placeholder'] = _('TIN, VAT Number, or Tax ID')

    def get_user_stores(self, user):
        """Get stores that the user has access to"""
        from stores.models import Store

        try:
            if user.is_superuser or self.is_admin:
                return Store.objects.filter(is_active=True).order_by('name')
            elif hasattr(user, 'profile') and hasattr(user.profile, 'stores'):
                # If user has profile with store access
                return user.profile.stores.filter(is_active=True).order_by('name')
            elif hasattr(user, 'store'):
                # If user is directly associated with a store
                return Store.objects.filter(id=user.store.id, is_active=True)
            else:
                # Default: show all active stores
                return Store.objects.filter(is_active=True).order_by('name')
        except Exception:
            return Store.objects.filter(is_active=True).order_by('name')

    def clean_attachments(self):
        """Validate uploaded files"""
        attachments = self.files.getlist('attachments') if self.files else []

        # Limit number of files
        max_files = 10
        if len(attachments) > max_files:
            raise ValidationError(_(f'Maximum {max_files} files allowed'))

        # Validate each file
        for attachment in attachments:
            # Check file size (10MB limit - increased from 5MB)
            if attachment.size > 10 * 1024 * 1024:
                raise ValidationError(_(f'File "{attachment.name}" exceeds 10MB limit'))

            # Check file extension
            allowed_extensions = [
                '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp',
                '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.csv', '.txt'
            ]
            ext = os.path.splitext(attachment.name)[1].lower()
            if ext not in allowed_extensions:
                raise ValidationError(_(
                    f'File type {ext} not allowed. Allowed types: {", ".join(allowed_extensions)}'
                ))

        return attachments

    def clean_amount(self):
        amount = self.cleaned_data.get('amount')
        if amount is not None and amount <= 0:
            raise ValidationError(_("Amount must be greater than zero"))
        return amount

    def clean_vendor_email(self):
        email = self.cleaned_data.get('vendor_email')
        if email and not email.strip():
            return ''
        return email

    def clean_vendor_phone(self):
        phone = self.cleaned_data.get('vendor_phone')
        if phone:
            # Basic phone number validation (remove non-digits)
            phone_digits = ''.join(filter(str.isdigit, phone))
            if len(phone_digits) < 9:
                raise ValidationError(_("Please enter a valid phone number"))
        return phone

    def clean(self):
        cleaned_data = super().clean()

        # Validate date logic
        expense_date = cleaned_data.get('expense_date')
        due_date = cleaned_data.get('due_date')

        if expense_date and due_date:
            if due_date < expense_date:
                self.add_error('due_date',
                               _("Payment due date cannot be before the expense date")
                               )

        # Validate payment reference based on payment method
        payment_method = cleaned_data.get('payment_method')
        payment_reference = cleaned_data.get('payment_reference')

        if payment_method and payment_method != 'CASH':
            if not payment_reference or not payment_reference.strip():
                self.add_error('payment_reference',
                               _(f"Payment reference is required for {self.get_payment_method_display(payment_method)}")
                               )

        return cleaned_data

    def get_payment_method_display(self, value):
        """Get display name for payment method"""
        choices_dict = dict(Expense.PAYMENT_METHODS)
        return choices_dict.get(value, value)

    def save(self, commit=True):
        instance = super().save(commit=False)

        # Set the user who created/updated the expense
        if self.user and not instance.pk:
            instance.created_by = self.user

        # Set admin notes if provided and user is admin
        if self.is_admin and 'admin_notes' in self.cleaned_data:
            instance.admin_notes = self.cleaned_data['admin_notes']

        if commit:
            instance.save()

            # Handle file attachments
            if self.files and 'attachments' in self.files:
                self.save_attachments(instance)

        return instance

    def save_attachments(self, expense):
        """Save uploaded attachments"""
        from .models import ExpenseAttachment

        for uploaded_file in self.files.getlist('attachments'):
            # Check if file already exists for this expense
            existing = ExpenseAttachment.objects.filter(
                expense=expense,
                file=uploaded_file.name
            ).exists()

            if not existing:
                attachment = ExpenseAttachment(
                    expense=expense,
                    file=uploaded_file,
                    uploaded_by=self.user,
                    file_name=uploaded_file.name
                )
                attachment.save()

class ExpenseFilterForm(forms.Form):
    """Form for filtering expenses"""

    status = forms.ChoiceField(
        required=False,
        choices=[('', _('All Statuses'))] + Expense.STATUS_CHOICES,
        widget=forms.Select(attrs={'class': 'form-select'})
    )

    category = forms.ModelChoiceField(
        required=False,
        queryset=ExpenseCategory.objects.filter(is_active=True),
        empty_label=_('All Categories'),
        widget=forms.Select(attrs={'class': 'form-select'})
    )

    date_from = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={
            'class': 'form-control',
            'type': 'date'
        }),
        label=_("From Date")
    )

    date_to = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={
            'class': 'form-control',
            'type': 'date'
        }),
        label=_("To Date")
    )

    search = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': _('Search expenses...')
        }),
        label=_("Search")
    )


class ExpenseApprovalForm(forms.Form):
    """Form for approving or rejecting expenses"""

    action = forms.ChoiceField(
        choices=[
            ('approve', _('Approve')),
            ('reject', _('Reject'))
        ],
        widget=forms.RadioSelect(attrs={'class': 'form-check-input'}),
        label=_("Action")
    )

    rejection_reason = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 3,
            'placeholder': _('Enter reason for rejection')
        }),
        label=_("Rejection Reason")
    )

    admin_notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 2,
            'placeholder': _('Internal notes (optional)')
        }),
        label=_("Admin Notes")
    )

    def clean(self):
        cleaned_data = super().clean()
        action = cleaned_data.get('action')
        rejection_reason = cleaned_data.get('rejection_reason')

        if action == 'reject' and not rejection_reason:
            raise ValidationError({
                'rejection_reason': _("Rejection reason is required when rejecting an expense")
            })

        return cleaned_data


class ExpensePaymentForm(forms.Form):
    """Form for marking expenses as paid"""

    payment_method = forms.ChoiceField(
        choices=Expense.PAYMENT_METHODS,
        widget=forms.Select(attrs={'class': 'form-select'}),
        label=_("Payment Method")
    )

    payment_reference = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': _('Transaction ID or reference number')
        }),
        label=_("Payment Reference")
    )

    payment_notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 2,
            'placeholder': _('Additional payment notes')
        }),
        label=_("Payment Notes")
    )


class ExpenseCommentForm(forms.ModelForm):
    """Form for adding comments to expenses"""

    class Meta:
        model = ExpenseComment
        fields = ['comment', 'is_internal']
        widgets = {
            'comment': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': _('Add your comment...'),
                'required': True
            }),
            'is_internal': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            })
        }


class ExpenseCategoryForm(forms.ModelForm):
    """Form for creating and editing expense categories"""

    class Meta:
        model = ExpenseCategory
        fields = [
            'name', 'code', 'description', 'monthly_budget',
            'requires_approval', 'approval_threshold', 'color_code',
            'icon', 'is_active', 'sort_order'
        ]
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': _('Category name'),
                'required': True
            }),
            'code': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': _('Unique code'),
                'required': True
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': _('Category description')
            }),
            'monthly_budget': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'min': '0',
                'placeholder': '0.00'
            }),
            'approval_threshold': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'min': '0',
                'placeholder': '0.00'
            }),
            'color_code': forms.TextInput(attrs={
                'class': 'form-control',
                'type': 'color'
            }),
            'icon': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': _('e.g., bi-cart, fa-shopping-cart')
            }),
            'requires_approval': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
            'is_active': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
            'sort_order': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '0'
            })
        }


class BulkExpenseActionForm(forms.Form):
    """Form for bulk actions on expenses"""

    action = forms.ChoiceField(
        choices=[
            ('', _('Select Action')),
            ('approve', _('Approve Selected')),
            ('reject', _('Reject Selected')),
            ('delete', _('Delete Selected')),
            ('export', _('Export Selected'))
        ],
        widget=forms.Select(attrs={'class': 'form-select'}),
        label=_("Bulk Action")
    )

    expense_ids = forms.CharField(
        widget=forms.HiddenInput(),
        required=False
    )

    def clean_expense_ids(self):
        ids = self.cleaned_data.get('expense_ids', '')
        if ids:
            try:
                return [int(id.strip()) for id in ids.split(',') if id.strip()]
            except ValueError:
                raise ValidationError(_("Invalid expense IDs"))
        return []
    

class CategoryBudgetForm(forms.Form):
    categories = forms.ModelMultipleChoiceField(
        queryset=ExpenseCategory.objects.all(),
        widget=forms.CheckboxSelectMultiple,
        required=False
    )
    budget_amount = forms.DecimalField(
        max_digits=12,
        decimal_places=2,
        min_value=0,
        widget=forms.NumberInput(attrs={'class': 'form-control'})
    )
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['categories'].queryset = ExpenseCategory.objects.filter(is_active=True)
        
class ExpenseSearchForm(forms.Form):
    query = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'placeholder': 'Search by title, description, vendor...',
            'class': 'form-control'
        })
    )
    category = forms.ModelChoiceField(
        queryset=ExpenseCategory.objects.filter(is_active=True),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    status = forms.ChoiceField(
        choices=[('', 'All Statuses')] + Expense.STATUS_CHOICES,
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

class ExpenseCommentForm(forms.ModelForm):
    class Meta:
        model = ExpenseComment
        fields = ['comment', 'is_internal']
        widgets = {
            'comment': forms.Textarea(attrs={
                'rows': 3,
                'class': 'form-control',
                'placeholder': 'Add your comment here...'
            }),
            'is_internal': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            })
        }
    
    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        
        # Only show internal checkbox for users with approval permissions
        if not self.user or not self.user.has_perm('expenses.approve_expense'):
            self.fields.pop('is_internal')

class BulkExpenseActionForm(forms.Form):
    ACTION_CHOICES = [
        ('submit', 'Submit for Approval'),
        ('delete', 'Delete'),
    ]
    
    expense_ids = forms.CharField(widget=forms.HiddenInput())
    action = forms.ChoiceField(choices=ACTION_CHOICES, widget=forms.Select(attrs={'class': 'form-select'}))
    
    def clean_expense_ids(self):
        expense_ids = self.cleaned_data['expense_ids']
        try:
            return [int(id) for id in expense_ids.split(',') if id.strip()]
        except (ValueError, AttributeError):
            raise ValidationError('Invalid expense IDs')

class ExpenseReportForm(forms.Form):
    REPORT_TYPE_CHOICES = [
        ('summary', 'Expense Summary'),
        ('category', 'Category Breakdown'),
        ('vendor', 'Vendor Analysis'),
        ('approval', 'Approval Timeline'),
    ]
    
    report_type = forms.ChoiceField(
        choices=REPORT_TYPE_CHOICES,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    date_from = forms.DateField(
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'})
    )
    date_to = forms.DateField(
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'})
    )
    category = forms.ModelChoiceField(
        queryset=ExpenseCategory.objects.filter(is_active=True),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    format = forms.ChoiceField(
        choices=[('pdf', 'PDF'), ('excel', 'Excel')],
        initial='pdf',
        widget=forms.Select(attrs={'class': 'form-select'})
    )