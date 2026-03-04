"""
views.py — Expense app views

New / enhanced over original:
  • ExpenseFilterForm validation (date_from > date_to now raises a user-visible error)
  • Bulk actions: submit, approve, reject, tag, delete, export CSV / PDF
  • CSV export view
  • PDF export view (WeasyPrint — falls back to plain CSV if not installed)
  • Receipt OCR trigger: queues process_receipt_ocr task after upload
  • Approval workflow views: submit, approve, reject, review history
  • currency & status columns in list / detail views
"""

import csv
import io
from datetime import date
import json
import logging
from datetime import timedelta
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.db.models import Avg, Count, Q, Sum
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST

from .forms import BudgetForm, BulkExpenseActionForm, ExpenseFilterForm, ExpenseForm
from .models import Budget, Expense, ExpenseApproval

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _trigger_budget_alert_if_needed(budget) -> None:
    """
    Fire send_budget_alert_email as a Celery task if the budget has crossed
    its alert threshold. Safe to call synchronously — the actual email send
    happens asynchronously in the worker.
    """
    try:
        if budget.is_over_threshold():
            from .tasks import send_budget_alert_email
            send_budget_alert_email.delay(budget.pk)
    except Exception as exc:
        logger.warning("Could not queue budget alert for budget %s: %s", budget.pk, exc)


def _check_budgets_after_expense(user) -> None:
    """
    After an expense is created or edited, re-check all of that user's budgets
    and fire alerts for any that have crossed their threshold.
    """
    for budget in Budget.objects.filter(user=user, is_active=True):
        _trigger_budget_alert_if_needed(budget)


# ===========================================================================
# Dashboard
# ===========================================================================

@login_required
def dashboard(request):
    """Main dashboard with analytics"""
    user = request.user
    today = timezone.now().date()

    week_start = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)
    year_start = today.replace(month=1, day=1)

    total_expenses = Expense.objects.filter(user=user).count()

    today_expenses = Expense.objects.filter(user=user, date=today)
    today_total = today_expenses.aggregate(total=Sum('amount_base'))['total'] or 0

    week_expenses = Expense.objects.filter(user=user, date__gte=week_start, date__lte=today)
    week_total = week_expenses.aggregate(total=Sum('amount_base'))['total'] or 0

    month_expenses = Expense.objects.filter(user=user, date__gte=month_start, date__lte=today)
    month_total = month_expenses.aggregate(total=Sum('amount_base'))['total'] or 0

    year_expenses = Expense.objects.filter(user=user, date__gte=year_start, date__lte=today)
    year_total = year_expenses.aggregate(total=Sum('amount_base'))['total'] or 0

    recent_expenses = Expense.objects.filter(user=user).select_related()[:10]

    # Top tags
    all_expenses = Expense.objects.filter(user=user)
    tag_stats = {}
    for expense in all_expenses:
        for tag in expense.tags.all():
            if tag.name not in tag_stats:
                tag_stats[tag.name] = {'count': 0, 'total': Decimal('0')}
            tag_stats[tag.name]['count'] += 1
            tag_stats[tag.name]['total'] += expense.amount_base

    top_tags = sorted(tag_stats.items(), key=lambda x: x[1]['total'], reverse=True)[:10]

    # Budget alerts
    budgets = Budget.objects.filter(user=user, is_active=True)
    budget_alerts = []
    for budget in budgets:
        percentage = budget.get_percentage_used()
        if budget.is_over_threshold():
            budget_alerts.append({
                'budget': budget,
                'percentage': round(float(percentage), 1),
                'spent': budget.get_current_spending(),
                'remaining': budget.get_remaining(),
                'status': budget.get_status_color()
            })

    # Pending approval count (expenses submitted by this user awaiting decision)
    pending_approval_count = Expense.objects.filter(
        user=user, status__in=('submitted', 'under_review')
    ).count()

    # Monthly trend (last 12 months)
    monthly_data = []
    for i in range(11, -1, -1):
        date = today - timedelta(days=30 * i)
        m_start = date.replace(day=1)
        if date.month == 12:
            m_end = date.replace(day=31)
        else:
            m_end = (date.replace(month=date.month + 1, day=1) - timedelta(days=1))

        m_expenses = Expense.objects.filter(user=user, date__gte=m_start, date__lte=m_end)
        monthly_data.append({
            'month': m_start.strftime('%b %Y'),
            'total': float(m_expenses.aggregate(total=Sum('amount_base'))['total'] or 0),
            'count': m_expenses.count(),
        })

    # Payment method breakdown
    payment_stats = {}
    for expense in all_expenses:
        method = expense.payment_method or 'Not Specified'
        if method not in payment_stats:
            payment_stats[method] = {'count': 0, 'total': Decimal('0')}
        payment_stats[method]['count'] += 1
        payment_stats[method]['total'] += expense.amount_base

    context = {
        'total_expenses': total_expenses,
        'today_total': today_total,
        'today_count': today_expenses.count(),
        'week_total': week_total,
        'week_count': week_expenses.count(),
        'month_total': month_total,
        'month_count': month_expenses.count(),
        'year_total': year_total,
        'year_count': year_expenses.count(),
        'recent_expenses': recent_expenses,
        'top_tags': top_tags,
        'budget_alerts': budget_alerts,
        'pending_approval_count': pending_approval_count,
        'monthly_data': json.dumps(monthly_data),
        'tag_stats': json.dumps([
            {'name': k, 'total': float(v['total']), 'count': v['count']}
            for k, v in top_tags
        ]),
        'payment_stats': json.dumps([
            {'method': k, 'total': float(v['total']), 'count': v['count']}
            for k, v in payment_stats.items()
        ]),
    }

    return render(request, 'expenses/dashboard.html', context)


