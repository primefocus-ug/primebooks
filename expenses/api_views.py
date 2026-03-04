"""
api_views.py — JSON/AJAX API endpoints for the expenses app

All endpoints are updated to use the revised model:
  • user= instead of created_by=
  • status values match the new lowercase STATUS_CHOICES
  • amounts aggregated on amount_base for currency-correct totals
  • ExpenseApproval.record() used for approve / reject workflow
  • Dead references to ExpenseCategory / ExpenseComment / expense_number removed
"""

import json
import logging

from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q, Sum
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from .models import Budget, Expense, ExpenseApproval

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------

@login_required
@require_http_methods(["GET"])
def expense_stats_api(request):
    """Aggregate expense statistics for the current user."""
    qs = Expense.objects.filter(user=request.user)

    stats = {
        'total_count': qs.count(),
        'by_status': {
            status: qs.filter(status=status).count()
            for status, _ in Expense.STATUS_CHOICES
        },
        'amounts': {
            'total_base': float(qs.aggregate(t=Sum('amount_base'))['t'] or 0),
            'pending_base': float(
                qs.filter(status__in=('submitted', 'under_review'))
                .aggregate(t=Sum('amount_base'))['t'] or 0
            ),
            'approved_base': float(
                qs.filter(status='approved')
                .aggregate(t=Sum('amount_base'))['t'] or 0
            ),
        },
        'this_month_base': float(
            qs.filter(
                date__month=timezone.now().month,
                date__year=timezone.now().year,
            ).aggregate(t=Sum('amount_base'))['t'] or 0
        ),
    }

    return JsonResponse(stats)


# ---------------------------------------------------------------------------
# Chart data
# ---------------------------------------------------------------------------

@login_required
@require_http_methods(["GET"])
def expense_chart_data_api(request):
    """Monthly trend (last 7 months) for the current user."""
    from datetime import timedelta

    qs = Expense.objects.filter(user=request.user)
    months_data = []

    for i in range(6, -1, -1):
        base = timezone.now().date().replace(day=1) - timedelta(days=30 * i)
        month_qs = qs.filter(date__year=base.year, date__month=base.month)
        months_data.append({
            'month': base.strftime('%b %Y'),
            'total_base': float(month_qs.aggregate(t=Sum('amount_base'))['t'] or 0),
            'count': month_qs.count(),
        })

    return JsonResponse({'monthly_trend': months_data})


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

@login_required
@require_http_methods(["GET"])
def expense_search_api(request):
    """Full-text search across description, vendor, notes, and tags."""
    query = request.GET.get('q', '').strip()
    limit = min(int(request.GET.get('limit', 10)), 50)  # cap at 50

    qs = Expense.objects.filter(user=request.user)

    if query:
        qs = qs.filter(
            Q(description__icontains=query) |
            Q(vendor__icontains=query) |
            Q(notes__icontains=query) |
            Q(tags__name__icontains=query)
        ).distinct()

    qs = qs.prefetch_related('tags')[:limit]

    results = [
        {
            'id': exp.pk,
            'description': exp.description,
            'vendor': exp.vendor,
            'amount': float(exp.amount),
            'currency': exp.currency,
            'amount_base': float(exp.amount_base),
            'status': exp.status,
            'status_display': exp.get_status_display(),
            'date': exp.date.strftime('%Y-%m-%d'),
            'tags': list(exp.tags.names()),
            'url': f'/expenses/{exp.pk}/',
        }
        for exp in qs
    ]

    return JsonResponse({'results': results, 'count': len(results)})


# ---------------------------------------------------------------------------
# Quick approval (AJAX)
# ---------------------------------------------------------------------------

@login_required
@require_http_methods(["POST"])
def quick_approve_api(request, pk):
    """Single-expense approve endpoint for AJAX dashboard buttons."""
    if not request.user.has_perm('expenses.approve_expense'):
        return JsonResponse({'success': False, 'error': 'Permission denied'}, status=403)

    try:
        expense = Expense.objects.get(pk=pk)
    except Expense.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Expense not found'}, status=404)

    if not expense.can_be_approved():
        return JsonResponse({
            'success': False,
            'error': f'Cannot approve an expense with status "{expense.status}"',
        }, status=400)

    # Prevent self-approval
    if expense.user == request.user:
        return JsonResponse({'success': False, 'error': 'You cannot approve your own expense'}, status=403)

    try:
        body = json.loads(request.body or '{}')
        comment = body.get('comment', '')
    except json.JSONDecodeError:
        comment = ''

    record = ExpenseApproval.record(expense, request.user, 'approved', comment)

    return JsonResponse({
        'success': True,
        'message': f'Expense approved',
        'status': expense.status,
        'status_display': expense.get_status_display(),
        'approval_id': record.pk,
    })


@login_required
@require_http_methods(["POST"])
def quick_reject_api(request, pk):
    """Single-expense reject endpoint."""
    if not request.user.has_perm('expenses.approve_expense'):
        return JsonResponse({'success': False, 'error': 'Permission denied'}, status=403)

    try:
        expense = Expense.objects.get(pk=pk)
    except Expense.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Expense not found'}, status=404)

    if not expense.can_be_rejected():
        return JsonResponse({
            'success': False,
            'error': f'Cannot reject an expense with status "{expense.status}"',
        }, status=400)

    try:
        body = json.loads(request.body or '{}')
        comment = body.get('comment', '').strip()
    except json.JSONDecodeError:
        comment = ''

    if not comment:
        return JsonResponse({'success': False, 'error': 'A rejection reason is required'}, status=400)

    record = ExpenseApproval.record(expense, request.user, 'rejected', comment)

    return JsonResponse({
        'success': True,
        'message': 'Expense rejected',
        'status': expense.status,
        'approval_id': record.pk,
    })


