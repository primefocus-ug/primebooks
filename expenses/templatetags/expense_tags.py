from django import template
from django.db.models import Sum
from decimal import Decimal
from django.utils import timezone

register = template.Library()

@register.simple_tag
def query_transform(request, **kwargs):
    updated = request.GET.copy()
    for k, v in kwargs.items():
        updated[k] = v
    return updated.urlencode()


@register.filter
def currency_format(value, currency='UGX'):
    """Format currency value"""
    try:
        value = float(value)
        if currency == 'UGX':
            return f"{value:,.0f} {currency}"
        else:
            return f"{value:,.2f} {currency}"
    except (ValueError, TypeError):
        return value


@register.filter
def expense_status_color(status):
    """Return Bootstrap color class for expense status"""
    colors = {
        'DRAFT': 'secondary',
        'SUBMITTED': 'warning',
        'APPROVED': 'info',
        'REJECTED': 'danger',
        'PAID': 'success',
        'CANCELLED': 'dark'
    }
    return colors.get(status, 'secondary')


@register.filter
def expense_status_icon(status):
    """Return Bootstrap icon for expense status"""
    icons = {
        'DRAFT': 'bi-file-earmark',
        'SUBMITTED': 'bi-clock',
        'APPROVED': 'bi-check-circle',
        'REJECTED': 'bi-x-circle',
        'PAID': 'bi-cash-coin',
        'CANCELLED': 'bi-ban'
    }
    return icons.get(status, 'bi-question-circle')


@register.filter
def days_ago(date):
    """Return number of days ago"""
    if not date:
        return None
    delta = timezone.now().date() - date
    return delta.days


@register.simple_tag
def get_month_expenses(user, month=None, year=None):
    """Get total expenses for a month"""
    from expenses.models import Expense

    if not month:
        month = timezone.now().month
    if not year:
        year = timezone.now().year

    total = Expense.objects.filter(
        created_by=user,
        expense_date__month=month,
        expense_date__year=year
    ).aggregate(Sum('amount'))['amount__sum'] or Decimal('0')

    return total


@register.simple_tag
def get_category_color(category):
    """Get category color code"""
    return category.color_code if hasattr(category, 'color_code') else '#6c757d'


@register.inclusion_tag('expenses/includes/expense_status_badge.html')
def expense_status_badge(expense, css_class=None):
    return {'expense': expense, 'css_class': css_class}

@register.filter
def abs(value):
    try:
        return builtins.abs(value)
    except Exception:
        return value

@register.inclusion_tag('expenses/includes/expense_card.html')
def expense_card(expense):
    """Render expense card"""
    return {'expense': expense}


@register.filter
def subtract(value, arg):
    """Subtract arg from value"""
    try:
        return float(value) - float(arg)
    except (ValueError, TypeError):
        return value


@register.filter
def percentage(value, total):
    """Calculate percentage"""
    try:
        if float(total) == 0:
            return 0
        return (float(value) / float(total)) * 100
    except (ValueError, TypeError, ZeroDivisionError):
        return 0


@register.filter
def budget_status_class(utilization):
    """Return CSS class based on budget utilization"""
    try:
        util = float(utilization)
        if util >= 100:
            return 'danger'
        elif util >= 80:
            return 'warning'
        elif util >= 50:
            return 'info'
        else:
            return 'success'
    except (ValueError, TypeError):
        return 'secondary'