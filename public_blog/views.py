from django.views.generic import ListView, DetailView, CreateView
from django.views import View
from django.shortcuts import get_object_or_404, redirect
from django.contrib import messages
from django.http import JsonResponse
from django.utils import timezone
from django.db.models import Q, Count
from .models import BlogPost, BlogCategory, BlogComment, Newsletter
from .forms import CommentForm, NewsletterForm


class BlogHomeView(ListView):
    """Blog homepage with featured and recent posts"""
    model = BlogPost
    template_name = 'public_blog/home.html'
    context_object_name = 'posts'
    paginate_by = 12

    def get_queryset(self):
        return BlogPost.objects.filter(
            status='PUBLISHED',
            published_at__lte=timezone.now()
        ).select_related('category')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['featured_posts'] = BlogPost.objects.filter(
            status='PUBLISHED',
            is_featured=True,
            published_at__lte=timezone.now()
        )[:3]
        context['categories'] = BlogCategory.objects.filter(
            is_active=True
        ).annotate(post_count=Count('posts'))
        return context


class BlogDetailView(DetailView):
    """Individual blog post"""
    model = BlogPost
    template_name = 'public_blog/detail.html'
    context_object_name = 'post'

    def get_queryset(self):
        return BlogPost.objects.filter(
            status='PUBLISHED',
            published_at__lte=timezone.now()
        )

    def get_object(self):
        post = super().get_object()
        # Increment view count
        post.increment_views()
        return post

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        post = self.object

        # Related posts
        context['related_posts'] = BlogPost.objects.filter(
            status='PUBLISHED',
            category=post.category,
            published_at__lte=timezone.now()
        ).exclude(id=post.id)[:3]

        # Approved comments
        context['comments'] = post.comments.filter(
            is_approved=True,
            is_spam=False
        )
        context['comment_form'] = CommentForm()

        return context


class BlogCategoryView(ListView):
    """Posts by category"""
    model = BlogPost
    template_name = 'public_blog/category.html'
    context_object_name = 'posts'
    paginate_by = 12

    def get_queryset(self):
        self.category = get_object_or_404(
            BlogCategory,
            slug=self.kwargs['slug'],
            is_active=True
        )
        return BlogPost.objects.filter(
            status='PUBLISHED',
            category=self.category,
            published_at__lte=timezone.now()
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['category'] = self.category
        return context


class BlogSearchView(ListView):
    """Search blog posts"""
    model = BlogPost
    template_name = 'public_blog/search.html'
    context_object_name = 'posts'
    paginate_by = 12

    def get_queryset(self):
        query = self.request.GET.get('q', '')

        if not query:
            return BlogPost.objects.none()

        return BlogPost.objects.filter(
            Q(title__icontains=query) |
            Q(excerpt__icontains=query) |
            Q(content__icontains=query) |
            Q(tags__icontains=query),
            status='PUBLISHED',
            published_at__lte=timezone.now()
        ).distinct()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['query'] = self.request.GET.get('q', '')
        return context


class AddCommentView(CreateView):
    """Add comment to blog post"""
    model = BlogComment
    form_class = CommentForm

    def form_valid(self, form):
        comment = form.save(commit=False)
        comment.post = get_object_or_404(
            BlogPost,
            slug=self.kwargs['slug']
        )
        comment.ip_address = self.get_client_ip()
        comment.user_agent = self.request.META.get('HTTP_USER_AGENT', '')[:500]

        # Auto-approve or require moderation
        # comment.is_approved = True  # Auto-approve
        comment.is_approved = False  # Require moderation

        comment.save()

        if comment.is_approved:
            messages.success(self.request, 'Your comment has been posted!')
        else:
            messages.info(
                self.request,
                'Your comment is awaiting moderation. Thank you!'
            )

        return redirect(comment.post.get_absolute_url())

    def get_client_ip(self):
        x_forwarded_for = self.request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = self.request.META.get('REMOTE_ADDR')
        return ip


class NewsletterSubscribeView(View):
    """Subscribe to newsletter"""

    def post(self, request):
        form = NewsletterForm(request.POST)

        if form.is_valid():
            newsletter = form.save(commit=False)
            newsletter.subscribed_from = request.POST.get('source', 'BLOG')
            newsletter.save()

            # Send confirmation email
            # send_newsletter_confirmation.delay(newsletter.id)

            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': True,
                    'message': 'Thanks for subscribing!'
                })

            messages.success(request, 'Thanks for subscribing to our newsletter!')
            return redirect(request.META.get('HTTP_REFERER', '/'))

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': False,
                'errors': form.errors
            }, status=400)

        messages.error(request, 'Please enter a valid email address.')
        return redirect(request.META.get('HTTP_REFERER', '/'))


class NewsletterUnsubscribeView(View):
    """Unsubscribe from newsletter"""

    def get(self, request, token):
        newsletter = get_object_or_404(Newsletter, unsubscribe_token=token)
        newsletter.unsubscribe()

        messages.success(request, 'You have been unsubscribed from our newsletter.')
        return redirect('public_blog:home')