# ---------------------------------------------------------------------------
# Bulk actions (JSON body)
# ---------------------------------------------------------------------------

@login_required
@require_http_methods(["POST"])
def bulk_action_api(request):
    """
    Handle bulk actions via JSON body.

    Expected body:
        {
            "action": "submit" | "approve" | "reject" | "delete" | "tag",
            "expense_ids": [1, 2, 3],
            "tag_name": "...",   // only for action=tag
            "comment": "..."     // only for action=reject
        }
    """
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON body'}, status=400)

    action = data.get('action')
    expense_ids = data.get('expense_ids', [])

    if not action or not expense_ids:
        return JsonResponse({'success': False, 'error': 'action and expense_ids are required'}, status=400)

    results = {'success': True, 'processed': 0, 'failed': 0, 'errors': []}

    try:
        if action in ('approve', 'reject'):
            if not request.user.has_perm('expenses.approve_expense'):
                return JsonResponse({'success': False, 'error': 'Permission denied'}, status=403)
            qs = Expense.objects.filter(pk__in=expense_ids)
        else:
            qs = Expense.objects.filter(pk__in=expense_ids, user=request.user)

        if action == 'submit':
            for exp in qs.filter(status__in=('draft', 'resubmit')):
                try:
                    ExpenseApproval.record(exp, request.user, 'submitted')
                    results['processed'] += 1
                except Exception as exc:
                    results['failed'] += 1
                    results['errors'].append(f'Expense {exp.pk}: {exc}')

        elif action == 'approve':
            comment = data.get('comment', '')
            for exp in qs.filter(status__in=('submitted', 'under_review')):
                if exp.user == request.user:
                    results['failed'] += 1
                    results['errors'].append(f'Expense {exp.pk}: cannot self-approve')
                    continue
                try:
                    ExpenseApproval.record(exp, request.user, 'approved', comment)
                    results['processed'] += 1
                except Exception as exc:
                    results['failed'] += 1
                    results['errors'].append(f'Expense {exp.pk}: {exc}')

        elif action == 'reject':
            comment = data.get('comment', '').strip()
            if not comment:
                return JsonResponse({'success': False, 'error': 'comment (rejection reason) required'}, status=400)
            for exp in qs.filter(status__in=('submitted', 'under_review')):
                try:
                    ExpenseApproval.record(exp, request.user, 'rejected', comment)
                    results['processed'] += 1
                except Exception as exc:
                    results['failed'] += 1
                    results['errors'].append(f'Expense {exp.pk}: {exc}')

        elif action == 'tag':
            tag_name = data.get('tag_name', '').strip()
            if not tag_name:
                return JsonResponse({'success': False, 'error': 'tag_name required'}, status=400)
            for exp in qs:
                exp.tags.add(tag_name)
                results['processed'] += 1

        elif action == 'delete':
            count = qs.filter(status='draft').count()
            qs.filter(status='draft').delete()
            results['processed'] = count

        else:
            return JsonResponse({'success': False, 'error': f'Unknown action: {action}'}, status=400)

        return JsonResponse(results)

    except Exception as exc:
        logger.exception("bulk_action_api error: %s", exc)
        return JsonResponse({'success': False, 'error': str(exc)}, status=500)


# ---------------------------------------------------------------------------
# Budget status
# ---------------------------------------------------------------------------

@login_required
@require_http_methods(["GET"])
def budget_status_api(request):
    """Return current spending status for all active budgets."""
    budgets = Budget.objects.filter(user=request.user, is_active=True)

    data = [
        {
            'id': b.pk,
            'name': b.name,
            'amount': float(b.amount),
            'currency': b.currency,
            'period': b.period,
            'period_display': b.get_period_display(),
            'spent': float(b.get_current_spending()),
            'remaining': float(b.get_remaining()),
            'percentage': round(float(b.get_percentage_used()), 1),
            'status': b.get_status_color(),
            'over_threshold': b.is_over_threshold(),
        }
        for b in budgets
    ]

    return JsonResponse({'budgets': data})


# ---------------------------------------------------------------------------
# Approval queue (for approvers)
# ---------------------------------------------------------------------------

@login_required
@require_http_methods(["GET"])
def approval_queue_api(request):
    """Return pending expenses for approvers."""
    if not request.user.has_perm('expenses.approve_expense'):
        return JsonResponse({'success': False, 'error': 'Permission denied'}, status=403)

    pending = Expense.objects.filter(
        status__in=('submitted', 'under_review')
    ).select_related('user').prefetch_related('tags').order_by('updated_at')

    data = [
        {
            'id': exp.pk,
            'description': exp.description,
            'vendor': exp.vendor,
            'amount': float(exp.amount),
            'currency': exp.currency,
            'amount_base': float(exp.amount_base),
            'submitted_by': str(exp.user),
            'status': exp.status,
            'status_display': exp.get_status_display(),
            'date': exp.date.strftime('%Y-%m-%d'),
            'tags': list(exp.tags.names()),
            'url': f'/expenses/{exp.pk}/',
        }
        for exp in pending
    ]

    return JsonResponse({'pending': data, 'count': len(data)})