from django.apps import AppConfig


class PublicSupportConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'public_support'

    def ready(self):
        try:
            import public_support.public_admin
        except ImportError:
            pass
