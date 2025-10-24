from django import forms
from django.utils.translation import gettext_lazy as _
from django.core.exceptions import ValidationError
from decimal import Decimal

from .models import (
    Expense, ExpenseCategory, Vendor, Budget, RecurringExpense,
    PettyCash, PettyCashTransaction, EmployeeReimbursement,
    ReimbursementItem, ExpenseAttachment, ExpenseSplit
)


class ExpenseForm(forms.ModelForm):
    """Form for creating/editing expenses"""

    class Meta:
        model = Expense
        fields = [
            'category', 'expense_type', 'vendor', 'description',
            'expense_date', 'amount', 'tax_rate', 'tax_amount',
            'due_date', 'invoice_number', 'purchase_order',
            'payment_method', 'is_recurring', 'notes'
        ]
        widgets = {
            'expense_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'due_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'description': forms.Textarea(attrs={'rows': 3, 'class': 'form-control'}),
            'notes': forms.Textarea(attrs={'rows': 3, 'class': 'form-control'}),
            'category': forms.Select(attrs={'class': 'form-control'}),
            'expense_type': forms.Select(attrs={'class': 'form-control'}),
            'vendor': forms.Select(attrs={'class': 'form-control'}),
            'amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'tax_rate': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'tax_amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'readonly': True}),
            'invoice_number': forms.TextInput(attrs={'class': 'form-control'}),
            'purchase_order': forms.TextInput(attrs={'class': 'form-control'}),
            'payment_method': forms.Select(attrs={'class': 'form-control'}),
        }

    def clean(self):
        cleaned_data = super().clean()
        amount = cleaned_data.get('amount')
        tax_rate = cleaned_data.get('tax_rate')
        tax_amount = cleaned_data.get('tax_amount')

        # Auto-calculate tax if not provided
        if amount and tax_rate and not tax_amount:
            cleaned_data['tax_amount'] = (amount * tax_rate / Decimal('100')).quantize(Decimal('0.01'))

        return cleaned_data


class ExpenseFilterForm(forms.Form):
    """Form for filtering expenses"""

    status = forms.ChoiceField(
        choices=[('', 'All Statuses')] + Expense.STATUS_CHOICES,
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'})
    )

    category = forms.ModelChoiceField(
        queryset=ExpenseCategory.objects.filter(is_active=True),
        required=False,
        empty_label='All Categories',
        widget=forms.Select(attrs={'class': 'form-control'})
    )

    vendor = forms.ModelChoiceField(
        queryset=Vendor.objects.filter(is_active=True),
        required=False,
        empty_label='All Vendors',
        widget=forms.Select(attrs={'class': 'form-control'})
    )

    start_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'})
    )

    end_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'})
    )

    search = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Search expenses...'
        })
    )


class ExpenseApprovalForm(forms.Form):
    """Form for approving/rejecting expenses"""

    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'rows': 3,
            'class': 'form-control',
            'placeholder': 'Add approval notes (optional)...'
        })
    )


class ExpenseCategoryForm(forms.ModelForm):
    """Form for creating/editing expense categories"""

    class Meta:
        model = ExpenseCategory
        fields = [
            'name', 'code', 'parent', 'category_type', 'description',
            'is_active', 'requires_approval', 'approval_limit',
            'is_taxable', 'default_tax_rate', 'budget_allocation',
            'color_code', 'icon', 'sort_order'
        ]
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'code': forms.TextInput(attrs={'class': 'form-control'}),
            'parent': forms.Select(attrs={'class': 'form-control'}),
            'category_type': forms.Select(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'rows': 3, 'class': 'form-control'}),
            'approval_limit': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'default_tax_rate': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'budget_allocation': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'color_code': forms.TextInput(attrs={'type': 'color', 'class': 'form-control'}),
            'icon': forms.TextInput(attrs={'class': 'form-control'}),
            'sort_order': forms.NumberInput(attrs={'class': 'form-control'}),
        }


class VendorForm(forms.ModelForm):
    """Form for creating/editing vendors"""

    class Meta:
        model = Vendor
        fields = [
            'name', 'vendor_type', 'contact_person', 'email', 'phone', 'address',
            'tin', 'is_registered_for_vat', 'payment_terms', 'custom_payment_days',
            'credit_limit', 'bank_name', 'account_number', 'account_name',
            'mobile_money_number', 'is_active', 'is_approved', 'rating', 'notes'
        ]
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'vendor_type': forms.Select(attrs={'class': 'form-control'}),
            'contact_person': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'phone': forms.TextInput(attrs={'class': 'form-control'}),
            'address': forms.Textarea(attrs={'rows': 3, 'class': 'form-control'}),
            'tin': forms.TextInput(attrs={'class': 'form-control'}),
            'payment_terms': forms.Select(attrs={'class': 'form-control'}),
            'custom_payment_days': forms.NumberInput(attrs={'class': 'form-control'}),
            'credit_limit': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'bank_name': forms.TextInput(attrs={'class': 'form-control'}),
            'account_number': forms.TextInput(attrs={'class': 'form-control'}),
            'account_name': forms.TextInput(attrs={'class': 'form-control'}),
            'mobile_money_number': forms.TextInput(attrs={'class': 'form-control'}),
            'rating': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0', 'max': '5'}),
            'notes': forms.Textarea(attrs={'rows': 3, 'class': 'form-control'}),
        }