# ===========================================================================
# Expense list & filtering
# ===========================================================================

@login_required
def expense_list(request):
    """Expense list with validated filtering and bulk action support."""
    expenses = Expense.objects.filter(user=request.user).prefetch_related('tags')

    filter_form = ExpenseFilterForm(request.GET or None)
    filter_errors = []

    if filter_form.is_valid():
        cd = filter_form.cleaned_data

        if cd.get('search'):
            expenses = expenses.filter(
                Q(description__icontains=cd['search']) |
                Q(notes__icontains=cd['search']) |
                Q(vendor__icontains=cd['search'])
            )

        if cd.get('tags'):
            tag_list = [t.strip() for t in cd['tags'].split(',') if t.strip()]
            if tag_list:
                expenses = expenses.filter(tags__name__in=tag_list).distinct()

        if cd.get('payment_method'):
            expenses = expenses.filter(payment_method=cd['payment_method'])

        if cd.get('currency'):
            expenses = expenses.filter(currency=cd['currency'])

        if cd.get('status'):
            expenses = expenses.filter(status=cd['status'])

        today = timezone.now().date()
        period = cd.get('period')
        if period == 'today':
            expenses = expenses.filter(date=today)
        elif period == 'week':
            expenses = expenses.filter(date__gte=today - timedelta(days=today.weekday()), date__lte=today)
        elif period == 'month':
            expenses = expenses.filter(date__gte=today.replace(day=1), date__lte=today)
        elif period == 'quarter':
            qm = ((today.month - 1) // 3) * 3 + 1
            expenses = expenses.filter(date__gte=today.replace(month=qm, day=1), date__lte=today)
        elif period == 'year':
            expenses = expenses.filter(date__gte=today.replace(month=1, day=1), date__lte=today)

        if cd.get('date_from'):
            expenses = expenses.filter(date__gte=cd['date_from'])
        if cd.get('date_to'):
            expenses = expenses.filter(date__lte=cd['date_to'])
        if cd.get('min_amount') is not None:
            expenses = expenses.filter(amount__gte=cd['min_amount'])
        if cd.get('max_amount') is not None:
            expenses = expenses.filter(amount__lte=cd['max_amount'])

    elif request.GET:
        # Form was submitted but invalid — collect errors to display
        filter_errors = [
            str(e) for errors in filter_form.errors.values() for e in errors
        ]

    total = expenses.aggregate(total=Sum('amount_base'))['total'] or Decimal('0')
    count = expenses.count()
    average = total / count if count > 0 else Decimal('0')

    all_tags = set()
    for expense in Expense.objects.filter(user=request.user):
        all_tags.update(expense.tags.names())

    bulk_form = BulkExpenseActionForm()

    context = {
        'expenses': expenses[:100],
        'total': total,
        'count': count,
        'average': average,
        'all_tags': sorted(all_tags),
        'payment_methods': Expense.PAYMENT_METHODS,
        'filter_form': filter_form,
        'filter_errors': filter_errors,
        'bulk_form': bulk_form,
    }

    return render(request, 'expenses/expense_list.html', context)


# ===========================================================================
# Expense CRUD
# ===========================================================================
@login_required
def expense_create(request):
    if request.method == 'POST':
        form = ExpenseForm(request.POST, request.FILES)
        if form.is_valid():
            expense = form.save(commit=False)
            expense.user = request.user
            expense.save()

            # Handle tags from the comma-separated hidden input
            raw_tags = form.cleaned_data.get('tags', '')
            tag_names = [t.strip() for t in raw_tags.split(',') if t.strip()]
            if tag_names:
                expense.tags.set(*tag_names)
            else:
                expense.tags.clear()

            # Trigger OCR if a receipt was uploaded
            if expense.receipt:
                try:
                    from .tasks import process_receipt_ocr
                    process_receipt_ocr.delay(expense.pk)
                except Exception as exc:
                    logger.warning(
                        "Could not queue OCR task for expense %s: %s",
                        expense.pk, exc
                    )

            messages.success(request, '✅ Expense added successfully!')

            _check_budgets_after_expense(request.user)

            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': True,
                    'expense': {
                        'id': str(expense.id),
                        'description': expense.description,
                        'amount': float(expense.amount),
                        'currency': expense.currency,
                        'date': expense.date.isoformat(),
                        'tags': list(expense.tags.names()),
                        'status': expense.status,
                    }
                })

            if request.POST.get('save_and_new'):
                return redirect('expenses:expense_create')

            return redirect('expenses:dashboard')

            # Form invalid — fall through to re-render with errors

    else:
        form = ExpenseForm()

    # Build recent tags for the tag autocomplete
    recent_tags = set()
    for exp in Expense.objects.filter(user=request.user).prefetch_related('tags')[:50]:
        recent_tags.update(exp.tags.names())

    return render(request, 'expenses/expense_form.html', {
        'form': form,
        'recent_tags': sorted(recent_tags)[:20],
        'today': date.today(),
    })


