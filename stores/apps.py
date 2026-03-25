from django.apps import AppConfig


class StoresConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'stores'

    module_key = 'stores'

    def ready(self):
        import stores.signals
