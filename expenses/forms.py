from django import forms
from .models import Expense, Budget
from taggit.forms import TagWidget


class ExpenseForm(forms.ModelForm):
    class Meta:
        model = Expense
        fields = ['amount', 'description', 'date', 'tags', 'payment_method', 'receipt', 'notes', 'is_recurring', 'is_important']
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'}),
            'tags': TagWidget(),
        }


class BudgetForm(forms.ModelForm):
    class Meta:
        model = Budget
        fields = ['name', 'amount', 'period', 'tags', 'alert_threshold', 'is_active']
        widgets = {
            'tags': TagWidget(),
        }


class ExpenseFilterForm(forms.Form):
    search = forms.CharField(required=False)
    tags = forms.CharField(required=False)
    payment_method = forms.CharField(required=False)
    date_from = forms.DateField(required=False)
    date_to = forms.DateField(required=False)
    min_amount = forms.DecimalField(required=False)
    max_amount = forms.DecimalField(required=False)
    period = forms.CharField(required=False)