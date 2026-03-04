from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from .models import Expense, Budget, CURRENCY_CHOICES
from taggit.forms import TagWidget


# ---------------------------------------------------------------------------
# Expense form
# ---------------------------------------------------------------------------

class ExpenseForm(forms.ModelForm):
    class Meta:
        model = Expense
        fields = [
            'amount', 'currency', 'exchange_rate',
            'description', 'vendor',
            'date', 'tags', 'payment_method',
            'receipt', 'notes',
            'is_recurring', 'recurrence_interval', 'next_recurrence_date',
            'is_important',
        ]
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'}),
            'next_recurrence_date': forms.DateInput(attrs={'type': 'date'}),
            'tags': TagWidget(),
            'notes': forms.Textarea(attrs={'rows': 3}),
        }
        help_texts = {
            'exchange_rate': 'Set to 1 if the amount is already in your base currency.',
            'receipt': 'Upload a receipt image — amounts will be auto-detected via OCR.',
            'recurrence_interval': 'Only required when "Is recurring" is checked.',
        }

    def clean(self):
        cleaned = super().clean()
        is_recurring = cleaned.get('is_recurring')
        recurrence_interval = cleaned.get('recurrence_interval')
        next_recurrence_date = cleaned.get('next_recurrence_date')

        if is_recurring:
            if not recurrence_interval:
                self.add_error(
                    'recurrence_interval',
                    'Recurrence interval is required for recurring expenses.',
                )
            if not next_recurrence_date:
                self.add_error(
                    'next_recurrence_date',
                    'Next recurrence date is required for recurring expenses.',
                )
            elif next_recurrence_date <= timezone.now().date():
                self.add_error(
                    'next_recurrence_date',
                    'Next recurrence date must be in the future.',
                )

        exchange_rate = cleaned.get('exchange_rate')
        if exchange_rate is not None and exchange_rate <= 0:
            self.add_error('exchange_rate', 'Exchange rate must be greater than zero.')

        return cleaned


# ---------------------------------------------------------------------------
# Budget form
# ---------------------------------------------------------------------------

class BudgetForm(forms.ModelForm):
    class Meta:
        model = Budget
        fields = ['name', 'amount', 'period', 'currency', 'tags', 'alert_threshold', 'is_active']
        widgets = {
            'tags': TagWidget(),
        }
        help_texts = {
            'currency': 'Leave blank to track across all currencies (using base-currency amounts).',
            'alert_threshold': 'You will be alerted when spending reaches this % of the budget.',
        }


# ---------------------------------------------------------------------------
# Expense filter form — with validation
# ---------------------------------------------------------------------------

class ExpenseFilterForm(forms.Form):
    search = forms.CharField(required=False, max_length=200)
    tags = forms.CharField(required=False, max_length=500)
    payment_method = forms.ChoiceField(
        required=False,
        choices=[('', 'All Methods')] + list(Expense.PAYMENT_METHODS),
    )
    currency = forms.ChoiceField(
        required=False,
        choices=[('', 'All Currencies')] + list(CURRENCY_CHOICES),
    )
    date_from = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'type': 'date'}),
    )
    date_to = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'type': 'date'}),
    )
    min_amount = forms.DecimalField(required=False, min_value=0)
    max_amount = forms.DecimalField(required=False, min_value=0)
    period = forms.ChoiceField(
        required=False,
        choices=[
            ('', 'Custom / All'),
            ('today', 'Today'),
            ('week', 'This Week'),
            ('month', 'This Month'),
            ('quarter', 'This Quarter'),
            ('year', 'This Year'),
        ],
    )
    status = forms.ChoiceField(
        required=False,
        choices=[('', 'All Statuses')] + list(Expense.STATUS_CHOICES),
    )

    def clean(self):
        cleaned = super().clean()

        date_from = cleaned.get('date_from')
        date_to = cleaned.get('date_to')
        if date_from and date_to and date_from > date_to:
            raise ValidationError(
                '"Date from" cannot be later than "Date to". Please correct the date range.'
            )

        min_amount = cleaned.get('min_amount')
        max_amount = cleaned.get('max_amount')
        if min_amount is not None and max_amount is not None and min_amount > max_amount:
            raise ValidationError(
                '"Min amount" cannot be greater than "Max amount".'
            )

        return cleaned


# ---------------------------------------------------------------------------
# Bulk action form
# ---------------------------------------------------------------------------

BULK_ACTIONS = [
    ('', '— Select Action —'),
    ('submit', '📤 Submit for Approval'),
    ('approve', '✅ Approve'),
    ('reject', '❌ Reject'),
    ('tag', '🏷️ Add Tag'),
    ('export_csv', '📄 Export as CSV'),
    ('export_pdf', '🖨️ Export as PDF'),
    ('delete', '🗑️ Delete'),
]


class BulkExpenseActionForm(forms.Form):
    """
    Submitted alongside a list of selected expense IDs.

    Usage in view:
        form = BulkExpenseActionForm(request.POST)
        if form.is_valid():
            action = form.cleaned_data['action']
            ids    = form.cleaned_data['expense_ids']  # list[int]
            tag    = form.cleaned_data.get('tag_name')
            comment = form.cleaned_data.get('comment')
    """
    action = forms.ChoiceField(choices=BULK_ACTIONS)
    # Comma-separated or multi-value hidden field populated by JS checkboxes
    expense_ids = forms.CharField(widget=forms.HiddenInput)
    # Optional fields used by specific actions
    tag_name = forms.CharField(required=False, max_length=100)
    comment = forms.CharField(
        required=False,
        max_length=500,
        widget=forms.Textarea(attrs={'rows': 2, 'placeholder': 'Optional comment / reason'}),
    )

    def clean_expense_ids(self):
        raw = self.cleaned_data.get('expense_ids', '')
        try:
            ids = [int(x.strip()) for x in raw.split(',') if x.strip()]
        except ValueError:
            raise ValidationError('Invalid expense selection.')
        if not ids:
            raise ValidationError('No expenses selected.')
        return ids

    def clean(self):
        cleaned = super().clean()
        action = cleaned.get('action')
        tag_name = cleaned.get('tag_name', '').strip()

        if action == 'tag' and not tag_name:
            self.add_error('tag_name', 'A tag name is required for the "Add Tag" action.')

        if action == 'reject' and not cleaned.get('comment', '').strip():
            self.add_error('comment', 'A rejection reason is required.')

        return cleaned