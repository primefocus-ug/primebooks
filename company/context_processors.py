def current_company(request):
    company = getattr(request, 'tenant', None)
    return {
        'company': company,
        'currency': company.preferred_currency if company else None,
        'company_logo': company.logo.url if company and company.logo else None,
        'company_brand_primary': company.brand_colors.get('primary') if company else '#000',
        'company_brand_secondary': company.brand_colors.get('secondary') if company else '#FFF',
        'is_trial': company.is_trial if company else False,
        'subscription_active': company.status == 'ACTIVE' if company else False,
    }

def efris_settings(request):
    """
    Global context processor to make EFRIS status available in all templates
    """
    efris_enabled = False
    company = None
    
    # Check if user is authenticated and has a company
    if hasattr(request, 'user') and request.user.is_authenticated:
        # For multi-tenant setup
        if hasattr(request, 'tenant'):
            company = request.tenant
            efris_enabled = getattr(company, 'efris_enabled', False)
        # Fallback: get from user's store
        elif hasattr(request.user, 'stores') and request.user.stores.exists():
            store = request.user.stores.first()
            if store and hasattr(store, 'company'):
                company = store.company
                efris_enabled = getattr(company, 'efris_enabled', False)
    
    return {
        'EFRIS_ENABLED': efris_enabled,
        'efris_enabled': efris_enabled,  # lowercase alias
        'company': company,
    }