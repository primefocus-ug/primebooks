from django.apps import AppConfig


class CompanyConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'company'

    def ready(self):
        import company.signals
        try:
            import company.public_admin  # noqa
        except ImportError:
            pass