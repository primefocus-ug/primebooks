from django import template
from django.utils.safestring import mark_safe
import json

register = template.Library()


@register.inclusion_tag('public_seo/meta_tags.html')
def render_seo_meta(seo_data=None):
    """
    Render SEO meta tags.
    Usage: {% load seo_tags %}{% render_seo_meta seo %}
    """
    return {'seo': seo_data or {}}


@register.filter
def jsonld(data):
    """
    Convert dict to JSON-LD script tag.
    Usage: {{ structured_data|jsonld }}
    """
    if not data:
        return ''

    json_str = json.dumps(data, indent=2)
    return mark_safe(f'<script type="application/ld+json">{json_str}</script>')