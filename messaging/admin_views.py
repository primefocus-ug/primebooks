from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.utils import timezone
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_http_methods
from django.db.models import Count, Q, Sum, Max, Avg
from django.views.decorators.http import require_http_methods
from datetime import timedelta
import csv

from .models import (
    Conversation, Message, ConversationParticipant,
    SystemAnnouncement, AnnouncementRead, MessageAuditLog,
    MessagingStatistics, LegalAccessRequest, LegalAccessLog
)
from .legal_access import LegalAccessService


def is_admin(user):
    """Check if user is saas_admin or company_admin"""
    return (
            user.is_authenticated and
            (user.is_superuser or
             getattr(user, 'is_saas_admin', False) or
             getattr(user, 'role', None) in ['admin', 'super_admin', 'company_admin'])
    )


from .models import (
    Conversation, Message, ConversationParticipant,
    SystemAnnouncement, AnnouncementRead, MessageAuditLog,
    MessagingStatistics
)

@login_required
@user_passes_test(is_admin)
def admin_dashboard(request):
    """
    Main admin dashboard for messaging overview
    """
    # Get date range
    today = timezone.now().date()
    last_30_days = today - timedelta(days=30)

    # Overall statistics
    stats = {
        'total_conversations': Conversation.objects.filter(is_active=True).count(),
        'total_messages': Message.objects.filter(is_deleted=False).count(),
        'active_users_today': ConversationParticipant.objects.filter(
            last_read_at__date=today
        ).values('user').distinct().count(),
        'messages_today': Message.objects.filter(
            created_at__date=today,
            is_deleted=False
        ).count(),
    }

    # Conversation breakdown
    conversation_types = Conversation.objects.filter(
        is_active=True
    ).values('conversation_type').annotate(
        count=Count('id')
    )

    # Recent activity
    recent_conversations = Conversation.objects.filter(
        is_active=True
    ).annotate(
        last_activity=Max('messages__created_at'),
        total_messages=Count('messages', filter=Q(messages__is_deleted=False))
    ).order_by('-last_activity')[:10]

    # Audit log
    recent_audit = MessageAuditLog.objects.all()[:50]

    # Chart data - Messages per day (last 30 days)
    daily_stats = MessagingStatistics.objects.filter(
        date__gte=last_30_days
    ).values('date').annotate(
        total=Sum('total_messages')
    ).order_by('date')

    context = {
        'stats': stats,
        'conversation_types': conversation_types,
        'recent_conversations': recent_conversations,
        'recent_audit': recent_audit,
        'daily_stats': list(daily_stats),
        'page_title': 'Messaging Admin Dashboard',
    }

    return render(request, 'messaging/admin/dashboard.html', context)


@login_required
@user_passes_test(is_admin)
def admin_conversations_list(request):
    """
    List all conversations with filtering
    """
    conversations = Conversation.objects.filter(
        is_active=True
    ).annotate(
        participant_count=Count('participants', filter=Q(participants__is_active=True)),
        message_count=Count('messages', filter=Q(messages__is_deleted=False)),
        last_activity=Max('messages__created_at')
    ).select_related('created_by').order_by('-last_activity')

    # Filtering
    conv_type = request.GET.get('type')
    if conv_type:
        conversations = conversations.filter(conversation_type=conv_type)

    search = request.GET.get('search')
    if search:
        conversations = conversations.filter(
            Q(name__icontains=search) |
            Q(created_by__username__icontains=search)
        )

    context = {
        'conversations': conversations,
        'page_title': 'All Conversations',
    }

    return render(request, 'messaging/admin/conversations_list.html', context)


@login_required
@user_passes_test(is_admin)
def admin_conversation_detail(request, conversation_id):
    """
    View conversation details and messages (metadata only for privacy)
    """
    conversation = get_object_or_404(Conversation, id=conversation_id)

    participants = ConversationParticipant.objects.filter(
        conversation=conversation,
        is_active=True
    ).select_related('user')

    # Get message metadata (not decrypted content)
    messages_data = Message.objects.filter(
        conversation=conversation,
        is_deleted=False
    ).select_related('sender').values(
        'id', 'sender__username', 'message_type',
        'created_at', 'is_edited', 'edited_at'
    ).order_by('-created_at')[:100]

    # Audit log for this conversation
    audit_logs = MessageAuditLog.objects.filter(
        conversation=conversation
    ).order_by('-timestamp')[:50]

    context = {
        'conversation': conversation,
        'participants': participants,
        'messages_metadata': messages_data,
        'audit_logs': audit_logs,
        'page_title': f'Conversation: {conversation.name or conversation.id}',
    }

    return render(request, 'messaging/admin/conversation_detail.html', context)


