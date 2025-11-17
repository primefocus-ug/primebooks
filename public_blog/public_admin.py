from django.utils.translation import gettext_lazy as _
from public_accounts.admin_site import public_admin, PublicModelAdmin
from .models import BlogCategory, BlogPost, BlogComment, Newsletter
from django import forms
from django.utils import timezone


# ==================== FORMS ====================

class BlogCategoryForm(forms.ModelForm):
    """Form for Blog Category"""

    class Meta:
        model = BlogCategory
        fields = '__all__'
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'slug': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'meta_title': forms.TextInput(attrs={'class': 'form-control'}),
            'meta_description': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'order': forms.NumberInput(attrs={'class': 'form-control'}),
        }


class BlogPostForm(forms.ModelForm):
    """Form for Blog Post"""

    class Meta:
        model = BlogPost
        fields = '__all__'
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control'}),
            'slug': forms.TextInput(attrs={'class': 'form-control'}),
            'excerpt': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'content': forms.Textarea(attrs={'class': 'form-control', 'rows': 10}),
            'category': forms.Select(attrs={'class': 'form-control'}),
            'tags': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'tag1, tag2, tag3'}),
            'featured_image_alt': forms.TextInput(attrs={'class': 'form-control'}),
            'meta_title': forms.TextInput(attrs={'class': 'form-control'}),
            'meta_description': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'focus_keyword': forms.TextInput(attrs={'class': 'form-control'}),
            'status': forms.Select(attrs={'class': 'form-control'}),
            'published_at': forms.DateTimeInput(attrs={'class': 'form-control', 'type': 'datetime-local'}),
            'scheduled_for': forms.DateTimeInput(attrs={'class': 'form-control', 'type': 'datetime-local'}),
            'reading_time_minutes': forms.NumberInput(attrs={'class': 'form-control'}),
            'author_name': forms.TextInput(attrs={'class': 'form-control'}),
            'author_email': forms.EmailInput(attrs={'class': 'form-control'}),
            'author_bio': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }


class BlogCommentForm(forms.ModelForm):
    """Form for Blog Comment"""

    class Meta:
        model = BlogComment
        fields = ['post', 'name', 'email', 'website', 'content', 'is_approved', 'is_spam']
        widgets = {
            'post': forms.Select(attrs={'class': 'form-control'}),
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'website': forms.URLInput(attrs={'class': 'form-control'}),
            'content': forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
        }


class NewsletterForm(forms.ModelForm):
    """Form for Newsletter"""

    class Meta:
        model = Newsletter
        fields = ['email', 'name', 'is_active', 'subscribed_from']
        widgets = {
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'subscribed_from': forms.Select(attrs={'class': 'form-control'}),
        }


# ==================== ADMIN CLASSES ====================

class BlogCategoryAdmin(PublicModelAdmin):
    """Admin for Blog Categories"""

    form_class = BlogCategoryForm

    list_display = ['name', 'slug', 'is_active', 'order']
    list_filter = ['is_active']
    search_fields = ['name', 'description']
    ordering = ['order', 'name']

    fieldsets = (
        (_('Basic Information'), {
            'fields': ('name', 'slug', 'description', 'is_active', 'order')
        }),
        (_('SEO Settings'), {
            'fields': ('meta_title', 'meta_description'),
            'classes': ('collapse',),
        }),
    )


class BlogPostAdmin(PublicModelAdmin):
    """Admin for Blog Posts"""

    form_class = BlogPostForm

    list_display = [
        'title', 'category', 'status', 'author_name',
        'is_featured', 'view_count', 'published_at'
    ]
    list_filter = ['status', 'is_featured', 'category', 'created_at']
    search_fields = ['title', 'excerpt', 'content', 'author_name', 'tags']
    ordering = ['-created_at']
    list_per_page = 20

    fieldsets = (
        (_('Basic Information'), {
            'fields': ('title', 'slug', 'excerpt', 'content', 'category', 'tags')
        }),
        (_('Media'), {
            'fields': ('featured_image', 'featured_image_alt'),
        }),
        (_('Author Information'), {
            'fields': ('author_name', 'author_email', 'author_bio', 'author_avatar'),
        }),
        (_('Publishing'), {
            'fields': ('status', 'published_at', 'scheduled_for', 'is_featured', 'allow_comments'),
        }),
        (_('SEO & Analytics'), {
            'fields': ('meta_title', 'meta_description', 'focus_keyword', 'reading_time_minutes', 'view_count'),
            'classes': ('collapse',),
        }),
    )

    readonly_fields = ['view_count', 'created_at', 'updated_at']

    # Custom actions
    actions = ['make_published', 'make_draft', 'make_featured']

    def make_published(self, request, queryset):
        """Bulk action: Publish selected posts"""
        count = 0
        for post in queryset:
            if post.status != 'PUBLISHED':
                post.status = 'PUBLISHED'
                if not post.published_at:
                    post.published_at = timezone.now()
                post.save()
                count += 1
        return f'{count} post(s) published successfully.'

    make_published.short_description = "Publish selected posts"

    def make_draft(self, request, queryset):
        """Bulk action: Set selected posts to draft"""
        count = queryset.update(status='DRAFT')
        return f'{count} post(s) set to draft.'

    make_draft.short_description = "Set selected posts to draft"

    def make_featured(self, request, queryset):
        """Bulk action: Mark selected posts as featured"""
        count = queryset.update(is_featured=True)
        return f'{count} post(s) marked as featured.'

    make_featured.short_description = "Mark as featured"