@login_required
def expense_edit(request, pk):
    expense = get_object_or_404(Expense, pk=pk, user=request.user)

    if request.method == 'POST':
        form = ExpenseForm(request.POST, request.FILES, instance=expense)
        if form.is_valid():
            updated = form.save()

            # Re-queue OCR if a new receipt was uploaded
            if 'receipt' in request.FILES and updated.receipt:
                updated.ocr_processed = False
                updated.save(update_fields=['ocr_processed'])
                try:
                    from .tasks import process_receipt_ocr
                    process_receipt_ocr.delay(updated.pk)
                except Exception as exc:
                    logger.warning("Could not queue OCR task for expense %s: %s", updated.pk, exc)

            messages.success(request, '✅ Expense updated successfully!')

            # Re-check budgets in case this edit pushed one over threshold
            _check_budgets_after_expense(request.user)

            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': True})

            return redirect('expenses:expense_list')
    else:
        form = ExpenseForm(instance=expense)

    return render(request, 'expenses/expense_form.html', {'form': form, 'expense': expense})


@login_required
@require_http_methods(["DELETE", "POST"])
def expense_delete(request, pk):
    expense = get_object_or_404(Expense, pk=pk, user=request.user)
    expense.delete()

    messages.success(request, '🗑️ Expense deleted successfully!')

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'success': True})

    return redirect('expenses:expense_list')


