from django import template
from django.utils.safestring import mark_safe
from django_tenants.utils import get_tenant_model

register = template.Library()


@register.simple_tag(takes_context=True)
def efris_enabled(context):
    """
    Check if EFRIS is enabled for current tenant
    Usage: {% efris_enabled as is_efris_enabled %}
    """
    request = context.get('request')
    if request and hasattr(request, 'tenant'):
        return request.tenant.efris_enabled
    return False


@register.simple_tag(takes_context=True)
def efris_active(context):
    """
    Check if EFRIS is active (enabled + configured)
    Usage: {% efris_active as is_efris_active %}
    """
    request = context.get('request')
    if request and hasattr(request, 'tenant'):
        return request.tenant.efris_enabled and request.tenant.efris_is_active
    return False


@register.simple_tag(takes_context=True)
def efris_status(context):
    """
    Get EFRIS status display
    Usage: {% efris_status as efris_status_text %}
    """
    request = context.get('request')
    if request and hasattr(request, 'tenant'):
        return request.tenant.efris_status_display
    return "Unknown"


@register.filter
def show_if_efris(value, default=''):
    """
    Show value only if EFRIS is enabled
    Usage: {{ "Some text"|show_if_efris }}
    """
    from django_tenants.utils import get_current_tenant
    try:
        tenant = get_current_tenant()
        if tenant and tenant.efris_enabled:
            return value
    except:
        pass
    return default


@register.inclusion_tag('efris/tags/efris_badge.html', takes_context=True)
def efris_status_badge(context):
    """
    Display EFRIS status badge
    Usage: {% efris_status_badge %}
    """
    request = context.get('request')
    if request and hasattr(request, 'tenant'):
        tenant = request.tenant
        return {
            'enabled': tenant.efris_enabled,
            'active': tenant.efris_is_active,
            'registered': tenant.efris_is_registered,
            'status_display': tenant.efris_status_display,
        }
    return {'enabled': False}


@register.inclusion_tag('efris/tags/efris_field_wrapper.html', takes_context=True)
def efris_field(context, field, label=None, help_text=None, required=False):
    """
    Wrap a form field to show/hide based on EFRIS status
    Usage: {% efris_field form.efris_field "EFRIS Field" "Help text" %}
    """
    request = context.get('request')
    efris_enabled = False
    
    if request and hasattr(request, 'tenant'):
        efris_enabled = request.tenant.efris_enabled
    
    return {
        'field': field,
        'label': label or field.label,
        'help_text': help_text or getattr(field, 'help_text', ''),
        'required': required,
        'efris_enabled': efris_enabled,
    }


@register.simple_tag
def efris_css_class():
    """
    Returns CSS class for EFRIS conditional display
    Usage: <div class="{% efris_css_class %}">...</div>
    """
    from django_tenants.utils import get_current_tenant
    try:
        tenant = get_current_tenant()
        if tenant and tenant.efris_enabled:
            return 'efris-enabled'
        return 'efris-disabled'
    except:
        return 'efris-disabled'


@register.simple_tag(takes_context=True)
def efris_show_class(context):
    """
    Returns class to show/hide element based on EFRIS status
    Usage: <div class="{% efris_show_class %}">EFRIS Content</div>
    """
    request = context.get('request')
    if request and hasattr(request, 'tenant') and request.tenant.efris_enabled:
        return ''
    return 'd-none'  # Bootstrap class to hide


@register.simple_tag(takes_context=True)
def efris_attr(context, attr_name, true_value='', false_value=''):
    """
    Returns attribute value based on EFRIS status
    Usage: <input {% efris_attr 'disabled' '' 'disabled' %}>
    """
    request = context.get('request')
    if request and hasattr(request, 'tenant') and request.tenant.efris_enabled:
        return mark_safe(true_value)
    return mark_safe(false_value)

