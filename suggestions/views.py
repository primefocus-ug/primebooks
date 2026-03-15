"""
reports/views.py

Views:
  submit_report   POST  /reports/submit/
  my_reports      GET   /reports/mine/
  report_detail   GET   /reports/<ticket_number>/

URL wiring — add to your main urls.py:
    from django.urls import path, include
    path('reports/', include('reports.urls')),

Rate limiting:
  Max 10 reports per user per 24 hours (configurable via REPORT_RATE_LIMIT in settings).
"""

from django.shortcuts               import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.http   import require_POST
from django.http                    import JsonResponse
from django.utils                   import timezone
from django.core.mail               import send_mail
from django.conf                    import settings
from datetime                       import timedelta
import json
from .models                        import Suggestion, SuggestionUpdate, SuggestionFeedback

RATE_LIMIT = getattr(settings, 'REPORT_RATE_LIMIT', 10)   # max submissions
RATE_WINDOW = getattr(settings, 'REPORT_RATE_WINDOW', 24)  # hours


# ─────────────────────────────────────────────────────────────
# Submit
# ─────────────────────────────────────────────────────────────

@login_required
@require_POST
def submit_report(request):
    user = request.user

    # ── Rate limit check ──
    window_start = timezone.now() - timedelta(hours=RATE_WINDOW)
    recent_count = Suggestion.objects.filter(
        submitted_by=user,
        created_at__gte=window_start,
    ).count()

    if recent_count >= RATE_LIMIT:
        return JsonResponse({
            'ok':    False,
            'error': f'You have reached the limit of {RATE_LIMIT} reports per {RATE_WINDOW} hours. '
                     f'Please try again later or contact support directly.',
        }, status=429)

    # ── Validate ──
    report_type  = request.POST.get('type', '').strip()
    title        = request.POST.get('title', '').strip()
    description  = request.POST.get('description', '').strip()
    priority     = request.POST.get('priority', 'medium').strip()
    affected_url = request.POST.get('affected_url', '').strip()
    affected_rec = request.POST.get('affected_record', '').strip()
    screenshot   = request.FILES.get('screenshot')

    valid_types    = [t[0] for t in Suggestion.TYPE_CHOICES]
    valid_priority = [p[0] for p in Suggestion.PRIORITY_CHOICES]

    errors = {}
    if report_type not in valid_types:
        errors['type'] = 'Please select a valid report type.'
    if not title:
        errors['title'] = 'Please enter a title.'
    if len(title) > 160:
        errors['title'] = 'Title must be 160 characters or fewer.'
    if not description:
        errors['description'] = 'Please describe the issue.'
    if priority not in valid_priority:
        priority = 'medium'

    if errors:
        return JsonResponse({'ok': False, 'errors': errors}, status=400)

    # ── Create ──
    report = Suggestion.objects.create(
        submitted_by    = user,
        type            = report_type,
        title           = title,
        description     = description,
        priority        = priority,
        affected_url    = affected_url[:500],
        affected_record = affected_rec[:200],
        screenshot      = screenshot,
    )

    # ── Auto-reply email to user ──
    _send_confirmation(report)

    # ── Admin notification email ──
    _notify_admins(report)

    return JsonResponse({
        'ok':            True,
        'ticket_number': report.ticket_number,
        'message':       f'Your report has been submitted. Ticket: {report.ticket_number}',
    })


# ─────────────────────────────────────────────────────────────
# My Reports
# ─────────────────────────────────────────────────────────────

@login_required
def my_reports(request):
    reports = (
        Suggestion.objects
        .filter(submitted_by=request.user)
        .prefetch_related('updates')
        .order_by('-created_at')
    )
    return render(request, 'suggestions/my_reports.html', {
        'reports':      reports,
        'page_title':   'My Reports',
        'active_count': reports.filter(status__in=['open', 'in_progress', 'waiting']).count(),
    })


# ─────────────────────────────────────────────────────────────
# Report Detail
# ─────────────────────────────────────────────────────────────

@login_required
def report_detail(request, ticket_number):
    report = get_object_or_404(
        Suggestion,
        ticket_number=ticket_number,
        submitted_by=request.user,
    )
    updates = report.updates.filter(is_internal=False).order_by('created_at')
    return render(request, 'suggestions/report_detail.html', {
        'report':     report,
        'updates':    updates,
        'page_title': f'Ticket {report.ticket_number}',
    })


# ─────────────────────────────────────────────────────────────
# Feedback
# ─────────────────────────────────────────────────────────────