@login_required
def expense_detail(request, pk):
    expense = get_object_or_404(Expense, pk=pk, user=request.user)

    related_expenses = []
    if expense.tags.exists():
        related_expenses = Expense.objects.filter(
            user=request.user,
            tags__name__in=list(expense.tags.names())
        ).exclude(id=expense.id).distinct()[:5]

    approval_history = expense.approvals.select_related('actor').order_by('created_at')

    return render(request, 'expenses/expense_detail.html', {
        'expense': expense,
        'related_expenses': related_expenses,
        'approval_history': approval_history,
    })


# ===========================================================================
# Bulk actions
# ===========================================================================

@login_required
@require_POST
def expense_bulk_action(request):
    """
    Handle bulk actions on a set of expenses.

    Expected POST body (standard form or JSON):
        action       — one of the BULK_ACTIONS choices
        expense_ids  — comma-separated IDs
        tag_name     — only for action=tag
        comment      — only for action=reject
    """
    form = BulkExpenseActionForm(request.POST)
    if not form.is_valid():
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'errors': form.errors}, status=400)
        messages.error(request, 'Invalid bulk action form.')
        return redirect('expenses:expense_list')

    action = form.cleaned_data['action']
    ids = form.cleaned_data['expense_ids']
    comment = form.cleaned_data.get('comment', '')

    # Scope to this user's own expenses (approvers can act on any — handled below)
    if action in ('approve', 'reject') and request.user.has_perm('expenses.approve_expense'):
        expenses = Expense.objects.filter(pk__in=ids)
    else:
        expenses = Expense.objects.filter(pk__in=ids, user=request.user)

    if action == 'submit':
        count = 0
        for exp in expenses.filter(status__in=('draft', 'resubmit')):
            ExpenseApproval.record(exp, request.user, 'submitted', comment)
            count += 1
        messages.success(request, f'📤 {count} expense(s) submitted for approval.')

    elif action == 'approve':
        if not request.user.has_perm('expenses.approve_expense'):
            messages.error(request, 'You do not have permission to approve expenses.')
            return redirect('expenses:expense_list')
        count = 0
        for exp in expenses.filter(status__in=('submitted', 'under_review')):
            ExpenseApproval.record(exp, request.user, 'approved', comment)
            count += 1
        messages.success(request, f'✅ {count} expense(s) approved.')

    elif action == 'reject':
        if not request.user.has_perm('expenses.approve_expense'):
            messages.error(request, 'You do not have permission to reject expenses.')
            return redirect('expenses:expense_list')
        count = 0
        for exp in expenses.filter(status__in=('submitted', 'under_review')):
            ExpenseApproval.record(exp, request.user, 'rejected', comment)
            count += 1
        messages.success(request, f'❌ {count} expense(s) rejected.')

    elif action == 'tag':
        tag_name = form.cleaned_data.get('tag_name', '').strip()
        count = 0
        for exp in expenses:
            exp.tags.add(tag_name)
            count += 1
        messages.success(request, f'🏷️ Tag "{tag_name}" added to {count} expense(s).')

    elif action == 'export_csv':
        return _export_expenses_csv(expenses)

    elif action == 'export_pdf':
        return _export_expenses_pdf(expenses)

    elif action == 'delete':
        count = expenses.count()
        expenses.delete()
        messages.success(request, f'🗑️ {count} expense(s) deleted.')

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'success': True})

    return redirect('expenses:expense_list')


# ===========================================================================
# Export views
# ===========================================================================

# ===========================================================================
# Export views
# ===========================================================================

@login_required
def export_expenses_csv(request):
    """Standalone CSV export for filtered expenses."""
    expenses = _get_filtered_expenses(request)
    return _export_expenses_csv(expenses)


