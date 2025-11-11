from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from django.db.models import Sum, Q, Count, Avg
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.views.decorators.http import require_http_methods
from django.db import transaction

from .models import Expense, ExpenseCategory, ExpenseAttachment, ExpenseComment
from .forms import (
    ExpenseForm, ExpenseApprovalForm, ExpensePaymentForm,
    ExpenseFilterForm, ExpenseCommentForm, BulkExpenseActionForm
)
from .utils import (
    get_expense_statistics, get_budget_analysis,
    validate_expense_approval, export_expenses_to_excel
)
from accounts.utils import log_action


@login_required
def expense_list(request):
    """List expenses with filtering and pagination"""
    expenses = Expense.objects.select_related(
        'category', 'created_by', 'store', 'approved_by'
    ).filter(created_by=request.user)

    # Apply filters
    filter_form = ExpenseFilterForm(request.GET)
    if filter_form.is_valid():
        if filter_form.cleaned_data.get('status'):
            expenses = expenses.filter(status=filter_form.cleaned_data['status'])
        if filter_form.cleaned_data.get('category'):
            expenses = expenses.filter(category=filter_form.cleaned_data['category'])
        if filter_form.cleaned_data.get('date_from'):
            expenses = expenses.filter(expense_date__gte=filter_form.cleaned_data['date_from'])
        if filter_form.cleaned_data.get('date_to'):
            expenses = expenses.filter(expense_date__lte=filter_form.cleaned_data['date_to'])
        if filter_form.cleaned_data.get('search'):
            search = filter_form.cleaned_data['search']
            expenses = expenses.filter(
                Q(expense_number__icontains=search) |
                Q(title__icontains=search) |
                Q(description__icontains=search) |
                Q(vendor_name__icontains=search)
            )

    # Pagination
    paginator = Paginator(expenses.order_by('-expense_date'), 20)
    page = request.GET.get('page')

    try:
        expenses_page = paginator.page(page)
    except PageNotAnInteger:
        expenses_page = paginator.page(1)
    except EmptyPage:
        expenses_page = paginator.page(paginator.num_pages)

    # Stats
    stats = {
        'total': expenses.count(),
        'draft': expenses.filter(status='DRAFT').count(),
        'submitted': expenses.filter(status='SUBMITTED').count(),
        'approved': expenses.filter(status='APPROVED').count(),
        'rejected': expenses.filter(status='REJECTED').count(),
        'paid': expenses.filter(status='PAID').count(),
        'total_amount': expenses.aggregate(Sum('amount'))['amount__sum'] or Decimal('0')
    }

    context = {
        'expenses': expenses_page,
        'categories': ExpenseCategory.objects.filter(is_active=True),
        'stats': stats,
        'filter_form': filter_form,
        'filters': request.GET.dict()
    }

    return render(request, 'expenses/expense_list.html', context)


@login_required
@transaction.atomic
def expense_create(request):
    """Create new expense with proper error handling"""
    if request.method == 'POST':
        form = ExpenseForm(request.POST, request.FILES, user=request.user)
        if form.is_valid():
            expense = form.save(commit=False)
            expense.created_by = request.user

            # Set store if user has one
            if hasattr(request.user, 'store') and request.user.store:
                expense.store = request.user.store

            # Determine status based on action
            action = request.POST.get('action', 'draft')
            if action == 'submit':
                expense.status = 'SUBMITTED'
                expense.submitted_at = timezone.now()

                # Check if auto-approval applies
                if expense.category.approval_threshold and \
                        expense.amount < expense.category.approval_threshold:
                    expense.status = 'APPROVED'
                    expense.approved_by = request.user
                    expense.approved_at = timezone.now()
            else:
                expense.status = 'DRAFT'

            expense.save()

            # Handle multiple file attachments
            files = request.FILES.getlist('attachments')
            for file in files:
                ExpenseAttachment.objects.create(
                    expense=expense,
                    file=file,
                    uploaded_by=request.user
                )

            # Log action
            log_action(
                request,
                'expense_created',
                f'Created expense: {expense.expense_number}',
                content_object=expense
            )

            if action == 'submit':
                messages.success(
                    request,
                    f'Expense {expense.expense_number} created and submitted successfully!'
                )
            else:
                messages.success(
                    request,
                    f'Expense {expense.expense_number} saved as draft!'
                )

            return redirect('expenses:expense_detail', pk=expense.pk)
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        # Pre-fill expense date with today
        initial = {'expense_date': timezone.now().date()}
        form = ExpenseForm(initial=initial, user=request.user)

    context = {
        'form': form,
        'categories': ExpenseCategory.objects.filter(is_active=True).order_by('sort_order', 'name')
    }

    return render(request, 'expenses/expense_form.html', context)