@login_required
@require_POST
def submit_feedback(request, ticket_number):
    """
    POST /suggestions/<ticket>/feedback/
    Body JSON: { "resolved_ok": true, "rating": 4, "comment": "..." }
    Returns:   { "ok": true, "resolved_ok": true, "rating": 4 }
               or { "ok": false, "error": "..." }

    Side-effects when resolved_ok is false:
      - Ticket is re-opened (status → open, resolved_at cleared)
      - A public SuggestionUpdate timeline entry is created
      - Admin is notified by email
    """
    report = get_object_or_404(
        Suggestion,
        ticket_number=ticket_number,
        submitted_by=request.user,
    )

    if report.status != 'resolved':
        return JsonResponse(
            {'ok': False, 'error': 'Feedback can only be submitted on resolved tickets.'},
            status=400,
        )

    if hasattr(report, 'feedback'):
        return JsonResponse(
            {'ok': False, 'error': 'Feedback has already been submitted for this ticket.'},
            status=400,
        )

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'ok': False, 'error': 'Invalid JSON payload.'}, status=400)

    rating      = int(data.get('rating', 0))
    resolved_ok = bool(data.get('resolved_ok', True))
    comment     = str(data.get('comment', '')).strip()[:500]

    if not (1 <= rating <= 5):
        return JsonResponse({'ok': False, 'error': 'Rating must be between 1 and 5.'}, status=400)

    SuggestionFeedback.objects.create(
        report      = report,
        rating      = rating,
        resolved_ok = resolved_ok,
        comment     = comment,
    )

    # ── Auto-reopen if user not satisfied ──
    if not resolved_ok:
        old_status         = report.status
        report.status      = 'open'
        report.resolved_at = None
        report.save(update_fields=['status', 'resolved_at'])

        SuggestionUpdate.objects.create(
            report      = report,
            author      = None,
            update_type = 'status_change',
            old_status  = old_status,
            new_status  = 'open',
            message     = 'User indicated the issue was not resolved. Ticket re-opened automatically.',
            is_internal = False,
        )

        # Notify admin
        admin_email = getattr(settings, 'REPORT_ADMIN_EMAIL', None)
        if admin_email:
            try:
                send_mail(
                    subject=f'[{report.ticket_number}] Re-opened — User not satisfied ({rating}/5)',
                    message=(
                        f'Ticket {report.ticket_number} has been re-opened.\n\n'
                        f'User rating:  {rating}/5\n'
                        f'Resolved?:    No\n'
                        f'Comment:      {comment or "(none)"}\n\n'
                        f'Review: {getattr(settings, "SITE_URL", "")}'
                        f'/admin/suggestions/suggestion/{report.pk}/change/'
                    ),
                    from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@primebooks.sale'),
                    recipient_list=[admin_email] if isinstance(admin_email, str) else admin_email,
                    fail_silently=True,
                )
            except Exception:
                pass

    return JsonResponse({'ok': True, 'resolved_ok': resolved_ok, 'rating': rating})


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def _send_confirmation(report):
    try:
        user = report.submitted_by
        if user and user.email:
            send_mail(
                subject=f'[{report.ticket_number}] We received your report — PrimeBooks',
                message=(
                    f'Hi {user.get_full_name() or user.username},\n\n'
                    f'Thank you for reaching out. We have received your report and '
                    f'our team will review it shortly.\n\n'
                    f'Ticket number: {report.ticket_number}\n'
                    f'Type: {report.get_type_display()}\n'
                    f'Priority: {report.get_priority_display()}\n\n'
                    f'You can track the status of your report by logging into PrimeBooks '
                    f'and visiting Reports > My Reports.\n\n'
                    f'PrimeBooks Support Team'
                ),
                from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@primebooks.sale'),
                recipient_list=[user.email],
                fail_silently=True,
            )
    except Exception:
        pass


def _notify_admins(report):
    try:
        admin_email = getattr(settings, 'REPORT_ADMIN_EMAIL', None)
        if not admin_email:
            return
        user = report.submitted_by
        send_mail(
            subject=f'[{report.ticket_number}] New {report.get_type_display()} — {report.get_priority_display()} Priority',
            message=(
                f'A new report has been submitted.\n\n'
                f'Ticket:      {report.ticket_number}\n'
                f'Type:        {report.get_type_display()}\n'
                f'Priority:    {report.get_priority_display()}\n'
                f'Submitted by: {user} ({user.email if user else "unknown"})\n\n'
                f'Title: {report.title}\n\n'
                f'Description:\n{report.description}\n\n'
                f'Affected URL:    {report.affected_url or "N/A"}\n'
                f'Affected Record: {report.affected_record or "N/A"}\n\n'
                f'Review in admin: {getattr(settings, "SITE_URL", "")}/admin/reports/report/{report.pk}/change/'
            ),
            from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@primebooks.sale'),
            recipient_list=[admin_email] if isinstance(admin_email, str) else admin_email,
            fail_silently=True,
        )
    except Exception:
        pass