def _export_expenses_csv(expenses):
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="expenses.csv"'

    writer = csv.writer(response)
    writer.writerow([
        'ID', 'Date', 'Description', 'Vendor',
        'Amount', 'Currency', 'Amount (Base)', 'Exchange Rate',
        'Payment Method', 'Tags', 'Status',
        'Is Recurring', 'Is Important', 'Notes', 'Created At',
    ])

    for exp in expenses.prefetch_related('tags'):
        writer.writerow([
            exp.pk,
            exp.date.isoformat(),
            exp.description,
            exp.vendor,
            exp.amount,
            exp.currency,
            exp.amount_base,
            exp.exchange_rate,
            exp.get_payment_method_display() if exp.payment_method else '',
            ', '.join(exp.tags.names()),
            exp.get_status_display(),
            exp.is_recurring,
            exp.is_important,
            exp.notes,
            exp.created_at.isoformat(),
        ])

    return response


@login_required
def export_expenses_pdf(request):
    """Standalone PDF export for filtered expenses."""
    expenses = _get_filtered_expenses(request)  # Fixed: use _get_filtered_expenses
    return _export_expenses_pdf(expenses, request)  # Pass request


def _export_expenses_pdf(expenses, request=None):
    """
    Generate a PDF via WeasyPrint.
    Falls back to CSV export with a warning header if WeasyPrint is not installed.
    """
    try:
        from weasyprint import HTML
        from django.template.loader import render_to_string

        expenses_list = list(expenses.prefetch_related('tags'))
        total = sum(e.amount_base for e in expenses_list)

        # Get user from request if available
        user = request.user if request else None

        html_string = render_to_string('expenses/exports/expenses_pdf.html', {
            'expenses': expenses_list,
            'total': total,
            'generated_at': timezone.now(),
            'user': user,  # Add user to context
        })

        pdf_file = HTML(string=html_string).write_pdf()
        response = HttpResponse(pdf_file, content_type='application/pdf')
        response['Content-Disposition'] = 'attachment; filename="expenses.pdf"'
        return response

    except ImportError:
        logger.warning("WeasyPrint not installed — falling back to CSV export")
        response = _export_expenses_csv(expenses)
        response['X-Export-Fallback'] = 'WeasyPrint not installed; exported as CSV instead'
        return response


def _get_filtered_expenses(request):
    """Apply GET filters from the request to the user's expenses queryset."""
    expenses = Expense.objects.filter(user=request.user).prefetch_related('tags')
    form = ExpenseFilterForm(request.GET or None)
    if form.is_valid():
        cd = form.cleaned_data
        if cd.get('date_from'):
            expenses = expenses.filter(date__gte=cd['date_from'])
        if cd.get('date_to'):
            expenses = expenses.filter(date__lte=cd['date_to'])
        if cd.get('currency'):
            expenses = expenses.filter(currency=cd['currency'])
        if cd.get('status'):
            expenses = expenses.filter(status=cd['status'])
        if cd.get('payment_method'):
            expenses = expenses.filter(payment_method=cd['payment_method'])
    return expenses


# ===========================================================================
# Approval workflow views
# ===========================================================================

@login_required
@require_POST
def expense_submit(request, pk):
    """Submit a draft expense for approval."""
    expense = get_object_or_404(Expense, pk=pk, user=request.user)

    if not expense.can_be_submitted():
        messages.error(request, f'This expense cannot be submitted (current status: {expense.status}).')
        return redirect('expenses:expense_detail', pk=pk)

    comment = request.POST.get('comment', '')
    ExpenseApproval.record(expense, request.user, 'submitted', comment)
    messages.success(request, '📤 Expense submitted for approval.')
    return redirect('expenses:expense_detail', pk=pk)


@login_required
@permission_required('expenses.approve_expense', raise_exception=True)
@require_POST
def expense_approve(request, pk):
    """Approve a submitted expense."""
    expense = get_object_or_404(Expense, pk=pk)

    if not expense.can_be_approved():
        messages.error(request, f'This expense cannot be approved (current status: {expense.status}).')
        return redirect('expenses:expense_detail', pk=pk)

    comment = request.POST.get('comment', '')
    ExpenseApproval.record(expense, request.user, 'approved', comment)
    messages.success(request, '✅ Expense approved.')

    # Notify the submitter by email
    try:
        from .tasks import send_expense_notification_email
        send_expense_notification_email.delay(
            expense.pk, 'approved', request.user.pk, comment
        )
    except Exception as exc:
        logger.warning("Could not queue approval email for expense %s: %s", expense.pk, exc)

    return redirect('expenses:expense_detail', pk=pk)


