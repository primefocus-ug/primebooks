from django.contrib.auth import get_user_model
from accounts.utils import get_accessible_companies
from .views import get_user_type_display_from_role

User = get_user_model()


def saas_admin_context(request):
    """
    Add SaaS admin context to all templates
    """
    context = {
        'is_saas_admin': False,
        'can_access_all_companies': False,
        'accessible_companies': [],
        'current_tenant': None,
        'show_tenant_switcher': False,
    }

    if hasattr(request, 'user') and request.user.is_authenticated:
        user = request.user

        context.update({
            'is_saas_admin': getattr(user, 'is_saas_admin', False),
            'can_access_all_companies': getattr(user, 'can_access_all_companies', False),
            'accessible_companies': get_accessible_companies(user),
            'current_tenant': getattr(request, 'tenant', None),
            'show_tenant_switcher': getattr(user, 'is_saas_admin', False),
        })

    return context


def user_role_context(request):

    if not request.user.is_authenticated:
        return {}

    return {
        'user_primary_role': request.user.primary_role,
        'user_all_roles': request.user.all_roles,
        'user_role_names': request.user.role_names,
        'user_display_role': request.user.display_role,
        'user_role_priority': request.user.highest_role_priority,
        # Backward compatibility
        'user_type_display': get_user_type_display_from_role(request.user),
    }