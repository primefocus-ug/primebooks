from django.apps import AppConfig


class PublicSeoConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'public_seo'

    def ready(self):
        try:
            import public_seo.public_admin  # noqa
        except ImportError:
            pass
