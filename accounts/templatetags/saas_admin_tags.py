from django.db import connection
from django import template
from django.contrib.auth import get_user_model
from accounts.utils import get_visible_users, get_company_user_count, get_accessible_companies

register = template.Library()
User = get_user_model()


@register.simple_tag
def visible_users_count(company=None):
    """Get count of visible users, optionally filtered by company"""
    queryset = User.objects.all()
    if company:
        queryset = queryset.filter(company=company)
    return get_visible_users(queryset).count()


@register.simple_tag
def company_user_count(company):
    """Get user count for a specific company"""
    return get_company_user_count(company)


@register.simple_tag
def accessible_companies(user):
    """Get companies accessible to a user"""
    return get_accessible_companies(user)


@register.filter
def is_saas_admin(user):
    """Check if user is a SaaS admin"""
    return getattr(user, 'is_saas_admin', False)


@register.filter
def can_access_all_companies(user):
    """Check if user can access all companies"""
    return getattr(user, 'can_access_all_companies', False)


@register.inclusion_tag('accounts/saas_admin_switcher.html', takes_context=True)
def saas_admin_tenant_switcher(context):
    """Render tenant switcher for SaaS admins"""
    request = context['request']
    user = request.user

    if not getattr(user, 'is_saas_admin', False):
        return {'show_switcher': False}

    return {
        'show_switcher': True,
        'current_tenant': getattr(request, 'tenant', None),
        'available_tenants': get_accessible_companies(user),
        'request': request
    }

def get_current_tenant():
    """Get the current tenant from the connection"""
    return getattr(connection, 'tenant', None)


def get_tenant_domain_url():
    """Get the current tenant's domain URL"""
    tenant = get_current_tenant()
    if tenant and hasattr(tenant, 'domains'):
        primary_domain = tenant.domains.filter(is_primary=True).first()
        if primary_domain:
            return primary_domain.domain
    return None


def get_tenant_schema_name():
    """Get the current tenant's schema name"""
    return getattr(connection, 'schema_name', 'public')


def is_public_schema():
    """Check if we're in the public schema"""
    return get_tenant_schema_name() == 'public'