@login_required
def expense_detail(request, pk):
    """View expense details with permission checks"""
    expense = get_object_or_404(
        Expense.objects.select_related(
            'category', 'created_by', 'approved_by', 'paid_by', 'store'
        ).prefetch_related('attachments', 'comments'),
        pk=pk
    )

    # Check permissions
    can_view = (
            expense.created_by == request.user or
            request.user.has_perm('expenses.view_all_expenses') or
            request.user.has_perm('expenses.approve_expense')
    )

    if not can_view:
        messages.error(request, "You don't have permission to view this expense.")
        return redirect('expenses:expense_list')

    attachments = expense.attachments.all()
    comments = expense.comments.select_related('user').order_by('created_at')

    # Filter internal comments for non-approvers
    if not request.user.has_perm('expenses.approve_expense'):
        comments = comments.filter(is_internal=False)

    context = {
        'expense': expense,
        'attachments': attachments,
        'comments': comments,
        'can_approve': request.user.has_perm('expenses.approve_expense') and expense.created_by != request.user,
        'can_pay': request.user.has_perm('expenses.pay_expense'),
        'can_edit': expense.status == 'DRAFT' and expense.created_by == request.user
    }

    return render(request, 'expenses/expense_detail.html', context)


@login_required
@require_http_methods(["POST"])
def expense_edit(request, pk):
    """Edit existing expense (only drafts)"""
    expense = get_object_or_404(Expense, pk=pk, created_by=request.user)

    if expense.status != 'DRAFT':
        messages.error(request, "Only draft expenses can be edited.")
        return redirect('expenses:expense_detail', pk=pk)

    form = ExpenseForm(request.POST, request.FILES, instance=expense, user=request.user)
    if form.is_valid():
        expense = form.save()

        # Handle new attachments
        files = request.FILES.getlist('attachments')
        for file in files:
            ExpenseAttachment.objects.create(
                expense=expense,
                file=file,
                uploaded_by=request.user
            )

        log_action(request, 'expense_updated', f'Updated expense: {expense.expense_number}', content_object=expense)
        messages.success(request, 'Expense updated successfully!')
        return redirect('expenses:expense_detail', pk=pk)

    return render(request, 'expenses/expense_form.html', {'form': form, 'expense': expense})


@login_required
@require_http_methods(["POST"])
def expense_submit(request, pk):
    """Submit expense for approval with validation"""
    expense = get_object_or_404(Expense, pk=pk, created_by=request.user)

    if expense.status != 'DRAFT':
        messages.error(request, "Only draft expenses can be submitted.")
        return redirect('expenses:expense_detail', pk=pk)

    # Validate required fields
    if not expense.attachments.exists() and expense.category.requires_approval:
        messages.warning(request, "Please attach receipts before submitting for approval.")
        return redirect('expenses:expense_detail', pk=pk)

    try:
        expense.submit_for_approval()

        log_action(
            request,
            'expense_submitted',
            f'Submitted expense {expense.expense_number} for approval',
            content_object=expense
        )

        messages.success(request, f'Expense {expense.expense_number} submitted for approval!')
    except ValueError as e:
        messages.error(request, str(e))

    return redirect('expenses:expense_detail', pk=pk)


@login_required
@permission_required('expenses.approve_expense', raise_exception=True)
@require_http_methods(["POST"])
def expense_approve(request, pk):
    """Approve expense with validation"""
    expense = get_object_or_404(Expense, pk=pk)

    # Validate approval
    validation = validate_expense_approval(expense, request.user)

    if validation['errors']:
        for error in validation['errors']:
            messages.error(request, error)
        return redirect('expenses:expense_detail', pk=pk)

    try:
        expense.approve(request.user)

        log_action(
            request,
            'expense_approved',
            f'Approved expense {expense.expense_number}',
            content_object=expense
        )

        messages.success(request, f'Expense {expense.expense_number} approved successfully!')

        # Send notification via WebSocket
        send_expense_update_notification(expense, 'approved')

    except ValueError as e:
        messages.error(request, str(e))

    return redirect('expenses:expense_detail', pk=pk)


