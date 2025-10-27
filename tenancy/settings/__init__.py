"""
Settings module initialization
"""
import os

settings_module = os.getenv('DJANGO_SETTINGS_MODULE', 'tenancy.settings.development')

if 'production' in settings_module:
    from .production import *
elif 'staging' in settings_module:
    from .staging import *
else:
    from .development import *