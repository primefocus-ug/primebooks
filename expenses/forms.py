from django import forms
from .models import Expense, Budget
from taggit.forms import TagWidget
from django.utils import timezone


class ExpenseForm(forms.ModelForm):
    class Meta:
        model = Expense
        fields = ['amount', 'description', 'date', 'tags', 'receipt', 'notes']
        widgets = {
            'amount': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': '0.00',
                'autofocus': True,
                'step': '0.01',
                'id': 'id_amount'
            }),
            'description': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Quick description',
                'id': 'id_description'
            }),
            'date': forms.DateInput(attrs={
                'class': 'form-control',
                'type': 'date',
                'id': 'id_date'
            }),
            'tags': TagWidget(attrs={
                'class': 'form-control',
                'placeholder': 'Add tags (comma-separated)',
                'id': 'id_tags'
            }),
            'receipt': forms.FileInput(attrs={
                'class': 'form-control',
                'accept': 'image/*,.pdf',
                'id': 'id_receipt'
            }),
            'notes': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 2,
                'placeholder': 'Optional notes',
                'id': 'id_notes'
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Set today as default
        if not self.instance.pk:
            self.fields['date'].initial = timezone.now().date()


class BudgetForm(forms.ModelForm):
    class Meta:
        model = Budget
        fields = ['name', 'amount', 'period', 'tags', 'alert_threshold', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'period': forms.Select(attrs={'class': 'form-control'}),
            'tags': TagWidget(attrs={'class': 'form-control'}),
            'alert_threshold': forms.NumberInput(attrs={'class': 'form-control', 'min': '1', 'max': '100'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class ExpenseFilterForm(forms.Form):
    PERIOD_CHOICES = [
        ('', 'All Time'),
        ('today', 'Today'),
        ('week', 'This Week'),
        ('fortnight', 'Last 2 Weeks'),
        ('month', 'This Month'),
        ('quarter', 'This Quarter'),
        ('6months', 'Last 6 Months'),
        ('year', 'This Year'),
        ('custom', 'Custom Range'),
    ]

    period = forms.ChoiceField(
        choices=PERIOD_CHOICES,
        required=False,
        widget=forms.Select(attrs={'class': 'form-control', 'id': 'id_period'})
    )
    start_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'})
    )
    end_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'})
    )
    tags = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Filter by tags'})
    )
    min_amount = forms.DecimalField(
        required=False,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Min'})
    )
    max_amount = forms.DecimalField(
        required=False,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Max'})
    )