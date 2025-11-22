from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods, require_GET, require_POST
from django.db.models import Q, Count, F
from django.core.paginator import Paginator
from django.utils import timezone
from django.contrib import messages
from django.views.generic import ListView, DetailView, UpdateView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse_lazy
from django.db import connection
from django_tenants.utils import get_public_schema_name, schema_context
import logging
import json

from .models import (
    Notification, NotificationPreference, Announcement,
    NotificationCategory, NotificationTemplate, NotificationBatch,
    NotificationLog, NotificationRule
)
from .services import NotificationService

logger = logging.getLogger(__name__)


# ============= NOTIFICATION VIEWS =============

@login_required
def notification_list(request):
    """List all notifications for the current user with tenant context"""
    # Get current tenant schema
    current_schema = connection.schema_name

    with schema_context(current_schema):
        notifications = Notification.objects.filter(
            recipient=request.user,
            is_dismissed=False
        ).select_related('category', 'template', 'content_type')

        # Filter by type
        filter_type = request.GET.get('type', 'all')
        if filter_type == 'unread':
            notifications = notifications.filter(is_read=False)
        elif filter_type == 'read':
            notifications = notifications.filter(is_read=True)
        elif filter_type in ['INFO', 'SUCCESS', 'WARNING', 'ERROR', 'ALERT']:
            notifications = notifications.filter(notification_type=filter_type)

        # Filter by category
        category_slug = request.GET.get('category')
        if category_slug:
            notifications = notifications.filter(category__slug=category_slug)

        # Filter by priority
        priority = request.GET.get('priority')
        if priority:
            notifications = notifications.filter(priority=priority)

        # Search
        search_query = request.GET.get('q')
        if search_query:
            notifications = notifications.filter(
                Q(title__icontains=search_query) |
                Q(message__icontains=search_query)
            )

        # Pagination
        paginator = Paginator(notifications, 25)
        page = request.GET.get('page', 1)
        notifications_page = paginator.get_page(page)

        # Stats with tenant context
        stats = {
            'total': Notification.objects.filter(recipient=request.user, is_dismissed=False).count(),
            'unread': Notification.objects.filter(recipient=request.user, is_read=False, is_dismissed=False).count(),
            'read': Notification.objects.filter(recipient=request.user, is_read=True, is_dismissed=False).count(),
        }

        # Categories with counts
        categories = NotificationCategory.objects.filter(
            is_active=True
        ).annotate(
            notification_count=Count(
                'notifications',
                filter=Q(notifications__recipient=request.user, notifications__is_dismissed=False)
            )
        ).order_by('sort_order')

        context = {
            'notifications': notifications_page,
            'stats': stats,
            'categories': categories,
            'filter_type': filter_type,
            'selected_category': category_slug,
            'selected_priority': priority,
            'search_query': search_query,
            'current_schema': current_schema,
        }

        return render(request, 'notifications/notification_list.html', context)


@login_required
def notification_detail(request, pk):
    """View a single notification with tenant context"""
    current_schema = connection.schema_name

    with schema_context(current_schema):
        notification = get_object_or_404(
            Notification,
            pk=pk,
            recipient=request.user
        )

        # Mark as read if unread
        if not notification.is_read:
            notification.mark_as_read()

        context = {
            'notification': notification,
            'current_schema': current_schema,
        }

        return render(request, 'notifications/notification_detail.html', context)


@login_required
@require_POST
def mark_as_read(request, pk):
    """Mark a notification as read with tenant context"""
    current_schema = connection.schema_name

    with schema_context(current_schema):
        notification = get_object_or_404(Notification, pk=pk, recipient=request.user)
        notification.mark_as_read()

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': True,
                'unread_count': NotificationService.get_unread_count(request.user, tenant_schema=current_schema)
            })

        messages.success(request, 'Notification marked as read.')
        return redirect('notifications:notification_list')


