from django import template
from decimal import Decimal, InvalidOperation


register = template.Library()

@register.filter
def filter_attr(queryset, attr_name):
    """Filter a queryset by attribute value (True)"""
    return [item for item in queryset if getattr(item, attr_name, False)]

@register.filter
def divide(value, arg):
    """Divides the value by the argument"""
    try:
        return float(value) / float(arg) if arg != 0 else 0
    except (ValueError, TypeError):
        return 0

@register.filter
def multiply(value, arg):
    """Multiplies the value by the argument"""
    try:
        return float(value) * float(arg)
    except (ValueError, TypeError):
        return 0

@register.filter
def absolute(value):
    try:
        return abs(float(value))
    except (ValueError, TypeError):
        return 0

@register.filter
def filter_by_month(expenses, month_str):
    """
    Filter a queryset or list of expenses by month string 'YYYY-MM'.
    """
    filtered = [e for e in expenses if e.date.strftime('%Y-%m') == month_str]
    return filtered

@register.filter
def sum_field(items, field_name):
    """
    Sum a specific numeric field from a list or queryset.
    Usage: {{ expenses|sum_field:"amount" }}
    """
    return sum(getattr(i, field_name, 0) for i in items)

@register.filter
def get_item(dictionary, key):
    return dictionary.get(key)

@register.filter
def get_item(dictionary, key):
    """Return dictionary[key] safely."""
    return dictionary.get(key)

@register.filter
def is_section_active(nav_item, current_section):
    """
    Check if the nav_item section is currently active
    """
    return getattr(nav_item, "name", "") == current_section

@register.filter
def subtract(value, arg):
    """Subtract the arg from the value"""
    try:
        return float(value) - float(arg)
    except (ValueError, TypeError):
        return value

@register.filter
def has_nav_permission(user, perm_name):
    """
    Check if the user has a specific permission
    Example: 'accounts.change_customuser'
    """
    if not user or user.is_anonymous:
        return False
    return user.has_perm(perm_name)

@register.filter
def mul(value, arg):
    """Multiply value by arg."""
    try:
        return float(value) * float(arg)
    except (ValueError, TypeError):
        return ""

@register.filter
def div(value, arg):
    """Divide value by arg safely."""
    try:
        return float(value) / float(arg) if float(arg) != 0 else 0
    except (ValueError, TypeError):
        return 0


@register.filter(name='replace')
def replace(value, arg):
    """
    Replace all occurrences of `old` with `new` in the string.
    Usage: {{ value|replace:"old,new" }}
    Example: {{ "sale_date"|replace:"_, " }} → "sale date"
    """
    try:
        old, new = arg.split(',', 1)
        old, new = old.strip(), new.strip()
        return str(value).replace(old, new)
    except Exception:
        return value

@register.filter(name="ratio")
def ratio(value, arg):
    """
    Compute a ratio between two numbers.
    Equivalent to (value / arg), returns 0 if arg is 0.
    """
    try:
        value = float(value)
        arg = float(arg)
        if arg == 0:
            return 0
        return value / arg
    except (ValueError, TypeError):
        return 0

@register.filter
def split(value, delimiter=","):
    """Split a string by the given delimiter."""
    if not value:
        return []
    return value.split(delimiter)

@register.filter
def trim(value):
    """Remove leading and trailing whitespace."""
    if not isinstance(value, str):
        return value
    return value.strip()


@register.filter
def get_item(dictionary, key):
    """Return a dictionary value safely."""
    if isinstance(dictionary, dict):
        return dictionary.get(key)
    return None

@register.filter(name='getattr')
def get_attribute(obj, attr_name):
    """Safely get an attribute by name in templates"""
    try:
        return getattr(obj, attr_name, '')
    except Exception:
        return ''

python_range = range

@register.filter
def range(value):
    return python_range(int(value))


@register.filter
def money(value, places=2):
    """
    Format a number with commas and optional decimal places.
    Usage: {{ amount|money }} or {{ amount|money:0 }}
    """
    try:
        value = Decimal(value)
        return f"{value:,.{places}f}"
    except (InvalidOperation, ValueError, TypeError):
        return value