@login_required
@user_passes_test(is_admin)
def admin_announcements(request):
    """
    Manage system announcements
    """
    announcements = SystemAnnouncement.objects.all().order_by('-created_at')

    context = {
        'announcements': announcements,
        'page_title': 'System Announcements',
    }

    return render(request, 'messaging/admin/announcements.html', context)


@login_required
@user_passes_test(is_admin)
@require_http_methods(["GET", "POST"])
def admin_create_announcement(request):
    """
    Create new system announcement
    """
    if request.method == 'POST':
        try:
            announcement = SystemAnnouncement.objects.create(
                title=request.POST.get('title'),
                message=request.POST.get('message'),
                announcement_type=request.POST.get('announcement_type', 'info'),
                priority=request.POST.get('priority', 'medium'),
                target_all_tenants=request.POST.get('target_all_tenants') == 'on',
                show_in_app=request.POST.get('show_in_app') == 'on',
                send_email=request.POST.get('send_email') == 'on',
                is_dismissible=request.POST.get('is_dismissible') == 'on',
                action_text=request.POST.get('action_text', ''),
                action_url=request.POST.get('action_url', ''),
                created_by=request.user
            )

            # Schedule or send immediately
            scheduled_for = request.POST.get('scheduled_for')
            if scheduled_for:
                announcement.scheduled_for = scheduled_for
                announcement.save()
            else:
                # Send immediately
                from .tasks import broadcast_announcement
                broadcast_announcement.delay(announcement.id)
                announcement.mark_as_sent()

            messages.success(request, 'Announcement created successfully!')
            return redirect('messaging:admin_announcements')

        except Exception as e:
            messages.error(request, f'Error creating announcement: {str(e)}')

    context = {
        'page_title': 'Create Announcement',
    }

    return render(request, 'messaging/admin/create_announcement.html', context)


@login_required
@user_passes_test(is_admin)
def admin_audit_log(request):
    """
    View complete audit log
    """
    logs = MessageAuditLog.objects.all().select_related(
        'user', 'conversation'
    ).order_by('-timestamp')

    # Filtering
    action_type = request.GET.get('action_type')
    if action_type:
        logs = logs.filter(action_type=action_type)

    user_id = request.GET.get('user_id')
    if user_id:
        logs = logs.filter(user_id=user_id)

    # Pagination
    from django.core.paginator import Paginator
    paginator = Paginator(logs, 100)
    page = request.GET.get('page', 1)
    logs_page = paginator.get_page(page)

    context = {
        'logs': logs_page,
        'page_title': 'Audit Log',
    }

    return render(request, 'messaging/admin/audit_log.html', context)


@login_required
@user_passes_test(is_admin)
def export_statistics_csv(request):
    """
    Export statistics as CSV
    """
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="messaging_stats.csv"'

    writer = csv.writer(response)
    writer.writerow([
        'Date', 'Tenant', 'Total Messages', 'Total Conversations',
        'Active Users', 'Files Shared', 'Storage (MB)'
    ])

    stats = MessagingStatistics.objects.all().order_by('-date')
    for stat in stats:
        writer.writerow([
            stat.date,
            stat.tenant_name or 'All',
            stat.total_messages,
            stat.total_conversations,
            stat.active_users,
            stat.files_shared,
            stat.total_storage_mb,
        ])

    return response



