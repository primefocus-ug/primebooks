from django.contrib.auth import get_user_model
from accounts.utils import get_accessible_companies
from .views import get_user_type_display_from_role
from public_accounts.models import PublicUser
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
    """Add user role info safely to templates"""
    user = getattr(request, 'user', None)

    if not user or not user.is_authenticated:
        return {}

    # Only apply tenant-specific attributes if this is a CustomUser
    if isinstance(user, User):  # Your tenant user model
        return {
            'user_primary_role': getattr(user, 'primary_role', None),
            'user_all_roles': getattr(user, 'all_roles', []),
            'user_role_names': getattr(user, 'role_names', []),
            'user_display_role': getattr(user, 'display_role', ''),
            'user_role_priority': getattr(user, 'highest_role_priority', None),
            # Backward compatibility
            'user_type_display': get_user_type_display_from_role(user),
        }

    # If it's a PublicUser, return minimal info
    elif isinstance(user, PublicUser):
        return {
            'user_primary_role': None,
            'user_all_roles': [],
            'user_role_names': [],
            'user_display_role': 'Public',
            'user_role_priority': None,
            'user_type_display': 'Public',
        }

    # Fallback for other unexpected user types
    return {}

from django.conf import settings

def version_context(request):
    return {
        'APP_VERSION': settings.APP_VERSION,
        'VERSION_FULL': settings.APP_VERSION,
    }


def maintenance_info(request):
    return {
        "MAINTENANCE_ACTIVE": getattr(settings, "MAINTENANCE_ACTIVE", False),
        "MAINTENANCE_START_TIME": (
            settings.MAINTENANCE_START_TIME.isoformat()
            if getattr(settings, "MAINTENANCE_START_TIME", None)
            else None
        ),
        "MAINTENANCE_MESSAGE": getattr(
            settings,
            "MAINTENANCE_MESSAGE",
            "System maintenance scheduled."
        ),
    }

