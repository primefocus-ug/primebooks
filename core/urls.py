from django.urls import path
from . import views

app_name = 'nav_preferences'

urlpatterns = [
    path('',                        views.get_nav_preferences,         name='get'),
    path('save/',                   views.save_nav_preferences,        name='save'),
    path('structure/',              views.get_nav_structure,           name='structure'),
    path('reset-layout/',           views.reset_layout_to_tenant_default, name='reset_layout'),
    path('tenant-default/',         views.get_tenant_default,          name='tenant_default_get'),
    path('tenant-default/save/',    views.save_tenant_default,         name='tenant_default_save'),
]

