# reports/services/currency_formatter.py
"""
Currency formatting utilities.
Reads preferred_currency from the Company model (company.preferred_currency).
Falls back to UGX if not set.
"""

CURRENCY_SYMBOLS = {
    'UGX': 'UGX',
    'USD': '$',
    'EUR': '€',
    'GBP': '£',
    'KES': 'KES',
    'TZS': 'TZS',
    'RWF': 'RWF',
    'ETB': 'ETB',
    'ZAR': 'R',
    'NGN': '₦',
    'GHS': 'GH₵',
}

CURRENCY_NAMES = {
    'UGX': 'Uganda Shillings',
    'USD': 'US Dollars',
    'EUR': 'Euros',
    'GBP': 'British Pounds',
    'KES': 'Kenyan Shillings',
    'TZS': 'Tanzanian Shillings',
    'RWF': 'Rwandan Francs',
    'ETB': 'Ethiopian Birr',
    'ZAR': 'South African Rand',
    'NGN': 'Nigerian Naira',
    'GHS': 'Ghanaian Cedis',
}

# Currencies that don't use decimals
NO_DECIMAL_CURRENCIES = {'UGX', 'RWF', 'TZS'}


class CurrencyFormatter:
    """
    Per-request currency formatter. Instantiate once with the user's company
    and reuse across the report. Thread-safe (no mutable state after init).
    """

    def __init__(self, company=None, currency_code: str = None):
        if currency_code:
            self.code = currency_code.upper()
        elif company and hasattr(company, 'preferred_currency'):
            self.code = (company.preferred_currency or 'UGX').upper()
        else:
            self.code = 'UGX'

        self.symbol = CURRENCY_SYMBOLS.get(self.code, self.code)
        self.name = CURRENCY_NAMES.get(self.code, self.code)
        self.use_decimals = self.code not in NO_DECIMAL_CURRENCIES

    def format(self, value, show_symbol: bool = True) -> str:
        """Format a numeric value as currency."""
        if value is None:
            value = 0
        try:
            value = float(value)
        except (TypeError, ValueError):
            return str(value)

        if self.use_decimals:
            formatted = f"{value:,.2f}"
        else:
            formatted = f"{int(round(value)):,}"

        if show_symbol:
            return f"{self.symbol} {formatted}"
        return formatted

    def format_short(self, value) -> str:
        """Compact format for tight spaces: 1,234,567 → 1.2M"""
        if value is None:
            value = 0
        try:
            value = float(value)
        except (TypeError, ValueError):
            return str(value)

        abs_val = abs(value)
        sign = '-' if value < 0 else ''

        if abs_val >= 1_000_000_000:
            return f"{sign}{self.symbol} {abs_val / 1_000_000_000:.1f}B"
        elif abs_val >= 1_000_000:
            return f"{sign}{self.symbol} {abs_val / 1_000_000:.1f}M"
        elif abs_val >= 1_000:
            return f"{sign}{self.symbol} {abs_val / 1_000:.1f}K"
        else:
            return self.format(value)

    def format_delta(self, current, prior) -> str:
        """Format the difference between two periods, e.g. '+UGX 1,200,000'"""
        if prior is None or prior == 0:
            return "no prior data"
        delta = float(current or 0) - float(prior or 0)
        sign = '+' if delta >= 0 else ''
        return f"{sign}{self.format(delta)}"

    def growth_pct(self, current, prior) -> float | None:
        """Calculate percentage growth. Returns None if prior is zero."""
        try:
            current = float(current or 0)
            prior = float(prior or 0)
        except (TypeError, ValueError):
            return None
        if prior == 0:
            return None
        return ((current - prior) / prior) * 100


def get_formatter(user=None, company=None) -> CurrencyFormatter:
    """
    Convenience: resolve formatter from a user or company object.
    Usage:
        fmt = get_formatter(user=request.user)
        fmt = get_formatter(company=some_company)
    """
    if company is None and user is not None:
        company = getattr(user, 'company', None)
    return CurrencyFormatter(company=company)