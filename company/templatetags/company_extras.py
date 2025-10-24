from django import template

register = template.Library()

@register.filter
def format_currency(amount, company):
    if not company:
        return amount
    symbol_map = {
        'UGX': 'UGX',
        'USD': '$',
        'KES': 'KSh',
        'EUR': '€',
        'GBP': '£',
    }
    symbol = symbol_map.get(company.preferred_currency, company.preferred_currency)
    return f"{symbol} {amount:,.2f}"
