from django.db import models
from django.urls import reverse
from django.utils.text import slugify
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone
import json


class SEOPage(models.Model):
    """
    SEO metadata for public pages.
    Manages meta tags, Open Graph, Twitter Cards, structured data.
    """

    PAGE_TYPES = [
        ('HOME', 'Homepage'),
        ('PRICING', 'Pricing Page'),
        ('FEATURES', 'Features Page'),
        ('ABOUT', 'About Page'),
        ('BLOG_HOME', 'Blog Homepage'),
        ('BLOG_POST', 'Blog Post'),
        ('CONTACT', 'Contact Page'),
        ('SIGNUP', 'Signup Page'),
        ('CUSTOM', 'Custom Page'),
    ]

    # Page Identification
    page_type = models.CharField(max_length=20, choices=PAGE_TYPES, unique=True)
    url_path = models.CharField(
        max_length=255,
        unique=True,
        help_text="URL path (e.g., /pricing/, /features/)"
    )

    # Basic SEO
    title = models.CharField(
        max_length=70,
        help_text="Page title (60-70 characters optimal)"
    )
    meta_description = models.CharField(
        max_length=160,
        help_text="Meta description (150-160 characters optimal)"
    )
    meta_keywords = models.CharField(
        max_length=255,
        blank=True,
        help_text="Comma-separated keywords"
    )

    # Advanced SEO
    canonical_url = models.URLField(blank=True, null=True)
    robots_meta = models.CharField(
        max_length=100,
        default='index, follow',
        help_text="e.g., 'index, follow' or 'noindex, nofollow'"
    )

    # Open Graph (Facebook, LinkedIn)
    og_title = models.CharField(max_length=95, blank=True)
    og_description = models.CharField(max_length=200, blank=True)
    og_image = models.ImageField(
        upload_to='seo/og_images/',
        blank=True,
        null=True,
        help_text="1200x630px recommended"
    )
    og_type = models.CharField(
        max_length=50,
        default='website',
        help_text="e.g., 'website', 'article', 'product'"
    )

    # Twitter Card
    twitter_card = models.CharField(
        max_length=50,
        default='summary_large_image',
        choices=[
            ('summary', 'Summary'),
            ('summary_large_image', 'Summary Large Image'),
            ('app', 'App'),
            ('player', 'Player'),
        ]
    )
    twitter_title = models.CharField(max_length=70, blank=True)
    twitter_description = models.CharField(max_length=200, blank=True)
    twitter_image = models.ImageField(
        upload_to='seo/twitter_images/',
        blank=True,
        null=True
    )

    # Structured Data (Schema.org JSON-LD)
    structured_data = models.JSONField(
        default=dict,
        blank=True,
        help_text="Schema.org JSON-LD structured data"
    )

    # Analytics
    focus_keyword = models.CharField(
        max_length=100,
        blank=True,
        help_text="Primary keyword for this page"
    )
    secondary_keywords = models.TextField(
        blank=True,
        help_text="One keyword per line"
    )

    # Status
    is_active = models.BooleanField(default=True)
    last_modified = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'public_seo_pages'
        verbose_name = 'SEO Page'
        verbose_name_plural = 'SEO Pages'
        ordering = ['page_type']

    def __str__(self):
        return f"{self.get_page_type_display()} - {self.title}"

    def get_meta_tags(self):
        """Generate meta tags HTML"""
        return {
            'title': self.title,
            'description': self.meta_description,
            'keywords': self.meta_keywords,
            'robots': self.robots_meta,
            'canonical': self.canonical_url or '',
        }

    def get_og_tags(self):
        """Generate Open Graph tags"""
        og_title = self.og_title or self.title
        og_description = self.og_description or self.meta_description

        return {
            'og:title': og_title,
            'og:description': og_description,
            'og:image': self.og_image.url if self.og_image else '',
            'og:type': self.og_type,
            'og:url': self.canonical_url or '',
        }

    def get_twitter_tags(self):
        """Generate Twitter Card tags"""
        twitter_title = self.twitter_title or self.title
        twitter_description = self.twitter_description or self.meta_description

        return {
            'twitter:card': self.twitter_card,
            'twitter:title': twitter_title,
            'twitter:description': twitter_description,
            'twitter:image': self.twitter_image.url if self.twitter_image else '',
        }


