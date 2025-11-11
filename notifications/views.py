from django.http import JsonResponse
from django.utils import timezone
from django.db import models, connection
from django_tenants.utils import get_public_schema_name
import logging
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.db.models import Q
from django.core.paginator import Paginator
from django.utils import timezone

from .models import Notification, NotificationPreference, Announcement


logger = logging.getLogger(__name__)


@login_required
def notification_list(request):
    """List all notifications for the current user"""
    notifications = Notification.objects.filter(
        recipient=request.user
    ).select_related('sender', 'content_type')

    # Filter
    filter_type = request.GET.get('type', 'all')
    if filter_type == 'unread':
        notifications = notifications.filter(is_read=False)
    elif filter_type == 'read':
        notifications = notifications.filter(is_read=True)
    elif filter_type != 'all':
        notifications = notifications.filter(notification_type=filter_type)

    # Pagination
    paginator = Paginator(notifications, 20)
    page = request.GET.get('page')
    notifications_page = paginator.get_page(page)

    # Stats
    stats = {
        'total': Notification.objects.filter(recipient=request.user).count(),
        'unread': Notification.objects.filter(recipient=request.user, is_read=False).count(),
        'read': Notification.objects.filter(recipient=request.user, is_read=True).count(),
    }

    context = {
        'notifications': notifications_page,
        'stats': stats,
        'filter_type': filter_type
    }

    return render(request, 'notifications/notification_list.html', context)


@login_required
@require_http_methods(["POST"])
def mark_as_read(request, pk):
    """Mark a notification as read"""
    notification = get_object_or_404(Notification, pk=pk, recipient=request.user)
    notification.mark_as_read()

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'success': True})

    return redirect('notifications:notification_list')


@login_required
@require_http_methods(["POST"])
def mark_as_unread(request, pk):
    """Mark a notification as unread"""
    notification = get_object_or_404(Notification, pk=pk, recipient=request.user)
    notification.mark_as_unread()

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'success': True})

    return redirect('notifications:notification_list')


@login_required
@require_http_methods(["POST"])
def mark_all_as_read(request):
    """Mark all notifications as read"""
    Notification.objects.filter(
        recipient=request.user,
        is_read=False
    ).update(is_read=True, read_at=timezone.now())

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'success': True})

    return redirect('notifications:notification_list')


@login_required
@require_http_methods(["POST"])
def delete_notification(request, pk):
    """Delete a notification"""
    notification = get_object_or_404(Notification, pk=pk, recipient=request.user)
    notification.delete()

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'success': True})

    return redirect('notifications:notification_list')


@login_required
@require_http_methods(["POST"])
def delete_all_read(request):
    """Delete all read notifications"""
    Notification.objects.filter(
        recipient=request.user,
        is_read=True
    ).delete()

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'success': True})

    return redirect('notifications:notification_list')


@login_required
def notification_preferences(request):
    """View and update notification preferences"""
    preferences, created = NotificationPreference.objects.get_or_create(
        user=request.user
    )

    if request.method == 'POST':
        # Update preferences
        preferences.email_on_expense_approved = request.POST.get('email_on_expense_approved') == 'on'
        preferences.email_on_expense_rejected = request.POST.get('email_on_expense_rejected') == 'on'
        preferences.email_on_expense_paid = request.POST.get('email_on_expense_paid') == 'on'
        preferences.email_on_comment = request.POST.get('email_on_comment') == 'on'
        preferences.email_on_budget_alert = request.POST.get('email_on_budget_alert') == 'on'

        preferences.push_enabled = request.POST.get('push_enabled') == 'on'
        preferences.push_on_expense_approved = request.POST.get('push_on_expense_approved') == 'on'
        preferences.push_on_expense_rejected = request.POST.get('push_on_expense_rejected') == 'on'

        preferences.digest_frequency = request.POST.get('digest_frequency', 'realtime')

        preferences.save()

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': True, 'message': 'Preferences updated successfully'})

        from django.contrib import messages
        messages.success(request, 'Notification preferences updated successfully!')
        return redirect('notifications:preferences')

    context = {
        'preferences': preferences
    }

    return render(request, 'notifications/preferences.html', context)


