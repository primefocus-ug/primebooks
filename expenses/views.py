from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib import messages
from django.http import JsonResponse, HttpResponse, FileResponse
from django.db.models import Sum, Q, Count, Avg, F, DecimalField, Case, When, Value
from django.db.models.functions import Coalesce, TruncMonth
from django.utils import timezone
from datetime import timedelta, datetime
from decimal import Decimal
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.views.decorators.http import require_http_methods
from django.db import transaction
from django.contrib.auth.mixins import PermissionRequiredMixin, LoginRequiredMixin
from django.views.generic import ListView, CreateView, UpdateView, DeleteView, DetailView
from django.urls import reverse_lazy
from decimal import InvalidOperation
from django.core.exceptions import PermissionDenied
import io
from reportlab.lib.pagesizes import letter, A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT

from .models import Expense, ExpenseCategory, ExpenseAttachment, ExpenseComment
from .forms import (
    ExpenseForm, ExpenseApprovalForm, ExpensePaymentForm,
    ExpenseFilterForm, ExpenseCommentForm, BulkExpenseActionForm
)
from .utils import (
    get_expense_statistics, get_budget_analysis,
    validate_expense_approval, export_expenses_to_excel,
    get_expense_insights, generate_expense_report_pdf
)
from .permissions import (
    expense_owner_or_approver_required,
    can_modify_expense, can_approve_expense, can_pay_expense
)
from accounts.utils import log_action


# ============================================================================
# EXPENSE LIST & DASHBOARD VIEWS
# ============================================================================

@login_required
def expense_list(request):
    """List expenses with advanced filtering and pagination"""
    # Base queryset with optimized select_related
    expenses = Expense.objects.select_related(
        'category', 'created_by', 'store', 'approved_by', 'paid_by'
    ).prefetch_related('attachments')

    # Filter by user unless they have view_all permission
    if not request.user.has_perm('expenses.view_all_expenses'):
        expenses = expenses.filter(created_by=request.user)

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

        if filter_form.cleaned_data.get('min_amount'):
            expenses = expenses.filter(amount__gte=filter_form.cleaned_data['min_amount'])

        if filter_form.cleaned_data.get('max_amount'):
            expenses = expenses.filter(amount__lte=filter_form.cleaned_data['max_amount'])

        if filter_form.cleaned_data.get('store'):
            expenses = expenses.filter(store=filter_form.cleaned_data['store'])

        if filter_form.cleaned_data.get('search'):
            search = filter_form.cleaned_data['search']
            expenses = expenses.filter(
                Q(expense_number__icontains=search) |
                Q(title__icontains=search) |
                Q(description__icontains=search) |
                Q(vendor_name__icontains=search) |
                Q(reference_number__icontains=search)
            )

        # Additional filters
        if filter_form.cleaned_data.get('is_reimbursable') is not None:
            expenses = expenses.filter(is_reimbursable=filter_form.cleaned_data['is_reimbursable'])

        if filter_form.cleaned_data.get('is_overdue'):
            expenses = expenses.filter(
                status='APPROVED',
                due_date__lt=timezone.now().date()
            )

    # Sorting
    sort_by = request.GET.get('sort', '-expense_date')
    valid_sorts = [
        'expense_date', '-expense_date',
        'amount', '-amount',
        'status', '-status',
        'created_at', '-created_at'
    ]
    if sort_by in valid_sorts:
        expenses = expenses.order_by(sort_by)
    else:
        expenses = expenses.order_by('-expense_date', '-created_at')

    # Pagination
    paginator = Paginator(expenses, 25)
    page = request.GET.get('page')

    try:
        expenses_page = paginator.page(page)
    except PageNotAnInteger:
        expenses_page = paginator.page(1)
    except EmptyPage:
        expenses_page = paginator.page(paginator.num_pages)

    # Calculate statistics
    stats = {
        'total': expenses.count(),
        'draft': expenses.filter(status='DRAFT').count(),
        'submitted': expenses.filter(status='SUBMITTED').count(),
        'approved': expenses.filter(status='APPROVED').count(),
        'rejected': expenses.filter(status='REJECTED').count(),
        'paid': expenses.filter(status='PAID').count(),
        'cancelled': expenses.filter(status='CANCELLED').count(),
        'total_amount': expenses.aggregate(Sum('amount'))['amount__sum'] or Decimal('0'),
        'approved_amount': expenses.filter(
            status__in=['APPROVED', 'PAID']
        ).aggregate(Sum('amount'))['amount__sum'] or Decimal('0'),
    }

    context = {
        'expenses': expenses_page,
        'categories': ExpenseCategory.objects.filter(is_active=True),
        'stats': stats,
        'filter_form': filter_form,
        'filters': request.GET.dict(),
        'current_sort': sort_by,
    }

    return render(request, 'expenses/expense_list.html', context)


