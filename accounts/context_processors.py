from django.contrib.auth import get_user_model
from accounts.utils import get_accessible_companies

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