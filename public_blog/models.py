from django.db import models
from django.utils.text import slugify
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.utils import timezone

User = get_user_model()


class BlogCategory(models.Model):
    """Blog post categories"""

    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=100, unique=True)
    description = models.TextField(blank=True)

    # SEO
    meta_title = models.CharField(max_length=70, blank=True)
    meta_description = models.CharField(max_length=160, blank=True)

    is_active = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = 'public_blog_categories'
        verbose_name_plural = 'Blog Categories'
        ordering = ['order', 'name']

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse('public_blog:category', kwargs={'slug': self.slug})


class BlogPost(models.Model):
    """Blog posts for content marketing"""

    STATUS_CHOICES = [
        ('DRAFT', 'Draft'),
        ('PUBLISHED', 'Published'),
        ('SCHEDULED', 'Scheduled'),
        ('ARCHIVED', 'Archived'),
    ]

    # Basic Info
    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=200, unique=True)
    excerpt = models.TextField(max_length=300, help_text="Short summary (300 chars)")
    content = models.TextField()

    # Categorization
    category = models.ForeignKey(
        BlogCategory,
        on_delete=models.SET_NULL,
        null=True,
        related_name='posts'
    )
    tags = models.CharField(max_length=255, blank=True, help_text="Comma-separated tags")

    # Media
    featured_image = models.ImageField(
        upload_to='blog/images/%Y/%m/',
        blank=True,
        null=True
    )
    featured_image_alt = models.CharField(max_length=255, blank=True)

    # SEO
    meta_title = models.CharField(max_length=70, blank=True)
    meta_description = models.CharField(max_length=160, blank=True)
    focus_keyword = models.CharField(max_length=100, blank=True)

    # Publishing
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='DRAFT')
    published_at = models.DateTimeField(null=True, blank=True)
    scheduled_for = models.DateTimeField(null=True, blank=True)

    # Analytics
    view_count = models.PositiveIntegerField(default=0)
    reading_time_minutes = models.PositiveIntegerField(default=5)

    # Author (nullable for public schema compatibility)
    author_name = models.CharField(max_length=100, default='Team')
    author_email = models.EmailField(blank=True)
    author_bio = models.TextField(blank=True)
    author_avatar = models.ImageField(upload_to='blog/authors/', blank=True, null=True)

    # Flags
    is_featured = models.BooleanField(default=False)
    allow_comments = models.BooleanField(default=True)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'public_blog_posts'
        verbose_name = 'Blog Post'
        verbose_name_plural = 'Blog Posts'
        ordering = ['-published_at', '-created_at']
        indexes = [
            models.Index(fields=['slug']),
            models.Index(fields=['status', 'published_at']),
            models.Index(fields=['category', 'status']),
        ]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.title)

        # Auto-calculate reading time
        if self.content:
            word_count = len(self.content.split())
            self.reading_time_minutes = max(1, word_count // 200)

        # Auto-publish if status changed to published
        if self.status == 'PUBLISHED' and not self.published_at:
            self.published_at = timezone.now()

        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse('public_blog:detail', kwargs={'slug': self.slug})

    def increment_views(self):
        """Increment view count"""
        self.view_count += 1
        self.save(update_fields=['view_count'])

    @property
    def is_published(self):
        return self.status == 'PUBLISHED' and self.published_at <= timezone.now()

    def get_tags_list(self):
        """Get tags as list"""
        return [tag.strip() for tag in self.tags.split(',') if tag.strip()]


class BlogComment(models.Model):
    """Comments on blog posts"""

    post = models.ForeignKey(BlogPost, on_delete=models.CASCADE, related_name='comments')

    # Commenter info
    name = models.CharField(max_length=100)
    email = models.EmailField()
    website = models.URLField(blank=True)

    content = models.TextField()
    # Moderation
    is_approved = models.BooleanField(default=False)
    is_spam = models.BooleanField(default=False)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    approved_at = models.DateTimeField(null=True, blank=True)

    # IP tracking
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)

    class Meta:
        db_table = 'public_blog_comments'
        verbose_name = 'Blog Comment'
        verbose_name_plural = 'Blog Comments'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['post', 'is_approved']),
            models.Index(fields=['email']),
        ]

    def __str__(self):
        return f"Comment by {self.name} on {self.post.title}"

    def approve(self):
        """Approve comment"""
        self.is_approved = True
        self.approved_at = timezone.now()
        self.save()


class Newsletter(models.Model):
    """Newsletter subscriptions"""

    email = models.EmailField(unique=True)
    name = models.CharField(max_length=100, blank=True)

    # Preferences
    is_active = models.BooleanField(default=True)
    subscribed_from = models.CharField(
        max_length=50,
        choices=[
            ('BLOG', 'Blog'),
            ('HOMEPAGE', 'Homepage'),
            ('FOOTER', 'Footer'),
            ('POPUP', 'Popup'),
        ],
        default='BLOG'
    )

    # Tracking
    subscribed_at = models.DateTimeField(auto_now_add=True)
    unsubscribed_at = models.DateTimeField(null=True, blank=True)
    last_email_sent = models.DateTimeField(null=True, blank=True)

    # Token for unsubscribe
    unsubscribe_token = models.CharField(max_length=64, unique=True)

    class Meta:
        db_table = 'public_blog_newsletter'
        verbose_name = 'Newsletter Subscription'
        verbose_name_plural = 'Newsletter Subscriptions'
        ordering = ['-subscribed_at']

    def __str__(self):
        return self.email

    def save(self, *args, **kwargs):
        if not self.unsubscribe_token:
            import secrets
            self.unsubscribe_token = secrets.token_urlsafe(48)
        super().save(*args, **kwargs)

    def unsubscribe(self):
        """Unsubscribe from newsletter"""
        self.is_active = False
        self.unsubscribed_at = timezone.now()
        self.save()