from django.urls import path
from .views import general_views as  views

app_name = 'legal'

urlpatterns = [
    path('terms/', views.TermsOfServiceView.as_view(), name='terms'),
    path('privacy/', views.PrivacyPolicyView.as_view(), name='privacy'),
    path('cookies/', views.CookiePolicyView.as_view(), name='cookies'),
]