import json
from django.http import JsonResponse, HttpResponseForbidden
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, get_object_or_404
from django.conf import settings
from .models import PushSubscription, UserPushPreference, PushNotificationType


from django.db import IntegrityError

@csrf_exempt
@login_required
def save_subscription(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    fcm_token = data.get('fcm_token', '').strip()
    if not fcm_token:
        return JsonResponse({'error': 'fcm_token is required'}, status=400)

    # Deactivate token if it was registered under a different user
    PushSubscription.objects.filter(
        fcm_token=fcm_token,
    ).exclude(user=request.user).update(is_active=False)

    try:
        PushSubscription.objects.update_or_create(
            user=request.user,
            fcm_token=fcm_token,
            defaults={
                'user_agent': request.META.get('HTTP_USER_AGENT', ''),
                'is_active': True,
            }
        )
    except IntegrityError:
        # Race condition: token was just created by a concurrent request
        PushSubscription.objects.filter(fcm_token=fcm_token).update(
            user=request.user,
            user_agent=request.META.get('HTTP_USER_AGENT', ''),
            is_active=True,
        )

    return JsonResponse({'status': 'subscribed'})


@login_required
def get_vapid_public_key(request):
    """
    Returns the Firebase Web Push (VAPID) key for the frontend.
    In Firebase this is the 'Web Push certificate' key pair public key,
    found in Project Settings → Cloud Messaging → Web Push certificates.
    """
    return JsonResponse({'public_key': settings.FIREBASE_VAPID_PUBLIC_KEY})


# ─── Admin views for managing user notification preferences ───────────────────

@login_required
def manage_user_push_preferences(request, user_id):
    """
    Custom page: Admin views/edits notification preferences for a specific user.
    """
    from django.contrib.auth import get_user_model
    User = get_user_model()

    if not request.user.has_perm('accounts.can_manage_users'):
        return HttpResponseForbidden()

    target_user = get_object_or_404(User, id=user_id)
    all_types = PushNotificationType.objects.filter(is_active=True)

    prefs = {
        pref.notification_type_id: pref
        for pref in UserPushPreference.objects.filter(user=target_user)
    }

    if request.method == 'POST':
        enabled_ids = set(map(int, request.POST.getlist('enabled_types')))
        for notif_type in all_types:
            is_enabled = notif_type.id in enabled_ids
            UserPushPreference.objects.update_or_create(
                user=target_user,
                notification_type=notif_type,
                defaults={'enabled': is_enabled}
            )
        return JsonResponse({'status': 'saved'})

    context = {
        'target_user': target_user,
        'all_types': all_types,
        'prefs': prefs,
    }
    return render(request, 'push_notifications/manage_preferences.html', context)


@login_required
def my_push_preferences(request):
    """User can view/toggle their own push preferences."""
    all_types = PushNotificationType.objects.filter(is_active=True)
    prefs = {
        pref.notification_type_id: pref
        for pref in UserPushPreference.objects.filter(user=request.user)
    }

    if request.method == 'POST':
        enabled_ids = set(map(int, request.POST.getlist('enabled_types')))
        for notif_type in all_types:
            is_enabled = notif_type.id in enabled_ids
            UserPushPreference.objects.update_or_create(
                user=request.user,
                notification_type=notif_type,
                defaults={'enabled': is_enabled}
            )
        return JsonResponse({'status': 'saved'})

    return render(request, 'push_notifications/my_preferences.html', {
        'all_types': all_types,
        'prefs': prefs,
    })