class BudgetForm(forms.ModelForm):
    """Form for creating/editing budgets"""

    class Meta:
        model = Budget
        fields = [
            'name', 'category', 'store', 'budget_period',
            'start_date', 'end_date', 'allocated_amount',
            'warning_threshold', 'critical_threshold',
            'is_active', 'notes'
        ]
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'category': forms.Select(attrs={'class': 'form-control'}),
            'store': forms.Select(attrs={'class': 'form-control'}),
            'budget_period': forms.Select(attrs={'class': 'form-control'}),
            'start_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'end_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'allocated_amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'warning_threshold': forms.NumberInput(attrs={'class': 'form-control', 'min': '0', 'max': '100'}),
            'critical_threshold': forms.NumberInput(attrs={'class': 'form-control', 'min': '0', 'max': '100'}),
            'notes': forms.Textarea(attrs={'rows': 3, 'class': 'form-control'}),
        }

    def clean(self):
        cleaned_data = super().clean()
        start_date = cleaned_data.get('start_date')
        end_date = cleaned_data.get('end_date')

        if start_date and end_date and end_date < start_date:
            raise ValidationError(_('End date must be after start date'))

        warning = cleaned_data.get('warning_threshold', 0)
        critical = cleaned_data.get('critical_threshold', 0)

        if warning > critical:
            raise ValidationError(_('Warning threshold must be less than critical threshold'))

        return cleaned_data


class RecurringExpenseForm(forms.ModelForm):
    """Form for creating/editing recurring expenses"""

    class Meta:
        model = RecurringExpense
        fields = [
            'name', 'description', 'store', 'category', 'expense_type',
            'vendor', 'frequency', 'amount', 'tax_rate', 'start_date',
            'end_date', 'next_occurrence', 'auto_approve', 'auto_pay',
            'payment_method', 'is_active'
        ]
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'rows': 3, 'class': 'form-control'}),
            'store': forms.Select(attrs={'class': 'form-control'}),
            'category': forms.Select(attrs={'class': 'form-control'}),
            'expense_type': forms.Select(attrs={'class': 'form-control'}),
            'vendor': forms.Select(attrs={'class': 'form-control'}),
            'frequency': forms.Select(attrs={'class': 'form-control'}),
            'amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'tax_rate': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'start_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'end_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'next_occurrence': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'payment_method': forms.Select(attrs={'class': 'form-control'}),
        }


class PettyCashForm(forms.ModelForm):
    """Form for creating/editing petty cash accounts"""

    class Meta:
        model = PettyCash
        fields = [
            'store', 'opening_balance', 'current_balance',
            'maximum_limit', 'minimum_balance', 'custodian', 'is_active'
        ]
        widgets = {
            'store': forms.Select(attrs={'class': 'form-control'}),
            'opening_balance': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'current_balance': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'maximum_limit': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'minimum_balance': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'custodian': forms.Select(attrs={'class': 'form-control'}),
        }


class PettyCashTransactionForm(forms.ModelForm):
    """Form for petty cash transactions"""

    class Meta:
        model = PettyCashTransaction
        fields = ['transaction_type', 'amount', 'expense', 'notes']
        widgets = {
            'transaction_type': forms.Select(attrs={'class': 'form-control'}),
            'amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'expense': forms.Select(attrs={'class': 'form-control'}),
            'notes': forms.Textarea(attrs={'rows': 3, 'class': 'form-control'}),
        }


class ReimbursementForm(forms.ModelForm):
    """Form for creating employee reimbursement claims"""

    class Meta:
        model = EmployeeReimbursement
        fields = [
            'employee', 'store', 'claim_date', 'description',
            'total_amount', 'status', 'notes'
        ]
        widgets = {
            'employee': forms.Select(attrs={'class': 'form-control'}),
            'store': forms.Select(attrs={'class': 'form-control'}),
            'claim_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'description': forms.Textarea(attrs={'rows': 3, 'class': 'form-control'}),
            'total_amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'status': forms.Select(attrs={'class': 'form-control'}),
            'notes': forms.Textarea(attrs={'rows': 3, 'class': 'form-control'}),
        }


class ReimbursementItemForm(forms.ModelForm):
    """Form for reimbursement items"""

    class Meta:
        model = ReimbursementItem
        fields = [
            'category', 'description', 'expense_date',
            'amount', 'receipt_number'
        ]
        widgets = {
            'category': forms.Select(attrs={'class': 'form-control'}),
            'description': forms.TextInput(attrs={'class': 'form-control'}),
            'expense_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'receipt_number': forms.TextInput(attrs={'class': 'form-control'}),
        }


class ExpenseAttachmentForm(forms.ModelForm):
    """Form for uploading expense attachments"""

    class Meta:
        model = ExpenseAttachment
        fields = ['attachment_type', 'file', 'description']
        widgets = {
            'attachment_type': forms.Select(attrs={'class': 'form-control'}),
            'file': forms.FileInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'rows': 2, 'class': 'form-control'}),
        }


class ExpenseSplitForm(forms.ModelForm):
    """Form for splitting expenses across stores"""

    class Meta:
        model = ExpenseSplit
        fields = ['store', 'allocation_percentage', 'notes']
        widgets = {
            'store': forms.Select(attrs={'class': 'form-control'}),
            'allocation_percentage': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'min': '0',
                'max': '100'
            }),
            'notes': forms.Textarea(attrs={'rows': 2, 'class': 'form-control'}),
        }


# Formsets for inline editing
from django.forms import inlineformset_factory

ReimbursementItemFormSet = inlineformset_factory(
    EmployeeReimbursement,
    ReimbursementItem,
    form=ReimbursementItemForm,
    extra=1,
    can_delete=True
)

ExpenseSplitFormSet = inlineformset_factory(
    Expense,
    ExpenseSplit,
    form=ExpenseSplitForm,
    extra=1,
    can_delete=True,
    max_num=10
)