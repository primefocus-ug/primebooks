from django.apps import AppConfig


class SalesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'sales'

    module_key = 'sales'

    def ready(self):
        import sales.signals
        import sales.cache