@login_required
@user_passes_test(is_admin)
def admin_statistics(request):
    """
    Detailed statistics and analytics
    """
    # Date range
    end_date = timezone.now().date()
    start_date = end_date - timedelta(days=30)

    date_from = request.GET.get('from', start_date.isoformat())
    date_to = request.GET.get('to', end_date.isoformat())

    try:
        start_date = timezone.datetime.strptime(date_from, '%Y-%m-%d').date()
        end_date = timezone.datetime.strptime(date_to, '%Y-%m-%d').date()
    except:
        start_date = end_date - timedelta(days=30)

    # Get daily stats
    daily_stats = MessagingStatistics.objects.filter(
        date__gte=start_date,
        date__lte=end_date
    ).order_by('date')

    # Aggregate stats
    total_stats = daily_stats.aggregate(
        total_messages=Sum('total_messages'),
        total_conversations=Sum('total_conversations'),
        total_files=Sum('files_shared'),
        total_storage=Sum('total_storage_mb'),
        avg_active_users=Avg('active_users')
    )

    # Top users by message count
    top_users = Message.objects.filter(
        is_deleted=False,
        created_at__date__gte=start_date,
        created_at__date__lte=end_date
    ).values(
        'sender__username', 'sender__email'
    ).annotate(
        count=Count('id')
    ).order_by('-count')[:10]

    # Top conversations by message count
    # Top conversations by message count
    top_conversations = Conversation.objects.filter(
        messages__created_at__date__gte=start_date,
        messages__created_at__date__lte=end_date,
        is_active=True
    ).annotate(
        annotated_message_count=Count('messages', filter=Q(messages__is_deleted=False))
    ).order_by('-annotated_message_count')[:10]

    # Conversation type breakdown
    conversation_breakdown = Conversation.objects.filter(
        created_at__date__gte=start_date,
        created_at__date__lte=end_date,
        is_active=True
    ).values('conversation_type').annotate(
        count=Count('id')
    )

    # Messages by day of week
    messages_by_day = Message.objects.filter(
        created_at__date__gte=start_date,
        created_at__date__lte=end_date,
        is_deleted=False
    ).extra(
        select={'day': 'EXTRACT(dow FROM created_at)'}
    ).values('day').annotate(
        count=Count('id')
    ).order_by('day')

    # Messages by hour
    messages_by_hour = Message.objects.filter(
        created_at__date__gte=start_date,
        created_at__date__lte=end_date,
        is_deleted=False
    ).extra(
        select={'hour': 'EXTRACT(hour FROM created_at)'}
    ).values('hour').annotate(
        count=Count('id')
    ).order_by('hour')

    context = {
        'daily_stats': list(daily_stats.values()),
        'total_stats': total_stats,
        'top_users': top_users,
        'top_conversations': top_conversations,
        'conversation_breakdown': conversation_breakdown,
        'messages_by_day': list(messages_by_day),
        'messages_by_hour': list(messages_by_hour),
        'start_date': start_date,
        'end_date': end_date,
        'page_title': 'Messaging Statistics',
    }

    return render(request, 'messaging/admin/statistics.html', context)


@login_required
@user_passes_test(is_admin)
def export_statistics_csv(request):
    """Export statistics as CSV"""
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="messaging_stats_{timezone.now().strftime("%Y%m%d")}.csv"'

    writer = csv.writer(response)
    writer.writerow([
        'Date', 'Tenant', 'Total Messages', 'Total Conversations',
        'Active Users', 'Files Shared', 'Storage (MB)'
    ])

    stats = MessagingStatistics.objects.all().order_by('-date')[:90]
    for stat in stats:
        writer.writerow([
            stat.date,
            stat.tenant_name or 'All',
            stat.total_messages,
            stat.total_conversations,
            stat.active_users,
            stat.files_shared,
            stat.total_storage_mb,
        ])

    return response


@login_required
@user_passes_test(is_admin)
def legal_requests_list(request):
    """
    List all legal access requests
    """
    requests = LegalAccessRequest.objects.all().select_related(
        'target_user',
        'target_conversation',
        'approved_by',
        'exported_by'
    ).order_by('-created_at')

    # Count by status
    pending_count = requests.filter(status='pending').count()
    approved_count = requests.filter(status='approved').count()
    fulfilled_count = requests.filter(status='fulfilled').count()
    denied_count = requests.filter(status='denied').count()

    # Get all users for dropdown
    from django.contrib.auth import get_user_model
    User = get_user_model()
    all_users = User.objects.filter(is_active=True).order_by('username')

    context = {
        'requests': requests,
        'pending_count': pending_count,
        'approved_count': approved_count,
        'fulfilled_count': fulfilled_count,
        'denied_count': denied_count,
        'all_users': all_users,
        'page_title': 'Legal Access Requests',
    }

    return render(request, 'messaging/admin/legal_requests.html', context)


@login_required
@user_passes_test(is_admin)
def legal_request_detail(request, request_id):
    """
    View detailed legal request information
    """
    legal_request = get_object_or_404(
        LegalAccessRequest.objects.select_related(
            'target_user',
            'target_conversation',
            'approved_by',
            'exported_by'
        ),
        id=request_id
    )

    # Get audit logs
    audit_logs = LegalAccessLog.objects.filter(
        request=legal_request
    ).select_related('performed_by').order_by('-timestamp')

    # Get messages in scope (metadata only)
    if legal_request.target_user:
        messages_query = Message.objects.filter(
            conversation__participants__user=legal_request.target_user,
            is_deleted=False
        )

        if legal_request.target_conversation:
            messages_query = messages_query.filter(
                conversation=legal_request.target_conversation
            )

        if legal_request.date_range_start:
            messages_query = messages_query.filter(
                created_at__gte=legal_request.date_range_start
            )

        if legal_request.date_range_end:
            messages_query = messages_query.filter(
                created_at__lte=legal_request.date_range_end
            )

        message_count = messages_query.count()
        conversation_count = messages_query.values('conversation').distinct().count()
    else:
        message_count = 0
        conversation_count = 0

    context = {
        'legal_request': legal_request,
        'audit_logs': audit_logs,
        'message_count': message_count,
        'conversation_count': conversation_count,
        'page_title': f'Legal Request: {legal_request.request_number}',
    }

    return render(request, 'messaging/admin/legal_request_detail.html', context)


