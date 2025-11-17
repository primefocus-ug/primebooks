from django import template

register = template.Library()


@register.filter
def lookup(obj, attr):
    """
    Template filter to get attribute value dynamically
    Usage: {{ obj|lookup:field_name }}
    """
    try:
        # Try to get as attribute
        value = getattr(obj, attr)

        # If it's callable (like a method), call it
        if callable(value):
            return value()

        return value
    except (AttributeError, TypeError):
        return ''


@register.filter
def get_verbose_name(model):
    """Get verbose name of model"""
    return model._meta.verbose_name


@register.filter
def get_verbose_name_plural(model):
    """Get verbose name plural of model"""
    return model._meta.verbose_name_plural


@register.simple_tag
def query_transform(request, **kwargs):
    """
    Update query parameters while keeping existing ones
    Usage: {% query_transform page=2 %}
    """
    updated = request.GET.copy()
    for k, v in kwargs.items():
        updated[k] = v
    return updated.urlencode()