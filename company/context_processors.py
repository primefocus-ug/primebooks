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