@login_required
@permission_required('expenses.reject_expense', raise_exception=True)
@require_http_methods(["POST"])
def expense_reject(request, pk):
    """Reject expense with reason"""
    expense = get_object_or_404(Expense, pk=pk)

    reason = request.POST.get('reason', '').strip()

    if not reason:
        messages.error(request, 'Rejection reason is required.')
        return redirect('expenses:expense_detail', pk=pk)

    if len(reason) < 10:
        messages.error(request, 'Please provide a detailed rejection reason (at least 10 characters).')
        return redirect('expenses:expense_detail', pk=pk)

    try:
        expense.reject(request.user, reason)

        log_action(
            request,
            'expense_rejected',
            f'Rejected expense {expense.expense_number}: {reason}',
            content_object=expense
        )

        messages.success(request, f'Expense {expense.expense_number} rejected.')

        # Send notification
        send_expense_update_notification(expense, 'rejected')

    except ValueError as e:
        messages.error(request, str(e))

    return redirect('expenses:expense_detail', pk=pk)


@login_required
@permission_required('expenses.pay_expense', raise_exception=True)
@require_http_methods(["POST"])
def expense_mark_paid(request, pk):
    """Mark expense as paid"""
    expense = get_object_or_404(Expense, pk=pk)

    payment_method = request.POST.get('payment_method')
    payment_reference = request.POST.get('payment_reference', '')

    if not payment_method:
        messages.error(request, 'Payment method is required.')
        return redirect('expenses:expense_detail', pk=pk)

    try:
        expense.mark_as_paid(request.user, payment_method, payment_reference)

        log_action(
            request,
            'expense_paid',
            f'Marked expense {expense.expense_number} as paid',
            content_object=expense,
            metadata={
                'payment_method': payment_method,
                'payment_reference': payment_reference
            }
        )

        messages.success(request, f'Expense {expense.expense_number} marked as paid!')

        # Send notification
        send_expense_update_notification(expense, 'paid')

    except ValueError as e:
        messages.error(request, str(e))

    return redirect('expenses:expense_detail', pk=pk)


@login_required
def expense_dashboard(request):
    """Enhanced expense dashboard with more insights"""
    # Date range (current month by default)
    today = timezone.now().date()
    start_of_month = today.replace(day=1)

    # User's expenses
    user_expenses = Expense.objects.filter(created_by=request.user)

    # Stats for current month
    month_expenses = user_expenses.filter(
        expense_date__gte=start_of_month,
        expense_date__lte=today
    )

    stats = {
        'total_this_month': month_expenses.aggregate(Sum('amount'))['amount__sum'] or Decimal('0'),
        'pending_approval': user_expenses.filter(status='SUBMITTED').count(),
        'approved_unpaid': user_expenses.filter(status='APPROVED').count(),
        'total_paid': user_expenses.filter(status='PAID').count(),
        'rejected': user_expenses.filter(status='REJECTED').count(),
        'average_expense': month_expenses.aggregate(Avg('amount'))['amount__avg'] or Decimal('0')
    }

    # Category breakdown for current month
    category_breakdown = month_expenses.values(
        'category__name', 'category__color_code'
    ).annotate(
        total=Sum('amount'),
        count=Count('id')
    ).order_by('-total')[:5]

    # Recent expenses
    recent_expenses = user_expenses.select_related(
        'category', 'store'
    ).order_by('-created_at')[:10]

    # Pending approvals (if user can approve)
    pending_approvals = []
    if request.user.has_perm('expenses.approve_expense'):
        pending_approvals = Expense.objects.filter(
            status='SUBMITTED'
        ).exclude(
            created_by=request.user
        ).select_related('created_by', 'category').order_by('-submitted_at')[:10]

    # Budget analysis
    budget_analysis = []
    if request.user.has_perm('expenses.view_all_expenses'):
        budget_analysis = get_budget_analysis()[:5]

    context = {
        'stats': stats,
        'category_breakdown': category_breakdown,
        'recent_expenses': recent_expenses,
        'pending_approvals': pending_approvals,
        'budget_analysis': budget_analysis
    }

    return render(request, 'expenses/dashboard.html', context)