class Redirect(models.Model):
    """
    URL redirects for SEO purposes.
    Handles 301/302 redirects.
    """

    REDIRECT_TYPES = [
        (301, '301 - Permanent'),
        (302, '302 - Temporary'),
    ]

    old_path = models.CharField(
        max_length=255,
        unique=True,
        help_text="Old URL path (e.g., /old-page/)"
    )
    new_path = models.CharField(
        max_length=255,
        help_text="New URL path or full URL"
    )
    redirect_type = models.IntegerField(
        choices=REDIRECT_TYPES,
        default=301
    )

    # Tracking
    hit_count = models.PositiveIntegerField(default=0)
    last_accessed = models.DateTimeField(null=True, blank=True)

    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = 'public_seo_redirects'
        verbose_name = 'Redirect'
        verbose_name_plural = 'Redirects'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.old_path} → {self.new_path} ({self.redirect_type})"

    def record_hit(self):
        """Record redirect hit"""
        self.hit_count += 1
        self.last_accessed = timezone.now()
        self.save(update_fields=['hit_count', 'last_accessed'])


class Sitemap(models.Model):
    """
    Dynamic sitemap entries.
    Auto-generates XML sitemap.
    """

    PRIORITY_CHOICES = [
        (1.0, 'Highest'),
        (0.8, 'High'),
        (0.5, 'Medium'),
        (0.3, 'Low'),
    ]

    CHANGE_FREQ_CHOICES = [
        ('always', 'Always'),
        ('hourly', 'Hourly'),
        ('daily', 'Daily'),
        ('weekly', 'Weekly'),
        ('monthly', 'Monthly'),
        ('yearly', 'Yearly'),
        ('never', 'Never'),
    ]

    url_path = models.CharField(max_length=255, unique=True)
    priority = models.FloatField(
        choices=PRIORITY_CHOICES,
        default=0.5,
        validators=[MinValueValidator(0.0), MaxValueValidator(1.0)]
    )
    change_frequency = models.CharField(
        max_length=20,
        choices=CHANGE_FREQ_CHOICES,
        default='weekly'
    )
    last_modified = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'public_seo_sitemap'
        verbose_name = 'Sitemap Entry'
        verbose_name_plural = 'Sitemap Entries'
        ordering = ['-priority', 'url_path']

    def __str__(self):
        return f"{self.url_path} (Priority: {self.priority})"


class RobotsTxt(models.Model):
    """
    Manages robots.txt content.
    Only one active record should exist.
    """

    content = models.TextField(
        default="User-agent: *\nAllow: /\nSitemap: https://yourdomain.com/sitemap.xml",
        help_text="robots.txt content"
    )
    is_active = models.BooleanField(default=True, unique=True)
    last_modified = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'public_seo_robots'
        verbose_name = 'Robots.txt'
        verbose_name_plural = 'Robots.txt'

    def __str__(self):
        return "Robots.txt Configuration"


class SEOAudit(models.Model):
    """
    Track SEO health and issues.
    """

    SEVERITY_CHOICES = [
        ('CRITICAL', 'Critical'),
        ('WARNING', 'Warning'),
        ('INFO', 'Info'),
    ]

    page = models.ForeignKey(SEOPage, on_delete=models.CASCADE, related_name='audits')
    severity = models.CharField(max_length=20, choices=SEVERITY_CHOICES)
    issue_type = models.CharField(max_length=100)
    description = models.TextField()
    recommendation = models.TextField(blank=True)

    is_resolved = models.BooleanField(default=False)
    resolved_at = models.DateTimeField(null=True, blank=True)

    detected_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'public_seo_audits'
        verbose_name = 'SEO Audit'
        verbose_name_plural = 'SEO Audits'
        ordering = ['-detected_at']

    def __str__(self):
        return f"{self.severity}: {self.issue_type} on {self.page}"


class KeywordTracking(models.Model):
    """
    Track keyword rankings over time.
    """

    keyword = models.CharField(max_length=200)
    target_url = models.URLField()

    # Current ranking
    current_position = models.PositiveIntegerField(null=True, blank=True)
    search_volume = models.PositiveIntegerField(null=True, blank=True)
    competition = models.CharField(
        max_length=20,
        choices=[('LOW', 'Low'), ('MEDIUM', 'Medium'), ('HIGH', 'High')],
        blank=True
    )

    # Tracking
    tracked_since = models.DateField(auto_now_add=True)
    last_checked = models.DateTimeField(null=True, blank=True)

    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = 'public_seo_keyword_tracking'
        verbose_name = 'Keyword Tracking'
        verbose_name_plural = 'Keyword Tracking'
        unique_together = ['keyword', 'target_url']

    def __str__(self):
        return f"{self.keyword} - Position: {self.current_position or 'N/A'}"


class KeywordRankingHistory(models.Model):
    """
    Historical ranking data for keywords.
    """

    keyword_tracking = models.ForeignKey(
        KeywordTracking,
        on_delete=models.CASCADE,
        related_name='history'
    )
    position = models.PositiveIntegerField()
    checked_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'public_seo_ranking_history'
        verbose_name = 'Ranking History'
        verbose_name_plural = 'Ranking History'
        ordering = ['-checked_at']

    def __str__(self):
        return f"{self.keyword_tracking.keyword}: #{self.position} on {self.checked_at.date()}"