from django.urls import path, include
from django.views.generic import TemplateView
from django.contrib.sitemaps.views import sitemap
from public_seo.sitemaps import PublicSitemap

sitemaps = {
    'public': PublicSitemap,
}

urlpatterns = [
    # Homepage
    path('', TemplateView.as_view(template_name='public_router/home.html'), name='home'),
    path('public-admin/', include('public_accounts.urls')),
    # Marketing pages
    path('pricing/', TemplateView.as_view(template_name='public_router/pricing.html'), name='pricing'),
    path('features/', TemplateView.as_view(template_name='public_router/features.html'), name='features'),
    path('about/', TemplateView.as_view(template_name='public_router/about.html'), name='about'),

    # Tenant signup
    path('prime-books/', include('public_router.urls')),

    # Blog
    path('blog/', include('public_blog.urls')),

    # Support
    path('support/', include('public_support.urls')),

    # Analytics
    path('auth/', include('public_admin.urls')),
    path('analytics/', include('public_analytics.urls')),
    # SEO
    path('sitemap.xml', sitemap, {'sitemaps': sitemaps}, name='sitemap'),
    path('seo/', include('public_seo.urls')),

    # Health check
    path('health/', TemplateView.as_view(template_name='public_router/health.html'), name='health'),
]