@login_required
def expense_dashboard(request):
    """Enhanced expense dashboard with comprehensive insights"""
    # Date ranges
    today = timezone.now().date()
    start_of_month = today.replace(day=1)
    start_of_last_month = (start_of_month - timedelta(days=1)).replace(day=1)
    start_of_year = today.replace(month=1, day=1)

    # Base queryset
    if request.user.has_perm('expenses.view_all_expenses'):
        all_expenses = Expense.objects.all()
    else:
        all_expenses = Expense.objects.filter(created_by=request.user)

    user_expenses = Expense.objects.filter(created_by=request.user)

    # Current month expenses
    month_expenses = user_expenses.filter(
        expense_date__gte=start_of_month,
        expense_date__lte=today
    )

    # Last month expenses for comparison
    last_month_expenses = user_expenses.filter(
        expense_date__gte=start_of_last_month,
        expense_date__lt=start_of_month
    )

    # Year-to-date expenses
    ytd_expenses = user_expenses.filter(
        expense_date__gte=start_of_year,
        expense_date__lte=today
    )

    # Current month statistics
    current_month_total = month_expenses.aggregate(Sum('amount'))['amount__sum'] or Decimal('0')
    last_month_total = last_month_expenses.aggregate(Sum('amount'))['amount__sum'] or Decimal('0')

    # Calculate percentage change
    if last_month_total > 0:
        month_change = ((current_month_total - last_month_total) / last_month_total) * 100
    else:
        month_change = 100 if current_month_total > 0 else 0

    # Main statistics
    stats = {
        'total_this_month': current_month_total,
        'total_last_month': last_month_total,
        'month_change': month_change,
        'month_change_positive': month_change >= 0,

        'ytd_total': ytd_expenses.aggregate(Sum('amount'))['amount__sum'] or Decimal('0'),
        'ytd_count': ytd_expenses.count(),

        'pending_approval': user_expenses.filter(status='SUBMITTED').count(),
        'approved_unpaid': user_expenses.filter(status='APPROVED').count(),
        'total_paid': user_expenses.filter(status='PAID').count(),
        'rejected': user_expenses.filter(status='REJECTED').count(),

        'average_expense': month_expenses.aggregate(Avg('amount'))['amount__avg'] or Decimal('0'),

        # Reimbursable expenses
        'reimbursable_pending': user_expenses.filter(
            is_reimbursable=True,
            status__in=['SUBMITTED', 'APPROVED']
        ).aggregate(Sum('amount'))['amount__sum'] or Decimal('0'),

        # Overdue payments
        'overdue_count': user_expenses.filter(
            status='APPROVED',
            due_date__lt=today
        ).count(),
    }

    # Category breakdown for current month
    category_breakdown = month_expenses.values(
        'category__name', 'category__color_code', 'category__icon'
    ).annotate(
        total=Sum('amount'),
        count=Count('id')
    ).order_by('-total')[:8]

    # Monthly trend (last 6 months)
    six_months_ago = today - timedelta(days=180)
    monthly_trend = user_expenses.filter(
        expense_date__gte=six_months_ago
    ).annotate(
        month=TruncMonth('expense_date')
    ).values('month').annotate(
        total=Sum('amount'),
        count=Count('id')
    ).order_by('month')

    # Recent expenses
    recent_expenses = user_expenses.select_related(
        'category', 'store', 'approved_by'
    ).prefetch_related('attachments').order_by('-created_at')[:10]

    # Pending approvals (if user can approve)
    pending_approvals = []
    if request.user.has_perm('expenses.approve_expense'):
        pending_approvals = Expense.objects.filter(
            status='SUBMITTED'
        ).exclude(
            created_by=request.user
        ).select_related(
            'created_by', 'category', 'store'
        ).order_by('-submitted_at')[:10]

    # Budget analysis (if user can view all expenses)
    budget_analysis = []
    if request.user.has_perm('expenses.view_all_expenses'):
        budget_analysis = get_budget_analysis()[:5]

    # Top vendors
    top_vendors = month_expenses.values('vendor_name').annotate(
        total=Sum('amount'),
        count=Count('id')
    ).exclude(vendor_name='').order_by('-total')[:5]

    # Payment method breakdown
    payment_breakdown = user_expenses.filter(
        status='PAID',
        paid_at__gte=start_of_month
    ).values('payment_method').annotate(
        total=Sum('amount'),
        count=Count('id')
    ).order_by('-total')

    context = {
        'stats': stats,
        'category_breakdown': category_breakdown,
        'monthly_trend': monthly_trend,
        'recent_expenses': recent_expenses,
        'pending_approvals': pending_approvals,
        'budget_analysis': budget_analysis,
        'top_vendors': top_vendors,
        'payment_breakdown': payment_breakdown,
    }

    return render(request, 'expenses/dashboard.html', context)


# ============================================================================
# EXPENSE CRUD VIEWS
# ============================================================================

@login_required
@transaction.atomic
def expense_create(request):
    """Create new expense with comprehensive validation"""
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
                    messages.info(request, 'Expense auto-approved based on category threshold.')
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

            # Send notification
            if action == 'submit':
                send_expense_update_notification(expense, 'submitted')
                messages.success(
                    request,
                    f'Expense {expense.expense_number} created and submitted successfully!'
                )
            else:
                messages.success(
                    request,
                    f'Expense {expense.expense_number} saved as draft!'
                )

            # Redirect based on action
            if request.POST.get('save_and_new'):
                return redirect('expenses:expense_create')
            else:
                return redirect('expenses:expense_detail', pk=expense.pk)
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        # Pre-fill expense date with today
        initial = {
            'expense_date': timezone.now().date(),
            'currency': 'UGX'
        }
        form = ExpenseForm(initial=initial, user=request.user)

    context = {
        'form': form,
        'categories': ExpenseCategory.objects.filter(is_active=True).order_by('sort_order', 'name'),
        'title': 'Create Expense',
    }

    return render(request, 'expenses/expense_form.html', context)


@login_required
@transaction.atomic
def expense_edit(request, pk):
    """Edit existing expense (only drafts)"""
    expense = get_object_or_404(Expense, pk=pk, created_by=request.user)

    if expense.status != 'DRAFT':
        messages.error(request, "Only draft expenses can be edited.")
        return redirect('expenses:expense_detail', pk=pk)

    if request.method == 'POST':
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

            log_action(
                request,
                'expense_updated',
                f'Updated expense: {expense.expense_number}',
                content_object=expense
            )

            messages.success(request, 'Expense updated successfully!')

            # Handle submit action
            action = request.POST.get('action', 'save')
            if action == 'submit':
                return redirect('expenses:expense_submit', pk=expense.pk)

            return redirect('expenses:expense_detail', pk=pk)
    else:
        form = ExpenseForm(instance=expense, user=request.user)

    context = {
        'form': form,
        'expense': expense,
        'categories': ExpenseCategory.objects.filter(is_active=True).order_by('sort_order', 'name'),
        'title': 'Edit Expense',
    }

    return render(request, 'expenses/expense_form.html', context)


@login_required
@expense_owner_or_approver_required
def expense_detail(request, pk):
    """View expense details with comprehensive information"""
    expense = get_object_or_404(
        Expense.objects.select_related(
            'category', 'created_by', 'approved_by', 'paid_by', 'store'
        ).prefetch_related('attachments', 'comments__user'),
        pk=pk
    )

    # Get attachments and comments
    attachments = expense.attachments.all()
    comments = expense.comments.select_related('user').order_by('created_at')

    # Filter internal comments for non-approvers
    if not request.user.has_perm('expenses.approve_expense'):
        comments = comments.filter(is_internal=False)

    # Permission checks
    can_edit = can_modify_expense(request.user, expense)
    can_approve = can_approve_expense(request.user, expense)
    can_pay = can_pay_expense(request.user, expense)
    can_delete = expense.status == 'DRAFT' and expense.created_by == request.user

    # Related expenses (same category, similar amount)
    related_expenses = Expense.objects.filter(
        category=expense.category,
        amount__gte=expense.amount * Decimal('0.8'),
        amount__lte=expense.amount * Decimal('1.2')
    ).exclude(pk=expense.pk).select_related('category')[:5]

    # Activity timeline
    timeline = []

    # Created
    timeline.append({
        'date': expense.created_at,
        'action': 'Created',
        'user': expense.created_by,
        'description': 'Expense created as draft'
    })

    # Submitted
    if expense.submitted_at:
        timeline.append({
            'date': expense.submitted_at,
            'action': 'Submitted',
            'user': expense.created_by,
            'description': 'Submitted for approval'
        })

    # Approved
    if expense.approved_at:
        timeline.append({
            'date': expense.approved_at,
            'action': 'Approved',
            'user': expense.approved_by,
            'description': 'Expense approved'
        })

    # Rejected
    if expense.rejected_at:
        timeline.append({
            'date': expense.rejected_at,
            'action': 'Rejected',
            'user': expense.approved_by,
            'description': expense.rejection_reason
        })

    # Paid
    if expense.paid_at:
        timeline.append({
            'date': expense.paid_at,
            'action': 'Paid',
            'user': expense.paid_by,
            'description': f'Paid via {expense.get_payment_method_display()}'
        })

    # Sort timeline
    timeline.sort(key=lambda x: x['date'])

    context = {
        'expense': expense,
        'attachments': attachments,
        'comments': comments,
        'can_approve': can_approve,
        'can_pay': can_pay,
        'can_edit': can_edit,
        'can_delete': can_delete,
        'related_expenses': related_expenses,
        'timeline': timeline,
        'comment_form': ExpenseCommentForm(),
    }

    return render(request, 'expenses/expense_detail.html', context)


