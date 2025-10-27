from django import template
from django.urls import reverse, NoReverseMatch
from django.utils.text import slugify
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
        'company_id', 'store_id', 'user_id', 'product_id', 'invoice_id',
        'customer_id', 'branch_id', 'employee_id', 'category_id'
    ]

    for key in id_keys:
        if key in context:
            nav_context[key] = context[key]

    # Get navigation items with context
    try:
        if nav_context:
            nav_items = get_contextual_navigation(user, request, **nav_context)
        else:
            nav_items = get_navigation_for_user(user, request)
    except Exception as e:
        # Log error but don't break the template
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Navigation loading error: {e}")
        nav_items = []

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
    try:
        return len(getattr(nav_item, 'children', [])) > 0
    except (AttributeError, TypeError):
        return False


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
        try:
            namespace, view_name = str(url_name).split(':', 1)
            return current_namespace == namespace and current_url_name == view_name
        except ValueError:
            # Invalid namespaced URL format
            return False

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

    # Check if nav_item has matches_url method
    if hasattr(nav_item, 'matches_url'):
        try:
            if nav_item.matches_url(request):
                return True
        except Exception:
            pass

    # Check if any child is active
    def check_children(children):
        for child in children:
            if hasattr(child, 'matches_url'):
                try:
                    if child.matches_url(request):
                        return True
                except Exception:
                    pass
            if hasattr(child, 'children') and child.children:
                if check_children(child.children):
                    return True
        return False

    if hasattr(nav_item, 'children'):
        return check_children(nav_item.children)

    return False


@register.simple_tag(takes_context=True)
def nav_item_url(context, nav_item):
    """
    Get URL for navigation item with enhanced parameter support
    """
    request = context.get('request')
    nav_context = context.get('nav_context', {})

    try:
        # Try to get URL using the nav_item's method
        if hasattr(nav_item, 'get_url'):
            return nav_item.get_url(request, **nav_context)

        # Fallback to url_name if available
        if hasattr(nav_item, 'url_name') and nav_item.url_name:
            url_kwargs = {}

            # Extract relevant kwargs from context
            if hasattr(nav_item, 'url_kwargs'):
                for key in nav_item.url_kwargs:
                    if key in nav_context:
                        url_kwargs[key] = nav_context[key]

            return reverse(nav_item.url_name, kwargs=url_kwargs)

    except (NoReverseMatch, AttributeError, Exception) as e:
        # Log the error for debugging
        import logging
        logger = logging.getLogger(__name__)
        logger.debug(f"URL generation failed for {nav_item}: {e}")

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
    url_kwargs = {}

    # Add context values first
    for key, value in nav_context.items():
        if key.endswith('_id') or key in ['pk', 'id']:
            url_kwargs[key] = value

    # Override with explicit kwargs
    url_kwargs.update(kwargs)

    # Clean up kwargs - remove None values
    url_kwargs = {k: v for k, v in url_kwargs.items() if v is not None}

    try:
        return reverse(url_name, kwargs=url_kwargs)
    except NoReverseMatch:
        # Try without kwargs if reverse fails
        try:
            return reverse(url_name)
        except NoReverseMatch:
            return '#'
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"URL generation error for {url_name}: {e}")
        return '#'


@register.filter
def slugify_nav(value):
    """
    Convert navigation item name to slug for IDs
    Uses Django's built-in slugify for consistency
    """
    try:
        return slugify(str(value))
    except Exception:
        # Fallback basic slugify
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
    try:
        return nav_item.is_visible(user)
    except AttributeError:
        # If nav_item doesn't have is_visible method, assume visible
        return True
    except Exception:
        return False


