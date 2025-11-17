from django.apps import AppConfig


class PublicAnalyticsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'public_analytics'

    def ready(self):
        try:
            import public_analytics.public_admin  # noqa
        except ImportError:
            pass
