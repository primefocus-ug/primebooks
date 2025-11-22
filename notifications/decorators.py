from functools import wraps
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from .models import Notification, NotificationPreference
import logging

logger = logging.getLogger(__name__)


def notification_required(view_func):
    """
    Decorator to check if notification exists and belongs to user
    """

    @wraps(view_func)
    @login_required
    def wrapper(request, pk, *args, **kwargs):
        try:
            notification = Notification.objects.get(
                pk=pk,
                recipient=request.user
            )
            request.notification = notification
            return view_func(request, pk, *args, **kwargs)
        except Notification.DoesNotExist:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': False,
                    'error': 'Notification not found'
                }, status=404)

            from django.shortcuts import redirect
            from django.contrib import messages
            messages.error(request, 'Notification not found.')
            return redirect('notifications:notification_list')

    return wrapper


def check_notification_preferences(channel='in_app'):
    """
    Decorator to check if user has enabled notifications for a channel
    """

    def decorator(view_func):
        @wraps(view_func)
        @login_required
        def wrapper(request, *args, **kwargs):
            try:
                prefs = request.user.notification_preferences

                channel_map = {
                    'in_app': prefs.in_app_enabled,
                    'email': prefs.email_enabled,
                    'sms': prefs.sms_enabled,
                    'push': prefs.push_enabled,
                }

                if not channel_map.get(channel, True):
                    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                        return JsonResponse({
                            'success': False,
                            'error': f'{channel} notifications are disabled'
                        })

                    from django.shortcuts import redirect
                    from django.contrib import messages
                    messages.warning(
                        request,
                        f'{channel.title()} notifications are disabled. '
                        'Enable them in your preferences.'
                    )
                    return redirect('notifications:preferences')

            except NotificationPreference.DoesNotExist:
                # Create default preferences
                NotificationPreference.objects.create(user=request.user)

            return view_func(request, *args, **kwargs)

        return wrapper

    return decorator


def ajax_required(view_func):
    """
    Decorator to require AJAX requests
    """

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': False,
                'error': 'This endpoint requires an AJAX request'
            }, status=400)

        return view_func(request, *args, **kwargs)

    return wrapper


def rate_limit_notifications(max_per_hour=100):
    """
    Decorator to rate limit notification creation
    """

    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            from django.utils import timezone
            from datetime import timedelta

            if not request.user.is_authenticated:
                return view_func(request, *args, **kwargs)

            # Count notifications created in last hour
            hour_ago = timezone.now() - timedelta(hours=1)
            count = Notification.objects.filter(
                recipient=request.user,
                created_at__gte=hour_ago
            ).count()

            if count >= max_per_hour:
                logger.warning(
                    f'Rate limit exceeded for user {request.user.id}: '
                    f'{count} notifications in last hour'
                )

                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({
                        'success': False,
                        'error': 'Too many notifications. Please try again later.'
                    }, status=429)

                from django.shortcuts import redirect
                from django.contrib import messages
                messages.error(
                    request,
                    'You have received too many notifications. Please try again later.'
                )
                return redirect('notifications:notification_list')

            return view_func(request, *args, **kwargs)

        return wrapper

    return decorator


def log_notification_action(action_name):
    """
    Decorator to log notification actions
    """

    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            result = view_func(request, *args, **kwargs)

            # Log the action
            notification_id = kwargs.get('pk')
            logger.info(
                f'Notification action: {action_name} | '
                f'User: {request.user.id} | '
                f'Notification: {notification_id}'
            )

            return result

        return wrapper

    return decorator

