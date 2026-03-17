"""
support_widget/context_processors.py

Injects `sw_config` into every template.
Add to TEMPLATES[0]['OPTIONS']['context_processors']:
    'support_widget.context_processors.support_widget_context',
"""

from django.db import connection


def support_widget_context(request):
    """
    Provides sw_config to templates so widget_embed.html can read
    brand_color, greeting, etc. without an extra DB call in the template.

    Skips cleanly on the public schema (admin panel / landing pages).
    """
    try:
        schema = getattr(connection, 'schema_name', 'public')
        if schema == 'public':
            return {'sw_config': None}

        from .models import SupportWidgetConfig
        config, _ = SupportWidgetConfig.objects.get_or_create(pk=1)

        if not config.is_active:
            return {'sw_config': None}

        return {'sw_config': config}

    except Exception:
        return {'sw_config': None}