@login_required
@permission_required('expenses.approve_expense', raise_exception=True)
@require_POST
def expense_reject(request, pk):
    """Reject a submitted expense."""
    expense = get_object_or_404(Expense, pk=pk)

    if not expense.can_be_rejected():
        messages.error(request, f'This expense cannot be rejected (current status: {expense.status}).')
        return redirect('expenses:expense_detail', pk=pk)

    comment = request.POST.get('comment', '').strip()
    if not comment:
        messages.error(request, 'A rejection reason is required.')
        return redirect('expenses:expense_detail', pk=pk)

    ExpenseApproval.record(expense, request.user, 'rejected', comment)
    messages.success(request, '❌ Expense rejected.')

    # Notify the submitter by email
    try:
        from .tasks import send_expense_notification_email
        send_expense_notification_email.delay(
            expense.pk, 'rejected', request.user.pk, comment
        )
    except Exception as exc:
        logger.warning("Could not queue rejection email for expense %s: %s", expense.pk, exc)

    return redirect('expenses:expense_detail', pk=pk)


@login_required
@permission_required('expenses.approve_expense', raise_exception=True)
def approval_dashboard(request):
    """Dashboard for approvers showing pending expenses."""
    pending = Expense.objects.filter(
        status__in=('submitted', 'under_review')
    ).select_related('user').prefetch_related('tags').order_by('updated_at')

    recent_actions = ExpenseApproval.objects.select_related(
        'expense', 'actor'
    ).order_by('-created_at')[:20]

    today = timezone.now().date()
    approved_today = ExpenseApproval.objects.filter(
        action='approved',
        created_at__date=today
    ).count()
    rejected_today = ExpenseApproval.objects.filter(
        action='rejected',
        created_at__date=today
    ).count()

    from django.db.models import Sum as _Sum
    pending_total = pending.aggregate(t=_Sum('amount_base'))['t'] or 0

    return render(request, 'expenses/approval_dashboard.html', {
        'pending_expenses': pending,          # template expects this name
        'pending': pending,
        'pending_count': pending.count(),
        'recent_actions': recent_actions,
        'approved_today': approved_today,
        'rejected_today': rejected_today,
        'pending_total': pending_total,
    })


# ===========================================================================
# Budget views (unchanged API, minor enhancements)
# ===========================================================================

@login_required
def budget_list(request):
    budgets = Budget.objects.filter(user=request.user)
    budget_data = []
    for budget in budgets:
        spending   = budget.get_current_spending()
        percentage = budget.get_percentage_used()
        budget_data.append({
            'budget':     budget,
            'spent':      spending,          # template uses item.spent
            'spending':   spending,          # kept for backward compat
            'percentage': round(float(percentage), 1),
            'remaining':  budget.get_remaining(),
            'status':     budget.get_status_color(),
            'is_over':    budget.is_over_threshold(),
        })
    # template iterates 'budgets', not 'budget_data'
    return render(request, 'expenses/budget_list.html', {
        'budgets':     budget_data,
        'budget_data': budget_data,
    })


@login_required
def budget_create(request):
    if request.method == 'POST':
        form = BudgetForm(request.POST)
        if form.is_valid():
            budget = form.save(commit=False)
            budget.user = request.user
            budget.save()
            form.save_m2m()
            messages.success(request, '✅ Budget created successfully!')
            # Fire an immediate alert check in case the budget is already breached
            _trigger_budget_alert_if_needed(budget)
            return redirect('expenses:budget_list')
    else:
        form = BudgetForm()
    return render(request, 'expenses/budget_form.html', {'form': form})


