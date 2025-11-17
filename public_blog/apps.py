from django.apps import AppConfig


class PublicBlogConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'public_blog'
    verbose_name = 'Public Blog'

    def ready(self):
        """Import admin when app is ready"""
        try:
            import public_blog.public_admin  # noqa
        except ImportError:
            pass