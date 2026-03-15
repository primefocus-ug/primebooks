"""
onboarding/urls.py

Include in main urls.py:
    path('onboarding/', include('onboarding.urls')),
"""

from django.urls import path
from . import views

urlpatterns = [
    path('complete-step/',  views.complete_step,      name='onboarding_complete_step'),
    path('welcome-seen/',   views.mark_welcome_seen,  name='onboarding_welcome_seen'),
    path('dismiss/',        views.dismiss_onboarding, name='onboarding_dismiss'),
    path('progress/',       views.get_progress,       name='onboarding_progress'),
]