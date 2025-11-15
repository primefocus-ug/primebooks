from django.contrib.sitemaps import Sitemap
from .models import Sitemap as SitemapEntry


class PublicSitemap(Sitemap):
    """
    Dynamic sitemap from database.
    """

    changefreq = "weekly"
    priority = 0.5

    def items(self):
        return SitemapEntry.objects.filter(is_active=True)

    def location(self, obj):
        return obj.url_path

    def lastmod(self, obj):
        return obj.last_modified

    def changefreq(self, obj):
        return obj.change_frequency

    def priority(self, obj):
        return obj.priority