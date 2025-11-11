from django import forms
from django.forms import inlineformset_factory, modelformset_factory, BaseInlineFormSet, BaseModelFormSet
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.db.models import Q
from decimal import Decimal
import json

from .models import (
    ChartOfAccounts, JournalEntry, JournalEntryLine, BankAccount,
    Transaction, Budget, BudgetLine, TaxCode, FixedAsset,
    BankReconciliation, RecurringJournalEntry, Currency, ExchangeRate,
    Dimension, DimensionValue, FiscalYear, FiscalPeriod, Journal,
    AssetCategory, BankReconciliationItem, BankStatement, FinancialReport,ExpenseCategory,Expense
)


# ============================================
# CUSTOM WIDGETS & FIELDS
# ============================================

class CurrencyAmountWidget(forms.TextInput):
    """Custom widget for currency amounts"""

    def __init__(self, *args, **kwargs):
        self.currency_code = kwargs.pop('currency_code', 'USD')
        super().__init__(*args, **kwargs)

    def render(self, name, value, attrs=None, renderer=None):
        if attrs is None:
            attrs = {}
        attrs.update({
            'class': 'currency-amount',
            'data-currency': self.currency_code,
            'step': '0.01',
            'min': '0'
        })
        return super().render(name, value, attrs, renderer)


class DimensionSelectMultiple(forms.CheckboxSelectMultiple):
    """Custom widget for dimension selection with grouping"""
    template_name = 'finance/widgets/dimension_select.html'
    option_template_name = 'finance/widgets/dimension_option.html'


class DateRangeWidget(forms.MultiWidget):
    """Widget for date range selection"""

    def __init__(self, attrs=None):
        widgets = [
            forms.DateInput(attrs={'type': 'date', 'class': 'date-start'}),
            forms.DateInput(attrs={'type': 'date', 'class': 'date-end'})
        ]
        super().__init__(widgets, attrs)

    def decompress(self, value):
        if value:
            return [value.get('start'), value.get('end')]
        return [None, None]


class DateRangeField(forms.MultiValueField):
    """Field for date range"""
    widget = DateRangeWidget

    def __init__(self, *args, **kwargs):
        fields = (
            forms.DateField(),
            forms.DateField()
        )
        super().__init__(fields, *args, **kwargs)

    def compress(self, data_list):
        if data_list:
            return {'start': data_list[0], 'end': data_list[1]}
        return None


# ============================================
# BASE FORM CLASSES
# ============================================

class FinanceBaseForm(forms.ModelForm):
    """Base form for all finance forms with common functionality"""

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop('request', None)
        super().__init__(*args, **kwargs)
        self._add_form_control_class()
        self._set_currency_fields()

    def _add_form_control_class(self):
        """Add Bootstrap form-control class to all fields"""
        for field_name, field in self.fields.items():
            if (isinstance(field.widget, (forms.TextInput, forms.NumberInput,
                                          forms.EmailInput, forms.DateInput,
                                          forms.Select, forms.Textarea))):
                field.widget.attrs.update({'class': 'form-control'})
            elif isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.update({'class': 'form-check-input'})

    def _set_currency_fields(self):
        """Configure currency-related fields"""
        currency_fields = ['amount', 'debit_amount', 'credit_amount', 'rate',
                           'purchase_cost', 'salvage_value', 'opening_balance']
        for field_name in currency_fields:
            if field_name in self.fields:
                self.fields[field_name].widget.attrs.update({
                    'step': '0.01',
                    'min': '0'
                })


class AuditForm(FinanceBaseForm):
    """Form with audit trail support"""

    def save(self, commit=True, user=None):
        instance = super().save(commit=False)
        if user and hasattr(instance, 'created_by') and not instance.pk:
            instance.created_by = user
        if commit:
            instance.save()
            self.save_m2m()
        return instance


# ============================================
# CURRENCY & EXCHANGE RATE FORMS
# ============================================