@login_required
@require_POST
def mark_as_unread(request, pk):
    """Mark a notification as unread with tenant context"""
    current_schema = connection.schema_name

    with schema_context(current_schema):
        notification = get_object_or_404(Notification, pk=pk, recipient=request.user)
        notification.mark_as_unread()

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': True,
                'unread_count': NotificationService.get_unread_count(request.user, tenant_schema=current_schema)
            })

        messages.success(request, 'Notification marked as unread.')
        return redirect('notifications:notification_list')


@login_required
@require_POST
def mark_all_as_read(request):
    """Mark all notifications as read with tenant context"""
    current_schema = connection.schema_name

    with schema_context(current_schema):
        count = NotificationService.mark_all_as_read(request.user, tenant_schema=current_schema)

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': True,
                'count': count,
                'unread_count': 0
            })

        messages.success(request, f'{count} notification(s) marked as read.')
        return redirect('notifications:notification_list')


@login_required
@require_POST
def dismiss_notification(request, pk):
    """Dismiss a notification with tenant context"""
    current_schema = connection.schema_name

    with schema_context(current_schema):
        notification = get_object_or_404(Notification, pk=pk, recipient=request.user)
        notification.dismiss()

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': True,
                'unread_count': NotificationService.get_unread_count(request.user, tenant_schema=current_schema)
            })

        messages.success(request, 'Notification dismissed.')
        return redirect('notifications:notification_list')


@login_required
@require_POST
def delete_notification(request, pk):
    """Delete a notification with tenant context"""
    current_schema = connection.schema_name

    with schema_context(current_schema):
        notification = get_object_or_404(Notification, pk=pk, recipient=request.user)
        notification.delete()

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': True,
                'unread_count': NotificationService.get_unread_count(request.user, tenant_schema=current_schema)
            })

        messages.success(request, 'Notification deleted.')
        return redirect('notifications:notification_list')


@login_required
@require_POST
def delete_all_read(request):
    """Delete all read notifications with tenant context"""
    current_schema = connection.schema_name

    with schema_context(current_schema):
        count, _ = Notification.objects.filter(
            recipient=request.user,
            is_read=True
        ).delete()

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': True,
                'count': count
            })

        messages.success(request, f'{count} notification(s) deleted.')
        return redirect('notifications:notification_list')


@login_required
@require_POST
def bulk_action(request):
    """Perform bulk actions on notifications with tenant context"""
    current_schema = connection.schema_name

    with schema_context(current_schema):
        try:
            data = json.loads(request.body)
            action = data.get('action')
            notification_ids = data.get('notification_ids', [])

            if not notification_ids:
                return JsonResponse({'success': False, 'error': 'No notifications selected'})

            notifications = Notification.objects.filter(
                pk__in=notification_ids,
                recipient=request.user
            )

            if action == 'mark_read':
                count = notifications.update(is_read=True, read_at=timezone.now())
                message = f'{count} notification(s) marked as read'
            elif action == 'mark_unread':
                count = notifications.update(is_read=False, read_at=None)
                message = f'{count} notification(s) marked as unread'
            elif action == 'dismiss':
                count = notifications.update(is_dismissed=True, dismissed_at=timezone.now())
                message = f'{count} notification(s) dismissed'
            elif action == 'delete':
                count, _ = notifications.delete()
                message = f'{count} notification(s) deleted'
            else:
                return JsonResponse({'success': False, 'error': 'Invalid action'})

            return JsonResponse({
                'success': True,
                'message': message,
                'unread_count': NotificationService.get_unread_count(request.user, tenant_schema=current_schema)
            })

        except Exception as e:
            logger.error(f"Bulk action error: {e}")
            return JsonResponse({'success': False, 'error': str(e)})


# ============= NOTIFICATION PREFERENCES =============

