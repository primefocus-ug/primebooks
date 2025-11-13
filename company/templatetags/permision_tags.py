from django import template
from django.urls import reverse

register = template.Library()

@register.simple_tag(takes_context=True)
def can_add(context, model_path):
    """
    Check if user has add permission
    Usage: {% can_add 'stores.store' %}
    """
    user = context['request'].user
    if not user.is_authenticated:
        return False
    
    app_label, model = model_path.split('.')
    return user.has_perm(f'{app_label}.add_{model}')

@register.simple_tag(takes_context=True)
def can_view(context, model_path):
    """
    Check if user has view permission
    Usage: {% can_view 'products.product' %}
    """
    user = context['request'].user
    if not user.is_authenticated:
        return False
    
    app_label, model = model_path.split('.')
    return user.has_perm(f'{app_label}.view_{model}')

@register.simple_tag(takes_context=True)
def can_change(context, model_path):
    """
    Check if user has change permission
    Usage: {% can_change 'stores.store' %}
    """
    user = context['request'].user
    if not user.is_authenticated:
        return False
    
    app_label, model = model_path.split('.')
    return user.has_perm(f'{app_label}.change_{model}')

@register.simple_tag(takes_context=True)
def can_delete(context, model_path):
    """
    Check if user has delete permission
    Usage: {% can_delete 'stores.store' %}
    """
    user = context['request'].user
    if not user.is_authenticated:
        return False
    
    app_label, model = model_path.split('.')
    return user.has_perm(f'{app_label}.delete_{model}')

@register.simple_tag(takes_context=True)
def has_perm(context, permission):
    """
    Generic permission check
    Usage: {% has_perm 'stores.custom_permission' %}
    """
    user = context['request'].user
    if not user.is_authenticated:
        return False
    return user.has_perm(permission)

@register.simple_tag(takes_context=True)
def has_any_perm(context, *permissions):
    """
    Check if user has ANY of the given permissions
    Usage: {% has_any_perm 'stores.add_store' 'stores.change_store' %}
    """
    user = context['request'].user
    if not user.is_authenticated:
        return False
    return any(user.has_perm(perm) for perm in permissions)

@register.simple_tag(takes_context=True)
def has_all_perms(context, *permissions):
    """
    Check if user has ALL of the given permissions
    Usage: {% has_all_perms 'stores.add_store' 'stores.change_store' %}
    """
    user = context['request'].user
    if not user.is_authenticated:
        return False
    return all(user.has_perm(perm) for perm in permissions)

@register.inclusion_tag('partials/action_buttons.html', takes_context=True)
def model_action_buttons(context, model_path, object_id=None, list_url=None):
    """
    Render CRUD action buttons based on permissions
    Usage: {% model_action_buttons 'stores.store' object.id %}
    """
    user = context['request'].user
    app_label, model = model_path.split('.')
    
    # Build URL names based on Django conventions
    # Assumes URL patterns like: stores:store_create, stores:store_update, etc.
    url_prefix = f'{app_label}:{model}'
    
    buttons = {
        'can_add': user.has_perm(f'{app_label}.add_{model}'),
        'can_view': user.has_perm(f'{app_label}.view_{model}'),
        'can_change': user.has_perm(f'{app_label}.change_{model}'),
        'can_delete': user.has_perm(f'{app_label}.delete_{model}'),
        'add_url': reverse(f'{url_prefix}_create') if user.has_perm(f'{app_label}.add_{model}') else None,
        'list_url': list_url or reverse(f'{url_prefix}_list') if user.has_perm(f'{app_label}.view_{model}') else None,
    }
    
    if object_id:
        if user.has_perm(f'{app_label}.view_{model}'):
            buttons['detail_url'] = reverse(f'{url_prefix}_detail', args=[object_id])
        if user.has_perm(f'{app_label}.change_{model}'):
            buttons['update_url'] = reverse(f'{url_prefix}_update', args=[object_id])
        if user.has_perm(f'{app_label}.delete_{model}'):
            buttons['delete_url'] = reverse(f'{url_prefix}_delete', args=[object_id])
    
    buttons['object_id'] = object_id
    buttons['model_name'] = model.replace('_', ' ').title()
    
    return buttons