@login_required
@require_http_methods(["POST"])
def expense_add_comment(request, pk):
    """Add comment to expense"""
    expense = get_object_or_404(Expense, pk=pk)

    # Check if user can view this expense
    can_view = (
            expense.created_by == request.user or
            request.user.has_perm('expenses.view_all_expenses') or
            request.user.has_perm('expenses.approve_expense')
    )

    if not can_view:
        messages.error(request, "You don't have permission to comment on this expense.")
        return redirect('expenses:expense_list')

    comment_text = request.POST.get('comment', '').strip()
    is_internal = request.POST.get('is_internal') == 'on'

    if comment_text:
        # Only approvers can make internal comments
        if is_internal and not request.user.has_perm('expenses.approve_expense'):
            is_internal = False

        comment = ExpenseComment.objects.create(
            expense=expense,
            user=request.user,
            comment=comment_text,
            is_internal=is_internal
        )

        messages.success(request, 'Comment added successfully!')

        # Send real-time notification
        send_comment_notification(expense, comment)
    else:
        messages.error(request, 'Comment cannot be empty.')

    return redirect('expenses:expense_detail', pk=pk)


@login_required
@require_http_methods(["POST"])
def expense_delete_attachment(request, pk, attachment_id):
    """Delete an attachment"""
    expense = get_object_or_404(Expense, pk=pk, created_by=request.user)
    attachment = get_object_or_404(ExpenseAttachment, pk=attachment_id, expense=expense)

    if expense.status != 'DRAFT':
        messages.error(request, "Cannot delete attachments from submitted expenses.")
        return redirect('expenses:expense_detail', pk=pk)

    attachment.file.delete()
    attachment.delete()

    messages.success(request, 'Attachment deleted successfully.')
    return redirect('expenses:expense_detail', pk=pk)


@login_required
@permission_required('expenses.view_all_expenses', raise_exception=True)
def expense_reports(request):
    """View expense reports and analytics"""
    from .utils import get_expense_statistics, get_expense_insights

    # Get date range from request
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')

    # Get statistics
    stats = get_expense_statistics(
        user=None if request.user.has_perm('expenses.view_all_expenses') else request.user,
        date_from=date_from,
        date_to=date_to
    )

    # Get insights
    insights = get_expense_insights(
        user=None if request.user.has_perm('expenses.view_all_expenses') else request.user
    )

    # Budget analysis
    budget_analysis = get_budget_analysis()

    context = {
        'stats': stats,
        'insights': insights,
        'budget_analysis': budget_analysis,
        'date_from': date_from,
        'date_to': date_to
    }

    return render(request, 'expenses/reports.html', context)


@login_required
def expense_export(request):
    """Export expenses to Excel"""
    from .tasks import export_expenses_to_csv

    filters = request.GET.dict()

    # Queue export task
    export_expenses_to_csv.delay(request.user.id, filters)

    messages.success(request, 'Export has been queued. You will receive a notification when it\'s ready.')
    return redirect('expenses:expense_list')


# Helper functions for WebSocket notifications
def send_expense_update_notification(expense, update_type):
    """Send real-time update via WebSocket"""
    from channels.layers import get_channel_layer
    from asgiref.sync import async_to_sync

    channel_layer = get_channel_layer()

    # Notify expense creator
    async_to_sync(channel_layer.group_send)(
        f'expense_user_{expense.created_by.id}',
        {
            'type': 'expense_update',
            'expense_id': expense.id,
            'expense_number': expense.expense_number,
            'status': expense.status,
            'message': f'Your expense has been {update_type}',
            'timestamp': timezone.now().isoformat()
        }
    )

    # Notify approvers if submitted
    if update_type == 'submitted':
        async_to_sync(channel_layer.group_send)(
            'expense_approvers',
            {
                'type': 'expense_update',
                'expense_id': expense.id,
                'expense_number': expense.expense_number,
                'status': expense.status,
                'message': f'New expense submitted by {expense.created_by.get_full_name()}',
                'timestamp': timezone.now().isoformat()
            }
        )


def send_comment_notification(expense, comment):
    """Send notification about new comment"""
    from channels.layers import get_channel_layer
    from asgiref.sync import async_to_sync

    channel_layer = get_channel_layer()

    async_to_sync(channel_layer.group_send)(
        f'expense_user_{expense.created_by.id}',
        {
            'type': 'expense_comment',
            'expense_id': expense.id,
            'comment': comment.comment[:100],
            'user': comment.user.get_full_name(),
            'timestamp': timezone.now().isoformat()
        }
    )