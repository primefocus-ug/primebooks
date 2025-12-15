from django.utils.translation import gettext_lazy as _

def sales_context(request):
    """Add sales-related context to all templates"""
    from .models import Sale

    context = {
        'TAX_RATES': dict(SaleItem.TAX_RATE_CHOICES),
        'PAYMENT_METHODS': dict(Sale.PAYMENT_METHODS),
        'DOCUMENT_TYPES': dict(Sale.DOCUMENT_TYPES),
        'STATUS_CHOICES': dict(Sale.STATUS_CHOICES),
        'EFRIS_ENABLED': getattr(request.user, 'company.efris_enabled', False) if request.user.is_authenticated else False,
    }

    # Convert to JSON for JavaScript
    import json
    context['tax_rates_json'] = json.dumps([
        {'value': value, 'label': str(label)}
        for value, label in SaleItem.TAX_RATE_CHOICES
    ])

    context['payment_modes_json'] = json.dumps({
        'CASH': '102',
        'CARD': '106',
        'MOBILE_MONEY': '105',
        'BANK_TRANSFER': '107',
        'VOUCHER': '101',
        'CREDIT': '101'
    })

    return context