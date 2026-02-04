# primebooks/apps.py (or your main app's apps.py)

from django.apps import AppConfig


class PrimebooksConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'primebooks'

