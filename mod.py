#!/usr/bin/env python
"""
List all Django models in the project, separating shared and tenant apps (for django-tenants)
Run: python list_models.py
"""
import os
import sys
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'tenancy.settings')
sys.path.insert(0, os.getcwd())
django.setup()

from django.apps import apps
from django.conf import settings

# Define shared and tenant apps
shared_apps = getattr(settings, 'SHARED_APPS', [])
tenant_apps = getattr(settings, 'TENANT_APPS', [])

def get_models_for_apps(app_list):
    """Return a dict of models for the given list of app labels"""
    models_dict = {}
    for model in apps.get_models():
        app_label = model._meta.app_label
        model_name = model.__name__
        if app_label in app_list:
            models_dict.setdefault(app_label, []).append(model_name)
    return models_dict

# Get models
shared_models = get_models_for_apps(shared_apps)
tenant_models = get_models_for_apps(tenant_apps)

# Function to print models nicely
def print_models(models_dict, title):
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)
    for app_label in sorted(models_dict.keys()):
        print(f"\n{app_label.upper()}:")
        for model_name in sorted(models_dict[app_label]):
            print(f"  • {app_label}.{model_name}")
    total_models = sum(len(v) for v in models_dict.values())
    print("\n" + "=" * 60)
    print(f"Total: {total_models} models across {len(models_dict)} apps")
    print("=" * 60)

# Print separately
print_models(shared_models, "SHARED APPS MODELS")
print_models(tenant_models, "TENANT APPS MODELS")
