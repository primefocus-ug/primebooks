from django.conf import settings

def error_context_processor(request):
    """
    Add error-related context to all templates
    """
    return {
        'site_name': getattr(settings, 'SITE_NAME', 'Website'),
        'support_email': getattr(settings, 'SUPPORT_EMAIL', ''),
        'maintenance_mode': getattr(settings, 'MAINTENANCE_MODE', False),
        'debug_mode': settings.DEBUG,
    }