@login_required
def notification_preferences(request):
    """View and update notification preferences with tenant context"""
    current_schema = connection.schema_name

    with schema_context(current_schema):
        preferences, created = NotificationPreference.objects.get_or_create(
            user=request.user
        )

        if request.method == 'POST':
            # Global preferences
            preferences.email_enabled = request.POST.get('email_enabled') == 'on'
            preferences.sms_enabled = request.POST.get('sms_enabled') == 'on'
            preferences.push_enabled = request.POST.get('push_enabled') == 'on'
            preferences.in_app_enabled = request.POST.get('in_app_enabled') == 'on'

            # Quiet hours
            preferences.quiet_hours_enabled = request.POST.get('quiet_hours_enabled') == 'on'
            if preferences.quiet_hours_enabled:
                quiet_start = request.POST.get('quiet_hours_start')
                quiet_end = request.POST.get('quiet_hours_end')
                if quiet_start:
                    preferences.quiet_hours_start = quiet_start
                if quiet_end:
                    preferences.quiet_hours_end = quiet_end

            # Digest
            preferences.digest_enabled = request.POST.get('digest_enabled') == 'on'
            preferences.digest_frequency = request.POST.get('digest_frequency', 'DAILY')

            # Do Not Disturb
            preferences.dnd_enabled = request.POST.get('dnd_enabled') == 'on'
            dnd_until = request.POST.get('dnd_until')
            if dnd_until:
                from django.utils.dateparse import parse_datetime
                preferences.dnd_until = parse_datetime(dnd_until)

            # Category preferences
            category_prefs = {}
            for category in NotificationCategory.objects.filter(is_active=True):
                category_prefs[str(category.id)] = {
                    'enabled': request.POST.get(f'category_{category.id}') == 'on'
                }
            preferences.category_preferences = category_prefs

            # Event preferences
            event_prefs = {}
            for template in NotificationTemplate.objects.filter(is_active=True):
                event_prefs[template.event_type] = {
                    'enabled': request.POST.get(f'event_{template.event_type}') == 'on'
                }
            preferences.event_preferences = event_prefs

            preferences.save()

            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': True, 'message': 'Preferences updated successfully'})

            messages.success(request, 'Notification preferences updated successfully!')
            return redirect('notifications:preferences')

        # Get all categories and templates for the form
        categories = NotificationCategory.objects.filter(is_active=True).order_by('sort_order')
        templates = NotificationTemplate.objects.filter(is_active=True).order_by('name')

        context = {
            'preferences': preferences,
            'categories': categories,
            'templates': templates,
            'current_schema': current_schema,
        }

        return render(request, 'notifications/preferences.html', context)


# ============= ANNOUNCEMENTS =============

@login_required
def announcement_list(request):
    """List active announcements with tenant context"""
    current_schema = connection.schema_name

    with schema_context(current_schema):
        announcements = Announcement.objects.filter(
            is_active=True
        ).exclude(
            dismissed_by=request.user
        )

        # Filter visible announcements
        visible_announcements = [a for a in announcements if a.is_visible()]

        # Separate by priority
        urgent = [a for a in visible_announcements if a.priority >= 100]
        normal = [a for a in visible_announcements if a.priority < 100]

        context = {
            'urgent_announcements': urgent,
            'normal_announcements': normal,
            'current_schema': current_schema,
        }

        return render(request, 'notifications/announcement_list.html', context)


@login_required
@require_POST
def dismiss_announcement(request, pk):
    """Dismiss an announcement with tenant context"""
    current_schema = connection.schema_name

    with schema_context(current_schema):
        announcement = get_object_or_404(Announcement, pk=pk)

        if announcement.is_dismissible:
            announcement.dismissed_by.add(request.user)

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': True})

        messages.success(request, 'Announcement dismissed.')
        return redirect('notifications:announcements')


# ============= API ENDPOINTS =============

