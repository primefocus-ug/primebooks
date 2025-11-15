from django.db import connection


def current_company(request):
    """
    Add current company to template context
    Handles multi-tenant setup with proper fallbacks
    """
    # Skip company context for public schema
    if connection.schema_name == 'public':
        return {
            'company': None,
            'currency': None,
            'company_logo': None,
            'company_brand_primary': '#000',
            'company_brand_secondary': '#FFF',
            'is_trial': False,
            'subscription_active': False,
        }

    company = getattr(request, 'tenant', None)

    # Check if company exists and has the required attributes (not FakeTenant)
    if company and hasattr(company, 'preferred_currency'):
        return {
            'company': company,
            'currency': company.preferred_currency,
            'company_logo': company.logo.url if hasattr(company, 'logo') and company.logo else None,
            'company_brand_primary': company.brand_colors.get('primary') if hasattr(company,
                                                                                    'brand_colors') and company.brand_colors else '#000',
            'company_brand_secondary': company.brand_colors.get('secondary') if hasattr(company,
                                                                                        'brand_colors') and company.brand_colors else '#FFF',
            'is_trial': company.is_trial if hasattr(company, 'is_trial') else False,
            'subscription_active': (company.status == 'ACTIVE') if hasattr(company, 'status') else False,
        }

    # Default fallback for FakeTenant or missing tenant
    return {
        'company': None,
        'currency': None,
        'company_logo': None,
        'company_brand_primary': '#000',
        'company_brand_secondary': '#FFF',
        'is_trial': False,
        'subscription_active': False,
    }


def efris_settings(request):
    """
    Global context processor to make EFRIS status available in all templates
    """
    # Skip for public schema
    if connection.schema_name == 'public':
        return {
            'EFRIS_ENABLED': False,
            'efris_enabled': False,
            'company': None,
        }

    efris_enabled = False
    company = None

    # Check if user is authenticated and has a company
    if hasattr(request, 'user') and request.user.is_authenticated:
        # For multi-tenant setup
        if hasattr(request, 'tenant') and hasattr(request.tenant, 'efris_enabled'):
            company = request.tenant
            efris_enabled = getattr(company, 'efris_enabled', False)
        # Fallback: get from user's store
        elif hasattr(request.user, 'stores'):
            try:
                if request.user.stores.exists():
                    store = request.user.stores.first()
                    if store and hasattr(store, 'company'):
                        company = store.company
                        efris_enabled = getattr(company, 'efris_enabled', False)
            except Exception:
                # Catch any database errors in public schema
                pass

    return {
        'EFRIS_ENABLED': efris_enabled,
        'efris_enabled': efris_enabled,
        'company': company,
    }