from django import template
from django.utils.safestring import mark_safe
from django.conf import settings
import json

register = template.Library()


@register.inclusion_tag('efris/websocket_client.html')
def efris_websocket_client(company_id, auto_connect=True):
    """Template tag to include EFRIS WebSocket client"""
    context = {
        'company_id': company_id,
        'auto_connect': auto_connect,
        'websocket_settings': getattr(settings, 'EFRIS_WEBSOCKET_SETTINGS', {})
    }
    return context


@register.simple_tag
def efris_websocket_config(company_id):
    """Generate WebSocket configuration JSON"""
    config = {
        'company_id': company_id,
        'websocket_url': f'ws://localhost:8000/ws/efris/company/{company_id}/',  # Update with your domain
        'settings': getattr(settings, 'EFRIS_WEBSOCKET_SETTINGS', {}),
        'debug': settings.DEBUG
    }
    return mark_safe(json.dumps(config))