@login_required
@require_GET
def notifications_api(request):
    """API endpoint for getting recent notifications with tenant context"""
    current_schema = connection.schema_name
    public_schema = get_public_schema_name()

    if not current_schema or current_schema == public_schema:
        logger.warning("Notifications API called from public schema")
        return JsonResponse({
            'notifications': [],
            'count': 0,
            'schema': 'public'
        })

    with schema_context(current_schema):
        try:
            # Get recent unread notifications
            notifications = Notification.objects.filter(
                recipient=request.user,
                is_read=False,
                is_dismissed=False
            ).select_related('category').order_by('-created_at')[:15]

            data = {
                'count': notifications.count(),
                'total_unread': NotificationService.get_unread_count(request.user, tenant_schema=current_schema),
                'notifications': [
                    {
                        'id': n.id,
                        'title': n.title,
                        'message': n.message[:100] + '...' if len(n.message) > 100 else n.message,
                        'notification_type': n.notification_type,
                        'priority': n.priority,
                        'category': {
                            'name': n.category.name if n.category else None,
                            'icon': n.category.icon if n.category else 'bell',
                            'color': n.category.color if n.category else 'primary'
                        } if n.category else None,
                        'action_url': n.action_url or '#',
                        'action_text': n.action_text,
                        'created_at': n.created_at.isoformat(),
                        'time_since': n.time_since_created,
                        'is_new': (timezone.now() - n.created_at).seconds < 300,  # New if < 5 min
                        'schema': current_schema,
                    }
                    for n in notifications
                ]
            }

            return JsonResponse(data)

        except Exception as e:
            logger.error(f"Error in notifications API: {e}")
            return JsonResponse({
                'notifications': [],
                'count': 0,
                'error': str(e),
                'schema': current_schema
            }, status=500)


@login_required
@require_GET
def notifications_count(request):
    """Get unread notification count with tenant context"""
    current_schema = connection.schema_name

    with schema_context(current_schema):
        try:
            count = NotificationService.get_unread_count(request.user, tenant_schema=current_schema)
            return JsonResponse({
                'count': count,
                'schema': current_schema
            })
        except Exception as e:
            logger.error(f"Error getting notification count: {e}")
            return JsonResponse({
                'count': 0,
                'error': str(e),
                'schema': current_schema
            })


@login_required
@require_GET
def active_announcements_api(request):
    """Get active announcements for the user with tenant context"""
    current_schema = connection.schema_name

    with schema_context(current_schema):
        try:
            announcements = Announcement.objects.filter(
                is_active=True
            ).exclude(
                dismissed_by=request.user
            ).order_by('-priority', '-created_at')

            # Filter visible announcements
            visible = [a for a in announcements if a.is_visible()]

            data = {
                'announcements': [
                    {
                        'id': a.id,
                        'title': a.title,
                        'message': a.message,
                        'announcement_type': a.announcement_type,
                        'is_dismissible': a.is_dismissible,
                        'action_url': a.action_url,
                        'action_text': a.action_text,
                        'priority': a.priority,
                        'show_on_dashboard': a.show_on_dashboard,
                        'schema': current_schema,
                    }
                    for a in visible
                ]
            }

            return JsonResponse(data)

        except Exception as e:
            logger.error(f"Error fetching announcements: {e}")
            return JsonResponse({
                'announcements': [],
                'error': str(e),
                'schema': current_schema
            })


