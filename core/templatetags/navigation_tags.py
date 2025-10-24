
from django import template
from django.urls import reverse, NoReverseMatch
from ..navigation import get_navigation_for_user, get_contextual_navigation

register = template.Library()


@register.inclusion_tag('navigation.html', takes_context=True)
def render_navigation(context):
    """
    Enhanced template tag to render navigation with URL parameter support
    """
    user = context.get('user')
    request = context.get('request')

    if not user or not user.is_authenticated:
        return {
            'navigation_items': [],
            'request': request,
            'nav_context': {},
        }

    # Extract navigation context from template context
    nav_context = {}

    # Common context objects that might be in templates
    context_keys = [
        'company', 'store', 'user_obj', 'product', 'invoice', 'customer',
        'branch', 'employee', 'order', 'report', 'category', 'supplier'
    ]

    for key in context_keys:
        if key in context:
            nav_context[key] = context[key]

    # Also check for ID parameters in the context
    id_keys = [
        'company_id', 'store.id', 'user.id', 'product.id', 'invoice.id',
        'customer.id', 'companybranch.id', 'employee.id',  'category.id'
    ]

    for key in id_keys:
        if key in context:
            nav_context[key] = context[key]

    # Get navigation items with context
    if nav_context:
        nav_items = get_contextual_navigation(user, request, **nav_context)
    else:
        nav_items = get_navigation_for_user(user, request)

    return {
        'navigation_items': nav_items,
        'request': request,
        'nav_context': nav_context,
    }


@register.filter
def has_visible_children(nav_item):
    """
    Check if navigation item has any visible children
    """
    return len(nav_item.children) > 0


@register.simple_tag(takes_context=True)
def is_active_nav(context, url_name):
    """
    Enhanced active navigation check with parameter support
    """
    if not url_name:
        return False

    request = context.get('request')
    if not request or not hasattr(request, 'resolver_match') or not request.resolver_match:
        return False

    current_url_name = request.resolver_match.url_name
    current_namespace = request.resolver_match.namespace

    # Handle namespaced URLs
    if ':' in str(url_name):
        namespace, view_name = str(url_name).split(':', 1)
        return current_namespace == namespace and current_url_name == view_name

    return current_url_name == str(url_name)


@register.simple_tag(takes_context=True)
def is_section_active(context, nav_item):
    """
    Check if current section is active (including children)
    Enhanced to work with navigation items
    """
    request = context.get('request')
    if not request or not hasattr(request, 'resolver_match'):
        return False

    # Check if current item is active
    if nav_item.matches_url(request):
        return True

    # Check if any child is active
    def check_children(children):
        for child in children:
            if child.matches_url(request):
                return True
            if child.children and check_children(child.children):
                return True
        return False

    return check_children(nav_item.children)


@register.simple_tag(takes_context=True)
def nav_item_url(context, nav_item):
    """
    Get URL for navigation item with enhanced parameter support
    """
    request = context.get('request')
    nav_context = context.get('nav_context', {})

    try:
        return nav_item.get_url(request, **nav_context)
    except (NoReverseMatch, AttributeError):
        return '#'


@register.simple_tag(takes_context=True)
def get_nav_url(context, url_name, **kwargs):
    """
    Generate URL with parameters from context
    Usage: {% get_nav_url 'companies:company_detail' company_id=company.id %}
    """
    request = context.get('request')
    nav_context = context.get('nav_context', {})

    # Merge provided kwargs with context
    url_kwargs = {**nav_context, **kwargs}

    try:
        return reverse(url_name, kwargs=url_kwargs)
    except (NoReverseMatch, AttributeError):
        return '#'


@register.filter
def slugify_nav(value):
    """
    Convert navigation item name to slug for IDs
    """
    import re
    value = str(value).lower()
    value = re.sub(r'[^\w\s-]', '', value)
    value = re.sub(r'[-\s]+', '-', value)
    return value.strip('-')


@register.filter
def nav_permission_check(nav_item, user):
    """
    Check if user has permission for navigation item
    """
    return nav_item.is_visible(user)


@register.inclusion_tag('core/breadcrumbs.html', takes_context=True)
def render_breadcrumbs(context, nav_items=None):
    """
    Enhanced breadcrumb rendering with parameter support
    """
    request = context.get('request')
    if not request or not hasattr(request, 'resolver_match'):
        return {'breadcrumbs': []}

    user = context.get('user')
    nav_context = context.get('nav_context', {})

    if nav_items is None:
        if nav_context:
            nav_items = get_contextual_navigation(user, request, **nav_context)
        else:
            nav_items = get_navigation_for_user(user, request)

    current_url_name = request.resolver_match.url_name
    current_namespace = request.resolver_match.namespace

    if current_namespace:
        full_url_name = f"{current_namespace}:{current_url_name}"
    else:
        full_url_name = current_url_name

    def find_breadcrumb_path(items, target_url, path=[]):
        for item in items:
            current_path = path + [item]

            # Check if this item matches
            item_url = item.url_name
            if item_url == target_url or item_url == full_url_name:
                return current_path

            # Search children
            if item.children:
                child_path = find_breadcrumb_path(item.children, target_url, current_path)
                if child_path:
                    return child_path

        return None

    # Find the path to current page
    breadcrumb_path = find_breadcrumb_path(nav_items, full_url_name)

    breadcrumbs = [{'name': 'Home', 'url': '/', 'active': False}]

    if breadcrumb_path:
        for i, item in enumerate(breadcrumb_path):
            is_last = i == len(breadcrumb_path) - 1

            # Get URL with context
            try:
                item_url = item.get_url(request, **nav_context) if not is_last else None
            except:
                item_url = '#' if not is_last else None

            breadcrumbs.append({
                'name': item.name,
                'url': item_url,
                'active': is_last
            })

    return {'breadcrumbs': breadcrumbs}


