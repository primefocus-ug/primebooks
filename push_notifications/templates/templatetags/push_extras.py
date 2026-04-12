# push_notifications/templatetags/push_extras.py

from django import template

register = template.Library()


@register.filter
def get_item(dictionary, key):
    """
    Usage in templates: {{ my_dict|get_item:key_var }}
    Returns the value for a given key, or None if not found.
    """
    if dictionary is None:
        return None
    return dictionary.get(key)