@login_required
@require_GET
def notification_stats(request):
    """Get notification statistics with tenant context"""
    current_schema = connection.schema_name

    with schema_context(current_schema):
        try:
            stats = {
                'total': Notification.objects.filter(recipient=request.user).count(),
                'unread': Notification.objects.filter(recipient=request.user, is_read=False,
                                                      is_dismissed=False).count(),
                'read': Notification.objects.filter(recipient=request.user, is_read=True).count(),
                'dismissed': Notification.objects.filter(recipient=request.user, is_dismissed=True).count(),
                'by_type': {},
                'by_category': {},
                'by_priority': {},
                'schema': current_schema,
            }

            # By type
            type_counts = Notification.objects.filter(
                recipient=request.user,
                is_dismissed=False
            ).values('notification_type').annotate(count=Count('id'))

            for item in type_counts:
                stats['by_type'][item['notification_type']] = item['count']

            # By category
            category_counts = Notification.objects.filter(
                recipient=request.user,
                is_dismissed=False,
                category__isnull=False
            ).values('category__name').annotate(count=Count('id'))

            for item in category_counts:
                stats['by_category'][item['category__name']] = item['count']

            # By priority
            priority_counts = Notification.objects.filter(
                recipient=request.user,
                is_dismissed=False
            ).values('priority').annotate(count=Count('id'))

            for item in priority_counts:
                stats['by_priority'][item['priority']] = item['count']

            return JsonResponse(stats)

        except Exception as e:
            logger.error(f"Error getting notification stats: {e}")
            return JsonResponse({
                'error': str(e),
                'schema': current_schema
            }, status=500)


# ============= ADMIN VIEWS (Staff Only) =============

@user_passes_test(lambda u: u.is_staff)
def admin_dashboard(request):
    """Admin dashboard for notifications with tenant context"""
    current_schema = connection.schema_name

    with schema_context(current_schema):
        # Recent notifications sent
        recent_notifications = Notification.objects.all().select_related(
            'recipient', 'category'
        ).order_by('-created_at')[:50]

        # Statistics
        from django.db.models import Count, Avg
        from datetime import timedelta

        stats = {
            'total_sent': Notification.objects.count(),
            'sent_today': Notification.objects.filter(
                created_at__date=timezone.now().date()
            ).count(),
            'sent_this_week': Notification.objects.filter(
                created_at__gte=timezone.now() - timedelta(days=7)
            ).count(),
            'unread_rate': Notification.objects.filter(
                is_read=False
            ).count() / max(Notification.objects.count(), 1) * 100,
            'current_schema': current_schema,
        }

        # Delivery stats
        delivery_stats = NotificationLog.objects.values('channel', 'status').annotate(
            count=Count('id')
        )

        # Template usage
        template_usage = Notification.objects.filter(
            template__isnull=False
        ).values('template__name').annotate(
            count=Count('id')
        ).order_by('-count')[:10]

        context = {
            'stats': stats,
            'recent_notifications': recent_notifications,
            'delivery_stats': delivery_stats,
            'template_usage': template_usage,
            'current_schema': current_schema,
        }

        return render(request, 'notifications/admin/dashboard.html', context)


@user_passes_test(lambda u: u.is_staff)
def admin_templates(request):
    """Manage notification templates with tenant context"""
    current_schema = connection.schema_name

    with schema_context(current_schema):
        templates = NotificationTemplate.objects.all().select_related('category').order_by('name')

        context = {
            'templates': templates,
            'current_schema': current_schema,
        }

        return render(request, 'notifications/admin/templates.html', context)


@user_passes_test(lambda u: u.is_staff)
def admin_categories(request):
    """Manage notification categories with tenant context"""
    current_schema = connection.schema_name

    with schema_context(current_schema):
        categories = NotificationCategory.objects.all().order_by('sort_order')

        context = {
            'categories': categories,
            'current_schema': current_schema,
        }

        return render(request, 'notifications/admin/categories.html', context)


@user_passes_test(lambda u: u.is_staff)
def admin_announcements(request):
    """Manage announcements with tenant context"""
    current_schema = connection.schema_name

    with schema_context(current_schema):
        announcements = Announcement.objects.all().order_by('-created_at')

        context = {
            'announcements': announcements,
            'current_schema': current_schema,
        }

        return render(request, 'notifications/admin/announcements.html', context)


@user_passes_test(lambda u: u.is_staff)
def admin_batches(request):
    """Manage notification batches with tenant context"""
    current_schema = connection.schema_name

    with schema_context(current_schema):
        batches = NotificationBatch.objects.all().select_related(
            'template', 'created_by'
        ).order_by('-created_at')

        context = {
            'batches': batches,
            'current_schema': current_schema,
        }

        return render(request, 'notifications/admin/batches.html', context)