@register.inclusion_tag('navigation/breadcrumbs.html', takes_context=True)
def render_breadcrumbs(context, nav_items=None):
    """
    Enhanced breadcrumb rendering with parameter support
    """
    request = context.get('request')
    if not request or not hasattr(request, 'resolver_match'):
        return {'breadcrumbs': []}

    user = context.get('user')
    nav_context = context.get('nav_context', {})

    # Get navigation items if not provided
    if nav_items is None:
        try:
            if nav_context:
                nav_items = get_contextual_navigation(user, request, **nav_context)
            else:
                nav_items = get_navigation_for_user(user, request)
        except Exception:
            nav_items = []

    current_url_name = request.resolver_match.url_name
    current_namespace = request.resolver_match.namespace

    if current_namespace:
        full_url_name = f"{current_namespace}:{current_url_name}"
    else:
        full_url_name = current_url_name

    def find_breadcrumb_path(items, target_url, path=None):
        if path is None:
            path = []

        for item in items:
            current_path = path + [item]

            # Check if this item matches
            item_url = getattr(item, 'url_name', None)
            if item_url == target_url or item_url == full_url_name:
                return current_path

            # Search children
            if hasattr(item, 'children') and item.children:
                child_path = find_breadcrumb_path(item.children, target_url, current_path)
                if child_path:
                    return child_path

        return None

    # Find the path to current page
    breadcrumb_path = find_breadcrumb_path(nav_items, full_url_name) if nav_items else None

    breadcrumbs = [{'name': 'Home', 'url': '/', 'active': False}]

    if breadcrumb_path:
        for i, item in enumerate(breadcrumb_path):
            is_last = i == len(breadcrumb_path) - 1

            # Get URL with context
            try:
                item_url = nav_item_url(context, item) if not is_last else None
            except Exception:
                item_url = '#' if not is_last else None

            breadcrumbs.append({
                'name': getattr(item, 'name', 'Unknown'),
                'url': item_url,
                'active': is_last
            })
    else:
        # Fallback: use current view name
        view_name = getattr(request.resolver_match, 'view_name', '')
        if view_name:
            breadcrumbs.append({
                'name': view_name.replace('_', ' ').title(),
                'url': None,
                'active': True
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

    try:
        if nav_context:
            nav_items = get_contextual_navigation(user, request, **nav_context)
        else:
            nav_items = get_navigation_for_user(user, request)

        # Find the specific section
        for section in nav_items:
            if getattr(section, 'name', None) == section_name:
                return getattr(section, 'children', [])
    except Exception:
        return []

    return []


@register.simple_tag(takes_context=True)
def object_nav_menu(context, obj, obj_type):
    """
    Generate navigation menu for a specific object
    Usage: {% object_nav_menu company 'company' as company_menu %}
    """
    user = context.get('user')
    request = context.get('request')

    if not user or not user.is_authenticated or not obj:
        return []

    # Generate object-specific navigation
    nav_items = []

    try:
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
                    'url': reverse('stores:store_detail', kwargs={'store_id': obj.pk}),
                    'icon': 'bi bi-shop',
                    'active': request.resolver_match.url_name == 'store_detail'
                },
                {
                    'name': 'Edit',
                    'url': reverse('stores:store_update', kwargs={'store_id': obj.pk}),
                    'icon': 'bi bi-pencil',
                    'active': request.resolver_match.url_name == 'store_update',
                    'permission': 'stores.change_store'
                },
                {
                    'name': 'Inventory',
                    'url': reverse('stores:store_inventory', kwargs={'store_id': obj.pk}),
                    'icon': 'bi bi-boxes',
                    'active': request.resolver_match.url_name == 'store_inventory',
                    'permission': 'inventory.view_stock'
                }
            ]

        # Add more object types as needed
        elif obj_type == 'user':
            nav_items = [
                {
                    'name': 'Profile',
                    'url': reverse('users:user_detail', kwargs={'user_id': obj.pk}),
                    'icon': 'bi bi-person',
                    'active': request.resolver_match.url_name == 'user_detail'
                },
                {
                    'name': 'Edit',
                    'url': reverse('users:user_update', kwargs={'user_id': obj.pk}),
                    'icon': 'bi bi-pencil',
                    'active': request.resolver_match.url_name == 'user_update',
                    'permission': 'users.change_user'
                }
            ]

    except NoReverseMatch as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(f"URL reverse failed for {obj_type}: {e}")

    # Filter based on permissions and update active status
    filtered_items = []
    for item in nav_items:
        # Check permission
        if 'permission' in item:
            if not user.has_perm(item['permission']):
                continue

        # Update active status based on current URL
        current_url_name = request.resolver_match.url_name
        if 'active' in item:
            # Override with actual check
            item['active'] = item.get('url_name', current_url_name) == current_url_name

        filtered_items.append(item)

    return filtered_items


@register.simple_tag
def has_nav_permission(user, permission):
    """
    Check if user has specific permission for navigation
    """
    if not permission or not user or not user.is_authenticated:
        return False

    try:
        if isinstance(permission, str):
            return user.has_perm(permission)
        elif isinstance(permission, (list, tuple)):
            return any(user.has_perm(perm) for perm in permission)
        else:
            return False
    except Exception:
        return False


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
        elif isinstance(obj, (int, str)):
            return obj
        else:
            return None
    except Exception:
        return None


@register.simple_tag(takes_context=True)
def build_nav_context(context, **kwargs):
    """
    Build navigation context from template variables
    Usage: {% build_nav_context company=company store=store as nav_ctx %}
    """
    nav_context = context.get('nav_context', {}).copy()

    # Clean kwargs - remove None values
    clean_kwargs = {k: v for k, v in kwargs.items() if v is not None}
    nav_context.update(clean_kwargs)

    return nav_context


@register.filter
def is_nav_item_active(nav_item):
    """
    Returns True if the nav_item is active.
    Assumes nav_item has an 'active' property or attribute.
    """
    try:
        return getattr(nav_item, "active", False)
    except Exception:
        return False


@register.simple_tag(takes_context=True)
def nav_item_classes(context, nav_item, base_class=""):
    """
    Generate CSS classes for navigation item including active state
    Usage: class="{% nav_item_classes nav_item 'nav-link' %}"
    """
    classes = [base_class] if base_class else []

    # Check if item is active
    if is_section_active(context, nav_item):
        classes.append('active')

    # Add custom CSS class if available
    custom_class = getattr(nav_item, 'css_class', None)
    if custom_class:
        classes.append(custom_class)

    return ' '.join(classes)


@register.simple_tag(takes_context=True)
def render_nav_icon(context, nav_item, default_icon="bi-circle"):
    """
    Render icon for navigation item with fallback
    """
    icon_class = getattr(nav_item, 'icon', None)
    if not icon_class:
        return f'<i class="bi {default_icon}"></i>'

    return f'<i class="{icon_class}"></i>'


@register.filter
def can_view_nav_item(nav_item, user):
    """
    Check if user can view this navigation item
    """
    try:
        if hasattr(nav_item, 'is_visible'):
            return nav_item.is_visible(user)
        return True
    except Exception:
        return False


@register.simple_tag
def nav_debug_info(nav_item):
    """
    Debug information for navigation items (development only)
    """
    if not nav_item:
        return "No nav item"

    info = {
        'name': getattr(nav_item, 'name', 'Unknown'),
        'url_name': getattr(nav_item, 'url_name', 'None'),
        'children_count': len(getattr(nav_item, 'children', [])),
        'has_permission_check': hasattr(nav_item, 'is_visible'),
    }

    return str(info)


# Global navigation context processor
def navigation_context(request):
    """
    Context processor to add navigation data to all templates
    """
    context = {}

    if request.user.is_authenticated:
        try:
            # Add basic navigation context
            context['has_navigation'] = True
            # You can add more global navigation context here
        except Exception:
            context['has_navigation'] = False

    return context