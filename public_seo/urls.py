from django.urls import path
from django.contrib.sitemaps.views import sitemap
from .sitemaps import PublicSitemap
from .views import RobotsTxtView

app_name = 'public_seo'

sitemaps = {
    'public_seo': PublicSitemap,
}

urlpatterns = [
    path('sitemap.xml', sitemap, {'sitemaps': sitemaps}, name='sitemap'),
    path('robots.txt', RobotsTxtView.as_view(), name='robots'),
]