@login_required
def budget_edit(request, pk):
    budget = get_object_or_404(Budget, pk=pk, user=request.user)
    if request.method == 'POST':
        form = BudgetForm(request.POST, instance=budget)
        if form.is_valid():
            updated_budget = form.save()
            messages.success(request, '✅ Budget updated successfully!')
            _trigger_budget_alert_if_needed(updated_budget)
            return redirect('expenses:budget_list')
    else:
        form = BudgetForm(instance=budget)
    return render(request, 'expenses/budget_form.html', {'form': form, 'budget': budget})


@login_required
def budget_delete(request, pk):
    budget = get_object_or_404(Budget, pk=pk, user=request.user)
    budget.delete()
    messages.success(request, '🗑️ Budget deleted successfully!')
    return redirect('expenses:budget_list')


# ===========================================================================
# Analytics & Reports (carry-over + minor base-currency fix)
# ===========================================================================

@login_required
def analytics(request):
    user = request.user
    period = request.GET.get('period', '30')
    try:
        days = int(period)
    except Exception:
        days = 30

    end_date = timezone.now().date()
    start_date = end_date - timedelta(days=days)

    expenses = Expense.objects.filter(user=user, date__gte=start_date, date__lte=end_date)

    daily_data = expenses.values('date').annotate(
        total=Sum('amount_base'), count=Count('id')
    ).order_by('date')

    tag_analysis = {}
    for expense in expenses.prefetch_related('tags'):
        for tag in expense.tags.all():
            if tag.name not in tag_analysis:
                tag_analysis[tag.name] = {'total': Decimal('0'), 'count': 0, 'avg': Decimal('0')}
            tag_analysis[tag.name]['total'] += expense.amount_base
            tag_analysis[tag.name]['count'] += 1

    for data in tag_analysis.values():
        if data['count'] > 0:
            data['avg'] = data['total'] / data['count']

    top_tags = sorted(tag_analysis.items(), key=lambda x: x[1]['total'], reverse=True)[:15]

    payment_analysis = expenses.values('payment_method').annotate(
        total=Sum('amount_base'), count=Count('id')
    ).order_by('-total')

    total = expenses.aggregate(total=Sum('amount_base'))['total'] or Decimal('0')
    count = expenses.count()
    average = total / count if count > 0 else Decimal('0')

    prev_start = start_date - timedelta(days=days)
    prev_end = start_date - timedelta(days=1)
    prev_total = Expense.objects.filter(
        user=user, date__gte=prev_start, date__lte=prev_end
    ).aggregate(total=Sum('amount_base'))['total'] or Decimal('0')

    trend_percentage = float(
        ((total - prev_total) / prev_total * 100) if prev_total > 0 else (100 if total > 0 else 0)
    )

    context = {
        'period_days': days,
        'start_date': start_date,
        'end_date': end_date,
        'total': total,
        'count': count,
        'average': average,
        'trend_percentage': round(trend_percentage, 1),
        'trend_direction': 'up' if trend_percentage > 0 else 'down',
        'daily_data': json.dumps([{
            'date': item['date'].isoformat(),
            'total': float(item['total']),
            'count': item['count'],
        } for item in daily_data]),
        'tag_data': json.dumps([{
            'name': name,
            'total': float(data['total']),
            'count': data['count'],
            'avg': float(data['avg']),
        } for name, data in top_tags]),
        'payment_data': json.dumps([{
            'method': item['payment_method'] or 'Not Specified',
            'total': float(item['total']),
            'count': item['count'],
        } for item in payment_analysis]),
    }

    return render(request, 'expenses/analytics.html', context)


