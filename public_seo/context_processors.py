from .models import SEOPage


def seo_metadata(request):
    """
    Add SEO metadata to template context.
    Add to TEMPLATES['OPTIONS']['context_processors'] in settings.py
    """

    from django.db import connection

    # Only for public schema
    if connection.schema_name != 'public':
        return {}

    try:
        # Try to find SEO data for current path
        seo_page = SEOPage.objects.filter(
            url_path=request.path,
            is_active=True
        ).first()

        if seo_page:
            return {
                'seo': {
                    'title': seo_page.title,
                    'description': seo_page.meta_description,
                    'meta_tags': seo_page.get_meta_tags(),
                    'og_tags': seo_page.get_og_tags(),
                    'twitter_tags': seo_page.get_twitter_tags(),
                    'structured_data': seo_page.structured_data,
                }
            }
    except:
        pass

    # Default SEO
    return {
        'seo': {
            'title': 'Your SaaS Platform - Manage Your Business',
            'description': 'The best SaaS platform for managing your business.',
            'meta_tags': {},
            'og_tags': {},
            'twitter_tags': {},
            'structured_data': {},
        }
    }