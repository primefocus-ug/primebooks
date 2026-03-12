from django.urls import path
from . import views
from .decorators import pending_approval

app_name = 'referral'

urlpatterns = [
    # Auth
    path('register/', views.partner_register, name='register'),
    path('login/', views.partner_login, name='login'),
    path('logout/', views.partner_logout, name='logout'),
    path('pending-approval/', pending_approval, name='pending_approval'),

    # Dashboard
    path('dashboard/', views.dashboard, name='dashboard'),
    path('referrals/', views.referrals_list, name='referrals_list'),
    path('profile/', views.profile, name='profile'),
]