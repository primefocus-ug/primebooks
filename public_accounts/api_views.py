from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods
from .models import PublicUser, PublicUserActivity


@login_required
@require_http_methods(["GET"])
def user_search_api(request):
    """API endpoint for user search"""
    query = request.GET.get('q', '')

    if len(query) < 2:
        return JsonResponse({'results': []})

    users = PublicUser.objects.filter(
        Q(identifier__icontains=query) |
        Q(email__icontains=query) |
        Q(first_name__icontains=query) |
        Q(last_name__icontains=query) |
        Q(username__icontains=query)
    )[:10]

    results = [{
        'id': user.id,
        'identifier': user.identifier,
        'name': user.get_full_name(),
        'email': user.email,
        'avatar': user.avatar.url if user.avatar else None,
    } for user in users]

    return JsonResponse({'results': results})


@login_required
@require_http_methods(["POST"])
def unlock_user_api(request, user_id):
    """API endpoint to unlock a user account"""
    if not request.user.is_admin:
        return JsonResponse({'error': 'Permission denied'}, status=403)

    try:
        user = PublicUser.objects.get(pk=user_id)
        user.unlock_account()

        # Log activity
        PublicUserActivity.objects.create(
            user=request.user,
            action='UPDATE',
            app_name='public_accounts',
            model_name='PublicUser',
            object_id=str(user_id),
            description=f'Unlocked user account: {user}',
            ip_address=request.META.get('REMOTE_ADDR'),
        )

        return JsonResponse({'success': True, 'message': 'User unlocked successfully'})
    except PublicUser.DoesNotExist:
        return JsonResponse({'error': 'User not found'}, status=404)


@login_required
@require_http_methods(["GET"])
def activity_stats_api(request):
    """API endpoint for activity statistics"""
    from django.db.models import Count
    from datetime import timedelta

    days = int(request.GET.get('days', 7))
    start_date = timezone.now() - timedelta(days=days)

    activities = PublicUserActivity.objects.filter(
        timestamp__gte=start_date
    ).values('action').annotate(count=Count('id'))

    stats = {activity['action']: activity['count'] for activity in activities}

    return JsonResponse({'stats': stats, 'period': f'Last {days} days'})


@login_required
@require_http_methods(["POST"])
def verify_email_api(request, user_id):
    """API endpoint to manually verify user email"""
    if not request.user.is_admin:
        return JsonResponse({'error': 'Permission denied'}, status=403)

    try:
        user = PublicUser.objects.get(pk=user_id)
        user.email_verified = True
        user.save(update_fields=['email_verified'])

        return JsonResponse({'success': True, 'message': 'Email verified successfully'})
    except PublicUser.DoesNotExist:
        return JsonResponse({'error': 'User not found'}, status=404)