from django.apps import AppConfig


class PublicRouterConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'public_router'

    def ready(self):
        try:
            import public_router.public_admin  # noqa
        except ImportError:
            pass
