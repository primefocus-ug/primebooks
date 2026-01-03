from django import template
from django.utils.safestring import mark_safe

register = template.Library()


@register.simple_tag(takes_context=True)
def efris_enabled(context):
    """Check if EFRIS is enabled for current company"""
    request = context.get('request')

    if not request:
        return False

    # Check tenant
    if hasattr(request, 'tenant'):
        return getattr(request.tenant, 'efris_enabled', False)

    # Check user's company
    if hasattr(request, 'user') and request.user.is_authenticated:
        if hasattr(request.user, 'company'):
            return getattr(request.user.company, 'efris_enabled', False)

        # Check via store
        if hasattr(request.user, 'stores') and request.user.stores.exists():
            store = request.user.stores.first()
            if store and hasattr(store, 'company'):
                return getattr(store.company, 'efris_enabled', False)

    return False


@register.simple_tag(takes_context=True)
def efris_and_vat_enabled(context):
    """Check if both EFRIS and VAT are enabled for current company"""
    request = context.get('request')

    if not request:
        return False

    # Check tenant
    if hasattr(request, 'tenant'):
        efris = getattr(request.tenant, 'efris_enabled', False)
        vat = getattr(request.tenant, 'is_vat_enabled', False)
        return efris and vat

    # Check user's company
    if hasattr(request, 'user') and request.user.is_authenticated:
        if hasattr(request.user, 'company'):
            efris = getattr(request.user.company, 'efris_enabled', False)
            vat = getattr(request.user.company, 'is_vat_enabled', False)
            return efris and vat

        # Check via store
        if hasattr(request.user, 'stores') and request.user.stores.exists():
            store = request.user.stores.first()
            if store and hasattr(store, 'company'):
                efris = getattr(store.company, 'efris_enabled', False)
                vat = getattr(store.company, 'is_vat_enabled', False)
                return efris and vat

    return False


@register.filter
def show_if_efris(value, arg=''):
    """
    Filter to conditionally show content if EFRIS is enabled
    Usage: {{ "Some EFRIS text"|show_if_efris:efris_enabled }}
    """
    if arg:
        return value
    return ''


@register.inclusion_tag('efris/efris_badge.html', takes_context=True)
def efris_status_badge(context):
    """Display EFRIS status badge"""
    request = context.get('request')
    efris_enabled = False
    efris_status = 'Disabled'
    badge_class = 'secondary'

    if hasattr(request, 'tenant'):
        company = request.tenant
        efris_enabled = getattr(company, 'efris_enabled', False)

        if efris_enabled:
            if getattr(company, 'efris_is_active', False):
                efris_status = 'Active'
                badge_class = 'success'
            else:
                efris_status = 'Inactive'
                badge_class = 'warning'

    return {
        'efris_enabled': efris_enabled,
        'efris_status': efris_status,
        'badge_class': badge_class,
    }


@register.simple_tag
def efris_field_help(field_name, efris_help='', default_help=''):
    """
    Return different help text based on EFRIS status
    Usage: {% efris_field_help 'tin' 'Required for EFRIS' 'Tax ID Number' %}
    """
    # This will be determined at render time via context
    return mark_safe(
        f'<span class="efris-help" data-efris-text="{efris_help}" '
        f'data-default-text="{default_help}"></span>'
    )