class BlogCommentAdmin(PublicModelAdmin):
    """Admin for Blog Comments"""

    form_class = BlogCommentForm

    list_display = [
        'name', 'post', 'email', 'is_approved',
        'is_spam', 'created_at'
    ]
    list_filter = ['is_approved', 'is_spam', 'created_at']
    search_fields = ['name', 'email', 'content', 'post__title']
    ordering = ['-created_at']
    list_per_page = 30

    readonly_fields = ['ip_address', 'user_agent', 'created_at', 'approved_at']

    fieldsets = (
        (_('Comment Information'), {
            'fields': ('post', 'name', 'email', 'website', 'content')
        }),
        (_('Moderation'), {
            'fields': ('is_approved', 'is_spam'),
        }),
        (_('Tracking Information'), {
            'fields': ('ip_address', 'user_agent', 'created_at', 'approved_at'),
            'classes': ('collapse',),
        }),
    )

    # Custom actions
    actions = ['approve_comments', 'mark_as_spam', 'mark_as_not_spam']

    def approve_comments(self, request, queryset):
        """Bulk action: Approve selected comments"""
        count = 0
        for comment in queryset:
            if not comment.is_approved:
                comment.approve()
                count += 1
        return f'{count} comment(s) approved successfully.'

    approve_comments.short_description = "Approve selected comments"

    def mark_as_spam(self, request, queryset):
        """Bulk action: Mark selected comments as spam"""
        count = queryset.update(is_spam=True, is_approved=False)
        return f'{count} comment(s) marked as spam.'

    mark_as_spam.short_description = "Mark as spam"

    def mark_as_not_spam(self, request, queryset):
        """Bulk action: Mark selected comments as not spam"""
        count = queryset.update(is_spam=False)
        return f'{count} comment(s) marked as not spam.'

    mark_as_not_spam.short_description = "Mark as not spam"


class NewsletterAdmin(PublicModelAdmin):
    """Admin for Newsletter Subscriptions"""

    form_class = NewsletterForm

    list_display = [
        'email', 'name', 'is_active', 'subscribed_from',
        'subscribed_at', 'last_email_sent'
    ]
    list_filter = ['is_active', 'subscribed_from', 'subscribed_at']
    search_fields = ['email', 'name']
    ordering = ['-subscribed_at']
    list_per_page = 50

    readonly_fields = [
        'unsubscribe_token', 'subscribed_at',
        'unsubscribed_at', 'last_email_sent'
    ]

    fieldsets = (
        (_('Subscriber Information'), {
            'fields': ('email', 'name', 'is_active', 'subscribed_from')
        }),
        (_('Tracking'), {
            'fields': ('subscribed_at', 'unsubscribed_at', 'last_email_sent', 'unsubscribe_token'),
            'classes': ('collapse',),
        }),
    )

    # Disable add permission for newsletter (subscribers come from frontend)
    has_add_permission_flag = False

    # Custom actions
    actions = ['activate_subscriptions', 'deactivate_subscriptions', 'export_emails']

    def activate_subscriptions(self, request, queryset):
        """Bulk action: Activate selected subscriptions"""
        count = queryset.update(is_active=True, unsubscribed_at=None)
        return f'{count} subscription(s) activated.'

    activate_subscriptions.short_description = "Activate selected subscriptions"

    def deactivate_subscriptions(self, request, queryset):
        """Bulk action: Deactivate selected subscriptions"""
        count = 0
        for subscription in queryset:
            subscription.unsubscribe()
            count += 1
        return f'{count} subscription(s) deactivated.'

    deactivate_subscriptions.short_description = "Deactivate selected subscriptions"

    def export_emails(self, request, queryset):
        """Export emails as CSV"""
        import csv
        from django.http import HttpResponse

        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="newsletter_emails.csv"'

        writer = csv.writer(response)
        writer.writerow(['Email', 'Name', 'Status', 'Subscribed From', 'Subscribed At'])

        for subscription in queryset:
            writer.writerow([
                subscription.email,
                subscription.name,
                'Active' if subscription.is_active else 'Inactive',
                subscription.get_subscribed_from_display(),
                subscription.subscribed_at.strftime('%Y-%m-%d %H:%M:%S')
            ])

        return response

    export_emails.short_description = "Export emails as CSV"


# ==================== REGISTER MODELS ====================

public_admin.register(BlogCategory, BlogCategoryAdmin, app_label='public_blog')
public_admin.register(BlogPost, BlogPostAdmin, app_label='public_blog')
public_admin.register(BlogComment, BlogCommentAdmin, app_label='public_blog')
public_admin.register(Newsletter, NewsletterAdmin, app_label='public_blog')