@register.simple_tag(takes_context=True)
def contextual_nav_items(context, section_name):
    """
    Get contextual navigation items for a specific section
    Usage: {% contextual_nav_items 'Companies' as company_nav %}
    """
    user = context.get('user')
    request = context.get('request')
    nav_context = context.get('nav_context', {})

    if not user or not user.is_authenticated:
        return []

    if nav_context:
        nav_items = get_contextual_navigation(user, request, **nav_context)
    else:
        nav_items = get_navigation_for_user(user, request)

    # Find the specific section
    for section in nav_items:
        if section.name == section_name:
            return section.children

    return []


@register.simple_tag(takes_context=True)
def object_nav_menu(context, obj, obj_type):
    """
    Generate navigation menu for a specific object
    Usage: {% object_nav_menu company 'company' as company_menu %}
    """
    user = context.get('user')
    request = context.get('request')

    if not user or not user.is_authenticated:
        return []

    # Generate object-specific navigation
    nav_items = []

    if obj_type == 'company':
        nav_items = [
            {
                'name': 'Overview',
                'url': reverse('companies:company_detail', kwargs={'company_id': obj.pk}),
                'icon': 'bi bi-building',
                'active': request.resolver_match.url_name == 'company_detail'
            },
            {
                'name': 'Edit',
                'url': reverse('companies:company_update', kwargs={'company_id': obj.pk}),
                'icon': 'bi bi-pencil',
                'active': request.resolver_match.url_name == 'company_update',
                'permission': 'companies.change_company'
            },
            {
                'name': 'Branches',
                'url': reverse('companies:company_branches', kwargs={'company_id': obj.pk}),
                'icon': 'bi bi-diagram-3',
                'active': request.resolver_match.url_name == 'company_branches',
                'permission': 'branches.view_branch'
            },
            {
                'name': 'Employees',
                'url': reverse('companies:company_employees', kwargs={'company_id': obj.pk}),
                'icon': 'bi bi-people',
                'active': request.resolver_match.url_name == 'company_employees',
                'permission': 'companies.view_employee'
            }
        ]
    elif obj_type == 'store':
        nav_items = [
            {
                'name': 'Overview',
                'url': reverse('stores:store_detail', kwargs={'store.id': obj.pk}),
                'icon': 'bi bi-shop',
                'active': request.resolver_match.url_name == 'store_detail'
            },
            {
                'name': 'Edit',
                'url': reverse('stores:store_update', kwargs={'store.id': obj.pk}),
                'icon': 'bi bi-pencil',
                'active': request.resolver_match.url_name == 'store_update',
                'permission': 'stores.change_store'
            },
            {
                'name': 'Inventory',
                'url': reverse('stores:store_inventory', kwargs={'store.id': obj.pk}),
                'icon': 'bi bi-boxes',
                'active': request.resolver_match.url_name == 'store_inventory',
                'permission': 'inventory.view_stock'
            }
        ]

    # Filter based on permissions
    filtered_items = []
    for item in nav_items:
        if 'permission' in item:
            if user.has_perm(item['permission']):
                filtered_items.append(item)
        else:
            filtered_items.append(item)

    return filtered_items


@register.simple_tag
def has_nav_permission(user, permission):
    """
    Check if user has specific permission for navigation
    """
    if not permission:
        return True

    if isinstance(permission, str):
        return user.has_perm(permission)
    elif isinstance(permission, list):
        return any(user.has_perm(perm) for perm in permission)

    return True


@register.filter
def get_object_id(obj, field_name='pk'):
    """
    Get ID from object for URL generation
    Usage: {{ company|get_object_id:'company_id' }}
    """
    try:
        if hasattr(obj, field_name):
            return getattr(obj, field_name)
        elif hasattr(obj, 'pk'):
            return obj.pk
        elif hasattr(obj, 'id'):
            return obj.id
        else:
            return str(obj)
    except:
        return None


@register.simple_tag(takes_context=True)
def build_nav_context(context, **kwargs):
    """
    Build navigation context from template variables
    Usage: {% build_nav_context company=company store=store as nav_ctx %}
    """
    nav_context = context.get('nav_context', {}).copy()
    nav_context.update(kwargs)
    return nav_context

@register.filter
def is_section_active(nav_item):
    """
    Returns True if the nav_item is active.
    Assumes nav_item has an 'active' property or attribute.
    """
    try:
        return getattr(nav_item, "active", False)
    except Exception:
        return False

@register.filter
def has_nav_permission(user, perm_codename):
    """
    Check if the user has a given permission.
    Usage: {% if user|has_nav_permission:"app_label.permission_codename" %}
    """
    try:
        return user.has_perm(perm_codename)
    except Exception:
        return False