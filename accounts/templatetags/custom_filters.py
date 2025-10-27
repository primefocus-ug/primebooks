from django import template

register = template.Library()

@register.filter
def filter_attr(queryset, attr_name):
    """Filter a queryset by attribute value (True)"""
    return [item for item in queryset if getattr(item, attr_name, False)]

@register.filter
def absolute(value):
    try:
        return abs(float(value))
    except (ValueError, TypeError):
        return 0

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