@login_required
def reports_dashboard(request):
    user = request.user
    period = request.GET.get('period', '30')
    try:
        days = int(period)
    except Exception:
        days = 30

    end_date = timezone.now().date()
    start_date = end_date - timedelta(days=days)

    expenses = Expense.objects.filter(user=user, date__gte=start_date, date__lte=end_date)

    total = expenses.aggregate(total=Sum('amount_base'))['total'] or Decimal('0')
    count = expenses.count()
    average = total / count if count > 0 else Decimal('0')

    tag_analysis = {}
    for expense in expenses.prefetch_related('tags'):
        for tag in expense.tags.all():
            if tag.name not in tag_analysis:
                tag_analysis[tag.name] = {'total': Decimal('0'), 'count': 0}
            tag_analysis[tag.name]['total'] += expense.amount_base
            tag_analysis[tag.name]['count'] += 1

    top_tags = sorted(tag_analysis.items(), key=lambda x: x[1]['total'], reverse=True)[:10]

    payment_analysis = expenses.values('payment_method').annotate(
        total=Sum('amount_base'), count=Count('id')
    ).order_by('-total')

    current_month_start = end_date.replace(day=1)
    current_month_total = expenses.filter(
        date__gte=current_month_start
    ).aggregate(total=Sum('amount_base'))['total'] or Decimal('0')

    if current_month_start.month == 1:
        prev_month_start = current_month_start.replace(year=current_month_start.year - 1, month=12)
    else:
        prev_month_start = current_month_start.replace(month=current_month_start.month - 1)

    prev_month_end = current_month_start - timedelta(days=1)
    prev_month_total = Expense.objects.filter(
        user=user, date__gte=prev_month_start, date__lte=prev_month_end
    ).aggregate(total=Sum('amount_base'))['total'] or Decimal('0')

    if prev_month_total > 0:
        month_change = float((current_month_total - prev_month_total) / prev_month_total * 100)
    else:
        month_change = 100.0 if current_month_total > 0 else 0.0

    budgets = Budget.objects.filter(user=user, is_active=True)
    budget_status = [{
        'budget': b,
        'percentage': round(float(b.get_percentage_used()), 1),
        'spent': b.get_current_spending(),
        'remaining': b.get_remaining(),
        'status': b.get_status_color(),
    } for b in budgets]

    context = {
        'period_days': days,
        'start_date': start_date,
        'end_date': end_date,
        'total': total,
        'count': count,
        'average': average,
        'top_tags': top_tags,
        'payment_analysis': payment_analysis,
        'current_month_total': current_month_total,
        'prev_month_total': prev_month_total,
        'month_change': round(month_change, 1),
        'month_change_direction': 'up' if month_change > 0 else 'down',
        'budget_status': budget_status,
    }

    return render(request, 'expenses/reports_dashboard.html', context)


# ===========================================================================
# API endpoints
# ===========================================================================

@login_required
def api_tag_suggestions(request):
    query = request.GET.get('q', '').lower()
    tag_counts = {}
    for expense in Expense.objects.filter(user=request.user):
        for tag in expense.tags.all():
            tag_counts[tag.name] = tag_counts.get(tag.name, 0) + 1

    if query:
        suggestions = [t for t in tag_counts if query in t.lower()]
    else:
        suggestions = sorted(tag_counts, key=lambda t: tag_counts[t], reverse=True)[:20]

    return JsonResponse({'tags': suggestions[:10]})


@login_required
def api_quick_stats(request):
    today = timezone.now().date()
    today_total = Expense.objects.filter(
        user=request.user, date=today
    ).aggregate(total=Sum('amount_base'))['total'] or 0

    month_start = today.replace(day=1)
    month_total = Expense.objects.filter(
        user=request.user, date__gte=month_start, date__lte=today
    ).aggregate(total=Sum('amount_base'))['total'] or 0

    return JsonResponse({'today': float(today_total), 'month': float(month_total)})


@login_required
def api_budget_status(request):
    budgets = Budget.objects.filter(user=request.user, is_active=True)
    return JsonResponse({'budgets': [{
        'id': b.id,
        'name': b.name,
        'amount': float(b.amount),
        'currency': b.currency,
        'spent': float(b.get_current_spending()),
        'remaining': float(b.get_remaining()),
        'percentage': round(float(b.get_percentage_used()), 1),
        'status': b.get_status_color(),
        'over_threshold': b.is_over_threshold(),
    } for b in budgets]})