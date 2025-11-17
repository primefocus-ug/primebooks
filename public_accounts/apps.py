from django.apps import AppConfig


class PublicAccountsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'public_accounts'

    def ready(self):
        try:
            import public_accounts.public_admin  # noqa
        except ImportError:
            pass