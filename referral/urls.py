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
    path('earnings/', views.earnings, name='earnings'),

    # QR Code & Share Cards
    path('qr/', views.qr_dashboard, name='qr_dashboard'),
    path('qr-code/', views.qr_code_svg, name='qr_code'),
    path('share-card-data/', views.share_card_data, name='share_card_data'),
]