@login_required
@require_http_methods(["POST"])
def expense_delete(request, pk):
    """Delete expense (only drafts)"""
    expense = get_object_or_404(Expense, pk=pk, created_by=request.user)

    if expense.status != 'DRAFT':
        messages.error(request, "Only draft expenses can be deleted.")
        return redirect('expenses:expense_detail', pk=pk)

    expense_number = expense.expense_number

    # Delete associated files
    for attachment in expense.attachments.all():
        attachment.file.delete()

    expense.delete()

    log_action(
        request,
        'expense_deleted',
        f'Deleted expense: {expense_number}'
    )

    messages.success(request, f'Expense {expense_number} deleted successfully!')
    return redirect('expenses:expense_list')


# ============================================================================
# EXPENSE WORKFLOW VIEWS
# ============================================================================

@login_required
@require_http_methods(["POST"])
def expense_submit(request, pk):
    """Submit expense for approval with comprehensive validation"""
    expense = get_object_or_404(Expense, pk=pk, created_by=request.user)

    if expense.status != 'DRAFT':
        messages.error(request, "Only draft expenses can be submitted.")
        return redirect('expenses:expense_detail', pk=pk)

    # Validate required fields
    errors = []

    if not expense.attachments.exists() and expense.category.requires_approval:
        errors.append("Please attach receipts before submitting for approval.")

    if not expense.vendor_name:
        errors.append("Vendor name is required.")

    if expense.amount <= 0:
        errors.append("Amount must be greater than zero.")

    if errors:
        for error in errors:
            messages.error(request, error)
        return redirect('expenses:expense_detail', pk=pk)

    try:
        expense.submit_for_approval()

        log_action(
            request,
            'expense_submitted',
            f'Submitted expense {expense.expense_number} for approval',
            content_object=expense
        )

        # Send notification
        send_expense_update_notification(expense, 'submitted')

        messages.success(
            request,
            f'Expense {expense.expense_number} submitted for approval!'
        )
    except ValueError as e:
        messages.error(request, str(e))

    return redirect('expenses:expense_detail', pk=pk)


@login_required
@permission_required('expenses.approve_expense', raise_exception=True)
@require_http_methods(["POST"])
def expense_approve(request, pk):
    """Approve expense with comprehensive validation"""
    expense = get_object_or_404(Expense, pk=pk)

    # Validate approval
    validation = validate_expense_approval(expense, request.user)

    if validation['errors']:
        for error in validation['errors']:
            messages.error(request, error)
        return redirect('expenses:expense_detail', pk=pk)

    # Show warnings if any
    if validation['warnings']:
        for warning in validation['warnings']:
            messages.warning(request, warning)

    try:
        expense.approve(request.user)

        log_action(
            request,
            'expense_approved',
            f'Approved expense {expense.expense_number}',
            content_object=expense
        )

        # Send notification
        send_expense_update_notification(expense, 'approved')

        messages.success(
            request,
            f'Expense {expense.expense_number} approved successfully!'
        )
    except ValueError as e:
        messages.error(request, str(e))

    return redirect('expenses:expense_detail', pk=pk)


@login_required
@permission_required('expenses.reject_expense', raise_exception=True)
@require_http_methods(["POST"])
def expense_reject(request, pk):
    """Reject expense with detailed reason"""
    expense = get_object_or_404(Expense, pk=pk)

    reason = request.POST.get('reason', '').strip()

    if not reason:
        messages.error(request, 'Rejection reason is required.')
        return redirect('expenses:expense_detail', pk=pk)

    if len(reason) < 10:
        messages.error(
            request,
            'Please provide a detailed rejection reason (at least 10 characters).'
        )
        return redirect('expenses:expense_detail', pk=pk)

    try:
        expense.reject(request.user, reason)

        log_action(
            request,
            'expense_rejected',
            f'Rejected expense {expense.expense_number}: {reason}',
            content_object=expense
        )

        # Send notification
        send_expense_update_notification(expense, 'rejected')

        messages.success(request, f'Expense {expense.expense_number} rejected.')
    except ValueError as e:
        messages.error(request, str(e))

    return redirect('expenses:expense_detail', pk=pk)


@login_required
@permission_required('expenses.pay_expense', raise_exception=True)
@require_http_methods(["POST"])
def expense_mark_paid(request, pk):
    """Mark expense as paid with payment details"""
    expense = get_object_or_404(Expense, pk=pk)

    payment_method = request.POST.get('payment_method')
    payment_reference = request.POST.get('payment_reference', '').strip()

    if not payment_method:
        messages.error(request, 'Payment method is required.')
        return redirect('expenses:expense_detail', pk=pk)

    # Validate payment method
    valid_methods = [choice[0] for choice in Expense.PAYMENT_METHODS]
    if payment_method not in valid_methods:
        messages.error(request, 'Invalid payment method.')
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

        # Send notification
        send_expense_update_notification(expense, 'paid')

        messages.success(
            request,
            f'Expense {expense.expense_number} marked as paid!'
        )
    except ValueError as e:
        messages.error(request, str(e))

    return redirect('expenses:expense_detail', pk=pk)


@login_required
@require_http_methods(["POST"])
def expense_cancel(request, pk):
    """Cancel an expense"""
    expense = get_object_or_404(Expense, pk=pk)

    # Check permissions
    can_cancel = (
                         expense.created_by == request.user and expense.status in ['DRAFT', 'SUBMITTED']
                 ) or request.user.has_perm('expenses.delete_expense')

    if not can_cancel:
        messages.error(request, "You don't have permission to cancel this expense.")
        return redirect('expenses:expense_detail', pk=pk)

    if expense.status in ['PAID', 'CANCELLED']:
        messages.error(request, "This expense cannot be cancelled.")
        return redirect('expenses:expense_detail', pk=pk)

    reason = request.POST.get('reason', '').strip()

    expense.status = 'CANCELLED'
    expense.admin_notes = f"Cancelled by {request.user.get_full_name()}: {reason}"
    expense.save(update_fields=['status', 'admin_notes'])

    log_action(
        request,
        'expense_cancelled',
        f'Cancelled expense {expense.expense_number}',
        content_object=expense
    )

    messages.success(request, f'Expense {expense.expense_number} cancelled.')
    return redirect('expenses:expense_detail', pk=pk)


