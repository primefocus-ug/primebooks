from django import forms
from django.utils.translation import gettext_lazy as _
from django.core.exceptions import ValidationError
from decimal import Decimal
from .models import Expense, ExpenseCategory, ExpenseAttachment, ExpenseComment


class ExpenseForm(forms.ModelForm):
    """Form for creating and editing expenses"""

    attachments = forms.FileField(
        required=False,
        widget=forms.ClearableFileInput(attrs={
            'class': 'form-control',
            'accept': 'image/*,.pdf,.doc,.docx,.xls,.xlsx'
        }),
        label=_("Attachments"),
        help_text=_("You can upload files (images, PDFs, documents)")
    )

    class Meta:
        model = Expense
        fields = [
            'title', 'description', 'category', 'amount', 'currency',
            'tax_rate', 'expense_date', 'due_date', 'vendor_name',
            'vendor_phone', 'vendor_email', 'vendor_tin', 'reference_number',
            'is_reimbursable', 'is_recurring', 'is_billable', 'notes'
        ]
        widgets = {
            'title': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': _('Enter expense title'),
                'required': True
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 4,
                'placeholder': _('Describe the expense in detail'),
                'required': True
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
                'class': 'form-select'
            }),
            'tax_rate': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'min': '0',
                'max': '100',
                'placeholder': '0.00'
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
                'placeholder': _('Vendor/Supplier name')
            }),
            'vendor_phone': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': _('Phone number')
            }),
            'vendor_email': forms.EmailInput(attrs={
                'class': 'form-control',
                'placeholder': _('Email address')
            }),
            'vendor_tin': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': _('Tax Identification Number')
            }),
            'reference_number': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': _('Receipt or invoice number')
            }),
            'notes': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': _('Additional notes')
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
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        # Filter active categories only
        self.fields['category'].queryset = ExpenseCategory.objects.filter(
            is_active=True
        ).order_by('sort_order', 'name')

        # Set currency choices
        self.fields['currency'].choices = [
            ('UGX', _('UGX - Uganda Shilling')),
            ('USD', _('USD - US Dollar')),
            ('EUR', _('EUR - Euro')),
            ('GBP', _('GBP - British Pound')),
        ]

    def clean_amount(self):
        amount = self.cleaned_data.get('amount')
        if amount and amount <= 0:
            raise ValidationError(_("Amount must be greater than zero"))
        return amount

    def clean(self):
        cleaned_data = super().clean()
        expense_date = cleaned_data.get('expense_date')
        due_date = cleaned_data.get('due_date')

        if expense_date and due_date and due_date < expense_date:
            raise ValidationError({
                'due_date': _("Due date cannot be before expense date")
            })

        return cleaned_data


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