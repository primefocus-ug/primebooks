from django.urls import path
from . import views
from .decorators import pending_approval

app_name = 'referral'

urlpatterns = [
    # ── Auth ────────────────────────────────────────────────────────────────
    path('register/',        views.partner_register, name='register'),
    path('login/',           views.partner_login,    name='login'),
    path('logout/',          views.partner_logout,   name='logout'),
    path('pending-approval/', pending_approval,      name='pending_approval'),

    # ── Password reset (unauthenticated flow) ────────────────────────────────
    path('forgot-password/',
         views.forgot_password,      name='forgot_password'),
    path('forgot-password/done/',
         views.forgot_password_done, name='forgot_password_done'),
    path('password-reset/<uidb64>/<token>/',
         views.password_reset_confirm, name='password_reset_confirm'),

    # ── Change password / email (authenticated) ──────────────────────────────
    path('change-password/',
         views.change_password, name='change_password'),
    path('change-email/',
         views.change_email,    name='change_email'),
    path('confirm-email-change/<uidb64>/<token>/',
         views.confirm_email_change, name='confirm_email_change'),

    # ── Dashboard ────────────────────────────────────────────────────────────
    path('dashboard/',   views.dashboard,      name='dashboard'),
    path('referrals/',   views.referrals_list, name='referrals_list'),
    path('profile/',     views.profile,        name='profile'),
    path('earnings/',    views.earnings,        name='earnings'),

    # ── QR Code & Share Cards ────────────────────────────────────────────────
    path('qr/',              views.qr_dashboard,   name='qr_dashboard'),
    path('qr-code/',         views.qr_code_svg,    name='qr_code'),
    path('share-card-data/', views.share_card_data, name='share_card_data'),
]