# ============================================================================
# BULK OPERATIONS
# ============================================================================

@login_required
@transaction.atomic
def expense_bulk_action(request):
    """Handle bulk actions for expenses"""
    if request.method == 'POST':
        form = BulkExpenseActionForm(request.POST, user=request.user)

        if form.is_valid():
            expense_ids = form.cleaned_data['expense_ids']
            action = form.cleaned_data['action']

            expenses = Expense.objects.filter(
                id__in=expense_ids,
                created_by=request.user
            )

            success_count = 0
            errors = []

            for expense in expenses:
                try:
                    if action == 'submit':
                        if expense.status == 'DRAFT':
                            expense.submit_for_approval()
                            success_count += 1
                        else:
                            errors.append(f"{expense.expense_number}: Already submitted")

                    elif action == 'delete':
                        if expense.status == 'DRAFT':
                            expense_number = expense.expense_number
                            expense.delete()
                            success_count += 1
                        else:
                            errors.append(
                                f"{expense.expense_number}: Cannot delete non-draft expense"
                            )

                    elif action == 'cancel':
                        if expense.status in ['DRAFT', 'SUBMITTED']:
                            expense.status = 'CANCELLED'
                            expense.save()
                            success_count += 1
                        else:
                            errors.append(
                                f"{expense.expense_number}: Cannot cancel"
                            )

                except Exception as e:
                    errors.append(f"{expense.expense_number}: {str(e)}")

            # Log bulk action
            log_action(
                request,
                'expense_bulk_action',
                f'Bulk {action} on {success_count} expenses'
            )

            if success_count > 0:
                messages.success(
                    request,
                    f'Successfully processed {success_count} expense(s)'
                )

            if errors:
                error_msg = f"Some actions failed: {', '.join(errors[:5])}"
                if len(errors) > 5:
                    error_msg += f" and {len(errors) - 5} more"
                messages.warning(request, error_msg)

            return redirect('expenses:expense_list')
        else:
            messages.error(request, 'Invalid bulk action request.')

    return redirect('expenses:expense_list')


@login_required
@permission_required('expenses.approve_expense', raise_exception=True)
@transaction.atomic
def expense_bulk_approve(request):
    """Bulk approve expenses"""
    if request.method == 'POST':
        expense_ids = request.POST.getlist('expense_ids')

        if not expense_ids:
            messages.error(request, 'No expenses selected.')
            return redirect('expenses:expense_list')

        expenses = Expense.objects.filter(
            id__in=expense_ids,
            status='SUBMITTED'
        ).exclude(created_by=request.user)

        success_count = 0
        errors = []

        for expense in expenses:
            try:
                validation = validate_expense_approval(expense, request.user)
                if not validation['errors']:
                    expense.approve(request.user)
                    send_expense_update_notification(expense, 'approved')
                    success_count += 1
                else:
                    errors.append(f"{expense.expense_number}: {validation['errors'][0]}")
            except Exception as e:
                errors.append(f"{expense.expense_number}: {str(e)}")

        log_action(
            request,
            'expense_bulk_approve',
            f'Bulk approved {success_count} expenses'
        )

        if success_count > 0:
            messages.success(request, f'Successfully approved {success_count} expense(s)')

        if errors:
            messages.warning(request, f'Some approvals failed: {", ".join(errors[:3])}')

        return redirect('expenses:expense_list')

    return redirect('expenses:expense_list')


# ============================================================================
# COMMENTS & ATTACHMENTS
# ============================================================================

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

    form = ExpenseCommentForm(request.POST)

    if form.is_valid():
        comment = form.save(commit=False)
        comment.expense = expense
        comment.user = request.user

        # Only approvers can make internal comments
        if comment.is_internal and not request.user.has_perm('expenses.approve_expense'):
            comment.is_internal = False

        comment.save()

        log_action(
            request,
            'expense_comment_added',
            f'Added comment to expense {expense.expense_number}',
            content_object=expense
        )

        # Send notification
        send_comment_notification(expense, comment)

        messages.success(request, 'Comment added successfully!')
    else:
        messages.error(request, 'Failed to add comment. Please try again.')

    return redirect('expenses:expense_detail', pk=pk)


@login_required
@require_http_methods(["POST"])
def expense_delete_comment(request, pk, comment_id):
    """Delete a comment"""
    expense = get_object_or_404(Expense, pk=pk)
    comment = get_object_or_404(ExpenseComment, pk=comment_id, expense=expense)

    # Only comment author or admins can delete
    if comment.user != request.user and not request.user.is_superuser:
        messages.error(request, "You don't have permission to delete this comment.")
        return redirect('expenses:expense_detail', pk=pk)

    comment.delete()
    messages.success(request, 'Comment deleted successfully.')

    return redirect('expenses:expense_detail', pk=pk)


@login_required
@require_http_methods(["POST"])
@transaction.atomic
def expense_add_attachment(request, pk):
    """Add attachment to expense"""
    expense = get_object_or_404(Expense, pk=pk)

    # Check permissions
    can_add = (
            expense.created_by == request.user or
            request.user.has_perm('expenses.change_expense')
    )

    if not can_add:
        messages.error(request, "You don't have permission to add attachments.")
        return redirect('expenses:expense_detail', pk=pk)

    files = request.FILES.getlist('files')

    if not files:
        messages.error(request, 'No files selected.')
        return redirect('expenses:expense_detail', pk=pk)

    added_count = 0
    for file in files:
        try:
            ExpenseAttachment.objects.create(
                expense=expense,
                file=file,
                uploaded_by=request.user
            )
            added_count += 1
        except Exception as e:
            messages.warning(request, f'Failed to upload {file.name}: {str(e)}')

    if added_count > 0:
        log_action(
            request,
            'expense_attachments_added',
            f'Added {added_count} attachment(s) to expense {expense.expense_number}',
            content_object=expense
        )
        messages.success(request, f'{added_count} attachment(s) added successfully.')

    return redirect('expenses:expense_detail', pk=pk)


@login_required
@require_http_methods(["POST"])
def expense_delete_attachment(request, pk, attachment_id):
    """Delete an attachment"""
    expense = get_object_or_404(Expense, pk=pk)
    attachment = get_object_or_404(ExpenseAttachment, pk=attachment_id, expense=expense)

    # Check permissions
    can_delete = (
            (expense.created_by == request.user and expense.status == 'DRAFT') or
            request.user.has_perm('expenses.delete_expenseattachment')
    )

    if not can_delete:
        messages.error(request, "You don't have permission to delete this attachment.")
        return redirect('expenses:expense_detail', pk=pk)

    if expense.status != 'DRAFT':
        messages.error(request, "Cannot delete attachments from submitted expenses.")
        return redirect('expenses:expense_detail', pk=pk)

    filename = attachment.filename
    attachment.file.delete()
    attachment.delete()

    log_action(
        request,
        'expense_attachment_deleted',
        f'Deleted attachment {filename} from expense {expense.expense_number}',
        content_object=expense
    )

    messages.success(request, 'Attachment deleted successfully.')
    return redirect('expenses:expense_detail', pk=pk)