@user_passes_test(lambda u: u.is_staff)
def admin_rules(request):
    """Manage notification rules with tenant context"""
    current_schema = connection.schema_name

    with schema_context(current_schema):
        rules = NotificationRule.objects.all().select_related('template').order_by('name')

        context = {
            'rules': rules,
            'current_schema': current_schema,
        }

        return render(request, 'notifications/admin/rules.html', context)


@user_passes_test(lambda u: u.is_staff)
@require_POST
def test_notification(request):
    """Send a test notification with tenant context"""
    current_schema = connection.schema_name

    with schema_context(current_schema):
        try:
            NotificationService.create_notification(
                recipient=request.user,
                title='Test Notification',
                message='This is a test notification sent from the admin panel.',
                notification_type='INFO',
                priority='MEDIUM',
                action_text='View Dashboard',
                action_url='/notifications/',
                tenant_schema=current_schema
            )

            return JsonResponse({
                'success': True,
                'message': 'Test notification sent successfully',
                'schema': current_schema
            })

        except Exception as e:
            logger.error(f"Error sending test notification: {e}")
            return JsonResponse({
                'success': False,
                'error': str(e),
                'schema': current_schema
            }, status=500)


# ============= CROSS-TENANT ADMIN VIEWS =============

@user_passes_test(lambda u: u.is_superuser)
def superuser_dashboard(request):
    """Superuser dashboard across all tenants"""
    from django_tenants.utils import get_tenant_model

    TenantModel = get_tenant_model()
    tenants = TenantModel.objects.exclude(schema_name='public')

    tenant_stats = []

    for tenant in tenants:
        with schema_context(tenant.schema_name):
            stats = {
                'tenant': tenant,
                'total_notifications': Notification.objects.count(),
                'total_users': Notification.objects.values('recipient').distinct().count(),
                'recent_activity': Notification.objects.filter(
                    created_at__gte=timezone.now() - timezone.timedelta(days=7)
                ).count(),
            }
            tenant_stats.append(stats)

    context = {
        'tenant_stats': tenant_stats,
        'total_tenants': tenants.count(),
    }

    return render(request, 'notifications/admin/superuser_dashboard.html', context)


# ============= TENANT-AWARE MIXINS =============

class TenantAwareMixin:
    """Mixin to ensure tenant context in class-based views"""

    def get_queryset(self):
        """Ensure queryset uses current tenant schema"""
        current_schema = connection.schema_name
        with schema_context(current_schema):
            return super().get_queryset()

    def get_context_data(self, **kwargs):
        """Add current schema to context"""
        context = super().get_context_data(**kwargs)
        context['current_schema'] = connection.schema_name
        return context


class NotificationListView(TenantAwareMixin, LoginRequiredMixin, ListView):
    """Class-based view for notification list with tenant support"""
    model = Notification
    template_name = 'notifications/notification_list.html'
    context_object_name = 'notifications'
    paginate_by = 25

    def get_queryset(self):
        current_schema = connection.schema_name
        with schema_context(current_schema):
            return Notification.objects.filter(
                recipient=self.request.user,
                is_dismissed=False
            ).select_related('category', 'template').order_by('-created_at')


class NotificationDetailView(TenantAwareMixin, LoginRequiredMixin, DetailView):
    """Class-based view for notification detail with tenant support"""
    model = Notification
    template_name = 'notifications/notification_detail.html'
    context_object_name = 'notification'

    def get_queryset(self):
        current_schema = connection.schema_name
        with schema_context(current_schema):
            return Notification.objects.filter(recipient=self.request.user)

    def get(self, request, *args, **kwargs):
        # Mark as read when viewing
        response = super().get(request, *args, **kwargs)
        if not self.object.is_read:
            self.object.mark_as_read()
        return response