@login_required
def notifications_api(request):
    """API endpoint for getting notifications (used by base template)"""
    notifications = Notification.objects.filter(
        recipient=request.user,
        is_read=False
    ).order_by('-created_at')[:10]

    data = {
        'count': notifications.count(),
        'notifications': [
            {
                'id': n.id,
                'title': n.title,
                'message': n.message,
                'icon': n.get_icon(),
                'color': n.get_color(),
                'url': n.action_url or '#',
                'created_at': n.created_at.isoformat(),
                'is_new': (timezone.now() - n.created_at).seconds < 300  # New if less than 5 minutes
            }
            for n in notifications
        ]
    }

    return JsonResponse(data)


@login_required
def notifications_count(request):
    """Get unread notification count"""
    count = Notification.objects.filter(
        recipient=request.user,
        is_read=False
    ).count()

    return JsonResponse({'count': count})


@login_required
def active_announcements(request):
    """Get active announcements for the user"""
    now = timezone.now()
    announcements = Announcement.objects.filter(
        is_active=True,
        start_date__lte=now
    ).filter(
        Q(end_date__isnull=True) | Q(end_date__gte=now)
    ).exclude(
        dismissed_by=request.user
    ).order_by('-priority', '-created_at')

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        data = [
            {
                'id': a.id,
                'title': a.title,
                'message': a.message,
                'type': a.announcement_type,
                'is_dismissible': a.is_dismissible,
                'action_url': a.action_url,
                'action_text': a.action_text,
            }
            for a in announcements
        ]
        return JsonResponse({'announcements': data})

    context = {
        'announcements': announcements
    }

    return render(request, 'notifications/announcements.html', context)


@login_required
@require_http_methods(["POST"])
def dismiss_announcement(request, pk):
    """Dismiss an announcement"""
    announcement = get_object_or_404(Announcement, pk=pk)

    if announcement.is_dismissible:
        announcement.dismissed_by.add(request.user)

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'success': True})

    return redirect('notifications:announcements')

def notiifications_api(request):
    """
    API endpoint for notifications.
    """
    public_schema = get_public_schema_name()
    current_schema = connection.schema_name

    # DEBUG: Log every request
    logger.info(f"notifications_api called - Schema: {current_schema}, Path: {request.path}, User: {request.user}")

    # Return empty response for public schema
    if not current_schema or current_schema == public_schema:
        logger.warning(f"Notifications API called from public schema - returning empty")
        return JsonResponse({
            'notifications': [],
            'count': 0
        })

    notifications = []

    try:
        from inventory.models import Stock
        from accounts.models import CustomUser

        # Low stock items
        try:
            low_stock_items = Stock.objects.filter(
                quantity__lte=models.F('low_stock_threshold')
            ).count()

            if low_stock_items > 0:
                notifications.append({
                    'message': f'{low_stock_items} item{"s" if low_stock_items != 1 else ""} below reorder level',
                    'icon': 'bi bi-exclamation-triangle',
                    'url': '/inventory/stock/'
                })
        except Exception as e:
            logger.error(f"Stock query error in schema {current_schema}: {e}")

        # New users registered in last 24h
        try:
            new_users_count = CustomUser.objects.filter(
                date_joined__gte=timezone.now() - timezone.timedelta(days=1)
            ).count()

            if new_users_count > 0:
                notifications.append({
                    'message': f'{new_users_count} new user{"s" if new_users_count != 1 else ""} registered',
                    'icon': 'bi bi-person-plus',
                    'url': '/accounts/users/'
                })
        except Exception as e:
            logger.error(f"User query error in schema {current_schema}: {e}")

    except Exception as e:
        logger.error(f"Error in notifications API for schema {current_schema}: {e}")

    # System update (only for staff users)
    if request.user.is_authenticated and request.user.is_staff:
        notifications.append({
            'message': 'System update available',
            'icon': 'bi bi-info-circle',
            'url': '/system/updates/'
        })

    return JsonResponse({
        'notifications': notifications,
        'count': len(notifications)
    })