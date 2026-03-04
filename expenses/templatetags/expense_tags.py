"""
expense_tags.py — Django template tag library for the expenses app.

Changes from original:
  • Fixed `abs` filter: was referencing undefined `builtins` — now uses the
    stdlib `builtins` module explicitly.
  • expense_status_color / expense_status_icon updated to lowercase status values
    that match the new STATUS_CHOICES on the Expense model.
  • get_month_expenses updated to use user= (not created_by=) and date= field.
  • New filter: currency_symbol — returns the symbol for a currency code.
  • New filter: ocr_confidence_class — Bootstrap colour for OCR result quality.
  • New simple_tag: get_approval_history — returns approval records for an expense.
  • query_transform preserved unchanged.
  • All other filters preserved and unchanged.
"""

import builtins

from django import template
from django.db.models import Sum
from django.utils import timezone
from decimal import Decimal

register = template.Library()


# ---------------------------------------------------------------------------
# URL / query helpers
# ---------------------------------------------------------------------------

@register.simple_tag
def query_transform(request, **kwargs):
    """Preserve existing query-string params while overriding specified ones."""
    updated = request.GET.copy()
    for k, v in kwargs.items():
        updated[k] = v
    return updated.urlencode()


# ---------------------------------------------------------------------------
# Currency helpers
# ---------------------------------------------------------------------------

_CURRENCY_SYMBOLS = {
    'USD': '$', 'EUR': '€', 'GBP': '£',
    'UGX': 'UGX', 'KES': 'KES', 'TZS': 'TZS',
    'NGN': '₦', 'ZAR': 'R', 'GHS': 'GH₵',
    'JPY': '¥', 'CAD': 'CA$', 'AUD': 'A$',
    'INR': '₹', 'CNY': '¥', 'CHF': 'Fr',
}

# Currencies that display without decimal places
_NO_DECIMAL_CURRENCIES = {'UGX', 'JPY', 'KES', 'TZS'}


@register.filter
def currency_format(value, currency='UGX'):
    """
    Format a numeric value with its currency symbol/code.

    Usage: {{ expense.amount|currency_format:expense.currency }}
    """
    try:
        value = float(value)
        symbol = _CURRENCY_SYMBOLS.get(currency, currency)
        if currency in _NO_DECIMAL_CURRENCIES:
            return f"{symbol} {value:,.0f}"
        return f"{symbol} {value:,.2f}"
    except (ValueError, TypeError):
        return value


@register.filter
def currency_symbol(currency_code):
    """Return the symbol for a given ISO 4217 currency code."""
    return _CURRENCY_SYMBOLS.get(str(currency_code).upper(), currency_code)


# ---------------------------------------------------------------------------
# Expense status helpers  (lowercase values to match new STATUS_CHOICES)
# ---------------------------------------------------------------------------

_STATUS_COLORS = {
    'draft':        'secondary',
    'submitted':    'warning',
    'under_review': 'info',
    'approved':     'success',
    'rejected':     'danger',
    'resubmit':     'orange',   # custom — use a CSS var or Bootstrap custom colour
}

_STATUS_ICONS = {
    'draft':        'bi-file-earmark',
    'submitted':    'bi-clock',
    'under_review': 'bi-eye',
    'approved':     'bi-check-circle-fill',
    'rejected':     'bi-x-circle-fill',
    'resubmit':     'bi-arrow-clockwise',
}


@register.filter
def expense_status_color(status):
    """Return Bootstrap colour token for a given status value."""
    return _STATUS_COLORS.get(str(status).lower(), 'secondary')


@register.filter
def expense_status_icon(status):
    """Return Bootstrap Icon class for a given status value."""
    return _STATUS_ICONS.get(str(status).lower(), 'bi-question-circle')


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------

@register.filter
def days_ago(date):
    """Return the number of days between today and *date*. Negative = future."""
    if not date:
        return None
    delta = timezone.now().date() - date
    return delta.days


# ---------------------------------------------------------------------------
# Math helpers
# ---------------------------------------------------------------------------

@register.filter(name='abs')
def abs_filter(value):
    """Return the absolute value of *value*."""
    try:
        return builtins.abs(value)
    except (TypeError, ValueError):
        return value


@register.filter
def subtract(value, arg):
    """Return value − arg."""
    try:
        return float(value) - float(arg)
    except (ValueError, TypeError):
        return value


@register.filter
def percentage(value, total):
    """Return (value / total) × 100, or 0 on errors."""
    try:
        t = float(total)
        if t == 0:
            return 0
        return (float(value) / t) * 100
    except (ValueError, TypeError, ZeroDivisionError):
        return 0


# ---------------------------------------------------------------------------
# Budget / threshold helpers
# ---------------------------------------------------------------------------

@register.filter
def budget_status_class(utilization):
    """Return Bootstrap colour token based on budget utilisation %."""
    try:
        util = float(utilization)
        if util >= 100:
            return 'danger'
        elif util >= 80:
            return 'warning'
        elif util >= 50:
            return 'info'
        return 'success'
    except (ValueError, TypeError):
        return 'secondary'


# ---------------------------------------------------------------------------
# OCR helpers
# ---------------------------------------------------------------------------

@register.filter
def ocr_confidence_class(expense):
    """
    Return a Bootstrap colour token indicating how complete the OCR result is.
    Useful for showing a visual indicator on expense cards.
    """
    if not expense.ocr_processed:
        return 'secondary'   # Not yet processed
    if expense.ocr_vendor and expense.ocr_amount:
        return 'success'     # Full extraction
    if expense.ocr_vendor or expense.ocr_amount:
        return 'warning'     # Partial extraction
    return 'danger'          # Processed but nothing extracted


# ---------------------------------------------------------------------------
# Simple tags
# ---------------------------------------------------------------------------

@register.simple_tag
def get_month_expenses(user, month=None, year=None):
    """Return the total base-currency expenses for a given user and month."""
    from .models import Expense

    if not month:
        month = timezone.now().month
    if not year:
        year = timezone.now().year

    total = (
        Expense.objects.filter(
            user=user,
            date__month=month,
            date__year=year,
        ).aggregate(total=Sum('amount_base'))['total']
        or Decimal('0')
    )
    return total


@register.simple_tag
def get_approval_history(expense):
    """Return the full approval history queryset for an expense."""
    return expense.approvals.select_related('actor').order_by('created_at')


@register.simple_tag
def get_category_color(category):
    """Return the color_code of a category object, defaulting to Bootstrap grey."""
    return getattr(category, 'color_code', '#6c757d')


# ---------------------------------------------------------------------------
# Inclusion tags
# ---------------------------------------------------------------------------

@register.inclusion_tag('expenses/includes/expense_status_badge.html')
def expense_status_badge(expense, css_class=None):
    return {'expense': expense, 'css_class': css_class}


@register.inclusion_tag('expenses/includes/expense_card.html')
def expense_card(expense):
    return {'expense': expense}