@login_required
def expense_download_attachment(request, pk, attachment_id):
    """Download an attachment"""
    expense = get_object_or_404(Expense, pk=pk)
    attachment = get_object_or_404(ExpenseAttachment, pk=attachment_id, expense=expense)

    # Check permissions
    can_view = (
            expense.created_by == request.user or
            request.user.has_perm('expenses.view_all_expenses') or
            request.user.has_perm('expenses.approve_expense')
    )

    if not can_view:
        raise PermissionDenied

    response = FileResponse(attachment.file, as_attachment=True)
    response['Content-Disposition'] = f'attachment; filename="{attachment.filename}"'

    return response


# ============================================================================
# REPORTS & ANALYTICS
# ============================================================================

@login_required
@permission_required('expenses.view_all_expenses', raise_exception=True)
def expense_reports(request):
    """View comprehensive expense reports and analytics"""
    # Get date range from request
    date_from_str = request.GET.get('date_from')
    date_to_str = request.GET.get('date_to')

    # Default to current month
    today = timezone.now().date()
    date_from = today.replace(day=1)
    date_to = today

    if date_from_str:
        try:
            date_from = datetime.strptime(date_from_str, '%Y-%m-%d').date()
        except ValueError:
            pass

    if date_to_str:
        try:
            date_to = datetime.strptime(date_to_str, '%Y-%m-%d').date()
        except ValueError:
            pass

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

    # Category-wise breakdown
    expenses = Expense.objects.filter(
        expense_date__gte=date_from,
        expense_date__lte=date_to
    )

    category_breakdown = expenses.values(
        'category__name', 'category__color_code'
    ).annotate(
        total_amount=Sum('amount'),
        count=Count('id'),
        avg_amount=Avg('amount')
    ).order_by('-total_amount')

    # Store-wise breakdown
    store_breakdown = expenses.exclude(
        store__isnull=True
    ).values(
        'store__name'
    ).annotate(
        total_amount=Sum('amount'),
        count=Count('id')
    ).order_by('-total_amount')

    # Monthly trend
    monthly_trend = expenses.annotate(
        month=TruncMonth('expense_date')
    ).values('month').annotate(
        total=Sum('amount'),
        count=Count('id')
    ).order_by('month')

    # Top vendors
    top_vendors = expenses.exclude(
        vendor_name=''
    ).values('vendor_name').annotate(
        total=Sum('amount'),
        count=Count('id')
    ).order_by('-total')[:10]

    # Status distribution
    status_distribution = expenses.values('status').annotate(
        count=Count('id'),
        total=Sum('amount')
    ).order_by('-count')

    context = {
        'stats': stats,
        'insights': insights,
        'budget_analysis': budget_analysis,
        'category_breakdown': category_breakdown,
        'store_breakdown': store_breakdown,
        'monthly_trend': monthly_trend,
        'top_vendors': top_vendors,
        'status_distribution': status_distribution,
        'date_from': date_from,
        'date_to': date_to,
    }

    return render(request, 'expenses/reports.html', context)


@login_required
def expense_export_excel(request):
    """Export expenses to Excel"""
    from .tasks import export_expenses_to_excel_task

    filters = request.GET.dict()

    # Queue export task
    result = export_expenses_to_excel_task.delay(request.user.id, filters)

    messages.success(
        request,
        'Export has been queued. You will receive a notification when it\'s ready.'
    )

    return redirect('expenses:expense_list')


