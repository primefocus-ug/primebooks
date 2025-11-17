from django.apps import AppConfig


class PublicAdminConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'public_admin'

    def ready(self):
        try:
            import public_admin.public_admin  # noqa
        except ImportError:
            pass