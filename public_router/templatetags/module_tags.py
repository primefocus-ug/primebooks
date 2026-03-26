from django import template
register = template.Library()

_ICON_TO_EMOJI = {
    'bi bi-cart-check':             '🛒',
    'bi bi-boxes':                  '📦',
    'bi bi-cash-stack':             '💰',
    'bi bi-receipt':                '🧾',
    'bi bi-people-fill':            '👥',
    'bi bi-file-earmark-bar-graph': '📊',
    'bi bi-receipt-cutoff':         '🧾',
    'bi bi-display':                '🖥️',
    'bi bi-chat-dots':              '💬',
    'bi bi-arrow-repeat':           '🔄',
    'bi bi-egg-fried':              '🍳',
}

@register.filter
def icon_to_emoji(icon_class):
    return _ICON_TO_EMOJI.get(icon_class, '⚙️')

@register.filter
def in_list(value, list_string):
    return value in [x.strip() for x in list_string.split(',')]