class CurrencyForm(AuditForm):
    """Advanced Currency Form"""

    class Meta:
        model = Currency
        fields = ['code', 'name', 'symbol', 'decimal_places', 'is_base', 'is_active']
        widgets = {
            'code': forms.TextInput(attrs={'style': 'text-transform: uppercase', 'maxlength': 3}),
            'name': forms.TextInput(attrs={'placeholder': 'e.g., US Dollar'}),
            'symbol': forms.TextInput(attrs={'placeholder': 'e.g., $'}),
        }

    def clean_code(self):
        code = self.cleaned_data.get('code', '').upper().strip()
        if len(code) != 3:
            raise ValidationError(_('Currency code must be exactly 3 characters'))
        return code

    def clean_is_base(self):
        is_base = self.cleaned_data.get('is_base')
        if is_base and not self.cleaned_data.get('is_active'):
            raise ValidationError(_('Base currency must be active'))
        return is_base


class ExchangeRateForm(AuditForm):
    """Advanced Exchange Rate Form"""

    class Meta:
        model = ExchangeRate
        fields = ['from_currency', 'to_currency', 'rate', 'rate_date', 'rate_type', 'source', 'is_active']
        widgets = {
            'rate_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'rate': forms.NumberInput(attrs={'step': '0.0000000001', 'min': '0'}),
        }

    def clean(self):
        cleaned_data = super().clean()
        from_currency = cleaned_data.get('from_currency')
        to_currency = cleaned_data.get('to_currency')
        rate_date = cleaned_data.get('rate_date')
        rate_type = cleaned_data.get('rate_type')

        if from_currency and to_currency:
            if from_currency == to_currency:
                raise ValidationError(_('From and To currencies cannot be the same'))

            # Check for duplicate rate
            if self.instance.pk:
                existing = ExchangeRate.objects.filter(
                    from_currency=from_currency,
                    to_currency=to_currency,
                    rate_date=rate_date,
                    rate_type=rate_type
                ).exclude(pk=self.instance.pk)
            else:
                existing = ExchangeRate.objects.filter(
                    from_currency=from_currency,
                    to_currency=to_currency,
                    rate_date=rate_date,
                    rate_type=rate_type
                )

            if existing.exists():
                raise ValidationError(_('Exchange rate for this currency pair and date already exists'))

        return cleaned_data

    def clean_rate(self):
        rate = self.cleaned_data.get('rate')
        if rate and rate <= 0:
            raise ValidationError(_('Exchange rate must be greater than 0'))
        return rate


# ============================================
# EXPENSE MANAGEMENT FORMS
# ============================================

class ExpenseCategoryForm(forms.ModelForm):
    class Meta:
        model = ExpenseCategory
        fields = ['code', 'name', 'description', 'parent', 'gl_account', 'is_active']
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3}),
        }


class ExpenseForm(forms.ModelForm):
    class Meta:
        model = Expense
        fields = [
            'date', 'category', 'amount', 'currency', 'description',
            'payment_method', 'paid_from_account', 'receipt_number',
            'receipt_date', 'vendor', 'dimension_values'
        ]
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'}),
            'receipt_date': forms.DateInput(attrs={'type': 'date'}),
            'description': forms.Textarea(attrs={'rows': 3, 'placeholder': 'Describe what was purchased'}),
            'dimension_values': forms.CheckboxSelectMultiple(),
        }

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop('request', None)
        super().__init__(*args, **kwargs)

        # Filter active categories and accounts
        self.fields['category'].queryset = ExpenseCategory.objects.filter(is_active=True)
        self.fields['paid_from_account'].queryset = BankAccount.objects.filter(is_active=True)

        if not self.instance.pk:
            self.fields['date'].initial = timezone.now().date()
            self.fields['receipt_date'].initial = timezone.now().date()

    def clean_amount(self):
        amount = self.cleaned_data.get('amount')
        if amount and amount <= 0:
            raise forms.ValidationError('Amount must be greater than zero.')
        return amount