@login_required
@user_passes_test(is_admin)
@require_http_methods(["POST"])
def create_legal_request(request):
    """
    Create new legal access request
    """
    try:
        from django.contrib.auth import get_user_model
        User = get_user_model()

        request_number = request.POST.get('request_number')
        request_type = request.POST.get('request_type')
        authority_name = request.POST.get('authority_name')
        authority_contact = request.POST.get('authority_contact')
        badge_number = request.POST.get('badge_number', '')
        target_user_id = request.POST.get('target_user')
        request_description = request.POST.get('request_description')
        legal_document = request.FILES.get('legal_document')

        # Optional fields
        date_range_start = request.POST.get('date_range_start')
        date_range_end = request.POST.get('date_range_end')

        # Validate
        if not all([request_number, request_type, authority_name, authority_contact,
                    target_user_id, request_description, legal_document]):
            messages.error(request, 'All required fields must be filled')
            return redirect('messaging:legal_requests')

        target_user = User.objects.get(id=target_user_id)

        # Create request
        legal_request = LegalAccessService.create_access_request(
            request_number=request_number,
            request_type=request_type,
            authority_name=authority_name,
            authority_contact=authority_contact,
            target_user=target_user,
            legal_document=legal_document,
            request_description=request_description,
            date_range_start=date_range_start if date_range_start else None,
            date_range_end=date_range_end if date_range_end else None,
        )

        if badge_number:
            legal_request.badge_number = badge_number
            legal_request.save()

        messages.success(request, f'Legal request {request_number} created successfully')
        return redirect('messaging:legal_request_detail', request_id=legal_request.id)

    except Exception as e:
        messages.error(request, f'Error creating request: {str(e)}')
        return redirect('messaging:legal_requests')


@login_required
@user_passes_test(is_admin)
@require_http_methods(["POST"])
def approve_legal_request(request, request_id):
    """
    Approve legal access request
    """
    try:
        legal_request = LegalAccessService.approve_request(
            request_id=request_id,
            approved_by_user=request.user
        )

        return JsonResponse({
            'success': True,
            'message': 'Request approved successfully',
            'request_id': legal_request.id
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=400)


@login_required
@user_passes_test(is_admin)
@require_http_methods(["POST"])
def deny_legal_request(request, request_id):
    """
    Deny legal access request
    """
    try:
        import json
        data = json.loads(request.body)
        reason = data.get('reason', 'No reason provided')

        legal_request = LegalAccessService.deny_request(
            request_id=request_id,
            denied_by_user=request.user,
            reason=reason
        )

        return JsonResponse({
            'success': True,
            'message': 'Request denied'
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=400)


@login_required
@user_passes_test(is_admin)
@require_http_methods(["POST"])
def export_legal_messages(request, request_id):
    """
    Export decrypted messages for legal request
    """
    try:
        legal_request, password = LegalAccessService.export_decrypted_messages(
            request_id=request_id,
            exported_by_user=request.user
        )

        return JsonResponse({
            'success': True,
            'password': password,
            'message': 'Export completed successfully'
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=400)


@login_required
@user_passes_test(is_admin)
def download_legal_export(request, request_id):
    """
    Download legal export file
    """
    legal_request = get_object_or_404(LegalAccessRequest, id=request_id)

    if legal_request.status != 'fulfilled' or not legal_request.export_file:
        messages.error(request, 'Export file not available')
        return redirect('messaging:legal_request_detail', request_id=request_id)

    # Log access
    LegalAccessService.log_access(
        request_id=request_id,
        action='download_export',
        user=request.user,
        ip_address=request.META.get('REMOTE_ADDR', '0.0.0.0'),
        user_agent=request.META.get('HTTP_USER_AGENT', '')[:500]
    )

    # Return file
    from django.http import FileResponse
    response = FileResponse(
        legal_request.export_file.open('rb'),
        content_type='application/zip'
    )
    response['Content-Disposition'] = f'attachment; filename="{legal_request.export_file.name}"'

    return response