@login_required
def expense_export_pdf(request):
    """Export expenses to PDF"""
    # Get filtered expenses
    expenses = Expense.objects.select_related(
        'category', 'created_by', 'store'
    )

    # Apply user filter
    if not request.user.has_perm('expenses.view_all_expenses'):
        expenses = expenses.filter(created_by=request.user)

    # Apply filters from request
    status = request.GET.get('status')
    category_id = request.GET.get('category')
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')

    if status:
        expenses = expenses.filter(status=status)
    if category_id:
        expenses = expenses.filter(category_id=category_id)
    if date_from:
        expenses = expenses.filter(expense_date__gte=date_from)
    if date_to:
        expenses = expenses.filter(expense_date__lte=date_to)

    # Limit to prevent large PDFs
    expenses = expenses.order_by('-expense_date')[:100]

    # Generate PDF
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    elements = []

    # Styles
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=24,
        textColor=colors.HexColor('#1a237e'),
        spaceAfter=30,
        alignment=TA_CENTER
    )

    # Title
    title = Paragraph("Expense Report", title_style)
    elements.append(title)
    elements.append(Spacer(1, 12))

    # Summary info
    summary_data = [
        ['Report Generated:', timezone.now().strftime('%Y-%m-%d %H:%M')],
        ['Total Expenses:', str(expenses.count())],
        ['Total Amount:', f"UGX {expenses.aggregate(Sum('amount'))['amount__sum'] or 0:,.2f}"],
    ]

    summary_table = Table(summary_data, colWidths=[2 * inch, 4 * inch])
    summary_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.grey),
        ('TEXTCOLOR', (0, 0), (0, -1), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
        ('GRID', (0, 0), (-1, -1), 1, colors.black)
    ]))

    elements.append(summary_table)
    elements.append(Spacer(1, 20))

    # Expense table
    if expenses.exists():
        data = [['#', 'Date', 'Description', 'Category', 'Amount', 'Status']]

        for i, expense in enumerate(expenses, 1):
            data.append([
                str(i),
                expense.expense_date.strftime('%Y-%m-%d'),
                expense.title[:30],
                expense.category.name[:20],
                f"{expense.amount:,.2f}",
                expense.get_status_display()
            ])

        table = Table(data, colWidths=[0.5 * inch, 1 * inch, 2 * inch, 1.5 * inch, 1 * inch, 1 * inch])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 1), (-1, -1), 8),
        ]))

        elements.append(table)
    else:
        elements.append(Paragraph("No expenses found for the selected criteria.", styles['Normal']))

    # Build PDF
    doc.build(elements)

    # Return response
    buffer.seek(0)
    response = HttpResponse(buffer, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="expenses_{timezone.now().strftime("%Y%m%d")}.pdf"'

    return response


@login_required
def expense_print(request, pk):
    """Generate printable expense report"""
    expense = get_object_or_404(
        Expense.objects.select_related(
            'category', 'created_by', 'approved_by', 'paid_by', 'store'
        ).prefetch_related('attachments'),
        pk=pk
    )

    # Check permissions
    can_view = (
            expense.created_by == request.user or
            request.user.has_perm('expenses.view_all_expenses') or
            request.user.has_perm('expenses.approve_expense')
    )

    if not can_view:
        raise PermissionDenied

    context = {
        'expense': expense,
        'print_date': timezone.now(),
    }

    return render(request, 'expenses/expense_print.html', context)


# ============================================================================
# API ENDPOINTS (AJAX)
# ============================================================================

@login_required
def expense_quick_stats(request):
    """Get quick stats for dashboard widgets"""
    today = timezone.now().date()
    start_of_month = today.replace(day=1)

    user_expenses = Expense.objects.filter(created_by=request.user)
    month_expenses = user_expenses.filter(
        expense_date__gte=start_of_month,
        expense_date__lte=today
    )

    stats = {
        'total_this_month': float(
            month_expenses.aggregate(Sum('amount'))['amount__sum'] or 0
        ),
        'pending_approval': user_expenses.filter(status='SUBMITTED').count(),
        'approved_unpaid': user_expenses.filter(status='APPROVED').count(),
        'recent_submissions': user_expenses.filter(
            submitted_at__gte=timezone.now() - timedelta(days=7)
        ).count(),
        'overdue': user_expenses.filter(
            status='APPROVED',
            due_date__lt=today
        ).count()
    }

    return JsonResponse(stats)


@login_required
def expense_category_summary(request):
    """Get category-wise summary for charts"""
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')

    expenses = Expense.objects.filter(created_by=request.user)

    if date_from:
        expenses = expenses.filter(expense_date__gte=date_from)
    if date_to:
        expenses = expenses.filter(expense_date__lte=date_to)

    summary = expenses.values(
        'category__name', 'category__color_code'
    ).annotate(
        total=Sum('amount'),
        count=Count('id')
    ).order_by('-total')

    data = {
        'labels': [item['category__name'] for item in summary],
        'datasets': [{
            'label': 'Total Amount',
            'data': [float(item['total']) for item in summary],
            'backgroundColor': [item['category__color_code'] for item in summary],
        }],
        'counts': [item['count'] for item in summary]
    }

    return JsonResponse(data)


@login_required
def expense_monthly_trend(request):
    """Get monthly expense trend"""
    months = int(request.GET.get('months', 6))

    start_date = timezone.now().date() - timedelta(days=months * 30)

    expenses = Expense.objects.filter(
        created_by=request.user,
        expense_date__gte=start_date
    ).annotate(
        month=TruncMonth('expense_date')
    ).values('month').annotate(
        total=Sum('amount'),
        count=Count('id')
    ).order_by('month')

    data = {
        'labels': [item['month'].strftime('%b %Y') for item in expenses],
        'datasets': [{
            'label': 'Total Amount',
            'data': [float(item['total']) for item in expenses],
            'borderColor': '#1976d2',
            'backgroundColor': 'rgba(25, 118, 210, 0.1)',
        }],
        'counts': [item['count'] for item in expenses]
    }

    return JsonResponse(data)


@login_required
def expense_status_distribution(request):
    """Get expense status distribution"""
    expenses = Expense.objects.filter(created_by=request.user)

    distribution = expenses.values('status').annotate(
        count=Count('id'),
        total=Sum('amount')
    ).order_by('status')

    status_colors = {
        'DRAFT': '#9e9e9e',
        'SUBMITTED': '#2196f3',
        'APPROVED': '#4caf50',
        'REJECTED': '#f44336',
        'PAID': '#00897b',
        'CANCELLED': '#757575',
    }

    data = {
        'labels': [item['status'] for item in distribution],
        'datasets': [{
            'data': [item['count'] for item in distribution],
            'backgroundColor': [
                status_colors.get(item['status'], '#9e9e9e')
                for item in distribution
            ],
        }],
        'amounts': [float(item['total'] or 0) for item in distribution]
    }

    return JsonResponse(data)


@login_required
def expense_search_api(request):
    """Search expenses via AJAX"""
    query = request.GET.get('q', '').strip()

    if len(query) < 2:
        return JsonResponse({'results': []})

    expenses = Expense.objects.filter(
        created_by=request.user
    ).filter(
        Q(expense_number__icontains=query) |
        Q(title__icontains=query) |
        Q(vendor_name__icontains=query) |
        Q(reference_number__icontains=query)
    ).select_related('category')[:10]

    results = [
        {
            'id': exp.id,
            'expense_number': exp.expense_number,
            'title': exp.title,
            'amount': float(exp.amount),
            'currency': exp.currency,
            'status': exp.status,
            'category': exp.category.name,
            'date': exp.expense_date.isoformat(),
        }
        for exp in expenses
    ]

    return JsonResponse({'results': results})


@login_required
def expense_validate_api(request):
    """Validate expense data via AJAX"""
    amount = request.GET.get('amount')
    category_id = request.GET.get('category_id')

    validation = {
        'is_valid': True,
        'warnings': [],
        'errors': []
    }

    try:
        amount = Decimal(amount)

        if amount <= 0:
            validation['is_valid'] = False
            validation['errors'].append('Amount must be greater than zero')

        if category_id:
            try:
                category = ExpenseCategory.objects.get(id=category_id)

                # Check against monthly budget
                if category.monthly_budget:
                    spent_this_month = category.get_monthly_spent()
                    if spent_this_month + amount > category.monthly_budget:
                        validation['warnings'].append(
                            f'This expense will exceed the monthly budget for {category.name}'
                        )

                # Check approval threshold
                if category.approval_threshold and amount >= category.approval_threshold:
                    validation['warnings'].append(
                        f'This expense requires approval (threshold: {category.approval_threshold})'
                    )

            except ExpenseCategory.DoesNotExist:
                validation['is_valid'] = False
                validation['errors'].append('Invalid category')

    except (ValueError, TypeError, InvalidOperation):
        validation['is_valid'] = False
        validation['errors'].append('Invalid amount')

    return JsonResponse(validation)


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def send_expense_update_notification(expense, update_type):
    """Send real-time update via WebSocket"""
    from channels.layers import get_channel_layer
    from asgiref.sync import async_to_sync

    channel_layer = get_channel_layer()

    if not channel_layer:
        return

    # Notify expense creator
    try:
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
    except Exception as e:
        print(f"Error sending notification: {e}")

    # Notify approvers if submitted
    if update_type == 'submitted':
        try:
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
        except Exception as e:
            print(f"Error sending approver notification: {e}")


def send_comment_notification(expense, comment):
    """Send notification about new comment"""
    from channels.layers import get_channel_layer
    from asgiref.sync import async_to_sync

    channel_layer = get_channel_layer()

    if not channel_layer:
        return

    try:
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
    except Exception as e:
        print(f"Error sending comment notification: {e}")


# ============================================================================
# CATEGORY MANAGEMENT VIEWS (Class-Based Views)
# ============================================================================

class ExpenseCategoryListView(LoginRequiredMixin, PermissionRequiredMixin, ListView):
    model = ExpenseCategory
    template_name = 'expenses/category_list.html'
    context_object_name = 'categories'
    permission_required = 'expenses.view_expensecategory'
    paginate_by = 50

    def get_queryset(self):
        queryset = ExpenseCategory.objects.annotate(
            expense_count=Count('expenses'),
            total_spent=Coalesce(Sum('expenses__amount'), Decimal('0'))
        ).order_by('sort_order', 'name')

        # Filter by active status
        is_active = self.request.GET.get('is_active')
        if is_active == 'true':
            queryset = queryset.filter(is_active=True)
        elif is_active == 'false':
            queryset = queryset.filter(is_active=False)

        # Search
        search = self.request.GET.get('search')
        if search:
            queryset = queryset.filter(
                Q(name__icontains=search) |
                Q(code__icontains=search) |
                Q(description__icontains=search)
            )

        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['active_categories'] = self.get_queryset().filter(is_active=True).count()
        context['inactive_categories'] = self.get_queryset().filter(is_active=False).count()
        context['total_categories'] = self.get_queryset().count()
        return context


class ExpenseCategoryCreateView(LoginRequiredMixin, PermissionRequiredMixin, CreateView):
    model = ExpenseCategory
    template_name = 'expenses/category_form.html'
    fields = [
        'name', 'code', 'description', 'gl_account', 'monthly_budget',
        'requires_approval', 'approval_threshold', 'color_code', 'icon',
        'is_active', 'sort_order'
    ]
    permission_required = 'expenses.add_expensecategory'
    success_url = reverse_lazy('expenses:category_list')

    def form_valid(self, form):
        response = super().form_valid(form)

        log_action(
            self.request,
            'category_created',
            f'Created expense category: {self.object.name}',
            content_object=self.object
        )

        messages.success(
            self.request,
            f'Category "{self.object.name}" created successfully!'
        )

        return response

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Create Category'
        context['submit_text'] = 'Create Category'
        return context


class ExpenseCategoryUpdateView(LoginRequiredMixin, PermissionRequiredMixin, UpdateView):
    model = ExpenseCategory
    template_name = 'expenses/category_form.html'
    fields = [
        'name', 'code', 'description', 'gl_account', 'monthly_budget',
        'requires_approval', 'approval_threshold', 'color_code', 'icon',
        'is_active', 'sort_order'
    ]
    permission_required = 'expenses.change_expensecategory'
    success_url = reverse_lazy('expenses:category_list')

    def form_valid(self, form):
        response = super().form_valid(form)

        log_action(
            self.request,
            'category_updated',
            f'Updated expense category: {self.object.name}',
            content_object=self.object
        )

        messages.success(
            self.request,
            f'Category "{self.object.name}" updated successfully!'
        )

        return response

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Edit Category'
        context['submit_text'] = 'Update Category'
        return context


class ExpenseCategoryDeleteView(LoginRequiredMixin, PermissionRequiredMixin, DeleteView):
    model = ExpenseCategory
    template_name = 'expenses/category_confirm_delete.html'
    permission_required = 'expenses.delete_expensecategory'
    success_url = reverse_lazy('expenses:category_list')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['expense_count'] = self.object.expenses.count()
        return context

    def delete(self, request, *args, **kwargs):
        category = self.get_object()

        # Check if category has expenses
        if category.expenses.exists():
            messages.error(
                request,
                f'Cannot delete category "{category.name}" because it has '
                f'{category.expenses.count()} associated expense(s). '
                f'You can deactivate it instead.'
            )
            return redirect('expenses:category_list')

        category_name = category.name
        response = super().delete(request, *args, **kwargs)

        log_action(
            request,
            'category_deleted',
            f'Deleted expense category: {category_name}'
        )

        messages.success(request, f'Category "{category_name}" deleted successfully!')
        return response


class ExpenseCategoryDetailView(LoginRequiredMixin, PermissionRequiredMixin, DetailView):
    model = ExpenseCategory
    template_name = 'expenses/category_detail.html'
    context_object_name = 'category'
    permission_required = 'expenses.view_expensecategory'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        category = self.object

        # Get expenses for this category
        expenses = category.expenses.select_related(
            'created_by', 'store'
        ).order_by('-expense_date')[:20]

        # Statistics
        total_expenses = category.expenses.count()
        total_amount = category.expenses.aggregate(
            Sum('amount')
        )['amount__sum'] or Decimal('0')

        # Monthly statistics
        today = timezone.now().date()
        start_of_month = today.replace(day=1)

        monthly_stats = category.expenses.filter(
            expense_date__gte=start_of_month,
            expense_date__lte=today
        ).aggregate(
            count=Count('id'),
            total=Sum('amount'),
            avg=Avg('amount')
        )

        # Budget utilization
        budget_utilization = None
        if category.monthly_budget:
            spent = category.get_monthly_spent()
            percentage = (spent / category.monthly_budget * 100) if category.monthly_budget > 0 else 0
            budget_utilization = {
                'spent': spent,
                'budget': category.monthly_budget,
                'percentage': percentage,
                'remaining': category.monthly_budget - spent,
                'is_over': spent > category.monthly_budget
            }

        # Monthly trend (last 6 months)
        six_months_ago = today - timedelta(days=180)
        monthly_trend = category.expenses.filter(
            expense_date__gte=six_months_ago
        ).annotate(
            month=TruncMonth('expense_date')
        ).values('month').annotate(
            total=Sum('amount'),
            count=Count('id')
        ).order_by('month')

        context.update({
            'expenses': expenses,
            'total_expenses': total_expenses,
            'total_amount': total_amount,
            'monthly_stats': monthly_stats,
            'budget_utilization': budget_utilization,
            'monthly_trend': monthly_trend,
        })

        return context


@login_required
@permission_required('expenses.change_expensecategory')
@require_http_methods(["POST"])
def category_toggle_active(request, pk):
    """Toggle category active status"""
    category = get_object_or_404(ExpenseCategory, pk=pk)

    category.is_active = not category.is_active
    category.save(update_fields=['is_active'])

    action = 'activated' if category.is_active else 'deactivated'

    log_action(
        request,
        'category_updated',
        f'{action.capitalize()} expense category: {category.name}',
        content_object=category
    )

    messages.success(request, f'Category "{category.name}" {action} successfully!')

    # Return JSON for AJAX requests
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({
            'success': True,
            'is_active': category.is_active,
            'message': f'Category {action} successfully!'
        })

    return redirect('expenses:category_list')


@login_required
def category_expenses(request, pk):
    """View expenses for a specific category"""
    category = get_object_or_404(ExpenseCategory, pk=pk)

    # Check permissions - users can only see their own expenses unless they have view_all permission
    if request.user.has_perm('expenses.view_all_expenses'):
        expenses = Expense.objects.filter(category=category)
    else:
        expenses = Expense.objects.filter(category=category, created_by=request.user)

    expenses = expenses.select_related('created_by', 'store', 'approved_by')

    # Apply filters
    status_filter = request.GET.get('status')
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')

    if status_filter:
        expenses = expenses.filter(status=status_filter)
    if date_from:
        expenses = expenses.filter(expense_date__gte=date_from)
    if date_to:
        expenses = expenses.filter(expense_date__lte=date_to)

    # Pagination
    paginator = Paginator(expenses.order_by('-expense_date'), 25)
    page = request.GET.get('page')

    try:
        expenses_page = paginator.page(page)
    except PageNotAnInteger:
        expenses_page = paginator.page(1)
    except EmptyPage:
        expenses_page = paginator.page(paginator.num_pages)

    # Statistics
    stats = {
        'total_expenses': expenses.count(),
        'total_amount': expenses.aggregate(Sum('amount'))['amount__sum'] or Decimal('0'),
        'approved_amount': expenses.filter(
            status__in=['APPROVED', 'PAID']
        ).aggregate(Sum('amount'))['amount__sum'] or Decimal('0'),
        'paid_amount': expenses.filter(status='PAID').aggregate(Sum('amount'))['amount__sum'] or Decimal('0'),
        'average_amount': expenses.aggregate(Avg('amount'))['amount__avg'] or Decimal('0'),
    }

    # Budget utilization
    budget_utilization = None
    if category.monthly_budget:
        current_month_spent = category.get_monthly_spent()
        budget_utilization = {
            'spent': current_month_spent,
            'budget': category.monthly_budget,
            'percentage': (current_month_spent / category.monthly_budget * 100) if category.monthly_budget > 0 else 0,
            'remaining': category.monthly_budget - current_month_spent,
            'is_over': current_month_spent > category.monthly_budget
        }

    context = {
        'category': category,
        'expenses': expenses_page,
        'stats': stats,
        'budget_utilization': budget_utilization,
        'status_choices': Expense.STATUS_CHOICES,
    }

    return render(request, 'expenses/category_expenses.html', context)


@login_required
@permission_required('expenses.view_expensecategory')
def category_budget_report(request):
    """Budget utilization report across all categories"""
    categories = ExpenseCategory.objects.filter(
        monthly_budget__isnull=False,
        monthly_budget__gt=0
    ).order_by('sort_order', 'name')

    # Calculate utilization for each category
    budget_data = []
    for category in categories:
        spent = category.get_monthly_spent()
        budget = category.monthly_budget
        percentage = (spent / budget * 100) if budget > 0 else 0

        budget_data.append({
            'category': category,
            'spent': spent,
            'budget': budget,
            'percentage': percentage,
            'remaining': budget - spent,
            'is_over_budget': spent > budget,
            'variance': spent - budget
        })

    # Sort by percentage (highest utilization first)
    budget_data.sort(key=lambda x: x['percentage'], reverse=True)

    # Overall statistics
    total_budget = sum(item['budget'] for item in budget_data)
    total_spent = sum(item['spent'] for item in budget_data)
    overall_percentage = (total_spent / total_budget * 100) if total_budget > 0 else 0

    context = {
        'budget_data': budget_data,
        'total_budget': total_budget,
        'total_spent': total_spent,
        'total_remaining': total_budget - total_spent,
        'overall_percentage': overall_percentage,
        'over_budget_categories': [item for item in budget_data if item['is_over_budget']],
        'categories_count': len(budget_data),
    }

    return render(request, 'expenses/category_budget_report.html', context)


# ============================================================================
# CATEGORY API ENDPOINTS
# ============================================================================

@login_required
@require_http_methods(["GET"])
def category_list_api(request):
    """Get list of categories for dropdowns"""
    categories = ExpenseCategory.objects.filter(is_active=True).order_by('sort_order', 'name')

    data = [
        {
            'id': category.id,
            'name': category.name,
            'code': category.code,
            'color_code': category.color_code,
            'icon': category.icon,
            'monthly_budget': float(category.monthly_budget) if category.monthly_budget else None,
            'requires_approval': category.requires_approval,
            'approval_threshold': float(category.approval_threshold) if category.approval_threshold else None,
            'description': category.description,
        }
        for category in categories
    ]

    return JsonResponse({'categories': data})


@login_required
@require_http_methods(["GET"])
def category_budget_utilization_api(request, pk):
    """Get budget utilization data for a specific category"""
    category = get_object_or_404(ExpenseCategory, pk=pk)

    # Get date range from request (default to current month)
    year = request.GET.get('year', timezone.now().year)
    month = request.GET.get('month', timezone.now().month)

    try:
        year = int(year)
        month = int(month)
    except (ValueError, TypeError):
        return JsonResponse({'error': 'Invalid year or month'}, status=400)

    # Calculate spent amount for the specified month
    spent = category.expenses.filter(
        expense_date__year=year,
        expense_date__month=month,
        status__in=['APPROVED', 'PAID']
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

    budget = category.monthly_budget or Decimal('0')
    utilization_percentage = (float(spent) / float(budget) * 100) if budget > 0 else 0

    data = {
        'category': {
            'id': category.id,
            'name': category.name,
            'code': category.code,
            'budget': float(budget),
        },
        'period': {
            'year': year,
            'month': month,
            'month_name': datetime(year, month, 1).strftime('%B')
        },
        'utilization': {
            'spent': float(spent),
            'remaining': float(budget - spent),
            'percentage': utilization_percentage,
            'is_over_budget': spent > budget
        }
    }

    return JsonResponse(data)


@login_required
@permission_required('expenses.view_expensecategory')
def category_usage_stats_api(request):
    """Get category usage statistics"""
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')

    # Build base queryset
    expenses = Expense.objects.all()

    if not request.user.has_perm('expenses.view_all_expenses'):
        expenses = expenses.filter(created_by=request.user)

    if date_from:
        expenses = expenses.filter(expense_date__gte=date_from)
    if date_to:
        expenses = expenses.filter(expense_date__lte=date_to)

    # Get category statistics
    category_stats = expenses.values(
        'category__id', 'category__name', 'category__color_code'
    ).annotate(
        total_amount=Sum('amount'),
        expense_count=Count('id'),
        avg_amount=Avg('amount')
    ).order_by('-total_amount')

    data = {
        'categories': [
            {
                'id': stat['category__id'],
                'name': stat['category__name'],
                'color_code': stat['category__color_code'],
                'total_amount': float(stat['total_amount'] or 0),
                'expense_count': stat['expense_count'],
                'avg_amount': float(stat['avg_amount'] or 0),
            }
            for stat in category_stats
        ],
        'summary': {
            'total_categories': len(category_stats),
            'total_amount': float(sum(stat['total_amount'] or 0 for stat in category_stats)),
            'total_expenses': sum(stat['expense_count'] for stat in category_stats)
        }
    }

    return JsonResponse(data)