class QuickExpenseForm(forms.ModelForm):
    """Simplified form for cashier quick expenses"""

    class Meta:
        model = Expense
        fields = ['category', 'amount', 'description']
        widgets = {
            'description': forms.TextInput(attrs={'placeholder': 'Brief description'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['category'].queryset = ExpenseCategory.objects.filter(is_active=True)

class ExchangeRateBulkForm(forms.Form):
    """Form for bulk exchange rate upload"""
    rate_date = forms.DateField(widget=forms.DateInput(attrs={'type': 'date'}))
    rate_type = forms.ChoiceField(choices=ExchangeRate._meta.get_field('rate_type').choices)
    source = forms.ChoiceField(choices=ExchangeRate._meta.get_field('source').choices)
    csv_file = forms.FileField(help_text=_('CSV file with columns: from_currency,to_currency,rate'))


# ============================================
# DIMENSION FORMS
# ============================================

class DimensionForm(AuditForm):
    """Advanced Dimension Form"""

    class Meta:
        model = Dimension
        fields = ['code', 'name', 'description', 'dimension_type', 'parent', 'require_for_posting', 'is_active']
        widgets = {
            'code': forms.TextInput(attrs={'style': 'text-transform: uppercase'}),
            'description': forms.Textarea(
                attrs={'rows': 3, 'placeholder': _('Describe the purpose of this dimension')}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Exclude self from parent choices to prevent circular references
        if self.instance.pk:
            self.fields['parent'].queryset = Dimension.objects.exclude(pk=self.instance.pk)


class DimensionValueForm(AuditForm):
    """Advanced Dimension Value Form"""

    class Meta:
        model = DimensionValue
        fields = ['dimension', 'code', 'name', 'description', 'parent', 'manager',
                  'budget_allocation_percentage', 'is_active']
        widgets = {
            'code': forms.TextInput(attrs={'style': 'text-transform: uppercase'}),
            'description': forms.Textarea(attrs={'rows': 2}),
            'budget_allocation_percentage': forms.NumberInput(attrs={'step': '0.01', 'min': '0', 'max': '100'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Filter parent choices to same dimension
        if 'dimension' in self.data:
            dimension_id = self.data.get('dimension')
            self.fields['parent'].queryset = DimensionValue.objects.filter(dimension_id=dimension_id)
        elif self.instance.pk and self.instance.dimension:
            self.fields['parent'].queryset = DimensionValue.objects.filter(dimension=self.instance.dimension)
        else:
            self.fields['parent'].queryset = DimensionValue.objects.none()

    def clean_budget_allocation_percentage(self):
        percentage = self.cleaned_data.get('budget_allocation_percentage', 0)
        if percentage < 0 or percentage > 100:
            raise ValidationError(_('Budget allocation percentage must be between 0 and 100'))
        return percentage


# ============================================
# CHART OF ACCOUNTS FORMS
# ============================================

class ChartOfAccountsForm(AuditForm):
    """Advanced Chart of Accounts Form"""

    class Meta:
        model = ChartOfAccounts
        fields = [
            'code', 'name', 'description', 'account_type', 'parent', 'is_header',
            'currency', 'allow_multi_currency', 'revaluation_account',
            'require_dimensions', 'allow_direct_posting', 'is_reconcilable',
            'is_control_account', 'tax_code', 'is_active'
        ]
        widgets = {
            'code': forms.TextInput(attrs={'style': 'text-transform: uppercase'}),
            'description': forms.Textarea(attrs={'rows': 3}),
            'require_dimensions': forms.CheckboxSelectMultiple(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Filter parent accounts to prevent circular references
        if self.instance.pk:
            self.fields['parent'].queryset = ChartOfAccounts.objects.exclude(pk=self.instance.pk)
            self.fields['revaluation_account'].queryset = ChartOfAccounts.objects.exclude(pk=self.instance.pk)

    def clean_code(self):
        code = self.cleaned_data.get('code', '').upper().strip()
        return code

    def clean(self):
        cleaned_data = super().clean()
        is_header = cleaned_data.get('is_header')
        parent = cleaned_data.get('parent')

        if is_header and parent and not parent.is_header:
            raise ValidationError(_('Header accounts can only have other header accounts as parents'))

        return cleaned_data


class AccountImportForm(forms.Form):
    """Form for importing accounts from CSV"""
    csv_file = forms.FileField(help_text=_('CSV file with account structure'))
    delimiter = forms.ChoiceField(choices=[(',', 'Comma'), (';', 'Semicolon'), ('\t', 'Tab')], initial=',')
    parent_account = forms.ModelChoiceField(
        queryset=ChartOfAccounts.objects.filter(is_header=True),
        required=False,
        help_text=_('Parent account for imported accounts')
    )


# ============================================
# JOURNAL ENTRY FORMS
# ============================================

class JournalEntryForm(AuditForm):
    """Advanced Journal Entry Form"""

    class Meta:
        model = JournalEntry
        fields = [
            'journal', 'entry_date', 'posting_date', 'fiscal_year', 'fiscal_period',
            'reference', 'description', 'notes', 'currency', 'exchange_rate',
            'requires_approval'
        ]
        widgets = {
            'entry_date': forms.DateInput(attrs={'type': 'date'}),
            'posting_date': forms.DateInput(attrs={'type': 'date'}),
            'description': forms.Textarea(attrs={'rows': 2, 'placeholder': _('Brief description of the transaction')}),
            'notes': forms.Textarea(attrs={'rows': 3, 'placeholder': _('Additional notes or context')}),
            'exchange_rate': forms.NumberInput(attrs={'step': '0.0000000001', 'min': '0'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Set default dates
        if not self.instance.pk:
            self.fields['entry_date'].initial = timezone.now().date()
            self.fields['posting_date'].initial = timezone.now().date()

        # Filter periods based on selected fiscal year
        if 'fiscal_year' in self.data:
            try:
                fiscal_year_id = self.data.get('fiscal_year')
                self.fields['fiscal_period'].queryset = FiscalPeriod.objects.filter(fiscal_year_id=fiscal_year_id)
            except (ValueError, TypeError):
                pass
        elif self.instance.pk and self.instance.fiscal_year_id:
            self.fields['fiscal_period'].queryset = FiscalPeriod.objects.filter(fiscal_year=self.instance.fiscal_year)
        else:
            self.fields['fiscal_period'].queryset = FiscalPeriod.objects.none()

    def clean(self):
        cleaned_data = super().clean()
        entry_date = cleaned_data.get('entry_date')
        posting_date = cleaned_data.get('posting_date')
        fiscal_period = cleaned_data.get('fiscal_period')

        if entry_date and posting_date and entry_date > posting_date:
            raise ValidationError(_('Entry date cannot be after posting date'))

        if fiscal_period and entry_date:
            if not (fiscal_period.start_date <= entry_date <= fiscal_period.end_date):
                raise ValidationError(_('Entry date must be within the selected fiscal period'))

        return cleaned_data


class JournalEntryLineForm(AuditForm):
    """Advanced Journal Entry Line Form"""

    class Meta:
        model = JournalEntryLine
        fields = [
            'account', 'description', 'currency', 'debit_amount', 'credit_amount',
            'dimension_values', 'tax_code', 'quantity', 'unit_price'
        ]
        widgets = {
            'description': forms.TextInput(attrs={'placeholder': _('Line item description')}),
            'debit_amount': forms.NumberInput(attrs={'step': '0.01', 'min': '0'}),
            'credit_amount': forms.NumberInput(attrs={'step': '0.01', 'min': '0'}),
            'dimension_values': forms.CheckboxSelectMultiple(attrs={'class': 'form-check-input'}),
            'quantity': forms.NumberInput(attrs={'step': '0.0001', 'min': '0'}),
            'unit_price': forms.NumberInput(attrs={'step': '0.0001', 'min': '0'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Filter accounts that allow direct posting
        self.fields['account'].queryset = ChartOfAccounts.objects.filter(
            allow_direct_posting=True, is_header=False, is_active=True
        )

    def clean(self):
        cleaned_data = super().clean()
        debit_amount = cleaned_data.get('debit_amount', 0)
        credit_amount = cleaned_data.get('credit_amount', 0)
        account = cleaned_data.get('account')
        dimension_values = cleaned_data.get('dimension_values', [])
        quantity = cleaned_data.get('quantity')
        unit_price = cleaned_data.get('unit_price')

        # Validate debit/credit
        if debit_amount and credit_amount:
            raise ValidationError(_('Cannot have both debit and credit amounts'))

        if not debit_amount and not credit_amount:
            raise ValidationError(_('Must have either debit or credit amount'))

        # Validate account requirements
        if account:
            required_dims = account.require_dimensions.all()
            provided_dims = {dv.dimension for dv in dimension_values}

            for dim in required_dims:
                if dim not in provided_dims:
                    raise ValidationError(_('Dimension "%(dim)s" is required for account %(account)s') % {
                        'dim': dim.name, 'account': account.code
                    })

        # Validate quantity and unit price
        if (quantity and not unit_price) or (unit_price and not quantity):
            raise ValidationError(_('Both quantity and unit price must be provided together'))

        return cleaned_data


class JournalEntryLineFormSet(BaseInlineFormSet):
    """Custom formset for journal entry lines with balance validation"""

    def clean(self):
        super().clean()

        if any(self.errors):
            return

        total_debit = Decimal('0.00')
        total_credit = Decimal('0.00')

        for form in self.forms:
            if not form.cleaned_data or form.cleaned_data.get('DELETE'):
                continue

            debit = form.cleaned_data.get('debit_amount', 0)
            credit = form.cleaned_data.get('credit_amount', 0)

            total_debit += debit
            total_credit += credit

        if abs(total_debit - total_credit) > Decimal('0.01'):
            raise ValidationError(
                _('Journal entry is not balanced. Total debit: %(debit)s, Total credit: %(credit)s') % {
                    'debit': total_debit, 'credit': total_credit
                }
            )


JournalEntryLineFormSet = inlineformset_factory(
    JournalEntry,
    JournalEntryLine,
    form=JournalEntryLineForm,
    formset=JournalEntryLineFormSet,
    extra=3,
    can_delete=True,
    min_num=2,
    validate_min=True
)


# ============================================
# BUDGET FORMS
# ============================================

class BudgetForm(AuditForm):
    """Advanced Budget Form"""

    class Meta:
        model = Budget
        fields = [
            'name', 'code', 'description', 'budget_type', 'fiscal_year',
            'start_date', 'end_date', 'scenario', 'is_baseline',
            'allow_overrun', 'alert_threshold'
        ]
        widgets = {
            'start_date': forms.DateInput(attrs={'type': 'date'}),
            'end_date': forms.DateInput(attrs={'type': 'date'}),
            'description': forms.Textarea(attrs={'rows': 3}),
            'alert_threshold': forms.NumberInput(attrs={'step': '0.01', 'min': '0', 'max': '100'}),
        }

    def clean(self):
        cleaned_data = super().clean()
        start_date = cleaned_data.get('start_date')
        end_date = cleaned_data.get('end_date')
        fiscal_year = cleaned_data.get('fiscal_year')

        if start_date and end_date and start_date > end_date:
            raise ValidationError(_('Start date cannot be after end date'))

        if fiscal_year and start_date and end_date:
            if start_date < fiscal_year.start_date or end_date > fiscal_year.end_date:
                raise ValidationError(_('Budget period must be within fiscal year'))

        return cleaned_data


class BudgetLineForm(AuditForm):
    """Advanced Budget Line Form"""

    class Meta:
        model = BudgetLine
        fields = ['account', 'amount', 'currency', 'description', 'dimension_values', 'notes']
        widgets = {
            'amount': forms.NumberInput(attrs={'step': '0.01', 'min': '0'}),
            'description': forms.TextInput(attrs={'placeholder': _('Budget line description')}),
            'notes': forms.Textarea(attrs={'rows': 2}),
            'dimension_values': forms.CheckboxSelectMultiple(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Filter to expense and revenue accounts for budgeting
        self.fields['account'].queryset = ChartOfAccounts.objects.filter(
            account_type__in=['EXPENSE', 'REVENUE', 'COGS'],
            is_active=True
        )


class BudgetLineFormSet(BaseInlineFormSet):
    """Custom formset for budget lines with validation"""

    def clean(self):
        super().clean()

        accounts_used = set()

        for form in self.forms:
            if not form.cleaned_data or form.cleaned_data.get('DELETE'):
                continue

            account = form.cleaned_data.get('account')
            if account in accounts_used:
                raise ValidationError(_('Duplicate account: %(account)s') % {'account': account.code})
            accounts_used.add(account)


BudgetLineFormSet = inlineformset_factory(
    Budget,
    BudgetLine,
    form=BudgetLineForm,
    formset=BudgetLineFormSet,
    extra=5,
    can_delete=True,
    min_num=1,
    validate_min=True
)


# ============================================
# BANKING FORMS
# ============================================

class BankAccountForm(AuditForm):
    """Advanced Bank Account Form"""

    class Meta:
        model = BankAccount
        fields = [
            'account_number', 'account_name', 'bank_name', 'bank_branch',
            'swift_code', 'iban', 'gl_account', 'currency', 'opening_balance',
            'overdraft_limit', 'is_default', 'enable_bank_feed', 'is_active'
        ]
        widgets = {
            'opening_balance': forms.NumberInput(attrs={'step': '0.01'}),
            'overdraft_limit': forms.NumberInput(attrs={'step': '0.01', 'min': '0'}),
        }

    def clean_account_number(self):
        account_number = self.cleaned_data.get('account_number', '').strip()
        return account_number


class TransactionForm(AuditForm):
    """Advanced Transaction Form"""

    class Meta:
        model = Transaction
        fields = [
            'bank_account', 'transaction_date', 'value_date', 'transaction_type',
            'amount', 'currency', 'description', 'reference', 'payee'
        ]
        widgets = {
            'transaction_date': forms.DateInput(attrs={'type': 'date'}),
            'value_date': forms.DateInput(attrs={'type': 'date'}),
            'amount': forms.NumberInput(attrs={'step': '0.01', 'min': '0'}),
            'description': forms.TextInput(attrs={'placeholder': _('Transaction description')}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.pk:
            self.fields['transaction_date'].initial = timezone.now().date()
            self.fields['value_date'].initial = timezone.now().date()

    def clean(self):
        cleaned_data = super().clean()
        transaction_date = cleaned_data.get('transaction_date')
        value_date = cleaned_data.get('value_date')

        if transaction_date and value_date and transaction_date > value_date:
            raise ValidationError(_('Transaction date cannot be after value date'))

        return cleaned_data


class BankReconciliationForm(AuditForm):
    """Advanced Bank Reconciliation Form"""

    class Meta:
        model = BankReconciliation
        fields = [
            'bank_account', 'reconciliation_date', 'start_date', 'end_date',
            'closing_balance_book', 'closing_balance_bank', 'notes'
        ]
        widgets = {
            'reconciliation_date': forms.DateInput(attrs={'type': 'date'}),
            'start_date': forms.DateInput(attrs={'type': 'date'}),
            'end_date': forms.DateInput(attrs={'type': 'date'}),
            'closing_balance_book': forms.NumberInput(attrs={'step': '0.01'}),
            'closing_balance_bank': forms.NumberInput(attrs={'step': '0.01'}),
            'notes': forms.Textarea(attrs={'rows': 3}),
        }

    def clean(self):
        cleaned_data = super().clean()
        start_date = cleaned_data.get('start_date')
        end_date = cleaned_data.get('end_date')

        if start_date and end_date and start_date > end_date:
            raise ValidationError(_('Start date cannot be after end date'))

        return cleaned_data


class BankReconciliationItemForm(forms.ModelForm):
    """Bank Reconciliation Item Form"""

    class Meta:
        model = BankReconciliationItem
        fields = ['item_type', 'transaction_date', 'description', 'amount', 'book_transaction', 'notes']
        widgets = {
            'transaction_date': forms.DateInput(attrs={'type': 'date'}),
            'amount': forms.NumberInput(attrs={'step': '0.01'}),
            'notes': forms.Textarea(attrs={'rows': 2}),
        }


# ============================================
# FIXED ASSET FORMS
# ============================================

class AssetCategoryForm(AuditForm):
    """Advanced Asset Category Form"""

    class Meta:
        model = AssetCategory
        fields = [
            'code', 'name', 'description', 'asset_account', 'accumulated_depreciation_account',
            'depreciation_expense_account', 'gain_loss_account', 'default_depreciation_method',
            'default_useful_life_years', 'default_salvage_percentage', 'is_active'
        ]
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3}),
            'default_salvage_percentage': forms.NumberInput(attrs={'step': '0.01', 'min': '0', 'max': '100'}),
        }


class FixedAssetForm(AuditForm):
    """Advanced Fixed Asset Form"""

    class Meta:
        model = FixedAsset
        fields = [
            'asset_number', 'name', 'description', 'category', 'purchase_date',
            'purchase_cost', 'currency', 'vendor', 'invoice_number', 'location',
            'dimension_values', 'assigned_to', 'depreciation_method',
            'useful_life_years', 'useful_life_months', 'salvage_value',
            'depreciation_start_date', 'total_units'
        ]
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3}),
            'purchase_date': forms.DateInput(attrs={'type': 'date'}),
            'depreciation_start_date': forms.DateInput(attrs={'type': 'date'}),
            'purchase_cost': forms.NumberInput(attrs={'step': '0.01', 'min': '0'}),
            'salvage_value': forms.NumberInput(attrs={'step': '0.01', 'min': '0'}),
            'dimension_values': forms.CheckboxSelectMultiple(attrs={'class': 'form-check-input'}),
            'total_units': forms.NumberInput(attrs={'min': '0'}),
        }

    def clean(self):
        cleaned_data = super().clean()
        purchase_date = cleaned_data.get('purchase_date')
        depreciation_start_date = cleaned_data.get('depreciation_start_date')
        purchase_cost = cleaned_data.get('purchase_cost', 0)
        salvage_value = cleaned_data.get('salvage_value', 0)

        if purchase_date and depreciation_start_date and depreciation_start_date < purchase_date:
            raise ValidationError(_('Depreciation start date cannot be before purchase date'))

        if salvage_value >= purchase_cost:
            raise ValidationError(_('Salvage value cannot be greater than or equal to purchase cost'))

        return cleaned_data


# ============================================
# TAX FORMS
# ============================================

class TaxCodeForm(AuditForm):
    """Advanced Tax Code Form"""

    class Meta:
        model = TaxCode
        fields = [
            'code', 'name', 'description', 'tax_type', 'rate',
            'tax_collected_account', 'tax_paid_account', 'is_compound',
            'effective_date', 'expiry_date', 'tax_authority',
            'filing_frequency', 'is_active'
        ]
        widgets = {
            'code': forms.TextInput(attrs={'style': 'text-transform: uppercase'}),
            'description': forms.Textarea(attrs={'rows': 3}),
            'effective_date': forms.DateInput(attrs={'type': 'date'}),
            'expiry_date': forms.DateInput(attrs={'type': 'date'}),
            'rate': forms.NumberInput(attrs={'step': '0.0001', 'min': '0', 'max': '100'}),
        }

    def clean(self):
        cleaned_data = super().clean()
        effective_date = cleaned_data.get('effective_date')
        expiry_date = cleaned_data.get('expiry_date')

        if effective_date and expiry_date and effective_date > expiry_date:
            raise ValidationError(_('Effective date cannot be after expiry date'))

        return cleaned_data


# ============================================
# RECURRING JOURNAL & AUTOMATION FORMS
# ============================================

class RecurringJournalEntryForm(AuditForm):
    """Advanced Recurring Journal Entry Form"""

    class Meta:
        model = RecurringJournalEntry
        fields = [
            'name', 'code', 'description', 'journal', 'frequency',
            'start_date', 'end_date', 'next_run_date', 'currency',
            'auto_post', 'is_active'
        ]
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3}),
            'start_date': forms.DateInput(attrs={'type': 'date'}),
            'end_date': forms.DateInput(attrs={'type': 'date'}),
            'next_run_date': forms.DateInput(attrs={'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.pk:
            self.fields['start_date'].initial = timezone.now().date()
            self.fields['next_run_date'].initial = timezone.now().date()

    def clean(self):
        cleaned_data = super().clean()
        start_date = cleaned_data.get('start_date')
        end_date = cleaned_data.get('end_date')
        next_run_date = cleaned_data.get('next_run_date')

        if start_date and next_run_date and next_run_date < start_date:
            raise ValidationError(_('Next run date cannot be before start date'))

        if end_date and next_run_date and next_run_date > end_date:
            raise ValidationError(_('Next run date cannot be after end date'))

        return cleaned_data


# ============================================
# FINANCIAL REPORTING FORMS
# ============================================

class FinancialReportForm(forms.ModelForm):
    """Financial Report Generation Form"""
    date_range = DateRangeField(required=False, label=_('Date Range'))
    as_of_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'type': 'date'}),
        label=_('As Of Date')
    )
    dimensions = forms.ModelMultipleChoiceField(
        queryset=Dimension.objects.filter(is_active=True),
        required=False,
        widget=forms.CheckboxSelectMultiple(attrs={'class': 'form-check-input'})
    )

    class Meta:
        model = FinancialReport
        fields = ['name', 'report_type', 'fiscal_period', 'as_of_date', 'is_final']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['fiscal_period'].required = False

    def clean(self):
        cleaned_data = super().clean()
        report_type = cleaned_data.get('report_type')
        fiscal_period = cleaned_data.get('fiscal_period')
        as_of_date = cleaned_data.get('as_of_date')
        date_range = cleaned_data.get('date_range')

        if report_type in ['BALANCE_SHEET', 'TRIAL_BALANCE'] and not as_of_date:
            raise ValidationError(_('As of date is required for balance sheet and trial balance reports'))

        if report_type in ['INCOME_STATEMENT', 'CASH_FLOW'] and not date_range:
            raise ValidationError(_('Date range is required for income statement and cash flow reports'))

        return cleaned_data


# ============================================
# BULK IMPORT & DATA MANAGEMENT FORMS
# ============================================

class BulkJournalEntryForm(forms.Form):
    """Form for bulk journal entry import"""
    journal = forms.ModelChoiceField(queryset=Journal.objects.filter(is_active=True))
    entry_date = forms.DateField(widget=forms.DateInput(attrs={'type': 'date'}))
    csv_file = forms.FileField(help_text=_('CSV file with journal entry lines'))
    auto_post = forms.BooleanField(required=False, initial=False)


class DataExportForm(forms.Form):
    """Form for data export"""
    MODEL_CHOICES = [
        ('ChartOfAccounts', 'Chart of Accounts'),
        ('JournalEntry', 'Journal Entries'),
        ('Transaction', 'Bank Transactions'),
        ('Budget', 'Budgets'),
        ('FixedAsset', 'Fixed Assets'),
    ]

    model_type = forms.ChoiceField(choices=MODEL_CHOICES)
    format = forms.ChoiceField(choices=[('csv', 'CSV'), ('json', 'JSON'), ('xlsx', 'Excel')])
    start_date = forms.DateField(required=False, widget=forms.DateInput(attrs={'type': 'date'}))
    end_date = forms.DateField(required=False, widget=forms.DateInput(attrs={'type': 'date'}))
    include_inactive = forms.BooleanField(required=False, initial=False)


# ============================================
# SEARCH & FILTER FORMS
# ============================================

class JournalEntrySearchForm(forms.Form):
    """Advanced Journal Entry Search Form"""
    journal = forms.ModelChoiceField(
        queryset=Journal.objects.filter(is_active=True),
        required=False
    )
    status = forms.MultipleChoiceField(
        choices=JournalEntry.STATUS_CHOICES,
        required=False,
        widget=forms.CheckboxSelectMultiple(attrs={'class': 'form-check-input'})
    )
    date_from = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'type': 'date'})
    )
    date_to = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'type': 'date'})
    )
    account = forms.ModelChoiceField(
        queryset=ChartOfAccounts.objects.filter(is_active=True),
        required=False
    )
    amount_min = forms.DecimalField(
        required=False,
        widget=forms.NumberInput(attrs={'step': '0.01', 'min': '0'})
    )
    amount_max = forms.DecimalField(
        required=False,
        widget=forms.NumberInput(attrs={'step': '0.01', 'min': '0'})
    )
    reference = forms.CharField(required=False, max_length=100)
    description = forms.CharField(required=False, max_length=500)


class TransactionSearchForm(forms.Form):
    """Bank Transaction Search Form"""
    bank_account = forms.ModelChoiceField(
        queryset=BankAccount.objects.filter(is_active=True),
        required=False
    )
    transaction_type = forms.MultipleChoiceField(
        choices=Transaction.TRANSACTION_TYPES,
        required=False,
        widget=forms.CheckboxSelectMultiple(attrs={'class': 'form-check-input'})
    )
    status = forms.MultipleChoiceField(
        choices=Transaction.STATUS_CHOICES,
        required=False,
        widget=forms.CheckboxSelectMultiple(attrs={'class': 'form-check-input'})
    )
    date_from = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'type': 'date'})
    )
    date_to = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'type': 'date'})
    )
    amount_min = forms.DecimalField(required=False)
    amount_max = forms.DecimalField(required=False)
    description = forms.CharField(required=False)