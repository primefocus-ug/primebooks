from django.urls import path, include
from django.views.generic import TemplateView
from django.contrib.sitemaps.views import sitemap
from public_seo.sitemaps import PublicSitemap
from pesapal_integration.ipn import platform_ipn, tenant_ipn
from pesapal_integration.invoice_payment_views import (
    InvoicePaymentView,
    InvoicePaymentCallbackView,
    InvoicePaymentCancelledView,
)
from public_router.views import download_center

sitemaps = {
    'public': PublicSitemap,
}

urlpatterns = [
    # ── Homepage ──────────────────────────────────────────────────────────
    path('', TemplateView.as_view(template_name='public_router/home.html'), name='home'),
    path('public-admin/', include('public_accounts.urls')),

    # ── Marketing pages ───────────────────────────────────────────────────
    path('pricing/',    TemplateView.as_view(template_name='public_router/pricing.html'),   name='pricing'),
    path('features/',   TemplateView.as_view(template_name='public_router/features.html'),  name='features'),
    path('about/',      TemplateView.as_view(template_name='public_router/about.html'),     name='about'),
    path('health/',     TemplateView.as_view(template_name='public_router/health.html'),    name='health'),

    # ── Desktop App Download Center ───────────────────────────────────────
    # Accessible at primebooks.sale/download/
    # The page JS calls /api/v1/releases/ for version data at runtime.
    path('download/', download_center, name='download'),

    # ── Partner / referral ────────────────────────────────────────────────
    path('partners/', include('referral.urls')),

    # ── Tenant signup & app ───────────────────────────────────────────────
    path('prime-books/', include('public_router.urls')),
    path('saas-support/', include('public_calls.urls')),

    # ── Blog ──────────────────────────────────────────────────────────────
    path('blog/', include('public_blog.urls')),

    # ── Support ───────────────────────────────────────────────────────────
    path('support/', include('public_support.urls')),

    # ── Analytics / Auth ─────────────────────────────────────────────────
    path('auth/', include('public_admin.urls')),
    path('analytics/', include('public_analytics.urls')),

    # ── SEO ───────────────────────────────────────────────────────────────
    path('sitemap.xml', sitemap, {'sitemaps': sitemaps}, name='sitemap'),
    path('seo/', include('public_seo.urls')),

    # ── Pesapal IPN (public, CSRF-exempt) ────────────────────────────────
    path('pesapal/ipn/platform/',
         platform_ipn, name='platform_ipn'),
    path('pesapal/ipn/tenant/<str:tenant_slug>/',
         tenant_ipn, name='tenant_ipn'),

    # ── Public invoice payment links (no login needed) ────────────────────
    path('pay/invoice/<str:token>/',
         InvoicePaymentView.as_view(), name='pay_invoice'),
    path('pay/invoice/<str:token>/callback/',
         InvoicePaymentCallbackView.as_view(), name='pay_invoice_callback'),
    path('pay/invoice/<str:token>/cancelled/',
         InvoicePaymentCancelledView.as_view(), name='pay_invoice_cancelled'),

    # ── API v1 (desktop updater + download center data) ───────────────────
    # Endpoints under here:
    #   GET  /api/v1/updates/check/   — desktop update check (auth required)
    #   POST /api/v1/crash-reports/   — crash intake (auth required)
    #   GET  /api/v1/releases/        — public releases list (no auth)
    path('api/v1/', include('saad.urls')),
]